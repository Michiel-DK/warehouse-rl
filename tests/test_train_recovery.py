"""Tests for scripts/train_recovery.py (smoke mode only; the real training is a scheduler item). Each case names its
red-demonstration in an `# inject:` comment."""
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate as ev
import train_recovery as tr
from warehouse_rl import learned_recovery as lr

SCRIPT = str(ROOT / "scripts" / "train_recovery.py")
MEDIUM = "tarware-medium-8agvs-4pickers-globalobs-v1"


def run(args, results_dir, env=None):
    return subprocess.run([sys.executable, SCRIPT, *args, "--results-dir", str(results_dir)], capture_output=True,
                          text=True, timeout=600, env=env)


def snapshot(d):
    return {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in sorted(Path(d).iterdir())}


class TestWindowRecorder(unittest.TestCase):
    # inject: put the decision step outside the window (k in (t, t']), drop the discount exponent, or charge the
    # call-human penalty without the cost factor
    def test_hand_computed_windows(self):
        c = dict(line_reward=1.0, stuck_penalty=0.1, gamma=0.5, call_human_cost=10)
        rec = tr.WindowRecorder(c, n_agents=2)
        x0, x1, x2 = (np.full(12, v, np.float32) for v in (0.0, 1.0, 2.0))
        rec.decision(7, 1, x0, 3)                                   # agent 7 decides at step 1
        rec.step_end(1, 2, {7}, set())                              # r = 2/2 - 0.1            = 0.9
        rec.step_end(2, 0, {7}, {7})                                # r = -0.1 - 0.1 * 10      = -1.1
        rec.decision(7, 3, x1, 4)                                   # next decision at step 3: Delta 2
        rec.decision(7, 3, x2, 0)                                   # second decision, same step: Delta 0
        rec.step_end(3, 0, set(), set())                            # r = 0
        rec.step_end(4, 1, set(), set())                            # r = 1/2 = 0.5, weight 0.5**(4-3)
        rec.finish(5)
        (a, b, d) = rec.out
        self.assertEqual((a[1], a[6], a[7], a[8], a[5]), (3, 7, 1, 2, False))
        self.assertAlmostEqual(a[2], 0.9 + 0.5 * -1.1)              # 0.35
        self.assertAlmostEqual(a[3], 0.25)                          # gamma ** Delta
        np.testing.assert_array_equal(a[4], x1)
        self.assertEqual((b[1], b[8], b[2], b[3], b[5]), (4, 0, 0.0, 1.0, False))   # Delta 0: no reward, discount 1
        np.testing.assert_array_equal(b[4], x2)
        self.assertEqual((d[1], d[8], d[5]), (0, 2, True))                         # closed by the episode end
        self.assertAlmostEqual(d[2], 0.0 + 0.5 * 0.5)               # step 3: 0, step 4: 0.5 * 0.5**1
        self.assertAlmostEqual(a[9], 0.9 - 1.1)                     # undiscounted return, used for the log only


class TestRolloutReward(unittest.TestCase):
    def episode(self, consts, steps=120, seed=3, **kw):
        torch.manual_seed(11)
        sd = lr.QNet().state_dict()
        cfg = {"breakdown": {"rate_per_hour": 8, "duration": [20, 60], "agent_types": ["agv"]}}
        task = dict(state_dict=sd, epsilon=0.5, explore_seed=seed, env_id=MEDIUM, disturb=cfg, steps=steps,
                    seed=seed, call_human_cost=consts["call_human_cost"], consts=consts, collect=True, trace=True)
        task.update(kw)
        return tr.run_episode(task)

    def reference(self, res, consts, n_agents=12):
        """Independent recomputation of every transition's reward from the recorded per-step trace."""
        trace = {t["k"]: t for t in res["trace"]}
        out = []
        for aid, t0, delta in zip(res["AID"], res["T0"], res["DELTA"]):
            total = 0.0
            for k in range(int(t0), int(t0) + int(delta)):
                st = trace[k]
                r = consts["line_reward"] * st["deliveries"] / n_agents
                r -= consts["stuck_penalty"] * (int(aid) in st["stuck"])
                r -= consts["stuck_penalty"] * consts["call_human_cost"] * (int(aid) in st["relocated"])
                total += consts["gamma"] ** (k - int(t0)) * r
            out.append(total)
        return np.array(out)

    # inject: change the window to (t, t'], read the env reward, or ignore the passed constants
    def test_trainer_reward_equals_reference_from_trace(self):
        for consts in (lr.reward_constants(),
                       dict(line_reward=2.0, stuck_penalty=0.5, gamma=0.9, call_human_cost=7)):
            res = self.episode(consts)
            self.assertEqual(res["reward_used"], consts)
            self.assertGreater(len(res["A"]), 50)
            np.testing.assert_allclose(res["R"], self.reference(res, consts), atol=1e-9)
            np.testing.assert_allclose(res["DISC"], consts["gamma"] ** res["DELTA"], atol=1e-12)
            self.assertEqual(res["busy_stuck_mismatch"], 0)  # recorder's stuck flag == info["stuck_busy_agents"]
            zero = res["DELTA"] == 0
            self.assertTrue(np.all(res["R"][zero] == 0.0) and np.all(res["DISC"][zero] == 1.0))
            self.assertTrue(np.any(res["R"] != 0.0))
        # the stuck penalty really enters: a 0.5 penalty makes the total strictly lower than at 0.01 (same actions)
        lo = self.episode(lr.reward_constants())["R"].sum()
        hi = self.episode(dict(lr.reward_constants(), stuck_penalty=0.5))["R"].sum()
        self.assertLess(hi, lo)

    # inject: count one decision per call twice, or lose a transition at the episode end
    def test_decision_accounting_and_windows_tile(self):
        res = self.episode(lr.reward_constants())
        self.assertEqual(res["policy_calls"], res["hook_decide_calls"])
        self.assertEqual(res["policy_calls"], res["decisions"])
        self.assertEqual(len(res["A"]), res["decisions"])  # one transition per decision, none dropped
        for aid in set(res["AID"].tolist()):  # per agent: each window ends where the next begins, the last at the end
            m = res["AID"] == aid
            starts, ends = res["T0"][m], res["T0"][m] + res["DELTA"][m]
            order = np.argsort(starts, kind="stable")
            self.assertTrue(np.all(starts[order][1:] == ends[order][:-1]))
            self.assertEqual(int(ends[order][-1]), 120)
            self.assertTrue(res["DONE"][m][order][-1] and not res["DONE"][m][order][:-1].any())

    # inject: ship epsilon-greedy actions in the evaluation, or instrument the hook there
    def test_eval_equals_evaluate_run_seed(self):
        with tempfile.TemporaryDirectory() as d:
            ck = Path(d) / "c.pt"
            torch.manual_seed(5)
            sd = lr.QNet().state_dict()
            lr.save_checkpoint(ck, sd, lr.reward_constants(), {"x": 1})
            cfg = tr.point_spec("breakdown", 2)[1]
            res = tr.run_episode(dict(state_dict=sd, epsilon=0.0, explore_seed=0, env_id=MEDIUM, disturb=cfg,
                                      steps=100, seed=1000, call_human_cost=60, consts=lr.reward_constants(),
                                      collect=False))
            row = ev.run_seed("stuck_aware_cta", MEDIUM, 100, 1000, disturb=cfg, recovery=lr.learned_config(ck))
        self.assertEqual(res["pick_rate"], row["pick_rate"])
        self.assertEqual(res["decisions"], row["recovery_stuck_events"] + row["recovery_clash_events"])


class TestUnits(unittest.TestCase):
    # inject: off-by-one in the horizon or a wrong floor
    def test_epsilon_schedule(self):
        self.assertEqual(tr.epsilon_at(0, 100), 1.0)
        self.assertAlmostEqual(tr.epsilon_at(25, 100), 0.5 * (1.0 + 0.05), places=9)
        self.assertAlmostEqual(tr.epsilon_at(50, 100), 0.05, places=9)
        self.assertAlmostEqual(tr.epsilon_at(99, 100), 0.05, places=9)

    # inject: take the max from the target net (vanilla DQN) instead of the online argmax
    def test_double_dqn_target_uses_online_argmax(self):
        class Fixed(torch.nn.Module):
            def __init__(self, q):
                super().__init__()
                self.q = torch.tensor(q, dtype=torch.float32)
                self.w = torch.nn.Parameter(torch.zeros(1))

            def forward(self, x):
                return self.q.expand(x.shape[0], -1) + self.w

        online, target = Fixed([0.0, 5.0, 0.0, 0.0, 0.0]), Fixed([9.0, 1.0, 0.0, 0.0, 0.0])
        x = torch.zeros(1, 12)
        batch = (x, torch.tensor([0]), torch.tensor([1.0]), torch.tensor([0.5]), x, torch.tensor([0.0]))
        # target value = target(s')[argmax online] = 1.0 -> y = 1 + 0.5 * 1 = 1.5; q(s, a=0) = 0
        loss = tr.dqn_loss(online, target, batch)
        self.assertAlmostEqual(float(loss.detach()), 1.0, places=6)  # Huber(0 - 1.5) = 1.5 - 0.5 = 1.0
        done = batch[:5] + (torch.tensor([1.0]),)
        self.assertAlmostEqual(float(tr.dqn_loss(online, target, done).detach()), 0.5, places=6)  # y = 1.0 -> 0.5 * 1

    # inject: read SCHED_WORKERS before --workers, or skip the cap
    def test_worker_resolution(self):
        seen = []

        def fake(rate, run_seed, steps, episodes, smoke, workers, results_dir, resume, max_intervals=None):
            seen.append(workers)
            return dict(status="stopped")

        def go(argv, sched):
            with mock.patch.object(tr, "train_run", fake), mock.patch.object(sys, "argv", ["train_recovery", *argv]), \
                    mock.patch.dict(os.environ):
                os.environ.pop("SCHED_WORKERS", None)
                if sched is not None:
                    os.environ["SCHED_WORKERS"] = sched
                tr.main()

        with tempfile.TemporaryDirectory() as d:
            base = ["--rates", "1", "--seeds", "0", "--results-dir", d]
            go(base + ["--workers", "3"], "5")
            go(base, "5")
            go(base + ["--workers", ""], "4")
            go(base, None)
            go(base + ["--workers", "50"], None)
        self.assertEqual(seen[:3], [3, 5, 4])
        self.assertEqual(seen[3], min(tr.ITER_EPISODES, max(1, (os.cpu_count() or 3) - 2)))
        self.assertEqual(seen[4], tr.ITER_EPISODES)

    # inject: let training episode seeds reach 0-29 or the eval seeds
    def test_seed_ranges_disjoint(self):
        self.assertEqual(tr.EVAL_SEEDS, [1000, 1001, 1002, 1003, 1004])
        for run_seed in (0, 1, 2, 7):
            train = {tr.TRAIN_SEED_BASE + tr.TRAIN_SEED_STRIDE * run_seed + e for e in range(0, tr.MAX_EPISODES, 997)}
            self.assertFalse(train & set(range(30)))
            self.assertFalse(train & set(tr.EVAL_SEEDS))

    def test_defaults(self):
        out = subprocess.run([sys.executable, SCRIPT, "--help"], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0)
        self.assertEqual((tr.DEFAULT_RATES, tr.DEFAULT_SEEDS), ("1,2,4", "0,1,2"))
        self.assertEqual(tr.parse_rates(tr.DEFAULT_RATES), [1, 2, 4])


class TestSmokeTrainAndResume(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.args = ["--smoke", "--steps", "100", "--workers", "2"]
        cls.first = run(cls.args, cls.dir)
        cls.run_dir = cls.dir / "rate1_seed0"

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    # inject: smoke trains 0 episodes, never reaches the warm-up (0 gradient steps), or omits a log field
    def test_smoke_files_and_log(self):
        self.assertEqual(self.first.returncode, 0, self.first.stderr)
        self.assertTrue((self.run_dir / "checkpoint.pt").exists())
        log = json.loads((self.run_dir / "log.json").read_text())
        self.assertTrue(log["finished"])
        cfg = log["config"]
        self.assertEqual((cfg["rate"], cfg["seed"], cfg["steps"], cfg["episodes"], cfg["eval_every"], cfg["batch"],
                          cfg["warmup"]), (1, 0, 100, 4, 2, 32, 32))
        self.assertEqual(cfg["eval_seeds"], [1000, 1001, 1002, 1003, 1004])
        self.assertEqual(len(log["intervals"]), 2)
        for iv in log["intervals"]:
            for k in ("episode", "env_steps", "wall_s", "train_reward_mean", "eval_pick_rate_mean", "eval_pick_rates",
                      "epsilon", "loss_mean", "decisions", "gradient_steps"):
                self.assertIn(k, iv)
            self.assertEqual(len(iv["eval_pick_rates"]), 5)
        last = log["intervals"][-1]
        self.assertEqual((last["episode"], last["env_steps"]), (4, 400))
        self.assertGreater(last["gradient_steps"], 0)
        self.assertTrue(math.isfinite(last["loss_mean"]))
        self.assertTrue(math.isfinite(last["train_reward_mean"]) and math.isfinite(last["eval_pick_rate_mean"]))
        self.assertGreater(last["wall_s"], 0)
        self.assertIn("steps/s", self.first.stdout)

    # inject: save the untrained initial net, or store constants other than the ones the workers used
    def test_checkpoint_trained_and_constants_match_those_used(self):
        ck = torch.load(self.run_dir / "checkpoint.pt", weights_only=True)
        log = json.loads((self.run_dir / "log.json").read_text())
        torch.manual_seed(0)  # run_seed, immediately before QNet construction
        init = lr.QNet().state_dict()
        self.assertEqual(set(init), set(ck["state_dict"]))
        self.assertTrue(any(not torch.equal(init[k], ck["state_dict"][k]) for k in init))
        # (a) the constants the workers echoed back after using them == the checkpoint's == the module's
        self.assertEqual(ck["reward"], log["reward_used"])
        self.assertEqual(ck["reward"], dict(line_reward=lr.LINE_REWARD, stuck_penalty=lr.STUCK_PENALTY,
                                            gamma=lr.GAMMA, call_human_cost=lr.CALL_HUMAN_COST))
        self.assertEqual(ck["train_config"], log["config"])
        pol = lr.LearnedRecovery.load(self.run_dir / "checkpoint.pt")
        self.assertEqual(pol.epsilon, 0.0)

    # inject: --resume re-runs or rewrites a finished run (any byte or mtime change), prints no skip line
    def test_resume_skips_finished_run_untouched(self):
        before = snapshot(self.run_dir)
        self.assertIn("train_state.pt", before)
        again = run(self.args + ["--resume"], self.dir)
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertIn("skip", again.stdout)
        self.assertEqual(snapshot(self.run_dir), before)

    # inject: silently overwrite or skip when --resume is absent
    def test_existing_run_without_resume_raises(self):
        before = snapshot(self.run_dir)
        r = run(self.args, self.dir)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("ValueError", r.stderr)
        self.assertEqual(snapshot(self.run_dir), before)

    # inject: compare no config, or only part of it
    def test_config_mismatch_raises(self):
        before = snapshot(self.run_dir)
        r = run(["--smoke", "--steps", "101", "--workers", "2", "--resume"], self.dir)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("ValueError", r.stderr)
        self.assertIn("refusing to resume", r.stderr)
        self.assertEqual(snapshot(self.run_dir), before)

    # inject: restart from scratch on resume, or lose the optimizer / episode counter
    def test_resume_continues_unfinished_run(self):
        with tempfile.TemporaryDirectory() as d:
            part = run(self.args + ["--max-intervals", "1"], d)
            self.assertEqual(part.returncode, 0, part.stderr)
            log1 = json.loads((Path(d) / "rate1_seed0" / "log.json").read_text())
            self.assertFalse(log1["finished"])
            self.assertEqual([iv["episode"] for iv in log1["intervals"]], [2])
            rest = run(self.args + ["--resume"], d)
            self.assertEqual(rest.returncode, 0, rest.stderr)
            self.assertIn("resume", rest.stdout)
            log2 = json.loads((Path(d) / "rate1_seed0" / "log.json").read_text())
            self.assertTrue(log2["finished"])
            self.assertEqual([iv["episode"] for iv in log2["intervals"]], [2, 4])
            self.assertEqual(log2["intervals"][0], log1["intervals"][0])
            self.assertGreater(log2["intervals"][1]["gradient_steps"], log1["intervals"][0]["gradient_steps"])


if __name__ == "__main__":
    unittest.main()

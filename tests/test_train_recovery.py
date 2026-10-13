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
sys.path.insert(0, str(ROOT / "tests"))

import evaluate as ev
import train_recovery as tr
from warehouse_rl import learned_recovery as lr
from warehouse_rl.recovery import ACTIONS
from tarware.warehouse import RewardType

SCRIPT = str(ROOT / "scripts" / "train_recovery.py")
MEDIUM = "tarware-medium-8agvs-4pickers-globalobs-v1"


def run(args, results_dir, env=None):
    return subprocess.run([sys.executable, SCRIPT, *args, "--results-dir", str(results_dir)], capture_output=True,
                          text=True, timeout=600, env=env)


def snapshot(d):
    return {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in sorted(Path(d).iterdir())}


class TestWindowRecorder(unittest.TestCase):
    # inject: put the decision step outside the window (k in (t, t']), drop the discount exponent, charge the
    # call-human penalty without the cost factor, or price an action cost with stuck_penalty instead of cost_unit
    def test_hand_computed_windows(self):
        c = dict(line_reward=1.0, stuck_penalty=0.1, cost_unit=0.2, gamma=0.5, call_human_cost=10, abandon_cost=15)
        rec = tr.WindowRecorder(c, n_agents=8)
        x0, x1, x2 = (np.full(12, v, np.float32) for v in (0.0, 1.0, 2.0))

        def own(v7):  # agent 7's own reward v7 (index 6), every other agent 5.0 (must never reach agent 7's windows)
            return [5.0] * 6 + [v7, 5.0]

        rec.decision(7, 1, x0, 3)                                   # agent 7 abandons at step 1: -0.2 * 15 = -3.0
        rec.step_end(1, own(1.0), {7}, set())                       # r = 1.0 - 0.1            = 0.9
        rec.step_end(2, own(0.0), {7}, {7})                         # r = -0.1 - 0.2 * 10      = -2.1
        rec.decision(7, 3, x1, 4)                                   # next decision at step 3: Delta 2
        rec.decision(7, 3, x2, 0)                                   # second decision, same step: Delta 0
        rec.step_end(3, own(0.0), set(), set())                     # r = 0
        rec.step_end(4, own(0.5), set(), set())                     # r = 0.5, weight 0.5**(4-3)
        rec.finish(5)
        (a, b, d) = rec.out
        self.assertEqual((a[1], a[6], a[7], a[8], a[5]), (3, 7, 1, 2, False))
        self.assertAlmostEqual(a[2], -3.0 + 0.9 + 0.5 * -2.1)       # -3.15 (abandon charge undiscounted)
        self.assertAlmostEqual(a[3], 0.25)                          # gamma ** Delta
        np.testing.assert_array_equal(a[4], x1)
        self.assertEqual((b[1], b[8], b[2], b[3], b[5]), (4, 0, 0.0, 1.0, False))   # Delta 0: no reward, discount 1
        np.testing.assert_array_equal(b[4], x2)
        self.assertEqual((d[1], d[8], d[5]), (0, 2, True))                         # closed by the episode end
        self.assertAlmostEqual(d[2], 0.0 + 0.5 * 0.5)               # step 3: 0, step 4: 0.5 * 0.5**1
        self.assertAlmostEqual(a[9], -3.0 + 0.9 - 2.1)              # undiscounted return, used for the log only

    # inject: no charge, charge on every decision, charge in step_end, or charge the call-human action
    def test_abandon_charged_once_per_abandon_decision_only(self):
        c = dict(line_reward=1.0, stuck_penalty=0.1, cost_unit=0.2, gamma=0.5, call_human_cost=10, abandon_cost=15)
        x = np.zeros(12, np.float32)
        for a, name in enumerate(ACTIONS):
            rec = tr.WindowRecorder(c, n_agents=2)
            rec.decision(1, 0, x, a)
            rec.step_end(0, [0.0, 0.0], set(), set())       # no own reward, not stuck: the step reward is 0
            rec.step_end(1, [0.0, 0.0], set(), set())
            rec.finish(2)
            (o,) = rec.out
            want = -0.2 * 15 if name == "abandon" else 0.0   # -3.0 (cost_unit, not stuck_penalty), undiscounted, once
            self.assertAlmostEqual(o[2], want, msg=name)     # R
            self.assertAlmostEqual(o[9], want, msg=name)     # U
        # two abandons by one agent are charged twice (once per window); the charge is not discounted by the window's
        # later steps: window 1 = steps 0-1 (r_k = 0.5 own reward at k = 1), window 2 = step 2
        rec = tr.WindowRecorder(c, n_agents=2)
        rec.decision(1, 0, x, 3)
        rec.step_end(0, [0.0, 0.0], set(), set())
        rec.step_end(1, [0.5, 0.0], set(), set())
        rec.decision(1, 2, x, 3)
        rec.step_end(2, [0.0, 0.0], set(), set())
        rec.finish(3)
        w1, w2 = rec.out
        self.assertAlmostEqual(w1[2], -3.0 + 0.5 * 0.5)
        self.assertAlmostEqual(w2[2], -3.0)

    # inject: STUCK_PENALTY back to 0.01, COST_UNIT changed, or an action cost priced with stuck_penalty (now 0)
    def test_shipped_reward_is_deliveries_minus_action_costs(self):
        c = lr.reward_constants()
        self.assertEqual(c, dict(line_reward=1.0, stuck_penalty=0.0, cost_unit=0.01, gamma=0.99, call_human_cost=60,
                                 abandon_cost=15, credit="own", vendor_step_penalty="excluded"))
        x = np.zeros(12, np.float32)
        out = {}
        for name, stuck, relocated in (("abandon", set(), set()), ("wait", {1}, set()), ("call_human", set(), {1})):
            rec = tr.WindowRecorder(c, n_agents=12)
            rec.decision(1, 0, x, ACTIONS.index(name))
            rec.step_end(0, [0.0] * 12, stuck, relocated)
            rec.finish(1)
            out[name] = rec.out[0][9]
        self.assertAlmostEqual(out["abandon"], -0.15, places=12)     # 0.01 x 15, once
        self.assertEqual(out["wait"], 0.0)                           # a stuck busy step costs nothing
        self.assertAlmostEqual(out["call_human"], -0.60, places=12)  # 0.01 x 60 per executed relocation


    # inject: sum the own vector (agent 3 gets 1.1), divide it by n_agents (agent 1 gets 1/12), or index it by aid
    # instead of aid - 1 (agent 1 gets 0.1)
    def test_each_agent_credited_with_its_own_reward_only(self):
        c = dict(lr.reward_constants(), gamma=0.9)
        x = np.zeros(12, np.float32)
        rec = tr.WindowRecorder(c, n_agents=12)
        for aid in (1, 2, 3, 12):
            rec.decision(aid, 0, x, ACTIONS.index("wait"))
        own = [0.0] * 12
        own[0], own[1] = 1.0, 0.1  # agent 1 (index 0) delivers, agent 2 (index 1) loads
        rec.step_end(0, [0.0] * 12, set(), set())
        rec.step_end(1, [0.0] * 12, set(), set())
        rec.step_end(2, own, set(), set())  # offset 2 in every window
        rec.finish(3)
        got = {o[6]: o[2] for o in rec.out}
        self.assertEqual(set(got), {1, 2, 3, 12})
        self.assertAlmostEqual(got[1], 1.0 * 0.9 ** 2, places=12)
        self.assertAlmostEqual(got[2], 0.1 * 0.9 ** 2, places=12)
        self.assertEqual(got[3], 0.0)
        self.assertEqual(got[12], 0.0)
        with self.assertRaises(ValueError):
            rec.step_end(3, [0.0] * 11, set(), set())


class TestOwnCreditFromEnv(unittest.TestCase):
    # inject: drop the VENDOR_STEP_PENALTY add-back in run_episode (a quiet step is then -0.001, not 0)
    def test_vendor_constant_step_term_is_pinned_and_removed(self):
        cfg = tr.point_spec("breakdown", 1)[1]
        env = lr.make_learned_env(MEDIUM, 10, cfg, lr.LearnedRecovery(lr.QNet()), 60)
        try:
            env.reset(seed=0)
            _, rewards, _, _, info = env.step([0] * env.num_agents)  # all NOOP: no load, unload or delivery
        finally:
            env.close()
        self.assertEqual(int(info["shelf_deliveries"]), 0)
        self.assertEqual([float(r) for r in rewards], [-lr.VENDOR_STEP_PENALTY] * 12)  # vendor warehouse.py:674
        torch.manual_seed(0)
        res = tr.run_episode(dict(state_dict=lr.QNet().state_dict(), epsilon=0.0, explore_seed=0, env_id=MEDIUM,
                                  disturb=cfg, steps=40, seed=0, call_human_cost=60, consts=lr.reward_constants(),
                                  collect=True, trace=True))
        self.assertEqual(res["trace"][0]["own"], [0.0] * 12)  # the first step has no event: exactly 0, not -0.001
        self.assertTrue(all(v >= 0.0 for t in res["trace"] for v in t["own"]))  # no -0.001 left anywhere

    # inject: credit the delivery to another agent (own[aid % 12]), broadcast the total (global_reward=True), or
    # share deliveries equally; checked against DisturbedWarehouse.delivered_per_agent, the repo's own counter
    def test_own_reward_matches_per_agent_deliveries(self):
        cfg = tr.point_spec("breakdown", 1)[1]
        torch.manual_seed(0)
        res = tr.run_episode(dict(state_dict=lr.QNet().state_dict(), epsilon=1.0, explore_seed=0, env_id=MEDIUM,
                                  disturb=cfg, steps=300, seed=1, call_human_cost=60, consts=lr.reward_constants(),
                                  collect=True, trace=True, prior="timeout", random_share=0.0))
        self.assertGreater(res["deliveries"], 0)
        per_agent = [0] * 12
        loads = 0
        for t in res["trace"]:
            whole = [int(math.floor(v + 1e-9)) for v in t["own"]]
            self.assertEqual(sum(whole), t["deliveries"], f"step {t['k']}")
            for i, w in enumerate(whole):
                per_agent[i] += w
                frac = t["own"][i] - w
                self.assertAlmostEqual(frac * 10, round(frac * 10), places=6)  # +0.1 per load/unload
                loads += round(frac * 10)
        self.assertEqual(per_agent, res["delivered_per_agent"])
        self.assertEqual(per_agent[8:], [0, 0, 0, 0])  # pickers (ids 9-12) never deliver
        self.assertGreater(loads, 0)
        self.assertTrue(any(t["own"][i] > 0 for t in res["trace"] for i in range(8, 12)))  # pickers earn the +0.1

    # inject: build the env with global_reward=True, or drop either half of the assertion in make_learned_env
    def test_make_learned_env_refuses_a_shared_reward(self):
        real = lr.WarehouseEnv

        def shared(*a, **kw):
            kw["global_reward"] = True
            return real(*a, **kw)

        cfg = tr.point_spec("breakdown", 1)[1]
        with mock.patch.object(lr, "WarehouseEnv", shared):
            with self.assertRaisesRegex(AssertionError, "own credit"):
                lr.make_learned_env(MEDIUM, 10, cfg, lr.LearnedRecovery(lr.QNet()), 60)

        def vendor_global(*a, **kw):  # the vendor broadcasting team credit (RewardType.GLOBAL)
            env = real(*a, **kw)
            env.env.reward_type = RewardType.GLOBAL
            return env

        with mock.patch.object(lr, "WarehouseEnv", vendor_global):
            with self.assertRaisesRegex(AssertionError, "own credit"):
                lr.make_learned_env(MEDIUM, 10, cfg, lr.LearnedRecovery(lr.QNet()), 60)


class TestRolloutReward(unittest.TestCase):
    def episode(self, consts, steps=120, seed=3, **kw):
        torch.manual_seed(11)
        sd = lr.QNet().state_dict()
        cfg = {"breakdown": {"rate_per_hour": 8, "duration": [20, 60], "agent_types": ["agv"]}}
        task = dict(state_dict=sd, epsilon=0.5, explore_seed=seed, env_id=MEDIUM, disturb=cfg, steps=steps,
                    seed=seed, call_human_cost=consts["call_human_cost"], consts=consts, collect=True, trace=True)
        task.update(kw)
        return tr.run_episode(task)

    def reference(self, res, consts):
        """Independent recomputation of every transition's reward from the recorded per-step trace."""
        trace = {t["k"]: t for t in res["trace"]}
        out = []
        for aid, t0, delta, act in zip(res["AID"], res["T0"], res["DELTA"], res["A"]):
            total = -consts["cost_unit"] * consts["abandon_cost"] * (ACTIONS[int(act)] == "abandon")
            for k in range(int(t0), int(t0) + int(delta)):
                st = trace[k]
                r = consts["line_reward"] * st["own"][int(aid) - 1]
                r -= consts["stuck_penalty"] * (int(aid) in st["stuck"])
                r -= consts["cost_unit"] * consts["call_human_cost"] * (int(aid) in st["relocated"])
                total += consts["gamma"] ** (k - int(t0)) * r
            out.append(total)
        return np.array(out)

    # inject: change the window to (t, t'], read the env reward, or ignore the passed constants
    def test_trainer_reward_equals_reference_from_trace(self):
        for consts in (lr.reward_constants(),
                       dict(line_reward=2.0, stuck_penalty=0.5, cost_unit=0.3, gamma=0.9, call_human_cost=7,
                            abandon_cost=4)):
            res = self.episode(consts)
            self.assertEqual(res["reward_used"], consts)
            self.assertGreaterEqual(int((res["A"] == ACTIONS.index("abandon")).sum()), 1)  # the abandon term is exercised
            self.assertGreater(len(res["A"]), 50)
            np.testing.assert_allclose(res["R"], self.reference(res, consts), atol=1e-9)
            np.testing.assert_allclose(res["DISC"], consts["gamma"] ** res["DELTA"], atol=1e-12)
            self.assertEqual(res["busy_stuck_mismatch"], 0)  # recorder's stuck flag == info["stuck_busy_agents"]
            zero = (res["DELTA"] == 0) & (res["A"] != ACTIONS.index("abandon"))  # an abandon is charged even at Delta 0
            self.assertTrue(np.all(res["R"][zero] == 0.0) and np.all(res["DISC"][zero] == 1.0))
            self.assertTrue(np.any(res["R"] != 0.0))
        # the stuck term is wired (coefficient 0 by default): a 0.5 penalty makes the total strictly lower
        lo = self.episode(lr.reward_constants())["R"].sum()
        hi = self.episode(dict(lr.reward_constants(), stuck_penalty=0.5))["R"].sum()
        self.assertLess(hi, lo)

    # inject: charge call-human on the decision instead of the executed relocation, or attribute it to another agent
    # (e.g. relocs.add(agent.id % 12 + 1)); the check is against the hook's own call_human_steps counter, not the trace
    def test_call_human_charged_on_execution_to_the_deciding_agent(self):
        for consts in (lr.reward_constants(), dict(line_reward=2.0, stuck_penalty=0.5, cost_unit=0.3, gamma=0.9,
                                                   call_human_cost=7, abandon_cost=4)):
            res = self.episode(consts)
            executed = sum(len(t["relocated"]) for t in res["trace"])
            decided = sum(a == 4 for t in res["trace"] for _, _, a in t["decisions"])
            self.assertGreater(executed, 0)
            self.assertGreater(decided, executed)  # some calls fall back, so decision != execution is observable
            self.assertEqual(executed * consts["call_human_cost"], res["call_human_steps"])
            for t in res["trace"]:
                last = {}
                for aid, k, a in t["decisions"]:
                    self.assertEqual(k, t["k"])
                    last[aid] = a
                for aid in t["relocated"]:
                    self.assertEqual(last.get(aid), 4, f"step {t['k']}: agent {aid} relocated without calling")

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

    # inject: in run_episode pass prior=None, or random_share=1.0, to LearnedRecovery (train_recovery.py, the
    # from_state_dict call), or let the collecting instrumentation change the episode
    def test_training_rollout_with_timeout_prior_equals_evaluate_timeout(self):
        cfg = tr.point_spec("breakdown", 1)[1]
        torch.manual_seed(7)
        sd = lr.QNet().state_dict()
        for seed in (1000, 1001):
            row = ev.run_seed("stuck_aware_cta", MEDIUM, 300, seed, disturb=cfg,
                              recovery={"name": "timeout", "call_human_cost": 60})
            want = (row["pick_rate"], row["deliveries"], row["recovery_stuck_events"] + row["recovery_clash_events"])
            self.assertGreater(want[2], 0, seed)  # non-vacuous: the hook decides in this episode

            def go(share):
                res = tr.run_episode(dict(state_dict=sd, epsilon=1.0, explore_seed=seed, env_id=MEDIUM, disturb=cfg,
                                          steps=300, seed=seed, call_human_cost=60, consts=lr.reward_constants(),
                                          collect=True, prior="timeout", random_share=share))
                self.assertEqual(len(res["A"]), res["decisions"])
                return res["pick_rate"], res["deliveries"], res["decisions"]

            self.assertEqual(go(0.0), want, seed)
            self.assertNotEqual(go(1.0), want, seed)  # all-random exploration is a different episode


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

    # inject: never sync the target (drop the load_state_dict), or sync every step
    def test_target_hard_sync_every_target_sync_steps(self):
        torch.manual_seed(0)
        online, target = lr.QNet(), lr.QNet()
        target.load_state_dict(online.state_dict())
        opt = torch.optim.Adam(online.parameters(), lr=1e-2)
        replay = tr.Replay(64)
        rng = np.random.default_rng(0)
        n = 64
        replay.add(dict(X=rng.normal(size=(n, 12)).astype(np.float32), X2=rng.normal(size=(n, 12)).astype(np.float32),
                        A=rng.integers(0, 5, n), R=rng.normal(size=n), DISC=np.full(n, 0.9), DONE=np.zeros(n, bool)))
        cfg = dict(batch=16, clip_norm=10.0, target_sync=3)

        def same():
            return all(torch.equal(a, b) for a, b in zip(online.state_dict().values(), target.state_dict().values()))

        g, _, ln = tr.learn(online, target, opt, replay, cfg, 2, 0)
        self.assertEqual((g, ln), (2, 2))
        self.assertFalse(same())            # 2 steps: online moved, target not yet synced
        g, _, _ = tr.learn(online, target, opt, replay, cfg, 1, g)
        self.assertTrue(same())             # step 3: hard sync
        g, _, _ = tr.learn(online, target, opt, replay, cfg, 1, g)
        self.assertFalse(same())            # step 4: online moves again, target holds the step-3 weights
        g, _, _ = tr.learn(online, target, opt, replay, cfg, 2, g)
        self.assertEqual(g, 6)
        self.assertTrue(same())             # step 6: synced again

    # inject: read SCHED_WORKERS before --workers, or skip the cap
    def test_worker_resolution(self):
        seen = []

        def fake(rate, run_seed, steps, episodes, smoke, workers, results_dir, resume, max_intervals=None, **kw):
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
        self.assertEqual((tr.DEFAULT_EPISODES, lr.FORMAT_VERSION, lr.ABANDON_COST, tr.RANDOM_SHARE, tr.ABORT_BELOW),
                         (3200, 2, 15, 0.1, 0.5))
        self.assertEqual(tr.DEFAULT_EPISODES % tr.EVAL_EVERY, 0)
        self.assertEqual(tr.DEFAULT_EPISODES % tr.ITER_EPISODES, 0)
        cfg = tr.build_config(1, 0, 500, 3200, False)
        self.assertEqual(cfg["reward"]["abandon_cost"], 15)
        self.assertEqual(cfg["abandon_cost"], 15)
        self.assertEqual(cfg["explore"], {"prior": "timeout", "random_share": 0.1})
        self.assertEqual((cfg["abort_below"], cfg["version"]), (0.5, 2))
        self.assertEqual((tr.ABORT_AFTER_FRAC, cfg["abort_after_frac"]), (tr.EPS_FRAC, 0.5))
        self.assertEqual(cfg["reward"], dict(line_reward=1.0, stuck_penalty=0.0, cost_unit=0.01, gamma=0.99,
                                             call_human_cost=60, abandon_cost=15, credit="own",
                                             vendor_step_penalty="excluded"))


class _RecordingPool:
    """In-process stand-in for the spawn pool: runs run_episode here, records every task list it was mapped."""
    calls = []

    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def map(self, fn, tasks, chunksize=1):
        tasks = list(tasks)
        _RecordingPool.calls.append(tasks)
        return [fn(t) for t in tasks]


class TestShippedWeights(unittest.TestCase):
    # inject: roll out every iteration with the initial weights (ship sd once, outside the loop), or evaluate with the
    # initial / pre-update weights instead of the current online net
    def test_workers_get_current_online_weights(self):
        _RecordingPool.calls = []
        fake_ctx = mock.Mock()
        fake_ctx.Pool = _RecordingPool
        with tempfile.TemporaryDirectory() as d, mock.patch.object(tr.mp, "get_context", return_value=fake_ctx):
            out = tr.train_run(1, 0, 100, None, True, 1, d, False, abort_below=0)
            self.assertEqual(out["status"], "finished")
            ck = lr.load_checkpoint(Path(d) / "rate1_seed0" / "checkpoint.pt")
        ref, calls = _RecordingPool.calls[0], _RecordingPool.calls[1:]
        self.assertTrue(all(t["policy"] == "timeout" and t["state_dict"] is None for t in ref))
        kinds = ["train" if c[0]["collect"] else "eval" for c in calls]
        self.assertEqual(kinds, ["train", "eval", "train", "eval"])  # smoke: iteration = interval = 2 episodes
        self.assertTrue(all(t["prior"] == "timeout" and t["random_share"] == 0.1 for t in calls[0] + calls[2]))
        self.assertTrue(all(t["prior"] is None and t["epsilon"] == 0.0 for t in calls[1] + calls[3]))

        def eq(a, b):
            return all(torch.equal(a[k], b[k]) for k in a)

        for c in calls:  # one weight set per map call
            self.assertTrue(all(eq(t["state_dict"], c[0]["state_dict"]) for t in c))
        torch.manual_seed(0)
        init = lr.QNet().state_dict()
        sd = [c[0]["state_dict"] for c in calls]
        self.assertTrue(eq(sd[0], init))
        self.assertFalse(eq(sd[2], init))      # iteration 2 rolls out with the weights updated after iteration 1
        self.assertTrue(eq(sd[2], sd[1]))      # ... the same ones the first eval used
        self.assertFalse(eq(sd[3], sd[2]))     # the last eval uses the post-iteration-2 weights
        self.assertTrue(eq(sd[3], ck["state_dict"]))  # ... which are the saved checkpoint
        self.assertTrue(all(t["epsilon"] == 0.0 for t in calls[1] + calls[3]))


class TestRandomSharePlumbing(unittest.TestCase):
    # inject: main drops --random-share, or task() uses the RANDOM_SHARE constant instead of the run's config
    def test_cli_random_share_reaches_every_training_rollout(self):
        _RecordingPool.calls = []
        with tempfile.TemporaryDirectory() as d, mock.patch.object(tr.mp, "get_context", return_value=_fake_ctx(
                _RecordingPool)), mock.patch.object(sys, "argv", ["t", "--smoke", "--random-share", "0.3",
                                                                   "--abort-below", "0", "--steps", "60",
                                                                   "--results-dir", d]), mock.patch("builtins.print"):
            tr.main()
            cfg = json.loads((Path(d) / "rate1_seed0" / "log.json").read_text())["config"]
        train = [t for c in _RecordingPool.calls for t in c if t.get("collect")]
        self.assertEqual(len(train), 4)
        self.assertTrue(all(t["random_share"] == 0.3 and t["prior"] == "timeout" for t in train))
        self.assertEqual(cfg["explore"], {"prior": "timeout", "random_share": 0.3})


class TestSmokeTrainAndResume(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.args = ["--smoke", "--steps", "100", "--workers", "2", "--abort-below", "0"]
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

    # inject: omit the reference from the log, write it only at the end, or compute it with another policy / seeds
    def test_smoke_writes_reference_and_first_interval(self):
        log = json.loads((self.run_dir / "log.json").read_text())
        ref = log["reference_pick_rate"]
        self.assertEqual(set(ref), {"mean", "values"})
        self.assertEqual(len(ref["values"]), 5)
        self.assertAlmostEqual(ref["mean"], float(np.mean(ref["values"])))
        cfg = log["config"]
        for seed, v in zip(tr.EVAL_SEEDS, ref["values"]):
            row = ev.run_seed("stuck_aware_cta", tr.MEDIUM_8, cfg["steps"], seed, disturb=cfg["disturb"],
                              recovery={"name": "timeout", "call_human_cost": cfg["call_human_cost"]})
            self.assertEqual(v, row["pick_rate"], seed)
        self.assertIn("eval_pick_rate_mean", log["intervals"][0])
        self.assertEqual(log["intervals"][0]["episode"], 2)
        self.assertEqual(cfg["abort_below"], 0)
        self.assertNotIn("aborted", log)
        self.assertIn("timeout reference", self.first.stdout)

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
        self.assertEqual(ck["reward"], dict(line_reward=lr.LINE_REWARD, stuck_penalty=0.0, cost_unit=0.01,
                                            gamma=lr.GAMMA, call_human_cost=lr.CALL_HUMAN_COST, abandon_cost=15,
                                            credit="own", vendor_step_penalty="excluded"))
        self.assertEqual(log["reward_used"]["abandon_cost"], 15)
        self.assertEqual(log["config"]["reward"], ck["reward"])
        self.assertEqual(ck["version"], 2)
        self.assertEqual(ck["train_config"], log["config"])
        pol = lr.LearnedRecovery.load(self.run_dir / "checkpoint.pt")
        self.assertEqual(pol.epsilon, 0.0)

    # inject: pass 0 instead of the running gradient-step counter into learn() (the target-sync clock restarts every
    # iteration and the logged gradient_steps is per-iteration)
    def test_gradient_step_counter_is_cumulative(self):
        st = torch.load(self.run_dir / "train_state.pt", weights_only=True)
        log = json.loads((self.run_dir / "log.json").read_text())
        adam_steps = int(st["optimizer"]["state"][0]["step"])  # Adam counts every opt.step() of the run
        self.assertEqual(st["gradient_steps"], adam_steps)
        self.assertEqual(log["intervals"][-1]["gradient_steps"], adam_steps)

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
        r = run(["--smoke", "--steps", "101", "--workers", "2", "--abort-below", "0", "--resume"], self.dir)
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

    # inject: on resume keep every log interval (drop the `<= episodes_done` filter). The episode-0 state write itself is
    # guarded by test_fresh_run_writes_state_before_first_rollout (this test rebuilds that state by hand)
    def test_kill_between_log_and_state_writes_stays_resumable(self):
        with tempfile.TemporaryDirectory() as d:
            rd = Path(d) / "rate1_seed0"
            part = run(self.args + ["--max-intervals", "1"], d)
            self.assertEqual(part.returncode, 0, part.stderr)
            state1 = (rd / "train_state.pt").read_bytes()
            done = run(self.args + ["--resume"], d)
            self.assertEqual(done.returncode, 0, done.stderr)
            # simulate a kill after the interval-2 log write but before its state write: log says 4 episodes (and,
            # for a non-final interval, finished false), the state is still the interval-1 one
            log = json.loads((rd / "log.json").read_text())
            log["finished"] = False
            (rd / "log.json").write_text(json.dumps(log))
            (rd / "train_state.pt").write_bytes(state1)
            again = run(self.args + ["--resume"], d)
            self.assertEqual(again.returncode, 0, again.stderr)
            log2 = json.loads((rd / "log.json").read_text())
            self.assertTrue(log2["finished"])
            self.assertEqual([iv["episode"] for iv in log2["intervals"]], [2, 4])  # interval 2 redone, not doubled
        with tempfile.TemporaryDirectory() as d:
            # a kill after the first log write but before its state write leaves the episode-0 state under it
            r = run(self.args + ["--max-intervals", "1"], d)
            self.assertEqual(r.returncode, 0, r.stderr)
            rd = Path(d) / "rate1_seed0"
            st = torch.load(rd / "train_state.pt", weights_only=True)
            self.assertEqual(st["episodes_done"], 2)
            # rebuild the episode-0 state the trainer writes first and put it back under the interval-1 log
            torch.manual_seed(0)
            online = lr.QNet()
            target = lr.QNet()
            target.load_state_dict(online.state_dict())
            opt = torch.optim.Adam(online.parameters(), lr=st["optimizer"]["param_groups"][0]["lr"])
            torch.save(dict(online=online.state_dict(), target=target.state_dict(), optimizer=opt.state_dict(),
                            torch_rng=torch.get_rng_state(), episodes_done=0, gradient_steps=0, env_steps=0,
                            wall_s=0.0), rd / "train_state.pt")
            again = run(self.args + ["--resume"], d)
            self.assertEqual(again.returncode, 0, again.stderr)
            log2 = json.loads((rd / "log.json").read_text())
            self.assertTrue(log2["finished"])
            self.assertEqual([iv["episode"] for iv in log2["intervals"]], [2, 4])

    # inject: skip the episode-0 state write
    def test_fresh_run_writes_state_before_first_rollout(self):
        calls = []
        orig = tr._atomic_torch

        def spy(path, obj):
            calls.append((Path(path).name, obj.get("episodes_done") if isinstance(obj, dict) else None))
            return orig(path, obj)

        class Boom(Exception):
            pass

        def fail_map(*a, **kw):
            raise Boom()

        fake_ctx = mock.Mock()
        fake_ctx.Pool = _RecordingPool
        with tempfile.TemporaryDirectory() as d, mock.patch.object(tr, "_atomic_torch", spy), \
                mock.patch.object(tr.mp, "get_context", return_value=fake_ctx), \
                mock.patch.object(_RecordingPool, "map", fail_map):
            with self.assertRaises(Boom):
                tr.train_run(1, 0, 100, None, True, 1, d, False, abort_below=0)
            self.assertEqual(calls, [("train_state.pt", 0)])
            self.assertTrue((Path(d) / "rate1_seed0" / "train_state.pt").exists())
            self.assertFalse((Path(d) / "rate1_seed0" / "log.json").exists())


class _FakeEvalPool(_RecordingPool):
    """In-process pool; the eval and the reference results are overridden with fixed pick-rates (fabricated)."""
    eval_rate, ref_rate = 0.0, 10.0

    def map(self, fn, tasks, chunksize=1):
        out = []
        for t in list(tasks):
            r = fn(t)
            if t.get("policy") == "timeout":
                r["pick_rate"] = self.ref_rate
            elif not t["collect"]:
                r["pick_rate"] = self.eval_rate
            out.append(r)
        return out


def _fake_ctx(pool=_FakeEvalPool):
    ctx = mock.Mock()
    ctx.Pool = pool
    return ctx


class TestAbortAndVersion(unittest.TestCase):
    def go(self, d, abort_below, resume=False, max_intervals=None, **kw):
        with mock.patch.object(tr.mp, "get_context", return_value=_fake_ctx()):
            return tr.train_run(1, 0, 60, None, True, 1, d, resume, max_intervals, abort_below=abort_below, **kw)

    # inject: never abort, compare against the wrong threshold, keep finished true, or omit a key of `aborted`
    def test_abort_fires_on_low_interval(self):
        with tempfile.TemporaryDirectory() as d, mock.patch("builtins.print") as pr:
            out = self.go(d, 0.5)
            self.assertEqual(out["status"], "aborted")
            log = json.loads((Path(d) / "rate1_seed0" / "log.json").read_text())
            self.assertIs(log["finished"], False)
            self.assertEqual(log["aborted"], dict(episode=2, eval_pick_rate_mean=0.0, reference=10.0, abort_below=0.5,
                                                  abort_after_frac=0.5))
            self.assertEqual(log["reference_pick_rate"], dict(mean=10.0, values=[10.0] * 5))
            self.assertEqual(len(log["intervals"]), 1)
            lines = [c.args[0] for c in pr.call_args_list if c.args and str(c.args[0]).startswith("ABORT")]
            self.assertEqual(lines, ["ABORT rate 1 seed 0 at episode 2: eval 0.00 < 0.5 x reference 10.00"])

    # inject: abort check skipped on the last interval, or an aborted last interval left as finished true
    def test_abort_on_last_interval_is_not_finished(self):
        class LateLow(_FakeEvalPool):
            n_eval = 0

            def map(self, fn, tasks, chunksize=1):
                tasks = list(tasks)
                if tasks[0].get("policy") != "timeout" and not tasks[0]["collect"]:
                    LateLow.n_eval += 1
                    type(self).eval_rate = 50.0 if LateLow.n_eval == 1 else 0.0
                return super().map(fn, tasks, chunksize)

        with tempfile.TemporaryDirectory() as d, mock.patch.object(tr.mp, "get_context", return_value=_fake_ctx(LateLow)):
            out = tr.train_run(1, 0, 60, None, True, 1, d, False, abort_below=0.5)
            log = json.loads((Path(d) / "rate1_seed0" / "log.json").read_text())
        self.assertEqual((out["status"], log["finished"], log["aborted"]["episode"]), ("aborted", False, 4))

    # inject: abort_below 0 still aborts
    def test_no_abort_when_disabled(self):
        with tempfile.TemporaryDirectory() as d:
            out = self.go(d, 0)
            log = json.loads((Path(d) / "rate1_seed0" / "log.json").read_text())
            self.assertEqual(out["status"], "finished")
            self.assertTrue(log["finished"])
            self.assertNotIn("aborted", log)
            self.assertEqual(log["config"]["abort_below"], 0)

    # inject: resume continues an aborted run
    def test_resume_on_aborted_raises_naming_dir(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.go(d, 0.5)["status"], "aborted")
            with self.assertRaises(ValueError) as cm:
                self.go(d, 0.5, resume=True)
            self.assertIn(str(Path(d) / "rate1_seed0"), str(cm.exception))
            self.assertIn("aborted", str(cm.exception))

    # inject: main swallows an aborted run's status, or stops the other runs after it
    def test_main_runs_all_then_exits_nonzero(self):
        seen = []

        def fake(rate, run_seed, *a, **kw):
            seen.append(run_seed)
            return dict(status="aborted" if run_seed == 0 else "stopped")

        with tempfile.TemporaryDirectory() as d, mock.patch.object(tr, "train_run", fake), \
                mock.patch.object(sys, "argv", ["t", "--rates", "1", "--seeds", "0,1", "--results-dir", d]):
            with self.assertRaises(SystemExit) as cm:
                tr.main()
        self.assertEqual((cm.exception.code, seen), (1, [0, 1]))
        with tempfile.TemporaryDirectory() as d, mock.patch.object(tr, "train_run", lambda *a, **kw: dict(
                status="stopped")), mock.patch.object(sys, "argv", ["t", "--rates", "1", "--seeds", "0", "--results-dir", d]):
            tr.main()  # no abort: returns normally

    # inject: the reference is not recomputed on resume, or a mismatch is ignored
    def test_resume_recomputes_reference_and_raises_on_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.go(d, 0, max_intervals=1)["status"], "stopped")
            log_path = Path(d) / "rate1_seed0" / "log.json"
            self.assertEqual(json.loads(log_path.read_text())["reference_pick_rate"]["mean"], 10.0)
            with mock.patch.object(_FakeEvalPool, "ref_rate", 11.0), self.assertRaises(ValueError) as cm:
                self.go(d, 0, resume=True)
            self.assertIn("reference", str(cm.exception))
            out = self.go(d, 0, resume=True)  # same reference: continues, and keeps it in the log
            self.assertEqual(out["status"], "finished")
            self.assertEqual(json.loads(log_path.read_text())["reference_pick_rate"]["mean"], 10.0)

    # inject: skip or continue a version-1 run, with or without --resume; name the config diff instead of the version
    def test_version_1_run_dir_raises_with_and_without_resume(self):
        with tempfile.TemporaryDirectory() as d:
            self.go(d, 0)
            rd = Path(d) / "rate1_seed0"
            log = json.loads((rd / "log.json").read_text())
            log["config"]["version"] = 1
            (rd / "log.json").write_text(json.dumps(log))
            before = snapshot(rd)
            for resume in (False, True):
                with self.assertRaises(ValueError) as cm:
                    self.go(d, 0, resume=resume)
                self.assertIn(str(rd), str(cm.exception))
                self.assertIn("version", str(cm.exception))
            self.assertEqual(snapshot(rd), before)
            del log["config"]["version"]  # a log with no version at all is also refused
            (rd / "log.json").write_text(json.dumps(log))
            with self.assertRaises(ValueError):
                self.go(d, 0, resume=True)

    def test_bad_arguments(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                self.go(d, -0.1)
            with self.assertRaises(ValueError):
                self.go(d, 0, random_share=1.5)
            for bad in (-0.1, 1.5):
                with self.assertRaises(ValueError):
                    self.go(d, 0.5, abort_after_frac=bad)

    def _long(self, d, **kw):
        """Non-smoke run of 8 episodes with an eval every 2 (patched), every eval fabricated at 0 vs reference 10."""
        with mock.patch.object(tr.mp, "get_context", return_value=_fake_ctx()), \
                mock.patch.multiple(tr, EVAL_EVERY=2, ITER_EPISODES=2, WARMUP=32, BATCH=32, TARGET_SYNC=10):
            return tr.train_run(1, 0, 60, 8, False, 1, d, False, **kw)

    # inject: no grace (check from the first interval), `>` instead of `>=` at the threshold, or a grace on the CLI
    # value instead of the run's episodes
    def test_default_grace_never_aborts_before_eps_frac(self):
        with tempfile.TemporaryDirectory() as d:
            out = self._long(d)  # default abort_below 0.5, abort_after_frac EPS_FRAC: first check at episode 4
            log = json.loads((Path(d) / "rate1_seed0" / "log.json").read_text())
        self.assertEqual(out["status"], "aborted")
        self.assertEqual([iv["episode"] for iv in log["intervals"]], [2, 4])  # episode 2 was 0.0 and did not abort
        self.assertEqual(log["aborted"], dict(episode=4, eval_pick_rate_mean=0.0, reference=10.0, abort_below=0.5,
                                              abort_after_frac=0.5))
        self.assertEqual(log["config"]["abort_after_frac"], 0.5)
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self._long(d, abort_after_frac=0.0)["aborted"]["episode"], 2)
        with tempfile.TemporaryDirectory() as d:  # 1.0: only the last interval is checked
            self.assertEqual(self._long(d, abort_after_frac=1.0)["aborted"]["episode"], 8)

    # inject: main ignores --abort-after-frac, swallows the aborted status, or exits 0
    def test_default_smoke_aborts_on_degenerate_eval_and_exits_1(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(tr.mp, "get_context", return_value=_fake_ctx()), \
                mock.patch.object(sys, "argv", ["t", "--smoke", "--abort-after-frac", "0", "--steps", "60",
                                                "--results-dir", d]), mock.patch("builtins.print"):
            with self.assertRaises(SystemExit) as cm:
                tr.main()  # default --abort-below (0.5); every greedy eval fabricated at 0 vs reference 10
            log = json.loads((Path(d) / "rate1_seed0" / "log.json").read_text())
        self.assertEqual(cm.exception.code, 1)
        self.assertIs(log["finished"], False)
        self.assertEqual(log["aborted"], dict(episode=2, eval_pick_rate_mean=0.0, reference=10.0, abort_below=0.5,
                                              abort_after_frac=0.0))


class TestReference(unittest.TestCase):
    # inject: evaluate another policy / other seeds / another disturbance for the reference
    def test_reference_equals_evaluate_run_seed_timeout(self):
        cfg = tr.build_config(2, 0, 300, None, True)
        ref = tr.reference_pick_rate(_RecordingPool(), cfg, lr.reward_constants())
        want = [ev.run_seed("stuck_aware_cta", tr.MEDIUM_8, 300, s, disturb=cfg["disturb"],
                            recovery={"name": "timeout", "call_human_cost": cfg["call_human_cost"]})["pick_rate"]
                for s in tr.EVAL_SEEDS]
        self.assertEqual(ref["values"], want)
        self.assertEqual(ref["mean"], float(np.mean(want)))
        self.assertGreater(ref["mean"], 0.0)  # non-vacuous at this length


if __name__ == "__main__":
    unittest.main()

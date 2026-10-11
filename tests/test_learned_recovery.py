"""Tests for warehouse_rl.learned_recovery and `evaluate.py --recovery learned:`. Each case names its red-demonstration
in an `# inject:` comment."""
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate as ev
from warehouse_rl import learned_recovery as lr
from warehouse_rl.recovery import ACTIONS, RecoveryHook

SMALL = "tarware-small-4agvs-2pickers-globalobs-v1"
EVALUATE = str(ROOT / "scripts" / "evaluate.py")


def make_ckpt(path, seed=0, call_human_cost=60, **overrides):
    """Save a checkpoint of a randomly initialised net (torch seeded) and return its path."""
    torch.manual_seed(seed)
    ck = dict(state_dict=lr.QNet().state_dict(), reward=lr.reward_constants(call_human_cost),
              train_config={"format": lr.FORMAT_VERSION, "seed": seed})
    ck.update(overrides)
    lr.save_checkpoint(path, **ck)
    return Path(path)


def random_obs(rng):
    vals = [rng.choice([0.0, 1.0]), rng.randint(0, 30), rng.randint(0, 4), rng.choice([0.0, 1.0]),
            rng.choice([0.0, 1.0]), rng.randint(0, 60), rng.randint(0, 60), *[rng.choice([0.0, 1.0]) for _ in range(4)],
            rng.random()]
    return dict(zip(RecoveryHook.OBS_KEYS, (float(v) for v in vals)))


class TestObsToTensor(unittest.TestCase):
    # inject: return a list/float64 tensor, a (1, 12) shape, or reorder OBS_KEYS
    def test_shape_dtype_order(self):
        obs = {k: float(i + 1) for i, k in enumerate(RecoveryHook.OBS_KEYS)}
        x = lr.obs_to_tensor(obs)
        self.assertEqual(tuple(x.shape), (12,))
        self.assertEqual(x.dtype, torch.float32)
        for i, k in enumerate(RecoveryHook.OBS_KEYS):
            self.assertAlmostEqual(float(x[i]), (i + 1) / lr.OBS_SCALE[k], places=6, msg=k)
        shuffled = dict(reversed(list(obs.items())))  # key order of the dict does not matter
        self.assertTrue(torch.equal(lr.obs_to_tensor(shuffled), x))

    # inject: ignore the obs_scale argument and always use OBS_SCALE
    def test_uses_given_scale(self):
        obs = {k: 1.0 for k in RecoveryHook.OBS_KEYS}
        scale = dict(lr.OBS_SCALE, stuck_count=2.0)
        i = RecoveryHook.OBS_KEYS.index("stuck_count")
        self.assertAlmostEqual(float(lr.obs_to_tensor(obs, scale)[i]), 0.5)
        self.assertAlmostEqual(float(lr.obs_to_tensor(obs)[i]), 1.0 / lr.OBS_SCALE["stuck_count"])

    # inject: skip the key check (a KeyError or a silently ignored extra key instead of ValueError)
    def test_missing_and_extra_keys_raise(self):
        obs = {k: 0.0 for k in RecoveryHook.OBS_KEYS}
        missing = dict(obs)
        missing.pop("path_len")
        with self.assertRaises(ValueError):
            lr.obs_to_tensor(missing)
        with self.assertRaises(ValueError):
            lr.obs_to_tensor(dict(obs, extra=1.0))


class TestDecide(unittest.TestCase):
    def _const_net(self, bias):
        net = lr.QNet()
        for p in net.parameters():
            torch.nn.init.zeros_(p)
        net.net[-1].bias.data = torch.tensor(bias, dtype=torch.float32)
        return net

    # inject: use torch.argmax over a reversed copy, or pick the last maximum
    def test_greedy_ties_go_to_lowest_index(self):
        obs = {k: 1.0 for k in RecoveryHook.OBS_KEYS}
        for bias, want in (([1, 1, 0, 0, 1], "wait"), ([0, 2, 2, 0, 2], "back_off"), ([0, 0, 0, 0, 0], "wait"),
                           ([0, 0, 0, 3, 3], "abandon"), ([0, 0, 0, 0, 1], "call_human")):
            self.assertEqual(lr.LearnedRecovery(self._const_net(bias)).decide(obs), want, bias)

    # inject: return an action index instead of its name, or an unlisted string
    def test_only_actions_and_default_is_greedy(self):
        torch.manual_seed(3)
        pol = lr.LearnedRecovery(lr.QNet())
        self.assertEqual(pol.epsilon, 0.0)
        rng = random.Random(0)
        for _ in range(100):
            self.assertIn(pol.decide(random_obs(rng)), ACTIONS)
        eps = lr.LearnedRecovery(lr.QNet(), epsilon=1.0, seed=5)
        seen = {eps.decide(random_obs(rng)) for _ in range(200)}
        self.assertEqual(seen, set(ACTIONS))  # epsilon 1: uniform over all five

    # inject: make the exploration RNG global/unseeded
    def test_epsilon_greedy_reproducible_per_seed(self):
        torch.manual_seed(3)
        net = lr.QNet()
        obs = [random_obs(random.Random(i)) for i in range(60)]
        a = [lr.LearnedRecovery(net, epsilon=0.5, seed=9).decide(o) for o in obs]
        b = [lr.LearnedRecovery(net, epsilon=0.5, seed=9).decide(o) for o in obs]
        self.assertEqual(a, b)


class TestCheckpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    # inject: save an nn.Module/numpy array into the checkpoint (weights_only load fails) or change a stored value
    def test_roundtrip_identical_decisions_weights_only(self):
        path = make_ckpt(self.dir / "a.pt", seed=1)
        ck = torch.load(path, weights_only=True)
        self.assertEqual(ck["obs_keys"], list(RecoveryHook.OBS_KEYS))
        self.assertEqual(ck["actions"], list(ACTIONS))
        self.assertEqual(ck["reward"], lr.reward_constants())
        torch.manual_seed(1)
        direct = lr.LearnedRecovery(lr.QNet())
        loaded = lr.LearnedRecovery.load(path)
        rng = random.Random(0)
        for _ in range(200):
            o = random_obs(rng)
            self.assertEqual(loaded.decide(o), direct.decide(o))

    # inject: ignore the stored obs_scale (use the module constant) when loading
    def test_loaded_checkpoint_scale_is_used(self):
        scale = dict(lr.OBS_SCALE, stuck_count=5.0, path_len=7.0)
        path = make_ckpt(self.dir / "scale.pt", obs_scale=scale)
        pol = lr.LearnedRecovery.load(path)
        self.assertEqual(pol.obs_scale, scale)
        rng = random.Random(1)
        for _ in range(50):
            o = random_obs(rng)
            with torch.no_grad():
                want = ACTIONS[lr.greedy_index(pol.net(lr.obs_to_tensor(o, scale)))]
            self.assertEqual(pol.decide(o), want)

    # inject: drop the obs_keys / actions comparison in load_checkpoint
    def test_mismatched_keys_or_actions_raise(self):
        good = make_ckpt(self.dir / "g.pt")
        ck = torch.load(good, weights_only=True)
        bad_keys = dict(ck, obs_keys=list(reversed(ck["obs_keys"])))
        bad_actions = dict(ck, actions=ck["actions"][:-1])
        for name, bad in (("keys.pt", bad_keys), ("actions.pt", bad_actions)):
            torch.save(bad, self.dir / name)
            with self.assertRaises(ValueError):
                lr.LearnedRecovery.load(self.dir / name)
        lr.LearnedRecovery.load(good)  # the unmodified one still loads

    # inject: seed torch differently per process, or break ties with randomness
    def test_greedy_deterministic_across_processes(self):
        path = make_ckpt(self.dir / "p.pt", seed=2)
        code = ("import sys, random, json; sys.path.insert(0, %r); sys.path.insert(0, %r)\n"
                "from warehouse_rl import learned_recovery as lr\n"
                "from test_learned_recovery import random_obs\n"
                "pol = lr.LearnedRecovery.load(sys.argv[1]); rng = random.Random(0)\n"
                "print(json.dumps([pol.decide(random_obs(rng)) for _ in range(300)]))\n"
                % (str(ROOT / "src"), str(ROOT / "tests")))
        outs = [subprocess.run([sys.executable, "-c", code, str(path)], capture_output=True, text=True, timeout=120)
                for _ in range(2)]
        for o in outs:
            self.assertEqual(o.returncode, 0, o.stderr)
        self.assertEqual(outs[0].stdout, outs[1].stdout)
        pol, rng = lr.LearnedRecovery.load(path), random.Random(0)
        self.assertEqual(json.loads(outs[0].stdout), [pol.decide(random_obs(rng)) for _ in range(300)])


class TestSeam(unittest.TestCase):
    # inject: build the env with the registered timeout policy only (no swap), or call the policy twice per event
    def test_every_decision_goes_to_the_learned_policy(self):
        from warehouse_rl.policy import StuckAwareCtaPolicy

        torch.manual_seed(4)
        pol = lr.LearnedRecovery(lr.QNet(), epsilon=0.3, seed=1)
        cfg = {"breakdown": {"rate_per_hour": 8, "duration": [20, 60], "agent_types": ["agv"]}}
        env = lr.make_learned_env("tarware-medium-8agvs-4pickers-globalobs-v1", 200, cfg, pol, 60)
        try:
            self.assertIsInstance(env.env, RecoveryHook)
            self.assertIs(env.env._recovery, pol)
            obs, info = env.reset(seed=3)
            disp = StuckAwareCtaPolicy()
            disp.reset(env)
            stuck = clash = 0
            for _ in range(200):
                obs, _, _, _, info = env.step(disp.act(obs, info["action_mask"], info))
                stuck += int(info["recovery_stuck_events"])
                clash += int(info["recovery_clash_events"])
            self.assertGreater(stuck + clash, 0)
            self.assertEqual(pol.calls, env.env.decide_calls)
            self.assertEqual(pol.calls, stuck + clash)
        finally:
            env.close()


class TestEvaluateLearned(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.ck1 = make_ckpt(cls.dir / "c1.pt", seed=1, call_human_cost=30)
        cls.ck2 = make_ckpt(cls.dir / "c2.pt", seed=2)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_ev(self, *args, policy="stuck_aware_cta", out=None):
        return subprocess.run([sys.executable, EVALUATE, "--policy", policy, "--env", SMALL, "--seeds", "0-1",
                               "--steps", "60", "--workers", "2", "--results-dir", str(out or self.dir / "res"),
                               *args], capture_output=True, text=True, timeout=300)

    # inject: record the checkpoint path only (no sha256), the wrong tag, or the default cost instead of the stored one
    def test_rows_and_doc_carry_learned_config(self):
        r = self.run_ev("--recovery", f"learned:{self.ck1}")
        self.assertEqual(r.returncode, 0, r.stderr)
        sha = lr.file_sha256(self.ck1)
        path = self.dir / "res" / f"stuck_aware_cta_{SMALL}_60_learned-{sha[:10]}.json"
        doc = json.loads(path.read_text())
        want = {"name": "learned", "checkpoint": str(self.ck1), "sha256": sha, "call_human_cost": 30}
        self.assertEqual(doc["recovery"], want)
        self.assertEqual(doc["recovery_tag"], f"learned-{sha[:10]}")
        self.assertEqual(len(doc["rows"]), 2)
        for row in doc["rows"]:
            self.assertEqual(row["recovery"], want)
            self.assertEqual(row["pick_rate"], row["deliveries"] * 3600 / (5 * 60))
            for k in ev.RECOVERY_SUMS:
                self.assertIn(k, row)

    # inject: let a second checkpoint write into the first one's file
    def test_different_checkpoint_cannot_merge(self):
        out = self.dir / "merge"
        self.assertEqual(self.run_ev("--recovery", f"learned:{self.ck1}", out=out).returncode, 0)
        sha1 = lr.file_sha256(self.ck1)
        f1 = out / f"stuck_aware_cta_{SMALL}_60_learned-{sha1[:10]}.json"
        sha2 = lr.file_sha256(self.ck2)
        f2 = out / f"stuck_aware_cta_{SMALL}_60_learned-{sha2[:10]}.json"
        self.assertNotEqual(f1, f2)
        f2.write_text(f1.read_text())  # pretend ck1's file sits where ck2 will write
        r = self.run_ev("--recovery", f"learned:{self.ck2}", out=out)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("refusing to merge", r.stderr)

    # inject: drop the policy check for the learned spec
    def test_learned_needs_stuck_aware_cta(self):
        for pol in ("cta", "random"):
            r = self.run_ev("--recovery", f"learned:{self.ck1}", policy=pol, out=self.dir / "bad")
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("ValueError", r.stderr)

    # inject: import torch at the top of evaluate.py or run_seed
    def test_torch_not_imported_without_learned(self):
        code = ("import sys; sys.path.insert(0, %r); sys.path.insert(0, %r)\n"
                "import evaluate as ev\n"
                "row = ev.run_seed('stuck_aware_cta', %r, 30, 0, disturb={}, recovery={'name': 'timeout', "
                "'call_human_cost': 60})\n"
                "print('torch' in sys.modules, row['pick_rate'])\n" % (str(ROOT / "src"), str(ROOT / "scripts"), SMALL))
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith("False"), r.stdout)


if __name__ == "__main__":
    unittest.main()

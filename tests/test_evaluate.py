import importlib.util
import os
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from warehouse_rl.env import WarehouseEnv
from warehouse_rl.policy import CtaPolicy, RandomPolicy

_spec = importlib.util.spec_from_file_location("evaluate_script", ROOT / "scripts" / "evaluate.py")
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)

ENV_ID = "tarware-small-4agvs-2pickers-globalobs-v1"
SCRIPT = str(ROOT / "scripts" / "evaluate.py")


def run_cli(policy, seeds, steps, results_dir, workers=2):
    return subprocess.run(
        [sys.executable, SCRIPT, "--policy", policy, "--env", ENV_ID, "--seeds", seeds, "--steps", str(steps),
         "--workers", str(workers), "--results-dir", str(results_dir)],
        capture_output=True, text=True, check=True, timeout=300)


def independent_deliveries(policy_name, seed, steps):
    """Sequential in-process loop, deliberately not evaluate.run_seed."""
    env = WarehouseEnv(ENV_ID, max_steps=steps)
    policy = CtaPolicy() if policy_name == "cta" else RandomPolicy(seed=seed)
    obs, info = env.reset(seed=seed)
    policy.reset(env)
    total = 0
    for _ in range(steps):
        obs, _, _, _, info = env.step(policy.act(obs, info["action_mask"], info))
        total += int(info["shelf_deliveries"])
    env.close()
    return total


class TestParsers(unittest.TestCase):
    def test_parse_seeds(self):  # inject: drop the reversed-range check
        self.assertEqual(ev.parse_seeds("0-29"), list(range(30)))
        self.assertEqual(ev.parse_seeds("0-3,7"), [0, 1, 2, 3, 7])
        self.assertEqual(ev.parse_seeds("5"), [5])
        for bad in ["", "5-2", "5-2,7", "a", "-1"]:
            with self.assertRaises(ValueError, msg=bad):
                ev.parse_seeds(bad)

    def test_parse_steps(self):
        self.assertEqual(ev.parse_steps("500,2000"), [500, 2000])
        for bad in ["0", "", "x", "5-6"]:
            with self.assertRaises(ValueError, msg=bad):
                ev.parse_steps(bad)

    def test_resolve_workers(self):  # inject: SCHED_WORKERS ignored / cap removed
        import os
        fallback = max(1, os.cpu_count() - 2)
        self.assertEqual(ev.resolve_workers(5, {"SCHED_WORKERS": "3"}), 5)
        self.assertEqual(ev.resolve_workers(None, {"SCHED_WORKERS": "3"}), 3)
        self.assertEqual(ev.resolve_workers(None, {"SCHED_WORKERS": ""}), fallback)
        self.assertEqual(ev.resolve_workers(None, {"SCHED_WORKERS": "x"}), fallback)
        self.assertEqual(ev.resolve_workers(None, {}), fallback)
        self.assertEqual(ev.resolve_workers(8, {}, n_tasks=2), 2)
        self.assertEqual(ev.resolve_workers(8, {}, n_tasks=0), 1)
        with self.assertRaises(ValueError):
            ev.resolve_workers(0, {})

    def test_summarise(self):  # inject: ddof=0
        s = ev.summarise([1, 2, 3, 4])
        sd = 1.2909944487358056
        self.assertAlmostEqual(s["mean"], 2.5)
        self.assertAlmostEqual(s["sd"], sd, places=6)
        self.assertAlmostEqual(s["ci95_low"], 2.5 - 3.182 * sd / 2, places=6)
        self.assertAlmostEqual(s["ci95_high"], 2.5 + 3.182 * sd / 2, places=6)
        one = ev.summarise([7])
        self.assertEqual((one["sd"], one["ci95_low"], one["ci95_high"]), (0.0, 7.0, 7.0))


class TestCli(unittest.TestCase):
    def _check(self, policy):
        with tempfile.TemporaryDirectory() as d:
            run_cli(policy, "0-3", 100, d)
            doc = json.loads((Path(d) / f"{policy}_{ENV_ID}_100.json").read_text())
        for k in ["policy", "env", "steps", "rows", "n", "pick_rate_mean", "pick_rate_sd", "ci95_low", "ci95_high"]:
            self.assertIn(k, doc)
        self.assertEqual([r["seed"] for r in doc["rows"]], [0, 1, 2, 3])
        for r in doc["rows"]:
            self.assertEqual(r["steps"], 100)
            self.assertAlmostEqual(r["pick_rate"], r["deliveries"] * 3600 / (5 * 100))
            self.assertEqual(r["deliveries"], independent_deliveries(policy, r["seed"], 100), r["seed"])

    def test_cta_parallel_matches_sequential(self):  # inject: worker-shared env or wrong steps
        self._check("cta")

    def test_random_parallel_matches_sequential(self):  # inject: unseeded / global RNG
        self._check("random")

    def test_resume(self):  # inject: ignore existing file
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / f"cta_{ENV_ID}_100.json"
            run_cli("cta", "0-1", 100, d)
            first = json.loads(path.read_text())["rows"]
            run_cli("cta", "0-3", 100, d)
            rows = json.loads(path.read_text())["rows"]
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[:2], first)  # wall_s identical: not recomputed

    def test_paired_delta(self):  # inject: never read the CTA file / cta - policy sign / pair by row index
        cta_rate = {0: 36.0, 1: 72.0, 2: 7.2, 3: 50.4, 9: 999.0}  # distinct per seed; seed 9 not requested
        with tempfile.TemporaryDirectory() as d:
            fake = {"rows": [{"seed": s, "steps": 100, "pick_rate": r} for s, r in sorted(cta_rate.items(), reverse=True)]}
            (Path(d) / f"cta_{ENV_ID}_100.json").write_text(json.dumps(fake))
            out = run_cli("random", "0-3", 100, d).stdout
            rows = json.loads((Path(d) / f"random_{ENV_ID}_100.json").read_text())["rows"]
        diffs = [r["pick_rate"] - cta_rate[r["seed"]] for r in rows]
        exp = ev.summarise(diffs)
        line = next(l for l in out.splitlines() if l.startswith("paired delta"))
        self.assertIn("n_paired=4", line)
        self.assertIn(f"mean_delta={exp['mean']:.2f}", line)
        self.assertIn(f"95% CI=[{exp['ci95_low']:.2f}, {exp['ci95_high']:.2f}]", line)

    def test_multi_steps_known_numbers(self):  # inject: pass steps_list[0] to every run / reuse one file
        # Seed 0 CTA on small: 24 deliveries at 500 steps (= heuristic_episode, see test_regression_cta), 86 at 2000
        # (probed 2026-10-10 through WarehouseEnv + CtaPolicy).
        with tempfile.TemporaryDirectory() as d:
            run_cli("cta", "0", "500,2000", d, workers=1)
            r500 = json.loads((Path(d) / f"cta_{ENV_ID}_500.json").read_text())["rows"]
            r2000 = json.loads((Path(d) / f"cta_{ENV_ID}_2000.json").read_text())["rows"]
        self.assertEqual([(r["seed"], r["steps"], r["deliveries"]) for r in r500], [(0, 500, 24)])
        self.assertEqual([(r["seed"], r["steps"], r["deliveries"]) for r in r2000], [(0, 2000, 86)])


class TestThroughput(unittest.TestCase):
    def _run(self, args, env):
        import os
        with tempfile.TemporaryDirectory() as d:
            subprocess.run([sys.executable, str(ROOT / "scripts" / "throughput.py"), "--env", ENV_ID, "--steps", "20",
                            "--episodes", "1", "--results-dir", d] + args,
                           env={**os.environ, **env}, capture_output=True, text=True, check=True, timeout=120)
            return json.loads((Path(d) / "throughput.json").read_text())

    def test_schema_and_cli_workers(self):  # inject: SCHED_WORKERS='' crashes int() / per-worker list dropped
        doc = self._run(["--workers", "2"], {"SCHED_WORKERS": ""})
        for k in ["env", "workers", "steps", "episodes", "per_worker_steps_per_s", "mean_per_worker_steps_per_s",
                  "total_steps_per_s", "wall_s", "cpu_count"]:
            self.assertIn(k, doc)
        self.assertEqual(doc["workers"], 2)
        self.assertEqual(len(doc["per_worker_steps_per_s"]), 2)
        self.assertTrue(all(v > 0 for v in doc["per_worker_steps_per_s"]))
        self.assertGreater(doc["total_steps_per_s"], 0)
        self.assertGreater(doc["wall_s"], 0)

    def test_sched_workers_env(self):  # inject: ignore SCHED_WORKERS
        self.assertEqual(self._run([], {"SCHED_WORKERS": "2"})["workers"], 2)

    def test_scheduler_command_with_empty_sched_workers(self):  # inject: --workers back to type=int (argparse exits 2)
        # The scheduler runs `throughput.py --workers $SCHED_WORKERS`; an empty variable leaves a bare --workers.
        fallback = max(1, os.cpu_count() - 2)
        self.assertEqual(self._run(["--workers"], {"SCHED_WORKERS": ""})["workers"], fallback)
        self.assertEqual(self._run(["--workers", ""], {"SCHED_WORKERS": ""})["workers"], fallback)


if __name__ == "__main__":
    unittest.main()

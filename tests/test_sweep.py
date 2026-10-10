"""Tests for scripts/sweep.py (smoke mode only; the full 30-seed sweep is a scheduler item) and evaluate.paired_delta."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

_spec = importlib.util.spec_from_file_location("evaluate_script", ROOT / "scripts" / "evaluate.py")
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)

SCRIPT = str(ROOT / "scripts" / "sweep.py")
# sweep -> (grid endpoints, policies)
EXPECTED = {
    "density": ([2, 16], ["cta"]),
    "breakdown": ([0, 16], ["cta", "stuck_aware_cta"]),
    "delay": ([0, 0.3], ["cta", "stuck_aware_cta"]),
    "router": ([2, 16], ["cta", "cta_care"]),
}
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def run(args, results_dir, sched_workers=None):
    env = dict(os.environ)
    if sched_workers is not None:
        env["SCHED_WORKERS"] = sched_workers
    return subprocess.run([sys.executable, SCRIPT, *args, "--results-dir", str(results_dir)],
                          capture_output=True, text=True, timeout=600, env=env)


class TestPairedDelta(unittest.TestCase):
    # inject: pair by row index instead of by seed
    def test_pairs_by_seed_not_position(self):
        a = [dict(seed=s, pick_rate=v) for s, v in [(0, 10.0), (1, 20.0), (2, 30.0)]]
        b = [dict(seed=s, pick_rate=v) for s, v in [(2, 1.0), (0, 4.0), (1, 5.0)]]  # shuffled, same seeds
        d = ev.paired_delta(a, b)
        self.assertEqual(d["n"], 3)
        self.assertAlmostEqual(d["mean"], ((10 - 4) + (20 - 5) + (30 - 1)) / 3)

    def test_common_seeds_and_restriction(self):  # inject: use the union of seeds / ignore the seeds argument
        a = [dict(seed=s, pick_rate=float(s)) for s in (0, 1, 2, 5)]
        b = [dict(seed=s, pick_rate=0.0) for s in (1, 2, 3)]
        self.assertEqual(ev.paired_delta(a, b)["n"], 2)
        d = ev.paired_delta(a, b, seeds=[2, 3])
        self.assertEqual((d["n"], d["mean"]), (1, 2.0))
        self.assertEqual(ev.paired_delta(a, b, seeds=[7])["n"], 0)


class TestSmokeSweep(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.first = run(["--smoke", "--workers", "2"], cls.dir)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_first_run_writes_all_four_files(self):  # inject: drop a sweep / key rows by something else
        self.assertEqual(self.first.returncode, 0, self.first.stderr)
        for name, (grid, policies) in EXPECTED.items():
            doc = json.loads((self.dir / "sweeps" / f"{name}_smoke.json").read_text())
            self.assertEqual(doc["definition"]["grid"], grid)
            self.assertEqual(doc["definition"]["steps"], 500)
            keys = {(r["point"], r["policy"], r["seed"]) for r in doc["rows"]}
            self.assertEqual(keys, {(g, p, s) for g in grid for p in policies for s in (0, 1)})
            self.assertEqual(len(doc["rows"]), len(keys))
            for r in doc["rows"]:
                for f in ("pick_rate", "frozen_fraction", "stuck_agent_steps", "stuck_busy_agent_steps",
                          "abandoned_tasks", "clash_agent_steps"):
                    self.assertIn(f, r)
                self.assertEqual(r["pick_rate"], r["deliveries"] * 3600 / (5 * 500))
                self.assertNotIn("wall_s", r)

    def test_png_with_magic_bytes(self):  # inject: skip plotting
        pngs = sorted(self.dir.glob("sweep_*_smoke.png"))
        self.assertGreaterEqual(len(pngs), 1)
        for p in pngs:
            self.assertEqual(p.read_bytes()[:8], PNG_MAGIC)

    def test_rerun_adds_nothing_and_is_byte_identical(self):  # inject: rewrite or re-run existing keys
        before = {p.name: p.read_bytes() for p in (self.dir / "sweeps").glob("*.json")}
        r = run(["--smoke", "--workers", "2"], self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.count(" 0 jobs to run"), 4, r.stdout)
        self.assertEqual({p.name: p.read_bytes() for p in (self.dir / "sweeps").glob("*.json")}, before)

    def test_definition_mismatch_raises(self):  # inject: skip the stored-definition check
        p = self.dir / "sweeps" / "density_smoke.json"
        doc = json.loads(p.read_text())
        doc["definition"]["steps"] = 501
        with tempfile.TemporaryDirectory() as d2:
            (Path(d2) / "sweeps").mkdir()
            (Path(d2) / "sweeps" / "density_smoke.json").write_text(json.dumps(doc))
            r = run(["--smoke", "--workers", "1", "--only", "a"], d2)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("refusing to merge", r.stderr)


class TestBareWorkers(unittest.TestCase):
    def test_bare_workers_with_empty_sched_workers(self):  # inject: --workers back to type=int
        with tempfile.TemporaryDirectory() as d:
            r = run(["--smoke", "--only", "a", "--workers"], d, sched_workers="")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue((Path(d) / "sweeps" / "density_smoke.json").exists())

    def test_bad_only_fails(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertNotEqual(run(["--smoke", "--only", "z", "--workers", "1"], d).returncode, 0)


class TestFullRunWiring(unittest.TestCase):
    # the full run is not executed here; this pins the grids, seeds and steps it would use
    def test_full_definition(self):  # inject: change a grid, the seed count or the step count
        spec = importlib.util.spec_from_file_location("sweep_script", SCRIPT)
        sw = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(ROOT / "scripts"))
        spec.loader.exec_module(sw)
        self.assertEqual((len(sw.SEEDS), sw.STEPS), (30, 500))
        self.assertEqual(sw.definition("density", False)["grid"], [2, 4, 6, 8, 10, 12, 14, 16])
        self.assertEqual(sw.definition("breakdown", False)["grid"], [0, 1, 2, 4, 8, 16])
        self.assertEqual(sw.definition("delay", False)["grid"], [0, 0.05, 0.1, 0.2, 0.3])
        self.assertEqual(sw.definition("router", False)["policies"], ["cta", "cta_care"])
        self.assertEqual(sw.point_spec("breakdown", 4)[1],
                         {"breakdown": {"rate_per_hour": 4, "duration": [20, 60], "agent_types": ["agv"]}})
        self.assertEqual(sw.point_spec("density", 6)[0], "tarware-medium-6agvs-3pickers-globalobs-v1")


if __name__ == "__main__":
    unittest.main()

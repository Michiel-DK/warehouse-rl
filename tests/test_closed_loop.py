"""scripts/closed_loop.py: the smoke run end to end (under 3 min, writes only into --out-dir) and the share arithmetic."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

_spec = importlib.util.spec_from_file_location("closed_loop_script", ROOT / "scripts" / "closed_loop.py")
cl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cl)


def _tracked_state():
    """`git status --porcelain` plus the file listings of results/ and fleet/data/ (pycache and caches excluded)."""
    status = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    listing = {}
    for d in ("results", "fleet/data"):
        base = ROOT / d
        listing[d] = sorted(str(p.relative_to(ROOT)) for p in base.rglob("*")
                            if p.is_file() and "__pycache__" not in p.parts) if base.exists() else []
    return status, listing


def _rows(values):
    return [dict(seed=i, pick_rate=v) for i, v in enumerate(values)]


class TestShare(unittest.TestCase):
    def test_share_value(self):
        none, und = _rows([10, 10, 10, 10]), _rows([20, 20, 20, 20])
        arm = _rows([15, 15, 15, 15])
        r = cl.share_recovered(arm, none, und)
        self.assertAlmostEqual(r["share"], 0.5)
        self.assertEqual(r["ci95"], [0.5, 0.5])  # no spread across seeds: the CI collapses on the point
        self.assertIsNone(r["reason"])

    def test_null_when_loss_is_small(self):
        none, und = _rows([10, 10]), _rows([10.5, 10.5])  # loss exactly 0.5 = not above the threshold
        r = cl.share_recovered(_rows([11, 11]), none, und)
        self.assertIsNone(r["share"])
        self.assertIsNone(r["ci95"])
        self.assertIn("lines/h", r["reason"])

    def test_bootstrap_is_reproducible(self):
        none, und, arm = _rows([10, 12, 9, 11, 10]), _rows([20, 19, 22, 18, 21]), _rows([13, 12, 15, 11, 14])
        self.assertEqual(cl.share_recovered(arm, none, und), cl.share_recovered(arm, none, und))


class TestSmoke(unittest.TestCase):
    def test_smoke_end_to_end(self):
        before = _tracked_state()
        with tempfile.TemporaryDirectory() as tmp:
            t0 = time.time()
            r = subprocess.run([sys.executable, str(ROOT / "scripts" / "closed_loop.py"), "--smoke", "--out-dir", tmp],
                               capture_output=True, text=True, timeout=600)
            wall = time.time() - t0
            self.assertEqual(r.returncode, 0, r.stdout[-2000:] + r.stderr[-3000:])
            self.assertLess(wall, 180)
            out = Path(tmp)
            self.assertTrue((out / "closed_loop.png").stat().st_size > 0)
            s = json.loads((out / "summary.json").read_text())
            self.assertEqual(s["env"], "tarware-small-4agvs-2pickers-globalobs-v1")
            self.assertEqual(s["n_seeds"], 2)
            self.assertEqual(set(s["arms"]), {"none", "map_a4", "oracle", "undisturbed"})
            self.assertEqual(s["headline_alpha"], 4.0)
            self.assertIn("before", s["headline_alpha_note"])
            self.assertTrue(s["map_tag"] and s["map_generated_at"])
            for name, a in s["arms"].items():
                self.assertEqual(a["n"], 2)
                self.assertEqual(len(a["pick_rate_ci95"]), 2)
                for k in cl.MEANS:
                    self.assertIsInstance(a[f"{k}_mean"], float, (name, k))
            self.assertIsNone(s["arms"]["none"]["alpha"])
            self.assertIsNone(s["arms"]["undisturbed"]["alpha"])
            self.assertEqual((s["arms"]["map_a4"]["alpha"], s["arms"]["oracle"]["alpha"]), (4.0, 4.0))
            for name in ("map_a4", "oracle"):
                a = s["arms"][name]
                self.assertEqual(set(a["paired_delta_vs_none"]), {"mean", "ci95", "n"})
                share = a["share_of_floor_loss_recovered"]
                self.assertTrue(share["share"] is not None or share["reason"])
            self.assertEqual(s["arms"]["none"]["routes_changed_by_map_mean"], 0)
            self.assertGreater(s["arms"]["map_a4"]["map_cells_entered_mean"], 0)
            # the phase A artefacts and every arm's results live under the out dir
            self.assertTrue((out / "phaseA" / "costmap.json").exists())
            for arm in s["arms"]:
                self.assertTrue(list((out / arm).glob("*.json")))
        self.assertEqual(_tracked_state(), before)


if __name__ == "__main__":
    unittest.main()

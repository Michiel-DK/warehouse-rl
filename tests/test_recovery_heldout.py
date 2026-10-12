"""Tests for scripts/recovery_heldout.py (smoke mode only; the 30-seed held-out run is a scheduler item). Each case names
its red-demonstration in an `# inject:` comment."""
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import evaluate as ev
from test_learned_recovery import make_ckpt

SCRIPT = str(ROOT / "scripts" / "recovery_heldout.py")
_spec = importlib.util.spec_from_file_location("recovery_heldout_script", SCRIPT)
rh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rh)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def run(args, results_dir, train_dir):
    return subprocess.run([sys.executable, SCRIPT, *args, "--results-dir", str(results_dir), "--train-dir",
                           str(train_dir)], capture_output=True, text=True, timeout=600)


def make_run(train_dir, name, finished=True, seed=0):
    d = Path(train_dir) / name
    d.mkdir(parents=True)
    make_ckpt(d / "checkpoint.pt", seed=seed)
    (d / "log.json").write_text(json.dumps({"finished": finished}))
    return d


class TestDiscovery(unittest.TestCase):
    # inject: pick up unfinished runs, stray directories, or run dirs without a checkpoint; sort by string
    def test_only_finished_rate_seed_dirs(self):
        with tempfile.TemporaryDirectory() as t:
            make_run(t, "rate2_seed0")
            make_run(t, "rate1_seed1", seed=1)
            make_run(t, "rate1_seed0", seed=2)
            make_run(t, "rate4_seed0", finished=False)
            make_run(t, "stray")
            make_run(t, "rate10_seed0", seed=3)
            (Path(t) / "rate8_seed0").mkdir()
            self.assertEqual([(r, s) for r, s, _ in rh.finished_checkpoints(t)],
                             [("1", 0), ("1", 1), ("2", 0), ("10", 0)])
            labels = [lbl for lbl, _, _ in rh.configs(t)]
            self.assertEqual(labels, ["learned rate1 seed0", "learned rate1 seed1", "learned rate2 seed0",
                                      "learned rate10 seed0", "rule 5/10/25", "timeout"])

    # inject: drop the `finished is True` test, or key on the aborted file instead of it
    def test_aborted_run_dir_is_excluded(self):
        with tempfile.TemporaryDirectory() as t:
            make_run(t, "rate1_seed0")
            d = make_run(t, "rate1_seed1", finished=False, seed=1)
            (d / "log.json").write_text(json.dumps({"finished": False, "aborted": {
                "episode": 40, "eval_pick_rate_mean": 0.0, "reference": 50.0, "abort_below": 0.5}}))
            self.assertTrue((d / "checkpoint.pt").exists())
            self.assertEqual([(r, s) for r, s, _ in rh.finished_checkpoints(t)], [("1", 0)])

    # inject: require at least one checkpoint, or import torch with none
    def test_zero_checkpoints_only_rule_and_timeout(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual([lbl for lbl, _, _ in rh.configs(Path(t) / "missing")], ["rule 5/10/25", "timeout"])
            self.assertEqual([lbl for lbl, _, _ in rh.configs(t)], ["rule 5/10/25", "timeout"])

    # inject: pair by list index instead of seed, or compute the delta against the wrong baseline
    def test_deltas_are_seed_paired_vs_both_baselines(self):
        defn = dict(grid=[1], configs=[dict(label="learned rate1 seed0"), dict(label="rule 5/10/25"),
                                       dict(label="timeout")])
        pr = {"learned rate1 seed0": {0: 10.0, 1: 20.0}, "rule 5/10/25": {1: 14.0, 0: 8.0}, "timeout": {0: 9.0, 1: 15.0}}
        rows = [dict(point=1, config=c, seed=s, pick_rate=v) for c, d in pr.items() for s, v in d.items()]
        d = rh.compute_deltas(defn, rows)
        self.assertEqual(set(d), {"vs_timeout", "vs_rule"})
        self.assertNotIn("timeout", d["vs_timeout"])
        self.assertNotIn("rule 5/10/25", d["vs_rule"])
        want = ev.paired_delta([r for r in rows if r["config"] == "learned rate1 seed0"],
                               [r for r in rows if r["config"] == "timeout"])
        self.assertEqual(d["vs_timeout"]["learned rate1 seed0"], [dict(point=1, **want)])
        self.assertAlmostEqual(want["mean"], (1.0 + 5.0) / 2)  # seed 0: 10-9, seed 1: 20-15
        self.assertAlmostEqual(d["vs_rule"]["learned rate1 seed0"][0]["mean"], (2.0 + 6.0) / 2)
        # the mean cannot tell pairings apart; the sd can: by seed (2, 6) -> sqrt(8), by index (-4, 12) -> sqrt(128)
        self.assertAlmostEqual(d["vs_rule"]["learned rate1 seed0"][0]["sd"], 8 ** 0.5)
        self.assertAlmostEqual(d["vs_timeout"]["rule 5/10/25"][0]["mean"], (-1.0 - 1.0) / 2)

    def test_grid_and_baselines(self):
        self.assertEqual(rh.GRID, [1, 1.5, 2, 3, 4, 6])
        _, rule, _ = rh.configs(tempfile.gettempdir() + "/nonexistent_train_dir")[0]
        self.assertEqual((rule["back_off_after"], rule["reroute_after"], rule["abandon_after"],
                          rule["call_human_after"]), (5, 10, 25, None))


class TestSmokeAndResume(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.train = cls.dir / "train"
        cls.train.mkdir()
        make_run(cls.train, "rate1_seed0")
        make_run(cls.train, "rate2_seed0", finished=False)
        cls.res = cls.dir / "res"
        cls.first = run(["--smoke", "--workers", "4"], cls.res, cls.train)
        cls.path = cls.res / "recovery" / "heldout_smoke.json"

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    # inject: write heldout.json in smoke mode, drop the deltas key, skip the png, or a wrong grid/seed set
    def test_files_rows_and_deltas(self):
        self.assertEqual(self.first.returncode, 0, self.first.stderr)
        self.assertFalse((self.res / "recovery" / "heldout.json").exists())
        doc = json.loads(self.path.read_text())
        self.assertEqual(doc["definition"]["grid"], [1, 6])
        labels = ["learned rate1 seed0", "rule 5/10/25", "timeout"]
        self.assertEqual([c["label"] for c in doc["definition"]["configs"]], labels)
        self.assertEqual({(r["point"], r["config"], r["seed"]) for r in doc["rows"]},
                         {(g, c, s) for g in (1, 6) for c in labels for s in (0, 1)})
        self.assertEqual(set(doc["deltas"]), {"vs_timeout", "vs_rule"})
        self.assertEqual(set(doc["deltas"]["vs_timeout"]), {"learned rate1 seed0", "rule 5/10/25"})
        self.assertEqual(set(doc["deltas"]["vs_rule"]), {"learned rate1 seed0", "timeout"})
        for lst in doc["deltas"]["vs_timeout"].values():
            self.assertEqual([e["point"] for e in lst], [1, 6])
            self.assertTrue(all(e["n"] == 2 for e in lst))
        png = (self.res / "recovery_heldout_smoke.png").read_bytes()
        self.assertEqual(png[:8], PNG_MAGIC)
        learned = [r for r in doc["rows"] if r["config"] == "learned rate1 seed0"]
        sha = doc["definition"]["configs"][0]["sha256"]
        self.assertTrue(all(r["recovery"]["sha256"] == sha for r in learned))
        self.assertTrue(all("wall_s" not in r for r in doc["rows"]))

    # inject: a different dispatcher, steps, map or disturbance schedule in the timeout job; add or drop a row field
    def test_timeout_row_equals_committed_row(self):
        doc = json.loads(self.path.read_text())
        mine = next(r for r in doc["rows"] if r["config"] == "timeout" and r["point"] == 1 and r["seed"] == 0)
        committed = json.loads((ROOT / "results" / "recovery" / "timeout.json").read_text())["rows"]
        theirs = next(r for r in committed if r["point"] == 1 and r["seed"] == 0)
        self.assertEqual(mine, theirs)

    # inject: rewrite or re-run rows already on disk
    def test_rerun_skips_rows_on_disk(self):
        before = self.path.read_bytes()
        again = run(["--smoke", "--workers", "4"], self.res, self.train)
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertIn("0 jobs to run (12 rows already on disk)", again.stdout)
        self.assertEqual(self.path.read_bytes(), before)

    def _copy_state(self, d):
        res, train = Path(d) / "res", Path(d) / "train"
        shutil.copytree(self.train, train)
        (res / "recovery").mkdir(parents=True)
        doc_path = res / "recovery" / "heldout_smoke.json"
        shutil.copy(self.path, doc_path)
        return res, train, doc_path

    def _expect_refusal(self, res, train, doc_path):
        before = doc_path.read_bytes()
        r = run(["--smoke", "--workers", "2"], res, train)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("refusing to merge", r.stderr)
        self.assertEqual(doc_path.read_bytes(), before)  # nothing merged, nothing rewritten

    # inject: key the definition on the checkpoint path only (not its sha256)
    def test_changed_checkpoint_raises(self):
        with tempfile.TemporaryDirectory() as d:
            res, train, doc_path = self._copy_state(d)
            make_ckpt(train / "rate1_seed0" / "checkpoint.pt", seed=99)  # retrained: same path, other weights
            self._expect_refusal(res, train, doc_path)

    # inject: ignore checkpoints that appeared since the file was written
    def test_added_checkpoint_raises(self):
        with tempfile.TemporaryDirectory() as d:
            res, train, doc_path = self._copy_state(d)
            make_run(train, "rate4_seed1", seed=5)
            self._expect_refusal(res, train, doc_path)

    # inject: ignore checkpoints that disappeared since the file was written
    def test_removed_checkpoint_raises(self):
        with tempfile.TemporaryDirectory() as d:
            res, train, doc_path = self._copy_state(d)
            shutil.rmtree(train / "rate1_seed0")
            self._expect_refusal(res, train, doc_path)


if __name__ == "__main__":
    unittest.main()

"""Tests for scripts/recovery_sweep.py (smoke mode only; the 2280-episode sweep is a scheduler item). Each case names
its red-demonstration in an `# inject:` comment."""
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
sys.path.insert(0, str(ROOT / "scripts"))

from warehouse_rl import recovery as rc

SCRIPT = str(ROOT / "scripts" / "recovery_sweep.py")
_spec = importlib.util.spec_from_file_location("recovery_sweep_script", SCRIPT)
rs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rs)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
ROW_FIELDS = ("pick_rate", "deliveries", "stuck_busy_agent_steps", "frozen_agent_steps", "abandoned_tasks",
              "call_human_steps", "recovery_wait", "recovery_back_off", "recovery_reroute", "recovery_abandon",
              "recovery_call_human", "recovery_stuck_events", "recovery_clash_events", "recovery_fallbacks",
              "recovery", "point", "config", "n_agents", "seed")


def run(args, results_dir, sched_workers=None):
    env = dict(os.environ)
    if sched_workers is not None:
        env["SCHED_WORKERS"] = sched_workers
    return subprocess.run([sys.executable, SCRIPT, *args, "--results-dir", str(results_dir)],
                          capture_output=True, text=True, timeout=600, env=env)


class TestSmokeAndResume(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.path = cls.dir / "recovery" / "timeout_smoke.json"
        cls.first = run(["--smoke", "--only", "a", "--workers", "2"], cls.dir)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    # inject: smoke runs one seed or one endpoint, drops a field from the row, or skips the plot
    def test_smoke_rows_and_png(self):
        self.assertEqual(self.first.returncode, 0, self.first.stderr)
        doc = json.loads(self.path.read_text())
        rows = doc["rows"]
        self.assertEqual({(r["point"], r["config"], r["seed"]) for r in rows},
                         {(g, "timeout", s) for g in (1, 8) for s in (0, 1)})
        self.assertEqual(len(rows), 4)
        for r in rows:
            for f in ROW_FIELDS:
                self.assertIn(f, r)
            self.assertNotIn("wall_s", r)
            self.assertEqual(r["pick_rate"], r["deliveries"] * 3600 / (5 * 500))
            self.assertEqual(r["recovery"], {"name": "timeout", "call_human_cost": 60})
            self.assertEqual(r["n_agents"], 12)
        self.assertEqual(doc["definition"]["grid"], [1, 8])
        png = self.dir / "recovery_timeout_smoke.png"
        self.assertEqual(png.read_bytes()[:8], PNG_MAGIC)

    # inject: rewrite or re-run rows already on disk, or key them without the seed
    def test_resume_runs_zero_then_exactly_one(self):
        before = self.path.read_bytes()
        r = run(["--smoke", "--only", "a", "--workers", "2"], self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("[timeout] 0 jobs to run (4 rows already on disk)", r.stdout)
        self.assertNotIn(" jobs on ", r.stdout)
        self.assertEqual(self.path.read_bytes(), before)
        doc = json.loads(before)
        gone = doc["rows"].pop(1)
        self.path.write_text(json.dumps(doc, indent=2))
        r = run(["--smoke", "--only", "a", "--workers", "2"], self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("[timeout] 1 jobs to run (3 rows already on disk)", r.stdout)
        self.assertIn("1 jobs on 1 workers", r.stdout)
        after = json.loads(self.path.read_text())["rows"]
        self.assertEqual(len(after), 4)
        kept = [x for x in json.loads(before)["rows"] if (x["point"], x["seed"]) != (gone["point"], gone["seed"])]
        for x in kept:
            self.assertIn(x, after)
        # deterministic per seed: the recomputed row equals the deleted one
        self.assertIn(gone, after)

    # inject: draw a fabricated delta when the timeout file is missing
    def test_delta_panel_warns_without_timeout_file(self):
        with tempfile.TemporaryDirectory() as d:
            r = run(["--smoke", "--only", "c", "--workers", "2"], d)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("delta panel left empty", r.stdout)
            self.assertEqual((Path(d) / "recovery_rule_smoke.png").read_bytes()[:8], PNG_MAGIC)


class TestFailures(unittest.TestCase):
    # inject: skip the stored-definition check
    def test_edited_stored_definition_raises(self):
        defn = rs.definition("timeout", True)
        defn["steps"] = 501
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "recovery").mkdir()
            (Path(d) / "recovery" / "timeout_smoke.json").write_text(json.dumps(dict(definition=defn, rows=[])))
            r = run(["--smoke", "--workers", "1", "--only", "a"], d)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("refusing to merge", r.stderr)

    # inject: leave best_rule out of the stored definition of sweep d
    def test_different_best_rule_against_existing_file_raises(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "recovery").mkdir()
            (Path(d) / "recovery" / "call_human_smoke.json").write_text(
                json.dumps(dict(definition=rs.definition("call_human", True), rows=[])))
            r = run(["--smoke", "--workers", "1", "--only", "d", "--best-rule", "2,5,10"], d)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("refusing to merge", r.stderr)

    # inject: let --best-rule through unvalidated (A = R + 1 leaves no room for the human rung)
    def test_unusable_best_rule_fails_with_its_own_message(self):
        for bad in ("3,4,5", "3,6", "a,b,c", "6,3,15", "0,2,9"):
            with tempfile.TemporaryDirectory() as d:
                r = run(["--smoke", "--workers", "1", "--only", "d", "--best-rule", bad], d)
            self.assertNotEqual(r.returncode, 0, bad)
            self.assertIn("--best-rule", r.stderr, bad)

    # inject: accept any --only
    def test_bad_only_fails(self):
        for bad in ("z", "", "a,z"):
            with tempfile.TemporaryDirectory() as d:
                self.assertNotEqual(run(["--smoke", "--only", bad, "--workers", "1"], d).returncode, 0, bad)

    # inject: --workers back to type=int (the empty-value case exits 2; a bare --workers never calls the type)
    def test_bare_workers_with_empty_sched_workers(self):
        for workers in (["--workers"], ["--workers", ""]):
            with tempfile.TemporaryDirectory() as d:
                r = run(["--smoke", "--only", "a", *workers], d, sched_workers="")
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertTrue((Path(d) / "recovery" / "timeout_smoke.json").exists())


class TestFullDefinitions(unittest.TestCase):
    # inject: change a grid, the seed count, a threshold triple, the cost list or the reference config
    def test_full_definitions_and_counts(self):
        self.assertEqual((rs.RATES, len(rs.SEEDS), rs.STEPS), ([1, 2, 4, 8], 30, 500))
        self.assertEqual(rs.SMOKE_SEEDS, [0, 1])
        counts = {s: len(rs.definition(s, False)["configs"]) for s in ("timeout", "tuned_timeout", "rule", "call_human")}
        self.assertEqual(counts, {"timeout": 1, "tuned_timeout": 9, "rule": 3, "call_human": 6})
        episodes = {s: counts[s] * 4 * 30 for s in counts}
        self.assertEqual(episodes, {"timeout": 120, "tuned_timeout": 1080, "rule": 360, "call_human": 720})
        self.assertEqual(sum(episodes.values()), 2280)
        smoke = {s: len(rs.definition(s, True)["configs"]) * 2 * 2 for s in counts}
        self.assertEqual(smoke, {"timeout": 4, "tuned_timeout": 36, "rule": 12, "call_human": 24})
        self.assertEqual(sum(smoke.values()), 76)
        self.assertEqual(rs.definition("timeout", False)["configs"][0]["recovery"],
                         {"name": "timeout", "call_human_cost": 60})
        tuned = [c["recovery"] for c in rs.definition("tuned_timeout", False)["configs"]]
        self.assertEqual([(c["replan"], c["abandon"]) for c in tuned],
                         [(r, a) for r in (3, 5, 8) for a in (10, 15, 25)])
        rules = [c["recovery"] for c in rs.definition("rule", False)["configs"]]
        self.assertEqual([(c["back_off_after"], c["reroute_after"], c["abandon_after"], c["call_human_after"])
                          for c in rules], [(2, 5, 10, None), (3, 6, 15, None), (5, 10, 25, None)])

    # inject: set call_human_after to A, drop the reference, or drop best_rule from the stored definition
    def test_call_human_sweep_definition(self):
        for best in ((3, 6, 15), (2, 5, 10), (5, 10, 25)):
            d = rs.definition("call_human", False, best)
            self.assertEqual(d["best_rule"], list(best))
            cfgs = [c["recovery"] for c in d["configs"]]
            self.assertEqual(len(cfgs), 6)
            humans, ref = cfgs[:5], cfgs[5]
            self.assertEqual([c["call_human_cost"] for c in humans], [0, 5, 15, 30, 60])
            for c in humans:
                self.assertEqual((c["back_off_after"], c["reroute_after"], c["abandon_after"]), best)
                self.assertEqual(c["call_human_after"], best[2] - 1)
            self.assertEqual((ref["back_off_after"], ref["reroute_after"], ref["abandon_after"]), best)
            self.assertIsNone(ref["call_human_after"])
            self.assertEqual(d["configs"][5]["label"].endswith("no human"), True)
        self.assertEqual(rs.definition("call_human", False)["best_rule"], [3, 6, 15])

    # inject: build the breakdown schedule locally instead of through sweep.point_spec
    def test_breakdown_schedule_is_sweep_py(self):
        import sweep
        self.assertIs(rs.point_spec, sweep.point_spec)
        self.assertEqual(sweep.point_spec("breakdown", 4)[1],
                         {"breakdown": {"rate_per_hour": 4, "duration": [20, 60], "agent_types": ["agv"]}})
        self.assertEqual(rs.MEDIUM_8, "tarware-medium-8agvs-4pickers-globalobs-v1")


class TestCallHumanIsAccountingOnly(unittest.TestCase):
    # inject: charge the cost as robot time (the step budget), or count call_human_steps at decide time
    def test_cost_changes_only_call_human_steps(self):
        """executed calls = successful _relocate calls (the only site that adds cost x 1 to call_human_steps)."""
        rate, seed = 8, 1
        base = dict(name="rule", back_off_after=3, reroute_after=6, abandon_after=15, call_human_after=14)
        results = {}
        for cost in (5, 30):
            executed = []
            orig = rc._HookedVendor._relocate

            def counting(self, agent, _orig=orig, _ex=executed):
                ok = _orig(self, agent)
                if ok:
                    _ex.append(1)
                return ok

            rc._HookedVendor._relocate = counting
            try:
                cfg = rc.normalise_recovery(dict(base, call_human_cost=cost))
                _, row = rs._job(("call_human", rate, f"cost {cost}", cfg, seed))
            finally:
                rc._HookedVendor._relocate = orig
            results[cost] = (row, len(executed))
        (r5, n5), (r30, n30) = results[5], results[30]
        self.assertGreater(n5, 0, "non-vacuity: no executed call_human at this (rate, seed)")
        self.assertEqual(n5, n30)
        self.assertEqual(r5["call_human_steps"], 5 * n5)
        self.assertEqual(r30["call_human_steps"], 30 * n30)
        self.assertGreaterEqual(r5["recovery_call_human"], n5)  # decisions >= executed (fallbacks)
        drop = {"call_human_steps", "recovery", "config"}
        self.assertEqual({k: v for k, v in r5.items() if k not in drop}, {k: v for k, v in r30.items() if k not in drop})


if __name__ == "__main__":
    unittest.main()

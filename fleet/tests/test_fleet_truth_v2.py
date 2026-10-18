"""S10A tests: fleet-truth/2 (time-resolved ground truth), fleet/truth.py truth_positive, the grading and scoring that use
it, the --smoke self-check and the import fence. Envs run strictly one at a time (class-level counters in the vendor env).
Each case names its injection in a `# inject:` comment."""
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "fleet", ROOT / "src", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import grade  # noqa: E402
import hotspot_score  # noqa: E402
import truth as truth_mod  # noqa: E402
from fleet_analyser import decisions, emitter as em, lessons  # noqa: E402
from fleet_analyser.parse import epoch_of  # noqa: E402
from fleet_analyser.store import JsonlStore  # noqa: E402
from warehouse_rl.disturb import resolve_disturb  # noqa: E402

T0 = epoch_of(em.DEFAULT_T0)
RUN = "r"


def v2_truth(**zone):
    base = dict(floor_cells={}, blocked_windows=[], outage_windows=[], frozen_windows=[], burst=None)
    return dict(schema_version="fleet-truth/2", t0=em.DEFAULT_T0, step_seconds=5, steps=500,
                zones={"0": dict(base, **zone)})


def blocked(cell, a, b):
    return dict(cell=cell, start_step=a, end_step=b)


class ListSink:
    def __init__(self):
        self.lines = []

    def write(self, serial, line, timestamp=None, header_id=None):
        self.lines.append(line)

    def stats(self):
        return dict(messages=len(self.lines), bytes_uncompressed=sum(map(len, self.lines)), bytes_compressed=None,
                    files=[])

    def close(self):
        pass


class TestWindowExtraction(unittest.TestCase):
    def test_steps_maximal_runs(self):
        # inject: end inclusive, drop the run open at the last step, merge two runs split by a gap, drop step 0
        per_step = [{"a"}, {"a"}, set(), {"a", "b"}, {"b"}, {"b"}, {"b"}]
        self.assertEqual(em.windows_from_steps(per_step),
                         [("a", 0, 2), ("a", 3, 4), ("b", 3, 7)])  # a touches step 0; b touches the last step

    def test_overlapping_cells_are_separate_windows_sorted_by_start_then_key(self):
        # inject: collapse overlapping cells into one window, sort by key only
        per_step = [(), ("9,9",), ("1,1", "9,9"), ("1,1", "9,9"), ("1,1",), ()]
        self.assertEqual(em.windows_from_steps(per_step), [("9,9", 1, 4), ("1,1", 2, 5)])

    def test_empty_schedule(self):
        self.assertEqual(em.windows_from_steps([]), [])
        self.assertEqual(em.windows_from_steps([(), ()]), [])
        self.assertEqual(em.windows_from_mask([]), [])

    def test_mask_rows(self):
        # inject: report the agent id instead of the row, or treat a False->True flip at step 0 as a gap
        mask = [[1, 1, 0, 1], [0, 0, 0, 0], [1, 0, 0, 1]]
        self.assertEqual(em.windows_from_mask(mask), [(0, 0, 2), (2, 0, 1), (0, 3, 4), (2, 3, 4)])


class TestTruthPositive(unittest.TestCase):
    def test_cell_rules(self):
        # inject: end inclusive, start exclusive, floor made time-dependent, outage ignored
        t = v2_truth(floor_cells={"1,1": 0.5}, blocked_windows=[blocked("2,2", 10, 20)],
                     outage_windows=[dict(goal_index=0, cell="3,3", start_step=5, end_step=6)])
        tp = lambda cell, a, b: truth_mod.truth_positive(t, 0, cell, a, b)  # noqa: E731
        self.assertEqual(tp("1,1", 0, 0), {"floor"})
        self.assertEqual(tp("2,2", 0, 9), frozenset())  # ends before the window starts
        self.assertEqual(tp("2,2", 0, 10), {"blocked"})  # a <= step_to
        self.assertEqual(tp("2,2", 19, 30), {"blocked"})
        self.assertEqual(tp("2,2", 20, 30), frozenset())  # b > step_from fails: end is exclusive
        self.assertEqual(tp("3,3", 5, 5), {"outage"})
        self.assertEqual(tp("3,3", 6, 9), frozenset())
        self.assertEqual(tp("4,4", 0, 500), frozenset())
        self.assertEqual(tp("1,1", 600, 700), {"floor"})

    def test_frozen_serial_matching_uses_the_emitted_serial(self):
        # inject: match on agent_index / a zero-based serial
        t = v2_truth(frozen_windows=[dict(agent_index=0, serial="Z3-01", start_step=2, end_step=8)])
        t["zones"]["3"] = t["zones"].pop("0")
        self.assertTrue(truth_mod.truth_positive(t, 3, "Z3-01", 0, 2))
        self.assertFalse(truth_mod.truth_positive(t, 3, "Z3-00", 0, 100))
        self.assertFalse(truth_mod.truth_positive(t, 3, "Z3-01", 8, 9))

    def test_v1_file_needs_no_t0_and_no_steps(self):
        # inject: robots positive on v1, steps required on v1
        v1 = dict(schema_version="fleet-truth/1", zones={"0": dict(floor_cells={"1,1": 0.5})})
        self.assertTrue(truth_mod.is_v1(v1))
        self.assertEqual(truth_mod.truth_positive(v1, 0, "1,1", None, None), {"floor"})
        self.assertFalse(truth_mod.truth_positive(v1, 0, "2,2", None, None))
        self.assertFalse(truth_mod.truth_positive(v1, 0, "Z0-01", None, None))
        self.assertEqual(truth_mod.forecast_steps(v1, 12345, {}), (None, None))
        self.assertEqual(truth_mod.lesson_steps(v1, None, 5), (None, None))

    def test_burst_is_never_a_positive(self):
        t = v2_truth(burst=dict(start_step=0, end_step=500, extra=9))
        self.assertFalse(truth_mod.truth_positive(t, 0, "1,1", 0, 500))
        self.assertFalse(truth_mod.truth_positive(t, 0, "Z0-01", 0, 500))


def forecast(store, cell, step, horizon_s, zone="0"):
    decisions.record_decision(store, run=RUN, kind="hotspot_forecast", subject=f"Z{zone}:{cell}",
                              start_iso=f"s{step}-{horizon_s}", decided_at=T0 + step * 5,
                              claim=dict(horizon_s=horizon_s, rank=1), rationale="x", expected=1.0, grade_after=0)


def truth_rows(store, source="truth"):
    out = {}
    for d in store.select("decisions", {"run": RUN}):
        for g in store.select("forecast_grades", {"id": d["id"], "grade_source": source}):
            out[d["subject"] + "@" + str(d["decided_at"])] = g["verdict"]
    return out


class TestGradeTruthV2(unittest.TestCase):
    def test_horizon_reaching_a_window_is_a_hit(self):
        # inject: ignore the horizon (grade the issue step only), use <= for the window end, off-by-one on s + horizon
        t = v2_truth(blocked_windows=[blocked("3,3", 40, 60)])
        with tempfile.TemporaryDirectory() as d:
            st = JsonlStore(d)
            forecast(st, "3,3", 10, 150)  # s + 30 = 40 >= a: hit
            forecast(st, "3,3", 9, 150)  # s + 30 = 39 < a: false alarm
            forecast(st, "3,3", 60, 150)  # window over (b = 60 is exclusive): false alarm
            forecast(st, "3,3", 59, 5)  # issued inside the window: hit
            forecast(st, "4,4", 45, 150)  # other cell: false alarm
            self.assertEqual(grade.grade_truth(st, RUN, t), dict(graded=5))
            self.assertEqual(truth_rows(st), {f"Z0:3,3@{T0 + 50}": "hit", f"Z0:3,3@{T0 + 45}": "false_alarm",
                                              f"Z0:3,3@{T0 + 300}": "false_alarm", f"Z0:3,3@{T0 + 295}": "hit",
                                              f"Z0:4,4@{T0 + 225}": "false_alarm"})

    def test_floor_cell_is_a_hit_whenever(self):
        t = v2_truth(floor_cells={"3,3": 0.5})
        with tempfile.TemporaryDirectory() as d:
            st = JsonlStore(d)
            forecast(st, "3,3", 400, 100)
            grade.grade_truth(st, RUN, t)
            self.assertEqual(list(truth_rows(st).values()), ["hit"])


def lesson(store, kind, subject, ws, we, zone="0"):
    claim = dict(lesson_kind=kind, zone=zone, subject=subject, window_start=T0 + ws * 5, window_end=T0 + we * 5)
    decisions.record_decision(store, run=RUN, kind=lessons.KIND, subject=f"{kind}|{subject}", start_iso=str(we),
                              decided_at=T0 + we * 5, claim=claim, rationale="x", expected=None, grade_after=0)


class TestGradeLessonTruth(unittest.TestCase):
    def verdicts(self, store):
        out = {}
        for d in store.select("decisions", {"run": RUN, "kind": lessons.KIND}):
            for g in store.select("forecast_grades", {"id": d["id"], "grade_source": "lesson_truth"}):
                out[lessons.claim_of(d)["subject"]] = g["verdict"]
        return out

    def test_v2_hot_robot_and_hot_cell_graded_over_the_lesson_window(self):
        # inject: skip hot_robot, treat the lesson window end as inclusive, grade a lesson against the whole run
        t = v2_truth(frozen_windows=[dict(agent_index=0, serial="Z0-01", start_step=130, end_step=135)],
                     blocked_windows=[blocked("5,5", 139, 150), blocked("6,6", 140, 150), blocked("7,7", 90, 100)])
        with tempfile.TemporaryDirectory() as d:
            st = JsonlStore(d)
            lesson(st, "hot_robot", "Z0:Z0-01", 100, 140)  # overlaps the frozen window: hit
            lesson(st, "hot_robot", "Z0:Z0-02", 100, 140)  # other robot: false alarm
            lesson(st, "hot_robot", "Z0:Z0-01", 140, 180)  # frozen window ended before: false alarm
            lesson(st, "hot_cell", "Z0:cell 5,5", 100, 140)  # last step 139: hit
            lesson(st, "hot_cell", "Z0:cell 6,6", 100, 140)  # window [100,140) excludes step 140: false alarm
            lesson(st, "hot_cell", "Z0:cell 7,7", 100, 140)  # blocked [90,100) ends exactly at the lesson start: false alarm
            self.assertEqual(grade.grade_lesson_truth(st, RUN, t), dict(graded=6))
            rows = [(lessons.claim_of(d)["subject"], lessons.claim_of(d)["window_start"],
                     g["verdict"], sorted(g))
                    for d in st.select("decisions", {"run": RUN, "kind": lessons.KIND})
                    for g in st.select("forecast_grades", {"id": d["id"]})]
            by = {(s, ws): v for s, ws, v, _ in rows}
            self.assertEqual(by[("Z0:Z0-01", T0 + 500)], "hit")
            self.assertEqual(by[("Z0:Z0-02", T0 + 500)], "false_alarm")
            self.assertEqual(by[("Z0:Z0-01", T0 + 700)], "false_alarm")
            self.assertEqual(by[("Z0:cell 5,5", T0 + 500)], "hit")
            self.assertEqual(by[("Z0:cell 6,6", T0 + 500)], "false_alarm")
            self.assertEqual(by[("Z0:cell 7,7", T0 + 500)], "false_alarm")
            self.assertTrue(all(d["status"] == "open" for d in st.select("decisions", {"run": RUN, "kind": "lesson"})))
            # row shape unchanged: the same columns as a v1 lesson_truth row
            (g,) = st.select("forecast_grades", {"grade_source": "lesson_truth", "verdict": "false_alarm"})[:1]
            self.assertEqual(sorted(g), sorted(["id", "run", "grade_source", "outcome", "expected", "error", "verdict",
                                                "horizon_s", "graded_at", "window_end"]))

    def test_v1_hot_cell_lesson_unchanged_and_no_robot_rows(self):
        # inject: grade v1 hot_robot lessons as false alarms, change the v1 floor rule
        v1 = dict(schema_version="fleet-truth/1", zones={"0": dict(floor_cells={"9,9": 0.5})})
        with tempfile.TemporaryDirectory() as d:
            st = JsonlStore(d)
            lesson(st, "hot_cell", "Z0:cell 9,9", 100, 140)
            lesson(st, "hot_cell", "Z0:cell 7,7", 100, 140)
            lesson(st, "hot_robot", "Z0:Z0-01", 100, 140)
            self.assertEqual(grade.grade_lesson_truth(st, RUN, v1), dict(graded=2))
            self.assertEqual(self.verdicts(st), {"Z0:cell 9,9": "hit", "Z0:cell 7,7": "false_alarm"})


STICKY = Path(os.environ.get("WR_STICKY_PHASEA", ROOT / "results" / "closed_loop_sticky" / "phaseA"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@unittest.skipUnless((STICKY / "store").is_dir() and (STICKY / "truth.json").is_file(),
                     "sticky phaseA store absent (untracked); set WR_STICKY_PHASEA")
class TestV1Regression(unittest.TestCase):
    """The v1 sticky run graded with v2 code must equal master 8ad6120 byte for byte."""

    def test_sticky_phaseA_grades_and_scores_unchanged(self):
        # inject: any change to the v1 floor rule, to row order, or a t0 requirement on v1
        with tempfile.TemporaryDirectory() as d:
            store = Path(d) / "store"
            shutil.copytree(STICKY / "store", store)
            truth_path = STICKY / "truth.json"
            self.assertEqual(json.loads(truth_path.read_text())["schema_version"], "fleet-truth/1")
            self.assertEqual(grade.main(["--run", "closed_loop", "--store", f"jsonl:{store}", "--once", "--truth",
                                         str(truth_path)]), 0)
            self.assertEqual(sha(store / "decisions.jsonl"),
                             "21be7a50e3e76e7fd750287010299eac71c2e8f268de935a26ba7940ecff5d79")
            self.assertEqual(sha(store / "forecast_grades.jsonl"),
                             "0cbc1353141f5448d22fbed46ed8b6c19206d5abc2770e267c311b182a96c48d")
            st = JsonlStore(store)
            verdicts = {}
            for g in st.select("forecast_grades", {"run": "closed_loop", "grade_source": "truth"}):
                verdicts[g["verdict"]] = verdicts.get(g["verdict"], 0) + 1
            self.assertEqual(verdicts, {"hit": 1125, "false_alarm": 175})
            out = Path(d) / "hs.json"
            self.assertEqual(hotspot_score.main(["--run-dir", str(STICKY), "--store", f"jsonl:{store}", "--tag",
                                                 "closed_loop", "--out", str(out)]), 0)
            res = json.loads(out.read_text())
            kinds = res.pop("truth_kinds")
            self.assertEqual(kinds["floor"]["positives"], 2400)
            self.assertEqual((kinds["blocked"]["positives"], kinds["outage"]["positives"],
                              kinds["frozen"]["positives"]), (0, 0, 0))
            base = Path("/tmp/s10a-baseline/hotspot_score.json")
            if base.is_file():  # the master output of this lane's baseline run; not part of the repo
                self.assertEqual(res, json.loads(base.read_text()))


class TestTruthKinds(unittest.TestCase):
    def costmap(self, **zones):
        return dict(zones={z: dict(cells) for z, cells in zones.items()})

    def test_positives_equal_per_zone_distinct_counts(self):
        # inject: count windows instead of distinct cells, pool the zones' cells into one set, count frozen rows
        t = dict(zones={
            "0": dict(floor_cells={"1,1": 0.5, "2,2": 0.5},
                      blocked_windows=[blocked("3,3", 0, 5), blocked("3,3", 9, 12), blocked("1,1", 2, 4)],
                      outage_windows=[dict(goal_index=0, cell="4,4", start_step=0, end_step=3)],
                      frozen_windows=[dict(agent_index=0, serial="Z0-01", start_step=0, end_step=3),
                                      dict(agent_index=0, serial="Z0-01", start_step=7, end_step=9)]),
            "1": dict(floor_cells={"1,1": 0.5}, blocked_windows=[blocked("3,3", 0, 5)], outage_windows=[],
                      frozen_windows=[dict(agent_index=1, serial="Z1-02", start_step=0, end_step=3)])})
        cm = self.costmap(**{"0": {"3,3": 5.0, "1,1": 4.0, "9,9": 3.0}, "1": {"3,3": 2.0, "5,5": 1.0}})
        tk = hotspot_score.truth_kinds(t, cm)
        self.assertEqual((tk["floor"]["positives"], tk["blocked"]["positives"], tk["outage"]["positives"]), (3, 3, 1))
        self.assertEqual(tk["any"]["positives"], 4 + 2)  # zone 0: 1,1 2,2 3,3 4,4; zone 1: 1,1 3,3
        self.assertEqual(tk["frozen"], dict(positives=2))
        self.assertNotIn("k", tk["frozen"])
        k20 = tk["blocked"]["k"]["20"]
        self.assertEqual(k20["hits"], 3)  # zone 0: 3,3 and 1,1; zone 1: 3,3
        self.assertEqual(set(tk), {"floor", "blocked", "outage", "any", "frozen"})

    def test_blocked_hits_precision_recall(self):
        t = dict(zones={"0": dict(floor_cells={}, blocked_windows=[blocked("3,3", 0, 5), blocked("1,1", 2, 4)]),
                        "1": dict(floor_cells={}, blocked_windows=[blocked("3,3", 0, 5)])})
        cm = self.costmap(**{"0": {"3,3": 5.0, "9,9": 3.0}, "1": {"3,3": 2.0}})
        k = hotspot_score.truth_kinds(t, cm, ks=(2,))["blocked"]["k"]["2"]
        self.assertEqual(k["hits"], 2)
        self.assertAlmostEqual(k["precision"], 2 / (2 * 2))
        self.assertAlmostEqual(k["recall"], 2 / 3)

    def test_burst_only_truth_has_no_positives_and_zero_precision(self):
        # inject: count burst steps as positives
        t = dict(zones={"0": dict(floor_cells={}, burst=dict(start_step=10, end_step=50, extra=5),
                                  blocked_windows=[], outage_windows=[], frozen_windows=[])})
        tk = hotspot_score.truth_kinds(t, self.costmap(**{"0": {"3,3": 5.0, "1,1": 1.0}}))
        for kind in ("floor", "blocked", "outage", "any"):
            self.assertEqual(tk[kind]["positives"], 0)
            for k in hotspot_score.KS:
                cell = tk[kind]["k"][str(k)]
                self.assertEqual((cell["precision"], cell["hits"], cell["recall"]), (0.0, 0, None))
        self.assertEqual(tk["frozen"]["positives"], 0)


SMALL = hotspot_score.SMOKE_ENV
FIVE = hotspot_score.SMOKE_DISTURB


def run_zone(disturb, steps, zone=0, seed=0):
    _, d = resolve_disturb(json.dumps(disturb))
    sink = ListSink()
    cfg = dict(zone=zone, seed=seed, steps=steps, env_id=SMALL, policy="stuck_aware_cta", disturb=d,
               recovery={"name": "timeout", "call_human_cost": 60}, t0=em.DEFAULT_T0)
    return em.run_zone(cfg, sink), sink


class TestEmitterTruth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result, cls.sink = run_zone(FIVE, 120, zone=3)
        cls.msgs = [json.loads(x) for x in cls.sink.lines]

    def test_all_five_kinds_present_and_well_formed(self):
        # inject: end inclusive, missing kind, row index as serial, burst as a list
        r = self.result
        for key in ("blocked_windows", "outage_windows", "frozen_windows"):
            self.assertTrue(r[key], key)
            for w in r[key]:
                self.assertTrue(0 <= w["start_step"] < w["end_step"] <= 120, w)
        self.assertEqual(r["burst"], dict(start_step=50, end_step=150, extra=4))
        for w in r["blocked_windows"]:
            self.assertRegex(w["cell"], r"^\d+,\d+$")
        self.assertEqual([w["start_step"] for w in r["blocked_windows"]],
                         sorted(w["start_step"] for w in r["blocked_windows"]))
        self.assertTrue(all(set(w) == {"goal_index", "cell", "start_step", "end_step"} for w in r["outage_windows"]))

    def test_frozen_serial_is_the_emitted_serialNumber_of_that_row(self):
        # inject: serial from the row index, a zone-0 serial, or agent.id without zero padding
        n = self.result["snapshot"]["robots"]
        serials = [m["serialNumber"] for m in self.msgs[:n]]  # row i is the i-th message of every step
        for w in self.result["frozen_windows"]:
            self.assertEqual(w["serial"], serials[w["agent_index"]])
            self.assertTrue(w["serial"].startswith("Z3-"))
            for step in range(w["start_step"], w["end_step"]):  # the robot reports BREAKDOWN exactly while frozen
                m = self.msgs[step * n + w["agent_index"]]
                self.assertEqual(m["serialNumber"], w["serial"])
                self.assertEqual([e["errorType"] for e in m["errors"]], ["BREAKDOWN"])

    def test_no_truth_in_any_message_line(self):
        # inject: leak a window key, floor_cells or a burst field into custom
        for key in (b"blocked_windows", b"outage_windows", b"frozen_windows", b"floor_cells", b"burst", b"start_step",
                    b"end_step", b"extra", b"goal_index", b"agent_index"):
            for n, line in enumerate(self.sink.lines):
                self.assertNotIn(key, line, (n, key))

    def test_truth_json_v2_top_level(self):
        with tempfile.TemporaryDirectory() as d:
            run = dict(env_id=SMALL, disturb_tag="t", disturb=resolve_disturb(json.dumps(FIVE))[1], steps=120,
                       seed_base=3, t0=em.DEFAULT_T0)
            em.write_truth(Path(d) / "truth.json", run, {3: dict(self.result, seed=3)})
            t = json.loads((Path(d) / "truth.json").read_text())
        self.assertEqual((t["schema_version"], t["t0"], t["step_seconds"]), ("fleet-truth/2", em.DEFAULT_T0, 5))
        zt = t["zones"]["3"]
        self.assertEqual(zt["frozen_windows"], self.result["frozen_windows"])
        self.assertEqual(zt["burst"], self.result["burst"])
        self.assertEqual(smoke_ok(t), [])

    def test_unconfigured_kinds_are_empty(self):
        r, _ = run_zone({"floor": {"cells": 3, "p": [0.3, 0.7]}}, 20)
        self.assertEqual((r["blocked_windows"], r["outage_windows"], r["frozen_windows"], r["burst"]), ([], [], [], None))


def smoke_ok(truth):
    return hotspot_score.smoke_problems(truth)


class TestSmoke(unittest.TestCase):
    def test_empty_list_or_null_burst_is_a_problem(self):
        # inject: a smoke check that always passes
        good = {"zones": {"0": dict(blocked_windows=[1], outage_windows=[1], frozen_windows=[1], burst={"x": 1})}}
        self.assertEqual(hotspot_score.smoke_problems(good), [])
        for key, empty in (("blocked_windows", []), ("outage_windows", []), ("frozen_windows", []), ("burst", None)):
            bad = {"zones": {"0": dict(good["zones"]["0"], **{key: empty})}}
            self.assertEqual(len(hotspot_score.smoke_problems(bad)), 1, key)

    def test_smoke_runs_green_and_writes_only_its_dir(self):
        results = ROOT / "results"
        before = sorted(str(p) for p in results.rglob("*")) if results.exists() else []
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(hotspot_score.main(["--smoke", "--out-dir", d]), 0)
            truth = json.loads((Path(d) / "run" / "truth.json").read_text())
            self.assertEqual(hotspot_score.smoke_problems(truth), [])
            self.assertTrue((Path(d) / "hotspot_smoke.json").is_file())
        after = sorted(str(p) for p in results.rglob("*")) if results.exists() else []
        self.assertEqual(before, after)


class TestImportFence(unittest.TestCase):
    IMPORT = re.compile(r"(?m)^\s*(from\s+(\.*\s*)?truth\b|import\s+truth\b|from\s+fleet\s+import\s+truth\b|"
                        r"import\s+fleet\.truth\b|from\s+fleet\.truth\b)")

    def test_only_grade_and_hotspot_score_import_truth(self):
        # inject: import truth from an analyser module or a viewer script
        importers = {p.relative_to(ROOT / "fleet").as_posix() for p in (ROOT / "fleet").rglob("*.py")
                     if "tests" not in p.parts and self.IMPORT.search(p.read_text())}
        self.assertLessEqual(importers, {"grade.py", "hotspot_score.py"})
        self.assertIn("grade.py", importers)
        for p in (ROOT / "fleet" / "fleet_analyser").glob("*.py"):
            self.assertNotRegex(p.read_text(), self.IMPORT, p.name)


if __name__ == "__main__":
    unittest.main()

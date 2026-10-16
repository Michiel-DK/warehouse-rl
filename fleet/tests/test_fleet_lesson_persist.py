"""Tests for S8L lesson_persist: the second next-window grade of hot_cell / hot_robot lessons ("still at or above the
next window's own average"). Fixtures are reused from test_fleet_lessons.
Each case names its injection in a `# inject:` comment."""
import json
import shutil
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "fleet") not in sys.path:
    sys.path.insert(0, str(ROOT / "fleet"))

import grade  # noqa: E402
import hotspot_score  # noqa: E402
from fleet.tests import test_fleet_lessons as tfl  # noqa: E402
from fleet_analyser import lessons  # noqa: E402
from fleet_analyser.store import JsonlStore, MemoryStore  # noqa: E402

RUN, BASE, W, NEXT = tfl.RUN, tfl.BASE, tfl.W, tfl.NEXT
CELL0 = tfl.cell_stalls(5, 5)  # window-0 hot_cell: cell 9,9 x5, 5 singles: baseline 10 / 6, ratio 3.0
ROBOT0 = dict(eps=tfl.robot_eps(5, 5), robots=(tfl.R4, BASE + 1))  # window-0 hot_robot Z0-01: baseline 10 / 4, ratio 2.0


def cell_case(nxt):
    st = tfl.lesson_then_advance(nxt, BASE + 2 * W)
    return st, lessons.grade_lessons_persist(st, RUN)


def robot_case(nxt_eps, end=BASE + 2 * W):
    st, _ = tfl.grade_case(ROBOT0, dict(eps=nxt_eps), end=end)
    return st, lessons.grade_lessons_persist(st, RUN)


def persist_rows(st):
    return st.select("forecast_grades", {"run": RUN, "grade_source": "lesson_persist"})


def next_cell(k, singles):
    return tfl.cell_stalls(k, singles, start=NEXT)


class TestCoexist(unittest.TestCase):
    def check(self, st, kind, ratio):
        d, c = tfl.one(st, kind)
        (old,) = st.select("forecast_grades", {"id": d["id"], "grade_source": "lesson"})
        (new,) = st.select("forecast_grades", {"id": d["id"], "grade_source": "lesson_persist"})
        self.assertEqual(old["verdict"], "off")  # the old threshold (3.0 / 2.0) no longer holds
        self.assertEqual((new["verdict"], new["expected"], new["outcome"], new["error"], new["horizon_s"],
                          new["window_end"], new["graded_at"]),
                         ("ok", 1.0, ratio, None, W, c["window_end"] + W, BASE + 2 * W))
        self.assertEqual((d["status"], d["verdict"]), ("graded", "off"))  # stamped by the old grade only
        self.assertEqual(len(st.select("forecast_grades", {"id": d["id"]})), 2)

    def test_hot_cell(self):
        # inject: persist row written under grade_source "lesson"; 2.0x = 4 * 3 / 6
        st = tfl.lesson_then_advance(next_cell(4, 2), BASE + 2 * W)
        lessons.grade_lessons(st, RUN)
        self.assertEqual(lessons.grade_lessons_persist(st, RUN), dict(graded=1, open=0))
        self.check(st, "hot_cell", 2.0)

    def test_hot_robot(self):
        # inject: as above; 1.5x = 3 * 3 / 6 (Z0-01 x3, Z0-02 x2, Z0-03 x1)
        st, _ = tfl.grade_case(ROBOT0, dict(eps=tfl.robot_eps(3, 3, base=1000, start=NEXT)))
        self.assertEqual(lessons.grade_lessons_persist(st, RUN), dict(graded=1, open=0))
        self.check(st, "hot_robot", 1.5)

    def test_cycle_writes_both_grades_and_stamps_by_the_old_grade_only(self):
        # inject: cycle() does not call grade_lessons_persist
        for kind in ("hot_cell", "hot_robot"):
            with tempfile.TemporaryDirectory() as d:
                st = JsonlStore(Path(d) / "store")
                if kind == "hot_cell":
                    st.insert("stalls", CELL0 + next_cell(4, 2))
                else:
                    st.insert("stuck_episodes", ROBOT0["eps"] + tfl.robot_eps(3, 3, base=1000, start=NEXT))
                    tfl.robots_in_transitions(st, tfl.R4, ts=BASE + 1)
                tfl.checkpoint(st, BASE + W)
                lessons.extract(st, RUN, 0.2)
                tfl.checkpoint(st, BASE + 2 * W)
                st.close()
                counts = grade.cycle(f"jsonl:{Path(d) / 'store'}", RUN)
                self.assertEqual(counts["lesson"]["persist"], dict(graded=1, open=0))
                st = JsonlStore(Path(d) / "store")
                (dec,) = [x for x in lessons.lessons(st, RUN) if lessons.claim_of(x)["lesson_kind"] == kind]
                got = {g["grade_source"]: g["verdict"] for g in st.select("forecast_grades", {"id": dec["id"]})}
                self.assertEqual(got, {"lesson": "off", "lesson_persist": "ok"})
                self.assertEqual(dec["verdict"], "off")
                st.close()


class TestBaselineIsTheNextWindows(unittest.TestCase):
    """Window-0 hot_cell claim baseline = 10 / 6 = 1.67; hot_robot = 10 / 4 = 2.5."""

    def got(self, st):
        return [g["verdict"] for g in persist_rows(st)], [g["outcome"] for g in persist_rows(st)]

    def test_cell_a_above_next_average_below_claim_baseline_is_ok(self):
        # inject: ratio divided by claim["baseline"] (1 / 1.67 = 0.6 -> off)
        st, _ = cell_case(next_cell(1, 3))  # 9,9 x1 among singles: next average 1.0, count 1 < 1.67
        self.assertEqual(self.got(st), (["ok"], [1.0]))

    def test_cell_b_above_claim_baseline_below_next_average_is_off(self):
        # inject: ratio divided by claim["baseline"] (2 / 1.67 = 1.2 -> ok)
        st, _ = cell_case(next_cell(2, 0) + [tfl.stall("5,5", NEXT) for _ in range(10)])  # n 12, C 2: average 6
        self.assertEqual(self.got(st), (["off"], [round(2 / 6, 4)]))

    def test_cell_c_absent_is_zero_and_off(self):
        # inject: absent subject skipped instead of ratio 0
        st, _ = cell_case([tfl.stall(f"{i},1", NEXT) for i in range(10)])
        self.assertEqual(self.got(st), (["off"], [0]))

    def test_cell_empty_next_window_is_zero_and_off(self):
        st, _ = cell_case([])
        self.assertEqual(self.got(st), (["off"], [0]))

    def test_robot_a(self):
        # inject: ratio divided by claim["baseline"] (2 / 2.5 = 0.8 -> off); next: Z0-01 x2, Z0-02 x2
        st, _ = robot_case(tfl.robot_eps(2, 2, per=2, base=1000, start=NEXT))
        self.assertEqual(self.got(st), (["ok"], [1.0]))

    def test_robot_b(self):
        # inject: ratio divided by claim["baseline"] (3 / 2.5 = 1.2 -> ok); next: Z0-01 x3, Z0-02 x10: average 6.5
        st, _ = robot_case(tfl.robot_eps(3, 10, per=10, base=1000, start=NEXT))
        self.assertEqual(self.got(st), (["off"], [round(3 * 2 / 13, 4)]))

    def test_robot_c_absent(self):
        st, _ = robot_case(tfl.robot_eps(0, 5, base=1000, start=NEXT))
        self.assertEqual(self.got(st), (["off"], [0]))


class TestMissingNextWindowStaysOpen(unittest.TestCase):
    def test_open_then_graded_once(self):
        # inject: the stream_end eligibility check removed
        st = tfl.lesson_then_advance(next_cell(4, 2), BASE + 2 * W - 1)
        self.assertEqual(lessons.grade_lessons_persist(st, RUN), dict(graded=0, open=1))
        self.assertEqual(st.select("forecast_grades", {"run": RUN}), [])  # no persist row, no lesson row
        (d,) = lessons.lessons(st, RUN)
        self.assertEqual(d["status"], "open")
        tfl.checkpoint(st, BASE + 2 * W)
        self.assertEqual(lessons.grade_lessons_persist(st, RUN), dict(graded=1, open=0))
        self.assertEqual(len(persist_rows(st)), 1)
        self.assertEqual(lessons.grade_lessons_persist(st, RUN), dict(graded=0, open=0))
        self.assertEqual(len(persist_rows(st)), 1)

    def test_no_stream_at_all_is_open(self):
        st = MemoryStore()
        st.insert("stalls", CELL0)
        tfl.checkpoint(st, BASE + W)
        lessons.extract(st, RUN, 0.2)
        self.assertEqual(lessons.grade_lessons_persist(st, RUN), dict(graded=0, open=1))


class TestAlreadyStamped(unittest.TestCase):
    def test_stamped_decision_still_gets_its_persist_row_and_is_unchanged(self):
        # inject: the loop skips decisions whose status is not "open"; persist calls decisions.stamp_grade
        st = tfl.lesson_then_advance(next_cell(4, 2), BASE + 2 * W)
        self.assertEqual(lessons.grade_lessons(st, RUN), dict(graded=1, open=0))
        (before,) = lessons.lessons(st, RUN)
        self.assertEqual(before["status"], "graded")
        self.assertEqual(lessons.grade_lessons_persist(st, RUN), dict(graded=1, open=0))
        self.assertEqual(len(persist_rows(st)), 1)
        self.assertEqual(lessons.lessons(st, RUN), [before])


def mixed_store(directory):
    """hot_cell + hot_robot + cause_mix lessons in window 0, each weaker in window 1. Lesson-kind rows only (no
    forecast decisions), so grade.cycle and the old-path simulation grade the same decisions."""
    st = JsonlStore(directory)
    st.insert("stalls", CELL0 + next_cell(4, 2))
    st.insert("stuck_episodes", tfl.robot_eps(5, 5) + tfl.traffic_eps(BASE, 10)
              + tfl.robot_eps(3, 3, base=1000, start=NEXT) + tfl.traffic_eps(NEXT, 10))
    tfl.robots_in_transitions(st, tfl.R4, ts=BASE + 1)
    tfl.checkpoint(st, BASE + W)
    lessons.extract(st, RUN, 0.2)
    tfl.checkpoint(st, BASE + 2 * W)
    st.close()


def old_rows(st):
    """Multiset of json.dumps(sort_keys) of the lesson / lesson_truth grade rows and the lesson decisions."""
    grades = [g for g in st.select("forecast_grades", {"run": RUN}) if g["grade_source"] in ("lesson", "lesson_truth")]
    return Counter(json.dumps(r, sort_keys=True) for r in grades + lessons.lessons(st, RUN))


TRUTH = dict(zones={"0": dict(floor_cells={"9,9": 0.5})})


class TestOldGradeUnchanged(unittest.TestCase):
    def test_old_rows_and_decisions_equal_the_old_path_only(self):
        # inject: persist writes under "lesson", stamps a decision, or changes grade_lessons / next_value
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            mixed_store(d / "new")
            shutil.copytree(d / "new", d / "old")
            (d / "truth.json").write_text(json.dumps(TRUTH))
            grade.cycle(f"jsonl:{d / 'new'}", RUN, truth_path=d / "truth.json")
            old = JsonlStore(d / "old")
            lessons.grade_lessons(old, RUN)
            grade.grade_lesson_truth(old, RUN, TRUTH)
            new = JsonlStore(d / "new")
            kinds = {lessons.claim_of(x)["lesson_kind"] for x in lessons.lessons(new, RUN)}
            self.assertTrue({"hot_cell", "hot_robot", "cause_mix"} <= kinds, kinds)
            want = old_rows(old)
            self.assertEqual(old_rows(new), want)
            self.assertGreater(sum(want.values()), len(lessons.lessons(old, RUN)))  # grade rows really compared
            self.assertEqual(len(persist_rows(new)), 2)  # the new rows exist only on the new side
            self.assertEqual(persist_rows(old), [])
            new.close()
            old.close()


class TestKindFence(unittest.TestCase):
    def test_other_kinds_get_no_persist_row(self):
        # inject: PERSIST_KINDS widened
        self.assertEqual(lessons.PERSIST_KINDS, ("hot_cell", "hot_robot"))
        for kind in ("cause_mix", "avoidable_share", "recurring_pair"):
            w0, ok, _ = tfl.GRADE_CASES[kind]
            st, _ = tfl.grade_case(w0, ok)
            tfl.one(st, kind)
            self.assertEqual(lessons.grade_lessons_persist(st, RUN), dict(graded=0, open=0), kind)
            self.assertEqual(persist_rows(st), [], kind)

    def test_hot_hour_gets_no_persist_row(self):
        st, _ = tfl.grade_case(dict(eps=tfl.hour_eps(12, 4)), dict(eps=tfl.hour_eps(12, 4, day=1, base=1000)),
                               end=BASE + 7200 + 86400, window_h=2, span=7200)
        tfl.one(st, "hot_hour")
        self.assertEqual(lessons.grade_lessons_persist(st, RUN), dict(graded=0, open=0))
        self.assertEqual(persist_rows(st), [])


class TestHotspotScoreLessonGrading(unittest.TestCase):
    FLOOR = dict(zones={"0": dict(floor_cells={})})

    def score(self, st, **kw):
        return hotspot_score.score_run(self.FLOOR, dict(zones={}), [],
                                       st.select("forecast_grades", {"run": RUN}), **kw)

    def test_lesson_grading_counts_by_source_kind_verdict(self):
        # inject: lesson_grading keyed on the wrong kind / source, or verdicts mixed
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            mixed_store(d / "s")
            (d / "truth.json").write_text(json.dumps(TRUTH))
            grade.cycle(f"jsonl:{d / 's'}", RUN, truth_path=d / "truth.json")
            st = JsonlStore(d / "s")
            res = self.score(st, lesson_decisions=st.select("decisions", {"run": RUN, "kind": "lesson"}))
            self.assertEqual(res["lesson_grading"], {
                "lesson": {"hot_cell": {"off": 1}, "hot_robot": {"ok": 1}, "cause_mix": {"ok": 1}},  # traffic robots join R
                "lesson_persist": {"hot_cell": {"ok": 1}, "hot_robot": {"ok": 1}},
                "lesson_truth": {"hot_cell": {"hit": 1}}})
            self.assertEqual(res["grading_counts"]["lesson_persist"], {"ok": 2})
            bare = self.score(st)  # no lesson_decisions: present and empty, nothing else changes
            self.assertEqual(bare["lesson_grading"], {})
            del bare["lesson_grading"]
            self.assertEqual(set(bare), {"zones", "mean", "grading_counts", "rank_grading", "stall_in_episode"})
            self.assertEqual(bare["grading_counts"], res["grading_counts"])
            st.close()

    def test_source_without_rows_is_omitted(self):
        st = tfl.lesson_then_advance(next_cell(4, 2), BASE + 2 * W)
        lessons.grade_lessons(st, RUN)
        res = self.score(st, lesson_decisions=lessons.lessons(st, RUN))
        self.assertEqual(res["lesson_grading"], {"lesson": {"hot_cell": {"off": 1}}})


if __name__ == "__main__":
    unittest.main()

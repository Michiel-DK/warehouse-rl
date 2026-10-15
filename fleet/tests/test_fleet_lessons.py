"""Tests for S8E lessons: extraction rules at their thresholds, Wilson confidence, dedup, windows, next-window grading,
lesson_truth, the roll-ups, the replay export and the page. Scripted MemoryStores, no env, no Docker.
Each case names its injection in a `# inject:` comment (the mutation table of the PR)."""
import copy
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "fleet",):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import grade  # noqa: E402
import hotspot_score  # noqa: E402
import lessons as lessons_cli  # noqa: E402
import replay_export as rx  # noqa: E402
from fleet.tests import test_replay_export as tre  # noqa: E402
from fleet_analyser import decisions, forecast_grade, ledger, lessons  # noqa: E402
from fleet_analyser.store import JsonlStore, MemoryStore  # noqa: E402

RUN = "r"
BASE = 1767225600  # a multiple of 7200, so 0.2 h (720 s) and 2 h windows both start here
W = 720
DOCS = ROOT / "docs" / "replay"


def checkpoint(st, end, zones=("0",), seq=[0]):
    seq[0] += 1
    st.insert("ingest_checkpoints", [dict(run=RUN, path=f"f{seq[0]}", cp_seq=seq[0],
                                          last_message_ts_by_zone=json.dumps({z: end for z in zones}))])


def ep(i, robot="Z0-01", start=BASE + 10, cell=(1, 1), cause="unknown", blocker=None, avoidable=False, zone="0",
       censored=False):
    return dict(run=RUN, episode_id=f"E{zone}-{i}", zone=zone, robot=robot, start=start, cell=list(cell), cause=cause,
                blocker=blocker, avoidable=avoidable, left_censored=censored, resolution="moved")


def stall(cell, start=BASE + 10, zone="0"):
    return dict(run=RUN, zone=zone, robot="Z0-01", cell=cell, start=start, end=start + 5, faulted_episode=False,
                next_occupied=False)


def robots_in_transitions(st, serials, ts=BASE + 1, zone="0"):
    st.insert("transitions", [dict(run=RUN, zone=zone, robot=s, ts=ts, cell=[0, 0], from_state="NONE", to_state="MOVING")
                              for s in serials])


def scripted(end=BASE + W, eps=(), stalls=(), robots=()):
    st = MemoryStore()
    st.insert("stuck_episodes", list(eps))
    st.insert("stalls", list(stalls))
    robots_in_transitions(st, robots)
    checkpoint(st, end)
    return st


def found(st, window_h=0.2):
    lessons.extract(st, RUN, window_h)
    return sorted((lessons.claim_of(d)["lesson_kind"], lessons.claim_of(d)["subject"]) for d in lessons.lessons(st, RUN))


def cell_stalls(k, singles, cell="9,9", start=BASE + 10):
    """k stalls at `cell` plus `singles` stalls at distinct other cells."""
    return [stall(cell, start) for _ in range(k)] + [stall(f"{i},0", start) for i in range(singles)]


class TestWilson(unittest.TestCase):
    def test_hand_computed_value(self):
        # inject: confidence uses p = k / n instead of the Wilson lower bound
        # L(7, 10) = (0.7 + 0.19208 - 1.96 * sqrt(0.021 + 0.009604)) / 1.38416 = 0.39677...; / 0.6 = 0.6613
        self.assertAlmostEqual(lessons.wilson_lower(7, 10), 0.3967732, places=6)
        self.assertEqual(lessons.confidence(7, 10, 0.6), 0.661)
        self.assertNotEqual(lessons.confidence(7, 10, 0.6), round(min(1, 0.7 / 0.6), 3))
        self.assertEqual(lessons.confidence(10, 10, 0.2), 1.0)  # capped at 1

    def test_non_decreasing_in_n_at_fixed_share(self):
        for p, s in ((0.5, 0.9), (0.6, 0.9), (0.7, 1.0), (0.3, 0.9)):
            vals = [lessons.confidence(round(p * n), n, s) for n in range(10, 400, 10) if abs(p * n - round(p * n)) < 1e-9]
            self.assertEqual(vals, sorted(vals))
            self.assertGreater(vals[-1], vals[0])

    def test_claim_confidence_is_wilson_over_s_star(self):
        # hot_cell: A x5 + 5 singles: n = 10, C = 6, s* = 3 / 6
        st = scripted(stalls=cell_stalls(5, 5))
        lessons.extract(st, RUN, 0.2)
        (d,) = lessons.lessons(st, RUN)
        self.assertEqual(lessons.claim_of(d)["confidence"], round(min(1, lessons.wilson_lower(5, 10) / 0.5), 3))


class TestThresholds(unittest.TestCase):
    """Each kind: fires at the threshold (>=), not just below it, not with the support one below n_min."""

    def test_hot_cell(self):
        # inject: `>=` -> `>` on the ratio threshold (m1); support check dropped (m2)
        fires = found(scripted(stalls=cell_stalls(5, 5)))  # k = 5 = n_min, ratio 5 * 6 / 10 = 3.0 exactly
        self.assertEqual(fires, [("hot_cell", "Z0:cell 9,9")])
        self.assertEqual(found(scripted(stalls=cell_stalls(5, 4))), [])  # ratio 5 * 5 / 9 = 2.78
        self.assertEqual(found(scripted(stalls=cell_stalls(4, 20))), [])  # ratio 3.5 but k = 4 < n_min

    def test_hot_robot(self):
        # inject: `>=` -> `>` on the ratio threshold (m1); support check dropped (m2)
        def eps(k, others, per=2):
            rows = [ep(i, "Z0-01", cell=(i, 0)) for i in range(k)]
            rows += [ep(100 + i, f"Z0-{2 + i // per:02d}", cell=(i, 5)) for i in range(others)]
            return rows

        r4 = ["Z0-01", "Z0-02", "Z0-03", "Z0-04"]
        self.assertEqual(found(scripted(eps=eps(5, 5), robots=r4)), [("hot_robot", "Z0:Z0-01")])  # 5 * 4 / 10 = 2.0
        self.assertEqual(found(scripted(eps=eps(5, 6), robots=r4)), [])  # 5 * 4 / 11 = 1.82
        r10 = [f"Z0-{i:02d}" for i in range(1, 11)]
        self.assertEqual(found(scripted(eps=eps(4, 6), robots=r10)), [])  # ratio 4.0 but k = 4 < n_min

    def test_hot_hour(self):
        # inject: `>=` -> `>` on the ratio threshold (m1); support check dropped (m2)
        def eps(h0, h1):
            return ([ep(i, "Z0-01", start=BASE + 100 + i, cell=(i, 0)) for i in range(h0)]
                    + [ep(100 + i, "Z0-02", start=BASE + 3700 + i, cell=(i, 5)) for i in range(h1)])

        two_h = 7200
        end = BASE + two_h
        self.assertEqual(found(scripted(end, eps=eps(12, 4)), 2), [("hot_hour", "Z0:hour 00")])  # 12 * 2 / 16 = 1.5
        self.assertEqual(found(scripted(end, eps=eps(12, 5)), 2), [])  # 12 * 2 / 17 = 1.41
        self.assertEqual(found(scripted(end, eps=eps(9, 3)), 2), [])  # ratio 1.5 but k = 9 < n_min
        # a 0.2 h window holds no whole clock hour: never fires, even for 16 episodes in one hour
        self.assertEqual(lessons.whole_hours(BASE, BASE + W), 0)
        self.assertEqual(found(scripted(eps=eps(16, 0))), [])

    def test_cause_mix(self):
        # inject: `>=` -> `>` on the share threshold (m1); support check dropped (m2); "unknown" allowed (m6)
        def eps(traffic, other, unknown=0):
            rows = [ep(i, f"Z0-{i:02d}", cell=(i, 0), cause="traffic") for i in range(traffic)]
            rows += [ep(100 + i, f"Z0-{50 + i:02d}", cell=(i, 5), cause="faulted_self" if i % 2 else "blocked_by_faulted")
                     for i in range(other)]
            rows += [ep(200 + i, f"Z0-{80 + i:02d}", cell=(i, 9), cause="unknown") for i in range(unknown)]
            return rows

        self.assertEqual(found(scripted(eps=eps(6, 4))), [("cause_mix", "Z0")])  # 6 / 10 = 0.6, n = 10
        self.assertEqual(found(scripted(eps=eps(6, 5))), [])  # 6 / 11 = 0.545
        self.assertEqual(found(scripted(eps=eps(6, 3))), [])  # 6 / 9 = 0.67 but n = 9 < n_min
        # twelve unknown and two traffic: unknown is 86 % of all episodes but is never a lesson, nor part of n
        self.assertEqual(found(scripted(eps=eps(2, 0, unknown=12))), [])
        st = scripted(eps=eps(7, 3, unknown=30))
        lessons.extract(st, RUN, 0.2)
        (d,) = lessons.lessons(st, RUN)
        c = lessons.claim_of(d)
        self.assertEqual((c["metric"], c["n"], c["k"]), ("cause_share:traffic", 10, 7))
        self.assertNotIn("unknown", c["text"])

    def test_cause_mix_ties_break_on_the_cause_name_and_baseline_is_fleet_wide(self):
        rows = [ep(i, f"Z0-{i:02d}", cell=(i, 0), cause="traffic") for i in range(10)]
        rows += [ep(100 + i, f"Z1-{i:02d}", cell=(i, 0), cause="faulted_self", zone="1") for i in range(10)]
        st = scripted(eps=rows)
        lessons.extract(st, RUN, 0.2)
        (d,) = lessons.lessons(st, RUN)
        c = lessons.claim_of(d)
        self.assertEqual((c["value"], c["baseline"]), (1.0, 0.5))  # zone 0 all traffic; fleet half traffic (10 of 20)
        data = lessons.Data(st, RUN)
        w = data.window("0", BASE, BASE + W)
        self.assertEqual(lessons.dominant([dict(k=3, metric="cause_share:traffic"), dict(k=3, metric="cause_share:a")])[0]
                         ["metric"], "cause_share:a")
        self.assertEqual(w["zone"], "0")

    def test_avoidable_share(self):
        # inject: `>=` -> `>` on the share threshold (m1); support check dropped (m2)
        def eps(n, avoid, by="cell"):
            return [ep(i, robot=f"Z0-{i:02d}" if by == "cell" else "Z0-01", cell=(5, 5) if by == "cell" else (i, 0),
                       avoidable=i < avoid) for i in range(n)]

        self.assertEqual(found(scripted(eps=eps(6, 3))), [("avoidable_share", "Z0:cell 5,5")])  # 3 / 6 = 0.5, n = 6
        self.assertEqual(found(scripted(eps=eps(7, 3))), [])  # 3 / 7 = 0.43
        self.assertEqual(found(scripted(eps=eps(4, 4))), [])  # 1.0 but n = 4 < n_min
        # the per-robot subject: robot Z0-01 at 6 different cells, 3 avoidable (hot_robot needs a ratio, not met: 1 robot)
        got = found(scripted(eps=eps(6, 3, by="robot"), robots=["Z0-01", "Z0-02"]))
        self.assertIn(("avoidable_share", "Z0:Z0-01"), got)

    def test_recurring_pair(self):
        # inject: `>=` -> `>` on the count threshold (m1); the threshold test has no separate support (n_min = 3)
        def eps(k):
            return ([ep(i, "Z0-02", cell=(i, 0), cause="blocked_by_stuck", blocker="Z0-01") for i in range(k)]
                    + [ep(50, "Z0-03", cell=(9, 9), cause="traffic")])

        self.assertEqual(found(scripted(eps=eps(3))), [("recurring_pair", "Z0:Z0-01->Z0-02")])
        self.assertEqual(found(scripted(eps=eps(2))), [])

    def test_left_censored_episodes_are_counted(self):
        rows = [ep(i, "Z0-02", cell=(i, 0), cause="blocked_by_stuck", blocker="Z0-01", censored=True) for i in range(3)]
        self.assertEqual(found(scripted(eps=rows)), [("recurring_pair", "Z0:Z0-01->Z0-02")])


class TestWindowsAndDedup(unittest.TestCase):
    def test_window_not_fully_observed_gives_no_lesson(self):
        # inject: evaluate a window before the zone stream reached its end (m4)
        self.assertEqual(found(scripted(end=BASE + W - 1, stalls=cell_stalls(5, 5))), [])
        self.assertEqual(len(found(scripted(end=BASE + W, stalls=cell_stalls(5, 5)))), 1)  # end == window_end counts

    def test_events_are_assigned_to_epoch_aligned_windows(self):
        st = scripted(end=BASE + 2 * W, stalls=cell_stalls(5, 5, start=BASE + W))  # all in the SECOND window
        lessons.extract(st, RUN, 0.2)
        (d,) = lessons.lessons(st, RUN)
        c = lessons.claim_of(d)
        self.assertEqual((c["window_start"], c["window_end"], d["decided_at"]), (BASE + W, BASE + 2 * W, BASE + 2 * W))
        self.assertEqual(d["grade_after"], BASE + 3 * W)

    def test_zones_are_independent(self):
        st = scripted(stalls=cell_stalls(5, 5))
        checkpoint(st, BASE + 5, zones=("0",))  # zone 0 stays at its max; zone 1 never reported
        st.insert("stalls", [stall(c["cell"], zone="1") for c in cell_stalls(5, 5)])
        self.assertEqual(found(st), [("hot_cell", "Z0:cell 9,9")])  # zone 1 has no stream_end: nothing

    def test_claim_keys_dedup_key_and_rerun_creates_nothing(self):
        # inject: add a key to the claim, or key the decision on something other than the window end
        st = scripted(stalls=cell_stalls(5, 5))
        first = lessons.extract(st, RUN, 0.2)
        self.assertEqual((first["created"], first["existing"]), (1, 0))
        (d,) = lessons.lessons(st, RUN)
        self.assertEqual(set(lessons.claim_of(d)), set(lessons.CLAIM_KEYS))
        self.assertEqual(len(lessons.CLAIM_KEYS), 15)
        self.assertEqual(d["dedup_key"], f"lesson:hot_cell|Z0:cell 9,9:2026-01-01T00:12:00Z")
        self.assertEqual((d["kind"], d["claim_version"], d["status"], d["subject"]), ("lesson", 1, "open",
                                                                                         "hot_cell|Z0:cell 9,9"))
        again = lessons.extract(st, RUN, 0.2)
        self.assertEqual((again["created"], again["existing"]), (0, 1))
        self.assertEqual(len(st.select("decisions")), 1)

    def test_registered_kind(self):
        self.assertIn("lesson", decisions.KINDS)
        self.assertEqual(decisions.CLAIM_VERSIONS["lesson"], 1)

    def test_text_is_rendered_from_the_stored_claim_alone(self):
        # inject: a number in the text that the claim cannot produce
        rows = ([ep(i, "Z0-02", cell=(i, 0), cause="blocked_by_stuck", blocker="Z0-01") for i in range(4)]
                + [ep(20 + i, f"Z0-{20 + i}", cell=(7, 7), avoidable=i < 3) for i in range(6)])
        rows += [ep(40 + i, f"Z0-{40 + i}", cell=(i, 9), cause="traffic") for i in range(12)]
        st = scripted(eps=rows, stalls=cell_stalls(7, 12), robots=["Z0-02", "Z0-01", "Z0-03"])
        lessons.extract(st, RUN, 0.2)
        kinds = set()
        for d in lessons.lessons(st, RUN):
            stored = json.loads(d["claim"])
            kinds.add(stored["lesson_kind"])
            self.assertEqual(lessons.render(stored), stored["text"])
            self.assertEqual(d["rationale"], stored["text"])
            self.assertTrue(stored["text"].startswith("In zone 0, "))
            self.assertTrue(stored["text"].endswith("."))
            self.assertIn("00:00-00:12", stored["text"])
            nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", stored["text"].replace("00:00-00:12", ""))]
            allowed = {float(stored[k]) for k in ("k", "n") if stored[k] is not None} | {0.0}
            for key in ("ratio",):
                allowed.add(round(stored[key], 1) if stored[key] is not None else 0.0)
            for key in ("value", "baseline"):
                if stored[key] is not None:
                    allowed |= {round(stored[key] * 100), stored[key]}
            subject_nums = {float(x) for x in re.findall(r"\d+", stored["subject"] + stored["metric"])}
            zone = {float(stored["zone"])}
            self.assertTrue(set(nums) <= allowed | subject_nums | zone, (stored["text"], nums, allowed))
        self.assertGreaterEqual(len(kinds), 4)
        self.assertEqual(lessons.render(dict(lesson_kind="recurring_pair", zone="3", subject="Z3:Z3-04->Z3-05", k=4,
                                             window_start=BASE + W, window_end=BASE + 2 * W)),
                         "In zone 3, robot Z3-04 blocked robot Z3-05 4 times (00:12-00:24).")

    def test_cli_once_twice(self):
        with tempfile.TemporaryDirectory() as d:
            st = JsonlStore(Path(d) / "store")
            st.insert("stalls", cell_stalls(5, 5))
            checkpoint(st, BASE + W)
            st.close()
            spec = f"jsonl:{Path(d) / 'store'}"
            self.assertEqual(lessons_cli.main(["--run", RUN, "--store", spec, "--once", "--window-h", "0.2"]), 0)
            self.assertEqual(lessons_cli.main(["--run", RUN, "--store", spec, "--once", "--window-h", "0.2"]), 0)
            rs = JsonlStore(Path(d) / "store")
            self.assertEqual(len(lessons.lessons(rs, RUN)), 1)
            rs.close()


def lesson_then_advance(next_stalls, end, store=None):
    """A hot_cell lesson on window 0 (cell 9,9); window 1 is scripted by `next_stalls`; the stream then reaches `end`."""
    st = store or MemoryStore()
    st.insert("stalls", cell_stalls(5, 5) + next_stalls)
    checkpoint(st, BASE + W)
    lessons.extract(st, RUN, 0.2)  # only window 0 is fully observed
    checkpoint(st, end)
    return st


NEXT = BASE + W + 10


class TestGrading(unittest.TestCase):
    def rows(self, st):
        return st.select("forecast_grades", {"run": RUN, "grade_source": "lesson"})

    def test_ok_when_the_threshold_still_holds_in_the_next_window(self):
        st = lesson_then_advance(cell_stalls(5, 5, start=NEXT), BASE + 2 * W)
        self.assertEqual(lessons.grade_lessons(st, RUN), dict(graded=1, open=0))
        (g,) = self.rows(st)
        (d,) = [d for d in lessons.lessons(st, RUN) if d["decided_at"] == BASE + W]
        self.assertEqual((g["verdict"], g["outcome"], g["expected"], g["error"], g["horizon_s"], g["graded_at"],
                          g["window_end"]), ("ok", 5, 5, None, W, BASE + 2 * W, BASE + 2 * W))
        self.assertEqual((d["status"], d["verdict"], d["graded_at"]), ("graded", "ok", BASE + 2 * W))

    def test_off_when_the_next_window_does_not_repeat_it(self):
        # inject: grade over the decision window instead of the next one (m3); the decision window HAS the signal
        st = lesson_then_advance([stall(f"{i},1", NEXT) for i in range(10)], BASE + 2 * W)
        self.assertEqual(lessons.grade_lessons(st, RUN), dict(graded=1, open=0))
        (g,) = self.rows(st)
        self.assertEqual((g["verdict"], g["outcome"], g["expected"]), ("off", 0, 5))
        (d,) = lessons.lessons(st, RUN)
        self.assertEqual(d["verdict"], "off")

    def test_open_until_the_next_window_is_fully_observed(self):
        st = lesson_then_advance(cell_stalls(5, 5, start=NEXT), BASE + 2 * W - 1)
        self.assertEqual(lessons.grade_lessons(st, RUN), dict(graded=0, open=1))
        self.assertEqual(self.rows(st), [])
        (d,) = lessons.lessons(st, RUN)
        self.assertEqual((d["status"], d["verdict"]), ("open", None))
        checkpoint(st, BASE + 2 * W)  # the stream reaches window_end + W: now it is graded
        self.assertEqual(lessons.grade_lessons(st, RUN), dict(graded=1, open=0))

    def test_support_minimum_is_not_applied_to_the_next_window(self):
        # next window: the cell has 4 stalls (below n_min 5) among 20 singles: ratio 3.5 still holds
        st = lesson_then_advance(cell_stalls(4, 20, start=NEXT), BASE + 2 * W)
        lessons.grade_lessons(st, RUN)
        (g,) = self.rows(st)
        self.assertEqual((g["verdict"], g["outcome"]), ("ok", 4))

    def test_a_graded_lesson_is_not_graded_again(self):
        st = lesson_then_advance(cell_stalls(5, 5, start=NEXT), BASE + 2 * W)
        lessons.grade_lessons(st, RUN)
        self.assertEqual(lessons.grade_lessons(st, RUN), dict(graded=0, open=0))
        self.assertEqual(len(self.rows(st)), 1)

    def test_row_is_written_before_the_decision_is_stamped(self):
        # inject: stamp the decision before the forecast_grades row is written (m7)
        class Logged(MemoryStore):
            log = []

            def upsert(self, table, key_cols, rows):
                self.log.append(("upsert", table, rows[0]["grade_source"]))
                return super().upsert(table, key_cols, rows)

            def update_where(self, table, eq, values):
                self.log.append(("update", table, values.get("verdict")))
                return super().update_where(table, eq, values)

        st = lesson_then_advance(cell_stalls(5, 5, start=NEXT), BASE + 2 * W, store=Logged())
        Logged.log.clear()
        lessons.grade_lessons(st, RUN)
        self.assertEqual(Logged.log, [("upsert", "forecast_grades", "lesson"), ("update", "decisions", "ok")])

    def test_cause_mix_persists_means_the_same_cause_is_still_dominant(self):
        def traffic(start, n=10, other=0):
            return ([ep(start + i, f"Z0-{i:02d}", start=start + 10, cell=(i, 0), cause="traffic") for i in range(n)]
                    + [ep(start + 100 + i, f"Z0-{60 + i}", start=start + 10, cell=(i, 7), cause="faulted_self")
                       for i in range(other)])

        for next_rows, want in ((traffic(NEXT, 10), "ok"), (traffic(NEXT, 5, other=5), "off")):
            st = MemoryStore()
            st.insert("stuck_episodes", traffic(BASE, 10) + next_rows)
            checkpoint(st, BASE + W)
            lessons.extract(st, RUN, 0.2)
            checkpoint(st, BASE + 2 * W)
            lessons.grade_lessons(st, RUN)
            (g,) = st.select("forecast_grades", {"run": RUN, "grade_source": "lesson"})
            self.assertEqual(g["verdict"], want)

    def test_cycle_returns_lesson_counts_and_show_prints_them(self):
        with tempfile.TemporaryDirectory() as d:
            st = JsonlStore(Path(d) / "store")
            st.insert("stalls", cell_stalls(5, 5) + cell_stalls(5, 5, start=NEXT))
            checkpoint(st, BASE + W)
            lessons.extract(st, RUN, 0.2)
            checkpoint(st, BASE + 2 * W)
            st.close()
            counts = grade.cycle(f"jsonl:{Path(d) / 'store'}", RUN)
            self.assertEqual(counts["lesson"], dict(graded=1, open=0))
            self.assertIn("lessons {'graded': 1, 'open': 0}", grade.show(RUN, counts))


class TestLessonTruth(unittest.TestCase):
    TRUTH = dict(zones={"0": dict(floor_cells={"9,9": 0.5})})

    def build(self):
        stalls = [stall("9,9") for _ in range(5)] + [stall("7,7") for _ in range(5)] + [stall(f"{i},0") for i in range(10)]
        rows = [ep(i, "Z0-02", cell=(i, 0), cause="blocked_by_stuck", blocker="Z0-01") for i in range(3)]
        st = scripted(eps=rows, stalls=stalls)
        lessons.extract(st, RUN, 0.2)
        return st

    def test_hit_and_false_alarm_for_hot_cell_lessons_only(self):
        st = self.build()
        kinds = sorted(lessons.claim_of(d)["lesson_kind"] for d in lessons.lessons(st, RUN))
        self.assertEqual(kinds, ["hot_cell", "hot_cell", "recurring_pair"])
        self.assertEqual(grade.grade_lesson_truth(st, RUN, self.TRUTH), dict(graded=2))
        rows = {lessons.claim_of(d)["subject"]: g["verdict"] for d in lessons.lessons(st, RUN)
                for g in st.select("forecast_grades", {"id": d["id"], "grade_source": "lesson_truth"})}
        self.assertEqual(rows, {"Z0:cell 9,9": "hit", "Z0:cell 7,7": "false_alarm"})
        self.assertTrue(all(d["status"] == "open" for d in lessons.lessons(st, RUN)))  # never stamped by truth
        self.assertEqual(grade.grade_lesson_truth(st, RUN, self.TRUTH), dict(graded=0))  # once per lesson

    def test_a_zone_missing_from_the_floor_file_raises_before_any_row(self):
        st = self.build()
        with self.assertRaises(ValueError):
            grade.grade_lesson_truth(st, RUN, dict(zones={"5": dict(floor_cells={})}))
        self.assertEqual(st.select("forecast_grades"), [])


def forecast_fixture(st, zone="0", t=BASE + 100):
    """One hotspot_forecast decision with its three grade rows."""
    did, _ = decisions.record_decision(
        st, run=RUN, kind="hotspot_forecast", subject=f"Z{zone}:3,4", start_iso="x", decided_at=t,
        claim=dict(horizon_s=600, rank=1, top_k=20, expected_stalls_next_hour=3.0), rationale="r", expected=None,
        grade_after=t + 600)
    for src, v, out in (("outcome", "ok", 1), ("outcome_count", "off", 4), ("truth", "hit", None)):
        forecast_grade.write_once(st, dict(id=did, run=RUN, grade_source=src, outcome=out, expected=20, error=None,
                                           verdict=v, horizon_s=600, graded_at=t + 700, window_end=t + 600))
    decisions.stamp_grade(st, did, 1, None, "ok", t + 700)
    return did


class TestReadersIgnoreLessonRows(unittest.TestCase):
    def lesson_store(self, st):
        st.insert("stalls", cell_stalls(5, 5) + cell_stalls(5, 5, start=NEXT))
        checkpoint(st, BASE + W)
        lessons.extract(st, RUN, 0.2)
        checkpoint(st, BASE + 2 * W)
        lessons.grade_lessons(st, RUN)
        grade.grade_lesson_truth(st, RUN, TestLessonTruth.TRUTH)
        return st

    def test_hotspot_score_numbers_are_unchanged_and_counts_gain_the_lesson_sources(self):
        # inject: a hotspot_score aggregate that counts every forecast_grades row (outcome_ids / count_ids)
        truth = dict(zones={"0": dict(floor_cells={"3,4": 0.5, "1,1": 0.2})})
        costmap = dict(zones={"0": {"3,4": 2.0, "5,5": 1.0}})
        plain = MemoryStore()
        forecast_fixture(plain)
        with_l = MemoryStore()
        forecast_fixture(with_l)
        self.lesson_store(with_l)
        n_lesson_rows = len([g for g in with_l.select("forecast_grades") if g["grade_source"].startswith("lesson")])
        self.assertEqual(n_lesson_rows, 2)  # one "lesson" row and one "lesson_truth" row
        stalls = [dict(zone="0", cell="3,4", in_episode=None)]
        a = hotspot_score.score_run(truth, costmap, stalls, plain.select("forecast_grades", {"run": RUN}))
        b = hotspot_score.score_run(truth, costmap, stalls, with_l.select("forecast_grades", {"run": RUN}))
        for key in ("zones", "mean", "rank_grading", "stall_in_episode"):
            self.assertEqual(a[key], b[key], key)
        self.assertEqual(a["rank_grading"], dict(top_k=[20], rank_graded=1, unranked=0))
        for src in ("outcome", "outcome_count", "truth"):
            self.assertEqual(a["grading_counts"][src], b["grading_counts"][src])
        self.assertEqual(set(a["grading_counts"]), {"outcome", "outcome_count", "truth"})
        self.assertEqual(b["grading_counts"]["lesson"], {"ok": 1})
        self.assertEqual(b["grading_counts"]["lesson_truth"], {"hit": 1})

    def test_replay_grades_are_unchanged(self):
        # inject: build_grades without the join to hotspot_forecast decisions
        plain = MemoryStore()
        forecast_fixture(plain)
        with_l = MemoryStore()
        forecast_fixture(with_l)
        self.lesson_store(with_l)
        pubs = [dict(t=BASE + 100)]
        want = rx.build_grades(plain, RUN, "0", pubs, BASE)
        self.assertEqual(rx.build_grades(with_l, RUN, "0", pubs, BASE), want)
        self.assertEqual(want["per_publish"][0]["forecasts"], 1)
        self.assertEqual(want["timeline"][-1]["outcome_ok"], 1)

    def test_forecast_grader_existing_row_check_is_per_decision_and_source(self):
        st = MemoryStore()
        did = forecast_fixture(st)
        self.lesson_store(st)
        again = forecast_grade.grade_outcomes(st, RUN)
        self.assertEqual(again, dict(graded=0, open=0, rank_graded=0, unranked=0))
        self.assertTrue(st.exists("forecast_grades", id=did, grade_source="outcome"))


class TestLedgerStatus(unittest.TestCase):
    def test_grades_last_day_lesson_line(self):
        st = MemoryStore()
        for i, v in enumerate(("ok", "ok", "off")):
            did, _ = decisions.record_decision(st, run=RUN, kind="lesson", subject=f"hot_cell|Z0:cell {i},0",
                                               start_iso=str(i), decided_at=BASE + i, claim={}, rationale="x",
                                               expected=None, grade_after=BASE + 99)
            decisions.stamp_grade(st, did, 1, None, v, BASE + 50)
        decisions.record_decision(st, run=RUN, kind="lesson", subject="hot_cell|Z0:cell 9,9", start_iso="9",
                                  decided_at=BASE + 9, claim={}, rationale="x", expected=None, grade_after=BASE + 99)
        line = [x for x in ledger.status_lines(st, RUN) if x.startswith("grades last day [lesson]")]
        self.assertEqual(line, ["grades last day [lesson]: ok 2, off 1, accuracy 0.6666666666666666"])
        self.assertIn("decisions: lesson/graded 3, lesson/open 1", ledger.status_lines(st, RUN))


# ------------------------------------------------------------------------------------------------ replay export
def add_lessons(directory):
    """Two zone-0 lessons (one graded ok, one open) and one zone-1 lesson, written into the fixture run's store."""
    st = JsonlStore(Path(directory) / "store")
    t0 = tre.BASE
    out = []
    for zone, subject, ws, verdict, conf in (("0", "Z0:cell 3,4", t0 + 100, "ok", 0.9), ("0", "Z0:Z0-01", t0 + 100, None, 0.5),
                                              ("1", "Z1:cell 1,1", t0 + 100, "off", 0.7)):
        claim = dict(text=f"T {subject}", lesson_kind="hot_cell" if "cell" in subject else "hot_robot", subject=subject,
                     zone=zone, confidence=conf, window_start=ws - 100, window_end=ws, k=1, n=1, value=1, baseline=1,
                     ratio=1, metric="m", threshold=1, n_min=1)
        did, _ = decisions.record_decision(st, run=tre.RUN, kind="lesson", subject=f"{claim['lesson_kind']}|{subject}",
                                           start_iso=str(ws), decided_at=ws, claim=claim, rationale="x", expected=None,
                                           grade_after=ws + 100)
        if verdict:
            forecast_grade.write_once(st, dict(id=did, run=tre.RUN, grade_source="lesson", outcome=1, expected=1,
                                               error=None, verdict=verdict, horizon_s=100, graded_at=ws + 500,
                                               window_end=ws + 100))
            decisions.stamp_grade(st, did, 1, None, verdict, ws + 500)
        out.append(did)
    st.close()
    return out


class TestReplayLessons(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = tre.build_run(cls.tmp.name)
        cls.spec = f"jsonl:{cls.dir / 'store'}"

        def build():
            return rx.build_payload(cls.dir, cls.spec, "0", env_runner=tre.fake_env, run_dir_arg=str(cls.dir),
                                    closed_loop_arg=None)

        cls.before = build()
        add_lessons(cls.dir)
        cls.after = build()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_no_lessons_is_an_empty_list(self):
        self.assertEqual(self.before["lessons"], [])

    def test_every_other_payload_key_is_unchanged(self):
        a, b = copy.deepcopy(self.before), copy.deepcopy(self.after)
        a.pop("lessons")
        b.pop("lessons")
        self.assertEqual(a, b)
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))

    def test_lessons_schema_order_and_zone_filter(self):
        t0, step = self.after["meta"]["t0_ts"], self.after["meta"]["step_seconds"]
        want = [dict(decided_at_step=100 // step, text="T Z0:cell 3,4", lesson_kind="hot_cell", confidence=0.9,
                     verdict="ok", graded_at_step=200 // step),
                dict(decided_at_step=100 // step, text="T Z0:Z0-01", lesson_kind="hot_robot", confidence=0.5, verdict=None,
                     graded_at_step=None)]
        # zone 1's lesson is absent; same decided_at, so sorted by the decision subject ("hot_cell|..." < "hot_robot|...")
        self.assertEqual(self.after["lessons"], want)
        self.assertEqual(t0, tre.BASE)

    def test_size_cap_holds_and_data_js_round_trips(self):
        with tempfile.TemporaryDirectory() as d:
            n = rx.write_data_js(self.after, Path(d) / "data.js")
            self.assertLessEqual(n, rx.MAX_BYTES)
            self.assertEqual(rx.read_data_js(Path(d) / "data.js")["lessons"], self.after["lessons"])


class TestCommittedPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (DOCS / "index.html").read_text(encoding="utf-8")
        cls.js = (DOCS / "replay.js").read_text(encoding="utf-8")
        cls.css = (DOCS / "replay.css").read_text(encoding="utf-8")

    @unittest.skipUnless((DOCS / "data.js").exists(), "docs/replay/data.js is absent")
    def test_committed_data_has_lessons_with_the_documented_fields(self):
        data = rx.read_data_js(DOCS / "data.js")
        self.assertIn("lessons", data)
        self.assertLessEqual((DOCS / "data.js").stat().st_size, rx.MAX_BYTES)
        keys = {"decided_at_step", "text", "lesson_kind", "confidence", "verdict", "graded_at_step"}
        for les in data["lessons"]:
            self.assertEqual(set(les), keys)
            self.assertIn(les["verdict"], ("ok", "off", None))
        order = [(x["decided_at_step"], x["text"]) for x in data["lessons"]]
        self.assertEqual([o[0] for o in order], sorted(o[0] for o in order))

    def test_panel_has_labels_empty_state_and_no_network(self):
        self.assertIn('id="lessons"', self.html)
        self.assertIn("Lessons", self.html)
        self.assertIn("held next window", self.js)  # text label next to the tick
        self.assertIn("did not hold", self.js)  # text label next to the cross
        self.assertIn("No lessons", self.js)  # empty state
        for text in (self.html, self.js, self.css):
            self.assertNotRegex(text.replace("http://www.w3.org/2000/svg", ""), r"https?://")


if __name__ == "__main__":
    unittest.main()

"""Tests for S8S lesson_persist_chance (fleet/hotspot_score.py persist_chance): the share of a lesson's candidate pool that
clears the same next-window bar. Fixtures are reused from test_fleet_lessons / test_fleet_lesson_persist.
Each case names its injection in a `# inject:` comment."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "fleet") not in sys.path:
    sys.path.insert(0, str(ROOT / "fleet"))

import hotspot_score  # noqa: E402
from fleet.tests import test_fleet_lessons as tfl  # noqa: E402
from fleet_analyser import decisions, forecast_grade, lessons  # noqa: E402
from fleet_analyser.parse import iso  # noqa: E402
from fleet_analyser.store import JsonlStore, MemoryStore  # noqa: E402

RUN, BASE, W, NEXT = tfl.RUN, tfl.BASE, tfl.W, tfl.NEXT
WINDOW_H = 0.2
# window 0: cell 9,9 x5 plus nine single-stall cells 0,0..8,0 -> pool of 10 cells, n 14, C 10, ratio 3.57 (fires)
W0 = tfl.cell_stalls(5, 9)
# next window: 9,9 x2, 0,0 x2, 1,0 x2, 2,0 x1 -> n 7, C 4, average 1.75: exactly 9,9 / 0,0 / 1,0 clear 1.0
NXT = ([tfl.stall("9,9", NEXT) for _ in range(2)] + [tfl.stall("0,0", NEXT) for _ in range(2)]
       + [tfl.stall("1,0", NEXT) for _ in range(2)] + [tfl.stall("2,0", NEXT)])


def cell_store(w0=W0, nxt=NXT, store=None, extra=None, zones=("0",)):
    st = store or MemoryStore()
    st.insert("stalls", [dict(s, in_episode=None) for s in list(w0) + list(nxt) + list(extra or ())])
    tfl.checkpoint(st, BASE + W, zones=zones)
    lessons.extract(st, RUN, WINDOW_H)
    tfl.checkpoint(st, BASE + 2 * W, zones=zones)
    lessons.grade_lessons_persist(st, RUN)
    return st


class TestPool(unittest.TestCase):
    def test_pool_three_of_ten(self):
        # inject: pool = only the lesson's own subject (pool_size 1), or ok counted against the claim baseline
        st = cell_store()
        res = hotspot_score.persist_chance(st, RUN)
        self.assertEqual(res["n_lessons"], 1)
        (row,) = res["per_lesson"]
        self.assertEqual((row["pool_size"], row["pool_ok"], row["chance"]), (10, 3, 0.3))
        self.assertEqual(row["subject"], "Z0:cell 9,9")
        self.assertTrue(row["observed"])
        self.assertEqual(set(row), {"id", "subject", "window_start", "pool_size", "pool_ok", "chance", "observed"})
        self.assertEqual(set(res), {"n_lessons", "observed_ok", "observed_rate", "chance_mean", "chance_median", "lift",
                                    "per_lesson"})
        self.assertEqual((res["observed_ok"], res["observed_rate"], res["chance_mean"], res["chance_median"]),
                         (1, 1.0, 0.3, 0.3))
        self.assertAlmostEqual(res["lift"], 1.0 / 0.3)

    def test_every_member_as_subject_gives_lift_one(self):
        # inject: observed counted for the fired lesson only (rate 1.0 against chance 0.3)
        st = cell_store()
        (d,) = lessons.lessons(st, RUN)
        claim = lessons.claim_of(d)
        data = lessons.Data(st, RUN)
        pool = lessons.STATS["hot_cell"](data.window("0", claim["window_start"], claim["window_end"]), None)
        self.assertEqual(len(pool), 10)
        for member in pool:
            if member["subject"] == claim["subject"]:
                continue
            c = dict(claim, subject=member["subject"], k=member["k"])
            decisions.record_decision(st, run=RUN, kind=lessons.KIND, subject=f"hot_cell|{member['subject']}",
                                      start_iso=iso(claim["window_end"]), decided_at=claim["window_end"], claim=c,
                                      rationale="x", expected=None, grade_after=claim["window_end"] + W)
        self.assertEqual(lessons.grade_lessons_persist(st, RUN), dict(graded=9, open=0))
        res = hotspot_score.persist_chance(st, RUN)
        self.assertEqual((res["n_lessons"], res["observed_ok"], res["observed_rate"]), (10, 3, 0.3))
        self.assertAlmostEqual(res["chance_mean"], 0.3)
        self.assertAlmostEqual(res["lift"], 1.0)

    def test_pool_equals_the_candidate_list(self):
        # inject: pool built from all zone stalls in [ws, we + W), or without the zone filter
        extra = [tfl.stall("7,7", NEXT),                      # stalled only in the next window -> OUT
                 tfl.stall("8,8", BASE + W),                  # stall at exactly window_end -> next window -> OUT
                 tfl.stall("6,6", BASE + 10, zone="1")]       # other zone -> OUT
        # "1,0" has exactly one stall in the claim window (a singleton) -> IN; no OUT cell has a claim-window stall
        seen = []
        real = lessons.STATS["hot_cell"]

        def spy(w, fleet):
            out = real(w, fleet)
            if w["ws"] == BASE:
                seen.append((w["zone"], {s["subject"] for s in out}))
            return out

        st = cell_store(extra=extra, zones=("0", "1"))
        with mock.patch.dict(lessons.STATS, {"hot_cell": spy}):
            res = hotspot_score.persist_chance(st, RUN)
        candidates = {s["subject"] for s in real(lessons.Data(st, RUN).window("0", BASE, BASE + W), None)}
        self.assertEqual(seen, [("0", candidates)])
        self.assertEqual(res["per_lesson"][0]["pool_size"], len(candidates))
        self.assertIn("Z0:cell 1,0", candidates)
        for out in ("Z0:cell 7,7", "Z0:cell 8,8", "Z1:cell 6,6"):
            self.assertNotIn(out, candidates)
        self.assertEqual(candidates, {"Z0:cell 9,9"} | {f"Z0:cell {i},0" for i in range(9)})

    def test_hot_robot_pool_is_robots_with_an_episode(self):
        # inject: pool = R (robots seen by a transition too): Z0-09 would enter the pool (size 5, chance 0.4)
        seen = []
        real = lessons.STATS["hot_robot"]

        def spy(w, fleet):
            out = real(w, fleet)
            if w["ws"] == BASE:
                seen.append({s["subject"] for s in out})
            return out

        # window 0: Z0-01 x5, Z0-02 x2, Z0-03 x2, Z0-04 x1; Z0-09 only in a transition -> R 5, ratio 2.5 fires
        w0 = dict(eps=tfl.robot_eps(5, 5), robots=(tfl.R4 + ["Z0-09"], BASE + 1))
        # next: Z0-01 x3, Z0-02 x2, Z0-03 x1: R 3, average 2 -> Z0-01 and Z0-02 (exactly 1.0) clear; Z0-03, Z0-04 do not
        nxt = dict(eps=tfl.robot_eps(3, 3, base=1000, start=NEXT))
        st, _ = tfl.grade_case(w0, nxt)
        lessons.grade_lessons_persist(st, RUN)
        with mock.patch.dict(lessons.STATS, {"hot_robot": spy}):
            res = hotspot_score.persist_chance(st, RUN)
        self.assertEqual(seen, [{"Z0:Z0-01", "Z0:Z0-02", "Z0:Z0-03", "Z0:Z0-04"}])
        self.assertNotIn("Z0:Z0-09", seen[0])
        (row,) = res["per_lesson"]
        self.assertEqual((row["subject"], row["pool_size"], row["pool_ok"], row["chance"], row["observed"]),
                         ("Z0:Z0-01", 4, 2, 0.5, True))


class TestWindowAndEmpty(unittest.TestCase):
    def run_main(self, d, *extra):
        d = Path(d)
        truth = dict(schema_version="fleet-truth/1", env_id="e", disturb_tag="x", disturb={}, steps=10, seed_base=0,
                     zones={"0": dict(seed=0, floor_cells={}, floor_skips=[0] * 10, floor_skips_total=0)})
        (d / "truth.json").write_text(json.dumps(truth))
        (d / "costmap.json").write_text(json.dumps(dict(
            schema_version="fleet-costmap/1", run=RUN, generated_at="x", window_hours=1, half_life_h=1, min_stalls=1,
            exclude_occupied=True, zones={"0": {}})))
        out = d / "o.json"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = hotspot_score.main(["--run-dir", str(d), "--store", f"jsonl:{d / 'store'}", "--tag", "t",
                                       "--out", str(out), *extra])
        return code, json.loads(out.read_text())

    def test_wrong_window_h_exits_nonzero(self):
        # inject: --window-h ignored when stored windows exist
        with tempfile.TemporaryDirectory() as d:
            cell_store(store=JsonlStore(Path(d) / "store")).close()
            with self.assertRaises(SystemExit) as cm:
                self.run_main(d, "--window-h", "0.5")
            self.assertNotEqual(cm.exception.code, 0)
            code, res = self.run_main(d, "--window-h", "0.2")  # matches the stored 720 s window
            self.assertEqual(code, 0)
            self.assertEqual(res["lesson_persist_chance"]["n_lessons"], 1)
            code, res = self.run_main(d)  # omitted: stored windows as-is
            self.assertEqual(res["lesson_persist_chance"]["per_lesson"][0]["pool_size"], 10)

    def test_no_rows_is_empty_without_window_h(self):
        # inject: the key omitted / lift computed as 0 / 0 when there are no lessons
        with tempfile.TemporaryDirectory() as d:
            st = JsonlStore(Path(d) / "store")
            st.insert("stalls", [dict(tfl.stall("1,1"), in_episode=None)])  # a store with data but no lesson_persist rows
            st.close()
            for extra in ((), ("--window-h", "0.5")):
                code, res = self.run_main(d, *extra)
                self.assertEqual(code, 0)
                self.assertEqual(res["lesson_persist_chance"],
                                 dict(n_lessons=0, observed_ok=0, observed_rate=None, chance_mean=None,
                                      chance_median=None, lift=None, per_lesson=[]))

    def test_zero_chance_gives_null_lift(self):
        # inject: lift = rate / 0 raises or returns inf
        st = cell_store(nxt=[tfl.stall(f"{i},1", NEXT) for i in range(10)])  # nobody in the pool recurs
        res = hotspot_score.persist_chance(st, RUN)
        self.assertEqual((res["chance_mean"], res["observed_ok"], res["lift"]), (0.0, 0, None))


class TestTripwire(unittest.TestCase):
    def test_stored_verdict_disagreeing_raises(self):
        # inject: stored row says "off" while the recomputed verdict is "ok"
        st = cell_store()
        (d,) = lessons.lessons(st, RUN)
        hotspot_score.persist_chance(st, RUN)  # the consistent store passes
        fake = MemoryStore()
        for table in ("stalls", "decisions", "ingest_checkpoints"):
            fake.insert(table, st.select(table, {"run": RUN}))
        forecast_grade.write_once(fake, dict(id=d["id"], run=RUN, grade_source=lessons.PERSIST_SOURCE, outcome=0.0,
                                             expected=1.0, error=None, verdict="off", horizon_s=W,
                                             graded_at=BASE + 2 * W, window_end=BASE + 2 * W))
        with self.assertRaises(ValueError) as cm:
            hotspot_score.persist_chance(fake, RUN)
        self.assertIn(d["id"], str(cm.exception))


if __name__ == "__main__":
    unittest.main()

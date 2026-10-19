"""Tests for S10D fleet/baselines.py and hotspot_score.py --baselines: persistence vs decayed map, PAI, the two chance
lines, the paired zone bootstrap, the outcome gate, the three lesson_persist pools, and that no flag means no change.
Synthetic MemoryStores / tmp JsonlStores only, no fleet/data, no env. Each case names its injection in a `# inject:` line."""
import contextlib
import hashlib
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

import baselines  # noqa: E402
import hotspot_score  # noqa: E402
from fleet.tests import test_fleet_lessons as tfl  # noqa: E402
from fleet_analyser import hotspot, lessons  # noqa: E402
from fleet_analyser.store import JsonlStore, MemoryStore  # noqa: E402

RUN = "r"
T = 10_000
H = 600
META = dict(window_hours=1.0, half_life_h=1.0, min_stalls=1, exclude_occupied=True)


def stall(zone, cell, end, next_occupied=False, faulted=False):
    return dict(run=RUN, zone=zone, robot="R1", cell=cell, start=end - 5, end=end, seconds=5, next_occupied=next_occupied,
                faulted_episode=faulted, in_episode=None)


def publish(st, stalls, t=T):
    """Insert the stalls and the costmap rows costmap.py would publish at t (hotspot.cost_zones)."""
    st.insert("stalls", stalls)
    rows = []
    for zone, cells in hotspot.cost_zones(stalls, t, **{"window_h": 1.0, "half_life_h": 1.0, "min_stalls": 1,
                                                        "exclude_occupied": True}).items():
        rows += [dict(run=RUN, zone=zone, published_at=t, cell=c, cost=v["cost"], score=v["score"], stalls=v["stalls"])
                 for c, v in cells.items()]
    st.insert("costmap", rows)


def claims(st, horizon=H, zones=("0",)):
    st.insert("decisions", [dict(run=RUN, kind="hotspot_forecast", id=f"d{z}", subject=f"Z{z}:1,1",
                                 claim=json.dumps(dict(horizon_s=horizon, rank=1, window_hours=1.0))) for z in zones])


def stream_end(st, end, zones=("0",)):
    st.insert("ingest_checkpoints", [dict(run=RUN, path="f", cp_seq=1,
                                          last_message_ts_by_zone=json.dumps({z: end for z in zones}))])


def compute(st, zones, cands, positives, ks=(2,), persist=None):
    return baselines.compute(st, RUN, zones, META, cands, lambda z, t, h: positives.get(z, set()), persist, ks)


# map and persistence disagree: A 3 old stalls (raw 3), B 2 fresh stalls (raw 2), C 1 fresh stall (raw 1).
# score A = 3 * 2 ** (-3000 / 3600) = 1.68, B = 2 * 2 ** (-100 / 3600) = 1.96, C = 0.98.
DISAGREE = [stall("0", "1,1", T - 3000) for _ in range(3)] + [stall("0", "2,2", T - 100) for _ in range(2)] + \
           [stall("0", "3,3", T - 100)]


class TestTopK(unittest.TestCase):
    def test_persistence_top_k_differs_from_map_top_k(self):
        # inject: persistence ranks by the decayed cost (the map's own order), or the map by the raw count
        st = MemoryStore()
        publish(st, DISAGREE)
        rows = {r["cell"]: r for r in st.select("costmap", {"run": RUN})}
        self.assertEqual(baselines.map_top(rows), ["2,2", "1,1", "3,3"])
        self.assertEqual(baselines.persistence_top(rows), ["1,1", "2,2", "3,3"])
        self.assertNotEqual(baselines.map_top(rows)[:1], baselines.persistence_top(rows)[:1])

    def test_persistence_ties_break_on_the_cell_string(self):
        # inject: ties left in insertion order
        rows = {c: dict(cost=1.0, stalls=2) for c in ("9,9", "10,2", "2,5")}
        self.assertEqual(baselines.persistence_top(rows), ["10,2", "2,5", "9,9"])

    def test_scored_against_truth_the_two_forecasts_get_different_hits(self):
        # inject: both forecasts read the same list; K = 1 so the first slot decides: map B, persistence A
        st = MemoryStore()
        publish(st, DISAGREE)
        claims(st)
        stream_end(st, T)
        cands = ["1,1", "2,2", "3,3", "4,4"]
        b = compute(st, ["0"], cands, {"0": {"2,2"}}, ks=(1,))
        self.assertEqual(b["k"]["1"]["map"]["hits"]["truth"], 1)
        self.assertEqual(b["k"]["1"]["persistence"]["hits"]["truth"], 0)

    def test_k_at_or_above_n_flagged_gives_equal_sets_and_zero_delta(self):
        # inject: persistence draws from a different pool than the map
        st = MemoryStore()
        publish(st, DISAGREE)
        claims(st)
        stream_end(st, T)
        b = compute(st, ["0"], ["1,1", "2,2", "3,3", "4,4"], {"0": {"2,2", "4,4"}}, ks=(3, 20, 40))
        for k in ("3", "20", "40"):
            self.assertEqual(b["k"][k]["map"], b["k"][k]["persistence"])
        self.assertEqual(b["paired"]["20"]["truth_precision"]["mean"], 0.0)


class TestPaiAndChance(unittest.TestCase):
    def perfect(self):
        # K = 2 positives a, b which are exactly the top 2; N_all = 10 candidates
        st = MemoryStore()
        publish(st, [stall("0", "1,1", T - 10), stall("0", "1,1", T - 20), stall("0", "2,2", T - 10),
                     stall("0", "3,3", T - 10)])
        claims(st)
        stream_end(st, T)
        cands = [f"{i},{i}" for i in range(1, 11)]
        return compute(st, ["0"], cands, {"0": {"1,1", "2,2"}}, ks=(2,))

    def test_perfect_forecast_pai_is_n_all_over_k(self):
        # inject: PAI divides by K instead of K / N_all
        b = self.perfect()
        for f in ("map", "persistence"):
            row = b["k"]["2"][f]
            self.assertEqual(row["truth_precision"], 1.0)
            self.assertEqual(row["truth_recall"], 1.0)
            self.assertEqual(row["pai"], 10 / 2)
            self.assertEqual(row["pai"], row["lift_all"])  # the identity PAI == lift against chance_all
        self.assertEqual(b["params"]["n_cells_all"], 10)

    def test_pai_equals_lift_all_when_pooled_over_units_and_partial_hits(self):
        # inject: lift_all uses a per-unit mean while PAI pools
        st = MemoryStore()
        publish(st, [stall("0", "1,1", T - 10), stall("0", "2,2", T - 10)])
        publish(st, [stall("1", "1,1", T - 10), stall("1", "5,5", T - 10)])
        claims(st, zones=("0", "1"))
        stream_end(st, T, zones=("0", "1"))
        cands = [f"{i},{i}" for i in range(1, 11)]
        b = compute(st, ["0", "1"], cands, {"0": {"1,1", "2,2", "7,7"}, "1": {"1,1"}}, ks=(2,))
        row = b["k"]["2"]["map"]
        self.assertAlmostEqual(row["pai"], row["lift_all"])
        self.assertAlmostEqual(row["truth_recall"], 3 / 4)

    def test_chance_ever_between_chance_all_and_one_with_exact_values(self):
        # inject: ever pool built from all stalls instead of the counted ones; or restricted to the candidates
        st = MemoryStore()
        publish(st, [stall("0", "1,1", T - 10), stall("0", "2,2", T - 10), stall("0", "3,3", T - 10),
                     stall("0", "99,99", T - 10),  # outside the candidates
                     stall("0", "8,8", T - 10, next_occupied=True)])  # not counted
        claims(st)
        stream_end(st, T)
        cands = [f"{i},{i}" for i in range(1, 11)]
        b = compute(st, ["0"], cands, {"0": {"1,1", "2,2", "5,5", "6,6"}}, ks=(2,))
        self.assertEqual(b["chance"]["all"], 4 / 10)
        self.assertEqual(b["chance"]["ever"], 2 / 4)  # ever = 1,1 2,2 3,3 99,99; positives among them 1,1 2,2
        self.assertLessEqual(b["chance"]["ever"], 1)
        self.assertGreaterEqual(b["chance"]["ever"], b["chance"]["all"])
        self.assertEqual(b["chance"]["per_zone"]["0"], dict(n_ever=4, n_ever_outside_candidates=1))
        self.assertAlmostEqual(b["k"]["2"]["map"]["lift_ever"], b["k"]["2"]["map"]["truth_precision"] / 0.5)

    def test_zero_positives_gives_null_recall_pai_and_lifts(self):
        # inject: division by zero positives
        st = MemoryStore()
        publish(st, [stall("0", "1,1", T - 10)])
        claims(st)
        stream_end(st, T)
        b = compute(st, ["0"], ["1,1", "2,2"], {}, ks=(2,))
        row = b["k"]["2"]["map"]
        self.assertEqual((row["truth_recall"], row["pai"], row["lift_all"]), (None, None, None))
        self.assertEqual(row["truth_precision"], 0.0)


class TestPairedAndOutcome(unittest.TestCase):
    def test_identical_inputs_give_delta_zero_within_noise(self):
        # inject: bootstrap resamples map and persistence independently
        st = MemoryStore()
        for z in ("0", "1", "2"):  # one flagged cell per zone: both lists are the same
            publish(st, [stall(z, "1,1", T - 10)])
        claims(st, zones=("0", "1", "2"))
        stream_end(st, T, zones=("0", "1", "2"))
        pos = {"0": {"1,1"}, "1": set(), "2": {"1,1"}}
        b = compute(st, ["0", "1", "2"], ["1,1", "2,2"], pos, ks=(20, 40))
        for k in ("20", "40"):
            p = b["paired"][k]["truth_precision"]
            self.assertEqual((p["mean"], p["ci95"], p["verdict"], p["n_zones"]), (0.0, [0.0, 0.0], "within noise", 3))

    def test_clear_win_is_beats_and_clear_loss_is_worse(self):
        # inject: verdict compares the mean instead of the CI
        self.assertEqual(baselines.paired_ci([0.1, 0.2, 0.15, 0.1])["verdict"], "beats")
        self.assertEqual(baselines.paired_ci([-0.1, -0.2, -0.15, -0.1])["verdict"], "worse")
        self.assertEqual(baselines.paired_ci([0.1, -0.1, 0.0, 0.05])["verdict"], "within noise")
        self.assertEqual(baselines.paired_ci([]), dict(mean=None, ci95=None, verdict=None, n_zones=0))

    def test_no_eligible_unit_gives_zero_outcome_units_and_nulls(self):
        # inject: the outcome gate is skipped, or an empty gate raises
        st = MemoryStore()
        publish(st, DISAGREE)
        claims(st)
        stream_end(st, T + H - 1)  # the window (T, T + H] is not fully observed
        b = compute(st, ["0"], ["1,1", "2,2", "3,3"], {"0": {"2,2"}}, ks=(2, 20, 40))
        self.assertEqual((b["n_units_outcome"], b["n_units_truth"]), (0, 1))
        for f in ("map", "persistence"):
            self.assertIsNone(b["k"]["2"][f]["outcome_precision"])
            self.assertEqual(b["k"]["2"][f]["hits"]["outcome"], 0)
        self.assertEqual(b["paired"]["20"]["outcome_precision"],
                         dict(mean=None, ci95=None, verdict=None, n_zones=0))
        self.assertEqual(b["paired"]["20"]["truth_precision"]["n_zones"], 1)

    def test_a_short_horizon_and_a_missing_stream_end_are_not_eligible(self):
        # inject: forecast_grade.DEFAULT_MIN_HORIZON_S ignored; stream_end None treated as infinite
        st = MemoryStore()
        publish(st, DISAGREE)
        claims(st, horizon=60)
        stream_end(st, T + 10_000)
        self.assertEqual(compute(st, ["0"], ["1,1"], {}, ks=(2,))["n_units_outcome"], 0)
        st2 = MemoryStore()
        publish(st2, DISAGREE)
        claims(st2)
        self.assertEqual(compute(st2, ["0"], ["1,1"], {}, ks=(2,))["n_units_outcome"], 0)

    def test_outcome_rank_uses_the_map_recomputed_at_t_plus_h(self):
        # inject: outcome rank read from the publish at t instead of recomputed at t + H
        # at T + H (600 s later) the two fresh B stalls and C beat the old A stalls only if A's score is lower; later
        # stall D (3 fresh stalls just before T + H) takes rank 1.
        later = [stall("0", "4,4", T + H - 10) for _ in range(3)]
        st = MemoryStore()
        publish(st, DISAGREE + later)  # the stall at T + H - 10 > T is outside the window of the publish at T
        claims(st)
        stream_end(st, T + H)
        b = compute(st, ["0"], ["1,1", "2,2", "3,3", "4,4"], {}, ks=(1,))
        # map at T (stalls with end <= T): B first. At T + H: 4,4 first (3 stalls, ~3), B second (2 * 2 ** (-700 / 3600) = 1.75)
        # K = 1: B is not rank 1 at T + H, so the map's outcome hit is 0; persistence picks A (rank 3 at T + H): 0.
        self.assertEqual(b["n_units_outcome"], 1)
        self.assertEqual(b["k"]["1"]["map"]["outcome_precision"], 0.0)
        self.assertEqual(b["k"]["1"]["persistence"]["outcome_precision"], 0.0)
        # K = 3: map top 3 = B, A, C; at T + H the top 3 are 4,4, B, A (C scores 0.5): B and A hit
        b3 = compute(st, ["0"], ["1,1", "2,2", "3,3", "4,4"], {}, ks=(3,))
        self.assertEqual(b3["k"]["3"]["map"]["outcome_precision"], 2 / 3)

    def test_horizon_must_be_unique(self):
        # inject: the first claim's horizon is used
        st = MemoryStore()
        publish(st, DISAGREE)
        st.insert("decisions", [dict(run=RUN, kind="hotspot_forecast", id="a", subject="Z0:1,1",
                                     claim=json.dumps(dict(horizon_s=600))),
                                dict(run=RUN, kind="hotspot_forecast", id="b", subject="Z0:1,1",
                                     claim=json.dumps(dict(horizon_s=1200)))])
        with self.assertRaises(ValueError):
            compute(st, ["0"], ["1,1"], {})
        with self.assertRaises(ValueError):
            compute(MemoryStore(), ["0"], ["1,1"], {})  # no claim at all


class TestLessonPersistPools(unittest.TestCase):
    def test_three_pools_on_a_hot_cell_lesson(self):
        # inject: chance_window recomputed with another pool; hot_robot lessons counted; chance_all divides by the pool
        # window 0: cell 9,9 x5 + 5 singles (ratio 3 -> lesson); next window: 9,9 x4 + 2 singles, only 9,9 clears (2.0)
        st = tfl.lesson_then_advance(tfl.cell_stalls(4, 2, start=tfl.NEXT), tfl.BASE + 2 * tfl.W)
        lessons.grade_lessons_persist(st, tfl.RUN)
        block = hotspot_score.persist_chance(st, tfl.RUN)
        ever = baselines.ever_pools(st.select("stalls", {"run": tfl.RUN}), True)
        self.assertEqual(len(ever["0"]), 6)
        out = baselines.lesson_persist_block(st, tfl.RUN, ever, 10, block)
        self.assertEqual(out["n_lessons"], 1)
        self.assertEqual(out["n_hot_robot_excluded"], 0)
        self.assertEqual(out["observed_rate"], 1.0)
        self.assertAlmostEqual(out["chance_window"], block["chance_mean"])
        self.assertAlmostEqual(out["chance_ever"], 1 / 6)
        self.assertAlmostEqual(out["chance_all"], 1 / 10)
        self.assertAlmostEqual(out["lift_ever"], 6.0)
        self.assertAlmostEqual(out["lift_all"], 10.0)
        self.assertTrue(out["s8s_pool_is_ever"])
        self.assertIn("chance_window", out["pools_note"])

    def test_no_lessons_gives_nulls(self):
        # inject: division by zero lessons
        st = MemoryStore()
        out = baselines.lesson_persist_block(st, RUN, {}, 10, hotspot_score.persist_chance(st, RUN))
        self.assertEqual((out["n_lessons"], out["chance_window"], out["lift_all"], out["s8s_pool_is_ever"]),
                         (0, None, None, None))


def sha_tree(path):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(path).iterdir())}


class TestHotspotScoreFlag(unittest.TestCase):
    """A synthetic run through hotspot_score.main: no flag = the old keys and values, flag = the old plus `baselines`."""
    CANDS = [f"{i},{i}" for i in range(1, 11)]

    def make(self, tmp):
        run_dir = Path(tmp) / "run"
        run_dir.mkdir()
        truth = dict(schema_version="fleet-truth/1", env_id="e", disturb_tag="t", disturb={}, steps=100, seed_base=0,
                     zones={"0": dict(seed=0, floor_cells={"1,1": 0.5, "2,2": 0.5}, floor_skips=[], floor_skips_total=0)})
        (run_dir / "truth.json").write_text(json.dumps(truth))
        costmap = dict(run=RUN, generated_at="x", zones={"0": {"1,1": 1.0, "2,2": 0.5}}, **META)
        (run_dir / "costmap.json").write_text(json.dumps(costmap))
        st = JsonlStore(Path(tmp) / "store")
        publish(st, DISAGREE)
        claims(st)
        stream_end(st, T + H)
        st.close()
        return run_dir

    def run_main(self, run_dir, tmp, name, *extra):
        out = Path(tmp) / name
        with contextlib.redirect_stdout(io.StringIO()), \
                mock.patch.object(hotspot_score, "candidate_cells", return_value=self.CANDS):
            rc = hotspot_score.main(["--run-dir", run_dir, "--store", f"jsonl:{Path(tmp) / 'store'}", "--tag", "t",
                                     "--out", out, *extra])
        self.assertEqual(rc, 0)
        return json.loads(out.read_text())

    def test_no_flag_output_is_unchanged_and_flag_only_appends(self):
        # inject: `baselines` always written; a key reordered or altered by the flag; the store written by --baselines
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self.make(tmp)
            before = sha_tree(Path(tmp) / "store")
            plain = self.run_main(run_dir, tmp, "plain.json")
            with_flag = self.run_main(run_dir, tmp, "flag.json", "--baselines")
            self.assertEqual(sha_tree(Path(tmp) / "store"), before)
        self.assertEqual(list(plain), ["zones", "mean", "grading_counts", "rank_grading", "stall_in_episode",
                                       "lesson_grading", "tag", "run", "config", "costmap", "platform",
                                       "lesson_persist_chance", "truth_kinds"])
        self.assertEqual(list(with_flag), list(plain) + ["baselines"])
        self.assertEqual({k: v for k, v in with_flag.items() if k != "baselines"}, plain)
        self.assertEqual(plain["zones"]["0"]["k"]["20"]["hits"], 2)
        self.assertEqual(with_flag["baselines"]["params"]["n_cells_all"], 10)
        self.assertEqual(with_flag["baselines"]["params"]["horizon_s"], H)
        self.assertEqual(with_flag["baselines"]["n_units_outcome"], 1)

    def test_baselines_module_does_not_import_or_read_truth(self):
        # inject: baselines.py imports truth or opens truth.json
        src = (ROOT / "fleet" / "baselines.py").read_text()
        for needle in ("truth.json", "import truth", "from truth", "fleet.truth"):
            self.assertNotIn(needle, src)


if __name__ == "__main__":
    unittest.main()

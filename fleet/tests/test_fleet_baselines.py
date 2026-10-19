"""Tests for S10D fleet/baselines.py and hotspot_score.py --baselines: persistence vs decayed map, PAI, the two chance
lines, the paired zone bootstrap, the outcome gate, the three lesson_persist pools, and that no flag means no change.
Synthetic MemoryStores / tmp JsonlStores only, no fleet/data, no env. Each case names its injection in a `# inject:` line."""
import contextlib
import hashlib
import io
import json
import random
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


# Output of master's (origin/master afa7b2b) hotspot_score.main on TestHotspotScoreFlag.make's fixture, platform dropped,
# pasted as a literal: the no-flag run must equal it key for key.
_K = {"120": 0.016666666666666666, "20": 0.1, "40": 0.05, "80": 0.025}
_ANYK = {k: {"hits": 2, "precision": v, "recall": 1.0} for k, v in _K.items()}
_ANY = {"k": _ANYK, "positives": 2}
_NONE = {"k": {k: {"hits": 0, "precision": 0.0, "recall": None} for k in _K}, "positives": 0}
MASTER_NO_FLAG = {
    "config": {"disturb": {}, "disturb_tag": "t", "emit_schema": None, "emit_status": None, "env_id": "e", "seed_base": 0,
               "steps": 100, "zones": 1},
    "costmap": {"exclude_occupied": True, "generated_at": "x", "half_life_h": 1.0, "min_stalls": 1, "window_hours": 1.0},
    "grading_counts": {}, "lesson_grading": {},
    "lesson_persist_chance": {"chance_mean": None, "chance_median": None, "lift": None, "n_lessons": 0, "observed_ok": 0,
                              "observed_rate": None, "per_lesson": []},
    "mean": {"k": {k: {"precision": v, "recall": 1.0} for k, v in _K.items()}, "n_flagged": 2.0, "spearman": None,
             "zero_stall_share": 0.0},
    "rank_grading": {"rank_graded": 0, "top_k": [], "unranked": 0}, "run": "r",
    "stall_in_episode": {"by_cause": {}, "in_episode": 0, "total_stalls": 6}, "tag": "t",
    "truth_kinds": {"any": _ANY, "blocked": _NONE, "floor": _ANY, "frozen": {"positives": 0, "cells": 0, "k": _NONE["k"]}, "outage": _NONE},
    "zones": {"0": {"k": _ANYK, "n_flagged": 2, "n_floor": 2, "spearman": None, "zero_stall_share": 0.0}}}


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
    """baselines.compute with the key names of the --baselines output (hotspot_score.truth_keys)."""
    return hotspot_score.truth_keys(
        baselines.compute(st, RUN, zones, META, cands, lambda z, t, h: positives.get(z, set()), persist, ks))


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

    def test_ci_is_pinned_for_seed_0_1000_resamples_and_2_5_97_5(self):
        # inject: another seed, resample count or percentile pair (golden value of this implementation)
        p = baselines.paired_ci([-0.05, 0.0, 0.05, 0.1, -0.1, 0.15, 0.0, 0.05, 0.2, -0.025])
        self.assertEqual((p["verdict"], p["n_zones"]), ("within noise", 10))
        self.assertAlmostEqual(p["mean"], 0.0375)
        self.assertAlmostEqual(p["ci95"][0], -0.015)  # 5th percentile would give -0.0076, 200 resamples -0.0101
        self.assertAlmostEqual(p["ci95"][1], 0.09)  # 200 resamples would give 0.0876

    def test_percentile_interpolates_linearly(self):
        # inject: no interpolation between the two neighbouring ranks
        self.assertAlmostEqual(baselines.percentile([0.0, 10.0], 50), 5.0)
        self.assertAlmostEqual(baselines.percentile([0.0, 10.0, 20.0, 40.0], 97.5), 38.5)

    def test_outcome_delta_is_map_minus_persistence(self):
        # inject: the outcome delta computed as persistence - map
        # K 1 per zone: map picks 2,2 (fresh), persistence 1,1 (3 old stalls). At T + H the 1,1 stalls (end T - 3000)
        # fall out of the (T + H - 3600, T + H] window, 2,2 is rank 1: map hits, persistence misses, delta +1 in each zone.
        zones = ("0", "1", "2")
        st = MemoryStore()
        for z in zones:
            publish(st, [dict(s, zone=z) for s in DISAGREE])
        claims(st, zones=zones)
        stream_end(st, T + H, zones=zones)
        with mock.patch.object(baselines, "PAIRED_KS", (1,)):  # pair at K 1, where the two forecasts differ
            b = compute(st, list(zones), ["1,1", "2,2", "3,3"], {}, ks=(1,))
        self.assertEqual((b["k"]["1"]["map"]["outcome_precision"], b["k"]["1"]["persistence"]["outcome_precision"]),
                         (1.0, 0.0))
        self.assertEqual(b["paired"]["1"]["outcome_precision"],
                         dict(mean=1.0, ci95=[1.0, 1.0], verdict="beats", n_zones=3))
        self.assertEqual(b["paired"]["1"]["truth_precision"]["mean"], 0.0)  # no positives: both 0

    def test_outcome_tally_accumulates_over_two_publishes_per_zone(self):
        # inject: the per-zone outcome hits or units overwritten per unit instead of accumulated
        # unit 1 at T: DISAGREE as above, map hits 1, persistence 0. Unit 2 at T2: one fresh stall on 5,5, both top-1
        # lists are 5,5 and it is rank 1 at T2 + H, both hit 1. Neither window reaches the other unit's stalls.
        # per zone: map (1 + 1) / 2 = 1.0, persistence (0 + 1) / 2 = 0.5, delta 0.5 in every zone.
        # hits overwritten: map 1 / 2 - persistence 1 / 2 = 0; units overwritten: map 2 / 1 - persistence 1 / 1 = 1.
        t2 = T + 7200
        zones = ("0", "1", "2")
        st = MemoryStore()
        for z in zones:
            publish(st, [dict(s, zone=z) for s in DISAGREE])
            publish(st, [stall(z, "5,5", t2 - 10)], t=t2)
        claims(st, zones=zones)
        stream_end(st, t2 + H, zones=zones)
        with mock.patch.object(baselines, "PAIRED_KS", (1,)):
            b = compute(st, list(zones), ["1,1", "2,2", "3,3", "5,5"], {}, ks=(1,))
        self.assertEqual(b["n_units_outcome"], 6)
        self.assertEqual((b["k"]["1"]["map"]["outcome_precision"], b["k"]["1"]["persistence"]["outcome_precision"]),
                         (6 / 6, 3 / 6))
        self.assertEqual(b["paired"]["1"]["outcome_precision"],
                         dict(mean=0.5, ci95=[0.5, 0.5], verdict="beats", n_zones=3))

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

    def next_window_store(self):
        # window 0: 9,9 x5 + singles 0,0..4,0 (the lesson on 9,9); next window: 9,9 x3, 7,7 x2, 0,0 x1, mean 2 per
        # stalled cell, so ratios 1.5, exactly 1.0 and 0.5: 9,9 and 7,7 clear the bar, 7,7 only in the next window.
        nxt = tfl.cell_stalls(3, 0, start=tfl.NEXT) + tfl.cell_stalls(2, 0, cell="7,7", start=tfl.NEXT) + \
            [tfl.stall("0,0", tfl.NEXT)]
        st = tfl.lesson_then_advance(nxt, tfl.BASE + 2 * tfl.W)
        lessons.grade_lessons_persist(st, tfl.RUN)
        return st

    def test_next_window_and_the_bar_at_exactly_persist_ratio(self):
        # inject: pool members graded on the lesson's own window (shift 0); the bar as > or >= 0 instead of >= 1.0
        st = self.next_window_store()
        block = hotspot_score.persist_chance(st, tfl.RUN)
        ever = baselines.ever_pools(st.select("stalls", {"run": tfl.RUN}), True)
        self.assertEqual(len(ever["0"]), 7)  # 9,9, 0,0..4,0, 7,7
        out = baselines.lesson_persist_block(st, tfl.RUN, ever, 10, block)
        self.assertEqual((out["n_lessons"], out["observed_rate"]), (1, 1.0))
        self.assertAlmostEqual(out["chance_ever"], 2 / 7)
        self.assertAlmostEqual(out["chance_all"], 2 / 10)
        self.assertAlmostEqual(out["lift_ever"], 7 / 2)
        self.assertFalse(out["s8s_pool_is_ever"])  # 7,7 stalled only in the next window

    def test_a_hot_robot_lesson_is_excluded_and_counted(self):
        # inject: the hot_cell filter dropped (the robot lesson enters the pools) or the exclusion count not computed
        st = self.next_window_store()
        block = hotspot_score.persist_chance(st, tfl.RUN)
        (d,) = lessons.lessons(st, tfl.RUN)
        robot = dict(d, id="robot-lesson", claim=json.dumps(dict(lessons.claim_of(d), lesson_kind="hot_robot",
                                                                 subject="Z0:Z0-01")))
        st.insert("decisions", [robot])
        block = dict(block, per_lesson=block["per_lesson"] + [dict(block["per_lesson"][0], id="robot-lesson",
                                                                   observed=False)])
        ever = baselines.ever_pools(st.select("stalls", {"run": tfl.RUN}), True)
        out = baselines.lesson_persist_block(st, tfl.RUN, ever, 10, block)
        self.assertEqual((out["n_lessons"], out["n_hot_robot_excluded"], out["observed_rate"]), (1, 1, 1.0))
        self.assertAlmostEqual(out["chance_ever"], 2 / 7)

    def test_only_hot_robot_lessons_still_report_the_exclusion(self):
        # inject: the no-hot_cell early return drops n_hot_robot_excluded
        st = self.next_window_store()
        block = hotspot_score.persist_chance(st, tfl.RUN)
        (d,) = lessons.lessons(st, tfl.RUN)
        st.upsert("decisions", ("id",), [dict(d, claim=json.dumps(dict(lessons.claim_of(d), lesson_kind="hot_robot")))])
        out = baselines.lesson_persist_block(st, tfl.RUN, {}, 10, block)
        self.assertEqual((out["n_lessons"], out["n_hot_robot_excluded"], out["chance_ever"]), (0, 1, None))

    def test_no_lessons_gives_nulls(self):
        # inject: division by zero lessons
        st = MemoryStore()
        out = baselines.lesson_persist_block(st, RUN, {}, 10, hotspot_score.persist_chance(st, RUN))
        self.assertEqual((out["n_lessons"], out["chance_window"], out["lift_all"], out["s8s_pool_is_ever"]),
                         (0, None, None, None))


def replay_ci(deltas):
    """Independent re-derivation of the zone bootstrap (hard-coded seed 0, 1000 resamples, 2.5 / 97.5 percentiles with
    linear interpolation); imports nothing from baselines, so a changed constant there moves the code, not this."""
    n = len(deltas)
    rng = random.Random(0)
    means = sorted(sum(deltas[rng.randrange(n)] for _ in range(n)) / n for _ in range(1000))

    def pct(q):
        pos = (len(means) - 1) * q / 100
        lo = int(pos)
        return means[lo] + (means[min(lo + 1, len(means) - 1)] - means[lo]) * (pos - lo)
    return pct(2.5), pct(97.5)


NC = 45  # cells "00,0" .. "44,0" per zone; the published map ranks them by index (cost 1 - i / 100)
NUMERIC = ("1", "2", "3", "10", "20")


def cell(i):
    return f"{i:02d},0"


def rot(r):
    return list(range(r, NC)) + list(range(r))


# per zone: the persistence order (raw `stalls` column, descending) and the label positives (cell indexes).
# Map top-K is always cells 0..K-1. Hand-computed hits (map | persistence) per publish, K = 20 then K = 40:
#   zone 1  persistence order 10..44,0..9; positives 0..9
#           K20: map 10, pers 10..29 -> 0:  d = +10/20 = 0.5;   K40: map 10, pers 10..44+0..4 -> 5:  d = +5/40
#   zone 2  persistence order 44..0; positives 25..34 and 2, 3
#           K20: map {2,3} -> 2, pers 25..44 -> 10:  d = -8/20 = -0.4;   K40: map 12, pers 5..44 -> 10:  d = +2/40
#   zone 3  persistence order 15..44,0..14; positives 0..14
#           K20: map 15, pers 15..34 -> 0:  d = +15/20 = 0.75;   K40: map 15, pers 15..44+0..9 -> 10:  d = +5/40
#   zone 10 persistence order 5..44,0..4; positives 0..19 and 40, 41, 42
#           K20: map 20, pers 5..24 -> 15:  d = +5/20 = 0.25;   K40: map 20, pers 5..44 -> 15 + 3 = 18:  d = +2/40
#   zone 20 persistence order 25..44,0..24; positives 0..9 and 25..29
#           K20: map 10, pers 25..44 -> 5:  d = +5/20 = 0.25;   K40: map 10 + 5 = 15, pers 25..44+0..19 -> 5 + 10 = 15: 0
ZONES5 = {
    "1": (rot(10), set(range(10))),
    "2": (list(range(NC - 1, -1, -1)), set(range(25, 35)) | {2, 3}),
    "3": (rot(15), set(range(15))),
    "10": (rot(5), set(range(20)) | {40, 41, 42}),
    "20": (rot(25), set(range(10)) | set(range(25, 30))),
}
D20 = {"1": 0.5, "2": -0.4, "3": 0.75, "10": 0.25, "20": 0.25}
D40 = {"1": 5 / 40, "2": 2 / 40, "3": 5 / 40, "10": 2 / 40, "20": 0.0}


class TestMultiZonePaired(unittest.TestCase):
    """Five zones whose map and persistence top-K differ in a known way, two publishes each (so the per-zone tallies
    accumulate), zones handed to compute() in an order that is neither numeric nor string order."""
    INPUT = ["1", "20", "10", "3", "2"]  # numeric order 1 2 3 10 20, string order 1 10 2 20 3

    def build(self):
        st = MemoryStore()
        rows = []
        for z, (order, _) in ZONES5.items():
            for t in (T, T + 100):
                rows += [dict(run=RUN, zone=z, published_at=t, cell=cell(i), cost=round(1 - i / 100, 6),
                              score=1.0, stalls=100 - order.index(i)) for i in range(NC)]
        st.insert("costmap", rows)
        claims(st, zones=tuple(ZONES5))
        return st

    def run_compute(self, order=None):
        pos = {z: {cell(i) for i in p} for z, (_, p) in ZONES5.items()}
        return baselines.compute(self.build(), RUN, order or self.INPUT, META, [cell(i) for i in range(NC)],
                                 lambda z, t, h: pos[z], None, (20, 40))

    def test_expected_deltas_follow_from_the_fixture(self):
        # the table above re-derived by set arithmetic, so the literals below are not circular
        for k, want in ((20, D20), (40, D40)):
            for z, (order, p) in ZONES5.items():
                self.assertAlmostEqual(len(set(range(k)) & p) / k - len(set(order[:k]) & p) / k, want[z])

    def test_paired_label_delta_mean_ci_verdict_and_hits(self):
        # inject: delta sign flipped (persistence - map); a per-zone hit / unit tally overwritten instead of
        # accumulated; zone_sort_key constant (CI index order follows the input order); a changed seed / percentile
        b = self.run_compute()
        self.assertEqual(b["n_units_label"], 10)
        # pooled hits over 2 publishes: the per-zone hits of the comment table (zones 1 2 3 10 20), doubled
        self.assertEqual(b["k"]["20"]["map"]["hits"]["label"], 2 * (10 + 2 + 15 + 20 + 10))
        self.assertEqual(b["k"]["20"]["persistence"]["hits"]["label"], 2 * (0 + 10 + 0 + 15 + 5))
        self.assertEqual(b["k"]["40"]["map"]["hits"]["label"], 2 * (10 + 12 + 15 + 20 + 15))
        self.assertEqual(b["k"]["40"]["persistence"]["hits"]["label"], 2 * (5 + 10 + 10 + 18 + 15))
        self.assertEqual(b["k"]["20"]["map"]["hits"]["positives"], 2 * (10 + 12 + 15 + 23 + 15))
        self.assertAlmostEqual(b["k"]["20"]["map"]["label_precision"], 114 / (20 * 10))
        # K 20: deltas in numeric zone order [0.5, -0.4, 0.75, 0.25, 0.25], mean 1.35 / 5
        p20 = b["paired"]["20"]["label_precision"]
        self.assertAlmostEqual(p20["mean"], 0.27)
        self.assertEqual(p20["n_zones"], 5)
        self.assertAlmostEqual(p20["ci95"][0], -0.09, places=12)
        self.assertAlmostEqual(p20["ci95"][1], 0.6, places=12)
        self.assertEqual(p20["verdict"], "within noise")
        # K 40: [0.125, 0.05, 0.125, 0.05, 0.0], mean 0.35 / 5
        p40 = b["paired"]["40"]["label_precision"]
        self.assertAlmostEqual(p40["mean"], 0.07)
        self.assertEqual(p40["n_zones"], 5)
        self.assertAlmostEqual(p40["ci95"][0], 0.03, places=12)
        self.assertAlmostEqual(p40["ci95"][1], 0.11, places=12)
        self.assertEqual(p40["verdict"], "beats")  # CI low 0.03 > 0
        # the literals above against the independent replay of the bootstrap over the numeric-order deltas
        for k, d in (("20", D20), ("40", D40)):
            lo, hi = replay_ci([d[z] for z in NUMERIC])
            got = b["paired"][k]["label_precision"]["ci95"]
            self.assertAlmostEqual(got[0], lo, places=12)
            self.assertAlmostEqual(got[1], hi, places=12)
        # outcome precision: no stream_end, so no unit is eligible
        self.assertEqual(b["paired"]["20"]["outcome_precision"], dict(mean=None, ci95=None, verdict=None, n_zones=0))

    def test_zone_order_given_to_compute_does_not_change_the_result(self):
        # inject: zone_sort_key constant / string order: the same deltas land on other bootstrap indexes
        want = self.run_compute()["paired"]
        self.assertEqual(self.run_compute(list(NUMERIC))["paired"], want)
        self.assertEqual(self.run_compute(["20", "3", "2", "10", "1"])["paired"], want)
        self.assertEqual(list(self.run_compute()["chance"]["per_zone"]), list(NUMERIC))

    def test_the_fixture_is_sensitive_to_the_order_of_the_deltas(self):
        # guard on the fixture: in input or string order the CI differs, so the pins above bite
        num20 = replay_ci([D20[z] for z in NUMERIC])
        self.assertNotEqual(num20, replay_ci([D20[z] for z in self.INPUT]))
        self.assertNotEqual(num20, replay_ci([D20[z] for z in ("1", "10", "2", "20", "3")]))
        self.assertNotEqual(replay_ci([D40[z] for z in NUMERIC]), replay_ci([D40[z] for z in self.INPUT]))


class TestHalfLifeIsNotTheWindow(unittest.TestCase):
    def test_params_carry_both_and_the_two_forecasts_differ_under_that_half_life(self):
        # inject: params.half_life_h read from window_hours (or the reverse), or the half-life ignored by the publish
        # window 2 h, half-life 0.5 h: A 3 stalls at T - 3000 -> 3 * 2 ** (-3000 / 1800) = 0.945, B 2 stalls at T - 100
        # -> 2 * 2 ** (-100 / 1800) = 1.924, C 1 stall at T - 100 -> 0.962. Map order B, C, A; persistence A, B, C.
        meta = dict(window_hours=2.0, half_life_h=0.5, min_stalls=1, exclude_occupied=True)
        st = MemoryStore()
        st.insert("stalls", DISAGREE)
        rows = []
        for z, cells in hotspot.cost_zones(DISAGREE, T, 2.0, 0.5, 1, True).items():
            rows += [dict(run=RUN, zone=z, published_at=T, cell=c, cost=v["cost"], score=v["score"], stalls=v["stalls"])
                     for c, v in cells.items()]
        st.insert("costmap", rows)
        claims(st)
        by_cell = {r["cell"]: r for r in rows}
        self.assertEqual(baselines.map_top(by_cell), ["2,2", "3,3", "1,1"])
        self.assertEqual(baselines.persistence_top(by_cell), ["1,1", "2,2", "3,3"])
        b = baselines.compute(st, RUN, ["0"], meta, ["1,1", "2,2", "3,3", "4,4"], lambda z, t, h: {"2,2"}, None, (1,))
        self.assertEqual(b["params"]["window_hours"], 2.0)
        self.assertEqual(b["params"]["half_life_h"], 0.5)
        self.assertEqual(b["k"]["1"]["map"]["hits"]["label"], 1)  # B first
        self.assertEqual(b["k"]["1"]["persistence"]["hits"]["label"], 0)  # A first


class TestLessonPersistMeans(unittest.TestCase):
    """Three hot_cell lessons (zones 0, 1, 2) with different rates, built directly; 10 candidate cells in all."""
    def build(self):
        s, nx = tfl.BASE + 10, tfl.NEXT
        st = MemoryStore()
        # zone 0: own window 1,1 x3 + 2,2 x1; the ever pool also holds 3,3 and 4,4 (stalled elsewhere): own != ever.
        # Next window 1,1 x2 + 3,3 x2: n 4, d 2 -> ratio of 1,1 and 3,3 = 1.0 = PERSIST_RATIO (clears); 2,2, 4,4 absent.
        stalls = [tfl.stall("1,1", s, "0") for _ in range(3)] + [tfl.stall("2,2", s, "0")]
        stalls += [tfl.stall("1,1", nx, "0") for _ in range(2)] + [tfl.stall("3,3", nx, "0") for _ in range(2)]
        # zone 1: own window 1,1 2,2 3,3 once each = exactly its ever pool. Next window 1,1 x3 + 2,2 x1: n 4, d 2 ->
        # ratio of 1,1 = 1.5 clears, 2,2 = 0.5, 3,3 absent.
        stalls += [tfl.stall(c, s, "1") for c in ("1,1", "2,2", "3,3")]
        stalls += [tfl.stall("1,1", nx, "1") for _ in range(3)] + [tfl.stall("2,2", nx, "1")]
        # zone 2: no stalls at all, empty ever pool.
        st.insert("stalls", stalls)
        st.insert("decisions", [dict(run=RUN, kind=lessons.KIND, id=f"L{z}", subject=f"Z{z}:cell 1,1",
                                     claim=json.dumps(dict(lesson_kind="hot_cell", zone=z,
                                                           window_end=tfl.BASE + tfl.W)))
                                for z in ("0", "1", "2")])
        # the last lesson iterated (zone 2) has own pool == its (empty) ever pool; the first (zone 0) does not
        per = [dict(id="L0", window_start=tfl.BASE, chance=0.3, observed=True),
               dict(id="L1", window_start=tfl.BASE, chance=0.6, observed=False),
               dict(id="L2", window_start=tfl.BASE, chance=0.15, observed=True)]
        ever = {"0": {"1,1", "2,2", "3,3", "4,4"}, "1": {"1,1", "2,2", "3,3"}}
        return st, dict(per_lesson=per), ever

    def test_means_over_unequal_lessons_with_an_empty_pool_and_a_mixed_same_pool(self):
        # inject: means without / n; same_pool overwritten instead of accumulated (only the last lesson has own ==
        # ever); empty-pool ever rate 0.0 -> 1.0; observed counted over the wrong lessons
        st, block, ever = self.build()
        out = baselines.lesson_persist_block(st, RUN, ever, 10, block)
        self.assertEqual(out["n_lessons"], 3)
        self.assertEqual(out["n_hot_robot_excluded"], 0)
        # chance_window: (0.3 + 0.6 + 0.15) / 3
        self.assertAlmostEqual(out["chance_window"], 1.05 / 3)
        # chance_ever: zone 0 clears {1,1 3,3} of 4 = 0.5, zone 1 clears {1,1} of 3 = 1/3, zone 2 pool empty = 0.0
        self.assertAlmostEqual(out["chance_ever"], (2 / 4 + 1 / 3 + 0.0) / 3)
        self.assertAlmostEqual(out["chance_ever"], 5 / 18)
        # chance_all: 2 / 10, 1 / 10, 0 / 10 -> 0.1
        self.assertAlmostEqual(out["chance_all"], (0.2 + 0.1 + 0.0) / 3)
        # observed: ok, off, ok -> 2 / 3
        self.assertAlmostEqual(out["observed_rate"], 2 / 3)
        self.assertAlmostEqual(out["lift_window"], (2 / 3) / 0.35)
        self.assertAlmostEqual(out["lift_ever"], (2 / 3) / (5 / 18))
        self.assertAlmostEqual(out["lift_ever"], 2.4)
        self.assertAlmostEqual(out["lift_all"], (2 / 3) / 0.1)
        self.assertIs(out["s8s_pool_is_ever"], False)

    def test_zero_candidate_cells_gives_a_zero_chance_all_and_a_null_lift(self):
        # inject: the n_all == 0 fallback rate 0.0 -> 1.0
        st, block, ever = self.build()
        out = baselines.lesson_persist_block(st, RUN, ever, 0, block)
        self.assertEqual(out["chance_all"], 0.0)
        self.assertIsNone(out["lift_all"])
        self.assertAlmostEqual(out["chance_ever"], 5 / 18)

    def test_a_lesson_whose_own_pool_is_the_ever_pool_alone_reports_true(self):
        # the other branch of s8s_pool_is_ever: only zone 1's lesson (own == ever), observed off
        st, block, ever = self.build()
        out = baselines.lesson_persist_block(st, RUN, ever, 10, dict(per_lesson=[block["per_lesson"][1]]))
        self.assertIs(out["s8s_pool_is_ever"], True)
        self.assertAlmostEqual(out["chance_ever"], 1 / 3)
        self.assertEqual(out["observed_rate"], 0.0)
        self.assertEqual(out["lift_ever"], 0.0)


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
        self.assertEqual({k: v for k, v in plain.items() if k != "platform"}, MASTER_NO_FLAG)  # == master's output
        self.assertEqual(list(with_flag), list(plain) + ["baselines"])
        self.assertEqual({k: v for k, v in with_flag.items() if k != "baselines"}, plain)
        self.assertEqual(plain["zones"]["0"]["k"]["20"]["hits"], 2)
        self.assertEqual(with_flag["baselines"]["params"]["n_cells_all"], 10)
        self.assertEqual(with_flag["baselines"]["params"]["horizon_s"], H)
        self.assertEqual(with_flag["baselines"]["n_units_outcome"], 1)

    def test_lesson_persist_pools_reach_the_output_through_main(self):
        # inject: baselines_block not handed the lesson_persist_chance block (persist_block=None)
        # the next-window lesson fixture (TestLessonPersistPools) in the same store as the costmap fixture; the lesson
        # stalls sit at BASE (2026), the costmap stalls at T, so neither window sees the other's stalls.
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self.make(tmp)
            # built apart and copied in: extracting lessons in the run's store would walk every window from the
            # costmap stalls at T (1970) to BASE; score_run reads in_episode on every stall
            mem = TestLessonPersistPools.next_window_store(None)
            st = JsonlStore(Path(tmp) / "store")
            for table, rows in mem._rows.items():
                st.insert(table, [dict(r, in_episode=None) if table == "stalls" else r for r in rows])
            st.close()
            res = self.run_main(run_dir, tmp, "flag.json", "--baselines")
        lp, chance = res["baselines"]["lesson_persist"], res["lesson_persist_chance"]
        self.assertEqual((lp["n_lessons"], chance["n_lessons"], lp["observed_rate"]), (1, 1, 1.0))
        self.assertAlmostEqual(lp["chance_window"], chance["chance_mean"])
        self.assertAlmostEqual(lp["chance_ever"], 2 / 10)  # ever pool: the 7 lesson cells + 1,1 2,2 3,3
        self.assertAlmostEqual(lp["chance_all"], 2 / 10)  # N_all = the 10 mocked candidates

    def test_truth_window_is_t_to_t_plus_h_through_main(self):
        # inject: the step window collapsed (s1 = s0), shifted, or the positives not drawn from truth_positive over the
        # candidates. v2 truth, step_seconds 1 and t0 at epoch 0, so step = epoch: the window is [T, T + H].
        # 1,1 floor (time-free) and 3,3 blocked strictly inside (T, T + H] are positive; 4,4 blocked ended before T,
        # 5,5 outage starts after T + H, 2,2 has nothing. Map top-20 = the 3 flagged cells 1,1 2,2 3,3.
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self.make(tmp)
            truth = json.loads((run_dir / "truth.json").read_text())
            truth.update(schema_version="fleet-truth/2", t0="1970-01-01T00:00:00Z", step_seconds=1)
            truth["zones"]["0"].update(
                floor_cells={"1,1": 0.5},
                blocked_windows=[dict(cell="3,3", start_step=T + 300, end_step=T + 400),
                                 dict(cell="4,4", start_step=T - 100, end_step=T - 10)],
                outage_windows=[dict(cell="5,5", start_step=T + H + 1, end_step=T + H + 50)], frozen_windows=[])
            (run_dir / "truth.json").write_text(json.dumps(truth))
            b = self.run_main(run_dir, tmp, "flag.json", "--baselines")["baselines"]
        m = b["k"]["20"]["map"]
        self.assertEqual(b["n_units_truth"], 1)
        self.assertEqual(m["hits"]["truth"], 2)
        self.assertEqual(m["hits"]["positives"], 2)
        self.assertAlmostEqual(m["truth_precision"], 2 / 20)
        self.assertAlmostEqual(m["truth_recall"], 1.0)
        self.assertAlmostEqual(m["pai"], (2 / 2) / (20 / 10))
        self.assertAlmostEqual(b["chance"]["all"], 2 / 10)
        self.assertAlmostEqual(b["chance"]["ever"], 2 / 3)  # ever pool = the 3 stalled cells, 2 of them positive
        self.assertAlmostEqual(m["lift_all"], (2 / 20) / (2 / 10))
        self.assertAlmostEqual(m["lift_ever"], (2 / 20) / (2 / 3))
        self.assertEqual(b["k"]["20"]["persistence"]["hits"]["truth"], 2)

    def test_baselines_module_does_not_import_or_read_truth(self):
        # inject: baselines.py imports truth or opens truth.json
        src = (ROOT / "fleet" / "baselines.py").read_text()
        # the analyst-isolation scan (test_fleet_hotspot.TestAnalystIsolation) bans this vocabulary outside exempt files
        self.assertNotRegex(src, r"floor_cells|floor_skip|floor_coin|applied_floor|truth")

    def test_truth_keys_renames_only_the_label_vocabulary(self):
        # inject: the rename misses a nested key
        got = hotspot_score.truth_keys({"n_units_label": 1, "k": {"20": {"map": {"label_precision": 1,
                                                                                "hits": {"label": 3}}}},
                                        "paired": {"20": {"label_recall": [{"label_x": 1}]}}})
        self.assertEqual(got, {"n_units_truth": 1, "k": {"20": {"map": {"truth_precision": 1, "hits": {"truth": 3}}}},
                               "paired": {"20": {"truth_recall": [{"truth_x": 1}]}}})


if __name__ == "__main__":
    unittest.main()

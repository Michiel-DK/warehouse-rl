"""Tests for S8B on scripted messages and in-memory stores: parser fields, stall extraction, aggregation, cost map,
hotspot_forecast decisions, grading (outcome and truth), the score script and the analyst-isolation rule.
No env, no Docker. Each case names its injection in a `# inject:` comment."""
import builtins
import contextlib
import dataclasses
import gzip
import io
import json
import math
import random
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "fleet",):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import costmap  # noqa: E402
import grade  # noqa: E402
import hotspot_score  # noqa: E402
from fleet.tests.test_fleet_clickhouse_store import HIDDEN, RecordingStore, schema_tables  # noqa: E402
from fleet.tests.test_fleet_ingest import BASE, GrowingGz, bounded_sleep, ingest_dir, line  # noqa: E402
from fleet_analyser.ingest import Ingester  # noqa: E402
from fleet_analyser import clickhouse_store as chs  # noqa: E402
from fleet_analyser import decisions, forecast_grade, hotspot  # noqa: E402
from fleet_analyser import grade as decision_grade  # noqa: E402
from fleet_analyser.parse import Message, iso as iso_of, parse_line  # noqa: E402
from fleet_analyser.store import JsonlStore, MemoryStore  # noqa: E402

RIGHT, UP, LEFT, DOWN = 0.0, math.pi / 2, math.pi, -math.pi / 2


def node(x, y):
    return [{"nodeId": f"{x}-{y}", "sequenceId": 0, "released": True,
             "nodePosition": {"x": x, "y": y, "mapId": "m"}}]


def msg(hid, ts, serial="Z0-01", order="o1", x=5, y=5, theta=RIGHT, nxt=(6, 5), faulted=False, reported=None):
    """A Message. nxt=None with reported=True is nodeStates []; reported=False is the key absent (old schema)."""
    if reported is None:
        reported = True
    return Message(serial=serial, zone=serial.split("-")[0][1:], header_id=hid, ts=ts, order_id=order, x=x, y=y,
                   driving=False, faulted=faulted, loaded=False, raw_len=1, theta=theta,
                   next_x=None if nxt is None else nxt[0], next_y=None if nxt is None else nxt[1],
                   nodes_reported=reported)


def pair(**kw):
    return [msg(0, 100), msg(1, 105)] if not kw else [msg(0, 100), msg(1, 105, **kw)]


def stalls_of(msgs):
    return hotspot.extract_stalls(msgs, "r")


class TestParserFields(unittest.TestCase):
    def raw(self, **over):
        obj = {"schema_version": "fleet-state/2", "headerId": 1, "timestamp": "2026-01-01T00:00:00Z",
               "manufacturer": "sim", "serialNumber": "Z0-01", "orderId": "o", "lastNodeId": "1-1",
               "nodeStates": node(2, 1), "agvPosition": {"x": 1, "y": 1, "theta": 1.5708, "mapId": "m"},
               "driving": False, "paused": False, "errors": [], "loads": [], "custom": {}}
        obj.update(over)
        return json.dumps(obj).encode()

    def test_theta_and_first_node_parsed(self):
        # inject: read next_x from the last nodeStates entry, or swap next_x / next_y
        m, why = parse_line(self.raw())
        self.assertIsNone(why)
        self.assertEqual((m.theta, m.next_x, m.next_y, m.nodes_reported), (1.5708, 2, 1, True))

    def test_empty_node_states_differs_from_absent(self):
        # inject: nodes_reported = bool(nodeStates) (collapses [] into absent)
        m, _ = parse_line(self.raw(nodeStates=[]))
        self.assertEqual((m.next_x, m.next_y, m.nodes_reported), (None, None, True))
        obj = json.loads(self.raw())
        del obj["nodeStates"], obj["agvPosition"]["theta"]
        m, why = parse_line(json.dumps(obj).encode())
        self.assertIsNone(why)
        self.assertEqual((m.theta, m.next_x, m.next_y, m.nodes_reported), (None, None, None, False))

    PRE = ("serial", "zone", "header_id", "ts", "order_id", "x", "y", "driving", "faulted", "loaded")

    def test_unusable_fields_degrade_never_reject(self):
        # inject: return (None, "type") for a malformed theta / nodeStates again (the pass-1 regression)
        base = json.loads(self.raw())
        del base["nodeStates"], base["agvPosition"]["theta"]
        master, why = parse_line(json.dumps(base).encode())  # what master's parser makes of the same message
        self.assertIsNone(why)
        bad_nodes = [dict(nodeStates="x"), dict(nodeStates=[1]), dict(nodeStates=None),
                     dict(nodeStates=[{"nodePosition": {"x": "a", "y": 1}}]), dict(nodeStates=[{"nodeId": "1-1"}]),
                     dict(nodeStates=[{"nodePosition": {"x": 1.5, "y": 1}}]), dict(nodeStates=[{"nodePosition": 3}]),
                     dict(nodeStates=[{"nodePosition": {"x": True, "y": 1}}]), dict(nodeStates={})]
        for over in bad_nodes:
            with self.subTest(over=over):
                m, why = parse_line(self.raw(**over))
                self.assertIsNone(why)
                self.assertEqual([getattr(m, f) for f in self.PRE], [getattr(master, f) for f in self.PRE])
                self.assertEqual((m.next_x, m.next_y, m.nodes_reported), (None, None, True))
        for theta in ("left", True, None, float("nan"), float("inf"), [1]):
            with self.subTest(theta=theta):
                obj = json.loads(self.raw())
                obj["agvPosition"]["theta"] = theta
                m, why = parse_line(json.dumps(obj).encode())  # json.dumps writes NaN / Infinity tokens
                self.assertIsNone(why)
                self.assertIsNone(m.theta)
                self.assertEqual([getattr(m, f) for f in self.PRE], [getattr(master, f) for f in self.PRE])
        obj = json.loads(self.raw())
        del obj["agvPosition"]["theta"]
        self.assertIsNone(parse_line(json.dumps(obj).encode())[0].theta)

    def test_integer_theta_too_large_for_a_float(self):
        # inject: drop the OverflowError / ValueError guard in parse._num (the pass-2 crash)
        text = self.raw().decode().replace("1.5708", "1" + "0" * 400)
        self.assertIn("1" + "0" * 400, text)
        m, why = parse_line(text.encode())
        bad, bad_why = parse_line(self.raw(agvPosition={"x": 1, "y": 1, "theta": "abc", "mapId": "m"}))
        self.assertEqual((why, bad_why), (None, None))
        self.assertIsNone(m.theta)
        self.assertEqual(dataclasses.replace(m, raw_len=0), dataclasses.replace(bad, raw_len=0))  # same as theta="abc"
        with tempfile.TemporaryDirectory() as d:
            with gzip.open(Path(d) / "zone0-000.jsonl.gz", "wb") as f:
                f.write(text.encode() + b"\n")
            ing, store, code = ingest_dir(d, once=True)  # does not raise
            self.assertEqual(code, 0)
            self.assertEqual(ing.ledger.total("messages_accepted"), 1)

    def test_vda_float_coordinates(self):
        # inject: read float x / y as None always, or truncate 2.5 to 2
        m, why = parse_line(self.raw(nodeStates=[{"nodePosition": {"x": 3.0, "y": 4.0}}]))
        self.assertEqual((why, m.next_x, m.next_y), (None, 3, 4))
        m, _ = parse_line(self.raw(nodeStates=[{"nodePosition": {"x": 2.5, "y": 4.0}}]))
        self.assertEqual((m.next_x, m.next_y, m.nodes_reported), (None, None, True))
        m, _ = parse_line(self.raw(nodeStates=[{"nodeId": "a", "sequenceId": 0, "released": True}]))
        self.assertEqual((m.next_x, m.nodes_reported), (None, True))

    def test_pre_existing_rejects_unchanged(self):
        # inject: accept a message with a bad pre-existing field because the new fields parse
        obj = json.loads(self.raw())
        obj["driving"] = "no"
        self.assertEqual(parse_line(json.dumps(obj).encode()), (None, "type"))
        obj = json.loads(self.raw())
        del obj["orderId"]
        self.assertEqual(parse_line(json.dumps(obj).encode())[1], "missing:orderId")
        self.assertEqual(parse_line(b"not json")[1], "json")
        self.assertEqual(parse_line(self.raw(timestamp="yesterday"))[1], "timestamp")


class TestStallExtraction(unittest.TestCase):
    def test_next_cell_attribution_not_curs_replanned_node(self):
        # inject: attribute to cur's next node instead of prev's
        (s,) = stalls_of([msg(0, 100), msg(1, 105, nxt=(5, 4))])  # cur replanned upward
        self.assertEqual((s["cell"], s["attribution"], s["n_msgs"]), ("6,5", "next", 1))
        self.assertEqual((s["start"], s["end"], s["seconds"]), (100, 105, 5))

    def test_front_cell_must_match_prev_theta(self):
        # inject: drop the front-cell check
        self.assertEqual(stalls_of([msg(0, 100, nxt=(5, 4)), msg(1, 105)]), [])  # facing RIGHT, next node above
        for theta, nxt in ((UP, (5, 4)), (LEFT, (4, 5)), (DOWN, (5, 6))):
            with self.subTest(theta=theta):
                (s,) = stalls_of([msg(0, 100, theta=theta, nxt=nxt), msg(1, 105, theta=theta)])
                self.assertEqual(s["cell"], f"{nxt[0]},{nxt[1]}")

    def test_old_schema_current_cell_fallback(self):
        # inject: fallback without theta, or attribute to the next cell
        (s,) = stalls_of([msg(0, 100, nxt=None, reported=False), msg(1, 105, nxt=None, reported=False)])
        self.assertEqual((s["cell"], s["attribution"]), ("5,5", "current"))
        no_theta = [msg(0, 100, theta=None, nxt=None, reported=False), msg(1, 105, theta=None, nxt=None, reported=False)]
        self.assertEqual(stalls_of(no_theta), [])  # a fleet-state/1 pair

    def test_empty_node_states_is_never_a_stall(self):
        # inject: treat nodeStates [] like an absent key
        self.assertEqual(stalls_of([msg(0, 100, nxt=None), msg(1, 105, nxt=(6, 5))]), [])

    def test_non_stall_pairs(self):
        # inject: drop one of the conditions in _stall_pair
        cases = {
            "order inactive": [msg(0, 100, order=""), msg(1, 105, order="")],
            "order changed": [msg(0, 100), msg(1, 105, order="o2")],
            "order dropped on cur": [msg(0, 100), msg(1, 105, order="")],
            "moved": [msg(0, 100), msg(1, 105, x=6)],
            "turned": [msg(0, 100), msg(1, 105, theta=UP)],
            "faulted": [msg(0, 100), msg(1, 105, faulted=True)],
            "header gap": [msg(0, 100), msg(2, 110)],
        }
        for name, ms in cases.items():
            with self.subTest(name):
                self.assertEqual(stalls_of(ms), [])

    def test_runs(self):
        # inject: one stall per message, or merge runs across a header gap
        (s,) = stalls_of([msg(i, 100 + 5 * i) for i in range(4)])
        self.assertEqual((s["n_msgs"], s["start"], s["end"], s["seconds"]), (3, 100, 115, 15))
        two = stalls_of([msg(0, 100), msg(1, 105), msg(3, 115), msg(4, 120)])  # gap between 1 and 3
        self.assertEqual([(s["start"], s["end"], s["n_msgs"]) for s in two], [(100, 105, 1), (115, 120, 1)])
        other = stalls_of([msg(0, 100), msg(1, 105), msg(2, 110, theta=UP, nxt=(5, 4)), msg(3, 115, theta=UP, nxt=(5, 4))])
        self.assertEqual([(s["cell"], s["n_msgs"]) for s in other], [("6,5", 1), ("5,4", 1)])

    def test_next_occupied(self):
        # inject: ignore the other robot / count the robot itself
        blocker = msg(0, 105, serial="Z0-02", order="", x=6, y=5, theta=RIGHT, nxt=None)
        (s,) = stalls_of([msg(0, 100), msg(1, 105), blocker])
        self.assertTrue(s["next_occupied"])
        elsewhere = msg(0, 105, serial="Z0-02", order="", x=7, y=5, theta=RIGHT, nxt=None)
        (s,) = stalls_of([msg(0, 100), msg(1, 105), elsewhere])
        self.assertFalse(s["next_occupied"])
        other_zone = msg(0, 105, serial="Z1-02", order="", x=6, y=5, theta=RIGHT, nxt=None)
        (s,) = stalls_of([msg(0, 100), msg(1, 105), other_zone])
        self.assertFalse(s["next_occupied"])  # every per-cell quantity is per zone

    def test_annotate_episodes(self):
        # inject: ignore left_censored / interrupted rows, or match on another robot
        (s,) = stalls_of([msg(0, 100), msg(1, 105)])
        ep = dict(zone="0", robot="Z0-01", start=90, end=300, cause="blocked_by_faulted", left_censored=False,
                  resolution="moved")
        hotspot.annotate_episodes([s], [ep])
        self.assertEqual((s["in_episode"], s["faulted_episode"]), ("blocked_by_faulted", True))
        for bad in (dict(ep, left_censored=True), dict(ep, resolution="interrupted"), dict(ep, robot="Z0-02"),
                    dict(ep, start=200), dict(ep, end=95)):
            hotspot.annotate_episodes([s], [bad])
            self.assertEqual((s["in_episode"], s["faulted_episode"]), (None, False), bad)
        hotspot.annotate_episodes([s], [dict(ep, end=None, cause="traffic")])  # still running
        self.assertEqual((s["in_episode"], s["faulted_episode"]), ("traffic", False))


class TestAggregate(unittest.TestCase):
    def st(self, end, **kw):
        return dict(zone="0", cell="6,5", robot="Z0-01", start=end - 5, end=end, seconds=5, n_msgs=1,
                    next_occupied=False, faulted_episode=False, in_episode=None, **kw)

    def test_decay_values(self):
        # inject: use e ** -x instead of 2 ** -x, or a half-life in hours not seconds
        T = 100000
        for age_h, want in ((0, 1.0), (1, 0.5), (2, 0.25)):
            agg = hotspot.aggregate([self.st(T - age_h * 3600)], T, window_h=3, half_life_h=1)
            self.assertAlmostEqual(agg[("0", "6,5")]["score"], want, delta=1e-9)
        agg = hotspot.aggregate([self.st(T - 1800), self.st(T)], T, window_h=1, half_life_h=0.5)
        self.assertAlmostEqual(agg[("0", "6,5")]["score"], 0.5 + 1.0, delta=1e-9)
        self.assertEqual((agg[("0", "6,5")]["stalls"], agg[("0", "6,5")]["robots"]), (2, 1))

    def test_window_and_no_look_ahead(self):
        # inject: use end <= at_ts + window (look-ahead) or an inclusive window start
        T = 100000
        agg = hotspot.aggregate([self.st(T - 3600), self.st(T - 3599), self.st(T + 1)], T, window_h=1)
        self.assertEqual(agg[("0", "6,5")]["stalls"], 1)  # end == T - window is outside, end > T is excluded

    def test_exclusions(self):
        # inject: count faulted-episode stalls, or ignore exclude_occupied
        T = 1000
        ok, fe, occ = self.st(900), dict(self.st(901), faulted_episode=True), dict(self.st(902), next_occupied=True)
        self.assertEqual(hotspot.aggregate([ok, fe, occ], T)[("0", "6,5")]["stalls"], 1)
        self.assertEqual(hotspot.aggregate([ok, fe, occ], T, exclude_occupied=False)[("0", "6,5")]["stalls"], 2)


def checkpoint_at(store, ts, path="p", run="r", zones=("0", "1")):
    """Establish the stream end for tests of the grading rule only: one ingest checkpoint row carrying
    last_message_ts_by_zone (`ts` for every zone in `zones`, or a {zone: ts} dict). The tests of what moves stream_end
    go through the real ingest path (TestStreamEndThroughIngest), not this."""
    by_zone = ts if isinstance(ts, dict) else {z: ts for z in zones}
    store.upsert("ingest_checkpoints", ("run", "path"), [dict(
        run=run, path=path, offset_uncompressed=0, last_header_ids="{}", ledger_counters=None, cp_seq=1,
        updated_at=0.0, last_message_ts_by_zone=json.dumps(by_zone))])


def stall_msgs(serial, zone_cells, first_hid=0, t0=0):
    """Messages of one robot holding one stall pair per (ts, cell) in zone_cells (cell = the cell in front, RIGHT)."""
    out = []
    for ts, (cx, cy) in zone_cells:
        hid = ts // 5
        out.append(msg(hid, ts, serial=serial, x=cx - 1, y=cy, nxt=(cx, cy)))
        out.append(msg(hid + 1, ts + 5, serial=serial, x=cx - 1, y=cy, nxt=(cx, cy)))
    return out


def filler(serial, upto, skip=()):
    """No-order messages on a fixed cell for every step < upto not in `skip` (a header gap breaks nothing: no order)."""
    return [msg(t // 5, t, serial=serial, order="", x=1, y=1, nxt=None) for t in range(0, upto, 5) if t not in skip]


def scenario():
    """Zone 0: cell (6,5) stalls at 100, 200, 1500, 2500; cell (7,5) at 300. Zone 1: cell (9,9) at 400. Stream 0..3000."""
    s0 = [(100, (6, 5)), (200, (6, 5)), (300, (7, 5)), (1500, (6, 5)), (2500, (6, 5))]
    skip = {t + d for t, _ in s0 for d in (0, 5)}
    ms = stall_msgs("Z0-01", s0) + filler("Z0-01", 3005, skip)
    ms += stall_msgs("Z1-01", [(400, (9, 9))]) + filler("Z1-01", 3005, {400, 405})
    return ms


class TestCostMap(unittest.TestCase):
    def build(self, store=None, **kw):
        store = store or MemoryStore()
        doc = costmap.build_costmap(scenario(), store, "r", **kw)
        return store, doc

    def test_max_cost_one_per_zone_independently(self):
        # inject: normalise by the global max instead of the zone's max
        _, doc = self.build()
        z0, z1 = doc["zones"]["0"], doc["zones"]["1"]
        self.assertEqual(max(z1.values()), 1.0)  # zone 1 has one weak cell and is still scaled to 1
        self.assertEqual(max(z0.values()), 1.0)
        self.assertEqual(set(z0), {"6,5", "7,5"})
        self.assertEqual(doc["zones"]["1"], {"9,9": 1.0})
        self.assertEqual(sorted(doc), sorted(["schema_version", "run", "generated_at", "window_hours", "half_life_h",
                                              "min_stalls", "exclude_occupied", "zones"]))
        self.assertEqual((doc["schema_version"], doc["generated_at"], doc["min_stalls"]),
                         ("fleet-costmap/1", "1970-01-01T00:50:00Z", 1))

    def test_min_stalls(self):
        # inject: filter on score instead of the stall count, or keep sub-threshold cells at their cost
        _, doc = self.build(window_h=2, min_stalls=2)
        self.assertEqual(set(doc["zones"]["0"]), {"6,5"})  # (7,5) has 1 stall
        self.assertEqual(doc["zones"]["0"]["6,5"], 1.0)
        self.assertEqual(doc["zones"]["1"], {})  # nothing reaches 2: zone present, no cells

    def test_publish_rows_in_store(self):
        # inject: write only the last publish to the costmap table
        st, doc = self.build(publish_every=1000)
        times = sorted({r["published_at"] for r in st.select("costmap")})
        self.assertEqual(times, [1000, 2000, 3000])
        last = [r for r in st.select("costmap") if r["published_at"] == 3000 and r["zone"] == "0"]
        self.assertEqual({r["cell"]: r["cost"] for r in last}, doc["zones"]["0"])
        self.assertEqual(len(st.select("stalls")), 6)

    def test_hotspot_forecast_decisions_dedup_on_publish_time(self):
        # inject: key on wall time, or write decisions without the publish time in the key
        self.assertIn("hotspot_forecast", decisions.KINDS)
        st, _ = self.build(publish_every=1000)
        rows = st.select("decisions")
        self.assertTrue(rows)
        n = len(rows)
        self.assertEqual(len({r["dedup_key"] for r in rows}), n)
        self.assertIn("hotspot_forecast:Z0:6,5:1970-01-01T00:16:40Z", {r["dedup_key"] for r in rows})
        self.build(st, publish_every=1000)  # same input again
        self.assertEqual(len(st.select("decisions")), n)
        self.build(st, publish_every=700)  # different publish times
        self.assertGreater(len(st.select("decisions")), n)

    def test_claim_fields(self):
        # inject: rank by cell string only, or divide by the window instead of the covered seconds
        st, _ = self.build(publish_every=1000)
        d = next(r for r in st.select("decisions") if r["dedup_key"] == "hotspot_forecast:Z0:6,5:1970-01-01T00:16:40Z")
        claim = json.loads(d["claim"])
        self.assertEqual(set(claim), {"expected_stalls_next_hour", "cost", "rank", "horizon_s", "window_hours", "top_k",
                                      "half_life_h", "min_stalls", "exclude_occupied"})
        self.assertEqual((d["claim_version"], claim["top_k"], claim["half_life_h"], claim["min_stalls"],
                          claim["exclude_occupied"]), (2, costmap.DEFAULT_TOP_K, 1.0, 1, True))
        # at P=1000: window stalls at 6,5 end at 105, 205 -> 2 over covered = min(3600, 1000 - 0) = 1000 s
        self.assertAlmostEqual(claim["expected_stalls_next_hour"], 2 * 3600 / 1000, delta=1e-9)
        self.assertEqual((claim["rank"], d["decided_at"], d["grade_after"], d["status"]), (1, 1000, 1000 + 3600, "open"))
        self.assertEqual(d["subject"], "Z0:6,5")


class TestGrading(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        costmap.build_costmap(scenario(), self.store, "r", publish_every=1000, horizon_s=2000)
        checkpoint_at(self.store, 3000)  # the scenario's stream ends at 3000
        self.id = decisions.decision_id("hotspot_forecast:Z0:6,5:1970-01-01T00:16:40Z")  # P = 1000
        self.truth = {"zones": {"0": {"floor_cells": {"6,5": 0.5}}, "1": {"floor_cells": {}}}}

    def forecast(self, did):
        return next(r for r in self.store.select("decisions") if r["id"] == did)

    def test_outcome_grade_values_and_open_below_min_horizon(self):
        # inject: count stalls with start <= P - 1 or end in the window, or grade at horizon < min
        res = forecast_grade.grade_outcomes(self.store, "r", min_horizon_s=600)
        d = self.forecast(self.id)
        # P=1000, stream end 3000 -> horizon 2000; stalls at 6,5 starting in [1000, 3000): 1500, 2500
        # the claim is rank 1 <= K: the decision follows the RANK grade (6,5 is still rank 1 at window_end 3000)
        self.assertEqual((d["status"], d["outcome"], d["error"], d["verdict"]), ("graded", 1, None, "ok"))
        expected = (2 * 3600 / 1000) * 2000 / 3600  # x = 2 window stalls over 1000 s covered
        self.assertTrue(res["open"] > 0)  # forecasts published at 3000 have horizon 0
        rows = {g["grade_source"]: g for g in self.store.select("forecast_grades", {"id": self.id})}
        self.assertEqual(set(rows), {"outcome", "outcome_count"})
        g = rows["outcome_count"]
        self.assertEqual((g["outcome"], g["horizon_s"], g["verdict"]), (2, 2000, "ok"))  # |2 - 4| = 2 <= 0.5 * 4
        self.assertAlmostEqual(g["error"], 2 - expected, delta=1e-9)
        self.assertAlmostEqual(g["expected"], expected, delta=1e-9)
        r = rows["outcome"]
        self.assertEqual((r["outcome"], r["expected"], r["error"], r["verdict"], r["horizon_s"], r["graded_at"],
                          r["window_end"]), (1, costmap.DEFAULT_TOP_K, None, "ok", 2000, 3000, 3000))
        late = [r for r in self.store.select("decisions") if r["decided_at"] == 3000]
        self.assertTrue(late and all(r["status"] == "open" for r in late))

    def test_min_horizon_boundary(self):
        # inject: compare with <= instead of <
        forecast_grade.grade_outcomes(self.store, "r", min_horizon_s=2001)
        self.assertEqual(self.forecast(self.id)["status"], "open")
        self.assertEqual(self.store.select("forecast_grades"), [])
        forecast_grade.grade_outcomes(self.store, "r", min_horizon_s=2000)  # horizon == min grades
        self.assertEqual(self.forecast(self.id)["status"], "graded")

    def test_verdict_tolerance(self):
        # inject: drop the max(expected, 1) floor or flip ok / off
        forecast_grade.grade_outcomes(self.store, "r", min_horizon_s=600, tolerance=0.4)
        (g,) = self.store.select("forecast_grades", {"id": self.id, "grade_source": "outcome_count"})
        self.assertEqual(g["verdict"], "off")  # 2 > 0.4 * 4
        self.assertEqual(self.forecast(self.id)["verdict"], "ok")  # the stamp is the rank verdict, not the tolerance one

    def test_occupied_stalls_not_counted_by_default(self):
        # inject: grade without the cost map's filter
        stalls = self.store.select("stalls")
        for s in stalls:
            if s["zone"] == "0" and s["start"] == 1500:
                s["next_occupied"] = True
        self.store.upsert("stalls", ("run", "zone", "robot", "start"), stalls)
        forecast_grade.grade_outcomes(self.store, "r", min_horizon_s=600)
        (g,) = self.store.select("forecast_grades", {"id": self.id, "grade_source": "outcome_count"})
        self.assertEqual(g["outcome"], 1)

    SNAP = ("decisions", "forecast_grades", "decision_grades")

    def snap(self):
        return {t: self.store.select(t) for t in self.SNAP}

    def test_truth_grading_separate_from_outcome(self):
        # inject: stamp the decision from truth grading, key forecast_grades on id alone, or upsert decision_grades
        forecast_grade.grade_outcomes(self.store, "r", min_horizon_s=600)
        before = self.snap()
        grade.grade_truth(self.store, "r", self.truth)
        rows = self.store.select("forecast_grades", {"id": self.id})
        self.assertEqual(sorted((r["grade_source"], r["verdict"]) for r in rows), [("outcome", "ok"), ("outcome_count", "ok"),
                                                                               ("truth", "hit")])
        other = decisions.decision_id("hotspot_forecast:Z0:7,5:1970-01-01T00:16:40Z")
        self.assertEqual([r["verdict"] for r in self.store.select("forecast_grades", {"id": other})
                          if r["grade_source"] == "truth"], ["false_alarm"])
        after = self.snap()
        self.assertEqual(after["decisions"], before["decisions"])  # status / outcome / verdict untouched
        self.assertEqual(after["decision_grades"], before["decision_grades"])
        self.assertEqual([r for r in after["forecast_grades"] if r["grade_source"] == "outcome"],
                         [r for r in before["forecast_grades"] if r["grade_source"] == "outcome"])
        grade.grade_truth(self.store, "r", self.truth)  # idempotent
        forecast_grade.grade_outcomes(self.store, "r", min_horizon_s=600)
        self.assertEqual(after, self.snap())

    def test_truth_only_leaves_decisions_open(self):
        # inject: truth grading calls stamp_grade or writes decision_grades
        before = self.snap()
        grade.grade_truth(self.store, "r", self.truth)
        after = self.snap()
        self.assertEqual(after["decisions"], before["decisions"])
        self.assertEqual(after["decision_grades"], before["decision_grades"])
        self.assertTrue(all(r["status"] == "open" for r in after["decisions"]))
        self.assertTrue(all(r["grade_source"] == "truth" for r in after["forecast_grades"]))
        self.assertEqual(len(after["forecast_grades"]), len(after["decisions"]))

    def test_truth_grading_of_a_zone_absent_from_truth_raises(self):
        # inject: treat a zone missing from truth.json as having no floor cells (silent false_alarm)
        before = self.snap()
        with self.assertRaises(ValueError):
            grade.grade_truth(self.store, "r", {"zones": {"0": {"floor_cells": {"6,5": 0.5}}}})  # zone 1 has forecasts
        self.assertEqual(self.snap(), before)  # nothing half-written

    def test_outcome_row_is_written_before_the_decision_is_stamped(self):
        # inject: stamp first and write the row after (a crash between leaves a graded decision with no row)
        real = decisions.stamp_grade
        seen = []

        def crash(store, did, *a, **k):
            seen.append((did, store.exists("forecast_grades", id=did, grade_source="outcome")
                         and store.exists("forecast_grades", id=did, grade_source="outcome_count")))
            raise RuntimeError("crash between the row and the stamp")

        with mock.patch.object(decisions, "stamp_grade", crash):
            with self.assertRaises(RuntimeError):
                forecast_grade.grade_outcomes(self.store, "r", min_horizon_s=600)
        self.assertEqual(seen[0][1], True)  # the row existed when the stamp was attempted
        self.assertEqual(self.forecast(seen[0][0])["status"], "open")
        self.assertEqual(len(self.store.select("forecast_grades")), 2)  # outcome_count + outcome of the one decision
        self.assertIs(decisions.stamp_grade, real)
        res = forecast_grade.grade_outcomes(self.store, "r", min_horizon_s=600)  # the re-run backfills the stamp
        self.assertGreater(res["graded"], 0)
        self.assertTrue(all(d["status"] == "graded" for d in self.store.select("decisions") if d["decided_at"] <= 1000))
        self.assertEqual(len(self.store.select("forecast_grades", {"grade_source": "outcome"})), res["graded"])
        self.assertEqual(len({r["id"] for r in self.store.select("forecast_grades")}), res["graded"])

    def test_grade_run_leaves_hotspot_forecast_alone(self):
        # inject: add a hotspot_forecast entry to GRADERS-less dispatch (KeyError) or stamp forecasts in grade_run
        before = self.snap()
        counts = decision_grade.grade_run(self.store, "r", 10 ** 9)
        self.assertEqual((counts["stamped"], counts["skipped_kind"]), (0, len(before["decisions"])))
        self.assertEqual(self.snap(), before)

    def test_cli_once_outcome_and_truth_through_a_jsonl_store(self):
        # inject: --once skips forecast grading, or --truth is ignored
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            st = JsonlStore(d / "st")
            costmap.build_costmap(scenario(), st, "r", publish_every=1000, horizon_s=2000)
            checkpoint_at(st, 3000)
            st.close()
            (d / "truth.json").write_text(json.dumps(self.truth))
            spec = f"jsonl:{d / 'st'}"
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(grade.main(["--run", "r", "--store", spec, "--once"]), 0)
            self.assertIn("forecasts", out.getvalue())
            st = JsonlStore(d / "st")
            sources = {r["grade_source"] for r in st.select("forecast_grades")}
            st.close()
            self.assertEqual(sources, {"outcome", "outcome_count"})  # no --truth, no truth rows
            with contextlib.redirect_stdout(io.StringIO()):
                grade.main(["--run", "r", "--store", spec, "--once", "--truth", str(d / "truth.json")])
                grade.main(["--run", "r", "--store", spec, "--once", "--truth", str(d / "truth.json")])
            st = JsonlStore(d / "st")
            rows = st.select("forecast_grades")
            by = {}
            for r in rows:
                by.setdefault(r["grade_source"], set()).add(r["id"])
            self.assertEqual(len(rows), len(by["outcome"]) + len(by["outcome_count"]) + len(by["truth"]))  # no dups
            self.assertEqual(by["outcome"], by["outcome_count"])  # every forecast here is rank-graded
            self.assertTrue(by["outcome"] <= by["truth"] and self.id in by["outcome"])
            self.assertEqual(st.select("decision_grades"), [])
            st.close()
            bad = dict(self.truth, zones={"0": self.truth["zones"]["0"]})
            (d / "bad.json").write_text(json.dumps(bad))
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                grade.main(["--run", "r", "--store", spec, "--once", "--truth", str(d / "bad.json")])

    def test_truth_json_read_only_on_the_truth_path(self):
        # inject: open truth.json whenever the grading path runs
        opened = []
        real = builtins.open

        def spy(file, *a, **k):
            opened.append(str(file))
            return real(file, *a, **k)

        with tempfile.TemporaryDirectory() as d:
            st = JsonlStore(Path(d) / "st")
            costmap.build_costmap(scenario(), st, "r", publish_every=1000, horizon_s=2000)
            checkpoint_at(st, 3000)
            st.close()
            with mock.patch.object(builtins, "open", spy), contextlib.redirect_stdout(io.StringIO()):
                grade.main(["--run", "r", "--store", f"jsonl:{Path(d) / 'st'}", "--once"])
        self.assertEqual([p for p in opened if "truth" in p], [])
        src = (ROOT / "fleet" / "grade.py").read_text()
        self.assertEqual(len(re.findall(r"\bopen\(", src)), 1)


def stall_row(zone, cell, start, end, robot=None, **kw):
    row = dict(run="r", zone=zone, robot=robot or f"Z{zone}-{start}", cell=cell, attribution="next", start=start,
               end=end, n_msgs=2, seconds=end - start, next_occupied=False, in_episode=None, faulted_episode=False)
    row.update(kw)
    return row


def forecast_row(store, zone, cell, p, horizon, expected=1.0, **claim_extra):
    """A hand-built hotspot_forecast. Default claim is the v1 shape (no top_k); pass rank=, top_k=, half_life_h=,
    min_stalls=, exclude_occupied=, window_hours= for a v2 claim (see v2_forecast)."""
    claim = dict(expected_stalls_next_hour=expected, cost=1.0, rank=1, horizon_s=horizon, window_hours=1.0)
    claim.update(claim_extra)
    did, _ = decisions.record_decision(
        store, run="r", kind="hotspot_forecast", subject=f"Z{zone}:{cell}", start_iso=f"P{p}", decided_at=p,
        claim=claim,
        rationale="t", expected=expected, grade_after=p + horizon)
    return did


def v2_forecast(store, zone, cell, p, horizon, rank, top_k=2, window_hours=0.25, half_life_h=1.0, min_stalls=1,
                exclude_occupied=True):
    return forecast_row(store, zone, cell, p, horizon, rank=rank, top_k=top_k, window_hours=window_hours,
                        half_life_h=half_life_h, min_stalls=min_stalls, exclude_occupied=exclude_occupied)


class TestRankGrade(unittest.TestCase):
    """The rank grade: a claim of rank k <= K is graded on the cell's rank in the zone's map recomputed at P + H."""

    P, H, K = 1000, 1000, 2

    def put(self, store, zone, cell, starts, occupied=False, end_of=lambda st: 1900):
        store.upsert("stalls", ("run", "zone", "robot", "start"),
                     [stall_row(zone, cell, st, end_of(st), next_occupied=occupied) for st in starts])

    def base_store(self):
        """Zone 0 at window_end 2000 (window 900 s): ranks a=1 (3 stalls), b=2 (2), c=3 (1); d only stalled long ago."""
        store = MemoryStore()
        self.put(store, "0", "1,1", (1800, 1801, 1802))
        self.put(store, "0", "2,1", (1810, 1811))
        self.put(store, "0", "3,1", (1820,))
        self.put(store, "0", "4,1", (100,), end_of=lambda st: 500)
        checkpoint_at(store, 2000, zones=("0",))
        return store

    def rows(self, store, did):
        return {g["grade_source"]: g for g in store.select("forecast_grades", {"id": did})}

    def dec(self, store, did):
        return next(r for r in store.select("decisions") if r["id"] == did)

    def test_rank_ok_at_exactly_k_off_below_k_and_none_when_the_cell_vanishes(self):
        # inject: m1 r <= K -> r < K (b sits at exactly rank K); m3 take the rank from the claim instead of recomputing
        #         (c claims rank 2 but is rank 3 at the end); a cell absent from the map must give outcome None
        store = self.base_store()
        ids = {c: v2_forecast(store, "0", c, self.P, self.H, rank=k)
               for c, k in (("1,1", 1), ("2,1", 2), ("3,1", 2), ("4,1", 1))}
        res = forecast_grade.grade_outcomes(store, "r", min_horizon_s=600)
        self.assertEqual(res, dict(graded=4, open=0, rank_graded=4, unranked=0))
        want = {"1,1": (1, "ok"), "2,1": (2, "ok"), "3,1": (3, "off"), "4,1": (None, "off")}
        for cell, (rank, verdict) in want.items():
            r = self.rows(store, ids[cell])["outcome"]
            self.assertEqual((r["outcome"], r["expected"], r["error"], r["verdict"], r["horizon_s"], r["graded_at"],
                              r["window_end"]), (rank, self.K, None, verdict, self.H, 2000, self.P + self.H), cell)
            d = self.dec(store, ids[cell])
            self.assertEqual((d["status"], d["outcome"], d["error"], d["verdict"], d["graded_at"]),
                             ("graded", rank, None, verdict, 2000), cell)

    def test_count_grade_is_still_written_for_every_rank_graded_forecast(self):
        # inject: m7 count grade written under "outcome" again (or not written for rank-graded forecasts)
        store = self.base_store()
        did = v2_forecast(store, "0", "1,1", self.P, self.H, rank=1)
        forecast_grade.grade_outcomes(store, "r", min_horizon_s=600)
        rows = self.rows(store, did)
        self.assertEqual(set(rows), {"outcome", "outcome_count"})
        c = rows["outcome_count"]
        # observed = stalls of 1,1 starting in [1000, 2000) = 3; expected = 1.0 / h * 1000 s
        self.assertEqual((c["outcome"], c["horizon_s"], c["graded_at"], c["window_end"]), (3, self.H, 2000, 2000))
        self.assertAlmostEqual(c["expected"], 1000 / 3600, delta=1e-9)
        self.assertAlmostEqual(c["error"], 3 - 1000 / 3600, delta=1e-9)
        self.assertEqual(c["verdict"], "off")  # |3 - 0.28| > 0.5 * max(0.28, 1)

    def test_claim_rank_above_k_is_unranked_terminally_and_has_no_outcome_row(self):
        # inject: m2 eligibility k <= K -> k < K does not matter here, but k > K must stay graded on truth only;
        #         m6 unranked decisions left open
        store = self.base_store()
        self.put(store, "0", "6,1", (1850,))
        did = v2_forecast(store, "0", "6,1", self.P, self.H, rank=3)  # 3 > K = 2
        res = forecast_grade.grade_outcomes(store, "r", min_horizon_s=600)
        self.assertEqual(res, dict(graded=1, open=0, rank_graded=0, unranked=1))
        self.assertEqual(set(self.rows(store, did)), {"outcome_count"})
        d = self.dec(store, did)
        c = self.rows(store, did)["outcome_count"]
        self.assertEqual((d["status"], d["verdict"], d["outcome"], d["graded_at"]), ("graded", "unranked", 1, 2000))
        self.assertAlmostEqual(d["error"], c["error"], delta=1e-9)
        again = forecast_grade.grade_outcomes(store, "r", min_horizon_s=600)  # terminal: nothing left to do
        self.assertEqual(again, dict(graded=0, open=0, rank_graded=0, unranked=0))

    def test_v1_claim_is_count_only_and_does_not_raise(self):
        # inject: read claim["top_k"] without a default (KeyError on old stores)
        store = self.base_store()
        did = forecast_row(store, "0", "1,1", self.P, self.H)  # v1: no top_k, no half_life_h
        res = forecast_grade.grade_outcomes(store, "r", min_horizon_s=600)
        self.assertEqual(res, dict(graded=1, open=0, rank_graded=0, unranked=1))
        self.assertEqual(set(self.rows(store, did)), {"outcome_count"})
        d = self.dec(store, did)
        self.assertEqual((d["status"], d["verdict"], d["outcome"]), ("graded", "unranked", 3))

    def test_unobserved_horizon_stays_open_with_no_rows(self):
        # inject: grade a v2 forecast before stream_end >= P + H
        store2 = MemoryStore()
        store2.upsert("stalls", ("run", "zone", "robot", "start"), [stall_row("0", "1,1", 1800, 1900)])
        checkpoint_at(store2, 1999, zones=("0",))
        did = v2_forecast(store2, "0", "1,1", self.P, self.H, rank=1)
        res = forecast_grade.grade_outcomes(store2, "r", min_horizon_s=600)
        self.assertEqual(res, dict(graded=0, open=1, rank_graded=0, unranked=0))
        self.assertEqual(store2.select("forecast_grades"), [])
        self.assertEqual(self.dec(store2, did)["status"], "open")

    def occupied_case(self, claim_excludes, grader_excludes):
        store = self.base_store()
        self.put(store, "0", "7,1", (1830, 1831, 1832, 1833), occupied=True)  # 4 stalls, all behind a robot
        did = v2_forecast(store, "0", "7,1", self.P, self.H, rank=1, exclude_occupied=claim_excludes)
        forecast_grade.grade_outcomes(store, "r", min_horizon_s=600, exclude_occupied=grader_excludes)
        return self.rows(store, did)["outcome"]

    def test_rank_uses_the_claims_exclude_occupied_not_the_graders(self):
        # inject: m4 the grader's exclude_occupied instead of the claim's
        r = self.occupied_case(claim_excludes=True, grader_excludes=False)  # claim drops them: 7,1 not in the map
        self.assertEqual((r["outcome"], r["verdict"]), (None, "off"))
        r = self.occupied_case(claim_excludes=False, grader_excludes=True)  # claim counts them: 4 stalls, rank 1
        self.assertEqual((r["outcome"], r["verdict"]), (1, "ok"))

    def test_rank_uses_the_claims_window_and_min_stalls(self):
        # inject: recompute with the default window / min_stalls instead of the claim's
        store = self.base_store()
        did = v2_forecast(store, "0", "2,1", self.P, self.H, rank=1, min_stalls=3)  # only 1,1 has 3 stalls
        forecast_grade.grade_outcomes(store, "r", min_horizon_s=600)
        self.assertEqual(self.rows(store, did)["outcome"]["outcome"], None)
        store = self.base_store()
        did = v2_forecast(store, "0", "4,1", self.P, self.H, rank=1, window_hours=1.0)  # the 1 h window reaches 100
        forecast_grade.grade_outcomes(store, "r", min_horizon_s=600)
        self.assertEqual(self.rows(store, did)["outcome"]["outcome"], 4)

    def test_ties_in_rounded_cost_break_on_the_cell_string_like_costmap(self):
        # inject: m5 raw-score order instead of rounded cost then cell
        store = MemoryStore()
        # 2,1 has the (microscopically) higher raw score, but both round to cost 1.0: "10,1" < "2,1" wins rank 1
        self.put(store, "0", "2,1", (1800,), end_of=lambda st: 1900.0)
        self.put(store, "0", "10,1", (1801,), end_of=lambda st: 1899.999)
        checkpoint_at(store, 2000, zones=("0",))
        did = v2_forecast(store, "0", "2,1", self.P, self.H, rank=1, top_k=1)
        forecast_grade.grade_outcomes(store, "r", min_horizon_s=600)
        r = self.rows(store, did)["outcome"]
        self.assertEqual((r["outcome"], r["expected"], r["verdict"]), (2, 1, "off"))
        maps = hotspot.cost_zones(store.select("stalls"), 2000, 0.25, 1.0, 1, True)
        self.assertEqual({v["cost"] for v in maps["0"].values()}, {1.0})
        self.assertEqual([c for c, _ in hotspot.rank_cells(maps["0"])], ["10,1", "2,1"])

    def test_costmap_and_grader_share_one_ranking_function(self):
        # inject: a second copy of cost_zones / the ranking in costmap.py
        self.assertIs(costmap.cost_zones, hotspot.cost_zones)
        self.assertIn("hotspot.rank_cells", (ROOT / "fleet" / "costmap.py").read_text())

    def test_rank_is_per_zone(self):
        # inject: rank across zones (one map for all cells)
        store = self.base_store()
        self.put(store, "1", "1,1", (1800,))
        checkpoint_at(store, 2000, zones=("0", "1"))
        did = v2_forecast(store, "1", "1,1", self.P, self.H, rank=1)
        forecast_grade.grade_outcomes(store, "r", min_horizon_s=600)
        self.assertEqual(self.rows(store, did)["outcome"]["outcome"], 1)  # zone 1's only cell, not behind zone 0's 3


class TestClaimV2FromCostmap(unittest.TestCase):
    def test_top_k_flag_and_claim_values_reach_the_decisions(self):
        # inject: --top-k ignored (claim keeps the default), or the map parameters left out of the claim
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            st = JsonlStore(d / "st")
            costmap.build_costmap(scenario(), st, "r", window_h=2, half_life_h=0.5, min_stalls=1, publish_every=1000,
                                  exclude_occupied=False, top_k=7)
            claims = [json.loads(r["claim"]) for r in st.select("decisions")]
            st.close()
        self.assertTrue(claims)
        for c in claims:
            self.assertEqual((c["top_k"], c["half_life_h"], c["min_stalls"], c["exclude_occupied"], c["window_hours"]),
                             (7, 0.5, 1, False, 2))

    def test_cli_top_k_default_and_validation(self):
        # inject: --top-k 0 accepted
        self.assertEqual(costmap.build_parser().parse_args(["--glob", "x"]).top_k, 20)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            costmap.main(["--glob", "x", "--top-k", "0"])


class TestOutcomeWindow(unittest.TestCase):
    """Outcome grading on a fully observed window [P, P + H): only the stalls' start decides, both edges hold."""

    P, H = 1000, 1000

    def test_boundary_stalls_by_start_not_end(self):
        # inject: m1 st from the stall end; m2 p <= st -> p < st; m3 st < p + H -> st <= p + H; m4 end >= P+H -> >
        store = MemoryStore()
        cases = {"1,1": (999, 1010, 0),     # starts before P, ends inside the window: not counted
                 "2,1": (1000, 1005, 1),    # starts at P: counted
                 "3,1": (1999, 2010, 1),    # starts at P + H - 1, ends after P + H: counted
                 "4,1": (2000, 2005, 0)}    # starts at P + H: not counted
        ids = {}
        for cell, (start, end, _) in cases.items():
            store.upsert("stalls", ("run", "zone", "robot", "start"), [stall_row("0", cell, start, end)])
            ids[cell] = forecast_row(store, "0", cell, self.P, self.H)
        checkpoint_at(store, self.P + self.H)  # data reaches exactly P + H: the window is closed
        res = forecast_grade.grade_outcomes(store, "r", min_horizon_s=600)
        self.assertEqual(res, dict(graded=4, open=0, rank_graded=0, unranked=4))  # hand-built v1 claims: count-only
        got = {c: next(r for r in store.select("decisions") if r["id"] == i)["outcome"] for c, i in ids.items()}
        self.assertEqual(got, {c: v[2] for c, v in cases.items()})
        rows = {r["id"]: r for r in store.select("forecast_grades")}
        self.assertTrue(all(r["horizon_s"] == self.H and r["graded_at"] == self.P + self.H for r in rows.values()))

    def test_window_stays_open_until_data_reaches_p_plus_h(self):
        # inject: m4 (end >= P+H -> >), or truncate the horizon to the data seen so far
        store = MemoryStore()
        store.upsert("ingest_runs", ("run",), [dict(run="r", emit_config=dict(t0="1970-01-01T00:00:00Z", steps=721))])
        store.upsert("stalls", ("run", "zone", "robot", "start"), [stall_row("0", "6,5", 600, 610)])
        did = forecast_row(store, "0", "6,5", 500, 3600)
        status = lambda: next(r for r in store.select("decisions") if r["id"] == did)["status"]  # noqa: E731
        for data_end in (1000, 1100, 4099):  # the planned end (3600) is never consulted
            checkpoint_at(store, data_end)
            self.assertEqual(forecast_grade.stream_end(store, "r", "0"), data_end)
            self.assertEqual(forecast_grade.grade_outcomes(store, "r", min_horizon_s=600),
                             dict(graded=0, open=1, rank_graded=0, unranked=0))
            self.assertEqual(status(), "open")
            self.assertEqual(store.select("forecast_grades"), [])
        checkpoint_at(store, 4100)
        self.assertEqual(forecast_grade.grade_outcomes(store, "r", min_horizon_s=600),
                         dict(graded=1, open=0, rank_graded=0, unranked=1))
        (g,) = store.select("forecast_grades")
        self.assertEqual((g["outcome"], g["horizon_s"], g["graded_at"], g["window_end"]), (1, 3600, 4100, 4100))
        self.assertEqual(status(), "graded")

    def test_stream_end_fallbacks(self):
        # inject: m4 (fall back to the planned end), or read stalls / transitions / costmap again
        store = MemoryStore()
        self.assertIsNone(forecast_grade.stream_end(store, "r", "0"))
        store.upsert("ingest_runs", ("run",), [dict(run="r", emit_config=dict(t0="1970-01-01T00:00:00Z", steps=721))])
        store.upsert("stalls", ("run", "zone", "robot", "start"), [stall_row("0", "6,5", 100, 150)])
        store.insert("transitions", [dict(run="r", zone="0", robot="Z0-01", ts=200, from_state="a", to_state="b",
                                          cell="1,1", order_id="o")])
        store.upsert("costmap", ("run", "published_at", "zone", "cell"),
                     [dict(run="r", zone="0", published_at=120, cell="1,1", cost=1.0, score=1.0, stalls=1)])
        self.assertIsNone(forecast_grade.stream_end(store, "r", "0"))  # planned end, costmap, stalls, transitions: none count
        store.upsert("ingest_checkpoints", ("run", "path"), [dict(run="r", path="a", cp_seq=1, last_message_ts_by_zone=None)])
        self.assertIsNone(forecast_grade.stream_end(store, "r", "0"))  # a checkpoint without a ts (None rows are ignored)
        checkpoint_at(store, {"5": 99}, path="z")
        self.assertIsNone(forecast_grade.stream_end(store, "r", "0"))  # another zone's end never counts
        checkpoint_at(store, 90, path="b")
        checkpoint_at(store, 70, path="c")
        self.assertEqual(forecast_grade.stream_end(store, "r", "0"), 90)  # max over the run's checkpoint rows
        self.assertFalse(hasattr(forecast_grade, "planned_end"))


def sline(serial, h, t, order="", x=1, y=1, nxt=None):
    """One zone-file line at event time BASE + t, with the fleet-state/2 fields: theta 0 (front cell = x + 1) and a
    nodeStates whose first node is `nxt`. Built on the S5B test line, so ingest and costmap read the same bytes."""
    obj = json.loads(line(serial, h, t // 5, order=order, x=x, y=y))
    obj["schema_version"] = "fleet-state/2"
    obj["agvPosition"]["theta"] = 0.0
    obj["nodeStates"] = [] if nxt is None else [{"nodeId": "n", "sequenceId": 0, "released": True,
                                                  "nodePosition": {"x": nxt[0], "y": nxt[1], "mapId": "m"}}]
    return (json.dumps(obj, separators=(",", ":")) + "\n").encode()


class TestStreamEndThroughIngest(unittest.TestCase):
    """stream_end = ts of the last message the ingester accepted, driven through the real file ingest path:
    gzip zone files -> Ingester -> store, then costmap.py's build_costmap on the same files, then the grader."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.glob = str(self.dir / "*.jsonl.gz")
        self.store = MemoryStore()
        self.hid = {}

    def msgs(self, serial, ts_list, stall_at=()):
        """Lines of one robot, every ts in ts_list; at the ts in stall_at it holds order o1 on (5,5) facing (6,5)."""
        out = []
        for t in ts_list:
            h = self.hid.get(serial, -1) + 1
            self.hid[serial] = h
            hold = t in stall_at
            out.append(sline(serial, h, t, order="o1" if hold else "", x=5 if hold else 1, y=5 if hold else 1,
                             nxt=(6, 5) if hold else None))
        return out

    def ingest(self):
        ing = Ingester(self.glob, "r", self.store, poll=0, ledger_interval=0.001, once=True, sleep=bounded_sleep())
        ing.run_loop()
        return ing

    def grade(self, min_horizon_s=600):
        return forecast_grade.grade_outcomes(self.store, "r", min_horizon_s=min_horizon_s)

    def costmap(self, lines=None, **kw):
        """costmap.py's build_costmap on the parsed zone lines (from the closed files, or the lines written so far)."""
        msgs = hotspot.read_messages(self.glob) if lines is None else [parse_line(ln)[0] for ln in lines]
        costmap.build_costmap(msgs, self.store, "r", **kw)

    def statuses(self):
        return {(d["decided_at"] - BASE, d["subject"]): d["status"] for d in self.store.select("decisions")
                if d["kind"] == "hotspot_forecast"}

    def test_duplicates_and_rejects_do_not_move_it_and_one_more_accepted_message_does(self):
        # inject: m5 _write_checkpoint stops writing last_message_ts; m6 _accepted_ts advanced on a parsed duplicate;
        #         m3 stream_end back to adc1efa's body (last costmap publish); m4 fall back to the planned end
        g = GrowingGz(self.dir / "zone0-000.jsonl.gz")
        # robot Z0-01 stalls once at 100; Z0-02 (never stalls) sends the last message of the data, at 1000
        a = self.msgs("Z0-01", range(0, 1001, 5), stall_at=(100, 105))
        b = self.msgs("Z0-02", range(0, 1001, 5))
        g.write(b"".join(a + b))
        first = a + b
        self.ingest()
        self.assertEqual(forecast_grade.stream_end(self.store, "r", "0"), BASE + 1000)
        self.costmap(first, publish_every=500, horizon_s=600)
        self.store.upsert("ingest_runs", ("run",), [dict(run="r", emit_config=dict(t0=iso_of(BASE), steps=721))])  # 3600
        self.assertEqual(self.statuses()[(500, "Z0:6,5")], "open")  # a forecast at P = 500 exists, P + H = 1100
        self.assertEqual(self.grade(), dict(graded=0, open=len(self.statuses()), rank_graded=0, unranked=0))
        # a duplicate header id with a LATER ts and a rejected line, then a resume that sees nothing else
        dup = sline("Z0-02", 5, 1500, order="", x=1, y=1)
        g.write(dup + b"this is not json\n")
        self.ingest()
        self.assertEqual(forecast_grade.stream_end(self.store, "r", "0"), BASE + 1000)  # unmoved, and not lost on resume
        self.assertEqual(self.grade(), dict(graded=0, open=len(self.statuses()), rank_graded=0, unranked=0))
        self.assertEqual(self.statuses()[(500, "Z0:6,5")], "open")
        # one more accepted message at 1100 from the robot that never stalls: P = 500 + H = 600 is now observed
        g.write(self.msgs("Z0-02", [1100])[0])
        self.ingest()
        self.assertEqual(forecast_grade.stream_end(self.store, "r", "0"), BASE + 1100)
        res = self.grade()
        st = self.statuses()
        self.assertEqual(st[(500, "Z0:6,5")], "graded")
        self.assertEqual(st[(1000, "Z0:6,5")], "open")  # P + H = 1600 is still ahead of the data
        self.assertEqual(res["graded"], sum(1 for (p, _), v in st.items() if p == 500 and v == "graded"))
        self.assertGreaterEqual(res["graded"], 1)

    def scenario_to(self, data_end):
        """Stall at 900 (cell 6,5), publishes every 500 s on a 720 s window: the stall is in the window of the publishes
        at 1000 and 1500 only, so the last NON-EMPTY publish is at 1500 and the later ones write no costmap rows."""
        g = GrowingGz(self.dir / "zone0-000.jsonl.gz")
        ts = range(0, data_end + 1, 5)
        g.close(b"".join(self.msgs("Z0-01", ts, stall_at=(900, 905))))
        self.ingest()
        self.costmap(window_h=0.2, publish_every=500, horizon_s=600)

    def test_empty_publishes_after_the_last_stall_do_not_hold_the_stream_end_back(self):
        # inject: m3 stream_end = last costmap.published_at with rows (adc1efa), which is 1500 here
        self.scenario_to(2000)
        rows = {r["published_at"] for r in self.store.select("costmap", {"run": "r"})}
        self.assertEqual(rows, {BASE + 1000, BASE + 1500})  # the publish at 2000 is empty
        self.assertEqual(forecast_grade.stream_end(self.store, "r", "0"), BASE + 2000)
        self.assertEqual(self.grade(), dict(graded=1, open=1, rank_graded=1, unranked=0))  # P = 1000 (window to 1600) graded; P = 1500 open
        st = self.statuses()
        self.assertEqual((st[(1000, "Z0:6,5")], st[(1500, "Z0:6,5")]), ("graded", "open"))

    def test_a_late_grade_keeps_graded_at_at_the_stream_end_and_window_end_at_p_plus_h(self):
        # inject: m1 graded_at = window_end on the forecast_grades row; m2 the same on the decision stamp
        self.scenario_to(1700)
        self.assertEqual(self.grade(), dict(graded=1, open=len(self.statuses()) - 1, rank_graded=1, unranked=0))
        (row,) = [r for r in self.store.select("forecast_grades") if r["grade_source"] == "outcome"]
        self.assertEqual((row["window_end"], row["graded_at"]), (BASE + 1600, BASE + 1700))
        d = next(r for r in self.store.select("decisions") if r["id"] == row["id"])
        self.assertEqual((d["status"], d["graded_at"]), ("graded", BASE + 1700))

    # ---- per-zone stream end: zone 0 to 3000, zone 1 to 1000, zone 2 with no messages
    PZ, PH = BASE + 1000, 600

    def zone_forecasts(self):
        return {z: forecast_row(self.store, z, "6,5", self.PZ, self.PH) for z in "012"}

    def decision(self, did):
        return next(r for r in self.store.select("decisions") if r["id"] == did)

    def test_each_zone_grades_on_its_own_end_and_a_late_zone_grades_at_its_own_ts(self):
        # inject: m7 gate on the run-wide max; m8 graded_at = run-wide max; m9 zone key = file path / partition;
        #         m10 _load_resume restores one scalar for all zones
        g0 = GrowingGz(self.dir / "zone0-000.jsonl.gz")
        g1 = GrowingGz(self.dir / "zone1-000.jsonl.gz")
        g0.write(b"".join(self.msgs("Z0-01", range(0, 3001, 5))))
        g1.write(b"".join(self.msgs("Z1-01", range(0, 1001, 5))))
        self.ingest()
        ids = self.zone_forecasts()
        self.assertEqual(forecast_grade.stream_end(self.store, "r", "0"), BASE + 3000)
        self.assertEqual(forecast_grade.stream_end(self.store, "r", "1"), BASE + 1000)
        self.assertIsNone(forecast_grade.stream_end(self.store, "r", "2"))
        self.assertEqual(self.grade(), dict(graded=1, open=2, rank_graded=0, unranked=1))
        self.assertEqual([self.decision(ids[z])["status"] for z in "012"], ["graded", "open", "open"])
        self.assertEqual(self.decision(ids["0"])["graded_at"], BASE + 3000)
        # one more accepted message of zone 1 at 1700: its window [1000, 1600) is observed, graded at ITS end
        g1.write(b"".join(self.msgs("Z1-01", [1700])))
        self.ingest()
        self.assertEqual(self.grade(), dict(graded=1, open=1, rank_graded=0, unranked=1))
        self.assertEqual([self.decision(ids[z])["status"] for z in "012"], ["graded", "graded", "open"])
        self.assertEqual(self.decision(ids["1"])["graded_at"], BASE + 1700)  # not 3000
        rows = {r["id"]: r for r in self.store.select("forecast_grades") if r["grade_source"] == "outcome_count"}
        self.assertEqual((rows[ids["1"]]["graded_at"], rows[ids["1"]]["window_end"]), (BASE + 1700, BASE + 1600))
        self.assertEqual((rows[ids["0"]]["graded_at"], rows[ids["0"]]["window_end"]), (BASE + 3000, BASE + 1600))
        # a fresh Ingester resuming on the same store restores the per-zone map (1 stays at 1700, not 3000)
        fresh = self.ingest()
        self.assertEqual(fresh._accepted_ts, {"0": BASE + 3000, "1": BASE + 1700})
        self.assertEqual(forecast_grade.stream_end(self.store, "r", "1"), BASE + 1700)
        self.assertEqual(forecast_grade.stream_end(self.store, "r", "0"), BASE + 3000)

    def test_resume_then_a_new_message_keeps_the_per_zone_map(self):
        # inject: m10 _load_resume restores one scalar (the max) for all zones
        g0 = GrowingGz(self.dir / "zone0-000.jsonl.gz")
        g1 = GrowingGz(self.dir / "zone1-000.jsonl.gz")
        g0.write(b"".join(self.msgs("Z0-01", range(0, 3001, 5))))
        g1.write(b"".join(self.msgs("Z1-01", range(0, 1001, 5))))
        self.ingest()
        g1.write(b"".join(self.msgs("Z1-01", [1005])))  # the resumed run writes a checkpoint carrying the restored map
        resumed = self.ingest()
        self.assertEqual(resumed._accepted_ts, {"0": BASE + 3000, "1": BASE + 1005})
        self.assertEqual(forecast_grade.stream_end(self.store, "r", "1"), BASE + 1005)

    def test_zone_is_the_serials_zone_not_the_file(self):
        # inject: m9 zone key = file path / partition (a Kafka partition or one file can mix zones)
        g = GrowingGz(self.dir / "mixed-000.jsonl.gz")
        g.write(b"".join(self.msgs("Z0-01", range(0, 3001, 5)) + self.msgs("Z1-01", range(0, 1001, 5))))
        self.ingest()
        self.assertEqual(forecast_grade.stream_end(self.store, "r", "0"), BASE + 3000)
        self.assertEqual(forecast_grade.stream_end(self.store, "r", "1"), BASE + 1000)
        ids = self.zone_forecasts()
        self.assertEqual(self.grade(), dict(graded=1, open=2, rank_graded=0, unranked=1))
        self.assertEqual(self.decision(ids["1"])["status"], "open")

    def test_stream_end_is_limited_to_the_run(self):
        checkpoint_at(self.store, {"0": 5000}, path="x", run="other")
        self.assertIsNone(forecast_grade.stream_end(self.store, "r", "0"))


class TestNewTablesSchema(unittest.TestCase):
    """stalls / costmap / forecast_grades against fleet/sql/schema.sql: engine, columns, keys."""

    def setUp(self):
        self.schema = schema_tables()
        self.rec = RecordingStore()
        costmap.build_costmap(scenario(), self.rec, "r", publish_every=1000)
        checkpoint_at(self.rec, 3000)
        forecast_grade.grade_outcomes(self.rec, "r", min_horizon_s=600)
        grade.grade_truth(self.rec, "r", {"zones": {"0": {"floor_cells": {"6,5": 0.5}}, "1": {"floor_cells": {}}}})

    def test_ddl_matches_what_the_writers_write(self):
        # inject: stalls ENGINE = MergeTree; drop forecast_grades.schema_version; rename costmap.cost; change an ORDER BY
        tables = ("stalls", "costmap", "forecast_grades")
        self.assertTrue(set(tables) <= set(self.rec.cols))
        for table in tables:
            ddl = self.schema[table]
            self.assertEqual((ddl["engine"], ddl["version"]), ("ReplacingMergeTree", "_ver"), table)
            for col in ("schema_version", "_ver", "_first"):
                self.assertIn(col, ddl["cols"], (table, col))
            self.assertIn("DEFAULT", ddl["cols"]["schema_version"], table)
            self.assertEqual(set(ddl["cols"]) - set(HIDDEN), self.rec.cols[table], table)  # DDL columns == row keys
            (key,) = self.rec.keys[table]
            self.assertEqual(ddl["order"], list(key), table)
            self.assertEqual(ddl["order"], list(chs.UPSERT_KEYS[table]), table)
        self.assertEqual(self.schema["forecast_grades"]["order"], ["id", "grade_source"])
        self.assertEqual(self.schema["costmap"]["order"], ["run", "published_at", "zone", "cell"])
        self.assertEqual(self.schema["stalls"]["order"], ["run", "zone", "robot", "start"])
        self.assertEqual(self.schema["decision_grades"]["order"], ["id"])
        self.assertNotIn("decision_grades", self.rec.cols)  # neither grader writes it


class TestRankGradingBlock(unittest.TestCase):
    def test_grading_counts_by_source_and_rank_grading_block(self):
        # inject: count unranked as rank-graded, or report one fixed K instead of the K values seen
        def g(i, src, verdict, expected=None):
            return dict(id=i, grade_source=src, verdict=verdict, expected=expected)

        grades = [g("a", "outcome", "ok", 20), g("b", "outcome", "off", 20), g("c", "outcome", "off", 5),
                  g("a", "outcome_count", "ok"), g("b", "outcome_count", "off"), g("c", "outcome_count", "off"),
                  g("d", "outcome_count", "off"), g("e", "outcome_count", "ok"),
                  g("a", "truth", "hit"), g("d", "truth", "false_alarm")]
        truth = {"zones": {"0": {"floor_cells": {"1,1": 0.5}}}}
        res = hotspot_score.score_run(truth, {"zones": {"0": {"1,1": 1.0}}}, [], grades)
        self.assertEqual(res["grading_counts"], {"outcome": {"ok": 1, "off": 2}, "outcome_count": {"ok": 2, "off": 3},
                                                 "truth": {"hit": 1, "false_alarm": 1}})
        self.assertEqual(res["rank_grading"], {"top_k": [5, 20], "rank_graded": 3, "unranked": 2})


class TestScore(unittest.TestCase):
    CELLS = [f"{i},{j}" for i in range(19) for j in range(20)]  # 380 candidates

    def floor(self, n=80):
        return {c: 0.3 + 0.4 * i / (n - 1) for i, c in enumerate(self.CELLS[:n])}

    def test_perfect_map(self):
        # inject: divide precision by the number of flagged cells, or drop the missing-slot misses
        floor = self.floor()
        r = hotspot_score.score_zone({c: 1.0 for c in floor}, floor, set())
        for k in ("20", "40", "80"):
            self.assertEqual(r["k"][k]["precision"], 1.0)
        self.assertAlmostEqual(r["k"]["120"]["precision"], 80 / 120, delta=1e-12)
        self.assertEqual(r["k"]["80"]["recall"], 1.0)
        self.assertEqual(r["n_flagged"], 80)
        self.assertEqual(r["zero_stall_share"], 1.0)

    def test_spearman_monotone_and_ties(self):
        # inject: ordinal ranks on ties or the wrong sign
        floor = self.floor()
        r = hotspot_score.score_zone({c: 0.01 + p for c, p in floor.items()}, floor, set(floor))
        self.assertAlmostEqual(r["spearman"], 1.0, delta=1e-12)
        self.assertEqual(r["zero_stall_share"], 0.0)
        self.assertAlmostEqual(hotspot_score.spearman([1, 2, 3, 4], [4, 3, 2, 1]), -1.0, delta=1e-12)
        self.assertIsNone(hotspot_score.spearman([1, 2], [1, 2]))
        self.assertIsNone(hotspot_score.spearman([1, 1, 1], [1, 2, 3]))
        self.assertEqual(hotspot_score._avg_ranks([5, 5, 7]), [1.5, 1.5, 3.0])

    def test_random_rankings_near_base_rate(self):
        # inject: rank floor cells first
        floor = self.floor()
        precs = []
        for seed in range(20):
            rng = random.Random(seed)
            cost = {c: rng.random() + 1e-9 for c in self.CELLS}
            precs.append(hotspot_score.score_zone(cost, floor, set())["k"]["80"]["precision"])
        mean = sum(precs) / len(precs)
        self.assertTrue(0.13 <= mean <= 0.29, mean)

    def test_main_writes_the_json(self):
        # inject: leave out a required key of the output
        floor = self.floor()
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            truth = dict(schema_version="fleet-truth/1", env_id="tarware-medium-8agvs-4pickers-globalobs-v1",
                         disturb_tag="x", disturb={}, steps=10, seed_base=0,
                         zones={"0": dict(seed=0, floor_cells=floor, floor_skips=[0] * 10, floor_skips_total=0)})
            (d / "truth.json").write_text(json.dumps(truth))
            (d / "costmap.json").write_text(json.dumps(dict(
                schema_version="fleet-costmap/1", run="r", generated_at="x", window_hours=1, half_life_h=1,
                min_stalls=1, exclude_occupied=True, zones={"0": {c: 1.0 for c in list(floor)[:10]}})))
            st = JsonlStore(d / "store")
            st.upsert("stalls", ("run", "zone", "robot", "start"), [
                dict(run="r", zone="0", robot="Z0-01", cell=list(floor)[0], attribution="next", start=1, end=2,
                     n_msgs=1, seconds=1, next_occupied=False, in_episode="traffic", faulted_episode=False)])
            st.upsert("forecast_grades", ("id", "grade_source"), [
                dict(id="a", run="r", grade_source="truth", verdict="hit", outcome=None, expected=None, error=None,
                     horizon_s=None, graded_at=None)])
            st.close()
            out = d / "o.json"
            with contextlib.redirect_stdout(io.StringIO()):
                code = hotspot_score.main(["--run-dir", str(d), "--store", f"jsonl:{d / 'store'}", "--tag", "t",
                                           "--out", str(out)])
            self.assertEqual(code, 0)
            res = json.loads(out.read_text())
        for key in ("zones", "mean", "grading_counts", "stall_in_episode", "platform", "config"):
            self.assertIn(key, res)
        self.assertEqual(res["zones"]["0"]["n_flagged"], 10)
        self.assertEqual(res["mean"]["k"]["20"]["precision"], 10 / 20)
        self.assertEqual(res["grading_counts"], {"truth": {"hit": 1}})
        self.assertEqual(res["rank_grading"], {"top_k": [], "rank_graded": 0, "unranked": 0})
        self.assertEqual(res["stall_in_episode"]["by_cause"], {"traffic": 1})
        self.assertNotIn("random_reference", res)  # out of scope: the base rate 80 / 380 lives in the PR text
        self.assertEqual(set(res["platform"]), {"platform", "python"})

    def test_main_on_an_empty_floor_prints_na(self):
        # inject: format recall None with :.3f again (TypeError)
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            truth = dict(schema_version="fleet-truth/1", env_id="x", disturb_tag="x", disturb={}, steps=10,
                         seed_base=0, zones={"0": dict(seed=0, floor_cells={}, floor_skips=[0] * 10,
                                                       floor_skips_total=0)})
            (d / "truth.json").write_text(json.dumps(truth))
            (d / "costmap.json").write_text(json.dumps(dict(
                schema_version="fleet-costmap/1", run="r", generated_at="x", window_hours=1, half_life_h=1,
                min_stalls=1, exclude_occupied=True, zones={"0": {"1,1": 1.0}})))
            st = JsonlStore(d / "store")
            st.close()
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = hotspot_score.main(["--run-dir", str(d), "--store", f"jsonl:{d / 'store'}", "--tag", "t",
                                           "--out", str(d / "o.json")])
            self.assertEqual(code, 0)
            self.assertIn("recall n/a", out.getvalue())
            self.assertIsNone(json.loads((d / "o.json").read_text())["mean"]["k"]["20"]["recall"])


class TestAnalystIsolation(unittest.TestCase):
    PATTERN = re.compile(r"floor_cells|floor_skip|floor_coin|applied_floor|truth")
    ALLOWED = ("NO field derived from the message's `custom` block (simulator ground truth)",  # parse.py docstring
               "The simulator ground-truth block is not in the store and is never read here.")  # grade.py docstring

    def analyst_files(self):
        fa = ROOT / "fleet" / "fleet_analyser"
        files = [p for p in sorted(fa.glob("*.py")) if p.name not in ("emitter.py", "emit_ledger.py", "sinks.py", "score.py")]
        files += [p for p in sorted((ROOT / "fleet").glob("*.py"))
                  # score.py, report.py, alert.py: S5C1 CLIs (score.py is the ground-truth scorer), not lane-added
                  # replay_export.py (S8-REPLAY): a viewer of a finished run that reads truth.json on purpose, to draw
                  # the hidden floor problems; nothing it reads feeds back into any analyst module
                  if p.name not in ("emit.py", "grade.py", "hotspot_score.py", "__init__.py", "score.py", "report.py",
                                    "alert.py", "replay_export.py")]
        return files

    def test_no_analyser_module_imports_replay_export(self):
        # replay_export.py is exempt from the truth scan above only because nothing in the analyser reads it back
        for p in sorted((ROOT / "fleet" / "fleet_analyser").glob("*.py")):
            self.assertNotRegex(p.read_text(), r"(?m)^\s*(from|import)\s+(\.*\s*)?replay_export\b|import\s+.*replay_export",
                                p.name)

    def test_no_ground_truth_in_analyst_code(self):
        # inject: mention truth.json / floor_cells in costmap.py, hotspot.py or any new analyst module
        names = {p.name for p in self.analyst_files()}
        self.assertTrue({"hotspot.py", "parse.py", "costmap.py", "ingest.py", "ledger.py", "detector.py",
                         "forecast_grade.py", "grade.py"} <= names)
        self.assertTrue({"emitter.py", "emit_ledger.py", "sinks.py", "hotspot_score.py"}.isdisjoint(names))
        hits = []
        for p in self.analyst_files():
            for n, line in enumerate(p.read_text().splitlines(), 1):
                if self.PATTERN.search(line) and not (p.name in ("parse.py", "grade.py") and any(a in line for a in self.ALLOWED)):
                    hits.append(f"{p.name}:{n}: {line.strip()}")
        self.assertEqual(hits, [])
        parse_hits = [ln for ln in (ROOT / "fleet" / "fleet_analyser" / "parse.py").read_text().splitlines()
                      if self.PATTERN.search(ln)]
        self.assertEqual(len(parse_hits), 1)  # the pre-existing docstring sentence, matched by content

    def test_message_fields_hold_no_floor_state(self):
        # inject: add a floor-derived field to parse.Message
        import dataclasses

        self.assertFalse([f.name for f in dataclasses.fields(Message) if "floor" in f.name or "truth" in f.name])


if __name__ == "__main__":
    unittest.main()

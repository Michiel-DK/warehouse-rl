"""S14D: the stop cause label is split by the robot's next route node. Hand-made batches go through the real Detector; each
case fails on master (no blocker_on_route key, no on-route blocker choice, no cause_label function). Messages every 10 s, so a
stopped robot is STUCK from its fourth message on (stuck_after 30 s)."""
import gzip
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "fleet", ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fleet_analyser import causes, ingest as ingest_mod, store as store_mod  # noqa: E402
from fleet_analyser.detector import Detector, cause_label  # noqa: E402
from fleet_analyser.parse import Message  # noqa: E402

BASE = 1767225600
A = "Z0-05"


def msg(k, serial, x, y, order="o1", faulted=False, nxt=None, reported=True):
    """One message at step k. nxt = (x, y) of nodeStates[0], None = nodeStates []; reported False = no nodeStates key."""
    return Message(serial=serial, zone="0", header_id=k, ts=BASE + 10 * k, order_id=order, x=x, y=y, driving=False,
                   faulted=faulted, loaded=False, raw_len=1, theta=0.0, next_x=None if nxt is None else nxt[0],
                   next_y=None if nxt is None else nxt[1], nodes_reported=reported)


def episode(others, a_at=(4, 4), nxt=(5, 4), reported=True, steps=6):
    """A stopped with an order at a_at for `steps` messages next to `others` = [(serial, x, y, faulted)], all stopped."""
    msgs = []
    for k in range(steps):
        msgs.append(msg(k, A, a_at[0], a_at[1], nxt=nxt, reported=reported))
        for s, x, y, f in others:
            msgs.append(msg(k, s, x, y, order="o2", faulted=f))
    det = Detector()
    ev = []
    for m in sorted(msgs, key=lambda m: (m.ts, m.serial)):
        ev.extend(det.feed(m))
    ev.extend(det.end_all())
    ops = [e for e in ev if e["kind"] == "episode_open" and e["robot"] == A]
    assert len(ops) == 1, ops
    return ops[0], [e for e in ev if e["kind"] == "episode_close" and e["robot"] == A]


class TestBlockerChoice(unittest.TestCase):
    def test_a_broken_robot_on_the_next_node_is_blocked_by(self):
        op, (cl,) = episode([("Z0-09", 5, 4, True)])
        self.assertEqual((op["cause"], op["blocker"], op["blocker_on_route"]), ("blocked_by_faulted", "Z0-09", True))
        self.assertEqual(cause_label(op["cause"], op["blocker_on_route"]), "Blocked by a broken robot")
        self.assertIs(cl["blocker_on_route"], True)  # the close row carries it too

    def test_b_broken_robot_next_to_but_not_on_the_route_is_stopped_next_to(self):
        op, (cl,) = episode([("Z0-09", 4, 5, True)])
        self.assertEqual((op["cause"], op["blocker"], op["blocker_on_route"]), ("blocked_by_faulted", "Z0-09", False))
        self.assertEqual(cause_label(op["cause"], op["blocker_on_route"]), "Stopped next to a broken robot")
        self.assertIs(cl["blocker_on_route"], False)

    def test_b2_same_x_other_y_is_not_on_route(self):
        # inject: compare only x with the next node
        op, _ = episode([("Z0-09", 5, 5, True)], a_at=(5, 4), nxt=(5, 3))
        self.assertEqual((op["cause"], op["blocker"], op["blocker_on_route"]), ("blocked_by_faulted", "Z0-09", False))
        self.assertEqual(cause_label(op["cause"], op["blocker_on_route"]), "Stopped next to a broken robot")

    def test_c_no_nodestates_key_is_none_and_stopped_next_to(self):
        op, (cl,) = episode([("Z0-09", 5, 4, True)], nxt=None, reported=False)
        self.assertEqual((op["cause"], op["blocker_on_route"]), ("blocked_by_faulted", None))
        self.assertIsNone(cl["blocker_on_route"])
        self.assertEqual(cause_label(op["cause"], op["blocker_on_route"]), "Stopped next to a broken robot")

    def test_c2_empty_nodestates_is_none(self):
        op, _ = episode([("Z0-09", 5, 4, True)], nxt=None, reported=True)
        self.assertEqual((op["cause"], op["blocker_on_route"]), ("blocked_by_faulted", None))

    def test_d_on_route_blocker_with_the_higher_serial_wins_and_supplies_faulted_s(self):
        # lowest serial Z0-01 is off route and faulted since step 0; Z0-09 is on route and faulted only from step 2
        msgs = []
        for k in range(6):
            msgs.append(msg(k, A, 4, 4, nxt=(5, 4)))
            msgs.append(msg(k, "Z0-01", 4, 5, order="o2", faulted=True))
            msgs.append(msg(k, "Z0-09", 5, 4, order="o2", faulted=k >= 2))
        det = Detector()
        ev = []
        for m in sorted(msgs, key=lambda m: (m.ts, m.serial)):
            ev.extend(det.feed(m))
        (op,) = [e for e in ev if e["kind"] == "episode_open" and e["robot"] == A]
        self.assertEqual((op["blocker"], op["blocker_on_route"]), ("Z0-09", True))
        self.assertEqual(op["t_entry"], BASE + 30)
        self.assertEqual(op["blocker_faulted_s"], 30 - 20)  # Z0-09 faulted from step 2, not Z0-01's 30 s

    def test_e_traffic_neighbour_on_the_next_node_or_beside_it(self):
        for pos, want_route, want_label in (((5, 4), True, "Traffic wait"), ((4, 5), False, "Stopped next to another robot")):
            msgs = []
            for k in range(6):
                msgs.append(msg(k, A, 4, 4, nxt=(5, 4)))
                msgs.append(msg(k, "Z0-09", pos[0], pos[1], order=""))  # idle: neither faulted nor stuck
            det = Detector()
            ev = []
            for m in sorted(msgs, key=lambda m: (m.ts, m.serial)):
                ev.extend(det.feed(m))
            (op,) = [e for e in ev if e["kind"] == "episode_open"]
            self.assertEqual((op["cause"], op["blocker"], op["blocker_on_route"]), ("traffic", None, want_route))
            self.assertEqual(cause_label(op["cause"], op["blocker_on_route"]), want_label)

    def test_e2_traffic_on_route_neighbour_need_not_be_the_lowest_serial(self):
        # inject: test only the first (lowest-serial) adjacent robot for the traffic route flag
        msgs = []
        for k in range(6):
            msgs.append(msg(k, A, 4, 4, nxt=(5, 4)))
            msgs.append(msg(k, "Z0-01", 4, 5, order=""))  # idle, adjacent, off route, lowest serial
            msgs.append(msg(k, "Z0-09", 5, 4, order=""))  # idle, on the next node
        det = Detector()
        ev = []
        for m in sorted(msgs, key=lambda m: (m.ts, m.serial)):
            ev.extend(det.feed(m))
        (op,) = [e for e in ev if e["kind"] == "episode_open"]
        self.assertEqual((op["cause"], op["blocker"], op["blocker_on_route"]), ("traffic", None, True))

    def test_e3_station_overrun_has_no_route_flag_even_with_a_robot_on_the_next_node(self):
        # inject: give the converted station stop False (or run _cause on it)
        msgs = []
        for k in range(10):
            msgs.append(msg(k, A, 4, 4, nxt=(5, 4)))
            msgs.append(msg(k, "Z0-09", 5, 4, order="o2", faulted=True))
        det = Detector(stations={(4, 4)}, station_radius=0, servicing_max_s=60)
        ev = []
        for m in sorted(msgs, key=lambda m: (m.ts, m.serial)):
            ev.extend(det.feed(m))
        ev.extend(det.end_all())
        eps = [e for e in ev if e["kind"].startswith("episode") and e["robot"] == A]
        self.assertTrue(eps)
        self.assertEqual({(e["cause"], e["blocker"], e["blocker_on_route"]) for e in eps}, {("station_overrun", None, None)})
        self.assertEqual(cause_label("station_overrun", eps[0]["blocker_on_route"]), "Station stop over time limit")

    def test_f_precedence_an_on_route_stuck_robot_never_beats_an_off_route_broken_one(self):
        # Z0-09 on route, stopped with an order (becomes STUCK); Z0-01 off route, faulted
        op, _ = episode([("Z0-09", 5, 4, False), ("Z0-01", 4, 5, True)])
        self.assertEqual((op["cause"], op["blocker"], op["blocker_on_route"]), ("blocked_by_faulted", "Z0-01", False))

    def test_g_stuck_neighbour_on_route(self):
        op, _ = episode([("Z0-09", 5, 4, False), ("Z0-01", 4, 3, False)])
        self.assertEqual((op["cause"], op["blocker"], op["blocker_on_route"]), ("blocked_by_stuck", "Z0-09", True))
        self.assertEqual(cause_label(op["cause"], True), "Blocked by a stuck robot")
        op, _ = episode([("Z0-09", 5, 4, False)], nxt=None, reported=False)  # inject: bool() the stuck flag
        self.assertEqual((op["cause"], op["blocker"], op["blocker_on_route"]), ("blocked_by_stuck", "Z0-09", None))
        self.assertEqual(cause_label(op["cause"], False), "Stopped next to a stuck robot")

    def test_h_faulted_self_and_unknown_have_no_route_flag(self):
        msgs = [msg(k, A, 4, 4, faulted=True, nxt=(5, 4)) for k in range(6)]
        det = Detector()
        ev = []
        for m in msgs:
            ev.extend(det.feed(m))
        (op,) = [e for e in ev if e["kind"] == "episode_open"]
        self.assertEqual((op["cause"], op["blocker_on_route"]), ("faulted_self", None))
        self.assertEqual(cause_label("faulted_self", None), "Robot error, cannot continue order")
        op, _ = episode([])
        self.assertEqual((op["cause"], op["blocker_on_route"]), ("unknown", None))
        self.assertEqual(cause_label("unknown", None), "Stopped, cause not identified")
        self.assertEqual(cause_label("station_overrun", None), "Station stop over time limit")


class TestTables(unittest.TestCase):
    def test_i_causes_table_splits_one_key_into_two_rows_by_route(self):
        # the False row comes first and ties on seconds: only the label tie-break puts "Blocked by" first
        eps = [dict(cause="blocked_by_stuck", duration_s=60, blocker_on_route=False),
               dict(cause="blocked_by_stuck", duration_s=100, blocker_on_route=True),
               dict(cause="blocked_by_stuck", duration_s=40, blocker_on_route=None),
               dict(cause="traffic", duration_s=10)]
        rows = causes.causes_table(eps)
        self.assertEqual([(r["cause"], r["cause_label"], r["episodes"], r["seconds"]) for r in rows], [
            ("blocked_by_stuck", "Blocked by a stuck robot", 1, 100),
            ("blocked_by_stuck", "Stopped next to a stuck robot", 2, 100),
            ("traffic", "Stopped next to another robot", 1, 10)])

    def test_j_ingest_writes_the_label_from_the_function(self):
        with tempfile.TemporaryDirectory() as d:
            lines = []
            for k in range(6):
                for serial, x, y, order, err in ((A, 4, 4, "o1", False), ("Z0-09", 5, 4, "o2", True)):
                    ts = "2026-01-01T00:00:%02dZ" % (10 * k) if k < 6 else None
                    obj = {"schema_version": "fleet-state/2", "headerId": k, "timestamp": ts, "manufacturer": "sim",
                           "serialNumber": serial, "orderId": order, "lastNodeId": "n", "driving": False, "paused": False,
                           "agvPosition": {"x": x, "y": y, "theta": 0.0, "mapId": "m"},
                           "errors": [{"errorType": "BREAKDOWN", "errorLevel": "FATAL"}] if err else [],
                           "loads": [], "nodeStates": [{"nodeId": "n", "nodePosition": {"x": 5, "y": 4}}] if serial == A else []}
                    lines.append((json.dumps(obj) + "\n").encode())
            with gzip.open(os.path.join(d, "zone0-000.jsonl.gz"), "wb") as f:
                for ln in lines:
                    f.write(ln)
            st = store_mod.MemoryStore()
            ingest_mod.Ingester(os.path.join(d, "*.jsonl.gz"), "r", st, once=True).run_loop()
        rows = [r for r in st.select("stuck_episodes", {"run": "r"}) if r["robot"] == A]
        self.assertTrue(rows)
        for r in rows:
            self.assertEqual((r["cause"], r["blocker_on_route"], r["cause_label"]),
                             ("blocked_by_faulted", True, "Blocked by a broken robot"))
        decs = [r for r in st.select("decisions", {"run": "r"}) if r["kind"] == "stuck_cause"]
        self.assertTrue(decs)
        for r in decs:  # the stuck_cause payload is unchanged: no blocker_on_route in it
            self.assertNotIn("blocker_on_route", json.dumps(r))


if __name__ == "__main__":
    unittest.main()

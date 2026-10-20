"""Tests for fleet_analyser.parse: field extraction, every reject reason, and that `custom` never reaches the Message.
Each case names its red demonstration in an `# inject:` comment."""
import dataclasses
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "fleet") not in sys.path:
    sys.path.insert(0, str(ROOT / "fleet"))

from fleet_analyser.parse import Message, parse_line, zone_of  # noqa: E402

GOOD = {"schema_version": "fleet-state/1", "headerId": 7, "timestamp": "2026-01-01T00:00:35Z", "manufacturer": "sim",
        "serialNumber": "Z3-04", "orderId": "Z3-4-o2", "lastNodeId": "5-6",
        "agvPosition": {"x": 5, "y": 6, "mapId": "m"}, "driving": False, "paused": False,
        "errors": [{"errorType": "BREAKDOWN", "errorLevel": "FATAL"}], "loads": [{"loadId": "shelf-1"}],
        "custom": {"stuck_count": 3, "carrying": True, "recovery_action": "abandon", "stuck_event": True,
                   "clash_event": False}}
MISSING = object()


def raw(**over):
    d = json.loads(json.dumps(GOOD))
    for k, v in over.items():
        if v is MISSING:
            d.pop(k)
        else:
            d[k] = v
    return (json.dumps(d) + "\n").encode()


class TestParse(unittest.TestCase):
    def test_good_line_exact_fields(self):
        # inject: derive faulted from `paused` instead of non-empty errors
        line = raw()
        msg, reason = parse_line(line)
        self.assertIsNone(reason)
        self.assertEqual(msg, Message(serial="Z3-04", zone="3", header_id=7, ts=1767225635, order_id="Z3-4-o2", x=5,
                                      y=6, driving=False, faulted=True, loaded=True, raw_len=len(line)))
        clean, _ = parse_line(raw(errors=[], loads=[], driving=True, orderId=""))
        self.assertFalse(clean.faulted)
        self.assertFalse(clean.loaded)
        self.assertTrue(clean.driving)
        self.assertEqual(clean.order_id, "")

    def test_identity_is_the_serial_not_the_order_id(self):
        # inject: set Message.serial from orderId
        msg, _ = parse_line(raw(serialNumber="Z3-04", orderId="Z9-9-o1"))
        self.assertEqual((msg.serial, msg.zone), ("Z3-04", "3"))

    def test_zone_of_serial(self):
        # inject: take the zone up to the last '-' instead of the first
        self.assertEqual(zone_of("Z12-03"), "12")
        self.assertEqual(zone_of("Zabc-1-2"), "abc")
        self.assertEqual(zone_of("robot-7"), "")
        self.assertEqual(zone_of("Z7"), "")

    def test_reject_reasons(self):
        # inject: accept a bool as int (headerId / coordinates)
        cases = [
            (b"{not json\n", "json"),
            (b"\n", "json"),
            (b"", "json"),
            (b"\xff\xfe\n", "json"),
            (b"[1, 2]\n", "type"),
            (b'"text"\n', "type"),
            (raw(headerId=MISSING), "missing:headerId"),
            (raw(serialNumber=MISSING), "missing:serialNumber"),
            (raw(agvPosition=MISSING), "missing:agvPosition"),
            (raw(agvPosition={"x": 1}), "missing:agvPosition.y"),
            (raw(timestamp="2026-01-01 00:00:35"), "timestamp"),
            (raw(timestamp="2026-13-45T00:00:35Z"), "timestamp"),
            (raw(timestamp=12345), "type"),
            (raw(headerId=-1), "type"),
            (raw(headerId=True), "type"),
            (raw(headerId="7"), "type"),
            (raw(serialNumber=""), "type"),
            (raw(orderId=None), "type"),
            (raw(agvPosition={"x": 1.5, "y": 2}), "type"),
            (raw(agvPosition={"x": True, "y": 2}), "type"),
            (raw(driving="no"), "type"),
            (raw(errors={}), "type"),
            (raw(loads="x"), "type"),
        ]
        for data, want in cases:
            with self.subTest(data=data[:60], want=want):
                msg, reason = parse_line(data)
                self.assertIsNone(msg)
                self.assertEqual(reason, want)

    def test_message_has_no_custom_derived_field(self):
        # inject: add a Message field copied from custom (e.g. stuck_count / carrying) or keep the custom dict on it
        names = {f.name for f in dataclasses.fields(Message)}
        self.assertEqual(names, {"serial", "zone", "header_id", "ts", "order_id", "x", "y", "driving", "faulted",
                                 "loaded", "raw_len", "theta", "next_x", "next_y",
                                 "nodes_reported", "paused"})
        msg, _ = parse_line(raw(custom={"stuck_count": 999, "sentinel": "SENTINEL-VALUE"}))
        values = [getattr(msg, n) for n in names]
        self.assertNotIn(999, [v for v in values if not isinstance(v, bool)])
        self.assertFalse(any("SENTINEL" in str(v) for v in values))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            msg.x = 1

    def test_custom_is_not_validated(self):
        # inject: reject a line with no custom block (parse would then read it)
        for custom in (MISSING, None, "garbage", [1]):
            msg, reason = parse_line(raw(custom=custom))
            self.assertIsNone(reason)
            self.assertEqual(msg.serial, "Z3-04")


class TestFaultedLevel(unittest.TestCase):
    """Message.faulted is true iff some errors entry is a dict whose errorLevel is CRITICAL or FATAL; nothing is rejected."""

    def faulted(self, errors):
        msg, reason = parse_line(raw(errors=errors))
        self.assertIsNone(reason)
        return msg.faulted

    def test_levels(self):
        # inject: go back to bool(errors)
        self.assertFalse(self.faulted([{"errorType": "X", "errorLevel": "WARNING"}]))
        self.assertFalse(self.faulted([{"errorType": "X", "errorLevel": "URGENT"}]))
        self.assertTrue(self.faulted([{"errorType": "X", "errorLevel": "CRITICAL"}]))
        self.assertTrue(self.faulted([{"errorType": "X", "errorLevel": "FATAL"}]))
        self.assertFalse(self.faulted([]))

    def test_missing_level_and_non_dict_entries_do_not_fault(self):
        # inject: treat a missing level or a string entry as faulted
        self.assertFalse(self.faulted([{"errorType": "X"}]))
        self.assertFalse(self.faulted([{"errorType": "X", "errorLevel": None}]))
        self.assertFalse(self.faulted([{"errorType": "X", "errorLevel": "fatal"}]))
        for entry in ("FATAL", 7, None, ["FATAL"]):
            self.assertFalse(self.faulted([entry]), entry)

    def test_any_entry_counts(self):
        # inject: look at the first entry only
        self.assertTrue(self.faulted([{"errorLevel": "WARNING"}, "junk", {"errorLevel": "FATAL"}]))

    def test_errors_not_a_list_is_still_rejected_as_type(self):
        # the type check is unchanged: errors must be a list
        for bad in (None, {}, "FATAL"):
            self.assertEqual(parse_line(raw(errors=bad)), (None, "type"))
        self.assertEqual(parse_line(raw(errors=MISSING)), (None, "missing:errors"))


class TestPaused(unittest.TestCase):
    def test_paused_only_when_exactly_true(self):
        # inject: bool(obj.get("paused")) (the string "false" or 1 would then pause)
        self.assertTrue(parse_line(raw(paused=True))[0].paused)
        self.assertFalse(parse_line(raw(paused=False))[0].paused)
        for odd in (MISSING, None, "true", 1, [True]):
            msg, reason = parse_line(raw(paused=odd))
            self.assertIsNone(reason)
            self.assertFalse(msg.paused, odd)

    def test_paused_is_the_last_field_with_default_false(self):
        # inject: put paused before nodes_reported or drop the default
        fields = dataclasses.fields(Message)
        self.assertEqual(fields[-1].name, "paused")
        self.assertIs(fields[-1].default, False)


if __name__ == "__main__":
    unittest.main()

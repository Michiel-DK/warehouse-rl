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
        # inject: derive faulted from `paused` instead of non-empty errors (or ts as the string, not epoch seconds)
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
        # inject: take the robot id from orderId ("Z9-9-o1" would give zone 9, the serial says Z3-04)
        msg, _ = parse_line(raw(serialNumber="Z3-04", orderId="Z9-9-o1"))
        self.assertEqual((msg.serial, msg.zone), ("Z3-04", "3"))

    def test_zone_of_serial(self):
        # inject: split the serial on the last '-' instead of the first, or default the zone to "0"
        self.assertEqual(zone_of("Z12-03"), "12")
        self.assertEqual(zone_of("Zabc-1-2"), "abc")
        self.assertEqual(zone_of("robot-7"), "")
        self.assertEqual(zone_of("Z7"), "")

    def test_reject_reasons(self):
        # inject: return reason "json" for every failure, or accept a bool headerId / a float coordinate
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
                                 "loaded", "raw_len"})
        msg, _ = parse_line(raw(custom={"stuck_count": 999, "sentinel": "SENTINEL-VALUE"}))
        values = [getattr(msg, n) for n in names]
        self.assertNotIn(999, [v for v in values if not isinstance(v, bool)])
        self.assertFalse(any("SENTINEL" in str(v) for v in values))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            msg.x = 1

    def test_custom_is_not_validated(self):
        # inject: reject lines whose custom is missing or malformed (parse would then read it)
        for custom in (MISSING, None, "garbage", [1]):
            msg, reason = parse_line(raw(custom=custom))
            self.assertIsNone(reason)
            self.assertEqual(msg.serial, "Z3-04")


if __name__ == "__main__":
    unittest.main()

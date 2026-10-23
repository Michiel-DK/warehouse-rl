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
            (b"[1, 2]\n", "type:line"),
            (b'"text"\n', "type:line"),
            (raw(headerId=MISSING), "missing:headerId"),
            (raw(serialNumber=MISSING), "missing:serialNumber"),
            (raw(agvPosition=MISSING), "missing:agvPosition"),
            (raw(agvPosition={"x": 1}), "missing:agvPosition.y"),
            (raw(timestamp="2026-01-01 00:00:35"), "timestamp:timestamp"),
            (raw(timestamp="2026-13-45T00:00:35Z"), "timestamp:timestamp"),
            (raw(timestamp=12345), "type:timestamp"),
            (raw(headerId=-1), "type:headerId"),
            (raw(headerId=True), "type:headerId"),
            (raw(headerId="7"), "type:headerId"),
            (raw(serialNumber=""), "type:serialNumber"),
            (raw(orderId=None), "type:orderId"),
            (raw(agvPosition={"x": 1.5, "y": 2}), "type:agvPosition.x"),
            (raw(agvPosition={"x": True, "y": 2}), "type:agvPosition.x"),
            (raw(driving="no"), "type:driving"),
            (raw(errors={}), "type:errors"),
            (raw(loads="x"), "type:loads"),
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
            self.assertEqual(parse_line(raw(errors=bad)), (None, "type:errors"))
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



# S17A: extended reasons. Frozen copy of the pre-S17A reject decision (reasons json / type / missing / timestamp only);
# the new reason must be the old one, or old + ":" + key.
def _old_reason(data):
    import re
    import time
    try:
        obj = json.loads(data)
    except ValueError:
        return "json"
    if not isinstance(obj, dict):
        return "type"
    for key in ("headerId", "timestamp", "serialNumber", "orderId", "agvPosition", "driving", "errors", "loads"):
        if key not in obj:
            return f"missing:{key}"
    pos = obj["agvPosition"]
    if not isinstance(pos, dict):
        return "type"
    for key in ("x", "y"):
        if key not in pos:
            return f"missing:agvPosition.{key}"
    isint = lambda v: isinstance(v, int) and not isinstance(v, bool)  # noqa: E731
    if not isint(obj["headerId"]) or obj["headerId"] < 0:
        return "type"
    ts = obj["timestamp"]
    if not isinstance(ts, str):
        return "type"
    if not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", ts):
        return "timestamp"
    try:
        time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return "timestamp"
    if not isinstance(obj["serialNumber"], str) or not obj["serialNumber"] or not isinstance(obj["orderId"], str):
        return "type"
    if not isint(pos["x"]) or not isint(pos["y"]):
        return "type"
    if not isinstance(obj["driving"], bool) or not isinstance(obj["errors"], list) or not isinstance(obj["loads"], list):
        return "type"
    return None


FIXTURE = Path(__file__).resolve().parent / "data" / "s17a_emit50" / "zone0-000.jsonl.gz"


def _fixture_lines():
    import gzip
    with gzip.open(FIXTURE, "rb") as f:
        return f.readlines()


def _mutated(path, value):
    obj = json.loads(_fixture_lines()[0])
    target = obj
    parts = path.split(".")
    for part in parts[:-1]:
        target = target[part]
    if value is MISSING:
        del target[parts[-1]]
    else:
        target[parts[-1]] = value
    return json.dumps(obj).encode() + b"\n"


class TestExtendedReasons(unittest.TestCase):
    def test_required_spec_is_the_contract_parse_line_iterates(self):
        from fleet_analyser.parse import OPTIONAL_FIELDS, REQUIRED_FIELDS
        self.assertEqual([(f.path, f.expected) for f in REQUIRED_FIELDS], [
            ("headerId", "int >= 0"), ("timestamp", "str YYYY-MM-DDTHH:MM:SSZ (UTC)"),
            ("serialNumber", "non-empty str"), ("orderId", "str"), ("agvPosition", "object"), ("driving", "bool"),
            ("errors", "list"), ("loads", "list"), ("agvPosition.x", "int"), ("agvPosition.y", "int")])
        self.assertEqual([p for p, _ in OPTIONAL_FIELDS], ["agvPosition.theta", "nodeStates", "paused"])

    def test_one_test_per_extended_reason(self):
        # inject: return plain "type" at any site, or swap two of the keys
        cases = [
            (b"[1]\n", "type:line"),
            (raw(agvPosition="here"), "type:agvPosition"),
            (raw(headerId=-3), "type:headerId"),
            (raw(timestamp=5), "type:timestamp"),
            (raw(timestamp="2026-01-01 00:00:00"), "timestamp:timestamp"),
            (raw(timestamp="2026-02-31T00:00:00Z"), "timestamp:timestamp"),
            (raw(serialNumber=7), "type:serialNumber"),
            (raw(orderId=7), "type:orderId"),
            (raw(agvPosition={"x": "1", "y": 2}), "type:agvPosition.x"),
            (raw(agvPosition={"x": 1, "y": None}), "type:agvPosition.y"),
            (raw(driving=1), "type:driving"),
            (raw(errors="e"), "type:errors"),
            (raw(loads=None), "type:loads"),
            (b"nope\n", "json"),
            (raw(loads=MISSING), "missing:loads"),
        ]
        for data, want in cases:
            with self.subTest(want=want):
                self.assertEqual(parse_line(data), (None, want))

    def test_combined_conditions_split_in_todays_order(self):
        # inject: check orderId before serialNumber, or y before x
        self.assertEqual(parse_line(raw(serialNumber="", orderId=3))[1], "type:serialNumber")
        self.assertEqual(parse_line(raw(agvPosition={"x": 1.5, "y": "q"}))[1], "type:agvPosition.x")
        self.assertEqual(parse_line(raw(driving="no", errors={}, loads=3))[1], "type:driving")
        self.assertEqual(parse_line(raw(errors={}, loads=3))[1], "type:errors")

    def test_every_mutation_keeps_accept_reject_and_old_reason(self):
        # inject: let a changed predicate accept or reject one more mutation; the (old, new) pairs are literal
        wrong = {"headerId": ("7", "type", "type:headerId"), "timestamp": (5, "type", "type:timestamp"),
                 "serialNumber": ("", "type", "type:serialNumber"), "orderId": (None, "type", "type:orderId"),
                 "agvPosition": ([], "type", "type:agvPosition"), "driving": ("no", "type", "type:driving"),
                 "errors": ({}, "type", "type:errors"), "loads": ("x", "type", "type:loads"),
                 "agvPosition.x": (1.5, "type", "type:agvPosition.x"),
                 "agvPosition.y": (True, "type", "type:agvPosition.y")}
        table = []
        for path in list(wrong):
            table.append((f"delete {path}", _mutated(path, MISSING), f"missing:{path}", f"missing:{path}"))
        for path, (value, old, new) in wrong.items():
            table.append((f"{path}={value!r}", _mutated(path, value), old, new))
        for ts in ("2026-01-01 00:00:35", "yesterday", "2026-13-45T00:00:35Z", "2026-01-01T00:00:35"):
            table.append((f"timestamp={ts}", _mutated("timestamp", ts), "timestamp", "timestamp:timestamp"))
        for name, data, old, new in table:
            with self.subTest(name):
                self.assertEqual(_old_reason(data), old)
                msg, reason = parse_line(data)
                self.assertIsNone(msg)
                self.assertEqual(reason, new)
        for data in _fixture_lines():
            self.assertIsNone(_old_reason(data))
            msg, reason = parse_line(data)
            self.assertIsNone(reason)
            obj = json.loads(data)
            self.assertEqual((msg.serial, msg.header_id, msg.order_id, msg.x, msg.y, msg.driving, msg.raw_len),
                             (obj["serialNumber"], obj["headerId"], obj["orderId"], obj["agvPosition"]["x"],
                              obj["agvPosition"]["y"], obj["driving"], len(data)))
        first = parse_line(_fixture_lines()[0])[0]
        self.assertEqual(first, Message(serial="Z0-01", zone="0", header_id=0, ts=1767225600, order_id="Z0-1-o1", x=19,
                                        y=2, driving=True, faulted=False, loaded=False, raw_len=572, theta=3.1416,
                                        next_x=18, next_y=2, nodes_reported=True, paused=False))

    def test_local_format_timestamp_through_parse_line(self):
        self.assertEqual(parse_line(_mutated("timestamp", "2026-01-01 00:00:00"))[1], "timestamp:timestamp")


if __name__ == "__main__":
    unittest.main()

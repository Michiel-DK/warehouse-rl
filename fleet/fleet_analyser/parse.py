"""Parse and validate one VDA 5050-shaped state line (docs/SCOPE.md "S5A" has the contract).

parse_line(raw_bytes) -> (Message | None, reject_reason | None). The Message carries only what detection needs. It has
NO field derived from the message's `custom` block (simulator ground truth) and `custom` is never copied: only a scorer
may read it. Robot identity is the serialNumber, never parsed out of orderId.
"""
import calendar
import json
import re
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, NamedTuple

_TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_FAULT_LEVELS = ("CRITICAL", "FATAL")
_ZONE_RE = re.compile(r"^Z([^-]+)-")


@dataclass(frozen=True, slots=True)
class Message:
    serial: str
    zone: str
    header_id: int
    ts: int  # epoch seconds
    order_id: str
    x: int
    y: int
    driving: bool
    faulted: bool  # some errors entry is a dict with errorLevel CRITICAL or FATAL (VDA 5050: WARNING/URGENT can continue)
    loaded: bool  # loads non-empty
    raw_len: int  # bytes of the raw line as read (including the newline when present)
    # fleet-state/2 fields, absent in /1 messages
    theta: float | None = None  # agvPosition.theta (radians)
    next_x: int | None = None  # first nodeStates entry's nodePosition; None when absent or []
    next_y: int | None = None
    nodes_reported: bool = False  # True iff the nodeStates KEY is present (even []): [] = "no route", absent = old schema
    paused: bool = False  # top-level `paused` is exactly true; absent or non-bool -> False


@lru_cache(maxsize=4096)
def _epoch(ts):
    return calendar.timegm(time.strptime(ts, _TS_FORMAT))


epoch_of = _epoch


def iso(epoch):
    return time.strftime(_TS_FORMAT, time.gmtime(epoch))


def zone_of(serial):
    m = _ZONE_RE.match(serial)
    return m.group(1) if m else ""


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _num(v):
    """A finite real number as float, else None (bool, str, null, nan, inf are all None)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v in (float("inf"), float("-inf")):
        return None
    try:
        return float(v)
    except (OverflowError, ValueError):  # an int literal too large for a float (1e400 written out in digits)
        return None


def _intval(v):
    """An int, or an integer-valued float (3.0) as int, else None."""
    if _is_int(v):
        return v
    f = _num(v)
    return int(f) if f is not None and f == int(f) else None


def _valid_timestamp(v):
    if not isinstance(v, str) or not _TS_RE.match(v):
        return False
    try:
        _epoch(v)
    except ValueError:
        return False
    return True


class Field(NamedTuple):
    path: str  # key path in the message, "agvPosition.x" for a nested key
    expected: str  # human-readable expected type
    valid: Callable  # the predicate parse_line applies to the value of this field


# The fleet-state contract as data: parse_line iterates it for its missing-key checks and applies each `valid` predicate;
# fleet/check_log.py imports it. Order = the order of the missing checks (top-level keys, then agvPosition's).
REQUIRED_FIELDS = (
    Field("headerId", "int >= 0", lambda v: _is_int(v) and v >= 0),
    Field("timestamp", "str YYYY-MM-DDTHH:MM:SSZ (UTC)", _valid_timestamp),
    Field("serialNumber", "non-empty str", lambda v: isinstance(v, str) and bool(v)),
    Field("orderId", "str", lambda v: isinstance(v, str)),
    Field("agvPosition", "object", lambda v: isinstance(v, dict)),
    Field("driving", "bool", lambda v: isinstance(v, bool)),
    Field("errors", "list", lambda v: isinstance(v, list)),
    Field("loads", "list", lambda v: isinstance(v, list)),
    Field("agvPosition.x", "int", _is_int),
    Field("agvPosition.y", "int", _is_int),
)
# fleet-state/2 fields: read when present and usable, never a reason to reject (they degrade to None / False).
OPTIONAL_FIELDS = (
    ("agvPosition.theta", "finite number (radians)"),
    ("nodeStates", "list of nodes; the first nodePosition is the next cell"),
    ("paused", "bool"),
)
FIELDS = {f.path: f for f in REQUIRED_FIELDS}
# The order in which parse_line checks values once every key is present (headerId, timestamp, serial, order, x, y, ...).
_VALUE_ORDER = tuple(FIELDS[k] for k in ("headerId", "timestamp", "serialNumber", "orderId", "agvPosition.x",
                                         "agvPosition.y", "driving", "errors", "loads"))
assert {f.path for f in _VALUE_ORDER} | {"agvPosition"} == set(FIELDS)


def field_value(obj, path):
    """(present, value) of a required field in a decoded JSON object; a nested key under a non-object is absent."""
    if not isinstance(obj, dict):
        return False, None
    if "." in path:
        head, tail = path.split(".", 1)
        obj = obj.get(head)
        if not isinstance(obj, dict):
            return False, None
        path = tail
    return (path in obj), obj.get(path)


def field_reason(path, value):
    """Reject reason parse_line gives when this present field's value is invalid: type:<path> or timestamp:timestamp."""
    if path == "timestamp" and isinstance(value, str):
        return "timestamp:timestamp"
    return f"type:{path}"


def check_field(obj, path):
    """(present, ok, value, reason) for one required field of a decoded JSON object. reason is None when ok;
    missing:<path> when absent. Same predicates parse_line applies."""
    present, value = field_value(obj, path)
    if not present:
        return False, False, None, f"missing:{path}"
    if FIELDS[path].valid(value):
        return True, True, value, None
    return True, False, value, field_reason(path, value)


def parse_line(raw):
    """Returns (Message, None) or (None, reason). reason: json | type:line | missing:<path> | type:<path> |
    timestamp:timestamp (see REQUIRED_FIELDS for the paths)."""
    try:
        obj = json.loads(raw)
    except ValueError:  # includes JSONDecodeError and UnicodeDecodeError; a blank line lands here too
        return None, "json"
    if not isinstance(obj, dict):
        return None, "type:line"
    for f in REQUIRED_FIELDS:
        if "." not in f.path and f.path not in obj:
            return None, f"missing:{f.path}"
    pos = obj["agvPosition"]
    if not FIELDS["agvPosition"].valid(pos):
        return None, "type:agvPosition"
    for f in REQUIRED_FIELDS:
        if "." in f.path and f.path.split(".", 1)[1] not in pos:
            return None, f"missing:{f.path}"
    for f in _VALUE_ORDER:
        value = pos[f.path.split(".", 1)[1]] if "." in f.path else obj[f.path]
        if not f.valid(value):
            return None, field_reason(f.path, value)
    header, ts, serial, order = obj["headerId"], obj["timestamp"], obj["serialNumber"], obj["orderId"]
    epoch = _epoch(ts)
    # fleet-state/2 fields degrade, never reject: anything master accepted is still accepted. Unusable theta -> None;
    # a present but unusable nodeStates -> next_x = next_y = None with nodes_reported True (no stall, no fallback).
    theta = _num(pos.get("theta"))
    next_x = next_y = None
    nodes_reported = "nodeStates" in obj
    if nodes_reported:
        nodes = obj["nodeStates"]
        first = nodes[0] if isinstance(nodes, list) and nodes else None
        np_ = first.get("nodePosition") if isinstance(first, dict) else None
        if isinstance(np_, dict):
            nx, ny = _intval(np_.get("x")), _intval(np_.get("y"))
            if nx is not None and ny is not None:
                next_x, next_y = nx, ny
    return Message(serial=serial, zone=zone_of(serial), header_id=header, ts=epoch, order_id=order, x=pos["x"],
                   y=pos["y"], driving=obj["driving"], faulted=any(isinstance(e, dict) and e.get("errorLevel") in _FAULT_LEVELS for e in obj["errors"]), loaded=bool(obj["loads"]),
                   raw_len=len(raw), theta=theta, next_x=next_x,
                   next_y=next_y, nodes_reported=nodes_reported, paused=obj.get("paused") is True), None

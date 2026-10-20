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


def parse_line(raw):
    """Returns (Message, None) or (None, reason) with reason one of json, type, missing:<key>, timestamp."""
    try:
        obj = json.loads(raw)
    except ValueError:  # includes JSONDecodeError and UnicodeDecodeError; a blank line lands here too
        return None, "json"
    if not isinstance(obj, dict):
        return None, "type"
    for key in ("headerId", "timestamp", "serialNumber", "orderId", "agvPosition", "driving", "errors", "loads"):
        if key not in obj:
            return None, f"missing:{key}"
    pos = obj["agvPosition"]
    if not isinstance(pos, dict):
        return None, "type"
    for key in ("x", "y"):
        if key not in pos:
            return None, f"missing:agvPosition.{key}"
    header, ts, serial, order = obj["headerId"], obj["timestamp"], obj["serialNumber"], obj["orderId"]
    if not _is_int(header) or header < 0:
        return None, "type"
    if not isinstance(ts, str):
        return None, "type"
    if not _TS_RE.match(ts):
        return None, "timestamp"
    try:
        epoch = _epoch(ts)
    except ValueError:
        return None, "timestamp"
    if not isinstance(serial, str) or not serial or not isinstance(order, str):
        return None, "type"
    if not _is_int(pos["x"]) or not _is_int(pos["y"]):
        return None, "type"
    if not isinstance(obj["driving"], bool) or not isinstance(obj["errors"], list) or not isinstance(obj["loads"], list):
        return None, "type"
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

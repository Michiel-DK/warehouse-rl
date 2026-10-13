"""Ground-truth scorer for the stuck detector. The ONLY fleet module that reads a message's `custom` block.

score_run(lines_by_zone, store, run, stuck_after=30) -> dict (the content of score.json). `lines_by_zone` maps a zone to an
iterable of the emitter's raw JSON lines (bytes or str), in time order; the detector's output is read from the store.
Definitions: docs/SCOPE.md "S5C1".

Truth stuck step: robot message t (not the robot's last) with driving false, orderId non-empty and errors empty, where the
same robot's NEXT message carries stuck_event true (the simulator wanted the robot to move at step t and it did not). A
truth episode is a maximal run of consecutive truth stuck steps of one robot with one orderId; start = ts of its first
message, end = ts of the message after its last; it counts when end - start >= stuck_after.
"""
import json

from .ledger import exclusion
from .parse import epoch_of

TRUTH_DEFINITION = ("truth stuck step = robot message t (not the last) with driving false, orderId non-empty and errors "
                    "empty whose next message has the simulator stuck flag; truth episode = maximal run of such steps "
                    "of one robot and one orderId, start = ts of its first message, end = ts of the message after its "
                    "last, kept when end - start >= stuck_after")
CAUSE_NOTE = ("Agreement with a proximity proxy, not ground truth about cause: the frozen state of a neighbour is public "
              "in the message, the simulator does not expose which robot blocks which, and a clash flag is a decision "
              "event of the simulator. traffic and blocked_by_stuck agree with clash or other, blocked_by_faulted with "
              "frozen_neighbour, unknown with other.")
TRUTH_CLASSES = ("clash", "frozen_neighbour", "other")
_AGREES = {"blocked_by_faulted": ("frozen_neighbour",), "traffic": ("clash", "other"),
           "blocked_by_stuck": ("clash", "other"), "unknown": ("other",)}


class _Rec:
    """One message, reduced to what the scorer needs."""
    __slots__ = ("ts", "order", "x", "y", "driving", "frozen", "stuck_event", "clash", "action")

    def __init__(self, obj):
        c = obj.get("custom") or {}
        self.ts = epoch_of(obj["timestamp"])
        self.order = obj["orderId"]
        self.x, self.y = obj["agvPosition"]["x"], obj["agvPosition"]["y"]
        self.driving = bool(obj["driving"])
        self.frozen = bool(obj["errors"])
        self.stuck_event = c.get("stuck_event") is True
        self.clash = c.get("clash_event") is True
        self.action = c.get("recovery_action")


def _load(lines_by_zone):
    """{robot: [_Rec by ts]}, {robot: zone}, {(zone, ts): [(robot, x, y)]} of frozen robots."""
    robots, zone_of, frozen = {}, {}, {}
    for zone in sorted(lines_by_zone):
        for raw in lines_by_zone[zone]:
            if not raw.strip():
                continue
            obj = json.loads(raw)
            r = _Rec(obj)
            serial = obj["serialNumber"]
            robots.setdefault(serial, []).append(r)
            zone_of[serial] = zone
            if r.frozen:
                frozen.setdefault((zone, r.ts), []).append((serial, r.x, r.y))
    for recs in robots.values():
        recs.sort(key=lambda r: r.ts)
    return robots, zone_of, frozen


def _truth_runs(recs):
    """Maximal runs of consecutive truth stuck steps of one robot with one orderId: [(first index, last index)]."""
    runs, cur = [], None
    for t in range(len(recs) - 1):
        m = recs[t]
        step = (not m.driving) and m.order != "" and not m.frozen and recs[t + 1].stuck_event
        if step and cur is not None and recs[cur[1]].order == m.order:
            cur[1] = t
        elif step:
            if cur is not None:
                runs.append(tuple(cur))
            cur = [t, t]
        elif cur is not None:
            runs.append(tuple(cur))
            cur = None
    if cur is not None:
        runs.append(tuple(cur))
    return runs


def _overlap(a0, a1, b0, b1):
    return min(a1, b1) - max(a0, b0)


def _frac(num, den):
    return None if den == 0 else num / den


def score_run(lines_by_zone, store, run, stuck_after=30):
    robots, zone_of, frozen = _load(lines_by_zone)
    truth, short = [], {}  # truth: dicts; short: robot -> [(start, end)] of truth runs shorter than stuck_after
    for serial in sorted(robots):
        recs = robots[serial]
        for first, last in _truth_runs(recs):
            start, end = recs[first].ts, recs[last + 1].ts
            if end - start >= stuck_after:
                truth.append(dict(robot=serial, start=start, end=end, first=first, last=last + 1))
            else:
                short.setdefault(serial, []).append((start, end))

    rows = store.select("stuck_episodes", {"run": run})
    excluded = dict(left_censored=0, interrupted=0, open=0, faulted_self=0)
    detected, fs = [], []
    for e in rows:
        why = exclusion(e)
        if why:
            excluded[why] += 1
        elif e["cause"] == "faulted_self":
            excluded["faulted_self"] += 1
            fs.append(e)
        else:
            detected.append(e)

    pairs = sorted(((d["robot"], d["start"], t["start"], i, j)
                    for i, d in enumerate(detected) for j, t in enumerate(truth)
                    if d["robot"] == t["robot"] and _overlap(d["start"], d["end"], t["start"], t["end"]) > 0))
    used_d, used_t, matched = set(), set(), []
    for _, _, _, i, j in pairs:
        if i not in used_d and j not in used_t:
            used_d.add(i)
            used_t.add(j)
            matched.append((detected[i], truth[j]))

    unmatched = dict(frozen=0, short_truth=0, by_design=0)
    for i, d in enumerate(detected):
        if i in used_d:
            continue
        recs = robots.get(d["robot"], [])
        if any(d["start"] <= r.ts <= d["end"] and r.frozen for r in recs):
            unmatched["frozen"] += 1
        elif any(_overlap(d["start"], d["end"], s, e) > 0 for s, e in short.get(d["robot"], [])):
            unmatched["short_truth"] += 1
        else:
            unmatched["by_design"] += 1

    confusion = {c: {t: 0 for t in TRUTH_CLASSES} for c in sorted(_AGREES)}
    agree = 0
    res_table = {"order_dropped": {"abandon": 0, "no_abandon": 0}, "not_order_dropped": {"abandon": 0, "no_abandon": 0}}
    for d, t in matched:
        recs = robots[t["robot"]]
        window = [r for r in recs if t["start"] <= r.ts <= t["end"]]
        if any(r.clash for r in window):
            klass = "clash"
        elif any(abs(r.x - fx) + abs(r.y - fy) <= 1
                 for r in window for (other, fx, fy) in frozen.get((zone_of[t["robot"]], r.ts), ()) if other != t["robot"]):
            klass = "frozen_neighbour"
        else:
            klass = "other"
        confusion[d["cause"]][klass] += 1
        agree += klass in _AGREES[d["cause"]]
        abandon = any(r.action == "abandon" for r in window)
        res_table["order_dropped" if d["resolution"] == "order_dropped" else "not_order_dropped"][
            "abandon" if abandon else "no_abandon"] += 1
    agree_res = res_table["order_dropped"]["abandon"] + res_table["not_order_dropped"]["no_abandon"]

    at_entry = 0
    for e in fs:
        at_entry += any(r.ts == e["t_entry"] and r.frozen for r in robots.get(e["robot"], []))

    return dict(
        run=run, stuck_after=stuck_after, truth_episodes=len(truth), detected_episodes=len(detected),
        detected_excluded=excluded, matched=len(matched),
        precision=_frac(len(matched), len(detected)), recall=_frac(len(matched), len(truth)),
        unmatched_detected=unmatched,
        cause_proximity_agreement=dict(agreement=_frac(agree, len(matched)), confusion=confusion, note=CAUSE_NOTE),
        resolution_agreement=dict(agreement=_frac(agree_res, len(matched)), table=res_table),
        faulted_self=dict(count=len(fs), frozen_at_entry=_frac(at_entry, len(fs))),
        truth_definition=TRUTH_DEFINITION)


def dumps(result):
    """Deterministic score.json text: same input, byte-identical output."""
    return json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n"


def zone_files(pattern):
    """{zone: [paths in nnn order]} for a glob of zone<z>-<nnn>.jsonl.gz files (numeric order, so zone10 > zone2)."""
    import glob
    import os
    import re

    out = {}
    for path in glob.glob(pattern):
        m = re.fullmatch(r"zone(\d+)-(\d+)\.jsonl\.gz", os.path.basename(path))
        if m:
            out.setdefault(m.group(1), []).append((int(m.group(2)), path))
    return {z: [p for _, p in sorted(v)] for z, v in sorted(out.items(), key=lambda kv: int(kv[0]))}


def gz_lines(paths):
    import gzip

    for p in paths:
        with gzip.open(p, "rb") as f:
            yield from f


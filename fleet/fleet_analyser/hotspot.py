"""Stall extraction and per-cell aggregation: where on the floor do robots with an active order keep failing to move?

Analyst side: the input is parsed `Message` objects and the store's `stuck_episodes` rows, nothing else. A *stall* is
what a robot with an order does when its move into the next cell does not happen (a clash, a wait, a slip on bad
floor): it stays on its cell, keeps its heading, keeps its order, and its route still names the cell in front of it.

Stall message: for consecutive messages (prev, cur) of one robot with cur.header_id == prev.header_id + 1, cur is a stall
message iff ALL of: prev.order_id != "" and cur.order_id == prev.order_id; same (x, y); theta present on both and equal;
cur is not faulted; and the nodeStates rule holds:
  * prev has a first route node (nodes_reported and next_x/next_y set): it must be the cell in front of prev given
    prev.theta (RIGHT x+1, UP y-1, LEFT x-1, DOWN y+1). The stall is attributed to that cell (attribution "next").
    cur's own next node is never used (a replan on cur does not move the attribution).
  * prev has no nodeStates key (old schema, nodes_reported False): the stall is attributed to the current cell
    (attribution "current"); every other condition still applies.
  * prev has nodeStates [] (nodes_reported True, no node): never a stall message (loading, picker waits).
A pair where either message lacks theta (fleet-state/1) produces no stall, as do an empty or changed order, a theta
change, a faulted cur and a headerId gap.
A *stall* is a maximal run of consecutive stall messages of one robot with the same (attribution, attributed cell).
start = prev.ts of its first message (the attempt time), end = ts of its last stall message.
"""
import glob as _glob
import gzip
from collections import defaultdict

from .parse import parse_line

# theta (as the emitter rounds it) -> (dx, dy); the grid's y axis points down
_FRONT = ((0.0, (1, 0)), (1.5708, (0, -1)), (3.1416, (-1, 0)), (-1.5708, (0, 1)))
_THETA_TOL = 1e-3
DEFAULT_WINDOW_H = 1.0
DEFAULT_HALF_LIFE_H = 1.0


def front_cell(x, y, theta):
    """The cell in front of (x, y) heading `theta` (radians), or None when theta is not one of the four headings."""
    for t, (dx, dy) in _FRONT:
        if abs(theta - t) <= _THETA_TOL:
            return x + dx, y + dy
    return None


def cell_str(x, y):
    return f"{x},{y}"


def read_messages(pattern):
    """Parse every line of the zone files matching `pattern` (sorted by name, so zone files in nnn order). Rejected lines
    and duplicate (serial, headerId) pairs are dropped. Holds the whole stream in memory (smoke and 10^6-message runs)."""
    msgs, seen = [], set()
    for path in sorted(_glob.glob(pattern)):
        with gzip.open(path, "rb") as f:
            for line in f:
                m, _ = parse_line(line)
                if m is None or (m.serial, m.header_id) in seen:
                    continue
                seen.add((m.serial, m.header_id))
                msgs.append(m)
    return msgs


def _stall_pair(prev, cur):
    """(attribution, (x, y)) when `cur` is a stall message after `prev`, else None."""
    if cur.header_id != prev.header_id + 1 or prev.order_id == "" or cur.order_id != prev.order_id:
        return None
    if (prev.x, prev.y) != (cur.x, cur.y) or prev.theta is None or cur.theta is None or prev.theta != cur.theta:
        return None
    if cur.faulted:
        return None
    if not prev.nodes_reported:
        return "current", (prev.x, prev.y)
    if prev.next_x is None:
        return None
    if front_cell(prev.x, prev.y, prev.theta) != (prev.next_x, prev.next_y):
        return None
    return "next", (prev.next_x, prev.next_y)


def extract_stalls(messages, run):
    """Pure and deterministic: list of stall row dicts sorted by (zone, robot, start). See the module docstring."""
    by_robot = defaultdict(list)
    occupied = defaultdict(set)  # (zone, ts, x, y) -> serials reporting that position
    for m in messages:
        by_robot[(m.zone, m.serial)].append(m)
        occupied[(m.zone, m.ts, m.x, m.y)].add(m.serial)
    stalls = []
    for (zone, serial), msgs in by_robot.items():
        msgs.sort(key=lambda m: m.header_id)
        cur_run = None  # dict(key, start, end, n, occ)
        for prev, cur in zip(msgs, msgs[1:]):
            hit = _stall_pair(prev, cur)
            if hit is None:
                if cur_run is not None:
                    stalls.append(_finish(cur_run, run, zone, serial))
                    cur_run = None
                continue
            attribution, (cx, cy) = hit
            occ = any(occupied.get((zone, t, cx, cy), set()) - {serial} for t in (prev.ts, cur.ts))
            key = (attribution, cell_str(cx, cy))
            if cur_run is not None and cur_run["key"] != key:
                stalls.append(_finish(cur_run, run, zone, serial))
                cur_run = None
            if cur_run is None:
                cur_run = dict(key=key, start=prev.ts, end=cur.ts, n=1, occ=occ)
            else:
                cur_run.update(end=cur.ts, n=cur_run["n"] + 1, occ=cur_run["occ"] or occ)
        if cur_run is not None:
            stalls.append(_finish(cur_run, run, zone, serial))
    stalls.sort(key=lambda s: (s["zone"], s["robot"], s["start"]))
    return stalls


def _finish(r, run, zone, serial):
    attribution, cell = r["key"]
    return dict(run=run, zone=zone, robot=serial, cell=cell, attribution=attribution, start=r["start"], end=r["end"],
                n_msgs=r["n"], seconds=r["end"] - r["start"], next_occupied=bool(r["occ"]), in_episode=None,
                faulted_episode=False)


def annotate_episodes(stalls, episodes):
    """Fill in_episode (the cause of an overlapping detector episode of the same robot) and faulted_episode in place.
    Episode rows come from the store's stuck_episodes. Skipped: left_censored rows (start unknown after a resume) and
    resolution "interrupted" rows (ingest marks an episode left `open` by a killed process that way on resume: its end is
    unknown). An open or unresolved episode with end None counts as running to +infinity. Returns `stalls`."""
    by_robot = defaultdict(list)
    for ep in episodes:
        if ep.get("left_censored") or ep.get("resolution") == "interrupted":
            continue
        by_robot[(str(ep["zone"]), ep["robot"])].append(ep)
    for eps in by_robot.values():
        eps.sort(key=lambda e: e["start"])
    for s in stalls:
        s["in_episode"] = None
        for ep in by_robot.get((s["zone"], s["robot"]), ()):
            end = float("inf") if ep.get("end") is None else ep["end"]
            if ep["start"] <= s["end"] and s["start"] <= end:
                s["in_episode"] = ep["cause"]
                break
        s["faulted_episode"] = s["in_episode"] == "blocked_by_faulted"
    return stalls


def counted(stall, exclude_occupied=True):
    """The filter shared by the cost map and the outcome grader: never faulted-episode stalls; by default never stalls
    whose attributed cell another robot was sitting on (that is a queue behind a robot, not bad floor)."""
    return not stall["faulted_episode"] and not (exclude_occupied and stall["next_occupied"])


def aggregate(stalls, at_ts, window_h=DEFAULT_WINDOW_H, half_life_h=DEFAULT_HALF_LIFE_H, exclude_occupied=True):
    """{(zone, cell): {stalls, seconds, robots, score}} from stalls with at_ts - window < end <= at_ts (no look-ahead),
    score = sum 2 ** (-(at_ts - end) / (half_life_h * 3600))."""
    lo = at_ts - window_h * 3600
    acc = {}
    for s in stalls:
        if not (lo < s["end"] <= at_ts) or not counted(s, exclude_occupied):
            continue
        a = acc.setdefault((s["zone"], s["cell"]), dict(stalls=0, seconds=0, robots=set(), score=0.0))
        a["stalls"] += 1
        a["seconds"] += s["seconds"]
        a["robots"].add(s["robot"])
        a["score"] += 2 ** (-(at_ts - s["end"]) / (half_life_h * 3600))
    for a in acc.values():
        a["robots"] = len(a["robots"])
    return acc

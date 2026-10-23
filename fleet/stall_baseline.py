"""S15A naive stall baseline: InOrbit-style stall rules and our station-aware bounded rule, side by side on one stream.

Usage: python fleet/stall_baseline.py [--moroop] [--runs RUN_DIR ...] [--smoke] [--out PATH] [--workers N]
           [--moroop-dir DIR] [--jsonl-dir NAME] [--sim-stations auto|PATH] [--sim-station-radius 0]
           [--reference-dir results/fleet]
Workers (processes in flight): --workers, else SCHED_WORKERS, else os.cpu_count() - 2 (fleet_analyser.stations
.resolve_workers); multiprocessing only, one task per MoRoOp shift or per simulator run.
--moroop    the nine MoRoOp shifts (fleet/data/moroop/{raw,<jsonl-dir>,stations.json}); asserts N0-30 stuck_runs == 567.
--smoke     MoRoOp shift 1 (k = 1) alone, end to end; the 567 check cannot run on one shift and is skipped.
--runs      simulator run directories (zone<z>-<nnn>.jsonl.gz + emit_ledger.json or --sim-stations PATH).
Output --out (default results/fleet/stall_baseline.json): sort_keys, indent 1, no timestamp or wall-clock value, so two runs
give byte-identical files. Nothing else is written. No store is written: the sim episodes are recomputed in memory and
handed to fleet_analyser.score.score_run through a duck-typed store; every `store*` directory of every --runs directory
is hashed before and after and the run exits 1 on a change; --out inside such a directory is refused (guard_out_path), and
open_store_for_write() refuses an original store (copy_store_to_temp() makes the copy a writer may use).

Rules (docs/LITERATURE.md Part 8 section 1; all gated on orderId non-empty, no station or error logic):
  N0-30, N0-60  fleet_analyser.detector.Detector(stations=None, stuck_after=30|60); stillness = the stream's `driving`
                flag. N0-30 is the old 30 s rule (567 stuck runs on MoRoOp, results/fleet/timebudget_moroop.json).
  N1            InOrbit `unableToNavigate`: the diagonal of the bounding box of the positions in the window (t-60, t] is
                < 2 m (Euclidean, sqrt(dx^2 + dy^2) * cell_m), and that has held at every grid second of [t-600, t];
                alert at the first such t, episode start = alert - 660, end = the first t after it where the 60 s
                condition fails.
  N2-W          InOrbit "stopped while on a mission", W in {30, 60, 120, 180} (180 documented): the largest side of the
                bounding box of the positions in (t-W, t] is < 2 m (max(max x - min x, max y - min y) * cell_m); alert
                at the first such t, episode start = alert - W, end = the first t after it where it fails.
  ours          the station-aware bounded rule: Detector(stations, station_radius, servicing_max_s auto), as in the -sb
                results (MoRoOp radius 1; the sim -sb stores used radius 0, so the sim default here is 0).
N1 and N2-W are POSITION rules, not the Detector, and are not forced through it: MoRoOp's `driving` counts rotation in
place (omega > 0.05 rad/s) as moving, a displacement box does not.

Window semantics (binding): positions are a right-continuous step function in event time, position(tau) = the last message
with ts <= tau, evaluated on a 1 s grid from the robot's first to its last message (the log is change-only, so each
message's position and orderId are carried forward to the next message). The position set of the half-open window
(t-W, t] is {position of the last message with ts <= t-W} u {positions of messages with ts in (t-W, t]}. A robot whose
stop message is at s after a jump of >= 6 cells therefore first satisfies N2-W at t = s+W exactly (at s+W-1 the window
still holds the pre-stop position); N1's 60 s condition first holds at s+60 and the alert is at s+660. A window that
starts before the robot's first message (t-W < first ts) is not evaluated (condition false). The orderId gate applies per
grid second: an empty orderId anywhere in the window (carried piece included) makes the condition false.
Units: MoRoOp cells are floored 0.5 m, so a side in metres = (max cell - min cell) * 0.5 and the test is < 2.0 (a spread of 3
cells qualifies, 4 does not); the diagonal is sqrt(dx^2 + dy^2) * 0.5 < 2.0 (dx^2 + dy^2 < 16). The simulator grid has no
metre scale on record: 2 m is read as 2 cells and the sim rows of N1 and N2-W carry "scale": "assumed 1 cell = 1 m".
Because the condition can only change at a message time or W seconds after one, it is evaluated at those breakpoints and
carried to the next (a sliding min/max over the messages), which is the same set of grid seconds without an O(n W) scan.

Gap-spanning alerts (N1, N2-W): an alert is gap-spanning iff its evidence window, (t-W, t] for N2-W and (t-660, t] for N1
(the 60 s window at every second of [t-600, t]), intersects a gap between two consecutive messages that is > 60 s
(timebudget's gap rule), i.e. gap start < t and gap end > t-W. The count per rule is reported.

stuck_runs for every rule = the number of alert episodes. The MoRoOp label match is fleet/adapters/moroop.py
label_comparison, called unchanged with moroop.run_intervals substituted (a context-managed module attribute swap) by the
rule's episodes as (start, end, first index, last index); no detector, gap or label-match logic is copied. On the sim the
reference stuck episodes and the match are fleet_analyser.score.score_run (its TRUTH_DEFINITION, run builder and overlap
rule), called once per zone with that zone's lines and episode rows, stuck_after 30 for every rule so the reference set is
identical across rules. N0 rows keep
the Detector's faulted_self episodes, which score_run excludes from `detected`; N1 / N2-W rows have no error logic and so
count a frozen robot as detected (cause "position_rule").

Per labelled stop (every MoRoOp label episode >= 30 s of a processed shift; shift 7 has the 250 s and 127 s ones) the output
carries the stopped run (the first driving-false run, of any length, that overlaps the label), the box-stillness span (the
maximal run of messages around the label's start, grown backwards first and then forwards, whose positions fit one 2 m
side box), and each rule's alert latency = the alert of the first episode of that rule that overlaps the label window
(label start .. label end + 30 s) minus the stopped run's start (null when the rule has no such episode or the label overlaps no stopped run).
"""
import argparse
import bisect
import collections
import contextlib
import gzip
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

FLEET = Path(__file__).resolve().parent
REPO = FLEET.parent
for _p in (FLEET, REPO / "src", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import timebudget as tb  # noqa: E402
from adapters import moroop  # noqa: E402
from fleet_analyser import score as score_mod  # noqa: E402
from fleet_analyser import servicing as servicing_mod  # noqa: E402
from fleet_analyser.detector import Detector  # noqa: E402
from fleet_analyser.parse import iso, parse_line  # noqa: E402
from fleet_analyser.stations import load_stations, resolve_workers  # noqa: E402
from fleet_analyser.store import JsonlStore  # noqa: E402

SCHEMA = "stall-baseline/1"
SCORE_FIELDS = ("detected_excluded", "matched", "precision", "recall")
BOX_LIMIT_M = 2.0
N1_WINDOW_S = 60
N1_SUSTAIN_S = 600
N2_WINDOWS = (30, 60, 120, 180)
RULES = ("N0-30", "N0-60", "N1", "N2-30", "N2-60", "N2-120", "N2-180", "ours")
POSITION_RULES = ("N1",) + tuple(f"N2-{w}" for w in N2_WINDOWS)
EXPECTED_N0_30_STUCK_RUNS = 567  # results/fleet/timebudget_moroop.json, the old rule over the nine shifts
SMOKE_SHIFT = 1
MOROOP_CELL_M = 0.5
SIM_CELL_M = 1.0
SIM_SCALE_NOTE = "assumed 1 cell = 1 m"
MOROOP_RADIUS = 1
GAP_S = tb.DEFAULT_MAX_GAP_S
STUCK_AFTER = 30
DEFAULT_OUT = REPO / "results" / "fleet" / "stall_baseline.json"
DEFAULT_REFERENCE = REPO / "results" / "fleet"
# sim run directory name -> tag of its results/fleet/*-sb.json files
SB_TAGS = {"s10-none": "s10-none", "s10c-blind": "s10c-blind", "s10-breakdown": "s10-breakdown",
           "s8b-score": "s8b-medium-80-p03-07", "phaseA": "closed-loop-sticky"}
_STORE_NAME = re.compile(r"^store(-.+)?$")


# ------------------------------------------------------------------------------------------------ store guard
def _is_original_store(path):
    p = Path(path)
    if not p.is_dir():
        return False
    return bool(_STORE_NAME.match(p.name)) and any(p.parent.glob("zone*-000.jsonl.gz"))


def guard_out_path(path):
    """SystemExit when `path` is, or lies inside, an original store directory (a run's store / store-* next to its zone
    files; a copy_store_to_temp() copy lives elsewhere and is not)."""
    p = Path(path).resolve()
    for q in (p, *p.parents):
        if _is_original_store(q):
            raise SystemExit(f"stall_baseline: refusing to write under the original store {q}")


def open_store_for_write(path):
    """A JsonlStore on `path` for writing, or SystemExit when `path` is an original store (use copy_store_to_temp)."""
    guard_out_path(path)
    return JsonlStore(str(path))


def copy_store_to_temp(src, parent=None):
    """Copy an original store directory into a fresh temp dir and return the copy's path (the only store a writer may open)."""
    dst = Path(tempfile.mkdtemp(prefix="stall_baseline_store_", dir=parent)) / Path(src).name
    shutil.copytree(src, dst)
    return str(dst)


def run_store_dirs(run_dir):
    p = Path(run_dir)
    return sorted(q for q in p.iterdir() if q.is_dir() and _STORE_NAME.match(q.name)) if p.is_dir() else []


def hash_run_stores(run_dirs):
    return {str(d): tb.store_hash(d) for r in run_dirs for d in run_store_dirs(r)}


# ------------------------------------------------------------------------------------------------ position rules
class _SlidingExtreme:
    """Min or max over the index range [lo, hi) of an array while both ends only move forward (monotonic deque)."""

    def __init__(self, values, is_max):
        self.v, self.sign, self.q, self.pushed = values, 1 if is_max else -1, collections.deque(), 0

    def query(self, lo, hi):
        v, s, q = self.v, self.sign, self.q
        while self.pushed < hi:
            i = self.pushed
            while q and s * v[q[-1]] <= s * v[i]:
                q.pop()
            q.append(i)
            self.pushed += 1
        while q[0] < lo:
            q.popleft()
        return v[q[0]]


def box_condition_runs(kept, window_s, kind, cell_m):
    """(runs, last grid second): maximal runs [a, b) of grid seconds at which the box condition holds.

    kind "side": the largest side of the bounding box of the window (t-window_s, t] is < 2 m; kind "diag": its diagonal is.
    The orderId of every position in the window (the carried one included) must be non-empty. Evaluated at the breakpoints
    (message times and message times + window_s) and carried to the next breakpoint; a window that starts before the first
    message is not evaluated."""
    ts = [m.ts for m in kept]
    xs, ys = [m.x for m in kept], [m.y for m in kept]
    empty = [0]
    for m in kept:
        empty.append(empty[-1] + (m.order_id == ""))
    t_first, t_last = ts[0] + window_s, ts[-1]
    if t_first > t_last:
        return [], t_last
    bps = sorted({t_first} | {t for t in ts if t_first <= t <= t_last}
                 | {t + window_s for t in ts if t_first <= t + window_s <= t_last})
    mn_x, mx_x = _SlidingExtreme(xs, False), _SlidingExtreme(xs, True)
    mn_y, mx_y = _SlidingExtreme(ys, False), _SlidingExtreme(ys, True)
    limit = BOX_LIMIT_M / cell_m  # in cells: a side of 3 cells (1.5 m) qualifies, 4 (2.0 m) does not
    flags = []
    for t in bps:
        hi = bisect.bisect_right(ts, t)
        lo = bisect.bisect_right(ts, t - window_s) - 1  # the carried message (ts <= t - window_s); t - window_s >= ts[0]
        dx = mx_x.query(lo, hi) - mn_x.query(lo, hi)
        dy = mx_y.query(lo, hi) - mn_y.query(lo, hi)
        still = max(dx, dy) < limit if kind == "side" else dx * dx + dy * dy < limit * limit
        flags.append(empty[hi] - empty[lo] == 0 and still)
    runs, start = [], None
    for t, ok in zip(bps, flags):
        if ok and start is None:
            start = t
        elif not ok and start is not None:
            runs.append((start, t))
            start = None
    if start is not None:
        runs.append((start, t_last + 1))
    return runs, t_last


def gaps_of(kept, gap_s=GAP_S):
    return [(a.ts, b.ts) for a, b in zip(kept, kept[1:]) if b.ts - a.ts > gap_s]


def spans_gap(gaps, alert, evidence_from):
    """True iff the window (evidence_from, alert] intersects a gap (g0, g1): g0 < alert and g1 > evidence_from."""
    i = bisect.bisect_left([g[0] for g in gaps], alert) - 1  # the last gap starting before the alert (gaps are disjoint)
    return i >= 0 and gaps[i][1] > evidence_from


def position_rule_episodes(kept, rule, cell_m):
    """Episodes of N1 or N2-W over one robot's kept messages (sorted, unique ts): dicts start, alert, end, resolution,
    a, b (first / last kept index, as the label match needs), gap_spanning."""
    if not kept:
        return []
    if rule == "N1":
        runs, t_last = box_condition_runs(kept, N1_WINDOW_S, "diag", cell_m)
        span = N1_WINDOW_S + N1_SUSTAIN_S
    else:
        span = int(rule.split("-")[1])
        runs, t_last = box_condition_runs(kept, span, "side", cell_m)
    ts = [m.ts for m in kept]
    gaps = gaps_of(kept)
    out = []
    for a, b in runs:
        if rule == "N1":
            if b - a < N1_SUSTAIN_S + 1:  # the condition must hold at every second of [t-600, t]
                continue
            alert = a + N1_SUSTAIN_S
        else:
            alert = a
        unresolved = b > t_last
        end = t_last if unresolved else b
        start = alert - span
        ia = max(bisect.bisect_right(ts, start) - 1, 0)
        ib = len(kept) - 1 if unresolved else max(ia, bisect.bisect_left(ts, end) - 1)
        out.append(dict(start=start, alert=alert, end=end, resolution="unresolved" if unresolved else "moved", a=ia, b=ib,
                        gap_spanning=spans_gap(gaps, alert, alert - span)))
    return out


# ------------------------------------------------------------------------------------------------ detector rules
def detector_rows(messages, stuck_after=STUCK_AFTER, stations=None, station_radius=0, servicing_max_s=None):
    """The Detector's episodes (last open / close event per episode id) over messages fed in (ts, serial) order."""
    det = Detector(stuck_after=stuck_after, stations=stations, station_radius=station_radius,
                   servicing_max_s=servicing_max_s)
    events = []
    for m in sorted(messages, key=lambda m: (m.ts, m.serial)):
        events += det.feed(m)
    events += det.end_all()
    rows = {}
    for ev in events:
        if ev["kind"] in ("episode_open", "episode_close"):
            rows[ev["episode_id"]] = ev
    return sorted(rows.values(), key=lambda r: (r["zone"], r["robot"], r["start"]))


def detector_episodes(kept, **kw):
    """detector_rows of one robot's kept messages as the common episode dict (indices into `kept`)."""
    ts = [m.ts for m in kept]
    out = []
    for r in detector_rows(kept, **kw):
        unresolved = r["resolution"] == "unresolved"
        ia = bisect.bisect_left(ts, r["start"])
        ib = len(kept) - 1 if unresolved else max(ia, bisect.bisect_left(ts, r["end"]) - 1)
        out.append(dict(start=r["start"], alert=r["t_entry"], end=r["end"], resolution=r["resolution"], a=ia, b=ib,
                        cause=r["cause"]))
    return out


def intervals_of(eps):
    return [(e["start"], e["end"], e["a"], e["b"]) for e in eps]


def rule_episodes(kept, rule, cell_m, stations=None, station_radius=0, servicing_max_s=None):
    """One robot's episodes under one rule (see the module docstring)."""
    if rule in ("N0-30", "N0-60"):
        return detector_episodes(kept, stuck_after=int(rule.split("-")[1]))
    if rule == "ours":
        return detector_episodes(kept, stuck_after=STUCK_AFTER, stations=stations, station_radius=station_radius,
                                 servicing_max_s=servicing_max_s)
    return position_rule_episodes(kept, rule, cell_m)


# ------------------------------------------------------------------------------------------------ MoRoOp
@contextlib.contextmanager
def _intervals_substituted(intervals):
    """moroop.label_comparison builds its stuck runs with moroop.run_intervals; swap in the rule's episodes for the call."""
    original = moroop.run_intervals
    moroop.run_intervals = lambda *a, **k: list(intervals)
    try:
        yield
    finally:
        moroop.run_intervals = original


def _label_counts(lab):
    fa = lab["false_alarms"]["list"]
    counts = dict(stuck_runs=lab["stuck_runs"], hits=lab["episodes_ge_30s"]["hits"], misses=lab["episodes_ge_30s"]["misses"],
                  false_alarms=lab["false_alarms"]["count"], ge30=lab["episodes_ge_30s"]["count"],
                  lt30=lab["episodes_lt_30s"]["count"], episodes=lab["episodes"], timeouts=lab["timeout_operations"]["count"],
                  timeouts_detected=lab["timeout_operations"]["detected"])
    return counts, sum(1 for f in fa if f["on_station_cell"])


def _box_span(kept, i0, cell_m):
    """Box-stillness span around message i0: grown backwards, then forwards, while the side of the box stays < 2 m."""
    limit = BOX_LIMIT_M / cell_m
    lo = hi = i0
    mnx = mxx = kept[i0].x
    mny = mxy = kept[i0].y
    for step in (-1, 1):
        while 0 <= (hi if step > 0 else lo) + step < len(kept):
            m = kept[(hi if step > 0 else lo) + step]
            nx, xx, ny, xy = min(mnx, m.x), max(mxx, m.x), min(mny, m.y), max(mxy, m.y)
            if max(xx - nx, xy - ny) >= limit:
                break
            mnx, mxx, mny, mxy = nx, xx, ny, xy
            if step > 0:
                hi += 1
            else:
                lo -= 1
    end = kept[hi + 1].ts if hi + 1 < len(kept) else kept[hi].ts
    return dict(start=kept[lo].ts, end=end, duration_s=end - kept[lo].ts)


def _label_rows(k, kept, native, eps_by_rule):
    t_end = kept[-1].ts
    ts = [m.ts for m in kept]
    runs, _ = tb.stopped_runs(kept)
    out = []
    for e in moroop.label_episodes(native, t_end):
        if e["end"] - e["start"] < STUCK_AFTER:
            continue
        run = None
        for a, b in runs:
            r_start, r_end = kept[a].ts, (kept[b + 1].ts if b + 1 < len(kept) else kept[b].ts)
            if r_start < e["end"] and r_end > e["start"]:
                run = dict(start=r_start, end=r_end, duration_s=r_end - r_start)
                break
        i0 = min(max(bisect.bisect_right(ts, e["start"]) - 1, 0), len(kept) - 1)
        rules = {}
        for rule in RULES:
            hit = next((x for x in eps_by_rule[rule] if x["start"] <= e["end"] + STUCK_AFTER and x["end"] > e["start"]),
                       None)
            # latency is measured from the stopped run only; no stopped run -> null, never the label start
            rules[rule] = dict(alert=None if hit is None else hit["alert"],
                               alert_latency_s=None if hit is None or run is None else hit["alert"] - run["start"])
        out.append(dict(shift=k, label_start=iso(e["start"]), label_duration_s=e["end"] - e["start"], reasons=e["reasons"],
                        stopped_run=run, box_stillness=_box_span(kept, i0, MOROOP_CELL_M), rules=rules))
    return out


def moroop_shift(k, moroop_dir, jsonl_name):
    """Every rule over MoRoOp shift k. Returns {shift, name, rules: {rule: {...}}, labels: [...]}."""
    d = Path(moroop_dir)
    name = moroop.SHIFTS[k]
    stations_json = json.loads((d / "stations.json").read_text())
    stations, near, _ = tb.cell_sets(stations_json["stations"], [])
    with gzip.open(d / jsonl_name / f"zone{k}-000.jsonl.gz", "rb") as f:
        parsed = []
        for ln in f:
            m, why = parse_line(ln)
            if m is None:
                raise ValueError(f"stall_baseline: shift {k}: parse reject ({why})")
            parsed.append(m)
    kept = tb.kept_messages(parsed)
    data = moroop.load_shift(d / "raw", name)
    native, ops = data["robot_state_cleaned"], data["operations"]
    bound = servicing_mod.resolve("auto", parsed, stations, MOROOP_RADIUS)["servicing_max_s"]
    buckets = moroop.second_buckets(kept, stations, near, tb)  # only label_seconds_per_bucket reads it; not reported
    eps_by_rule = {r: rule_episodes(kept, r, MOROOP_CELL_M, stations, MOROOP_RADIUS, bound) for r in RULES}
    # the Detector episodes must be the existing code's stuck runs (timebudget / the adapter): same (start, end) sets
    old = sorted((s, e) for s, e, _, _ in moroop.run_intervals(kept, tb))
    if sorted((x["start"], x["end"]) for x in eps_by_rule["N0-30"]) != old:
        raise ValueError(f"stall_baseline: shift {k}: N0-30 Detector episodes differ from moroop.run_intervals")
    old = sorted((s, e) for s, e, _, _ in moroop.run_intervals(kept, tb, stations, MOROOP_RADIUS, bound))
    if sorted((x["start"], x["end"]) for x in eps_by_rule["ours"]) != old:
        raise ValueError(f"stall_baseline: shift {k}: ours Detector episodes differ from moroop.run_intervals")
    rules = {}
    for r in RULES:
        with _intervals_substituted(intervals_of(eps_by_rule[r])):
            lab = moroop.label_comparison(native, kept, buckets, ops, stations, tb, None, None)
        counts, on_station = _label_counts(lab)
        row = dict(counts=counts, false_alarms_on_station_cell=on_station)
        if r in POSITION_RULES:
            row["gap_spanning_alerts"] = sum(1 for e in eps_by_rule[r] if e["gap_spanning"])
        if r == "ours":
            row["servicing_max_s"] = bound
        rules[r] = row
    return dict(shift=k, name=name, rules=rules, labels=_label_rows(k, kept, native, eps_by_rule))


def pool_moroop(shift_results):
    out = {}
    for r in RULES:
        counts = collections.Counter()
        on_station = gaps = 0
        for s in shift_results:
            row = s["rules"][r]
            counts.update(row["counts"])
            on_station += row["false_alarms_on_station_cell"]
            gaps += row.get("gap_spanning_alerts", 0)
        counts = {key: counts[key] for key in sorted(counts)}
        row = dict(counts=counts, false_alarms_on_station_cell=on_station,
                   on_station_cell_share=(on_station / counts["false_alarms"]) if counts["false_alarms"] else None,
                   per_shift={str(s["shift"]): s["rules"][r]["counts"] for s in shift_results})
        if r in POSITION_RULES:
            row["gap_spanning_alerts"] = gaps
            row["scale"] = "MoRoOp 0.5 m cells: side < 2 m is a spread of at most 3 cells, diagonal < 2 m is dx^2 + dy^2 < 16"
        out[r] = row
    return out


# ------------------------------------------------------------------------------------------------ simulator runs
class _RowsStore:
    """Duck-typed store for score_run: select("stuck_episodes", {"run": ...}) returns the given rows."""

    def __init__(self, rows):
        self.rows = rows

    def select(self, table, where=None):
        if table != "stuck_episodes":
            raise KeyError(table)
        return list(self.rows)


def _zone_lines(run_dir):
    files = score_mod.zone_files(str(Path(run_dir) / "zone*-*.jsonl.gz"))
    if not files:
        raise SystemExit(f"stall_baseline: no zone<z>-<nnn>.jsonl.gz in {run_dir}")
    return {z: list(score_mod.gz_lines(paths)) for z, paths in files.items()}


def _parse_zone(lines):
    seen, msgs = set(), []
    for ln in lines:
        m, _ = parse_line(ln)
        if m is None or (m.serial, m.header_id) in seen:
            continue
        seen.add((m.serial, m.header_id))
        msgs.append(m)
    return msgs


def _episode_row(robot, e, cause):
    return dict(robot=robot, start=e["start"], end=e["end"], cause=cause, resolution=e["resolution"], left_censored=False,
                t_entry=e["t_entry"] if "t_entry" in e else e["alert"])


def sim_run(run_dir, stations_spec="auto", station_radius=0, workers=1):
    """Every rule over every zone of one simulator run, scored with score_run (per zone)."""
    run_dir = Path(run_dir)
    lines = _zone_lines(run_dir)
    msgs_by_zone = {z: _parse_zone(v) for z, v in lines.items()}
    all_msgs = [m for z in msgs_by_zone for m in msgs_by_zone[z]]
    stations = load_stations(stations_spec, str(run_dir), workers=workers)
    stats = servicing_mod.resolve("auto", all_msgs, stations, station_radius)
    bound = stats["servicing_max_s"]
    zones = {}
    for z in msgs_by_zone:
        by_robot = collections.defaultdict(list)
        for m in msgs_by_zone[z]:
            by_robot[m.serial].append(m)
        kept = {s: tb.kept_messages(v) for s, v in sorted(by_robot.items())}
        zone_rules = {}
        for rule in RULES:
            rows, gap_alerts = [], 0
            if rule in POSITION_RULES:
                for serial, kp in kept.items():
                    for e in position_rule_episodes(kp, rule, SIM_CELL_M):
                        rows.append(_episode_row(serial, e, "position_rule"))
                        gap_alerts += e["gap_spanning"]
            else:
                kw = dict(stuck_after=int(rule.split("-")[1]) if rule.startswith("N0") else STUCK_AFTER)
                if rule == "ours":
                    kw.update(stations=stations, station_radius=station_radius, servicing_max_s=bound)
                rows = [_episode_row(r["robot"], r, r["cause"]) for r in detector_rows(msgs_by_zone[z], **kw)]
            res = score_mod.score_run({z: lines[z]}, _RowsStore(rows), str(run_dir), stuck_after=STUCK_AFTER)
            # the benchmark's own field names: detected_episodes, <reference>_episodes, matched, precision, recall
            row = dict(episodes_total=len(rows),
                       **{k: v for k, v in res.items() if k in SCORE_FIELDS or k.endswith("_episodes")})
            if rule in POSITION_RULES:
                row.update(scale=SIM_SCALE_NOTE, gap_spanning_alerts=gap_alerts)
            zone_rules[rule] = row
        zones[z] = zone_rules
    zones = {z: zones[z] for z in sorted(zones, key=int)}
    return dict(zones=zones, scoring_definition=score_mod.TRUTH_DEFINITION, servicing=dict(stats, station_radius=station_radius),
                ours_episodes_total=sum(zones[z]["ours"]["episodes_total"] for z in zones))


# ------------------------------------------------------------------------------------------------ references
def _read_json(path):
    p = Path(path)
    return json.loads(p.read_text()) if p.is_file() else None


def sb_reference(reference_dir, run_dirs):
    """The -sb numbers copied from their files, each with its source path."""
    ref = Path(reference_dir)
    lab = _read_json(ref / "moroop_label-sb.json")
    out = dict(moroop=dict(source="results/fleet/moroop_label-sb.json", present=lab is not None))
    if lab is not None:
        out["moroop"].update(
            counts=lab["pooled"]["counts"], station_radius=lab["station_radius"], servicing_max_s=lab.get("servicing_max_s"),
            false_alarms_on_station_cell=sum(1 for f in lab["pooled"]["false_alarms"] if f["on_station_cell"]),
            per_shift={k: dict(stuck_runs=v["stuck_runs"], hits=v["episodes_ge_30s"]["hits"],
                               misses=v["episodes_ge_30s"]["misses"], false_alarms=v["false_alarms"]["count"])
                       for k, v in lab["shifts"].items()})
    old = _read_json(ref / "timebudget_moroop.json")
    out["moroop_old_rule"] = dict(source="results/fleet/timebudget_moroop.json", present=old is not None,
                                  counts=None if old is None else old["label"]["counts"])
    sims = {}
    for r in run_dirs:
        tag = SB_TAGS.get(Path(r).name)
        doc = _read_json(ref / f"timebudget_{tag}-sb.json") if tag else None
        sims[str(r)] = dict(source=f"results/fleet/timebudget_{tag}-sb.json" if tag else None, present=doc is not None)
        if doc is not None:
            sims[str(r)].update(stuck_runs_vs_detector=doc["run"]["stuck_runs_vs_detector"],
                                station_radius=doc["src"].get("station_radius"), servicing_max_s=doc.get("servicing_max_s"))
    out["sim"] = sims
    return out


# ------------------------------------------------------------------------------------------------ orchestration
def _task(spec):
    if spec[0] == "moroop":
        return moroop_shift(spec[1], spec[2], spec[3])
    return sim_run(spec[1], spec[2], spec[3], 1)


def run_all(shifts, run_dirs, moroop_dir, jsonl_name, sim_stations, sim_radius, workers):
    tasks = [("moroop", k, str(moroop_dir), jsonl_name) for k in shifts]
    tasks += [("sim", str(r), sim_stations, sim_radius) for r in run_dirs]
    if workers <= 1 or len(tasks) <= 1:
        return [_task(t) for t in tasks]
    import concurrent.futures as cf
    import multiprocessing as mp

    with cf.ProcessPoolExecutor(max_workers=min(workers, len(tasks)), mp_context=mp.get_context("spawn")) as pool:
        return list(pool.map(_task, tasks))  # input order, so the output does not depend on completion order


def definition_block():
    return dict(
        windows="half-open (t-W, t] in event time; positions are a right-continuous step function (position(tau) = the last "
                "message with ts <= tau); the window's position set = the position carried at t-W plus every message position "
                "in (t-W, t]; a window starting before the first message is not evaluated",
        units="MoRoOp 0.5 m cells: side = (max cell - min cell) * 0.5 < 2.0 m, diagonal = sqrt(dx^2 + dy^2) * 0.5 < 2.0 m; "
              "simulator: 2 m read as 2 cells, rows tagged scale 'assumed 1 cell = 1 m'",
        rules={"N0-30": "Detector(stations=None, stuck_after=30)", "N0-60": "Detector(stations=None, stuck_after=60)",
               "N1": "InOrbit unableToNavigate: 60 s box diagonal < 2 m held at every grid second of [t-600, t]; start = alert - 660",
               "N2-W": "InOrbit stopped while on a mission: W s box side < 2 m, W in 30/60/120/180; start = alert - W",
               "ours": "Detector(stations, station_radius, servicing_max_s auto), the -sb rule"},
        gap_spanning="alert whose evidence window ((t-W, t] for N2-W, (t-660, t] for N1) intersects a gap > 60 s between "
                     "consecutive messages",
        position_rules="N1 and N2-W are position rules, not the Detector (MoRoOp driving counts rotation in place as moving)",
        stuck_runs="number of alert episodes under the rule",
        label_match="fleet/adapters/moroop.py label_comparison with run_intervals substituted by the rule's episodes",
        sim_scoring="fleet_analyser/score.py score_run per zone, stuck_after 30; N0 / ours rows keep the Detector's "
                    "faulted_self episodes (excluded by score_run), N1 / N2-W rows have no error logic",
        alert_latency="alert time of the first episode overlapping the label window minus the stopped run's start",
        box_stillness="maximal run of messages around the label start, grown backwards then forwards, whose positions fit a "
                      "2 m side box",
        expected_n0_30_stuck_runs=EXPECTED_N0_30_STUCK_RUNS)


def build_document(args, results, run_dirs, reference, stores):
    mo = [r for r in results if "name" in r]
    sims = {str(r): res for r, res in zip(run_dirs, [x for x in results if "zones" in x])}
    doc = dict(schema=SCHEMA, definition=definition_block(), rules=list(RULES), smoke=bool(args.smoke),
               src=dict(moroop_dir=str(args.moroop_dir) if mo else None, jsonl_dir=args.jsonl_dir if mo else None,
                        shifts=[r["shift"] for r in mo], runs=[str(r) for r in run_dirs],
                        sim_stations=args.sim_stations if sims else None,
                        sim_station_radius=args.sim_station_radius if sims else None,
                        moroop_station_radius=MOROOP_RADIUS, script="fleet/stall_baseline.py"),
               reference_sb=reference, store_guard=dict(stores=sorted(stores), unchanged=True))
    if mo:
        doc["moroop"] = dict(rules=pool_moroop(mo), labels=[row for r in mo for row in r["labels"]])
    if sims:
        doc["sim"] = sims
        for run, res in sims.items():
            ref = reference["sim"].get(run, {})
            sv = ref.get("stuck_runs_vs_detector")
            res["ours_matches_sb_detector_episodes"] = None if sv is None else (
                sv["detector_episodes"] == res["ours_episodes_total"]
                and ref.get("station_radius") == res["servicing"]["station_radius"])
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser(description="S15A naive stall baseline vs our station-aware bounded rule")
    ap.add_argument("--moroop", action="store_true", help="the nine MoRoOp shifts (asserts N0-30 stuck_runs == 567)")
    ap.add_argument("--smoke", action="store_true", help="MoRoOp shift 1 alone, end to end")
    ap.add_argument("--runs", nargs="*", default=[], metavar="RUN_DIR", help="simulator run directories")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--workers", type=int, default=None, help="default: SCHED_WORKERS, else os.cpu_count() - 2")
    ap.add_argument("--moroop-dir", default=str(FLEET / "data" / "moroop"))
    ap.add_argument("--jsonl-dir", default="jsonl-sb", help="name of the adapter jsonl directory under --moroop-dir")
    ap.add_argument("--sim-stations", default="auto", metavar="auto|PATH")
    ap.add_argument("--sim-station-radius", type=int, default=0)
    ap.add_argument("--reference-dir", default=str(DEFAULT_REFERENCE))
    args = ap.parse_args(argv)
    if not (args.moroop or args.smoke or args.runs):
        ap.error("nothing to do: give --moroop, --smoke and/or --runs")
    if args.moroop and args.smoke:
        ap.error("--moroop and --smoke are alternatives")
    if args.sim_station_radius < 0:
        ap.error("--sim-station-radius must be >= 0")
    guard_out_path(args.out)
    out_path = Path(args.out)
    if not out_path.parent.is_dir():
        raise SystemExit(f"stall_baseline: parent directory of --out does not exist: {out_path.parent}")
    run_dirs = [Path(r) for r in args.runs]
    for r in run_dirs:
        if not r.is_dir():
            raise SystemExit(f"stall_baseline: run directory {r} does not exist")
    shifts = list(range(len(moroop.SHIFTS))) if args.moroop else ([SMOKE_SHIFT] if args.smoke else [])
    workers = resolve_workers(args.workers, n_tasks=len(shifts) + len(run_dirs))
    before = hash_run_stores(run_dirs)
    results = run_all(shifts, run_dirs, args.moroop_dir, args.jsonl_dir, args.sim_stations, args.sim_station_radius,
                      workers)
    after = hash_run_stores(run_dirs)
    if before != after:
        changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
        print(f"stall_baseline: store changed during the run: {changed}", file=sys.stderr)
        return 1
    doc = build_document(args, results, run_dirs, sb_reference(args.reference_dir, run_dirs), before)
    if args.moroop:  # full-run assertion: the old rule's 567 stuck runs over the nine shifts (one shift cannot check it)
        got = doc["moroop"]["rules"]["N0-30"]["counts"]["stuck_runs"]
        if got != EXPECTED_N0_30_STUCK_RUNS:
            print(f"stall_baseline: N0-30 stuck_runs {got} != {EXPECTED_N0_30_STUCK_RUNS} "
                  "(results/fleet/timebudget_moroop.json)", file=sys.stderr)
            return 1
    out_path.write_text(json.dumps(doc, sort_keys=True, indent=1, allow_nan=False) + "\n")
    if "moroop" in doc:
        for r in RULES:
            c = doc["moroop"]["rules"][r]["counts"]
            print(f"moroop {r:7s} stuck_runs {c['stuck_runs']:4d} hits {c['hits']} misses {c['misses']} "
                  f"false_alarms {c['false_alarms']}")
    for run, res in doc.get("sim", {}).items():
        print(f"sim {run}: ours episodes {res['ours_episodes_total']}, matches -sb {res['ours_matches_sb_detector_episodes']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

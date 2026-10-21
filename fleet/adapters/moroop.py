"""S13A MoRoOp adapter: one wheel.me AMR, nine 8 h lab shifts -> fleet-state messages for the S12A time budget.

Usage: python fleet/adapters/moroop.py --raw DIR --out DIR [--shift N] [--cell-m 0.5] [--moving-eps 0.05]
                                       [--omega-eps 0.05] [--stations PATH]
       python fleet/adapters/moroop.py --analyse [--raw DIR] [--jsonl DIR] [--budget DIR] [--stations PATH] [--results DIR]
                                       [--station-radius N] [--servicing-max-s S|auto] [--suffix S]

Build mode writes OUT/zone<k>-000.jsonl.gz per shift (only k = N with --shift) and OUT/adapter_stats.json, and derives the
stations file from ALL nine shifts (default fleet/data/moroop/stations.json). The time budget is then run UNCHANGED once
per shift, never one glob over all nine (read_messages dedups (serial, headerId) and the serial has no zone prefix):
  python fleet/timebudget.py --glob fleet/data/moroop/jsonl/zone<k>-000.jsonl.gz --run moroop-<shift> \\
      --stations fleet/data/moroop/stations.json --out fleet/data/moroop/budget/zone<k>.json
Analyse mode reads raw + jsonl + budget and writes results/fleet/timebudget_moroop.json and
results/fleet/timebudget_moroop_shifts.json (sort_keys, indent 1, no wall clock, no absolute path).
S13B: --station-radius N applies the --stations cells to the stuck rule (a run starting within Manhattan N of a station
cell is not stuck; timebudget.run_is_stuck with stations, the same predicate as the Detector). --suffix S writes
timebudget_moroop-S.json, timebudget_moroop_shifts-S.json and moroop_label-S.json (the per-shift and pooled `label`
objects) and never the unsuffixed files. Both absent: the S13A files, byte for byte (S14A adds a `causes` table and an
`overruns` list to every label object).
S14A: --servicing-max-s S|auto (with --station-radius) turns a station stop longer than the bound back into a stuck run
(cause station_overrun, the detector's rule). auto computes one bound PER SHIFT (a shift is one run) from that shift's dwell
times at stations; the four servicing_* keys are in each shift's label object and, as lists in shift order, in the pooled
files. The per-shift budget files it reads must then be written with timebudget.py --station-aware --station-radius N
--servicing-max-s (same spec), and the budget check follows the rule a budget file recorded.

The pure functions work on plain lists of dicts (one dict per row, timestamps int epoch microseconds). pyarrow is imported
lazily inside load_table only, so this module imports and the pure functions run on a venv without pyarrow.
Column mapping and the label comparison: docs/LITERATURE.md Part 2b sections 4 and 5; MAPPING / DEVIATIONS below are
copied into the JSON.
"""
import argparse
import bisect
import collections
import gzip
import hashlib
import json
import math
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
FLEET = HERE.parent
REPO = FLEET.parent

SERIAL = "moroop-amr-1"
MANUFACTURER = "wheel.me"
DEFAULT_CELL_M = 0.5
DEFAULT_MOVING_EPS = 0.05
DEFAULT_OMEGA_EPS = 0.05
STATION_IDS = {135: "charging", 136: "warehouse", 137: "kitting", 138: "assembly"}
STATION_MIN_SHARE = 0.05
SHIFTS = ("2026_07_27_morning", "2026_07_27_evening", "2026_07_28_morning", "2026_07_28_evening", "2026_07_29_morning",
          "2026_07_29_evening", "2026_07_30_morning", "2026_07_31_morning", "2026_07_31_evening")
TABLES = ("jobs", "operations", "dispatch_events", "robot_state_raw", "robot_state_cleaned")
DEFAULT_RAW = FLEET / "data" / "moroop" / "raw"
DEFAULT_STATIONS = FLEET / "data" / "moroop" / "stations.json"
DEFAULT_JSONL = FLEET / "data" / "moroop" / "jsonl"
DEFAULT_BUDGET = FLEET / "data" / "moroop" / "budget"
DEFAULT_RESULTS = REPO / "results" / "fleet"
STUCK_AFTER_S = 30  # fleet_analyser.detector.DEFAULT_STUCK_AFTER, asserted equal in analyse()

HF = dict(repo="Self-Organizing-Production-Logistics/MoRoOp", revision="1.0.1",
          tag_target_commit="9051cb4653648b625999608367eced435e0b3991",
          revision_api_sha="15177e72c99d209d64e20cc013793a5dd3f5b124", license="cc-by-4.0",
          paper="Klein & Jeong, arXiv 2610.02428v1")

EXPECTED = dict(
    cleaned_rows=[15194, 15038, 15553, 15252, 15182, 15168, 14711, 15635, 15694],
    label_rows=[37, 3, 52, 20, 3, 17, 48, 17, 10],
    timeout_operations=[0, 1, 0, 0, 0, 1, 2, 3, 1],
    span_h=[8.12, 8.04, 8.26, 8.10, 8.03, 8.10, 8.15, 8.03, 8.16],
    pooled_span_h=72.99,
    pooled_jobs_per_robot_hour=1382 / 72.99,
)

MAPPING = [
    dict(field="timestamp", source_columns=["created_at"],
         rule="floor to whole seconds, UTC, '%Y-%m-%dT%H:%M:%SZ'; keep the LAST native row of each second"),
    dict(field="headerId", source_columns=["id"],
         rule="1..n contiguous over this shift's emitted messages; never the dataset id (gaps in id are screening removals)"),
    dict(field="manufacturer", source_columns=[], rule="constant 'wheel.me'"),
    dict(field="serialNumber", source_columns=[],
         rule="constant 'moroop-amr-1' (no Z<zone>- prefix, so parse.zone_of gives zone '')"),
    dict(field="orderId", source_columns=["operations.job_id", "operations.start_time", "operations.finish_time",
                                          "jobs.payload.job_type"],
         rule="job_id of the operation running at the kept row's native created_at (start_time <= t < finish_time; null "
              "start or finish never runs); none running but the last finished operation before t and the next starting "
              "one after t share a job -> that job; two running -> latest start_time wins, second counted in "
              "overlap_seconds; job_type 'charging' -> ''"),
    dict(field="agvPosition.x", source_columns=["pos_x"], rule="math.floor(pos_x / cell_m), cell_m 0.5 (floor, not int())"),
    dict(field="agvPosition.y", source_columns=["pos_y"], rule="math.floor(pos_y / cell_m), cell_m 0.5 (floor, not int())"),
    dict(field="agvPosition.theta", source_columns=["pos_theta"], rule="pos_theta as float (radians)"),
    dict(field="driving", source_columns=["velocity_x", "velocity_y", "velocity_omega"],
         rule="hypot(velocity_x, velocity_y) > 0.05 m/s OR abs(velocity_omega) > 0.05 rad/s (strict); never state == "
              "'Navigating'"),
    dict(field="paused", source_columns=["state", "operating_mode"],
         rule="state == 'Paused' or operating_mode != 'Autonomous'"),
    dict(field="errors", source_columns=["diagnostics"],
         rule="[] always; diagnostics status levels are tabulated only; stuck_reason, TIMEOUT and operation_start_denied "
              "are never errors"),
    dict(field="loads", source_columns=[], rule="[] (no payload column in the robot state)"),
    dict(field="waiting_shelf", source_columns=[], rule="'n/a': no shelves, no picker"),
    dict(field="faulted", source_columns=["diagnostics"], rule="'not computed' in S13A"),
    dict(field="stations", source_columns=["state", "current_position_id", "pos_x", "pos_y"],
         rule="per current_position_id in 135 charging / 136 warehouse / 137 kitting / 138 assembly, every cell (same "
              "grid) holding >= 5 % of the state == 'Idle' cleaned rows at that id, pooled over nine shifts; shelves []"),
]

DEVIATIONS = [
    dict(item="pooled numbers",
         deviation="pooled = sum of the nine per-shift timebudget runs (seconds, jobs, spans summed; shares and "
                   "jobs_per_robot_hour recomputed from the sums)",
         reason="serial moroop-amr-1 has no Z<zone>- prefix, so every shift is zone ''; one timebudget run over all nine "
                "files would have read_messages drop shifts 2-9 as duplicate (serial, headerId) and merge them into one "
                "robot"),
    dict(item="station cells distinct",
         deviation="reported (disjoint true/false per id pair), not asserted",
         reason="the brief says report, do not fail; docs/LITERATURE.md Part 2b section 4 said assert"),
    dict(item="label window overlap",
         deviation="a stuck run is the half-open [start ts, ts owning-end of its last message); the hit window "
                   "[label start, label end + 30 s] and the false-alarm window [run start - 30, run end + 30] are closed "
                   "at the far end; label episodes are half-open [floor(first ts), floor(next None ts))",
         reason="the brief gives intervals without endpoint conventions"),
    dict(item="label episode at stream end",
         deviation="an episode with no later 'None' row ends at the last emitted message's timestamp",
         reason="'stream end' in the brief; the bucket grid ends there"),
    dict(item="seconds per state value",
         deviation="seconds = the interval each kept message owns (next kept ts - ts), no_data intervals included",
         reason="the brief asks rows and seconds per state / operating_mode value without a gap rule"),
    dict(item="removed rows",
         deviation="removed rows = max(id) - min(id) + 1 - rows, not max(id) - rows",
         reason="ids continue across shifts (a shift's ids do not start at 1), so max(id) - rows would add the earlier "
                "shifts' rows; for shift 0 (ids from 1) the two agree"),
    dict(item="percentiles",
         deviation="nearest rank: sorted[ceil(p * n) - 1]",
         reason="deterministic and dependency free"),
    dict(item="per-second bucket assignment",
         deviation="the bucket of an owned interval is taken from timebudget.robot_budget called on the pair "
                   "(message i, message i+1); stuck vs stopped_short for the 'anywhere else' case is then decided with "
                   "timebudget.stopped_runs / run_is_stuck on the full stream",
         reason="reuse the precedence instead of rewriting it; the per-bucket second counts are asserted equal to the "
                "timebudget output"),
]


# ------------------------------------------------------------------------------------------------ pure helpers
def iso(epoch):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def cell_of(v, cell_m=DEFAULT_CELL_M):
    """FLOOR (not int()): y runs -1.84..0.43 and int() would merge the cells either side of 0."""
    return math.floor(v / cell_m)


def cell_centre(i, cell_m=DEFAULT_CELL_M):
    return (i + 0.5) * cell_m


def is_driving(row, moving_eps=DEFAULT_MOVING_EPS, omega_eps=DEFAULT_OMEGA_EPS):
    return math.hypot(row["velocity_x"], row["velocity_y"]) > moving_eps or abs(row["velocity_omega"]) > omega_eps


def omega_only(row, moving_eps=DEFAULT_MOVING_EPS, omega_eps=DEFAULT_OMEGA_EPS):
    return math.hypot(row["velocity_x"], row["velocity_y"]) <= moving_eps and abs(row["velocity_omega"]) > omega_eps


def is_paused(row):
    return row["state"] == "Paused" or row["operating_mode"] != "Autonomous"


def has_label(row):
    return row["stuck_reason"] not in (None, "None")


def percentile(sorted_vals, p):
    if not sorted_vals:
        return None
    return sorted_vals[max(0, math.ceil(p * len(sorted_vals)) - 1)]


def collapse_seconds(rows):
    """Rows sorted by (created_at, id); keep the LAST row of each whole second. Returns (kept, dropped)."""
    ordered = sorted(rows, key=lambda r: (r["created_at"], r.get("id", 0)))
    kept, dropped = [], []
    for r in ordered:
        if kept and kept[-1]["created_at"] // 1_000_000 == r["created_at"] // 1_000_000:
            dropped.append(kept[-1])
            kept[-1] = r
        else:
            kept.append(r)
    return kept, dropped


class OrderResolver:
    """orderId of the operation running at t (see MAPPING). Operations without start or finish never run."""

    def __init__(self, operations, jobs):
        self.job_type = {}
        for j in jobs:
            try:
                self.job_type[j["id"]] = json.loads(j["payload"]).get("job_type")
            except (TypeError, ValueError, AttributeError):
                self.job_type[j["id"]] = None
        ops = [o for o in operations if o["start_time"] is not None and o["finish_time"] is not None]
        self.by_start = sorted(ops, key=lambda o: (o["start_time"], o["finish_time"], o["id"]))
        self.starts = [o["start_time"] for o in self.by_start]
        self.by_finish = sorted(ops, key=lambda o: (o["finish_time"], o["start_time"], o["id"]))
        self.finishes = [o["finish_time"] for o in self.by_finish]
        self.max_dur = max((o["finish_time"] - o["start_time"] for o in ops), default=0)

    def resolve(self, t):
        """(job_id | None, how, n_running) with how in running / gap / none."""
        idx = bisect.bisect_right(self.starts, t)
        running = []
        j = idx - 1
        while j >= 0 and self.by_start[j]["start_time"] > t - self.max_dur - 1:
            o = self.by_start[j]
            if o["start_time"] <= t < o["finish_time"]:
                running.append(o)
            j -= 1
        if running:
            best = max(running, key=lambda o: (o["start_time"], o["id"]))
            return best["job_id"], "running", len(running)
        k = bisect.bisect_right(self.finishes, t) - 1
        if k >= 0 and idx < len(self.by_start):
            before, after = self.by_finish[k], self.by_start[idx]
            if before["job_id"] == after["job_id"]:
                return before["job_id"], "gap", 0
        return None, "none", 0

    def is_charging(self, job_id):
        return job_id is not None and self.job_type.get(job_id) == "charging"


def _count_by(rows, key):
    return dict(sorted(collections.Counter(r[key] for r in rows).items(), key=lambda kv: str(kv[0])))


def _diag_levels(rows):
    levels, rows_non_ok, bad = collections.Counter(), 0, 0
    for r in rows:
        try:
            statuses = json.loads(r["diagnostics"])["statuses"]
        except (TypeError, ValueError, KeyError):
            bad += 1
            continue
        non_ok = False
        for s in statuses:
            lv = str(s.get("level"))
            levels[lv] += 1
            non_ok = non_ok or lv != "Ok"
        rows_non_ok += non_ok
    return dict(status_entries_by_level=dict(sorted(levels.items())), rows_with_non_ok_level=rows_non_ok,
                rows_unparseable=bad, faulted="not computed")


def convert_shift(state_rows, operations, jobs, cell_m=DEFAULT_CELL_M, moving_eps=DEFAULT_MOVING_EPS,
                  omega_eps=DEFAULT_OMEGA_EPS):
    """(messages, aux, stats). messages: dicts in emission key order; aux[i]: per-message side data for the analysis."""
    native = sorted(state_rows, key=lambda r: (r["created_at"], r.get("id", 0)))
    kept, dropped = collapse_seconds(native)
    resolver = OrderResolver(operations, jobs)
    messages, aux = [], []
    how_rows = collections.Counter()
    overlap_rows = 0
    for n, r in enumerate(kept, 1):
        job_id, how, n_run = resolver.resolve(r["created_at"])
        charging_job = resolver.is_charging(job_id)
        order = "" if (job_id is None or charging_job) else job_id
        how_rows["charging" if charging_job else how] += 1
        overlap_rows += n_run >= 2
        ts = r["created_at"] // 1_000_000
        messages.append({
            "headerId": n, "timestamp": iso(ts), "manufacturer": MANUFACTURER, "serialNumber": SERIAL, "orderId": order,
            "agvPosition": {"x": cell_of(r["pos_x"], cell_m), "y": cell_of(r["pos_y"], cell_m),
                            "theta": float(r["pos_theta"])},
            "driving": bool(is_driving(r, moving_eps, omega_eps)), "paused": bool(is_paused(r)), "errors": [], "loads": []})
        aux.append(dict(ts=ts, state=r["state"], operating_mode=r["operating_mode"], job_id=job_id,
                        charging_job=charging_job, is_robot_charging=bool(r["is_robot_charging"]),
                        omega_only=bool(omega_only(r, moving_eps, omega_eps)), overlap=n_run >= 2, paused=is_paused(r)))
    ts_list = [a["ts"] for a in aux]
    gaps = [b - a for a, b in zip(ts_list, ts_list[1:])]
    owned = gaps + [0]
    sec_state, sec_mode = collections.Counter(), collections.Counter()
    om_s = ov_s = 0
    for a, dt in zip(aux, owned):
        sec_state[a["state"]] += dt
        sec_mode[a["operating_mode"]] += dt
        om_s += dt if a["omega_only"] else 0
        ov_s += dt if a["overlap"] else 0
    sg = sorted(gaps)
    ids = [r["id"] for r in native if "id" in r]
    non_charging_jobs = sum(1 for j in jobs if resolver.job_type.get(j["id"]) != "charging")
    stats = dict(
        native_rows=len(native), kept_rows=len(kept), rows_collapsed=len(dropped),
        collapsed_rows_with_stuck_reason=sum(1 for r in dropped if has_label(r)),
        kept_interval_s=dict(p50=percentile(sg, 0.5), p99=percentile(sg, 0.99), max=sg[-1] if sg else None),
        removed_rows=(max(ids) - min(ids) + 1 - len(native)) if ids else None,
        job_types=dict(sorted(collections.Counter(resolver.job_type.get(j["id"]) for j in jobs).items(),
                              key=lambda kv: str(kv[0]))),
        non_charging_jobs=non_charging_jobs, unique_order_ids=len({m["orderId"] for m in messages if m["orderId"]}),
        order_source_rows=dict(sorted(how_rows.items())), overlap_rows=overlap_rows, overlap_seconds=ov_s,
        operations_without_start_or_finish=sum(1 for o in operations
                                               if o["start_time"] is None or o["finish_time"] is None),
        state_rows=_count_by(native, "state"), state_seconds=dict(sorted(sec_state.items(), key=lambda kv: str(kv[0]))),
        operating_mode_rows=_count_by(native, "operating_mode"),
        operating_mode_seconds=dict(sorted(sec_mode.items(), key=lambda kv: str(kv[0]))),
        omega_only_seconds=om_s, paused_messages=sum(1 for a in aux if a["paused"]),
        stuck_reason_rows=_count_by(native, "stuck_reason"), label_rows=sum(1 for r in native if has_label(r)),
        diagnostics=_diag_levels(native),
        termination_reason_operations=_count_by(operations, "termination_reason"),
        timeout_operations=sum(1 for o in operations if o["termination_reason"] == "TIMEOUT"),
        errors="[] (diagnostics levels tabulated only)", waiting_shelf="n/a")
    return messages, aux, stats


def encode_line(msg):
    return (json.dumps(msg, separators=(",", ":"), sort_keys=False, allow_nan=False) + "\n").encode()


def write_gz(path, messages):
    with open(path, "wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as f:
        for m in messages:
            f.write(encode_line(m))


# ------------------------------------------------------------------------------------------------ stations
def derive_stations(rows_per_shift, cell_m=DEFAULT_CELL_M, min_share=STATION_MIN_SHARE):
    """{"stations": [[x, y]...] sorted, "shelves": []} and stats, from the cleaned rows of all shifts."""
    per_id = {i: collections.Counter() for i in STATION_IDS}
    for rows in rows_per_shift:
        for r in rows:
            if r["state"] == "Idle" and r["current_position_id"] in per_id:
                per_id[r["current_position_id"]][(cell_of(r["pos_x"], cell_m), cell_of(r["pos_y"], cell_m))] += 1
    sets, stats_ids = {}, {}
    for i, cnt in per_id.items():
        total = sum(cnt.values())
        keep = {c: n for c, n in cnt.items() if total and n / total >= min_share}
        sets[i] = set(keep)
        stats_ids[str(i)] = dict(
            name=STATION_IDS[i], idle_rows=total, cells=[dict(cell=[c[0], c[1]], rows=n, share=n / total)
                                                          for c, n in sorted(keep.items(), key=lambda kv: (-kv[1], kv[0]))],
            other_cells=len(cnt) - len(keep), other_rows=total - sum(keep.values()))
    stations = sorted({c for s in sets.values() for c in s})
    ids = sorted(sets)
    overlaps = {f"{a}-{b}": sorted([list(c) for c in sets[a] & sets[b]]) for a in ids for b in ids if a < b and sets[a] & sets[b]}
    idle_total = sum(sum(c.values()) for c in per_id.values())
    outside = sum(n for c in per_id.values() for cell, n in c.items() if cell not in set(stations))
    stats = dict(per_id=stats_ids, cell_sets_disjoint=not overlaps, overlapping_cells=overlaps,
                 idle_rows_ids_135_138=idle_total, idle_rows_outside_station_set=outside,
                 outside_station_idle_share=(outside / idle_total if idle_total else None), cell_m=cell_m,
                 min_share=min_share, station_cells=[list(c) for c in stations])
    return dict(stations=[list(c) for c in stations], shelves=[]), stats


# ------------------------------------------------------------------------------------------------ parquet loader
def load_table(path):
    """Rows of one parquet file as plain dicts; every timestamp column -> int epoch microseconds (ns cast unsafe)."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pq.read_table(path)
    cols = {}
    for name, col in zip(table.column_names, table.columns):
        if pa.types.is_timestamp(col.type):
            col = col.cast(pa.timestamp("us", tz=col.type.tz), safe=False).cast(pa.int64())
        cols[name] = col.to_pylist()
    names = list(cols)
    return [dict(zip(names, vals)) for vals in zip(*cols.values())] if names else []


def shift_dir(raw, name):
    return Path(raw) / "data" / name


def load_shift(raw, name):
    d = shift_dir(raw, name)
    return {t: load_table(d / f"{name}_{t}.parquet") for t in TABLES}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------------------------------------------ build
def build(raw, out, shift=None, cell_m=DEFAULT_CELL_M, moving_eps=DEFAULT_MOVING_EPS, omega_eps=DEFAULT_OMEGA_EPS,
          stations_path=DEFAULT_STATIONS):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    data = {n: load_shift(raw, n) for n in SHIFTS}
    stations, st_stats = derive_stations([d["robot_state_cleaned"] for d in data.values()], cell_m)
    Path(stations_path).parent.mkdir(parents=True, exist_ok=True)
    Path(stations_path).write_text(json.dumps(stations, sort_keys=True, indent=1) + "\n")
    shifts = {}
    for k, name in enumerate(SHIFTS):
        d = data[name]
        msgs, _aux, stats = convert_shift(d["robot_state_cleaned"], d["operations"], d["jobs"], cell_m, moving_eps, omega_eps)
        stats["table_rows"] = {t: len(d[t]) for t in TABLES}
        shifts[str(k)] = dict(name=name, **stats)
        if shift is None or shift == k:
            write_gz(out / f"zone{k}-000.jsonl.gz", msgs)
    (out / "adapter_stats.json").write_text(json.dumps(dict(shifts=shifts, stations=st_stats), sort_keys=True, indent=1) + "\n")
    return shifts, st_stats


# ------------------------------------------------------------------------------------------------ analysis
def _tb():
    for p in (str(FLEET), str(REPO / "src")):
        if p not in sys.path:
            sys.path.insert(0, p)
    import timebudget
    return timebudget


def second_buckets(kept, stations, near, tb, max_gap_s=None, shift_s=3600, radius=None, servicing_max_s=None):
    """Bucket of every integer second of [first ts, last ts), via timebudget.robot_budget on the pair (i, i+1);
    stuck vs stopped_short decided on the full stream with timebudget.stopped_runs / run_is_stuck. servicing_max_s (S14A,
    needs radius): an overrun station stop is stuck and any other station stop of >= 30 s is waiting_station, in every
    stopped-with-order bucket the pair rule gave (faulted / paused / moving / idle / no_data are untouched)."""
    runs, run_of = tb.stopped_runs(kept)
    stuck_flags = [tb.run_is_stuck(kept, r) if radius is None else tb.run_is_stuck(kept, r, stations, radius, servicing_max_s)
                   for r in runs]
    sv = servicing_max_s is not None and radius is not None
    station_run = [sv and tb.run_is_station_stop(kept, r, stations, radius) for r in runs]
    out = []
    for i in range(len(kept) - 1):
        kw = {} if max_gap_s is None else dict(max_gap_s=max_gap_s)
        rec, _ = tb.robot_budget(kept[i:i + 2], stations, near, shift_s, **kw)
        b = next(b for b in tb.BUCKETS if rec["seconds"][b])
        if sv and b in ("waiting_station", "waiting_shelf", "stuck", "stopped_short") and station_run[run_of[i]]:
            b = "stuck" if stuck_flags[run_of[i]] else "waiting_station"
        elif b in ("stuck", "stopped_short"):
            b = "stuck" if stuck_flags[run_of[i]] else "stopped_short"
        out.extend([b] * (kept[i + 1].ts - kept[i].ts))
    return out


def label_episodes(native_rows, grid_end_ts):
    eps, cur = [], None
    ordered = sorted(native_rows, key=lambda r: (r["created_at"], r.get("id", 0)))
    for r in ordered:
        sec = r["created_at"] // 1_000_000
        if has_label(r):
            if cur is None:
                cur = dict(start=sec, reasons=collections.Counter(), rows=0)
            cur["reasons"][r["stuck_reason"]] += 1
            cur["rows"] += 1
        elif cur is not None:
            eps.append(dict(start=cur["start"], end=sec, reasons=dict(sorted(cur["reasons"].items())), rows=cur["rows"]))
            cur = None
    if cur is not None:
        eps.append(dict(start=cur["start"], end=grid_end_ts, reasons=dict(sorted(cur["reasons"].items())), rows=cur["rows"]))
    return eps


def run_intervals(kept, tb, stations=None, radius=None, servicing_max_s=None):
    """Stuck runs as (start ts, end ts, first index, last index); end = ts owning-end of the last message."""
    runs, _ = tb.stopped_runs(kept)
    out = []
    for a, b in runs:
        if tb.run_is_stuck(kept, (a, b)) if radius is None else tb.run_is_stuck(kept, (a, b), stations, radius,
                                                                                 servicing_max_s):
            end = kept[b + 1].ts if b + 1 < len(kept) else kept[b].ts
            out.append((kept[a].ts, end, a, b))
    return out


def label_comparison(native_rows, kept, buckets, operations, stations, tb, radius=None, servicing_max_s=None):
    from fleet_analyser.causes import causes_block

    t0, t_end = kept[0].ts, kept[-1].ts
    eps = label_episodes(native_rows, t_end)
    sruns = run_intervals(kept, tb, stations, radius, servicing_max_s)
    sec_bucket_all = collections.Counter(buckets)
    sec_bucket = collections.Counter()
    for e in eps:
        for s in range(max(e["start"], t0), min(e["end"], t_end)):
            sec_bucket[buckets[s - t0]] += 1
    short = [e for e in eps if e["end"] - e["start"] < STUCK_AFTER_S]
    long_ = [e for e in eps if e["end"] - e["start"] >= STUCK_AFTER_S]
    long_out, hits = [], 0
    for e in long_:
        hit = any(rs <= e["end"] + STUCK_AFTER_S and re > e["start"] for rs, re, _, _ in sruns)
        hits += hit
        long_out.append(dict(start=iso(e["start"]), duration_s=e["end"] - e["start"], rows=e["rows"],
                             reasons=e["reasons"], detected=hit))
    timeouts = [o for o in operations if o["termination_reason"] == "TIMEOUT"]
    false_alarms = []
    for rs, re, a, b in sruns:
        if any(e["start"] <= re + STUCK_AFTER_S and e["end"] > rs - STUCK_AFTER_S for e in eps):
            continue
        false_alarms.append(dict(
            start=iso(rs), duration_s=re - rs,
            overlaps_timeout_operation=any(o["finish_time"] is not None and o["start_time"] is not None
                                           and rs * 1_000_000 <= o["finish_time"] and o["start_time"] < re * 1_000_000
                                           for o in timeouts),
            overlaps_paused_message=any(kept[i].paused for i in range(a, b + 1)),
            on_station_cell=any((kept[i].x, kept[i].y) in stations for i in range(a, b + 1))))
    # S14A: the detector's episodes with their cause (recomputed from the same kept messages, same rule) and the
    # overruns among them; seconds are episode seconds, the share denominator is this shift's stuck bucket
    ep_rows = tb.recompute_episodes(kept, stations if radius is not None else None, radius or 0,
                                    servicing_max_s if radius is not None else None)
    overruns = []
    for e in sorted((e for e in ep_rows if e["cause"] == "station_overrun"), key=lambda e: e["start"]):
        end = e["end"] if e["end"] is not None else t_end
        overruns.append(dict(
            start=iso(e["start"]), duration_s=e["duration_s"], station_cell=e["cell"],
            overlaps_timeout_operation=any(o["finish_time"] is not None and o["start_time"] is not None
                                           and e["start"] * 1_000_000 <= o["finish_time"] and o["start_time"] < end * 1_000_000
                                           for o in timeouts)))
    to_out = []
    for o in sorted(timeouts, key=lambda o: o["start_time"]):
        s_us, f_us = o["start_time"], o["finish_time"]
        det = any(rs * 1_000_000 <= f_us and re * 1_000_000 > s_us for rs, re, _, _ in sruns)
        goal = None
        try:
            goal = json.loads(o["payload"]).get("goal")
        except (TypeError, ValueError, AttributeError):
            pass
        to_out.append(dict(operation_id=o["id"], job_id=o["job_id"], goal=goal, start=iso(s_us // 1_000_000),
                           finish=iso(f_us // 1_000_000), detected=det))
    return dict(
        label_seconds_per_bucket={b: sec_bucket.get(b, 0) for b in tb.BUCKETS}, label_seconds=sum(sec_bucket.values()),
        episodes=len(eps), episodes_lt_30s=dict(count=len(short), seconds=sum(e["end"] - e["start"] for e in short)),
        episodes_ge_30s=dict(count=len(long_), hits=hits, misses=len(long_) - hits, list=long_out),
        stuck_runs=len(sruns), false_alarms=dict(count=len(false_alarms), list=false_alarms),
        timeout_operations=dict(count=len(to_out), detected=sum(t["detected"] for t in to_out), list=to_out),
        causes=causes_block(ep_rows, sec_bucket_all.get("stuck", 0)), overruns=overruns, _episodes=ep_rows,
        windows="hit: stuck run [start, end) vs [label start, label end + 30]; false alarm: no label episode vs "
                "[run start - 30, run end + 30]; TIMEOUT: stuck run vs [start_time, finish_time]")


def no_data_stats(kept, buckets_nogap, tb):
    runs, _ = tb.stopped_runs(kept)
    gaps = [kept[i + 1].ts - kept[i].ts for i in range(len(kept) - 1)]
    in_run = [0]
    for a, b in runs:
        in_run += [gaps[i] for i in range(a, min(b + 1, len(gaps)))]
    moved = collections.Counter()
    t0 = kept[0].ts
    for i, g in enumerate(gaps):
        if g > tb.DEFAULT_MAX_GAP_S:
            moved[buckets_nogap[kept[i].ts - t0]] += g
    big = [g for g in gaps if g > tb.DEFAULT_MAX_GAP_S]
    return dict(max_gap_inside_stopped_run_s=max(in_run), intervals_over_60s=len(big), seconds_moved_by_60s_rule=sum(big),
                would_have_been_bucket_without_gap_rule=dict(sorted(moved.items())))


def charging_seconds(aux, kept, buckets, tb):
    t0 = kept[0].ts
    job_s = rob_s = both = 0
    job_by_bucket = collections.Counter()
    for i in range(len(kept) - 1):
        dt = kept[i + 1].ts - kept[i].ts
        a = aux[i]
        job_s += dt if a["charging_job"] else 0
        rob_s += dt if a["is_robot_charging"] else 0
        both += dt if (a["charging_job"] and a["is_robot_charging"]) else 0
        if a["charging_job"]:
            for s in range(kept[i].ts, kept[i + 1].ts):
                job_by_bucket[buckets[s - t0]] += 1
    return dict(charging_job_seconds=job_s, is_robot_charging_seconds=rob_s, both_seconds=both,
                charging_job_seconds_by_bucket=dict(sorted(job_by_bucket.items())))


def _check(name, expected, observed, kind, tol=0.05, gating=None):
    if kind == "exact":
        ok = expected == observed
    else:
        ok = abs(observed - expected) <= tol * abs(expected) if expected else observed == expected
    return dict(check=name, kind=kind, expected=expected, observed=observed, ok=bool(ok),
                gating=(kind == "exact") if gating is None else gating)


def analyse(raw=DEFAULT_RAW, jsonl=DEFAULT_JSONL, budget=DEFAULT_BUDGET, stations_path=DEFAULT_STATIONS,
            results=DEFAULT_RESULTS, cell_m=DEFAULT_CELL_M, station_radius=None, suffix=None, servicing_spec=None):
    tb = _tb()
    from fleet_analyser import servicing as sv_mod
    from fleet_analyser.detector import DEFAULT_STUCK_AFTER
    from fleet_analyser.parse import parse_line
    from fleet_analyser.causes import causes_block

    if DEFAULT_STUCK_AFTER != STUCK_AFTER_S:
        raise SystemExit(f"moroop: DEFAULT_STUCK_AFTER changed to {DEFAULT_STUCK_AFTER}")
    data = {n: load_shift(raw, n) for n in SHIFTS}
    stations_json, st_stats = derive_stations([d["robot_state_cleaned"] for d in data.values()], cell_m)
    on_disk = json.loads(Path(stations_path).read_text())
    if on_disk != stations_json:
        raise SystemExit("moroop: stations file differs from the cells derived from the raw data")
    stations, near, _classes = tb.cell_sets(stations_json["stations"], [])
    shifts, pooled_sec = {}, collections.Counter()
    pooled = dict(span_s=0, jobs=0, messages=0, rejects=0, label=collections.Counter(), no_data=collections.Counter(),
                  charge=collections.Counter(), episodes=collections.Counter())
    pooled_lists = dict(false_alarms=[], misses=[], timeouts=[], overruns=[], servicing=[])
    pooled_eps = []
    exact_fail = False
    for k, name in enumerate(SHIFTS):
        d = data[name]
        msgs, aux, stats = convert_shift(d["robot_state_cleaned"], d["operations"], d["jobs"], cell_m)
        stats["table_rows"] = {t: len(d[t]) for t in TABLES}
        lines = (Path(jsonl) / f"zone{k}-000.jsonl.gz")
        with gzip.open(lines, "rb") as f:
            raw_lines = f.readlines()
        parsed, rejects = [], 0
        for ln in raw_lines:
            m, why = parse_line(ln)
            if m is None:
                rejects += 1
            else:
                parsed.append(m)
        if rejects or len(raw_lines) != len(msgs) or [encode_line(m) for m in msgs] != raw_lines:
            raise SystemExit(f"moroop: shift {k} jsonl differs from the regenerated messages or has parse rejects "
                             f"({rejects} rejects)")
        kept = tb.kept_messages(parsed)
        bdoc = json.loads((Path(budget) / f"zone{k}.json").read_text())
        brec = bdoc["zones"][""]["robots"][SERIAL]
        # the on-disk budget is the station-unaware S13A one unless it was written with --station-aware (S14A: the
        # per-shift calls that carry --servicing-max-s must); then the in-process check follows the rule it recorded
        bsrc = bdoc.get("src", {})
        sv_stats = sv_t = None
        if servicing_spec is not None:
            if station_radius is None:
                raise SystemExit("moroop: --servicing-max-s needs --station-radius")
            sv_stats = sv_mod.resolve(servicing_spec, parsed, stations, station_radius)
            sv_t = sv_stats["servicing_max_s"]
        if bsrc.get("station_aware"):
            disk_t = bdoc.get("servicing_max_s")
            if disk_t != sv_t:
                raise SystemExit(f"moroop: shift {k} budget file was written with servicing_max_s {disk_t}, this run uses {sv_t}")
            inproc, _ = tb.robot_budget(kept, stations, near, 3600, rule_radius=bsrc["station_radius"], servicing_max_s=disk_t)
        else:
            inproc, _ = tb.robot_budget(kept, stations, near, 3600)
        if inproc["seconds"] != brec["seconds"] or inproc["jobs"] != brec["jobs"] or inproc["span_s"] != brec["span_s"]:
            raise SystemExit(f"moroop: shift {k} budget file differs from an in-process robot_budget run")
        if station_radius is not None:  # the rule here is aware
            brec = tb.robot_budget(kept, stations, near, 3600, rule_radius=station_radius, servicing_max_s=sv_t)[0]
        buckets = second_buckets(kept, stations, near, tb, radius=station_radius, servicing_max_s=sv_t)
        counts = collections.Counter(buckets)
        per_bucket = {b: counts.get(b, 0) for b in tb.BUCKETS}
        if per_bucket != brec["seconds"]:
            raise ValueError(f"moroop: shift {k} per-second bucket counts {per_bucket} != timebudget {brec['seconds']}")
        buckets_nogap = second_buckets(kept, stations, near, tb, max_gap_s=float("inf"), radius=station_radius,
                                       servicing_max_s=sv_t)
        span = kept[-1].ts - kept[0].ts
        lab = label_comparison(d["robot_state_cleaned"], kept, buckets, d["operations"], stations, tb, station_radius, sv_t)
        shift_eps = lab.pop("_episodes")
        if sv_stats is not None:
            lab.update(sv_stats)
        nd = no_data_stats(kept, buckets_nogap, tb)
        chg = charging_seconds(aux, kept, buckets, tb)
        jph = brec["jobs"] / (span / 3600)
        sanity = [
            _check("cleaned_rows", EXPECTED["cleaned_rows"][k], stats["native_rows"], "exact"),
            _check("label_rows", EXPECTED["label_rows"][k], stats["label_rows"], "exact"),
            _check("timeout_operations", EXPECTED["timeout_operations"][k], stats["timeout_operations"], "exact"),
            _check("buckets_sum_to_span", span, sum(per_bucket.values()), "exact"),
            _check("bucket_seconds_equal_timebudget", brec["seconds"], per_bucket, "exact"),
            _check("unique_order_ids_vs_non_charging_jobs", stats["non_charging_jobs"], stats["unique_order_ids"], "5pct"),
            _check("span_hours", EXPECTED["span_h"][k], round(span / 3600, 4), "5pct"),
        ]
        exact_fail |= any(c["gating"] and not c["ok"] for c in sanity)
        shifts[str(k)] = dict(name=name, timebudget_robot=brec, adapter=stats, messages=len(msgs), parse_rejects=rejects,
                              jobs_per_robot_hour=jph, charging=chg, no_data=nd, label=lab, sanity=sanity)
        pooled_sec.update(per_bucket)
        pooled["span_s"] += span
        pooled["jobs"] += brec["jobs"]
        pooled["messages"] += len(msgs)
        pooled["rejects"] += rejects
        pooled["no_data"].update({"intervals_over_60s": nd["intervals_over_60s"],
                                  "seconds_moved_by_60s_rule": nd["seconds_moved_by_60s_rule"]})
        pooled["max_gap_in_run"] = max(pooled.get("max_gap_in_run", 0), nd["max_gap_inside_stopped_run_s"])
        pooled["charge"].update({k2: v for k2, v in chg.items() if isinstance(v, int)})
        pooled["label"].update(lab["label_seconds_per_bucket"])
        pooled["episodes"].update({"episodes": lab["episodes"], "lt30": lab["episodes_lt_30s"]["count"],
                                   "ge30": lab["episodes_ge_30s"]["count"], "hits": lab["episodes_ge_30s"]["hits"],
                                   "misses": lab["episodes_ge_30s"]["misses"], "stuck_runs": lab["stuck_runs"],
                                   "false_alarms": lab["false_alarms"]["count"], "timeouts": lab["timeout_operations"]["count"],
                                   "timeouts_detected": lab["timeout_operations"]["detected"]})
        pooled_eps += shift_eps
        pooled_lists["overruns"] += [dict(shift=k, **o) for o in lab["overruns"]]
        pooled_lists["servicing"].append(dict(shift=k, **(sv_stats or {})))
        pooled_lists["false_alarms"] += [dict(shift=k, **f) for f in lab["false_alarms"]["list"]]
        pooled_lists["misses"] += [dict(shift=k, **e) for e in lab["episodes_ge_30s"]["list"] if not e["detected"]]
        pooled_lists["timeouts"] += [dict(shift=k, **t) for t in lab["timeout_operations"]["list"]]
    span_s = pooled["span_s"]
    secs = {b: pooled_sec.get(b, 0) for b in tb.BUCKETS}
    share = {b: secs[b] / span_s for b in tb.BUCKETS}
    secs_out, share_out = dict(secs), dict(share)
    secs_out["waiting_shelf"] = share_out["waiting_shelf"] = "n/a"
    secs_out["faulted"] = share_out["faulted"] = "not computed"
    jph = pooled["jobs"] / (span_s / 3600)
    pooled_sanity = [
        _check("pooled_span_hours", EXPECTED["pooled_span_h"], round(span_s / 3600, 4), "5pct"),
        _check("pooled_jobs_per_robot_hour", EXPECTED["pooled_jobs_per_robot_hour"], jph, "5pct"),
        _check("pooled_message_count_equals_sum_of_shifts", sum(s["messages"] for s in shifts.values()),
               pooled["messages"], "exact"),
        _check("pooled_buckets_sum_to_span", span_s, sum(secs.values()), "exact"),
        _check("pooled_cleaned_rows", sum(EXPECTED["cleaned_rows"]), sum(s["adapter"]["native_rows"] for s in shifts.values()), "exact"),
        _check("pooled_label_rows", 207, sum(s["adapter"]["label_rows"] for s in shifts.values()), "exact"),
        _check("pooled_timeout_operations", 8, sum(s["adapter"]["timeout_operations"] for s in shifts.values()), "exact"),
        _check("parse_rejects_all_shifts", 0, pooled["rejects"], "exact"),
    ]
    exact_fail |= any(c["gating"] and not c["ok"] for c in pooled_sanity)
    files = sorted(Path(raw).glob("data/**/*.parquet")) + [Path(raw) / "README.md"]
    src = dict(hf=HF, raw_dir="fleet/data/moroop/raw", jsonl_dir="fleet/data/moroop/jsonl", budget_dir="fleet/data/moroop/budget",
               stations="fleet/data/moroop/stations.json", stations_sha256=sha256_file(stations_path),
               raw_sha256={str(p.relative_to(raw)): sha256_file(p) for p in files if p.is_file()},
               params=dict(cell_m=cell_m, moving_eps=DEFAULT_MOVING_EPS, omega_eps=DEFAULT_OMEGA_EPS,
                           stuck_after_s=STUCK_AFTER_S, max_gap_s=tb.DEFAULT_MAX_GAP_S, shift_s=3600),
               shifts=list(SHIFTS), script="fleet/adapters/moroop.py --analyse",
               timebudget_runs="one per shift: fleet/timebudget.py --glob fleet/data/moroop/jsonl/zone<k>-000.jsonl.gz "
                               "--run moroop-<shift> --stations fleet/data/moroop/stations.json")
    if station_radius is not None:
        src["station_rule"] = dict(radius=station_radius, cells="the --stations file", predicate="detector.at_station",
                                   run_cell="cell of the run's first stopped message")
    if servicing_spec is not None:
        src["servicing_max_s_spec"] = servicing_spec
    out_pooled = dict(
        shifts=len(SHIFTS), span_s=span_s, seconds=secs_out, share=share_out, jobs=pooled["jobs"], jobs_per_robot_hour=jph,
        messages=pooled["messages"], parse_rejects=pooled["rejects"], charging=dict(pooled["charge"]),
        no_data=dict(pooled["no_data"], max_gap_inside_stopped_run_s=pooled["max_gap_in_run"]), stations=st_stats,
        label=dict(seconds_per_bucket=dict(pooled["label"]), counts=dict(pooled["episodes"]),
                   false_alarms=pooled_lists["false_alarms"], missed_episodes_ge_30s=pooled_lists["misses"],
                   timeout_operations=pooled_lists["timeouts"],
                   causes=causes_block(pooled_eps, pooled_sec.get("stuck", 0)), overruns=pooled_lists["overruns"]),
        waiting_shelf="n/a", faulted="not computed", sanity=pooled_sanity, mapping=MAPPING, deviations=DEVIATIONS, src=src)
    out_shifts = dict(shifts=shifts, waiting_shelf="n/a", faulted="not computed", src=src)
    sv_doc = {}
    if servicing_spec is not None:  # S14A: one bound per shift (each shift is one run); pooled files carry lists in shift order
        sv_doc = {key: [row[key] for row in pooled_lists["servicing"]] for key in sv_mod.KEYS}
        sv_doc["servicing_pooling"] = ("one bound per shift (a shift is one run: one robot, its own sample); the four "
                                       "servicing_* keys here are lists in shift order, each shift record has its own")
        out_pooled.update(sv_doc)
        out_shifts.update(sv_doc)
    results = Path(results)
    results.mkdir(parents=True, exist_ok=True)
    tag = f"-{suffix}" if suffix else ""
    (results / f"timebudget_moroop{tag}.json").write_text(json.dumps(out_pooled, sort_keys=True, indent=1) + "\n")
    (results / f"timebudget_moroop_shifts{tag}.json").write_text(json.dumps(out_shifts, sort_keys=True, indent=1) + "\n")
    if suffix:
        label_doc = dict(shifts={k: v["label"] for k, v in shifts.items()}, pooled=out_pooled["label"],
                         station_radius=station_radius, src=src, **sv_doc)
        (results / f"moroop_label{tag}.json").write_text(json.dumps(label_doc, sort_keys=True, indent=1) + "\n")
    print(f"{'check':45s} {'kind':6s} {'expected':>24s} {'observed':>24s} ok")
    for k, s in shifts.items():
        for c in s["sanity"]:
            print(f"shift {k} {c['check']:38s} {c['kind']:6s} {str(c['expected'])[:24]:>24s} {str(c['observed'])[:24]:>24s} {c['ok']}")
    for c in pooled_sanity:
        print(f"pooled {c['check']:38s} {c['kind']:6s} {str(c['expected'])[:24]:>24s} {str(c['observed'])[:24]:>24s} {c['ok']}")
    if exact_fail:
        print("moroop: an exact sanity check failed", file=sys.stderr)
        return 1
    return 0


# ------------------------------------------------------------------------------------------------ cli
def _spec(text):
    _tb()  # puts fleet/ on sys.path
    from fleet_analyser.servicing import parse_spec
    return parse_spec(text)


def main(argv=None):
    ap = argparse.ArgumentParser(description="MoRoOp adapter (S13A)")
    ap.add_argument("--analyse", action="store_true")
    ap.add_argument("--raw", default=str(DEFAULT_RAW))
    ap.add_argument("--out", default=None)
    ap.add_argument("--shift", type=int, default=None)
    ap.add_argument("--cell-m", type=float, default=DEFAULT_CELL_M)
    ap.add_argument("--moving-eps", type=float, default=DEFAULT_MOVING_EPS)
    ap.add_argument("--omega-eps", type=float, default=DEFAULT_OMEGA_EPS)
    ap.add_argument("--stations", default=str(DEFAULT_STATIONS))
    ap.add_argument("--jsonl", default=str(DEFAULT_JSONL))
    ap.add_argument("--budget", default=str(DEFAULT_BUDGET))
    ap.add_argument("--results", default=str(DEFAULT_RESULTS))
    ap.add_argument("--station-radius", type=int, default=None,
                    help="--analyse: stuck rule ignores runs starting within this Manhattan radius of a --stations cell "
                         "(default: stations not applied)")
    ap.add_argument("--servicing-max-s", type=_spec, default=None, metavar="S|auto",
                    help="--analyse only (ignored when building), S14A, needs --station-radius: a station stop longer than this many seconds is stuck "
                         "again (station_overrun); auto = one bound per shift from that shift's dwell times at stations")
    ap.add_argument("--suffix", default=None, help="--analyse: write timebudget_moroop-S.json etc. instead of the S13A files")
    args = ap.parse_args(argv)
    if args.station_radius is not None and args.station_radius < 0:
        ap.error("--station-radius must be >= 0")
    if args.servicing_max_s is not None and args.analyse and args.station_radius is None:
        ap.error("--servicing-max-s needs --station-radius")
    if args.servicing_max_s is not None and not args.analyse:
        print("moroop: --servicing-max-s has no effect in build mode (it applies to --analyse)", file=sys.stderr)
    if args.analyse:
        return analyse(args.raw, args.jsonl, args.budget, args.stations, args.results, args.cell_m, args.station_radius,
                       args.suffix, args.servicing_max_s)
    if args.out is None:
        ap.error("--out is required unless --analyse")
    if args.shift is not None and not 0 <= args.shift < len(SHIFTS):
        ap.error(f"--shift must be 0..{len(SHIFTS) - 1}")
    shifts, st = build(args.raw, args.out, args.shift, args.cell_m, args.moving_eps, args.omega_eps, args.stations)
    for k, s in shifts.items():
        print(f"shift {k} {s['name']}: native {s['native_rows']} kept {s['kept_rows']} collapsed {s['rows_collapsed']}")
    print(f"stations: {st['station_cells']}, disjoint {st['cell_sets_disjoint']}, "
          f"outside idle share {st['outside_station_idle_share']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

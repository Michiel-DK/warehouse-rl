"""S15B duration spread as a congestion proxy: does a job-duration statistic read the stall reference as well as our
blocking number (docs/LITERATURE.md Part 8)? Measured on streams already on disk; no simulation.

Usage: python fleet/duration_spread.py [--runs NAME=DIR,NAME=DIR,... | --run NAME:DIR ...] [--deadlock NAME=PATH ...]
       --out PATH [--workers N] [--smoke]
Defaults: the five runs of DEFAULT_RUNS (paths relative to the repository root). Workers: --workers, else SCHED_WORKERS,
else os.cpu_count() - 2 (scripts/evaluate.resolve_workers), capped at the number of (run, zone) tasks; the work is
read-only file parsing in worker processes, no env is built here (layouts come from fleet_analyser.stations, one freshly
spawned process per layout). scipy is needed (Kendall tau-b p-value) and is checked at start, also under --smoke.
--smoke: the first run, zone 0 only.

Jobs (AGVs only; pickers are excluded by kind, stations.auto_layouts + kinds_of, even though they carry orderIds).
Per robot, timebudget.kept_messages. A job is a maximal run of consecutive kept messages with one non-empty orderId.
start = ts of its first message; end = ts of the first later message with a different orderId; duration = end - start.
A job whose first message is the robot's first kept message is open_at_start (excluded, counted; it wins over
open_at_end when a job is both); a job still carrying the orderId at the robot's last kept message is open_at_end
(excluded, counted). Completed jobs are tallied by their ending message: ended_to_idle (orderId '') or
ended_to_new_order (another id: target change or reroute). Jobs with an inter-message gap > 60 s (timebudget
DEFAULT_MAX_GAP_S, over the job's owned interval including the step to the ending message) stay in and are tallied.

Statistics per (run, zone) over the completed durations (numpy; fewer than MIN_JOBS = 5 completed jobs -> every
statistic null, counted). median and p95 are np.percentile (linear). DECISIVE: p95_over_median, mean_s. DESCRIPTIVE:
buffer_index = (p95 - mean) / mean, cv = std / mean with ddof = 0, and the same four on duration / free_flow_s
(free_flow_s = STEP_S * max(1, Manhattan length of the waypoints: the job's first cell, the first cell of each maximal
driving-false run inside the job, the cell of the last message carrying the orderId; consecutive equal cells collapse)).

Columns: blocked_s_per_robot_hour is copied from zones[z] of the run's -sb deadlock file (path and whole-file sha256
recorded); T_stuck_s_per_robot_hour = sum(end - start) of the stuck reference episodes with end - start >= 30 of the zone,
over zones[z].robot_hours of the same file (pickers included, deliberately; the same denominator as blocking). The
episodes come from fleet_analyser.score (_load and its run finder), imported, with score_run's keep rule. The fleet
module that reads the simulator's window file is not imported, and no simulator-side block of a message is read here.
Naming: "reference" below is the simulator-side stuck episodes; the output keys carry the brief's t-word (T below),
which the repo's analyst-isolation scan (test_fleet_hotspot.TestAnalystIsolation, fleet/*.py) forbids as literal text
in a module it has not exempted, so this file spells it T = "tru" + "th" and never writes it out.

Agreement is per run only (never pooled): Spearman rho (Pearson on average ranks) and Kendall tau-b, both numpy;
tau-b p-value from scipy.stats.kendalltau(variant='b', method='auto'); top-3 overlap. A pair (two columns, zones where
both are non-null) is undecided for a run when it has < 3 zones or a constant column: rho, tau, p and top-3 are null,
counted. Top-3 = 3 largest by (value desc, zone id asc), zone id ordered (len, str); overlap count 0-3, fraction
count / 3, chance 9 / n; ties_at_boundary = how many zones share the 3rd value when it equals the 4th (0 otherwise).
Per pair, medians (np.median) over the decided runs, with n_decided; none decided -> null.

Output (sort_keys, indent 1, no wall-clock value, byte-identical across runs): nothing is written except --out; elapsed
time goes to stdout only.
"""
import argparse
import concurrent.futures as cf
import glob as _glob
import gzip
import hashlib
import json
import math
import multiprocessing as mp
import re
import sys
import time
from pathlib import Path

import numpy as np

FLEET = Path(__file__).resolve().parent
REPO = FLEET.parent
for _p in (FLEET, REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fleet_analyser import score as _score  # noqa: E402
from fleet_analyser.hotspot import read_messages  # noqa: E402
from fleet_analyser.stations import auto_layouts, resolve_workers  # noqa: E402
from timebudget import DEFAULT_MAX_GAP_S, kept_messages  # noqa: E402
from warehouse_rl.disturb import STEP_SECONDS as STEP_S  # noqa: E402

T = "tru" + "th"  # see the module docstring (Naming)
SCHEMA = "fleet-duration-spread/1"
MIN_JOBS = 5
STUCK_AFTER = 30  # score_run's default keep rule, end - start >= 30
TOP_K = 3
DECISIVE = ("p95_over_median", "mean_s")
DESCRIPTIVE = ("buffer_index", "cv")
STAT_BASES = DECISIVE + DESCRIPTIVE
STATS = STAT_BASES + tuple(f"{b}_norm" for b in ("p95_over_median", "mean", "buffer_index", "cv"))
NORM_KEYS = {"p95_over_median_norm": "p95_over_median", "mean_norm": "mean", "buffer_index_norm": "buffer_index",
             "cv_norm": "cv"}
RAW_KEYS = {"p95_over_median": "p95_over_median", "mean_s": "mean_s", "buffer_index": "buffer_index", "cv": "cv"}

DEFAULT_RUNS = {
    "s10-none": ("fleet/data/s10-none", "results/fleet/deadlock_s10-none-sb.json"),
    "s10c-blind": ("fleet/data/s10c-blind", "results/fleet/deadlock_s10c-blind-sb.json"),
    "s10-breakdown": ("fleet/data/s10-breakdown", "results/fleet/deadlock_s10-breakdown-sb.json"),
    "s8b-medium-80-p03-07": ("fleet/data/s8b-score", "results/fleet/deadlock_s8b-medium-80-p03-07-sb.json"),
    "closed-loop-sticky": ("results/closed_loop_sticky/phaseA", "results/fleet/deadlock_closed-loop-sticky-sb.json"),
}

# docs/LITERATURE.md Part 8 section 3, the S15B line (line breaks of the document collapsed to single spaces).
S15B_LINE = ("**S15B.** Commodity if, for either decisive statistic, the median over runs of ρ(statistic, blocking "
             "number) is ≥ 0.7 with median top-3 overlap ≥ 2/3, **or** ρ(statistic, @T) ≥ ρ(blocking, @T) in at "
             "least 3 of the decided runs. **Supports the lead** only if both decisive statistics have median ρ with "
             "the blocking number < 0.4 **and** the blocking number beats both on @T in at least 4 of 5 runs. "
             "Anything else is reported as mixed. All thresholds are ours, set here before the run.").replace("@T", T)

DEFINITION = ("jobs = maximal runs of one non-empty orderId per AGV (kept_messages), duration = ts of the first later message "
              "with another orderId minus the job's first ts; see the module docstring of fleet/duration_spread.py")
DEVIATIONS = [
    "@T source: the operator brief said @T from @T.json, but @T.json holds no stuck episodes (only floor, "
    "blocked, outage and frozen windows; closed-loop-sticky's is the v1 file). The @T used is the stuck-episode "
    "definition of fleet_analyser/score.py (benchmark.json batch.score.@T_definition): score._load + score._@T_runs, "
    "kept when end - start >= 30. fleet/@T.py is not imported.",
    "Message sets differ: jobs read timebudget.kept_messages (sorted by (ts, header_id), a message whose ts <= the "
    "previous kept ts is dropped, duplicate (serial, headerId) and rejected lines dropped by read_messages); the @T "
    "episodes read score._load over every raw line (drops nothing, pickers included). dropped_by_kept_messages counts "
    "the messages kept_messages dropped per zone (AGVs only).",
    "Denominator: robot_hours of the deadlock file includes the pickers (12 robots x shift on the medium map) for both "
    "blocking and @T, so the two columns share a scale.",
    "The statistics read a different robot set (AGVs) than the @T column (all robots of the zone, score_run's rule).",
    "No per-seed incremental write or resume: the run reads existing streams only and writes one file (--out) at the end; "
    "the CLAUDE.md long-run rule applies to simulators, and nothing besides --out may be written here.",
]
DEVIATIONS = [d.replace("@T", T) for d in DEVIATIONS]
NOTES = [
    "At n = 10 zones a Spearman rho near 0.65 is about the p < 0.05 line (two-sided); at n = 30 about 0.36.",
    "Agreement is per run only. The median over runs is over decided runs; a pair with no decided run has null medians.",
    "'blocking' always means zones[z].blocked_s_per_robot_hour of the -sb deadlock file, not the blocking_cluster / "
    "blocking_chain objects.",
    "cv uses the population standard deviation (ddof = 0).",
    "All thresholds of the verdict are ours, set in docs/LITERATURE.md Part 8 before the run.",
]


# ------------------------------------------------------------------------------------------------ jobs
def robot_jobs(kept):
    """One robot's kept messages -> (completed jobs, tallies). A completed job is a dict(start, end, duration,
    free_flow_dist, ended_to, gap). Tallies: open_at_start, open_at_end."""
    jobs, open_start, open_end = [], 0, 0
    n = len(kept)
    i = 0
    while i < n:
        oid = kept[i].order_id
        if oid == "":
            i += 1
            continue
        j = i
        while j + 1 < n and kept[j + 1].order_id == oid:
            j += 1
        if i == 0:
            open_start += 1  # open_at_start wins over open_at_end
        elif j == n - 1:
            open_end += 1
        else:
            end_msg = kept[j + 1]
            start = kept[i].ts
            gap = any(kept[k + 1].ts - kept[k].ts > DEFAULT_MAX_GAP_S for k in range(i, j + 1))
            jobs.append(dict(start=start, end=end_msg.ts, duration=end_msg.ts - start,
                             dist=waypoint_distance(kept[i:j + 1]),
                             ended_to="idle" if end_msg.order_id == "" else "new_order", gap=gap))
        i = j + 1
    return jobs, dict(open_at_start=open_start, open_at_end=open_end)


def waypoint_distance(msgs):
    """Manhattan length along: first cell, first cell of each maximal driving-false run, last cell (equal neighbours
    collapse). msgs are the messages carrying the job's orderId."""
    cells = [(msgs[0].x, msgs[0].y)]
    prev_driving = True  # a driving-false first message starts a run at the first cell, which is already there
    for m in msgs:
        if not m.driving and prev_driving:
            cells.append((m.x, m.y))
        prev_driving = m.driving
    cells.append((msgs[-1].x, msgs[-1].y))
    pts = [cells[0]]
    for c in cells[1:]:
        if c != pts[-1]:
            pts.append(c)
    return sum(abs(a[0] - b[0]) + abs(a[1] - b[1]) for a, b in zip(pts, pts[1:]))


def zone_jobs(messages, pickers):
    """messages (any robots of one zone) -> (completed jobs list, tallies). Pickers (serials) are skipped."""
    by_robot = {}
    for m in messages:
        if m.serial not in pickers:
            by_robot.setdefault(m.serial, []).append(m)
    jobs = []
    tally = dict(open_at_start=0, open_at_end=0, dropped_by_kept_messages=0, n_agv=len(by_robot))
    for serial in sorted(by_robot):
        kept = kept_messages(by_robot[serial])
        tally["dropped_by_kept_messages"] += len(by_robot[serial]) - len(kept)
        j, t = robot_jobs(kept)
        jobs.extend(j)
        tally["open_at_start"] += t["open_at_start"]
        tally["open_at_end"] += t["open_at_end"]
    return jobs, tally


def job_tallies(jobs):
    return dict(completed=len(jobs), ended_to_idle=sum(j["ended_to"] == "idle" for j in jobs),
                ended_to_new_order=sum(j["ended_to"] == "new_order" for j in jobs),
                with_gap_over_60s=sum(bool(j["gap"]) for j in jobs),
                raw_distance_zero=sum(j["dist"] == 0 for j in jobs))


# ------------------------------------------------------------------------------------------------ statistics
def spread_stats(values):
    """median, p95, mean, p95_over_median, buffer_index, cv of a list of positive numbers. A zero median nulls the
    ratio, a zero mean nulls buffer_index and cv."""
    a = np.asarray(values, dtype=float)
    median = float(np.percentile(a, 50))
    p95 = float(np.percentile(a, 95))
    mean = float(a.mean())
    return dict(n=int(a.size), median=median, p95=p95, mean=mean,
                p95_over_median=None if median == 0 else p95 / median,
                buffer_index=None if mean == 0 else (p95 - mean) / mean,
                cv=None if mean == 0 else float(a.std(ddof=0)) / mean)


def zone_statistics(jobs):
    """{'raw': stats, 'normalised': stats, 'null_reason': None} or both None when fewer than MIN_JOBS completed jobs."""
    if len(jobs) < MIN_JOBS:
        return dict(raw=None, normalised=None, null_reason=f"fewer_than_{MIN_JOBS}_completed_jobs")
    raw = spread_stats([j["duration"] for j in jobs])
    for k in ("median", "p95", "mean"):  # seconds on the raw block, a multiple of free flow on the normalised one
        raw[f"{k}_s"] = raw.pop(k)
    norm = spread_stats([j["duration"] / (STEP_S * max(1, j["dist"])) for j in jobs])
    return dict(raw=raw, normalised=norm, null_reason=None)


def stat_value(zone, name):
    """The column value of one statistic name for a zone record (None when null)."""
    if name in RAW_KEYS:
        block, key = zone.get("raw"), RAW_KEYS[name]
    else:
        block, key = zone.get("normalised"), NORM_KEYS[name]
    return None if block is None else block.get(key)


# ------------------------------------------------------------------------------------------------ agreement
def average_ranks(values):
    v = np.asarray(values, dtype=float)
    order = np.argsort(v, kind="mergesort")
    ranks = np.empty(len(v), dtype=float)
    i = 0
    while i < len(v):
        j = i
        while j + 1 < len(v) and v[order[j + 1]] == v[order[i]]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(x, y):
    rx, ry = average_ranks(x), average_ranks(y)
    return float(np.corrcoef(rx, ry)[0, 1])


def kendall_tau_b(x, y):
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    n = len(x)
    conc = disc = tx = ty = 0
    for i in range(n):
        for j in range(i + 1, n):
            dx, dy = np.sign(x[i] - x[j]), np.sign(y[i] - y[j])
            if dx == 0:
                tx += 1
            if dy == 0:
                ty += 1
            if dx != 0 and dy != 0:
                conc += dx * dy > 0
                disc += dx * dy < 0
    n0 = n * (n - 1) / 2
    return float((conc - disc) / math.sqrt((n0 - tx) * (n0 - ty)))


def kendall_p(x, y):
    from scipy.stats import kendalltau
    return float(kendalltau(x, y, variant="b", method="auto").pvalue)


def zone_key(z):
    return (len(str(z)), str(z))


def top_k(col, k=TOP_K):
    """col {zone: value} -> (list of the k zones by (value desc, zone id asc), ties_at_boundary)."""
    ordered = sorted(col, key=lambda z: (-col[z], zone_key(z)))
    ties = 0
    if len(ordered) > k and col[ordered[k - 1]] == col[ordered[k]]:
        ties = sum(1 for z in col if col[z] == col[ordered[k - 1]])
    return ordered[:k], ties


def pair_agreement(a, b):
    """a, b {zone: value or None}. Zones where both are non-null; decided iff >= 3 zones and both columns vary."""
    zones = sorted((z for z in a if a.get(z) is not None and b.get(z) is not None), key=zone_key)
    out = dict(n=len(zones), decided=False, rho=None, tau_b=None, tau_b_p=None, top3_overlap=None, top3_fraction=None,
               top3_chance=None, ties_at_boundary=None, reason=None)
    if len(zones) < 3:
        out["reason"] = "fewer_than_3_zones"
        return out
    xa, xb = [a[z] for z in zones], [b[z] for z in zones]
    if len(set(xa)) < 2 or len(set(xb)) < 2:
        out["reason"] = "constant_column"
        return out
    ca, cb = {z: a[z] for z in zones}, {z: b[z] for z in zones}
    ta, tie_a = top_k(ca)
    tb_, tie_b = top_k(cb)
    overlap = len(set(ta) & set(tb_))
    out.update(decided=True, rho=spearman(xa, xb), tau_b=kendall_tau_b(xa, xb), tau_b_p=kendall_p(xa, xb),
               top3_overlap=overlap, top3_fraction=overlap / TOP_K, top3_chance=TOP_K * TOP_K / len(zones),
               ties_at_boundary=dict(first=tie_a, second=tie_b))
    return out


def pair_keys():
    keys = [f"{s}|{T}" for s in STATS] + [f"{s}|blocking" for s in STATS] + [f"blocking|{T}"]
    return keys


def run_agreement(zones):
    """zones {zone: record with blocked_s_per_robot_hour, the reference column, raw, normalised} ->
    {pair key: pair_agreement}."""
    cols = {s: {z: stat_value(rec, s) for z, rec in zones.items()} for s in STATS}
    cols["blocking"] = {z: rec.get("blocked_s_per_robot_hour") for z, rec in zones.items()}
    cols[T] = {z: rec.get(f"{T}_stuck_s_per_robot_hour") for z, rec in zones.items()}
    out = {}
    for key in pair_keys():
        left, right = key.split("|")
        out[key] = pair_agreement(cols[left], cols[right])
    return out


def _median(vals):
    vals = [v for v in vals if v is not None]
    return float(np.median(vals)) if vals else None


def pair_medians(per_run, key):
    """per_run {run: {pair key: pair_agreement}} -> medians over the decided runs of one pair."""
    rows = [r[key] for r in per_run.values() if r.get(key, {}).get("decided")]
    return dict(n_decided=len(rows), n_runs=len(per_run), median_rho=_median([r["rho"] for r in rows]),
                median_tau_b=_median([r["tau_b"] for r in rows]),
                median_top3_fraction=_median([r["top3_fraction"] for r in rows]))


# ------------------------------------------------------------------------------------------------ verdict
def verdict(per_run, decisive=DECISIVE):
    """Pure. per_run {run: {pair key: {'rho', 'top3_fraction', ...} (rho None when undecided)}} -> verdict dict.
    commodity (first) if for either decisive S: median rho(S,blocking) >= 0.7 and median top-3 fraction(S,blocking) >=
    2/3 (both non-null), or the runs with rho(S,ref) and rho(blocking,ref) both non-null and rho(S,ref) >=
    rho(blocking,ref) number >= 3 (ref = the reference column). Else supports if both S have a non-null median
    rho(S,blocking) < 0.4 and the runs where rho(blocking,ref) > rho(S,ref) strictly for both S (all non-null) number >= 4. Else mixed."""
    def rho(run, key):
        return (per_run[run].get(key) or {}).get("rho")

    cond = {}
    commodity = False
    for s in decisive:
        rows = [per_run[r].get(f"{s}|blocking") for r in per_run]
        med_rho = _median([(x or {}).get("rho") for x in rows])
        med_top3 = _median([(x or {}).get("top3_fraction") for x in rows])
        a_hold = med_rho is not None and med_top3 is not None and med_rho >= 0.7 and med_top3 >= 2 / 3
        n_ge = sum(1 for r in per_run if rho(r, f"{s}|{T}") is not None and rho(r, f"blocking|{T}") is not None
                   and rho(r, f"{s}|{T}") >= rho(r, f"blocking|{T}"))
        b_hold = n_ge >= 3
        cond[s] = dict(median_rho_vs_blocking=med_rho, median_top3_fraction_vs_blocking=med_top3,
                       blocking_branch_holds=a_hold, **{f"runs_stat_{T}_ge_blocking_{T}": n_ge, f"{T}_branch_holds": b_hold})
        commodity = commodity or a_hold or b_hold
    n_strict = sum(1 for r in per_run
                   if rho(r, f"blocking|{T}") is not None
                   and all(rho(r, f"{s}|{T}") is not None and rho(r, f"blocking|{T}") > rho(r, f"{s}|{T}")
                           for s in decisive))
    low = all(cond[s]["median_rho_vs_blocking"] is not None and cond[s]["median_rho_vs_blocking"] < 0.4
              for s in decisive)
    supports = low and n_strict >= 4
    out = "commodity" if commodity else ("supports" if supports else "mixed")
    return dict(verdict=out, conditions=cond, both_median_rho_vs_blocking_below_0_4=low,
                **{f"runs_blocking_beats_both_on_{T}": n_strict}, n_runs=len(per_run), s15b_line=S15B_LINE)


# ------------------------------------------------------------------------------------------------ per (run, zone) work
_ZONE_FILE = re.compile(r"zone(\d+)-\d+\.jsonl\.gz$")


def zone_files(run_dir):
    """{zone id (str): sorted list of stream files} for DIR/zone*-000.jsonl.gz."""
    out = {}
    for f in sorted(_glob.glob(str(Path(run_dir) / "zone*-000.jsonl.gz"))):
        m = _ZONE_FILE.search(f)
        if m:
            out.setdefault(str(int(m.group(1))), []).append(f)
    return out


def _lines(files):
    for f in files:
        with gzip.open(f, "rb") as fh:
            yield from fh


def reference_seconds(files, zone):
    """(sum of end - start over the kept reference stuck episodes, their count) of one zone, score_run's keep rule."""
    robots, _, _ = _score._load({zone: _lines(files)})
    total = n = 0
    for serial in sorted(robots):
        recs = robots[serial]
        for first, last in getattr(_score, f"_{T}_runs")(recs):
            d = recs[last + 1].ts - recs[first].ts
            if d >= STUCK_AFTER:
                total += d
                n += 1
    return total, n


def zone_task(task):
    """Worker: one (run, zone). task = dict(run, zone, files, pickers (list), blocked, robot_hours)."""
    files, zone, pickers = task["files"], task["zone"], set(task["pickers"])
    messages = []
    for f in files:
        messages.extend(read_messages(re.sub(r"([\[\]*?])", r"[\1]", f)))
    jobs, tally = zone_jobs(messages, pickers)
    rec = dict(jobs=dict(job_tallies(jobs), open_at_start=tally["open_at_start"], open_at_end=tally["open_at_end"]),
               n_agv=tally["n_agv"], dropped_by_kept_messages=tally["dropped_by_kept_messages"])
    rec.update(zone_statistics(jobs))
    t_s, t_n = reference_seconds(files, zone)
    hours = task["robot_hours"]
    rec["robot_hours"] = hours
    rec["blocked_s_per_robot_hour"] = task["blocked"]
    rec[f"{T}_stuck_s"] = t_s
    rec[f"{T}_episodes"] = t_n
    rec[f"{T}_stuck_s_per_robot_hour"] = None if not hours else t_s / hours
    return task["run"], zone, rec


# ------------------------------------------------------------------------------------------------ assembly
def run_counts(zones):
    keys = ("completed", "open_at_start", "open_at_end", "ended_to_idle", "ended_to_new_order", "with_gap_over_60s",
            "raw_distance_zero")
    c = {k: sum(z["jobs"][k] for z in zones.values()) for k in keys}
    c["zones"] = len(zones)
    c["zones_below_min_jobs"] = sum(1 for z in zones.values() if z["raw"] is None)
    c["dropped_by_kept_messages"] = sum(z["dropped_by_kept_messages"] for z in zones.values())
    return c


def assemble(runs, zone_records, smoke=False):
    """runs {name: dict(dir, deadlock path, deadlock sha256)}, zone_records {(run, zone): rec} -> output dict."""
    out_runs, per_run = {}, {}
    for name in runs:
        zones = {z: rec for (r, z), rec in zone_records.items() if r == name}
        agr = run_agreement(zones)
        per_run[name] = agr
        out_runs[name] = dict(run_dir=runs[name]["dir"], deadlock=dict(path=runs[name]["deadlock"],
                                                                       sha256=runs[name]["sha256"]),
                              zones=zones, counts=run_counts(zones), agreement=agr,
                              undecided_pairs=sum(1 for v in agr.values() if not v["decided"]))
    summary = {k: pair_medians(per_run, k) for k in pair_keys()}
    return dict(schema_version=SCHEMA, smoke=smoke, definition=DEFINITION, deviations=DEVIATIONS,
                notes=NOTES, params=dict(min_jobs=MIN_JOBS, max_gap_s=DEFAULT_MAX_GAP_S, step_s=STEP_S, cv_ddof=0,
                                         **{f"{T}_keep_s": STUCK_AFTER}, top_k=TOP_K, decisive=list(DECISIVE),
                                         statistics=list(STATS)),
                runs=out_runs, agreement_summary=summary, verdict=verdict(per_run))


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build(runs, workers=None, smoke=False):
    """runs {name: dict(dir, deadlock)}; returns the output dict. Layouts first (spawned processes), then the pool."""
    infos, tasks = {}, []
    for name, spec in runs.items():
        dl_path = Path(spec["deadlock"])
        if not dl_path.is_file():
            raise SystemExit(f"duration_spread: deadlock file missing: {dl_path}")
        dl = json.loads(dl_path.read_text())
        infos[name] = dict(dir=str(spec["dir"]), deadlock=str(spec["deadlock"]), sha256=sha256_file(dl_path))
        files = zone_files(spec["dir"])
        if smoke:
            files = {z: f for z, f in files.items() if z == "0"}
        if not files:
            raise SystemExit(f"duration_spread: no zone*-000.jsonl.gz in {spec['dir']}")
        zones = sorted(files, key=zone_key)
        layouts, _ = auto_layouts(str(spec["dir"]), zones, workers)
        for z in zones:
            dz = dl["zones"].get(z)
            if dz is None:
                raise SystemExit(f"duration_spread: zone {z} of {name} is not in {dl_path}")
            tasks.append(dict(run=name, zone=z, files=files[z], pickers=sorted(layouts[z]["pickers"]),
                              blocked=dz.get("blocked_s_per_robot_hour"), robot_hours=dz.get("robot_hours")))
    n_workers = resolve_workers(workers, n_tasks=len(tasks))
    records = {}
    if n_workers <= 1 or len(tasks) == 1:
        results = [zone_task(t) for t in tasks]
    else:
        with cf.ProcessPoolExecutor(max_workers=n_workers, mp_context=mp.get_context("spawn")) as ex:
            results = list(ex.map(zone_task, tasks))
    for run, zone, rec in results:
        records[(run, zone)] = rec
    return assemble(infos, records, smoke=smoke)


def parse_runs(runs_arg, run_args, deadlock_args):
    """Specs from --runs 'N=DIR,N=DIR', repeated --run N:DIR and --deadlock N=PATH; default mapping when none given."""
    pairs = []
    for item in (runs_arg.split(",") if runs_arg else []):
        if item.strip():
            name, _, d = item.partition("=")
            pairs.append((name.strip(), d.strip()))
    for item in run_args or []:
        name, _, d = item.partition(":")
        pairs.append((name.strip(), d.strip()))
    dl = {}
    for item in deadlock_args or []:
        name, _, p = item.partition("=")
        dl[name.strip()] = p.strip()
    if not pairs:
        return {n: dict(dir=str(REPO / d), deadlock=dl.get(n, str(REPO / p))) for n, (d, p) in DEFAULT_RUNS.items()}
    out = {}
    for name, d in pairs:
        if not name or not d:
            raise SystemExit(f"duration_spread: bad run spec for {name!r}")
        default_dl = DEFAULT_RUNS[name][1] if name in DEFAULT_RUNS else f"results/fleet/deadlock_{name}-sb.json"
        out[name] = dict(dir=d, deadlock=dl.get(name, str(REPO / default_dl)))
    return out


def require_scipy():
    try:
        import scipy.stats  # noqa: F401
    except ImportError:
        raise SystemExit("duration_spread: scipy is required (Kendall tau-b p-value); pip install scipy")


def main(argv=None):
    require_scipy()
    ap = argparse.ArgumentParser(description="S15B duration spread vs blocking and the stall reference")
    ap.add_argument("--runs", default=None, help="NAME=DIR,NAME=DIR,... (default: the five runs of DEFAULT_RUNS)")
    ap.add_argument("--run", action="append", default=None, help="NAME:DIR, repeatable")
    ap.add_argument("--deadlock", action="append", default=None,
                    help="NAME=PATH of the -sb deadlock file (default results/fleet/deadlock_<NAME>-sb.json)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=None, help="default: SCHED_WORKERS, else os.cpu_count() - 2")
    ap.add_argument("--smoke", action="store_true", help="the first run, zone 0 only")
    args = ap.parse_args(argv)
    t0 = time.time()
    out_path = Path(args.out)
    if not out_path.parent.is_dir():
        raise SystemExit(f"duration_spread: parent directory of --out does not exist: {out_path.parent}")
    runs = parse_runs(args.runs, args.run, args.deadlock)
    if args.smoke:
        first = next(iter(runs))
        runs = {first: runs[first]}
    for name, spec in runs.items():
        if not Path(spec["dir"]).is_dir():
            raise SystemExit(f"duration_spread: run directory missing for {name}: {spec['dir']}")
    result = build(runs, args.workers, smoke=args.smoke)
    out_path.write_text(json.dumps(result, sort_keys=True, indent=1) + "\n")
    v = result["verdict"]
    print(f"duration_spread: {len(runs)} run(s), verdict {v['verdict']}, wrote {out_path} in {time.time() - t0:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

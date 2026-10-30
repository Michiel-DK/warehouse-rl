"""S18A reduce_check: does a reduced log give the same answers as the full one? Runs fleet/reduce.py's rungs and compares.

Usage: python fleet/reduce_check.py --glob 'DIR/zone*-000.jsonl.gz' --run NAME --out results/fleet/reduce_NAME.json
           [--stations PATH] [--station-radius N] [--servicing-max-s S] [--moroop-raw DIR] [--workers N]
H is 30 and 60 s, max_gap_s is timebudget's default (fixed by the S18A brief; the python API takes others for tests).
Workers (env layouts for the s10-none style bucket cell sets): --workers, else SCHED_WORKERS, else os.cpu_count() - 2.

For the full log and for each reduced log (rule x H) the SAME existing analyses run with the SAME args (stations, radius,
servicing bound, max gap), one analysis per input file group (fleet/reduce.py: a MoRoOp shift is one group; the same robot
serial recurs in every shift), and the outputs are compared EXACTLY, no numeric tolerance:
  time_budget      per robot: every bucket's seconds and share, span, jobs; per zone: same_minute_stops (fleet/timebudget.py)
  stall_list       episode id, start, end, robot, cell, cause, blocker, resolution (timebudget.recompute_episodes)
  transitions      detector transitions (robot, ts, from, to)
  station_bound    only with --stations: detector servicing_runs / station_overruns and the station_overrun episodes
  s15a_rules       only with --moroop-raw: stall_baseline rows N1 and N2-W (counts, gap_spanning alerts, episodes by timestamp)
  label_hits       only with --moroop-raw: moroop.label_comparison (labelled stops hit / missed, false alarms, TIMEOUT
                   operations, overruns) and the per-labelled-stop alerts of every S15A rule
Every position-rule and label comparison is by TIMESTAMP: the kept indices a / b of stall_baseline episodes shift in a reduced
log and are never compared. An output that does not apply to the run is "not_applicable", never "identical". The ledger's
sequence_gaps / missing_messages and the byte counts are reported next to the flags and are not part of them (dropping lines
leaves headerId holes by construction).
A difference is {"count": items that differ (a missing item counts), "max_abs_diff_s": largest absolute difference of a
seconds-valued field, null when none, "robots": serials involved}. all_identical = at least one output applies and every
applicable one is identical. first_identical_rule = the lowest of change, gap, threshold, neighbours, recovered with
all_identical, else null ("all", the identity, is run as a sanity check and excluded).
"""
import argparse
import collections
import glob as _glob
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

FLEET = Path(__file__).resolve().parent
REPO = FLEET.parent
for _p in (FLEET, REPO / "src", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import stall_baseline as sb  # noqa: E402
import timebudget as tb  # noqa: E402
from adapters import moroop  # noqa: E402
from fleet_analyser.detector import Detector  # noqa: E402
from fleet_analyser.ledger import SequenceTracker  # noqa: E402
from fleet_analyser.parse import parse_line  # noqa: E402
from fleet_analyser.stations import auto_layouts, goal_cells, resolve_workers  # noqa: E402
from reduce import RUNGS, Reducer, group_of, read_lines  # noqa: E402

SCHEMA = "reduce-check/1"
NOT_APPLICABLE = "not_applicable"
IDENTICAL = "identical"
OUTPUTS = ("time_budget", "stall_list", "transitions", "station_bound", "s15a_rules", "label_hits")
SECONDS_NAMES = {"ts", "start", "end", "alert", "span_s", "duration_s", "servicing_s", "alert_latency_s", "label_start",
                 "box_start", "box_end", "run_start", "run_end", "count_s"}
MISSING = object()
ROBOT_HOURS_TEXT = ("per (file group, robot serial): last accepted ts minus first accepted ts in the full input, summed over "
                    "all robots (pickers included), in hours; the same denominator for lines in and lines kept")


# ------------------------------------------------------------------------------------------------ comparison
def _is_seconds(field):
    return field in SECONDS_NAMES or field.startswith("seconds.")


def compare(full, red):
    """NOT_APPLICABLE, IDENTICAL or a diff dict. full / red: {key tuple (group, robot or "-", ...): {field: leaf}} or None."""
    if full is None:
        return NOT_APPLICABLE
    diff_keys, max_s = [], None
    for k in set(full) | set(red):
        a, b = full.get(k, MISSING), red.get(k, MISSING)
        if a == b:
            continue
        diff_keys.append(k)
        if a is MISSING or b is MISSING:
            continue
        for f in set(a) | set(b):
            x, y = a.get(f), b.get(f)
            if x != y and _is_seconds(f) and isinstance(x, (int, float)) and isinstance(y, (int, float)):
                d = abs(x - y)
                max_s = d if max_s is None else max(max_s, d)
    if not diff_keys:
        return IDENTICAL
    return dict(count=len(diff_keys), max_abs_diff_s=max_s,
                robots=sorted({str(k[1]) for k in diff_keys if k[1] != "-"} | {f"group:{k[0]}" for k in diff_keys if k[1] == "-"}))


def verdict_of(flags):
    """all_identical: at least one output applies and every applicable one is identical."""
    applicable = [v for v in flags.values() if v != NOT_APPLICABLE]
    return bool(applicable) and all(v == IDENTICAL for v in applicable)


# ------------------------------------------------------------------------------------------------ context
class Context:
    """Everything the analyses are given, identical for the full and every reduced log."""

    def __init__(self, paths, run, stations=None, station_radius=0, servicing_max_s=None, max_gap_s=tb.DEFAULT_MAX_GAP_S,
                 moroop_raw=None, workers=None, layouts=None):
        self.run, self.stations_path, self.max_gap_s = run, stations, max_gap_s
        self.station_radius, self.servicing_max_s = station_radius, servicing_max_s
        self.station_aware = stations is not None
        self.moroop_raw = moroop_raw
        msgs = [m for p in paths for m in _group_messages([p])]
        zones = sorted({m.zone for m in msgs}, key=lambda s: (len(s), s))
        if layouts is not None:  # python API (tests): a ready {zone: layout}, used for the bucket cell sets only
            self.layouts, self.layout_source = layouts, "given"
        elif stations is not None:
            self.layouts, self.layout_source = tb.path_layouts(stations, zones), "path"
        else:
            glob_dir = str(Path(paths[0]).parent)
            self.layouts, _ = auto_layouts(glob_dir, zones, workers)
            self.layout_source = "auto (emit_ledger.json of the full log)"
        self.det_stations = goal_cells(self.layouts) if self.station_aware else None
        self.rule_radius = station_radius if self.station_aware else None
        self._natives = {}
        if moroop_raw is not None:
            sj = json.loads(Path(stations).read_text())
            self.cells, self.near, _ = tb.cell_sets(sj["stations"], [])

    def native(self, k):
        if k not in self._natives:
            self._natives[k] = moroop.load_shift(self.moroop_raw, moroop.SHIFTS[k])
        return self._natives[k]


def _group_messages(files):
    """timebudget's input for one group: parsed lines, the first of every (serial, headerId) pair (hotspot.read_messages)."""
    msgs, seen = [], set()
    for path in sorted(files):
        for line in read_lines(path):
            m, _ = parse_line(line)
            if m is None or (m.serial, m.header_id) in seen:
                continue
            seen.add((m.serial, m.header_id))
            msgs.append(m)
    return msgs


def groups_of(paths):
    out = collections.defaultdict(list)
    for p in sorted(paths):
        out[group_of(p)].append(p)
    return dict(out)


# ------------------------------------------------------------------------------------------------ analyses of one group
def _detector_pass(ctx, msgs):
    det = Detector(stations=ctx.det_stations, station_radius=ctx.station_radius, servicing_max_s=ctx.servicing_max_s)
    events = []
    for m in sorted(msgs, key=lambda m: (m.ts, m.serial)):
        events += det.feed(m)
    events += det.end_all()
    return det, events


def _cell(c):
    return f"{c[0]},{c[1]}" if c is not None else None


def analyse_group(ctx, group, files):
    """{output: {key: record}} for one file group; an output that does not apply is None."""
    msgs = _group_messages(files)
    episodes = tb.recompute_episodes(msgs, ctx.det_stations, ctx.station_radius, ctx.servicing_max_s)
    zones, _ = tb.compute(msgs, ctx.run, ctx.layouts, episodes, "recomputed", 3600, ctx.max_gap_s, ctx.rule_radius,
                          ctx.servicing_max_s)
    budget = {}
    for z, d in zones.items():
        for kind in ("robots", "pickers"):
            for serial, rec in d[kind].items():
                r = {f"seconds.{b}": rec["seconds"][b] for b in tb.BUCKETS}
                r.update({f"share.{b}": rec["share"][b] for b in tb.BUCKETS})
                r.update(span_s=rec["span_s"], jobs=rec["jobs"])
                budget[(group, serial, kind)] = r
        same = d["same_minute_stops"]
        budget[(group, "-", "same_minute_stops", z)] = dict(count=same["count"], minutes=",".join(same["minutes"]),
                                                            n_robots=same["n_robots"])
    stall = {(group, e["robot"], e["episode_id"]): dict(
        start=e["start"], end=e["end"], robot=e["robot"], cell=_cell(e["cell"]), cause=e["cause"], blocker=e["blocker"],
        resolution=e["resolution"]) for e in episodes}
    det, events = _detector_pass(ctx, msgs)
    n = collections.Counter()
    transitions = {}
    for ev in events:
        if ev["kind"] == "transition":
            transitions[(group, ev["robot"], n[ev["robot"]])] = dict(ts=ev["ts"], from_state=ev["from_state"],
                                                                      to_state=ev["to_state"])
            n[ev["robot"]] += 1
    bound = None
    if ctx.station_aware:
        bound = {(group, "-", "counters"): dict(servicing_runs=det.servicing_runs, station_overruns=det.station_overruns)}
        for e in episodes:
            if e["cause"] == "station_overrun":
                bound[(group, e["robot"], e["episode_id"])] = dict(start=e["start"], end=e["end"],
                                                                   servicing_s=e.get("servicing_s"), resolution=e["resolution"])
    out = dict(time_budget=budget, stall_list=stall, transitions=transitions, station_bound=bound, s15a_rules=None,
               label_hits=None)
    if ctx.moroop_raw is not None:
        out["s15a_rules"], out["label_hits"] = _moroop_outputs(ctx, group, msgs)
    return out, _sequence(files)


def _sequence(files):
    tr = SequenceTracker()
    for p in sorted(files):
        for line in read_lines(p):
            m, _ = parse_line(line)
            if m is not None:
                tr.check(m.serial, m.header_id)
    return dict(sequence_gaps=tr.gaps, missing_messages=tr.missing, duplicates=tr.duplicates)


def _moroop_outputs(ctx, group, msgs):
    """S15A rule rows (N1, N2-W) and the labelled-stop hits of one MoRoOp shift file, compared by timestamp only."""
    k = int(group[len("zone"):])
    native = ctx.native(k)
    kept = tb.kept_messages(msgs)
    cells, near = ctx.cells, ctx.near
    radius, bound = ctx.station_radius, ctx.servicing_max_s
    buckets = moroop.second_buckets(kept, cells, near, tb)
    eps_by_rule = {r: sb.rule_episodes(kept, r, sb.MOROOP_CELL_M, cells, radius, bound) for r in sb.RULES}
    rules, labels = {}, {}
    for r in sb.RULES:
        with sb._intervals_substituted(sb.intervals_of(eps_by_rule[r])):
            lab = moroop.label_comparison(native["robot_state_cleaned"], kept, buckets, native["operations"], cells, tb,
                                          None, None)
        counts, on_station = sb._label_counts(lab)
        if r in sb.POSITION_RULES:
            row = {f"counts.{c}": v for c, v in counts.items()}
            row.update(false_alarms_on_station_cell=on_station,
                       gap_spanning_alerts=sum(1 for e in eps_by_rule[r] if e["gap_spanning"]))
            rules[(group, "-", r, "rule")] = row
            for i, e in enumerate(eps_by_rule[r]):
                rules[(group, "-", r, f"ep{i}")] = dict(start=e["start"], alert=e["alert"], end=e["end"],
                                                        resolution=e["resolution"], gap_spanning=e["gap_spanning"])
        else:
            labels[(group, "-", r, "counts")] = {f"counts.{c}": v for c, v in counts.items()}
    # the sf run's own label match (radius, servicing bound), as moroop.analyse does for results/fleet/moroop_label-sf.json
    buckets_sf = moroop.second_buckets(kept, cells, near, tb, radius=radius, servicing_max_s=bound)
    lab = moroop.label_comparison(native["robot_state_cleaned"], kept, buckets_sf, native["operations"], cells, tb, radius,
                                  bound)
    lab.pop("_episodes")
    labels[(group, "-", "sf", "counts")] = dict(
        stuck_runs=lab["stuck_runs"], episodes=lab["episodes"], ge30=lab["episodes_ge_30s"]["count"],
        hits=lab["episodes_ge_30s"]["hits"], misses=lab["episodes_ge_30s"]["misses"],
        false_alarms=lab["false_alarms"]["count"], timeouts=lab["timeout_operations"]["count"],
        timeouts_detected=lab["timeout_operations"]["detected"], overruns=len(lab["overruns"]))
    for i, e in enumerate(lab["episodes_ge_30s"]["list"]):
        labels[(group, "-", "sf", f"label{i}")] = dict(label_start=e["start"], duration_s=e["duration_s"],
                                                       detected=e["detected"])
    for i, f in enumerate(lab["false_alarms"]["list"]):
        labels[(group, "-", "sf", f"fa{i}")] = dict(start=f["start"], duration_s=f["duration_s"],
                                                    timeout=f["overlaps_timeout_operation"],
                                                    paused=f["overlaps_paused_message"], on_station=f["on_station_cell"])
    for i, t in enumerate(lab["timeout_operations"]["list"]):
        labels[(group, "-", "sf", f"timeout{i}")] = dict(operation_id=t["operation_id"], start=t["start"], finish=t["finish"],
                                                         detected=t["detected"])
    for i, o in enumerate(lab["overruns"]):
        labels[(group, "-", "sf", f"overrun{i}")] = dict(start=o["start"], duration_s=o["duration_s"],
                                                         cell=_cell(o["station_cell"]), timeout=o["overlaps_timeout_operation"])
    for i, row in enumerate(sb._label_rows(k, kept, native["robot_state_cleaned"], eps_by_rule)):
        rec = dict(label_start=row["label_start"], label_duration_s=row["label_duration_s"],
                   box_start=row["box_stillness"]["start"], box_end=row["box_stillness"]["end"])
        sr = row["stopped_run"]
        rec.update(run_start=None if sr is None else sr["start"], run_end=None if sr is None else sr["end"])
        for r, v in row["rules"].items():
            rec[f"alert.{r}"] = v["alert"]
            rec[f"latency.{r}"] = v["alert_latency_s"]
        labels[(group, "-", "stops", f"stop{i}")] = rec
    return rules, labels


def analyse_dir(ctx, paths):
    """(outputs merged over the groups, sequence accounting). An output is None iff it is None in every group."""
    merged = {o: None for o in OUTPUTS}
    seq = collections.Counter()
    for group, files in groups_of(paths).items():
        out, s = analyse_group(ctx, group, files)
        seq.update(s)
        for o in OUTPUTS:
            if out[o] is not None:
                merged[o] = {**(merged[o] or {}), **out[o]}
    return merged, dict(seq)


# ------------------------------------------------------------------------------------------------ the check
def check(paths, run, stations=None, station_radius=0, servicing_max_s=None, max_gap_s=tb.DEFAULT_MAX_GAP_S,
          moroop_raw=None, heartbeats=(30.0, 60.0), workers=None, workdir=None, layouts=None):
    paths = sorted(paths)
    ctx = Context(paths, run, stations, station_radius, servicing_max_s, max_gap_s, moroop_raw, workers, layouts)
    red = Reducer(paths, stations, station_radius, servicing_max_s, max_gap_s)
    if red.n_out_of_order:
        # the analyses read every deduplicated message (out-of-order ts included), the reducer its canonical view without
        # them: on such a log the comparison would report differences that come from the input view, not the rule
        raise SystemExit(f"reduce_check: {red.n_out_of_order} out-of-order lines; the comparison assumes none")
    full, full_seq = analyse_dir(ctx, paths)
    own_tmp = workdir is None
    work = Path(tempfile.mkdtemp(prefix="reduce_check_")) if own_tmp else Path(workdir)
    cache = {}
    try:
        def one(rule, h):
            key = (rule, None if rule in ("all", "change") else h)  # R0 and R1 do not depend on H
            if key not in cache:
                out = work / f"{rule}-{'x' if key[1] is None else int(key[1])}"
                red.write(rule, out, h)
                rpaths = sorted(str(out / Path(p).name) for p in paths)
                outs, seq = analyse_dir(ctx, rpaths)
                flags = {o: compare(full[o], outs[o]) for o in OUTPUTS}
                s = red.summary(rule, h)
                cache[key] = dict(
                    ratio_gzip=s["ratio_gzip"], line_ratio=s["line_ratio"],
                    kept_lines_per_robot_hour=s["kept_lines_per_robot_hour"], lines_in=s["lines_in"],
                    lines_kept=s["lines_kept"], bytes_in_gzip=s["bytes_in_gzip"], bytes_kept_gzip=s["bytes_kept_gzip"],
                    bytes_in_raw=s["bytes_in_raw"], bytes_kept_raw=s["bytes_kept_raw"],
                    kept_by_rule=s["kept_by_rule"], added_by_rule=s["added_by_rule"],
                    outputs=flags, all_identical=verdict_of(flags), sequence=seq)
            return cache[key]

        per_h = {}
        for h in heartbeats:
            rungs = {rule: dict(one(rule, h)) for rule in ("all",) + RUNGS}
            first = next((r for r in RUNGS if rungs[r]["all_identical"]), None)
            per_h[str(int(h)) if float(h).is_integer() else str(h)] = dict(
                rungs=rungs, first_identical_rule=first, verdict=IDENTICAL if first is not None else "refuted",
                ratio_gzip_at_first_identical_rule=None if first is None else rungs[first]["ratio_gzip"])
    finally:
        if own_tmp:
            shutil.rmtree(work, ignore_errors=True)
    s_all = red.summary("all")
    return dict(
        schema=SCHEMA, run=run,
        args=dict(glob_files=[_rel(p) for p in paths], stations=_rel(stations),
                  station_radius=station_radius if stations else None,
                  servicing_max_s=servicing_max_s, max_gap_s=max_gap_s, moroop_raw=_rel(moroop_raw),
                  heartbeats=[float(h) for h in heartbeats], timebudget_layout=ctx.layout_source,
                  stations_sha256=_sha(stations)),
        robot_hour_definition=ROBOT_HOURS_TEXT, robot_hours=s_all["robot_hours"], robots=s_all["robots"],
        groups=s_all["groups"], lines_rejected=s_all["lines_rejected"], lines_duplicate=s_all["lines_duplicate"],
        lines_out_of_order=s_all["lines_out_of_order"], gzip_level=s_all["gzip_level"],
        applicable={o: full[o] is not None for o in OUTPUTS}, full_sequence=full_seq,
        full_label_sf_pooled=_pooled_sf(full["label_hits"]),
        heartbeat=per_h)


def _pooled_sf(label_hits):
    """The full log's sf label counts summed over the shifts (compare with results/fleet/moroop_label-sf.json pooled.counts)."""
    if label_hits is None:
        return None
    tot = collections.Counter()
    for k, v in label_hits.items():
        if k[2] == "sf" and k[3] == "counts":
            tot.update(v)
    return dict(sorted(tot.items()))


def _rel(path):
    """A path as recorded in a result file: relative to the checkout it lives in (the first ancestor holding both fleet/
    and vendor/), so no machine path is committed; unchanged when it is in no checkout."""
    if path is None:
        return None
    p = Path(path).resolve()
    for root in p.parents:
        if (root / "fleet").is_dir() and (root / "vendor").is_dir():
            return str(p.relative_to(root))
    return str(path)


def _sha(path):
    import hashlib
    return None if path is None else hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ------------------------------------------------------------------------------------------------ table
def table_markdown(doc):
    """One markdown table per H: rung, ratio_gzip, line_ratio, kept lines/robot-h, per-output flag, all_identical."""
    out = []
    for h, d in doc["heartbeat"].items():
        out.append(f"{doc['run']}, H = {h} s (lines per robot-hour in: "
                   f"{d['rungs']['all']['lines_kept'] / doc['robot_hours']:.1f}); first_identical_rule: "
                   f"{d['first_identical_rule']}; verdict: {d['verdict']}")
        out.append("")
        out.append("| rung | ratio_gzip | line_ratio | kept lines/robot-h | " + " | ".join(OUTPUTS) + " | all_identical |")
        out.append("|" + "---|" * (5 + len(OUTPUTS)))
        for rung, r in d["rungs"].items():
            cells = []
            for o in OUTPUTS:
                v = r["outputs"][o]
                cells.append(v if isinstance(v, str) else f"diff n={v['count']} max_s={v['max_abs_diff_s']} "
                             f"robots={len(v['robots'])}")
            out.append(f"| {rung} | {r['ratio_gzip']:.4f} | {r['line_ratio']:.4f} | {r['kept_lines_per_robot_hour']:.1f} | "
                       + " | ".join(cells) + f" | {r['all_identical']} |")
        out.append("")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="S18A: compare the analyses on a full and a reduced log")
    ap.add_argument("--glob", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--stations", type=_stations, default=None)
    ap.add_argument("--station-radius", type=int, default=0)
    ap.add_argument("--servicing-max-s", type=_servicing, default=None, metavar="S")
    ap.add_argument("--moroop-raw", default=None, help="fleet/data/moroop/raw: adds the S15A rows and the label hits")
    ap.add_argument("--workers", type=int, default=None, help="default: SCHED_WORKERS, else os.cpu_count() - 2")
    a = ap.parse_args(argv)
    if a.station_radius < 0:
        ap.error("--station-radius must be >= 0")
    if a.moroop_raw and not a.stations:
        ap.error("--moroop-raw needs --stations")
    paths = sorted(_glob.glob(a.glob))
    if not paths:
        print(f"reduce_check: no files match {a.glob}", file=sys.stderr)
        return 2
    out_path = Path(a.out)
    if not out_path.parent.is_dir():
        raise SystemExit(f"reduce_check: parent directory of --out does not exist: {out_path.parent}")
    workers = resolve_workers(a.workers, n_tasks=len(paths))
    doc = check(paths, a.run, a.stations, a.station_radius, a.servicing_max_s, tb.DEFAULT_MAX_GAP_S, a.moroop_raw,
                (30.0, 60.0), workers)
    out_path.write_text(json.dumps(doc, sort_keys=True, indent=1, allow_nan=False) + "\n")
    print(table_markdown(doc))
    return 0


def _stations(text):
    from reduce import stations_path
    return stations_path(text)


def _servicing(text):
    from reduce import servicing_number
    return servicing_number(text)


if __name__ == "__main__":
    sys.exit(main())

"""Export ONE zone of a real fleet run as a static `window.REPLAY = {...};` file for the offline replay page (docs/replay/).

Usage: python fleet/replay_export.py --run-dir DIR --store jsonl:DIR/store --zone 0 --out docs/replay/data.js
       [--closed-loop results/closed_loop]
DIR holds the zone files zone<Z>-<nnn>.jsonl.gz, truth.json, emit_ledger.json and costmap.json (the run name is
costmap.json["run"], as fleet/hotspot_score.py reads it). The store is only READ (every table through
store.select(table, {"run": run}); the raw .jsonl store files are never read and nothing is upserted). The export reuses
fleet_analyser.parse / hotspot / ledger and fleet/hotspot_score.py; it implements none of them again. The file is written
atomically (tmp + os.replace) and the writer raises, without writing, when it is larger than 2 MiB (2097152 bytes).

Payload (every key is always present unless marked optional):
  meta        run, zone (str), env_id, steps, step_seconds (5), t0_ts (epoch s of step 0), seed, disturb, policy, recovery,
              schema "replay/1", source {run_dir, store, closed_loop} = the paths exactly as given on the command line
              (never resolved to absolute paths). Step s covers event time t0_ts + s * step_seconds.
  grid        {width, height, highway, goals, shelves}: shape is width (columns, x) by height (rows, y), the same (x, y)
              system as agvPosition. highway = height strings of width chars, "1" = highway cell, "0" = not;
              goals = [[x, y]]; shelves = [[x, y]] shelf positions right after the reset. Built from the vendored env of
              meta.env_id, reset with the zone's seed, read-only, in ONE fresh process (Agent.counter and Shelf.counter
              are class attributes: never two envs in one process). Every robot position of every layer must lie inside
              the grid or the export raises.
  robots      [{serial, kind}] sorted by serial; kind "agv" or "picker" (the first num_agvs agents are AGVs).
  frames      frames[step][robot_index] = [x, y, state] for every step and every robot (robots order). A robot with no
              message at a step keeps its previous entry (before its first message: its first position, "idle").
              A step with several messages of a robot uses the highest headerId. state is one of
              moving, loading, stalled, stuck, frozen, idle, derived by derive_state() with precedence
              frozen > stuck > stalled > loading > moving > idle:
                frozen  the message has errors (the robot is faulted; unrelated to the S3E "frozen blocker" vocabulary)
                stuck   the message ts lies in [start, end] of a detector stuck episode of that robot (end None = runs to
                        the stream end); left_censored rows and resolution "interrupted" rows are skipped, the rule of
                        hotspot.annotate_episodes
                stalled the ts lies in [start, end] of a stall of that robot (hotspot.extract_stalls)
                loading has an order, is not driving and reports nodeStates []
                moving  driving true
                idle    anything else
  obstacles   the zone's hidden floor problems from truth.json: [{kind "floor", cell "x,y", p, hidden_from_analyser true}]
              sorted by cell (truth.json of this emitter carries no breakdown or frozen windows, so none are emitted).
  extractor   {series, totals, check}. series: per step (steps entries each), CUMULATIVE and non-decreasing, in EVENT time
              (a parsed line counts at the step of its message ts; a rejected line at the step of the last parsed line
              before it, step 0 if none): bytes (uncompressed, len of the raw line), messages (lines), parsed, rejected,
              rejected_by_reason {reason: [..]}, duplicates, sequence_gaps, missing_messages, accepted, coverage
              (accepted / expected, null without an expected count). Duplicates and gaps are classified by
              ledger.SequenceTracker exactly as the ingester does (headerId <= last accepted = duplicate). totals: the
              series at the last step plus expected_messages and bytes_compressed (the emit ledger's total for the zone
              file(s); compressed bytes are not split per line, so there is no series for it). check: the ingest
              checkpoint counters of the zone's file(s) (messages_parsed, messages_rejected, duplicates, sequence_gaps,
              missing_messages, messages_accepted, bytes_read_uncompressed). The ingester's counters are cumulative over
              the run, so check is the difference to the previous checkpoint row by cp_seq, which is exact when the files
              are ingested one after another (a file is consumed before the next starts). The export raises when the
              replayed totals disagree with check; check is null when the store has no checkpoint for the file.
  publishes   every costmap publish of the zone in the store, ascending by t: {t, step, cells [[cell, cost (4 decimals),
              stalls]] sorted by (-cost, cell), precision_at_20, hits_at_20, n_flagged}; precision comes from
              hotspot_score.precision_recall(zone map, floor cells, ks=(20,))[20] on the unrounded costs.
  grades      {per_publish, timeline}. per_publish[i] belongs to publishes[i]: counts over the forecast_grades rows whose id
              joins to a decisions row of kind hotspot_forecast, subject prefix "Z<zone>:" and decided_at == t. Keys:
              t, forecasts, rank {ok, off} (grade_source "outcome"), count {ok, off} (grade_source "outcome_count"),
              truth {hit, false_alarm} (grade_source "truth"), open (forecasts with no "outcome" row whose decision is
              still open), unranked (decisions stamped verdict "unranked"), outcome_kind, window_end (+ _step): the
              latest window_end of the publish's outcome rows, null without any (the time the outcome grades exist). The source names are kept.
              outcome_kind says what the "outcome" rows of that publish mean: "rank" when their decisions carry a v2 claim
              (top_k present: ok = the cell is still in the zone's top K at window_end), "count" for older v1 claims
              (the "outcome" row is then the expected-stall-count grade), null when the publish has no "outcome" row.
              The page must only call a rank grade "still in top 20 after the horizon" when outcome_kind is "rank".
              timeline: cumulative counts by event time [{t, step, rank_ok, rank_off, truth_hit, truth_false_alarm}],
              a grade at its window_end (truth rows, which have none, at the publish t).
  episodes    ALL detector stuck-episode rows of the zone from store.select (zone == the exported zone), NOT filtered:
              [{start_step, end_step (null = open), robot, cell [x, y], cause, resolution, left_censored}]. Only the
              frames skip left_censored and "interrupted" rows (see stuck above); the page does the same.
  stalls      [[robot, cell, start_step, end_step, counted]] from hotspot.extract_stalls, counted = hotspot.counted() after
              annotate_episodes (the filter the cost map uses).
  with_map    OPTIONAL, only with --closed-loop DIR when DIR/summary.json names a headline_arm and DIR/phaseA/costmap.json
              exists: {arm, alpha, map_path, map_generated_at, map_tag, deliveries, pick_rate, frames, note}. DIR holds
              per-seed aggregates only, so this layer RE-SIMULATES the zone's seed (same env, disturbance, recovery and
              policy, steps) with the cost-aware router and the FINAL phaseA map of this zone applied from step 0
              (in-sample, not learned live). frames use the same derive_state(); episodes are not available for it, so
              its "stuck" state never occurs and "stalled" comes from stall extraction only. Env numbers are
              platform-dependent (pyastar2d tie-breaks): only the layer's layout is stable across machines.
"""
import argparse
import gzip
import json
import multiprocessing as mp
import os
import posixpath
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

FLEET = Path(__file__).resolve().parent
REPO = FLEET.parent
for _p in (FLEET, REPO / "src", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import hotspot_score  # noqa: E402
from fleet_analyser import emitter, hotspot, ledger, store as store_mod  # noqa: E402
from fleet_analyser.parse import epoch_of, parse_line  # noqa: E402

SCHEMA = "replay/1"
STATES = ("moving", "loading", "stalled", "stuck", "frozen", "idle")
MAX_BYTES = 2 * 1024 * 1024
PREFIX = "window.REPLAY = "
CHECK_KEYS = ("messages_parsed", "messages_rejected", "duplicates", "sequence_gaps", "missing_messages",
              "messages_accepted", "bytes_read_uncompressed")
SERIES_KEYS = ("bytes", "messages", "parsed", "rejected", "duplicates", "sequence_gaps", "missing_messages", "accepted")
STEP_SECONDS = 5


# ------------------------------------------------------------------------------------------------ state derivation
def derive_state(msg, in_episode=False, in_stall=False):
    """The state of one robot at one message, precedence frozen > stuck > stalled > loading > moving > idle."""
    if msg.faulted:
        return "frozen"
    if in_episode:
        return "stuck"
    if in_stall:
        return "stalled"
    if msg.order_id != "" and not msg.driving and msg.nodes_reported and msg.next_x is None:
        return "loading"
    if msg.driving:
        return "moving"
    return "idle"


def _intervals(rows):
    """{robot: [(start, end_or_inf)]}; the rows are episodes (skip rule of annotate_episodes) or stalls."""
    out = {}
    for r in rows:
        if r.get("left_censored") or r.get("resolution") == "interrupted":
            continue
        end = float("inf") if r.get("end") is None else r["end"]
        out.setdefault(r["robot"], []).append((r["start"], end))
    return out


def _within(spans, ts):
    return any(a <= ts <= b for a, b in spans)


def build_frames(messages, robots, t0_ts, steps, episodes, stalls, grid, step_seconds=STEP_SECONDS):
    """frames[step][robot_index] = [x, y, state]. Raises ValueError for a position outside the grid."""
    ep_by = _intervals(episodes)
    st_by = _intervals(stalls)
    index = {r["serial"]: i for i, r in enumerate(robots)}
    cell = {}  # (robot_index, step) -> (header_id, entry)
    for m in messages:
        i = index.get(m.serial)
        step, rem = divmod(m.ts - t0_ts, step_seconds)
        if i is None or rem or not 0 <= step < steps:
            continue
        if not (0 <= m.x < grid["width"] and 0 <= m.y < grid["height"]):
            raise ValueError(f"{m.serial} reports ({m.x}, {m.y}) at step {step}, outside the {grid['width']}x"
                             f"{grid['height']} grid")
        state = derive_state(m, _within(ep_by.get(m.serial, ()), m.ts), _within(st_by.get(m.serial, ()), m.ts))
        prev = cell.get((i, step))
        if prev is None or m.header_id > prev[0]:
            cell[(i, step)] = (m.header_id, [m.x, m.y, state])
    frames = [[None] * len(robots) for _ in range(steps)]
    for i in range(len(robots)):
        last = None
        first = next((cell[(i, s)][1] for s in range(steps) if (i, s) in cell), None)
        for s in range(steps):
            if (i, s) in cell:
                last = cell[(i, s)][1]
            elif last is None and first is not None:
                last = [first[0], first[1], "idle"]
            frames[s][i] = list(last) if last is not None else None
    for s, row in enumerate(frames):
        for i, e in enumerate(row):
            if e is None:
                raise ValueError(f"robot {robots[i]['serial']} has no message in the zone files")
    return frames


# ------------------------------------------------------------------------------------------------ extractor
def zone_files(run_dir, zone):
    return sorted(Path(run_dir).glob(f"zone{zone}-*.jsonl.gz"))


def replay_extractor(files, t0_ts, steps, expected, bytes_compressed=None, step_seconds=STEP_SECONDS):
    """Replay the zone files line by line; returns (series, totals). See the module docstring."""
    zeros = lambda: [0] * steps  # noqa: E731
    delta = {k: zeros() for k in SERIES_KEYS}
    reasons = {}
    seq = ledger.SequenceTracker()
    last_step = 0
    for path in files:
        with gzip.open(path, "rb") as f:
            for raw in f:
                msg, reason = parse_line(raw)
                if msg is None:
                    step = last_step
                    delta["rejected"][step] += 1
                    reasons.setdefault(reason, zeros())[step] += 1
                else:
                    step = min(max((msg.ts - t0_ts) // step_seconds, 0), steps - 1)
                    last_step = step
                    delta["parsed"][step] += 1
                    accepted, missing = seq.check(msg.serial, msg.header_id)
                    if not accepted:
                        delta["duplicates"][step] += 1
                    else:
                        delta["accepted"][step] += 1
                        if missing:
                            delta["sequence_gaps"][step] += 1
                            delta["missing_messages"][step] += missing
                delta["bytes"][step] += len(raw)
                delta["messages"][step] += 1

    def cumulative(xs):
        out, tot = [], 0
        for x in xs:
            tot += x
            out.append(tot)
        return out

    series = {k: cumulative(v) for k, v in delta.items()}
    series["rejected_by_reason"] = {r: cumulative(v) for r, v in sorted(reasons.items())}
    series["coverage"] = [None if ledger.coverage(a, expected) is None else round(ledger.coverage(a, expected), 6)
                          for a in series["accepted"]]
    totals = {k: series[k][-1] for k in SERIES_KEYS}
    totals["rejected_by_reason"] = {r: v[-1] for r, v in series["rejected_by_reason"].items()}
    totals["coverage"] = series["coverage"][-1]
    totals["expected_messages"] = expected
    totals["bytes_compressed"] = bytes_compressed
    return series, totals


def _counter_sum(row):
    out = dict.fromkeys(CHECK_KEYS, 0)
    for minute in json.loads(row["ledger_counters"] or "{}").values():
        for k in CHECK_KEYS:
            out[k] += minute.get(k, 0) or 0
    return out


def ingest_check(st, run, files):
    """The ingest checkpoint counters of `files` (differences to the previous checkpoint by cp_seq), or None."""
    latest = {}
    for r in st.select("ingest_checkpoints", {"run": run}):
        name = posixpath.basename(r["path"].replace("\\", "/"))
        key = (r.get("cp_seq") or 0, r.get("updated_at") or 0)
        if name not in latest or key > (latest[name].get("cp_seq") or 0, latest[name].get("updated_at") or 0):
            latest[name] = r
    ordered = sorted(latest.values(), key=lambda r: (r.get("cp_seq") or 0, r.get("updated_at") or 0))
    total = dict.fromkeys(CHECK_KEYS, 0)
    for f in files:
        row = latest.get(f.name)
        if row is None or not row.get("ledger_counters"):
            return None
        i = ordered.index(row)
        cur = _counter_sum(row)
        prev = _counter_sum(ordered[i - 1]) if i > 0 and ordered[i - 1].get("ledger_counters") else dict.fromkeys(CHECK_KEYS, 0)
        for k in CHECK_KEYS:
            total[k] += cur[k] - prev[k]
    return total


def verify_check(totals, check):
    if check is None:
        return
    mine = dict(messages_parsed=totals["parsed"], messages_rejected=totals["rejected"], duplicates=totals["duplicates"],
                sequence_gaps=totals["sequence_gaps"], missing_messages=totals["missing_messages"],
                messages_accepted=totals["accepted"], bytes_read_uncompressed=totals["bytes"])
    bad = {k: (mine[k], check[k]) for k in CHECK_KEYS if mine[k] != check[k]}
    if bad:
        raise ValueError(f"the replayed extractor totals disagree with the ingest checkpoint (replay, checkpoint): {bad}")


# ------------------------------------------------------------------------------------------------ publishes, grades
def build_publishes(st, run, zone, floor_cells, t0_ts, step_seconds=STEP_SECONDS):
    by_t = {}
    for r in st.select("costmap", {"run": run, "zone": zone}):
        by_t.setdefault(r["published_at"], []).append(r)
    out = []
    for t in sorted(by_t):
        rows = by_t[t]
        zmap = {r["cell"]: r["cost"] for r in rows}
        pr = hotspot_score.precision_recall(zmap, floor_cells, ks=(20,))[20]
        cells = [[r["cell"], round(r["cost"], 4), r["stalls"]] for r in sorted(rows, key=lambda r: (-r["cost"], r["cell"]))
                 if r["cost"] > 0]
        out.append(dict(t=t, step=(t - t0_ts) // step_seconds, cells=cells, precision_at_20=pr["precision"],
                        hits_at_20=pr["hits"], n_flagged=len(hotspot_score.ranked_cells(zmap))))
    return out


def _claim(d):
    c = d["claim"]
    return json.loads(c) if isinstance(c, str) else (c or {})


def build_grades(st, run, zone, publishes, t0_ts, step_seconds=STEP_SECONDS):
    decs = [d for d in st.select("decisions", {"run": run, "kind": "hotspot_forecast"})
            if d["subject"].startswith(f"Z{zone}:")]
    by_id = {d["id"]: d for d in decs}
    rows_by_id = {}
    for g in st.select("forecast_grades", {"run": run}):
        if g["id"] in by_id:
            rows_by_id.setdefault(g["id"], []).append(g)
    per_publish = []
    for p in publishes:
        mine = [d for d in decs if d["decided_at"] == p["t"]]
        rank, count, truth = dict(ok=0, off=0), dict(ok=0, off=0), dict(hit=0, false_alarm=0)
        n_open = unranked = 0
        kinds = set()
        for d in mine:
            rows = rows_by_id.get(d["id"], [])
            has_outcome = False
            for g in rows:
                src, v = g["grade_source"], g["verdict"]
                if src == "outcome" and v in rank:
                    rank[v] += 1
                    has_outcome = True
                    kinds.add("rank" if d.get("claim_version", 1) >= 2 and "top_k" in _claim(d) else "count")
                elif src == "outcome_count" and v in count:
                    count[v] += 1
                elif src == "truth" and v in truth:
                    truth[v] += 1
            if not has_outcome and d["status"] == "open":
                n_open += 1
            if d.get("verdict") == "unranked":
                unranked += 1
        kind = None if not kinds else (next(iter(kinds)) if len(kinds) == 1 else "mixed")
        ends = [g["window_end"] for d in mine for g in rows_by_id.get(d["id"], [])
                if g["grade_source"] in ("outcome", "outcome_count") and g.get("window_end") is not None]
        end = max(ends) if ends else None
        per_publish.append(dict(t=p["t"], forecasts=len(mine), rank=rank, count=count, truth=truth, open=n_open,
                                unranked=unranked, outcome_kind=kind, window_end=end,
                                window_end_step=None if end is None else (end - t0_ts) // step_seconds))
    events = {}
    for gid, rows in rows_by_id.items():
        for g in rows:
            t = g["window_end"] if g.get("window_end") is not None else by_id[gid]["decided_at"]
            e = events.setdefault(t, dict(rank_ok=0, rank_off=0, truth_hit=0, truth_false_alarm=0))
            key = {("outcome", "ok"): "rank_ok", ("outcome", "off"): "rank_off", ("truth", "hit"): "truth_hit",
                   ("truth", "false_alarm"): "truth_false_alarm"}.get((g["grade_source"], g["verdict"]))
            if key:
                e[key] += 1
    timeline, cum = [], dict(rank_ok=0, rank_off=0, truth_hit=0, truth_false_alarm=0)
    for t in sorted(events):
        for k in cum:
            cum[k] += events[t][k]
        timeline.append(dict(t=t, step=(t - t0_ts) // step_seconds, **cum))
    return dict(per_publish=per_publish, timeline=timeline)


def build_episodes(rows, zone, t0_ts, step_seconds=STEP_SECONDS):
    out = []
    for e in rows:
        if str(e["zone"]) != str(zone):
            continue
        out.append(dict(start_step=(e["start"] - t0_ts) // step_seconds,
                        end_step=None if e.get("end") is None else (e["end"] - t0_ts) // step_seconds,
                        robot=e["robot"], cell=list(e["cell"]), cause=e["cause"], resolution=e["resolution"],
                        left_censored=bool(e.get("left_censored"))))
    return sorted(out, key=lambda e: (e["start_step"], e["robot"]))


# ------------------------------------------------------------------------------------------------ env layer (own process)
def _grid_of(hook):
    rows, cols = hook.grid_size
    return dict(width=int(cols), height=int(rows),
                highway=["".join(str(int(hook.highways[y, x])) for x in range(cols)) for y in range(rows)],
                goals=[[int(x), int(y)] for x, y in hook.goals],
                shelves=sorted([int(s.x), int(s.y)] for s in hook.shelfs))


def _kind(agent, i, num_agvs):
    return "agv" if i < num_agvs else "picker"


def env_worker(job):
    """Runs in a fresh spawned process, so exactly one env is ever built there. job = dict(env_id, steps, seed, zone,
    run=None | the run_zone cfg). Returns dict(grid, kinds {serial: kind}, lines (with_map only), deliveries, pick_rate)."""
    from warehouse_rl.env import WarehouseEnv

    seen = {}

    def capture(env):
        hook = env.env
        seen["grid"] = _grid_of(hook)
        seen["kinds"] = {f"Z{job['zone']}-{a.id:02d}": _kind(a, i, hook.num_agvs) for i, a in enumerate(hook.agents)}

    if job["run"] is None:
        env = WarehouseEnv(job["env_id"], max_steps=job["steps"])
        try:
            env.reset(seed=job["seed"])
            capture(env)
        finally:
            env.close()
        return dict(seen, lines=None, deliveries=None, pick_rate=None)

    class ListSink:
        def __init__(self):
            self.lines = []

        def write(self, serial, line, timestamp=None, header_id=None):
            self.lines.append(line)

        def stats(self):
            return dict(messages=len(self.lines), bytes_uncompressed=sum(map(len, self.lines)))

        def close(self):
            pass

    sink = ListSink()
    res = emitter.run_zone(job["run"], sink, on_ready=capture)
    return dict(seen, lines=sink.lines, deliveries=res["deliveries"], pick_rate=res["pick_rate"])


def run_env_worker(job):
    ctx = mp.get_context("spawn")
    with ProcessPoolExecutor(max_workers=1, mp_context=ctx) as ex:
        return ex.submit(env_worker, job).result()


# ------------------------------------------------------------------------------------------------ with_map
def with_map_job(closed_loop, zone, run_cfg, log=print):
    """(job, info) for the optional layer, or None (with a log line) when the closed-loop files are missing."""
    base = Path(closed_loop)
    summary_p, map_p = base / "summary.json", base / "phaseA" / "costmap.json"
    if not summary_p.is_file() or not map_p.is_file():
        log(f"replay_export: no with_map layer ({summary_p} or {map_p} missing)")
        return None
    summary = json.loads(summary_p.read_text())
    arm = summary.get("headline_arm")
    if not arm or arm not in summary.get("arms", {}):
        log(f"replay_export: no with_map layer (no usable headline_arm in {summary_p})")
        return None
    import evaluate as ev

    tag, generated_at, zones = ev._load_costmap(map_p)
    if summary.get("map_tag") not in (None, tag):
        raise ValueError(f"{map_p} has tag {tag} but {summary_p} names map_tag {summary['map_tag']}")
    seed_base = run_cfg["seed_base"]
    cost_map = ev._cost_map_for_seed(zones, seed_base + int(zone), seed_base)
    alpha = float(summary["arms"][arm]["alpha"])
    cfg = dict(zone=int(zone), seed=seed_base + int(zone), steps=run_cfg["steps"], env_id=run_cfg["env_id"],
               policy=run_cfg["policy"], disturb=run_cfg["disturb"], recovery=run_cfg["recovery"], t0=run_cfg["t0"],
               cost_map=cost_map, cost_alpha=alpha)
    info = dict(arm=arm, alpha=alpha, map_path=posixpath.join(closed_loop.replace(os.sep, "/"), "phaseA", "costmap.json"),
                map_generated_at=generated_at, map_tag=tag)
    return cfg, info


WITH_MAP_NOTE = ("Re-simulation of this zone's seed with the cost-aware router. The map is the FINAL phaseA map, built from "
                 "this same seed's episode, applied from step 0 (in-sample, not learned live). No detector episodes exist "
                 "for this layer, so 'stuck' never occurs here and 'stalled' comes from stall extraction only.")


# ------------------------------------------------------------------------------------------------ assembly
def build_payload(run_dir, store_spec, zone, closed_loop=None, env_runner=None, log=print,
                  run_dir_arg=None, closed_loop_arg=None):
    zone = str(zone)
    run_dir = Path(run_dir)
    truth = json.loads((run_dir / "truth.json").read_text())
    if zone not in truth["zones"]:
        raise ValueError(f"truth.json has no zone {zone}")
    ledger_p = run_dir / "emit_ledger.json"
    emit = json.loads(ledger_p.read_text()) if ledger_p.exists() else {}
    cfg = emit.get("config") or {}
    run = json.loads((run_dir / "costmap.json").read_text())["run"]
    steps = truth["steps"]
    t0_ts = epoch_of(cfg.get("t0") or emitter.DEFAULT_T0)
    seed = truth["zones"][zone]["seed"]
    floor = truth["zones"][zone]["floor_cells"]
    zrow = next((z for z in emit.get("zones", []) if str(z.get("zone")) == zone), {})
    expected = zrow.get("expected_messages")

    files = zone_files(run_dir, zone)
    if not files:
        raise ValueError(f"no zone{zone}-*.jsonl.gz files under {run_dir}")
    messages = hotspot.read_messages(str(run_dir / f"zone{zone}-*.jsonl.gz"))
    st = store_mod.open_store(store_spec, run)
    try:
        episode_rows = st.select("stuck_episodes", {"run": run, "zone": zone})
        stalls = hotspot.extract_stalls(messages, run)
        hotspot.annotate_episodes(stalls, episode_rows)
        check = ingest_check(st, run, files)
        publishes = build_publishes(st, run, zone, floor, t0_ts)
        grades = build_grades(st, run, zone, publishes, t0_ts)
    finally:
        st.close()

    wm = with_map_job(closed_loop, zone, dict(seed_base=truth["seed_base"], steps=steps, env_id=truth["env_id"],
                                              policy=cfg.get("policy", emitter.DEFAULT_POLICY),
                                              disturb=truth["disturb"], recovery=cfg.get("recovery"),
                                              t0=cfg.get("t0") or emitter.DEFAULT_T0), log) if closed_loop else None
    if closed_loop and wm is None:
        closed_loop = None
    job = dict(env_id=truth["env_id"], steps=steps, seed=seed, zone=zone, run=wm[0] if wm else None)
    env = (env_runner or run_env_worker)(job)
    grid = env["grid"]
    robots = [dict(serial=s, kind=k) for s, k in sorted(env["kinds"].items())]

    series, totals = replay_extractor(files, t0_ts, steps, expected, zrow.get("bytes_compressed"))
    verify_check(totals, check)
    frames = build_frames(messages, robots, t0_ts, steps, episode_rows, stalls, grid)

    payload = dict(
        meta=dict(run=run, zone=zone, env_id=truth["env_id"], steps=steps, step_seconds=STEP_SECONDS, t0_ts=t0_ts,
                  seed=seed, disturb=truth["disturb"], policy=cfg.get("policy"), recovery=cfg.get("recovery"),
                  schema=SCHEMA,
                  source=dict(run_dir=run_dir_arg if run_dir_arg is not None else str(run_dir),
                              store=store_spec if store_spec is not None else None,
                              closed_loop=closed_loop_arg if closed_loop_arg is not None else closed_loop)),
        grid=grid, robots=robots, frames=frames,
        obstacles=[dict(kind="floor", cell=c, p=floor[c], hidden_from_analyser=True) for c in sorted(floor)],
        extractor=dict(series=series, totals=totals, check=check),
        publishes=publishes, grades=grades,
        episodes=build_episodes(episode_rows, zone, t0_ts),
        stalls=[[s["robot"], s["cell"], (s["start"] - t0_ts) // STEP_SECONDS, (s["end"] - t0_ts) // STEP_SECONDS,
                 bool(hotspot.counted(s))] for s in stalls if s["zone"] == zone])
    if wm:
        cfg_wm, info = wm
        wm_msgs = []
        for line in env["lines"]:
            m, reason = parse_line(line)
            if m is None:
                raise ValueError(f"the with_map re-simulation emitted an unparsable line ({reason})")
            wm_msgs.append(m)
        wm_stalls = hotspot.extract_stalls(wm_msgs, run)
        wm_frames = build_frames(wm_msgs, robots, t0_ts, steps, [], wm_stalls, grid)
        payload["with_map"] = dict(arm=info["arm"], alpha=info["alpha"], map_path=info["map_path"],
                                   map_generated_at=info["map_generated_at"], map_tag=info["map_tag"],
                                   deliveries=env["deliveries"], pick_rate=round(env["pick_rate"], 2), frames=wm_frames,
                                   note=WITH_MAP_NOTE)
    return payload


def write_data_js(payload, out, max_bytes=MAX_BYTES):
    """Atomic write of `window.REPLAY = <compact json>;\\n`; raises (nothing written) above max_bytes."""
    body = PREFIX + json.dumps(payload, allow_nan=False, separators=(",", ":")) + ";\n"
    data = body.encode("utf-8")
    if len(data) > max_bytes:
        raise ValueError(f"replay payload is {len(data)} bytes, over the {max_bytes} byte cap")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, out)
    return len(data)


def read_data_js(path):
    text = Path(path).read_text(encoding="utf-8")
    if not text.startswith(PREFIX):
        raise ValueError(f"{path} does not start with {PREFIX!r}")
    return json.loads(text[len(PREFIX):].rstrip().removesuffix(";"))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--run-dir", required=True)
    p.add_argument("--store", required=True, help="jsonl:<dir> or clickhouse://host[:port]/db (read only)")
    p.add_argument("--zone", default="0")
    p.add_argument("--out", required=True)
    p.add_argument("--closed-loop", default=None, metavar="DIR", help="results/closed_loop: adds the with_map layer")
    a = p.parse_args(argv)
    try:
        payload = build_payload(a.run_dir, a.store, a.zone, a.closed_loop, run_dir_arg=a.run_dir,
                                closed_loop_arg=a.closed_loop)
        n = write_data_js(payload, a.out)
    except (ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    pubs = ", ".join(f"{q['t']}: {q['precision_at_20']}" for q in payload["publishes"])
    print(f"replay zone {a.zone}: {payload['meta']['steps']} steps x {len(payload['robots'])} robots, "
          f"{len(payload['publishes'])} publishes (precision@20 {pubs}), {len(payload['episodes'])} episodes, "
          f"with_map {'yes' if 'with_map' in payload else 'no'}, {n} bytes -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

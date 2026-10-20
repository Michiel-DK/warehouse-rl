"""S12A per-robot time budget: where does each AGV's shift go, with waiting split from stuck.

Usage: python fleet/timebudget.py --glob 'DIR/*.jsonl.gz' --run RUN --stations PATH|auto --out PATH
       [--shift-s 3600] [--store jsonl:DIR]

An accounting on top of the existing message stream. It does not change what a stall is: the detector
(fleet_analyser.detector.Detector, DEFAULT_STUCK_AFTER) is imported unchanged, nothing under fleet_analyser/ is edited,
and this module reads only parse.Message plus the station / shelf cell lists. It reads no simulator-side block of the
message and no scoring file.

Interval rule: message i of a robot owns [ts_i, ts_{i+1}); the robot's last message owns 0 s; span = last ts - first
ts. Per robot, messages are sorted by (ts, header_id) and any message whose ts <= the previous kept ts is dropped (the
rule of Detector._process_batch). Each owned interval goes to exactly one of seven buckets, decided by message i and the
stopped run it belongs to. Precedence, highest first:
  faulted        errors non-empty (Message.faulted), even when driving is true
  > moving       driving true
  > waiting_station  driving false, orderId non-empty, (x, y) in the station cell set
  > waiting_shelf    driving false, orderId non-empty, (x, y) within Manhattan distance <= 1 of a shelf slot (the slot
                     itself included) and loads empty (an AGV waiting for a picker)
  > stuck / stopped_short  driving false, orderId non-empty, anywhere else
  > idle         orderId empty, driving false
A stopped run is exactly the detector's run: it starts at a message with driving false and a non-empty orderId when no
run is open, continues while driving is false and the orderId is unchanged (faulted messages inside it continue it) and
ends at the first message that breaks that; a breaking message that is itself driving false with another non-empty
orderId opens the next run. A run still open at stream end is judged on the same rule. A run is stuck iff (max ts of a
message inside it) - (run start ts) >= DEFAULT_STUCK_AFTER, which is when the Detector opens an episode; the seconds of
a stuck run that fall to the "anywhere else" rule go to stuck, of any other run to stopped_short (a whole run is one or
the other).

Robot scope: the budget is for AGVs. Pickers are in the same stream; they are reported apart under zones[z].pickers with
the same per-robot fields and are excluded from totals, jobs_per_robot_hour and same_minute_stops. Kinds come from the
layout worker (--stations auto) or from an optional "pickers" list in the --stations file (absent = all AGVs).
Per robot the bucket sum equals the span (checked by check_bucket_sum, which raises ValueError; integer seconds).

Layouts (--stations auto): every (env_id, seed) layout is computed by its own freshly spawned process (a new
ProcessPoolExecutor(max_workers=1) per call), because Agent.counter / Shelf.counter are class attributes. The station
cells are the env goals and the shelf slots the env shelf positions right after reset.

Output (sort_keys, indent 1, no wall-clock value, so two runs give byte-identical files): zones, run, src. Nothing is
written except --out. Elapsed time goes to stdout only.
"""
import argparse
import concurrent.futures as cf
import glob as _glob
import hashlib
import json
import multiprocessing as mp
import sys
import time
from pathlib import Path

FLEET = Path(__file__).resolve().parent
REPO = FLEET.parent
for _p in (FLEET, REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fleet_analyser.detector import DEFAULT_STUCK_AFTER, Detector  # noqa: E402
from fleet_analyser.hotspot import read_messages  # noqa: E402
from fleet_analyser.parse import iso  # noqa: E402
from fleet_analyser.store import JsonlStore  # noqa: E402

BUCKETS = ("faulted", "moving", "waiting_station", "waiting_shelf", "stuck", "stopped_short", "idle")
SHELF_ADJACENT_MANHATTAN = 1
SAME_MINUTE_SHARE = 0.8
LAYOUT_THREADS = 4


# ------------------------------------------------------------------------------------------------ layouts
def _layout_worker(job):
    """Runs in a fresh spawned process: exactly one env is built here."""
    from warehouse_rl.env import WarehouseEnv

    env = WarehouseEnv(job["env_id"], max_steps=job["steps"])
    try:
        env.reset(seed=job["seed"])
        hook = env.env
        return dict(goals=[[int(x), int(y)] for x, y in hook.goals],
                    shelves=sorted([int(s.x), int(s.y)] for s in hook.shelfs),
                    agent_ids=[int(a.id) for a in hook.agents], num_agvs=int(hook.num_agvs))
    finally:
        env.close()


def run_layout_worker(job):
    """One layout, one new process, one env (never reuse a pool for a second layout)."""
    ctx = mp.get_context("spawn")
    with cf.ProcessPoolExecutor(max_workers=1, mp_context=ctx) as ex:
        return ex.submit(_layout_worker, job).result()


def kinds_of(layout, zone):
    return {f"Z{zone}-{i:02d}": "agv" if k < layout["num_agvs"] else "picker"
            for k, i in enumerate(layout["agent_ids"])}


def auto_layouts(glob_dir, zones):
    """{zone: dict(goals, shelves, pickers (set of serials), layout (description))} for the zones present."""
    ledger_path = Path(glob_dir) / "emit_ledger.json"
    if not ledger_path.is_file():
        raise SystemExit(f"timebudget: --stations auto needs {ledger_path}")
    ledger = json.loads(ledger_path.read_text())
    cfg = ledger["config"]
    seeds = {str(z["zone"]): z["seed"] for z in ledger["zones"]}
    missing = [z for z in zones if z not in seeds]
    if missing:
        raise SystemExit(f"timebudget: zones {missing} are in the messages but not in {ledger_path}")
    jobs = {}  # (env_id, seed) -> job
    for z in zones:
        jobs[(cfg["env_id"], seeds[z])] = dict(env_id=cfg["env_id"], steps=cfg["steps"], seed=seeds[z])
    results = {}
    with cf.ThreadPoolExecutor(max_workers=LAYOUT_THREADS) as pool:
        futs = {k: pool.submit(run_layout_worker, j) for k, j in sorted(jobs.items())}
        for k, f in futs.items():
            results[k] = f.result()
    out = {}
    for z in zones:
        key = (cfg["env_id"], seeds[z])
        lay = results[key]
        kinds = kinds_of(lay, z)
        out[z] = dict(goals=lay["goals"], shelves=lay["shelves"],
                      pickers={s for s, k in kinds.items() if k == "picker"},
                      layout=dict(source="auto", env_id=cfg["env_id"], steps=cfg["steps"], seed=seeds[z]))
    return out, str(ledger_path)


def path_layouts(stations_path, zones):
    data = json.loads(Path(stations_path).read_text())
    out = {}
    for z in zones:
        out[z] = dict(goals=[[int(x), int(y)] for x, y in data["stations"]],
                      shelves=[[int(x), int(y)] for x, y in data["shelves"]],
                      pickers=set(data.get("pickers", [])), layout=dict(source="path", path=str(stations_path)))
    return out


def cell_sets(goals, shelves):
    stations = {(x, y) for x, y in goals}
    near = set()
    for sx, sy in shelves:
        for dx in range(-SHELF_ADJACENT_MANHATTAN, SHELF_ADJACENT_MANHATTAN + 1):
            for dy in range(-SHELF_ADJACENT_MANHATTAN, SHELF_ADJACENT_MANHATTAN + 1):
                if abs(dx) + abs(dy) <= SHELF_ADJACENT_MANHATTAN:
                    near.add((sx + dx, sy + dy))
    classes = dict(n_station_cells=len(stations), n_shelf_slots=len({tuple(s) for s in shelves}),
                   n_shelf_adjacent_cells=len(near - stations))
    return stations, near, classes


# ------------------------------------------------------------------------------------------------ per robot
def kept_messages(msgs):
    """Sorted by (ts, header_id); a message whose ts <= the previous kept ts is dropped."""
    out = []
    for m in sorted(msgs, key=lambda m: (m.ts, m.header_id)):
        if out and m.ts <= out[-1].ts:
            continue
        out.append(m)
    return out


def stopped_runs(kept):
    """The detector's runs over one robot's kept messages: list of (first index, last index) and the run index of every
    message (None outside runs)."""
    runs, run_of = [], [None] * len(kept)
    cur = None  # [start index, order id]
    for i, m in enumerate(kept):
        if cur is not None and not (not m.driving and m.order_id == cur[1]):
            runs.append((cur[0], i - 1))
            cur = None
        if cur is None and not m.driving and m.order_id != "":
            cur = [i, m.order_id]
        if cur is not None:
            run_of[i] = len(runs)
    if cur is not None:
        runs.append((cur[0], len(kept) - 1))
    return runs, run_of


def run_is_stuck(kept, run):
    return kept[run[1]].ts - kept[run[0]].ts >= DEFAULT_STUCK_AFTER


def check_bucket_sum(serial, seconds, span):
    """An explicit raise (not an assert: python -O must not strip it) when a robot's buckets do not add up to its span."""
    total = sum(seconds.values())
    if total != span:
        raise ValueError(f"timebudget: robot {serial}: bucket sum {total} != span {span} ({seconds})")


def robot_budget(kept, stations, near_shelf, shift_s):
    """(record, runs) for one robot. record = dict(seconds, share, span_s, per_shift_s, jobs)."""
    seconds = {b: 0 for b in BUCKETS}
    runs, run_of = stopped_runs(kept)
    stuck_flags = [run_is_stuck(kept, r) for r in runs]
    for i in range(len(kept) - 1):
        m = kept[i]
        dt = kept[i + 1].ts - m.ts
        if m.faulted:
            b = "faulted"
        elif m.driving:
            b = "moving"
        elif m.order_id == "":
            b = "idle"
        elif (m.x, m.y) in stations:
            b = "waiting_station"
        elif (m.x, m.y) in near_shelf and not m.loaded:
            b = "waiting_shelf"
        else:
            b = "stuck" if stuck_flags[run_of[i]] else "stopped_short"
        seconds[b] += dt
    span = kept[-1].ts - kept[0].ts
    check_bucket_sum(kept[0].serial, seconds, span)
    jobs = 0
    prev = None
    for m in kept:
        if m.order_id != "" and (prev is None or m.order_id != prev):
            jobs += 1
        prev = m.order_id
    share = {b: (seconds[b] / span if span else None) for b in BUCKETS}
    per_shift = {b: (share[b] * shift_s if span else None) for b in BUCKETS}
    rec = dict(seconds=seconds, share=share, span_s=span, per_shift_s=per_shift, jobs=jobs)
    starts = {(kept[a].serial, kept[a].ts) for (a, z), s in zip(runs, stuck_flags) if s}
    return rec, starts


def totals_of(records):
    seconds = {b: sum(r["seconds"][b] for r in records) for b in BUCKETS}
    span = sum(r["span_s"] for r in records)
    return dict(seconds=seconds, share={b: (seconds[b] / span if span else None) for b in BUCKETS}, span_s=span,
                robots=len(records))


def stop_minutes(agv_kept):
    """Epoch minutes in which >= SAME_MINUTE_SHARE of the AGVs (with a message) have a stop event."""
    n_robots = len(agv_kept)
    per_minute = {}
    for serial, kept in agv_kept.items():
        for prev, cur in zip(kept, kept[1:]):
            if prev.driving and not cur.driving:
                per_minute.setdefault(cur.ts // 60, set()).add(serial)
    flagged = sorted(m for m, s in per_minute.items() if len(s) >= SAME_MINUTE_SHARE * n_robots)
    return dict(count=len(flagged), minutes=[iso(m * 60) for m in flagged], threshold=SAME_MINUTE_SHARE,
                n_robots=n_robots)


# ------------------------------------------------------------------------------------------------ episodes
def recompute_episodes(messages):
    """Detector() fed every kept message in (ts, serial) order, then end_all(); last open/close event per episode_id."""
    det = Detector()
    rows = {}
    events = []
    for m in sorted(messages, key=lambda m: (m.ts, m.serial)):
        events += det.feed(m)
    events += det.end_all()
    for ev in events:
        if ev["kind"] in ("episode_open", "episode_close"):
            rows[ev["episode_id"]] = {k: v for k, v in ev.items() if k not in ("kind", "decided_by")}
    return list(rows.values())


def store_present(store_dir):
    return store_dir is not None and Path(store_dir).is_dir() and (Path(store_dir) / "stuck_episodes.jsonl").is_file()


def store_hash(store_dir):
    h = hashlib.sha256()
    root = Path(store_dir)
    for p in sorted(q for q in root.rglob("*") if q.is_file()):
        h.update(str(p.relative_to(root)).encode() + b"\0")
        h.update(p.read_bytes())
    return h.hexdigest()


def store_episodes(store_dir, run):
    st = JsonlStore(store_dir)
    rows = st.select("stuck_episodes", {"run": run})
    if not rows:
        raise SystemExit(f"timebudget: store {store_dir} has no stuck_episodes rows for run {run!r} (wrong --run?)")
    last = {}
    for r in rows:
        last[r["episode_id"]] = r
    return list(last.values())


def station_waits(eps, stations, near_shelf, pickers):
    n = len(eps)
    at_station = sum(1 for e in eps if tuple(e["cell"]) in stations)
    at_shelf = sum(1 for e in eps if tuple(e["cell"]) in near_shelf and tuple(e["cell"]) not in stations)
    picker_eps = sum(1 for e in eps if e["robot"] in pickers)
    return dict(episodes=n, at_station=at_station, at_shelf=at_shelf, picker_episodes=picker_eps,
                share_station=at_station / n if n else None, share_shelf=at_shelf / n if n else None,
                share_either=(at_station + at_shelf) / n if n else None)


def _pool_waits(parts, source):
    n = sum(p["episodes"] for p in parts)
    a = sum(p["at_station"] for p in parts)
    b = sum(p["at_shelf"] for p in parts)
    return dict(source=source, episodes=n, at_station=a, at_shelf=b, picker_episodes=sum(p["picker_episodes"] for p in parts),
                share_station=a / n if n else None, share_shelf=b / n if n else None,
                share_either=(a + b) / n if n else None)


# ------------------------------------------------------------------------------------------------ main computation
def compute(messages, run, layouts, episodes, source, shift_s):
    by_zone = {}
    for m in messages:
        by_zone.setdefault(m.zone, {}).setdefault(m.serial, []).append(m)
    ep_by_zone = {}
    for e in episodes:
        ep_by_zone.setdefault(str(e["zone"]), []).append(e)
    zones, all_agv, run_waits, run_cmp = {}, [], [], []
    run_jobs = run_span = run_same = 0
    for z in sorted(by_zone, key=lambda s: (len(s), s)):
        lay = layouts[z]
        stations, near, classes = cell_sets(lay["goals"], lay["shelves"])
        pickers = lay["pickers"]
        robots, pick, agv_kept, starts = {}, {}, {}, set()
        for serial in sorted(by_zone[z]):
            kept = kept_messages(by_zone[z][serial])
            rec, s = robot_budget(kept, stations, near, shift_s)
            starts |= s
            if serial in pickers:
                pick[serial] = rec
            else:
                robots[serial] = rec
                agv_kept[serial] = kept
        ztot = totals_of(list(robots.values()))
        jobs = sum(r["jobs"] for r in robots.values())
        jph = jobs / (ztot["span_s"] / 3600) if ztot["span_s"] else None
        eps = ep_by_zone.get(z, [])
        waits = dict(station_waits(eps, stations, near, pickers), source=source)
        det_starts = {(e["robot"], e["start"]) for e in eps}
        cmp_ = dict(timebudget_stuck_runs=len(starts), detector_episodes=len(eps), start_sets_equal=starts == det_starts)
        same = stop_minutes(agv_kept)
        zones[z] = dict(robots=robots, pickers=pick, totals=ztot, jobs_per_robot_hour=jph, same_minute_stops=same,
                        station_waits_in_stall_list=waits, stuck_runs_vs_detector=cmp_, cell_classes=classes,
                        layout=lay["layout"])
        all_agv += list(robots.values())
        run_jobs += jobs
        run_span += ztot["span_s"]
        run_same += same["count"]
        run_waits.append(waits)
        run_cmp.append(cmp_)
    rtot = totals_of(all_agv)
    run_out = dict(totals=rtot, jobs_per_robot_hour=run_jobs / (run_span / 3600) if run_span else None,
                   same_minute_stops_count=run_same, station_waits_in_stall_list=_pool_waits(run_waits, source),
                   stuck_runs_vs_detector=dict(timebudget_stuck_runs=sum(c["timebudget_stuck_runs"] for c in run_cmp),
                                              detector_episodes=sum(c["detector_episodes"] for c in run_cmp),
                                              start_sets_equal=all(c["start_sets_equal"] for c in run_cmp)))
    return zones, run_out


def parse_store_arg(arg):
    if arg is None:
        return None
    if not arg.startswith("jsonl:"):
        raise SystemExit("timebudget: --store must be jsonl:DIR")
    return arg[len("jsonl:"):]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Per-robot time budget (S12A)")
    ap.add_argument("--glob", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--stations", required=True, help="PATH or auto")
    ap.add_argument("--out", required=True)
    ap.add_argument("--shift-s", type=float, default=3600)
    ap.add_argument("--store", default=None, help="jsonl:DIR (default: DIR/store, DIR = the glob's directory)")
    args = ap.parse_args(argv)
    t_start = time.time()
    out_path = Path(args.out)
    if not out_path.parent.is_dir():
        raise SystemExit(f"timebudget: parent directory of --out does not exist: {out_path.parent}")
    files = sorted(_glob.glob(args.glob))
    if not files:
        raise SystemExit(f"timebudget: no files match {args.glob}")
    glob_dir = str(Path(args.glob).parent)
    store_dir = parse_store_arg(args.store) or str(Path(glob_dir) / "store")
    present = store_present(store_dir)
    hash_before = store_hash(store_dir) if present else None

    messages = read_messages(args.glob)
    zones_present = sorted({m.zone for m in messages}, key=lambda s: (len(s), s))
    if args.stations == "auto":
        layouts, ledger_path = auto_layouts(glob_dir, zones_present)
        stations_sha = None
    else:
        layouts, ledger_path = path_layouts(args.stations, zones_present), None
        stations_sha = hashlib.sha256(Path(args.stations).read_bytes()).hexdigest()
    if present:
        episodes, source = store_episodes(store_dir, args.run), "store"
    else:
        episodes, source = recompute_episodes(messages), "recomputed"
    zones, run_out = compute(messages, args.run, layouts, episodes, source, args.shift_s)
    hash_after = store_hash(store_dir) if present else None
    if hash_after != hash_before:
        print(f"timebudget: store {store_dir} changed during the run", file=sys.stderr)
        return 1
    src = dict(glob=args.glob, files=files, run=args.run, stations=args.stations if args.stations == "auto" else args.stations,
               stations_sha256=stations_sha, emit_ledger=ledger_path, store=store_dir if present else None,
               store_sha256_before=hash_before, store_sha256_after=hash_after, stuck_after=DEFAULT_STUCK_AFTER,
               shelf_adjacent_manhattan=SHELF_ADJACENT_MANHATTAN, same_minute_share=SAME_MINUTE_SHARE,
               shift_s=args.shift_s, script="timebudget.py")
    out_path.write_text(json.dumps(dict(zones=zones, run=run_out, src=src), sort_keys=True, indent=1) + "\n")

    for z, d in zones.items():
        sh = d["totals"]["share"]
        print(f"zone {z}: {len(d['robots'])} robots / {len(d['pickers'])} pickers, span_s {d['totals']['span_s']}, "
              f"moving {_pct(sh['moving'])} station {_pct(sh['waiting_station'])} stuck {_pct(sh['stuck'])}")
    t = run_out["totals"]
    print(f"run {args.run}: {t['robots']} AGVs, span_s {t['span_s']}, source {source}")
    for b in BUCKETS:
        print(f"  {b:16s} {_pct(t['share'][b]):>7s}  {t['seconds'][b]} s")
    w = run_out["station_waits_in_stall_list"]
    print(f"station_waits_in_stall_list: episodes {w['episodes']} at_station {w['at_station']} at_shelf {w['at_shelf']} "
          f"picker_episodes {w['picker_episodes']} share_station {w['share_station']} share_either {w['share_either']}")
    print(f"jobs_per_robot_hour {run_out['jobs_per_robot_hour']}, same_minute_stops {run_out['same_minute_stops_count']}, "
          f"stuck_runs_vs_detector {run_out['stuck_runs_vs_detector']}")
    print(f"elapsed {time.time() - t_start:.1f} s")
    return 0


def _pct(v):
    return "n/a" if v is None else f"{100 * v:.1f}%"


if __name__ == "__main__":
    sys.exit(main())

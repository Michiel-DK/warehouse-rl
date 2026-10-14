"""Publish per-zone cost maps of the bad floor from the fleet stream, and the hotspot_forecast decisions behind them.

Usage: python fleet/costmap.py --glob 'fleet/data/<run>/*.jsonl.gz' [--store jsonl:DIR | clickhouse://HOST[:PORT]/DB]
       [--run NAME] [--window-hours 1] [--half-life-h 1] [--min-stalls 1] [--publish-every S] [--include-occupied]
       [--horizon-s 3600] [--out fleet/data/<run>/costmap.json]
Reads the zone files and the store's stuck_episodes (written by fleet/ingest.py), extracts stalls (fleet_analyser/hotspot.py)
and upserts them into the store's `stalls` table. Publishes at every multiple of --publish-every event seconds after the
first message that is <= the stream end, plus one at the stream end (only the stream end without --publish-every). Per
publish and zone cost = decayed score / the zone's max score (cells with fewer than --min-stalls window stalls are 0 and
omitted), written to the `costmap` table; the LAST publish is written to --out (atomic). Every nonzero cell also gets a
`hotspot_forecast` decision deduped on (kind, Z<zone>:x,y, publish event-time ISO), so a re-run is a no-op.
Every per-cell quantity is per zone: each zone has its own seed and floor layout. Analyst side: input is the stream and the
store only.
"""
import argparse
import json
import os
import sys
from pathlib import Path

FLEET = Path(__file__).resolve().parent
if str(FLEET) not in sys.path:
    sys.path.insert(0, str(FLEET))

from fleet_analyser import decisions, hotspot, store as store_mod  # noqa: E402
from fleet_analyser.parse import iso  # noqa: E402

SCHEMA_VERSION = "fleet-costmap/1"
DEFAULT_HORIZON_S = 3600


def publish_times(first_ts, end_ts, every):
    times = []
    if every:
        t = first_ts + every
        while t <= end_ts:
            times.append(t)
            t += every
    if not times or times[-1] != end_ts:
        times.append(end_ts)
    return times


def cost_zones(stalls, at_ts, window_h, half_life_h, min_stalls, exclude_occupied):
    """{zone: {cell: dict(cost, score, stalls)}} for one publish; only nonzero cells, max cost exactly 1.0 per zone."""
    agg = hotspot.aggregate(stalls, at_ts, window_h, half_life_h, exclude_occupied)
    by_zone = {}
    for (zone, cell), a in agg.items():
        if a["stalls"] >= min_stalls:
            by_zone.setdefault(zone, {})[cell] = a
    out = {}
    for zone, cells in by_zone.items():
        top = max(a["score"] for a in cells.values())
        out[zone] = {c: dict(cost=round(a["score"] / top, 6), score=a["score"], stalls=a["stalls"])
                     for c, a in cells.items()}
        out[zone] = {c: v for c, v in out[zone].items() if v["cost"] > 0}
    return out


def build_costmap(messages, store, run, window_h=1.0, half_life_h=1.0, min_stalls=1, publish_every=None,
                  exclude_occupied=True, horizon_s=DEFAULT_HORIZON_S):
    """Extract + persist stalls, publish cost maps and forecasts. Returns the last publish as the costmap.json dict."""
    if not messages:
        raise ValueError("no messages")
    stalls = hotspot.extract_stalls(messages, run)
    hotspot.annotate_episodes(stalls, store.select("stuck_episodes", {"run": run}))
    store.upsert("stalls", ("run", "zone", "robot", "start"), stalls)
    first_ts, end_ts = min(m.ts for m in messages), max(m.ts for m in messages)
    zones = sorted({m.zone for m in messages})
    last = None
    for t in publish_times(first_ts, end_ts, publish_every):
        maps = cost_zones(stalls, t, window_h, half_life_h, min_stalls, exclude_occupied)
        rows = [dict(run=run, zone=z, published_at=t, cell=c, cost=v["cost"], score=v["score"], stalls=v["stalls"])
                for z, cells in sorted(maps.items()) for c, v in sorted(cells.items())]
        store.upsert("costmap", ("run", "published_at", "zone", "cell"), rows)
        covered = min(window_h * 3600, t - first_ts)
        if covered > 0:
            for z, cells in sorted(maps.items()):
                ranked = sorted(cells.items(), key=lambda kv: (-kv[1]["cost"], kv[0]))
                for k, (c, v) in enumerate(ranked, 1):
                    x = v["stalls"] * 3600 / covered
                    decisions.record_decision(
                        store, run=run, kind="hotspot_forecast", subject=f"Z{z}:{c}", start_iso=iso(t), decided_at=t,
                        claim=dict(expected_stalls_next_hour=x, cost=v["cost"], rank=k, horizon_s=horizon_s,
                                   window_hours=window_h),
                        rationale=f"{v['stalls']} stalls at {c} in zone {z} over the last {covered:.0f}s; cost "
                                  f"{v['cost']}, rank {k}",
                        expected=x, grade_after=t + horizon_s)
        last = dict(schema_version=SCHEMA_VERSION, run=run, generated_at=iso(t), window_hours=window_h,
                    half_life_h=half_life_h, min_stalls=min_stalls, exclude_occupied=exclude_occupied,
                    zones={z: {c: v["cost"] for c, v in sorted(maps.get(z, {}).items())} for z in zones})
    return last


def write_json(path, doc):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w") as f:
        json.dump(doc, f, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def build_parser():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--glob", required=True, help="zone<z>-<nnn>.jsonl.gz files of the run")
    p.add_argument("--store", default=None, help="jsonl:<dir> (default fleet/data/<run>/store) or clickhouse://...")
    p.add_argument("--run", default=None, help="run name (default: name of the glob's directory, as for ingest)")
    p.add_argument("--window-hours", type=float, default=1.0)
    p.add_argument("--half-life-h", type=float, default=1.0)
    p.add_argument("--min-stalls", type=int, default=1)
    p.add_argument("--publish-every", type=int, default=None, metavar="S", help="event seconds between publishes")
    p.add_argument("--include-occupied", action="store_true", help="also count stalls whose cell another robot occupied")
    p.add_argument("--horizon-s", type=int, default=DEFAULT_HORIZON_S)
    p.add_argument("--out", default=None, help="costmap.json path (default fleet/data/<run>/costmap.json)")
    return p


def main(argv=None):
    p = build_parser()
    a = p.parse_args(argv)
    if a.window_hours <= 0 or a.half_life_h <= 0 or a.min_stalls < 1 or a.horizon_s < 1 \
            or (a.publish_every is not None and a.publish_every < 1):
        p.error("--window-hours and --half-life-h must be > 0; --min-stalls, --horizon-s, --publish-every >= 1")
    run = a.run or os.path.basename(os.path.dirname(os.path.abspath(a.glob))) or "run"
    try:
        st = store_mod.open_store(a.store, run)
    except ValueError as e:
        p.error(str(e))
    messages = hotspot.read_messages(a.glob)
    if not messages:
        print(f"error: no messages under {a.glob}", file=sys.stderr)
        return 2
    doc = build_costmap(messages, st, run, a.window_hours, a.half_life_h, a.min_stalls, a.publish_every,
                        not a.include_occupied, a.horizon_s)
    st.close()
    out = a.out or str(FLEET / "data" / run / "costmap.json")
    write_json(out, doc)
    n = {z: len(c) for z, c in doc["zones"].items()}
    print(f"costmap {run}: {len(messages)} messages, last publish {doc['generated_at']}, nonzero cells per zone {n} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

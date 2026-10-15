"""Emit synthetic VDA 5050-shaped fleet state: one JSON line per robot per step, per zone (one medium-map episode).

Usage: python fleet/emit.py --zones 2 --steps 200 --speed 0 --sink file --dir /tmp/fleet-run
Zone z runs seed --seed-base + z, in its own process (one env per process). Workers: --workers, else SCHED_WORKERS,
else os.cpu_count() - 2. Pacing (--rate) is about wall-clock emission speed and has nothing to do with the disturbance
rates: 'flat' (default) emits as fast as the sim runs, 'realtime' paces to simulated time / --speed (--speed 0 = flat
out) and needs zones <= workers. Output: <dir>/zone<z>-<nnn>.jsonl.gz and <dir>/emit_ledger.json (atomic rewrites).
Message contract and field semantics: docs/SCOPE.md "S5A".
Demo (NOT a measurement; roadblocks appended while it runs; --demo and --control-file go together):
  python fleet/emit.py --demo --control-file /tmp/ctl.jsonl --rate realtime --speed 5 --dir /tmp/fleet-demo &
  echo '{"t": null, "floor": {"5,3": 0.9}}' >> /tmp/ctl.jsonl     # or {"t": 40, "breakdown": {"agent": 2, "duration": 30}}
Demo noise (S8I, needs --demo): --demo-noise adds malformed and duplicate lines and one headerId jump per zone (extra lines
only, see fleet_analyser/emitter.py), for the replay page's log panel.
Live mode (S8G, fleet/live.py; demo only): --cost-map-file PATH [--cost-alpha A] re-reads a published costmap.json before
every step, and the file sink sync-flushes after every step so a reader sees the stream live.
"""
import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

FLEET = Path(__file__).resolve().parent
REPO = FLEET.parent
if str(FLEET) not in sys.path:
    sys.path.insert(0, str(FLEET))

from fleet_analyser import emitter, sinks  # noqa: E402


def build_parser():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--zones", type=int, default=1, help="number of zones (episodes); zone z uses seed base + z")
    p.add_argument("--steps", type=int, default=emitter.DEFAULT_STEPS, help="steps per zone (5 s of simulated time each)")
    p.add_argument("--env", default=emitter.DEFAULT_ENV)
    p.add_argument("--seed-base", type=int, default=0)
    p.add_argument("--disturb", default=emitter.DEFAULT_DISTURB, help="disturbance preset name or JSON object")
    p.add_argument("--policy", choices=[emitter.DEFAULT_POLICY], default=emitter.DEFAULT_POLICY)
    p.add_argument("--t0", default=emitter.DEFAULT_T0, help="simulated start time, ISO 8601 UTC with Z, or 'now'")
    p.add_argument("--workers", type=int, default=None)
    p.add_argument("--rate", choices=["flat", "realtime"], default="flat",
                   help="wall-clock pacing of the emission: flat = no sleeping, realtime = pace to simulated time")
    p.add_argument("--speed", type=float, default=1.0,
                   help="realtime pacing factor (1 = one 5 s step per 5 s wall time); 0 = flat out")
    p.add_argument("--sink", choices=["file", "kafka"], default="file")
    p.add_argument("--dir", default=None, help="file sink output directory (default fleet/data/run-<timestamp>)")
    p.add_argument("--rotate-bytes", type=int, default=sinks.DEFAULT_ROTATE_BYTES,
                   help="rotate a zone's file before it would exceed this many uncompressed bytes")
    p.add_argument("--topic", default="fleet.state")
    p.add_argument("--bootstrap", default="localhost:9092")
    p.add_argument("--ledger-dir", default=None, help="ledger directory for the kafka sink")
    p.add_argument("--ledger-interval", type=float, default=emitter.DEFAULT_LEDGER_INTERVAL,
                   help="seconds between ledger rewrites")
    p.add_argument("--demo", action="store_true",
                   help="demo mode (not a measurement): inject floor patches / breakdowns from --control-file")
    p.add_argument("--control-file", default=None, help="demo control file, one JSON command per line (needs --demo)")
    p.add_argument("--demo-noise", action="store_true",
                   help="demo only (needs --demo, default off): add ~0.5%% malformed lines, ~1%% exact duplicates and one "
                        "headerId jump per zone, as extra lines; nothing real is dropped")
    p.add_argument("--cost-map-file", default=None, metavar="PATH",
                   help="demo only: costmap.json re-read before every step; the router uses it with --cost-alpha")
    p.add_argument("--cost-alpha", type=float, default=None,
                   help="demo only, needs --cost-map-file: router weight 1 + alpha * cost (default 4)")
    return p


def main(argv=None):
    p = build_parser()
    a = p.parse_args(argv)
    if a.zones < 1 or a.steps < 1 or a.seed_base < 0:
        p.error("--zones and --steps must be >= 1 and --seed-base >= 0")
    if a.demo != (a.control_file is not None):
        p.error("--demo and --control-file must be given together")
    if a.demo_noise and not a.demo:
        p.error("--demo-noise is a demo-mode option (it needs --demo)")
    if (a.cost_map_file is not None or a.cost_alpha is not None) and not a.demo:
        p.error("--cost-map-file and --cost-alpha are demo-mode options (they need --demo)")
    if a.cost_alpha is not None and a.cost_map_file is None:
        p.error("--cost-alpha needs --cost-map-file")
    if a.speed < 0 or a.ledger_interval <= 0 or a.rotate_bytes < 1:
        p.error("--speed must be >= 0, --ledger-interval > 0 and --rotate-bytes >= 1")
    try:
        t0 = emitter.resolve_t0(a.t0)
        import evaluate as ev
        from warehouse_rl.disturb import resolve_disturb
        from warehouse_rl.recovery import normalise_recovery

        disturb_tag, disturb = resolve_disturb(a.disturb)
        recovery = normalise_recovery({"name": "timeout"})
        workers = ev.resolve_workers(a.workers, os.environ)
    except ValueError as e:
        p.error(str(e))
    if a.rate == "realtime" and a.zones > workers:
        p.error(f"--rate realtime needs --zones <= workers (zones {a.zones} > workers {workers}): "
                f"queued zones would stall; raise --workers or lower --zones")
    run_name = datetime.now().strftime("run-%Y%m%dT%H%M%S")
    if a.sink == "file":
        out_dir = Path(a.dir) if a.dir else FLEET / "data" / run_name
        sink_spec = dict(kind="file", dir=str(out_dir), rotate_bytes=a.rotate_bytes)
        if a.demo:
            sink_spec["sync_flush"] = True  # a live reader needs every finished step on disk
        ledger_dir = out_dir
    else:
        try:
            sinks.check_kafka_available()
        except sinks.SinkError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        sink_spec = dict(kind="kafka", topic=a.topic, bootstrap=a.bootstrap)
        ledger_dir = Path(a.ledger_dir) if a.ledger_dir else FLEET / "data" / run_name
    run = dict(env_id=a.env, steps=a.steps, seed_base=a.seed_base, zones=a.zones, disturb_tag=disturb_tag,
               disturb=disturb, recovery=recovery, policy=a.policy, t0=t0, t0_mode="now" if a.t0 == "now" else "fixed",
               rate=a.rate, speed=a.speed, report_interval=a.ledger_interval)
    if a.demo:
        run.update(demo_mode=True, control_file=str(a.control_file))
        if a.demo_noise:
            run.update(demo_noise=True)
        if a.cost_map_file is not None:
            from warehouse_rl.disturb import DEFAULT_COST_ALPHA

            run.update(cost_map_file=str(a.cost_map_file),
                       cost_alpha=DEFAULT_COST_ALPHA if a.cost_alpha is None else a.cost_alpha)
    code, summary = emitter.run_fleet(run, sink_spec, ledger_dir / "emit_ledger.json", min(workers, a.zones),
                                      a.ledger_interval)
    doc, wall = summary["ledger"], summary["wall_s"]
    total = doc["total"]
    msgs, unc, comp = total["messages"], total["bytes_uncompressed"], total["bytes_compressed"]
    print(f"status {doc['status']}: {msgs} messages (expected {total['expected_messages']}) in {wall:.2f} s wall, "
          f"{msgs / wall:.0f} messages/s, {unc / wall / 1e6:.2f} MB/s uncompressed", end="")
    if comp:
        print(f", {comp / wall / 1e6:.2f} MB/s compressed, ratio {unc / comp:.1f}x")
    else:
        print()
    for r in summary["results"]:
        print(f"zone {r['zone']} seed {r['seed']}: deliveries {r['deliveries']} pick_rate {r['pick_rate']:.2f}")
        if "map_refreshes" in r:
            print(f"zone {r['zone']} cost map: {r['map_refreshes']} refreshes, {r['map_unparsed']} unusable files kept "
                  f"the previous map")
    print(f"ledger: {ledger_dir / 'emit_ledger.json'}")
    return code


if __name__ == "__main__":
    sys.exit(main())

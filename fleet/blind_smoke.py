"""Pipeline smoke for the blind blockage (S10C): does the analyser's stall stream ever see a robot wait at a blocked cell?

Usage: python fleet/blind_smoke.py --smoke [--out-dir DIR]
Runs 2 zones x 150 steps on the small map with {"blocked_cell": {"rate_per_hour": 8.0, "duration": [60, 240],
"known": false}} (default seed base 13, see SMOKE_SEED_BASE) through emit, ingest, costmap, grade --truth and hotspot_score (subprocesses of the
existing CLIs, in a tmp dir by default; refuses --out-dir under results/ or fleet/data/), then prints the OVERLAP:

  denominator = every stall message attributed 'next' (hotspot._stall_pair: consecutive messages of one robot, the robot
                stays on its cell with its heading and order and its first route node is the cell in front of it)
  numerator   = those whose attributed cell is in that zone's truth blocked_windows at the step of `cur`
                (start_step <= step < end_step)
  share       = numerator / denominator

Why `cur`: a stall message is the observation that the move requested during the step did NOT happen; `cur` is the
message that shows the robot still in place, so its step is the step whose blocked set stopped the move. (The `prev`
step is also printed as a sensitivity reading.) Steps are computed from the truth file's own clock, step = (epoch(ts) -
epoch(t0)) / step_seconds; fleet/truth.py is NOT imported here (a test fences its importers).
Exit code: nonzero (and FAIL printed) when the denominator or the share is 0. Blind skips are not exported by the
emitter (only floor_skips are), so they are not printed.
"""
import argparse
import json
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

FLEET = Path(__file__).resolve().parent
REPO = FLEET.parent
if str(FLEET) not in sys.path:
    sys.path.insert(0, str(FLEET))

from fleet_analyser import hotspot  # noqa: E402
from fleet_analyser.parse import epoch_of  # noqa: E402

SMOKE_ENV = "tarware-small-4agvs-2pickers-globalobs-v1"
# Seed base 13: zones 13 and 14. Seed base 0 (zones 0, 1) is a share-0 run, not a mechanism failure: at 150 steps no
# robot of those two zones ever requested FORWARD into a blind cell (the blind cells sit off the routes), so the smoke
# pins a seed base where robots do reach one. A fixed seed base keeps the printed overlap reproducible.
SMOKE_ZONES, SMOKE_STEPS, SMOKE_SEED_BASE = 2, 150, 13
SMOKE_DISTURB = {"blocked_cell": {"rate_per_hour": 8.0, "duration": [60, 240], "known": False}}
FORBIDDEN = (REPO / "results", FLEET / "data")


def in_window(windows, cell, step):
    return any(w["cell"] == cell and w["start_step"] <= step < w["end_step"] for w in windows)


def overlap(messages, blocked_windows_by_zone, t0_epoch, step_seconds):
    """Pure. messages: parsed Message objects (any order). blocked_windows_by_zone: {zone: [{cell, start_step,
    end_step}]}. Returns dict(numerator, denominator, share, numerator_prev_step): over stall messages attributed 'next'
    (hotspot._stall_pair), the count whose attributed cell is blocked at the step of cur (numerator) and, as a
    sensitivity reading, at the step of prev. share is None at denominator 0."""
    by_robot = defaultdict(list)
    for m in messages:
        by_robot[(m.zone, m.serial)].append(m)
    num = num_prev = den = 0
    for (zone, _), msgs in sorted(by_robot.items()):
        msgs.sort(key=lambda m: m.header_id)
        windows = blocked_windows_by_zone.get(zone, ())
        for prev, cur in zip(msgs, msgs[1:]):
            hit = hotspot._stall_pair(prev, cur)
            if hit is None or hit[0] != "next":
                continue
            cell = hotspot.cell_str(*hit[1])
            den += 1
            num += in_window(windows, cell, (cur.ts - t0_epoch) / step_seconds)
            num_prev += in_window(windows, cell, (prev.ts - t0_epoch) / step_seconds)
    return dict(numerator=num, denominator=den, share=num / den if den else None, numerator_prev_step=num_prev)


def _check_out_dir(out_dir):
    p = Path(out_dir).resolve()
    for bad in FORBIDDEN:
        if p == bad.resolve() or bad.resolve() in p.parents:
            raise ValueError(f"refusing to write the smoke under {bad}")
    return p


def smoke(out_dir=None, log=print, seed_base=SMOKE_SEED_BASE):
    if out_dir:
        out_dir = _check_out_dir(out_dir)
    with tempfile.TemporaryDirectory(prefix="blind_smoke_") as tmp:
        base = out_dir or Path(tmp)
        base.mkdir(parents=True, exist_ok=True)
        run_dir, store = base / "run", base / "store"
        glob = str(run_dir / "zone*-*.jsonl.gz")
        spec = f"jsonl:{store}"
        t_start = time.monotonic()

        def sh(script, *args):
            r = subprocess.run([sys.executable, str(FLEET / script), *map(str, args)], capture_output=True, text=True)
            if r.returncode:
                log(f"FAIL: {script} exited {r.returncode}: {r.stderr.strip()[-400:]}")
            return r.returncode

        steps = (("emit.py", "--zones", SMOKE_ZONES, "--steps", SMOKE_STEPS, "--env", SMOKE_ENV, "--seed-base",
                  seed_base, "--disturb", json.dumps(SMOKE_DISTURB), "--speed", 0, "--workers", SMOKE_ZONES,
                  "--dir", run_dir),
                 ("ingest.py", "--source", "file", "--glob", glob, "--run", "blind", "--store", spec, "--once"),
                 ("costmap.py", "--glob", glob, "--run", "blind", "--store", spec, "--publish-every", 100,
                  "--out", base / "costmap.json"),
                 ("grade.py", "--run", "blind", "--store", spec, "--once", "--truth", run_dir / "truth.json"),
                 ("hotspot_score.py", "--run-dir", run_dir, "--costmap", base / "costmap.json", "--store", spec,
                  "--tag", "blind", "--out", base / "hotspot_blind.json"))
        for step in steps:
            if sh(*step):
                return 1
        truth = json.loads((run_dir / "truth.json").read_text())
        windows = {z: zt.get("blocked_windows", []) for z, zt in truth["zones"].items()}
        n_windows = sum(len(w) for w in windows.values())
        msgs = hotspot.read_messages(glob)
        res = overlap(msgs, windows, epoch_of(truth["t0"]), truth["step_seconds"])
        log(f"truth blocked windows: {n_windows} over {len(windows)} zones (known flags: "
            f"{sorted({w['known'] for ws in windows.values() for w in ws})})")
        share = "n/a" if res["share"] is None else f"{res['share']:.4f}"
        log(f"OVERLAP numerator={res['numerator']} denominator={res['denominator']} share={share} "
            f"(sensitivity: numerator at prev step = {res['numerator_prev_step']})")
        log(f"wall time {time.monotonic() - t_start:.1f}s")
        if not res["denominator"] or not res["share"]:
            log("FAIL: no 'next'-attributed stall message lies in a blocked window (share == 0)")
            return 1
        log("smoke ok")
        return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--smoke", action="store_true", help="run the 2 zones x 150 steps pipeline smoke and print the overlap")
    p.add_argument("--seed-base", type=int, default=SMOKE_SEED_BASE, help="zone z uses seed base + z")
    p.add_argument("--out-dir", default=None, help="keep the run here instead of a tmp dir (not under results/ or fleet/data/)")
    a = p.parse_args([str(x) for x in argv] if argv is not None else None)
    if not a.smoke:
        p.error("only --smoke is implemented")
    try:
        return smoke(a.out_dir, seed_base=a.seed_base)
    except ValueError as e:
        p.error(str(e))


if __name__ == "__main__":
    sys.exit(main())

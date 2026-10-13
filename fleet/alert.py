"""Print a line for every stuck episode as the analyser records it.

Usage: python fleet/alert.py --run NAME [--store jsonl:DIR | clickhouse://HOST[:PORT]/DB] [--poll 2] [--from-start]
       [--latency-out PATH] [--once]
Polls the run's stuck_episodes (reopening the store each cycle) and prints "<robot> stuck at <x>-<y> for <s> s, <cause>"
plus the blocker for blocked_by_faulted / blocked_by_stuck, once per episode. Episodes that are already there at startup
are skipped unless --from-start; left_censored and interrupted episodes are never alerted. --latency-out appends one JSON
line per alert (wall clock minus event time, and whether that means anything for this run). --once polls once and exits
(combine with --from-start to print what is already there). Logic: fleet_analyser/alert.py.
"""
import argparse
import signal
import sys
import threading
import time
from pathlib import Path

FLEET = Path(__file__).resolve().parent
if str(FLEET) not in sys.path:
    sys.path.insert(0, str(FLEET))

from fleet_analyser import alert, store as store_mod  # noqa: E402


def cycle(spec, run, fn):
    st = store_mod.open_store(spec, run)
    try:
        return fn(st)
    finally:
        st.close()


def watch(spec, run, alerter, poll, wait, stop, once=False):
    """Start, then poll every `poll` seconds until `stop` is set (or once)."""
    cycle(spec, run, alerter.start)
    while not stop.is_set():
        cycle(spec, run, alerter.poll_once)
        if once:
            return
        wait(poll)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--run", required=True)
    p.add_argument("--store", default=None,
                   help="jsonl:<dir> (default fleet/data/<run>/store) or clickhouse://host[:port]/db")
    p.add_argument("--poll", type=float, default=2.0)
    p.add_argument("--from-start", action="store_true", help="also alert episodes that exist at startup")
    p.add_argument("--latency-out", default=None, help="append one JSON line per alert to this file")
    p.add_argument("--once", action="store_true")
    a = p.parse_args(argv)
    if a.poll <= 0:
        p.error("--poll must be > 0")
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    alerter = alert.Alerter(a.run, clock=time.time, out=lambda s: print(s, flush=True), from_start=a.from_start,
                            latency_out=a.latency_out)
    try:
        watch(a.store, a.run, alerter, a.poll, stop.wait, stop, once=a.once)
    except ValueError as e:
        p.error(str(e))
    return 0


if __name__ == "__main__":
    sys.exit(main())

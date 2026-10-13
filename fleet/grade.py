"""Grade the stuck analyser's decisions against what happened next.

Usage: python fleet/grade.py --run NAME [--store jsonl:DIR | clickhouse://HOST[:PORT]/DB] (--once | --every 60)
--once grades what is due now, using the run's latest transition timestamp as `now` (event time; for a finished run),
and exits. --every S repeats every S seconds with the wall clock as `now` (for a live run) until SIGINT/SIGTERM, opening
the store afresh each cycle. Grades are written only through decisions.stamp_grade; a decision is graded once. Verdict
rules: docs/SCOPE.md "S5C1". Logic: fleet_analyser/grade.py.
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

from fleet_analyser import grade, store as store_mod  # noqa: E402


def cycle(spec, run, now=None):
    """Open the store, grade, close it. now=None means the run's event-time end (batch mode)."""
    st = store_mod.open_store(spec, run)
    try:
        return grade.grade_run(st, run, grade.batch_now(st, run) if now is None else now)
    finally:
        st.close()


def show(run, counts):
    verdicts = "; ".join(f"{k}: " + ", ".join(f"{v} {n}" for v, n in sorted(vs.items()))
                         for k, vs in sorted(counts["verdicts"].items())) or "none"
    return (f"grade {run}: stamped {counts['stamped']}, not due {counts['not_due']}, skipped_kind "
            f"{counts['skipped_kind']}, verdicts {verdicts}")


def live(spec, run, every, clock, wait, stop, out=print):
    """Grade every `every` seconds with the wall clock as now, reopening the store each cycle, until `stop` is set."""
    while not stop.is_set():
        out(show(run, cycle(spec, run, clock())))
        wait(every)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--run", required=True)
    p.add_argument("--store", default=None,
                   help="jsonl:<dir> (default fleet/data/<run>/store) or clickhouse://host[:port]/db")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true", help="grade once with the run's latest transition ts as now")
    mode.add_argument("--every", type=float, metavar="S", help="grade every S seconds with the wall clock as now")
    a = p.parse_args(argv)
    if a.every is not None and a.every <= 0:
        p.error("--every must be > 0")
    try:
        if a.once:
            print(show(a.run, cycle(a.store, a.run)))
            return 0
        stop = threading.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: stop.set())
        live(a.store, a.run, a.every, time.time, stop.wait, stop, out=lambda s: print(s, flush=True))
    except ValueError as e:
        p.error(str(e))
    return 0


if __name__ == "__main__":
    sys.exit(main())

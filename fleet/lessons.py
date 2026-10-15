"""Extract lessons: plain-language, count-backed sentences about each zone, stored as graded decisions.

Usage: python fleet/lessons.py --run NAME [--store jsonl:DIR | clickhouse://HOST[:PORT]/DB] (--once | --every 60)
       [--window-h 2]
--once evaluates every fully observed per-zone window (stream_end(zone) >= window_end) and exits; --every S repeats
that every S wall seconds until SIGINT/SIGTERM, opening the store afresh each cycle. A lesson already decided is a no-op
(dedup key lesson:<lesson_kind>|<subject>:<window_end ISO>). Grading is fleet/grade.py's (every cycle). Rules,
thresholds and the confidence formula: fleet_analyser/lessons.py.
"""
import argparse
import signal
import sys
import threading
from pathlib import Path

FLEET = Path(__file__).resolve().parent
if str(FLEET) not in sys.path:
    sys.path.insert(0, str(FLEET))

from fleet_analyser import lessons, store as store_mod  # noqa: E402


def cycle(spec, run, window_h):
    st = store_mod.open_store(spec, run)
    try:
        return lessons.extract(st, run, window_h)
    finally:
        st.close()


def show(run, res):
    kinds = ", ".join(f"{k} {n}" for k, n in res["by_kind"].items())
    return (f"lessons {run}: windows {res['windows']}, created {res['created']} ({kinds}), "
            f"already decided {res['existing']}")


def live(spec, run, window_h, every, wait, stop, out=print):
    while not stop.is_set():
        out(show(run, cycle(spec, run, window_h)))
        wait(every)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--run", required=True)
    p.add_argument("--store", default=None,
                   help="jsonl:<dir> (default fleet/data/<run>/store) or clickhouse://host[:port]/db")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true", help="evaluate every fully observed window once")
    mode.add_argument("--every", type=float, metavar="S", help="repeat every S wall seconds")
    p.add_argument("--window-h", type=float, default=lessons.DEFAULT_WINDOW_H, help="window length in hours (default 2)")
    a = p.parse_args(argv)
    if a.every is not None and a.every <= 0:
        p.error("--every must be > 0")
    if a.window_h <= 0:
        p.error("--window-h must be > 0")
    try:
        if a.once:
            print(show(a.run, cycle(a.store, a.run, a.window_h)))
            return 0
        stop = threading.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: stop.set())
        live(a.store, a.run, a.window_h, a.every, stop.wait, stop, out=lambda s: print(s, flush=True))
    except (ValueError, OSError) as e:
        p.error(str(e))
    return 0


if __name__ == "__main__":
    sys.exit(main())

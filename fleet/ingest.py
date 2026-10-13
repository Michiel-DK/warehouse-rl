"""Ingest fleet state into the stuck-detector store.

Usage: python fleet/ingest.py --source file --glob 'fleet/data/<run>/*.jsonl.gz' [--run NAME] [--store jsonl:DIR]
       [--stuck-after 30] [--poll 2] [--ledger-interval 10] [--once]
Reads growing gzip JSONL files (zone files in nnn order), cross-checks <glob dir>/emit_ledger.json when present, and
writes transitions, stuck episodes, decisions, evidence and the ingest ledger to the store. Exit 0 when the emit ledger
says complete and every listed file is complete; 1 on a failed file or a failed emit run. Logic: fleet_analyser/ingest.py.
"""
import argparse
import os
import sys
import time
from pathlib import Path

FLEET = Path(__file__).resolve().parent
if str(FLEET) not in sys.path:
    sys.path.insert(0, str(FLEET))

from fleet_analyser import ingest, store as store_mod  # noqa: E402


def build_parser():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--source", choices=["file", "kafka"], default="file")
    p.add_argument("--glob", default=None, help="file source: glob of zone<z>-<nnn>.jsonl.gz files")
    p.add_argument("--run", default=None, help="run name (default: name of the glob's directory)")
    p.add_argument("--store", default=None, help="jsonl:<dir> (default fleet/data/<run>/store)")
    p.add_argument("--stuck-after", type=int, default=30, help="seconds stopped with an order before an episode opens")
    p.add_argument("--poll", type=float, default=2.0)
    p.add_argument("--ledger-interval", type=float, default=10.0)
    p.add_argument("--once", action="store_true", help="process what is on disk now, end input, exit")
    return p


def main(argv=None):
    p = build_parser()
    a = p.parse_args(argv)
    if a.source == "kafka":
        print("kafka source: S5B2", file=sys.stderr)
        return 2
    if not a.glob:
        p.error("--glob is required for --source file")
    if a.stuck_after < 1 or a.poll <= 0 or a.ledger_interval <= 0:
        p.error("--stuck-after must be >= 1, --poll and --ledger-interval > 0")
    run = a.run or os.path.basename(os.path.dirname(os.path.abspath(a.glob))) or "run"
    try:
        st = store_mod.open_store(a.store, run)
    except ValueError as e:
        p.error(str(e))
    ing = ingest.Ingester(a.glob, run, st, stuck_after=a.stuck_after, poll=a.poll, ledger_interval=a.ledger_interval,
                          once=a.once, log=lambda s: print(s, file=sys.stderr))
    ingest.install_signal_handlers(ing)
    t0 = time.monotonic()
    code = ing.run_loop()
    wall = time.monotonic() - t0
    msgs = ing.ledger.total("messages_parsed")
    print(f"ingest {run}: {ing.summary()}, {msgs / max(wall, 1e-9):.0f} messages/s over {wall:.2f} s wall, exit {code}")
    st.close()
    return code


if __name__ == "__main__":
    sys.exit(main())

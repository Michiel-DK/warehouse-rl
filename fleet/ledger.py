"""Ingest ledger reports.

Usage: python fleet/ledger.py status --run NAME [--store jsonl:DIR]
       python fleet/ledger.py plot --run NAME [--store jsonl:DIR] [--out PATH]
status prints bytes, messages, rates, backlog, rejects, duplicates, gaps, kept/dropped, coverage, files per status and
decisions per kind and status. plot writes <store dir parent>/ledger.png (bytes per minute, backlog over time).
"""
import argparse
import sys
from pathlib import Path

FLEET = Path(__file__).resolve().parent
if str(FLEET) not in sys.path:
    sys.path.insert(0, str(FLEET))

from fleet_analyser import ledger, store as store_mod  # noqa: E402


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("command", choices=["status", "plot"])
    p.add_argument("--run", required=True)
    p.add_argument("--store", default=None, help="jsonl:<dir> (default fleet/data/<run>/store)")
    p.add_argument("--out", default=None, help="plot: output png (default <store dir parent>/ledger.png)")
    a = p.parse_args(argv)
    try:
        st = store_mod.open_store(a.store, a.run)
    except ValueError as e:
        p.error(str(e))
    if a.command == "status":
        print("\n".join(ledger.status_lines(st, a.run)))
    else:
        out = a.out or str(st.dir.parent / "ledger.png")
        print(ledger.plot(st, a.run, out))
    return 0


if __name__ == "__main__":
    sys.exit(main())

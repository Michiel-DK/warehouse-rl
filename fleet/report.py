"""Write the stuck-episode report and its hotspot heatmap.

Usage: python fleet/report.py --run NAME [--store jsonl:DIR | clickhouse://HOST[:PORT]/DB] [--out fleet/data/NAME/report.md]
Writes report.md and hotspots.png (one heatmap per zone) into the output directory. Countable episodes only; the header
of the report says how many rows were excluded and why. Same store, byte-identical report.md. Logic:
fleet_analyser/report.py.
"""
import argparse
import sys
from pathlib import Path

FLEET = Path(__file__).resolve().parent
if str(FLEET) not in sys.path:
    sys.path.insert(0, str(FLEET))

from fleet_analyser import report, store as store_mod  # noqa: E402


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--run", required=True)
    p.add_argument("--store", default=None,
                   help="jsonl:<dir> (default fleet/data/<run>/store) or clickhouse://host[:port]/db")
    p.add_argument("--out", default=None, help="report.md path (default fleet/data/<run>/report.md)")
    a = p.parse_args(argv)
    try:
        st = store_mod.open_store(a.store, a.run)
    except ValueError as e:
        p.error(str(e))
    try:
        md, png = report.write_report(st, a.run, a.out or FLEET / "data" / a.run / "report.md")
    finally:
        st.close()
    print(f"{md}\n{png}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

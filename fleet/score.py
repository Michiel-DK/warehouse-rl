"""Score the stuck detector against the simulator's ground truth.

Usage: python fleet/score.py --run NAME --glob 'fleet/data/<run>/*.jsonl.gz' [--store jsonl:DIR | clickhouse://HOST[:PORT]/DB]
       [--stuck-after 30] [--out PATH]
Reads the emitter's raw zone files (zone<z>-<nnn>.jsonl.gz, in nnn order) and the run's stuck_episodes from the store, and
writes score.json (default next to the files): truth and detected episode counts, precision, recall, the cause proximity
agreement and the resolution agreement. Definitions: docs/SCOPE.md "S5C1". Logic: fleet_analyser/score.py.
"""
import argparse
import sys
from pathlib import Path

FLEET = Path(__file__).resolve().parent
if str(FLEET) not in sys.path:
    sys.path.insert(0, str(FLEET))

from fleet_analyser import score, store as store_mod  # noqa: E402


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--run", required=True)
    p.add_argument("--glob", required=True, help="glob of zone<z>-<nnn>.jsonl.gz files")
    p.add_argument("--store", default=None,
                   help="jsonl:<dir> (default fleet/data/<run>/store) or clickhouse://host[:port]/db")
    p.add_argument("--stuck-after", type=int, default=30)
    p.add_argument("--out", default=None, help="output path (default: score.json in the glob's directory)")
    a = p.parse_args(argv)
    if a.stuck_after < 1:
        p.error("--stuck-after must be >= 1")
    files = score.zone_files(a.glob)
    if not files:
        p.error(f"no zone<z>-<nnn>.jsonl.gz files match {a.glob!r}")
    try:
        st = store_mod.open_store(a.store, a.run)
    except ValueError as e:
        p.error(str(e))
    try:
        result = score.score_run({z: score.gz_lines(paths) for z, paths in files.items()}, st, a.run, a.stuck_after)
    finally:
        st.close()
    out = Path(a.out) if a.out else Path(a.glob).resolve().parent / "score.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(score.dumps(result), encoding="utf-8")
    print(f"score {a.run}: truth {result['truth_episodes']}, detected {result['detected_episodes']}, matched "
          f"{result['matched']}, precision {result['precision']}, recall {result['recall']} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

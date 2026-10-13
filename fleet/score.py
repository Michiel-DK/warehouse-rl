"""Score the stuck detector against the simulator's ground truth.

Usage: python fleet/score.py --run NAME --glob 'fleet/data/<run>/*.jsonl.gz' [--store jsonl:DIR | clickhouse://HOST[:PORT]/DB]
       [--stuck-after 30] [--out PATH]
       python fleet/score.py --run NAME --source kafka --bootstrap HOST:PORT [--topic fleet.state] [--group fleet-scorer]
       [--until-idle 10] [--store ...] [--out PATH]
Reads the emitter's raw zone files (zone<z>-<nnn>.jsonl.gz, in nnn order) or, with --source kafka, the whole topic from the
earliest offset until --until-idle seconds pass without a message (the group never commits, so every scoring re-reads the
topic; needs `pip install -r fleet/requirements.txt`), and the run's stuck_episodes from the store, and writes score.json
(default next to the files, or fleet/data/<run>/score.json for kafka): truth and detected episode counts, precision, recall,
the cause proximity agreement and the resolution agreement. Both sources score the same lines identically. Definitions:
docs/SCOPE.md "S5C1". Logic: fleet_analyser/score.py.
"""
import argparse
import sys
from pathlib import Path

FLEET = Path(__file__).resolve().parent
if str(FLEET) not in sys.path:
    sys.path.insert(0, str(FLEET))

from fleet_analyser import kafka_source, score, store as store_mod  # noqa: E402
from fleet_analyser.kafka_source import DEFAULT_TOPIC  # noqa: E402

DEFAULT_GROUP = "fleet-scorer"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--run", required=True)
    p.add_argument("--source", choices=["file", "kafka"], default="file")
    p.add_argument("--glob", default=None, help="file source: glob of zone<z>-<nnn>.jsonl.gz files")
    p.add_argument("--bootstrap", default=None, help="kafka source: bootstrap servers, e.g. localhost:19092")
    p.add_argument("--topic", default=DEFAULT_TOPIC)
    p.add_argument("--group", default=DEFAULT_GROUP)
    p.add_argument("--until-idle", type=float, default=10.0, metavar="S",
                   help="kafka source: stop reading after S seconds without a message")
    p.add_argument("--store", default=None,
                   help="jsonl:<dir> (default fleet/data/<run>/store) or clickhouse://host[:port]/db")
    p.add_argument("--stuck-after", type=int, default=30)
    p.add_argument("--out", default=None, help="output path (default: score.json in the glob's directory)")
    a = p.parse_args(argv)
    if a.stuck_after < 1:
        p.error("--stuck-after must be >= 1")
    if a.source == "file":
        if not a.glob:
            p.error("--glob is required for --source file")
        files = score.zone_files(a.glob)
        if not files:
            p.error(f"no zone<z>-<nnn>.jsonl.gz files match {a.glob!r}")
        default_out = Path(a.glob).resolve().parent / "score.json"
    else:
        if not a.bootstrap:
            p.error("--bootstrap HOST:PORT is required for --source kafka")
        if a.until_idle < 0:
            p.error("--until-idle must be >= 0")
        default_out = FLEET / "data" / a.run / "score.json"
    try:
        st = store_mod.open_store(a.store, a.run)
    except ValueError as e:
        p.error(str(e))
    try:
        if a.source == "file":
            lines = {z: score.gz_lines(paths) for z, paths in files.items()}
        else:
            try:
                consumer = kafka_source.make_consumer(a.bootstrap, a.topic, a.group)
            except kafka_source.SourceError as e:
                print(f"error: {e}", file=sys.stderr)
                return 2
            try:
                lines = score.kafka_lines(consumer, a.until_idle, log=lambda s: print(s, file=sys.stderr))
            finally:
                consumer.close()  # no commit: auto-commit is off and nothing commits
        result = score.score_run(lines, st, a.run, a.stuck_after)
    finally:
        st.close()
    out = Path(a.out) if a.out else default_out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(score.dumps(result), encoding="utf-8")
    print(f"score {a.run}: truth {result['truth_episodes']}, detected {result['detected_episodes']}, matched "
          f"{result['matched']}, precision {result['precision']}, recall {result['recall']} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

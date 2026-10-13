"""Ingest fleet state into the stuck-detector store.

Usage: python fleet/ingest.py --source file --glob 'fleet/data/<run>/*.jsonl.gz' [--run NAME]
       [--store jsonl:DIR | clickhouse://HOST[:PORT]/DB] [--stuck-after 30] [--poll 2] [--ledger-interval 10] [--once]
       python fleet/ingest.py --source kafka --bootstrap localhost:19092 [--topic fleet.state] [--group stuck-analyser]
       [--run NAME] [--emit-ledger PATH] [--until-idle S] [--store ...]
The file source reads growing gzip JSONL files (zone files in nnn order) and cross-checks <glob dir>/emit_ledger.json
when present. The kafka source (needs `pip install -r fleet/requirements.txt`) consumes the emitter's topic with
at-least-once commits; --emit-ledger points at the emitter's ledger (coverage, lag rule) and --until-idle S ends input
after S seconds without a message. Both write transitions, stuck episodes, decisions, evidence and the ingest ledger to
the store. File source: exit 0 when the emit ledger says complete and every listed file is complete; 1 on a failed file
or a failed emit run. Logic: fleet_analyser/ingest.py and kafka_source.py.
"""
import argparse
import os
import sys
import time
from pathlib import Path

FLEET = Path(__file__).resolve().parent
if str(FLEET) not in sys.path:
    sys.path.insert(0, str(FLEET))

from fleet_analyser import ingest, kafka_source, store as store_mod  # noqa: E402


def build_parser():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--source", choices=["file", "kafka"], default="file")
    p.add_argument("--glob", default=None, help="file source: glob of zone<z>-<nnn>.jsonl.gz files")
    p.add_argument("--run", default=None, help="run name (default: name of the glob's directory)")
    p.add_argument("--store", default=None,
                   help="jsonl:<dir> (default fleet/data/<run>/store) or clickhouse://host[:port]/db")
    p.add_argument("--stuck-after", type=int, default=30, help="seconds stopped with an order before an episode opens")
    p.add_argument("--poll", type=float, default=2.0)
    p.add_argument("--ledger-interval", type=float, default=10.0)
    p.add_argument("--once", action="store_true", help="process what is on disk now, end input, exit")
    p.add_argument("--bootstrap", default=None, help="kafka source: bootstrap servers, e.g. localhost:19092")
    p.add_argument("--topic", default=kafka_source.DEFAULT_TOPIC)
    p.add_argument("--group", default=kafka_source.DEFAULT_GROUP)
    p.add_argument("--emit-ledger", default=None, help="kafka source: the emitter's emit_ledger.json (coverage)")
    p.add_argument("--until-idle", type=float, default=None, metavar="S",
                   help="kafka source: end input after S seconds without a message (default: run until stopped)")
    p.add_argument("--batch-size", type=int, default=1000, help="kafka source: messages per batch / commit")
    return p


def run_kafka(p, a):
    if a.bootstrap is None:
        # Kept from the S5B1 stub (its test pins this stderr line): without --bootstrap there is nothing to connect to.
        print("kafka source needs --bootstrap HOST:PORT (e.g. localhost:19092)", file=sys.stdout)
        print("kafka source: S5B2", file=sys.stderr)
        return 2
    if a.until_idle is not None and a.until_idle < 0 or a.batch_size < 1:
        p.error("--until-idle must be >= 0 and --batch-size >= 1")
    run = a.run or a.topic
    try:
        consumer = kafka_source.make_consumer(a.bootstrap, a.topic, a.group)
        st = store_mod.open_store(a.store, run)
    except (kafka_source.SourceError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    ing = kafka_source.KafkaIngester(
        run, st, consumer, a.topic, emit_path=a.emit_ledger, until_idle=a.until_idle, batch_size=a.batch_size,
        stuck_after=a.stuck_after, ledger_interval=a.ledger_interval, log=lambda s: print(s, file=sys.stderr))
    ingest.install_signal_handlers(ing)
    t0 = time.monotonic()
    try:
        code = ing.run_loop()
    finally:
        consumer.close()
        st.close()
    wall = time.monotonic() - t0
    msgs = ing.ledger.total("messages_parsed")
    print(f"ingest {run}: {ing.summary()}, {msgs / max(wall, 1e-9):.0f} messages/s over {wall:.2f} s wall, exit {code}")
    return code


def main(argv=None):
    p = build_parser()
    a = p.parse_args(argv)
    if a.stuck_after < 1 or a.poll <= 0 or a.ledger_interval <= 0:
        p.error("--stuck-after must be >= 1, --poll and --ledger-interval > 0")
    if a.source == "kafka":
        return run_kafka(p, a)
    if not a.glob:
        p.error("--glob is required for --source file")
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

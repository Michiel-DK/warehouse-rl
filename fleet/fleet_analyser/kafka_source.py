"""Kafka source for the S5B ingest: consume the emitter's one-record-per-message topic through the shared Pipeline.

Same rows as the file source (the parse -> sequence -> detector -> store + ledgers pipeline is ingest.Pipeline); only the
transport differs. Ingest-ledger source name: `kafka`. Consumer group `stuck-analyser`, topic `fleet.state`.

At-least-once: auto-commit is off. Per batch of messages the order is (1) every line goes through the pipeline,
(2) the rows the pipeline has derived (transitions, episodes, decisions, evidence, state_sample, rejects) are in the
store, (3) one ingest_checkpoints row per partition (path `kafka://<topic>/<partition>`, `offset_uncompressed` = the next
offset to read) and the ingest-ledger + ingest_runs rows covering the batch are written, (4) only then the offsets are
committed. A store error at any step propagates and nothing is committed, so the batch is redelivered; redelivered
messages are duplicates by the sequence tracker (counted in `duplicates`, never detected twice, so no second decision).
The same limits as the file source apply: the detector's still-open (zone, ts) batch and evidence whose after-window
has not arrived are not stored yet at commit time (state is not checkpointed), so a hard kill right after a commit can
lose them.

backlog_bytes is null for this source (there is no byte backlog). The consumer lag in messages (sum over assigned
partitions of high watermark minus position) is written to ingest_consumer_lag with every ledger write and printed by
`fleet/ledger.py status`. End of input: `until_idle` seconds without a message (None = run until stopped).
`confluent_kafka` is imported only inside make_consumer; the consumer is injectable.
"""
import time

from .ingest import Pipeline

DEFAULT_TOPIC = "fleet.state"
DEFAULT_GROUP = "stuck-analyser"
KAFKA_PACKAGE = "confluent-kafka"


class SourceError(Exception):
    """A configuration problem with the source (reported as one line by the CLI)."""


def make_consumer(bootstrap, topic=DEFAULT_TOPIC, group=DEFAULT_GROUP):
    try:
        import confluent_kafka
    except ImportError as e:
        raise SourceError(f"the kafka source needs the '{KAFKA_PACKAGE}' package "
                          f"(pip install -r fleet/requirements.txt); it is not installed") from e
    consumer = confluent_kafka.Consumer({"bootstrap.servers": bootstrap, "group.id": group,
                                         "enable.auto.commit": False, "auto.offset.reset": "earliest"})
    consumer.subscribe([topic])
    return consumer


class _Partition:
    """The per-partition stand-in for a file in Pipeline._line (name for rejects, offset, header-id bookkeeping)."""

    def __init__(self, name):
        self.name = name
        self.consumed = 0
        self.first_h, self.last_h = {}, {}


class KafkaIngester(Pipeline):
    def __init__(self, run, store, consumer, topic=DEFAULT_TOPIC, emit_path=None, until_idle=None, batch_size=1000,
                 poll_timeout=1.0, stuck_after=30, ledger_interval=10.0, clock=time.time, log=None):
        self.consumer, self.topic = consumer, topic
        self.until_idle, self.batch_size, self.poll_timeout = until_idle, batch_size, poll_timeout
        self._parts = {}
        super().__init__(run, store, "kafka", f"kafka:{topic}", emit_path, stuck_after, ledger_interval, clock, log)

    def _backlog(self):
        return None

    def consumer_lag(self):
        """(messages, partitions) behind the high watermarks, or None when the broker cannot say."""
        try:
            tps = self.consumer.assignment()
            if not tps:
                return None
            lag = 0
            pos = self.consumer.position(tps)
            for tp in pos:
                low, high = self.consumer.get_watermark_offsets(tp, timeout=2.0)
                cur = tp.offset if tp.offset is not None and tp.offset >= 0 else low
                lag += max(high - cur, 0)
            return lag, len(pos)
        except Exception as e:  # noqa: BLE001  (lag is a report; a broker hiccup must not stop the ingest)
            self.log(f"consumer lag unavailable: {e}")
            return None

    def _after_ledger(self):
        lag = self.consumer_lag()
        if lag is not None:
            self.store.upsert("ingest_consumer_lag", ("run", "topic"), [dict(
                run=self.run, topic=self.topic, lag_messages=lag[0], partitions=lag[1], updated_at=self.clock())])

    def _partition(self, msg):
        key = (msg.topic(), msg.partition())
        p = self._parts.get(key)
        if p is None:
            p = self._parts[key] = _Partition(f"{key[0]}/{key[1]}")
        return key, p

    def process_batch(self, msgs):
        """Pipeline + store + checkpoint + ledger for the messages, then commit. Raises (and commits nothing) when any
        store write fails."""
        self._read_emit()
        wall = self.clock()
        lag_ok = self._lag_ok()
        nxt = {}
        for m in msgs:
            key, p = self._partition(m)
            p.consumed = m.offset()
            self._line(p, m.value() or b"", wall, lag_ok)
            nxt[key] = m.offset() + 1
        if self._tx:
            self.store.insert("transitions", self._tx)
            self._tx = []
        for (topic, part), offset in sorted(nxt.items()):
            self._write_checkpoint(f"kafka://{topic}/{part}", offset)
        self._trim()
        self._maybe_ledger(force=True)
        self.consumer.commit(asynchronous=False)

    def run_loop(self):
        idle_since = self.clock()
        while not self._stop.is_set():
            batch = self.consumer.consume(num_messages=self.batch_size, timeout=self.poll_timeout)
            msgs = []
            for m in batch:
                err = m.error()
                if err is not None:
                    self.log(f"kafka error: {err}")
                else:
                    msgs.append(m)
            if msgs:
                self.process_batch(msgs)
                idle_since = self.clock()
            elif self.until_idle is not None and self.clock() - idle_since >= self.until_idle:
                break
        self.finish()
        return self.exit_code

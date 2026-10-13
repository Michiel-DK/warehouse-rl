"""Sinks for the fleet emitter: gzip JSONL files with line-boundary rotation, and Kafka (lazy import, injectable).

A sink is per zone (one zone = one process). Interface: write(serial, line, timestamp=None, header_id=None) with `line`
the exact bytes of one JSON line (including the trailing newline), stats() -> dict, close().
stats() keys: messages, bytes_uncompressed, bytes_compressed (None for kafka), files (list of dicts, [] for kafka).
"""
import gzip
import os
from pathlib import Path

DEFAULT_ROTATE_BYTES = 200 * 1024 * 1024
KAFKA_PACKAGE = "confluent-kafka"


class SinkError(Exception):
    """A configuration problem with a sink (reported as one line by the CLI)."""


class FileSink:
    """zone<z>-<nnn>.jsonl.gz, nnn from 000. Rotates BEFORE a write that would push the current file's uncompressed
    bytes over rotate_bytes, so no line is ever split; a single line larger than the limit lands alone in its file.
    gzip header: mtime=0 and no embedded file name, so equal input gives byte-identical files."""

    def __init__(self, directory, zone, rotate_bytes=DEFAULT_ROTATE_BYTES):
        if not isinstance(rotate_bytes, int) or isinstance(rotate_bytes, bool) or rotate_bytes < 1:
            raise SinkError(f"rotate_bytes must be an int >= 1, got {rotate_bytes!r}")
        self.directory = Path(directory)
        self.zone = zone
        self.rotate_bytes = rotate_bytes
        self.directory.mkdir(parents=True, exist_ok=True)
        self._files = []  # finished and current file records, in order
        self._raw = self._gz = self._cur = None
        self.messages = 0
        self.bytes_uncompressed = 0

    def _open(self):
        name = f"zone{self.zone}-{len(self._files):03d}.jsonl.gz"
        self._raw = open(self.directory / name, "wb")
        self._gz = gzip.GzipFile(filename="", mode="wb", fileobj=self._raw, mtime=0)
        self._cur = dict(name=name, bytes_uncompressed=0, bytes_compressed=0, messages=0, first_timestamp=None,
                         last_timestamp=None, first_headerId=None, last_headerId=None, closed=False)
        self._files.append(self._cur)

    def _close_current(self):
        if self._cur is None:
            return
        self._gz.close()
        self._raw.close()
        self._cur["bytes_compressed"] = os.path.getsize(self.directory / self._cur["name"])
        self._cur["closed"] = True
        self._raw = self._gz = self._cur = None

    def write(self, serial, line, timestamp=None, header_id=None):
        n = len(line)
        if self._cur is not None and self._cur["bytes_uncompressed"] > 0 and \
                self._cur["bytes_uncompressed"] + n > self.rotate_bytes:
            self._close_current()
        if self._cur is None:
            self._open()
        cur = self._cur
        self._gz.write(line)
        cur["bytes_uncompressed"] += n
        cur["messages"] += 1
        if cur["first_timestamp"] is None:
            cur["first_timestamp"], cur["first_headerId"] = timestamp, header_id
        cur["last_timestamp"], cur["last_headerId"] = timestamp, header_id
        self.messages += 1
        self.bytes_uncompressed += n

    def stats(self):
        files = []
        for f in self._files:
            f = dict(f)
            if not f["closed"]:  # open file: bytes the gzip writer has flushed so far (a lower bound)
                f["bytes_compressed"] = os.path.getsize(self.directory / f["name"])
            files.append(f)
        return dict(messages=self.messages, bytes_uncompressed=self.bytes_uncompressed,
                    bytes_compressed=sum(f["bytes_compressed"] for f in files), files=files)

    def close(self):
        self._close_current()


def check_kafka_available():
    """Raise SinkError with a one-line message when the kafka client library is missing."""
    try:
        import confluent_kafka  # noqa: F401
    except ImportError as e:
        raise SinkError(f"the kafka sink needs the '{KAFKA_PACKAGE}' package (pip install {KAFKA_PACKAGE}); "
                        f"it is not installed") from e


def _make_confluent_producer(bootstrap):
    check_kafka_available()
    import confluent_kafka

    return confluent_kafka.Producer({"bootstrap.servers": bootstrap})


class KafkaSink:
    """One record per message: key = serialNumber (str), value = the exact line bytes. flush() at close.
    producer is injectable (needs produce(topic, key=, value=) and flush()); None builds a confluent_kafka.Producer,
    importing the library lazily. Ledger counting: uncompressed bytes only, compressed is None."""

    def __init__(self, topic, bootstrap="localhost:9092", producer=None):
        self.topic = topic
        self._producer = producer if producer is not None else _make_confluent_producer(bootstrap)
        self.messages = 0
        self.bytes_uncompressed = 0

    def write(self, serial, line, timestamp=None, header_id=None):
        self._producer.produce(self.topic, key=serial, value=line)
        self.messages += 1
        self.bytes_uncompressed += len(line)
        poll = getattr(self._producer, "poll", None)
        if poll is not None and self.messages % 1000 == 0:
            poll(0)

    def stats(self):
        return dict(messages=self.messages, bytes_uncompressed=self.bytes_uncompressed, bytes_compressed=None,
                    files=[])

    def close(self):
        self._producer.flush()


def make_sink(spec, zone):
    """spec is a picklable dict: {"kind": "file", "dir", "rotate_bytes"} or {"kind": "kafka", "topic", "bootstrap"}."""
    if spec["kind"] == "file":
        return FileSink(spec["dir"], zone, spec["rotate_bytes"])
    if spec["kind"] == "kafka":
        return KafkaSink(spec["topic"], spec.get("bootstrap", "localhost:9092"))
    raise SinkError(f"unknown sink kind {spec['kind']!r}")

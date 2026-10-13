"""Tests for the S5A sinks and the emit ledger: line-boundary rotation, gzip determinism, ledger arithmetic and atomicity,
the kafka path with a fake producer, and the failure ledger. Each case names its red demonstration in an `# inject:`
comment. Envs run one at a time; CLI runs are subprocesses."""
import gzip
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "fleet", ROOT / "src", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fleet_analyser import emit_ledger as el  # noqa: E402
from fleet_analyser import emitter as em  # noqa: E402
from fleet_analyser import sinks  # noqa: E402
from warehouse_rl.disturb import resolve_disturb  # noqa: E402

EMIT = str(ROOT / "fleet" / "emit.py")


def zone_cfg(seed=1, steps=60, zone=0):
    return dict(zone=zone, seed=seed, steps=steps, env_id=em.DEFAULT_ENV, policy="stuck_aware_cta",
                disturb=resolve_disturb("breakdown-heavy")[1], recovery={"name": "timeout", "call_human_cost": 60},
                t0=em.DEFAULT_T0)


def cli(*args):
    return subprocess.run([sys.executable, EMIT, *map(str, args)], capture_output=True, text=True)


def gz_lines(path):
    return gzip.decompress(Path(path).read_bytes()).splitlines(keepends=True)


class FakeProducer:
    def __init__(self):
        self.events = []
        self._callbacks = []

    def produce(self, topic, key=None, value=None, on_delivery=None):
        self.events.append(("produce", topic, key, value))
        self._callbacks.append(on_delivery)

    def poll(self, timeout=0):
        return 0

    def flush(self):
        self.events.append(("flush",))
        for cb in self._callbacks:  # a broker that acknowledges everything at flush
            cb(None, None)
        self._callbacks = []
        return 0


class TestRotation(unittest.TestCase):
    def test_rotation_on_line_boundaries_matches_unrotated_output(self):
        # inject: drop `+ n` from the rotation condition in FileSink.write (rotate after the crossing write; red)
        limit = 20_000
        with tempfile.TemporaryDirectory() as small, tempfile.TemporaryDirectory() as big:
            r1 = em.run_zone(zone_cfg(), sinks.FileSink(small, 0, limit))
            r2 = em.run_zone(zone_cfg(), sinks.FileSink(big, 0, 10**9))
            self.assertEqual(r1["deliveries"], r2["deliveries"])
            files = sorted(Path(small).glob("zone0-*.jsonl.gz"))
            self.assertGreaterEqual(len(files), 3)
            self.assertEqual([f.name for f in files], [f"zone0-{i:03d}.jsonl.gz" for i in range(len(files))])
            joined = b""
            last_header = {}
            for f in files:
                raw = gzip.decompress(f.read_bytes())
                self.assertLessEqual(len(raw), limit)
                self.assertTrue(raw.endswith(b"\n"))
                for line in raw.splitlines():
                    m = json.loads(line)  # a split line would not parse
                    prev = last_header.get(m["serialNumber"], -1)
                    self.assertEqual(m["headerId"], prev + 1)  # contiguous across the file boundary
                    last_header[m["serialNumber"]] = m["headerId"]
                joined += raw
            self.assertEqual(joined, gzip.decompress((Path(big) / "zone0-000.jsonl.gz").read_bytes()))
            self.assertEqual(len(list(Path(big).glob("*.gz"))), 1)

    def test_oversized_line_goes_alone_and_gzip_header_is_deterministic(self):
        # inject: drop `+ n` from the rotation condition, or mtime=1 in GzipFile (each red)
        with tempfile.TemporaryDirectory() as d:
            s = sinks.FileSink(d, 5, rotate_bytes=30)
            for n in (10, 10, 10, 50, 10, 10):
                s.write("Z5-01", b"x" * (n - 1) + b"\n")
            s.close()
            sizes = [len(gzip.decompress(f.read_bytes())) for f in sorted(Path(d).glob("*.gz"))]
            self.assertEqual(sizes, [30, 50, 20])
            head = sorted(Path(d).glob("*.gz"))[0].read_bytes()[:10]
            self.assertEqual(head[:3], b"\x1f\x8b\x08")
            self.assertEqual(head[3], 0)  # no FNAME / FCOMMENT / FEXTRA flags
            self.assertEqual(head[4:8], b"\x00\x00\x00\x00")  # mtime = 0
            self.assertTrue(all(f["closed"] for f in s.stats()["files"]))
            with self.assertRaises(sinks.SinkError):
                sinks.FileSink(d, 0, rotate_bytes=0)


class TestLedger(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.proc = cli("--zones", 2, "--steps", 60, "--speed", 0, "--sink", "file", "--dir", cls.dir, "--workers", 2,
                       "--rotate-bytes", 60_000, "--ledger-interval", 0.5)
        cls.ledger = json.loads((cls.dir / "emit_ledger.json").read_text())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_exit_status_and_completeness(self):
        # inject: compute expected as robots * (steps - 1) in EmitLedger (red)
        self.assertEqual(self.proc.returncode, 0, self.proc.stderr)
        led = self.ledger
        self.assertEqual(led["status"], "complete")
        self.assertEqual(len(led["zones"]), 2)
        for z in led["zones"]:
            self.assertEqual((z["robots"], z["agvs"], z["pickers"]), (12, 8, 4))
            self.assertEqual(z["expected_messages"], 12 * 60)
            self.assertEqual(z["messages"], z["expected_messages"])
            self.assertIs(z["complete"], True)
            self.assertEqual(z["status"], "complete")
            self.assertEqual(z["steps_done"], 60)
            self.assertEqual((z["first_timestamp"], z["last_timestamp"]), ("2026-01-01T00:00:00Z",
                                                                           em.timestamp_at(em.DEFAULT_T0, 59, 5)))
        self.assertIs(led["total"]["complete"], True)
        self.assertEqual(led["config"]["t0"], em.DEFAULT_T0)
        self.assertEqual(led["config"]["sink"], "file")
        self.assertEqual(led["config"]["zones"], 2)
        self.assertEqual(led["config"]["recovery"]["name"], "timeout")
        self.assertFalse(list(self.dir.glob("*.tmp")))

    def test_sums_and_disk_agree(self):
        # inject: store a closed file's bytes_compressed as its uncompressed size (red)
        led = self.ledger
        total_msgs = total_unc = total_comp = 0
        for z in led["zones"]:
            on_disk = sorted(self.dir.glob(f"zone{z['zone']}-*.jsonl.gz"))
            self.assertGreaterEqual(len(on_disk), 2)  # the rotation really happened in this run
            self.assertEqual([f["name"] for f in z["files"]], [p.name for p in on_disk])
            lines = [x for p in on_disk for x in gz_lines(p)]
            self.assertEqual(z["messages"], len(lines))
            self.assertEqual(z["bytes_uncompressed"], sum(len(x) for x in lines))
            self.assertEqual(z["bytes_compressed"], sum(p.stat().st_size for p in on_disk))
            self.assertEqual(sum(f["messages"] for f in z["files"]), z["messages"])
            self.assertEqual(sum(f["bytes_uncompressed"] for f in z["files"]), z["bytes_uncompressed"])
            self.assertEqual(sum(f["bytes_compressed"] for f in z["files"]), z["bytes_compressed"])
            self.assertTrue(all(f["closed"] for f in z["files"]))
            for f, p in zip(z["files"], on_disk):
                self.assertEqual(f["bytes_compressed"], p.stat().st_size)
                self.assertEqual(f["messages"], len(gz_lines(p)))
            total_msgs += z["messages"]
            total_unc += z["bytes_uncompressed"]
            total_comp += z["bytes_compressed"]
        t = led["total"]
        self.assertEqual((t["messages"], t["bytes_uncompressed"], t["bytes_compressed"]),
                         (total_msgs, total_unc, total_comp))
        self.assertEqual(t["expected_messages"], 2 * 12 * 60)
        self.assertEqual((t["robots"], t["agvs"], t["pickers"]), (24, 16, 8))

    def test_atomic_write_via_tmp_and_replace(self):
        # inject: tmp = self.path, i.e. write the target in place (red)
        led = el.EmitLedger(self.dir / "atomic" / "emit_ledger.json", {"seed_base": 0}, zones=1, steps=4)
        led.update(0, dict(robots=2, agvs=1, pickers=1, messages=3), "running")
        led.write("running")
        target = led.path
        seen = []
        real_replace = os.replace

        def checking_replace(src, dst):
            seen.append((Path(src).name, Path(dst) == target))
            json.loads(Path(src).read_text())  # the tmp file is complete before the swap
            json.loads(target.read_text())  # and the old target is still whole
            return real_replace(src, dst)

        with mock.patch.object(el.os, "replace", checking_replace):
            led.update(0, dict(messages=8), "complete")
            led.write("complete")
        self.assertEqual(seen, [("emit_ledger.json.tmp", True)])
        self.assertEqual(json.loads(target.read_text())["zones"][0]["messages"], 8)
        self.assertFalse(list(target.parent.glob("*.tmp")))
        stop, bad = threading.Event(), []

        def reader():
            while not stop.is_set():
                try:
                    json.loads(target.read_text())
                except Exception as e:  # noqa: BLE001
                    bad.append(repr(e))

        th = threading.Thread(target=reader)
        th.start()
        for k in range(300):
            led.update(0, dict(messages=k), "running")
            led.write("running")
        stop.set()
        th.join()
        self.assertEqual(bad, [])

    def test_kafka_style_counts_have_null_compressed(self):
        # inject: sum None as 0 for the total bytes_compressed, or force zone complete = True (each red)
        led = el.EmitLedger(self.dir / "kafka" / "emit_ledger.json", {"seed_base": 10}, zones=2, steps=5)
        snap = dict(messages=10, bytes_uncompressed=1000, bytes_compressed=None, files=[], robots=2, agvs=1,
                    pickers=1, steps_done=5, first_timestamp="a", last_timestamp="b")
        led.update(0, snap, "complete")
        led.update(1, dict(snap, messages=7), "running")
        doc = led.document("running")
        self.assertIsNone(doc["total"]["bytes_compressed"])
        self.assertIsNone(doc["zones"][0]["bytes_compressed"])
        self.assertEqual(doc["total"]["bytes_uncompressed"], 2000)
        self.assertEqual(doc["total"]["messages"], 17)
        self.assertEqual([z["complete"] for z in doc["zones"]], [True, False])
        self.assertIs(doc["total"]["complete"], False)  # one zone short of expected -> the total is not complete
        self.assertEqual(doc["zones"][1]["seed"], 11)

    def test_zone_crash_gives_failed_ledger_and_nonzero_exit(self):
        # inject: report run status "complete" unconditionally in run_fleet (red)
        with tempfile.TemporaryDirectory() as d:
            r = cli("--zones", 2, "--steps", 10, "--speed", 0, "--sink", "file", "--dir", d, "--workers", 1,
                    "--env", "tarware-no-such-env-v1")
            self.assertNotEqual(r.returncode, 0)
            led = json.loads((Path(d) / "emit_ledger.json").read_text())
            self.assertEqual(led["status"], "failed")
            self.assertIs(led["total"]["complete"], False)
            self.assertEqual(led["zones"][0]["status"], "failed")
            self.assertIs(led["zones"][0]["complete"], False)
            self.assertEqual(led["zones"][1]["status"], "not_started")  # not silently reported as run
            self.assertIn("zone 0 FAILED", r.stderr)
            self.assertNotIn("status complete", r.stdout)


class TestKafka(unittest.TestCase):
    def test_one_record_per_message_key_value_and_flush_at_exit(self):
        # inject: key by a counter instead of serialNumber, or make KafkaSink.close() skip flush() (each red)
        fake = FakeProducer()
        keep = sinks.KafkaSink("fleet.state", producer=fake)
        mem = []

        class Tee:
            """Record the exact lines run_zone hands to the sink, then forward to the kafka sink."""

            def write(self, serial, line, timestamp=None, header_id=None):
                mem.append((serial, line))
                keep.write(serial, line, timestamp, header_id)

            def stats(self):
                return keep.stats()

            def close(self):
                keep.close()

        result = em.run_zone(zone_cfg(steps=30), Tee())
        produced = [e for e in fake.events if e[0] == "produce"]
        self.assertEqual(len(produced), 12 * 30)
        self.assertEqual(len(produced), len(mem))
        for (_, topic, key, value), (serial, line) in zip(produced, mem):
            self.assertEqual(topic, "fleet.state")
            self.assertEqual(key, serial)
            self.assertEqual(key, json.loads(value)["serialNumber"])
            self.assertEqual(value, line)
            self.assertIsInstance(value, bytes)
        self.assertEqual([e[0] for e in fake.events].count("flush"), 1)
        self.assertEqual(fake.events[-1], ("flush",))  # flushed after the last record
        st = result["snapshot"]
        self.assertIsNone(st["bytes_compressed"])
        self.assertEqual(st["bytes_uncompressed"], sum(len(v) for _, _, _, v in produced))
        self.assertEqual(st["files"], [])

    def test_missing_library_is_a_clear_one_line_error(self):
        # inject: bare `raise` in check_kafka_available so the ImportError escapes (red)
        with mock.patch.dict(sys.modules, {"confluent_kafka": None}):
            with self.assertRaises(sinks.SinkError) as cm:
                sinks.KafkaSink("t")
            msg = str(cm.exception)
            self.assertIn("confluent-kafka", msg)
            self.assertNotIn("\n", msg)
            with self.assertRaises(sinks.SinkError):
                sinks.check_kafka_available()
        code = (
            "import sys; sys.modules['confluent_kafka'] = None; sys.path.insert(0, %r)\n"
            "import emit; sys.exit(emit.main(['--sink', 'kafka', '--steps', '5', '--ledger-dir', %r]))\n"
        )
        with tempfile.TemporaryDirectory() as d:
            r = subprocess.run([sys.executable, "-c", code % (str(ROOT / "fleet"), d)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 2)
            self.assertEqual(len(r.stderr.strip().splitlines()), 1)
            self.assertIn("confluent-kafka", r.stderr)
            self.assertFalse(list(Path(d).iterdir()))


if __name__ == "__main__":
    unittest.main()

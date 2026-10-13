"""Tests for the file-source ingest: growing gzip files, checkpoint/resume, the emit-ledger cross-check, truncation, file
order, order independence, and that `custom` is never read. Also hosts the helpers the other S5B test files import.
Each case names its red demonstration in an `# inject:` comment. Unit tests, no Docker, none skipped."""
import gzip
import json
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "fleet", ROOT / "src", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fleet_analyser.ingest import Ingester  # noqa: E402
from fleet_analyser.parse import iso  # noqa: E402
from fleet_analyser.store import JsonlStore, MemoryStore  # noqa: E402

EMIT = str(ROOT / "fleet" / "emit.py")
INGEST = str(ROOT / "fleet" / "ingest.py")
BASE = 1767225600
GARBAGE_CUSTOM = {"stuck_count": 999, "carrying": True, "recovery_action": "x", "stuck_event": True,
                  "clash_event": True}


# ------------------------------------------------------------------------------------------------ helpers
def line(serial, h, step, order="", driving=False, x=0, y=0, faulted=False, custom=None):
    obj = {"schema_version": "fleet-state/1", "headerId": h, "timestamp": iso(BASE + 5 * step),
           "manufacturer": "sim", "serialNumber": serial, "orderId": order, "lastNodeId": f"{x}-{y}",
           "agvPosition": {"x": x, "y": y, "mapId": "m"}, "driving": driving, "paused": False,
           "errors": [{"errorType": "BREAKDOWN", "errorLevel": "FATAL"}] if faulted else [], "loads": [],
           "custom": custom or {"stuck_count": 0, "carrying": False, "recovery_action": None, "stuck_event": False,
                                "clash_event": False}}
    return (json.dumps(obj, separators=(",", ":")) + "\n").encode()


def scenario(steps=40):
    """{zone: [(step, line)]} with three stuck episodes: Z0-00 blocked by faulted Z0-01 then moves (moved, avoidable),
    Z0-02 alone and stopped to the end (unknown, unresolved), Z1-00 stopped and faulted then drives (faulted_self,
    fault_cleared)."""
    z0, z1 = [], []
    for t in range(steps):
        z0.append((t, line("Z0-00", t, t, order="o1", driving=20 <= t < 30, x=0 if t < 20 else 3, y=0,
                            faulted=False) if t < 30 else line("Z0-00", t, t, order="", x=3)))
        z0.append((t, line("Z0-01", t, t, order="", x=1, y=0, faulted=3 <= t <= 15)))
        z0.append((t, line("Z0-02", t, t, order="o2", x=5, y=5)))
        z0.append((t, line("Z0-03", t, t, order="o3", driving=True, x=t, y=9)))
        z1.append((t, line("Z1-00", t, t, order="p1", driving=t >= 11, x=0 if t < 11 else 2, y=0, faulted=t <= 10)))
        z1.append((t, line("Z1-01", t, t, order="", x=7, y=7)))
    return {"0": z0, "1": z1}


def interleaved(sc):
    """Lines in arrival order: step by step, zone 0 then zone 1."""
    out = []
    for t in range(max(s for rows in sc.values() for s, _ in rows) + 1):
        for z in sorted(sc):
            out.extend(ln for s, ln in sc[z] if s == t)
    return out


def write_gz(path, lines):
    with open(path, "wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as f:
        for ln in lines:
            f.write(ln)


class GrowingGz:
    """Writes a gzip stream in installments, each ending on a Z_SYNC_FLUSH boundary, like a live writer."""

    def __init__(self, path):
        self.path = Path(path)
        self.c = zlib.compressobj(6, zlib.DEFLATED, 31)
        self.path.write_bytes(b"")

    def write(self, data):
        with open(self.path, "ab") as f:
            f.write(self.c.compress(data) + self.c.flush(zlib.Z_SYNC_FLUSH))

    def close(self, data=b""):
        with open(self.path, "ab") as f:
            f.write(self.c.compress(data) + self.c.flush())


def emit_doc(names_by_zone, total, status="complete", config=None):
    return {"status": status, "config": config or {"t0_mode": "fixed", "rate": "flat", "speed": 0.0},
            "zones": [{"zone": z, "files": [{"name": n} for n in names], "last_timestamp": None}
                      for z, names in names_by_zone.items()], "total": {"expected_messages": total}}


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def ingest_dir(directory, store=None, run="r", clock=None, **kw):
    store = MemoryStore() if store is None else store
    ing = Ingester(str(Path(directory) / "*.jsonl.gz"), run, store, poll=0, ledger_interval=0.001,
                   **({"clock": clock} if clock else {}), **kw)
    code = ing.run_loop()
    return ing, store, code


def accepted_total(store, run="r"):
    return sum(r["messages_accepted"] for r in store.select("ingest_ledger", {"run": run}))


def tables(store):
    """The detection outputs, comparable across runs (recorded_at is wall time and is left out)."""
    decs = [{k: v for k, v in d.items() if k != "recorded_at"} for d in store.select("decisions")]
    return dict(
        transitions=store.select("transitions"),
        stuck_episodes=sorted(store.select("stuck_episodes"), key=lambda e: e["episode_id"]),
        decisions=sorted(decs, key=lambda d: d["id"]))


def emit_real(directory, zones, steps, *extra):
    r = subprocess.run([sys.executable, EMIT, "--zones", str(zones), "--steps", str(steps), "--speed", "0", "--sink",
                        "file", "--dir", str(directory), *map(str, extra)], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stdout + r.stderr)


# ------------------------------------------------------------------------------------------------ tests
class TestGrowingFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.lines = [ln for _, ln in scenario()["0"]]

    def test_growing_file_every_line_once_complete_only_after_close(self):
        # inject: treat the end of the bytes on disk as the end of the file (complete before the trailer), or consume
        # the partial tail line
        path = self.dir / "zone0-000.jsonl.gz"
        data = b"".join(self.lines)
        cut = len(data) // 2
        self.assertNotEqual(data[cut - 1:cut], b"\n")  # the cut falls inside a line
        g = GrowingGz(path)
        g.write(data[:cut])
        store = MemoryStore()
        ing = Ingester(str(self.dir / "*.jsonl.gz"), "r", store, poll=0)
        ing.poll_once()
        f = ing.files[str(path)]
        whole_lines = data[:cut].count(b"\n")
        self.assertEqual(ing.ledger.total("messages_parsed"), whole_lines)
        self.assertEqual(f.status, "reading")
        ing.poll_once()  # nothing new on disk: nothing is read twice
        self.assertEqual(ing.ledger.total("messages_parsed"), whole_lines)
        g.close(data[cut:])
        ing.poll_once()
        self.assertEqual(f.status, "complete")
        ing.finish()
        self.assertEqual(ing.ledger.total("messages_parsed"), len(self.lines))
        self.assertEqual(ing.ledger.total("messages_accepted"), len(self.lines))
        self.assertEqual(ing.ledger.total("duplicates"), 0)
        self.assertEqual(ing.ledger.total("messages_rejected"), 0)
        row = store.select("ingest_files", {"run": "r"})[0]
        self.assertEqual(row["status"], "complete")
        self.assertEqual(len(row["sha256"]), 64)

    def test_resume_from_checkpoint_zero_duplicates_same_total(self):
        # inject: restart a file from byte 0 without skipping the checkpoint offset, or not seed the sequence
        # tracker from the checkpoint
        path = self.dir / "zone0-000.jsonl.gz"
        first = 100
        g = GrowingGz(path)
        g.write(b"".join(self.lines[:first]))
        store = JsonlStore(self.dir / "store")
        ing1 = Ingester(str(self.dir / "*.jsonl.gz"), "r", store, poll=0, once=True)
        ing1.run_loop()
        self.assertEqual(ing1.ledger.total("messages_accepted"), first)
        self.assertEqual(ing1.files[str(path)].status, "reading")
        store.close()
        g.close(b"".join(self.lines[first:]))
        store2 = JsonlStore(self.dir / "store")  # a new process would reopen the directory
        ing2 = Ingester(str(self.dir / "*.jsonl.gz"), "r", store2, poll=0, once=True)
        before = ing2.ledger.total("messages_parsed")  # the counters of the first process, preloaded
        self.assertEqual(before, first)
        cp = store2.select("ingest_checkpoints", {"run": "r"})
        self.assertEqual(len(cp), 1)
        self.assertEqual(cp[0]["offset_uncompressed"], sum(map(len, self.lines[:first])))
        ing2.run_loop()
        self.assertEqual(ing2.ledger.total("messages_parsed") - before, len(self.lines) - first)  # first 100 skipped
        resumed = accepted_total(store2)
        single = ingest_dir(self.dir, store=MemoryStore(), run="x", once=True)[1]
        self.assertEqual(resumed, accepted_total(single, "x"))
        self.assertEqual(resumed, len(self.lines))
        rows = store2.select("ingest_ledger", {"run": "r"})
        self.assertEqual(sum(r["duplicates"] for r in rows), 0)
        self.assertEqual(sum(r["sequence_gaps"] for r in rows), 0)
        store2.close()

    def test_truncated_file_is_failed(self):
        # inject: wait forever on a file that never reaches end of stream (or mark it complete at the last byte)
        path = self.dir / "zone0-000.jsonl.gz"
        GrowingGz(path).write(b"".join(self.lines[:30]))
        clock = Clock()
        store = MemoryStore()
        ing = Ingester(str(self.dir / "*.jsonl.gz"), "r", store, poll=0, clock=clock, truncate_after=10)
        ing.poll_once()
        clock.t += 9
        ing.poll_once()
        self.assertEqual(ing.files[str(path)].status, "reading")
        clock.t += 2
        ing.poll_once()
        self.assertEqual(ing.files[str(path)].status, "failed")
        self.assertEqual(ing.exit_code, 1)
        self.assertEqual(store.select("ingest_files", {"run": "r"})[0]["status"], "failed")

    def test_unchanged_file_is_not_failed_while_the_emit_ledger_says_running(self):
        # inject: ignore the emit ledger status in the truncation rule
        path = self.dir / "zone0-000.jsonl.gz"
        GrowingGz(path).write(b"".join(self.lines[:30]))
        (self.dir / "emit_ledger.json").write_text(json.dumps(emit_doc({0: [path.name]}, 999, status="running")))
        clock = Clock()
        ing = Ingester(str(self.dir / "*.jsonl.gz"), "r", MemoryStore(), poll=0, clock=clock, truncate_after=10)
        ing.poll_once()
        clock.t += 60
        ing.poll_once()
        self.assertEqual(ing.files[str(path)].status, "reading")
        self.assertEqual(ing.exit_code, 0)

    def test_corrupt_gzip_is_failed(self):
        # inject: let zlib.error escape (crash) or skip the CRC/trailer check
        path = self.dir / "zone0-000.jsonl.gz"
        write_gz(path, self.lines)
        raw = bytearray(path.read_bytes())
        raw[-6] ^= 0xFF  # inside the CRC32 of the trailer
        path.write_bytes(bytes(raw))
        ing, store, code = ingest_dir(self.dir, once=True)
        self.assertEqual(ing.files[str(path)].status, "failed")
        self.assertEqual(code, 1)

    def test_zone_files_are_read_in_nnn_order(self):
        # inject: open file nnn+1 while nnn is incomplete (the sequence check then counts a gap)
        p0, p1 = self.dir / "zone0-000.jsonl.gz", self.dir / "zone0-001.jsonl.gz"
        half = 120
        g = GrowingGz(p0)
        g.write(b"".join(self.lines[:half]))
        write_gz(p1, self.lines[half:])
        ing = Ingester(str(self.dir / "*.jsonl.gz"), "r", MemoryStore(), poll=0)
        ing.poll_once()
        self.assertEqual(ing.files[str(p1)].fed, 0)
        self.assertEqual(ing.files[str(p1)].status, "discovered")
        self.assertEqual(ing.ledger.total("messages_parsed"), half)
        g.close()
        ing.poll_once()
        self.assertEqual({f.status for f in ing.files.values()}, {"complete"})
        self.assertEqual(ing.ledger.total("messages_accepted"), len(self.lines))
        self.assertEqual(ing.ledger.total("sequence_gaps"), 0)

    def test_rejects_are_recorded_with_reason_and_offset(self):
        # inject: drop rejected lines silently, or advance the offset by the stripped length
        bad = [b"{broken\n", b"\n", b"[]\n"]
        lines = self.lines[:8] + bad + self.lines[8:12]
        write_gz(self.dir / "zone0-000.jsonl.gz", lines)
        ing, store, _ = ingest_dir(self.dir, once=True)
        rows = store.select("rejects", {"run": "r"})
        self.assertEqual([r["reason"] for r in rows], ["json", "json", "type"])
        self.assertEqual(rows[0]["offset"], sum(map(len, self.lines[:8])))
        self.assertEqual(ing.ledger.total("messages_rejected"), 3)
        self.assertEqual(ing.ledger.total("messages_parsed"), 12)


class TestOrderIndependence(unittest.TestCase):
    def test_shuffled_batches_and_mid_batch_split_give_identical_outputs(self):
        # inject: process a batch in arrival order (or close a batch at a read boundary instead of on a later ts)
        sc = scenario()
        base = interleaved(sc)
        rng = random.Random(7)
        shuffled = []
        for t in range(40):
            for z in ("0", "1"):
                batch = [ln for s, ln in sc[z] if s == t]
                rng.shuffle(batch)
                shuffled.extend(batch)
        self.assertNotEqual(base, shuffled)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            for name, ls in (("plain", base), ("shuffled", shuffled)):
                (tmp / name).mkdir()
                write_gz(tmp / name / "zone0-000.jsonl.gz", ls)
            out = {n: tables(ingest_dir(tmp / n, once=True)[1]) for n in ("plain", "shuffled")}
            # growing file, installments split in the middle of a (zone, ts) batch
            (tmp / "split").mkdir()
            g = GrowingGz(tmp / "split" / "zone0-000.jsonl.gz")
            store = MemoryStore()
            ing = Ingester(str(tmp / "split" / "*.jsonl.gz"), "r", store, poll=0)
            for a, b in ((0, 7), (7, 33), (33, 61), (61, len(base))):
                g.write(b"".join(base[a:b])) if b < len(base) else g.close(b"".join(base[a:b]))
                ing.poll_once()
            ing.finish()
            out["split"] = tables(store)
        self.assertGreater(len(out["plain"]["stuck_episodes"]), 0)
        self.assertGreater(len(out["plain"]["decisions"]), 0)
        self.assertEqual(out["plain"], out["shuffled"])
        self.assertEqual(out["plain"], out["split"])

    def test_scenario_detections_are_the_expected_ones(self):
        # inject: change any cause / resolution rule (the scripted episodes then differ)
        with tempfile.TemporaryDirectory() as tmp:
            write_gz(Path(tmp) / "zone0-000.jsonl.gz", interleaved(scenario()))
            _, store, _ = ingest_dir(tmp, once=True)
        eps = {e["robot"]: e for e in store.select("stuck_episodes")}
        self.assertEqual({r: (e["cause"], e["resolution"]) for r, e in eps.items()},
                         {"Z0-00": ("blocked_by_faulted", "moved"), "Z0-02": ("unknown", "unresolved"),
                          "Z1-00": ("faulted_self", "fault_cleared")})
        self.assertEqual(eps["Z0-00"]["blocker"], "Z0-01")
        self.assertTrue(eps["Z0-00"]["avoidable"])


class TestRealEmitterRuns(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name) / "run"
        emit_real(cls.dir, 1, 120)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_custom_is_never_read(self):
        # inject: let any detection or decision depend on a custom value (e.g. open an episode on custom.stuck_event)
        corrupt = Path(self.tmp.name) / "corrupt"
        corrupt.mkdir()
        shutil.copy(self.dir / "emit_ledger.json", corrupt)
        for p in sorted(self.dir.glob("*.jsonl.gz")):
            out = []
            with gzip.open(p, "rb") as f:
                for raw in f:
                    obj = json.loads(raw)
                    obj["custom"] = dict(GARBAGE_CUSTOM)
                    out.append((json.dumps(obj, separators=(",", ":")) + "\n").encode())
            write_gz(corrupt / p.name, out)
        a = tables(ingest_dir(self.dir)[1])
        b = tables(ingest_dir(corrupt)[1])
        self.assertGreaterEqual(len(a["stuck_episodes"]), 1)  # not vacuous
        self.assertGreaterEqual(len(a["decisions"]), 1)
        self.assertEqual(a["transitions"], b["transitions"])
        self.assertEqual(a["stuck_episodes"], b["stuck_episodes"])
        self.assertEqual(a["decisions"], b["decisions"])

    def test_unlisted_stale_file_is_not_ingested_and_coverage_is_one(self):
        # inject: ingest every file the glob matches (the stale copy then pushes coverage above 1.0)
        stale_dir = Path(self.tmp.name) / "stale"
        shutil.copytree(self.dir, stale_dir)
        shutil.copy(stale_dir / "zone0-000.jsonl.gz", stale_dir / "zone0-001.jsonl.gz")
        ing, store, code = ingest_dir(stale_dir)
        doc = json.loads((stale_dir / "emit_ledger.json").read_text())
        stale = ing.files[str(stale_dir / "zone0-001.jsonl.gz")]
        self.assertEqual(stale.status, "unlisted")
        self.assertEqual(stale.fed, 0)
        self.assertEqual(code, 0)
        self.assertEqual(accepted_total(store) / doc["total"]["expected_messages"], 1.0)
        self.assertEqual(sum(r["duplicates"] for r in store.select("ingest_ledger")), 0)
        statuses = {r["path"].rsplit("/", 1)[1]: r["status"] for r in store.select("ingest_files")}
        self.assertEqual(statuses, {"zone0-000.jsonl.gz": "complete", "zone0-001.jsonl.gz": "unlisted"})

    def test_stale_file_waits_as_discovered_while_the_emit_ledger_is_running(self):
        # inject: mark an unlisted file `unlisted` before the emit ledger is final
        d = Path(self.tmp.name) / "waiting"
        shutil.copytree(self.dir, d)
        doc = json.loads((d / "emit_ledger.json").read_text())
        doc["status"] = "running"
        (d / "emit_ledger.json").write_text(json.dumps(doc))
        shutil.copy(d / "zone0-000.jsonl.gz", d / "zone0-001.jsonl.gz")
        ing = Ingester(str(d / "*.jsonl.gz"), "r", MemoryStore(), poll=0)
        ing.poll_once()
        self.assertEqual(ing.files[str(d / "zone0-001.jsonl.gz")].status, "discovered")
        self.assertEqual(ing.files[str(d / "zone0-001.jsonl.gz")].fed, 0)

    def test_cli_exit_codes_and_kafka_stub(self):
        # inject: exit 0 on a failed file, or let --source kafka do anything but print the one line and exit 2
        r = subprocess.run([sys.executable, INGEST, "--source", "file", "--glob", str(self.dir / "*.jsonl.gz"),
                            "--run", "cli", "--store", f"jsonl:{self.dir.parent}/cli-store", "--poll", "0.1"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("coverage 1.0", r.stdout)
        k = subprocess.run([sys.executable, INGEST, "--source", "kafka"], capture_output=True, text=True)
        self.assertEqual(k.returncode, 2)
        self.assertEqual(k.stderr.strip(), "kafka source: S5B2")


if __name__ == "__main__":
    unittest.main()

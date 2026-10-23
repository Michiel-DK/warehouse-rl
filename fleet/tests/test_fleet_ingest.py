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


def bounded_sleep(limit=300):
    """A poll sleep that fails the test instead of spinning forever when the loop never finishes."""
    n = [0]

    def sleep(_s):
        n[0] += 1
        if n[0] > limit:
            raise RuntimeError("the ingest loop did not finish")

    return sleep


def ingest_dir(directory, store=None, run="r", clock=None, **kw):
    store = MemoryStore() if store is None else store
    kw.setdefault("sleep", bounded_sleep())
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
        # inject: treat the end of the bytes on disk as the end of the file (complete before the trailer)
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
        # inject: restart a file from byte 0 without skipping the checkpoint offset
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

    def test_hard_kill_resume_ledger_matches_checkpoint(self):
        # inject: on resume, preload the counters from ingest_ledger rows instead of the newest checkpoint's snapshot
        path = self.dir / "zone0-000.jsonl.gz"
        first = 100
        g = GrowingGz(path)
        g.write(b"".join(self.lines[:first]))
        store = JsonlStore(self.dir / "store")
        ing1 = Ingester(str(self.dir / "*.jsonl.gz"), "r", store, poll=0, ledger_interval=1e9)
        ing1.poll_once()  # then the process dies: no finish(), no ledger row ever written
        self.assertEqual(store.select("ingest_ledger", {"run": "r"}), [])
        self.assertEqual(store.select("ingest_checkpoints", {"run": "r"})[0]["offset_uncompressed"],
                         sum(map(len, self.lines[:first])))
        store.close()
        g.close(b"".join(self.lines[first:]))
        store2 = JsonlStore(self.dir / "store")
        ing2 = Ingester(str(self.dir / "*.jsonl.gz"), "r", store2, poll=0, once=True)
        ing2.run_loop()
        self.assertEqual(accepted_total(store2), len(self.lines))
        rows = store2.select("ingest_ledger", {"run": "r"})
        self.assertEqual(sum(r["duplicates"] for r in rows), 0)
        self.assertEqual(sum(r["sequence_gaps"] for r in rows), 0)
        store2.close()

    def test_resume_censors_runs_and_interrupts_open_episodes(self):
        # inject: write the stuck_cause decision for a left_censored episode (drop the left_censored skip in ingest)
        path = self.dir / "zone0-000.jsonl.gz"
        lines = [line("Z0-00", t, t, order="o1", driving=t >= 30, x=0 if t < 30 else 1) for t in range(40)]
        g = GrowingGz(path)
        g.write(b"".join(lines[:12]))
        store = JsonlStore(self.dir / "store")
        ing1 = Ingester(str(self.dir / "*.jsonl.gz"), "r", store, poll=0, ledger_interval=1e9)
        ing1.poll_once()  # stuck at step 6, then the process dies with the episode open
        self.assertEqual(len(store.select("decisions")), 1)
        store.close()
        g.close(b"".join(lines[12:]))
        store2 = JsonlStore(self.dir / "store")
        Ingester(str(self.dir / "*.jsonl.gz"), "r", store2, poll=0, once=True).run_loop()
        eps = {e["episode_id"]: e for e in store2.select("stuck_episodes", {"run": "r"})}
        self.assertEqual(eps[f"Z0-00@{iso(BASE)}"]["resolution"], "interrupted")
        resumed = [e for e in eps.values() if e["left_censored"]]
        self.assertEqual(len(resumed), 1)
        self.assertEqual(resumed[0]["resolution"], "moved")
        self.assertEqual(len(store2.select("decisions")), 1)  # no second stuck_cause under a shifted dedup_key
        store2.close()

    def test_truncated_file_is_failed(self):
        # inject: wait forever on a file that never reaches end of stream
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
        # inject: let zlib.error escape instead of marking the file failed
        path = self.dir / "zone0-000.jsonl.gz"
        write_gz(path, self.lines)
        raw = bytearray(path.read_bytes())
        raw[-6] ^= 0xFF  # inside the CRC32 of the trailer
        path.write_bytes(bytes(raw))
        ing, store, code = ingest_dir(self.dir, once=True)
        self.assertEqual(ing.files[str(path)].status, "failed")
        self.assertEqual(code, 1)

    def test_zone_files_are_read_in_nnn_order(self):
        # inject: move on to file nnn+1 while nnn is incomplete (the sequence check then counts a gap)
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
        # inject: record offset 0 for every reject
        bad = [b"{broken\n", b"\n", b"[]\n"]
        lines = self.lines[:8] + bad + self.lines[8:12]
        write_gz(self.dir / "zone0-000.jsonl.gz", lines)
        ing, store, _ = ingest_dir(self.dir, once=True)
        rows = store.select("rejects", {"run": "r"})
        self.assertEqual([r["reason"] for r in rows], ["json", "json", "type:line"])
        self.assertEqual(rows[0]["offset"], sum(map(len, self.lines[:8])))
        self.assertEqual(ing.ledger.total("messages_rejected"), 3)
        self.assertEqual(ing.ledger.total("messages_parsed"), 12)


class TestOrderIndependence(unittest.TestCase):
    def test_shuffled_batches_and_mid_batch_split_give_identical_outputs(self):
        # inject: process a batch in arrival order instead of serial order
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
            ts = [json.loads(ln)["timestamp"] for ln in base]
            self.assertEqual(ts[6], ts[7])  # the first split point (7) is inside a (zone, ts) batch
            self.assertEqual(ts[60], ts[61])
            for a, b in ((0, 7), (7, 32), (32, 61), (61, len(base))):
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
        # inject: let ingest drop lines whose custom.stuck_event is true (any dependency on a custom value)
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
        # inject: mark an unlisted file `unlisted` even while the emit ledger is running
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
        # inject: change the kafka stub's message or exit code
        r = subprocess.run([sys.executable, INGEST, "--source", "file", "--glob", str(self.dir / "*.jsonl.gz"),
                            "--run", "cli", "--store", f"jsonl:{self.dir.parent}/cli-store", "--poll", "0.1"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("coverage 1.0", r.stdout)
        k = subprocess.run([sys.executable, INGEST, "--source", "kafka"], capture_output=True, text=True)
        self.assertEqual(k.returncode, 2)
        self.assertEqual(k.stderr.strip(), "kafka source: S5B2")



# ---------------------------------------------------------------------------------------------------- S17A
S17A_FIXTURE = ROOT / "fleet" / "tests" / "data" / "s17a_emit50"
# Store content hash of the fixture ingest measured on the code before S17A (parse.py unmodified), 23 Oct 2026.
S17A_FIXTURE_HASH = "233700cb3016c31c8706a56376537a22c4f3fec7b4df98158dca9a475225e27a"
S17A_BAD_LOG = [b'{"robot":"r1","time":"2026-10-23 08:00:00","x":1,"y":2}\n',
                b'{"robot":"r1","time":"2026-10-23 08:00:00","x":1,"y":2}\n', b"not json at all\n"]


def store_content_hash(store_dir):
    """Every *.jsonl of a jsonl store except ingest_* (wall clock); decisions rows without recorded_at, sorted."""
    import hashlib
    h = hashlib.sha256()
    for f in sorted(Path(store_dir).glob("*.jsonl")):
        if f.name.startswith("ingest_"):
            continue
        lines = f.read_bytes().splitlines()
        if f.name == "decisions.jsonl":
            rows = [json.loads(ln) for ln in lines]
            for r in rows:
                r.pop("recorded_at", None)
            lines = sorted(json.dumps(r, sort_keys=True).encode() for r in rows)
        h.update(f.name.encode() + b"\0" + b"\n".join(lines) + b"\0")
    return h.hexdigest()


def run_ingest(*args):
    return subprocess.run([sys.executable, INGEST, *map(str, args)], capture_output=True, text=True)


class TestS17aMinAccepted(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        (self.dir / "badlog").mkdir()
        write_gz(self.dir / "badlog" / "zone0-000.jsonl.gz", S17A_BAD_LOG)

    def test_bad_log_once_with_flag_exits_2_and_names_the_reasons(self):
        # inject: leave the exit code at 0, or drop the DOES NOT MATCH line
        r = run_ingest("--glob", self.dir / "badlog" / "*.jsonl.gz", "--store", f"jsonl:{self.dir / 's'}", "--once",
                       "--min-accepted", "0.5")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        out = r.stdout.splitlines()
        self.assertIn("accepted 0 (parsed 0, rejected 3, duplicates 0)", out[0])
        self.assertTrue(out[0].endswith("exit 2"), out[0])
        self.assertEqual(out[1], "ingest badlog: rejects by reason missing:headerId 2, json 1; top failing keys "
                                 "headerId 2")
        self.assertEqual(out[2], "ingest badlog: DOES NOT MATCH the fleet-state contract, run fleet/check_log.py")
        rows = [json.loads(ln) for ln in (self.dir / "s" / "rejects.jsonl").read_text().splitlines()]
        self.assertEqual([x["reason"] for x in rows], ["missing:headerId", "missing:headerId", "json"])

    def test_bad_log_once_without_flag_keeps_exit_0(self):
        # inject: make the default 0.5 apply with --once
        r = run_ingest("--glob", self.dir / "badlog" / "*.jsonl.gz", "--store", f"jsonl:{self.dir / 's'}", "--once")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(len(r.stdout.splitlines()), 1)
        self.assertTrue(r.stdout.strip().endswith("exit 0"))

    def test_flag_is_validated(self):
        # inject: accept 1.5
        r = run_ingest("--glob", self.dir / "badlog" / "*.jsonl.gz", "--once", "--min-accepted", "1.5")
        self.assertEqual(r.returncode, 2)
        self.assertIn("--min-accepted", r.stderr)

    def test_existing_nonzero_code_is_kept_and_empty_input_is_no_mismatch(self):
        # inject: report 0 rejected + 0 accepted as a mismatch, or overwrite exit 1 with 2
        ing = Ingester(str(self.dir / "badlog" / "*.jsonl.gz"), "r", MemoryStore(), poll=0, once=True)
        self.assertEqual(ing.contract_check(0.5, 0), (0, []))
        ing.reject_reasons["json"] += 4
        ing.ledger.rejected()
        self.assertEqual(ing.contract_check(0.5, 1)[0], 1)
        self.assertEqual(ing.contract_check(0.5, 0)[0], 2)
        self.assertEqual(ing.contract_check(None, 0), (0, []))

    def test_share_boundary(self):
        # inject: compare with <= instead of <
        ing = Ingester(str(self.dir / "badlog" / "*.jsonl.gz"), "r", MemoryStore(), poll=0, once=True)
        ing.ledger.accepted()
        ing.ledger.rejected()
        ing.reject_reasons["json"] += 1
        self.assertEqual(ing.contract_check(0.5, 0), (0, []))
        self.assertEqual(ing.contract_check(0.51, 0)[0], 2)


class TestS17aDefault(unittest.TestCase):
    def test_default_share_per_source_and_once(self):
        # inject: make the default apply with --once or on kafka, or drop it on the file source
        from ingest import min_accepted_for
        self.assertEqual(min_accepted_for("file", False, None), 0.5)
        self.assertIsNone(min_accepted_for("file", True, None))
        self.assertIsNone(min_accepted_for("kafka", False, None))
        self.assertIsNone(min_accepted_for("kafka", True, None))
        for source, once in (("file", False), ("file", True), ("kafka", False)):
            self.assertEqual(min_accepted_for(source, once, 0.8), 0.8)
            self.assertEqual(min_accepted_for(source, once, 0.0), 0.0)

    def test_file_source_without_once_on_a_matching_log_ends_with_exit_0_and_the_same_store(self):
        # the default 0.5 is in force here (no --once); the fixture's emit_ledger.json says complete, so the run ends
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run([sys.executable, INGEST, "--glob", str(S17A_FIXTURE / "*.jsonl.gz"), "--run",
                                "s17a-emit50", "--store", f"jsonl:{tmp}", "--poll", "0.1"],
                               capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(len(r.stdout.splitlines()), 1)
            self.assertEqual(store_content_hash(tmp), S17A_FIXTURE_HASH)


class TestS17aFixtureIngest(unittest.TestCase):
    def ingest_hash(self, *extra):
        with tempfile.TemporaryDirectory() as tmp:
            r = run_ingest("--glob", S17A_FIXTURE / "*.jsonl.gz", "--run", "s17a-emit50", "--store",
                           f"jsonl:{tmp}", "--once", *extra)
            return r.returncode, r.stdout, store_content_hash(tmp)

    def test_store_content_hash_equals_pre_change_value(self):
        # inject: let the extended reasons or the min-accepted check change a store row
        code, out, h = self.ingest_hash()
        self.assertEqual(code, 0, out)
        self.assertEqual(h, S17A_FIXTURE_HASH)
        self.assertEqual(self.ingest_hash()[2], S17A_FIXTURE_HASH)

    def test_matching_log_with_flag_is_unchanged(self):
        # inject: write a row or print a line when the log matches
        code, out, h = self.ingest_hash("--min-accepted", "0.5")
        self.assertEqual((code, h), (0, S17A_FIXTURE_HASH))
        self.assertEqual(len(out.splitlines()), 1)
        self.assertIn("accepted 600 (parsed 600, rejected 0, duplicates 0)", out)


if __name__ == "__main__":
    unittest.main()

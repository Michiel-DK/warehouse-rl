"""Tests for the ingest ledger: sequence accounting, per-row byte invariant, totals, coverage, lag gating, retention,
and the `ledger.py status` / `plot` CLI against a store written by an earlier process.
Each case names its red demonstration in an `# inject:` comment."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "fleet") not in sys.path:
    sys.path.insert(0, str(ROOT / "fleet"))

from fleet.tests.test_fleet_ingest import (INGEST, emit_real, ingest_dir, interleaved, line,  # noqa: E402
                                           scenario, write_gz)
from fleet.tests.test_fleet_ingest import BASE  # noqa: E402
from fleet_analyser import decisions  # noqa: E402
from fleet_analyser.ledger import SequenceTracker, coverage, lag_enabled, status_lines  # noqa: E402
from fleet_analyser.store import MemoryStore  # noqa: E402

LEDGER = str(ROOT / "fleet" / "ledger.py")


class TickClock:
    """A wall clock that advances a fixed amount on every read, so a short test spans several minutes."""

    def __init__(self, step, t=1_800_000_000.0):
        self.t, self.step = t, step

    def __call__(self):
        self.t += self.step
        return self.t


class TestSequence(unittest.TestCase):
    def test_duplicate_gap_and_first_message_gap(self):
        # inject: treat headerId == h as accepted, count a gap as h - last instead of h - last - 1, or count a
        # first message with k > 0 as no gap
        t = SequenceTracker()
        seen = [("A", 0), ("A", 1), ("A", 1), ("A", 3), ("A", 2), ("A", 4), ("B", 5)]
        got = [t.check(s, h) for s, h in seen]
        self.assertEqual(got, [(True, 0), (True, 0), (False, 0), (True, 1), (False, 0), (True, 0), (True, 5)])
        self.assertEqual((t.accepted, t.duplicates, t.gaps, t.missing), (5, 2, 2, 6))
        self.assertEqual(t.accepted + t.duplicates, len(seen))  # accepted = valid and not duplicate

    def test_first_message_zero_is_not_a_gap(self):
        # inject: count the first message of every robot as a gap
        t = SequenceTracker()
        self.assertEqual(t.check("A", 0), (True, 0))
        self.assertEqual((t.gaps, t.missing), (0, 0))

    def test_seeded_tracker_resumes_without_a_gap(self):
        # inject: ignore the seed (a resumed robot then looks like a first message with k > 0)
        t = SequenceTracker({"A": 9})
        self.assertEqual(t.check("A", 10), (True, 0))
        self.assertEqual(t.check("A", 9), (False, 0))

    def test_gaps_and_duplicates_reach_the_ledger_through_ingest(self):
        # inject: skip the sequence check in the ingest line handler (accepted, missing = True, 0)
        lines = [line("Z0-00", h, h) for h in (0, 1, 1, 4, 5)] + [line("Z0-01", 3, 3)]
        with tempfile.TemporaryDirectory() as tmp:
            write_gz(Path(tmp) / "zone0-000.jsonl.gz", lines)
            ing, store, _ = ingest_dir(tmp, once=True)
        led = ing.ledger
        self.assertEqual((led.total("messages_parsed"), led.total("messages_accepted"), led.total("duplicates")),
                         (6, 5, 1))
        self.assertEqual((led.total("sequence_gaps"), led.total("missing_messages")), (2, 2 + 3))


class TestLagGate(unittest.TestCase):
    def test_lag_is_only_enabled_for_now_realtime_speed_one(self):
        # inject: enable lag for fixed t0, or for speed != 1
        ok = {"t0_mode": "now", "rate": "realtime", "speed": 1.0}
        self.assertTrue(lag_enabled(ok))
        for bad in (dict(ok, t0_mode="fixed"), dict(ok, rate="flat"), dict(ok, speed=2.0), dict(ok, speed=0.0), {}, None):
            self.assertFalse(lag_enabled(bad))

    def test_coverage_arithmetic(self):
        # inject: divide expected by accepted, or return 0 for an unknown denominator
        self.assertEqual(coverage(90, 120), 0.75)
        self.assertIsNone(coverage(5, None))


class TestRealRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name) / "run"
        emit_real(cls.dir, 2, 120)
        cls.doc = json.loads((cls.dir / "emit_ledger.json").read_text())
        cls.files = sorted(cls.dir.glob("*.jsonl.gz"))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_coverage_is_exactly_one_and_totals_match_the_emit_ledger(self):
        # inject: count every accepted message twice in the ledger
        ing, store, code = ingest_dir(self.dir, clock=TickClock(0.01))
        rows = store.select("ingest_ledger", {"run": "r"})
        expected = self.doc["total"]["expected_messages"]
        self.assertEqual(code, 0)
        self.assertEqual(sum(r["messages_accepted"] for r in rows) / expected, 1.0)
        self.assertEqual(sum(r["messages_parsed"] for r in rows), expected)
        self.assertEqual(sum(r["bytes_read_uncompressed"] for r in rows), self.doc["total"]["bytes_uncompressed"])
        self.assertEqual(sum(r["bytes_read_compressed"] for r in rows), sum(p.stat().st_size for p in self.files))
        self.assertEqual(sum(r["messages_rejected"] + r["duplicates"] + r["sequence_gaps"] for r in rows), 0)
        self.assertTrue(all(r["backlog_bytes"] == 0 for r in rows[-1:]))
        self.assertEqual(store.select("ingest_runs", {"run": "r"})[0]["expected_messages"], expected)

    def test_kept_plus_dropped_equals_read_per_row_across_minutes(self):
        # inject: in IngestLedger.keep add to bytes_kept without subtracting from bytes_dropped
        clock = TickClock(0.05)  # ~50 ms per clock read: the run spans several wall minutes
        ing, store, _ = ingest_dir(self.dir, clock=clock)
        rows = store.select("ingest_ledger", {"run": "r"})
        self.assertGreater(len(rows), 1)
        for r in rows:
            self.assertEqual(r["bytes_kept"] + r["bytes_dropped"], r["bytes_read_uncompressed"])
            self.assertGreaterEqual(r["bytes_dropped"], 0)
            self.assertEqual(r["minute"] % 60, 0)
            self.assertGreater(r["msgs_per_s"], 0)
            self.assertGreater(r["mb_per_s"], 0)
        self.assertEqual(sum(r["bytes_kept"] for r in rows) + sum(r["bytes_dropped"] for r in rows),
                         self.doc["total"]["bytes_uncompressed"])

    def test_lag_is_null_for_a_fixed_t0_run_and_set_for_now_realtime(self):
        # inject: compute lag for every run, whatever the emit config says (months of lag for the fixed-t0 emitter)
        _, store, _ = ingest_dir(self.dir)
        rows = store.select("ingest_ledger", {"run": "r"})
        self.assertTrue(all(r["lag_p50_s"] is None and r["lag_p99_s"] is None for r in rows))
        live = Path(self.tmp.name) / "live"
        shutil.copytree(self.dir, live)
        doc = json.loads((live / "emit_ledger.json").read_text())
        doc["config"].update(t0_mode="now", rate="realtime", speed=1.0)
        (live / "emit_ledger.json").write_text(json.dumps(doc))
        _, store, _ = ingest_dir(live)
        rows = store.select("ingest_ledger", {"run": "r"})
        self.assertTrue(all(r["lag_p50_s"] is not None and r["lag_p99_s"] >= r["lag_p50_s"] for r in rows))

    def test_behind_emitter_is_event_seconds_and_null_without_an_emit_ledger(self):
        # inject: add one second to behind_emitter_s
        _, store, _ = ingest_dir(self.dir)
        self.assertEqual(store.select("ingest_ledger", {"run": "r"})[-1]["behind_emitter_s"], 0)
        with tempfile.TemporaryDirectory() as tmp:
            write_gz(Path(tmp) / "zone0-000.jsonl.gz", [ln for _, ln in scenario()["0"]])
            _, store, _ = ingest_dir(tmp, once=True)
        self.assertIsNone(store.select("ingest_ledger", {"run": "r"})[-1]["behind_emitter_s"])
        self.assertIsNone(store.select("ingest_runs", {"run": "r"})[0]["expected_messages"])

    def test_status_cli_prints_coverage_from_a_store_written_by_an_earlier_process(self):
        # inject: print the coverage line without its value
        store_dir = Path(self.tmp.name) / "cli-store"
        r = subprocess.run([sys.executable, INGEST, "--source", "file", "--glob", str(self.dir / "*.jsonl.gz"),
                            "--run", "cli", "--store", f"jsonl:{store_dir}", "--poll", "0.1"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        s = subprocess.run([sys.executable, LEDGER, "status", "--run", "cli", "--store", f"jsonl:{store_dir}"],
                           capture_output=True, text=True)
        self.assertEqual(s.returncode, 0, s.stderr)
        expected = self.doc["total"]["expected_messages"]
        self.assertIn(f"coverage: 1.0 (accepted {expected} / expected {expected})", s.stdout)
        for needle in ("last 1 min", "last 5 min", "last 60 min", "total [file]", "backlog_bytes (latest row): 0",
                       "rejects 0", "duplicates 0", "gaps 0", "kept ratio", "files: complete 2",
                       "episodes per cause:", "decisions:"):
            self.assertIn(needle, s.stdout)
        p = subprocess.run([sys.executable, LEDGER, "plot", "--run", "cli", "--store", f"jsonl:{store_dir}"],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        png = store_dir.parent / "ledger.png"
        self.assertEqual(p.stdout.strip(), str(png))
        self.assertTrue(png.read_bytes().startswith(b"\x89PNG"))

    def test_status_cli_without_an_emit_ledger_prints_coverage_none(self):
        # inject: print 0.0 instead of None when there is no emit ledger
        store_dir = Path(self.tmp.name) / "noemit-store"
        data = Path(self.tmp.name) / "noemit"
        data.mkdir()
        write_gz(data / "zone0-000.jsonl.gz", [ln for _, ln in scenario()["0"]])
        subprocess.run([sys.executable, INGEST, "--source", "file", "--glob", str(data / "*.jsonl.gz"), "--run", "n",
                        "--store", f"jsonl:{store_dir}", "--once"], capture_output=True, text=True, check=True)
        s = subprocess.run([sys.executable, LEDGER, "status", "--run", "n", "--store", f"jsonl:{store_dir}"],
                           capture_output=True, text=True)
        self.assertIn("coverage: None", s.stdout)


class TestRetention(unittest.TestCase):
    def test_kept_bytes_are_exactly_evidence_state_samples_and_reject_raws(self):
        # inject: stop marking state_sample lines as kept
        bad = [b"{broken\n", b"x" * 5000 + b"\n"]
        lines = interleaved(scenario(steps=60))
        lines = lines[:50] + bad + lines[50:]
        with tempfile.TemporaryDirectory() as tmp:
            write_gz(Path(tmp) / "zone0-000.jsonl.gz", lines)
            ing, store, _ = ingest_dir(tmp, once=True)
        held = set()
        for e in store.select("evidence"):
            held.update(e["lines"])
        held.update(s["raw"] for s in store.select("state_sample"))
        want = sum(len(x.encode()) for x in held) + sum(len(r["raw"].encode()) for r in store.select("rejects"))
        self.assertEqual(ing.ledger.total("bytes_kept"), want)
        self.assertEqual(len(store.select("rejects")), 2)
        self.assertEqual(max(len(r["raw"]) for r in store.select("rejects")), 4096)  # first 4096 bytes only
        self.assertGreater(len(store.select("state_sample")), 0)
        self.assertTrue(all(json.loads(s["raw"])["headerId"] % 50 == 0 for s in store.select("state_sample")))


class TestStatusCountableAndGrades(unittest.TestCase):
    """S5C1: status counts only countable episodes (and says what it left out) and rolls the grades up per kind."""

    @staticmethod
    def episode(i, cause="unknown", resolution="moved", left_censored=False):
        return dict(run="r", episode_id=f"E{i}", zone="0", robot=f"Z0-{i:02d}", order_id="o", start=BASE + i,
                    start_iso="", t_entry=BASE + i + 30, cell=[0, 0], cause=cause, blocker=None, blocker_faulted_s=None,
                    end=None if resolution in ("open", "interrupted") else BASE + i + 99, duration_s=None,
                    resolution=resolution, avoidable=False, avoidable_s=None, left_censored=left_censored)

    @staticmethod
    def decide(store, kind, subject, decided_at, verdict=None):
        did, _ = decisions.record_decision(store, run="r", kind=kind, subject=subject, start_iso=f"{subject}-{decided_at}",
                                           decided_at=decided_at, claim={}, rationale="x", expected=None,
                                           grade_after=decided_at + 3600, recorded_at=1.0)
        if verdict:
            decisions.stamp_grade(store, did, {}, None, verdict, decided_at + 5)

    def test_status_counts_only_countable_episodes_and_reports_the_rest(self):
        # inject: count every stuck_episodes row in the per-cause and per-resolution lines
        store = MemoryStore()
        store.insert("stuck_episodes", [
            self.episode(1, "traffic"), self.episode(2, "unknown", "unresolved"), self.episode(3, "unknown"),
            self.episode(4, "unknown", "open"), self.episode(5, "traffic", "interrupted"),
            self.episode(6, "traffic", left_censored=True), self.episode(7, "traffic", "interrupted", left_censored=True)])
        lines = status_lines(store, "r")
        self.assertIn("episodes per cause: traffic 1, unknown 2", lines)
        self.assertIn("episodes per resolution: moved 2, unresolved 1", lines)
        self.assertIn("episodes excluded: left_censored 2, interrupted 1, open 1", lines)

    def test_excluded_line_is_printed_even_when_nothing_is_excluded(self):
        # inject: print the excluded line only when something was excluded
        store = MemoryStore()
        store.insert("stuck_episodes", [self.episode(1)])
        self.assertIn("episodes excluded: left_censored 0, interrupted 0, open 0", status_lines(store, "r"))

    def test_grade_lines_per_kind_with_accuracy_from_confirmed_and_refuted(self):
        # inject: divide by all graded decisions instead of confirmed + refuted, or count open decisions as graded
        t = BASE + 200_000
        store = MemoryStore()
        for i, v in enumerate(("confirmed", "confirmed", "refuted", "inconclusive")):
            self.decide(store, "stuck_cause", f"R{i}", t - i, v)
        self.decide(store, "stuck_cause", "ROPEN", t)  # still open: not a verdict
        self.decide(store, "stuck_cause", "ROLD", t - 90_000, "refuted")  # outside the 86400 s window
        self.decide(store, "avoidable_reset", "R9", t - 10, "reset_happened")
        lines = status_lines(store, "r")
        self.assertIn("grades last day [stuck_cause]: confirmed 2, refuted 1, inconclusive 1, accuracy 0.6666666666666666",
                      lines)
        self.assertIn("grades last day [avoidable_reset]: confirmed 0, refuted 0, inconclusive 0, reset_happened 1, "
                      "accuracy null", lines)

    def test_window_is_anchored_on_the_latest_decision_of_the_run_not_the_wall_clock(self):
        # inject: anchor the window on the latest graded decision, or on time.time()
        t = BASE
        store = MemoryStore()
        self.decide(store, "stuck_cause", "A", t, "confirmed")
        self.decide(store, "stuck_cause", "B", t + 86_400, "refuted")  # exactly 86400 s later: A is still inside
        lines = [ln for ln in status_lines(store, "r") if ln.startswith("grades last day")]
        self.assertEqual(lines, ["grades last day [stuck_cause]: confirmed 1, refuted 1, inconclusive 0, accuracy 0.5"])
        self.decide(store, "stuck_cause", "LATEOPEN", t + 86_401)  # an open decision still moves the anchor
        lines = [ln for ln in status_lines(store, "r") if ln.startswith("grades last day")]
        self.assertEqual(lines, ["grades last day [stuck_cause]: confirmed 0, refuted 1, inconclusive 0, accuracy 0.0"])

    def test_no_grade_lines_without_decisions(self):
        # inject: print a grades line for a kind that has no decision in the run
        self.assertFalse([ln for ln in status_lines(MemoryStore(), "r") if ln.startswith("grades last day")])


if __name__ == "__main__":
    unittest.main()

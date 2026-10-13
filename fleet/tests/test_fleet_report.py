"""Tests for the stuck-episode report (fleet_analyser/report.py, fleet/report.py): section contents on a scripted store,
the countable filter and its header, nearest-rank percentiles, byte-identical output, hotspots.png, Store-interface-only
reads. Each case names its red demonstration in an `# inject:` comment. Unit tests, no Docker, none skipped."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "fleet", ROOT / "src", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fleet.tests.test_fleet_grade import decide, episode  # noqa: E402
from fleet.tests.test_fleet_ingest import BASE  # noqa: E402
from fleet_analyser import decisions, report  # noqa: E402
from fleet_analyser.store import JsonlStore, MemoryStore, Store  # noqa: E402

REPORT_CLI = str(ROOT / "fleet" / "report.py")


def ep(robot, offset, dur, cause="unknown", resolution="moved", zone="0", cell=(1, 1), **kw):
    start = BASE + offset
    row = episode(robot=robot, start=start, end=start + dur, cause=cause, resolution=resolution, zone=zone,
                  cell=list(cell))
    row.update(kw)
    row["episode_id"] = f"{robot}@{start}"
    return row


def scripted_store():
    """5 countable episodes (3 for R1) and 3 excluded ones (open, interrupted, left_censored)."""
    store = MemoryStore()
    rows = [
        ep("R1", 0, 40, "blocked_by_faulted", avoidable=True, avoidable_s=10),
        ep("R1", 4000, 60),
        ep("R1", 8000, 100, "traffic", "order_dropped"),
        ep("R2", 100, 30, zone="1", cell=(2, 2)),
        ep("R3", 200, 50, "blocked_by_faulted", "unresolved", zone="1", cell=(2, 2)),
        ep("R4", 300, 0, resolution="open", end=None, duration_s=None),
        ep("R5", 400, 0, resolution="interrupted", end=None, duration_s=None),
        ep("R6", 500, 90, left_censored=True),
    ]
    store.insert("stuck_episodes", rows)
    for row, verdict in ((rows[0], "confirmed"), (rows[1], "refuted"), (rows[3], "inconclusive")):
        did = decide(store, row)
        decisions.stamp_grade(store, did, {}, None, verdict, BASE + 9999)
    decide(store, rows[4])  # still open
    return store


class OnlySelect(Store):
    """A store that allows select and nothing else: the report must go through the read side of the interface."""

    def __init__(self, inner):
        self.inner = inner
        self.calls = []

    def select(self, table, where=None):
        self.calls.append(table)
        return self.inner.select(table, where)


class TestSections(unittest.TestCase):
    def setUp(self):
        self.text = report.report_run(scripted_store(), "r")

    def test_header_counts_only_countable_episodes_and_states_the_rest(self):
        # inject: count every row of the run (drop the countable filter)
        self.assertIn("5 countable episodes (excluded: left_censored 1, interrupted 1, open 1).", self.text)

    def test_hotspots_episodes_per_hour_and_mixes(self):
        # inject: sort hotspots by cell only, or bucket hours by end instead of start
        self.assertIn("- zone 0 cell 1-1: 3\n- zone 1 cell 2-2: 2\n", self.text)
        self.assertIn("- 2026-01-01T00:00:00Z: 3\n- 2026-01-01T01:00:00Z: 1\n- 2026-01-01T02:00:00Z: 1\n", self.text)
        self.assertIn("## Cause mix\n\n- blocked_by_faulted: 2\n- traffic: 1\n- unknown: 2\n", self.text)
        self.assertIn("## Resolution mix\n\n- moved: 3\n- order_dropped: 1\n- unresolved: 1\n", self.text)

    def test_duration_and_time_to_resolution_are_nearest_rank(self):
        # inject: interpolate the percentiles, or measure time to resolution from start instead of t_entry
        self.assertEqual(report.nearest_rank([10, 20, 30, 40, 100], 0.5), 30)
        self.assertEqual(report.nearest_rank([10, 20, 30, 40, 100], 0.95), 100)
        self.assertIsNone(report.nearest_rank([], 0.5))
        dur = self.text.split("## Duration")[1].split("##")[0]
        self.assertIn("- p50: 50\n- p95: 100\n", dur)  # durations 30 40 50 60 100
        wait = self.text.split("## Time from stuck to resolution")[1].split("##")[0]
        self.assertIn("- p50: 20\n- p95: 70\n", wait)  # end - t_entry: 0 10 20 30 70
        self.assertIn("nearest-rank", self.text)

    def test_avoidable_is_labelled_near_tautological(self):
        # inject: drop the label text or count avoidable rows that are not countable
        sec = self.text.split("## Avoidable")[1].split("##")[0]
        self.assertIn("near-tautological", self.text)
        self.assertIn(report.AVOIDABLE_LABEL, self.text)
        self.assertIn("- episodes: 1\n- minutes: 0.17\n", sec)

    def test_repeat_robots_need_three_episodes(self):
        # inject: list robots with >= 2 episodes
        sec = self.text.split("## Repeat robots")[1].split("##")[0]
        self.assertIn("- R1: 3\n", sec)
        self.assertNotIn("R2", sec)

    def test_grades_per_kind_and_verdict(self):
        # inject: count open decisions under their (null) verdict or skip graded ones
        sec = self.text.split("## Decision grades")[1]
        for needle in ("- stuck_cause / confirmed: 1", "- stuck_cause / refuted: 1", "- stuck_cause / inconclusive: 1",
                       "- stuck_cause / open: 1"):
            self.assertIn(needle, sec)

    def test_hotspots_top_twenty_ties_by_zone_then_cell(self):
        # inject: keep 21 hotspots or break ties by robot
        eps = [ep(f"R{i}", i, 40, zone="1" if i % 2 else "0", cell=(i % 5, i // 5)) for i in range(30)]
        top = report.hotspots(eps)
        self.assertEqual(len(top), 20)
        self.assertEqual([n for *_, n in top], [1] * 20)
        self.assertEqual(top[0], ("0", (0, 0), 1))
        self.assertEqual([z for z, _, _ in top].count("0"), 15)  # all 15 zone "0" cells sort before zone "1"
        self.assertEqual([(z, c) for z, c, _ in top], sorted((z, c) for z, c, _ in top))
        eps += [ep("RX", 99, 40, zone="1", cell=(9, 9))] * 2
        self.assertEqual(report.hotspots(eps)[0], ("1", (9, 9), 2))

    def test_empty_run(self):
        # inject: divide or index into an empty list (crash on a run without episodes)
        text = report.report_run(MemoryStore(), "r")
        self.assertIn("0 countable episodes (excluded: left_censored 0, interrupted 0, open 0).", text)
        self.assertIn("- p50: n/a", text)


class TestFiles(unittest.TestCase):
    def test_same_store_gives_byte_identical_report_and_a_png_next_to_it(self):
        # inject: add a wall-clock line to the report, or write the png somewhere else
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / "a" / "report.md", Path(tmp) / "b" / "report.md"
            md1, png1 = report.write_report(scripted_store(), "r", a)
            md2, _ = report.write_report(scripted_store(), "r", b)
            self.assertEqual(a.read_bytes(), b.read_bytes())
            self.assertEqual(png1, a.parent / "hotspots.png")
            self.assertTrue(png1.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))
            empty = report.write_report(MemoryStore(), "r", Path(tmp) / "e" / "report.md")[1]
            self.assertTrue(empty.read_bytes().startswith(b"\x89PNG"))

    def test_report_reads_only_through_select(self):
        # inject: call store.insert (or any non-select method) from the report
        store = OnlySelect(scripted_store())
        with tempfile.TemporaryDirectory() as tmp:
            report.write_report(store, "r", Path(tmp) / "report.md")
        self.assertEqual(set(store.calls), {"stuck_episodes", "decisions"})

    def test_cli_writes_report_and_png_from_a_jsonl_store(self):
        # inject: ignore --out
        with tempfile.TemporaryDirectory() as tmp:
            src = scripted_store()
            js = JsonlStore(Path(tmp) / "st")
            js.insert("stuck_episodes", src.select("stuck_episodes"))
            js.insert("decisions", src.select("decisions"))
            js.close()
            out = Path(tmp) / "out" / "report.md"
            r = subprocess.run([sys.executable, REPORT_CLI, "--run", "r", "--store", f"jsonl:{Path(tmp) / 'st'}", "--out",
                                str(out)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(out.read_text(), report.report_run(src, "r"))
            self.assertTrue((out.parent / "hotspots.png").read_bytes().startswith(b"\x89PNG"))


if __name__ == "__main__":
    unittest.main()

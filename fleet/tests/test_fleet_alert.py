"""Tests for the stuck alert (fleet_analyser/alert.py, fleet/alert.py): the output line, what is alertable, startup
skipping, the latency lines, all with a fake clock and a MemoryStore. Each case names its red demonstration in an
`# inject:` comment. Unit tests, no Docker, none skipped."""
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "fleet", ROOT / "src", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fleet.tests.test_fleet_grade import episode  # noqa: E402
from fleet.tests.test_fleet_ingest import BASE  # noqa: E402
from fleet_analyser import alert  # noqa: E402
from fleet_analyser.store import JsonlStore, MemoryStore  # noqa: E402

ALERT_CLI = str(ROOT / "fleet" / "alert.py")


class FakeClock:
    def __init__(self, t=BASE + 1000.5):
        self.t = t

    def __call__(self):
        return self.t


def ep(robot, offset=0, **kw):
    kw.setdefault("cell", [3, 4])
    row = episode(robot=robot, start=BASE + offset, **kw)
    return row


def make(store=None, episodes=(), **kw):
    store = MemoryStore() if store is None else store
    store.insert("stuck_episodes", list(episodes))
    out = []
    a = alert.Alerter("r", clock=kw.pop("clock", FakeClock()), out=out.append, **kw)
    return store, a, out


class TestLine(unittest.TestCase):
    def test_line_format_with_both_blocker_suffixes_and_integer_seconds(self):
        # inject: print round() instead of int() seconds, drop either suffix, or print the faulted seconds as a float
        faulted = ep("A", cause="blocked_by_faulted", blocker="B", blocker_faulted_s=125.9, t_entry=BASE + 30.9)
        stuck = ep("C", 5, cause="blocked_by_stuck", blocker="D", blocker_faulted_s=None)
        plain = ep("E", 9, cause="unknown", resolution="open", end=None)
        self.assertEqual(alert.format_line(faulted), "A stuck at 3-4 for 30 s, blocked_by_faulted B (faulted 125 s)")
        self.assertEqual(alert.format_line(stuck), "C stuck at 3-4 for 30 s, blocked_by_stuck D")
        self.assertEqual(alert.format_line(plain), "E stuck at 3-4 for 30 s, unknown")
        self.assertEqual(alert.format_line(dict(faulted, t_entry=BASE + 31.99)), alert.format_line(faulted).replace(
            "for 30", "for 31"))

    def test_poll_prints_new_lines_in_t_entry_order_once_each(self):
        # inject: forget the alerted set (print an episode on every poll), or print in store order
        store, a, out = make(episodes=[ep("A", 100), ep("B", 0)], from_start=True)
        lines = a.poll_once(store)
        self.assertEqual(lines, ["B stuck at 3-4 for 30 s, unknown", "A stuck at 3-4 for 30 s, unknown"])
        self.assertEqual(a.poll_once(store), [])
        self.assertEqual(out, lines)


class TestWhatIsAlerted(unittest.TestCase):
    def test_open_and_closed_episodes_alert_but_censored_and_interrupted_never(self):
        # inject: alert left_censored rows, alert interrupted rows, or skip open rows
        rows = [ep("OPEN", 0, resolution="open", end=None), ep("MOVED", 1), ep("UNRES", 2, resolution="unresolved"),
                ep("DROP", 3, resolution="order_dropped"), ep("INT", 4, resolution="interrupted", end=None),
                ep("CENS", 5, left_censored=True), ep("CENSINT", 6, left_censored=True, resolution="interrupted"),
                ep("CENSOPEN", 7, left_censored=True, resolution="open", end=None)]
        store, a, out = make(episodes=rows, from_start=True)
        a.poll_once(store)
        self.assertEqual(sorted(line.split()[0] for line in out), ["DROP", "MOVED", "OPEN", "UNRES"])

    def test_an_open_episode_that_closes_is_not_alerted_twice(self):
        # inject: key the alerted set by (episode_id, resolution)
        store, a, out = make(episodes=[ep("A", resolution="open", end=None)], from_start=True)
        a.poll_once(store)
        store.upsert("stuck_episodes", ("run", "episode_id"), [ep("A", resolution="moved")])
        a.poll_once(store)
        self.assertEqual(len(out), 1)

    def test_episodes_present_at_startup_are_skipped_unless_from_start(self):
        # inject: ignore from_start (always skip, or never skip)
        store, a, out = make(episodes=[ep("OLD")])
        a.start(store)
        self.assertEqual(a.poll_once(store), [])
        store.insert("stuck_episodes", [ep("NEW", 10)])
        self.assertEqual(a.poll_once(store), ["NEW stuck at 3-4 for 30 s, unknown"])
        store2, b, out2 = make(episodes=[ep("OLD")], from_start=True)
        b.start(store2)
        self.assertEqual(b.poll_once(store2), ["OLD stuck at 3-4 for 30 s, unknown"])


class TestLatency(unittest.TestCase):
    def test_latency_lines_carry_both_latencies_and_the_meaningful_flag(self):
        # inject: measure latency from the wrong event time, or hard-code meaningful
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lat.jsonl"
            e = ep("A", 0)
            store, a, out = make(episodes=[e], from_start=True, latency_out=str(path))
            a.start(store)
            self.assertIn("meaningful: no", out[0])
            a.poll_once(store)
            rec = json.loads(path.read_text().splitlines()[0])
            self.assertEqual(set(rec), {"episode_id", "alert_wall", "latency_from_entry_s", "latency_from_start_s",
                                        "meaningful"})
            self.assertEqual((rec["episode_id"], rec["alert_wall"]), (e["episode_id"], BASE + 1000.5))
            self.assertEqual((rec["latency_from_entry_s"], rec["latency_from_start_s"]), (970.5, 1000.5))
            self.assertIs(rec["meaningful"], False)
            live = MemoryStore()
            live.insert("ingest_runs", [dict(run="r", emit_config={"t0_mode": "now", "rate": "realtime", "speed": 1.0})])
            live, b, out2 = make(live, episodes=[ep("B", 0)], from_start=True, latency_out=str(path))
            b.start(live)
            self.assertIn("meaningful: yes", out2[0])
            b.poll_once(live)
            self.assertIs(json.loads(path.read_text().splitlines()[1])["meaningful"], True)


class TestCli(unittest.TestCase):
    def test_once_from_start_prints_what_is_there_and_skips_it_without_the_flag(self):
        # inject: ignore --from-start in the CLI
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "st"
            store = JsonlStore(d)
            store.insert("stuck_episodes", [ep("A"), ep("CENS", 1, left_censored=True)])
            store.close()
            args = [sys.executable, ALERT_CLI, "--run", "r", "--store", f"jsonl:{d}", "--once"]
            full = subprocess.run(args + ["--from-start"], capture_output=True, text=True)
            self.assertEqual(full.returncode, 0, full.stderr)
            self.assertIn("A stuck at 3-4 for 30 s, unknown\n", full.stdout)
            self.assertNotIn("CENS", full.stdout)
            skipped = subprocess.run(args, capture_output=True, text=True)
            self.assertNotIn("stuck at", skipped.stdout)

    def test_watch_reopens_the_store_each_cycle_and_stops_on_the_event(self):
        # inject: poll a store opened once (a JsonlStore never sees rows appended by another process)
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "st"
            spec = f"jsonl:{d}"
            JsonlStore(d).close()
            sys.path.insert(0, str(ROOT / "fleet"))
            import alert as cli

            out = []
            a = alert.Alerter("r", clock=FakeClock(), out=out.append)
            stop, waits = threading.Event(), []

            def wait(s):
                waits.append(s)
                if len(waits) == 1:  # another process appends an episode between two polls
                    writer = JsonlStore(d)
                    writer.insert("stuck_episodes", [ep("LATE")])
                    writer.close()
                else:
                    stop.set()

            cli.watch(spec, "r", a, 2.0, wait, stop)
            self.assertEqual(waits, [2.0, 2.0])
            self.assertIn("LATE stuck at 3-4 for 30 s, unknown", out)


if __name__ == "__main__":
    unittest.main()

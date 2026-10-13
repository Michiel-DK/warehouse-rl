"""Tests for the decision grader (fleet_analyser/grade.py, fleet/grade.py): every verdict branch with scripted store rows,
idempotence, the due rule, unknown kinds, event-time `now` for --once. Each case names its red demonstration in an
`# inject:` comment. Unit tests, no Docker, none skipped."""
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

from fleet_analyser import decisions, grade  # noqa: E402
from fleet_analyser.store import JsonlStore, MemoryStore  # noqa: E402

GRADE_CLI = str(ROOT / "fleet" / "grade.py")
T0 = 1000  # episode start; t_entry = T0 + 30
NOW = 10_000_000


def episode(robot="A", resolution="moved", start=T0, end=T0 + 200, cause="unknown", blocker=None, **kw):
    row = dict(run="r", episode_id=f"{robot}@{start}", zone="0", robot=robot, order_id="o1", start=start,
               start_iso=f"iso-{robot}-{start}", t_entry=start + 30, cell=[0, 0], cause=cause, blocker=blocker,
               blocker_faulted_s=None, end=end, duration_s=None if end is None else end - start, resolution=resolution,
               avoidable=False, avoidable_s=None, left_censored=False)
    row.update(kw)
    return row


def tr(robot, ts, frm, to):
    return dict(run="r", zone="0", robot=robot, ts=ts, from_state=frm, to_state=to, cell=[0, 0], order_id="o1")


def decide(store, ep, kind="stuck_cause", grade_after=None, claim=None, **kw):
    claim = claim or dict(episode_id=ep["episode_id"], cause=ep["cause"], blocker=ep["blocker"])
    return decisions.record_decision(
        store, run="r", kind=kind, subject=ep["robot"], start_iso=ep["start_iso"], decided_at=ep["t_entry"], claim=claim,
        rationale="x", expected=None, grade_after=ep["t_entry"] + 3600 if grade_after is None else grade_after,
        recorded_at=1.0, **kw)[0]


def world(ep, other_eps=(), transitions=(), kind="stuck_cause", **kw):
    store = MemoryStore()
    store.insert("stuck_episodes", [ep, *other_eps])
    store.insert("transitions", list(transitions))
    did = decide(store, ep, kind=kind, **kw)
    return store, did


def graded(store, did):
    return {d["id"]: d for d in store.select("decisions")}[did]


def run_one(ep, **kw):
    store, did = world(ep, **kw)
    counts = grade.grade_run(store, "r", NOW)
    return graded(store, did), counts


class TestBlockedByFaulted(unittest.TestCase):
    EP = episode(cause="blocked_by_faulted", blocker="B")

    def test_confirmed_when_the_blocker_left_faulted_inside_the_window(self):
        # inject: never confirm (drop the confirmed branch)
        d, counts = run_one(self.EP, transitions=[tr("B", 500, "IDLE", "FAULTED"), tr("B", 1100, "FAULTED", "IDLE")])
        self.assertEqual((d["status"], d["verdict"], d["error"], d["graded_at"]), ("graded", "confirmed", None, NOW))
        self.assertEqual(d["outcome"], dict(resolution="moved", end=T0 + 200, blocker_state_at_end="IDLE",
                                            blocker_cleared_at=1100))
        self.assertEqual(counts["verdicts"], {"stuck_cause": {"confirmed": 1}})

    def test_a_clear_outside_the_window_does_not_confirm(self):
        # inject: drop the lower bound of the (t_entry, end] window when looking for the clear
        before = [tr("B", 500, "IDLE", "FAULTED"), tr("B", 1030, "FAULTED", "IDLE")]  # exactly at t_entry: not after it
        after = [tr("B", 500, "IDLE", "FAULTED"), tr("B", T0 + 201, "FAULTED", "IDLE")]
        for tx in (before, after):
            d, _ = run_one(self.EP, transitions=tx)
            self.assertNotEqual(d["verdict"], "confirmed")

    def test_refuted_when_moved_while_the_blocker_is_still_faulted(self):
        # inject: never refute (drop the refuted branch)
        d, _ = run_one(self.EP, transitions=[tr("B", 500, "IDLE", "FAULTED")])
        self.assertEqual(d["verdict"], "refuted")
        self.assertEqual(d["outcome"]["blocker_state_at_end"], "FAULTED")
        self.assertIsNone(d["outcome"]["blocker_cleared_at"])

    def test_inconclusive_otherwise(self):
        # inject: refute on resolution alone, or confirm without requiring resolution moved
        faulted = [tr("B", 500, "IDLE", "FAULTED")]
        cleared = [tr("B", 500, "IDLE", "FAULTED"), tr("B", 1100, "FAULTED", "IDLE")]
        d1, _ = run_one(episode(cause="blocked_by_faulted", blocker="B", resolution="order_dropped"), transitions=cleared)
        d2, _ = run_one(self.EP, transitions=[tr("B", 500, "IDLE", "MOVING")])  # never faulted: nothing to confirm
        d3, _ = run_one(episode(cause="blocked_by_faulted", blocker="B", resolution="unresolved"), transitions=faulted)
        d4, _ = run_one(self.EP, transitions=[])  # blocker without any transition
        for d in (d1, d2, d3, d4):
            self.assertEqual((d["verdict"], d["status"]), ("inconclusive", "graded"))


class TestBlockedByStuck(unittest.TestCase):
    EP = episode(cause="blocked_by_stuck", blocker="B")

    def blocker_ep(self, start, end, **kw):
        return episode(robot="B", start=start, end=end, **kw)

    def test_confirmed_when_the_blocker_episode_ended_first(self):
        # inject: compare with < instead of <= (an end at the same ts would then not confirm)
        for b_end in (T0 + 150, T0 + 200):
            d, _ = run_one(self.EP, other_eps=[self.blocker_ep(T0 - 100, b_end)])
            self.assertEqual(d["verdict"], "confirmed", b_end)
            self.assertEqual(d["outcome"]["blocker_cleared_at"], b_end)

    def test_refuted_when_the_blocker_episode_outlasted_this_one(self):
        # inject: swap confirmed and refuted
        d, _ = run_one(self.EP, other_eps=[self.blocker_ep(T0 - 100, T0 + 260)])
        self.assertEqual(d["verdict"], "refuted")

    def test_inconclusive_without_a_containing_blocker_episode_or_when_not_moved(self):
        # inject: take any blocker episode, whatever its interval
        far = self.blocker_ep(T0 + 5000, T0 + 5100)  # does not contain t_entry
        d1, _ = run_one(self.EP, other_eps=[far])
        d2, _ = run_one(episode(cause="blocked_by_stuck", blocker="B", resolution="unresolved"),
                        other_eps=[self.blocker_ep(T0 - 100, T0 + 150)])
        d3, _ = run_one(self.EP, other_eps=[self.blocker_ep(T0 - 100, None, resolution="open")])
        d4, _ = run_one(self.EP)  # the blocker has no episode at all
        for d in (d1, d2, d3, d4):
            self.assertEqual(d["verdict"], "inconclusive")


class TestOtherCauses(unittest.TestCase):
    def test_faulted_self_confirmed_only_by_fault_cleared(self):
        # inject: confirm on resolution moved too
        d, _ = run_one(episode(cause="faulted_self", resolution="fault_cleared"))
        self.assertEqual(d["verdict"], "confirmed")
        for res in ("moved", "unresolved", "order_dropped"):
            d, _ = run_one(episode(cause="faulted_self", resolution=res))
            self.assertEqual(d["verdict"], "inconclusive", res)

    def test_traffic_and_unknown_are_inconclusive(self):
        # inject: grade traffic as confirmed when the robot moved
        for cause in ("traffic", "unknown"):
            d, _ = run_one(episode(cause=cause, resolution="moved"))
            self.assertEqual((d["verdict"], d["status"], d["error"]), ("inconclusive", "graded", None), cause)
            self.assertEqual(set(d["outcome"]), {"resolution", "end", "blocker_state_at_end", "blocker_cleared_at"})

    def test_interrupted_left_censored_and_missing_episodes_are_inconclusive(self):
        # inject: drop the censored/interrupted/missing guard (the moved + cleared case below would then confirm)
        tx = [tr("B", 500, "IDLE", "FAULTED"), tr("B", 1100, "FAULTED", "IDLE")]
        base = dict(cause="blocked_by_faulted", blocker="B")
        d1, _ = run_one(episode(resolution="interrupted", end=None, **base), transitions=tx)
        d2, _ = run_one(episode(left_censored=True, **base), transitions=tx)
        self.assertEqual((d1["verdict"], d2["verdict"]), ("inconclusive", "inconclusive"))
        self.assertEqual(d1["outcome"]["resolution"], "interrupted")
        store = MemoryStore()  # the decision names an episode that is not in the store
        ghost = episode(**base)
        decide(store, ghost)
        counts = grade.grade_run(store, "r", NOW)
        self.assertEqual((counts["stamped"], store.select("decisions")[0]["verdict"]), (1, "inconclusive"))
        self.assertEqual(store.select("decisions")[0]["outcome"]["resolution"], None)

    def test_avoidable_reset_records_whether_a_reset_happened(self):
        # inject: set reset = resolution == "moved"
        for res, verdict, reset in (("order_dropped", "reset_happened", True), ("moved", "no_reset", False)):
            ep = episode(cause="blocked_by_faulted", blocker="B", resolution=res)
            d, _ = run_one(ep, kind="avoidable_reset")
            self.assertEqual((d["verdict"], d["error"], d["status"]), (verdict, None, "graded"), res)
            self.assertEqual(d["outcome"], dict(resolution=res, reset=reset))
        d, _ = run_one(episode(resolution="interrupted", end=None), kind="avoidable_reset")
        self.assertEqual(d["verdict"], "inconclusive")


class TestDueRuleAndWrites(unittest.TestCase):
    def test_second_run_stamps_nothing_and_changes_nothing(self):
        # inject: drop the status == open filter and count a refused stamp as stamped
        store, did = world(episode(cause="faulted_self", resolution="fault_cleared"))
        first = grade.grade_run(store, "r", NOW)
        before = store.select("decisions")
        second = grade.grade_run(store, "r", NOW + 5)
        self.assertEqual((first["stamped"], second["stamped"]), (1, 0))
        self.assertEqual(store.select("decisions"), before)

    def test_grades_are_written_only_through_stamp_grade(self):
        # inject: write the grade with store.update_where directly instead of decisions.stamp_grade
        store, did = world(episode(cause="faulted_self", resolution="fault_cleared"))
        with mock.patch.object(decisions, "stamp_grade", wraps=decisions.stamp_grade) as spy:
            grade.grade_run(store, "r", NOW)
        self.assertEqual(spy.call_count, 1)
        self.assertEqual(spy.call_args.args[1], did)

    def test_unknown_kind_stays_open_and_is_counted(self):
        # inject: grade every kind (drop the decisions.KINDS check)
        ep = episode(cause="unknown")
        store, did = world(ep, kind="hotspot_forecast")
        counts = grade.grade_run(store, "r", NOW)
        d = graded(store, did)
        self.assertEqual((d["status"], d["verdict"], d["outcome"], d["graded_at"]), ("open", None, None, None))
        self.assertEqual((counts["stamped"], counts["skipped_kind"]), (0, 1))

    def test_not_due_until_terminal_or_grade_after(self):
        # inject: grade every open decision at once (ignore due-ness)
        ep = episode(cause="unknown", resolution="open", end=None)
        store, did = world(ep, grade_after=5000)
        counts = grade.grade_run(store, "r", 4999)
        self.assertEqual((counts["stamped"], counts["not_due"], graded(store, did)["status"]), (0, 1, "open"))
        counts = grade.grade_run(store, "r", 5000)
        d = graded(store, did)
        self.assertEqual((counts["stamped"], d["verdict"], d["graded_at"], d["outcome"]["resolution"]),
                         (1, "inconclusive", 5000, "open"))

    def test_terminal_episode_is_due_before_grade_after(self):
        # inject: require grade_after <= now even for a terminal episode
        store, did = world(episode(cause="faulted_self", resolution="fault_cleared"), grade_after=NOW * 2)
        self.assertEqual(grade.grade_run(store, "r", 1)["stamped"], 1)

    def test_other_runs_decisions_are_untouched(self):
        # inject: drop the run filter on decisions
        ep = episode(cause="faulted_self", resolution="fault_cleared")
        store, did = world(ep)
        counts = grade.grade_run(store, "other", NOW)
        self.assertEqual((counts["stamped"], graded(store, did)["status"]), (0, "open"))


class TestOnceUsesEventTime(unittest.TestCase):
    def test_once_uses_the_latest_transition_ts_as_now(self):
        # inject: use time.time() as now in batch mode (a ts in 2096 is in the wall clock's future)
        far = 4_000_000_000
        ep = episode(cause="unknown", resolution="open", end=None, start=far, episode_id="A@far")
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonlStore(Path(tmp) / "st")
            store.insert("stuck_episodes", [ep])
            store.insert("transitions", [tr("A", far + 3600, "STUCK", "STUCK"), tr("A", far + 10, "NONE", "MOVING")])
            decide(store, ep)  # grade_after = t_entry + 3600 = far + 3630
            self.assertEqual(grade.batch_now(store, "r"), far + 3600)
            store.close()
            r = subprocess.run([sys.executable, GRADE_CLI, "--run", "r", "--store", f"jsonl:{Path(tmp) / 'st'}", "--once"],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("stamped 0, not due 1", r.stdout)  # far + 3600 < far + 3630
            store = JsonlStore(Path(tmp) / "st")
            store.insert("transitions", [tr("A", far + 3700, "STUCK", "STUCK")])
            store.close()
            r = subprocess.run([sys.executable, GRADE_CLI, "--run", "r", "--store", f"jsonl:{Path(tmp) / 'st'}", "--once"],
                               capture_output=True, text=True)
            self.assertIn("stamped 1", r.stdout)
            self.assertIn("inconclusive 1", r.stdout)
            store = JsonlStore(Path(tmp) / "st")
            d = store.select("decisions")[0]
            self.assertEqual((d["status"], d["graded_at"]), ("graded", far + 3700))
            store.close()
            r = subprocess.run([sys.executable, GRADE_CLI, "--run", "r", "--store", f"jsonl:{Path(tmp) / 'st'}"],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 2)  # one of --once / --every is required

    def test_every_mode_uses_the_clock_and_reopens_the_store(self):
        # inject: pass the batch now (max transition ts, 0 here) in the live loop instead of the clock
        sys.path.insert(0, str(ROOT / "fleet"))
        import grade as cli

        far = 4_000_000_000
        ep = episode(cause="unknown", resolution="open", end=None, start=far, episode_id="A@far")
        with tempfile.TemporaryDirectory() as tmp:
            spec = f"jsonl:{Path(tmp) / 'st'}"
            store = JsonlStore(Path(tmp) / "st")
            store.insert("stuck_episodes", [ep])
            decide(store, ep)
            store.close()
            stop, waits, out = threading.Event(), [], []
            cli.live(spec, "r", 5, lambda: far + 3630, lambda s: (waits.append(s), stop.set()), stop, out=out.append)
            self.assertEqual(waits, [5])
            self.assertIn("stamped 1", out[0])
            reopened = JsonlStore(Path(tmp) / "st")
            self.assertEqual(reopened.select("decisions")[0]["graded_at"], far + 3630)
            reopened.close()


if __name__ == "__main__":
    unittest.main()

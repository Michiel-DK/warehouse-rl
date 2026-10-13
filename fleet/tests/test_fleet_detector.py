"""Scripted tests for fleet_analyser.detector (hand-built Messages, no env): one per cause, one per resolution, the
stuck_after threshold, the transition sequence, avoidable, precedence, and that the detector never touches `custom`.
Each case names its red demonstration in an `# inject:` comment. One step = 5 s; stuck_after is 30 s."""
import inspect
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "fleet") not in sys.path:
    sys.path.insert(0, str(ROOT / "fleet"))

from fleet_analyser import detector as detector_mod  # noqa: E402
from fleet_analyser.detector import Detector  # noqa: E402
from fleet_analyser.parse import Message  # noqa: E402

BASE = 1767225600  # 2026-01-01T00:00:00Z


def M(serial, step, order="o1", driving=False, faulted=False, x=0, y=0, zone="0"):
    return Message(serial=serial, zone=zone, header_id=step, ts=BASE + 5 * step, order_id=order, x=x, y=y,
                   driving=driving, faulted=faulted, loaded=False, raw_len=1)


def run(msgs, stuck_after=30, end=True):
    """Feed messages in time order (stable within a timestamp); returns (events, detector)."""
    d = Detector(stuck_after)
    ev = []
    for m in sorted(msgs, key=lambda m: m.ts):
        ev.extend(d.feed(m))
    if end:
        ev.extend(d.end_all())
    return ev, d


def episodes(events):
    """Final row per episode_id (close replaces open)."""
    out = {}
    for e in events:
        if e["kind"] in ("episode_open", "episode_close"):
            out[e["episode_id"]] = e
    return out


def stopped(serial, first, last, **kw):
    return [M(serial, s, **kw) for s in range(first, last + 1)]


def only_episode(events):
    eps = episodes(events)
    assert len(eps) == 1, eps
    return next(iter(eps.values()))


class TestCauses(unittest.TestCase):
    def test_cause_faulted_self(self):
        # inject: drop the faulted_self rule (the episode then falls through to unknown) or test it after traffic
        msgs = stopped("Z0-00", 0, 8, faulted=True) + [M("Z0-00", 9, driving=True, x=1)]
        ep = only_episode(run(msgs)[0])
        self.assertEqual(ep["cause"], "faulted_self")
        self.assertIsNone(ep["blocker"])
        self.assertEqual(ep["t_entry"], BASE + 30)

    def test_cause_blocked_by_faulted_with_blocker_and_streak(self):
        # inject: report T_entry minus the episode start as blocker_faulted_s, or pick the highest serial as blocker
        a = stopped("Z0-00", 0, 11)  # robot A at (0,0), neighbours at distance 1
        a.append(M("Z0-00", 12, driving=True, x=0, y=3))
        b = [M("Z0-03", s, order="", faulted=(2 <= s <= 14), x=1, y=0) for s in range(0, 14)]  # faulted since step 2
        c = [M("Z0-02", s, order="", faulted=(4 <= s <= 14), x=0, y=1) for s in range(0, 14)]  # also adjacent
        ep = [e for e in episodes(run(a + b + c)[0]).values() if e["robot"] == "Z0-00"][0]
        self.assertEqual(ep["cause"], "blocked_by_faulted")
        self.assertEqual(ep["blocker"], "Z0-02")  # lowest serial among faulted neighbours
        self.assertEqual(ep["blocker_faulted_s"], 5 * (6 - 4))  # T_entry is step 6, its streak began at step 4

    def test_cause_blocked_by_stuck(self):
        # inject: decide causes before the batch's STUCK states are known (the first robot then sees traffic)
        a = stopped("Z0-00", 0, 8, x=0, y=0) + [M("Z0-00", 9, driving=True, x=0, y=5)]
        b = stopped("Z0-01", 0, 8, x=1, y=0) + [M("Z0-01", 9, driving=True, x=1, y=5)]
        eps = episodes(run(a + b)[0])
        self.assertEqual(eps["Z0-00@2026-01-01T00:00:00Z"]["cause"], "blocked_by_stuck")
        self.assertEqual(eps["Z0-00@2026-01-01T00:00:00Z"]["blocker"], "Z0-01")
        self.assertEqual(eps["Z0-01@2026-01-01T00:00:00Z"]["cause"], "blocked_by_stuck")
        self.assertEqual(eps["Z0-01@2026-01-01T00:00:00Z"]["blocker"], "Z0-00")

    def test_cause_traffic(self):
        # inject: drop the traffic rule (a moving neighbour then reads as unknown)
        a = stopped("Z0-00", 0, 8) + [M("Z0-00", 9, driving=True, x=0, y=4)]
        b = [M("Z0-01", s, driving=True, x=1, y=0) for s in range(0, 10)]
        ep = only_episode(run(a + b)[0])
        self.assertEqual(ep["cause"], "traffic")
        self.assertIsNone(ep["blocker"])

    def test_cause_unknown(self):
        # inject: count a robot at Manhattan distance 2 (or in another zone) as a neighbour
        a = stopped("Z0-00", 0, 8) + [M("Z0-00", 9, driving=True, x=0, y=4)]
        far = [M("Z0-01", s, driving=True, x=1, y=1) for s in range(0, 10)]  # distance 2
        other_zone = [M("Z1-00", s, zone="1", order="", faulted=True, x=0, y=1) for s in range(0, 10)]
        ep = [e for e in episodes(run(a + far + other_zone)[0]).values() if e["robot"] == "Z0-00"][0]
        self.assertEqual(ep["cause"], "unknown")

    def test_cause_precedence_faulted_self_beats_neighbours(self):
        # inject: test blocked_by_faulted before faulted_self
        a = stopped("Z0-00", 0, 8, faulted=True)
        b = [M("Z0-01", s, order="", faulted=True, x=1) for s in range(0, 9)]
        ep = [e for e in episodes(run(a + b)[0]).values() if e["robot"] == "Z0-00"][0]
        self.assertEqual(ep["cause"], "faulted_self")

    def test_cause_is_decided_once_at_t_entry(self):
        # inject: re-decide the cause at close (a blocker that appears later would change the answer)
        a = stopped("Z0-00", 0, 12) + [M("Z0-00", 13, driving=True, x=0, y=4)]
        late_blocker = [M("Z0-01", s, order="", faulted=(s >= 8), x=1) for s in range(0, 13)]
        ep = only_episode([e for e in run(a + late_blocker)[0] if e.get("robot") == "Z0-00"])
        self.assertEqual(ep["cause"], "traffic")  # healthy neighbour at T_entry; its later fault changes nothing


class TestResolutions(unittest.TestCase):
    def test_resolution_moved(self):
        # inject: return fault_cleared/unresolved for a plain drive-off
        msgs = stopped("Z0-00", 0, 8) + [M("Z0-00", 9, driving=True, x=0, y=3)]
        ep = only_episode(run(msgs)[0])
        self.assertEqual(ep["resolution"], "moved")
        self.assertEqual(ep["end"], BASE + 45)
        self.assertEqual(ep["duration_s"], 45)
        self.assertEqual(ep["start"], BASE)
        self.assertEqual(ep["episode_id"], "Z0-00@2026-01-01T00:00:00Z")
        self.assertEqual(ep["cell"], [0, 0])

    def test_resolution_order_dropped_to_empty_order(self):
        # inject: check fault_cleared or moved before order_dropped
        msgs = stopped("Z0-00", 0, 8) + [M("Z0-00", 9, order=""), M("Z0-00", 10, order="")]
        ev, _ = run(msgs)
        self.assertEqual(only_episode(ev)["resolution"], "order_dropped")
        tr = [(e["ts"] - BASE, e["from_state"], e["to_state"]) for e in ev if e["kind"] == "transition"]
        self.assertIn((45, "STUCK", "RECOVERED"), tr)  # the ending message is RECOVERED, not IDLE
        self.assertIn((50, "RECOVERED", "IDLE"), tr)

    def test_resolution_order_dropped_to_other_order_wins_over_fault(self):
        # inject: let fault_cleared (last run message faulted) win over order_dropped
        msgs = stopped("Z0-00", 0, 7) + [M("Z0-00", 8, faulted=True), M("Z0-00", 9, order="o2", driving=False)]
        ev, _ = run(msgs)
        self.assertEqual(only_episode(ev)["resolution"], "order_dropped")

    def test_resolution_fault_cleared(self):
        # inject: ignore the robot's own last-run-message fault (the episode then reads as moved)
        msgs = stopped("Z0-00", 0, 7) + [M("Z0-00", 8, faulted=True), M("Z0-00", 9, driving=True, x=0, y=2)]
        ep = only_episode(run(msgs)[0])
        self.assertEqual(ep["resolution"], "fault_cleared")

    def test_resolution_unresolved_at_end_of_input(self):
        # inject: leave the episode open (resolution "open") or end it at the batch time instead of the last ts
        msgs = stopped("Z0-00", 0, 10)
        ev, _ = run(msgs)
        ep = only_episode(ev)
        self.assertEqual(ep["resolution"], "unresolved")
        self.assertEqual(ep["end"], BASE + 50)
        self.assertEqual(ep["duration_s"], 50)
        self.assertFalse(ep["avoidable"])
        self.assertEqual(ev[-1]["kind"], "episode_close")

    def test_open_episode_is_reported_at_t_entry_with_resolution_open(self):
        # inject: emit the episode only at close
        ev, _ = run(stopped("Z0-00", 0, 8), end=False)
        opens = [e for e in ev if e["kind"] == "episode_open"]
        self.assertEqual(len(opens), 1)
        self.assertEqual(opens[0]["resolution"], "open")
        self.assertEqual(opens[0]["t_entry"], BASE + 30)

    def test_threshold_is_stuck_after_exactly(self):
        # inject: use > instead of >= for ts - since against stuck_after (or count the ending message as run time)
        short = stopped("Z0-00", 0, 5) + [M("Z0-00", 6, driving=True, x=0, y=3)]  # stopped 25 s = stuck_after - 5
        self.assertEqual(episodes(run(short)[0]), {})
        exact = stopped("Z0-00", 0, 6) + [M("Z0-00", 7, driving=True, x=0, y=3)]  # stopped 30 s
        ep = only_episode(run(exact)[0])
        self.assertEqual((ep["t_entry"], ep["end"]), (BASE + 30, BASE + 35))
        ep60 = only_episode(run(stopped("Z0-00", 0, 3), stuck_after=15)[0])  # the parameter is honoured
        self.assertEqual(ep60["t_entry"], BASE + 15)


class TestStatesAndAvoidable(unittest.TestCase):
    def test_transition_sequence_for_one_robot(self):
        # inject: skip the NONE first row, drop RECOVERED, or hold RECOVERED for two messages
        msgs = [M("Z0-00", 0, driving=True, x=0), M("Z0-00", 1, driving=True, x=1)]  # MOVING
        msgs += stopped("Z0-00", 2, 8, x=1)  # STOPPED_WITH_ORDER from step 2; STUCK once 30 s have passed (step 8)
        msgs += [M("Z0-00", 9, driving=True, x=2), M("Z0-00", 10, driving=True, x=3)]  # RECOVERED, MOVING
        msgs += [M("Z0-00", 11, order="", x=3), M("Z0-00", 12, order="", faulted=True, x=3)]  # IDLE, FAULTED
        ev, _ = run(msgs)
        tr = [(e["ts"] - BASE, e["from_state"], e["to_state"]) for e in ev if e["kind"] == "transition"]
        self.assertEqual(tr, [(0, "NONE", "MOVING"), (10, "MOVING", "STOPPED_WITH_ORDER"),
                              (40, "STOPPED_WITH_ORDER", "STUCK"), (45, "STUCK", "RECOVERED"),
                              (50, "RECOVERED", "MOVING"), (55, "MOVING", "IDLE"), (60, "IDLE", "FAULTED")])

    def test_state_precedence(self):
        # inject: put IDLE or MOVING above FAULTED, or STUCK above MOVING
        def states(msgs):
            return [(e["ts"] - BASE, e["to_state"]) for e in run(msgs)[0] if e["kind"] == "transition"]

        self.assertEqual(states([M("A-1", 0, order="", faulted=True)]), [(0, "FAULTED")])
        self.assertEqual(states([M("A-1", 0, order="", driving=True)]), [(0, "IDLE")])
        self.assertEqual(states([M("A-1", 0, driving=True)]), [(0, "MOVING")])
        self.assertEqual(states([M("A-1", 0)]), [(0, "STOPPED_WITH_ORDER")])

    def test_fault_inside_a_run_does_not_stop_the_clock(self):
        # inject: restart the stopped run at a faulted message
        msgs = [M("Z0-00", 0), M("Z0-00", 1, faulted=True), M("Z0-00", 2, faulted=True), M("Z0-00", 3),
                M("Z0-00", 4), M("Z0-00", 5), M("Z0-00", 6)]
        ep = only_episode(run(msgs)[0])
        self.assertEqual(ep["start"], BASE)
        self.assertEqual(ep["t_entry"], BASE + 30)

    def test_driving_with_same_order_ends_run_and_next_run_restarts_the_clock(self):
        # inject: keep `since` across a driving message
        msgs = stopped("Z0-00", 0, 4) + [M("Z0-00", 5, driving=True, x=1)] + stopped("Z0-00", 6, 10, x=1)
        self.assertEqual(episodes(run(msgs)[0]), {})

    def test_avoidable_true_for_closed_blocked_by_faulted(self):
        # inject: compute avoidable_s as duration_s (not minus stuck_after) or require cause != blocked_by_faulted
        # (the duration clause is always true for a closed episode at 5 s steps; the SCOPE note says so)
        a = stopped("Z0-00", 0, 10) + [M("Z0-00", 11, driving=True, x=0, y=4)]
        b = [M("Z0-01", s, order="", faulted=(s >= 1), x=1) for s in range(0, 12)]
        ep = [e for e in episodes(run(a + b)[0]).values() if e["robot"] == "Z0-00"][0]
        self.assertEqual((ep["cause"], ep["resolution"], ep["duration_s"]), ("blocked_by_faulted", "moved", 55))
        self.assertTrue(ep["avoidable"])
        self.assertEqual(ep["avoidable_s"], 25)  # duration - stuck_after

    def test_avoidable_false_cases(self):
        # inject: mark every episode avoidable, or avoidable regardless of resolution
        b = [M("Z0-01", s, order="", faulted=True, x=1) for s in range(0, 12)]
        unresolved = [e for e in episodes(run(stopped("Z0-00", 0, 10) + b)[0]).values() if e["robot"] == "Z0-00"][0]
        self.assertEqual((unresolved["cause"], unresolved["resolution"]), ("blocked_by_faulted", "unresolved"))
        self.assertFalse(unresolved["avoidable"])
        self.assertIsNone(unresolved["avoidable_s"])
        other = only_episode(run(stopped("Z0-00", 0, 8) + [M("Z0-00", 9, driving=True, x=0, y=4)])[0])
        self.assertEqual(other["cause"], "unknown")
        self.assertFalse(other["avoidable"])

    def test_late_message_for_a_robot_is_skipped(self):
        # inject: process messages whose ts does not move forward for that robot
        msgs = stopped("Z0-00", 0, 3) + [M("Z0-00", 2, driving=True)] + stopped("Z0-00", 4, 8)
        ev, _ = run(msgs)
        self.assertEqual(only_episode(ev)["start"], BASE)

    def test_detector_source_never_touches_custom(self):
        # inject: read msg.custom (or a custom-derived name) anywhere in detector.py code
        code = "\n".join(line for line in inspect.getsource(detector_mod).splitlines()
                         if not line.lstrip().startswith("#"))
        body = code.split('"""', 2)[2]  # drop the module docstring, which names the rule
        for word in ("custom", "stuck_count", "stuck_event", "clash_event", "recovery_action", "carrying"):
            self.assertNotIn(word, body)


if __name__ == "__main__":
    unittest.main()

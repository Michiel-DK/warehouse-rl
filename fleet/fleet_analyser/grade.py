"""Decision grader: reads the store tables only (decisions, stuck_episodes, transitions) and stamps grades through
decisions.stamp_grade, never anywhere else. The simulator ground-truth block is not in the store and is never read here.

grade_run(store, run, now) -> counts. `now` is event time in batch mode (the run's max transition ts) and the wall clock
in live mode; graded_at is `now`. A decision is due when it is open and its episode has a terminal resolution
(moved, order_dropped, fault_cleared, unresolved) or has been interrupted, or grade_after <= now. A due decision whose
episode is missing, left_censored or interrupted grades inconclusive. Verdict rules: docs/SCOPE.md "S5C1".
Kinds outside decisions.KINDS are left open and counted as skipped_kind.
"""
import json

from . import decisions

TERMINAL = ("moved", "order_dropped", "fault_cleared", "unresolved")
FAULTED = "FAULTED"


def batch_now(store, run):
    """Event time of a finished run: the latest transition ts (0 when there is none)."""
    return max((t["ts"] for t in store.select("transitions", {"run": run})), default=0)


class _View:
    """The run's episodes and transitions, indexed once per grade_run call."""

    def __init__(self, store, run):
        self.episodes = {}
        self.by_robot = {}
        for e in store.select("stuck_episodes", {"run": run}):
            self.episodes[e["episode_id"]] = e
            self.by_robot.setdefault(e["robot"], []).append(e)
        self.trans = {}
        for t in store.select("transitions", {"run": run}):
            self.trans.setdefault(t["robot"], []).append(t)
        for rows in self.trans.values():
            rows.sort(key=lambda t: t["ts"])

    def state_at(self, robot, ts):
        """The robot's latest transition at or before ts: its state then, or None."""
        state = None
        for t in self.trans.get(robot, ()):
            if t["ts"] <= ts:
                state = t["to_state"]
        return state

    def faulted_cleared(self, robot, after, upto):
        """ts of the first transition out of FAULTED in (after, upto], or None."""
        for t in self.trans.get(robot, ()):
            if after < t["ts"] <= upto and t["from_state"] == FAULTED and t["to_state"] != FAULTED:
                return t["ts"]
        return None


def _outcome(ep, state=None, cleared=None):
    return dict(resolution=ep["resolution"] if ep else None, end=ep.get("end") if ep else None,
                blocker_state_at_end=state, blocker_cleared_at=cleared)


def _stuck_cause(claim, ep, view):
    if ep is None or ep.get("left_censored") or ep["resolution"] == "interrupted":
        return "inconclusive", _outcome(ep)
    cause, blocker, end = claim.get("cause"), claim.get("blocker"), ep.get("end")
    moved = ep["resolution"] == "moved" and end is not None
    if cause == "blocked_by_faulted" and blocker and end is not None:
        state = view.state_at(blocker, end)
        cleared = view.faulted_cleared(blocker, ep["t_entry"], end)
        verdict = "inconclusive"
        if moved and cleared is not None:
            verdict = "confirmed"
        elif moved and state == FAULTED:
            verdict = "refuted"
        return verdict, _outcome(ep, state, cleared)
    if cause == "blocked_by_stuck" and blocker and end is not None:
        state = view.state_at(blocker, end)
        theirs = sorted((b for b in view.by_robot.get(blocker, ())
                         if b.get("end") is not None and b["start"] <= ep["t_entry"] <= b["end"]),
                        key=lambda b: (b["start"], b["episode_id"]))
        if not (moved and theirs):
            return "inconclusive", _outcome(ep, state)
        b_end = theirs[0]["end"]
        return ("confirmed" if b_end <= end else "refuted"), _outcome(ep, state, b_end)
    if cause == "faulted_self":
        return ("confirmed" if ep["resolution"] == "fault_cleared" else "inconclusive"), _outcome(ep)
    return "inconclusive", _outcome(ep)  # traffic, unknown, or a blocker the claim does not name


def _avoidable_reset(claim, ep, view):
    if ep is None or ep.get("left_censored") or ep["resolution"] == "interrupted":
        return "inconclusive", dict(resolution=ep["resolution"] if ep else None, reset=None)
    reset = ep["resolution"] == "order_dropped"  # the only reset visible in public data
    return ("reset_happened" if reset else "no_reset"), dict(resolution=ep["resolution"], reset=reset)


GRADERS = {"stuck_cause": _stuck_cause, "avoidable_reset": _avoidable_reset}


def grade_run(store, run, now):
    """Grade every due, open decision of the run. Returns {"stamped", "skipped_kind", "not_due", "verdicts"} with
    verdicts = {kind: {verdict: n}} for the grades written by this call."""
    view = _View(store, run)
    counts = dict(stamped=0, skipped_kind=0, not_due=0, verdicts={})
    for d in store.select("decisions"):
        if d["run"] != run or d["status"] != "open":
            continue
        if d["kind"] not in decisions.KINDS:
            counts["skipped_kind"] += 1
            continue
        try:
            claim = json.loads(d["claim"])
        except ValueError:
            claim = {}
        ep = view.episodes.get(claim.get("episode_id"))
        done = ep is not None and (ep["resolution"] in TERMINAL or ep["resolution"] == "interrupted")
        if not (done or d["grade_after"] <= now):
            counts["not_due"] += 1
            continue
        verdict, outcome = GRADERS[d["kind"]](claim, ep, view)
        if decisions.stamp_grade(store, d["id"], outcome, None, verdict, now):
            counts["stamped"] += 1
            kind_counts = counts["verdicts"].setdefault(d["kind"], {})
            kind_counts[verdict] = kind_counts.get(verdict, 0) + 1
    return counts

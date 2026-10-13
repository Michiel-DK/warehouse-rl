"""Append-only decision ledger (modelled on restaurant-brain BrainDecision): first write wins, grading fields stamped once.

dedup_key = "<kind>:<subject>:<episode start ISO>" uses EVENT time, not wall time: a flat-out replay decides thousands of
episodes per wall minute, so wall-time keys would collide and a re-run of the same files would not be a no-op.
The grader is S5C's; this module provides record_decision and stamp_grade.
"""
import hashlib
import json
import time

KINDS = ("stuck_cause", "avoidable_reset")
GRADE_FIELDS = ("status", "outcome", "error", "verdict", "graded_at")
CLAIM_VERSION = 1
GRADE_AFTER_S = 3600


def dedup_key(kind, subject, start_iso):
    return f"{kind}:{subject}:{start_iso}"


def decision_id(key):
    return hashlib.sha1(key.encode()).hexdigest()


def record_decision(store, *, run, kind, subject, start_iso, decided_at, claim, rationale, expected, grade_after,
                    recorded_at=None):
    """Insert the decision unless one with the same dedup_key exists. Returns (id, created)."""
    key = dedup_key(kind, subject, start_iso)
    did = decision_id(key)
    if store.exists("decisions", dedup_key=key):
        return did, False
    store.insert("decisions", [dict(
        id=did, run=run, decided_at=decided_at, recorded_at=time.time() if recorded_at is None else recorded_at,
        kind=kind, subject=subject, claim=json.dumps(claim, sort_keys=True, separators=(",", ":")),
        claim_version=CLAIM_VERSION, rationale=rationale, expected=expected, grade_after=grade_after, status="open",
        outcome=None, graded_at=None, error=None, verdict=None, dedup_key=key)])
    return did, True


def stamp_grade(store, decision_id_, outcome, error, verdict, graded_at):
    """Set outcome / error / verdict / graded_at and status "graded", only if the decision is still open. A second
    stamp is refused (False) and changes nothing. No other field is ever modified."""
    n = store.update_where("decisions", {"id": decision_id_, "status": "open"},
                           dict(status="graded", outcome=outcome, error=error, verdict=verdict, graded_at=graded_at))
    return n > 0

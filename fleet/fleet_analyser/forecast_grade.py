"""Outcome grader for hotspot_forecast decisions: reads the store tables only (decisions, stalls, costmap, ingest_runs).
The other grade source of forecast_grades is written by fleet/grade.py, not here.

For each open forecast published at P with claim horizon H: graded iff H >= min_horizon_s and stream_end[zone] >= P + H, i.e.
only on a fully observed window; otherwise it stays open (no forecast_grades row, no stamp). Observed = stalls of that
zone and cell (hotspot.counted: no faulted-episode stalls, no next_occupied stalls unless exclude_occupied is False)
with start in [P, P + H); expected = claimed stalls per hour * H / 3600; verdict "ok" iff
|observed - expected| <= tolerance * max(expected, 1), else "off". horizon_s in the row is H, graded_at is stream_end[zone].
Order of writes: the forecast_grades row (grade_source "outcome") first, then decisions.stamp_grade. A crash between the
two leaves the decision open and the row present; a re-run finds the row, skips it and stamps the decision.
Stream end (event time) is PER ZONE: the ts of the last message the ingester ACCEPTED from that zone (zone = msg.zone,
never the file path or Kafka partition; passed parse and the sequence check, rejects and duplicates never move it):
max over the run's ingest_checkpoints rows of last_message_ts_by_zone[zone], None when no row has the zone (then that
zone's forecasts stay open). Zones are independent episodes with independent clocks. It does not depend on stalls, costmap publishes, transitions or the emit
ledger's planned end. graded_at is the stream end at the grading call, window_end is P + H; they differ on a late grade.
Accepted consequence of that definition: stalls are written by costmap.py from the files, not by ingest, so a grade cycle
run after ingest but before costmap has caught up counts stalls not yet extracted. The required order is
ingest -> costmap -> grade.
"""
import json

from . import decisions, hotspot

DEFAULT_MIN_HORIZON_S = 600
DEFAULT_TOLERANCE = 0.5
KEY = ("id", "grade_source")


def stream_end(store, run, zone):
    """Event-time ts of the last message the ingester accepted from `zone` (msg.zone), None when it accepted none."""
    seen = []
    for r in store.select("ingest_checkpoints", {"run": run}):
        ts = json.loads(r.get("last_message_ts_by_zone") or "{}").get(zone)
        if ts is not None:
            seen.append(ts)
    return max(seen) if seen else None


def split_subject(subject):
    """'Z0:3,4' -> ('0', '3,4')."""
    zone, _, cell = subject.partition(":")
    return zone[1:], cell


def forecasts(store, run):
    return store.select("decisions", {"run": run, "kind": "hotspot_forecast"})


def write_once(store, row):
    """Insert a forecast_grades row unless its (id, grade_source) exists. True iff a row was written."""
    if store.exists("forecast_grades", id=row["id"], grade_source=row["grade_source"]):
        return False
    store.upsert("forecast_grades", KEY, [row])
    return True


def grade_outcomes(store, run, min_horizon_s=DEFAULT_MIN_HORIZON_S, tolerance=DEFAULT_TOLERANCE,
                   exclude_occupied=True):
    """Returns dict(graded, open)."""
    ends = {}  # zone -> stream_end, read once per call
    by_cell = {}
    for s in store.select("stalls", {"run": run}):
        if hotspot.counted(s, exclude_occupied):
            by_cell.setdefault((s["zone"], s["cell"]), []).append(s["start"])
    graded = still_open = 0
    for d in forecasts(store, run):
        if d["status"] != "open":
            continue
        claim = json.loads(d["claim"]) if isinstance(d["claim"], str) else d["claim"]
        p = d["decided_at"]
        horizon = claim["horizon_s"]
        zone, cell = split_subject(d["subject"])
        if zone not in ends:
            ends[zone] = stream_end(store, run, zone)
        end = ends[zone]
        if end is None or horizon < min_horizon_s or end < p + horizon:
            still_open += 1
            continue
        observed = sum(1 for st in by_cell.get((zone, cell), ()) if p <= st < p + horizon)
        expected = claim["expected_stalls_next_hour"] * horizon / 3600
        error = observed - expected
        verdict = "ok" if abs(error) <= tolerance * max(expected, 1) else "off"
        write_once(store, dict(id=d["id"], run=run, grade_source="outcome", outcome=observed, expected=expected,
                               error=error, verdict=verdict, horizon_s=horizon, graded_at=end,
                               window_end=p + horizon))
        if decisions.stamp_grade(store, d["id"], observed, error, verdict, end):
            graded += 1
    return dict(graded=graded, open=still_open)

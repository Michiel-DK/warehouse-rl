"""Outcome grader for hotspot_forecast decisions: reads the store tables only (decisions, stalls, costmap, ingest_runs).
The "truth" grade source of forecast_grades is written by fleet/grade.py, not here.

For each open forecast published at P with claim horizon H: graded iff H >= min_horizon_s and stream_end[zone] >= P + H, i.e.
only on a fully observed window; otherwise it stays open (no forecast_grades row, no stamp). Two grades per eligible forecast:
  * COUNT grade, grade_source "outcome_count", for every eligible forecast (any rank, any claim version): observed = stalls
    of that zone and cell (hotspot.counted: no faulted-episode stalls, no next_occupied stalls unless exclude_occupied is
    False) with start in [P, P + H); expected = claimed stalls per hour * H / 3600; verdict "ok" iff
    |observed - expected| <= tolerance * max(expected, 1), else "off".
  * RANK grade, grade_source "outcome", only for a claim with rank k <= top_k = K (claim_version 2): the cell's rank r in
    the zone's map recomputed at window_end = P + H from the stalls table with the CLAIM's window_hours, half_life_h,
    min_stalls and exclude_occupied (never the grader's CLI flags), ranked by hotspot.rank_cells exactly as costmap.py
    ranks the claim; r is None when the cell is not in the map. outcome = r, expected = K, error None, verdict "ok" iff
    r is not None and r <= K, else "off". The decision is stamped with outcome = r, error None, that verdict.
  * k > K or a v1 claim (no top_k): no "outcome" row; the decision is stamped terminally with verdict "unranked",
    outcome = observed count, error = count error (it is graded on truth only, never left open).
horizon_s in the rows is H, graded_at is stream_end[zone], window_end is P + H.
Order of writes: the forecast_grades rows ("outcome_count", then "outcome") first, then decisions.stamp_grade. A crash
between leaves the decision open and the rows present; a re-run finds the rows, skips them and stamps the decision.
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


def ranked_zone(stalls_by_zone, cache, zone, at_ts, claim):
    """{cell: 1-based rank} of zone `zone`'s map at `at_ts`, recomputed from the stalls with the CLAIM's own map
    parameters (never the grader's CLI flags) and the ranking costmap.py publishes with (hotspot.rank_cells)."""
    params = (zone, at_ts, claim["window_hours"], claim["half_life_h"], claim["min_stalls"], claim["exclude_occupied"])
    if params not in cache:
        maps = hotspot.cost_zones(stalls_by_zone.get(zone, ()), at_ts, claim["window_hours"], claim["half_life_h"],
                                  claim["min_stalls"], claim["exclude_occupied"])
        cache[params] = {c: r for r, (c, _) in enumerate(hotspot.rank_cells(maps.get(zone, {})), 1)}
    return cache[params]


def grade_outcomes(store, run, min_horizon_s=DEFAULT_MIN_HORIZON_S, tolerance=DEFAULT_TOLERANCE,
                   exclude_occupied=True):
    """Returns dict(graded, open, rank_graded, unranked). graded = decisions stamped by this call = rank_graded
    (claim rank k <= claim top_k K: grade_source "outcome" row, stamp follows the rank grade) + unranked (k > K, or a
    v1 claim without top_k: no "outcome" row, stamp verdict "unranked" with the observed count). Every eligible
    forecast also gets its "outcome_count" row."""
    ends = {}  # zone -> stream_end, read once per call
    by_cell = {}
    stalls_by_zone = {}
    for s in store.select("stalls", {"run": run}):
        stalls_by_zone.setdefault(s["zone"], []).append(s)
        if hotspot.counted(s, exclude_occupied):
            by_cell.setdefault((s["zone"], s["cell"]), []).append(s["start"])
    rank_cache = {}
    rank_graded = unranked = still_open = 0
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
        write_once(store, dict(id=d["id"], run=run, grade_source="outcome_count", outcome=observed, expected=expected,
                               error=error, verdict=verdict, horizon_s=horizon, graded_at=end,
                               window_end=p + horizon))
        k, top_k = claim.get("rank"), claim.get("top_k")
        if top_k is not None and k is not None and k <= top_k:
            rank = ranked_zone(stalls_by_zone, rank_cache, zone, p + horizon, claim).get(cell)
            rank_verdict = "ok" if rank is not None and rank <= top_k else "off"
            write_once(store, dict(id=d["id"], run=run, grade_source="outcome", outcome=rank, expected=top_k,
                                   error=None, verdict=rank_verdict, horizon_s=horizon, graded_at=end,
                                   window_end=p + horizon))
            if decisions.stamp_grade(store, d["id"], rank, None, rank_verdict, end):
                rank_graded += 1
        elif decisions.stamp_grade(store, d["id"], observed, error, "unranked", end):
            unranked += 1
    return dict(graded=rank_graded + unranked, open=still_open, rank_graded=rank_graded, unranked=unranked)

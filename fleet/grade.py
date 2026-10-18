"""Grade the stuck analyser's decisions against what happened next.

Usage: python fleet/grade.py --run NAME [--store jsonl:DIR | clickhouse://HOST[:PORT]/DB] (--once | --every 60)
       [--min-horizon-s 600] [--tolerance 0.5] [--include-occupied] [--truth PATH]
--once grades what is due now, using the run's latest transition timestamp as `now` (event time; for a finished run),
and exits. --every S repeats every S seconds with the wall clock as `now` (for a live run) until SIGINT/SIGTERM, opening
the store afresh each cycle. Grades are written only through decisions.stamp_grade; a decision is graded once. Verdict
rules: docs/SCOPE.md "S5C1". Logic: fleet_analyser/grade.py.
hotspot_forecast decisions (S8B) are outcome-graded in every cycle too (stream only, fleet_analyser/forecast_grade.py):
a forecast_grades row "outcome_count" (stall count within tolerance) for every eligible forecast, a row "outcome" (the
claimed rank <= top_k still holds at window_end) for a claim with rank <= top_k, and the decision is stamped (with the
rank grade, or verdict "unranked" when there is no rank claim to grade). --truth PATH additionally truth-grades every
forecast against that run's truth.json: forecast_grades rows with grade_source "truth", verdict "hit" iff the cell is
one of the zone's floor_cells else "false_alarm"; the decision and decision_grades are never touched, and a forecast
in a zone truth.json does not list raises. With a fleet-truth/2 file (S10A) the verdict is truth.truth_positive over the steps [decided_at, decided_at + horizon_s]
(floor cells time-free, blocked / outage cell windows); a v1 file keeps the floor-only rule. This file is the only place the
grading path reads truth.json.
Lesson decisions (fleet/lessons.py) are graded in every cycle too (fleet_analyser/lessons.py grade_lessons): an open
lesson whose zone stream reached window_end + W gets a forecast_grades row "lesson" (ok / off against the next window of
the same length) and then its stamp. hot_cell and hot_robot lessons also get a "lesson_persist" row (ok iff the subject
is still at or above the next window's own average stalled cell / robot; the decision is never touched by it). --truth also writes a "lesson_truth" row (hit / false_alarm) for every hot_cell
lesson, and with a v2 file for every hot_robot lesson too (frozen windows; a v1 file writes no robot rows); the lesson decision is never stamped by truth. counts["lesson"] = dict(graded, open, persist = dict(graded, open)[, truth]).
"""
import argparse
import json
import signal
import sys
import threading
import time
from pathlib import Path

FLEET = Path(__file__).resolve().parent
if str(FLEET) not in sys.path:
    sys.path.insert(0, str(FLEET))

from fleet_analyser import forecast_grade, grade, lessons, store as store_mod  # noqa: E402
from fleet_analyser.forecast_grade import split_subject, write_once  # noqa: E402
import truth as truth_mod  # noqa: E402


def grade_truth(store, run, truth):
    """truth = the parsed truth.json. A forecast in a zone truth.json does not list raises ValueError before any row is
    written. Returns dict(graded) = new rows."""
    fcs = forecast_grade.forecasts(store, run)
    missing = sorted({split_subject(d["subject"])[0] for d in fcs} - set(truth.get("zones", {})))
    if missing:
        raise ValueError(f"truth.json has no zone {', '.join(missing)} (forecasts exist for it)")
    n = 0
    for d in fcs:
        zone, cell = split_subject(d["subject"])
        s0, s1 = truth_mod.forecast_steps(truth, d["decided_at"], lessons.claim_of(d))
        verdict = "hit" if truth_mod.truth_positive(truth, zone, cell, s0, s1) else "false_alarm"
        n += write_once(store, dict(id=d["id"], run=run, grade_source="truth", outcome=None, expected=None,
                                    error=None, verdict=verdict, horizon_s=None, graded_at=None,
                                    window_end=None))
    return dict(graded=n)


def grade_lesson_truth(store, run, truth):
    """lesson_truth rows for every hot_cell lesson: verdict "hit" iff the cell is one of the lesson zone's floor_cells,
    else "false_alarm". The decision is never stamped by truth. A lesson in a zone truth.json does not list raises
    ValueError before any row is written. Returns dict(graded) = new rows."""
    hot = [(d, lessons.claim_of(d)) for d in lessons.lessons(store, run)]
    hot = [(d, c) for d, c in hot if c["lesson_kind"] == "hot_cell"
           or (c["lesson_kind"] == "hot_robot" and not truth_mod.is_v1(truth))]
    missing = sorted({c["zone"] for _, c in hot} - set(truth.get("zones", {})))
    if missing:
        raise ValueError(f"truth.json has no zone {', '.join(missing)} (hot_cell lessons exist for it)")
    n = 0
    for d, c in hot:
        subject = split_subject(c["subject"])[1].removeprefix("cell ")
        s0, s1 = truth_mod.lesson_steps(truth, c.get("window_start"), c["window_end"])
        verdict = "hit" if truth_mod.truth_positive(truth, c["zone"], subject, s0, s1) else "false_alarm"
        n += write_once(store, dict(id=d["id"], run=run, grade_source="lesson_truth", outcome=None, expected=None,
                                    error=None, verdict=verdict, horizon_s=None, graded_at=None, window_end=None))
    return dict(graded=n)


def cycle(spec, run, now=None, min_horizon_s=forecast_grade.DEFAULT_MIN_HORIZON_S,
          tolerance=forecast_grade.DEFAULT_TOLERANCE, exclude_occupied=True, truth_path=None):
    """Open the store, grade, close it. now=None means the run's event-time end (batch mode). The returned counts carry
    the forecast results under "forecast" (outcome, and truth when truth_path is given) and the lesson results under
    "lesson" (graded, open, and truth when truth_path is given)."""
    st = store_mod.open_store(spec, run)
    try:
        counts = grade.grade_run(st, run, grade.batch_now(st, run) if now is None else now)
        fc = dict(outcome=forecast_grade.grade_outcomes(st, run, min_horizon_s, tolerance, exclude_occupied))
        counts["lesson"] = lessons.grade_lessons(st, run)
        counts["lesson"]["persist"] = lessons.grade_lessons_persist(st, run)
        if truth_path is not None:
            with open(truth_path) as f:  # the only read of the emitter's ground truth on the grading path
                truth = json.load(f)
            fc["truth"] = grade_truth(st, run, truth)
            counts["lesson"]["truth"] = grade_lesson_truth(st, run, truth)
        counts["forecast"] = fc
        return counts
    finally:
        st.close()


def show(run, counts):
    verdicts = "; ".join(f"{k}: " + ", ".join(f"{v} {n}" for v, n in sorted(vs.items()))
                         for k, vs in sorted(counts["verdicts"].items())) or "none"
    line = (f"grade {run}: stamped {counts['stamped']}, not due {counts['not_due']}, skipped_kind "
            f"{counts['skipped_kind']}, verdicts {verdicts}")
    if "forecast" in counts:
        line += f"; forecasts {counts['forecast']}"
    if "lesson" in counts:
        line += f"; lessons {counts['lesson']}"
    return line


def live(spec, run, every, clock, wait, stop, out=print, **kw):
    """Grade every `every` seconds with the wall clock as now, reopening the store each cycle, until `stop` is set."""
    while not stop.is_set():
        out(show(run, cycle(spec, run, clock(), **kw)))
        wait(every)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--run", required=True)
    p.add_argument("--store", default=None,
                   help="jsonl:<dir> (default fleet/data/<run>/store) or clickhouse://host[:port]/db")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true", help="grade once with the run's latest transition ts as now")
    mode.add_argument("--every", type=float, metavar="S", help="grade every S seconds with the wall clock as now")
    p.add_argument("--min-horizon-s", type=float, default=forecast_grade.DEFAULT_MIN_HORIZON_S,
                   help="a hotspot_forecast with less observed horizon than this stays open")
    p.add_argument("--tolerance", type=float, default=forecast_grade.DEFAULT_TOLERANCE)
    p.add_argument("--include-occupied", action="store_true", help="count next_occupied stalls in forecast outcomes")
    p.add_argument("--truth", default=None, metavar="PATH", help="also truth-grade every hotspot_forecast")
    a = p.parse_args(argv)
    if a.every is not None and a.every <= 0:
        p.error("--every must be > 0")
    if a.min_horizon_s < 0 or a.tolerance < 0:
        p.error("--min-horizon-s and --tolerance must be >= 0")
    kw = dict(min_horizon_s=a.min_horizon_s, tolerance=a.tolerance, exclude_occupied=not a.include_occupied,
              truth_path=a.truth)
    try:
        if a.once:
            print(show(a.run, cycle(a.store, a.run, **kw)))
            return 0
        stop = threading.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: stop.set())
        live(a.store, a.run, a.every, time.time, stop.wait, stop, out=lambda s: print(s, flush=True), **kw)
    except (ValueError, OSError) as e:
        p.error(str(e))
    return 0


if __name__ == "__main__":
    sys.exit(main())

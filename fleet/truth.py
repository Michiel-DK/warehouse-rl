"""The one place a truth.json is asked "is this subject a real problem in this time range?" (S10A, fleet-truth/2).

Truth readers: only grade.py, hotspot_score.py and time_to_detect.py (its blocked / outage window kinds, S10B) import
this module (enforced by a test); nothing under fleet_analyser/ does. Other truth readers (score.py, replay_export.py,
overview_build.py) read the file directly and keep the v1 rules (floor_cells only); that is deliberate and out of scope
here.

truth_positive(truth, zone, subject, step_from, step_to) -> frozenset of matched kinds (truthy = positive):
  cell "x,y"       "floor" iff in the zone's floor_cells (time-free); "blocked" / "outage" iff some window [a, b) of
                   that kind on the cell has a <= step_to and b > step_from.
                   S10G: also "frozen" iff some frozen window has `cell` == the subject and overlaps the same way (a window
                   without a `cell` key, from an older file, never matches a cell; `cells` is informational, not scored).
                   S12B: also "deadzone" iff the cell is in the zone's `deadzones` ([x, y] pairs written by emit.py --deadzone;
                   time-free like floor; a zone without the key never matches). A dead zone is not a stall: every caller that
                   treats a non-empty answer as positive (grade.py, time_to_detect.py, hotspot_score's baselines) will also
                   count a dead cell as positive in a run that has them; hotspot_score keeps 'deadzone' out of "any".
  robot "Z<z>-NN"  "frozen" iff some frozen window with that serial overlaps the same way.
A v1 file (no window keys, no t0) answers with floor_cells only, robots are never positive, and no step is needed
(step_from / step_to may be None). A v2 file asked for a window kind with None steps raises ValueError.
Steps are floats on the emitter's clock: step = (epoch - epoch(t0)) / step_seconds.
"""
import math
import sys
from pathlib import Path

_FLEET = Path(__file__).resolve().parent
if str(_FLEET) not in sys.path:
    sys.path.insert(0, str(_FLEET))

from fleet_analyser.parse import epoch_of  # noqa: E402

WINDOW_KINDS = (("blocked", "blocked_windows"), ("outage", "outage_windows"))


def is_v1(truth):
    return "t0" not in truth


def step_of(truth, ts):
    """Epoch seconds -> step on the file's clock (float). Needs a v2 file."""
    return (ts - epoch_of(truth["t0"])) / truth["step_seconds"]


def forecast_steps(truth, decided_at, claim):
    """(step_from, step_to) of a forecast issued at epoch decided_at whose claim holds horizon_s; (None, None) for v1
    (the claim is not read)."""
    if is_v1(truth):
        return None, None
    s = step_of(truth, decided_at)
    return s, s + claim["horizon_s"] / truth["step_seconds"]


def lesson_steps(truth, window_start, window_end):
    """(step_from, step_to) of a lesson window [window_start, window_end) in epoch seconds: the first and the last
    emitted step inside it (step_to = ceil(step(window_end)) - 1); (None, None) for v1."""
    if is_v1(truth):
        return None, None
    return math.ceil(step_of(truth, window_start)), math.ceil(step_of(truth, window_end)) - 1


def _overlaps(w, step_from, step_to):
    return w["start_step"] <= step_to and w["end_step"] > step_from


def truth_positive(truth, zone, subject, step_from, step_to):
    zt = truth["zones"][str(zone)]
    kinds = set()
    if "," in subject:
        if subject in zt.get("floor_cells", {}):
            kinds.add("floor")
        if "deadzones" in zt and any(f"{x},{y}" == subject for x, y in zt["deadzones"]):
            kinds.add("deadzone")
        for kind, key in WINDOW_KINDS:
            ws = [w for w in zt.get(key, ()) if w["cell"] == subject]
            if ws and step_from is None:
                raise ValueError(f"a v2 truth needs steps to answer for {subject}")
            if any(_overlaps(w, step_from, step_to) for w in ws):
                kinds.add(kind)
        ws = [w for w in zt.get("frozen_windows", ()) if w.get("cell") == subject]
        if ws and step_from is None:
            raise ValueError(f"a v2 truth needs steps to answer for {subject}")
        if any(_overlaps(w, step_from, step_to) for w in ws):
            kinds.add("frozen")
    else:
        ws = [w for w in zt.get("frozen_windows", ()) if w["serial"] == subject]
        if ws and step_from is None:
            raise ValueError(f"a v2 truth needs steps to answer for {subject}")
        if any(_overlaps(w, step_from, step_to) for w in ws):
            kinds.add("frozen")
    return frozenset(kinds)

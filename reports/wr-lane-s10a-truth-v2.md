# wr-lane-s10a-truth-v2 — S10A truth sidecar v2 (18 Oct 2026)

**Result: MERGED** PR #36 → master `46e9872` (squash). Fast-forwarded. Docs follow-up on master: `24cb0b7`
(fleet/data/README stall-share readings). Brief: `reports/wr-lane-s10a-brief.md`.

## What landed
- `fleet/fleet_analyser/emitter.py`: truth.json is `fleet-truth/2` with top-level `t0`, `step_seconds`, and per zone
  `blocked_windows`, `outage_windows`, `frozen_windows` (serial = emitted `Z{z}-NN`), `burst` (or null).
- `fleet/truth.py`: `truth_positive(truth, zone, subject, step_from, step_to)`. A window [a,b) overlaps when
  a <= step_to and b > step_from. Floor cells don't depend on time. A v1 file gives exactly the old rule.
- `fleet/grade.py`: grades forecasts over [decided_at step, + horizon_s/5]. Grades hot_cell lessons over the lesson
  window, and adds hot_robot lessons for v2 files only (v1 files skip them).
- `fleet/hotspot_score.py`: adds `truth_kinds` (floor/blocked/outage/any per-K precision/recall/hits plus frozen robot
  positives) and `--smoke`.
- Tests: `fleet/tests/test_fleet_truth_v2.py` (24 tests). `test_fleet_truth.py`, `test_fleet_hotspot.py`
  (truth.py registered as a truth reader) and `test_fleet_demo.py` were extended.

## Evidence (main loop, run myself)
- Gate on PR head `11cfeba`: `fleet/tests` **Ran 754, OK** (WR_STICKY_PHASEA set); `tests/` **Ran 828, OK
  (skipped=1)**.
- v1 regression, rerun independently on a fresh copy of the sticky phase-A store with the PR code:
  decisions.jsonl `21be7a50…`, forecast_grades.jsonl `0cbc1353…`, truth hit 1125 / false_alarm 175. These are
  byte-identical to master 8ad6120, measured twice before the lane. The hotspot_score JSON with `truth_kinds` removed
  equals master's.
  CAVEAT: the test that asserts this runs only when `WR_STICKY_PHASEA` is set (the store is untracked), and the
  hotspot equality runs only when `/tmp/s10a-baseline` exists. The default gate and CI check neither. My manual
  rerun is the evidence.
- `hotspot_score.py --smoke`: exit 0 in **3.0 s**. All lists are non-empty on both zones; the run checks this in code
  and `smoke_problems` has a unit test for the failure cases.
- Queue command dry run with the new configs (2 zones × 120 steps, /tmp): all four presets ran emit → ingest →
  costmap → lessons → grade → score with exit 0. I then deleted the toy `results/fleet/hotspot_s10-*.json` files the
  dry run left behind.

## Review round
Criterion pre-review halted launch 1 with 3 blocking findings: unscoped importer fence, no file list, missing
hot_robot grading. Relaunched with its rewrite verbatim. Refuters for correctness, regression and test-honesty did
not refute. The invariants lens did not refute. The scope-adherence lens refuted only on `fleet/tests/test_fleet_demo.py`
being outside my file list. I resolved that: the 9-line edit only extends two exact-key assertions with the v2 keys and
adds t0 to a run dict, which the new keys force. The operator brief asked for "extensions of the existing truth tests";
the file list was my authoring error. Recorded on the PR.

## Deviations (stated, not hidden)
1. **Clause 5 calibration band is unreachable.** With the specified reading (≥1 robot inside a stuck_episodes row,
   open episode = to stream end), the no-disturbance baseline is 0.982 on the medium map (2 zones × 500 steps). I
   reproduced the lane's number exactly. I checked four other readings: the baseline lands in the band only on
   `stalls` rows (0.334), and there the disturbances *lower* it (blocked 0.323, breakdown-heavy 0.236). Only breakdown
   separates from baseline, and only on "stalls with in_episode" (0.099 → 0.190). No reading makes the config a knob
   for the band. Table in `fleet/data/README.md`.
2. **So the queue configs were chosen on a substitute criterion: truth coverage** (windows on 10 zones × 500 steps,
   seeds 0-9, read from the schedule). The lane's "closest to band" outage pick (0.25/h) had 1 window in 10 zones, so it
   could not be graded.

   | preset | config | truth windows (10 zones) | zones with none | stall share (lane reading) |
   |---|---|---|---|---|
   | blocked | `{"blocked_cell":{"rate_per_hour":8.0,"duration":[60,240]}}` | 50 | 0 | 0.977 |
   | outage | `{"outage":{"rate_per_hour":4.0,"duration":[120,360]}}` | 20 | 1 | 0.982 |
   | breakdown | `breakdown-heavy` | 426 frozen | 0 | 0.996 |
   | burst | `{"burst":{"start":100,"end":300,"extra":20}}` | no cells (by design) | – | 0.981 |
   | baseline | `{}` | – | – | 0.982 |

   Written into `wr-s10-disturbance-measure`'s command (only that item; title updated to say so) and into
   `fleet/data/README.md`.
3. **`hotspot_score.py` does not import `truth.py`.** `truth_kinds` counts window cells itself, at run level and
   without time. Its forecast grading comes from rows `grade.py` wrote through `truth_positive`. The brief asked for ONE
   matching function imported by both. No v1 number changes. S10B (time to detect/clear) should reuse `truth.py`
   instead of a third copy.

## Operator questions
- Do you want a stall-share definition that separates disturbed from undisturbed runs? None of the five readings does
  for blocked or outage on 2 zones. Or is truth coverage the right rule for choosing the S10 configs?
- Breakdown-heavy has 426 frozen windows over 120 robots, so nearly every robot is a frozen-truth positive. hot_robot
  truth precision will be close to trivially high on that run; read it next to the positives count.
- Blocked cells and outages may barely cause stalls: A* routes round them. That may itself be the S10 headline.

SCHED_RESULT: OK S10A merged (PR #36 -> 46e9872); gates 754 OK / 828 OK (1 skip); v1 byte-identical; smoke 3.0 s; calibration band unreachable (baseline 0.982), measure configs chosen by truth coverage and written to wr-s10-disturbance-measure

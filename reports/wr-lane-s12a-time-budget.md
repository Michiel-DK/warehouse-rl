| run-level AGV time budget | moving | waiting_station | waiting_shelf | stuck | stopped_short | idle | faulted |
|---|---|---|---|---|---|---|---|
| s10-none (80 AGVs, 10 zones, 199600 AGV-s) | 40.0% | 2.1% | 28.8% | 20.8% | 4.5% | 3.8% | 0.0% |
| closed_loop_sticky phaseA (240 AGVs, 30 zones, 598800 AGV-s) | 12.1% | 1.6% | 51.7% | 32.0% | 1.6% | 1.0% | 0.0% |

| station_waits_in_stall_list (detector episodes, store source) | episodes | at station | shelf-adjacent | picker episodes | share at station | share station or shelf |
|---|---|---|---|---|---|---|
| s10-none | 677 | 10 | 658 | 79 | 1.5% | 98.7% |
| closed_loop_sticky phaseA | 2411 | 47 | 1839 | 998 | 2.0% | 78.2% |

**Station waits are NOT a large share of the sticky run's stall list: 47 of 2411 detector episodes (2.0%) start on a
station cell, 10 of 677 (1.5%) on the undisturbed run.** The operator complaint "a robot queued at a station is filed as
stuck" is real in the definition but small in this sim. The detector is untouched; whether station waits leave the stall
list is the operator's decision.

**The "shelf-adjacent" share is not evidence of picker waits.** On tarware-medium (22 x 25 = 550 cells) the
shelf-adjacent class (slot or Manhattan 1 from a slot, minus stations) covers 360 cells: all 160 slots plus 200 of the
390 highway cells (51% of the aisles). So `waiting_shelf` (28.8% / 51.7% of AGV time) and the 97% / 76% of stall
episodes that start "next to a shelf" mostly say "stopped in an aisle", not "waiting for a picker". A tighter signal
exists in the stream and is NOT built: a stopped AGV whose nodeStates is [] (no next node), which hotspot.py already
treats as loading / picker wait. Operator call whether to refine the bucket.

# S12A per-robot time budget (fleet/timebudget.py)

PR #47 (branch worktree-wf_79da7d70-976-2), squash-merged into master as 6daac2d. Three files: fleet/timebudget.py (new),
fleet/tests/test_fleet_timebudget.py (new, T1-T14, 28 cases), fleet/tests/test_fleet_hotspot.py ("timebudget.py" added to
the analyst-isolation required names). Nothing under fleet/fleet_analyser/, vendor/, src/, scripts/, README, SCOPE.

## What it does

`timebudget.py --glob DIR/*.jsonl.gz --run RUN --stations PATH|auto --out PATH [--shift-s 3600] [--store jsonl:DIR]
[--workers N]`. Per zone and AGV, every second of the span goes to one of seven buckets from the message stream alone,
precedence faulted > moving > waiting_station > waiting_shelf > stuck / stopped_short > idle; stopped runs and the 30 s
rule are the detector's own (Detector and DEFAULT_STUCK_AFTER imported unchanged); bucket sum == span is an explicit
ValueError. Pickers are reported apart (zones[z].pickers) and kept out of the totals. `--stations auto` derives goals,
shelf slots and robot kinds from the run's emit_ledger.json, one freshly spawned env process per (env_id, seed), and does
not import replay_export (T3/T11 compare it with replay_export.run_env_worker). Also: jobs_per_robot_hour,
same_minute_stops, station_waits_in_stall_list, stuck_runs_vs_detector, cell_classes, src with store hashes.

## Smoke (in the lane, main-checkout data, --stations auto, outputs in /tmp)

| run | elapsed | AGVs / zone | stuck runs vs detector | store hash | input listing |
|---|---|---|---|---|---|
| s10-none | 2.7-5.2 s | 8 AGVs + 4 pickers, all 10 zones | 677 = 677, start sets equal | before == after | identical |
| closed_loop | 8.0-15.9 s | 8 AGVs + 4 pickers, all 30 zones | 2411 = 2411, start sets equal | before == after | identical |

jobs_per_robot_hour: 22.18 (s10-none), 7.02 (sticky).

## Caveat: same_minute_stops is not an outage signal yet

Both runs give 16 flagged minutes. Sticky: all 16 are minute 00:00, the zone start (robots start driving and stop in
the first minute), so the count is a start artefact. s10-none (undisturbed): 3 at 00:00, 13 scattered = about 1.3 per
zone of background with no outage at all. Before reading it as the "software update" signature it needs the first
minute excluded and a reference rate from an undisturbed run (s10-none is that reference). Not changed in this lane.

## Review rounds

- Criterion pre-review halted twice before any build (robot scope: pickers in the stream; per-zone vs per-robot fields;
  then process-per-layout not gated). Rewrites adopted.
- Pass 1: correctness, scope, invariants refuters clean; test-honesty refuted (single-zone fixtures, T3 overclaimed
  process isolation, hash-changed exit untested).
- Pass 2: added T10-T13, explicit raise; all four refuters clean, mutations for T10/T11/T12 went red. python-reviewer
  failed it on the repo worker rule (hard-coded LAYOUT_THREADS = 4).
- Main loop fix ce792b4: --workers / SCHED_WORKERS / cpu_count - 2 via scripts/evaluate.resolve_workers, capped at the
  layouts; T14 (both mutations, constant pool and args.workers dropped, went red). Re-verified by a fresh verify-gate:
  not refuted. Gate on the fix: fleet/tests 1029 tests OK (skipped 4); tests/ 1038 tests OK (skipped 4); on master after the merge the 28 timebudget tests + TestAnalystIsolation pass.
- Counter drift from reusing one process is unobservable on this map (reset() restarts the counters; seeds 0 and 1 give
  identical layouts); T11 documents it as a characterization and T3's inject comment was corrected.
- Open minor (not fixed): `--workers ""` is an argparse error here, while scripts/evaluate.workers_arg treats it as unset.

## Queue

`wr-s12a-budget-run` in laptop-scheduler/queues/warehouse-rl.json now has the fixed command (not run): timebudget on
fleet/data/s10-none, fleet/data/s10c-blind, fleet/data/s10-breakdown, results/closed_loop_sticky/phaseA (run closed_loop)
and fleet/data/s8b-score (the run results/fleet/baselines_s8b-medium-80-p03-07.json names: run s8b-score; there is no
results/fleet_s8b_medium) into results/fleet/timebudget_{s10-none,s10c-blind,s10-breakdown,closed-loop-sticky,
s8b-medium-80-p03-07}.json. Expected well under its 10 min estimate (smoke: < 20 s per run).

## Operator questions

1. Station waits are 1.5-2.0% of the stall list: drop them from the stall list, or leave the detector as is?
2. Refine waiting_shelf to "stopped with nodeStates []" (picker / loading wait) instead of the 360-cell neighbourhood?
3. same_minute_stops: exclude the first minute and report against the undisturbed rate before it goes on a page?

SCHED_RESULT: OK S12A merged PR #47 -> 6daac2d (fleet/timebudget.py, T1-T14); station waits 47/2411 (2.0%) of sticky stall list, 10/677 (1.5%) s10-none; waiting_shelf is a 360-of-550-cell catch-all; same_minute_stops = start-minute artefact; wr-s12a-budget-run command set (not run)

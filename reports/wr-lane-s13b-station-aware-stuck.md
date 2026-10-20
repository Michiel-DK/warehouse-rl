sha256 of the Detector() event stream with stations absent (json.dumps(ev, sort_keys=True) per event, newline-joined; every message of the zone file fed through hotspot.read_messages order, then end_all()), produced by `python -I /tmp/evhash.py CODE_ROOT FILE` where CODE_ROOT is `git archive master fleet src` extracted to /tmp/master_tree (master b931b3b) or this branch, and the script is:

```
sys.path.insert(0, root + "/fleet")
from fleet_analyser.detector import Detector
from fleet_analyser.hotspot import read_messages
det = Detector(); evs = []
for m in read_messages(path): evs += det.feed(m)
evs += det.end_all()
print(sha256("\n".join(json.dumps(e, sort_keys=True) for e in evs)))
```

| zone file | master b931b3b | branch (stations absent) | equal |
|---|---|---|---|
| fleet/data/s10-none/zone0-000.jsonl.gz (6000 msgs, 1614 events) | c43c6ce3ea97462e035fddc1262275ab2634b4795db91a39a3e3bbda31da5ccb | c43c6ce3ea97462e035fddc1262275ab2634b4795db91a39a3e3bbda31da5ccb | yes |
| results/closed_loop_sticky/phaseA/zone0-000.jsonl.gz (6000 msgs, 418 events) | 880568466599e4e0059eb6ab11ec55213f8d121863b746bf42d3620e647a2420 | 880568466599e4e0059eb6ab11ec55213f8d121863b746bf42d3620e647a2420 | yes |

The data files are untracked in the lane worktree and were read from the main checkout (read-only). The s10-none value is pinned in tests/platform_expected.json (fleet_stream.darwin-arm64.s13b_s10_none_zone0_event_sha256) and checked by test (e); linux has no value, so (e) skips there visibly.

Further stations-absent byte checks, master tree vs branch, same inputs (a /tmp copy of fleet/data/s10c-blind): `deadlock.py` output file cmp-identical; `timebudget.py --stations auto` output cmp-identical; `ingest.py` stuck_episodes, transitions, evidence jsonl cmp-identical, decisions and ingest_files differ only in the wall-clock keys recorded_at / updated_at, and ingest_runs has no servicing_runs key; `moroop.py --analyse` (no new option) rebuilt from the regenerated jsonl / budget gives timebudget_moroop.json and timebudget_moroop_shifts.json cmp-identical to the committed S13A files in results/fleet.

## What changed

- fleet/fleet_analyser/detector.py: `at_station(x, y, stations, radius)` (Manhattan <= radius to any station goal cell, False when stations is None or empty), `Detector(stuck_after, resumed, stations=None, station_radius=0)`, state SERVICING (state tuple and module docstring). The run's cell is the cell of the run's first stopped message. A run that lasts >= stuck_after at a station is SERVICING from that moment: transitions are emitted, no episode opens, no cause is computed; `Detector.servicing_runs` counts them. A run that starts off-station is untouched; moving off and stopping again starts a new run judged on its own cell. `stations` may be a set of cells or a mapping zone -> cells with "*" as fallback.
- fleet/fleet_analyser/stations.py (new): `load_stations(spec, glob_dir)` ("auto" or a `{"stations": [[x, y], ...]}` path), `goal_cells`, and `auto_layouts`, `_layout_worker`, `run_layout_worker`, `kinds_of`, `resolve_workers` moved from timebudget.py (timebudget imports them back, behaviour unchanged). Imports nothing from fleet/truth.py and contains none of the words the analyst isolation scan looks for.
- fleet/ingest.py + fleet_analyser/ingest.py: `--stations auto|PATH`, `--station-radius N` (default 0), file source only. Suppressed runs write no episode; the ingest_runs row carries `servicing_runs` only when --stations is given.
- fleet/deadlock.py: same two flags into the `_Tap(Detector)` construction; `station_rule` key in the document only when given.
- fleet/timebudget.py: `--station-aware`, `--station-radius N`; `run_is_stuck(kept, run, stations=None, radius=0)` and `recompute_episodes(messages, stations, station_radius)` use the same `at_station`; `robot_budget(..., rule_radius=None)`; src carries station_aware / station_radius only with the flag. A suppressed run's seconds fall to stopped_short (or waiting_station / waiting_shelf where those buckets already apply).
- fleet/adapters/moroop.py `--analyse`: `--station-radius N` (default None = unaware) and `--suffix S`. With a radius the `--stations` cells go through timebudget.run_is_stuck into second_buckets, run_intervals and label_comparison, and the in-process robot_budget is the aware one (the on-disk S13A budget file is still checked against the unaware one). With a suffix it writes timebudget_moroop-S.json, timebudget_moroop_shifts-S.json and moroop_label-S.json (per-shift `label` objects and the pooled `label`, same field names) and never the unsuffixed files.
- Tests: fleet/tests/test_fleet_detector_stations.py (a)-(g) plus CLI flag tests; fleet/tests/test_fleet_timebudget.py T14 now patches `run_layout_worker` on the stations module (the function moved); tests/platform_expected.json gains the pinned hash.
- Queue: wr-s13b-rerun in laptop-scheduler/queues/warehouse-rl.json now holds the real command (cores 4, est 5 min, max 30). Only that item changed (checked by diffing the parsed JSON item by item).

## Store readers: no flag needed

costmap.py, grade.py, hotspot_score.py, baselines.py, time_to_detect.py (and fastmap.py) construct no Detector. They read the store: costmap / fastmap / baselines / hotspot_score take stalls from the messages (hotspot.py: consecutive stall messages with nodeStates attribution; a station wait has nodeStates [] and is never a stall message) and only join the store's `stuck_episodes` rows through `annotate_episodes` for `in_episode` and the faulted_episode exclusion; grade.py reads stuck_episodes / transitions. A store written with `ingest --stations` therefore flows through unchanged, and a station dwell merely no longer has an episode. time_to_detect copies DIR/store and reruns costmap on it.

## replay_export

fleet/replay_export.py:610 constructs `Detector(stuck_after=...)` and is untouched; stations defaults to None, so it is identical to master. fastmap.py constructs no Detector and is untouched.

## MoRoOp

Shift 0 (2026_07_27_morning), `test_f` output: stuck runs / unlabelled (false alarm) runs / label hits / label misses before (stations unaware) 69 / 67 / 0 / 0, after `--station-radius 1` 0 / 0 / 0 / 0. All nine shifts (full `--analyse --station-radius 1 --suffix st` in the smoke below): stuck runs 567 -> 2, false alarms 544 -> 1, label episodes >= 30 s hits 2 -> 2 (misses 0), but TIMEOUT operations detected 8 -> 1: the only reading I can offer is that the seven were detected through stuck runs that now count as station dwells (inferred from the counts, not inspected per operation). That is a consequence of the rule, not checked as a bug, and worth the operator's eye.

## Smoke timing

The whole wr-s13b-rerun command ran on a /tmp copy of the five runs plus the MoRoOp raw (symlinked), SCHED_WORKERS=4: 157 s wall, exit 0, the before/after hash check passed. One ingest with `--stations auto` of s10c-blind (10 zones, includes 10 layout processes): 6.0 s wall. On the five simulator runs the effect is small: servicing runs 8 on s10c-blind; blocking clusters 49 -> 41 (s10-none), 56 -> 49 (s10c-blind), 28 -> 25 (s10-breakdown); the time-budget stuck share is unchanged at 0.2081 / 0.259 / 0.1864 because the exact station cell was already waiting_station there.

## Queue command notes

time_to_detect is run on view directories `DIR-st` (symlinked zone files, truth.json, emit_ledger.json, and a copy of store-st as `store`) instead of `--store-suffix st`: an existing DIR/store-st is read as a prebuilt CUSUM store (check_prebuilt_rows refuses non-cusum rows) and an absent one is copied from the station-unaware DIR/store. phase A keeps its original one-publish costmap, s8b-score its 1250 s publish interval, s10 runs 300 s; lessons only where the original had them. The command was written and smoked on a copy; it was not run on the real data.

## Gate

`.venv/bin/python -m unittest discover -s tests` (the fleet tests are collected by tests/test_fleet_collect.py), final run on the branch head:

```
Ran 1085 tests in 663.374s

OK (skipped=7)
```

An earlier run of the same gate (before the T14 test patch) had one error, test_t14_cli_workers_reaches_the_layout_pool, because auto_layouts moved to fleet_analyser.stations and the test patched the old name; fixed in the test, fleet.tests.test_fleet_timebudget 37/37 ok. The truth.json isolation tests (test_fleet_hotspot.TestAnalystIsolation, test_time_to_detect isolation scan) are part of this gate and ok. `python -m unittest fleet.tests.test_fleet_detector_stations -v`: 12 tests, all ok, none skipped on darwin-arm64 (the MoRoOp raw dir is in the main checkout).

## Pass 2

Cause of the pass-1 refutations: one defect, not two. `_step` computed `servicing = stuck_now and run station flag` without looking at `m.faulted`, so a faulted robot stopped on a station opened no episode (and, because the episode was missing, the faulted robot's episode could not be seen in the event list at all); the suite never fed a faulted message, so it could not tell. The two verdicts (correctness, test-honesty) are the code half and the test half of that one gap.

Fix (fleet/fleet_analyser/detector.py `_step`): `servicing = stuck_now and run.get("station", False) and not m.faulted`. A FAULTED message is never SERVICING and never suppresses the open guard. The Detector docstring now states that a run that was servicing and later faulted stays counted in `servicing_runs` (counted when it became SERVICING), and that if the fault clears on the station the state returns to SERVICING with the opened episode left open until the run ends.

New tests, fleet/tests/test_fleet_detector_stations.py (class TestFaultBeatsServicing, plus test_i), all ok on darwin-arm64, none skipped. Result against the pass-1 detector (head 36ee8a9, same tests, detector.py unfixed):

- h1 (faulted throughout a 90 s stop on (3,4), stations={(3,4)} vs stations=None, json.dumps sort_keys per event): FAILS at `assertEqual(dumps(got), dumps(want))`, 2 events missing (the faulted_self episode_open at 30 s and its close).
- h2 (not faulted 40 s on the station, then faulted 40-90 s): FAILS at `assertEqual(len(opens), 1)`, 0 != 1 (FAULTED transition appears but no episode opens).
- h3 (faulted robot on a station, adjacent off-station robot): FAILS at `assertEqual(dumps(got), dumps(want))`, the fault robot's 2 episode events are missing from the stations run (the neighbour's blocked_by_faulted episode with blocker Z0-00 is present in both; so the blocker lookup itself was not broken on 36ee8a9, the divergence is the missing faulted episode).
- All three pass after the fix.
- test_i pins the stations=None event-stream sha256 of results/closed_loop_sticky/phaseA/zone0-000.jsonl.gz (6000 messages, 418 events) at tests/platform_expected.json fleet_stream.darwin-arm64.s13b_sticky_phasea_zone0_event_sha256 = 880568466599e4e0059eb6ab11ec55213f8d121863b746bf42d3620e647a2420 (same serialisation and feed order as test e). The file is untracked; the test reads it from the main checkout through find_file (read-only). ok on darwin-arm64 (equal to the master value); linux has no value, so it skips visibly. Test e (s10-none) is still ok. Tests a-g and the flag tests are unchanged and ok.

Fence: fleet/timebudget.py `run_is_stuck` (and deadlock.py) are not edited in this pass. `run_is_stuck` judges a run by its first cell and has no fault check, so a run on a station that is faulted part-way now has a detector episode while timebudget books its non-faulted seconds to stopped_short; faulted messages are bucketed as faulted first, so the divergence is small. Test g has no faulted case.

Gate: `.venv/bin/python -m unittest discover -s tests` (root tests plus the fleet tests collected by tests/test_fleet_collect.py), run from this worktree with the main checkout's interpreter:

```
Ran 1089 tests in 648.652s

OK (skipped=7)
```

(1085 in pass 1 plus h1, h2, h3, test_i.)

SCHED_RESULT: OK S13B station-aware stuck rule: detector SERVICING + flags on ingest/deadlock/timebudget/moroop, stations-absent bytes equal master, pass 2 faulted-beats-servicing fix, gate 1089 ok, wr-s13b-rerun command written and smoked on a copy (157 s)

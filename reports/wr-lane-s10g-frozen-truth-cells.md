# wr-lane-s10g-frozen-truth-cells — S10G frozen windows carry the robot's cell (19 Oct 2026)

**Outcome: MERGED.** PR #42 was squash-merged as `5fe4501`, and master in `~/code/Michiel-DK/warehouse-rl` was fast-forwarded to it.
- Workflow: `single-lane-build`, tier standard, build model sonnet, run `wf_2cbb719f-5d2`.
- Brief: `laptop-scheduler/reports/wr-lane-s10g-brief.md` (including its amendment). Criterion: `wr-lane-s10g-criterion-v2.txt`.

## What landed (5 files, +166/-17)
- **`fleet/fleet_analyser/emitter.py`:** the step loop records every agent's `(int(x), int(y))` as written in that step's message. Each `frozen_windows` entry gains:
  - `cell`: "x,y" at start_step.
  - `cells`: the distinct cells over [start_step, end_step), sorted by string. It is informational and nothing scores it.
  - Schema stays fleet-truth/2. Nothing new reaches a message.
- **`fleet/truth.py`:** `truth_positive` on a cell subject adds "frozen" when the cell equals the `cell` of an overlapping frozen window.
  - It uses `w.get("cell")`, so older files without the key degrade to the serial-only rule and never raise.
  - A None-steps call raises ValueError only when a cell-matching window exists.
  - Robot subjects are unchanged, and `WINDOW_KINDS` is unchanged (a test pins it), so time_to_detect's `--truth-kind` choices are untouched.
  - grade.py needs no change: forecast truth grades and hot_cell lesson_truth already go through truth_positive.
- **`fleet/hotspot_score.py` `truth_kinds.frozen`:**
  - `positives` is UNCHANGED (distinct serials), because `scripts/sprint8_tables.py` prints it as "frozen robots".
  - New `cells`: an integer, the per-zone distinct count summed over zones.
  - New `k`: {K: precision = hits/(K·zones), recall = hits/cells, hits}.
  - `any` now includes frozen cells.
- **Tests (`fleet/tests/test_fleet_truth_v2.py`):**
  - Cell "3,4" with window [10,30): a hit at step 12 and a false alarm at step 40, both via truth_positive and via grade.grade_truth.
  - A hot_cell lesson_truth hit.
  - A truth without `cell` degrades to serial-only without raising.
  - truth_kinds is hand-computed, including the same cell frozen in two zones (cells 3, recall 2/3 at K=2).
  - Emitter CLI smoke (2 zones × 150 steps, small map, breakdown-heavy, seed-base 0): 9 frozen windows (5 + 4). Every window has `cells == [cell]`. The message at start_step has agvPosition == cell and a BREAKDOWN error; the message at start_step−1 has none.
  - The one frozen fixture in `test_fleet_baselines.py` was updated to the new shape.

## Evidence (from the PR body unless marked as mine)
- **Zone files.** They are byte-identical between base 217ecff and head on a 2-zone × 150-step breakdown-heavy run. The correctness refuter repeated this with `cmp` and found them the same.
- **More frozen windows.** The refuter also ran a 3-zone medium run: all 132 frozen windows have `cells == [cell]`.
- **Premise for the rerun.** A head re-emit of zone 0 has sha256 `8d0201e9…` on macOS, identical to `fleet/data/s10-breakdown/zone0-000.jsonl.gz`. The deterministic rerun should therefore pass its hash check.
- **Byte-identity on `results/closed_loop_sticky/phaseA`** (on copies of the store, base vs head):
  - grade stdout and the store hashes are identical.
  - The hotspot JSON differs only by the added `frozen.cells` and `frozen.k`.
- **Gate, run by me in the main checkout on PR head 5bce705** with WR_STICKY_PHASEA set:
  - `tests`: Ran 938, OK.
  - `fleet/tests`: Ran 892, OK.
  - Neither suite skipped anything.

## Review round
- **Criterion pre-review, attempt 1: halted** on one blocking item. "Distinct frozen cells pooled over zones" allowed a global union, which could put recall above 1. I adopted the reviewer's rewrite (v2: per-zone distinct, summed, plus a two-zone repeated-cell test). The halt came before any build ran, and it left no branch or PR.
  - The v2 pre-review found it sound, with 5 advisories (none changed the build).
- **python-reviewer:** pass, minor notes only.
  - A frozen window that starts at or past the recorded steps gets no `cell` and nothing signals it. This cannot happen in the measured runs, but a demo injection past the episode end could hit it.
  - The `positions` list is kept even when there are no frozen windows.
  - grade.py's docstring is stale.
- **Refuters (correctness, regression, plus the auto-added scope-adherence and invariants):** none refuted, all at medium confidence.
  - The regression refuter's full-suite run failed in its own worktree. That worktree had no vendor/ and its cwd broke spawn, so the refuter attributed the failures to its environment. My gate run in the main checkout is the authoritative one, and it is green.

## Queue
`wr-s10g-breakdown-rerun` (laptop-scheduler `queues/warehouse-rl.json`) now has a real command. It is not run yet; its dependency, this lane, is now satisfied. The command:
- Re-emits into `fleet/data/s10-breakdown.rerun` with the flags of `wr-s10-disturbance-measure`'s breakdown branch.
- sha256-compares all 10 zone files and exits 1 before touching `fleet/data/s10-breakdown` on any mismatch or a count other than 10.
- Only then moves `truth.json` and `emit_ledger.json` in and removes the temp dir, the old store and `costmap.json`.
- Then runs ingest, costmap `--publish-every 300 --horizon-s 1245`, lessons `--window-h 0.2`, grade `--truth`, and hotspot_score `--tag s10-breakdown --window-h 0.2`.
- All six argvs were dry-parsed and `bash -n` is clean.
- Load: 4 cores, 3 GB, est 10 min, not exclusive.
- The new hotspot_score output overwrites `results/fleet/hotspot_s10-breakdown.json`, which README S10 numbers came from. The rerun's commit must name the new file and the lessons-window change (0.5 → 0.2).
- The builder rewrote the queue file with `json.dumps(indent=1)` and no trailing newline. The scheduler repo already had uncommitted queue edits before this lane.
- **Mechanism check (main loop, after merge; read before reading the rerun's numbers).** The cost map is built so that it probably cannot rank a frozen cell. `fleet/fleet_analyser/hotspot.py:142-145` `counted()`, shared by the cost map and the outcome grader, drops two kinds of stall:
  - Every `faulted_episode` stall, which includes the frozen robot's own `faulted_self` stall.
  - With the default `exclude_occupied=True` (`fleet/costmap.py:48`), every stall whose attributed cell another robot was sitting on. That is exactly a follower queued behind the frozen robot (`blocked_by_faulted`, with `next` = the frozen cell).

  So a breakdown's own stalls never reach the map. Expect `truth_kinds.frozen.k` hits of about 0 on `wr-s10g-breakdown-rerun`, and read a 0 as a structural exclusion, not a detection miss. This repeats the S10 blocked/outage lesson. The one way to measure it fairly would be a separate costmap with occupied stalls included (`fleet/costmap.py --include-occupied` exists, line 4; faulted-episode stalls stay excluded even then, so only followers would count). That is not in the queued command, and the choice is the operator's. I did not run the rerun to confirm the 0.

## Side effects to know (not fixed, by design)
- On future runs whose frozen windows carry cells, these counts shift: time_to_detect false flags, AMOC false-alarm counts, and the S10F gate false alarms. A frozen cell is now truth-positive. Existing results files are unchanged.
- grade.py's docstring ("hot_cell = floor_cells") is stale. `scripts/sprint8_tables.py` does not print frozen cell precision or recall yet.
- README / SCOPE were not edited.

SCHED_RESULT: OK S10G merged PR #42 -> 5fe4501; gate 938+892 OK; wr-s10g-breakdown-rerun command written (not run)

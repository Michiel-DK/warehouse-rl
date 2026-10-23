# wr-lane-s12b-deadlock-gapmap — S12B deadlock finder + WiFi gap map

**Result: MERGED.** PR #46 was squash-merged as `e8a9bb0` and master was fast-forwarded. The review round was clean:
- python-reviewer: pass.
- Refuters: 0 of 5 refuted (correctness, regression, test-honesty, scope-adherence, invariants).
- CI `gate` on ubuntu: `Ran 1010 tests ... OK (skipped=8)`.

Workflow run: `wf_309bd3bd-e75`. Builder: sonnet. The README and SCOPE were not touched.

## What was built
- **`fleet/deadlock.py --glob --run --out [--min-s 30] [--store jsonl:COPY]`** builds a blocking graph for each zone at every batch.
  - The detector decides a cause only once per episode, at the moment the robot turns stuck. So deadlock.py re-applies the detector's rule (faulted > stuck > traffic) at every batch, using `detector._near`.
  - It keeps edges to **all** qualifying neighbours, not only the lowest serial.
  - Deadlock = a strongly connected group of at least 2 robots.
  - Knot = an acyclic chain of at least 2 edges.
  - start = the latest stopped-run start among the members. end = the first batch in which the group is gone.
  - Each deadlock becomes one decision of kind `deadlock`. Its subject is the set of cells.
  - Test D4 checks that deadlock.py agrees with the detector at every `episode_open`.
- **`fleet/emit.py --deadzone "x,y;..."`** is a pure write filter. The headerId still advances, so the ingester sees a gap.
  - truth.json gains `deadzones` and `dropped_messages`, but only when the flag is given.
  - Without the flag, output and truth.json are byte-identical to master (G2, darwin hash).
- **`fleet/gapmap.py --glob --run --out [--top-k 10] [--store jsonl:COPY]`** places each headerId gap on the grid:
  - 0 steps between the cells before and after the gap: the whole gap goes on that cell.
  - 1 step: split in half between the two cells.
  - 2 or more steps: split over the interior cells of a Bresenham line, endpoints excluded.
  - It records the top K cells per zone as `gap_cell` decisions.
- **`fleet/truth.py`** adds the kind `deadzone`. **`fleet/hotspot_score.py`** adds:
  - `truth_kinds.deadzone`, only when the truth file has dead zones; it does **not** join `any`;
  - `gap_grading`, only when the store holds `gap_cell` decisions.
  - Runs without either produce byte-identical output; the builder checked this with `cmp` on s10c-blind.
- **Isolation test:** both new modules are in the required analyst set and contain no banned word.

## Smoke (re-run by the main loop on merged master, 4.0 s total)
| run | deadlocks | knots | deadlock-s per robot-hour | robot-hours | median / max length | max robots | unresolved |
|---|---|---|---|---|---|---|---|
| closed-loop sticky phase A | 163 | 0 | 300.44 | 249.5 | 95 s / 1875 s | 4 | 18 |
| s10c-blind | 56 | 0 | 146.09 | 83.2 | 75 s / 440 s | 3 | 3 |

**Read these with this caveat.** Adjacency (`_near`, Manhattan ≤ 1) is symmetric, and the grid has no odd cycles. So any two adjacent STUCK robots without a faulted neighbour count as blocking each other. A "deadlock" here is therefore a mutually blocked cluster that persists, **not a proven circular wait**. A queue of robots behind a blockage the planner can't see, or behind a floor problem, counts as one. I expect s10c-blind to be mostly that, but this was not measured. A knot needs a faulted robot at its head (a moving head makes the pair mutual), which is why both runs show 0 knots. The operator's "free head" was read as "head with no out-edge". `--min-s 30` filters nothing at the detector default: with start moved back to the stop, every stuck cycle is already ≥ 30 s long.

## Gap map dry run (main loop, /tmp, not a measurement)
I ran the full queue chain at 2 zones × 200 steps with the final dead cells: 50 messages dropped, all placed, `gap_grading` 12 of 12 hits, precision@10 0.6 per zone. 0.6 is the ceiling with 6 cells. The lane's own G3 test (4 cells, small map, darwin) got 4 of 4 in the top 10, precision@10 0.40, which is also the ceiling.

**Dead-cell choice changed during the dry run.** I first ranked cells by dwell (`6,23;16,5;...`). That lost 98 of 103 drops to one robot that sat on a dead cell from step 0. Its gap has no "before" cell, so gapmap reports it as `unplaced_leading_missing` and doesn't place it. The queue now uses the 6 non-adjacent highway cells with the most **arrivals** in s10-none, excluding every step-0 cell: `11,11;10,10;19,20;7,11;14,11;10,20`. Each is arrived at 89–125 times across 10 of 10 zones.

## Queue
`wr-s12b-run` now has a fixed command, which has **not been run** (c4, r3G, est 12 min, needs no go):
- deadlock.py on s10-none, s10c-blind, s10-breakdown and sticky phase A → `results/fleet/deadlock_<tag>.json`;
- emit `fleet/data/s12-deadzone`: s10-none config (10 zones × 500 steps, medium, seed base 0, disturb none) plus the 6 dead cells;
- then ingest → costmap → grade → copy the store to `store-gap` → gapmap → hotspot_score.
- Outputs: `results/fleet/gapmap_s12-deadzone.json` and `results/fleet/hotspot_s12-deadzone.json`.
- `scheduler plan` lists it as waiting on the lane item.

## Open items / caveats for the readme pass and the operator
1. **Truth grading is contaminated on dead-zone runs.** `grade.py --truth`, the `time_to_detect` false flags and the `--baselines` positives treat any non-empty `truth_positive` as a hit. On s12-deadzone, map forecasts on dead cells will grade as "hit": the dry run showed `grading {'truth': {'hit': 2, ...}}` on an undisturbed run. Read `gap_grading` only. Those files were out of scope; filtering them to stall kinds is a follow-up.
2. **Decisions can collapse across zones.** The dedup key `kind:subject:start_iso` has no zone. The same cell with the same first-gap time in two zones collapses to one stored row. The JSON keeps both rows and `store_duplicates` counts the refused ones. The dry run had 0.
3. **Parked robots.** A robot parked on a dead cell that leaves the way it came puts its gap on the neighbouring cell. A robot parked on a dead cell from step 0 can't be placed at all (`unplaced_leading_missing`). Both are documented.
4. **Linux coverage.** G2 has no Linux hash, so it skips there. G3 picks its cells from each platform's own run and is verified on darwin only, though CI ubuntu was green.
5. **The operator's 60 s / 3-robot case** is test D1, and it passes. A strict 3-robot directed cycle is impossible under Manhattan adjacency, so it is satisfied as a 3-robot strongly connected group in a line.
6. **Possible slow paths, not observed.** gapmap's per-missing-id loop could be slow on a corrupt headerId jump. The knot path walk could blow up on fans.

SCHED_RESULT: OK S12B merged PR #46 e8a9bb0 (clean round 0/5 refuted, CI 1010 OK); smoke sticky 163 deadlocks/0 knots/300.44 s per robot-h, s10c-blind 56/0/146.09; wr-s12b-run command written (not run); caveat: grade.py truth hits contaminated on dead-zone runs

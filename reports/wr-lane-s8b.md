# wr-lane-s8b — S8B-HOTSPOT-COSTMAP (13-14 Oct 2026)

- PR: https://github.com/Michiel-DK/warehouse-rl/pull/16, **OPEN, NOT merged**. Head f437a9a, branch
  `worktree-wf_9e86bb15-03b-1`, rebased onto master a0bfb23 (S5C1, PR #15, merged while this lane ran).
- Brief: `reports/wr-lane-s8b-brief.md` (spec + Round 2/3/4 + Pass 2 notes). README.md / docs/SCOPE.md / src/ /
  scripts/ / vendor/ untouched. Master not moved by this lane.
- Verdict: **FAIL**. Pass 2 still refuted 3/5 (correctness, regression, test-honesty). Per the job rule (refuted
  after `pass: 2` -> FAIL with the PR URL) I did not do a main-loop fix round. All three findings are narrow, and each
  has a stated fix (below). A pass 3 is the operator's call.

## Runs
| Run | Result |
|---|---|
| wf_3fb25fd2-719 | HALTED, criterion pre-review: 6 blocking. (1) Sidecar bytes were compared against master. (2) `[]` vs absent nodeStates was ambiguous. (3) An agvPosition test edit was not allowed. (4) The analyst file list was a fixed list, so a new module was ungated. (5) max cost = 1 fails when min_stalls > 1. (6) The precision@K denominator was untested. Rewrite adopted, brief patched. |
| wf_928b6dac-d99 | HALTED, round 2: 2 blocking. **Measured by the reviewer:** with p = [1, 1], a robot facing a floor cell never moves again, so every floor stall is a detector episode and the old coordinate check could not pass. The fix keys the coordinate check on the env's per-step `applied_floor`. The old-schema fallback was also bound to prev/theta. |
| wf_9e3bdef3-02d | HALTED, round 3: 3 blocking (pinned Message-field and upsert-table test sets, the front-cell rule missing from the criterion, the forecast_grades key not pinned). |
| wf_9e86bb15-03b | Stop rule: round-3 rewrite adopted verbatim, `skipCriterionReview`. Built PR #16 (bd3b210). **Refuted 3/5.** Regression: parse_line newly rejected messages master accepts (nodeStates without nodePosition, float coords, null). Test-honesty: new-table schema and decision_grades untouched by truth grading were not tested. Scope: unrequested `random_reference`. Correctness and invariants survived. |
| wf_8fdabd39-e0d (pass 2, priorPasses) | Rebased onto S5C1, all pass-1 findings fixed (mutation results in the PR body). **Refuted 3/5 again** (below). Scope and invariants survived. python-reviewer passed. |

## Pass-2 refutations (open; each is a fix of a few lines plus a test)
1. **correctness**: `forecast_grade.stream_end()` takes the emit ledger's PLANNED end (`t0 + (steps-1)*5` from
   `ingest_runs.emit_config`, upserted at the start of ingest), not the data actually seen. During a live or cut-short
   stream it grades forecasts for time it has no data for. The refuter's repro: data ends at 1000, stream_end is 3600,
   all forecasts graded `0 off`. The same forecast is `2 ok` on the full stream. Grades are written once, so the wrong
   grade sticks. Fix: bound stream_end by the data seen (last transition / message ts). Use the planned end only when
   the emit status is complete and ingest has caught up. Add a test where the planned end is past the last message and
   the forecast must stay open. Batch runs on complete files (the smoke, `wr-s8b-hotspot-score`) are not affected.
2. **regression**: `parse._num` calls `float(v)` on an unbounded JSON int theta (`1e400` as an int literal), which
   raises OverflowError. That escapes parse_line and crashes ingest; master accepts the message. Fix:
   `try/except (OverflowError, ValueError): return None` plus a parse test.
3. **test-honesty**: the outcome-grading tests cannot tell stall start from end and never hit the [P, P+horizon) edges.
   Four boundary mutations stayed green. Fix: one test with stalls starting exactly at P (counts), exactly at P+horizon
   (does not count), and starting before P but ending after it (does not count).
Minor (correctness refuter, outside the criterion): `hotspot_score.main` crashes formatting `recall=None` when a run
has no floor cells.

## Attribution choice
**Next cell.** The emitter now sends VDA 5050 `agvPosition.theta` and `nodeStates` truncated to the first node
(`agent.path[0]` after the step; `[]` when there is no route). `SCHEMA_VERSION` is `fleet-state/2`. A stall message
needs all of the following:
- the same cell and the same theta as the previous message;
- the same non-empty orderId;
- the robot is not faulted;
- the previous message's next node is the cell in front of it.

The stall is attributed to the previous message's next node. That is the cell the robot tried to ENTER, which matches
S8A's enter semantics. Why: without a heading, turns look like skips, and attributing to the current cell would put
every floor skip one cell early. The current-cell fallback applies only to messages with theta but no nodeStates key.
All 282 smoke stalls used "next". The truncation to one node keeps message bytes down for the S5 benchmark budget.

## Smoke (PR head f437a9a; builder's run, numbers read back by me from `/tmp/s8b-smoke/hotspot_smoke.json`)
2 zones x 300 steps on the **medium map** (`/tmp/s8b-smoke/truth.json` env_id `tarware-medium-8agvs-4pickers-globalobs-v1`,
80 floor cells per zone), `{"floor": {"cells": 80, "p": [0.3, 0.7]}}`, file path, 5 commands in 4 s,
`--publish-every 750`. The PR body's remark "smoke is the small map, so not comparable" is wrong: the 0.21 random
reference applies.

| K | precision (mean of 2 zones) | recall |
|---|---|---|
| 20 | 0.950 | 0.238 |
| 40 | 0.775 | 0.388 |
| 80 | 0.538 | 0.538 |
| 120 | 0.358 | 0.538 |

- n_flagged 51 / 59, Spearman(cost, true p) 0.151 / 0.208.
- Zero-stall share 0.456: about 46% of the true floor cells had no stall at all in 300 steps. That is the
  detectability ceiling at this traffic, and it is why recall plateaus at 0.538.
- Random reference: precision ≈ 80/380 = 0.21 on medium.
- Grading: outcome ok 16 / off 51 (110 forecasts open, horizon < 600 s); truth hit 143 / false_alarm 34.
- Anecdote from a 2-zone smoke, not a result: the top-20 cells are mostly real floor cells; recall is capped by cells
  that robots never tried to enter.

## Stalls vs detector episodes (smoke)
13 of 282 stalls fall inside a detector stuck episode: traffic 3, unknown 10, blocked_by_faulted 0. This confirms the
S8A finding: floor skips at p <= 0.7 are short and mostly invisible to the detector. The stall feature is a separate
signal, not a re-read of `stuck_episodes`.

## Tests (on the PR head; gate green: `tests` 492 OK per the regression refuter, `fleet/tests` 240 OK)
New tests are in `fleet/tests/test_fleet_hotspot.py` and `fleet/tests/test_fleet_truth.py`:
- stall rules: next / current / `[]`, replan, gap, faulted, order change, theta change, front cell, runs;
- aggregate: window, no look-ahead, exclusions, exact decay;
- cost map: normalisation per zone, min_stalls;
- hotspot_forecast: dedup;
- grading: outcome and truth, rows coexisting, decision_grades untouched, row-before-stamp, missing truth zone raises,
  grade_run skips hotspot_forecast, CLI `--once --truth`;
- score: precision@K with the 80/120 rule, Spearman, random band;
- schema: DDL == written row keys, engine, `_ver` / `_first` / `schema_version`;
- parser: degrades on bad nodeStates/theta, never rejects; VDA float coordinates;
- analyst isolation: glob over `fleet_analyser/*.py` + CLIs;
- sidecar: floor_cells == env, floor_skips sum, ledger `truth.bytes`, zone bytes == sink files;
- coordinates: p = [1, 1], floor-skip stalls land on floor_cells with attribution "next".

Existing tests were edited by adding members only: the agvPosition keys, "fleet-state/2", the Message field set and the
upsert-table set. The Docker round trip (`integration_fleet_stack.test_stalls_costmap_and_forecast_grades_round_trip`)
is written but **NOT run**: `compose.sh up` failed twice on a wedged `fleet-clickhouse-1` container ("did not receive
an exit event"). The Docker daemon needs a restart before the next integration run.

## Refuter verdicts (opus)
| Pass | correctness | regression | test-honesty | scope | invariants |
|---|---|---|---|---|---|
| 1 (bd3b210) | survives | REFUTED | REFUTED | REFUTED (low) | survives |
| 2 (f437a9a) | REFUTED | REFUTED | REFUTED | survives | survives |

## `wr-s8b-hotspot-score` (only after S8B merges; not runnable from master today)
Mac host, `.venv`, file path, seed base 0:
```
R=fleet/data/s8b-score
.venv/bin/python fleet/emit.py --zones 10 --steps 500 --seed-base 0 --env tarware-medium-8agvs-4pickers-globalobs-v1 --disturb '{"floor": {"cells": 80, "p": [0.3, 0.7]}}' --dir $R --workers ${SCHED_WORKERS:-6}
.venv/bin/python fleet/ingest.py --glob "$R/*.jsonl.gz" --store jsonl:$R/store --once
.venv/bin/python fleet/costmap.py --glob "$R/*.jsonl.gz" --store jsonl:$R/store --publish-every 1250 --out $R/costmap.json
.venv/bin/python fleet/grade.py --run s8b-score --store jsonl:$R/store --once --truth $R/truth.json
.venv/bin/python fleet/hotspot_score.py --run-dir $R --store jsonl:$R/store --tag s8b-medium-80-p03-07
```
Output `results/fleet/hotspot_s8b-medium-80-p03-07.json`, committed with the README number (S8 docs item). Each 500-step
run is 41.7 simulated minutes, so `--publish-every 1250` gives one gradeable publish per zone (horizon 1250 s >= 600).

## What S8C needs from the map
- **Format**: `fleet/data/<run>/costmap.json` =
  `{"schema_version": "fleet-costmap/1", "run", "generated_at" (event-time ISO), "window_hours", "half_life_h",
  "min_stalls", "exclude_occupied", "zones": {"<z>": {"x,y": cost}}}`.
  - Cost is in (0, 1] and only nonzero cells are listed. **Per zone**: each zone has its own seed and floor layout.
  - Coordinates are vendor (x, y): x is the column, y is the row, UP = y-1, the same frame as `agent.x/agent.y` and
    `floor_cells`.
  - ClickHouse: table `costmap` (run, published_at, zone, cell, cost, score, stalls), one row per publish.
- **Refresh cadence**: the router reads the last publish at or before its current event time. The window defaults to 1 h
  with a 1 h half-life. Inside a 500-step episode, publish every 1250 s, or smaller (the planner may want every 600 s).
- **Which map for which episode (S8C design, operator's call):** the floor layout is drawn from (seed, FULL disturb
  config hash). A map built from other seeds therefore describes a different floor and is about as useful as a random
  map. The map must come from the SAME (seed, full disturb config) as the episode it routes. Zone z means seed
  `seed_base + z`, so use the same `seed_base` and the same config; adding breakdown or any other key reshuffles the
  floor (S8A). Two honest designs:
  - a no-map baseline run of the same seed (the "yesterday's data" map), then the map-on run;
  - an earlier window of the same episode feeding the later window.
  Sharing one floor across many episodes would need the floor draw decoupled from the episode seed. That is a
  protected `disturb.py` change.
- Caveats for S8C:
  - Recall is capped by the zero-stall share (about 46% on the smoke).
  - A p = 1 cell is a permanent wall (S8A), and its stall becomes a detector episode, though not a
    `blocked_by_faulted` one, so it is still counted.
  - `next_occupied` stalls (traffic) are excluded by default.

## Hygiene
- The worktree `wf_9e86bb15-03b-1` is checked out at a stale commit b3be23e; the remote branch is at f437a9a. Pass 2
  pushed from its own worktree `wf_8fdabd39-e0d-1`. Pull before any pass 3.
- Main checkout `git status --short` at close: the same 12 untracked files (6 `.pt`, 6 results JSONs) as at lane start; nothing new from builders or refuters.


## Pass 3 (14 Oct 01:00-02:00, loop job; workflow wf_3546ada6-509, record `/tmp/s8b-pass3/result.json`)

- PR https://github.com/Michiel-DK/warehouse-rl/pull/16 **OPEN, NOT merged**. Head **adc1efa** (one commit on f437a9a),
  branch `worktree-wf_9e86bb15-03b-1`, MERGEABLE against origin/master a0bfb23. Master was not moved.
- Run: `single-lane-build` pass 3, tier full, build sonnet, verify opus. `priorPasses` = the pass 1 and pass 2 result
  objects, passed verbatim. Scope was closed to brief section "Pass 3" items 1-4, which I appended to
  `reports/wr-lane-s8b-brief.md`. Criterion (g) was amended and (l) added.
- **Verdict: FAIL, refuted 2/5.** Correctness and test-honesty refuted. Regression, scope and invariants survived.
  The workflow's own label is "ready-for-merge-gate" because 3 of 5 survived. But the job rule (clean round only) and
  the CLAUDE.md merge delegation (every finding fixed and re-verified) both rule out a merge, so I stopped here.

### What pass 3 changed (adc1efa)
1. Outcome grading now grades only fully observed windows. `stream_end` is the last `costmap.published_at`. If there
   is no costmap row it falls back to max(`transitions.ts`, `stalls.end`), and the planned end is used only when the
   store has none of those. A forecast (P, H) is graded iff H >= min_horizon_s and stream_end >= P+H, over the window
   [P, P+H). The pass-2 tests that encoded truncation were rewritten.
2. `parse._num` now catches OverflowError and ValueError and returns None.
3. `TestOutcomeWindow` boundary tests use stall start != end at both window edges. The mutation table is in the PR
   body; the builder ran the mutations, and the test-honesty refuter independently got m1-m4 red.
4. `hotspot_score.main` prints `n/a` when recall is None. This is the one-line guard, with a test.

Gate as reported by the builder: `tests` 497 OK, `fleet/tests` 245 OK. The regression refuter re-ran `fleet/tests`
(245 OK). Its root-gate run overlapped a mutation another refuter was applying in the same worktree (see Hygiene), so
there is no clean refuter run of `tests`. Pass 3 changed nothing under `tests/`.

New tests: TestOutcomeWindow.{test_boundary_stalls_by_start_not_end, test_window_stays_open_until_data_reaches_p_plus_h,
test_stream_end_fallbacks}, TestParserFields.test_integer_theta_too_large_for_a_float,
TestScore.test_main_on_an_empty_floor_prints_na.

### Pass-3 smoke (builder's run; I read these numbers from the PR body and did not re-run it)
Setup: 2 zones x 300 steps on medium, 80-cell config, `--publish-every 750 --horizon-s 745`. Outcome-graded
forecasts: Z0 25, Z1 42; 110 still open. Every zone has at least one grade, as required.

| K | precision | recall |
|---|---|---|
| 20 | 0.950 | 0.237 |
| 40 | 0.775 | 0.388 |
| 80 | 0.537 | 0.537 |
| 120 | 0.358 | 0.537 |

Other numbers:
- Spearman 0.180, zero-stall share 0.456.
- Outcome grades: ok 16 / off 51. Truth grades: hit 143 / false_alarm 34.
- 13 of 282 stalls fall inside a stuck episode.
- Every stall was attributed to the "next" cell.

### Pass-3 refutations (open)
1. **correctness (medium), real, and caused by MY brief.** The Pass 3 item 1 rule, written by me (the lane
   orchestrator) on the advisor's suggestion, sets stream_end = last costmap row. But `build_costmap` writes no rows
   for a publish whose map is empty. So if a run's tail has no stalls, stream_end stops at the last non-empty publish,
   and forecasts whose window was in fact fully observed stay open forever. Those are exactly the ones that should
   grade "off" with outcome 0, so the outcome grades are biased toward forecasts that were followed by stalls.
   - Refuter repro: one stall at t=100, stream to 10000, publish every 1000, H 3600. stream_end comes out at 3000,
     with 0 graded and 3 open.
   - Fix (small): have each publish record its coverage even when the map is empty, either as a per-publish marker
     (a `costmap_publishes` table, or end_ts recorded by build_costmap) or by reading message coverage directly. Add a
     test where the stream's last hour has no stalls and stream_end must equal the last message ts.
   - Effect on `wr-s8b-hotspot-score`: only a zone whose last publish map is empty is affected. That is unlikely
     with 80 floor cells and a 1 h window, but it is not proven.
2. **test-honesty (medium), test-only.** No test tells `graded_at = stream_end` apart from `P+H`, because every
   graded case has stream_end == P+H. The mutation `graded_at=p+horizon` stays green. Fix: grade at a stream_end
   strictly after P+H (for example publish at 4200 instead of 4100) and assert `graded_at` == 4200 on both the
   forecast_grades row and the decision stamp.

Survivors' notes, non-blocking:
- The hotspot_forecast dedup key has no run name, so two runs that share one ClickHouse store and the same
  DEFAULT_T0 collide. This is inherited from S5C1.
- The S5C1 `grade.py --once` output line gains a "; forecasts {...}" suffix. Nothing parses it.
- python-reviewer: the precision print has no None guard. That is not reachable today.

### Refuter verdicts (opus)
| Pass | correctness | regression | test-honesty | scope | invariants |
|---|---|---|---|---|---|
| 1 (bd3b210) | survives | REFUTED | REFUTED | REFUTED (low) | survives |
| 2 (f437a9a) | REFUTED | REFUTED | REFUTED | survives | survives |
| 3 (adc1efa) | REFUTED | survives | REFUTED | survives | survives |

### `wr-s8b-hotspot-score`: still blocked until S8B merges. The command DID change: the costmap step needs `--horizon-s`
Under the pass-3 rule, the default H = 3600 can never be graded inside a 500-step run (the data ends at t0+2495).
With `--publish-every 1250` there are publishes at t0+1250 and t0+2495, and H = 1245 closes the first one exactly at
the data end. The flag already exists, so this is no CLI change. Mac host, `.venv`, file path, seed base 0:
```
R=fleet/data/s8b-score
.venv/bin/python fleet/emit.py --zones 10 --steps 500 --seed-base 0 --env tarware-medium-8agvs-4pickers-globalobs-v1 --disturb '{"floor": {"cells": 80, "p": [0.3, 0.7]}}' --dir $R --workers ${SCHED_WORKERS:-6}
.venv/bin/python fleet/ingest.py --glob "$R/*.jsonl.gz" --store jsonl:$R/store --once
.venv/bin/python fleet/costmap.py --glob "$R/*.jsonl.gz" --store jsonl:$R/store --publish-every 1250 --horizon-s 1245 --out $R/costmap.json
.venv/bin/python fleet/grade.py --run s8b-score --store jsonl:$R/store --once --truth $R/truth.json
.venv/bin/python fleet/hotspot_score.py --run-dir $R --store jsonl:$R/store --tag s8b-medium-80-p03-07
```
If the correctness fix changes how stream_end is computed, re-check this command on a tiny run (>= 1 outcome grade per
zone) before queueing it.

### Hygiene
- I made an orchestrator mistake. While building the workflow args, an unquoted shell heredoc executed the
  backticked commands inside the brief text.
  - `git push --force-with-lease origin HEAD:worktree-wf_9e86bb15-03b-1` ran from the f437a9a worktree. It was a
    no-op ("Everything up-to-date").
  - A `tests` run started; I killed it before the next backticked command, `git add -A`, could run.
  - Verified afterwards: the remote branch was still at f437a9a and nothing was staged. Args are now generated by
    `/tmp/s8b-pass3/gen.py` with a quoted heredoc.
- The refuters shared the worktree `wf_8fdabd39-e0d-1`, and one refuter's mutation run overlapped another's gate run.
  The tree ended clean: `git status` shows only the untracked `vendor`/`.venv` symlinks. Before a pass 4, give the
  refuters separate checkouts.
- `gh pr edit` fails on a Projects-classic deprecation error. The builder updated the PR body with `gh api` PATCH.
- Main checkout: the same 12 untracked files as at lane start.

(pass-3 result line superseded by Pass 4 below) SCHED_RESULT: FAIL S8B PR #16 (https://github.com/Michiel-DK/warehouse-rl/pull/16, head adc1efa) still refuted after pass 3 (correctness: stream_end from last non-empty costmap publish leaves fully observed forecasts open when the tail has no stalls; test-honesty: graded_at=stream_end indistinguishable from P+H); not merged, operator decides

## Pass 4 (14 Oct 10:05-11:30, operator go "A1"; workflow wf_eb472d14-b86, script/args `/tmp/s8b-pass4/gen.py`)

- PR https://github.com/Michiel-DK/warehouse-rl/pull/16 **OPEN, NOT merged**. Head **5c2a17c**, branch
  `worktree-wf_9e86bb15-03b-1`, based on master a0bfb23. origin/master did not move during the run. Master was not
  moved by this lane.
- Run: `single-lane-build` pass 4, tier full, build sonnet, verify opus. `priorPasses` = the pass 1, 2 and 3 result
  objects, passed verbatim. Scope was closed to brief section "Pass 4" (appended to `reports/wr-lane-s8b-brief.md`),
  and criterion (m) was added. Each refuter was told to mutate only in its own `/tmp/s8b-p4-<lens>` worktree. All of
  them report doing so and removing it.
- **Verdict: FAIL, refuted 2/5.** Correctness and invariants are refuted, both with the same finding (below).
  Regression, test-honesty and scope survived. python-reviewer passed. Per the operator's pass-4 rule ("Refuted:
  FAIL, STOP, this PR is then closed by the operator"), I stopped. I did not close the PR myself.

### What pass 4 changed (5c2a17c; builder's report, cross-checked by the refuters)
- `ingest_checkpoints.last_message_ts`: `Pipeline._write_checkpoint` writes the ts of the last ACCEPTED message. It
  lives in the new attribute `_accepted_ts`, which is set after the sequence check and restored on resume as the max
  over the run's rows. The Kafka source uses the same path. The schema gets the CREATE column plus an idempotent
  `ALTER ... ADD COLUMN IF NOT EXISTS`.
- `forecast_grade.stream_end` = max(`last_message_ts`) over the run's checkpoint rows, else None. `planned_end` is
  deleted.
- Outcome rows store `window_end = P+H`. `graded_at` = stream_end on both the row and the stamp. Truth rows carry
  `window_end` None.
- New tests (`TestStreamEndThroughIngest`, real gzip -> Ingester -> store path):
  `test_duplicates_and_rejects_do_not_move_it_and_one_more_accepted_message_does`,
  `test_empty_publishes_after_the_last_stall_do_not_hold_the_stream_end_back` (red on adc1efa),
  `test_a_late_grade_keeps_graded_at_at_the_stream_end_and_window_end_at_p_plus_h`.
  The tests that previously used a costmap publish as the stream end now use a `checkpoint_at` helper; the list is in
  the PR body.
- The operator's three required tests are all present and pass the mutation check.

### Mutation table (builder, PR body; the test-honesty refuter re-ran m3, m4, m5 and m6 plus extra mutants independently, all red)
| mutation | result |
|---|---|
| m1 row `graded_at = window_end` | RED (late-grade test) |
| m2 stamp `graded_at = window_end` | RED (late-grade test) |
| m3 stream_end reverted to adc1efa | RED (6 tests) |
| m4 planned-end fallback | RED (test_stream_end_fallbacks) |
| m5 checkpoint stops writing last_message_ts | RED (3 tests) |
| m6 `_accepted_ts` advanced on duplicates | RED (duplicates/rejects test) |
The test-honesty refuter's extra mutants: resume restore removed, min instead of max, `_latest_ts` instead of
`_accepted_ts`, and `end < p+H` changed to `<=`. All four went RED. Only "drop the run filter in stream_end" stayed
green; the refuter called this non-blocking.

Gate: `tests` 500 OK, `fleet/tests` 248 OK. Two refuters (regression and test-honesty) re-ran both gates in their own
worktrees. **Not run:** the Docker integration test (it was edited), and the ALTER against a real ClickHouse.

### Pass-4 smoke (builder's run, numbers from the PR body; I did not re-run it)
2 zones x 300 steps, medium, 80-cell config, `--publish-every 750 --horizon-s 745`. Outcome-graded forecasts:
Z0 25, Z1 42 (graded 67, open 110).

| K | precision | recall |
|---|---|---|
| 20 | 0.950 | 0.237 |
| 40 | 0.775 | 0.388 |
| 80 | 0.537 | 0.537 |
| 120 | 0.358 | 0.537 |

Other numbers:
- Spearman 0.180, zero-stall share 0.456.
- Outcome grades: ok 16 / off 51. Truth grades: hit 143 / false_alarm 34.
- 13 of 282 stalls fall inside a stuck episode (traffic 3, unknown 10).
- Every stall was attributed to "next".
- The numbers match pass 3: on a complete batch run, the definition change moves no grade.

### Pass-4 refutation (open): the operator's definition, not an implementation slip
**correctness + invariants (both medium): stream_end is one number for the whole run.** It is the max over all zones,
so a zone whose data lags or stops gets its forecasts graded on windows it never observed. Those forecasts count as 0
stalls, and the grade is written once.
- Correctness repro: zone 0 ingested to 2000 and zone 1 to 1000. Z1 forecasts at P=500 and P=1000 (H 600) graded 0.
  Zone 1 data was then appended up to 2000, including a stall at 1050. Both grades stay 0.
- Invariants repro: zone 1 stopped at 1000 and zone 0 ran to 4000. Six Z1 forecasts were graded 0, with window_end up
  to 3600.
- When this can happen: live Kafka (one partition per zone) or continuous file ingest (zones are read one after the
  other). A failed zone process too. It does NOT happen in a complete batch run where every zone reaches the same
  end, which includes the smoke and `wr-s8b-hotspot-score` as long as all 10 zones complete.
- This is what the go text asked for. "Last message the ingester accepted, from any robot" is run-wide, and I briefed
  it as "any robot, any zone". Both refuters say so and route the fix to the operator: track the last accepted ts per
  zone, write the path's zone value into its checkpoint (each file or partition is one zone), take
  `stream_end(store, run, zone)`, and add a two-zone real-ingest test where the lagging zone's forecasts stay open.
  It is about 10 lines plus one test, and it needs the operator's sign-off because it changes the definition.
- Pass 3's stream_end was also run-wide, so this was not introduced in pass 4. It was just not found before.

Survivors' notes, non-blocking:
- **regression:** `forecast_grades.window_end` has no ADD COLUMN migration. Only stacks created from passes 1-3 of
  this PR are affected; the table does not exist on master.
- **test-honesty:** no test pins the run filter in stream_end.
- **python-reviewer:** the ALTER is verified only against the fake server.

### Refuter verdicts (opus)
| Pass | correctness | regression | test-honesty | scope | invariants |
|---|---|---|---|---|---|
| 1 (bd3b210) | survives | REFUTED | REFUTED | REFUTED (low) | survives |
| 2 (f437a9a) | REFUTED | REFUTED | REFUTED | survives | survives |
| 3 (adc1efa) | REFUTED | survives | REFUTED | survives | survives |
| 4 (5c2a17c) | REFUTED | survives | survives | survives | REFUTED |

### Operator choices
1. **Close PR #16** (the pass-4 rule as written).
2. **Accept run-wide stream_end** as the definition for batch scoring. The PR is otherwise clean; record the
   per-zone limitation in the docstring and in S8C's contract. This needs an explicit operator merge, since a
   delegated merge needs a clean round.
3. **Per-zone stream_end** as a pass 5, with the fix the refuters gave.

### `wr-s8b-hotspot-score` (only runs after S8B merges; the CLI is unchanged from the pass-3 command)
Mac host, `.venv`, file path, seed base 0. The order ingest -> costmap -> grade is required. All 10 zones must
complete, otherwise run-wide stream_end grades the short zones on windows they never observed (refutation above).
```
R=fleet/data/s8b-score
.venv/bin/python fleet/emit.py --zones 10 --steps 500 --seed-base 0 --env tarware-medium-8agvs-4pickers-globalobs-v1 --disturb '{"floor": {"cells": 80, "p": [0.3, 0.7]}}' --dir $R --workers ${SCHED_WORKERS:-6}
.venv/bin/python fleet/ingest.py --glob "$R/*.jsonl.gz" --store jsonl:$R/store --once
.venv/bin/python fleet/costmap.py --glob "$R/*.jsonl.gz" --store jsonl:$R/store --publish-every 1250 --horizon-s 1245 --out $R/costmap.json
.venv/bin/python fleet/grade.py --run s8b-score --store jsonl:$R/store --once --truth $R/truth.json
.venv/bin/python fleet/hotspot_score.py --run-dir $R --store jsonl:$R/store --tag s8b-medium-80-p03-07
```
I did NOT re-check `--publish-every 1250 --horizon-s 1245` on a tiny run under the new stream_end. That check was to
follow a merge. Under the pass-4 definition, the grade is reached when the last accepted message ts >= P+H. The last
message is at t0+2495 and the first publish is at first-message + 1250, so P+H = t0+2495 should grade exactly at the
end, but that is unverified.

### Hygiene
- Args were generated by `/tmp/s8b-pass4/gen.py` using quoted heredocs only, and no backticked command executed.
- Refuters used separate `/tmp/s8b-p4-*` worktrees and report removing them.
- Main checkout: the same 12 untracked files as at lane start. No README.md or docs/SCOPE.md edits.

(Superseded by Pass 5 below.) pass-4 result was: FAIL S8B PR #16 (https://github.com/Michiel-DK/warehouse-rl/pull/16, head 5c2a17c) refuted 2/5 after pass 4 (correctness + invariants: operator's run-wide stream_end grades a lagging zone's forecasts on unobserved windows; fix = per-zone stream_end, needs operator sign-off); not merged, operator decides close / accept run-wide / pass 5

## Pass 5 (14 Oct 11:10-13:00, loop; workflow wf_eab457ab-926, args `/tmp/s8b-pass5/gen.py`, record `/tmp/s8b-pass5/result.json`)

- PR https://github.com/Michiel-DK/warehouse-rl/pull/16 **MERGED**, squash commit **56dc46c** on master. Master was
  fast-forwarded in the main checkout (`git log -1`: 56dc46c).
- Run: `single-lane-build` pass 5, tier full, build sonnet, verify opus. `priorPasses` = passes 1-4 (pass 4 = `result`
  of `/tmp/s8b-pass4/result.raw`). Criterion (n) was appended, and brief section "Pass 5" was added to
  `wr-lane-s8b-brief.md`.
- **Verdict: clean round.** 0/5 refuted (correctness, regression, test-honesty, invariants medium; scope high), and
  python-reviewer passed.

### What pass 5 changed (lane head bcc2e5a)
- **Per-zone stream end.** `stream_end[zone]` = the event ts of the last ACCEPTED message from that zone.
  - The zone is `msg.zone`, which is `parse.zone_of(serial)`. It is not the file path or the Kafka partition. The
    Kafka sink keys records by serial, so a partition can mix zones.
  - `Pipeline._accepted_ts` is a `{zone: ts}` map. It is written as JSON to
    `ingest_checkpoints.last_message_ts_by_zone Nullable(String)`, and the schema has an idempotent ADD COLUMN for it.
  - Resume restores the per-zone max. Pass 4's scalar `last_message_ts` is gone.
- **Grading.** `forecast_grade.stream_end(store, run, zone)` requires the zone. There is no run-wide variant and no
  fallback; the scope refuter's grep found no 2-arg call.
  - A forecast for zone z grades only when `stream_end[z] >= P+H`.
  - `graded_at` = `stream_end[z]`, on both the row and the stamp. `window_end` = P+H.
- **New tests (real gzip -> Ingester -> store path), all in `TestStreamEndThroughIngest`:**
  `test_each_zone_grades_on_its_own_end_and_a_late_zone_grades_at_its_own_ts`,
  `test_resume_then_a_new_message_keeps_the_per_zone_map`, `test_zone_is_the_serials_zone_not_the_file`,
  `test_stream_end_is_limited_to_the_run`. The last one covers pass 4's non-blocking run-filter note.
  - Setup: zone A runs to 3000, zone B to 1000, and zone C has no messages; H is 600.
  - At P 1000, A's forecasts grade, and B's and C's stay open.
  - After one B message at 1700, B grades with graded_at 1700 (row and stamp) and window_end 1600.

### Mutation table (builder, run for real; test-honesty refuter re-ran m7, m8 (row-only and stamp-only as well), m10 and extra mutants, all red)
| mutation | result |
|---|---|
| m1 row `graded_at = window_end` | RED (2) |
| m2 stamp `graded_at = window_end` | RED (2) |
| m3 `stream_end` = last costmap publish (adc1efa) | RED (4) |
| m4 planned-end fallback | RED (1) |
| m5 checkpoint stops writing the map | RED (6) |
| m6 `_accepted_ts` advanced on a duplicate | RED (1) |
| m7 gate on the run-wide max over zones | RED (2) |
| m8 `graded_at` = run-wide max | RED (1) |
| m9 zone key from the file, not `msg.zone` | RED (1) |
| m10 resume restores one scalar for all zones | RED (2) |

Test-honesty survivor notes (non-blocking):
- A per-zone ts overwritten unconditionally, instead of max-only, stays green.
- A resume that reads the last row instead of the per-zone max stays green. Every checkpoint row carries the same
  full map, so the two cannot differ today.

### Merge gate (main loop)
- **Rebase.** S5C2 (PR #17, 13097ec) merged during the run and PR #16 went CONFLICTING. I squashed the branch onto
  26d097a and rebased the one commit onto 13097ec.
  - Conflict: `fleet/sql/schema.sql`. Both sides only added tables, so I kept both (the S5C2 `results` table and the
    S8B stalls/costmap/forecast_grades tables).
- **Semantic conflict.** S5C2's new `fleet/tests/test_fleet_dashboard.py::schema()` parses every statement as a CREATE,
  so S8B's ALTER line broke its setUpClass.
  - Fix: filter to `CREATE TABLE` statements. This is the same filter S8B already uses in
    `test_fleet_clickhouse_store.schema_tables()`. It is a one-line test-helper change, and **the refuters did not
    review it**.
- **Diff check.** The squashed diff vs 13097ec equals the reviewed diff bcc2e5a vs 26d097a, except schema.sql (the
  same +/- lines) and the dashboard helper. The only other difference is one context line that S5C2 changed in
  `integration_fleet_stack.py`'s docstring.
- **Gates on the rebased tree (my run):** `fleet/tests` Ran 298 OK, `tests` Ran 564 OK.
- **CI.** The `gate` check passed on 168136b (14m48s) and GitGuardian passed. Merged with
  `gh pr merge 16 --squash --match-head-commit 168136b` and merge state CLEAN.
- **Not run:** the Docker integration tests and the ALTER against a real ClickHouse (same as pass 4).

### Pass-5 smoke (builder's run, numbers from the PR body; I did not re-run it)
2 zones x 300 steps, medium, 80-cell config, `--publish-every 750 --horizon-s 745`.
- Outcome-graded forecasts: Z0 25, Z1 42 (graded 67, open 110).

| K | precision | recall |
|---|---|---|
| 20 | 0.950 | 0.237 |
| 40 | 0.775 | 0.388 |
| 80 | 0.537 | 0.537 |
| 120 | 0.358 | 0.537 |

- Spearman 0.180, zero-stall share 0.456.
- Outcome grades: ok 16 / off 51. Truth grades: hit 143 / false_alarm 34.
- 13 of 282 stalls fall inside a stuck episode (traffic 3, unknown 10). Every stall was attributed "next".
- These are the same numbers as passes 3 and 4. On a complete batch run, per-zone stream_end changes no grade.

### `wr-s8b-hotspot-score` (final; CLI unchanged since pass 3; runnable from master 56dc46c)
Mac host, `.venv`, file path, seed base 0. The order ingest -> costmap -> grade is required. Grading is now per zone,
so a short or lagging zone keeps its forecasts open instead of grading them on windows it never observed.
```
R=fleet/data/s8b-score
.venv/bin/python fleet/emit.py --zones 10 --steps 500 --seed-base 0 --env tarware-medium-8agvs-4pickers-globalobs-v1 --disturb '{"floor": {"cells": 80, "p": [0.3, 0.7]}}' --dir $R --workers ${SCHED_WORKERS:-6}
.venv/bin/python fleet/ingest.py --glob "$R/*.jsonl.gz" --store jsonl:$R/store --once
.venv/bin/python fleet/costmap.py --glob "$R/*.jsonl.gz" --store jsonl:$R/store --publish-every 1250 --horizon-s 1245 --out $R/costmap.json
.venv/bin/python fleet/grade.py --run s8b-score --store jsonl:$R/store --once --truth $R/truth.json
.venv/bin/python fleet/hotspot_score.py --run-dir $R --store jsonl:$R/store --tag s8b-medium-80-p03-07
```
**Checked on master 56dc46c:** I ran the first four steps with `--zones 2` and the rest unchanged, under
`/tmp/s8b-p5-cmdcheck` (since deleted).
- Ingest accepted 12000 messages, with 0 rejected and 0 duplicates.
- Grade: outcome 96 graded / 140 open, truth 236 graded.
- So 1250/1245 does produce outcome grades at 500 steps. I did not run `hotspot_score` in that check, so it wrote
  nothing to `results/`.

### Open risk (builder, recorded in the PR body; outside the operator's definition, not fixed)
- The grading watermark comes from ingest, but the counted stalls are written by `costmap.py`.
- The order ingest -> costmap -> grade is documented, not enforced.
- A stall still open at a zone's stream tail may not exist as a row yet.
- A grade written on either gap stays wrong. Closing this needs a per-zone coverage mark written by costmap, or
  revisable outcome grades; that is an operator decision.
- The batch `wr-s8b-hotspot-score` follows the order, so it is not affected. Live S8C use would be.

### What S8C needs from the map (unchanged from pass 1, plus one point)
Same format and cadence as above. New: S8C must run ingest -> costmap -> grade in that order per cycle (see the
open risk).

### Hygiene
- Refuters worked in their own `/tmp/s8b-p5-*` worktrees and report removing them.
- My merge worktree `/tmp/s8b-p5-merge` is removed.
- Local branch `s8b-p5-merge` is left over: the git-guardrails hook blocks `git branch -D`. It is a leftover, not
  pushed, and safe to delete.
- Main checkout: on master 56dc46c, with the same 12 untracked results files as at lane start. No README.md or
  docs/SCOPE.md edits.

SCHED_RESULT: OK S8B merged PR #16 (56dc46c) after clean pass 5 (0/5 refuted, CI gate green); per-zone stream_end; next item wr-s8b-hotspot-score (command in report)

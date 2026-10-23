# wr-lane-s10f-false-alarm-floor — S10F false-alarm gate (19 Oct 2026)

**Outcome: MERGED.** PR #44 was squash-merged as `ae299d6` on pass 2. Master in `~/code/Michiel-DK/warehouse-rl` was fast-forwarded to it; S10H, PR #43 `a83c9a4`, had landed on master in between.
- Workflow `single-lane-build`, tier standard, build model sonnet.
- Refuters: correctness and test-honesty. scope-adherence and invariants were added automatically.
- Runs:
  - `wf_cf941a16-069`: criterion halt, no build.
  - `wf_8e636595-01b`: pass 1, opened PR #44, round-trip.
  - `wf_386ebe5a-c43`: pass 2, clean.
- Brief: `laptop-scheduler/reports/wr-lane-s10f-brief.md`, with its AMENDMENT. Criterion: `wr-lane-s10f-criterion-v2.txt`.

## What landed (3 files, +877/-7)

### `fleet/costmap.py`
New flags:
- `--gate none|baseline|persistence`, default none.
- `--gate-windows 3`, `--gate-sigma 2.0`, `--gate-min-excess 2`, `--gate-min-count 2`.
- `--reset-forecasts`.

Gate windows are the publish intervals, which do not overlap: (t_{i-1}, t_i], with t_0 = global first_ts - 1. Counts use `hotspot.counted`.
- **baseline:** passes a cell iff c_i > mean + 2·pstdev of the previous 3 windows AND c_i - mean >= 2. Publishes 1-3 are warm-up and pass nothing (`gate_warmup: true`).
- **persistence:** passes a cell iff it is a new entrant in the zone's top-K with count >= 2, OR its count rose by >= 2 since the previous window. Publish 1 is warm-up.

What the gate changes, and what it leaves alone:
- The gate only suppresses forecasts. The cost map, the costmap rows, the stalls and each claim's rank are unchanged.
- A gated claim carries the ungated fields plus `gate`, `gate_reason`, `gate_count` and the baseline or previous-window numbers.
- `--out` gains a `gate` key: name, params, `skipped_not_in_map`, and per-publish `flagged` per zone.
- `--gate` without `--publish-every` exits with an error.
- `--reset-forecasts` drops the run's hotspot_forecast decisions, their update records, their forecast_grades rows and the run's costmap rows, on a jsonl store only.
  - It refuses a store directory whose normalised name is `store`.
  - It reads torn and unparsable lines the way `JsonlStore._load` does.
- A gated rerun without the reset prints one stderr warning, because forecast ids are deterministic and the rerun would otherwise dedupe into the ungated rows.

### `fleet/hotspot_score.py`
- Gains a `gate_grading` block {gate: forecasts, truth_graded, hits, false_alarms, precision, hit_cells, positive_cells, recall, flags_per_zone_publish {max, mean}}.
- The block appears only when a forecast claim of the run has a `gate`. Ungated outputs are byte-identical to base, per the PR body diff on copies of phaseA and s10-none.

### `fleet/tests/test_fleet_costmap_gate.py`
31 tests:
- Synthetic baseline and persistence streams, with values computed by hand.
- `counted()` filter tests (faulted and next_occupied stalls) and window-edge tests. Each was shown to fail under a mutation: counted() deleted, and bisect_left changed to bisect_right.
- `gate_grading` checked field by field.
- reset refusals and torn lines.
- `--gate none` gives a costmap.json `cmp`-identical to the recorded `fleet/data/s10-none/costmap.json`.
- The s10-none flag ceiling.

Data tests read `WR_S10_DATA` and skip when the data is absent, as on CI.

## Numbers (from the PR body; tmp copies, nothing written under the main checkout)

| run | gate | max flags / zone / publish (after warm-up) | total flags | truth hits / graded |
|---|---|---|---|---|
| s10-none (undisturbed) | none (before) | ~26 cells per zone at the last publish | 1391 forecasts | 0 / 1391 |
| s10-none | baseline | 1 | 2 (6 publishes) | — |
| s10-none | persistence | 1 | 5 (8 publishes) | — |
| s10c-blind | baseline | 1 | 5 | 1 / 5 (precision 0.2), hit cells 1 of 50 |
| s10c-blind | persistence | 1 | 9 | 1 / 9 (precision 0.111), hit cells 1 of 50 |

- The default start values met the ≤2 ceiling on the first try (max 1), so none were tuned.
- The s10c-blind smoke (both gates, copy → costmap → grade → hotspot_score) took 5.4 s, against a 120 s limit.

**Read this before the queue run's numbers (my check, from `results/fleet/hotspot_s10c-blind.json`):**
- On the same blind run, the ungated forecasts scored 16 truth hits in 1363 (precision ≈ 0.012).
- The ungated final map's top 20 reached blocked recall 0.34 (17 of 50 cells).
- The gate therefore raises forecast precision roughly tenfold but finds 1 of 50 blocked cells.
- The 0.34 is a different measure (the last map's top 20). On the gate's own measure, distinct (zone, cell) with a truth-hit forecast, the ungated forecasts hit **6 of 50** blocked cells. The gated ones hit **1 of 50**.
  - My read-only count on the original `fleet/data/s10c-blind/store`: 1363 forecasts, hit cells Z1:12,7, Z1:13,2, Z3:17,5, Z3:4,6, Z5:2,23 and Z8:4,8.
  - So the gate removes the false-alarm floor (1347 false alarms down to 4 or 8) and 5 of the 6 detected cells with it.
- **Mechanism:** the baseline warm-up blanks publishes 1-3 (the first ~900 s of a 2495 s run), so a blockage that starts and ends in that span cannot be flagged. Persistence blanks only publish 1 and still hits 1 of 50, so warm-up is not the whole story.
- The S10 blockages last 60-240 s, so most of them start and end inside one or two 300 s windows. A baseline of 3 windows plus an excess of 2 stalls may simply be too slow or too coarse for them.
- That is a question for the operator or the next measurement. This lane does not judge it.

## Review round
- **Criterion pre-review 1 halted:** gate_grading values were not pinned by any test. I adopted the reviewer's rewrite verbatim as v2 and added the hand-computed gate_grading test to the brief.
- **Pass 1 (PR #44, bc9b27d).** Correctness and invariants did not refute. Three findings:
  - test-honesty refuted: `counted()` was never exercised, no stall ended on a window edge, and the zero-flag mean test checked nothing.
  - scope-adherence refuted on the extras.
  - python-reviewer (blocking minor): reset_forecasts crashed on a torn last line.
- **Pass 2 (260c97e).** No refuter refuted (correctness, test-honesty, scope-adherence, invariants, all medium confidence). python-reviewer passed with nits:
  - A non-dict JSON line is kept verbatim, where `_load` would raise.
  - The stdout summary counts a deduped cell as flagged when the reset is missing; the warning covers this.
  - The PR body's sections from pass 1 are stale; the Pass 2 section is current.
- **Scope extras kept, each justified in the PR body:**
  - `gate.name/params` and `skipped_not_in_map`: the brief asked for them.
  - The parameter `p.error` checks and the `build_costmap` ValueErrors: guards for callers outside the CLI.
  - The hotspot_score console print loop was removed.
- **Merge gate, which I ran on PR head 260c97e** in a detached worktree with vendor and .venv symlinked, `WR_STICKY_PHASEA` and `WR_S10_DATA` set:
  - `fleet/tests`: Ran 923, OK.
  - `tests`: Ran 969, OK.
  - No skips in either.
  - CI `gate` and GitGuardian were green.
  - The first attempt at this gate was killed by the 10-minute background limit, so I reran it with a longer limit.

## Queue
`wr-s10f-gate-run` (laptop-scheduler `queues/warehouse-rl.json`) has its command written by the lane. I read it; it has not been run. It is a `set -e` loop over (s10-none, s10c-blind with `--window-h 0.2`; phaseA run `closed_loop` without it) × (baseline, persistence). Each leg:
1. Hashes every file in `$R/store`, then copies `$R/store` to `$R/store-gate-$G`.
2. Runs costmap with `--run $RUN --publish-every 300 --horizon-s 1245 --gate $G --reset-forecasts --out $R/costmap-gate-$G.json`.
3. Runs grade with `--truth`, then hotspot_score with `--costmap $R/costmap-gate-$G.json --tag <tag>-gate-$G`, giving `results/fleet/hotspot_<tag>-gate-$G.json`.
4. Exits 1 if any original store file changed.

It never writes `$R/store` or `$R/costmap.json`. Load: 2 cores, 2 GB, est 15 min, not exclusive.

The `_note` says phaseA's gated numbers use 300/1245 publishes, while the original phase A map was published once, so the two are not comparable.

## Side effects / leftovers
- The pass-2 builder appended a `vendor` line to the main repo's `.git/info/exclude`. It is harmless and local only.
- The scheduler repo's queue file had uncommitted edits from other items before this lane; this lane only replaced the one command and appended to its `_note`.
- `results/fleet/hotspot_s10-breakdown.json` was already modified in the main checkout before this lane. I did not touch it.
- README / SCOPE were not edited.
- The page and docs readers (`wr-dev-s10f-readme`) should quote the recall drop next to the false-alarm drop, not the false-alarm drop alone.

SCHED_RESULT: OK S10F merged PR #44 -> ae299d6 (pass 2); gate 923+969 OK; s10-none gated max 1 flag/zone/publish (was ~26); wr-s10f-gate-run command written (not run); gate recall on s10c-blind 1/50 cells, flagged for the operator

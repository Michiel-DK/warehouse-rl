# wr-lane-s10d — S10D-PERSISTENCE-BASELINE (19 Oct 2026)

**Status: HALTED before merge.** PR #39 (branch `worktree-wf_89967f7a-140-2`, head `41714b9`) is OPEN and not merged;
master is unchanged at `afa7b2b`. The reason is an unresolved test-honesty refutation in round 4. Under the 10 Oct
delegation, an unresolved refutation goes to the operator. The queue item `wr-s10d-baselines-run` was NOT changed and
still holds its placeholder `exit 1`, because the code it needs is not on master.

Brief: `wr-lane-s10d-brief.md`. Criterion: `wr-lane-s10d-criterion.txt`. Workflow: `wf_89967f7a-140`.

## What the PR does (measured on head 41714b9 or 59b4342; the code itself is unchanged since 59b4342)
- **`fleet/baselines.py` (new):** builds two top-K lists per zone and per costmap publish time.
  - The map's top-K is `rank_cells` over the published rows.
  - The persistence top-K takes the same rows' raw `stalls` count, descending, with ties broken on the cell string. It uses
    the same window `(t-W, t]`, the same `counted()` filter and the same `min_stalls` as the map, so decay is the only
    difference between the two lists.
  - Outcome rank reuses `forecast_grade.ranked_zone` and `stream_end`.
  - Truth positives are passed in from `hotspot_score.py`, so `baselines.py` never imports `truth.py` and the truth
    isolation test is unchanged.
  - The module also computes PAI, `chance_all` (the env's 380 highway non-goal cells) and `chance_ever` (cells with at
    least one counted stall in the stream).
  - It computes lesson_persist against three named pools and runs a paired zone bootstrap at K 20 and 40.
- **`hotspot_score.py --baselines`:** adds one trailing `baselines` key.
- **`fleet/baselines.py --smoke --data-dir fleet/data/s8b-score`:** passes in 2.0 s and leaves the store unchanged.
  `--data-dir` is the run dir.

Checked by me:
- **No-flag output:** on s8b-score, master and the branch are equal once `platform` is dropped (True).
- **With the flag:** every non-`baselines` key equals master's (True).
- **Store:** the sha256 of the s8b store is unchanged.
- **Other stores:** closed_loop_sticky and s8e-long store-w0.5 both exit 0. closed_loop_sticky gives `n_units_outcome` 0
  (1 publish, at the end of the stream).
- **Fleet gate on 41714b9:** `discover -s fleet/tests` ran 846 tests, OK (skipped=1, pre-existing).
- **Gate not completed:**
  - `discover -s tests` was stopped by me after the halt and has no result on this head. The builder reported 865 OK on
    59b4342.
  - CI `gate` was pending when I stopped; GitGuardian passed.

### Numbers (from a /tmp run on the PR head, NOT committed; for orientation only)

| run | K | truth precision map / persistence | paired map - pers (CI95) | verdict | outcome verdict |
|---|---|---|---|---|---|
| s8b (10 zones) | 20 | 0.925 / 0.932 | -0.008 (-0.020, +0.005) | within noise | within noise |
| s8b | 40 | 0.791 / 0.814 | -0.023 (-0.034, -0.011) | worse | within noise |
| closed_loop_sticky (30 zones) | 20 | 0.955 / 0.953 | +0.002 (-0.010, +0.017) | within noise | n/a, 0 units |
| closed_loop_sticky | 40 | 0.841 / 0.859 | -0.018 (-0.029, -0.008) | worse | n/a |
| s8e-long w0.5 (3 zones) | 20 / 40 | 0.977 / 0.985, 0.879 / 0.898 | -0.008, -0.019 | worse / worse | beats / beats |

Chance lines:
- `chance_all` is 0.211 on all three runs.
- `chance_ever` is 0.70 on s8b, 0.87 on closed_loop and 0.49 on s8e-long.
- Map lift at K 20 on s8b is 4.39 against all cells and 1.32 against the ever-stalled cells.

lesson_persist on s8e-long w0.5:
- Lift is 2.99 against the window pool (S8S), 3.26 against the ever pool and 9.33 against all cells.
- The S8S pool is not the ever pool (`s8s_pool_is_ever` false).

Read with care:
- The outcome grade re-ranks with the map's own decay, so it leans toward the map.
- s8e-long has only 3 zones.
- The round-4 refutation is exactly that the paired truth-precision delta's sign is untested. These numbers are therefore
  unverified until that test exists.

## Review rounds
1. **wf_89967f7a-140:** the build (Sonnet) opened PR #39. The criterion pre-review was sound, with 5 advisories.
   - The python-reviewer passed it with 3 nits.
   - The correctness, scope-adherence and invariants refuters did not refute.
   - **test-honesty refuted:** the truth wiring (`forecast_steps` -> `truth_positive` in `baselines_block`) was untested,
     and `s1 = s0` survived.
   - Fixed by me in `bcd350b` with an end-to-end v2-truth test through `main`, which kills `s1=s0` and the shifted
     window.
2. **test-honesty re-verify refuted** on 9 survivors:
   - outcome delta sign;
   - lesson_persist `shift=0`;
   - persist bar `>` and `>= 0`;
   - hot_cell filter;
   - bootstrap percentiles 5/95, seed and `N_RESAMPLES`.

   Fixed in `fc38957`; all 9 were killed by my mutation script.
3. **Refuted** on `persist_block=chance -> None` surviving (lesson_persist never asserted through `main`), plus percentile
   interpolation and the early `return empty`. Fixed in `41714b9`. All 12 mutants were killed, and the fleet gate was
   846 OK.
4. **Refuted, high confidence. UNRESOLVED.** No test pins a non-zero `paired[k].truth_precision`. I confirmed that the
   label-delta sign flip survives all 27 tests. Other survivors the refuter reported, which I did not re-run:
   - per-zone hit tally x2;
   - lesson_persist means without `/n` (every lesson test has 1 lesson);
   - `same_pool` overwritten instead of accumulated;
   - empty-pool rate `0.0 -> 1.0`;
   - `params.half_life_h` read from `window_hours` (the test META has both at 1.0);
   - `zone_sort_key` replaced by a constant.

Why I halted instead of a 5th round: each round found a new layer, and the 4th hit the headline verdict
(map vs persistence on truth precision). The pattern is a test file built around single-zone, single-lesson,
equal-set fixtures. Patching one survivor per round is not converging, so the decision belongs to the operator.

## Operator decision
- **Option A, recommended:** a pass-2 lane on the same branch with the refuter's REQUIRED FIX as the brief.
  - Add one `compute` test with at least 2 zones, flagged cells above K at K 20 or 40, and map != persistence per zone.
    Assert the exact `paired[k].truth_precision` mean and verdict.
  - Add one `lesson_persist_block` test with at least 2 hot_cell lessons, different rates, one lesson observed off and
    only one pool matching. Assert exact means and `s8s_pool_is_ever` False.
  - Give `META` a `half_life_h` distinct from `window_hours` and assert `params`.

  This is about 3 tests and is test-only. Then rerun the test-honesty refuter and the full gate.
- **Option B:** merge as is, and accept that the paired-delta sign and the multi-lesson means are covered only by the
  real-data runs above.

After merge, set the queue command to this (written into the queue after the merge, not now). It uses
`--out results/fleet/baselines_<tag>.json` so the committed `hotspot_s8b-medium-80-p03-07.json` is NOT overwritten. The s8b
store on disk now grades differently from that committed file (rank_graded 442 vs 200 there).

```
set -e; P=.venv/bin/python; S=fleet/hotspot_score.py
$P $S --run-dir fleet/data/s8b-score --store jsonl:fleet/data/s8b-score/store --tag s8b-medium-80-p03-07 --baselines --out results/fleet/baselines_s8b-medium-80-p03-07.json
$P $S --run-dir results/closed_loop_sticky/phaseA --store jsonl:results/closed_loop_sticky/phaseA/store --tag closed-loop-sticky --baselines --out results/fleet/baselines_closed-loop-sticky.json
$P $S --run-dir fleet/data/s8e-long --store jsonl:fleet/data/s8e-long/store-w0.5 --tag s8e-long-w0.5 --window-h 0.5 --baselines --out results/fleet/baselines_s8e-long-w0.5.json
$P $S --run-dir fleet/data/s10c-blind --store jsonl:fleet/data/s10c-blind/store --tag s10c-blind --window-h 0.2 --baselines --out results/fleet/baselines_s10c-blind.json
$P $S --run-dir fleet/data/s10-none --store jsonl:fleet/data/s10-none/store --tag s10-none --window-h 0.2 --baselines --out results/fleet/baselines_s10-none.json
```

The last two runs need `wr-s10c-blind-run` and `wr-s10-none-run` first.
- **s10-none:** with no disturbance there are 0 positives everywhere, so truth precision, PAI and lifts come out 0 or null.
  The run still gives the false-alarm floor.

## Facts worth keeping
- 114 of 394 stalled cell strings on s8b lie outside the 380 candidates; that is my count with no filter. The builder
  counted 17 of 634 with `counted()` and per zone. Either way, `chance_ever` can fall below `chance_all`, so the code
  does not assert it.
- With `min_stalls` 1, at K >= n_flagged the two top-K sets are equal and every delta is exactly 0.

## Leftovers
- The lane worktree `.claude/worktrees/wf_89967f7a-140-2` is clean and pushed. I removed the /tmp worktrees.
- My mutation scripts are `/tmp/s10d_mut.py` and `/tmp/s10d_mut2.py`.

SCHED_RESULT: FAIL S10D halted before merge: PR #39 (head 41714b9) OPEN; test-honesty refuted 4 rounds (rounds 1-3 fixed: truth wiring, 9+3 mutants killed; round 4 unresolved: paired truth-precision delta sign + multi-lesson means untested, sign-flip survivor confirmed); fleet gate 846 OK; no-flag output == master, store unchanged, smoke 2.0 s; queue item NOT updated (command proposed in report); operator: pass-2 test-only lane (recommended) or merge as is

# wr-lane-s10e-amoc — S10E AMOC sweep in time_to_detect (19 Oct 2026)

**Outcome: MERGED.** PR #41 was squash-merged as `85df140`, and master in `~/code/Michiel-DK/warehouse-rl` was fast-forwarded to it.
- Workflow: `single-lane-build`, tier standard, build model sonnet, run `wf_697becbe-e4c`.
- Brief: `wr-lane-s10e-brief.md` (including its amendment). Criterion: `wr-lane-s10e-criterion-v2.txt`.

## What landed (only `fleet/time_to_detect.py` and `fleet/tests/test_time_to_detect.py`)
- **New flags.** `--reference DIR`, `--sweep-k`, `--sweep-cost`, for `--truth-kind blocked|outage` only.
  - Usage errors (exit 2): any of the three with floor; any of the three with `--smoke`; `--reference` without a sweep; reference dir equal to `--phase-a` (realpath); bad or duplicate values; nan or inf costs.
- **K sweep.** It runs the unchanged `analyse_windows_k` on the same forecast rows as `by_k`.
- **Cost sweep.** It calls `analyse_windows_k(1, ...)` on rank-1 pseudo rows. These come from the rerun copy's `costmap` rows at publish times with cost >= c. A new `strip_costmap` first removes phase A's own costmap rows from the copy.
- **Reference run.**
  - It goes through one shared helper (`rerun_on_copy`): copy, strip, rerun, hash check, remove. The measured run uses the same helper.
  - It must be a v2 truth with no truth at all.
  - env_id, steps, step_seconds, zone set and publish count must match the measured run, else ValueError naming the field, with no output written.
- **Output.**
  - `amoc` holds `k` and `cost` lists, `k_at_miss_below_half` (walk K ascending) and `cost_at_miss_below_half` (walk cost descending).
  - FA/h = flags / (zones × steps × step_seconds / 3600). Rank is per zone, so the unit is flag-publishes per zone per simulated hour.
  - New meta keys appear only when a sweep is requested.
- **Unchanged paths.** Without the new flags, output and stdout are identical to master. `WINDOW_GOLDEN` was computed on base 7bebef4, and the test-honesty refuter re-ran it against base code: it passes. The existing `FLOOR_GOLDEN` test is unchanged and passes.

## Review round
- **Criterion pre-review, attempt 1: halted** on one blocking item. "Exact stdout" can never match, because the final line carries the wall time and the `--out` path. I adopted the reviewer's rewrite (v2) and relaunched; the v2 pre-review found it sound with 5 advisories.
  - The first launch before that passed placeholder strings by mistake. I stopped it before any build ran, and it left no branch or PR.
- **python-reviewer:** pass, nits only. The v2 check is `is_v1` only; strip_costmap reads the whole file into memory; the K pick is asserted field by field.
- **Refuters (correctness, test-honesty, auto-added scope-adherence and invariants):** none refuted, all at medium confidence.
  - The test-honesty refuter mutated the code five ways (strip removed, `>=` changed to `>`, rank `<=` changed to `<`, the reference publish filter dropped, and others) and each mutation broke the suite.
  - Weak spots it named:
    - FakeRerun stands in for the real costmap subprocess, so the real path is only covered by the smoke below.
    - The reference store has no stale-costmap test of its own (it uses the same helper).

## Evidence (run by me on PR head b9c182c)
- **Gate, `tests`:** `WR_STICKY_PHASEA=<main>/results/closed_loop_sticky/phaseA .venv/bin/python -m unittest discover -s tests` printed `Ran 894 tests ... OK`, with no skips.
- **Gate, `fleet/tests`:** `-s fleet/tests -p 'test_*.py'` printed `Ran 848 tests ... OK`.
- **CI:** GitHub `gate` check passed (16m04s).
- **Smoke.** The queue command, with absolute paths into the main checkout and `--out /tmp/s10e_amoc_smoke.json`:
  - It exited 0 in 5 s wall at load average 11.
  - Both `store/decisions.jsonl` sha256 were unchanged: s10c-blind `3c663adb...`, s10-none `a885ee6e...`.
  - No `store-ttd-*` dir was left behind.
  - Sanity check on the numbers: at K=5 the per-zone FA/h ceiling is 5 × 9 / 0.694 = 64.8, and zone 9 is exactly at it.
- **On merged master:** the module's tests ran `58 tests OK`, and the exact `wr-s10e-amoc-run` argv validates (`[20]`).

Smoke output (this is a preview; the queue item writes the real `results/fleet/amoc_blind.json`):
```
K=20: windows 50, detected 6 (0.120), missed 44, ... first detect s p25/median/p75 218.75/295.0/438.75, false flags per publish 135.1
AMOC K=5:  median delay 475.0 s, miss share 0.940, FA/h ref 59.184,  FA/h measured outside 58.896
AMOC K=10: median delay 402.5 s, miss share 0.880, FA/h ref 109.008, FA/h measured outside 108.288
AMOC K=20: median delay 295.0 s, miss share 0.880, FA/h ref 177.840, FA/h measured outside 175.104
AMOC K=40: median delay 295.0 s, miss share 0.880, FA/h ref 200.304, FA/h measured outside 194.688
AMOC K=80: median delay 295.0 s, miss share 0.880, FA/h ref 200.304, FA/h measured outside 194.688
AMOC cost=0.2: 295.0 s, miss 0.880, FA/h ref 200.304 | cost=0.4: 402.5 s, 0.880, 143.136
AMOC cost=0.6: 537.5 s, miss 0.960, FA/h ref 50.256  | cost=0.8: 475.0 s, 0.980, 37.728
AMOC K at miss share < 0.5: none;  cost at miss share < 0.5: none
```
**What this preview shows.**
- Miss share never drops below 0.5 at any dial. At best 6 of the 50 planner-blind windows are ever flagged.
- At that best point the map raises about 180-200 false flag-publishes per zone-hour on the undisturbed run.
- From K=40 up, and at cost 0.2, every nonzero cell is already flagged (identical rows), so the curve saturates.
- The measured run's false-alarm rate outside windows is within about 3% of the reference's. So the blocked windows add almost nothing to what the map shows.

Treat these numbers as a smoke check, not the measurement. The real numbers come from `wr-s10e-amoc-run`, whose command is valid and not edited. I did not run it.

## Interpretation choices (flagged for the operator)
- **The brief's "`--smoke` on s10c-blind".** I implemented this as the queue command run lane-locally with `--out` under /tmp. `--smoke` itself keeps its meaning: it still rejects `--phase-a`, and the existing test still pins that.
- **Sim hours.** Computed as steps × step_seconds / 3600 = 2500 s, not the 2495 s message span. The stream-end publish counts as a publish.
- **`fa_per_hour_measured_outside_windows`.** It counts flags with no truth of any kind (the S10B false-flag rule).

## Housekeeping
- The main checkout is on `master` at 85df140, and there are no tracked modifications.
- The lane worktree `.claude/worktrees/wf_697becbe-e4c-2` is left in place.

SCHED_RESULT: OK S10E merged PR #41 85df140; gate 894 OK + fleet 848 OK, CI gate pass; smoke 5 s exit 0, stores unchanged; preview: miss share >= 0.88 at every K/cost, FA/h ref 38-200; wr-s10e-amoc-run command valid, not run

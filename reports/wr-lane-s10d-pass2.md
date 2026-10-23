# wr-lane-s10d-pass2 — S10D persistence baseline, pass 2: tests only (19 Oct 2026)

**Status: MERGED.** PR #39 was squash-merged as `02322b1`, and local `master` fast-forwarded to it. The round was
clean: neither refuter (test-honesty, correctness) refuted, and every gate was green on the merged tree.
- Pass-2 commits on the branch: `f1c8a66` (builder) and `0c9fb5c` (my one fix round).
- Workflow: `wf_90eff0f1-36a` (single-lane-build, pass 2, tier standard, build Sonnet).
- Brief: `jobs/wr-lane-s10d-pass2.md`. Pass 1: `reports/wr-lane-s10d-persistence-baseline.md`.

## What changed
Only one file: `fleet/tests/test_fleet_baselines.py`, +239 lines over 41714b9. `fleet/baselines.py` and
`fleet/hotspot_score.py` are unchanged. **No test exposed a defect.**

- **`TestMultiZonePaired` (4 tests)** covers task 1.
  - **Setup:** 5 zones (1, 2, 3, 10, 20), passed to `compute()` as `['1','20','10','3','2']`. Input, numeric and
    string order all differ. Each zone has 45 cells and 2 publishes; K is 20 and 40.
  - **Hand-computed per-zone truth-precision deltas:**

    | K | per-zone deltas | mean | ci95 | verdict |
    |---|---|---|---|---|
    | 20 | [0.5, -0.4, 0.75, 0.25, 0.25] | 0.27 | (-0.09, 0.6) | within noise |
    | 40 | [0.125, 0.05, 0.125, 0.05, 0] | 0.07 | (0.03, 0.11) | beats |

  - **What is pinned:** the ci95 bounds as literal floats, cross-checked against an in-test replay with seed 0,
    1000 resamples and its own percentile. The test does not import `BOOTSTRAP_SEED` or `N_RESAMPLES`.
  - **Why 5 zones and not 3:** with 3 zones the CI sits on the extreme resamples, so it does not depend on zone
    order. A constant `zone_sort_key` mutant would then survive.
- **`TestHalfLifeIsNotTheWindow`** covers task 3.
  - Uses `window_hours` 2.0 and `half_life_h` 0.5.
  - The map's top-K and the persistence top-K differ (map hits 1, persistence hits 0).
  - Asserts the two params separately.
- **`TestLessonPersistMeans` (3 tests)** covers task 2.
  - **Lessons:** 3 hot_cell lessons. Window chances are 0.3, 0.6 and 0.15; observed is ok, off, ok.
  - **Ever rates:** 2/4, 1/3 and 0.0. Zone 2's ever pool is empty.
  - **Pool order:** only the last lesson's own pool equals its ever pool, so `s8s_pool_is_ever` is False.
  - **Pinned values:** chance_window 0.35, chance_ever 5/18, chance_all 0.1, observed_rate 2/3, lift_window (2/3)/0.35,
    lift_ever 2.4, lift_all 20/3, n_lessons 3.
  - **Extra cases:** n_all = 0, and the True branch of `s8s_pool_is_ever`.
- **`test_outcome_tally_accumulates_over_two_publishes_per_zone`** was added in `0c9fb5c`; see round 1.
  - **Setup:** 3 zones, 2 outcome-eligible publishes each, K 1.
  - **Expected:** per-zone outcome delta (1+1)/2 - (0+1)/2 = 0.5; paired outcome `mean=0.5, ci95=[0.5,0.5]`, beats.
  - **Under the mutants:** hits overwritten gives 0, and units overwritten gives 1.

## Review round
1. **The workflow round on `f1c8a66` came back as round-trip.**
   - **Reviewers and refuters:** the python-reviewer failed it, and both refuters refuted with the same single
     survivor. `zt["oh"] += oh` became `zt["oh"] = oh` at `fleet/baselines.py:175`, the per-zone outcome-hit tally
     behind `paired[k].outcome_precision`. Every outcome test had one publish per zone, so overwrite and accumulate
     could not be told apart.
   - **My decision:** this is the same fixture-shape cause as pass 1, one layer over (the outcome side of the tally
     the brief named). It was test-only, so I did one fix round instead of halting.
   - **Fix:** I wrote the test above and pushed `0c9fb5c`.
2. **Re-verify on `0c9fb5c`: both refuters SURVIVE, medium confidence.**
   - **Test-honesty:** re-ran all four mutant scripts (all killed), then tried 19 extra mutants of its own; 15 were
     killed. Its 4 survivors are outside the criterion, and none was a prior-round survivor. See Leftovers.
   - **Correctness:** re-derived the 5-zone deltas, the two-publish outcome test and the lesson means by hand. It
     found no defect in `baselines.py` and confirmed the no-flag path is unchanged.

## Mutation check, on 0c9fb5c, run by me from the branch root (`.venv/bin/python <script>`)
Every mutant is **KILLED**; the count in brackets is the number of failing tests.

`/tmp/s10d_mut.py` (pass 1):

| mutant | result |
|---|---|
| out sign | KILLED (2) |
| shift 0 | KILLED (6) |
| bar > | KILLED (5) |
| bar >=0 | KILLED (7) |
| filter | KILLED (2) |
| pct 5 | KILLED (2) |
| pct 95 | KILLED (2) |
| seed | KILLED (2) |
| n200 | KILLED (2) |

`/tmp/s10d_mut2.py` (pass 1): the same 9 mutants, killed with the same counts, plus:

| mutant | result |
|---|---|
| persist None | KILLED (1) |
| pct no interp | KILLED (1) |
| early empty | KILLED (1) |

`/tmp/s10d_p2/mut3.py` (pass 2, the round-4 survivors):

| mutant | result |
|---|---|
| label_d sign flip | KILLED (1) |
| zone h overwrite | KILLED (1) |
| zone h += 0 | KILLED (1) |
| zone u overwrite | KILLED (1) |
| zone u += 2 | KILLED (1) |
| pooled hits overwrite | KILLED (2) |
| means without /n | KILLED (2) |
| same_pool overwrite | KILLED (1) |
| empty ever rate 1.0 | KILLED (2) |
| empty all rate 1.0 | KILLED (1) |
| half_life from window | KILLED (1) |
| window from half_life | KILLED (1) |
| constant zone_sort_key | KILLED (2) |
| string zone_sort_key | KILLED (2) |

`/tmp/s10d_p2/mut4.py` (round-1 survivors):

| mutant | result |
|---|---|
| zone oh overwrite | KILLED (1) |
| zone ou overwrite | KILLED (1) |

mut4.py, kept here as the brief asks (run from the repo root):
```python
import subprocess, sys
F = "fleet/baselines.py"
M = [("zone oh overwrite", 'zt["oh"] += oh', 'zt["oh"] = oh'),
     ("zone ou overwrite", 'zt["ou"] += 1', 'zt["ou"] = 1')]
orig = open(F).read()
try:
    for name, a, b in M:
        assert orig.count(a) == 1, name
        open(F, "w").write(orig.replace(a, b))
        r = subprocess.run([sys.executable, "-B", "-m", "unittest", "fleet.tests.test_fleet_baselines"], capture_output=True, text=True)
        print(f"{name:18s}", "KILLED" if r.returncode else "SURVIVED", r.stderr.strip().splitlines()[-1])
finally:
    open(F, "w").write(orig)
```
The sign-flip mutant from the brief is `label_d sign flip` in `/tmp/s10d_p2/mut3.py`. It swaps the two terms of
`label_d`, so the delta becomes persistence - map, and it is killed.

## Gates
- **Branch `0c9fb5c`:**
  - `discover -s fleet/tests`: 855 tests, OK (skipped=1).
  - `fleet.tests.test_fleet_baselines`: 36 tests, OK.
  - `discover -s tests` was stopped by the 10-minute background limit before it finished. The builder reported 881 OK
    on `f1c8a66`, and `0c9fb5c` touches only a fleet test.
- **Trial merge of `0c9fb5c` into the new master `7bebef4`:**
  - `discover -s fleet/tests`: 864 tests, OK (skipped=1).
  - `discover -s tests`: 910 tests in 632 s, OK (skipped=1).
  - Master moved during the lane: S10C (PR #40) merged in, and it touches none of the S10D files.
- **CI on PR #39:** `gate` SUCCESS, GitGuardian SUCCESS.
- **No `--baselines` flag:** I ran `fleet/hotspot_score.py --run-dir fleet/data/s8b-score --store
  jsonl:fleet/data/s8b-score/store --tag s8b-medium-80-p03-07` with `--out` pointing to /tmp.
  - **Output JSON:** byte-identical across master `afa7b2b`, the new master `7bebef4`, branch `0c9fb5c` and the trial
    merge (all sha256 `a9c6f256…`).
  - **stdout:** differs only in the echoed `--out` path.
  - **Store:** its file hashes are unchanged before and after.
- **Post-merge on master `02322b1`:** `fleet/baselines.py --smoke --data-dir fleet/data/s8b-score` reports "baselines
  scored in 1.8s, store unchanged".

## Queue item `wr-s10d-baselines-run`
**I did not change it.** Its `command` already equals the pass-1 report's five-run command exactly. I checked this
programmatically: the string compares equal to the five lines joined with ` && ` after `set -e`. The operator queued
it at 11:50. Its outputs are `results/fleet/baselines_<tag>.json`. It was not run here, and it still depends on
`wr-s10c-blind-run` and `wr-s10-none-run`.

## Deviations from the brief and from CLAUDE.md lane args
- **Refuter set:** I passed `verifyLenses` set to correctness and test-honesty. I did not pass `declaredFiles` or
  `repoInvariants` as workflow args; both went into the brief text instead. Either arg would have auto-added a
  scope-adherence or an invariants refuter, and the brief asks for exactly two.
  - **Scope instead:** `git diff --stat 41714b9..0c9fb5c` shows only the test file.
- **Branch handling:** the builder worked on a new local branch and pushed fast-forward to
  `worktree-wf_89967f7a-140-2`. I did not open a new PR.
- **The one fix round (`0c9fb5c`) was mine**, not the builder's.

## Leftovers and advisories
**Test-honesty hardening, not refutations.** Four mutants outside the criterion survive in `fleet/baselines.py`:
1. Dropping the `if zm[z]["u"]` zero-unit guard on `label_d`. A zone with no costmap units would then raise
   ZeroDivisionError instead of being skipped. This is real but untested.
2. Dropping `& set(candidates)` on the positives in `score_units`. Positives outside the candidates are untested.
3. `hotspot.counted(...)` replaced by `True` in `ever_pools`. The exclude_occupied filter on the ever pool is untested.
4. `r["chance"] or 0` on the window rate. This one is probably equivalent.

The refuter's mutant script is `/tmp/th39_m.py`. Covering these would take three small tests, if wanted later.

**Correctness advisory:** `s8s_pool_is_ever` compares a set built by `lessons.STATS` with a set built by
`hotspot.counted`. If the two filters ever diverge, the flag could read False on equal pools. It affects no rate,
and no failing input was found.

**Workspace:**
- The local branch `s10d-pass2-fix` remains, because the git guardrail blocks `git branch -D`. It is fully contained
  in the squash.
- `/tmp/pr39wt` (detached at 59b4342, from pass 1) holds untracked `fleet/data_real`. I left it alone.
- The builder worktree `.claude/worktrees/wf_90eff0f1-36a-2` and the pass-1 worktree `wf_89967f7a-140-2` remain. The
  remote branch was not deleted.
- The main checkout is on `master` at `02322b1`, and the untracked `results/` files are untouched.

SCHED_RESULT: OK S10D pass 2 MERGED (PR #39 squash 02322b1, master ff): tests-only (+239 lines in test_fleet_baselines.py; 5-zone paired delta with pinned CI, 3-lesson pool means, half_life != window, 2-publish outcome tally); baselines.py/hotspot_score.py unchanged, no defect; all 37 mutants killed (mut, mut2, mut3, mut4); refuters test-honesty + correctness survive; merged-tree gates fleet 864 OK, tests 910 OK, CI green; no-flag output byte-identical on s8b-score; queue item wr-s10d-baselines-run already holds the five-run command (unchanged)

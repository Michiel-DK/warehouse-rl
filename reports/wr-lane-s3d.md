# wr-lane-s3d: S3D-WARM-START-RECOVERY, pass 3 (2026-10-13 pm): MERGED

## Status
- PR: https://github.com/Michiel-DK/warehouse-rl/pull/8, **MERGED** (squash). Merge sha **f392164db96cea51f9b261cdb92e5fad457b55ce** on master.
- Branch head before merge: 93001ff. Pass-3 commits:
  - 5cab46f: code and tests
  - 65b94e1: docs and probe
  - 48858fb: doc nit
  - 93001ff: test for the surviving mutant
- `git diff 93001ff f392164` is empty: the squash tree is the tested tree.
- Gate on master after the fast-forward: `Ran 203 tests in 474.958s OK`.
- Sprint 1 regression on master (`evaluate.py --policy cta`, small map, seeds 0-9, 500 steps): per-seed pick-rates identical to `results/fifo_tarware-small-4agvs-2pickers-globalobs-v1.json` (mean 30.53).
- Post-merge steps:
  - `results/recovery_train` was moved to `results/recovery_train_v1_degenerate` in the main checkout. It holds `rate1_seed0` and `rate1_seed1`, both untracked.
  - `results/recovery_train/` no longer exists, so the retrain starts from an empty directory.
  - Smoke and probe `.pt` files were deleted; none are left under `results/`.
  - The 3 refuter worktrees in `/tmp` were removed.
- Not done: the remote branch `worktree-wf_a912e35b-403-2` still exists. `gh pr merge --delete-branch` failed locally because master is checked out in the main checkout, and the git-guardrails hook blocks `git push --delete`. The operator can delete it, which is harmless. The local worktree `.claude/worktrees/wf_a912e35b-403-2` is also left in place.

## What pass 3 changed (operator decision, 13 Oct pm)
- **Per-agent own credit.** Per step k in agent i's window: `r_k = LINE_REWARD * own_i,k - COST_UNIT*call_human_cost*[relocated_i,k]`, plus `COST_UNIT*ABANDON_COST` charged once at an abandon decision.
  - `own_i,k` is entry `aid - 1` of the vector `WarehouseEnv.step` returns, with `RewardType.INDIVIDUAL` and `global_reward=False`. `make_learned_env` asserts both.
  - The vendor credits +1 to the AGV that delivers and +0.1 to the **picker** at whose cell an AGV loads or unloads. The AGV gets nothing for a load or unload (vendor `warehouse.py:539-544, 566-571`). The brief's "+0.1 for the picker and the AGV" was corrected in the docs after the correctness refuter measured it.
  - The fleet-share term is gone.
- **The vendor's constant -0.001 per agent-step (`warehouse.py:674`) is added back, so it is left out of the reward** (the operator's "not adopted" line). The sum is rounded to 9 decimals, so a quiet step is exactly 0.0.
- `reward_constants()` gains `credit: "own"` and `vendor_step_penalty: "excluded"`. `FORMAT_VERSION` stays 2 as the operator instructed.
- Unchanged: `ABANDON_COST` = 15, `RANDOM_SHARE` = 0.1, `DEFAULT_EPISODES` = 3200, `ABORT_BELOW` = 0.5, `abort_after_frac` = `EPS_FRAC` = 0.5.
- The metric is unchanged.
- Protected files are untouched: `git diff 951eca9` over `evaluate.py`, `recovery.py`, `env.py`, `policy.py`, `disturb.py` and `vendor/` is empty.

## Chosen constants and arithmetic (unchanged since pass 1)
- `ABANDON_COST` = 15 stuck-steps, which is 0.01 x 15 = 0.15 reward per abandon decision. 15 is the timeout rule's own abandon threshold: abandoning costs what waiting out the timeout would have cost.
- `random_share` = 0.1. Of the exploratory decisions, 90% follow the timeout rule, so the fleet keeps delivering, and 10% are uniform random, so every action is still tried.
- `DEFAULT_EPISODES` = 3200.
  - The v1 seed-0 run took 7145 s for 6400 episodes, or 1.12 s per episode all-in.
  - 3200 x 1.12 is about 3580 s, about 1.0 h per run, so 9 runs take about 9 h.
  - Rollout alone at 539 steps/s: 3200 x 500 / 539 = 2970 s per run.
  - With the timeout-prior warm start, the training data has deliveries from episode 1.

## Smoke / probe evidence (reported, not judged)
Command: `train_recovery.py --rates 1 --seeds 0 --abort-below 0 --max-intervals 1 --workers 2 --results-dir results/recovery_train_smoke`. It took 57 s. The log is committed as `results/recovery_train_smoke/rate1_seed0/log.json`; pass 2's log is kept as `pass2_rate1_seed0/log.json`.
- **Timeout reference:** 50.112, from 48.96, 46.08, 46.08, 56.16, 53.28.
- **First interval (episode 40, eps 0.977):** greedy eval **1.44** (per seed 2.88, 0, 4.32, 0, 0), mean training return +34.91, 504 rollout steps/s on 2 workers.

`evaluate.py --policy stuck_aware_cta --recovery learned:<ckpt>`, rate 1, seeds 1000 / 1001, from the committed eval JSONs in `results/recovery_train_smoke/eval/`:

| recovery | pick-rate | abandon | reroute | wait | back-off | stuck events |
|---|---|---|---|---|---|---|
| learned, pass 3 own credit, ep 40 (`learned-b70a8a6f70`) | 2.88 / 0.00 | 0 / 0 | 1401 / 1956 | 33 / 11 | 1 / 0 | 1427 / 1967 |
| learned, pass 2 shared reward, ep 40 (`learned-6d94d6ea36`) | 1.44 / 0.00 | 0 / 0 | 1442 / 1996 | 15 / 20 | 5 / 0 | 1461 / 2016 |
| learned, pass 1, ep 40 (attempt-3 report) | 3.60 avg | 0 / 0 | 1391 / 1496 | 39 / 235 | — | 1437 / 1629 |
| timeout | 48.96 / 46.08 | 0 / 2 | 90 / 68 | 407 / 341 | 0 / 0 | 456 / 388 |

At 40 episodes the greedy net still reroutes at about 98% of stuck events under own credit. Per the brief, this is a row, not a verdict. The queued one-run pilot decides.

## Refuter verdicts (pass 3; 3 fresh-context opus verify-gate agents, each in its own detached worktree at 65b94e1)
- **correctness: survives (high confidence).**
  - It recomputed every window's R from the raw hook reward vector on 3 medium-map episodes: 808, 509 and 2745 transitions, with abandons and relocations included. The max difference was 0.0.
  - Every run had `RewardType.INDIVIDUAL` and `global_reward False`. No reward was negative.
  - Gate: 203 OK.
  - Finding: the "+0.1 to the AGV" doc error. Fixed in 48858fb.
- **regression: survives (high confidence).**
  - Protected files untouched; gate 203 OK.
  - The Sprint 1 CTA regression is identical per seed.
  - `run_episode` rollouts at eps 0, 0.3 and 1.0 and the `evaluate.py --recovery learned:` rows are byte-identical to pass 2 (0aa56c3).
  - Note: FORMAT_VERSION stays 2, as the operator instructed. No pass-2 checkpoint exists, and a pass-2 run dir is refused on `--resume` (config mismatch).
- **test-honesty: survives (medium-high confidence).**
  - 13 of 14 mutants went red: sum, divide by n, `own[aid]`, `own[aid%n]`, drop the add-back, broadcast the total, share on top of own (in `run_episode` and in the recorder), drop the assertion, abandon charged twice, STUCK_PENALTY 0.01.
  - The survivor (M7b, dropping only the INDIVIDUAL half of the assertion) is closed by 93001ff. I checked that the mutant goes red.
  - Every README/SCOPE number matches a committed file exactly.
  - It flagged the same doc error as the correctness refuter, also fixed.
- The criterion was not rewritten. The refuters were given the operator's "-0.001 left out" line verbatim with the criterion.

## Next queue items (the retrain is NOT run here)
- Pilot `wr-s3-recovery-pilot` (one run, 3200 episodes, abort grace):
  `.venv/bin/python scripts/train_recovery.py --rates 1 --seeds 0 --workers $SCHED_WORKERS --resume`
- Full retrain, 9 runs, about 9 h, after the operator reads the pilot:
  `.venv/bin/python scripts/train_recovery.py --workers $SCHED_WORKERS --resume`
  - With `--resume`, a finished pilot run is skipped. Checked: `build_config(1, 0, 500, 3200, False)` holds only per-run fields, with no rates or seeds lists and no worker count, and it compares equal between the pilot and the default retrain.
  - An aborted pilot raises and must be deleted first.
- Then `.venv/bin/python scripts/recovery_heldout.py --workers $SCHED_WORKERS`.

---
# Earlier passes, kept for the record

# wr-lane-s3d: S3D-WARM-START-RECOVERY, pass 2 (2026-10-13)

## Status
- PR: https://github.com/Michiel-DK/warehouse-rl/pull/8, **OPEN, NOT MERGED**.
  - Branch `worktree-wf_a912e35b-403-2`, head `0aa56c3`. No merge sha.
  - master is unchanged at `951eca9`.
- **Retrain:** keep `wr-s3-recovery-train` held until the operator decides (see below).
- **Untracked state:**
  - `results/recovery_train/` (v1) was **not** moved, because the lane did not merge.
  - The probe checkpoint `.claude/worktrees/wf_a912e35b-403-2/results/recovery_train_smoke/rate1_seed0/checkpoint.pt` and its `train_state.pt` are kept, untracked, for inspection. The committed eval JSONs name it by sha `6d94d6ea36...`. Delete after the decision.
- Pass-2 commits on the branch:
  - `89a42fc` code + tests;
  - `be7d337` docs + committed probe evidence;
  - `0aa56c3` review nits.
- **Gate:**
  - Full `unittest discover` on `89a42fc`: `Ran 198 tests in 486.170s OK`.
  - After `0aa56c3`, the touched modules (`tests.test_train_recovery`, `tests.test_recovery_heldout`): `Ran 48 tests in 176.989s OK`.
  - The `0aa56c3` change is tests + README only. The full gate was not re-run on it.

## What pass 2 changed (operator decision, 13 Oct)
- **Reward = deliveries + real action costs.**
  - `STUCK_PENALTY = 0.0`; the term stays wired with coefficient 0.
  - `COST_UNIT = 0.01` gives abandon 0.15 per decision and an executed call-human 0.60.
  - `reward_constants()` records `stuck_penalty: 0.0` and `cost_unit: 0.01`.
- **Abort grace.**
  - `abort_after_frac` defaults to `EPS_FRAC` (0.5). It is set with `--abort-after-frac`, and 0 means "check from the first interval".
  - It is stored in `config` and in the `aborted` record.
  - The check runs only at intervals with episode >= frac x episodes. With the defaults that is episode 1600 of 3200.
- **Test-honesty fixes:**
  - A `run_episode`-level bit-identity test against `evaluate.run_seed` timeout on seeds 1000 and 1001. A `random_share=1` variant must differ.
  - An in-process `main --smoke --abort-after-frac 0` on a fabricated degenerate eval, which exits 1 with the record.
  - A default-grace test: no abort at episode 2, abort at 4. With frac 0 it aborts at 2; with frac 1 it aborts at 8.
  - The README numbers come from committed JSONs.
  - Hand mutations: `prior=None` turns the bit-identity test red; `random_share=1.0` turns it red with (33.6, 14, 655) != (52.8, 22, 279).
- **Unchanged:**
  - `FORMAT_VERSION` 2.
  - `ABANDON_COST` 15: the timeout rule's own abandon threshold, so abandoning costs what waiting out the timeout would.
  - `RANDOM_SHARE` 0.1.
  - `DEFAULT_EPISODES` 3200. The v1 seed-0 run took 7145 s / 6400 episodes = 1.12 s per episode all-in, so 3200 episodes ≈ 1.0 h per run and ≈ 9 h for 9 runs. Rollout alone at 539 steps/s is 3200 x 500 / 539 ≈ 2970 s.
  - The regression refuter notes that the 9 h figure is based on v1 timings and is unverified for v2.

## Smoke evidence (probe re-run with the pass-1 command; committed files)
Command: `train_recovery.py --rates 1 --seeds 0 --abort-below 0 --max-intervals 1 --workers 2 --results-dir results/recovery_train_smoke`. Results are in `results/recovery_train_smoke/rate1_seed0/log.json`.
- **Reference: 50.11** (48.96, 46.08, 46.08, 56.16, 53.28).
- **First interval** (episode 40, eps 0.98, 5740 gradient steps, 67 s):
  - greedy eval **1.15**;
  - training return +27.3.
  - Pass 1 for comparison: 3.17 / +21.2. v1: 10.66 / -84.9.

`evaluate.py --policy stuck_aware_cta --recovery learned:<probe ckpt>`, rate 1, seeds 1000/1001. Results are in `results/recovery_train_smoke/eval/`.

| recovery | pick-rate | abandon | reroute | wait | back-off | stuck events |
|---|---|---|---|---|---|---|
| learned, pass 2, episode 40 | 1.44 / 0.00 | 0 / 0 | 1442 / 1996 | 15 / 20 | 5 / 0 | 1461 / 2016 |
| learned, pass 1, episode 40 (attempt-3 report) | 3.60 mean | 0 / 0 | 1391 / 1496 | 39 / 235 | — | 1437 / 1629 |
| timeout | 48.96 / 46.08 | 0 / 2 | 90 / 68 | 407 / 341 | 0 / 0 | 456 / 388 |

**The action mix is still a single action: about 99% reroute.**
- Ad hoc Q check (not committed). `ACTIONS` order: wait, back_off, reroute, abandon, call_human.
  - **On states a timeout-behaviour episode visits** (seed 1000, 497 decisions):
    - argmax counts: wait 351, back_off 89, reroute 49, abandon 5, call_human 3;
    - mean Q: [0.213 0.196 0.192 0.053 -0.324].
  - **On states the greedy net reaches itself** (1462 decisions):
    - argmax reroute 1442;
    - mean Q: [0.150 0.145 0.178 -0.025 -0.481];
    - median top-2 gap 0.011.
- The net roughly follows the prior on the states the prior visits. Once its own reroutes take it to unfamiliar states, a small Q gap picks reroute.

## Refuter verdicts (opus, fresh context, one worktree each, pass 2, priorPasses = attempt-3 report)
- **correctness: REFUTED (medium), on the operator's criterion, not on the code.**
  - Verified the reward: stuck term 0; abandon 0.15 once, to the deciding agent; call-human 0.60 per executed relocation, to the right agent.
  - Verified the grace arithmetic: `>=` at 1600.0, matching where epsilon hits its floor; no off-by-one.
  - Verified resume: a changed frac raises as a config mismatch; an aborted run cannot be continued.
  - Verified the semi-MDP transition form.
  - Tested the hypothesis "short-Delta bootstrap bias favours reroute" by measurement on 2 training-mode episodes:
    - every Q is about 0.2, against a true per-agent value of about 0.5 (systematic underestimation);
    - reroute's TD target is 0.172 against wait's 0.250, so at this stage the Delta structure biases *against* reroute.
  - **Its conclusion:** removing the stuck-penalty dodge did not change the action mix (pass 1 ~95% reroute, pass 2 ~99%). This probe does not support the premise that the dodge was the cause. It cannot rule out an under-trained net either: 40 episodes at eps 0.98, with the shared fleet-deliveries reward giving each agent little signal about its own action.
  - Its required fix: an operator decision.
- **regression: NOT REFUTED (medium-high).**
  - No change to `vendor/`, `evaluate.py`, `recovery.py` or `env.py`.
  - 95 targeted tests OK (Sprint 1 `test_regression_cta` included).
  - Re-evaluating the probe checkpoint reproduced the committed JSON exactly.
  - No script that globs `results/` picks up `recovery_train_smoke/`.
  - CLI defaults match the docs.
  - Doc nit fixed in `0aa56c3`: the v1 2-seed eval is on disk.
- **test-honesty: NOT REFUTED (high).**
  - All 13 listed mutants are killed, as is a `task()` prior=None mutant.
  - The three prior-pass findings (a), (b) and (c) are confirmed fixed.
  - Its non-blocking survivors (`--random-share` plumbing) are fixed in `0aa56c3`. That test fails under both mutants (main dropping the flag; `task()` using the constant).
  - The `# inject:` comment in `test_recovery_heldout` is corrected.

## Operator decision needed
The code implements the 13 Oct decision and is tested. Two refuters are clean. The unresolved item is the pass's own criterion: "the action mix no longer being a single action". It fails at episode 40.

Options:
1. **Accept that a 1-interval probe at eps 0.98 cannot show the action mix, merge, and let the retrain decide.**
   - With the grace, abort is checked from episode 1600 of 3200.
   - A run that still reroutes ~99% will abort there and cost about 0.5 h per run, not the full 1 h.
   - The merge then needs the post-merge steps below.
2. **Change the setup before any retrain.** These are the correctness refuter's suggestions, and both change the reward:
   - per-agent credit instead of the shared fleet-deliveries reward;
   - a reroute cost (which the operator rejected on 13 Oct).
3. **A longer probe first** (e.g. `--max-intervals 40`, about 1600 episodes, roughly 30-45 min on 8 workers, unmeasured for v2). This would show the greedy mix after exploration has decayed, before committing 9 h.

## Retrain command (only after a merge)
```sh
mv results/recovery_train results/recovery_train_v1_degenerate
.venv/bin/python scripts/train_recovery.py --rates 1,2,4 --seeds 0,1,2
```

---
## Previous attempt (attempt 3, 2026-10-12), kept for the record

# wr-lane-s3d: S3D-WARM-START-RECOVERY (2026-10-12)

- PR: https://github.com/Michiel-DK/warehouse-rl/pull/8, **OPEN, NOT MERGED**. Branch `worktree-wf_a912e35b-403-2`, head `376f0fc`. No merge sha.
- master is unchanged at `951eca9`.
- `results/recovery_train/` (v1) was **not** moved, because the lane did not merge. master still runs v1 code, so the v1 dirs remain consistent with it.
- This attempt picked up the earlier work instead of rebuilding it. The PR, tests and docs had already been committed and pushed by the previous attempt, so this run did the review round only.
- Gate on the PR head, run in the lane worktree: `Ran 194 tests in 459.662s OK`.

## Measured warm start (rate 1, run seed 0, temporary dirs, deleted)
I reproduced the PR's probe exactly: `train_recovery.py --rates 1 --seeds 0 --abort-below 0 --max-intervals 1 --workers 2`.
- Timeout reference: **50.11** lines/h (48.96, 46.08, 46.08, 56.16, 53.28).
- First interval (episode 40, epsilon 0.98, 5719 gradient steps): greedy eval **3.17**, training return +21.215. Wall time 60 s.
- `--smoke` (from the PR body, not re-run here): eval 9.50, return +4.31.
- v1's first interval, from `results/recovery_train/rate1_seed0/log.json`: eval 10.656, return -84.89.

**The lane's stated point fails.** The first interval is not near the reference.

## Diagnosis
`evaluate.py --policy stuck_aware_cta --recovery learned:<probe ckpt>` on seeds 1000-1001:

| policy | pick-rate | abandon | reroute | wait | stuck events |
|---|---|---|---|---|---|
| learned (probe ckpt) | 3.60 | 0 / 0 | 1391 / 1496 | 39 / 235 | 1437 / 1629 |
| timeout | 47.52 | 0 / 2 | 90 / 68 | 407 / 341 | — |

- The abandon degeneracy is gone: change 1 works.
- The net now reroutes at about 93-97% of decisions.
- The cause, found by the correctness refuter and consistent with the counts above:
  - `_reroute_stuck` in `recovery.py` resets the StuckCounter.
  - The reward's stuck term only counts `count > 0`.
  - So rerouting avoids the stuck penalty for free. This is the same loophole abandon had in v1, through a different action.
- Refuter's measurement on seed 1000, one episode:
  - always-reroute: 0 deliveries, 0 stuck-busy steps.
  - timeout: 34 deliveries, 555 stuck-busy steps.
  - always-wait: 2 deliveries, 3273 stuck-busy steps.
- The probe net's Q(wait) and Q(reroute) are within 0.05 of each other at every stuck_count.
- Timeout-prior exploration changes the data but not this incentive.

## Refuter verdicts (opus, fresh context, one worktree each)
- **correctness: REFUTED (high).** Reroute is an unpriced way to dodge the stuck penalty, and the default abort makes every retrain run abort at interval 1. The mechanics of all four changes check out: abandon charged once, one RNG draw per decision, abort decided before the log write, version checks, reference compared on resume.
- **regression: NOT REFUTED.**
  - Only the 7 declared files change.
  - The greedy path and the prior=None epsilon-greedy RNG stream are identical to the old code.
  - A v2 checkpoint runs through `evaluate.py`.
  - `test_regression_cta`, `test_recovery`, `test_learned_recovery` and `test_recovery_heldout` pass: 59 tests OK.
- **test-honesty: REFUTED (high).**
  - In `scripts/train_recovery.py:187`, `prior=prior` can become `None`, or `random_share` can be hard-coded to 1.0 at `:188`, and every test stays green. The bit-identical test exercises `LearnedRecovery` directly, never `run_episode`.
  - The 9 other mutants are caught.
  - Every smoke test passes `--abort-below 0`, so a default `--smoke` (which aborts) is untested.
  - The README probe numbers come from temporary dirs with no results file on disk, which breaks CLAUDE.md's "numbers from a results JSON" rule.

## Chosen constants (on the PR branch)
- **`ABANDON_COST = 15`** stuck-steps, the timeout rule's own abandon threshold.
- **`RANDOM_SHARE = 0.1`**.
- **`ABORT_BELOW = 0.5`**.
- **`DEFAULT_EPISODES = 3200`**:
  - v1 seed 0 took 7145 s for 6400 episodes, which is 1.12 s per episode all-in.
  - 3200 × 1.12 ≈ 3580 s ≈ 1.0 h per run, so 9 runs take about 9 h.
  - Rollout time alone: 3200 × 500 / 539 ≈ 2970 s per run.

## Retrain command (do NOT run until the PR is fixed and merged)
```sh
mv results/recovery_train results/recovery_train_v1_degenerate
.venv/bin/python scripts/train_recovery.py --rates 1,2,4 --seeds 0,1,2
```
**The queued `wr-s3-recovery-train` retrain should be held.**
- On master (v1 code), it would retrain the degenerate v1 setup.
- On this PR, every run aborts at interval 1.

## Operator decisions needed
1. **Close the reroute loophole.** This is a reward-design change outside the four specified changes. Options:
   - (a) A per-reroute cost in stuck-steps. Note that the timeout rule itself reroutes about 70-90 times per episode.
   - (b) Redefine the stuck term as "busy and did not move this step" instead of `StuckCounter.count > 0`. This needs `recovery.py` or a wrapper; `recovery.py` is outside this lane's declared files.
   - (c) Behaviour-clone or pretrain Q on the timeout rule before DQN, so interval 1 starts near the reference.
2. **The abort threshold or a grace period**, for example only after epsilon < x.
3. **Fixes to make on the branch in pass 2, whatever the decision:**
   - Add a `run_episode`-level test: `prior="timeout"`, `random_share=0`, epsilon 1 must be bit-identical to `evaluate.py` timeout. Add a `random_share=1` variant that is expected to differ.
   - Add a test that a default-settings `--smoke` exits 1 with an `aborted` record.
   - Write the probe/reference numbers to a results JSON or drop them from the README.

(attempt 3 result) FAIL PR #8 refuted (2/3): greedy net reroutes ~95% of stuck events (reroute resets StuckCounter, dodging the stuck penalty), interval-1 eval 3.17 vs reference 50.11; needs operator reward-design decision

(pass 2 result) FAIL PR #8 pass 2 refuted 1/3 (correctness): reward + grace correct and tested, but greedy probe net still reroutes ~99% of stuck events (operator criterion unmet); operator decides merge-and-retrain vs reward change

SCHED_RESULT: OK

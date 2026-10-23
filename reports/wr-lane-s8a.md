# wr-lane-s8a — S8A-FLOOR-PRESET (13 Oct 2026)

- PR: https://github.com/Michiel-DK/warehouse-rl/pull/12, **MERGED** (squash), merge sha **f694d49**
  (`f694d495cc2dcef37eef4c258b1e5e5a599a9ee2`). Branch `worktree-wf_39f88a79-123-2`, final head 20cba2c.
- Main checkout on `master` fast-forwarded to f694d49. Brief: `reports/wr-lane-s8a-brief.md`.
- **Checkout hygiene:** when I merged, the main checkout was on a **detached HEAD** at 236d241, and the local
  `master` was still at 236d241. The reflog shows `checkout: moving from master to FETCH_HEAD` from another session,
  most likely the concurrent S5 lane checking out a PR. I ran `git checkout master` and `merge --ff-only
  origin/master`. Both pointed at the same commit, so no files changed. If the other session expects a detached
  HEAD, it is now on `master`.
- Six untracked `.pt` files under `results/recovery_train_v*` were there before this lane started. I did not touch
  them; staging was by explicit path only.
- README.md and docs/SCOPE.md were not edited (concurrent-lane rule).

## Read this first (operator / S8B)

1. **A floor skip is invisible to the StuckCounter.** This was observed, not assumed. A floor skip reuses the delay
   mechanism: a NOOP, plus the agent is OR-ed into `_suppressed`. That hides the agent from the vendor's
   `resolve_stuck_agents`. Its count therefore neither increments nor resets, which is how a delay skip behaves.
   - Integration test (CTA, p [1,1], 12 cells, small map, 300 steps): 593 busy floor-skipped agent-steps, with the
     count and position unchanged in every one. The count before each of these steps was 0.
   - Unit test: a counter set to 3 stays at 3 across a floor skip. A plain NOOP by the same agent (the control)
     takes it to 4.
   - **Consequences:**
     - The vendor never replans around a floor cell. A p=1 cell is a permanent wall: 1000-1600 skips per 300
       steps were seen in the correctness refuter's p=[1,1] probes. The presets top out at p=0.6 with a coin
       redrawn every step, so agents get through eventually.
     - **S8B wants to infer floor cells from `stuck_episodes`.** Floor skips produce no StuckCounter signal and no
       `stuck_agents` count. The analyser can only see them as "commanded to move, did not move".
     - The S5 emitter builds its stopped/frozen state from `applied_frozen` only (regression refuter,
       `fleet/fleet_analyser/emitter.py:188`). A floor-skipped AGV currently looks like it is moving normally.
     - Decide before S8B: either the emitter exposes position-unchanged-while-commanded, or the floor skip should
       count in the StuckCounter. The second is a metric-semantics change and the operator's call.
2. **The floor cells depend on the FULL config, as specified.** The floor generator hashes the whole config, so
   floor-alone and floor+breakdown use different floor layouts. The draws of the existing types do NOT depend on
   `floor`. A paired "floor alone vs floor + X" comparison would need a floor seed that excludes the other keys.
   That would be a later change.
3. **Not built here:** the S8 brief also mentions a context-layer registry and contract (`fleet/context/<layer>.py`)
   "built in S8A". This stub's closed file set excluded it, so it is still open for a later lane.

## Decisions

- **Enter, not leave.** A FORWARD move whose target cell (`req_location`, which is not the agent's own cell) is a
  floor cell is NOOPed iff `floor_coin[agent, t] < p_c`.
  - Why: `req_location` is the cell the vendor's move resolution evaluates. Moving into a bad patch is the physical
    event (a wheel slips, or a floor marker is misread on arrival). "Leave" would also fire for agents parked on a
    floor cell.
  - The check runs in `DisturbedWarehouse.resolve_move_conflict` before `super()`. It has to precede super for the
    same reason as the existing NOOPs: `_execute_forward` has no occupancy check.
  - Precedence is frozen > delayed > floor > blocked-cell obstacle. A floor skip is not written into
    `applied_delayed` or `delayed_agents`.
- **Seeding.** The main layer rng is seeded from `config_hash_int` of the config with the `floor` key removed. For
  every config without `floor` that is the same dict, so the draws are bit-identical.
  - Floor has its own generator, `SeedSequence([seed, hash(full config), _SEED_TAG, _FLOOR_TAG])`.
  - Its fixed draw order is: K cells without replacement from `_blockable_cells` (highway, non-goal, sorted), then
    p_c ~ U[lo, hi], then a pre-drawn (agents, steps) coin matrix.
  - Nothing is drawn lazily, so `floor_cells` and `floor_coin` are identical across policies.
- **Exposure, simulator side only.** `DisturbedWarehouse.floor_cells` is a dict `(x, y) -> p_c`. There are also
  `floor_coin` and `applied_floor`, and `info["floor_skips"]`.
  - `evaluate.py` `DISTURB_SUMS` gains `floor_skip_steps`. It is 0 for every disturbed preset without floor, and
    `--disturb none` rows carry no disturbance keys, as before.
  - A grep of src/, scripts/ and fleet/ finds no reader of `floor_cells` or `floor_coin` outside disturb.py.
- Presets `floor-light` = `{"floor": {"cells": 6, "p": [0.05, 0.25]}}` and `floor-heavy` = `{"floor": {"cells":
  12, "p": [0.2, 0.6]}}`. Candidate cells: 248 on the small map, 380 on medium.
- `validate_config` rejects:
  - K = 0, negative, bool, float or str;
  - p with NaN or inf, length other than 2, a non-list, lo > hi, or values outside [0, 1];
  - missing or unknown keys.
  K greater than the number of candidates raises ValueError at reset.

## Regression (the measurement did not move)

`evaluate.py` ran on the PR head 95cc5df; the src at 20cba2c is identical, only tests changed after. The baselines
were computed on master 4402927 before the lane, in `/tmp/s8a_master`. The comparison skips `wall_s`.

The brief's literal command `--policy cta ... --disturb breakdown-light --recovery timeout` **fails on master**:
`ValueError: --recovery needs --policy stuck_aware_cta`. The stored rows in `results/recovery/timeout.json` are
`stuck_aware_cta` with `{"breakdown": {"rate_per_hour": 2, "duration": [20, 60], "agent_types": ["agv"]}}`
(sweep.py `point_spec`), so I compared against that config.

**Rate-2 check:** first master vs the stored file (before the lane), then branch vs the stored file.
```
master   vs stored rate-2 seed 0: 24 common keys, diffs=[]; pick_rate 44.64 vs 44.64, deliveries 31 vs 31
master   vs stored rate-2 seed 1: 24 common keys, diffs=[]; pick_rate 47.52 vs 47.52, deliveries 33 vs 33
branch-vs-stored-timeout.json-rate2 seed 0: 24 common keys equal=True diffs=[] pick_rate 44.64|44.64 deliveries 31|31
branch-vs-stored-timeout.json-rate2 seed 1: 24 common keys equal=True diffs=[] pick_rate 47.52|47.52 deliveries 33|33
```
(keys only on one side: config, point, n_agents, decisions/reroutes_while_blocker_frozen [S3E-era], floor_skip_steps)

**Undisturbed path:** `--disturb none` vs `results/cta_tarware-medium-8agvs-4pickers-globalobs-v1_500.json`.
```
branch-vs-stored-cta-none seed 0: 6 common keys equal=True diffs=[] only_in_one=[] pick_rate 56.16|56.16 deliveries 39|39
branch-vs-stored-cta-none seed 1: 6 common keys equal=True diffs=[] only_in_one=[] pick_rate 59.04|59.04 deliveries 41|41
```

**Every key, branch vs master** (M = medium map, 500 steps, seeds 0-1).
```
cta_M_500 (none)                    seed 0/1: 6 keys equal  ; pick_rate 56.16 / 59.04
cta_M_500_breakdown-light           seed 0/1: 14 keys equal ; pick_rate 47.52 / 48.96   (+floor_skip_steps=0)
cta_M_500_breakdown-heavy           seed 0/1: 14 keys equal ; pick_rate 18.72 / 28.8    (+floor_skip_steps=0)
cta_M_500_delay-10                  seed 0/1: 14 keys equal ; pick_rate 44.64 / 48.96   (+floor_skip_steps=0)
stuck_aware_cta breakdown-light +timeout     seed 0/1: 26 keys equal ; 47.52 / 48.96   (+floor_skip_steps=0)
stuck_aware_cta rate-2 agv config +timeout   seed 0/1: 26 keys equal ; 44.64 / 47.52   (+floor_skip_steps=0)
ALL EQUAL (0 diffs)
```

The opus regression refuter went further. It hashed obs, rewards, actions and the info dict (minus `floor_skips`)
at every step, plus all schedules, for 24 episodes over 300 steps, master vs branch. Cases: blocked_cell, outage,
burst, all five types combined, the router toggle, RuleRecovery with call-human, both informed modes, tuned timeout,
`{}`, the S1 `disturb=None` path, and the learned-recovery env. All identical.

## Tests

`tests/test_disturb_floor.py` (new, 27 tests):
- determinism: cells and coin are identical across random and cta, realised skips repeat for the same policy and
  seed, a different seed gives different draws;
- draws recomputed independently in the spec's order from the separate generator, with and without
  breakdown + burst;
- cells drawn without replacement: K = 248 (every candidate) on small, and K = 12 over 30 seeds;
- every cell is checked against `highways` and `goals` directly;
- the medium map has more than 12 candidates, `floor-heavy` resets on it, oversize K raises, presets;
- `validate_config` rejects and accepts;
- isolation over 6 base configs: frozen, delay, blocked, outage and obstacle schedules and `burst_order` are
  unchanged by adding floor;
- no-floor configs give empty floor state;
- p [0,0] gives zero skips, p [1,1] gives some, and no robot ends a step on a floor cell it entered, under the
  random policy, seed 0;
- `floor_skips` matches `applied_floor`;
- unit semantics:
  - enter skips and counts once;
  - the coin threshold is strict;
  - the coin is read at the executing step;
  - turn, NOOP and toggle never skip;
  - leaving a floor cell is free;
  - frozen or delayed beats floor, and floor beats an obstacle only when the coin hits;
  - a skipped agent is suppressed;
  - `t >= max_steps` is guarded;
- StuckCounter: the integration observation, and the nonzero unit case with a control;
- `evaluate.py` row smoke test, including `--recovery timeout`.

Existing tests changed because the new type and key force it:
- `tests/test_disturb.py:38`: the LANDED set gains "floor".
- `tests/test_recovery_heldout.py`: the committed-row comparison exempts `floor_skip_steps` and asserts it is 0.
  Every other key is still compared for equality (test-honesty refuter checked this).

Gate on 20cba2c: `Ran 274 tests in 521.286s / OK` (master before the lane: 247 OK). The regression refuter also ran
`fleet/tests` on 95cc5df: 22 OK.

## Review rounds

Process: the `single-lane-build` workflow ran twice.
- Run 1 (wf_bce0c296-f25) halted at the criterion pre-review. Its blocking finding: the criterion did not pin
  enter-vs-leave, so a "leave" build would pass. No build started. I applied its suggested rewrite (plus the named
  policy and seed) and tightened the brief.
- Run 2 (wf_39f88a79-123) built PR #12 and ran 5 Sonnet refuters.
- The brief asks for opus refuters, so I then ran three fresh-context opus `verify-gate` refuters by hand.
- The opus test-honesty refutation was fixed on the same branch with one tests-only commit (20cba2c), then re-verified
  by the same refuter. This follows the S3E precedent: a second workflow pass would have opened a second PR.

| Round | Head | correctness | regression | test-honesty | other | gate |
|---|---|---|---|---|---|---|
| workflow run 2 (sonnet) | 95cc5df | not refuted (medium) | not refuted (medium) | not refuted (medium; noted StuckCounter test only sees count 0) | scope-adherence, invariants: not refuted; python-reviewer pass (nits) | 270 OK |
| opus round | 95cc5df | not refuted (medium-high; per-step oracle over 48 runs, 0 mismatches) | not refuted (high; 24 episodes step-hash identical to master) | **REFUTED** (high): mutants M04 floor-from-main-rng-after-burst, M10 coin [a,t+1], M11 replace=True, M15 coin-before-cells, M19 skip-resets-StuckCounter survived | | 270 OK |
| opus re-verify (same refuter) | 20cba2c | | | not refuted (medium-high): 25 mutants RED incl. the 5 former survivors; 2 GREEN are equivalent (M18 reset-clear, M23 own-cell guard: 0 own-cell FORWARD requests in ~27k observed) | | 274 OK |

The PR body lists the builder's own mutants: leave-instead-of-enter, main rng hashed over the full config, skips
written into `applied_delayed`, floor drawn from the main rng, and a lazy coin. All were caught.

Non-refuting notes from the refuters, kept for later:
- Floor and blocked_cell can pick the same cell. While the floor coin hits, floor takes precedence, so the agent is
  suppressed and the stuck-replan it would get from a plain obstacle NOOP is delayed.
- A `call_human` relocation can place a robot on a floor cell without the floor rule firing. Never observed.
- `InformedTimeoutRecovery`'s blocker check uses `frozen_now()` only, so a floor-held blocker counts as "not frozen".
  Delay already behaves the same way.
- A results file that mixes old rows (no `floor_skip_steps`) with new ones is accepted silently. This is harmless
  today, since the value is 0 without floor.

Smoke anecdote, not a result (cta, medium map, 500 steps, seeds 0/1, /tmp only, nothing in results/):
- `floor-light`: pick-rate 56.16 / 43.2, `floor_skip_steps` 2 / 5.
- `floor-heavy`: pick-rate 56.16 / 54.72, `floor_skip_steps` 39 / 19.

## What the next items need

- **`wr-s8a-floor-measure`:** `evaluate.py --policy stuck_aware_cta --env tarware-medium-8agvs-4pickers-globalobs-v1
  --seeds 0-29 --steps 500 --disturb floor-light|floor-heavy --recovery timeout`. `--recovery` requires
  `stuck_aware_cta`, so the "timeout rule" measurement must use that policy. Run the matching `--disturb none` /
  no-recovery baselines for the paired delta.
  - Report pick-rate, `stuck_busy_agent_steps` / (steps × agents), and `floor_skip_steps`.
  - Note: floor skips do not show in the stuck counts (Read-first item 1). Expect the stuck-busy fraction to
    understate the floor's effect; `floor_skip_steps` is the direct measure.
- **S8B:** the emitter sidecar needs `env.floor_cells` (a dict `(x, y) -> p_c`, fixed at reset) as ground truth,
  plus `applied_floor[-1]` per step if the scorer wants per-skip truth. Nothing in the stream may carry them. Resolve
  Read-first item 1 first: floor skips are not stuck episodes today, and the emitter only marks
  `applied_frozen` robots as stopped.
- Later: the context-layer registry and contract (`fleet/context/`), not built here.

SCHED_RESULT: OK S8A floor preset merged (PR #12, f694d49); existing presets bit-identical to master and stored results; gate 274 OK; floor skips are invisible to StuckCounter (flag for S8B)

# warehouse-rl

Can a learned policy make a simulated robot warehouse recover from stuck robots better than a timeout or a hand-written rule? And, as the original question, does a learned task-allocation policy beat the Closest-Task-Assignment (CTA) heuristic on pick-rate?

Environment: [TA-RWARE](https://github.com/uoe-agents/task-assignment-robotic-warehouse) (Edinburgh, MIT).
Metric: pick-rate in order-lines per hour, same map, same seeds, against the CTA heuristic that ships with the env (nearest free AGV per request).

Plan, decision log, review findings and sprint plan: [docs/SCOPE.md](docs/SCOPE.md). Current direction (2026-10-10): Sprint 1 evaluation harness, Sprint 2 disturbance layer and density/failure sweeps with CTA only, Sprint 3 learned stuck-recovery vs timeout vs hand-written rule. Dispatcher learning is optional Sprint 4. Short summary page: https://claude.ai/artifact/33YWuNCVFjQxH3LdYXRbS3

Replay of one CTA episode: open `results/replay_small.html` in a browser (made by `scripts/record_episode.py` + `scripts/replay_template.html`).

## Setup (macOS)

```
./scripts/setup.sh
.venv/bin/python scripts/evaluate.py --policy cta --env tarware-medium-8agvs-4pickers-globalobs-v1 --seeds 0-9 --steps 500
```

`scripts/evaluate.py` is resumable and multiprocess (`--workers`, else `SCHED_WORKERS`, else cpu_count - 2) and writes `results/<policy>_<env>_<steps>.json`. `scripts/throughput.py` measures steps/s per worker and in total.

Hardware this was built on: M1 Pro, 10 cores, 16 GB, CPU only. The env steps at roughly 1,700 steps/s on the small map (500-step episode in 0.3 s), so all training here is local.

## Baselines (CTA heuristic, 10 seeds, 2026-10-09)

| Map | Agents | Pick-rate mean (lines/h) | SD | 95% CI |
| --- | --- | --- | --- | --- |
| medium, global obs | 8 AGV + 4 pickers | 54.4 | 6.9 | 49.5 to 59.4 |
| small, global obs | 4 AGV + 2 pickers | 30.5 | 2.9 | 28.4 to 32.6 |
| small, partial obs | 4 AGV + 2 pickers | 30.5 | 2.9 | 28.4 to 32.6 |

SD is the sample SD (ddof=1) and the CI is a Student-t 95% interval over the 10 seeds, both recomputed with `evaluate.summarise` from the rows in `results/fifo_tarware-medium-8agvs-4pickers-globalobs-v1.json`, `results/fifo_tarware-small-4agvs-2pickers-globalobs-v1.json` and `results/fifo_tarware-small-4agvs-2pickers-partialobs-v1.json`. The SD convention changed from the population SD used in the first version of this table (2.8 and 6.6).

Raw per-episode numbers are in `results/fifo_*.json`; these files predate the rename (the CTA heuristic was called FIFO in this repo before 2026-10-10). The heuristic does not read observations, so partial and global give identical results.

The medium map is the paper's "GTP Small" (Krnjaic et al. 2023), where the paper reports 52.7 lines/h for the same heuristic. At 500 steps one delivery is 1.44 lines/h and the 95% CI over 10 seeds is about +/- 5 lines/h on this map (+/- 2 on small, see the table), so these numbers cannot resolve a 5% effect; Sprint 1 fixes the evaluation length and seed count.

### Evaluation resolution

CTA on medium (8 AGV + 4 pickers, global obs), seeds 0-29, from `results/cta_tarware-medium-8agvs-4pickers-globalobs-v1_500.json`, `_2000.json` and `_5000.json`:

| Episode length | Mean (lines/h) | SD | 95% CI | MDE (abs) | MDE % of mean | Seeds for 5% | s/seed |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 500 | 53.66 | 6.51 | +/- 2.43 | 4.71 | 8.8% | 93 | 1.82 |
| 2000 | 49.39 | 10.60 | +/- 3.96 | 7.67 | 15.5% | 290 | 7.14 |
| 5000 | 47.04 | 14.20 | +/- 5.30 | 10.27 | 21.8% | 572 | 17.75 |

SD is ddof=1 and the CI is Student-t (t = 2.045, 29 df). The minimum detectable effect (MDE) is for two policies at 30 seeds each, two-sided alpha 0.05, power 0.8, normal approximation: MDE = (z_0.975 + z_0.8) * SD * sqrt(2/n) = 2.80 * SD * sqrt(2/30). "Seeds for 5%" is the same formula solved for n per policy: n = 2 * (2.80 * SD / (0.05 * mean))^2. s/seed is the mean `wall_s` per row (one process).

**Decision:** no episode length makes a 5% effect detectable at 30 seeds; at 5000 steps it would take 572 seeds per policy. For the operator: 500 steps needs 93 seeds per policy for the same 5% (about 21 s of compute per policy on 8 workers, against about 21 min for 572 seeds at 5000).

Why SD grows with length: some episodes deadlock and never recover. Seed 4 delivers 33 at both 2000 and 5000 steps; seed 17 freezes at 35 deliveries with 1 stuck and 25 clashes at every length (the built-in recovery never fires); seed 16 collapses between 2000 and 5000. The distribution is bimodal, so the MDE at 2000 and 5000 is driven by about three seeds, not by spread among normal episodes.

**Warm-up for Sprint 2:** no discard (W = 0), and no long episodes. Episodes are deterministic per seed, so each longer run extends the shorter one (deliveries are non-decreasing across lengths for all 30 seeds). On the 25 seeds that do not collapse, the rates per window are 54.4 lines/h (steps 0-500), 51.8 (500-2000) and 53.1 (2000-5000). There is no start-up transient to discard; the falling per-length mean (53.7 to 49.4 to 47.0) comes from deadlocks piling up.

Throughput (`results/throughput.json`, medium, 8 worker processes, 10 episodes x 500 steps, 10 CPUs): 2185.7 steps/s in total, 274.3 steps/s per worker.

## Sprint 2: disturbances, stuck-aware CTA, sweeps

### Sprint 2 results (2026-10-10)

From `results/sweeps/density.json`, `breakdown.json`, `delay.json` and `router.json`: 30 seeds (0-29) per (point, policy), 500 steps, medium map. Mean, SD (ddof=1) and the Student-t 95% CI half-width are computed with `evaluate.summarise` over the 30 seeds; the paired delta is the same summary over the 30 per-seed differences (same seed, same disturbance schedule). Stuck-busy % = sum(`stuck_busy_agent_steps`) / (n_agents x steps) and frozen % = sum(`frozen_agent_steps`) / (n_agents x steps), pooled over the 30 seeds; n_agents counts AGVs and pickers. Abandoned / ep is the mean of `abandoned_tasks` (stuck-timeout drops) per episode. The 8-AGV, rate-0 cell (53.66) is the same number as the S1 500-step evaluation, as it should be.

**a. Density** (CTA, pickers = AGVs / 2):

| Point | Policy | Mean (lines/h) | SD | 95% CI | Stuck-busy % | Frozen % | Abandoned / ep |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2 | cta | 14.45 | 1.63 | +/- 0.61 | 7.9 | 0.0 | 0.00 |
| 4 | cta | 27.50 | 3.47 | +/- 1.30 | 8.9 | 0.0 | 0.43 |
| 6 | cta | 41.33 | 4.57 | +/- 1.71 | 10.0 | 0.0 | 1.27 |
| 8 | cta | 53.66 | 6.51 | +/- 2.43 | 10.7 | 0.0 | 2.87 |
| 10 | cta | 71.47 | 6.56 | +/- 2.45 | 12.6 | 0.0 | 2.97 |
| 12 | cta | 81.36 | 5.24 | +/- 1.96 | 12.4 | 0.0 | 4.33 |
| 14 | cta | 89.66 | 10.60 | +/- 3.96 | 13.1 | 0.0 | 5.90 |
| 16 | cta | 101.18 | 14.39 | +/- 5.37 | 14.3 | 0.0 | 15.10 |

Knee rule: the first AGV count whose mean pick-rate is not below the next grid point's with non-overlapping 95% CIs. There is no knee in 2-16: the mean rises at every step (the smallest step, 12 to 14 AGVs, is 81.36 to 89.66 with CIs that do not overlap), so it does not fall afterwards either. The return per AGV does shrink, from 7.2 lines/h per AGV at 2 AGVs to 6.3 at 16, and at 16 the SD and the abandonments jump (15.1 per episode against 5.9 at 14). That is the start of saturation, not a knee.

**b. Breakdown rate** (8 AGV + 4 pickers, freezes of 20 to 60 steps):

| Point | Policy | Mean (lines/h) | SD | 95% CI | Stuck-busy % | Frozen % | Abandoned / ep | Paired delta vs cta (95% CI) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | cta | 53.66 | 6.51 | +/- 2.43 | 10.7 | 0.0 | 2.87 | |
| 0 | stuck_aware_cta | 53.66 | 6.51 | +/- 2.43 | 10.7 | 0.0 | 2.87 | +0.00 (+0.00 to +0.00) |
| 1 | cta | 51.60 | 5.07 | +/- 1.89 | 11.2 | 3.4 | 4.30 | |
| 1 | stuck_aware_cta | 51.17 | 5.25 | +/- 1.96 | 11.1 | 3.4 | 4.10 | -0.43 (-0.78 to -0.08) |
| 2 | cta | 47.71 | 5.62 | +/- 2.10 | 10.5 | 6.2 | 3.37 | |
| 2 | stuck_aware_cta | 47.47 | 5.83 | +/- 2.18 | 10.6 | 6.2 | 3.37 | -0.24 (-0.49 to +0.01) |
| 4 | cta | 42.10 | 6.64 | +/- 2.48 | 10.6 | 12.8 | 5.93 | |
| 4 | stuck_aware_cta | 42.48 | 6.70 | +/- 2.50 | 10.7 | 12.8 | 5.83 | +0.38 (-0.20 to +0.97) |
| 8 | cta | 33.41 | 4.77 | +/- 1.78 | 10.3 | 22.1 | 6.80 | |
| 8 | stuck_aware_cta | 33.17 | 4.47 | +/- 1.67 | 10.2 | 22.1 | 6.70 | -0.24 (-0.71 to +0.23) |
| 16 | cta | 22.56 | 4.46 | +/- 1.67 | 10.6 | 37.7 | 9.90 | |
| 16 | stuck_aware_cta | 21.89 | 4.17 | +/- 1.56 | 10.5 | 37.7 | 9.90 | -0.67 (-1.55 to +0.21) |

**c. Delay** (8 AGV + 4 pickers; the delayed fraction of robot-time is 5.1%, 10.1%, 20.0% and 29.8% at p_skip 0.05, 0.1, 0.2 and 0.3):

| Point | Policy | Mean (lines/h) | SD | 95% CI | Stuck-busy % | Frozen % | Abandoned / ep | Paired delta vs cta (95% CI) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | cta | 53.66 | 6.51 | +/- 2.43 | 10.7 | 0.0 | 2.87 | |
| 0 | stuck_aware_cta | 53.66 | 6.51 | +/- 2.43 | 10.7 | 0.0 | 2.87 | +0.00 (+0.00 to +0.00) |
| 0.05 | cta | 52.51 | 5.14 | +/- 1.92 | 10.6 | 0.0 | 1.30 | |
| 0.05 | stuck_aware_cta | 52.51 | 5.14 | +/- 1.92 | 10.6 | 0.0 | 1.30 | +0.00 (+0.00 to +0.00) |
| 0.1 | cta | 48.19 | 5.72 | +/- 2.14 | 10.4 | 0.0 | 2.53 | |
| 0.1 | stuck_aware_cta | 48.62 | 5.24 | +/- 1.95 | 10.1 | 0.0 | 1.43 | +0.43 (-0.45 to +1.32) |
| 0.2 | cta | 44.06 | 4.52 | +/- 1.69 | 10.6 | 0.0 | 1.30 | |
| 0.2 | stuck_aware_cta | 44.06 | 4.52 | +/- 1.69 | 10.6 | 0.0 | 1.30 | +0.00 (+0.00 to +0.00) |
| 0.3 | cta | 38.88 | 3.86 | +/- 1.44 | 10.4 | 0.0 | 1.93 | |
| 0.3 | stuck_aware_cta | 38.88 | 3.86 | +/- 1.44 | 10.4 | 0.0 | 1.67 | +0.00 (+0.00 to +0.00) |

**d. Router ablation** (`cta_care` = CTA with `assign_care_for_agents` on):

| Point | Policy | Mean (lines/h) | SD | 95% CI | Stuck-busy % | Frozen % | Abandoned / ep | Paired delta vs cta (95% CI) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2 | cta | 14.45 | 1.63 | +/- 0.61 | 7.9 | 0.0 | 0.00 | |
| 2 | cta_care | 14.40 | 1.77 | +/- 0.66 | 7.9 | 0.0 | 0.03 | -0.05 (-0.22 to +0.12) |
| 4 | cta | 27.50 | 3.47 | +/- 1.30 | 8.9 | 0.0 | 0.43 | |
| 4 | cta_care | 27.74 | 3.09 | +/- 1.16 | 8.1 | 0.0 | 0.33 | +0.24 (-0.48 to +0.96) |
| 6 | cta | 41.33 | 4.57 | +/- 1.71 | 10.0 | 0.0 | 1.27 | |
| 6 | cta_care | 40.46 | 5.42 | +/- 2.02 | 9.1 | 0.0 | 0.93 | -0.86 (-2.42 to +0.69) |
| 8 | cta | 53.66 | 6.51 | +/- 2.43 | 10.7 | 0.0 | 2.87 | |
| 8 | cta_care | 53.52 | 6.82 | +/- 2.55 | 10.1 | 0.0 | 4.17 | -0.14 (-2.24 to +1.95) |
| 10 | cta | 71.47 | 6.56 | +/- 2.45 | 12.6 | 0.0 | 2.97 | |
| 10 | cta_care | 71.23 | 4.52 | +/- 1.69 | 11.5 | 0.0 | 2.73 | -0.24 (-2.22 to +1.74) |
| 12 | cta | 81.36 | 5.24 | +/- 1.96 | 12.4 | 0.0 | 4.33 | |
| 12 | cta_care | 79.87 | 6.45 | +/- 2.41 | 11.5 | 0.0 | 5.57 | -1.49 (-4.50 to +1.53) |
| 14 | cta | 89.66 | 10.60 | +/- 3.96 | 13.1 | 0.0 | 5.90 | |
| 14 | cta_care | 89.52 | 11.85 | +/- 4.42 | 11.9 | 0.0 | 7.63 | -0.14 (-4.13 to +3.84) |
| 16 | cta | 101.18 | 14.39 | +/- 5.37 | 14.3 | 0.0 | 15.10 | |
| 16 | cta_care | 99.65 | 14.22 | +/- 5.31 | 12.0 | 0.0 | 8.87 | -1.54 (-5.78 to +2.71) |

`cta_care` does not differ from CTA at any density: every paired CI contains 0. It lowers the stuck-busy fraction a little at every density from 4 AGVs up (14.3% to 12.0% at 16) without moving the pick-rate.

**Stuck-busy crossing 10% and what stuck-aware CTA recovers.**
- Stuck-busy is at or above 10% at every breakdown rate and every delay probability, **including rate 0**: 10.7% undisturbed, and 10.2% to 11.2% across both grids. The per-seed 95% CI contains 10% at every point except breakdown rate 1 (10.5% to 12.0%), so the threshold is reached by baseline congestion, not by the disturbances. It does not rise with the rate: a frozen robot's stuck counter is suppressed, so a breakdown shows up as frozen time (3.4% to 37.7%), not stuck time. What does rise with the breakdown rate is the stuck-timeout abandonments, 2.87 per episode at rate 0 to 9.90 at rate 16. Lowest rate above 10%: rate 0 for breakdown and for delay on the point estimate. That is at the threshold rather than clearly above it; only breakdown rate 1 is distinguishably above.
- Share of the CTA pick-rate loss against rate 0 that stuck-aware CTA recovers (paired delta / loss). Breakdown: -21% at rate 1 (loss 2.06, delta -0.43, CI -0.78 to -0.08: significantly worse, one of five tests), -4% at 2, +3% at 4, -1% at 8 and -2% at 16; the other four CIs contain 0. Delay: not applicable by construction. The frozen filter only acts on frozen robots and delay never freezes one, so the pick-rate is identical to CTA on every seed at p_skip 0.05, 0.2 and 0.3; at 0.1 it differs only through the abandonment path (+0.43, CI -0.45 to +1.32).

**Decision.**
- (a) The 10% stuck regime exists at every plausible rate. For breakdown that is 1 to 2 per robot-hour, which freezes 3.4% to 6.2% of robot-time; rates 8 and 16 freeze 22% and 38% of the fleet, which is not a fleet that is operating. For delay it is any p_skip, because stuck-busy is flat in it. The Exit rule's "recovery is moot" branch does not trigger and Sprint 3 recovery stands. The stuck time is present without any disturbance and does not grow with the rate, so the premise that *disturbances* produce the stuck regime is not supported. Most of it is a floor whose source is unverified (see below); that fork is flagged to the operator.
- (b) The frozen filter alone recovers none of the disturbance loss: between -21% and +3% of the breakdown loss, with every paired CI containing 0 except a small loss at rate 1.

**What "robots get stuck" means in this sim.** A robot is counted stuck-busy on a step when its `StuckCounter` is above 0. That means it has a mission, its requested action is not a turn and not a load toggle away from a goal, and it did not change cell. So NOOP waits and loading at a goal count, not only blocked moves (`resolve_stuck_agents` in `vendor/tarware/tarware/warehouse.py`). On the medium map with 8 AGVs and 4 pickers that is 10.7% of robot-time with no disturbance at all, and it grows with fleet size, from 7.9% at 2 AGVs to 14.3% at 16. Failure does not drive it, because it is flat across every breakdown and delay rate. Congestion is not the main part either. There is a 7.9% floor with only 3 robots on the map, and density adds 6.4 points from 2 to 16 AGVs (2.8 points at 8). The floor most likely includes structural waits such as AGV-picker handoffs and unloading, but these rows cannot split it by agent type or action, so its source is UNVERIFIED. The stuck time is mostly short waits: the env replans after 5 stuck steps and drops the mission at the timeout, and that happens only 2.87 times per 500-step episode at 8 AGVs. Injected breakdowns do not add stuck time; they take capacity away. A broken-down robot is frozen, not stuck, and the pick-rate falls almost linearly with the frozen fraction (53.66 to 22.56 lines/h as frozen time goes from 0% to 37.7%). Delays also cost capacity rather than stuck time: stuck-busy stays at 10.4% to 10.6% while the pick-rate falls to 38.88 at p_skip 0.3. Routing around other robots (`cta_care`) and never dispatching to a frozen robot (stuck-aware CTA) both leave the pick-rate where it was. Whatever recovery can win has to come from the busy robot that is waiting or blocked (replan, back off, return the shelf), not from the dispatch. Waits that are handoffs are out of recovery's reach, so the recoverable part of the 10.7% is smaller than 10.7%, by an amount these rows do not measure.

### Disturbance taxonomy (`src/warehouse_rl/disturb.py`)

`DisturbedWarehouse` subclasses the vendor env; `{}` means no disturbance. All schedules are drawn at reset from the (seed, config) pair only, so they are identical across policies (common random numbers). One step is 5 s; rates are onsets per robot-hour (per map for the map-level types).

- **breakdown**: the robot is frozen for a uniform number of steps (all its micro-actions become no-ops). "Stuck" is modelled as a freeze: a symptom, not a cause.
- **delay**: the robot skips a step with probability `p_skip` (execution delay). A delayed robot is not frozen.
- **blocked cell**: a highway cell becomes impassable for a while; planning avoids it and moves into it are cancelled.
- **burst**: extra requests enter the queue for a window of steps.
- **outage**: a goal station becomes impassable and AGVs cannot be sent there.

### Baselines

- **CTA** (`CtaPolicy`): the vendor heuristic, ported step by step. Unchanged by this sprint.
- **Stuck-aware CTA** (`StuckAwareCtaPolicy`): CTA with two changes. (1) A NEW AGV assignment never goes to an AGV that the layer has frozen for the step about to execute (current step only, no look-ahead) or to an AGV that abandoned its mission in the same call. (2) When the env's stuck timeout drops a PICKING mission (robot not carrying, not at the pick location), the item is released in that call and goes to the closest eligible AGV; if none is eligible it stays queued and unassigned until the next call. Idle AGVs are never excluded by their stuck counter.
- **Fence**: pickers keep CTA's static zones, and an AGV that freezes mid-mission keeps its order, because `act()` cannot cancel a busy path stored in the env. Cancelling is the recovery layer's job (Sprint 3). A mission whose path was empty when the env accepted it never becomes busy and is outside the abandonment rule (existing CTA behaviour).

### Sweeps (`scripts/sweep.py`)

All sweeps: 30 seeds (0-29), 500 steps, warm-up W = 0 (no discard), seed-paired under common random numbers, run on the disturbance layer so every row carries the frozen, stuck, abandoned and clash sums.

| Axis | Setting | Grid | Policies |
| --- | --- | --- | --- |
| a. density | medium map, AGVs (pickers = AGVs / 2) | 2, 4, 6, 8, 10, 12, 14, 16 | cta |
| b. breakdown rate | medium, 8 AGV + 4 pickers, AGV breakdowns, duration 20 to 60 steps | 0, 1, 2, 4, 8, 16 onsets per robot-hour | cta, stuck_aware_cta |
| c. delay | medium, 8 AGV + 4 pickers | p_skip 0, 0.05, 0.1, 0.2, 0.3 | cta, stuck_aware_cta |
| d. router ablation | density grid of (a) | as (a) | cta, cta_care |

The router-side toggle in (d) is `assign_care_for_agents` (`DisturbedWarehouse` and `WarehouseEnv`, default False): when True, the path the env computes on accepting a macro action treats other agents as obstacles. The policy's own distance estimate is not changed. `cta_care` is CTA with the toggle on.

Command (smoke test: add `--smoke`, which runs seeds 0-1 and the two endpoints of each grid; `--only a,b,c,d` selects sweeps):

```sh
.venv/bin/python scripts/sweep.py --workers N
```

Output: `results/sweeps/<sweep>.json` (`<sweep>_smoke.json` for smoke), written after every row, one row per (point, policy, seed), skipped on re-run; and `results/sweep_<sweep>.png` (PNGs are not committed). Plots show the mean per policy with a Student-t 95% CI band; the breakdown and delay plots add the seed-paired difference stuck_aware_cta - cta and the frozen and stuck fractions of robot-time.

`scripts/evaluate.py --policy stuck_aware_cta ... --disturb PRESET|JSON` runs the same policy on a single configuration and prints the seed-paired delta against the CTA file with the same disturbance tag.

### Disturbed replay

`results/replay_disturbed.json` is one episode on the small map (seed 0, preset `breakdown-heavy`, `stuck_aware_cta`), recorded with `scripts/record_episode.py --disturb breakdown-heavy --policy stuck_aware_cta --out results/replay_disturbed.json`. Frames carry a per-agent `fz` flag (frozen); `scripts/replay_template.html` ignores it.

## Sprint 3: recovery baselines

### Sprint 3 results: recovery baselines (2026-10-10)

Data: `results/recovery/timeout.json`, `tuned_timeout.json`, `rule.json` and `call_human.json`, written by `scripts/recovery_sweep.py`. The rate-0 reference is `stuck_aware_cta` at point 0 in `results/sweeps/breakdown.json`. Every row has 30 seeds (0-29) per (rate, policy). Runs are 500 steps on the medium map with 8 AGVs and 4 pickers. The dispatcher is `StuckAwareCtaPolicy` throughout. Breakdowns hit AGVs only and freeze them for 20 to 60 steps, with the same schedule as Sprint 2. Statistics are computed as in Sprint 2:
- Mean, SD and Student-t 95% CI come from `evaluate.summarise`.
- The paired delta is against `timeout` on the same seed and the same disturbance schedule.
- Fractions of robot-time are pooled over 12 robots x 500 steps x 30 seeds.
- Abandoned / ep is the mean of `abandoned_tasks`.

`timeout` reproduces the Sprint 2 `stuck_aware_cta` breakdown rows seed for seed (same pick_rate on all 120 episodes), and `tuned replan 5 abandon 15` reproduces `timeout`, so the deltas below are against the env default.

**a. TimeoutRecovery (env default: replan after 5 stuck steps, abandon after 15):**

| Rate | Policy | Mean (lines/h) | SD | 95% CI | Paired delta vs timeout (95% CI) | Stuck-busy % | Frozen % | Abandoned / ep |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | timeout | 51.17 | 5.25 | +/- 1.96 |  | 11.1 | 3.4 | 4.10 |
| 2 | timeout | 47.47 | 5.83 | +/- 2.18 |  | 10.6 | 6.2 | 3.37 |
| 4 | timeout | 42.48 | 6.70 | +/- 2.50 |  | 10.7 | 12.8 | 5.83 |
| 8 | timeout | 33.17 | 4.47 | +/- 1.67 |  | 10.2 | 22.1 | 6.70 |

**b. TunedTimeoutRecovery** (replan x abandon thresholds):

| Rate | Policy | Mean (lines/h) | SD | 95% CI | Paired delta vs timeout (95% CI) | Stuck-busy % | Frozen % | Abandoned / ep |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | tuned replan 3 abandon 10 | 50.88 | 4.77 | +/- 1.78 | -0.29 (-1.63 to +1.05) | 10.8 | 3.4 | 5.70 |
| 1 | tuned replan 3 abandon 15 | 51.41 | 4.95 | +/- 1.85 | +0.24 (-1.37 to +1.85) | 10.9 | 3.4 | 3.50 |
| 1 | tuned replan 3 abandon 25 | 50.26 | 6.01 | +/- 2.24 | -0.91 (-2.98 to +1.16) | 11.3 | 3.4 | 1.40 |
| 1 | tuned replan 5 abandon 10 | 50.74 | 5.61 | +/- 2.09 | -0.43 (-1.89 to +1.02) | 10.8 | 3.4 | 5.20 |
| 1 | tuned replan 5 abandon 15 | 51.17 | 5.25 | +/- 1.96 | +0.00 (+0.00 to +0.00) | 11.1 | 3.4 | 4.10 |
| 1 | tuned replan 5 abandon 25 | 49.97 | 5.02 | +/- 1.87 | -1.20 (-2.61 to +0.21) | 11.1 | 3.4 | 1.53 |
| 1 | tuned replan 8 abandon 10 | 50.83 | 5.71 | +/- 2.13 | -0.34 (-2.20 to +1.52) | 11.1 | 3.4 | 6.10 |
| 1 | tuned replan 8 abandon 15 | 50.78 | 4.60 | +/- 1.72 | -0.38 (-1.53 to +0.76) | 11.0 | 3.4 | 3.13 |
| 1 | tuned replan 8 abandon 25 | 50.30 | 4.52 | +/- 1.69 | -0.86 (-2.23 to +0.50) | 11.2 | 3.4 | 1.57 |
| 2 | tuned replan 3 abandon 10 | 48.29 | 5.66 | +/- 2.11 | +0.82 (-0.22 to +1.85) | 10.7 | 6.2 | 5.73 |
| 2 | tuned replan 3 abandon 15 | 47.95 | 6.30 | +/- 2.35 | +0.48 (-1.16 to +2.12) | 11.0 | 6.2 | 3.63 |
| 2 | tuned replan 3 abandon 25 | 47.76 | 6.95 | +/- 2.60 | +0.29 (-1.46 to +2.03) | 11.9 | 6.2 | 1.83 |
| 2 | tuned replan 5 abandon 10 | 48.05 | 6.47 | +/- 2.41 | +0.58 (-0.42 to +1.57) | 10.0 | 6.2 | 5.33 |
| 2 | tuned replan 5 abandon 15 | 47.47 | 5.83 | +/- 2.18 | +0.00 (+0.00 to +0.00) | 10.6 | 6.2 | 3.37 |
| 2 | tuned replan 5 abandon 25 | 47.81 | 6.21 | +/- 2.32 | +0.34 (-0.60 to +1.27) | 11.2 | 6.2 | 1.77 |
| 2 | tuned replan 8 abandon 10 | 48.29 | 6.32 | +/- 2.36 | +0.82 (-0.15 to +1.78) | 10.2 | 6.2 | 6.77 |
| 2 | tuned replan 8 abandon 15 | 47.76 | 5.99 | +/- 2.24 | +0.29 (-0.41 to +0.99) | 10.4 | 6.2 | 3.33 |
| 2 | tuned replan 8 abandon 25 | 48.10 | 5.87 | +/- 2.19 | +0.62 (-0.36 to +1.61) | 11.2 | 6.2 | 1.67 |
| 4 | tuned replan 3 abandon 10 | 41.04 | 5.07 | +/- 1.89 | -1.44 (-2.69 to -0.19) | 10.0 | 12.8 | 8.03 |
| 4 | tuned replan 3 abandon 15 | 41.42 | 5.92 | +/- 2.21 | -1.06 (-2.21 to +0.10) | 10.5 | 12.8 | 5.57 |
| 4 | tuned replan 3 abandon 25 | 40.61 | 5.46 | +/- 2.04 | -1.87 (-3.16 to -0.58) | 11.3 | 12.8 | 3.20 |
| 4 | tuned replan 5 abandon 10 | 42.00 | 6.25 | +/- 2.33 | -0.48 (-0.98 to +0.02) | 10.2 | 12.8 | 8.60 |
| 4 | tuned replan 5 abandon 15 | 42.48 | 6.70 | +/- 2.50 | +0.00 (+0.00 to +0.00) | 10.7 | 12.8 | 5.83 |
| 4 | tuned replan 5 abandon 25 | 42.43 | 6.31 | +/- 2.36 | -0.05 (-1.68 to +1.58) | 11.3 | 12.8 | 3.17 |
| 4 | tuned replan 8 abandon 10 | 41.42 | 6.46 | +/- 2.41 | -1.06 (-1.99 to -0.12) | 10.2 | 12.8 | 8.87 |
| 4 | tuned replan 8 abandon 15 | 41.47 | 6.22 | +/- 2.32 | -1.01 (-1.77 to -0.25) | 10.7 | 12.8 | 6.30 |
| 4 | tuned replan 8 abandon 25 | 42.19 | 5.69 | +/- 2.12 | -0.29 (-1.49 to +0.91) | 11.4 | 12.8 | 3.50 |
| 8 | tuned replan 3 abandon 10 | 33.89 | 4.42 | +/- 1.65 | +0.72 (-0.05 to +1.49) | 9.7 | 22.1 | 9.57 |
| 8 | tuned replan 3 abandon 15 | 34.03 | 4.73 | +/- 1.77 | +0.86 (+0.19 to +1.54) | 10.3 | 22.1 | 7.20 |
| 8 | tuned replan 3 abandon 25 | 33.70 | 4.73 | +/- 1.77 | +0.53 (-0.35 to +1.40) | 11.0 | 22.1 | 4.70 |
| 8 | tuned replan 5 abandon 10 | 33.65 | 4.48 | +/- 1.67 | +0.48 (-0.16 to +1.12) | 9.8 | 22.1 | 9.47 |
| 8 | tuned replan 5 abandon 15 | 33.17 | 4.47 | +/- 1.67 | +0.00 (+0.00 to +0.00) | 10.2 | 22.1 | 6.70 |
| 8 | tuned replan 5 abandon 25 | 32.88 | 4.69 | +/- 1.75 | -0.29 (-1.13 to +0.55) | 10.6 | 22.1 | 4.90 |
| 8 | tuned replan 8 abandon 10 | 33.74 | 4.53 | +/- 1.69 | +0.58 (-0.32 to +1.48) | 9.8 | 22.1 | 10.60 |
| 8 | tuned replan 8 abandon 15 | 33.22 | 4.52 | +/- 1.69 | +0.05 (-0.54 to +0.64) | 9.8 | 22.1 | 7.10 |
| 8 | tuned replan 8 abandon 25 | 33.26 | 4.77 | +/- 1.78 | +0.10 (-0.71 to +0.91) | 10.6 | 22.1 | 4.47 |

**c. RuleRecovery** (back off after B, reroute after R, abandon after A, no human):

| Rate | Policy | Mean (lines/h) | SD | 95% CI | Paired delta vs timeout (95% CI) | Stuck-busy % | Frozen % | Abandoned / ep |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | rule 2/5/10 | 45.74 | 6.64 | +/- 2.48 | -5.42 (-7.52 to -3.33) | 11.9 | 3.4 | 6.50 |
| 1 | rule 3/6/15 | 47.28 | 6.50 | +/- 2.43 | -3.89 (-6.01 to -1.76) | 12.3 | 3.4 | 7.70 |
| 1 | rule 5/10/25 | 50.40 | 5.27 | +/- 1.97 | -0.77 (-2.20 to +0.66) | 12.2 | 3.4 | 2.10 |
| 2 | rule 2/5/10 | 44.40 | 5.48 | +/- 2.05 | -3.07 (-5.02 to -1.13) | 12.1 | 6.2 | 8.77 |
| 2 | rule 3/6/15 | 45.12 | 5.01 | +/- 1.87 | -2.35 (-4.29 to -0.42) | 11.4 | 6.2 | 5.20 |
| 2 | rule 5/10/25 | 46.66 | 4.81 | +/- 1.79 | -0.82 (-2.18 to +0.54) | 11.6 | 6.2 | 2.40 |
| 4 | rule 2/5/10 | 38.78 | 5.70 | +/- 2.13 | -3.70 (-5.24 to -2.15) | 11.6 | 12.8 | 9.47 |
| 4 | rule 3/6/15 | 39.60 | 6.72 | +/- 2.51 | -2.88 (-4.55 to -1.21) | 11.5 | 12.8 | 7.83 |
| 4 | rule 5/10/25 | 39.46 | 5.64 | +/- 2.11 | -3.02 (-5.17 to -0.88) | 11.7 | 12.8 | 3.83 |
| 8 | rule 2/5/10 | 32.26 | 5.91 | +/- 2.21 | -0.91 (-2.44 to +0.61) | 10.8 | 22.1 | 10.30 |
| 8 | rule 3/6/15 | 31.97 | 5.31 | +/- 1.98 | -1.20 (-2.50 to +0.10) | 10.7 | 22.1 | 9.07 |
| 8 | rule 5/10/25 | 32.78 | 4.61 | +/- 1.72 | -0.38 (-1.59 to +0.82) | 11.0 | 22.1 | 5.23 |

**Best per rate, by paired delta in pick_rate.** These CIs are optimistic: each is the winner picked from 8 non-default tuned points or 3 rules, and the CI does not correct for that selection.
- Best tuned timeout:
  - Rate 1: replan 3 abandon 15, +0.24 (-1.37 to +1.85).
  - Rate 2: replan 8 abandon 10, +0.82 (-0.15 to +1.78). It ties with replan 3 abandon 10, +0.82 (-0.22 to +1.85); the tie is broken by the higher CI low end.
  - Rate 4: the default 5/15 is best. Every other point is below it, and four of them significantly.
  - Rate 8: replan 3 abandon 15, +0.86 (+0.19 to +1.54).
  - No single point wins at every rate. Only 1 of the 32 non-default comparisons excludes 0 in the favourable direction, which is about what chance gives at 95%.
- Best rule:
  - Rates 1, 2 and 8: 5/10/25, at -0.77 (-2.20 to +0.66), -0.82 (-2.18 to +0.54) and -0.38 (-1.59 to +0.82).
  - Rate 4: 3/6/15, at -2.88 (-4.55 to -1.21).
  - No rule beats `timeout` at any rate. The faster rules (2/5/10, 3/6/15) are significantly worse at rates 1, 2 and 4.
  - The rules log 26 to 67 recovery fallbacks per episode (`recovery_fallbacks`) and abandon more often than the default, except 5/10/25. Call-human % is 0 by construction in tables a to c (no human rung); it is reported in (d).

**d. Call-human curve** (rule 3/6/15 with call-human after 14 stuck steps; 3/6/15 was the default `--best-rule` and is not the best rule found in (c)):

| Rate | Cost (steps per call) | Mean (lines/h) | Delta vs no-human rule (95% CI) | Delta vs timeout (95% CI) | Calls decided / ep | Calls executed / ep | Human-steps / ep (total cost) | Call-human % (accounting) | Extra deliveries / ep vs no-human | Human-steps per extra delivery | Abandoned / ep |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 0 | 49.06 | +1.78 (+0.04 to +3.51) | -2.11 (-3.56 to -0.67) | 5.00 | n/a (cost 0) | 0.0 | 0.00 | +1.23 | 0 | 2.50 |
| 1 | 5 | 49.06 | +1.78 (+0.04 to +3.51) | -2.11 (-3.56 to -0.67) | 5.00 | 2.27 | 11.3 | 0.19 | +1.23 | 9 | 2.50 |
| 1 | 15 | 49.06 | +1.78 (+0.04 to +3.51) | -2.11 (-3.56 to -0.67) | 5.00 | 2.27 | 34.0 | 0.57 | +1.23 | 28 | 2.50 |
| 1 | 30 | 49.06 | +1.78 (+0.04 to +3.51) | -2.11 (-3.56 to -0.67) | 5.00 | 2.27 | 68.0 | 1.13 | +1.23 | 55 | 2.50 |
| 1 | 60 | 49.06 | +1.78 (+0.04 to +3.51) | -2.11 (-3.56 to -0.67) | 5.00 | 2.27 | 136.0 | 2.27 | +1.23 | 110 | 2.50 |
| 1 | no human | 47.28 | | -3.89 (-6.01 to -1.76) | 0.00 | 0.00 | 0.0 | 0.00 | | | 7.70 |
| 2 | 0 | 44.30 | -0.82 (-1.72 to +0.08) | -3.17 (-4.99 to -1.35) | 5.47 | n/a (cost 0) | 0.0 | 0.00 | -0.57 | 0 | 2.90 |
| 2 | 5 | 44.30 | -0.82 (-1.72 to +0.08) | -3.17 (-4.99 to -1.35) | 5.47 | 2.30 | 11.5 | 0.19 | -0.57 | n/a (no gain) | 2.90 |
| 2 | 15 | 44.30 | -0.82 (-1.72 to +0.08) | -3.17 (-4.99 to -1.35) | 5.47 | 2.30 | 34.5 | 0.57 | -0.57 | n/a (no gain) | 2.90 |
| 2 | 30 | 44.30 | -0.82 (-1.72 to +0.08) | -3.17 (-4.99 to -1.35) | 5.47 | 2.30 | 69.0 | 1.15 | -0.57 | n/a (no gain) | 2.90 |
| 2 | 60 | 44.30 | -0.82 (-1.72 to +0.08) | -3.17 (-4.99 to -1.35) | 5.47 | 2.30 | 138.0 | 2.30 | -0.57 | n/a (no gain) | 2.90 |
| 2 | no human | 45.12 | | -2.35 (-4.29 to -0.42) | 0.00 | 0.00 | 0.0 | 0.00 | | | 5.20 |
| 4 | 0 | 40.51 | +0.91 (-0.27 to +2.10) | -1.97 (-3.62 to -0.32) | 8.50 | n/a (cost 0) | 0.0 | 0.00 | +0.63 | 0 | 4.70 |
| 4 | 5 | 40.51 | +0.91 (-0.27 to +2.10) | -1.97 (-3.62 to -0.32) | 8.50 | 3.53 | 17.7 | 0.29 | +0.63 | 28 | 4.70 |
| 4 | 15 | 40.51 | +0.91 (-0.27 to +2.10) | -1.97 (-3.62 to -0.32) | 8.50 | 3.53 | 53.0 | 0.88 | +0.63 | 84 | 4.70 |
| 4 | 30 | 40.51 | +0.91 (-0.27 to +2.10) | -1.97 (-3.62 to -0.32) | 8.50 | 3.53 | 106.0 | 1.77 | +0.63 | 167 | 4.70 |
| 4 | 60 | 40.51 | +0.91 (-0.27 to +2.10) | -1.97 (-3.62 to -0.32) | 8.50 | 3.53 | 212.0 | 3.53 | +0.63 | 335 | 4.70 |
| 4 | no human | 39.60 | | -2.88 (-4.55 to -1.21) | 0.00 | 0.00 | 0.0 | 0.00 | | | 7.83 |
| 8 | 0 | 32.40 | +0.43 (-0.48 to +1.35) | -0.77 (-1.97 to +0.44) | 9.13 | n/a (cost 0) | 0.0 | 0.00 | +0.30 | 0 | 5.13 |
| 8 | 5 | 32.40 | +0.43 (-0.48 to +1.35) | -0.77 (-1.97 to +0.44) | 9.13 | 3.80 | 19.0 | 0.32 | +0.30 | 63 | 5.13 |
| 8 | 15 | 32.40 | +0.43 (-0.48 to +1.35) | -0.77 (-1.97 to +0.44) | 9.13 | 3.80 | 57.0 | 0.95 | +0.30 | 190 | 5.13 |
| 8 | 30 | 32.40 | +0.43 (-0.48 to +1.35) | -0.77 (-1.97 to +0.44) | 9.13 | 3.80 | 114.0 | 1.90 | +0.30 | 380 | 5.13 |
| 8 | 60 | 32.40 | +0.43 (-0.48 to +1.35) | -0.77 (-1.97 to +0.44) | 9.13 | 3.80 | 228.0 | 3.80 | +0.30 | 760 | 5.13 |
| 8 | no human | 31.97 | | -1.20 (-2.50 to +0.10) | 0.00 | 0.00 | 0.0 | 0.00 | | | 9.07 |

How to read the curve:
- **Cost is accounting only.** Relocation is instant and only `call_human_steps` grows (the S3A contract). So pick-rate is identical at every cost, and "Call-human %" is booked human time, not robot time.
- **Calls decided vs calls executed.** Calls decided is about 2x calls executed: a call on an agent with an empty path falls back to a wait. Total cost = executed calls x cost = `call_human_steps`.
- **Against the env default, calling a human never pays at any cost.** At cost 0 the call-human rule is below `timeout` at every rate, and significantly so at rates 1, 2 and 4.
- **Against the same rule without a human,** it helps only at rate 1: +1.78 (+0.04 to +3.51), with abandonments down from 7.70 to 2.50 per episode. At rates 2, 4 and 8 the CI contains 0, so there is no measured gain to pay for.
- **Where it stops paying.** This is derived, not simulated. Value one human-step as one AGV-step. At rate 1 the no-human rule spends 121.8 AGV-steps per delivery, and the human buys one extra delivery per 1.84 executed calls. Calling stops paying above about 66 steps (5.5 min) per call.

**Frozen floor and headroom.** The frozen floor is a model, not a measurement: rate-0 pick-rate x the AGV frozen share (`frozen_agent_steps / (8 x 500)`), per seed. The AGV share is the right denominator because breakdowns are AGV-only (`scripts/sweep.py` `point_spec`). It assumes pick-rate scales with available AGV-time, and it overshoots at rate 1, so treat it as approximate. All figures are lines/h, paired over 30 seeds.

| Rate | Loss vs rate 0 (95% CI) | AGV frozen % | Frozen floor (95% CI) | `timeout` above floor (95% CI) | Best rule delta vs `timeout` | Best rule's share of the loss | Best rule above floor (95% CI) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | +2.50 (+0.32 to +4.67) | 5.1 | +2.75 (+2.28 to +3.22) | -0.25 (-2.28 to +1.78) | -0.77 (5/10/25) | -31% | +0.51 (-1.41 to +2.43) |
| 2 | +6.19 (+3.83 to +8.55) | 9.3 | +5.01 (+4.44 to +5.58) | +1.19 (-0.85 to +3.22) | -0.82 (5/10/25) | -13% | +2.00 (-0.18 to +4.19) |
| 4 | +11.18 (+8.43 to +13.94) | 19.2 | +10.29 (+9.44 to +11.14) | +0.89 (-1.54 to +3.32) | -2.88 (3/6/15) | -26% | +3.77 (+1.44 to +6.11) |
| 8 | +20.50 (+17.65 to +23.34) | 33.2 | +17.84 (+16.57 to +19.11) | +2.66 (+0.75 to +4.56) | -0.38 (5/10/25) | -2% | +3.04 (+1.43 to +4.65) |

**Decision.**
- (a) **Does any hand-written recovery beat the default?** No, not at a plausible rate (1 to 2 per robot-hour).
  - The best tuned point is +0.24 (-1.37 to +1.85) at rate 1 and +0.82 (-0.15 to +1.78) at rate 2.
  - Every rule and the call-human rule is at or below `timeout`.
  - The only CI that excludes 0 in favour is tuned 3/15 at rate 8, +0.86 (+0.19 to +1.54), which is 1 of 32 comparisons.
- (b) **How much of the breakdown loss does the best rule recover?** None. It loses more: an extra 31% of the loss at rate 1 (noisy, the loss CI is 0.32 to 4.67), 13% at rate 2, 26% at rate 4 and 2% at rate 8.
- (c) **Is there headroom for a learned policy?** The gap between the best rule and the frozen floor is 0.51 lines/h at rate 1 and 2.00 at rate 2, and both CIs contain 0. It splits into two parts:
  - The rule's own deficit against `timeout`.
  - `timeout`'s residual above the floor: -0.25 (-2.28 to +1.78) at rate 1 and +1.19 (-0.85 to +3.22) at rate 2.
  - Above the env default, the headroom at plausible rates cannot be told apart from zero. A learned policy that beats `RuleRecovery` (the kill criterion) could do so just by waiting the way the default does.

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

No measured results are stated here. The numbers come from the sweep JSON files after the scheduler has run them.

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

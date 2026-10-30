# warehouse-rl

A record of experiments on robot-fleet stall analysis, with every number tied to a results file in this tree and the negatives left in. It started as a reinforcement-learning question (can a learned policy beat the simulator's heuristic at recovering stuck robots, and at task assignment) and turned into a diagnostic tool measured on a simulator and on one public real-robot log.

**What survived:** the per-robot time budget, the stall list with its caveat, the blocking number as a comparison between floors, and the hotspot map as a diagnosis of the worst cells after the fact.

**What did not:** everything learned, every hand-written recovery rule, the map as a forecast, routing on the map, early warning of a blockage; keeping less of the log (report by exception, S18): identical, not worth it.

The name is the original question, and that question was not answered: the learned recovery policy was killed by its own criterion in Sprint 3 and learned task assignment was never built. Everything after that is what the measurement harness turned up instead.

The work was produced with an agent pipeline, Claude Code lanes with adversarial reviewers behind a test gate, under the rules in `CLAUDE.md`; the commits carry the trailers. Direction, kill criteria, the reward design and every change to a metric were the author's decisions. `docs/PROCESS.md` says what the pipeline did and what the author did.

Everything below the "Setup" heading is the lab notebook in sprint order; this page is the summary. The confidence intervals behind each row are in the section the row points to.

## What was tried, and what survived

| Experiment | Result | Where |
|---|---|---|
| Learned stuck recovery (double DQN, warm start, priced abandons) | Killed. The net abandoned every stuck task: 0 deliveries against the timeout baseline | Sprint 3 |
| Learned task assignment, the original question | Never built. Plan and kill criteria in `docs/SCOPE.md` Sprint 4 | SCOPE |
| Dispatch that skips frozen robots (stuck-aware CTA), routing around other robots (`cta_care`) | Within noise. Paired delta against CTA inside +/-0.7 lines/h at every breakdown rate and fleet size | Sprint 2 |
| Hand-written recovery rules and a call-a-human rung, against the simulator's timeout | None beats the timeout at any breakdown rate; call-human is below it at every rate | Sprint 3 |
| A hotspot map against "last hour's spots" (persistence) | Within noise: precision 0.925 against 0.932 at the top 20 cells | (j) |
| The same map against the true bad cells (floor truth) | Precision 0.965 at the top 20 cells, recall 0.241; 44% of the bad cells are never driven over | S8B |
| Routing robots around the map | 15.6% of the floor's loss recovered, CI includes 0; an oracle that knows the floor gets 22.7% | Sprint 8, (a) |
| Routing on a sticky floor (p 0.9-0.99), dose over the map weight | The strongest weight recovers 11.1% of the floor's loss against an oracle's 15.9% | Sprint 8, sticky |
| Tuning the map-to-cost transform by random search, held out | Mixed. Beats the weight-4 map at p 0.9-0.99, worse than weight 32 at p 0.8-0.95 | Sprint 8, guidance |
| Lessons that persist (a hot cell still hot next window) against chance | Above chance at every window: 18 of 25 against a chance mean of 0.241, lift 2.99; no CI | Sprint 8, lessons |
| Early warning of a blockage the planner cannot see | Not solved. Best while open: the map catches 6 of 50 at 177.8 false alarms per zone-hour; CUSUM 2 of 50 at none | (k), (n), (t), (u) |
| A false-alarm gate on the map's forecasts | 1,391 false forecasts on an undisturbed run become 2 or 5, and recall goes with them: 1 of 50 cells | (l) |
| Per-robot time budget | Stuck time 20.81% of AGV time on an undisturbed floor, 32.05% on a sticky one; real log 0.42% | (o), (q) |
| A stall list that leaves station stops out | Real log: stuck runs 567 to 6, both labelled stops kept. A plain 60 s timer gets 10 runs with the same hits | (r), (s), (w1) |
| Keeping less of the log (report by exception, S18) | Identical, not worth it. At a 30 s heartbeat every answer is identical at the first identical rung on both runs, but the reduced log gzips only 1.1820 times smaller than gzip of the full log on the simulator (line ratio 1.5021) and 1.0001 times on the real log (line ratio 1.0003), below the 3:1 reference | (y) |
| "Blocked by" only when the neighbour is on the robot's route | 8% to 31% of neighbour-cause episodes have the neighbour on the route | (v) |
| A blocking number per shift | Three times higher on the sticky floor; rank correlation 0.04 with truth stuck time, so not a validated gauge | (p), (w2) |
| The real log's own records as labels (ROS diagnostics, dispatcher events) | Mixed. Component errors cover 0.19% of the span; the two uncaused stalls stay uncaused. Two stalls, not a rate | (x1), (x2), (x3) |

## Speed and coverage

| | Figure | Where |
|---|---|---|
| Batch ingest | 2,789 messages per second, 6,912,000 messages, 12 robots, one laptop | `results/fleet/benchmark.json` |
| Re-grading an eight-hour shift | 4.4 to 4.7 s | Sprint 14E |
| Real log | 132,838 rows read, 0 rejected by our parser | (q) |

The reject count is against our own contract, and that contract is a format check, not a quality check. The dataset's authors removed 2,959 of 140,386 raw rows (2.1%) before publishing; run on the raw table, our parser rejects none of them (x3). The live Kafka leg of the benchmark runs at the emitter's pace, not at a limit.

## Tested on

| Source | What it is |
|---|---|
| TA-RWARE simulator, medium map | 8 AGVs and 4 pickers, synthetic, emitted as VDA 5050-shaped JSON lines by `fleet/emit.py` |
| MoRoOp (Klein and Jeong 2026, arXiv 2610.02428, CC BY 4.0) | one wheel.me robot in a lab, nine 8-hour shifts, four named positions, through `fleet/adapters/moroop.py` |

Nothing else. A log in any other shape needs an adapter like the MoRoOp one; the ingester accepts the contract in `docs/SCOPE.md` "S5A" and nothing else. Before running anything on your own log, check it field by field:

```sh
.venv/bin/python fleet/check_log.py --glob 'DIR/*.jsonl.gz'
```

It prints one row per required field and a verdict line, exit 0 on a match and 2 otherwise. The ingester refuses a log the same way when fewer than `--min-accepted` of its lines parse; pass `--once --min-accepted 0.5` on a plain folder of files, because without `--once` a folder with no emitter ledger never ends and the default never fires (S17A lane report, open point). One robot on four positions cannot produce a map, a congestion figure or a blockage, so every claim about those is simulator-only.

## Reproducing

- `./scripts/setup.sh` fetches the two vendored packages (both MIT) at pinned commits. The simulator numbers here are macOS arm64 numbers; Linux gives different absolute values from the A* tie-break and the same paired comparisons (`docs/PLATFORM.md`).
- The raw simulator streams (about 2.5 GB) are not in the repo. `fleet/emit.py` regenerates them from the seeds named in each section. The results files they produced are in `results/`.
- MoRoOp is downloaded from Hugging Face (dataset `Self-Organizing-Production-Logistics/MoRoOp`, revision 1.0.1, fetched by `fleet/adapters/moroop.py`; the raw and converted files are not committed); only the derived stations file `fleet/data/moroop/stations.json` is. No client data is in this repo and none will be.
- Every lane and literature report cited from here is under `reports/`. The gate is `.venv/bin/python -m unittest discover -s tests`.

## Reading further

`docs/PROCESS.md` (how the work was produced, what the agents did and what the author did), `docs/SCOPE.md` (plan, decisions, kill criteria, open questions), `docs/LITERATURE.md` (what was already known before each build, with the standard names), `docs/COMPETITION.md` (which of these capabilities vendors document, every cell dated with its URL, absences only from documentation trees), `docs/DEMO.md` (the pipeline end to end on a laptop), `docs/overview/` and `docs/replay/` (pages built from the results).

## The notebook

Everything from here on is in sprint order, written as the work happened. Numbers in each section come from the results files named in the same commit.

Replay of one CTA episode: open `results/replay_small.html` in a browser (made by `scripts/record_episode.py` + `scripts/replay_template.html`).

## Setup (macOS)

Absolute simulator numbers in this README are macOS arm64 numbers; Linux gives different absolute values (A* tie-breaking) and the same paired comparisons. See [docs/PLATFORM.md](docs/PLATFORM.md).

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

### Sprint 3 close-out (2026-10-13)

#### Learned recovery: kill criterion hit

The Sprint 3 kill criterion ("learned recovery does not beat `RuleRecovery` outside the CI", `docs/SCOPE.md`) was applied on 13 Oct. No learned policy came near `RuleRecovery`, let alone `timeout`: every greedy evaluation of every attempt stayed far below the timeout reference of 50.11 lines/h on the 5 eval seeds. Training, the held-out evaluation and the 9-run retrain are dropped. Three attempts, three failure modes:
- **Abandon loophole (v1, 11 Oct).** The stuck penalty stopped when the task was abandoned, and abandoning was free, so the net learned to abandon every stuck task: 0 deliveries and 4782 abandons on seed 0 (`results/recovery_train_v1_degenerate/rate1_seed0/v1_eval/`).
- **Reroute loophole (v2 with stuck penalty, 12 Oct).** With abandon priced, the net rerouted at about 95% of stuck events instead: a reroute resets the StuckCounter the penalty was keyed on (`reports/wr-lane-s3d.md`, PR #8 review; that probe's log was not kept). Removing the stuck term did not change the action mix in the 40-episode probes (98% to 99% reroute, `results/recovery_train_smoke/eval/`), so the loophole was real but not shown to be the cause.
- **No learning signal on the honest reward (v2 own-credit pilot, 13 Oct).** Deliveries minus the real action costs, no stuck term, per-agent credit, timeout-prior exploration. The training return was carried by the timeout prior and fell as epsilon decayed, and the greedy net never learned to deliver. Our hypothesis, not tested: a stuck robot that sees only its four neighbour cells cannot tell a two-step hiccup from a 50-step breakdown, so wait and reroute look alike.

![Learned recovery training curves](results/recovery_train_curves.png)

`results/recovery_train_curves.png`, from `scripts/plot_recovery_train.py`, which reads only the logs:
- `results/recovery_train_v1_degenerate/rate1_seed{0,1}/log.json` (v1);
- `results/recovery_train_smoke/{rate1_seed0,pass2_rate1_seed0}/log.json` (v2 probes, one interval each);
- `results/recovery_train_v2_pilot_aborted/rate1_seed0/log.json` (pilot).

The training returns of v1 and v2 are different rewards and are not comparable. This PNG and `results/recovery_informed.png` are the two plots committed (force-added past `results/*.png`); the others are regenerated by their scripts.

**Pilot numbers** (`results/recovery_train_v2_pilot_aborted/rate1_seed0/log.json`; rate 1, run seed 0, 3200 episodes planned):
- Timeout reference on eval seeds 1000-1004: 50.11 lines/h (48.96, 46.08, 46.08, 56.16, 53.28).
- Greedy eval: 1.44 lines/h at episode 40. The best interval was 35.14 at episode 240 (epsilon 0.86), and no later interval was above 8.35. Every interval from episode 1360 on was at most 1.44, ending at 0.0 at episode 1600.
- Aborted at episode 1600 (`aborted`: eval 0.0 < 0.5 x 50.11, the first interval the abort grace allows). Wall time 974 s.
- Mean training return per interval: 34.9 at episode 40, between 32.4 and 36.0 up to episode 1320 (epsilon 0.22), then falling to 4.28 at episode 1600 (epsilon 0.05).
- Recovery decisions per training episode: 564 at episode 40, 1738 at episode 1600. Once the net acts on its own, robots stay stuck and keep asking.

v1 for comparison (`results/recovery_train_v1_degenerate/`): the best greedy eval was 11.23 (seed 0, 6400 episodes, finished) and 4.03 (seed 1, 4880 episodes, killed). Both ended at 0.0.

#### Informed recovery (lane E)

A stuck robot sees only its four neighbour cells. Lane E gives the recovery hook two more observation keys:
- `blocker_frozen`: the robot on my next cell is frozen right now;
- `blocker_frozen_left`: how many more steps its frozen run lasts (optimistic look-ahead).

It also adds `InformedTimeoutRecovery`, with two modes:
- `informed_timeout` ("informed flag"): reroute or abandon at once when the blocker is frozen;
- `informed_timeout_left` ("informed left"): the same, but only when the remaining frozen run exceeds `replan`.

Both otherwise behave as `timeout` (replan 5, abandon 15). The observation grew from 12 to 14 keys, so learned-recovery checkpoints are format version 3, and v2 checkpoints are refused.

Data: `results/recovery/informed.json` (`scripts/recovery_sweep.py --only e`, queue item `wr-s3e-informed-sweep`) against the stored rows of `results/recovery/timeout.json`. The setup is the same as Sprint 3 above:
- medium map, 500 steps, `StuckAwareCtaPolicy`;
- 30 seeds (0-29) per (rate, policy), seed-paired, with the same disturbance schedules;
- statistics from `evaluate.summarise` and `evaluate.paired_delta`.

Plot: `results/recovery_informed.png`.

| Rate | Policy | Mean (lines/h) | SD | 95% CI | Paired delta vs timeout (95% CI) | Stuck-busy % | Abandoned / ep | Reroutes / ep | Decisions with frozen blocker / ep | Of which reroutes / ep |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | timeout | 51.17 | 5.25 | +/- 1.96 |  | 11.1 | 4.10 | 124.1 | n/a | n/a |
| 1 | informed flag | 50.54 | 5.45 | +/- 2.03 | -0.62 (-1.64 to +0.39) | 11.9 | 4.10 | 169.7 | 61.0 | 61.0 |
| 1 | informed left | 50.69 | 5.59 | +/- 2.09 | -0.48 (-1.12 to +0.16) | 11.7 | 3.83 | 161.5 | 59.2 | 56.6 |
| 2 | timeout | 47.47 | 5.83 | +/- 2.18 |  | 10.6 | 3.37 | 105.3 | n/a | n/a |
| 2 | informed flag | 47.81 | 5.74 | +/- 2.14 | +0.34 (-0.58 to +1.25) | 11.6 | 3.23 | 169.7 | 77.5 | 77.5 |
| 2 | informed left | 47.57 | 6.36 | +/- 2.37 | +0.10 (-0.33 to +0.52) | 11.6 | 3.37 | 164.0 | 74.0 | 70.6 |
| 4 | timeout | 42.48 | 6.70 | +/- 2.50 |  | 10.7 | 5.83 | 124.0 | n/a | n/a |
| 4 | informed flag | 41.76 | 6.12 | +/- 2.29 | -0.72 (-1.59 to +0.15) | 13.3 | 5.73 | 287.9 | 183.6 | 183.6 |
| 4 | informed left | 42.48 | 6.38 | +/- 2.38 | +0.00 (-0.42 to +0.42) | 13.0 | 5.57 | 252.0 | 149.8 | 144.3 |
| 8 | timeout | 33.17 | 4.47 | +/- 1.67 |  | 10.2 | 6.70 | 135.1 | n/a | n/a |
| 8 | informed flag | 33.17 | 5.31 | +/- 1.98 | +0.00 (-1.35 to +1.35) | 14.6 | 6.67 | 409.3 | 288.2 | 288.2 |
| 8 | informed left | 33.60 | 4.79 | +/- 1.79 | +0.43 (-0.20 to +1.07) | 14.0 | 6.77 | 377.6 | 276.1 | 266.3 |

The timeout rows are the stored `timeout.json` rows. The `decisions_while_blocker_frozen` columns are n/a for timeout because rows written before lane E do not carry them.

**Verdict: fault information does not move the number; the jam loss is in the layout.**
- No paired CI excludes 0 at any rate, for either mode. That includes the look-ahead mode, which knows the repair time.
- At rate 8 the best is informed left, +0.43 (-0.20 to +1.07). That is 2% of the 20.50 lines/h breakdown loss, and within noise.
- "In the layout" is an inference from the frozen-floor table above, not a measurement. Of the 20.50 lines/h lost at rate 8, the frozen floor (the broken robots' own lost time) is 17.84. `timeout`'s residual of +2.66 above that floor is not recovered by any rule family: tuned timeout, rules, call-human and now informed. The only CI-excluding gain anywhere is tuned replan 3 abandon 15 at rate 8, +0.86 (+0.19 to +1.54), which is 1 of 32 tuned comparisons (about what chance gives) and 4% of the 20.50 loss.

**What was measured.** This sweep tests reroute-at-once use of the fact, not abandon-at-once:
- When the blocker is frozen, both modes reroute on nearly every decision (flag: 288.2 of 288.2 per episode at rate 8).
- A reroute resets the StuckCounter, so the abandon at 15 effectively never fires early. Abandons per episode are unchanged (6.67 vs 6.70 at rate 8).
- Stuck-busy time rises instead, from 10.2% to 14.6% at rate 8.

This is the lane E caveat (`reports/wr-lane-s3e.md`). An abandon-on-frozen-blocker rule was not measured.

### Learned recovery trainer (`scripts/train_recovery.py`, format version 2, 2026-10-13)

The learned policy (`src/warehouse_rl/learned_recovery.py`) is a semi-MDP double DQN over the `RecoveryHook` decision events on the medium map at breakdown rates 1, 2 and 4, with `StuckAwareCtaPolicy` as the dispatcher. The reward of a decision window is the agent's own reward minus the real action costs:
- the agent's own entry of the simulator's per-agent reward (`RewardType.INDIVIDUAL`, `global_reward=False`, both asserted): +1 to the AGV that delivers, +0.1 to the picker at whose cell an AGV loads or unloads (the AGV gets nothing for it), nothing shared between agents (`credit: "own"` since 13 Oct; before, the fleet's deliveries were shared equally). The vendor's constant -0.001 per agent-step is added back (`vendor_step_penalty: "excluded"`): at a fixed 500 steps it is the same for every policy. The evaluation metric does not change: pick-rate still comes from `info["shelf_deliveries"]`;
- minus `COST_UNIT x CALL_HUMAN_COST` (0.01 x 60 = 0.60) per executed call-human;
- minus `COST_UNIT x ABANDON_COST` (0.01 x 15 = 0.15) per abandon decision, charged once at the decision. 15 is the timeout rule's own abandon threshold: abandoning costs what waiting out the timeout would have cost.

There is no per-step stuck penalty (`STUCK_PENALTY` = 0.0). Reroute, back-off and abandon all reset the stuck counter, so any stuck term the action itself can reset is a free dodge. Stuck time stays an evaluation metric (`stuck_busy_agents`). `log.json["reward_used"]` records `stuck_penalty: 0.0`, `cost_unit: 0.01`, `credit: "own"` and `vendor_step_penalty: "excluded"`.

The first real run (11 Oct, format version 1) had no abandon term, and its policy was degenerate. Greedy eval pick-rate never rose above 11.2 lines/h on run seed 0 (6400 episodes) or 4.0 on seed 1 (4880 episodes, killed), against 51.17 for `timeout` at rate 1. A 2-seed check with `scripts/evaluate.py --recovery learned:` (11 Oct, `results/recovery_train_v1_degenerate/rate1_seed0/v1_eval/`) found 0 deliveries and an abandon at almost every stuck event: abandoning cleared the stuck penalty and cost nothing. Those runs are in `results/recovery_train_v1_degenerate/` (`log.json` and `v1_eval/` committed 13 Oct, checkpoints not).

Version 2 changes four things:
- **Abandon costs something**, as above. The value is in the config, in `log.json["reward_used"]` and in the checkpoint's reward dict.
- **Exploration starts from the timeout rule.** With probability epsilon a training decision is the timeout rule's action (share `1 - random_share`, default `random_share` 0.1, `--random-share`) or a uniform random one. Otherwise it is greedy. Evaluation is greedy with no prior, so checkpoints evaluate exactly as before. Uniform random recovery gridlocks the medium map, so v1 almost never saw a delivery while it explored.
- **A reference and an abort.** Each run first evaluates `TimeoutRecovery` on the 5 eval seeds through the same rollout path (`log.json["reference_pick_rate"]`). From episode `--abort-after-frac` x episodes on (default 0.5 = `EPS_FRAC`, where epsilon reaches its floor and the net acts on its own), if an interval's greedy eval falls below `--abort-below` (default 0.5) x that reference, the run stops with `finished: false` and an `aborted` record, and the script exits 1. Earlier intervals never abort. Aborted runs cannot be resumed, and `recovery_heldout.py` ignores them. `--abort-below 0` disables the check; `--abort-after-frac 0` checks from the first interval.
- **Format version 2.** `load_checkpoint` refuses version-1 checkpoints, and `--resume` refuses a run directory with another version. `DEFAULT_EPISODES` is 3200, down from 6400. The v1 seed-0 run took 7145 s for 6400 episodes (1.12 s per episode, everything included), so 3200 episodes is about 1.0 h per run and about 9 h for the 9 runs. Rollouts alone ran at 539 env steps/s, which is 2970 s per run.

**Warm start probes, 13 Oct (rate 1, run seed 0).** `train_recovery.py --rates 1 --seeds 0 --abort-below 0 --max-intervals 1 --workers 2 --results-dir results/recovery_train_smoke`, one interval of 40 episodes at epsilon 0.98. Own credit (the reward above): `results/recovery_train_smoke/rate1_seed0/log.json`. Fleet-shared deliveries (the reward before own credit, same day): `results/recovery_train_smoke/pass2_rate1_seed0/log.json`.
- timeout reference on the 5 eval seeds, identical in both: 50.11 lines/h (48.96, 46.08, 46.08, 56.16, 53.28);
- greedy eval at episode 40: 1.44 lines/h with own credit (mean training return +34.9), 1.15 with the shared reward (+27.3). The behaviour policy delivers; the greedy net does not yet.

Action mix of those checkpoints with `scripts/evaluate.py --recovery learned:` on seeds 1000-1001, rate 1 (`results/recovery_train_smoke/eval/`):

| recovery | pick-rate | abandon | reroute | wait | back-off | stuck events |
|---|---|---|---|---|---|---|
| learned, own credit, episode 40 (`learned-b70a8a6f70`) | 2.88 / 0.00 | 0 / 0 | 1401 / 1956 | 33 / 11 | 1 / 0 | 1427 / 1967 |
| learned, shared reward, episode 40 (`learned-6d94d6ea36`) | 1.44 / 0.00 | 0 / 0 | 1442 / 1996 | 15 / 20 | 5 / 0 | 1461 / 2016 |
| timeout | 48.96 / 46.08 | 0 / 2 | 90 / 68 | 407 / 341 | 0 / 0 | 456 / 388 |

After 40 episodes the greedy net still reroutes at almost every stuck event under both rewards. 40 episodes at epsilon 0.98 was too early to judge. The one-run pilot (3200 episodes, with the abort grace) decided: it aborted at episode 1600 with greedy eval 0.0 (see "Learned recovery: kill criterion hit" above), and the retrain was dropped.

## Sprint 5: fleet stuck analyser (Stage 1 measured 2026-10-14)

`fleet/emit.py` turns simulated medium-map episodes into a synthetic fleet log: one VDA 5050-shaped state message per robot per step, written to gzip JSONL files (or Kafka behind a flag) together with an `emit_ledger.json` that counts exactly what was emitted. The simulator's stuck, recovery and clash ground truth sits only in each message's `custom` block. The message contract and field semantics are in the "Sprint 5 / S5A" note of [docs/SCOPE.md](docs/SCOPE.md). Output goes under `fleet/data/` (not committed).

`fleet/ingest.py` reads those files while they are still being written, parses and validates every line, runs a per-robot stuck detector over event time, and writes transitions, stuck episodes with a cause and a resolution, an append-only decision ledger with the raw lines around each decision, and a per-minute ingest ledger into a local store. `fleet/ledger.py status` reports coverage against the emit ledger. The detector never reads the simulator's `custom` block; only a scorer may. The state machine, cause and resolution rules and the ledger definitions are in the "Sprint 5 / S5B" note of [docs/SCOPE.md](docs/SCOPE.md).

`fleet/compose.sh up` starts a local stack (Redpanda for Kafka, ClickHouse, Grafana with a ClickHouse datasource; data in Docker named volumes `fleet_*`, memory-capped containers). `fleet/ingest.py --store clickhouse://localhost:18123/fleet` writes to ClickHouse instead of local files, and `fleet/ingest.py --source kafka --bootstrap localhost:19092` reads the emitter's Kafka topic (`fleet/emit.py --sink kafka --bootstrap localhost:19092`; `pip install -r fleet/requirements.txt` first). When the emitter writes to Kafka its ledger now records how many messages the broker acknowledged. Details are in the "Sprint 5 / S5B2" note of [docs/SCOPE.md](docs/SCOPE.md).

After an ingest, `fleet/grade.py --run NAME --once` grades the analyser's decisions against what happened next, `fleet/score.py --run NAME --glob 'fleet/data/NAME/*.jsonl.gz'` scores the detected episodes against the simulator's ground truth (the one place that reads the `custom` block) and writes `score.json`, `fleet/report.py --run NAME` writes `report.md` and a hotspot heatmap, and `fleet/alert.py --run NAME` prints a line per new stuck episode while an ingest runs. `fleet/ledger.py status` now counts only countable episodes and adds a per-kind grade rollup. Definitions, the truth rule and the grade rules are in the "Sprint 5 / S5C1" note of [docs/SCOPE.md](docs/SCOPE.md).

The report sections also exist as ClickHouse queries under `fleet/sql/reports/` (one file per section, parameterised by the run) and as a provisioned Grafana dashboard (`fleet/grafana/dashboard.json`, loaded when the stack starts, with rows for the integration, the simulation and the results). `fleet/fleet_analyser/bench.py` loads a benchmark JSON and a score JSON into the `results` table. `fleet/score.py --source kafka` scores straight from the topic. `fleet/benchmark.py` runs the batch and live benchmark on the host (the simulator never runs in a container); `--smoke` is the quick version and writes to a temporary file. The definitions are in the "Sprint 5 / S5C2" note of [docs/SCOPE.md](docs/SCOPE.md); the real run is a scheduler queue item and its numbers come from the results JSON it writes.

Demo v0, a walkthrough of about 4 minutes with every command and output from one run: [docs/DEMO.md](docs/DEMO.md).

### Sprint 5 results: benchmark (2026-10-14)

Every number below comes from `results/fleet/benchmark.json` (git sha 56dc46c, written by `fleet/benchmark.py`) or the run files copied next to it under `results/fleet/s5_benchmark/{batch,live}/` (`score.json`, `report.md`, `ingest_ledger.json`, `emit_ledger.json`, `hotspots.png`). The two `score.json` files are identical to the `score` blocks inside `benchmark.json`. Platform: `macOS-14.3.1-arm64`. The simulator ran on the Mac host and only Redpanda, ClickHouse and Grafana ran in Docker, because the vendored A* breaks ties differently on Linux ([docs/PLATFORM.md](docs/PLATFORM.md)).

**What it is.** This is a plugin that reads a robot fleet's state logs as they arrive. It finds stuck episodes and names a likely cause. It keeps two ledgers: a volume ledger (what was retrieved and kept) and a decision ledger (every call, graded later against what happened). Think of it as a flight recorder that also writes its own incident reports and later checks whether they were right.

```
fleet/emit.py (simulator, host)        fleet/ingest.py (same pipeline for both sources)
  zone files *.jsonl.gz ---- poll ---> parse -> validate -> per-robot state machine -> ClickHouse
  Kafka topic fleet.state -- consume ->                                                 transitions, stuck_episodes,
  emit_ledger.json (denominator)                                                        decisions, ingest_ledger, rejects
                                     fleet/grade.py, score.py, report.py, alert.py <--- ClickHouse ---> Grafana dashboard
```

**Batch (files from cold).** 8 zones x 12 robots (96 robots) x 72,000 steps, so 100 simulated hours per zone. That is 6,912,000 messages, 3.42 GB uncompressed and 46.7 MB gzip (`emit_ledger.json`), with the `breakdown-heavy` preset under the timeout rule.

| | value |
|---|---|
| emit wall time | 315 s |
| ingest wall time | 2,478 s (41 min) |
| ingest throughput | 2,789 msgs/s, 0.083 GB/min uncompressed (0.0011 GB/min compressed) |
| coverage (accepted / expected from the emit ledger) | 1.0 |
| rejects, duplicates, sequence gaps (`ingest_ledger.json`, 46 minute rows) | 0, 0, 0 |
| bytes kept / read (retention policy) | 0.70 / 3.42 GB = 20.5% |

**Live (Kafka, real time).** The emitter ran at `--speed 1` into Redpanda for 601 s with the ingester on. The feed was 11,520 messages = 19.2 msgs/s, which is the real-time rate of 96 robots at one message per 5 s. This shows the ingester kept up with that feed. It is not a capacity number; the capacity number is the batch one.

| | value |
|---|---|
| coverage | 1.0 |
| lag, wall clock at parse minus message time | p50 2.6 s, p99 5.2 s |
| alert latency from the moment the detector could know (`t_entry`) | p50 8.5 s, p99 9.7 s |
| alert latency from the episode start | p50 38.5 s, p99 39.7 s (30 s of this is the `stuck_after` definition itself) |
| bytes kept / read | 47% (the raw evidence block around each decision weighs more in a short run) |

**Scoring against the simulator's ground truth** (`score.json`; the truth rule and the matching are in the "Sprint 5 / S5C1" note of [docs/SCOPE.md](docs/SCOPE.md)):

| | batch | live |
|---|---|---|
| truth episodes | 5,103 | 16 |
| detected (countable, excluding `faulted_self`) | 16,506 | 93 |
| matched | 3,561 | 16 |
| recall | 0.698 | 1.0 (n = 16) |
| precision | 0.216 | 0.172 |
| unmatched detected: stopped by design / robot frozen inside / short truth run | 5,600 / 7,246 / 99 | 51 / 26 / 0 |
| resolution agreement (`order_dropped` vs simulator abandon) | 0.981 | 1.0 |
| cause agreement with a proximity proxy | 0.907 | 0.938 |

Low precision is mostly a definition gap, not noise. The detector flags every robot that is stopped with an order for 30 s or more. Ground truth counts only stops that the simulator itself flags as stuck. Batch precision with the two named split classes taken out of the denominator: 3,561 / (16,506 - 5,600) = 0.33 without `by_design`, and 3,561 / (16,506 - 5,600 - 7,246) = 0.97 without `frozen` too. Whether a robot waiting at a shelf for 30 s counts as "stuck" is a definition the client has to give us (open operator item). Cause agreement is **not cause accuracy**. The simulator does not expose which robot blocks which, so the score compares the detector's cause with a proximity proxy built from the same public data. Cause accuracy against real ground truth is not measured. A further 12,076 batch episodes are `faulted_self`, and in every one of them the robot is frozen at `t_entry`.

**Decision ledger, batch** (`fleet/grade.py`, one pass after the ingest; the live run's grades were never run, so all of its decisions are still `open`). `stuck_cause`: 7,251 confirmed, 135 refuted, 21,196 inconclusive out of 28,582. Three in four are inconclusive by construction (`fleet/fleet_analyser/grade.py`). The 13,804 `traffic` and `unknown` claims have no grading rule. A `faulted_self` claim is confirmed only when the episode ends with `fault_cleared`. A blocked claim is confirmed only when the robot moved after its named blocker recovered. `avoidable_reset`: 1,821 calls, a reset happened in 1,406, not in 415. The report itself calls "avoidable" near-tautological at 5 s steps: it is every closed `blocked_by_faulted` episode. So these 1,821 are a count, not a finding.

**Report excerpt** (`results/fleet/s5_benchmark/batch/report.md`, 28,582 countable episodes). Duration p50 270 s, p95 1,250 s. Stuck to resolution p50 240 s, p95 1,220 s. Cause mix: unknown 12,597, faulted_self 12,076, blocked_by_faulted 1,825, traffic 1,207, blocked_by_stuck 877. Resolution: order_dropped 15,843, fault_cleared 7,030, moved 5,650, unresolved 59. Top hotspot: zone 6 cell 7-15 with 63 episodes. The load is very uneven across zones under the same preset. Robots in zones 1, 4, 5 and 6 have 390 to 613 episodes each, zones 2 and 3 have 69 to 122, and zones 0 and 7 have 13 to 40. So the top-20 hotspot list comes entirely from zones 1, 4, 5 and 6. This is a seed effect that has not been investigated, and no reading is put on it here.

**Prior art (13 Oct check, rechecked 15 and 18 Oct; fourteen vendors, per-capability table in [docs/COMPETITION.md](docs/COMPETITION.md)).** The dashboard is not new: InOrbit's docs list an "Incidents" map overlay, a "Position (heatmap)" overlay in Time Capsule and SEV-rated incident definitions (https://www.inorbit.ai/docs), Formant's incident-management docs cover threshold events, timelines and analytics dashboards (https://docs.formant.io/docs/incident-management) and its map heatmap overlay is for "spotting where robots repeatedly stop, get stuck, or dwell" (https://docs.formant.io/docs/getting-started-map-heatmap-overlay.md), OTTO's docs correlate task failures with place and have hand-drawn cost zones (https://docs.ottomotors.com), Formant and InOrbit document vendor-agnostic live ingest, MiR Insights advertises bottleneck heatmaps in marketing only, and Ocado (6 River Systems) advertises zones and routing that adjust to live congestion (https://ocadointelligentautomation.com/ocado-iq). Forecast grading, persistence-graded lessons, time-to-detect reporting and a graded decision ledger were not found in the two doc trees we could search in full (Formant, InOrbit) nor on OTTO's public tech-docs pages, and none of the three documents a forecast of stall locations, although failure or bottleneck anticipation is claimed in press or marketing by Exotec, Geek+, Dematic, AutoStore and GreyOrange. MiR, Locus, Geek+, Exotec, Dematic, AutoStore, Symbotic, Körber (Infios), Zebra/Fetch, 6 River Systems and GreyOrange keep their docs behind a login or publish none, and OTTO's help centre is behind a login, so for those twelve every absence is UNTESTED and "not on the shelf" is established for two vendors, not for the market.

**Caveats.**
- The logs are synthetic and clean: zero rejects, zero gaps and zero duplicates is what a simulator produces, not what a real fleet produces. Sprint 6 adds messy text and noise on purpose.
- The parser expects the VDA 5050 state shape. A real client sample needs a mapping file (`fleet/mapping/<client>.yaml`) and the client's own definitions of "stuck" and "manual reset". Neither exists yet.
- Simulator rules, not a real warehouse: no claim transfers to a real fleet.
- The numbers are from one run on one laptop (10 cores, 16 GB), macOS-arm64 only.
- The Grafana dashboard is provisioned, but the benchmark run took no screenshot, so none is shown here.

## Sprint 8, analyst half: floor imperfections and the hotspot map (2026-10-14)

The closed loop of Sprint 8 is "the analyst finds the bad floor, the planner avoids it, reality grades both". This section is the first half, measured; the planner half (cost-aware routing, S8C) is measured in "Sprint 8: the closed loop" below. Lane reports: `reports/wr-lane-s8a.md`, `wr-lane-s8b.md`. Figures: `scripts/plot_sprint8.py` (reads results files only).

### Ground truth: the `floor` disturbance type (S8A)

`floor` = K highway cells, drawn once per (seed, config) from the same candidate set as `blocked_cell` (380 highway non-goal cells on the medium map), each with its own move-failure probability p_c uniform in [lo, hi]. A move INTO a bad cell is skipped with probability p_c ("enter" semantics, drawn in fixed agent order from the disturbance layer's own RNG, so identical across policies). Existing presets are bit-identical to before (regression against `results/recovery/timeout.json` and the undisturbed rows). Two facts the analyser has to live with: a floor skip never reaches the vendor's `StuckCounter`, so it does not show up as stuck time, and it is the robot's NEXT cell that is bad, not the one it reports.

Severity on the medium map, `stuck_aware_cta` with the `timeout` recovery, 30 seeds x 500 steps (`results/stuck_aware_cta_tarware-medium-8agvs-4pickers-globalobs-v1_500_{floor-light,floor-heavy,cfg-*}_timeout.json`; reference = undisturbed CTA, `results/cta_tarware-medium-8agvs-4pickers-globalobs-v1_500.json`):

| bad cells | p range | pick-rate (lines/h) | 95% CI | floor skips / episode |
|---|---|---|---|---|
| 0 (undisturbed CTA) | - | 53.66 | +/- 2.33 | 0 |
| 6 (`floor-light`) | 0.05-0.25 | 52.99 | +/- 2.54 | 5 |
| 12 (`floor-heavy`) | 0.2-0.6 | 53.62 | +/- 2.06 | 35 |
| 40 | 0.3-0.7 | 51.02 | +/- 2.04 | 167 |
| 80 | 0.3-0.7 | 47.52 | +/- 1.60 | 305 |
| 120 | 0.5-0.9 | 34.85 | +/- 1.84 | 950 |
| 200 | 0.5-0.9 | 28.42 | +/- 1.73 | 1278 |

![floor severity](results/floor_severity.png)

The two committed presets are too mild to measure; the Sprint 8 regime is `{"floor": {"cells": 80, "p": [0.3, 0.7]}}`, an 11% loss. Caveat: cells are drawn uniformly over the highway; real floor damage clusters on busy aisles. A traffic-weighted draw is a later one-lane change.

### The hotspot map (S8B)

The analyser never sees `floor_cells`. From the stream alone it counts, per robot, consecutive messages with an active order and no cell change ("stalls"), attributes each stall to the robot's next cell, drops stalls that fall inside detector stuck episodes caused by a faulted blocker, and aggregates per cell with a decayed, count-weighted score into a cost map in [0, 1] (`fleet/costmap.py`). Every publish writes `hotspot_forecast` decisions to the decision ledger; they are graded twice, against the next hour's observed stalls (outcome) and, when a truth sidecar exists, against the real floor cells (truth). The emitter writes that sidecar (`truth.json`) next to the run and never into a message. Scoring: `fleet/hotspot_score.py`, data `results/fleet/hotspot_s8b-medium-80-p03-07.json` (10 zones x 500 steps, seeds 0-9, the 80-cell regime, platform macOS arm64).

| K cells flagged | precision@K (mean of 10 zones) | recall@K |
|---|---|---|
| 20 | 0.965 | 0.241 |
| 40 | 0.825 | 0.412 |
| 80 | 0.556 | 0.556 |
| 120 | 0.371 | 0.556 |

Restated with the station-aware rule in (r).

![hotspot precision recall](results/fleet/hotspot_precision_recall.png)

Random flagging would give precision 80/380 = 0.21. Recall plateaus at 0.56 because 44% of the true bad cells never see a stall in 500 steps (no robot drives into them), which is a traffic ceiling, not a detector limit. Spearman between cost and true p over flagged cells: 0.37. Grading (before S8D): outcome 136 ok / 306 off (the stall-count forecasts are weak; since S8D this count grade is the `outcome_count` key, see below), truth 796 hits / 280 false alarms. Of 2028 stalls, 115 fell inside detector stuck episodes. One zone, cost map against the true cells:

![cost map zone 0](results/fleet/hotspot_costmap_zone0.png)

What this earns: "the stream alone finds the worst floor cells with high precision; it cannot see the ones nobody drives over". What it does not earn yet: any pick-rate recovered, which is S8C's measurement.

## Sprint 8: the closed loop (2026-10-14)

The analyst's cost map goes back to the central planner: `DisturbedWarehouse.find_path` puts weight `1 + alpha * cost` on every mapped cell for every path search (macro-action assignment, vendor replans, recovery reroute, CTA's distance scoring). One run of `scripts/closed_loop.py --seeds 30 --steps 500 --alphas 2,4,8 --workers 8 --out-dir results/closed_loop` Medium map, `stuck_aware_cta` + `timeout`, the Sprint 8 floor regime `{"floor": {"cells": 80, "p": [0.3, 0.7]}}`, seeds 0-29, every arm paired per seed. Phase A emits the 30 zones with no map, ingests them and publishes one cost map per zone at the stream end (`results/closed_loop/phaseA/costmap.json`); Phase B replays seed z with zone z's map. Data: `results/closed_loop/summary.json` (re-aggregated 16 Oct with a `map_a32` arm, see "Sprint 8: sticky floor routing" below), the per-arm results under `results/closed_loop/<arm>/`. Lane report: `reports/wr-lane-s8c.md`.

| arm | map | pick-rate (lines/h) | 95% CI | paired delta vs none (95% CI) | share of the floor loss recovered (95% CI) | routes changed by the map / episode | floor skips / episode |
|---|---|---|---|---|---|---|---|
| none | floor on, no map | 47.52 | 45.85-49.19 | - | - | 0 | 305 |
| map (alpha 4, headline) | analyst map from Phase A | 48.48 | 46.84-50.12 | +0.96 (-0.72 to +2.64) | 15.6% (-11.3% to 45.0%) | 382 | 226 |
| oracle (alpha 4) | the true floor cells, cost = p_c | 48.91 | 46.79-51.04 | +1.39 (-0.36 to +3.15) | 22.7% (-3.8% to 50.0%) | 407 | 192 |
| undisturbed | `--disturb none` | 53.66 | 51.24-56.09 | - | - | 0 | 0 |

The floor loss is undisturbed - none = 6.14 lines/h (11.4%), paired per seed. `none` reproduces the 80-cell row of the severity table above (47.52). Share = mean(arm - none) / mean(undisturbed - none); its CI is a 1000-resample seed bootstrap (seed 0). "Routes changed" counts every `find_path` query whose weighted path differs from the unweighted one, CTA's assignment scoring included, so it is not the number of robots rerouted.

**Alpha sensitivity** (alpha 4 was fixed in `scripts/closed_loop.py` before any result was seen; the other two are a check, not a tuning): floor skips fall monotonically with alpha (305 / 257 / 226 / 179 for none / 2 / 4 / 8) but pick-rate does not follow: +0.34 (-1.72 to +2.39) at alpha 2, +0.96 at alpha 4, -0.82 (-3.16 to +1.53) at alpha 8. At alpha 8 the detours cost more than the skips they save.

![closed loop](results/closed_loop/closed_loop.png)

**The claim this earns: it does not.** At 30 seeds the analyser's map does not recover a measurable share of the floor loss: point estimate 15.6% (CI -11% to 45%). The oracle does not clear zero either: 22.7% (CI -4% to 50%). The map cuts floor skips by 26% and the oracle by 37%, but at this sample size the rig cannot separate map from oracle, or either from no map. So the analyst's information is not shown to be the bottleneck. A map-vs-oracle ratio would be a ratio of two noise-level numbers; there is no paired map-vs-oracle CI, so none is claimed.

**Grading the hotspot forecasts (S8D).** S8B graded each `hotspot_forecast` on whether the cell's stall count next hour came out near the claim. S8D grades it on rank (is the cell still in the zone's top 20 at the horizon end) and keeps the count grade as `outcome_count`. Same data, `results/fleet/hotspot_s8b-medium-80-p03-07.json` (re-scored in 274e20f):

| grade | before S8D (56dc46c) | after S8D (274e20f) |
|---|---|---|
| count grade | `outcome`: 136 ok / 306 off (442) | `outcome_count`: 136 ok / 306 off (442), identical |
| rank grade, top 20 at the horizon end | - | `outcome`: 120 ok / 80 off (200 rank-graded) |
| not rank-graded (claim rank > 20) | - | 242 `unranked` (truth-graded only) |
| truth | 796 hit / 280 false alarm | 796 hit / 280 false alarm |

60% of the top-20 forecasts are still in the top 20 an hour later. Precision, recall and Spearman are unchanged.

**Replay page.** [`docs/replay/index.html`](docs/replay/index.html) (opens from disk, no server needed) replays one zone (seed 0, 500 steps) in three panels on one timeline: the hidden floor, the extractor's counters and the analyst's map (two publishes, at steps 250 and 499). You can toggle a re-run of the same seed with the map switched on. Its grades are the pre-S8D count grade. Its with-map layer is in-sample (the final map of that same episode, on from step 0). The page has not yet been checked in a browser.

**Caveats.**
- The floor is a uniform draw over the 380 highway cells. Real damage clusters on busy aisles. What a traffic-weighted draw would do is untested, and it could move either arm.
- One context layer (`floor`) only. The other layers are not built.
- The map is "yesterday's data" from the same seed. Phase A runs seed z with no map, and Phase B runs seed z again with that map, so the floor layout and the demand are identical. That is in-sample and optimistic: a real deployment would face a new day.
- The oracle is an upper bound on the map's information, not on its penalty. Oracle costs are p_c in [0.3, 0.7], while the analyst map is normalised to 1.0 per zone, so at the same alpha the analyst map penalises its top cells harder. Map <= oracle is not guaranteed.
- The logs are synthetic: VDA 5050-shaped messages emitted by this simulator, not a client fleet.
- The numbers are macOS arm64 only (pyastar2d tie-break, `docs/PLATFORM.md`). At alpha 4 with an analyst cost of 1.0, an open-grid sidestep is an exact tie (alpha * cost = 4 = the extra steps and turns), and darwin breaks it toward going straight.
- The figure is drawn from `summary.json` by `scripts/closed_loop.py`.

## Sprint 8: sticky floor routing, dose-response and guidance tuning (2026-10-16)

The README had no sticky-routing section before this one. The sticky regime (80 cells, p 0.9-0.99) is the default of the live demo (`docs/DEMO.md` section 8). Follow-ups to the closed loop above. The routing ones (a-c) all use `stuck_aware_cta` + `timeout` on the medium map, every arm paired per seed against `none`; (d) and (e) grade the analyser itself. Everything between this paragraph and "Reading the numbers" is the output of `.venv/bin/python scripts/sprint8_tables.py`, which reads the JSONs it names. Only its headings were demoted one level. In-sample and held-out are side by side so the gap stays visible. The oracle runs at alpha 4 in every regime. `map_aN` is the cost map at alpha N, and `map_tuned` is the tuned transform, with its parameters printed in (c). Updated 2026-10-16 (evening) with alphas 8 and 16 at p 0.6-0.9 and p 0.8-0.95, guidance tuning on p 0.8-0.95, time to detect and the lesson_persist chance rate.

#### (a) Dose-response: map benefit by floor stickiness (30 seeds x 500 steps)

| floor regime (80 cells) | floor loss (lines/h) | none (lines/h) | map_a4 share | map_a8 share | map_a16 share | map_a32 share | oracle (alpha 4) share |
|---|---|---|---|---|---|---|---|
| p 0.3-0.7 | 6.14 | 47.52 (45.85-49.19) | 15.6% (-11.3% to 45.0%) | -13.3% (-62.5% to 20.3%) | - | -92.2% (-196.5% to -49.7%) | 22.7% (-3.8% to 50.0%) |
| p 0.6-0.9 | 15.70 | 37.97 (36.22-39.71) | 15.9% (9.2% to 22.3%) | 6.7% (-2.7% to 15.8%) | 6.7% (-2.1% to 16.2%) | -10.4% (-23.5% to 1.2%) | 14.4% (5.2% to 22.5%) |
| p 0.8-0.95 | 26.16 | 27.50 (26.31-28.70) | 10.3% (4.3% to 15.7%) | 14.1% (7.7% to 20.1%) | 14.1% (8.7% to 19.6%) | 15.2% (9.2% to 20.7%) | 27.7% (22.0% to 34.1%) |
| p 0.9-0.99 | 37.54 | 16.13 (14.62-17.63) | 3.7% (0.7% to 7.2%) | - | 9.1% (5.5% to 12.6%) | 11.1% (6.0% to 15.9%) | 15.9% (11.9% to 20.3%) |

Pick-rate by arm, lines/h, mean (95% CI):

| floor regime | map_a4 | map_a8 | map_a16 | map_a32 | oracle | undisturbed |
|---|---|---|---|---|---|---|
| p 0.3-0.7 | 48.48 (46.84-50.12) | 46.70 (44.61-48.80) | - | 41.86 (39.86-43.85) | 48.91 (46.79-51.04) | 53.66 (51.24-56.09) |
| p 0.6-0.9 | 40.46 (38.92-42.01) | 39.02 (37.13-40.91) | 39.02 (37.35-40.70) | 36.34 (34.57-38.10) | 40.22 (38.52-41.92) | 53.66 (51.24-56.09) |
| p 0.8-0.95 | 30.19 (28.39-31.99) | 31.20 (29.24-33.16) | 31.20 (29.52-32.88) | 31.49 (29.82-33.15) | 34.75 (33.11-36.40) | 53.66 (51.24-56.09) |
| p 0.9-0.99 | 17.52 (15.89-19.15) | - | 19.54 (17.75-21.33) | 20.30 (18.28-22.33) | 22.08 (19.97-24.19) | 53.66 (51.24-56.09) |

Paired between fixed alphas (the arm with the highest mean pick-rate in each regime minus each other fixed alpha, lines/h, 95% CI):

| floor regime | top fixed alpha (point estimate) | minus | delta (95% CI) | verdict |
|---|---|---|---|---|
| p 0.3-0.7 | map_a4 | map_a8 | +1.78 (-0.21 to +3.76) | within noise |
| p 0.3-0.7 | map_a4 | map_a32 | +6.62 (+4.94 to +8.31) | beats |
| p 0.6-0.9 | map_a4 | map_a8 | +1.44 (+0.18 to +2.70) | beats |
| p 0.6-0.9 | map_a4 | map_a16 | +1.44 (-0.11 to +2.99) | within noise |
| p 0.6-0.9 | map_a4 | map_a32 | +4.13 (+2.38 to +5.87) | beats |
| p 0.8-0.95 | map_a32 | map_a4 | +1.30 (-0.27 to +2.86) | within noise |
| p 0.8-0.95 | map_a32 | map_a8 | +0.29 (-0.80 to +1.38) | within noise |
| p 0.8-0.95 | map_a32 | map_a16 | +0.29 (-0.66 to +1.24) | within noise |
| p 0.9-0.99 | map_a32 | map_a4 | +2.78 (+0.75 to +4.82) | beats |
| p 0.9-0.99 | map_a32 | map_a16 | +0.77 (-0.95 to +2.48) | within noise |

Share = mean(arm - none) / mean(undisturbed - none), paired per seed, with a 1000-resample seed-bootstrap CI; "-" = the regime's summary has no such arm. Ties in the top-alpha pick use the first in alpha order. Sources: `results/closed_loop/summary.json`, `results/closed_loop_p06_09/summary.json`, `results/closed_loop_p08_095/summary.json`, `results/closed_loop_sticky/summary.json`; the between-alpha rows are computed by `scripts/sprint8_tables.py` from `<regime>/<arm>/*.json` with `evaluate.paired_delta`.

#### (b) Longer shift

**1,500-step shift, sticky regime (p 0.9-0.99, 30 seeds).** Floor loss 37.54 lines/h at 500 steps, 36.64 at 1500. Share of the loss recovered: map_a4 3.7% (0.7% to 7.2%) at 500 -> 4.8% (2.2% to 7.5%) at 1,500; map_a32 11.1% (6.0% to 15.9%) at 500 -> 8.6% (5.7% to 11.5%) at 1,500; oracle 15.9% (11.9% to 20.3%) at 500 -> 16.4% (13.1% to 19.8%) at 1,500. Phase A maps differ (tag `30b4c70868` from a 500-step day, `e773b55cf1` from a 1,500-step day); there is no paired 500-vs-1,500 CI. Sources: `results/closed_loop_sticky/summary.json`, `results/closed_loop_sticky_1500/summary.json`.

#### (c) Guidance tuning (S8M), two regimes

**`results/guidance/sticky`**

**Train (seeds 0-9, 48 evaluations, random search seed 0).** Objective = mean paired pick-rate gain over none on the train seeds. Identity (eval 0, alpha 4, gamma 1, tau 0, dilate 0) +1.440; best (eval 20: alpha 50.3, gamma 1.41, tau 0.053, dilate 0) +2.016 lines/h.
Check: identity objective +1.440 vs in-sample map_a4 delta +1.440; best objective +2.016 vs in-sample map_tuned delta +2.016.

| arm | held-out seeds 10-29 (n=20): delta vs none (95% CI) | held-out share (95% CI) | in-sample seeds 0-9 (n=10): delta vs none (95% CI) | verdict vs none, held-out |
|---|---|---|---|---|
| map_a4 | +1.37 (-0.37 to +3.11) | 3.7% (-0.4% to 7.8%) | +1.44 (-0.79 to +3.67) | within noise |
| map_a32 | +5.33 (+2.83 to +7.82) | 14.3% (8.4% to 20.6%) | +1.87 (-1.42 to +5.17) | beats |
| map_tuned | +4.18 (+2.30 to +6.06) | 11.2% (6.5% to 16.3%) | +2.02 (-1.14 to +5.17) | beats |
| oracle | +6.98 (+4.60 to +9.37) | 18.8% (13.0% to 24.1%) | +3.89 (+1.77 to +6.01) | beats |

| paired delta | held-out (95% CI) | verdict | in-sample (95% CI) |
|---|---|---|---|
| map_tuned - map_a4 | +2.81 (+1.09 to +4.52) | beats | +0.58 (-3.37 to +4.53) |
| map_tuned - map_a32 | -1.15 (-2.80 to +0.49) | within noise | +0.14 (-0.76 to +1.05) |

Sources: `results/guidance/sticky/tune.json`, `results/guidance/sticky/best_transform.json`, `results/guidance/sticky/heldout.json`; the paired tuned-vs-fixed rows are computed by `scripts/sprint8_tables.py` from `results/guidance/sticky/map_tuned/stuck_aware_cta_tarware-medium-8agvs-4pickers-globalobs-v1_500_cfg-86550f4e27_timeout_cm-c16a06c160.json` (held-out), `results/guidance/sticky/evals/20/stuck_aware_cta_tarware-medium-8agvs-4pickers-globalobs-v1_500_cfg-86550f4e27_timeout_cm-883ecd5387.json` (in-sample) and `results/closed_loop_sticky/{map_a4,map_a32}/*.json` with `evaluate.paired_delta`.

**`results/guidance/p08_095`**

**Train (seeds 0-9, 48 evaluations, random search seed 0).** Objective = mean paired pick-rate gain over none on the train seeds. Identity (eval 0, alpha 4, gamma 1, tau 0, dilate 0) +2.160; best (eval 10: alpha 1.8, gamma 2.30, tau 0.263, dilate 0) +3.600 lines/h.
Check: identity objective +2.160 vs in-sample map_a4 delta +2.160; best objective +3.600 vs in-sample map_tuned delta +3.600.

| arm | held-out seeds 10-29 (n=20): delta vs none (95% CI) | held-out share (95% CI) | in-sample seeds 0-9 (n=10): delta vs none (95% CI) | verdict vs none, held-out |
|---|---|---|---|---|
| map_a4 | +2.95 (+0.76 to +5.14) | 11.7% (4.1% to 18.5%) | +2.16 (-0.37 to +4.69) | beats |
| map_a32 | +4.32 (+2.16 to +6.48) | 17.1% (9.6% to 23.9%) | +3.31 (+0.32 to +6.31) | beats |
| map_tuned | +0.72 (-0.82 to +2.26) | 2.8% (-2.4% to 8.7%) | +3.60 (+1.02 to +6.18) | within noise |
| oracle | +7.42 (+5.11 to +9.72) | 29.3% (21.2% to 38.9%) | +6.91 (+4.54 to +9.28) | beats |

| paired delta | held-out (95% CI) | verdict | in-sample (95% CI) |
|---|---|---|---|
| map_tuned - map_a4 | -2.23 (-4.51 to +0.05) | within noise | +1.44 (-1.08 to +3.96) |
| map_tuned - map_a32 | -3.60 (-5.89 to -1.31) | worse | +0.29 (-1.52 to +2.09) |

Sources: `results/guidance/p08_095/tune.json`, `results/guidance/p08_095/best_transform.json`, `results/guidance/p08_095/heldout.json`; the paired tuned-vs-fixed rows are computed by `scripts/sprint8_tables.py` from `results/guidance/p08_095/map_tuned/stuck_aware_cta_tarware-medium-8agvs-4pickers-globalobs-v1_500_cfg-9e41bd6eef_timeout_cm-1be39504d0.json` (held-out), `results/guidance/p08_095/evals/10/stuck_aware_cta_tarware-medium-8agvs-4pickers-globalobs-v1_500_cfg-9e41bd6eef_timeout_cm-9ef1aebcf3.json` (in-sample) and `results/closed_loop_p08_095/{map_a4,map_a32}/*.json` with `evaluate.paired_delta`.

Side by side (map_tuned on held-out seeds 10-29, paired per seed):

| held-out seeds 10-29, paired | p 0.9-0.99 (tuned alpha 50.31) | p 0.8-0.95 (tuned alpha 1.75) |
|---|---|---|
| map_tuned - none | +4.18 (+2.30 to +6.06) **beats** (in-sample +2.02 (-1.14 to +5.17)) | +0.72 (-0.82 to +2.26) **within noise** (in-sample +3.60 (+1.02 to +6.18)) |
| map_tuned - map_a4 | +2.81 (+1.09 to +4.52) **beats** (in-sample +0.58 (-3.37 to +4.53)) | -2.23 (-4.51 to +0.05) **within noise** (in-sample +1.44 (-1.08 to +3.96)) |
| map_tuned - map_a32 | -1.15 (-2.80 to +0.49) **within noise** (in-sample +0.14 (-0.76 to +1.05)) | -3.60 (-5.89 to -1.31) **worse** (in-sample +0.29 (-1.52 to +2.09)) |

#### (d) Time to detect (S8P), sticky regime

| K (per zone) | 500 steps: truth cells seen by shift end | 500 steps: first detect, min, median (p25-p75) | 500 steps: false flags per publish, 30 zones summed (per zone) | 1500 steps: truth cells seen by shift end | 1500 steps: first detect, min, median (p25-p75) | 1500 steps: false flags per publish, 30 zones summed (per zone) |
|---|---|---|---|---|---|---|
| 10 | 32.7% | 10 (5-20) | 10.6 (0.35) | 44.9% | 15 (5-55) | 4.7 (0.16) |
| 20 | 44.0% | 10 (5-25) | 39.0 (1.30) | 57.5% | 20 (5-50) | 23.1 (0.77) |
| 40 | 46.9% | 15 (5-25) | 90.9 (3.03) | 66.5% | 25 (10-55) | 140.3 (4.68) |

- `results/fleet/time_to_detect_sticky500.json`: 500 steps = 41.7 simulated min, 30 zones, 2400 truth cells, 9 publishes every 5 min, {"floor": {"cells": 80, "p": [0.9, 0.99]}}, phase A `results/closed_loop_sticky/phaseA`.
- `results/fleet/time_to_detect_sticky1500.json`: 1500 steps = 125.0 simulated min, 30 zones, 2400 truth cells, 25 publishes every 5 min, {"floor": {"cells": 80, "p": [0.9, 0.99]}}, phase A `results/closed_loop_sticky_1500/phaseA`.

Times are simulated minutes since the zone's first message, over the detected cells only, so they move in steps of the publish cadence; K is the per-zone top-K of the hotspot map; a false flag is a top-K cell that is not a truth cell. Caveat (verbatim from the JSON): "Floors are static from step 0, so this measures time to see what is already there, not reaction to a change."

#### (e) lesson_persist against its chance rate (S8S)

| run tag (lesson window, h) | lessons graded (by kind) | persisted (observed rate) | chance mean (median) | lift |
|---|---|---|---|---|
| s8e-long-w0.2 | 14 (hot_cell 4 ok / 9 off, hot_robot 0 ok / 1 off) | 4 (0.286) | 0.179 (0.161) | 1.60 |
| s8e-long-w0.5 | 25 (hot_cell 18 ok / 7 off) | 18 (0.720) | 0.241 (0.250) | 2.99 |
| s8e-long-w1.0 | 13 (hot_cell 12 ok / 1 off) | 12 (0.923) | 0.256 (0.250) | 3.60 |

Chance = for each lesson, the share of its own candidate pool (every cell with >= 1 stall, or every robot with >= 1 episode, in the lesson's zone and window) that persists over the next window by the same bar; lift = observed rate / chance mean. Pools are shared between lessons of the same zone and window, and there is no CI on the lift. The window is the `--window-h` named in the run tag. Sources: `results/fleet/hotspot_s8e-long-w0.2.json`, `results/fleet/hotspot_s8e-long-w0.5.json`, `results/fleet/hotspot_s8e-long-w1.0.json` (`lesson_persist_chance`, `lesson_grading.lesson_persist`).

**Reading the numbers.**
- **Dose-response.** No one fixed alpha is best across regimes. Alpha 4 has the highest mean at p 0.3-0.7 and p 0.6-0.9 and alpha 32 at p 0.8-0.95 and p 0.9-0.99, but the paired between-alpha table separates them only in places: alpha 4 beats alpha 32 at p 0.3-0.7 and p 0.6-0.9 and beats alpha 8 at p 0.6-0.9, alpha 32 beats alpha 4 at p 0.9-0.99, and at p 0.8-0.95 alphas 4 to 32 are all within noise of each other.
  - At p 0.3-0.7, alpha 32 is clearly worse than no map.
  - From p 0.8 up, alpha 32 beats no map.
  - The alpha-4 map's share separates from zero from p 0.6 up, but its point estimate shrinks as the floor gets stickier.
  - Alphas 8 and 16 sit between 4 and 32 and do not clear zero at p 0.6-0.9. Their mean pick-rates are equal to the third decimal in both new regimes. The per-seed rows and the skip/route counts differ (checked against the per-arm JSONs), so this is a tie in the sum on the 1.44 lines/h grid of a 500-step run, not a copied result.
  - The sticky regime's summary has no alpha-8 arm. A `results/closed_loop_sticky/map_a8/` result exists on disk but was never aggregated into that summary, so it is not shown.
  - The oracle clears zero from p 0.6 up. It runs at alpha 4 only, so it bounds the information at that penalty, not the achievable gain.
- **Longer shift.** Nothing shows the map's share growing over a 1,500-step shift:
  - The alpha-4 and oracle shares are within each other's CIs at 500 and 1,500 steps.
  - The alpha-32 point estimate is lower at 1,500 steps.
  - The two lengths use different phase-A maps, and there is no paired 500-vs-1,500 CI, so "it shrinks" is not claimed either.
- **Guidance tuning, sticky regime (p 0.9-0.99).**
  - On the train seeds the search beat the identity transform (best objective vs eval 0 above), but in-sample no map arm's delta vs none clears zero at n=10.
  - On the held-out seeds 10-29, `map_tuned` **beats** no map and **beats** the identity (`map_a4`). Against the fixed `map_a32` it is **within noise**, and its point estimate is lower.
  - Tuning landed on a high alpha, like `map_a32`, and nothing in these numbers shows it beating that fixed map.
  - On seeds 10-29, `map_a32`, `map_tuned` and the oracle all gain more than on seeds 0-9, while `map_a4` gains about the same. Since an untuned map and the oracle move the same way, the in-sample/held-out gap is a difference between the seed sets, not a tuning effect.
- **Guidance tuning, p 0.8-0.95.** The opposite of the sticky result.
  - Tuning landed on a low alpha (below every fixed arm) and beat the identity on the train seeds, where `map_tuned` also clears zero against no map.
  - On the held-out seeds it is **within noise** of no map, **within noise** of the identity (`map_a4`, point estimate lower) and **worse** than the fixed `map_a32`.
  - Here the drop from in-sample to held-out is specific to `map_tuned`: `map_a4`, `map_a32` and the oracle all keep or grow their gain on seeds 10-29. That pattern fits a transform selected on 10 seeds that does not carry over, not a seed-set difference.
  - Across both regimes, the tuning search is not shown to beat a plain fixed alpha 32 on a floor with p >= 0.8.
- **Time to detect (sticky regime).** Most cells the map ever ranks in its top K show up early in the shift, and a longer shift shows more of them, but never all.
  - At 500 steps the per-zone top 10 has shown about a third of the truth cells by shift end; at 1,500 steps more, and more again at larger K.
  - False flags per publish grow with K. At K 10 they are well under one per zone per publish.
  - The floors are static from step 0 (caveat above), so this is time to see what is already there, not time to react to a new bad cell.
- **lesson_persist against chance.** At every window the observed persist rate is above the chance mean of the lesson's own candidate pool, and the lift grows with the window. There is no CI on the lift and the pools are shared, so this is a direction, not a significance claim.
  - At window 0.2 h, the chance block counts 14 lessons (4 ok) because it includes one hot_robot lesson; the hot_cell-only lesson_persist grade is 4 ok / 9 off (the by-kind column).

**Caveats** (on top of the closed-loop ones above):
- Every phase-A map is in-sample "yesterday's data" from the same seed.
- The alpha-8, -16 and -32 arms were added after alpha 4 had been seen, so they are checks, not pre-registered headlines. The between-alpha comparison picks the top arm by its point estimate first, then tests it, so its "beats" rows lean optimistic.
- `map_tuned` was chosen on 10 seeds out of 48 random draws, separately per regime.
- The numbers are macOS arm64 only.

## Sprint 10: the analyser on other disturbances, time to detect and time to clear (2026-10-18)

S10A (PR #36) gave the ground truth time windows (`fleet-truth/2`: blocked, outage and frozen windows per zone, burst per zone). The queue item `wr-s10-disturbance-measure` ran the analyser chain (emit, ingest, costmap, lessons, grade, hotspot_score) on four presets, 10 zones x 500 steps on the medium map, seeds 0-9. The presets were chosen by truth coverage (report `wr-lane-s10a-truth-v2.md`). S10B (PR #38) added `--truth-kind blocked|outage` to `fleet/time_to_detect.py`. Everything between this paragraph and "Reading the numbers" is the output of sections (f) and (g) of `.venv/bin/python scripts/sprint8_tables.py`, which reads the JSONs it names. Only its headings were demoted one level.

#### (f) Analyser on other disturbances (S10A truth v2, 10 zones x 500 steps)

Truth positives per run (cells are counted once per kind over the whole run, robots by distinct serial):

| run | disturbance | floor cells | blocked cells | outage cells | frozen robots | flagged cells per zone, mean |
|---|---|---|---|---|---|---|
| s10-blocked | `{"blocked_cell": {"rate_per_hour": 8.0, "duration": [60, 240]}}` | 0 | 50 | 0 | 0 | 26.7 |
| s10-outage | `{"outage": {"rate_per_hour": 4.0, "duration": [120, 360]}}` | 0 | 0 | 20 | 0 | 26.8 |
| s10-breakdown | `{"breakdown": {"rate_per_hour": 8.0, "duration": [20, 60]}}` | 0 | 0 | 0 | 119 | 8.9 |
| s10-burst | `{"burst": {"start": 100, "end": 300, "extra": 20}}` | 0 | 0 | 0 | 0 | 25.7 |

Precision and recall at K, split by kind (only kinds with positives in the run; pooled over zones; frozen cells = the robot's cell at the start of each frozen window, S10G):

| run | kind | positives | K 20: hits, precision, recall | K 40: hits, precision, recall | zones flagging fewer than K cells (K 20 / K 40) |
|---|---|---|---|---|---|
| s10-blocked | blocked | 50 | 4, 0.0200, 0.08 | 7, 0.0175, 0.14 | 1 / 10 |
| s10-outage | outage | 20 | 1, 0.0050, 0.05 | 1, 0.0025, 0.05 | 0 / 10 |
| s10-breakdown | frozen cells | 283 | 19, 0.0950, 0.07 | 19, 0.0475, 0.07 | 10 / 10 |
| s10-burst | none | 0 cells (the run has no truth cells) | n/a | n/a | 1 / 10 |

Restated with the station-aware rule in (r) for s10-breakdown only; s10-blocked, s10-outage and s10-burst were not rerun.

False flags (top-K cells that are not a truth cell of any kind, summed over 10 zones, on the final map) and the forecast truth grades:

| run | K 20: false flags (per zone) | K 40: false flags (per zone) | hotspot_forecast truth grades: false_alarm / graded |
|---|---|---|---|
| s10-blocked | 195 (19.5) | 260 (26.0) | 1386 / 1409 |
| s10-outage | 199 (19.9) | 267 (26.7) | 1414 / 1417 |
| s10-breakdown | 70 (7.0) | 70 (7.0) | 463 / 488 |
| s10-burst | 195 (19.5) | 257 (25.7) | 1388 / 1388 |

Restated with the station-aware rule in (r) for s10-breakdown only; s10-blocked, s10-outage and s10-burst were not rerun.

lesson_persist and its chance rate:

| run | stream length (s) | lesson_truth grades (by lesson kind) | lesson_persist graded | observed rate | chance mean | lift |
|---|---|---|---|---|---|---|
| s10-blocked | 2500 | hot_cell 3 false_alarm, hot_robot 2 false_alarm | 0 | n/a | n/a | n/a |
| s10-outage | 2500 | hot_cell 4 false_alarm, hot_robot 2 false_alarm | 0 | n/a | n/a | n/a |
| s10-breakdown | 2500 | hot_robot 1 false_alarm, 1 hit | 2 | 0.000 | 0.582 | 0.00 |
| s10-burst | 2500 | hot_cell 6 false_alarm, hot_robot 2 false_alarm | 0 | n/a | n/a | n/a |

`truth_kinds` is run-level: a cell is positive for a kind if the truth lists it at any time in the run, and the map is the final one, so a hit does not mean the cell was flagged while it was blocked (time is in (g)). Precision = hits / (K x zones), so zones that flag fewer than K cells still count K. false flags = sum over zones of min(K, flagged cells) minus the `any` hits. The floor-based `mean.k` block of these JSONs is not used: no S10 run has floor cells. lesson_persist grades a lesson with window [s, e) over [e, e + W) only when the zone's stream reaches e + W (`fleet/fleet_analyser/lessons.py` docstring); the queue item `wr-s10-disturbance-measure` ran lessons with `--window-h 0.5` (1800 s), so a 2500 s stream allows no graded lesson. s10-breakdown was re-emitted bit-identically and re-scored by `wr-s10g-breakdown-rerun` (S10G truth with frozen cells, lessons `--window-h 0.2`), so its row is the re-score. Sources: `results/fleet/hotspot_s10-blocked.json`, `results/fleet/hotspot_s10-outage.json`, `results/fleet/hotspot_s10-breakdown.json`, `results/fleet/hotspot_s10-burst.json` (`truth_kinds`, `zones.*.n_flagged`, `grading_counts.truth`, `lesson_grading`, `lesson_persist_chance`).

#### (g) Time to detect and time to clear (S10B)

| kind | K (per zone) | windows | detected (share) | missed | preflag | first detect, s, median (p25-p75) | cleared | cleared, s after end, median (p25-p75) | stale_at_end | open_at_end | false flags per publish, 10 zones summed (per zone) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| blocked | 10 | 50 | 6 (0.12) | 44 | 1 | 187.5 (117.5-242.5) | 3 | 155 (95-172.5) | 1 | 2 | 83.0 (8.30) |
| blocked | 20 | 50 | 7 (0.14) | 43 | 2 | 190 (140-232.5) | 2 | 970 (910-1030) | 2 | 3 | 135.8 (13.58) |
| blocked | 40 | 50 | 7 (0.14) | 43 | 2 | 190 (140-232.5) | 0 | none | 4 | 3 | 154.6 (15.46) |
| outage | 10 | 20 | 1 (0.05) | 19 | 0 | 280 (280-280) | 0 | none | 0 | 1 | 85.0 (8.50) |
| outage | 20 | 20 | 1 (0.05) | 19 | 0 | 280 (280-280) | 0 | none | 0 | 1 | 139.0 (13.90) |
| outage | 40 | 20 | 1 (0.05) | 19 | 0 | 280 (280-280) | 0 | none | 0 | 1 | 157.1 (15.71) |

- `results/fleet/time_to_detect_blocked.json`: blocked, run `s10-blocked`, 500 steps = 41.7 simulated min, 10 zones, 50 windows (median length 132 steps), 9 publishes every 5 min, `{"blocked_cell": {"rate_per_hour": 8.0, "duration": [60, 240]}}`, phase A `fleet/data/s10-blocked`.
- `results/fleet/time_to_detect_outage.json`: outage, run `s10-outage`, 500 steps = 41.7 simulated min, 10 zones, 20 windows (median length 171.5 steps), 9 publishes every 5 min, `{"outage": {"rate_per_hour": 4.0, "duration": [120, 360]}}`, phase A `fleet/data/s10-outage`.

Per window: detected = the cell is in the zone's top K at a publish while the window is open; preflag = in the top K at the last publish before the window opened (not a detection); first detect is seconds from the window's start. Over detected windows only: cleared = the first publish at or after the end where the cell is out of the top K (seconds from the end); stale_at_end = still in the top K at every publish after the end; open_at_end = no publish after the end, so clearing is not observed. cleared = detected - stale_at_end - open_at_end (asserted here). "none" = no window to take a median over. A flag counts as false only when the cell matches no truth window of any kind at that publish. Caveat (verbatim from the JSON): "Windows have a start and an end; detection is measured from the start, clearing from the end."

**Reading the numbers.**
- **Blocked cells.** In the final map, 4 of the 50 blocked cells are in a zone's top 20 (recall 0.08) and 7 are in a zone's top 40 (recall 0.14). Precision is 0.02 or lower at both K. Over time (g), 7 of the 50 windows were in the top 20 at some publish while they were open; 43 were missed and 2 were preflagged. The median first detection is 190 s after the window opened, which is less than one publish interval (300 s).
- **Outages.** 1 of the 20 outage cells is in the final top 20 and top 40 (recall 0.05). Over time, 1 of 20 windows was detected, at 280 s. That window was still open at the last publish, so whether it cleared is not observed.
- **Clearing.** Of the 7 detected blocked windows at K 20, 2 cleared (median 970 s after the window ended), 2 were stale at the end and 3 were open at the end. At K 40, none cleared: 4 were stale and 3 were open. At K 10, 3 of the 6 detected windows cleared, median 155 s after the end. All of these counts are 3 or fewer, so the medians rest on 0 to 3 windows.
- **False flags.** The burst run has no truth cells, so all its flagged cells are false: 195 in the top 20 over 10 zones (19.5 per zone) and 257 in the top 40. The blocked and outage runs have 195 and 199 false flags in the top 20, and 260 and 267 in the top 40. That is within 4 (K 20) and 10 (K 40) of the burst run, which has no truth at all. Per publish (g), the blocked and outage maps carry 83 to 157 false flags over 10 zones, and the count rises with K.
- **Forecast grades.** 23 of 1,409 `hotspot_forecast` truth grades are hits on the blocked run and 3 of 1,417 on the outage run. All 1,388 on the burst run are false alarms. On the breakdown run 25 of 488 are hits since the S10G re-score (19 Oct, (m)); before it, all 488 were false alarms because frozen windows carried no cell.
- **Breakdown.** The run has 119 frozen robots. Since S10G their cells are truth cells: 283 frozen cells over 10 zones. The map flags 8.9 cells per zone on average, and 19 of the 89 flagged cells are frozen cells (recall 0.07). Details in (m).
- **Lessons.** On the four 2026-10-18 presets, no lesson_persist row was graded. A 0.5 h lesson window needs 3,600 s of stream to be graded over its next window, and each zone streams 2,500 s. Against truth, all 13 hot_cell lessons and all 6 hot_robot lessons across the blocked, outage and burst runs are false alarms. The breakdown re-score ran lessons at 0.2 h: 2 hot_robot lessons were graded for persistence and neither persisted (chance 0.582). Against truth, 1 of its 2 hot_robot lessons is a hit.
- **Against the sticky floor (d).** On the sticky floor the per-zone top 20 had shown 44.0% of the truth cells by the end of a 500-step shift. Here it caught 14% of blocked windows and 5% of outage windows. These are different units (static cells there, time windows here), so the comparison is about scale only.

**Caveats.**
- One seed set (0-9) and one 500-step shift per preset, with no CI on any count here.
- The undisturbed run is set against these in (i) below. Why the map misses known blockages is explained by the mechanism audit in `docs/SCOPE.md`: the planner routes around them.
- The (f) hits are run-level (final map, truth at any time). Only (g) is time-resolved.
- In (g) a flag matching a truth window of any kind counts as not false. Each S10 run holds only its own kind, so this does not move these numbers.
- The numbers are macOS arm64 only.

### Sprint 10, second half: planner-blind blockage, undisturbed reference, persistence, AMOC (2026-10-19)

The mechanism audit (`docs/SCOPE.md`, 2026-10-18) found that the known blockages of (f) and (g) never tested the analyser: the planner routes around them. Four lanes and four queue runs followed. S10C (PR #40) added `blocked_cell` with `"known": false`, a blockage the planner does not see, with the robot hidden from the StuckCounter like a floor cell. The queue item `wr-s10c-blind-run` ran it on the same 50 windows as s10-blocked. `wr-s10-none-run` ran the same 10 zones x 500 steps with no disturbance. S10D (PR #39) added `hotspot_score.py --baselines`: a persistence forecast (the same window count without decay) and chance lines. `wr-s10d-baselines-run` re-scored five runs with it. S10E (PR #41) added the AMOC sweep to `fleet/time_to_detect.py`, run as `wr-s10e-amoc-run`. Everything between this paragraph and the next "Reading the numbers" is the output of sections (h) to (k) of `.venv/bin/python scripts/sprint8_tables.py`. Only its headings were demoted one level.

#### (h) Planner-blind blockage next to the known blockage (S10C)

Final map (run-level, as in (f)):

| run | planner knows the cell | blocked cells | K 20: hits, precision, recall | K 40: hits, precision, recall | K 20: false flags (per zone) | K 40: false flags (per zone) | hotspot_forecast truth grades: hit / graded |
|---|---|---|---|---|---|---|---|
| s10-blocked | yes | 50 | 4, 0.0200, 0.08 | 7, 0.0175, 0.14 | 195 (19.5) | 260 (26.0) | 23 / 1409 |
| s10c-blind | no | 50 | 17, 0.0850, 0.34 | 20, 0.0500, 0.40 | 183 (18.3) | 241 (24.1) | 16 / 1363 |

Restated with the station-aware rule in (r) for s10c-blind only; s10-blocked was not rerun.

Over time (as in (g)), the same 50 windows on both runs:

| K (per zone) | run | detected (share) | missed | preflag | first detect, s, median (p25-p75) | cleared | stale_at_end | open_at_end | false flags per publish, 10 zones summed (per zone) |
|---|---|---|---|---|---|---|---|---|---|
| 10 | s10-blocked | 6 (0.12) | 44 | 1 | 187.5 (117.5-242.5) | 3 | 1 | 2 | 83.0 (8.30) |
| 10 | s10c-blind | 6 (0.12) | 44 | 1 | 402.5 (277.5-568.75) | 0 | 2 | 4 | 83.6 (8.36) |
| 20 | s10-blocked | 7 (0.14) | 43 | 2 | 190 (140-232.5) | 2 | 2 | 3 | 135.8 (13.58) |
| 20 | s10c-blind | 6 (0.12) | 44 | 2 | 295 (218.75-438.75) | 0 | 2 | 4 | 135.1 (13.51) |
| 40 | s10-blocked | 7 (0.14) | 43 | 2 | 190 (140-232.5) | 0 | 4 | 3 | 154.6 (15.46) |
| 40 | s10c-blind | 6 (0.12) | 44 | 2 | 295 (218.75-438.75) | 0 | 2 | 4 | 150.2 (15.02) |

Paired by window (same cell, start and end on both runs):

| K (per zone) | detected on both | known only | blind only | neither |
|---|---|---|---|---|
| 10 | 4 | 2 | 2 | 42 |
| 20 | 5 | 2 | 1 | 42 |
| 40 | 5 | 2 | 1 | 42 |

Both runs use `rate_per_hour` 8 and duration [60, 240], seeds 0-9, 500 steps; `known` is removed before the schedule is hashed (S10C), so the windows are identical (asserted here). With `known: false` the planner does not see the cell, a move into it is NOOPed and the robot is hidden from the StuckCounter, like a floor cell with p = 1 while the window is open. Sources: `results/fleet/hotspot_s10-blocked.json`, `results/fleet/hotspot_s10c-blind.json`, `results/fleet/time_to_detect_blocked.json`, `results/fleet/time_to_detect_blind.json`.

#### (i) The undisturbed reference (s10-none) next to the disturbed runs

Final map (run-level; false flags = top-K cells that are not a truth cell of any kind):

| run | disturbance | flagged cells per zone, mean | K 20: false flags (per zone) | K 40: false flags (per zone) |
|---|---|---|---|---|
| s10-none | `{}` | 26.4 | 200 (20.0) | 264 (26.4) |
| s10-blocked | `{"blocked_cell": {"rate_per_hour": 8.0, "duration": [60, 240]}}` | 26.7 | 195 (19.5) | 260 (26.0) |
| s10-outage | `{"outage": {"rate_per_hour": 4.0, "duration": [120, 360]}}` | 26.8 | 199 (19.9) | 267 (26.7) |
| s10-breakdown | `{"breakdown": {"rate_per_hour": 8.0, "duration": [20, 60]}}` | 8.9 | 70 (7.0) | 70 (7.0) |
| s10-burst | `{"burst": {"start": 100, "end": 300, "extra": 20}}` | 25.7 | 195 (19.5) | 257 (25.7) |
| s10c-blind | `{"blocked_cell": {"rate_per_hour": 8.0, "duration": [60, 240], "known": false}}` | 26.1 | 183 (18.3) | 241 (24.1) |

Restated with the station-aware rule in (r) for s10-none, s10-breakdown and s10c-blind (final maps asserted equal); s10-blocked, s10-outage and s10-burst were not rerun.

Per publish (9 publishes every 5 min, the last at stream end), false flags per zone per publish and false alarms per zone per simulated hour:

| K (per zone) | s10-none (undisturbed, every flag is false): per publish, per hour | s10-blocked: per publish, per hour | s10-outage: per publish, per hour | s10c-blind: per publish, per hour |
|---|---|---|---|---|
| 10 | 8.41, 109.0 | 8.30, 107.6 | 8.50, 110.2 | 8.36, 108.3 |
| 20 | 13.72, 177.8 | 13.58, 176.0 | 13.90, 180.1 | 13.51, 175.1 |
| 40 | 15.46, 200.3 | 15.46, 200.3 | 15.71, 203.6 | 15.02, 194.7 |

Restated with the station-aware rule in (r) for s10-none and s10c-blind; s10-blocked and s10-outage were not rerun.

Reference = `fleet/data/s10-none` (10 zones x 500 steps, no disturbance, no truth), scored by `results/fleet/amoc_blind.json` (`amoc.k[].fa_per_hour_reference`; per publish = that x 0.6944 h / 9 publishes). The disturbed columns count only flags that match no truth window at that publish (the S10B rule), from `time_to_detect_{blocked,outage,blind}.json`, so they are flagged cells minus the flags on an open truth window (each such flag is a detection, so at most the detected windows of (g) and (h) per publish over all zones): per hour = false flags per publish summed over zones x publishes / (zones x steps x 5 s / 3600). The conversion is asserted equal to `amoc.k[].fa_per_hour_measured_outside_windows` for s10c-blind at K 10, 20, 40. The unit is flag-publishes per zone per simulated hour, not distinct cells. The burst and breakdown runs have no time-to-detect file, so they appear in the final-map table only. Sources: `results/fleet/hotspot_s10-none.json`, `results/fleet/hotspot_s10-blocked.json`, `results/fleet/hotspot_s10-outage.json`, `results/fleet/hotspot_s10-breakdown.json`, `results/fleet/hotspot_s10-burst.json`, `results/fleet/hotspot_s10c-blind.json`, `results/fleet/time_to_detect_blocked.json`, `results/fleet/time_to_detect_outage.json`, `results/fleet/time_to_detect_blind.json`, `results/fleet/amoc_blind.json`.

#### (j) Map versus persistence (S10D)

| run | zones | K | truth precision: map / persistence | PAI (= lift_all): map / persistence | lift_ever: map / persistence | paired truth precision, map - persistence (95% CI) | verdict | paired outcome precision (95% CI) | verdict |
|---|---|---|---|---|---|---|---|---|---|
| s8b-medium-80-p03-07 | 10 | 20 | 0.925 / 0.932 | 4.39 / 4.43 | 1.32 / 1.33 | -0.008 (-0.020 to +0.005) | within noise | +0.015 (-0.020 to +0.055) | within noise |
| s8b-medium-80-p03-07 | 10 | 40 | 0.791 / 0.814 | 3.76 / 3.87 | 1.13 / 1.16 | -0.023 (-0.034 to -0.011) | worse | +0.003 (-0.032 to +0.033) | within noise |
| closed-loop-sticky | 30 | 20 | 0.955 / 0.953 | 4.54 / 4.53 | 1.10 / 1.10 | +0.002 (-0.010 to +0.017) | within noise | n/a (0 units) | n/a |
| closed-loop-sticky | 30 | 40 | 0.841 / 0.859 | 3.99 / 4.08 | 0.97 / 0.99 | -0.018 (-0.029 to -0.008) | worse | n/a (0 units) | n/a |
| s8e-long-w0.5 | 3 | 20 | 0.977 / 0.985 | 4.64 / 4.68 | 2.02 / 2.03 | -0.008 (-0.019 to -0.002) | worse | +0.029 (+0.007 to +0.071) | beats |
| s8e-long-w0.5 | 3 | 40 | 0.879 / 0.898 | 4.18 / 4.27 | 1.81 / 1.85 | -0.019 (-0.026 to -0.009) | worse | +0.008 (+0.007 to +0.010) | beats |
| s10c-blind | 10 | 20 | 0.008 / 0.009 | 1.03 / 1.10 | 0.18 / 0.19 | -0.001 (-0.002 to +0.000) | within noise | +0.000 (+0.000 to +0.000) | within noise |
| s10c-blind | 10 | 40 | 0.004 / 0.004 | 0.55 / 0.55 | 0.09 / 0.09 | +0.000 (+0.000 to +0.000) | identical top-K sets | +0.000 (+0.000 to +0.000) | identical top-K sets |
| s10-none | 10 | 20 | 0.000 / 0.000 | n/a / n/a | n/a / n/a | n/a | n/a, no truth positives | +0.000 (+0.000 to +0.000) | within noise |
| s10-none | 10 | 40 | 0.000 / 0.000 | n/a / n/a | n/a / n/a | n/a | n/a, no truth positives | +0.000 (+0.000 to +0.000) | identical top-K sets |

Restated with the station-aware rule in (r); s8e-long-w0.5 was not rerun.

Chance lines and units per run:

| run | disturbance | steps | chance_all | chance_ever | forecast units (truth / outcome) | rank forecasts graded (unranked) |
|---|---|---|---|---|---|---|
| s8b-medium-80-p03-07 | `{"floor": {"cells": 80, "p": [0.3, 0.7]}}` | 500 | 0.211 | 0.702 | 20 / 10 | 442 (0) |
| closed-loop-sticky | `{"floor": {"cells": 80, "p": [0.9, 0.99]}}` | 500 | 0.211 | 0.865 | 30 / 0 | 0 (0) |
| s8e-long-w0.5 | `{"floor": {"cells": 80, "p": [0.3, 0.7]}}` | 2000 | 0.211 | 0.485 | 24 / 21 | 420 (1120) |
| s10c-blind | `{"blocked_cell": {"rate_per_hour": 8.0, "duration": [60, 240], "known": false}}` | 500 | 0.008 | 0.047 | 90 / 40 | 300 (0) |
| s10-none | `{}` | 500 | 0.000 | 0.000 | 90 / 40 | 297 (0) |

Restated with the station-aware rule in (r); s8e-long-w0.5 was not rerun.

lesson_persist (hot_cell lessons) against three pools:

| run | hot_cell lessons graded | hot_robot excluded | observed rate | chance: window (S8S) / ever / all | lift: window / ever / all |
|---|---|---|---|---|---|
| s8b-medium-80-p03-07 | 0 | 0 | n/a | n/a | n/a |
| closed-loop-sticky | 0 | 0 | n/a | n/a | n/a |
| s8e-long-w0.5 | 25 | 0 | 0.720 | 0.241 / 0.221 / 0.0772 | 2.99 / 3.26 / 9.33 |
| s10c-blind | 2 | 3 | 0.500 | 0.034 / 0.024 / 0.0013 | 14.50 / 21.00 / 380.00 |
| s10-none | 3 | 3 | 0.333 | 0.061 / 0.102 / 0.0061 | 5.45 / 3.28 / 54.29 |

Restated with the station-aware rule in (r) for s10-none and s10c-blind; the other runs were not rerun or have no lessons.

Persistence = the same published rows ranked by their raw window stall count instead of the decayed cost: same window, same filter, same `min_stalls`, so decay is the only difference (`fleet/baselines.py` docstring). Truth precision here is per publish against the cells that are truth-positive over the next horizon [t, t + H], pooled over (zone, publish) units, so it is not the run-level `truth_kinds` of (f) and (h). PAI = (hits / positives) / (K / 380 candidate cells) and equals lift_all by definition (asserted). Paired = per-zone map minus persistence, mean over zones, 1,000-resample zone bootstrap (seed 0), 2.5 / 97.5 percentiles; the verdict rule is the one at the top of this script (asserted equal to the JSON's), but the CI is a bootstrap, not `evaluate.paired_delta`'s Student-t. "identical top-K sets" = every zone flags fewer than K cells on the final map and the map window covers the whole stream, so both lists hold the whole flagged set at every publish (asserted: equal blocks, CI 0 to 0): s10c-blind at K 40 (at most 36 flagged cells per zone); s10-none at K 40 (at most 32 flagged cells per zone). s10-none has no truth positives, so its truth columns are 0 or n/a by construction. s8e-long-w0.5 has 3 zones; a bootstrap over so few zones sits on the extreme resamples, so its verdicts are weak. The outcome grade re-ranks with the map's own decay at t + H, so it leans toward the map; closed-loop-sticky has one publish at stream end and 0 outcome units. The s8b re-score reads the store as it is on disk today, which grades 442 rank forecasts (0 unranked); the committed `results/fleet/hotspot_s8b-medium-80-p03-07.json` graded 200 (242 unranked). The `baselines` block is computed from the costmap rows, not from those grades. Sources: `results/fleet/baselines_s8b-medium-80-p03-07.json`, `results/fleet/baselines_closed-loop-sticky.json`, `results/fleet/baselines_s8e-long-w0.5.json`, `results/fleet/baselines_s10c-blind.json`, `results/fleet/baselines_s10-none.json` (`baselines`, `rank_grading`, `config`).

#### (k) AMOC: delay, misses and false alarms per hour (S10E, planner-blind blockage)

By K (flag = rank <= K in the zone's map at a publish):

| K (per zone) | detected / windows | miss share | first detect, s, median (p25-p75) | stale_at_end share | false alarms per zone-hour, s10-none | false alarms per zone-hour, s10c-blind outside windows |
|---|---|---|---|---|---|---|
| 5 | 3 / 50 | 0.94 | 475 (285-537.5) | 0.02 | 59.2 | 58.9 |
| 10 | 6 / 50 | 0.88 | 402.5 (277.5-568.75) | 0.04 | 109.0 | 108.3 |
| 20 | 6 / 50 | 0.88 | 295 (218.75-438.75) | 0.04 | 177.8 | 175.1 |
| 40 | 6 / 50 | 0.88 | 295 (218.75-438.75) | 0.04 | 200.3 | 194.7 |
| 80 | 6 / 50 | 0.88 | 295 (218.75-438.75) | 0.04 | 200.3 | 194.7 |

Restated with the station-aware rule in (r).

By cost threshold (flag = cost >= c at a publish):

| cost >= | detected / windows | miss share | first detect, s, median (p25-p75) | stale_at_end share | false alarms per zone-hour, s10-none | false alarms per zone-hour, s10c-blind outside windows |
|---|---|---|---|---|---|---|
| 0.2 | 6 / 50 | 0.88 | 295 (218.75-438.75) | 0.04 | 200.3 | 194.7 |
| 0.4 | 6 / 50 | 0.88 | 402.5 (277.5-568.75) | 0.04 | 143.1 | 140.5 |
| 0.6 | 2 / 50 | 0.96 | 537.5 (506.25-568.75) | 0.00 | 50.3 | 45.2 |
| 0.8 | 1 / 50 | 0.98 | 475 (475-475) | 0.00 | 37.7 | 35.7 |

Restated with the station-aware rule in (r).

Dial at which the miss share first drops below 0.5: K none at any K; cost none at any cost.

Measured run `fleet/data/s10c-blind` (50 planner-blind blocked windows, `{"blocked_cell": {"rate_per_hour": 8.0, "duration": [60, 240], "known": false}}`), reference `fleet/data/s10-none` (undisturbed), both 10 zones x 500 steps = 0.6944 simulated h, 9 publishes every 5 min. False alarms are flag-publishes per zone per simulated hour: on the reference every flag counts; on the measured run only flags matching no truth window at that publish. Rows with equal numbers are saturated: the dial already flags every cell with a nonzero cost. Definitions (verbatim from the JSON): sim_hours: "steps * step_seconds / 3600 from each run's truth.json (not the span)"; fa_per_hour_reference: "flags over all reference publishes and zones (flagged: rank <= K, or cost >= c) / (n_zones_reference * sim_hours_reference); every flag on the reference is false"; fa_per_hour_reference_by_zone: "{zone: zone flags / sim_hours_reference}"; fa_per_hour_measured_outside_windows: "sum over measured publishes of analyse_windows_k's false flags (flagged cells with no truth_positive of any kind) / (n_zones_measured * sim_hours_measured)"; miss_share: "summary.missed / n_windows (null for 0 windows)"; stale_at_end_share: "summary.stale_at_end / n_windows (null for 0 windows)"; median_delay_s: "summary.first_detect_s median over detected windows; p25 / p75 likewise"; k_at_miss_below_half: "first K entry (K ascending) with miss_share < 0.5, else null"; cost_at_miss_below_half: "first cost entry (cost descending) with miss_share < 0.5, else null". Source: `results/fleet/amoc_blind.json` (`amoc`).

**Reading the numbers.**
- **Map against persistence (j).** On truth precision the decayed map is within noise of persistence, the plain one-hour stall count, at K 20 on s8b (-0.008, CI -0.020 to +0.005) and on the 30-zone sticky run (+0.002, CI -0.010 to +0.017); it is worse at K 40 on both (-0.023 and -0.018) and at both K on the 3-zone s8e-long run (-0.008 and -0.019), and never better. On outcome precision the map is within noise on s8b at both K and beats persistence on s8e-long (+0.029 and +0.008). That run has only 3 zones, and the outcome grade re-ranks with the map's own decay. Both forecasts are far above a random draw from all cells on the floor runs (PAI 4.39 to 4.68 at K 20) Against a random draw from the cells that ever stalled the margin is small on the 500-step runs (lift_ever 1.10 to 1.33 at K 20, and 0.97 for the map on the sticky run at K 40) and about twice chance on s8e-long (2.02 and 2.03, 3 zones).
- **On the blockage runs (j).** On s10c-blind both forecasts have truth precision below 0.01, about chance (map PAI 1.03, chance_all 0.008). The map's lift_ever is 0.18, so a random pick among the cells that ever stalled would do better. At K 40 the two lists are the same set. s10-none has no truth, so only its outcome column means anything.
- **Lessons against three pools (j).** On s8e-long 18 of 25 hot_cell lessons persisted (0.720). Lift is 2.99 against the S8S window pool, 3.26 against the ever-stalled pool and 9.33 against all cells. The s10c-blind and s10-none rows rest on 2 and 3 lessons, too few to read.
- **Planner-blind against known blockage (h).** Hiding the blockage from the planner did not raise detection while the window was open. At K 20, 6 of 50 blind windows were detected against 7 of 50 known ones. Per window, 5 were caught on both runs, 2 only on the known run and 1 only on the blind run. Detection came later on the blind run (median 295 s against 190 s), and no blind window cleared (known: 2). On the final map the blind run has 17 blocked cells in a zone's top 20 against 4 (recall 0.34 against 0.08). At least 11 of those 17 were never in the top 20 at a publish while their window was open, so the final-map recall measures cells flagged after the fact. The JSONs do not record how many robots reached a blind cell (`blind_skips`). This run therefore cannot tell "robots rarely reach the cell" apart from "the map does not rank it". The S10C smoke (2 zones x 150 steps, small map) found 0 blind skips at seed base 0.
- **The false-alarm floor is the map's own (i).** With no disturbance at all, the map flags 26.4 cells per zone on the final map and 20.0 per zone in the top 20 (all false). That is the same as the disturbed runs (18.3 to 19.9 per zone at K 20, outside breakdown). Per publish, the undisturbed run raises 177.8 false flag-publishes per zone per simulated hour at K 20. Every disturbed run is within 3% of the undisturbed run at K 10, 20 and 40, so the false flags come from ordinary traffic, not from the disturbances.
- **AMOC (k).** No setting of K or of the cost threshold brings the miss share below 0.5 on the planner-blind run. The miss share is 0.88 or more everywhere. The best dial (K 20) detects 6 of 50 windows with a median delay of 295 s, at 177.8 false alarms per zone-hour on the undisturbed run. The quietest dial (cost >= 0.8) detects 1 of 50 at 37.7. K 40, K 80 and cost >= 0.2 give identical rows: every cell with a nonzero cost is already flagged.

**Caveats.**
- One seed set and one 500-step shift per preset (s8e-long: 3 zones x 2,000 steps). The only CIs are the zone-bootstrap CIs of (j); there is none on any count in (h), (i) or (k).
- The s8b re-score reads today's store, which grades 442 rank forecasts against the committed hotspot JSON's 200 (footnote of (j)). The `baselines` block does not use those grades.
- Persistence here differs from the map only by the decay. A persistence forecast over a different window length was not run.
- The numbers are macOS arm64 only.

### Sprint 10, closing: false-alarm gate and frozen truth cells (2026-10-19)

S10F (PR #44) added a false-alarm gate to `fleet/costmap.py`. `--gate baseline` passes a cell only when its count in the latest 300 s window is above the mean plus 2 standard deviations of the previous 3 windows, by at least 2 stalls. `--gate persistence` passes a new top-K entrant with at least 2 stalls, or a cell whose count rose by at least 2 since the previous window. The gate suppresses forecasts only: the map is unchanged. The queue item `wr-s10f-gate-run` ran both gates on copies of the s10-none, s10c-blind and sticky phase A stores. S10G (PR #42) gave each frozen window the robot's cell, so a frozen cell is now truth-positive. `wr-s10g-breakdown-rerun` re-emitted s10-breakdown, checked it bit-identical by sha256, and re-scored it, with lessons at `--window-h 0.2` instead of 0.5. That re-score is why the s10-breakdown rows of (f) and (i) above changed. S10H (PR #43) put the persistence baseline of (j) next to every map precision on the overview and replay pages. Everything between this paragraph and "Reading the numbers" is the output of sections (l) and (m) of `.venv/bin/python scripts/sprint8_tables.py`. Only its headings were demoted one level.

#### (l) The false-alarm gate (S10F): gate none / baseline / persistence

| run | gate | forecasts (flags) | per zone per publish: mean over all, max | truth hits / false alarms | precision | truth cells hit / truth cells | recall (cells) |
|---|---|---|---|---|---|---|---|
| s10-none | none | 1391 | 15.46, n/a | 0 / 1391 | 0.000 | n/a / 0 | n/a |
| s10-none | baseline | 2 | 0.02, 1 | 0 / 2 | 0.000 | 0 / 0 | n/a (no truth cells) |
| s10-none | persistence | 5 | 0.06, 1 | 0 / 5 | 0.000 | 0 / 0 | n/a (no truth cells) |
| s10c-blind | none | 1363 | 15.14, n/a | 16 / 1347 | 0.012 | n/a / 50 | n/a |
| s10c-blind | baseline | 5 | 0.06, 1 | 1 / 4 | 0.200 | 1 / 50 | 0.020 |
| s10c-blind | persistence | 9 | 0.10, 1 | 1 / 8 | 0.111 | 1 / 50 | 0.020 |
| closed-loop-sticky | none | n/a | n/a | n/a | n/a | n/a | n/a (not comparable: the original phase A map had one publish) |
| closed-loop-sticky | baseline | 89 | 0.33, 3 | 88 / 1 | 0.989 | 85 / 2400 | 0.035 |
| closed-loop-sticky | persistence | 176 | 0.65, 4 | 175 / 1 | 0.994 | 157 / 2400 | 0.065 |

Restated with the station-aware rule in (r) for the ungated rows; the gated rows were not rerun.

Forecasts = `hotspot_forecast` claims, each graded once against the truth over the next horizon (truth hit or false alarm); a gated run publishes only the forecasts that pass the gate, and the cost map itself is unchanged (asserted here: `zones` and every `truth_kinds` kind except `frozen`, whose S10G fields the ungated JSONs predate, are equal to the ungated JSON's). Per zone per publish, mean over all = forecasts / (zones x publishes), with 9 publishes every 300 s, the last at stream end, warm-up publishes included (baseline: publishes 1-3 pass nothing; persistence: publish 1); max = `gate_grading.flags_per_zone_publish.max`, after warm-up. The ungated JSONs carry no per-publish maximum and no truth cells hit, so those are n/a; truth cells = `truth_kinds.any.positives`. Truth cells hit = distinct (zone, cell) with at least one truth-hit forecast; recall = that / truth cells. The gate runs used `--publish-every 300 --horizon-s 1245` on copies of each store (`wr-s10f-gate-run`); s10-none and s10c-blind are the same publishes as their ungated runs, the sticky phase A was originally published once, so it has no ungated row on this schedule. On the sticky run the truth cells are its 80 floor cells per zone, present for the whole run. Gate parameters: windows 3, sigma 2.0, min excess 2, min count 2 (the S10F defaults). Sources: `results/fleet/hotspot_s10-none.json`, `results/fleet/hotspot_s10-none-gate-baseline.json`, `results/fleet/hotspot_s10-none-gate-persistence.json`, `results/fleet/hotspot_s10c-blind.json`, `results/fleet/hotspot_s10c-blind-gate-baseline.json`, `results/fleet/hotspot_s10c-blind-gate-persistence.json`, `results/fleet/hotspot_closed-loop-sticky-gate-baseline.json`, `results/fleet/hotspot_closed-loop-sticky-gate-persistence.json` (`gate_grading`, `grading_counts.truth`, `truth_kinds`).

#### (m) Frozen truth cells on the breakdown run (S10G)

| run | frozen robots | frozen cells | flagged cells, final map (per zone, max) | K 20: hits, precision, recall | K 40: hits, precision, recall | zones flagging fewer than K cells (K 20 / K 40) | hotspot_forecast truth grades: hit / graded |
|---|---|---|---|---|---|---|---|
| s10-breakdown | 119 | 283 | 89 (8.9, 16) | 19, 0.0950, 0.067 | 19, 0.0475, 0.067 | 10 / 10 | 25 / 488 |

Restated with the station-aware rule in (r).

Frozen cells = per zone, the distinct cells a robot stood on at the start of a frozen window, summed over zones (`truth_kinds.frozen.cells`); a hit is a final-map top-K cell that is a frozen cell of its zone at any time in the run, so it does not mean the cell was flagged while the robot was frozen. Frozen cells are the only truth cells of this run (asserted: frozen hits = `any` hits), so 19 of the 89 flagged cells are frozen cells and the rest are false flags. Every zone flags fewer than 20 cells, so K 20 and K 40 score the same cells. The time-matched number is the forecast truth grade: a forecast is a hit when its cell is truth-positive (here: frozen) over the next horizon (1245 s). Before S10G the same run graded 0 hits of 488 (the committed (f) of 2026-10-18), because frozen windows carried no cell. No chance line is computed for frozen cells. Source: `results/fleet/hotspot_s10-breakdown.json` (`truth_kinds.frozen`, `zones.*.n_flagged`, `grading_counts.truth`), from `wr-s10g-breakdown-rerun` (bit-identical re-emit, lessons `--window-h 0.2`).

**Reading the numbers.**
- **The gate removes the false-alarm floor (l).** With no disturbance, the ungated map raised 1,391 forecasts, all false: 15.46 per zone per publish. The baseline gate raised 2 and the persistence gate 5, and neither put more than 1 flag in any zone at any publish.
- **It removes the detections with it (l).** On the planner-blind blockage run, the ungated forecasts scored 16 truth hits out of 1,363 (precision 0.012). The baseline gate kept 1 hit out of 5 (0.200), and the persistence gate 1 out of 9 (0.111). Both gated runs hit 1 of the 50 blocked cells (recall 0.020). Precision rose roughly tenfold, but 15 of the 16 hits were lost. The ungated JSON does not record how many distinct cells its 16 hits cover, so the ungated cell recall is n/a here.
- **Persistence against baseline (l).** The persistence gate passes about twice as many forecasts as the baseline gate on every run: 5 against 2, 9 against 5, 176 against 89. On the sticky floor it hits 157 of 2,400 floor cells against 85 (recall 0.065 against 0.035), at precision 0.994 against 0.989. On that run nearly every stalled cell is a floor cell (chance_ever 0.865 in (j), over a 60-min horizon), so a precision near 1 says little. The difference between the gates is in recall. The sticky run has no ungated row on the same publish schedule.
- **Frozen cells (m).** S10G's mechanism note predicted about 0 frozen hits, because `counted()` drops faulted-episode stalls and, by default, stalls on an occupied cell. That prediction did not hold. 19 of the 89 cells the breakdown map flags are frozen cells, out of 283 (recall 0.067). Over time, 25 of 488 forecasts are truth hits (0.051), against 0 of 488 before frozen windows carried a cell. Which stalls put those cells on the map was not examined. The hits are run-level, so a hit does not show that the cell was flagged while its robot was frozen. No chance line exists for frozen cells, so 0.067 cannot be read as above or below chance. K 20 and K 40 are the same cells, because no zone flags 20 (max 16).

**Caveats.**
- One seed set (0-9) and one 500-step shift per run (the sticky phase A run: 30 zones). There is no CI on any count in (l) or (m).
- Each gate ran once, at its S10F default parameters (windows 3, sigma 2.0, min excess 2, min count 2). No other setting was run, so (l) shows one point on each gate's trade-off, not the trade-off curve.
- The baseline gate's warm-up blanks publishes 1-3 (the first 900 s of a 2,500 s stream), so a blockage that ends inside that span cannot be flagged. The blockages last 60-240 steps, i.e. 300-1,200 s (`duration` is in steps, `src/warehouse_rl/disturb.py:109`; median window 132 steps in (g)). The S10F lane report's "60-240 s" read the steps as seconds. The persistence gate blanks only publish 1 and still hits 1 of 50, so warm-up does not explain the recall loss on its own.
- The numbers are macOS arm64 only.

### Sprint 10, S10I: fast detector against the decayed map (2026-10-19)

S10I (PR #45) added `fleet/fastmap.py`, a per-cell CUSUM. It is published every 60 s and writes the same decision rows as the map. A stall counts in every 60 s bin it overlaps (`--count active`), whereas the map counts a stall at its end. The queue item `wr-s10i-fast-run` (exit 0) ran it at its default parameters on s10c-blind and s10-none. It also re-ran the map with a short memory (window 0.2 h, half-life 0.1 h) published every 60 s, so a map runs on the CUSUM's schedule. Both went through the AMOC scorer of (k). Everything between this paragraph and "Reading the numbers" is the output of section (n) of `.venv/bin/python scripts/sprint8_tables.py`. Only its heading was demoted one level.

#### (n) Fast detector vs decayed map (S10I, planner-blind blockage)

By K (map: flag = rank <= K in the zone's map at a publish; CUSUM: flag = a flagged cell at a publish, K only caps the rank):

| detector | publish every, s (publishes) | K (per zone) | detected / windows | miss share | first detect, s, median (p25-p75) | stale_at_end share | false alarms per zone-hour, s10-none | false alarms per zone-hour, s10c-blind outside windows |
|---|---|---|---|---|---|---|---|---|
| decayed map (S10E) | 300 (9) | 5 | 3 / 50 | 0.94 | 475 (285-537.5) | 0.02 | 59.2 | 58.9 |
| decayed map (S10E) | 300 (9) | 10 | 6 / 50 | 0.88 | 402.5 (277.5-568.75) | 0.04 | 109.0 | 108.3 |
| decayed map (S10E) | 300 (9) | 20 | 6 / 50 | 0.88 | 295 (218.75-438.75) | 0.04 | 177.8 | 175.1 |
| decayed map (S10E) | 300 (9) | 40 | 6 / 50 | 0.88 | 295 (218.75-438.75) | 0.04 | 200.3 | 194.7 |
| short-memory map | 60 (42) | 5 | 6 / 50 | 0.88 | 402.5 (108.75-568.75) | 0.00 | 260.2 | 254.6 |
| short-memory map | 60 (42) | 10 | 6 / 50 | 0.88 | 402.5 (108.75-568.75) | 0.00 | 427.4 | 402.8 |
| short-memory map | 60 (42) | 20 | 6 / 50 | 0.88 | 402.5 (108.75-568.75) | 0.00 | 451.9 | 426.2 |
| short-memory map | 60 (42) | 40 | 6 / 50 | 0.88 | 402.5 (108.75-568.75) | 0.00 | 451.9 | 426.2 |
| CUSUM (S10I) | 60 (42) | 5 | 2 / 50 | 0.96 | 525 (482.5-567.5) | 0.02 | 0.000 | 0.144 |
| CUSUM (S10I) | 60 (42) | 10 | 2 / 50 | 0.96 | 525 (482.5-567.5) | 0.02 | 0.000 | 0.144 |
| CUSUM (S10I) | 60 (42) | 20 | 2 / 50 | 0.96 | 525 (482.5-567.5) | 0.02 | 0.000 | 0.144 |
| CUSUM (S10I) | 60 (42) | 40 | 2 / 50 | 0.96 | 525 (482.5-567.5) | 0.02 | 0.000 | 0.144 |

Restated with the station-aware rule in (r) for the decayed map rows; the CUSUM and the short-memory map were not rerun.

Dominance over every row on disk (detected up, false alarms per zone-hour on the reference down, one strictly): the CUSUM row is dominated by no map row; it dominates decayed map (S10E): cost >= 0.6, cost >= 0.8; short-memory map: none. Map rows at the CUSUM's reference false-alarm rate (0): none. Lowest map false-alarm rate on disk 37.7; most windows any map row detects 6 / 50.

Same measured run (`fleet/data/s10c-blind`, 50 planner-blind blocked windows) and reference (`fleet/data/s10-none`) for all three, store hashes equal before and after (asserted). Ks shown are the ones all three JSONs share (5, 10, 20, 40). CUSUM parameters (from `fleet/data/s10c-blind/fastmap.json`, gitignored, not committed): k 1, h 3, bin 60 s, baseline 30 bins, count `active`. The CUSUM rows are identical at every K (asserted). False alarms are flag-publishes per zone per simulated hour, so they scale with the publish rate: a detector publishing every 60 s has 5 times as many publishes per hour as one publishing every 300 s, and more chances to catch a window while it is open. The short-memory map is published at the CUSUM's 60 s and is the like-for-like cadence comparison for it. Column definitions are those of (k). Sources: decayed map (S10E): `results/fleet/amoc_blind.json`, window 1 h, half-life 1 h; short-memory map: `results/fleet/amoc_shortmap.json`, window 0.2 h, half-life 0.1 h; CUSUM (S10I): `results/fleet/amoc_fast.json`, store-fast (prebuilt) (`amoc`, `meta`).

**Reading the numbers.**
- **Verdict (n): neither detector catches more windows while open at the same false-alarm rate, because no map row runs at the CUSUM's rate.** On the undisturbed reference, the CUSUM raises 0.000 false alarms per zone-hour and detects 2 of 50 blind windows. No map row on disk gets to 0. The quietest map row is cost >= 0.8 in (k), at 37.7. The maps detect more windows, 3 to 6 of 50, at 59.2 to 451.9 false alarms per zone-hour across K. The CUSUM's rows are the same at every K, because K only caps a rank.
- **Against the map's cost rows.** The CUSUM is at least as good on both axes as two of the decayed map's cost rows in (k): cost >= 0.6 (2 of 50 at 50.3) and cost >= 0.8 (1 of 50 at 37.7). That is not a detector win, for three reasons:
  - it rests on 2 windows;
  - the CUSUM publishes every 60 s against the decayed map's 300 s (42 publishes against 9), so it has more chances to catch an open window;
  - the S10I lane report shows that the whole detection at the defaults comes from the active counting rule. With the end rule, the same CUSUM flags nothing on s10c-blind.

  No map row dominates the CUSUM, and the CUSUM dominates no row of the short-memory map.
- **Short-memory map against decayed map (n).** At K 20, the short-memory map detects the same 6 of 50 as the decayed map. Its median first detection is 402.5 s against 295 s, at 451.9 false alarms per zone-hour against 177.8. Two things changed at once between these maps: the publish rate (60 s against 300 s) and the memory (window 0.2 h, half-life 0.1 h, against 1 h and 1 h). This run cannot separate the two effects. The fair cadence comparison is the short-memory map against the CUSUM, since both publish every 60 s: 6 of 50 at 260.2 to 451.9 against 2 of 50 at 0.000.
- **On the measured run (n).** Outside the windows, the CUSUM raised 0.144 false alarms per zone-hour on s10c-blind. That is one flag, at the stream-end publish. So the CUSUM's false-alarm rate is low on this run, not zero.

**Caveats.**
- One seed set (0-9), one 500-step shift, one CUSUM parameter pair (k 1, h 3, the defaults; not tuned). No count in (n) has a CI.
- The S10I lane report lists in-sample (k, h) pairs that detect more windows. They were picked on the same 50 windows they are scored on, no results JSON holds them, and they need a held-out run before they are quoted.
- The map with the active counting rule was not run. Part of any map-against-CUSUM gap may be the counting rule rather than the detector.
- The numbers are macOS arm64 only (pyastar2d tie-break).

## Sprint 12: where the shift goes (2026-10-20)

Sprint 12 asks what the robots spend the shift on, using only the message stream the analyser already reads. S12A (PR #47) added `fleet/timebudget.py`: per robot, every second of the stream goes to one of seven buckets (moving, waiting_station, waiting_shelf, stuck, stopped_short, faulted, idle); S12C (PR #48) added `paused` and `no_data`. It uses the detector's own stopped runs and 30 s rule, and takes the station and shelf cells from the run's layout. S12B (PR #46) added `fleet/deadlock.py`, which looks for groups of stuck robots that block each other (blocking clusters and blocking chains; S12B's "deadlock" and "knot", renamed in S12C), and `fleet/gapmap.py`, which puts each gap in a robot's message sequence numbers (headerId) on the grid cell where it happened. `emit.py --deadzone` lets a test plant cells where messages are dropped. The queue item `wr-s12a-budget-run` ran the time budget on five stored runs. `wr-s12b-run` ran the blocking finder on four of them, then emitted the undisturbed configuration with 6 planted dead cells per zone and ran the gap map on it. The names follow `docs/LITERATURE.md` Part 2 (fleet management, 2026-10-20). Where the tools' bucket or field names differ, the tables give the standard term next to them. Everything between this paragraph and "Reading the numbers" is the output of sections (o) and (p) of `.venv/bin/python scripts/sprint8_tables.py`. Only its headings were demoted one level.

#### (o) Where the shift goes (S12A time budget)

| run | disturbance | AGVs (zones) | moving (productive: travel) | waiting_station (productive: load/unload, or standby: queued) | waiting_shelf (standby: no operator) | stuck (blocked, >= 30 s) | stopped_short (blocked: congestion wait, < 30 s) | faulted (unscheduled downtime) | idle (standby: no work) | paused (standby: paused or manual mode, VDA `paused`) | no_data (unobserved: no message for more than max_gap_s) | throughput: jobs per AGV-hour | same-minute stops: zone-start minute / later | stall list: episodes starting on a station cell, n/N (share) | starting next to a shelf, n/N (share) | picker episodes in N |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| s10-none | undisturbed | 80 (10) | 40.0% | 2.1% | 28.8% | 20.8% | 4.5% | 0.0% | 3.8% | 0.0% | 0.0% | 22.18 | 3 / 13 | 10/677 (1.5%) | 658/677 (97.2%) | 79 |
| s10c-blind | planner-blind blockage | 80 (10) | 35.0% | 1.9% | 30.0% | 25.9% | 3.9% | 0.0% | 3.3% | 0.0% | 0.0% | 19.53 | 3 / 9 | 8/646 (1.2%) | 615/646 (95.2%) | 92 |
| s10-breakdown | robot breakdowns | 80 (10) | 18.0% | 0.9% | 26.5% | 18.6% | 1.7% | 32.1% | 2.1% | 0.0% | 0.0% | 10.08 | 2 / 0 | 9/526 (1.7%) | 486/526 (92.4%) | 141 |
| s8b-medium-80-p03-07 | floor, 80 cells, p 0.3-0.7 | 80 (10) | 35.6% | 1.9% | 31.0% | 22.6% | 5.6% | 0.0% | 3.2% | 0.0% | 0.0% | 19.26 | 9 / 21 | 7/657 (1.1%) | 625/657 (95.1%) | 116 |
| closed-loop-sticky | sticky floor, 80 cells, p 0.9-0.99 (phase A, 30 zones) | 240 (30) | 12.1% | 1.6% | 51.7% | 32.0% | 1.6% | 0.0% | 1.0% | 0.0% | 0.0% | 7.02 | 16 / 0 | 47/2411 (1.9%) | 1839/2411 (76.3%) | 998 |

Restated with the station-aware rule in (r).

Shares are of AGV-seconds over the zone's span, summed over zones (`run.totals.share`; pickers are reported apart by the tool and are not in the shares, the AGV count or the jobs rate). Every second goes to one bucket, in the precedence no_data > faulted > paused > moving > waiting_station > waiting_shelf > stuck / stopped_short > idle, so a stop next to a shelf is `waiting_shelf` even when it lasts past the stuck threshold (30 s, the detector's own). The term in brackets is the standard class `docs/LITERATURE.md` Part 2 section 2 maps each bucket to (SEMI E10 classes, Standridge's blocked time, VDA 5050 fields); where the bucket does not measure that class, the reading below says so. Station cells: 10 per zone. Shelf-adjacent cells: 360 per zone (the 160 shelf slots plus every cell within Manhattan 1 of one, stations excluded). Throughput is jobs per AGV-hour, the MAPF word for goals reached per unit time. Same-minute stops: minutes in which at least 80% of a zone's AGVs stop, split into the zone-start minute (00:00) and later minutes. Stall list: the detector's stuck episodes from the run's store (pickers included, last column); a station or shelf episode is one whose first cell is a station or shelf-adjacent cell. Asserted per run: the time-budget stuck runs and the detector episodes have the same start sets (`stuck_runs_vs_detector`), and the bucket seconds sum to the span. `faulted` counts robots with an error of error level CRITICAL or FATAL (S12C; the emitter writes only FATAL errors). `paused` is a message with VDA 5050 `paused` true; `no_data` is the whole interval between two messages more than 60 s apart (`src.max_gap_s`). The simulator emitter never sets `paused` and sends every robot every step, so both shares are zero on these runs, as the JSONs show. Sources: `results/fleet/timebudget_s10-none.json`, `results/fleet/timebudget_s10c-blind.json`, `results/fleet/timebudget_s10-breakdown.json`, `results/fleet/timebudget_s8b-medium-80-p03-07.json`, `results/fleet/timebudget_closed-loop-sticky.json` (`run`, `zones.*.same_minute_stops`, `zones.*.cell_classes`, `src`), from `wr-s12a-budget-run`, re-run after S12C with the new buckets (every other value unchanged).

#### (p) Blocking clusters and chains (S12B): a congestion measure, and message-loss cells

| run | blocking clusters (JSON `blocking_clusters`) | broke up / still open at stream end | blocking chains (JSON `blocking_chains`) | cluster length, s: median (max) | robots per cluster, max | blocked robot-s in clusters per robot-hour | vs s10-none | top cell by cluster seconds (cells tied at that value) | standoffs (same robots, gaps of at most one step merged) | longest standoff: zone, span s, clusters, end | longest standoff's share of blocked robot-s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| s10-none | 49 | 48 / 1 | 0 | 75 (430) | 3 | 108.2 | 1.00x | zone 4, cell 7,4: 1330 s in 19 clusters (2) | 34 | zone 4, 1260 s, 16, open at stream end | 26.3% |
| s10c-blind | 56 | 53 / 3 | 0 | 75 (440) | 3 | 146.1 | 1.35x | zone 4, cell 7,4: 1330 s in 19 clusters (2) | 39 | zone 4, 1260 s, 16, open at stream end | 19.5% |
| s10-breakdown | 28 | 28 / 0 | 5 | 187.5 (655) | 3 | 162.9 | 1.51x | zone 5, cell 7,14: 1105 s in 3 clusters (2) | 26 | zone 5, 655 s, 1, broke up | 14.5% |
| closed-loop-sticky | 163 | 145 / 18 | 0 | 95 (1875) | 4 | 300.4 | 2.78x | zone 27, cell 6,9: 1985 s in 3 clusters (1) | 154 | zone 23, 1875 s, 1, open at stream end | 5.0% |

Restated with the station-aware rule in (r).

A blocking cluster is a strongly connected group of at least 2 robots in the per-batch wait-for graph (`fleet/deadlock.py`), kept when it lasts at least 30 s. The tool's own definition: "mutually blocked robots (strongly connected component, >= 2) that persist >= min_s; every one found so far resolves, so this is a congestion measure, not a circular wait". Adjacency is symmetric (Manhattan 1), so any two adjacent stuck robots with no faulted neighbour form a cluster: it is congestion that persists, not the circular wait that `docs/LITERATURE.md` Part 2 section 1 calls a deadlock (Coffman et al. 1971; a cycle in the wait-for graph). So the table is a congestion measure: no circular wait survives in TA-RWARE, because the vendor replans a robot once it has been stuck more than 5 steps (`_STUCK_THRESHOLD`, `vendor/tarware/tarware/warehouse.py:15` and `:494`), and every cluster that ends inside the stream broke up. The clusters still open at stream end (third column) are censored, not shown to clear. A blocking chain (JSON `blocking_chains`; S12B called it a knot) is a path of at least 2 edges among robots in no cluster; Part 2 renames it because a knot in deadlock theory is the closed set that is the deadlock. Still open at stream end = censored, its length is a lower bound. Broke up = the group was gone at the next batch, which can be a single step: the vendor planner replans a robot after more than 5 stuck steps, frees one cell, and the same robots can block each other again. A standoff merges clusters of the same zone and robot set that start at most one step (5 s) after the previous one ends; its span runs from the first start to the last end. Blocked robot-s per robot-hour = sum(length x robots) / robot-hours, where robot-hours include the pickers (12 robots per zone), unlike (o), which counts AGVs only. Top cell: each cluster adds its length to every cell it covers, so cells of one cluster tie; the tie rule is most seconds, then lowest zone, then cell string. Sources: `results/fleet/deadlock_s10-none.json`, `results/fleet/deadlock_s10c-blind.json`, `results/fleet/deadlock_s10-breakdown.json`, `results/fleet/deadlock_closed-loop-sticky.json` (`total`, `decisions`, `zones.*.top_cells`), from `wr-s12b-run`; no run of the s8b floor store.

**Message-loss cells inferred from headerId gaps (S12B gap map, run `s12-deadzone`).** precision@10 of `gap_cell` against the 6 planted dead cells per zone, pooled over 10 zones: 0.57 (ceiling 0.60: only 6 of 10 can be right); 57 of 94 `gap_cell` decisions hit, and 57 of 60 planted cells are found (recall 0.95). 713 dropped messages placed, 0 unplaced. The graded count is 94, not 10 x 10: the gap map wrote 97 decisions (some zones place fewer than 10 cells), and the store refused 3 as duplicates of another zone's row (same cell and first-gap time; the dedup key has no zone, S12B caveat 2). **Synthetic:** the dead cells are planted by the project's own emitter (`emit.py --deadzone`, which drops every message sent from them), so the only cause of a gap is the planted cell. In a real log a gap can also be a broker- or consumer-side drop with no location cause, and a VDA 5050 robot keeps driving through a disconnect. The stall-map truth grades in the same hotspot JSON count the dead cells as truth hits and are not read here. Sources: `results/fleet/gapmap_s12-deadzone.json` (`zones.*.cells`, `unplaced_leading_missing`, `store_duplicates`), `results/fleet/hotspot_s12-deadzone.json` (`gap_grading` only).

**Reading the numbers.**
- **What share of "stuck" was a robot waiting at a station or a shelf (o).** At a station: almost none. Of the stall episodes the detector reports, 1.1% to 1.9% start on a station cell in every run (7 of 657 to 47 of 2,411). So the complaint "a robot queued at a station is filed as stuck" is real, but in this simulation it covers one or two stalls in a hundred. Next to a shelf: 76.3% to 97.2% of episodes start there, but that does not mean 76% to 97% were robots waiting for a picker. The shelf-adjacent class is 360 cells per zone: the 160 shelf slots plus every cell next to one. On the 550-cell medium map (S12A lane report) that includes about half the aisle cells. So the number mostly says "the robot stopped in an aisle". The stall list also includes the pickers' own episodes (79 of 677 undisturbed, 998 of 2,411 on the sticky floor), and pickers work at shelves. These JSONs do not measure how much of "stuck" is a real wait for a picker. The `waiting_shelf` column carries the standard class it is meant to approximate (SEMI E10 "standby: no operator"), but it does not isolate that class.
- **The detector was NOT changed.** The stall list behind every count in Sprints 5 to 10 is the same as before. Whether station and shelf waits should leave the list is an open operator decision (`docs/SCOPE.md` Sprint 12).
- **Where the shift goes (o).** With no disturbance, AGVs are moving 40.0% of the time. They are stopped next to a shelf 28.8%, stuck elsewhere 20.8%, in short stops 4.5%, idle 3.8% and at a station 2.1%, at 22.18 jobs per AGV-hour. On the sticky floor, moving falls to 12.1% and next-to-a-shelf rises to 51.7%, at 7.02 jobs per AGV-hour. On the breakdown run, 32.1% of AGV time is faulted and throughput is 10.08. The planner-blind blockage and the s8b floor change the budget by a few points (moving 35.0% and 35.6%; 19.53 and 19.26 jobs per AGV-hour).
- **Same-minute stops are not an outage signal yet (o).** On the sticky and breakdown runs every flagged minute is the zone-start minute. The undisturbed run has 13 flagged minutes after the start with no outage at all (9 on blind, 21 on the s8b floor), and that is the background rate any outage reading has to beat.
- **Blocking clusters are congestion, not deadlock (p).** The number to read is the rate against the undisturbed run: the sticky floor has 2.78x the undisturbed run's blocked robot-seconds per robot-hour (300.4 against 108.2), the breakdown run 1.51x and the planner-blind blockage 1.35x. The undisturbed run already has 49 clusters. None is a proven circular wait: the blocking relation is symmetric, and the vendor replans a robot after more than 5 stuck steps, so no circular wait survives in TA-RWARE. The counts were re-read from the schema-v2 files written by `wr-s12c-rerun` (commit 708763b) and are unchanged from the v1 files of 612518b (49 / 56 / 28 / 163 clusters, 0 / 0 / 5 / 0 chains, same rates). Blocking chains appear only on the breakdown run (5), because a chain needs a faulted robot at its head.
- **"Broke up" does not mean "cleared" (p).** 48 of the 49 undisturbed clusters broke up, but a break can last a single step. In zone 4 of the undisturbed run, the same two robots stand each other off from the 19th minute to the end of the stream. The vendor planner's replan frees them for one step, and they block each other again. Merged, that is one standoff: 16 clusters over 1,260 s, still open at stream end, and 26.3% of the run's blocked robot-seconds. The blind run carries the same standoff (19.5% of its blocked robot-seconds), so the 1.35x and the other ratios against s10-none lean on one pair of robots. On the sticky floor and the breakdown run, the longest standoff is a single cluster (1,875 s open at stream end; 655 s), and merging changes the counts little (163 clusters into 154 standoffs, 28 into 26). The "congestion, every cluster resolves" reading (operator, 2026-10-20) holds for most clusters, but not for this one: here the vendor replan does not resolve the jam inside the shift.
- **Message-loss cells (p).** With 6 planted dead cells per zone, the gap map finds 57 of 60 (recall 0.95). Its precision@10 is 0.57 against a ceiling of 0.60. This shows only that the method finds cells where every message is dropped. It says nothing about a real log, where most gaps may have no location cause.

**Caveats.**
- One seed set (0-9), one 500-step shift per run (the sticky phase A run: 30 zones). No count in (o) or (p) has a CI.
- `waiting_station` mixes being served with queueing, and the stream cannot split them without action states (Part 2 section 2). `idle` tests an empty `orderId`, not VDA 5050's empty node, edge and action states. S12C (PR #48) added `paused` and `no_data`, made `faulted` require error level CRITICAL or FATAL, and renamed `deadlock` and `knot` to `blocking_cluster` and `blocking_chain`; on the simulator runs `paused` and `no_data` are 0 s (the re-run `results/fleet/timebudget_*.json`, commit 8a17a0b) and every other value is unchanged. There is still no bucket for charging.
- The 30 s stuck threshold and the 30 s minimum cluster length are parameters set in this project. They are not standard values.
- (o) counts AGV-hours only, while (p) divides by robot-hours that include the pickers, so the two rates do not share a denominator.
- The gap-map run's stall-map truth grades are contaminated: the hotspot scorer counts dead cells as truth hits. Only `gap_grading` is read.
- The numbers are macOS arm64 only (pyastar2d tie-break).

## Sprint 13: a real shift (2026-10-20)

Sprint 13 runs the Sprint 12 time budget on a real robot log for the first time. S13A (PR #49) added `fleet/adapters/moroop.py`, which turns the MoRoOp dataset (Klein & Jeong 2026, arXiv 2610.02428, CC BY 4.0) into the same message stream the simulator emits, and ran `fleet/timebudget.py` on each of its nine shifts. The column mapping follows `docs/LITERATURE.md` Part 2b. Everything between this paragraph and "Reading the numbers" is the output of section (q) of `.venv/bin/python scripts/sprint8_tables.py`. Only its heading was demoted one level.

#### (q) Sprint 13: a real shift (S13A, MoRoOp, one robot)

| shift | span, h | moving (productive: travel) | waiting_station (productive: load/unload, or standby: queued) | waiting_shelf (standby: no operator) | stuck (blocked, >= 30 s) | stopped_short (blocked: congestion wait, < 30 s) | faulted (unscheduled downtime) | idle (standby: no work) | paused (standby: paused or manual mode, VDA `paused`) | no_data (unobserved: no message for more than max_gap_s) | throughput: jobs per robot-hour |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0: 2026_07_27_morning | 8.12 | 39.6% | 42.4% | n/a | 0.0% | 0.7% | not computed | 11.4% | 0.0% | 5.8% | 18.71 |
| 1: 2026_07_27_evening | 8.04 | 40.1% | 41.8% | n/a | 0.0% | 0.5% | not computed | 11.0% | 0.0% | 6.5% | 18.78 |
| 2: 2026_07_28_morning | 8.26 | 40.0% | 40.3% | n/a | 0.0% | 0.8% | not computed | 13.1% | 0.0% | 5.7% | 18.41 |
| 3: 2026_07_28_evening | 8.10 | 40.4% | 40.9% | n/a | 0.0% | 0.6% | not computed | 12.2% | 0.0% | 5.9% | 18.65 |
| 4: 2026_07_29_morning | 8.03 | 40.4% | 41.6% | n/a | 0.0% | 0.6% | not computed | 7.5% | 0.0% | 9.9% | 19.18 |
| 5: 2026_07_29_evening | 8.10 | 40.1% | 41.4% | n/a | 0.0% | 0.7% | not computed | 10.2% | 0.0% | 7.6% | 18.77 |
| 6: 2026_07_30_morning | 8.15 | 38.1% | 37.4% | n/a | 3.8% | 0.9% | not computed | 8.4% | 0.5% | 10.8% | 17.68 |
| 7: 2026_07_31_morning | 8.03 | 42.7% | 42.2% | n/a | 0.0% | 1.0% | not computed | 5.2% | 0.0% | 9.0% | 18.81 |
| 8: 2026_07_31_evening | 8.16 | 42.3% | 40.9% | n/a | 0.0% | 0.6% | not computed | 9.1% | 0.0% | 7.2% | 18.38 |
| **pooled, 9 shifts** | 72.98 | 40.4% | 41.0% | n/a | 0.4% | 0.7% | not computed | 9.8% | 0.1% | 7.6% | 18.59 |

Restated with the station-aware rule in (r).

**Against the robot's own label.** The stuck bucket holds 1,113 s of the pooled 262,717 s; 1,107 of them are in shift 6 (2026_07_30_morning, a manual intervention per the S13A lane report). The robot's stuck label (`stuck_reason` not None) covers 765 s, of which 0 s fall in the stuck bucket. Of its 77 episodes, 75 are shorter than the 30 s threshold; the 2 longer ones are both detected (2 hits, 0 misses), too few for a rate. Of the detector's 567 stuck runs, 544 have no label within 30 s, and 542 of those 544 sit on a station cell (median 39 s, a dwell just over the threshold). Failed navigation: no label in the data. The closest is the operations that ended in TIMEOUT: 8, all 8 overlapped by a stuck run (the lane report finds only 2 of them overlap a run off a station cell, `reports/wr-lane-s13a-moroop-budget.md` section 5 (d)). Paused (joystick or non-autonomous rows): 161 s. `faulted` is "not computed" (the diagnostics levels are undocumented) and `waiting_shelf` is "n/a" (no shelves, no picker). `no_data` is mostly station dwell: the log stores a row only when a value changes, and the 60 s rule moved 19,970 s there, 13,470 of which would otherwise be waiting_station (`shifts.*.no_data.would_have_been_bucket_without_gap_rule`).

**Data.** MoRoOp (Klein & Jeong, arXiv 2610.02428v1, licence CC BY 4.0), `Self-Organizing-Production-Logistics/MoRoOp` revision 1.0.1: one wheel.me AMR in a lab, 9 shifts, 132,838 messages, 0 parse rejects. Shares are of the shift's span (`timebudget_robot.share` per shift, `share` pooled; the pooled row sums the nine per-shift runs). The station share is set by the job generator's dwell and is not a finding. **Limit:** one robot, so no deadlock, congestion or hotspot result. Sources: `results/fleet/timebudget_moroop.json` (`seconds`, `share`, `label`, `no_data`, `src.hf`), `results/fleet/timebudget_moroop_shifts.json` (`shifts.*.timebudget_robot`, `shifts.*.jobs_per_robot_hour`), from the S13A lane (PR #49).

**Reading the numbers.**
- **The pipeline runs on a real robot (q).** Nine shifts, 0 parse rejects, and the buckets sum to the span in every shift. The robot moves 40.4% of the time and stands at a station 41.0%, at 18.59 jobs per robot-hour pooled (17.68 to 19.18 per shift). The station share comes from the job generator's dwell times, so it says nothing about the robot.
- **Stuck time is one event (q).** 1,107 of the 1,113 stuck seconds are in one shift (30 Jul morning), which the S13A lane report ties to a manual intervention; every other shift has 0 or 6 s.
- **The robot's own stuck label and the stuck bucket share no seconds (q).** 0 of the label's 765 s fall in the stuck bucket. 75 of its 77 episodes are shorter than 30 s, so the detector cannot see them by design; the 2 longer ones are both caught, which is too few for a rate.
- **Station dwells are the false alarms (q).** 542 of the detector's 544 unlabelled stuck runs sit on a station cell. On this log, the station-cell exclusion that Sprint 12 left open would remove nearly all of them.
- **There is no failed-navigation label.** The closest is the 8 operations that ended in TIMEOUT. All 8 overlap a stuck run, but the lane report finds only 2 of them overlap a run off a station cell.

**Caveats.**
- One robot in an 8 x 2.3 m lab (`docs/LITERATURE.md` Part 2b), so there is no deadlock, congestion or hotspot result.
- The log stores a row only when a value changes, so a long gap means "unchanged", not "lost", and `no_data` is mostly station dwell. A change-only source needs its own gap rule; S13A did not add one.
- `faulted` is not computed: the diagnostics levels (Ok, Warning, Error, Stale) are undocumented and are not mapped to VDA 5050 error levels.
- No chance baseline for the label comparison, and no CI.

## Sprint 13B: the stuck rule knows where stations are (2026-10-21)

S13B (PR #50) taught the stall detector where the stations are. A stopped run whose first stopped cell is a station goal cell, or within a set radius of one, is filed as SERVICING once it passes the 30 s threshold, and no stuck episode opens. Sprint 12 left open whether station waits should leave the stall list (`docs/SCOPE.md` Sprint 12), and S13A found that 542 of the 544 unlabelled stuck runs on the real MoRoOp log were station dwells. `waiting_station` in (o) maps to "productive: load/unload, or standby: queued" (`docs/LITERATURE.md` Part 2 section 2), not to blocked time, so it does not belong in a stall list. The queue item `wr-s13b-rerun` rebuilt the stores of the five simulator runs with the rule (radius 0) and recomputed every stall-list number on them. It re-ran the MoRoOp analysis with radius 1, and wrote everything to `-st` files next to the originals (results commit 2970c17). Shelf waits are not touched. Everything between this paragraph and "Reading the numbers" is the output of section (r) of `.venv/bin/python scripts/sprint8_tables.py`. Only its heading was demoted one level.

#### (r) The stuck rule knows where stations are (S13B): old / station-aware

| measure | run | old rule | station-aware | delta | files |
|---|---|---|---|---|---|
| top-20 truth precision | s10-none | 0.000 (no truth cells) | 0.000 (no truth cells) | +0.000 | `results/fleet/hotspot_s10-none.json`, `results/fleet/hotspot_s10-none-st.json` |
| top-20 truth precision (hits / truth cells) | s10c-blind | 0.085 (17 / 50) | 0.085 (17 / 50) | +0.000 | `results/fleet/hotspot_s10c-blind.json`, `results/fleet/hotspot_s10c-blind-st.json` |
| top-20 truth precision (hits / truth cells) | s10-breakdown | 0.095 (19 / 283) | 0.095 (19 / 283) | +0.000 | `results/fleet/hotspot_s10-breakdown.json`, `results/fleet/hotspot_s10-breakdown-st.json` |
| top-20 truth precision (hits / truth cells) | s8b-medium-80-p03-07 | 0.965 (193 / 800) | 0.965 (193 / 800) | +0.000 | `results/fleet/baselines_s8b-medium-80-p03-07.json`, `results/fleet/hotspot_s8b-medium-80-p03-07-st.json` |
| top-20 truth precision (hits / truth cells) | closed-loop-sticky | 0.955 (573 / 2400) | 0.955 (573 / 2400) | +0.000 | `results/fleet/baselines_closed-loop-sticky.json`, `results/fleet/hotspot_closed-loop-sticky-st.json` |
| frozen cells hit at K 20 / frozen cells (m) | s10-breakdown | 19 / 283 | 19 / 283 | +0 | `results/fleet/hotspot_s10-breakdown.json`, `results/fleet/hotspot_s10-breakdown-st.json` |
| ungated forecasts: truth hits / graded (l), (m) | s10-none | 0 / 1391 | 0 / 1391 | +0 hits | `results/fleet/hotspot_s10-none.json`, `results/fleet/hotspot_s10-none-st.json` |
| ungated forecasts: truth hits / graded (l), (m) | s10c-blind | 16 / 1363 | 16 / 1363 | +0 hits | `results/fleet/hotspot_s10c-blind.json`, `results/fleet/hotspot_s10c-blind-st.json` |
| ungated forecasts: truth hits / graded (l), (m) | s10-breakdown | 25 / 488 | 25 / 488 | +0 hits | `results/fleet/hotspot_s10-breakdown.json`, `results/fleet/hotspot_s10-breakdown-st.json` |
| gated forecasts, baseline and persistence gate (l) | s10-none | see (l) | not rerun | n/a | `results/fleet/hotspot_s10-none-gate-baseline.json`, `results/fleet/hotspot_s10-none-gate-persistence.json` |
| gated forecasts, baseline and persistence gate (l) | s10c-blind | see (l) | not rerun | n/a | `results/fleet/hotspot_s10c-blind-gate-baseline.json`, `results/fleet/hotspot_s10c-blind-gate-persistence.json` |
| gated forecasts, baseline and persistence gate (l) | closed-loop-sticky | see (l) | not rerun | n/a | `results/fleet/hotspot_closed-loop-sticky-gate-baseline.json`, `results/fleet/hotspot_closed-loop-sticky-gate-persistence.json` |
| S10D map - persistence, truth precision, K 20 / K 40 (j) | s10-none | K 20: n/a, n/a, no truth positives; K 40: n/a, n/a, no truth positives | K 20: n/a, n/a, no truth positives; K 40: n/a, n/a, no truth positives | unchanged (`k`, `paired`, `chance` blocks equal) | `results/fleet/baselines_s10-none.json`, `results/fleet/baselines_s10-none-st.json` |
| S10D map - persistence, truth precision, K 20 / K 40 (j) | s10c-blind | K 20: -0.001 (-0.002 to +0.000), within noise; K 40: +0.000 (+0.000 to +0.000), identical top-K sets | K 20: -0.001 (-0.002 to +0.000), within noise; K 40: +0.000 (+0.000 to +0.000), identical top-K sets | unchanged (`k`, `paired`, `chance` blocks equal) | `results/fleet/baselines_s10c-blind.json`, `results/fleet/baselines_s10c-blind-st.json` |
| S10D map - persistence, truth precision, K 20 / K 40 (j) | s10-breakdown | n/a (no station-unaware file) | K 20: +0.000 (+0.000 to +0.000), identical top-K sets; K 40: +0.000 (+0.000 to +0.000), identical top-K sets | n/a | `results/fleet/baselines_s10-breakdown-st.json` |
| S10D map - persistence, truth precision, K 20 / K 40 (j) | s8b-medium-80-p03-07 | K 20: -0.008 (-0.020 to +0.005), within noise; K 40: -0.023 (-0.034 to -0.011), worse | K 20: -0.008 (-0.020 to +0.005), within noise; K 40: -0.023 (-0.034 to -0.011), worse | unchanged (`k`, `paired`, `chance` blocks equal) | `results/fleet/baselines_s8b-medium-80-p03-07.json`, `results/fleet/baselines_s8b-medium-80-p03-07-st.json` |
| S10D map - persistence, truth precision, K 20 / K 40 (j) | closed-loop-sticky | K 20: +0.002 (-0.010 to +0.017), within noise; K 40: -0.018 (-0.029 to -0.008), worse | K 20: +0.002 (-0.010 to +0.017), within noise; K 40: -0.018 (-0.029 to -0.008), worse | unchanged (`k`, `paired`, `chance` blocks equal) | `results/fleet/baselines_closed-loop-sticky.json`, `results/fleet/baselines_closed-loop-sticky-st.json` |
| S10D map - persistence, truth precision, K 20 / K 40 (j) | s8e-long-w0.5 | see (j) | not rerun | n/a | `results/fleet/baselines_s8e-long-w0.5.json` |
| lesson_persist, hot_cell and hot_robot lessons as in (f): held / graded, lift over chance | s10-none | 4 / 6, lift 2.94 | 3 / 5, lift 5.14 | lift +2.20 | `results/fleet/hotspot_s10-none.json`, `results/fleet/hotspot_s10-none-st.json` |
| lesson_persist, hot_cell and hot_robot lessons as in (f): held / graded, lift over chance | s10c-blind | 4 / 5, lift 3.21 | 3 / 4, lift 6.40 | lift +3.19 | `results/fleet/hotspot_s10c-blind.json`, `results/fleet/hotspot_s10c-blind-st.json` |
| AMOC, decayed map K 20: detected while open / windows (k) | s10c-blind | 6 / 50 | 6 / 50 | +0 | `results/fleet/amoc_blind.json`, `results/fleet/amoc_blind-st.json` |
| AMOC, decayed map K 20: false alarms per zone-hour, s10-none / s10c-blind outside windows (k) | s10c-blind | 177.8 / 175.1 | 177.8 / 175.1 | unchanged (`amoc` and `by_k` blocks equal) | `results/fleet/amoc_blind.json`, `results/fleet/amoc_blind-st.json` |
| CUSUM and short-memory map (n) | s10c-blind | see (n) | not rerun | n/a | `results/fleet/amoc_fast.json`, `results/fleet/amoc_shortmap.json` |
| time budget: stuck share of AGV time (o) | s10-none | 20.81% | 20.81% | +0.00 pts | `results/fleet/timebudget_s10-none.json`, `results/fleet/timebudget_s10-none-st.json` |
| stall list: episodes starting on a station cell / episodes (o) | s10-none | 10 / 677 | 0 / 667 | -10 episodes | `results/fleet/timebudget_s10-none.json`, `results/fleet/timebudget_s10-none-st.json` |
| time budget: stuck share of AGV time (o) | s10c-blind | 25.90% | 25.90% | +0.00 pts | `results/fleet/timebudget_s10c-blind.json`, `results/fleet/timebudget_s10c-blind-st.json` |
| stall list: episodes starting on a station cell / episodes (o) | s10c-blind | 8 / 646 | 0 / 638 | -8 episodes | `results/fleet/timebudget_s10c-blind.json`, `results/fleet/timebudget_s10c-blind-st.json` |
| time budget: stuck share of AGV time (o) | s10-breakdown | 18.64% | 18.64% | +0.00 pts | `results/fleet/timebudget_s10-breakdown.json`, `results/fleet/timebudget_s10-breakdown-st.json` |
| stall list: episodes starting on a station cell / episodes (o) | s10-breakdown | 9 / 526 | 5 / 522 | -4 episodes | `results/fleet/timebudget_s10-breakdown.json`, `results/fleet/timebudget_s10-breakdown-st.json` |
| time budget: stuck share of AGV time (o) | s8b-medium-80-p03-07 | 22.57% | 22.57% | +0.00 pts | `results/fleet/timebudget_s8b-medium-80-p03-07.json`, `results/fleet/timebudget_s8b-medium-80-p03-07-st.json` |
| stall list: episodes starting on a station cell / episodes (o) | s8b-medium-80-p03-07 | 7 / 657 | 0 / 650 | -7 episodes | `results/fleet/timebudget_s8b-medium-80-p03-07.json`, `results/fleet/timebudget_s8b-medium-80-p03-07-st.json` |
| time budget: stuck share of AGV time (o) | closed-loop-sticky | 32.05% | 32.05% | +0.00 pts | `results/fleet/timebudget_closed-loop-sticky.json`, `results/fleet/timebudget_closed-loop-sticky-st.json` |
| stall list: episodes starting on a station cell / episodes (o) | closed-loop-sticky | 47 / 2411 | 0 / 2364 | -47 episodes | `results/fleet/timebudget_closed-loop-sticky.json`, `results/fleet/timebudget_closed-loop-sticky-st.json` |
| blocking clusters; blocked robot-s per robot-hour (x s10-none) (p) | s10-none | 49; 108.2 (1.00x) | 41; 100.6 (1.00x) | -8; -7.6 | `results/fleet/deadlock_s10-none.json`, `results/fleet/deadlock_s10-none-st.json` |
| blocking clusters; blocked robot-s per robot-hour (x s10-none) (p) | s10c-blind | 56; 146.1 (1.35x) | 49; 137.4 (1.37x) | -7; -8.7 | `results/fleet/deadlock_s10c-blind.json`, `results/fleet/deadlock_s10c-blind-st.json` |
| blocking clusters; blocked robot-s per robot-hour (x s10-none) (p) | s10-breakdown | 28; 162.9 (1.51x) | 25; 160.0 (1.59x) | -3; -2.9 | `results/fleet/deadlock_s10-breakdown.json`, `results/fleet/deadlock_s10-breakdown-st.json` |
| blocking clusters; blocked robot-s per robot-hour (x s10-none) (p) | s8b-medium-80-p03-07 | n/a (no station-unaware run) | 45; 135.1 (1.34x) | n/a | `results/fleet/deadlock_s8b-medium-80-p03-07-st.json` |
| blocking clusters; blocked robot-s per robot-hour (x s10-none) (p) | closed-loop-sticky | 163; 300.4 (2.78x) | 156; 297.0 (2.95x) | -7; -3.5 | `results/fleet/deadlock_closed-loop-sticky.json`, `results/fleet/deadlock_closed-loop-sticky-st.json` |
| stuck share of the span; stuck s (q) | MoRoOp, 9 shifts (radius 1) | 0.42%; 1113 | 0.005%; 13 | -1100 s | `results/fleet/timebudget_moroop.json`, `results/fleet/timebudget_moroop-st.json` |
| shift 6 (2026_07_30_morning, the manual intervention): stuck s (q) | MoRoOp, 9 shifts (radius 1) | 1107 | 7 | -1100 | `results/fleet/timebudget_moroop_shifts.json`, `results/fleet/timebudget_moroop_shifts-st.json` |
| shift 6 (2026_07_30_morning, the manual intervention): stopped_short s (q) | MoRoOp, 9 shifts (radius 1) | 276 | 1376 | +1100 | `results/fleet/timebudget_moroop_shifts.json`, `results/fleet/timebudget_moroop_shifts-st.json` |
| detector stuck runs (q) | MoRoOp, 9 shifts (radius 1) | 567 | 2 | -565 | `results/fleet/timebudget_moroop.json`, `results/fleet/timebudget_moroop-st.json`, `results/fleet/moroop_label-st.json` |
| stuck runs with no label within 30 s (q) | MoRoOp, 9 shifts (radius 1) | 544 | 1 | -543 | `results/fleet/timebudget_moroop.json`, `results/fleet/timebudget_moroop-st.json`, `results/fleet/moroop_label-st.json` |
| label episodes >= 30 s detected (q) | MoRoOp, 9 shifts (radius 1) | 2 / 2 | 2 / 2 | +0 | `results/fleet/timebudget_moroop.json`, `results/fleet/timebudget_moroop-st.json`, `results/fleet/moroop_label-st.json` |
| TIMEOUT operations overlapped by a stuck run (q) | MoRoOp, 9 shifts (radius 1) | 8 / 8 | 1 / 8 | -7 | `results/fleet/timebudget_moroop.json`, `results/fleet/timebudget_moroop-st.json`, `results/fleet/moroop_label-st.json` |
| unlabelled stuck runs on a station cell (q) | MoRoOp, 9 shifts (radius 1) | 542 | 0 | -542 | `results/fleet/timebudget_moroop.json`, `results/fleet/timebudget_moroop-st.json` |

Restated with the bounded rule in (s).

Old rule = the station-unaware detector of Sprints 5 to 13A; station-aware = S13B (PR #50): a stopped run whose first stopped cell is within the station radius of a station goal cell becomes SERVICING after the 30 s threshold, not a stuck episode. Simulator runs: stations `auto` from the emit ledger, radius 0 (asserted: `src.station_radius`, `station_rule.radius`); MoRoOp: `fleet/data/moroop/stations.json`, radius 1 (asserted). The station-aware files come from queue item `wr-s13b-rerun`, which rebuilt each store as `store-st` with `ingest --stations auto` and re-ran costmap, lessons, grade, hotspot_score, baselines, timebudget and deadlock on it, with the original publish schedules and lesson windows, and checked that no original store or results file changed. Unchanged rows are asserted, not eyeballed: the final map (`zones`) is equal in every run, and the S10D `k`, `paired` and `chance` blocks and the AMOC `amoc` and `by_k` blocks are equal. Old top-20 precision for s8b-medium-80-p03-07 and closed-loop-sticky is read from the S10D baselines JSON, because their hotspot JSON on disk predates `truth_kinds` (s8b) or does not exist (sticky). The sticky baselines files differ in `params.horizon_s` (3600 old, 1245 new); the asserted blocks are equal anyway. s10-breakdown has no station-unaware S10D file and s8b no station-unaware blocking run, so those rows have no old value. The ratio in the blocking rows is the run's rate over the s10-none rate under the same rule. The lesson_persist rows pool hot_cell and hot_robot lessons, as (f) does (`lesson_persist_chance`); the hot_cell-only block of (j) (`baselines.lesson_persist`) is equal under both rules except `n_hot_robot_excluded` (asserted). MoRoOp unlabelled runs on a station cell are counted from `label.false_alarms[].on_station_cell`.

**Reading the numbers.**
- **From this section on, the station-aware numbers are the headline; earlier tables keep the old rule and say so.**
- **The simulator results do not move (r).** On all five runs the final map is the same cells at the same costs. Top-20 truth precision is unchanged (0.085 on the planner-blind blockage, 0.095 on breakdowns, 0.965 on the s8b floor, 0.955 on the sticky floor). So are the forecast truth grades (16 of 1,363 on the blind run), the frozen-cell hits (19 of 283), every S10D map-against-persistence verdict and the AMOC detection (6 of 50 at K 20, 177.8 false alarms per zone-hour on the undisturbed run). The reason: the map counts stall messages, and a robot waiting at a station sends none (S13B lane report, "Store readers"). The rule only removes stuck episodes, so it reaches the map only through which stalls count as inside an episode.
- **What moved on the simulator is the stall list itself (r).** Station episodes leave it: 10, 8, 4, 7 and 47 on the undisturbed, blind, breakdown, s8b and sticky runs (677 to 667 episodes undisturbed, 2,411 to 2,364 on the sticky floor). The stuck share of AGV time is unchanged on every run (20.81% undisturbed, 32.05% sticky), because the time budget already put a stop on a station cell into `waiting_station`. On the breakdown run, 5 episodes that start on a station cell remain; why was not inspected.
- **Blocking clusters fall by 3 to 8 per run (r)**, and the undisturbed rate falls by a larger share than the others (108.2 to 100.6 blocked robot-s per robot-hour, 7.0%, against 1.2% to 6.0%). So the ratios against it rise: 1.35x to 1.37x (planner-blind blockage), 1.51x to 1.59x (breakdowns), 2.78x to 2.95x (sticky floor). The s8b floor, run for the first time, is at 1.34x. The direction of every reading in (p) holds.
- **The lesson_persist lift of (f) doubles on few lessons (r).** It pools hot_cell and hot_robot lessons, and goes from 2.94 to 5.14 undisturbed and from 3.21 to 6.40 on the blind run. One hot_robot lesson per run is gone (6 to 5 and 5 to 4 graded), and the mean chance rate of the lessons left falls from 0.227 to 0.117 and from 0.249 to 0.117 (`lesson_persist_chance`). The hot_cell lessons of (j) are unchanged. Why that hot_robot lesson went was not inspected. The observed counts are 3 of 5 and 3 of 4, too few to read the lift as a change in the method.
- **On the real log, the station rule removes the false alarms and the one real stop with them (r).** With radius 1, the detector's stuck runs fall from 567 to 2 and the unlabelled ones from 544 to 1 (the remaining one is off a station and overlaps a paused message). The robot's two labelled episodes of 30 s or more are still both detected. But the stuck share falls from 0.42% to 0.005% (1,113 s to 13 s). That is because the 1,107 s stop in shift 6, which (q) ties to a manual intervention, started within one cell of a station: it is now 1,100 s of `stopped_short`, a bucket whose definition is "< 30 s". TIMEOUT operations overlapped by a stuck run fall from 8 of 8 to 1 of 8. So on this log the rule trades 543 false alarms for the only long stop and 7 of 8 timeout overlaps. Whether those 7 were real stops or dwells was not inspected per operation (S13B lane report).
- **The S12 question is answered for stations (r).** Station waits now leave the stall list. On the simulator that changes no map, precision or detection number. On the real log it removes nearly every false alarm. Shelf waits stay in the list.

**Caveats.**
- The gated forecasts of (l), the CUSUM and short-memory map of (n) and the s8e-long run of (j) were not rerun. Their rows in (r) say so. The final maps they would read are unchanged on the runs that were rerun, but that is not a rerun.
- The simulator runs use radius 0 and MoRoOp radius 1, so the two halves of (r) apply different rules. No other radius was run on either.
- A suppressed stop stays suppressed however long it lasts. The 1,107 s MoRoOp stop shows that this hides a long stop that starts next to a station.
- `stopped_short` is defined as a stop under 30 s, yet on MoRoOp it now holds a 1,100 s stop. The bucket names in (o) and (q) have not been changed for the new rule.
- One seed set (0-9) and one 500-step shift per simulator run, one robot on the real log; no CI on any count in (r). macOS arm64 only (pyastar2d tie-break).

## Sprint 14A: the station stop has an upper bound (2026-10-21)

S13B filed every stop at a station as SERVICING, however long it lasted, and so hid the 1,107 s manual-intervention stop on MoRoOp (r). S14A (PR #51) puts a bound T on a station stop: a SERVICING run still stopped T seconds after the stop began becomes a stuck episode with cause `station_overrun`. T comes from the run's own station stops, as `docs/LITERATURE.md` Part 4 section 1 set it: T = min(300 s, exp(Q3 + 3 IQR of ln dwell)). That is the NIST outer fence on the log scale, capped at the OEE five-minute small-stop edge, which is also the MoRoOp dispatcher's own 300 s timeout. Every stuck episode now also carries a `cause_label` from Part 4 section 2. The queue item `wr-s14a-rerun` rebuilt every `-st` store as `store-sb` with `--servicing-max-s auto`. The radius is the same as in (r): 0 on the simulator, 1 on MoRoOp. It wrote `-sb` files next to the `-st` ones (results commit d5b777a). Everything between this paragraph and "Reading the numbers" is the output of section (s) of `.venv/bin/python scripts/sprint8_tables.py`. Only its heading was demoted one level.

#### (s) The station stop has an upper bound (S14A): station-aware / bounded

| measure | run | station-aware (r) | bounded (S14A) | delta | files |
|---|---|---|---|---|---|
| top-20 truth precision | s10-none | 0.000 (no truth cells) | 0.000 (no truth cells) | +0.000 | `results/fleet/hotspot_s10-none-st.json`, `results/fleet/hotspot_s10-none-sb.json` |
| top-20 truth precision (hits / truth cells) | s10c-blind | 0.085 (17 / 50) | 0.085 (17 / 50) | +0.000 | `results/fleet/hotspot_s10c-blind-st.json`, `results/fleet/hotspot_s10c-blind-sb.json` |
| top-20 truth precision (hits / truth cells) | s10-breakdown | 0.095 (19 / 283) | 0.095 (19 / 283) | +0.000 | `results/fleet/hotspot_s10-breakdown-st.json`, `results/fleet/hotspot_s10-breakdown-sb.json` |
| top-20 truth precision (hits / truth cells) | s8b-medium-80-p03-07 | 0.965 (193 / 800) | 0.965 (193 / 800) | +0.000 | `results/fleet/hotspot_s8b-medium-80-p03-07-st.json`, `results/fleet/hotspot_s8b-medium-80-p03-07-sb.json` |
| top-20 truth precision (hits / truth cells) | closed-loop-sticky | 0.955 (573 / 2400) | 0.955 (573 / 2400) | +0.000 | `results/fleet/hotspot_closed-loop-sticky-st.json`, `results/fleet/hotspot_closed-loop-sticky-sb.json` |
| frozen cells hit at K 20 / frozen cells (m) | s10-breakdown | 19 / 283 | 19 / 283 | +0 | `results/fleet/hotspot_s10-breakdown-st.json`, `results/fleet/hotspot_s10-breakdown-sb.json` |
| ungated forecasts: truth hits / graded (l), (m) | s10-none | 0 / 1391 | 0 / 1391 | +0 hits | `results/fleet/hotspot_s10-none-st.json`, `results/fleet/hotspot_s10-none-sb.json` |
| ungated forecasts: truth hits / graded (l), (m) | s10c-blind | 16 / 1363 | 16 / 1363 | +0 hits | `results/fleet/hotspot_s10c-blind-st.json`, `results/fleet/hotspot_s10c-blind-sb.json` |
| ungated forecasts: truth hits / graded (l), (m) | s10-breakdown | 25 / 488 | 25 / 488 | +0 hits | `results/fleet/hotspot_s10-breakdown-st.json`, `results/fleet/hotspot_s10-breakdown-sb.json` |
| gated forecasts, baseline and persistence gate (l) | s10-none | not rerun (see (l), (r)) | not rerun | n/a | `results/fleet/hotspot_s10-none-gate-baseline.json`, `results/fleet/hotspot_s10-none-gate-persistence.json` |
| gated forecasts, baseline and persistence gate (l) | s10c-blind | not rerun (see (l), (r)) | not rerun | n/a | `results/fleet/hotspot_s10c-blind-gate-baseline.json`, `results/fleet/hotspot_s10c-blind-gate-persistence.json` |
| gated forecasts, baseline and persistence gate (l) | closed-loop-sticky | not rerun (see (l), (r)) | not rerun | n/a | `results/fleet/hotspot_closed-loop-sticky-gate-baseline.json`, `results/fleet/hotspot_closed-loop-sticky-gate-persistence.json` |
| S10D map - persistence, truth precision, K 20 / K 40 (j) | s10-none | K 20: n/a, n/a, no truth positives; K 40: n/a, n/a, no truth positives | K 20: n/a, n/a, no truth positives; K 40: n/a, n/a, no truth positives | unchanged (`k`, `paired`, `chance`, `lesson_persist` blocks equal) | `results/fleet/baselines_s10-none-st.json`, `results/fleet/baselines_s10-none-sb.json` |
| S10D map - persistence, truth precision, K 20 / K 40 (j) | s10c-blind | K 20: -0.001 (-0.002 to +0.000), within noise; K 40: +0.000 (+0.000 to +0.000), identical top-K sets | K 20: -0.001 (-0.002 to +0.000), within noise; K 40: +0.000 (+0.000 to +0.000), identical top-K sets | unchanged (`k`, `paired`, `chance`, `lesson_persist` blocks equal) | `results/fleet/baselines_s10c-blind-st.json`, `results/fleet/baselines_s10c-blind-sb.json` |
| S10D map - persistence, truth precision, K 20 / K 40 (j) | s10-breakdown | K 20: +0.000 (+0.000 to +0.000), identical top-K sets; K 40: +0.000 (+0.000 to +0.000), identical top-K sets | K 20: +0.000 (+0.000 to +0.000), identical top-K sets; K 40: +0.000 (+0.000 to +0.000), identical top-K sets | unchanged (`k`, `paired`, `chance`, `lesson_persist` blocks equal) | `results/fleet/baselines_s10-breakdown-st.json`, `results/fleet/baselines_s10-breakdown-sb.json` |
| S10D map - persistence, truth precision, K 20 / K 40 (j) | s8b-medium-80-p03-07 | K 20: -0.008 (-0.020 to +0.005), within noise; K 40: -0.023 (-0.034 to -0.011), worse | K 20: -0.008 (-0.020 to +0.005), within noise; K 40: -0.023 (-0.034 to -0.011), worse | unchanged (`k`, `paired`, `chance`, `lesson_persist` blocks equal) | `results/fleet/baselines_s8b-medium-80-p03-07-st.json`, `results/fleet/baselines_s8b-medium-80-p03-07-sb.json` |
| S10D map - persistence, truth precision, K 20 / K 40 (j) | closed-loop-sticky | K 20: +0.002 (-0.010 to +0.017), within noise; K 40: -0.018 (-0.029 to -0.008), worse | K 20: +0.002 (-0.010 to +0.017), within noise; K 40: -0.018 (-0.029 to -0.008), worse | unchanged (`k`, `paired`, `chance`, `lesson_persist` blocks equal) | `results/fleet/baselines_closed-loop-sticky-st.json`, `results/fleet/baselines_closed-loop-sticky-sb.json` |
| S10D map - persistence, truth precision, K 20 / K 40 (j) | s8e-long-w0.5 | not rerun | not rerun | n/a | `results/fleet/baselines_s8e-long-w0.5.json` |
| lesson_persist, hot_cell and hot_robot lessons as in (f): held / graded, lift over chance | s10-none | 3 / 5, lift 5.14 | 3 / 5, lift 5.14 | lift +0.00 | `results/fleet/hotspot_s10-none-st.json`, `results/fleet/hotspot_s10-none-sb.json` |
| lesson_persist, hot_cell and hot_robot lessons as in (f): held / graded, lift over chance | s10c-blind | 3 / 4, lift 6.40 | 3 / 4, lift 6.40 | lift +0.00 | `results/fleet/hotspot_s10c-blind-st.json`, `results/fleet/hotspot_s10c-blind-sb.json` |
| AMOC, decayed map K 20: detected while open / windows (k) | s10c-blind | 6 / 50 | 6 / 50 | +0 | `results/fleet/amoc_blind-st.json`, `results/fleet/amoc_blind-sb.json` |
| AMOC, decayed map K 20: false alarms per zone-hour, s10-none / s10c-blind outside windows (k) | s10c-blind | 177.8 / 175.1 | 177.8 / 175.1 | unchanged (`amoc` and `by_k` blocks equal) | `results/fleet/amoc_blind-st.json`, `results/fleet/amoc_blind-sb.json` |
| CUSUM and short-memory map (n) | s10c-blind | not rerun (see (n), (r)) | not rerun | n/a | `results/fleet/amoc_fast.json`, `results/fleet/amoc_shortmap.json` |
| time budget: stuck share of AGV time (o) | s10-none | 20.81% | 20.81% | +0.00 pts | `results/fleet/timebudget_s10-none-st.json`, `results/fleet/timebudget_s10-none-sb.json` |
| stall list: episodes starting on a station cell / episodes (o) | s10-none | 0 / 667 | 0 / 667 | +0 episodes | `results/fleet/timebudget_s10-none-st.json`, `results/fleet/timebudget_s10-none-sb.json` |
| time budget: stuck share of AGV time (o) | s10c-blind | 25.90% | 26.03% | +0.13 pts | `results/fleet/timebudget_s10c-blind-st.json`, `results/fleet/timebudget_s10c-blind-sb.json` |
| stall list: episodes starting on a station cell / episodes (o) | s10c-blind | 0 / 638 | 1 / 639 | +1 episodes | `results/fleet/timebudget_s10c-blind-st.json`, `results/fleet/timebudget_s10c-blind-sb.json` |
| time budget: stuck share of AGV time (o) | s10-breakdown | 18.64% | 18.64% | +0.00 pts | `results/fleet/timebudget_s10-breakdown-st.json`, `results/fleet/timebudget_s10-breakdown-sb.json` |
| stall list: episodes starting on a station cell / episodes (o) | s10-breakdown | 5 / 522 | 5 / 522 | +0 episodes | `results/fleet/timebudget_s10-breakdown-st.json`, `results/fleet/timebudget_s10-breakdown-sb.json` |
| time budget: stuck share of AGV time (o) | s8b-medium-80-p03-07 | 22.57% | 22.57% | +0.00 pts | `results/fleet/timebudget_s8b-medium-80-p03-07-st.json`, `results/fleet/timebudget_s8b-medium-80-p03-07-sb.json` |
| stall list: episodes starting on a station cell / episodes (o) | s8b-medium-80-p03-07 | 0 / 650 | 0 / 650 | +0 episodes | `results/fleet/timebudget_s8b-medium-80-p03-07-st.json`, `results/fleet/timebudget_s8b-medium-80-p03-07-sb.json` |
| time budget: stuck share of AGV time (o) | closed-loop-sticky | 32.05% | 32.95% | +0.90 pts | `results/fleet/timebudget_closed-loop-sticky-st.json`, `results/fleet/timebudget_closed-loop-sticky-sb.json` |
| stall list: episodes starting on a station cell / episodes (o) | closed-loop-sticky | 0 / 2364 | 25 / 2389 | +25 episodes | `results/fleet/timebudget_closed-loop-sticky-st.json`, `results/fleet/timebudget_closed-loop-sticky-sb.json` |
| blocking clusters; blocked robot-s per robot-hour (x s10-none) (p) | s10-none | 41; 100.6 (1.00x) | 41; 100.6 (1.00x) | +0; +0.0 | `results/fleet/deadlock_s10-none-st.json`, `results/fleet/deadlock_s10-none-sb.json` |
| blocking clusters; blocked robot-s per robot-hour (x s10-none) (p) | s10c-blind | 49; 137.4 (1.37x) | 52; 142.4 (1.41x) | +3; +4.9 | `results/fleet/deadlock_s10c-blind-st.json`, `results/fleet/deadlock_s10c-blind-sb.json` |
| blocking clusters; blocked robot-s per robot-hour (x s10-none) (p) | s10-breakdown | 25; 160.0 (1.59x) | 25; 160.0 (1.59x) | +0; +0.0 | `results/fleet/deadlock_s10-breakdown-st.json`, `results/fleet/deadlock_s10-breakdown-sb.json` |
| blocking clusters; blocked robot-s per robot-hour (x s10-none) (p) | s8b-medium-80-p03-07 | 45; 135.1 (1.34x) | 45; 135.1 (1.34x) | +0; +0.0 | `results/fleet/deadlock_s8b-medium-80-p03-07-st.json`, `results/fleet/deadlock_s8b-medium-80-p03-07-sb.json` |
| blocking clusters; blocked robot-s per robot-hour (x s10-none) (p) | closed-loop-sticky | 156; 297.0 (2.95x) | 161; 299.7 (2.98x) | +5; +2.8 | `results/fleet/deadlock_closed-loop-sticky-st.json`, `results/fleet/deadlock_closed-loop-sticky-sb.json` |
| stuck share of the span; stuck s (q) | MoRoOp, 9 shifts (radius 1) | 0.005%; 13 | 0.675%; 1773 | +1760 s | `results/fleet/timebudget_moroop-st.json`, `results/fleet/timebudget_moroop-sb.json` |
| shift 6 (2026_07_30_morning, the manual intervention): stuck s (q) | MoRoOp, 9 shifts (radius 1) | 7 | 1107 | +1100 | `results/fleet/timebudget_moroop_shifts-st.json`, `results/fleet/timebudget_moroop_shifts-sb.json` |
| shift 6 (2026_07_30_morning, the manual intervention): stopped_short s (q) | MoRoOp, 9 shifts (radius 1) | 1376 | 276 | -1100 | `results/fleet/timebudget_moroop_shifts-st.json`, `results/fleet/timebudget_moroop_shifts-sb.json` |
| detector stuck runs (q) | MoRoOp, 9 shifts (radius 1) | 2 | 6 | +4 | `results/fleet/moroop_label-st.json`, `results/fleet/moroop_label-sb.json` |
| stuck runs with no label within 30 s (q) | MoRoOp, 9 shifts (radius 1) | 1 | 5 | +4 | `results/fleet/moroop_label-st.json`, `results/fleet/moroop_label-sb.json` |
| label episodes >= 30 s detected (q) | MoRoOp, 9 shifts (radius 1) | 2 / 2 | 2 / 2 | +0 | `results/fleet/moroop_label-st.json`, `results/fleet/moroop_label-sb.json` |
| TIMEOUT operations overlapped by a stuck run (q) | MoRoOp, 9 shifts (radius 1) | 1 / 8 | 5 / 8 | +4 | `results/fleet/moroop_label-st.json`, `results/fleet/moroop_label-sb.json` |
| unlabelled stuck runs on a station cell (q) | MoRoOp, 9 shifts (radius 1) | 0 | 3 | +3 | `results/fleet/moroop_label-st.json`, `results/fleet/moroop_label-sb.json` |

**The bound per run, as the files record it** (`servicing_max_s`, `servicing_sample_n`, `servicing_q1_s`, `servicing_q3_s`, `servicing_pooling`):

| run | bound T, s | stops in the sample | Q1, s | Q3, s | pooling | file |
|---|---|---|---|---|---|---|
| s10-none | 80 | 436 | 5 | 10 | all robots of all zones of the glob (one run) | `results/fleet/timebudget_s10-none-sb.json` |
| s10c-blind | 80 | 387 | 5 | 10 | all robots of all zones of the glob (one run) | `results/fleet/timebudget_s10c-blind-sb.json` |
| s10-breakdown | 80 | 196 | 5 | 10 | all robots of all zones of the glob (one run) | `results/fleet/timebudget_s10-breakdown-sb.json` |
| s8b-medium-80-p03-07 | 80 | 392 | 5 | 10 | all robots of all zones of the glob (one run) | `results/fleet/timebudget_s8b-medium-80-p03-07-sb.json` |
| closed-loop-sticky | 80 | 377 | 5 | 10 | all robots of all zones of the glob (one run) | `results/fleet/timebudget_closed-loop-sticky-sb.json` |
| MoRoOp, shifts 0-8 | 300, 300, 300, 300, 300, 300, 300, 300, 300 | 823, 789, 820, 802, 814, 821, 780, 835, 778 | 3.0, 6.0, 4.0, 6.0, 6.0, 3.0, 3.7, 2.0, 6.0 | 21.0, 21.0, 20.0, 21.0, 22.0, 21.0, 19.0, 21.0, 21.7 | one bound per shift (a shift is one run: one robot, its own sample); the four servicing_* keys here are lists in shift order, each shift record has its own | `results/fleet/moroop_label-sb.json` |

**Causes per run** (`causes` block; share = cause seconds / the time budget's stuck bucket, the file's `denominator`; `share_total` is the sum of the shares):

| run | cause | cause_label | episodes | episode seconds | share of the stuck bucket |
|---|---|---|---|---|---|
| s10-none | `unknown` | Stopped, cause not identified | 440 | 77,200 | 1.858 |
| s10-none | `traffic` | Traffic wait | 93 | 8,305 | 0.200 |
| s10-none | `blocked_by_stuck` | Blocked by a stuck robot | 55 | 6,440 | 0.155 |
| s10-none | **all** | episode seconds 91,945 / stuck bucket 41,545 s (open episodes not counted: 0) | 588 | 91,945 | 2.21 |
| s10c-blind | `unknown` | Stopped, cause not identified | 404 | 88,115 | 1.696 |
| s10c-blind | `blocked_by_stuck` | Blocked by a stuck robot | 63 | 9,750 | 0.188 |
| s10c-blind | `traffic` | Traffic wait | 79 | 7,310 | 0.141 |
| s10c-blind | `station_overrun` | Station stop over time limit | 1 | 265 | 0.005 |
| s10c-blind | **all** | episode seconds 105,440 / stuck bucket 51,955 s (open episodes not counted: 0) | 547 | 105,440 | 2.03 |
| s10-breakdown | `unknown` | Stopped, cause not identified | 225 | 104,410 | 2.807 |
| s10-breakdown | `faulted_self` | Robot fault | 107 | 26,875 | 0.722 |
| s10-breakdown | `blocked_by_faulted` | Blocked by a faulted robot | 20 | 7,970 | 0.214 |
| s10-breakdown | `blocked_by_stuck` | Blocked by a stuck robot | 8 | 7,105 | 0.191 |
| s10-breakdown | `traffic` | Traffic wait | 21 | 4,315 | 0.116 |
| s10-breakdown | **all** | episode seconds 150,675 / stuck bucket 37,200 s (open episodes not counted: 0) | 381 | 150,675 | 4.05 |
| s8b-medium-80-p03-07 | `unknown` | Stopped, cause not identified | 424 | 84,955 | 1.886 |
| s8b-medium-80-p03-07 | `blocked_by_stuck` | Blocked by a stuck robot | 41 | 7,165 | 0.159 |
| s8b-medium-80-p03-07 | `traffic` | Traffic wait | 69 | 7,100 | 0.158 |
| s8b-medium-80-p03-07 | **all** | episode seconds 99,220 / stuck bucket 45,040 s (open episodes not counted: 0) | 534 | 99,220 | 2.20 |
| closed-loop-sticky | `unknown` | Stopped, cause not identified | 1180 | 430,625 | 2.183 |
| closed-loop-sticky | `blocked_by_stuck` | Blocked by a stuck robot | 121 | 46,115 | 0.234 |
| closed-loop-sticky | `traffic` | Traffic wait | 65 | 18,000 | 0.091 |
| closed-loop-sticky | `station_overrun` | Station stop over time limit | 25 | 5,365 | 0.027 |
| closed-loop-sticky | **all** | episode seconds 500,105 / stuck bucket 197,275 s (open episodes not counted: 0) | 1391 | 500,105 | 2.54 |
| MoRoOp, pooled (radius 1) | `station_overrun` | Station stop over time limit | 4 | 4,250 | 2.397 |
| MoRoOp, pooled (radius 1) | `unknown` | Stopped, cause not identified | 2 | 180 | 0.102 |
| MoRoOp, pooled (radius 1) | **all** | episode seconds 4,430 / stuck bucket 1,773 s (open episodes not counted: 0) | 6 | 4,430 | 2.50 |

**MoRoOp overruns** (`pooled.overruns`; the last two columns from `pooled.false_alarms` by start):

| shift | start | duration, s | station cell | overlaps a TIMEOUT operation | label within 30 s | first cell is a station cell |
|---|---|---|---|---|---|---|
| 1 | 2026-07-27T19:03:16Z | 318 | [9, -3] | yes | no (false alarm) | yes |
| 6 | 2026-07-30T06:16:31Z | 3,245 | [15, -1] | yes | no (false alarm) | no, within radius |
| 7 | 2026-07-31T10:00:24Z | 343 | [15, 0] | yes | no (false alarm) | yes |
| 8 | 2026-07-31T17:43:15Z | 344 | [15, 0] | yes | no (false alarm) | yes |

Station-aware = S13B, the rows of (r); bounded = S14A (PR #51): a SERVICING run still stopped at T after the stop began becomes a stuck episode with cause `station_overrun`. T is set per run from the run's own station stops (`--servicing-max-s auto`). The files come from queue item `wr-s14a-rerun`. It rebuilt each store as `store-sb` with the flag and re-ran costmap, lessons, grade, hotspot_score, baselines, timebudget, deadlock and the MoRoOp analysis on it. Same radius as (r): 0 on the simulator, 1 on MoRoOp (asserted). Unchanged rows are asserted, not eyeballed: `zones`, `truth_kinds`, `grading_counts` and `lesson_persist_chance` of every hotspot file, the S10D `k`, `paired`, `chance` and `lesson_persist` blocks, and the AMOC `amoc` and `by_k` blocks are equal under both rules. In each time budget the bound moves exactly its overrun episodes: stuck seconds rise and waiting_station seconds fall by the `station_overrun` seconds of the `causes` block, the stall list grows by its episode count, and every other bucket is equal (asserted). Stuck seconds moved: s10-none 41,545 to 41,545 s (0 overrun episodes, 0 s); s10c-blind 51,690 to 51,955 s (1 overrun episodes, 265 s); s10-breakdown 37,200 to 37,200 s (0 overrun episodes, 0 s); s8b-medium-80-p03-07 45,040 to 45,040 s (0 overrun episodes, 0 s); closed-loop-sticky 191,910 to 197,275 s (25 overrun episodes, 5,365 s). The bucket split of an overrun episode keeps the time budget's precedence, so its gap and paused seconds stay in `no_data` and `paused`. In MoRoOp shift 6, 2,091 s of `no_data` would be stuck without the 60 s gap rule (`shifts.6.no_data.would_have_been_bucket_without_gap_rule`). The causes shares do not sum to 1, and nothing rescales them. Episode seconds span each whole episode. The stuck bucket is the time budget's per-second split, where shelf-adjacent stops are `waiting_shelf`, faulted seconds are `faulted` and gaps are `no_data`.

**Reading the numbers.**
- **From this section on, the bounded numbers are the headline; (r) and earlier tables keep their rule and say so.**
- **The 1,107 s stop is back (s).** In MoRoOp shift 6 (30 Jul morning), the stuck bucket goes from 7 s under the station-aware rule to 1,107 s under the bound, the old rule's value in (r). `stopped_short` falls from 1,376 s back to 276 s. The stop is now a `station_overrun` episode: "Station stop over time limit", starting 2026-07-30T06:16:31Z at cell [15, -1]. Its first cell is within radius 1 of a station but is not a station cell, it overlaps a TIMEOUT operation, and the robot's label does not cover it, so it counts as a false alarm against the label. The episode lasts 3,245 s. Only 1,100 of those seconds move into the stuck bucket. The rest of the stop stays in `no_data` and `paused` under the time budget's precedence: 2,091 s of shift 6's `no_data` would be stuck without the 60 s gap rule.
- **TIMEOUT overlaps return in part: 1 of 8 under (r), 5 of 8 bounded (s).** All four overruns overlap a TIMEOUT operation. The old rule of (r) overlapped 8 of 8, so 3 are still not overlapped by any stuck run. Which of them were real stops was not inspected.
- **The false alarms stay low (s).** At T = 300 s in all nine shifts, the detector's stuck runs go from 2 to 6 and the unlabelled ones from 1 to 5. Unlabelled stuck runs on a station cell go from 0 to 3, against the Part 4 bar of at most 54. The robot's two labelled episodes of 30 s or more are still both detected. The pooled stuck share goes from 0.005% to 0.675% (13 s to 1,773 s). The old rule of (q) gave 0.42% (1,113 s). The bounded total is higher because the three overruns that start on a station cell (318, 343 and 344 s) were `waiting_station` under every earlier rule, and the bound files them as stuck: pooled `waiting_station` falls from 107,665 s to 107,005 s.
- **The cap binds on MoRoOp, and the fence binds on the simulator (s).** MoRoOp's fence is above 300 s in every shift (Q1 2.0 to 6.0 s, Q3 19.0 to 22.0 s), so T = 300 s, the cap. On all five simulator runs T = 80 s: Q1 5 s and Q3 10 s give 10 x (10/5)^3. The files store it as 80.00000000000011, from the log-space computation. The simulator's 5 s step quantises the dwells, so the bound sits on the step grid.
- **On the simulator only two runs move, and the map does not (s).** Final map, top-20 truth precision, forecast grades, frozen-cell hits, lessons, the S10D verdicts and the AMOC detection are all equal under both rules (asserted). One station stop on the planner-blind run passes 80 s: 1 episode, 265 s, stuck share 25.90% to 26.03%. On the undisturbed, breakdown and s8b runs no stop passes 80 s, and nothing moves.
- **Why the sticky-floor stuck share moved, 32.05% to 32.95% (s).** At T = 80 s, 25 station stops on that run overrun: 5,365 s, which leave `waiting_station` for `stuck`. Stuck seconds go from 191,910 to 197,275 and the stall list from 2,364 to 2,389 episodes; both changes are exactly the 25 overruns (asserted). This is the only simulator run where the bound adds more than one episode. Why its station stops run past 80 s was not inspected.
- **Blocking clusters rise on the same two runs (s):** 49 to 52 on the planner-blind run and 156 to 161 on the sticky floor. The other three runs are unchanged. Why was not inspected (an overrunning robot is now a stuck neighbour, which may close clusters).
- **Causes: "Stopped, cause not identified" is most of every simulator stall list (s).** `unknown` is 440 of 588 counted episodes undisturbed and 1,180 of 1,391 on the sticky floor. On the breakdown run, `faulted_self` is 107 of 381. The labels are the six of Part 4 section 2, verbatim. There is no earlier causes table to compare the `unknown` share with.

**Caveats.**
- **The causes shares do not sum to 1, and nothing rescales them.** The denominator is the time budget's stuck bucket (`causes.denominator`). The numerator is each episode's whole duration, from the detector. On MoRoOp, `episode_seconds` is 4,430 and `stuck_bucket_s` is 1,773, so `share_total` is 2.50. The 3,245 s overrun alone is 1.83 times the stuck bucket, because most of it is `no_data` and `paused` seconds. On the simulator, `share_total` is 2.03 to 4.05, because a stall on a shelf-adjacent cell is `waiting_shelf` in the budget and a fault is `faulted`. Read the share column as "episode time against stuck time", not as a split of the stuck bucket.
- Only the lane-chosen rule was run: one fence (3 IQR), one cap (300 s), one radius per data set. No other T was tried, and T was not tuned on the label.
- The bound reads the whole run before it starts (a first pass over the files), so it is not a streaming rule. A live fleet would need T from earlier shifts.
- The gated forecasts of (l), the CUSUM and short-memory map of (n) and the s8e-long run of (j) were not rerun, as in (r).
- `stopped_short` on MoRoOp shift 6 is back to 276 s, its (q) value. The bucket names are unchanged.
- One seed set (0-9) and one 500-step shift per simulator run, one robot on the real log; no CI on any count in (s). macOS arm64 only (pyastar2d tie-break).

## Sprint 14B: traffic absence against the map and the CUSUM (2026-10-21)

A planner-blind blocked cell sends no stalls once robots route around it; it goes quiet. `docs/LITERATURE.md` Part 3 (What this means, item 1) therefore asked for a retest with a traffic-absence signal. S14B (PR #52) built the test Part 4 section 3 chose, the HERE zero-count rule. It counts robot passes per cell and flags a cell when the gap since its last pass is improbable under the cell's own pass rate (e^(-r gap) < alpha). A cell is eligible after 10 expected passes and is released at its next pass. Alpha defaults to 1e-3, with a sweep over 1e-2, 1e-3 and 1e-4. Part 4 set all of these before the run. The queue item `wr-s14b-amoc-run` ran it on the same 50 planner-blind windows as (k) and (n), against the same undisturbed reference. Everything between this paragraph and "Reading the numbers" is the output of section (t) of `.venv/bin/python scripts/sprint8_tables.py`. Only its heading was demoted one level.

#### (t) Traffic absence against the map and the CUSUM (S14B)

| detector | publish every, s (publishes) | detected / windows | miss share | first detect, s, median (p25-p75) | stale_at_end share | false alarms per zone-hour, s10-none | false alarms per zone-hour, s10c-blind outside windows |
|---|---|---|---|---|---|---|---|
| decayed map K 20 (S10E) | 300 (9) | 6 / 50 | 0.88 | 295 (218.75-438.75) | 0.04 | 177.8 | 175.1 |
| CUSUM (S10I) | 60 (42) | 2 / 50 | 0.96 | 525 (482.5-567.5) | 0.02 | 0.000 | 0.144 |
| traffic absence, alpha 1e-3 (S14B default) | n/a | no AMOC: 0 forecast rows on s10c-blind (store `store-absence`) | n/a | n/a | n/a | not in the file | not in the file |

**Alpha sweep** (`results/fleet/amoc_absence_sweep.json`, one entry per alpha; the AMOC rows by K where the entry has one):

| alpha | K (per zone) | publish every, s (publishes) | detected / windows | miss share | first detect, s, median (p25-p75) | stale_at_end share | false alarms per zone-hour, s10-none | false alarms per zone-hour, s10c-blind outside windows |
|---|---|---|---|---|---|---|---|---|
| 1e-2 | 5 | 60 (42) | 0 / 50 | 1.00 | none | 0.00 | 13.4 | 13.4 |
| 1e-2 | 10 | 60 (42) | 0 / 50 | 1.00 | none | 0.00 | 17.7 | 18.1 |
| 1e-2 | 20 | 60 (42) | 0 / 50 | 1.00 | none | 0.00 | 18.1 | 18.6 |
| 1e-2 | 40 | 60 (42) | 0 / 50 | 1.00 | none | 0.00 | 18.1 | 18.6 |
| 1e-3 | any | n/a | no AMOC: 0 forecast rows on s10c-blind (`store-absence-a1e-3`) | n/a | n/a | n/a | not in the file | not in the file |
| 1e-4 | any | n/a | no AMOC: 0 forecast rows on s10c-blind (`store-absence-a1e-4`) | n/a | n/a | n/a | not in the file | not in the file |

Same measured run (`fleet/data/s10c-blind`, 50 planner-blind blocked windows) and reference (`fleet/data/s10-none`, undisturbed) for every row with an AMOC, and the same store hashes before and after (asserted). The absence detector (`fleet/absencemap.py`, PR #52) publishes into its own store copy. `time_to_detect` refuses a measured store with no forecast rows, so for an alpha that flags nothing the queue item `wr-s14b-amoc-run` writes a stub (`detector`, `store_suffix`, `measured_forecast_rows`, `amoc` null). The stub records the measured run only, so the reference false-alarm count is not in the file. Cadence differs: the decayed map publishes every 300 s and the CUSUM and absence detectors every 60 s. False alarms are flag-publishes per zone per simulated hour, so they scale with the publish rate. Reference false alarms at K 20 by zone: alpha 1e-2: zone 4 118.1 per zone-hour, 5 of 10 zones at 0. Column definitions are those of (k). Sources: `results/fleet/amoc_blind.json`, `results/fleet/amoc_fast.json`, `results/fleet/amoc_absence.json`, `results/fleet/amoc_absence_sweep.json`.

**Reading the numbers.**
- **Verdict (t): the absence test detects no blockage while it is open, at any alpha of the sweep.** At the default alpha 1e-3, and at 1e-4, it flags nothing on the planner-blind run. There are 0 forecast rows, so there is no AMOC to draw. At alpha 1e-2 it detects 0 of 50 windows at every K. On the same windows the decayed map detects 6 of 50 at K 20 and the CUSUM 2 of 50.
- **What it does flag at 1e-2 is not the blockage (t).** At K 20 it raises 18.1 false alarms per zone-hour on the undisturbed run and 18.6 on the planner-blind run outside the windows. The rate is the same with and without blockages. Zone 4 runs at 118.1 per zone-hour on its own, about two thirds of the reference's flags, and 5 of the 10 zones raise none.
- **Part 4's bar is not reached, so its negative holds.** The bar was at least 5 windows detected that the reference detector misses, and none the other way. The reference was the CUSUM at no more than 1 false alarm per zone-hour, or the map at less than 177.8. No alpha detects a single window.
- **Why, in plain terms:** at this fleet density a cell sees too few passes in one 2,495 s run. Few cells collect the 10 passes the test needs before it may flag. A 300 to 1,200 s blockage then ends before the gap gets long enough to be improbable. `docs/LITERATURE.md` Part 4 section 4 predicted this from the pass counts before the build. The S14B lane report has the eligible-cell count (`reports/wr-lane-s14b-traffic-absence.md`).

**Caveats.**
- The same seed set (0-9), one 500-step shift and one map as (k) and (n); no count in (t) has a CI.
- Alpha was not picked in-sample. The default (1e-3) and the sweep were set in `docs/LITERATURE.md` Part 4 before the run, and no alpha was chosen from these results.
- The stub documents for 1e-3 and 1e-4 record the measured run only. That nothing was flagged on the undisturbed reference at those alphas is in the S14B lane report, not in a results file.
- The decayed map publishes every 300 s, the CUSUM and the absence test every 60 s. False alarms per zone-hour count flag-publishes, and an absence flag stays up until the next pass, so one flag can count at many publishes.
- Built without HERE's time-of-day model, labelled threshold and hysteresis, and without Pan et al.'s detour count (no planned route in the stream, and no history in one run). The lane report lists the deviations.
- macOS arm64 only (pyastar2d tie-break).

## Sprint 14C: an eight-hour shift (2026-10-21)

Every planner-blind blockage run so far, (h) to (t), was a 500-step shift, about 42 minutes. A real shift is 8 hours, and `docs/LITERATURE.md` Part 4 section 3 said the absence test needs traffic history that one short run cannot give. The queue item `wr-s14c-8h-run` emitted the planner-blind blockage run and the undisturbed reference at 10 zones x 5,760 steps (8 simulated hours per zone), seed base 100. The S10I tuning used seeds 0-9 and these seeds are not among them. It then ran the map, the CUSUM and the absence test (alpha 1e-3) with the settings of (t). Everything between this paragraph and "Reading the numbers" is the output of section (u) of `.venv/bin/python scripts/sprint8_tables.py`. Only its heading was demoted one level.

#### (u) Eight-hour shift: map, CUSUM and absence on the blind blockage (S14C)

| detector | shift | publish every, s (publishes) | detected / windows | miss share | first detect, s, median (p25-p75) | stale_at_end share | false alarms per zone-hour, undisturbed reference | false alarms per zone-hour, blind run outside windows | file |
|---|---|---|---|---|---|---|---|---|---|
| decayed map K 20 (S10E) | 500 steps (S14B) | 300 (9) | 6 / 50 | 0.88 | 295 (218.75-438.75) | 0.04 | 177.8 | 175.1 | `results/fleet/amoc_blind.json` |
| decayed map K 20 (S10E) | 8 hours (S14C) | 300 (96) | 31 / 661 | 0.95 | 170 (107.5-260) | 0.00 | 199.4 | 216.5 | `results/fleet/amoc_blind-8h.json` |
| CUSUM (S10I) | 500 steps (S14B) | 60 (42) | 2 / 50 | 0.96 | 525 (482.5-567.5) | 0.02 | 0.000 | 0.144 | `results/fleet/amoc_fast.json` |
| CUSUM (S10I) | 8 hours (S14C) | n/a | flagged nothing: 0 forecast rows on s10c-blind-8h, 0 / 661 | 1.00 | none | n/a | not in the file | not in the file | `results/fleet/amoc_fast-8h.json` |
| traffic absence, alpha 1e-3 (S14B) | 500 steps (S14B) | n/a | flagged nothing: 0 forecast rows on s10c-blind, 0 / 50 | 1.00 | none | n/a | not in the file | not in the file | `results/fleet/amoc_absence.json` |
| traffic absence, alpha 1e-3 (S14B) | 8 hours (S14C) | 60 (480) | 11 / 661 | 0.98 | 55 (30-485) | 0.00 | 341.2 | 236.6 | `results/fleet/amoc_absence-8h.json` |

500-step rows: `fleet/data/s10c-blind` (50 planner-blind blocked windows, 0.69 simulated hours per zone) against `fleet/data/s10-none`, the same rows as (t). 8-hour rows: `fleet/data/s10c-blind-8h` (661 windows, median 152 steps, 8 simulated hours per zone, 10 zones x 5,760 steps) against `fleet/data/s10-none-8h`. Every live row of a shift has the same runs, windows and store hashes before and after as that shift's map row (asserted). The detectors, their defaults and the disturbance ({"blocked_cell": {"rate_per_hour": 8.0, "duration": [60, 240], "known": false}}) are those of (t); only the shift length and the seeds changed. K is 20 per zone for every live row. A stub (`amoc` null) means the detector wrote no forecast row on the blind run, so it detects 0 windows; it records the blind run only, so its reference false alarms are not in the file. Column definitions are those of (k). Reference false alarms per zone-hour at K 20 on the 8-hour run, by zone: decayed map: zone 0 61.8, zone 1 62.2, zone 2 232.4, zone 3 233.8, zone 4 233.0, zone 5 233.2, zone 6 235.6, zone 7 233.6, zone 8 233.6, zone 9 234.8; traffic absence: zone 0 881.2, zone 1 915.8, zone 2 235.0, zone 3 219.0, zone 4 97.8, zone 5 288.5, zone 6 106.6, zone 7 209.5, zone 8 208.5, zone 9 250.4.

Window overlap on the 8-hour run at K 20 (`by_k.20.windows`): the absence test detects 11 windows the decayed map misses, the map 31 that the absence test misses, both 0. Absence hits by zone: zone 1 5, zone 2 1, zone 5 1, zone 6 2, zone 7 1, zone 9 1.
Map rows of the K sweep that detect at least as many windows as the absence test at K 20 (11) at no more reference false alarms (341.2): K 10 17 / 661 at 102.2; K 20 31 / 661 at 199.4 (`results/fleet/amoc_blind-8h.json` `amoc.k`).
Against the CUSUM, which detects none: 11 windows to 0, one-sided exact sign test p = 0.5^11 = 0.00049.

**Reading the numbers.**
- **Verdict (u): with 8 hours of history, none of the three catches a useful share of the hidden blockages, so the hidden-blockage line is closed on three signals: stall map, stall CUSUM and traffic absence.** The best is the map at 31 of 661 windows (4.7%) for 199.4 false alarms per zone-hour. History changed one detector, the absence test, which now flags. Its flags do not follow the blockages.
- **Absence test (u): it went from flagging nothing to 11 of 661 windows, at more false alarms than the map.** It catches 1.7% of windows at K 20, with 341.2 false alarms per zone-hour on the undisturbed reference. It raises fewer false alarms on the blind run outside windows (236.6) than on the undisturbed run, so blockages do not raise its rate. The map at K 10 detects more (17) at fewer false alarms (102.2). Zones 0 and 1 give 881.2 and 915.8 per zone-hour on the reference on their own, and 5 of the 11 hits are in zone 1.
- **Part 4's bar, read to the letter, passes against the CUSUM and fails against the map.** The bar (`docs/LITERATURE.md` Part 4, S14B rule) asks for at least 5 windows detected that the reference misses and none the other way, with a one-sided exact sign test. The reference is the CUSUM at no more than 1 false alarm per zone-hour, or the map at less than 177.8.
  - Against the map: the absence test has 11 the map misses, the map 31 the absence test misses, and they share none. This branch fails. The map at K 20 sits at 199.4, above the 177.8 it was set at.
  - Against the CUSUM: the CUSUM detects nothing on this run, so 11 to 0, p = 0.00049. This branch passes on windows.
  - The bar sets the reference's false-alarm budget but not the candidate's. The absence test passes the CUSUM branch at 341.2 false alarms per zone-hour, against the CUSUM's 0 forecast rows on the blind run. A detector that flags hundreds of cells an hour will beat one that flags nothing. This docs job therefore reads the CUSUM branch as no evidence of early warning. The bar was also written for the 50 windows of the 500-step run, not this run. **Whether the CUSUM branch counts is the operator's call.**
- **Map (u): 31 of 661 (4.7%) at K 20, against 6 of 50 (12%) on the 500-step run.** False alarms are 199.4 per zone-hour on the reference and 216.5 outside windows, against 177.8 and 175.1. The seeds differ (see caveats), so this is no evidence that longer history helps or hurts the map.
- **CUSUM (u): it flagged nothing in 8 hours on seeds 100-109.** It wrote 0 forecast rows on the blind run, where the 500-step run on seeds 0-9 gave 2 of 50. Its defaults come from S10I, so this is held-out.

**Caveats.**
- Seed base 100 is a different seed set from every earlier table, so the 500-step and 8-hour rows are not paired. A change between them mixes shift length with seeds.
- One map, one run per shift length; no count in (u) has a CI.
- `results/fleet/amoc_absence-8h.json` was recomputed in the S14C docs job (commit 69b0378). The queue item wrote a stub for it, but its guard grep could not match the escaped quotes in `decisions.jsonl`, and the store held absence forecast rows; the counts are in that commit's message. The CUSUM stub is real: no `cusum` forecast row exists in either 8-hour store. The S14B stubs for 1e-3 and 1e-4 were checked the same way and hold (0 absence rows).
- Zones 0 and 1 run far slower than the other eight (pick-rate in the `wr-s14c-8h-run` log, not in a results file). Both detectors behave differently there: the map raises a quarter of its usual false alarms and the absence test about four times as many.
- False alarms count flag-publishes per zone per simulated hour. The map publishes every 300 s and the CUSUM and absence test every 60 s, as in (t).
- macOS arm64 only (pyastar2d tie-break).

## Sprint 14D: "blocked by" only when the neighbour is on the route (2026-10-21)

S14A gave every neighbour stop a label that names the neighbour as the cause, for example "Blocked by a stuck robot", whenever a stuck or broken robot stood on any adjacent cell. `docs/LITERATURE.md` Part 5 section 2 said that adjacency does not show blocking, and Part 6 row 6 named the cheapest directional fact the stream carries: the robot's next route node. S14D (PR #54) keeps the cause keys and their precedence. Within the chosen cause, the robot standing on the stopped robot's next node is the blocker, and only then is the label "Blocked by ..." (or "Traffic wait"). Otherwise, or when the message reports no route, it is "Stopped next to ...". The labels are the operator's strings from the S14D brief, not Part 5's draft (lane report `reports/wr-lane-s14d-cause-route.md`, "Deviation from Part 5"). The queue item `wr-s14d-rerun` re-ingested the five simulator runs and MoRoOp into `-sd` files (results commit 2c9cd68). Everything between this paragraph and "Reading the numbers" is the output of section (v) of `.venv/bin/python scripts/sprint8_tables.py`. Only its heading was demoted one level.

#### (v) Stop causes split by the next route node (S14D): S14A label / S14D label

| run | cause | S14A label (`-sb`) | episodes | seconds | S14D label (`-sd`) | episodes | seconds | on route | files |
|---|---|---|---|---|---|---|---|---|---|
| s10-none | `unknown` | Stopped, cause not identified | 440 | 77,200 | Stopped, cause not identified | 440 | 77,200 | n/a | `results/fleet/timebudget_s10-none-sb.json`, `results/fleet/timebudget_s10-none-sd.json` |
| s10-none | `traffic` | Traffic wait | 93 | 8,305 | Stopped next to another robot | 81 | 7,445 | no or unknown | `results/fleet/timebudget_s10-none-sb.json`, `results/fleet/timebudget_s10-none-sd.json` |
| s10-none | | | | | Traffic wait | 12 | 860 | yes | `results/fleet/timebudget_s10-none-sb.json`, `results/fleet/timebudget_s10-none-sd.json` |
| s10-none | `blocked_by_stuck` | Blocked by a stuck robot | 55 | 6,440 | Stopped next to a stuck robot | 22 | 3,990 | no or unknown | `results/fleet/timebudget_s10-none-sb.json`, `results/fleet/timebudget_s10-none-sd.json` |
| s10-none | | | | | Blocked by a stuck robot | 33 | 2,450 | yes | `results/fleet/timebudget_s10-none-sb.json`, `results/fleet/timebudget_s10-none-sd.json` |
| s10c-blind | `unknown` | Stopped, cause not identified | 404 | 88,115 | Stopped, cause not identified | 404 | 88,115 | n/a | `results/fleet/timebudget_s10c-blind-sb.json`, `results/fleet/timebudget_s10c-blind-sd.json` |
| s10c-blind | `blocked_by_stuck` | Blocked by a stuck robot | 63 | 9,750 | Stopped next to a stuck robot | 28 | 7,180 | no or unknown | `results/fleet/timebudget_s10c-blind-sb.json`, `results/fleet/timebudget_s10c-blind-sd.json` |
| s10c-blind | | | | | Blocked by a stuck robot | 35 | 2,570 | yes | `results/fleet/timebudget_s10c-blind-sb.json`, `results/fleet/timebudget_s10c-blind-sd.json` |
| s10c-blind | `traffic` | Traffic wait | 79 | 7,310 | Stopped next to another robot | 70 | 6,665 | no or unknown | `results/fleet/timebudget_s10c-blind-sb.json`, `results/fleet/timebudget_s10c-blind-sd.json` |
| s10c-blind | | | | | Traffic wait | 9 | 645 | yes | `results/fleet/timebudget_s10c-blind-sb.json`, `results/fleet/timebudget_s10c-blind-sd.json` |
| s10c-blind | `station_overrun` | Station stop over time limit | 1 | 265 | Station stop over time limit | 1 | 265 | n/a | `results/fleet/timebudget_s10c-blind-sb.json`, `results/fleet/timebudget_s10c-blind-sd.json` |
| s10-breakdown | `unknown` | Stopped, cause not identified | 225 | 104,410 | Stopped, cause not identified | 225 | 104,410 | n/a | `results/fleet/timebudget_s10-breakdown-sb.json`, `results/fleet/timebudget_s10-breakdown-sd.json` |
| s10-breakdown | `faulted_self` | Robot fault | 107 | 26,875 | Robot error, cannot continue order | 107 | 26,875 | n/a | `results/fleet/timebudget_s10-breakdown-sb.json`, `results/fleet/timebudget_s10-breakdown-sd.json` |
| s10-breakdown | `blocked_by_faulted` | Blocked by a faulted robot | 20 | 7,970 | Stopped next to a broken robot | 19 | 7,895 | no or unknown | `results/fleet/timebudget_s10-breakdown-sb.json`, `results/fleet/timebudget_s10-breakdown-sd.json` |
| s10-breakdown | | | | | Blocked by a broken robot | 1 | 75 | yes | `results/fleet/timebudget_s10-breakdown-sb.json`, `results/fleet/timebudget_s10-breakdown-sd.json` |
| s10-breakdown | `blocked_by_stuck` | Blocked by a stuck robot | 8 | 7,105 | Stopped next to a stuck robot | 8 | 7,105 | no or unknown | `results/fleet/timebudget_s10-breakdown-sb.json`, `results/fleet/timebudget_s10-breakdown-sd.json` |
| s10-breakdown | `traffic` | Traffic wait | 21 | 4,315 | Stopped next to another robot | 18 | 4,090 | no or unknown | `results/fleet/timebudget_s10-breakdown-sb.json`, `results/fleet/timebudget_s10-breakdown-sd.json` |
| s10-breakdown | | | | | Traffic wait | 3 | 225 | yes | `results/fleet/timebudget_s10-breakdown-sb.json`, `results/fleet/timebudget_s10-breakdown-sd.json` |
| s8b-medium-80-p03-07 | `unknown` | Stopped, cause not identified | 424 | 84,955 | Stopped, cause not identified | 424 | 84,955 | n/a | `results/fleet/timebudget_s8b-medium-80-p03-07-sb.json`, `results/fleet/timebudget_s8b-medium-80-p03-07-sd.json` |
| s8b-medium-80-p03-07 | `blocked_by_stuck` | Blocked by a stuck robot | 41 | 7,165 | Stopped next to a stuck robot | 39 | 7,040 | no or unknown | `results/fleet/timebudget_s8b-medium-80-p03-07-sb.json`, `results/fleet/timebudget_s8b-medium-80-p03-07-sd.json` |
| s8b-medium-80-p03-07 | | | | | Blocked by a stuck robot | 2 | 125 | yes | `results/fleet/timebudget_s8b-medium-80-p03-07-sb.json`, `results/fleet/timebudget_s8b-medium-80-p03-07-sd.json` |
| s8b-medium-80-p03-07 | `traffic` | Traffic wait | 69 | 7,100 | Stopped next to another robot | 62 | 6,565 | no or unknown | `results/fleet/timebudget_s8b-medium-80-p03-07-sb.json`, `results/fleet/timebudget_s8b-medium-80-p03-07-sd.json` |
| s8b-medium-80-p03-07 | | | | | Traffic wait | 7 | 535 | yes | `results/fleet/timebudget_s8b-medium-80-p03-07-sb.json`, `results/fleet/timebudget_s8b-medium-80-p03-07-sd.json` |
| closed-loop-sticky | `unknown` | Stopped, cause not identified | 1180 | 430,625 | Stopped, cause not identified | 1180 | 430,625 | n/a | `results/fleet/timebudget_closed-loop-sticky-sb.json`, `results/fleet/timebudget_closed-loop-sticky-sd.json` |
| closed-loop-sticky | `blocked_by_stuck` | Blocked by a stuck robot | 121 | 46,115 | Stopped next to a stuck robot | 113 | 45,560 | no or unknown | `results/fleet/timebudget_closed-loop-sticky-sb.json`, `results/fleet/timebudget_closed-loop-sticky-sd.json` |
| closed-loop-sticky | | | | | Blocked by a stuck robot | 8 | 555 | yes | `results/fleet/timebudget_closed-loop-sticky-sb.json`, `results/fleet/timebudget_closed-loop-sticky-sd.json` |
| closed-loop-sticky | `traffic` | Traffic wait | 65 | 18,000 | Stopped next to another robot | 56 | 16,370 | no or unknown | `results/fleet/timebudget_closed-loop-sticky-sb.json`, `results/fleet/timebudget_closed-loop-sticky-sd.json` |
| closed-loop-sticky | | | | | Traffic wait | 9 | 1,630 | yes | `results/fleet/timebudget_closed-loop-sticky-sb.json`, `results/fleet/timebudget_closed-loop-sticky-sd.json` |
| closed-loop-sticky | `station_overrun` | Station stop over time limit | 25 | 5,365 | Station stop over time limit | 25 | 5,365 | n/a | `results/fleet/timebudget_closed-loop-sticky-sb.json`, `results/fleet/timebudget_closed-loop-sticky-sd.json` |
| MoRoOp, pooled (radius 1) | `station_overrun`, `unknown` | no route nodes in the log, every blocker_on_route null (asserted by the `wr-s14d-rerun` queue item over every episode); no neighbour cause in the table, and the causes block equals the S14A one (asserted) | | | | | n/a | `results/fleet/moroop_label-sb.json`, `results/fleet/moroop_label-sd.json` |

**On-route share per run** (neighbour causes = `blocked_by_faulted`, `blocked_by_stuck`, `traffic`; on route = the S14D label is the route label of `ROUTE_LABELS` in `fleet/fleet_analyser/detector.py`):

| run | on-route / all neighbour episodes | share | on-route / all neighbour seconds | share | "Blocked by" / old "Blocked by" episodes (blocked_by_* only) |
|---|---|---|---|---|---|
| s10-none | 45 / 148 | 30.4% | 3,310 / 14,745 | 22.4% | 33 / 55 |
| s10c-blind | 44 / 142 | 31.0% | 3,215 / 17,060 | 18.8% | 35 / 63 |
| s10-breakdown | 4 / 49 | 8.2% | 300 / 19,390 | 1.5% | 1 / 28 |
| s8b-medium-80-p03-07 | 9 / 110 | 8.2% | 660 / 14,265 | 4.6% | 2 / 41 |
| closed-loop-sticky | 17 / 186 | 9.1% | 2,185 / 64,115 | 3.4% | 8 / 121 |

S14A = the bounded rule of (s), files `-sb`; S14D (PR #54) = the same rule with each neighbour cause split by the robot's next route node, files `-sd` from queue item `wr-s14d-rerun`, which re-ingested every store as `store-sd`. A neighbour cause takes its route label ("Blocked by a broken robot", "Blocked by a stuck robot", "Traffic wait") only when the chosen blocker stands on the node the stopped robot reports next; otherwise, or when the message reports no route, it takes the "Stopped next to" label. The rerun moves labels only: per run the causes header (`episode_seconds`, `stuck_bucket_s`, `share_total`), every time budget bucket, and each cause key's episode and second sums equal the S14A file (asserted). "Traffic wait" is the S14A label of every traffic stop and the S14D label of on-route traffic only.

**Reading the numbers.**
- **Most old neighbour causes do not survive the route test (v).** Counting all three neighbour causes, the on-route label holds for 45 of 148 episodes undisturbed (30.4%), 44 of 142 on the planner-blind run (31.0%), 4 of 49 on the breakdown run (8.2%), 9 of 110 on the s8b floor run (8.2%) and 17 of 186 on the sticky floor (9.1%). By seconds the share is lower on every run (1.5% to 22.4%): on-route stops are shorter on average.
- **"Blocked by" itself (v).** Of the S14A "Blocked by a stuck / faulted robot" episodes, 33 of 55 keep a "Blocked by" label undisturbed, 35 of 63 on the planner-blind run, 1 of 28 on the breakdown run, 2 of 41 on the s8b run and 8 of 121 on the sticky floor. On the breakdown run, 1 of 20 "Blocked by a faulted robot" stops has the broken robot on its next node (75 s of 7,970).
- **Nothing else moved (v).** The rerun changes labels only. Per run, the stuck bucket, every time-budget bucket, the causes header and each cause key's episode and second sums equal the S14A files (asserted). `unknown` is still most of every simulator stall list, as in (s).
- **MoRoOp: no change (v).** The log has no route nodes, so every `blocker_on_route` is null (the queue item's assertion: True 0, False 0). The pooled table has no neighbour cause at all, only `station_overrun` and `unknown`, so the split could not show there for two reasons.

**Caveats.**
- **"Stopped next to" mixes two cases, and the results files cannot separate them.** It is the label both when the neighbour is off the route and when the stopped robot reports no route (`nodeStates` absent or `[]`). The lane report's check on s10-none zone 0 found 5 of its 11 traffic stops with `nodeStates []`. So the on-route shares are a floor on how often the neighbour stands on the route. They are not evidence that the rest stood beside it.
- **On route is geometry, not proof of blocking.** Part 6 row 6 calls the next-node test "a directional geometry fact, still not Part 5 §2's 'blocked by'". A planner log would prove it. The operator chose "Blocked by" for this case, and the client text overstates it by that much (lane report).
- **"Traffic wait" changed meaning.** In (s) it labels every traffic stop; in (v) only the on-route ones. Compare (s) and (v) by cause key, not by label.
- The README text and the pages before this section still carry the S14A strings ("Robot fault", "Blocked by a faulted robot"); renaming them is not done here.
- The on-route choice can change which robot is named as the blocker on routed streams. Its effect on grades and lessons was not measured (lane report, review).
- One seed set (0-9) and one 500-step shift per simulator run; no count in (v) has a CI. macOS arm64 only (pyastar2d tie-break).

## Sprint 14E: grading time (2026-10-21)

S14E (PR #53) made the in-memory store keep its indices current on update (a per-row sequence number and bisect re-insertion) instead of dropping them. Grading had become the slow step on long runs. Lane report `reports/wr-lane-s14e-store-index.md`, measured on this laptop: `grade --once --truth` on the stripped 500-step planner-blind store went from 1.73-1.86 s with the old store to 0.17 s, with `decisions.jsonl` and `forecast_grades.jsonl` byte-identical to the old store's. On the 8-hour planner-blind store (`fleet/data/s10c-blind-8h`, 10 zones x 5,760 steps) the new code grades in 4.4 s and 4.7 s (two runs). The old code was not run on that store. The only "before" is about 50 minutes read off file mtimes, and it covers lessons and grade together, so it is not a like-for-like speedup. Loading the graded 8-hour `decisions.jsonl` takes 0.5 s; the old load was stopped unfinished at 15 minutes. The tests that pin it are in `fleet/tests/test_fleet_store_index.py`: `TestGradeOnData.test_grade_byte_identity_500step` (byte identity) and `TestGradeOnData.test_grade_8h_timing` (the 8-hour grade under a 120 s limit). Both skip when that store is absent under `WR_S10_DATA`; the S14E gate ran them (ok, not skipped).

## Sprint 15: the two page figures against the vendor-documented methods (2026-10-23)

The page leads with two figures that `docs/COMPETITION.md` pass 4 found no readable vendor shipping as a default: a stall list that leaves out station stops (InOrbit has it only as a rule a customer writes, scored present), and a blocking number per zone (not documented by any readable vendor). Sprint 15 measured each against the method a vendor does document, on data already on disk. `docs/LITERATURE.md` Part 8 named the methods and set the refute lines before either run. S15A (PR #56) added `fleet/stall_baseline.py`. It runs InOrbit's two documented stillness rules and the plain driving-flag timer next to our station-aware, bounded rule, on the same stream: N0-30 and N0-60 are the detector with no station logic at 30 s and 60 s; N1 is InOrbit `unableToNavigate`; N2-W is InOrbit "stopped while on a mission" at W = 30, 60, 120 and 180 s, where 180 s is the documented value. S15B (PR #55) added `fleet/duration_spread.py`. It computes OTTO's figure (mean job duration) and the TTTR spread (p95 / median job duration) per zone and ranks the zones against the blocking number (`blocked_s_per_robot_hour` of the `-sb` deadlock file) and against truth stuck time. The queue items `wr-s15a-run` and `wr-s15b-run` wrote `results/fleet/stall_baseline.json` and `results/fleet/duration_spread.json`, committed with this section. The tables below are not printed by `scripts/sprint8_tables.py`, which has no section (w); adding one is code and goes through a lane. They were printed by a read-only script over the two files, and its text is in `reports/wr-dev-s15-readme.md`.

#### (w1) S15A: the station-aware rule against the naive stall rules on MoRoOp (9 shifts, one robot, 2 labelled stops of 30 s or more)

| rule | stuck runs | labelled hits (of 2) | misses | false alarms | of them on a station cell | alerts spanning a > 60 s gap | alert latency, label 1 / label 2 (s) | 2/2 with <= 12 runs |
|---|---|---|---|---|---|---|---|---|
| N0-30 | 567 | 2 | 0 | 544 | 542 | n/a | 98 / 132 | no |
| N0-60 | 10 | 2 | 0 | 6 | 5 | n/a | 98 / 132 | yes |
| N1 | 1 | 0 | 2 | 1 | 0 | 1 | miss / miss | no |
| N2-30 | 4,033 | 2 | 0 | 3,946 | 3,923 | 156 | -293 / 24 | no |
| N2-60 | 818 | 2 | 0 | 783 | 782 | 157 | -263 / 54 | no |
| N2-120 | 55 | 2 | 0 | 52 | 51 | 53 | -203 / 114 | no |
| N2-180 | 7 | 1 | 1 | 5 | 4 | 5 | -143 / miss | no |
| ours | 6 | 2 | 0 | 5 | 3 | n/a | 413 / 132 | reference |

Alert latency = the rule's first alert overlapping the label minus the start of the stopped run (the `driving`-false run) under it. A negative latency means the position rule fired before the stopped run began: the 2 m box was still before the driving flag went false. "n/a" = not a position rule, so the gap count does not apply. The line column applies the Part 8 refute line; "ours" is the rule under test, not a candidate.

#### (w2) S15B: job-duration statistics against the blocking number and truth, per zone (5 simulator runs)

| run | zones | completed jobs | ρ(p95/median, blocking) | top-3 | ρ(mean, blocking) | top-3 | ρ(p95/median, truth) | ρ(mean, truth) | ρ(blocking, truth) | blocking beats both on truth |
|---|---|---|---|---|---|---|---|---|---|---|
| closed-loop-sticky | 30 | 696 | 0.13 | 0/3 | 0.06 | 0/3 | 0.12 | 0.06 | 0.04 | no |
| s10-breakdown | 10 | 402 | -0.27 | 1/3 | -0.12 | 1/3 | 0.04 | -0.16 | -0.01 | no |
| s10-none | 10 | 1,070 | 0.27 | 1/3 | 0.14 | 1/3 | -0.35 | -0.87 | 0.00 | yes |
| s10c-blind | 10 | 925 | 0.58 | 2/3 | 0.30 | 2/3 | 0.09 | -0.27 | 0.48 | yes |
| s8b-medium-80-p03-07 | 10 | 910 | -0.16 | 0/3 | -0.12 | 1/3 | -0.32 | -0.67 | 0.20 | yes |
| median over 5 runs | | | 0.13 | 0.33 | 0.06 | 0.33 | 0.04 | -0.27 | 0.04 | 3 of 5 |

ρ = Spearman over the zones of one run. "Truth" = truth stuck seconds per robot-hour by `fleet_analyser/score.py`'s definition (episodes of 30 s or more). Top-3 = how many of the statistic's top 3 zones are also in the blocking number's top 3 (chance 0.9 of 3 at 10 zones, 0.3 at 30). The median row's top-3 entries are fractions of 3. "Blocking beats both" means ρ(blocking, truth) is strictly above both statistics' ρ with truth.

**Reading the numbers.**
- **S15A refute line: commodity (w1).** Part 8 section 3: "Commodity if any N2-W, N1 or N0-60 on MoRoOp reaches 2/2 labelled hits with ≤ 12 stuck runs (2× our 6)." N0-60 reaches 2/2 hits with 10 stuck runs. Ours reaches 2/2 with 6 stuck runs and 5 false alarms; N0-60 raises 6 false alarms. On this log, a plain 60 s timer on the driving flag does what the station filter does, one false alarm apart.
- **The rule that meets the line is not a vendor-documented form (w1).** N0-60 is the driving-flag timer at 60 s. InOrbit's two documented position rules do not meet the line. N2-180, the documented "stopped while on a mission", hits 1 of 2 with 7 stuck runs. N1 (`unableToNavigate`) hits neither and raises 1 alert in nine shifts. N2-120 hits both at 55 runs, and the shorter windows raise 818 and 4,033. So the page may not say the station filter beats a naive rule. It may say that InOrbit's documented example misses one of the two labelled stops at a similar alarm count (7 runs against our 6). Part 8 allows "not in the documented example", never "a vendor can't".
- **The station filter's own gain is real against the 30 s rule (w1):** 567 stuck runs to 6, and false alarms on a station cell 542 to 3. That is the S13B/S14A result, now from the same script as the baselines. Most of the gain comes from the longer threshold, not from station logic: N0-60 has 5 false alarms on a station cell.
- **Ours alerts later on the first labelled stop (w1).** Its alert comes 413 s after the stop began, against 98 s for N0-30 and N0-60. That is the same alert time as for label 2, and it comes after label 1 had ended (label 1 starts 12 s after the stopped run and lasts 250 s). Why the first stopped run (262 s) raised no alert of its own under ours was not inspected.
- **On the simulator, ours keeps recall where N0-60 loses it (secondary, not part of the line).** Summed over `sim.<run>.zones` of `stall_baseline.json`, ours matches 58/63 (breakdown), 113/126 (undisturbed), 127/135 (planner-blind), 92/98 (s8b) and 126/129 (sticky floor) truth episodes. N0-60 matches 46/63, 77/126, 83/135, 46/98 and 109/129. Truth keeps episodes of 30 s or more, which favours a 30 s rule by construction. Pooled precision (matched over scored detections) is ours 0.17, 0.17, 0.20, 0.14, 0.05 and N0-60 0.16, 0.14, 0.16, 0.10, 0.06: on the sticky floor N0-60's is the higher. N1 and N2-W read 2 m as 2 cells there ("scale assumed, 1 cell = 1 m" in the file). N1 matches no truth episode on any run, and N2-180 matches 0 to 8.
- **S15B refute line: mixed (w2),** as `verdict.verdict` in the file reads. Neither commodity branch holds. The median ρ with the blocking number is 0.13 (p95 / median) and 0.06 (mean), not ≥ 0.7, with median top-3 overlap 0.33. A statistic matched or beat the blocking number on truth in 2 runs (p95 / median) and 1 run (mean), not 3. The supports line fails on its second condition. Both medians are below 0.4, but the blocking number beats both statistics on truth in 3 of 5 runs, not 4.
- **The blocking number does not track truth stuck time either (w2).** Its median ρ with truth is 0.04 (per run -0.01 to 0.48). No run reaches the p < 0.05 line (about 0.65 at 10 zones, 0.36 at 30). Two of its three "beats" come from statistics with negative ρ against truth (mean job duration -0.87 undisturbed, -0.67 on s8b), while the blocking number sits near zero there (0.00, 0.20). The planner-blind run is the only one where the blocking number ranks the zones somewhat like truth (ρ 0.48, a real beat over 0.09 and -0.27). So S15B does not show that OTTO's figure is a weaker blocking measure than ours. It shows that neither ranks zones by stuck time on these runs. The blocking number counts robots blocked by each other, and truth counts every stuck second, so they need not agree. Even so, the blocking figure has no validation against truth on record.
- **Reroutes do not end jobs here (w2).** `ended_to_new_order` is 0 on all five runs, and every completed job ended to idle. The S15B lane report's check before reading a low ρ as "spread misses blocking" is answered: reroutes do not shorten the jobs. Why mean job duration ranks against truth on the undisturbed and s8b runs was not inspected.

**Caveats.**
- **Two labelled stops, one shift, one robot (w1).** "2/2" is the whole positive sample, and both are in shift 7, 274 s apart (stopped runs of 262 s and 133 s). The ≤ 12 threshold is ours, set in Part 8 before the run, and one false alarm separates N0-60 from ours.
- **The S15A line was read on the lane's dev run before the queue run.** The queue run reproduces the same counts. It is still one deterministic computation on one log, not a replication.
- **Rule thresholds:** N0-60 and the N2 windows other than 180 s are our variations of editable vendor examples, not shipped defaults (Part 8 Verdict 1). N1 and N2 on MoRoOp use 0.5 m cells, so 2 m quantises to within one cell.
- **S15B is per run at 10 zones (one run at 30), so every ρ is coarse.** The supports and commodity thresholds are ours (Part 8 section 3). Jobs read AGVs only, while truth and the blocking denominator include pickers (deviations 1-4 in the file).
- **Both results files record absolute local paths** (`src.moroop_dir` in `stall_baseline.json`, `runs.*.deadlock.path` in `duration_spread.json`). Scrub them before any public copy.
- One seed set (0-9) and one 500-step shift per simulator run, no CI on any count or ρ. macOS arm64 only (pyastar2d tie-break).

## Sprint 16: the real log's own labels: diagnostics, dispatcher events, the authors' cleaning (2026-10-23)

Sprints 13 to 15 left three of the MoRoOp log's own records unread: the robot's ROS diagnostics, the lab dispatcher's event table, and the rows the dataset's authors removed before publishing. `docs/LITERATURE.md` Part 9 set what each may be called and the refute lines before either run. S16A (PR #57) added `fleet/adapters/moroop.py --faults`. With it, a diagnostics status at level Error that is not on the noise list becomes a FATAL `errors` entry, so the time budget's `faulted` bucket is computed for the first time. It also added `fleet/moroop_faults.py`, which tabulates every status and the overlap of each stall with an Error status. S16B (PR #58) added `fleet/moroop_dispatch.py`, which classes the dispatcher's events against the `-sb` stuck episodes and runs our parser over `robot_state_raw` instead of the authors' cleaned table. The queue items `wr-s16a-run` (exit 0) and `wr-s16b-run` (exit 0) wrote `results/fleet/moroop_faults.json`, `moroop_label-sf.json`, `timebudget_moroop-sf.json`, `timebudget_moroop_shifts-sf.json` and `moroop_dispatch.json`, committed with this section. `-sf` is `-sb` (S14A, bounded station stop, radius 1) plus `--faults`; nothing else changed. As in Sprint 15, the tables are not printed by `scripts/sprint8_tables.py`. A read-only script over those files and the `-sb` ones printed them, and its text is in `reports/wr-dev-s16-readme.md`. The label for faulted seconds and the `faulted_self` cause is "Robot reported a component error". The detector's own cause label for `faulted_self`, still in the `-sf` files, may not be quoted for MoRoOp (Part 9 section 1).

#### (x1) The real-log time budget with `faulted` computed (MoRoOp, 9 shifts, pooled; `-sb` / `-sf`)

| bucket | -sb s | -sb share | -sf s | -sf share | delta s |
|---|---|---|---|---|---|
| moving | 106,171 | 40.41% | 106,113 | 40.39% | -58 |
| waiting_station | 107,005 | 40.73% | 107,188 | 40.80% | +183 |
| waiting_shelf | n/a | n/a | n/a | n/a | n/a |
| stuck | 1,773 | 0.67% | 1,264 | 0.48% | -509 |
| stopped_short | 1,870 | 0.71% | 1,763 | 0.67% | -107 |
| faulted | not computed | not computed | 508 | 0.19% | +508 |
| idle | 25,767 | 9.81% | 25,750 | 9.80% | -17 |
| paused | 161 | 0.06% | 161 | 0.06% | +0 |
| no_data | 19,970 | 7.60% | 19,970 | 7.60% | +0 |
| span | 262,717 | | 262,717 | | sum of deltas +0 |

| shift | faulted s (bucket) | faulted share of span | faulted s from raw | stuck s -sb | stuck s -sf |
|---|---|---|---|---|---|
| 0: 2026_07_27_morning | 31 | 0.106% | 31 | 0 | 0 |
| 1: 2026_07_27_evening | 42 | 0.145% | 42 | 160 | 152 |
| 2: 2026_07_28_morning | 98 | 0.330% | 98 | 0 | 0 |
| 3: 2026_07_28_evening | 28 | 0.096% | 28 | 0 | 0 |
| 4: 2026_07_29_morning | 37 | 0.128% | 37 | 0 | 0 |
| 5: 2026_07_29_evening | 50 | 0.172% | 50 | 0 | 0 |
| 6: 2026_07_30_morning | 35 | 0.119% | 35 | 1107 | 1107 |
| 7: 2026_07_31_morning | 120 | 0.415% | 197 | 282 | 5 |
| 8: 2026_07_31_evening | 67 | 0.228% | 67 | 224 | 0 |
| **pooled** | 508 | 0.193% | 585 | 1773 | 1264 |

This is the `faulted` column that (q) shows as "not computed". The bucket holds 508 s, against 585 s of Error status counted from the raw rows. The 77 s difference is all in shift 7, and the file's note says why: `no_data` outranks `faulted`. Of the 585 raw seconds, 58 are while driving (0.099) and 0 in paused rows. The (q) caveat "the diagnostics levels (Ok, Warning, Error, Stale) are undocumented" is superseded in part: Part 9 section 1 identifies them as the ROS levels at rank B (inferred), and wheel.me's own documents are untested, not read. Its correction sentence: "`faulted`: the diagnostics levels are the ROS diagnostic levels (OK, WARN, ERROR, STALE; REP 107), inferred from the field names and a stock ROS message, not documented by wheel.me. A component ERROR does not say the robot stopped, so S16A's faulted bucket is our rule and is reported with its seconds while driving." Sources: `results/fleet/timebudget_moroop-sb.json` and `timebudget_moroop-sf.json` (`seconds`, `share`, `faulted`), `results/fleet/timebudget_moroop_shifts-sb.json` and `timebudget_moroop_shifts-sf.json` (`faulted`, `shifts.*.timebudget_robot.seconds`), `results/fleet/moroop_faults.json` (`table_a`, `cross_check`).

#### (x2) Stalls with no identified cause, before and after the diagnostics lookup (`-sb` / `-sf`)

| cause | public label | -sb episodes | -sb s | -sf episodes | -sf s |
|---|---|---|---|---|---|
| station_overrun | Station stop over time limit | 4 | 4,250 | 2 | 3,563 |
| faulted_self | Robot reported a component error | 0 | 0 | 8 | 1,237 |
| unknown | Stopped, cause not identified | 2 | 180 | 1 | 47 |

| shift | start | s | cause -sb | cause -sf | s under an Error status (share) | Error statuses over the stall |
|---|---|---|---|---|---|---|
| 1 | 2026-07-27T19:03:16Z | 318 | station_overrun | station_overrun | 8 (0.025) | /Wheels "Error" 8 s; /Wheels/FL "Lidar: Calibrating" 8 s |
| 2 | 2026-07-28T09:24:05Z | 41 | no episode | faulted_self | 41 (1.000) | /System "Error" 41 s; /System/Clock "Not synchronized" 41 s |
| 6 | 2026-07-30T06:16:31Z | 3245 | station_overrun | station_overrun | 0 (0.000) | none |
| 6 | 2026-07-30T07:10:44Z | 47 | unknown | unknown | 0 (0.000) | none |
| 6 | 2026-07-30T07:35:38Z | 37 | no episode | faulted_self | 2 (0.054) | /Wheels "Error" 2 s; /Wheels/FL "Lidar: Calibrating" 2 s |
| 6 | 2026-07-30T10:53:31Z | 36 | no episode | faulted_self | 2 (0.056) | /Wheels "Error" 2 s; /Wheels/BR "Lidar: Calibrating" 2 s |
| 7 | 2026-07-31T06:42:16Z | 41 | no episode | faulted_self | 2 (0.049) | /Wheels "Error" 2 s; /Wheels/BR "Lidar: Calibrating" 2 s |
| 7 | 2026-07-31T10:00:24Z | 343 | station_overrun | faulted_self | 7 (0.020) | /Wheels "Error" 7 s; /Wheels/BR "Lidar: Calibrating" 7 s |
| 7 | 2026-07-31T12:18:25Z | 262 | no episode | faulted_self | 164 (0.626) | /Navigation "Error" 164 s; /Navigation/Robot Stuck ": Goal is obstructed. Remove obstacle from goal location." 164 s |
| 7 | 2026-07-31T12:23:06Z | 133 | unknown | faulted_self | 1 (0.008) | /Navigation "Error" 1 s; /Navigation/Robot Stuck ": Goal is obstructed. Remove obstacle from goal location." 1 s |
| 8 | 2026-07-31T17:43:15Z | 344 | station_overrun | faulted_self | 23 (0.067) | /Wheels "Error" 23 s; /Wheels/BR "Lidar: Calibration failed" 23 s |

"No episode" = the `-sb` detector opened no stuck episode at that start. Each stall lists two statuses with the same seconds, a parent path (`/Wheels`, `/System`, `/Navigation`) with message "Error" and a child path under it; the overlap column counts a second once. **Noise families:** the noise list has one entry, `/Devices/Camera` "Frequency too high." at Warning (1,830 status rows, 3,685 s; stock `diagnostic_updater` FrequencyStatus, Part 9 section 2). Warning never counts as faulted, so it removes nothing from the bucket or from the table above. Of the 51 (level, name, message) combinations in the log, 20 at Error are faulted by our rule, 1 is the noise entry, and 30 (29 Warning, 1 Stale) are unclassified. The families on the stalls (Lidar "Calibrating" and "Calibration failed", `/System/Clock` "Not synchronized", Robot Stuck "Goal is obstructed") have no documented meaning, so they are unclassified, not noise (Part 9 section 2). Sources: `results/fleet/moroop_label-sb.json` and `moroop_label-sf.json` (`pooled.causes.table`), `results/fleet/moroop_faults.json` (`table_b.sb`, `table_b.sf`, `table_c`, `verdict_inputs`).

#### (x3) Dispatcher events against the stuck episodes, and the authors' cleaning (S16B)

| class (Part 9 section 3) | events |
|---|---|
| dispatcher refused (39 start denials, 2 auto-pauses) | 41 |
| external call | 3 |
| shift start (a resume before the shift's first `operation_started`) | 9 |
| neither (`started`, `stopped`, `operation_failed`) | 10 |

| shift | event | time | class | inside a stuck episode | after a stuck episode | intervention |
|---|---|---|---|---|---|---|
| 6: 2026_07_30_morning | paused | 2026-07-30T06:01:31Z | external call | no | no | no |
| 6: 2026_07_30_morning | paused (auto-pause) | 2026-07-30T06:21:15Z | dispatcher refused | 3245 s episode, 284.2 s in | no | no |
| 6: 2026_07_30_morning | resumed | 2026-07-30T07:11:22Z | external call | 47 s episode, 38.6 s in | 46.6 s after the 3245 s episode | yes |
| 7: 2026_07_31_morning | paused (auto-pause) | 2026-07-31T12:23:29Z | dispatcher refused | 127 s episode, 18.7 s in | 42.7 s after the 250 s episode | no |
| 7: 2026_07_31_morning | resumed | 2026-07-31T12:25:42Z | external call | no | 24.4 s after the 127 s episode | yes |

| raw ids | count | share of the 2,959 the authors removed | collapse drops among them |
|---|---|---|---|
| both drop (the authors and our rules) | 0 | 0.0% | 0 |
| authors only | 2,959 | 100.0% | 1,314 |
| ours only | 0 | 0.0% | 0 |

The event rows are every pause and every resume other than the 9 shift-start resumes. A stuck episode here is every entry of the `-sb` label file's labelled episodes of 30 s or more and its detector false alarms (S16B lane report, "Rules"). That is why the 127 s and 250 s episodes are the robot's own labels, not the 133 s detector run of (x2). "Near" is ±120 s. The table holds 11 resumes against 3 pauses: 3 resumes have a pause before them, 8 do not, and no explanation is asserted (Part 9 section 3). Cleaning: 140,386 raw rows, 137,427 cleaned, 2,959 removed by the authors (2.1%). Our rule drops on the raw path are 0, and no cleaned id is missing from raw. Collapse drops (the adapter's last-row-per-second resampling) are counted apart and are not "our drops": 6,444 in all, 1,314 of them among the authors-only rows. The authors-only rows are 2,645 Navigating and 314 Idle, all Autonomous, with no missing or non-finite pose or velocity. Their pose stays within x 0.39 to 8.21 m and y -1.84 to 0.41 m. Their diagnostics maximum is Ok in 2,758, Warning in 184, Error in 2 and none in 15. Source: `results/fleet/moroop_dispatch.json` (`pooled.classes`, `pooled.resumes_vs_pauses`, `shifts.*.events`, `pooled.cleaning`, `verdicts`, `page_sentence`).

**Reading the numbers.**
- **S16A refute line: mixed (x2).** Part 9 section 5: "fault cause" needs both `-sb` "cause not identified" episodes to overlap a faulted status for ≥ 50% of their seconds and ≤ 20% of pooled faulted seconds while driving. "Unknown stays unknown" needs neither to overlap at all. The two episodes overlap for 0 of 47 s and 1 of 133 s (0.008), so the first condition fails. The driving share is 58 of 585 s (0.099), which is under 0.20. One second of overlap is what keeps the verdict from "unknown stays unknown". In substance, the diagnostics give these two stalls no cause. The file says "n = 2: a description, not a rate".
- **"ERROR = stopped" is refuted for five families (x2, `table_a`).** Part 9's line is a share above 50% while driving. Robot Stuck "Blocked by obstacle. Check robot surroundings." is at 31 of 39 s (0.79), and the four `/Wheels/<BL, BR, FL, FR>` "Power Input: Not Charging." families are at 5 of 5, 5 of 5, 4 of 4 and 1 of 1 s. All five are small. The large families are mostly while stopped: `/Wheels` "Error" 310 s at 0.02, `/Navigation` "Error" 206 s at 0.16, Robot Stuck "Goal is obstructed" 167 s at 0.01.
- **The unknowns shrink from 2 (180 s) to 1 (47 s), but only one flip rests on the diagnostics (x2).** The 133 s stall becomes `faulted_self` on 1 s of Error status. The S16A lane report puts this down to the detector's rule: a stall takes the cause of the message that enters the stuck state. Two station overruns (343 s and 344 s) flip to `faulted_self` the same way, on 7 s and 23 s. Of the 8 `faulted_self` episodes, 2 are under an Error status for more than half their seconds: 41 of 41 s (clock not synchronized) and 164 of 262 s (goal obstructed). The other 6 are at 0.008 to 0.067. The 47 s stall, which the dispatcher's resume falls inside, overlaps no status at all.
- **`--faults` moves the stuck bucket, not only the faulted one (x1).** Stuck goes from 1,773 s to 1,264 s (0.67% to 0.48% of the span) and `faulted` takes 508 s, while every bucket together still sums to the span. Shift 8 goes from 224 s stuck to 0, and shift 7 from 282 s to 5. The stuck runs in the label comparison go from 6 to 4, false alarms from 5 to 3, and TIMEOUT operations overlapped from 5 of 8 to 3 of 8. The two labelled stops of 30 s or more are still both detected. The 1,107 s in shift 6 (the 3,245 s station overrun of (s)) do not move: no Error status falls inside that stop.
- **S16B dispatcher refute line: marks the intervention (x3).** The line is a non-auto pause or resume in or within ±120 s of the 3,245 s shift-6 episode. The external resume at 07:11:22 is 46.6 s after it ends. The auto-pause at 06:21:15 is inside it, but the dispatcher's retry limit raised it, so it does not count. The external pause at 06:01:31 is 15 minutes before the episode and near no episode. The other intervention is the resume 24.4 s after the 127 s labelled stop in shift 7. Who made either call cannot be told from the dispatcher's code (Part 9 section 3), so the README does not say "a human".
- **S16B cleaning refute line: our ingest keeps rows the authors removed (x3; the file's verdict "we keep theirs").** "Our drops match theirs" needs ≥ 90% of the authors' removed raw ids to be our rule drops. They are 0 of 2,959 (0%). "Our ingest keeps rows the authors removed" needs > 10% to pass our rules, and all 2,959 do (100%). This is a counterfactual run on `robot_state_raw`. Production reads the cleaned table, so on our real path the authors' removals happen before our parser sees anything. The authors-only rows have no missing or non-finite pose or velocity,, and `velocity_x` is at most 0.80 m/s. Why the authors removed them is not answered by the data (Part 9 section 4: no published thresholds).
- **Page wording (x3).** The file's `page_sentence_holds` is true for "No row of the authors' cleaned table was rejected by our parser; the authors had already removed 2,959 of 140,386 raw rows (2.1 %)". Part 9 section 4 does not allow "no row rejected" on its own.

**Caveats.**
- One robot, nine shifts, one lab. The S16A verdict rests on two stalls and one second of overlap, and the dispatcher verdict on one resume that also falls inside the next stall (47 s). Neither is a rate.
- The Error-to-faulted rule is ours, at rank B. A ROS ERROR is a statement about one component, and REP 107 says diagnostics halt nothing. The faulted bucket is our classification, not the robot's own statement that it stopped.
- The `faulted_self` flips are a detector-rule effect: the entering message sets the cause. A stall whose seconds are under an Error status for 1 to 7% is still filed under it. Whether to require an overlap share before a cause is assigned was not tested.
- `no_data` outranks `faulted`, so the bucket under-counts raw Error seconds by 77 s, all in shift 7.
- The S16B stuck-episode set mixes the robot's own labels and our detector's false alarms (`-sb`). On `-sf` the false alarms change (5 to 3), and S16B was not re-run on `-sf`.
- "Our drops" are message-format rules (json, timestamp, type). They were never meant to catch localization or plausibility faults, so 0 of 2,959 is the expected reading, not a failure of a quality check.
- Deterministic on one log, no CI. The tables were printed by a read-only script, not by `scripts/sprint8_tables.py`.

## Sprint 18: keeping less of the log (2026-10-30)

Question (operator, from buyers): how small can a fleet state log get while every answer the analyser gives stays the same. Standard name (`docs/LITERATURE.md` Part 10 section 1): report by exception (change-only) with a maximum interval, zero deadband. Not compression: gzip of the full log is the baseline the ratio is measured against. Reports: `reports/wr-dev-lit-s18.md`, `reports/wr-lane-s18a-keep-what-matters.md`, `reports/wr-dev-s18-readme.md`.

#### (y) Keeping less of the log (S18A)

The keep rules are a ladder (Part 10 section 4), each rung the one before plus one rule: `all` (identity), `change` (a line only when a field the analyser reads changes, plus each robot's first and last line), `gap` (no interval longer than the heartbeat H, source gaps kept as gaps), `threshold` (the line that makes a stop count as stuck), `neighbours` (the zone batch at each episode's entry), `recovered` (the line after each episode ends). Every rung is run at H = 30 s (the VDA 5050 `state` heartbeat) and H = 60 s (our gap rule). "Identical" means every applicable output equal to the full log's, no tolerance: time budget, stall list, transitions, and on MoRoOp also the station bound, the S15A rows and the labelled-stop hits. `ratio_gzip` = gzip bytes of the full log / gzip bytes of the reduced log, both re-gzipped the same way, so `all` is exactly 1.0.

**s10-none** (`results/fleet/reduce_s10-none.json`): 120 robots, 83.2 robot-hours, 60,000 lines in, 721.4 lines per robot-hour in; outputs not applicable: station_bound, s15a_rules, label_hits.

| rung | H | lines kept | line ratio | ratio_gzip | kept lines/robot-h | outputs that differ (items) | identical |
|---|---|---|---|---|---|---|---|
| all | 30 s | 60,000 | 1.0000 | 1.0000 | 721.4 | none | yes |
| all | 60 s | 60,000 | 1.0000 | 1.0000 | 721.4 | none | yes |
| change | 30 s | 33,340 | 1.7996 | 1.2646 | 400.9 | time_budget 117, stall_list 627, transitions 8,230 | no |
| change | 60 s | 33,340 | 1.7996 | 1.2646 | 400.9 | time_budget 117, stall_list 627, transitions 8,230 | no |
| gap | 30 s | 37,188 | 1.6134 | 1.2185 | 447.2 | stall_list 41, transitions 5,425 | no |
| gap | 60 s | 35,080 | 1.7104 | 1.2040 | 421.8 | time_budget 26, stall_list 233, transitions 6,470 | no |
| threshold | 30 s | 37,193 | 1.6132 | 1.2183 | 447.2 | stall_list 37, transitions 5,420 | no |
| threshold | 60 s | 35,732 | 1.6792 | 1.2088 | 429.6 | stall_list 40, transitions 5,420 | no |
| neighbours | 30 s | 39,746 | 1.5096 | 1.1843 | 477.9 | transitions 5,187 | no |
| neighbours | 60 s | 38,443 | 1.5608 | 1.1839 | 462.2 | transitions 5,187 | no |
| recovered | 30 s | 39,944 | 1.5021 | 1.1820 | 480.3 | none | yes |
| recovered | 60 s | 38,641 | 1.5528 | 1.1816 | 464.6 | none | yes |

**moroop-sf** (`results/fleet/reduce_moroop-sf.json`): 9 robots, 73.0 robot-hours, 132,838 lines in, 1820.3 lines per robot-hour in; outputs not applicable: none.

| rung | H | lines kept | line ratio | ratio_gzip | kept lines/robot-h | outputs that differ (items) | identical |
|---|---|---|---|---|---|---|---|
| all | 30 s | 132,838 | 1.0000 | 1.0000 | 1820.3 | none | yes |
| all | 60 s | 132,838 | 1.0000 | 1.0000 | 1820.3 | none | yes |
| change | 30 s | 132,740 | 1.0007 | 1.0004 | 1818.9 | time_budget 1, transitions 2, s15a_rules 4 | no |
| change | 60 s | 132,740 | 1.0007 | 1.0004 | 1818.9 | time_budget 1, transitions 2, s15a_rules 4 | no |
| gap | 30 s | 132,801 | 1.0003 | 1.0001 | 1819.8 | transitions 1 | no |
| gap | 60 s | 132,785 | 1.0004 | 1.0002 | 1819.5 | transitions 1 | no |
| threshold | 30 s | 132,802 | 1.0003 | 1.0001 | 1819.8 | none | yes |
| threshold | 60 s | 132,786 | 1.0004 | 1.0002 | 1819.6 | none | yes |
| neighbours | 30 s | 132,802 | 1.0003 | 1.0001 | 1819.8 | none | yes |
| neighbours | 60 s | 132,786 | 1.0004 | 1.0002 | 1819.6 | none | yes |
| recovered | 30 s | 132,802 | 1.0003 | 1.0001 | 1819.8 | none | yes |
| recovered | 60 s | 132,786 | 1.0004 | 1.0002 | 1819.6 | none | yes |

| run | H | first identical rung | verdict | ratio_gzip | line ratio | headerId gaps / missing at that rung |
|---|---|---|---|---|---|---|
| s10-none | 30 s | recovered | identical | 1.1820 | 1.5021 | 6,466 / 20,056 |
| s10-none | 60 s | recovered | identical | 1.1816 | 1.5528 | 5,481 / 21,359 |
| moroop-sf | 30 s | threshold | identical | 1.0001 | 1.0003 | 42 / 45 |
| moroop-sf | 60 s | threshold | identical | 1.0002 | 1.0004 | 44 / 61 |

The three references (Part 10 section 2):
- (a) **gzip of the full log**: the ratio is against it, so the number is the gain over plain compression.
- (b) **kept lines per robot-hour against the emitted rate**: the simulator emits every robot every 5 s (721.4 lines per robot-hour in); MoRoOp is already change-only (1820.3 in).
- (c) **the 3:1 floor** AVEVA calls the suggested minimum (a vendor's rule of thumb, rank D). It counts events; on gzip bytes it is the stricter reading, so the line ratio is shown next to it. Neither ratio reaches 3 on either run.

**Reading the numbers.** The refute line (Part 10 section 5) is met as **identical** on both runs at both H: a reduced stream gives the same answers. The ratio at the first identical rung is below 3 in all four cells, so on these two runs the pitch is **not worth making**. On the simulator `change` alone is not enough (117 time-budget items and 627 stall-list items differ); each later rung fixes the diff the one before it leaves, and only `recovered` is identical. On MoRoOp `threshold` is enough.

**Caveats.**
- **MoRoOp is already change-only** (q), and `theta` changes on almost every line, so `change` keeps 132,740 of 132,838 lines. A ratio near 1 there is expected and is not a refutation; the MoRoOp cell shows the reduction is harmless there, not that it pays.
- **A VDA 5050 fleet already sends `state` change-only with a 30 s heartbeat**, so the simulator's every-step stream overstates the gain for such a fleet: the simulator ratio is the best case. A real VDA 5050 fleet's gain would be against `visualization` messages or bags, which the analyser does not read.
- Dropping lines leaves headerId holes by construction (last column of the summary table); a consumer that alarms on them would alarm on a reduced log. They are reported apart, not in "identical".
- Two runs: a 10-zone x 500-step undisturbed simulator run and nine MoRoOp shifts. The eight-hour simulator runs (`s10-none-8h`, `s10c-blind-8h`) were not run.

Source: `results/fleet/reduce_s10-none.json`, `results/fleet/reduce_moroop-sf.json` (`heartbeat.<H>.rungs`, `first_identical_rule`, `ratio_gzip_at_first_identical_rule`, `verdict`), written by `fleet/reduce_check.py`. The tables were printed by a read-only script whose text is in `reports/wr-dev-s18-readme.md`.

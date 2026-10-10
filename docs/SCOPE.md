# Scope and sprint plan

> STATUS: canon. Written 2026-10-09, revised 2026-10-10 (direction change, see "Where to focus"). Supersedes the Claude Doc "Warehouse Robot RL Scoping" (same date), which
> was the exploratory pass; this file adds the verified install, the measured baseline, and the sprint plan.
> Premises verified 2026-10-09: TA-RWARE installs and runs locally (see README, `scripts/setup.sh`).

## The one claim

Revised 2026-10-10. Two candidate claims share one harness; pick after the common core is built.

- Recovery (preferred): a learned stuck-recovery policy plus order reassignment cuts stuck time and holds
  pick-rate better than timeout-and-wait AND better than a hand-written back-off-and-reroute rule, across a sweep
  of failure rates and fleet densities.
- Dispatcher (original): a learned task-allocation policy beats the FIFO heuristic on pick-rate, same map, same
  seeds, clean sim and under disturbance.

Either way, if the learned policy loses, that is the result and the calibrated simulator plus the sweep curves
are the deliverable.

## Where to focus (decision log, 2026-10-10)

Motivating scenario: a company whose warehouse robots "get stuck". Question: how to model that without their data.

Three layers of decision, and RL can sit in any of them:

| Layer | Decision | TA-RWARE today | Where learning can go |
| --- | --- | --- | --- |
| Dispatcher | which shelf, which station, which empty slot | RL or FIFO | sees stuck robots only via obs; can learn to reassign away from frozen robots and jammed aisles |
| Router | which cells to drive through | A* per robot, replan on clash | steer the planner, do not replace it: learned priorities (who yields), learned edge weights (one-way lanes under load), learned replan triggers |
| Recovery | what to do when blocked | wait, replan around the other robot, give up after a fixed window (`fixing_clash`, stuck counter) | small policy triggered on stuck events: wait / back off one cell / reroute via another lane / abandon task and return shelf / call human. ~5 actions, sparse events, tractable |

Reasoning that led to "core first, then recovery":
- Disturbances are exogenous and the env has none. Clashes and stucks exist but are endogenous (baseline: 10 to 15
  clashes, 0 to 1 stuck per 500-step episode). A disturbance wrapper is needed for any robustness claim.
- You do not need the client's logs. You need their failure taxonomy and rough rates (one conversation with an ops
  manager: how often, how long, where), then sweep each knob over a plausible range and report curves, not points.
  Results are relative (policy A vs B under disturbance X), never absolute ("your warehouse will do N/h").
- The density sweep (fixed map, 2 to 16 AGVs, FIFO only) needs no assumptions and shows the congestion collapse
  point, which is usually what "robots get stuck" means in practice. Run it first.
- Breakdowns and blocked cells hurt every dispatcher about equally; the dispatcher only wins on demand bursts and
  density (allocation problems). Pure breakdown recovery is a routing/recovery-layer problem.
- Recovery has the smallest action space and the clearest client story, so it is the more likely win. Its default
  baseline (timeout) is a low bar; a hand-written recovery rule MUST be in the comparison or the result is hollow.
- Replacing A* with a learned planner is the option to avoid: published learned planners rarely beat good solvers.

Disturbance taxonomy to implement in the wrapper (Sprint 1):

| Disturbance | Model | Knobs |
| --- | --- | --- |
| Robot breakdown / battery swap | agent frozen d steps, others route around | rate per robot-hour, duration dist |
| Execution delay | robot skips a move step | prob per step (LoRR 2026 Execution track does this) |
| Blocked cell | pallet or human in an aisle, cell impassable d steps | rate, duration, zones |
| Demand burst | request queue 20 -> 40 for a while | timing, size |
| Workstation outage | one goal disabled d steps | rate, duration |
| Fleet density | more AGVs on the same map | count only |

Feasibility notes, read from `vendor/tarware/tarware/warehouse.py`, not yet tried:
- Paths are recomputed from a grid mask in `find_path` on every replan, so freezing an agent or blocking a cell
  via the wrapper should work by editing that mask / overriding the agent's action to no-op.
- Recovery decisions happen inside `step` (clash block, `fixing_clash`). Exposing them as a hook for a policy is
  modest surgery, budget 1 to 2 days with uncertainty.

Effort estimates (working days, focused; training unattended overnight; unmeasured, +/- 50%):

| Path | Yields | Days |
| --- | --- | --- |
| Common core | harness, disturbance wrapper, density + failure sweeps with FIFO, collapse curves | 3 to 4 |
| Recovery only | core + recovery hook + small policy vs timeout vs hand-written rule | 8 to 10 total |
| Dispatcher MVP | core + IPPO/MAPPO vs FIFO, clean and under disturbance | 9 to 11 total |
| Both + write-up | one report | 15 to 18 total |
| Whole sprint plan | + realistic demand, LLM dispatcher, exam packaging, hybrid routing | 25 to 30 total |

Before the core is finished, if there is a real company: get their failure taxonomy and rates. Everything after
the core is parameterised on that.

## Premises and kill criteria

| Premise | Status | If false |
| --- | --- | --- |
| TA-RWARE installs and steps fast enough for CPU training | Verified 2026-10-09: ~1,700 steps/s small map, M1 Pro | n/a |
| EPyMARL can wrap TA-RWARE with action masking | UNVERIFIED. Env `reset()` returns obs only, not `(obs, info)`, and actions are 103-way discrete with invalid actions, so a wrapper is required | Write a compact IPPO in PyTorch instead (Sprint 2, option B) |
| RL beats FIFO on the small map within ~5M env steps | UNVERIFIED. Paper (Krnjaic et al. 2023) reports gains with their own hierarchical method, not plain IPPO | Stop at end of Sprint 2, write up as negative result, keep harness |
| Footwear dataset gives a usable shelf-popularity distribution | UNVERIFIED, page opened but files not downloaded | Use a Zipf prior and say so |

Known env facts (read from source, `vendor/tarware/tarware/`):
- Map sizes: tiny (1x3 racks), small (2x3), medium (2x5), large (3x5), extralarge (4x7). Episode = 500 steps, 1 step = 5 s.
- Action per agent = Discrete(num_locations + goals), 103 on small. Valid-action masks exist (`valid_action_masks`, warehouse.py:747).
- Global obs on small = 228 floats per agent. Rewards: +1 AGV delivery, +0.1 picker assist. Requests sampled uniformly.
- The FIFO heuristic ignores observations and reads env state directly.

## Sprints

Each sprint has a coding half and a training half. Exit criterion is a thing that runs, not a doc.

### Sprint 0: foundation (done 2026-10-09)

- [x] Repo, venv, TA-RWARE and its A* dependency built on macOS (`scripts/setup.sh` records the two gotchas)
- [x] FIFO baseline, 10 seeds, small and medium (README table, `results/fifo_*.json`)

### Sprint 1: evaluation harness + disturbance wrapper (coding, 3 to 4 days)

Goal: one command that scores any policy on the same seeds as FIFO, with a disturbance config, and prints a
comparison table. Then the density sweep and one failure-rate sweep with FIFO.

- [ ] `src/warehouse_rl/env.py`: Gymnasium-compliant wrapper. `reset -> (obs, info)`, `info["action_mask"]`
      per agent, per-agent rewards as a list, optional global reward sum. Thin, no logic changes.
- [ ] `src/warehouse_rl/policy.py`: `Policy.act(obs, masks, info) -> list[int]`. Implement `RandomPolicy` and
      `FifoPolicy` (adapter over `tarware.heuristic`).
- [ ] `scripts/evaluate.py --policy <name> --env <id> --seeds 0-9`: writes `results/<policy>_<env>.json`, prints
      mean, SD, 95% CI, and the delta vs FIFO.
- [ ] Regression test: `FifoPolicy` through the harness reproduces `baseline_fifo.py` within noise on seeds 0-9.
- [ ] Throughput test: 8 parallel envs via `gymnasium.vector` or multiprocessing; record steps/s in the README.
- [ ] `src/warehouse_rl/disturb.py`: wrapper implementing the disturbance taxonomy above behind a config dict.
      Start with breakdown (freeze) and blocked cell; delay and burst next.
- [ ] `scripts/sweep.py`: density sweep (2 to 16 AGVs, small map, FIFO) and breakdown-rate sweep; plots to
      `results/`. Also record one disturbed episode with `record_episode.py` for the replay viewer.

Exit: `evaluate.py --policy random` and `--policy fifo` both run; random is worse than FIFO; collapse curves in
README. Decision point: recovery vs dispatcher (default: recovery).

### Sprint 2: first learner (training, 3 to 4 days wall, mostly unattended)

Goal: a learning curve and a pick-rate number against FIFO on the small map.

Option A, try first (1 day to wire): EPyMARL. Register the Sprint 1 wrapper as a Gymnasium env, expose
`get_avail_actions` for masking, run IPPO and MAPPO with shared parameters. Common-reward and per-agent variants.

Option B, fallback (2 days to write): a compact masked IPPO in PyTorch, ~300 lines, shared actor-critic across
agents with an agent-type embedding. Vectorised envs from Sprint 1. Pick this if EPyMARL fights the wrapper for
more than a day.

Training budget, estimated not measured: 2M to 5M env steps per run. At 300 to 500 steps/s including the policy
forward pass that is 1 to 5 hours per run on CPU. 3 seeds per config. Runs overnight.

- [ ] Wire env into EPyMARL or write IPPO
- [ ] Reward shaping ablation: raw sparse reward vs small per-step penalty vs distance-to-target bonus
- [ ] Log pick-rate every N updates (not just return), save checkpoints, plot curves with `dataviz` conventions
- [ ] Evaluate the best checkpoint through `evaluate.py` on seeds 0-9

Exit: table RL vs FIFO vs random, small map, 10 eval seeds, CI. Either direction is a valid exit.
Kill: after 5M steps and one shaping pass, RL is within one SD of FIFO. Stop, write up, go to Sprint 3b only.

### Sprint 2b: recovery policy (coding 2 days, training 1 to 2 days). Preferred over Sprint 2 as of 2026-10-10.

- [ ] Pull the clash/stuck handling in `warehouse.py` `step` into a hook: on a stuck event, ask a `RecoveryPolicy`
      for one of {wait, back off one cell, reroute via other lane, abandon and return shelf, call human}
- [ ] Baselines through the hook: `TimeoutRecovery` (the env default) and `RuleRecovery` (hand-written
      back-off-then-reroute). The rule baseline is mandatory.
- [ ] Train a small policy on stuck events (DQN or PPO over a short local observation), under the disturbance
      wrapper at several failure rates
- [ ] Optional second lever: dispatcher reassigns the stuck robot's order
- [ ] Report: stuck time and pick-rate vs failure rate, three recovery policies, CI over seeds

Exit: curves. Kill: learned recovery does not beat `RuleRecovery`; the client takes the rule, write that up.

### Sprint 3a: make it non-toy (coding 2 days, training 2 days)

Goal: the result says something about operations, not about a toy.

- [ ] Realistic demand: download the footwear order-picking dataset (Mendeley `pf2w725pw3`, CC BY 4.0), fit SKU
      popularity, map to shelf popularity, patch the env's request sampler (uniform today) behind a flag
- [ ] Re-run FIFO and the trained policy on skewed demand; report both
- [ ] Scale to medium map (8 AGV + 4 pickers, FIFO = 54.4/h) with the same pipeline

Exit: two-demand-regime table. Kill: dataset is unusable, fall back to Zipf and label it.

### Sprint 3b: the non-traditional angles (coding 1 to 2 days each, no training)

Pick one or two. They reuse `evaluate.py` and need no RL training.

- [ ] LLM dispatcher: `OllamaPolicy` that gets a text summary of the state and returns target locations.
      Local gemma4 via Ollama. Expected to lose on pick-rate; the eval harness is the artefact.
- [ ] Warehouse as an agent exam: freeze env, seeds and scoring into an exam spec in the agent-sandbox
      format, so any agent (LLM, RL, heuristic) is graded the same way
- [ ] Traffic-rule evolution: one-way lanes on the grid, MAP-Elites over lane directions, FIFO as the evaluator.
      Not RL. Visual, and the guidance-graph literature says the gains are large.

### Sprint 4: hybrid, stretch (1 to 2 weeks)

RL steers the classical planner instead of replacing it: the policy sets AGV priorities or chooses when to
replan, and A* (or a PIBT port from the League of Robot Runners start kit) does the routing. This is the version
a robotics person would respect. Only start if Sprint 2 produced a positive result.

### Sprint 5: write-up (2 days)

Negative or positive, one page with the tables, the curves, and the honest caveats. Candidate for the portfolio
showcase set. Decide whether this becomes a Wilco exam.

## Compute and timing

Everything above is CPU on the M1 Pro. The step-rate number is measured; training throughput and run times are
estimates until Sprint 1's throughput test. No GPU, no cloud, no JAX rewrite unless Sprint 2 is throughput bound.

## Open decisions

- [ ] Portfolio piece or client-facing? Decides whether Sprint 3a uses the public dataset or a WMS export.
- [ ] Add to the GitHub showcase set once Sprint 2 has a table, regardless of direction?

## Tooling notes

- `scripts/record_episode.py` records any episode (agent positions, carrying state, targets, request queue,
  shelves, cumulative deliveries) to JSON. `scripts/replay_template.html` + the JSON = `results/replay_small.html`,
  an animated replay with scrubber and live pick-rate. Works for any policy once the harness exists; use it to
  show disturbed episodes and recovery behaviour.
- Published replay (FIFO, small, seed 0): https://claude.ai/artifact/4jb8nmT154TrYapGPBxUJ7

## Sources

- TA-RWARE source, `vendor/tarware`, commit of 2024-08-28, and its paper: Krnjaic et al. 2023, arXiv:2212.11498
- pyastar2d fork used by TA-RWARE: github.com/raulsteleac/pyastar2d_TARWARE
- EPyMARL: github.com/uoe-agents/epymarl (opened 2026-10-09)
- Footwear order-picking dataset: data.mendeley.com/datasets/pf2w725pw3/1 (opened 2026-10-09)
- League of Robot Runners start kit: github.com/MAPF-Competition/Start-Kit (opened 2026-10-09)

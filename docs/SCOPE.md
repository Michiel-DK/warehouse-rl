# Scope and sprint plan

> STATUS: canon. Written 2026-10-09. Supersedes the Claude Doc "Warehouse Robot RL Scoping" (same date), which
> was the exploratory pass; this file adds the verified install, the measured baseline, and the sprint plan.
> Premises verified 2026-10-09: TA-RWARE installs and runs locally (see README, `scripts/setup.sh`).

## The one claim

A learned task-allocation policy beats the FIFO heuristic on pick-rate in TA-RWARE, same map, same seeds, with
confidence intervals. If it does not, that is the result and the calibrated simulator is the deliverable.

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

### Sprint 1: evaluation harness (coding, 2 days)

Goal: one command that scores any policy on the same seeds as FIFO and prints a comparison table.

- [ ] `src/warehouse_rl/env.py`: Gymnasium-compliant wrapper. `reset -> (obs, info)`, `info["action_mask"]`
      per agent, per-agent rewards as a list, optional global reward sum. Thin, no logic changes.
- [ ] `src/warehouse_rl/policy.py`: `Policy.act(obs, masks, info) -> list[int]`. Implement `RandomPolicy` and
      `FifoPolicy` (adapter over `tarware.heuristic`).
- [ ] `scripts/evaluate.py --policy <name> --env <id> --seeds 0-9`: writes `results/<policy>_<env>.json`, prints
      mean, SD, 95% CI, and the delta vs FIFO.
- [ ] Regression test: `FifoPolicy` through the harness reproduces `baseline_fifo.py` within noise on seeds 0-9.
- [ ] Throughput test: 8 parallel envs via `gymnasium.vector` or multiprocessing; record steps/s in the README.

Exit: `evaluate.py --policy random` and `--policy fifo` both run; random is worse than FIFO; numbers in README.

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

## Sources

- TA-RWARE source, `vendor/tarware`, commit of 2024-08-28, and its paper: Krnjaic et al. 2023, arXiv:2212.11498
- pyastar2d fork used by TA-RWARE: github.com/raulsteleac/pyastar2d_TARWARE
- EPyMARL: github.com/uoe-agents/epymarl (opened 2026-10-09)
- Footwear order-picking dataset: data.mendeley.com/datasets/pf2w725pw3/1 (opened 2026-10-09)
- League of Robot Runners start kit: github.com/MAPF-Competition/Start-Kit (opened 2026-10-09)

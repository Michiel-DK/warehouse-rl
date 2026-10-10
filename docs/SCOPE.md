# Scope and sprint plan

> STATUS: canon. Written 2026-10-09, revised 2026-10-10 twice: (1) direction change to core-then-recovery, (2) review
> pass folding in a source audit of `vendor/tarware` and a literature check (see "Review findings"). Supersedes the
> Claude Doc "Warehouse Robot RL Scoping" (2026-10-09), which was the exploratory pass.
> Premises verified 2026-10-09: TA-RWARE installs and runs locally (see README, `scripts/setup.sh`).

## The one claim

Revised 2026-10-10. Two candidate claims share one harness; pick after the common core is built.

- Recovery (preferred): a learned stuck-recovery policy with task abandonment and re-dispatch as options cuts stuck
  time and holds pick-rate better than the env's built-in timeout AND better than a hand-written back-off-and-reroute
  rule, across a sweep of failure rates and fleet densities.
- Dispatcher (original): a learned task-allocation policy beats the Closest-Task-Assignment heuristic on pick-rate,
  same map, same seeds, clean sim and under disturbance.

Either way, if the learned policy loses, that is the result and the calibrated simulator plus the sweep curves
are the deliverable.

Positioning (from the literature check, 2026-10-10): "RL beats FIFO" is a reproduction of Krnjaic et al. 2023 at a
smaller scale. "First robustness and density characterisation of an open task-assignment warehouse benchmark, plus
a learned recovery layer compared against a hand-written rule" is a small, real gap. Write towards the second.

## Review findings (2026-10-10)

Source audit of `vendor/tarware/tarware/warehouse.py` (W), `heuristic.py` (H), `spaces/`, plus a literature check.
Read, not executed. Line numbers are from the vendored commit of 2024-08-28.

### Terminology and map labels

- The baseline is NOT FIFO. H:60-73 walks `request_queue` in list order (reset order, with replacements dropped into
  the delivered item's slot, so "first" is arbitrary) and assigns each request to the nearest free AGV by A* path
  length, delivers to the nearest goal, returns to the nearest empty slot. Pickers are zoned statically. The paper
  calls this Closest-Task-Assignment (CTA). Use "CTA" everywhere from now on; `FifoPolicy` becomes `CtaPolicy`.
- The paper's "GTP Small" map is 2x5 racks, 8 AGVs, 4 pickers, 20 requests, 10 goals. That is this repo's `medium`.
  Paper CTA on it: 52.7 lines/h. Our medium baseline: 54.4. The repo's `small` (2x3, 4+2) has no published numbers.
  Make `medium` the headline map.
- Paper results (arXiv 2212.11498v3, IROS 2024): IAC 65.2 vs CTA 52.7 on GTP Small (+24%), HIAC 66.7 (+27%). On GTP
  Large (4x7, 14+7): CTA 67.1, IAC 80.4, HIAC 86.0. Plain IAC captures ~90% of the hierarchical gain. They used
  action masking (AGVs to requested shelves + goals; pickers to AGV targets), 10,000 training episodes, episodes
  ending when all orders complete. IPPO/MAPPO/EPyMARL are not in the paper.

### Metric resolution

- `pick_rate = deliveries * 3600 / (5 * T)`. The 5 s/step constant comes from upstream `scripts/run_heuristic.py:56`.
- At T=500 one delivery = 1.44 lines/h. Small-map CTA: 18-24 deliveries, SD 2.8 over 10 seeds, 95% CI ~ +/- 2.
  A 5% effect (1.5 lines/h) is not detectable. Options: longer eval episodes (T configurable via `max_steps`) and/or
  30-50 seeds. Decide in Sprint 1 and state the minimum detectable effect in the README.
- `info["shelf_deliveries"]` counts delivery events regardless of the `has_delivered` reward gate (W:600-607), so the
  metric and the reward can differ slightly. Use the info count for pick-rate, as upstream does.

### Rewards (differs from the earlier summary)

- -0.001 per agent per step (W:674). +1 to the delivering AGV, gated by `has_delivered` which resets only on rack
  unload (W:563, 600-606). +0.1 to the picker on BOTH load and rack unload (W:537-544, 565-571), so twice per cycle,
  never on goal unload. AGVs get nothing for load/unload. `RewardType.INDIVIDUAL` is the registered default;
  `TWO_STAGE` exists in the enum but is unused.

### Built-in recovery (this is the TimeoutRecovery baseline)

Two mechanisms, both called from `step` (W:667-670):

- `resolve_move_conflict` (W:402-479): commit agents on longest paths / cycles in a move graph, NOOP the rest. When an
  agent's next cell is occupied by a non-moving agent with `fixing_clash == 0`: set own `fixing_clash = 4`
  (`_FIXING_CLASH_TIME`, W:14), replan with `care_for_agents=True` to the same goal, swap in the new path if one exists
  (W:460-468). Same-destination conflicts: loser NOOPs and gets `fixing_clash = 4` (wait, not replan). `clashes` in
  info counts only the replan attempts (W:462).
- `resolve_stuck_agents` (W:481-514) with `StuckCounter` (W:74-89), `_STUCK_THRESHOLD = 5` (W:15): counter +1 per step
  without position change for busy non-rotating agents. 5 < count < 15: NOOP + replan around agents (W:494-503).
  count > 15: `stucks += 1`, `busy = False`, task dropped (W:509-513). Counter resets on new task (W:371) and while a
  picker waits for a load (W:399).
- Consequences: (a) baseline stucks are 0-3 per episode because this already recovers; a learned recovery policy has
  no training signal until disturbances are injected AND this logic is routed through the hook; (b) any wrapper
  freeze longer than 5 steps triggers the replan and longer than 15 drops the task, so the disturbance layer must
  suppress the counter for frozen agents; (c) the hook is a subclass override of these two methods, estimated 30-60
  lines, cheaper than the 1-2 days budgeted earlier. The picker/AGV rack-cell exception (W:450-455) and the commit
  logic (W:402-440) must be kept.

### Disturbance layer feasibility (subclass `Warehouse`, do not wrap `step`)

- `find_path` (W:256-312) rebuilds its grid from agent layers on every call; shelves are passable for AGVs; pickers
  are confined to highways. Paths are computed on assignment (`care_for_agents=False`, W:366), on clash and on stuck,
  then consumed one cell per step in `_execute_forward` (W:517-520). `_recalc_grid` (W:314-325) overwrites `env.grid`
  every step; `env.highways` is static.
- Freeze (breakdown) and skip-move (delay): set `req_action = NOOP` for affected agents BEFORE `resolve_move_conflict`
  runs, because `_execute_forward` has no occupancy check and two agents can land on one cell otherwise. Also reset
  or skip those agents' stuck counters.
- Blocked cell: override `find_path` to add blocked cells to the mask, AND NOOP any FORWARD into a blocked cell in
  `execute_micro_actions`, because stored paths ignore the mask until replan. Setting `path = []` is wrong (AGV would
  TOGGLE_LOAD in place).
- Demand burst / request distribution: `request_queue` is a plain list, refilled in `process_shelf_deliveries`
  (W:593-598) by uniform `np.random.choice` over non-requested, non-carried shelves. Override that method for a
  skewed sampler; append to the list for bursts. Observation is computed after refill, so post-hoc edits show up one
  step late unless `extract_environment_info` is re-called.
- Station outage: remove a goal from `env.goals` for d steps and mask it; check the heuristic's `argmin` over goals
  tolerates it.
- RNG: the env seeds and draws from the GLOBAL `np.random` and `random` (W:759-761). The disturbance layer MUST use
  its own `np.random.Generator`, or it changes the env's spawns and requests. `seed=None` reseeds from entropy.
- Delay model to copy: League of Robot Runners 2026 `delayConfig`: per-agent Bernoulli or Poisson delay events,
  uniform or Gaussian durations (Start-Kit `Input_Output_Format.md`). Citable, and matches the "execution delay" row.

### Multi-env and masking (affects Sprint 1 throughput test and Sprint 4)

- `Agent.counter` and `Shelf.counter` are class attributes (W:618-619). Two env instances in one process corrupt each
  other. Vectorise with multiprocessing only, never in-process `gymnasium.vector.SyncVectorEnv`.
- `compute_valid_action_masks` (W:722-747) exists but is never called in the package, is not in `info`, and has
  aliasing bugs (W:735, 740, 741 mutate `requested_items` / `empty_items` in place). Write our own mask function in
  the wrapper; keep the paper's masking rule.
- EPyMARL: masking works in the learner (`basic_controller.py` sets masked logits to -1e10; `multinomial` and
  `epsilon_greedy` selectors honour `avail_actions`, `soft_policies` does NOT). Its Gymnasium adapter `gymma.py`
  returns all-ones masks and never queries the env. So option A needs a custom adapter either way. Default to
  option B (own masked IPPO) and treat EPyMARL as optional.

### Observation

- Global on small = 228 floats: self first, then others in id order, then 2 flags per shelf (present, requested).
  Layout therefore depends on agent id. Coordinates are raw grid ints because `normalised_coordinates` lands in the
  `msg_bits` positional slot of the base class and is silently ignored. No stuck, busy, clash or direction state.
  "Partial" is role-based, not spatial: pickers get no shelf or request info.
- Wrapper must: normalise coordinates, optionally append per-agent stuck counter / `fixing_clash` / `busy`, and keep
  the request queue visible. A learned dispatcher cannot reassign away from stuck robots otherwise.

### API facts

- `reset()` returns obs only (W:661). `step()` returns `terminated is truncated` (same list, W:686-699). Episode ends
  only at `max_steps` (500 registered, W:682-688). Agents spawn on random highway cells with random directions.
- Action index 0 = no-op; 1..6 goals; 7..102 rack slots on small (W:237-251). Action is read only when `not busy`
  (W:363-371); otherwise the stored path is followed.
- `full_registration()` in `__init__.py:47-66` is broken (5-tuple into 4 names, unknown `sensor_range` kwarg). Only
  the normal registration loop is live.

### Bugs in our scripts

- `scripts/record_episode.py:29-30`: `tx, ty = id2xy[target]` but `id2xy` values are (row, col), while agent `x, y`
  are (col, row). Targets are swapped relative to positions. Invisible so far because all recorded targets are null.
- `scripts/baseline_fifo.py:38`: assumes `results/` exists (no mkdir). `global_return` includes the -0.001 penalty and
  is not comparable across agent counts.
- Heuristic edge cases that can raise: `in_pickers_zone.index(True)` (H:119) if a location is in no zone; `argmin`
  over an empty slot list (H:105); unreachable items (path length 0) win the `argmin` (H:72-73).

### Literature verdicts per idea

| Idea | Closest prior work | Verdict |
| --- | --- | --- |
| Learned dispatcher vs CTA | Krnjaic 2023 (+24-28%, IAC); RTAW ICRA 2023; Zhu et al. 2502.07332 ("planner swap dominates, assigner tuning ~3%") | Reproduction. Keep as learned baseline only |
| Learned stuck recovery with abandon / re-dispatch / call-human | Müller 2025 dissertation (RL deadlock handling vs rules, no task-level options); "Should I Replan?" 2604.25567 (learned replan trigger, one-shot, 5-25 agents) | Partial gap. Preferred |
| Disturbance + density sweeps | No taxonomy or benchmark for this env family; LoRR 2026 delay model; Amazon ESC 2608.21533 (one station-outage disturbance) | Open as an evaluation contribution. Build first |
| Dispatcher vs router ablation | No clean ablation on an open env; indirect: GRAND (+22% from scheduler at fixed planner), PUSH-LNS (+25-300% from planner) | Open, cheap here (`care_for_agents` toggle + density) |
| Realistic demand | Mendeley pf2w725pw3 (CC BY 4.0, anonymised and randomised); KIT order-picking instances (radar.kit.edu, 2026, article-occurrence probability parameterised) | Input axis, not a result. KIT preferred. Fold into sweeps, optional |
| LLM dispatcher | Chen/Koenig/Dilkina TMLR 2025: seconds per step, collapse past 8 agents | Drop |
| Traffic-rule evolution | GGO IJCAI 2024 (+9-18% at 88-600 agents), online GGO AAAI 2025, MGGO 2026; CMA-ES budgets 10k+ evals | Conditional: only if density sweep shows a knee at <= 16 AGVs, then a ~1k-eval (1+lambda)-EA on aisle directions |
| RL steering the planner | PRIMAL3, RL-RH-PP (learned PIBT priorities, crowded); learned replan trigger thin | Narrow to "learned replan / yield trigger inside `resolve_move_conflict`", after recovery |

### Expected outcomes and gaps (2026-10-10, expectations not measurements)

Expectations:
- S1: random loses to CTA by a wide margin. Likely eval config: 2,000 to 5,000 steps or 30+ seeds to resolve 5%.
- S2 density: throughput rises, flattens, falls. Knee on medium guessed at 12 to 20 AGVs (baseline already logs ~40
  clashes at 8). Breakdowns hurt more than linearly: a frozen robot loses its own time and blocks an aisle, and CTA
  keeps the order assigned to it.
- Ceiling on any recovery gain = fraction of robot-time spent stuck at a plausible failure rate. If that is 5%, no
  recovery policy gains more than ~5% pick-rate. S2 answers this before any training.
- S3 most likely: rule ~ learned, both beat timeout modestly. Learned beating a tuned rule by a detectable margin:
  roughly one in three. Still a valid write-up if the sweeps are clean.
- S4: +10 to 25% over CTA if training converges (paper: +24% with IAC). Risk is plumbing and compute, not science.
- Dispatcher-vs-router ablation via the `care_for_agents` flag will show a small difference; clashes replan anyway.
  A real ablation needs a second planner (PIBT port), out of scope.

Gaps found in the review, now folded into S2 and S3:
- Stuck-aware CTA baseline (never assign to a frozen robot, re-dispatch abandoned orders at once). Mandatory. Without
  it, a learned gain under disturbance may just mean "knows which robots are frozen".
- Abandon requires re-dispatch: CTA retains missions, so an abandoned task is re-attempted by the same robot.
- Picker unavailability (breaks, zone changes) added to the disturbance taxonomy.
- Common random numbers: same seeds and same disturbance schedule across policies; report paired differences.
- Tuned-threshold timeout baseline (sweep the 5/15 thresholds). Cheap and honest.
- Held-out failure rates for the learned recovery policy (train at 3 rates, test between and beyond).
- Cost of "call human" is a free parameter: sweep it, report the curve.
- Startup transient: random spawns, empty hands. Use longer episodes or discard a warm-up window.
- Realism limits to state up front: grid moves, no kinematics, no batteries or charging, unlimited shelf capacity,
  "stuck" modelled as a freeze (symptom, not cause). Relative comparisons only.

## Where to focus (decision log, 2026-10-10)

Motivating scenario: a company whose warehouse robots "get stuck". Question: how to model that without their data.

Three layers of decision, and RL can sit in any of them:

| Layer | Decision | TA-RWARE today | Where learning can go |
| --- | --- | --- | --- |
| Dispatcher | which shelf, which station, which empty slot | RL or CTA | sees stuck robots only if the wrapper adds that state; can learn to reassign away from frozen robots and jammed aisles |
| Router | which cells to drive through | A* per robot, replan on clash | steer the planner, do not replace it: learned yield / replan triggers, learned edge weights |
| Recovery | what to do when blocked | replan after 5 still steps, drop task after 15 (`resolve_stuck_agents`), 4-step clash cooldown | small policy on stuck events: wait / back off one cell / reroute via another lane / abandon task and return shelf / call human. ~5 actions, sparse events, tractable |

Reasoning that led to "core first, then recovery":
- Disturbances are exogenous and the env has none. Clashes and stucks exist but are endogenous and already
  recovered by the env (baseline: 10 to 15 clashes, 0 to 1 stuck per 500-step episode on small). A disturbance layer
  is needed for any robustness claim.
- You do not need the client's logs. You need their failure taxonomy and rough rates, then sweep each knob over a
  plausible range and report curves, not points. Results are relative (policy A vs B under disturbance X), never
  absolute.
- The density sweep (fixed map, 2 to 16 AGVs, CTA only) needs no assumptions and shows the congestion collapse
  point. Run it first. Nobody has published this curve for the RWARE family.
- Breakdowns and blocked cells hurt every dispatcher about equally; the dispatcher only wins on demand bursts and
  density. Pure breakdown recovery is a routing/recovery-layer problem.
- Recovery has the smallest action space and the clearest client story. Its default baseline (the env's timeout) is
  a low bar; a hand-written recovery rule MUST be in the comparison or the result is hollow.
- Replacing A* with a learned planner is the option to avoid: the learned-planner literature is crowded and runs at
  hundreds of agents on GPUs.

Disturbance taxonomy to implement (Sprint 2):

| Disturbance | Model | Knobs | Implementation |
| --- | --- | --- | --- |
| Robot breakdown / battery swap | agent frozen d steps, others route around | rate per robot-hour, duration dist | NOOP before conflict resolution, suppress stuck counter |
| Execution delay | robot skips a move step | LoRR 2026: Bernoulli/Poisson events, uniform/Gaussian duration | same hook as freeze |
| Blocked cell | pallet or human in an aisle, cell impassable d steps | rate, duration, zones | `find_path` mask + NOOP FORWARD into blocked cell |
| Demand burst | request queue 20 -> 40 for a while | timing, size | append to `request_queue` |
| Workstation outage | one goal disabled d steps | rate, duration | remove from `env.goals`, mask |
| Picker unavailability | picker frozen or removed d steps (break, zone change) | rate, duration | same hook as freeze, picker type |
| Fleet density | more AGVs on the same map | count only | env id |
| Demand skew (optional) | Zipf or dataset-fitted shelf popularity | exponent / dataset | override `process_shelf_deliveries` sampler |

Effort estimates (working days, focused; training unattended overnight; unmeasured, +/- 50%):

| Path | Yields | Days |
| --- | --- | --- |
| Harness (S1) | evaluate.py, CtaPolicy, RandomPolicy, metric resolution, throughput | 3 to 4 |
| Disturbances + sweeps (S2) | disturb.py, density + failure curves, dispatcher vs router ablation | 3 to 4 |
| Recovery (S3) | hook + TimeoutRecovery + RuleRecovery + learned policy, curves | 4 |
| Dispatcher reproduction (S4, optional) | masked IPPO vs CTA on medium, clean and disturbed | 4 |
| Write-up (S5) | one page | 2 |
| Total without S4 | | 12 to 14 |

Before the core is finished, if there is a real company: get their failure taxonomy and rates. Everything after
the core is parameterised on that.

## Premises and kill criteria

| Premise | Status | If false |
| --- | --- | --- |
| TA-RWARE installs and steps fast enough for CPU training | Verified 2026-10-09: ~1,700 steps/s small map, M1 Pro (heuristic incl. A*) | n/a |
| Multiple envs can run in parallel | Known 2026-10-10: only via multiprocessing (class-level counters). Steps/s UNMEASURED | Train single-env, longer wall clock |
| EPyMARL can wrap TA-RWARE with action masking | Known 2026-10-10: learner supports masks, Gymnasium adapter does not query the env. Custom adapter required | Option B (own masked IPPO) is now the default |
| RL beats CTA on the medium map within ~5M env steps | Paper: IAC +24% after 10k episodes (~5M steps if 500 each). Plausible but UNVERIFIED for IPPO | Stop at end of S4, write up as negative result |
| Disturbances produce a regime where stuck time matters | UNVERIFIED. Decided by the S2 failure-rate sweep | Recovery is moot; S3 becomes the dispatcher under disturbance |
| Learned recovery beats the hand-written rule | UNVERIFIED | The client takes the rule; write that up |
| Realistic demand dataset is usable | Footwear dataset is CC BY 4.0 but randomised; KIT instances better | Use a Zipf prior and say so |

Known env facts (from source, `vendor/tarware/tarware/`): map sizes tiny (1x3), small (2x3), medium (2x5), large
(3x5), extralarge (4x7); column_height 8; goals = 2 x shelf_columns on the bottom row; episode = 500 steps, 1 step =
5 s (upstream `run_heuristic.py`); action per agent = Discrete(num_locations + goals + 1), 103 on small; global obs on
small = 228 floats; request queue 20 (tiny/small/medium), 40 (large), 60 (extralarge); requests uniform over shelves.

## Sprints

Each sprint has a coding half and, where relevant, a training half. Exit criterion is a thing that runs, not a doc.

### Sprint 0: foundation (done 2026-10-09)

- [x] Repo, venv, TA-RWARE and its A* dependency built on macOS (`scripts/setup.sh` records the two gotchas)
- [x] CTA baseline, 10 seeds, small and medium (README table, `results/fifo_*.json`)

### Sprint 1: evaluation harness (coding, 3 to 4 days)

Goal: one command that scores any policy on the same seeds as CTA, with confidence intervals, and prints the delta.

- [ ] Rename: FIFO -> CTA in README, scripts and result file names (keep old JSON, add a note)
- [ ] `src/warehouse_rl/env.py`: Gymnasium-compliant wrapper over `Warehouse`. `reset -> (obs, info)`,
      `info["action_mask"]` from OUR mask function (paper's rule, no aliasing), per-agent rewards as a list, optional
      global sum, normalised coordinates, optional stuck/busy/clash features, `max_steps` configurable. Separate
      `np.random.Generator` for anything the wrapper draws. Thin, no logic changes to the env
- [ ] `src/warehouse_rl/policy.py`: `Policy.act(obs, masks, info) -> list[int]`. `RandomPolicy` (masked) and
      `CtaPolicy` (adapter over `tarware.heuristic`, guarded against the three edge cases above)
- [ ] `scripts/evaluate.py --policy <name> --env <id> --seeds 0-29 --steps 500`: writes
      `results/<policy>_<env>_<steps>.json`, prints mean, SD, 95% CI, delta vs CTA with CI
- [ ] Regression test: `CtaPolicy` through the harness reproduces `baseline_fifo.py` exactly on seeds 0-9 at 500 steps
- [ ] Metric resolution: run CTA on medium at 500 / 2000 / 5000 steps x 30 seeds, pick the eval config that makes a
      5% effect detectable, record the minimum detectable effect in the README
- [ ] Throughput test: 8 envs via multiprocessing; record steps/s in the README
- [ ] Fix `record_episode.py` target coordinate swap; mkdir in scripts
- [ ] README: medium map as headline row, CI column, paper's CTA number alongside

Exit: `evaluate.py --policy random` and `--policy cta` both run; random is worse than CTA outside the CI; README has
the resolution decision.

### Sprint 2: disturbance layer + sweeps (coding, 3 to 4 days, CTA only, no training)

Goal: a config-driven disturbance layer and the curves nobody has published for this env.

- [ ] `src/warehouse_rl/disturb.py`: `DisturbedWarehouse(Warehouse)` subclass implementing the taxonomy table above,
      behind a config dict. Order: breakdown (freeze) and execution delay (LoRR model) first, then blocked cell,
      demand burst, station outage. Own RNG. Freeze applied before `resolve_move_conflict`; stuck counters suppressed
      for frozen agents. Unit test: two agents never share a cell under heavy freezing
- [ ] Metrics added to `info`: stuck-time (steps with counter > 0), abandoned tasks, time-in-clash, per-agent
      delivered count, fraction of robot-time frozen (the recovery ceiling)
- [ ] Common random numbers: disturbance schedule is a function of (seed, config) only, identical across policies.
      `evaluate.py` reports paired differences vs CTA, not just means
- [ ] `StuckAwareCtaPolicy`: CTA that never assigns to a frozen or stuck robot and re-dispatches abandoned orders at
      once. Mandatory baseline for everything under disturbance
- [ ] Warm-up: eval discards the first W steps (W decided in S1) or uses long episodes; state which in README
- [ ] `scripts/sweep.py`: (a) density 2..16 AGVs on medium map, pickers at AGV/2, CTA; (b) breakdown-rate sweep;
      (c) delay-probability sweep; (d) dispatcher-vs-router ablation: CTA with `care_for_agents` False vs True on
      assignment, across density. Plots to `results/` following `dataviz` conventions, CI bands
- [ ] Record one disturbed episode with `record_episode.py` for the replay viewer
- [ ] README: collapse curves, ablation, one paragraph on what "robots get stuck" means in this sim

Exit: curves in README, including CTA vs stuck-aware CTA. Decision point: at what failure rate does stuck-time
exceed, say, 10% of robot-time? If no plausible rate gets there, recovery is moot and Sprint 3 becomes "dispatcher
under disturbance" instead. Also record how much of the disturbance loss the stuck-aware CTA alone recovers.

### Sprint 3: recovery policy (coding 2 days, training 2 days). Preferred.

- [ ] `RecoveryHook`: subclass override of `resolve_stuck_agents` and the blocked-agent branch of
      `resolve_move_conflict`. On a stuck/clash event, build a local observation (stuck counter, fixing_clash,
      neighbour occupancy, own target distance, carrying flag, queue pressure) and ask `RecoveryPolicy.decide` for
      one of {wait, back off one cell, reroute via other lane, abandon and return shelf, call human}. "Call human"
      = instant unstick with a fixed time cost (parameter)
- [ ] `TimeoutRecovery`: reproduces the env default (5-step replan, 15-step abandon) through the hook. Regression test
      against the unhooked env on seeds 0-9
- [ ] `TunedTimeoutRecovery`: sweep the replan and abandon thresholds (5/15 today); best point is a baseline
- [ ] `RuleRecovery`: hand-written back-off-then-reroute-then-abandon with tuned thresholds. Mandatory
- [ ] Learned: DQN or PPO over the local observation, trained under the disturbance layer at 3 failure rates,
      3 seeds each. Reward: delivered lines minus stuck-time penalty minus call-human cost
- [ ] Re-dispatch on abandon is REQUIRED (use `StuckAwareCtaPolicy` as the dispatcher for all recovery runs);
      otherwise CTA re-attempts the abandoned task with the same robot
- [ ] Sweep the "call human" cost; report the curve, not one point
- [ ] Held-out evaluation: train at 3 failure rates, evaluate at rates between and beyond
- [ ] Report: stuck-time and pick-rate vs failure rate and vs density, three recovery policies, CI over seeds

Exit: curves. Kill: learned recovery does not beat `RuleRecovery` outside the CI; the client takes the rule, write
that up.

### Sprint 4: dispatcher reproduction (optional, coding 2 days, training 2 days)

Only if S3 produced a result and there is time, or if the S2 decision point kills recovery.

- [ ] Compact masked IPPO in PyTorch, shared actor-critic with agent-type embedding, multiprocessing envs. EPyMARL
      only if the custom adapter is under a day
- [ ] Medium map, target the paper's +24% over CTA. Reward shaping ablation: raw vs per-step penalty vs distance bonus
- [ ] Evaluate best checkpoint through `evaluate.py`, clean and under the S2 disturbance configs

Exit: table RL vs CTA vs random, medium map, CI. Either direction is a valid exit. Kill: after 5M steps and one
shaping pass, RL is within the CI of CTA.

### Sprint 5: write-up (2 days)

One page: the collapse curves, the ablation, the recovery comparison, honest caveats. Negative or positive. Candidate
for the portfolio showcase set. Caveats to state: relative results only; grid moves, no kinematics, no batteries,
unlimited shelf capacity; "stuck" is a freeze (symptom, not cause); failure rates are swept, not measured.

### Dropped or conditional

- LLM dispatcher: dropped. Expected to be a slow negative result; the literature already shows it.
- Traffic-rule evolution: conditional on the S2 density curve showing a knee at <= 16 AGVs. If so, a ~1k-eval
  (1+lambda)-EA over aisle directions with CTA as evaluator, 1 to 2 days.
- Realistic demand: folded into S2 as an optional axis (Zipf first, KIT instances if time). Not a sprint.
- Agent-exam packaging: after S5, if the harness is clean.
- Hybrid RL-steers-planner: narrowed to a learned yield/replan trigger inside `resolve_move_conflict`, after S3.

## Compute and timing

Everything above is CPU on the M1 Pro. The step-rate number is measured; parallel throughput and run times are
estimates until Sprint 1's throughput test. No GPU, no cloud, no JAX rewrite unless Sprint 4 is throughput bound.

### Compute profile for the shared-laptop scheduler (2026-10-10, estimates unless marked)

The laptop (M1 Pro, 10 cores, 16 GB unified memory) is shared with `~/code/Michiel-DK/agent-sandbox`, whose exam
snapshots run local Ollama models on the GPU for hours and cannot share the machine with another model. An operator
scheduling agent decides when and which queue runs. Facts it needs from this repo:

- Nothing here uses the GPU or Ollama. All load is CPU + a little RAM. Co-running beside a GPU exam block is
  possible if RAM headroom allows and the worker count is capped (suggest <= 4 workers during a GPU block, 8 when
  the machine is free).
- Measured: one medium-map 500-step CTA episode = 0.68 s on one core (~735 steps/s). Small map ~1,700 steps/s.
- Per-process RAM: UNMEASURED, expected 100-300 MB per env worker; 8 workers ~1-2 GB. Training adds a small
  PyTorch policy, < 1 GB.

| Job | Cores | RAM | Duration (est.) | Exclusive? | Needs go? |
| --- | --- | --- | --- | --- | --- |
| S1 regression + metric-resolution run (CTA, medium, 30 seeds x 3 lengths) | 1-4 | < 1 GB | 5-10 min | no | no, dev work |
| S1 throughput test (8 workers) | 8 | ~2 GB | 5 min | prefer idle machine (it is a measurement) | no |
| S2 sweeps (density x failure x 30 seeds x 2-3 policies, ~7M steps) | 4-8 | ~2 GB | 20-40 min at 8 workers, ~2.5 h at 1 | no | no |
| S3 recovery training (3 rates x 3 seeds, 1-3M steps each) | 4-8 | ~3 GB | 5-15 h total, splittable per run (~1-2 h each) | no | yes, overnight blocks |
| S4 IPPO training (3 seeds x 5M steps) | 8 | ~3 GB | 3-5 h per seed | no, but wants full cores | yes |

Scheduling rules this repo accepts: training runs are checkpointed per run and can be killed and resumed between
runs; sweeps are embarrassingly parallel and can run at any worker count; nothing here needs an API key or
network. Every long job must write to `results/` incrementally so a kill loses at most one seed.

The gate is `~/code/Michiel-DK/laptop-scheduler` (`python3 -m scheduler plan` before any long run). Its
`queues/warehouse-rl.json` lists the S1-S4 jobs above with placeholder commands. Contract for our scripts: read the
worker count from `SCHED_WORKERS` (default to `os.cpu_count() - 2` when unset), support `--resume`, write results
incrementally.

## Open decisions

- [ ] Portfolio piece or client-facing? Decides whether S2's demand axis uses the public dataset or a WMS export.
- [ ] Add to the GitHub showcase set once S2 has curves, regardless of direction?
- [ ] Eval episode length (decided in S1).

## Tooling notes

- `scripts/record_episode.py` records any episode (agent positions, carrying state, targets, request queue,
  shelves, cumulative deliveries) to JSON. `scripts/replay_template.html` + the JSON = `results/replay_small.html`,
  an animated replay with scrubber and live pick-rate. Target coordinates are swapped (see bugs); fix in S1.
- Published replay (CTA, small, seed 0): https://claude.ai/artifact/4jb8nmT154TrYapGPBxUJ7
- Review summary page (2026-10-10, plain-language gist): https://claude.ai/artifact/33YWuNCVFjQxH3LdYXRbS3

## Sources

- TA-RWARE source, `vendor/tarware`, commit of 2024-08-28, and its paper: Krnjaic et al. 2023, arXiv:2212.11498 (v3)
- pyastar2d fork used by TA-RWARE: github.com/raulsteleac/pyastar2d_TARWARE
- EPyMARL: github.com/uoe-agents/epymarl (`src/envs/gymma.py`, `basic_controller.py`, `action_selectors.py`)
- League of Robot Runners Start-Kit, delay model: github.com/MAPF-Competition/Start-Kit (`Input_Output_Format.md`)
- Müller 2025, MARL for deadlock handling among AMRs: arXiv:2511.07071
- "Should I Replan?" learned replan trigger: arXiv:2604.25567
- Concurrent planning and execution in lifelong MAPF with delay probabilities, AAAI 2025
- Guidance Graph Optimization: arXiv:2402.01446 (IJCAI 2024); online GGO arXiv:2411.16506; MGGO arXiv:2602.23468
- GRAND: arXiv:2512.03194. PRIMAL3: arXiv:2608.04905. Zhu et al. "Rule-Based Systems Matter": arXiv:2502.07332
- LLMs for MAPF: Chen, Koenig, Dilkina, arXiv:2401.03630 (TMLR 2025)
- Footwear order-picking dataset: data.mendeley.com/datasets/pf2w725pw3/1 (CC BY 4.0)
- KIT manual order-picking benchmark instances: radar.kit.edu/radar/en/dataset/mwsv59v8sk9sqaan (CC BY 4.0)

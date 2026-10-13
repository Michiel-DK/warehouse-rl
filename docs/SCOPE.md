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
| RL beats CTA on the medium map within ~5M env steps | Paper: IAC +24% after 10k episodes (~5M steps if 500 each). Plausible but UNVERIFIED for IPPO. Not tested: S4 deprioritised 2026-10-13 | Stop at end of S4, write up as negative result |
| Disturbances produce a regime where stuck time matters | Measured 2026-10-10: half true. Stuck-busy time is >= 10% of robot-time at every rate including 0 (10.7% undisturbed, medium 8 AGV), but disturbances do not raise it; breakdowns add frozen time and stuck-timeout abandonments (2.87 to 9.90 per episode). Not failure: a 7.9% floor already at 3 robots (source UNVERIFIED, likely includes handoff waits) plus 6.4 points from density at 16 AGVs (README "Sprint 2 results") | Recovery is moot; S3 becomes the dispatcher under disturbance |
| Learned recovery beats the hand-written rule | FALSE, kill criterion applied 2026-10-13: three attempts, none near `RuleRecovery` or `timeout` (best greedy eval of the own-credit pilot 35.14 once, 0.0 at its abort at episode 1600, vs timeout reference 50.11; README "Sprint 3 close-out") | Applied: the client takes the rule (`timeout`, the env default, since no rule beats it); written up in README "Sprint 3 close-out" |
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
- [x] README: collapse curves, ablation, one paragraph on what "robots get stuck" means in this sim (2026-10-10: as
      tables from `results/sweeps/*.json`; the PNGs are not committed)

Exit: curves in README, including CTA vs stuck-aware CTA. Decision point: at what failure rate does stuck-time
exceed, say, 10% of robot-time? If no plausible rate gets there, recovery is moot and Sprint 3 becomes "dispatcher
under disturbance" instead. Also record how much of the disturbance loss the stuck-aware CTA alone recovers.

- [x] Exit decision (2026-10-10, README "Sprint 2 results", from `results/sweeps/*.json`, measure
      `stuck_busy_agent_steps`): stuck-busy time is 10.7% of robot-time at breakdown rate 0 and 10.2% to 11.2% at
      every breakdown and delay point, so the 10% line is met at every plausible rate (1 to 2 per robot-hour) and
      recovery stands for Sprint 3. It is not failure: the fraction is flat in the rate (breakdowns show up as
      frozen time, 3.4% to 37.7%). There is a 7.9% floor at 2 AGVs + 1 picker, and density adds 6.4 points up to 16
      AGVs. The floor's source is UNVERIFIED; the measure counts NOOP waits and loading at a goal, so it likely
      includes handoff waits that recovery cannot fix. Point estimate >= 10% at every rate; the per-seed CI
      excludes 10% only at rate 1. Stuck-aware CTA
      recovers none of the breakdown loss (-21% to +3% of it; the only paired CI that excludes 0 is a loss at rate
      1). Open for the operator: whether recovery under congestion alone is still the Sprint 3 question.

### Sprint 3: recovery policy (coding 2 days, training 2 days). Preferred. CLOSED 2026-10-13 (kill criterion applied)

- [x] `RecoveryHook`: subclass override of `resolve_stuck_agents` and the blocked-agent branch of
      `resolve_move_conflict`. On a stuck/clash event, build a local observation (stuck counter, fixing_clash,
      neighbour occupancy, own target distance, carrying flag, queue pressure) and ask `RecoveryPolicy.decide` for
      one of {wait, back off one cell, reroute via other lane, abandon and return shelf, call human}. "Call human"
      = instant unstick with a fixed time cost (parameter)
      (2026-10-10, PR #5; `TimeoutRecovery` through it is bit-identical to the unhooked env.)
- [x] `TimeoutRecovery`: reproduces the env default (5-step replan, 15-step abandon) through the hook. Regression test
      against the unhooked env on seeds 0-9
      (2026-10-10, README "Sprint 3 results", `results/recovery/timeout.json`: reproduces the S2 `stuck_aware_cta`
      breakdown rows on all 120 episodes; 51.17 / 47.47 / 42.48 / 33.17 lines/h at rates 1 / 2 / 4 / 8.)
- [x] `TunedTimeoutRecovery`: sweep the replan and abandon thresholds (5/15 today); best point is a baseline
      (2026-10-10, `tuned_timeout.json`: no point beats 5/15 at rates 1 to 2. The best are 3/15 at rate 1, +0.24
      (-1.37 to +1.85), and 8/10 at rate 2, +0.82 (-0.15 to +1.78). 5/15 itself is best at rate 4. Only 3/15 at
      rate 8 excludes 0, +0.86 (+0.19 to +1.54), 1 of 32 comparisons. No single point wins across rates, so the
      baseline stays the default 5/15.)
- [x] `RuleRecovery`: hand-written back-off-then-reroute-then-abandon with tuned thresholds. Mandatory
      (2026-10-10, `rule.json`: no rule beats `timeout` at any rate. The best is 5/10/25 at rates 1, 2 and 8, at
      -0.77 / -0.82 / -0.38, every CI containing 0, and 3/6/15 at rate 4, -2.88 (-4.55 to -1.21). The faster rules
      are significantly worse at rates 1, 2 and 4. The best rule loses an extra 2% to 31% of the breakdown loss and
      recovers none of it.)
- [~] KILLED 2026-10-13. Learned: DQN or PPO over the local observation, trained under the disturbance layer at 3 failure rates,
      3 seeds each. Reward: delivered lines minus stuck-time penalty minus call-human cost
      **Headroom (2026-10-10, README "Sprint 3 results", for the operator's training decision).**
      - The frozen floor is a model: rate-0 pick-rate x AGV frozen share. Above that floor, the env default
        `timeout` leaves -0.25 (-2.28 to +1.78) lines/h at rate 1 and +1.19 (-0.85 to +3.22) at rate 2. Neither
        can be told apart from zero.
      - The rate-8 residual is +2.66 (+0.75 to +4.56), but rate 8 freezes 33% of AGV-time, so it is not a
        plausible operating point.
      - The best rule sits 0.51 / 2.00 lines/h above the floor at rates 1 / 2. That gap is mostly the rule's own
        deficit against `timeout`.
      - **Operator flag:** `RuleRecovery` is below the env default. The kill criterion "beat `RuleRecovery`
        outside the CI" can be passed by a policy that only learns to wait like `timeout`. The bar that
        separates a real gain is `timeout`, and its headroom at plausible rates is within noise. The kill
        criterion is unchanged; it is the operator's call.
      **First run degenerate, trainer fixed (2026-10-11/13, S3D-WARM-START-RECOVERY).**
      - 11 Oct, format v1, rate 1 (`results/recovery_train_v1_degenerate/rate1_seed{0,1}/log.json`, untracked):
        greedy eval pick-rate never above 11.2 lines/h (seed 0, 6400 episodes, finished) and 4.0 (seed 1, 4880
        episodes, killed after a ~7 h laptop stall), against 51.17 for `timeout` at rate 1. Training return rose
        from -85 to -6 with no deliveries: abandon cleared the stuck penalty for free, so the net learned to abandon
        every stuck task. Uniform random exploration gridlocked the map, so deliveries were almost never observed.
        Seed 0 took 7145 s (1.12 s per episode), so 6400 x 9 runs was ~18 h, not the planned 9.6 h.
      - 12 Oct fix (trainer and learned policy only; metric, `evaluate.py`, hook and env unchanged):
        `ABANDON_COST` 15 stuck-steps per abandon decision; exploration follows `TimeoutRecovery` with
        `random_share` 0.1 uniform random; a timeout reference per run and an abort below 0.5 x reference;
        `FORMAT_VERSION` 2 (v1 checkpoints and run dirs refused); `DEFAULT_EPISODES` 3200 (~9 h for 9 runs).
        Review (laptop-scheduler `reports/wr-lane-s3d.md`, PR #8 refuted 2/3): greedy eval 3.17 at episode 40 vs
        reference 50.11, and the net rerouted at ~95% of stuck events: `_reroute_stuck` resets the StuckCounter and
        the stuck term only counted `count > 0`, so rerouting dodged the stuck penalty for free.
      - 13 Oct operator decision: training reward = deliveries + the real action costs. `STUCK_PENALTY` 0.0;
        `COST_UNIT` 0.01 keeps abandon at 0.15 and an executed call-human at 0.60; abort only from episode
        `abort_after_frac` x episodes (default `EPS_FRAC`). Why: a delivery cannot be faked, every stuck measure the
        recovery action can reset (reroute, back_off, abandon) is gameable, and `timeout` itself reroutes 70-90 times
        per episode, so pricing reroute would punish the reference behaviour. Rejected:
        - per-reroute cost: punishes the timeout rule's own behaviour;
        - "busy and did not move" stuck term: back_off ping-pong dodges it, and it needs `recovery.py`;
        - behaviour cloning on `timeout`: more code, and it does not remove the incentive.
        Probe (README trainer section, `results/recovery_train_smoke/pass2_rate1_seed0/`): greedy eval 1.15 at
        episode 40 vs reference 50.11; the greedy net still reroutes at 1442 of 1461 and 1996 of 2016 stuck events
        (seeds 1000, 1001). The retrain decides whether that changes once exploration has decayed.
      - 13 Oct pm operator decision: per-agent own credit. Each agent's window gets its own entry of the vendored
        per-agent reward (`RewardType.INDIVIDUAL`: +1 to the delivering AGV, +0.1 to the picker
        serving a load/unload, `global_reward=False`, both
        asserted in `make_learned_env`) instead of an equal share of the fleet's deliveries; the two action costs
        are unchanged; `reward_constants()` records `credit: "own"`. Why: the TA-RWARE authors train on individual
        rewards (Krnjaic et al., arXiv 2212.11498, Sec. C4), and one shared team reward is the documented "lazy
        agent" case (Sunehag et al., VDN). The metric is untouched (pick-rate from `info["shelf_deliveries"]`).
        Not adopted: the vendor's constant -0.001 per agent-step is added back, so it is left out of the training reward
        (`vendor_step_penalty: "excluded"`): at a fixed 500 steps it is episode-constant and cannot change the
        ranking of policies. Probe (`results/recovery_train_smoke/rate1_seed0/`): greedy eval 1.44 at episode 40 vs
        reference 50.11; reroute at 1401 of 1427 and 1956 of 1967 stuck events (seeds 1000, 1001). Reported, not
        judged: the one-run pilot (`wr-s3-recovery-pilot`, 3200 episodes with the abort grace) is read before the
        9-run retrain.
      **Killed (2026-10-13).** The own-credit pilot (`results/recovery_train_v2_pilot_aborted/rate1_seed0/log.json`)
      aborted at episode 1600: greedy eval 0.0 vs reference 50.11. Its best interval was 35.14 at episode 240,
      and no later interval was above 8.35. Training return 34.9 -> 4.28 as epsilon fell to 0.05, so the return was
      the timeout prior's, not the net's. Decisions per episode rose from 564 to 1738. Kill criterion applied; the
      9-run retrain is dropped. Curves: `results/recovery_train_curves.png` (`scripts/plot_recovery_train.py`).
- [x] Re-dispatch on abandon is REQUIRED (use `StuckAwareCtaPolicy` as the dispatcher for all recovery runs);
      otherwise CTA re-attempts the abandoned task with the same robot
      (held for every sweep a-e and every training run: `dispatcher: stuck_aware_cta` in every definition and config.)
- [x] Sweep the "call human" cost; report the curve, not one point
      (2026-10-10, `call_human.json`, rule 3/6/15 with H = 14, cost 0/5/15/30/60. The cost is accounting only, so
      pick-rate is identical at every cost. Calling a human never beats `timeout`, even at cost 0: it is
      significantly below it at rates 1, 2 and 4. Against the same rule without a human, it helps only at rate
      1, +1.78 (+0.04 to +3.51). Valuing a human-step as an AGV-step, it stops paying above about 66 steps per
      call. 3/6/15 was the default `--best-rule`, not the best rule found.)
- [~] DROPPED 2026-10-13 with the learned policy. Held-out evaluation: train at 3 failure rates, evaluate at
      rates between and beyond (`scripts/recovery_heldout.py` exists, never run on a real checkpoint)
- [x] S3E informed recovery (added 2026-10-13, Direction change): `blocker_frozen` / `blocker_frozen_left`,
      `InformedTimeoutRecovery`, sweep e (`results/recovery/informed.json`, 30 seeds per (rate, policy), README
      "Sprint 3 close-out"). No paired CI excludes 0 at any rate for either mode. Best at rate 8: informed left,
      +0.43 (-0.20 to +1.07), 2% of the 20.50 lines/h loss. Both modes reroute on nearly every frozen-blocker
      decision, and abandons are unchanged, so this measured reroute-at-once, not abandon-at-once. The learned path does not reopen.
- [~] PARTIAL. Report: stuck-time and pick-rate vs failure rate and vs density, three recovery policies, CI over
      seeds. Done vs failure rate (README Sprint 3 tables a-e, close-out). Not done: recovery vs density; density is
      measured only for the dispatcher (Sprint 2).

Exit: curves. Kill: learned recovery does not beat `RuleRecovery` outside the CI; the client takes the rule, write
that up. **Applied 2026-10-13:** README "Sprint 3 close-out" is the write-up. The rule the client takes is the env
default `timeout` (5/15), because no tuned, rule, call-human or informed variant beats it outside the CI.

### Sprint 4: dispatcher reproduction (optional, coding 2 days, training 2 days). DEPRIORITISED 2026-10-13

Deprioritised behind Sprint 5 (stuck analyser) by the Direction change (2026-10-13). Not scheduled. The original
gate: only if S3 produced a result and there is time, or if the S2 decision point kills recovery.

- [ ] Compact masked IPPO in PyTorch, shared actor-critic with agent-type embedding, multiprocessing envs. EPyMARL
      only if the custom adapter is under a day
- [ ] Medium map, target the paper's +24% over CTA. Reward shaping ablation: raw vs per-step penalty vs distance bonus
- [ ] Evaluate best checkpoint through `evaluate.py`, clean and under the S2 disturbance configs

Exit: table RL vs CTA vs random, medium map, CI. Either direction is a valid exit. Kill: after 5M steps and one
shaping pass, RL is within the CI of CTA.

### Sprint 5: stuck analyser (new direction, 2026-10-13)

A diagnostic tool for a real AGV fleet, per "Direction change (2026-10-13)": where and why robots get stuck, what
precedes a manual reset, and which resets were avoidable. Built against synthetic VDA 5050-shaped logs from this
simulator; the real value needs a client log sample (open operator item). Brief and sprint map S5-S9:
laptop-scheduler `jobs/wr-s5-stuck-analyser.md`. Code under `fleet/`.

### Write-up (formerly Sprint 5)

Folded into the README: the Sprint 2 collapse curves and the Sprint 3 recovery comparison and close-out. A one-page
version is still a candidate for the portfolio showcase set. Caveats to state: relative results only; grid moves, no kinematics, no batteries,
unlimited shelf capacity; "stuck" is a freeze (symptom, not cause); failure rates are swept, not measured.

### Dropped or conditional

- LLM dispatcher: dropped. Expected to be a slow negative result; the literature already shows it.
- Traffic-rule evolution: conditional on the S2 density curve showing a knee at <= 16 AGVs. If so, a ~1k-eval
  (1+lambda)-EA over aisle directions with CTA as evaluator, 1 to 2 days.
- Realistic demand: folded into S2 as an optional axis (Zipf first, KIT instances if time). Not a sprint.
- Agent-exam packaging: after S5, if the harness is clean.
- Hybrid RL-steers-planner: narrowed to a learned yield/replan trigger inside `resolve_move_conflict`, after S3.

## Direction change (2026-10-13)

Learned recovery hit its kill criterion three times (lane D reports; own-credit pilot aborted at episode 1600 with
eval 0.0 against a timeout reference of 50.1). Two of the failures were reward loopholes (abandon, then reroute reset
the StuckCounter the penalty was keyed on); the third was an honest reward with no usable signal: a stuck robot that
sees only its four neighbour cells cannot tell a two-step hiccup from a 50-step breakdown, so wait and reroute look
alike. The headroom table from `results/recovery/*.json` says the prize at rates 1-2 is below the 30-seed noise and
the prize at rate 8 (about a quarter of the lost output on a back-of-envelope) is untouched by every rule family.

Decisions:
- **S3E, informed recovery (lane E):** give the stuck robot the one fact every real fleet manager has, "the thing in
  front of me is a faulted robot" (`blocker_frozen`), plus an optimistic look-ahead variant (`blocker_frozen_left`),
  and measure a hand-written informed timeout rule against `timeout` at rates 1/2/4/8, 30 seeds, paired. This is the
  measured version of the claim "the fix is fault information at fleet level". The learned path reopens only if
  this shows a prize above the CI.
  Definition of the two keys (`RecoveryHook._blocker`, recovery.py): the next cell is `agent.path[0]` (vendor
  `get_next_micro_action` steers toward `path[0]` and `_execute_forward` does `path = path[1:]`; `path[-1]` is the
  target; if `path[0]` is the robot's own cell, `path[1]`). The occupant is any other agent on that cell, AGV or
  picker, busy or not. `blocker_frozen` is 1.0 iff an occupant is frozen for the executing step per `frozen_now()`.
  `blocker_frozen_left` is the number of consecutive True entries of `frozen_schedule[occupant, t:]` from the current
  step t (max over frozen occupants; at least 1 when the flag is set; 0.0 when the flag is 0 or there is no next
  cell). Caveat: `_left` is LOOK-AHEAD, the optimistic "the fleet manager knows the repair time" variant; the flag uses
  only the current step. Both only read `frozen_schedule`; the schedule stays a function of (seed, config).
- **Learned recovery training, held-out eval and its README item: dropped.** The negative result is written up in
  the Sprint 3 close-out with the curves (`results/recovery_train_v1_degenerate`, `results/recovery_train_smoke`,
  `results/recovery_train_v2_pilot_aborted`).
- **Sprint 4 (learned task assignment) deprioritised** behind a new direction, **Sprint 5: stuck analyser**, a
  diagnostic tool for a real AGV fleet (where and why robots get stuck, what precedes a manual reset, avoidable
  resets). Buildable against synthetic VDA 5050-shaped logs emitted by this simulator; the real value needs a client
  log sample, which is the open operator item. Brief and sprint map (S5 structured path + ledger, S6 messy text + typed labeller, S7 Spark/Delta + dbt/Dagster,
  S8 models, S9 deploy/CI/demo, cross-cutting checklist): laptop-scheduler `jobs/wr-s5-stuck-analyser.md`. Code
  under `fleet/` here (private repo), extracted to a public repo in S9; no client data in any repo, ever.

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
- [x] Eval episode length (decided in S1, 2026-10-10): no length detects a 5% effect at 30 seeds; 5000 steps
      needs 572 seeds per policy, 500 steps needs 93. Warm-up: none (W = 0). Table and reasoning in README
      "Evaluation resolution".

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

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

## Mechanism audit: what each disturbance does to a robot (2026-10-18)

Written after the S10 measurement scored the analyser on blocked aisles and outages and found recall 0.05-0.14. Read
this before writing any measurement brief: the truth cell is only worth scoring if robots stall there.

| kind (`disturb.py`) | does the planner know? | what the robot physically does | where the stall message lands (analyser) | StuckCounter / replan | detectable by the stall map? |
|---|---|---|---|---|---|
| `floor` | no (never an obstacle) | move INTO the cell is NOOPed with p_c, retried next step (`resolve_move_conflict`, ENTER semantics) | robot stays one cell before, heading in; `hotspot.py` attributes the stall to the cell in front ("next") = the floor cell, exact | hidden (`_suppressed`): the counter never advances, the robot never reroutes, so the stall repeats for as long as the coins say | yes: long, repeated stalls at one cell (precision@20 0.97) |
| `blocked_cell` | yes: active cells are obstacles in `find_path` (disturb.py:446-470) | a stored path that crosses a cell blocked after planning is NOOPed at the cell before (disturb.py:538, "stored paths ignore the mask until replan") | "next" = the blocked cell | NOT hidden: the vendor counter advances and replans after `_STUCK_THRESHOLD` = 5 steps (warehouse.py:15, 494) with the obstacle known, so the robot goes around | barely: one stall of about 5 steps per robot per window, below or at the detector's `DEFAULT_STUCK_AFTER` = 30 s (6 steps); measured 7/50 windows at K 20 |
| `outage` | yes: the out goal is an obstacle and a blocked target yields an empty path | as `blocked_cell`, plus tasks to that goal are not plannable | "next" = the goal cell, when a stored path still points at it | as `blocked_cell` | barely: 1/20 windows |
| `breakdown` (frozen) | the frozen robot: all actions NOOPed, `errors` BREAKDOWN in its messages. Others: agent positions are obstacles only when `care_for_agents` is true (replans at warehouse.py:464, 497; the macro-action path at 366 uses False) | the frozen robot sits still; followers stall behind it until their own counter replans around it | frozen robot: `faulted_self` at its own cell. Followers: "next" = the frozen robot's cell (`blocked_by_faulted`) | followers replan after 5 steps | the frozen robot's cell is a hotspot for the breakdown duration (20-60 steps). The S10 truth lists robot serials, not cells, so `truth_kinds` scored 0 cells: the fair truth is (cell of the frozen robot, window). Done by S10G (PR #42): 19 of 283 frozen cells on the re-scored map, README (m) |
| `delay` | n/a | random execution skips, NOOP at the current cell, hidden from the counter | current cell, no spatial pattern | hidden | noise source, no truth |
| `burst` | n/a | extra orders, more traffic | wherever congestion forms | normal | no truth cells; the run measures the map's false-alarm floor (about 20 flagged cells per zone per publish on every S10 run) |

Consequences:
- Only `floor` is a planner-blind, recurring, spatially fixed fault, which is exactly what the decayed stall-count map
  is built to find. The S10 blocked and outage runs did not test the analyser; they tested whether robots stall at
  cells they route around. They do not.
- A fair "new blockage mid-shift" test needs a planner-blind blockage: `blocked_cell` with `known: false` (not added
  to the obstacle set, enforced at move time like a floor with p = 1 while the window is open, hidden from the
  counter like a floor so the robot keeps trying), or equivalently a floor cell with a start and an end. That is
  S10C. Both views are defensible for a real fleet: a known blockage is a planned closure, an unknown one is a spill.
- Breakdowns are measurable today if the truth maps each frozen window to the robot's cell at freeze time.
  S10G did this (2026-10-19); README "Sprint 10, closing" (m) has the numbers.
- The 30 s episode threshold in the detector and the vendor's 5-step replan interact: any stall the vendor can
  reroute away from is at most 5 steps and therefore at most borderline for an episode. Floors escape this because
  the layer hides them from the counter. Any future disturbance must say which side of that line it is on.
- The false-alarm floor (about 20 cells per zone per publish regardless of truth) is the analyser's own problem and
  is independent of this audit.

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
| The analyser's hotspot map recovers the floor-imperfection loss when the planner routes on it | NOT SHOWN 2026-10-14: 30 seeds paired, medium map, 80 cells p 0.3-0.7, loss 6.14 lines/h. The map at alpha 4 recovers 15.6% (CI -11% to 45%) and the oracle 22.7% (CI -4% to 50%). Neither CI excludes zero (README "Sprint 8: the closed loop", `results/closed_loop/summary.json`) | Operator's call. Candidates: more seeds, or a traffic-weighted floor draw. The map's information is not shown to be the bottleneck, since the oracle does not clear zero either |
| Realistic demand dataset is usable | Footwear dataset is CC BY 4.0 but randomised; KIT instances better | Use a Zipf prior and say so |

What the persistence comparison (S10D, 2026-10-19, README "Sprint 10" (j)) means for the analyser premise. The
analyser's ranking step is an exponentially decayed stall count. On every floor run it ranks truth cells no better
than the same one-hour count without decay. It is within noise at K 20 on s8b (-0.008, CI -0.020 to +0.005) and on
the 30-zone sticky run (+0.002). It is worse at K 40 on both and at both K on the 3-zone s8e-long run. Its only
"beats" is on outcome precision on s8e-long: 3 zones, graded with the map's own decay. So the ranking value the map
shows on floors (precision@20 0.97) is value a raw recent-stall tally also delivers; the decay adds none that was
measured. The closed loop was not re-run with a persistence-routed arm. On the planner-blind blockage run (the only
blockage run re-scored against persistence) neither forecast is above chance. With no disturbance the map flags about 20 cells per zone at K 20, all false, at the same rate as the
disturbed runs.

Measured answer (2026-10-19, README "Sprint 10" (j) and "Sprint 10, closing" (l), (m); S10H pages): **the map
does not beat persistence.** On truth precision at K 20 it is never better on any of the five runs: 1 worse
(s8e-long), 3 within noise (s8b, sticky, s10c-blind) and 1 with nothing planted (s10-none). The one "beats" is on
outcome precision on s8e-long (3 zones, graded with the map's own decay), so the statement is scoped to truth
precision. The ranking step is therefore not the asset. The working framing is that the detector and the grading are
the asset. The S10 runs support the grading half: every forecast is checked afterwards against the truth and the
outcome. That loop measured the map against persistence and the S10F gate's trade. On the undisturbed run,
forecasts per zone per publish fell from a mean of 15.46 to 0.02 (baseline) and 0.06 (persistence), max 1. On the
blind run, 1 of 50 blocked cells was hit (l). The stuck-robot detector was not re-measured in S10. Its numbers
are the Sprint 5 benchmark (README "Sprint 5": batch recall 0.698, strict precision 0.216, mostly a definition
gap). The S10G
re-score found 19 of 283 frozen cells on the breakdown map (m), against a predicted ~0. The runs still do not test
the lessons at scale or a longer window. Whether the premise stands, narrows to "detector plus grading", or the
analyser changes direction (an ETAS-style background-rate model per `docs/LITERATURE.md`, or stopping) is the
operator's decision.

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
default `timeout` (5/15). No tuned, rule, call-human or informed variant beats it at the plausible rates 1-2. The
only CI-excluding gain anywhere is tuned 3/15 at rate 8, +0.86 (+0.19 to +1.54), 1 of 32 comparisons, about what
chance gives.

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

### Sprint 5 / S5A: fleet state emitter (message contract)

`fleet/emit.py` runs `--zones N` medium-map episodes (zone z = seed base + z, one env per process, disturbance
`breakdown-heavy` or JSON, recovery `timeout`, dispatch `stuck_aware_cta`, built exactly like `evaluate.run_seed`, so
deliveries per zone equal run_seed's) and emits one VDA 5050-shaped JSON line per robot per executed step (steps
0..steps-1, no reset message) to gzip JSONL files (`zone<z>-<nnn>.jsonl.gz`, rotation on line boundaries, gzip mtime 0)
or, behind a flag, Kafka. Every agent is a robot: AGVs and pickers both occupy cells and block each other; the ledger
records the AGV/picker split. `emit_ledger.json` (atomic rewrites) holds the exact message and byte counts per zone and
in total, `expected = robots * steps`, and `complete`/`status`; it is the denominator for every later coverage number.
Key order, one line each: `schema_version` ("fleet-state/1"), `headerId`, `timestamp`, `manufacturer` ("sim"),
`serialNumber`, `orderId`, `lastNodeId`, `agvPosition` {x, y, mapId}, `driving`, `paused`, `errors`, `loads`,
`custom` {stuck_count, carrying, recovery_action, stuck_event, clash_event}.
- `headerId`: per robot, from 0, +1 per message, continuous across file rotation. `timestamp`: `t0 + 5 s * step`
  (`disturb.STEP_SECONDS`), `--t0` default `2026-01-01T00:00:00Z` (byte-reproducible), `--t0 now` for live use.
  `serialNumber`: `Z<zone>-<agent id, two digits>`.
- `orderId`: `""` when the robot is not busy. Every new assignment (not busy -> busy, or busy with a changed target)
  takes a never-used id `Z<zone>-<id>-o<k>` with a per-robot counter k that is never reset; an abandon (busy -> not busy
  without a delivery) gives `""` and the next assignment gets k+1. Keyed on the busy transition read from the env after
  the step, not on `custom.recovery_action`.
- `errors`: `[{"errorType": "BREAKDOWN", "errorLevel": "FATAL"}]` exactly when the robot was frozen in that step
  (`applied_frozen[-1]`, equal to `frozen_schedule[:, t]`), else `[]`. `driving`: position changed in this step.
  `paused` is always false and is not a stuck signal. `loads`: the carried shelf, if any.
- `custom` is the simulator's ground truth and the ONLY place stuck, recovery and clash information appears (the
  contract's own fields errors, orderId, loads, driving excepted). The later detector must never read it; the scorer
  will. `stuck_count`: the StuckCounter after the step. `recovery_action`: the last action decided for this robot in
  this step or null (captured by wrapping the hook instance's `_decide`; decisions are unchanged). `stuck_event` /
  `clash_event`: a stuck / clash decision was made for this robot in this step.

### Sprint 5 / S5B: ingest, stuck detector, ledgers (definitions S5C scores against)

Code: `fleet/fleet_analyser/{parse,detector,ledger,ingest,store,decisions}.py`; thin CLIs `fleet/ingest.py`,
`fleet/ledger.py`. Words kept apart: a *stopped run* and a *stuck episode* are detector concepts over the messages;
`run` in a table column and `--run` is the ingest run name; the env's `StuckCounter` / `stuck_count` is not used here.
Nothing in `parse.py`, `detector.py` or `ingest.py` reads a message's `custom` block: `Message` has no field derived
from it and `custom` is never copied. A test ingests a real emitter run as written and with every `custom` replaced by a
fixed garbage object and asserts identical transitions, episodes and decisions.

**Parse.** Valid = JSON object; `headerId` int >= 0; `timestamp` `%Y-%m-%dT%H:%M:%SZ`; `serialNumber` non-empty str;
`orderId` str; `agvPosition.x/.y` ints; `driving` bool; `errors`, `loads` lists. Reject reasons: `json` (also blank
line), `type`, `missing:<key>`, `timestamp`. Robot identity is the serialNumber, never parsed from `orderId`.
Sequence accounting per robot (last accepted headerId h): headerId <= h is a duplicate (counted, not detected); > h + 1
is a gap (`sequence_gaps` + 1, `missing_messages` += headerId - h - 1) and is processed; a robot's first message with
headerId k > 0 is one gap with k missing. accepted = valid and not duplicate.

**State machine** (per robot, event time only; `STEP_S` = 5, `stuck_after` default 30 s). Messages are processed in
complete (zone, ts) batches: a zone's batch T closes when a message of that zone with ts > T arrives or the zone's input
ends; inside a batch robots are processed in serial order and every cause is decided after the whole batch's states are
known, so the output is independent of in-batch order and of where a read boundary falls.
- Precedence per message: `FAULTED` (errors non-empty) > `IDLE` (orderId "") > `MOVING` (driving) > `STUCK` (in a
  stopped run with ts - since >= stuck_after) > `STOPPED_WITH_ORDER`. `RECOVERED` overrides all of them on exactly the
  message that ends a stuck episode (so an ending message that is faulted or has orderId "" is `RECOVERED`, not
  `FAULTED`/`IDLE`); the next message gets its normal state. A message whose ts does not move forward for its robot is
  skipped.
- Stopped run: consecutive messages with driving false and the same non-empty orderId as the run's first message;
  `since` = ts of the first. A faulted message with the same order and driving false continues the run (the clock does
  not stop for the robot's own fault). The run ends at the first message E with driving true or a different orderId
  (including ""); if E has driving false and a non-empty order it starts the next run.
- Stuck episode: opens at the first message of the run with ts - since >= stuck_after (`T_entry`);
  `episode_id = "<serial>@<since ISO>"`, start = since, cell = (x, y) of the run. It closes at E with end = E.ts,
  `duration_s` = end - start. Runs shorter than stuck_after produce nothing.
- Cause, decided once at `T_entry` from the same zone's batch, first match: `faulted_self` (own message faulted) >
  `blocked_by_faulted` (another robot faulted, Manhattan distance <= 1; `blocker` = lowest serial, `blocker_faulted_s` =
  T_entry minus the ts its consecutive faulted streak began) > `blocked_by_stuck` (a neighbour whose state at T_entry
  is `STUCK`; `blocker` = lowest serial) > `traffic` (a neighbour, none faulted or stuck) > `unknown`.
- Resolution, first match: `order_dropped` (E.orderId differs from the run's, including "") > `fault_cleared` (the
  robot's own last run message was faulted; E is driving with the same order) > `moved`. An episode still open when the
  zone's input ends closes with end = the robot's last ts and resolution `unresolved`.
- Avoidable (literal): cause `blocked_by_faulted` AND resolution != `unresolved` AND `duration_s > stuck_after`;
  `avoidable_s = duration_s - stuck_after`. With 5 s steps every closed episode has duration_s > stuck_after, so the
  duration clause never bites; this is the spec's definition and S5C / the operator may tighten it.
- Transitions: one row per state change per robot `(run, zone, robot, ts, from_state, to_state, cell, order_id)`; the
  first message of a robot has from_state `NONE`.

**Decision ledger** (`decisions` table, append-only, modelled on restaurant-brain `BrainDecision`). Columns: id (hex
sha1 of dedup_key), run, decided_at (event epoch s), recorded_at (wall epoch s), kind, subject, claim (JSON string),
claim_version (1), rationale (one line), expected, grade_after (event epoch s), status (`open`), outcome, graded_at,
error, verdict, dedup_key. `dedup_key = "<kind>:<subject>:<episode start ISO>"`: EVENT time, not wall time (a flat-out
replay decides thousands of episodes per wall minute, so wall-time keys collide and re-runs would not be no-ops); this
replaces the sprint text's "decided-minute". `stuck_cause` at T_entry (subject = serial, claim `{episode_id, cause,
blocker, blocker_faulted_s, cell}`, expected null, grade_after = T_entry + 3600); `avoidable_reset` at episode close
when avoidable (claim `{episode_id, blocker, avoidable_s}`, expected = avoidable_s / 60, grade_after = end + 3600).
`record_decision` is a no-op on an existing dedup_key (first write wins, the run column included); `stamp_grade` sets
only status (`graded`), outcome, error, verdict, graded_at, and only from status `open`; a second stamp returns False
and changes nothing. Evidence (`evidence(decision_id, run, zone, lines, line_count, bytes)`): the raw lines of the
decision's zone in arrival order, 25 before the deciding message and the deciding message plus 24 after it, so at most
50 lines (the brief's "25 after" and its "<= 50 lines including the deciding line" cannot both hold; the bound won),
fewer at stream edges; written once the lines after have arrived or the zone's input ended.

**Store.** `Store` interface (`insert`, `upsert`, `select`, `exists`, `update_where`); `MemoryStore` and
`JsonlStore(dir)` (append-only `<table>.jsonl`, upserts and updates appended and replayed on read, last row per key
wins). `--store jsonl:<dir>`, default `fleet/data/<run>/store`. Tables: `transitions`, `stuck_episodes` (upsert by
run + episode_id: a row at T_entry with resolution `open`, replaced at close), `rejects`, `ingest_ledger`
(run, source, minute), `ingest_files`, `ingest_checkpoints`, `decisions`, `evidence`, `state_sample` (every message with
headerId % 50 == 0), and `ingest_runs` (run, glob, emit ledger status/config, `expected_messages`: what `ledger.py
status` needs for coverage).

**File ingest.** Zone files are read strictly in nnn order. A growing gzip is read with `zlib.decompressobj(wbits=31)`;
only newline-terminated lines are consumed; a file is `complete` only at end of stream (trailer and CRC checked). A file
whose size is unchanged for 10 s without end of stream while the emit ledger is absent or not `running` is `failed`. A
file the glob matches but the emit ledger does not list stays `discovered`, and becomes `unlisted` (never ingested) once
the ledger is `complete` or `failed`: stale rotation files cannot push coverage over 1. No emit ledger: every matched
file is ingested. Exit 0 when the emit ledger is `complete` and every listed file is `complete`; 1 on a failed file,
a failed emit run or a listed file missing on disk. Checkpoints: after each chunk's rows are written, `(run, path)` gets
the uncompressed offset, the sequence tracker and a snapshot of the ingest-ledger counters (one row, `cp_seq`
increasing); a restart re-decompresses from byte 0, skips that many bytes and restores the counters from the newest
checkpoint row, so a hard kill (laptop sleep, SIGKILL) cannot leave coverage behind the offsets (lag samples of the
restored minutes are lost). A kill between a chunk's rows and its checkpoint can duplicate that chunk's transitions.
Detector state is NOT checkpointed: after a resume the detector starts empty at the checkpoint offset (the last open
batch before a stop is not detected). Episodes still `open` from the killed process get resolution `interrupted`; an
episode whose stopped run begins at a robot's first message after the resume has `left_censored = true` (start and
duration are lower bounds) and writes no decision, because its dedup_key would not match the original episode's. So a resume can
LOSE decisions (a run censored before its stuck_after threshold is never decided) and one real episode can leave several
rows (`interrupted` + `left_censored`); episode counts that matter must filter on both (S5C reports do).
Retention: kept raw bytes = evidence lines + state_sample lines + reject raws (first 4096 bytes); everything else is
dropped after parsing; transitions, episodes and decisions are always kept. `--source kafka` is S5B2 (below); without
`--bootstrap` it still prints the S5B1 stub line "kafka source: S5B2" on stderr and exits 2 (an S5B1 test pins that line).

**Ingest ledger** (per source and wall minute, upserted every `--ledger-interval` s and at exit): bytes read
(compressed, uncompressed), messages_parsed (valid lines incl. duplicates), messages_rejected, duplicates,
sequence_gaps, missing_messages, messages_accepted, lag_p50_s / lag_p99_s, behind_emitter_s, msgs_per_s, mb_per_s,
bytes_kept, bytes_dropped, backlog_bytes, written_at; `bytes_kept + bytes_dropped == bytes_read_uncompressed` per row.
**Lag-null rule:** lag (wall clock at parse minus message ts, percentiles over the minute's accepted messages) is null
unless the emit ledger config says `t0_mode == "now"`, `rate == "realtime"` and `speed == 1`; otherwise the number is
months or negative and meaningless. `behind_emitter_s` = the emit ledger's latest `last_timestamp` minus the latest
accepted ts (event seconds), null without an emit ledger. **Coverage = sum(messages_accepted) over the run / emit
ledger `total.expected_messages`**, null without an emit ledger; it is the single completeness number. A resumed process
continues the counters of the newest checkpoint (or the run's ledger rows when it has none), so coverage spans processes. `fleet/ledger.py status --run R` prints the last
1, 5, 60 minutes (back from the latest ledger minute) and total, coverage, files per status, episodes per cause and
decisions per kind and status; `plot` writes `ledger.png` next to the store directory.
`emit_ledger.json` config gained `t0_mode` (`now` when `--t0 now`, else `fixed`).

### Sprint 5 / S5B2: compose stack, ClickHouse store, Kafka source, delivery accounting

Code: `fleet/docker-compose.yml`, `fleet/compose.sh`, `fleet/sql/schema.sql`, `fleet/fleet_analyser/{clickhouse_store,
kafka_source}.py`, `fleet/grafana/provisioning/`, `fleet/requirements.txt`; `ingest.py` now has one `Pipeline` (parse ->
sequence -> detector -> store + ledgers) that the file `Ingester` and the `KafkaIngester` share.

**Stack** (`fleet/compose.sh up [service...] | down | reset | status`): Redpanda (Kafka API on host 19092, mem_limit
1.5g), ClickHouse (HTTP on host 18123, 3g), Grafana (host 13000, 512m, `grafana-clickhouse-datasource`, datasource
provisioned from `fleet/grafana/provisioning`; the dashboard is S5C). Host ports: `FLEET_KAFKA_PORT`,
`FLEET_CLICKHOUSE_PORT`, `FLEET_GRAFANA_PORT`. Data lives in Docker named volumes `fleet_redpanda`, `fleet_clickhouse`,
`fleet_grafana` (S5C2 pass 3, 14 Oct: the earlier bind mounts under `fleet/data/volumes/` wedged Docker Desktop twice
on writes; `fleet/compose.sh status` prints the volume sizes, which count toward the 8 GB cap; `reset` removes them). Measured
idle memory of the three containers on 13 Oct: grafana 67 MiB, clickhouse 341 MiB, redpanda 238 MiB.

**ClickHouseStore** (`--store clickhouse://host[:port]/db`, default port 18123; stdlib `urllib`, no client library).
`INSERT ... FORMAT JSONEachRow` / `SELECT ... FORMAT JSONEachRow`; `open_store` creates the database and applies
`schema.sql` (all `IF NOT EXISTS`). Upsert tables (stuck_episodes, ingest_ledger, ingest_files, ingest_checkpoints,
ingest_runs, decision_grades, ingest_consumer_lag) are `ReplacingMergeTree(_ver)` ordered by exactly the key columns
S5B1 passes to `store.upsert` and are read with `FINAL`; `_ver` is a writer-side strictly increasing integer (ns clock,
+1 on a tie), so within one writer the later upsert wins. Insert-only tables are `MergeTree`. Every table has a
`schema_version` column (a DDL default for the table layout, unrelated to the VDA 5050 message field) that `select()`
never returns; `state_sample` has `TTL toDateTime(ts) + INTERVAL 7 DAY` on EVENT time, so replaying files whose t0 is
older than 7 days lets ClickHouse drop those sample rows on merge (use `--t0 now`). `select/exists/update_where` return
what MemoryStore returns for the same call sequence, except row order: insert-only tables come back in insert order,
upsert tables in last-write order. Lists and dicts are stored as JSON text and parsed back. `decisions` is insert-only
(first write wins via the dedup_key check in `record_decision`); `update_where("decisions", ...)` writes the grade to
`decision_grades(id, status, outcome, error, verdict, graded_at)` only if the decision has none, so for a single writer a
decision is graded at most once (check-then-insert is not atomic: two concurrent writers can both stamp), and
`select("decisions")` overlays the grade. Only those five fields can be changed. No other table supports `update_where`.

**Kafka source** (`ingest.py --source kafka --bootstrap localhost:19092 [--topic fleet.state] [--group stuck-analyser]
[--run NAME] [--emit-ledger PATH] [--until-idle S]`; needs `pip install -r fleet/requirements.txt`, imported lazily).
Ingest-ledger source name `kafka`. Auto-commit is off; per batch: lines through the pipeline, derived rows to the store,
one `ingest_checkpoints` row per partition (path `kafka://<topic>/<partition>`, `offset_uncompressed` = the next offset),
the ingest-ledger and `ingest_runs` rows covering the batch, and only then a synchronous commit (at-least-once; a store
error commits nothing). Redelivered messages are duplicates by the sequence tracker: counted in `duplicates`, never
detected twice, so no second decision. Same limit as the file source: detector state is not checkpointed, so the open
(zone, ts) batch and evidence whose after-window has not arrived are not in the store at commit time. `backlog_bytes` is
null for this source; the consumer lag (messages: sum over partitions of high watermark minus position) is written to
`ingest_consumer_lag` with every ledger write and printed by `ledger.py status`. End of input: `--until-idle S` seconds
without a message (default: until SIGINT/SIGTERM). `--emit-ledger` points at the emitter's `emit_ledger.json` (coverage
and the lag rule); without it coverage is null.

**KafkaSink delivery accounting** (S5A trap 5 fixed). Each record carries a delivery callback: `delivered` counts
acknowledged records, `delivery_failed` counts failed callbacks plus what `flush()` returns at close (records whose
callback has not fired). A full local queue (`BufferError`) polls 0.5 s and retries the same record without counting a
second message. The emit ledger's kafka zones and total carry integer `delivered` and `delivery_failed`
(`delivered + delivery_failed == messages` once closed); a kafka zone with `delivery_failed > 0` is not `complete`. File
zones carry null for both.

**Tests.** Unit (in the gate, no Docker, no skips): `fleet/tests/test_fleet_clickhouse_store.py` (a stdlib fake HTTP
server emulates the ClickHouse slice; one store-contract class runs on Memory, Jsonl and ClickHouse; schema.sql is
checked against every table, column and upsert key S5B1 writes) and `fleet/tests/test_fleet_kafka.py` (fake consumer and
producer). Integration, run explicitly and skipped when `docker info` fails: `.venv/bin/python -m unittest -v
fleet.tests.integration_fleet_stack` (real ClickHouse, ClickHouse service only).

### Sprint 5 / S5C1: ground-truth scorer, decision grader, report, alert

Code: `fleet/fleet_analyser/{score,grade,report,alert}.py`, thin CLIs `fleet/{score,grade,report,alert}.py`; `ledger.py
status` gained the countable filter and a grade rollup. Only `score.py` reads a message's `custom` block; `grade.py`,
`report.py`, `alert.py`, `ledger.py` and the CLIs work on store tables, and the isolation test
`test_detector_and_grader_never_read_custom` runs ingest + grade over a real emitter run as written and with every
`custom` block replaced by one garbage object (identical transitions, episodes, decisions and grades).

**Countable episode** (scorer, report, status): `left_censored` false and resolution not `open` / `interrupted`. One
precedence for what is left out: left_censored, then interrupted, then open. The alert is wider: `left_censored` false and
any resolution but `interrupted` (open rows alert at T_entry).

**Truth definition.** A *truth stuck step* is a message t of a robot (not its last) with `driving` false, `orderId`
non-empty and `errors` empty, where the SAME robot's next message has `custom.stuck_event` true (the simulator wanted the
robot to move at step t and it did not; measured 13 Oct on 1 zone x 300 steps: 153 of 156 such steps). A *truth episode* is
a maximal run of consecutive truth stuck steps of one robot with one `orderId`; start = ts of its first message, end = ts
of the message after its last; kept when `end - start >= stuck_after` (6 steps at 5 s). `custom.stuck_count` is not used
(the timeout policy resets it before it reaches 6).

**Matching.** Detected = `stuck_episodes` rows of the run that are countable and not `faulted_self` (those are scored
apart: count, and the fraction whose robot is frozen at the `t_entry` message). A detected and a truth episode match when
they are the same robot and their intervals overlap by more than 0 s (touching is not overlapping). Greedy, one-to-one,
pairs ordered by (robot, detected start, truth start). precision = matched / detected, recall = matched / truth, `null`
on a zero denominator. Unmatched detected episodes are split: the robot is frozen inside the episode (`frozen`), it
overlaps a truth run shorter than `stuck_after` (`short_truth`), else `by_design` (the robot was stopped by design, for
example waiting at a shelf; an episode that overlaps a long truth episode already taken by another match also lands here).
Truth is a lower bound on what a rule-based detector could be asked to find, so low precision here is mostly `by_design`,
not noise; read it with the split.

**`cause_proximity_agreement` (never called accuracy).** For each matched pair the truth class is `clash` when any message
of the robot in [start, end] has `clash_event` true, else `frozen_neighbour` when another robot of the zone with `errors`
non-empty is within Manhattan 1 at any such message, else `other`. The detector's cause agrees when `blocked_by_faulted`
meets `frozen_neighbour`, `traffic` / `blocked_by_stuck` meet `clash` or `other`, `unknown` meets `other`. Caveat, also
written into `score.json`: frozen is public in the message, the simulator does not expose which robot blocks which, and
`clash_event` is a decision event; this measures agreement with a proximity proxy, not ground truth about cause. The
resolution agreement compares the detector's `order_dropped` with "some message of the robot in [start, end] has
`recovery_action == abandon`". `score.json` is deterministic (sorted keys); `results/fleet/*.json` come from the
`wr-s5-benchmark` queue item, not from a lane.

**Grader.** `grade.py` stamps only through `decisions.stamp_grade`; a second run stamps nothing. `now` is the run's latest
transition ts for `--once` (event time) and the wall clock for `--every`; `graded_at` is `now`. A decision is due when it
is open and its episode has a terminal resolution (moved, order_dropped, fault_cleared, unresolved) or is interrupted, or
`grade_after <= now`. A due decision whose episode is missing, left_censored or interrupted grades `inconclusive`. A kind
outside `decisions.KINDS` (Sprint 8's `hotspot_forecast`, `reroute_recommendation`) stays open and is counted as
`skipped_kind`. `stuck_cause` outcome `{resolution, end, blocker_state_at_end, blocker_cleared_at}`, error null:
- `blocked_by_faulted`: confirmed when resolution `moved` and the blocker has a transition out of FAULTED at a ts in
  (t_entry, end]; else refuted when `moved` and the blocker's latest transition at or before end is to FAULTED; else
  inconclusive (confirmed is checked first, so a blocker that cleared and re-faulted before end still confirms).
- `blocked_by_stuck`: confirmed when `moved` and the blocker has an episode whose [start, end] contains t_entry and whose
  end <= this end; refuted when that episode's end > this end; else inconclusive.
- `faulted_self`: confirmed when `fault_cleared`, else inconclusive. `traffic`, `unknown`: inconclusive.
`avoidable_reset` records `{resolution, reset}` with reset = resolution `order_dropped` (the only reset visible in public
data); verdict `reset_happened` or `no_reset`. The detector's `avoidable` is near-tautological at 5 s steps (every closed
`blocked_by_faulted` episode beyond `stuck_after`), so reports label it so; its definition is not changed.

**Report and alert.** `report.py` reads through `Store.select` only, so it runs on both stores; sections: hotspots (top 20
by (zone, cell), ties by zone then cell), episodes per event hour, duration and time-to-resolution (nearest-rank p50/p95),
cause and resolution mix, avoidable (labelled), repeat robots (>= 3 episodes), grades per kind and verdict. No wall-clock
text: the same store gives a byte-identical `report.md`; `hotspots.png` (one heatmap per zone) sits next to it. The alert
prints `<robot> stuck at <x>-<y> for <int(t_entry - start)> s, <cause>` plus the blocker (`(faulted <int s>)` for
`blocked_by_faulted`), skips episodes present at startup unless `--from-start`, and with `--latency-out` appends JSON
lines whose latencies mean something only when the emit config is now / realtime / speed 1. `ledger.py status` counts only
countable episodes, prints `episodes excluded: ...`, and adds `grades last day [<kind>]` lines: verdict counts of graded
decisions with `decided_at >= (latest decided_at of the run) - 86400`, accuracy = confirmed / (confirmed + refuted), `null`
when that is 0. This grade-verdict accuracy is unrelated to the cause figure above.

### Sprint 5 / S5C2: report SQL, provisioned dashboard, results table, benchmark script

Code: `fleet/sql/reports/*.sql`, `fleet/grafana/dashboard.json` + `provisioning/dashboards/fleet.yaml`, `fleet/benchmark.py`,
`fleet/fleet_analyser/bench.py`, `score.py --source kafka`, the `results` table in `fleet/sql/schema.sql`.

**Report SQL.** One ClickHouse query per report section (hotspots, episodes per hour, duration, cause mix, resolution mix,
avoidable, repeat robots, time to resolution, decision grades), parameterised by `{run:String}`, reading upsert tables with
`FINAL` and applying the S5C1 countable filter (`NOT left_censored AND resolution NOT IN ('open', 'interrupted')`) wherever
they count episodes. Percentiles are nearest-rank like `report.py` (`arraySort` and the `ceil(q * n)`-th element, not a
`quantile*` function). `fleet/tests/integration_fleet_reports.py` (explicit run, skipped when `docker info` fails) emits 2
zones x 300 steps on the host, ingests them into a throwaway ClickHouse database, adds one censored, one open and one
interrupted episode, and asserts that each SQL file gives the numbers of its `report.py` section; it fails on a SQL file
without a comparator and runs every dashboard panel query once.

**Dashboard.** Provisioned, not clicked: `dashboard.json` is mounted by `docker-compose.yml` at `/etc/grafana/dashboards` and
`provisioning/dashboards/fleet.yaml` reads that path. Rows `INTEGRATION` (coverage, consumer lag, sequence accounting, ingest
rate, messages per minute, lag p50 / p99), `SIMULATION` (the report SQL files verbatim, `{run:String}` replaced by the
dashboard variable) and `RESULTS` (the `results` table). `test_fleet_dashboard.py` checks the three row titles, that every
panel query names only tables and columns of `schema.sql` (parsed), the datasource uid against `clickhouse.yaml`, and the
compose mount against the provider path.

**`results` table** `(kind, run, key, value Float64, text Nullable(String), loaded_at, schema_version, _ver)`, insert-only.
`bench.load_results(store, benchmark_json, score_json)` writes one row per numeric leaf (booleans, nulls and strings are not
numeric leaves; `key` is the dotted path, list indices included). Kind `benchmark` has run = the commit sha of the benchmark
document, kind `score` has run = the score's run. A reload appends; readers take `argMax(value, loaded_at)`.

**Scorer from Kafka.** `fleet/score.py --source kafka --bootstrap B [--topic fleet.state] [--group fleet-scorer]
[--until-idle 10]` reads the topic from the earliest offset until `--until-idle` seconds pass without a message and scores
exactly as the file source (a unit test compares the two `score.json` byte for byte). It never commits, so every scoring
re-reads the topic.

**Benchmark definitions** (`fleet/benchmark.py [--smoke] [--workers N] [--out PATH] [--force]`; workers: `--workers`, else
`SCHED_WORKERS`, else `os.cpu_count() - 2`).
- *Batch:* 8 zones x 72000 steps x 12 robots on `tarware-medium-8agvs-4pickers-globalobs-v1` = 6,912,000 messages = 100
  simulated hours per zone, about one hour of 5 s state traffic of a ~9,600-robot fleet. Emitted flat out with `--t0 now`
  (the `state_sample` TTL is on event time), then ingested from cold into ClickHouse. The estimate comes from a 1-zone
  200-step probe (bytes per message times the message count); the run aborts before emitting when it exceeds 6 GB
  uncompressed. `gb_per_min_*` and `msgs_per_s` are the ingest's (bytes read and messages parsed from the ingest ledger over
  the ingest wall time); `coverage` is accepted over the emit ledger's expected total.
- *Live:* emitter `--sink kafka --t0 now --rate realtime --speed 1`, 8 zones, 600 s, with the kafka ingester and the alert
  (`--latency-out`) running alongside on a fresh topic per run. It is a latency test (about 19 messages/s), not a throughput
  test. `lag_p50_s` is the nearest-rank median of the per-minute ingest-ledger p50, `lag_p99_s` the largest per-minute p99;
  the alert latencies are nearest-rank percentiles over the latency-file lines flagged meaningful. Then the score is taken
  from the topic with the `fleet-scorer` group. A live leg that fails after the preflight is recorded as `{not_run: reason}`
  and the exit code is 1. The live leg paces one process per zone, so it needs `--workers >= zones` (exit 2 otherwise).
- *Preflight* (one stderr line, exit 2, nothing emitted): inside a Linux container, `docker info`, `confluent_kafka`
  importable, ClickHouse and Redpanda reachable, the 6 GB estimate, free disk at least 3x the estimate, `fleet/data` (what is
  there plus the compressed batch) under 8 GB.
- *Output:* `platform`, `machine` (cores, ram_gb, disk_free_gb, docker_version), `git_sha`, `batch`, `live`; written atomically
  after each leg. A leg already finished for the same commit and definition is skipped on a re-run (`--force` reruns). Every
  number is read from the emit ledger, the ingest ledger rows, the alert latency file or `score.json`; only the wall times are
  timers. The scorer runs before cleanup; a finished run directory keeps `emit_ledger.json`, `ingest_ledger.json`,
  `decision_ledger.json`, `score.json`, `report.md` and `*.png` (the rest of `fleet/data/<run>/` is deleted).
- *Smoke:* `--smoke` runs 2 zones x 300 steps and a 60 s live leg on 2 zones, writes to a tmp path by default and refuses an
  `--out` under `results/`. The real benchmark is the queue item `wr-s5-benchmark`; no lane writes `results/fleet/`.

**Platform rule.** The vendored A* breaks ties differently on Linux, so the emitter and every simulator episode run on the
macOS host `.venv`, never in a container; only Redpanda, ClickHouse and Grafana run in Docker. The benchmark records
`platform.platform()` and `platform.machine()` and refuses to run inside a Linux container. Its numbers are macOS-arm64
numbers.

### Sprint 8: the closed loop. CLOSED 2026-10-14 (claim: "it does not", at 30 seeds)

Brief: laptop-scheduler `jobs/wr-s5-stuck-analyser.md` "Sprint 8". The analyst finds the bad floor, the planner
avoids it, and reality grades both. Results are in README "Sprint 8, analyst half" and "Sprint 8: the closed loop".

- [x] S8A `floor` disturbance preset (PR #12, f694d49). Severity curve, 30 seeds. The Sprint 8 regime is 80 cells,
      p 0.3-0.7, an 11% loss.
- [x] S8B hotspot -> cost map (`fleet/costmap.py`, PR #16, 56dc46c). `hotspot_forecast` decisions go to the
      ledger, which grades them against outcome and truth. Precision@20 is 0.965 and recall plateaus at 0.56.
- [x] S8D rank grading (PR #18, 274e20f). Rank grade 120 ok / 80 off. The count grade is kept as `outcome_count`
      (136 / 306).
- [x] S8C cost-aware router (PR #19, 99d526e) and `wr-s8c-closed-loop-measure`, 30 seeds paired, alphas 2/4/8,
      headline alpha 4 fixed in advance. The map at alpha 4 gives +0.96 lines/h (CI -0.72 to +2.64), share 15.6%
      (CI -11% to 45%). The oracle gives +1.39 (CI -0.36 to +3.15), share 22.7% (CI -4% to 50%). Neither is
      distinguishable from no map.
- [x] S8-REPLAY offline replay page (PR #20, 998cb21), `docs/replay/index.html`. Not yet checked in a browser.
- [ ] NOT BUILT: `reroute_recommendation` decisions. No code writes the kind, and it stays outside
      `decisions.KINDS`. The router changes paths, but the ledger does not see it.
- [ ] NOT BUILT: the context-layer registry (`fleet/context/<layer>.py`, one contract per layer). `floor` is
      wired directly into `disturb.py`, `costmap.py` and the router.
- Open:
  - The ingest -> costmap -> grade order is unenforced.
  - The comment at `fleet/sql/schema.sql:300` still calls `outcome` the count grade.
  - The oracle and the analyst map are on different cost scales (oracle p_c in [0.3, 0.7], analyst max 1.0 per zone).

Findings, 2026-10-16 (queue items `wr-s8c-dose-response`, `wr-s8c-long-shift`, `wr-s8m-guidance-tune-run` and
`wr-s8m-guidance-heldout`; numbers in README "Sprint 8: sticky floor routing", printed by `scripts/sprint8_tables.py`):
- **Dose-response.** The map's benefit depends on how sticky the floor is and on alpha. At alpha 4 the map recovers a
  share that is above zero from p 0.6 up, and the share shrinks as the floor gets stickier. Alpha 32 is clearly worse
  than no map at p 0.3-0.7 and beats no map from p 0.8 up. The headline regime p 0.3-0.7 remains "does not".
- **Longer shift.** Running the sticky regime at 1,500 steps instead of 500 shows no growth in the map's share.
- **Guidance tuning (S8M).** On held-out seeds 10-29 the tuned map->weight transform beats no map and beats the identity
  transform (alpha 4). It is within noise of the fixed alpha-32 map, with a lower point estimate, so it is not shown to
  beat a plain high alpha on a sticky floor.

Findings, 2026-10-16 evening (alphas 8/16 at p 0.6-0.9 and p 0.8-0.95, guidance tuning on p 0.8-0.95, S8P time to
detect, S8S lesson_persist chance; README "Sprint 8: sticky floor routing" (a), (c), (d), (e), printed by
`scripts/sprint8_tables.py`): no one fixed alpha is best across regimes. Alpha 4 has the top mean at p 0.3-0.7 and
p 0.6-0.9, alpha 32 at p 0.8-0.95 and p 0.9-0.99, and at p 0.8-0.95 alphas 4 to 32 are within noise of each other (paired between-alpha deltas). Guidance tuning
on p 0.8-0.95 picked a low alpha that held-out is within noise of no map and worse than fixed alpha 32, the opposite
of the sticky regime, so the tuning search is not shown to beat a fixed alpha 32 on any floor with p >= 0.8. On the
sticky floor the per-zone top-10 map has shown about a third of the true cells by the end of a 500-step shift and
under half by 1,500 steps, most of them early. Floors are static, so this is time to see, not time to react.
lesson_persist sits above its own chance rate at every window (lift 1.6 / 3.0 / 3.6 at 0.2 / 0.5 / 1.0 h). There is
no CI on the lift and the pools are shared, so it is a direction only. The premise row is unchanged and stays the
operator's call.

Next layers, listed with no claims. Each would be a later one-lane addition with the four-part contract (ground
truth preset, blind analyst feature, planner input, graded decision kind):
- aisle congestion by time of day
- human traffic zones (pickers' walking lanes)
- charging-station queues
- dock/door events
- shift changes
- Wi-Fi dead zones (observable as gaps in the ledger)

The learned planner (Sprint 4, parked) comes after this loop shows a gain with the rule-based router. It has not
shown one yet.

### Sprint 10: the analyser on other disturbances (2026-10-18)

Results are in README "Sprint 10", printed by `scripts/sprint8_tables.py` sections (f) to (n). Reports are in
laptop-scheduler `reports/wr-lane-s10a-truth-v2.md`, `wr-lane-s10b-ttd-change.md`, `wr-lane-s11a-explorer.md`,
`wr-dev-s10-readme.md`, `wr-lane-s10c-blind-blockage.md`, `wr-lane-s10d-persistence-baseline.md`,
`wr-lane-s10d-pass2.md`, `wr-lane-s10e-amoc.md`, `wr-dev-s10c-readme.md`, `wr-lane-s10f-false-alarm-floor.md`,
`wr-lane-s10g-frozen-truth-cells.md`, `wr-lane-s10h-persistence-on-pages.md`, `wr-dev-s10f-readme.md`,
`wr-lane-s10i-fast-detector.md` and `wr-dev-s10i-readme.md`.

- [x] S10A truth v2 (PR #36, 46e9872). `fleet-truth/2` blocked/outage/frozen windows, `fleet/truth.py`, and
      `truth_kinds` in `hotspot_score.py`. The stall-share calibration band was unreachable (baseline 0.982), so the
      presets were picked by truth coverage.
- [x] S10 measure (queue item `wr-s10-disturbance-measure`, no PR; results committed in 9970ebe as
      `results/fleet/hotspot_s10-{blocked,outage,breakdown,burst}.json`). In the final map, 4 of 50 blocked cells are
      in the top 20 (7 in the top 40). For outages it is 1 of 20 at both K. The burst run, with no truth cells, has
      195 top-20 false flags. lesson_persist graded 0 lessons: a 0.5 h window needs 3,600 s and the stream is 2,500 s.
- [x] S10B time to detect / clear (PR #38, 6ae3e00; run `wr-s10b-ttd-change-run`, results
      `results/fleet/time_to_detect_{blocked,outage}.json`). At K 20, 7 of 50 blocked windows were detected, with a
      median of 190 s. 2 cleared, 2 were stale at the end and 3 were open at the end. For outages, 1 of 20 was
      detected, and it was open at the end.
- [x] S11A explorer (PR #37, d655d96). "Try it" section over the recorded measurements.
- [x] S10C planner-blind blockage (PR #40, 7bebef4). `blocked_cell` takes `"known": false`: the planner does not see
      the cell, the move is NOOPed and the robot is hidden from the StuckCounter; the schedule is the same as known.
- [x] S10D persistence baseline (PR #39, 02322b1 after a tests-only pass 2). `fleet/baselines.py`,
      `hotspot_score.py --baselines`: persistence top-K, PAI, chance_all / chance_ever, paired zone bootstrap.
- [x] S10E AMOC (PR #41, 85df140). `time_to_detect.py --reference --sweep-k --sweep-cost`.
- [x] Runs (queue items `wr-s10-none-run`, `wr-s10c-blind-run`, `wr-s10d-baselines-run`, `wr-s10e-amoc-run`, all
      exit 0 on 2026-10-19; no PR; results committed in d44ed98, README (h)-(k)). Planner-blind detection at K 20 is
      6 of 50 windows against 7 of 50 known, median 295 s against 190 s. The undisturbed run raises 177.8 false
      flag-publishes per zone-hour at K 20, and every disturbed run is within 3% of it. The map is within noise of
      persistence at K 20 on s8b and sticky and worse at K 40. No K or cost brings the blind miss share below 0.5.
- [x] S10G frozen truth cells (PR #42, 5fe4501). Each frozen window carries the robot's `cell`, `truth_positive`
      scores it, and `truth_kinds.frozen` gains `cells` and `k`.
- [x] S10H persistence on the pages (PR #43, a83c9a4). `replay_export.py --baselines`. The overview and replay
      pages show the persistence number next to every map precision, with a block titled "Does the map beat last
      hour's counts?". It does not on any of the five runs (truth precision).
- [x] S10F false-alarm gate (PR #44, ae299d6). `costmap.py --gate none|baseline|persistence`,
      `--reset-forecasts`, and `gate_grading` in `hotspot_score.py`.
- [x] Runs (queue items `wr-s10f-gate-run` and `wr-s10g-breakdown-rerun`, both exit 0 on 2026-10-19; no PR;
      README (l), (m), and the s10-breakdown rows of (f) and (i)). Undisturbed: forecasts per zone per publish fell
      from 15.46 to 0.02 (baseline) and 0.06 (persistence), max 1. Blind: 16 truth hits of 1,363 became 1 of 5 and
      1 of 9, and 1 of 50 blocked cells was hit. Breakdown re-emit bit-identical: 19 of 89 flagged cells are frozen
      cells (283 in all), and 25 of 488 forecasts are truth hits (was 0).
- [x] S10I fast detector (PR #45, 9417ea2). `fleet/fastmap.py`: a per-cell CUSUM published every 60 s, counting a
      stall in every bin it overlaps (`--count active`), plus `time_to_detect.py --store-suffix`.
- [x] Run (queue item `wr-s10i-fast-run`, exit 0 on 2026-10-19; no PR; results `results/fleet/amoc_fast.json` and
      `amoc_shortmap.json`, README (n)). On the blind run at the defaults (k 1, h 3) the CUSUM detects 2 of 50
      windows at 0.000 false alarms per zone-hour on the reference. The maps detect 3 to 6 of 50 at 59.2 to 451.9,
      and no map row reaches 0, so the two are never compared at the same false-alarm rate. The short-memory map at
      60 s detects the same 6 of 50 as the decayed map at K 20, at 451.9 false alarms against 177.8.
- Open:
  - lesson_persist: s10c-blind and s10-none ran lessons with `--window-h 0.2` and graded 5 and 6 rows (2 and 3
    hot_cell lessons in the `baselines` block), too few to read. Of the four 2026-10-18 presets, only the
    s10-breakdown re-score (0.2 h) graded any: 2 hot_robot lessons, neither persisted.
  - The blind run does not record how many robots reached a blind cell, so a low detection share cannot be split
    into "rarely reached" and "not ranked".
  - `hotspot_score.py` still counts window cells itself instead of importing `truth.py` (S10A deviation 3).
  - The S10F gate ran at one parameter set only, so its false-alarm/recall trade-off curve is not measured. The
    blockages last 60-240 steps (300-1,200 s), not the "60-240 s" of the S10F lane report.
  - Which stalls put the 19 frozen cells on the breakdown map, given that `counted()` drops faulted-episode stalls
    and occupied-cell stalls, was not examined. There is no chance line for frozen cells.
  - S10I: the in-sample (k, h) pairs in the lane report detect more windows, but they need a held-out run. The map
    with the active counting rule (S10I's finding: the map's end-time count cannot see a blockage while it is
    open) was not measured.

### Sprint 12: where the shift goes (2026-10-20)

Results are in README "Sprint 12", printed by `scripts/sprint8_tables.py` sections (o) and (p). Reports: this
repo's untracked `reports/wr-lane-s12a-time-budget.md` and `reports/wr-dev-lit-fleet-management.md`; laptop-scheduler
`reports/wr-lane-s12b-deadlock-gapmap.md` and `reports/wr-dev-s12a-readme.md`. Names follow
`docs/LITERATURE.md` Part 2.

- [x] S12A per-robot time budget (PR #47, 6daac2d). `fleet/timebudget.py`: seven buckets per robot from the stream,
      the detector's own stopped runs, `--stations auto` from the emit ledger.
- [x] Run (queue item `wr-s12a-budget-run`; results `results/fleet/timebudget_{s10-none,s10c-blind,s10-breakdown,
      s8b-medium-80-p03-07,closed-loop-sticky}.json`, README (o)). 1.1% to 1.9% of stall episodes start on a
      station cell. 76.3% to 97.2% start on a shelf-adjacent cell, but that class is 360 cells per zone, so it is
      not a picker-wait measure. Undisturbed AGVs move 40.0% of the time, at 22.18 jobs per AGV-hour. The detector
      is unchanged.
- [x] S12B blocking finder and gap map (PR #46, e8a9bb0). `fleet/deadlock.py`, `fleet/gapmap.py`,
      `emit.py --deadzone`.
- [x] Run (queue item `wr-s12b-run`; results `results/fleet/deadlock_{s10-none,s10c-blind,s10-breakdown,
      closed-loop-sticky}.json`, `gapmap_s12-deadzone.json`, `hotspot_s12-deadzone.json`, README (p)). The
      "deadlocks" are congestion (blocking clusters), with symmetric adjacency, not circular waits. Undisturbed
      108.2 blocked robot-s per robot-hour; sticky 2.78x that. Gap map on 6 planted cells per zone: recall 57/60,
      precision@10 0.57 (ceiling 0.60), synthetic.
- Open (operator):
  - ~~**Exclude station and shelf waits from the stall list?**~~ Stations: answered by S13B (2026-10-21). Station
    waits leave the stall list (detector state SERVICING). On the five simulator runs no map, precision, S10D verdict
    or AMOC number moves; only the station episodes leave the list (README (r)). Shelves: still open. The
    shelf-adjacent class is a 360-cell catch-all, and a tighter shelf signal (a stopped robot with empty
    `nodeStates`) is not built.
  - **"Broke up" includes one-step breaks.** In undisturbed zone 4, one robot pair stands off from minute 19 to stream
    end: 16 clusters, 1,260 s, open at the end, 26.3% of the run's blocked robot-seconds (README (p), standoff
    columns). The "congestion, every cluster resolves" reading needs this exception. Should S12C report standoffs
    (merged clusters) instead of clusters?
  - `same_minute_stops`: should the zone-start minute be excluded and the count reported against the undisturbed
    rate (13 later minutes on s10-none) before it goes on a page?
- [x] S12C literature corrections (PR #48, fdce880): `deadlock` / `knot` renamed `blocking_cluster` /
      `blocking_chain` (schema v2), `faulted` needs error level CRITICAL or FATAL, `paused` and `no_data` buckets.
      Rerun `wr-s12c-rerun`: v2 counts equal v1 on all four runs (results commit 708763b). Time budgets re-run with
      the new buckets: `paused` and `no_data` 0 s on all five simulator runs, every other value unchanged
      (8a17a0b). README (o) and (p) regenerated.
- Open (not fixed): the hotspot scorer's truth hits on dead-zone runs still count dead cells (S12B caveat 1),
  `gap_cell` dedup across zones still collapses rows (3 on s12-deadzone), and `fleet/fleet_analyser/score.py:41`
  still counts any error as frozen (no committed number moves; the emitter writes only FATAL).

### Sprint 13: a real shift (2026-10-20)

Results are in README "Sprint 13", printed by `scripts/sprint8_tables.py` section (q). Reports: laptop-scheduler
`reports/wr-lane-s13a-moroop-budget.md`; data notes in `docs/LITERATURE.md` Part 2b.

- [x] S13A MoRoOp adapter and time budget (PR #49, e5d0808). `fleet/adapters/moroop.py`; results
      `results/fleet/timebudget_moroop.json` and `results/fleet/timebudget_moroop_shifts.json`, README (q). One
      wheel.me AMR, 9 shifts, 0 parse rejects; moving 40.4%, at a station 41.0%, 18.59 jobs per robot-hour; stuck
      1,113 s, 1,107 of them in one shift (30 Jul morning, manual intervention). The robot's stuck label: 0 of
      765 s in the stuck bucket, 2/2 episodes of 30 s or more detected. 542 of 544 false alarms are station dwells.
      No failed-navigation label in the data. One robot, so no deadlock, congestion or hotspot result.
- [x] S13B station-aware stuck rule (PR #50, 5d8d51b) and rerun (queue item `wr-s13b-rerun`; results
      `results/fleet/*-st.json`, commit 2970c17; README (r), printed by `scripts/sprint8_tables.py` section (r)).
      Simulator runs, radius 0: top-20 truth precision, forecast grades, S10D verdicts and AMOC unchanged (asserted
      equal blocks). 4 to 47 station episodes leave the stall list per run, with stuck share unchanged, and blocking
      clusters fall by 3 to 8 per run. MoRoOp, radius 1: stuck runs 567 to 2, unlabelled 544 to 1, label hits 2/2
      kept; but stuck seconds 1,113 to 13 and TIMEOUT overlaps 8 to 1, because the 1,107 s manual-intervention stop
      started within one cell of a station. From README (r) on, the station-aware numbers are the headline.
- Open (operator):
  - **Is a one-robot real log enough to show a client, or do we wait for a fleet log?**
  - ~~**Should a station stop that lasts far longer than a normal dwell count as stuck again?**~~ Answered by S14A
    (2026-10-21): yes. A SERVICING run still stopped at T = min(300 s, exp(Q3 + 3 IQR of ln dwell)) becomes a stuck
    episode with cause `station_overrun` (`docs/LITERATURE.md` Part 4 Verdict 1; T per run from its own station stops).
    Value as the files record it: T = 300 s in all nine MoRoOp shifts (the cap binds) and T = 80 s on all five
    simulator runs (Q1 5 s, Q3 10 s). The 1,107 s stop is back in the stuck bucket (shift 6: 7 s to 1,107 s), as a
    3,245 s `station_overrun` episode. README (s). No other radius was run.

### Sprint 14: station stop bound and traffic absence (2026-10-21)

Results are in README "Sprint 14A" and "Sprint 14B", printed by `scripts/sprint8_tables.py` sections (s) and (t).
Literature: `docs/LITERATURE.md` Part 4. Reports: `reports/wr-lane-s14a-servicing-bound.md`,
`reports/wr-lane-s14b-traffic-absence.md`.

- [x] S14A station stop bound and `cause_label` (PR #51, 95feaaf). `fleet/fleet_analyser/servicing.py`,
      `fleet/fleet_analyser/causes.py`, `Detector(servicing_max_s=...)`, `--servicing-max-s auto` on ingest,
      timebudget, deadlock and the MoRoOp adapter.
- [x] Rerun (queue item `wr-s14a-rerun`; results `results/fleet/*-sb.json`, commit d5b777a; README (s)). Simulator,
      radius 0, T = 80 s: map, precision, grades, S10D and AMOC equal to the `-st` files (asserted). One overrun on
      s10c-blind (265 s) and 25 on the sticky floor (5,365 s, stuck share 32.05% to 32.95%), none on the other
      three. MoRoOp, radius 1, T = 300 s: shift-6 stuck 7 s to 1,107 s (a 3,245 s `station_overrun` episode),
      TIMEOUT overlaps 1/8 to 5/8, unlabelled station-cell stuck runs 0 to 3 (Part 4 bar <= 54), label hits 2/2.
      Causes shares sum to 2.03-4.05 (simulator) and 2.50 (MoRoOp: 4,430 episode s against a 1,773 s stuck bucket);
      stated, not rescaled.
- [x] S14B traffic-absence detector (PR #52, 53fd44f). `fleet/absencemap.py`, `time_to_detect.py` prebuilt detector
      `absence`.
- [x] Run (queue item `wr-s14b-amoc-run`; results `results/fleet/amoc_absence.json`,
      `results/fleet/amoc_absence_a1e-{2,3,4}.json`, `results/fleet/amoc_absence_sweep.json`, commit d5b777a; README
      (t)). Alpha 1e-3 (default) and 1e-4: 0 forecast rows, no AMOC. Alpha 1e-2: 0/50 windows at every K, 18.1 false
      alarms per zone-hour on s10-none at K 20. Map K 20 6/50, CUSUM 2/50 on the same windows.
- **Part 3 Q1 (hidden blockage, `docs/LITERATURE.md` Part 3 "What this means" item 1): absence signal DROP** (recorded
  by the S14 docs job; applying it is the operator's call). Part 4's
  negative bar is met: no alpha of the sweep detects a window, and the CUSUM and map rows of (n) stand. At this fleet
  density too few cells collect 10 passes in one run (lane report). A retest needs a denser fleet or a longer
  history, not another alpha. Detours (Pan et al. 2013) were not built: no planned route in the stream. The
  stall-count floor on the missed windows (Part 3 item 1, last part) was not counted.
- [x] S14C eight-hour shift (queue item `wr-s14c-8h-run`; results `results/fleet/amoc_blind-8h.json`,
      `results/fleet/amoc_fast-8h.json`, `results/fleet/amoc_absence-8h.json`, `results/fleet/hotspot_s10c-blind-8h.json`,
      `results/fleet/hotspot_s10-none-8h.json`; table `scripts/sprint8_tables.py` (u); README "Sprint 14C"). 10 zones x
      5,760 steps, seed base 100, 661 windows. Map K 20 31/661 at 199.4 FA/h on the reference; CUSUM flagged nothing;
      absence 11/661 at 341.2 FA/h, no window shared with the map's 31.
      `amoc_absence-8h.json` was recomputed in the docs job (69b0378): the queue's stub guard
      `grep -q 'detector\":\"absence'` (same for `cusum`) cannot match the escaped quotes inside the claim string,
      so it always writes a stub. It happened to be true for the CUSUM. Fix the queue template in laptop-scheduler
      (operator).
- **Part 3 Q1 after S14C: DROP, on three signals** (recorded by the S14C docs job; applying it is the operator's
  call). With 8 hours of traffic the absence test flags, but it misses 98% of windows at more false alarms than the
  map, and its rate outside windows (236.6) is below the undisturbed reference (341.2). The map at K 10 detects 17 at
  102.2. Part 4's bar to the letter fails against the map (31 windows the other way) and passes against the CUSUM
  (11 to 0, p 0.00049). The CUSUM flagged nothing and the bar caps only the reference's false alarms, so the job reads
  that branch as no evidence; whether it counts is the operator's call (README Sprint 14C). The stall map and the stall
  CUSUM do not find it either. The "longer history" retest asked for above is done. The
  gurren page may not mention early warning of blocked cells.
- Open (operator):
  - Stop the hidden-blockage line here (S14C: drop recorded), or wait for a client log with more traffic per cell?
  - Causes table: keep the episode-seconds share against the stuck bucket (sums 2-4), or report shares of episode
    seconds (sums to 1)?
  - 3 of 8 MoRoOp TIMEOUT operations still overlap no stuck run under the bound; inspect them?

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

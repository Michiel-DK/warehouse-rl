# wr-lane-s8c — S8C-COST-AWARE-ROUTER, pass 4 (14 Oct 2026, night): MERGED

**Result: OK. Pass 4 was a clean round: 0 of 5 refuters refuted. PR #19 was squash-merged and master fast-forwarded.**
- PR: https://github.com/Michiel-DK/warehouse-rl/pull/19, MERGED.
- **Merge sha: 99d526e** on master. The local checkout was fast-forwarded 274e20f..99d526e.
- PR head before the merge: f2f750b, based on origin/master 274e20f. Rebase was a no-op because master had not moved. GitHub CI `gate` SUCCESS, mergeState CLEAN.
- Workflow run wf_d0ed8a21-47a, script `/tmp/s8c/single-lane-build-s8c-pass4.js`, priorPasses = passes 1-3 verbatim. Result saved to `reports/wr-lane-s8c-pass4-result.json`.

## What pass 4 changed
Commit f2f750b touches `tests/test_evaluate.py` only, +18/-10 (`git diff --stat 11f351a f2f750b`).
- `test_seed_base_is_part_of_the_identity` now uses its own map under `self.tmp` with zones '0'..'6' and seeds (5, 6).
  - Base 0 needs zones 5 and 6, base 5 needs zones 0 and 1, base 1 needs zones 4 and 5. All exist, so the missing-zone error cannot fire.
  - The base-5 resume into the base-0 dir is the first refusal. It and the base-1 refusal both use `assertRaisesRegex(ValueError, 'costmap_seed_base')`.
  - The two errors have different messages. The identity message is `"... stores costmap_seed_base ..."`, while the missing-zone message says "seed base" with a space.
  - The explicit-0 resume still succeeds. The stored rows deep-equal the rows from before the refusals. A base-5 run in its own dir records header 5.
- Mutation proof, reproduced independently by the correctness, test-honesty and invariants refuters:
  - With `costmap_seed_base` removed from the `_check_same_costmap` tuple, the test FAILS at `tests/test_evaluate.py` line 311, the base-5 `assertRaisesRegex`, with "ValueError not raised".
  - With the real code: `Ran 1 test ... OK`.
- The setUp fixture is unchanged. No production code changed in pass 4.
- Gate at f2f750b:
  - `tests`: Ran 616 OK, from the builder; the correctness and invariants refuters re-ran it.
  - `fleet/tests`: Ran 312 OK.

## Pass-4 criterion: two pre-review halts before the build (harness lesson applied)
- Following the pass-3 lesson, I ran pass 4 at first WITHOUT `proceedWithCriterion`.
  - Round 1 halted on a letter trap: the range `11f351a..HEAD` breaks if master moves and the builder rebases.
  - Round 2 halted on a quantifier: did "zones under both bases" also cover the own-dir base-5 header run?
- I adopted round 2's complete rewrite of the criterion as written. Then I set `proceedWithCriterion`, because the rewrite resolved both blocking findings.
- Round 3 returned `sound: true` with 4 advisories.

## Criterion (a) no-map regression
Not re-run by the builder, because pass 4 has no production change. Re-run independently at the pass-4 head f2f750b by the regression refuter and the invariants refuter, on darwin, medium map, seeds 0-1, 500 steps, each into a new /tmp dir:
```
(1) breakdown rate 2 + timeout vs results/recovery/timeout.json point 2: 24 common keys/seed, differing [], routes_changed_by_map 0, map_cells_entered 0
(2) cta --disturb none vs cta_tarware-medium-8agvs-4pickers-globalobs-v1_500.json: 6 common keys/seed, differing []
(3) floor-heavy + timeout vs ..._500_floor-heavy_timeout.json: 27 common keys/seed, differing [], new keys 0, 0
```
Every output filename equals master's. The pass-1/2 comparison table is below. The router code is unchanged since pass 1.

## How the weighted grid is built (from the PR)
### Weighted grid (how it is built)
With an active map (non-empty dict) and `cost_alpha > 0`, `DisturbedWarehouse.find_path` returns the A* path on the weighted grid, for every caller (macro-action assignment, vendor replans, recovery reroute, policy distance scoring), with or without active obstacles:
1. The grid is built and binarised to {1, inf} exactly as today (agents, shelves, picker non-highway, obstacles are inf).
2. The start-cell trim flag `1 - int(grid[start] > 1)` is computed on that BINARY grid.
3. Then each map cell `(x, y)` whose binary value is finite gets weight `1 + alpha * cost` at `grid[y, x]`. inf cells stay inf.
4. With no active map, or alpha 0, the code path is the existing one (vendor `Warehouse.find_path` when there are no obstacles, the existing port otherwise); no weighting and no second search.
`routes_changed_by_map` counts, over all find_path queries since the previous step (policy scoring included), those whose weighted path differs from the unweighted one (the only unweighted search, run only when a map is active). `map_cells_entered` counts agent-steps whose cell changed and whose new cell is in the active map (a floor skip is no entry). Both are in every disturbed-env info (0 without a map) and reset at `reset()`.
`cost_map` = None | dict `{(x, y): cost}` (int tuples inside the grid, 0 < cost <= 1) | `"oracle"` (`dict(floor_cells)` re-read after each reset; the only NEW read of `floor_cells`, one commented branch in `DisturbedWarehouse._set_active_map`; an empty floor is no map). `cost_alpha` finite >= 0. Anything else, and a non-None map on `WarehouseEnv` without a disturb dict, raises ValueError. The map never enters the disturb config, so schedules and floor layout are unchanged (tested for breakdown+floor and for an all-types config, no map vs dict vs oracle, 2 seeds).
Weighted lengths also change CTA's assignment distances (it calls `find_path`): expected under "every path search".

**pyastar2d wall/float handling.**
- Walls: pyastar2d takes a float32 grid, with inf = wall and every finite weight >= 1.
- Grid build: the port binarises exactly like the vendor (`grid != 0` -> {1, inf}). Weights `1 + alpha*cost` then go only on cells still equal to 1.
- Trim flag: the vendor's start-cell trim `astar_path[1 - int(grid[start] > 1):]` assumes free = 1, so it is computed on the BINARY grid before weighting. A robot standing on a costed cell would otherwise keep its start cell.
- The fork's cost per move is the weight of the entered cell, plus 1 on a direction change. The turn penalty is skipped when the entered weight is >= 100, i.e. alpha*cost >= 99.
- Visited cells get `+= 100` on the passed array. The port rebuilds the grid on every call, so this mutation is harmless.

**Consequence for the measurement (a planner property, read before any result; stated at the strength measured).**
- Thresholds: in the three hand-built single-cell cases, a sidestep needs alpha*cost > E, with E = 4 (open grid: +2 steps, +2 turns), 6 and 8 (walls beside the cell).
  - The brief's pass-2 note estimated "+4 turns = 6". The measured open-grid E is 4.
  - These are three cases, not a proof that 4 is the lowest E anywhere on the warehouse grid.
- At the headline alpha 4 with an analyst cost of exactly 1.0 (costmap.py normalises each zone's top cell to 1.0), the open-grid case is an exact tie (alpha*cost = E = 4).
  - On darwin the tie goes straight. A* tie-breaks differ between macOS and Linux (docs/PLATFORM.md).
- The smoke shows the map still acts at alpha 4:
  - map_a4 cut floor_skip_steps from 263.5 to 162.5 and changed 108.5 routes per episode.
  - The oracle (alpha*cost <= 2.8, below every measured single-cell threshold) still gained +2.16.
  - It acts through multi-cell runs (k*alpha*cost > E), equal-length alternatives and CTA assignment distances.
- Smoke pick-rates: map_a4 = none = 25.20 (same CI) despite non-zero map counters. This is pick-rate quantisation, not a silent fallback: 1.44 lines/h per delivery at 500 steps, 2 seeds.
- **Oracle is not scale-matched to the analyst map.**
  - Oracle costs are p_c in [0.3, 0.7]. Analyst costs are normalised to a per-zone max of 1.0.
  - At the same alpha, the analyst map can penalise cells harder than the oracle. So map <= oracle is NOT guaranteed, and the README comparison needs that caveat. "Oracle = upper bound" holds for the map's information, not for the penalty scale.


## Smoke summary (pass-1 head; the router and closed_loop code are unchanged in passes 2-4)
### Smoke summary (`scripts/closed_loop.py --smoke`, small map, 2 seeds x 500 steps, 14 s wall)
```
arm            pick-rate              95% CI  delta vs none   share
none               25.20      [16.05, 34.35]              -       -
map_a4             25.20      [16.05, 34.35]          +0.00    0.00
oracle             27.36      [27.36, 27.36]          +2.16    0.25
undisturbed        33.84      [24.69, 42.99]              -       -
```
Means (none / map_a4 / oracle / undisturbed): floor_skip_steps 263.5 / 162.5 / 167.0 / 0; stuck_busy_agent_steps 300 / 265.5 / 285.5 / 360; routes_changed_by_map 0 / 108.5 / 127.0 / 0; map_cells_entered 0 / 177.5 / 155.0 / 0. This is a 2-seed plumbing check, not a result: the CIs are n=2.


## Queue command for `wr-s8c-closed-loop-measure` (S8C is merged, so this is now releasable; NOT released by this lane)
```
.venv/bin/python scripts/closed_loop.py --seeds 30 --steps 500 --alphas 2,4,8 --workers 8 --out-dir results/closed_loop
```
- Settings: medium map, `stuck_aware_cta` + `timeout`, floor regime `{"floor": {"cells": 80, "p": [0.3, 0.7]}}`.
- Order: Phase A (emit -> ingest -> costmap), then the arms none / map_a2 / map_a4 / map_a8 / oracle / undisturbed.
- Headline alpha is 4.0, chosen before any results.
- The item uses 8 workers, so per the operator's announce-big-runs rule it must be announced before release (cores, RAM, duration). Size it from the scheduler's measured minutes; this lane did not measure the 30-seed wall time ⚠️.
- Read the map-vs-oracle comparison with the scale caveat in the grid section above: the oracle's p_c is in [0.3, 0.7], while the analyst's per-zone max is 1.0.

## Pass-4 refuter verdicts (verbatim)
**correctness: survives (high)**
```
VERDICT: survives
LENS: correctness
CONFIDENCE: high
STRONGEST OBJECTION: In the test, the base-0 resume with explicit --costmap-seed-base 0 runs after the two refusals rather than right after the first run. The criterion only requires that base 5 is the first refusal, so this ordering does not break it. No wrong result found.
EVIDENCE:
- Scope: `git diff --stat 11f351a2 f2f750b4` shows that pass 4 changes only tests/test_evaluate.py (+18/-10), with no production code. The PR head f2f750b4 has origin/master 274e20f as an ancestor. The setUp fixture is unchanged; the only hunk is inside test_seed_base_is_part_of_the_identity.
- Zone coverage: the test-local map cm7 has zones '0' to '6' and uses seeds (5, 6). Base 0 needs zones 5 and 6, base 5 needs 0 and 1, and base 1 needs 4 and 5, so all are present. The missing-zone ValueError cannot fire.
- Regex: both refusals use assertRaisesRegex(ValueError, 'costmap_seed_base'). The rows are compared after the refused runs. The separate base-5 run writes into its own directory and records costmap_seed_base == 5.
- m2: in a worktree at f2f750b4, the real code gives `Ran 1 test ... OK`.
- m1: I removed "costmap_seed_base" from the tuple at scripts/evaluate.py:264. The test then FAILS at tests/test_evaluate.py line 311, which is the base-5 `with self.assertRaisesRegex`, with "ValueError not raised". This matches the PR body.
- Gate at the head: tests gives Ran 616, OK; fleet/tests gives Ran 312, OK.
- PR body: it has the m1/m2 runs, the traceback at line 311, the pass-3 correction sentence (base 5 asked for zone '-4' and hit the missing-zone path), and the --stat. All checked on the PR body.
WOULD-FAIL-ON-OLD-CODE: yes. The m1 mutant fails at the base-5 assertion.
REQUIRED FIX: none.
```

**regression: survives (medium)**
```
VERDICT: survives
LENS: regression
CONFIDENCE: medium

STRONGEST OBJECTION: The diff adds two keys to `DISTURB_SUMS`, so every disturbed row now carries `routes_changed_by_map` and `map_cells_entered`. That reaches callers outside the diff: `scripts/sweep.py:95`, `scripts/recovery_sweep.py:149`, `scripts/recovery_heldout.py:134`, `fleet/fleet_analyser/emitter.py:168-174` and `train_recovery`. When those scripts resume into older results files, the new rows have keys the stored rows lack.

Why it is not a refutation:
- Callers do exist. The builder's `existing_callers_touched=false` means none of them was edited, and that is true. No caller needs an edit:
  - `run_seed` only gained trailing keyword parameters with defaults.
  - The job tuples for the no-map path are unchanged.
  - `cm_suffix` is "" without a map, so `base_path` and `cta_path` are the same as on master.
  - `_check_same_costmap` with `want = {}` accepts old files, because `doc.get(...)` returns None for all three keys.
- Adding keys this way follows the S8A `floor_skip_steps` precedent. The one key-set pin, at `tests/test_recovery_heldout.py:150-154`, was updated and asserts the new values are 0.
- `RecoveryHook` (`recovery.py:534`) is the only subclass and does not override `find_path` or `_find_path_with_obstacles`. The new `weights=None` keyword is backward compatible.
- With no active map, `find_path` takes the same branches as master, including `super().find_path` when there are no obstacles. The start-cell trim is now computed before weighting, but it is the same value because the grid is still binary at that point.

EVIDENCE: I re-ran criterion (a) myself at PR head f2f750b, in a separate worktree, on darwin, medium map, seeds 0-1, 500 steps, each run into a new /tmp dir:
- (1) breakdown at rate 2 + timeout vs `results/recovery/timeout.json` point 2: 24 common keys, differing [], both new keys 0.
- (2) cta with `--disturb none` vs the stored cta file: 6 common keys, differing []. The undisturbed rows do not gain the new keys.
- (3) floor-heavy + timeout vs the stored file: 27 common keys, differing [], both new keys 0.
- All output filenames match master's names.

Tests:
- The full `tests` gate hit my 10-minute background limit and was stopped, so I did not see the full-gate count.
- These modules passed (OK): test_disturb, test_disturb_floor, test_env, test_recovery, test_regression_cta, test_stuck_aware, test_recovery_heldout, test_sweep, test_recovery_sweep.
- `fleet/tests/test_fleet_emit.py`: Ran 14, OK.
- Not run by me: test_evaluate, test_cost_router, test_closed_loop, test_learned_recovery, test_train_recovery, test_platform, test_recovery_informed, test_recovery_rule, test_fleet_collect, and the rest of fleet/tests.

Scope:
- `git diff origin/master --stat -- README.md docs vendor fleet` is empty.
- The pass-4 commit touches only `tests/test_evaluate.py` (18+/10-), and its diff does not touch setUp.

WOULD-FAIL-ON-OLD-CODE: n/a (regression lens)
REQUIRED FIX: none. Confidence is medium rather than high because I did not see the full gate finish.

The repo checkout was left on master; the temporary worktree /tmp/pr19rev has been removed.
```

**test-honesty: survives (high)**
```
VERDICT: survives
LENS: test-honesty
CONFIDENCE: high
STRONGEST OBJECTION: I found nothing that refutes the test. The closest thing to a gap is that the explicit base-0 resume runs after the two refusals instead of before them. The criterion only says the base-5 resume must be the first refusal, so this order is allowed.
EVIDENCE:
- Pass-4 diff (`git diff --stat 11f351a f2f750b`): only tests/test_evaluate.py changes, 18 insertions and 10 deletions. The setUp fixture is not in the hunk, so its bytes are unchanged.
- The test writes its own map, costmap7.json, with zones '0'..'6' and runs seeds (5, 6). Under base 0 that needs zones 5 and 6, under base 5 zones 0 and 1, under base 1 zones 4 and 5. All exist, so the missing-zone check (evaluate.py L326-327) passes in every run.
- The two possible errors have different messages. The identity check at L266 says "stores costmap_seed_base ...". The missing-zone error at L284 says "seed base" with a space. So `assertRaisesRegex(ValueError, 'costmap_seed_base')` can only pass if the identity check fired. The flag-validation messages at L309-311 use "--costmap-seed-base" with hyphens, so they cannot match either.
- I ran the mutant myself in a temporary worktree at f2f750b, with "costmap_seed_base" removed from the tuple at L264. Result: FAILED, traceback "tests/test_evaluate.py, line 311 ... with self.assertRaisesRegex(ValueError, "costmap_seed_base"): AssertionError: ValueError not raised". Line 311 is the base-5 assertion.
- With the real code the test passes: Ran 1 test, OK.
- The test also checks that the base-0 header has costmap_seed_base == 0 and that the stored rows deep-equal the rows saved before the refused runs. A separate base-5 run into its own dir writes a header with costmap_seed_base == 5.
- PR body: it has the pass-4 section, the correction to the pass-3 sentence (base 5 had hit the missing-zone path), m1 with the line-311 traceback, m2 OK, the --stat, and the gate lines (Ran 616 OK, Ran 312 OK). I did not re-run the full gate myself.
WOULD-FAIL-ON-OLD-CODE: yes. The mutated identity check fails at the base-5 assertion; I reproduced this.
REQUIRED FIX: none
```

**scope-adherence: survives (medium)**
```
VERDICT: survives. LENS: scope-adherence.

The brief closes the scope for pass 4. Criteria (a)-(i), p3-1 and p3-2 are judged only for regressions that the pass-4 commits introduce, so I judged the pass-4 delta.

What I checked:
- **The pass-4 delta is one commit touching one file.** `git rev-parse f2f750b4^` returns 11f351a2, the pass-3 head. `git diff --stat 11f351a2 f2f750b4` shows only tests/test_evaluate.py (18 insertions, 10 deletions).
- **The change is a single hunk inside the one test.** That diff has exactly one hunk (`@@ -295,22 +295,30 @@`), inside TestCostMapFlags.test_seed_base_is_part_of_the_identity.
- **The setUp fixture bytes are unchanged.** grep finds no `def setUp` or `self.cm =` line in the delta.
- **Everything in the hunk is something p4-1 asked for:**
  - a test-local cm7 with zones '0'..'6' and seeds (5, 6), which is the brief's own example;
  - the base-5 resume as the first refusal, using assertRaisesRegex(ValueError, 'costmap_seed_base');
  - the base-1 resume kept as a refusal with the same regex;
  - an explicit base-0 resume that succeeds;
  - a row-equality check after the refusals, stronger than the "at minimum seed list" floor the brief allows;
  - a separate base-5 run into its own dir that checks the header value 5 (cm7 is explicitly allowed).
- **No production code changed and nothing extra was added.**
- **PR body, checked by reading the body.** It has the pass-3 correction (body line 85), m1 failing at the base-5 assertion (line 90), m2 passing with "Ran 1 test ... OK" (line 97), and the pass-4 `--stat` (line 99).

Extras from passes 1-3 that (g) and (f) did not ask for. These are out of this pass's scope and non-blocking; they do NOT change the verdict:
- scripts/closed_loop.py hard-codes REFERENCE_MEDIUM_30SEED = 53.66 and writes it to summary.json as reference_medium_30seed_undisturbed. That is a retyped number labelled "context only".
- scripts/closed_loop.py has an `--alphas` multi-arm sweep and a phaseA_meta.json resume guard.
- scripts/closed_loop.py defaults `--out-dir` to a path under results/ when the flag is omitted.
- In scripts/evaluate.py, the paired-delta lookup paths `base_path` and `cta_path` now append cm_suffix. This does nothing without a map flag, so it cannot affect criterion (a).

WOULD-FAIL-ON-OLD-CODE: n/a for this lens. The mutant runs m1 and m2 come from the PR body only; I did not re-run them.
```

**invariants: survives (medium)**
```
VERDICT: survives. LENS: invariants. STRONGEST OBJECTION: none held up. The weakest spot is the routes_changed reference in the test: it reuses the same vendor find_path / obstacle port that the counter calls, so it is only partly independent. That is a test-honesty point, not a broken invariant.

EVIDENCE (PR #19, head f2f750b, checked in a temporary worktree):
- No-map runs bit-identical to master. I re-ran the 3 criterion (a) commands (medium env, seeds 0-1, 500 steps) and compared rows by seed against the stored results/ JSONs. All differing-key lists were empty. Common keys: 24 for timeout.json point==2, 6 for the cta file, 27 for the floor-heavy file. The only new keys are routes_changed_by_map=0 and map_cells_entered=0 (pre-existing extra keys aside).
- Same code path without a map. disturb.py find_path: with `_weights is None`, it calls the vendor super().find_path or the obstacle port with weights=None, exactly as before. The trim is still computed on the binary grid before any weighting.
- Schedules do not depend on the map. reset runs _generate_schedule(seed) before _set_active_map. cost_map is a separate constructor kwarg and never goes into disturb_config. The new code makes no RNG draws.
- floor_cells reads. `git grep floor_cells` in src/ and scripts/ finds only one new read, disturb.py:256 (`m = dict(self.floor_cells)`, labelled oracle-only). The old floor-skip reads at L467/484/486 are unchanged. closed_loop.py and evaluate.py never read it.
- vendor/ untouched. `git diff --stat origin/master...f2f750b` touches only scripts/, src/ and tests/: no vendor/, fleet/, README or SCOPE.
- One env per process. closed_loop.py runs evaluate and the fleet CLIs as subprocesses. Test envs are built one at a time, and vendor reset sets Agent.counter = 0 and Shelf.counter = 0 (warehouse.py:618-619).
- Pick-rate. It comes from evaluate rows (row["pick_rate"]), not from reward.
- Workers. closed_loop passes --workers through and otherwise leaves the choice to evaluate's resolve_workers. evaluate still writes after every seed and skips pairs already on disk. The resume identity now includes costmap, costmap_alpha and costmap_seed_base.
- Pass 4. Commit f2f750b touches only tests/test_evaluate.py (+18/-10).
- m1 mutation reproduced. With costmap_seed_base removed from _check_same_costmap, the test fails at test_evaluate.py:311, the base-5 assertRaisesRegex, with "ValueError not raised". The real code passes.
- Gate at f2f750b: tests Ran 616, OK; fleet/tests Ran 312, OK.

WOULD-FAIL-ON-OLD-CODE: yes (the m1 mutant fails at the base-5 line).

REQUIRED FIX: none.
```

## Non-blocking notes from the refuters (for the operator; no action this lane)
- scope-adherence, pass 1-3 extras:
  - `closed_loop.py` hard-codes `REFERENCE_MEDIUM_30SEED = 53.66` into summary.json as a context-only, retyped number. README numbers must still come from the undisturbed arm's results JSON.
  - `--out-dir` defaults to a path under `results/`.
- invariants: the routes_changed reference in the test reuses the same find_path port as the counter, so it is only partly independent.
- regression: older results files resumed by sweep.py, recovery_sweep.py or recovery_heldout.py will mix rows with and without the two new keys. No consumer needs a uniform key set. Cosmetic.

## Hygiene
- Main checkout: on master at 99d526e. Only the pre-existing untracked `.pt` files are present.
- Pass-3 report kept below; its prior copy is at `/tmp/s8c/wr-lane-s8c.pass3.md`.

---

## Regression comparisons (PR body, re-run independently by 3 refuters across both passes)
### (a) No-map regression (darwin, medium, seeds 0-1, 500 steps, each into its own new /tmp dir)
```
(1) stuck_aware_cta_tarware-medium-8agvs-4pickers-globalobs-v1_500_cfg-30ea5eed00_timeout.json  common keys (2 seeds) = 48, differing = []  new keys routes_changed_by_map [0, 0], map_cells_entered [0, 0]
(2) cta_tarware-medium-8agvs-4pickers-globalobs-v1_500.json                                      common keys (2 seeds) = 12, differing = []
(3) stuck_aware_cta_tarware-medium-8agvs-4pickers-globalobs-v1_500_floor-heavy_timeout.json      common keys (2 seeds) = 54, differing = []  new keys routes_changed_by_map [0, 0], map_cells_entered [0, 0]
```
(24 / 6 / 27 common keys per seed, wall_s excluded; (1) against the point == 2 rows of results/recovery/timeout.json.) Filenames equal master's for the same commands.


---

# Pass 3 report (kept for the record)

# wr-lane-s8c — S8C-COST-AWARE-ROUTER, pass 3 (14 Oct 2026, evening)

**Result: FAIL. Pass 3 (the last pass) is still refuted by one refuter: test-honesty, medium. Not merged, and master not moved. The operator decides.**
- PR: https://github.com/Michiel-DK/warehouse-rl/pull/19. OPEN, head 11f351a, rebased onto origin/master 274e20f, MERGEABLE.
- Merge sha: none.
- Workflow run wf_0bf8608f-4c3. Script `/tmp/s8c/single-lane-build-s8c-pass3.js` (pass 3, priorPasses = pass 1 + pass 2 verbatim).
- Result object saved verbatim to `reports/wr-lane-s8c-pass3-result.json`, for priorPasses if a pass 4 runs.
- Harness tally: 1 of 5 refuted, recommendation `ready-for-merge-gate`. That is the harness's majority rule. It is NOT this repo's merge rule.
  - CLAUDE.md merge delegation needs a clean round: no refuter still refuting, or every finding fixed and re-verified.
  - The job says "Refuted: FAIL and STOP".
  - So no merge, and no main-loop fix: a main-loop fix would be an unreviewed edit on a full-tier PR, in effect an unauthorised pass 4.

## What pass 3 changed (commit 11f351a: scripts/evaluate.py +7 lines, tests only)
1. **Seed base.** `costmap_seed_base` is now in the evaluate doc header: the effective base for a file map (0 when omitted), null for the oracle.
   - It is also in `_check_same_costmap` (evaluate.py L264).
   - A resume with a different base raises ValueError. Filenames are unchanged, and an explicit 0 equals an omitted base.
   - Test: `test_seed_base_is_part_of_the_identity`.
2. **Wall-cell guard.** The vacuous test `test_weights_never_open_inf_cells` is replaced by three guard tests that use a tiny alpha, so a costed wall would be a shortcut:
   - picker over costed racks;
   - costed active-obstacle cell;
   - costed cell under another agent with care_for_agents=True.
   - Plus a ValueError test for non-finite costs.
   - Mutation proof (PR body, independently re-run by the correctness and test-honesty refuters): with `if grid[wy, wx] == 1:` replaced by `if True:`, `Ran 26 tests ... FAILED (failures=3)`. The real code gives `Ran 26 tests ... OK`.

## The live refutation (test-honesty, medium)
- **Defect.** `tests/test_evaluate.py` ~L305-306: the base-5 `assertRaises` runs seeds (1, 2) against a fixture with zones 0, 1, 2 only.
  - It asks for zone '-4', so it raises the up-front missing-zone ValueError (evaluate.py L283-284) before `_check_same_costmap` is reached.
  - Refuter probe: `BASE 5 -> costmap has no zone '-4' for seed 1 (seed base 5)`, versus `BASE 1 -> ... stores costmap_seed_base 0, requested 1; refusing to merge`.
- **The code fix itself is sound.** With `costmap_seed_base` removed from the identity tuple, the test as a whole goes red, but only through the base-1 assertion.
  - So base 0 vs 5 (the case the operator named) is never exercised on the identity path.
  - The PR body ("base 0 then 5 and 1 into the same dir raise") overstates it.
- **Suggested fix (UNVERIFIED, for the operator):**
  - Run the base-5 case with seeds 5-6 into the base-0 directory, so zones '0' and '1' exist and only the identity check can refuse.
  - Mutation proof: drop the key at evaluate.py L264, and the base-5 assertion alone must go red.
  - Merging by hand after that one-line test change is a reasonable option. A pass 4 is the other option.

## Harness finding: the criterion pre-review predicted this exact trap, and the harness dropped it
- The pass-3 criterion pre-review returned `sound: false` with **2 blocking** letter-traps.
  - Blocking issue 1 is exactly the refuted defect: "base 5 raises the missing-zone ValueError whether or not seed base is part of the identity check".
  - Blocking issue 2: p3-1's "different filename" option contradicts (f)'s pinned filename. Moot, because the build chose refusal.
- Because the run had `proceedWithCriterion: true` (carried over from pass 2), `criterionGate` returns `proceed` before it looks at blocking issues (script ~L727-729).
  - Only the 4 advisories were attached to the builder brief. The run log says "criterion pre-review: sound, with 4 advisory finding(s)".
  - So the builder never saw the warning.
- The lesson: drop `proceedWithCriterion` on a re-scoped pass, or have the harness pass blocking issues to the builder even when proceeding.

## Criterion (a) no-map regression re-run at the pass-3 head (PR body; the regression and correctness refuters re-ran it independently)
```
1. timeout, breakdown rate 2: file ..._500_cfg-30ea5eed00_timeout.json, 24 common keys, differing []; routes_changed_by_map / map_cells_entered 0, 0
2. cta, disturb none: cta_..._500.json, 6 common keys, differing []
3. floor-heavy timeout: ..._floor-heavy_timeout.json, 27 common keys, differing []; new keys 0, 0
```
(darwin, medium, seeds 0-1, 500 steps, fresh /tmp dirs, every key except wall_s; common keys per seed.)

## Gate at 11f351a
- Builder (PR body): `unittest discover -s tests` Ran 616 OK; `unittest discover -s fleet/tests` Ran 312 OK.
- Regression refuter: tests exit 0 (it did not capture the OK line), fleet/tests "Ran 312 tests ... OK".

## Smoke summary
Unchanged from pass 1 (table below). Pass 3 touched only evaluate.py header/identity code and tests; the smoke was not re-run in pass 3.

## Queue command for `wr-s8c-closed-loop-measure` (unchanged; only after S8C merges, do NOT release now)
```
.venv/bin/python scripts/closed_loop.py --seeds 30 --steps 500 --alphas 2,4,8 --workers 8 --out-dir results/closed_loop
```

## Pass-3 refuter verdicts (verbatim, as returned; the excerpts above quote them)

**correctness: survives (medium)**
```
VERDICT: survives. LENS: correctness. I checked the pass-3 diff (11f351a) against p3-1, p3-2, the re-run of (a) and the evaluate tests. I found no input that gives a wrong result.

p3-1: in scripts/evaluate.py, L264 adds costmap_seed_base to the _check_same_costmap identity keys. The oracle header stores None (L325-326). File maps store the effective base, cm_base = 0 when the flag is omitted (L319, L333), so an omitted flag and an explicit 0 count as the same identity. That matches the advisory. Old no-map files hold no such key, and with no map flag the expected value is {}, so they compare None == None and stay compatible. Mutation: I dropped the key from the check tuple and test_seed_base_is_part_of_the_identity FAILED ("ValueError not raised" on the base-1 resume). So the identity check is really exercised.

Weak spot, test honesty only: the base-5 assertRaises with seeds (1, 2) passes on the up-front missing-zone ValueError (zone "-4"), not on the identity check. The base-1 case carries the real proof. Base 5 is covered only by the header value (5) recorded in its own directory.

p3-2: the guard is in src/warehouse_rl/disturb.py: `if grid[wy, wx] == 1:`. I ran it at head: test_cost_router plus test_evaluate, Ran 47, OK. With the guard mutated to `if True:`, three tests fail: test_costed_rack_cells_stay_walls_for_a_picker, test_costed_active_obstacle_cell_stays_a_wall and test_costed_cell_under_another_agent_stays_a_wall_with_care_for_agents. The tests use alpha 0.001, which turns a costed wall into a shortcut, so they are not vacuous. Non-finite costs raise ValueError in the constructor (test_non_finite_costs_are_rejected_not_weighted).

(a)(3) re-run at head: no map, stuck_aware_cta, timeout recovery, floor-heavy, medium map, seeds 0-1, 500 steps, written to a new /tmp directory. The output filename is the same as master's. Against the stored file, rows for seeds 0 and 1 share 27 common keys each, with no differing keys. routes_changed_by_map and map_cells_entered are both 0. The doc header has no costmap keys. I did not re-run comparisons (1) and (2), but the pass-3 diff touches only map-flag branches of evaluate.py and no src/ file, so no-map behaviour cannot change. I did not run the full gate (unittest discover over tests/ and fleet/tests).
```

**regression: survives (medium)**
```
VERDICT: survives. LENS: regression. CONFIDENCE: medium.

STRONGEST OBJECTION: Old rows and new rows will now sit in the same file. If sweep.py, recovery_sweep.py or recovery_heldout.py resumes into an existing results file, the old rows lack routes_changed_by_map and map_cells_entered and the new rows have them. No consumer I found needs every row to have the same keys. closed_loop.py:115 does `r[k]`, but it only reads rows it wrote itself. So this is a cosmetic risk, not a breakage.

EVIDENCE:
- I checked out the PR head 11f351a in a temporary detached worktree (/tmp/rev19, since removed). The lane worktree is stale at 8db5ad4.
- Callers of every modified function, found by grep: the run_seed callers are scripts/sweep.py:95, recovery_sweep.py:149 and recovery_heldout.py:134. The find_path callers are policy.py:80/97/111 and recovery.py:337/360/388/473. There are three WarehouseEnv/DisturbedWarehouse/RecoveryHook construction sites (env.py:52/56, learned_recovery.py:217, throughput.py:35). All of them use keyword defaults, so they are unaffected.
- With no active map, or with alpha 0 (`_weights is None`), find_path runs exactly the code master runs. In `_find_path_with_obstacles`, `trim` is computed on the binary grid, so its value is the same as before.
- Without a map flag, evaluate builds the same job tuples as master. `cm_header or None` leaves the doc unchanged. On resume, `_check_same_costmap` compares None to None for old files and passes.
- learned_recovery.obs_to_tensor rejects extra keys, but its obs is built in recovery.py, which this diff does not touch. The new info keys never reach it.
- Gate at the head: `unittest discover -s tests` exited 0 (about 10 min). I did not capture the OK line because the tail cut it off. `unittest discover -s fleet/tests` printed "Ran 312 tests ... OK".
- Criterion (a) re-run at the head on darwin, medium env, seeds 0-1, 500 steps, each into a new /tmp dir:
  - (1) timeout point 2: 24 common keys, no differing keys.
  - (2) cta none: 6 common keys, no differing keys.
  - (3) floor-heavy timeout: 27 common keys, no differing keys.
  - Runs (1) and (3) carry routes_changed_by_map=0 and map_cells_entered=0. Every filename matches master's.
- p3-1: an omitted seed base and `--costmap-seed-base 0` both resolve to cm_base=0, so they are the same identity. A different base changes the header, and `_check_same_costmap` refuses the resume. The oracle stores null.

WOULD-FAIL-ON-OLD-CODE: n/a (regression lens).

REQUIRED FIX: none.
```

**test-honesty: REFUTED (medium)**
```
VERDICT: refuted
LENS: test-honesty
CONFIDENCE: medium

STRONGEST OBJECTION: Clause p3-1 asks for a test that proves base 0 vs base 5 behaviour. The base-5 refusal at tests/test_evaluate.py:305-306 does raise, but not because of the seed-base identity check. It raises because the zone lookup fails first. So 0 vs 5 is never tested on the identity path, and the PR body describes this case as identity evidence.

EVIDENCE (worktree at PR head 11f351a; removed afterwards):
- The fixture has only zones "0", "1" and "2" (tests/test_evaluate.py:213). With seeds (1, 2) and base 5, evaluate asks for zone "-4". `_cost_map_for_seed` (scripts/evaluate.py:283-284) raises before `_check_same_costmap` is reached.
- A probe printed both ValueError messages:
  - `BASE 5 -> costmap has no zone '-4' for seed 1 (seed base 5); zones: ['0', '1', '2']`
  - `BASE 1 -> ... stores costmap_seed_base 0, requested 1; refusing to merge`
- Mutant: I removed "costmap_seed_base" from the identity tuple at evaluate.py:264. Under that mutant the base-5 assertRaises still passed, and only the base-1 assertion at test_evaluate.py:307 failed ("ValueError not raised"). The test as a whole does catch the mutant, but only through base 1.
- With this fixture, no seed pair is valid under both base 0 and base 5. The required 0-vs-5 refusal therefore cannot be tested here.
- The PR body says "base 0 then 5 and 1 into the same dir raise". That overstates what the base-5 case proves.

What holds up:
- The header values 0, 5 and null are asserted directly.
- The explicit `--costmap-seed-base 0` resumes into the file written with the flag omitted.
- p3-2 is honest. I mutated disturb.py:441 to `if True:` and got 3 failures (`test_costed_active_obstacle_cell_stays_a_wall`, `..._under_another_agent_...`, `..._rack_cells_stay_walls_for_a_picker`), "Ran 26 tests FAILED (failures=3)". The real code passes, and the rack test asserts more than 20 tempting shortcuts, so it is not vacuous.
- Gate at head, my run: `unittest discover -s tests` "Ran 616 tests in 604.032s OK". I did not re-run fleet/tests or the (a) regression runs.

WOULD-FAIL-ON-OLD-CODE: yes for the test as a whole (only through the base-1 assertion); no for the base-5 assertion on its own.

REQUIRED FIX (if refuted):
1. Add zones "5" and "6" to the fixture.
2. Run seeds (5, 6) under base 0, then try to resume with base 5 into the same directory.
3. Use `assertRaisesRegex(ValueError, "costmap_seed_base")` on every refusal so the cause is pinned.
4. Correct the base-5 line in the PR body.
```

**scope-adherence: survives (medium)**
```
VERDICT: survives
LENS: scope-adherence
CONFIDENCE: medium
STRONGEST OBJECTION: For p3-2 the lane added three guard tests (costed rack cells, a costed active-obstacle cell, a costed cell under another agent) plus a non-finite-cost ValueError test, where p3-2 asked for one test. All four are test code. They cover the three ways a cell becomes inf on the binary grid, and the ValueError test is what criterion advisory 4 asked for. No production code was added beyond the request.
EVIDENCE: The pass-3 commit 11f351a2 changes only scripts/evaluate.py (7 lines), tests/test_cost_router.py and tests/test_evaluate.py.
- In evaluate.py, `costmap_seed_base` is added to the tuple `_check_same_costmap` iterates over (L264) and to both doc headers. The file-map header stores the effective `cm_base`; the oracle header stores `None` (L325-333). This matches p3-1 and the advisory reading (doc header, effective base, null for the oracle).
- test_evaluate.py `test_seed_base_is_part_of_the_identity` covers: an omitted base equals an explicit 0, base 5 or base 1 against a base-0 file raises, and a base-5 run records 5 in its header. That is p3-1.
- test_cost_router.py replaces the vacuous `test_weights_never_open_inf_cells` (alpha 4, so a costed wall was never a tempting shortcut) with tiny-alpha tests that need the wall to be a shortcut (`shortcuts > 20`). That is p3-2.
- No pass-3 changes to src/, fleet/, vendor/, README.md or docs/SCOPE.md (`git show --stat 11f351a2`). Criterion (i) holds for this pass.
- Earlier-pass extras, such as `cm_suffix` added to the paired-delta lookups for `base_path`/`cta_path` in evaluate.py, are outside the pass-3 fence (advisory 3: other clauses are judged only for regressions the pass-3 diff introduced). They also follow from (f)'s filename rule.
Not checked: the PR body's mutation proof and the gate counts. Those belong to other lenses.
WOULD-FAIL-ON-OLD-CODE: yes. The seed-base test fails without the new key, because the header assert raises KeyError and the base-5 resume is not refused.
REQUIRED FIX: none.
```

**invariants: survives (medium)**
```
VERDICT: survives. LENS: invariants. CONFIDENCE: medium.

I checked PR #19 at head 11f351a (`gh pr diff 19`, and the PR file read with `git show pr19tmp:...`) against each of the 8 invariants and found no violation.

1. One env per process: evaluate.py still runs one env per `mp.Pool` job. closed_loop.py starts evaluate.py and the fleet CLIs through subprocess only (`_run`). There is no in-process vectorisation.
2. Pick-rate: the definition is not touched. closed_loop.py reads `r["pick_rate"]` from evaluate rows and never uses the reward.
3. Workers and resume: closed_loop.py passes `--workers` through only when it is given. Otherwise the evaluate.py subprocess falls back to SCHED_WORKERS, then `cpu_count`. Resume is evaluate's own skip of seeds already on disk. Phase A is skipped when costmap.json already exists with the same meta. evaluate.py still writes after every row.
4 and 6. Schedules do not depend on the map: `_generate_schedule` (disturb.py L289-337) seeds its RNGs from (seed, config hash) only. `cost_map` is stored in `_cost_map_arg` and never enters `disturb_config`. The weighted A* draws no random numbers. `test_cost_router` `_schedules` (L530-561) compares floor_cells, floor_coin, frozen and delayed across no map, a dict map and the oracle.
5. vendor/ is read-only: no file under vendor/ changed. The router subclasses `find_path` and adds a `weights` argument to the existing port of `_find_path_with_obstacles`.
7. No-map runs are bit-identical: when `_weights is None` (disturb.py L383-386), `find_path` follows exactly the branches master has. `trim` is computed from the binary grid before any weighting, so the trim is unchanged. The only new info keys are the two counters, both 0 without a map.
8. floor_cells reads: the only new read in src/ and scripts/ is `_set_active_map` at disturb.py L255-256, on the oracle branch, and it takes a copy (`dict(...)`). closed_loop.py does not read floor_cells (I grepped it). The test reads are allowed by the criterion.

Gate check I ran on a `git archive` snapshot of the head in /tmp/pr19h: `python -m unittest tests.test_cost_router tests.test_evaluate tests.test_disturb` gave Ran 79 tests, OK.

Not checked by me: the full gate, the fleet tests, and the (a) re-run on the medium map at this head.

Minor point, not a violation: closed_loop.py's default out-dir is under results/. That is allowed for long runs, and the smoke test passes `--out-dir`.

STRONGEST OBJECTION: none that holds up.
EVIDENCE: none found.
WOULD-FAIL-ON-OLD-CODE: n/a.
```

## Hygiene
- Main checkout: on master at 274e20f. No new files beyond the pre-existing untracked `.pt` files.
- The builder pushed PR #19 with force-with-lease from a local branch, because the lane branch is checked out in the stale worktree `wf_979a96b1-c1c-2`.

---
# Pass 1-2 report (kept for the record)

# wr-lane-s8c — S8C-COST-AWARE-ROUTER (14 Oct 2026)

**Result: FAIL. Still refuted after pass 2. Not merged; master not moved.**
- PR: https://github.com/Michiel-DK/warehouse-rl/pull/19. It is OPEN, head 1fa4a21, branch `worktree-wf_979a96b1-c1c-2`,
  and MERGEABLE against origin/master 274e20f. S8D (#18) merged beside it, and a regression refuter merge-tested it clean.
- Merge sha: none.
- Brief: `reports/wr-lane-s8c-brief.md`. It holds the criterion history, the pass-2 scope and the overrule record.

## Run history
| Run | Workflow | Outcome |
|---|---|---|
| criterion v1 | wf_37df6512-ac5 | HALT, 4 blocking: the `breakdown-light` preset != the stored timeout.json config (agv-only), wall_s, existing floor_cells reads, alpha-0 vs filename |
| criterion v2 | wf_cbdc7916-f2c | HALT, 3 blocking: "every path search" vs the counting search, undefined counters, resume into a non-empty results dir |
| criterion v3 | wf_89882a5c-2be | HALT, 3 blocking: floor_cells reads in tests, "present (0)", "existing code path" for the obstacle branch |
| criterion v4 | wf_dd587e4f-ff3 | HALT, 2 blocking: nothing required evaluate to PASS the map into the env (real gap); "doc unchanged" vs the new row keys |
| pass 1 (v5, `proceedWithCriterion: true`) | wf_979a96b1-c1c | PR #19 built. correctness, regression, scope and invariants survive; **test-honesty REFUTED (high)** |
| pass 2 (v5.1, priorPasses = pass 1 verbatim) | wf_aa9381c7-345 | criterion sound (advisories only); **correctness REFUTED (medium), test-honesty REFUTED (high)**; regression, scope and invariants survive |

- Each criterion halt: the reviewer's own full rewrite was adopted whole.
- After the 4th halt, the main loop set `proceedWithCriterion: true`. The rounds were converging on wording, and v5 itself is the 4th reviewer's rewrite. That overrule is the main loop's call, and it is recorded here.
- Builder: sonnet. Verify: opus. Tier: full. Five lenses: correctness, regression, test-honesty, scope-adherence, invariants.

## Refuter verdicts
**Pass 1 (head 8db5ad4)**
- **test-honesty: REFUTED (high).**
  - The detour test used alpha*cost = 10x the extra steps. The refuter's probe showed straight paths at alpha*cost of 2.5-4 for a 2-step detour.
  - Root cause, read from `vendor/pyastar2d/src/cpp/astar.cpp` ~L115-139: the vendored fork adds +1 per direction change and marks relaxed cells with `weights += 100`. The comparator is therefore extra steps + extra turns, not steps.
- correctness, regression, scope and invariants: survive. They re-ran the regression, the gates (598/298 OK) and their own counter probes.

**Pass 2 (head 1fa4a21)**
- **correctness: REFUTED (medium). `--costmap-seed-base` is in neither the doc header, `_check_same_costmap`, nor the filename.**
  - A run with base 1 resumes silently into a file written with base 0. It then hands back rows that were routed on the other zone.
  - Reproduced: a fresh run differs on 9 keys, e.g. floor_skip_steps 73 vs 106.
  - The criterion's resume clause names only costmap/costmap_alpha, so the build met the letter. closed_loop always uses base 0, so the headline arms are unaffected.
  - Fix: add `costmap_seed_base` to the header and the resume check (or to the suffix), plus a test.
- **test-honesty: REFUTED (high). No test can see criterion (b)'s "inf cells stay inf".**
  - Mutating the guard `if grid[wy, wx] == 1:` to `if True:` (disturb.py ~L441) leaves all 23 router tests green.
  - Under that mutation, picker queries walk through rack cells in 121/1600 cases, against 0/1600 on the real code.
  - `test_weights_never_open_inf_cells` queries an AGV with care_for_agents=False, a grid on which no cell is inf.
  - Fix: a test that costs inf cells (picker non-highway, an occupied cell with care_for_agents=True, an active obstacle) and asserts the path never enters them; the mutation must turn it red.
- regression: survives. It re-ran (a)(1)-(3) at 1fa4a21 with 0 diffs, plus the gates: tests 598 OK, fleet/tests 312 OK on the branch and on the merged tree.
- scope-adherence: survives.
- invariants: survives. It notes that Phase A emits the same seeds and config that Phase B scores, so the map is "same floor, earlier run", not other-day data. This is the S8B design ("Which map for which episode", option 1).

**Both pass-2 kills are small and local.** One is a header/resume key. The other is one missing test, plus the mutation check. A pass 3 scoped to those two should be short. Per the job rule, the main loop stops here and does not run it.

## How the weighted grid is built (from the PR)
### Weighted grid (how it is built)
With an active map (non-empty dict) and `cost_alpha > 0`, `DisturbedWarehouse.find_path` returns the A* path on the weighted grid, for every caller (macro-action assignment, vendor replans, recovery reroute, policy distance scoring), with or without active obstacles:
1. The grid is built and binarised to {1, inf} exactly as today (agents, shelves, picker non-highway, obstacles are inf).
2. The start-cell trim flag `1 - int(grid[start] > 1)` is computed on that BINARY grid.
3. Then each map cell `(x, y)` whose binary value is finite gets weight `1 + alpha * cost` at `grid[y, x]`. inf cells stay inf.
4. With no active map, or alpha 0, the code path is the existing one (vendor `Warehouse.find_path` when there are no obstacles, the existing port otherwise); no weighting and no second search.
`routes_changed_by_map` counts, over all find_path queries since the previous step (policy scoring included), those whose weighted path differs from the unweighted one (the only unweighted search, run only when a map is active). `map_cells_entered` counts agent-steps whose cell changed and whose new cell is in the active map (a floor skip is no entry). Both are in every disturbed-env info (0 without a map) and reset at `reset()`.
`cost_map` = None | dict `{(x, y): cost}` (int tuples inside the grid, 0 < cost <= 1) | `"oracle"` (`dict(floor_cells)` re-read after each reset; the only NEW read of `floor_cells`, one commented branch in `DisturbedWarehouse._set_active_map`; an empty floor is no map). `cost_alpha` finite >= 0. Anything else, and a non-None map on `WarehouseEnv` without a disturb dict, raises ValueError. The map never enters the disturb config, so schedules and floor layout are unchanged (tested for breakdown+floor and for an all-types config, no map vs dict vs oracle, 2 seeds).
Weighted lengths also change CTA's assignment distances (it calls `find_path`): expected under "every path search".

**pyastar2d wall/float handling.**
- Walls: pyastar2d takes a float32 grid, with inf = wall and every finite weight >= 1.
- Grid build: the port binarises exactly like the vendor (`grid != 0` -> {1, inf}). Weights `1 + alpha*cost` then go only on cells still equal to 1.
- Trim flag: the vendor's start-cell trim `astar_path[1 - int(grid[start] > 1):]` assumes free = 1, so it is computed on the BINARY grid before weighting. A robot standing on a costed cell would otherwise keep its start cell.
- The fork's cost per move is the weight of the entered cell, plus 1 on a direction change. The turn penalty is skipped when the entered weight is >= 100, i.e. alpha*cost >= 99.
- Visited cells get `+= 100` on the passed array. The port rebuilds the grid on every call, so this mutation is harmless.

**Consequence for the measurement (a planner property, read before any result; stated at the strength measured).**
- Thresholds: in the three hand-built single-cell cases, a sidestep needs alpha*cost > E, with E = 4 (open grid: +2 steps, +2 turns), 6 and 8 (walls beside the cell).
  - The brief's pass-2 note estimated "+4 turns = 6". The measured open-grid E is 4.
  - These are three cases, not a proof that 4 is the lowest E anywhere on the warehouse grid.
- At the headline alpha 4 with an analyst cost of exactly 1.0 (costmap.py normalises each zone's top cell to 1.0), the open-grid case is an exact tie (alpha*cost = E = 4).
  - On darwin the tie goes straight. A* tie-breaks differ between macOS and Linux (docs/PLATFORM.md).
- The smoke shows the map still acts at alpha 4:
  - map_a4 cut floor_skip_steps from 263.5 to 162.5 and changed 108.5 routes per episode.
  - The oracle (alpha*cost <= 2.8, below every measured single-cell threshold) still gained +2.16.
  - It acts through multi-cell runs (k*alpha*cost > E), equal-length alternatives and CTA assignment distances.
- Smoke pick-rates: map_a4 = none = 25.20 (same CI) despite non-zero map counters. This is pick-rate quantisation, not a silent fallback: 1.44 lines/h per delivery at 500 steps, 2 seeds.
- **Oracle is not scale-matched to the analyst map.**
  - Oracle costs are p_c in [0.3, 0.7]. Analyst costs are normalised to a per-zone max of 1.0.
  - At the same alpha, the analyst map can penalise cells harder than the oracle. So map <= oracle is NOT guaranteed, and the README comparison needs that caveat. "Oracle = upper bound" holds for the map's information, not for the penalty scale.

## Regression comparisons (PR body, re-run independently by 3 refuters across both passes)
### (a) No-map regression (darwin, medium, seeds 0-1, 500 steps, each into its own new /tmp dir)
```
(1) stuck_aware_cta_tarware-medium-8agvs-4pickers-globalobs-v1_500_cfg-30ea5eed00_timeout.json  common keys (2 seeds) = 48, differing = []  new keys routes_changed_by_map [0, 0], map_cells_entered [0, 0]
(2) cta_tarware-medium-8agvs-4pickers-globalobs-v1_500.json                                      common keys (2 seeds) = 12, differing = []
(3) stuck_aware_cta_tarware-medium-8agvs-4pickers-globalobs-v1_500_floor-heavy_timeout.json      common keys (2 seeds) = 54, differing = []  new keys routes_changed_by_map [0, 0], map_cells_entered [0, 0]
```
(24 / 6 / 27 common keys per seed, wall_s excluded; (1) against the point == 2 rows of results/recovery/timeout.json.) Filenames equal master's for the same commands.

## Smoke summary (pass 1 head; router code unchanged in pass 2)
### Smoke summary (`scripts/closed_loop.py --smoke`, small map, 2 seeds x 500 steps, 14 s wall)
```
arm            pick-rate              95% CI  delta vs none   share
none               25.20      [16.05, 34.35]              -       -
map_a4             25.20      [16.05, 34.35]          +0.00    0.00
oracle             27.36      [27.36, 27.36]          +2.16    0.25
undisturbed        33.84      [24.69, 42.99]              -       -
```
Means (none / map_a4 / oracle / undisturbed): floor_skip_steps 263.5 / 162.5 / 167.0 / 0; stuck_busy_agent_steps 300 / 265.5 / 285.5 / 360; routes_changed_by_map 0 / 108.5 / 127.0 / 0; map_cells_entered 0 / 177.5 / 155.0 / 0. This is a 2-seed plumbing check, not a result: the CIs are n=2.

## Queue command for `wr-s8c-closed-loop-measure` (only after S8C merges)
```
.venv/bin/python scripts/closed_loop.py --seeds 30 --steps 500 --alphas 2,4,8 --workers 8 --out-dir results/closed_loop
```
- Settings: medium map, `stuck_aware_cta` + `timeout`, the floor regime `{"floor": {"cells": 80, "p": [0.3, 0.7]}}`.
- Arms: none / map_a2 / map_a4 / map_a8 / oracle / undisturbed. Phase A runs emit -> ingest -> costmap first.
- **Do not release it now.** PR #19 is not merged.

## Operator decisions
1. Pass 3 scoped to the two pass-2 kills (seed_base in header/resume, an inf-guard test with mutation proof), or merge by hand. The job rule forbids an automatic merge.
2. For information only, no re-pick asked: the turn penalty means alpha 4 sits at or below the single-cell sidestep thresholds seen in the three test cases, and the 2/4/8 sweep shows the sensitivity. Also, the oracle and the analyst map use different cost scales (see above), so read map vs oracle with that in mind.

## Hygiene
- Main checkout: on master, with no new files beyond the pre-existing untracked `.pt` files.
- The lane worktree `wf_979a96b1-c1c-2` is stale at 8db5ad4, per the test-honesty refuter. The PR head 1fa4a21 is on the remote branch. Pull before a pass 3.
- Pass-2 script (args spliced in, as the harness advises for large priorPasses): `/tmp/s8c/single-lane-build-s8c-pass2.js`. Result objects (verbatim, for priorPasses): `reports/wr-lane-s8c-pass1-result.json`, `reports/wr-lane-s8c-pass2-result.json`.


(superseded, pass 3) sched_result: FAIL S8C pass 3 still refuted (test-honesty, medium): the base-5 seed-base test passes on the missing-zone error, not the identity check (one-line fixture fix, seeds 5-6); PR #19 open at 11f351a, not merged; operator decides merge-by-hand vs pass 4


SCHED_RESULT: OK S8C merged (PR #19 -> 99d526e), pass 4 clean 0/5 refuted; next wr-s8c-closed-loop-measure (8 workers, announce before release)

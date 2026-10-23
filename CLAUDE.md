# warehouse-rl — can a learned policy beat CTA on pick-rate, and recover from stuck robots better than a rule?

Environment TA-RWARE (vendored under `vendor/`, never edited). Everything here is CPU only, local, deterministic per
seed. Plan, review findings, sprint checklists and the compute profile: `docs/SCOPE.md`. Current state and the queue:
`~/code/Michiel-DK/laptop-scheduler` (`python3 -m scheduler plan`) is the gate for anything longer than a smoke test.

## Bearings

```sh
.venv/bin/python -m unittest discover -s tests          # the deterministic gate (plain unittest, no pytest)
.venv/bin/python scripts/evaluate.py --policy cta --env tarware-small-4agvs-2pickers-globalobs-v1 --seeds 0-9 --steps 500
# internal dev harness (roger3000-dev, private): checked out locally at harness/, not part of this tree
```

Then read `docs/SCOPE.md` "Review findings" before touching the env: the API facts, the class-level counters and
the heuristic's edge cases are all there with file:line references into `vendor/`.

## Lane args

Pass these explicitly to `single-lane-build`. A declaration here does nothing on its own; the workflow never reads
`CLAUDE.md`.

```yaml
sensitivePaths:
  full:
    - 'src/warehouse_rl/(env|policy|disturb)\.py$'
    - 'scripts/evaluate\.py$'
repoInvariants:
  - 'one env per process: Agent.counter and Shelf.counter are class attributes, so parallelism is multiprocessing
     only, never in-process vectorisation'
  - 'pick-rate is deliveries * 3600 / (5 * steps); use info["shelf_deliveries"], never the reward'
  - 'scripts read the worker count from --workers, else SCHED_WORKERS, else os.cpu_count() - 2; long runs write to
     results/ after every seed and skip (config, seed) pairs that already exist'
  - 'the disturbance schedule is a function of (seed, config) only, identical across policies'
  - 'vendor/ is read-only; wrap or subclass, never patch'
repoReviewers: []
proceedAfterDiagnosis: '<name a test that is RED right now>'
```

The `full` files are the measurement itself: a bug there moves every number in the README.

## Conventions

- **The gate is `unittest`, run from the repo root.** No pytest, no assertions hidden in prints.
- **Measurements run through the scheduler**, never inside a build lane. A lane proves the harness works on <= 10
  seeds x 500 steps; the 30-seed runs and sweeps are queue items with their own logs and measured minutes.
- **Numbers in the README come from a results JSON on disk**, named in the same commit. Nothing retyped.
- **Code goes through a lane PR; docs go direct to master.** Stage explicit paths, never `git add -A`.
- **Merge delegation (operator, 2026-10-10):** a lane PR whose full review round is clean (refuters non-refuting
  or every finding fixed and re-verified, gate green) merges itself with `gh pr merge --squash`, then the checkout
  on `master` is fast-forwarded so the queue's measurement items run on the merged code. Halt to the operator only
  on an unresolved refutation or when a lane wants to change the metric definition or the vendored env.
- **Literature before the build (operator, 2026-10-20).** Every new sprint starts with a queued literature item
  (opus, about an hour) that names the planned build; the lanes depend on it and their briefs are written after its
  verdict, using the standard names it found. A check after the fact is only for results already measured.
- **Kill criteria are in `docs/SCOPE.md` "Premises and kill criteria"** and are the operator's to apply.

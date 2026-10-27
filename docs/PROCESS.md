# How this repository was produced

One author, one laptop (M1 Pro, 10 cores, 16 GB, CPU only), 9 to 27 October 2026, and an agent pipeline built on
Claude Code. This page says what the pipeline did and what the author did, because the commit trailers and the
vocabulary in `reports/` ("lane", "refuter", "operator") raise the question and the answer should be in the tree.

## The pipeline

- **One lane per change.** A lane takes a written brief (goal, files it may touch, a success criterion that names
  a test), builds in an isolated worktree, and opens a pull request. The 59 pull requests in the history are lanes.
- **Fresh-context review.** Before a lane may merge, reviewers that did not see the build read the diff: a
  correctness reviewer, a regression reviewer and a test-honesty reviewer that tries to show the new tests would pass
  with the bug present. The `# inject:` comments in the tests name the fault each test catches; that habit comes from
  the test-honesty reviewer. A lane with an unresolved refutation halts and is written up (for one that failed twice
  before merging, `reports/wr-lane-s3d.md`).
- **The gate.** `python -m unittest discover -s tests`, run locally per lane and on Ubuntu in CI
  (`.github/workflows/gate.yml`). Expected values are per platform because the vendored A* breaks ties differently
  on Linux (`docs/PLATFORM.md`).
- **Measurements outside lanes.** Anything longer than a smoke test runs as a queue item on a load scheduler, writes
  to `results/` after every seed, and is read back into the README by a script (`scripts/sprint8_tables.py`) rather
  than retyped. The convention "every number in the README names its results file in the same commit" is checked
  by hand at each docs pass and was checked again before this repository was made public.
- **Literature before a build.** Each sprint since 20 October starts with a literature pass that names the standard
  for what is about to be built (`docs/LITERATURE.md`). Several builds were renamed or cut by it.
- **Lane reports.** Every lane and literature pass left a report in `reports/`: what it built, what the reviewers
  found, what stayed open. They are the raw record; the README is the digest.

The orchestration code itself (the lane runner, reviewer prompts, queue) lives in a separate private repository
and is not needed to reproduce any number here. Reproduction needs only `scripts/setup.sh` and the commands in
the README.

## What the author did

- Chose the question, the simulator and the metric, and wrote the kill criteria before each sprint
  (`docs/SCOPE.md`, "Premises and kill criteria").
- Applied the kills. The learned recovery policy was stopped on its criterion after three attempts (README,
  "Sprint 3 close-out"); learned task assignment was never started once the recovery result was in.
- Made the calls that changed what was measured: the reward design after two failed passes (SCOPE, 13 October),
  the platform rule (`docs/PLATFORM.md`, decision B3), the pivot from a learned controller to a diagnostic tool, the
  rule that measurement items run on the scheduler and never inside a lane, and the ruling in every case where a
  reviewer and a builder disagreed.
- Wrote and rewrote the briefs. A brief that named the wrong files or a soft criterion produced a halted lane, and
  several did.
- Decided what goes on the front page and what stays a negative in the notebook.

## What the author did not do

- Type most of the code or the prose. Line counts here are not a measure of the author's unaided output and should
  not be read as one.
- Run a human code review of every line. The review that happened is the one described above, and its verdicts are
  in `reports/`.

## What this process is weak at

- It produces documents easily and products slowly. There is no API and no deployment beyond the local Docker
  compose in `fleet/compose.sh`; the pipeline had no step that asked "what can a user run end to end after this
  sprint", and it shows.
- The gate was red on master for a stretch in October (a page-freshness test and a missing dependency in
  `scripts/setup.sh`), because merges were gated on the local gate and the Ubuntu run was advisory. Both are fixed;
  the lesson is recorded here rather than hidden.

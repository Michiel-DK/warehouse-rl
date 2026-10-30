# wr-lane-s10c-blind-blockage — S10C planner-blind blockage (19 Oct 2026)

**Outcome: MERGED.** PR #40 squash-merged as `7bebef4`; master in `<local>/warehouse-rl` fast-forwarded to it.
Workflow `single-lane-build` run `wf_fd0c1a6f-559`, tier full, build model sonnet.

## What landed
- `blocked_cell` takes `"known": true|false`. The default is true, the old behaviour. `validate_config` accepts only a bool for it; under any other disturbance type the key stays an unknown-key ValueError.
- `_draw_config` removes `blocked_cell.known` before hashing. All three generators (main, floor, demo) are seeded through it, so known absent, true and false give the same schedules.
- With `known:false` the cell stays in `_blocked_by_step` (truth, `info["blocked_cells"]`) but is left out of `_obstacles_by_step`, so the planner is blind to it. `recovery.py`'s `_obstacles_now` is blind as well, which is intended.
  - A FORWARD into a blind cell is NOOPed in a new branch after the floor branch and before the obstacle branch.
  - The agent is added to `_suppressed`, which hides it from the StuckCounter.
  - The skip is counted only in `info["blind_skips"]`, which is present at every step.
- Emitter `blocked_windows` entries carry `known`. Truth readers accept entries without the key (test in `fleet/tests/test_fleet_truth_v2.py`). `fleet/data/README.md` documents the key.
- New `fleet/blind_smoke.py --smoke` and `fleet/tests/test_fleet_blind_smoke.py`. New `tests/test_disturb_blind.py`, which holds golden digests computed on base `afa7b2b` and reproduced for known absent, true and false.
- One existing test file changed outside the declared list: `fleet/tests/test_fleet_hotspot.py`. It only adds `blind_smoke.py` to the exemption list of the analyst ground-truth scan; no expected value changed.

## Smoke overlap (run by me on the PR head and again on merged master)
`.venv/bin/python fleet/blind_smoke.py --smoke` printed
`OVERLAP numerator=130 denominator=174 share=0.7471 (sensitivity: numerator at prev step = 130)`, wall time 2.6-2.7 s, `smoke ok`.
The setup is 2 zones x 150 steps on the small map, blocked_cell rate 8.0, duration [60, 240], known:false. The denominator is every stall message attributed to the cell in front of the robot.

**Caveat: the seed was chosen after seeing a zero.** At seed base 0, the brief's literal setting, the share is **0**: no robot reaches a blind cell in 150 steps (the builder traced 0 blind_skips). The smoke therefore pins seed base 13. That shows the mechanism produces stalls at the truth cell when a robot does reach one. It says nothing about how often robots reach one in short runs. Test (e) needed 300 steps rather than 100 to get blind_skips > 0 on seeds 0-2.

## Review round
- Criterion pre-review: sound, 4 wording advisories only.
- python-reviewer: pass, nits only.
- Refuters: correctness, regression, test-honesty, scope-adherence and invariants all returned **not refuted** (medium confidence). scope-adherence and invariants were auto-added by the harness on top of the 3 refuters requested.
- Weak spots the refuters named:
  - The known-absent vs known-true comparison tests the new code against itself. The goldens anchor the schedules to base, but not the per-step info.
  - Seed base 13 is cherry-picked (above).
  - The regression refuter could not finish the full gate inside its timeout.

## Gate (run by me on PR head 5b12414)
- `.venv/bin/python -m unittest discover -s tests`: `Ran 874 tests ... OK (skipped=1)`. The skip already existed: the sticky test is skipped when WR_STICKY_PHASEA is unset.
- `WR_STICKY_PHASEA=<main>/results/closed_loop_sticky/phaseA .venv/bin/python -m unittest discover -s fleet/tests -p 'test_*.py'`: `Ran 828 tests ... OK`.
- GitHub `gate` check: SUCCESS.
- After the merge I re-ran `tests.test_disturb_blind` on master: OK.

## Queue item `wr-s10c-blind-run` (not run)
- Every flag in its command exists in `--help` of emit, ingest, costmap, lessons, grade, hotspot_score and time_to_detect.
- Its `--disturb` JSON passes `validate_config` on merged code.
- The emitter writes `truth.json` (TRUTH_FILE) next to the run.
- No change was needed. Its dependency `wr-lane-s10c-blind-blockage` is now satisfied.

## Housekeeping / traps
- The main checkout was left on a **detached HEAD at 5b12414**, which is the known refuter trap. There were no tracked modifications, so I ran `git checkout master` and fast-forwarded. The lane worktree `.claude/worktrees/wf_fd0c1a6f-559-2` is left in place.

SCHED_RESULT: OK S10C merged PR #40 7bebef4; gate 874 OK (1 pre-existing skip) + fleet 828 OK; smoke overlap 130/174 = 0.747 at pinned seed base 13 (seed base 0 gives 0); wr-s10c-blind-run command valid

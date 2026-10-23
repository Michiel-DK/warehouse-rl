# wr-lane-s3e — S3E-INFORMED-RECOVERY (13 Oct 2026)

- PR: https://github.com/Michiel-DK/warehouse-rl/pull/9, **MERGED** (squash), merge sha **a8e9c81**
  (`a8e9c8113a8e09364d642c4bb52120525dfb1ffe`). Branch `worktree-wf_0a2ae569-d31-2`, final head d29ea37.
- Main checkout on `master` fast-forwarded to a8e9c81. Brief: `reports/wr-lane-s3e-brief.md`.

## Read this before the sweep runs (operator)

1. **Flag mode re-arms its own timeout while the blocker stays frozen.** `informed_timeout` (flag) reroutes on every
   stuck event while the robot ahead is frozen. A successful reroute resets the StuckCounter, so the abandon at 15
   never fires for the length of the breakdown. This is what the stub specified (reroute at once, else timeout), but
   it is the same counter-reset dynamic that sank lane D. The correctness refuter's 2-seed probe (medium map, rate 8,
   seeds 0-1, not a measurement) saw more stuck-busy agent-steps than timeout: 689 vs 494 (seed 0), 988 vs 727
   (seed 1); flag made 331 decisions with a frozen blocker and rerouted on all 331. Read sweep e with this in mind:
   a flat or negative result may be the reroute loop, not "the information is worthless".
2. Same probe: timeout, informed flag and informed left gave identical pick-rates on both seeds (24.48, 33.12).
   Anecdote on 2 seeds x 500 steps, not a result; no numbers went into the README.

## Path-ordering finding

`agent.path[0]` is the **next** cell, `path[-1]` the target. Evidence in `vendor/tarware/tarware/warehouse.py`: the
micro-action is computed toward `path[0]` (W:370, W:380) and `_execute_forward` moves then does
`agent.path = agent.path[1:]` (W:516-519). Tested (`test_path_zero_not_path_last_is_the_next_cell`; mutating to
`path[-1]` fails 7 tests). `find_path` can keep the start cell (`astar_path[1 - int(grid[start] > 1):]`, W:307), so
the hook uses `path[1]` when `path[0]` is the agent's own cell; the correctness refuter found that case effectively
dead (only the picker `start_fix` keeps a start, and there `path[0]` is already the neighbour cell). Harmless.
Timing: `resolve_move_conflict`/`resolve_stuck_agents` run before the moves and before `_build_info`, so during a
decision `DisturbedWarehouse._t` is the executing step and `frozen_now()` / `frozen_schedule[aid, _t:]` describe the
step the decision affects. The correctness refuter recomputed both keys independently (grid layers + raw schedule)
over 3838 real decisions: 0 mismatches.

## What merged

- `RecoveryHook.OBS_KEYS`: old 12 unchanged + `blocker_frozen`, `blocker_frozen_left` (obs dict built with
  `zip(strict=True)`). `blocker_frozen_left` is look-ahead (optimistic fleet-manager-knows-repair-time variant).
- Diagnostics `decisions_while_blocker_frozen`, `reroutes_while_blocker_frozen` in `RECOVERY_INFO_KEYS` and
  `evaluate.RECOVERY_SUMS`: every recovery row now carries them (committed a-d rows lack them; resume and plots do
  not read them, checked by the regression refuter).
- `InformedTimeoutRecovery`, registry `informed_timeout` (flag) / `informed_timeout_left` (left), default (5, 15).
- `learned_recovery`: 14 keys, `FORMAT_VERSION = 3`, v2 refused ("checkpoint version 2 != required version 3 ...").
- `scripts/recovery_sweep.py` letter `e` = `informed` (default `--only` stays a,b,c,d).
- README "Informed recovery (lane E)" stub (no numbers), SCOPE two-key definition + look-ahead caveat.
- Two existing tests outside the brief's named list were relaxed only for the two new counters
  (`tests/test_recovery.py:456`, `tests/test_recovery_heldout.py`); regression refuter confirmed everything else is
  still pinned.

## Review rounds

Process deviation: pass 1 ran through `single-lane-build` (run wf_0a2ae569-d31). Pass 2 was NOT a second
single-lane-build run, because that would have opened a second PR (forbidden); it was fixes on the same branch plus a
manual round of 3 fresh-context opus `verify-gate` refuters, one worktree each. Its one finding was fixed and
re-verified by the same refuter.

| Round | Head | correctness | regression | test-honesty | other | gate |
|---|---|---|---|---|---|---|
| 1 (workflow, sonnet refuters) | 2f37052 | not refuted | not refuted | **REFUTED**: max-over-occupants mutant survived; plot test checked PNG bytes only; random table never set the flag | scope-adherence, invariants: not refuted; python-reviewer pass (nits) | 220 OK (refuters) |
| 2 (opus) | 82d25f2 | not refuted (medium-high) | not refuted (high; re-ran 49 committed a-d rows, all identical minus the 2 new keys) | **REFUTED**: a one-step-late frozen mask survived (all scenarios started at t0=0); version-digit asserts satisfied by the file name | | 223 OK |
| 2 re-verify (same refuter) | 5991ec5 | | | not refuted (medium-high); mutants 10, 31, 31b/c, 09, 07, 08, 16, 25, 26 red | | 224 OK |

Final commit d29ea37 is comment-only (fixes an inaccurate `# inject:` comment the refuter flagged); module re-run OK.
I ran my own fix mutations red too (max->first, left gate, flag gated on _left, timeout band off, band from `rows`,
lagged mask, early mask, version text stripped), each isolated, clearing `__pycache__` (a same-length edit restored
within one second reused stale bytecode once and gave a false gate failure, 223/1, cleared and re-run green).

## Verification on master (a8e9c81)

- Pre-lane gate on d607a47: `Ran 203 tests ... OK`.
- Sprint 1 regression: `.venv/bin/python -m unittest tests.test_regression_cta` -> `Ran 6 tests in 12.913s OK`.
- Sweep e smoke: `recovery_sweep.py --smoke --only e --workers 2 --results-dir /tmp/s3e_smoke` -> 8 rows,
  `total 9.5 s` (wall 10.07 s); rerun `[informed] 0 jobs to run (8 rows already on disk)`. (Empty smoke dir, so the
  timeout band/delta warned as designed; the full run reads the committed `results/recovery/timeout.json`.)
- Full gate on master a8e9c81: `Ran 224 tests in 469.506s OK` (exit 0); tracked tree clean.

## Next queue item (wr-s3e-informed-sweep): exact command

```sh
cd ~/code/Michiel-DK/warehouse-rl && .venv/bin/python scripts/recovery_sweep.py --only e --workers "$SCHED_WORKERS"
```

240 episodes (2 configs x 4 rates x 30 seeds, 500 steps, medium map). Writes `results/recovery/informed.json` after
every row (resumable) and `results/recovery_informed.png`; the timeout band and paired delta read the committed
`results/recovery/timeout.json`. Full sweep NOT run in this lane.

## Housekeeping

Remote branch `worktree-wf_0a2ae569-d31-2` and local worktree `.claude/worktrees/wf_0a2ae569-d31-2` left in place
(no `--delete-branch`, as in lane D). Refuter worktrees `agent-a64b599f...`, `agent-aeadc0e3...`, `agent-a2d22265...`
hold only untracked `.venv`/`vendor` symlinks. `/tmp/s3e_*` logs.

SCHED_RESULT: OK

# S15A lane: naive stall baseline (`fleet/stall_baseline.py`)

Date 2026-10-23. Lane `single-lane-build`, tier standard, build model sonnet, base master. PR #56, squash-merged as
`a0a1854` on origin/master. Local master took it as merge commit `2df6598`, because it holds 7 unpushed public-repo prep
commits (operator: "hold till done") and cannot fast-forward. Origin was not pushed beyond the PR merge.
Queue item `wr-s15a-run` written in laptop-scheduler `d49210a`. It has not been run.

## What was built

- **`fleet/stall_baseline.py`** runs every rule on the same stream and writes one deterministic JSON
  (`results/fleet/stall_baseline.json`, sorted keys, no wall-clock). The rules are N0-30, N0-60, N1 and N2-30/60/120/180
  from LITERATURE Part 8 §1, plus ours (station-aware, radius 1 on MoRoOp, servicing bound auto). It covers the nine
  MoRoOp shifts and the five `wr-s14d-rerun` sim runs.
  - The N0 rules and ours run through the existing `Detector`.
  - The label match is `adapters/moroop.label_comparison`, called unchanged, with `run_intervals` swapped for each rule's
    episodes.
  - The sim match is `fleet_analyser/score.score_run`. All of these are reused by import.
  - N1 and N2-W are position rules, not the Detector, and the script says so in its docstring and in the JSON.
  - The full `--moroop` path exits 1 if N0-30 `stuck_runs != 567`.
  - The store guard refuses an original store. Every `store*` of every run is hashed before and after the run.
- **`fleet/tests/test_fleet_stall_baseline.py`** has 31 tests: the synthetic six-stop stream, the 2 m boundaries, the gap,
  CLI = in-memory, byte-identical output, the store guard, and the MoRoOp shift-1 smoke.

Window convention, binding: (t-W, t] in event time, with position as a right-continuous step function. The window's
position set is therefore the position carried at t-W plus every message in (t-W, t]. Under this convention N2-W fires
at exactly stop+W (with no alert at stop+W-1), and N1 fires at stop+660.

The first attempt was halted by the criterion pre-review. It found that "half-open window" and "alert at stop+W" contradict
each other under a grid-sample reading (that reading puts the alert at stop+W-1). The fix was to define the window as
above. The alert times were not changed.

## Gate and review

- **Gate** on the rebased branch: `.venv/bin/python -m unittest discover -s tests` printed `Ran 1178 tests in 772.096s` /
  `OK (skipped=9)`, exit 0. The 9 skips are existing s10-none data skips.
- **Smoke** (`--smoke`, shift 1): wall time 1.1-1.8 s. Shift-1 counts are N0-30 59, N0-60 1, N1 0, N2-30 447, N2-60 83,
  N2-120 8, N2-180 1, ours 1.
- **Refuters, first round:**
  - Test-honesty, scope-adherence and invariants did not refute.
  - Correctness refuted. PR #56 showed 6 files, because the branch carried the operator's unpushed master commits
    (LICENSE, docs, reports). The fix was to rebase onto origin/master, without pushing master. The PR then listed only the
    two declared files.
- **Python-reviewer, one major finding:** alert latency fell back to the label start when no stopped run overlapped the
  label. Fixed in `10b1cc0`: latency is now null in that case.
  - Added `test_label_without_stopped_run_has_null_latency`. I checked that it fails with the old line swapped back in.
  - A fresh verify-gate refuter did not refute the fix.
- **Minor findings, accepted and disclosed:**
  - The smoke skip condition is wider than the brief's. Deviation 7: CI has `fleet/data/moroop/stations.json` but no raw
    data.
  - The N0 rules and ours have no alert-time assertions to the second. The criterion asked for them only for N1 and N2-W.
  - The gap comparison is inlined. timebudget exposes no function for it.

## Deviations from LITERATURE Part 8, as built (from the PR body)

1. N1's diagonal is the Euclidean cell diagonal × 0.5 m. Part 8 gives no formula.
2. On the sim, ours uses station radius 0, which is what the sim `-sb` stores used: the episode totals match `-sb`
   `detector_episodes` on all five runs. On MoRoOp it uses radius 1. Both are recorded in the JSON.
3. On the sim, N0 rows keep the Detector's `faulted_self` episodes (score_run excludes them). N1 and N2-W have no error
   logic.
4. The box-stillness span and the "stop start" (the first driving-false run overlapping the label) are defined in the
   script. N2-W latency can be negative: box stillness can begin before the driving flag goes false.
5. MoRoOp is read from `jsonl-sb`. The old `jsonl/` is gone. The dev run reproduced the 567, which confirms the swap is
   equivalent.
6. A window that starts before a robot's first message is not evaluated.
7. The smoke test skips when the raw parquet, `jsonl-sb` or pyarrow is missing, not only when `fleet/data/moroop` is absent.

One more choice, from my brief rather than Part 8: an empty orderId anywhere in the window makes N1/N2 false. This is the
"carry orderId forward" gate, applied per grid second.

## The refute line

LITERATURE Part 8 §3, S15A, quoted: "Commodity if any N2-W, N1 or N0-60 on MoRoOp reaches 2/2 labelled hits with ≤ 12
stuck runs (2× our 6). **Supports the lead** if none does. A "supports" result shows only that station logic plus the
bound removes the alarms: InOrbit customers can write that logic (COMPETITION pass 4 scores it present as a configurable
rule), so the page may say "not in the documented example", never "a vendor can't"."

**Where the result sits: provisional, on the lane's dev run, which was not committed.** The builder ran all 9 shifts and
5 sim runs (about 54 s on 4 workers) and reported these MoRoOp counts (stuck runs / hits / misses / false alarms):

| rule | runs | hits | misses | false alarms |
|---|---|---|---|---|
| N0-30 | 567 | 2 | 0 | 544 |
| N0-60 | **10** | **2** | 0 | 6 |
| N1 | 1 | 0 | 2 | 1 |
| N2-30 | 4033 | 2 | 0 | 3946 |
| N2-60 | 818 | 2 | 0 | 783 |
| N2-120 | 55 | 2 | 0 | 52 |
| N2-180 (documented) | 7 | 1 | 1 | 5 |
| ours | 6 | 2 | 0 | 5 |

- N0-60 (the driving-flag rule at 60 s, no station logic) reaches 2/2 hits with 10 stuck runs, which is ≤ 12. **On the
  pre-set line that makes the result "commodity", not "supports".**
- The two InOrbit position forms do not reach the line. The documented N2-180 misses one of the two labels. N1 misses
  both. N2-120 hits both but raises 55 runs.
- Ours and N0-30 reproduce their old figures exactly (6/2/0/5 = `moroop_label-sb.json`, 567/544 = `timebudget_moroop.json`).
  For the first time, both come from one script under one definition.

Caveats on that reading:
- These are the builder's numbers from an uncommitted dev run. I did not re-run them. They count only after `wr-s15a-run`
  writes `results/fleet/stall_baseline.json`, and its SCHED_RESULT line applies the refute line automatically.
- There are two labelled stops of ≥ 30 s, both in one shift. "2/2" is a very small sample.
- N0-60 has 6 false alarms against ours 5. The gap between a 60 s timer and the station-aware bound on this lab log is
  one alarm.

The page claim this lane was meant to support, "our station filter removes the false alarms a naive rule raises", holds
against the 30 s rule (567 → 6). On the pre-set line, it does not hold against a plain 60 s stillness timer.

## Next

- `wr-s15a-run`: 4 cores, about 5 min, not exclusive. `wr-s14d-rerun` measured 2.0 min (`state/done.json`), not the
  "about 10" in the brief.
- The S15 readme item (`wr-dev-s15-readme`) depends on it and S15B. The operator decides the page wording.

SCHED_RESULT: OK S15A merged PR #56 -> a0a1854 (local master 2df6598, held commits unpushed), gate 1178 OK, wr-s15a-run command written (laptop-scheduler d49210a, not run); dev run puts N0-60 at 2/2 hits with 10 runs -> refute line reads commodity, pending the queue run

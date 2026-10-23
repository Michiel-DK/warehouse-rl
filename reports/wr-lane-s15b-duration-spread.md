# wr-lane-s15b-duration-spread: OTTO-style job-duration spread vs the blocking number vs truth

Lane job, 23 Oct 2026, unattended. **Built and merged; not measured.** The verdict comes from the queue item
`wr-s15b-run`, which is installed and has not been run (CLAUDE.md: measurements go through the scheduler).

## Outcome

- PR #55, squash-merged as `036c50e` on origin. Files: `fleet/duration_spread.py`,
  `fleet/tests/test_fleet_duration_spread.py` (44 tests), `fleet/requirements.txt` (scipy as an optional extra), and
  `fleet/tests/test_fleet_hotspot.py` (a one-line exemption, explained below).
- Queue item `wr-s15b-run`: command written (laptop-scheduler `bd8aef5`). Cores 2, est 3 min, max 30. It runs a
  sha256 snap and cmp over the five `-sb` deadlock files, the run streams, truth.json, emit_ledger.json and every
  pre-existing `results/fleet/*.json`. It prints `SCHED_RESULT` to stdout with the verdict read from
  `results/fleet/duration_spread.json`.
- Timing: the smoke (s10-none zone 0) takes 0.6 s in `main()`. A trial of the full s10-none run (10 zones, 2 workers)
  took 4.3 s; the builder wrote that output to /tmp and did not commit it.
- Gate on PR head `28ef5c9`: `Ran 1185 tests`, **1 failure**, 9 skips (pre-existing). The failure is
  `fleet.tests.test_fleet_s8o_step4_label.TestOverviewStep4.test_committed_page_is_a_fresh_build`.
  - It **fails on master too, and has since `bacfab7`**: the operator's report-path edit changed the committed
    `docs/overview/index.html` to `reports/...`, while `overview_build.py` still emits `laptop-scheduler/reports/...`.
  - This PR does not touch it. I merged on that basis; the operator should fix master's overview build separately.
- The final head `3bde391` adds tests only. On merged master, the new file plus the hotspot and time_to_detect
  isolation suites: `Ran 180 tests ... OK`.

## The refute line (docs/LITERATURE.md Part 8 section 3), quoted

> **S15B.** Commodity if, for either decisive statistic, the median over runs of ρ(statistic, blocking number) is ≥
> 0.7 with median top-3 overlap ≥ 2/3, **or** ρ(statistic, truth) ≥ ρ(blocking, truth) in at least 3 of the decided
> runs. **Supports the lead** only if both decisive statistics have median ρ with the blocking number < 0.4 **and**
> the blocking number beats both on truth in at least 4 of 5 runs. Anything else is reported as mixed. All
> thresholds are ours, set here before the run.

**Result against it: pending `wr-s15b-run`.** The verdict is computed in the script (`duration_spread.verdict`, a
pure function), never by hand. The output carries the quoted line, the per-condition numbers and the verdict. The
smoke's one zone leaves every pair undecided, so the smoke verdict is "mixed" by construction; it is not a result.

## What it computes

- **Jobs:** AGVs only; pickers are excluded through `stations.auto_layouts` and `kinds_of`, because they do carry
  orderIds on these streams. Messages come from `timebudget.kept_messages`.
  - A job is a maximal run of one non-empty orderId.
  - Duration = the ts of the first later message with a different orderId, minus the job's first ts.
  - Excluded and counted: `open_at_start` (wins when a job is open at both ends) and `open_at_end`.
  - Tallied: `ended_to_idle` vs `ended_to_new_order`. The emitter gives a new orderId on a target change, so a reroute
    ends a job. Jobs with a gap over 60 s are also tallied, and stay in.
- **Statistics:**
  - Decisive: `p95_over_median` (TTTR form) and `mean_s` (OTTO's figure).
  - Descriptive: buffer index, CV (ddof 0), and the same four on duration / free-flow.
  - Free-flow = 5 s × max(1, Manhattan distance along the waypoints). The waypoints are the first cell, the first cell
    of each driving-false run inside the job, and the last cell carrying the orderId.
  - Percentiles use numpy's default linear rule. Zones with fewer than 5 completed jobs get null, and are counted.
- **Agreement:** per run only.
  - Spearman ρ on average ranks, and Kendall τ-b, both computed in numpy.
  - The τ-b p-value comes from scipy `kendalltau(variant='b', method='auto')`. scipy is checked when the CLI starts;
    without it the CLI exits non-zero.
  - Top-3 overlap uses the tie-break (value descending, zone id ascending) and reports the boundary-tie count next to
    the chance value 9/n.
  - A constant column or fewer than 3 zones gives null, counted as undecided.
  - Medians are taken over decided runs only. The output notes that at n = 10 a ρ near 0.65 is about the p < 0.05 line.

## Deviations from the brief (each also in the output's `deviations` list)

1. **Truth source.** The brief said truth stuck seconds come from truth.json, but truth.json has no stuck episodes.
   It holds floor, blocked, outage and frozen windows; closed-loop-sticky's is a v1 file.
   - Used instead: `fleet_analyser/score.py`'s definition (`benchmark.json` `batch.score.truth_definition`), via
     `score._load` and `_truth_runs`, imported. Episodes are kept when end − start ≥ 30 s (score_run's rule).
   - The truth rate = truth stuck seconds / the deadlock file's `zones[z].robot_hours`. That denominator includes
     pickers; it is the same one the blocking number uses.
2. **Message sets differ.** Jobs read `kept_messages`, which drops a message whose ts is ≤ the previous ts. Truth reads
   `score._load`, which drops nothing and includes pickers. The output counts the dropped messages per zone.
3. **Isolation-scan exemption.** `duration_spread.py` was added by name to the exempt list in
   `test_fleet_hotspot.TestAnalystIsolation`, the same treatment as `time_to_detect.py` (an evaluation script that
   nothing in the analyser imports). It is a fourth tracked file beyond the declared three.
   - The builder had first dodged the scan by spelling the word `"tru" + "th"`. python-reviewer failed that, and I
     replaced it with the honest exemption.
4. **Absolute paths in the output.** The output records each deadlock file's path as absolute (with the home
   directory) plus a sha256. Scrub it before any public copy of the results file.
5. **Two refuters became five verify-gate runs, plus scope-adherence and invariants.** The harness adds those two
   refuters automatically when `declaredFiles` and `repoInvariants` are set.

## Review round (pass 1 of the workflow, then main-loop fixes)

- The criterion pre-review halted the first launch. `fleet/data` is gitignored, so a lane worktree has no s10-none
  data. The fix: the tests resolve data from this checkout or the main one and skip only when both lack it (repo
  convention).
- On the build:
  - The correctness, scope-adherence and invariants refuters did not refute.
  - The test-honesty refuter refuted: the truth column was untested.
  - python-reviewer failed the split-word workaround.
- Main-loop fixes, each re-verified by re-running the named mutants (all now killed):
  - **`b3b028a`:** the exemption replaces the workaround; truth-column tests cover the keep rule, the interval, the
    sum, the robot_hours denominator and the copied blocking field.
  - **`16c4946`:** an exactly-30 s episode, and `STUCK_AFTER` pinned to `score_run`'s default. A threshold of 35 and
    `>` in place of `>=` had survived.
  - **`28ef5c9`:** statistic-name wiring (a `mean_s` → `median_s` miswire had survived) and every supports condition
    (strict beat, both statistics, both medians < 0.4, a null blocking ρ).
  - **`3bde391`:** direct values for the median and p95 ratio, Spearman on ranks versus raw values, a partial top-3
    overlap, a constant second column, gap jobs kept, commodity before supports at 7 runs, and zero robot-hours.
- A re-verify correctness refuter on `b3b028a` did not refute. The smoke output is byte-identical to the
  pre-fix output, apart from a capital T in one deviation string.
- **Known remaining survivors are descriptive only:** the waypoint free-flow slice, the gap tally range, the zero-median
  null and the waypoint `prev_driving` flag. They do not feed the verdict.
- **Not re-verified by a fifth refuter:** whether further decisive mutants survive after `3bde391`. Each refuter round
  so far found new ones, so the suite is stronger but not proven complete.

## Merge incident (needs the operator's eye)

- Local master held 7 commits that were not on origin: `ee30641..bacfab7` (licence, harness submodule drop, reports
  copy, LITERATURE Part 8 and its fixes, COMPETITION passes 3 and 4). I had rebased the lane branch onto local master,
  so **the squash `036c50e` on origin folds those 7 commits' content into the one S15B commit.**
- The repo is private (`gh repo view`: `isPrivate` true), and the content is the operator's own committed work.
- I did not force-push master. Local master is now `76f4e15`, a merge of origin/master. Its tree equals `036c50e`
  (checked with `git diff --quiet`). It keeps the 7 individual commits, and `backup/master-pre-s15b-merge` points at
  `bacfab7`. Local master is ahead of origin by those commits plus the merge, and is not pushed.
- If the operator wants origin's history to show the 7 commits on their own, that takes a force-push of master. That
  is their call.

## Open for the readme item

- Read `results/fleet/duration_spread.json` → `verdict` after `wr-s15b-run`.
- With 5 runs, at most one closed-loop-sticky run has n = 30; the other four have n = 10, so ρ is coarse.
- Jobs end on a reroute (new orderId on a target change), so blocking-heavy zones may show shorter, not longer, jobs.
  Check `ended_to_new_order` before reading a low ρ as "spread misses blocking".

SCHED_RESULT: OK wr-lane-s15b-duration-spread PR #55 merged (036c50e), wr-s15b-run command installed (bd8aef5, not run); gate 1185 tests with 1 pre-existing master failure (overview page freshness since bacfab7); squash folded 7 unpushed local docs commits into 036c50e, local master merged not force-pushed

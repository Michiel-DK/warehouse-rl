# wr-lane-s10b-ttd-change — 18 Oct 2026

**Result: MERGED.** PR #38 was squash-merged as `6ae3e00` on master, and the main checkout was fast-forwarded to it.

`fleet/time_to_detect.py` now takes `--truth-kind blocked|outage` (default `floor`, unchanged). It measures, per truth window:
- how long the top-K map takes to flag a cell after it gets blocked;
- how long the map keeps flagging the cell after it clears.

## What was built
- **Per window** (half-open `[start_step, end_step)`, on the truth file's clock via `truth.step_of`):
  - `first_detect_s`: the first publish with start ≤ step < end where the cell has rank ≤ K. Detection counts only while the window is open.
  - `preflag`: the cell was in the top K at the last publish before the window started. This is not counted as a detection.
  - `missed`: no in-window flag.
  - For detected windows only, one of three outcomes:
    - `cleared_s`: the first publish at or after end_step where the cell is not in the top K;
    - `stale_at_end`: flagged at every publish after the end;
    - `open_at_end`: no publish at or after the end, so clearing could not be observed. These windows are censored, not stale.
- **Per-K summary:**
  - counts: n_windows, n_detected, share_detected, missed, preflag, stale_at_end, open_at_end;
  - p25/median/p75 of `first_detect_s` and of `cleared_s`;
  - false flags per publish. A flag counts as false only when S10A's `truth_positive(truth, zone, cell, s, s)` returns empty, with s the publish step. That makes a flag on a cell whose window is open at that moment not false.
- **Run name:** the s10 stores are keyed `run=s10-blocked` / `s10-outage`, not `closed_loop`. For window kinds the run is read from `DIR/store/ingest_runs.jsonl`. It must have exactly one run; otherwise, or if the file is missing, the tool raises ValueError. The floor path keeps `closed_loop`.
- **Meta for window kinds:** adds truth_kind, run, n_windows and window_len_steps_median. The caveat becomes "Windows have a start and an end; detection is measured from the start, clearing from the end."
- **Errors:** a v1 truth with a window kind raises. A truth `t0` that differs from a zone's first message ts also raises.
- **Floor output** is byte-identical to before. A sha256 produced by the unmodified master code (24cb0b7) is pinned in the test, and the test-honesty refuter re-ran that script on master and got the same hash.
- **Files changed (4):** `fleet/time_to_detect.py` and `fleet/tests/test_time_to_detect.py`, the two the brief declared, plus two the brief did not name:
  - `fleet/tests/test_fleet_truth_v2.py`: one allowlist line. The import fence allowed only grade.py and hotspot_score.py to import `truth`.
  - `fleet/truth.py`: docstring sentence only. It said time_to_detect.py keeps v1 rules.
- **Horizon:** phase A ran costmap with `--horizon-s 1245`; the rerun uses the default 3600. Rank does not depend on horizon (costmap.py:47-76). False flags use a point query, not `forecast_steps`, so the horizon does not enter the numbers.

## Review round
- **Criterion pre-review halted 3 times before any build, each on a real wording defect in my criterion:**
  1. Non-verbose unittest prints no test names.
  2. "0 skipped" cannot hold in a worktree without untracked data. Fixed by setting `WR_STICKY_PHASEA` and requiring a skip count no higher than master's.
  3. Clause 4 had to say *detected* window for open_at_end.

  Each time I adopted the reviewer's suggested rewrite whole. The 4th pass was sound.
- **python-reviewer:** pass. The minor finding is noted below; the nits were left as they are.
- **Refuters:**
  - correctness: did not refute.
  - test-honesty: did not refute, and re-ran the golden script on master to the same hash.
  - invariants: did not refute.
  - scope-adherence (auto-added): **refuted**. I overrode it on evidence:
    - (a) The t0 check is in the brief ("Assert epoch(truth t0) == each zone's first message ts (raise otherwise)").
    - (c) The summary and window fields it called extra (share_detected, preflag, missed, false_flags_per_publish_mean, rank_at_detect, false_flag_cells) are all listed in the brief.
    - (b) The one genuine extra is `validate()` rejecting `--smoke --truth-kind X`. The smoke dir only has floors, so this guard is correct and tested. I judged it not a defect.

  ⚠️ This is a merge over a refutation, on my judgment, not a refuter re-run.
- **Gate:** CI `gate` passed on head 839a1a9. Locally with WR_STICKY_PHASEA set, master gave `Ran 828 tests`, OK, 0 skipped, and the PR head gave `Ran 846 tests`, OK, 0 skipped (builder's run, quoted in PR #38).

## Lane smoke (PR #38 body; builder-run, not re-run by me)
- **Data:** the s10 data on the main checkout, 9 publishes. Wall time 3 s (blocked) and 2 s (outage).
- **Clean-up:** decisions.jsonl sha256 was unchanged in both directories. I checked that no `store-ttd-*` directory remains (`ls` matched nothing).

| run | K | windows | detected | missed | preflag | stale at end | open at end | first detect s (p25/med/p75) | cleared s (p25/med/p75) | false flags / publish |
|---|---|---|---|---|---|---|---|---|---|---|
| blocked | 10 | 50 | 6 (0.12) | 44 | 1 | 1 | 2 | 117.5/187.5/242.5 | 95/155/172.5 | 83.0 |
| blocked | 20 | 50 | 7 (0.14) | 43 | 2 | 2 | 3 | 140/190/232.5 | 910/970/1030 | 135.8 |
| blocked | 40 | 50 | 7 (0.14) | 43 | 2 | 4 | 3 | 140/190/232.5 | none | 154.6 |
| outage | 10 | 20 | 1 (0.05) | 19 | 0 | 0 | 1 | 280 (single value) | none | 85.0 |

- The outage rows for K=20 and K=40 are the same as K=10, except false flags (139.0 and 157.1).
- These are smoke numbers on /tmp output, not the queue result. The queue item writes `results/fleet/time_to_detect_{blocked,outage}.json`.

## Notes for the operator
- **The map rarely sees a blocked cell.** It catches 12–14% of blocked windows and 5% of outages. When it does, the median is about 3 minutes. At K=10 most top-K flags are false: 83 per publish over 10 zones, so at most 100 flags. Offer 2's "minutes until flagged" has a small numerator; expect the queue run to say the same.
- **False flags count matches of any truth kind.** A blocked-kind run counts a flag on a floor cell or an outage window as not false (python-reviewer minor, pinned by `test_matched_kind_of_any_type_is_not_false`). The s10 dirs have no floor cells, and each holds only its own kind of window, so the s10 numbers are unaffected.
- **Queue item `wr-s10b-ttd-change-run`:** the fixed command, unchanged. Both argvs pass `build_parser` + `validate` on merged master (checked). It was not run here. Expect seconds of single-process CPU, judging by the smoke.
- **Clean-up check:** the builder's temp master worktree `/tmp/ttd_master_wt` was removed (builder report). I did not check the lane worktree `.claude/worktrees/wf_e0acf2b9-f23-2`.

SCHED_RESULT: OK S10B merged PR #38 -> 6ae3e00 (--truth-kind blocked|outage, floor byte-identical, CI gate green, 846 tests OK 0 skips; scope refuter overruled on brief text); smoke blocked 12-14% windows detected median ~190 s, outage 5%; queue item wr-s10b-ttd-change-run valid, not run

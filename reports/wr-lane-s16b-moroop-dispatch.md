# S16B lane: MoRoOp dispatcher events and the authors' cleaning (`fleet/moroop_dispatch.py`)

Date 2026-10-23. Lane job `wr-lane-s16b-moroop-dispatch`, `single-lane-build` run wf_7e229898-78a (tier standard, Sonnet
builder, refuters: correctness and test-honesty). **PR #58, squash-merged as 010b257 on origin/master.** Local master
took it through merge commit 31897c2, because local master holds unpushed public-repo prep commits (17 ahead) that stay
held. Master was not pushed.

## What was built

- `fleet/moroop_dispatch.py`, CLI `--raw DIR --label results/fleet/moroop_label-sb.json --out results/fleet/moroop_dispatch.json [--smoke]`.
  It imports the adapter's functions and does not edit `fleet/adapters/moroop.py`. It reads `robot_state_raw` directly,
  so no table parameter was needed and the `-sb` outputs could not change.
- `fleet/tests/test_fleet_moroop_dispatch.py`, 35 tests: the 6 the brief asked for plus mutation-driven additions (below).
- Queue item `wr-s16b-run` installed: laptop-scheduler 7617280, cores 1, est 3 min. It pins the label sha256 `d8635c21…`,
  which matches the main checkout. It hashes every pre-existing `results/fleet/*.json` (except the output) and the raw
  tree before and after. It prints a FAIL line if the pin, the hashes or the Python step fails, and its OK line carries
  both verdict words. The command passed `zsh -n` and was not run.

## Rules and deviations from LITERATURE Part 9

- **Auto-pause.** Part 9 says "a pause whose previous event is a denial of the same operation with retry_count ==
  max_retries". Pause events carry no operation id, so the implemented rule is: the immediately previous
  `dispatch_events` row in the shift is an `operation_start_denied` with integer `retry_count == max_retries`. That row
  may be of any type, ordered by `(created_at, table order)`. The brief mandated this reading.
- **Extra rule-drop reason** beyond json / timestamp / type. A raw row on which the adapter's conversion raises counts
  as `convert:<ExceptionType>`. Rows with unparseable diagnostics count as `diagnostics_unparseable`, following
  `rows_unparseable`. The parser can also return `missing:<key>`, and that reason is kept as returned. None of these
  fired on the real data: 0 rule drops.
- **Stuck episodes** are every entry of `episodes_ge_30s.list` and `false_alarms.list` in `moroop_label-sb.json` (our
  `-sb` detector runs), each taken as `[start, start + duration_s)`. "Near" means `[start-120, start)` before and
  `[end, end+120]` after. Shift start is the first `robot_state_cleaned` row of the shift.
- The word "human" is not claimed anywhere.

## Numbers (main-loop re-run of the merged code, 9 shifts, 14 s, output in /tmp, not committed; the queue item writes the file)

- **Dispatcher verdict: "marks the intervention".** There are 3 external calls:
  - a pause at 2026-07-30 06:01:31, not near any episode;
  - a resume at 2026-07-30 07:11:22. It is 46.6 s after the end of the 3,245 s episode (06:16:31), and inside the
    following 47 s episode (07:10:44);
  - a resume at 2026-07-31 12:25:42, 24.4 s after the end of the 127 s episode.

  The two resumes are the 2 interventions. That pause and that resume bracket the whole 3,245 s episode. This is
  reported, not interpreted.
- **Classes:** "dispatcher refused" 41 (39 denials and 2 auto-pauses), "external call" 3, "shift start" 9 (resumes
  before the shift's first `operation_started`), "neither" 10. **11 resumes against 3 pauses:** 3 resumes have a pause
  before them in the table, 8 do not. No explanation is asserted.
- **Cleaning verdict: "we keep theirs".** Raw rows 140,386, cleaned 137,427. The authors removed 2,959, and our rule
  drops are 0, so `both_drop` is 0, `ours_only` is 0 and `authors_only` is 2,959 (100 %). Collapse drops are a separate
  column: 6,444 in all, of which 1,314 are in `authors_only` and 5,130 in no set. Cleaned ids not in raw: 0.
- **Profile of the authors-only rows** (builder's PR body, same code): state Navigating 2,645 / Idle 314; all
  Autonomous; diagnostics max level Ok 2,758 / Warning 184 / Error 2 / none 15. pos_x ranges from 0.39 to 8.21 and
  pos_y from -1.84 to 0.41. Velocities lie within normal motion and none is None or non-finite. These rows show no
  "implausible value" signature, and our rules reject none of them.
- **Page sentence** (`page_sentence_holds` true): "No row of the authors' cleaned table was rejected by our parser; the
  authors had already removed 2,959 of 140,386 raw rows (2.1 %)".

## Review round

- Criterion pre-review: sound, 4 advisories.
- Correctness refuter: not refuting.
- Invariants refuter: not refuting.
- python-reviewer: pass. Minor findings: the queue command printed no FAIL line on a Python crash, which the main loop
  fixed in the installed command. The page_sentence lead is fixed text, and `page_sentence_holds` carries the check.
- **Test-honesty refuter: REFUTED.** Replacing the auto-pause `retry_count == max_retries` check with `True`
  survived, and the external-call filter in the dispatcher verdict was untested. The main loop fixed this over three
  re-verify rounds, all test-only commits:
  - c57f463 killed both mutants.
  - A re-verify refuter ran 50 mutants. Survivors were the "neither" class, the case with no `operation_started`, exact
    window edges, the nearest episode, the "mixed" rule and the parser-reject rule drop. 57cb32d added tests for them.
  - A second re-verify refuter ran 51 new mutants. Survivors were pooling across shifts, the diagnostics level order,
    the state row at ts, inside-vs-near, ties, the auto-pause guards, the 1 µs shift-start tie, collapse per set, and
    scope / sha / sorted keys. a69b37f added tests for them.

  Final state of both refuter harnesses on a69b37f: every non-equivalent mutant is killed. The survivors are
  `autoPrevAnyType`, `autoMaxIsThis`, `verd_order`, `page_pct`, `inter_scope`, `firststarted_first`, `deltaAbs` and
  `dispNoEvScope`. Each is equivalent on the inputs the module can see: retry fields appear only on denials, pauses
  carry no meta, the two sets are disjoint, `starts` is sorted, deltas are non-negative by construction, and the
  intervention start is unique. The re-verification of the last round was by re-running the refuter's own harness,
  not by a fresh refuter agent.
- **Gate:** `.venv/bin/python -m unittest discover -s tests` on 57cb32d: Ran 1247 tests in 902 s, FAILED (failures=1,
  skipped=9). The single failure is `test_fleet_s8o_step4_label.TestOverviewStep4.test_committed_page_is_a_fresh_build`.
  I reproduced it on a clean `git archive origin/master` (baseline-red, not this diff), and local master's 233f82f
  fixes it. a69b37f changed only the test file: `unittest fleet.tests.test_fleet_moroop_dispatch` gives 35 OK, with
  the smoke test run, not skipped, via `WR_MOROOP_RAW`. The smoke test skips in CI and in worktrees, because the raw
  parquet is gitignored.

## Open for the operator / S16 readme

- The dispatcher verdict rests on one resume that is 46.6 s after the 3,245 s episode and also inside a 47 s follow-on
  episode. An external call also opened 15 min before that episode. Who made either call is not knowable from the code
  (Part 9 §3).
- "We keep theirs" is a statement about our rules, not about why the authors removed those rows.

SCHED_RESULT: OK wr-lane-s16b-moroop-dispatch PR #58 merged 010b257 (local master 31897c2); dispatcher=marks the intervention cleaning=we keep theirs (main-loop re-run, 9 shifts); wr-s16b-run installed (laptop-scheduler 7617280); gate 1 baseline-red failure only (reproduced on origin/master)

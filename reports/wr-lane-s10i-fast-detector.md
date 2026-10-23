No: the short-memory map (b) does not match the CUSUM (c) at K 20. At the default (k, h) (b) detects 6/50 with 451.9 false flags per zone-hour on s10-none; (c) detects 2/50 with 0.0. They are different operating points (c is far quieter and far less sensitive), not the same detector.

# S10I fast change detector (per-cell CUSUM) vs the decayed map

Branch worktree-wf_637e43aa-66b-2, base master. Smoke command (run from the worktree, 10.5 s):

    .venv/bin/python fleet/fastmap_smoke.py --data-root fleet/data

Stdout, pasted:

    ROW a: detected 6/50, median first-detect 295.0 s, FA/h ref 177.840  [S10E map, results/fleet/amoc_blind.json, not rerun]
    ROW b: detected 6/50, median first-detect 402.5 s, FA/h ref 451.872  [short map: publish 60, window 0.2 h, half-life 0.1 h]
    ROW c: detected 2/50, median first-detect 525.0 s, FA/h ref 0.000  [CUSUM defaults k 1.0 h 3.0, count active, publish 60]
    ROW c-end: detected 0/50, median first-detect n/a s, FA/h ref 0.000  [CUSUM defaults, count end, publish 60; no flag on s10c-blind, row written by the smoke]
    fastmap_smoke: 4 rows, K 20, elapsed 10.5 s

Units: detected = n_detected of 50 blocked windows (known:false, s10c-blind), the field the AMOC output calls n_detected; median first-detect = median_delay_s; FA/h ref = fa_per_hour_reference, flag-publishes per zone per simulated hour on the undisturbed s10-none run (every flag there is false). For the maps (a, b) a flag is rank <= 20 at a publish; for the CUSUM a flag is a flagged cell at a publish (K 20 only caps the rank).

## Row table (K 20, publish 60)

| arm | detected | median first-detect s | FA/h on s10-none |
|---|---|---|---|
| a  S10E map (window 1 h, half-life 1 h), from results/fleet/amoc_blind.json | 6/50 | 295.0 | 177.84 |
| b  short-memory map (window 0.2 h, half-life 0.1 h) | 6/50 | 402.5 | 451.87 |
| c  CUSUM defaults (k 1, h 3), count active | 2/50 | 525.0 | 0.00 |
| c-end  CUSUM defaults, count end | 0/50 (no flag at all) | n/a | 0.00 |

Headline = row c, the default (k, h) pair. It is the pre-set operating point, not tuned on the data. Honest reading: at the defaults the CUSUM is almost silent (11 flags over 42 publishes on s10c-blind, none on s10-none) and detects 2 of 50 windows. One robot waiting at a blocked cell gives 1 active stall per bin; with mu = 0 or 1 and k = 1 the CUSUM then adds x - (mu + k) <= 0 per bin, so it only moves when two or more robots queue on the same cell. Rows (a) vs (c) are not comparable at a single dial: a map at K 20 flags up to 20 cells per zone per publish, the CUSUM flags what it flags.

In-sample tuned pairs (from a separate run with `--grid 0.5:2,0.5:3,0:2,0:3,0.5:1.5`, K 20, same data; IN-SAMPLE on s10c-blind, not a held-out result, no seed split exists for this run):

| (k, h) | detected | median first-detect s | FA/h on s10-none |
|---|---|---|---|
| 0.5, 2 | 12/50 | 500.0 | 0.000 |
| 0.5, 3 | 6/50 | 520.0 | 0.000 |
| 0, 2 | 18/50 | 337.5 | 7.344 |
| 0, 3 | 17/50 | 425.0 | 0.000 |
| 0.5, 1.5 | 15/50 | 445.0 | 0.000 |

These pairs were picked by looking at the same 50 windows they are scored on. (0, 3) is the best quiet pair here (17/50 at 0 FA/h on this one reference run); it needs a held-out run before it is quoted anywhere. The queue item wr-s10i-fast-run runs only the defaults.

## Counting-rule finding

The map counts a stall at its END time (hotspot.aggregate). A stall on a blind blockage ends only when the blockage clears (stalls last up to 915 s and end 0-1 steps before the window end, per the main loop's 19 Oct measurement, not re-measured here), so an open blockage is invisible to an end-time count. fastmap's default rule `active` counts a stall in every bin it overlaps. Same CUSUM, same defaults, only the rule changed: `end` gives 0 flags on s10c-blind (0/50), `active` gives 11 flags and 2/50. So at the defaults the whole detection comes from the counting rule; part of any (b)-vs-(c) gap is the rule, not the CUSUM. A map re-run with the active rule was not measured (costmap.py is not edited in this lane).

Known mild look-ahead in the active rule (also in the map): next_occupied is OR'd over the whole stall and the faulted-episode flag uses whole episodes (both from hotspot.py).

## Declared deviations and findings against the brief

1. fastmap_smoke.py instead of `fastmap.py --smoke`: the smoke needs a truth kind through time_to_detect, which would put the word truth into fastmap.py and trip TestAnalystIsolation. fastmap_smoke.py is in that test's exemption tuple with a comment; fastmap.py is in the required-names set; TestImportFence is unchanged (the smoke does not import truth).
2. Two-mode --store-suffix rule: DIR/store-X absent = rerun mode (copy, strip, rerun, hash check, select, remove), present = prebuilt mode (no copy, strip, rerun or remove; hash check kept; ValueError for non-cusum rows or zero rows; window flags and --sweep-cost rejected). meta.store_suffix and meta.store_mode appear only with the flag.
3. Zero-row exception for the reference (not in the brief): the CUSUM at the defaults flags nothing on the undisturbed s10-none run, so its store-fast holds zero forecast rows, and the brief's "zero rows is a ValueError" would abort the queue command on the reference. In prebuilt mode zero rows is therefore an error for the measured run and allowed for the reference (zero flags = FA/h 0); non-cusum rows are an error in both. Without this the smoke and the queue item fail.
4. Smoke row for a zero-flag measured run: time_to_detect refuses a prebuilt store with zero rows, so for (c-end) the smoke writes the row itself (0 detected, windows counted from the run's truth file, FA/h from the reference flag count). It is labelled in the row. The queue item does not hit this (defaults, count active).
5. T1 as written is not satisfiable: 4 active stalls per bin for 10 bins with k = 1 makes S peak near 18, and S falls by at most mu + k = about 1 per bin, so release needs about 15 bins after the jump, not 5. T1 `test_jump_flagged_and_released` uses a burst (6 active stalls in one bin): detect delay 60 s, release lag 3 bins, baseline mu exactly the pre-jump mean 1.0. A second test (`test_long_jump_held_through_the_jump_and_baseline_frozen`) covers the 10-bin jump: flagged 120 s after its start, held for the whole jump, mu frozen, released 15 bins after it.
6. est_minutes of wr-s10i-fast-run was already 10 (smoke 10.5 s x 1.5 is below the 10-minute floor), so only "command" differs from the pre-lane queue file (/tmp/wr-queue-pre-s10i.json, snapshotted before the edit). The queue command was not run; laptop-scheduler not committed.

Checks: fleet/data/{s10c-blind,s10-none} file listings (name, size, mtime) identical before and after the smoke; `git status results` in the worktree empty before and after.

## Pass 2 (PR #45, same branch worktree-wf_637e43aa-66b-2)

Shared cause of the pass-1 findings: the store-path guard compared names and equality while `shutil.rmtree` acts on a whole subtree (high finding), and the tests asserted shape (ROW regex, key presence, cmd list) where the criteria named values (the low findings). The two groups are separate defects; what they share is that each check was weaker than the property it stood for.

(A) fleet/fastmap.py `check_copy(glob, copy)`, called by `run_fastmap` (ValueError) and `main` (p.error, exit 2), before any rmtree/copytree. Resolves both paths and refuses: copy is the original store, an ancestor of it (so the run dir, fleet/data and every parent), inside it, named `store`, or containing a file that matches --glob. An existing copy is deleted only if it holds decisions.jsonl, no *.jsonl.gz and no directory named store. Test `test_refuses_ancestor_and_run_dir`: --store jsonl:<run dir>, <parent>, <run dir>/store/sub, <run dir>/store, `..` spellings and a non-copy directory -> exit 2 and ValueError from run_fastmap, sha256 of every file under the temp tree identical after each refused call. Verified red against the pass-1 fastmap.py (3 errors).
(B) `test_no_new_flags_output_identical`: real `rerun_costmap` cmd (stubbed subprocess.run) equals the literal pre-lane list, meta has no store_suffix / store_mode, output bytes equal those of the FakeRerun run that gets the default copy DIR/store-ttd-<S>, and >= 1 window detected.
(C) T10 `test_smoke_on_real_data`: row (a) read from results/fleet/amoc_blind.json and equal to 6/50, 295.0, 177.84; all rows: detected <= 50, FA/h finite >= 0, median null iff 0 detected; on macOS only (pyastar2d tie-break differs on Linux) (b) 6/50 402.5 451.87 and (c) 2/50 525.0 0.00 exactly. `test_decision_rows_read_by_time_to_detect` now asserts n_detected >= 1 (by_k and amoc) and recomputes fa_per_hour_reference from the store copy rows. The undisturbed 150-step fixture has no stall, so that recomputation is 0 there; the nonzero case is pinned by `test_prebuilt_reference_fa_recomputed` on hand-built cusum rows (3/(2*h) at K 1, 4/(2*h) at K 2).
(D) Declared deviation from pass-1 criterion 3, accepted by the main loop: a prebuilt reference with zero rows is accepted (code was already so in pass 1; the docstring of time_to_detect.py now says it) and a prebuilt measured run with zero rows raises ValueError. Test `test_prebuilt_zero_row_reference_allowed_measured_not`.
T1 long-jump deviation stays (item 5 above): plain CUSUM with drift k = 1 releases about 1 per bin after a 10-bin jump, so release within 5 bins cannot hold; not a defect.

Gate (worktree, data at fleet/data for T10): `.venv/bin/python -m unittest discover -s fleet/tests -p 'test_*.py'` Ran 980, OK (skipped=4: three s10-none gate tests and the sticky phaseA test, pre-existing untracked-data skips outside this lane). `.venv/bin/python -m unittest discover -s tests` Ran 989, OK (skipped=4), 627 s.

## Main-loop merge (19 Oct)

Pass 1 was refuted (correctness: `--store` set to an ancestor of the original store let rmtree delete the run directory; test-honesty: shape-only tests). Pass 2 fixed both. All three refuters (correctness, test-honesty, invariants) were non-refuting on head 363cb0c. The python-reviewer's "fail" listed tests as missing that exist on 363cb0c, and its gate counts (985/976) are the pass-1 numbers, so it reviewed the stale head. Main loop re-checked on 363cb0c: an ancestor `--store` exits 2 and deletes nothing; `unittest discover -s tests` Ran 989, OK (skipped=4); `unittest discover -s fleet/tests -p 'test_*.py'` Ran 980, OK (skipped=4); smoke rows identical to the table above, 10.8 s. Squash-merged as PR #45, commit 9417ea2, master fast-forwarded. Queue item wr-s10i-fast-run: only its command changed against the pre-lane snapshot; not run. The T10 values for (b) and (c) are pinned for macOS only (pyastar2d tie-break).

SCHED_RESULT: OK S10I merged PR #45 (9417ea2); K20 on s10c-blind: map 6/50 295 s 177.8 FA/h, short map 6/50 402.5 s 451.9 FA/h, CUSUM default 2/50 525 s 0.0 FA/h (in-sample k0 h3 17/50 0.0); wr-s10i-fast-run command set, not run

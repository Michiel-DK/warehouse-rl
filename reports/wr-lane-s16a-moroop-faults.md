# S16A MoRoOp --faults and fleet/moroop_faults.py

Branch `s16a-moroop-faults`, based on origin/master a0a1854. Changed files: `fleet/adapters/moroop.py`,
`fleet/moroop_faults.py`, `fleet/tests/test_fleet_moroop_faults.py`, this report. parse.py, detector.py, score.py,
timebudget.py, README.md, docs/SCOPE.md untouched.

## What was built

- `moroop.py --faults` (build and `--analyse`, default off, threaded as `faults=False` through `convert_shift`, `build`,
  `analyse`). With it each message's `errors` holds one entry per status of the kept row at level exactly `Error` that is not
  the noise key, in status order: `{errorType: name, errorLevel: "FATAL", errorDescription: message[:120]}`. parse.py needs
  no other key (it only checks that `errors` is a list and reads `errorLevel`), so none were added. Unparseable diagnostics ->
  `[]`, counted in `stats.diagnostics.faulted.kept_messages_unparseable_diagnostics`.
- With `--faults` only: `MAPPING_FAULTS` rows replace the errors/faulted rows in the result JSON, one extra DEVIATIONS row,
  `src.faults`, the faulted bucket seconds/share as numbers (pooled `seconds`/`share` plus top-level `faulted`; per shift in
  `timebudget_moroop_shifts-S.json`), `faults: true` and `faults_note` in `moroop_label-S.json`. Without it none of these keys
  exist and every string (`not computed`, `[] (diagnostics levels tabulated only)`, MAPPING/DEVIATIONS) is the S13A text.
- `fleet/moroop_faults.py`: tables (a), (b), (c), the cross-check, the section 5 `verdict` (top-level key), public label
  'Robot reported a component error'. Pure functions on plain dicts; pyarrow only in `main`.

## Deviations from the brief / Part 9

1. Verdict overlap = seconds with >= 1 qualifying Error status whether or not the robot was paused (`faulted_overlap_s`).
   Table (b)'s `faulted_s` / `faulted_share` exclude faulted+paused seconds (counted as `faulted_paused_s`), as asked. The
   brief does not say which feeds the verdict; none of the dev-run episodes has a paused second so the choice is moot there.
2. Extra CLI args: `--label-sb`, `--stations`, `--station-radius` (default 1). Per-shift servicing bounds for the Detector
   re-run come from the label files' `servicing_max_s` lists (the bound `auto` resolved to in the original run).
3. Extra hard checks (exit 1): each Detector re-run must equal its label file's causes table per cause (episodes, seconds);
   -sb unknown must be (2, 180); the number of faulted messages in jsonl-sf must equal the raw-derived count (catches a
   build run without --faults); the 3,245 s shift-6 episode must be among the -sb episodes.
4. A record holding two error families counts its seconds in each family row of table (a), so family rows can sum above the
   total.
5. Table (c) is pooled over the nine shifts; `first_onset` is the first record in shift order. `robot_uptime` exists in the
   raw cleaned table (verified: column list read in this session) and is reported; had it been absent the field would be
   `absent`.
6. Byte-identity proof covers the criterion's files. The per-shift `budget-S/zone<k>.json` (written by timebudget.py, not
   changed here) differ only in the `glob`/`stations` path strings because I wrote into /tmp (diff of zone0 checked: 4 path
   lines). The unsuffixed S13A pair was not rebuilt: its `jsonl`/`budget` dirs are not on disk.
7. Driving/paused flags in moroop_faults use the adapter defaults (0.05 m/s, 0.05 rad/s), as the shipped jsonl does.

## Byte-identity (no --faults), full SHA-256 prefix (16 hex), on-disk/origin copy vs /tmp rebuild

Commands: the MoRoOp leg of wr-s14a-rerun (suffix sb) and wr-s14d-rerun (suffix sd) with `--out/--stations/--results` into
/tmp/s16a/<tag>. Tracked JSON compared against the origin/master copy, jsonl against the untracked on-disk copy.

| file | on disk / origin | rebuilt | |
|---|---|---|---|
| jsonl-sb/zone0-000.jsonl.gz | `8c911f44d97aa060` | `8c911f44d97aa060` | match |
| jsonl-sb/zone1-000.jsonl.gz | `c96ba6878c4aee49` | `c96ba6878c4aee49` | match |
| jsonl-sb/zone2-000.jsonl.gz | `96bb8e3a915dd130` | `96bb8e3a915dd130` | match |
| jsonl-sb/zone3-000.jsonl.gz | `72203d8c910502d7` | `72203d8c910502d7` | match |
| jsonl-sb/zone4-000.jsonl.gz | `f1249817ba99095c` | `f1249817ba99095c` | match |
| jsonl-sb/zone5-000.jsonl.gz | `f039e46fb8bc57ef` | `f039e46fb8bc57ef` | match |
| jsonl-sb/zone6-000.jsonl.gz | `2344900e9a84f577` | `2344900e9a84f577` | match |
| jsonl-sb/zone7-000.jsonl.gz | `0c71f27ae5ca5ed7` | `0c71f27ae5ca5ed7` | match |
| jsonl-sb/zone8-000.jsonl.gz | `a5e956f286918231` | `a5e956f286918231` | match |
| jsonl-sb/adapter_stats.json | `0f13fcd04b4b867e` | `0f13fcd04b4b867e` | match |
| moroop_label-sb.json | `d8635c21d7be6b09` | `d8635c21d7be6b09` | match |
| timebudget_moroop-sb.json | `1c615d40be10c1af` | `1c615d40be10c1af` | match |
| timebudget_moroop_shifts-sb.json | `dedd5c1f0d7a78ae` | `dedd5c1f0d7a78ae` | match |
| jsonl-sd/zone0-000.jsonl.gz | `8c911f44d97aa060` | `8c911f44d97aa060` | match |
| jsonl-sd/zone1-000.jsonl.gz | `c96ba6878c4aee49` | `c96ba6878c4aee49` | match |
| jsonl-sd/zone2-000.jsonl.gz | `96bb8e3a915dd130` | `96bb8e3a915dd130` | match |
| jsonl-sd/zone3-000.jsonl.gz | `72203d8c910502d7` | `72203d8c910502d7` | match |
| jsonl-sd/zone4-000.jsonl.gz | `f1249817ba99095c` | `f1249817ba99095c` | match |
| jsonl-sd/zone5-000.jsonl.gz | `f039e46fb8bc57ef` | `f039e46fb8bc57ef` | match |
| jsonl-sd/zone6-000.jsonl.gz | `2344900e9a84f577` | `2344900e9a84f577` | match |
| jsonl-sd/zone7-000.jsonl.gz | `0c71f27ae5ca5ed7` | `0c71f27ae5ca5ed7` | match |
| jsonl-sd/zone8-000.jsonl.gz | `a5e956f286918231` | `a5e956f286918231` | match |
| jsonl-sd/adapter_stats.json | `0f13fcd04b4b867e` | `0f13fcd04b4b867e` | match |
| moroop_label-sd.json | `d8635c21d7be6b09` | `d8635c21d7be6b09` | match |
| timebudget_moroop-sd.json | `1c615d40be10c1af` | `1c615d40be10c1af` | match |
| timebudget_moroop_shifts-sd.json | `dedd5c1f0d7a78ae` | `dedd5c1f0d7a78ae` | match |

26 of 26 match. Budget files: 0 of 18 byte-equal, the rest differ in path strings only.

## Tests (fleet/tests/test_fleet_moroop_faults.py, 12 cases, no skips)

`.venv/bin/python -m unittest fleet.tests.test_fleet_moroop_faults -v` -> `Ran 12 tests ... OK`. Each case has an `# inject:`
line. Cases: error status -> exact FATAL entry + parse faulted (a)(d), (b)(c)(e) errors [] and not faulted; Detector files (a)
and (d) faulted_self and (b)(c)(e) unknown stuck episodes; description truncated to 120; faults off == current adapter
(encoded lines, stats, MAPPING objects, `not computed`); unparseable diagnostics; table (c) classes with 'noise' on exactly one
row; table (a) driving split and family share; table (b) status vs episode (60 s) and the faulted+paused case (20 s paused,
40 s faulted); verdict words incl. 50 % and 20 % boundaries; label-aggregate reproduction check; determinism. Red check run:
emptying `mo.NOISE` in-process fails `test_table_c_classes` and the report test.

## Gate

Lane run, worktree on origin/master a0a1854 + this branch: `Ran 1234 tests in 785.971s` / `FAILED (failures=1, skipped=9)`.
The one failure was `fleet.tests.test_fleet_s8o_step4_label.TestOverviewStep4.test_committed_page_is_a_fresh_build`
(`fleet/overview_build.py` still emitted `laptop-scheduler/reports/wr-s8e-lessons-long.md` while the committed page says
`reports/...`). The correctness refuter refuted on it: red gate, no master baseline.

Main loop, re-verification:
- Baseline: the same test fails alone on a clean detached worktree of origin/master a0a1854 (`FAILED (failures=1)`), so it
  predates this lane. The diff touches neither `fleet/overview_build.py` nor `docs/overview/`.
- Local master gained `233f82f` during the lane (overview_build.py emits `reports/` paths; unpushed, with the held public-repo
  prep commits). Gate on a detached worktree of local master 233f82f with this branch merged in:
  `Ran 1234 tests in 898.537s` / `OK (skipped=9)`, exit 0 (1222 on 233f82f + the 12 new cases). The 9 skips are the data
  tests that need untracked data, absent in a worktree.
- origin/master stays red on that one test until the held commits are pushed (operator's call); this PR does not change that.

## Part 9 is not on origin/master

`docs/LITERATURE.md` Part 9 (the rules this lane implements) is in local master commits 682bdd0 / 35251c8, held unpushed with
the public-repo prep. Until they are pushed, the rules are restated in this report's "Deviations" and in the module
docstrings; the PR's Part 9 citations are checkable on local master only.

## Dev run (lane dev run, pending wr-s16a-run)

/tmp rebuild with `--faults` (suffix sf), then moroop_faults.py (exit 0, two runs byte-identical, sha256
`2f980848e34bfab6...`).

- Verdict: **mixed** (n = 2: a description, not a rate). Episodes of the -sb 'cause not identified' set (2, 180 s,
  reproduced from the Detector re-run):
- shift 6 2026-07-30T07:10:44Z: 47 s, overlaps a faulted status for 0 s (0.000)
- shift 7 2026-07-31T12:23:06Z: 133 s, overlaps a faulted status for 1 s (0.008)
- Caveat (main loop): 'mixed' rests on that one second. With 0 s it would read 'unknown stays unknown'; at 1 s of 133 the
  diagnostics give these two stalls no cause in substance. Read the verdict with that number next to it.
- Pooled faulted seconds from raw: 585 (0.0022 of 262717 s span), driving
  58 s (share 0.099), in paused rows 0 s.
- Cross-check: time-budget faulted bucket 508 s vs 585 s from raw,
  difference 77 s (no_data outranks faulted; not equal, as the brief anticipated). Per shift bucket:
  {'0': 31, '1': 42, '2': 98, '3': 28, '4': 37, '5': 50, '6': 35, '7': 120, '8': 67}.
- Families with > 50 % of their faulted seconds while driving (refute 'ERROR = stopped' for that family, Part 9 section 5):
  - /Navigation/Robot Stuck | : Blocked by obstacle. Check robot surroundings.
  - /Wheels/BL | Power Input: Not Charging.
  - /Wheels/BR | Power Input: Not Charging.
  - /Wheels/FL | Power Input: Not Charging.
  - /Wheels/FR | Power Input: Not Charging.
  Each has <= 39 faulted seconds; the larger families (/Wheels lidar, /Navigation/Robot Stuck 'Goal is obstructed',
  /Navigation Error) have a driving share <= 0.16 (table (a) of the JSON).
- -sf label file: causes station_overrun 2 eps / 3563 s, faulted_self 8 eps / 1237 s, unknown 1 ep / 47 s. The 133 s -sb
  unknown episode (shift 7, 2026-07-31T12:23:06Z) becomes faulted_self in -sf although only 1 s of it overlaps an Error
  status: the Detector assigns the cause of the message that enters the stuck state. Treat that flip as a Detector rule effect.
- The 3,245 s shift-6 episode (2026-07-30T06:16:31Z): station_overrun in -sb and -sf, no Error status inside it (0 s).
- Table (c): 51 (level, name, message) combinations; 'noise' on exactly one row (/Devices/Camera, 'Frequency too
  high.', Warning, 1830 rows / 3685 s); `robot_uptime` column present.

## WARNING: the faulted_self label

`results/fleet/moroop_label-sf.json` (and anything built from the Detector's causes table) carries the cause label
'Robot error, cannot continue order' for `faulted_self`. That label must NOT be quoted for MoRoOp: Part 9 says an Error status
is our rule (rank B) and REP 107 says a component ERROR does not halt the system. Use 'Robot reported a component error'.
The label file also carries `faults_note` saying so.

## Queue command lines (wr-s16a-run, to be written by the main loop)

    setopt shwordsplit 2>/dev/null || true
    set -e
    P=.venv/bin/python
    M=fleet/data/moroop
    $P fleet/adapters/moroop.py --raw $M/raw --out $M/jsonl-sf --stations $M/stations-sf.json --servicing-max-s auto --faults
    cmp $M/stations-sf.json $M/stations.json
    mkdir -p $M/budget-sf
    k=0
    for S in 2026_07_27_morning 2026_07_27_evening 2026_07_28_morning 2026_07_28_evening 2026_07_29_morning 2026_07_29_evening 2026_07_30_morning 2026_07_31_morning 2026_07_31_evening; do
      $P fleet/timebudget.py --glob "$M/jsonl-sf/zone$k-000.jsonl.gz" --run "moroop-$S" --stations $M/stations.json --station-aware --station-radius 1 --servicing-max-s auto --out "$M/budget-sf/zone$k.json"
      k=$((k+1))
    done
    $P fleet/adapters/moroop.py --analyse --raw $M/raw --jsonl $M/jsonl-sf --budget $M/budget-sf --stations $M/stations.json --station-radius 1 --servicing-max-s auto --suffix sf --faults
    $P fleet/moroop_faults.py --raw $M/raw --jsonl-sf $M/jsonl-sf --budget-dir $M/budget-sf --label-sf results/fleet/moroop_label-sf.json --jsonl-sb $M/jsonl-sb --label-sb results/fleet/moroop_label-sb.json --out results/fleet/moroop_faults.json
    echo "SCHED_RESULT: OK wr-s16a-run MoRoOp --faults into *-sf outputs and moroop_faults-sf.json"

SCHED_RESULT: OK wr-lane-s16a-moroop-faults 12 new tests ok, byte-identity 26/26 without --faults, gate on master 233f82f + branch Ran 1234 OK (skipped=9) (origin/master a0a1854 red on a pre-existing overview test, fixed in held 233f82f); dev-run verdict mixed on 1 s of overlap, pending wr-s16a-run

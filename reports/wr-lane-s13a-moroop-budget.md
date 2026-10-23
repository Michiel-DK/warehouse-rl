# wr-lane-s13a-moroop-budget — S13A: the time budget on the first real robot log (MoRoOp)

Date 2026-10-20. Lane `single-lane-build` run wf_18b87014-6b4 (tier standard, build sonnet, base master), PR #49
(head 48939b1). Review round: criterion pre-review sound (5 advisories), python-reviewer pass (minor only), refuters
correctness / test-honesty / scope-adherence / invariants all **not refuted**. Merge status: see the end of this file.

Every number below is read from `results/fleet/timebudget_moroop.json` (pooled) or
`results/fleet/timebudget_moroop_shifts.json` (per shift), both committed in PR #49.

## 1. Data

- Source: https://huggingface.co/datasets/Self-Organizing-Production-Logistics/MoRoOp, revision `1.0.1`.
  Tag target commit `9051cb4653648b625999608367eced435e0b3991`; the API's `revision/1.0.1` sha is
  `15177e72c99d209d64e20cc013793a5dd3f5b124`. Both are recorded in `src.hf`.
- The card says "current release (1.0.0)", and the paper and toolkit say 1.0.1. The pin is 1.0.1, as Part 2b advised.
- Licence: the card's `license: cc-by-4.0` (Klein & Jeong 2026, arXiv 2610.02428).
- Files: 46 under `data/` plus the card `README.md`, 26,770,883 bytes in total. That is one folder per shift with
  `{jobs, operations, dispatch_events, robot_state_cleaned, robot_state_raw}.parquet`, plus `data/kits.parquet`
  (88 rows: kit_id, color, size, quantity).
- Every file's sha256 matches its HF LFS oid. The file list with sizes and oids is in `fleet/data/moroop/filelist.txt`
  (untracked) and the sha256s are in `src.raw_sha256`.
- The raw files are in `fleet/data/moroop/raw/` and are untracked.
- Shifts: 2026-07-27 to 2026-07-31, morning and evening. 30 Jul evening is absent, which the paper says was dropped for
  a job-generator bug.

**Row counts per shift.** Shift order is 27m 27e 28m 28e 29m 29e 30m 31m 31e.

| table | per shift | total |
|---|---|---|
| jobs | 154 154 156 155 155 155 148 152 153 | 1,382 |
| operations | 536 535 540 538 541 539 520 533 533 | 4,815 |
| dispatch_events | 2149 2145 2173 2159 2170 2167 2103 2149 2137 | 19,352 |
| robot_state_raw | 15549 15389 15912 15566 15546 15491 15053 15949 15931 | 140,386 |
| robot_state_cleaned | 15194 15038 15553 15252 15182 15168 14711 15635 15694 | 137,427 |

**Schemas.** Pyarrow types. The schema is identical across all nine shifts for every table.

- `jobs`: id large_string, created_at timestamp[us, UTC], payload large_string (JSON job_type, kit_id), operations
  large_string (JSON id list), state, outcome, termination_reason large_string, release_date, start_time, due_date,
  finish_time timestamp[us, UTC].
- `operations`: id large_string, created_at timestamp[us, UTC], payload large_string (JSON goal), priority int64,
  job_id, dependencies, state, outcome, termination_reason large_string, retry_count int64, start_time, finish_time
  timestamp[us, UTC].
- `dispatch_events`: id large_string, created_at timestamp[us, UTC], event_type, operation_id, changes (JSON),
  meta_data (JSON), all large_string.
- `robot_state_raw` and `robot_state_cleaned`:
  - id int64, created_at timestamp[us, UTC];
  - operating_mode, state, stuck_reason large_string;
  - pos_x, pos_y, pos_theta, velocity_x, velocity_y, velocity_omega double;
  - current_position_id, navigating_to_position_id, last_navigated_position_id int64;
  - next_goal_timestamp **timestamp[ns, UTC]** (pyarrow `to_pylist` raises on it; it is cast to us);
  - tl/tr/bl/br_charge_state int64;
  - is_robot_charging and tl/tr/bl/br_charging bool;
  - robot_uptime double;
  - diagnostics large_string (JSON `{"statuses": [{hardwareId, name, level, message, values}]}`).

**Field values, cleaned rows, all shifts.**

- `stuck_reason`: `None`, `ObstacleInTheWay`, `GoalObstructed`. 207 rows are not `None`.
- `state` rows: Navigating 122,509, Idle 14,901, Nonautonomous 10, Initializing 3, Waiting 2, Paused 2.
- `operating_mode` rows: Autonomous 137,410, Joystick 10, Reconnecting 3, Initializing 3, PoweredOff 1.
- `job_type`: `kit supply`, `empty_box_refill`, `charging`. Shift 0, for example, has 115, 37 and 2.
- **Diagnostics `level` values: Ok 2,322,264, Warning 18,231, Error 387, Stale 1** (status entries over all rows).
  Part 2b had seen only "Ok", in the first 81 rows; this corrects it.
  - The vocabulary is still undocumented, so no level is mapped to an errorLevel and `faulted` is "not computed".
  - A later lane could test whether `Error` statuses line up with the label or with TIMEOUTs. That would be a rank-F
    mapping until wheel.me documents the levels.
- No "failed navigation" rows exist. Failures are the 8 operations with `termination_reason` TIMEOUT.

## 2. Adapter and mapping

The adapter is `fleet/adapters/moroop.py --raw DIR --out DIR [--shift N] [--cell-m 0.5] [--moving-eps 0.05]
[--omega-eps 0.05] [--stations PATH]`, plus `--analyse`. It writes one `zone<k>-000.jsonl.gz` per shift, with k from 0
to 8 in chronological order.

- pyarrow is imported lazily, so the module imports and its pure functions run without pyarrow.
- `fleet/requirements.txt` gains an unpinned `pyarrow` line; `requirements.lock.txt` is unchanged.
- pyarrow 25.0.1 was installed into the local `.venv` for this lane.

The mapping list is stored in the JSON `mapping` key. Source column, then the field:

| field | source | rule (Part 2b §4) |
|---|---|---|
| timestamp | `created_at` | floored to whole seconds UTC; the last native row of each second is kept |
| headerId | (not `id`) | 1..n contiguous per shift |
| manufacturer / serialNumber | constant | `wheel.me` / `moroop-amr-1` |
| orderId | `operations.job_id`, start_time, finish_time, `jobs.payload.job_type` | the operation running at the kept row's native created_at; an inter-operation gap inside one job keeps the job id; on overlap the latest start wins; charging → `""` |
| agvPosition.x/y | `pos_x`, `pos_y` | `math.floor(v / 0.5)` (floor, so cells either side of 0 stay distinct) |
| agvPosition.theta | `pos_theta` | as-is, radians |
| driving | velocity_x, velocity_y, velocity_omega | `hypot(vx, vy) > 0.05` or `abs(omega) > 0.05` (strict); never `state == "Navigating"` |
| paused | state, operating_mode | `state == "Paused"` or `operating_mode != "Autonomous"` |
| errors | diagnostics | `[]`; levels tabulated only. stuck_reason, TIMEOUT and start_denied are never errors |
| loads | (none) | `[]` |
| waiting_shelf | (none) | "n/a": there are no shelves and no picker |
| faulted | diagnostics | "not computed" |

**Deviations.** These are recorded in the JSON `deviations` key, each with its reason.

1. **The pooled result is the sum of nine per-shift `fleet/timebudget.py` runs.** It is not one run over all nine
   files.
   - Serial `moroop-amr-1` has no `Z<zone>-` prefix, so `parse.zone_of` puts every shift in zone `""`.
   - `read_messages` would then drop shifts 2-9 as duplicate (serial, headerId) pairs and merge the rest into one robot.
   - Seconds, jobs and spans are summed; shares and jobs per robot-hour are recomputed from the sums.
2. **Removed rows are counted as `max(id) - min(id) + 1 - rows`, not `max(id) - rows`.** Ids continue across shifts.
   The values equal raw minus cleaned rows: 355 351 359 314 364 323 342 314 237.
3. The four stations' cell sets are reported as disjoint (they are), not asserted. The brief said report; Part 2b said
   assert.
4. Endpoint conventions for the label windows are written out: runs and label episodes are half-open, and the search
   windows are closed at the far end.
5. A label episode with no later `None` row ends at the last message. Percentiles are nearest-rank.
6. **Per-second buckets come from calling `timebudget.robot_budget` on each message pair.** Stuck versus stopped_short
   is then decided with `stopped_runs` and `run_is_stuck` over the full stream.
   - The per-bucket second counts are checked against each shift's timebudget output, and `--analyse` raises on a
     mismatch.
   - This check is partly circular, because both sides use the same code. The test-honesty refuter said so.

**Adapter statistics, pooled.**

- 132,838 messages and 0 parse rejects in all nine shifts.
- 4,589 native rows collapsed by the one-row-per-second rule. None of the collapsed rows had `stuck_reason != None`.
- Kept-interval p50 is 1 s in every shift, p99 is 21-26 s, and the maximum is 99-190 s.
- Overlap seconds between operations: 0 in every shift.
- Seconds that count as driving only because of omega: 2,293-3,091 per shift.
- Paused messages: 2 in 27 Jul evening and 17 in 30 Jul morning (the Joystick / Nonautonomous rows). That is 161 paused
  seconds in total.
- Seconds per operating_mode: Reconnecting 56, Initializing 53, Joystick 12, PoweredOff 3.

## 3. Stations

`fleet/data/moroop/stations.json` is 120 bytes and committed. Its cells are `[[0,-4],[2,0],[9,-3],[15,0]]`, with an
empty `shelves` list.

- Each `current_position_id` gets exactly one cell holding 100 % of the `state == "Idle"` rows at that id: 135
  charging (0,-4) with 796 rows, 136 warehouse (9,-3) with 6,289, 137 kitting (15,0) with 4,112, and 138 assembly (2,0)
  with 3,704.
- The four cells are disjoint.
- Of the 14,901 Idle rows at ids 135-138, 0 lie outside the station set (share 0.0).
- At 0.5 m cells the docking jitter never crosses a cell border, so the multi-cell rule was never needed.

## 4. Time budget

Shares are of span. Charging time is reported separately, as seconds of the charging job (whose orderId is `""`, so it
lands in idle or moving) and seconds with `is_robot_charging`. The waiting_station share is not a finding: the job
generator sets the station dwell.

| k | shift | span h | moving | waiting_station | stuck | stopped_short | idle | paused | no_data | charging-job s | is_robot_charging s | jobs/robot-h |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 27 Jul morning | 8.12 | 39.6 | 42.4 | 0.0 | 0.7 | 11.4 | 0.0 | 5.8 | 801 | 654 | 18.71 |
| 1 | 27 Jul evening | 8.04 | 40.1 | 41.8 | 0.0 | 0.5 | 11.0 | 0.0 | 6.5 | 1459 | 1253 | 18.78 |
| 2 | 28 Jul morning | 8.26 | 40.0 | 40.3 | 0.0 | 0.8 | 13.1 | 0.0 | 5.7 | 2267 | 1963 | 18.41 |
| 3 | 28 Jul evening | 8.10 | 40.4 | 40.9 | 0.0 | 0.6 | 12.2 | 0.0 | 5.9 | 2267 | 2017 | 18.65 |
| 4 | 29 Jul morning | 8.03 | 40.4 | 41.6 | 0.0 | 0.6 | 7.5 | 0.0 | 9.9 | 21 | 2 | 19.18 |
| 5 | 29 Jul evening | 8.10 | 40.1 | 41.4 | 0.0 | 0.7 | 10.2 | 0.0 | 7.6 | 1504 | 1337 | 18.77 |
| 6 | 30 Jul morning | 8.15 | 38.1 | 37.4 | 3.8 | 0.9 | 8.4 | 0.5 | 10.8 | 2189 | 2286 | 17.68 |
| 7 | 31 Jul morning | 8.03 | 42.7 | 42.2 | 0.0 | 1.0 | 5.2 | 0.0 | 9.0 | 103 | 31 | 18.81 |
| 8 | 31 Jul evening | 8.16 | 42.3 | 40.9 | 0.0 | 0.6 | 9.1 | 0.0 | 7.2 | 1599 | 1384 | 18.38 |
| **pooled** | 72.98 h | | **40.4** | **41.0** | **0.42** | **0.71** | **9.8** | **0.06** | **7.6** | 12,210 | 10,927 | **18.59** |

Pooled seconds: moving 106,171, waiting_station 107,665, stuck 1,113, stopped_short 1,870, idle 25,767, paused 161,
no_data 19,970, which sums to the 262,717 s span. faulted is "not computed" and waiting_shelf is "n/a".

**Pooled stuck seconds, 1,113 in total, per shift: 1,107 in shift 6 (30 Jul morning), 6 in shift 7, and 0 elsewhere**
(`timebudget_robot.seconds.stuck` in the shifts JSON).

- Shift 6 has two off-station stuck runs, both overlapping paused (Joystick / Nonautonomous) messages, so both are part
  of the 30 Jul morning manual intervention:
  - 3,245 s from 06:16:31Z, which also overlaps a TIMEOUT operation;
  - 47 s from 07:10:44Z.
  - How the 1,107 s split between the two runs was not computed. The rest of the 3,245 s went to the higher-precedence
    paused and no_data buckets.
- Shift 7's 6 s come from a 133 s off-station run at 12:23:06Z (see §5 (b)). Most of that run's time is in no_data,
  because the change-only logger sends nothing while the robot stands still.
  - This is inferred from shift 7's stuck seconds. The run's per-bucket split was not stored.

**no_data.**

- 239 intervals are over 60 s. The 60 s rule moves 19,970 s (7.6 % of span) into no_data.
- Without the rule those seconds would have been waiting_station 13,470, idle 4,282 and stuck 2,218.
- The largest gap inside a stopped run is 90-190 s per shift, 190 s in 30 Jul morning.
- Cause: the logger stores a row "only when at least one reported value differed". A robot parked at a station sends
  nothing, so on this log a long gap means "unchanged", not "lost".
- So here the S12C 60 s rule mostly re-labels station dwell. A change-only source needs a per-source gap rule; this lane
  did not change one.

## 5. Comparison with the robot's own stuck label

A label episode is a maximal run of native cleaned rows with `stuck_reason != "None"`.

- **(a) Label seconds by our bucket:** 765 in total. no_data 290, idle 142, moving 134, waiting_station 117,
  stopped_short 82, **stuck 0**, paused 0.
  - The robot's label never falls in our stuck bucket.
  - Most label time is spent moving (re-planning around the obstacle) or sits in change-only logging gaps.
- **(b) Episodes:** 77 in all, of which 75 are shorter than 30 s. Those 75 cannot reach DEFAULT_STUCK_AFTER = 30, so
  they are not counted as misses.
  - Episodes of 30 s or more: **2, both detected (2/2, 0 misses)**. Both are in 31 Jul morning: 12:18:37Z
    (GoalObstructed, 250 s) and 12:23:11Z (127 s).
  - Both are hit by a real off-station stuck run, 133 s from 12:23:06Z. The first is also overlapped by a 262 s run on
    a station cell starting 12:18:25Z, so the robot could not complete the goal at the station.
  - This was checked by the main loop after the merge, by recomputing the stuck runs from `zone7-000.jsonl.gz` with
    `timebudget.kept_messages` / `stopped_runs` / `run_is_stuck` against `stations.json`. It is not stored in the
    JSON.
  - Two episodes are too few to give a rate.
- **(c) False alarms:** our stuck runs (detector episodes) with no label within ±30 s number **544 of 567**.
  - **542 of the 544 sit on a station cell.** Their median duration is 39 s, 537 of them are 60 s or shorter, and
    the range is 31-344 s. The 3-box kitting dwell averages about 30.7 s, just over the 30 s threshold.
  - Of the station false alarms, 4 last 300 s or more. Those are the long station stops behind TIMEOUT operations; see
    (d).
  - The time budget puts those seconds in waiting_station, not stuck. But the detector's episode list counts them, the
    same "station waits filed as stuck" problem the operator-problems scout found.
  - The 2 off-station false alarms are both in 30 Jul morning and both overlap paused messages: the 3,245 s manual
    intervention, and a 47 s run at 07:10:44Z.
  - Across all false alarms, 6 overlap a TIMEOUT operation and 3 overlap a paused message.
- **(d) Second label, rank B (the 8 TIMEOUT operations of about 300 s):** **8/8 overlap one of our stuck runs, but only 2 of the 8
  overlap an off-station run.** The two are 30 Jul 06:16Z (the 3,245 s manual intervention) and 31 Jul 12:18Z (the
  133 s run).
  - The other 6 overlap only a station run of 102-344 s: the robot stood at a station for about the full 300 s
    timeout.
  - The budget files those 6 as waiting_station. A station stop ten times the generator's 5-25 s dwell is plausibly a
    fault, but the budget cannot tell it apart from a normal dwell.
  - There is no chance baseline. The correctness refuter flagged the same, and this count was made by the main loop
    after the merge, as for (b).

**The one line that matters:** on one real AMR, the time budget runs end to end with 0 parse rejects and buckets that
sum to the span.

- The robot's own stuck label gives 2/2 detections, on only 2 episodes long enough to judge. Both come from a real
  off-station stuck run (133 s), whose seconds land mostly in no_data because the log is change-only.
- Of our stuck bucket, 1,107 of 1,113 s are the 30 Jul morning manual intervention.
- The stall list's false alarms are almost all (542/544) dwells of just over 30 s at a station. On this log, a
  station-cell exclusion in the detector would remove nearly all of them.
- Nothing multi-robot is claimed: there is one robot, an 8 x 2.3 m lab, and no congestion, deadlock or hotspot.

## 6. Sanity checks (stored observed vs expected)

- **Exact, all pass:**
  - cleaned rows per shift: 15194 15038 15553 15252 15182 15168 14711 15635 15694;
  - label rows: 37 3 52 20 3 17 48 17 10 (207);
  - TIMEOUT operations: 0 1 0 0 0 1 2 3 1 (8);
  - buckets sum to span in every shift (pooled 262,717 s);
  - per-second bucket counts equal the timebudget seconds in every shift;
  - parse rejects 0;
  - the pooled message count equals the sum over shifts. This is a tautology under the summing rule.
- **Within 5 %, all pass:**
  - unique non-empty orderIds equal the non-charging jobs in every shift: 152 151 152 151 154 152 144 151 150;
  - span per shift: 8.123 8.039 8.255 8.096 8.030 8.096 8.146 8.029 8.163 h against 8.12 8.04 8.26 8.10 8.03 8.10
    8.15 8.03 8.16;
  - pooled span: 72.977 h against 72.99;
  - **pooled jobs per robot-hour: 18.59 against 18.93** (1,382 / 72.99), 1.8 % low. The 1,382 includes the 25 charging
    jobs, which we count as orderId `""`, and 1,357 / 72.98 = 18.59.

## 7. Tests and gate

`fleet/tests/test_fleet_moroop.py` has 15 tests: 12 always run and 3 need the data.

- The always-run tests use a hand-made frame. They cover parse_line with 0 rejects, Detector and robot_budget with
  bucket sum equal to span, the last row of a second kept, the driving thresholds 0.04 / 0.06 and omega alone, the floor
  round-trip with -0.01 → -1, 0.0 → 0 and -1.84 → -4, the orderId gap rule, charging → `""`, the station-share rule and
  the label hit window.
- The data tests (one real shift: 0 rejects, Detector, Table 7 count) ran with 0 skips according to the builder and both
  refuters. With the raw symlink removed they skip and the file still passes.
- PR CI: `gate` SUCCESS, GitGuardian SUCCESS.
- Builder self-report: root gate 1073 tests OK (4 skipped), fleet gate 645 OK (4 skipped).

Weak points named by the refuters, none of them refuting:

- the `# inject:` red cases are comments and were not run;
- the data tests cover one shift; the other eight are covered only by `--analyse`;
- two of the pooled sanity checks are tautologies;
- `analyse()` raises on a bucket mismatch instead of storing a failed check;
- the committed results JSONs are 124 KB and 168 KB, mostly the false-alarm lists.

`.gitignore`: `fleet/data/` became `fleet/data/*`, `!fleet/data/moroop/`, `fleet/data/moroop/*` and
`!fleet/data/moroop/stations.json`. The correctness refuter's `git check-ignore` found raw/, jsonl/ and filelist.txt
ignored and stations.json tracked.

## 8. Not done / open for the operator

- README and SCOPE were not edited, as the job file requires. The real-data row is for the docs pass.
- Diagnostics show Error and Warning levels; mapping them to faulted is open and stays rank F.
- The per-source gap rule for change-only logs is open.
- The detector's station-cell exclusion is open. It is the S12A "exclusion question", which is no longer moot on real
  data.

## 9. Merge

Local gate on the PR head, run by the main loop with the main checkout's `.venv`:

- `unittest discover -s tests`: Ran 1073, OK (skipped=4).
- `unittest discover -s fleet/tests -p 'test_fleet_*'`: Ran 645, OK (skipped=4).
- `fleet.tests.test_fleet_moroop`: Ran 15, OK, 0 skipped with the data present.

PR #49 was squash-merged as **e5d0808** and master was fast-forwarded with `git merge --ff-only`. The pre-existing
uncommitted `results/fleet/deadlock_*.json` changes were left untouched.

On master, `git check-ignore` shows `fleet/data/moroop/raw/` and `fleet/data/s10-none` ignored, and
`git ls-files fleet/data/moroop` lists only `stations.json`.

SCHED_RESULT: OK S13A merged e5d0808 (PR #49): MoRoOp time budget on 9 real shifts, 0 rejects, stuck 0.42% (1107 of 1113 s in the 30 Jul manual intervention), label 2/2 >=30 s detected via one 133 s off-station run, 542/544 false alarms are station dwells

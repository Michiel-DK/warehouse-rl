82e3c5e907d9f9a15fd6d6b30eda8d5f8acef1fcbb569ac9aba8a0c3887390fe

# S14A servicing bound: lane report

**Byte identity (the hash above).** sha256 of the Detector event stream (`json.dumps(ev, sort_keys=True)` per event, newline-joined) over `fleet/data/s10-none/zone0-000.jsonl.gz` (6000 messages, 1610 events, 2 servicing runs) with `Detector(stations=load_stations('auto', fleet/data/s10-none), station_radius=0)`, the bound absent. Measured on master 61d93fa before any edit and again on this branch with `servicing_max_s` absent and with `servicing_max_s=None`: equal (82e3c5e9..., darwin-arm64). Pinned per platform in `tests/platform_expected.json` (`fleet_stream.darwin-arm64.s14a_s10_none_zone0_stations_auto_event_sha256`), checked by test `t`; linux has no value yet, so `t` skips there visibly. The existing S13B stations-absent pins are untouched and still pass. With the bound absent no event carries a new key (asserted in `event_stream_sha`).

Script used for the master value (`python -I`, the `__main__` guard is needed because `--stations auto` spawns a process):
`load_stations("auto", dir)`, `Detector(stations=st, station_radius=0)`, `read_messages(zone0)`, `end_all()`.

## What changed (files)

- `fleet/fleet_analyser/detector.py`: `Detector(servicing_max_s=None)`, `station_overruns`, `CAUSE_LABELS` (the one exported map), `station_overrun` appended to `CAUSES`, `stations_of()` (the zone lookup, moved out of the method, behaviour unchanged).
- `fleet/fleet_analyser/servicing.py` (new): `dwell_sample`, `auto_bound`, `resolve`, `parse_spec`.
- `fleet/fleet_analyser/causes.py` (new): `causes_table`, `causes_block`.
- `fleet/fleet_analyser/ingest.py`, `fleet/ingest.py`: `servicing_max_s` / `servicing_stats` on `Pipeline` and `Ingester`; CLI flag; `cause_label` on every episode row.
- `fleet/timebudget.py`, `fleet/deadlock.py`, `fleet/adapters/moroop.py`: flag, bucket rule, causes.
- `fleet/fleet_analyser/report.py`, `fleet/report.py`: causes tables, optional `--timebudget`.
- `fleet/fleet_analyser/score.py`: `station_overrun` no longer a KeyError in the confusion table (`setdefault`, agrees with `other`); output unchanged when no overrun matched.
- `fleet/sql/schema.sql`: `cause_label` column + `ALTER ... ADD COLUMN IF NOT EXISTS`.
- `fleet/tests/test_fleet_detector_servicing_bound.py` (25 tests), `tests/platform_expected.json`.
- laptop-scheduler: item `wr-s14a-rerun` (commit 5d703f7).

## Rules stated

**Emission rule.** A SERVICING run (station, stopped >= 30 s, not faulted) converts at the first still-stopped, non-faulted observation with `ts - stop >= T`. `episode_open` has `t_entry` = that ts, `start` = the stop time, `cause` `station_overrun`, `blocker` None, `servicing_s` = T. A stop whose ending message is at exactly stop+T opens nothing, because the observation at stop+T is the ending message, not a stopped one; so "duration > T" and "observation >= stop+T" agree. Tests use a message every 10 s: the 60 s stop is stopped at 0..50 and driving at 60. T < 30 converts at the first SERVICING observation (30 s).
**FAULTED.** Before T: `faulted_self` as today, that episode is the run's only one, no conversion (`station_overruns` 0). After the conversion: state FAULTED, the open `station_overrun` episode is untouched (the cause is decided once, as for any open episode), STUCK again when the fault clears (test `e`). Neighbours of a converted robot read `blocked_by_stuck` (test `f`).
**Counters.** `servicing_runs` still counts the run; `station_overruns` counts conversions.
**Auto bound.** `T = min(300, exp(Q3L + 3 (Q3L - Q1L)))`, type-7 (numpy default) quartiles of ln(dwell); `servicing_q1_s` / `_q3_s` are `exp(Q1L)` / `exp(Q3L)`. Sample: every stopped-with-order stretch (the detector's run) whose first cell is within `station_radius` of a station, of any length; dwell = ending message ts - first ts; a stretch still open at the end of the input counts with last ts - first ts (a lower bound); dwell <= 0 is dropped (ln undefined). n < 5: T = 300. A number S is used as given and the sample statistics are still computed so the four keys exist. **Pooling: one T per ingested run, all robots of all zones of the glob pooled, each zone against its own station set.** For MoRoOp a shift is a run, so one T per shift. n = 5 stops of 20, 30, 40, 50, 600 s give T = 231.48 (test g); the n = 6 case [20, 30, 40, 50, 50, 60] gives 186.557 (log space, by hand Q1 = 30 (4/3)^0.25) against 182.07 in raw space (test h).
**Ingest needs the whole run on disk** for `auto`/number (a first pass `read_messages(glob)` before the Ingester starts). Kafka source and ClickHouse: not supported with the flag.

## (a)-(g) checklist

- (a) Detector flag, hash, no new keys, `servicing_s` only on overrun episodes: tests a-f, t.
- (b)/(c) CLIs on ingest, deadlock, timebudget, moroop: tests g-k, u, v. Ledger (`ingest_runs`) gets `servicing_max_s`, `servicing_sample_n`, `servicing_q1_s`, `servicing_q3_s`, `station_overruns` only with the flag (test u); timebudget and deadlock result files get the four keys at top level plus `servicing_pooling`; MoRoOp: per shift in each label object, lists in shift order in the pooled files and `moroop_label-<suffix>.json`. Constraints: timebudget `--servicing-max-s` needs `--station-aware`, deadlock needs `--stations`, ingest needs `--stations`, moroop needs `--station-radius` (in build mode the flag is accepted, ignored, with a stderr note, so every moroop call in the rerun carries it).
- (c) buckets: partition exact (`check_bucket_sum` raises otherwise; tests l, m, n). Non-converted station stop of >= 30 s: all its seconds in `waiting_station` whatever the cell. Overrun stop: stuck, none in `waiting_station`.
- (d) labels and causes: below.
- (e) the 25 tests pass, none skipped in this file here (MoRoOp smoke ran; it skips only without the raw dir or pyarrow).
- (f) queue item: below.
- (g) `git diff --name-only 61d93fa` lists no README.md, docs/SCOPE.md or vendor/ path.

### Deviation from the criterion wording

"An overrun stop puts its whole duration in stuck." True on the hand-made stream (test l) and on the simulator runs. It is **not** true when the stop contains a gap > 60 s, a paused or a faulted message: those intervals keep their higher bucket (no_data > faulted > paused > the rest, unchanged precedence). On MoRoOp shift 6 the overrun episode lasts 3245 s; its seconds in the per-second buckets are stuck 1100, no_data 2091, paused 54. I kept the precedence rather than let a stuck rule overwrite "no data"; the causes table reports episode seconds and the shares make the difference visible.

### Flag absent versus master (tools, input: a /tmp copy of fleet/data/s10c-blind, `--stations auto`, master 61d93fa extracted with `git archive`)

- `deadlock.py` output: `cmp` identical.
- `timebudget.py` output: identical except the `causes` blocks and the store path / store hash (my two stores differ in `cause_label`).
- `ingest.py`: `stuck_episodes` rows identical once `cause_label` is dropped (1276 rows), `transitions` (12383), `evidence` (638) and `decisions` (638, apart from `recorded_at`) identical, `ingest_runs` has the same keys (`servicing_runs`, no new key).
- Additions with the flag absent (the list the criterion asks for): `cause_label` on every `stuck_episodes` row (ingest/store layer, `Pipeline._handle`, from `CAUSE_LABELS`; never in the Detector event stream); `causes` in timebudget output (every robot and picker, `zones[z].totals`, `run.totals`); the `## Causes` and `## Causes per robot` sections of `report.md`; `causes` and `overruns` in every MoRoOp label object; the `cause_label` ClickHouse column. The causes table lives in `fleet_analyser/report.py` (`fleet/report.py` CLI, optional `--timebudget PATH`, shares n/a without it) and in timebudget output.

### Causes tables

Rows: cause, label, episodes, episode seconds (`duration_s`; episodes without a duration are not counted and reported as `uncounted_open_episodes`), share of the time budget's stuck bucket; ordered by seconds descending, then cause key ascending (test p). `report.md` counts the countable episodes (as the rest of that report). **The shares do not sum to 1 and I do not force them:** `share_total` is reported. On the simulator runs it is 2.0-4.1 because a stuck episode on a shelf-adjacent cell is `waiting_shelf` seconds in the budget (s10-none: waiting_shelf 57,570 s against stuck 41,545 s), a faulted_self episode is mostly faulted-bucket seconds, and the stuck bucket holds nothing from gaps and pauses. Tests: p, q, w.

## Measurements (smoke only: nothing here is a sweep; outputs under /tmp, no results/ file written)

**Simulator runs, `--stations auto --servicing-max-s auto`, radius 0.** T = 80 s on all five (sample 436 / 387 / 196 / 392 / 377 stops, Q1 5 s, Q3 10 s: the 5 s step quantises the dwells, so 10 (10/5)^3 = 80). The criterion's expected "no bucket moves" is wrong: station stops over 80 s exist in two runs.

| run | station_overrun episodes | bucket moved (waiting_station -> stuck) |
|---|---|---|
| s10-none | 0 | none |
| s10c-blind | 1 (265 s) | 265 s |
| s10-breakdown | 0 | none |
| s8b-score | 0 | none |
| closed_loop (sticky phase A) | 25 (5,365 s) | 5,365 s |

Other totals do not move. `start_sets_equal` (timebudget stuck runs vs detector episodes) is True on four runs; s10-breakdown has 517 vs 522 with and without the flag (pre-existing, S13B: a faulted station stop is an episode in the detector but not a stuck run in timebudget).

**MoRoOp, radius 1, `auto` per shift** (the full rerun legs were run into /tmp: build, nine per-shift timebudget calls, `--analyse`; exit 0, every sanity check true, stations file identical to the tracked one). T = 300 s in all nine shifts (cap binds: Q1 2-6 s, Q3 19-22 s, n 778-835).
- Overruns: 4, in shifts 1, 6, 7, 8: 2026-07-27T19:03:16Z 318 s cell [9, -3]; **2026-07-30T06:16:31Z 3245 s cell [15, -1] (shift 6: the S13B "1,107 s stop"; 1,100 s of it is in the stuck bucket, see the deviation above)**; 2026-07-31T10:00:24Z 343 s cell [15, 0]; 2026-07-31T17:43:15Z 344 s cell [15, 0]. All four overlap a TIMEOUT operation.
- TIMEOUT operations overlapped by a stuck run: **5 of 8** (was 1 of 8 with radius 1 alone); 4 of those by overruns.
- Unlabelled station-cell stuck runs: **3** (Part 4 bar <= 54; before the bound 0 at radius 1). False alarms in total 5 (was 1). Label hits unchanged, 2 of 2.
- The 1,107 s stop does not stay hidden. No tuning of T was done; the cap is Part 4's.
- Pooled buckets against the committed `-st` file: stuck 13 -> 1,773 s, stopped_short 2,970 -> 1,870 s, waiting_station 107,665 -> 107,005 s. Causes pooled: station_overrun 4 episodes 4,250 s, unknown 2 episodes 180 s, stuck bucket 1,773 s, share_total 2.50.

## Queue item

`wr-s14a-rerun` in `<local>/laptop-scheduler/queues/warehouse-rl.json`: the S13B command with `-st` -> `-sb` throughout (`store-sb`, `*-sb.json`, `DIR-sb` views, `jsonl-sb`, `budget-sb`, `stations-sb.json`), `setopt shwordsplit` first, the `${V:+--flag} ${V:+$V}` forms kept, `--servicing-max-s auto` on each ingest / timebudget / deadlock / moroop call (the per-shift MoRoOp budget calls also carry `--station-aware --station-radius 1`, which the budget check needs), the hash guard `grep -v -- '-sb\.json$'` (the existing `-st` files stay in the hash and are never written, so they are not flagged). cores 4, est 10 / max 40 minutes, note says about 3 minutes (the S13B rerun was 157 s on 4 workers; the extra first pass is small). **The command was not run**; its legs were smoked separately into /tmp (above). Committed on its own as 5d703f7. The working tree of that repo holds about 1,500 lines of other uncommitted queue edits, so the commit contains only this item added to HEAD's file (built with `hash-object` / `update-index`); the working file has the same item text and the other edits are untouched.

## Not done / limits

- ClickHouse DDL has `cause_label` only; `servicing_s` and the `ingest_runs` servicing columns are not in it (the flag needs `--stations`, which has no ClickHouse columns for `servicing_runs` either).
- `fleet/overview_build.py` has its own cause wording table (static, built from stored data); `station_overrun` is not added there.
- `score.py` calls an overrun episode `other` for the cause agreement (a proxy).
- Linux: the new hash pin has no value.

## Tests

`.venv/bin/python -m unittest discover -s fleet/tests -p 'test_fleet_*.py'`: Ran 686, OK (skipped=7; the same 7 as on master, 661 tests there, +25 here, none skipped in the new file).
`.venv/bin/python -m unittest discover -s tests`: Ran 1114, OK (skipped=7) (run in this worktree with the main checkout's venv; the worktree has no .venv of its own).

## Merge (main loop, 21 Oct 2026)

Criterion pre-review halted 3 times (cause_label vs hash layer; flag-gating and partition; log-space quartiles); the 4th
criterion passed. Review round: python-reviewer pass; refuters correctness, regression, test-honesty, scope-adherence,
invariants all non-refuting. Builder set criterion_met false only for the two deviations stated above (overrun seconds
keep no_data/paused/faulted precedence; T = 80 s moves 265 s on s10c-blind and 5,365 s on closed_loop). Gate re-run by
the main loop on PR head 7013404: fleet/tests Ran 686 OK (skipped=7), tests Ran 1114 OK (skipped=7). Squash-merged as
PR #51 -> 95feaaf, master fast-forwarded. Operator questions: the 1,107 s stop is now a 3,245 s episode (2,091 s no_data
inside it); causes shares sum to 2.0-4.1 against the stuck bucket.

SCHED_RESULT: OK wr-lane-s14a PR #51 merged 95feaaf; gate 686+1114 OK; MoRoOp TIMEOUT overlaps 5/8 (was 1), unlabelled station-cell stuck 3 (bar 54); wr-s14a-rerun written (5d703f7), not run

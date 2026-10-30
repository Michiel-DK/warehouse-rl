# S18A keep what matters: lane report

Question (operator, 30 Oct, buyers): how small can a fleet state log get while every answer the analyser gives stays the
same. Standard name (docs/LITERATURE.md Part 10 section 1): report by exception (change-only) with a maximum interval, zero
deadband. This is not compression; gzip over the full log is the baseline the ratio is measured against.

Built: `fleet/reduce.py` (keep rules R0-R5), `fleet/reduce_check.py` (full vs reduced, exact),
`fleet/tests/test_fleet_reduce.py`. Results: `results/fleet/reduce_s10-none.json`, `results/fleet/reduce_moroop-sf.json`
(both written by `reduce_check`; the tables below are `reduce_check.py --table` of those files, nothing retyped).

## Verdict against the refute line (set before the run, Part 10 section 5)

| run | H = 30 s | H = 60 s |
|---|---|---|
| s10-none | identical (first_identical_rule recovered, ratio_gzip 1.1820) | identical (recovered, ratio_gzip 1.1816) |
| moroop-sf | identical (threshold, ratio_gzip 1.0001) | identical (threshold, ratio_gzip 1.0002) |

**Overall: `identical`** (both runs identical at both H): on these two runs a reduced stream gives identical outputs, no
tolerance. **ratio_gzip at first_identical_rule is below 3 in all four cells (1.18, 1.18, 1.0001, 1.0002): not worth
pitching.** The line ratio at the same rung is 1.50 (H = 30) and 1.55 (H = 60) on s10-none, 1.0003 and 1.0004 on MoRoOp.
"Identical" and "worth it" are different questions; the first is answered yes, the second no, on these two runs.

Scope of "identical": the six outputs listed below on a 10-zone x 500-step simulator run (`s10-none`: 120 robots, 83.2
robot-hours, no disturbance) and nine MoRoOp shifts (9 robots, 73.0 robot-hours). Not run: `s10-none-8h`, `s10c-blind-8h`
(queue item wr-s18a-run).

## The ratio and its three references (Part 10 section 2)

`ratio_gzip` = gzip bytes of the full log / gzip bytes of the reduced log. Both sides are the decompressed lines re-gzipped
per file with the same compressor and level (Python gzip, compresslevel 9, mtime 0), never the emitter's .gz size, so R0 is
exactly 1.0 (test). The three references:

- (a) gzip of the full log: the ratio is against it. On s10-none the line ratio at recovered / H = 60 is 1.55 but
  ratio_gzip is 1.18: gzip already removes most of the repetition that change-only removes, so reduction on top of gzip buys
  little.
- (b) kept lines per robot-hour against the emitted rate. Robot-hours = per (file group, robot serial) last accepted ts minus
  first accepted ts in the full input, summed over all robots (pickers included), divided by 3600; the same denominator for
  lines in and lines kept. s10-none: 721.4 lines per robot-hour emitted (the sim emits every robot every 5 s = 720), kept
  480.3 (H = 30) / 464.6 (H = 60) at recovered. MoRoOp: 1820.3 in, 1819.8 (H = 30) / 1819.6 (H = 60) kept at threshold.
- (c) the 3:1 floor (AVEVA suggested minimum, a vendor rule of thumb, D). AVEVA's 3:1 counts events; on gzip bytes it is the
  stricter reading, and the line ratio is reported next to it for the like-for-like reading. Neither reaches 3.

## Caveats that go next to the number

- **MoRoOp is already change-only** (README (q)), and its `theta` changes on almost every line (the change test has zero
  deadband and `theta` is a Message field), so `change` keeps 99.93 % of the lines (132,740 of 132,838). A ratio near 1 there
  is expected and is not a refutation. What the MoRoOp cell shows is that the reduction is harmless there (identical outputs,
  including the labelled stops and the S15A rows), not that it pays.
- **A VDA 5050 fleet already sends `state` change-only with a 30 s heartbeat**, so the simulator's every-step stream overstates
  the gain for such a fleet: the simulator ratio is the best case. A real VDA 5050 fleet's gain is against `visualization`
  messages or bags, which the analyser does not read.
- The sim lines carry a `custom` block (simulator ground truth, never read by the reducer or the analyser); its bytes count in
  the byte numbers.
- `sequence_gaps` / `missing_messages` are reported next to the flags, not in them. Dropping lines leaves headerId holes by
  construction: s10-none full log 0 gaps; reduced (recovered) 6466 gaps / 20056 missing at H = 30, 5481 / 21359 at H = 60.
  MoRoOp full 9 / 9; reduced (threshold) 42 / 45 and 44 / 61. A consumer that alarms on headerId holes would alarm on a
  reduced log.

## Args per run

| | s10-none | moroop-sf |
|---|---|---|
| glob | fleet/data/s10-none/zone*-000.jsonl.gz (main checkout; absolute paths in the JSON) | fleet/data/moroop/jsonl-sf/zone*-000.jsonl.gz |
| --stations (reduce.py Detector and every analysis) | omitted (null) | fleet/data/moroop/stations-sf.json |
| --station-radius | omitted (null) | 1 |
| --servicing-max-s | omitted (null) | 300.0 |
| max gap (timebudget) / stuck_after | 60 / 30 | 60 / 30 |
| bucket cell sets (timebudget layout only) | auto: the full log's emit_ledger.json, one layout applied to full and reduced | the stations file (shelves empty) |
| H | 30, 60 | 30, 60 |

The result files record `servicing_max_s` (number or null), `stations` and `station_radius` under `args`. Provenance of the
MoRoOp values: station radius 1 = `results/fleet/moroop_label-sf.json` `station_radius` and
`results/fleet/timebudget_moroop-sf.json` `src.station_rule.radius` (the two agree); servicing_max_s 300.0 =
`timebudget_moroop-sf.json` `servicing_max_s`, 300.0 on all 9 shifts. `stations-sf.json` has the same sha256 as
`stations.json` (3755543f...), the file those results cite. s10-none: `results/fleet/timebudget_s10-none.json` has only
run/src/zones (not station-aware, no bound), so the three flags are omitted and R3 keeps only the stuck_after line.

Check that the arguments match the full-log run: the full-log MoRoOp label counts computed by `reduce_check` (stuck_runs 4,
hits 2, misses 0, false_alarms 3, timeouts 8 of which 3 detected, episodes 77) equal `moroop_label-sf.json`
`pooled.counts` (`full_label_sf_pooled` in the result file).

## Design choices a reviewer should know

- **Unit of work is a file group, not the glob.** `zone<z>-<nnn>.jsonl.gz` files of one `<z>` form a group; any other name is
  its own group. Robots are keyed (group, serial) because MoRoOp serials (`moroop-amr-1`) have no zone prefix and recur in
  every shift file; a whole-glob key would merge nine shifts into one robot. Reducer and `reduce_check` both work per group
  (the existing MoRoOp runs were one per shift). For s10-none each group is one zone, so this equals the glob.
- **Canonical per-robot sequence** = what `timebudget.kept_messages` / `hotspot.read_messages` give the analyses (lines that
  parse, first of each (serial, headerId), sorted by (ts, headerId), ts <= previous dropped). R1-R5 run on it; lines outside
  it are dropped by every rule except `all`. Counts on both runs: 0 rejects, 0 duplicates, 0 out-of-order.
- **Rungs are strict supersets** (R3 = R2's set plus the threshold lines, no re-optimised heartbeat), tested. The summary has
  `kept_by_rule` (cumulative per rung) and `added_by_rule` (marginal).
- The in-reducer Detector is `fleet_analyser.detector.Detector` unchanged, fed parsed Messages only, with the stations /
  radius / bound the full-log analysis gets. R4 uses every `episode_open` `t_entry` (every cause); R5 every closed episode that
  is not `unresolved`.
- `reduce_check` compares per group and merges: time budget (seconds, share, span, jobs per robot; same_minute_stops per
  zone), stall list, transitions, station bound (detector counters and the station_overrun episodes; station-aware runs
  only), S15A rows N1 and N2-W (counts, gap-spanning alerts, episodes by start / alert / end / resolution) and the labelled-stop
  hits (the sf label match, the per-stop alerts and latencies of every S15A rule, box stillness, stopped run); the last two
  with `--moroop-raw` only. No kept index is compared. Transitions are keyed (robot, n-th transition), so a dropped transition
  shifts the later keys and the diff `count` counts the shifted ones too.
- No file under vendor/, fleet/fleet_analyser/, docs/, README.md, fleet/timebudget.py or fleet/stall_baseline.py is changed; no
  site copy; no ratio in README.

## Per run, per H (every rung listed)

### s10-none

s10-none, H = 30 s (lines per robot-hour in: 721.4); first_identical_rule: recovered; verdict: identical

| rung | ratio_gzip | line_ratio | kept lines/robot-h | time_budget | stall_list | transitions | station_bound | s15a_rules | label_hits | all_identical |
|---|---|---|---|---|---|---|---|---|---|---|
| all | 1.0000 | 1.0000 | 721.4 | identical | identical | identical | not_applicable | not_applicable | not_applicable | True |
| change | 1.2646 | 1.7996 | 400.9 | diff n=117 max_s=2195 robots=117 | diff n=627 max_s=None robots=110 | diff n=8230 max_s=1305 robots=113 | not_applicable | not_applicable | not_applicable | False |
| gap | 1.2185 | 1.6134 | 447.2 | identical | diff n=41 max_s=None robots=30 | diff n=5425 max_s=525 robots=83 | not_applicable | not_applicable | not_applicable | False |
| neighbours | 1.1843 | 1.5096 | 477.9 | identical | identical | diff n=5187 max_s=525 robots=79 | not_applicable | not_applicable | not_applicable | False |
| recovered | 1.1820 | 1.5021 | 480.3 | identical | identical | identical | not_applicable | not_applicable | not_applicable | True |
| threshold | 1.2183 | 1.6132 | 447.2 | identical | diff n=37 max_s=None robots=27 | diff n=5420 max_s=525 robots=80 | not_applicable | not_applicable | not_applicable | False |

s10-none, H = 60 s (lines per robot-hour in: 721.4); first_identical_rule: recovered; verdict: identical

| rung | ratio_gzip | line_ratio | kept lines/robot-h | time_budget | stall_list | transitions | station_bound | s15a_rules | label_hits | all_identical |
|---|---|---|---|---|---|---|---|---|---|---|
| all | 1.0000 | 1.0000 | 721.4 | identical | identical | identical | not_applicable | not_applicable | not_applicable | True |
| change | 1.2646 | 1.7996 | 400.9 | diff n=117 max_s=2195 robots=117 | diff n=627 max_s=None robots=110 | diff n=8230 max_s=1305 robots=113 | not_applicable | not_applicable | not_applicable | False |
| gap | 1.2040 | 1.7104 | 421.8 | diff n=26 max_s=150 robots=26 | diff n=233 max_s=None robots=93 | diff n=6470 max_s=525 robots=113 | not_applicable | not_applicable | not_applicable | False |
| neighbours | 1.1839 | 1.5608 | 462.2 | identical | identical | diff n=5187 max_s=525 robots=79 | not_applicable | not_applicable | not_applicable | False |
| recovered | 1.1816 | 1.5528 | 464.6 | identical | identical | identical | not_applicable | not_applicable | not_applicable | True |
| threshold | 1.2088 | 1.6792 | 429.6 | identical | diff n=40 max_s=None robots=29 | diff n=5420 max_s=525 robots=80 | not_applicable | not_applicable | not_applicable | False |

### moroop-sf

moroop-sf, H = 30 s (lines per robot-hour in: 1820.3); first_identical_rule: threshold; verdict: identical

| rung | ratio_gzip | line_ratio | kept lines/robot-h | time_budget | stall_list | transitions | station_bound | s15a_rules | label_hits | all_identical |
|---|---|---|---|---|---|---|---|---|---|---|
| all | 1.0000 | 1.0000 | 1820.3 | identical | identical | identical | identical | identical | identical | True |
| change | 1.0004 | 1.0007 | 1818.9 | diff n=1 max_s=1088 robots=1 | identical | diff n=2 max_s=2841 robots=1 | identical | diff n=4 max_s=None robots=1 | identical | False |
| gap | 1.0001 | 1.0003 | 1819.8 | identical | identical | diff n=1 max_s=4 robots=1 | identical | identical | identical | False |
| neighbours | 1.0001 | 1.0003 | 1819.8 | identical | identical | identical | identical | identical | identical | True |
| recovered | 1.0001 | 1.0003 | 1819.8 | identical | identical | identical | identical | identical | identical | True |
| threshold | 1.0001 | 1.0003 | 1819.8 | identical | identical | identical | identical | identical | identical | True |

moroop-sf, H = 60 s (lines per robot-hour in: 1820.3); first_identical_rule: threshold; verdict: identical

| rung | ratio_gzip | line_ratio | kept lines/robot-h | time_budget | stall_list | transitions | station_bound | s15a_rules | label_hits | all_identical |
|---|---|---|---|---|---|---|---|---|---|---|
| all | 1.0000 | 1.0000 | 1820.3 | identical | identical | identical | identical | identical | identical | True |
| change | 1.0004 | 1.0007 | 1818.9 | diff n=1 max_s=1088 robots=1 | identical | diff n=2 max_s=2841 robots=1 | identical | diff n=4 max_s=None robots=1 | identical | False |
| gap | 1.0002 | 1.0004 | 1819.5 | identical | identical | diff n=1 max_s=31 robots=1 | identical | identical | identical | False |
| neighbours | 1.0002 | 1.0004 | 1819.6 | identical | identical | identical | identical | identical | identical | True |
| recovered | 1.0002 | 1.0004 | 1819.6 | identical | identical | identical | identical | identical | identical | True |
| threshold | 1.0002 | 1.0004 | 1819.6 | identical | identical | identical | identical | identical | identical | True |

Reading: on s10-none `change` alone is not enough (117 budget items and 627 stall-list items differ). `gap` fixes the budget at
H = 30 but not at H = 60 (26 robots, max 150 s): the budget calls a stopped run stuck from the run's own last kept line, and a
60 s heartbeat does not guarantee a kept line 30 s into a stop. `threshold` fixes that, `neighbours` fixes the stall list (the
cause needs the T_entry batch), `recovered` fixes the transitions (the line after the ending line). On MoRoOp `threshold` is
enough, and `neighbours` and `recovered` add no lines at H = 60.

## Tests and the injection that turns each red

`fleet/tests/test_fleet_reduce.py`, 18 cases, plain unittest. Each injection was applied to the code with a throwaway script
(not committed), the file was run, the named case(s) went red, and the code was restored. "Not mutation-run" means the case
exists and passes but I did not run an injection against it.

| case | injection that turns it red | observed red |
|---|---|---|
| identity (R0 byte-identical, ratio_gzip 1.0, all_identical) | `all` drops the first line | test_identity_and_ratio, test_rungs_are_nested |
| every output line equals the input line at its source index | re-encode or reorder a kept line | not mutation-run |
| dropped transition makes the check report a diff | `compare()` returns identical for a missing item | test_dropped_transition_is_a_diff (and 6 more) |
| gap survives as a gap, no interval longer than H | R2 heartbeat step off | test_gap_survives_as_gap_and_no_interval_longer_than_h |
| source gap ends kept (H = 120, because H <= 60 hides the step) | R2 gap-ends step off | test_source_gap_ends_are_kept_even_when_h_is_longer_than_the_gap_rule |
| R3 fixture (H = 60): a stop reduced to first and ending line opens no episode | R3 threshold step off | test_r3_a_stop_reduced_to_first_and_ending_line_opens_no_episode (and the R4 case) |
| R4 fixture (H = 60): neighbour vanishes, cause becomes unknown | R4 T_entry batch step off | test_r4_a_stationary_neighbour_vanishes_and_the_cause_becomes_unknown, test_scenario_ladder, test_stations_reach_the_in_reducer_detector |
| R5 fixture (H = 60): transition out of RECOVERED moves under R4 | R5 next-line step off | test_r5_the_transition_out_of_recovered_moves_under_r4, test_scenario_ladder |
| re-indexing (MoRoOp-shaped, `change`) | add the kept indices a / b to the compared episode fields | test_s15a_rows_and_label_hits_equal_by_timestamp |
| custom garbage (every rule, H in 30, 60, with and without stations) | put `raw_len` into the change signature | test_garbage_custom_gives_the_same_kept_indices |
| stations reach the in-reducer Detector | build the Detector without stations / bound | test_stations_reach_the_in_reducer_detector |
| determinism | gzip with the wall-clock mtime | test_determinism |
| 'auto' rejected | accept 'auto' as a number | test_auto_servicing_bound_is_rejected |
| rungs nested | R3 re-optimises the heartbeat | test_rungs_are_nested (and the R3 and R5 cases) |

The garbage-custom case replaces `custom` with different JSON of a different length on fixtures; it does not run on the two real
runs. At H = 30 a greedy heartbeat from a kept run start lands on since + 30, so R2 already gives R3's line (visible in the
s10-none H = 30 table: gap and threshold keep the same lines); the R3 case is therefore built for H = 60.

## Gate

The PR description pastes the summary lines of `.venv/bin/python -m unittest discover -s tests` and
`.venv/bin/python -m unittest discover -s fleet/tests -p 'test_*.py'`.

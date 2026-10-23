# wr-dev-s12a-readme: README Sprint 12 (o) + (p), SCOPE Sprint 12 (2026-10-20)

## Done
- Results committed by explicit path, 612518b: 5 `results/fleet/timebudget_*.json`, 4 `deadlock_*.json`,
  `gapmap_s12-deadzone.json`, `hotspot_s12-deadzone.json`.
- `scripts/sprint8_tables.py` gains (o) `time_budget()` and (p) `blocking_clusters()` (+ gap-map line). README
  "Sprint 12: where the shift goes" = its output verbatim (checked: generated block is a substring of README), headings
  demoted; "Reading the numbers" + caveats. SCOPE gains "Sprint 12" with S12A/S12B and both runs ticked, the open operator
  question "Exclude station and shelf waits from the stall list? (changes every Sprint 5-10 stall count)", and the
  same-minute question.
- Vocabulary from LITERATURE.md Part 2: bucket columns carry the standard class (SEMI E10 / Standridge), throughput for
  jobs per AGV-hour, "blocking cluster" for JSON `deadlocks` and "blocking chain" for `knots`, "message-loss cells
  inferred from headerId gaps". Part 2 names "circular wait in a wait-for graph" as the standard for deadlock, but
  deadlock.py's own definition string says "not a proven circular wait" (symmetric adjacency) and the operator ruled
  these congestion (17:55), so the README does NOT use the deadlock name; it cites Part 2 for why. "ours" appears
  nowhere in the new section (grep -w).

## Headline numbers (all from the JSONs through the script)
- Stall list episodes starting on a station cell: 1.1%-1.9% (7/657 .. 47/2411). Shelf-adjacent: 76.3%-97.2%, but the
  class is 360 cells/zone, so not a picker-wait measure; picker episodes are in N (79/677, 998/2411). Detector unchanged.
- Undisturbed AGVs: moving 40.0%, waiting_shelf 28.8%, stuck 20.8%, 22.18 jobs/AGV-h; sticky 12.1% moving, 7.02.
- Blocking clusters: s10-none 49 (108.2 robot-s/robot-h), blind 1.35x, breakdown 1.51x (5 chains), sticky 2.78x;
  censored at stream end 1 / 3 / 0 / 18. Top cell s10-none = s10c-blind: zone 4 cell 7,4, 19 clusters, 1330 s (one
  robot pair re-forming).
- Gap map (synthetic): recall 57/60, precision@10 0.57 vs ceiling 0.60; 97 decisions written, 3 refused by store dedup
  (no zone in key), 94 graded.

## Not done / caveats
- No s8b deadlock JSON exists (wr-s12b-run never ran deadlock.py on it); (p) has 4 runs, noted in the table text.
- `same_minute_stops`: split into zone-start minute vs later, derived from `zones.*.same_minute_stops.minutes` against
  the emitter's DEFAULT_T0.
- Report for S12A lane lives in warehouse-rl `reports/` (untracked), not here.

## Gate and commits
- `.venv/bin/python -m unittest discover -s tests`: Ran 1038 tests in 667.694s, OK. `fleet.tests.test_s11a_explorer`
  (imports sprint8_tables): Ran 47 tests, OK.
- 612518b results JSONs; f91adfa README + SCOPE + scripts/sprint8_tables.py; d354d23 standoff columns (below); all
  pushed to origin/master. The tests/ gate ran on f91adfa; it was not rerun for d354d23 because tests/ does not import
  sprint8_tables. The only importer, fleet.tests.test_s11a_explorer, was rerun: 47 tests OK.

## Correction after review (d354d23)
- The first draft said zone 4's top cell was "a repeating traffic jam, not a jam that never clears". That was wrong. One
  robot pair, Z4-02 and Z4-05, blocks from 00:19:10 to the stream end. It is cut into 75 s clusters with one-step
  (5 s) breaks, and the last cluster is open at the end.
- The script now merges each run of clusters with the same robots and gaps of at most one step into a "standoff":
  - s10-none: 49 clusters become 34 standoffs. The longest is 1,260 s (16 clusters), open at the end, and holds 26.3%
    of the blocked robot-seconds.
  - s10c-blind: 39 standoffs. The same standoff holds 19.5%.
  - Breakdown: 28 clusters become 26 standoffs.
  - Sticky: 163 clusters become 154 standoffs.
- The undisturbed ratios in (p) lean on this one pair. The operator's 17:55 reading, "congestion, every cluster
  resolves", does not hold for it. This was flagged as a SCOPE operator question; nothing was relabelled.
- "vendor planner replans after a few stuck steps" comes from the operator note / S12B report, not from this pass.

SCHED_RESULT: OK README Sprint 12 (o)+(p) + SCOPE S12A/S12B ticked + operator Qs committed f91adfa+d354d23 (JSONs 612518b), pushed; station cells start 1.1-1.9% of stall episodes, shelf-adjacent 76-97% is a 360-cell catch-all, detector unchanged; blocking clusters named per LITERATURE Part 2 (not deadlock): s10-none 108 robot-s/robot-h, sticky 2.78x, but one undisturbed zone-4 standoff (1260 s, open at end) is 26% of the baseline; gap map recall 57/60, p@10 0.57 (ceiling 0.60, synthetic); no s8b deadlock JSON; tests/ 1038 OK

# wr-dev-s10c-readme — Sprint 10 second half: README tables (h)-(k), SCOPE ticks, premise paragraph (19 Oct 2026)

**Outcome: DONE, pushed.** `master` 85df140 -> d44ed98 -> 7bc437b -> 217ecff, pushed to origin.

## Commits
- `d44ed98` results: the 9 JSONs named in the tables, staged by explicit path:
  `results/fleet/{hotspot_s10c-blind,time_to_detect_blind,hotspot_s10-none,amoc_blind}.json` and
  `results/fleet/baselines_{s8b-medium-80-p03-07,closed-loop-sticky,s8e-long-w0.5,s10c-blind,s10-none}.json`.
- `7bc437b` `scripts/sprint8_tables.py` + README + `docs/SCOPE.md`.
  - The script went direct to master with the docs, following the earlier README jobs (b3604cf, 8ad6120 did the same).
    It is a docs printer, not one of the `sensitivePaths`.
- `217ecff` follow-up after the advisor review:
  - (j) verdict now leads with "within noise", scoped to truth precision.
  - lift_ever range split by run length (1.10-1.33 on 500-step runs, 2.02 on s8e-long).
  - SCOPE premise blockage clause limited to the one re-scored run (s10c-blind).
  - (j) footnote values (max flagged, n_cells_all, n_resamples, seed, few-zone runs) are read from the JSONs, not retyped.
  - (i) footnote says what the disturbed false-flag columns exclude.
  - (a)-(g) still byte-identical; README block re-checked verbatim.
- Nothing under `reports/` or `results/closed_loop*` was staged.

## What the script now prints
- **(h) Planner-blind vs known blockage:**
  - final-map hits, precision, recall and false flags at K 20/40;
  - the (g) columns per K for both runs;
  - a per-window crosstab. The 50 windows are identical across the two runs; this is asserted.
- **(i) Undisturbed reference:**
  - final-map flagged cells per zone and false flags for s10-none next to all five disturbed S10 runs;
  - false flags per zone per publish and per simulated hour at K 10/20/40 for s10-none (from `amoc_blind.json`) next to
    blocked, outage and blind (from the time-to-detect JSONs).
  - The ttd-to-per-hour conversion is asserted equal to `fa_per_hour_measured_outside_windows` at all three K.
- **(j) Map vs persistence:**
  - truth precision, PAI (= lift_all, definitional, asserted), lift_ever, and the paired truth/outcome delta with the
    bootstrap CI and verdict. The verdict is asserted equal to the JSON's.
  - Degenerate cells are labelled, not called "within noise": "n/a, no truth positives" on s10-none; "identical top-K
    sets" where every zone flags < K and the 1 h window covers the stream (blind/none at K 40); "n/a (0 units)" for the
    sticky outcome.
  - Also prints a chance/units table and a lesson_persist table with three pools.
  - The footnote names the s8b 442 vs 200 rank-graded discrepancy.
- **(k) AMOC** by K and by cost threshold, with the saturation note and "none at any K / any cost".

## Checks run
- `.venv/bin/python scripts/sprint8_tables.py` exits 0. The (a)-(g) prefix (165 lines) is byte-identical to the output
  before the edit (`cmp`).
- The README's (h)-(k) block equals the printed output after heading demotion. Checked programmatically: True.
- `fleet.tests.test_s11a_explorer` (imports the script): `Ran 47 tests ... OK`. The full gates were not run; they are
  not touched by a docs printer.
- `baselines_s10c-blind`/`baselines_s10-none` equal `hotspot_s10c-blind`/`hotspot_s10-none` on every non-`baselines`,
  non-`platform` key.
- The queue items `wr-s10-none-run`, `wr-s10c-blind-run`, `wr-s10d-baselines-run` and `wr-s10e-amoc-run` show exit 0
  in `state/done.json`, all 2026-10-19.

## Headline numbers (all from the printed tables)
- **Map vs persistence:** within noise at K 20 on s8b (-0.008, CI -0.020 to +0.005) and sticky (+0.002). Worse at K 40
  on both, and at both K on s8e-long (3 zones). Outcome precision beats only on s8e-long (3 zones, map-decay grading).
- **Blind vs known at K 20:** 6/50 vs 7/50 windows detected while open; median 295 s vs 190 s; 0 vs 2 cleared.
  - Crosstab: 5 both, 2 known only, 1 blind only.
  - Final-map recall is 0.34 vs 0.08, but at least 11 of the 17 blind hits were flagged only after their window.
- **Undisturbed reference:** 177.8 false flag-publishes per zone-hour at K 20. Every disturbed run is within 3% of it
  at K 10/20/40.
- **AMOC:** miss share >= 0.88 at every K and cost. K >= 40 and cost >= 0.2 are saturated.

## For the operator
- The SCOPE premise paragraph states that the decay adds no measured ranking value over a raw one-hour count. It leaves
  the direction (ETAS-style model, narrower claim, or stop) to you.
- **Odd field, not investigated:** `baselines_s8b-medium-80-p03-07.json` has `rank_grading.top_k` =
  `[0.996, 1.992, ...]` (non-integer). The committed hotspot JSON has `[20]`. This looks like a grade-store artefact of
  the on-disk s8b store. The tables do not use the field.
- **Not measured:** how many robots reached a blind cell (`blind_skips` is not in any JSON). A low blind detection share
  cannot yet be split into "rarely reached" and "not ranked". This is added to the SCOPE Open list.

SCHED_RESULT: OK S10 second half documented: sprint8_tables (h)-(k) added, (a)-(g) byte-identical; 9 JSONs d44ed98, README+SCOPE+script 7bc437b + 217ecff pushed; map within noise of persistence at K20 (s8b, sticky), worse at K40; blind 6/50 vs known 7/50; undisturbed FA floor within 3%; AMOC miss >= 0.88 everywhere

# wr-dev-s10-readme — Sprint 10 README + SCOPE (18 Oct 2026)

**Result: DONE, pushed to master.** Two commits:
- `9970ebe` commits the six result JSONs, staged by explicit path: `results/fleet/hotspot_s10-{blocked,outage,breakdown,burst}.json` and `results/fleet/time_to_detect_{blocked,outage}.json`.
- `b3604cf` commits `scripts/sprint8_tables.py`, `README.md` and `docs/SCOPE.md`.

`master` is level with `origin/master`.

## What changed
- **`scripts/sprint8_tables.py`** has two new sections, and the docstring `Reads:` list is updated.
  - **(f) Analyser on other disturbances:**
    - truth positives per run by kind (floor, blocked and outage cells; frozen robots);
    - hits, precision and recall at K 20 and 40, split by kind, taken from `truth_kinds`, with the number of zones that flag fewer than K cells;
    - false flags at K 20 and 40 for all four runs (burst included), computed as Σ min(K, n_flagged) − `any` hits, plus the forecast truth grades;
    - lesson_persist with its chance rate.
  - **(g) Time to detect and time to clear:** per kind and per K, the windows, detected, missed and preflag counts, the first-detect median, the cleared count and cleared median, stale_at_end, open_at_end, and false flags per publish.
  - The script asserts cleared = detected − stale − open against the per-window records.
- **Regression check:** the (a)–(e) output is byte-identical to the output before the edit (`diff`). The README (f)/(g) block is identical to the script output (`diff`).
- **README:** a new section "Sprint 10: the analyser on other disturbances, time to detect and time to clear". The printed tables are pasted with headings demoted. The verdict sentences use counts only, and the caveats are listed.
- **SCOPE:** a new "Sprint 10" checklist with these items ticked:
  - S10A (PR #36, 46e9872);
  - S10 measure (queue item, no PR; JSONs in 9970ebe);
  - S10B (PR #38, 6ae3e00);
  - S11A (PR #37, d655d96).

## Numbers (from the JSONs, printed by the script)
- **Blocked:** in the final map, 4 of 50 blocked cells are in the top 20 and 7 of 50 in the top 40. At K 20, 7 of 50 windows were detected over time, with a median of 190 s. Of those 7, 2 cleared (median 970 s), 2 were stale and 3 were open.
- **Outage:** 1 of 20 cells is in the final map's top K, and 1 of 20 windows was detected over time, at 280 s. That window was still open at the end.
- **False flags at K 20:** the burst run, which has no truth cells, has 195. The blocked run has 195 and the outage run 199. The breakdown run has 119 frozen robots, no truth cells, and 8.9 flagged cells per zone.
- **lesson_persist:** 0 rows graded in all four runs, so there is no persist rate and no chance rate. The reason, from the `lessons.py` docstring: a lesson is graded over [e, e+W) only when the stream reaches e+W. With W = 1800 s that needs 3,600 s, and each zone streams 2,500 s. By lesson_truth, all 13 hot_cell lessons and all 6 hot_robot lessons are false alarms.

## Deviations
- **SCOPE had no Sprint 10 checklist**, and nothing in the file mentioned S10 or S11 (grep). I created the section rather than ticking existing items.
- **No per-publish false-flag figure exists for burst**, because S10B did not run on burst. (f) gives the final-map top-K count instead, and the README labels it that way.
- **The full unittest gate was not re-run to completion.** The first `tests/` run took 9:53, but its summary line was lost to my `tail -3`, and I stopped the run before `fleet/tests`. No test reads `scripts/sprint8_tables.py` or the root README: grep of `tests/` and `fleet/tests/` for `sprint8_tables` and `README` matched only `docs/replay/README.md` readers. The change is a docs file plus a print-only script.

## Operator questions
- **lesson_persist on the S10 presets** needs either a shift longer than 3,600 s or a lesson window of at most 1,250 s ≈ 0.35 h (two windows within 2,500 s). Should a rerun be queued?
- **There is no undisturbed hotspot run** to set the S10 false-flag counts against. The burst run (no truth) is the nearest reference.

SCHED_RESULT: OK S10 README+SCOPE pushed (9970ebe JSONs, b3604cf tables f/g + README Sprint 10 + SCOPE checklist); a-e output unchanged; blocked 7/50 windows detected at K20 (median 190 s), outage 1/20; lesson_persist 0 graded (stream 2500 s < 3600 s); full gate not re-run (no test reads the touched files)

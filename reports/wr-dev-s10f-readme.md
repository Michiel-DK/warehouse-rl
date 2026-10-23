# wr-dev-s10f-readme — README + SCOPE for S10F/G/H, tables (l) and (m) (19 Oct 2026)

**Outcome: DONE, pushed to master.** Follow-ups `fcbb8ad` (kill-criteria paragraph: mean vs max made explicit, the detector claim scoped to the Sprint 5 benchmark) and the mechanism-audit pointer commit d39e790 came after this list.
- `d9f1526` adds the results JSONs. Explicit paths: the 6 `results/fleet/hotspot_<run>-gate-{baseline,persistence}.json` files and the re-scored `hotspot_s10-breakdown.json`. The commit message names the lessons-window change from 0.5 to 0.2.
- `1cbba8e` changes README, `docs/SCOPE.md` and `scripts/sprint8_tables.py`.
- Push: `ae299d6..1cbba8e master -> master`.

## Inputs checked
- `laptop-scheduler/log/wr-s10f-gate-run.exit` and `wr-s10g-breakdown-rerun.exit` are both 0.
- The rerun command exits 1 on any sha256 mismatch before it touches the data. Exit 0 therefore means the re-emit was bit-identical.

## What changed
- **`scripts/sprint8_tables.py`**
  - New (l) `gate_table` and (m) `frozen_cells`.
  - (f) now scores `frozen` as a kind when `truth_kinds.frozen.cells` exists. The breakdown row used to read "none | 0 cells".
  - The (f) footnote names the 0.2 h re-score.
  - Assertions:
    - gate_grading hits and false alarms equal `grading_counts.truth`.
    - The gated `zones` and `truth_kinds` equal the ungated ones, except `frozen`, whose S10G fields the ungated JSONs predate.
    - Frozen hits equal `any` hits.
    - The publish count equals `time_to_detect_blind.json` n_publishes (9).
  - Full run: rc 0, 0 MISSING.
- **README**
  - (f) to (k) were regenerated from the script. Only (f) and (i) changed, and only their s10-breakdown rows plus the (f) kind-table header and footnote:
    - K 20 false flags went from 89 to 70.
    - Forecast truth grades went from 488/488 false to 463/488 false.
    - 2 lesson_persist rows were graded.
  - The (f)/(g) reading bullets on forecast grades, breakdown and lessons were updated to match.
  - New subsection "Sprint 10, closing" with (l), (m), "Reading the numbers" and caveats.
- **SCOPE**
  - The S10 reports list now covers (f) to (m).
  - New ticks:
    - S10G (PR #42, 5fe4501)
    - S10H (PR #43, a83c9a4)
    - S10F (PR #44, ae299d6)
    - the two runs
  - Open items updated: the lesson_persist note, gate tuning, the frozen-hit mechanism.
  - In the kill-criteria paragraph, the open question "not shown" is replaced by the measured answer.
    - The answer: the map does not beat persistence on truth precision (1 worse, 3 within noise, 1 nothing planted; the s8e-long outcome "beats" is kept as the scope caveat).
    - The stuck-robot detector and the grading loop are named as what the runs show working.
    - The premise decision is left to the operator.

## Numbers (from the JSONs, via the script)
| run | gate | forecasts | truth hits / false | precision | truth cells hit |
|---|---|---|---|---|---|
| s10-none | none / baseline / persistence | 1391 / 2 / 5 | 0 hits | 0 | no truth |
| s10c-blind | none / baseline / persistence | 1363 / 5 / 9 | 16 / 1 / 1 | 0.012 / 0.200 / 0.111 | n/a / 1 of 50 / 1 of 50 |
| closed-loop-sticky | baseline / persistence | 89 / 176 | 88 / 175 | 0.989 / 0.994 | 85 / 157 of 2400 |

On s10-breakdown, 19 of the 89 flagged cells are frozen cells (283 frozen cells in all; recall 0.067 at both K, since no zone flags 20). 25 of 488 forecasts are truth hits; before S10G it was 0.

## Things to know
1. **The S10G mechanism note predicted about 0 frozen hits. The measurement is 19 run-level and 25 forecast hits.** The README says the prediction did not hold and that the cause was not examined. It does not invent a reason. It is listed as Open in SCOPE.
2. **The S10F lane report's "S10 blockages last 60-240 s" is wrong.** `duration` is in steps (`src/warehouse_rl/disturb.py:109`), so the blockages last 300-1,200 s. The README caveat corrects it.
3. **Two rows have no comparison.**
   - The ungated cell recall for s10c-blind is n/a, because no JSON records it. The lane's read-only count of 6 of 50 was not quoted.
   - The sticky run has no ungated row on the 300 s / 1,245 s schedule.
4. **Not run:** the full unittest gate. The docs-touching suites passed (`test_s11a_explorer`, `test_s8k_overview`, `test_s8j_rebuild`, `test_s8i_page`, `test_s8j_page`, `test_s10h_baselines_page`: Ran 173, OK). No code under the `full` sensitive paths was touched.
5. **Left uncommitted, as found:** `reports/` in the repo, `results/closed_loop*/phaseA/*`, `results/guidance/*` and the gate store/costmap copies.

SCHED_RESULT: OK README (l)+(m) and SCOPE S10F/G/H ticked, kill-criteria persistence answer; commits d9f1526 (JSONs) + 1cbba8e, fcbb8ad, d39e790 (docs) pushed; gate: blind 16->1 truth hits, 1/50 cells; breakdown 19/283 frozen cells (predicted ~0)

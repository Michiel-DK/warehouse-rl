# wr-dev-lit-s15: literature check before S15A / S15B (2026-10-23)

Unattended docs job, opus. Output: `docs/LITERATURE.md` Part 8 (110 lines; commit 4eecd76, then a review-fix commit), the two lane briefs rewritten in place in
`~/code/Michiel-DK/laptop-scheduler/jobs/`. No code, no simulator run.

## Verdicts

1. **Naive stall rule.** No standard name and no standard window found. The one documented vendor form, InOrbit's,
   is a *position* rule, not a velocity flag with a 30 s timer:
   `unableToNavigate` = mission gate + `visitedAreaDiagonal(60)` BELOW 2 sustained 600 s, plus a second documented
   example, "Robot stopped while on a mission" = `visitedAreaSide(180) < 2` ("has not left a 2-meter square for three
   minutes"). Pass 4 had only the first. Baseline name: "stopped on a mission" (InOrbit's wording). S15A runs N0-30
   (= the old 567-run rule), N0-60, N1 (InOrbit form 1 as documented) and N2-W, InOrbit form 2 swept over
   W ∈ {30, 60, 120, 180} (180 documented), because the vendor's numbers are editable examples and a fixed long
   window would decide the comparison before the run.
2. **Duration spread.** FHWA names buffer index, planning time index, p95 travel time and frequency over a threshold
   and discourages SD/CV as public measures; US federal rules define TTTR = p95 / p50 (23 CFR 490.611) and LOTTR =
   p80 / p50 (490.511). OTTO documents a *mean* ("Average Run Time") plus an unquantified hand method. ISO 22400-2's 34
   KPIs (Kikolski 2020 reproduction) have no time-dispersion KPI; Kingman makes variability a cause of waiting; Little's
   law is about means. No AGV/AMR source uses spread as a congestion proxy and none found validates a spread statistic
   against a direct blocking measure. S15B decisive statistics: raw p95 / median (TTTR form) and raw mean (OTTO);
   buffer index, CV and the free-flow-normalised versions are descriptive. Spearman rho per run + Kendall tau-b,
   top-3 overlap with chance k²/n, median over runs, no raw pooling, constant column = undecided run.
3. **Refute lines** written in Part 8 §3 before any run, both sides: S15A commodity = any N2-W, N1 or N0-60 reaches
   2/2 labelled hits with ≤ 12 stuck runs; a "supports" result may only say "not in the documented example" (InOrbit
   customers can write station logic; COMPETITION pass 4 scores it present). S15B commodity = median rho(statistic,
   blocking) ≥ 0.7 with top-3 ≥ 2/3, or the statistic reads truth as well as blocking in ≥ 3 decided runs.
   **No prediction from durations:** both labelled stops (250 s, 127 s) are hit by one `driving`-false run of 133 s
   (`fleet/data/moroop/budget-sb/zone7.json`, cause `unknown`), so label length is not stillness length.

## Review pass (same job)

An advisor review of the first commit found five problems, all fixed in the second commit: (1) a prediction that N1/N2
"cannot hit" the labelled stops, built on label durations rather than stillness (removed); (2) a refute line that the
fixed 660 s N1 would satisfy automatically (now an N2-W sweep, plus the "not in the documented example" wording rule);
(3) an S15B refute line that dropped "spread ranks zones like the blocking number" (restored) and an OR over six
variants (now two decisive statistics); (4) "no source names p95/median" was wrong: it is the federal TTTR (fixed,
now the primary); (5) the task's manufacturing question was unanswered (ISO 22400-2, Kingman, Little added).

## What changed in the briefs

`jobs/wr-lane-s15a-naive-stall-baseline.md` (backup of the draft at the start: /tmp/s15lit/s15a.orig.md, not kept):
- Why: "stopped while on a mission ... the vendor's 60 s window" replaced by the two InOrbit forms as read; the vendor
  has no 60 s timer.
- Rule: "windows 30 s and 60 s; velocity flag or displacement" replaced by N0-30, N0-60 (Detector, `stations=None`;
  N0-30 asserted = 567), N1, N2-W for W ∈ {30, 60, 120, 180} (position rules on a 1 s event-time grid, half-open
  windows, carry-forward on the change-only log, 0.5 m cells so 2 m = 4 cells, sim rows tagged "scale assumed 1 cell
  = 1 m", count of alerts spanning a > 60 s gap).
- "Must be expressible as the existing detector" dropped for N1/N2: they are not (box vs `driving`, rotation in place).
- Output adds, per labelled stop, the stopped-run span, the box-stillness span and each rule's alert latency.
- Test fixture: was a/b/c with naive-30/naive-60; now a-f (adds 200 s, 700 s, 200 s spin-in-place; each drive one
  message jumping ≥ 6 cells so alert times are exact) with expected flags per rule and alert times to the second,
  plus a carry-forward gap test. **Changed expectation:** the old "naive-60 flags b only" is now "N0-60 flags b, d, e".
- Report must place the result against Part 8 §3's refute line, with the "not in the documented example" wording rule.
- Kept: file names, `results/fleet/stall_baseline.json`, smoke, store guard, determinism, queue item `wr-s15a-run`.

`jobs/wr-lane-s15b-duration-spread.md`:
- Why: names OTTO's mean and the TTTR p95 / median.
- Statistics: "CV and p95/median" replaced by two decisive statistics, raw p95 / median (kept from the draft, now
  sourced as TTTR) and raw mean; buffer index, CV and normalised versions (free-flow = Manhattan along the job's
  waypoints × `STEP_S`) descriptive; fewer than 5 jobs → null, counted.
- Agreement: "per run and pooled, Spearman + top-3" replaced by per run Spearman + Kendall tau-b, top-3 with chance,
  median over runs, no raw pooling, constant column = undecided; pairs include each statistic vs truth; the verdict
  (commodity / supports / mixed) is computed in the script from Part 8 §3's thresholds.
- Test: "B's spread is higher under every statistic" replaced by "p95/median, buffer index and CV higher, means equal" (the mean
  is equal by construction), plus a route-length-only zone whose normalised buffer index is 0.
- Kept: file names, `results/fleet/duration_spread.json`, three-zone rho test, smoke, determinism, `wr-s15b-run`.

The briefs are edited in the laptop-scheduler working tree and **not committed there** (this job commits only to
warehouse-rl).

## Query log

Fetched / read (all 2026-10-23):
- https://developer.inorbit.ai/docs — curl, 409,461 bytes, HTML stripped and grepped for `visitedAreaDiagonal`,
  `unableToNavigate`, `sustained`, `0.3m`, `isZoneBlocked`, "Robot stopped while on a mission", "preset nogo". Raw
  text, not a summariser.
- https://docs.formant.io/llms.txt (curl, grep event/trigger/alert/stuck/idle/stop) and
  /docs/getting-started-create-an-event-and-configure-notifications.md (grep threshold/second/duration/stuck).
- https://ops.fhwa.dot.gov/publications/tt_reliability/TTR_Report.htm — curl, grepped.
- https://www.ecfr.gov (renderer API) 23 CFR 490.511 and 490.611: LOTTR and TTTR ratio definitions, grepped.
- https://reference.opcfoundation.org/specs/OPC-40001-1/c-2 and c-3: no dispersion, variation or throughput text.
- Kikolski 2020, https://www.scitepress.org/Papers/2020/91758/91758.pdf (pdftotext): Table 1, 34 ISO 22400 KPIs.
- OpenAlex DOI records: 10.1017/S0305004100036094 (Kingman 1961), 10.1287/opre.9.3.383 (Little 1961).
- `fleet/data/moroop/budget-sb/zone7.json`: shift 7 causes, one `unknown` episode of 133 s.
- https://www.nap.edu/read/22282/chapter/{2,3,6,7} — the page text is image placeholders; the L33 equation is a search
  snippet only (rank S).
- OpenAlex DOI records: 10.13023/ktc.rr.2010.08 (abstract), 10.1145/1852102.1852106.
- scipy kendalltau and spearmanr docs.
- `results/fleet/moroop_label-sb.json` shifts.7.episodes_ge_30s (250 s, 127 s).

WebSearch (standard): FHWA buffer/planning time index; SHRP 2 L03 TTI vs PTI; AGV travel-time variability CV
congestion; Formant stuck alert; ISO 22400-2 KPI list; Kingman VUT; L03 data-poor TTI95 equation; Locus/Geek+/MiR Fleet stuck alert docs (no vendor
doc found → UNTESTED).

OpenAlex `works?search=` (all HTTP 200; top 5 read, none on-topic): "AGV travel time variability congestion
indicator" (243); "automated guided vehicle cycle time variability blocking" (21,022); "mobile robot fleet stuck
detection time threshold" (375); "robot stall detection no progress timeout" (233); "task duration variance
congestion warehouse robots" (422); "travel time reliability index congestion correlation validation" (9,325; road
only); "coefficient of variation cycle time congestion manufacturing indicator" (6,990).

CORE API v3 (flat AND, abstract fields):
| query | status | hits |
|---|---|---|
| AGV variance blocking travel | 200 | 0 |
| AGV variability congestion indicator | 200 (after a 429) | 0 |
| robot stall detection fleet | 200 | 0 |
| robot stuck threshold seconds | 200 (after two 429s) | 0 |
| buffer index congestion correlation reliability | 200 once (then 429) | 1: Chen 2010 KTC |
| cycle time variability blocking proxy | 200 | 2, off-topic |
| title: catch-up conflict AGV (calibration) | 200 | 1: Li et al. 2018 |
| Tarapore / swarm fault detection immune (calibration, OR form) | 200 | 5 incl. Tarapore 2017 |
| AGV congestion Little | 200 | 4 duplicates, Swedish thesis, off-topic |
| 5 grouped-paren and quoted forms | 500 / None, not counted | — |

Two-index status: the stall-rule absence and the AGV spread-proxy absence each have OpenAlex plus CORE with a
calibration hit in their field. "No validation of a spread statistic against blocking" rests on the same queries;
road traffic has more literature than these queries reach (SHRP 2 L03/L33 were not read in full), so Part 8 says
"not found", not "none".

## Limits
- InOrbit's forms are documentation examples, not shipped defaults; S15A tests "what a customer copying the doc gets".
- The 2 m threshold on the simulator is a guess (no metre scale on record); MoRoOp is the clean comparison.
- The thresholds in the refute lines (≤ 12 runs, rho 0.7 / 0.4, top-3 2/3, 3 or 4 of 5 runs) are ours, set before the
  run.
- Hopp & Spearman's VUT text and the Kingman / Little papers were not read; only their records.

SCHED_RESULT: OK Part 8 appended (110 lines) + review fixes, S15A/S15B briefs rewritten in laptop-scheduler (uncommitted there)

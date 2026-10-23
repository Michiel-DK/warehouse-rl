# wr-dev-lit-s15: literature check before S15A / S15B (2026-10-23)

Unattended docs job, opus. Output: `docs/LITERATURE.md` Part 8 (108 lines), the two lane briefs rewritten in place in
`~/code/Michiel-DK/laptop-scheduler/jobs/`. No code, no simulator run.

## Verdicts

1. **Naive stall rule.** No standard name and no standard window found. The one documented vendor form, InOrbit's,
   is a *position* rule, not a velocity flag with a 30 s timer:
   `unableToNavigate` = mission gate + `visitedAreaDiagonal(60)` BELOW 2 sustained 600 s, plus a second documented
   example, "Robot stopped while on a mission" = `visitedAreaSide(180) < 2` ("has not left a 2-meter square for three
   minutes"). Pass 4 had only the first. Baseline name: "stopped on a mission" (InOrbit's wording). S15A runs N0-30
   (= the old 567-run rule), N0-60, N1 (InOrbit form 1), N2 (InOrbit form 2).
2. **Duration spread.** FHWA names buffer index, planning time index, p95 travel time and frequency over a threshold;
   it discourages SD/CV as public measures. OTTO documents a *mean* ("Average Run Time") plus an unquantified hand
   method. No AGV/AMR source uses spread as a congestion proxy, and no source found validates any spread statistic
   against a direct blocking measure. S15B: buffer index (primary), mean (OTTO), CV (secondary), on raw and
   free-flow-normalised durations; Spearman rho per run + Kendall tau-b, top-3 overlap with chance k²/n, median over
   runs, no raw pooling.
3. **Refute lines** written in Part 8 §3 before any run. Prediction from data on disk: the two labelled MoRoOp stops
   ≥ 30 s last 250 s and 127 s (`results/fleet/moroop_label-sb.json`, shifts.7), so N1 cannot hit either and N2 can hit
   the 250 s one at most. A trade-off is expected, not a clean "commodity" result. This is a prediction, not measured.

## What changed in the briefs

`jobs/wr-lane-s15a-naive-stall-baseline.md` (backup of the draft at the start: /tmp/s15lit/s15a.orig.md, not kept):
- Why: "stopped while on a mission ... the vendor's 60 s window" replaced by the two InOrbit forms as read; the vendor
  has no 60 s timer.
- Rule: "windows 30 s and 60 s; velocity flag or displacement" replaced by N0-30, N0-60 (Detector, `stations=None`;
  N0-30 asserted = 567), N1, N2 (position rules on a 1 s event-time grid, carry-forward on the change-only log, 0.5 m
  cells so 2 m = 4 cells, sim rows tagged "scale assumed 1 cell = 1 m", count of alerts spanning a > 60 s gap).
- "Must be expressible as the existing detector" dropped for N1/N2: they are not (box vs `driving`, rotation in place).
- Output adds per-labelled-stop alert latency.
- Test fixture: was a/b/c with naive-30/naive-60; now a-f (adds 200 s, 700 s, 200 s spin-in-place, ≥ 6-cell drives
  between stops) with expected flags per rule, plus a carry-forward gap test. **Changed expectation:** the old
  "naive-60 flags b only" is now "N0-60 flags b, d, e".
- Report must place the result against Part 8 §3's refute line.
- Kept: file names, `results/fleet/stall_baseline.json`, smoke, store guard, determinism, queue item `wr-s15a-run`.

`jobs/wr-lane-s15b-duration-spread.md`:
- Why: names OTTO's mean and FHWA's buffer index.
- Statistics: "CV and p95/median" replaced by buffer index, mean, CV, raw and normalised (free-flow = Manhattan along
  the job's waypoints × `STEP_S`); fewer than 5 jobs → null, counted. p95/median dropped: no source names it.
- Agreement: "per run and pooled, Spearman + top-3" replaced by per run Spearman + Kendall tau-b, top-3 with chance,
  median over runs, no raw pooling; the pairs now include each statistic vs truth (the refute line rests on it).
- Test: "B's spread is higher under every statistic" replaced by "buffer index and CV higher, means equal" (the mean
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
- https://www.nap.edu/read/22282/chapter/{2,3,6,7} — the page text is image placeholders; the L33 equation is a search
  snippet only (rank S).
- OpenAlex DOI records: 10.13023/ktc.rr.2010.08 (abstract), 10.1145/1852102.1852106.
- scipy kendalltau and spearmanr docs.
- `results/fleet/moroop_label-sb.json` shifts.7.episodes_ge_30s (250 s, 127 s).

WebSearch (standard): FHWA buffer/planning time index; SHRP 2 L03 TTI vs PTI; AGV travel-time variability CV
congestion; Formant stuck alert; L03 data-poor TTI95 equation; Locus/Geek+/MiR Fleet stuck alert docs (no vendor
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
- The thresholds in the refute lines (2×, 5×, 4 of 5 runs) are ours, set before the run.

SCHED_RESULT: OK Part 8 appended (108 lines), S15A/S15B briefs rewritten in laptop-scheduler (uncommitted there)

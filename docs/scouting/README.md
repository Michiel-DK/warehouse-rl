# Scouting synthesis: does the fleet stall analyser transfer? (2026-10-19)

Six domain scouts ran on 19 Oct 2026 (briefs in `laptop-scheduler/jobs/wr-scout-*.md`, search logs in
`reports/wr-scout-*.md`). Five ran on the haiku model in 4 to 7 minutes each, the farm-robots one on
opus in 18 minutes with a review pass; the depth difference is visible and is stated per row below. This file adds no
new web research. Every number and name here is quoted from the six docs, which carry the URLs and `verified@` dates.

## 1. One table

SCOUT_SCORE as each doc states it (0 to 3; competition 3 = open field). "Forecast grading at rank A" = vendors whose own
documentation shows a graded location forecast (capability 4 in `docs/COMPETITION.md`).

| domain | data | sim | comp. | fit | best public data | best open simulator | vendors read at rank A | forecast grading yes (A) | single blocker (the doc's words) | scout depth |
|---|---|---|---|---|---|---|---|---|---|---|
| [farm robots](farm-robots.md) | 1 | 1 | 2 | 2 | TUM tractor load cycles: 2.8 GB, 5 tractors, RTK + hitch in-work flag, CC BY 4.0, no fault channel | none for farms; TA-RWARE or RWARE re-skin | DeLaval, Burro (2 of 8; Deere, Lely, Carbon behind logins) | 0 | "a fleet log with position plus a fault or stop cause, obtainable only through an OEM API with a machine owner's grant" | opus, 213 lines, 2 passes |
| [greenhouse logistics](greenhouse-logistics.md) | 1 | 2 | 2 | 2 | GREENBOT: pose and sensors, no state or fault | Lay2Graph-MAPD (MIT) or RWARE as a rail event loop, no fault injection | 0 of 6 | 0 | "a grower or a vendor ... would have to share a trolley log with positions and stop causes, and none is public" | haiku, 147 lines |
| [AGV and tug fleets](agv-tugs.md) | 0 | 1 | 2 | 2 | DEDICAT6G lab KPIs: robot positions in a 3x2 m area, no fault field | SimPy yard, hand-written faults | 0 of 7 (all cells from search snippets) | 0 | "one real telemetry log from a port or hospital operator in VDA 5050 or TOS export form" | haiku, 74 lines, 8 fetches total, Kaggle and data.gov not searched |
| [mining and construction](mining-construction.md) | 0 | 2 | 1 | 2 | none with faults (AutoMine is lidar and camera) | OpenMines: MIT, gymnasium API, shovel downtime and road repairs keyed by segment | 0 of 7 (Trimble and Trackunit help pages only) | 0 | "no public location-resolved fault log exists in this domain ... every field claim waits on an operator-side log or an AEMP API subscription" | haiku, 115 lines |
| [factory stoppages](factory-stoppages.md) | 2 | 2 | 2 | 2 | PIADE: 429,394 rows, 133 stop-reason types, machine IDs, CC BY 4.0, no station position | SimPy (MIT, 4.1.2 of 2026-05-24), breakdowns written by hand | 0 of 6 (MachineMetrics one article as snippet) | 0 | "no public log has station position and stop time on the same rows" | haiku, 149 lines |
| [solar PV](solar-pv.md) | 1 | 1 | 2 | 2 | DuraMAT emulated tracker faults (one tracker; record returned 404) and Réunion rooftop shading labels per inverter | pvlib / pvops: physics, no fault injection by location | Raptor Maps (1 of 6) | 0 | "the emulated tracker set is the only open stall-labelled log, and its licence, columns and file sizes are unread" | haiku, 74 lines |

Across the six docs, 41 vendors were listed and none shows forecast grading, graded lessons, time-to-detect or a decision
ledger at rank A. That is the same shape as `docs/COMPETITION.md`: absence is established only where a doc tree was
readable (DeLaval, Burro, Raptor Maps, parts of Trimble, Trackunit and MachineMetrics) and UNTESTED everywhere else.

## 2. Contradiction sweep

Same subject described differently across the six docs:

- **SimPy's home.** agv-tugs.md cites `https://github.com/jcaplan/simpy` "(URL from search; official host not checked)";
  factory-stoppages.md cites `https://simpy.readthedocs.io` with source at `https://gitlab.com/team-simpy/simpy/` and PyPI
  4.1.2 (2026-05-24); mining-construction.md cites PyPI 4.1.2 (2026-05-24). The agv-tugs URL is a fork, the other two agree.
- **TUM tractor dataset hours.** farm-robots.md itself records the disagreement: "paper says 862 h recorded / 354 h
  fieldwork on 143 fields, Zenodo text says 1245 h (sources disagree)". No other doc cites it.
- **RWARE and Flatland rows.** greenhouse-logistics.md marks its rows "carried from farm-robots.md"; the licence, push
  date and "malfunctions per agent, rate-based" statements match. No conflict.
- **VDA 5050 repository.** greenhouse-logistics.md and agv-tugs.md both give `https://github.com/VDA5050/VDA5050`, MIT,
  spec and schemas only, no logs. agv-tugs.md adds "version 3.0.0". No conflict.
- **Kaggle and the government portals.** Five docs report Kaggle as JavaScript-only or searched through web search only,
  and data.gov / data.europa.eu as not reached or partial. Consistent, and it means "none found" never covers those four
  repositories in any domain.
- **Semantic Scholar.** farm-robots.md reports HTTP 429 on four queries; the others say no Semantic Scholar or Google
  Scholar query ran. Consistent: no academic-anchor section rests on a scholarly index.

No two docs assert opposite facts about the same vendor or dataset.

## 3. Ranking by "honest demo within two weeks"

Ordered by what can be measured without a client log, with the doc's own first measurement.

1. **Factory stoppages.** The only domain with a real public log usable as is: PIADE gives timestamps, machine IDs and
   133 stop reasons under CC BY 4.0, so a per-machine stop-reason ranking graded on the next day against chance and
   persistence is a real-data test of our grading method. It is a station ranking, not a map, and the routing loop has no
   analogue.
2. **Mining and construction.** OpenMines (MIT, gymnasium API, segment-keyed downtime) is the closest thing to a second
   TA-RWARE: planted stalls on three fixed segments, graded on shift t+1 against persistence. Synthetic only; no public
   telemetry exists and the AEMP route is a paid subscription.
3. **Farm robots.** The TUM tractor set gives real in-field stops by RTK position with a work-state flag, so top-K stop
   locations of earlier passes can be graded against later passes. Stops are not faults, headlands must be excluded
   first, and passes per field are not reported, so the measurement may collapse to one pass.
4. **Solar PV.** Synthetic only, and the emitter is a full rewrite on top of pvlib (layout, soiling, tracker stalls). The one
   readable vendor tree (Raptor Maps) already has a string-level map and log upload at rank A, so the market is not open
   on the two capabilities we could demo first.
5. **Greenhouse logistics.** Synthetic re-skin only, and the geometry breaks a premise: a single rail has no detour, so a
   hidden fault freezes every trolley behind it and the planner-blind test loses its meaning. All six vendors UNTESTED.
6. **AGV and tug fleets.** Technically the nearest to our product (VDA 5050, hospital and port maps), but no public log of
   any kind and the thinnest scout (8 fetches, vendor cells from snippets). Its doc should be redone at opus depth before
   any decision rests on it.

## 4. Direction test

The six verdicts all point the same way, and it is the unflattering way: every doc says no honest real-data demo within
two weeks, names data as the single blocker, and scores competition 1 or 2 with every absence UNTESTED. None claims an
open field. The claims that rest on rank B or worse, and would be the first to flatter us if wrong: the mining "yes"
cells for heatmap (Caterpillar dealer brochure, B) and routing (Komatsu marketing, B); the whole agv-tugs vendor table
(snippets); the solar DuraMAT and Réunion rows (record not opened, Zenodo not opened); the factory Bosch row (page did
not render); the greenhouse Lay2Graph "Python" claim (metadata only). The 11 "yes" cells across the six docs are all
heatmap, avoid-zones or log upload, never forecast grading, which matches the warehouse result and is not a surprise.

## 5. What this means

The blocker is the same in all six domains as in the warehouse: one real log with position, state and a fault or stop
cause. Choosing a domain by its label does not change that; whoever provides a log first picks the domain. Two things
can be done now without one: the PIADE grading demo (real data, about a day of work, no location) and the OpenMines
synthetic demo (three to four days, a second simulator for the same pipeline). Neither should start before the
persistence-baseline result on our own data (S10D) is in, because if the decayed map does not beat persistence in the
warehouse, porting it is the wrong next step.

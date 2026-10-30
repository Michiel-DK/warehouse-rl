# Scouting: mining haul-truck and construction-machinery fleets

Scope: can the fleet stuck analyser (Sprints 5-10) be demoed on open-pit haul trucks or construction machinery with public
data or an open simulator? Searched 2026-10-19 with WebSearch and WebFetch only. Search log and per-source notes are in
`reports/wr-scout-mining-construction.md`. Rank key (`outward-claim-discipline` (private harness rule set)): A = primary page read
this session, B = vendor marketing, C = press, trade article or search snippet only (not read), D = tutorial, F = memory.
Every claim carries its URL and `verified@2026-10-19`.

## 1. Fit

The four requirements, read against the Sprint 5 README (telemetry with position and state, stalls with causes, a
location axis, a next window to grade against): the first, third and fourth hold in principle; the second is the gap,
because no public log exists. Position and fault telemetry exist in the AEMP 2.0 / ISO/TS 15143-3 schema, which
defines the vendor-to-customer feed (https://www.aem.org/standards/iso15143/3, A, verified@2026-10-19), and a
search-snippet source says the feed carries location and fault codes at 30-minute, hourly, daily or state-change cadence
(https://www.constructionbusinessowner.com/technology/new-telematics-standard-streamlines-equipment-data-management, C,
verified@2026-10-19, not read in full). Recurring places are plausible: haul time varies with road topography and
intersections on a fixed route (Chapman 2012, https://queensu.scholaris.ca/items/6bd81266-5e15-416a-b632-88589025bc54,
A, verified@2026-10-19). A stall here is a truck stationary or below a speed threshold away from a planned stop; queues
at a shovel, crusher or dump are planned waiting and must be excluded, or they swamp every signal. A cell is a road
segment or intersection id, or a fixed grid (for example 50 m) over the haul network. A window is a shift (8-12 h) or
an hour, with the forecast made on window t and graded on t+1. The planner-blind case maps onto our floor case: dispatch
already reroutes around a known blockage, so what it cannot see is an unreported road defect (soft spot, spillage, a
stuck body), which is the case our floor-invisible setting models. The throughput metric is loads (or tonnes) per
productive truck-hour, taken from the dispatch cycle count and not from any reward; the pick-rate equivalent is
loads x 3600 / (productive seconds x trucks). Requirement 4 (open log) does not hold, so the fit is structural only.

## 2. Data

| name | owner | URL | size | fields | position? | state / fault? | licence | verified@ | rank |
|---|---|---|---|---|---|---|---|---|---|
| ISO/TS 15143-3 (AEMP 2.0) | AEM publishes the page; JCMA maintains the standard | https://www.aem.org/standards/iso15143/3 | spec; no sample data read | communication schema, machine status (scope quoted from page) | UNVERIFIED (not in the page scope text read) | UNVERIFIED for the spec; fault codes per C snippet | not stated on page | 2026-10-19 | A (existence, scope) |
| Volvo CE AEMP 2.0 API | Volvo Construction Equipment | https://developer.volvoce.com/vce/cs/api-products | live API, not a file | "REST API for retrieving machine data", XML, ISO 15143-3:2020 (page) | UNVERIFIED | UNVERIFIED | sign-in; subscription per C snippet | 2026-10-19 | A (listing), C (access) |
| Mine Haul Truck Rear Dump Profiles | Aaron Young, University of Utah | https://doi.org/10.5281/zenodo.5789951 | 419 MB DWG | 3D CAD of dump faces from photogrammetry; no time or location fields | no | no | CC BY 4.0 | 2026-10-19 | A (record read) |
| AutoMine (JFR 2025; CVPR 2022 precursor) | AutoMine team | DOI 10.1002/rob.22469 (repository record); CVPR 2022: https://openaccess.thecvf.com/content/CVPR2022/html/Li_AutoMine_An_Unmanned_Mine_Dataset_CVPR_2022_paper.html | 18+ h, 18K frames (CVPR 2022 abstract, snippet) | lidar, camera, odometry, 5 platforms, 8 sites | UNVERIFIED (odometry, not stated GNSS) | no fault log | not checked | 2026-10-19 | C (repository record and snippet; download not located) |
| Haul road mapping from GPS (Seiler, APCOM 2021) | Univ. of Sydney | https://arxiv.org/abs/2206.13936 | not stated | truck GPS traces (abstract) | yes, as input | no | not stated | 2026-10-19 | A (abstract); no data release |
| Haul time variability thesis (Chapman, 2012) | Queen's University | https://queensu.scholaris.ca/items/6bd81266-5e15-416a-b632-88589025bc54 | 18.49 MB PDF | haul times, location-specific (Goldstrike) | location in text only | no | thesis | 2026-10-19 | A (page read); data not separately published |
| Open-pit fleet data in arXiv 2506.04296 | HxGN MineOperate fleet (commercial) | https://arxiv.org/pdf/2506.04296 | n/a | GPS and onboard telemetry | yes | yes | not public | 2026-10-19 | C (snippet) |
| 4D mmWave radar, lidar, camera, open-pit mine | IEEE DataPort | https://ieee-dataport.org/documents/dataset-4d-mmwave-radar-point-clouds-open-pit-mine | n/a | radar, lidar, camera | n/a | no | UNVERIFIED | 2026-10-19 | C (snippet) |

**No open log in the AEMP / ISO 15143-3 format was found.** Repositories searched: Kaggle (search page rendered with no
results; JavaScript-only, so not conclusive, UNTESTED); Zenodo (JSON API, first 17 hits for "haul truck" OR "open pit",
none telemetry; total hit count not read, so partial); IEEE DataPort (search for "haul truck" returned 0 matches; the
search box rendered blank, so low confidence); data.gov (20 of 586,937 results for "haul truck", none mining or
construction telematics; page 1 only); data.europa.eu (no results rendered, UNTESTED); Hugging Face datasets (0
results for "haul truck"); GitHub repository search (0 results for "haul truck" telematics); standards body (AEM page
read; JCMA "Supporting Files" and the ISO catalogue page not read). The premise that dispatch systems publish delay
reasons was not confirmed: Komatsu's DISPATCH product page names no reason codes or delay logs (B,
https://www.komatsu.com/en-br/technology/smart-mining/modular, verified@2026-10-19). A Tarkwa study uses delay codes
from dispatch data (snippet, C), so codes exist in practice but no public copy was found.

## 3. Simulators

| name | URL | licence | maintained? | faults injected by location? | CPU-only? | python API? | verified@ |
|---|---|---|---|---|---|---|---|
| OpenMines (truck dispatch, arXiv 2404.00622) | https://github.com/370025263/openmines | MIT (repo page label, A) | 56 stars; "updated Jul 22" (year not shown); no release tag | partial: shovel downtime and road repairs keyed by segment start and end points (README, A); no documented injection API | not stated | yes: gymnasium env, `gym.make('mine/Mine-v1-dense', ...)`, reset, step (README, A) | 2026-10-19 |
| SUMO (Eclipse, traffic) | https://eclipse.dev/sumo/ | EPL-2.0 or GPL-2.0 (A) | docs copyright 2001-2026 DLR (A); release version not verified | UNTESTED: edge or lane closure via TraCI not confirmed (docs read only for traffic lights, https://sumo.dlr.de/docs/Simulation/Traffic_Lights.html) | UNTESTED (native binary) | yes: `traci` on PyPI, EPL-2.0 (C, search snippet) | 2026-10-19 |
| SimPy (discrete-event library) | https://pypi.org/project/simpy/ | MIT (A) | 4.1.2, released 2026-05-24 (A) | not a mine model; faults would be coded by hand (UNTESTED) | yes (pure Python) | yes (library) | 2026-10-19 |
| AnyPit (Beihang, real-time truck dispatch) | https://research.buaa.edu.cn/en/publications/anypit-a-lightweight-and-extensible-simulation-platform-for-real-/ | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | 2026-10-19 (snippet, C) |

Adaptation: the emitter would have to write simulated truck positions and states into the same schema as the Sprint 5
fleet emitter, and fault injection would be a wrapper that closes a segment or slows it, not a patch to the simulator,
so the work is roughly the S5A emitter plus a truck model, moderate for OpenMines and more for SUMO.

## 4. Who sells this already

Rows are the nine capabilities from `docs/COMPETITION.md`. Seven vendors (Modular Mining's DISPATCH is listed on Komatsu's
Modular page, so it sits under Komatsu). No cell is `not found in docs (A)`, because no vendor's doc tree was read in full; every absence is
UNTESTED. Each vendor's column was read from the pages listed in the search log, at most ten fetches each, and several
fetches failed with 403, timeouts or JavaScript-only pages.

| capability | Komatsu (DISPATCH) | Caterpillar (MineStar / VisionLink / RAC) | Trimble (VisionLink, WorksOS) | Trackunit | Volvo CE (CareTrack, AEMP 2.0 API) | Wenco | Hexagon Mining (HxGN, CAS Insights) |
|---|---|---|---|---|---|---|---|
| doc tree read | product and case-study pages (B); portal behind sign-in | RAC page via search only (A, snippet); fleet page timed out | one help topic (A) | two help articles and a community page (A, D) | AEMP API product page (A); sign-in | press and exhibitor profile only (C, B) | press only (C) |
| 1 heatmap | UNTESTED | yes (B, search snippet only): dealer brochure, GNSS reports "show where ... alerts occur" (https://www.finning.com/content/dam/finning/en_ca/migratedassets/documents/Health_Broch_FINALweb.pdf) | UNTESTED | UNTESTED | UNTESTED | UNTESTED (press: "live maps", C) | UNTESTED (CAS: "pinpoint recurring risk locations", C) |
| 2 recurring-location trend | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED (C, as row 1) |
| 3 forecast of stall location | UNTESTED (Replenish "analyzes shift target forecasts", not places; B) | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED |
| 4 forecast grading | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED |
| 5 graded lessons | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED |
| 6 time-to-detect | UNTESTED | UNTESTED | UNTESTED (help topic: "near real-time", A; no latency figure) | UNTESTED | UNTESTED | UNTESTED | UNTESTED |
| 7 decision ledger | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED |
| 8 avoid-zones / cost map to routing | yes (B): Roadways "updating the road network with real-time data to improve routing" (https://www.komatsu.com/en-br/technology/smart-mining/modular) | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED (C: "geofenced slow zones" as a suggested control, not routing) |
| 9 log upload for a client's fleet | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED (AEMP API exports the owner's data; upload not stated) | UNTESTED | UNTESTED |

Direction test: the only "yes" cells are marketing (B) or press (C), and they all point toward presence, the flattering
direction for the vendor. None is `yes (A)`. The row 1 and row 8 yes cells are the ones to re-verify first if this
domain is pursued. Circular differentiation: no capability in this table was copied from a vendor's feature list.

## 5. Academic anchor

None found that does fault, stall or breakdown hotspot analysis for haul trucks or construction machinery. Queries and
results are in the report. The three closest, none on this fleet type:

1. Chapman, "A Field Study on Haul Time Variability in Open Pit Mines", MSc thesis, Queen's University, 2012.
   https://queensu.scholaris.ca/items/6bd81266-5e15-416a-b632-88589025bc54 (A, verified@2026-10-19). Location-linked
   travel-time variability (topography, intersections), not faults. Useful as the delay-by-place precedent.
2. Nguyen and Hegarty-Cremer, Winter Simulation Conference 2021 (queues at load, dump and crusher locations).
   https://informs-sim.org/wsc21papers/060.pdf (C, snippet only; the PDF had no readable text under WebFetch, so the
   title and method are UNVERIFIED).
3. Seiler, "Haul Road Mapping from GPS Traces", APCOM 2021; arXiv 2206.13936, https://arxiv.org/abs/2206.13936
   (A, abstract). Road network inferred from haul-truck GPS. A location method, not a fault analysis.

## 6. Verdict

With public data the honest answer is no: no open haul-truck or construction telematics log in the AEMP format was
found, and the ISO and Volvo routes need a paid API subscription. With an open simulator the answer is yes for a
simulator-only demo: OpenMines (MIT, gym API) or SUMO (EPL-2.0, TraCI) can run a shift with planted road faults. That
demo would be synthetic and would prove the analyser on planted truth, not that the domain has the problem. The first
measurement would be on OpenMines: plant recurring stalls on three fixed segments that dispatch does not know about,
run the stall detector and the decayed hotspot map over shift t, and grade on shift t+1 against the planted truth and
a persistence baseline, after checking that the sim's dispatch really does reroute around known blockages. The single
blocker is the data: no public location-resolved fault log exists in this domain that was found, so every field claim
waits on an operator-side log or an AEMP API subscription.

SCOUT_SCORE: data=0 (no open log in AEMP or ISO 15143-3 format; the API route needs a subscription); sim=2 (MIT and EPL simulators exist, but no documented location-fault injection in either); competition=1 (location heatmaps and routing from road data are already sold, rank B and C only, every absence UNTESTED); fit=2 (structure matches the location axis and shift window, but the planner-blind case and the stall signal are unverified in this domain)

# wr-dev-lit-part5: query log for LITERATURE.md Part 5 (run 2026-10-21)

Job `wr-dev-lit-part5`, unattended, opus. The brief stamps claims `verified@2026-10-22`; every fetch ran on
2026-10-21 (local clock `Wed Oct 21 15:47 CEST 2026`), so the doc uses `verified@2026-10-21`, as Part 2b did.
Three research subagents (threshold, cause rule, scholarly rerun); the main session re-fetched every number and quote
that entered LITERATURE.md (list in "Main-session re-verification"). Scratch files were in /tmp (not kept).

## Main-session re-verification (all 2026-10-21)

- VDA 5050 main (`## Version 3.0.0`, line 7) and release/2.1.0, raw GitHub, curl: L1034 "at least every 30 seconds";
  2.1.0 L936 "at the latest every 30s"; 2.1.0 L1137 errorLevel "Enum {'WARNING', 'FATAL'}"; main L139, L282, L353,
  L870, L1121-1126, L1877 (seven actionStatus values incl. RETRIABLE), L1899, L1931 (fieldViolation).
- MiR Fleet reference guide 1.2 (distributor mirror https://www.hmi-mbs.fr/wp-content/uploads/2020/07/notice-mir_fleet_reference_guide_12_en.pdf),
  pdftotext: "Path timeout ... if the path is blocked. Default is 5 seconds." and "Path timeout sets the amount of time
  the robot will wait for the path to clear before generating a new one"; "Retries (Blocked Path)".
- ROS move_base `MoveBase.cfg` (noetic-devel): planner_patience / controller_patience 5.0 s; oscillation_timeout 0.0.
- Nav2 `simple_progress_checker.cpp` (main) L54-56: required_movement_radius 0.5, movement_time_allowance 10.0.
- Open-RMF rmf_ros2 `EasyFullControl.hpp` L595 `max_delay = rmf_traffic::time::from_seconds(10.0)`;
  `RobotUpdateHandle.hpp` L133 "how high the delay ... can become before it gets interrupted and replanned".
- Stern et al. 2019 arXiv 1906.08291 PDF: vertex / edge / following / cycle / swapping conflict definitions, all
  "according to these plans" / "planned to".
- Andersson & Veldhuis 2025, Chalmers MSc thesis (https://odr.chalmers.se/bitstreams/7d9faa35-7c28-4653-b856-5cc62f4e6653/download),
  §4.1.1-4.1.3: blocking object with blockee "planned path"; "a blocking is an instance of a traffic rule being
  activated"; "AGV blocking ... blocker(s)"; blocking graphs as causal chains (DAG).
- Kita et al. 2023 arXiv 2302.01489 PDF: edge delay "x ∼ Gamma(a(e), b(e))"; parameters "are unknown ... estimate
  the parameters from m observations of delay".
- OpenAlex records: Kondaveeti et al. 2011 (doi 10.1109/med.2011.5983183) title/year; Azzalini et al. 2020
  (doi 10.5555/3398761.3398779). arXiv record: DeepFleet 2508.08574 title.

## Threshold pass (§1): queries and walls

WebSearch: "VDI 4451 Blatt Fahrerlose Transportsysteme Titel"; "VDI 2510 Blatt 2 Blatt 3 fahrerlose Transportsysteme
dinmedia"; "MiR fleet "blocked" robot notification seconds path blocked timeout"; "Open-RMF fleet adapter "blocked" OR
"deadlock" timeout seconds rmf_traffic negotiation"; "OTTO Motors fleet manager robot "blocked" state
help.ottomotors.com"; "openTCS user guide vehicle "unavailable" OR "blocked" timeout seconds"; "Seegrid Supervisor
robot blocked obstacle alert seconds manual"; "MiR user guide "obstacle" "seconds" robot "blocked" mission error
'Planner' timeout pdf"; "Locus Robotics LocusServer robot blocked stuck alert documentation"; "SEMI E10 unscheduled
downtime definition minimum duration "idle time" "standby" equipment states"; "ISO 22400-2 "unplanned downtime"
definition ADOT "actual unit down time" KPI"; "Ma Kumar Koenig 2017 "Multi-Agent Path Finding with Delay
Probabilities" delay definition"; "Hönig ... "Persistent and Robust Execution of MAPF Schedules" action dependency
graph arXiv"; "Atzmon Stern Felner "Robust Multi-Agent Path Finding and Executing" k-robust delay definition arXiv";
"ISO 3691-4:2023 driverless industrial trucks abstract"; "AMR AGV "stationary for more than" OR "not moved for"
seconds stuck detection warehouse robot"; ""VDI 2510" Blatt 1 OR "VDI 2510:2005" title vdi.de"; "Geek+ OR Hikrobot OR
"Fetch Robotics" fleet "robot stuck" alarm timeout seconds configuration"; "site:docs.ottomotors.com blocked OR stuck
OR obstacle robot state"; "openTCS documentation vehicle "integration level" "UNAVAILABLE" "ERROR" state definition";
"SEMI E10 "SEMI E58" ARAMS interrupt short stop downtime threshold OR "minimum duration""; "AGV deadlock detection
"waiting time exceeds" threshold seconds paper multi-AGV timeout-based". GitHub code search open-rmf/rmf_ros2
"deadlock", "blocked timeout". Walls: iso.org 403 + Cloudflare; wiki.ros.org bot wall (source file read instead);
help.ottomotors.com login; act.usc.edu DNS failure; VDI/DIN pages: titles from search snippets only.
Results (subagent, URL + quote each): VDI 2510 Blatt 1 "Infrastruktur und periphere Einrichtungen" (2009-12), Blatt 2
"Sicherheit von FTS", Blatt 3 "Schnittstellen zu Infrastruktur und peripheren Einrichtungen" (2017-09), Blatt 4
"Energieversorgung und Ladetechnik", 2025-07 draft; VDI 4451 series "Kompatibilität von FTS", Blatt 3 drive motors
(1998), 4 open control structure, 6 sensors, 7 "Leitsteuerung für FTS" (2005-10); all snippet, no stop duration.
SEMI E10 unscheduled downtime definition (secondary, chemicool.com) and E58 abstract: no minimum duration. ISO 22400-2
via a vendor blog (fabrico.io): AUDT "unplanned stops", no minimum. Bear Robotics API RobotStatus "stuck: unable to
make navigation progress", no time; SoftBank Whiz "path is blocked" notification attempt-based. Seegrid, Locus,
Geek+, openTCS: no doc tree found (snippet searches only). MAPF delays (Ma 2017, Atzmon 2018, Hönig 2019): one
timestep in which the agent does not advance; counted in steps.

## Cause-rule pass (§2): queries and walls

WebSearch: "SEMI E10 equipment states blocked starved definition "E58" reasons"; "PackML Suspended state "starved"
"blocked" upstream downstream definition"; "MiR robot error code "path is blocked" OR "blocked by obstacle" help MiR
fleet"; "Stern 2019 "Multi-Agent Pathfinding: Definitions, Variants, and Benchmarks" vertex conflict"; "Open-RMF
rmf_fleet_adapter blockade negotiation "deadlock" traffic conflict obstacle event"; "openTCS vehicle state "waiting
for" resources allocation blocked vehicle documentation user guide"; "Hönig 2019 "action dependency graph" "Type 2"
edge"; "AGV log analysis waiting time attributed to blocking vehicle "wait-for graph""; "OTTO Motors fleet manager
robot state "blocked" OR "obstructed""; "Seegrid fleet central "blocked" path obstruction alert AMR event"; "Highway
Capacity Manual definition "queue spillback""; "openTCS documentation vehicle "waiting for resources""; "MiR error
code list "Planner" "Failed to reach goal""; "Locus Robotics LocusOne robot status "blocked""; "SUMO traci
getLeader"; "multi-robot "blocked by" attribution requires planned path"; "Network Rail Delay Attribution Principles
reactionary"; ""blocking graph" AGV congestion Andersson Veldhuis". GitHub code search "Status::Blocked", "waiting
for" in open-rmf/rmf_ros2. Walls: MiR error-code list PDF is image-only; opentcs.org user guide certificate error then
404; SEMI E10/E58/E116 and HCM paywalled; OTTO/Seegrid/Locus doc trees not found.
Results: Open-RMF task_state.json status enum includes "blocked", "error"; WaitForTraffic.cpp "Waiting for [robot:"
built from schedule `dependencies`; RobotUpdateHandle `blocked(text)` warning tier; openTCS Vehicle.java states
UNKNOWN / UNAVAILABLE / ERROR / IDLE / EXECUTING / CHARGING, no "blocked"; PackML OPC 30050 6.3.8 blocked/starved;
SEMI E116 abstract "reasons ... why equipment is blocked"; UK rail reactionary delay to "the identified Responsible
Train" (snippet); SUMO getLeader needs the route (snippet). No source found that calls a robot "blocked by" another
from adjacency alone.

## Scholarly rerun (§3)

Semantic Scholar Graph API `/graph/v1/paper/search`, one request in flight, Python script with backoff 5/15/45/90 s
(switched to 5/15 s from idx 16 because each rare 200 reset the ladder; those rows are labelled `search-resume` in the
raw log): **64 queries, 179 tries, 170 × HTTP 429, 9 × 200**; 9 queries ended on 200 (idx 1, 12, 16, 17, 20, 28, 41,
50, 51), 55 never answered. Bulk endpoint `/paper/search/bulk`: 1 try, 429. Web UI
`https://www.semanticscholar.org/search?q=AGV%20deadlock%20detection%20logs` via WebFetch: HTTP 403, no body.
OpenAlex `/works?search=`: 64 queries + 19 `filter=title_and_abstract.search` extras, 83 × 200 (8 extras empty).
OpenAlex repeats of earlier parts: idx 43-45 (Part 3 Q1) and idx 62 (Part 3 road closure). Part 1 used OpenAlex only
for DOI lookups, so no Part 1 query is a repeat. Google Scholar: not tried (blocks scripted access).

### Per-query status (generated from the raw S2 and OpenAlex logs)

| idx | claim | label | S2 tries | S2 final | OpenAlex hits | query |
|---|---|---|---|---|---|---|
| 0 | 1a | orig | 5 | 429 | 2681 | isolation forest anomaly detection mobile robot |
| 1 | 1a | orig | 4 | 200 | 1518 | hidden Markov model fault detection mobile robot execution monitoring |
| 2 | 1a | orig | 5 | 429 | 3700 | LSTM autoencoder anomaly detection mobile robot |
| 3 | 1a | orig | 5 | 429 | 554 | anomaly detection AGV operational data industrial logistics machine learning |
| 4 | 1a | extra | 5 | 429 | 209 | anomaly detection fleet telemetry autonomous mobile robots warehouse |
| 5 | 1a | extra | 1 | 429 | 124 | unsupervised anomaly detection AGV log data |
| 6 | 1b | orig | 1 | 429 | 207 | stuck robot detection warehouse fleet |
| 7 | 1b | orig | 1 | 429 | 4860 | blocked robot detection multi-robot traffic jam detection |
| 8 | 1b | orig | 1 | 429 | 245 | wait-for graph deadlock detection AGV |
| 9 | 1b | extra | 1 | 429 | 1259 | root cause analysis multi-robot failure blocked by another robot telemetry |
| 10 | 1b | extra | 1 | 429 | 3860 | fault propagation diagnosis multi-robot system logs |
| 11 | 1c | orig | 1 | 429 | 86 | exponential decay kernel density crime hotspot baseline |
| 12 | 1c | extra | 1 | 200 | 598 | exponentially weighted moving average hotspot forecast baseline predictive accuracy index |
| 13 | 1d | orig | 5 | 429 | 19864 | persistence baseline hotspot |
| 14 | 1d | orig | 5 | 429 | 3339 | hot spot persistence expected by chance micro-place |
| 15 | 1d | orig | 2 | 429 | 612 | recapture rate index hotspot stability next period |
| 16 | 1d | extra | 1 | 200 | 88 | hot spot stability chance expectation permutation crime places |
| 17 | 1e | orig | 3 | 200 | 44904 | activity monitoring operating characteristic false alarm time to detection |
| 18 | 1e | extra | 3 | 429 | 8630 | time to clear incident duration detection metric surveillance |
| 19 | 1f | orig | 3 | 429 | 73375 | multi-agent path finding delay probabilities |
| 20 | 1f | orig | 3 | 200 | 115031 | robust multi-agent path finding uncertainty |
| 21 | 1f | extra | 3 | 429 | 9271 | multi-agent path finding unknown delay probability per edge learning |
| 22 | 2a | orig | 3 | 429 | 1095 | runtime deadlock detection multi-robot systems |
| 23 | 2a | orig | 3 | 429 | 0 | rmf_traffic deadlock fleet manager |
| 24 | 2a | extra | 3 | 429 | 78 | deadlock detection AGV logs observed positions |
| 25 | 2a | extra | 3 | 429 | 650 | detecting deadlocks mobile robots from trajectory data without planner |
| 26 | 2a | extra | 3 | 429 | 37 | gridlock detection multi-robot warehouse monitoring |
| 27 | 2b | orig | 3 | 429 | 283 | packet loss coverage map AGV |
| 28 | 2b | orig | 2 | 200 | 13 | packet loss dead zones heartbeat telemetry robots |
| 29 | 2b | extra | 3 | 429 | 207 | WiFi coverage hole detection from mobile robot connectivity logs |
| 30 | 2b | extra | 3 | 429 | 103 | passive radio map crowdsourced connectivity gaps industrial robots |
| 31 | 2b | extra | 3 | 429 | 292 | coverage hole inference message loss telemetry |
| 32 | 2c | orig | 3 | 429 | 227 | AGV dataset fleet trajectories warehouse |
| 33 | 2c | orig | 3 | 429 | 4054 | autonomous mobile robot telemetry dataset |
| 34 | 2c | extra | 3 | 429 | 4470 | multi-robot warehouse real operation log dataset |
| 35 | 2c | extra | 3 | 429 | 57 | AGV fleet operational data open dataset intralogistics |
| 36 | 2b1 | orig | 3 | 429 | 21 | hospital delivery robot TUG log analysis time waiting stuck |
| 37 | 2b1 | orig | 3 | 429 | 49 | AMR operational log utilization idle time navigation failures field deployment |
| 38 | 2b1 | orig | 3 | 429 | 276 | single mobile robot long-term deployment log analysis time blocked stuck waiting percentage |
| 39 | 2b1 | extra | 3 | 429 | 18490 | autonomous mobile robot utilization time in state real deployment logs |
| 40 | 2b1 | extra | 3 | 429 | 2270 | AGV availability utilization field data analysis production logistics |
| 41 | Q1 | orig | 1 | 200 | 5 | multi-robot fleet infer blocked edge unknown obstacle robot delays lifelong MAPF |
| 42 | Q1 | orig | 3 | 429 | 5 | warehouse AGV fleet logs detect blocked aisle obstruction robot position data |
| 43 | Q1 | orig-OA-repeat | 3 | 429 | 232 | anomaly detection AGV trajectories warehouse |
| 44 | Q1 | orig-OA-repeat | 3 | 429 | 1206 | lifelong multi-agent path finding unknown obstacles detection |
| 45 | Q1 | orig-OA-repeat | 3 | 429 | 37016 | detecting decreases counts spatial surveillance absence |
| 46 | Q1 | extra | 3 | 429 | 516 | obstacle detection from multi-robot traversal times map update false alarm |
| 47 | Q1 | extra | 3 | 429 | 655 | blocked path inference from robot fleet traces detection delay |
| 48 | Q2 | orig | 3 | 429 | 11 | warehouse AGV congestion prediction hotspot forecast baseline |
| 49 | Q2 | orig | 3 | 429 | 1 | AMR fleet congestion hotspot prediction persistence baseline |
| 50 | Q2 | orig | 1 | 200 | 2864 | warehouse robot congestion prediction |
| 51 | Q2 | extra | 1 | 200 | 1068 | multi-robot congestion forecasting real logs historical average baseline |
| 52 | Q3 | orig | 3 | 429 | 59 | congestion-aware AGV routing dynamic edge weights small fleet throughput warehouse simulation |
| 53 | Q3 | extra | 3 | 429 | 1491 | multi-agent path finding hidden slow cells delays routing disturbance |
| 54 | Q3 | extra | 3 | 429 | 197 | AGV routing unknown traversal cost learning warehouse |
| 55 | 4a | orig | 3 | 429 | 3 | station dwell time timeout outlier threshold median robot |
| 56 | 4a | orig | 3 | 429 | 1 | VDA 5050 action timeout |
| 57 | 4a | extra | 3 | 429 | 1169 | dwell time anomaly threshold multiple of median service time |
| 58 | 4a | extra | 3 | 429 | 19 | AGV station waiting time timeout fleet management |
| 59 | 4b | orig | 3 | 429 | 286 | detect blocked edge warehouse robot fleet absence of traffic |
| 60 | 4b | orig | 3 | 429 | 222 | negative information absence of observations multi-robot blocked aisle |
| 61 | 4b | orig | 3 | 429 | 16786 | road closure detection absence of location data |
| 62 | 4b | extra | 3 | 429 | 3290 | road closure detection GPS trajectories |
| 63 | 4b | extra | 3 | 429 | 401 | absence of traffic anomaly detection zero count Poisson road segment |
| bulk | 2a | extra | 1 | 429 | - | AGV deadlock detection |

OpenAlex `filter=title_and_abstract.search` extras:

| idx | claim | hits | query |
|---|---|---|---|
| 100 | 1e | 1869 | end of outbreak detection |
| 101 | 1e | 20 | alarm return to normal detection delay |
| 102 | 1d | 7 | spatial point pattern test hot spot stability |
| 103 | 1d | 0 | crime hot spot stability expected by chance |
| 104 | 1a | 1 | isolation forest AGV |
| 105 | 1a | 2 | autoencoder fleet robots anomaly |
| 106 | 2a | 8 | deadlock detection robot trajectories |
| 107 | 2a | 2 | livelock detection robots |
| 108 | 2a | 0 | deadlock detection AGV monitoring |
| 109 | 2b | 10 | radio map AGV |
| 110 | 2b | 2 | connectivity map mobile robots packet loss |
| 111 | 2b1 | 32 | AGV utilization field data |
| 112 | 2b1 | 2 | long-term autonomy deployment statistics mobile robot |
| 113 | 4a | 0 | AGV dwell time threshold |
| 114 | 4a | 0 | AMR docking timeout |
| 115 | 4b | 0 | blocked aisle detection warehouse robots |
| 116 | Q1 | 0 | obstacle inference robot traversal delays fleet |
| 117 | Q3 | 0 | multi-agent path finding unknown travel times learning edge |
| 118 | 1f | 1 | multi-agent path finding stochastic travel times unknown distribution |

### Screening outcome per claim (subagent screen, decisive hits re-read in the main session)

- 1f overturned: Kita et al. 2023 (arXiv 2302.01489, full text read; OpenAlex source "Adaptive Agents and Multi-Agents
  Systems", doi 10.65109/uvds9134). 3 citing works in OpenAlex, not read.
- Q3 weakened: Kita et al. 2023 (same).
- 1e weakened: Kondaveeti et al. (doi 10.1109/med.2011.5983183, abstract read: "'Return To Normal' (RTN) information");
  2013 Alberta thesis doi 10.7939/r38k6g (abstract, subagent only, not used in the doc).
- 1a weakened: Azzalini et al. 2020 (doi 10.5555/3398761.3398779, abstract read, single robots); a 2025 CNN-LSTM
  autoencoder on one robot (subagent only, not used).
- 2c / 2b1 / Q2: DeepFleet (arXiv 2508.08574, record title checked; content per subagent: real Amazon fleet data, no
  release, no persistence row). 10-AMR hospital study (Sci. Rep. 2026, subagent grep of full text: no time-in-state
  share). Not re-read in the main session beyond the arXiv title.
- All other claims: no hit that changes the verdict; 1c, 1d, 4a result sets mostly off-topic or near-empty, so those
  "kept" verdicts are uninformative rather than confirmed.

## Contradiction sweep (§4): method

Grepped LITERATURE.md Parts 1-4, COMPETITION.md and docs/scouting/README.md for repeated subjects: VDA 5050 version and
errorLevel, MoRoOp counts (1,382 / 140,386 / 137,427 / 207 / 72.99), the 1,107 / 1,113 / 3,245 s stop, Nav2, SEMI E10
standby, ISO 22400 ADET, Bonetti 2026, Standridge, OTTO / MiR / Locus / Geek+ doc surfaces, search coverage lines.
Fixes made in place with a dated note (2026-10-21): LITERATURE Part 1 §5, Part 2 §1, Part 2 §2, Part 2 §5 table row,
Part 3 Verdict 3, Part 4 §2; COMPETITION MiR "Surfaces read". The 1,773 s figure of commit bf4b175 is not in these
three files (README / SCOPE only), so it was out of scope.

## Review round (main session, 2026-10-21)

Additional re-fetches after the review: VDA 2.1.0 L872 `waitForTrigger` "Master control is responsible to handle the
timeout"; VDA 3.0.0 L1894 `errorReferences` "(e.g., `nodeId`, `edgeId`, `orderId`, `actionId` ..."; Open-RMF
`rmf_fleet_adapter/src/rmf_fleet_adapter/events/WaitForTraffic.cpp:199` "Waiting for [robot:" (the subagent's
`phases/` path is 404; found via the GitHub tree API); openTCS `Vehicle.java` L1363 `enum State` UNKNOWN, UNAVAILABLE,
ERROR, IDLE, EXECUTING, CHARGING; Ma et al. 2017 PDF "executes no action and remains delayed in its current"; Atzmon
et al. 2018 PDF "not perform the move action defined for it in πi and instead stayed at time t"; Hönig et al. 2019 PDF
"so-called Type 2 edges", "delayed up to k timesteps"; SEMI E116 store page "why equipment is blocked from performing
its task". OTTO public tech docs (doc tree from the exceptions page navigation,
https://docs.ottomotors.com/en/30495-31050-exceptions.html, Recoveries section): "Recover your AMR: Blocked",
https://docs.ottomotors.com/en/127044-119570-recover-your-amr--blocked.html: "The AMR is blocked from proceeding on its
planned path", physical or logical ("An incorrect container state") blockage, "stops all AMR movement until the
blockage is cleared"; no seconds on the page. The MiR ref guide 2.2 on the MiR support portal (subagent) was not
re-fetched, so the doc cites only the 2020 distributor mirror and COMPETITION says only that it exists.
Changes: gurren-page line now "none may front it yet" (Semantic Scholar gate of Parts 1-3 unmet: 9 of 64 answered,
none for 2 §1 deadlock-from-logs; the 429 body asks for an API key); Part 4 Verdict 2 and Part 1 Q4/Q5 annotated;
neighbour labels marked as our wording.
Consistent across docs (no action): Nav2 0.5 m / 10 s (Parts 1, 2), SEMI E10 standby (Parts 2, 4), ISO 22400 ADET
(Parts 2, 4), Bonetti 2026 (Parts 1, 2), the 1,107 s MoRoOp stop and 3,245 s episode (Part 4, README (s)),
COMPETITION's 14 vendors / 12 UNTESTED, scouting §2 VDA 5050 and Semantic Scholar rows, VDA "3.0" vs "3.0.0" (same).

# Scouting: hospital, airport and port AGV and tug fleets (2026-10-19)

## 1. Fit

Of the four requirements, the location axis holds on paper: VDA 5050 state messages carry a position and an error field, and hospital, baggage and port fleets run fixed routes over a mapped site. Faults recurring at the same places is not shown for this domain; the only place-specific evidence is a 2012 student report of a hospital TUG stuck in a corridor (rank D, [WPI](https://digital.wpi.edu/downloads/dz010r68p?locale=en)), so it is untested. Position-and-state logs exist in the standard but no public log was found, so that requirement fails in practice. The next-window grade needs such a log, so it fails with it. A **stall** here is a vehicle that holds a task or a route for longer than a threshold without completing a move, with a cause such as a blocking vehicle or person, a lane conflict, an elevator wait, charging, or a sensor fault. A **cell** is a node, bay or corridor segment taken from the fleet's own map, not a GPS grid. A **window** is a shift (port, about 8 h) or a day (hospital). The planner-blind case is a blockage the planner's cost map does not model, such as a load spilled in a lane, an unmapped obstacle, or a floor-friction problem; the fleet then routes into the same cell again and stall events cluster there. The throughput metric is completed moves per hour of fleet time (container moves per tractor-hour, or deliveries per hour in a hospital), counted from task-completion events, which is the equivalent of our pick-rate `deliveries * 3600 / (5 * steps)`.

## 2. Data

Verified 2026-10-19. "Verified" means the page or search snippet named in the URL was read this session; WebSearch snippets are marked as such. Full search log is in `reports/wr-scout-agv-tugs.md`.

| name | owner | URL | size | fields | position? | state/fault? | licence | verified@ | rank |
|---|---|---|---|---|---|---|---|---|---|
| VDA 5050 specification repo | VDA 5050 working group | https://github.com/VDA5050/VDA5050 | repo, no data | spec document and JSON schemas; `assets` folder not read | defined by spec | defined by spec (error fields) | MIT (repo page) | 2026-10-19 | A (spec); no logs visible |
| Hybrid few-shot PID tuning, AGV runs | Kinza Nazir, Jeju National University | https://zenodo.org/records/17152352 | 21.3 MB | not described; folders "all", "augmented" (GPT synthetic), "llm_data" | not stated | not stated | CC-BY 4.0 | 2026-10-19 | A for licence; D for fit (AGV control, not fleet telemetry) |
| DEDICAT6G Smart Warehousing robot KPIs | WINGS ICT Solutions | https://zenodo.org/records/10793054 | 885.9 kB, three CSVs | no column list on page; "positions of the robots ... in a 3x2 m area" | yes (per page description) | "operational" = running tasks; no fault field stated | CC-BY 4.0 | 2026-10-19 | A for listing; C for fit (lab scale) |
| AI4Mobile iV2V / iV2I+ wireless datasets | Fraunhofer HHI, Ericsson, TU Dresden, Bosch et al. | https://ieee-dataport.org/open-access/ai4mobile-industrial-wireless-datasets-iv2v-and-iv2i (DOI 10.21227/04ta-v128) | not read | about 10 h sidelink among 3 AGVs; radio metrics, QoS, positioning | yes (positioning, per abstract) | no stall or fault | open access; terms not read | 2026-10-19 | B- (abstract via search) |
| Synthetic predictive localization monitoring | TUHH | https://tore.tuhh.de/bitstreams/647a6e4b-36d3-45f3-bd24-29c2b83ce49f/download | not read | simulated localisation failures, labelled from position or orientation error | simulated | labelled localisation failure | not read | 2026-10-19 | B- (synthetic, omnidirectional robot in Isaac Sim, search snippet) |
| AGV status example documentation | Item.com | https://bi.item.com/documents/Example/ARobot.html | not read | AGV status, charging, downtime, odometer (search snippet) | not stated | status and downtime | not read | 2026-10-19 | D (vendor example, not a download) |
| Forgis robot dataset | Lior-ACQU (Hugging Face) | https://huggingface.co/datasets/Lior-ACQU/Forgis | not read | joint-state, fault, episode (viewer) | no; robot-arm data | fault column | not read | 2026-10-19 | D for fit (not a mobile base) |

**Telemetry standards.** VDA 5050 is the open standard for AGV-to-fleet control (version 3.0.0 on the spec repo, rank A). Port terminals use the TOS interfaces instead: TEAMS controls AGV fleets at HHLA Altenwerder and ECT Euromax and is coupled to Navis SPARCS and N4 ([Port Technology](https://www.porttechnology.org/news/teams_the_brain_of_the_automated_terminal/), rank C, search snippet). Those interfaces are vendor-specific and not published as open logs.

**Open VDA 5050 log: none found.** Search results pointed at the spec repo, a fleet-manager code project and MQTT sample tooling, none of them a log.

**Port or hospital log or TOS replay: none found.** No open log of tractor, straddle carrier, tug or hospital AGV telemetry turned up in any searched repository. Public port data found (EU ports register, AIS vessel tracks, ONS port-area road counts) is not terminal equipment telemetry.

**Repositories searched.** Kaggle: WebSearch only, the Kaggle site was not searched. Zenodo: WebSearch, plus two record pages read. IEEE DataPort: WebSearch. data.gov: not searched. data.europa.eu: WebSearch; the portal itself was not reached. Hugging Face: WebSearch. GitHub: WebSearch plus the spec repo page. The VDA standard body: a VDA press-release search hit, the site not fetched. Coverage is therefore partial, and "none found" is a statement about these searches, not a full catalogue.

## 3. Simulators

Verified 2026-10-19. A simulator here means one that could replay a yard or hospital with AGVs and inject a fault at a location.

| name | URL | licence | maintained? | fault by location? | CPU-only? | python API? | verified@ |
|---|---|---|---|---|---|---|---|
| ConFlowGen | https://github.com/1kastner/conflowgen | MIT (repo page) | UNTESTED (last commit not shown; 403 commits) | no: generates container flows, does not simulate vehicles | UNTESTED | Python application, pip install (search snippet) | 2026-10-19 |
| SimPy (DES library) | https://github.com/jcaplan/simpy (URL from search; official host not checked) | MIT (search snippet) | UNTESTED | not a simulator; faults would be hand-coded | yes (pure Python) | yes | 2026-10-19 |
| simcraft port_terminal example | https://simcraft.readthedocs.io/en/latest/_sources/examples/port_terminal.md.txt | UNTESTED | UNTESTED | UNTESTED (berths, cranes, AGVs, yard blocks, per snippet) | UNTESTED | UNTESTED | 2026-10-19 |
| Open-RMF fleet adapters (rmf_fleet_adapter_python) | https://index.ros.org/p/rmf_fleet_adapter_python/ | Apache-2.0 (ROS index) | UNTESTED | UNTESTED; Gazebo-based simulation, no fault-by-location found | UNTESTED | yes (Python bindings) | 2026-10-19 |
| NVIDIA Mission Simulator container (isaac_ros) | https://catalog.ngc.nvidia.com/orgs/nvidia/isaac/containers/mission-simulator/isaac_ros | Apache-2.0 (NGC listing) | UNTESTED | UNTESTED | UNTESTED (GPU container likely) | UNTESTED | 2026-10-19 |
| vda-5050-lib.js | https://github.com/coatyio/vda-5050-lib.js | UNTESTED | UNTESTED | no; a message library, not a simulator | yes (Node) | JavaScript | 2026-10-19 |

Adaptation: a SimPy yard or hospital map would need an emitter that writes VDA 5050 state JSON (position, task, error) with a hidden injected blockage, which is our `emit` step plus a map loader, roughly the same work as the TA-RWARE wrapper.

## 4. Who sells this already

Every cell is UNTESTED, because none of the seven vendors had a documentation tree that was read. The vendor list is the ones the search surfaced in this domain. Hospital and port products sit behind demos or partner portals; the cells below rest on search snippets and marketing, so none reaches rank A. Nothing here is an absence claim, so no "not found in docs" cell appears.

| vendor (product) | heatmap | trend | forecast | grading | lessons | time-to-detect | ledger | zones to routing | log upload | evidence (rank) |
|---|---|---|---|---|---|---|---|---|---|---|
| Aethon, ST Engineering (Fleet Management Suite) | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | third-party profile: "mission tracking, uptime optimization" (C); patent US9223313B2 titled monitoring and diagnostic tool; docs not found |
| Diligent Robotics (Moxi) | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | job posting: "planned maintenance program" (intent, C); "multiple terabytes of performance data" (vendor claim, B) |
| Terberg Connect (terminal tractors) | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | product page: "current location" and route history "snail trail" (B); fault codes via Connect GO (B); no published fault list |
| Kalmar Insight (terminal tractors, AGV SmartFleet) | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | 2025 article: reads fault codes and notifies engineers (B); "predictive analytics solutions" (B, location not stated) |
| AMPcontrol (electric port tractors) | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | marketing: fault alerts into TOS (B); no analytics or location pages read |
| Identec Solutions (Terminal Tracker) | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | 2026 article: "real-time location analysis", "route habits" (B); "recurring error codes" as a question, not a feature (B) |
| SPIE E.RAMP (Robot Analysis and Monitoring Portal) | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | digital report: "visual hotspot generation" for intralogistics AMRs (C); not hospital or port |

Near misses a demo account could turn into presence: Kalmar's predictive analytics, Identec's location analysis and Terberg's route history, none stating a stall location or a hit rate. The walled trees (Aethon, Diligent, Terberg, Kalmar) need demo access before any pitch says "not on the market".

## 5. Academic anchor

None found that does fault or stall hotspot analysis for this fleet type. Queries: "hospital AGV tug fleet stall fault hotspot analysis", "AGV failure diagnosis location hotspot mining port", "AGV deadlock hospital corridor", "automated container terminal AGV congestion deadlock spatial hotspot", "hospital delivery robot AGV breakdown root cause location", "baggage tug airport fleet fault location". The closest papers, none of which qualifies:

1. Bertoli, Battilani, Fantuzzi, "Multi-AGV fault diagnosis", IFAC PapersOnLine (SAFEPROCESS 2024), 2024, DOI 10.1016/j.ifacol.2024.07.225 (not fetched; the redirect was not followed, abstract via search snippet, rank B-). Location-aware single-AGV fault diagnosis in a factory, not port or hospital.
2. Kim, Jeon, Ryu, "Deadlock prevention for automated guided vehicles in automated container terminals", in *Container Terminals and Cargo Systems*, Springer, 2007 (search snippet, rank C). Deadlock avoidance by grid-block reservation, not fault location.
3. Lehmann, Grunow, Günther, "Deadlock handling for crane-AGV systems", Springer, 2007 (search snippet, rank C). Deadlock detection and resolution, not hotspots.
4. Li, Pogromsky, Adriaansen, Udding, "Zone-control deadlock avoidance", *International Journal of Advanced Robotic Systems*, 2016 (search snippet, rank C). Container-terminal case, no stall statistics.
5. Greenville Memorial Hospital AGV simulation, arXiv:2006.10031, 2020, [https://arxiv.org/abs/2006.10031](https://arxiv.org/abs/2006.10031) (search snippet, rank C). Discrete-event model of surgical-cart AGVs with congestion, no faults.

## 6. Verdict

We cannot demo this domain honestly in two weeks on public data, because no searched repository holds position-plus-fault AGV or tug logs; the closest, DEDICAT6G, has positions and no fault field. An open simulator gives a route only if we build the fault-by-location layer ourselves, so any demo would be synthetic with our own truth, the same shape as the TA-RWARE work. The first measurement would be a SimPy yard emitting VDA 5050 state JSON with a hidden blocked cell, run through the stall analyser and graded against a persistence baseline on the next shift, labelled synthetic. The single blocker is one real telemetry log from a port or hospital operator in VDA 5050 or TOS export form, which no public source provides. The competition check is almost entirely UNTESTED and the academic check is partial, so neither supports a market-gap claim yet.

SCOUT_SCORE: data=0 (no public position-plus-fault AGV log found); sim=1 (SimPy and ConFlowGen are open but neither injects faults by location); competition=2 (fault telemetry is sold, but stall-location grading was not seen and most cells are UNTESTED); fit=2 (the location axis holds on paper, recurring faults at places and next-window grading are untested).

# wr-dev-lit-index-rerun: second scholarly index for the absence claims (run 2026-10-21)

Job `wr-dev-lit-index-rerun`, unattended, opus. The brief stamps `verified@2026-10-22`; every request ran on
2026-10-21 (local clock `Wed Oct 21 18:4x-20:0x CEST 2026`, UTC 16:4x-18:0x), so LITERATURE.md Part 7 uses
`verified@2026-10-21`, as Parts 5 and 6 did. Raw JSON responses were kept in /tmp/wrlit_out (not committed).
Scripts in /tmp/wrlit_scripts (Python stdlib, urllib).

## Services tried (a page that did not render = not run, never "no hits")

| service | endpoint | result | status |
|---|---|---|---|
| dblp | `dblp.org/search/publ/api?format=json` (curl, browser and default UA), `dblp.org/search?q=` (WebFetch), `dblp.dagstuhl.de` API | HTTP 202 Anubis "Making sure you're not a bot!" page; WebFetch "Access Denied: error code 9e4edb5b6b850c41" | **not run** |
| dblp | `dblp.uni-trier.de` API; `sparql.dblp.org` | connection failed / timed out after 30 s | **not run** |
| Semantic Scholar | Graph API `/paper/search` (1 try on the 2a query), `/paper/search/match` | HTTP 429 "apply for a key" | **not run** |
| Semantic Scholar | web page `semanticscholar.org/search?q=` via WebFetch and curl | HTTP 403 (WebFetch), HTTP 202 empty body (curl) | **not run** |
| Lens.org | `lens.org/lens/search/scholar/list?q=` (curl) | HTTP 200, 582 kB JS application shell; the query string appears only in locale links and the search box; no result titles in the HTML | **not run** (did not render) |
| CORE | web page `core.ac.uk/search?q=` | HTTP 403 Cloudflare "Just a moment..." | **not run** |
| CORE | API v3 `api.core.ac.uk/v3/search/works/` without a key | HTTP 200; limit 10 requests per window, `x-ratelimit-retry-after` honoured (window grew to ~10 min after ~40 requests); 2 × HTTP 500 on `arxivId:` and `title:(...)` syntax | **ran** |
| CORE | docs page `api.core.ac.uk/docs/v3` (WebFetch) | HTTP 403 | syntax found by probing |
| OpenAlex | reruns of the four Part 6 queries that hit 429 | HTTP 429 "Insufficient budget ... resets at midnight UTC" (retry-after 25,059 s) | **not run** |
| Crossref | `api.crossref.org/works/{doi}` for 3 DOIs | 200 | metadata checks |
| arXiv | `export.arxiv.org/api/query?id_list=2609.10400` | 200 | metadata check |

So the one second index that ran is **CORE**, an open-access aggregator with its own harvest of repositories and
journals (record ids, data providers such as "Kent Academic Repository" in its responses), separate from OpenAlex's
catalogue though the two overlap in content. Who runs it was not checked this session.

## How CORE behaves (probed, so the results below can be read)

- A plain multi-word query (`q=stuck robot detection warehouse fleet`) is OR over full text: 3.4 M hits, top results
  ordered by record id, not relevance. The first pass (57 plain queries, 30 answered, 18:44-18:55 CEST) was
  **discarded as uninformative**, neither hits nor "no hits".
- Field queries `title:"..."` / `abstract:"..."` work; `title:(word)` returns HTTP 500.
- Quoted phrases match loosely for counting (title phrase of a known paper gives 17-78 M "hits") but rank the exact
  record first, so known-item lookups work by the first result, not by the count.
- **OR groups are not reliable:** `mobile robot AND stuck AND detection` = 14 hits (repeated, 14 again);
  adding `AGV OR multi-robot` to the first group gave 3; adding `traffic jam` as an OR to the second gave 0. A
  correct OR cannot shrink a set. So the OR-grouped run (37 queries) is screened for **presence** (any relevant hit is
  real) but its zeros are not counted.
- **Flat AND queries** (each term `title:"t" OR abstract:"t"`, terms ANDed, no OR between terms) were repeatable and
  are the coverage run: 63 queries, all HTTP 200.
- Hyphens are harmless (`multi-robot` and `multi robot` both 176 hits with `deadlock`).

## Calibration: does CORE hold the field of each claim?

16 known items that OpenAlex or Parts 1-6 already found: **10 found**, 6 missed.
Found: Kita 2023 (title), Azzalini 2020 (title), Tarapore 2017 (title), Bonetti 2026 (DOI; also came up unprompted
in flat query 2a.1), Zarour 2023 (title; also unprompted in 2b.4), Daamen 2009 (title; also unprompted in P6-6.4),
Mohler 2015 (title), Neill 2005 (DOI), Gerling 2016 (DOI), Chainey 2008 (DOI).
Missed: DeepFleet 2025 (title; arXiv id → HTTP 500, not run), MoRoOp 2026 (title), Lee 2026 Digital Health (DOI),
O'Brien 2025 JSAN (title and DOI), Fitzpatrick 2020 (title; arXiv id → HTTP 500), Kondaveeti 2011 (abstract
phrase only, weak query). Pattern: CORE misses 2025-26 preprints and recent journal items; older and repository
items are there.

**Rule applied in Part 7:** a claim has two indexes when CORE's flat queries for it ran **and** CORE retrieved at least
one known item of that claim's field. Otherwise the claim stays at one index.

## Screening: hits that change or touch a verdict (abstract read from the CORE record unless noted)

- **P6-6 weakened:** Nyström 2008, "A methodology for measuring the quality of deviation reporting: applied to railway
  delay attribution", Int. J. Quality & Reliability Mgmt, https://doi.org/10.1108/02656710810890863 (Crossref checked;
  A- abstract): vignette survey "to measure the consistency of railway delay attribution"; railways "can use [it] to
  estimate the accuracy of their delay attribution systems". Human attributors, no figure in the abstract.
- **Contradiction, Part 1 table row:** Part 1 lists Bonetti, Proia, Guidetti, Sabattini 2026 as "Deadlock detection and
  resolution for AGV fleets", doi 10.1177/02783649261470035, arXiv 2609.10400. Crossref and the arXiv API both give
  that DOI / id the title **"A traffic management system for large and heterogeneous vehicles in narrow industrial
  environments"** (IJRR, issued 2026-08-07; arXiv 2026-09-09), same four authors. CORE's abstract: L-MAPF on NURBS
  roadmaps with rolling-horizon CBS. Part 1's content claim (graph cycle detection, nested acyclic deadlocks) was not
  re-read here.
- Near hits, verdict kept: Catal, Leroux, De Boom, Verbelen, Dhoedt 2020, "Anomaly Detection for Autonomous Guided
  Vehicles using Bayesian Surprise", IROS, https://doi.org/10.1109/iros45743.2020.9341386 (Crossref checked; A-): one
  AGV's RGBD camera detects obstructions in a warehouse (P6-1, Q1: on-board, single vehicle, not a fleet stream).
  "Lane Closure Detection on Highway Using Connected Vehicle Data" 2025, https://doi.org/10.1155/atr/9579025 (A-):
  road only, speed and lateral position, not absence (4b). "Synapse Open Dataset" 2024 (Zenodo 10.5281/zenodo.11459539):
  synthetic camera images (2c). "Raw Simulation Logs and Intralogistics Performance Metrics for AMR-Assisted Internal
  Transport" 2026 (CORE 388247400, title only): simulated (2c). Deadlock in AGV controllers, all on the controller or
  simulation model (2a): "Deadlock detection and resolution in automated material handling system" 2013 (resource
  allocation graph in simulation), WSC 2020 doi 10.1109/wsc48552.2020.9383883 (simulation), "Evaluating Open-RMF" NTU
  2026 (source-code analysis), an Italian MSc thesis 2024 on pick-to-pallet AMRs (CORE 304537379). Robust MAPF for obstacles, Sensors 2026
  doi 10.3390/s26134139 (planning, A-). Lifelong MAPF with delay probabilities, AAAI 2025 doi 10.1609/aaai.v39i22.34506
  (A-, planning with execution delays, already in the Kita family).
- Everything else: off-topic or empty. 1c, 1d, 4a and 4b result sets were off-topic on CORE as on OpenAlex.

## OpenAlex coverage of the Part 6 absence rows (from wr-dev-lit-sota.md, not rerun)

Row 1: 2 queries ran. Row 4: 1 ran. Row 6: 2 of 3 ran. Row 7: 1 of 3 ran (the RLF / MDT string). Rows 5 and 7 map
to Part 5 claims Q1 and 2b, which OpenAlex covered with 7-8 queries each.

### Flat AND queries (the coverage run; title-or-abstract per term)

| id | claim | terms (each `title:"t" OR abstract:"t"`, ANDed) | HTTP | hits | first titles |
|---|---|---|---|---|---|
| 1b.1 | 1b | stuck AND robot AND telemetry | 200 | 0 |  |
| 1b.2 | 1b | blocked by AND robot AND logs | 200 | 0 |  |
| 1b.3 | 1b | blocking AND AGV AND root cause | 200 | 0 |  |
| 1b.4 | 1b | wait for graph AND AGV | 200 | 1 | Planning and Control of Multiple Mobile Robots for Intralogi |
| 1b.5 | 1b | traffic jam AND robots AND detection | 200 | 1 | Algoritmos de coordinación descentralizada autónoma en equip |
| 1c.1 | 1c | hotspot AND exponential decay | 200 | 19 | EXPONENTIAL DECAY QUEUE THRESHOLDS FOR OPTIMAL BUFFER SHARIN; Enhancing OLLA via Exponential Decay for Efficient Link Adap; Research on multi-physical field coupling modeling and multi |
| 1c.2 | 1c | hot spot AND exponentially weighted | 200 | 1 | Clinically Ready Simulation Package for Monitoring Gamma Hot |
| 1c.3 | 1c | crime AND exponential smoothing AND hot spot | 200 | 0 |  |
| 1c.4 | 1c | predictive accuracy index AND baseline | 200 | 860 | Personalized baseline and residual TMTV influence treatment ; Baseline Doppler parameters are useful predictors of chronic; Baseline Fourier-Domain Optical Coherence Tomography Structu |
| 1d.1 | 1d | hot spot AND stability AND chance | 200 | 6 | Fullerol-facilitated transport of copper ions in water-satur; The engineer's pothole repair guide; Port of Tacoma, Pier 4 Reconfiguration - Phase 2 |
| 1d.2 | 1d | hotspot AND persistence AND chance | 200 | 7 | Habitat restoration will help some functional plant types pe; Spatial and Temporal Dynamics of Lekking Behavior and Female; Spatial and Temporal Dynamics of Lekking Behavior and Female |
| 1d.3 | 1d | hot spot AND stability AND permutation | 200 | 7 | Stability of patches of higher population density within the; Stability of patches of higher population density within the; Stability of patches of higher population density within the |
| 1d.4 | 1d | crime AND recapture rate index | 200 | 6 | Exploring Violent and Property Crime Geographically; The spatial-temporal prediction of various crime types in Ho; A Discussion of Current Crime Forecasting Indices and an Imp |
| 2a.1 | 2a | deadlock AND AGV AND detection | 200 | 9 | Traffic Management of Multi-AGV Systems by Improved Dynamic ; Deadlock resolutions in flexible manufacturing systems with ; Deadlock resolutions in flexible manufacturing systems with  |
| 2a.2 | 2a | deadlock AND mobile robots AND logs | 200 | 0 |  |
| 2a.3 | 2a | deadlock AND robot AND trajectory data | 200 | 1 | Cooperative Navigation for Teams of Mobile Robots |
| 2a.4 | 2a | gridlock AND robots | 200 | 0 |  |
| 2a.5 | 2a | deadlock AND warehouse AND detection | 200 | 3 | Automated pick to pallet systems with congestion: impact of ; Comparison of Deadlock Handling Strategies for Different War; Evaluating Open-RMF: mechanism analysis and traffic-graph de |
| 2a.6 | 2a | deadlock AND multi robot AND monitoring | 200 | 2 | Collision avoidance for persistent monitoring in multi-robot; Controllo e coordinamento di un sistema multi-robot: colmare |
| 2b.1 | 2b | packet loss AND AGV | 200 | 12 | Transmission Scheduling With Order Constraints in WIA-FA-Bas; Transmission Scheduling With Order Constraints in WIA-FA-Bas; Formation control of multiple robots under packet loss |
| 2b.2 | 2b | packet loss AND mobile robot AND map | 200 | 5 | Generation of Critical Information and Sharing Mechanism for; Development of stable telecontrol and teleoperation of the A; Development of stable telecontrol and teleoperation of the A |
| 2b.3 | 2b | coverage hole AND robot | 200 | 41 | A Coverage Hole Healing Strategy with Awareness of Data Deli; Unmanned Ground Vehicle navigation and coverage hole patchin; Unknown hostile environment-oriented autonomous WSN deployme |
| 2b.4 | 2b | coverage hole AND AGV | 200 | 1 | Coverage Hole Elimination System in Industrial Environment |
| 2b.5 | 2b | radio map AND AGV | 200 | 0 |  |
| 2b.6 | 2b | message loss AND telemetry AND map | 200 | 1 | Developing a Fire Monitoring System Based on MQTT, ESP-NOW,  |
| 2b.7 | 2b | coverage hole AND minimization of drive tests | 200 | 0 |  |
| 2c.1 | 2c | dataset AND AGV AND warehouse | 200 | 7 | A Multi-Model Optimization Framework for Sustainable AGV-Ass; Lightweight Semantic Segmentation for AGV Navigation: An Enh; Advances in AGV perception for people and object detection i |
| 2c.2 | 2c | dataset AND multi robot AND warehouse | 200 | 18 | Multi-Task Learning for Industrial Mobile Robot Perception U; Synapse Open Dataset: A dataset for warehouse robots; Probabilistic Object-level Change Detection for Mapping Semi |
| 2c.3 | 2c | dataset AND autonomous mobile robot AND logs | 200 | 2 | Raw Simulation Logs and Intralogistics Performance Metrics f; Configuration-Aware Bayesian Shelf Inference for Mobile RFID |
| 2c.4 | 2c | dataset AND AGV AND fleet | 200 | 3 | Data for integrated production and internal logistics optimi; Optimization of job shop scheduling with material handling b; Raw Simulation Logs and Intralogistics Performance Metrics f |
| 2b1.1 | 2b1 | hospital AND delivery robot AND logs | 200 | 4 | Civil Liability for Surgical Medical Robots Under Jordan's M; Design and Implementation of an Autonomous Mobile Manipulato; Design and Implementation of an Autonomous Mobile Manipulato |
| 2b1.2 | 2b1 | TUG AND robot AND hospital | 200 | 4 | Care + a robot = good care?; Care + a robot = good care?; Effect of overground gait training with ‘Mobility Assisted R |
| 2b1.3 | 2b1 | mobile robot AND long-term deployment AND statistics | 200 | 0 |  |
| 2b1.4 | 2b1 | AGV AND utilization AND field data | 200 | 1 | Vihivaunujen käytön optimointi : Vihivaunujen käyttöasteen p |
| 2b1.5 | 2b1 | autonomous mobile robot AND utilization AND deployment | 200 | 15 | Optimizing Book Stocktaking Process: Integration of Mobile R; Development and Deployment of Robonaut 2 to the Internationa; FiMa-Reader: A Cost-Effective Fiducial Marker Reader System  |
| Q1.1 | Q1 | blocked AND AGV AND false alarm | 200 | 0 |  |
| Q1.2 | Q1 | obstacle AND multi robot AND detection delay | 200 | 20 | RETRACTED: Obstacle avoidance using a path correction method; RETRACTED: Obstacle avoidance design for a humanoid intellig; RETRACTED: Fuzzy Lyapunov Stability Analysis and NN Modeling |
| Q1.3 | Q1 | lifelong AND multi agent path finding AND unknown obstacles | 200 | 0 |  |
| Q1.4 | Q1 | travel time AND AGV AND anomaly | 200 | 0 |  |
| Q1.5 | Q1 | blocked aisle AND warehouse | 200 | 1 | Digging Deep: Dynamic Programming for Optimal Routing With D |
| Q2.1 | Q2 | congestion AND AGV AND prediction | 200 | 3 | A Bi-Level Programming Approach for Coordinated Task Sequenc; AMR 운영 방식 의사결정을 위한 시스템 성능 예측 모델 제안; AMR 운영 방식 의사결정을 위한 시스템 성능 예측 모델 제안 |
| Q2.2 | Q2 | congestion AND warehouse robots AND forecast | 200 | 0 |  |
| Q2.3 | Q2 | congestion AND multi robot AND prediction AND baseline | 200 | 0 |  |
| Q2.4 | Q2 | congestion AND mobile robots AND persistence | 200 | 0 |  |
| 4a.1 | 4a | dwell time AND AGV | 200 | 7 | Optimal location of dwell points in a single loop AGV system; Simuleringsbaserad utvärdering av prestanda hos alternativa ; Simuleringsbaserad utvärdering av prestanda hos alternativa  |
| 4a.2 | 4a | dwell time AND robot AND timeout | 200 | 0 |  |
| 4a.3 | 4a | service time AND median AND threshold AND outlier | 200 | 3 | Detecting Abnormal Drinking Water Consumptions And Developin; Detecting Abnormal Drinking Water Consumptions And Developin; FWS/CSS-139-2022 |
| 4a.4 | 4a | VDA 5050 | 200 | 32 | VDA 5050 im Fokus; VDA 5050 - Eine Analyse und Einordnung; VDA 5050 - Eine Analyse und Einordnung |
| 4b.1 | 4b | absence AND traffic AND blocked | 200 | 58 | Visual obstruction, but not moderate traffic noise, increase; Visual obstruction, but not moderate traffic noise, increase; PROBABILITY MODEL FOR PERFOMANCE ANALYSIS OF JOINT URLLC AND |
| 4b.2 | 4b | road closure AND detection | 200 | 208 | Loop closure detection on a suburban road network using a co; Black ice detection and road closure control system for Okla; BLACK ICE DETECTION AND ROAD CLOSURE CONTROL SYSTEM FOR OKLA |
| 4b.3 | 4b | zero count AND road segment | 200 | 11 | Modeling accident risk at the road level through zero-inflat; A Trial of a Virtual Fence to Mitigate Roadkill on an Unseal; Integrating the macroscopic and microscopic traffic safety a |
| 4b.4 | 4b | negative information AND robots AND blocked | 200 | 0 |  |
| 4b.5 | 4b | absence AND AGV | 200 | 40 | Modeling and control of the AGV system in an automated conta; Progresses on the Design of Small Flexible Automated Guided ; Planification de trajets pour un véhicule à guidage automati |
| P6-1.1 | P6-1 | anomaly detection AND AGV AND warehouse | 200 | 1 | Anomaly detection for autonomous guided vehicles using Bayes |
| P6-1.2 | P6-1 | fault detection AND multi robot AND real world | 200 | 12 | A Distributed Approach for Fault Detection in Swarms of Robo; Distributed fault detection in swarm robotic systems using a; Fault-Tolerant Framework for Dynamic Task Reassignment in Mu |
| P6-1.3 | P6-1 | stuck AND robot AND fleet | 200 | 2 | Route Planning and Operator Allocation in Robot Fleets; ÇOKLU SENSOR FÜZYONU İLE LOKALİZASYON PERFORMANS TAHMİNİ |
| P6-4.1 | P6-4 | congestion AND index AND AGV | 200 | 0 |  |
| P6-4.2 | P6-4 | congestion AND metric AND multi robot | 200 | 26 | Risk-Aware Motion Planning forMulti-Robot System; Semantische Modellierung von Situationen zur Aufgabenplanung; Frontmatter |
| P6-4.3 | P6-4 | congestion AND measure AND warehouse robots | 200 | 0 |  |
| P6-6.1 | P6-6 | delay attribution AND railway | 200 | 8 | A methodology for measuring the quality of deviation reporti; Description of railway delays : a study from the views of th; Measuring high-speed train delay severity: Static and dynami |
| P6-6.2 | P6-6 | delay attribution AND accuracy | 200 | 41 | A methodology for measuring the quality of deviation reporti; Influence of stimulated Brillouin scattering on positioning ; She told me about a singing cactus: Counterintuitive concept |
| P6-6.3 | P6-6 | root cause AND delay AND AGV | 200 | 0 |  |
| P6-6.4 | P6-6 | knock on AND delays AND automatic | 200 | 1 | Non-Discriminatory Automatic Registration of Knock-On Train  |

### OR-grouped queries (ran; hits screened for presence only, zeros not counted)

| id | claim | Part 5 idx | HTTP | hits | first titles |
|---|---|---|---|---|---|
| b1 | 1b | 6,9 | 200 | 15 | A Hardware-Software Complex for the Reconstruction of Unmann; Analysing Requests Blocked by Modsecurity; Constraining electric resistivity tomography by direct push  |
| b2 | 1b | 9,10 | 200 | 0 |  |
| b3 | 1b | 8 | 200 | 182 | Collision-Free Robot Scheduling; Collision-free Robot Scheduling; Auction aggregation protocols for wireless robot-robot coord |
| b4 | 1b | 6,7 | 200 | 0 |  |
| c1 | 1c | 11 | 200 | 0 |  |
| c2 | 1c | 12 | 200 | 9 | The spatial-temporal prediction of various crime types in Ho; Next-gen regional fire risk mapping: Integrating hyperspectr; AN INDEX MAPPING-BASED DEEP TRANSFER LEARNING APPROACH FOR V |
| d1 | 1d | 14,16 | 200 | 6 | Fullerol-facilitated transport of copper ions in water-satur; The engineer's pothole repair guide; Port of Tacoma, Pier 4 Reconfiguration - Phase 2 |
| d2 | 1d | 13,14 | 200 | 107 | (Brachyura: Potamidae) identifies Quaternary glacial refugia; Origin of depleted components in basalt related to the Hawai; Quantifying beetle-macrofungal associations in a temperate b |
| d3 | 1d | 15 | 200 | 232 | Pits versus patterns: effects of transponders on recapturera; Pits versus patterns: effects of transponders on recapturera; Pits versus patterns: effects of transponders on recapturera |
| a1 | 2a | 24,25 | 200 | 114 | Collision avoidance for persistent monitoring in multi-robot; A Scheme for Coordinating Multi-robot Planning Activities an; A Scheme for Coordinating Multi-robot Planning Activities an |
| a2 | 2a | 22,26 | 200 | 0 |  |
| a3 | 2a | bulk,8 | 200 | 707 | Deadlock resolutions in flexible manufacturing systems with ; Deadlock resolutions in flexible manufacturing systems with ; Traffic Management of Multi-AGV Systems by Improved Dynamic  |
| m1 | 2b | 27,28 | 200 | 46 | Adaptive Communication for Mobile Multi-Robot Systems; Adaptive Communication for Mobile Multi-Robot Systems; Adaptive Communication for Mobile Multi-Robot Systems |
| m2 | 2b | 29,31 | 200 | 835 | Coverage Hole Elimination System in Industrial Environment; The Repair Strategy for Event Coverage Holes Based on Mobile; Market-Based Sensor Relocation by a Team of Robots in Wirele |
| m3 | 2b | 30 | 200 | 306 | Coverage Hole Elimination System in Industrial Environment; ENHANCING PLC-WIFI NETWORK CONNECTIVITY AND RADIO ENVIRONMEN; ENHANCING PLC-WIFI NETWORK CONNECTIVITY AND RADIO ENVIRONMEN |
| m4 | 2b/P6-7 | P6 row 7 | 200 | 3384 | Coverage Hole Elimination System in Industrial Environment; Building a coverage hole-free communication tree; Building a coverage hole-free communication tree |
| l1 | 2c | 32,34 | 200 | 15 | Multi-Task Learning for Industrial Mobile Robot Perception U; Synapse Open Dataset: A dataset for warehouse robots; Model-Predictive Control for Omnidirectional Mobile Robots i |
| l2 | 2c | 33,35 | 200 | 1 | Raw Simulation Logs and Intralogistics Performance Metrics f |
| t1 | 2b1 | 37,39,40 | 200 | 0 |  |
| t2 | 2b1 | 36 | 200 | 120 | Care + a robot = good care?; Care + a robot = good care?; Campus Day tug-of-war, 1961 |
| t3 | 2b1 | 38 | 200 | 112 | 3DOF pedestrian trajectory prediction learned from long-term; 3DOF Pedestrian Trajectory Prediction Learned from Long-Term; 3DOF Pedestrian Trajectory Prediction Learned from Long-Term |
| q1 | Q1 | 42,46,47 | 200 | 37 | Special issue on multi-robot systems: Challenges, trends, an; Hybrid Motion Planner Integrating Global Voronoi Diagrams an; Hybrid Motion Planner Integrating Global Voronoi Diagrams an |
| q2 | Q1 | 41,44 | 200 | 46 | Online Guidance Graph Optimization for Lifelong Multi-Agent ; Caching-Augmented Lifelong Multi-Agent Path Finding; Caching-Augmented Lifelong Multi-Agent Path Finding |
| q3 | Q1 | 46 | 200 | 119 | Impact Analysis of Travel Time Uncertainty on AGV Catch-Up C; AGV travel time among L/U point and machines for example 2.; Task Travel Time Prediction Method Based on IMA-SURBF for Ta |
| f1 | Q2 | 48,50 | 200 | 128 | Localization of Mobile Robots in a Network using Mobile Agen; Multi-robot coordination under temporal uncertainty; Sampling-based Multi-robot Motion Planning |
| f2 | Q2 | 49,51 | 200 | 0 |  |
| k1 | 4a | 55,58 | 200 | 0 |  |
| k2 | 4a | 56 | 200 | 32 | VDA 5050 im Fokus; VDA 5050 - Eine Analyse und Einordnung; VDA 5050 - Eine Analyse und Einordnung |
| k3 | 4a | 57 | 200 | 32 | Denial of service detection using dynamic time warping; Denial of service detection using dynamic time warping; Denial of service detection using dynamic time warping |
| x1 | 4b | 59,60 | 200 | 331 | Jumping to negative impressions again: The role of pessimism; Feedbacks play an important role in the ABA induced closure ; Social Network Closure and Child Adjustment |
| x2 | 4b | 61,62 | 200 | 101 | Loop closure detection on a suburban road network using a co; Black ice detection and road closure control system for Okla; BLACK ICE DETECTION AND ROAD CLOSURE CONTROL SYSTEM FOR OKLA |
| x3 | 4b | 59,63 | 200 | 13 | Warehouse in Tanos-Viernoles industrial park; Violence in eighteenth-century European port-cities and thei; Local aggregate - conceptual design of a multidisciplinary s |
| s1 | P6-1 | P6 row 1 | 200 | 0 |  |
| g1 | P6-4 | P6 row 4 | 200 | 1581 | Categorizing Congestion: A Framework for Congestion Analysis; A quantitative measure of congestion in Stellenbosch using p; Feature Congestion: A Measure of Display Clutter |
| r1 | P6-6 | P6 row 6 | 200 | 665 | A methodology for measuring the quality of deviation reporti; Hierarchical Delay Attribution Classification using Unstruct; Hierarchical Delay Attribution Classification using Unstruct |
| r2 | P6-6 | P6 row 6 | 200 | 214 | A methodology for measuring the quality of deviation reporti; A probabilistic multi-touch attribution model for online adv; Hierarchical Delay Attribution Classification using Unstruct |
| r3 | P6-6 | P6 row 6 | 200 | 170 | Stochastic modelling of train delays and delay propagation i; A delay root cause discovery and timetable adjustment model ; Automatic Door Lock Design with Arduino Mega 2560 Based Knoc |

### Known-item calibration

| id | claim field | query | HTTP | first title |
|---|---|---|---|---|
| K-kita | Q1/1f | `title:"Online Re-Planning and Adaptive Parameter Update"` | 200 | Online Re-Planning and Adaptive Parameter Update for Multi-A |
| K-azzalini | P6-1/1a | `title:"HMMs for Anomaly Detection in Autonomous Robots"` | 200 | HMMs for Anomaly Detection in Autonomous Robots |
| K-tarapore | P6-1 | `title:"decentralized fault detection for robot swarms"` | 200 | Generic, scalable and decentralized fault detection for robo |
| K-bonetti | 2a | `title:"Deadlock detection and resolution for AGV fleets"` | 200 |  |
| K-deepfleet | 2c/Q2 | `title:"DeepFleet"` | 200 |  |
| K-zarour | 2b | `title:"Coverage hole elimination in industrial environment"` | 200 | Coverage Hole Elimination System in Industrial Environment |
| K-obrien | 2b | `title:"Real-time diagnostics of 5G and Wi-Fi using mobile robotics"` | 200 |  |
| K-daamen | P6-6 | `title:"knock-on train delays"` | 200 | Non-Discriminatory Automatic Registration of Knock-On Train  |
| K-mohler | 1c/1d | `title:"Randomized controlled field trials of predictive policing"` | 200 | Randomized Controlled Field Trials of Predictive Policing |
| K-fitzpatrick | 1c/1d | `title:"Policing chronic and temporary hot spots"` | 200 |  |
| K-kondaveeti | 1e | `(title:"alarm" AND abstract:"Return To Normal")` | 200 | Detection of Historical Alarm Subsequences Using Alarm Event |
| K-deepfleet-ax | 2c/Q2 | `arxivId:"2508.08574"` | err 500 |  |
| K-deepfleet-t | 2c/Q2 | `title:"Multi-Agent Foundation Models for Mobile Robots"` | 200 | Multi-Agent System Based on Psychological Models for Mobile  |
| K-obrien-doi | 2b | `doi:"10.3390/jsan14060110"` | 200 |  |
| K-fitz-ax | 1c/1d | `arxivId:"2011.06019"` | err 500 |  |
| K-moroop | 2c/2b1 | `title:"MoRoOp"` | 200 |  |
| K-neill-doi | 4b/Q1 | `doi:"10.1145/1081870.1081897"` | 200 | Detection of emerging space-time clusters |
| K-lee-doi | 2b1 | `doi:"10.1177/20552076261437181"` | 200 |  |
| K-gerling-doi | 2b1 | `doi:"10.1007/s00391-016-1065-6"` | 200 | Robot deployment in long-term care |
| K-chainey-doi | 1c/1d | `doi:"10.1057/palgrave.sj.8350066"` | 200 | The Utility of Hotspot Mapping for Predicting Spatial Patter |
| K-bonetti-doi | 2a | `doi:"10.1177/02783649261470035"` | 200 | A traffic management system for large and heterogeneous vehi |

# Scouting: does the fleet stall analyser transfer to greenhouse and vertical-farm internal logistics? (2026-10-19)

Scope: pipe-rail trolleys, harvest carts, induction-wire carts and container-farm shuttles. WebFetch/WebSearch only, no
browser, no logins. Source ranks follow `outward-claim-discipline` (private harness rule set) (A = owner's own docs, dataset page or
repo; B = first-party marketing; C = press; D = tutorials, mirrors, blogs, dataset pages without a card; F = memory or
name only). The search log (every query and URL with its result) is in
`reports/wr-scout-greenhouse-logistics.md`, not here. Sibling scout: [farm-robots.md](farm-robots.md).

## 1. Fit

Location holds, and the map is one-dimensional. Pipe-rail trolleys run on the greenhouse's heating pipes and harvest carts
follow an induction wire, stopping at fixed stop points ([Bogaerts, Qii-Drive, verified@2026-10-19, B](https://www.greentech.nl/products-and-services/bogaerts-greenhouse-logistics/products/qii-drive)),
so the map is a graph of rail segments between stop points and junctions, not a 2-D grid; Logiqs' X-Rail adds row changes,
which makes it a sparse graph of junctions, not a grid ([Logiqs, B](https://www.greentech.nl/products-and-services/logiqs-b-v/products)).
A cell is therefore a segment or a bay, and a decayed count spreads along graph distance, not Chebyshev distance.
Faults that recur at places are plausible but unmeasured: the public pipe-rail troubleshooting page names component and
operator causes (flat batteries, key switch, emergency stop, limit switch) and no place
([Royal Brinkman, D](https://royalbrinkman.com/knowledge-center/mechanical-equipment/solve-problems-pipe-rail-trolley), verified@2026-10-19).
Logs with position and state are half-present: GREENBOT records robot pose and sensors but no state or fault
([Almería, A-, via paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC10976038/), verified@2026-10-19), and no greenhouse log with a stop cause was found.
The next window holds: a trolley runs daily, so the next day at the same segment is a natural window, better than the
seasonal field windows in farm-robots.md. A **stall** here is an unplanned stop of a loaded trolley or cart longer than a
set time; planned stops at stop points and bay loading are excluded, as our `by_design` class does (our definition, no
URL). The **planner-blind case** changes shape: on a single rail there is no detour, so an unknown obstacle freezes every
trolley queued behind it, and only junctions give alternatives (our reasoning from the geometry, not a sourced fact; the
planner-blind premise of our env assumes a detour exists). The throughput metric (our definition, the pick-rate equivalent) is completed transport tasks per
robot-hour: tray moves or harvest-cart loads.

## 2. Data

**None found:** no public log pairs a greenhouse rail or trolley position with a fault or stop cause. Repositories searched
(queries and counts in the report): **Zenodo** (API keyword search, read; "VDA 5050" OR AGV log returned 4 hits, none a fleet
log; "greenhouse robot" returned mostly greenhouse-gas records, relevant items read). **Hugging Face** (datasets API
search "greenhouse", 50 results read, each candidate opened). **GitHub** (repository search, 14,675 hits, first 18 read,
none a rail-fleet log). **Kaggle** (search page is JavaScript-only, no results rendered: **inconclusive, not searched**).
**IEEE DataPort** (site search query not applied, 24 unrelated listings: **inconclusive**). **data.gov** (CKAN API returned
HTTP 404: **not searched**). **data.europa.eu** (API returned unrelated results, query not applied: **partial**). The
**standard body**: the VDA 5050 specification repository was read; the VDA's own PDF surfaced in search only and was not
opened. All verified@2026-10-19.

| name | owner | URL | size | fields | position? | state/fault? | licence | rank |
|---|---|---|---|---|---|---|---|---|
| GREENBOT (multimodal greenhouse robot dataset) | Univ. of Almería | https://arm.ual.es/arm-group/dataset-greenhouse-2024/ (URL from the paper's data statement, not fetched; paper DOI 10.3390/s24061874) | not checked | stereo camera, 2 LiDARs, IMU, GNSS, per-sequence climate (air temp, humidity, irradiance) | yes (SLAM trajectories; the paper's "Pose" ground truth is not a described reference system) | no | none stated for the data (article CC BY) | A- |
| Risk-aware greenhouse robot navigation, code and trial data | Karakoç and Bucak, Iğdır Univ. | https://doi.org/10.5281/zenodo.23024226 | 4.9 MB | code, DQN checkpoints, RRT* results, "training logs"; geothermal tomato greenhouse simulation | UNTESTED (archive not opened) | no (training logs only) | CC BY 4.0 | A |
| Smart-Greenhouse-Telemetry | GS-2004 (HF) | https://huggingface.co/datasets/GS-2004/Smart-Greenhouse-Telemetry | 5,000 rows, CSV | Timestamp, Temperature_C, Humidity_Pct, LDR_Raw, Soil_Moisture_Pct, Risk_Level | no | Risk_Level, undefined; "No dataset card yet" | not stated | D |
| greenhouse-sensor-data | Okyanus (HF) | https://huggingface.co/datasets/Okyanus/greenhouse-sensor-data | 18,414 rows, 32.4 MB | instruction/input/output text with climate keys; no robot fields | no | no | CC BY 4.0 | B |
| Greenhouse-Inspection-Robot | richardmotee (HF) | https://huggingface.co/datasets/richardmotee/Greenhouse-Inspection-Robot | 14.4 GB, viewer unavailable | UNTESTED (empty README, no schema) | UNTESTED | UNTESTED | MIT | F (name only) |
| VDA 5050 specification (our telemetry-standard equivalent) | VDA, GitHub mirror | https://github.com/VDA5050/VDA5050 | spec and JSON schemas, no data | state and order messages (schema) | by message schema, no log | by message schema, no log | MIT (repo) | A |

**Telemetry standard.** VDA 5050 is the nearest equivalent: an open fleet-to-robot standard for AGVs and mobile robots
whose schema repository has only specification files (top level `assets/`, `json_schemas/`, `LICENSE.txt`, `README.md`,
`VDA5050_EN.md`; [VDA5050 repo, MIT, verified@2026-10-19, A](https://github.com/VDA5050/VDA5050)). **No open VDA 5050 log was
found** in the Zenodo, GitHub or web searches; the two Zenodo records that name VDA 5050 are a framework that lists support for
it and a gap-analysis preprint. No greenhouse rail or trolley vendor was seen publishing a VDA 5050 interface. Berg Hortimotive's public pages show
manuals and service documents, no BergDrive, API or software download
([berghortimotive.com, verified@2026-10-19, B](https://www.berghortimotive.com/)).

## 3. Simulators

No open simulator injects faults by location into a greenhouse rail or trolley fleet. Rows verified@2026-10-19 unless
marked "carried from farm-robots.md".

| name | URL | licence | maintained? | faults by location? | CPU-only? | python API? | verified@ |
|---|---|---|---|---|---|---|---|
| Lay2Graph-MAPD-Framework (event-driven discrete-time sim, layout-aware routing graph) | https://zenodo.org/records/21410202 | MIT | v1.0.0, published 2026-07-17 | no; faults not mentioned on the record | UNTESTED | partial: metadata says Python, no entry points named | 2026-10-19 |
| RWARE (multi-robot warehouse MARL grid) | https://github.com/semitable/robotic-warehouse | MIT | last push 2024-09-15 (carried from farm-robots.md) | no; obstacles are shelves, no failure model | UNTESTED | yes (`pip install rware`) | 2026-10-19 |
| Flatland (rail grid MARL) | https://github.com/flatland-association/flatland-rl | MIT | pushed 2026-10-19 (carried from farm-robots.md) | no: malfunctions per agent and rate-based, not by place | yes (carried) | yes (carried) | carried from farm-robots.md |
| Agri-Sim (Unity + ROS 2, one dual-arm harvest robot) | https://arxiv.org/abs/2608.29100 | not stated; no code link | not stated | no; one robot, no fleet or fault model | UNTESTED | no | 2026-10-19 |
| greenhouse-open (climate simulator, no robots) | https://github.com/AndreyBesedin/greenhouse-open | Apache-2.0 | 719 commits, no push date read | no; "a simulator with a hidden world and noisy sensors" for climate | yes (Python 3.14, uv) | yes | 2026-10-19 |

Adaptation: our emitter needs the medium map re-skinned as a rail graph with stop nodes and junctions, a segment-blocking
fault model, and the same VDA 5050-shaped state messages, while the event loop could come from Lay2Graph or RWARE. Our
estimate, not measured: a moderate rewrite of the layout and fault layers, not a re-skin of the planner.

## 4. Who sells this already

Six vendors, nine capabilities each, the same bar and cell rules as `docs/COMPETITION.md`, at most 10 fetches per vendor.
Every cell is UNTESTED: none of the six has a readable documentation tree that was searched, so no absence is claimed and no
presence is shown. H = heatmap, T = recurring-location trend, F = forecast, G = forecast grading, L = graded lessons,
D = time-to-detect, R = decision ledger, Z = avoid-zones to routing, U = log upload.

| vendor | doc tree | H | T | F | G | L | D | R | Z | U |
|---|---|---|---|---|---|---|---|---|---|---|
| Berg Hortimotive (BeNomic pipe-rail trolleys, BeTrac AGV) | service pages: two PDF manuals per product, no software or API page ([verified@2026-10-19](https://berghortimotive.com/nl/service-onderhoud/benomic-star-300/handleidingen)) | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| Bogaerts Greenhouse Logistics (Qii-Drive, Power Bee harvest carts) | product pages on greentech.nl only; no vendor site found | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| Logiqs (2D-Shuttle, X-Rail) | no support portal found; task software Dat-A-Control named in a trade listing ([search snippet](https://www.greentech.nl/news/in-the-spotlight-the-logiqs-story/), not fetched) | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| Octiva (Xenion platform, Device Manager) | [octiva.tech](https://octiva.tech/): no docs, support or API links | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| Ecoation (sensors and cameras on Bogaerts trolleys) | ecoation.com: DNS failure on www.ecoation.com, UNTESTED ([hortidaily, search snippet](https://hortidaily.com/article/9360096/data-collection-on-the-go-requires-a-reliable-solution-for-mobility)) | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| Fabrico (MES, OEE, CMMS for growers) | [fabrico.io](https://fabrico.io/): no docs, help, API or changelog link; knowledge centre is marketing | ? | ? | ? | ? | ? | ? | ? | ? | ? |

Evidence behind the nearest misses, none scored:

- **Fabrico, near miss for D:** "tracks downtime automatically" and "Cameras suggest the real reason for each stop", with
  asset hierarchies per plant ([fabrico.io, B](https://fabrico.io/)). Its own blog gives a zone-keyed work order, "Si la humedad
  aumenta bruscamente en la Zona 4" (a humidity rise in Zone 4), for a sensor, not a robot
  ([Fabrico blog, 26 Feb 2026, B](https://www.fabrico.io/es/blog/best-maintenance-software-commercial-greenhouses-indoor-farming/)).
  Not counted as a heatmap: it is a climate alarm, not a stall location.
- **Ecoation with Bogaerts, near miss for H and T:** location-tagged scouting data from trolleys, with "real-time analytics"
  claimed and no technical detail (trade press, C; search snippet). Not counted: it is crop and climate data, not stops.
- **Octiva, marketing only:** "Reliable insights through our Octiva Device Manager" and "Real-time data for full control and
  planning" ([octiva.tech, B](https://octiva.tech/)). No fault, stop or location term on the page.
- **Berg and Bogaerts, absence not checked:** Berg's page lists a "Datagedreven systemen" category with no description, and its
  manuals were not read beyond one product. Bogaerts' product text names obstacle stops, not fault logging. Neither can carry
  an absence yet.

Checked, not rows: Swisslog's product page has no vertical-farming product, only warehouse pallet shuttles and a "SynQ"
software platform with "real-time visibility" ([swisslog.com, B](https://www.swisslog.com/en/products/vertical-farming));
Priva's robotics were merged into Octiva (search snippet only, not fetched).

Direction test, against us: Ecoation's location-tagged scouting and Fabrico's zone alarm were not counted as presence, so
the errors could still flatter us. In our favour, not counted: Fabrico's climate alarms. What remains: the Berg service
tree, the Bogaerts and Logiqs trees and the Ecoation site are UNTESTED, so "nobody sells fault heatmaps for rails" is not
a claim this section supports.

## 5. Academic anchor

**None found:** no paper does fault, stop or stall hotspot analysis by location for greenhouse rail, trolley or shuttle
fleets. Queries (web search unless noted, all run 2026-10-19): "greenhouse AGV OR pipe-rail OR trolley fault stop location
analysis journal article 2024 2025"; "greenhouse rail-guided robot fault diagnosis failure location paper"; "greenhouse
robot fault stop location dataset logs zenodo"; "agricultural robot downtime root cause analysis fleet logs stops spatial
hotspot paper"; "greenhouse multi-robot logistics simulator open source python"; "vertical farm robot simulation open source
Gazebo OR Unity OR python multi-robot rail grow tower"; "\"greenhouse\" \"pipe rail\" OR \"rail-guided\" robot multi-agent
path finding OR fault injection simulation paper"; arXiv API `all:greenhouse AND (AGV OR trolley OR pipe rail OR multi-robot)`
(3 hits, none on faults). Limit: no Semantic Scholar or Google Scholar query ran, so this rests on web search and arXiv only.

Near misses, **not hotspot analysis**, named so the operator does not have to look again:

| paper | venue, year | URL | read depth | location content |
|---|---|---|---|---|
| Yan, Jackson and Dunnett, AGV mission reliability (FMECA, fault tree, Petri net) | Int. J. Adv. Manuf. Technol. 92(5-8), 2017 | https://doi.org/10.1007/s00170-017-0175-7 | search summary only (A-) | none; the authors note the Petri-net method "could easily be extended to" fleets |
| Cañadas-Aránega et al., ROS 2 to MQTT cloud architecture in Mediterranean greenhouses | arXiv 2606.22682, cs.RO, submitted 21 Jun 2026 | https://arxiv.org/abs/2606.22682 | abstract (A-) | telemetry exchange only; no fault or stop analysis by place |

All verified@2026-10-19.

## 6. Verdict

We cannot demo this domain honestly within two weeks on public data, because no open greenhouse rail or trolley log pairs
a position with a fault or stop cause, in any repository searched (section 2). A simulated demo is possible but proves less:
re-skinning Lay2Graph or RWARE as a rail graph with segment blocking shows that the pipeline runs on a different layout, not
that faults recur at places. The first measurement worth making is in that re-skin: does the analyser's top-K segment list
recover the injected blocked segments, and how many trolleys does one blocked segment freeze, since a rail has no detour
and the planner-blind premise changes. The single blocker is data: a grower or a vendor (Bogaerts, Berg via a customer,
Logiqs) would have to share a trolley log with positions and stop causes, and none is public. Competition is UNTESTED for
all six vendors, so this section cannot claim an open field. Fit is partial: the next window is daily, which helps, but the
rail network has no route around a fault, which the method was not built for.

SCOUT_SCORE: data=1 (GREENBOT gives position, but no open log has state or fault), sim=2 (two MIT Python sims host a rail event loop, neither injects faults by place), competition=2 (all six vendors UNTESTED, nearest misses Fabrico and Ecoation, so not an open field), fit=2 (1-D rail map and daily windows fit, but no fault log and no detour)

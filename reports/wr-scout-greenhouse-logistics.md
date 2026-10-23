# wr-scout-greenhouse-logistics: search log (2026-10-19, started 11:05 UTC, finished about 11:12 UTC)

Doc: `warehouse-rl/docs/scouting/greenhouse-logistics.md`, committed and pushed as 655ef85 on master (verified: origin/master = HEAD).
Scope from the brief: greenhouse and vertical-farm internal logistics (pipe-rail trolleys, harvest carts, container-farm shuttles).
WebFetch and WebSearch only. Budget 75 minutes; used about 7.

Contradiction sweep: `docs/scouting/farm-robots.md` was read in full. Its Flatland row (malfunctions per agent, rate-based, not by place) and its RWARE row (last push 2024-09-15) are carried into the greenhouse doc with the same wording and no new claim against them. Nothing in the farm doc is contradicted.

## Search log

### Web searches (WebSearch, standard mode unless noted)
1. "VDA 5050 open dataset log AGV telemetry zenodo OR kaggle OR github": KIT page, standict.eu, powerprogress (VDA 5050 2.0.0), flowfuse blog (Aug 2026), VDA PDF EN-VDA5050-V2_0_0 (surfaced, not fetched), bluebotics blog, github VDA5050 repo. Result: no open VDA 5050 log.
2. "greenhouse rail trolley autonomous internal logistics robot pipe-rail vendor": greentech.nl Logiqs story, Berg Hortimotive pages, Bogaerts products, tomatoworld.nl pipe-rail trolleys, hortispares. Result: vendor leads (Berg, Bogaerts, Logiqs).
3. "greenhouse robot fault stop location dataset logs zenodo": GREENBOT (PMC10976038), synthetic localisation rosbags, Zenodo 1467221 (robot swarm, not greenhouse), Bielefeld fault dataset. Result: no greenhouse fault log.
4. "vertical farm autonomous shuttle AGV fleet software vendor fault analytics": FleetExecuter (MHP), Seegrid, verticalfarmdaily fleet article, Oxmaint. Result: no vertical-farm shuttle fault vendor.
5. "greenhouse multi-robot logistics simulator open source python": arXiv 2608.29100 (Agri-Sim), arXiv 2504.09079 (agriFrame), GreenhouseSplat, RWARE, RAWSim-O Python MVP, Westworld. Result: RWARE the nearest candidate.
6. "greenhouse fleet management software trolley harvest cart telemetry analytics vendor": Boxcar Central, Agrilyst, SBI, Hoogendoorn Analytics, Ecoation/Bogaerts (hortidaily). Result: no trolley fleet product; Ecoation-Bogaerts lead.
7. "Priva OR Hortiplex OR Ondo greenhouse logistics robot fleet control software": Priva brochure, Kompano, Octiva/Continental press, Hortilogics JV. Hortiplex and Ondo: no results.
8. "container farm shuttle robot vertical farm rail system fault monitoring software": US patents (11778956, 12252343 Amazon shuttle self-maintenance), verticalfarmdaily, Swisslog PowerStore. Result: no vertical-farm fault product.
9. "greenhouse rail-guided robot fault diagnosis failure location paper": Chalmers rail-bound inspection thesis, AGV fault patents, IJCAI 2005 model-based diagnosis. Result: no greenhouse paper.
10. "Bogaerts Greenhouse Logistics website harvest cart automatic inductive wire fault monitoring": no vendor page; patents only.
12. "Logiqs 2D shuttle greenhouse X-Rail support documentation": greentech Logiqs, IPM Essen listing, hortidaily Geman greenhouse, Dat-A-Control (trade listing). No support portal.
13. "greenhouse AGV OR pipe-rail OR trolley fault stop location analysis journal article 2024 2025": royalbrinkman fault page, hortispares pipe-rail category, Loughborough AGV reliability (Yan et al.). No greenhouse journal article.
14. "agricultural robot downtime root cause analysis fleet logs stops spatial hotspot paper": Fleet Rabbit pages, InOrbit Time Capsule (foodlogistics), PyRoboReplay (PyPI), downtime-driver patent. No paper.
15. "Ecoation Bogaerts mobility platform sensors cameras greenhouse real-time analytics": hortidaily (Bogaerts-Ecoation-Biobest), Ecoation (mtec-sc), OTTO scouting robot article. Result: partnership lead.
16. "\"greenhouse\" \"pipe rail\" OR \"rail-guided\" robot multi-agent path finding OR fault injection simulation paper": MAPF pipe routing (arXiv 1905.08412, Belov et al. SoCS 2020), delay-robust MAPF. No greenhouse.
17. "Loughborough AGV mission reliability FMECA fault tree Petri net Yan Jackson Dunnett journal": Springer s00170-017-0175-7, Loughborough thesis, ESREL 2016, RESS 2018 (named in a search summary, not fetched).
18. "vertical farm robot simulation open source Gazebo OR Unity OR python multi-robot rail grow tower": Gazebo/Unity comparison (TAROS 2024), cpr_agriculture_gazebo, Ignition crop fields. No vertical-farm rail simulator.

### Fetches (WebFetch)
- https://github.com/VDA5050/VDA5050: MIT; top level `assets/`, `json_schemas/`, `LICENSE.txt`, `README.md`, `VDA5050_EN.md`; no logs seen. 602 commits, no date shown.
- https://zenodo.org/api/records?q=greenhouse AND (robot OR AGV OR trolley OR logistics): 11 of many records read (truncated); query did not filter to robots (greenhouse-gas records). Record 2 (10.5281/zenodo.23024226) read via its record page.
- https://huggingface.co/api/datasets?search=greenhouse&limit=50: 50 entries, all tags read; candidates opened: GS-2004/Smart-Greenhouse-Telemetry, Okyanus/greenhouse-sensor-data, richardmotee/Greenhouse-Inspection-Robot.
- https://data.europa.eu/api/hub/search/search?q=greenhouse robot: returned a Polish dataset (dane.gov.pl, robotic surgery) and 3584 hits; query not applied. Recorded as partial.
- https://catalog.data.gov/api/3/action/package_search?q=greenhouse robot: HTTP 404. Not searched.
- https://api.github.com/search/repositories?q=greenhouse AGV OR greenhouse fleet OR greenhouse trolley OR pipe-rail: 14,675 total, first 18 read. Candidate opened: AndreyBesedin/greenhouse-open.
- https://github.com/AndreyBesedin/greenhouse-open: Apache-2.0, Python 3.14, climate simulator, no robots or faults.
- https://huggingface.co/datasets/GS-2004/Smart-Greenhouse-Telemetry: CSV, 5,000 rows, no card, no licence stated.
- https://huggingface.co/datasets/richardmotee/Greenhouse-Inspection-Robot: MIT, 14.4 GB, viewer unavailable, empty README.
- https://huggingface.co/datasets/Okyanus/greenhouse-sensor-data: CC BY 4.0, 18,414 rows, climate keys in text input, card present.
- https://github.com/richardmotee/Greenhouse-Inspection-Robot: HTTP 404 (wrong host; the HF dataset above is the real id).
- https://zenodo.org/records/23024226: CC BY 4.0, 4.9 MB, DQN and RRT* code, "training logs", no robot position or fault logs named.
- https://ieee-dataport.org/search?keywords=greenhouse robot: query not applied, 24 unrelated listings. Inconclusive.
- https://www.kaggle.com/search?q=greenhouse robot: JavaScript-only, no results. Inconclusive.
- https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10976038/ (redirected to pmc.ncbi.nlm.nih.gov): GREENBOT data statement, URL https://arm.ual.es/arm-group/dataset-greenhouse-2024/, sensors listed, no fault or stop annotations.
- https://zenodo.org/api/records?q="VDA 5050" OR VDA5050 OR (AGV AND log): 4 hits, none a fleet log.
- https://export.arxiv.org/api/query?search_query=all:greenhouse AND (AGV OR trolley OR pipe rail OR multi-robot): 3 hits (2109.03089, 2606.22682, 2109.10106).
- https://www.greentech.nl/products-and-services/bogaerts-greenhouse-logistics/products: Qii-Drive, Power Bee (induction cable, stops at obstacles and stop points), Bull Qii D930; no fault logging or API.
- https://www.greentech.nl/products-and-services/logiqs-b-v/products: 2D-Shuttle, semi-autonomous, battery, pipe-rail vehicle; no X-Rail detail, no software or support on the page.
- https://www.berghortimotive.com/ (fetched as https://www.bergHortimotive.com): menus, Service & onderhoud, Handleidingen per product, Datagedreven systemen (undescribed), Nieuws; no BergDrive, API or software download.
- https://berghortimotive.com/nl/service-onderhoud/benomic-star-300/handleidingen: two PDF manuals (NL-V2, EN-V1); no troubleshooting or fault-code guide listed by title.
- https://www.hortispares.com/brand/berg-hortimotive/: 301 to royalbrinkman.com/discover-hortispares; not followed.
- https://octiva.tech/ (redirect from octiva.com): Xenion platform, Lumion, Renion, Octiva Device Manager ("Reliable insights"); no docs, support or API links.
- https://ecoation.com and www.ecoation.com: DNS failure (getaddrinfo ENOTFOUND www.ecoation.com). Not reached.
- https://www.swisslog.com/en/products/vertical-farming: no vertical-farming product; warehouse pallet shuttles, SynQ software, customer portal login.
- https://www.fabrico.io/es/blog/best-maintenance-software-commercial-greenhouses-indoor-farming/: dated 26 Feb 2026; Fabrico, Priva, MaintainX, Artemis, UpKeep; Fabrico zone-based humidity work order.
- https://fabrico.io/: MES, OEE, CMMS, AI; no docs, help, API or changelog link on the page.
- https://royalbrinkman.com/knowledge-center/mechanical-equipment/solve-problems-pipe-rail-trolley: drive, lift, speed and tipping faults with component and operator causes; no location; no logging; "consult your dealer".
- https://github.com/semitable/robotic-warehouse: MIT, 198 commits, `pip install rware`, shelves and X/G layout, no fault model.
- https://arxiv.org/abs/2608.29100: Agri-Sim, Unity + ROS 2, one dual-arm harvest robot, no code link, licence not stated.
- https://arxiv.org/abs/2606.22682: ROS 2 to MQTT greenhouse architecture, submitted 21 Jun 2026, abstract only; telemetry exchange, no fault analysis.
- https://zenodo.org/records/21410202 (Lay2Graph-MAPD-Framework): MIT, v1.0.0 2026-07-17, Python per metadata, event-driven discrete-time simulation, layout-aware graph generation; no fault or blocked-cell model named.

## Decisions taken without the operator

- Vendor set: six rows (Berg, Bogaerts, Logiqs, Octiva, Ecoation, Fabrico), not eight. Swisslog and Priva were checked and left out as not greenhouse or vertical-farm rail vendors on the evidence read. Every cell is UNTESTED: no readable doc tree was searched for any of the six, so no absence was claimed under the brief's rule.
- Cell scoring: no `yes` cell, because no rank-A or rank-B source showed a stall or location capability for any vendor. Marketing near-misses (Fabrico's downtime tracking and zone alarm, Ecoation's trolley scouting) are described in prose, not scored.
- Simulator row for RWARE carries its 2024-09-15 push date from farm-robots.md rather than a new API read today; marked as carried.
- Berg's manual surface is read for one product only; its absence cells are UNTESTED, not "not found".
- The 1-D claim: pipe-rail and induction-wire routes are graphs of segments with junctions; the "no detour" consequence is our reasoning from geometry, labelled as such in section 1.
- Score: data=1, sim=2, competition=2, fit=2. Competition is 2 rather than 3 because a field with no readable vendor tree cannot be called open.

## Gate and checks

- Docs-only change; no code, no gate run. The unittest gate was not run because nothing under `src/`, `scripts/` or `tests/` changed.
- Line count of the doc: 148 (limit 250). Section headings: Fit, Data, Simulators, Who sells this already, Academic anchor, Verdict. Plus the title line and one scope sentence at the top.
- Claims: each outside-world claim carries a URL and verified@2026-10-19 or is marked as a search snippet, carried, or UNTESTED.

SCHED_RESULT: OK commit 655ef85 docs/scouting/greenhouse-logistics.md pushed to master; SCOUT_SCORE data=1 sim=2 competition=2 fit=2; 6 vendors all UNTESTED; 0 academic papers

# wr-scout-farm-robots — scouting report (2026-10-19)

Deliverable: `warehouse-rl/docs/scouting/farm-robots.md` (213 lines, limit 250), commits 7c9ae77 + 0e5e2c0 (review fixes) on master, pushed
(`git log -1 origin/master` = 0e5e2c0). Wall clock about 12:50-13:06 CEST, well inside 75 min. Method: three parallel
research subagents (datasets+standards, simulators+papers, vendors), WebFetch/WebSearch only, plus my own fetches for
the crop-sensing sub-question, the Flatland check, the DM1 check and the Deere release-notes URL.

## Outcome
- SCOUT_SCORE: data=1 sim=1 competition=2 fit=2.
- No public log pairs farm-machine position with a fault or stop cause (tractors, field robots, milking robots, feed
  pushers). Best public proxy: TUM tractor GNSS+CAN (Zenodo 14619787, CC BY 4.0, RTK + hitch in-work flag, 10 Hz).
- Open ISOBUS TimeLogs exist only as library test data (dev4Agriculture isoxml-dotnet, 21 TLGs; ADAPT ISOv4Plugin
  datacards, unopened). No public ADAPT sample log. DM1/ISO 11783-12 only at snippet level (unverified).
- No open farm simulator with fault injection by location; re-skin TA-RWARE/RWARE is the path.
- No academic hotspot-by-location paper found; near misses Velasquez 2022, CropFollow++ 2024.
- Vendors: only DeLaval and Burro have public doc trees; F/G/L/D/R not found there; 6/8 UNTESTED.
- Single blocker: data with fault/stop cause (OEM API with owner grant, e.g. CNH FieldOps, or a barn operator).

## Downgrades applied (advisor review before writing)
- Flatland fault-by-location: subagent said yes from memory; only a GitLab mirror was found (rank D) showing per-agent,
  rate-based malfunctions -> "possible with code".
- John Deere Equipment API: JS page, snippet only -> UNTESTED.
- DM1 PGN 65226: snippets only, direct fetches returned other PGNs (and my own isobus.net search fetch did not filter)
  -> unverified.
- "ISO 11783-10 has no alarm element": not in 21 TimeLogs read, standard text 403 -> UNTESTED.
- TUM hours: paper 862 h / 354 h fieldwork vs Zenodo 1245 h -> both printed.
- data.gov search inconclusive, data.europa.eu partial -> stated as such.
- Not cited: unopened arXiv IDs 2608.29100, 2609.25725, 2606.31941; PyBulletFleet; ISMN (site down, DDoS notice).
- Not padded section 5 with Gygax 2007 / Lehnert 2018 (no location content).

## Second-pass fixes (advisor, after first push) -> 0e5e2c0
- Section 2/1/6 "no position+fault log" narrowed to fleet scale: Augmenta (Zenodo 18293250) has position + a camera
  sun-glare fault, 48 kB, one field.
- First measurement reworded: TUM paper (WF PMC11993161) = one CSV per field and implement, 143 fields, one 2024
  season, passes per field not reported -> grade earlier vs later passes within one operation; repeat operations not assumed.
- Barn standard sentence: ISO 17532 / ISOagriNET seen in search results only (WS "ISOagriNET ISO 17532 livestock farm
  data exchange standard milking robot"; WF scc-ccn.ca 403, iteh.es DNS fail, technickenormy.cz redirect then socket
  hang-up) -> UNTESTED.
- Velasquez generalisation narrowed to "one deployment, 8 of 12 interventions".

## Open items / caveats
- Semantic Scholar API 429 on all 4 queries; no Google Scholar query. Section 5 rests on web search + arXiv.
- Vendor HTML quotes pass through the WebFetch summariser (near-verbatim); PDF quotes via pdftotext (exact).
- Monarch's website returned 404 on several paths today; only the training PDF was served.
- Unread lead: SLU (Ljunggren) thesis on unsuccessful milkings in rotary systems, may break down by bail position.
- The "Raam" soil network record fetched is the 2018-04/2019-04 release (DataCite API), CC0, 15-min logging.

## Search log

### Own fetches (main loop)
- WF https://ismn.earth/en/ -> ISMN described; services down (DDoS notice); not cited.
- WF https://www.aef-online.org/about-us/isobus.html -> ISOBUS general definition quoted; no part numbers.
- WF https://www.iso.org/standard/57556.html -> 403.
- WS "soil moisture sensor network logging interval 15 minutes hourly in situ dataset Zenodo" -> Raam (4TU), ISU AgClimate.
- WF https://doi.datacite.org/dois/10.4121%2Fuuid:b68e3971-... -> empty shell.
- WF https://api.datacite.org/dois/10.4121/uuid:b68e3971-c73e-4d7f-b52f-9ef7d7fe1ed2 -> title, 4TU, CC0, 15-min, 15 sites.
- WS "flatland-rl malfunction_generator malfunction parameters documentation" -> GitLab mirrors only; per-agent rate-based.
- WF https://www.isobus.net/isobus/pGNAndSPN/?type=PGN&search=65226 -> filter not applied, 65226 not shown.
- WS "John Deere Operations Center sept2023 release notes english pdf" -> full PDF URL found.

### Datasets + standards subagent (verbatim summary of its log)
1. WS "ISOXML TaskData TimeLog sample files GitHub" -> libraries only (isoxml.net, isoxml npm, PyPI isoxml, isoxmlviz).
2. WS "AgGateway ADAPT framework sample data GitHub" -> wiki/press; EPL, ISO plugin.
3. WS AMS dataset alarm/failed milking Zenodo/Mendeley -> patents/papers; buffalo paper ~4053 failed visits/yr (paper only).
4. WS GNSS trajectories ag machinery field-road -> papers (Agronomy 2023, IJABE, PeerJ); no public benchmark.
5. WS tractor CAN J1939 GPS dataset -> TUM, Tümosan; CANdid, CSU heavy-vehicle (not farm).
6. WF PMC11993161 -> TUM details.
7. WF Mendeley bbjtjrsxvx/2 -> Tümosan confirmed.
8. WF github.com/ADAPT, github.com/dev4Agriculture/isoxml.net -> 404.
9. WF api.github.com search q=isoxml -> 31 repos (19 read).
10. WF api.github.com search "ADAPT AgGateway" -> 2 repos.
11. WF zenodo 14619787 -> 2.8 GB, CC BY 4.0, v1 2025-01-09.
12. WF ISOv4Plugin / isoxml-dotnet / isoxml-js contents -> test data found.
13. WF TLGTest.cs, TLG00001.xml, TASKDATA.XML -> PTN position, DDI 141, 148, vendor DDIs.
14. WF api orgs/AgGateway-ADAPT/repos -> 15 repos; Examples code only; TwinYields/ISOXML test folder unopened.
15. WF isobus.net dDEntity/164 -> 404; dDEntity?search=141 -> DDI 141 Actual Work State.
16. WF developer.deere.com, /dev-docs/equipment -> title only (JS); WS snippet: alerts=DTCs, breadcrumbs.
17. WS "ISO 11783-12 DM1" -> snippets PGN 65226; WF isobus.net 15102/15104 -> PGN 64927 (mismatch); WF beta.isobus.net 16233 -> DM5.
18. WS Lely Astronaut dataset -> app/marketing only.
19. WS site:zenodo.org AMS -> papers only.
20. WS Kaggle milking robot -> barn video dataset, DeLaval analysis repos without data.
21. WF zenodo API milking robot -> 3 hits (barn video, simulated AgriFoodTEF records, survey).
22. WF zenodo API tractor GNSS / trajectory -> TUM, Augmenta, ROS2 windrow dataset; rest irrelevant.
23. WF zenodo API isoxml/isobus -> 10 hits; no TimeLog data.
24. WF zenodo 18293250 -> Augmenta confirmed; zenodo 22926317 -> PDF paper.
25. WS ISOBlue -> Purdue CKT archive.
26. WF purr cktgpsdata, publications/3083/3 -> confirmed.
27. WF HF API "tractor" 6 / "agricultural robot" 0 / "farm" 100 -> none telemetry.
28. WF catalog.data.gov API 404; query not applied; WS site:catalog.data.gov -> none. INCONCLUSIVE.
29. WF data.europa.eu "tractor GNSS" 1150 hits, "agricultural machinery" 228 -> first 4-6 read, aggregates/geodesy. PARTIAL.
30. WF ieee-dataport search 404; WS site: -> LFSD, RIFIS, Agri-EBV, mini-vehicle IMU (perception, no faults).
31. WS site:kaggle.com -> Padova GNSS study (403), IJABE 90 tractors (no data statement).
32. WF Kaggle API "tractor" 20 / "milking" 0 / "agricultural robot" 9 images / "telematics" 20 road.
33. WS site:data.mendeley.com -> not indexed.
34. WS/WF Rosario, Sugar Beets 2016 -> confirmed, no faults.
35. WS FarmDroid/Naio/SwarmFarm logs -> none; Wine Australia SwarmFarm trial "frequent stoppages" qualitatively.
36. WS site:aef-online.org -> none.
37. WS site:aggateway.org -> webinar TOC only.
38. WS ag robot failure/intervention logs -> none in ag (ForEnt forest quadruped nearest).
39. WS AMS dryad/figshare/Data in Brief -> papers only.
40. WS Lely Juno/Vector/DeLaval VMS logs -> marketing only.
41. WS CNH/AGCO/CLAAS APIs -> CNH FieldOps documented (WF develop.cnh.com); AGCO/CLAAS nothing; CNH sample files not found.
42. WF IJABE 10646 -> no data availability statement.

### Simulators + papers subagent (verbatim summary of its log)
- WS virtual_maize_field -> repo URL; GH API: GPL-3.0, push 2025-03-14; WF README: random hole/litter by seed.
- WS farm-gym -> readthedocs; GH API BSD-3 push 2025-08-22; WF docs: no robots/faults.
- WS CropCraft -> Romea/cropcraft; GH API Apache-2.0 push 2026-06-02.
- WS orchard MARL env -> no repo (arXiv 2303.00460, Berkeley slides).
- WS AMS DES SimPy -> Simul8/MATLAB/DigiMilk, no SimPy.
- WS Thorvald Gazebo -> no Thorvald repo; cpr_agriculture_gazebo (GH API no licence, push 2023-11-29).
- GH API WUR-AI/crop-gym MIT 2021-07-12; PCSE-Gym GPL-3.0 2026-06-18; gym-dssat forks only.
- GH API semitable/robotic-warehouse MIT 2024-09-15; Fields2Cover BSD-3 2026-09-22; flatland-rl MIT 2026-10-19.
- GH API "agriculture simulation multi-robot" -> agrofleet (WF README MIT; last commit 2026-07-28).
- GH API "milking simulation" -> karreric1/rms (WF: MIT, breakdowns unused; last commit 2019-10-30).
- WS PettingZoo ag -> none. WS AgriSim -> commercial; Agrobots-SIM. WS Webots ag -> none. WS Isaac ag -> AgriGen, Pheno-Robot (GPU).
- WS Agrobots-SIM github -> AgroRobotSimulator (GH API no licence, push 2024-02-07; WF README ROS Noetic + Gurobi), RoboVineSim (IJCAI 2026, no code).
- WS DES ag robot fleet python -> Lincoln DES paper (WF 403), INL FieldSim (not released), Ciw, PyBulletFleet (WF docs: repo/licence not stated).
- GH API LCAS/topological_navigation Apache-2.0 2026-10-16. WS Nav2 multi-robot orchard -> docs only. WS PyBullet ag -> none. WS CARLA tractor -> no open package.
- Papers: WS "spatial analysis failed milking attempts per milking box" -> SLU rotary thesis, UMN thesis; WS "agricultural robot field trials failure analysis MTBF" -> sweet pepper 1810.11920, machinery MTBF; WS "autonomous tractor field trial stops interventions location map analysis" -> nothing; WS "failure mode analysis agricultural field robot deployment" -> 2211.14013, DFKI ICRA 2023; WS "under-canopy ... failure locations map" -> CropFollow line; WS "milking robot incomplete milkings OR failed attachments JDS" -> Gygax 2007, Masía 2019; WS "autonomous feed pusher robot barn failures stuck" -> none; WS "field robot intervention events GPS location heatmap vineyard OR orchard" -> none; WS "automatic milking robot downtime alarms spatial" -> patents; WS "weeding robot field trial failures stuck terrain" -> trade press; WS "agricultural robot deployment where failures occur spatial statistics" -> headland/slope papers.
- S2 API x4 -> 429 (failed). arXiv API "agricultural AND robot AND failures AND deployment" -> 2 hits.
- WF arxiv.org/html/2404.17718v1 -> 7 failure types, no map. WF ar5iv 2106.15029 -> gaps/row ends in text. WF export.arxiv.org abs 2211.14013, 2106.15029, 2404.17718, 1810.11920 -> abstracts/venues. WF SLU thesis PDF -> binary, failed.

### Vendor subagent (fetch counts and URLs per vendor; WebSearch log)
- Deere (7): sept22, sept2023, mar2024 release-notes PDFs (deere.com/assets/pdfs/.../operations-center/); autonomous-tractor page (title only); operations-center-pro-service 404; deere.com/en/autonomy 404; deere.co.uk compatibility FAQ (title only).
- Monarch (7): https://www.monarchtractor.com/hubfs/Training%20Modules.pdf (108 pp read); /faq, /en/kb, /en/kb/operating-the-mk-v, /digital-solutions, homepage 404; Operator Guide PDF > 10 MB.
- Lely (4): community.lely.com HD15, HD67 -> auth.lely.cloud login; lely.com Horizon page (marketing); lely.com/services/technical-documents (121 docs, manuals).
- DeLaval (10): help.delaval.com/kb/en/; Analysis, Equipment, Attention categories; VMS overview guide; Voluntary Milking Performance index; Introduction to Alerts (x2); Using the Alerts app; What's New (titles).
- Burro (8): docs.burro.ai root; boss-web index; boss-pro; web-api (empty); exclusion-zones; reporting-issues; releaseburro.vercel.app/changelog; support.burro.ai.
- Carbon (5): carbonrobotics.com/companion-app, /faq, /support, /carbon-ops-center, /carbon-autonomy.
- AgXeed (7): agxeed.com/faq/, /traxwise/, routing FAQ category, TRAXWISE brochure PDF; ?p=8249, AgXCloud Sept 2024 update, /2024/01/page/5/ -> 404.
- FarmDroid (4): farmdroid.com/support/ 404; homepage footer; /faq/; App Store id6446589580.
- Excluded: SwarmFarm, Naio (searches returned unrelated firms), Agtonomy (third-party only).
- Prompt-injection note: Burro BOSS Pro page and AgXeed "For LLMs" page contained instructions aimed at AI tools; ignored.
- WebSearch log: 1 Deere OpsCenter alerts map -> dealer pages; 2 Monarch help -> marketing/FAQ; 3 Lely alarms per box -> nothing official; 4 Carbon docs -> press/FAQ; 5 Deere OC help DTC -> dealer/PRO page; 6 DeLaval alarms per box -> help.delaval.com; 7 AgXeed manual -> junk; 8 Burro help -> docs + changelog; 9 Lely KB -> community HD; 10 FarmDroid manual -> App Store; 11 SwarmFarm -> unrelated; 12 Naio -> unrelated; 13 Deere Expert Alerts -> construction; 14 help.deere.com -> release notes PDFs; 15 Deere release notes alerts -> PDFs; 16 Deere DataConnect -> press; 17 Deere autonomy obstacle stop -> 2022 trade press; 18 deere.com autonomy -> URL; 19 deere.com DataConnect -> UK FAQ, 2021 press; 20 Monarch operator manual -> training PDF; 21 Monarch stay-off zone -> nothing; 22 Carbon Ops Center help -> pages; 23 AgXeed obstacles -> snippet; 24 Agtonomy -> third-party; 25-27 AgXeed -> FAQ/TraXwise/nothing; 28 Carbon site search -> pages; 29 FarmDroid support -> third-party; 30 Lely A5 alarms -> HD67/HD53; 31 FarmDroid error log -> App Store; 32 FarmDroid FAQ alarm -> FAQ/brochures.

SCHED_RESULT: OK docs/scouting/farm-robots.md pushed (7c9ae77, 0e5e2c0); SCOUT_SCORE data=1 sim=1 competition=2 fit=2; blocker = no fleet-scale public position+fault log

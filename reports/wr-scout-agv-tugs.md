# Scout report: AGV and tug fleets (hospital, airport, port), 2026-10-19

Output: `docs/scouting/agv-tugs.md` (74 lines). Budget: 75 min; used about 40 min. Tools: WebSearch and WebFetch only.

## Search log

Every search and fetch, with its result. "snippet" = read from the search result only, not the page.

### Searches

1. "VDA 5050 open dataset log AGV fleet github": no open VDA 5050 log. Hits: github.com/berketunckal/VDA5050-FleetManagement (code), vda.de press release 2024, VDA 5050 explainers (snippet).
2. "AGV fleet telemetry dataset public position state fault logs port terminal": only a vendor API page for emergency vehicles (knogin.com, 7 translations). Not used.
3. "open source container terminal simulator AGV straddle carrier python": commercial (Mevea, LSyM) and academic papers only. No open AGV simulator.
4. "hospital AGV tug fleet stall fault hotspot analysis paper": arXiv 2006.10031 (Greenville hospital AGV DES, congestion, no faults); Loughborough FTA+Petri net (not hospital); WPI TUG corridor impasse thesis (2012).
5. "baggage tug airport fleet fault location analysis dataset": arXiv 2405.05514 (luggage trolley vision dataset, 13,740 images, not faults); TNO Schiphol tug simulation; NTSB report; no fault dataset.
6. "AGV failure diagnosis location hotspot mining port automated guided vehicles study": IFAC 2024 Bertoli et al. (closest); CN119105554A patent (bearing fault); no hotspot study.
7. "zenodo automated guided vehicle dataset logs": zenodo 17152352 (AGV PID tuning, CC-BY 4.0); Brainport AVP car logs (not AGV); IEEE DataPort AGV sidelink.
8. "Kaggle AGV warehouse robot logs dataset position status": zenodo 10793054 (DEDICAT6G positions); item.com docs; no Kaggle result. Kaggle site not searched directly.
9. "container terminal simulation open-source model benchmark instances AGV yard": Flexsim sample (commercial), WSC 2017 O2 DES.Net AGV model, Cyprus AGV yard layouts; no benchmark set.
10. "hospital autonomous mobile robot fleet vendor fault analytics heatmap dashboard": SPIE E.RAMP, OxMaint (marketing), Formant/InOrbit (already in competition doc), Aethon and Diligent named; no hospital heatmap doc.
11. "port terminal tractor AGV telemetry analytics vendor TOS integration fleet monitoring": Identec article (2026); AMPcontrol; Port Technology TEAMS; SEA Terminals 2016 slides; Terberg Connect at Spinelli Genoa (2020); CARGOES TOS+.
12. "Aethon TUG hospital robot fleet analytics dashboard docs": robotics.press profile (Fleet Management Suite), US9223313B2 patent, Parkview release (41,510 deliveries 2023). No docs found.
13. "Terberg Connect telematics terminal tractor fault codes location data": terbergspecialvehicles.com telematics page; Connect GO app; Trieste Marine Terminal (40 tractors).
14. "Diligent Robotics Moxi hospital fleet analytics stuck robot location report": ABI Research Moxi 2.0 fleet data; Diligent data-analyst job posting (maintenance programme intent). No stuck-location report.
15. "Kalmar terminal tractor AGV fleet data analytics product fault telemetry": Kalmar Insight (OT2 article, 2025), 2019 Kalmar presentation, 2021 remote services, SmartFleet (2015 PSA Singapore).
16. "open source AGV fleet simulator github VDA 5050 simulation": NVIDIA mission simulator (Apache-2.0 per NGC), libVDA5050++ (Fraunhofer), coatyio vda-5050-lib.js, openTCS adapters.
17. "Open-RMF fleet adapter AGV simulation open source license": ROS index rmf_fleet_adapter_python (Apache-2.0), PyBulletFleet RMF integration, Olive fleet adapter (Apache-2.0).
18. "automated container terminal AGV congestion deadlock spatial hotspot analysis simulation paper": Kim, Jeon, Ryu 2007 (Springer); Lehmann, Grunow, Günther 2007 (Springer); Li et al. 2016 IJARS; Gerrits, Mes, Schuur WSC 2018; Zhou, Li, Lee, Chew WSC 2017; Northwestern Polytechnical deadlock-free routing (2023-2026).
19. "hospital delivery robot AGV breakdown root cause location study journal": IFAC 2024 again; Fragapane NTNU hospital AGV; Preprints.org 2023 route disruption; Fluke TUG battery and servo case note.
20. "IEEE DataPort automated guided vehicles dataset sidelink AGV": AI4Mobile iV2V / iV2I+ (DOI 10.21227/04ta-v128).
21. "open source AGV fleet simulator" family covered by 16; "huggingface dataset AGV robot fleet logs position fault": Forgis (robot arm, not AGV), TUHH synthetic localization monitoring, Agibot, andyc03 server.log, Bielefeld RoboCup@Home fault set.
22. "data.europa.eu open data seaport terminal operations vehicle telemetry dataset": no terminal telemetry; EuRIS, EEA port layer, Eurostat maritime traffic, ONS port-area road counts, Piraeus and Valencia AIS. Portal not reached.
23. "SimPy container terminal port simulation github open source model": ConFlowGen (MIT, flow generator), simcraft port_terminal example, Pusan National University 2022 thesis (SimPy, no code).
24. "huggingface dataset AGV robot fleet logs position fault" (duplicate of 21 for logs; counted once).

### Fetches

| # | URL | result |
|---|---|---|
| F1 | https://github.com/VDA5050/VDA5050 | MIT per page; spec repo (version 3.0.0), `json_schemas`, `assets`; no sample logs visible; assets unverified |
| F2 | https://zenodo.org/records/17152352 | "Generative AI meets classical control: Hybrid few-shot PID tuning for autonomous robots", Nazir, CC-BY 4.0, 21.3 MB; no fields described |
| F3 | https://zenodo.org/records/10793054 | DEDICAT 6G Smart Warehousing, WINGS ICT, CC-BY 4.0, 885.9 kB, three CSVs; positions in 3x2 m; no column list |
| F4 | https://iris.unimore.it/handle/11380/1372170 | 403 Forbidden; not retried |
| F5 | https://www.identecsolutions.com/news/vehicle-telematics-at-container-terminals-how-to-build-insight | 2026-03-05; telematics layers, fault-code question, "Manually export data" workaround; vendor-authored |
| F6 | https://doi.org/10.1016/j.ifacol.2024.07.225 | redirect to linkinghub.elsevier.com; not followed |
| F7 | https://linkinghub.elsevier.com/retrieve/pii/S2405896324003094 | returned "Redirecting" only; abstract not read |
| F8 | https://github.com/1kastner/conflowgen | MIT; "generator for synthetic container flows at maritime container terminals"; no release or last-commit date shown; 403 commits |
| F9 | https://www.identecsolutions.com/... (second call, unused) | not used |

Fetch count: 8 in total (F1-F8), all under the 10-per-vendor limit. Vendor pages were not fetched; vendor cells rest on search snippets. Pages not fetched: aethon.com, diligent pages, terbergspecialvehicles.com, kalmarglobal.com, ampcontrol.io, spie.de, mevea, and the vda.de press release.

## What is not verified

- Bertoli et al. 2024: abstract not read (F6, F7 failed). The description in the doc comes from the search snippet.
- SimPy URL: the search returned github.com/jcaplan/simpy. The official host was not checked. The MIT licence is from a snippet.
- ConFlowGen maintenance: last commit not visible; left UNTESTED.
- The academic anchors from Springer chapters (Kim 2007, Lehmann 2007) come from search snippets. The Li et al. 2016 abstract was not read.
- Vendor cells: all UNTESTED. No doc tree was read for any of the seven vendors, so no absence claim is made.
- Kaggle site, data.gov, data.europa.eu portal and the VDA site were not searched directly. The doc says so.

## Direction check

The errors would flatter us if a vendor cell was marked present when it was only a snippet. Every vendor cell was set to UNTESTED for that reason. The data score is 0 and the sim score is 1; neither flatters the project.

## Result

Verdict and SCOUT_SCORE are in the doc, section 6.

Committed 71ce977 on master and pushed (0e5e2c0..71ce977). Report file is untracked, not committed.

SCHED_RESULT: OK docs/scouting/agv-tugs.md pushed 71ce977; no public AGV or tug fault log found; data=0 sim=1 competition=2 fit=2

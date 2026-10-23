# Scout report: mining haul-truck and construction-machinery fleets (2026-10-19)

Doc: `docs/scouting/mining-construction.md`. Tools: WebSearch (standard mode, all) and WebFetch only; no browser.
Budget: 75 min. Rules: `outward-claim-discipline` (rank A-F, URL + verified@, absence only after the
doc tree).

## Scope limits and failures

- Fetch failures: aemp.org/page/Publications (403); road-analysis-control (cat.com, timeout); cat.com fleet page (timeout
  on second try); digital.cat.com/node/3541 (403); Komatsu DISPATCH case study read but the Komatsu Roadways page only via
  the Komatsu "modular" page; komatsu.com/en-us case study returned a 2024 repost.
- Zenodo search page (HTML) rendered no results; the JSON API returned 17 visible hits, total not read.
- Kaggle search page rendered only its header (JavaScript); no results read. data.europa.eu rendered no list.
- The Nguyen and Hegarty-Cremer WSC 2021 PDF is compressed; WebFetch could not read its text.
- Vendor doc trees were not reached for any vendor. Caterpillar's and Komatsu's product pages are marketing or dealer
  copy. Trimble's help is a single topic. No absence claim is written as `not found in docs (A)`.
- Hexagon: no MineOS page found; cells rely on press (2017 release) and a CAS Insights article snippet.

## Search log (query -> URLs returned / read, result)

Dataset and log searches (WebSearch):
1. "open pit haul truck dispatch dataset public telemetry delay reasons zenodo kaggle" -> no dataset; patents, UMaT
   thesis (ir.umat.edu.gh), Peruvian thesis (cybertesis.uni.edu.pe), Scribd dispatch deck. No dataset.
2. "AEMP 2.0 telematics open source implementation machine data logs github" -> vendor pages (volvoce.com, autopi.io,
   oemoffhighway.com, verizonconnect.com, hcss.com); no open implementation.
3. "ISO 15143-3 AEMP telematics standard specification official page" -> aem.org/standards/iso15143/3 (read), aemp.org
   Publications (403), afnor boutique (XP ISO/TS 15143-3), dps.gov.al (ISO/CD TS 15143-3 entry, May 2026).
4. "open-source open pit mine simulator haul trucks python fleet simulation" -> arxiv.org/abs/2404.00622 (read),
   github.com/370025263/openmines (read), repositorio.udec.cl (Python/SimPy haul sim, code unconfirmed), research.buaa.edu.cn
   AnyPit (no licence seen), pretalx euroscipy 2022 talk.
5. "construction machinery telematics dataset public fault codes GPS open data" -> standard-body and vendor blogs; no dataset.
6. "haul truck fault location hotspot analysis open-pit mine journal paper" -> Satbayev University papers (bow-tie safety),
   Journal of Mining Institute traction drive paper, USPTO patent 10210677; no fault-hotspot paper.
7. "kaggle dataset mining haul truck cycle GPS" -> arxiv 2206.13936 (read), Mining Magazine 2017, APCOM 2021 Jigsaw slides,
   AVA Load & Haul, DT-CARGO (on-road, not mining). No Kaggle dataset.
8. "zenodo open-pit mine dataset truck GPS positions dataset" -> AutoMine (uic repository record, DOI 10.1002/rob.22469),
   ieee-dataport 4D mmWave (DOI 10.21227/g7ga-4z96), arXiv 2206.13936. No GPS truck dataset.
9. "Modular Mining DISPATCH system delay reason codes haul road congestion map documentation" -> komatsu.com smart-mining
   and case studies, Scribd deck, Grib case study; no reason-code documentation.
10. "Caterpillar MineStar Fleet Komatsu FrontRunner dispatch road condition hotspot analytics" -> cat.com RAC page (snippet),
    cat.com fleet page (snippet), Finning Health brochure (snippet). No FrontRunner material.
11. "spatial analysis of truck delays open pit haul road segments queue location paper" -> Queen's thesis (read), WSC 2021
    (unreadable PDF), koreascience GIS haul-route paper (snippet), USPTO 12373751.
12. "Wenco Hexagon Trimble VisionLink construction fleet location fault analytics documentation" -> help.fieldsystems.trimble
    (read), cat.com VisionLink pages (snippet), no Wenco or Hexagon docs.
13. "kaggle dataset mining haul truck cycle GPS" (see 7); "huggingface dataset open pit mine haul truck telemetry" -> arXiv
    2506.04296 (snippet: commercial HxGN MineOperate data), IEEE DataPort open-pit energy dataset (no telemetry).
14. "Wenco Insight dispatch mining fleet management features help center" -> engineeringnews (2016), im-mining and hitachi
    (2018 press), Electra Mining exhibitor profile (snippet). No help center.
15. "Hexagon HxGN MineOS dispatch haul road hazard map analytics" -> mining-technology and globalminingreview (2017 HxGN
    Dynamic Haulage, press), geomechanics.io CAS Insights (snippet). No MineOS page.
16. "Trackunit Manager support documentation fault codes location history geofence" -> help.trackunit.com article 150261
    (read, both versions), community.trackunit.com (snippet), Trackunit user-guide PDF (2013, TOC only).
17. "Volvo CareTrack construction fleet fault code location documentation" -> Motive and Samsara marketplace listings
    (snippet), Off-Highway CareTrack article (snippet), Volvo 2019 release (ActiveCare, snippet).
18. "construction equipment fault prediction telematics CAN bus hotspot location spatial analysis paper" -> Politecnico di
    Torino repository (snippet), UBC 2015 thesis (snippet), patents (fleet-level fault-code mapping, US 12462623 snippet).
19. "mining haul truck breakdown prediction onboard telemetry machine learning paper IEEE 2023 2024" -> arXiv 2506.04296
    (snippet), Pythian/Teck case (vendor), C3 AI and Unikie (vendor).
20. "open pit haul road congestion truck speed loss location hotspot GPS analysis journal article mining" -> Haul Road
    Explorer (product page, snippet), Cascadia press release (snippet), U Chile congestion thesis (snippet), Danish
    emerging hot spot paper (vbn.aau.dk, road freight, snippet).
21. "heavy equipment excavator dump truck fault clustering spatial location telematics study 2022 2023 2024 journal" ->
    US 12462623 (patent, snippet), US 12429865 (patent, snippet), Applied Sciences Aug 2024 on-road truck failure (snippet,
    doaj.org / mdpi.com).
22. "SUMO Eclipse traffic simulator license EPL-2.0 github eclipse-sumo TraCI Python" -> pypi traci (snippet), eclipse.dev
    (read for licence in a separate fetch), helmholtz software (snippet).
23. "AEMP telematics API 2.0 swagger open source github mixed fleet client sample" -> volvoce AEMP 2.0 page, developer
    portal (snippet), DPL Wireless docs (snippet), Dynapac manual (snippet), Caterpillar digital.cat.com (snippet),
    NMFTA open telematics (freight, not AEMP; snippet).
24. "AutoMine multimodal dataset open-pit mining Journal of Field Robotics 2025 download" -> CVPR 2022 AutoMine paper
    (snippet), repository record (snippet), no 2025 download link.
25. "huggingface dataset open pit mine haul truck telemetry" -> see 13.

Direct fetches (WebFetch), with result:
- github.com/370025263/openmines -> MIT label; Python gym env API; no fault-injection API; no commit dates; 56 stars (search
  listing).
- arxiv.org/abs/2404.00622 -> OpenMines, 31 Mar 2024, open source, probabilistic user-defined events.
- aem.org/standards/iso15143/3 -> ISO/TS 15143-3 title, JCMA maintains, scope sentence, status not stated.
- aemp.org/page/Publications -> 403.
- cat.com road-analysis-control -> timeout.
- komatsu.com case study (2024 repost) -> DISPATCH idle-time figures; no delay, reason-code, export or forecast.
- komatsu.com/en-br/technology/smart-mining/modular -> Replenish, Look Ahead, Roadways (hazards and congestion), Adapt,
  portal list incl. APIs.
- sumo.dlr.de Traffic_Lights -> TraCI traffic-light control only; licence not shown.
- arxiv.org/abs/2206.13936 -> Seiler, GPS of haul trucks, no data or code release.
- queensu.scholaris.ca Chapman thesis -> 2012, Goldstrike, variability from topography and intersections; PDF 18.49 MB.
- informs-sim.org/wsc21papers/060.pdf -> unreadable (FlateDecode); metadata only.
- zenodo.org/records/5789951 -> Mine Haul Truck Rear Dump Profiles, CC BY 4.0, 419 MB DWG, no location or time fields.
- zenodo.org/api/records?q=... -> 17 visible records, none telemetry; total not shown.
- zenodo.org/search (HTML) -> no results rendered.
- data.europa.eu search -> no results rendered.
- catalog.data.gov/dataset?q=haul+truck -> 20 of 586,937, none relevant.
- ieee-dataport.org search "haul truck" -> 0 matches (search box blank; low confidence).
- huggingface.co/datasets?search=haul+truck -> 0 results.
- kaggle.com/search?q=haul+truck -> header only (JavaScript).
- github.com/search (haul truck telematics repos) -> 0 results.
- github.com/search (open-pit truck simulator) -> 1.2k hits; openmines the only mine repo; rest are game mods.
- developer.volvoce.com/vce/cs/api-products -> AEMP 2.0 and Extended Asset API listed; access not stated.
- digital.cat.com/node/3541 -> 403.
- help.fieldsystems.trimble.com/tbc/10220.htm -> VisionLink help topic; "replaced by Trimble WorksOS"; no fault or heatmap.
- help.trackunit.com article 150261 -> geofence alarms replaced by Movement-Based Theft Alerts; no fault or heatmap.
- cat.com fleet page -> timeout.
- pypi.org/project/simpy -> 4.1.2, 24 May 2026, MIT.
- eclipse.dev/sumo -> EPL-2.0 and GPL-2.0 licence sentence; "Simulation of Urban MObility".

## Direction and contradiction check

- Dispatch "already publishes delay reasons" (the premise) is not supported by the one DISPATCH marketing page read. It
  is also not refuted: delay codes exist in the Tarkwa study (snippet). Recorded as unconfirmed.
- Komatsu's Roadways claim (routing from hazards and congestion) is marketing (B). It is the only avoid-zone-style "yes" in
  the table; it points toward presence, so it is flagged for re-verification.
- AEMP sources disagree on dates: AutoPi and FleetRabbit give v1.0 2010 / v2.0 2016 (secondary, C); another gives 2012.
  The doc does not use the dates.
- Fault-code counts differ across snippets (41 vs 42). The doc does not use the count.
- Chapman: the abstract names topography and intersections; no fault or stall data. Used only as a location-precedent.

## Open items for the operator

1. The only route to a real log is a paid API (Volvo CE AEMP 2.0 with subscription, or a fleet operator's own export).
   Decide whether an operator contact or a sandbox API account is worth pursuing.
2. An absence sweep needs vendor doc trees behind login (Komatsu portal, Caterpillar Knowledge Hub, Trimble WorksOS
   help). Not done in this scout; every absence is UNTESTED.
3. SUMO's TraCI edge-closure API was not read. If SUMO is preferred, read the TraCI change-edge pages next.

SCHED_RESULT: OK scout doc written (docs/scouting/mining-construction.md); data=0 sim=2 competition=1 fit=2; no open log, no vendor doc tree reached

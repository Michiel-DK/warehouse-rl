# wr-dev-lit-negative-results — query log (2026-10-21)

Docs job, opus. Output: warehouse-rl docs/LITERATURE.md Part 3, commit 1a054a0 (pushed to master). Three parallel research passes (WebSearch/WebFetch/curl APIs); Semantic Scholar 429 in all three; Google Scholar not tried. Main session re-checked against PDF/abstract text: Stephanedes 1992 3.5 FA/h; Pietrobon 2019 92%/80%; Jiang 2024 Table 3 (Random 100/200, City 1000); Yu & Wolf 4.4% + naive past-10 s baseline sentence; Han & Yu Table I n=40/160; Pittsburgh MAVG 1.31 and the 0-3% sentence.

Verdicts: Q1 not found; Q2 someone got the same (Pittsburgh MAVG, Hu 2018); Q3 consistent (near-zero same-planner gains at low N), underpowered.

## Q1 hidden blockage
## NOT FOUND (exact queries that returned nothing usable)
Target: blocked-edge / unmapped-obstacle inference from multi-robot (AGV/AMR) position or state traces alone, with detection rate + delay + false-alarm numbers.
- WebSearch(extended): "multi-robot fleet infer blocked edge unknown obstacle from robot delays lifelong MAPF roadmap update observed traversal times" -> only planner-side delay handling (Kita 2023, Zahradka 2025), no detection metrics
- WebSearch(extended): "warehouse AGV AMR fleet logs detect blocked aisle obstruction from robot position data anomaly detection evaluation" -> vendor blogs only (Pozyx RTLS, fuselab, tfsfventures); no evaluation
- arXiv API: all:AGV AND all:anomaly AND all:trajectory -> 1 hit, response not detection
- arXiv API: all:warehouse AND all:robots AND all:anomaly AND all:detection -> nothing relevant
- arXiv API: all:"blocked edges" AND all:robots -> OSCAR (onboard perception)
- arXiv API: all:fleet AND all:obstacle AND all:inference AND all:traces -> 0
- OpenAlex: "anomaly detection AGV trajectories warehouse" -> control/MARL/positioning papers only
- OpenAlex: "lifelong multi-agent path finding unknown obstacles detection" -> nothing on detection
- Semantic Scholar API: "road closure detection GPS trajectories" and "blocked edge detection multi-robot trajectories" -> HTTP 429 both times (API did NOT answer)
Also not found: a road-closure paper reporting recall + delay + FA/h together (T-Closure gives delay + volume, Pietrobon gives precision only); any study of DECREASE/absence detection on a grid with AMOC numbers. Spatial CUSUM and ETAS: one OpenAlex query each ("Rogerson spatial CUSUM surveillance detection time" -> Rogerson-style space-time surveillance papers, CSDA 2008 'Surveillance to detect emerging space-time clusters', none read; "ETAS seismicity rate change detection anomaly" -> 'Detecting misfits of the ETAS for seismicity anomalies' 2012, EPSL 2026 nonstationary ETAS test, none read). No rows added: metadata only (M), no numbers extracted.


## QUERY LOG
- WebSearch: road closure detection from GPS probe vehicle trajectories detection rate false alarm -> 9 USPTO patents (HERE/TomTom), no numbers
- Semantic Scholar API: /paper/search?query=road+closure+detection+GPS+trajectories -> HTTP 429 Too Many Requests (no answer)
- OpenAlex: "road closure detection GPS trajectories" -> T-Closure KDD 2023, Sensors 2017 collaborative path inference, others
- OpenAlex: "crowd sensing of traffic anomalies" -> Pan et al 2013 SIGSPATIAL (377 cites)
- OpenAlex: "inferring the root cause of anomalies trajectories" -> not Chawla 2012 directly; Access 2019 root cause
- WebSearch: "Understanding the Semantics of GPS-based Trajectories for Road Closure Detection" KDD 2023 -> aminer, unpaywall, no numbers
- ACM DL fetch for T-Closure -> 403 (WebFetch), HTML not PDF (curl)
- arXiv API: all:"road closure" (20) -> mostly irrelevant; "Road Network Fusion for Incremental Map Updates" 1802.02351, "Commercial Vehicle Detouring Patterns ... Probe Trajectory" 2407.17319
- WebSearch(extended): detecting road closures from floating car data precision recall detection time -> Pietrobon 2019 TSAS; lane-closure CV data 2025; Wuhan lane change detection; Dutch AID FCD (ResearchGate 321752923)
- OpenAlex+Crossref: doi 10.1145/3325912 -> abstract, closed access
- WebSearch: Pietrobon ... pdf -> no PDF; HERE patents
- WebFetch: patents.google.com US11270578 -> Poisson model text, no eval numbers
- WebSearch(extended): California algorithm McMaster incident detection comparison DR FAR MTTD table -> TTI 2917-1F, TRR 1360 Stephanedes 1992, Caltrans CA18-2531, MDPI 2022 systematic review, PMC9735737 V2I I-64
- curl+pdftotext: TTI 2917-1F and TRR 1360-009 full text OK
- WebFetch PMC9735737 -> Zhang & Kianfar 2022 numbers
- WebSearch: incident detection using probe vehicles travel time DR FAR MTTD ADVANCE Sethi -> Sethi 1995 TR-C (TRID 425502), Cheu 2002 MOSES, Li & McDonald 2005, Houston cell-phone probes TTI, ITS KRS 2014-b00962 (75% DR, 26% FAR arterial, snippet only)
- WebFetch swov.nl -> Cloudflare block; TRID 731882 -> MOSES abstract
- OpenAlex: motorway incident detection probe vehicles Li McDonald -> Asakura 2015, Ushiki 2014, ElSahly 2022 review; ScienceDirect 403
- WebSearch(extended): multi-robot fleet infer blocked edge unknown obstacle from robot delays lifelong MAPF roadmap update observed traversal times -> Kita 2023, Zahradka 2025, MDPI Sensors 26(13) 4139 2026 (robots detect obstacles onboard), Persistent and Robust Execution of MAPF Schedules in Warehouses (Honig 2019); none infer blockage from traces with metrics
- arXiv API: all:AGV AND anomaly AND trajectory -> 1 hit (dead zones 2610.08524)
- arXiv API: all:warehouse AND robots AND anomaly AND detection -> 3 irrelevant
- arXiv API: all:"blocked edges" AND robots -> OSCAR 2606.00990
- arXiv API: all:fleet AND obstacle AND inference AND traces -> 0 hits
- OpenAlex doi 10.1145/2525314.2525343 -> Pan 2013 abstract, closed
- OpenAlex: "inferring the root cause of anomalies Chawla Zheng" -> did not surface Chawla 2012 KDD record
- OpenAlex: road network change detection floating car data -> JNW 2012 (jnw.7.7.1063), Telecom Syst 2016
- OpenAlex: CrowdAtlas map update GPS trajectories -> CrowdAtlas MobiSys 2013, IJGI 2019 additive changes
- OpenAlex: detecting road network changes GPS traces map update closed roads -> map inference papers (additive, not closure)
- WebSearch: Pan Zheng Wilkie Shahabi pdf -> MSR PDF; curl got HTML, WebFetch saved binary -> pdftotext OK
- WebSearch: road closure detection driver GPS traces Grab/Uber/Lyft/Google blog -> no industry blog with numbers; TomTom patent "available for analysis within ... 3 minutes"; INRIX blog (human validation of closures)
- WebSearch: Chawla Zheng Hu 2012 ICDM -> MSR page, HBKU; also Pang 2011
- OpenAlex: Pang 2011 ADMA, Pang 2013 DKE, Chawla 2012 ICDM, Kuang 2015 Harbin taxi PCA
- WebSearch: Pang Chawla LRT grid pdf -> MSR PDF DKE-ADMA-1-num20-20v3.pdf; WebFetch saved binary, pdftotext OK
- WebSearch: Neill expectation-based scan days to detect FP per month -> sss-kdd05.pdf, ijhg09.pdf, thesis, robust EB scan
- OpenAlex: spatial CUSUM grid Poisson ARL -> surveillance R package, Spatio-temporal health surveillance 2023, Kuwait V2I corridor 2026 (Sensors 26(17) 5368)
- OpenAlex: prospective space-time scan timeliness -> Unkel 2012 JRSS-A review, Neill 2009 MBSS, Sonesson & Bock 2003 review, Neill 2009 IJHG comparison
- OpenAlex: detecting decreases counts spatial surveillance absence -> zero-inflated Poisson scan 2014; nothing on decrease detection with delay
- curl: Neill kdd05/ijhg09 PDFs OK
- WebSearch: road closure detection driver GPS traces Grab/Uber/Lyft/Google blog -> none
- OpenAlex: "traffic incident detection probe vehicle trajectories false alarm rate time to detect" -> Asakura 2015, ElSahly 2022, Duan 2024 arXiv
- OpenAlex: "Waze road closure detection crowdsourced" -> Sybil devices in crowdsourced mapping (MobiSys 2016), flooding; no closure detection eval
- arXiv API id_list 2412.10892 -> abstract, no numbers

## SUMMARY (5 lines)
1. Not tried, as far as these queries reach: no paper infers planner-blind blocked cells or edges from robot fleet traces and scores detection rate, delay and FA/h. Adjacent robotics work either senses the obstacle onboard (OSCAR 2026) or is told where the anomaly is (AGV dead zones 2026).
2. Closest analogue is road closures from probe traces. Pietrobon et al. 2019 (HERE, ACM TSAS) run a per-segment Poisson likelihood test against a historical model, which is our CUSUM's twin, but report only precision (92% on low-volume roads, 80% overall): no recall, delay or FA/h. T-Closure (KDD 2023, UESTC + Didi Chuxing per OpenAlex; supervised, uses planned routes) reports "7000+ closure events monthly, with a delay within 1.5 hours" online.
3. Loop-detector AID: California #7/#8 give DR 67-68%, off-line FAR 0.134-0.177% of station-intervals and MTTD 2.9-3.0 min. McMaster (QEW on-line test) gives DR 68%, FAR 0.0008%, which is "20 false alarms over 64 days", and 1.4 min; I derived about 0.013 FA/h for the whole test section, assuming round-the-clock monitoring. Stephanedes 1992 converts California #7 at 50% DR to about 3.5 FA/h for 14 stations, and their own filter to 1.5 FA/h. Probe-based AID in simulation (Zhang & Kianfar 2022) reaches 100% DR on 10 incidents, but its FAR is a % of intervals. All of these detect lane-scale incidents, a much stronger signal than one blind cell.
4. Pan 2013 (Beijing taxis) gets 86.7% recall vs 46.7% for a flow/PCA baseline by tracking routing shifts; it reports no precision or FA by design. Neill 2005 misses outbreaks with fewer than 5 cases at 1 FP/month. Our 44-48 missed cells may sit below the same signal floor, but that is a hypothesis: count the stall events per missed cell to test it.
5. Verdict: no one beats or matches us at comparable FA, because no one reports FA in a comparable unit. Cite Pietrobon 2019 as the method twin (precision only) and Stephanedes 1992 / McMaster for the FA/h scale. The literature points to routing-shift and inter-arrival-gap signals (Pan 2013; HERE/TomTom patents), not stall counts.

## Q2 map vs persistence
### Absences (exact queries)
- WebSearch: "warehouse AGV congestion prediction hotspot forecast baseline historical average robot traffic" -> only Amazon sim paper has a persistence baseline.
- WebSearch: "AMR fleet real log deadlock congestion hotspot prediction "persistence baseline" OR "naive baseline" multi-robot warehouse" -> nothing on real logs.
- arXiv API: all:warehouse AND all:robot AND all:congestion AND all:prediction -> 1 irrelevant hit.
- WebSearch: "NIJ crime forecasting challenge results analysis "naive" OR "baseline" PAI PEI entries compared simple hot spot prior period" -> no NIJ naive benchmark found.
- Mohler-Porter "a remark on..." NOT searched (budget).
- Semantic Scholar API: one call, HTTP 429, did not answer.

## Query log
- WebSearch | NIJ Real-Time Crime Forecasting Challenge naive baseline previous period hotspots PAI comparison | NIJ pages, Flaxman arXiv 1801.02858, Amstat magazine; no baseline numbers in snippets
- Semantic Scholar API (curl graph/v1/paper/search "crime hotspot forecast naive baseline prior period") | HTTP 429 Too Many Requests -- DID NOT ANSWER (one attempt, as instructed)
- curl arXiv API | all:"rotational grid" AND all:crime | 0 hits
- WebSearch | Mohler Porter "Rotational grid, PAI-maximizing crime forecasts" naive | OJP record + PDF 251203 (fetched, no baseline)
- WebSearch | Lee Eck O NIJ crime forecasting challenge "theory-driven algorithm" hot spot forecasting Police Quarterly | OJP report 251179 (downloaded, read)
- WebSearch | crime forecasting machine learning "prior year" OR "previous year" counts baseline hot spots barely outperforms | Pittsburgh arXiv 2011.06019 (read: MAVG best), Liu&Brown 2003 IJF snippet, IEEE Access LSTM, RIT thesis
- WebSearch | Liu Brown 2003 "Criminal incident prediction using a point-pattern-based density model" ... | RePEc (no abstract), IAOR, NIJ report 197634 (downloaded)
- WebSearch | Gorr Olligschlaeger Thompson 2003 "Short-term forecasting of crime" naive random walk forecast accuracy | NIJ 195168 (read), 195167 (ncjrs URL returned non-PDF), Cohen&Gorr 2005 NIJ snippet: naive and leading-indicator worst
- WebSearch | Adepeju Rosser Cheng 2016 novel evaluation metrics sparse spatio-temporal point process hotspot predictions crime case study prospective hotspot | UCL eprint (PDF URL returned HTML, not read), arXiv 2006.00272 Hu et al. (read)
- WebSearch | traffic accident risk prediction deep learning "historical average" baseline grid city Hetero-ConvLSTM results | Hetero-ConvLSTM PDF (read), HintNet arXiv 2203.03100 (read), LISA arXiv 2412.15365 (not read)
- WebSearch | crash hotspot identification site consistency test empirical Bayes versus accident frequency ranking before-after periods Cheng Washington | Khattak 2024 Sustainability (UHasselt PDF -> HTML then 503), USQ Toowoomba 2024 (PDF -> HTML), SWOV record of Cheng&Washington 2005
- WebSearch | "site consistency test" empirical Bayes "crash frequency" hotspot identification results table subsequent period crashes | same set + Newcastle 2019 TRB (crash-rate hotspots unreliable), PacTrans report
- OpenAlex API | search "new criteria for evaluating methods of identifying hot spots" | ANSWERED: 10.3141/2083-09 closed; abstract retrieved
- OpenAlex API | search Montella / Cheng 2005 | returned wrong paper (2014 urban expressway note)
- WebSearch | Montella 2010 "A comparative analysis of hotspot identification methods" ... | metadata + snippet conclusion, no numbers
- WebSearch | Zechar 2013 Regional Earthquake Likelihood Models I first-order results relative intensity smoothed seismicity T-test information gain | SCEC page (abstract read), USGS 2010 first results, Zenodo dataset
- WebSearch | prospective CSEP evaluation hybrid earthquake forecast outperforms smoothed seismicity significant information gain T-test Bayona Strader GEAR1 | EGU2017/2018 abstracts, GFZ PDF (returned HTML), Seismic Record 2023 (DOAJ 403), SCEC nodes
- WebFetch | EGU2018-9733 pdf | binary; extracted with pdftotext -> abstract read
- WebSearch | Mignan Broccardo 2019 "One neuron versus deep learning in aftershock prediction" Nature baseline AUC | arXiv 1904.01983 (abstract via arXiv API, verified)
- WebSearch | warehouse AGV congestion prediction hotspot forecast baseline historical average robot traffic | Amazon Yu&Wolf (PDF read: Hist base = past-10s persistence), Chalmers GNN thesis, Sabattini 2016, IJSIM 2025
- WebSearch | AMR fleet real log deadlock congestion hotspot prediction "persistence baseline" OR "naive baseline" multi-robot warehouse | 2 USPTO patents (road), WSC22 Kim&Choe (read: no naive baseline), urban congestion PMC, SESAR -- no warehouse forecast vs persistence on real logs
- WebSearch | Kounadi 2020 systematic review spatial crime forecasting Crime Science baseline models comparison naive | PMC7319308 (read via WebFetch, 2 offsets)
- WebSearch | Rosser Davies Bowers Johnson Cheng 2017 "Predictive crime mapping: arbitrary grids or street networks" network STKDE prospective hotspot hit rate | PMC6979510 (read)
- arXiv API | all:warehouse AND all:robot AND all:congestion AND all:prediction | totalResults=1 ("Improved Swarm Engineering: Aligning Intuition and Analysis", 2020) -- irrelevant; ABSENCE
- WebSearch | NIJ crime forecasting challenge results analysis "naive" OR "baseline" PAI PEI entries compared simple hot spot prior period | Flaxman (already cited, skipped), Conduent post-mortem NCJ 251464 (abstract: no naive comparison), Shreveport eval -- ABSENCE: no NIJ-published naive/previous-period benchmark score found
- (not run, budget) Mohler-Porter "a remark on ..." -- NOT SEARCHED; status unknown
# Q2 query log (service | query | rough result)
- WebSearch | NIJ Real-Time Crime Forecasting Challenge naive baseline previous period hotspots PAI comparison | NIJ pages, Flaxman arXiv 1801.02858, Amstat magazine; no baseline numbers in snippets
- Semantic Scholar API (curl graph/v1/paper/search "crime hotspot forecast naive baseline prior period") | HTTP 429 Too Many Requests -- DID NOT ANSWER (one attempt, as instructed)
- curl arXiv API | all:"rotational grid" AND all:crime | 0 hits
- WebSearch | Mohler Porter "Rotational grid, PAI-maximizing crime forecasts" naive | OJP record + PDF 251203 (fetched, no baseline)
- WebSearch | Lee Eck O NIJ crime forecasting challenge "theory-driven algorithm" hot spot forecasting Police Quarterly | OJP report 251179 (downloaded, read)
- WebSearch | crime forecasting machine learning "prior year" OR "previous year" counts baseline hot spots barely outperforms | Pittsburgh arXiv 2011.06019 (read: MAVG best), Liu&Brown 2003 IJF snippet, IEEE Access LSTM, RIT thesis
- WebSearch | Liu Brown 2003 "Criminal incident prediction using a point-pattern-based density model" ... | RePEc (no abstract), IAOR, NIJ report 197634 (downloaded)
- WebSearch | Gorr Olligschlaeger Thompson 2003 "Short-term forecasting of crime" naive random walk forecast accuracy | NIJ 195168 (read), 195167 (ncjrs URL returned non-PDF), Cohen&Gorr 2005 NIJ snippet: naive and leading-indicator worst
- WebSearch | Adepeju Rosser Cheng 2016 novel evaluation metrics sparse spatio-temporal point process hotspot predictions crime case study prospective hotspot | UCL eprint (PDF URL returned HTML, not read), arXiv 2006.00272 Hu et al. (read)
- WebSearch | traffic accident risk prediction deep learning "historical average" baseline grid city Hetero-ConvLSTM results | Hetero-ConvLSTM PDF (read), HintNet arXiv 2203.03100 (read), LISA arXiv 2412.15365 (not read)
- WebSearch | crash hotspot identification site consistency test empirical Bayes versus accident frequency ranking before-after periods Cheng Washington | Khattak 2024 Sustainability (UHasselt PDF -> HTML then 503), USQ Toowoomba 2024 (PDF -> HTML), SWOV record of Cheng&Washington 2005
- WebSearch | "site consistency test" empirical Bayes "crash frequency" hotspot identification results table subsequent period crashes | same set + Newcastle 2019 TRB (crash-rate hotspots unreliable), PacTrans report
- OpenAlex API | search "new criteria for evaluating methods of identifying hot spots" | ANSWERED: 10.3141/2083-09 closed; abstract retrieved
- OpenAlex API | search Montella / Cheng 2005 | returned wrong paper (2014 urban expressway note)
- WebSearch | Montella 2010 "A comparative analysis of hotspot identification methods" ... | metadata + snippet conclusion, no numbers
- WebSearch | Zechar 2013 Regional Earthquake Likelihood Models I first-order results relative intensity smoothed seismicity T-test information gain | SCEC page (abstract read), USGS 2010 first results, Zenodo dataset
- WebSearch | prospective CSEP evaluation hybrid earthquake forecast outperforms smoothed seismicity significant information gain T-test Bayona Strader GEAR1 | EGU2017/2018 abstracts, GFZ PDF (returned HTML), Seismic Record 2023 (DOAJ 403), SCEC nodes
- WebFetch | EGU2018-9733 pdf | binary; extracted with pdftotext -> abstract read
- WebSearch | Mignan Broccardo 2019 "One neuron versus deep learning in aftershock prediction" Nature baseline AUC | arXiv 1904.01983 (abstract via arXiv API, verified)
- WebSearch | warehouse AGV congestion prediction hotspot forecast baseline historical average robot traffic | Amazon Yu&Wolf (PDF read: Hist base = past-10s persistence), Chalmers GNN thesis, Sabattini 2016, IJSIM 2025
- WebSearch | AMR fleet real log deadlock congestion hotspot prediction "persistence baseline" OR "naive baseline" multi-robot warehouse | 2 USPTO patents (road), WSC22 Kim&Choe (read: no naive baseline), urban congestion PMC, SESAR -- no warehouse forecast vs persistence on real logs
- WebSearch | Kounadi 2020 systematic review spatial crime forecasting Crime Science baseline models comparison naive | PMC7319308 (read via WebFetch, 2 offsets)
- WebSearch | Rosser Davies Bowers Johnson Cheng 2017 "Predictive crime mapping: arbitrary grids or street networks" network STKDE prospective hotspot hit rate | PMC6979510 (read)
- arXiv API | all:warehouse AND all:robot AND all:congestion AND all:prediction | totalResults=1 ("Improved Swarm Engineering: Aligning Intuition and Analysis", 2020) -- irrelevant; ABSENCE
- WebSearch | NIJ crime forecasting challenge results analysis "naive" OR "baseline" PAI PEI entries compared simple hot spot prior period | Flaxman (already cited, skipped), Conduent post-mortem NCJ 251464 (abstract: no naive comparison), Shreveport eval -- ABSENCE: no NIJ-published naive/previous-period benchmark score found
- (not run, budget) Mohler-Porter "a remark on ..." -- NOT SEARCHED; status unknown

## Q3 routing feedback
1. WebFetch arxiv.org/html/2402.01446 (GGO) -> full text HTML, Tables 2/3 (2 fetches)
2. WebSearch(standard) "Chen Harabor Li Stuckey Traffic flow optimisation for lifelong MAPF arXiv" -> arXiv 2308.11234 + AAAI OJS
3. WebFetch arxiv.org/html/2308.11234v4 -> full text, Tables 1/2
4. WebSearch(standard) "Zang online guidance graph optimization lifelong MAPF AAAI 2025 arXiv" -> arXiv 2411.16506
5. Semantic Scholar API (curl graph/v1/paper/search "guidance graph lifelong multi-agent path finding") -> HTTP 429 Too Many Requests. NOT ANSWERED. Not retried (one try as instructed).
6. WebFetch arxiv.org/html/2411.16506v2 -> full text; throughput only in plots except Fig. 1 caption
7. WebFetch arxiv.org/abs/2005.07371 (RHCR) -> abstract; then curl arxiv PDF + pdftotext grep highway|guid|crisscross|weight -> no hits
8. WebSearch(standard) "Cohen Uras Koenig feasibility study using highways bounded-suboptimal MAPF experimental results" -> idm-lab socs15b.pdf, IJCAI 16/563, 16/435
9. curl idm-lab socs15b.pdf + ijcai.org 16/435 -> socs15b read; 16/435 turned out to be "Improved Solvers..." (wrong paper)
10. WebFetch arxiv.org/abs/2605.16855 -> metadata/abstract; WebFetch arxiv.org/html/2605.16855v1 -> full text
11. WebSearch(standard) "Jiang Zhang Veerapaneni Li Scaling Lifelong MAPF to More Realistic Settings guidance throughput arXiv" -> arXiv 2404.16162
12. WebFetch arxiv.org/html/2404.16162v1 -> Table 3 extracted (no/manual/auto guidance x PIBT/WPPL x density)
13. curl arxiv.org/pdf/2404.16162 + pdftotext -layout -> Table 3 verified; corrected WebFetch errors (steps, City/Game densities 2.1/6.4/9.3%, not 12.1/16.4/19.3%)
14. curl arxiv.org/pdf/2308.11234v5 + pdftotext -layout -> Tables 1/2 verified
15. curl arxiv.org/pdf/2402.01446 + pdftotext -layout -> Tables 2/3 + setup-10 text verified
16. local: .venv/bin/python gym.make(tarware-medium-8agvs-4pickers-globalobs-v1) -> grid (25,22), 160 shelves, 390 highway cells
17. WebSearch(standard) "congestion-aware AGV routing dynamic edge weights small fleet throughput improvement warehouse simulation 10 AGVs" -> Bartlett GT thesis, Oxford ORA AGV order picking, WSC22, arXiv 2504.01985; none with ~10-AGV routing gain
18. WebFetch repository.gatech.edu (Bartlett) -> 403; WebFetch hg.gatech.edu/node/315821 -> 403
19. WebFetch export.arxiv.org/abs/2504.01985 -> NAHACO, irrelevant (no throughput vs SP)
20. WebSearch(standard) "Congestion-aware dynamic routing in automated material handling systems Bartlett dissertation 4-6% travel time" -> snippets confirm 4-6%, C&IE 70:176-182
21. WebSearch(standard) "Han Yu Optimizing space utilization for more effective multi-robot path planning ICRA 2022 congestion SU-I throughput" -> arXiv 2109.04677
22. curl arxiv.org/pdf/2109.04677 + pdftotext -layout -> Table I throughput verified
23. WebSearch(standard) "Yu Wolf 2023 deep learning predict congestion delays lifelong MAPF throughput warehouse" -> amazon.science PDF "Congestion Prediction for Large Fleets of Mobile Robots"; also JAIR learning-guided PP, arXiv 2603.23838 (not read)
24. curl amazon.science PDF + pdftotext (layout + raw) -> Table II, baseline text, setup
Fix commit: 7888bb6 (NIJ sentence, Yu & Wolf caveat, road-safety label)

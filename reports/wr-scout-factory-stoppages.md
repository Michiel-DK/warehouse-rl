# wr-scout-factory-stoppages (2026-10-19)

Doc: `warehouse-rl/docs/scouting/factory-stoppages.md`, committed 3b182f1 and pushed to master.
Tools: WebSearch (standard mode) and WebFetch only. No browser. Dates are the day of the run, 2026-10-19.

## Search and fetch log

Each line: query or URL, then what came back. Rank is the source rank used in the doc.

### Datasets and logs
- WebSearch "Bosch production line performance dataset Kaggle station line identifiers": arxiv 1701.00705 (Mangal and Kumar); repo aakashveera/bosch-production-line-performance; repo joostgp/kaggle_bosch. Snippet: IDs like L3_S50_F4243; station counts 51 vs 52 disagree. D.
- WebSearch "open dataset machine downtime reasons alarm log production line stoppage zenodo": no Zenodo record; Springer s10845-022-01952-x (40M log entries, single machine, data availability unread); vendor product pages. No dataset.
- WebSearch "PHM data challenge manufacturing dataset alarm logs machine faults open download": IEEE DataPort node 2549 and open-access ALPI; PHM Society data challenge page; arXiv 2312.16810 (PHM review). Snippet only.
- WebSearch "MTConnect sample data open log github cppagent test streams Condition fault": mtconnect/ros_bridge; industrialmonitordirect.com blog (same article under ~10 country paths, unverified). No open log.
- WebSearch "SimPy open source manufacturing line simulation library machine breakdown failures": pypi maintsim, simantha, SimPy Machine Shop example, siamese-optimizer, ManPy. Snippets.
- WebSearch "Gymnasium reinforcement learning factory simulator open source job shop machine breakdown Python": job-shop-lib docs, Graph Matrix Job Shop Env, JSSEnv, arXiv 2601.09293 (action masking with machine failures). Snippets.
- WebFetch https://ieee-dataport.org/open-access/alarm-logs-packaging-industry-alpi: ALPI details (8.12 MB, 20 machines, 154 codes, fields, login needed, licence not stated). A.
- WebFetch https://www.kaggle.com/competitions/bosch-production-line-performance/data: login/error page, no content.
- WebFetch https://www.kaggle.com/competitions/bosch-production-line-performance: title only. Unverified.
- WebFetch https://arxiv.org/pdf/1701.00705: compressed PDF stream, unreadable. Chart names only (FeaturesbyStation, ErrorbyStation).
- WebFetch https://arxiv.org/abs/1701.00705: abstract read; no counts. A-.
- WebFetch https://github.com/mtconnect/ros_bridge: Apache-2.0 (copyright 2012 System Insights), 370 commits, no releases, no sample streams in visible folders. A.
- WebFetch https://github.com/mtconnect (org page): 15 of 80 repos listed, none named sample/data/stream except cstream and mtcstreamer; no open log.
- WebFetch https://api.github.com/orgs/mtconnect/repos?per_page=100: 20 repos returned with descriptions (cstream "multipart/x-replace streaming data sample in C"; ros_bridge "ROS Python Adapter and Ruby Robot Simulator"; verifier; cppagent). Truncated at 100k of 449k chars; no open log seen in the 20.
- WebFetch https://www.mtconnect.org/mtconnect-standard and https://www.mtconnect.org/: title only. Royalty status UNVERIFIED.
- WebSearch "stoppage ... downtime ... recurring stations" (general): Augury, Pareto guides (ifactoryapp, jitbase, teeptrak), Google Patents US5327349, Journal of Industrial Engineering and Management doi 10.3926/jiem.4347 (stamping line Weibull, by stop type), Epistemus (biblat, workstation stoppages). Snippets.
- WebFetch https://ifactoryapp.com/article/downtime-pareto-analysis-prioritize-failures: not fetched; the doc cites the vendor-guide statements (under-5-minute stops omitted; bottleneck weighting) from the snippet. D, unverified by fetch. (Note: the doc uses this URL for both claims.)
- WebSearch "alarm sequence analysis production line root cause... packaging": arXiv 2606.09892 (LMT), arXiv 2203.11321 (alarm RCA, Tennessee Eastman), Chalmers thesis (Volvo, internal), US10235631 patent, SEER. Snippets.
- WebSearch "zenodo dataset manufacturing machine alarm log station fault records CSV open access": Zenodo 5078737 (USN state logs), Padua 7071746 link, ALPI.
- WebFetch https://zenodo.org/record/5078737: USN Industry 4.0 Lab state logs, CC BY 4.0, sizes 6.0 kB and 6.0 MB (stated 1.1 GB total, inconsistent), no field list. A (record page).
- WebFetch https://zenodo.org/records/7071746: resolved to PIADE (DOI 10.5281/zenodo.7071747), CC BY 4.0, 61.0 MB CSV, 133 alarm types, 429,394 rows, equipment IDs. A.
- WebSearch "huggingface dataset industrial machine alarm logs production line failures station": pgurazada1/machine-failure-logs and machine-failure-mlops-demo-logs (file listings only, no card read). D, unread.
- WebFetch https://huggingface.co/datasets/pgurazada1/machine-failure-logs: not fetched; search listing only.

### Simulators
- WebFetch https://pypi.org/pypi/simpy/json: MIT, 4.1.2, uploaded 2026-05-24, source gitlab.com/team-simpy/simpy. A.
- WebFetch https://github.com/healthcare-simulation/simpy: 404 (wrong URL, not used).
- WebFetch https://pypi.org/project/maintsim/: license field empty, classifier MIT, 0.1.3, 2019-08-06, author Michael Hoffman. A.
- WebFetch https://pypi.org/pypi/maintsim/json: same (license field empty, classifier MIT, version 0.1.3, upload 2019-08-06). A.
- WebFetch https://github.com/m-hoff/maintsim: returned a Simantha README ("Simantha is a package for simulating discrete manufacturing systems") and LICENSE.txt "MIT-0"; 176 commits; repo identity unresolved (noted in doc).
- WebFetch https://pypi.org/project/simantha/: error page. UNVERIFIED.
- WebFetch https://pypi.org/project/job-shop-lib/: MIT, 1.7.2, uploaded 2026-10-08, feature list without failures, repo github.com/Pabloo22/job_shop_lib. A.

### Standards
- WebSearch "OPC UA for Machinery companion specification free download OPC Foundation": VDMA catalog pages (level-2-minimal category 3782490), VDW/VDMA 2020 press PDF (Part 1 free from 25 Sept 2020; press, C), VDMA 40001-1:2026-01 listed. Alarm/state part not identified.

### Vendors
- WebSearch "MachineMetrics downtime reason codes andon documentation help center": support articles 360056036474 and 360033266554, docs downtime-quality-guide, support-hub automatic-downtime-categorization-guide. Snippets.
- WebFetch https://docs.machinemetrics.com/docs/product-guides/downtime-quality-guide: empty content.
- WebFetch https://support.machinemetrics.com/hc/en-us/articles/360033266554-Downtime-Report: HTTP 403.
- WebSearch "Senseye predictive maintenance documentation downtime reasons heatmap": Siemens TCOD 2024 PDF, Verdantix, siemens.com/au senseye page, rfp.wiki review, siemens.com/senseye (B "forecasts machine failure and prioritizes risks", snippet).
- WebFetch https://www.siemens.com/en-us/products/senseye/: HTTP 404.
- WebFetch https://siemens.com/au/en/products/services/industry/senseye-predictive-maintenance.html: marketing, no documentation links, no location or grading. B.
- WebSearch "Senseye documentation help center downtime reasons asset health dashboard user guide": no Senseye help centre found; MaintainX and Oracle/MindSphere results are other vendors and not used.
- WebFetch https://www.sightmachine.com/platform/: HTTP 404.
- WebFetch https://www.sightmachine.com/: "Connect every OT and IT system ..."; no docs links. B.
- WebFetch https://www.tulip.co/platform/: connectivity text; footer doc links listed (support.tulip.co, developer, library). B.
- WebFetch https://support.tulip.co/: KB index sections (Get Started, Build, Deploy and Manage, Developer Tools, IT and Technical Docs, Use Cases, University, Library). Index only.
- WebFetch https://www.litmus.io/: "Detect equipment failures before they occur."; footer links docs.litmus.io, support.litmus.io. B.
- WebFetch https://docs.litmus.io: index sections Platform / Build and automate / Get help; no matching titles. Index only.
- WebSearch "Augury OR Oden OR Sight Machine stoppage ... accuracy": Augury ROI page (99.9% diagnostic accuracy, B), others no results. Oden not found.

### Academic
- WebSearch "Bosch production line dataset station failure hotspot analysis paper journal station-level failure rate": arXiv 1701.00705, FedCSIS annals vol 35 paper 677 (52 stations, 4 lines, AUC up to 0.997; snippet), UAB record. Snippets.
- WebSearch "spatial hotspot analysis of machine failures on shop floor stoppages location recurring journal article": arXiv 0904.4608 (Laxman et al.), JIEM 2023 stamping line (by stop type), Epistemus station stoppages, Getis-Ord crash hotspot papers (road domain, not factory). Snippets.
- WebFetch https://arxiv.org/abs/0904.4608: Laxman, Shadid, Sastry, Unnikrishnan; arXiv 2009; engine assembly plant fault logs. A-.
- WebFetch https://arxiv.org/abs/2606.09892: Xiao et al., submitted 2026-06-03; simulation studies; no dataset link. A-.
- WebFetch https://biblat.unam.mx/... (Epistemus paper): verification screen, not read.

## Counts
- WebFetch calls: about 40 (exact count not kept; includes repeated Kaggle, MTConnect and maintsim URLs). WebSearch calls: about 16 (general and vendor queries; one returned no usable results).
- Per vendor (cap of 10 fetches each): MachineMetrics 2, Senseye 2, Sight Machine 2, Tulip 2, Litmus 1 (docs index 1), Augury 0 fetches (snippets only).

## What was not done, and why
- Zenodo, Kaggle datasets, Hugging Face, data.gov, data.europa.eu and IEEE DataPort own search were not run as direct queries; only the web index and the single records above were used. "None found" in the doc is limited to these searches.
- Kaggle's Bosch page and the Bosch PDF could not be read; Bosch file list, size and licence are UNVERIFIED.
- MTConnect's own site returned title only; the standard's royalty status and version are UNVERIFIED.
- The VDMA OPC UA catalog pages were not fetched; "free" rests on a 2020 press release (C).
- Vendor docs were walled or missing (MachineMetrics docs 403 or empty, Siemens, Sight Machine root and platform 404s), so all vendor capability cells are UNTESTED.
- Academic: Epistemus and JIEM 2023 were not read in full; both were kept out of the anchor list.
- The ifactoryapp Pareto article is cited for two claims from its search snippet; the page was not fetched.

SCHED_RESULT: OK docs/scouting/factory-stoppages.md 3b182f1 pushed; 6 vendors (all UNTESTED except 2 rank-B log upload cells); 3 academic anchors (arXiv preprints); data gaps listed in doc

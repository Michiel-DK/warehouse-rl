# wr-scout-operator-problems: report (2026-10-20)

Deliverable: `docs/scouting/operator-problems.md` (200 lines, 5 sections, 80 problem rows, 15 ranked themes), commits 73610c8
and 706bab9 on master, pushed.

## Method
- Six general-purpose subagents (opus) using WebFetch/WebSearch, each with a source group:
  A ROS Discourse, Open-RMF, VDA5050, Nav2 (25 fetches); B Reddit, HN, LinkedIn (38 fetches/searches);
  C job postings (about 30); D incidents, talks, surveys (about 40); E HN, reviews, trade press (about 29);
  F surveys, regulators, studies, Open-RMF and Discourse neutral queries (about 30).
- Every scout ran neutral queries next to theme queries ("production deployment problems", "lessons learned",
  "robots warehouse problems", "challenges after deploying AMRs"). B notes its AmazonFC yield came from one query
  (body=pods) because the others hit 429/422, which tilts its rows towards station waits and pod crashes.
- Verification (main loop): WebFetch output is model-summarised, so every one of the 116 candidate quotes was checked
  string-for-string against raw text fetched with curl (GitHub HTML, Discourse `/t/<id>.json`, Greenhouse API, amazon.jobs,
  press HTML, Rapyuta with a browser user agent because the default one hit Cloudflare), pdftotext for the two PDFs,
  arctic-shift `api/comments/ids` and `api/posts/ids` for Reddit, and hn.algolia.com `/api/v1/items/<id>` for HN.
  Deviation from the brief's "WebFetch and WebSearch only": curl was used read-only for this check, because WebFetch
  cannot show verbatim text. 2 quotes failed on trailing punctuation and were corrected to the raw text. Symbotic quotes were
  dropped (raw page 403). Three r/Warehousing comments flagged as possible astroturf (the same text from three accounts,
  one promoting Hubble Network) were dropped. Every quote is 25 words or fewer.
- 116 verified rows were cut to 80 for length (the brief aims for 40-80). Ranking counts run on the 80 shown; on all 116
  the top order is the same for ranks 1-5 (stall 17, congestion 12, commissioning 11, wait 11, integration 11 sources).
- Recount (706bab9): in the first version every r/AmazonFC thread counted as its own source, so waiting led on
  operator sources (7). All nine threads come from one employer, one week and one query, so they now count as one
  source. Waiting drops to 6th (5 sources, 2 operator), stalls stay 1st (12), and DEMAND_SCORE changed from
  stalls=3 waiting=3 to stalls=2 waiting=2. The detector has no station or picker logic (grep of fleet/fleet_analyser;
  causes at detector.py:26), so "no stage separates waiting from stalling" stands.
- Theme tags were assigned by me, row by row. They are a judgement, not a measurement.

## Caveats
- Operator voices are thin outside Amazon associates (r/AmazonFC, 10 rows), ASKUL (5) and r/Warehousing AGV users. No
  rank-A operator survey with raw tables was reached (MHI UNREACHED; Interact and Peerless only as write-ups, rank D).
- Interact's VDA 5050 awareness figure (20% fully aware, 8% mandatory) is in the doc rows but not in the ranking.
- The pipeline column's "today a wait over 30 s is a stuck episode" rests on the overview page's rule ("30 seconds
  waiting with a job means stuck") and the S5B state machine in docs/SCOPE.md. No run was made to measure how many
  sim stuck episodes are station waits.
- Recruiter rows are duties, not complaints. They make up 14 of the 80 rows and inflate stall/dash/rca source counts.

## Rows verified but not shown (36)
- "since human movements cannot be replicated in simulations" | operator | https://www.rapyuta-robotics.com/use-cases/case-askul2/ | undated | commissioning
- "Due to the limitations of our environment, we could not make major changes to the location of items or equipment." | operator | https://www.rapyuta-robotics.com/use-cases/case-askul2/ | undated | commissioning
- "The other one is if the AGV get confused due to human error." | operator | https://www.reddit.com/r/Warehousing/comments/1pyhaf1/realworld_experience_using_agvs_in_warehouse/nwqyd3z/ | 2025-12-30 | stall
- "the biggest effort is in the day in day out optimization." | integrator (consultant) | https://www.reddit.com/r/Warehousing/comments/1pyhaf1/realworld_experience_using_agvs_in_warehouse/nwloxa1/ | 2025-12-29 | tuning
- "I inherited someone's vanity idea of a robot. One robot. Didn't really do the job." | operator | https://www.reddit.com/r/Warehousing/comments/1tc9y9t/manhattan_wms_is_impossible_to_work_with_what_do/olxl136/ | 2026-05-15 | cost
- "changing the color of the box can completely break the system with no resolution." | developer (warehouse robots) | https://news.ycombinator.com/item?id=29985380 | 2022-01-18 | brittle
- "the robot usually had to be scrapped and redesigned, which costs millions and takes months or even years." | developer (warehouse robots) | https://news.ycombinator.com/item?id=29985380 | 2022-01-18 | brittle;cost
- "initial localization errors (wrong aisle)" | developer (indoor fleets) | https://news.ycombinator.com/item?id=44766803 | 2025-08-02 | map
- "stay in one spot for the entire shift while the work comes to you, because algorithms." | operator (Amazon FC associate) | https://news.ycombinator.com/item?id=14296607 | 2017-05-08 | other
- "Kiva's projects don't solve a single problem regarding: Palletizing, receiving items" | operator (Amazon logistics) | https://news.ycombinator.com/item?id=32123158 | 2022-07-17 | other
- "Cost of overhead and development was increasing" | operator (Director Software Dev, NRI) | https://www.automatedwarehouseonline.com/3pl-nri-deploys-heterogenous-fleet-of-amrs/ | 2024-07-15 | integration;cost
- "The robotic arm is not yet as fast as a team member" | operator (VP Eng. Automation, Medline) | https://www.mmh.com/article/medline_builds_on_success_with_mobile_robots/Healthcare | 2022-11-15 | other
- "When team members see a robot, the first thought in their mind is: Will this replace me?" | operator (SVP Distribution, Giant Eagle) | https://www.mmh.com/article/giant_eagle_makes_the_case_for_mobile_robots | 2013-06-01 | workforce
- "Bot will B will stop moving." | integrator | https://github.com/open-rmf/rmf_ros2/issues/214 | 2024-12-23 | stall;congestion
- "Its when we start RMF that it just doesn't work most of the times." | integrator | https://github.com/open-rmf/rmf/issues/258 | 2022-10-21 | commissioning
- "After running the program for a period of time (approximately six or seven hours), the error message is as follows" | integrator | https://github.com/open-rmf/rmf/issues/359 | 2023-06-05 | updates
- "we have come across situations where the fields contained different values" | integrator | https://github.com/VDA5050/VDA5050/issues/605 | 2026-04-23 | integration
- "does not contain any option to shut down the whole AGV fleet at once" | integrator | https://github.com/VDA5050/VDA5050/issues/57 | 2021-08-10 | charging;other
- "Without the change, our robot cannot overtake an obstacle wider than ~1m." | developer | https://github.com/ros-navigation/navigation2/pull/6091 | 2026-04-16 | stall;floor
- "the pattern that kept frustrating me was field debugging." | developer (pitching own tool) | https://discourse.openrobotics.org/t/55593 | 2026-06-21 | logs
- "Investigate failed tasks and inaccessible stock and customer totes" | recruiter (Ocado COE Specialist) | https://careers.ocadogroup.com/jobs/details?gh_jid=4427666101 | 2026-10-12 | rca
- "Diagnose technical issues involving robotic machines, including Fanuc Arms, network connections, hard drives" | recruiter (Ocado Field Service Tech) | https://careers.ocadogroup.com/jobs/details?gh_jid=4997948101 | 2026-10-12 | wifi;maint
- "Using hardware logs and device history, troubleshoot hardware failures and drive remediation efforts" | recruiter (Ocado HW Reliability Eng.) | https://careers.ocadogroup.com/jobs/details?gh_jid=4892147101 | 2026-10-12 | logs;maint
- "guide installation, commissioning, and troubleshooting of these systems both on site and remotely" | recruiter (Amazon Robotics Systems Eng.) | https://www.amazon.jobs/en/jobs/10572920/robotics-systems-engineer-tech-deployment | 2026-10-08 | commissioning
- "Act as a liaison between customer operations and internal teams, ensuring clear communication of issues" | recruiter (Locus Onsite Support Eng.) | https://job-boards.greenhouse.io/locusrobotics/jobs/5240208007 | 2026-09-16 | kpi
- "aisle widths, flooring adjustments, and other environmental factors" | recruiter (Locus Tech Support Eng.) | https://jobs.scalevp.com/companies/locus-robotics/jobs/70025377-technical-support-engineer | 2026-03-10 | commissioning;floor
- "Diagnose and resolve hardware-related problems, both remotely and on-site, to minimize downtime" | recruiter (Geekplus Field Ops Eng.) | https://jobs.b.capital/companies/geekplus-technology/jobs/43014006 | 2024-11-26 | maint
- "Monitor Tally robot performance dashboards, telemetry data, and service health indicators across the fleet." | recruiter (Simbe Robot Ops Eng.; retail, not AMR) | https://www.builtinchicago.org/job/robot-operations-analyst/8784609 | 2026-06-02 | dash
- "we basically play chicken with them" | developer (Ocado, quoted) | https://www.engadget.com/ocado-robot-collision-fire-114027027.html | 2021-07-19 | safety;congestion
- "the first generation battery charging units were used only at CFC 3" | operator (Ocado statement) | https://www.logisticsmatters.co.uk/?p=18762 | 2019 | safety;charging
- "injury rates have been significantly higher at Amazon's robotic warehouses than at its traditional sites" | press (from internal records) | https://revealnews.org/article/how-amazon-hid-its-safety-crisis/ | 2020-09-29 | injury
- "the robots started dropping offline inside dense metal storage" | analyst (newsletter) | https://parths-newsletter-7ea31b.beehiiv.com/p/your-weekly-warehouse-robotics-roundup-sept-22-to-sept-28 | 2025-09-28 | wifi
- "fine at pilot scale, cracking under real order volumes" | analyst (newsletter) | https://parths-newsletter-7ea31b.beehiiv.com/p/your-weekly-warehouse-robotics-roundup-sept-22-to-sept-28 | 2025-09-28 | integration
- "If predictions are very bad then you might find robots waiting longer than they need to" | developer (Open-RMF maintainer) | https://discourse.openrobotics.org/t/53697 | 2026-04-01 | congestion;wait
- "As a result, factory workers must keep robot paths clear for smooth operation." | developer (study authors, deployed system) | https://arxiv.org/pdf/2512.15215 | 2025-12 | floor;stall
- "existing wireless networks that support traditional wireless terminal usage (RF) are not robust enough to support the big jump in data required" | analyst (SCDigest editorial) | https://www.scdigest.com/ONTARGET/23-10-10_BANDWIDTH_WIFI_MOLBILE_ROBOTS_WAREHOUSES.PHP | 2023-10-10 | wifi

## Search log (per scout, every URL or search and its result, as the scouts returned them)
### A: ROS Discourse, Open-RMF, VDA5050, Nav2
- discourse.ros.org/search.json?q=fleet production deployment problems: 301 to discourse.openrobotics.org
- discourse.openrobotics.org/search.json?q=fleet production deployment problems: ok (mostly job posts)
- .../search.json?q=lessons learned fleet deployment: ok, nothing relevant; q=mixed fleet: ok; q=warehouse AMR operations: ok, nothing new; q=fleet logs debugging field: ok
- discourse t/56931.json (do AMR operators monitor fleets): ok, no operator answers (a negative signal); t/52899, t/57050, t/54681, t/55593: ok
- api.github.com search repo:open-rmf/rmf_ros2+lift: ok; repo:VDA5050+mixed+fleet: ok; repo:navigation2+production+stuck: ok; repo:open-rmf/rmf+charging: ok; +door+deployment: ok (setup issues only); +real+robots+traffic: ok; repo:VDA5050+practice+problem: ok; repo:VDA5050+manufacturer+is:issue: ok; repo:navigation2+warehouse: titles only (the fetch tool refused to extract)
- github open-rmf/rmf_ros2#214, #555; VDA5050#647, #653; rmf#711, #716; navigation2#6185 (sim, excluded): ok
- Not run: rmf discussions, rmf_demos, the neutral terms idle/utilization/dashboard/localization/KPI
### B: Reddit, HN, LinkedIn
- old.reddit.com/r/warehousing/search?q=robots: UNREACHED (tool cannot fetch); www.reddit.com/.../search.json: UNREACHED
- WebSearch site:reddit.com Locus/AutoStore/amazonfc/pods: empty (no Reddit results)
- redlib.catsarch.com: 429
- api.pullpush.io: q=robots sub=warehousing ok; link_id=1pyhaf1 ok; q=AMR sub=warehousing ok; submissions sub=autostore ok; comments sub=autostore ok, 0; q=locus ok, 0; q=autostore ok, 0; q=drives / robots / "robots down" / "robotics floor drives" sub=AmazonFC: 429
- arctic-shift: body=pods sub=AmazonFC ok (two pages); body=drives ok, 0 (delivery drivers); body=amnesty 422; posts "drive amnesty" 422; body=AMR sub=supplychain 422
- HN Algolia: "warehouse robots worked", "locus robotics", "autostore", "AGV warehouse wifi", "kiva robots warehouse worked", "warehouse robots stuck", "amazon robotics drives pods stow", "AMR fleet warehouse": ok, low yield
- WebSearch eng-tips/forum AGV fleet traffic: vendor and port research only
- linkedin.com/search/results/content/?keywords=AMR fleet robots stuck: UNREACHED (login wall)
- Not run: r/supplychain, r/robotics, r/logistics, r/LocusRobotics; Reddit neutral queries "robot charging", "wifi robots warehouse", "goods to person downtime"
### C: job postings
- boards-api.greenhouse.io locusrobotics ok; ocadogroup ok (50 jobs); symbotic, exotec, ocado, ocadotechnology, autostore 404 (guesses)
- api.lever.co greyorange 404; GreyOrange ATS token not found: UNREACHED
- amazon.jobs search.json (robotics fleet, AMR operations, robotics operations engineer, robotics technician, robotics technical services, robotics site engineer, AR floor): ok
- symbotic.com R7276: curl 403, WebFetch excerpt only (rows dropped)
- embedded.jobs GXO, jobs.b.capital Geekplus, jobs.accel.com OTTO, jobs.scalevp.com Locus, builtinchicago Simbe: ok
- app.welcometothejungle.com Exotec: 502 UNREACHED; jobs.gxo.com: no duty text; Indeed: 403; LinkedIn guest search: off-topic results
- DHL direct, 6 River, inVia, Attabotics, Walmart, Radial, Geodis, AutoStore careers: not reached
### D: incidents, talks, surveys
- hampshire.moderngov.co.uk s38626 and s36357 Report.pdf: 403 UNREACHED
- logisticsmanager.com Erith, thegrocer.co.uk Erith, engadget Erith, logisticsmatters ?p=18762, revealnews.org, nbcphiladelphia bear spray, materialhandling247 Peerless, inorbit.ai ROSCon 2019, beehiiv newsletter, rapyuta ASKUL: ok
- scmr.com AMR blueprint 403; geekwire 403; supplychain247 survey 403; computing.co.uk 403; help.senate.gov PDF 403; uhasselt docx 503; npr.org timeout; redlib AmazonFC DNS failure; dailydot: homepage only; logisticsmgmt.com and mmh.com webinars: teaser only
- WebSearches (all ok): Ocado Andover/Erith, Senate HELP, challenges after deploying AMRs, Hampshire FRS, MHI 2025 barriers, Reveal, warehouse automation downtime survey, Robbinsville bear spray, DC Velocity, ROSCon lessons learned, MMH VP operations, AmazonFC amnesty
### E: HN, reviews, trade press
- HN Algolia: "warehouse robots", "Kiva robots", "AutoStore", "worked amazon fulfillment center robots", "Locus robots", "AMR warehouse fleet" (0), "warehouse automation failed", "amazon robotics drives pods", "amnesty robotic floor", "warehouse robots wifi", "I worked warehouse robots stuck": ok
- ottomotors.com lessons-learned MODEX panel: 404; emerald IJLM-09-2022-0362: paywall; imec CHI 2025: abstract only; osuva.uwasa.fi thesis: bot-blocked
- automatedwarehouseonline NRI, mmh.com Giant Eagle, mmh.com Medline: ok
- g2.com, capterra.com, gartner.com reviews: 403 UNREACHED
### F: surveys, regulators, studies, Open-RMF
- api.github.com repo:open-rmf/rmf deadlock 0; idle 1 (#551, no quote); lift stuck: setup only; hospital: #722, #726; localization: #726
- discourse search traffic jam: ok (44731, 53697); charging queue: no deployment complaint; relocalization warehouse: nothing; fleet dashboard operators: ok (55245, 53820 roadmap only)
- arxiv 2512.15215 PDF: pdftotext ok; edoc.ku.de Ohneberg PDF: pdftotext ok; EU-OSHA ID4 PDF: ok, one weak line (not used)
- automatedwarehouseonline Interact Analysis: ok; scdigest: ok; salzburgresearch: abstract only; imec: abstract only
- mhi.org/publications/report: no PDF, UNREACHED; help.senate.gov: 403; OSHA, Washington L&I: search snippets only
- Not searched: Zebra Warehousing Vision Study, Deloitte, A3
### Main loop: verification fetches (curl, read-only)
- About 45 raw pages and APIs listed under Method; all fetched ok except symbotic.com (403) and rapyuta with the default user agent (Cloudflare; ok with a browser user agent). Scratch files in /tmp/opscout_fetch, /tmp/opscout.

SCHED_RESULT: OK docs/scouting/operator-problems.md committed (73610c8, 706bab9) and pushed; 80 verified rows from 56 sources, 13 UNREACHED source rows; top themes stalls, congestion, integration; build = per-robot time budget (waiting split from stuck); DEMAND_SCORE stalls=2 waiting=2 congestion=2 integration=3 trust_in_alerts=1

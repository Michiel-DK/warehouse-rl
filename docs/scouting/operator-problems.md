# Operator problems: what people who run robot fleets complain about, in their own words (2026-10-20)

## 1. Sources read

Demand side only. Six scouts ran on 2026-10-20 (WebFetch/WebSearch). Every quote below was then checked string-for-string
against the page's raw text on 2026-10-20: GitHub, Discourse JSON, job-board APIs, press pages, PDFs via pdftotext, Reddit
comments through the arctic-shift archive API (reddit.com itself did not render), Hacker News through the Algolia API.
Rows that failed the check, or came only from a search snippet or a summarised fetch, are not here. The search log, the
check script and 36 more verified rows left out for length are in the scout report `reports/wr-scout-operator-problems.md` (untracked; copy in `laptop-scheduler/reports/`).
Rules: `~/.claude/skills/outward-claim-discipline`. Rank C = first-hand practitioner text, D = summary, talk or survey
write-up, A = official report.

| source | URL | type | date of source | verified@ | statements taken |
|---|---|---|---|---|---|
| ASKUL interview on a Rapyuta case-study page (customer's words) | https://www.rapyuta-robotics.com/use-cases/case-askul2/ | post-mortem (customer interview) | undated, operation from 2022-04 | 2026-10-20 | 5 |
| r/Warehousing, 4 threads (AGV/AMR users and consultants) | https://www.reddit.com/r/Warehousing/comments/1pyhaf1/ and 3 more (row URLs) | forum thread | 2024-07 to 2026-09 | 2026-10-20 | 10 |
| r/AmazonFC, 9 threads (associates on drive floors) | https://www.reddit.com/r/AmazonFC/ (row URLs) | forum thread | 2026-10-12 to 2026-10-19 | 2026-10-20 | 10 |
| r/autostore | https://www.reddit.com/r/autostore/comments/1ql1tav/r5_chargers_shutting_down/ | forum thread | 2026-01-23 | 2026-10-20 | 1 |
| Hacker News, 3 comments | https://news.ycombinator.com/item?id=44766803 (+26629861, 42770083) | forum thread | 2021-03 to 2025-08 | 2026-10-20 | 4 |
| ROS Discourse, 6 threads | https://discourse.openrobotics.org/t/57050 (+44731, 52899, 53697, 54681, 55245) | forum thread | 2024-04 to 2026-08 | 2026-10-20 | 7 |
| Open-RMF GitHub issues | https://github.com/open-rmf/rmf_ros2/issues/214 (+555; rmf 711, 716, 726) | issue | 2022-06 to 2026-09 | 2026-10-20 | 7 |
| VDA5050 GitHub issues | https://github.com/VDA5050/VDA5050/issues/647 (+653, 429, 233, 74) | issue | 2021-11 to 2026-08 | 2026-10-20 | 6 |
| Nav2 GitHub issue | https://github.com/ros-navigation/navigation2/issues/3186 | issue | 2022-09-13 | 2026-10-20 | 1 |
| Ocado job postings, 4 (Tokyo, Sofia, Sydney, Toronto) | https://boards-api.greenhouse.io/v1/boards/ocadogroup/jobs | job posting | 2026-10-12 to 2026-10-19 | 2026-10-20 | 5 |
| Amazon job postings, 2 | https://www.amazon.jobs/en/jobs/10450570/process-assistant-ric6 (+10583208) | job posting | 2026-06-16, 2026-10-19 | 2026-10-20 | 3 |
| Locus Robotics job postings, 2 | https://job-boards.greenhouse.io/locusrobotics/jobs/5238730007 (+scalevp 70025377) | job posting | 2026-03-10, 2026-09-15 | 2026-10-20 | 2 |
| GXO (GreyOrange site), OTTO/Plex, Simbe job postings | row URLs | job posting | 2026-05-02, 2026-06-02, GXO undated | 2026-10-20 | 4 |
| NRI 3PL heterogeneous fleet (named NRI managers) | https://www.automatedwarehouseonline.com/3pl-nri-deploys-heterogenous-fleet-of-amrs/ | press interview | 2024-07-15 | 2026-10-20 | 2 |
| Interact Analysis end-user survey, n=300 (reprint) | https://www.automatedwarehouseonline.com/interact-analysis-asks-what-customers-want-from-mobile-robots-in-global-survey/ | survey | 2024-07-27 | 2026-10-20 | 3 |
| Peerless Research Group survey, n=217 (write-up) | https://www.materialhandling247.com/article/warehouse-robotics-adoption-trends-2025/peerless_research_group | survey | 2025-06-04 | 2026-10-20 | 1 |
| Ohneberg et al., hospital transport robot interviews (Int J Soc Robotics) | https://edoc.ku.de/id/eprint/35413/1/s12369-025-01289-4.pdf | survey (interview study) | 2025-07-23 | 2026-10-20 | 2 |
| arXiv 2512.15215, AMR operator/driver interviews | https://arxiv.org/pdf/2512.15215 | survey (interview study) | 2025-12 | 2026-10-20 | 1 |
| Ocado Erith fire, Ocado statement | https://www.logisticsmanager.com/three-amrs-collide-resulting-in-fire-at-ocado-erith-warehouse | post-mortem (press) | 2021-07-19 | 2026-10-20 | 1 |
| Ocado Andover fire, Hampshire FRS findings via press | https://www.logisticsmatters.co.uk/?p=18762 | post-mortem (press) | 2019 events, article undated | 2026-10-20 | 1 |
| Reveal, Amazon robotic sites injuries | https://revealnews.org/article/how-amazon-hid-its-safety-crisis/ | post-mortem (press) | 2020-09-29 | 2026-10-20 | 1 |
| Parth Pethani warehouse robotics newsletter (site visits) | https://parths-newsletter-7ea31b.beehiiv.com/p/your-weekly-warehouse-robotics-roundup-sept-22-to-sept-28 | talk (newsletter) | 2025-09-28 | 2026-10-20 | 2 |
| InOrbit ROSCon 2019 write-up | https://www.inorbit.ai/blog/2019-11-03-roscon-2019 | talk (summary) | 2019-11-03 | 2026-10-20 | 1 |
| old.reddit.com and www.reddit.com search pages | https://old.reddit.com/r/warehousing/search?q=robots | forum | n/a | UNREACHED 2026-10-20 | 0 |
| r/supplychain, r/robotics, r/logistics | https://arctic-shift.photon-reddit.com/api/comments/search?subreddit=supplychain&body=AMR | forum | n/a | UNREACHED 2026-10-20 (HTTP 422/429; not searched) | 0 |
| LinkedIn posts; Indeed | https://www.linkedin.com/search/results/content/?keywords=AMR%20fleet%20robots%20stuck ; Indeed search | post / job posting | n/a | UNREACHED 2026-10-20 (login wall, 403) | 0 |
| G2, Capterra, Gartner Peer Insights operator reviews | https://www.g2.com/products/locus-robotics/reviews | review | n/a | UNREACHED 2026-10-20 (403) | 0 |
| Job boards: GreyOrange, Exotec, AutoStore, 6 River, inVia, Attabotics, DHL, Geek+ (live) | e.g. https://app.welcometothejungle.com (Exotec, 502) | job posting | n/a | UNREACHED 2026-10-20 (no ATS token found or 404/502) | 0 |
| Symbotic careers R7276 | https://www.symbotic.com/careers/open-positions/R7276 | job posting | 2026-08-17 | UNREACHED raw (403); summarised fetch only, rows dropped | 0 |
| Hampshire FRS Andover reports | https://hampshire.moderngov.co.uk/documents/s38626/Report.pdf | post-mortem | 2019 | UNREACHED 2026-10-20 (403) | 0 |
| US Senate HELP Amazon report | https://www.help.senate.gov/ (amazon_investigation.pdf) | post-mortem | 2024 | UNREACHED 2026-10-20 (403) | 0 |
| MHI Annual Industry Report | https://www.mhi.org/publications/report | survey | 2024-2026 | UNREACHED 2026-10-20 (no PDF on page) | 0 |
| SCMR AMR blueprint (17 practitioners); SupplyChain247 robotics survey | https://www.scmr.com ; https://www.supplychain247.com | survey | 2025-2026 | UNREACHED 2026-10-20 (403) | 0 |
| MODEX/ProMat/LogiMAT/ROSCon/Automate talk transcripts | https://ottomotors.com/lessons-learned-in-business-critical-amr-installations/ (404) | talk | n/a | UNREACHED 2026-10-20 (no transcript found; one page 404) | 0 |
| Hasselt AMR interview study; Emerald IJLM Grover & Ashraf 2023 | https://doi.org/10.1108/IJLM-09-2022-0362 | survey (interview study) | 2023-2025 | UNREACHED 2026-10-20 (503; paywall) | 0 |
| OSHA / Washington L&I Amazon citations | https://www.osha.gov | post-mortem | various | UNREACHED as text (search snippets only, about pace, no robot fleet content) | 0 |

## 2. Problem statements

Ordered by theme. Theme codes: stall, congestion (deadlock, traffic, jams), wait (at stations, pickers, queues, starved
stations), integration (WMS, mixed vendor, VDA 5050), commissioning, dash (monitoring, dashboards), kpi, logs, map
(localisation, maps), rca (recurring faults), updates (software/firmware updates, version drift), charging, wifi, doors
(doors, lifts), maint, floor (floor obstructions, pod crashes), timebudget (time spent per state), idle, safety, injury,
cost, support, workforce, dataquality, hotspot, vdaaware, wifi_counter (evidence against wifi as a pain). Job postings are
duties a company pays for, not complaints, so role = recruiter.

| # | quote (verbatim) | who | fleet | URL | date | rank | verified@ | themes |
|---|---|---|---|---|---|---|---|---|
| 1 | "During the initial stages of operation, there were a few instances where the robots stopped due to errors." | operator | Rapyuta AMR, person-to-goods | https://www.rapyuta-robotics.com/use-cases/case-askul2/ | undated (ops from 2022-04) | C | 2026-10-20 | stall, commissioning |
| 2 | "there was a tendency for AMRs to get stuck while moving between two zones, causing pickers to wait" | operator | Rapyuta AMR | https://www.rapyuta-robotics.com/use-cases/case-askul2/ | undated | C | 2026-10-20 | stall, wait |
| 3 | "An AMR drives to an empty spot and stops" | integrator (WMS consultant) | AMR | https://www.reddit.com/r/Warehousing/comments/1w9pw47/what_is_the_best_warehouse_process_to_automate/p8mu8ov/ | 2026-09-08 | C | 2026-10-20 | stall, dataquality |
| 4 | "every time you get a waiting for work or a stuck pod, hit that andon and jot down the time." | operator (associate) | Amazon drives | https://www.reddit.com/r/AmazonFC/comments/1x6ykpg/pickers/ph0gunp/ | 2026-10-16 | C | 2026-10-20 | wait, stall, timebudget, kpi |
| 5 | "standing next to the gatee with their beacon lit stopping your pods for no reason" | operator (associate) | Amazon drives | https://www.reddit.com/r/AmazonFC/comments/1x5idkh/pick_robotics_warehouse/ph3lteu/ | 2026-10-16 | C | 2026-10-20 | stall, wait |
| 6 | "there is major significant delays and robots are stuck for some time" | integrator | 2 robots, free_fleet | https://github.com/open-rmf/rmf/issues/711 | 2025-07-18 | C | 2026-10-20 | stall, congestion |
| 7 | "When the footprint touches the costmap filter, it is stuck forever until I teleop it away from the area" | developer | not stated | https://github.com/ros-navigation/navigation2/issues/3186 | 2022-09-13 | C | 2026-10-20 | stall |
| 8 | "Prioritising bot recoveries and arranging recovery windows" | recruiter (Ocado COE Specialist) | Ocado grid bots | https://careers.ocadogroup.com/jobs/details?gh_jid=4427666101 | 2026-10-12 | C | 2026-10-20 | stall |
| 9 | "orchestrate mobile robot recoveries, smash SLAs, and dive deep into technical data to analyse asset performance" | recruiter (Ocado Ops Services Support) | Ocado Hive bots | https://careers.ocadogroup.com/jobs/details?gh_jid=4807169101 | 2026-10-12 | C | 2026-10-20 | stall, rca, kpi |
| 10 | "Support partner operations including "jam busting" and fault clearing" | recruiter (Ocado Technical Operator) | Ocado grid | https://careers.ocadogroup.com/jobs/details?gh_jid=5009526101 | 2026-10-19 | C | 2026-10-20 | stall, congestion |
| 11 | "resolving issues on the Amazon Robotics (AR) floor such as restarting a drive" | recruiter (Amazon Process Assistant) | Amazon drives | https://www.amazon.jobs/en/jobs/10450570/process-assistant-ric6 | 2026-06-16 | C | 2026-10-20 | stall |
| 12 | "monitoring overall floor health of the robotic field" | recruiter (Amazon AR Quarterback) | Amazon drives | https://www.amazon.jobs/en/jobs/10450570/process-assistant-ric6 | 2026-06-16 | C | 2026-10-20 | dash, stall |
| 13 | "Locate sources of problems by observing and monitoring the automation field" | recruiter (GXO Robotics Tech II) | GreyOrange Butler | https://embedded.jobs/job/Robotics-Tech-II-Day-Shift-with-GXO-Logistics-969b47 | undated (expired) | C | 2026-10-20 | rca, stall |
| 14 | "Once a robot was operational, the most common pain points were lack of maintenance prediction, costly downtime, and too much manual intervention required." | survey respondents (Interact Analysis, n=300 users/buyers) | mobile robots | https://www.automatedwarehouseonline.com/interact-analysis-asks-what-customers-want-from-mobile-robots-in-global-survey/ | 2024-07-27 | D | 2026-10-20 | maint, stall |
| 15 | "The attempt to overtake the robot in front would easily lead to really bad traffic jams and then all the robots get stuck." | developer (Open-RMF maintainer) | delivery robots | https://discourse.openrobotics.org/t/44731 | 2024-04-19 | C | 2026-10-20 | congestion, stall |
| 16 | "During times of congestion, we utilize the "Mark as reached" button to prevent idle time." | operator | Rapyuta AMR | https://www.rapyuta-robotics.com/use-cases/case-askul2/ | undated | C | 2026-10-20 | congestion, idle |
| 17 | "They control AGV routes and can skip replenishment locations when bottlenecks form and get back to them once clear." | operator | AGV, 3 vehicles | https://www.reddit.com/r/Warehousing/comments/1pyhaf1/realworld_experience_using_agvs_in_warehouse/nwjnwwe/ | 2025-12-29 | C | 2026-10-20 | congestion |
| 18 | "most failed deployments we've seen aren't a navigation failure, they're a scheduling failure once you're past 4-5 vehicles" | integrator (vendor, customer problem) | AMR/AGV | https://www.reddit.com/r/Warehousing/comments/1pyhaf1/realworld_experience_using_agvs_in_warehouse/owffmh7/ | 2026-07-09 | D | 2026-10-20 | congestion, wait |
| 19 | "There are many gotchas. Tight aisles are certainly problem areas." | integrator | AGV/AMR | https://www.reddit.com/r/Warehousing/comments/1vqn6ed/our_facility_has_narrow_aisles_and_tight_spaces/p4ofze3/ | ~2026-08 | C | 2026-10-20 | congestion |
| 20 | "added more drives onto the floor and didn't increase the floor space and got confused why the pod gaps and drive utilization kept going up" | operator (associate) | Amazon drives | https://www.reddit.com/r/AmazonFC/comments/1x7vfzv/does_amazons_picking_system_track_how_much_weight/ph7mq48/ | 2026-10-16 | C | 2026-10-20 | congestion, wait, kpi, timebudget |
| 21 | "multiple mobile robots may be simultaneously blocked waiting for the same resource, such as a lift" | developer (Open-RMF maintainer) | not stated | https://github.com/open-rmf/rmf_ros2/issues/214 | 2022-06-09 | C | 2026-10-20 | doors, wait, congestion |
| 22 | "sometimes the robot collides as navigation gets very less moment to react on it." | integrator | 2 robots, free_fleet | https://github.com/open-rmf/rmf/issues/711 | 2025-07-31 | C | 2026-10-20 | congestion |
| 23 | "appears to have been caused by the collision of three bots on the grid" | operator (Ocado statement) | Ocado grid | https://www.logisticsmanager.com/three-amrs-collide-resulting-in-fire-at-ocado-erith-warehouse | 2021-07-19 | C | 2026-10-20 | safety, congestion |
| 24 | "the most common pain points were operation slowdowns, routing and tasking difficulties, and problems with integrating with internal software." | survey respondents (Interact Analysis) | mobile robots | https://www.automatedwarehouseonline.com/interact-analysis-asks-what-customers-want-from-mobile-robots-in-global-survey/ | 2024-07-27 | D | 2026-10-20 | commissioning, integration, congestion |
| 25 | "A great robot with a laggy or manual handoff to the WMS creates the exact "waiting on each other" problem" | integrator (vendor, customer problem) | AMR/AGV | https://www.reddit.com/r/Warehousing/comments/1pyhaf1/realworld_experience_using_agvs_in_warehouse/owffmh7/ | 2026-07-09 | D | 2026-10-20 | integration, wait |
| 26 | "Sometimes you don't get pods, so there is nothing you can do." | operator (associate) | Amazon drives | https://www.reddit.com/r/AmazonFC/comments/1x6ykpg/pickers/pgzp868/ | 2026-10-15 | C | 2026-10-20 | wait |
| 27 | "AR floor system updates led to numerous "No pods en route" messages across multiple buildings." | operator | Amazon drives | https://www.reddit.com/r/AmazonFC/comments/1x47y50/this_past_pbdd_week_was_nothing_much_of_a/pfhsgux/ | 2026-10-12 | C | 2026-10-20 | updates, wait |
| 28 | "people with long lines of waiting pods causing slowdown." | operator (associate) | Amazon drives | https://www.reddit.com/r/AmazonFC/comments/1x4stk6/im_being_sabotaged/pgn2tuj/ | 2026-10-14 | C | 2026-10-20 | wait |
| 29 | "I can hit 400 but then i get pod gaps and its impossible to maintain." | operator (associate) | Amazon drives | https://www.reddit.com/r/AmazonFC/comments/1x58g1p/kinda_struggling/pgunpod/ | 2026-10-15 | C | 2026-10-20 | wait, kpi |
| 30 | "having a robot reach a zone/queue only for it to learn that the queue is full" | developer (Open-RMF maintainer) | not stated | https://github.com/open-rmf/rmf_ros2/issues/214 | 2024-12-24 | C | 2026-10-20 | wait |
| 31 | "Highlighting and resolving pick support issues" | recruiter (Ocado COE Specialist) | Ocado grid | https://careers.ocadogroup.com/jobs/details?gh_jid=4427666101 | 2026-10-12 | C | 2026-10-20 | wait |
| 32 | "The ROI killers are comms issues with the WMS." | operator | AGV | https://www.reddit.com/r/Warehousing/comments/1pyhaf1/realworld_experience_using_agvs_in_warehouse/nwqyd3z/ | 2025-12-30 | C | 2026-10-20 | integration |
| 33 | "Usually a system update on either side causing the AGV to not run." | operator | AGV | https://www.reddit.com/r/Warehousing/comments/1pyhaf1/realworld_experience_using_agvs_in_warehouse/nwqyd3z/ | 2025-12-30 | C | 2026-10-20 | updates, integration |
| 34 | "Most of the real pain isn't mechanical — it's WMS/AGV comms breaking after updates or edge cases caused by human error." | operator | AGV (manufacturing) | https://www.reddit.com/r/Warehousing/comments/1pyhaf1/realworld_experience_using_agvs_in_warehouse/nxl2aa7/ | 2026-01-04 | C | 2026-10-20 | integration, updates |
| 35 | "We looked heavily at AMR's (Pick to robot carts); multiple vendors, and just couldn't justify the system and integration." | operator | AMR pick carts | https://www.reddit.com/r/Warehousing/comments/1e9v1gk/picking_improvement_software/leqa2m3/ | 2024-07-24 | C | 2026-10-20 | integration, cost |
| 36 | "And because each API structure was different, it required manipulation and re-mapping on our side." | operator (Director Software Dev, 3PL NRI) | 6 River + Locus | https://www.automatedwarehouseonline.com/3pl-nri-deploys-heterogenous-fleet-of-amrs/ | 2024-07-15 | C | 2026-10-20 | integration |
| 37 | "For a mixed fleet this is the most expensive part of integration and the only part the standard doesn't help with." | integrator | mixed-vendor AGV | https://github.com/VDA5050/VDA5050/issues/647 | 2026-08-07 | C | 2026-10-20 | integration, commissioning |
| 38 | "commissioning fifty vehicles from four manufacturers means four different procedures, repeated fifty times" | integrator | mixed-vendor AGV | https://github.com/VDA5050/VDA5050/issues/647 | 2026-08-07 | C | 2026-10-20 | commissioning, integration |
| 39 | "either installs one vendor-specific telemetry stack per manufacturer or does without." | integrator | mixed-vendor AGV | https://github.com/VDA5050/VDA5050/issues/653 | 2026-08-24 | C | 2026-10-20 | integration, dash |
| 40 | "for manufacturer-specific actions, we can't get the information of what blockingType of a given action" | integrator (master control side) | AGV | https://github.com/VDA5050/VDA5050/issues/233 | 2023-07-24 | C | 2026-10-20 | integration |
| 41 | "is the vehicle manufacturer required to accept and process a map provided by the Master Control system" | integrator | AGV | https://github.com/VDA5050/VDA5050/issues/429 | 2025-11-05 | C | 2026-10-20 | map, integration |
| 42 | "Companies cite integration hurdles and internal knowledge gaps as major obstacles" | survey respondents (Peerless, n=217) | robotics general | https://www.materialhandling247.com/article/warehouse-robotics-adoption-trends-2025/peerless_research_group | 2025-06-04 | D | 2026-10-20 | integration, workforce |
| 43 | "if you fuck up an automation project, it's gonna be stuck that way for years." | operator (fulfilment ops) | not stated | https://news.ycombinator.com/item?id=26629861 | 2021-03-30 | C | 2026-10-20 | cost, commissioning |
| 44 | "the first robot rollout that we did ourselves, which took us over six months" | operator (VP Technology, NRI) | 6 River + Locus | https://www.automatedwarehouseonline.com/3pl-nri-deploys-heterogenous-fleet-of-amrs/ | 2024-07-15 | C | 2026-10-20 | commissioning |
| 45 | "Respond to real-time issues during deployment and go-live periods through hands-on troubleshooting, log review, triage" | recruiter (OTTO Deployment Support Tech) | OTTO AMR | https://jobs.accel.com/companies/plex-systems-inc-2-9ae9ad5c-be0b-48be-bcb0-f1ecda4be810/jobs/77076852-deployment-support-technician | 2026-05-02 | C | 2026-10-20 | commissioning, logs |
| 46 | "Wi-Fi dead zones → invisible in testing, devastating in production" | analyst (newsletter) | not stated | https://parths-newsletter-7ea31b.beehiiv.com/p/your-weekly-warehouse-robotics-roundup-sept-22-to-sept-28 | 2025-09-28 | D | 2026-10-20 | wifi, commissioning |
| 47 | "often the technology doesn't work initially, and then, of course, frustration sets in" | operator (nursing staff, IP6) | hospital transport robot | https://edoc.ku.de/id/eprint/35413/1/s12369-025-01289-4.pdf | 2025-07-23 | C | 2026-10-20 | commissioning |
| 48 | "Perhaps the metrics dashboard revealed unusual performance at a facility or spare parts dropped below threshold" | recruiter (Amazon Robotics Field HW Eng.) | Amazon Robotics | https://www.amazon.jobs/en/jobs/10583208/robotics-field-hardware-engineer-robotics-technical-services | 2026-10-19 | C | 2026-10-20 | dash, maint |
| 49 | "proactively monitoring system health, robot activity, task execution, and workflows to maximize uptime" | recruiter (Locus Onsite Support Eng.) | Locus AMR | https://job-boards.greenhouse.io/locusrobotics/jobs/5238730007 | 2026-09-15 | C | 2026-10-20 | dash, kpi |
| 50 | "When a failure mode recurs, the instinct should be to build the detection before the next incident" | recruiter (Simbe Robot Ops Eng.) | shelf-scan robots | https://www.builtinchicago.org/job/robot-operations-analyst/8784609 | 2026-06-02 | C | 2026-10-20 | rca, dash |
| 51 | "once a company hits 50 they find that the tools and processes that they had been using are inadequate" | developer (InOrbit, about customers) | ROS fleets | https://www.inorbit.ai/blog/2019-11-03-roscon-2019 | 2019-11-03 | D | 2026-10-20 | dash |
| 52 | "otherwise we won't even know where to depict it on the dashboard." | developer (Open-RMF maintainer) | not stated | https://discourse.openrobotics.org/t/55245 | 2026-06-04 | C | 2026-10-20 | dash, map |
| 53 | "Operators found it slightly acceptable but noted ergonomic deficiencies and the need for constant monitoring." | analyst (study authors, summarising operator interviews) | infrastructure-camera AMR | https://arxiv.org/pdf/2512.15215 | 2025-12 | D | 2026-10-20 | dash |
| 54 | "We currently do not have log data on the waiting times of the robots" | operator | Rapyuta AMR | https://www.rapyuta-robotics.com/use-cases/case-askul2/ | undated | C | 2026-10-20 | timebudget, logs, kpi |
| 55 | "It would be great if they could analyze the logs and propose improvements based on the data." | operator | Rapyuta AMR | https://www.rapyuta-robotics.com/use-cases/case-askul2/ | undated | C | 2026-10-20 | logs, rca |
| 56 | "A mixed-version fleet is behind most of the 2am mysteries this thread is really about." | developer | not stated | https://discourse.openrobotics.org/t/57050 | 2026-08-10 | C | 2026-10-20 | updates, logs |
| 57 | "scattered logs just stop scaling" | developer (tool vendor) | ROS 2 + PLC machines | https://discourse.openrobotics.org/t/52899 | 2026-03-03 | C | 2026-10-20 | logs |
| 58 | "Read and interpret device logs to identify and resolve problems." | recruiter (Ocado Field Service Tech) | Ocado robotic pick | https://careers.ocadogroup.com/jobs/details?gh_jid=4997948101 | 2026-10-12 | C | 2026-10-20 | logs, rca |
| 59 | "Drift is one issue" | developer (indoor fleets, a decade) | large indoor fleets | https://news.ycombinator.com/item?id=44766803 | 2025-08-02 | C | 2026-10-20 | map |
| 60 | "electromagnetic environment change (wifi strength is not static)" | developer (indoor fleets) | large indoor fleets | https://news.ycombinator.com/item?id=44766803 | 2025-08-02 | C | 2026-10-20 | wifi, map |
| 61 | "Manage and update SLAM-based maps, implementing changes to optimize robot navigation." | recruiter (Locus Tech Support Eng.) | Locus AMR | https://jobs.scalevp.com/companies/locus-robotics/jobs/70025377-technical-support-engineer | 2026-03-10 | C | 2026-10-20 | map |
| 62 | "Robots tend to get lost in certain areas, either because the area is featureless or because the features are blocked by dynamic obstacles" | integrator (Singapore healthcare RMF) | hospital robots | https://github.com/open-rmf/rmf/issues/726 | 2026-04-17 | C | 2026-10-20 | map |
| 63 | "We are having a ton of chargers shuts down on us just after an update." | maintenance | AutoStore R5 | https://www.reddit.com/r/autostore/comments/1ql1tav/r5_chargers_shutting_down/ | 2026-01-23 | C | 2026-10-20 | charging, updates |
| 64 | "On three robots that's annoying. On thirty it's a full day gone." | operator (small AMR fleet) | ROS 2 AMR | https://discourse.openrobotics.org/t/57050 | 2026-07-29 | C | 2026-10-20 | updates |
| 65 | "task bids are rejected due to insufficient battery." | integrator | not stated | https://github.com/open-rmf/rmf/issues/716 | 2025-08-14 | C | 2026-10-20 | charging, idle |
| 66 | "How can be a charging process be stopped when AGV has an horizont behind the charger" | integrator | AGV | https://github.com/VDA5050/VDA5050/issues/74 | 2021-11-03 | C | 2026-10-20 | charging |
| 67 | "Repair and maintain site GreyOrange butlers, field components and butler chargers" | recruiter (GXO Robotics Tech II) | GreyOrange Butler | https://embedded.jobs/job/Robotics-Tech-II-Day-Shift-with-GXO-Logistics-969b47 | undated (expired) | C | 2026-10-20 | maint, charging |
| 68 | "especially over WiFi, ROS is missing most of what you need" | developer | not stated | https://news.ycombinator.com/item?id=42770083 | 2025-01-20 | C | 2026-10-20 | wifi |
| 69 | "Sometimes the message arrives, but it is no longer safe or meaningful to execute by the time it reaches the robot." | developer | not stated | https://discourse.openrobotics.org/t/54681 | 2026-05-10 | C | 2026-10-20 | wifi |
| 70 | "Standard APs weren't cutting it - the signal just died." | analyst (newsletter, site visits) | AS/RS | https://parths-newsletter-7ea31b.beehiiv.com/p/your-weekly-warehouse-robotics-roundup-sept-22-to-sept-28 | 2025-09-28 | D | 2026-10-20 | wifi |
| 71 | "The lift carries the robot back to the boarding floor and the task does not progress." | integrator | not stated | https://github.com/open-rmf/rmf_ros2/issues/555 | 2026-09-09 | C | 2026-10-20 | doors |
| 72 | "This is due to narrow corridors, missing features such as automatic doors" | analyst (study authors, from interviews) | hospital transport robot | https://edoc.ku.de/id/eprint/35413/1/s12369-025-01289-4.pdf | 2025-07-23 | C | 2026-10-20 | doors |
| 73 | "There's a station on the 5th floor that has nonstop pod crashes anytime I used it" | operator (associate) | Amazon drives | https://www.reddit.com/r/AmazonFC/comments/1x7bsu0/in_honor_of_halloween_do_you_have_any_spooky/ph3f7dz/ | 2026-10-16 | C | 2026-10-20 | floor, hotspot |
| 74 | "Over here having a 5 plus pod crash because there is a whole ass box sticking a foot out of the bin" | operator (associate) | Amazon drives | https://www.reddit.com/r/AmazonFC/comments/1x584ao/stow_cant_stow_rite/pgkpwfo/ | 2026-10-13 | C | 2026-10-20 | floor |
| 75 | "They can and do tip over on the AR floor." | operator (associate) | Amazon drives | https://www.reddit.com/r/AmazonFC/comments/1x9i55r/man_i_understand_the_saying_if_it_shows_it_goes/phlllfk/ | 2026-10-19 | C | 2026-10-20 | floor |
| 76 | "2nd/3rd shift is slower since it's usually a rotating POC unless we're in peak." | operator | AGV | https://www.reddit.com/r/Warehousing/comments/1pyhaf1/realworld_experience_using_agvs_in_warehouse/nxl2aa7/ | 2026-01-04 | C | 2026-10-20 | support |
| 77 | "The absence of effective automatic fire detection allowed the fire to develop before discovery." | regulator (Hampshire FRS, via press) | Ocado grid, Andover | https://www.logisticsmatters.co.uk/?p=18762 | 2019 (article undated) | A via C | 2026-10-20 | safety |
| 78 | "We vastly underestimated the effects it was going to have on our associates" | operator (former Amazon safety manager) | Amazon drives | https://revealnews.org/article/how-amazon-hid-its-safety-crisis/ | 2020-09-29 | C | 2026-10-20 | injury |
| 79 | "only 20% of respondents said they were fully aware of it, and only 8% said it was or would soon be a mandatory requirement" | survey respondents (Interact Analysis, re VDA 5050) | mobile robots | https://www.automatedwarehouseonline.com/interact-analysis-asks-what-customers-want-from-mobile-robots-in-global-survey/ | 2024-07-27 | D | 2026-10-20 | vdaaware |
| 80 | "I haven't seen any issues or complaints about latency or network bottlenecks." | developer (Open-RMF maintainer; counter-evidence on wifi) | Open-RMF deployments | https://discourse.openrobotics.org/t/53697 | 2026-04-01 | C | 2026-10-20 | wifi_counter |

## 3. Ranking

Counted by script over the 80 rows above (`sources` = distinct threads, postings or articles; `roles` = distinct role
words; `op` = sources where an operator or maintainer, not a developer or recruiter, says it). Ties are broken by roles.
`timebudget` is a cross-cutting tag and is answered in section 5, not ranked. Floor obstructions (3 sources, 1 role, all
r/AmazonFC) and idle robots (2 sources) are 16th and lower.

| # | theme | sources | roles | op | best quote | our pipeline today |
|---|---|---|---|---|---|---|
| 1 | stalls, stuck robots, recovery | 13 | 5 | 3 | "there was a tendency for AMRs to get stuck while moving between two zones, causing pickers to wait" (ASKUL) | measures it: stuck episodes from `orderId` + `driving` + `errors`, with a cause and a resolution (S5B) |
| 2 | congestion, deadlock, traffic jams | 10 | 5 | 4 | "added more drives onto the floor and didn't increase the floor space and got confused why the pod gaps and drive utilization kept going up" (r/AmazonFC) | measures part of it: episode cause `traffic` / `blocked_by_stuck` (`fleet/fleet_analyser/detector.py:26`); no deadlock-cycle or robots-per-area view |
| 3 | waiting at stations, for pickers, queues, starved stations | 10 | 4 | 7 | "every time you get a waiting for work or a stuck pod, hit that andon and jot down the time." (r/AmazonFC) | could with the stream we already read: robot busy, not driving, at a station cell; needs a station cell list from the site map, which the stream does not carry. Today such a wait over 30 s is a stuck episode |
| 4 | integration: WMS, mixed vendor, VDA 5050 | 9 | 3 | 3 | "The ROI killers are comms issues with the WMS." (r/Warehousing) | not ours (we parse one VDA 5050-shaped schema; per-vendor mapping is the integrator's job) |
| 5 | commissioning, go-live | 8 | 5 | 4 | "commissioning fifty vehicles from four manufacturers means four different procedures, repeated fifty times" (VDA5050 #647) | not ours |
| 6 | monitoring and dashboards | 8 | 4 | 0 | "When a failure mode recurs, the instinct should be to build the detection before the next incident" (Simbe posting) | measures it: every flag is in the decision ledger and graded later; false alarms per zone-hour in README (k), (l) |
| 7 | KPI and rate disputes | 6 | 2 | 4 | "I can hit 400 but then i get pod gaps and its impossible to maintain." (r/AmazonFC) | could with the stream: jobs per robot-hour from `orderId` changes; picks per station-hour needs WMS data we do not have |
| 8 | logs and field debugging | 5 | 3 | 1 | "It would be great if they could analyze the logs and propose improvements based on the data." (ASKUL) | measures it: reads the state log as it is written, volume and decision ledgers, `report.md` (S5B, S5C) |
| 9 | localisation, maps, re-mapping | 5 | 3 | 0 | "Robots tend to get lost in certain areas, either because the area is featureless or because the features are blocked by dynamic obstacles" (Open-RMF #726) | needs data we do not have: `agvPosition.localizationScore` / `positionInitialized` are VDA 5050 fields our emitter and parser do not carry |
| 10 | recurring faults, root cause | 5 | 2 | 1 | "Locate sources of problems by observing and monitoring the automation field" (GXO posting) | could with the stream: `errors[]` per robot and per cell over time; our sim emits one errorType (BREAKDOWN), so untested on real codes |
| 11 | software updates, version drift | 4 | 3 | 4 | "Usually a system update on either side causing the AGV to not run." (r/Warehousing) | needs data we do not have: software version per robot and update times; the stream shows the outage, not the update |
| 12 | charging | 4 | 3 | 1 | "We are having a ton of chargers shuts down on us just after an update." (r/autostore) | needs data we do not have: `batteryState` (not emitted, not parsed) |
| 13 | WiFi, connectivity | 4 | 2 | 0 | "Wi-Fi dead zones → invisible in testing, devastating in production" (newsletter, rank D) | could with the stream: `headerId` gaps are counted (`sequence_gaps`, `missing_messages`, `fleet/fleet_analyser/ledger.py:125`) per minute, not per cell; placing each gap at the robot's last position gives a dead-zone map |
| 14 | doors and lifts | 3 | 3 | 0 | "multiple mobile robots may be simultaneously blocked waiting for the same resource, such as a lift" (Open-RMF #214) | needs data we do not have: door and lift states are not in the robot state stream |
| 15 | maintenance, downtime | 3 | 2 | 0 | "Once a robot was operational, the most common pain points were lack of maintenance prediction, costly downtime, and too much manual intervention required." (Interact, n=300) | could, partly: time in FAULTED per robot from `errors[]`; prediction needs component data we do not have |

## 4. What we missed

Waiting is the theme with the most operator sources (7 of its 10), and Sprints 5-10 never separate it from stalling. Our
own page says "30 seconds waiting with a job means stuck", so a drive queued at a station or waiting for a picker lands
in the stall list. The stream already carries the evidence (`orderId`, `driving`, `agvPosition`); what is missing is a
station or pick-location list from the site map, plus a state for it. Starved stations ("pod gaps", "No pods en route")
are the other side of waiting: no robot arrives. That shows in the stream only as arrivals per station cell, and we do
not count them. KPI disputes (rank 7) could use the same arrivals and jobs per robot-hour, which we never report. WiFi
(rank 13) has evidence in the stream we already parse: gaps are counted per minute but never placed on the floor, and
one Open-RMF maintainer reports no latency or network complaints, so the theme is contested. Charging, updates and
version drift, localisation, and doors and lifts need fields we do not emit or parse (`batteryState`, a software
version, `localizationScore`, door and lift events). A real VDA 5050 log has the first and third. Integration and
commissioning are named often but are integrator work, not an analysis we could sell.

## 5. Verdict

The build with the most operator demand behind it is a per-robot time budget from the stream we already read. It
separates waiting at a station, waiting for a picker or queue, and starved stations from stuck, faulted, moving and idle,
and needs only a station cell list from the site map. Waiting has the most operator sources (7), stalls the most sources
overall (13), and Ocado and Amazon both pay people to recover stuck robots. That is evidence of demand, not of
willingness to pay: no source names a price. The claim an operator would push back on is the overview headline "Robots
get stuck. Nobody knows why." Operators name the why themselves: "a system update on either side", "a whole ass box
sticking a foot out of the bin", a monitor's "beacon lit stopping your pods". The time budget is never named in full in
operators' own words; three of the 80 rows ask for a piece of it: ASKUL's "We currently do not have log data on the
waiting times of the robots", the associate's "jot down the time", and the "drive utilization" comment. The Locus posting
("maximize uptime") and the Interact survey ("costly downtime") name only uptime and downtime.

DEMAND_SCORE: stalls=3 waiting=3 congestion=2 integration=3 trust_in_alerts=1

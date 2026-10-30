# Scouting: does the fleet stall analyser transfer to farm robot and autonomous machinery fleets? (2026-10-19)

Scope: field robots (weeding, seeding, harvesting), autonomous tractors and barn robots (milking robots, feed
pushers). WebFetch/WebSearch only, no browser, no logins. Source ranks follow
`outward-claim-discipline` (private harness rule set) (A = owner's own docs, dataset page or repo; B = first-party marketing;
C = press; D = tutorials, mirrors, forum posts; F = memory). The search log (every query and URL with its result) is in
`reports/wr-scout-farm-robots.md`, not here. Our own definitions (metric names, what a cell means
for us) carry no URL; every claim about the outside world does.

## 1. Fit

Three of the four requirements hold on paper and one is weak. **Location axis, holds:** tractors log RTK
position at 10 Hz (TUM dataset, https://zenodo.org/records/14619787, verified@2026-10-19, A) and ISOBUS TimeLogs carry
a position in every record (section 2). **Faults that recur at places, plausible but unmeasured:** one
under-canopy deployment attributed 8 of 12 interventions to crop-row gaps, others to row ends (Velasquez et al. 2022,
https://arxiv.org/abs/2106.15029, verified@2026-10-19, A-), but no source maps them across passes. **Logs with
position and state, half:** public logs pair position with a work state (hitch in-work, ISOBUS DDI 141 "Actual Work
State"), and no fleet-scale log has machine faults or stop causes (section 2). **Next window, holds for barns and is weak for
fields:** a barn robot runs every day so the next day is a natural window, while a field is visited once per operation
and again next season, so the next window at the same cell is days to a year away. For us a **stall** is an
in-field stop of a machine that should be working (field), or a failed or aborted task at a box or route point (barn).
A **cell** is a grid square of a field about one implement width wide, or a milking box or feed-push route segment.
The **planner-blind case** is a wet patch, mud, a crop gap or a stone that is on no map: CropFollow++ lists "corn
gap" and motor/mud failures among its seven intervention types (Sivakumar et al. 2024,
https://arxiv.org/abs/2404.17718, verified@2026-10-19, A-). The **throughput metric** (our definition, the
pick-rate equivalent) is worked hectares per machine-hour in the field and milkings or feed pushes per robot per day
in the barn.

**Why crop, soil and irrigation sensing is not this method.** Those networks are fixed sensors that sample a slowly
changing field. A typical example is the Raam soil-moisture network: 15 fixed sites in a 223 km² catchment, sensors at
5-80 cm, "the logging time interval is set on 15 minutes" (4TU.Centre for Research Data, CC0,
https://api.datacite.org/dois/10.4121/uuid:b68e3971-c73e-4d7f-b52f-9ef7d7fe1ed2, verified@2026-10-19, A). Nothing in
such a log moves, so there is no route to block, no task to abort and no state machine whose "stopped with an order"
transition our detector keys on. The signal is a slow continuous field (moisture, temperature, NDVI) that a 15-minute logger
is fast enough to follow, so a "stall" has no meaning and the question becomes interpolation and anomaly detection on a
spatial field, which is geostatistics, not fleet episode mining.

The two methods meet only where a machine acts on the sensed field. A wet cell found by soil sensing is a candidate
cause of a tractor stall at that cell, so a soil map could be a covariate for the stall hotspot map, never the stall
data itself. Irrigation hardware (centre pivots) is a single machine with a fixed path, so a stop-location map of one
pivot is a degenerate one-robot case of our method, and no pivot log was searched for here.

## 2. Data

**None found at fleet scale:** no public dataset or log pairs machine position with machine fault, alarm or
stop-cause events, for field robots, tractors, milking robots or feed pushers. The only position-plus-fault set found
is the 48 kB single-field Augmenta file below, whose sole fault is camera sun-glare. Repositories searched (queries and result counts in the report):
Kaggle (API search "tractor", "milking", "agricultural robot", "telematics"), Zenodo (API search for milking robot,
tractor GNSS, ag machinery trajectory, isoxml/isobus/ISO 11783), IEEE DataPort (site search only, its own search
returned 404, so snippet-level), data.gov (the catalogue search did not apply the query and its API returned 404:
**inconclusive, not searched**), data.europa.eu (only the first 4-6 hits of two searches read: **partial**), Hugging
Face (API search "tractor", "agricultural robot", "farm"), GitHub (API search "isoxml", "ADAPT AgGateway"), Mendeley
Data (via web search, site not indexed), AEF (site search returned no pages), AgGateway (wiki and webinar pages only),
isobus.net (data dictionary only). All verified@2026-10-19.

| name | owner | URL | size | fields | position? | state/fault? | licence | verified@ | rank |
|---|---|---|---|---|---|---|---|---|---|
| Agricultural Load Cycles: tractor mission profiles from GNSS and CAN | TUM (Götz et al.), Data in Brief 2025 | https://zenodo.org/records/14619787, paper https://pmc.ncbi.nlm.nih.gov/articles/PMC11993161/ | 2.8 GB CSV, 5 tractors; paper says 862 h recorded / 354 h fieldwork on 143 fields, Zenodo text says 1245 h (sources disagree) | lat/lon/alt, course, speeds, engine torque/speed/fuel, draft, hitch position, hitch in-work flag, PTO, work type, implement, road/field status, 10 Hz | yes (RTK except one tractor) | state yes (hitch in-work, road/field); no fault or DTC channel listed | CC BY 4.0 | 2026-10-19 | A |
| Tümosan 81.110 tillage CAN data | A. Dana, Mendeley Data v2 | https://data.mendeley.com/datasets/bbjtjrsxvx/2 | 10 TSV, 24.7 h, 10 Hz | J1939 engine, speed, hitch/draft, PTO and transfer-case status | not listed | status flags only, no faults | CC BY 4.0 | 2026-10-19 | A |
| isoxml-dotnet test TimeLogs (ISOBUS) | dev4Agriculture | https://github.com/dev4Agriculture/isoxml-dotnet (folder `Dev4Agriculture.ISO11783.ISOXML.Test/testdata/TimeLogs/ValidTimeLogs`) | 21 TLG binaries (~5.9 MB) + TASKDATA.XML (19 tasks); TLG00001 4716 rows from 2020-01-02 | position (north/east/status), DDI 141 Actual Work State, DDI 148 total fuel, ~10 vendor-specific DDIs | yes | work state yes, no alarms | Apache-2.0 (GitHub listing) | 2026-10-19 | A |
| ISOv4Plugin test datacards (ADAPT) | AgGateway ADAPT | https://github.com/AgGateway-ADAPT/ISOv4Plugin (folder `TestUtilities/Datacards`) | 4 zips, ~290 KB (AGCO MicroTrak, AGCO C100 + JD sprayer, KV) | not opened | UNTESTED | UNTESTED | EPL-1.0 | 2026-10-19 | A (listing only) |
| Augmenta tractor-drone co-robotics | Augmenta (CNH), MLSysOps | https://zenodo.org/records/18293250 | 48.4 kB zip, one field in Greece | lat/lon/alt, sensor_fault_probability, time_since_sensor_fault, success_rate | yes | camera sun-glare fault only | CC BY 4.0 | 2026-10-19 | A |
| Combine Kart Truck GPS archive v3 | Purdue OATS | https://purr.purdue.edu/publications/3083/3 | 3 GB, wheat harvests 2014-2020, one farm | raw phone GPS logs | yes | no | CC0 1.0 | 2026-10-19 | A |
| Rosario dataset v1 (field robot) | CIFASIS-CONICET | https://arxiv.org/abs/1809.06413 | 6 sequences | stereo, IMU, wheel odometry, RTK GPS 5 Hz | yes | no | CC BY 4.0 | 2026-10-19 | A |
| Sugar Beets 2016 (field robot) | Uni Bonn IPB | https://www.ipb.uni-bonn.de/data/sugarbeets2016 | ~5 TB | multispectral, RGB-D, lidar, GPS, wheel encoders | yes | no | CC BY-SA 4.0 | 2026-10-19 | A |
| Dummy milking-robot records | AgriFoodTEF, Zenodo | https://doi.org/10.5281/zenodo.17045457 | not stated | per-milking yield, interval, composition, simulated | no | no alarms or failed attachments | CC BY 4.0 | 2026-10-19 | A (search metadata only) |
| CNH FieldOps API (obtainable, not public) | CNH | https://develop.cnh.com/api-guides/fieldops-api | n/a | ISO 15143-3 telemetry: Locations, Fault Codes, Caution Codes | yes, with the machine owner's grant | yes, with the machine owner's grant | proprietary, no public sample found | 2026-10-19 | A (docs) |
| John Deere Equipment API (obtainable, not public) | Deere | https://developer.deere.com/dev-docs/equipment | n/a | page is JavaScript, only its title loaded; a search snippet mentions alerts, breadcrumbs, device state | UNTESTED | UNTESTED | proprietary | 2026-10-19 | UNTESTED |

**Telemetry standards (our VDA 5050 equivalent).** ISOBUS (ISO 11783) is the tractor-implement bus standard; AEF
describes it as defining "the communication between agricultural machinery, mainly tractors and implements"
(https://www.aef-online.org/about-us/isobus.html, verified@2026-10-19, B). Its part 10 TaskData/TimeLog files are the
nearest thing to a fleet state log, and **open TimeLogs exist only as library test data** (the dev4Agriculture and
ADAPT rows above): position plus work state, no robot-fleet semantics. An alarm or DTC element was **not found in the
21 TimeLogs read; the ISO 11783-10 text itself was not read (iso.org returned 403), so whether the format can carry
faults is UNTESTED**. A diagnostic channel (DM1 "Active Diagnostic Trouble Codes", PGN 65226, ISO 11783-12) appears
only in isobus.net search snippets; two direct fetches returned other PGNs, so it is **unverified**, and no public DM1
log for farm machinery was found. AgGateway ADAPT is a conversion framework (EPL, 15 repos under
https://github.com/AgGateway-ADAPT, verified@2026-10-19, A); its Examples repository holds code only and **no public
ADAPT sample log was found**. For barns, ISO 17532:2007 (ISOagriNET, "Data communications network for livestock farming") appeared in one web
search (standards retailers and ICAR slides, e.g. https://old.icar.org/wp-content/uploads/2015/09/Onken.pdf,
verified@2026-10-19, search results only, rank C); its text is paywalled and whether Lely or DeLaval robots log through
it is UNTESTED. No public log in it was found.

## 3. Simulators

No open simulator gives cell-level fault injection for a farm fleet out of the box. Rows verified@2026-10-19;
"maintained" is the last push date from the GitHub API.

| name | URL | licence | maintained? | faults by location? | CPU-only? | python API? | verified@ |
|---|---|---|---|---|---|---|---|
| virtual_maize_field (Field Robot Event world generator) | https://github.com/FieldRobotEvent/virtual_maize_field | GPL-3.0 | last push 2025-03-14; Gazebo Classic on main is end-of-life | possible with code: holes, litter, weeds placed by probability and seed, not by position | UNTESTED (Gazebo) | partial (two path helpers) | 2026-10-19 |
| CropCraft (crop world generator) | https://github.com/Romea/cropcraft | Apache-2.0 | 2026-06-02 | no | needs Blender ≥ 4.0 | CLI + YAML | 2026-10-19 |
| cpr_agriculture_gazebo (static farm world) | https://github.com/clearpathrobotics/cpr_gazebo | none listed | 2023-11-29 | possible with code | UNTESTED | ROS only | 2026-10-19 |
| AgroFleet (5 rovers, Gazebo Harmonic + Nav2) | https://github.com/siddharth10ss/agrofleet | MIT | 2026-07-28, 3 commits | not documented (battery return only) | not stated | ROS 2 topics only | 2026-10-19 |
| AgroRobotSimulator (multi-robot task allocation) | https://github.com/JorgeGutierrezCejudo/AgroRobotSimulator | none listed | 2024-02-07 | README does not mention it | not stated | no (ROS Noetic + Gurobi) | 2026-10-19 |
| rms (robotic milking parlour queue model) | https://github.com/karreric1/rms | MIT | last commit 2019-10-30 | no: `breakdowns` parameter unused, no spatial layout | yes | yes (numpy) | 2026-10-19 |
| farm-gym / PCSE-Gym (crop sims, not fleet sims) | https://github.com/farm-gym/farm-gym, https://github.com/WUR-AI/PCSE-Gym | BSD-3 / GPL-3.0 | 2025-08-22 / 2026-06-18 | no robots | yes | yes | 2026-10-19 |
| Fields2Cover (coverage path library, not a sim) | https://github.com/Fields2Cover/Fields2Cover | BSD-3 | 2026-09-22 | n/a | yes | yes (bindings) | 2026-10-19 |
| Re-skin: RWARE (grid MARL) | https://github.com/semitable/robotic-warehouse | MIT | 2024-09-15 | possible with code | yes | yes | 2026-10-19 |
| Re-skin: Flatland (rail grid) | https://github.com/flatland-association/flatland-rl | MIT | 2026-10-19 | possible with code: malfunctions are per agent and rate-based, not by place (seen only on a GitLab mirror, https://gitlab.aicrowd.com/pranjal_dhole/flatland/-/blob/6d0f42a743880a9506753bfd327e467d538b31c0/flatland/envs/malfunction_generators.py, rank D) | yes | yes | 2026-10-19 |

Our emitter would need moderate adaptation: the cheapest path is a TA-RWARE re-skin (a field as parallel rows with
headlands, or a barn as alleys plus milking boxes) that keeps our floor and disturbance machinery and emits the same
VDA 5050-shaped state messages, with a mapping from work state to our `driving`/`stopped with order` states; the Gazebo
worlds would need a ROS bridge, a fleet layer and fault injection written from scratch.

## 4. Who sells this already

Eight vendors, nine capabilities each, the same bar and cell rules as `docs/COMPETITION.md`; at most 10 fetches per
vendor. For a barn, a per-box or per-unit breakdown counts as location. All cells verified@2026-10-19. HTML quotes
come back through WebFetch's summariser (near-verbatim), PDF quotes were extracted locally with `pdftotext`. SwarmFarm,
Naio and Agtonomy were dropped because no vendor docs came up (searches returned unrelated firms or third-party
profiles).

H = heatmap, T = recurring-location trend, F = forecast, G = forecast grading, L = graded lessons, D = time-to-detect,
R = decision ledger, Z = avoid-zones to routing, U = log upload. `A`/`B` = yes at that rank, `n` = not found in docs
(A), `?` = UNTESTED.

| vendor | doc tree | H | T | F | G | L | D | R | Z | U |
|---|---|---|---|---|---|---|---|---|---|---|
| John Deere (Operations Center) | in-app, login | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| Monarch Tractor (WingspanAI) | KB 404 today; training PDF only | A | ? | ? | ? | ? | ? | ? | A | ? |
| Lely (Horizon) | login | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| DeLaval (DelPro / Alerts) | public (help.delaval.com) | A | A | n | n | n | n | n | n | n |
| Burro (BOSS) | public (docs.burro.ai) | n | n | n | n | n | n | n | A | ? |
| Carbon Robotics (Ops Center) | none public; customer login | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| AgXeed (TraXwise) | none (FAQ, brochure) | ? | ? | ? | ? | ? | ? | ? | ? | B |
| FarmDroid (FD20 app) | none (FAQ, App Store notes) | ? | ? | ? | ? | ? | ? | ? | ? | B |

Evidence for every yes, and the surfaces behind every `n`:

- **Monarch H, yes (A), borderline:** the analytics map shows "notable events (guardrails, snapshots, traveled path,
  health indicators, tickets ...)" along one drive's path, with a date range that "can be a maximum of 1 day apart"
  (https://www.monarchtractor.com/hubfs/Training%20Modules.pdf, 108 pages read). **Z, yes (A):** "Stay-off zones
  (blue): Zones that the tractor needs to stay away from while operating" (same PDF); nothing says they come from
  incident data. Tickets "can be assigned, updated or resolved" = incident status only.
- **DeLaval H, yes (A):** per VMS unit, "Alarms : average number of stop alarms per day" and "Detect those VMS robots
  that may require your attention" (https://help.delaval.com/kb/guide/en/vms-overview-hWBFcjOkqH/Steps/5965100).
  **T, yes (A), borderline:** "Follow performance trends over different time periods" and the Alerts app "helps you to
  understand what areas, systems or devices experience issues over time"
  (https://help.delaval.com/kb/guide/en/introduction-to-alerts-vSHtCRCLVD/Steps/4001919). **`n` cells:** read the
  footer-linked tree https://help.delaval.com/kb/en/ (Analysis, Equipment and Attention categories, VMS overview,
  Voluntary Milking Performance index, Alerts intro and usage) and the "What's New?" changelog (titles only); System
  Guides, DelPro Xtra and the changelog bodies were not read. "Disease Risk" is about animals and does not count as F.
- **Burro Z, yes (A), hand-drawn:** "Draw the shape around the area you want excluded", and the zones only shape the
  coverage path: "Exclusion Zones do not prevent a Burro from traveling through them during autonomy or manual
  control" (https://docs.burro.ai/robot-and-web-interfaces/boss-web/elements/exclusion-zones). **`n` cells:** read
  https://docs.burro.ai (root, BOSS Web index, BOSS Pro, reporting-issues), the changelog
  https://releaseburro.vercel.app/changelog and https://support.burro.ai; issue reports record "GPS coordinates" but
  no view by place is documented, and the only stall entries are "faster stall recovery in the field". FAQ and robot
  manuals not read. U stays UNTESTED because the web-API page rendered empty.
- **AgXeed U, yes (B), borderline:** "TraXwise is scalable and compatible with any machine" (other brands need
  AgXeed's control unit), https://www.agxeed.com/wp-content/uploads/2025/11/TRAXWISE-Agxeed-brochure.pdf.
- **FarmDroid U, yes (B), borderline:** "AgriRouter integration for seamless data transfer", direction not stated
  (https://apps.apple.com/app/id6446589580, v2.0.5 release notes).
- **Deere, all UNTESTED:** help sits in the app, "the link to "Help Documentation" is found in the dropdown menu when
  you select the "?"" (https://www.deere.com/assets/pdfs/common/products/technology-products/precision-ag-technology/data-management/operations-center/sept2023-release-notes-english.pdf);
  the Sept 2022 notes add "notification/alert history" per machine, not per place.
- **Lely, all UNTESTED:** Horizon docs on https://community.lely.com redirect to a login; marketing
  (https://www.lely.com/solutions/farm-management-software/horizon/) "generate[s] predictions and advice" about cow
  health, not stall places.
- **Carbon Robotics, all UNTESTED:** "Heat Maps" on https://carbonrobotics.com/carbon-ops-center are weed maps;
  "Get notified of any issues, such as debris build up, broken shear bolts ... before they become problems" is
  implement prediction, not a stall location.

Direction test, against us: Monarch's single-drive event map counted as a heatmap, DeLaval's period trends as a
recurring-location trend, AgXeed's and FarmDroid's integrations as log upload. In our favour: Deere's per-machine alert
history not counted as a heatmap, Burro's GPS-tagged issue reports not counted (nothing displays them), Lely's
third-party cow data not counted as log upload. So capabilities F, G, L, D and R were not found in the two public doc
trees (DeLaval, Burro) and are unknown for the other six, including the three largest (Deere, Lely, Carbon).

## 5. Academic anchor

**None found:** no paper doing fault, stop or stall hotspot analysis by location for farm robot, autonomous tractor
or barn robot fleets turned up. Queries (web search unless noted, all run 2026-10-19): "spatial analysis failed
milking attempts per milking box"; "agricultural robot field trials failure analysis MTBF"; "autonomous tractor field
trial stops interventions location map analysis"; "failure mode analysis agricultural field robot deployment";
"under-canopy agricultural robot long-term failure locations map"; "milking robot incomplete milkings OR failed
attachments JDS"; "autonomous feed pusher robot barn failures stuck"; "field robot intervention events GPS location
heatmap vineyard OR orchard"; "automatic milking robot downtime alarms spatial"; "weeding robot field trial failures
stuck terrain"; "agricultural robot deployment where failures occur spatial statistics"; arXiv API
"agricultural AND robot AND failures AND deployment" (2 hits). Limit: four Semantic Scholar API queries all returned
HTTP 429, and no Google Scholar query ran, so this rests on web search and arXiv only.

Near misses, **not hotspot analysis**, named so the operator does not have to look again:

| paper | venue, year | URL | read depth | location content |
|---|---|---|---|---|
| Velasquez et al., Multi-sensor fusion based robust row following for compact agricultural robots | Field Robotics 2, 2022 | https://doi.org/10.55417/fr.2022043 (arXiv 2106.15029) | HTML summary (A-) | interventions attributed in text to row gaps ("8 of 12 ... while crossing or soon after robot crossed the gap") and row ends; rates per field, no map, no recurrence |
| Sivakumar et al., Lessons from deploying CropFollow++ | ICRA 2024 Workshop on Field Robotics | https://arxiv.org/abs/2404.17718 | HTML (A-) | seven failure types (corn gap, bad start, motor/mud, ...) and distance between interventions; no location map |

All verified@2026-10-19. One unread lead: an SLU thesis on unsuccessful milkings in a rotary system may break results
down by bail position (PDF did not parse, so it is not counted).

## 6. Verdict

We cannot demo this domain honestly within two weeks on fault data, because no fleet-scale public log pairs a machine position
with a fault or stop cause (section 2), and no open farm simulator injects faults by location (section 3). We can demo
a weaker version: the TUM tractor dataset (RTK position, hitch in-work flag and road/field status at 10 Hz, CC BY 4.0)
lets us derive in-field stops while the hitch says "working", bin them into implement-width cells and grade whether
the top-K stop locations of a field's earlier passes predict those of its later passes in the same operation (a wet
strip crosses every pass). Repeat operations on the same field cannot be assumed: the data is one CSV per field and
implement, 143 fields in one 2024 season, and the paper does not report passes per field
(https://pmc.ncbi.nlm.nih.gov/articles/PMC11993161/, verified@2026-10-19, A). That first measurement is a measurement of stops, not faults: headland turns and planned refills are intentional stops, the
same definition gap as our `by_design` class, so the stall definition would have to exclude headlands first. A
simulated version is a TA-RWARE re-skin (rows plus headlands, or a barn) with our existing floor machinery, which
proves only that the pipeline runs on a different layout, not that farm faults recur where we say. Barn robots fit
the method better (daily windows, fixed boxes and routes), but no barn robot log is public. The single blocker is
data: a fleet log with position plus a fault or stop cause, obtainable only through an OEM API with a machine owner's
grant (CNH FieldOps documents Locations and Fault Codes) or from a barn-robot operator.

SCOUT_SCORE: data=1 (position plus work state is public, machine faults are not beyond one 48 kB sun-glare file) sim=1 (only generic grid sims to re-skin, no farm fault injection) competition=2 (F, G, L, D and R absent in the two public trees, DeLaval and Burro, but six of eight vendors incl. Deere and Lely are behind logins) fit=2 (location axis and planner-blind faults fit; the field window is the next pass or next season, the barn window is daily)

# Scouting: does the fleet stall analyser transfer to factory line stoppages and machine alarm logs? (2026-10-19)

Scope: discrete manufacturing lines (andon events, OEE downtime reasons, PLC alarm streams). WebFetch and WebSearch
only, no browser, no logins. Source ranks follow `outward-claim-discipline` (private harness rule set) (A = owner's own docs,
dataset page or repo; B = first-party marketing; C = press; D = snippet or secondary; F = memory). Every outside
claim below carries a URL and `verified@2026-10-19`. The search log (every query and URL with its result) is in
`reports/wr-scout-factory-stoppages.md`, not here. Our own definitions (what a cell and a window
mean for us) carry no URL. Coverage limits are stated where they bite; a limit is never written up as an absence.

## 1. Fit

Location holds only partly: a station is a fixed, named place (Bosch part IDs encode line and station, see section 2),
but the public alarm logs carry a machine ID and nothing finer, so the axis is a ranking of about 10 to 50 stations
per line, not a map. Recurring faults at places are plausible and unmeasured: no public log found pairs station
position with stop events. State holds: the alarm and stop-reason logs have typed events (ALPI 154 alarm codes, PIADE
133 stop-reason types; section 2), but position and state are not on the same rows. The next window holds well, since
a line runs every shift and the next day is a natural grading window, unlike a field visited once a season. For us a
**stall** is a stop of a machine that should be producing, with an alarm or stop-reason code. A **cell** is a station
or machine, not a grid square, so the decayed-count map becomes a station ranking and loses the spatial neighbours
that smooth it. The **planner-blind case** is a stop with no reason code, or a stop too short to log: the vendor
guide at https://ifactoryapp.com/article/downtime-pareto-analysis-prioritize-failures (D, verified@2026-10-19) says
manual logs often omit stops under five minutes. The **closed loop does not transfer**: a fixed line has no router, so
the avoid-zone step has no analogue, and the nearest actions (buffering, maintenance timing, work reassignment) must
be simulated, not tested on a planner. The **throughput metric** is good units per scheduled hour (the pick-rate
equivalent); count of stops is not a substitute, because a stop at a bottleneck costs line output and a stop in front
of a buffer may cost none (same vendor guide, D).

## 2. Data

| name | owner | URL | size | fields | position? | state / fault? | licence | verified@ | rank |
|---|---|---|---|---|---|---|---|---|---|
| Alarm Logs in Packaging Industry (ALPI), DOI 10.21227/nfv6-k750 | Tosato, Dalle Pezze, Masiero, Susto, Beghi (Univ. Padova) | https://ieee-dataport.org/open-access/alarm-logs-packaging-industry-alpi | 8.12 MB archive; 20 machines, 2019-02-21 to 2020-06-17 | alarm code, timestamp, equipment identifier; `raw/alarms.csv`, one row per alarm | no (equipment ID only) | yes: 154 alarm codes, highly unbalanced | not stated on page; download needs a free IEEE account | 2026-10-19 | A |
| PIADE (Packaging Industry Anomaly DEtection), DOI 10.5281/zenodo.7071747 | same group | https://zenodo.org/records/7071746 (the fetched record; its DOI is ...7071747) | 61.0 MB CSV: `raw_data.csv` 49.3 MB, `sequences_1h_data.csv` 11.7 MB | interval start and end, equipment ID, alarm code of the active stop reason; 133 alarm types, 429,394 rows; hourly per-alarm counters | no (equipment ID only) | yes: stop reasons and downtime states | CC BY 4.0 | 2026-10-19 | A |
| Industry 4.0 Lab state logs, DOI 10.5281/zenodo.5078737 | Friederich, Lazarova-Molnar (Univ. of Southern Denmark) | https://zenodo.org/record/5078737 | `I4.0Lab_state_log.csv` 6.0 kB, `..._failures.csv` 6.0 MB (page also says 1.1 GB total; inconsistent) | not listed on page | no | "failures" file named; no label fields described | CC BY 4.0 | 2026-10-19 | A (record page), sizes unresolved |
| AI4I 2020 Predictive Maintenance | UCI (Matzka, AI4I project) | https://archive.ics.uci.edu/dataset/601/ai4i+2020+predictive+maintenance+dataset | 10,000 rows | product ID, type, temperatures, speed, torque, tool wear; machine-failure and failure-mode targets | no | yes: failure labels, no timestamps | CC BY 4.0 | 2026-10-19 | A |
| Bosch Production Line Performance (Kaggle) | Bosch | https://www.kaggle.com/competitions/bosch-production-line-performance | UNVERIFIED (page returned its title only) | feature names encode line and station, e.g. `L3_S36_F3939` (repo `joostgp/kaggle_bosch`, snippet only, D); part-level pass/fail `Response` | yes at station level (not coordinates) | part quality failure, not stop events; no stoppage times | UNVERIFIED | 2026-10-19 | B for existence (arXiv 1701.00705 abstract, A-, https://arxiv.org/abs/1701.00705); D for field names |

Gaps: the Kaggle Bosch page could not be read, so its file list and licence are unverified. The
Bosch station count is not settled: the FedCSIS paper snippet says 4 lines and 52 stations (D, unread), another
snippet says 51 (D). Bosch has no stoppage times, so it cannot join to stop events.

**Telemetry standards (our VDA 5050 equivalent).** Two candidates. **MTConnect** is the machine-tool telemetry
standard with Condition items (normal, warning, fault). Its own site returned only its title to WebFetch
(https://www.mtconnect.org/, verified@2026-10-19), so royalty status and version are UNVERIFIED here. **OPC UA for
Machinery** (VDMA 40001) is the machinery companion spec; a 2020 VDMA press release says Part 1 became free to download
(https://vdma.org/en/level-2-minimal/-/category/3782490, found by search; press, C; verified@2026-10-19). Its alarm and
machine-state part was not identified.

**Open log in that standard: none found.** The GitHub organisation `mtconnect` was read through the API
(https://api.github.com/orgs/mtconnect/repos, verified@2026-10-19), which returned 20 of about 80 repos: `cstream`
(a streaming sample in C), `ros_bridge` (a ROS adapter with a Ruby robot simulator), `verifier`. None is a recorded
machine log in the 20 read. The other ~60 repos were not read, so this is a partial search, not an absence.

**What was searched.** Web searches for Bosch, alarm and downtime datasets, PHM challenge data, MTConnect samples and
Hugging Face alarm logs; direct fetches of IEEE DataPort, Zenodo, UCI, Kaggle and the MTConnect GitHub org. Zenodo was
searched through the web index, not its own search; Kaggle's dataset search and data.gov, data.europa.eu, IEEE
DataPort's own search were not run. Hugging Face returned two user-uploaded `machine-failure-logs` sets with no card
read (https://huggingface.co/datasets/pgurazada1/machine-failure-logs, D, unread). So "none found" means none in these
searches, not in the repositories listed in the brief.

## 3. Simulators

| name | URL | licence | maintained? | faults by location? | CPU-only? | Python API? | verified@ |
|---|---|---|---|---|---|---|---|
| SimPy | https://simpy.readthedocs.io (source https://gitlab.com/team-simpy/simpy/) | MIT (PyPI metadata) | yes: 4.1.2 uploaded 2026-05-24 (https://pypi.org/pypi/simpy/json) | no built-in; a breakdown process is written by hand (its Machine Shop example, https://simpy.readthedocs.io/en/3.0/examples/machine_shop.html, lists breakdowns and a single repairman; D, search snippet, not fetched) | yes | yes (it is the library) | 2026-10-19 |
| job-shop-lib | https://github.com/Pabloo22/job_shop_lib | MIT (https://pypi.org/project/job-shop-lib/) | yes: 1.7.2 uploaded 2026-10-08 | no; the feature list names machines, release dates and deadlines, not failures | yes | yes, Gymnasium environments | 2026-10-19 |
| maintsim | https://pypi.org/project/maintsim/ | MIT by classifier; `license` field empty | no: 0.1.3, last upload 2019-08-06 | component degradation and maintenance, not location | yes | yes (SimPy-based, per search snippet) | 2026-10-19 |
| Simantha | https://pypi.org/project/simantha/ (not readable; fetch returned an error page) | UNVERIFIED: a GitHub fetch of https://github.com/m-hoff/maintsim returned a Simantha README and an MIT-0 licence file, so the repo identity is unresolved | unknown | models machine failures and repair per search snippet; not confirmed | yes | yes | UNVERIFIED |

Commercial line simulators (AnyLogic, FlexSim) were not checked, and nothing is claimed about them. Adapting our
emitter would need a station topology with buffers, a stop-reason event generator with a per-station time-to-failure,
and an output counter for good units; SimPy's Machine Shop example already has breakdown and repair, so this is new
code of a few hundred lines (an estimate, not measured). The simulator's faults would be location-keyed only because
we would write that in, which is the honest version of "can inject by location".

## 4. Who sells this already

Six vendors, one pass each. Nine capabilities as in `docs/COMPETITION.md`. Every cell is UNTESTED: the vendor
documentation trees that would settle absence were not readable, and no marketing read is treated as absence.

| capability | MachineMetrics | Senseye (Siemens) | Sight Machine | Tulip | Litmus | Augury |
|---|---|---|---|---|---|---|
| 1 Heatmap by location | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED |
| 2 Recurring-location trend | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED |
| 3 Forecast (location of stalls) | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED |
| 4 Forecast grading | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED |
| 5 Graded lessons | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED |
| 6 Time-to-detect | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED |
| 7 Decision ledger | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED |
| 8 Avoid-zones to routing | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED |
| 9 Log upload (other fleet's data) | UNTESTED | UNTESTED | yes (B) | yes (B) | UNTESTED | UNTESTED |

Evidence, one line per vendor (all verified@2026-10-19):

- **MachineMetrics.** Downtime categories are set per company, and rules assign categories from alarms and I/O
  signals (support article https://support.machinemetrics.com/hc/en-us/articles/360056036474, read as a search snippet,
  A, not fetched). The downtime guide https://docs.machinemetrics.com/docs/product-guides/downtime-quality-guide
  returned no content and the Downtime Report article returned 403, so no location view or forecast could be read.
  Automatic categorisation is a rule, not a graded decision, so row 7 is not presence.
- **Senseye.** The Siemens page https://siemens.com/au/en/products/services/industry/senseye-predictive-maintenance.html
  (B) says "reduce unplanned outages" and links no documentation. The product marketing (https://www.siemens.com/senseye,
  B, search snippet) says it "forecasts machine failure". That is asset predictive maintenance, which the rules exclude
  from row 3. No Senseye help centre was found.
- **Sight Machine.** https://www.sightmachine.com/ (B, fetched): "Connect every OT and IT system — controls, historians,
  MES, ERP, and more." No docs or help links on the page. Row 9 scored yes (B), same rule as the Dematic and AutoStore
  cells in COMPETITION.md.
- **Tulip.** https://www.tulip.co/platform/ (B, fetched) describes connectivity to machines, sensors, cameras and
  enterprise systems. The knowledge base index https://support.tulip.co/ (fetched) lists sections only; no article
  title on stop reasons, heatmaps or prediction was visible, but the index is not the tree, so no absence is written.
- **Litmus.** https://www.litmus.io/ (B, fetched): "Detect equipment failures before they occur." That is predictive
  maintenance, excluded from row 3. The docs index https://docs.litmus.io (fetched) lists "Platform", "Build and
  automate" and "Get help" with no matching titles; it is an index, not a tree.
- **Augury.** Read from search snippets only, not fetched: its ROI page cites "99.9% diagnostic accuracy" (B, a vendor
  claim on a sales page, https://www.augury.com/roi-calculator). It is rotating-equipment monitoring, not stall location.

Not found in any vendor doc tree in this pass, because no tree was read end to end. The vendors most likely to hold
rows 1 to 8 are the ones whose trees were walled or missing here.

## 5. Academic anchor

No paper was found that does a location-based fault or stall hotspot analysis for discrete lines. Three papers are
nearest, and all are arXiv preprints, not peer-reviewed venues:

1. Mangal and Kumar, "Using Big Data to Enhance the Bosch Production Line Performance: A Kaggle Challenge", arXiv, 2017,
   https://arxiv.org/abs/1701.00705 (abstract read, A-). Part-level failure prediction on station-structured data; the
   station-level failure ranking is in the paper body, not read.
2. Laxman, Shadid, Sastry and Unnikrishnan, "Temporal data mining for root-cause analysis of machine faults in
   automotive assembly lines", arXiv, 2009, https://arxiv.org/abs/0904.4608 (abstract read, A-). Fault logs from an
   engine assembly plant; the abstract does not say whether logs carry location, so it is not a location method.
3. Xiao et al., "LMT: A Bayesian Framework for Causal Discovery from Textual Alarm Records in Manufacturing Systems",
   arXiv, submitted 2026-06-03, https://arxiv.org/abs/2606.09892 (abstract read, A-). Causal graphs over alarm
   records; evaluated on simulation, no public dataset named.

Queries and rejected hits are in the report. Not read: an Epistemus paper on workstation stoppages (biblat returned a
verification page), a 2023 stamping-line Weibull study (snippet only, by stop type, not location), and a 2022 Tennessee
Eastman alarm-RCA preprint (https://arxiv.org/abs/2203.11321, process plant, not a fleet of machines).

## 6. Verdict

We could demo the time and machine axes honestly within two weeks on PIADE: it has timestamps, machine IDs and 133
stop-reason types under CC BY 4.0, so the first measurement would be a per-machine stop-reason ranking graded on the
next day against chance and against persistence. A station-location demo is not possible on public data, because the
only dataset with stations (Bosch) has no stoppage events. The single blocker is that no public log has station
position and stop time on the same rows; a demo needs either a client log or a SimPy line we write, which makes the
simulator the fallback, not the data. The competition picture is UNTESTED throughout, so nothing here says the space
is open; the adjacent facts checked are that MachineMetrics documents downtime reasons and that Litmus and Senseye sell
predictive maintenance. The Bosch licence and file list are unverified, and the MTConnect royalty status is unverified.

SCOUT_SCORE: data=2 (PIADE and ALPI give stop reasons with timestamps; Bosch gives station position with part labels, but no row has both); sim=2 (SimPy is MIT and maintained, but breakdowns by station are written by hand); competition=2 (all cells UNTESTED except two rank-B presence cells, so the field is not known to be open); fit=2 (state and next window fit, but a fixed line has no routing loop and only about 10 to 50 cells).

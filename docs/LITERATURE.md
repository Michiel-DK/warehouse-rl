# Literature check: is the stall analyser a reasonable baseline, and is its grading new? (2026-10-18)

Scope: the academic side of what the fleet stuck analyser does (README "Sprint 5" to "Sprint 10"). The vendor side is
[COMPETITION.md](COMPETITION.md). Five questions, one research pass each on 2026-10-18, WebSearch/WebFetch only, no
browser. Rules: `~/.claude/skills/outward-claim-discipline` (source ranks, provenance per claim). The search log with
every query and its outcome is in `laptop-scheduler/reports/wr-dev-lit-stall-detection.md`. The queries behind each
absence claim are listed at the end of this page.

**Search coverage, read this first.** The Semantic Scholar API answered HTTP 429 (rate limited) to every request in
all five passes, so **no Semantic Scholar search ran**. Google Scholar was not tried, because it blocks scripted access.
DBLP was behind a bot wall. The searches that did run were Crossref, arXiv API, OpenAlex, WebSearch and publisher or
author pages. This is a targeted check of about 60 papers, not a systematic review. Every absence below means "not
found in the queries listed", never "does not exist".

**Provenance.** Every paper in the table was looked up this session (Crossref DOI record, arXiv record, publisher page
or author page; verified@2026-10-18). The table marks which ones had their full text read and which only had their
metadata checked. A claim about a paper's content rests only on full-text or abstract reading. Preprints are marked.

## 1. Stall, deadlock and anomaly detection for robot fleets from telemetry

In the AGV and multi-robot papers found, a stall is detected at runtime in one of two ways: a no-progress rule
threshold, or a cycle search on a graph. ROS 2 Nav2's shipped progress checker flags a robot that moves less than
0.5 m in 10 s by default (Nav2 `simple_progress_checker.cpp`), the same shape as our rule "active order and no cell
change for 30 s". Graph methods build a wait-for or precedence graph and search it for cycles (Cho, Kumaran & Wysk
1995 for manufacturing; Bonetti et al. 2026 for AGV fleets, adding nested acyclic deadlocks), and both read the
edges from the traffic planner's internal state, not from telemetry. Most Petri-net AGV work (Wu & Zhou 2005;
Fanti et al. 2015) is about avoiding deadlock by design, not detecting it in logs. Learned detectors appear for
single robots, swarms and predictive maintenance: outliers on groups of correlated sensors (Khalastchi et al.
2015), immune-inspired classifiers over neighbouring robots' behaviour (Tarapore et al. 2017), and LSTM and GRU
power forecasting on one real AGV (Benecki et al. 2024). Their ground truth is almost always faults the authors
injected or emulated: sensor and motor faults simulated in ARGoS (Tarapore), faults on UAVs and a vacuum robot
(Khalastchi), overload and wheel damage on an AGV (Benecki), and Bonetti et al. 2026 score against their own
detector's count with no independent label. Khalastchi et al. write that labelled datasets "are not common", and the
only real labelled fault set found is UAV only (ALFA, Keipour et al. 2020), so a threshold rule scored against
simulator truth is normal practice. Two things were not found in the queries listed: HMMs, isolation forests or
autoencoders on fleet telemetry, and any paper that rebuilds "blocked by a faulted robot" from telemetry rather than
from planner state.

## 2. Spatial hotspot forecasting: decayed counts against the alternatives

In crime-hotspot forecasting the standard metric is the hit rate, "the percentage of new crimes that occur within the
areas where crimes are predicted to occur" (Chainey, Tompson & Uhlig 2008), reported at a fixed coverage (NIJ
challenge: 0.2-0.5% of the city) or as a curve against the share of cells flagged (Mohler et al. 2011, Fig. 6). PAI
divides the hit rate by the area share (Chainey et al. call it the "Prediction Accuracy Index"), and PEI divides the
captured events n by n\*, the most the same area could have captured (Hunt 2016 via the NIJ posting; Flaxman et al.
2018). The usual baselines are kernel density (best of five methods in Chainey et al.), the prospective hotspot map
of Bowers, Johnson & Pease 2004, crime analysts' daily maps in a field trial (Mohler et al. 2015), and random cells
drawn only from cells that ever had an event (Adepeju, Rosser & Cheng 2016). Our score, a sum of 2^(-age /
half-life) per cell (`fleet/fleet_analyser/hotspot.py:148-163`), is the ETAS intensity λ = μ + Σ θω e^(-ω(t - tᵢ)) of
Mohler et al. 2015 with the background rate μ = 0 and the decay fixed, which is the prospective-hotspot family that
Mohler et al. 2011 found loses to ETAS because it ignores "the background rate of crime". With our defaults (1 h
window, 1 h half-life) the weights only fall from 1 to 0.5, so the map is close to a plain one-hour count. Mapping:
our recall@K is their hit rate counted in cells against hidden truth instead of next-period events, and precision@K
divided by our chance rate (positives / 380) equals recall@K divided by K/380, which is PAI's form in cells, so at
fixed K and positives precision and recall are one result, not two. Our rank grade (is the cell in the top K of the
map recomputed at the horizon end, `fleet/fleet_analyser/forecast_grade.py` docstring) is a cell-count cousin of
PEI, and our chance line draws from all 380 candidate cells, the lenient null that Adepeju et al. reject as
"unfairly simplistic".

## 3. Grading location forecasts on the next window against chance, and persistence of flagged places

Three fields already grade location forecasts on the next window against chance: crime mapping (hotspots built from
Time 1 and scored on Time 2, Hu et al. 2018, where PAI = 1 is a randomly placed map), meteorology (the equitable
threat or Gilbert score subtracts the hits expected by chance, (hits+misses)(hits+false alarms)/total, JWGFVR
verification pages) and earthquake testing (Molchan diagrams, where a random alarm scores an area skill of 0.5,
Zechar & Jordan 2008). Hits divided by chance hits equals precision divided by the base rate, which is our lift when
"total" is the lesson's candidate pool, so the ETS chance term is the closest analogue found. Persistence of flagged
places is measured too: Hunt 2016 (via NIJ) defines stability as the share of grid cells hot in two adjacent
intervals, Adepeju et al. 2016 report the share of hotspots that are new each day (DVI), and Platt et al. 2018 find a
relative risk of 1.77 that a hotspot household is in a hotspot again the next season. What was not found in the
queries listed is our chance rate computed per lesson over that lesson's own zone-and-window pool and then averaged,
which is a stratified version of the ETS base rate, not a new kind of score. The more important finding is the
reference: verification practice says "random chance is usually not the best forecast to compare to" and uses
persistence or climatology (JWGFVR), and in earthquake testing the recent-activity model RI (Holliday et al. 2005)
was the bar that the PI method and the national hazard map did not significantly beat (Zechar & Jordan 2008). Our
lessons are themselves persistence forecasts, so lift 2.99 (README Sprint 8 (e)) shows that hot cells persist well
above pool chance, not that the analyser has skill above a naive persistence forecast.

## 4. Time to detect and time to clear for a published map

The standard framing is sequential change-point detection: minimise the delay E(N - ν | N ≥ ν) subject to a bound on
the run length to false alarm, E(N | ν = ∞) ≥ B (Pollak 1985), for which Page's CUSUM (Page 1954) is optimal in a
defined sense (Moustakides 1986) and has a version for Poisson counts (Lucas 1985). In practice surveillance work
plots mean time to detection against false alerts per unit time, sweeping the alarm threshold: the AMOC curve
(Fawcett & Provost 1999, construction quoted from Jiang, Cooper & Neill 2009). For maps the canonical tool is the
prospective space-time scan statistic, which aims to pick up a new cluster "as quickly as possible" while keeping
false alarms down (Kulldorff 2001; Neill et al. 2005). Our first detect is the delay N - ν with ν the window start,
but our dial is K rather than a score threshold, so each K is one AMOC point, not a curve. Our median runs over
detected windows only, whereas Jiang et al. count a miss as the window length D plus a penalty P; with 5-14% of
windows detected (README Sprint 10 (g)), a 190 s median says little without the miss rate. AMOC takes false
positives from background data with no true events, and we have no such run (README Sprint 10: "There is no
undisturbed hotspot run"). Our map is never reset, so one stale cell is a false flag at every publish, the non-reset
case for which Fraker, Woodall & Mousavi 2008 give the average time between signal events and the average signal
event length. "Time to clear" has no standard name in the sources fetched; it is the delay to detect the reverse
change after the window ends.

## 5. Path finding when the robots do not know a cell is bad until they try it

Our A* plans under the freespace assumption, "the robot assumes that the terrain is clear unless it knows otherwise"
(Koenig & Smirnov 1997), as D* (Stentz 1994) and D* Lite (Koenig & Likhachev 2002) do, except that our planner
learns nothing when a robot hits a bad cell unless the analyser's cost map is fed back. The failure mechanism of our
floor cells is that of MAPF with Delay Probabilities (Ma, Kumar & Koenig 2017), where "the execution of move actions
fails with delay probability pᵢ" and the robot stays in its vertex, but there p belongs to the robot and is known
to the planner, while ours belongs to the cell and is unknown. The knowledge gap is that of MAPF under Obstacle
Uncertainty (Shofer, Shani & Stern 2023), where potential obstacles "can only be sensed once the agent reaches the
proximity", and of MAPF in inaccurate maps (Malka, Shani & Stern 2024), but in both a cell is simply blocked or
open. The Canadian Traveller problem (Papadimitriou & Yannakakis 1991) reveals blocked edges on arrival, and ours is
the stochastic, partly passable case where one failed try does not settle the cell. Execution-robustness work absorbs
delays without locating them (k-robust plans, Atzmon et al. 2020; action dependency graphs, Hönig et al. 2019). Only
`floor` is planner-blind in our setup, since active blocked cells and outages are passed to the planner as obstacles
(`src/warehouse_rl/disturb.py:462-465`). The nearest analogue of our analyser-to-planner loop is MAGIC (Parimi et
al. 2026, arXiv preprint, not peer reviewed), which pools robot observations into a shared passability belief and
hands "detour-aware costs" to a standard MAPF planner, while guidance graphs (Zhang et al. 2024; Zang et al. 2025)
are the precedent for planner edge weights but for congestion. A fitting name for our floor setting is "MAPF under
the freespace assumption with unknown per-cell delay probabilities".

## What this means for us

The decayed-count map is a defensible baseline: it is the prospective-hotspot family (Bowers et al. 2004) that crime
forecasting uses as its standard comparison, and at our defaults it is close to a plain one-hour count. It is the weak
end of that literature, since Mohler et al. 2011 beat it by adding a per-cell background rate. The obvious next
comparison is therefore an ETAS-style per-cell model (Mohler et al. 2011, 2015), a background stall rate μ per cell
plus a fitted decay, scored with the same metrics on held-out seeds. Two cheaper changes should come first: draw the
chance line only from cells that ever had a stall (Adepeju et al. 2016), and add a persistence forecast as the
reference, because verification practice treats persistence, not chance, as the bar to beat. Grading location
forecasts on the next window against chance is standard in crime mapping (PAI), meteorology (ETS) and earthquake
testing (Molchan), and our lift has the form of the ETS chance term, so "graded forecasts" is not a novelty claim we
can make. What was not found, in the queries listed, is our per-lesson pool chance rate and a persistence grade on
generated lessons, which is a variation on a standard idea, not a new kind of score. Time to detect should be
reported as an AMOC curve: delay against false alarms per hour, swept over K or a cost threshold, with misses
counted and false alarms measured on an undisturbed run that does not exist yet. The floor setting has a name and a
precedent, the freespace assumption plus MAPF delay probabilities indexed by cell and unknown, and the closest
analyser-to-planner loop is the MAGIC preprint. This check is limited by its search: no Semantic Scholar or Google
Scholar query ran.

## Papers

Ranks follow outward-claim-discipline: A = the paper's own text, read this session; A- = abstract or publisher record
read; M = metadata only (authors, year and venue confirmed, content not read). All rows verified@2026-10-18.

| Q | Authors, year | Title (short) | Venue | URL | Read | Used for |
|---|---|---|---|---|---|---|
| 1 | Bonetti, Proia, Guidetti, Sabattini 2026 | Deadlock detection and resolution for AGV fleets | Int. J. Robotics Research | https://doi.org/10.1177/02783649261470035 (arXiv 2609.10400) | A | graph cycle detection, self-scored |
| 1 | Bonetti, Guidetti, Sabattini 2024 | Efficient deadlock detection and resolution for AGV fleet management | European Robotics Forum 2024 (Springer SPAR) | https://doi.org/10.1007/978-3-031-76428-8_50 | M | precursor |
| 1 | Cho, Kumaran, Wysk 1995 | Graph-theoretic deadlock detection and resolution for FMS | IEEE Trans. Robotics & Automation | https://doi.org/10.1109/70.388784 | M | classic graph detection |
| 1 | Wu, Zhou 2005 | Modeling and deadlock avoidance of AMS with multiple AGVs | IEEE Trans. SMC-B | https://doi.org/10.1109/tsmcb.2005.850141 | M | Petri-net avoidance |
| 1 | Fanti, Mangini, Pedroncelli, Ukovich 2015 | Decentralized deadlock-free control for AGV systems | American Control Conf. | https://doi.org/10.1109/acc.2015.7171094 | M | avoidance |
| 1 | Khalastchi, Kalech, Kaminka, Lin 2015 | Online data-driven anomaly detection in autonomous robots | Knowledge and Information Systems 43(3) | https://doi.org/10.1007/s10115-014-0754-y | A | correlated-sensor outliers, injected faults |
| 1 | Khalastchi, Kalech 2019 | Fault detection and diagnosis in multi-robot systems: a survey | Sensors | https://doi.org/10.3390/s19184019 | A- | survey |
| 1 | Tarapore, Christensen, Timmis 2017 | Generic, scalable and decentralized fault detection for robot swarms | PLoS One 12(8) | https://doi.org/10.1371/journal.pone.0182058 | A | swarm, ARGoS-injected faults |
| 1 | Benecki, Kostrzewa, Drewniak, Mrozek et al. 2024 | Anomalies in AGVs based on telemetry data | ICCS 2024 (LNCS) | https://doi.org/10.1007/978-3-031-63783-4_15 | A | LSTM/GRU, emulated faults |
| 1 | Keipour, Mousaei, Scherer 2020 | ALFA: a dataset for UAV fault and anomaly detection | Int. J. Robotics Research | https://doi.org/10.1177/0278364920966642 | A- | only real labelled set found |
| 1 | Salanova, Roche, Mahulea, Montijano 2025 | Petri-net generated multi-robot anomalies | arXiv preprint | https://arxiv.org/abs/2510.17261 | A- | synthetic labels |
| 1 | ROS 2 Navigation (Nav2) | `simple_progress_checker.cpp` (software, not a paper) | GitHub, main branch | https://github.com/ros-navigation/navigation2/blob/main/nav2_controller/plugins/simple_progress_checker.cpp | A | 0.5 m / 10 s rule |
| 2,3 | Chainey, Tompson, Uhlig 2008 | The utility of hotspot mapping for predicting spatial patterns of crime | Security Journal 21 | https://doi.org/10.1057/palgrave.sj.8350066 | A (UCL preprint) | hit rate, PAI |
| 2 | Bowers, Johnson, Pease 2004 | Prospective hot-spotting | British J. Criminology 44(5) | https://doi.org/10.1093/bjc/azh036 | A- | prospective map baseline |
| 2 | Mohler, Short, Brantingham, Schoenberg, Tita 2011 | Self-exciting point process modeling of crime | JASA 106(493) | https://doi.org/10.1198/jasa.2011.ap09546 | A | ETAS beats prospective map |
| 2 | Mohler, Short, Malinowski, Johnson, Tita, Bertozzi, Brantingham 2015 | Randomized controlled field trials of predictive policing | JASA 110(512) | https://doi.org/10.1080/01621459.2015.1077710 | A (in-press PDF) | ETAS form, analyst baseline |
| 2,3 | Adepeju, Rosser, Cheng 2016 | Novel evaluation metrics for sparse spatio-temporal hotspot predictions | IJGIS 30(11) | https://doi.org/10.1080/13658816.2016.1159684 | A | ever-hit random baseline, DVI |
| 2 | Flaxman, Chirico, Pereira, Loeffler 2018 | Winning solution to the NIJ Real-Time Crime Forecasting Challenge | arXiv preprint (journal not confirmed) | https://arxiv.org/abs/1801.02858 | A | PAI, PEI definitions |
| 2,3 | National Institute of Justice 2016 | Real-Time Crime Forecasting Challenge posting | NIJ (agency page) | https://nij.ojp.gov/funding/real-time-crime-forecasting-challenge-posting | A | PEI\* (Hunt 2016), coverage |
| 2 | Mohler, Porter, Carter, LaFree 2020 | Learning to rank spatio-temporal event hotspots | Crime Science 9 | https://doi.org/10.1186/s40163-020-00112-x | A- | PAI = area-normalised recall@k |
| 3 | Hu, Wang, Guin, Zhu 2018 | Spatio-temporal KDE for crime hotspots | Applied Geography 99 | https://doi.org/10.1016/j.apgeog.2018.08.001 | A (arXiv 2006.00272) | Time 1 / Time 2 protocol |
| 3 | Joshi, D'Ath, Curtis-Ham, Searle 2020 | Crime forecast accuracy measures | arXiv preprint | https://arxiv.org/abs/2006.08008 | A | stability indices, chance test |
| 3 | Levine 2008 | The "hottest" part of a hotspot | Security Journal 21 | https://doi.org/10.1057/sj.2008.5 | M | RRI (formula not obtained) |
| 3 | JWGFVR (WMO joint working group) | Forecast verification: methods (web resource) | web | https://jwgfvr.github.io/forecastverification | A (summarised fetch) | ETS chance term, persistence reference |
| 3 | Zechar, Jordan 2008 | Testing alarm-based earthquake predictions | Geophysical J. International 172 | https://doi.org/10.1111/j.1365-246X.2007.03676.x | A- | Molchan, random = 0.5 |
| 3 | Holliday, Nanjo, Tiampo, Rundle, Turcotte 2005 | Earthquake forecasting and its verification | Nonlinear Processes in Geophysics 12 | https://arxiv.org/abs/cond-mat/0508476 | A- | RI = persistence reference |
| 3 | Platt, Obala, MacIntyre, Otsyula, O'Meara 2018 | Malaria hotspot stability | Scientific Reports 8 | https://doi.org/10.1038/s41598-017-13801-6 | A- | recurrence ratio |
| 3 | Weisburd, Bushway, Lum, Yang 2004 | Trajectories of crime at places | Criminology 42 | https://doi.org/10.1111/j.1745-9125.2004.tb00521.x | M | place stability |
| 3 | Roberts, Lean 2008 | Fractions skill score | Monthly Weather Review 136 | https://doi.org/10.1175/2007MWR2123.1 | M | spatial verification |
| 3 | Gilleland, Ahijevych, Brown, Casati, Ebert 2009 | Spatial forecast verification intercomparison | Weather and Forecasting 24 | https://doi.org/10.1175/2009WAF2222269.1 | M | spatial verification |
| 4 | Page 1954 | Continuous inspection schemes | Biometrika 41 | https://doi.org/10.1093/biomet/41.1-2.100 | M | CUSUM |
| 4 | Lorden 1971 | Procedures for reacting to a change in distribution | Ann. Math. Statist. 42 | https://doi.org/10.1214/aoms/1177693055 | A- | change detection |
| 4 | Pollak 1985 | Optimal detection of a change in distribution | Ann. Statist. 13 | https://doi.org/10.1214/aos/1176346587 | A- | delay vs ARL, formal |
| 4 | Moustakides 1986 | Optimal stopping times for detecting changes | Ann. Statist. 14 | https://doi.org/10.1214/aos/1176350164 | A- | CUSUM optimality |
| 4 | Lucas 1985 | Counted data CUSUMs | Technometrics 27 | https://doi.org/10.1080/00401706.1985.10488030 | A- | Poisson CUSUM |
| 4 | Fawcett, Provost 1999 | Activity monitoring | KDD '99 | https://doi.org/10.1145/312129.312195 | M | AMOC origin |
| 4 | Jiang, Cooper, Neill 2009 | Generalized AMOC curves | AMIA Annu. Symp. Proc. | https://www.cs.nyu.edu/~neill/papers/gamoc.pdf (PMC2815453) | A | AMOC construction, miss = D + P |
| 4 | Fraker, Woodall, Mousavi 2008 | Performance metrics for surveillance schemes | Quality Engineering 20 | https://doi.org/10.1080/08982110701810444 | A- | non-reset signal events |
| 4 | Kleinman, Abrams 2006 | Sensitivity, specificity and timeliness | Stat. Methods Med. Res. 15 | https://doi.org/10.1177/0962280206071641 | A- | timeliness ROC |
| 4 | Kulldorff 2001 | Prospective time periodic geographical surveillance (scan) | J. R. Stat. Soc. A 164 | https://doi.org/10.1111/1467-985x.00186 | A- | prospective scan |
| 4 | Neill, Moore, Sabhnani, Daniel 2005 | Detection of emerging space-time clusters | KDD '05 | https://doi.org/10.1145/1081870.1081897 | A- | emerging clusters, injected outbreaks |
| 5 | Koenig, Smirnov 1997 | Sensor-based planning with the freespace assumption | ICRA 1997 | https://doi.org/10.1109/robot.1997.606883 | A- | freespace assumption |
| 5 | Stentz 1994 | Optimal and efficient path planning for partially-known environments (D\*) | ICRA 1994 | https://doi.org/10.1109/robot.1994.351061 | A- | replanning on discovery |
| 5 | Koenig, Likhachev 2002 | D\* Lite | AAAI 2002 | http://idm-lab.org/bib/abstracts/Koen02e.html | A | unknown cells assumed traversable |
| 5 | Ma, Kumar, Koenig 2017 | Multi-agent path finding with delay probabilities | AAAI 2017 | https://arxiv.org/abs/1612.05309 | A | move fails with p, robot stays put |
| 5 | Shofer, Shani, Stern 2023 | MAPF under obstacle uncertainty | ICAPS 2023 | https://doi.org/10.1609/icaps.v33i1.27219 | A | obstacles sensed on proximity |
| 5 | Malka, Shani, Stern 2024 | Online planning for MAPF in inaccurate maps | IROS 2024 | https://doi.org/10.1109/iros58592.2024.10801975 | A- | inaccurate maps |
| 5 | Parimi, Chan, Zhang, Chen, Williams 2026 | Belief-aware MAPF under map uncertainty (MAGIC) | arXiv preprint, under review | https://arxiv.org/abs/2609.40269 | A- | belief to planner costs |
| 5 | Papadimitriou, Yannakakis 1991 | Shortest paths without a map | Theoretical Computer Science 84 | https://doi.org/10.1016/0304-3975(91)90263-2 | M | Canadian Traveller |
| 5 | Hönig, Kiesel, Tinka, Durham, Ayanian 2019 | Persistent and robust execution of MAPF schedules in warehouses | IEEE RA-L 4(2) | https://doi.org/10.1109/lra.2019.2894217 | A- | ADG execution robustness |
| 5 | Atzmon, Stern, Felner, Wagner, Barták, Zhou 2020 | Robust multi-agent path finding and executing | JAIR 67 | https://doi.org/10.1613/jair.1.11734 | A- | k-robust plans |
| 5 | Li, Tinka, Kiesel, Durham, Kumar, Koenig 2021 | Lifelong MAPF in large-scale warehouses (RHCR) | AAAI 2021 | https://arxiv.org/abs/2005.07371 | M | warehouse lifelong MAPF |
| 5 | Zhang, Jiang, Bhatt, Nikolaidis, Li 2024 | Guidance graph optimization for lifelong MAPF | IJCAI 2024 | https://doi.org/10.24963/ijcai.2024/35 | A- | learned edge weights |
| 5 | Zang et al. 2025 | Online guidance graph optimization for lifelong MAPF | AAAI 2025 | https://doi.org/10.1609/aaai.v39i14.33614 | A- | adaptive edge weights |
| 5 | Krnjaic et al. 2024 | Scalable MARL for warehouse logistics with robotic and human co-workers (TA-RWARE) | IROS 2024 per the arXiv comment | https://arxiv.org/abs/2212.11498 | A- | our simulator |

Not verified and kept out of the text: the RRI formula (Levine 2008), the difference between PEI and PEI\*, the
contents of Hunt 2016 (a dissertation, known only through NIJ), Lorden's worst-case delay formula, and the
Fawcett & Provost AMOC wording in their own paper (taken second-hand from Jiang et al. 2009). The Weisburd, Roberts &
Lean, Gilleland, Page, Papadimitriou and RHCR rows are metadata only and back no content claim above. The DOIs of
the Tarapore, Roberts & Lean, Gilleland, Papadimitriou, Stentz, Koenig & Smirnov and Malka rows were resolved on
Crossref in the main session after the passes.

## Absence claims and the queries behind them

Services: Crossref `query.bibliographic`, arXiv API, OpenAlex, WebSearch. Semantic Scholar was attempted for every
question and returned HTTP 429 every time. Google Scholar was not attempted.

- **HMM, isolation forest or autoencoder on fleet telemetry** (Q1). Crossref: "isolation forest anomaly detection
  mobile robot", "hidden Markov model fault detection mobile robot execution monitoring", "LSTM autoencoder anomaly
  detection mobile robot", "anomaly detection AGV operational data industrial logistics machine learning". arXiv:
  `abs:robot AND abs:telemetry AND abs:anomaly`, `abs:"anomaly detection" AND abs:warehouse AND abs:robots`.
- **Rebuilding blocker cause from telemetry** (Q1). Crossref: "stuck robot detection warehouse fleet", "blocked robot
  detection multi-robot traffic jam detection", "wait-for graph deadlock detection AGV". arXiv:
  `all:AGV AND all:deadlock AND all:detection`.
- **Exponentially decayed per-cell counts as a named baseline** (Q2). Crossref: "exponential decay kernel density crime
  hotspot baseline". WebSearch: "exponentially weighted / exponential smoothing baseline PAI self-exciting".
- **A per-lesson, pool-conditioned chance rate for persistence** (Q3). arXiv: `abs:"persistence baseline" AND
  abs:hotspot` (0 results), `hotspot AND crime AND baseline AND previous`. WebSearch: "hot spot persistence 'expected by
  chance' micro-place", "recapture rate index Levine hotspot stability next period".
- **A standard name for "time to clear"** (Q4). Crossref: the surveillance-metric queries in the report (Fraker,
  Kleinman, Frisén, Woodall). WebSearch: "activity monitoring operating characteristic AMOC false alarm time to
  detection".
- **A paper with per-cell, unknown delay probabilities** (Q5). arXiv: `ti:"delay probabilities"`,
  `ti:"multi-agent path finding" AND ti:uncertainty`, `ti:"robust multi-agent path finding"`. WebSearch: MAPF-OU
  Shofer ICAPS 2023, Malka IROS 2024.

Rerun these on Semantic Scholar when it is not rate limited, before any of these absences fronts a pitch or a paper.

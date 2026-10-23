# Literature check: is the stall analyser a reasonable baseline, and is its grading new? (2026-10-18)

Scope: the academic side of what the fleet stuck analyser does (README "Sprint 5" to "Sprint 10"). The vendor side is
[COMPETITION.md](COMPETITION.md). Five questions, one research pass each on 2026-10-18, WebSearch/WebFetch only, no
browser. Rules: `~/.claude/skills/outward-claim-discipline` (source ranks, provenance per claim). A condensed
query log is in `reports/wr-dev-lit-stall-detection.md`. The queries behind each
absence claim are listed at the end of this page.

**Search coverage, read this first.** The Semantic Scholar API answered HTTP 429 (rate limited) to every request in
all five passes, so **no Semantic Scholar search ran**. Google Scholar was not tried, because it blocks scripted access.
DBLP was behind a bot wall. The searches that did run were Crossref, arXiv API, OpenAlex, WebSearch and publisher or
author pages. This is a targeted check of about 60 papers, not a systematic review. Every absence below means "not
found in the queries listed", never "does not exist". *(Rule rewritten 2026-10-21, Part 7: an absence claim needs two
independent scholarly indexes, OpenAlex plus one of Semantic Scholar, dblp, Lens or CORE, before it fronts a pitch.
Semantic Scholar is no longer required. Which claims reach the bar: Part 7.)*

**Provenance.** Every paper in the table was looked up this session (Crossref DOI record, arXiv record, publisher page
or author page; verified@2026-10-18). The table marks which ones had their full text read and which only had their
metadata checked. A claim about a paper's content rests only on full-text or abstract reading. Preprints are marked.

## 1. Stall, deadlock and anomaly detection for robot fleets from telemetry

In the AGV and multi-robot papers found, a stall is detected at runtime in one of two ways: a no-progress rule
threshold, or a cycle search on a graph. ROS 2 Nav2's shipped progress checker flags a robot that moves less than
0.5 m in 10 s by default (Nav2 `simple_progress_checker.cpp`), the same shape as our rule "active order and no cell
change for 30 s". Graph methods build a wait-for or precedence graph and search it for cycles (Cho, Kumaran & Wysk
1995 for manufacturing, title only; Bonetti et al. 2026 for AGV fleets, adding nested acyclic deadlocks), and
Bonetti et al. read the edges from the traffic planner's internal state, not from telemetry. The Petri-net AGV
papers found (Wu & Zhou 2005; Fanti et al. 2015) are, by their titles, about avoiding deadlock by design rather than
detecting it in logs. Learned detectors appear for
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
half-life) per cell (`fleet/fleet_analyser/hotspot.py:148-163`), is the per-box ETAS intensity λ = μ + Σ θω e^(-ω(t - tᵢ))
of Mohler et al. 2015 with the background rate μ = 0 and the decay fixed, i.e. the prospective-hotspot family
without Bowers' spatial spread, that
Mohler et al. 2011 found loses to ETAS because it ignores "the background rate of crime". With our defaults (1 h
window, 1 h half-life) the weights only fall from 1 to 0.5, so the map is close to a plain one-hour count. Mapping:
our recall@K is their hit rate counted in cells against hidden truth instead of next-period events, and precision@K
divided by our chance rate (positives / 380) equals recall@K divided by K/380, which is PAI's form in cells, so at
fixed K and positives precision and recall are one result, not two. Our rank grade (is the cell in the top K of the
map recomputed at the horizon end, `fleet/fleet_analyser/forecast_grade.py` docstring) is a cell-count cousin of
PEI. Our chance line draws from all 380 candidate cells, the lenient null that Adepeju et al. reject as
"unfairly simplistic".

## 3. Grading location forecasts on the next window against chance, and persistence of flagged places

Three fields already grade location forecasts on the next window against chance: crime mapping (hotspots built from
Time 1 and scored on Time 2, Hu et al. 2018, where PAI = 1 is a randomly placed map), meteorology (the equitable
threat or Gilbert score subtracts the hits expected by chance, (hits+misses)(hits+false alarms)/total, JWGFVR
verification pages) and earthquake testing (Molchan diagrams, where a random alarm scores an area skill of 0.5,
Zechar & Jordan 2008). Hits divided by chance hits equals precision divided by the base rate, which is our lift when
"total" is the lesson's candidate pool, so the ETS chance term is the closest analogue found. Persistence of flagged
places is measured too: Hunt 2016 (OJP abstract) defines stability as the share of grid cells hot in two adjacent
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
open. The Canadian Traveller problem (Papadimitriou & Yannakakis 1991; description from the record and a search snippet,
paper not read) reveals blocked edges on arrival, and ours is
the stochastic, partly passable case where one failed try does not settle the cell. Execution-robustness work absorbs
delays without locating them (k-robust plans, Atzmon et al. 2020; action dependency graphs, Hönig et al. 2019). Only
`floor` is planner-blind in our setup, since active blocked cells and outages are passed to the planner as obstacles
(`src/warehouse_rl/disturb.py:462-465`). The nearest analogue of our analyser-to-planner loop is MAGIC (Parimi et
al. 2026, arXiv preprint, not peer reviewed), which pools robot observations into a shared passability belief and
hands "detour-aware costs" to a standard MAPF planner, while guidance graphs (Zhang et al. 2024; Zang et al. 2025)
are the precedent for planner edge weights but for congestion. A fitting name for our floor setting is "MAPF under
the freespace assumption with unknown per-cell delay probabilities". *(Corrected 2026-10-21, Part 5: the "delay
belongs to the place and is unknown" part is not new; Kita et al. 2023, https://arxiv.org/abs/2302.01489, give each
edge an unknown Gamma delay that the planner learns from traversals. Cite it with the name.)*

## What this means for us

The decayed-count map is a defensible baseline: it is the prospective-hotspot family (Bowers et al. 2004) that crime
forecasting uses as its standard comparison, and at our defaults it is close to a plain one-hour count. It is the weak
end of that literature, since Mohler et al. 2011 beat it by adding a per-cell background rate. The obvious next
comparison is therefore an ETAS-style per-cell model (Mohler et al. 2011, 2015), a background stall rate μ per cell
plus a fitted decay, scored with the same metrics on held-out seeds. Two cheaper changes should come first: draw the
chance line only from cells that ever had a stall (Adepeju et al. 2016), and add a persistence forecast as the
reference, because verification practice treats persistence, not chance, as the bar to beat. Grading location
forecasts on the next window against chance is standard in crime mapping (PAI), meteorology (ETS) and earthquake
testing (Molchan), our lift has the form of the ETS chance term, and our hot_cell lesson_persist is Hunt's (2016)
hotspot stability measure, so neither "graded forecasts" nor "persistence-graded lessons" is a novelty claim we can
make. Only the per-lesson, pool-conditioned chance rate was not found in the queries listed, a variation on a
standard idea, not a new kind of score. Time to detect should be
reported as an AMOC curve: delay against false alarms per hour, swept over K or a cost threshold, with misses
counted and false alarms measured on an undisturbed run that does not exist yet. The floor setting has a name and a
precedent, the freespace assumption plus MAPF delay probabilities indexed by cell and unknown, and the closest
analyser-to-planner loop is the MAGIC preprint. This check is limited by its search: no Semantic Scholar or Google
Scholar query ran.

## Contradiction sweep (2026-10-18)

README, `docs/SCOPE.md`, `docs/DEMO.md`, `docs/overview` and `docs/replay`
were grepped for novelty wording. One line is affected: `docs/overview/index.html:152` says "trend tools exist, this
one grades its own calls". It is scoped to products (fleet managers, trend tools), which COMPETITION.md covers, and
this page does not contradict it for vendors. Read as a general claim, though, it is not new in the academic
literature (section 3). Whether to reword it is the operator's call; it was not edited here.

## Papers

Read depth (not the skill's source ranks): A = the paper's own text, read this session; A- = abstract, publisher
record or a hosted summary page read; M = metadata only (authors, year and venue confirmed, content not read). All rows verified@2026-10-18.

| Q | Authors, year | Title (short) | Venue | URL | Read depth | Used for |
|---|---|---|---|---|---|---|
| 1 | Bonetti, Proia, Guidetti, Sabattini 2026 | Deadlock detection and resolution for AGV fleets *(2026-10-21, Part 7: Crossref and arXiv title this DOI "A traffic management system for large and heterogeneous vehicles in narrow industrial environments")* | Int. J. Robotics Research | https://doi.org/10.1177/02783649261470035 (arXiv 2609.10400) | A | graph cycle detection, self-scored |
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
| 2,3 | Hunt (Joel M.) 2016 | Do crime hot spots move? MAUP, MTUP and crime hot spot stability | dissertation, NCJ 250376 (OJP library abstract) | https://www.ojp.gov/library/publications/do-crime-hot-spots-move-exploring-effects-modifiable-areal-unit-problem-and | A- | stability = share of cells hot in two adjacent intervals, PEI |
| 3 | Levine 2008 | The "hottest" part of a hotspot | Security Journal 21 | https://doi.org/10.1057/sj.2008.5 | M | RRI (formula not obtained) |
| 3 | JWGFVR (WMO joint working group) | Forecast verification: methods (web resource) | web | https://jwgfvr.github.io/forecastverification | A (summarised fetch) | ETS chance term, persistence reference |
| 3 | Zechar, Jordan 2008 | Testing alarm-based earthquake predictions | Geophysical J. International 172 | https://doi.org/10.1111/j.1365-246X.2007.03676.x | A- | Molchan, random = 0.5 |
| 3 | Holliday, Nanjo, Tiampo, Rundle, Turcotte 2005 | Earthquake forecasting and its verification | Nonlinear Processes in Geophysics 12 | https://arxiv.org/abs/cond-mat/0508476 | A- | RI = persistence reference |
| 3 | Platt, Obala, MacIntyre, Otsyula, O'Meara 2018 | Malaria hotspot stability | Scientific Reports 8 | https://doi.org/10.1038/s41598-017-13801-6 | A- | recurrence ratio |
| 3 | Weisburd, Bushway, Lum, Yang 2004 | Trajectories of crime at places | Criminology 42 | https://doi.org/10.1111/j.1745-9125.2004.tb00521.x | M | place stability |
| 3 | Roberts, Lean 2008 | Scale-selective verification of rainfall accumulations from high-resolution forecasts of convective events | Monthly Weather Review 136 | https://doi.org/10.1175/2007MWR2123.1 | M | spatial verification |
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
full text of Hunt 2016 (only the OJP abstract was read), Lorden's worst-case delay formula, and the
Fawcett & Provost AMOC wording in their own paper (taken second-hand from Jiang et al. 2009). The Weisburd, Roberts &
Lean, Gilleland, Page and RHCR rows are metadata only and back no content claim above. Three M rows do back a
claim, and the text marks each one: Cho et al. 1995 and Wu & Zhou 2005 / Fanti et al. 2015 back statements made from
their titles, and Papadimitriou & Yannakakis 1991 backs the Canadian Traveller description, which comes from the
bibliography record and a search snippet. The DOIs of
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
- **A standard name for "time to clear"** (Q4). *(Weakened 2026-10-21, Part 5: alarm "Return To Normal".)* Crossref: the surveillance-metric queries in the report (Fraker,
  Kleinman, Frisén, Woodall). WebSearch: "activity monitoring operating characteristic AMOC false alarm time to
  detection".
- **A paper with per-cell, unknown delay probabilities** (Q5). *(Overturned 2026-10-21, Part 5: Kita et al. 2023,
  per edge.)* arXiv: `ti:"delay probabilities"`,
  `ti:"multi-agent path finding" AND ti:uncertainty`, `ti:"robust multi-agent path finding"`. WebSearch: MAPF-OU
  Shofer ICAPS 2023, Malka IROS 2024.

Rerun these on Semantic Scholar when it is not rate limited, before any of these absences fronts a pitch or a paper.
*(Superseded 2026-10-21: the bar is now two independent scholarly indexes, OpenAlex plus one of Semantic Scholar, dblp,
Lens or CORE; see Part 7.)*

## Part 2: fleet management, deadlock, utilisation, connectivity (2026-10-20)

Scope: the field the Sprint 12 lanes build into: S12A, a per-robot time budget, and S12B, a deadlock finder and a WiFi
gap map (laptop-scheduler `jobs/wr-lane-s12a-time-budget.md`, `jobs/wr-lane-s12b-deadlock-gapmap.md`; neither merged
when this was written). The rules are as in Part 1. One pass on 2026-10-20 with WebSearch and WebFetch only; the query
log is in `reports/wr-dev-lit-fleet-management.md`. **Coverage:** Semantic Scholar was not queried
and Google Scholar was not tried. Crossref answered 429 twice, and both lookups resolved on retry or by another route.
ACM, MDPI and ISO full texts returned 403, and VDI, ISO and SEMI texts are paywalled (only public contents pages,
abstracts and a corrigendum were read). Every absence means "not found in the queries in the report".

### 1. AGV / AMR deadlock detection and resolution

The classic line treats AGVs as a resource allocation system: zones or cells are the resources, and a deadlock is a
circular wait in the sense of Coffman, Elphick & Shoshani (1971). The canonical approaches are digraph and Petri-net
avoidance (Fanti et al. 1997; Fanti, Maione & Turchiano 2000; Wu & Zhou 2005, Part 1), banker's-algorithm avoidance
(Lawley, Reveliotis & Ferreira 1998; Reveliotis 2000 for AGV conflicts), zone control (Ho & Liao 2009) and time-window
routing (Kim & Tanchoco 1991; ter Mors et al. 2010). Vis (2006) and Qiu et al. (2002) survey the field. The
often-cited review by Fazlollahtabar & Saidi-Mehrabad (2013) is **retracted**. Almost all of this work *avoids*
deadlock in the controller. Detection means searching the controller's own wait-for graph for cycles (Cho et al. 1995;
Bonetti et al. 2026, Part 1).

The modern line has the same split. RHCR resolves collisions only within a bounded horizon (Li et al. 2021), and the
RHCR and traffic-flow (Chen et al. 2024) abstracts do not mention deadlock. Open-RMF sends conflicts to a "negotiation
between the fleet managers", warns that fleets outside it "will likely result in deadlocks", and fires a
`deadlock_callback` "when a deadlock has occurred due to an unresolvable conflict" ("Human intervention may be
required"), a negotiation signal, not one read from positions. Grover, Liu & Sycara define deadlock as "an equilibrium
of system dynamics that causes the robots to stall". No method was found that detects robot deadlock **from logs** of
observed state rather than planner or negotiation state (about three queries).

**Names.** "A cycle in the robot-blocks-robot graph" is the standard **circular wait** in a **wait-for graph**. In the
AND model, "A deadlock occurs in a schedule if and only if there is at least one cycle in the wait-for graph"; in the
OR model a deadlock needs a **knot** (Wikipedia, wait-for graph). The ">= T seconds" persistence has **no standard
name or definition** in anything found; Open-RMF's callback is event-based. The traffic analogue is **gridlock**, "an
extreme traffic state where vehicle cannot move at all", formed by a "congestion loop" (Qi et al. 2015). **Our word
"knot" collides with the standard term.** A knot is a node set where "every vertex in the knot has outgoing edges" and
"all outgoing edges from vertices in the knot have other vertices in knot as destinations" (U. Iowa notes; Misra &
Chandy 1982 call it "a useful concept in deadlock detection"; Holt 1972 not read, ACM 403). In the S12B graph each
robot has at most one blocker, so a knot is exactly a cycle, which the lane calls a *deadlock*. The lane's acyclic
chain is the opposite of a knot. No formal name for an acyclic chain was found. *(Corrected 2026-10-21, Part 5:
Andersson & Veldhuis 2025, a Chalmers MSc thesis with Kollmorgen, call them "blocking graphs" of "causal chains".)* Fanti et al. 1997's **second level
deadlocks** "inevitably evolve to circular waits" (snippet only), a forecast, not a chain; Bonetti et al. 2026's
**nested acyclic deadlocks** are deadlocks. The plain term is **blocking chain**, with chain length as its depth.

### 2. Fleet KPIs and utilisation

**VDI** guidelines are paywalled; only contents pages, abstracts and a corrigendum were read. VDI 3581 (2004) derives
availability from Einschaltzeit (operating plus standby) and Ausfallzeit; its corrigendum combines units in series as
η_S = η5·η12·η13·η14 and in parallel as η_S = η5·(1 − μ12·μ13·μ14). VDI 3649 defines availability as the probability
of finding a system "in einem funktionsfähigen Zustand" (quoted by Follert & Nagel 2006, who note that short local
disturbances cut throughput without moving time-based availability). VDI 4486 (2012) measures availability by "waiting
times or lead times", the closest VDI idea to a time budget. VDI 2510 (2025 draft, pp. 1-3) has no chapter on KPIs or
time categories, and VDI 4451 Blatt 7's §4.3.3 "Statistik" is behind the paywall. **No VDI or ISO taxonomy that
separates waiting from blocked was found**; ISO 3691-4 covers safety only.

**Equipment-state standards.** SEMI E10 has "six mutually exclusive, basic equipment states": productive, standby,
engineering, scheduled downtime, unscheduled downtime and non-scheduled. Standby "includes such equipment states as no
operator available, no product available" (names from patent US5740429, which cites an older edition). ISO 22400-2,
read via OPC 40001-1 C.2, separates production time APT, delay time ADET ("out of service while an order is
registered") and down time ADOT. The one OEE adaptation for AGVs found is "Overall Transport Efficiency" (Foit et al.
2020, abstract).

**VDA 5050** (3.0.0 and 2.1.0) has **no robot state taxonomy**: no busy or waiting field, WAITING only as an action
status. `driving` means driving "(manual or automatic)"; "Other movements (e.g., lift movements) are not included".
`paused` leaves the robot able to "resume the order". Idle is derived (line 1241): `nodeStates` and `edgeStates` empty
and all actions "either 'FINISHED' or 'FAILED'". `operatingMode` (3.0) adds STARTUP and INTERVENED to AUTOMATIC,
SEMIAUTOMATIC, MANUAL, SERVICE, TEACH_IN. `errorLevel` WARNING and URGENT are "able to continue active order",
CRITICAL and FATAL are not (line 1899). *(Corrected 2026-10-21, Part 5 §4: that line is 3.0.0 only; 2.1.0 has
`errorLevel` "Enum {'WARNING', 'FATAL'}" (line 1137), as Part 4 §2 found.)* **Fleet managers:** openTCS has UNKNOWN, UNAVAILABLE, ERROR, IDLE, EXECUTING,
CHARGING (plus AWAITING_ORDER / PROCESSING_ORDER); Open-RMF `RobotMode` has IDLE, CHARGING, MOVING, PAUSED, WAITING,
EMERGENCY, DOCKING, ADAPTER_ERROR and others; no vendor definitions were found (MiR, ANT, NDC8, Locus).

**AGV simulation.** Standridge (ch. 17) counts utilisation as "loaded travel time, travel time while empty, blocked
time, load time, and unload time", with idle kept separate. Blocking delays "could account for 2%-20% of the
transaction cycle times" (Roy et al. 2016).

**Taxonomy to adopt:** the SEMI E10 classes on top, with VDA 5050 fields as the evidence.

| our bucket (S12A) | adopt as | standard anchor | where ours disagrees |
|---|---|---|---|
| `moving` | productive: travel | VDA `driving`; Standridge loaded/empty travel | none |
| `waiting_station` | productive: load/unload, or standby: queued | Standridge counts load/unload as utilised; `driving` excludes lift moves | mixes being served with queueing; the stream cannot split them without action states |
| `waiting_shelf` | standby: no operator | SEMI E10 "no operator available" | name it "waiting for picker" |
| `stuck` | blocked (>= 30 s) | Standridge "blocked time"; ISO delay time | the 30 s is ours (Nav2 uses 0.5 m / 10 s, Part 1); no standard |
| `stopped_short` | blocked: congestion wait | Standridge congestion | none |
| `faulted` | unscheduled downtime | SEMI E10; ISO ADOT; openTCS ERROR | ours is "errors non-empty"; WARNING/URGENT robots keep driving, so only CRITICAL/FATAL should count (our emitter writes only FATAL, `fleet/fleet_analyser/emitter.py:92`) |
| `idle` | standby: no work | VDA §6.6.8; openTCS AWAITING_ORDER | ours tests `orderId` empty, VDA tests empty node/edge/action states |
| (missing) | charging, paused / e-stop, manual mode, no data | openTCS CHARGING/UNKNOWN; RMF PAUSED/EMERGENCY; VDA `paused`, `operatingMode`, HIBERNATING | a paused robot with an order lands in `stuck`; seconds inside a message gap get a state nobody observed |

### 3. Congestion and throughput metrics

Lifelong MAPF reports **throughput**, "the average number of goal locations visited per timestep" (RHCR). The League
of Robot Runners scores "the throughput of a solution over the best throughput among all solutions submitted" (Jiang
et al. 2024; no organisers' paper was found), and guidance-graph work reports throughput only (Zhang et al. 2024).

Congestion enters as a **planning cost**. Chen et al. 2024 define vertex congestion as "the least total delay that
will occur assuming all agents enter the vertex at the same time". Two position-only measures were found: Arita &
Okumura 2026 (preprint) plot a "heatmap of vertex stop counts" and fail an episode "once the number of non-moving
agents exceeds half of the team", and Standridge counts the "average number of AGV's waiting due to contention for
control points". No "wait ratio" or "congestion index" standard was found. RWARE reports returns only (Papoudakis et
al. 2021); TA-RWARE reports "pick rate, defined as order-lines per hour" (Krnjaic et al., which gives no seconds per
step: our 5 s is from upstream `scripts/run_heuristic.py:56`, `docs/SCOPE.md:46`); Kiva reports field productivity
and no congestion metric (Wurman et al. 2008). Our per-cell stop counts (S8 cost map) match the one MAPF example;
neither is a benchmark standard.

### 4. Connectivity mapping from robot telemetry

Robots map radio coverage from **signal strength**: Gaussian-process maps (Fink & Kumar 2010, snippet
only), RCAMP's online radio map with self-repair after loss (Caccamo et al. 2017), and an AGV
coverage-hole map (Zarour et al. 2023). Location-tagged **packet loss** comes from **active tests**. O'Brien et al.
2025 log "latency, packet loss, bandwidth ... continuously" with "spatial localization". Simbe US11897148B2 records
"latency, throughput, packet loss, signal strength" by location into a heatmap and scans it for "dead zones". **No
passive inference of dead zones from gaps in ordinary telemetry, which is what the S12B gap map does, was found.**

VDA 5050 supports the signal and limits it. headerId is "incremented by 1 with each sent (but not necessarily
received) message", per topic (line 1458), so a jump is a loss; state goes out "when relevant events occur or at least
every 30 seconds" (line 1034), so a time gap alone is not. The heartbeat is the MQTT last will: the `connection` topic
(QoS 1; `state` is best effort) reports ONLINE, OFFLINE, HIBERNATING or CONNECTION_BROKEN, the last "detected via a
heartbeat that is exchanged between the broker and the client". On disconnect the robot "keeps all the order
information and fulfills the order up to the last released node" (line 187), so a gap is not a stop, a drop shorter
than the keepalive leaves only the headerId jump, and HIBERNATING stops messages on purpose. How Open-RMF handles lost
state updates is an unanswered forum question (2026-08-31).

### 5. Log-based fleet analytics in the literature

Analyses of real AGV/AMR logs are few and small. **No public multi-robot warehouse fleet log with positions, errors
and sequence numbers was found.** What exists:

| dataset | fleet | contents | size | available |
|---|---|---|---|---|
| MoRoOp, Klein & Jeong 2026 | 1 AMR, laboratory kit supply | jobs, dispatch events, robot state (pose, velocity, battery), delays, failed navigation *(corrected 2026-10-21, Part 5 §4: "delays" and "failed navigation" are phenomena, not tables, per Part 2b)* | 9 × 8 h shifts, 1,382 jobs, 140,386 state rows *(raw; 137,427 cleaned, Part 2b §1)* | CC BY 4.0, Hugging Face parquet |
| Sharma 2026, Zenodo | 1 real AGV + simulated traffic | OPC UA telemetry | 13 sessions, 25,976 1-s records | CC BY 4.0 |
| AI4Mobile, Hernangómez et al. 2024 | 3 AGVs (10 h); 1 cleaning robot (16 h) | radio quality, delay, throughput, positions | as stated | IEEE DataPort, login, licence not stated |

WINGS ICT (Zenodo, CC BY 4.0) has one AGV's location; no data was found for Benecki et al. 2024 (Part 1). MoRoOp, the
first real AMR log in either part, can exercise the time budget but not deadlock or congestion: one robot, and by its
own scope no multi-vehicle effects. AI4Mobile alone pairs positions with radio measurements, so it is the one public
place a gap map could be checked.

### What this means for us (Part 2)

**Time budget: standard, with names we should use.** SEMI E10 (productive / standby / unscheduled downtime),
Standridge (travel / blocked / load-unload / idle) and VDI 4486 (availability by waiting time) already cover it; the
seven buckets are a fleet specialisation, not a new metric. Two fixes follow: `faulted` should need errorLevel
CRITICAL or FATAL, since VDA 5050 robots with WARNING or URGENT continue their order, and seconds with no message need
their own bucket (paused, charging and manual mode later). **Deadlock finder: standard, with a name.** A persisting
cycle is a circular wait in a wait-for graph (Cho et al. 1995; Bonetti et al. 2026); T is our parameter, not part of
the definition. **Stop calling the acyclic chain a "knot"**: in deadlock theory a knot is the closed set that *is* the
deadlock, so rename it "blocking chain" in code, JSON and README table (p) before any number is written. Bonetti et
al. 2026, which also finds nested acyclic deadlocks, is the method to compare against; ours differs only in reading
edges from observed state. **Gap map: not found in its passive form.** Active packet-loss maps (O'Brien et al. 2025;
Simbe) measure the link directly and are the stronger method wherever a robot can run probes. Table (p) should say
"message-loss cells inferred from headerId gaps", not "WiFi dead zones": a VDA 5050 robot keeps driving through a
disconnect, and a broker- or consumer-side drop leaves the same gap with no location cause. Vocabulary for (o) and
(p): "wait-for graph", "circular wait (deadlock)", "blocking chain", productive / standby / blocked / downtime, and
MAPF "throughput" for jobs per robot-hour. Stop claiming deadlock detection or a robot time budget as ours: only the
from-logs, no-planner-access setting of each was not found, and that absence rests on a few queries.

### Papers and sources (Part 2)

All rows verified@2026-10-20. Read depth: A = text read (A\* = through a summarising fetch, wording not grep-checked);
A- = abstract or record page; M = metadata only; S = search snippet only.

| § | Authors / org, year | Title (short) | Venue | URL | Read | Used for |
|---|---|---|---|---|---|---|
| 1 | Coffman, Elphick, Shoshani 1971 | System deadlocks | ACM Computing Surveys 3(2) | https://doi.org/10.1145/356586.356588 | M | deadlock conditions |
| 1 | Holt 1972 | Some deadlock properties of computer systems | ACM Computing Surveys 4(3) | https://doi.org/10.1145/356603.356607 | M (403) | knot origin, wording not read |
| 1 | Misra, Chandy 1982 | A distributed graph algorithm: knot detection | ACM TOPLAS 4(4) | https://doi.org/10.1145/69622.357190 | A- | knot in deadlock detection |
| 1 | U. Iowa 22C:116 (Jones) | Lecture notes 08, deadlock | course page | https://homepage.divms.uiowa.edu/~jones/opsys/spring02/notes/08.html | A | knot definition |
| 1 | Wikipedia | Wait-for graph | web | https://en.wikipedia.org/wiki/Wait-for_graph | A | cycle / knot, AND / OR |
| 1 | Fanti, Maione, Mascolo, Turchiano 1997 | Event-based feedback control for deadlock avoidance in FPS | IEEE T-RA 13(3) | https://doi.org/10.1109/70.585898 | M (+S) | second level deadlock |
| 1 | Fanti, Maione, Turchiano 2000 | Comparing digraph and Petri net approaches to deadlock avoidance | IEEE T-SMC-B 30(5) | https://doi.org/10.1109/3477.875452 | M | Petri net vs digraph |
| 1 | Lawley, Reveliotis, Ferreira 1998 | Banker's algorithm for deadlock-free buffer allocation in FMS | Int. J. Flexible Manuf. Syst. 10 | https://doi.org/10.1023/a:1007969601583 | M | banker's algorithm |
| 1 | Reveliotis 2000 | Conflict resolution in AGV systems | IIE Transactions 32(7) | https://doi.org/10.1080/07408170008967423 | M | AGV conflicts |
| 1 | Kim, Tanchoco 1991 | Conflict-free shortest-time bidirectional AGV routeing | Int. J. Production Research 29(12) | https://doi.org/10.1080/00207549108948090 | M | time windows |
| 1 | ter Mors, Witteveen, Zutt, Kuipers 2010 | Context-aware route planning | MATES 2010 (LNCS) | https://doi.org/10.1007/978-3-642-16178-0_14 | M | time windows |
| 1 | Ho, Liao 2009 | Zone design and control in a zone-control AGV system | Computers & Industrial Eng. 56(1) | https://doi.org/10.1016/j.cie.2008.07.007 | M | zone control |
| 1 | Vis 2006 | Survey of research in design and control of AGV systems | EJOR 170(3) | https://doi.org/10.1016/j.ejor.2004.09.020 | M | survey |
| 1 | Qiu, Hsu, Huang, Wang 2002 | Scheduling and routing algorithms for AGVs: a survey | Int. J. Production Research 40(3) | https://doi.org/10.1080/00207540110091712 | M | survey |
| 1 | Fazlollahtabar, Saidi-Mehrabad 2013 | AGV scheduling and routing: a review | J. Intell. Robot. Syst. **RETRACTED** | https://doi.org/10.1007/s10846-023-01923-1 | M | do not cite |
| 1,3 | Li, Tinka, Kiesel, Durham, Kumar, Koenig 2021 | Lifelong MAPF in large-scale warehouses (RHCR) | AAAI 2021 | https://arxiv.org/abs/2005.07371 | A | bounded horizon; throughput |
| 1,3 | Chen, Harabor, Li, Stuckey 2024 | Traffic flow optimisation for lifelong MAPF | AAAI 2024 | https://doi.org/10.1609/aaai.v38i18.30054 | A\* | congestion as planning cost |
| 1 | Grover, Liu, Sycara 2022 (arXiv) | The before, during and after of multi-robot deadlock | IJRR (WAFR 2020 issue) | https://arxiv.org/abs/2206.01781 | A- | dynamic definition |
| 1 | Open-RMF | RMF core (book) and `EasyTrafficLight::Blocker` API | docs | https://osrf.github.io/ros2multirobotbook/rmf-core.html ; https://openrmf.readthedocs.io/projects/rmf-ros2/en/latest/api/classrmf__fleet__adapter_1_1agv_1_1EasyTrafficLight_1_1Blocker.html | A | negotiation, `deadlock_callback` |
| 1 | Qi et al. 2015 | Spatial development of urban road network traffic gridlock | Int. J. Civil Engineering 13(4) | https://ijce.iust.ac.ir/article-1-1010-en.html | A | gridlock |
| 2 | VDI 2004 (+2006 corrigendum) | VDI 3581 Availability of transport and storage systems | VDI guideline | https://www.vdi.de/fileadmin/pages/vdi_de/redakteure/richtlinien/inhaltsverzeichnisse/9774307.pdf | A- (contents, corrigendum) | availability formulas |
| 2 | VDI 2012 | VDI 4486 Performance availability | VDI guideline | https://vdi.de/richtlinien/details/vdi-4486-reliability-for-intralogistics-performance-availability | A- | waiting-time availability |
| 2 | VDI 2025 (draft) | VDI 2510 Fahrerlose Transportsysteme | VDI guideline | https://www.vdi.de/2510 | A (pp. 1-3) | no KPI chapter |
| 2 | VDI 2005 | VDI 4451 Blatt 7 Leitsteuerung für FTS | VDI guideline | https://vdi.de/richtlinien/details/vdi-4451-blatt-7-compatibility-of-automated-guided-vehicle-systems-agvs-agvs-guidance-control-system | A- (contents) | §4.3.3 Statistik |
| 2 | Follert, Nagel 2006 | Verfügbarkeit intralogistischer Systeme | Logistics Journal | https://edrev.logistics-journal.de/article/download/114/116/1044 | A | VDI 3649 quote, critique |
| 2 | SEMI 2022 | E10 Equipment RAM and utilization | SEMI standard (store page) | https://store-us.semi.org/products/e01000-semi-e10-specification-for-definition-and-measurement-of-equipment-reliability-availability-and-maintainability-ram-and-utilization | A- | six states |
| 2 | AMD, US5740429 (1998) | Equipment state tracking (cites SEMI E10) | patent | https://patents.google.com/patent/US5740429 | A\* | E10 state names, standby |
| 2 | OPC Foundation | OPC 40001-1 Annex C.2 (ISO 22400-2 times) | spec page | https://reference.opcfoundation.org/specs/OPC-40001-1/c-2 | A\* | APT / ADET / ADOT |
| 2 | Foit, Gołda, Kampa 2020 | OEE metrics for AGV intra-logistics | Processes 8(12) | https://doi.org/10.3390/pr8121648 | A- | Overall Transport Efficiency |
| 2,4 | VDA / VDMA | VDA 5050 v3.0.0 (main) and 2.1.0 | spec, GitHub | https://github.com/VDA5050/VDA5050/blob/main/VDA5050_EN.md | A (grepped) | fields, idle, errorLevel, headerId, connection |
| 2 | openTCS | `Vehicle.java` (master) | source | https://github.com/openTCS/opentcs/blob/master/opentcs-api-base/src/main/java/org/opentcs/data/model/Vehicle.java | A\* | vehicle states |
| 2 | Open-RMF | `RobotMode.msg` | source | https://github.com/open-rmf/rmf_internal_msgs/blob/main/rmf_fleet_msgs/msg/RobotMode.msg | A\* | robot modes |
| 2 | Standridge n.d. | Beyond Lean, ch. 17 AGV systems | open textbook (LibreTexts) | https://eng.libretexts.org/Bookshelves/Industrial_and_Systems_Engineering/Beyond_Lean_-_Simulation_in_Practice_(Standridge)/17%3A_Automated_Guided_Vehicle_Systems | A\* | utilisation, congestion |
| 2 | Roy, Krishnamurthy, Heragu, Malmborg 2016 | Blocking in AVS/RS | Eur. J. Industrial Eng. 10(1) | https://ideas.repec.org/a/ids/eujine/v10y2016i1p51-80.html | A- | blocking 2-20% |
| 3 | Jiang, Zhang, Veerapaneni, Li 2024 | Scaling lifelong MAPF (Robot Runners) | SoCS 2024 | https://arxiv.org/abs/2404.16162 | A\* | competition score |
| 3 | Zhang, Jiang, Bhatt, Nikolaidis, Li 2024 | Guidance graph optimization | IJCAI 2024 | https://arxiv.org/abs/2402.01446 | A- | throughput |
| 3 | Arita, Okumura 2026 | Lifelong LaCAM with local guidance | arXiv preprint | https://arxiv.org/abs/2605.16855 | A\* | stop-count heatmap, failure rule |
| 3 | Papoudakis, Christianos, Schäfer, Albrecht 2021 | Benchmarking multi-agent deep RL | NeurIPS 2021 D&B | https://arxiv.org/abs/2006.07869 | A | RWARE returns |
| 3 | Krnjaic et al. 2024 | TA-RWARE (Part 1 row) | IROS 2024 per arXiv | https://arxiv.org/abs/2212.11498 | A (grepped) | pick rate, no s/step |
| 3,5 | Wurman, D'Andrea, Mountz 2008 | Coordinating hundreds of autonomous vehicles in warehouses | AI Magazine 29(1) | https://doi.org/10.1609/aimag.v29i1.2082 | A | Kiva field results |
| 4 | Fink, Kumar 2010 | Online methods for radio signal mapping with mobile robots | ICRA 2010 | https://ieeexplore.ieee.org/document/5509574 | S | RSSI mapping |
| 4 | Caccamo, Parasuraman, Freda, Gianni, Ögren 2017 | RCAMP | IROS 2017 | https://arxiv.org/abs/1710.09303 | A- | radio map, self-repair |
| 4 | Zarour, Tayade, Melnyk, Schotten 2023 | Coverage hole elimination in industrial environment | VTC2023-Spring | https://arxiv.org/abs/2311.04011 | A- | coverage holes for AGVs |
| 4 | O'Brien, Dooley, Penica, McGrath, O'Connell 2025 | Real-time diagnostics of 5G and Wi-Fi using mobile robotics | J. Sensor Actuator Netw. 14(6) | https://doi.org/10.3390/jsan14060110 | A- | active packet-loss map |
| 4 | Simbe Robotics, US11897148B2 (2024) | Network coverage testing by a mobile robot | patent | https://patents.google.com/patent/US11897148B2 | A\* | dead-zone heatmap |
| 4 | Open Robotics Discourse 2026 | RMF and lost state updates (thread 57782) | forum | https://discourse.openrobotics.org/t/57782 | A\* | unanswered |
| 4,5 | Hernangómez et al. 2024 | AGV communication and sensor measurement datasets | IEEE Comm. Magazine 62(4) | https://arxiv.org/abs/2301.03364 | A- | radio + positions data |
| 5 | Klein, Jeong 2026 | MoRoOp: AMR operations dataset | arXiv preprint (submitted to Sci. Data) | https://arxiv.org/abs/2610.02428 ; https://huggingface.co/datasets/Self-Organizing-Production-Logistics/MoRoOp | A- (+HF file list) | the one real AMR log |
| 5 | Sharma 2026 | Availability-aware integration of dispatched plans and AGV execution | Zenodo dataset | https://doi.org/10.5281/zenodo.23393677 | M | 1 AGV + sim |
| 5 | WINGS ICT 2023 | Use case 3 datasets | Zenodo dataset | https://doi.org/10.5281/zenodo.10204117 | M | 1 AGV location |

Not verified and kept out of the text: Holt's own knot wording; the current SEMI E10 / E79 and ISO 22400-2 texts; VDI
3581's per-element formula and VDI 4451-7 §4.3.3; Foit et al.'s OEE definitions; vendor state models; openTCS, Nav2
and AWS RoboRunner behaviour on lost connection; MoRoOp's "stuck reason" field (summarised fetch only). The S row
(Fink & Kumar) backs only "RSSI mapping exists". Rerun the absence claims on Semantic Scholar before any of them
fronts a pitch.

## Part 2b: MoRoOp and single-robot operation logs (2026-10-21)

Scope: the check before S13A (laptop-scheduler `jobs/wr-lane-s13a-moroop-budget.md`). WebFetch, WebSearch, curl and the
GitHub API, no parquet downloaded; all fetches ran 2026-10-20 (the brief expected the 21st), hence `verified@2026-10-20`;
query log `reports/wr-dev-lit-moroop.md`. Ranks: **A** = paper full text or card; **A-** = counts the
Hugging Face viewer computed from the released files (`/info`, `/statistics`, `/first-rows`: beyond "card and file
listing", no parquet); **B** = authors' toolkit code or inferred from A; **F** = guess, do not use. **Overrides the Part 2
§5 MoRoOp row** (summarising fetch): "delays" and "failed navigation" are retained phenomena, not tables or columns, and
140,386 is the *raw* state-row total.

### 1. The dataset

Klein & Jeong, "Autonomous mobile robot operations in production logistics: a dataset of jobs, dispatch events and
robot states", arXiv 2610.02428v1, submitted to Scientific Data (https://arxiv.org/html/2610.02428v1, A,
verified@2026-10-20). One wheel.me AMR, KTH IPU lab, four stations, nine 8 h shifts on 27-31 Jul 2026 (30 Jul evening
excluded for a job-generator bug). Rule-based dispatch of stochastic jobs: kit supply (operations warehouse, kitting,
assembly, warehouse; inter-arrival Tri(225,250,275) s, due offset Tri(275,285,295) s), empty-box refill (assembly,
kitting), charging. Station times are triangular 5-25 s and "represent waiting periods of the AMR rather than
measurements of physical human work"; personnel "could cross or temporarily obstruct the planned trajectory";
multi-vehicle effects "are consequently not represented" (A). **Licence:** card `license: cc-by-4.0`, arXiv "License: CC
BY 4.0" (https://huggingface.co/datasets/Self-Organizing-Production-Logistics/MoRoOp, A, verified@2026-10-20). **Version:**
card "current release (1.0.0)", paper and toolkit 1.0.1 (pin HF revision `1.0.1`); version of record KTH
https://doi.org/10.71775/kth.vx0cq-w7h93; HF main sha `880a249d...`; 26.8 MB.

| table (per shift) | columns (paper Tables 3-6, A; dtypes from HF `/info`, A-) | meaning that matters here |
|---|---|---|
| `jobs` | id, created_at, payload (JSON job_type, kit_id), operations (JSON id list), state, outcome, termination_reason, release_date, start_time, due_date, finish_time | one row per job, final state; release/due are null on 39 of 154 jobs in 27 Jul morning (inferred: the non-kit-supply jobs, B) |
| `operations` | id, created_at, payload (JSON goal: warehouse / kitting / assembly / charging, opt. goal_soc), priority, job_id, dependencies, state, outcome, termination_reason, retry_count, start_time, finish_time | one row per operation; FAILURE rows carry termination_reason TIMEOUT |
| `dispatch_events` | id, created_at, event_type, operation_id, changes (JSON), meta_data (JSON) | operation_added / start_requested / started / completed / failed / start_denied, dispatcher paused / resumed / started / stopped; a failure's meta_data holds `elapsed_time`, `timeout_seconds: 300` |
| `robot_state_raw`, `robot_state_cleaned` | id, created_at, operating_mode, state, stuck_reason, pos_x, pos_y, pos_theta, velocity_x, velocity_y, velocity_omega, current_position_id, navigating_to_position_id, last_navigated_position_id, next_goal_timestamp, {tl,tr,bl,br}_charge_state, is_robot_charging, {tl,tr,bl,br}_charging, robot_uptime, diagnostics (JSON statuses with name / level / message) | cleaned = raw minus "invalid localization states or physically implausible values"; ids are kept, so a gap in `id` marks a removed row |

**Cadence:** "queried at a frequency of 1 Hz", a row stored "only when at least one reported value differed" (A), so
irregular: median 0.91 s, max 9.07 s in the first 81 rows; shift mean 1.85-1.99 s (A-); UTC, sub-second. **Poses:** "map
reference frame" (A), metres (B: toolkit label "Position x-coordinate (m)"), x 0.38-8.24, y -1.84-0.43 (A-): an 8 x 2.3 m
lab. `pos_theta` in ±π (radians, B); velocity m/s (B: toolkit label); `velocity_y` up to 0.20, so holonomic (B). **Named
positions:** "135, 136, 137, and 138 correspond to the charging station, warehouse, kitting station, and assembly station"
(A); no table carries station coordinates. **`stuck_reason` confirmed:** "Reported reason the robot was stuck, if any"
(A); values `None`, `ObstacleInTheWay`, `GoalObstructed` (A-), wheel.me enum names with no documentation found (one
search). `state`: Navigating, Idle, rarely Waiting / Paused / Nonautonomous / Initializing; `operating_mode`: Autonomous,
rarely Joystick / Reconnecting / Initializing / PoweredOff (A-).

**Authors' statistics:** Table 7 counts only; **no delay shares, stuck, failure or time-in-state figures** in the full text.
Per shift in order 27m 27e 28m 28e 29m 29e 30m 31m 31e:

| quantity | per shift | total | rank |
|---|---|---|---|
| jobs | 154 154 156 155 155 155 148 152 153 | 1,382 | A (Table 7) |
| operations | 536 535 540 538 541 539 520 533 533 | 4,815 | A |
| dispatch events | 2149 2145 2173 2159 2170 2167 2103 2149 2137 | 19,352 | A |
| state rows raw / cleaned | 15549/15194 15389/15038 15912/15553 15566/15252 15546/15182 15491/15168 15053/14711 15949/15635 15931/15694 | 140,386 / 137,427 | A |
| cleaned rows with stuck_reason ≠ None | 37 3 52 20 3 17 48 17 10 | 207 (raw: same) | A- |
| failed operations (TIMEOUT, ~300 s) = failed jobs | 0 1 0 0 0 1 2 3 1 | 8 | A- |
| operation_start_denied events | 2 2 6 3 3 5 9 7 2 | 39 | A- |
| state-row span (h) | 8.12 8.04 8.26 8.10 8.03 8.10 8.15 8.03 8.16 | 72.99 | A- |

### 2. Prior use

No time budget or stuck analysis found. Semantic Scholar record `citationCount` 0 (search 429 three times, a gap);
Google Scholar "MoRoOp": the paper, no "Cited by"; OpenAlex: 0 citations; HF: no models or spaces (485 downloads).
GitHub code search: the authors' toolkit (`JaFeKl/moroop-dataset-toolkit`, MIT, loaders + paper figures) and one third
party, `CrazyEther/robotization-agent-lab` `research/calibration/derive_moroop_transitions.py`, which only extracts
(state, is_robot_charging) transitions from one shift. The toolkit's `figures.py` `_segments` splits an operation into "navigating" (state Navigating), "station_process"
(non-Navigating after driving) and "latency" (before it): the authors' only time split, never published as numbers (B).
All verified@2026-10-20.

### 3. Single-robot log analyses elsewhere

| source (rank) | robot, setting | log size | states / measures | stuck definition | stuck / failure share |
|---|---|---|---|---|---|
| Lee et al. 2026, Digital Health, doi 10.1177/20552076261437181 (A, Europe PMC full text) | DOGU medication robot, Korea Univ. Guro hospital | 122 missions, 18-29 Jun 2025, logs at 1 Hz | elevator waiting time, elevator travel time, corridor navigation time per mission | "delivery failure was defined as the robot remaining stationary for > 1 min at any point or requiring manual assistance" | 87.03 % success; 14 failures (8 elevator blockage, 4 corridor self-drive, 2 call communication) |
| Hawes et al., STRANDS, IEEE RAM, doi 10.1109/MRA.2016.2636359 (arXiv 1604.04384, A, PDF) | SCITOS G5, care and security sites | 104 d 7 h cumulative, 8,444 tasks | total system lifetime; autonomy % = time "actively performing tasks" / time allowed | reset on "unrecoverable failure" or "unrequested expert intervention" | A% 38.80 / 18.27 / 53.51 / 51.10 % per deployment |
| Gerling et al. 2016, Z. Gerontol. Geriatr., doi 10.1007/s00391-016-1065-6 (A, Europe PMC) | SCITOS G5, Vienna care hospital | 30 days | qualitative issue categories from system logs | "stopped moving and ... after a significant waiting time (in the order of minutes) could not continue" vs "appeared to be stuck but continued" | "rare"; no share |
| Sharma 2026, Zenodo 10.5281/zenodo.23393677 (A-, record) | 1 real AGV + simulated traffic, OPC UA | 13 sessions, 25,976 1-s records, 342 dispatches | plan vs execution, per-second classification | not stated in record | not stated |

Not found: a published time-in-state share (moving / waiting / blocked / idle) of one real AMR or AGV from its logs
(queries on TUG / Aethon: press only; MiR case studies: throughput and distance, no utilisation; verified@2026-10-20). The
written rules are "stationary for > 1 min" (Lee 2026) and "minutes" (Gerling 2016); the S12A 30 s is tighter than both.

### 4. Column mapping verdict (for S13A task 2)

Rows: `robot_state_cleaned`, one `zone<k>-000.jsonl.gz` per shift. Whole-second UTC only (`fleet/fleet_analyser/parse.py:15`).

| our field | MoRoOp source and rule | conf. |
|---|---|---|
| `timestamp` | `created_at` floored to the second; keep the **last** row of each second (the state at the end of that second). Report rows collapsed, and how many collapsed rows had stuck_reason ≠ None | A (column) / rule ours |
| `headerId` | contiguous 1..n over the emitted messages, **not** `id` (gaps in `id` are screening removals, not lost messages); report removed-row count = max id − rows | B |
| `serialNumber`, `manufacturer` | constant `moroop-amr-1`, `wheel.me` | A (paper names the robot) |
| `orderId` | `job_id` of the operation running at t (`operations.start_time <= t < finish_time`); the ~1 s gaps between consecutive operations of one job keep that job's id. No overlap in the first 100 jobs and operations (A-); report overlap seconds, do not assert. Tabulate `job_type` first; charging jobs → `""`, seconds reported apart from `is_robot_charging` | A (columns) / B (rule) |
| `agvPosition{x,y,theta}` | `pos_x`, `pos_y` quantised to `--cell-m` (default 0.5 at this map size; report the four station cells and assert they are distinct), `pos_theta` | A frame, B units |
| `driving` | `hypot(velocity_x, velocity_y) > 0.05` m/s **or** `abs(velocity_omega) > 0.05` rad/s. VDA 5050 3.0 §3.3 has driving = "non zero translational and/or rotational velocity". Never `state == "Navigating"`, which stays on while the robot is blocked; report seconds where only omega counts | B |
| `paused` | `state == "Paused"` or `operating_mode != "Autonomous"` (17 cleaned rows, 27 Jul evening and 30 Jul morning; Joystick / Nonautonomous is VDA manual mode, folded in for lack of a bucket); report per value | A values / B meaning |
| `errors` | `[]` for S13A. Tabulate and report the diagnostics `level` values (only "Ok" in the first 81 rows; vocabulary undocumented). Any level → errorLevel mapping is F and not used; `stuck_reason`, TIMEOUTs and start_denied are never errors | F (mapping) |
| `loads` | `[]`: no payload column in robot state (inferring it from operation goals would be a guess) | A (absence) |
| stations file | per id 135..138 (paper's names), every cell holding ≥ 5 % of the `state == "Idle"` rows at that `current_position_id` (docking jitter: a 3-box kitting dwell averages ~30.7 s, so a missed cell turns it into stuck); report the share of those Idle rows outside the station set (target ≈ 0); `shelves: []`. `--stations auto` builds TA-RWARE layouts, **do not use** | A ids / B poses |

**Buckets.** From state rows: moving, idle, paused. State rows + jobs (orderId): waiting_station, stuck, stopped_short.
faulted: not computed in S13A. no_data: report the interval p50 / p99 / max, the largest gap inside any
stopped run, and the seconds S12C's 60 s rule would move. waiting_shelf (waiting for picker): **cannot be computed**, no
shelves or picker; report n/a, not 0. Job counts, failures, lateness (`finish_time − due_date`, kit supply only) and
dispatcher pauses need the **event tables**.

### 5. What this means for S13A

**Credible on one robot:** a per-shift time budget (moving / waiting_station / stuck / stopped_short / idle / paused, plus
charging seconds) and jobs per robot-hour: the pipeline runs on a real, irregularly sampled log. **Must not be claimed:**
anything multi-robot (deadlock, blocking chain, congestion, hotspot map, message-loss cells); the waiting_station share as
a finding (the generator sets it, "waiting periods ... rather than measurements"; check it against Table 1 only); "real
warehouse" (an 8 x 2.3 m lab moving toy bricks).

**Detection comparison (the robot's own label supports it).** Label episode = maximal run of consecutive native rows with
`stuck_reason ≠ "None"`, owning [first row ts, ts of the next `None` row), on the same whole-second grid. (a) Label seconds per our bucket (stuck,
stopped_short, waiting_station, moving, idle); `GoalObstructed` near a station may land in waiting_station. (b) A label
episode is **detected** if one of our stuck runs overlaps [label start, label end + 30 s]; split episodes at 30 s, since
shorter ones cannot reach `DEFAULT_STUCK_AFTER` = 30 (`fleet/fleet_analyser/detector.py:22`) and are not detector misses.
(c) Our stuck runs with no label episode within ±30 s are false alarms; say for each whether it overlaps a TIMEOUT
operation, a paused row or a station cell. The 8 TIMEOUT operations are a second, long-event label (B: the paper never
ties timeouts to obstruction): detected if a stuck run overlaps the operation's [start_time, finish_time].

**Sanity checks.** Exact: Table 7 rows per shift, the 207 label rows, the 8 failed operations. Within 5 %: unique non-empty
orderIds vs non-charging `jobs`; span per shift (8.03-8.26 h); jobs per robot-hour vs 1,382 / 72.99 h = 18.9.

## Part 3: are our negative results known? (2026-10-21)

Scope: three measured negative results, each set against published numbers for the same question: did someone beat
it, get the same, or not try? One pass on 2026-10-21 with WebSearch, WebFetch, curl to the arXiv / OpenAlex APIs and
`pdftotext` on downloaded PDFs, as three parallel research passes. The main session re-checked these numbers
against the PDF or abstract text: Stephanedes 1992, Pietrobon 2019, Jiang 2024 Table 3, Yu & Wolf (4.4 % and the
baseline sentence), Han & Yu Table I and the Pittsburgh MAVG 1.31. The query log is in
`reports/wr-dev-lit-negative-results.md`. **Coverage:** the Semantic Scholar API answered HTTP 429
once in each of the three passes, so again **no Semantic Scholar search ran**, and Google Scholar was not tried. ACM
and ScienceDirect full texts returned 403. Every absence means "not found in the queries listed". The rules are those
of Part 1. Read depth (A text read, A- abstract or record, M metadata, S snippet) is the rank column, as in Parts 1
and 2. The skill's A-F scale is written for vendor claims; for papers, peer-review status is stated per row
(preprint, patent, report). Every row is verified@2026-10-21.

### 1. Hidden blockage: early warning from fleet traces alone

Detecting a closure from traffic traces is studied for roads, not for robot fleets. HERE's method (Pietrobon,
Lewis & Heverly-Coulson 2019) "triggers an alert whenever the likelihood of the observed probe activity is too small
given a historical model", which is a per-segment Poisson test like our CUSUM, but it reports only precision. T-Closure
(Zhang et al. 2023, UESTC with Didi Chuxing) is supervised and uses the planned route, so it is not planner-blind. It
reports volume and delay, not a detection rate. Pan et al. 2013 detect anomalies from drivers' *route changes* (86.7 %
recall vs 46.7 % for a flow baseline) and leave out precision by design. Classic loop-detector incident detection
(AID) is the only field that reports detection rate, delay and false alarms together, and its
false-alarm rate is a share of station-intervals: Stephanedes et al. 1992 is the one source found that converts it to
false alarms per hour. Every AID incident is lane-scale, a much stronger signal than one blocked cell among 380.
Neill et al. 2005 (Part 1 §4, now read in full) report a floor: at 1 false positive a month, the injected outbreaks
they miss "consisted of a very small number of cases (less than 5 in total), and as a result there was essentially
no signal to detect". In robotics, the nearby work senses the obstacle on board (OSCAR, Sahak et al. 2026, preprint)
or is told where the anomaly is (Ogorelysheva et al. 2026, preprint). The road patents (HERE US 11270578, TomTom)
describe tests on *missing* traffic (elapsed time between probes, detour counts), not on stalls, and give no
evaluation numbers.

| Method (source) | Data | Detection rate | Delay | False alarms (unit) |
|---|---|---|---|---|
| Our decayed map K 20 (README (n), `amoc_blind.json`) | sim, 50 planner-blind blocked cells, 10 zones | 6 / 50 | median 295 s | 177.8 per zone-hour (flag-publishes) |
| Our short-memory map K 20 (`amoc_shortmap.json`) | same | 6 / 50 | median 402.5 s | 451.9 per zone-hour |
| Our CUSUM k 1 h 3 (`amoc_fast.json`) | same | 2 / 50 | median 525 s | 0.000 per zone-hour |
| Our CUSUM k 0 h 3, **in-sample tuned** (`reports/wr-lane-s10i-fast-detector.md:37`) | same, tuned on the 50 scored windows | 17 / 50 | median 425 s | 0.000 per zone-hour |
| Pietrobon et al. 2019, HERE (abstract only) | real probes, 12 metro areas | n/a (precision 92 % low-volume, 80 % overall) | n/a | n/a, precision only |
| T-Closure, Zhang et al. 2023 (abstract only) | real GPS + planned route | n/a ("7000+ closure events monthly") | "within 1.5 hours" | n/a |
| California #7 / #8 (TTI 2917-1F citing Payne) | real loop detectors | 67 % / 68 % | 2.91 / 3.04 min | 0.134 % / 0.177 % of incident-free intervals |
| McMaster (same report, QEW on-line) | real loop detectors | 68 % | 1.4 min | "20 false alarms over 64 days" (≈0.013 / h, our arithmetic, 24 h assumed) |
| Stephanedes et al. 1992 | real, 14 stations, 140 h | 50 % (operating point) | ~3 min structural | 3.5 / h (Calif. #7), 1.5 / h (theirs) per 5.5-mi segment |
| Zhang & Kianfar 2022 | sim (VISSIM), V2I probes, 10 incidents | 100 % (≥50 % penetration) | 0.9-1.9 min | % of intervals, not per hour |
| Pan et al. 2013 | real, 13,597 Beijing taxis | 86.7 % recall | 30-min slots | not reported, by design |
| Neill et al. 2005 | real ED baseline + injected outbreaks | 53/60 (low release) | 3.68 days | 1 per month (fixed) |

**Verdict 1: not found. No paper found infers an unmapped blocked cell or edge from multi-robot traces with a
detection rate, delay and false-alarm rate (queries at the end of Part 3). The nearest fields (road closures, AID)
detect much larger events, and the road work points to traffic absence and detours, not stall counts, as the signal.**

### 2. The map against persistence

The definitions differ, and that matters. Our persistence baseline ranks the *same window* by raw stall count, so
decay is the only difference (README table (j), `fleet/baselines.py` docstring). The brief's "the same top-K
cells as last window" is the literature's previous-period persistence, which we have not run. On the NIJ challenge
no naive benchmark was found: the auto-theft prize entry (Lee, O & Eck 2017) is itself a persistence ranking (12-month
rate, previous month as tie-break), Mohler & Porter 2017 report no naive baseline, and the 32-paper review (Kounadi
et al. 2020) lists autoregressive, logistic and KDE comparators, not last period. Our paired
map-minus-persistence truth precision, 1,000-resample zone bootstrap (`baselines_*.json`, `paired`): s8b K 20
−0.008 (−0.020 to +0.005, within noise), K 40 −0.023 (−0.034 to −0.011, worse); closed-loop-sticky K 20 +0.002
(−0.010 to +0.017), K 40 −0.018 (−0.029 to −0.008, worse); s8e K 20 −0.008 (−0.019 to −0.002) and K 40 −0.019 (worse,
3 zones only). s10-none has no truth positives and s10c-blind's precision is about 0.008, so only three of the five
runs carry information. In the literature, a tuned recent-window count is hard to beat. In Pittsburgh (Fitzpatrick,
Gorr & Neill 2020, arXiv SI) "The MAVG model shows the best prediction performance in the top-predicted areas, from
zero up to 3% of the city area": pAUC 1.31 against 1.23 for the best of nine models (CNN, MLP, GP, two self-exciting
point processes, KDE, LASSO), with no CI. Hu et al. 2018 find the decayed ProMap (Bowers 2004) no better than a static
KDE (no significant difference between the two), the same shape as our decay-vs-raw result. Their STKDE won on PAI at an area share chosen
on the test weeks, with no significant difference in hit rate. The tested wins over previous-period persistence are
small: Liu & Brown 2003 (72 and 140 test incidents, 90 % level, and "Best vs. Best" weekly indistinguishable), and
Gorr & Olligschlaeger 2002, which is precinct count error, not cell ranking. Traffic-accident deep models beat a
*long-run* historical average on MSE (Hetero-ConvLSTM urban 0.021 vs HA 0.050; HintNet a little better than HA in
rural cells), on one test year without a CI, and every off-the-shelf ML baseline in those papers lost to HA. In road
safety, empirical-Bayes shrinkage beats raw-count ranking on next-period site consistency (Cheng & Washington 2008,
abstract only), so the gain there comes from pooling over sites, not from decay. In CSEP earthquake tests, smoothed
past seismicity won the 5-year RELM test (Zechar et al. 2013, 31 events), and the hybrid that later beat it (GEAR1)
contains it. The only fleet forecast found with a persistence baseline is a simulation (Yu & Wolf, Amazon): the
learned model beats "delays from the past 10s" on RMSE, 0.92 vs 1.19 s at 0-10 s, but it gets planned paths as input.

| Field | Persistence definition used | Beats it with a CI or test? | Label |
|---|---|---|---|
| Crime | previous week or month (Liu & Brown, Gorr); tuned moving average (Pittsburgh); decayed ProMap (Hu) | small-sample tests only; the tuned moving average was not beaten | **rare** |
| Traffic accidents | long-run historical average per cell | beaten on MSE in every deep-model paper, never with a CI | **normal without a CI; with a CI unreported** |
| Road-safety hotspots | raw-count ranking, next period | beaten by empirical Bayes | reported (one abstract, numbers not read) |
| Earthquakes (CSEP) | smoothed long-run seismicity | usually ties or wins; GEAR1 wins at 2 years and contains it | **rare** |
| Warehouse / AGV / AMR | past 10 s per vertex (sim only) | RMSE without a CI; no real-log study found | **unreported** |

**Verdict 2: someone got the same. A tuned recent-window count beats richer models in Pittsburgh, and a decayed map
does not beat a static count in Hu et al. 2018. Beating persistence with a CI is rare in crime and earthquakes,
done without a CI in traffic, and unreported for robot fleets.**

### 3. Feeding the map back to routing

As a throughput share of 47.52 lines/h, our gain is map +2.0 % (95 % CI −1.5 to +5.6 %) and oracle +2.9 % (−0.8 to
+6.6 %), on the medium map (25 × 22 = 550 cells, 390 aisle cells, checked with `gym.make`) with 8 AGVs and 4 pickers,
which is 2.2 % agent density. The disturbance is a hidden slow floor; every paper below targets congestion between
agents. The same-planner ablations find almost nothing at low density. In Jiang et al. 2024 Table 3 (League of Robot
Runners winner, no seeds or spread reported), WPPL with no guidance vs manual guidance scores 3.20 vs 3.08 at Random
100 (12.2 % density), 5.69 vs 5.72 at Random 200, and 4.72 vs 4.70 at City 1000 (2.1 % density). It gains ×5.3 only
at Warehouse 8000. In Han & Yu 2022 Table I, a congestion tie-break changes throughput by −0.4 % at 40 robots and
+0.3 % at 160 (1.981 → 1.974, 6.873 → 6.896). The large gains (Zhang et al. 2024, +46 % at 400 agents on
warehouse-33-36; Chen et al. 2024, +22 % to +76 %; Zang et al. 2025, ×2.7 at 600 agents) are against plain PIBT at
hundreds to thousands of agents. At the lowest count Zhang et al. test (150 agents), RHCR on unweighted costs (4.95)
still beats guided PIBT (4.77). Chen et al.'s guided planner loses to RHCR at 200 agents (5.0 vs 5.7 / 6.0). The
closest mechanism, a learned per-vertex delay added to A* costs (Yu & Wolf, Amazon, 810-850 robots, simulation), gains
"an average of 4.4%" (1.0-7.7 % by scenario, std over 10 seeds 0.24-0.97 points). Its results text names the baseline as a
planner fed the past-10-s delays (the abstract says "versus without predictions"). Part 1 §5 read Zhang 2024 at A-
and Part 2 read Chen 2024 at A\*. Both are now read at A (PDF tables), and nothing in those parts changes.

| Source | Map, agents (density) | Baseline | Gain | Spread reported |
|---|---|---|---|---|
| This repo, Sprint 8 (README) | TA-RWARE medium 25×22, 8 AGV + 4 pickers (2.2 %) | no map | +2.0 % map, +2.9 % oracle | 95 % CI, 30 paired seeds |
| Jiang et al. 2024 | random-32-32, 100 / 200 (12 / 24 %); City 256², 1,000 (2.1 %) | WPPL, no guidance | −3.8 % / +0.5 %; −0.4 % | none |
| Han & Yu 2022 | 37×20 warehouse, 40-160 | bounded-horizon search | −0.6 % to +0.3 % | none |
| Zhang et al. 2024 | warehouse-33-36, 400 (42 %); 150 (16 %) | unweighted PIBT | +46 %; at 150, RHCR plain 4.95 > guided 4.77 | SE, 50 runs |
| Chen et al. 2024 | Sortation 33×57, 600; 200 (13 %) | PIBT; RHCR | +76 %; at 200, guided 5.0 < RHCR 5.7 / 6.0 | ± (meaning not stated), 24 instances |
| Zang et al. 2025 | warehouse 33×57, 600 (55 %) | no guidance | ×2.7 (3.18 → 8.66) | std, 10 runs |
| Arita & Okumura 2026 (preprint) | random-64-64-10, empty-48-48, 1,000 | LaCAM, no guidance | +23 %, +28 % | min / max, 10 instances |
| Yu & Wolf (Amazon, venue not confirmed) | sortation 179×69, 810-850 (6.6-6.9 %) | planner with past-10 s delays | +4.4 % (1.0-7.7 %) | std, 10 seeds |

**Verdict 3: someone got the same. Congestion-aware costs add about nothing below a few hundred agents in the
same-planner ablations found. A +2-3 % gain at 12 agents is consistent with them. Our CI upper ends (+5.6 % and
+6.6 %) still contain Yu & Wolf's +4.4 %, so the result is underpowered rather than negative. No paper tests hidden
slow cells.** *(Corrected 2026-10-21, Part 5: Kita et al. 2023 hide per-edge delays from the planner and learn them
in execution; they score conflicts and travel time, not throughput.)*

### What this means for us (Part 3)

1. **Hidden blockage: retest with a different signal.** Stall counts are the wrong evidence for a cell robots now
   avoid. Add a per-cell *traffic-absence* test: time since the last pass against the expected inter-arrival time,
   the HERE / TomTom form. Add a detour count too (Pan et al. 2013). Then count stall events on the 44-48 missed
   windows to test the Neill-type signal floor. Keep the in-sample 17/50 out of any text until a held-out run exists.
   *Done 2026-10-21 (S14B): the absence test detects 0 of 50 windows at every alpha swept (README (t)); recorded as
   drop in `docs/SCOPE.md` Sprint 14. Detours and the stall-count floor were not done.*
2. **Map vs persistence: keep the negative, reword it.** It matches Pittsburgh and Hu et al. 2018. Drop "decay"
   as a claimed improvement. If it is ever retested, use the literature's baselines: previous-window top-K, a window
   tuned on calibration seeds (MAVG), and empirical-Bayes shrinkage to the zone mean as the challenger.
3. **Routing feedback: retest only with more power.** At 30 seeds the CI spans −1.5 to +5.6 %, which cannot separate
   0 from the one comparable published gain (4.4 %). The half-width is now ±1.7 lines/h (±3.5 %); halving it needs about
   4× the seeds (120), ±1 % about 12× (360), or a denser fleet where congestion gains are known to appear. Until then, write it up as within noise and consistent
   with near-zero gains at low agent counts, not as a shown absence of effect.

### Papers and sources (Part 3)

All rows verified@2026-10-21. Read depth as in Part 2 (A\* = through a summarising fetch). § = question.

| § | Authors / org, year | Title (short) | Venue | URL | Read | Used for |
|---|---|---|---|---|---|---|
| 1 | Pietrobon, Lewis, Heverly-Coulson 2019 | Road closure detection from vehicle probe data | ACM TSAS 5 | https://doi.org/10.1145/3325912 | A- (abstract only) | Poisson probe test, precision |
| 1 | Zhang, An, Liu, Wen, Hu, Shao 2023 | T-Closure: GPS trajectories for road closure detection | KDD 2023 | https://doi.org/10.1145/3580305.3599926 | A- (abstract only) | volume, 1.5 h delay |
| 1 | HERE Global, US 11270578 B2 | Detecting road closures based on probe activity | patent | https://patents.google.com/patent/US11270578 | A\* (first 100k chars) | Poisson absence test, no eval |
| 1 | Texas Transportation Institute (Chang et al.) | San Antonio incident detection algorithm study, 2917-1F | report (year not checked) | http://tti.tamu.edu/documents/2917-1F.pdf | A | California #7/#8, McMaster |
| 1 | Stephanedes, Chassiakos, Michalopoulos 1992 | Comparative evaluation of incident detection algorithms | TRR 1360 | https://onlinepubs.trb.org/Onlinepubs/trr/1992/1360/1360-009.pdf | A | FA per hour |
| 1 | Zhang, Kianfar 2022 | AID for V2I, I-64 Missouri | Sensors 22(23) | https://pmc.ncbi.nlm.nih.gov/articles/PMC9735737/ | A\* | probe AID in sim |
| 1 | Pan, Zheng, Wilkie, Shahabi 2013 | Crowd sensing of traffic anomalies | SIGSPATIAL 2013 | https://doi.org/10.1145/2525314.2525343 | A (MSR PDF) | route-change signal |
| 1 | Neill, Moore, Sabhnani, Daniel 2005 | Detection of emerging space-time clusters (Part 1 row) | KDD 2005 | https://cs.nyu.edu/~neill/papers/sss-kdd05.pdf | A | signal floor at 1 FP / month |
| 1 | Sahak, Jiao, Rhinehart, Barfoot 2026 | OSCAR: obstacle survival curves | arXiv preprint | https://arxiv.org/abs/2606.00990 | A- | onboard sensing, not traces |
| 1 | Ogorelysheva, Howar, Chen 2026 | Localized anomaly isolation via dead zones in AGV fleets | arXiv preprint | https://arxiv.org/abs/2610.08524 | A- | location given, not detected |
| 2 | Fitzpatrick, Gorr, Neill 2020 | Policing chronic and temporary hot spots (SI) | arXiv preprint | https://arxiv.org/abs/2011.06019 | A | MAVG best of 10 |
| 2 | Hu, Wang, Guin, Zhu 2018 | STKDE for crime hotspots (Part 1 row) | Applied Geography 99 | https://arxiv.org/abs/2006.00272 | A | ProMap = static KDE |
| 2 | Liu, Brown 2003 | Point-pattern density model (NIJ report version) | Int. J. Forecasting 19(4) | https://www.ojp.gov/pdffiles1/nij/grants/197634.pdf | A- (OCR tables) | beats last week, 90 % |
| 2 | Gorr, Olligschlaeger 2002 | Crime hot spot forecasting (NIJ 195168) | NIJ report | https://www.ojp.gov/pdffiles1/nij/grants/195168.pdf | A | random walk, lag-12 naive |
| 2 | Lee, O, Eck 2017 | Theory-driven hot spot forecasting (NIJ 251179) | NIJ report | https://www.ojp.gov/pdffiles1/nij/grants/251179.pdf | A | persistence method won a category |
| 2 | Mohler, Porter 2017 | Rotational grid, PAI-maximizing forecasts (NIJ 251203) | NIJ report | https://www.ojp.gov/pdffiles1/nij/grants/251203.pdf | A | no naive baseline |
| 2 | Yuan, Zhou, Yang 2018 | Hetero-ConvLSTM traffic accident prediction | KDD 2018 | https://doi.org/10.1145/3219819.3219922 | A (author PDF) | HA baseline MSE |
| 2 | An, Vahedian, Zhou, Street, Li 2022 | HintNet | SIAM SDM 2022 | https://arxiv.org/abs/2203.03100 | A | HA baseline MSE |
| 2 | Cheng, Washington 2008 | New criteria for evaluating hot spot methods | TRR 2083 | https://doi.org/10.3141/2083-09 | A- (abstract only) | EB beats raw-count ranking |
| 2 | Zechar et al. 2013 | RELM I: first-order results | BSSA 103(2A) | https://doi.org/10.1785/0120120186 | A- | smoothed seismicity wins |
| 2 | Strader, Schorlemmer, Cotton 2018 | Testing strain rate in global seismicity models | EGU2018-9733 abstract | https://meetingorganizer.copernicus.org/EGU2018/EGU2018-9733.pdf | A- | GEAR1 contains KJSS |
| 2 | Kounadi, Ristea, Araujo, Leitner 2020 | Systematic review on spatial crime forecasting | Crime Science 9 | https://doi.org/10.1186/s40163-020-00116-7 | A\* | baselines used in 32 papers |
| 2 | Rosser, Davies, Bowers, Johnson, Cheng 2017 | Predictive crime mapping: grids or street networks | J. Quant. Criminology 33 | https://doi.org/10.1007/s10940-016-9321-x | A\* | Wilcoxon on 90 paired days (context only) |
| 2,3 | Yu, Wolf (Amazon) 2023 | Congestion prediction for large fleets of mobile robots | amazon.science (venue not confirmed) | https://cdn.amazon.science/8c/e5/80b4bc184aebb861fa764f8173cc/congestion-prediction-for-large-fleets-of-mobile-robots.pdf | A | past-10 s persistence, +4.4 % |
| 3 | Jiang, Zhang, Veerapaneni, Li 2024 | Scaling lifelong MAPF (Part 2 row) | SoCS 2024 | https://arxiv.org/abs/2404.16162 | A (PDF Table 3) | guidance ablation by density |
| 3 | Han, Yu 2022 | Optimizing space utilization for MRPP (SU-I) | ICRA 2022 | https://arxiv.org/abs/2109.04677 | A (PDF Table I) | ±0.6 % at 40-160 robots |
| 3 | Zhang, Jiang, Bhatt, Nikolaidis, Li 2024 | Guidance graph optimization (Part 1 row) | IJCAI 2024 | https://arxiv.org/abs/2402.01446 | A (PDF Tables 2-3) | +46 %; RHCR plain at N 150 |
| 3 | Chen, Harabor, Li, Stuckey 2024 | Traffic flow optimisation (Part 2 row) | AAAI 2024 | https://arxiv.org/abs/2308.11234 | A (PDF Tables 1-2) | +22-76 %; loses at N 200 |
| 3 | Zang et al. 2025 | Online guidance graph optimization (Part 1 row) | AAAI 2025 | https://arxiv.org/abs/2411.16506 | A (plots; Fig. 1 only numeric) | ×2.7 at 55 % density |
| 3 | Arita, Okumura 2026 | Lifelong LaCAM with local guidance (Part 2 row) | arXiv preprint (SoCS 2026 per comment) | https://arxiv.org/abs/2605.16855 | A | +23-28 % at 1,000 |
| 3 | Cohen, Uras, Koenig 2015 | Highways for bounded-suboptimal MAPF | SoCS 2015 | https://idm-lab.org/bib/abstracts/papers/socs15b.pdf | A | one-shot, solve-rate effect; not used for a number |

Not verified and kept out of the text: Liu & Brown's table values (OCR garbled), the Montella 2010 and Bartlett 2014
congestion-routing numbers (snippet only, Bartlett 403), Cohen et al. IJCAI 2016 (wrong PDF fetched), the 2023 Seismic
Record regional CSEP result (403), the low-agent curves of Zhang, Chen, Zang and Arita (plots only), and Zhang & Kianfar's
Table 3 FAR values, whose relayed numbers contradict the text. The Mohler-Porter "a remark on" note and NIJ challenge
naive-baseline scores were not found or not searched.

**Absence queries (Part 3).** Q1, blocked-edge inference from multi-robot traces with DR / delay / FA: WebSearch
"multi-robot fleet infer blocked edge unknown obstacle from robot delays lifelong MAPF roadmap update observed
traversal times", "warehouse AGV AMR fleet logs detect blocked aisle obstruction from robot position data anomaly
detection evaluation"; arXiv API `all:AGV AND all:anomaly AND all:trajectory`, `all:warehouse AND all:robots AND
all:anomaly AND all:detection`, `all:"blocked edges" AND all:robots`, `all:fleet AND all:obstacle AND all:inference
AND all:traces` (0); OpenAlex "anomaly detection AGV trajectories warehouse", "lifelong multi-agent path finding
unknown obstacles detection", "detecting decreases counts spatial surveillance absence". Q2, a fleet forecast against
persistence on real logs: WebSearch "warehouse AGV congestion prediction hotspot forecast baseline historical average
robot traffic", "AMR fleet real log deadlock congestion hotspot prediction "persistence baseline" OR "naive baseline"
multi-robot warehouse"; arXiv API `all:warehouse AND all:robot AND all:congestion AND all:prediction`; and an NIJ
naive benchmark, WebSearch "NIJ crime forecasting challenge results analysis "naive" OR "baseline" PAI PEI entries
compared simple hot spot prior period". Q3, hidden slow cells as the routing disturbance: none of the twelve Q3
papers read uses it, and WebSearch "congestion-aware AGV routing dynamic edge weights small fleet throughput
improvement warehouse simulation 10 AGVs" found no small-fleet number. Rerun on Semantic Scholar before any of these
fronts a pitch.

## Part 4: service-time bounds, stall causes, traffic absence (2026-10-21)

Scope: the check before S14A and S14B (laptop-scheduler `jobs/wr-lane-s14a-servicing-bound.md`,
`jobs/wr-lane-s14b-traffic-absence.md`). Three research passes on 2026-10-21 (WebSearch, WebFetch, curl); the main
session re-fetched the quoted pages and grepped the patent texts for every number used. Query log:
`reports/wr-dev-lit-s14.md`. Ranks as in Part 2, patents their own class; all verified@2026-10-21.
**Coverage:** SEMI E10/E58/E116, ISO 22400-2, ISO 3691-4, ISO 14224 and VDI 4486 are paywalled (records and secondary
mappings read). A station/dock timeout was searched for MiR, OTTO, Kollmorgen NDC, BlueBotics ANT, openTCS and Open-RMF,
not Geek+ or Locus; none found, but on search results, not doc trees, so that vendor absence is rank F.

### 1. Upper bound on a station stop
| rule (source, read) | standard name | default | state the overrun moves to |
|---|---|---|---|
| VDA 5050 main (3.0), https://raw.githubusercontent.com/VDA5050/VDA5050/main/VDA5050_EN.md (A) | none: actions "can run as long as they need to run and should be self-terminating"; "The handling of timeouts and retries shall be defined during integration" | none stated | fleet control's call (cancel the order; action FAILED / an error) |
| OEE six big losses, https://www.oee.com/oee-six-big-losses/ (A, vendor docs) | small stop vs breakdown threshold | small stops "typically a minute or two", "well under five minutes"; threshold "based on your policy for tracking reasons", e.g. "any downtime longer than two minutes should have a reason" | below: small stop (performance loss); above: breakdown (availability loss, needs a reason) |
| MoRoOp dispatcher, https://huggingface.co/datasets/Self-Organizing-Production-Logistics/MoRoOp (Part 2b, A-) | operation TIMEOUT | `timeout_seconds: 300` in a failure's meta_data | operation FAILURE, termination_reason TIMEOUT |
| NIST/SEMATECH e-Handbook 7.1.6, https://www.itl.nist.gov/div898/handbook/prc/section1/prc16.htm (A) | outer fence | Q3 + 3·IQ: "beyond an outer fence is considered an extreme outlier" (inner fence 1.5·IQ, mild) | n/a (statistics) |
| JMP probability limits, https://www.jmp.com/en/statistics-knowledge-portal/quality-and-reliability-methods/control-charts/probability-limits-on-control-charts (A) | probability limits | fit a distribution, "Find the quantiles of the model for 0.005, 0.5, 0.995"; for skewed data the 3σ lower limit "does not seem appropriate" | n/a |
| SEMI E10 via OPC 40001-1 C.3, https://reference.opcfoundation.org/specs/OPC-40001-1/c-3 (A) | six states | none | no rule found that a process-time overrun is unscheduled downtime |
| SEMI E116 EPT, https://store-us.semi.org/products/e11600-semi-e116-specification-for-equipment-performance-tracking (A-) | IDLE / BUSY / BLOCKED, "reasons for being blocked" | codes paywalled | BLOCKED (mapped to E10 unscheduled down by one MES vendor, S only) |

Not found (queries below): a k × median dwell rule with a published k, a planned cycle time for a robot's station stop
in VDA 5050 or ISO 22400 (catalogue only), a vendor dock or station timeout default. **A non-robust limit fails here:**
with the outlier in the sample it masks itself (stops 20, 30, 40, 50, 600 s: log-scale mean + 3σ is 2,150 to 3,300 s).

**Verdict 1.** S14A bound: **T = min(300 s, exp(Q3 + 3·IQR of ln dwell))** = min(300, Q3·(Q3/Q1)^3), the NIST outer
fence on the log scale, capped at the OEE five-minute small-stop edge and the MoRoOp dispatcher's own 300 s timeout.
Sample: every stopped run with an order that starts within `station_radius` of a station, **of any length** (SERVICING
only exists past 30 s, so a sample of SERVICING runs is left-truncated and pushes Q1 up; if S14A uses it, the report
says so). Pooled per run; fewer than 5 stops in the sample → T = 300 s (the minimum is set here, no source). On the S14A
fixture (20, 30, 40, 50, 600 s, linear-interpolated quartiles) T = 50·(50/30)^3 ≈ 231.5 s, only the 600 s stop converts.
State STUCK; cause key `station_overrun`; above the OEE small-stop threshold, so an availability loss that needs a
reason.

### 2. Cause taxonomy for a stuck log a client reads
**VDA 5050 error record** (A, both branches read). 3.0 (`main`): `errors[]` with `errorType`, `errorReferences[]`
{`referenceKey`, `referenceValue`}, `errorDescription`, `errorHint`, translations, `errorLevel` {WARNING, URGENT,
CRITICAL, FATAL}; predefined types include FATAL `LOCALIZATION_ERROR`, CRITICAL `OUTSIDE_OF_CORRIDOR`,
`BLOCKED_ZONE_VIOLATION`, `NODE_UNREACHABLE`, WARNING `NO_ROUTE_TO_TARGET`; `safetyState` {`activeEmergencyStop`
MANUAL/REMOTE/NONE, `fieldViolation` "Protective field violation (e.g., by laser or bumper)"}. 2.1.0
(https://raw.githubusercontent.com/VDA5050/VDA5050/release/2.1.0/VDA5050_EN.md): `errorLevel` "Enum {'WARNING',
'FATAL'}", `eStop` {AUTOACK "e.g., by bumper or protective field", MANUAL, REMOTE, NONE}. **Correction to Part 2 §2**,
which read URGENT and CRITICAL into 2.1.0: they exist only from 3.0, so `faulted` = CRITICAL/FATAL means FATAL only on a
2.x stream. Neither version has a "blocked by obstacle" field. **PackML**, OPC 30050 §6.3.8,
https://reference.opcfoundation.org/specs/OPC-30050/6.3.8 (A): Suspending when "conditions external to the unit/machine
require a pause" ("the unit/machine is 'blocked'" downstream, "'starved'" upstream); Held for "internal process
conditions". **SEMI E10/E79** substates
(https://www.cimetrix.com/hubfs/Blog_Files/Cimetrix-Productivity-infrastructure-Smart-Manufacturing.pdf, E79 figure
reproduced, B): unscheduled downtime "Maintenance delay, Repair time, Change of consumables, Out of spec input,
Facilities related"; standby "No operator, No product, No support tool". **PIADE**, https://zenodo.org/records/7071746
(A): rows carry `interval_start`, `equipment_ID`, `alarm` ("alarm code of the active stop reason"), `type` in {idle,
production, downtime, performance_loss, scheduled_downtime}, `start`, `end`, `elapsed`; the 133 alarm codes are not
grouped into classes, `type` is the only class. ISO 3691-4 stop categories: not obtained.

| cause key | `cause_label` (verbatim) | standard anchor | computable from a VDA 5050 state stream |
|---|---|---|---|
| `faulted_self` | Robot fault | E10 unscheduled downtime; PackML Held; VDA `errorLevel` CRITICAL/FATAL | yes on 3.0; FATAL only on 2.x; export `errorType` and `errorHint` with it |
| `blocked_by_faulted` | Blocked by a faulted robot | PackML Suspended (blocked) | partly: neighbour's `errors` + positions; "adjacent" is the detector's geometry |
| `blocked_by_stuck` | Blocked by a stuck robot | PackML Suspended (blocked); blocking chain (Part 2 §1) | partly: inferred from the neighbour's state |
| `traffic` | Traffic wait | PackML Suspended (blocked); ISO 22400 delay time ADET; Standridge congestion | partly: cannot be told from a planned wait without the plan |
| `unknown` | Stopped, cause not identified | none (residual) | yes, as the residual |
| `station_overrun` | Station stop over time limit | OEE breakdown side of the small-stop threshold (§1) | partly: needs a station map, which VDA 5050 does not carry |

*(Corrected 2026-10-21, Part 5 §2: PackML "blocked" and SEMI E116 blocked reasons are the unit's own report, so they
anchor no neighbour row; from a state stream those three rows are co-location facts, relabelled "Stopped next to ...".)*

**Not computable from the fields read today** (field needed): e-stop vs protective-field stop (`safetyState`), manual or
intervened mode (`operatingMode`), operator pause (`paused`, emitted but not a cause), charging
(`powerSupply.charging`), connection loss (`connectionState`), localisation lost and no route (`errorType`). **Not
computable from any VDA 5050 stream:** E10 standby no operator / no product at the station (needs WMS or station data)
and maintenance delay, consumables, facilities (needs a maintenance log).

**Verdict 2.** S14A exports the six `cause_label` strings of the table exactly; `cause` stays the machine key. Rows
carry stop interval and robot id (PIADE shape). *(Superseded 2026-10-21 by Part 5 §2 for four labels: "Robot fault" →
"Robot error, cannot continue order" (VDA CRITICAL covers order and zone errors), the three neighbour labels → "Stopped
next to ...".)*

### 3. Traffic-absence detection
**HERE US 11270578 B2**, https://patents.google.com/patent/US11270578B2/en (patent): a "historical model of expected
probe activity" per segment and "per time epoch", from "a designated time span (e.g., one year or longer)"; Poisson
(Gaussian for ">1000 data points"); worked example λ = 8.83 from 12 observations, "the likelihood of 0 vehicles is
0.015%"; closed when the probability is below a threshold "determined based on ground truth data comprising labeled
closure status data"; release "with the role of the historical baseline model and the closure model flipped". Its
threshold examples contradict each other; no evaluation. **HERE US 10847029 B2**,
https://patents.google.com/patent/US10847029B2/en (patent): the monitoring window must hold "total expected (historic)
vehicle volume ... greater than EXPECTED_THRESH, which is 10 in this example"; links that cannot reach it within
MAX_WINDOW_SIZE are never monitored. **TomTom US 10767999 B2**, https://patents.google.com/patent/US10767999B2/en
(patent): passability decays as e^(−βt) with β inversely proportional to the "expected visit interval" (monthly
average), a fixed jump on each traversal; release with hysteresis; "a closure of less than 15 minutes" may not be
detected. Google, INRIX: nothing documented found (rank F). **Pan et al. 2013**
(https://doi.org/10.1145/2525314.2525343, A, MSR PDF): no planned route needed. A routing pattern is the historical
share of traffic on each path between an origin and a destination region; anomalous when its Mahalanobis distance from
the median pattern is ≥ 3σ; runs every 30 min; recall 86.7 % vs 46.7 %. It needs positions only, but scores 30-min slots
against historical patterns, and one 2,495 s run gives one slot and no history; the planned route is not in the stream
either (`nodeStates` holds the first route node only, `fleet/fleet_analyser/emitter.py:17-19`). **SPC
time-between-events chart** (t / TBE chart, Chan, Xie & Goh 2000) via Hinestroza & González 2019,
https://doi.org/10.15446/rev.fac.cienc.v8n2.69524 (A): T ~ exp(λ0), UCL = −(1/λ0)·ln(α/2), standard α = 0.0027, ARL0 ≈
370. **Neill expectation-based Poisson** (Part 1; decrease form, arXiv https://arxiv.org/abs/2012.07574, A): at an
observed count of 0 the log-likelihood ratio equals the expected count B (algebra done here): the same test. **AMOC**
(arXiv https://arxiv.org/abs/2101.12246, A): ROC with the detection rate replaced by delay, a missed event's delay = its
length; origin Fawcett & Provost, KDD 1999 (not read). No absence-test source reports false alarms per hour; the only
per-hour false-alarm figures remain the loop-detector ones of Part 3 (0.013 to 3.5 per hour, on lane-scale incidents).
Absence-based blocked-cell detection in robot fleets: not found (queries below and Part 3 Q1).

**Verdict 3.** S14B test: the **time-between-events upper probability limit on the open gap** (the HERE zero-count
rule). Per (zone, cell): rate r = passes / unflagged observed seconds, from the stream's own past (causal, expanding
from the first message, frozen while the cell is flagged); eligible when r·(seconds observed) ≥ 10 expected passes (a
deviation: HERE's 10 is the expected count inside the tested window, i.e. r·gap ≥ 10); flag at bin end when e^(−r·gap) <
α, i.e. gap > ln(1/α)/r, so a cell is flagged ⌈ln(1/α)/(r·bin_s)⌉ bins after its last pass; release at the next pass. α
default 1e-3, sweep {1e-2, 1e-3, 1e-4} (set here; the SPC 0.0027 is per chart; under a Poisson null, flag events per
zone-hour ≈ α × eligible passes per hour, and the harness counts flag-publishes, a multiple of that since a flag stays
up about 1/r). Deviations from HERE (state them): one 2,495 s run, not a year of epochs; no time-of-day model or
labelled threshold.

### 4. What this means for S14
**Scale (sizing on undisturbed `s10-none` zones 0/3/7, counted this session, not a result):** a zone's busiest cell sees
14 to 19 robot passes in 2,495 s (≤ 0.008 passes/s), the tenth-busiest 12 to 15. Blockages last 300 to 1,200 s (60-240
steps × 5 s, `src/warehouse_rl/disturb.py:20`). On the busiest cells the flag needs a gap of about 600 / 900 / 1,200 s
at α 1e-2 / 1e-3 / 1e-4, and eligibility (10 expected passes) is reached only 1,300 to 1,800 s into the run. So only
long, late blockages on the busiest cells can be flagged while open (the Neill floor of Part 3). Under HERE's own window
rule (r·gap ≥ 10, about 1,300 s or more) no cell is testable while a blockage is open.

- **S14A rule:** min(300 s, log-scale outer fence) on all station stops with an order; parameter: the 300 s cap, the
  3·IQR fence, the minimum of 5 stops. **Positive:** on MoRoOp the 1,107 s stop is a `station_overrun` episode again,
  TIMEOUT overlaps rise above 1 of 8, and unlabelled station-cell stuck runs stay ≤ 54 (10 % of README (q)'s 542, bar
  set here). **Negative:** more than 54 of them come back, or the 1,107 s stop stays hidden. Simulator: the stall list
  grows by fewer episodes than the 4-47 per run that (r) removed (or the report says why). Causes: the six labels of §2,
  verbatim; positive: every closed episode carries one. Negative: a higher `unknown` share than before is a regression.
- **S14B rule:** zero-count absence test above at α 1e-3, eligibility 10 expected passes, release at the next pass.
  **Positive:** on the same 50 `s10c-blind` windows, at least 5 detected while open that the reference misses and none
  the other way (one-sided exact sign test, p < 0.05), against the CUSUM of README (n) at ≤ 1 false alarm per zone-hour
  on `s10-none`, or against the map of (k) at < 177.8. **Negative:** no α of the sweep reaches that bar. The sizing
  makes it likely; it would close the hidden-blockage warning at this density. The in-sample tuned CUSUM is not a
  comparison.

- **S14A measured (README (s), `results/fleet/*-sb.json`, 2026-10-21): positive on every bar.** The 1,107 s stop is a
  `station_overrun` episode again (3,245 s; shift-6 stuck bucket 7 s to 1,107 s), TIMEOUT overlaps are 5 of 8 (above
  1), unlabelled station-cell stuck runs are 3 (bar <= 54), and the simulator stall lists grow by 0, 1, 0, 0 and 25
  episodes (fewer than the 4-47 that (r) removed). T = 300 s on MoRoOp (the cap, the dispatcher's own timeout) and
  80 s on the simulator. No source gave a delay or false-alarm figure for this rule, so there was none to reach.
  Every closed episode carries one of the six labels; there is no earlier `unknown` share to compare with.
- **S14B measured (README (t), `results/fleet/amoc_absence*.json`, 2026-10-21): negative.** Alpha 1e-3 and 1e-4
  flag nothing (0 forecast rows), and alpha 1e-2 detects 0 of 50 windows at 18.1 false alarms per zone-hour on
  `s10-none` (K 20). The bar against the CUSUM (2/50 at 0) and the map (6/50 at 177.8) is not reached. The sources'
  numbers were not reached either. HERE and TomTom publish no delay or false-alarm figure (precision only, and a
  closure under 15 minutes may go undetected), the SPC chart's ARL0 of about 370 assumes a rate this run cannot
  estimate, and the loop-detector rates of Part 3 (0.013 to 3.5 per hour, about 3 min delay) belong to lane-scale
  incidents. The sizing above predicted the outcome.

**Absence queries (Part 4)** (WebSearch; full log in the report): "VDA 5050 action timeout blockingType actionParameters
specification", "MiR robot mission "wait for" action timeout docking", "Open-RMF dispenser ingestor timeout task phase
"dispense" request timeout", "openTCS vehicle operation timeout load cargo "timeout" peripheral job", "OTTO Fleet
Manager job timeout autonomous mobile robot "timeout" pick drop", "Kollmorgen NDC OR BlueBotics ANT server AGV load
station timeout error", "ISO 22400-2 KPI "planned run time per item" "actual unit processing time" definition", "VDA
5050 3.0 obstacle detection state message "blocked" mobile robot", "ISO 3691-4 protective stop emergency stop stop
category 0 1 personnel detection driverless trucks", ""E116" "BlockedReason" OR "blocked reason" EPT equipment
performance tracking SEMI", "detect blocked edge warehouse robot fleet absence of traffic MAPF", ""negative information"
OR "absence of observations" multi-robot blocked aisle", "Google patent detecting road closures absence of location
data"; arXiv API ti:"road closure detection" (0 results).

## Part 5: the stuck threshold, the cause rule, and a sweep of Parts 1 to 4 (2026-10-22)

Scope: the 30 s stop-to-stall threshold (`DEFAULT_STUCK_AFTER = 30`, `fleet/fleet_analyser/detector.py:46`), the
neighbour cause rule (`_cause`, `detector.py:258-271`, Manhattan ≤ 1 via `_near`, `:81-82`) and a scholarly rerun of
the absence claims of Parts 1 to 4. Scheduled for 2026-10-22, fetched 2026-10-21, so `verified@2026-10-21`. Three
research passes (WebSearch, WebFetch, curl to raw GitHub, arXiv, OpenAlex, Semantic Scholar); the main session
re-fetched every quote used; §3's DeepFleet, hospital and Petri-net rows rest on a subagent read. Query log:
`reports/wr-dev-lit-part5.md`. Ranks as in Part 2 (A read, A- abstract or record, S snippet).
**Coverage:** Semantic Scholar answered 9 of 64 queries (170 of 179 tries 429 with backoff; bulk 429; web UI 403);
OpenAlex all 83. Still not a Semantic Scholar sweep. Google Scholar not tried. ISO, SEMI, VDI paywalled.

### Overturned and weakened first (§3 detail below)

- **Overturned, Part 1 §5 (per-cell unknown delays).** Kita, Suenari, Okada & Taniguchi 2023, "Online Re-Planning and
  Adaptive Parameter Update for MAPF with Stochastic Travel Times" (https://arxiv.org/abs/2302.01489, A, preprint;
  OpenAlex lists it as AAMAS): each edge's delay is "x ∼ Gamma(a(e), b(e))", the parameters "are unknown", and the
  planner estimates them "from m observations of delay". That is what §5 said set our floor setting apart. Left:
  edge not cell, continuous delay not a failure probability, a given prior, 30-50-node graphs.
- **Weakened:** Part 3 Q3 "No paper tests hidden slow cells" (Kita: per edge; conflicts and travel time, not
  throughput). Part 1 Q4, no name for "time to clear": alarm management's "'Return To Normal' (RTN)" and off-delay
  timer (Kondaveeti et al., MED, OpenAlex 2011, https://doi.org/10.1109/med.2011.5983183, A-), a clearing event, not a
  map metric. Part 1 Q1, HMMs on
  telemetry: Azzalini et al. 2020, AAMAS, https://doi.org/10.5555/3398761.3398779 (A-), "data collected during their
  routine operations", single robots, so the absence holds for fleets only. Part 2 §1, no name for an acyclic chain:
  Andersson & Veldhuis 2025, Chalmers MSc thesis with Kollmorgen
  (https://odr.chalmers.se/bitstreams/7d9faa35-7c28-4653-b856-5cc62f4e6653/download, A, not peer reviewed), "blocking
  graphs" of "causal chains", where "a blocking is an instance of a traffic rule being activated" (controller state).

### 1. The stop-to-stall threshold

| source (rank) | what it defines | time | what happens at the time |
|---|---|---|---|
| VDA 5050 3.0.0 (https://raw.githubusercontent.com/VDA5050/VDA5050/main/VDA5050_EN.md) and 2.1.0 (release/2.1.0) (A) | state "at least every 30 seconds" (3.0.0 L1034; 2.1.0 L936 "at the latest every 30s"); `driving`, `paused`, WAITING, `newBaseRequest`, NODE_UNREACHABLE: no duration; 2.1.0 `waitForTrigger`: "Master control is responsible to handle the timeout" | 30 s = message interval only | fleet control owns "Detection and resolution of blockages ("deadlocks")" (L282) |
| OTTO tech docs, https://docs.ottomotors.com/en/127044-119570-recover-your-amr--blocked.html (A) | Blocked: "The AMR is blocked from proceeding on its planned path"; physical ("An obstacle blocking the AMR path") or logical ("An incorrect container state") | none stated | "stops all AMR movement until the blockage is cleared" |
| MiR Fleet reference guide 1.2 (2020), https://www.hmi-mbs.fr/wp-content/uploads/2020/07/notice-mir_fleet_reference_guide_12_en.pdf (A, distributor mirror) | zone "Path timeout": "the amount of time the robot will wait for the path to clear before generating a new one"; "if the path is blocked. Default is 5 seconds." | 5 s | replan; "Retries (Blocked Path)" exhausted → mission error |
| ROS 2 Nav2 `simple_progress_checker.cpp` L54-56 (A) | `movement_time_allowance` to move `required_movement_radius` | 10.0 s / 0.5 m | progress failure → recovery |
| ROS move_base `MoveBase.cfg` (A) | `planner_patience`, `controller_patience` | 5.0 s each | "space-clearing operations" |
| Open-RMF rmf_ros2 `EasyFullControl.hpp` L595, `RobotUpdateHandle.hpp` L133 (A, source) | `max_delay`: "how high the delay of the current itinerary can become before it gets interrupted and replanned" | 10 s | replan |
| Lee et al. 2026; Gerling et al. 2016 (Part 2b §3, A); OEE six big losses (Part 4 §1, A vendor docs) | failure: "stationary for > 1 min"; stuck: "in the order of minutes"; small stop: "a minute or two" | 60 s to minutes | failure label; breakdown needs a reason |
| MAPF: Ma et al. 2017 (arXiv 1612.05309), Atzmon et al. 2018 (SoCS), Hönig et al. 2019 (RA-L) (A) | a delay = a timestep the agent "remains delayed in its current vertex" / "did not perform the move action" | counted in steps, not seconds | k-robust plans tolerate "up to k" |
| VDI 2510 Bl. 1-4, VDI 4451 Bl. 3/4/6/7 (S, titles only); ISO 3691-4:2023 (S, iso.org 403); SEMI E10/E58, ISO 22400-2 AUDT (S, secondary) | AGV infrastructure, safety, interfaces, compatibility; unscheduled downtime / unplanned stops | none found | n/a |

Not found: a stop-to-stall rule at 30 s or any fixed time in a standard, spec, manual or paper; ISO 3691-4 stop
durations; a minimum downtime in SEMI E10 / ISO 22400 (secondary only). Decisive WebSearch queries (abridged …, full in the log): "AMR AGV
"stationary for more than" OR "not moved for" seconds stuck detection warehouse robot", "AGV deadlock detection
"waiting time exceeds" threshold seconds …", "SEMI E10 "SEMI E58" … short stop downtime … "minimum duration"", "MiR fleet
"blocked" robot notification seconds path blocked timeout". Seegrid, Locus, Geek+, OTTO help centre: UNTESTED.

**Verdict 1. 30 s is backed by nothing found; it is our parameter.** The sources split into two bands: replan or
recovery triggers at 5-10 s inside the robot or fleet manager (MiR, move_base, Nav2, Open-RMF; OTTO states none), and failure or
breakdown labels at a minute or more (Lee, Gerling, OEE). 30 s sits between them, above the simulator's (TA-RWARE)
5-step replan (25 s at `STEP_S = 5`, `docs/SCOPE.md:207`), which is the one reason it has. The 30 s coincidence with
VDA 5050 is a hazard, not support: a stopped robot that sends only the mandatory state may report once per 30 s, so
on an event-driven stream the threshold can be decided by a single heartbeat and confirmed up to 30 s late. Name it
the **stuck threshold** (`stuck_after_s`), say "set by us, no standard" wherever it is shown, and make it a **site
setting with a documented default of 30 s**, chosen to sit above the site's fleet-manager replan timeout and below
its failure or small-stop threshold; report the stream's maximum state interval next to it.

### 2. The cause rule

**What a stop record carries.** VDA 5050 3.0.0 (A): `errors[]` with `errorType`, `errorReferences` ("e.g., `nodeId`,
`edgeId`, `orderId`, `actionId`"), `errorDescription`, `errorHint`, `errorLevel`; CRITICAL "shall not continue driving
since it can not continue its current order" (L1125) and also covers order and zone errors (NODE_UNREACHABLE,
BLOCKED_ZONE_VIOLATION L870); `actionStatus` has seven values incl. 'RETRIABLE' (L1877); `safetyState.fieldViolation`
"Protective field violation (e.g., by laser or bumper)" (L1931) names no obstacle. **No field says "blocked by another
vehicle"**; BLOCKED is a zone robots "shall not enter". VDA's own traffic stop is a self-fact, "shall stop at the
decision point if no further nodes and edges are added to the base" (L353), visible only in `nodeStates`, which our
emitter does not carry. SEMI E116 "reasons ... why equipment is blocked" (abstract read,
https://store-us.semi.org/products/e11600-semi-e116-specification-for-equipment-performance-tracking) and PackML
"blocked" / "starved" (Part 4 §2, A) are the unit's own report. Open-RMF builds "Waiting for [robot:" from its schedule
`dependencies` (`rmf_ros2` `WaitForTraffic.cpp`, A); openTCS `Vehicle.State` has no blocked state (A). Every MAPF
conflict is defined on plans: a following conflict "occurs iff one agent is planned to occupy a vertex that was occupied
by another agent in the previous time step" (Stern et al. 2019, https://arxiv.org/abs/1906.08291, A); ADG "Type 2
edges" come from the plan (Hönig et al. 2019, A); the Chalmers / Kollmorgen blocking names "blocker(s)" from
traffic-rule activations and stores the blockee's "planned path" (A); OTTO's Blocked is the robot's own state on its
"planned path" (A, §1). **No source found attributes a robot's stop to another robot from adjacency alone** (a search
absence, not proof; WebSearch: "multi-robot "blocked by" attribution requires planned path", "AGV log analysis waiting
time attributed to blocking vehicle "wait-for graph"", ""blocking graph" AGV congestion", "Open-RMF rmf_fleet_adapter
blockade negotiation "deadlock" traffic conflict obstacle event", "Network Rail Delay Attribution Principles reactionary").

| cause key | label now | what the stream shows | claimable from the stream | label to use (neighbour rows: our plain wording, no standard term exists) |
|---|---|---|---|---|
| `faulted_self` | Robot fault | own `errorLevel` CRITICAL/FATAL | yes, a self-fact; but CRITICAL includes order and zone errors, not only faults | **Robot error, cannot continue order** (VDA 5050 L1125-1126); export `errorType` |
| `blocked_by_faulted` | Blocked by a faulted robot | a CRITICAL/FATAL robot within one cell | the co-location is a fact; "blocked by" needs the route or reservation | **Stopped next to a robot in error** |
| `blocked_by_stuck` | Blocked by a stuck robot | a stuck robot within one cell | same; a wait-for edge needs plans (ADG) or the fleet manager's dependency log | **Stopped next to a stuck robot** |
| `traffic` | Traffic wait | any robot within one cell | same; VDA's traffic stop is visible only from `nodeStates` | **Stopped next to another robot** |
| `unknown` | Stopped, cause not identified | no robot within one cell, no error | yes, the residual | keep; it means "no robot nearby, no error reported"; most episodes on every simulator run (README (s)) |
| `station_overrun` | Station stop over time limit | own stop at a station cell past T | yes, a self-fact plus site configuration | keep |

**Verdict 2.** Three causes are self-facts a stream-only observer can claim: `faulted_self`, `unknown`,
`station_overrun`. The three neighbour causes are co-location facts; "blocked by" for them needs the planner's
conflict or dependency log (Open-RMF `dependencies`, an ADG, the Kollmorgen traffic-rule trace), which a VDA 5050
state stream does not carry. Rename them as in the table; keep the keys (Part 4 §2's PackML anchors for them are
annotated). `faulted_self` is checked first, so a robot reporting NODE_UNREACHABLE because another robot is in the way
is filed as an error; export `errorType` so the client can tell.

### 3. Scholarly rerun of the absence claims

All listed queries plus 1-2 sharper ones per claim, on OpenAlex and Semantic Scholar (per-query status in the report;
"S2" = a Semantic Scholar query of the claim answered). Every row of Part 5 is verified@2026-10-21. *(Coverage rule
rewritten 2026-10-21: an absence claim needs two independent scholarly indexes, OpenAlex plus one of Semantic
Scholar, dblp, Lens or CORE. The "kept" rows below were rerun on CORE in Part 7, which gives each row's status.)*

| claim (part) | queries | hits that change the verdict | verdict |
|---|---|---|---|
| per-cell unknown delay probabilities (1 Q5) | 4, S2 | Kita et al. 2023 (above) | **overturned** |
| hidden slow cells as a routing disturbance (3 Q3) | 4 | Kita et al. 2023 | weakened |
| standard name for time to clear (1 Q4) | 4, S2 | Kondaveeti et al. 2011, RTN | weakened |
| HMM / isolation forest / autoencoder on fleet telemetry (1 Q1) | 8, S2 | Azzalini et al. 2020, single robots | weakened (fleets only) |
| rebuilding "blocked by a faulted robot" from telemetry (1 Q1) | 5 | none; Petri-net detection on the controller model only | kept |
| decayed per-cell counts as a named baseline (1 Q2) | 2, S2 | none | kept (results off-topic) |
| per-lesson pool-conditioned chance rate (1 Q3) | 6, S2 | none | kept (results off-topic) |
| deadlock detection from observed-state logs (2 §1) | 8 | none; on-board or planned-trajectory methods; Chalmers 2025 reads controller state | kept |
| passive message-loss map (2 §4) | 7, S2 | none new (Zarour 2023, O'Brien 2025 already cited) | kept |
| public multi-robot warehouse log (2 §5) | 4 | DeepFleet (arXiv 2508.08574, A-) trains on real Amazon fleet data, no release stated | kept (private logs exist) |
| time-in-state share of a real AMR (2b §3) | 7 | none; a 10-AMR hospital study (Sci. Rep. 2026) gives none | kept |
| blocked-edge inference with DR / delay / FA (3 Q1) | 8 (3 OpenAlex repeats), S2 | none | kept |
| fleet forecast vs persistence on real logs (3 Q2) | 4, S2 | DeepFleet forecasts on held-out real data with no persistence row | kept |
| k × median dwell rule, station-stop timeout (4 §1) | 6 | none (4 near-empty result sets) | kept, uninformative |
| absence-based blocked-cell detection in fleets (4 §3) | 6 (1 OpenAlex repeat) | none new (road-only) | kept |

### 4. Contradiction sweep (Parts 1-4, COMPETITION.md, docs/scouting/README.md)

| subject | disagreement | better-sourced | action |
|---|---|---|---|
| VDA 5050 `errorLevel` on 2.1.0 | Part 2 §2 cites the 3.0.0 four levels under "(3.0.0 and 2.1.0)"; Part 4 §2: 2.1.0 has WARNING / FATAL only | Part 4 (both texts read; L1137 re-read here) | Part 2 §2 annotated |
| MoRoOp contents | Part 2 §5 row lists "delays, failed navigation" as contents and 140,386 rows; Part 2b: phenomena, raw rows | Part 2b (paper + HF viewer) | Part 2 §5 row annotated |
| per-cell unknown delays; time to clear | Part 1 §5 and its absence list (Q4, Q5) | Kita 2023 (text read); Kondaveeti (abstract) | Part 1 §5 and list annotated |
| hidden slow cells | Part 3 Verdict 3 "No paper tests hidden slow cells" | Kita (per edge) | Part 3 annotated |
| cause labels | Part 4 §2 anchors three neighbour labels to PackML Suspended (blocked), calls CRITICAL/FATAL "Robot fault", Verdict 2 fixes the six strings | PackML / E116 / OTTO: own report; VDA L1125 | Part 4 §2 annotated |
| acyclic-chain name | Part 2 §1 "No formal name ... was found" | Chalmers 2025 "blocking graphs" (not peer reviewed) | Part 2 §1 annotated |
| MiR doc surface | COMPETITION: no public docs tree | a 2020 MiR Fleet 1.2 guide exists on a distributor mirror; says nothing about what is behind the sign-in | COMPETITION noted |
| search coverage | the brief and Parts 1, 3 say Google Scholar never tried and no S2 search ran; Part 2b §2 ran Google Scholar "MoRoOp" and read one S2 record | Part 2b (its own log) | none; coverage lines are per part |

### 5. What this means for us (Part 5)

- **Threshold:** keep 30 s as the default, make it a documented site setting, and label it "set by us, no standard".
- **Cause labels:** keep the keys. Rename faulted_self to "Robot error, cannot continue order". The three neighbour
  labels become "Stopped next to ..." because "blocked by" needs the planner's log.
- **Absence claims for the gurren page:** none may front it yet. Parts 1-3 require a Semantic Scholar rerun and it
  answered 9 of 64 queries (none for deadlock-from-logs); the 429 reply asks for an API key, an operator action.
  *(Superseded 2026-10-21, Part 7: the bar is now OpenAlex plus one more independent index; of the eleven kept rows
  of §3, eight reach it on CORE and three do not; seven claims may front the page; see Part 7.)*
  The code, README and pages keep the old labels until a lane renames them.

## Part 6: state of the art per deliverable (2026-10-22)

Scope: one row per deliverable of the fleet analyser, the best published method next to ours, with numbers, to answer
the operator's "not SOTA, right?" (21 Oct). Scheduled for 2026-10-22, fetched 2026-10-21, so every source checked in
this pass is `verified@2026-10-21`; rows reused from Parts 1-3 keep the date they were read. One pass (WebSearch,
WebFetch, curl to arXiv, OpenAlex, Semantic Scholar, `pdftotext` on one ETSI PDF). Query log:
`reports/wr-dev-lit-sota.md`. Read depth as in Part 2: A text read (A\* through a summarising fetch),
A- abstract or record (a benchmark number read from an abstract is A-), S snippet. **Coverage:** Semantic Scholar
answered 1 of 3 queries (2 × HTTP 429); OpenAlex answered 8 searches and 4 DOI lookups, then its daily budget ran out
(4 searches 429); Google Scholar not tried. Our side never has planner access: the analyser reads the state stream.
Our numbers are the headline rule of README (s) unless a row says otherwise; none is in-sample.

### (1) Stall / stuck detection from a state stream
- **Best published:** (a) the no-progress rule, Nav2 `simple_progress_checker.cpp` defaults
  `required_movement_radius` 0.5 m, `movement_time_allowance` 10.0 s (A, grepped,
  https://github.com/ros-navigation/navigation2/blob/main/nav2_controller/plugins/simple_progress_checker.cpp,
  verified@2026-10-21); runs inside the robot's own navigation stack, no accuracy figure. (b) Tarapore, Christensen & Timmis 2017
  (https://doi.org/10.1371/journal.pone.0182058, A\*, verified@2026-10-21): 20 simulated e-pucks in ARGoS, no planner,
  injected faults; faulty robot flagged a mean 0.89 ± 0.14 of the time for five fault types incl. both wheels dead,
  normal robots tolerated 0.97-0.99 of the time. (c) Azzalini et al. 2020 (https://doi.org/10.5555/3398761.3398779,
  A-, verified@2026-10-21): HMM on real single-robot routine logs; it "improves by 6% the area under the ROC curve" of standard online methods.
- **Ours:** README Sprint 5: recall 0.698, strict precision 0.216 against the simulator's stuck flag (8 zones × 12
  robots, breakdown-heavy preset, **old rule**, not re-measured under (s), no CI). Real log (s): MoRoOp's 2 labelled
  episodes ≥ 30 s both detected, 5 unlabelled stuck runs; too few for a rate. **Not comparable:** time share on
  injected motor faults vs episode recall against a simulator flag.
- **Gap and cost:** closed on method: ours is the standard rule (Nav2 shape; 30 s is our parameter, Part 5 §1).
  Learned detectors are scored on injected faults (b) or one real robot (c). Missing: a real fleet log with stuck labels.

### (2) Stall hotspot map and its grading
- **Best published:** (a) ETAS per-cell intensity, Mohler et al. 2015 (https://doi.org/10.1080/01621459.2015.1077710,
  A- for the numbers, abstract via OpenAlex; the in-press PDF Part 1 read now returns 404; verified@2026-10-21): real
  crime, 3 LAPD + 2 Kent divisions, 20 boxes of 150 × 150 m per shift (CEBCP summary,
  https://cebcp.org/evidence-based-policing/the-matrix/micro-places/micro-places-mohler-et-al-2015/, secondary);
  "1.4–2.2 times as much crime" as **crime analysts**, not as a decayed count. (b) Fitzpatrick, Gorr & Neill 2020 SI
  (https://arxiv.org/abs/2011.06019, A, Part 3, verified@2026-10-21): Pittsburgh, the moving average (MAVG) best up to
  3 % of area, pAUC 1.31 vs 1.23 for the best of nine incl. two self-exciting point processes, no CI. Grading:
  hit rate and PAI (Chainey et al. 2008, https://doi.org/10.1057/palgrave.sj.8350066, A, Part 1, verified@2026-10-18),
  the ETS chance term (Part 1 §3).
- **Ours:** (j), unchanged under (s): map minus persistence, truth precision at K 20, s8b −0.008 (CI −0.020 to
  +0.005), sticky +0.002 (−0.010 to +0.017); K 40 worse on both. K 20 of 380 cells is 5.3 % of the zone, against
  0.2-0.5 % in the NIJ challenge and ≤ 3 % in (b). **Not comparable:** planted floor cells vs crime events, and a
  different area share. The grading half (PAI form, ETS-form lift, persistence reference) is the standard.
- **Gap and cost:** behind on method: ETAS (background rate μ per cell plus a fitted decay) was never built. The
  precedent is mixed, so the size is unknown: Mohler et al. 2011 (https://doi.org/10.1198/jasa.2011.ap09546, A, Part 1,
  verified@2026-10-18) found ETAS beats the prospective-hotspot family ours belongs to, while in (b) a moving average
  beat two self-exciting models. Closing it: one lane, ETAS fitted on seeds 0-9 and scored paired against
  persistence on held-out seeds 10-29, as (j).

### (3) Per-robot time budget
- **Best published:** SEMI E10's six equipment states (https://store-us.semi.org/products/e01000-semi-e10-specification-for-definition-and-measurement-of-equipment-reliability-availability-and-maintainability-ram-and-utilization,
  A-, Part 2, verified@2026-10-20) and Standridge's AGV utilisation buckets, travel / blocked / load-unload / idle
  (ch. 17, https://eng.libretexts.org/Bookshelves/Industrial_and_Systems_Engineering/Beyond_Lean_-_Simulation_in_Practice_(Standridge)/17%3A_Automated_Guided_Vehicle_Systems,
  A\*, Part 2, verified@2026-10-20). One number in a
  fleet setting: "blocking delays could account for 2%-20% of the transaction cycle times" (Roy, Krishnamurthy, Heragu
  & Malmborg 2016, https://ideas.repec.org/a/ids/eujine/v10y2016i1p51-80.html, A-, verified@2026-10-21), simulated
  autonomous-vehicle storage and retrieval.
- **Ours:** (o) under (s): stuck 20.81 % of AGV time undisturbed, 26.03 % planner-blind blockage, 32.95 % sticky floor
  (80-240 simulated AGVs, no CI); MoRoOp 0.675 % (one robot, 9 lab shifts; T = 300 s, the cap, not tuned on the label;
  no CI). **Loosely comparable** with Roy: both a share of time, but ours counts every stop ≥ 30 s off a shelf or
  station, theirs blocking within a transaction.
- **Gap and cost:** closed: ours is the standard method (E10 classes, Standridge buckets, Part 2 §2). Left: VDA 5050
  states the stream does not carry yet (charging, action states), a field mapping, not a method.

### (4) Congestion measure for a fleet
- **Best published:** no fleet standard (Part 2 §3: no "wait ratio" or "congestion index" found; MAPF reports
  throughput). Nearest: Standridge's "average number of AGV's waiting due to contention for control points" (ch. 17
  above, A\*, Part 2, verified@2026-10-20), a model output; road traffic's Travel Time Index, "a comparison between the travel
  conditions in the peak period to free-flow conditions" (FHWA, https://ops-dr.fhwa.dot.gov/congestion_report_04/appendix_C.htm,
  A, verified@2026-10-21), no planner.
- **Ours:** (p) under (s): blocked robot-seconds in mutual clusters (≥ 2 robots, symmetric adjacency, ≥ 30 s) per
  robot-hour: 100.6 undisturbed (2.8 % of robot time), 1.41× planner-blind, 1.59× breakdowns, 2.98× sticky floor
  (no CI). Same unit as Standridge's form, narrower count; no TTI computed. **Not comparable** with any number found.
- **Gap and cost:** none to close against a fleet standard, consistent with Part 2 §3. To reach the cross-field
  standard: one small lane computing per-job TTI, job time over the free-flow A\* time on the empty map.

### (5) Early warning of a hidden blockage or slow cell
- **Best published:** freeway automatic incident detection (TTI report 2917-1F, http://tti.tamu.edu/documents/2917-1F.pdf,
  A, Part 3, verified@2026-10-21):
  California #7 / #8 67 % / 68 % detected, 2.91 / 3.04 min, 0.134 % / 0.177 % of incident-free intervals; McMaster
  68 %, 1.4 min, about 0.013 false alarms per hour (Part 3's arithmetic, 24 h assumed); real loop detectors, lane-scale incidents, no planner. Neill et
  al. 2005 (https://cs.nyu.edu/~neill/papers/sss-kdd05.pdf, A, Part 3, verified@2026-10-21): outbreaks under 5 cases
  are missed, "essentially no signal to detect". Road-closure patents (HERE https://patents.google.com/patent/US11270578B2/en,
  TomTom https://patents.google.com/patent/US10767999B2/en, Part 4, verified@2026-10-21) publish no detection rate.
- **Ours:** planner-blind blocked cell, 50 windows, 10 zones × 500 steps, no CI: map K 20 6 / 50, median 295 s,
  177.8 false alarms per zone-hour (k, unchanged under (s)); CUSUM 2 / 50 at 0.000 (n, old rule, not rerun); traffic
  absence 0 / 50 at every alpha (t). **Not comparable:** a lane-scale incident vs one cell of 380.
- **Gap and cost:** no published equivalent in our setting (Part 3 Verdict 1, kept in Part 5 §3; this pass's queries
  below). What we lack is signal, not method: the busiest cell sees 14-19 passes per run (Part 4 §4). Closing it
  needs multi-shift history per cell or a planner-side signal (replans, detours), i.e. data, then the S14B test rerun.

### (6) Cause attribution of a stop
- **Best published:** attribution from the plan plus observed state. Rail: Daamen, Goverde & Hansen 2009 (Netw. Spat. Econ. 9(1)), conflicts
  and knock-on delays identified "automatically and without discrimination" from "standard train describer and
  infrastructure messages" (https://doi.org/10.1007/s11067-008-9087-2, A-, verified@2026-10-21), real Dutch network,
  route data in hand. Robots: Open-RMF builds "Waiting for [robot:" from schedule `dependencies` (`WaitForTraffic.cpp:199`,
  https://github.com/open-rmf/rmf_ros2/blob/main/rmf_fleet_adapter/src/rmf_fleet_adapter/events/WaitForTraffic.cpp, A,
  grepped, verified@2026-10-21); MAPF defines a following conflict on planned paths (Stern et al. 2019,
  https://arxiv.org/abs/1906.08291, A, Part 5, verified@2026-10-21). No
  attribution accuracy figure was found for any of them.
- **Ours:** six labels (s): "Stopped, cause not identified" is 440 of 588 episodes undisturbed and 1,180 of 1,391 on
  the sticky floor (no CI); the three neighbour labels are co-location facts (Part 5 §2). The Sprint 5 "cause agreement 0.907"
  is against a proximity proxy built on the same geometry, so it is circular, not accuracy. **Not comparable:** no
  accuracy number on either side.
- **Gap and cost:** behind: published attribution reads the plan or the controller's dependencies, ours reads
  adjacency. The stream already carries the robot's next route node (`nodeStates` truncated to `agent.path[0]`,
  `fleet/fleet_analyser/emitter.py:17-19, 202-209`; parsed as `next_x`, `fleet/fleet_analyser/parse.py:35`), but
  `_cause` does not read it (`fleet/fleet_analyser/detector.py:258-271`). A detector-only lane, rerun on the existing
  stores, could label a neighbour stop "robot X is on its next route node", a directional geometry fact, still not
  Part 5 §2's "blocked by" (that needs the planner's log). It leaves `unknown` (no robot within one cell) unchanged;
  (o) found 76-97 % of stall episodes start next to a shelf (old rule), so a shelf-wait label (E10 "no operator") may
  be the larger lever on `unknown`; that overlap was not measured.
- **Built in S14D (2026-10-21, PR #54), label split by route node:** "Blocked by ..." / "Traffic wait" only when the
  blocker is on the next route node, else "Stopped next to ..."; on-route share of neighbour-cause episodes 8.2-31.0 %
  (45/148 undisturbed, 44/142 planner-blind, 4/49 breakdown, 9/110 s8b, 17/186 sticky floor; README (v)). Still a
  geometry fact, as above.

### (7) Message-loss / connectivity map from telemetry
- **Best published:** 3GPP MDT, ETSI TS 137 320 V10.1.0 §5.2.1.2 (A, PDF grepped,
  https://www.etsi.org/deliver/etsi_ts/137300_137399/137320/10.01.00_60/ts_137320v100100p.pdf, verified@2026-10-21):
  "Upon Radio Link Failure detection in the UE, RLFreport ... also includes available location information on where
  RLF occurred"; Annex A lists coverage holes as the use. The device logs the failure; no detection rate is given.
  Active probing maps measure loss directly (O'Brien et al. 2025, https://doi.org/10.3390/jsan14060110, A-; Simbe,
  https://patents.google.com/patent/US11897148B2, A\*; Part 2 §4, verified@2026-10-20).
- **Ours:** (p) gap map on `s12-deadzone`: precision@10 0.57 (ceiling 0.60), 57 of 60 planted dead cells found
  (recall 0.95); synthetic, every message in a dead cell dropped, no CI. **Not comparable:** no published number.
- **Gap and cost:** no published equivalent in our setting (inference from headerId gaps with no device-side failure
  report; Part 2 §4, kept in Part 5 §3). Missing is a real check: AI4Mobile (3 AGVs, radio plus positions, Part 2 §5)
  is the one public log for it; an adapter lane plus an IEEE DataPort login.

### Where we stand (Part 6)
- **At the standard:** (1) the stuck rule, (3) the time budget, and the grading half of (2).
- **Behind:** (2) ranking (ETAS not built; precedent mixed, size unknown) and (6) cause (adjacency, not the plan).
- **No published equivalent in our setting:** (4), (5), (7), on the queries below and in Parts 2-5; Semantic Scholar
  answered 1 of 3 here, so none of these absences may front a pitch (Part 5). *(2026-10-21, Part 7: (5) and (7) now
  have two indexes, OpenAlex and CORE; (4) has one.)*
- **The row that matters is (6):** it is the label a client reads on every stop, and the next route node is already in
  the stream, so a detector-only lane changes it; (2) has mixed precedent and (5) is a data floor.

**Queries (Part 6)** (full strings and per-query status in the report; S2 = Semantic Scholar):

| row | service: query (abridged) | result |
|---|---|---|
| 1 | OpenAlex: "stuck robot detection fleet telemetry precision recall", "anomaly detection autonomous mobile robot fleet operational logs"; arXiv: `abs:"stuck detection" AND abs:robot` (0), `abs:warehouse AND abs:robots AND abs:anomaly`; WebSearch (extended): multi-robot warehouse fault detection, real fleet data; S2: "stuck robot detection warehouse fleet" (429) | Tarapore 2017, Cline et al. 2026 (arXiv 2603.14622, no numbers in abstract); no real fleet evaluation |
| 2 | OpenAlex: "self-exciting point process hotspot forecasting field trial predictive policing"; S2: "self-exciting point process crime forecasting comparison" (429) | Mohler 2015 |
| 3 | OpenAlex: "Roy Krishnamurthy Heragu Malmborg blocking ..." (429, read on IDEAS) | Roy 2016 |
| 4 | OpenAlex: "multi-robot congestion metric delay per robot warehouse"; arXiv: `abs:congestion AND abs:"multi-robot" AND abs:metric` (1, flocking); WebSearch: FHWA travel time index, Urban Mobility Report definitions | no fleet congestion index; FHWA TTI |
| 5 | WebSearch: automatic incident detection benchmark, detection rate, false alarm rate, mean time to detect | AID studies 1996-2013 only |
| 6 | OpenAlex: "railway delay attribution automatic train describer data", "delay attribution multi-agent root cause robot fleet", "automatic delay attribution railway machine learning accuracy" (429); arXiv: `abs:"root cause" AND abs:"multi-robot" AND abs:delay` (0); S2: "delay attribution blocking robot fleet" (200, off-topic) | Daamen et al. 2009; no attribution accuracy figure |
| 7 | OpenAlex: "radio link failure report location coverage hole detection minimization of drive tests", two more (429); arXiv: `abs:"packet loss" AND abs:map AND abs:robot`, `abs:"coverage hole" AND abs:robot` (off-topic); WebSearch: 3GPP MDT RLF report coverage hole | TS 37.320; no passive gap inference, no accuracy figure |

## Part 7: second index for the absence claims (2026-10-22)

Scope: every absence claim marked "kept" in Part 5 §3 and the absence clauses of Part 6, rerun on a second scholarly
index (operator, 21 Oct: the second index does not have to be Semantic Scholar). Scheduled for 2026-10-22, fetched
2026-10-21, so `verified@2026-10-21`. Query log, per-query status and raw counts:
`reports/wr-dev-lit-index-rerun.md`. Ranks as in Part 2 (A read, A- abstract or record).
**Services:** dblp: not run (Anubis bot wall on dblp.org and dblp.dagstuhl.de, uni-trier and SPARQL time out).
Semantic Scholar: not run (API 429 "apply for a key"; web page 403). Lens: not run (HTTP 200 but a JavaScript shell,
no result titles). CORE web page: not run (Cloudflare 403). **CORE API v3 without a key
(https://api.core.ac.uk/v3/search/works/): ran**, 63 flat AND queries
(title-or-abstract per term), all HTTP 200, plus 37 OR-grouped queries whose zeros are not counted, because CORE's OR
is unreliable (an added OR alternative shrank 14 hits to 0; log). The OpenAlex reruns of Part 6's four 429 queries hit
the daily budget again (429): not run.

**Calibration.** CORE retrieved 10 of 16 papers OpenAlex had already found (Kita, Azzalini, Tarapore, Bonetti, Zarour,
Daamen, Mohler, Neill, Gerling, Chainey). It missed DeepFleet, MoRoOp, Lee 2026, O'Brien 2025, Fitzpatrick 2020 and
Kondaveeti 2011, mostly 2025-26 items. Rule used below: **a claim has two indexes when CORE's flat queries for it ran
and CORE retrieved at least one known paper of that claim's field.** CORE results add nothing about papers newer than
its harvest.

### Changes first

- **Weakened, Part 6 (6) "no attribution accuracy figure".** Nyström 2008, "A methodology for measuring the quality of
  deviation reporting", Int. J. Quality & Reliability Mgmt (https://doi.org/10.1108/02656710810890863, A-, Crossref
  checked, verified@2026-10-21): a vignette survey "to measure the consistency of railway delay attribution", which
  railways "can use ... to estimate the accuracy of their delay attribution systems". Human attributors, no figure in
  the abstract. A measurement method exists for rail; still no accuracy number for automatic attribution.
- **Contradiction, Part 1 papers table.** https://doi.org/10.1177/02783649261470035 and
  https://arxiv.org/abs/2609.10400 are titled "A traffic management system for large and heterogeneous vehicles in
  narrow industrial environments" (Bonetti, Proia, Guidetti, Sabattini, IJRR 2026; Crossref and arXiv API, A-,
  verified@2026-10-21), not "Deadlock detection and resolution for AGV fleets". Row annotated; its content claim was
  not re-read here. CORE also returned "Efficient Deadlock Detection and Resolution Algorithm for AGV Fleet Management"
  (2024, CORE record 166089625, title only), close to Part 1's title: the row may merge the 2024 and 2026 papers.
- **Overturned:** none.

### Second index per claim

| claim (part) | CORE flat queries | known item in CORE | indexes | status | verdict |
|---|---|---|---|---|---|
| rebuilding "blocked by" from telemetry (1 Q1) | 5 (0-1 hits each) | Bonetti, Tarapore | OpenAlex, CORE | two indexes | kept |
| decayed per-cell counts as a named baseline (1 Q2) | 4, off-topic | Mohler, Chainey | OpenAlex, CORE | two indexes | kept (off-topic on both) |
| per-lesson pool-conditioned chance rate (1 Q3) | 4, off-topic | Mohler, Chainey | OpenAlex, CORE | two indexes | kept (off-topic on both) |
| deadlock detection from observed-state logs (2 §1) | 6 | Bonetti (unprompted, 2a.1) | OpenAlex, CORE | two indexes | kept: AGV deadlock hits all on controller or simulation models |
| passive message-loss map (2 §4; Part 6 (7)) | 7 | Zarour (unprompted); O'Brien missed | OpenAlex, CORE | two indexes | kept |
| public multi-robot warehouse log (2 §5) | 4 | DeepFleet, MoRoOp missed | OpenAlex | one index | kept (CORE: synthetic images, simulated logs only) |
| time-in-state share of a real AMR (2b §3) | 5 | Gerling; Lee missed | OpenAlex, CORE | two indexes | kept |
| blocked-edge inference with DR / delay / FA (3 Q1; Part 6 (5)) | 5 | Kita, Neill | OpenAlex, CORE | two indexes | kept; near hit Catal et al. 2020 (one AGV's camera, https://doi.org/10.1109/iros45743.2020.9341386, A-) |
| fleet forecast vs persistence on real logs (3 Q2) | 4 (0-3 hits) | DeepFleet missed | OpenAlex | one index | kept |
| k × median dwell rule (4 §1) | 4 | none tested in the field | OpenAlex | one index | kept, uninformative |
| absence-based blocked-cell detection (4 §3) | 5 | Neill | OpenAlex, CORE | two indexes | kept (road-only, e.g. lane closure from connected-vehicle speeds, https://doi.org/10.1155/atr/9579025, A-) |
| real fleet evaluation of stuck detection (Part 6 (1)) | 3 | Tarapore, Azzalini | OpenAlex, CORE | two indexes | kept |
| fleet congestion index (Part 6 (4)) | 3 (0, 26 off-topic, 0) | none tested in the field | OpenAlex (1 query) | one index | kept |
| automatic stop-attribution accuracy (Part 6 (6)) | 4 | Daamen (unprompted) | OpenAlex (2 of 3), CORE | two indexes | **weakened** (Nyström 2008) |

### What this means for us (Part 7)

- **Coverage rule, rewritten in Part 1 and Part 5 §3 (2026-10-21):** an absence claim needs two independent scholarly
  indexes, OpenAlex plus one of Semantic Scholar, dblp, Lens or CORE. Semantic Scholar is no longer required.
- **May front the gurren page's "what we could not find" line**, worded "not found in OpenAlex or CORE", never "does
  not exist": deadlock detection from observed-state logs; a passive message-loss map; blocked-cell or blocked-edge
  early warning from fleet traces (Part 6 (5)); a real fleet evaluation of stuck detection; rebuilding "blocked by"
  from telemetry; a time-in-state share for a real AMR. Seven claims.
- **May not yet:** a public multi-robot warehouse log and fleet forecast vs persistence (CORE missed the one known
  paper, DeepFleet), the k × median dwell rule, and a fleet congestion index (no known item to test CORE on; one
  OpenAlex query). Also the two crime-forecasting absences (1 Q2, 1 Q3): they have two indexes, but both result sets
  were off-topic, which Part 5 already called "uninformative rather than confirmed", as for 4 §1. Part 6 (6) is weakened: say "no accuracy figure found for automatic attribution".
- The two-index bar is about search coverage. It does not make an absence a proof; CORE's blind spot is 2025-26
  preprints, where this field moves fastest.

## Part 8: the naive stall rule and duration spread as a congestion proxy (2026-10-23)

Scope: the two builds the operator's 23 Oct decision puts before the page (laptop-scheduler
`jobs/wr-lane-s15a-naive-stall-baseline.md`, `jobs/wr-lane-s15b-duration-spread.md`): measure the page's "real stalls"
and blocking figures against the two vendor methods COMPETITION pass 4 found (InOrbit, OTTO), on data already on disk.
One pass on 2026-10-23 (WebSearch, curl of the InOrbit developer doc and the FHWA report, OpenAlex, CORE API v3),
so `verified@2026-10-23` unless a row says otherwise (eCFR, OPC and one PDF added after review). Query log: `reports/wr-dev-lit-s15.md`. Ranks
as in Part 2 (A read, A- abstract or record, S snippet). **Coverage:** OpenAlex 7 queries; CORE 9 flat queries ran,
5 more answered 429 and are not counted; calibration hits: Tarapore 2017 (stall field) and Li et al. 2018 (AGV
travel time). Semantic Scholar, dblp, Lens: not tried (Part 7 found them closed).

### 1. The naive stall rule

**What vendors document.** InOrbit's developer doc (https://developer.inorbit.ai/docs, A, raw HTML read) has three
stillness forms, and **none is a velocity flag or a 30 s timer**:

| InOrbit form | gate | stillness | alert after | what fires |
|---|---|---|---|---|
| `unableToNavigate` (Advanced Incidents, "Navigation Problems") | `getValue('dsMission') in ['DELIVERY','RETURN-DOCK']` | `visitedAreaDiagonal(60)` BELOW 2 | `"sustainedForSeconds" : 600` | status ERROR, incident "Unable to reach destination", SEV 2 |
| "Example: Robot stopped while on a mission" (Expressions Language) | `hasTag("prod") and getValue('currentProgram') == "DELIVERY"` | `visitedAreaSide(180) < 2` | none: "has not left a 2-meter square for three minutes" | a status rule |
| traffic-zone `blocked` thresholds (`isZoneBlocked`) | robot inside a zone | "moved less than meters over the last seconds"; example 0.3 m / 60 s; "The preset nogo and soz types come with 30 seconds and 0.5 meters" | live | a zone state, not a per-robot alert |

`visitedAreaDiagonal(<seconds>)`: "The diagonal length of the smallest bounding box containing all of the robot
positions during the last N seconds. It allows determining if the robot is actually moving; beyond its linear or
angular distance". Pass 4 quoted only the first form; the second is new here. Both are examples a customer copies,
not shipped defaults. Formant (https://docs.formant.io/llms.txt, title index read): events are thresholds on a
numeric stream ("Each datapoint in this numeric set stream is compared to the threshold(s) you define",
/docs/getting-started-create-an-event-and-configure-notifications.md, A); no stuck, stillness or idle title. MiR:
5 s path timeout then replan (Part 5 §1, 2020 guide on a mirror, verified@2026-10-21). VDA 5050 `driving` / `paused`
carry no duration (Part 2 §2, Part 5 §1). Locus, Geek+, Seegrid: no public doc tree found: UNTESTED. **Literature:**
the robot-side form is Nav2's progress checker, 0.5 m in 10 s (Part 6 (1)); failure labels start at 60 s (Part 5 §1).
A named "stall rule" with a window: not found in OpenAlex or CORE (queries in the report; Tarapore retrieved). A
k × planned-dwell window: not found (Part 4 §1). SPC has no fixed window: the bound is a fence on the sample (S14A).

**Verdict 1.** Name the baseline **"stopped on a mission"**, InOrbit's own wording; there is no standard name. S15A
runs these rules on the same stream, all gated on `orderId` non-empty, none with station or error logic:
- **N0-30**, **N0-60**: the existing detector with `stations=None` at `stuck_after` 30 s and 60 s (stillness = the
  stream's `driving` flag; N0-30 is the old 567-run rule). Expressible as the detector.
- **N1** (InOrbit `unableToNavigate`): bounding-box diagonal of the positions in the last 60 s < 2 m, held for 600 s.
- **N2-W** (InOrbit "stopped while on a mission"): largest bounding-box side of the positions in the last W s < 2 m,
  W ∈ {30, 60, 120, 180}; 180 is the documented value, the others because InOrbit's numbers are editable examples.
N1 and N2 are position rules and **not** expressible as the detector: MoRoOp's `driving` counts rotation in place
(omega > 0.05 rad/s) as moving, a displacement box does not. Positions: MoRoOp cells are floored 0.5 m, so 2 m = 4
cells (quantisation ≤ one cell); the simulator grid has no metre scale on record, so N1/N2 there read 2 m as 2 cells
and are labelled "scale assumed". A change-only log fills the window by carrying each message's position and
orderId forward to the next message; report how many N1/N2 alerts span a gap > 60 s (timebudget's gap rule).
**Not predicted.** The labelled stops ≥ 30 s (shift 7: 250 s and 127 s, GoalObstructed, `moroop_label-sb.json`)
are both hit by one `driving`-false run of 133 s (`fleet/data/moroop/budget-sb/zone7.json`, cause `unknown`), so
label length is not stillness length and a 2 m box may hold longer or shorter. S15A reports, per label, the stopped
run, the box-stillness span and each rule's alert latency.

### 2. Duration spread as a congestion signal

**What OTTO documents** (pass 4, A, verified@2026-10-22): a mean ("Average Run Time", "average run times in seconds")
and a hand method with no statistic ("task or workflow durations with a lot of variation"). **Traffic engineering**
names the spread statistics. FHWA's travel-time reliability guide
(https://ops.fhwa.dot.gov/publications/tt_reliability/TTR_Report.htm, A) recommends four: "90th or 95th percentile
travel time, buffer index, planning time index, and frequency that congestion exceeds some expected threshold". Buffer
index = "the difference between the 95th percentile travel time and average travel time, divided by the average
travel time"; planning time index = "the 95th percentile travel time divided by the free-flow travel time"; the
indices exist so that "comparisons or combinations of routes or trips with different lengths" are possible. On CV:
"standard deviation and coefficient of variation ... are discouraged as performance measures, as they are not readily
understood by non-technical audiences" (a communication argument, not a validity one). The travel time index (mean over
free flow) is FHWA's average-congestion measure (Part 6 (4), verified@2026-10-21).

| statistic | name and source | validated against a direct blocking measure? |
|---|---|---|
| (p95 − mean) / mean | buffer index, FHWA (A) | no: freeway reliability vs incident counts explored (Chen 2010, KTC, https://doi.org/10.13023/ktc.rr.2010.08, A-, abstract only, no result read) |
| p95 / free-flow | planning time index, FHWA (A) | no; SHRP 2 L03 / L33 predict p95 TTI from mean TTI ("1 + 3.4201·ln(meanTTI)", https://www.nap.edu/read/22282/chapter/2, S, snippet; page text not readable): spread tracks mean congestion on freeways |
| σ / μ | coefficient of variation; FHWA discourages it (A) | no |
| p95 / p50; p80 / p50 | Truck Travel Time Reliability (TTTR), "95th percentile travel time divided by the Normal Truck Travel Time" (50th), 23 CFR 490.611 (https://www.ecfr.gov/current/title-23/part-490/section-490.611, A); LOTTR, "80th percentile travel time divided by the 50th percentile travel time", 490.511 (A): US federal reliability measures | no |
| IQR / median | no source found naming it as a congestion measure | no |
| mean job duration | OTTO "Average Run Time" (A) | no |

No AGV or AMR paper using duration spread as a congestion or blocking proxy: not found in OpenAlex ("AGV travel
time variability congestion indicator", "task duration variance congestion warehouse robots") or CORE ("AGV
variability congestion indicator", "AGV variance blocking travel": 0 hits; Li et al. 2018,
https://doi.org/10.1155/2018/4037695, retrieved: travel-time uncertainty as a *cause* of AGV catch-up conflicts).
**Manufacturing.** ISO 22400-2's 34 KPIs, as reproduced by Kikolski 2020 (MODELSWARD,
https://www.scitepress.org/Papers/2020/91758/91758.pdf, A- secondary, table read), have no dispersion KPI on a time
(the capability indices are on quality characteristics); OPC 40001-1 C.2 maps time elements only (read). Kingman's
heavy-traffic queue (1961, https://doi.org/10.1017/S0305004100036094, A- record; the VUT form via Hopp & Spearman,
not read) has variability as a *cause* of waiting, so spread is an expected correlate of congestion, not a validated
measure of it; Little's law (1961, https://doi.org/10.1287/opre.9.3.383, A- record) relates means only.
**Trap:** raw job durations vary with route length, so a zone with mixed job lengths shows spread with no congestion.

**Verdict 2.** S15B's two **decisive** statistics, per (run, zone) over completed jobs on raw durations (OTTO's hand
method): **p95 / median** (the TTTR form: needs no free-flow time, robust to one long job) and **mean job duration**
(OTTO's figure). Descriptive only: buffer index, CV, and all of them on durations over free-flow time (Manhattan along
the job's waypoints times `STEP_S`). Agreement:
**Spearman ρ per run** (average ranks for ties) with **Kendall τ-b** next to it (scipy: tau-b is the variant that
handles ties, https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.kendalltau.html, A), and **top-3
overlap** with its chance value k²/n (0.9 zones of 3 at n = 10, 0.3 at n = 30). Per run and the median over runs;
never one pooled ρ over raw values from different runs (the 30-zone sticky run would dominate). With n = 10 a ρ near
0.65 is about the p < 0.05 line; say so. A run where either column is constant has ρ undefined: null, counted as
undecided for that run.

### 3. What refutes each

- **S15A.** Commodity if any N2-W, N1 or N0-60 on MoRoOp reaches 2/2 labelled hits with ≤ 12 stuck runs (2× our
  6). **Supports the lead** if none does. A "supports" result shows only that station logic plus the bound removes
  the alarms: InOrbit customers can write that logic (COMPETITION pass 4 scores it present as a configurable rule),
  so the page may say "not in the documented example", never "a vendor can't".
- **S15B.** Commodity if, for either decisive statistic, the median over runs of ρ(statistic, blocking number) is ≥
  0.7 with median top-3 overlap ≥ 2/3, **or** ρ(statistic, truth) ≥ ρ(blocking, truth) in at least 3 of the decided
  runs. **Supports the lead** only if both decisive statistics have median ρ with the blocking number < 0.4 **and**
  the blocking number beats both on truth in at least 4 of 5 runs. Anything else is reported as mixed. All
  thresholds are ours, set here before the run.

**Briefs:** both S15 drafts rewritten in place from Verdicts 1-2; file names, tests and result paths kept; diff in the report.

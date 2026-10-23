# wr-dev-lit-sota: LITERATURE Part 6, state of the art per deliverable (run 2026-10-21, scheduled 2026-10-22)

Output: `warehouse-rl/docs/LITERATURE.md` "## Part 6", commits a3ec4be + review fixes e4b2bbd (145 lines). Model opus, unattended.

## Verdicts per row
1 stuck detection: standard | 2 hotspot map + grading: behind (ETAS not built; gap unquantified, possibly 0) |
3 time budget: standard | 4 congestion: none (no fleet standard; TTI reachable) | 5 hidden-blockage warning: none |
6 cause attribution: behind (adjacency, not plan) | 7 message-loss map: none. Row that matters: 6 (the per-stop label;
next route node already parsed as next_x but unused by _cause; a next-node label leaves `unknown` unchanged).

## Service status
- Semantic Scholar API: 3 queries, 2 x HTTP 429, 1 x 200 ("delay attribution blocking robot fleet", off-topic).
- OpenAlex: 8 searches + 5 DOI lookups answered (10.1016/j.eswa.2015.04.011 was a wrong DOI for Khalastchi 2015, returned an unrelated paper, unused); then HTTP 429 "Insufficient budget" (no API key, daily IP
  budget, retryAfter 31767 s) on 4 searches. An API key is an operator action (free, email confirmation).
- arXiv API: first batch of 4 returned no entries because http:// got a 301 to https:// (not 0 results); rerun on
  https, results below.
- Google Scholar: not tried.

## Query log
| # | service | query | status | result |
|---|---|---|---|---|
| 1 | OpenAlex | stuck robot detection fleet telemetry precision recall | 200 | N=12, off-topic |
| 2 | OpenAlex | anomaly detection autonomous mobile robot fleet operational logs | 200 | N=1193; MoRoOp the only on-topic hit |
| 3 | OpenAlex | self-exciting point process hotspot forecasting field trial predictive policing | 200 | Mohler 2015 (381 cites) |
| 4 | OpenAlex | railway delay attribution automatic train describer data | 200 | Daamen et al. 2009 (2008 in OpenAlex) |
| 5 | OpenAlex | radio link failure report location coverage hole detection minimization of drive tests | 200 | coverage-hole papers (drive tests, UAV, relay UE, Zarour 2023); none infers holes passively from message gaps |
| 6 | OpenAlex | AGV anomaly detection operational data F1 score | 200 | N=90, off-topic |
| 7 | OpenAlex | multi-robot congestion metric delay per robot warehouse | 200 | no congestion index |
| 8 | OpenAlex | delay attribution multi-agent root cause robot fleet | 200 | off-topic (AUDITA preprint is outcome auditing, not stop attribution; not read) |
| 9 | OpenAlex | passive coverage hole detection from packet loss logs mobile robots | 429 | - |
| 10 | OpenAlex | automatic delay attribution railway machine learning accuracy incident cause | 429 | - |
| 11 | OpenAlex | coverage hole detection minimization of drive tests MDT measurements accuracy | 429 | - |
| 12 | OpenAlex | Roy Krishnamurthy Heragu Malmborg blocking autonomous vehicle storage retrieval | 429 | read on IDEAS |
| 13 | OpenAlex DOI | 10.1080/01621459.2015.1077710, 10.5555/3398761.3398779, 10.1198/jasa.2011.ap09546, 10.1007/s11067-008-9087-2 | 200 | abstracts read |
| 14 | arXiv | abs:"stuck detection" AND abs:robot | 200 | 0 |
| 15 | arXiv | abs:congestion AND abs:"multi-robot" AND abs:metric | 200 | 1 (flocking) |
| 16 | arXiv | abs:"root cause" AND abs:"multi-robot" AND abs:delay | 200 | 0 |
| 17 | arXiv | abs:"packet loss" AND abs:map AND abs:robot | 200 | 1 (UDON, mapping under comm loss, off-topic) |
| 18 | arXiv | abs:warehouse AND abs:robots AND abs:anomaly | 200 | 2, off-topic |
| 19 | arXiv | abs:stuck AND abs:robot AND abs:detection | 200 | 6, off-topic |
| 20 | arXiv | abs:"coverage hole" AND abs:robot | 200 | 3, off-topic |
| 21 | arXiv | ti:"Policing Chronic and Temporary Hot Spots" | 200 | 2011.06019 exists |
| 22 | S2 | stuck robot detection warehouse fleet | 429 | - |
| 23 | S2 | self-exciting point process crime forecasting comparison | 429 | - |
| 24 | S2 | delay attribution blocking robot fleet | 200 | off-topic |
| 25 | WebSearch | Mohler 2015 randomized controlled field trials predictive policing ETAS 1.4-2.2 ... | ok | abstract confirmed; in-press PDF now 404 |
| 26 | WebSearch | automatic incident detection algorithm benchmark detection rate false alarm rate mean time to detect ... | ok | AID 1990s-2013 only (Dia 1996, Kim 2013) |
| 27 | WebSearch | 3GPP MDT radio link failure report location coverage hole detection accuracy passive UE logs | ok | patents; TS 37.320 |
| 28 | WebSearch | FHWA travel time index annual hours of delay per commuter congestion measure definition | ok | secondary |
| 29 | WebSearch | "travel time index" "planning time index" definition FHWA ... | ok | FHWA appendix C |
| 30 | WebSearch (extended) | multi-robot warehouse fault detection stuck robot detection evaluation ... real fleet data paper | ok | Cline et al. 2026 arXiv 2603.14622 (ACC 2026; abstract gives no numbers), Tarapore 2017 |
| 31 | WebSearch | Daamen Goverde Hansen non-discriminatory automatic registration knock-on train delays ... | ok | "55 % of arrival delays > 3 min" only second-hand; NOT used |
| 32 | WebSearch | minimization of drive tests coverage hole detection RLF reports evaluation detection probability paper | ok | no detection-probability figure found |
| 33 | WebSearch | Texas A&M Urban Mobility Report definitions ... | ok | secondary only |

## Fetches
- arXiv 2603.14622 abstract (no numbers, not used in the table); PLoS One Tarapore 2017 (summarising fetch, A*:
  0.89 +- 0.14, tolerated 0.97-0.99); CEBCP Mohler 2015 summary (20 boxes 150 x 150 m per shift); FHWA congestion
  report appendix C (TTI quote); IDEAS Roy 2016 (2%-20% quote); TU Delft record Goverde et al. 2008 (no abstract);
  ETSI TS 137 320 V10.1.0 PDF -> pdftotext, §5.2.1.2 and Annex A quoted; Nav2 simple_progress_checker.cpp grepped
  (0.5 m, 10.0 s).
- Mohler in-press PDF (mshort9.math.gatech.edu) 404; Mohler numbers therefore A- (abstract).

## Our numbers used (README, headline rule (s))
Sprint 5 recall 0.698 / precision 0.216 (old rule, labelled); (s) MoRoOp 2/2, 5 unlabelled, 0.675 %; (j) paired
K 20 s8b -0.008 (-0.020 to +0.005), sticky +0.002 (-0.010 to +0.017); (s) stuck 20.81 / 26.03 / 32.95 %; (s) clusters
100.6 robot-s per robot-h, 1.41x / 1.59x / 2.98x; (k) 6/50, 295 s, 177.8; (n) CUSUM 2/50 at 0.000 (old rule);
(t) 0/50; (s) unknown 440/588, 1,180/1,391; (p) gap map 0.57 / 57 of 60. No in-sample number used (17/50 omitted).

## Review fixes (e4b2bbd, after an advisor pass)
- Row 2: ETAS precedent is mixed (Mohler 2011 ETAS > prospective map, Part 1 A; Fitzpatrick 2020 MAVG > SEPP); "may be
  zero" and "at best ties persistence" removed.
- Row 6: emitter already sends nodeStates[0] = agent.path[0] (emitter.py:202-209), parsed as next_x (parse.py:35), unread
  by _cause (detector.py:258-271); `unknown` = no robot within Manhattan 1, so a next-node rule cannot touch it; label
  stays a geometry fact, not Part 5's "blocked by". Shelf-wait label flagged as the possible lever on `unknown` (unmeasured).
- URLs + verified@ added for TTI 2917-1F, Neill 2005, HERE/TomTom, SEMI E10, Standridge, Chainey, Open-RMF
  (WaitForTraffic.cpp:199 re-grepped 2026-10-21), Stern 2019, O'Brien 2025, Simbe. Azzalini quoted verbatim. Queries
  table merged per row. Hazard: `cp` is aliased to `cp -i` here; an unattended cp hung on the prompt; use `command cp -f`.

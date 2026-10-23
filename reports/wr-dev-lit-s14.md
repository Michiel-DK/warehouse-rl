# wr-dev-lit-s14: literature check before S14A / S14B (2026-10-21)

Output: `docs/LITERATURE.md` "Part 4: service-time bounds, stall causes, traffic absence (2026-10-21)" (140 lines).
Briefs rewritten from the verdicts: `jobs/wr-lane-s14a-servicing-bound.md` (task 1 bound, task 3 cause labels, fixture
value), `jobs/wr-lane-s14b-traffic-absence.md` (task 1 test, sweep values, flag-bin test). Both briefs already carried
the "Rules from docs/LITERATURE.md Part 4" line; it was not duplicated. The briefs are not committed (laptop-scheduler).

Method: three parallel research passes (WebSearch standard mode, WebFetch, curl to Google Patents / Crossref / arXiv /
Semantic Scholar DOI lookup). Main session re-fetched: oee.com six big losses, NIST e-Handbook 7.1.6, JMP probability
limits, VDA 5050 release/2.1.0 errorLevel + eStop, OPC 30050 §6.3.8; grepped downloaded patent texts (US11270578B2,
US10847029B2, US10767999B2) for 8.83, 0.015%, "one year or longer", EXPECTED_THRESH = 10, 0.14 / 0.23, "less than 15
minutes"; Hinestroza & González 2019 TBE chart text (UCL, α 0.0027, ARL0, Chan Xie Goh lineage). Sizing of per-cell
passes on `fleet/data/s10-none` zones 0/3/7 by a scratch script (/tmp/lits14/passes.py; not committed).

## Query log

### Pass 1: station dwell bound
1. WebSearch "VDA 5050 action timeout blockingType actionParameters specification" — nothing beyond the spec
2. "SEMI E10 unscheduled downtime definition standby productive state assist" — secondary only
3. "OEE minor stops threshold 5 minutes breakdown vs small stops definition" — oee.com (A), blogs (S)
4. "MoRoOp dataset Klein Jeong arXiv mobile robot operations timeout" — null; arXiv fetched directly
5. "MiR robot mission "wait for" action timeout docking" — Scribd snippet only
6. "Open-RMF dispenser ingestor timeout task phase "dispense" request timeout" — null
7. "openTCS vehicle operation timeout load cargo "timeout" peripheral job" — null
8. "OTTO Fleet Manager job timeout autonomous mobile robot "timeout" pick drop" — marketing only (B)
9. "ISO 22400-2 KPI "planned run time per item" "actual unit processing time" definition" — catalogue/blogs
10. "SEMI E10 "assist" definition unscheduled interruption MTBA "productive time" standby" — null for assist
11. "process mining activity duration outlier detection performance spectrum delays boxplot"
12. "lognormal service time distribution control chart log-transformed cycle time upper control limit"
13. "Brown Gans Mandelbaum statistical analysis telephone call center service times lognormal"
14. "SEMI E58 ARAMS blocked starved state equipment "E116" equipment performance tracking waiting" — null on E58
15. "Kollmorgen NDC OR BlueBotics ANT server AGV load station timeout error" — null
16. "open-rmf rmf_fleet_adapter dispenser request "timeout" github RequestDispenser" — null
17. "MiR REST API mission action "wait" timeout "relative_move" OR "docking" "max time" mission error" — ROS mir_actions only
18. "VDI 4486 Zuverlässigkeit Intralogistik Verfügbarkeit Definition Störung Ausfall" — record only
19. "Leys 2013 detecting outliers median absolute deviation threshold 2.5 recommended" — secondary
Not searched: Geek+, Locus, VDI 3581 text.

### Pass 2: cause taxonomy
1. "VDA 5050 3.0 obstacle detection state message "blocked" mobile robot" — no blocked field
2. "ISO 3691-4 protective stop emergency stop stop category 0 1 personnel detection driverless trucks" — no categories
3. "SEMI E10 unscheduled downtime substates "maintenance delay" "out of spec input" standby "no operator" "no product""
4. "SEMI E10 standby time "no operator" "no product" "no support tool""
5. "SEMI E116 equipment performance tracking BUSY IDLE BLOCKED states blocked reason"
6. ""E116" "BlockedReason" OR "blocked reason" EPT equipment performance tracking SEMI" — null for codes
7. "SEMI E58 ARAMS state model reason codes unscheduled down standby productive engineering"
8. "PackML PackTags Admin.StopReason Admin.Warning Blocked Starved ISA-TR88.00.02 state "Held" "Suspended""
9. "PIADE packaging industry anomaly detection dataset zenodo 7071746 stop reasons alarms"
10. "OPC 30050 PackML PackMLAdminObjectType StopReason Warning "PackMLAlarmDataType" category"
11. "ISO 22400-2 KPI ADET actual unit delay time ADOT actual unit down time definition" — null
12. ""ADET" "ADOT" ISO 22400 "unit delay time" "unit down time" OEE availability"
13. "Nakajima six big losses equipment failure setup adjustment idling minor stoppages reduced speed defects startup TPM"
14. "ISO 14224 failure cause classification "design-related" "operation/maintenance" "management" "miscellaneous" failure mechanism table B.3" — table not found
15. "Open-RMF rmf_fleet_msgs RobotMode MODE_IDLE MODE_CHARGING MODE_MOVING MODE_PAUSED MODE_WAITING MODE_EMERGENCY"
16. "openTCS Vehicle.State UNKNOWN UNAVAILABLE ERROR IDLE EXECUTING CHARGING ProcState integration level" — null (source read on GitHub)
17. "MiR robot error codes categories "protective stop" "emergency stop" mission "path blocked" fleet state" — mostly null
18. "AMR fleet KPI "blocked" "starved" robot waiting time categories warehouse AMR downtime reasons taxonomy" — no taxonomy
Fetch failures: docs.ros.org (bot wall), opentcs.org (certificate error).

### Pass 3: traffic absence
1. curl Google Patents US11270578B2/en — full text
2. WebSearch "Pietrobon Lewis Heverly-Coulson "Road closure detection from vehicle probe data"" — AMiner record
3. Crossref API 10.1145/3325912 — abstract; 4. arXiv API ti:"road closure detection" — 0 results
5. Semantic Scholar DOI:10.1145/3325912 — abstract, no PDF; 6. ACM PDF / Unpaywall — 403 / 422
7. "An Algorithm for Road Closure Detection from Vehicle Probe Data pdf likelihood lower-volume roads parameters" — patents only
8. curl Google Patents US10767999, US11015939, US10847029, US11468768, US10192432, WO2017009464A1 — full texts
9. "Pan Zheng Wilkie Shahabi 2013 Crowd sensing of traffic anomalies pdf" — MSR PDF
10. "time-between-events control chart exponential probability limits UCL Montgomery t chart" — 2 PDFs
11. "Neill expectation-based scan statistic (C/B)^C exp(B−C) decreased counts" — arXiv papers
12. "SaTScan user guide "scan for areas with low rates"" — tutorial (S)
13. "Fawcett Provost 1999 "Activity monitoring: noticing interesting changes in behavior" AMOC" — bibliographic only
14. Semantic Scholar search "Activity monitoring noticing" — not found; 15. ""activity monitoring operating characteristic" AMOC" — secondary
16. WebFetch PMC2815453 — captcha
17. "exponential CUSUM time between events Gan 1994 Lucas 1985" — S
18. "detect blocked edge warehouse robot fleet absence of traffic MAPF" — not found
19. "Google patent detecting road closures absence of location data" — no Google patent
20. "INRIX OR Google Maps road closure detection probe absence delay minutes" — INRIX blog (S), no numbers
21. ""negative information" OR "absence of observations" multi-robot blocked aisle" — not found

## Verdicts
1. S14A bound: T = min(300 s, exp(Q3 + 3·IQR of ln dwell)) over all station stops with an order (any length), pooled
   per run, < 5 stops -> 300 s; state STUCK, cause `station_overrun`, label "Station stop over time limit".
2. Causes: six verbatim `cause_label`s (Robot fault / Blocked by a faulted robot / Blocked by a stuck robot / Traffic
   wait / Stopped, cause not identified / Station stop over time limit); correction to Part 2: VDA 5050 2.1.0 errorLevel
   is WARNING / FATAL only.
3. S14B test: time-between-events upper probability limit on the open gap (HERE zero-count rule), causal expanding rate,
   eligibility 10 expected passes, alpha 1e-3 (sweep 1e-2/1e-3/1e-4), release at next pass. Sizing predicts a negative.

## Brief edits (every change; everything else kept)
S14A `jobs/wr-lane-s14a-servicing-bound.md`:
- Task 1: bound rule replaced by Part 4 verdict 1 (min(300 s, exp(Q3 + 3·IQR of ln dwell)), linear quartiles, sample =
  every station stop with an order of any length, pooled per run, < 5 stops -> 300 s, left-truncation note); new
  ledger/result fields `servicing_sample_n`, `servicing_q1_s`, `servicing_q3_s` next to `servicing_max_s`.
- Task 3: the six verbatim `cause_label` strings written in. (An errorType/errorHint export was added, then removed:
  `fleet/fleet_analyser/parse.py` does not carry errorType, so it would touch an undeclared file.)
- Tests: fixture value T ≈ 231.5 s asserted to 0.1 s; added a four-stop case (T = 300 s); MoRoOp smoke also reports
  TIMEOUT overlaps (was 1 of 8) and unlabelled station-cell stuck runs against the Part 4 bar (≤ 54).
- NOT edited, flagged: the existing test "the set of labels [on s10-none zone 0] equals the Part 4 table" cannot pass
  as written (no faults on s10-none and no overrun with the flag absent); the lane should assert a subset, or the
  brief owner should change it.
S14B `jobs/wr-lane-s14b-traffic-absence.md`:
- Task 1: test replaced by Part 4 verdict 3 (causal expanding rate frozen while flagged, `--min-expected` default 10
  labelled a deviation from HERE, `--alpha` default 1e-3, release at next pass, no hysteresis / time-of-day / labelled
  threshold stated as deviations); score = r·gap, rank (-score, cell); claim gains `min_expected`.
- Task 1 detours: "not computable from the stream" replaced by "not built in this lane" with the Part 4 reason (one
  2,495 s run = one 30-min slot, no history; no planned route in the stream).
- Task 4: sweep values fixed to 1e-2, 1e-3, 1e-4.
- Tests: the flag bin is the first bin end where gap > ln(1/alpha)/r, computed and asserted in the test.

## Second commit (after review)
EXPECTED_THRESH relabelled (HERE's 10 is the expected count inside the tested window, so r·gap ≥ 10 ≈ 1,300 s+, longer
than any blockage: under HERE's own rule nothing is testable while open); in-sample 17/50 figure removed; Pan reason
added; positive bar for S14B now a one-sided exact sign test on discordant windows (≥ 5 to 0); harness false alarms are
flag-publishes, a multiple of α × passes; URLs added for the Cimetrix deck and MoRoOp 300 s.

SCHED_RESULT: OK lit-s14 Part 4 pushed | S14A: station stop STUCK past min(300 s, log-scale Q3+3IQR fence) | causes: six verbatim labels anchored PackML/SEMI E10/VDA; 2.1 FATAL-only | S14B: time-between-events limit on open gap, alpha 1e-3; negative likely

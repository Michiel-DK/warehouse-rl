# wr-dev-lit-fleet-management — literature check Part 2 (2026-10-20)

**Result:** `docs/LITERATURE.md` Part 2 appended in two commits on master, `536fd98` and the fix-up `9bb4326`, both pushed to
origin. Together they add 219 lines, 0 deletions (`git diff 706bab9 --stat`). Part 1 is unchanged. The run took about 20 minutes of the
75-minute budget (15:51 to 16:11 CEST).

## Findings that matter for the Sprint 12 lanes

1. **S12B "knot" is the wrong word.** In deadlock theory a knot is a closed set of nodes. Every node in it has
   outgoing edges, and every edge stays inside the set (U. Iowa 22C:116 notes; Wikipedia, wait-for graph; Misra &
   Chandy 1982). In the S12B graph each robot has at most one blocker, so a knot there is exactly a cycle, which the
   lane calls a deadlock. Rename the acyclic chain to "blocking chain" before README table (p) is written. Table (p) is the S12B deadlock
   table, per `laptop-scheduler/jobs/wr-dev-s12a-readme.md` line 21. Holt's
   1972 text could not be read (ACM returned 403).
2. **A persisting cycle is a standard idea.** It is a circular wait in a wait-for graph (Coffman et al. 1971). No
   standard name or definition was found for the ">= T s" persistence. No published method was found that detects
   robot deadlock from logs rather than from planner state, but that rests on about three queries.
3. **The S12A `faulted` bucket ("errors non-empty") conflicts with VDA 5050 3.0.** The spec's errorLevel (line 1899)
   says WARNING and URGENT robots are "able to continue active order". Our emitter only writes FATAL
   (`fleet/fleet_analyser/emitter.py:92`), so the simulated runs are unaffected; a real log would be affected. Two
   gaps in the bucket set:
   - no bucket for seconds with no message;
   - no paused, charging or manual-mode bucket. A paused robot with an order lands in `stuck`.
4. **The time budget maps onto existing standards.** SEMI E10's six states, ISO 22400-2's APT/ADET/ADOT, and
   Standridge's AGV utilisation (travel, blocked, load/unload, idle). VDA 5050 defines no state taxonomy; idle is
   derived (§6.6.8). No VDI or ISO taxonomy that separates waiting from blocked was found; the full texts are
   paywalled.
5. **Gap map.** Passive dead-zone inference from headerId gaps was not found. Location-tagged packet-loss maps exist,
   but from active probes (O'Brien et al. 2025, JSAN; Simbe US11897148B2). VDA 5050 robots "keep all the order
   information" on disconnect, so a gap is not a stop. Proposed wording for (p): "message-loss cells inferred from
   headerId gaps", not "WiFi dead zones".
6. **Real logs.** MoRoOp (Klein & Jeong 2026, arXiv 2610.02428) is one AMR in a laboratory kit-supply scenario: nine
   8 h shifts, 140,386 state rows, CC BY 4.0. I checked the Hugging Face listing myself: 9 shift folders with parquet
   files. It is useful for the time budget, not for deadlock. No public multi-robot warehouse fleet log was found.
7. **Side finding.** The TA-RWARE paper (arXiv 2212.11498, grepped by pdftotext) defines pick rate as "order-lines per
   hour". It gives no seconds per step. Our 5 s comes from the upstream script (`docs/SCOPE.md:46`), which is already
   documented.
8. **Do not cite** Fazlollahtabar & Saidi-Mehrabad 2013 (J. Intell. Robot. Syst.): it is retracted
   (https://doi.org/10.1007/s10846-023-01923-1, which resolved with HTTP 200).

## Method

The research ran as three parallel general-purpose subagents, using WebSearch and WebFetch only:
- deadlock;
- KPIs, VDI and VDA 5050;
- congestion, connectivity and real logs.

I spot-checked these in the main session:
- **VDA 5050 main**: I downloaded the raw markdown and grepped lines 187, 1034, 1241, 1458 and 1899.
- **Wikipedia's wait-for graph page**: fetched for the cycle and knot sentences.
- **MoRoOp**: the arXiv abstract page and the Hugging Face API.
- **Zenodo records 23393677 and 10204117**: through the API. Both are CC BY 4.0 and the titles match.
- **TA-RWARE PDF**: grepped with pdftotext.
- **Constructed URLs**: checked with curl. All returned 200, except IEEE Xplore (202) and Zenodo DOI (403 to curl;
  the record was confirmed through the API).

## Search log

**Services.**
- Crossref `query.bibliographic`: about 20 queries. It returned 429 twice (Coffman first try; Wurman), and both
  worked on retry or through another route.
- arXiv API: about 15 queries.
- Zenodo API, type=dataset: "automated guided vehicle", "autonomous mobile robot" fleet, AGV trajectories, warehouse
  robot trajectories, AMR telemetry.
- Hugging Face datasets API: AGV, warehouse-robot, AMR, forklift. The "mobile robot" query errored.
- WebSearch and WebFetch on standards, vendor and publisher pages.
- **Semantic Scholar: not queried. Google Scholar: not tried. Kaggle: not searched directly** (a web search found no
  Kaggle listing).

**Blocked.**
- dl.acm.org PDF (403); cs.fsu.edu (403); FLAIRS (403); MDPI (403, twice); iso.org (403); DIN (404).
- umbc.edu, isical.ac.in, ics.uci.edu: certificate errors.
- The McGill knot-detection PDF and the Sha 1990 PDF are image scans.

**Deadlock queries.**
- Holt knot definition (3 variants); Misra-Chandy knot detection; Fanti "second level deadlock"; "chained blocking";
  runtime deadlock detection for multi-robot systems; traffic gridlock definition; openTCS / fleet manager deadlock
  timeout; rmf_traffic deadlock.
- Crossref for each canonical paper: Reveliotis 2000, Fanti 1997/2000/2001, Lawley 1998 ×2, Kim & Tanchoco 1991, ter
  Mors 2010, Ho & Liao 2009, Lee & Park 2023, Vis 2006, Qiu 2002, Fazlollahtabar 2013 and its retraction, Coffman
  1971, Holt 1972, Chandy-Misra-Haas 1983, Knapp 1987, Sha 1990, Blasgen 1979.
- arXiv: RHCR, traffic-flow optimisation, PIBT, Real-Time LaCAM, Berndt ADG, Grover deadlock.

**KPI and standards queries.**
- VDI 3581, 2510, 3649, 4451, 4480, 4486, 4451-7; the VDI 3581 formula; the VDI 2510 2025 draft.
- OEE AGV/AMR; SEMI E10 states, SEMI E10 store, SEMI E79; ISO 22400-2 time model; ISO 3691-4; ISO 22166-1.
- openTCS Vehicle.State; MiR fleet statistics; BlueBotics ANT; Kollmorgen, Locus, SYNAOS.
- Le-Anh & de Koster; AGV blocking vs waiting simulation; blocking after service / before service (Perros, ×2); AMR
  blocking time.
- VDA 5050 main (3.0.0) and 2.1.0 raw markdown, read and grepped.

**Congestion queries.**
- "League of Robot Runners" (arXiv all/ti/abs): no organisers' paper found.
- MAPF wait / congestion metric; Wurman DOI; RWARE, TA-RWARE, guidance graph.

**Connectivity queries.**
- Fink & Kumar; Ferris WiFi-SLAM; AGV packet-loss coverage; packet-loss dead zones from heartbeat telemetry
  (extended search); Open-RMF lost connection; openTCS comm adapter; MiR lost connection.
- Not attempted: Hsieh et al.; Ferris 2006; Nav2; AWS RoboRunner.

**Real-log queries.**
- AGV/AMR datasets on Zenodo, DataPort and Kaggle (extended search); hospital TUG logs; AGV field data; Kaggle AGV
  telemetry.
- An arXiv author search for Benecki returned only unrelated papers.

## Absence claims in Part 2, and what each rests on

| claim | rests on |
|---|---|
| no detection of deadlock from logs | about three queries (runtime deadlock detection; rmf_traffic deadlock; openTCS timeout) |
| no standard name for ">= T s" persistence | the same queries plus the gridlock definitions |
| no name for an acyclic blocking chain | the Holt/knot queries, "chained blocking", "second level deadlock" |
| no VDI/ISO waiting-vs-blocked taxonomy | contents pages only (texts paywalled), so weak |
| no passive gap-to-dead-zone inference | the connectivity queries above |
| no multi-robot real fleet log | the Zenodo, Hugging Face and WebSearch queries above; Kaggle not searched directly |

Rerun these on Semantic Scholar before any of them fronts a pitch.

## Fix-up commit 9bb4326 (after the advisor's review)

- Table letter: the knot rename now targets (p), not (o).
- Removed one sentence whose source had been trimmed from the table: the action dependency graph deadlock-free claim
  (Berndt abstract).
- Added years to three rows: Grover 2022 (arXiv first version), Standridge n.d., WINGS 2023 (Zenodo publication_date).
- The doc now points to `laptop-scheduler/reports/` for this report, because `reports/` in warehouse-rl is
  untracked.
- Crossref wording: the doc now says the 429 lookups resolved "on retry or by another route".
- The Nav2 threshold is no longer credited with 30 s.

## Contradiction sweep (grep for knot, dead zone, deadlock, time budget)

| file | what it says | conflict |
|---|---|---|
| README, `docs/overview` | no hits for "knot" or "dead zone" | none |
| `docs/SCOPE.md:922` | "Wi-Fi dead zones (observable as gaps in the ledger)" | Part 2 recommends "message-loss cells inferred from headerId gaps" |
| `docs/scouting/operator-problems.md:167` | row 13 says "placing each gap at the robot's last position gives a dead-zone map" | same wording conflict |
| S12B brief and `wr-dev-s12a-readme.md` | "knots" in table (p) | conflicts with the rename |

None of these were edited, because README and SCOPE are outside this job. The rename is for the S12B lane or the README
pass. `wr-dev-s12a-readme.md` line 28 already tells that pass to read Part 2.

## Not done or not verified

- Holt 1972 text (ACM returned 403).
- The current wording of SEMI E10 and E79, and the ISO 22400-2 edition.
- VDI 3581's per-element formula and VDI 4451-7 §4.3.3.
- Foit et al.'s OEE definitions (MDPI returned 403).
- Vendor state models.
- How openTCS, Nav2 and AWS RoboRunner behave on lost connection.
- The MoRoOp "stuck reason" field (seen only through a summarising fetch).
- The wording of the A\* rows in the doc came from WebFetch's summarising model and was not grep-checked; the doc
  says so.
- README and SCOPE were not edited. The README (o)/(p) vocabulary and the S12B rename are the operator's or a lane's
  call.

SCHED_RESULT: OK lit Part 2 appended to docs/LITERATURE.md (219 lines, 536fd98 + 9bb4326, pushed); key: S12B "knot" collides with the standard term (rename to blocking chain in README (p)), S12A faulted should be CRITICAL/FATAL only, passive gap map not found (active probes exist), MoRoOp single-AMR log only

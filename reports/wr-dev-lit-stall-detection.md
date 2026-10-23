# wr-dev-lit-stall-detection: academic literature check for the fleet stall analyser (2026-10-18)

Unattended docs job. Started 19:23 CEST, first commit pushed 19:40, review-fix commit pushed about 19:50 CEST (under 30 min of the 100 min budget).

## Deliverable

- `docs/LITERATURE.md` on master: commit **1f11586** (first version), then **afa7b2b** (review fixes), both pushed.
  After the second push, `git rev-parse HEAD origin/master` gave afa7b2b for both.
- What afa7b2b fixed:
  - The closing no longer lists "persistence grade on lessons" as not found, because hot_cell lesson_persist is
    Hunt's 2016 hotspot stability measure. That earlier wording was the flattering direction, caught on review.
  - Claims that rest on titles only (Cho 1995, Wu & Zhou, Fanti) and on a search snippet (Canadian Traveller) are
    now marked as such.
  - Hunt 2016 has a table row, verified on the OJP library page (NCJ 250376).
  - Read-depth column renamed; the real Roberts & Lean title is used.
  - A contradiction-sweep section was added.
- Contents: five questions, each answered in at most 8 sentences, and a closing section of 9 sentences. Sentence
  counts came from a regex counter over each section (8 / 7 / 6 / 8 / 8 / 9).
- A table of 56 sources with venue, URL and read depth (A full text / A- abstract or record / M metadata only), all
  verified@2026-10-18.
- An "Absence claims" section listing the queries behind every "not found".
- Only that one path was staged. The untracked `results/closed_loop*` files were left alone.

## Method

- Five research subagents ran in parallel, one per question, using WebSearch and WebFetch only. No browser was used.
- Provenance rule: a paper enters the table only if its record or text was fetched this session.
- In the main session I resolved 7 DOIs on Crossref that the subagents had not returned: Tarapore 2017,
  Roberts & Lean 2008, Gilleland 2009, Papadimitriou 1991, Stentz 1994, Koenig & Smirnov 1997 and Malka 2024.
- I checked these code facts against the source:
  - The costmap score is a decayed sum, `fleet/fleet_analyser/hotspot.py:148-163`.
  - Defaults: 1 h window and 1 h half-life, from `fleet/costmap.py`.
  - The rank-grade definition, from the `fleet/fleet_analyser/forecast_grade.py` docstring.
  - Blocked cells and outages are planner obstacles, `src/warehouse_rl/disturb.py:462-465`.
  - The README numbers I cite: S10 detection 5-14%, S8 lift 2.99.

## Findings

1. **Detection.** A no-progress threshold (ROS 2 Nav2 default: 0.5 m in 10 s) or a wait-for graph cycle search is
   standard. Ground truth is nearly always injected faults. Our 30 s rule scored against simulator truth is normal
   practice.
2. **Hotspot map.**
   - Our decayed count is the prospective-hotspot family. It equals Mohler's ETAS with the background rate μ = 0 and
     a fixed decay.
   - That is the standard baseline, and ETAS beats it (Mohler et al. 2011).
   - recall@K is the hit rate, counted in cells.
   - precision@K over chance has PAI's form, so at fixed K precision and recall are one result.
   - Our chance line over all 380 cells is the lenient null; Adepeju et al. 2016 reject it.
3. **Grading against chance is not new.** Crime PAI, meteorology ETS and earthquake Molchan diagrams all do it, and
   our lift has the form of the ETS hits-by-chance term.
   - Not found: our per-lesson, pool-conditioned chance rate.
   - The verification literature says persistence, not chance, is the reference to beat. Our lessons are persistence
     forecasts.
4. **Time to detect.** The standard frame is change-point detection with an AMOC trade-off (delay against false alarms
   per hour). Three things are missing on our side:
   - an undisturbed baseline run
   - misses counted in the delay
   - a sweep over K or a threshold

   Non-reset false flags have metrics in Fraker et al. 2008.
5. **Planner-blind floor.** It is the freespace assumption (Koenig & Smirnov 1997) combined with MAPF delay
   probabilities (Ma, Kumar & Koenig 2017), with the probability indexed by cell and unknown. The closest
   analyser-to-planner loop is MAGIC, an arXiv preprint from 2026.

Direction test: the errors do not point the flattering way. The main findings cut against us. "Graded forecasts" is
not novel, chance is the weak reference, and the map is the weak end of its own field.

## Problems and deviations

- **Semantic Scholar was not searched.** The API returned HTTP 429 to every call in all five passes, through both
  WebFetch and curl. Google Scholar was not attempted, and DBLP was behind a bot wall. The brief asked for Google
  Scholar or Semantic Scholar queries; what ran instead was Crossref, the arXiv API, OpenAlex and WebSearch, and the
  doc says so in its first section. Every absence claim is therefore weaker than the brief intended. The doc asks for a
  Semantic Scholar rerun before any absence is used in a pitch.
- **Email rule breach by one subagent (Q2).** One Crossref request carried the user's email address in its User-Agent
  header. That is Crossref's "polite pool" convention, but it breaks the rule against sending the email to an
  unrelated service. It happened once and was not repeated. Nothing else was sent.
- **Second-hand items.** Some content claims rest on second-hand or summarised text, and the doc marks them:
  - The JWGFVR and SCEC quotes came through the fetch summariser.
  - The AMOC definition is taken via Jiang et al. 2009.
  - Hunt 2016 is known only via the NIJ posting.
- **Kept out as unverified.** The RRI formula, the difference between PEI and PEI\*, and Lorden's delay formula.
- **2026 arXiv items as fetched.** Bonetti et al. 2026 (IJRR, arXiv 2609.10400) and Parimi et al. 2026 (arXiv
  2609.40269) were taken as the subagents fetched them. I did not re-fetch them in the main session.
- **Report location.** The brief said `reports/`. warehouse-rl has no `reports/` directory, so this report sits with
  the other `wr-dev-*` reports in `laptop-scheduler/reports/`. It is not committed to warehouse-rl.

## Query log (condensed from the five passes)

**Q1 detection.**
- Semantic Scholar: 6 requests, all 429.
- arXiv:
  - `all:AGV AND all:deadlock AND all:detection` (1 result)
  - `abs:anomaly AND abs:detection AND abs:multi-robot` (38)
  - `abs:robot AND abs:telemetry AND abs:anomaly` (3, none relevant)
  - `abs:swarm AND abs:fault AND abs:detection` (19)
  - `abs:deadlock AND abs:detection AND abs:robots` (13)
  - `abs:deadlock AND abs:lifelong AND abs:warehouse` (1)
  - `abs:"anomaly detection" AND abs:warehouse AND abs:robots` (2)
- Crossref:
  - "deadlock detection automated guided vehicles"
  - "deadlock avoidance AGV Petri net"
  - "wait-for graph deadlock detection AGV"
  - "anomaly detection automated guided vehicle data"
  - "fault detection multi-robot system telemetry"
  - "anomaly detection ROS robot logs"
  - "deadlock detection multi-agent path finding execution"
  - "stuck robot detection warehouse fleet"
  - "LSTM autoencoder anomaly detection mobile robot"
  - "isolation forest anomaly detection mobile robot"
  - "hidden Markov model fault detection mobile robot execution monitoring"
  - ALFA dataset
  - "anomaly detection AGV operational data industrial logistics machine learning"
  - "deadlock detection multi-robot system graph cycle"
  - "blocked robot detection multi-robot traffic jam detection"
- About 18 DOI records fetched. Full texts read: Bonetti 2026, Khalastchi 2015, Tarapore 2017 (PMC), Benecki 2024,
  Nav2 source.

**Q2 hotspot forecasting.**
- Semantic Scholar: 3 requests plus retries, all 429.
- Crossref: Chainey "utility hotspot mapping", Mohler "self-exciting", "randomized predictive policing", Bowers
  "prospective hot-spotting" (failed 3 times), Adepeju "novel evaluation metrics", "Hunt PEI NIJ" (failed),
  "exponential decay kernel density crime hotspot baseline", "learning to rank spatio-temporal event hotspots".
- WebSearch: PEI Hunt NIJ definition; Chainey PAI UCL; Mohler 2011 and 2015 PDFs; Adepeju PDF; "exponentially
  weighted / exponential smoothing baseline PAI self-exciting"; "Recapture Rate Index Levine definition".
- Full texts read: Chainey (UCL preprint), Mohler 2011 and 2015 (Wayback copies of the author PDFs), Adepeju (UCL),
  Flaxman (arXiv), NIJ posting.

**Q3 grading against chance.**
- Semantic Scholar: 4 requests, all 429.
- arXiv: `abs:"persistence baseline" AND abs:hotspot` (0 results), `hotspot AND crime AND baseline AND previous`
  (1, unrelated).
- WebSearch: Weisburd 2004; "predictive accuracy index" Chainey; "recapture rate index" Levine; Gilbert skill score
  hits by chance; PAI "hit rate" "area percentage"; Zechar Jordan Molchan; RI definition; Gorr Lee 2015; CrimeStat
  RRI; "hot spot persistence 'expected by chance' micro-place" (no chance-baseline persistence test found); malaria
  hotspot stability.
- Crossref: 10 DOIs resolved.
- Full texts read: Hu 2018 (arXiv 2006.00272), Joshi 2020 (arXiv 2006.08008).

**Q4 time to detect.**
- Semantic Scholar: 12 requests, all 429.
- Crossref: two batches (Fawcett & Provost, Kulldorff 2001, Page, Lorden, Lucas, Buckeridge, Moustakides, Frisén,
  Kleinman & Abrams, Fraker et al., Neill 2005, Kulldorff 2005, Pollak, Stoto, Woodall).
- OpenAlex: abstracts for 14 DOIs (11 returned).
- WebSearch: AMOC "activity monitoring operating characteristic"; Fawcett & Provost PDF (not found).
- Full text read: Jiang, Cooper & Neill 2009 (author PDF).
- ACM DL returned 403.

**Q5 MAPF under unknown obstacles.**
- Semantic Scholar: 5 requests, all 429. DBLP: 3 queries, bot wall.
- arXiv: `ti:"warehouse logistics" AND ti:"co-workers"`, `ti:"delay probabilities"`,
  `ti:"robust multi-agent path finding"`, `ti:"persistent and robust execution"` (0 results),
  `ti:"lifelong MAPF in large-scale warehouses"`, `ti:"guidance graph optimization"`,
  `ti:"multi-agent path finding" AND ti:uncertainty` (found MAGIC).
- WebSearch: D* Lite freespace; MAPF-OU Shofer ICAPS 2023; Malka IROS 2024; Papadimitriou & Yannakakis 1991; Hönig
  RA-L 2019; Atzmon JAIR 2020; Stentz ICRA 1994; Koenig & Smirnov ICRA 1997.
- Full texts read: Ma, Kumar & Koenig 2017 (arXiv PDF), D* Lite (PDF), Shofer 2023 (PDF).

**Main session.** Crossref record lookups for the 7 DOIs listed under Method.

## Operator items

- **Contradiction sweep.** `docs/overview/index.html:152` reads "trend tools exist, this one grades its own calls".
  It is scoped to products, so it is fine against COMPETITION.md. Read as a general claim, though, it is not new in
  the academic literature (LITERATURE.md section 3). Rewording it is the operator's call; it was not edited.

- Whether to queue the next analyser comparison (an ETAS-style per-cell model), or first the two cheap changes: an
  ever-stalled chance pool and a persistence reference.
- Whether an undisturbed hotspot run should be queued so time to detect can be reported as an AMOC curve.
- A Semantic Scholar rerun of the absence queries before any of them fronts a pitch.

SCHED_RESULT: OK docs/LITERATURE.md committed 1f11586 + afa7b2b and pushed; Semantic Scholar rate-limited (429) in every pass, so absences rest on Crossref/arXiv/OpenAlex/WebSearch only

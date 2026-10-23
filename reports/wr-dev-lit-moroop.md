# wr-dev-lit-moroop: literature check before S13A (2026-10-20)

Deliverable: `warehouse-rl/docs/LITERATURE.md` "Part 2b: MoRoOp and single-robot operation logs", commits 9479b87 and
5749cba, both pushed to origin/master. It is 120 lines, the cap. Brief edited: `jobs/wr-lane-s13a-moroop-budget.md`. That file is
untracked in laptop-scheduler and was not committed.

All fetches ran on 2026-10-20 by the local clock (the brief assumed the 21st), so every claim carries `verified@2026-10-20`.
No parquet file was downloaded.

## Query log

| # | tool | query / URL | result |
|---|---|---|---|
| 1 | curl | huggingface.co/datasets/Self-Organizing-Production-Logistics/MoRoOp/raw/main/README.md | card, 7,833 B. `license: cc-by-4.0`, "current release (1.0.0)", table list, no column dictionary |
| 2 | curl | huggingface.co/api/datasets/.../tree/main?recursive=true | 46 parquet + kits + jpg, 26.8 MB total |
| 3 | curl | datasets-server.huggingface.co/info?dataset=... | column names + dtypes, rows per split, all 5 configs. **Beyond "card and file listing"; metadata only** |
| 4 | curl | datasets-server /statistics, 5 configs x 9 splits | value counts (stuck_reason, state, operating_mode, outcome, event_type), min/max, nulls. Computed by HF, ranked A- |
| 5 | curl | datasets-server /first-rows, 4 configs, 2026_07_27_morning | 81-100 sample rows, used for cadence and diagnostics shape |
| 6 | WebFetch | arxiv.org/abs/2610.02428 | title, authors, submitted 1 Oct 2026, CC BY 4.0, "Submitted to Nature Scientific Data" |
| 7 | curl | arxiv.org/html/2610.02428v1 | full text incl. math alttext: Tables 1, 3-7, 1 Hz polling, position-id mapping, exclusions |
| 8 | gh api | search/code?q=MoRoOp (3 pages); search/repositories?q=moroop; search/code?q=Self-Organizing-Production-Logistics | toolkit JaFeKl/moroop-dataset-toolkit; third party CrazyEther/robotization-agent-lab (state transitions only); rest name collisions |
| 9 | gh api | toolkit data.py, figures.py, walkthrough notebook | units from axis labels (m, m/s, %); `_segments` time split; HF revision tag 1.0.1 |
| 10 | gh api | CrazyEther .../derive_moroop_transitions.py | (state, is_robot_charging) transitions, one shift; no budget or stuck analysis |
| 11 | curl | api.semanticscholar.org paper/arXiv:2610.02428 | citationCount 0 |
| 12 | curl | api.semanticscholar.org paper/search?query=MoRoOp (x2), a topical search (x1) | **429 all three times**, coverage gap |
| 13 | curl | scholar.google.com/scholar?q="MoRoOp" | 1 result (the paper), no "Cited by" |
| 14 | curl | api.openalex.org/works?search=MoRoOp | paper, HF record, toolkit Zenodo: 0 citations each |
| 15 | curl | huggingface.co/api/models?filter=dataset:...; api/spaces?search=moroop | [] and [] |
| 16 | WebSearch | wheel.me API robot state "stuck" "ObstacleInTheWay" OR "GoalObstructed" | no wheel.me docs; enum meaning undocumented |
| 17 | WebSearch (ext) | hospital delivery robot TUG log analysis time spent waiting stuck share of trips | no TUG log analysis; found Lee et al. 2026 (Digital Health) |
| 18 | WebSearch (ext) | AMR case study operational log utilization idle time share navigation failures field deployment months | STRANDS, MOSAIC (idle share is a labelling artefact, multi-robot, not used), others |
| 19 | WebSearch | Klein Jeong MoRoOp dataset autonomous mobile robot operations cited | nothing |
| 20 | WebSearch (ext) | single mobile robot long-term deployment log analysis time spent blocked OR stuck OR waiting percentage | STRANDS; Gerling et al. 2016 care-home robot |
| 21 | WebSearch | MiR autonomous mobile robot case study utilization percentage hours logs intralogistics paper | vendor case pages only, no utilisation figure |
| 22 | WebFetch | pmc.ncbi.nlm.nih.gov PMC13039597 | reCAPTCHA, so fetched via Europe PMC fullTextXML instead (A) |
| 23 | WebFetch | nature.com s41598-026-49800-9; link.springer.com 978-3-032-05435-7_18 | login redirect, not read, not used |
| 24 | curl | arxiv.org/pdf/1604.04384 (pdftotext) | STRANDS Table 1: TSL, A% |
| 25 | curl | Europe PMC PMC4899482 fullTextXML | Gerling et al. 2016 stuck wording |
| 26 | curl | zenodo.org/api/records/23393677 | Sharma 2026 record description |
| 27 | curl | raw.githubusercontent.com/VDA5050/VDA5050/main/VDA5050_EN.md | §3.3 Driving = "non zero translational and/or rotational velocity" |

## Findings that change the S13A brief

1. **`stuck_reason` exists.** Values are `None`, `ObstacleInTheWay` and `GoalObstructed`, with 207 labelled cleaned rows
   across the 9 shifts (37 3 52 20 3 17 48 17 10). The value meanings are undocumented.
2. **140,386 is the raw state-row total.** Cleaned is 137,427. There are no "delays" or "failed navigation" tables. The
   failures are 8 TIMEOUT operations (~300 s), equal to the 8 failed jobs.
3. **The parser takes whole-second timestamps only**, while MoRoOp is sub-second (median interval 0.91 s), so the
   adapter must floor and collapse rows.
4. **`--stations auto` would build TA-RWARE layouts.** Stations must come from the position ids 135-138.
5. **The waiting_station share is generator-set** and must not be reported as a finding.

## Changed after the first commit (5749cba)

These came out of a review pass. They are mirrored in the brief's tasks 2, 3 and 5.
- **orderId:** now the `job_id` of the running *operation*, with the gaps between operations of one job filled. Overlap
  seconds are reported instead of asserted: operations carry priority 0-2, and the charging operations were not in the
  sampled rows. The first 100 jobs and operations show 0 overlaps and 0 interleaving. Jobs are counted as unique
  orderIds, not as orderId changes.
- **Stations:** every cell with >= 5 % of the Idle rows at an id, not one median cell. A 3-box kitting dwell averages
  ~30.7 s, so docking jitter would otherwise create stuck false alarms.
- **errors:** `[]` in S13A. The diagnostics level vocabulary is unknown, so the level mapping is F and not used.

## Deviations from the brief

- Besides tasks 2 and 4 (as asked), I also rewrote task 3 (stations: the auto fallback is invalid) and task 5 (the
  sanity numbers from Part 2b §1). The required line "Mapping rules from docs/LITERATURE.md Part 2b, do not deviate
  without saying so in the report." is its own line in task 2.
- The brief's "Read first" paragraph still says "140,386 state rows" and "failed navigation". I left it untouched under
  "keep everything else"; task 2 states the correction.
- Section 3's table has 4 rows. A published single-robot time-in-state share was not found (queries 17, 18, 20, 21).

SCHED_RESULT: OK lit-moroop Part 2b committed 9479b87+5749cba (120 lines, pushed); S13A brief tasks 2-5 rewritten

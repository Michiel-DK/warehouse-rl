# wr-dev-lit-s16: LITERATURE Part 9 (ROS diagnostics, dispatcher events, the authors' cleaning), 2026-10-23

Unattended docs job, opus. Outputs:
- `docs/LITERATURE.md` Part 9 (114 lines; commit 682bdd0, then a review-fix commit), plus an inline correction note on the Part 2b §4 `errors` row.
- The S16A and S16B lane briefs, rewritten in place in `<local>/laptop-scheduler/jobs/`. They are **not
  committed there**: this job commits only to warehouse-rl, as the S15 lit job did.
- No code, no parquet read, no simulator run. README is not edited; the correction sentence for README (r) is in
  Part 9 §1 for the next docs pass.

## Verdicts in one line each

1. **Vocabulary:** the levels are the ROS `diagnostic_msgs` set. That is rank **B**, inferred from four things: the
   field names, the four level words, aggregator-style names, and the byte-identical stock FrequencyStatus string. The
   ROS definitions themselves are rank A. wheel.me's docs are behind a partner login, so their definition is UNTESTED.
   **No level maps to faulted at rank A.** REP 107 says diagnostics are "not going to halt the system in any way", and
   ROS ERROR describes a component, not the robot. Error (outside the noise list) -> faulted is **our rule, rank B**.
   Warning and Stale never count.
2. **Noise list:** one entry, `/Devices/Camera` "Frequency too high." at Warning (ROS diagnostic_updater FrequencyStatus).
   Every other family is **unclassified**: SSD, lidar, mecanum and navigation. The SSD and navigation texts describe
   themselves, but a message's own text is not documentation.
3. **Dispatcher (code at 35dbb76):**
   - start_denied means the lab application's callback refused a start.
   - A pause is either an API/app call, an automatic pause after 5 denials, or `start_paused`.
   - A resume is an API/app call only.
   - Our classes: "dispatcher refused" (denials and auto-pauses); "external call" (other pauses, all resumes; called
     "intervention" only when within ±120 s of a stuck episode); neither (started, stopped, failed).
   - "Human" is never claimed.
4. **Cleaning:** the only definition is the paper's sentence; there are no thresholds and no code in the toolkit. Our
   adapter reads the cleaned table, so "no row rejected" holds only for the authors' table after their 2,959 removals.
   S16B must run our path on raw and keep collapse drops apart from rule drops.
5. **Refute thresholds** are set numerically in Part 9 §5.

## Review fixes (second commit)

An advisor review of 682bdd0 found four problems; all are fixed.
1. The S16A rewrite put every Warning and Stale status into `errors` as "WARNING". That is wrong:
   `fleet/fleet_analyser/score.py:41` sets `frozen = bool(obj["errors"])`, checked this session with grep. Now only
   Error statuses outside the noise list enter, as "FATAL"; the other levels are read from the raw column.
   Tests (b), (c) and (e) assert `errors == []`. Part 9 §2 now says the one-entry noise list removes nothing from the
   faulted bucket.
2. In S16B, a resume before the shift's first `operation_started` is now class "shift start", never "intervention".
3. The claim that 35dbb76 is the recorded version is now marked rank B, a date inference, in Part 9 §3 and in the
   S16B Why line.
4. The gurren-page note below was added.

## Query and fetch log (all 2026-10-23)

| # | what | result |
|---|---|---|
| 1 | curl raw `ros/common_msgs` noetic-devel and `ros2/common_interfaces` rolling `DiagnosticStatus.msg` | both: OK=0 WARN=1 ERROR=2 STALE=3; fields level/name/message/hardware_id/values |
| 2 | curl https://ros.org/reps/rep-0107.html | level definitions; "not going to halt the system in any way" |
| 3 | curl `ros/diagnostics` ros2 (sha 81b53fa) `diagnostic_aggregator/README.md`, `diagnostic_updater` `update_functions.hpp`, `_update_functions.py` | Other analyzer items "go stale after 5 seconds"; FrequencyStatus: "No events recorded." ERROR (py L120), "Frequency too low." / "Frequency too high." WARN (py L123/L127; hpp L195/L197) |
| 4 | GitHub API: JaFeKl/OperationDispatcher tree, commits, compare 35dbb76...0609fa7 | 35dbb76 = 2026-07-22, last code commit before recording; only README.md differs to HEAD (README edit 2026-10-15) |
| 5 | curl the dispatcher sources (`models.py`, `request_handler.py`, `retry_policy.py`, `services/runtime_service.py`, `services/operation_lifecycle_service.py`, `runtime_controller.py`, `operation_dispatcher.py`, README) | event enum values; auto-pause at `max_retries_reached`; `start_request_max_retries: int = 5`; resume via API only; README "Neither runtime pause nor a state change automatically stops a physical resource" |
| 6 | curl https://arxiv.org/html/2610.02428v1, text search | cleaning = "invalid localization states or physically implausible values", "restricted to technical validity"; 0 hits for paus / resum / manual / interven / deni / approv |
| 7 | GitHub API + raw: JaFeKl/moroop-dataset-toolkit (sha 2529c9d) `data.py`, `figures.py`, README | no cleaning or diagnostics code; loads `robot_state_cleaned` |
| 8 | WebSearch "wheel.me RGo robot diagnostics API documentation" | no vendor doc; only a third-party Peakboard extension page (positions, robots) |
| 9 | WebSearch for the exact strings "RGo will stop at 90%" / "Mecanum: RPM feedback mismatch" / "Lidar: Waiting for scans" | 0 pages with any of them |
| 10 | curl wheel.me: sitemap.xml 404; docs., developer., support., help., api. subdomains: no response; /en-us footer links; /faqs; partner.wheel.me | footer: no docs or support tree; /faqs: no technical content; partner portal "Product Documents ... technical documentation" behind a login (`/products/` returns the login form); WP search API "diagnostic", "error": only "What's new?" page title -> **UNTESTED** |
| 11 | OpenAlex search "MoRoOp" | dataset (W7211872143), paper (W7220748450), toolkit; all cited_by_count 0 |
| 12 | OpenAlex "ROS diagnostics fault label mobile robot log" | 217 full-text hits, none read; **no absence claim made** from it |
| 13 | CORE API v3 `title:(MoRoOp)`; `ROS AND diagnostics AND "mobile robot" AND fault AND log` | 0 and 0; CORE holds no MoRoOp record, so its zeros are uninformative (Part 7 rule) |

## What changed in the briefs

**S16A (`jobs/wr-lane-s16a-moroop-faults.md`).**
- *Why:* now says the levels are the ROS set at rank B, and that Error -> faulted is our rule.
- *Task 1:* the mapping is explicit. Only Error statuses outside the noise list enter `errors`, as "FATAL";
  everything else stays out (score.py:41). The noise list is one (name, message, level) triple.
- *Table (a):* adds the driving share per family (> 50 % refutes "ERROR = stopped") and the faulted ∩ paused seconds
  per family.
- *Table (b):* paused wins over faulted in this table only. The §5 verdict is computed, with the n = 2 caveat.
- *Table (c):* the classes are noise / faulted-by-rule / unclassified, plus uptime at first onset. The public label is
  "Robot reported a component error", and the detector's faulted_self wording is not to be quoted.
- *Task 3:* SCHED_RESULT carries the verdict word.
- *Tests:* two cases added, camera "Frequency too high." at Error (d) and an unclassified Warning (e); Stale (c) is now
  pinned as not faulted.
- *Kept:* file names, result paths, the suffix `sf` and the declared files.

**S16B (`jobs/wr-lane-s16b-moroop-dispatch.md`).**
- *Why:* now carries the dispatcher semantics from code 35dbb76 ("human" never claimed), and says the cleaning happens
  before our parser.
- *(a):* event kinds listed; meta_data fields; the three classes with the auto-pause rule; "intervention" defined; each
  resume's offset from shift start and preceding pause (11 vs 3 reported, not explained).
- *(c):* our path runs on **raw** (import, do not edit the adapter, or prove the `-sb` output byte-identical). Rule
  drops and collapse drops are kept apart. Authors-only pose and velocity ranges are reported. Both §5 verdicts are
  computed. The page sentence is given with its N, M, P fields.
- *Task 2:* SCHED_RESULT carries both verdicts.
- *Tests:* an auto-pause case and a collapse case added.
- *Kept:* file names, result paths, declared files.
- **Chokepoint:** both lanes may touch `fleet/adapters/moroop.py`. S16B is told not to edit it; if it must, it runs
  after S16A merges.

## Not done / open for the operator

- The wheel.me partner portal (login) is the only possible rank-A source for the level vocabulary and the message
  families. A partner account would settle §1-§2.
- README (r) still says "undocumented". Part 9 §1 has the correction sentence for the S16 docs pass.
- The gurren page's "no row rejected" line (roger3000 drafts, uncommitted there) must take the Part 9 §4 sentence
  once S16B has N, M and P.
- No push. `origin/master..master` already held the 7 public-prep commits, and this commit joins them locally.

SCHED_RESULT: OK Part 9 appended (114 lines) + Part 2b note + review fixes; S16A/S16B briefs rewritten in laptop-scheduler (uncommitted there); levels = ROS set (B), Error->faulted is our rule (B), noise list 1 entry, wheel.me docs UNTESTED

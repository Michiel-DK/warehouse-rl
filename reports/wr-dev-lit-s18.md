# wr-dev-lit-s18: LITERATURE Part 10 (keeping less of a fleet log without losing the answers), 2026-10-30

Unattended docs job, opus. Outputs:
- `docs/LITERATURE.md` Part 10 (112 lines after the review-fix pass, under the 120 limit).
- The S18A lane brief `~/code/Michiel-DK/laptop-scheduler/jobs/wr-lane-s18a-keep-what-matters.md`, rewritten in place.
  Its DRAFT header is gone, so the lane's own self-fail check no longer fires. The brief is **not committed** in
  laptop-scheduler: this job commits only to warehouse-rl, as the S15 and S16 lit jobs did.
- No code, no log read, no run. README is not edited. No ratio was measured; every number below is someone else's
  and carries its source.

## Verdicts in one line each

1. **Name:** "report by exception (change-only) with a maximum interval", with zero deadband because every field the
   analyser reads is discrete. Not deadband, swinging door or LTTB: those approximate continuous signals or plots, and
   the analyser reads a step function. gzip is the baseline, so the word "compression" stays out.
2. **Reference ratio:** report gzip(full) / gzip(reduced), kept lines per robot-hour against the emitted rate, and the
   3:1 floor (AVEVA's "suggested minimum compression ratio", a vendor rule of thumb, rank D). The published downstream
   tests (EDBT 2024, Hollmig 2017) measure *degradation* at a tolerance. An "every output identical" test was not found
   in one index plus a partial second, which falls short of the Part 7 bar, so it is not a pitch claim.
3. **Vendors:** Formant and InOrbit document volume knobs: rate throttling, store-on-device, and choosing what to
   store. Neither doc tree has a check that answers stay the same (verified@2026-10-30). "Keep less" is not new;
   "keep less and prove each answer unchanged" was not found in their docs.
4. **Keep rules:** R0 `all`; R1 `change` (Message projection, plus first and last line); R2 `+gap` (never create an
   interval longer than H, with H = 60 and 30); R3 `+threshold` (the line at since + stuck_after and since + servicing
   bound); R4 `+neighbours` (the whole zone batch at T_entry, because `_cause` reads only the same-ts batch); R5
   `+recovered`. Ledger sequence gaps and bytes are out of "identical" by construction.
5. **Refute:** the full stream is needed if no rung up to R5 is identical on s10-none and MoRoOp -sf. Below R = 3 the
   pitch is not worth making. A VDA 5050 fleet already sends `state` change-only with a 30 s heartbeat, so the
   simulator's every-step ratio overstates that fleet's gain.

## What the code says (rank A, read this session)

- `fleet/fleet_analyser/detector.py` L181-210: `_process_batch` decides cause after the whole (zone, ts) batch. L287:
  `others` = robots **in that batch** within Manhattan 1. A change-only log drops stationary neighbours from the batch,
  so the cause falls to `unknown`. That is R4.
- `detector.py` L212-273 `_step` and `fleet/timebudget.py` L166 `run_is_stuck` (last line of the run minus the first)
  test the threshold only on lines that exist. A stop reduced to its first and ending line never becomes an episode.
  That is R3.
- `timebudget.py` L203: an interval longer than `max_gap_s` (60) goes wholly to `no_data`. Dropping lines inside a
  long stop would create no_data, which is the README (q) effect. That is R2.
- `timebudget.py` L246 `stop_minutes` and `hotspot.py` L65 compare consecutive lines. They stay exact under R1, because
  a dropped line equals the kept line before it in every field they read.
- `parse.py` L21-40: `Message` = serial, zone, header_id, ts, order_id, x, y, driving, faulted, loaded, raw_len, theta,
  next_x, next_y, nodes_reported, paused. `theta` is read by hotspot.py, so it is in the R1 projection.

## Query log

Fetched with curl, except where WebFetch is noted. All dated 2026-10-30.

| what | where | status | used for |
|---|---|---|---|
| VDA 5050 2.1.0 and 3.0.0 text | raw.githubusercontent.com/VDA5050/VDA5050/{2.1.0,main,3.0.0}/VDA5050_EN.md (tag 2.1.0 511d01d; main 0b2ae43 read first; tag 3.0.0 e9ba560 fetched after and checked: same 30 s sentence (L1028), same 16 triggers, `minimumStateInterval` present; the files differ elsewhere) | 200, read §6.10 (2.1.0) and §6.6 (3.0.0), topic tables | §1 |
| Sparkplug RBE | eclipse-sparkplug/sparkplug master e45b610, Sparkplug_2_Principles.adoc | 200, read | §1 |
| AVEVA PI deck (Bregenzer 2023) | cdn.osisoft.com …UC23NA-3PGK04…pdf | 200, pdftotext, read | §1, §2 |
| AVEVA docs pages | docs.aveva.com/bundle/pi-server-s-da-admin/page/1021696.html | JS shell, no text | UNTESTED |
| Swinging door patent | patents.google.com/patent/US4669097A/en | 200, record metadata | §1 |
| Åström & Bernhardsson 2002 | OpenAlex W1685524015 | abstract | §1 |
| LTTB thesis | WebSearch only (skemman 1946/15343 via package docs) | not opened | §1, content F |
| rosbag / rosbag2 | ros_comm noetic-devel 30483a9 rosbag_main.py; rosbag2 rolling 737e0fa README | 200, read | §1 |
| wiki.ros.org rosbag/Commandline | WebFetch | Anubis wall | replaced by source |
| Muñiz-Cuza et al. EDBT 2024 | OpenAlex W4412220054 | abstract read | §2 |
| Hollmig et al. 2017 | OpenAlex W2555140555 (no abstract), dbis.ipd.kit.edu/english/722_2434.php | abstract read via WebFetch summary | §2 |
| Thornhill et al. 2004 | OpenAlex W2143579868, Crossref (no abstract), CORE 33256137 (abstract field holds a repository note, not the abstract); PDF core.ac.uk/download/76991136.pdf HTTP 403 | metadata only; content from a WebSearch summary (C) | §2 |
| Formant | docs.formant.io/llms.txt (502 lines; "retention" 0 hits) + configure-stream-rate, how-telemetry-streams-work, on-demand-streams, faq-reduce-bandwidth…, managing-datapoint-throttling (.md) | 200, read | §3 |
| InOrbit | developer.inorbit.ai/sitemap.xml (9 URLs, shallow); developer.inorbit.ai/docs (single page, ~168k chars of text; "retention" 0, "Adaptive sampling" 1, `timeline` field) | 200, read | §3 |
| InOrbit WebSearch "data retention / publish rate / throttling" | — | only PyPI inorbit-edge | nothing used |

**Scholarly absence (§2 "answers identical"; robot-log reduction).** OpenAlex `title_and_abstract.search` returned 0 to
16 hits per query and nothing on topic: "robot log compression analysis" (16; one 2018 dissertation, "Compression of
sensor data in robotic systems", hdl 10773/25969, title only), "AGV telemetry compression" (0 on topic), "mobile robot
logging data reduction" (8), "rosbag compression" (1, a dataset), "fleet telemetry downsampling" (1, SCADA preprint),
"robot event-based logging" (404, none on volume), "robot swinging door" (8, doors), "AGV log compression" (1,
off-topic), "AMR telemetry reduction" (3), "warehouse robot logs storage reduction" (0), "lossy compression anomaly
detection time series" (4: degradation studies, none on exact identity), "report by exception telemetry" (95,
off-topic). CORE API v3: `title:robot AND title:log AND abstract:compression` = 0, `abstract:AGV AND
abstract:telemetry AND abstract:compression` = 0. Calibration: CORE retrieved Thornhill 2004 (the known historian
compression paper) and missed Hollmig 2017 (0 hits on a title phrase). Five further CORE queries were rate limited
(HTTP 429, three tries each, 20 s back-off): "mobile robot" + logging + "data reduction", rosbag + compression, fleet +
telemetry + downsampling, robot + "swinging door", "lossy compression" + "anomaly detection" + "time series". By the
Part 7 rule this is **one index plus a partial second**, so the absence is not pitch-grade.

## Brief diff (wr-lane-s18a-keep-what-matters.md)

- The DRAFT header was replaced by a "Rewritten 30 Oct" header listing what changed.
- Name added (report by exception, change-only, max interval).
- Build 1: kept lines are written byte for byte, headerId is never renumbered, `custom` is never read, gzip mtime is 0.
  The summary adds `ratio_gzip` and kept lines per robot-hour. `--rules` is now the cumulative ladder R0-R5
  (`all`, `change`, `gap`, `threshold`, `neighbours`, `recovered`), plus `--heartbeat-s` (60 and 30) and
  `--servicing-max-s` fixed from the full run. The detector runs inside the reducer from R3 on.
- Build 2: the transitions table, blocker and resolution are added to the compared outputs, and S15A rows where they
  apply. Ledger gaps and bytes are reported apart, not in "identical". `first_identical_rule` is added. No tolerance.
- Build 3: kept the draft's identity, dropped-transition, gap and determinism tests. Added one fixture per rung R3-R5
  (identical at that rung, not below), a test that R2 creates no new interval longer than H, and a garbage-`custom`
  invariance test.
- The refute line is written into the brief before the run.
- "Do not" adds editing `fleet/fleet_analyser/`, and the lane report must name all three references next to the ratio.
- Unchanged: file names (`fleet/reduce.py`, `fleet/reduce_check.py`, `fleet/tests/test_fleet_reduce.py`), result path
  `results/fleet/reduce_<run>.json`, proof runs (s10-none, moroop/jsonl-sf), the follow-on items `wr-s18a-run` and
  `wr-dev-s18-readme`.

## Rank per name (item 1 asked for rank A)

Report by exception: A (Sparkplug). VDA 5050: A. Bag filtering: A (source). Event-based sampling: A- (abstract).
Exception and swinging door: **D** (AVEVA's deck; the AVEVA docs are a JavaScript shell to our fetch, so UNTESTED) plus
the patent record. LTTB: **F** for content (the thesis was not opened). Neither D nor F name is the lane's name.

## Review-fix pass

After b6943f6 an advisor read added: the **mixed** outcome in the refute line, per run and per H; the 3:1 units
(events, not bytes; stricter on gzip; the line ratio is reported next to it); the MoRoOp label match by kept index
(the brief now says to compare by timestamp); the 3.0.0 tag check; and the InOrbit searched surface. Part 10 is now 112
lines.

## Open for the operator

- The 3:1 floor is a vendor's rule of thumb (rank D), not a buyer's number. If buyers named a size or cost target, that
  replaces it.
- R4 needs the detector inside the reducer. That makes the reducer analyser-specific: "keep what *this* analyser needs",
  not a general log policy. The page wording should say so.
- Formant's two pages disagree on the default stream rate (0.5 Hz vs 5 Hz). Noted only; nothing depends on it.

## Commits

b6943f6 (Part 10 + report) and the review-fix commit after it are on local `master`, **not pushed** (the job said
commit). A lane that squash-merges should rebase onto them knowingly (memory: S15B squash folded unpushed master commits).

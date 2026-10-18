"""Export ONE zone of a real fleet run as a static `window.REPLAY = {...};` file for the offline replay page (docs/replay/).

Usage: python fleet/replay_export.py --run-dir DIR --store jsonl:DIR/store --zone 0 --out docs/replay/data.js
       [--closed-loop results/closed_loop] [--benchmark results/fleet/benchmark.json]
       [--hotspot results/fleet/hotspot_<tag>.json] [--closed-loop-summary results/closed_loop_sticky/summary.json]
       [--lessons-long results/fleet/hotspot_s8e-long-w0.5.json]
       [--dose-response "p 0.3-0.7=results/closed_loop/summary.json" ...]   (repeatable, order kept)
       [--explorer]   (run_constants.explorer from the five closed-loop summaries and the density and breakdown sweeps)
       [--sticky-none PATH --sticky-map-a32 PATH --sticky-oracle-a32 PATH --sticky-undisturbed PATH]
DIR holds the zone files zone<Z>-<nnn>.jsonl.gz, truth.json, emit_ledger.json and costmap.json (the run name is
costmap.json["run"], as fleet/hotspot_score.py reads it). The store is only READ (every table through
store.select(table, {"run": run}); the raw .jsonl store files are never read and nothing is upserted). The export reuses
fleet_analyser.parse / hotspot / ledger and fleet/hotspot_score.py; it implements none of them again. The file is written
atomically (tmp + os.replace) and the writer raises, without writing, when it is larger than 2 MiB (2097152 bytes).

Payload (every key is always present unless marked optional):
  meta        run, zone (str), env_id, steps, step_seconds (5), t0_ts (epoch s of step 0), seed, disturb, policy, recovery,
              schema "replay/4", state_display {raw state: display state} = live_state.display_state over STATES (moving,
              working, waiting, down; the page draws this and falls back to waiting for a raw value missing from it), source {run_dir, store, closed_loop, costmap, demo_noise, injected_noise} = the
              paths exactly as given on the command line (never resolved to absolute paths); costmap = "<run_dir>/costmap.json"
              as given; demo_noise = the emit ledger's config.demo_noise (bool) and injected_noise its total.injected_noise
              (null without). Step s covers event time t0_ts + s * step_seconds.
  grid        {width, height, highway, goals, shelves}: shape is width (columns, x) by height (rows, y), the same (x, y)
              system as agvPosition. highway = height strings of width chars, "1" = highway cell, "0" = not;
              goals = [[x, y]]; shelves = [[x, y]] shelf positions right after the reset. Built from the vendored env of
              meta.env_id, reset with the zone's seed, read-only, in ONE fresh process (Agent.counter and Shelf.counter
              are class attributes: never two envs in one process). Every robot position of every layer must lie inside
              the grid or the export raises.
  robots      [{serial, kind}] sorted by serial; kind "agv" or "picker" (the first num_agvs agents are AGVs).
  frames      frames[step][robot_index] = [x, y, state, job] for every step and every robot (robots order). job is the
              order id of the message the entry came from ("" = none). A robot with no message at a step keeps its
              previous entry, job included (before its first message: its first position, "idle", "").
              A step with several messages of a robot uses the highest headerId. state is one of
              moving, loading, stalled, stuck, frozen, idle, derived by derive_state() with precedence
              frozen > stuck > stalled > loading > moving > idle:
                frozen  the message has errors (the robot is faulted; unrelated to the S3E "frozen blocker" vocabulary)
                stuck   the message ts lies in [start, end] of a detector stuck episode of that robot (end None = runs to
                        the stream end); left_censored rows and resolution "interrupted" rows are skipped, the rule of
                        hotspot.annotate_episodes
                stalled the ts lies in [start, end] of a stall of that robot (hotspot.extract_stalls)
                loading has an order, is not driving and reports nodeStates []
                moving  driving true
                idle    anything else
  obstacles   the zone's hidden floor problems from truth.json: [{kind "floor", cell "x,y", p, hidden_from_analyser true}]
              sorted by cell (truth.json of this emitter carries no breakdown or frozen windows, so none are emitted).
  extractor   {series, totals, check}. series: per step (steps entries each), CUMULATIVE and non-decreasing, in EVENT time
              (a parsed line counts at the step of its message ts; a rejected line at the step of the last parsed line
              before it, step 0 if none): bytes (uncompressed, len of the raw line), messages (lines), parsed, rejected,
              rejected_by_reason {reason: [..]}, duplicates, sequence_gaps, missing_messages, accepted, coverage
              (accepted / expected, null without an expected count). Duplicates and gaps are classified by
              ledger.SequenceTracker exactly as the ingester does (headerId <= last accepted = duplicate). totals: the
              series at the last step plus expected_messages and bytes_compressed (the emit ledger's total for the zone
              file(s); compressed bytes are not split per line, so there is no series for it). check: the ingest
              checkpoint counters of the zone's file(s) (messages_parsed, messages_rejected, duplicates, sequence_gaps,
              missing_messages, messages_accepted, bytes_read_uncompressed) plus coverage = messages_accepted /
              expected_messages (null without an expected count). The ingester's counters are cumulative over
              the run, so check is the difference to the previous checkpoint row by cp_seq, which is exact when the files
              are ingested one after another (a file is consumed before the next starts). The export raises when the
              replayed totals disagree with check; check is null when the store has no checkpoint for the file.
  publishes   every costmap publish of the zone in the store, ascending by t: {t, step, cells [[cell, cost (4 decimals),
              stalls]] sorted by (-cost, cell), precision_at_20, hits_at_20, n_flagged, recall_at_k, k}; precision comes
              from hotspot_score.precision_recall(zone map, floor cells, ks=(20, k)) on the unrounded costs, k = the number
              of floor obstacles of the zone and recall_at_k = the recall at k (hits in the top k / floor cells; null
              without floor cells).
  grades      {per_publish, timeline}. per_publish[i] belongs to publishes[i]: counts over the forecast_grades rows whose id
              joins to a decisions row of kind hotspot_forecast, subject prefix "Z<zone>:" and decided_at == t. Keys:
              t, forecasts, outcome {ok, off} (grade_source "outcome"), outcome_count {ok, off} (grade_source "outcome_count"),
              truth {hit, false_alarm} (grade_source "truth"), open (forecasts with no "outcome" row whose decision is
              still open), unranked (decisions stamped verdict "unranked"), outcome_kind, window_end (+ _step): the
              latest window_end of the publish's outcome rows, null without any (the time the outcome grades exist). The source names are kept.
              outcome_kind says what the "outcome" rows of that publish mean: "rank" when their decisions carry a v2 claim
              (top_k present: ok = the cell is still in the zone's top K at window_end), "count" for older v1 claims
              (the "outcome" row is then the expected-stall-count grade), null when the publish has no "outcome" row.
              The page must only call a rank grade "still in top 20 after the horizon" when outcome_kind is "rank".
              timeline: cumulative counts by event time [{t, step, outcome_ok, outcome_off, truth_hit, truth_false_alarm}],
              a grade at its window_end (truth rows, which have none, at the publish t).
  run_constants  {ingest_msgs_per_s, benchmark_msgs_per_s, kept, hotspot, closed_loop, audit, header, speed, lessons_long,
              worth, dose_response, explorer}: the numbers the page shows that
              are not per-step, each an object with a `source` (the path exactly as given, or a "store:..." name for
              store-derived ones) or null when its source is absent. The page types none of them.
                ingest_msgs_per_s  {value, source "store:ingest_ledger", formula}: over the run's ingest_ledger rows with a
                                   rate, sum(messages_parsed) / sum(messages_parsed / msgs_per_s) (one row: its msgs_per_s).
                benchmark_msgs_per_s  {value = batch.msgs_per_s of --benchmark, source}.
                kept               {kept_pct, bytes_kept, bytes_arrived, bytes_by_table, scope "run", n_zones, source,
                                   formula}. KEPT FORMULA: kept_pct = 100 * sum over T in (transitions, decisions,
                                   state_sample, rejects) of B(T) / sum(ingest_ledger.bytes_read_uncompressed), each table
                                   read as store.select(T, {"run": run}) and B(T) = sum over its rows of
                                   len(json.dumps(row, sort_keys=True, separators=(",", ":")).encode()) with every key
                                   starting "__" (the bookkeeping the store adds, e.g. __key) removed and every other key,
                                   run included, kept. Run level (all zones), not only the exported zone. Null without
                                   ingest_ledger rows. Also n_changes (zone level) = the transition rows of the run and
                                   the exported zone whose (robot, ts) is an accepted message of the replayed extractor
                                   (every transition row is one: the detector writes a transition at the ts of the message
                                   that changed the state, also from end_all), and n_repeats = extractor totals.accepted -
                                   n_changes, the accepted messages that are not a counted change of state.
                                   changes_by_step = n_changes cumulated by event-time step (steps entries, the last is
                                   n_changes), for the page's running Kept and Dropped numbers.
                                   The formula string, verbatim (it is also run_constants.kept.formula):
kept_pct = 100 * (B(transitions) + B(decisions) + B(state_sample) + B(rejects)) / sum(ingest_ledger.bytes_read_uncompressed); B(T) = sum over the rows of store.select(T, {run}) of len(json.dumps(row, sort_keys=True, separators=(',', ':')).encode()) with keys starting '__' removed
                hotspot            {precision_at_20, recall_at_k, k (= n_floor), zero_stall_share, n_floor, source} from
                                   --hotspot zones[zone]; the export raises when the file's run != meta.run or its n_floor
                                   != the number of obstacles.
                closed_loop        {arm (= headline_arm), map_share, map_share_ci95, oracle_share, oracle_share_ci95,
                                   source} from --closed-loop-summary: arms[arm] and arms["oracle"]
                                   .share_of_floor_loss_recovered.
                audit              {sent, read, missing, source "emit_ledger:zones[Z].messages / store:extractor"}: sent =
                                   the emit ledger's zones[Z].messages (the sender's own count of robot messages), read =
                                   extractor totals.accepted, missing = sent - read. The deliberate headerId jump of the demo
                                   noise is NOT a missing message (the extractor's missing_messages counts it, this does
                                   not). Null without a ledger entry for the zone.
                header             {msgs, noise, source}: msgs = extractor totals.messages (lines that arrived), noise = the
                                   exported zone's ledger injected_noise malformed + duplicates (the ledger total when the
                                   zone has no entry of its own; noise_scope says "zone" or "total").
                speed              {robot_rate, ingest_rate, ratio, source = the --benchmark path, robot_rate_source}:
                                   robot_rate = ledger zones[Z].messages / (meta.steps * STEP_SECONDS), ingest_rate =
                                   benchmark batch.msgs_per_s, ratio = floor(ingest_rate / robot_rate). Null without
                                   --benchmark or the ledger count.
                lessons_long       {truth_hit, truth_n, held, graded, persist_held, persist_graded, source} from --lessons-long:
                                   grading_counts.lesson_truth.hit, sum(grading_counts.lesson_truth.values()),
                                   grading_counts.lesson.ok, lesson.ok + lesson.off, and persist_held = lesson_persist.ok,
                                   persist_graded = lesson_persist.ok + lesson_persist.off (both null when the JSON has no
                                   lesson_persist; zero-count keys are omitted from grading_counts, hence .get).
                                   Context from a longer independent run, not from this shift.
                worth              {bars [{key, mean, ci95_low, ci95_high, source}] in the order none, map_a32, oracle_a32,
                                   undisturbed, map_share, map_share_ci95, oracle_share, oracle_share_ci95, n_seeds, label,
                                   source = the common directory of the four row files}. bars come from the row files
                                   --sticky-none / --sticky-map-a32 / --sticky-oracle-a32 / --sticky-undisturbed (one file
                                   per arm: pick_rate_mean, ci95_low, ci95_high of the file). Each file's rows are sorted by
                                   seed and the export raises when the four seed sets differ. SHARE FORMULA: share(arm) =
                                   mean over seeds of (arm_pick_rate - none_pick_rate) / mean over seeds of
                                   (undisturbed_pick_rate - none_pick_rate), paired on seed; the ci95 is the seed bootstrap
                                   of scripts/closed_loop.share_recovered (the only part taken from it). This is a 30-seed
                                   test on a floor that traps robots, NOT the shift in the replay; `label` says so. Null
                                   unless all four files are given. Every entry above, like the other run_constants, may
                                   come from other files or runs than the replay: they are labelled context.
                dose_response      [{label, p_lo, p_hi, floor_loss, arms {none, map_a4, map_a32, oracle: each {pick_rate_mean,
                                   ci95, share, share_ci95}}, source}] in the order of the repeatable --dose-response
                                   LABEL=PATH (split on the first "="), one entry per closed-loop summary.json. p_lo/p_hi =
                                   json.loads(summary["disturb"])["floor"]["p"]; floor_loss = undisturbed - none pick-rate
                                   mean = share_of_floor_loss_recovered.mean_loss (the export raises when an arm disagrees);
                                   share/share_ci95 = share_of_floor_loss_recovered of the arm (null for "none"); source =
                                   PATH as given. Raises, naming the file, when a summary lacks one of the four arms or
                                   "undisturbed". Null without --dose-response. Context from other runs than the replay.
                explorer           {axes, floor, sweeps, source_note} from --explorer (null without; a refresh without it leaves
                                   an existing key untouched). Paths are fixed and resolved from the repo root. axes {regimes
                                   [{key, word, p_lo, p_hi}], arms [{key, alpha or null, label}] (none, map_a4, map_a8, map_a16,
                                   map_a32, oracle), steps, density, breakdown (the grid points), ci_level}. floor = one entry per
                                   (regime, arm, steps) that exists: the arms of results/closed_loop{,_p06_09,_p08_095,_sticky,
                                   _sticky_1500}/summary.json that are in {none, map_a4, map_a8, map_a16, map_a32, oracle,
                                   undisturbed}; a missing triple is absent. Each {regime, p_lo, p_hi, steps, arm, mean, ci_lo,
                                   ci_hi, n, share, share_ci_lo, share_ci_hi, src}; share is null for none and undisturbed.
                                   sweeps.density {src, policy cta, pickers_per_agv, steps, points [{point (AGVs), pickers, mean,
                                   ci_lo, ci_hi, n}]} and sweeps.breakdown {src, robots, steps, policies {cta, stuck_aware_cta:
                                   [{point (onsets per robot-hour), mean, ci_lo, ci_hi, n}]}}: pick_rate over the per-seed rows,
                                   scripts/evaluate.summarise. Context from other runs than the replay.
  lessons     every lesson decision of the run and of the exported zone (S8E, kind "lesson"), sorted by
              (decided_at, int(zone), claim subject, lesson_kind): [{run, decided_at_step, zone, text, lesson_kind,
              confidence, verdict, graded_at_step, truth}], zone = the claim's zone string. verdict "ok" / "off"
              and graded_at_step (the step of the "lesson" grade row's window_end, when the grade exists) are null while
              the lesson is open. truth = the verdict of the decision's "lesson_truth" grade row ("hit" / "false_alarm") or
              null. Rows of other grade sources never enter it, and lesson rows enter no other key (but
              run_constants.kept counts the bytes of every decisions row). The lessons are always this run's own: there is
              no carry-over from another run, and assert_single_run (below) raises on a foreign one.
  episodes    ALL detector stuck-episode rows of the zone from store.select (zone == the exported zone), NOT filtered:
              [{start_step, end_step (null = open), robot, cell [x, y], cause, resolution, left_censored, episode_id,
              verdict}]. verdict is the verdict of the graded stuck_cause decision whose claim names the episode_id
              (confirmed / refuted / inconclusive), else null. Only the
              frames skip left_censored and "interrupted" rows (see stuck above); the page does the same.
  stalls      [[robot, cell, start_step, end_step, counted]] from hotspot.extract_stalls, counted = hotspot.counted() after
              annotate_episodes (the filter the cost map uses).
  with_map    OPTIONAL, only with --closed-loop DIR when DIR/summary.json names a headline_arm and DIR/phaseA/costmap.json
              exists: {arm, alpha, map_path, map_generated_at, map_tag, deliveries, pick_rate, frames, episodes, note}. DIR holds
              per-seed aggregates only, so this layer RE-SIMULATES the zone's seed (same env, disturbance, recovery and
              policy, steps) with the cost-aware router and the FINAL phaseA map of this zone applied from step 0
              (in-sample, not learned live). Its episodes come from running fleet_analyser.detector.Detector (the ingest
              default stuck_after) over the re-simulated messages (same row shape as the top-level episodes, verdict always
              null: no store, no grader); frames use
              the same derive_state() and stuck overlay as the main layer (derive_layer). Env numbers are
              platform-dependent (pyastar2d tie-breaks): only the layer's layout is stable across machines.
"""
import argparse
import gzip
import json
import multiprocessing as mp
import os
import posixpath
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

FLEET = Path(__file__).resolve().parent
REPO = FLEET.parent
for _p in (FLEET, REPO / "src", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import hotspot_score  # noqa: E402
from fleet_analyser import detector, emitter, hotspot, ledger, store as store_mod  # noqa: E402
from fleet_analyser import live_state  # noqa: E402
from fleet_analyser.parse import epoch_of, parse_line  # noqa: E402

SCHEMA = "replay/4"
STATES = ("moving", "loading", "stalled", "stuck", "frozen", "idle")
MAX_BYTES = 2 * 1024 * 1024
PREFIX = "window.REPLAY = "
CHECK_KEYS = ("messages_parsed", "messages_rejected", "duplicates", "sequence_gaps", "missing_messages",
              "messages_accepted", "bytes_read_uncompressed")
SERIES_KEYS = ("bytes", "messages", "parsed", "rejected", "duplicates", "sequence_gaps", "missing_messages", "accepted")
STEP_SECONDS = 5


# ------------------------------------------------------------------------------------------------ state derivation
def derive_state(msg, in_episode=False, in_stall=False):
    """The state of one robot at one message, precedence frozen > stuck > stalled > loading > moving > idle."""
    if msg.faulted:
        return "frozen"
    if in_episode:
        return "stuck"
    if in_stall:
        return "stalled"
    if msg.order_id != "" and not msg.driving and msg.nodes_reported and msg.next_x is None:
        return "loading"
    if msg.driving:
        return "moving"
    return "idle"


def _intervals(rows):
    """{robot: [(start, end_or_inf)]}; the rows are episodes (skip rule of annotate_episodes) or stalls."""
    out = {}
    for r in rows:
        if r.get("left_censored") or r.get("resolution") == "interrupted":
            continue
        end = float("inf") if r.get("end") is None else r["end"]
        out.setdefault(r["robot"], []).append((r["start"], end))
    return out


def _within(spans, ts):
    return any(a <= ts <= b for a, b in spans)


def build_frames(messages, robots, t0_ts, steps, episodes, stalls, grid, step_seconds=STEP_SECONDS):
    """frames[step][robot_index] = [x, y, state, job]. Raises ValueError for a position outside the grid."""
    ep_by = _intervals(episodes)
    st_by = _intervals(stalls)
    index = {r["serial"]: i for i, r in enumerate(robots)}
    cell = {}  # (robot_index, step) -> (header_id, entry)
    for m in messages:
        i = index.get(m.serial)
        step, rem = divmod(m.ts - t0_ts, step_seconds)
        if i is None or rem or not 0 <= step < steps:
            continue
        if not (0 <= m.x < grid["width"] and 0 <= m.y < grid["height"]):
            raise ValueError(f"{m.serial} reports ({m.x}, {m.y}) at step {step}, outside the {grid['width']}x"
                             f"{grid['height']} grid")
        state = derive_state(m, _within(ep_by.get(m.serial, ()), m.ts), _within(st_by.get(m.serial, ()), m.ts))
        prev = cell.get((i, step))
        if prev is None or m.header_id > prev[0]:
            cell[(i, step)] = (m.header_id, [m.x, m.y, state, m.order_id])
    frames = [[None] * len(robots) for _ in range(steps)]
    for i in range(len(robots)):
        last = None
        first = next((cell[(i, s)][1] for s in range(steps) if (i, s) in cell), None)
        for s in range(steps):
            if (i, s) in cell:
                last = cell[(i, s)][1]
            elif last is None and first is not None:
                last = [first[0], first[1], "idle", ""]
            frames[s][i] = list(last) if last is not None else None
    for s, row in enumerate(frames):
        for i, e in enumerate(row):
            if e is None:
                raise ValueError(f"robot {robots[i]['serial']} has no message in the zone files")
    return frames


# ------------------------------------------------------------------------------------------------ extractor
def zone_files(run_dir, zone):
    return sorted(Path(run_dir).glob(f"zone{zone}-*.jsonl.gz"))


def replay_extractor(files, t0_ts, steps, expected, bytes_compressed=None, step_seconds=STEP_SECONDS, accepted_out=None):
    """Replay the zone files line by line; returns (series, totals). See the module docstring. accepted_out: an optional set that
    receives (serial, ts) of every accepted message."""
    zeros = lambda: [0] * steps  # noqa: E731
    delta = {k: zeros() for k in SERIES_KEYS}
    reasons = {}
    seq = ledger.SequenceTracker()
    last_step = 0
    for path in files:
        with gzip.open(path, "rb") as f:
            for raw in f:
                msg, reason = parse_line(raw)
                if msg is None:
                    step = last_step
                    delta["rejected"][step] += 1
                    reasons.setdefault(reason, zeros())[step] += 1
                else:
                    step = min(max((msg.ts - t0_ts) // step_seconds, 0), steps - 1)
                    last_step = step
                    delta["parsed"][step] += 1
                    accepted, missing = seq.check(msg.serial, msg.header_id)
                    if not accepted:
                        delta["duplicates"][step] += 1
                    else:
                        delta["accepted"][step] += 1
                        if accepted_out is not None:
                            accepted_out.add((msg.serial, msg.ts))
                        if missing:
                            delta["sequence_gaps"][step] += 1
                            delta["missing_messages"][step] += missing
                delta["bytes"][step] += len(raw)
                delta["messages"][step] += 1

    def cumulative(xs):
        out, tot = [], 0
        for x in xs:
            tot += x
            out.append(tot)
        return out

    series = {k: cumulative(v) for k, v in delta.items()}
    series["rejected_by_reason"] = {r: cumulative(v) for r, v in sorted(reasons.items())}
    series["coverage"] = [None if ledger.coverage(a, expected) is None else round(ledger.coverage(a, expected), 6)
                          for a in series["accepted"]]
    totals = {k: series[k][-1] for k in SERIES_KEYS}
    totals["rejected_by_reason"] = {r: v[-1] for r, v in series["rejected_by_reason"].items()}
    totals["coverage"] = series["coverage"][-1]
    totals["expected_messages"] = expected
    totals["bytes_compressed"] = bytes_compressed
    return series, totals


def _counter_sum(row):
    out = dict.fromkeys(CHECK_KEYS, 0)
    for minute in json.loads(row["ledger_counters"] or "{}").values():
        for k in CHECK_KEYS:
            out[k] += minute.get(k, 0) or 0
    return out


def ingest_check(st, run, files):
    """The ingest checkpoint counters of `files` (differences to the previous checkpoint by cp_seq), or None."""
    latest = {}
    for r in st.select("ingest_checkpoints", {"run": run}):
        name = posixpath.basename(r["path"].replace("\\", "/"))
        key = (r.get("cp_seq") or 0, r.get("updated_at") or 0)
        if name not in latest or key > (latest[name].get("cp_seq") or 0, latest[name].get("updated_at") or 0):
            latest[name] = r
    ordered = sorted(latest.values(), key=lambda r: (r.get("cp_seq") or 0, r.get("updated_at") or 0))
    total = dict.fromkeys(CHECK_KEYS, 0)
    for f in files:
        row = latest.get(f.name)
        if row is None or not row.get("ledger_counters"):
            return None
        i = ordered.index(row)
        cur = _counter_sum(row)
        prev = _counter_sum(ordered[i - 1]) if i > 0 and ordered[i - 1].get("ledger_counters") else dict.fromkeys(CHECK_KEYS, 0)
        for k in CHECK_KEYS:
            total[k] += cur[k] - prev[k]
    return total


def verify_check(totals, check):
    if check is None:
        return
    mine = dict(messages_parsed=totals["parsed"], messages_rejected=totals["rejected"], duplicates=totals["duplicates"],
                sequence_gaps=totals["sequence_gaps"], missing_messages=totals["missing_messages"],
                messages_accepted=totals["accepted"], bytes_read_uncompressed=totals["bytes"])
    bad = {k: (mine[k], check[k]) for k in CHECK_KEYS if mine[k] != check[k]}
    if bad:
        raise ValueError(f"the replayed extractor totals disagree with the ingest checkpoint (replay, checkpoint): {bad}")


# ------------------------------------------------------------------------------------------------ publishes, grades
def build_publishes(st, run, zone, floor_cells, t0_ts, step_seconds=STEP_SECONDS):
    by_t = {}
    for r in st.select("costmap", {"run": run, "zone": zone}):
        by_t.setdefault(r["published_at"], []).append(r)
    out = []
    for t in sorted(by_t):
        rows = by_t[t]
        zmap = {r["cell"]: r["cost"] for r in rows}
        k = len(floor_cells)
        both = hotspot_score.precision_recall(zmap, floor_cells, ks=(20, k) if k > 0 else (20,))
        pr = both[20]
        cells = [[r["cell"], round(r["cost"], 4), r["stalls"]] for r in sorted(rows, key=lambda r: (-r["cost"], r["cell"]))
                 if r["cost"] > 0]
        out.append(dict(t=t, step=(t - t0_ts) // step_seconds, cells=cells, precision_at_20=pr["precision"],
                        hits_at_20=pr["hits"], n_flagged=len(hotspot_score.ranked_cells(zmap)),
                        recall_at_k=both[k]["recall"] if k > 0 else None, k=k))
    return out


def _claim(d):
    c = d["claim"]
    return json.loads(c) if isinstance(c, str) else (c or {})


def build_lessons(st, run, t0_ts, step_seconds=STEP_SECONDS, zone=None):
    """Every lesson decision of the run (all zones, or only `zone` when given) as a timeline (see the `lessons` payload key). The
    verdict and graded_at_step come from the "lesson" forecast_grades row of the decision (window_end = the time the grade
    exists), truth from its "lesson_truth" row, never from rows of other sources; an open lesson has verdict and graded_at_step
    null, an unscored one has truth null."""
    decs = st.select("decisions", {"run": run, "kind": "lesson"})
    if zone is not None:
        decs = [d for d in decs if str(_claim(d)["zone"]) == str(zone)]
    by_id = {d["id"]: d for d in decs}
    grades = st.select("forecast_grades", {"run": run})
    rows = {g["id"]: g for g in grades if g["grade_source"] == "lesson" and g["id"] in by_id}
    truth = {g["id"]: g["verdict"] for g in grades if g["grade_source"] == "lesson_truth" and g["id"] in by_id}
    out = []
    for d in sorted(decs, key=lambda d: (d["decided_at"], int(_claim(d)["zone"]), _claim(d)["subject"],
                                                _claim(d)["lesson_kind"])):
        c, g = _claim(d), rows.get(d["id"])
        out.append(dict(run=d["run"], decided_at_step=(d["decided_at"] - t0_ts) // step_seconds, zone=c["zone"],
                        text=c["text"],
                        lesson_kind=c["lesson_kind"], confidence=c["confidence"],
                        verdict=None if g is None else g["verdict"],
                        graded_at_step=None if g is None else (g["window_end"] - t0_ts) // step_seconds,
                        truth=truth.get(d["id"])))
    return out


def build_grades(st, run, zone, publishes, t0_ts, step_seconds=STEP_SECONDS):
    decs = [d for d in st.select("decisions", {"run": run, "kind": "hotspot_forecast"})
            if d["subject"].startswith(f"Z{zone}:")]
    by_id = {d["id"]: d for d in decs}
    rows_by_id = {}
    for g in st.select("forecast_grades", {"run": run}):
        if g["id"] in by_id:
            rows_by_id.setdefault(g["id"], []).append(g)
    per_publish = []
    for p in publishes:
        mine = [d for d in decs if d["decided_at"] == p["t"]]
        outcome, count, truth = dict(ok=0, off=0), dict(ok=0, off=0), dict(hit=0, false_alarm=0)
        n_open = unranked = 0
        kinds = set()
        for d in mine:
            rows = rows_by_id.get(d["id"], [])
            has_outcome = False
            for g in rows:
                src, v = g["grade_source"], g["verdict"]
                if src == "outcome" and v in outcome:
                    outcome[v] += 1
                    has_outcome = True
                    kinds.add("rank" if d.get("claim_version", 1) >= 2 and "top_k" in _claim(d) else "count")
                elif src == "outcome_count" and v in count:
                    count[v] += 1
                elif src == "truth" and v in truth:
                    truth[v] += 1
            if not has_outcome and d["status"] == "open":
                n_open += 1
            if d.get("verdict") == "unranked":
                unranked += 1
        kind = None if not kinds else (next(iter(kinds)) if len(kinds) == 1 else "mixed")
        ends = [g["window_end"] for d in mine for g in rows_by_id.get(d["id"], [])
                if g["grade_source"] in ("outcome", "outcome_count") and g.get("window_end") is not None]
        end = max(ends) if ends else None
        per_publish.append(dict(t=p["t"], forecasts=len(mine), outcome=outcome, outcome_count=count, truth=truth, open=n_open,
                                unranked=unranked, outcome_kind=kind, window_end=end,
                                window_end_step=None if end is None else (end - t0_ts) // step_seconds))
    events = {}
    for gid, rows in rows_by_id.items():
        for g in rows:
            t = g["window_end"] if g.get("window_end") is not None else by_id[gid]["decided_at"]
            e = events.setdefault(t, dict(outcome_ok=0, outcome_off=0, truth_hit=0, truth_false_alarm=0))
            key = {("outcome", "ok"): "outcome_ok", ("outcome", "off"): "outcome_off", ("truth", "hit"): "truth_hit",
                   ("truth", "false_alarm"): "truth_false_alarm"}.get((g["grade_source"], g["verdict"]))
            if key:
                e[key] += 1
    timeline, cum = [], dict(outcome_ok=0, outcome_off=0, truth_hit=0, truth_false_alarm=0)
    for t in sorted(events):
        for k in cum:
            cum[k] += events[t][k]
        timeline.append(dict(t=t, step=(t - t0_ts) // step_seconds, **cum))
    return dict(per_publish=per_publish, timeline=timeline)


def stuck_verdicts(st, run):
    """{episode_id: verdict} of the graded stuck_cause decisions (the claim names the episode)."""
    out = {}
    for d in st.select("decisions", {"run": run, "kind": "stuck_cause"}):
        if d.get("status") == "graded" and d.get("verdict") in ("confirmed", "refuted", "inconclusive"):
            out[_claim(d).get("episode_id")] = d["verdict"]
    return out


def build_episodes(rows, zone, t0_ts, step_seconds=STEP_SECONDS, verdicts=None):
    verdicts = verdicts or {}
    out = []
    for e in rows:
        if str(e["zone"]) != str(zone):
            continue
        out.append(dict(start_step=(e["start"] - t0_ts) // step_seconds,
                        end_step=None if e.get("end") is None else (e["end"] - t0_ts) // step_seconds,
                        robot=e["robot"], cell=list(e["cell"]), cause=e["cause"], resolution=e["resolution"],
                        left_censored=bool(e.get("left_censored")),
                        episode_id=e["episode_id"], verdict=verdicts.get(e["episode_id"])))
    return sorted(out, key=lambda e: (e["start_step"], e["robot"]))


# ------------------------------------------------------------------------------------------------ env layer (own process)
def _grid_of(hook):
    rows, cols = hook.grid_size
    return dict(width=int(cols), height=int(rows),
                highway=["".join(str(int(hook.highways[y, x])) for x in range(cols)) for y in range(rows)],
                goals=[[int(x), int(y)] for x, y in hook.goals],
                shelves=sorted([int(s.x), int(s.y)] for s in hook.shelfs))


def _kind(agent, i, num_agvs):
    return "agv" if i < num_agvs else "picker"


def env_worker(job):
    """Runs in a fresh spawned process, so exactly one env is ever built there. job = dict(env_id, steps, seed, zone,
    run=None | the run_zone cfg). Returns dict(grid, kinds {serial: kind}, lines (with_map only), deliveries, pick_rate)."""
    from warehouse_rl.env import WarehouseEnv

    seen = {}

    def capture(env):
        hook = env.env
        seen["grid"] = _grid_of(hook)
        seen["kinds"] = {f"Z{job['zone']}-{a.id:02d}": _kind(a, i, hook.num_agvs) for i, a in enumerate(hook.agents)}

    if job["run"] is None:
        env = WarehouseEnv(job["env_id"], max_steps=job["steps"])
        try:
            env.reset(seed=job["seed"])
            capture(env)
        finally:
            env.close()
        return dict(seen, lines=None, deliveries=None, pick_rate=None)

    class ListSink:
        def __init__(self):
            self.lines = []

        def write(self, serial, line, timestamp=None, header_id=None):
            self.lines.append(line)

        def stats(self):
            return dict(messages=len(self.lines), bytes_uncompressed=sum(map(len, self.lines)))

        def close(self):
            pass

    sink = ListSink()
    res = emitter.run_zone(job["run"], sink, on_ready=capture)
    return dict(seen, lines=sink.lines, deliveries=res["deliveries"], pick_rate=res["pick_rate"])


def run_env_worker(job):
    ctx = mp.get_context("spawn")
    with ProcessPoolExecutor(max_workers=1, mp_context=ctx) as ex:
        return ex.submit(env_worker, job).result()


# ------------------------------------------------------------------------------------------------ with_map
def with_map_job(closed_loop, zone, run_cfg, log=print):
    """(job, info) for the optional layer, or None (with a log line) when the closed-loop files are missing."""
    base = Path(closed_loop)
    summary_p, map_p = base / "summary.json", base / "phaseA" / "costmap.json"
    if not summary_p.is_file() or not map_p.is_file():
        log(f"replay_export: no with_map layer ({summary_p} or {map_p} missing)")
        return None
    summary = json.loads(summary_p.read_text())
    arm = summary.get("headline_arm")
    if not arm or arm not in summary.get("arms", {}):
        log(f"replay_export: no with_map layer (no usable headline_arm in {summary_p})")
        return None
    import evaluate as ev

    tag, generated_at, zones = ev._load_costmap(map_p)
    if summary.get("map_tag") not in (None, tag):
        raise ValueError(f"{map_p} has tag {tag} but {summary_p} names map_tag {summary['map_tag']}")
    seed_base = run_cfg["seed_base"]
    cost_map = ev._cost_map_for_seed(zones, seed_base + int(zone), seed_base)
    alpha = float(summary["arms"][arm]["alpha"])
    cfg = dict(zone=int(zone), seed=seed_base + int(zone), steps=run_cfg["steps"], env_id=run_cfg["env_id"],
               policy=run_cfg["policy"], disturb=run_cfg["disturb"], recovery=run_cfg["recovery"], t0=run_cfg["t0"],
               cost_map=cost_map, cost_alpha=alpha)
    info = dict(arm=arm, alpha=alpha, map_path=posixpath.join(closed_loop.replace(os.sep, "/"), "phaseA", "costmap.json"),
                map_generated_at=generated_at, map_tag=tag)
    return cfg, info


WITH_MAP_NOTE = ("A second run of the same shift with the map switched on. The map is the final map from this same run, "
                 "switched on from the start, so it is in-sample and was not learned live. Its stuck periods come from "
                 "running the same detector on the messages of this second run.")


def detect_episodes(messages, stuck_after=detector.DEFAULT_STUCK_AFTER):
    """Run the ingest detector (default stuck_after) over parsed messages in ts order and return episode rows of the
    shape store.select("stuck_episodes") gives (an episode_close replaces its episode_open, by episode_id)."""
    det = detector.Detector(stuck_after=stuck_after)
    rows = {}
    events = []
    for m in sorted(messages, key=lambda m: (m.ts, m.serial)):
        events += det.feed(m)
    events += det.end_all()
    for ev in events:
        if ev["kind"] in ("episode_open", "episode_close"):
            rows[ev["episode_id"]] = {k: v for k, v in ev.items() if k not in ("kind", "decided_by")}
    return list(rows.values())


def derive_layer(messages, robots, t0_ts, steps, grid, run, stuck_after=detector.DEFAULT_STUCK_AFTER):
    """(frames, episode_rows, stalls) of a layer that has no store: the same state function and stuck overlay as the
    main layer, with the episodes found by running the detector on the layer's own messages."""
    episode_rows = detect_episodes(messages, stuck_after)
    stalls = hotspot.extract_stalls(messages, run)
    hotspot.annotate_episodes(stalls, episode_rows)
    return build_frames(messages, robots, t0_ts, steps, episode_rows, stalls, grid), episode_rows, stalls


# ------------------------------------------------------------------------------------------------ run constants
KEPT_TABLES = ("transitions", "decisions", "state_sample", "rejects")
KEPT_FORMULA = ("kept_pct = 100 * (B(transitions) + B(decisions) + B(state_sample) + B(rejects)) / "
                "sum(ingest_ledger.bytes_read_uncompressed); B(T) = sum over the rows of store.select(T, {run}) of "
                "len(json.dumps(row, sort_keys=True, separators=(',', ':')).encode()) with keys starting '__' removed")
INGEST_RATE_FORMULA = "sum(messages_parsed) / sum(messages_parsed / msgs_per_s) over the run's ingest_ledger rows with a rate"


def row_bytes(row):
    """Bytes of one store row as the kept formula counts them (see the module docstring)."""
    clean = {k: v for k, v in row.items() if not str(k).startswith("__")}
    return len(json.dumps(clean, sort_keys=True, separators=(",", ":")).encode())


def ingest_rate(ledger_rows):
    rows = [r for r in ledger_rows if (r.get("msgs_per_s") or 0) > 0 and (r.get("messages_parsed") or 0) > 0]
    if not rows:
        return None
    seconds = sum(r["messages_parsed"] / r["msgs_per_s"] for r in rows)
    return sum(r["messages_parsed"] for r in rows) / seconds


def kept_constant(st, run, ledger_rows, n_zones):
    """run_constants.kept (see the module docstring); None without ingest_ledger rows or without arrived bytes."""
    arrived = sum(r.get("bytes_read_uncompressed") or 0 for r in ledger_rows)
    if not ledger_rows or arrived <= 0:
        return None
    by_table = {t: sum(row_bytes(r) for r in st.select(t, {"run": run})) for t in KEPT_TABLES}
    kept = sum(by_table.values())
    return dict(kept_pct=100 * kept / arrived, bytes_kept=kept, bytes_arrived=arrived, bytes_by_table=by_table,
                scope="run", n_zones=n_zones, source="store:transitions+decisions+state_sample+rejects / store:ingest_ledger",
                formula=KEPT_FORMULA)


def _load_json(path, what):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError(f"cannot read the {what} file {path}: {e}") from e


def benchmark_constant(path):
    if path is None:
        return None
    try:
        value = _load_json(path, "benchmark")["batch"]["msgs_per_s"]
    except (KeyError, TypeError) as e:
        raise ValueError(f"{path} has no batch.msgs_per_s") from e
    return dict(value=value, source=path)


def hotspot_constant(path, run, zone, n_obstacles):
    if path is None:
        return None
    doc = _load_json(path, "hotspot")
    if doc.get("run") != run:
        raise ValueError(f"{path} scores run {doc.get('run')!r}, the export is run {run!r}")
    z = (doc.get("zones") or {}).get(zone)
    if z is None:
        raise ValueError(f"{path} has no zone {zone}")
    if z.get("n_floor") != n_obstacles:
        raise ValueError(f"{path} has n_floor {z.get('n_floor')} for zone {zone}, the export has {n_obstacles} obstacles")
    try:
        return dict(precision_at_20=z["k"]["20"]["precision"], recall_at_k=z["k"][str(n_obstacles)]["recall"], k=n_obstacles,
                    zero_stall_share=z["zero_stall_share"], n_floor=z["n_floor"], source=path)
    except KeyError as e:
        raise ValueError(f"{path} lacks {e} for zone {zone}") from e


def closed_loop_constant(path):
    if path is None:
        return None
    doc = _load_json(path, "closed-loop summary")
    arm = doc.get("headline_arm")
    try:
        mine = doc["arms"][arm]["share_of_floor_loss_recovered"]
        oracle = doc["arms"]["oracle"]["share_of_floor_loss_recovered"]
        return dict(arm=arm, map_share=mine["share"], map_share_ci95=mine["ci95"], oracle_share=oracle["share"],
                    oracle_share_ci95=oracle["ci95"], source=path)
    except (KeyError, TypeError) as e:
        raise ValueError(f"{path} lacks arms[headline_arm / oracle].share_of_floor_loss_recovered ({e})") from e


WORTH_ARMS = ("none", "map_a32", "oracle_a32", "undisturbed")
WORTH_LABEL = ("The bars come from a {n}-seed simulator test on a harder floor, one that traps robots, not from the shift in "
               "panel 1.")


def lessons_long_constant(path):
    if path is None:
        return None
    try:
        counts = _load_json(path, "lessons-long")["grading_counts"]
        truth, lesson = counts["lesson_truth"], counts["lesson"]
        lp = counts.get("lesson_persist")
        if lp is not None and not isinstance(lp, dict):
            raise ValueError(f"{path} grading_counts.lesson_persist is {type(lp).__name__}, expected an object")
        persist_held = None if lp is None else lp.get("ok", 0)
        persist_graded = None if lp is None else lp.get("ok", 0) + lp.get("off", 0)
        return dict(truth_hit=truth["hit"], truth_n=sum(truth.values()), held=lesson["ok"], graded=lesson["ok"] + lesson["off"],
                    persist_held=persist_held, persist_graded=persist_graded, source=path)
    except (KeyError, TypeError) as e:
        raise ValueError(f"{path} lacks grading_counts.lesson / lesson_truth ({e})") from e


DOSE_ARMS = ("none", "map_a4", "map_a32", "oracle")


def dose_response_constant(specs):
    """run_constants.dose_response from ["LABEL=PATH", ...] (see the module docstring); None without specs."""
    if not specs:
        return None
    out = []
    for spec in specs:
        label, sep, path = spec.partition("=")
        if not sep or not label or not path:
            raise ValueError(f"--dose-response {spec!r} is not LABEL=PATH")
        doc = _load_json(path, "dose-response")
        try:
            arms = doc["arms"]
            missing = [a for a in DOSE_ARMS + ("undisturbed",) if not isinstance(arms.get(a), dict)]
            if missing:
                raise ValueError(f"{path} lacks arms {', '.join(missing)}")
            disturb = doc["disturb"]
            p_lo, p_hi = (json.loads(disturb) if isinstance(disturb, str) else disturb)["floor"]["p"]
            loss = arms["undisturbed"]["pick_rate_mean"] - arms["none"]["pick_rate_mean"]
            entry_arms, mean_loss = {}, None
            for a in DOSE_ARMS:
                row = arms[a]
                sh = row.get("share_of_floor_loss_recovered")
                if a == "none":
                    share = share_ci = None
                else:
                    if not isinstance(sh, dict):
                        raise ValueError(f"{path} arm {a} lacks share_of_floor_loss_recovered")
                    if abs(sh["mean_loss"] - loss) > 1e-9:
                        raise ValueError(f"{path} arm {a} mean_loss {sh['mean_loss']} != undisturbed - none {loss}")
                    mean_loss = sh["mean_loss"]
                    share, share_ci = sh["share"], list(sh["ci95"])
                entry_arms[a] = dict(pick_rate_mean=row["pick_rate_mean"], ci95=list(row["pick_rate_ci95"]),
                                     share=share, share_ci95=share_ci)
        except (KeyError, TypeError, IndexError) as e:
            raise ValueError(f"{path} is not a closed-loop summary with the fields the dose response needs ({type(e).__name__}: {e})") from e
        out.append(dict(label=label, p_lo=p_lo, p_hi=p_hi, floor_loss=mean_loss, arms=entry_arms, source=path))
    return out


# S11A: the explorer's data. Paths are resolved from the repo root, never from the cwd.
EXPLORER_FILES = (  # (regime key, word, summary path); the order is the page order
    ("mild", "mild", "results/closed_loop/summary.json"),
    ("medium", "medium", "results/closed_loop_p06_09/summary.json"),
    ("sticky", "sticky", "results/closed_loop_p08_095/summary.json"),
    ("very_sticky", "very sticky", "results/closed_loop_sticky/summary.json"),
    ("very_sticky", "very sticky", "results/closed_loop_sticky_1500/summary.json"))
EXPLORER_ARMS = (("none", "no map"), ("map_a4", "map, alpha"), ("map_a8", "map, alpha"), ("map_a16", "map, alpha"),
                 ("map_a32", "map, alpha"), ("oracle", "perfect knowledge"))
EXPLORER_KEPT = tuple(k for k, _ in EXPLORER_ARMS) + ("undisturbed",)
CI_KEY = "pick_rate_ci95"
EXPLORER_DENSITY ="results/sweeps/density.json"
EXPLORER_BREAKDOWN = "results/sweeps/breakdown.json"
EXPLORER_NOTE = ("Every figure is the mean over the recorded shifts in one results file. Nothing is estimated between the "
                 "measured settings, so a setting that was not measured cannot be picked.")


def _whole(x):
    """4.0 -> 4 so a whole-number setting is written without a decimal point; anything else unchanged."""
    return int(x) if isinstance(x, float) and x == int(x) else x


def sweep_points(path, filt, point_key="point"):
    """(doc, [{point, mean, ci_lo, ci_hi, n, rows}]) of pick_rate per grid point over the per-seed rows that pass `filt`, in the
    order of the file's own definition.grid. Stats are scripts/evaluate.summarise (ci95_low/ci95_high renamed)."""
    import evaluate as ev
    doc = _load_json(path, "sweep")
    rows = [r for r in doc["rows"] if filt(r)]
    out = []
    for g in doc["definition"]["grid"]:
        at = [r for r in rows if r[point_key] == g]
        if not at:
            raise ValueError(f"{path} has no rows at grid point {g}")
        s = ev.summarise([r["pick_rate"] for r in at])
        out.append(dict(point=g, mean=s["mean"], ci_lo=s["ci95_low"], ci_hi=s["ci95_high"], n=s["n"], rows=at))
    return doc, out


def explorer_constant(repo=None):
    """run_constants.explorer (see the module docstring). Reads only the five closed-loop summaries and the two sweeps."""
    repo = Path(repo) if repo is not None else REPO
    rel = lambda p: str(repo / p)
    regimes, floor, steps_seen, alpha_of = [], [], [], {}
    for key, word, path in EXPLORER_FILES:
        doc = _load_json(rel(path), "explorer")
        try:
            p_lo, p_hi = (json.loads(doc["disturb"]) if isinstance(doc["disturb"], str) else doc["disturb"])["floor"]["p"]
            steps = doc["steps"]
            arms = doc["arms"]
            prev = next((r for r in regimes if r["key"] == key), None)
            if prev is None:
                regimes.append(dict(key=key, word=word, p_lo=p_lo, p_hi=p_hi))
            elif (prev["p_lo"], prev["p_hi"]) != (p_lo, p_hi):
                raise ValueError(f"{path} p range {(p_lo, p_hi)} differs from {(prev['p_lo'], prev['p_hi'])} of regime {key}")
            if steps not in steps_seen:
                steps_seen.append(steps)
            for arm in EXPLORER_KEPT:
                if arm not in arms:
                    continue
                row = arms[arm]
                alpha = _whole(row.get("alpha"))
                if arm in alpha_of and alpha_of[arm] != alpha:
                    raise ValueError(f"{path} arm {arm} alpha {alpha} differs from another file's {alpha_of[arm]}")
                alpha_of[arm] = alpha
                sh = row.get("share_of_floor_loss_recovered")
                if arm in ("none", "undisturbed"):
                    share = ci = None
                else:
                    if not isinstance(sh, dict):
                        raise ValueError(f"{path} arm {arm} lacks share_of_floor_loss_recovered")
                    share, ci = sh["share"], sh["ci95"]
                floor.append(dict(regime=key, p_lo=p_lo, p_hi=p_hi, steps=steps, arm=arm, mean=row["pick_rate_mean"],
                                  ci_lo=row[CI_KEY][0], ci_hi=row[CI_KEY][1], n=row["n"], share=share,
                                  share_ci_lo=None if ci is None else ci[0], share_ci_hi=None if ci is None else ci[1],
                                  src=f"{path}:arms.{arm}"))
        except (KeyError, TypeError, IndexError) as e:
            raise ValueError(f"{path} is not a closed-loop summary with the fields the explorer needs ({type(e).__name__}: {e})") from e
    for arm, _ in EXPLORER_ARMS:
        if arm not in alpha_of:
            raise ValueError(f"no summary has arm {arm}")
    ddoc, dpts = sweep_points(rel(EXPLORER_DENSITY), lambda r: r["policy"] == "cta")
    ratios = {(r["n_agents"] - p["point"]) / p["point"] for p in dpts for r in p["rows"]}
    if len(ratios) != 1:
        raise ValueError(f"{EXPLORER_DENSITY}: pickers per AGV is not one value ({sorted(ratios)})")
    density = dict(src=f"{EXPLORER_DENSITY}:rows[policy=cta].pick_rate by point (AGVs)", policy="cta", pickers_per_agv=ratios.pop(),
                   steps=ddoc["definition"]["steps"],
                   points=[dict(point=p["point"], pickers=p["rows"][0]["n_agents"] - p["point"], mean=p["mean"], ci_lo=p["ci_lo"],
                                ci_hi=p["ci_hi"], n=p["n"]) for p in dpts])
    bdoc = _load_json(rel(EXPLORER_BREAKDOWN), "sweep")
    policies, robots = {}, set()
    for pol in ("cta", "stuck_aware_cta"):
        _, pts = sweep_points(rel(EXPLORER_BREAKDOWN), lambda r, pol=pol: r["policy"] == pol)
        policies[pol] = [dict(point=p["point"], mean=p["mean"], ci_lo=p["ci_lo"], ci_hi=p["ci_hi"], n=p["n"]) for p in pts]
        robots |= {r["n_agents"] for p in pts for r in p["rows"]}
    if len(robots) != 1:
        raise ValueError(f"{EXPLORER_BREAKDOWN}: robot count is not one value ({sorted(robots)})")
    breakdown = dict(src=f"{EXPLORER_BREAKDOWN}:rows[policy=cta|stuck_aware_cta].pick_rate by point (onsets per robot-hour)",
                     robots=robots.pop(), steps=bdoc["definition"]["steps"], policies=policies)
    axes = dict(
        regimes=regimes,
        arms=[dict(key=k, alpha=alpha_of[k], label=lab) for k, lab in EXPLORER_ARMS],
        steps=sorted(steps_seen),
        density=[p["point"] for p in dpts],
        breakdown=[p["point"] for p in policies["cta"]],
        ci_level=int(re.search(r"ci(\d+)", CI_KEY).group(1)))
    return dict(axes=axes, floor=floor, sweeps=dict(density=density, breakdown=breakdown), source_note=EXPLORER_NOTE)


def zone_ledger(emit, zone):
    """The emit ledger's entry of the exported zone, or {}."""
    return next((z for z in emit.get("zones", []) if str(z.get("zone")) == str(zone)), {})


def audit_constant(zrow, totals, zone):
    """run_constants.audit: the sender's own count against what the extractor accepted (see the module docstring)."""
    sent = zrow.get("messages")
    if sent is None:
        return None
    return dict(sent=sent, read=totals["accepted"], missing=sent - totals["accepted"],
                source=f"emit_ledger:zones[{zone}].messages / store:extractor accepted")


def header_constant(emit, zrow, totals, zone):
    """run_constants.header: lines that arrived and the deliberately broken ones, from the emit ledger."""
    entry = zrow.get("injected_noise")
    scope = "zone"
    if entry is None:
        entry, scope = (emit.get("total") or {}).get("injected_noise"), "total"
    if entry is None:
        return None
    where = f"zones[{zone}]" if scope == "zone" else "total"
    return dict(msgs=totals["messages"], noise=entry["malformed"] + entry["duplicates"], noise_scope=scope,
                source=f"emit_ledger:{where}.injected_noise (malformed + duplicates) / store:extractor messages")


def speed_constant(benchmark, zrow, steps, zone):
    """run_constants.speed (see the module docstring); None without the benchmark or the ledger's message count."""
    if benchmark is None or zrow.get("messages") is None:
        return None
    robot_rate = zrow["messages"] / (steps * STEP_SECONDS)
    return dict(robot_rate=robot_rate, ingest_rate=benchmark["value"], ratio=int(benchmark["value"] // robot_rate),
                source=benchmark["source"],
                robot_rate_source=f"emit_ledger:zones[{zone}].messages / (meta.steps * {STEP_SECONDS})")


def _row_file(path, arm):
    doc = _load_json(path, f"sticky row ({arm})")
    try:
        rows = sorted(doc["rows"], key=lambda r: r["seed"])
        for k in ("pick_rate_mean", "ci95_low", "ci95_high"):
            doc[k]
        [r["pick_rate"] for r in rows]
    except (KeyError, TypeError) as e:
        raise ValueError(f"{path} is not a closed-loop row file ({e})") from e
    return doc, rows


def worth_constant(paths):
    """run_constants.worth from the four sticky row files; paths = {arm: path}; None unless all four are given."""
    if not paths or any(paths.get(a) is None for a in WORTH_ARMS):
        return None
    docs, rows = {}, {}
    for arm in WORTH_ARMS:
        docs[arm], rows[arm] = _row_file(paths[arm], arm)
    seeds = {arm: [r["seed"] for r in rows[arm]] for arm in WORTH_ARMS}
    if any(seeds[a] != seeds["none"] for a in WORTH_ARMS) or len(set(seeds["none"])) != len(seeds["none"]):
        raise ValueError(f"the sticky row files do not hold the same seeds: { {a: len(v) for a, v in seeds.items()} }")
    n = len(rows["none"])
    pr = {a: [r["pick_rate"] for r in rows[a]] for a in WORTH_ARMS}

    def share(arm):
        loss = sum(u - b for u, b in zip(pr["undisturbed"], pr["none"])) / n
        if loss <= 0:
            raise ValueError("the floor loss (undisturbed - none) is not positive, so there is no share to show")
        return sum(a - b for a, b in zip(pr[arm], pr["none"])) / n / loss

    import closed_loop  # scripts/closed_loop.py loads the evaluate script at import time, so only here

    def ci95(arm):
        res = closed_loop.share_recovered(rows[arm], rows["none"], rows["undisturbed"])
        if res["ci95"] is None:
            raise ValueError(f"no confidence interval for the {arm} share: {res['reason']}")
        return res["ci95"]

    bars = [dict(key=a, mean=docs[a]["pick_rate_mean"], ci95_low=docs[a]["ci95_low"], ci95_high=docs[a]["ci95_high"],
                 source=paths[a]) for a in WORTH_ARMS]
    return dict(bars=bars, map_share=share("map_a32"), map_share_ci95=ci95("map_a32"), oracle_share=share("oracle_a32"),
                oracle_share_ci95=ci95("oracle_a32"), n_seeds=n, label=WORTH_LABEL.format(n=n),
                source=", ".join(str(paths[a]) for a in WORTH_ARMS))  # the four paths as passed


# ------------------------------------------------------------------------------------------------ one run, one zone
def _serial_zone(serial):
    """'Z3-01' -> '3'; None for a name that does not start with Z<number>-."""
    head, sep, _ = str(serial).partition("-")
    return head[1:] if sep and head[:1] == "Z" and head[1:].isnumeric() else None


def assert_single_run(payload):
    """Raise ValueError when an element of frames, publishes, grades, lessons, episodes or stalls belongs to another run or
    another zone than meta.run / meta.zone: a dict element with a different `run` or `zone`, or a robot serial or job id
    (frames, episodes, stalls) that names another zone. Entries of run_constants carry a `source` and are labelled context:
    they are not checked."""
    try:
        run, zone = payload["meta"]["run"], str(payload["meta"]["zone"])
    except (KeyError, TypeError) as e:
        raise ValueError("the payload has no meta.run / meta.zone to check against") from e

    def bad(where, what):
        raise ValueError(f"{where} holds {what}, but the export is run {run!r} zone {zone!r}")

    def check(where, e):
        if isinstance(e, dict):
            if "run" in e and e["run"] != run:
                bad(where, f"run {e['run']!r}")
            if "zone" in e and str(e["zone"]) != zone:
                bad(where, f"zone {e['zone']!r}")
            if "robot" in e and _serial_zone(e["robot"]) not in (None, zone):
                bad(where, f"robot {e['robot']!r}")
        elif isinstance(e, (list, tuple)):
            if where == "stalls" and e and _serial_zone(e[0]) not in (None, zone):
                bad(where, f"robot {e[0]!r}")
            if where == "frames" and len(e) > 3 and _serial_zone(str(e[3]).split("-o")[0]) not in (None, zone):
                bad(where, f"job {e[3]!r}")

    for key in ("publishes", "lessons", "episodes", "stalls"):
        for e in payload.get(key) or ():
            check(key, e)
    for key, rows in (payload.get("grades") or {}).items():
        for e in rows or ():
            check("grades." + key, e)
    for step in payload.get("frames") or ():
        for e in step:
            check("frames", e)


# ------------------------------------------------------------------------------------------------ assembly
def build_payload(run_dir, store_spec, zone, closed_loop=None, env_runner=None, log=print,
                  run_dir_arg=None, closed_loop_arg=None, benchmark=None, hotspot_file=None, closed_loop_summary=None,
                  lessons_long=None, sticky=None, dose_response=None, explorer=False):
    zone = str(zone)
    run_dir = Path(run_dir)
    truth = json.loads((run_dir / "truth.json").read_text())
    if zone not in truth["zones"]:
        raise ValueError(f"truth.json has no zone {zone}")
    ledger_p = run_dir / "emit_ledger.json"
    emit = json.loads(ledger_p.read_text()) if ledger_p.exists() else {}
    cfg = emit.get("config") or {}
    run = json.loads((run_dir / "costmap.json").read_text())["run"]
    steps = truth["steps"]
    t0_ts = epoch_of(cfg.get("t0") or emitter.DEFAULT_T0)
    seed = truth["zones"][zone]["seed"]
    floor = truth["zones"][zone]["floor_cells"]
    zrow = zone_ledger(emit, zone)
    expected = zrow.get("expected_messages")

    files = zone_files(run_dir, zone)
    if not files:
        raise ValueError(f"no zone{zone}-*.jsonl.gz files under {run_dir}")
    messages = hotspot.read_messages(str(run_dir / f"zone{zone}-*.jsonl.gz"))
    st = store_mod.open_store(store_spec, run)
    try:
        episode_rows = st.select("stuck_episodes", {"run": run, "zone": zone})
        stalls = hotspot.extract_stalls(messages, run)
        hotspot.annotate_episodes(stalls, episode_rows)
        check = ingest_check(st, run, files)
        publishes = build_publishes(st, run, zone, floor, t0_ts)
        grades = build_grades(st, run, zone, publishes, t0_ts)
        lessons = build_lessons(st, run, t0_ts, zone=zone)
        change_rows = [(r["robot"], r["ts"]) for r in st.select("transitions", {"run": run}) if str(r.get("zone")) == zone]
        changes = set(change_rows)
        if len(changes) != len(change_rows):  # a set would undercount the transition rows; the detector writes one per message
            raise ValueError(f"run {run} zone {zone}: {len(change_rows) - len(changes)} duplicate (robot, ts) transition rows")
        verdicts = stuck_verdicts(st, run)
        ledger_rows = st.select("ingest_ledger", {"run": run})
        kept = kept_constant(st, run, ledger_rows, len(truth["zones"]))
    finally:
        st.close()

    rate = ingest_rate(ledger_rows)
    bench = benchmark_constant(benchmark)

    wm = with_map_job(closed_loop, zone, dict(seed_base=truth["seed_base"], steps=steps, env_id=truth["env_id"],
                                              policy=cfg.get("policy", emitter.DEFAULT_POLICY),
                                              disturb=truth["disturb"], recovery=cfg.get("recovery"),
                                              t0=cfg.get("t0") or emitter.DEFAULT_T0), log) if closed_loop else None
    if closed_loop and wm is None:
        closed_loop = None
    job = dict(env_id=truth["env_id"], steps=steps, seed=seed, zone=zone, run=wm[0] if wm else None)
    env = (env_runner or run_env_worker)(job)
    grid = env["grid"]
    robots = [dict(serial=s, kind=k) for s, k in sorted(env["kinds"].items())]

    accepted_keys = set()
    series, totals = replay_extractor(files, t0_ts, steps, expected, zrow.get("bytes_compressed"), accepted_out=accepted_keys)
    verify_check(totals, check)
    # a transition is written at the ts of the message that changed the state (also from end_all), so every one is an accepted
    # message; counting only those keeps n_changes + n_repeats = accepted by construction
    counted = changes & accepted_keys
    n_changes = len(counted)
    by_step = [0] * steps
    for _, ts in counted:
        by_step[min(max((ts - t0_ts) // STEP_SECONDS, 0), steps - 1)] += 1
    if kept is not None:
        kept = dict(kept, n_changes=n_changes, n_repeats=totals["accepted"] - n_changes,
                    changes_by_step=[sum(by_step[:i + 1]) for i in range(steps)])
    run_constants = dict(
        ingest_msgs_per_s=None if rate is None else dict(value=rate, source="store:ingest_ledger", formula=INGEST_RATE_FORMULA),
        benchmark_msgs_per_s=bench,
        kept=kept,
        hotspot=hotspot_constant(hotspot_file, run, zone, len(floor)),
        closed_loop=closed_loop_constant(closed_loop_summary),
        audit=audit_constant(zrow, totals, zone),
        header=header_constant(emit, zrow, totals, zone),
        speed=speed_constant(bench, zrow, steps, zone),
        lessons_long=lessons_long_constant(lessons_long),
        worth=worth_constant(sticky),
        dose_response=dose_response_constant(dose_response),
        explorer=explorer_constant() if explorer else None)
    if check is not None:
        cov = ledger.coverage(check["messages_accepted"], expected)
        check = dict(check, coverage=None if cov is None else round(cov, 6))
    frames = build_frames(messages, robots, t0_ts, steps, episode_rows, stalls, grid)

    payload = dict(
        meta=dict(run=run, zone=zone, env_id=truth["env_id"], steps=steps, step_seconds=STEP_SECONDS, t0_ts=t0_ts,
                  seed=seed, disturb=truth["disturb"], policy=cfg.get("policy"), recovery=cfg.get("recovery"),
                  schema=SCHEMA, state_display={raw: live_state.display_state(raw) for raw in STATES},
                  source=dict(run_dir=run_dir_arg if run_dir_arg is not None else str(run_dir),
                              store=store_spec if store_spec is not None else None,
                              closed_loop=closed_loop_arg if closed_loop_arg is not None else closed_loop,
                              costmap=posixpath.join((run_dir_arg if run_dir_arg is not None else str(run_dir)).replace(os.sep, "/"),
                                                     "costmap.json"),
                              demo_noise=bool(cfg.get("demo_noise")),
                              injected_noise=(emit.get("total") or {}).get("injected_noise"))),
        grid=grid, robots=robots, frames=frames,
        obstacles=[dict(kind="floor", cell=c, p=floor[c], hidden_from_analyser=True) for c in sorted(floor)],
        extractor=dict(series=series, totals=totals, check=check),
        publishes=publishes, grades=grades, lessons=lessons, run_constants=run_constants,
        episodes=build_episodes(episode_rows, zone, t0_ts, verdicts=verdicts),
        stalls=[[s["robot"], s["cell"], (s["start"] - t0_ts) // STEP_SECONDS, (s["end"] - t0_ts) // STEP_SECONDS,
                 bool(hotspot.counted(s))] for s in stalls if s["zone"] == zone])
    if wm:
        cfg_wm, info = wm
        wm_msgs = []
        for line in env["lines"]:
            m, reason = parse_line(line)
            if m is None:
                raise ValueError(f"the with_map re-simulation emitted an unparsable line ({reason})")
            wm_msgs.append(m)
        wm_frames, wm_rows, _ = derive_layer(wm_msgs, robots, t0_ts, steps, grid, run)
        payload["with_map"] = dict(arm=info["arm"], alpha=info["alpha"], map_path=info["map_path"],
                                   map_generated_at=info["map_generated_at"], map_tag=info["map_tag"],
                                   deliveries=env["deliveries"], pick_rate=round(env["pick_rate"], 2), frames=wm_frames,
                                   episodes=build_episodes(wm_rows, zone, t0_ts), note=WITH_MAP_NOTE)
    assert_single_run(payload)
    return payload


def write_data_js(payload, out, max_bytes=MAX_BYTES):
    """Atomic write of `window.REPLAY = <compact json>;\\n`; raises (nothing written) above max_bytes or when
    assert_single_run does."""
    assert_single_run(payload)
    body = PREFIX + json.dumps(payload, allow_nan=False, separators=(",", ":")) + ";\n"
    data = body.encode("utf-8")
    if len(data) > max_bytes:
        raise ValueError(f"replay payload is {len(data)} bytes, over the {max_bytes} byte cap")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, out)
    return len(data)


def read_data_js(path):
    text = Path(path).read_text(encoding="utf-8")
    if not text.startswith(PREFIX):
        raise ValueError(f"{path} does not start with {PREFIX!r}")
    return json.loads(text[len(PREFIX):].rstrip().removesuffix(";"))


def refresh_constants(out, lessons_long_path=None, dose_response=None, max_bytes=MAX_BYTES, explorer=False):
    """Rewrite only the run_constants keys whose source was given (lessons_long, dose_response, explorer) of an existing data.js by text
    splice; a key that is not in the file yet is appended to run_constants. Returns the new byte size."""
    out = Path(out)
    if not out.is_file():
        raise ValueError(f"--out {out} does not exist (refresh mode never creates a file)")
    new_values = {}
    if lessons_long_path is not None:
        new_values["lessons_long"] = lessons_long_constant(lessons_long_path)
    if dose_response:
        new_values["dose_response"] = dose_response_constant(dose_response)
    if explorer:
        new_values["explorer"] = explorer_constant()
    if not new_values:
        raise ValueError("nothing to refresh: give --lessons-long, --dose-response and/or --explorer")
    text = out.read_text(encoding="utf-8")
    if not text.startswith(PREFIX):
        raise ValueError(f"{out} does not start with {PREFIX!r}")
    before = json.loads(text[len(PREFIX):].rstrip().removesuffix(";"))
    new_text = text
    for name, value in new_values.items():
        enc = json.dumps(value, separators=(",", ":"), allow_nan=False)
        key = f'"{name}":'
        if name in before["run_constants"]:
            if new_text.count(key) != 1:
                raise ValueError(f'{out}: {key} occurs {new_text.count(key)} times, expected exactly once')
            start = new_text.index(key) + len(key)
            _, end = json.JSONDecoder().raw_decode(new_text, start)
            new_text = new_text[:start] + enc + new_text[end:]
        else:
            rc_key = '"run_constants":'
            if new_text.count(rc_key) != 1:
                raise ValueError(f'{out}: {rc_key} occurs {new_text.count(rc_key)} times, expected exactly once')
            rc_start = new_text.index(rc_key) + len(rc_key)
            _, rc_end = json.JSONDecoder().raw_decode(new_text, rc_start)
            sep = "" if new_text[rc_end - 2] == "{" else ","
            new_text = new_text[:rc_end - 1] + f'{sep}{key}{enc}' + new_text[rc_end - 1:]
    after = json.loads(new_text[len(PREFIX):].rstrip().removesuffix(";"))
    for name in new_values:
        if after["run_constants"].get(name) != new_values[name]:
            raise ValueError(f"refresh did not write run_constants.{name} as computed")
        before["run_constants"].pop(name, None)
        after["run_constants"].pop(name)
    if before != after:
        raise ValueError(f"refresh would change keys other than run_constants.{'/'.join(new_values)}")
    data = new_text.encode("utf-8")
    if len(data) > max_bytes:
        raise ValueError(f"replay payload is {len(data)} bytes, over the {max_bytes} byte cap")
    tmp = out.with_name(out.name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, out)
    return len(data)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--refresh-constants-only", action="store_true",
                   help="rewrite only the run_constants keys given by --lessons-long, --dose-response and/or --explorer of the existing --out (no re-simulation)")
    p.add_argument("--run-dir", default=None)
    p.add_argument("--store", default=None, help="jsonl:<dir> or clickhouse://host[:port]/db (read only)")
    p.add_argument("--zone", default="0")
    p.add_argument("--out", required=True)
    p.add_argument("--closed-loop", default=None, metavar="DIR", help="results/closed_loop: adds the with_map layer")
    p.add_argument("--benchmark", default=None, metavar="PATH", help="results/fleet/benchmark.json: run_constants.benchmark_msgs_per_s")
    p.add_argument("--hotspot", default=None, metavar="PATH", help="results/fleet/hotspot_<tag>.json of this run: run_constants.hotspot")
    p.add_argument("--closed-loop-summary", default=None, metavar="PATH",
                   help="results/closed_loop_sticky/summary.json: run_constants.closed_loop")
    p.add_argument("--lessons-long", default=None, metavar="PATH",
                   help="results/fleet/hotspot_s8e-long-w0.5.json: run_constants.lessons_long (context from a longer run)")
    p.add_argument("--dose-response", action="append", default=None, metavar="LABEL=PATH",
                   help="repeatable: a closed-loop summary.json and its label, in page order: run_constants.dose_response")
    p.add_argument("--explorer", action="store_true",
                   help="run_constants.explorer: the five closed-loop summaries and the density and breakdown sweeps under results/ "
                        "(resolved from the repo root); without it a full export writes explorer = null and a refresh leaves the key alone")
    for arm in WORTH_ARMS:
        p.add_argument("--sticky-" + arm.replace("_", "-"), default=None, metavar="PATH",
                       help=f"results/closed_loop_sticky/{arm}/*.json (one row file): a bar of run_constants.worth")
    a = p.parse_args(argv)
    if a.refresh_constants_only:
        if a.lessons_long is None and not a.dose_response and not a.explorer:
            p.error("--refresh-constants-only requires --lessons-long, --dose-response and/or --explorer")
        try:
            n = refresh_constants(a.out, a.lessons_long, a.dose_response, explorer=a.explorer)
        except (ValueError, OSError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        names = [k for k, v in (("lessons_long", a.lessons_long), ("dose_response", a.dose_response), ("explorer", a.explorer)) if v]
        print(f"refreshed run_constants.{' and '.join(names)}, {n} bytes -> {a.out}")
        return 0
    if a.run_dir is None or a.store is None:
        p.error("--run-dir and --store are required (unless --refresh-constants-only)")
    try:
        payload = build_payload(a.run_dir, a.store, a.zone, a.closed_loop, run_dir_arg=a.run_dir,
                                closed_loop_arg=a.closed_loop, benchmark=a.benchmark, hotspot_file=a.hotspot,
                                closed_loop_summary=a.closed_loop_summary, lessons_long=a.lessons_long, dose_response=a.dose_response, explorer=a.explorer,
                                sticky={arm: getattr(a, "sticky_" + arm) for arm in WORTH_ARMS})
        n = write_data_js(payload, a.out)
    except (ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    pubs = ", ".join(f"{q['t']}: {q['precision_at_20']}" for q in payload["publishes"])
    print(f"replay zone {a.zone}: {payload['meta']['steps']} steps x {len(payload['robots'])} robots, "
          f"{len(payload['publishes'])} publishes (precision@20 {pubs}), {len(payload['episodes'])} episodes, "
          f"with_map {'yes' if 'with_map' in payload else 'no'}, {n} bytes -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""S16B: MoRoOp dispatcher events against our stuck episodes, and the authors' cleaning against our drops
(docs/LITERATURE.md Part 9 sections 3, 4, 5).

Usage: python fleet/moroop_dispatch.py --raw DIR --label results/fleet/moroop_label-sb.json --out PATH [--smoke]
--raw defaults to fleet/data/moroop/raw (moroop.DEFAULT_RAW, resolved against the repository root). --smoke = shift index 1
(2026_07_27_evening) only. Writes only --out. The output is deterministic: no wall-clock value, no absolute path (raw and
label are recorded as given, plus the label file's sha256), keys sorted. Nothing here claims who made a call: the word for
an unexplained pause or resume is "external call", and that is all the table can say.

STUCK EPISODES. Per shift k, every entry of shifts[str(k)].episodes_ge_30s.list and .false_alarms.list of the label file
(the -sb detector's stuck runs), each [start, start + duration_s) with start an ISO UTC string; every episode carries the
name of the list it came from. The 3,245 s episode (shift 2026_07_30_morning, false_alarms, start 2026-07-30T06:16:31Z) is
looked up by those values, asserted to exist, and written as `intervention_episode`.

EVENTS (dispatch_events, ordered by (created_at, table order)): the six kinds in EVENT_KINDS. Class:
  "dispatcher refused" every operation_start_denied, and every auto-pause. READING: a pause carries no operation, so an
      auto-pause is a pause whose immediately previous dispatch event of ANY type in the same shift is an
      operation_start_denied with retry_count == max_retries (both ints). Part 9 says "of the same operation"; with no
      operation on the pause that condition cannot be tested and is dropped (declared deviation).
  "external call" every other pause and every resume, except a resume before the shift's first operation_started event
      (none if the shift has no such event), which is "shift start".
  "neither" operation_dispatcher_started / _stopped and operation_failed.
Per event: in_episode = episode with start <= ts < end; near_before = episode with start - 120 <= ts < start;
near_after = episode with end <= ts <= end + 120 (nearest boundary when several; each is null or {list, start,
duration_s, delta_s}). intervention is true iff class == "external call" and any of the three is set; no other class is ever
an intervention. Resumes add offset_s from the shift start (shift start = created_at of the first robot_state_cleaned row of
the shift) and pause_precedes (a pause earlier in the shift's table since the previous resume, or since the start of the
table). The 11-resume vs 3-pause mismatch is reported (resumes_vs_pauses), not explained.
Per-kind table: count, overlap_episode (in_episode set), near_episode (near_before or near_after set and not inside),
in_paused_or_non_autonomous (nearest robot_state_cleaned row at or before ts has moroop.is_paused true; events with no such
row are counted in no_row_before and not in the column).

CLEANING on robot_state_raw. authors_removed = raw ids absent from robot_state_cleaned. A raw id is a RULE DROP when, per
raw row, (i) the adapter's conversion (convert_shift on that single row, with empty operations and jobs: the order id plays
no part in any rule) or encode_line raises -> "convert:<ExceptionType>" (an addition to Part 9's reasons), (ii)
parse_line(encode_line(msg)) rejects it -> the parser's reason, (iii) its diagnostics column is unparseable the way
moroop._diag_levels counts rows_unparseable -> "diagnostics_unparseable". COLLAPSE DROPS (moroop.collapse_seconds on the full
raw table of the shift, ids in `dropped`) are a separate column and never part of both_drop / ours_only. Partition of
authors_removed + rule drops: both_drop, authors_only, ours_only. Per set: state, operating_mode, diagnostics max level
(ROS order Ok < Warning < Error < Stale, others last) counts; authors_only also pos_x, pos_y, velocity_x, velocity_y,
velocity_omega min / max over finite numbers and the count of None / non-finite values.

VERDICTS (Part 9 section 5, integer arithmetic, pooled over the shifts run): cleaning "match" if both_drop / authors_removed
>= 0.90, "we keep theirs" if authors_only / authors_removed > 0.10, else "mixed" (authors_removed == 0 -> "mixed").
dispatcher "marks the intervention" if any "external call" event is in or within +-120 s of the intervention episode, else
"adds nothing" if no pause or resume of any class is in or within +-120 s of any stuck episode, else "mixed". The
dispatcher verdict looks at the intervention episode only if its shift is in scope (under --smoke it is not, so a smoke
verdict is a smoke verdict).
"""
import argparse
import bisect
import calendar
import collections
import hashlib
import json
import math
import sys
import time
from pathlib import Path

FLEET = Path(__file__).resolve().parent
REPO = FLEET.parent
for _p in (FLEET, REPO / "src", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from adapters import moroop  # noqa: E402
from fleet_analyser.parse import parse_line  # noqa: E402

SCHEMA = "moroop-dispatch/1"
NEAR_S = 120
EVENT_KINDS = ("operation_start_denied", "operation_dispatcher_paused", "operation_dispatcher_resumed",
               "operation_dispatcher_started", "operation_dispatcher_stopped", "operation_failed")
DENIED, PAUSED, RESUMED = EVENT_KINDS[0], EVENT_KINDS[1], EVENT_KINDS[2]
STARTED_OP = "operation_started"
EPISODE_LISTS = ("episodes_ge_30s", "false_alarms")
SMOKE_SHIFT = 1
INTERVENTION_SHIFT, INTERVENTION_START, INTERVENTION_DURATION = "2026_07_30_morning", "2026-07-30T06:16:31Z", 3245
LEVEL_ORDER = {"Ok": 0, "Warning": 1, "Error": 2, "Stale": 3}
RANGE_FIELDS = ("pos_x", "pos_y", "velocity_x", "velocity_y", "velocity_omega")
DEFAULT_RAW = moroop.DEFAULT_RAW
DEFAULT_LABEL = REPO / "results" / "fleet" / "moroop_label-sb.json"
DEFAULT_OUT = REPO / "results" / "fleet" / "moroop_dispatch.json"


# ------------------------------------------------------------------------------------------------ episodes
def epoch_of(iso_text):
    return calendar.timegm(time.strptime(iso_text, "%Y-%m-%dT%H:%M:%SZ"))


def shift_episodes(label, k):
    """Stuck episodes of shift k from both lists, in list order, times in epoch microseconds."""
    block = label["shifts"][str(k)]
    out = []
    for lst in EPISODE_LISTS:
        for e in block[lst]["list"]:
            start = epoch_of(e["start"]) * 1_000_000
            out.append(dict(list=lst, start=e["start"], duration_s=e["duration_s"], start_us=start,
                            end_us=start + int(round(e["duration_s"] * 1_000_000))))
    return out


def find_intervention(label):
    """The 3,245 s episode, looked up by its values; asserts it exists exactly once."""
    name = label["src"]["shifts"].index(INTERVENTION_SHIFT)
    hits = [e for e in label["shifts"][str(name)]["false_alarms"]["list"]
            if e["start"] == INTERVENTION_START and e["duration_s"] == INTERVENTION_DURATION]
    assert len(hits) == 1, f"intervention episode {INTERVENTION_START} {INTERVENTION_DURATION} s not found exactly once"
    return dict(shift=INTERVENTION_SHIFT, shift_index=name, list="false_alarms", start=INTERVENTION_START,
                duration_s=INTERVENTION_DURATION)


def _ref(ep, delta_us):
    return dict(list=ep["list"], start=ep["start"], duration_s=ep["duration_s"], delta_s=round(delta_us / 1e6, 6))


def locate(ts_us, episodes):
    """(in_episode, near_before, near_after): each None or an episode reference. Nearest boundary wins, ties by start."""
    near = NEAR_S * 1_000_000
    inside, before, after = [], [], []
    for ep in episodes:
        if ep["start_us"] <= ts_us < ep["end_us"]:
            inside.append((ts_us - ep["start_us"], ep["start_us"], ep))
        if ep["start_us"] - near <= ts_us < ep["start_us"]:
            before.append((ep["start_us"] - ts_us, ep["start_us"], ep))
        if ep["end_us"] <= ts_us <= ep["end_us"] + near:
            after.append((ts_us - ep["end_us"], ep["start_us"], ep))

    def pick(c):
        if not c:
            return None
        d, _, ep = min(c, key=lambda t: (t[0], t[1]))
        return _ref(ep, d)
    return pick(inside), pick(before), pick(after)


def touches(ts_us, ep):
    """True when ts is inside the episode or within +-NEAR_S of it (same windows as locate)."""
    near = NEAR_S * 1_000_000
    return ep["start_us"] - near <= ts_us <= ep["end_us"] + near


# ------------------------------------------------------------------------------------------------ events
def _meta(row):
    try:
        m = json.loads(row["meta_data"])
    except (TypeError, ValueError):
        return {}
    return m if isinstance(m, dict) else {}


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def classify_events(rows, operations, cleaned, episodes):
    """Event dicts for the six kinds of one shift, plus the shift start and the first operation_started (microseconds)."""
    ordered = [r for _, r in sorted(enumerate(rows), key=lambda t: (t[1]["created_at"], t[0]))]
    job_of = {o["id"]: o.get("job_id") for o in operations}
    cl_ts = sorted(r["created_at"] for r in cleaned)
    cl_rows = sorted(cleaned, key=lambda r: r["created_at"])
    shift_start = cl_ts[0] if cl_ts else None
    starts = [r["created_at"] for r in ordered if r["event_type"] == STARTED_OP]
    first_started = min(starts) if starts else None
    events, prev, pause_seen = [], None, False
    for r in ordered:
        kind = r["event_type"]
        if kind in EVENT_KINDS:
            ts = r["created_at"]
            meta = _meta(r)
            retry, mx = meta.get("retry_count"), meta.get("max_retries")
            auto = bool(kind == PAUSED and prev is not None and prev["event_type"] == DENIED
                        and _is_int(_meta(prev).get("retry_count")) and _is_int(_meta(prev).get("max_retries"))
                        and _meta(prev)["retry_count"] == _meta(prev)["max_retries"])
            if kind == DENIED or auto:
                cls = "dispatcher refused"
            elif kind in (PAUSED, RESUMED):
                cls = "external call"
                if kind == RESUMED and first_started is not None and ts < first_started:
                    cls = "shift start"
            else:
                cls = "neither"
            inside, before, after = locate(ts, episodes)
            i = bisect.bisect_right(cl_ts, ts) - 1
            paused = moroop.is_paused(cl_rows[i]) if i >= 0 else None
            ev = dict(ts=moroop.iso(ts // 1_000_000), ts_us=ts, kind=kind, operation_id=r.get("operation_id"),
                      job_id=job_of.get(r.get("operation_id")), reasoning=meta.get("reasoning"), retry_count=retry,
                      max_retries=mx, termination_reason=meta.get("termination_reason"), auto_pause=auto, cls=cls,
                      in_episode=inside, near_before=before, near_after=after,
                      intervention=bool(cls == "external call" and (inside or before or after)),
                      in_paused_or_non_autonomous=paused)
            if kind == RESUMED:
                ev["offset_s"] = None if shift_start is None else round((ts - shift_start) / 1e6, 6)
                ev["pause_precedes"] = pause_seen
                pause_seen = False
            if kind == PAUSED:
                pause_seen = True
            events.append(ev)
        prev = r
    return events, shift_start, first_started


def per_kind_table(events):
    t = {k: dict(count=0, overlap_episode=0, near_episode=0, in_paused_or_non_autonomous=0, no_row_before=0)
         for k in EVENT_KINDS}
    for e in events:
        row = t[e["kind"]]
        row["count"] += 1
        row["overlap_episode"] += e["in_episode"] is not None
        row["near_episode"] += e["in_episode"] is None and (e["near_before"] is not None or e["near_after"] is not None)
        row["in_paused_or_non_autonomous"] += e["in_paused_or_non_autonomous"] is True
        row["no_row_before"] += e["in_paused_or_non_autonomous"] is None
    return t


def add_tables(a, b):
    return {k: {f: a[k][f] + b[k][f] for f in a[k]} for k in a}


# ------------------------------------------------------------------------------------------------ cleaning
def rule_drop_reason(row):
    """None when the raw row passes every rule of our path, else the reason (see module docstring)."""
    try:
        messages, _, _ = moroop.convert_shift([row], [], [])
        line = moroop.encode_line(messages[0])
    except Exception as exc:  # any failure of the adapter on this row is a rule drop
        return f"convert:{type(exc).__name__}"
    msg, reason = parse_line(line)
    if msg is None:
        return reason
    if moroop._diag_levels([row])["rows_unparseable"]:
        return "diagnostics_unparseable"
    return None


def diag_max_level(row):
    try:
        statuses = json.loads(row["diagnostics"])["statuses"]
        levels = [str(s.get("level")) for s in statuses]
    except (TypeError, ValueError, KeyError, AttributeError):
        return "unparseable"
    if not levels:
        return "none"
    return max(levels, key=lambda lv: (LEVEL_ORDER.get(lv, len(LEVEL_ORDER)), lv))


def _finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def set_stats(rows, collapse_ids, ranges=False):
    d = dict(ids=len(rows), collapse_drops=sum(1 for r in rows if r["id"] in collapse_ids),
             state=_sorted_count(r["state"] for r in rows),
             operating_mode=_sorted_count(r["operating_mode"] for r in rows),
             diagnostics_max_level=_sorted_count(diag_max_level(r) for r in rows))
    if ranges:
        rng = {}
        for f in RANGE_FIELDS:
            vals = [r[f] for r in rows if _finite(r[f])]
            rng[f] = dict(min=min(vals) if vals else None, max=max(vals) if vals else None,
                          none_or_nonfinite=len(rows) - len(vals))
        d["ranges"] = rng
    return d


def _sorted_count(it):
    return dict(sorted(collections.Counter(str(x) for x in it).items()))


def clean_shift(raw_rows, cleaned_rows):
    """Cleaning block of one shift; also carries the rule-drop reasons per set."""
    cleaned_ids = {r["id"] for r in cleaned_rows}
    raw_ids = {r["id"] for r in raw_rows}
    reasons = {}
    for r in raw_rows:
        why = rule_drop_reason(r)
        if why is not None:
            reasons[r["id"]] = why
    _, dropped = moroop.collapse_seconds(raw_rows)
    collapse_ids = {r["id"] for r in dropped}
    removed = [r for r in raw_rows if r["id"] not in cleaned_ids]
    sets = dict(both_drop=[], authors_only=[], ours_only=[])
    for r in raw_rows:
        gone, rule = r["id"] not in cleaned_ids, r["id"] in reasons
        if gone and rule:
            sets["both_drop"].append(r)
        elif gone:
            sets["authors_only"].append(r)
        elif rule:
            sets["ours_only"].append(r)
    out = dict(raw_rows=len(raw_rows), cleaned_rows=len(cleaned_rows), cleaned_ids_not_in_raw=len(cleaned_ids - raw_ids),
               authors_removed=len(removed), rule_drops=len(reasons),
               rule_drop_reasons=_sorted_count(reasons.values()), collapse_drops=len(collapse_ids),
               collapse_drops_in_no_set=sum(1 for r in raw_rows if r["id"] in collapse_ids
                                            and r["id"] in cleaned_ids and r["id"] not in reasons))
    for name, rows in sets.items():
        out[name] = set_stats(rows, collapse_ids, ranges=(name == "authors_only"))
    return out


def _merge_counts(a, b):
    out = dict(a)
    for k, v in b.items():
        out[k] = out.get(k, 0) + v
    return dict(sorted(out.items()))


def _merge_set(a, b):
    out = dict(ids=a["ids"] + b["ids"], collapse_drops=a["collapse_drops"] + b["collapse_drops"])
    for f in ("state", "operating_mode", "diagnostics_max_level"):
        out[f] = _merge_counts(a[f], b[f])
    if "ranges" in a:
        out["ranges"] = {}
        for f in RANGE_FIELDS:
            x, y = a["ranges"][f], b["ranges"][f]
            mins = [v for v in (x["min"], y["min"]) if v is not None]
            maxs = [v for v in (x["max"], y["max"]) if v is not None]
            out["ranges"][f] = dict(min=min(mins) if mins else None, max=max(maxs) if maxs else None,
                                    none_or_nonfinite=x["none_or_nonfinite"] + y["none_or_nonfinite"])
    return out


def pool_cleaning(blocks):
    first, rest = blocks[0], blocks[1:]
    out = json.loads(json.dumps(first))
    for b in rest:
        for f in ("raw_rows", "cleaned_rows", "cleaned_ids_not_in_raw", "authors_removed", "rule_drops", "collapse_drops",
                  "collapse_drops_in_no_set"):
            out[f] += b[f]
        out["rule_drop_reasons"] = _merge_counts(out["rule_drop_reasons"], b["rule_drop_reasons"])
        for s in ("both_drop", "authors_only", "ours_only"):
            out[s] = _merge_set(out[s], b[s])
    return out


# ------------------------------------------------------------------------------------------------ verdicts
def cleaning_verdict(both_drop, authors_only, authors_removed):
    """Integer comparisons of the Part 9 section 5 thresholds (no float rounding)."""
    if authors_removed <= 0:
        return "mixed"
    if both_drop * 10 >= authors_removed * 9:
        return "match"
    if authors_only * 10 > authors_removed:
        return "we keep theirs"
    return "mixed"


def dispatcher_verdict(events, intervention_episodes):
    """events: {shift name: [event]}; intervention_episodes: [(shift name, episode dict)] in scope."""
    for shift, ep in intervention_episodes:
        if any(e["cls"] == "external call" and touches(e["ts_us"], ep) for e in events.get(shift, [])):
            return "marks the intervention"
    anything = any(e["kind"] in (PAUSED, RESUMED) and (e["in_episode"] or e["near_before"] or e["near_after"])
                   for evs in events.values() for e in evs)
    return "mixed" if anything else "adds nothing"


def page_sentence(removed, raw_rows):
    pct = 100.0 * removed / raw_rows if raw_rows else 0.0
    return (f"No row of the authors' cleaned table was rejected by our parser; the authors had already removed "
            f"{removed:,} of {raw_rows:,} raw rows ({pct:.1f} %)")


# ------------------------------------------------------------------------------------------------ run
def sha256_file(path):
    return moroop.sha256_file(path)


def analyse_shift(name, tables, episodes):
    cleaned = tables["robot_state_cleaned"]
    events, shift_start, first_started = classify_events(tables["dispatch_events"], tables["operations"], cleaned, episodes)
    return dict(
        shift=name,
        stuck_episodes=[dict(list=e["list"], start=e["start"], duration_s=e["duration_s"]) for e in episodes],
        shift_start=None if shift_start is None else moroop.iso(shift_start // 1_000_000),
        first_operation_started=None if first_started is None else moroop.iso(first_started // 1_000_000),
        events=events, per_kind=per_kind_table(events),
        classes=_sorted_count(e["cls"] for e in events),
        interventions=sum(e["intervention"] for e in events),
        auto_pauses=sum(e["auto_pause"] for e in events),
        cleaning=clean_shift(tables["robot_state_raw"], cleaned))


def analyse(label, label_sha, raw_arg, shift_indices, loader, label_path=None):
    names = label["src"]["shifts"]
    inter = find_intervention(label)
    shifts, episodes_by = [], {}
    for k in shift_indices:
        eps = shift_episodes(label, k)
        episodes_by[names[k]] = eps
        res = analyse_shift(names[k], loader(raw_arg, names[k]), eps)
        res["index"] = k
        shifts.append(res)
    events = {s["shift"]: s["events"] for s in shifts}
    inter_eps = [(s, e) for s, eps in episodes_by.items() for e in eps
                 if s == inter["shift"] and e["list"] == inter["list"] and e["start"] == inter["start"]
                 and e["duration_s"] == inter["duration_s"]]
    pooled_kind = shifts[0]["per_kind"]
    for s in shifts[1:]:
        pooled_kind = add_tables(pooled_kind, s["per_kind"])
    resumes = [e for s in shifts for e in s["events"] if e["kind"] == RESUMED]
    pooled_clean = pool_cleaning([s["cleaning"] for s in shifts])
    verdicts = dict(
        dispatcher=dispatcher_verdict(events, inter_eps),
        cleaning=cleaning_verdict(pooled_clean["both_drop"]["ids"], pooled_clean["authors_only"]["ids"],
                                  pooled_clean["authors_removed"]))
    return dict(
        schema=SCHEMA, scope="smoke" if list(shift_indices) == [SMOKE_SHIFT] else "full",
        raw=str(raw_arg), label=dict(path=str(label_path) if label_path else None, sha256=label_sha),
        shifts_run=[names[k] for k in shift_indices],
        intervention_episode=inter, intervention_episode_in_scope=bool(inter_eps),
        pooled=dict(
            per_kind=pooled_kind,
            classes=_sorted_count(e["cls"] for s in shifts for e in s["events"]),
            interventions=sum(s["interventions"] for s in shifts),
            auto_pauses=sum(s["auto_pauses"] for s in shifts),
            resumes_vs_pauses=dict(
                resumes=len(resumes), pauses=pooled_kind[PAUSED]["count"],
                resumes_with_pause_precedes=sum(1 for e in resumes if e["pause_precedes"]),
                resumes_without_pause_precedes=sum(1 for e in resumes if not e["pause_precedes"])),
            cleaning=pooled_clean),
        shifts=shifts, verdicts=verdicts,
        page_sentence=page_sentence(pooled_clean["authors_removed"], pooled_clean["raw_rows"]),
        page_sentence_holds=pooled_clean["ours_only"]["ids"] == 0 and pooled_clean["cleaned_ids_not_in_raw"] == 0)


def dump(result):
    return json.dumps(result, indent=1, sort_keys=True) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="S16B MoRoOp dispatcher events vs stuck episodes; the authors' cleaning")
    ap.add_argument("--raw", default=str(DEFAULT_RAW))
    ap.add_argument("--label", default=str(DEFAULT_LABEL))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--smoke", action="store_true", help="shift index 1 (2026_07_27_evening) only")
    args = ap.parse_args(argv)
    t0 = time.time()
    label = json.loads(Path(args.label).read_text())
    idx = [SMOKE_SHIFT] if args.smoke else list(range(len(label["src"]["shifts"])))
    result = analyse(label, sha256_file(args.label), args.raw, idx, moroop.load_shift, label_path=args.label)
    Path(args.out).write_text(dump(result))
    print(f"moroop_dispatch: {len(idx)} shift(s) in {time.time() - t0:.1f} s -> {args.out}")
    print(f"dispatcher={result['verdicts']['dispatcher']} cleaning={result['verdicts']['cleaning']}")
    print(result["page_sentence"])
    return 0


if __name__ == "__main__":
    sys.exit(main())

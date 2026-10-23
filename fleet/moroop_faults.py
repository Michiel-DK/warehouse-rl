"""S16A: what the MoRoOp diagnostics Error statuses are doing next to the stuck episodes (docs/LITERATURE.md Part 9).

Usage: python fleet/moroop_faults.py [--raw DIR] [--jsonl-sf DIR] [--budget-dir DIR] [--label-sf PATH]
                                     [--jsonl-sb DIR] [--label-sb PATH] [--stations PATH] [--station-radius N] --out PATH

Read-only on the raw parquet files. The -sf messages (adapter --faults) carry only the qualifying Error statuses, so the
Warning / Stale / noise statuses are read from the raw diagnostics column here. Three tables and a verdict, one JSON
(sort_keys, indent 1, no wall clock, no absolute path):
  (a) faulted seconds per shift and pooled, split driving / not driving, per (name, message) family; a family with more
      than half its faulted seconds while driving refutes 'ERROR = stopped' for that family;
  (b) every stuck episode of -sf and of -sb (the Detector re-run over the jsonl zone files, matched to the label files),
      with the Error statuses active in it; a second that is both faulted and paused counts as paused in THIS table only;
  (c) every (level, name, message) over all non-Ok statuses with its class.
The verdict is the Part 9 section 5 rule over the -sb 'cause not identified' episodes. Seconds are the seconds a kept
message owns (next kept ts - ts, as convert_shift). The pure functions take plain dicts, no pyarrow. The public label for
these seconds is 'Robot reported a component error'; the detector's faulted_self label must not be quoted for MoRoOp.
"""
import argparse
import bisect
import glob
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
for _p in (str(HERE), str(REPO / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from adapters import moroop as mo  # noqa: E402

PUBLIC_LABEL = "Robot reported a component error"
NOISE_SOURCE = "diagnostic_updater FrequencyStatus, rank A, Part 9 section 2"
FAULT_SOURCE = "ours, rank B, Part 9 section 1"
CLASS_NOISE, CLASS_FAULT, CLASS_OTHER = "noise", "faulted by our rule", "unclassified"
VERDICTS = ("fault cause", "unknown stays unknown", "mixed")
N_NOTE = "n = 2: a description, not a rate"
EXPECT_SB_UNKNOWN = (2, 180)
INTERVENTION = ("2026-07-30T06:16:31Z", 3245)
FAMILY_NOTES = {
    "/Localization/Perception": "unclassified (disk usage warning)",
    "/Navigation/Navigation": "unclassified; cross-tab against paused (the manual intervention shows there)",
}
LIDAR_WORDS = ("Lidar: Waiting for scans", "Lidar: Calibrating")


# ------------------------------------------------------------------------------------------------ pure: records
def classify(name, message, level):
    """(class, source). 'noise' only for the one sourced entry."""
    if (name, message, level) in mo.NOISE:
        return CLASS_NOISE, NOISE_SOURCE
    if level == mo.FAULT_LEVEL:
        return CLASS_FAULT, FAULT_SOURCE
    return CLASS_OTHER, "none"


def shift_records(raw_rows):
    """One record per kept row (mo.collapse_seconds): ts, owned seconds, driving, paused, uptime, bad (unparseable
    diagnostics), statuses = distinct non-Ok (level, name, message) in status order, errors = distinct (name, message)
    of the qualifying Error statuses."""
    kept, _ = mo.collapse_seconds(sorted(raw_rows, key=lambda r: (r["created_at"], r.get("id", 0))))
    recs = []
    for i, r in enumerate(kept):
        ts = r["created_at"] // 1_000_000
        nxt = kept[i + 1]["created_at"] // 1_000_000 if i + 1 < len(kept) else ts
        sts = mo.status_list(r.get("diagnostics"))
        non_ok, errs = [], []
        for s in sts or []:
            name, message, level = mo.status_key(s)
            if level != "Ok" and (level, name, message) not in non_ok:
                non_ok.append((level, name, message))
            if mo.is_qualifying_error(s) and (name, message) not in errs:
                errs.append((name, message))
        recs.append(dict(ts=ts, owned=nxt - ts, driving=bool(mo.is_driving(r)), paused=bool(mo.is_paused(r)),
                         uptime=r.get("robot_uptime"), bad=sts is None, statuses=non_ok, errors=errs))
    return recs


def _share(a, b):
    return a / b if b else None


# ------------------------------------------------------------------------------------------------ pure: table (a)
def _family_rows(acc):
    rows = []
    for (name, message), v in sorted(acc.items()):
        ds = _share(v["driving_s"], v["faulted_s"])
        rows.append(dict(name=name, message=message, faulted_s=v["faulted_s"], driving_s=v["driving_s"], driving_share=ds,
                         refutes_error_equals_stopped=bool(ds is not None and ds > 0.5), faulted_paused_s=v["paused_s"]))
    return rows


def table_a(recs_by_shift):
    """Per shift and pooled faulted seconds. A record with two families counts its seconds for each family."""
    per_shift, pooled, pooled_fam = {}, dict(span_s=0, faulted_s=0, driving_s=0, paused_s=0), {}
    for k, recs in recs_by_shift.items():
        span = sum(r["owned"] for r in recs)
        a = dict(span_s=span, faulted_s=0, driving_s=0, paused_s=0)
        fam = {}
        for r in recs:
            if not r["errors"]:
                continue
            a["faulted_s"] += r["owned"]
            a["driving_s"] += r["owned"] if r["driving"] else 0
            a["paused_s"] += r["owned"] if r["paused"] else 0
            for f in r["errors"]:
                for d in (fam, pooled_fam):
                    v = d.setdefault(f, dict(faulted_s=0, driving_s=0, paused_s=0))
                    v["faulted_s"] += r["owned"]
                    v["driving_s"] += r["owned"] if r["driving"] else 0
                    v["paused_s"] += r["owned"] if r["paused"] else 0
        per_shift[str(k)] = dict(span_s=span, faulted_s=a["faulted_s"], faulted_driving_s=a["driving_s"],
                                 faulted_not_driving_s=a["faulted_s"] - a["driving_s"], faulted_paused_s=a["paused_s"],
                                 share_of_span=_share(a["faulted_s"], span), families=_family_rows(fam))
        for key in pooled:
            pooled[key] += a[key]
    return dict(
        per_shift=per_shift,
        pooled=dict(span_s=pooled["span_s"], faulted_s=pooled["faulted_s"], faulted_driving_s=pooled["driving_s"],
                    faulted_not_driving_s=pooled["faulted_s"] - pooled["driving_s"], faulted_paused_s=pooled["paused_s"],
                    driving_share=_share(pooled["driving_s"], pooled["faulted_s"]),
                    share_of_span=_share(pooled["faulted_s"], pooled["span_s"]), families=_family_rows(pooled_fam)),
        label=PUBLIC_LABEL)


def cross_check(pooled_faulted_s, bucket_seconds_by_shift):
    """Raw-derived faulted seconds vs the time budget's faulted bucket (which loses seconds to no_data). Both and the
    difference; no equality asserted."""
    if bucket_seconds_by_shift is None:
        return dict(available=False)
    bucket = sum(bucket_seconds_by_shift.values())
    return dict(available=True, faulted_seconds_from_raw=pooled_faulted_s, faulted_bucket_seconds=bucket,
                difference=pooled_faulted_s - bucket, equal=pooled_faulted_s == bucket,
                bucket_by_shift={str(k): v for k, v in sorted(bucket_seconds_by_shift.items())},
                note="the bucket loses seconds to no_data, which outranks faulted")


# ------------------------------------------------------------------------------------------------ pure: table (b)
def episode_rows(episodes, recs_by_shift):
    """episodes: dicts shift, start (epoch s), duration_s, cause. Adds the Error statuses active in each. Overlap of a
    record = [ts, ts + owned) against [start, start + duration). Faulted+paused seconds are paused here."""
    index = {k: [r["ts"] for r in recs] for k, recs in recs_by_shift.items()}
    out = []
    for e in sorted(episodes, key=lambda e: (e["shift"], e["start"])):
        recs = recs_by_shift[e["shift"]]
        s, d = e["start"], e["duration_s"]
        end = None if d is None else s + d
        any_s = nonpaused_s = paused_s = 0
        fam = {}
        if end is not None:
            for r in recs[max(0, bisect.bisect_right(index[e["shift"]], s) - 1):]:
                if r["ts"] >= end:
                    break
                ov = max(0, min(end, r["ts"] + r["owned"]) - max(s, r["ts"]))
                if not ov or not r["errors"]:
                    continue
                any_s += ov
                if r["paused"]:
                    paused_s += ov
                else:
                    nonpaused_s += ov
                for f in r["errors"]:
                    v = fam.setdefault(f, dict(seconds=0, paused_seconds=0))
                    v["paused_seconds" if r["paused"] else "seconds"] += ov
        out.append(dict(
            shift=e["shift"], start=mo.iso(s), duration_s=d, cause=e["cause"], resolution=e.get("resolution"),
            public_label=PUBLIC_LABEL if e["cause"] == "faulted_self" else None,
            statuses=[dict(name=n, message=m, seconds=v["seconds"], paused_seconds=v["paused_seconds"])
                      for (n, m), v in sorted(fam.items())],
            faulted_overlap_s=any_s, faulted_s=nonpaused_s, faulted_paused_s=paused_s,
            faulted_share=_share(nonpaused_s, d), faulted_overlap_share=_share(any_s, d)))
    return out


def verdict(overlap_s, duration_s, pooled_driving_s, pooled_faulted_s):
    """Part 9 section 5, exact integer arithmetic. overlap_s / duration_s: one entry per -sb 'cause not identified'
    episode (seconds overlapping a faulted status, episode seconds). 'fault cause': every episode overlaps for >= 50 % of
    its seconds AND <= 20 % of the pooled faulted seconds are while driving. 'unknown stays unknown': no episode overlaps
    at all. Otherwise 'mixed' (also for no episode)."""
    if not overlap_s or len(overlap_s) != len(duration_s):
        return "mixed"
    if all(o == 0 for o in overlap_s):
        return "unknown stays unknown"
    if all(duration_s[i] and 2 * overlap_s[i] >= duration_s[i] for i in range(len(overlap_s))) \
            and pooled_faulted_s > 0 and 5 * pooled_driving_s <= pooled_faulted_s:
        return "fault cause"
    return "mixed"


def reproduces(episodes, label_table):
    """None when the episodes' (episodes, seconds) per cause equal the label file's causes table, else a message."""
    got, want = {}, {}
    for e in episodes:
        if e["duration_s"] is not None:
            c = got.setdefault(e["cause"], [0, 0])
            c[0] += 1
            c[1] += e["duration_s"]
    for r in label_table:
        c = want.setdefault(r["cause"], [0, 0])
        c[0] += r["episodes"]
        c[1] += r["seconds"]
    return None if got == want else f"episodes per cause {got} != label file {want}"


# ------------------------------------------------------------------------------------------------ pure: table (c)
def table_c(recs_by_shift):
    acc = {}
    for k, recs in recs_by_shift.items():
        for r in recs:
            for key in r["statuses"]:
                v = acc.get(key)
                if v is None:
                    v = acc[key] = dict(status_rows=0, seconds=0, driving_s=0, paused_s=0,
                                        first_onset=dict(shift=k, time=mo.iso(r["ts"]), robot_uptime=r["uptime"]))
                v["status_rows"] += 1
                v["seconds"] += r["owned"]
                v["driving_s"] += r["owned"] if r["driving"] else 0
                v["paused_s"] += r["owned"] if r["paused"] else 0
    rows = []
    for (level, name, message), v in sorted(acc.items()):
        cls, src = classify(name, message, level)
        note = FAMILY_NOTES.get(name)
        if note is None and name.startswith("/Wheels/") and message in LIDAR_WORDS:
            note = "unclassified; robot_uptime at first onset is the column of interest"
        rows.append(dict(level=level, name=name, message=message, status_rows=v["status_rows"], seconds=v["seconds"],
                         driving_share=_share(v["driving_s"], v["seconds"]), paused_share=_share(v["paused_s"], v["seconds"]),
                         first_onset=v["first_onset"], **{"class": cls}, source=src, family_note=note))
    return rows


# ------------------------------------------------------------------------------------------------ episodes from jsonl
def rebuild_episodes(jsonl_dir, servicing, stations, radius):
    """The Detector's episodes over jsonl_dir/zone<k>-000.jsonl.gz, one shift per file, the way mo.analyse does."""
    tb = mo._tb()
    from fleet_analyser.hotspot import read_messages
    out, faulted_msgs = [], {}
    for k in range(len(mo.SHIFTS)):
        msgs = read_messages(str(Path(jsonl_dir) / f"zone{k}-000.jsonl.gz"))
        kept = tb.kept_messages(msgs)
        faulted_msgs[k] = sum(1 for m in kept if m.faulted)
        for e in tb.recompute_episodes(kept, stations if radius is not None else None, radius or 0,
                                       servicing[k] if radius is not None else None):
            out.append(dict(shift=k, start=e["start"], duration_s=e["duration_s"], cause=e["cause"] or "unknown",
                            resolution=e.get("resolution")))
    return out, faulted_msgs


def build_report(recs_by_shift, eps_sf, eps_sb, cross, uptime_column_present, sf_faulted_msgs=None):
    a = table_a(recs_by_shift)
    b_sf = episode_rows(eps_sf, recs_by_shift)
    b_sb = episode_rows(eps_sb, recs_by_shift)
    sf_by_start = {(r["shift"], r["start"]): r for r in b_sf}
    unknown = []
    for r in b_sb:
        if r["cause"] != "unknown":
            continue
        m = sf_by_start.get((r["shift"], r["start"]))
        unknown.append(dict(r, sf_match=None if m is None else dict(cause=m["cause"], duration_s=m["duration_s"],
                                                                    public_label=m["public_label"])))
    pooled = a["pooled"]
    word = verdict([r["faulted_overlap_s"] for r in unknown], [r["duration_s"] for r in unknown],
                   pooled["faulted_driving_s"], pooled["faulted_s"])
    refuted = [f"{f['name']} | {f['message']}" for f in pooled["families"] if f["refutes_error_equals_stopped"]]
    named = [r for r in b_sb if r["start"] == INTERVENTION[0] and r["duration_s"] == INTERVENTION[1]]
    named_sf = [r for r in b_sf if r["start"] == INTERVENTION[0]]
    return dict(
        public_label=PUBLIC_LABEL, verdict=word, verdict_sentence=N_NOTE,
        verdict_inputs=dict(
            rule="Part 9 section 5: 'fault cause' if every -sb 'cause not identified' episode overlaps a faulted status for "
                 ">= 50 % of its seconds AND <= 20 % of the pooled faulted seconds are while driving; 'unknown stays "
                 "unknown' if none overlaps at all; else 'mixed'. Overlap counts a faulted second whether or not the robot "
                 "was paused (table (b) faulted_overlap_s)",
            episodes=[dict(shift=r["shift"], start=r["start"], duration_s=r["duration_s"],
                           faulted_overlap_s=r["faulted_overlap_s"], faulted_overlap_share=r["faulted_overlap_share"])
                      for r in unknown],
            pooled_faulted_s=pooled["faulted_s"], pooled_faulted_driving_s=pooled["faulted_driving_s"],
            pooled_driving_share=pooled["driving_share"], families_refuting_error_equals_stopped=refuted),
        table_a=a, cross_check=cross,
        table_b=dict(sf=b_sf, sb=b_sb, sb_unknown=unknown,
                     paused_rule="a second that is both faulted and paused counts as paused here (faulted_paused_s, "
                                 "paused_seconds); the time budget's bucket order is unchanged",
                     shift6_intervention=dict(sb=named, sf=named_sf, start=INTERVENTION[0], duration_s=INTERVENTION[1])),
        table_c=table_c(recs_by_shift),
        robot_uptime_column=("present" if uptime_column_present else "absent"),
        jsonl_sf_faulted_messages=sf_faulted_msgs)


# ------------------------------------------------------------------------------------------------ cli
def _load_json(p):
    return json.loads(Path(p).read_text())


def main(argv=None):
    ap = argparse.ArgumentParser(description="MoRoOp Error statuses vs stuck episodes (S16A)")
    ap.add_argument("--raw", default=str(mo.DEFAULT_RAW))
    ap.add_argument("--jsonl-sf", required=True)
    ap.add_argument("--budget-dir", default=str(mo.FLEET / "data" / "moroop" / "budget-sf"))
    ap.add_argument("--label-sf", default=str(mo.DEFAULT_RESULTS / "moroop_label-sf.json"))
    ap.add_argument("--jsonl-sb", default=str(mo.FLEET / "data" / "moroop" / "jsonl-sb"))
    ap.add_argument("--label-sb", default=str(mo.DEFAULT_RESULTS / "moroop_label-sb.json"))
    ap.add_argument("--stations", default=str(mo.DEFAULT_STATIONS))
    ap.add_argument("--station-radius", type=int, default=1)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    tb = mo._tb()
    stations, _near, _ = tb.cell_sets(_load_json(args.stations)["stations"], [])
    recs_by_shift, uptime_present = {}, False
    for k, name in enumerate(mo.SHIFTS):
        rows = mo.load_table(mo.shift_dir(args.raw, name) / f"{name}_robot_state_cleaned.parquet")
        uptime_present = uptime_present or bool(rows) and "robot_uptime" in rows[0]
        recs_by_shift[k] = shift_records(rows)
    lab_sf, lab_sb = _load_json(args.label_sf), _load_json(args.label_sb)
    eps_sf, sf_fmsgs = rebuild_episodes(args.jsonl_sf, lab_sf["servicing_max_s"], stations, args.station_radius)
    eps_sb, _ = rebuild_episodes(args.jsonl_sb, lab_sb["servicing_max_s"], stations, args.station_radius)
    for tag, eps, lab in (("sf", eps_sf, lab_sf), ("sb", eps_sb, lab_sb)):
        bad = reproduces(eps, lab["pooled"]["causes"]["table"])
        if bad:
            print(f"moroop_faults: the {tag} Detector re-run does not reproduce the label file: {bad}", file=sys.stderr)
            return 1
    unk = [e for e in eps_sb if e["cause"] == "unknown"]
    got = (len(unk), sum(e["duration_s"] for e in unk))
    if got != EXPECT_SB_UNKNOWN:
        print(f"moroop_faults: -sb unknown episodes (count, seconds) {got} != {EXPECT_SB_UNKNOWN}", file=sys.stderr)
        return 1
    raw_f = {k: sum(1 for r in recs if r["errors"]) for k, recs in recs_by_shift.items()}
    if raw_f != sf_fmsgs:
        print(f"moroop_faults: faulted messages in jsonl-sf {sf_fmsgs} != raw-derived {raw_f} (adapter run without --faults?)",
              file=sys.stderr)
        return 1
    bucket = None
    if all((Path(args.budget_dir) / f"zone{k}.json").is_file() for k in range(len(mo.SHIFTS))):
        bucket = {k: _load_json(Path(args.budget_dir) / f"zone{k}.json")["zones"][""]["robots"][mo.SERIAL]["seconds"]["faulted"]
                  for k in range(len(mo.SHIFTS))}
    rep = build_report(recs_by_shift, eps_sf, eps_sb,
                       cross_check(sum(sum(r["owned"] for r in recs if r["errors"]) for recs in recs_by_shift.values()), bucket),
                       uptime_present, sf_fmsgs)
    if not rep["table_b"]["shift6_intervention"]["sb"]:
        print("moroop_faults: the 3245 s shift-6 episode (2026-07-30T06:16:31Z) is not among the -sb episodes", file=sys.stderr)
        return 1
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(rep, sort_keys=True, indent=1) + "\n")
    print(f"verdict: {rep['verdict']} ({N_NOTE}); faulted s pooled {rep['table_a']['pooled']['faulted_s']}, "
          f"driving share {rep['table_a']['pooled']['driving_share']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Time to detect (S8P): how far into a shift the analyser's top-K hotspot map first shows a sticky floor cell.

Usage: python fleet/time_to_detect.py --phase-a DIR --publish-every S --top-k K[,K...] --out PATH [--keep-store] [--smoke]
       [--truth-kind {floor,blocked,outage}]
DIR is a closed-loop phase-A directory (zone*.jsonl.gz, store/decisions.jsonl, truth.json, phaseA_meta.json). The tool
copies DIR/store to DIR/store-ttd-<S>, reruns fleet/costmap.py ONCE on the copy with --publish-every S (by subprocess;
costmap's own --top-k is not passed: its rank claim already covers every nonzero cell), reads the copy's
hotspot_forecast rows of run closed_loop decided at the publish times, and derives every K from those same rows by the
claim's rank. DIR/store/decisions.jsonl is hashed before and after; a change aborts with no output. Per K: per truth cell
the first publish at which its rank is <= K (seconds since the zone's first message), a pooled cumulative detected-share
curve, false flags per publish (cells in the top K that are not truth cells), and a summary split at p >= 0.95.
--smoke runs the whole thing on a tiny self-built phase-A dir in a temp directory (nothing under results/).
Evaluation script like hotspot_score.py: reads truth.json on purpose; nothing in the analyser imports it.

CAVEAT: Floors are static from step 0, so this measures time to see what is already there, not reaction to a change.

--truth-kind blocked|outage (S10B) measures WINDOWS of a v2 truth (fleet-truth/2; a v1 file raises ValueError). Default
floor keeps everything above, output bytes included. Window kinds, for a window [start_step, end_step) (half-open, so
end_step is the first step the cell is clear) and publish step s(t) = truth.step_of(truth, t); seconds are step
differences * step_seconds; flagged(cell, t) = rank <= K at publish t:
  first_detect_s  (s(t*) - start_step) * step_seconds, t* the first publish with start_step <= s(t) < end_step that
                  flags the cell. No such publish: missed (first_detect_s and cleared_s null, never stale or open).
  preflag         flagged at the last publish with s(t) < start_step (the flag was already up; not a detection).
  cleared_s       DETECTED windows only: (s(t') - end_step) * step_seconds, t' the first publish with s(t) >= end_step that
                  does not flag the cell. Publishes at/after end_step exist but all flag it: null, stale_at_end. None
                  exist: null, open_at_end (censored, not stale).
  false flags     per publish, cells in the top K for which truth.truth_positive(truth, zone, cell, s, s) is empty.
The run name is read from DIR/store/ingest_runs.jsonl (exactly one unique run, else ValueError) and used for the forecast
selection, the forecast stripping and the costmap rerun. Phase A's costmap used --horizon-s 1245 and the rerun the
default; rank does not depend on the horizon (costmap.py), so that is moot.
"""
import argparse
import hashlib
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

FLEET = Path(__file__).resolve().parent
REPO = FLEET.parent
if str(FLEET) not in sys.path:
    sys.path.insert(0, str(FLEET))

from fleet_analyser import hotspot, store as store_mod  # noqa: E402
import costmap  # noqa: E402
import truth as truth_mod  # noqa: E402

SCHEMA_VERSION = "fleet-time-to-detect/1"
CAVEAT = "Floors are static from step 0, so this measures time to see what is already there, not reaction to a change."
QUANTILE_METHOD = "statistics.quantiles(n=4, method='inclusive')"
RUN = "closed_loop"
HIGH_P = 0.95
META_KEYS = ("publish_every_s", "top_k", "window_hours", "half_life_h", "steps", "env", "disturb", "zones", "n_publishes",
             "publish_times_s", "first_ts_global", "t0", "t0_offsets", "quantile_method", "caveat", "phase_a_dir",
             "store_hash_before", "store_hash_after")
TRUTH_KINDS = ("floor", "blocked", "outage")
WINDOW_CAVEAT = "Windows have a start and an end; detection is measured from the start, clearing from the end."
SMOKE_ENV = "tarware-small-4agvs-2pickers-globalobs-v1"
SMOKE_DISTURB = '{"floor": {"cells": 20, "p": [0.9, 0.99]}}'
SMOKE_STEPS = 150
SMOKE_ZONES = 2
SMOKE_EVERY = 150
SMOKE_KS = (5, 10)


# ------------------------------------------------------------------------------------------------ analysis
def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def quartiles(values):
    """{p25, median, p75} by statistics.quantiles(n=4, method='inclusive'); nulls for none, all equal for one value."""
    if not values:
        return dict(p25=None, median=None, p75=None)
    if len(values) == 1:
        return dict(p25=values[0], median=values[0], p75=values[0])
    q = statistics.quantiles(values, n=4, method="inclusive")
    return dict(p25=q[0], median=q[1], p75=q[2])


def parse_subject(subject):
    zone, _, cell = subject[1:].partition(":")
    return zone, cell


def select_forecasts(decision_rows, publish_ts, run=RUN):
    """hotspot_forecast rows of run closed_loop (or `run`) decided at a publish time -> [{zone, cell, t, rank}], plus the (uniform)
    window_hours and half_life_h read from the claims (raises when they differ across rows, or there are no rows)."""
    wanted = set(publish_ts)
    out, windows, halves = [], set(), set()
    for r in decision_rows:
        if r.get("kind") != "hotspot_forecast" or r.get("run") != run or r.get("decided_at") not in wanted:
            continue
        claim = json.loads(r["claim"]) if isinstance(r["claim"], str) else r["claim"]
        zone, cell = parse_subject(r["subject"])
        out.append(dict(zone=zone, cell=cell, t=r["decided_at"], rank=int(claim["rank"])))
        windows.add(claim["window_hours"])
        halves.add(claim["half_life_h"])
    if not out:
        raise ValueError("no hotspot_forecast rows at the publish times")
    if len(windows) != 1 or len(halves) != 1:
        raise ValueError(f"window_hours / half_life_h not uniform across the forecast rows: {sorted(windows)} {sorted(halves)}")
    return out, windows.pop(), halves.pop()


def analyse_k(k, forecasts, truth, t0, first_ts, publish_ts):
    """One K from the rows. truth {zone: {cell: p}}, t0 {zone: ts}. Pure function of its arguments."""
    ranks = {(f["zone"], f["cell"], f["t"]): f["rank"] for f in forecasts}
    by_t = {}
    for f in forecasts:
        if f["rank"] <= k:
            by_t.setdefault(f["t"], []).append(f)
    zones = sorted(truth, key=lambda z: (len(z), z))
    cells = {z: {c: dict(p=p, detected=False, first_detect_s=None, rank_at_detect=None) for c, p in sorted(truth[z].items())}
             for z in zones}
    n_truth = sum(len(v) for v in cells.values())
    curve, false_cells, flags = [], {}, []
    detected_n = 0
    for t in sorted(publish_ts):
        for z in zones:
            for c, rec in cells[z].items():
                if rec["detected"]:
                    continue
                r = ranks.get((z, c, t))
                if r is not None and r <= k:
                    rec.update(detected=True, first_detect_s=t - t0[z], rank_at_detect=r)
                    detected_n += 1
        ff = {}
        for f in by_t.get(t, []):
            if f["cell"] not in truth.get(f["zone"], {}):
                ff.setdefault(f["zone"], []).append(f["cell"])
        ff = {z: sorted(v) for z, v in sorted(ff.items())}
        n_ff = sum(len(v) for v in ff.values())
        flags.append(n_ff)
        key = str(t - first_ts)
        false_cells[key] = ff
        curve.append(dict(t_s=t - first_ts, detected_share=detected_n / n_truth if n_truth else None, false_flags=n_ff))

    def block(sel):
        recs = [r for z in zones for r in cells[z].values() if sel(r)]
        det = [r["first_detect_s"] for r in recs if r["detected"]]
        return recs, det

    all_recs, all_det = block(lambda r: True)
    summary = dict(share_detected_end=len(all_det) / n_truth if n_truth else None, first_detect_s=quartiles(all_det))
    for name, sel in (("p_ge_0.95", lambda r: r["p"] >= HIGH_P), ("p_lt_0.95", lambda r: r["p"] < HIGH_P)):
        recs, det = block(sel)
        summary[name] = dict(n_truth=len(recs), n_detected=len(det), share=len(det) / len(recs) if recs else None,
                             **quartiles(det))
    summary["false_flags_per_publish_mean"] = sum(flags) / len(flags) if flags else None
    return dict(summary=summary, curve=curve, cells=cells, false_flag_cells=false_cells)


def analyse_windows_k(k, forecasts, truth_doc, kind, publish_ts, first_ts):
    """One K for the windows of `kind` in a v2 truth doc (definitions in the module docstring). Pure function."""
    ss = truth_doc["step_seconds"]
    ranks = {(f["zone"], f["cell"], f["t"]): f["rank"] for f in forecasts}
    flagged_at = {}
    for f in forecasts:
        if f["rank"] <= k:
            flagged_at.setdefault(f["t"], []).append(f)
    pubs = [(t, truth_mod.step_of(truth_doc, t)) for t in sorted(publish_ts)]
    key = dict(truth_mod.WINDOW_KINDS)[kind]
    zones = sorted(truth_doc["zones"], key=lambda z: (len(z), z))

    def flagged(z, c, t):
        r = ranks.get((z, c, t))
        return r is not None and r <= k

    windows = {}
    for z in zones:
        recs = []
        for w in truth_doc["zones"][z].get(key, ()):
            c, a, b = w["cell"], w["start_step"], w["end_step"]
            first = next(((t, s) for t, s in pubs if a <= s < b and flagged(z, c, t)), None)
            before = [t for t, s in pubs if s < a]
            rec = dict(cell=c, start_step=a, end_step=b, detected=first is not None, first_detect_s=None,
                       rank_at_detect=None, preflag=bool(before) and flagged(z, c, before[-1]), cleared_s=None,
                       stale_at_end=False, open_at_end=False, missed=first is None)
            if first is not None:
                rec.update(first_detect_s=(first[1] - a) * ss, rank_at_detect=ranks[(z, c, first[0])])
                after = [(t, s) for t, s in pubs if s >= b]
                if not after:
                    rec["open_at_end"] = True
                else:
                    clear = next(((t, s) for t, s in after if not flagged(z, c, t)), None)
                    if clear is None:
                        rec["stale_at_end"] = True
                    else:
                        rec["cleared_s"] = (clear[1] - b) * ss
            recs.append(rec)
        windows[z] = recs
    false_cells, flags = {}, []
    for t, s in pubs:
        ff = {}
        for f in flagged_at.get(t, []):
            if f["zone"] not in truth_doc["zones"] or not truth_mod.truth_positive(truth_doc, f["zone"], f["cell"], s, s):
                ff.setdefault(f["zone"], []).append(f["cell"])
        ff = {z: sorted(v) for z, v in sorted(ff.items())}
        flags.append(sum(len(v) for v in ff.values()))
        false_cells[str(t - first_ts)] = ff
    allw = [r for z in zones for r in windows[z]]
    det = [r["first_detect_s"] for r in allw if r["detected"]]
    clr = [r["cleared_s"] for r in allw if r["cleared_s"] is not None]
    summary = dict(n_windows=len(allw), n_detected=len(det), share_detected=len(det) / len(allw) if allw else None,
                   first_detect_s=quartiles(det), cleared_s=quartiles(clr), missed=sum(r["missed"] for r in allw),
                   preflag=sum(r["preflag"] for r in allw), stale_at_end=sum(r["stale_at_end"] for r in allw),
                   open_at_end=sum(r["open_at_end"] for r in allw),
                   false_flags_per_publish_mean=sum(flags) / len(flags) if flags else None)
    return dict(summary=summary, windows=windows, false_flag_cells=false_cells)


def analyse_windows(decision_rows, truth_doc, kind, first_ts, publish_ts, ks, run):
    """(decision rows of `run`, v2 truth, kind, publish times, Ks) -> (by_k, window_hours, half_life_h)."""
    forecasts, window_h, half_h = select_forecasts(decision_rows, publish_ts, run)
    return {str(k): analyse_windows_k(k, forecasts, truth_doc, kind, publish_ts, first_ts) for k in ks}, window_h, half_h


def infer_run(phase_a):
    """The one run named in DIR/store/ingest_runs.jsonl. ValueError when the file is missing, has no run, or several."""
    path = Path(phase_a) / "store" / "ingest_runs.jsonl"
    if not path.exists():
        raise ValueError(f"{path} is missing: cannot infer the run for a window truth kind")
    runs = set()
    for ln in path.read_text(encoding="utf-8").splitlines():
        rec = json.loads(ln) if ln.strip() else {}
        if rec.get("run") is not None:
            runs.add(rec["run"])
    if not runs:
        raise ValueError(f"{path} names no run")
    if len(runs) > 1:
        raise ValueError(f"{path} names several runs {sorted(runs)}; exactly one is needed")
    return runs.pop()


def analyse(decision_rows, truth, t0, first_ts, publish_ts, ks):
    """(decision rows, truth, t0, publish times, Ks) -> (by_k, window_hours, half_life_h). All Ks from the same rows."""
    forecasts, window_h, half_h = select_forecasts(decision_rows, publish_ts)
    missing = sorted(set(truth) - set(t0))
    if missing:
        raise ValueError(f"truth zones without a first message: {missing}")
    return {str(k): analyse_k(k, forecasts, truth, t0, first_ts, publish_ts) for k in ks}, window_h, half_h


# ------------------------------------------------------------------------------------------------ io
def read_span(glob):
    """({zone: first ts}, first_ts_global, end_ts) from the zone files, parsed exactly as costmap.py does."""
    messages = hotspot.read_messages(glob)
    if not messages:
        raise ValueError(f"no messages under {glob}")
    t0 = {}
    for m in messages:
        z = str(m.zone)
        t0[z] = min(m.ts, t0.get(z, m.ts))
    return t0, min(m.ts for m in messages), max(m.ts for m in messages)


def strip_forecasts(copy, run=RUN):
    """Drop the copy's hotspot_forecast rows of RUN before the rerun. costmap.py dedups decisions on (kind, subject,
    publish ISO) and its last publish is always the stream end, which phase A already published: without this the
    stream-end rows would stay phase A's own (built with phase A's map parameters), not the rerun's. Returns n dropped."""
    path = Path(copy) / "decisions.jsonl"
    if not path.exists():
        return 0
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines(keepends=True)]
    recs = [json.loads(ln) if ln.strip() else None for ln in lines]
    gone = {r["id"] for r in recs if r and r.get("kind") == "hotspot_forecast" and r.get("run") == run}
    keep = [ln for ln, r in zip(lines, recs)  # also the update records (grades) of the dropped rows: same ids on rerun
            if not (r and (r.get("id") in gone and "__upd" not in r or r.get("__upd", {}).get("eq", {}).get("id") in gone))]
    dropped = len(gone)
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(keep)
    return dropped


def rerun_costmap(phase_a, copy, every, run=RUN):
    """The one costmap rerun: by subprocess on the store copy. Same pattern as scripts/closed_loop._run."""
    cmd = [sys.executable, str(FLEET / "costmap.py"), "--glob", str(Path(phase_a) / "*.jsonl.gz"), "--run", run,
           "--store", f"jsonl:{copy}", "--publish-every", str(every), "--out", str(Path(copy) / "costmap_ttd.json")]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"command failed ({r.returncode}): {' '.join(cmd)}\n{r.stdout[-2000:]}\n{r.stderr[-4000:]}")


def run(phase_a, every, ks, out, keep_store=False, rerun=rerun_costmap, span=read_span, truth_kind="floor"):
    """Full pipeline. Returns the output document; writes `out` only after the original store hash was checked."""
    phase_a = Path(phase_a)
    orig = phase_a / "store" / "decisions.jsonl"
    truth_doc = json.loads((phase_a / "truth.json").read_text())
    meta_path = phase_a / "phaseA_meta.json"
    pm = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    windows = truth_kind != "floor"
    run_name = RUN
    if windows:
        if truth_mod.is_v1(truth_doc):
            raise ValueError(f"--truth-kind {truth_kind} needs a v2 truth file (fleet-truth/2); {phase_a / 'truth.json'} is v1")
        run_name = infer_run(phase_a)
    t0, first_ts, end_ts = span(str(phase_a / "*.jsonl.gz"))
    if windows:
        t0_epoch = truth_mod.epoch_of(truth_doc["t0"])
        bad = {z: t for z, t in t0.items() if t != t0_epoch}
        if bad:
            raise ValueError(f"truth t0 {truth_doc['t0']} ({t0_epoch}) differs from the zones' first message: {bad}")
    pub = costmap.publish_times(first_ts, end_ts, every)
    hash_before = sha256_file(orig)
    copy = phase_a / f"store-ttd-{every}"
    if copy.exists():
        shutil.rmtree(copy)
    try:
        shutil.copytree(phase_a / "store", copy)
        if windows:
            strip_forecasts(copy, run_name)
            rerun(phase_a, copy, every, run=run_name)
        else:
            strip_forecasts(copy)
            rerun(phase_a, copy, every)
        hash_after = sha256_file(orig)
        if hash_after != hash_before:
            raise RuntimeError(f"{orig} changed during the rerun ({hash_before} -> {hash_after}); no output written")
        st = store_mod.open_store(f"jsonl:{copy}", RUN)
        try:
            rows = st.select("decisions", {"kind": "hotspot_forecast", "run": run_name})
        finally:
            st.close()
    finally:
        if not keep_store:
            shutil.rmtree(copy, ignore_errors=True)
    t0z = {z: t0[z] for z in sorted(t0, key=lambda z: (len(z), z))}
    if windows:
        by_k, window_h, half_h = analyse_windows(rows, truth_doc, truth_kind, first_ts, pub, ks, run_name)
        truth = {str(z): None for z in truth_doc["zones"]}
    else:
        truth = {str(z): dict(v["floor_cells"]) for z, v in truth_doc["zones"].items()}
        by_k, window_h, half_h = analyse(rows, truth, t0z, first_ts, pub, ks)
    meta = dict(publish_every_s=every, top_k=list(ks), window_hours=window_h, half_life_h=half_h,
                steps=pm.get("steps", truth_doc.get("steps")), env=pm.get("env", truth_doc.get("env_id")),
                disturb=pm.get("disturb", truth_doc.get("disturb")), zones=sorted(truth, key=lambda z: (len(z), z)),
                n_publishes=len(pub), publish_times_s=[t - first_ts for t in pub], first_ts_global=first_ts, t0=t0z,
                t0_offsets={z: t - first_ts for z, t in t0z.items() if t != first_ts}, quantile_method=QUANTILE_METHOD,
                caveat=CAVEAT, phase_a_dir=str(phase_a), store_hash_before=hash_before, store_hash_after=hash_after)
    if windows:
        key = dict(truth_mod.WINDOW_KINDS)[truth_kind]
        lens = [w["end_step"] - w["start_step"] for v in truth_doc["zones"].values() for w in v.get(key, ())]
        meta.update(caveat=WINDOW_CAVEAT, truth_kind=truth_kind, run=run_name, n_windows=len(lens),
                    window_len_steps_median=statistics.median(lens) if lens else None)
    return dict(schema_version=SCHEMA_VERSION, meta=meta, by_k=by_k)


def summary_line(k, doc):
    s = doc["by_k"][str(k)]["summary"]
    if "n_windows" in s:
        f, c = s["first_detect_s"], s["cleared_s"]
        share = "n/a" if s["share_detected"] is None else f"{s['share_detected']:.3f}"
        return (f"K={k}: windows {s['n_windows']}, detected {s['n_detected']} ({share}), missed {s['missed']}, preflag "
                f"{s['preflag']}, stale at end {s['stale_at_end']}, open at end {s['open_at_end']}, first detect s "
                f"p25/median/p75 {f['p25']}/{f['median']}/{f['p75']}, cleared s {c['p25']}/{c['median']}/{c['p75']}, "
                f"false flags per publish {s['false_flags_per_publish_mean']}")
    f = s["first_detect_s"]
    share = "n/a" if s["share_detected_end"] is None else f"{s['share_detected_end']:.3f}"
    return (f"K={k}: detected at end {share}, first detect s p25/median/p75 {f['p25']}/{f['median']}/{f['p75']}, "
            f"false flags per publish {s['false_flags_per_publish_mean']}")


# ------------------------------------------------------------------------------------------------ smoke
def _run(cmd):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"command failed ({r.returncode}): {' '.join(map(str, cmd))}\n{r.stdout[-2000:]}\n{r.stderr[-4000:]}")


def build_smoke_phase_a(tmp):
    pa = Path(tmp) / "phaseA"
    py = sys.executable
    _run([py, FLEET / "emit.py", "--zones", SMOKE_ZONES, "--seed-base", "0", "--steps", SMOKE_STEPS, "--env", SMOKE_ENV,
          "--disturb", SMOKE_DISTURB, "--sink", "file", "--rate", "flat", "--speed", "0", "--dir", pa])
    _run([py, FLEET / "ingest.py", "--source", "file", "--glob", pa / "*.jsonl.gz", "--run", RUN, "--store",
          f"jsonl:{pa / 'store'}", "--once"])
    (pa / "phaseA_meta.json").write_text(json.dumps(
        dict(env=SMOKE_ENV, seeds=SMOKE_ZONES, steps=SMOKE_STEPS, disturb=SMOKE_DISTURB), indent=1))
    return pa


# ------------------------------------------------------------------------------------------------ cli
def build_parser():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--phase-a", default=None, metavar="DIR", help="closed-loop phase-A directory")
    p.add_argument("--publish-every", type=int, default=None, metavar="S", help="event seconds between publishes")
    p.add_argument("--top-k", default=None, metavar="K[,K...]", help="comma separated K list")
    p.add_argument("--out", default=None, metavar="PATH")
    p.add_argument("--keep-store", action="store_true", help="keep DIR/store-ttd-<S> after the run")
    p.add_argument("--truth-kind", choices=TRUTH_KINDS, default="floor",
                   help="floor (default, static floor cells) or blocked / outage windows of a v2 truth")
    p.add_argument("--smoke", action="store_true", help="self-contained run on a tiny phase-A dir in a temp directory")
    return p


def validate(p, a):
    """Usage errors (p.error exits 2). Returns (ks or None). Without --smoke the first four flags are required."""
    ks = None
    if a.top_k is not None:
        try:
            ks = [int(x) for x in a.top_k.split(",")]
        except ValueError:
            p.error(f"--top-k must be a comma separated list of integers, got {a.top_k!r}")
        if not ks or any(k < 1 for k in ks) or len(set(ks)) != len(ks):
            p.error("--top-k values must be distinct integers >= 1")
    if a.publish_every is not None and a.publish_every < 1:
        p.error("--publish-every must be >= 1")
    if a.smoke:
        if a.phase_a is not None:
            p.error("--smoke builds its own phase-A directory; drop --phase-a")
        if a.truth_kind != "floor":
            p.error("--smoke measures floors; drop --truth-kind")
        if a.out is not None:
            out = Path(os.path.realpath(a.out))
            if (REPO / "results").resolve() in out.parents:
                p.error("--smoke must not write under results/")
    else:
        missing = [f for f, v in (("--phase-a", a.phase_a), ("--publish-every", a.publish_every), ("--top-k", a.top_k),
                                  ("--out", a.out)) if v is None]
        if missing:
            p.error("required without --smoke: " + ", ".join(missing))
    return ks


def main(argv=None, rerun=rerun_costmap, span=read_span):
    p = build_parser()
    a = p.parse_args(argv)
    ks = validate(p, a)
    t_start = time.time()
    with tempfile.TemporaryDirectory(prefix="ttd-smoke-") as tmp:
        if a.smoke:
            pa = build_smoke_phase_a(tmp)
            every, ks = a.publish_every or SMOKE_EVERY, ks or list(SMOKE_KS)
            out = a.out or str(Path(tmp) / "time_to_detect_smoke.json")
            doc = run(pa, every, ks, out, a.keep_store, rerun, span)
            costmap.write_json(out, doc)
            print(f"smoke: {pa}")
        else:
            every, out = a.publish_every, a.out
            doc = run(a.phase_a, every, ks, out, a.keep_store, rerun, span, a.truth_kind)
            costmap.write_json(out, doc)
        for k in ks:
            print(summary_line(k, doc))
        print(f"CAVEAT: {doc['meta']['caveat']}")
        print(f"time_to_detect: {doc['meta']['n_publishes']} publishes, Ks {ks} -> {out} ({time.time() - t_start:.1f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

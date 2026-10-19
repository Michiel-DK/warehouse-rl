"""Publish per-zone cost maps of the bad floor from the fleet stream, and the hotspot_forecast decisions behind them.

Usage: python fleet/costmap.py --glob 'fleet/data/<run>/*.jsonl.gz' [--store jsonl:DIR | clickhouse://HOST[:PORT]/DB]
       [--run NAME] [--window-hours 1] [--half-life-h 1] [--min-stalls 1] [--publish-every S] [--include-occupied]
       [--horizon-s 3600] [--top-k 20] [--out fleet/data/<run>/costmap.json]
       [--gate none|baseline|persistence] [--gate-windows 3] [--gate-sigma 2.0] [--gate-min-excess 2]
       [--gate-min-count 2] [--reset-forecasts]
Reads the zone files and the store's stuck_episodes (written by fleet/ingest.py), extracts stalls (fleet_analyser/hotspot.py)
and upserts them into the store's `stalls` table. Publishes at every multiple of --publish-every event seconds after the
first message that is <= the stream end, plus one at the stream end (only the stream end without --publish-every). Per
publish and zone cost = decayed score / the zone's max score (cells with fewer than --min-stalls window stalls are 0 and
omitted), written to the `costmap` table; the LAST publish is written to --out (atomic). Every nonzero cell also gets a
`hotspot_forecast` decision (claim_version 2: the claim carries rank, top_k and the map parameters the rank
grader recomputes with) deduped on (kind, Z<zone>:x,y, publish event-time ISO), so a re-run is a no-op.
S10F false-alarm gate (--gate, needs --publish-every). A gate only suppresses forecasts: the stalls, the costmap table
rows and the cost values are the same under every gate, and a gated forecast is the ungated one (same id, rank, cost,
claim fields) plus gate fields. The gate counts stalls in its own windows: the NON-overlapping publish intervals
(t_{i-1}, t_i] of the global publish grid (t_i = the publish times, t_0 = the first message ts - 1, so the first
message's stalls count in window 1), per (zone, cell), over hotspot.counted stalls by end time (the same filter and end
rule as hotspot.aggregate). This is not the decayed --window-hours window. The last (stream-end) window may be shorter
than --publish-every and is gated as it is. A cell absent from a window has count 0. Candidates are the cells with
count >= 1 at publish i (1-based).
  baseline: with i > B (--gate-windows), m = mean and sd = pstdev of the cell's counts over windows i-B..i-1; the cell
    passes iff c_i > m + S*sd (--gate-sigma) and c_i - m >= E (--gate-min-excess). i <= B is warm-up: nothing passes.
  persistence: top_K(i) = the zone's first K (--top-k) cells by (-count, cell string), counts >= 1, ranked within each
    zone; a cell passes iff (in top_K(i) and c_i >= C (--gate-min-count) and not in top_K(i-1)) or c_i - c_{i-1} >= E.
    Publish 1 is warm-up: nothing passes.
Only passing cells that are also in the ungated map get a forecast (claim + gate, gate_reason, gate_count and the gate's
numbers and parameters). --out gains one key `gate`. Forecast ids are deterministic on (kind, subject, publish ISO), so a
gated rerun on a store that already holds the ungated forecasts would dedupe into them: --reset-forecasts (jsonl store
copies only, never a directory named "store") first drops this run's hotspot_forecast decisions with their update
records, the forecast_grades rows of those ids and this run's costmap rows, and prints the three counts.
Every per-cell quantity is per zone: each zone has its own seed and floor layout. Analyst side: input is the stream and the
store only.
"""
import argparse
import json
import os
import statistics
import sys
from bisect import bisect_left
from pathlib import Path

FLEET = Path(__file__).resolve().parent
if str(FLEET) not in sys.path:
    sys.path.insert(0, str(FLEET))

from fleet_analyser import decisions, hotspot, store as store_mod  # noqa: E402
from fleet_analyser.hotspot import cost_zones  # noqa: E402,F401  (re-export: costmap.cost_zones stays importable)
from fleet_analyser.parse import iso  # noqa: E402

SCHEMA_VERSION = "fleet-costmap/1"
DEFAULT_HORIZON_S = 3600
DEFAULT_TOP_K = 20
GATES = ("none", "baseline", "persistence")
DEFAULT_GATE_WINDOWS = 3
DEFAULT_GATE_SIGMA = 2.0
DEFAULT_GATE_MIN_EXCESS = 2
DEFAULT_GATE_MIN_COUNT = 2


def publish_times(first_ts, end_ts, every):
    times = []
    if every:
        t = first_ts + every
        while t <= end_ts:
            times.append(t)
            t += every
    if not times or times[-1] != end_ts:
        times.append(end_ts)
    return times


def gate_window_counts(stalls, times, first_ts, exclude_occupied=True):
    """[{zone: {cell: n}}], one per publish: counted stalls with times[i-1] < end <= times[i], times[-1] := first_ts - 1."""
    out = [{} for _ in times]
    for s in stalls:
        if not hotspot.counted(s, exclude_occupied):
            continue
        j = bisect_left(times, s["end"])
        if j >= len(times) or (j == 0 and s["end"] <= first_ts - 1):
            continue
        zc = out[j].setdefault(s["zone"], {})
        zc[s["cell"]] = zc.get(s["cell"], 0) + 1
    return out


def gate_warmup(gate, idx, windows_b):
    """True when publish idx (0-based; i = idx + 1) is warm-up under `gate`: nothing passes."""
    return idx + 1 <= windows_b if gate == "baseline" else idx == 0


def _top_k(counts, k):
    return {c for c, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:k] if n >= 1}


def gate_pass(gate, windows, idx, zone, top_k, windows_b, sigma, min_excess, min_count):
    """{cell: info} the gate lets through for `zone` at publish idx. Pure; see the module docstring."""
    cur, passed = windows[idx].get(zone, {}), {}
    if gate_warmup(gate, idx, windows_b):
        return passed
    if gate == "baseline":
        for cell in sorted(cur):
            c = cur[cell]
            hist = [windows[w].get(zone, {}).get(cell, 0) for w in range(idx - windows_b, idx)]
            m, sd = statistics.mean(hist), statistics.pstdev(hist)
            if c >= 1 and c > m + sigma * sd and c - m >= min_excess:
                passed[cell] = dict(gate_reason="above_baseline", gate_count=c, gate_mean=m, gate_sd=sd,
                                    gate_windows=windows_b, gate_sigma=sigma, gate_min_excess=min_excess)
        return passed
    prev = windows[idx - 1].get(zone, {})
    now_top, prev_top = _top_k(cur, top_k), _top_k(prev, top_k)
    for cell in sorted(cur):
        c = cur[cell]
        new = cell in now_top and c >= min_count and cell not in prev_top
        rose = c - prev.get(cell, 0) >= min_excess
        if c >= 1 and (new or rose):
            passed[cell] = dict(gate_reason="+".join(r for r, on in (("new_entrant", new), ("rose", rose)) if on),
                                gate_count=c, gate_prev_count=prev.get(cell, 0), gate_top_k=top_k,
                                gate_min_count=min_count, gate_min_excess=min_excess)
    return passed


def reset_forecasts(directory, run):
    """Drop `run`'s hotspot_forecast decisions (with their update records), the forecast_grades rows (and update
    records) of those ids and the run's costmap rows from a jsonl store directory.
    Returns (decisions dropped, grade rows dropped, costmap rows dropped)."""
    d = Path(directory)

    def records(name):
        path = d / name
        if not path.exists():
            return []
        return [(ln, json.loads(ln) if ln.strip() else None) for ln in path.read_text(encoding="utf-8").splitlines(True)]

    def rewrite(name, recs, drop):
        keep = [ln for ln, r in recs if not (r is not None and drop(r))]
        if len(keep) != len(recs):
            (d / name).write_text("".join(keep), encoding="utf-8")
        return len(recs) - len(keep)

    def upd_id(r):
        return r.get("__upd", {}).get("eq", {}).get("id")

    dec = records("decisions.jsonl")
    gone = {r["id"] for _, r in dec if r and "__upd" not in r and r.get("kind") == "hotspot_forecast"
            and r.get("run") == run}
    n_dec = rewrite("decisions.jsonl", dec, lambda r: ("__upd" not in r and r.get("id") in gone) or upd_id(r) in gone)
    n_gr = rewrite("forecast_grades.jsonl", records("forecast_grades.jsonl"),
                   lambda r: r.get("id") in gone or upd_id(r) in gone)
    n_cm = rewrite("costmap.jsonl", records("costmap.jsonl"), lambda r: r.get("run") == run)
    return len(gone), n_gr, n_cm


def build_costmap(messages, store, run, window_h=1.0, half_life_h=1.0, min_stalls=1, publish_every=None,
                  exclude_occupied=True, horizon_s=DEFAULT_HORIZON_S, top_k=DEFAULT_TOP_K, gate="none",
                  gate_windows=DEFAULT_GATE_WINDOWS, gate_sigma=DEFAULT_GATE_SIGMA,
                  gate_min_excess=DEFAULT_GATE_MIN_EXCESS, gate_min_count=DEFAULT_GATE_MIN_COUNT):
    """Extract + persist stalls, publish cost maps and forecasts. Returns the last publish as the costmap.json dict
    (under a gate with one more key, `gate`; see the module docstring)."""
    if gate not in GATES:
        raise ValueError(f"gate must be one of {GATES}")
    if gate != "none" and not publish_every:
        raise ValueError("a gate needs publish_every (a single publish is permanent warm-up)")
    if not messages:
        raise ValueError("no messages")
    stalls = hotspot.extract_stalls(messages, run)
    hotspot.annotate_episodes(stalls, store.select("stuck_episodes", {"run": run}))
    store.upsert("stalls", ("run", "zone", "robot", "start"), stalls)
    first_ts, end_ts = min(m.ts for m in messages), max(m.ts for m in messages)
    zones = sorted({m.zone for m in messages})
    last = None
    times = publish_times(first_ts, end_ts, publish_every)
    gated = gate != "none"
    windows = gate_window_counts(stalls, times, first_ts, exclude_occupied) if gated else None
    gate_log, skipped = [], 0
    for idx, t in enumerate(times):
        maps = cost_zones(stalls, t, window_h, half_life_h, min_stalls, exclude_occupied)
        rows = [dict(run=run, zone=z, published_at=t, cell=c, cost=v["cost"], score=v["score"], stalls=v["stalls"])
                for z, cells in sorted(maps.items()) for c, v in sorted(cells.items())]
        store.upsert("costmap", ("run", "published_at", "zone", "cell"), rows)
        covered = min(window_h * 3600, t - first_ts)
        flagged = {z: [] for z in zones}
        passes = {}
        if gated and covered > 0:
            for z, cells in sorted(maps.items()):
                passes[z] = gate_pass(gate, windows, idx, z, top_k, gate_windows, gate_sigma, gate_min_excess,
                                      gate_min_count)
                skipped += sum(1 for c in passes[z] if c not in cells)
                flagged[z] = sorted(c for c in passes[z] if c in cells)
        if covered > 0:
            for z, cells in sorted(maps.items()):
                ranked = hotspot.rank_cells(cells)
                for k, (c, v) in enumerate(ranked, 1):
                    extra = {}
                    if gated:
                        if c not in passes[z]:
                            continue
                        extra = dict(gate=gate, **passes[z][c])
                    x = v["stalls"] * 3600 / covered
                    decisions.record_decision(
                        store, run=run, kind="hotspot_forecast", subject=f"Z{z}:{c}", start_iso=iso(t), decided_at=t,
                        claim=dict(expected_stalls_next_hour=x, cost=v["cost"], rank=k, horizon_s=horizon_s,
                                   window_hours=window_h, top_k=top_k, half_life_h=half_life_h,
                                   min_stalls=min_stalls, exclude_occupied=exclude_occupied, **extra),
                        rationale=f"{v['stalls']} stalls at {c} in zone {z} over the last {covered:.0f}s; cost "
                                  f"{v['cost']}, rank {k}" + (f"; gate {gate}: {extra['gate_reason']}" if extra else ""),
                        expected=x, grade_after=t + horizon_s)
        if gated:
            gate_log.append(dict(published_at=t, gate_warmup=gate_warmup(gate, idx, gate_windows), flagged=flagged))
        last = dict(schema_version=SCHEMA_VERSION, run=run, generated_at=iso(t), window_hours=window_h,
                    half_life_h=half_life_h, min_stalls=min_stalls, exclude_occupied=exclude_occupied,
                    zones={z: {c: v["cost"] for c, v in sorted(maps.get(z, {}).items())} for z in zones})
    if gated:
        last["gate"] = dict(name=gate, params=dict(windows=gate_windows, sigma=gate_sigma, min_excess=gate_min_excess,
                                                   min_count=gate_min_count, top_k=top_k),
                            skipped_not_in_map=skipped, publishes=gate_log)
    return last


def write_json(path, doc):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w") as f:
        json.dump(doc, f, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def build_parser():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--glob", required=True, help="zone<z>-<nnn>.jsonl.gz files of the run")
    p.add_argument("--store", default=None, help="jsonl:<dir> (default fleet/data/<run>/store) or clickhouse://...")
    p.add_argument("--run", default=None, help="run name (default: name of the glob's directory, as for ingest)")
    p.add_argument("--window-hours", type=float, default=1.0)
    p.add_argument("--half-life-h", type=float, default=1.0)
    p.add_argument("--min-stalls", type=int, default=1)
    p.add_argument("--publish-every", type=int, default=None, metavar="S", help="event seconds between publishes")
    p.add_argument("--include-occupied", action="store_true", help="also count stalls whose cell another robot occupied")
    p.add_argument("--horizon-s", type=int, default=DEFAULT_HORIZON_S)
    p.add_argument("--top-k", type=int, default=DEFAULT_TOP_K,
                   help="K of the rank claim: a forecast of rank <= K claims its cell stays in the zone's top K")
    p.add_argument("--out", default=None, help="costmap.json path (default fleet/data/<run>/costmap.json)")
    p.add_argument("--gate", choices=GATES, default="none",
                   help="false-alarm gate on the forecasts (needs --publish-every); the cost map is unchanged")
    p.add_argument("--gate-windows", type=int, default=DEFAULT_GATE_WINDOWS, metavar="B",
                   help="baseline gate: number of previous gate windows the cell's history is taken over")
    p.add_argument("--gate-sigma", type=float, default=DEFAULT_GATE_SIGMA, metavar="S",
                   help="baseline gate: count must exceed mean + S * pstdev")
    p.add_argument("--gate-min-excess", type=int, default=DEFAULT_GATE_MIN_EXCESS, metavar="E",
                   help="baseline: count - mean >= E; persistence: count - previous count >= E passes")
    p.add_argument("--gate-min-count", type=int, default=DEFAULT_GATE_MIN_COUNT, metavar="C",
                   help="persistence gate: a new top-K entrant needs a count >= C")
    p.add_argument("--reset-forecasts", action="store_true",
                   help="before publishing drop this run's hotspot_forecast decisions (+ updates), their forecast_grades "
                        "rows and this run's costmap rows from a jsonl store COPY (refuses a directory named store)")
    return p


def main(argv=None):
    p = build_parser()
    a = p.parse_args(argv)
    if a.window_hours <= 0 or a.half_life_h <= 0 or a.min_stalls < 1 or a.horizon_s < 1 or a.top_k < 1 \
            or (a.publish_every is not None and a.publish_every < 1):
        p.error("--window-hours and --half-life-h must be > 0; --min-stalls, --horizon-s, --top-k, --publish-every >= 1")
    if a.gate != "none" and a.publish_every is None:
        p.error("--gate needs --publish-every (a single publish is permanent warm-up)")
    if a.gate_windows < 1 or a.gate_min_excess < 1 or a.gate_min_count < 1 or a.gate_sigma < 0:
        p.error("--gate-windows, --gate-min-excess, --gate-min-count must be >= 1 and --gate-sigma >= 0")
    run = a.run or os.path.basename(os.path.dirname(os.path.abspath(a.glob))) or "run"
    if a.reset_forecasts:
        kind, _, rest = (a.store or "").partition(":")
        if kind != "jsonl" or not rest:
            p.error("--reset-forecasts works on a jsonl:<dir> store copy only")
        if Path(rest).resolve().name == "store":
            p.error("--reset-forecasts refuses a store directory named 'store' (it is meant for copies, "
                    "e.g. store-gate-baseline)")
        n_dec, n_gr, n_cm = reset_forecasts(rest, run)
        print(f"reset-forecasts {run}: dropped {n_dec} hotspot_forecast decisions, {n_gr} forecast_grades rows, "
              f"{n_cm} costmap rows")
    try:
        st = store_mod.open_store(a.store, run)
    except ValueError as e:
        p.error(str(e))
    messages = hotspot.read_messages(a.glob)
    if not messages:
        print(f"error: no messages under {a.glob}", file=sys.stderr)
        return 2
    doc = build_costmap(messages, st, run, a.window_hours, a.half_life_h, a.min_stalls, a.publish_every,
                        not a.include_occupied, a.horizon_s, a.top_k, a.gate, a.gate_windows, a.gate_sigma,
                        a.gate_min_excess, a.gate_min_count)
    st.close()
    out = a.out or str(FLEET / "data" / run / "costmap.json")
    write_json(out, doc)
    n = {z: len(c) for z, c in doc["zones"].items()}
    print(f"costmap {run}: {len(messages)} messages, last publish {doc['generated_at']}, nonzero cells per zone {n} -> {out}")
    if a.gate != "none":
        live = [pb for pb in doc["gate"]["publishes"] if not pb["gate_warmup"]]
        per = [len(c) for pb in live for c in pb["flagged"].values()]
        print(f"gate {a.gate}: flagged cells per zone per non-warm-up publish max {max(per, default=0)} total "
              f"{sum(per)} ({len(live)} of {len(doc['gate']['publishes'])} publishes), "
              f"{doc['gate']['skipped_not_in_map']} passing cells not in the map")
    return 0


if __name__ == "__main__":
    sys.exit(main())

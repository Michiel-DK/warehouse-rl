"""Fast change detector (S10I): a per-cell Page-CUSUM on stall counts, published as hotspot_forecast decisions.

Usage: python fleet/fastmap.py --glob 'fleet/data/<run>/*.jsonl.gz' --store jsonl:<COPY> --out PATH [--run NAME]
       [--publish-every 60] [--bin-s 60] [--baseline-bins 30] [--k 1.0] [--h 3.0] [--top-k 20]
       [--count {active,end}] [--include-occupied]
Why: the decayed map (hotspot.aggregate) counts a stall at its END time. A blind blockage holds a robot for hundreds of
seconds and the stall ends only when the blockage clears, so an open blockage is invisible to the map until it is over.
A detector that counts by end time fails the same way, hence the default counting rule:
  active  a counted stall counts once in EVERY bin it overlaps: start < bin_end and end > bin_start (bin j is
          (first_ts + j*B, first_ts + (j+1)*B]). Causal in the stall stream: a stall overlapping (a, b] has a stall
          message with ts <= b on the step grid. Known mild look-ahead, shared with the map: `next_occupied` is OR'd over
          the whole stall and the faulted-episode flag uses whole episodes (both from hotspot.py, unchanged).
  end     counted stalls with bin_start < end <= bin_end (the map's rule; kept for attribution in the report).
CUSUM per (zone, cell); every cell with any count in its zone is tracked from bin 0 (missing bins count 0):
  mu_j = mean of the cell's counts over bins max(0, j-N)..j-1 in which the cell was NOT flagged at the end of that bin
         (frozen while flagged, so a long jump does not leak into its own baseline); no such bin -> 0
  S_j  = max(0, S_{j-1} + x_j - (mu_j + k)), S_{-1} = 0; flag on when S_j > h; once flagged, release when S_j < h/2.
  S keeps running (no reset on alarm or release).
Publish on the costmap.publish_times grid (same grid as the map, incl. the stream-end publish). At publish t the state is
the one after the last complete bin with bin_end <= t (none: nothing flagged). Per zone the flagged cells are ranked by
(-score, cell); one hotspot_forecast decision per flagged cell, claim {detector "cusum", score, rank, top_k, horizon_s,
bin_s, k, h, baseline_bins, count, exclude_occupied, window_hours, half_life_h}. window_hours (= bin_s * N / 3600, the
baseline memory) and half_life_h (None: there is no decay) are in the claim only because
time_to_detect.select_forecasts reads both and raises when they are missing.
Store: the decisions go to a jsonl COPY of <glob dir>/store after costmap.reset_forecasts(copy, run) (the copied store
already holds map forecasts on the same grid and record_decision would dedupe into them). The original store is never
written and its decisions.jsonl is hashed before and after (a change aborts, no --out). A --store that is not jsonl:,
that resolves to the original store, or whose directory is named "store" is refused (exit 2). Stalls are not upserted.
Analyst side: input is the stream and the store copy only.
"""
import argparse
import hashlib
import math
import os
import shutil
import sys
from pathlib import Path

FLEET = Path(__file__).resolve().parent
if str(FLEET) not in sys.path:
    sys.path.insert(0, str(FLEET))

import costmap  # noqa: E402
from fleet_analyser import decisions, hotspot, store as store_mod  # noqa: E402
from fleet_analyser.parse import iso  # noqa: E402

SCHEMA_VERSION = "fleet-fastmap/1"
RULES = ("active", "end")
DEFAULT_BIN_S = 60
DEFAULT_BASELINE_BINS = 30
DEFAULT_K = 1.0
DEFAULT_H = 3.0
DEFAULT_TOP_K = 20
DEFAULT_PUBLISH_S = 60


def n_bins_of(first_ts, end_ts, bin_s):
    """Complete bins only: bin j is (first_ts + j*B, first_ts + (j+1)*B] and counts while its end <= end_ts."""
    return max(0, int((end_ts - first_ts) // bin_s))


def bin_counts(stalls, first_ts, end_ts, bin_s, rule="active"):
    """{(zone, cell): [count per bin]} over the bins of n_bins_of, from stalls already filtered by hotspot.counted.
    Cells with no count in any bin are absent."""
    if rule not in RULES:
        raise ValueError(f"count rule must be one of {RULES}")
    n = n_bins_of(first_ts, end_ts, bin_s)
    out = {}
    for s in stalls:
        if rule == "end":
            lo = hi = math.ceil((s["end"] - first_ts) / bin_s) - 1
        else:
            lo = math.floor((s["start"] - first_ts) / bin_s)
            hi = math.ceil((s["end"] - first_ts) / bin_s) - 1
        lo, hi = max(lo, 0), min(hi, n - 1)
        if lo > hi:
            continue
        row = out.setdefault((s["zone"], s["cell"]), [0] * n)
        for j in range(lo, hi + 1):
            row[j] += 1
    return out


def cusum(counts, baseline_bins, k, h):
    """Page-CUSUM with hysteresis over one cell's per-bin counts -> [(score, flagged, mu)] per bin (module docstring)."""
    out, s, on = [], 0.0, False
    clean = []  # (bin, count) of bins the cell was not flagged at the end of
    for j, x in enumerate(counts):
        window = [c for b, c in clean if b >= j - baseline_bins]
        mu = sum(window) / len(window) if window else 0.0
        s = max(0.0, s + x - (mu + k))
        if not on and s > h:
            on = True
        elif on and s < h / 2:
            on = False
        if not on:
            clean.append((j, x))
        out.append((s, on, mu))
    return out


def detect(stalls, first_ts, end_ts, bin_s, rule, baseline_bins, k, h):
    """{(zone, cell): [(score, flagged, mu)] per bin} for every cell with any count."""
    return {key: cusum(c, baseline_bins, k, h) for key, c in sorted(bin_counts(stalls, first_ts, end_ts, bin_s, rule).items())}


def flagged_at(states, first_ts, bin_s, t, n_bins):
    """{zone: [(cell, score)] ranked by (-score, cell)} after the last complete bin with bin_end <= t."""
    j = min(int((t - first_ts) // bin_s), n_bins) - 1
    out = {}
    if j < 0:
        return out
    for (zone, cell), seq in states.items():
        score, on, _ = seq[j]
        if on:
            out.setdefault(zone, []).append((cell, score))
    return {z: sorted(v, key=lambda cs: (-cs[1], cs[0])) for z, v in sorted(out.items())}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run_fastmap(glob, run, copy, out, publish_every=DEFAULT_PUBLISH_S, bin_s=DEFAULT_BIN_S,
                baseline_bins=DEFAULT_BASELINE_BINS, k=DEFAULT_K, h=DEFAULT_H, top_k=DEFAULT_TOP_K, rule="active",
                include_occupied=False):
    """The whole sequence (module docstring). Returns the --out document."""
    src = Path(os.path.dirname(os.path.abspath(glob))) / "store"
    copy = Path(copy)
    orig = src / "decisions.jsonl"
    hash_before = sha256_file(orig)
    if copy.exists():
        shutil.rmtree(copy)
    shutil.copytree(src, copy)
    costmap.reset_forecasts(copy, run)
    messages = hotspot.read_messages(glob)
    if not messages:
        raise ValueError(f"no messages under {glob}")
    first_ts, end_ts = min(m.ts for m in messages), max(m.ts for m in messages)
    stalls = hotspot.extract_stalls(messages, run)
    st = store_mod.open_store(f"jsonl:{copy}", run)
    try:
        hotspot.annotate_episodes(stalls, st.select("stuck_episodes", {"run": run}))
        stalls = [s for s in stalls if hotspot.counted(s, not include_occupied)]
        n_bins = n_bins_of(first_ts, end_ts, bin_s)
        states = detect(stalls, first_ts, end_ts, bin_s, rule, baseline_bins, k, h)
        window_h = bin_s * baseline_bins / 3600
        publishes = []
        for t in costmap.publish_times(first_ts, end_ts, publish_every):
            flagged = flagged_at(states, first_ts, bin_s, t, n_bins)
            doc_flagged = {}
            for zone, cells in flagged.items():
                doc_flagged[str(zone)] = []
                for rank, (cell, score) in enumerate(cells, 1):
                    doc_flagged[str(zone)].append(dict(cell=cell, score=score, rank=rank))
                    decisions.record_decision(
                        st, run=run, kind="hotspot_forecast", subject=f"Z{zone}:{cell}", start_iso=iso(t), decided_at=t,
                        claim=dict(detector="cusum", score=float(score), rank=rank, top_k=top_k, horizon_s=publish_every,
                                   bin_s=bin_s, k=k, h=h, baseline_bins=baseline_bins, count=rule,
                                   exclude_occupied=not include_occupied, window_hours=window_h, half_life_h=None),
                        rationale=f"CUSUM score {score:.2f} > {h} at {cell} in zone {zone} (count {rule}, bin {bin_s}s)",
                        expected=float(score), grade_after=t + publish_every)
            publishes.append(dict(published_at=t, t_s=t - first_ts, flagged=doc_flagged))
    finally:
        st.close()
    hash_after = sha256_file(orig)
    if hash_after != hash_before:
        raise RuntimeError(f"{orig} changed during the run ({hash_before} -> {hash_after}); no output written")
    doc = dict(schema_version=SCHEMA_VERSION, run=run,
               params=dict(publish_every=publish_every, bin_s=bin_s, baseline_bins=baseline_bins, k=k, h=h, top_k=top_k,
                           count=rule, include_occupied=include_occupied, window_hours=window_h, half_life_h=None),
               first_ts=first_ts, end_ts=end_ts, n_bins=n_bins, store_hash_before=hash_before,
               store_hash_after=hash_after, publishes=publishes)
    costmap.write_json(out, doc)
    return doc


def build_parser():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--glob", required=True, help="zone<z>-<nnn>.jsonl.gz files of the run")
    p.add_argument("--run", default=None, help="run name (default: name of the glob's directory)")
    p.add_argument("--store", required=True, help="jsonl:<copy dir>; the copy of <glob dir>/store, never the original")
    p.add_argument("--publish-every", type=int, default=DEFAULT_PUBLISH_S, metavar="S")
    p.add_argument("--bin-s", type=int, default=DEFAULT_BIN_S, metavar="B")
    p.add_argument("--baseline-bins", type=int, default=DEFAULT_BASELINE_BINS, metavar="N")
    p.add_argument("--k", type=float, default=DEFAULT_K, help="CUSUM allowance above the baseline mean")
    p.add_argument("--h", type=float, default=DEFAULT_H, help="CUSUM flag threshold (release at h/2)")
    p.add_argument("--top-k", type=int, default=DEFAULT_TOP_K, help="K recorded in the claim (flags are not truncated)")
    p.add_argument("--count", choices=RULES, default="active")
    p.add_argument("--include-occupied", action="store_true")
    p.add_argument("--out", required=True, metavar="PATH")
    return p


def main(argv=None):
    p = build_parser()
    a = p.parse_args(argv)
    if a.publish_every < 1 or a.bin_s < 1 or a.baseline_bins < 1 or a.top_k < 1 or a.h <= 0 or a.k < 0:
        p.error("--publish-every, --bin-s, --baseline-bins, --top-k must be >= 1, --h > 0, --k >= 0")
    kind, _, rest = a.store.partition(":")
    if kind != "jsonl" or not rest:
        p.error("--store must be jsonl:<dir> (a copy of the glob's store)")
    src = Path(os.path.dirname(os.path.abspath(a.glob))) / "store"
    copy = Path(rest).resolve()
    if copy == src.resolve() or copy.name == "store":
        p.error("--store refuses the original store and any directory named 'store'; give a copy, e.g. store-fast")
    if not (src / "decisions.jsonl").exists():
        p.error(f"{src / 'decisions.jsonl'} is missing")
    run = a.run or os.path.basename(os.path.dirname(os.path.abspath(a.glob))) or "run"
    doc = run_fastmap(a.glob, run, copy, a.out, a.publish_every, a.bin_s, a.baseline_bins, a.k, a.h, a.top_k, a.count,
                      a.include_occupied)
    per = [len(c) for pb in doc["publishes"] for c in pb["flagged"].values()]
    print(f"fastmap {run}: {len(doc['publishes'])} publishes, max flagged per zone per publish {max(per, default=0)}, "
          f"total flags {sum(per)} -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

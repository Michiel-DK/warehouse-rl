"""Traffic-absence detector (S14B): a per-cell silence test on robot passes, published as hotspot_forecast decisions.

Usage: python fleet/absencemap.py --glob 'fleet/data/<run>/*.jsonl.gz' --store jsonl:<COPY> --out PATH [--run NAME]
       [--publish-every 60] [--bin-s 60] [--alpha 1e-3] [--min-expected 10] [--top-k 20]
       python fleet/absencemap.py --smoke --glob '<data>/<run>/zone0-000.jsonl.gz'
Why: a blind blockage is a cell the planner routes around. It produces no stalls, it produces SILENCE. The decayed map and
the CUSUM (fastmap.py) both count stalls. This is the literature's detector (docs/LITERATURE.md Part 3 section 1, Part 4
section 3 and 4): a cell that traffic used to cross at some rate and nobody has crossed for much longer than that rate
explains is flagged.
Passes: per (zone, cell) a pass is one robot's FIRST message on that cell per visit (the robot's previous message, by
headerId, was on another cell, or it has none). A robot standing on a cell adds no further pass. Cell = hotspot.cell_str(x, y)
of agvPosition, the same cell as the map and the CUSUM. Duplicate (serial, headerId) pairs are dropped by read_messages.
Time axis: ONE origin for the whole run, first_ts = the first message ts over all files of --glob (as fastmap does; for a
run whose zones start together it equals the zone's first message). Bin j is (first_ts + j*B, first_ts + (j+1)*B], complete
bins only (fastmap.n_bins_of, imported).
Rule, evaluated per (zone, cell) at EVERY bin end t (causal, expanding):
  r      = passes_unflagged / observed_unflagged_s. observed_unflagged_s = seconds from first_ts to t EXCLUDING the seconds
           the cell was flagged; passes_unflagged = passes up to t made while the cell was not flagged (the releasing pass
           counts). While the cell is flagged both are frozen.
  eligible  r * observed_unflagged_s >= --min-expected (default 10). That product is passes_unflagged, so before any flag it
           is the pass count (9 passes: not eligible, 10: eligible). A cell with zero passes is never eligible.
  flag      eligible and exp(-r * gap) < --alpha (default 1e-3), gap = t - time of the cell's last pass; equivalently
           gap > ln(1/alpha) / r. The Poisson probability of a gap this long if the cell were still crossed at rate r.
  release   at the next pass on the cell (unflagged from that pass's time on; it stays unflagged at the next bin end unless
           the rule flags it again).
  score     r * gap, the expected passes missed. Per zone flagged cells are ranked by (-score, cell).
Per-bin-end rate versus the closed form: Part 4 gives a first-flag gap of ceil(ln(1/alpha) / (r * bin_s)) bins at a constant
rate. Here the denominator keeps growing during the open gap, so r falls and the threshold ln(1/alpha)/r rises; the per-bin
evaluation above is what is implemented, the closed form is only an approximation of it.
Deviations from HERE US 10847029 / 11270578 (the patents Part 4 follows): no time-of-day model (one rate per cell over the
whole observed span), no labelled threshold (alpha is the only dial, nothing is fitted to labels), no hysteresis (a
cell is released at its first pass, nothing else), and the eligibility count r*observed >= 10 runs over the whole unflagged
observed span, not over the tested window (HERE's 10 is the expected count inside the tested window, r*gap >= 10).
NOT built: the detours test of Pan et al. 2013. One run gives one 30-minute slot and no history, and the stream carries no
planned route (nodeStates holds only the first route node).
Publish on the costmap.publish_times grid (same as the map and the CUSUM). At publish t the state is the one after the last
complete bin with bin_end <= t (none: nothing flagged). One hotspot_forecast decision per flagged cell, claim {detector
"absence", score, rank, top_k, horizon_s, bin_s, alpha, min_expected, rate, gap_s, expected_passes, window_hours None,
half_life_h None}; time_to_detect.select_forecasts reads the last two, both None is uniform and accepted. recorded_at is the
publish time (not the wall clock), so two runs write byte-identical decision rows.
Store: the decisions go to a jsonl COPY of <glob dir>/store after costmap.reset_forecasts(copy, run), exactly as fastmap.py
(check_copy, sha256_file and n_bins_of are imported from it). The original store is never written and its decisions.jsonl is
hashed before and after (a change aborts with RuntimeError, no --out). A --store that is not jsonl: is refused (exit 2).
--smoke copies nothing of the original: it builds a temp layout (the zone0 files of --glob symlinked, store symlinked, so the
hash guard covers the real store), runs zone 0 there and prints one line. Analyst side: the input is the stream and the store
copy only.
"""
import argparse
import glob as globmod
import math
import os
import shutil
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

FLEET = Path(__file__).resolve().parent
if str(FLEET) not in sys.path:
    sys.path.insert(0, str(FLEET))

import costmap  # noqa: E402
from fastmap import check_copy, n_bins_of, sha256_file  # noqa: E402
from fleet_analyser import decisions, hotspot, store as store_mod  # noqa: E402
from fleet_analyser.parse import iso  # noqa: E402

SCHEMA_VERSION = "fleet-absencemap/1"
DEFAULT_BIN_S = 60
DEFAULT_ALPHA = 1e-3
DEFAULT_MIN_EXPECTED = 10.0
DEFAULT_TOP_K = 20
DEFAULT_PUBLISH_S = 60
CLAIM_KEYS = ("detector", "score", "rank", "top_k", "horizon_s", "bin_s", "alpha", "min_expected", "rate", "gap_s",
              "expected_passes", "window_hours", "half_life_h")


def pass_times(messages):
    """{(zone, cell): [pass ts ascending]}: a robot's first message on a cell per visit (module docstring)."""
    by_robot = defaultdict(list)
    for m in messages:
        by_robot[(m.zone, m.serial)].append(m)
    out = defaultdict(list)
    for (zone, _), msgs in by_robot.items():
        msgs.sort(key=lambda m: m.header_id)
        prev = None
        for m in msgs:
            cell = hotspot.cell_str(m.x, m.y)
            if cell != prev:
                out[(zone, cell)].append(m.ts)
            prev = cell
    return {k: sorted(v) for k, v in sorted(out.items())}


def absence_states(passes, first_ts, bin_s, n_bins, alpha, min_expected):
    """[(flagged, score, rate, gap_s)] per bin end for one cell's ascending pass times (module docstring rule)."""
    out = []
    i, n_pass = 0, len(passes)
    n_unfl = 0            # passes made while unflagged (the releasing pass counts)
    frozen_s = 0.0        # observed unflagged seconds before the current unflagged segment
    seg_start = first_ts  # the current unflagged segment began here
    flagged, last_pass = False, None
    for j in range(n_bins):
        t = first_ts + (j + 1) * bin_s
        while i < n_pass and passes[i] <= t:
            if flagged:
                flagged, seg_start = False, passes[i]
            n_unfl += 1
            last_pass = passes[i]
            i += 1
        if flagged:
            observed = frozen_s
        else:
            observed = frozen_s + (t - seg_start)
        rate = n_unfl / observed if observed > 0 else 0.0
        gap = t - last_pass if last_pass is not None else 0.0
        if not flagged and last_pass is not None and observed > 0:
            if n_unfl >= min_expected and math.exp(-rate * gap) < alpha:
                flagged = True
                frozen_s = observed
        out.append((flagged, rate * gap, rate, gap))
    return out


def detect(messages, first_ts, end_ts, bin_s, alpha, min_expected):
    """{(zone, cell): [(flagged, score, rate, gap_s)] per bin} for every cell with a pass."""
    n_bins = n_bins_of(first_ts, end_ts, bin_s)
    return {key: absence_states(p, first_ts, bin_s, n_bins, alpha, min_expected)
            for key, p in pass_times(messages).items()}


def flagged_at(states, first_ts, bin_s, t, n_bins):
    """{zone: [(cell, score, rate, gap_s)] ranked by (-score, cell)} after the last complete bin with bin_end <= t."""
    j = min(int((t - first_ts) // bin_s), n_bins) - 1
    out = {}
    if j < 0:
        return out
    for (zone, cell), seq in states.items():
        on, score, rate, gap = seq[j]
        if on:
            out.setdefault(zone, []).append((cell, score, rate, gap))
    return {z: sorted(v, key=lambda c: (-c[1], c[0])) for z, v in sorted(out.items())}


def run_absencemap(glob, run, copy, out, publish_every=DEFAULT_PUBLISH_S, bin_s=DEFAULT_BIN_S, alpha=DEFAULT_ALPHA,
                   min_expected=DEFAULT_MIN_EXPECTED, top_k=DEFAULT_TOP_K):
    """The whole sequence (module docstring). Returns the --out document (written unless `out` is None)."""
    src = Path(os.path.dirname(os.path.abspath(glob))) / "store"
    copy = check_copy(glob, copy)
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
    n_bins = n_bins_of(first_ts, end_ts, bin_s)
    states = detect(messages, first_ts, end_ts, bin_s, alpha, min_expected)
    st = store_mod.open_store(f"jsonl:{copy}", run)
    try:
        publishes = []
        for t in costmap.publish_times(first_ts, end_ts, publish_every):
            flagged = flagged_at(states, first_ts, bin_s, t, n_bins)
            doc_flagged = {}
            for zone, cells in flagged.items():
                doc_flagged[str(zone)] = []
                for rank, (cell, score, rate, gap) in enumerate(cells, 1):
                    doc_flagged[str(zone)].append(dict(cell=cell, score=score, rank=rank, rate=rate, gap_s=gap))
                    decisions.record_decision(
                        st, run=run, kind="hotspot_forecast", subject=f"Z{zone}:{cell}", start_iso=iso(t), decided_at=t,
                        claim=dict(detector="absence", score=float(score), rank=rank, top_k=top_k, horizon_s=publish_every,
                                   bin_s=bin_s, alpha=alpha, min_expected=min_expected, rate=float(rate),
                                   gap_s=float(gap), expected_passes=float(score), window_hours=None, half_life_h=None),
                        rationale=(f"no pass at {cell} in zone {zone} for {gap:.0f} s, expected {score:.1f} at rate "
                                   f"{rate:.4f}/s (alpha {alpha})"),
                        expected=float(score), grade_after=t + publish_every, recorded_at=float(t))
            publishes.append(dict(published_at=t, t_s=t - first_ts, flagged=doc_flagged))
    finally:
        st.close()
    hash_after = sha256_file(orig)
    if hash_after != hash_before:
        raise RuntimeError(f"{orig} changed during the run ({hash_before} -> {hash_after}); no output written")
    doc = dict(schema_version=SCHEMA_VERSION, run=run,
               params=dict(publish_every=publish_every, bin_s=bin_s, alpha=alpha, min_expected=min_expected, top_k=top_k),
               first_ts=first_ts, end_ts=end_ts, n_bins=n_bins, store_hash_before=hash_before,
               store_hash_after=hash_after, publishes=publishes)
    if out is not None:
        costmap.write_json(out, doc)
    return doc


def smoke(glob, publish_every=DEFAULT_PUBLISH_S, bin_s=DEFAULT_BIN_S, alpha=DEFAULT_ALPHA,
          min_expected=DEFAULT_MIN_EXPECTED, top_k=DEFAULT_TOP_K):
    """Zone 0 of the run behind `glob` in a temp layout (nothing is written under the real data). Returns the one line."""
    files = sorted(Path(f).resolve() for f in globmod.glob(glob) if os.path.basename(f).startswith("zone0-"))
    if not files:
        raise ValueError(f"no zone0-*.jsonl.gz file matches {glob}")
    real = files[0].parent
    if not (real / "store" / "decisions.jsonl").is_file():
        raise ValueError(f"{real / 'store' / 'decisions.jsonl'} is missing")
    run = real.name
    t0 = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="absencemap-smoke-") as tmp:
        d = Path(tmp) / run
        d.mkdir()
        for f in files:
            (d / f.name).symlink_to(f)
        (d / "store").symlink_to(real / "store")
        doc = run_absencemap(str(d / "*.jsonl.gz"), run, d / "store-absence", None, publish_every, bin_s, alpha,
                             min_expected, top_k)
    flags = [c["cell"] for pb in doc["publishes"] for cells in pb["flagged"].values() for c in cells]
    return (f"absencemap smoke {run} zone 0: {len(doc['publishes'])} publishes, {len(set(flags))} distinct flagged cells, "
            f"{len(flags)} flag-publishes, {time.monotonic() - t0:.1f}s")


def build_parser():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--glob", required=True, help="zone<z>-<nnn>.jsonl.gz files of the run")
    p.add_argument("--run", default=None, help="run name (default: name of the glob's directory)")
    p.add_argument("--store", default=None, help="jsonl:<copy dir>; the copy of <glob dir>/store, never the original")
    p.add_argument("--publish-every", type=int, default=DEFAULT_PUBLISH_S, metavar="S")
    p.add_argument("--bin-s", type=int, default=DEFAULT_BIN_S, metavar="B")
    p.add_argument("--alpha", type=float, default=DEFAULT_ALPHA, help="flag when exp(-rate*gap) < alpha")
    p.add_argument("--min-expected", type=float, default=DEFAULT_MIN_EXPECTED,
                   help="eligible when rate * observed unflagged seconds >= this")
    p.add_argument("--top-k", type=int, default=DEFAULT_TOP_K, help="K recorded in the claim (flags are not truncated)")
    p.add_argument("--out", default=None, metavar="PATH")
    p.add_argument("--smoke", action="store_true", help="zone 0 of --glob in a temp layout, prints one line")
    return p


def main(argv=None):
    p = build_parser()
    a = p.parse_args(argv)
    if a.publish_every < 1 or a.bin_s < 1 or a.top_k < 1 or not 0 < a.alpha < 1 or a.min_expected <= 0:
        p.error("--publish-every, --bin-s, --top-k must be >= 1, 0 < --alpha < 1, --min-expected > 0")
    if a.smoke:
        try:
            print(smoke(a.glob, a.publish_every, a.bin_s, a.alpha, a.min_expected, a.top_k))
        except ValueError as e:
            p.error(str(e))
        return 0
    if a.store is None or a.out is None:
        p.error("--store and --out are required (except with --smoke)")
    kind, _, rest = a.store.partition(":")
    if kind != "jsonl" or not rest:
        p.error("--store must be jsonl:<dir> (a copy of the glob's store)")
    src = Path(os.path.dirname(os.path.abspath(a.glob))) / "store"
    try:
        copy = check_copy(a.glob, rest)
    except ValueError as e:
        p.error(str(e))
    if not (src / "decisions.jsonl").exists():
        p.error(f"{src / 'decisions.jsonl'} is missing")
    run = a.run or os.path.basename(os.path.dirname(os.path.abspath(a.glob))) or "run"
    doc = run_absencemap(a.glob, run, copy, a.out, a.publish_every, a.bin_s, a.alpha, a.min_expected, a.top_k)
    per = [len(c) for pb in doc["publishes"] for c in pb["flagged"].values()]
    print(f"absencemap {run}: {len(doc['publishes'])} publishes, max flagged per zone per publish {max(per, default=0)}, "
          f"total flags {sum(per)} -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Where do the sequence gaps happen? (S12B) A per-cell map of missing messages, read from the fleet state stream alone.

Usage: python fleet/gapmap.py --glob 'DIR/*.jsonl.gz' --run NAME --out PATH [--top-k 10] [--store jsonl:COPY]
Why: the ingester counts sequence gaps per wall minute (fleet_analyser/ledger.py `gap`) but never says where. A WiFi dead
zone shows up as robots whose headerId jumps whenever they cross a cell. This tool puts each gap on the grid.
Rules (an analyst-side estimate; it knows nothing about where the gaps were made):
  Per (zone, robot) the valid, non-duplicate messages are ordered by headerId (rejected lines and repeated (serial,
  headerId) pairs are ignored, as the ingester ignores them). A jump of M = headerId_after - headerId_before - 1 > 0 is a
  gap between the last cell before (P) and the first cell after (Q). The M missing messages are placed so that:
    P == Q                      all M on that cell
    Manhattan distance 1        M / 2 on each of P and Q
    Manhattan distance >= 2     on the cells strictly between P and Q on a Bresenham line from P to Q (endpoints
                                EXCLUDED), M split evenly; if that interior is empty (a pure diagonal step) M / 2 on P and Q
  A robot's first message with headerId k > 0 is a gap with no P: it is not placed (counted in `unplaced_leading_missing`).
  A robot that ends the stream inside a dead zone leaves no gap at all (nothing follows the missing ids).
Per zone the cells are ranked by (-dropped, cell) with {cell, dropped (float), gaps, robots (sorted serials), minutes
(sorted distinct UTC minutes, "YYYY-MM-DDTHH:MMZ", of the missing span: the j-th missing message is dated by linear
interpolation between the timestamps of P and Q)}. One decision row per flagged cell, the top K per zone (kind "gap_cell",
subject "x,y", start_iso = the first gap's start, decided_at = stream end, claim {dropped, gaps, rank, top_k, zone}), is in
the output JSON under "decisions" and, with --store, written by decisions.record_decision. --store must be a jsonl: COPY
(fastmap.check_copy, exit 2 otherwise); an existing copy is appended to, a missing one is a copy of <glob dir>/store; the
original store is never written. Known limit: the dedup key (kind:subject:start_iso) has no zone, so two zones with the same
cell and the same first-gap start share one stored row; `store_duplicates` counts what the store refused.
Stdout: per zone the top-10 cells. Analyst side: the input is the stream (and the store copy); no ground-sidecar file is read.
"""
import argparse
import glob as globmod
import gzip
import os
import shutil
import sys
import time
from pathlib import Path

FLEET = Path(__file__).resolve().parent
if str(FLEET) not in sys.path:
    sys.path.insert(0, str(FLEET))

import costmap  # noqa: E402
import fastmap  # noqa: E402
from fleet_analyser import decisions, store as store_mod  # noqa: E402
from fleet_analyser.parse import iso, parse_line  # noqa: E402

SCHEMA_VERSION = "fleet-gapmap/1"
DEFAULT_TOP_K = 10


def bresenham(p, q):
    """All integer cells on the Bresenham line from p to q, endpoints included."""
    (x0, y0), (x1, y1) = p, q
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err, cells = dx + dy, []
    while True:
        cells.append((x0, y0))
        if (x0, y0) == (x1, y1):
            return cells
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def place(p, q, missing):
    """[(cell, share)] for a gap of `missing` messages between cells p and q (module docstring)."""
    dist = abs(p[0] - q[0]) + abs(p[1] - q[1])
    if dist == 0:
        return [(p, float(missing))]
    if dist >= 2:
        interior = bresenham(p, q)[1:-1]
        if interior:
            return [(c, missing / len(interior)) for c in interior]
    return [(p, missing / 2), (q, missing / 2)]


def _minute(epoch):
    return iso(epoch - epoch % 60)[:-4] + "Z"  # "...THH:MM:SSZ" -> "...THH:MMZ"


def read_stream(pattern):
    """{(zone, serial): [(header_id, ts, (x, y))]} sorted by headerId, rejects and repeated ids dropped."""
    robots = {}
    for path in sorted(globmod.glob(pattern)):
        with gzip.open(path, "rb") as f:
            for line in f:
                m, _ = parse_line(line)
                if m is not None:
                    robots.setdefault((m.zone, m.serial), {}).setdefault(m.header_id, (m.ts, (m.x, m.y)))
    return {k: [(h, ts, c) for h, (ts, c) in sorted(v.items())] for k, v in robots.items()}


def gaps_of(rows):
    """[(P cell, Q cell, missing, ts_P, ts_Q)] and the count of unplaced leading missing ids for one robot's rows."""
    out, leading = [], 0
    if rows and rows[0][0] > 0:
        leading = rows[0][0]
    for (h0, t0, c0), (h1, t1, c1) in zip(rows, rows[1:]):
        if h1 > h0 + 1:
            out.append((c0, c1, h1 - h0 - 1, t0, t1))
    return out, leading


def build_document(robots, run, top_k=DEFAULT_TOP_K):
    zones, leading, end_ts = {}, 0, 0
    for (zone, serial), rows in sorted(robots.items()):
        end_ts = max([end_ts] + [r[1] for r in rows])
        gaps, lead = gaps_of(rows)
        leading += lead
        cells = zones.setdefault(zone, {})
        for p, q, missing, t0, t1 in gaps:
            shares = place(p, q, missing)
            minutes = {_minute(t0 + (t1 - t0) * j // (missing + 1)) for j in range(1, missing + 1)}
            for c, share in shares:
                e = cells.setdefault(c, dict(dropped=0.0, gaps=0, robots=set(), minutes=set(), first=t0))
                e["dropped"] += share
                e["gaps"] += 1
                e["robots"].add(serial)
                e["minutes"] |= minutes
                e["first"] = min(e["first"], t0)
    out_zones, rows_out = {}, []
    for zone in sorted(zones):
        ranked = sorted(zones[zone].items(), key=lambda kv: (-kv[1]["dropped"], f"{kv[0][0]},{kv[0][1]}"))
        listing = [dict(cell=f"{c[0]},{c[1]}", dropped=e["dropped"], gaps=e["gaps"], robots=sorted(e["robots"]),
                        minutes=sorted(e["minutes"])) for c, e in ranked]
        out_zones[str(zone)] = dict(cells=listing, total_dropped=sum(e["dropped"] for _, e in ranked))
        for rank, ((c, e), item) in enumerate(zip(ranked[:top_k], listing), 1):
            start_iso = iso(e["first"])
            subject = item["cell"]
            claim = dict(dropped=e["dropped"], gaps=e["gaps"], rank=rank, top_k=top_k, zone=str(zone))
            key = decisions.dedup_key("gap_cell", subject, start_iso)
            rows_out.append(dict(id=decisions.decision_id(key), run=run, kind="gap_cell", subject=subject,
                                 start_iso=start_iso, decided_at=end_ts, claim=claim,
                                 rationale=f"{e['dropped']:.1f} missing messages placed on {subject} in zone {zone}",
                                 expected=float(e["dropped"]), grade_after=end_ts, dedup_key=key))
    return dict(schema_version=SCHEMA_VERSION, run=run, top_k=top_k, unplaced_leading_missing=leading, zones=out_zones,
                decisions=rows_out)


def write_store(copy, glob, run, rows):
    """Append the decision rows to the jsonl store copy (created as a copy of <glob dir>/store when missing). Returns the
    number of rows the store refused as already present."""
    src = Path(os.path.dirname(os.path.abspath(glob))) / "store"
    if not copy.exists() and src.is_dir():
        shutil.copytree(src, copy)
    st = store_mod.open_store(f"jsonl:{copy}", run)
    refused = 0
    try:
        for r in rows:
            _, created = decisions.record_decision(
                st, run=run, kind=r["kind"], subject=r["subject"], start_iso=r["start_iso"], decided_at=r["decided_at"],
                claim=r["claim"], rationale=r["rationale"], expected=r["expected"], grade_after=r["grade_after"])
            refused += 0 if created else 1
    finally:
        st.close()
    return refused


def build_parser():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--glob", required=True, help="zone<z>-<nnn>.jsonl.gz files of the run")
    p.add_argument("--run", required=True)
    p.add_argument("--out", required=True, metavar="PATH")
    p.add_argument("--top-k", type=int, default=DEFAULT_TOP_K, help="cells per zone recorded as gap_cell decisions")
    p.add_argument("--store", default=None, help="jsonl:<COPY of the run store>; never the original")
    return p


def main(argv=None):
    p = build_parser()
    a = p.parse_args(argv)
    if a.top_k < 1:
        p.error("--top-k must be >= 1")
    copy = None
    if a.store is not None:
        kind, _, rest = a.store.partition(":")
        if kind != "jsonl" or not rest:
            p.error("--store must be jsonl:<dir> (a copy of the glob's store)")
        try:
            copy = fastmap.check_copy(a.glob, rest)
        except ValueError as e:
            p.error(str(e))
    t0 = time.monotonic()
    robots = read_stream(a.glob)
    if not robots:
        p.error(f"no messages under {a.glob}")
    doc = build_document(robots, a.run, a.top_k)
    if copy is not None:
        doc["store_duplicates"] = write_store(copy, a.glob, a.run, doc["decisions"])
    costmap.write_json(a.out, doc)
    for zone, z in doc["zones"].items():
        top = ", ".join(f"{c['cell']}={c['dropped']:.1f}" for c in z["cells"][:10])
        print(f"gapmap {a.run} zone {zone}: dropped {z['total_dropped']:.0f}, top cells: {top or 'none'}")
    print(f"gapmap {a.run}: {len(doc['decisions'])} decisions ({time.monotonic() - t0:.1f} s) -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

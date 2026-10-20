"""Mutual-blocking finder (S12B, renamed S12C): blocking clusters and blocking chains among stuck robots, read from
the fleet state stream alone.

Usage: python fleet/deadlock.py --glob 'DIR/*.jsonl.gz' --run NAME --out PATH [--min-s 30] [--store jsonl:COPY]
Stdout: "blocking RUN: blocking_clusters N blocking_chains M blocked_s_per_robot_hour R -> PATH".
Why: congestion and deadlock are the second most named operator theme (docs/scouting/operator-problems.md). The stream
carries every robot's cell at every step, so who waits for whom can be read off it. This tool does not change what a stall
is: the detector (fleet_analyser/detector.py) and its episodes are untouched and it is not a second detector.

The graph. The detector decides `_cause` ONCE per stuck episode (at T_entry), so this module RECOMPUTES the detector's rule
at every batch. It drives a fleet_analyser.detector.Detector over the parsed stream (same (zone, ts) batching, same
out-of-order skip; imported, not copied) and taps every processed batch to get each robot's state. For every robot whose
state is STUCK in the batch the out-edges follow the detector's own precedence, with `detector._near` (Manhattan <= 1) on
the batch's messages:
  robot faulted                       -> no out-edge (faulted_self)
  >= 1 adjacent FAULTED robot         -> an edge to EVERY adjacent faulted robot (blocked_by_faulted)
  >= 1 adjacent STUCK robot           -> an edge to EVERY adjacent stuck robot (blocked_by_stuck)
  exactly one adjacent robot          -> one edge to it (traffic); several or none -> no edge
ALL qualifying neighbours, not only the lowest serial the detector records as `blocker`: with a single lowest-serial
blocker three stuck robots in a line would read as a 2-cycle plus a hanger-on. A traffic edge always points at a robot that
is not STUCK, so it can never close a cycle; it is inert for cycles and kept only for the length of a blocking chain.

What a "blocking cluster" is here, and why it is not called a deadlock (S12C, docs/LITERATURE.md Part 2 section 1).
`_near` is symmetric and the grid is bipartite, so two adjacent STUCK robots with no faulted neighbour always block each
other. A blocking cluster is therefore a mutually-blocked group that persists, NOT a proven circular wait; a queue of stuck
robots behind a non-robot obstacle (a blind blockage, a floor problem) counts as one too. On the undisturbed run 49
clusters with median length 75 s all resolve, because the vendor planner replans after five stuck steps; a true deadlock
(a circular wait in a wait-for graph, Coffman 1971) cannot survive in this simulator. In deadlock theory a knot IS the
deadlock set, so the acyclic chain must not be called a knot.

Definitions, per zone and per batch:
  cluster   a strongly connected component of >= 2 robots in the batch's graph, tracked across batches by the identity of
            its robot set (a change of membership closes the old one and opens a new one). start = the latest stopped-run
            start (the run `since`, the detector's stuck-episode start convention) among its members at the first batch
            the component appears; end = ts of the first batch in which that exact component no longer exists
            (resolution "broke_up"), or the zone's last batch ts ("unresolved_at_end"); length_s = end - start. A robot
            with no message in a batch is not in that batch's graph (it splits a component). Kept iff length_s >= --min-s
            (default 30). With this backdating every STUCK cycle already has length_s >= stuck_after, so min_s = 30 filters
            nothing at the detector default; min_s is compared against length_s.
  chain     a batch-level path of >= 2 edges (A -> B -> C) among robots that are in no component of size >= 2 that batch;
            reported as the maximal such paths (sources to sinks of that acyclic part, robots ordered along the path, `head`
            = the last robot), tracked by robot set with the same start / end / length / min_s rule. A weaker class: a chain
            of waiting robots that ends at a robot with no out-edge. With the edge rules above the head is always a FAULTED
            robot: the middle robot B of A -> B -> C is STUCK, and if it had no faulted neighbour it would point back at the
            stuck A (adjacency is symmetric) and A, B would be a cluster; a traffic edge ends at a robot with no other
            neighbour, which cannot be a middle robot. So chains are rare (a stuck line feeding a faulted robot).
Per zone: blocked_s_per_robot_hour = sum(length_s * robots) over kept clusters / (distinct robots * (last ts - first ts)
/ 3600); top_cells = the 10 cells with the most blocked seconds (each cluster adds its length_s to each of its cells at
its first batch), ranked by (-blocked_s, cell). Output schema "fleet-deadlock/2" (v1 had the keys deadlocks, knots,
deadlock_s_per_robot_hour, top_cells[].deadlock_s and decision kind "deadlock"; same values).
Decisions: one row per kept cluster (kind "blocking_cluster", subject = its sorted cells joined with ";", start_iso, decided_at =
end, claim {robots, cells, length_s, resolution, min_s, zone}); they are always in the output JSON under "decisions" and,
with --store, also written by decisions.record_decision. --store must be a jsonl: COPY (fastmap.check_copy, exit 2
otherwise): an existing copy is appended to, a missing one is a copy of <glob dir>/store; the original store is never
written. Known limit: the dedup key (kind:subject:start_iso) has no zone, so two zones with the same cells and the same
start would share one stored row; the output JSON keeps both and `store_duplicates` counts what the store refused.
Analyst side: the input is the stream (and the store copy); no ground-sidecar file is read.
"""
import argparse
import os
import shutil
import sys
import time
from pathlib import Path

FLEET = Path(__file__).resolve().parent
if str(FLEET) not in sys.path:
    sys.path.insert(0, str(FLEET))

import fastmap  # noqa: E402  (check_copy, the store-copy guard)
import costmap  # noqa: E402
from fleet_analyser import decisions, hotspot, store as store_mod  # noqa: E402
from fleet_analyser.detector import DEFAULT_STUCK_AFTER, FAULTED, STUCK, Detector, _near  # noqa: E402
from fleet_analyser.parse import iso  # noqa: E402

SCHEMA_VERSION = "fleet-deadlock/2"
DEFAULT_MIN_S = 30
TOP_CELLS = 10
DEFINITION = ("blocking cluster: mutually blocked robots (strongly connected component, >= 2) that persist >= min_s; every one "
              "found so far resolves, so this is a congestion measure, not a circular wait. blocking chain: maximal path of "
              ">= 2 edges among robots in no cluster. length_s = end - start, start = latest stopped-run start among the "
              "members.")


# ------------------------------------------------------------------------------------------------ the graph
def category_of(m, batch, states):
    """(cause, targets) of one robot in one batch by the detector's precedence; targets = sorted serials it waits for.
    cause is the detector's `_cause` value ("unknown" when there is no neighbour); a traffic robot with several
    neighbours has no target."""
    if m.faulted:
        return "faulted_self", []
    others = [o for s, o in sorted(batch.items()) if s != m.serial and _near(m, o)]
    faulted = [o.serial for o in others if o.faulted]
    if faulted:
        return "blocked_by_faulted", faulted
    stuck = [o.serial for o in others if states[o.serial] == STUCK]
    if stuck:
        return "blocked_by_stuck", stuck
    if len(others) == 1:
        return "traffic", [others[0].serial]
    return ("traffic", []) if others else ("unknown", [])


def batch_edges(batch, states):
    """{serial: (cause, targets)} for every STUCK robot of the batch."""
    return {s: category_of(m, batch, states) for s, m in sorted(batch.items()) if states[s] == STUCK}


def sccs(graph):
    """Strongly connected components (Tarjan, iterative) of {node: [targets]} -> list of sorted tuples, sorted."""
    index, low, on, stack, out, counter = {}, {}, set(), [], [], [0]
    for root in sorted(graph):
        if root in index:
            continue
        work = [(root, iter(sorted(graph.get(root, ()))))]
        index[root] = low[root] = counter[0]
        counter[0] += 1
        stack.append(root)
        on.add(root)
        while work:
            node, it = work[-1]
            advanced = False
            for nxt in it:
                if nxt not in index:
                    index[nxt] = low[nxt] = counter[0]
                    counter[0] += 1
                    stack.append(nxt)
                    on.add(nxt)
                    work.append((nxt, iter(sorted(graph.get(nxt, ())))))
                    advanced = True
                    break
                if nxt in on:
                    low[node] = min(low[node], index[nxt])
            if advanced:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node])
            if low[node] == index[node]:
                comp = []
                while True:
                    w = stack.pop()
                    on.discard(w)
                    comp.append(w)
                    if w == node:
                        break
                out.append(tuple(sorted(comp)))
    return sorted(out)


def clusters_of(graph):
    """The components of >= 2 robots, as frozensets."""
    return {frozenset(c) for c in sccs(graph) if len(c) >= 2}


def chains_of(graph, in_scc):
    """Maximal paths of >= 2 edges among the nodes outside every >= 2 component, as {frozenset: ordered tuple}. A path
    runs from a node with no in-edge (inside that acyclic part) to a node with no out-edge (inside it)."""
    nodes = {n for n in set(graph) | {t for ts in graph.values() for t in ts} if n not in in_scc}
    succ = {n: sorted(t for t in graph.get(n, ()) if t in nodes) for n in nodes}
    has_in = {t for ts in succ.values() for t in ts}
    found = {}

    def walk(path):
        nxt = succ[path[-1]]
        if not nxt:
            if len(path) >= 3:
                key = frozenset(path)
                if key not in found or tuple(path) < found[key]:
                    found[key] = tuple(path)
            return
        for t in nxt:
            walk(path + [t])

    for n in sorted(nodes - has_in):
        walk([n])
    return found


# ------------------------------------------------------------------------------------------------ the tap
class _Tap(Detector):
    """A Detector that reports every batch it processes (states of the robots that were actually stepped)."""

    def __init__(self, observer, **kw):
        super().__init__(**kw)
        self.observer = observer

    def _process_batch(self, zone, z, ts, msgs):
        before = {m.serial: (z.robots[m.serial].last_ts if m.serial in z.robots else None) for m in msgs}
        events = super()._process_batch(zone, z, ts, msgs)
        batch = {}
        for m in sorted(msgs, key=lambda m: m.serial):
            lt = before[m.serial]
            if m.serial not in batch and (lt is None or ts > lt):  # the detector's own out-of-order skip
                batch[m.serial] = m
        states = {s: z.robots[s].state for s in batch}
        since = {s: z.robots[s].run["since"] for s in batch if z.robots[s].run is not None}
        self.observer(zone, ts, batch, states, since, events)
        return events


def run_batches(messages, stuck_after=DEFAULT_STUCK_AFTER, observer=None, stations=None, station_radius=0):
    """Drive the detector over `messages` (in stream order) and call observer(zone, ts, batch, states, edges, events, since) per
    processed batch, where edges = batch_edges(batch, states) and since = {serial: stopped-run start} of the robots in a run. Returns {zone: sorted list of batch ts}."""
    seen = {}

    def tap(zone, ts, batch, states, since, events):
        seen.setdefault(zone, []).append(ts)
        if observer is not None:
            observer(zone, ts, batch, states, batch_edges(batch, states), events, since)

    det = _Tap(tap, stuck_after=stuck_after, stations=stations, station_radius=station_radius)
    for m in messages:
        det.feed(m)
    det.end_all()
    return seen


# ------------------------------------------------------------------------------------------------ tracking
class _Tracker:
    """Open / close items by robot-set identity across the batches of one zone."""

    def __init__(self):
        self.active = {}  # frozenset -> item dict
        self.done = []

    def step(self, ts, current, make):
        """current: {frozenset: payload}. Closes items no longer present (end = ts), opens new ones via make(key, payload)."""
        for key in [k for k in self.active if k not in current]:
            self.done.append(dict(self.active.pop(key), end=ts, resolution="broke_up"))
        for key, payload in sorted(current.items(), key=lambda kv: sorted(kv[0])):
            if key not in self.active:
                self.active[key] = make(key, payload)

    def finish(self, last_ts):
        for key in sorted(self.active, key=sorted):
            self.done.append(dict(self.active[key], end=last_ts, resolution="unresolved_at_end"))
        self.active = {}
        return self.done


def _row(item):
    start, end = item["start"], item["end"]
    row = dict(robots=sorted(item["robots"]), cells=sorted(item["cells"]), start=start, end=end, start_iso=iso(start),
               end_iso=iso(end), length_s=end - start, resolution=item["resolution"])
    if "order" in item:
        row.update(robots=list(item["order"]), head=item["order"][-1])
    return row


def analyse(messages, min_s=DEFAULT_MIN_S, stuck_after=DEFAULT_STUCK_AFTER, stations=None, station_radius=0):
    """{zone: dict(blocking_clusters, blocking_chains, n_robots, first_ts, last_ts)}: the clusters / chains kept by min_s, as rows."""
    trackers, spans = {}, {}

    def observe(zone, ts, batch, states, edges, events, since):
        tr = trackers.setdefault(zone, (_Tracker(), _Tracker()))
        sp = spans.setdefault(zone, dict(first=ts, last=ts, robots=set()))
        sp["last"] = ts
        sp["robots"].update(batch)
        graph = {s: list(t) for s, (_, t) in edges.items()}
        cur = clusters_of(graph)
        members = set().union(*cur) if cur else set()
        chains = chains_of(graph, members)

        def cells(key):
            return {f"{batch[s].x},{batch[s].y}" for s in key if s in batch}

        tr[0].step(ts, {k: None for k in cur},
                   lambda k, _p: dict(robots=k, cells=cells(k), start=max(since[s] for s in k)))
        tr[1].step(ts, chains, lambda k, order: dict(robots=k, order=order, cells=cells(k),
                                                      start=max(since[s] for s in k if s in since)))

    run_batches(messages, stuck_after, observe, stations, station_radius)
    out = {}
    for zone in sorted(trackers):
        sp = spans[zone]
        dl = [_row(i) for i in trackers[zone][0].finish(sp["last"])]
        kn = [_row(i) for i in trackers[zone][1].finish(sp["last"])]
        out[zone] = dict(blocking_clusters=[r for r in dl if r["length_s"] >= min_s],
                         blocking_chains=[r for r in kn if r["length_s"] >= min_s],
                         n_robots=len(sp["robots"]), first_ts=sp["first"], last_ts=sp["last"])
    return out


def build_document(messages, run, min_s=DEFAULT_MIN_S, stuck_after=DEFAULT_STUCK_AFTER, stations=None, station_radius=0):
    per = analyse(messages, min_s, stuck_after, stations, station_radius)
    zones, rows = {}, []
    num = hours = 0.0
    n_dl = n_kn = 0
    for zone, z in sorted(per.items(), key=lambda kv: str(kv[0])):
        rh = z["n_robots"] * (z["last_ts"] - z["first_ts"]) / 3600
        zn = sum(d["length_s"] * len(d["robots"]) for d in z["blocking_clusters"])
        by_cell = {}
        for d in z["blocking_clusters"]:
            for c in d["cells"]:
                by_cell[c] = by_cell.get(c, 0) + d["length_s"]
        top = sorted(by_cell.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_CELLS]
        zones[str(zone)] = dict(blocking_clusters=z["blocking_clusters"], blocking_chains=z["blocking_chains"],
                                robot_hours=rh, blocked_s_per_robot_hour=zn / rh if rh else 0.0,
                                top_cells=[dict(cell=c, blocked_s=s) for c, s in top])
        num, hours = num + zn, hours + rh
        n_dl, n_kn = n_dl + len(z["blocking_clusters"]), n_kn + len(z["blocking_chains"])
        for d in z["blocking_clusters"]:
            subject = ";".join(d["cells"])
            claim = dict(robots=d["robots"], cells=d["cells"], length_s=d["length_s"], resolution=d["resolution"],
                         min_s=min_s, zone=str(zone))
            key = decisions.dedup_key("blocking_cluster", subject, d["start_iso"])
            rows.append(dict(id=decisions.decision_id(key), run=run, kind="blocking_cluster", subject=subject,
                             start_iso=d["start_iso"], decided_at=d["end"], claim=claim,
                             rationale=f"blocking cluster: {len(d['robots'])} robots mutually blocked for {d['length_s']} s in zone {zone}",
                             expected=float(d["length_s"]), grade_after=d["end"], dedup_key=key))
    return dict(schema_version=SCHEMA_VERSION, run=run, min_s=min_s, definition=DEFINITION, zones=zones,
                total=dict(blocking_clusters=n_dl, blocking_chains=n_kn, robot_hours=hours,
                           blocked_s_per_robot_hour=num / hours if hours else 0.0),
                decisions=rows)


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
    p.add_argument("--min-s", type=float, default=DEFAULT_MIN_S, help="keep blocking clusters / chains with length_s >= this")
    p.add_argument("--store", default=None, help="jsonl:<COPY of the run store>; never the original")
    p.add_argument("--stations", default=None, metavar="auto|PATH",
                   help="S13B: station goal cells (auto = from <glob dir>/emit_ledger.json and the env, or a PATH file); "
                        "a stopped run starting within --station-radius of one is SERVICING, not STUCK")
    p.add_argument("--station-radius", type=int, default=0, help="Manhattan radius around a station cell (default 0)")
    return p


def main(argv=None):
    p = build_parser()
    a = p.parse_args(argv)
    if a.min_s < 0:
        p.error("--min-s must be >= 0")
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
    messages = hotspot.read_messages(a.glob)
    if not messages:
        p.error(f"no messages under {a.glob}")
    if a.station_radius < 0:
        p.error("--station-radius must be >= 0")
    stations = None
    if a.stations is not None:
        from fleet_analyser.stations import load_stations

        stations = load_stations(a.stations, os.path.dirname(os.path.abspath(a.glob)))
    doc = build_document(messages, a.run, a.min_s, DEFAULT_STUCK_AFTER, stations, a.station_radius)
    if stations is not None:
        doc["station_rule"] = dict(stations=a.stations, radius=a.station_radius)
    if copy is not None:
        doc["store_duplicates"] = write_store(copy, a.glob, a.run, doc["decisions"])
    costmap.write_json(a.out, doc)
    t = doc["total"]
    print(f"blocking {a.run}: blocking_clusters {t['blocking_clusters']} blocking_chains {t['blocking_chains']} "
          f"blocked_s_per_robot_hour {t['blocked_s_per_robot_hour']:.4f} ({time.monotonic() - t0:.1f} s) -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

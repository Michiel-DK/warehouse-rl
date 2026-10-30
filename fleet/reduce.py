"""S18A report by exception: keep fewer lines of a fleet state log and still give the same answers.

Usage: python fleet/reduce.py --glob 'DIR/*.jsonl.gz' --rules {all,change,gap,threshold,neighbours,recovered}
           --out OUTDIR [--heartbeat-s 60] [--servicing-max-s S] [--stations PATH] [--station-radius N]
Prints one JSON summary (sort_keys). Writes the kept lines, BYTE FOR BYTE AS READ, to OUTDIR/<same file name>
(gzip with mtime 0 and no embedded name: two runs on the same input give identical files). Nothing else is written.

Standard name (docs/LITERATURE.md Part 10 section 1): report by exception (change-only) with a maximum interval, zero
deadband, because every field the analyser reads is discrete. This is not compression; gzip is the baseline it is measured
against. The keep decision uses parse.Message only: the `custom` block is never read, and neither is the raw byte length
(`raw_len`), `header_id` or `ts` in the change test. The in-reducer Detector gets parsed Messages only.

Unit of work: one input FILE GROUP, never the whole glob. zone<z>-<nnn>.jsonl.gz files of the same <z> form one group (a
zone's rollover files), any other name is its own group. Robots are keyed (group, serial): MoRoOp serials have no zone
prefix and the same serial recurs in every shift file, so a whole-glob key would merge nine shifts into one robot. One
Detector per group, one robot-hour sum per (group, serial).

Canonical per-robot sequence (what every analysis sees, fleet/timebudget.kept_messages and fleet/fleet_analyser/hotspot
.read_messages): lines that parse, the first of every (serial, headerId) pair in a group, per robot sorted by (ts, headerId)
with any message whose ts <= the previous one dropped. Rules R1 to R5 run on that sequence. A line outside it (parse reject,
duplicate headerId, out-of-order ts) is dropped by every rule except `all`, because no analysis reads it and keeping it
could make a different line count in the reduced log. Their counts are in the summary.

Rules, cumulative and simplest first (each rung's kept set contains the rung below's):
  all         R0 identity.
  change      R1 per robot, keep a line whose Message minus (header_id, ts, raw_len) differs from the last kept line of that
              robot; keep each robot's first and last line.
  gap         R2 = R1 + never create an interval longer than --heartbeat-s H between two kept lines (an interval already
              longer than H in the source stays as it is) + both ends of every source interval longer than max_gap_s (60).
  threshold   R3 = R2 + in each stopped run (the detector's: driving false, one non-empty orderId) the first line at or after
              since + stuck_after, and with --servicing-max-s S the first line at or after since + S.
  neighbours  R4 = R3 + at each stuck episode's T_entry (Detector run on the full group inside the reducer, given
              --stations / --station-radius / --servicing-max-s exactly as the full-log analysis is given them) every line of
              that zone with ts == T_entry.
  recovered   R5 = R4 + the line after each closed episode's ending line, per robot.
The rules that use H are gap, threshold, neighbours, recovered. R0 and R1 do not.

Robot-hours: per (group, serial), last accepted ts minus first accepted ts in the FULL input, summed, divided by 3600. The
same denominator is used for the lines in and the lines kept. Gzip bytes: both sides are the decompressed lines re-gzipped
per file with the same compressor and level (GZIP_LEVEL, mtime 0), never the emitter's .gz size, so `all` gives
ratio_gzip == 1.0.
"""
import argparse
import glob as _glob
import gzip
import io
import json
import math
import re
import sys
from pathlib import Path

FLEET = Path(__file__).resolve().parent
REPO = FLEET.parent
for _p in (FLEET, REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fleet_analyser.detector import DEFAULT_STUCK_AFTER, Detector  # noqa: E402
from fleet_analyser.parse import parse_line  # noqa: E402
from fleet_analyser.stations import load_stations  # noqa: E402
from timebudget import DEFAULT_MAX_GAP_S, stopped_runs  # noqa: E402

RULES = ("all", "change", "gap", "threshold", "neighbours", "recovered")
RUNGS = RULES[1:]
GZIP_LEVEL = 9
GZIP_MAGIC = b"\x1f\x8b"
DEFAULT_HEARTBEAT_S = 60.0
_GROUP_RE = re.compile(r"^(.*)-\d+\.jsonl(?:\.gz)?$")
_NOT_IN_SIG = ("header_id", "ts", "raw_len")


def stations_path(text):
    """argparse type for --stations: a PATH. 'auto' (the analysers' emit-ledger layout) is refused: it would resolve
    emit_ledger.json against the wrong directory here, and the reducer must be given the file the full-log run used."""
    if text == "auto":
        raise argparse.ArgumentTypeError("'auto' is not accepted, pass the stations PATH the full-log analysis used")
    return text


def servicing_number(text):
    """argparse type for --servicing-max-s: a finite number > 0. 'auto' (the analysers' data-driven bound) is refused: the
    reducer must be told the number the full-log run used."""
    try:
        v = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"must be a number (got {text!r}); 'auto' is not accepted, pass the bound the "
                                         "full-log analysis used") from None
    if not 0 < v < math.inf:
        raise argparse.ArgumentTypeError(f"must be > 0 and finite, got {text}")
    return v


def positive(text):
    v = float(text)
    if not 0 < v < math.inf:
        raise argparse.ArgumentTypeError(f"must be > 0 and finite, got {text}")
    return v


def read_lines(path):
    """Every line of a file as bytes, newline included (gzip detected by magic bytes)."""
    with open(path, "rb") as f:
        gz = f.read(2) == GZIP_MAGIC
    with (gzip.open(path, "rb") if gz else open(path, "rb")) as f:
        return list(f)


def gz_bytes(lines):
    """The lines as one gzip member: fixed level, mtime 0, no embedded file name (deterministic)."""
    buf = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buf, compresslevel=GZIP_LEVEL, mtime=0) as f:
        for ln in lines:
            f.write(ln)
    return buf.getvalue()


def group_of(path):
    name = Path(path).name
    m = _GROUP_RE.match(name)
    return m.group(1) if m else name


def signature(m):
    """The change key: every Message field except header_id, ts and raw_len."""
    return tuple(getattr(m, f) for f in m.__dataclass_fields__ if f not in _NOT_IN_SIG)


class Reducer:
    """Loads and parses a log once; `kept(rule, heartbeat_s)` gives the kept (file index, line index) set of a rung."""

    def __init__(self, paths, stations=None, station_radius=0, servicing_max_s=None, max_gap_s=DEFAULT_MAX_GAP_S):
        self.paths = [str(p) for p in paths]
        self.stations_path = stations
        self.station_radius = station_radius
        self.servicing_max_s = servicing_max_s
        self.max_gap_s = max_gap_s
        if stations == "auto":
            raise ValueError("Reducer: stations must be a PATH, not 'auto'")
        self.stations = load_stations(stations, ".") if stations is not None else None
        self.lines = [read_lines(p) for p in self.paths]
        self.n_rejected = self.n_duplicate = self.n_out_of_order = 0
        self.groups = {}   # group -> {serial: [(file idx, line idx, Message)] in canonical order}
        self._parse()
        self._events = {}  # group -> detector events (filled on demand)
        self._cache = {}

    # ---------------------------------------------------------------- loading
    def _parse(self):
        by_group = {}
        for fi, p in enumerate(self.paths):
            by_group.setdefault(group_of(p), []).append(fi)
        self.group_files = by_group
        self.span = {}  # (group, serial) -> [first ts, last ts] over every accepted line
        for g, fis in by_group.items():
            seen, robots = set(), {}
            for fi in fis:
                for li, raw in enumerate(self.lines[fi]):
                    m, _ = parse_line(raw)
                    if m is None:
                        self.n_rejected += 1
                        continue
                    if (m.serial, m.header_id) in seen:
                        self.n_duplicate += 1
                        continue
                    seen.add((m.serial, m.header_id))
                    robots.setdefault(m.serial, []).append((fi, li, m))
                    s = self.span.setdefault((g, m.serial), [m.ts, m.ts])
                    s[0], s[1] = min(s[0], m.ts), max(s[1], m.ts)
            views = {}
            for serial, ents in robots.items():
                view = []
                for e in sorted(ents, key=lambda e: (e[2].ts, e[2].header_id)):
                    if view and e[2].ts <= view[-1][2].ts:
                        self.n_out_of_order += 1
                        continue
                    view.append(e)
                views[serial] = view
            self.groups[g] = views

    # ---------------------------------------------------------------- the Detector pass (full group, Messages only)
    def detector_events(self, group):
        if group not in self._events:
            det = Detector(stations=self.stations, station_radius=self.station_radius,
                           servicing_max_s=self.servicing_max_s)
            msgs = [e[2] for view in self.groups[group].values() for e in view]
            events = []
            for m in sorted(msgs, key=lambda m: (m.ts, m.serial)):
                events += det.feed(m)
            events += det.end_all()
            self._events[group] = [ev for ev in events if ev["kind"] in ("episode_open", "episode_close")]
        return self._events[group]

    # ---------------------------------------------------------------- rungs
    def _r1(self):
        keep = set()
        for views in self.groups.values():
            for view in views.values():
                last_sig = None
                for i, (fi, li, m) in enumerate(view):
                    sig = signature(m)
                    if i == 0 or i == len(view) - 1 or sig != last_sig:
                        keep.add((fi, li))
                        last_sig = sig
        return keep

    def _r2(self, keep, heartbeat_s):
        keep = set(keep)
        for views in self.groups.values():
            for view in views.values():
                n = len(view)
                for i in range(n - 1):
                    if view[i + 1][2].ts - view[i][2].ts > self.max_gap_s:  # a source gap: both ends stay
                        keep.add(view[i][:2])
                        keep.add(view[i + 1][:2])
                last_ts = None
                for i, (fi, li, m) in enumerate(view):
                    if (fi, li) in keep:
                        last_ts = m.ts
                    elif i + 1 < n and view[i + 1][2].ts - last_ts > heartbeat_s:
                        keep.add((fi, li))  # dropping it would leave an interval longer than H
                        last_ts = m.ts
        return keep

    def _r3(self, keep):
        keep = set(keep)
        for views in self.groups.values():
            for view in views.values():
                msgs = [e[2] for e in view]
                for a, b in stopped_runs(msgs)[0]:
                    since = msgs[a].ts
                    bounds = [DEFAULT_STUCK_AFTER] + ([] if self.servicing_max_s is None else [self.servicing_max_s])
                    for bound in bounds:
                        for j in range(a, b + 1):
                            if msgs[j].ts - since >= bound:
                                keep.add(view[j][:2])
                                break
        return keep

    def _r4(self, keep):
        keep = set(keep)
        entries = {}  # (group, zone, ts) -> [(fi, li)]
        for g, views in self.groups.items():
            for view in views.values():
                for fi, li, m in view:
                    entries.setdefault((g, m.zone, m.ts), []).append((fi, li))
        for g in self.groups:
            for ev in self.detector_events(g):
                if ev["kind"] == "episode_open":
                    keep.update(entries.get((g, ev["zone"], ev["t_entry"]), ()))
        return keep

    def _r5(self, keep):
        keep = set(keep)
        for g, views in self.groups.items():
            for ev in self.detector_events(g):
                if ev["kind"] != "episode_close" or ev["resolution"] == "unresolved":
                    continue
                view = views[ev["robot"]]
                for i, (fi, li, m) in enumerate(view):
                    if m.ts == ev["end"]:
                        if i + 1 < len(view):
                            keep.add(view[i + 1][:2])
                        break
        return keep

    def rung_sets(self, heartbeat_s):
        """{rung: kept set} for change..recovered at one H, each a superset of the one before."""
        key = float(heartbeat_s)
        if key not in self._cache:
            sets = {"change": self._r1()}
            sets["gap"] = self._r2(sets["change"], heartbeat_s)
            sets["threshold"] = self._r3(sets["gap"])
            sets["neighbours"] = self._r4(sets["threshold"])
            sets["recovered"] = self._r5(sets["neighbours"])
            self._cache[key] = sets
        return self._cache[key]

    def kept(self, rule, heartbeat_s=DEFAULT_HEARTBEAT_S):
        if rule == "all":
            return {(fi, li) for fi in range(len(self.paths)) for li in range(len(self.lines[fi]))}
        return self.rung_sets(heartbeat_s)[rule]

    # ---------------------------------------------------------------- output
    def kept_lines(self, kept):
        """Per file index: the kept lines in source order, with their source indices."""
        out = {}
        for fi, li in sorted(kept):
            out.setdefault(fi, []).append((li, self.lines[fi][li]))
        return out

    def robot_hours(self):
        return sum(hi - lo for lo, hi in self.span.values()) / 3600

    def write(self, rule, outdir, heartbeat_s=DEFAULT_HEARTBEAT_S):
        outdir = Path(outdir)
        inputs = {Path(p).resolve() for p in self.paths}
        if any((outdir / Path(p).name).resolve() in inputs for p in self.paths):
            raise SystemExit("reduce: --out would overwrite an input file")
        outdir.mkdir(parents=True, exist_ok=True)
        kept = self.kept_lines(self.kept(rule, heartbeat_s))
        for fi, p in enumerate(self.paths):
            lines = [raw for _, raw in kept.get(fi, [])]
            name = Path(p).name
            (outdir / name).write_bytes(gz_bytes(lines) if name.endswith(".gz") else b"".join(lines))
        return kept

    def summary(self, rule, heartbeat_s=DEFAULT_HEARTBEAT_S):
        kept = self.kept_lines(self.kept(rule, heartbeat_s))
        n_in = sum(len(ls) for ls in self.lines)
        n_kept = sum(len(v) for v in kept.values())
        raw_in = sum(len(raw) for ls in self.lines for raw in ls)
        raw_kept = sum(len(raw) for v in kept.values() for _, raw in v)
        gz_in = sum(len(gz_bytes(ls)) for ls in self.lines)
        gz_kept = sum(len(gz_bytes([raw for _, raw in kept.get(fi, [])])) for fi in range(len(self.paths)))
        hours = self.robot_hours()
        cum, added, prev = {}, {}, 0
        if rule != "all":
            sets = self.rung_sets(heartbeat_s)
            for r in RUNGS[:RUNGS.index(rule) + 1]:
                cum[r] = len(sets[r])
                added[r] = len(sets[r]) - prev
                prev = len(sets[r])
        else:
            cum["all"] = added["all"] = n_in
        return dict(
            rules=rule, heartbeat_s=None if rule in ("all", "change") else heartbeat_s,
            lines_in=n_in, lines_kept=n_kept, bytes_in_raw=raw_in, bytes_kept_raw=raw_kept,
            bytes_in_gzip=gz_in, bytes_kept_gzip=gz_kept, gzip_level=GZIP_LEVEL,
            ratio_gzip=gz_in / gz_kept if gz_kept else None, line_ratio=n_in / n_kept if n_kept else None,
            kept_lines_per_robot_hour=n_kept / hours if hours else None,
            lines_per_robot_hour_in=n_in / hours if hours else None, robot_hours=hours,
            robots=len(self.span), groups=sorted(self.groups),
            kept_by_rule=cum, added_by_rule=added,
            lines_rejected=self.n_rejected, lines_duplicate=self.n_duplicate, lines_out_of_order=self.n_out_of_order,
            args=dict(servicing_max_s=self.servicing_max_s, stations=self.stations_path,
                      station_radius=self.station_radius if self.stations_path is not None else None,
                      max_gap_s=self.max_gap_s, stuck_after=DEFAULT_STUCK_AFTER))


def main(argv=None):
    ap = argparse.ArgumentParser(description="S18A report by exception: keep fewer lines, same answers")
    ap.add_argument("--glob", required=True, help="input files, e.g. 'DIR/*.jsonl.gz' (the contract of fleet/check_log.py)")
    ap.add_argument("--rules", required=True, choices=RULES)
    ap.add_argument("--heartbeat-s", type=positive, default=DEFAULT_HEARTBEAT_S,
                    help="H: the longest interval the reducer may create (default 60; used by gap and above)")
    ap.add_argument("--servicing-max-s", type=servicing_number, default=None, metavar="S",
                    help="the S14A station time bound the full-log analysis used, a number (never 'auto')")
    ap.add_argument("--stations", type=stations_path, default=None, help="stations PATH the full-log analysis used (optional)")
    ap.add_argument("--station-radius", type=int, default=0, help="with --stations: Manhattan radius (default 0)")
    ap.add_argument("--out", required=True, help="output directory (kept lines, same file names)")
    a = ap.parse_args(argv)
    if a.station_radius < 0:
        ap.error("--station-radius must be >= 0")
    paths = sorted(_glob.glob(a.glob))
    if not paths:
        print(f"reduce: no files match {a.glob}", file=sys.stderr)
        return 2
    red = Reducer(paths, a.stations, a.station_radius, a.servicing_max_s)
    red.write(a.rules, a.out, a.heartbeat_s)
    print(json.dumps(red.summary(a.rules, a.heartbeat_s), sort_keys=True, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

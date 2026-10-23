"""Check a robot-state log against the fleet-state contract, field by field. Writes nothing.

Usage: python fleet/check_log.py --glob 'DIR/*.jsonl.gz' [--lines 500]
Reads the first --lines lines of every matched file (gzip detected by magic bytes, so plain .jsonl works too), prints one
table (per required field: how many lines have it, how many parse, the first offending value and the reason
fleet_analyser/parse.py gives for it) and one verdict line. Exit 0: every line read parses. Exit 2: it does not, or no
line could be read.

Tested sources are exactly two: the TA-RWARE simulator through fleet/emit.py, and MoRoOp through
fleet/adapters/moroop.py. Every other source is untested: a MATCH here means these lines pass parse.py, nothing more.
The contract is fleet_analyser/parse.py REQUIRED_FIELDS (docs/SCOPE.md "S5A"); this script holds no copy of it.
"""
import argparse
import glob as _glob
import gzip
import json
import sys
from itertools import islice
from pathlib import Path

FLEET = Path(__file__).resolve().parent
if str(FLEET) not in sys.path:
    sys.path.insert(0, str(FLEET))

from fleet_analyser.parse import OPTIONAL_FIELDS, REQUIRED_FIELDS, check_field, field_value, parse_line  # noqa: E402

GZIP_MAGIC = b"\x1f\x8b"
VALUE_CHARS = 120
NOT_OBJECT = "not a JSON object"


def _open(path):
    with open(path, "rb") as f:
        magic = f.read(2)
    return gzip.open(path, "rb") if magic == GZIP_MAGIC else open(path, "rb")


def read_lines(paths, limit):
    """The first `limit` lines (bytes) of each file."""
    for path in paths:
        with _open(path) as f:
            yield from islice(f, limit)


def _show(value):
    text = repr(value)
    return text if len(text) <= VALUE_CHARS else text[:VALUE_CHARS - 3] + "..."


def scan(lines):
    """Returns (n_lines, n_accepted, n_objects, stats, optional_counts, bad_line). stats[path] = dict(has, ok, first,
    reason); bad_line = (first non-object line repr or None, count of non-object lines)."""
    stats = {f.path: dict(has=0, ok=0, first=None, reason=None) for f in REQUIRED_FIELDS}
    optional = {path: 0 for path, _ in OPTIONAL_FIELDS}
    n = accepted = objects = 0
    non_object = [None, 0]
    for raw in lines:
        n += 1
        if parse_line(raw)[0] is not None:
            accepted += 1
        try:
            obj = json.loads(raw)
        except ValueError:
            obj = None
        if not isinstance(obj, dict):
            non_object[1] += 1
            if non_object[0] is None:
                non_object[0] = _show(raw.rstrip(b"\r\n").decode("utf-8", "replace"))
            continue
        objects += 1
        for f in REQUIRED_FIELDS:
            present, ok, value, reason = check_field(obj, f.path)
            st = stats[f.path]
            st["has"] += present
            st["ok"] += ok
            if not ok and st["first"] is None:
                st["first"] = "<missing>" if not present else _show(value)
                st["reason"] = reason
        for path in optional:
            optional[path] += field_value(obj, path)[0]
    return n, accepted, objects, stats, optional, non_object


def render(n, accepted, objects, stats, optional, non_object):
    """(lines of output, exit code)."""
    rows = [("field", "expected type", "has it", "parses", "first offending value", "reason")]
    for f in REQUIRED_FIELDS:
        st = stats[f.path]
        rows.append((f.path, f.expected, f"{st['has']}/{n}", f"{st['ok']}/{n}", st["first"] or "-", st["reason"] or "-"))
    rows.append((NOT_OBJECT, "-", f"{non_object[1]}/{n}", "-", non_object[0] or "-", "json / type:line"))
    widths = [max(len(r[i]) for r in rows) for i in range(6)]
    out = ["  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip() for r in rows]
    out.append("optional fleet-state/2 fields (never reject, not in the verdict):")
    out += [f"  {path}  {desc}  present in {optional[path]}/{n}" for path, desc in OPTIONAL_FIELDS]
    names = [f.path for f in REQUIRED_FIELDS]
    absent = [p for p in names if stats[p]["has"] == 0]
    if accepted == n:
        out.append(f"check_log: MATCHES the fleet-state contract ({n}/{n} lines parse)")
        return out, 0
    text = f"check_log: DOES NOT MATCH: {len(absent)} of {len(names)} fields missing"
    if absent:
        text += f" ({', '.join(absent)})"
    else:
        failing = [p for p in names if stats[p]["ok"] < objects]
        if failing:
            text += ", failing: " + ", ".join(f"{p} ({stats[p]['reason']})" for p in failing)
    text += (f", {accepted}/{n} lines parse; see docs/SCOPE.md \"S5A\" and fleet/adapters/moroop.py "
             "for how a source is adapted")
    out.append(text)
    return out, 2


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--glob", required=True, help="files to check, e.g. 'DIR/*.jsonl.gz'")
    ap.add_argument("--lines", type=int, default=500, help="lines read from the start of each file (default 500)")
    a = ap.parse_args(argv)
    if a.lines < 1:
        ap.error("--lines must be >= 1")
    paths = sorted(_glob.glob(a.glob))
    if not paths:
        print(f"check_log: no files match {a.glob}")
        return 2
    n, accepted, objects, stats, optional, non_object = scan(read_lines(paths, a.lines))
    if n == 0:
        print(f"check_log: no lines in the {len(paths)} file(s) matching {a.glob}")
        return 2
    out, code = render(n, accepted, objects, stats, optional, non_object)
    print("\n".join(out))
    return code


if __name__ == "__main__":
    sys.exit(main())

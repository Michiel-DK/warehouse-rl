"""Run the fleet stuck analyser on your own log with one command (S19A): check -> ingest -> time budget -> blocking -> report.

Usage: python fleet/run_on_log.py --glob 'DIR/*.jsonl.gz' --stations PATH [--out DIR] [--run NAME]
       [--station-radius 0] [--servicing-max-s S|auto]
Tooling only: it runs the existing scripts (check_log, ingest, timebudget, deadlock, report) as subprocesses in that order
and stops at the first one that exits non-zero, with that exit code. No analysis happens here.
The stations file is {"stations": [[x, y], ...], "shelves": [[x, y], ...]}, cells in the log's grid; see
fleet/data/moroop/stations.json. --out must be absent or empty (exit 2 otherwise): a fresh store is built under it.
Writes OUT/check_log.txt, OUT/store, OUT/timebudget.json, OUT/blocking.json and OUT/report.md (with a header on top).
"""
import argparse
import glob as globmod
import gzip
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FLEET = ROOT / "fleet"
if str(FLEET) not in sys.path:
    sys.path.insert(0, str(FLEET))

from fleet_analyser import servicing  # noqa: E402

SENTENCE = ("Descriptive, not graded: this log carries no right answers, so no figure here is a hit rate. "
            "The blocking number compares shifts; it does not say where.")
STEPS = ("check_log", "ingest", "timebudget", "deadlock", "report")


def _git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)


def step_version(script):
    """Short sha of the last commit touching the script, ' (modified)' when the working tree differs; 'unknown' without git."""
    rel = f"fleet/{script}.py"
    try:
        r = _git("log", "-1", "--format=%h", "--", rel)
    except OSError:
        return "unknown"
    sha = r.stdout.strip()
    if r.returncode != 0 or not sha:
        return "unknown"
    return sha + (" (modified)" if _git("diff", "--quiet", "HEAD", "--", rel).returncode != 0 else "")


def line_count(paths):
    n = 0
    for p in paths:
        with gzip.open(p, "rb") as f:
            n += sum(1 for _ in f)
    return n


def header(glob, stations, n_lines):
    """Prepended to report.md. Holds nothing that differs between two runs on the same input (no OUT, no time)."""
    out = ["<!-- run_on_log header -->", "", f"- input: `{glob}`, {n_lines} lines",
           f"- stations: `{stations}`", "- step versions (last commit touching the script):"]
    out += [f"  - {s}: {step_version(s)}" for s in STEPS]
    out += [f"  - run_on_log: {step_version('run_on_log')}", "", SENTENCE, "", "<!-- end run_on_log header -->", ""]
    return "\n".join(out) + "\n"


def run_step(name, args):
    r = subprocess.run([sys.executable, str(FLEET / f"{name}.py"), *map(str, args)], capture_output=True, text=True, cwd=ROOT)
    sys.stderr.write(r.stderr)
    return r


def build_parser():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0], epilog=(
        "stations file: {\"stations\": [[x, y], ...], \"shelves\": [[x, y], ...]}, cells in the log's grid "
        "(example: fleet/data/moroop/stations.json)."))
    p.add_argument("--glob", required=True, help="the log: 'DIR/*.jsonl.gz' (files named zone<z>-<nnn>.jsonl.gz)")
    p.add_argument("--stations", required=True,
                   help="PATH of a stations file {\"stations\": [[x, y], ...], \"shelves\": [[x, y], ...]}, cells in the "
                        "log's grid; example fleet/data/moroop/stations.json (no 'auto': that reads the simulator layout)")
    p.add_argument("--out", default=None, help="output directory, absent or empty (default fleet/data/<run>-run-on-log)")
    p.add_argument("--run", default=None, help="run name (default: name of the glob's directory)")
    p.add_argument("--station-radius", type=int, default=0, help="Manhattan radius around a station cell (default 0)")
    p.add_argument("--servicing-max-s", type=servicing.parse_spec, default=None, metavar="S|auto",
                   help="a station stop longer than this many seconds is stuck again; auto = one bound from the log")
    return p


def main(argv=None):
    p = build_parser()
    a = p.parse_args(argv)
    if a.station_radius < 0:
        p.error("--station-radius must be >= 0")
    run = a.run or Path(a.glob).resolve().parent.name
    out = Path(a.out) if a.out else FLEET / "data" / f"{run}-run-on-log"
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        print(f"run_on_log: {out} exists and is not empty; give a fresh --out (nothing was touched)", file=sys.stderr)
        return 2
    if not Path(a.stations).is_file():
        print(f"run_on_log: stations file not found: {a.stations}", file=sys.stderr)
        return 2
    files = sorted(globmod.glob(a.glob))
    out.mkdir(parents=True, exist_ok=True)

    chk = run_step("check_log", ["--glob", a.glob])
    sys.stdout.write(chk.stdout)
    (out / "check_log.txt").write_text(chk.stdout)
    if chk.returncode != 0:
        return chk.returncode

    store = out / "store"
    sv = [] if a.servicing_max_s is None else ["--servicing-max-s", str(a.servicing_max_s)]
    st = ["--stations", a.stations, "--station-radius", str(a.station_radius), *sv]
    steps = [
        ("ingest", ["--source", "file", "--once", "--min-accepted", "0.5", "--glob", a.glob, "--run", run,
                    "--store", f"jsonl:{store}", *st]),
        ("timebudget", ["--glob", a.glob, "--run", run, "--store", f"jsonl:{store}", "--station-aware", *st,
                        "--out", out / "timebudget.json"]),
    ]
    for name, args in steps:
        r = run_step(name, args)
        sys.stdout.write(r.stdout)
        if r.returncode != 0:
            return r.returncode
    with tempfile.TemporaryDirectory(prefix="run_on_log-") as tmp:
        copy = Path(tmp) / "store-copy"
        shutil.copytree(store, copy)
        r = run_step("deadlock", ["--glob", a.glob, "--run", run, "--store", f"jsonl:{copy}", *st,
                                  "--out", out / "blocking.json"])
        sys.stdout.write(r.stdout)
        if r.returncode != 0:
            return r.returncode
    r = run_step("report", ["--run", run, "--store", f"jsonl:{store}", "--timebudget", out / "timebudget.json",
                            "--out", out / "report.md"])
    sys.stdout.write(r.stdout)
    if r.returncode != 0:
        return r.returncode
    rp = out / "report.md"
    rp.write_text(header(a.glob, a.stations, line_count(files)) + rp.read_text())
    print(f"run_on_log: wrote {out}/{{check_log.txt,store,timebudget.json,blocking.json,report.md}}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

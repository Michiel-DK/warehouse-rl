"""Benchmark library: definitions, preflight checks, size estimate, result assembly, atomic JSON, cleanup, results table.

The orchestration (emitting, ingesting, subprocesses) is fleet/benchmark.py; everything here is plain functions over
injected probes and documents, so it is unit-tested without Docker. Definitions: docs/SCOPE.md "S5C2".

Every number in the output comes from a ledger or a result file: the emit ledger (messages, bytes, expected), the ingest
ledger rows (bytes read, messages parsed / accepted, lag), the alert latency file and score.json. The only numbers
measured here are wall times (a timer around a subprocess).
"""
import json
import math
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from .ledger import coverage
from .report import nearest_rank

FLEET = Path(__file__).resolve().parents[1]
REPO = FLEET.parent
DATA_DIR = FLEET / "data"

ENV = "tarware-medium-8agvs-4pickers-globalobs-v1"
STEP_S = 5  # simulated seconds per step
BATCH = dict(zones=8, steps=72000)
LIVE = dict(zones=8, seconds=600)
SMOKE_BATCH = dict(zones=2, steps=300)
SMOKE_LIVE = dict(zones=2, seconds=60)
PROBE = dict(zones=1, steps=200)
MAX_ESTIMATE_BYTES = 6_000_000_000  # abort before emitting when the uncompressed estimate is above this
DATA_CAP_BYTES = 8_000_000_000  # fleet/data (volumes included) must stay under this
DISK_FACTOR = 3  # free disk must be at least this many times the uncompressed estimate
PIP_LINE = "pip install -r fleet/requirements.txt"

BATCH_KEYS = ("zones", "steps", "robots", "simulated_hours", "messages_expected", "emit_wall_s", "ingest_wall_s",
              "gb_per_min_uncompressed", "gb_per_min_compressed", "msgs_per_s", "coverage", "grades", "score")
LIVE_KEYS = ("duration_s", "msgs_per_s", "lag_p50_s", "lag_p99_s", "alert_latency_from_entry_p50_s",
             "alert_latency_from_entry_p99_s", "alert_latency_from_start_p50_s", "alert_latency_from_start_p99_s",
             "coverage", "score")
# What stays in a finished run directory: the ledgers (emit, ingest, decision), score.json, report.md and every *.png.
KEEP_NAMES = ("emit_ledger.json", "ingest_ledger.json", "decision_ledger.json", "score.json", "report.md")
KEEP_SUFFIXES = (".png",)


class PreflightError(Exception):
    """A failed preflight check; str() is the one stderr line (without the `error: ` prefix)."""


# ------------------------------------------------------------------------------------------------ workers
def resolve_workers(cli_value, environ=os.environ):
    """--workers, else SCHED_WORKERS, else os.cpu_count() - 2 (the repo's rule; scripts/evaluate.resolve_workers)."""
    for p in (REPO / "src", REPO / "scripts"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    import evaluate as ev

    return ev.resolve_workers(cli_value, environ)


# ------------------------------------------------------------------------------------------------ probes
class Probes:
    """The host facts the preflight reads; tests pass a fake with the same methods."""

    def in_linux_container(self):
        if platform.system() != "Linux":
            return False
        if Path("/.dockerenv").exists():
            return True
        try:
            text = Path("/proc/1/cgroup").read_text()
        except OSError:
            return False
        return any(w in text for w in ("docker", "kubepods", "containerd", "libpod"))

    def docker_info(self):
        """(ok, why)."""
        try:
            r = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as e:
            return False, str(e)
        return r.returncode == 0, (r.stderr.strip().splitlines() or ["docker info failed"])[-1]

    def kafka_importable(self):
        try:
            import confluent_kafka  # noqa: F401
        except ImportError:
            return False
        return True

    def clickhouse_reachable(self, url):
        try:
            with urllib.request.urlopen(f"{url}/ping", timeout=5) as r:
                return r.status == 200
        except OSError:
            return False

    def redpanda_reachable(self, bootstrap):
        host, _, port = bootstrap.rpartition(":")
        try:
            with socket.create_connection((host or "localhost", int(port)), timeout=5):
                return True
        except (OSError, ValueError):
            return False

    def disk_free_bytes(self, path):
        return shutil.disk_usage(path).free

    def tree_bytes(self, path):
        total = 0
        for root, _, files in os.walk(path):
            for f in files:
                try:
                    total += os.lstat(os.path.join(root, f)).st_size
                except OSError:
                    pass
        return total


def check_environment(probes, clickhouse_url, bootstrap):
    """The static preflight, in order; raises PreflightError with one line for the first failure."""
    if probes.in_linux_container():
        raise PreflightError("running inside a Linux container: the vendored A* breaks ties differently on Linux, so the "
                             "simulator must run on the macOS host; run benchmark.py on the host")
    ok, why = probes.docker_info()
    if not ok:
        raise PreflightError(f"`docker info` failed ({why}); start Docker, then fleet/compose.sh up")
    if not probes.kafka_importable():
        raise PreflightError(f"confluent_kafka is not importable; run: {PIP_LINE}")
    if not probes.clickhouse_reachable(clickhouse_url):
        raise PreflightError(f"ClickHouse is not reachable at {clickhouse_url}; run fleet/compose.sh up")
    if not probes.redpanda_reachable(bootstrap):
        raise PreflightError(f"Redpanda is not reachable at {bootstrap}; run fleet/compose.sh up")


def estimate(probe_doc, zones, steps):
    """Size of a (zones x steps) batch from a probe's emit ledger: bytes per message times the message count."""
    total = probe_doc["total"]
    robots = probe_doc["zones"][0]["robots"]
    per_unc = total["bytes_uncompressed"] / total["messages"]
    per_comp = (total["bytes_compressed"] or 0) / total["messages"]
    messages = zones * steps * robots
    return dict(bytes_per_message=per_unc, compressed_bytes_per_message=per_comp, messages=messages,
                uncompressed_bytes=int(per_unc * messages), compressed_bytes=int(per_comp * messages))


def check_sizes(probes, est, data_dir=DATA_DIR):
    """Size preflight on an estimate(): the 6 GB uncompressed ceiling, free disk >= 3x the estimate, and fleet/data (what
    is there plus the compressed files the batch will add) under 8 GB."""
    unc = est["uncompressed_bytes"]
    if unc > MAX_ESTIMATE_BYTES:
        raise PreflightError(f"estimated batch is {unc / 1e9:.2f} GB uncompressed, above the {MAX_ESTIMATE_BYTES / 1e9:.0f} "
                             f"GB ceiling; nothing was emitted")
    path = data_dir if Path(data_dir).exists() else Path(data_dir).parent
    free = probes.disk_free_bytes(path)
    if free < DISK_FACTOR * unc:
        raise PreflightError(f"free disk {free / 1e9:.2f} GB is below {DISK_FACTOR}x the estimated "
                             f"{unc / 1e9:.2f} GB uncompressed batch")
    have = probes.tree_bytes(data_dir) if Path(data_dir).exists() else 0
    if have + est["compressed_bytes"] > DATA_CAP_BYTES:
        raise PreflightError(f"fleet/data would reach {(have + est['compressed_bytes']) / 1e9:.2f} GB, above the "
                             f"{DATA_CAP_BYTES / 1e9:.0f} GB cap")


# ------------------------------------------------------------------------------------------------ output document
def atomic_write_json(path, doc):
    """tmp file in the same directory, fsync, os.replace: a killed run never leaves a torn file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def machine_facts(disk_path, docker_version):
    try:
        ram = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        ram = 0
    free = shutil.disk_usage(disk_path).free
    return dict(cores=os.cpu_count(), ram_gb=round(ram / 2 ** 30, 1), disk_free_gb=round(free / 1e9, 1),
                docker_version=docker_version)


def docker_version():
    try:
        r = subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"], capture_output=True, text=True,
                           timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() or None


def git_sha(repo=REPO):
    try:
        r = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() or None


def platform_string():
    return f"{platform.platform()} {platform.machine()}"


def not_run(reason):
    return {"not_run": reason}


def finished(leg):
    return isinstance(leg, dict) and "not_run" not in leg


def new_doc(platform_str, machine, sha):
    return dict(platform=platform_str, machine=machine, git_sha=sha, batch=not_run("batch leg not run yet"),
                live=not_run("live leg not run yet"))


def load_previous(path, sha):
    """The finished legs of an earlier document at `path` for the same git sha, else {}: a re-run skips them."""
    try:
        old = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(old, dict) or old.get("git_sha") != sha:
        return {}
    return {k: old[k] for k in ("batch", "live") if finished(old.get(k))}


# ------------------------------------------------------------------------------------------------ leg metrics
def _sum(rows, key):
    return sum(r[key] or 0 for r in rows)


def grade_counts(decisions):
    """{kind: {verdict or 'open': n}} over a run's decisions (a decision that is not graded counts as open)."""
    out = {}
    for d in decisions:
        v = d["verdict"] if d["status"] == "graded" else "open"
        k = out.setdefault(d["kind"], {})
        k[str(v)] = k.get(str(v), 0) + 1
    return out


def batch_metrics(zones, steps, emit_doc, ingest_rows, expected_messages, emit_wall_s, ingest_wall_s, grades, score):
    """The `batch` object. Throughput columns are the ingest's: bytes read and messages parsed (ingest ledger rows) over
    the ingest wall time. messages_expected and robots come from the emit ledger, coverage = accepted / expected."""
    total, wall = emit_doc["total"], max(ingest_wall_s, 1e-9)
    return dict(
        zones=zones, steps=steps, robots=emit_doc["zones"][0]["robots"], simulated_hours=steps * STEP_S / 3600,
        messages_expected=total["expected_messages"], emit_wall_s=emit_wall_s, ingest_wall_s=ingest_wall_s,
        gb_per_min_uncompressed=_sum(ingest_rows, "bytes_read_uncompressed") / 1e9 / (wall / 60),
        gb_per_min_compressed=_sum(ingest_rows, "bytes_read_compressed") / 1e9 / (wall / 60),
        msgs_per_s=_sum(ingest_rows, "messages_parsed") / wall,
        coverage=coverage(_sum(ingest_rows, "messages_accepted"), expected_messages), grades=grades, score=score)


def live_metrics(duration_s, emit_doc, ingest_rows, expected_messages, latency_lines, score):
    """The `live` object. msgs_per_s = emitted messages (emit ledger) over the emitter's wall time. Lag comes from the
    per-minute ingest-ledger percentiles: lag_p50_s is the nearest-rank median of the minutes' p50, lag_p99_s the largest
    minute p99. Alert latencies are nearest-rank percentiles over the latency-file lines flagged meaningful."""
    p50s = [r["lag_p50_s"] for r in ingest_rows if r["lag_p50_s"] is not None]
    p99s = [r["lag_p99_s"] for r in ingest_rows if r["lag_p99_s"] is not None]
    ok = [ln for ln in latency_lines if ln.get("meaningful")]
    entry = [ln["latency_from_entry_s"] for ln in ok]
    start = [ln["latency_from_start_s"] for ln in ok]
    return dict(
        duration_s=duration_s, msgs_per_s=emit_doc["total"]["messages"] / max(duration_s, 1e-9),
        lag_p50_s=nearest_rank(p50s, 0.5), lag_p99_s=max(p99s) if p99s else None,
        alert_latency_from_entry_p50_s=nearest_rank(entry, 0.5), alert_latency_from_entry_p99_s=nearest_rank(entry, 0.99),
        alert_latency_from_start_p50_s=nearest_rank(start, 0.5), alert_latency_from_start_p99_s=nearest_rank(start, 0.99),
        coverage=coverage(_sum(ingest_rows, "messages_accepted"), expected_messages), score=score)


def read_jsonl(path):
    try:
        return [json.loads(ln) for ln in Path(path).read_text().splitlines() if ln.strip()]
    except OSError:
        return []


# ------------------------------------------------------------------------------------------------ run directory
def export_ledgers(store, run, directory):
    """Write the run's ingest ledger and decision ledger rows next to the emit ledger (before cleanup removes the rest)."""
    directory = Path(directory)
    for name, rows in (("ingest_ledger.json", store.select("ingest_ledger", {"run": run})),
                       ("decision_ledger.json", [d for d in store.select("decisions") if d["run"] == run])):
        (directory / name).write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def cleanup_run_dir(directory):
    """Leave only the ledgers (KEEP_NAMES), score.json, report.md and *.png; delete everything else, directories too."""
    directory = Path(directory)
    removed = []
    for p in sorted(directory.iterdir()):
        if p.is_file() and (p.name in KEEP_NAMES or p.suffix in KEEP_SUFFIXES):
            continue
        shutil.rmtree(p) if p.is_dir() and not p.is_symlink() else p.unlink()
        removed.append(p.name)
    return removed


# ------------------------------------------------------------------------------------------------ results table
def numeric_leaves(obj, prefix=""):
    """(dotted path, float) for every numeric leaf of a JSON value. Booleans, None, NaN, inf and strings are not
    numeric leaves; list indices go into the path (a.0.b)."""
    if isinstance(obj, dict):
        for k in sorted(obj):
            yield from numeric_leaves(obj[k], f"{prefix}.{k}" if prefix else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from numeric_leaves(v, f"{prefix}.{i}" if prefix else str(i))
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool) and math.isfinite(obj):
        yield prefix, float(obj)


def _as_doc(x):
    if x is None or isinstance(x, dict):
        return x
    return json.loads(Path(x).read_text())


def load_results(store, benchmark_json=None, score_json=None, clock=time.time):
    """Insert one `results` row per numeric leaf (key = dotted path) of benchmark.json (kind `benchmark`, run = its git
    sha) and of score.json (kind `score`, run = its `run`). Arguments are paths or already-parsed dicts. Insert-only: a
    reload appends rows with a later loaded_at (readers take argMax(value, loaded_at)). Returns the number of rows."""
    now = clock()
    rows = []
    bench, sc = _as_doc(benchmark_json), _as_doc(score_json)
    if bench is not None:
        run = str(bench.get("git_sha") or "benchmark")
        rows += [dict(kind="benchmark", run=run, key=k, value=v, text=None, loaded_at=now)
                 for k, v in numeric_leaves(bench)]
    if sc is not None:
        rows += [dict(kind="score", run=str(sc["run"]), key=k, value=v, text=None, loaded_at=now)
                 for k, v in numeric_leaves(sc)]
    if rows:
        store.insert("results", rows)
    return len(rows)

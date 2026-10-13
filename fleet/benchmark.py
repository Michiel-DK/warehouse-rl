"""Benchmark the fleet pipeline end to end on this host: one big batch leg and one real-time live leg.

Usage: python fleet/benchmark.py [--workers N] [--smoke] [--out results/fleet/benchmark.json] [--force]
Needs the stack up (`fleet/compose.sh up`) and `pip install -r fleet/requirements.txt`. The simulator runs on the host,
never in a container (the vendored A* breaks ties differently on Linux). Workers: --workers, else SCHED_WORKERS, else
os.cpu_count() - 2.
  batch: 8 zones x 72000 steps of the medium map, emitted flat out (--t0 now) to files, then ingested from cold into
         ClickHouse; the estimate (bytes per message from a 1-zone 200-step probe) must be <= 6 GB uncompressed.
  live:  8 zones for 600 s with --sink kafka --t0 now --rate realtime --speed 1, the kafka ingester and the alert running
         alongside; a latency test (about 19 messages/s), not a throughput test.
  --smoke: 2 zones x 300 steps and a 60 s live leg on 2 zones, written to a tmp path by default (never under results/).
Preflight (one stderr line, exit 2, nothing emitted): inside a Linux container, `docker info`, confluent_kafka, ClickHouse,
Redpanda, the 6 GB estimate, free disk >= 3x the estimate, fleet/data under 8 GB. The JSON is rewritten atomically after
each leg; a leg already finished for this git sha and definition is skipped on a re-run (--force reruns). The scorer runs
before cleanup; a finished run directory keeps only its ledgers, score.json, report.md and *.png. Logic: fleet_analyser/bench.py.
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

FLEET = Path(__file__).resolve().parent
if str(FLEET) not in sys.path:
    sys.path.insert(0, str(FLEET))

from fleet_analyser import bench, store as store_mod  # noqa: E402

REPO = bench.REPO
PY = sys.executable
SCRIPTS = {name: str(FLEET / f"{name}.py") for name in ("emit", "ingest", "grade", "score", "report", "alert")}
LOG_TAIL = 300


class LegError(Exception):
    """A leg failed after the preflight passed; str() is the reason recorded in the JSON as {not_run: reason}."""


def clickhouse_port():
    return int(os.environ.get("FLEET_CLICKHOUSE_PORT", "18123"))


def kafka_bootstrap():
    return f"localhost:{os.environ.get('FLEET_KAFKA_PORT', '19092')}"


class Runner:
    """The real legs: subprocesses of the fleet CLIs. main() takes any object with facts / probe / batch / live."""

    def __init__(self, workers, smoke):
        self.workers, self.smoke = workers, smoke
        self.spec = f"clickhouse://127.0.0.1:{clickhouse_port()}/fleet"
        self.stamp = time.strftime("%Y%m%dT%H%M%S")

    # ---------------------------------------------------------------- helpers
    def name(self, leg):
        return f"bench-{'smoke-' if self.smoke else ''}{leg}-{self.stamp}"

    def sh(self, label, args):
        r = subprocess.run([PY, *map(str, args)], capture_output=True, text=True)
        if r.returncode != 0:
            tail = ((r.stderr or r.stdout).strip().splitlines() or ["no output"])[-1][:LOG_TAIL]
            raise LegError(f"{label} failed (exit {r.returncode}): {tail}")
        return r

    def popen(self, directory, label, args):
        log = open(Path(directory) / f"{label}.log", "w")
        return subprocess.Popen([PY, *map(str, args)], stdout=log, stderr=subprocess.STDOUT)

    def log_tail(self, directory, label):
        try:
            return ((Path(directory) / f"{label}.log").read_text().strip().splitlines() or ["no output"])[-1][:LOG_TAIL]
        except OSError:
            return "no log"

    # ---------------------------------------------------------------- interface used by main()
    def facts(self):
        machine = bench.machine_facts(FLEET, bench.docker_version())
        return bench.platform_string(), machine, bench.git_sha()

    def probe(self):
        """Emit 1 zone x 200 steps to a tmp directory and return its emit ledger (the bytes-per-message source)."""
        with tempfile.TemporaryDirectory() as tmp:
            self.sh("probe emit", [SCRIPTS["emit"], "--zones", bench.PROBE["zones"], "--steps", bench.PROBE["steps"],
                                   "--env", bench.ENV, "--t0", "now", "--workers", 1, "--sink", "file", "--dir", tmp])
            return json.loads((Path(tmp) / "emit_ledger.json").read_text())

    def score_and_report(self, run, directory, score_args):
        self.sh("score", [SCRIPTS["score"], "--run", run, "--store", self.spec, "--out", Path(directory) / "score.json",
                          *score_args])
        self.sh("report", [SCRIPTS["report"], "--run", run, "--store", self.spec, "--out", Path(directory) / "report.md"])

    def batch(self, zones, steps):
        run = self.name("batch")
        d = bench.DATA_DIR / run
        d.mkdir(parents=True)
        t = time.monotonic()
        self.sh("emit", [SCRIPTS["emit"], "--zones", zones, "--steps", steps, "--env", bench.ENV, "--t0", "now",
                         "--workers", self.workers, "--sink", "file", "--dir", d])
        emit_wall = time.monotonic() - t
        t = time.monotonic()
        self.sh("ingest", [SCRIPTS["ingest"], "--source", "file", "--glob", d / "*.jsonl.gz", "--run", run, "--store",
                           self.spec, "--once"])
        ingest_wall = time.monotonic() - t
        self.sh("grade", [SCRIPTS["grade"], "--run", run, "--store", self.spec, "--once"])
        self.score_and_report(run, d, ["--glob", d / "*.jsonl.gz"])  # the scorer reads the zone files: before cleanup
        st = store_mod.open_store(self.spec, run)
        try:
            emit_doc = json.loads((d / "emit_ledger.json").read_text())
            rows = st.select("ingest_ledger", {"run": run})
            expected = (st.select("ingest_runs", {"run": run}) or [{}])[0].get("expected_messages")
            grades = bench.grade_counts([x for x in st.select("decisions") if x["run"] == run])
            score = json.loads((d / "score.json").read_text())
            bench.export_ledgers(st, run, d)
        finally:
            st.close()
        bench.cleanup_run_dir(d)
        return bench.batch_metrics(emit_doc, rows, expected, emit_wall, ingest_wall, grades, score)

    def ensure_topic(self, topic, partitions=4):
        from confluent_kafka.admin import AdminClient, NewTopic

        admin = AdminClient({"bootstrap.servers": kafka_bootstrap()})  # keep the handle alive until the futures resolve
        futures = admin.create_topics([NewTopic(topic, num_partitions=partitions, replication_factor=1)])
        for f in futures.values():
            try:
                f.result(30)
            except Exception as e:  # noqa: BLE001  (an existing topic is fine; anything else is a leg failure)
                if "EXISTS" not in str(e).upper():
                    raise LegError(f"could not create topic {topic}: {str(e)[:LOG_TAIL]}") from e

    def live(self, zones, seconds):
        run = self.name("live")
        d = bench.DATA_DIR / run
        d.mkdir(parents=True)
        topic = f"fleet.{run}"  # a fresh topic per run: old records on fleet.state would mix runs into the score
        boot = kafka_bootstrap()
        procs = {}
        try:
            self.ensure_topic(topic)
            t = time.monotonic()
            procs["emit"] = self.popen(d, "emit", [SCRIPTS["emit"], "--zones", zones, "--steps", seconds // bench.STEP_S,
                                                   "--env", bench.ENV, "--t0", "now", "--workers", self.workers,
                                                   "--rate", "realtime", "--speed", 1, "--sink", "kafka", "--bootstrap",
                                                   boot, "--topic", topic, "--ledger-dir", d])
            procs["ingest"] = self.popen(d, "ingest", [SCRIPTS["ingest"], "--source", "kafka", "--bootstrap", boot,
                                                       "--topic", topic, "--group", f"bench-ingest-{self.stamp}",
                                                       "--run", run, "--emit-ledger", d / "emit_ledger.json",
                                                       "--store", self.spec])
            procs["alert"] = self.popen(d, "alert", [SCRIPTS["alert"], "--run", run, "--store", self.spec, "--poll", 2,
                                                     "--latency-out", d / "alert_latency.jsonl"])
            try:
                code = procs["emit"].wait(timeout=seconds * 3 + 600)
            except subprocess.TimeoutExpired:
                raise LegError("emitter did not finish in time") from None
            duration = time.monotonic() - t
            if code != 0:
                raise LegError(f"emit failed (exit {code}): {self.log_tail(d, 'emit')}")
            emit_doc = json.loads((d / "emit_ledger.json").read_text())
            expected = emit_doc["total"]["expected_messages"]
            st = store_mod.open_store(self.spec, run)
            try:
                deadline = time.monotonic() + 180
                while time.monotonic() < deadline:  # drain: the ingester has accepted everything the emitter produced
                    if sum(r["messages_accepted"] for r in st.select("ingest_ledger", {"run": run})) >= expected:
                        break
                    if procs["ingest"].poll() is not None:
                        raise LegError(f"ingest exited early (exit {procs['ingest'].returncode}): "
                                       f"{self.log_tail(d, 'ingest')}")
                    time.sleep(2)
                self.stop(procs["ingest"], 60)
                time.sleep(4)  # one more alert poll after the last episode landed
                self.stop(procs["alert"], 30)
                self.score_and_report(run, d, ["--source", "kafka", "--bootstrap", boot, "--topic", topic,
                                               "--group", "fleet-scorer", "--until-idle", 10])
                rows = st.select("ingest_ledger", {"run": run})
                ingested = (st.select("ingest_runs", {"run": run}) or [{}])[0].get("expected_messages")
                score = json.loads((d / "score.json").read_text())
                latency = bench.read_jsonl(d / "alert_latency.jsonl")
                bench.export_ledgers(st, run, d)
            finally:
                st.close()
            bench.cleanup_run_dir(d)
            return bench.live_metrics(duration, emit_doc, rows, ingested, latency, score)
        finally:
            for p in procs.values():
                if p.poll() is None:
                    p.kill()

    @staticmethod
    def stop(proc, timeout):
        if proc.poll() is None:
            proc.send_signal(signal.SIGINT)
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


def leg_matches(name, leg, definition):
    """Is a finished leg from an earlier document the same definition as this run's?"""
    if name == "batch":
        return leg.get("zones") == definition["zones"] and leg.get("steps") == definition["steps"]
    # a paced run ends on its last step, one step short of the nominal duration
    return leg.get("duration_s", 0) >= definition["seconds"] - bench.STEP_S


def main(argv=None, probes=None, runner=None, environ=os.environ):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--workers", type=int, default=None, help="default: SCHED_WORKERS, else os.cpu_count() - 2")
    p.add_argument("--smoke", action="store_true", help="2 zones x 300 steps and a 60 s live leg; tmp output by default")
    p.add_argument("--out", default=None, help="output JSON (default results/fleet/benchmark.json; tmp path in smoke mode)")
    p.add_argument("--force", action="store_true", help="rerun legs that are already finished for this git sha")
    a = p.parse_args(argv)

    def fail(msg):
        print(f"error: {msg}", file=sys.stderr)
        return 2

    out = Path(a.out) if a.out else (Path(tempfile.gettempdir()) / "fleet-benchmark-smoke.json" if a.smoke
                                     else REPO / "results" / "fleet" / "benchmark.json")
    if a.smoke and (REPO / "results").resolve() in [out.resolve(), *out.resolve().parents]:
        return fail(f"--smoke never writes under results/ (got --out {out}); the real benchmark is the queue item")
    try:
        workers = bench.resolve_workers(a.workers, environ)
    except ValueError as e:
        return fail(str(e))
    batch_def, live_def = (bench.SMOKE_BATCH, bench.SMOKE_LIVE) if a.smoke else (bench.BATCH, bench.LIVE)
    if live_def["zones"] > workers:
        return fail(f"the live leg paces {live_def['zones']} zones in real time and needs --workers >= "
                    f"{live_def['zones']} (got {workers})")
    probes = probes or bench.Probes()
    runner = runner or Runner(workers, a.smoke)
    try:
        bench.check_environment(probes, f"http://127.0.0.1:{clickhouse_port()}", kafka_bootstrap())
        est = bench.estimate(runner.probe(), batch_def["zones"], batch_def["steps"])
        bench.check_sizes(probes, est)
    except bench.PreflightError as e:
        return fail(str(e))
    except LegError as e:
        return fail(f"preflight probe failed: {e}")

    platform_str, machine, sha = runner.facts()
    doc = bench.new_doc(platform_str, machine, sha)
    previous = {} if a.force else bench.load_previous(out, sha)
    failed = False
    for name, definition in (("batch", batch_def), ("live", live_def)):
        leg = previous.get(name)
        if leg is not None and leg_matches(name, leg, definition):
            doc[name] = leg
            print(f"{name} leg: already finished for git sha {sha}, skipped (--force reruns)")
        else:
            try:
                if name == "batch":
                    doc[name] = runner.batch(definition["zones"], definition["steps"])
                else:
                    doc[name] = runner.live(definition["zones"], definition["seconds"])
            except LegError as e:
                doc[name] = bench.not_run(str(e))
                failed = True
                print(f"{name} leg failed: {e}", file=sys.stderr)
        bench.atomic_write_json(out, doc)
    print(f"benchmark written to {out}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

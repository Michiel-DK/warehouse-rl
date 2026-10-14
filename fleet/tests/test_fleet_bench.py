"""Tests for the benchmark (fleet/benchmark.py, fleet_analyser/bench.py) and the results-table loader. Unit tests only: the
probes and the runner are injected, so there is no Docker, no network and no simulator. The real thing is exercised by
`fleet/benchmark.py --smoke` (quoted in the PR). Each case names its red demonstration in an `# inject:` comment. None skipped."""
import contextlib
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "fleet", ROOT / "src", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import benchmark as cli  # noqa: E402
from fleet_analyser import bench  # noqa: E402
from fleet_analyser.store import MemoryStore  # noqa: E402


# ------------------------------------------------------------------------------------------------ fakes
class OkProbes:
    """All preflight probes pass; a test breaks exactly one by overriding an attribute."""
    container = False
    docker = (True, "")
    kafka = True
    clickhouse = True
    redpanda = True
    free = 10 ** 12
    data = 0

    def in_linux_container(self):
        return self.container

    def docker_info(self):
        return self.docker

    def kafka_importable(self):
        return self.kafka

    def clickhouse_reachable(self, url):
        return self.clickhouse

    def redpanda_reachable(self, bootstrap):
        return self.redpanda

    def disk_free_bytes(self, path):
        return self.free

    def tree_bytes(self, path):
        return self.data


def ledger_doc(per_message=800, compressed=80, messages=2400, robots=12):
    """A probe's emit ledger, with the byte counts the estimate reads."""
    return {"total": {"messages": messages, "bytes_uncompressed": per_message * messages,
                      "bytes_compressed": compressed * messages, "expected_messages": messages},
            "zones": [{"robots": robots}]}


def metrics_batch(**kw):
    return dict(dict.fromkeys(bench.BATCH_KEYS, 1), **kw)


class FakeRunner:
    def __init__(self, probe=None):
        self.calls, self._probe = [], probe or ledger_doc()

    def facts(self):
        return "plat", {"cores": 4, "ram_gb": 8.0, "disk_free_gb": 1.0, "docker_version": "1"}, "sha1"

    def probe(self):
        self.calls.append("probe")
        return self._probe

    def batch(self, zones, steps):
        self.calls.append(("batch", zones, steps))
        return metrics_batch(zones=zones, steps=steps)

    def live(self, zones, seconds):
        self.calls.append(("live", zones, seconds))
        return dict(dict.fromkeys(bench.LIVE_KEYS, 2), duration_s=float(seconds))


def run_main(argv, probes=None, runner=None, environ=None):
    err = io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
        code = cli.main(argv, probes=probes or OkProbes(), runner=runner or FakeRunner(),
                        environ={} if environ is None else environ)
    return code, err.getvalue()


class TestWorkers(unittest.TestCase):
    def test_workers_flag_then_sched_workers_then_cpu_count_minus_two(self):
        # inject: read SCHED_WORKERS before --workers, or use os.cpu_count() without the minus two
        with mock.patch("os.cpu_count", return_value=10):
            self.assertEqual(bench.resolve_workers(3, {"SCHED_WORKERS": "6"}), 3)
            self.assertEqual(bench.resolve_workers(None, {"SCHED_WORKERS": "6"}), 6)
            self.assertEqual(bench.resolve_workers(None, {}), 8)
            self.assertEqual(bench.resolve_workers(None, {"SCHED_WORKERS": ""}), 8)

    def test_the_live_leg_needs_as_many_workers_as_zones(self):
        # inject: drop the zones > workers check (the emitter would then refuse the realtime run mid-leg)
        r = FakeRunner()
        with tempfile.TemporaryDirectory() as tmp:
            code, err = run_main(["--workers", "4", "--out", f"{tmp}/b.json"], runner=r)
            self.assertEqual(code, 2)
            self.assertEqual(len(err.strip().splitlines()), 1)
            self.assertIn("--workers >= 8", err)
            self.assertEqual(r.calls, [])
            code, _ = run_main(["--smoke", "--workers", "2", "--out", f"{tmp}/s.json"], runner=r)
            self.assertEqual(code, 0)


class TestPreflight(unittest.TestCase):
    """One check per test: exactly one stderr line, exit code 2, no leg started, no output file written."""

    def check(self, probes=None, runner=None, needle=""):
        runner = runner or FakeRunner()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "b.json"
            code, err = run_main(["--workers", "8", "--out", str(out)], probes=probes, runner=runner)
            self.assertEqual(code, 2, err)
            self.assertEqual(len(err.strip().splitlines()), 1, err)
            self.assertTrue(err.startswith("error: "), err)
            self.assertIn(needle, err)
            self.assertFalse(out.exists())
            self.assertFalse([c for c in runner.calls if c != "probe"], runner.calls)

    def test_the_baseline_passes(self):
        # inject: make OkProbes fail one check (then every other test in this class is red for the wrong reason)
        r = FakeRunner()
        with tempfile.TemporaryDirectory() as tmp:
            code, err = run_main(["--workers", "8", "--out", f"{tmp}/b.json"], runner=r)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(r.calls, ["probe", ("batch", 8, 72000), ("live", 8, 600)])

    def test_docker_info_fails(self):
        # inject: skip the docker check
        p = OkProbes()
        p.docker = (False, "Cannot connect to the Docker daemon")
        self.check(p, needle="`docker info` failed")

    def test_clickhouse_unreachable(self):
        # inject: skip the ClickHouse check
        p = OkProbes()
        p.clickhouse = False
        self.check(p, needle="ClickHouse is not reachable")

    def test_redpanda_unreachable(self):
        # inject: skip the Redpanda check
        p = OkProbes()
        p.redpanda = False
        self.check(p, needle="Redpanda is not reachable")

    def test_confluent_kafka_not_importable_names_the_install_line(self):
        # inject: skip the import check, or drop the install line from the message
        p = OkProbes()
        p.kafka = False
        self.check(p, needle="pip install -r fleet/requirements.txt")

    def test_free_disk_below_three_times_the_estimate(self):
        # inject: compare against 1x the estimate instead of 3x
        est = bench.estimate(ledger_doc(), 8, 72000)["uncompressed_bytes"]
        p = OkProbes()
        p.free = 3 * est - 1
        self.check(p, needle="below 3x")
        p.free = 3 * est
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(run_main(["--workers", "8", "--out", f"{tmp}/b.json"], probes=p)[0], 0)

    def test_fleet_data_would_exceed_eight_gb(self):
        # inject: ignore what is already in fleet/data, or the compressed bytes the batch adds
        est = bench.estimate(ledger_doc(), 8, 72000)
        p = OkProbes()
        p.data = bench.DATA_CAP_BYTES - est["compressed_bytes"] + 1
        self.check(p, needle="8 GB cap")

    def test_running_inside_a_linux_container(self):
        # inject: skip the container check
        p = OkProbes()
        p.container = True
        self.check(p, needle="Linux container")

    def test_container_detection_reads_dockerenv_or_cgroup_only_on_linux(self):
        # inject: report a container on macOS
        pr = bench.Probes()
        with mock.patch("platform.system", return_value="Darwin"):
            self.assertFalse(pr.in_linux_container())
        with mock.patch("platform.system", return_value="Linux"), mock.patch.object(Path, "exists", return_value=True):
            self.assertTrue(pr.in_linux_container())

    def test_estimate_above_six_gb_aborts_before_emitting(self):
        # inject: raise the ceiling, or run the batch before the estimate check
        n = 8 * 72000 * 12
        over = FakeRunner(ledger_doc(per_message=6_000_000_000 // n + 1))
        self.check(runner=over, needle="above the 6 GB ceiling")
        self.assertEqual(over.calls, ["probe"])
        under = FakeRunner(ledger_doc(per_message=6_000_000_000 // n))
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(run_main(["--workers", "8", "--out", f"{tmp}/b.json"], runner=under)[0], 0)

    def test_the_estimate_is_bytes_per_message_from_the_probe_times_the_message_count(self):
        # inject: use the step count instead of zones x steps x robots
        est = bench.estimate(ledger_doc(per_message=1000, compressed=100, messages=2400), 8, 72000)
        self.assertEqual(est["messages"], 6_912_000)
        self.assertEqual(est["uncompressed_bytes"], 6_912_000_000)
        self.assertEqual(est["compressed_bytes"], 691_200_000)


class TestDefinitions(unittest.TestCase):
    def test_batch_and_live_definitions(self):
        # inject: change a constant (zones, steps, seconds or the env)
        self.assertEqual(bench.ENV, "tarware-medium-8agvs-4pickers-globalobs-v1")
        self.assertEqual((bench.BATCH, bench.LIVE), (dict(zones=8, steps=72000), dict(zones=8, seconds=600)))
        self.assertEqual(8 * 72000 * 12, 6_912_000)
        self.assertEqual(72000 * bench.STEP_S / 3600, 100)
        self.assertEqual((bench.SMOKE_BATCH, bench.SMOKE_LIVE), (dict(zones=2, steps=300), dict(zones=2, seconds=60)))
        self.assertEqual((bench.MAX_ESTIMATE_BYTES, bench.DATA_CAP_BYTES, bench.DISK_FACTOR), (6 * 10 ** 9, 8 * 10 ** 9, 3))

    def test_smoke_runs_the_small_legs_and_the_full_run_the_big_ones(self):
        # inject: ignore --smoke when choosing the definition
        with tempfile.TemporaryDirectory() as tmp:
            r = FakeRunner()
            run_main(["--smoke", "--workers", "8", "--out", f"{tmp}/s.json"], runner=r)
            self.assertEqual(r.calls, ["probe", ("batch", 2, 300), ("live", 2, 60)])

    def test_smoke_refuses_an_output_under_results(self):
        # inject: drop the results/ check
        target = ROOT / "results" / "fleet" / "smoke-test-never-written.json"
        r = FakeRunner()
        writes = []
        with mock.patch.object(bench, "atomic_write_json", lambda path, doc: writes.append(path)):  # a regression must not write
            code, err = run_main(["--smoke", "--workers", "8", "--out", str(target)], runner=r)
        self.assertEqual(code, 2)
        self.assertIn("results/", err)
        self.assertEqual(len(err.strip().splitlines()), 1)
        self.assertFalse(target.exists())
        self.assertEqual((writes, r.calls), ([], []))

    def test_smoke_defaults_to_a_tmp_path(self):
        # inject: default the smoke output to results/fleet/benchmark.json
        seen = {}
        with mock.patch.object(bench, "atomic_write_json", lambda path, doc: seen.setdefault("path", Path(path))):
            run_main(["--smoke", "--workers", "8"])
        self.assertEqual(seen["path"].parent, Path(tempfile.gettempdir()))
        self.assertNotIn(str(ROOT / "results"), str(seen["path"]))


class TestOutput(unittest.TestCase):
    def test_the_document_has_the_specified_keys_and_the_leg_numbers(self):
        # inject: drop a key from batch_metrics / live_metrics or from the top-level document
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "b.json"
            self.assertEqual(run_main(["--workers", "8", "--out", str(out)])[0], 0)
            doc = json.loads(out.read_text())
        self.assertEqual(set(doc), {"platform", "machine", "git_sha", "batch", "live"})
        self.assertEqual(set(doc["machine"]), {"cores", "ram_gb", "disk_free_gb", "docker_version"})
        self.assertEqual(set(doc["batch"]), set(bench.BATCH_KEYS))
        self.assertEqual(set(doc["live"]), set(bench.LIVE_KEYS))

    def test_batch_metrics_come_from_the_ledgers(self):
        # inject: use the compressed bytes for the uncompressed GB/min, or read zones / steps from a constant, not the emit ledger
        emit = {"total": {"expected_messages": 7200}, "zones": [{"robots": 12, "steps": 300}] * 2}
        rows = [dict(bytes_read_uncompressed=3 * 10 ** 9, bytes_read_compressed=3 * 10 ** 8, messages_parsed=7000,
                     messages_accepted=6000),
                dict(bytes_read_uncompressed=3 * 10 ** 9, bytes_read_compressed=3 * 10 ** 8, messages_parsed=200,
                     messages_accepted=200)]
        m = bench.batch_metrics(emit, rows, 7200, 5.0, 120.0, {"stuck_cause": {"open": 1}}, {"precision": 0.5})
        self.assertEqual(set(m), set(bench.BATCH_KEYS))
        self.assertAlmostEqual(m["gb_per_min_uncompressed"], 3.0)  # 6 GB in 2 minutes
        self.assertAlmostEqual(m["gb_per_min_compressed"], 0.3)
        self.assertAlmostEqual(m["msgs_per_s"], 60.0)
        self.assertAlmostEqual(m["coverage"], 6200 / 7200)
        self.assertEqual((m["robots"], m["messages_expected"], m["zones"], m["steps"]), (12, 7200, 2, 300))
        self.assertAlmostEqual(m["simulated_hours"], 300 * 5 / 3600)
        self.assertEqual((m["emit_wall_s"], m["ingest_wall_s"]), (5.0, 120.0))

    def test_live_metrics_use_meaningful_latencies_only_and_the_ledger_lags(self):
        # inject: include lines flagged not meaningful, take the mean of the minute p99s instead of their maximum
        emit = {"total": {"messages": 1200, "expected_messages": 1200}}
        rows = [dict(lag_p50_s=1.0, lag_p99_s=3.0, messages_accepted=600), dict(lag_p50_s=3.0, lag_p99_s=9.0, messages_accepted=600),
                dict(lag_p50_s=2.0, lag_p99_s=5.0, messages_accepted=0), dict(lag_p50_s=None, lag_p99_s=None, messages_accepted=0)]
        lines = [dict(meaningful=True, latency_from_entry_s=float(i), latency_from_start_s=float(i) + 30) for i in range(1, 101)]
        lines.append(dict(meaningful=False, latency_from_entry_s=10 ** 6, latency_from_start_s=10 ** 6))
        m = bench.live_metrics(60.0, emit, rows, 1200, lines, {"precision": None})
        self.assertEqual(set(m), set(bench.LIVE_KEYS))
        self.assertEqual((m["lag_p50_s"], m["lag_p99_s"]), (2.0, 9.0))
        self.assertEqual((m["alert_latency_from_entry_p50_s"], m["alert_latency_from_entry_p99_s"]), (50.0, 99.0))
        self.assertEqual((m["alert_latency_from_start_p50_s"], m["alert_latency_from_start_p99_s"]), (80.0, 129.0))
        self.assertEqual((m["msgs_per_s"], m["coverage"]), (20.0, 1.0))
        none = bench.live_metrics(60.0, emit, [], 1200, [], None)
        self.assertEqual((none["lag_p99_s"], none["alert_latency_from_entry_p50_s"], none["coverage"]), (None, None, 0.0))

    def test_grade_counts_group_by_kind_and_count_ungraded_as_open(self):
        # inject: use the verdict of an ungraded decision
        ds = [dict(kind="k", status="graded", verdict="confirmed"), dict(kind="k", status="open", verdict="confirmed"),
              dict(kind="k", status="graded", verdict="confirmed"), dict(kind="j", status="open", verdict=None)]
        self.assertEqual(bench.grade_counts(ds), {"k": {"confirmed": 2, "open": 1}, "j": {"open": 1}})

    def test_a_live_leg_failure_is_recorded_as_not_run_and_keeps_the_batch(self):
        # inject: let the LegError escape main, or discard the batch leg when the live leg fails
        class Failing(FakeRunner):
            def live(self, zones, seconds):
                raise cli.LegError("kafka went away")

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "b.json"
            code, err = run_main(["--workers", "8", "--out", str(out)], runner=Failing())
            doc = json.loads(out.read_text())
        self.assertEqual(code, 1)
        self.assertEqual(doc["live"], {"not_run": "kafka went away"})
        self.assertEqual(set(doc["batch"]), set(bench.BATCH_KEYS))

    def test_an_empty_topic_creation_timeout_names_its_type_in_the_leg_reason(self):
        # inject: format the LegError with str(e) instead of bench.exc_reason(e)
        import concurrent.futures
        import types

        class Future:
            def result(self, timeout):
                raise concurrent.futures.TimeoutError()  # str() is "" on a real confluent timeout too

        admin = types.ModuleType("confluent_kafka.admin")
        admin.AdminClient = lambda conf: types.SimpleNamespace(create_topics=lambda topics: {"t": Future()})
        admin.NewTopic = lambda *a, **k: None
        with mock.patch.dict(sys.modules, {"confluent_kafka": types.ModuleType("confluent_kafka"),
                                           "confluent_kafka.admin": admin}):
            with self.assertRaises(cli.LegError) as ctx:
                cli.Runner(2, True).ensure_topic("fleet.t")
        self.assertEqual(str(ctx.exception), "could not create topic fleet.t: TimeoutError: timed out")
        self.assertEqual(bench.exc_reason(ValueError("boom")), "boom")

    def test_killed_between_legs_the_finished_leg_is_on_disk(self):
        # inject: write the document once at the end, or write it non-atomically
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "b.json"
            code = (
                "import os, signal, sys\n"
                f"sys.path[:0] = [{str(ROOT)!r}, {str(ROOT / 'fleet')!r}]\n"
                "import benchmark\n"
                "from fleet.tests.test_fleet_bench import FakeRunner, OkProbes\n"
                "class R(FakeRunner):\n"
                "    def live(self, zones, seconds):\n"
                "        os.kill(os.getpid(), signal.SIGKILL)\n"
                f"sys.exit(benchmark.main(['--workers', '8', '--out', {str(out)!r}], probes=OkProbes(), runner=R(), environ={{}}))\n")
            r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT)
            self.assertEqual(r.returncode, -signal.SIGKILL, r.stderr)
            doc = json.loads(out.read_text())  # parses: the write was atomic
            self.assertEqual(set(doc["batch"]), set(bench.BATCH_KEYS))
            self.assertIn("not_run", doc["live"])
            self.assertFalse(list(Path(tmp).glob("*.tmp")))

    def test_a_finished_leg_is_skipped_on_a_rerun_for_the_same_sha_and_definition(self):
        # inject: ignore the previous document, skip a leg of another git sha, or skip when the definition changed
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "b.json"
            first = FakeRunner()
            run_main(["--workers", "8", "--out", str(out)], runner=first)
            again = FakeRunner()
            run_main(["--workers", "8", "--out", str(out)], runner=again)
            self.assertEqual(again.calls, ["probe"])  # both legs finished: nothing reruns
            forced = FakeRunner()
            run_main(["--workers", "8", "--out", str(out), "--force"], runner=forced)
            self.assertEqual(forced.calls, ["probe", ("batch", 8, 72000), ("live", 8, 600)])
            doc = json.loads(out.read_text())
            doc["git_sha"] = "other"
            out.write_text(json.dumps(doc))
            moved = FakeRunner()
            run_main(["--workers", "8", "--out", str(out)], runner=moved)
            self.assertEqual(len(moved.calls), 3)
            doc = json.loads(out.read_text())
            doc["batch"]["steps"] = 100  # a batch of another definition
            doc["live"] = {"not_run": "x"}
            out.write_text(json.dumps(doc))
            redo = FakeRunner()
            run_main(["--workers", "8", "--out", str(out)], runner=redo)
            self.assertEqual(redo.calls, ["probe", ("batch", 8, 72000), ("live", 8, 600)])


class TestCleanup(unittest.TestCase):
    def test_cleanup_leaves_only_ledgers_score_report_and_pngs(self):
        # inject: also keep the *.jsonl.gz zone files, or delete the pngs
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            keep = ["emit_ledger.json", "ingest_ledger.json", "decision_ledger.json", "score.json", "report.md", "hotspots.png"]
            drop = ["zone0-000.jsonl.gz", "zone1-000.jsonl.gz", "alert_latency.jsonl", "emit.log", "emit_ledger.json.tmp"]
            for n in keep + drop:
                (d / n).write_text("x")
            (d / "store").mkdir()
            (d / "store" / "transitions.jsonl").write_text("x")
            removed = bench.cleanup_run_dir(d)
            self.assertEqual(sorted(p.name for p in d.iterdir()), sorted(keep))
            self.assertEqual(sorted(removed), sorted(drop + ["store"]))

    def test_export_ledgers_writes_the_run_rows_before_cleanup(self):
        # inject: export the rows of every run, or skip the decision ledger
        st = MemoryStore()
        st.insert("ingest_ledger", [dict(run="r", minute=1), dict(run="other", minute=2)])
        st.insert("decisions", [dict(run="r", id="a"), dict(run="other", id="b")])
        with tempfile.TemporaryDirectory() as tmp:
            bench.export_ledgers(st, "r", tmp)
            self.assertEqual(json.loads((Path(tmp) / "ingest_ledger.json").read_text()), [dict(run="r", minute=1)])
            self.assertEqual(json.loads((Path(tmp) / "decision_ledger.json").read_text()), [dict(run="r", id="a")])


class TestLoadResults(unittest.TestCase):
    def test_one_row_per_numeric_leaf_with_a_dotted_key(self):
        # inject: write string / bool / None leaves too, or join the path with "/"
        score = {"run": "r1", "precision": 0.5, "recall": None, "matched": 4, "ok": True,
                 "faulted_self": {"count": 20, "frozen_at_entry": 1.0}, "truth_definition": "text",
                 "list": [{"a": 1}, 2], "bad": float("nan")}
        bench_doc = {"git_sha": "abc", "platform": "p", "machine": {"cores": 10},
                     "batch": {"zones": 8, "coverage": 1.0, "grades": {"stuck_cause": {"confirmed": 3}}}, "live": {"not_run": "x"}}
        st = MemoryStore()
        n = bench.load_results(st, bench_doc, score, clock=lambda: 123.0)
        rows = st.select("results")
        self.assertEqual(n, len(rows))
        got = {(r["kind"], r["run"], r["key"]): r["value"] for r in rows}
        self.assertEqual(got, {
            ("score", "r1", "precision"): 0.5, ("score", "r1", "matched"): 4.0, ("score", "r1", "faulted_self.count"): 20.0,
            ("score", "r1", "faulted_self.frozen_at_entry"): 1.0, ("score", "r1", "list.0.a"): 1.0, ("score", "r1", "list.1"): 2.0,
            ("benchmark", "abc", "machine.cores"): 10.0, ("benchmark", "abc", "batch.zones"): 8.0,
            ("benchmark", "abc", "batch.coverage"): 1.0, ("benchmark", "abc", "batch.grades.stuck_cause.confirmed"): 3.0})
        self.assertTrue(all(isinstance(r["value"], float) and r["text"] is None and r["loaded_at"] == 123.0 for r in rows))
        self.assertEqual(set(rows[0]), {"kind", "run", "key", "value", "text", "loaded_at"})

    def test_paths_are_read_and_a_reload_appends_with_a_later_loaded_at(self):
        # inject: upsert instead of insert, or ignore a path argument
        with tempfile.TemporaryDirectory() as tmp:
            b, s = Path(tmp) / "benchmark.json", Path(tmp) / "score.json"
            b.write_text(json.dumps({"git_sha": "g", "batch": {"zones": 2}}))
            s.write_text(json.dumps({"run": "r", "matched": 1}))
            st = MemoryStore()
            ticks = iter([1.0, 2.0])
            self.assertEqual(bench.load_results(st, str(b), s, clock=lambda: next(ticks)), 2)
            self.assertEqual(bench.load_results(st, b, s, clock=lambda: next(ticks)), 2)
            self.assertEqual(sorted((r["key"], r["loaded_at"]) for r in st.select("results")),
                             [("batch.zones", 1.0), ("batch.zones", 2.0), ("matched", 1.0), ("matched", 2.0)])
            self.assertEqual(bench.load_results(st, None, None), 0)

    def test_the_real_clickhouse_store_accepts_the_rows(self):
        # inject: add a column to the rows that schema.sql lacks (the fake ClickHouse rejects unknown fields)
        from fleet.tests.test_fleet_clickhouse_store import fake_store

        fake, st = fake_store(self)
        bench.load_results(st, {"git_sha": "g", "batch": {"zones": 2}}, {"run": "r", "matched": 1}, clock=lambda: 5.0)
        self.assertEqual(sorted((r["kind"], r["key"], r["value"]) for r in st.select("results")),
                         [("benchmark", "batch.zones", 2.0), ("score", "matched", 1.0)])


if __name__ == "__main__":
    unittest.main()

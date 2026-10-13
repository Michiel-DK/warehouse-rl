"""Integration test against REAL ClickHouse in Docker: every fleet/sql/reports/*.sql gives the numbers of the matching
report.py section on the same store. NOT collected by the gate (the file name does not match test_fleet_*.py); run it
explicitly from the repo root:

    .venv/bin/python -m unittest -v fleet.tests.integration_fleet_reports

Skips with a reason when `docker info` fails. Otherwise: starts the clickhouse service (`fleet/compose.sh up
clickhouse`), emits 2 zones x 300 steps on the host (the simulator never runs in a container), ingests them into a
throwaway database, grades once, writes report.md through report.write_report, runs each SQL file with the run as the
{run:String} parameter and compares the numbers section by section. Brings the stack down afterwards. Host port:
FLEET_CLICKHOUSE_PORT (default 18123)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "fleet", ROOT / "src", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fleet.tests.integration_fleet_stack import COMPOSE, PORT, docker_ok  # noqa: E402
from fleet.tests.test_fleet_ingest import emit_real  # noqa: E402
from fleet_analyser import grade, report  # noqa: E402
from fleet_analyser.clickhouse_store import ClickHouseStore  # noqa: E402
from fleet_analyser.ingest import Ingester  # noqa: E402
from fleet_analyser.parse import iso  # noqa: E402

SQL_DIR = ROOT / "fleet" / "sql" / "reports"
RUN = "it-reports"


def sections(md):
    """{heading text: [bullet lines]} of a report.md."""
    out, cur = {}, None
    for ln in md.splitlines():
        if ln.startswith("## "):
            cur = out.setdefault(ln[3:], [])
        elif cur is not None and ln.startswith("- "):
            cur.append(ln)
    return out


def section(secs, prefix):
    (key,) = [k for k in secs if k.startswith(prefix)]
    return secs[key]


def or_none(lines):
    return lines or ["- none"]


# one comparator per SQL file: (rows from the SQL) -> (report.md heading prefix, the bullet lines the report prints)
COMPARATORS = {
    "hotspots": ("Hotspots", lambda rows: or_none([f"- zone {r['zone']} cell {r['x']}-{r['y']}: {r['episodes']}"
                                                   for r in rows])),
    "episodes_per_hour": ("Episodes per event hour", lambda rows: or_none(
        [f"- {iso(r['hour'])}: {r['episodes']}" for r in rows])),
    "duration": ("Duration", lambda rows: [f"- p50: {report.num(rows[0]['p50'])}", f"- p95: {report.num(rows[0]['p95'])}"]),
    "cause_mix": ("Cause mix", lambda rows: or_none([f"- {r['cause_label']}: {r['episodes']}" for r in rows])),
    "resolution_mix": ("Resolution mix", lambda rows: or_none([f"- {r['resolution']}: {r['episodes']}" for r in rows])),
    "avoidable": ("Avoidable", lambda rows: [report_label(), f"- episodes: {report.num(rows[0]['episodes'])}",
                                             f"- minutes: {report.num(rows[0]['minutes'])}"]),
    "repeat_robots": ("Repeat robots", lambda rows: or_none([f"- {r['robot']}: {r['episodes']}" for r in rows])),
    "time_to_resolution": ("Time from stuck to resolution", lambda rows: [
        f"- p50: {report.num(rows[0]['p50'])}", f"- p95: {report.num(rows[0]['p95'])}"]),
    "decision_grades": ("Decision grades", lambda rows: or_none(
        [f"- {r['kind']} / {r['verdict']}: {r['decisions']}" for r in rows])),
}


def report_label():
    return f"- {report.AVOIDABLE_LABEL}"


class TestReportSqlEqualsReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ok, why = docker_ok()
        if not ok:
            raise unittest.SkipTest(f"`docker info` failed, so the real-ClickHouse report test cannot run: {why}")
        cls.addClassCleanup(subprocess.run, [COMPOSE, "down"], capture_output=True, text=True)
        up = subprocess.run([COMPOSE, "up", "clickhouse"], capture_output=True, text=True)
        if up.returncode != 0:
            raise RuntimeError(f"compose.sh up clickhouse failed:\n{up.stdout}\n{up.stderr}")
        cls.db = f"fleet_it_reports_{os.getpid()}"
        cls.url = f"http://127.0.0.1:{PORT}"
        cls.addClassCleanup(lambda: ClickHouseStore(cls.url, cls.db)._post(f"DROP DATABASE IF EXISTS {cls.db}", False))
        cls.store = ClickHouseStore(cls.url, cls.db)
        cls.store.ensure_schema()
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        emit_real(tmp.name, 2, 300, "--t0", "now", "--workers", 2)
        ing = Ingester(str(Path(tmp.name) / "*.jsonl.gz"), RUN, cls.store, poll=0, ledger_interval=0.5,
                       sleep=lambda s: None)
        assert ing.run_loop() == 0
        # rows the countable filter must leave out of every count: censored, still open, interrupted (and a robot name
        # that would be a repeat robot if they counted)
        base = dict(run=RUN, zone="0", robot="Z0-99", order_id="o", start=1.0e9, start_iso="x", t_entry=1.0e9 + 30,
                    cell=[7, 7], cause="traffic", blocker=None, blocker_faulted_s=None, end=1.0e9 + 90,
                    duration_s=90.0, resolution="moved", avoidable=True, avoidable_s=90.0, left_censored=False)
        cls.store.upsert("stuck_episodes", ("run", "episode_id"), [
            dict(base, episode_id="x-censored", left_censored=True),
            dict(base, episode_id="x-open", resolution="open", end=None, duration_s=None),
            dict(base, episode_id="x-interrupted", resolution="interrupted")])
        cls.graded = grade.grade_run(cls.store, RUN, grade.batch_now(cls.store, RUN))
        cls.secs = sections(report.report_run(cls.store, RUN))

    def run_sql(self, path):
        text = path.read_text()
        out = ClickHouseStore(self.url, self.db)._post(text.rstrip().rstrip(";") + "\nFORMAT JSONEachRow",
                                                      params={"param_run": RUN})
        return [json.loads(ln) for ln in out.splitlines() if ln.strip()]

    def test_every_sql_file_has_a_comparator_and_the_other_way_round(self):
        files = sorted(p.stem for p in SQL_DIR.glob("*.sql"))
        self.assertTrue(files)
        self.assertEqual(files, sorted(COMPARATORS))

    def test_the_store_is_not_empty_so_the_comparison_means_something(self):
        eps = self.store.select("stuck_episodes", {"run": RUN})
        self.assertGreater(len(report.countable(eps)), 0)
        self.assertGreater(len([d for d in self.store.select("decisions") if d["run"] == RUN]), 0)

    def test_each_sql_file_equals_its_report_section(self):
        for path in sorted(SQL_DIR.glob("*.sql")):
            heading, expect = COMPARATORS[path.stem]
            with self.subTest(sql=path.name):
                rows = self.run_sql(path)
                got = expect(rows)
                self.assertEqual(got, section(self.secs, heading))
                print(f"{path.name}: {len(rows)} row(s), first line: {got[0]}", file=sys.stderr)

    def test_every_dashboard_panel_query_runs_on_clickhouse(self):
        dash = json.loads((ROOT / "fleet" / "grafana" / "dashboard.json").read_text())
        n = 0
        stack = list(dash["panels"])
        while stack:
            p = stack.pop()
            stack += p.get("panels", [])
            for t in p.get("targets", []):
                sql = t["rawSql"].replace("${run}", RUN)
                ClickHouseStore(self.url, self.db)._post(sql.rstrip().rstrip(";") + "\nFORMAT JSONEachRow")
                n += 1
        self.assertGreater(n, 10)

    def test_the_sql_applies_the_countable_filter_where_it_counts_episodes(self):
        eps = self.store.select("stuck_episodes", {"run": RUN})
        countable = report.countable(eps)
        self.assertEqual(len(eps) - len(countable), 3)
        for stem in ("resolution_mix", "cause_mix", "hotspots", "episodes_per_hour"):
            rows = self.run_sql(SQL_DIR / f"{stem}.sql")
            if stem != "hotspots":  # hotspots is cut at the top 20
                self.assertEqual(sum(r["episodes"] for r in rows), len(countable), stem)
        self.assertNotIn("x-open", json.dumps(self.run_sql(SQL_DIR / "hotspots.sql")))
        self.assertNotIn("Z0-99", json.dumps(self.run_sql(SQL_DIR / "repeat_robots.sql")))


if __name__ == "__main__":
    unittest.main()

"""Integration test against REAL ClickHouse in Docker. NOT collected by the gate (the file name does not match
test_fleet_*.py); run it explicitly from the repo root:

    .venv/bin/python -m unittest -v fleet.tests.integration_fleet_stack

It starts only the clickhouse service (`fleet/compose.sh up clickhouse`, mem_limit 3g), uses a throwaway database,
and brings the stack down afterwards (`fleet/compose.sh down`; data stays in the fleet_clickhouse volume). Skips with a reason
when `docker info` fails. Host port: FLEET_CLICKHOUSE_PORT (default 18123)."""
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

from fleet.tests.test_fleet_hotspot import checkpoint_at, scenario  # noqa: E402
from fleet.tests.test_fleet_ingest import emit_real  # noqa: E402
from fleet_analyser import decisions, forecast_grade  # noqa: E402
from fleet_analyser.clickhouse_store import ClickHouseStore  # noqa: E402
from fleet_analyser.ingest import Ingester  # noqa: E402
from fleet_analyser.ledger import coverage  # noqa: E402
from fleet_analyser.store import MemoryStore  # noqa: E402

import costmap  # noqa: E402
import grade  # noqa: E402

COMPOSE = str(ROOT / "fleet" / "compose.sh")
PORT = int(os.environ.get("FLEET_CLICKHOUSE_PORT", "18123"))


def docker_ok():
    try:
        r = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"docker is not usable: {e}"
    return r.returncode == 0, (r.stderr.strip().splitlines() or ["docker info failed"])[-1]


class TestRealClickHouse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ok, why = docker_ok()
        if not ok:
            raise unittest.SkipTest(f"`docker info` failed, so the real-ClickHouse integration test cannot run: {why}")
        cls.addClassCleanup(subprocess.run, [COMPOSE, "down"], capture_output=True, text=True)
        up = subprocess.run([COMPOSE, "up", "clickhouse"], capture_output=True, text=True)
        if up.returncode != 0:
            raise RuntimeError(f"compose.sh up clickhouse failed:\n{up.stdout}\n{up.stderr}")
        cls.db = f"fleet_it_{os.getpid()}"
        cls.url = f"http://127.0.0.1:{PORT}"
        cls.addClassCleanup(lambda: ClickHouseStore(cls.url, cls.db)._post(f"DROP DATABASE IF EXISTS {cls.db}", False))
        ClickHouseStore(cls.url, cls.db).ensure_schema()

    def store(self):
        return ClickHouseStore(self.url, self.db)

    def test_upsert_and_stamp_contract_on_real_clickhouse(self):
        st = self.store()
        key = ("run", "episode_id")
        row = dict(run="c", episode_id="e", zone="0", robot="Z0-01", order_id="o", start=1, start_iso="a", t_entry=31,
                   cell=[1, 2], cause="unknown", blocker=None, blocker_faulted_s=None, end=None, duration_s=None,
                   resolution="open", avoidable=False, avoidable_s=None, left_censored=False)
        st.upsert("stuck_episodes", key, [row])
        st.upsert("stuck_episodes", key, [dict(row, resolution="moved", end=91, duration_s=90)])
        got = st.select("stuck_episodes", {"run": "c"})  # FINAL: one row, the later values (parts are not merged yet)
        self.assertEqual(len(got), 1)
        self.assertEqual((got[0]["resolution"], got[0]["end"], got[0]["duration_s"], got[0]["cell"]),
                         ("moved", 91, 90, [1, 2]))
        # first-write order survives a replacement, also from a second writer process (fresh store instance)
        st.upsert("stuck_episodes", key, [dict(row, episode_id="e2")])
        self.store().upsert("stuck_episodes", key, [dict(row, resolution="unresolved")])
        order = [(r["episode_id"], r["resolution"]) for r in self.store().select("stuck_episodes", {"run": "c"})]
        self.assertEqual(order, [("e", "unresolved"), ("e2", "open")])
        did, created = decisions.record_decision(st, run="c", kind="stuck_cause", subject="Z0-01", start_iso="a",
                                                 decided_at=31, claim={"cause": "unknown"}, rationale="r",
                                                 expected=None, grade_after=3631)
        self.assertTrue(created)
        self.assertFalse(decisions.record_decision(st, run="c", kind="stuck_cause", subject="Z0-01", start_iso="a",
                                                   decided_at=99, claim={}, rationale="x", expected=None,
                                                   grade_after=1)[1])
        n1 = st.update_where("decisions", {"id": did, "status": "open"},
                             dict(status="graded", outcome="o", error=None, verdict="v", graded_at=4000))
        n2 = st.update_where("decisions", {"id": did, "status": "open"},
                             dict(status="graded", outcome="again", error=None, verdict="w", graded_at=5000))
        self.assertEqual((n1, n2), (1, 0))
        (d,) = st.select("decisions", {"id": did})
        self.assertEqual((d["status"], d["outcome"], d["verdict"], d["graded_at"], d["decided_at"]),
                         ("graded", "o", "v", 4000, 31))
        self.assertNotIn("schema_version", d)

    def test_stalls_costmap_and_forecast_grades_round_trip(self):
        """The S8B tables written through real ClickHouse equal the same run through MemoryStore."""
        truth = {"zones": {"0": {"floor_cells": {"6,5": 0.5}}, "1": {"floor_cells": {}}}}
        mem, ch = MemoryStore(), self.store()
        for st in (mem, ch):
            costmap.build_costmap(scenario(), st, "s8b", publish_every=1000)
            checkpoint_at(st, 3000, run="s8b")
            forecast_grade.grade_outcomes(st, "s8b", min_horizon_s=600)
            if st is ch:
                before = ch.select("decision_grades")
            grade.grade_truth(st, "s8b", truth)
            forecast_grade.grade_outcomes(st, "s8b", min_horizon_s=600)  # re-run: no new rows

        def canon(st, table):
            return sorted(json.dumps(r, sort_keys=True) for r in st.select(table, {"run": "s8b"}))

        for table in ("stalls", "costmap", "forecast_grades"):
            self.assertGreater(len(mem.select(table, {"run": "s8b"})), 0, table)
            self.assertEqual(canon(ch, table), canon(mem, table), table)
        sources = {r["grade_source"] for r in ch.select("forecast_grades", {"run": "s8b"})}
        self.assertEqual(sources, {"outcome", "truth"})
        graded = [d for d in ch.select("decisions", {"run": "s8b"}) if d["status"] == "graded"]
        self.assertGreater(len(graded), 0)
        self.assertGreater(len(before), 0)  # the outcome stamps wrote decision_grades; truth grading left them alone
        self.assertEqual(ch.select("decision_grades"), before)

    def test_emit_two_zones_ingest_into_clickhouse_twice(self):
        with tempfile.TemporaryDirectory() as d:
            emit_real(d, 2, 300, "--t0", "now", "--workers", 2)
            files = str(Path(d) / "*.jsonl.gz")
            st = self.store()
            ing = Ingester(files, "it", st, poll=0, ledger_interval=0.5, sleep=lambda s: None)
            self.assertEqual(ing.run_loop(), 0)
            eps = st.select("stuck_episodes", {"run": "it"})
            decs = [x for x in st.select("decisions") if x["run"] == "it"]
            rows = st.select("ingest_ledger", {"run": "it"})
            expected = st.select("ingest_runs", {"run": "it"})[0]["expected_messages"]
            self.assertEqual(expected, 2 * 12 * 300)
            cov = coverage(sum(r["messages_accepted"] for r in rows), expected)
            self.assertGreater(len(eps), 0)
            self.assertGreater(len(decs), 0)
            self.assertEqual(cov, 1.0)
            self.assertGreater(len(st.select("state_sample", {"run": "it"})), 0)
            raw_count = int(st._post(f"SELECT count() FROM {self.db}.stuck_episodes FINAL WHERE run = 'it'", False))
            self.assertEqual(raw_count, len(eps))
            # the same files again, same run: nothing new
            ing2 = Ingester(files, "it", self.store(), poll=0, ledger_interval=0.5, sleep=lambda s: None)
            self.assertEqual(ing2.run_loop(), 0)
            st2 = self.store()
            self.assertEqual(len(st2.select("stuck_episodes", {"run": "it"})), len(eps))
            self.assertEqual(len([x for x in st2.select("decisions") if x["run"] == "it"]), len(decs))
            # the same files under another run name: the decision ledger's dedup_key keeps first-write-wins
            ing3 = Ingester(files, "it-again", self.store(), poll=0, ledger_interval=0.5, sleep=lambda s: None)
            self.assertEqual(ing3.run_loop(), 0)
            self.assertEqual(len([x for x in self.store().select("decisions") if x["run"] in ("it", "it-again")]),
                             len(decs))
            print(f"\nintegration: {len(eps)} episodes, {len(decs)} decisions, coverage {cov}", file=sys.stderr)


if __name__ == "__main__":
    unittest.main()

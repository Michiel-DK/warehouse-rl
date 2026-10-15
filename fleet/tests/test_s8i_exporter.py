"""S8I-ONE-PAGER, exporter side (criterion C1-C3): schema replay/3, run_constants with their sources, the kept formula
checked independently on a tiny hand-written store, publishes with recall_at_k and k, and --carry-lessons. The committed
docs/replay/data.js is checked against the documented numbers. Unit tests: no Docker, no fleet/data, no env run."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "fleet", ROOT / "src", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import hotspot_score  # noqa: E402
import replay_export as rx  # noqa: E402
from fleet.tests import test_replay_export as tre  # noqa: E402
from fleet_analyser import decisions, hotspot, lessons as lessons_mod  # noqa: E402
from fleet_analyser.store import JsonlStore  # noqa: E402

DOCS = ROOT / "docs" / "replay"


def write_json(path, obj):
    Path(path).write_text(json.dumps(obj))
    return str(path)


def new_run(parent):
    (Path(parent) / "run").mkdir()
    return tre.build_run(Path(parent) / "run")


def fixture_files(directory, run=tre.RUN, n_floor=2, zone="0"):
    d = Path(directory)
    bench = write_json(d / "benchmark.json", {"batch": {"msgs_per_s": 2788.5}, "other": 1})
    hot = write_json(d / "hotspot.json", {"run": run, "zones": {zone: {
        "n_floor": n_floor, "zero_stall_share": 0.4,
        "k": {"20": {"precision": 0.3, "recall": 0.1, "hits": 6}, str(n_floor): {"precision": 0.5, "recall": 0.25, "hits": 1}}}}})
    cl = write_json(d / "summary.json", {"headline_arm": "map_a4", "arms": {
        "map_a4": {"share_of_floor_loss_recovered": {"share": 0.04, "ci95": [0.01, 0.07]}},
        "oracle": {"share_of_floor_loss_recovered": {"share": 0.16, "ci95": [0.12, 0.2]}},
        "none": {"share_of_floor_loss_recovered": {"share": 0.0, "ci95": [0.0, 0.0]}}}})
    return bench, hot, cl


class TestRunConstants(tre.Fixture):
    def test_schema_is_replay_3_and_no_test_asserts_replay_2(self):
        self.assertEqual(rx.SCHEMA, "replay/3")
        self.assertEqual(self.payload["meta"]["schema"], "replay/3")
        old = "replay" + "/2"  # spelled in two parts so this very search does not match itself
        for f in (ROOT / "fleet" / "tests").glob("test_*.py"):
            text = f.read_text(encoding="utf-8")
            self.assertNotIn(f'"{old}"', text, f.name)
            self.assertNotIn(f"'{old}'", text, f.name)

    def test_without_the_optional_args_the_file_entries_are_null_and_the_export_succeeds(self):
        rc = self.payload["run_constants"]
        self.assertEqual(set(rc), {"ingest_msgs_per_s", "benchmark_msgs_per_s", "kept", "hotspot", "closed_loop"})
        for key in ("benchmark_msgs_per_s", "hotspot", "closed_loop"):
            self.assertIsNone(rc[key], key)

    def test_file_entries_copy_the_files_and_name_the_path_as_given(self):
        with tempfile.TemporaryDirectory() as tmp:
            bench, hot, cl = fixture_files(tmp)
            p = rx.build_payload(self.dir, self.spec, "0", env_runner=tre.fake_env, run_dir_arg=str(self.dir),
                                 benchmark=bench, hotspot_file=hot, closed_loop_summary=cl)
        rc = p["run_constants"]
        self.assertEqual(rc["benchmark_msgs_per_s"], dict(value=2788.5, source=bench))
        self.assertEqual(rc["hotspot"], dict(precision_at_20=0.3, recall_at_k=0.25, k=2, zero_stall_share=0.4, n_floor=2, source=hot))
        self.assertEqual(rc["closed_loop"], dict(arm="map_a4", map_share=0.04, map_share_ci95=[0.01, 0.07], oracle_share=0.16,
                                                 oracle_share_ci95=[0.12, 0.2], source=cl))
        for key in ("ingest_msgs_per_s", "kept"):
            self.assertTrue(rc[key]["source"].startswith("store:"), key)

    def test_a_hotspot_file_of_another_run_or_another_floor_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, hot, _ = fixture_files(tmp, run="other")
            with self.assertRaisesRegex(ValueError, "scores run"):
                rx.build_payload(self.dir, self.spec, "0", env_runner=tre.fake_env, hotspot_file=hot)
            _, hot, _ = fixture_files(tmp, n_floor=3)
            with self.assertRaisesRegex(ValueError, "n_floor"):
                rx.build_payload(self.dir, self.spec, "0", env_runner=tre.fake_env, hotspot_file=hot)

    def test_ingest_rate_is_the_parsed_weighted_harmonic_rate(self):
        rows = [dict(messages_parsed=100, msgs_per_s=50.0), dict(messages_parsed=300, msgs_per_s=100.0),
                dict(messages_parsed=10, msgs_per_s=0), dict(messages_parsed=0, msgs_per_s=9.0)]
        self.assertAlmostEqual(rx.ingest_rate(rows), 400 / (2 + 3))
        self.assertIsNone(rx.ingest_rate([]))
        self.assertEqual(rx.ingest_rate(rows[:1]), 50.0)


class TestKeptFormula(unittest.TestCase):
    """C2: the kept percentage on a tiny store whose bytes the test computes itself."""

    RUN = "r"

    def build(self, tmp):
        d = Path(tmp)
        run_dir = new_run(d)  # truth, emit ledger, zone files, costmap.json (run "r")
        st = JsonlStore(d / "tiny")
        rows = dict(
            transitions=[dict(run="r", zone="0", robot="Z0-01", ts=1, from_state="a", to_state="b", cell="1,2", order_id="o"),
                         dict(run="r", zone="0", robot="Z0-02", ts=2, from_state="b", to_state="c", cell="3,4", order_id="")],
            decisions=[dict(id="x" * 40, run="r", kind="stuck_cause", subject="Z0-01", claim='{"a":1}', rationale="é — non ascii"),
                       dict(id="y" * 40, run="r", kind="avoidable_reset", subject="s", claim="{}", rationale="")],
            state_sample=[dict(run="r", zone="0", serial="Z0-01", header_id=0, ts=5, raw='{"k": "v"}\n')],
            rejects=[dict(run="r", source="file", file="f", offset=3, reason="json", raw="{trunc")])
        for table, rs in rows.items():
            st.insert(table, [dict(r, __bookkeeping=7) for r in rs])  # a store-added "__" key that must not count
            st.insert(table, [dict(rs[0], run="other-run")])  # another run's row: excluded
        st.insert("ingest_ledger", [dict(run="r", source="file", minute=1, bytes_read_uncompressed=100000, messages_parsed=50,
                                         msgs_per_s=25.0)])
        st.insert("ingest_ledger", [dict(run="other-run", source="file", minute=1, bytes_read_uncompressed=999, messages_parsed=1,
                                         msgs_per_s=1.0)])
        st.close()
        return run_dir, f"jsonl:{d / 'tiny'}", rows

    def test_kept_pct_is_the_documented_formula(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir, spec, rows = self.build(tmp)
            p = rx.build_payload(run_dir, spec, "0", env_runner=tre.fake_env)
            st = JsonlStore(Path(tmp) / "tiny")
            total = 0
            for table in ("transitions", "decisions", "state_sample", "rejects"):
                for row in st.select(table, {"run": "r"}):
                    clean = {k: v for k, v in row.items() if not k.startswith("__")}
                    self.assertEqual(set(clean) - set(row), set())
                    total += len(json.dumps(clean, sort_keys=True, separators=(",", ":")).encode())
            arrived = sum(r["bytes_read_uncompressed"] for r in st.select("ingest_ledger", {"run": "r"}))
            st.close()
        kept = p["run_constants"]["kept"]
        self.assertEqual(arrived, 100000)
        self.assertEqual(kept["kept_pct"], 100 * total / arrived)
        self.assertEqual((kept["bytes_kept"], kept["bytes_arrived"], kept["scope"]), (total, arrived, "run"))
        self.assertEqual(sum(kept["bytes_by_table"].values()), total)
        self.assertEqual(sorted(kept["bytes_by_table"]), ["decisions", "rejects", "state_sample", "transitions"])
        self.assertTrue(kept["formula"].strip())
        self.assertIn(kept["formula"], rx.__doc__)

    def test_row_bytes_drops_only_the_double_underscore_keys_and_keeps_run(self):
        row = {"run": "r", "a": "é", "__key": ["run"], "__upd": 1, "_single": 2}
        self.assertEqual(rx.row_bytes(row), len(json.dumps({"_single": 2, "a": "é", "run": "r"}, sort_keys=True,
                                                          separators=(",", ":")).encode()))

    def test_no_ingest_ledger_means_no_kept_and_no_rate(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = new_run(Path(tmp))
            st = JsonlStore(Path(tmp) / "empty")
            st.close()
            p = rx.build_payload(run_dir, f"jsonl:{Path(tmp) / 'empty'}", "0", env_runner=tre.fake_env)
        self.assertIsNone(p["run_constants"]["kept"])
        self.assertIsNone(p["run_constants"]["ingest_msgs_per_s"])


class TestPublishRecall(tre.Fixture):
    def test_every_publish_has_recall_at_k_equal_to_hotspot_score(self):
        st = self.store()
        floor = tre.FLOOR["0"]
        self.assertTrue(self.payload["publishes"])
        for pub in self.payload["publishes"]:
            zmap = {r["cell"]: r["cost"] for r in st.select("costmap", {"run": tre.RUN, "zone": "0", "published_at": pub["t"]})}
            want = hotspot_score.precision_recall(zmap, floor, ks=(20, len(floor)))
            self.assertEqual(pub["k"], len(floor))
            self.assertEqual(pub["recall_at_k"], want[len(floor)]["recall"])
            self.assertEqual(pub["precision_at_20"], want[20]["precision"])
        st.close()


class TestCarryLessons(tre.Fixture):
    LESSONS = [dict(decided_at_step=3, zone="1", text="In zone 1, x", lesson_kind="hot_cell", confidence=0.5, verdict="off",
                    graded_at_step=9)]

    def carry_file(self, tmp, **meta):
        payload = dict(meta=dict(run="s8b-score", source={}, **meta), lessons=self.LESSONS)
        out = Path(tmp) / "carry.js"
        rx.write_data_js(payload, out)
        return str(out)

    def test_lessons_are_copied_verbatim_and_the_origin_is_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.carry_file(tmp)
            p = rx.build_payload(self.dir, self.spec, "0", env_runner=tre.fake_env, carry_lessons=path)
        self.assertEqual(p["lessons"], self.LESSONS)
        self.assertEqual((p["meta"]["source"]["carry_lessons"], p["meta"]["source"]["carry_lessons_run"]), (path, "s8b-score"))

    def test_the_origin_survives_exporting_from_an_exported_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.carry_file(tmp)
            first = rx.build_payload(self.dir, self.spec, "0", env_runner=tre.fake_env, carry_lessons=path)
            rx.write_data_js(first, path)  # the chain reads and writes the same data.js
            again = rx.build_payload(self.dir, self.spec, "0", env_runner=tre.fake_env, carry_lessons=path)
        self.assertEqual(again["meta"]["source"]["carry_lessons_run"], "s8b-score")
        self.assertEqual(again["lessons"], self.LESSONS)

    def test_a_store_with_lesson_decisions_rejects_the_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.carry_file(tmp)
            run_dir = new_run(Path(tmp))
            st = JsonlStore(run_dir / "store")
            decisions.record_decision(st, run=tre.RUN, kind="lesson", subject="Z0:cell 1,1", start_iso="2026-01-01T00:00:00Z",
                                      decided_at=tre.BASE + 100, claim=dict(zone="0", subject="Z0:cell 1,1", text="T", lesson_kind="hot_cell",
                                                                              confidence=0.5),
                                      rationale="r", expected=None, grade_after=tre.BASE + 200, recorded_at=1.0)
            st.close()
            with self.assertRaisesRegex(ValueError, "carry-lessons"):
                rx.build_payload(run_dir, f"jsonl:{run_dir / 'store'}", "0", env_runner=tre.fake_env, carry_lessons=path)


class TestCommittedData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = rx.read_data_js(DOCS / "data.js")

    def test_header_and_size(self):
        self.assertEqual(self.d["meta"]["schema"], "replay/3")
        self.assertLessEqual((DOCS / "data.js").stat().st_size, 2097152)
        self.assertNotEqual(self.d["meta"]["run"], "s8b-score")

    def test_publishes_carry_recall_and_k(self):
        k = len(self.d["obstacles"])
        self.assertGreater(k, 0)
        for p in self.d["publishes"]:
            self.assertEqual(p["k"], k)
            self.assertIsInstance(p["recall_at_k"], float)

    def test_lessons_and_noise_and_sources(self):
        self.assertEqual(len(self.d["lessons"]), 15)
        ex = self.d["extractor"]
        self.assertGreater(ex["totals"]["rejected"], 0)
        self.assertGreater(ex["totals"]["duplicates"], 0)
        self.assertEqual(ex["check"]["coverage"], 1.0)
        src = self.d["meta"]["source"]
        self.assertIs(src["demo_noise"], True)
        self.assertEqual(src["carry_lessons_run"], "s8b-score")
        self.assertTrue(src["carry_lessons"])
        rc = self.d["run_constants"]
        self.assertTrue(0 < rc["kept"]["kept_pct"] <= 100)
        self.assertEqual(rc["closed_loop"]["source"], "results/closed_loop_sticky/summary.json")
        self.assertEqual(rc["hotspot"]["source"], "results/fleet/hotspot_s8i-demo-noise.json")
        self.assertTrue((ROOT / rc["hotspot"]["source"]).is_file())
        self.assertEqual(rc["benchmark_msgs_per_s"]["source"], "results/fleet/benchmark.json")

    def test_run_constants_equal_their_files(self):
        rc = self.d["run_constants"]
        hot = json.loads((ROOT / rc["hotspot"]["source"]).read_text())
        z = hot["zones"][self.d["meta"]["zone"]]
        self.assertEqual(hot["run"], self.d["meta"]["run"])
        self.assertEqual((rc["hotspot"]["precision_at_20"], rc["hotspot"]["zero_stall_share"]),
                         (z["k"]["20"]["precision"], z["zero_stall_share"]))
        bench = json.loads((ROOT / rc["benchmark_msgs_per_s"]["source"]).read_text())
        self.assertEqual(rc["benchmark_msgs_per_s"]["value"], bench["batch"]["msgs_per_s"])
        cl = json.loads((ROOT / rc["closed_loop"]["source"]).read_text())
        self.assertEqual(rc["closed_loop"]["map_share"], cl["arms"][cl["headline_arm"]]["share_of_floor_loss_recovered"]["share"])


if __name__ == "__main__":
    unittest.main()

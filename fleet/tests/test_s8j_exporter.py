"""S8J-WORDING, exporter side (criterion C1 and the exporter half of C3): schema replay/4, the run_constants entries kept /
audit / header / speed / lessons_long / worth with their sources, the single-run validator, the lesson truth field and the
removal of --carry-lessons. Unit tests on the synthetic two-zone run of test_replay_export (no Docker, no fleet/data)."""
import contextlib
import copy
import io
import json
import math
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "fleet", ROOT / "src", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import grade as grade_cli  # noqa: E402
import replay_export as rx  # noqa: E402
from fleet.tests import test_replay_export as tre  # noqa: E402
from fleet.tests.test_fleet_lessons import put_lesson  # noqa: E402
from fleet_analyser.parse import parse_line  # noqa: E402
from fleet_analyser.store import JsonlStore  # noqa: E402

ARMS = rx.WORTH_ARMS
# per-seed pick rates of the four arms: the floor costs about 30 lines/h, the map wins back a little, perfect knowledge more
PICK = {"none": [10.0, 12.0, 14.0, 16.0, 18.0, 20.0], "map_a32": [12.0, 14.5, 15.0, 20.0, 19.0, 26.0],
        "oracle_a32": [20.0, 22.0, 21.0, 30.0, 28.0, 31.0], "undisturbed": [40.0, 42.0, 41.0, 50.0, 48.0, 52.0]}


def write_json(path, obj):
    Path(path).write_text(json.dumps(obj))
    return str(path)


def row_file(directory, arm, pick=None, seeds=None, shuffle=True):
    """A closed-loop row file of one arm (the keys the exporter reads); rows in reverse seed order unless shuffle is off."""
    pick = PICK[arm] if pick is None else pick
    seeds = list(range(len(pick))) if seeds is None else seeds
    rows = [dict(seed=s, pick_rate=v) for s, v in zip(seeds, pick)]
    mean = sum(pick) / len(pick)
    sub = Path(directory) / arm
    sub.mkdir(parents=True, exist_ok=True)
    return write_json(sub / "rows.json", dict(pick_rate_mean=mean, ci95_low=mean - 1.5, ci95_high=mean + 2.5,
                                              rows=rows[::-1] if shuffle else rows))


def edit_ledger(run_dir, zone_noise=None, total_noise=None):
    p = Path(run_dir) / "emit_ledger.json"
    doc = json.loads(p.read_text())
    if zone_noise is not None:
        doc["zones"][0]["injected_noise"] = zone_noise
    if total_noise is not None:
        doc["total"]["injected_noise"] = total_noise
    p.write_text(json.dumps(doc))


class Base(unittest.TestCase):
    """One run dir with a headerId jump on Z0-04 (4 numbers skipped from step 60 on), noise in the ledger, a lesson on a floor
    cell, one on a plain cell and one that is not a hot_cell, all in zone 0, plus the row files and the context files."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.tmp.name)
        orig = tre.zone0_lines

        def jump():
            rows = [r for r in orig() if b'"Z0-04"' not in r[1]]
            rows += [(t, tre.v2("Z0-04", t if t < 60 else t + 4, t, 0, 0)) for t in range(tre.STEPS)]
            return rows

        (cls.base / "run").mkdir()
        with mock.patch.object(tre, "zone0_lines", jump):
            cls.dir = tre.build_run(cls.base / "run")
        cls.noise = dict(malformed=7, duplicates=11, gap_ids=4)
        edit_ledger(cls.dir, zone_noise=cls.noise, total_noise=dict(malformed=70, duplicates=110, gap_ids=40))
        st = JsonlStore(cls.dir / "store")
        t = tre.BASE + 100
        cls.hit_id = put_lesson(st, tre.RUN, "0", "Z0:cell 3,2", t, None, 0.8)  # 3,2 is a floor cell of zone 0
        cls.miss_id = put_lesson(st, tre.RUN, "0", "Z0:cell 9,9", t + 50, None, 0.6)
        cls.robot_id = put_lesson(st, tre.RUN, "0", "Z0:Z0-01", t + 100, None, 0.5)
        put_lesson(st, tre.RUN, "1", "Z1:cell 3,2", t, None, 0.7)  # another zone: not in the export
        truth = json.loads((cls.dir / "truth.json").read_text())
        grade_cli.grade_lesson_truth(st, tre.RUN, truth)
        st.close()
        cls.spec = f"jsonl:{cls.dir / 'store'}"
        cls.files = cls.base / "files"
        cls.files.mkdir()
        cls.bench = write_json(cls.files / "benchmark.json", {"batch": {"msgs_per_s": 2788.5}})
        cls.long = write_json(cls.files / "long.json", {"grading_counts": {"lesson": {"ok": 9, "off": 22},
                                                                          "lesson_truth": {"hit": 27, "false_alarm": 3}}})
        cls.rows = {arm: row_file(cls.files, arm) for arm in ARMS}
        cls.payload = cls.build()

    @classmethod
    def build(cls, **kw):
        args = dict(env_runner=tre.fake_env, run_dir_arg=str(cls.dir), benchmark=cls.bench, lessons_long=cls.long,
                    sticky=cls.rows)
        args.update(kw)
        return rx.build_payload(cls.dir, cls.spec, "0", **args)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def accepted_keys(self):
        """(serial, ts) of the accepted messages, parsed independently of the exporter: first copy of each (serial, headerId)."""
        import gzip
        seen, out = set(), set()
        with gzip.open(self.dir / "zone0-000.jsonl.gz", "rb") as f:
            for raw in f:
                m, _ = parse_line(raw)
                if m is not None and (m.serial, m.header_id) not in seen:
                    seen.add((m.serial, m.header_id))
                    out.add((m.serial, m.ts))
        return out

    def store(self):
        return JsonlStore(self.dir / "store")


class TestSchemaAndFields(Base):
    def test_schema_is_replay_4_and_no_test_asserts_the_old_one(self):
        self.assertEqual(rx.SCHEMA, "replay/4")
        self.assertEqual(self.payload["meta"]["schema"], "replay/4")
        old = "replay" + "/3"  # spelled in two parts so this search does not match itself
        for f in (ROOT / "fleet" / "tests").glob("test_*.py"):
            text = f.read_text(encoding="utf-8")
            self.assertNotIn(f'"{old}"', text, f.name)
            self.assertNotIn(f"'{old}'", text, f.name)

    def test_the_run_constants_keys(self):
        self.assertEqual(set(self.payload["run_constants"]), {"ingest_msgs_per_s", "benchmark_msgs_per_s", "kept", "hotspot",
                                                              "closed_loop", "audit", "header", "speed", "lessons_long", "worth",
                                                              "dose_response", "explorer", "baselines"})  # S8R; S11A: explorer; S10H: baselines

    def test_every_source_is_a_passed_path_or_store_or_emit_ledger(self):
        passed = {self.bench, self.long, *self.rows.values()}
        for key in ("benchmark_msgs_per_s", "kept", "audit", "header", "speed", "lessons_long", "worth", "ingest_msgs_per_s"):
            src = self.payload["run_constants"][key]["source"]
            self.assertIsInstance(src, str, key)
            if key == "worth":  # the four row-file paths as passed, in bar order
                self.assertEqual(src, ", ".join(self.rows[a] for a in rx.WORTH_ARMS))
            else:
                self.assertTrue(src in passed or src.startswith(("store:", "emit_ledger:")), (key, src))
        for bar in self.payload["run_constants"]["worth"]["bars"]:
            self.assertEqual(bar["source"], self.rows[bar["key"]])

    def test_kept_counts_changes_and_repeats(self):
        kept = self.payload["run_constants"]["kept"]
        st = self.store()
        rows = [r for r in st.select("transitions", {"run": tre.RUN}) if str(r["zone"]) == "0"]
        st.close()
        accepted = self.accepted_keys()
        want = sum(1 for r in rows if (r["robot"], r["ts"]) in accepted)
        self.assertGreater(want, 0)
        self.assertEqual(want, len(rows))  # every transition row is an accepted message (the detector writes at its ts)
        self.assertEqual(kept["n_changes"], want)
        totals = self.payload["extractor"]["totals"]
        self.assertEqual(totals["accepted"], len(accepted))
        self.assertEqual(kept["n_repeats"], len(accepted) - want)
        self.assertEqual(kept["changes_by_step"][-1], want)
        self.assertEqual(len(kept["changes_by_step"]), tre.STEPS)
        self.assertEqual(kept["changes_by_step"], sorted(kept["changes_by_step"]))

    def test_a_duplicate_transition_row_raises_instead_of_being_undercounted(self):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "run"
            shutil.copytree(self.dir, d)
            path = d / "store" / "transitions.jsonl"
            first = next(l for l in path.read_text().splitlines() if l.strip())
            with path.open("a") as f:
                f.write(first + "\n")
            with self.assertRaisesRegex(ValueError, "duplicate"):
                rx.build_payload(d, f"jsonl:{d / 'store'}", "0", env_runner=tre.fake_env, run_dir_arg=str(d),
                                 benchmark=self.bench, lessons_long=self.long, sticky=self.rows)

    def test_audit_ignores_the_headerid_jump_while_the_extractor_counts_it(self):
        a = self.payload["run_constants"]["audit"]
        totals = self.payload["extractor"]["totals"]
        self.assertGreater(totals["missing_messages"], 0)  # the jump on Z0-04
        self.assertEqual(a["sent"], 4 * tre.STEPS)  # emit ledger zones[0].messages
        self.assertEqual(a["read"], totals["accepted"])
        self.assertEqual(a["missing"], a["sent"] - a["read"])
        self.assertEqual(a["missing"], 0)

    def test_header_uses_the_zone_noise_and_the_total_only_when_the_zone_has_none(self):
        h = self.payload["run_constants"]["header"]
        self.assertEqual(h["msgs"], self.payload["extractor"]["totals"]["messages"])
        self.assertEqual((h["noise"], h["noise_scope"]), (7 + 11, "zone"))  # not the total's 70 + 110
        edit_ledger(self.dir, total_noise=dict(malformed=70, duplicates=110))
        doc = json.loads((self.dir / "emit_ledger.json").read_text())
        doc["zones"][0].pop("injected_noise")
        (self.dir / "emit_ledger.json").write_text(json.dumps(doc))
        try:
            h2 = self.build()["run_constants"]["header"]
        finally:
            edit_ledger(self.dir, zone_noise=self.noise)
        self.assertEqual((h2["noise"], h2["noise_scope"]), (180, "total"))

    def test_speed(self):
        s = self.payload["run_constants"]["speed"]
        robot = 4 * tre.STEPS / (tre.STEPS * rx.STEP_SECONDS)
        self.assertEqual(rx.STEP_SECONDS, 5)
        self.assertEqual(s["robot_rate"], robot)
        self.assertEqual(s["ingest_rate"], 2788.5)
        self.assertEqual(s["ratio"], math.floor(2788.5 / robot))
        self.assertEqual(s["source"], self.bench)

    def test_lessons_long(self):
        d = self.payload["run_constants"]["lessons_long"]
        self.assertEqual((d["truth_hit"], d["truth_n"], d["held"], d["graded"], d["source"]), (27, 30, 9, 31, self.long))

    def test_missing_optional_arguments_give_null_entries(self):
        p = self.build(benchmark=None, lessons_long=None, sticky=None)
        rc = p["run_constants"]
        for key in ("benchmark_msgs_per_s", "speed", "lessons_long", "worth"):
            self.assertIsNone(rc[key], key)
        self.assertIsNotNone(rc["audit"])
        partial = self.build(sticky={**self.rows, "map_a32": None})["run_constants"]["worth"]
        self.assertIsNone(partial)

    def test_carry_lessons_is_gone(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            rx.main(["--run-dir", str(self.dir), "--store", self.spec, "--out", str(self.base / "x.js"), "--carry-lessons", "x"])
        self.assertEqual(cm.exception.code, 2)
        self.assertNotIn("carry", json.dumps(self.payload["meta"]["source"]))
        self.assertNotIn("carry_lessons", rx.__doc__.replace("--carry-lessons", ""))


class TestWorth(Base):
    def by_hand(self, arm):
        n = len(PICK["none"])
        loss = sum(u - b for u, b in zip(PICK["undisturbed"], PICK["none"])) / n
        return sum(a - b for a, b in zip(PICK[arm], PICK["none"])) / n / loss

    def test_bars_copy_the_row_files(self):
        w = self.payload["run_constants"]["worth"]
        self.assertEqual([b["key"] for b in w["bars"]], list(ARMS))
        for b in w["bars"]:
            doc = json.loads(Path(self.rows[b["key"]]).read_text())
            self.assertEqual((b["mean"], b["ci95_low"], b["ci95_high"], b["source"]),
                             (doc["pick_rate_mean"], doc["ci95_low"], doc["ci95_high"], self.rows[b["key"]]))

    def test_shares_are_the_paired_mean_ratio_and_the_formula_is_documented(self):
        w = self.payload["run_constants"]["worth"]
        self.assertLess(abs(w["map_share"] - self.by_hand("map_a32")), 1e-12)
        self.assertLess(abs(w["oracle_share"] - self.by_hand("oracle_a32")), 1e-12)
        for lo_hi in (w["map_share_ci95"], w["oracle_share_ci95"]):
            self.assertEqual(len(lo_hi), 2)
        self.assertIn("mean over seeds of (arm_pick_rate - none_pick_rate)", " ".join(rx.__doc__.split()))
        self.assertIn("(undisturbed_pick_rate - none_pick_rate)", " ".join(rx.__doc__.split()))

    def test_rows_are_paired_by_seed_not_by_file_order(self):
        # the fixture files hold their rows in reverse seed order; unsorted pairing would change the shares
        for shuffle in (True, False):
            with tempfile.TemporaryDirectory() as tmp:
                rows = {arm: row_file(tmp, arm, shuffle=shuffle) for arm in ARMS}
                w = rx.worth_constant(rows)
            self.assertLess(abs(w["map_share"] - self.by_hand("map_a32")), 1e-12)

    def test_differing_seed_sets_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = {arm: row_file(tmp, arm) for arm in ARMS}
            rows["oracle_a32"] = row_file(tmp, "oracle_a32", pick=PICK["oracle_a32"][:-1])
            with self.assertRaisesRegex(ValueError, "same seeds"):
                rx.worth_constant(rows)
            rows["oracle_a32"] = row_file(tmp, "oracle_a32", seeds=[0, 1, 2, 3, 4, 9])
            with self.assertRaisesRegex(ValueError, "same seeds"):
                rx.worth_constant(rows)

    def test_the_label_says_a_harder_floor_and_not_panel_1(self):
        w = self.payload["run_constants"]["worth"]
        self.assertEqual(w["n_seeds"], 6)
        self.assertIn("6-seed", w["label"])
        self.assertIn("harder floor", w["label"])
        self.assertIn("not from the shift in panel 1", w["label"])

    def test_on_the_committed_row_files_the_map_share_is_the_summary_share(self):
        sticky = ROOT / "results" / "closed_loop_sticky"
        paths = {arm: str(next((sticky / arm).glob("*.json")).relative_to(ROOT)) for arm in ARMS}
        for arm in ARMS:
            self.assertEqual(len(list((sticky / arm).glob("*.json"))), 1, arm)  # one file per arm directory
        import os
        cwd = os.getcwd()
        os.chdir(ROOT)
        try:
            w = rx.worth_constant(paths)
        finally:
            os.chdir(cwd)
        summary = json.loads((sticky / "summary.json").read_text())
        self.assertAlmostEqual(w["map_share"], summary["arms"]["map_a32"]["share_of_floor_loss_recovered"]["share"], places=9)


class TestLessonsAndSingleRun(Base):
    def test_lessons_hold_this_run_and_zone_with_their_truth(self):
        ls = self.payload["lessons"]
        self.assertEqual([(l["lesson_kind"], l["zone"], l["run"]) for l in ls],
                         [("hot_cell", "0", tre.RUN), ("hot_cell", "0", tre.RUN), ("hot_robot", "0", tre.RUN)])
        self.assertEqual([l["truth"] for l in ls], ["hit", "false_alarm", None])
        self.assertEqual(set(ls[0]), {"run", "decided_at_step", "zone", "text", "lesson_kind", "confidence", "verdict",
                                      "graded_at_step", "truth"})

    def test_the_validator_passes_the_clean_payload(self):
        rx.assert_single_run(self.payload)

    def test_a_foreign_run_lesson_and_a_foreign_zone_element_raise(self):
        p = copy.deepcopy(self.payload)
        p["lessons"].append(dict(p["lessons"][0], run="s8b-score"))
        with self.assertRaisesRegex(ValueError, "run 's8b-score'"):
            rx.assert_single_run(p)
        p = copy.deepcopy(self.payload)
        p["lessons"].append(dict(p["lessons"][0], zone="1"))
        with self.assertRaisesRegex(ValueError, "zone '1'"):
            rx.assert_single_run(p)
        for key, mutate in (("episodes", lambda p: p["episodes"].append(dict(p["episodes"][0], robot="Z1-01"))),
                            ("stalls", lambda p: p["stalls"].append(["Z1-01", "1,1", 0, 1, True])),
                            ("frames", lambda p: p["frames"][3].append([1, 1, "idle", "Z1-3-o1"]))):
            p = copy.deepcopy(self.payload)
            self.assertTrue(p[key])
            mutate(p)
            with self.assertRaises(ValueError, msg=key):
                rx.assert_single_run(p)

    def test_context_entries_with_a_source_may_come_from_other_runs(self):
        p = copy.deepcopy(self.payload)
        p["run_constants"]["lessons_long"]["run"] = "s8e-long"
        p["run_constants"]["worth"]["zone"] = "elsewhere"
        rx.assert_single_run(p)

    def test_build_payload_and_write_data_js_both_call_it(self):
        p = copy.deepcopy(self.payload)
        p["lessons"].append(dict(p["lessons"][0], run="other"))
        out = self.base / "never.js"
        with self.assertRaises(ValueError):
            rx.write_data_js(p, out)
        self.assertFalse(out.exists())
        with mock.patch.object(rx, "assert_single_run", side_effect=ValueError("called")) as m:
            with self.assertRaisesRegex(ValueError, "called"):
                self.build()
        self.assertTrue(m.called)

    def test_store_rows_of_another_run_never_reach_the_payload(self):
        st = self.store()
        put_lesson(st, "another-run", "0", "Z0:cell 3,2", tre.BASE + 100, None, 0.9)
        st.close()
        self.assertEqual(len(self.build()["lessons"]), 3)


if __name__ == "__main__":
    unittest.main()

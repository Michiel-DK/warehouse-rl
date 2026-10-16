"""Tests for fleet/time_to_detect.py (S8P). Hand-written decision rows and an injected costmap rerun, so no simulator is
needed except in the one end-to-end `--smoke` subprocess test. Each case names its red demonstration in an `# inject:`
comment. None skipped. NOTE: the operator fixed this file name; tests/test_fleet_collect.py collects it explicitly."""
import contextlib
import importlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "fleet", ROOT / "src", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import time_to_detect as ttd  # noqa: E402
from fleet_analyser.store import JsonlStore  # noqa: E402

FIRST = 1000
END = 1300
EVERY = 100
PUB = [1100, 1200, 1300]
TRUTH = {"0": {"1,1": 0.99, "2,2": 0.5}, "1": {"3,3": 0.95}}
T0 = {"0": FIRST, "1": FIRST}


def row(zone, cell, t, rank, window=1.0, half=1.0, kind="hotspot_forecast", run="closed_loop"):
    claim = dict(expected_stalls_next_hour=1.0, cost=1.0, rank=rank, horizon_s=3600, window_hours=window,
                 half_life_h=half, top_k=20, min_stalls=1, exclude_occupied=True)
    return dict(id=f"{kind}-{zone}-{cell}-{t}", run=run, decided_at=t, recorded_at=0.0, kind=kind, subject=f"Z{zone}:{cell}",
                claim=json.dumps(claim), claim_version=2, rationale="", expected=1.0, grade_after=t + 3600, status="open",
                outcome=None, graded_at=None, error=None, verdict=None, dedup_key=f"{kind}:{zone}:{cell}:{t}")


ROWS = [
    row("0", "1,1", 1100, 1), row("0", "9,9", 1100, 2), row("1", "3,3", 1100, 5), row("1", "8,8", 1100, 1),
    row("0", "1,1", 1200, 3), row("0", "2,2", 1200, 2), row("0", "9,9", 1200, 1), row("1", "3,3", 1200, 4),
    row("0", "2,2", 1300, 1), row("1", "3,3", 1300, 1),
]


def make_phase_a(d, orig_extra=(), truth=TRUTH):
    """DIR with store/decisions.jsonl (the original store), truth.json, phaseA_meta.json."""
    d = Path(d)
    st = JsonlStore(d / "store")
    st.insert("decisions", list(orig_extra))
    st.close()
    (d / "store" / "decisions.jsonl").touch()
    (d / "truth.json").write_text(json.dumps(dict(
        schema_version="fleet-truth/1", env_id="E", disturb={"floor": {}}, steps=60,
        zones={z: dict(floor_cells=c) for z, c in truth.items()})))
    (d / "phaseA_meta.json").write_text(json.dumps(dict(env="E", seeds=len(truth), steps=60, disturb="D")))
    return d


class FakeRerun:
    """Stands in for the costmap subprocess: appends `rows` to the store copy and records the calls."""

    def __init__(self, rows, also=None):
        self.rows, self.calls, self.also = rows, [], also

    def __call__(self, phase_a, copy, every):
        self.calls.append((Path(phase_a), Path(copy), every))
        st = JsonlStore(copy)
        st.insert("decisions", self.rows)
        st.close()
        if self.also:
            self.also(phase_a, copy)


def span(t0=T0, first=FIRST, end=END):
    return lambda glob: (dict(t0), first, end)


def run_main(d, rerun, extra=(), ks="1,2", out=None, sp=None):
    out = out or str(Path(d) / "out.json")
    buf, err = io.StringIO(), io.StringIO()
    argv = ["--phase-a", str(d), "--publish-every", str(EVERY), "--top-k", ks, "--out", out, *extra]
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
        code = ttd.main(argv, rerun=rerun, span=sp or span())
    return code, buf.getvalue(), out


class TestAnalysis(unittest.TestCase):
    def test_exact_numbers_two_zones_three_publishes(self):
        # inject: measure first_detect_s from first_ts instead of t0, or count rank < K instead of rank <= K
        by_k, w, h = ttd.analyse(ROWS, TRUTH, T0, FIRST, PUB, [1, 2])
        k2 = by_k["2"]
        self.assertEqual(k2["curve"], [dict(t_s=100, detected_share=1 / 3, false_flags=2),
                                       dict(t_s=200, detected_share=2 / 3, false_flags=1),
                                       dict(t_s=300, detected_share=1.0, false_flags=0)])
        c = k2["cells"]
        self.assertEqual(c["0"]["1,1"], dict(p=0.99, detected=True, first_detect_s=100, rank_at_detect=1))
        self.assertEqual(c["0"]["2,2"], dict(p=0.5, detected=True, first_detect_s=200, rank_at_detect=2))
        self.assertEqual(c["1"]["3,3"], dict(p=0.95, detected=True, first_detect_s=300, rank_at_detect=1))
        self.assertEqual(k2["false_flag_cells"], {"100": {"0": ["9,9"], "1": ["8,8"]}, "200": {"0": ["9,9"]}, "300": {}})
        s = k2["summary"]
        self.assertEqual(s["share_detected_end"], 1.0)
        self.assertEqual(s["first_detect_s"], dict(p25=150.0, median=200.0, p75=250.0))
        self.assertEqual(s["p_ge_0.95"], dict(n_truth=2, n_detected=2, share=1.0, p25=150.0, median=200.0, p75=250.0))
        self.assertEqual(s["p_lt_0.95"], dict(n_truth=1, n_detected=1, share=1.0, p25=200, median=200, p75=200))
        self.assertEqual(s["false_flags_per_publish_mean"], 1.0)
        k1 = by_k["1"]
        self.assertEqual([x["detected_share"] for x in k1["curve"]], [1 / 3, 1 / 3, 1.0])
        self.assertEqual([x["false_flags"] for x in k1["curve"]], [1, 1, 0])
        self.assertAlmostEqual(k1["summary"]["false_flags_per_publish_mean"], 2 / 3)
        self.assertEqual((w, h), (1.0, 1.0))

    def test_curve_is_cumulative_when_a_cell_drops_out(self):
        # inject: compute detected_share per publish non-cumulatively (1,1 is rank 3 at t=1200, so the share would dip)
        by_k, _, _ = ttd.analyse(ROWS, TRUTH, T0, FIRST, PUB, [2])
        shares = [x["detected_share"] for x in by_k["2"]["curve"]]
        self.assertEqual(shares, sorted(shares))
        self.assertTrue(by_k["2"]["cells"]["0"]["1,1"]["detected"])
        self.assertEqual([x["false_flags"] for x in by_k["2"]["curve"]], [2, 1, 0])  # false flags are not cumulative

    def test_k_sweep_uses_rank_only_and_reruns_once(self):
        # inject: filter rows by a fixed K, or rerun the costmap once per K (calls would be 3)
        rows = [row("0", "5,5", 1100, 15)]
        truth = {"0": {"5,5": 0.9}}
        by_k, _, _ = ttd.analyse(rows, truth, {"0": FIRST}, FIRST, PUB, [10, 20])
        self.assertFalse(by_k["10"]["cells"]["0"]["5,5"]["detected"])
        self.assertTrue(by_k["20"]["cells"]["0"]["5,5"]["detected"])
        self.assertEqual(by_k["20"]["cells"]["0"]["5,5"]["rank_at_detect"], 15)
        with tempfile.TemporaryDirectory() as t:
            d = make_phase_a(t)
            fake = FakeRerun(ROWS)
            code, _, _ = run_main(d, fake, ks="1,2,3")
            self.assertEqual(code, 0)
            self.assertEqual(len(fake.calls), 1)
            self.assertEqual(fake.calls[0][2], EVERY)

    def test_undetected_cell_has_null_first_detect(self):
        # inject: initialise first_detect_s to 0 instead of None for undetected cells
        truth = {"0": {"7,7": 0.9}}
        by_k, _, _ = ttd.analyse(ROWS, truth, {"0": FIRST}, FIRST, PUB, [2])
        rec = by_k["2"]["cells"]["0"]["7,7"]
        self.assertIs(rec["detected"], False)
        self.assertIsNone(rec["first_detect_s"])
        self.assertIsNone(rec["rank_at_detect"])
        s = by_k["2"]["summary"]
        self.assertEqual(s["share_detected_end"], 0.0)
        self.assertEqual(s["first_detect_s"], dict(p25=None, median=None, p75=None))

    def test_quartile_edge_cases(self):
        # inject: call statistics.quantiles on one value (raises) or return nulls for it
        self.assertEqual(ttd.quartiles([7]), dict(p25=7, median=7, p75=7))
        self.assertEqual(ttd.quartiles([]), dict(p25=None, median=None, p75=None))
        self.assertEqual(ttd.quartiles([1, 2, 3, 4, 5]), dict(p25=2.0, median=3.0, p75=4.0))

    def test_rows_at_non_publish_times_are_ignored(self):
        # inject: drop the decided_at-in-publish_times filter (the copy also holds other publishes)
        truth = {"0": {"4,4": 0.9}}
        rows = [row("0", "4,4", 1150, 1), row("0", "4,4", 1250, 1)]
        with self.assertRaises(ValueError):  # no row at any publish time at all
            ttd.analyse(rows, truth, {"0": FIRST}, FIRST, PUB, [5])
        rows.append(row("0", "4,4", 1300, 1))
        by_k, _, _ = ttd.analyse(rows, truth, {"0": FIRST}, FIRST, PUB, [5])
        self.assertEqual(by_k["5"]["cells"]["0"]["4,4"]["first_detect_s"], 300)
        self.assertEqual(by_k["5"]["curve"][0]["detected_share"], 0.0)

    def test_other_run_and_kind_are_ignored(self):
        # inject: drop the run / kind filter
        rows = [row("0", "1,1", 1100, 1, run="other"), row("0", "1,1", 1100, 1, kind="stuck_cause"),
                row("0", "2,2", 1100, 1)]
        fc, _, _ = ttd.select_forecasts(rows, PUB)
        self.assertEqual([(f["zone"], f["cell"]) for f in fc], [("0", "2,2")])

    def test_non_uniform_window_hours_raises(self):
        # inject: take window_hours from the first row instead of checking uniformity
        rows = [row("0", "1,1", 1100, 1, window=1.0), row("0", "2,2", 1200, 1, window=2.0)]
        with self.assertRaises(ValueError):
            ttd.analyse(rows, TRUTH, T0, FIRST, PUB, [2])
        with self.assertRaises(ValueError):
            ttd.analyse([row("0", "1,1", 1100, 1, half=1.0), row("0", "2,2", 1200, 1, half=3.0)], TRUTH, T0, FIRST, PUB, [2])

    def test_zone_t0_offset_is_measured_from_the_zone_t0(self):
        # inject: measure first_detect_s from first_ts_global instead of the zone's own t0
        t0 = {"0": FIRST, "1": FIRST + 50}
        by_k, _, _ = ttd.analyse(ROWS, TRUTH, t0, FIRST, PUB, [2])
        self.assertEqual(by_k["2"]["cells"]["1"]["3,3"]["first_detect_s"], 250)
        with tempfile.TemporaryDirectory() as t:
            d = make_phase_a(t)
            _, _, out = run_main(d, FakeRerun(ROWS), sp=span(t0=t0))
            meta = json.loads(Path(out).read_text())["meta"]
            self.assertEqual(meta["t0_offsets"], {"1": 50})
            self.assertEqual(meta["t0"], t0)


class TestStoreAndCli(unittest.TestCase):
    def test_original_store_hash_unchanged_in_normal_run(self):
        # inject: run the rerun on the original store instead of the copy
        with tempfile.TemporaryDirectory() as t:
            d = make_phase_a(t, orig_extra=[row("0", "1,1", 1300, 1)])
            before = ttd.sha256_file(d / "store" / "decisions.jsonl")
            code, _, out = run_main(d, FakeRerun(ROWS))
            self.assertEqual(code, 0)
            self.assertEqual(ttd.sha256_file(d / "store" / "decisions.jsonl"), before)
            meta = json.loads(Path(out).read_text())["meta"]
            self.assertEqual((meta["store_hash_before"], meta["store_hash_after"]), (before, before))

    def test_mutated_original_store_aborts_without_output(self):
        # inject: skip the post-rerun hash comparison
        with tempfile.TemporaryDirectory() as t:
            d = make_phase_a(t)

            def corrupt(phase_a, copy):
                with open(Path(phase_a) / "store" / "decisions.jsonl", "a") as f:
                    f.write("{}\n")

            out = str(Path(t) / "out.json")
            with self.assertRaises(RuntimeError):
                run_main(d, FakeRerun(ROWS, also=corrupt), out=out)
            self.assertFalse(Path(out).exists())
            self.assertFalse((d / f"store-ttd-{EVERY}").exists())

    def test_rerun_rows_replace_phase_a_stream_end_rows_under_real_dedup(self):
        # inject: drop the strip_forecasts(copy) call in run() -> record_decision dedups the stream-end publish onto
        # phase A's row (window_hours 2.0), the selected rows mix window 1.0 and 2.0 and analyse raises
        from fleet_analyser import decisions
        from fleet_analyser.parse import iso
        with tempfile.TemporaryDirectory() as d:
            orig = row("0", "1,1", END, 7, window=2.0)
            orig["dedup_key"] = decisions.dedup_key("hotspot_forecast", "Z0:1,1", iso(END))
            make_phase_a(d, orig_extra=[orig])
            st = JsonlStore(Path(d) / "store")  # a phase A grade of that row: must not replay onto the rerun's row
            st.update_where("decisions", {"id": orig["id"]}, {"status": "graded", "verdict": "hit"})
            st.close()

            def real_dedup_rerun(phase_a, copy, every):
                st = JsonlStore(copy)
                for t in PUB:
                    decisions.record_decision(
                        st, run="closed_loop", kind="hotspot_forecast", subject="Z0:1,1", start_iso=iso(t), decided_at=t,
                        claim=dict(rank=1, window_hours=1.0, half_life_h=1.0, top_k=20), rationale="", expected=1.0,
                        grade_after=t + 3600)
                st.close()
            doc = ttd.run(d, EVERY, [1], Path(d) / "o.json", rerun=real_dedup_rerun, span=span())
            self.assertEqual(doc["meta"]["window_hours"], 1.0)
            self.assertEqual(doc["by_k"]["1"]["cells"]["0"]["1,1"]["first_detect_s"], 100)
            self.assertEqual(sum(1 for ln in (Path(d) / "store" / "decisions.jsonl").read_text().splitlines() if ln), 2)
            copy = Path(d) / "copy"
            shutil.copytree(Path(d) / "store", copy)
            # inject: keep __upd records in strip_forecasts -> the stripped row's grade stays in the copy
            self.assertEqual(ttd.strip_forecasts(copy), 1)
            self.assertEqual((copy / "decisions.jsonl").read_text().strip(), "")

    def test_copy_dir_removed_unless_keep_store(self):
        # inject: never remove the copy / always remove it
        with tempfile.TemporaryDirectory() as t:
            d = make_phase_a(t)
            run_main(d, FakeRerun(ROWS))
            self.assertFalse((d / f"store-ttd-{EVERY}").exists())
            run_main(d, FakeRerun(ROWS), extra=["--keep-store"])
            self.assertTrue((d / f"store-ttd-{EVERY}" / "decisions.jsonl").exists())
            run_main(d, FakeRerun(ROWS))  # a stale copy is replaced and then removed again
            self.assertFalse((d / f"store-ttd-{EVERY}").exists())

    def test_copy_removed_when_the_rerun_fails(self):
        # inject: remove the copy only on success (no try/finally)
        with tempfile.TemporaryDirectory() as t:
            d = make_phase_a(t)

            def boom(phase_a, copy, every):
                raise RuntimeError("costmap failed")

            with self.assertRaises(RuntimeError):
                run_main(d, boom)
            self.assertFalse((d / f"store-ttd-{EVERY}").exists())

    def test_stdout_has_one_line_per_k_then_caveat(self):
        # inject: print the caveat before the K lines, or drop it
        with tempfile.TemporaryDirectory() as t:
            d = make_phase_a(t)
            code, text, out = run_main(d, FakeRerun(ROWS), ks="1,2")
            lines = text.splitlines()
            self.assertEqual([ln.split(":")[0] for ln in lines[:2]], ["K=1", "K=2"])
            self.assertEqual(lines[2], f"CAVEAT: {ttd.CAVEAT}")
            self.assertIn(ttd.CAVEAT, ttd.__doc__)
            doc = json.loads(Path(out).read_text())
            self.assertEqual(doc["meta"]["caveat"], ttd.CAVEAT)
            self.assertEqual(doc["schema_version"], "fleet-time-to-detect/1")
            self.assertEqual(set(doc), {"schema_version", "meta", "by_k"})
            self.assertEqual(set(doc["meta"]), set(ttd.META_KEYS))
            self.assertEqual(set(doc["by_k"]), {"1", "2"})
            self.assertEqual(set(doc["by_k"]["1"]), {"summary", "curve", "cells", "false_flag_cells"})
            self.assertEqual(doc["meta"]["publish_times_s"], [100, 200, 300])

    def usage(self, argv):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as cm:
            ttd.main(argv)
        return cm.exception.code, err.getvalue()

    def test_usage_errors(self):
        # inject: use argparse required=True (then --smoke alone fails) or drop the manual check
        full = ["--phase-a", "d", "--publish-every", "100", "--top-k", "5", "--out", "o.json"]
        for drop in ("--phase-a", "--publish-every", "--top-k", "--out"):
            argv = list(full)
            i = argv.index(drop)
            del argv[i:i + 2]
            code, msg = self.usage(argv)
            self.assertEqual(code, 2)
            self.assertIn(drop, msg)
        code, _ = self.usage([])
        self.assertEqual(code, 2)
        code, msg = self.usage(["--smoke", "--out", str(ROOT / "results" / "x.json")])
        self.assertEqual(code, 2)
        self.assertIn("results/", msg)
        code, _ = self.usage(["--phase-a", "d", "--publish-every", "100", "--out", "o.json", "--top-k", "x"])
        self.assertEqual(code, 2)

    def test_smoke_alone_and_tmp_out_pass_validation(self):
        # inject: make the four flags required even with --smoke
        p = ttd.build_parser()
        ttd.validate(p, p.parse_args(["--smoke"]))
        ttd.validate(p, p.parse_args(["--smoke", "--out", str(Path(tempfile.gettempdir()) / "x.json")]))


class TestIsolation(unittest.TestCase):
    def hotspot_tests(self):
        return importlib.import_module("fleet.tests.test_fleet_hotspot")

    def test_isolation_scan_exempts_the_script_and_passes(self):
        # inject: remove "time_to_detect.py" from the exempt list in test_fleet_hotspot.analyst_files (the scan then hits
        # its truth.json / floor_cells words)
        mod = self.hotspot_tests()
        t = mod.TestAnalystIsolation("test_no_ground_truth_in_analyst_code")
        self.assertNotIn("time_to_detect.py", {p.name for p in t.analyst_files()})
        self.assertTrue((ROOT / "fleet" / "time_to_detect.py").exists())
        t.test_no_ground_truth_in_analyst_code()
        mod.TestAnalystIsolation("test_no_analyser_module_imports_replay_export").test_no_analyser_module_imports_replay_export()

    def test_no_import_guard_fails_when_an_analyser_module_imports_it(self):
        # inject: delete the time_to_detect assertion from test_no_analyser_module_imports_replay_export
        mod = self.hotspot_tests()
        for text in ("from time_to_detect import run\n", "import time_to_detect\n", "import os, time_to_detect\n"):
            with tempfile.TemporaryDirectory() as t:
                fa = Path(t) / "fleet" / "fleet_analyser"
                fa.mkdir(parents=True)
                (fa / "evil.py").write_text(text)
                with mock.patch.object(mod, "ROOT", Path(t)):
                    with self.assertRaises(AssertionError):
                        mod.TestAnalystIsolation("test_no_analyser_module_imports_replay_export") \
                            .test_no_analyser_module_imports_replay_export()


def results_listing():
    out = {}
    for dp, _, fs in os.walk(ROOT / "results"):
        for f in fs:
            p = os.path.join(dp, f)
            try:
                st = os.stat(p)
            except OSError:
                continue
            out[p] = (st.st_mtime_ns, st.st_size)
    return out


class TestSmokeEndToEnd(unittest.TestCase):
    def test_smoke_subprocess(self):
        # inject: drop a meta key, let --smoke write under results/, or leave the phase-A temp dir behind in the repo
        before = results_listing()
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "ttd.json"
            t0 = time.time()
            r = subprocess.run([sys.executable, str(ROOT / "fleet" / "time_to_detect.py"), "--smoke", "--out", str(out)],
                               capture_output=True, text=True)
            wall = time.time() - t0
            self.assertEqual(r.returncode, 0, r.stderr[-2000:])
            self.assertLess(wall, 120)
            doc = json.loads(out.read_text())
            self.assertEqual(set(doc["meta"]), set(ttd.META_KEYS))
            self.assertEqual(doc["meta"]["top_k"], [5, 10])
            self.assertGreater(doc["meta"]["n_publishes"], 1)
            self.assertEqual(set(doc["by_k"]), {"5", "10"})
            self.assertIn(ttd.CAVEAT, r.stdout)
            self.assertEqual(len([ln for ln in r.stdout.splitlines() if ln.startswith("K=")]), 2)
            shares = [c["detected_share"] for c in doc["by_k"]["10"]["curve"]]
            self.assertEqual(shares, sorted(shares))
        self.assertEqual(results_listing(), before)


if __name__ == "__main__":
    unittest.main()

"""Tests for fleet/time_to_detect.py (S8P). Hand-written decision rows and an injected costmap rerun, so no simulator is
needed except in the one end-to-end `--smoke` subprocess test. Each case names its red demonstration in an `# inject:`
comment. None skipped. NOTE: the operator fixed this file name; tests/test_fleet_collect.py collects it explicitly."""
import contextlib
import hashlib
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
import costmap  # noqa: E402
import truth as truth_mod  # noqa: E402
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

    def __init__(self, rows, also=None, costmap_rows=()):
        self.rows, self.calls, self.also, self.runs, self.costmap_rows = rows, [], also, [], list(costmap_rows)

    def __call__(self, phase_a, copy, every, run=None):
        self.calls.append((Path(phase_a), Path(copy), every))
        self.runs.append(run)
        st = JsonlStore(copy)
        st.insert("decisions", self.rows)
        if self.costmap_rows:  # what costmap.py upserts: one row per nonzero cell, keyed (run, published_at, zone, cell)
            st.upsert("costmap", ("run", "published_at", "zone", "cell"),
                      [dict(r, run=r.get("run") or run) for r in self.costmap_rows])
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


# ------------------------------------------------------------------------------------------------ S10B windows
# Floor output golden: sha256 of the S8P-fixture output (ROWS / TRUTH / FakeRerun, --top-k 1,2) with meta.phase_a_dir
# set to "FIXED" and re-written by costmap.write_json. Produced by the UNMODIFIED master code (24cb0b7), by running
# /tmp/ttd_golden.py (builds make_phase_a(t), run_main(d, FakeRerun(ROWS), ks="1,2"), normalises, hashes).
FLOOR_GOLDEN = "fb551df1996d49235ada54c3cff9df1a8621ddad3f0345fb0d6635efd8a65bb2"
WRUN = "s10-x"
WT0 = "2026-01-01T00:00:00Z"
WF = int(truth_mod.epoch_of(WT0))  # first message of every zone
WPUB = [WF + 100, WF + 200, WF + 300]  # steps 20, 40, 60 at step_seconds 5


def wtruth(zone_windows, key="blocked_windows", v2=True):
    """zone_windows {zone: [(cell, start, end)]} -> truth doc (v2 unless v2=False -> v1 with floor_cells only)."""
    zones = {z: ({key: [dict(cell=c, start_step=a, end_step=b) for c, a, b in ws], "floor_cells": {}})
             for z, ws in zone_windows.items()}
    doc = dict(schema_version="fleet-truth/2", env_id="E", disturb={}, steps=60, step_seconds=5, t0=WT0, zones=zones)
    if not v2:
        doc = dict(schema_version="fleet-truth/1", env_id="E", disturb={}, steps=60,
                   zones={z: dict(floor_cells={}) for z in zone_windows})
    return doc


def wrow(zone, cell, step, rank, run=WRUN):
    return row(zone, cell, WF + 5 * step, rank, run=run)


def make_window_phase_a(d, truth_doc, runs=(WRUN,), orig_extra=()):
    d = Path(d)
    st = JsonlStore(d / "store")
    st.insert("decisions", list(orig_extra))
    st.close()
    (d / "store" / "decisions.jsonl").touch()
    if runs is not None:
        (d / "store" / "ingest_runs.jsonl").write_text("".join(json.dumps(dict(run=r, glob="g")) + "\n" for r in runs))
    (d / "truth.json").write_text(json.dumps(truth_doc))
    return d


# two zones, two blocked windows, three publishes (steps 20, 40, 60), K=2 unless noted. Hand-computed:
#   Z0 1,1 [30,50): r1@20 (preflag; window not open yet -> false flag), r2@40 (detected, 10 steps = 50 s, rank 2),
#                   r1@60 (only post-end publish, still flagged -> cleared_s null, stale_at_end; false flag at 60)
#   Z1 3,3 [10,45): r3@20 (not in top 2), r1@40 (detected, 30 steps = 150 s, rank 1, flag on an OPEN window: not false),
#                   r5@60 (first post-end publish unflagged -> cleared_s (60-45)*5 = 75)
#   Z0 9,9 r2@20 (no window: false flag). False flags per publish: 20 -> 2, 40 -> 0, 60 -> 1 (mean 1.0).
WWIN = {"0": [("1,1", 30, 50)], "1": [("3,3", 10, 45)]}
WROWS = [wrow("0", "1,1", 20, 1), wrow("0", "9,9", 20, 2), wrow("1", "3,3", 20, 3),
         wrow("0", "1,1", 40, 2), wrow("1", "3,3", 40, 1),
         wrow("0", "1,1", 60, 1), wrow("1", "3,3", 60, 5)]


def wanalyse(rows, windows, ks=(2,), kind="blocked", pub=WPUB, key="blocked_windows"):
    doc = wtruth(windows, key=key)
    by_k, w, h = ttd.analyse_windows(rows, doc, kind, WF, pub, list(ks), WRUN)
    return by_k, doc


def only(by_k, k, zone, i=0):
    return by_k[str(k)]["windows"][zone][i]


class TestWindowAnalysis(unittest.TestCase):
    def test_exact_windows_preflag_stale_and_false_flags(self):
        # inject: measure from end instead of start, count rank < K, drop the start<=s<end guard, or use forecast_steps
        by_k, _ = wanalyse(WROWS, WWIN)
        a, b = only(by_k, 2, "0"), only(by_k, 2, "1")
        self.assertEqual((a["first_detect_s"], a["rank_at_detect"], a["cleared_s"]), (50, 2, None))
        self.assertEqual((a["preflag"], a["stale_at_end"], a["open_at_end"], a["missed"], a["detected"]),
                         (True, True, False, False, True))
        self.assertEqual((b["first_detect_s"], b["rank_at_detect"], b["cleared_s"]), (150, 1, 75))
        self.assertEqual((b["preflag"], b["stale_at_end"], b["open_at_end"], b["missed"], b["detected"]),
                         (False, False, False, False, True))
        s = by_k["2"]["summary"]
        self.assertEqual((s["n_windows"], s["n_detected"], s["share_detected"]), (2, 2, 1.0))
        self.assertEqual((s["preflag"], s["stale_at_end"], s["open_at_end"], s["missed"]), (1, 1, 0, 0))
        self.assertEqual(s["first_detect_s"], dict(p25=75.0, median=100.0, p75=125.0))
        self.assertEqual(s["cleared_s"], dict(p25=75, median=75, p75=75))
        self.assertEqual(s["false_flags_per_publish_mean"], 1.0)
        self.assertEqual(by_k["2"]["false_flag_cells"], {"100": {"0": ["1,1", "9,9"]}, "200": {}, "300": {"0": ["1,1"]}})

    def test_flag_on_open_window_is_not_false_and_flag_off_window_is(self):
        # inject: score false flags with truth.forecast_steps (3600 s horizon) or ignore the window span
        by_k, _ = wanalyse(WROWS, WWIN)
        ff = by_k["2"]["false_flag_cells"]
        self.assertNotIn("3,3", ff["200"].get("1", []))
        self.assertEqual(ff["200"], {})
        self.assertIn("1,1", ff["100"]["0"])  # flagged before its window opened
        self.assertIn("1,1", ff["300"]["0"])  # flagged after its window closed

    def test_matched_kind_of_any_type_is_not_false(self):
        # inject: only accept the measured kind as a positive
        doc = wtruth({"0": [("1,1", 30, 50)]})
        doc["zones"]["0"]["floor_cells"] = {"5,5": 0.9}
        doc["zones"]["0"]["outage_windows"] = [dict(cell="6,6", start_step=0, end_step=60)]
        rows = [wrow("0", "5,5", 40, 1), wrow("0", "6,6", 40, 2), wrow("0", "7,7", 40, 3), wrow("0", "1,1", 20, 1),
                wrow("0", "1,1", 60, 1)]
        by_k, _, _ = ttd.analyse_windows(rows, doc, "blocked", WF, WPUB, [3], WRUN)
        self.assertEqual(by_k["3"]["false_flag_cells"]["200"], {"0": ["7,7"]})

    def test_k_uses_rank_only(self):
        # inject: filter rows by a fixed K
        by_k, _ = wanalyse(WROWS, WWIN, ks=(1, 2))
        a = only(by_k, 1, "0")
        self.assertEqual((a["detected"], a["missed"], a["preflag"], a["first_detect_s"]), (False, True, True, None))
        self.assertTrue(only(by_k, 1, "1")["detected"])
        self.assertTrue(only(by_k, 2, "0")["detected"])

    def test_window_ending_before_first_publish_is_missed(self):
        # inject: allow detection after the window ended, or flag missed windows stale_at_end / open_at_end
        rows = [wrow("0", "4,4", s, 1) for s in (20, 40, 60)]
        by_k, _ = wanalyse(rows, {"0": [("4,4", 5, 15)]})
        w = only(by_k, 2, "0")
        self.assertEqual((w["first_detect_s"], w["cleared_s"], w["detected"], w["open_at_end"], w["stale_at_end"],
                          w["missed"]), (None, None, False, False, False, True))
        s = by_k["2"]["summary"]
        self.assertEqual((s["missed"], s["n_detected"], s["stale_at_end"], s["open_at_end"]), (1, 0, 0, 0))
        self.assertEqual(s["first_detect_s"], dict(p25=None, median=None, p75=None))

    def test_detected_window_without_post_end_publish_is_open_not_stale(self):
        # inject: report such a window as stale_at_end or as cleared
        rows = [wrow("0", "1,1", 40, 1), wrow("0", "1,1", 60, 1)]
        by_k, _ = wanalyse(rows, {"0": [("1,1", 30, 70)]})
        w = only(by_k, 2, "0")
        self.assertEqual((w["detected"], w["first_detect_s"], w["cleared_s"], w["open_at_end"], w["stale_at_end"]),
                         (True, 50, None, True, False))

    def test_missed_window_without_post_end_publish_is_not_open(self):
        # inject: set open_at_end for every window with no post-end publish
        rows = [wrow("0", "1,1", 20, 1), wrow("0", "1,1", 40, 1)]
        by_k, _ = wanalyse(rows, {"0": [("1,1", 50, 80)]})  # not flagged at the one in-window publish (step 60)
        w = only(by_k, 2, "0")
        self.assertEqual((w["missed"], w["open_at_end"], w["stale_at_end"], w["cleared_s"]), (True, False, False, None))

    def test_flag_only_after_the_window_ended_is_missed_and_not_stale(self):
        # inject: let a post-end flag count as detection
        rows = [wrow("0", "1,1", 60, 1)]
        by_k, _ = wanalyse(rows, {"0": [("1,1", 30, 50)]})
        w = only(by_k, 2, "0")
        self.assertEqual((w["missed"], w["stale_at_end"], w["open_at_end"], w["first_detect_s"]), (True, False, False, None))

    def test_reflag_after_a_clear_still_counts_as_cleared(self):
        # inject: require the cell to stay unflagged at every later publish
        pub = [WF + 100, WF + 200, WF + 250, WF + 300]  # steps 20, 40, 50, 60
        rows = [wrow("0", "1,1", 40, 1), wrow("0", "1,1", 60, 1), wrow("0", "9,9", 50, 1)]
        by_k, _ = wanalyse(rows, {"0": [("1,1", 30, 45)]}, pub=pub)
        w = only(by_k, 2, "0")
        self.assertEqual((w["cleared_s"], w["stale_at_end"]), (25, False))  # first unflagged publish: step 50

    def test_outage_kind_reads_outage_windows(self):
        # inject: read blocked_windows for every kind
        doc = wtruth({"0": [("2,2", 30, 50)]}, key="outage_windows")
        doc["zones"]["0"]["blocked_windows"] = [dict(cell="1,1", start_step=0, end_step=60)]
        by_k, _, _ = ttd.analyse_windows([wrow("0", "2,2", 40, 1), wrow("0", "2,2", 60, 9)], doc, "outage", WF, WPUB, [2],
                                         WRUN)
        self.assertEqual(by_k["2"]["summary"]["n_windows"], 1)
        self.assertEqual(only(by_k, 2, "0")["cell"], "2,2")


def norm_sha(out):
    doc = json.loads(Path(out).read_text())
    doc["meta"]["phase_a_dir"] = "FIXED"
    n = Path(out).with_name("norm.json")
    costmap.write_json(n, doc)
    return hashlib.sha256(n.read_bytes()).hexdigest()


class TestFloorByteIdentity(unittest.TestCase):
    def test_floor_output_bytes_match_the_pre_change_golden(self):
        # inject: add a meta key, change the key order or schema_version, or let --truth-kind floor take another path
        for extra in ((), ("--truth-kind", "floor")):
            with tempfile.TemporaryDirectory() as t:
                d = make_phase_a(t)
                _, text, out = run_main(d, FakeRerun(ROWS), extra=extra, ks="1,2")
                self.assertEqual(norm_sha(out), FLOOR_GOLDEN, extra)
                self.assertIn(f"CAVEAT: {ttd.CAVEAT}", text)

    def test_floor_meta_keys_are_exactly_the_existing_ones(self):
        # inject: add truth_kind / run to the floor meta
        with tempfile.TemporaryDirectory() as t:
            d = make_phase_a(t)
            fake = FakeRerun(ROWS)
            _, _, out = run_main(d, fake, extra=("--truth-kind", "floor"))
            self.assertEqual(set(json.loads(Path(out).read_text())["meta"]), set(ttd.META_KEYS))
            self.assertEqual(fake.runs, [None])  # floor calls the rerun with the old three-argument signature


class TestWindowRunAndMeta(unittest.TestCase):
    def run_w(self, d, rows, kind="blocked", ks="2", fake=None):
        fake = fake or FakeRerun(rows)
        return fake, run_main(d, fake, extra=("--truth-kind", kind), ks=ks,
                              sp=span(t0={"0": WF, "1": WF}, first=WF, end=WF + 300))

    def test_window_run_end_to_end_meta_and_stdout(self):
        # inject: drop a window meta key, print the floor caveat, or change the caveat text
        with tempfile.TemporaryDirectory() as t:
            d = make_window_phase_a(t, wtruth(WWIN))
            fake, (code, text, out) = self.run_w(d, WROWS)
            doc = json.loads(Path(out).read_text())
            self.assertEqual(set(doc["meta"]),
                             set(ttd.META_KEYS) | {"truth_kind", "run", "n_windows", "window_len_steps_median"})
            m = doc["meta"]
            self.assertEqual((m["truth_kind"], m["run"], m["n_windows"], m["window_len_steps_median"]),
                             ("blocked", WRUN, 2, 27.5))
            self.assertEqual(m["caveat"], "Windows have a start and an end; detection is measured from the start, "
                                          "clearing from the end.")
            self.assertEqual(text.splitlines()[-2], f"CAVEAT: {m['caveat']}")
            self.assertEqual(doc["by_k"]["2"]["summary"]["stale_at_end"], 1)
            self.assertFalse((d / f"store-ttd-{EVERY}").exists())

    def test_inferred_run_is_used_for_select_strip_and_rerun(self):
        # inject: use the constant RUN in select_forecasts, strip_forecasts or the rerun call
        other = [wrow("1", "3,3", 20, 1, run="closed_loop"), wrow("0", "1,1", 20, 1, run="closed_loop")]
        with tempfile.TemporaryDirectory() as t:
            stale = wrow("0", "9,9", 60, 1)  # phase A's own row of the inferred run: must be stripped before the rerun
            d = make_window_phase_a(t, wtruth(WWIN), orig_extra=[stale])
            fake, (_, _, out) = self.run_w(d, WROWS + other)
            self.assertEqual(fake.runs, [WRUN])
            ref = json.loads(Path(out).read_text())["by_k"]
            with tempfile.TemporaryDirectory() as t2:
                d2 = make_window_phase_a(t2, wtruth(WWIN))
                _, (_, _, out2) = self.run_w(d2, WROWS)
                self.assertEqual(json.loads(Path(out2).read_text())["by_k"], ref)  # rows of another run ignored
            self.assertEqual(ref["2"]["false_flag_cells"]["300"], {"0": ["1,1"]})  # stale 9,9@60 not kept
            copy = Path(t) / "copy"
            shutil.copytree(d / "store", copy)
            self.assertEqual(ttd.strip_forecasts(copy), 0)
            self.assertEqual(ttd.strip_forecasts(copy, WRUN), 1)

    def test_run_inference_errors(self):
        # inject: take the first run, default to closed_loop, or return None for a missing file
        with tempfile.TemporaryDirectory() as t:
            d = make_window_phase_a(t, wtruth(WWIN), runs=("a", "b", "a"))
            with self.assertRaisesRegex(ValueError, r"\['a', 'b'\]"):
                self.run_w(d, WROWS)
            self.assertFalse((d / f"store-ttd-{EVERY}").exists())
        with tempfile.TemporaryDirectory() as t:
            d = make_window_phase_a(t, wtruth(WWIN), runs=None)
            with self.assertRaisesRegex(ValueError, "ingest_runs.jsonl"):
                self.run_w(d, WROWS)
        with tempfile.TemporaryDirectory() as t:
            d = make_window_phase_a(t, wtruth(WWIN), runs=())
            (d / "store" / "ingest_runs.jsonl").write_text("\n")
            with self.assertRaisesRegex(ValueError, "no run"):
                self.run_w(d, WROWS)

    def test_v1_truth_with_a_window_kind_raises(self):
        # inject: fall through to floor_cells for a v1 file
        for kind in ("blocked", "outage"):
            with tempfile.TemporaryDirectory() as t:
                d = make_window_phase_a(t, wtruth(WWIN, v2=False))
                with self.assertRaisesRegex(ValueError, "v2"):
                    self.run_w(d, WROWS, kind=kind)

    def test_truth_t0_must_equal_the_zone_first_message(self):
        # inject: drop the one-clock assertion
        with tempfile.TemporaryDirectory() as t:
            d = make_window_phase_a(t, wtruth(WWIN))
            with self.assertRaisesRegex(ValueError, "first message"):
                run_main(d, FakeRerun(WROWS), extra=("--truth-kind", "blocked"),
                         sp=span(t0={"0": WF + 5, "1": WF}, first=WF, end=WF + 300))

    def test_queue_item_argvs_validate(self):
        # inject: drop --truth-kind from the parser
        base = ["--publish-every", "300", "--top-k", "10,20,40"]
        for kind in ("blocked", "outage"):
            p = ttd.build_parser()
            a = p.parse_args(["--phase-a", f"fleet/data/s10-{kind}", "--truth-kind", kind, *base, "--out",
                              f"results/fleet/time_to_detect_{kind}.json"])
            self.assertEqual(ttd.validate(p, a), [10, 20, 40])
            self.assertEqual(a.truth_kind, kind)
            self.assertEqual((a.sweep_k_values, a.sweep_cost_values, a.reference), (None, None, None))
        p = ttd.build_parser()  # wr-s10e-amoc-run
        a = p.parse_args(["--phase-a", "fleet/data/s10c-blind", "--truth-kind", "blocked", "--publish-every", "300",
                          "--top-k", "20", "--sweep-k", "5,10,20,40,80", "--sweep-cost", "0.2,0.4,0.6,0.8", "--reference",
                          "fleet/data/s10-none", "--out", "results/fleet/amoc_blind.json"])
        self.assertEqual(ttd.validate(p, a), [20])
        self.assertEqual(a.sweep_k_values, [5, 10, 20, 40, 80])
        self.assertEqual(a.sweep_cost_values, [0.2, 0.4, 0.6, 0.8])
        p = ttd.build_parser()
        self.assertEqual(p.parse_args([]).truth_kind, "floor")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            p.parse_args(["--truth-kind", "frozen"])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            ttd.validate(p, p.parse_args(["--smoke", "--truth-kind", "blocked"]))


# ------------------------------------------------------------------------------------------------ S10E AMOC
# Window-path golden, computed on base 7bebef4 BEFORE editing time_to_detect.py by running /tmp/ttd_window_golden.py
# (make_window_phase_a(t, wtruth(WWIN)), FakeRerun(WROWS), run_main(..., extra=("--truth-kind","blocked"), ks="2",
# sp=span(t0={"0": WF, "1": WF}, first=WF, end=WF + 300)); sha256 via norm_sha, stdout with the final line's --out path and
# elapsed seconds replaced by "OUT (Ns)").
WINDOW_GOLDEN = "04f11c527c9dcbc9cec2076cbc066d66b320d6b7b5268043f58fde64bef35bab"
WINDOW_STDOUT = (
    "K=2: windows 2, detected 2 (1.000), missed 0, preflag 1, stale at end 1, open at end 0, first detect s p25/median/p75 "
    "75.0/100.0/125.0, cleared s 75.0/75.0/75.0, false flags per publish 1.0\n"
    "CAVEAT: Windows have a start and an end; detection is measured from the start, clearing from the end.\n"
    "time_to_detect: 3 publishes, Ks [2] -> OUT (Ns)\n")

REF = "s10-ref"


def norm_stdout(text):
    import re
    return re.sub(r"-> \S+ \(\d+\.\d+s\)", "-> OUT (Ns)", text)


def cmrow(zone, cell, step, cost, run=WRUN):
    return dict(run=run, zone=zone, published_at=WF + 5 * step, cell=cell, cost=cost, score=cost, stalls=1)


def refrow(zone, cell, step, rank):
    return wrow(zone, cell, step, rank, run=REF)


# measured costmap rows (run WRUN), by publish step 20 / 40 / 60
WCM = [cmrow("0", "1,1", 20, 0.9), cmrow("0", "9,9", 20, 0.5), cmrow("1", "3,3", 20, 0.3),
       cmrow("0", "1,1", 40, 0.7), cmrow("1", "3,3", 40, 0.9), cmrow("0", "7,7", 40, 0.25),
       cmrow("0", "1,1", 60, 0.8), cmrow("1", "3,3", 60, 0.1),
       cmrow("0", "1,1", 30, 0.99)]  # step 30 is not a publish time: ignored
# reference forecasts (run REF), ranks per zone; a rank-1 row at step 30 (not a publish time) is ignored
RROWS = [refrow("0", "a", 20, 1), refrow("0", "b", 20, 2), refrow("0", "c", 20, 3), refrow("1", "e", 20, 1),
         refrow("0", "a", 40, 1), refrow("0", "a", 60, 1), refrow("0", "d", 60, 4), refrow("1", "f", 60, 2),
         refrow("0", "a", 30, 1)]
RCM = [cmrow("0", "a", 20, 0.9, REF), cmrow("0", "b", 20, 0.6, REF), cmrow("1", "e", 20, 0.95, REF),
       cmrow("0", "a", 40, 0.8, REF), cmrow("0", "a", 60, 0.5, REF), cmrow("0", "b", 60, 0.2, REF),
       cmrow("1", "f", 60, 0.3, REF), cmrow("0", "a", 30, 0.99, REF)]
HOURS = 300 / 3600  # steps 60 * step_seconds 5


class Dispatch:
    """One rerun callable for two dirs: routes on phase_a."""

    def __init__(self, by):
        self.by = {str(Path(k)): v for k, v in by.items()}

    def __call__(self, phase_a, copy, every, run=None):
        return self.by[str(Path(phase_a))](phase_a, copy, every, run=run)


def dspan(by):
    by = {str(Path(k)): v for k, v in by.items()}
    def sp(glob):
        t0, first, end = by[str(Path(glob).parent)]
        return dict(t0), first, end
    return sp


class TestAmoc(unittest.TestCase):
    ZSPAN = ({"0": WF, "1": WF}, WF, WF + 300)

    def setup_dirs(self, t, ref_doc=None, ref_runs=(REF,), ref_span=None, stale_cm=(), rows=WROWS, windows=WWIN, cm=WCM,
                   ref_rows=RROWS, ref_cm=RCM, ref_also=None):
        (Path(t) / "m").mkdir()
        d = make_window_phase_a(Path(t) / "m", wtruth(windows))
        ref = Path(t) / "r"
        ref.mkdir()
        make_window_phase_a(ref, ref_doc or wtruth({"0": [], "1": []}), runs=ref_runs)
        if stale_cm:
            st = JsonlStore(d / "store")
            st.upsert("costmap", ("run", "published_at", "zone", "cell"), list(stale_cm))
            st.close()
        fakes = {d: FakeRerun(rows, costmap_rows=cm), ref: FakeRerun(ref_rows, costmap_rows=ref_cm, also=ref_also)}
        sp = dspan({d: self.ZSPAN, ref: ref_span or self.ZSPAN})
        return d, ref, Dispatch(fakes), sp, fakes

    def amoc_run(self, t, sweep=("--sweep-k", "3,1,2", "--sweep-cost", "0.95,0.8,0.5"), use_ref=True, ks="2", **kw):
        d, ref, rr, sp, fakes = self.setup_dirs(t, **kw)
        extra = ("--truth-kind", "blocked", *sweep, *(("--reference", str(ref)) if use_ref else ()))
        code, text, out = run_main(d, rr, extra=extra, ks=ks, sp=sp, out=str(Path(t) / "out.json"))
        return d, ref, fakes, code, text, json.loads(Path(out).read_text()), out

    # ---- identity without the new flags
    def test_window_output_and_stdout_match_the_pre_change_golden(self):
        # inject: add a key / line to the window output without a sweep flag, or reorder meta
        with tempfile.TemporaryDirectory() as t:
            d = make_window_phase_a(t, wtruth(WWIN))
            _, (code, text, out) = TestWindowRunAndMeta().run_w(d, WROWS)
            self.assertEqual(norm_sha(out), WINDOW_GOLDEN)
            self.assertEqual(norm_stdout(text), WINDOW_STDOUT)
            doc = json.loads(Path(out).read_text())
            self.assertEqual(set(doc), {"schema_version", "meta", "by_k"})

    def test_by_k_is_equal_with_and_without_the_sweep(self):
        # inject: let the sweep reuse / mutate the by_k rows
        with tempfile.TemporaryDirectory() as t:
            d = make_window_phase_a(t, wtruth(WWIN))
            _, (_, _, out) = TestWindowRunAndMeta().run_w(d, WROWS)
            plain = json.loads(Path(out).read_text())
        with tempfile.TemporaryDirectory() as t:
            *_, doc, _ = self.amoc_run(t)
        self.assertEqual(doc["by_k"], plain["by_k"])
        self.assertEqual({k: v for k, v in doc["meta"].items() if k in plain["meta"] and k != "phase_a_dir"},
                         {k: v for k, v in plain["meta"].items() if k != "phase_a_dir"})

    # ---- hand-computed values
    def test_k_sweep_hand_computed(self):
        # inject: count rank < K, use the span instead of steps*step_seconds as hours, or divide by zones once
        with tempfile.TemporaryDirectory() as t:
            d, ref, fakes, code, text, doc, _ = self.amoc_run(t)
        self.assertEqual(code, 0)
        ks = doc["amoc"]["k"]
        self.assertEqual([e["K"] for e in ks], [1, 2, 3])
        for e in ks:
            self.assertEqual(set(e), {"K", "median_delay_s", "p25", "p75", "miss_share", "stale_at_end_share", "n_windows",
                                      "n_detected", "fa_per_hour_reference", "fa_per_hour_reference_by_zone",
                                      "fa_per_hour_measured_outside_windows"})
            self.assertEqual(e["n_windows"], 2)
        a = self.assertAlmostEqual
        # K=1: Z0 window missed, Z1 detected at 150 s; measured false flags 2 (1,1@20 and 1,1@60)
        k1, k2, k3 = ks
        self.assertEqual((k1["n_detected"], k1["miss_share"], k1["stale_at_end_share"]), (1, 0.5, 0.0))
        self.assertEqual((k1["median_delay_s"], k1["p25"], k1["p75"]), (150, 150, 150))
        a(k1["fa_per_hour_measured_outside_windows"], 2 / (2 * HOURS))
        # K=2: both detected (50 s, 150 s), Z0 stale at end; 3 false flags (2 + 0 + 1)
        self.assertEqual((k2["n_detected"], k2["miss_share"], k2["stale_at_end_share"]), (2, 0.0, 0.5))
        self.assertEqual((k2["median_delay_s"], k2["p25"], k2["p75"]), (100.0, 75.0, 125.0))
        a(k2["fa_per_hour_measured_outside_windows"], 3 / (2 * HOURS))
        # K=3: both detected at 50 s; 3 false flags
        self.assertEqual((k3["miss_share"], k3["stale_at_end_share"], k3["median_delay_s"]), (0.0, 0.5, 50.0))
        a(k3["fa_per_hour_measured_outside_windows"], 3 / (2 * HOURS))
        # reference flags: K=1 -> z0 3, z1 1; K=2 -> z0 4, z1 2; K=3 -> z0 5, z1 2 (the rank-1 row at step 30 is ignored)
        for e, z0, z1 in ((k1, 3, 1), (k2, 4, 2), (k3, 5, 2)):
            a(e["fa_per_hour_reference"], (z0 + z1) / (2 * HOURS))
            self.assertEqual(set(e["fa_per_hour_reference_by_zone"]), {"0", "1"})
            a(e["fa_per_hour_reference_by_zone"]["0"], z0 / HOURS)
            a(e["fa_per_hour_reference_by_zone"]["1"], z1 / HOURS)
        self.assertEqual(doc["amoc"]["k_at_miss_below_half"]["K"], 2)
        self.assertEqual(doc["amoc"]["k_at_miss_below_half"]["miss_share"], 0.0)
        a(doc["amoc"]["k_at_miss_below_half"]["fa_per_hour_reference"], 6 / (2 * HOURS))

    def test_cost_sweep_hand_computed(self):
        # inject: use > instead of >= for the threshold, keep non-publish rows, or walk cost ascending
        with tempfile.TemporaryDirectory() as t:
            d, ref, fakes, code, text, doc, _ = self.amoc_run(t)
        cs = doc["amoc"]["cost"]
        self.assertEqual([e["cost"] for e in cs], [0.5, 0.8, 0.95])
        c5, c8, c95 = cs
        a = self.assertAlmostEqual
        # c=0.5: both detected (50 s, 150 s), Z0 stale; 3 false flags (1,1@20, 9,9@20, 1,1@60)
        self.assertEqual((c5["miss_share"], c5["stale_at_end_share"], c5["median_delay_s"], c5["p25"], c5["p75"]),
                         (0.0, 0.5, 100.0, 75.0, 125.0))
        a(c5["fa_per_hour_measured_outside_windows"], 3 / (2 * HOURS))
        # c=0.8 (>=: 1,1@60 at 0.8 counts): Z0 missed, Z1 detected at 150 s; false flags 1,1@20 and 1,1@60
        self.assertEqual((c8["miss_share"], c8["stale_at_end_share"], c8["median_delay_s"], c8["n_detected"]),
                         (0.5, 0.0, 150, 1))
        a(c8["fa_per_hour_measured_outside_windows"], 2 / (2 * HOURS))
        # c=0.95: nothing flagged, both missed
        self.assertEqual((c95["miss_share"], c95["n_detected"], c95["median_delay_s"], c95["p25"], c95["p75"]),
                         (1.0, 0, None, None, None))
        self.assertEqual(c95["fa_per_hour_measured_outside_windows"], 0.0)
        # reference: c=0.5 -> z0 4 (0.9,0.6,0.8,0.5), z1 1; c=0.8 -> z0 2, z1 1; c=0.95 -> z0 0, z1 1
        for e, z0, z1 in ((c5, 4, 1), (c8, 2, 1), (c95, 0, 1)):
            a(e["fa_per_hour_reference"], (z0 + z1) / (2 * HOURS))
            a(e["fa_per_hour_reference_by_zone"]["0"], z0 / HOURS)
            a(e["fa_per_hour_reference_by_zone"]["1"], z1 / HOURS)
        # walking from the strictest (highest) cost: 0.95 misses 1.0, 0.8 misses 0.5 (not < 0.5), 0.5 misses 0.0
        pick = doc["amoc"]["cost_at_miss_below_half"]
        self.assertEqual((pick["cost"], pick["miss_share"]), (0.5, 0.0))
        a(pick["fa_per_hour_reference"], 5 / (2 * HOURS))
        self.assertEqual(set(pick), {"cost", "miss_share", "fa_per_hour_reference"})

    def test_meta_keys_stdout_lines_and_cleanup(self):
        # inject: omit a meta key, print the AMOC lines after the CAVEAT, or leave a store-ttd dir behind
        with tempfile.TemporaryDirectory() as t:
            d, ref, fakes, code, text, doc, _ = self.amoc_run(t)
            self.assertEqual(list(doc), ["schema_version", "meta", "by_k", "amoc"])
            self.assertEqual(list(doc["amoc"]), ["k", "cost", "k_at_miss_below_half", "cost_at_miss_below_half"])
            m = doc["meta"]
            self.assertEqual(set(m) - set(ttd.META_KEYS) - {"truth_kind", "run", "n_windows", "window_len_steps_median"},
                             {"reference_dir", "reference_run", "reference_store_hash_before", "reference_store_hash_after",
                              "sim_hours", "sim_hours_reference", "n_publishes_reference", "sweep_k", "sweep_cost",
                              "amoc_definitions"})
            self.assertEqual((m["reference_dir"], m["reference_run"], m["n_publishes_reference"]), (str(ref), REF, 3))
            self.assertEqual((m["sweep_k"], m["sweep_cost"]), ([1, 2, 3], [0.5, 0.8, 0.95]))
            self.assertAlmostEqual(m["sim_hours"], HOURS)
            self.assertAlmostEqual(m["sim_hours_reference"], HOURS)
            self.assertEqual(m["reference_store_hash_before"], m["reference_store_hash_after"])
            self.assertEqual(m["reference_store_hash_before"], ttd.sha256_file(ref / "store" / "decisions.jsonl"))
            self.assertTrue(all(isinstance(v, str) for v in m["amoc_definitions"].values()))
            lines = text.splitlines()
            self.assertEqual(lines[0].split(":")[0], "K=2")
            self.assertEqual([ln.split(":")[0] for ln in lines[1:4]], ["AMOC K=1", "AMOC K=2", "AMOC K=3"])
            self.assertEqual([ln.split(":")[0] for ln in lines[4:7]], ["AMOC cost=0.5", "AMOC cost=0.8", "AMOC cost=0.95"])
            self.assertTrue(lines[7].startswith("AMOC K at miss share < 0.5: K=2"))
            self.assertTrue(lines[8].startswith("AMOC cost at miss share < 0.5: cost=0.5"))
            self.assertTrue(lines[9].startswith("CAVEAT:"))
            self.assertTrue(lines[10].startswith("time_to_detect:"))
            self.assertEqual(len(lines), 11)
            for dd in (d, ref):
                self.assertEqual([p.name for p in dd.glob("store-ttd-*")], [])
            self.assertEqual([len(f.calls) for f in fakes.values()], [1, 1])

    def test_only_the_requested_sweep_keys_and_null_miss_below_half(self):
        # inject: always emit both lists, or return the last entry instead of null when no miss share is below 0.5
        with tempfile.TemporaryDirectory() as t:
            *_, doc, _ = self.amoc_run(t, sweep=("--sweep-k", "1"))
        self.assertEqual(list(doc["amoc"]), ["k", "k_at_miss_below_half"])
        self.assertIsNone(doc["amoc"]["k_at_miss_below_half"])  # K=1 misses 0.5, not < 0.5
        self.assertEqual(doc["meta"]["sweep_cost"], None)
        with tempfile.TemporaryDirectory() as t:
            *_, code, text, doc, _ = self.amoc_run(t, sweep=("--sweep-cost", "0.95"))
        self.assertEqual(list(doc["amoc"]), ["cost", "cost_at_miss_below_half"])
        self.assertIsNone(doc["amoc"]["cost_at_miss_below_half"])
        self.assertIn("AMOC cost at miss share < 0.5: none", text)

    def test_without_reference_the_reference_fields_are_null(self):
        # inject: report 0.0 instead of null without a reference
        with tempfile.TemporaryDirectory() as t:
            d, ref, fakes, code, text, doc, _ = self.amoc_run(t, use_ref=False)
        for e in doc["amoc"]["k"] + doc["amoc"]["cost"]:
            self.assertIsNone(e["fa_per_hour_reference"])
            self.assertIsNone(e["fa_per_hour_reference_by_zone"])
            self.assertIsNotNone(e["fa_per_hour_measured_outside_windows"])
        m = doc["meta"]
        self.assertEqual((m["reference_dir"], m["reference_run"], m["sim_hours_reference"], m["n_publishes_reference"]),
                         (None, None, None, None))
        self.assertEqual(len(fakes[ref].calls), 0)
        self.assertIn("FA/h ref n/a", text)

    def test_zero_windows_give_null_shares(self):
        # inject: divide by n_windows without the zero guard
        with tempfile.TemporaryDirectory() as t:
            *_, doc, _ = self.amoc_run(t, sweep=("--sweep-k", "2"), windows={"0": [], "1": []})
        e = doc["amoc"]["k"][0]
        self.assertEqual((e["n_windows"], e["miss_share"], e["stale_at_end_share"], e["median_delay_s"]), (0, None, None, None))
        self.assertIsNone(doc["amoc"]["k_at_miss_below_half"])

    def test_sweep_calls_the_unchanged_analyser_on_the_same_rows(self):
        # inject: sweep a re-derived forecast list, or feed the cost sweep real ranks instead of rank 1
        calls = []
        orig = ttd.analyse_windows_k

        def spy(k, forecasts, *rest):
            calls.append((k, list(forecasts)))
            return orig(k, forecasts, *rest)
        with mock.patch.object(ttd, "analyse_windows_k", spy), tempfile.TemporaryDirectory() as t:
            *_, doc, _ = self.amoc_run(t, sweep=("--sweep-k", "1,3", "--sweep-cost", "0.8"))
        self.assertEqual([c[0] for c in calls], [2, 1, 3, 1])  # by_k (K=2), the K sweep, one cost entry at k=1
        self.assertEqual(calls[0][1], calls[1][1])
        self.assertEqual(calls[0][1], calls[2][1])
        pseudo = calls[3][1]
        self.assertEqual(sorted((f["zone"], f["cell"], f["t"], f["rank"]) for f in pseudo),
                         sorted([("0", "1,1", WF + 100, 1), ("1", "3,3", WF + 200, 1), ("0", "1,1", WF + 300, 1)]))

    def test_stale_phase_a_costmap_row_is_not_counted(self):
        # inject: drop the strip_costmap call in rerun_on_copy
        stale = cmrow("0", "1,1", 40, 0.99)  # phase A's row: would detect Z0 1,1 at c=0.95 if it survived into the copy
        with tempfile.TemporaryDirectory() as t:
            d, ref, fakes, code, text, doc, _ = self.amoc_run(t, sweep=("--sweep-cost", "0.95"), stale_cm=[stale])
            self.assertEqual(doc["amoc"]["cost"][0]["miss_share"], 1.0)
            self.assertEqual(doc["amoc"]["cost"][0]["n_detected"], 0)
            self.assertEqual(len((d / "store" / "costmap.jsonl").read_text().splitlines()), 1)  # the original is untouched
        with tempfile.TemporaryDirectory() as t:
            d, *_ = self.setup_dirs(t, stale_cm=[stale, cmrow("0", "1,1", 40, 0.5, run="other")])
            copy = Path(t) / "copy"
            shutil.copytree(d / "store", copy)
            self.assertEqual(ttd.strip_costmap(copy, WRUN), 1)
            kept = [json.loads(ln) for ln in (copy / "costmap.jsonl").read_text().splitlines()]
            self.assertEqual([r["run"] for r in kept], ["other"])

    # ---- the reference is checked before anything is written
    def mismatch(self, **kw):
        with tempfile.TemporaryDirectory() as t:
            d, ref, rr, sp, fakes = self.setup_dirs(t, **kw)
            out = str(Path(t) / "out.json")
            with self.assertRaises(ValueError) as cm:
                run_main(d, rr, extra=("--truth-kind", "blocked", "--sweep-k", "1", "--reference", str(ref)), sp=sp, out=out)
            self.assertFalse(Path(out).exists())
            self.assertEqual([len(f.calls) for f in fakes.values()], [0, 0])  # rejected before any rerun
            for dd in (d, ref):
                self.assertEqual([p.name for p in dd.glob("store-ttd-*")], [])
            return str(cm.exception)

    def test_reference_env_id_mismatch(self):
        # inject: drop the env_id comparison
        doc = wtruth({"0": [], "1": []})
        doc["env_id"] = "F"
        msg = self.mismatch(ref_doc=doc)
        self.assertIn("env_id", msg)
        self.assertIn("'E'", msg)
        self.assertIn("'F'", msg)

    def test_reference_steps_mismatch(self):
        # inject: drop the steps comparison
        doc = wtruth({"0": [], "1": []})
        doc["steps"] = 90
        msg = self.mismatch(ref_doc=doc)
        self.assertIn("steps", msg)
        self.assertIn("60", msg)
        self.assertIn("90", msg)

    def test_reference_step_seconds_mismatch(self):
        # inject: drop the step_seconds comparison
        doc = wtruth({"0": [], "1": []})
        doc["step_seconds"] = 10
        self.assertIn("step_seconds", self.mismatch(ref_doc=doc))

    def test_reference_zone_set_mismatch(self):
        # inject: compare the zone count instead of the zone set
        msg = self.mismatch(ref_doc=wtruth({"0": [], "2": []}))
        self.assertIn("zone set", msg)
        self.assertIn("['0', '1']", msg)
        self.assertIn("['0', '2']", msg)

    def test_reference_publish_count_mismatch(self):
        # inject: drop the publish count comparison
        msg = self.mismatch(ref_span=({"0": WF, "1": WF}, WF, WF + 400))
        self.assertIn("publish count", msg)
        self.assertIn("3", msg)
        self.assertIn("4", msg)

    def test_reference_with_truth_or_v1_raises(self):
        # inject: accept a reference that carries floor cells / windows / frozen windows, or a v1 file
        for mutate in ("floor", "blocked", "outage", "frozen"):
            doc = wtruth({"0": [], "1": []})
            z = doc["zones"]["0"]
            if mutate == "floor":
                z["floor_cells"] = {"1,1": 0.9}
            elif mutate == "frozen":
                z["frozen_windows"] = [dict(serial="a", start_step=0, end_step=5)]
            else:
                z[f"{mutate}_windows"] = [dict(cell="1,1", start_step=0, end_step=5)]
            self.assertIn("not an undisturbed run", self.mismatch(ref_doc=doc))
        self.assertIn("v1", self.mismatch(ref_doc=wtruth({"0": [], "1": []}, v2=False)))

    def test_mutated_reference_store_aborts_without_output(self):
        # inject: skip the hash comparison for the reference dir
        def corrupt(phase_a, copy):
            with open(Path(phase_a) / "store" / "decisions.jsonl", "a") as f:
                f.write("{}\n")

        with tempfile.TemporaryDirectory() as t:
            d, ref, rr, sp, fakes = self.setup_dirs(t, ref_also=corrupt)
            out = str(Path(t) / "out.json")
            with self.assertRaisesRegex(RuntimeError, "changed during the rerun"):
                run_main(d, rr, extra=("--truth-kind", "blocked", "--sweep-k", "1", "--reference", str(ref)), sp=sp, out=out)
            self.assertFalse(Path(out).exists())
            for dd in (d, ref):
                self.assertEqual([p.name for p in dd.glob("store-ttd-*")], [])

    def test_one_helper_serves_both_dirs(self):
        # inject: duplicate the sequence for the reference
        with tempfile.TemporaryDirectory() as t:
            seen = []
            orig = ttd.rerun_on_copy

            def spy(src, *a, **kw):
                seen.append(Path(src).name)
                return orig(src, *a, **kw)
            with mock.patch.object(ttd, "rerun_on_copy", spy):
                self.amoc_run(t)
            self.assertEqual(seen, ["m", "r"])

    # ---- usage errors
    def usage(self, argv):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as cm:
            ttd.main(argv)
        return cm.exception.code, err.getvalue()

    def test_usage_errors(self):
        # inject: drop any one of the checks in validate()
        base = ["--phase-a", "d", "--publish-every", "300", "--top-k", "5", "--out", "o.json", "--truth-kind", "blocked"]
        cases = [
            (["--sweep-k", "5,5"], "distinct"), (["--sweep-k", "0"], "integers >= 1"), (["--sweep-k=-3,4"], "integers >= 1"),
            (["--sweep-k", "a,b"], "--sweep-k"), (["--sweep-k", "1.5"], "--sweep-k"), (["--sweep-k", ""], "--sweep-k"),
            (["--sweep-cost", "0.5,0.5"], "distinct"), (["--sweep-cost", "0"], "> 0"), (["--sweep-cost", "-1"], "> 0"),
            (["--sweep-cost", "nan"], "finite"), (["--sweep-cost", "inf"], "finite"), (["--sweep-cost", "0.1,-inf"], "finite"),
            (["--sweep-cost", "x"], "--sweep-cost"), (["--sweep-cost", "1e999"], "finite"),
            (["--reference", "r"], "--reference needs"),
            (["--reference", "d", "--sweep-k", "5"], "different directory"),
            (["--reference", "./d/../d", "--sweep-cost", "0.5"], "different directory"),
        ]
        for extra, needle in cases:
            code, msg = self.usage(base + extra)
            self.assertEqual(code, 2, extra)
            self.assertIn(needle, msg, extra)
        floor = [x for x in base if x not in ("--truth-kind", "blocked")]
        for extra in (["--sweep-k", "5"], ["--sweep-cost", "0.5"], ["--sweep-k", "5", "--reference", "r"]):
            code, msg = self.usage(floor + extra)
            self.assertEqual(code, 2, extra)
            self.assertIn("--truth-kind", msg)
            code, msg = self.usage(floor + ["--truth-kind", "floor"] + extra)
            self.assertEqual(code, 2, extra)
        for extra in (["--sweep-k", "5"], ["--sweep-cost", "0.5"], ["--reference", "r", "--sweep-k", "5"]):
            code, msg = self.usage(["--smoke", *extra])
            self.assertEqual(code, 2, extra)
            self.assertIn("--smoke", msg)

    def test_reference_same_directory_via_symlink_is_rejected(self):
        # inject: compare the path strings instead of the resolved directories
        with tempfile.TemporaryDirectory() as t:
            real = Path(t) / "real"
            real.mkdir()
            (Path(t) / "link").symlink_to(real)
            code, msg = self.usage(["--phase-a", str(real), "--publish-every", "300", "--top-k", "5", "--out", "o.json",
                                    "--truth-kind", "blocked", "--sweep-k", "5", "--reference", str(Path(t) / "link")])
            self.assertEqual(code, 2)
            self.assertIn("different directory", msg)


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

"""S15B duration_spread: job reading, spread statistics, agreement measures, the verdict function and the s10-none smoke.

The smoke and read-only tests resolve fleet/data/s10-none and results/fleet/deadlock_s10-none-sb.json from this checkout,
else from the main checkout; they skip only when both lack them (CI has no data)."""
import hashlib
import io
import contextlib
import math
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "fleet", ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import duration_spread as ds  # noqa: E402
from fleet_analyser.parse import Message  # noqa: E402

try:
    import scipy.stats  # noqa: F401
    HAVE_SCIPY = True
except ImportError:
    HAVE_SCIPY = False


def main_checkout():
    env = os.environ.get("WR_MAIN_CHECKOUT")
    cands = [Path(env)] if env else []
    try:
        common = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                capture_output=True, text=True, check=True).stdout.strip()
        cands.append(Path(common).parent)
    except (subprocess.CalledProcessError, OSError):
        pass
    return cands


def find_file(*rel):
    for base in [ROOT, *main_checkout()]:
        p = base.joinpath(*rel)
        if p.exists():
            return p
    return None


def msg(serial, ts, order, x=0, y=0, driving=True, header=None):
    return Message(serial=serial, zone=serial.split("-")[0][1:], header_id=ts if header is None else header, ts=ts,
                   order_id=order, x=x, y=y, driving=driving, faulted=False, loaded=False, raw_len=1)


def jobs_of(pairs):
    """[(duration, dist)] -> job dicts as robot_jobs returns them."""
    return [dict(duration=d, dist=k, ended_to="idle", gap=False, start=0, end=d) for d, k in pairs]


class TestJobReading(unittest.TestCase):
    def robot(self):
        # A-01: first message already carries o1 (open_at_start); o2 ends into o3 (new order); o3 ends idle;
        # o5 holds a 70 s gap; o4 is still open at the end
        rows = [(0, "o1"), (5, "o1"), (10, ""), (15, "o2"), (20, "o2"), (25, "o3"), (30, "o3"), (35, ""),
                (40, "o5"), (110, "o5"), (115, ""), (120, "o4"), (125, "o4")]
        return [msg("Z0-01", ts, o) for ts, o in rows]

    def test_open_ends_excluded_and_counted_and_endings_tallied(self):
        jobs, t = ds.robot_jobs(self.robot())
        self.assertEqual((t["open_at_start"], t["open_at_end"]), (1, 1))
        self.assertEqual([j["duration"] for j in jobs], [10, 10, 75])  # o2: 15->25, o3: 25->35, o5: 40->115
        self.assertEqual([j["ended_to"] for j in jobs], ["new_order", "idle", "idle"])
        self.assertEqual([j["gap"] for j in jobs], [False, False, True])  # the gap job stays in
        tal = ds.job_tallies(jobs)
        self.assertEqual((tal["completed"], tal["ended_to_idle"], tal["ended_to_new_order"], tal["with_gap_over_60s"]),
                         (3, 2, 1, 1))

    def test_single_job_that_is_both_open_at_start_and_end_counts_once_as_open_at_start(self):
        jobs, t = ds.robot_jobs([msg("Z0-01", 0, "o1"), msg("Z0-01", 5, "o1")])
        self.assertEqual((jobs, t["open_at_start"], t["open_at_end"]), ([], 1, 0))

    def test_picker_with_an_order_id_is_excluded_and_dropped_messages_counted(self):
        agv = self.robot() + [msg("Z0-01", 125, "o4", header=999)]  # ts <= previous kept ts: dropped by kept_messages
        picker = [msg("Z0-10", 0, ""), msg("Z0-10", 10, "pk1"), msg("Z0-10", 20, "pk1"), msg("Z0-10", 30, "")]
        jobs, t = ds.zone_jobs(agv + picker, pickers={"Z0-10"})
        self.assertEqual(len(jobs), 3)
        self.assertEqual((t["n_agv"], t["dropped_by_kept_messages"]), (1, 1))
        jobs_all, _ = ds.zone_jobs(agv + picker, pickers=set())
        self.assertEqual(len(jobs_all), 4)  # the picker's job would count if it were not excluded by kind

    def test_waypoints_first_cell_stop_starts_and_last_cell(self):
        ms = [msg("Z0-01", 0, "o", 0, 0, True), msg("Z0-01", 5, "o", 3, 0, False), msg("Z0-01", 10, "o", 3, 0, False),
              msg("Z0-01", 15, "o", 3, 0, True), msg("Z0-01", 20, "o", 3, 4, False), msg("Z0-01", 25, "o", 3, 4, True)]
        # cells (0,0) (3,0) (3,4) (3,4): 3 + 4 = 7; consecutive duplicates collapse
        self.assertEqual(ds.waypoint_distance(ms), 7)
        self.assertEqual(ds.waypoint_distance([msg("Z0-01", 0, "o", 2, 2), msg("Z0-01", 5, "o", 2, 2)]), 0)


class TestStatistics(unittest.TestCase):
    def test_equal_mean_spread_ranks_higher_on_p95_median_buffer_index_and_cv(self):
        a = ds.zone_statistics(jobs_of([(120, 6)] * 10))
        b = ds.zone_statistics(jobs_of([(100, 6)] * 9 + [(300, 6)]))
        self.assertAlmostEqual(a["raw"]["mean_s"], b["raw"]["mean_s"], places=9)
        self.assertEqual(a["raw"]["p95_over_median"], 1.0)
        for k in ("p95_over_median", "buffer_index", "cv"):
            self.assertGreater(b["raw"][k], a["raw"][k], k)
        self.assertEqual((a["raw"]["buffer_index"], a["raw"]["cv"]), (0.0, 0.0))
        self.assertAlmostEqual(b["raw"]["p95_s"], 210.0)  # np.percentile linear: 100 + 0.55 * 200
        self.assertAlmostEqual(b["raw"]["cv"], 60.0 / 120.0)  # population sd of [100]*9 + [300] is 60, ddof 0

    def test_route_length_only_spread_raw_ratio_above_one_normalised_buffer_index_zero(self):
        dists = [2, 3, 4, 6, 8, 10, 12, 16]
        st = ds.zone_statistics(jobs_of([(ds.STEP_S * k, k) for k in dists]))  # constant speed: 1 cell per step
        self.assertGreater(st["raw"]["p95_over_median"], 1.0)
        self.assertLess(abs(st["normalised"]["buffer_index"]), 1e-12)
        self.assertLess(abs(st["normalised"]["cv"]), 1e-12)
        self.assertEqual(st["normalised"]["mean"], 1.0)

    def test_zero_distance_job_uses_one_step_of_free_flow(self):
        st = ds.zone_statistics(jobs_of([(10, 0)] * 5))
        self.assertEqual(st["normalised"]["mean"], 10 / ds.STEP_S)

    def test_fewer_than_five_jobs_gives_null_statistics_and_is_counted(self):
        st = ds.zone_statistics(jobs_of([(10, 1)] * 4))
        self.assertIsNone(st["raw"])
        self.assertIsNone(st["normalised"])
        self.assertTrue(st["null_reason"])
        zone = dict(jobs=dict(completed=4, open_at_start=0, open_at_end=0, ended_to_idle=4, ended_to_new_order=0,
                              with_gap_over_60s=0, raw_distance_zero=0), dropped_by_kept_messages=0, **st)
        ok = dict(zone, jobs=dict(zone["jobs"], completed=5), **ds.zone_statistics(jobs_of([(10, 1)] * 5)))
        counts = ds.run_counts({"0": zone, "1": ok})
        self.assertEqual((counts["zones"], counts["zones_below_min_jobs"], counts["completed"]), (2, 1, 9))
        self.assertIsNone(ds.stat_value(zone, "p95_over_median"))
        self.assertIsNone(ds.stat_value(zone, "cv_norm"))


class TestAgreement(unittest.TestCase):
    def test_spearman_on_three_zones_matches_the_rank_formula(self):
        x, y = [1.0, 2.0, 3.0], [1.0, 3.0, 2.0]
        n = 3
        d2 = sum((rx - ry) ** 2 for rx, ry in zip([1, 2, 3], [1, 3, 2]))
        self.assertAlmostEqual(ds.spearman(x, y), 1 - 6 * d2 / (n * (n * n - 1)), places=12)
        self.assertAlmostEqual(ds.spearman(x, y), 0.5, places=12)
        self.assertAlmostEqual(ds.kendall_tau_b(x, y), 1 / 3, places=12)  # 2 concordant, 1 discordant, no ties

    def test_ties_get_average_ranks(self):
        self.assertEqual(list(ds.average_ranks([1, 2, 2, 3])), [1.0, 2.5, 2.5, 4.0])
        self.assertEqual(list(ds.average_ranks([5, 5, 5])), [2.0, 2.0, 2.0])
        self.assertEqual(list(ds.average_ranks([3, 1, 2, 1])), [4.0, 1.5, 3.0, 1.5])
        # Pearson on average ranks: [1,2,2,3] vs [1,2,3,4] by hand
        rx, ry = [1, 2.5, 2.5, 4], [1, 2, 3, 4]
        mx = my = 2.5
        num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
        den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
        self.assertAlmostEqual(ds.spearman([1, 2, 2, 3], [1, 2, 3, 4]), num / den, places=12)

    def test_tau_b_with_ties_by_hand(self):
        # x = [1,2,2,3], y = [1,2,3,4]: pairs 6, tied in x 1 -> C = 5, D = 0; n0 = 6, n1 = 1, n2 = 0
        self.assertAlmostEqual(ds.kendall_tau_b([1, 2, 2, 3], [1, 2, 3, 4]), 5 / math.sqrt(5 * 6), places=12)

    @unittest.skipUnless(HAVE_SCIPY, "scipy absent")
    def test_tau_b_equals_scipy(self):
        from scipy.stats import kendalltau
        x = [3, 1, 4, 1, 5, 9, 2, 6, 5, 3]
        y = [2, 7, 1, 8, 2, 8, 1, 8, 2, 8]
        self.assertAlmostEqual(ds.kendall_tau_b(x, y), float(kendalltau(x, y, variant="b").statistic), places=12)
        self.assertEqual(ds.kendall_p(x, y), float(kendalltau(x, y, variant="b", method="auto").pvalue))

    def test_top3_tie_break_value_desc_then_zone_id_asc_and_boundary_ties(self):
        col = {"0": 5.0, "1": 9.0, "2": 5.0, "3": 5.0, "10": 5.0, "4": 1.0}
        top, ties = ds.top_k(col)
        self.assertEqual(top, ["1", "0", "2"])
        self.assertEqual(ties, 4)  # four zones share 5.0, straddling the 3rd/4th boundary
        self.assertEqual(ds.top_k({"0": 3.0, "1": 2.0, "2": 1.0, "3": 0.0})[1], 0)

    @mock.patch.object(ds, "kendall_p", lambda x, y: 0.5)  # the p-value is scipy's; not under test here
    def test_pair_agreement_decided_and_chance(self):
        a = {str(i): float(i) for i in range(10)}
        b = {str(i): float(i) for i in range(10)}
        r = ds.pair_agreement(a, b)
        self.assertTrue(r["decided"])
        self.assertAlmostEqual(r["rho"], 1.0)
        self.assertEqual((r["top3_overlap"], r["top3_fraction"], r["top3_chance"]), (3, 1.0, 0.9))

    def test_constant_column_and_too_few_zones_are_undecided(self):
        r = ds.pair_agreement({"0": 1.0, "1": 1.0, "2": 1.0}, {"0": 1.0, "1": 2.0, "2": 3.0})
        self.assertFalse(r["decided"])
        self.assertEqual((r["rho"], r["tau_b"], r["tau_b_p"], r["top3_fraction"], r["reason"]),
                         (None, None, None, None, "constant_column"))
        r = ds.pair_agreement({"0": 1.0, "1": 2.0}, {"0": 1.0, "1": 2.0})
        self.assertEqual((r["decided"], r["reason"], r["n"]), (False, "fewer_than_3_zones", 2))
        r = ds.pair_agreement({"0": 1.0, "1": 2.0, "2": None, "3": 4.0}, {"0": 1.0, "1": 2.0, "2": 3.0, "3": None})
        self.assertEqual((r["n"], r["decided"]), (2, False))  # null zones dropped pairwise

    def test_run_agreement_counts_undecided_and_medians_are_null_without_decided_runs(self):
        zones = {"0": dict(raw=None, normalised=None, blocked_s_per_robot_hour=1.0, truth_stuck_s_per_robot_hour=2.0)}
        agr = ds.run_agreement(zones)
        self.assertEqual(set(agr), set(ds.pair_keys()))
        self.assertTrue(all(not v["decided"] for v in agr.values()))
        med = ds.pair_medians({"r": agr}, "p95_over_median|truth")
        self.assertEqual((med["n_decided"], med["median_rho"], med["median_tau_b"], med["median_top3_fraction"]),
                         (0, None, None, None))

    @mock.patch.object(ds, "kendall_p", lambda x, y: 0.5)
    def test_median_over_decided_runs(self):
        up = {str(i): float(i) for i in range(5)}
        down = {str(i): float(-i) for i in range(5)}
        per_run = {"a": {"k": ds.pair_agreement(up, up)}, "b": {"k": ds.pair_agreement(up, down)},
                   "c": {"k": ds.pair_agreement(up, up)}, "d": {"k": ds.pair_agreement(up, {"0": 1.0, "1": 1.0})}}
        med = ds.pair_medians(per_run, "k")
        self.assertEqual((med["n_decided"], med["n_runs"]), (3, 4))
        self.assertAlmostEqual(med["median_rho"], 1.0, places=12)


def pr(rho=None, top3=None):
    return dict(rho=rho, top3_fraction=top3)


def runs_with(n, **pairs):
    """n runs, each carrying the same {pair key: pr(...)}."""
    return {f"r{i}": dict(pairs) for i in range(n)}


class TestVerdict(unittest.TestCase):
    def test_commodity_via_the_blocking_branch(self):
        per = runs_with(5, **{"p95_over_median|blocking": pr(0.7, 2 / 3), "mean_s|blocking": pr(0.1, 0.0),
                              "blocking|truth": pr(0.9)})
        v = ds.verdict(per)
        self.assertEqual(v["verdict"], "commodity")
        self.assertTrue(v["conditions"]["p95_over_median"]["blocking_branch_holds"])
        self.assertFalse(v["conditions"]["mean_s"]["blocking_branch_holds"])
        self.assertIn("Commodity if", v["s15b_line"])

    def test_blocking_branch_needs_both_rho_and_top3(self):
        per = runs_with(5, **{"p95_over_median|blocking": pr(0.9, 1 / 3), "mean_s|blocking": pr(0.69, 1.0)})
        self.assertEqual(ds.verdict(per)["verdict"], "mixed")

    def test_commodity_via_the_truth_branch_needs_three_runs_with_both_non_null(self):
        def run(s_truth, b_truth):
            return {"mean_s|blocking": pr(0.1, 0.0), "p95_over_median|blocking": pr(0.1, 0.0),
                    "p95_over_median|truth": pr(s_truth), "blocking|truth": pr(b_truth)}
        per = {"r0": run(0.5, 0.5), "r1": run(0.6, 0.4), "r2": run(0.9, 0.1), "r3": run(0.1, 0.9), "r4": run(None, 0.1)}
        v = ds.verdict(per)
        self.assertEqual(v["verdict"], "commodity")
        self.assertEqual(v["conditions"]["p95_over_median"]["runs_stat_truth_ge_blocking_truth"], 3)
        per["r2"] = run(0.0, 0.1)
        self.assertEqual(ds.verdict(per)["verdict"], "mixed")  # only 2 runs now (equality counts)

    def test_supports(self):
        def run(strict):
            s, b = (0.2, 0.8) if strict else (0.9, 0.1)
            return {"p95_over_median|blocking": pr(0.1, 0.0), "mean_s|blocking": pr(0.3, 0.0),
                    "p95_over_median|truth": pr(s), "mean_s|truth": pr(s), "blocking|truth": pr(b)}
        per = {f"r{i}": run(i < 4) for i in range(5)}
        # the truth branch would need rho(S,truth) >= rho(blocking,truth) in 3 runs: only 1 run has it
        v = ds.verdict(per)
        self.assertEqual((v["verdict"], v["runs_blocking_beats_both_on_truth"]), ("supports", 4))

    def test_mixed_when_blocking_beats_in_only_three_runs(self):
        def run(strict):
            s, b = (0.2, 0.8) if strict else (0.9, 0.1)
            return {"p95_over_median|blocking": pr(0.1, 0.0), "mean_s|blocking": pr(0.3, 0.0),
                    "p95_over_median|truth": pr(s), "mean_s|truth": pr(s), "blocking|truth": pr(b)}
        per = {f"r{i}": run(i < 3) for i in range(5)}
        self.assertEqual(ds.verdict(per)["verdict"], "mixed")

    def test_all_undecided_is_mixed_with_null_medians(self):
        per = runs_with(5, **{k: pr() for k in ds.pair_keys()})
        v = ds.verdict(per)
        self.assertEqual(v["verdict"], "mixed")
        self.assertIsNone(v["conditions"]["mean_s"]["median_rho_vs_blocking"])
        self.assertFalse(v["both_median_rho_vs_blocking_below_0_4"])  # a null median satisfies neither bound

    def test_the_quoted_line_is_part_8_section_3(self):
        self.assertTrue(ds.S15B_LINE.startswith("**S15B.** Commodity if, for either decisive statistic"))
        self.assertTrue(ds.S15B_LINE.endswith("All thresholds are ours, set here before the run."))
        texts = [(b / "docs" / "LITERATURE.md").read_text() for b in [ROOT, *main_checkout()]
                 if (b / "docs" / "LITERATURE.md").is_file()]
        texts = [t for t in texts if "## Part 8" in t]
        if not texts:
            self.skipTest("LITERATURE Part 8 absent in this checkout and the main one")
        text = " ".join(texts[0].split())
        self.assertIn(" ".join(ds.S15B_LINE.split()), text)


class TestCli(unittest.TestCase):
    def test_missing_scipy_exits_non_zero_before_any_work(self):
        with mock.patch.dict(sys.modules, {"scipy": None, "scipy.stats": None}):
            with self.assertRaises(SystemExit) as cm:
                ds.main(["--smoke", "--out", "/nonexistent/x.json"])
        self.assertIsInstance(cm.exception.code, str)
        self.assertIn("scipy", cm.exception.code)

    def test_run_spec_parsing(self):
        r = ds.parse_runs("a=/x,b=/y", ["c:/z"], ["b=/dl.json"])
        self.assertEqual(list(r), ["a", "b", "c"])
        self.assertEqual((r["b"]["dir"], r["b"]["deadlock"]), ("/y", "/dl.json"))
        self.assertTrue(r["c"]["deadlock"].endswith("results/fleet/deadlock_c-sb.json"))
        self.assertEqual(list(ds.parse_runs(None, None, None)), list(ds.DEFAULT_RUNS))


class TestSmoke(unittest.TestCase):
    def setUp(self):
        self.data = find_file("fleet", "data", "s10-none")
        self.deadlock = find_file("results", "fleet", "deadlock_s10-none-sb.json")
        if self.data is None or self.deadlock is None or not (self.data / "zone0-000.jsonl.gz").is_file():
            self.skipTest("s10-none data absent in this checkout and the main one")
        if not HAVE_SCIPY:  # one zone: every pair is undecided and scipy is never called; only the start check differs
            patcher = mock.patch.object(ds, "require_scipy", lambda: None)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_smoke(self, out):
        argv = ["--run", f"s10-none:{self.data}", "--deadlock", f"s10-none={self.deadlock}", "--out", str(out),
                "--smoke", "--workers", "1"]
        t0 = time.time()
        with contextlib.redirect_stdout(io.StringIO()):
            rc = ds.main(argv)
        self.assertEqual(rc, 0)
        return time.time() - t0

    @staticmethod
    def sha_tree(root):
        out = {}
        for p in sorted(Path(root).rglob("*")):
            if p.is_file():
                out[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
        return out

    def test_smoke_is_fast_and_byte_identical_over_two_runs(self):
        with tempfile.TemporaryDirectory() as d:
            e1 = self.run_smoke(Path(d) / "a.json")
            e2 = self.run_smoke(Path(d) / "b.json")
            self.assertLess(e1, 120)
            self.assertLess(e2, 120)
            a, b = (Path(d) / "a.json").read_bytes(), (Path(d) / "b.json").read_bytes()
            self.assertEqual(a, b)
            import json
            out = json.loads(a)
            self.assertTrue(out["smoke"])
            zones = out["runs"]["s10-none"]["zones"]
            self.assertEqual(list(zones), ["0"])
            z = zones["0"]
            self.assertGreater(z["jobs"]["completed"], 0)
            self.assertEqual(z["robot_hours"], json.loads(self.deadlock.read_text())["zones"]["0"]["robot_hours"])
            self.assertEqual(out["runs"]["s10-none"]["deadlock"]["sha256"],
                             hashlib.sha256(self.deadlock.read_bytes()).hexdigest())
            self.assertEqual(out["runs"]["s10-none"]["undecided_pairs"], len(ds.pair_keys()))  # one zone: all undecided
            self.assertEqual(out["verdict"]["verdict"], "mixed")

    def test_smoke_leaves_the_run_directory_and_the_deadlock_file_unchanged(self):
        before = self.sha_tree(self.data)
        before_dl = hashlib.sha256(self.deadlock.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as d:
            self.run_smoke(Path(d) / "a.json")
        self.assertEqual(self.sha_tree(self.data), before)
        self.assertEqual(hashlib.sha256(self.deadlock.read_bytes()).hexdigest(), before_dl)
        self.assertTrue(before)


if __name__ == "__main__":
    unittest.main()

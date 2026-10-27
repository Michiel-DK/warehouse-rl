"""Tests for fleet/fastmap.py (S10I). T1-T3 drive the pure functions with synthetic stalls; T4-T7 run the CLI and
time_to_detect on a tiny emitted phase-A pair (2 zones x 150 steps, built once per class by the real emit / ingest /
costmap CLIs, seconds); T10 runs fleet/fastmap_smoke.py on the real untracked data (skipped when it is absent). T8-T9
live in test_time_to_detect.py. Each case names its red demonstration in an `# inject:` comment."""
import contextlib
import hashlib
import io
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "fleet", ROOT / "src", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import fastmap  # noqa: E402
import costmap as costmap_mod  # noqa: E402
import fastmap_smoke  # noqa: E402
import time_to_detect as ttd  # noqa: E402
from fleet_analyser.store import JsonlStore  # noqa: E402

B, N, K_OFF, H = 60, 30, 1.0, 3.0
REAL_DATA = Path(__file__).resolve().parents[1] / "data"
ENV = "tarware-small-4agvs-2pickers-globalobs-v1"
BLIND = '{"blocked_cell": {"rate_per_hour": 8.0, "duration": [60, 240], "known": false}}'
RUN = "t4run"


def stall(zone, cell, start, end):
    return dict(zone=zone, cell=cell, start=start, end=end)


def background(first_bins, cells, zone="0"):
    """One 5 s stall per bin per cell."""
    return [stall(zone, c, j * B + 10, j * B + 15) for c in cells for j in range(first_bins)]


def run_detect(stalls, n_bins, rule="active"):
    return fastmap.detect(stalls, 0, n_bins * B, B, rule, N, K_OFF, H)


class TestPureFunctions(unittest.TestCase):
    def test_jump_flagged_and_released(self):
        # inject: count a flagged bin into the baseline, release at H instead of H/2, or drop the S clamp at 0
        jump_start = 20 * B
        bg = background(60, ["1,1", "2,2", "3,3", "4,4"])
        # burst cell: one stall per bin like the background, except 6 active stalls in bin 20 only (S jumps by 6 - 2 = 4 > H)
        burst = [stall("0", "9,9", j * B + 10, j * B + 15) for j in range(60) if j != 20]
        burst += [stall("0", "9,9", 20 * B + 5 + 5 * i, 20 * B + 10 + 5 * i) for i in range(6)]
        seq = run_detect(bg + burst, 60)[("0", "9,9")]
        flagged = [j for j, (_, on, _) in enumerate(seq) if on]
        first, last = flagged[0], flagged[-1]
        delay = (first + 1) * B - jump_start
        release_lag = (last + 1) - 20  # bins after the jump's last bin (bin 20) until the first unflagged bin
        print(f"T1 detect delay {delay} s, release lag {release_lag} bins")
        self.assertLessEqual(delay, 3 * B)
        self.assertLessEqual(release_lag, 5)
        self.assertEqual(first, 20)
        # the baseline did not absorb the jump: mu in every bin after it is the pre-jump mean (1 stall per bin)
        self.assertTrue(all(seq[j][2] == 1.0 for j in range(21, 30)))
        for cell in ("1,1", "2,2", "3,3", "4,4"):  # steady background cells are never flagged
            self.assertFalse(any(on for _, on, _ in run_detect(bg, 60)[("0", cell)]))

    def test_long_jump_held_through_the_jump_and_baseline_frozen(self):
        # inject: let flagged bins into the baseline (mu would climb towards 4 during the jump)
        # Brief T1 wanted 4 active stalls per bin for 10 bins AND a release within 5 bins; with k = 1 and S falling by at
        # most mu + k per bin that cannot hold (S peaks near 18, release needs S < 1.5 at -1 per bin), so the long jump
        # is asserted on what does hold: flagged within 3 bins, held for the whole jump, mu frozen, released after it.
        stalls = background(60, ["1,1"])
        stalls += [stall("0", "9,9", j * B + 10, j * B + 15) for j in range(60) if not 20 <= j < 30]
        stalls += [stall("0", "9,9", j * B + 5 + 5 * i, j * B + 10 + 5 * i) for j in range(20, 30) for i in range(4)]
        seq = run_detect(stalls, 60)[("0", "9,9")]
        flagged = [j for j, (_, on, _) in enumerate(seq) if on]
        self.assertLessEqual((flagged[0] + 1) * B - 20 * B, 3 * B)
        self.assertTrue(all(seq[j][1] for j in range(flagged[0], 30)))
        self.assertTrue(all(seq[j][2] < 1.2 for j in range(22, 30)))
        self.assertFalse(seq[-1][1])
        print(f"T1b long jump: flagged bin {flagged[0]}, released after {flagged[-1] + 1 - 29} bins past the jump")

    def test_constant_cell_never_flagged(self):
        # inject: flag at S >= H instead of S > H, or start the baseline at a fixed 0 instead of the previous bins
        for c in (0, 1, 3):
            seq = fastmap.cusum([c] * 60, N, K_OFF, H)
            self.assertFalse(any(on for _, on, _ in seq), c)
            stalls = [stall("0", "5,5", j * B + 10 + 5 * i, j * B + 15 + 5 * i) for j in range(60) for i in range(c)]
            self.assertFalse(any(on for seq in run_detect(stalls, 60).values() for _, on, _ in seq), c)

    def test_active_vs_end_rule(self):
        # inject: swap the rules, or count active stalls only in the bin that holds their start
        s = [stall("0", "1,1", 2 * B, 10 * B)]  # one stall from the start of bin 2 to the end of bin 9
        act = fastmap.bin_counts(s, 0, 12 * B, B, "active")[("0", "1,1")]
        end = fastmap.bin_counts(s, 0, 12 * B, B, "end")[("0", "1,1")]
        self.assertEqual(act, [0, 0] + [1] * 8 + [0, 0])
        self.assertEqual(end, [0] * 9 + [1] + [0, 0])
        self.assertEqual(sum(fastmap.bin_counts(s, 0, 12 * B, B, "end")[("0", "1,1")]), 1)
        with self.assertRaises(ValueError):
            fastmap.bin_counts(s, 0, 12 * B, B, "mid")

    def test_hysteresis_holds_between_half_h_and_h(self):
        # inject: release as soon as S <= H
        seq = fastmap.cusum([0, 0, 5, 0, 0, 0, 0, 0], N, 1.0, 3.0)
        self.assertEqual([on for _, on, _ in seq], [False, False, True, True, True, False, False, False])
        self.assertEqual([round(sc, 6) for sc, _, _ in seq][:6], [0, 0, 4, 3, 2, 1])


class Built(unittest.TestCase):
    """Two tiny emitted phase-A dirs: `blind` (blocked_cell known:false) and `none` (undisturbed), each ingested as run
    t4run with a costmap forecast set on the 60 s grid already in its store."""
    tmp = None

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="fastmap-test-"))
        for name, seed, dis in (("blind", 13, BLIND), ("none", 21, "{}")):
            d = cls.tmp / name
            extra = ["--disturb", dis] if dis else []
            cls.sh("emit.py", "--zones", 2, "--steps", 150, "--env", ENV, "--seed-base", seed, *extra, "--speed", 0,
                   "--workers", 2, "--dir", d)
            cls.sh("ingest.py", "--source", "file", "--glob", d / "*.jsonl.gz", "--run", RUN, "--store",
                   f"jsonl:{d / 'store'}", "--once")
            cls.sh("costmap.py", "--glob", d / "*.jsonl.gz", "--run", RUN, "--store", f"jsonl:{d / 'store'}",
                   "--publish-every", 60, "--out", d / "cm.json")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @staticmethod
    def sh(script, *args):
        r = subprocess.run([sys.executable, str(ROOT / "fleet" / script), *map(str, args)], capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(f"{script}: {r.stderr[-800:]}")

    def fm(self, d, out=None, copy=None, *extra):
        out = out or d / "fm.json"
        copy = copy or d / "store-fast"
        argv = ["--glob", str(d / "*.jsonl.gz"), "--run", RUN, "--store", f"jsonl:{copy}", "--out", str(out),
                "--k", "0", "--h", "1", *extra]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = fastmap.main(argv)
        return code, buf.getvalue()

    @staticmethod
    def store_hashes(d):
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((d / "store").iterdir())}

    @staticmethod
    def span(d):
        """(first_ts, end_ts) of the zone files, the way time_to_detect reads them."""
        _, first, end = ttd.read_span(str(d / "*.jsonl.gz"))
        return first, end

    @staticmethod
    def rows(copy):
        st = JsonlStore(copy)
        try:
            return st.select("decisions", {"kind": "hotspot_forecast", "run": RUN})
        finally:
            st.close()


class TestCli(Built):
    def test_cli_writes_only_copy_and_strips_costmap_forecasts(self):
        # inject: skip reset_forecasts (the map's forecasts at the 60 s grid stay in the copy), or write into SRC
        d = self.tmp / "blind"
        before = self.store_hashes(d)
        old = self.rows(d / "store")
        self.assertTrue(old and all("detector" not in json.loads(r["claim"]) for r in old))  # the map's own forecasts
        code, text = self.fm(d)
        self.assertEqual(code, 0)
        self.assertEqual(self.store_hashes(d), before)
        rows = self.rows(d / "store-fast")
        self.assertTrue(rows)
        self.assertTrue(all(json.loads(r["claim"])["detector"] == "cusum" for r in rows))
        claim = json.loads(rows[0]["claim"])
        self.assertEqual(set(claim), {"detector", "score", "rank", "top_k", "horizon_s", "bin_s", "k", "h",
                                      "baseline_bins", "count", "exclude_occupied", "window_hours", "half_life_h"})
        self.assertEqual((claim["window_hours"], claim["half_life_h"]), (B * N / 3600, None))
        doc = json.loads((d / "fm.json").read_text())
        self.assertEqual(set(doc), {"schema_version", "run", "params", "first_ts", "end_ts", "n_bins", "store_hash_before",
                                    "store_hash_after", "publishes"})
        self.assertEqual(doc["store_hash_before"], doc["store_hash_after"])
        self.assertEqual(set(doc["publishes"][-1]), {"published_at", "t_s", "flagged"})
        self.assertIn("fastmap t4run:", text)

    def test_refuses_original_store(self):
        # inject: drop the refusal of a directory named store, or of the original store path
        d = self.tmp / "blind"
        before = self.store_hashes(d)
        for target in (d / "store", self.tmp / "elsewhere" / "store", d / "x" / ".." / "store"):
            err = io.StringIO()
            with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as cm:
                self.fm(d, copy=target)
            self.assertEqual(cm.exception.code, 2, target)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            fastmap.main(["--glob", str(d / "*.jsonl.gz"), "--store", "clickhouse://h/db", "--out", str(d / "o.json")])
        self.assertEqual(cm.exception.code, 2)
        self.assertEqual(self.store_hashes(d), before)

    def tree(self):
        return {str(p.relative_to(self.tmp)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(self.tmp.rglob("*")) if p.is_file()}

    def test_refuses_ancestor_and_run_dir(self):
        # inject: compare names / equality only (the pass-1 guard), or run the rmtree before the check
        d = self.tmp / "blind"
        (d / "store" / "sub").mkdir()  # a subdirectory of the original store (removed again: fixtures are shared)
        self.addCleanup((d / "store" / "sub").rmdir)
        (self.tmp / "other").mkdir(exist_ok=True)
        (self.tmp / "other" / "decisions.jsonl").write_text("{}\n")  # looks like a copy but sits under the temp tree
        (d / "notacopy").mkdir()
        self.addCleanup(shutil.rmtree, d / "notacopy")
        (d / "notacopy" / "keep.txt").write_text("x")  # an existing directory that is not a previous fastmap copy
        targets = (d, self.tmp, d / "store" / "sub", d / "store", d / ".." / "blind", d / "x" / ".." / ".." / "blind",
                   d / "notacopy")
        before = self.tree()
        self.assertTrue(any(k.endswith(".jsonl.gz") for k in before) and any("store/" in k for k in before))
        for target in targets:
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
                self.fm(d, copy=target)
            self.assertEqual(cm.exception.code, 2, target)
            self.assertEqual(self.tree(), before, target)
            with self.assertRaises(ValueError, msg=str(target)):
                fastmap.run_fastmap(str(d / "*.jsonl.gz"), RUN, target, str(d / "o.json"))
            self.assertEqual(self.tree(), before, target)
        # a leftover fastmap copy is replaced
        code, _ = self.fm(d, copy=d / "store-again")
        code, _ = self.fm(d, copy=d / "store-again")
        self.assertEqual(code, 0)

    def test_deterministic(self):
        # inject: iterate a set or dict in insertion-unstable order when ranking, or stamp wall time into --out
        d = self.tmp / "blind"
        self.fm(d, d / "a.json", d / "store-a")
        self.fm(d, d / "b.json", d / "store-b")
        self.assertEqual((d / "a.json").read_bytes(), (d / "b.json").read_bytes())

        def strip(copy):
            return [{k: v for k, v in r.items() if k != "recorded_at"} for r in self.rows(copy)]
        self.assertEqual(strip(d / "store-a"), strip(d / "store-b"))
        self.assertTrue(strip(d / "store-a"))

    def test_decision_rows_read_by_time_to_detect(self):
        # inject: leave window_hours / half_life_h out of the claim (select_forecasts raises), or call the rerun
        blind, none = self.tmp / "blind", self.tmp / "none"
        self.fm(blind)
        self.fm(none)
        calls = []

        def spy(*a, **k):
            calls.append((a, k))
        out = self.tmp / "ttd.json"
        buf, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            code = ttd.main(["--phase-a", str(blind), "--truth-kind", "blocked", "--publish-every", "60", "--top-k", "20",
                             "--sweep-k", "20", "--reference", str(none), "--store-suffix", "fast", "--out", str(out)],
                            rerun=spy)
        self.assertEqual(code, 0, err.getvalue())
        self.assertEqual(calls, [])
        doc = json.loads(out.read_text())
        self.assertIn("20", doc["by_k"])
        self.assertEqual(doc["meta"]["store_suffix"], "fast")
        self.assertEqual(doc["meta"]["store_mode"], {str(blind): "prebuilt", str(none): "prebuilt"})
        self.assertTrue((blind / "store-fast").exists() and (none / "store-fast").exists())
        self.assertEqual(doc["amoc"]["k"][0]["K"], 20)
        # the cusum rows detect on the fixture (known:false blocked windows -> stalls -> flags), not just parse
        self.assertGreaterEqual(doc["by_k"]["20"]["summary"]["n_detected"], 1)
        self.assertGreaterEqual(doc["amoc"]["k"][0]["n_detected"], 1)
        # FA/h in the fa_per_hour_reference unit, recomputed from the reference store copy: flags (rank <= K) at publish
        # times / (n_zones * sim_hours)
        truth = json.loads((none / "truth.json").read_text())
        pubs = set(costmap_mod.publish_times(*self.span(none), 60))
        flags = sum(1 for r in self.rows(none / "store-fast")
                    if r["decided_at"] in pubs and json.loads(r["claim"])["rank"] <= 20)
        hours = truth["steps"] * truth["step_seconds"] / 3600
        expect = flags / (len(truth["zones"]) * hours)
        # the 150-step undisturbed fixture has no stall, so flags == 0 here (a zero-row prebuilt reference); the nonzero
        # recomputation is pinned on hand-built cusum rows in test_time_to_detect.test_prebuilt_reference_fa_recomputed
        self.assertAlmostEqual(doc["amoc"]["k"][0]["fa_per_hour_reference"], expect, places=9)


@unittest.skipUnless((REAL_DATA / "s10c-blind").is_dir() and (REAL_DATA / "s10-none").is_dir(),
                     "the untracked fleet/data/{s10c-blind,s10-none} runs are absent")
class TestSmokeOnRealData(unittest.TestCase):
    def test_smoke_on_real_data(self):
        # inject: drop an arm from fastmap_smoke.main, or let it copy more than the temp dir needs (elapsed > 180 s)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = fastmap_smoke.main(["--data-root", str(REAL_DATA)])
        self.assertEqual(code, 0)
        text = buf.getvalue()
        rows = {}
        for arm in ("a", "b", "c", "c-end"):
            m = re.search(rf"(?m)^ROW {re.escape(arm)}: detected (\d+)/(\d+), median first-detect (\S+) s, FA/h ref (\S+)", text)
            self.assertIsNotNone(m, f"arm {arm}\n{text}")
            self.assertEqual(m.group(2), "50")
            det, med, fa = int(m.group(1)), m.group(3), float(m.group(4))
            self.assertTrue(math.isfinite(fa) and fa >= 0, (arm, fa))
            self.assertLessEqual(det, 50)
            self.assertEqual(med == "n/a", det == 0, (arm, det, med))  # median is null iff nothing was detected
            rows[arm] = (det, None if med == "n/a" else float(med), fa)
        # (a) is read from the tracked results/fleet/amoc_blind.json, so exact on every platform
        e = next(x for x in json.loads((ROOT / "results/fleet/amoc_blind.json").read_text())["amoc"]["k"] if x["K"] == 20)
        self.assertEqual(rows["a"][:2], (e["n_detected"], e["median_delay_s"]))
        self.assertEqual((rows["a"][0], rows["a"][1], round(rows["a"][2], 2)), (6, 295.0, 177.84))
        self.assertAlmostEqual(rows["a"][2], e["fa_per_hour_reference"], places=3)
        # (b) and (c) are the pass-1 measured values, deterministic on this data on macOS; pinned there only because the
        # pyastar2d A* tie-break differs on Linux (the bounds above still hold everywhere)
        if sys.platform == "darwin":
            got = {arm: (rows[arm][0], rows[arm][1], round(rows[arm][2], 2)) for arm in ("b", "c")}
            self.assertEqual(got, {"b": (6, 402.5, 451.87), "c": (2, 525.0, 0.0)})
        elapsed = float(re.search(r"elapsed ([0-9.]+) s", text).group(1))
        self.assertLess(elapsed, 180)


if __name__ == "__main__":
    unittest.main()

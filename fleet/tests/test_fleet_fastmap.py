"""Tests for fleet/fastmap.py (S10I). T1-T3 drive the pure functions with synthetic stalls; T4-T7 run the CLI and
time_to_detect on a tiny emitted phase-A pair (2 zones x 150 steps, built once per class by the real emit / ingest /
costmap CLIs, seconds); T10 runs fleet/fastmap_smoke.py on the real untracked data (skipped when it is absent). T8-T9
live in test_time_to_detect.py. Each case names its red demonstration in an `# inject:` comment."""
import contextlib
import hashlib
import io
import json
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
import fastmap_smoke  # noqa: E402
import time_to_detect as ttd  # noqa: E402
from fleet_analyser.store import JsonlStore  # noqa: E402

B, N, K_OFF, H = 60, 30, 1.0, 3.0
REAL_DATA = Path("/Users/michieldekoninck/code/Michiel-DK/warehouse-rl/fleet/data")
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
        for arm in ("a", "b", "c", "c-end"):
            m = re.search(rf"(?m)^ROW {re.escape(arm)}: detected (\d+)/(\d+), median first-detect (\S+) s, FA/h ref (\S+)", text)
            self.assertIsNotNone(m, f"arm {arm}\n{text}")
            self.assertEqual(m.group(2), "50")
        elapsed = float(re.search(r"elapsed ([0-9.]+) s", text).group(1))
        self.assertLess(elapsed, 180)


if __name__ == "__main__":
    unittest.main()

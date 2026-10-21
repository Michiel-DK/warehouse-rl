"""Tests for fleet/absencemap.py (S14B). T1-T3 and T5-T7 run on small synthetic zone files written per test class (a 10 x 10
grid walked by 12 robots; a store directory holding an empty decisions.jsonl); T4 runs `--smoke` on the real untracked data
(skipped when it is absent). T8-T9 live in test_time_to_detect.py. Each case names its red demonstration in an `# inject:`
comment."""
import contextlib
import gzip
import hashlib
import io
import json
import math
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "fleet", ROOT / "src", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import absencemap  # noqa: E402
from fleet_analyser import hotspot  # noqa: E402
from fleet_analyser.parse import iso  # noqa: E402

REAL_DATA = Path("/Users/michieldekoninck/code/Michiel-DK/warehouse-rl/fleet/data")
T0 = 1767225600  # 2026-01-01T00:00:00Z
STEP = 5
B = 60
ALPHA, MIN_EXP = 1e-3, 10
CLAIM_KEYS = {"detector", "score", "rank", "top_k", "horizon_s", "bin_s", "alpha", "min_expected", "rate", "gap_s",
              "expected_passes", "window_hours", "half_life_h"}


def write_run(root, name, positions):
    """<root>/<name>/zone0-000.jsonl.gz from positions {serial: [(step, x, y), ...]} plus store/decisions.jsonl (empty).
    One message per listed step; headerId counts per robot from 0. Returns the run directory."""
    d = Path(root) / name
    (d / "store").mkdir(parents=True)
    (d / "store" / "decisions.jsonl").write_text("")
    lines = []
    for serial, seq in sorted(positions.items()):
        for hid, (step, x, y) in enumerate(seq):
            lines.append((T0 + step * STEP, serial, hid, json.dumps(
                {"schema_version": "fleet-state/2", "headerId": hid, "timestamp": iso(T0 + step * STEP),
                 "manufacturer": "sim", "serialNumber": serial, "orderId": "", "agvPosition": {"x": x, "y": y},
                 "driving": True, "errors": [], "loads": []})))
    lines.sort(key=lambda r: (r[0], r[1]))
    with gzip.open(d / "zone0-000.jsonl.gz", "wt", encoding="utf-8") as f:
        for _, _, _, ln in lines:
            f.write(ln + "\n")
    return d


# T1 fixture: 12 robots walk the cells 0..99 of a 10 x 10 grid in index order, one cell per step, robot i offset by 8
# cells. Every cell is crossed by every robot once per 100 steps (500 s): 12 passes per 500 s, gaps <= 40 s. Cell 44 =
# (4, 4) is skipped (the robot stays on 43) for steps SKIP_FROM <= s < SKIP_TO.
N_STEPS, SKIP_FROM, SKIP_TO = 800, 240, 600
CELL = (4, 4)


def grid_positions():
    pos = {f"Z0-{i:02d}": [] for i in range(12)}
    for i, serial in enumerate(pos):
        for s in range(N_STEPS):
            idx = (i * 8 + s) % 100
            if idx == 44 and SKIP_FROM <= s < SKIP_TO:
                idx = 43
            pos[serial].append((s, idx % 10, idx // 10))
    return pos


def cell_pass_times(positions, x, y):
    """Fixture-side pass times of one cell: a robot's step onto it from another cell (or its first step)."""
    out = []
    for seq in positions.values():
        prev = None
        for step, px, py in seq:
            if (px, py) == (x, y) and prev != (x, y):
                out.append(T0 + step * STEP)
            prev = (px, py)
    return sorted(out)


def reference_first_flag_bin(passes, first_ts, n_bins, alpha=ALPHA, min_expected=MIN_EXP):
    """Independent per-bin-end stepping for a cell that has not been flagged yet: r = passes so far / elapsed, flagged when
    eligible and exp(-r * gap) < alpha. Returns the bin index (0-based) or None."""
    for j in range(n_bins):
        t = first_ts + (j + 1) * B
        made = [p for p in passes if p <= t]
        if len(made) < min_expected:
            continue
        r = len(made) / (t - first_ts)
        if math.exp(-r * (t - made[-1])) < alpha:
            return j
    return None


class TestGridStream(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.positions = grid_positions()
        cls.run_dir = write_run(cls.tmp.name, "grid", cls.positions)
        cls.messages = hotspot.read_messages(str(cls.run_dir / "*.jsonl.gz"))
        cls.first_ts = min(m.ts for m in cls.messages)
        cls.end_ts = max(m.ts for m in cls.messages)
        cls.n_bins = absencemap.n_bins_of(cls.first_ts, cls.end_ts, B)
        cls.states = absencemap.detect(cls.messages, cls.first_ts, cls.end_ts, B, ALPHA, MIN_EXP)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_t1_exact_first_flag_only_cell_and_release(self):
        # inject: closed-form constant-rate gap, count a flagged stretch into the rate, never release, or flag at the
        # pass count of the whole run instead of the per-bin-end rate
        passes = cell_pass_times(self.positions, *CELL)
        expect = reference_first_flag_bin(passes, self.first_ts, self.n_bins)
        self.assertIsNotNone(expect)
        self.assertGreaterEqual(expect, 20)  # silence starts at bin 20 (step 240 = 1200 s)
        seq = self.states[("0", "4,4")]
        flagged = [j for j, s in enumerate(seq) if s[0]]
        self.assertEqual(flagged[0], expect)
        # the only flagged cell of the whole stream
        ever = {cell for (zone, cell), sq in self.states.items() if any(s[0] for s in sq)}
        self.assertEqual(ever, {"4,4"})
        # release at the first bin end at/after the first re-crossing, held until then
        recross = min(p for p in passes if p >= T0 + SKIP_TO * STEP)
        j_release = next(j for j in range(self.n_bins) if self.first_ts + (j + 1) * B >= recross)
        self.assertEqual(flagged, list(range(expect, j_release)))
        self.assertFalse(seq[j_release][0])
        self.assertFalse(any(s[0] for s in seq[j_release:]))
        # the rate is frozen while flagged and equals passes / elapsed at the flag bin end
        t_flag = self.first_ts + (expect + 1) * B
        r_flag = len([p for p in passes if p <= t_flag]) / (t_flag - self.first_ts)
        for j in flagged:
            self.assertAlmostEqual(seq[j][2], r_flag, places=12)
        # score = rate * gap, growing while the silence lasts
        scores = [seq[j][1] for j in flagged]
        self.assertEqual(scores, sorted(scores))
        self.assertAlmostEqual(scores[0], r_flag * (t_flag - max(p for p in passes if p <= t_flag)), places=9)

    def test_t6_determinism(self):
        # inject: iterate a set / dict in hash order, or stamp wall-clock time into a decision or the --out document
        outs, rows = [], []
        for n in ("a", "b"):
            copy = Path(self.tmp.name) / f"copy-{n}"
            out = Path(self.tmp.name) / f"out-{n}.json"
            absencemap.run_absencemap(str(self.run_dir / "*.jsonl.gz"), "grid", copy, out)
            outs.append(out.read_bytes())
            # recorded_at is the store's wall-clock stamp (decisions.record_decision), the one field that may differ
            rows.append([{k: v for k, v in json.loads(ln).items() if k != "recorded_at"}
                         for ln in (copy / "decisions.jsonl").read_text().splitlines()])
        self.assertEqual(outs[0], outs[1])
        self.assertEqual(rows[0], rows[1])
        self.assertTrue(rows[0])

    def test_t7_claim_keys_and_publish_document(self):
        # inject: add, drop or rename a claim key (the AMOC harness reads window_hours / half_life_h), or write
        # detector 'cusum'
        copy = Path(self.tmp.name) / "copy-t7"
        out = Path(self.tmp.name) / "out-t7.json"
        doc = absencemap.run_absencemap(str(self.run_dir / "*.jsonl.gz"), "grid", copy, out)
        recs = [json.loads(ln) for ln in (copy / "decisions.jsonl").read_text().splitlines() if ln.strip()]
        fc = [r for r in recs if r.get("kind") == "hotspot_forecast"]
        self.assertTrue(fc)
        for r in fc:
            claim = json.loads(r["claim"]) if isinstance(r["claim"], str) else r["claim"]
            self.assertEqual(set(claim), CLAIM_KEYS)
            self.assertEqual(claim["detector"], "absence")
            self.assertIsNone(claim["window_hours"])
            self.assertIsNone(claim["half_life_h"])
            self.assertEqual(r["subject"], "Z0:4,4")
            self.assertEqual(claim["expected_passes"], claim["score"])
        self.assertEqual(doc["schema_version"], "fleet-absencemap/1")
        self.assertEqual(json.loads(out.read_text()), doc)
        flagged_publishes = [pb for pb in doc["publishes"] if pb["flagged"]]
        self.assertEqual(len(flagged_publishes), len(fc))
        for pb in flagged_publishes:
            (cells,) = pb["flagged"].values()
            self.assertEqual([c["cell"] for c in cells], ["4,4"])
            self.assertEqual(set(cells[0]), {"cell", "score", "rank", "rate", "gap_s"})
        self.assertEqual(doc["store_hash_before"], doc["store_hash_after"])

    def test_t5_store_copy_guard(self):
        # inject: drop the check_copy call (the original store would be rmtree'd), or accept the glob's directory
        glob = str(self.run_dir / "*.jsonl.gz")
        marker = self.run_dir / "store" / "decisions.jsonl"
        before = hashlib.sha256(marker.read_bytes()).hexdigest()
        outside = Path(self.tmp.name) / "elsewhere"
        bad = [self.run_dir / "store", self.run_dir, outside / "store", self.run_dir / "store" / "sub", self.run_dir.parent]
        for target in bad:
            err = io.StringIO()
            with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as cm:
                absencemap.main(["--glob", glob, "--store", f"jsonl:{target}", "--out", str(Path(self.tmp.name) / "o.json")])
            self.assertEqual(cm.exception.code, 2, target)
            with self.assertRaises(ValueError, msg=str(target)):
                absencemap.run_absencemap(glob, "grid", target, None)
        err = io.StringIO()  # not jsonl
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as cm:
            absencemap.main(["--glob", glob, "--store", f"sqlite:{outside}", "--out", str(Path(self.tmp.name) / "o.json")])
        self.assertEqual(cm.exception.code, 2)
        self.assertEqual(hashlib.sha256(marker.read_bytes()).hexdigest(), before)
        self.assertTrue((self.run_dir / "zone0-000.jsonl.gz").exists())
        self.assertFalse((outside).exists())

    def test_flag_validation(self):
        # inject: accept alpha outside (0, 1) or a non-positive min-expected
        glob = str(self.run_dir / "*.jsonl.gz")
        for flags in (["--alpha", "0"], ["--alpha", "1"], ["--min-expected", "0"], ["--bin-s", "0"], ["--top-k", "0"],
                      ["--publish-every", "0"]):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
                absencemap.main(["--glob", glob, "--store", f"jsonl:{self.tmp.name}/c", "--out", "o.json", *flags])
            self.assertEqual(cm.exception.code, 2, flags)


class TestBoundaryAndPasses(unittest.TestCase):
    def hop_run(self, tmp, n_passes, name):
        """One robot passes cell (3, 3) n_passes times, each time via a fresh cell, then parks 3000 s on the last cell."""
        seq, step = [], 0
        for k in range(n_passes):
            seq.append((step, 3, 3))
            seq.append((step + 1, 10 + k, 0))
            step += 2
        last = (10 + n_passes - 1, 0)
        for s in range(step, step + 600):
            seq.append((s, *last))
        return write_run(tmp, name, {"Z0-00": seq})

    def flagged_cells(self, run_dir):
        msgs = hotspot.read_messages(str(run_dir / "*.jsonl.gz"))
        f, e = min(m.ts for m in msgs), max(m.ts for m in msgs)
        st = absencemap.detect(msgs, f, e, B, ALPHA, MIN_EXP)
        return {cell for (_, cell), sq in st.items() if any(s[0] for s in sq)}

    def test_t2_min_expected_boundary(self):
        # inject: compare with > instead of >=, drop the eligibility check, or count the pass total of the whole run
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(self.flagged_cells(self.hop_run(t, 9, "nine")), set())
            self.assertEqual(self.flagged_cells(self.hop_run(t, 10, "ten")), {"3,3"})
            msgs = hotspot.read_messages(str(Path(t) / "nine" / "*.jsonl.gz"))
            self.assertEqual(len(absencemap.pass_times(msgs)[("0", "3,3")]), 9)

    def test_t3_standing_still_adds_one_pass(self):
        # inject: count every message as a pass, or key the visit on the header id instead of the cell
        with tempfile.TemporaryDirectory() as t:
            seq = [(s, 2, 2) for s in range(50)] + [(50 + s, 6, 6) for s in range(30)] + [(80 + s, 2, 2) for s in range(40)]
            d = write_run(t, "stand", {"Z0-00": seq})
            passes = absencemap.pass_times(hotspot.read_messages(str(d / "*.jsonl.gz")))
            self.assertEqual(passes[("0", "2,2")], [T0, T0 + 80 * STEP])
            self.assertEqual(passes[("0", "6,6")], [T0 + 50 * STEP])


@unittest.skipUnless((REAL_DATA / "s10c-blind" / "zone0-000.jsonl.gz").is_file(), "real data fleet/data/s10c-blind is absent")
class TestRealDataSmoke(unittest.TestCase):
    def test_t4_smoke_on_real_zone0(self):
        # inject: write into the real store, drop the zone filter, change the printed line, or exceed the time budget
        real = REAL_DATA / "s10c-blind"
        dec = real / "store" / "decisions.jsonl"
        before = hashlib.sha256(dec.read_bytes()).hexdigest()
        listing = sorted(p.name for p in real.iterdir())
        t0 = time.monotonic()
        res = subprocess.run([sys.executable, str(ROOT / "fleet" / "absencemap.py"), "--smoke", "--glob",
                              str(real / "zone0-000.jsonl.gz")], capture_output=True, text=True, timeout=120)
        wall = time.monotonic() - t0
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertLess(wall, 120)
        m = re.fullmatch(r"absencemap smoke s10c-blind zone 0: (\d+) publishes, (\d+) distinct flagged cells, "
                         r"(\d+) flag-publishes, ([0-9.]+)s\n", res.stdout)
        self.assertIsNotNone(m, res.stdout)
        publishes, distinct, flag_pubs = int(m.group(1)), int(m.group(2)), int(m.group(3))
        self.assertGreater(publishes, 0)
        self.assertLessEqual(distinct, flag_pubs)
        print(f"T4 {res.stdout.strip()} (subprocess wall {wall:.1f}s, {distinct} flagged cells)")
        self.assertEqual(hashlib.sha256(dec.read_bytes()).hexdigest(), before)
        self.assertEqual(sorted(p.name for p in real.iterdir()), listing)


class TestIsolationFromTruth(unittest.TestCase):
    def test_module_names_no_truth(self):
        # inject: import truth.py or mention a truth file in absencemap.py (the analyst isolation scan)
        text = (ROOT / "fleet" / "absencemap.py").read_text()
        self.assertNotRegex(text, r"(?i)truth")
        self.assertNotRegex(text, r"floor_cells|floor_skip|floor_coin|applied_floor")
        for name in ("check_copy", "sha256_file", "n_bins_of"):
            self.assertNotRegex(text, rf"(?m)^def {name}\b")


if __name__ == "__main__":
    unittest.main()

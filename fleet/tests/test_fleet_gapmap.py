"""Tests for S12B dead zones: the emitter's --deadzone write filter (G1, G2), fleet/gapmap.py (G3, G4), and the truth /
hotspot_score additions (G5). Envs run strictly one at a time: every emit is a subprocess of the emit CLI.
G2 pins the sha256 of a fixed-seed run per platform in tests/platform_expected.json (fleet_stream.<tag>.g2_*, measured on
master BEFORE the emitter change); a platform without a value skips visibly.
Each case names its red demonstration in an `# inject:` comment."""
import gzip
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "fleet", ROOT / "src", ROOT / "scripts", ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import _platform  # noqa: E402
import gapmap  # noqa: E402
import hotspot_score  # noqa: E402
import truth as truth_mod  # noqa: E402
from fleet_analyser import decisions  # noqa: E402
from fleet_analyser.parse import iso  # noqa: E402
from fleet_analyser.store import JsonlStore  # noqa: E402

EMIT = str(ROOT / "fleet" / "emit.py")
ENV = "tarware-small-4agvs-2pickers-globalobs-v1"
STEPS = 150
G1_SEED = 5
G2_SEED = 3


def emit(directory, seed, *extra):
    r = subprocess.run([sys.executable, EMIT, "--zones", "1", "--steps", str(STEPS), "--env", ENV, "--seed-base", str(seed),
                        "--speed", "0", "--workers", "1", "--dir", str(directory), *extra], capture_output=True, text=True)
    return r


def read_lines(directory):
    with gzip.open(Path(directory) / "zone0-000.jsonl.gz", "rb") as f:
        return f.read().splitlines()


def sha(b):
    return hashlib.sha256(b).hexdigest()


class TestDeadzoneEmitter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name)
        cls.plain, cls.dz = base / "plain", base / "dz"
        r = emit(cls.plain, G1_SEED)
        assert r.returncode == 0, r.stderr
        msgs = [json.loads(x) for x in read_lines(cls.plain)]
        first, last, arrivals = {}, {}, Counter()
        for m in msgs:  # a visit = a robot moving INTO a cell; a robot parked on a cell does not make it busy
            p = (m["agvPosition"]["x"], m["agvPosition"]["y"])
            first.setdefault(m["serialNumber"], p)
            if m["serialNumber"] in last and last[m["serialNumber"]] != p:
                arrivals[p] += 1
            last[m["serialNumber"]] = p
        ranked = sorted(((c, n) for c, n in arrivals.items() if c not in set(first.values())), key=lambda cn: (-cn[1], cn[0]))
        cls.cells = sorted(c for c, _ in ranked[:4])
        spec = ";".join(f"{x},{y}" for x, y in cls.cells)
        r = emit(cls.dz, G1_SEED, "--deadzone", spec)
        assert r.returncode == 0, r.stderr
        cls.plain_msgs = msgs
        cls.dz_msgs = [json.loads(x) for x in read_lines(cls.dz)]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_g1_differential_only_dead_cell_messages_are_missing(self):
        # inject: also drop the neighbours / renumber headerId after a drop / filter on the previous position
        dead = {f"{x},{y}" for x, y in self.cells}
        keep = [m for m in self.plain_msgs if f"{m['agvPosition']['x']},{m['agvPosition']['y']}" not in dead]
        n_dropped = len(self.plain_msgs) - len(keep)
        self.assertGreater(n_dropped, 0)
        self.assertEqual(len(self.cells), 4)
        self.assertEqual(self.dz_msgs, keep)
        truth = json.loads((self.dz / "truth.json").read_text())["zones"]["0"]
        self.assertEqual(truth["deadzones"], [list(c) for c in self.cells])
        self.assertEqual(truth["dropped_messages"], n_dropped)
        ledger = json.loads((self.dz / "emit_ledger.json").read_text())
        self.assertEqual(ledger["total"]["messages"], ledger["total"]["expected_messages"])  # REAL messages generated
        self.assertEqual(ledger["config"]["deadzones"], [list(c) for c in self.cells])
        plain_zone = json.loads((self.plain / "truth.json").read_text())["zones"]["0"]
        self.assertNotIn("deadzones", plain_zone)
        self.assertNotIn("dropped_messages", plain_zone)

    def test_g1_bad_flag_is_a_usage_error(self):
        # inject: accept a malformed or out-of-map cell
        for spec in ("a", "1;2", "1,2;", "-1,3", "999,999", ""):
            with self.subTest(spec=spec):
                with tempfile.TemporaryDirectory() as d:
                    r = emit(d, 0, "--deadzone", spec)
                    self.assertEqual(r.returncode, 2, (spec, r.stderr))

    def test_g3_gapmap_puts_the_dead_cells_in_the_top_10(self):
        # inject: include the Bresenham endpoints, or place every gap at P only
        doc = gapmap.build_document(gapmap.read_stream(str(self.dz / "*.jsonl.gz")), "g3")
        top = [c["cell"] for c in doc["zones"]["0"]["cells"][:10]]
        dead = [f"{x},{y}" for x, y in self.cells]
        hits = [c for c in dead if c in top]
        print(f"\nG3 precision@10 = {len(hits) / 10:.2f} (ceiling 0.4 with 4 dead cells); hits {hits}; top 10 {top}")
        self.assertGreaterEqual(len(hits), 3)


class TestByteIdentity(unittest.TestCase):
    def test_g2_no_flag_bytes_equal_master(self):
        # inject: writing deadzones: [] / dropped_messages: 0 into truth.json (or the ledger) when the flag is absent
        content = _platform.expected("fleet_stream", "g2_content_sha256")  # SkipTest here skips visibly
        truth_sha = _platform.expected("fleet_stream", "g2_truth_sha256")
        with tempfile.TemporaryDirectory() as d:
            r = emit(d, G2_SEED)
            self.assertEqual(r.returncode, 0, r.stderr)
            with gzip.open(Path(d) / "zone0-000.jsonl.gz", "rb") as f:
                self.assertEqual(sha(f.read()), content)
            self.assertEqual(sha((Path(d) / "truth.json").read_bytes()), truth_sha)
            for name in ("truth.json", "emit_ledger.json"):
                text = (Path(d) / name).read_text()
                self.assertNotIn("deadzone", text)
                self.assertNotIn("dropped_messages", text)


class TestPlacement(unittest.TestCase):
    def test_g4_distance_zero_one_two_and_diagonal(self):
        # inject: split zero-distance gaps in halves, keep Bresenham endpoints, or skip the diagonal fallback
        self.assertEqual(gapmap.place((3, 3), (3, 3), 4), [((3, 3), 4.0)])
        self.assertEqual(gapmap.place((3, 3), (4, 3), 4), [((3, 3), 2.0), ((4, 3), 2.0)])
        self.assertEqual(gapmap.place((0, 0), (2, 0), 3), [((1, 0), 3.0)])
        self.assertEqual(gapmap.place((0, 0), (4, 0), 6), [((1, 0), 2.0), ((2, 0), 2.0), ((3, 0), 2.0)])
        self.assertEqual(gapmap.place((0, 0), (1, 1), 2), [((0, 0), 1.0), ((1, 1), 1.0)])  # distance 2, interior empty
        for p, q in (((0, 0), (3, 2)), ((5, 5), (1, 2)), ((2, 2), (2, 6))):
            shares = gapmap.place(p, q, 7)
            self.assertAlmostEqual(sum(s for _, s in shares), 7.0)
            self.assertNotIn(p, [c for c, _ in shares])
            self.assertNotIn(q, [c for c, _ in shares])

    def test_g4_gaps_from_a_stream(self):
        # inject: count duplicates or a rejected line as received messages, or sort by arrival instead of headerId
        t = 1767225600  # 2026-01-01T00:00:00Z
        robots = {("0", "Z0-01"): [(0, t, (1, 1)), (1, t + 5, (1, 1)), (4, t + 20, (1, 3)), (5, t + 25, (1, 3))],
                  ("0", "Z0-02"): [(2, t, (7, 7)), (3, t + 5, (7, 8))]}
        doc = gapmap.build_document(robots, "g4", top_k=2)
        cells = {c["cell"]: c for c in doc["zones"]["0"]["cells"]}
        self.assertEqual(cells["1,2"]["dropped"], 2.0)  # P (1,1) -> Q (1,3), 2 missing, interior (1,2)
        self.assertEqual(cells["1,2"]["gaps"], 1)
        self.assertEqual(cells["1,2"]["robots"], ["Z0-01"])
        self.assertEqual(cells["1,2"]["minutes"], ["2026-01-01T00:00Z"])
        self.assertEqual(doc["unplaced_leading_missing"], 2)  # Z0-02 starts at headerId 2
        self.assertEqual([d["subject"] for d in doc["decisions"]], ["1,2"])
        self.assertEqual(doc["decisions"][0]["kind"], "gap_cell")
        self.assertEqual(doc["decisions"][0]["claim"]["rank"], 1)

    def test_g4_original_store_refused(self):
        # inject: drop the check_copy call in gapmap.main
        with tempfile.TemporaryDirectory() as d:
            run = Path(d) / "run"
            run.mkdir()
            with gzip.open(run / "zone0-000.jsonl.gz", "wb") as f:
                for h in (0, 3):
                    f.write((json.dumps({"headerId": h, "timestamp": iso(1767225600 + 5 * h), "serialNumber": "Z0-01",
                                         "orderId": "", "agvPosition": {"x": 1, "y": 1}, "driving": False, "errors": [],
                                         "loads": []}) + "\n").encode())
            (run / "store").mkdir()
            out = Path(d) / "out.json"
            args = [sys.executable, str(ROOT / "fleet" / "gapmap.py"), "--glob", str(run / "*.jsonl.gz"), "--run", "r",
                    "--out", str(out)]
            r = subprocess.run(args + ["--store", f"jsonl:{run / 'store'}"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertFalse(out.exists())
            self.assertEqual(list((run / "store").iterdir()), [])
            r = subprocess.run(args + ["--store", f"jsonl:{Path(d) / 'store-gap'}"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("top cells", r.stdout)
            rows = [json.loads(x) for x in (Path(d) / "store-gap" / "decisions.jsonl").read_text().splitlines()]
            self.assertEqual({x["kind"] for x in rows}, {"gap_cell"})


def v2_truth(deadzones=None, steps=500):
    zone = dict(floor_cells={"4,4": 0.5}, floor_skips=[], blocked_windows=[dict(cell="5,5", start_step=0, end_step=10, known=True)],
                outage_windows=[], frozen_windows=[dict(agent_index=0, serial="Z0-01", start_step=2, end_step=6, cell="6,6",
                                                        cells=["6,6"])], burst=None)
    if deadzones is not None:
        zone["deadzones"] = deadzones
    return dict(schema_version="fleet-truth/2", t0="2026-01-01T00:00:00Z", step_seconds=5, steps=steps, zones={"0": zone})


class TestTruthAndScore(unittest.TestCase):
    def test_g5_truth_positive_deadzone_only_when_listed(self):
        # inject: write 'deadzone' for every cell / match a zone without the key / let 'deadzone' answer for robots
        plain, dz = v2_truth(), v2_truth([[5, 5], [8, 9]])
        for subject, expect in (("4,4", {"floor"}), ("5,5", {"blocked"}), ("6,6", {"frozen"}), ("Z0-01", {"frozen"}),
                                ("1,1", set())):
            self.assertEqual(truth_mod.truth_positive(plain, "0", subject, 0, 20), frozenset(expect), subject)
        self.assertEqual(truth_mod.truth_positive(dz, "0", "5,5", 0, 20), frozenset({"blocked", "deadzone"}))
        self.assertEqual(truth_mod.truth_positive(dz, "0", "8,9", 0, 20), frozenset({"deadzone"}))
        self.assertEqual(truth_mod.truth_positive(dz, "0", "4,4", 0, 20), frozenset({"floor"}))
        self.assertEqual(truth_mod.truth_positive(dz, "0", "Z0-01", 0, 20), frozenset({"frozen"}))
        self.assertEqual(truth_mod.truth_positive(dict(v2_truth(), zones={"0": dict(floor_cells={"1,1": 1.0})}), "0", "1,1",
                                                  None, None), frozenset({"floor"}))  # v1-style zone, no steps needed

    def test_g5_truth_kinds_unchanged_without_deadzones(self):
        # inject: add a 'deadzone' entry always, or let it join 'any'
        costmap = {"zones": {"0": {"5,5": 3.0, "8,9": 2.0, "4,4": 1.0}}}
        base = hotspot_score.truth_kinds(v2_truth(), costmap)
        self.assertEqual(list(base), ["floor", "blocked", "outage", "any", "frozen"])
        self.assertEqual(list(hotspot_score.truth_kinds(v2_truth([]), costmap)), list(base))  # an empty list is no deadzone
        with_dz = hotspot_score.truth_kinds(v2_truth([[8, 9], [1, 1]]), costmap)
        self.assertEqual(list(with_dz), list(base) + ["deadzone"])
        for kind in base:
            self.assertEqual(with_dz[kind], base[kind], kind)  # 'any' included: unchanged
        self.assertEqual(with_dz["deadzone"]["positives"], 2)
        self.assertEqual(with_dz["deadzone"]["k"]["20"]["hits"], 1)
        self.assertEqual(with_dz["deadzone"]["k"]["20"]["recall"], 0.5)

    def test_g5_gap_grading_only_with_gap_cell_decisions(self):
        # inject: always emit gap_grading, or count a non-dead cell as a hit, or pool precision@10 over the wrong zones
        truth = v2_truth([[8, 9], [1, 1]])
        self.assertIsNone(hotspot_score.gap_grading(truth, []))
        with tempfile.TemporaryDirectory() as d:
            st = JsonlStore(d)
            for rank, cell in enumerate(("8,9", "2,2", "1,1"), 1):
                decisions.record_decision(st, run="r", kind="gap_cell", subject=cell, start_iso=iso(1767225600 + rank),
                                          decided_at=1767226000, claim=dict(dropped=3.0, gaps=1, rank=rank, top_k=10, zone="0"),
                                          rationale="t", expected=3.0, grade_after=1767226000)
            rows = st.select("decisions", {"run": "r", "kind": "gap_cell"})
            st.close()
        g = hotspot_score.gap_grading(truth, rows)
        self.assertEqual((g["decisions"], g["hits"], g["deadzone_cells"]), (3, 2, 2))
        self.assertAlmostEqual(g["precision"], 2 / 3)
        self.assertEqual(g["recall"], 1.0)
        self.assertEqual(g["per_zone"], {"0": {"hits": 2, "decisions": 3}})
        self.assertEqual(g["precision_at_10"], {"per_zone": {"0": 0.2}, "pooled": 0.2})
        # a truth without deadzones never has a hit
        self.assertEqual(hotspot_score.gap_grading(v2_truth(), rows)["hits"], 0)


if __name__ == "__main__":
    unittest.main()

"""Tests for S15A fleet/stall_baseline.py: the naive stall rules (Detector at 30 / 60 s, InOrbit's two position forms) and
our station-aware bounded rule on one synthetic stream, with exact flagged sets and exact alert times.

Synthetic stream (one robot Z0-01, one message per 5 s, a job throughout, cells of 0.5 m): six stands, each entered by ONE
driving message at a midpoint cell >= 6 cells (3 m) from the stand cell and from the previous stand cell, so stillness
(box and driving-false) starts at the stop message s and every alert time is exact:
  a 45 s at the station cell | b 90 s | c 20 s | d 200 s | e 700 s | f 200 s spinning in place (driving true).
Expected flagged sets (a stand is flagged iff a rule opens an episode starting at its stop message):
  N0-30 {a,b,d,e}  N0-60 {b,d,e}  N1 {e}  N2-30 {a,b,d,e,f}  N2-60 {b,d,e,f}  N2-120 {d,e,f}  N2-180 {d,e,f}  ours {b,d,e}
Alert times: N2-W at s+W, N1 at s+660 (episode start s for both). `ours` runs station_radius 1 and servicing_max_s "auto",
which resolves to 300 s on this stream (one station stop, fewer than 5 stops in the sample -> the cap), so nothing is pinned.
Each case names its red demonstration in an `# inject:` comment. The smoke test skips only when fleet/data/moroop raw data,
the jsonl directory or pyarrow is missing (CI has only the tracked stations.json)."""
import gzip
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "fleet", ROOT / "src", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import stall_baseline as sb  # noqa: E402
import timebudget as tb  # noqa: E402
from adapters import moroop  # noqa: E402
from fleet_analyser import score as score_mod  # noqa: E402
from fleet_analyser import servicing  # noqa: E402
from fleet_analyser.detector import Detector  # noqa: E402
from fleet_analyser.parse import Message, iso  # noqa: E402

try:
    import pyarrow  # noqa: F401
    HAVE_PYARROW = True
except ImportError:
    HAVE_PYARROW = False

SCRIPT = str(ROOT / "fleet" / "stall_baseline.py")
BASE = 1767225600
CELL_M = 0.5
STANDS = (("a", 45), ("b", 90), ("c", 20), ("d", 200), ("e", 700), ("f", 200))
EXPECTED = {"N0-30": "abde", "N0-60": "bde", "N1": "e", "N2-30": "abdef", "N2-60": "bdef", "N2-120": "def", "N2-180": "def",
            "ours": "bde"}
WINDOW = {"N2-30": 30, "N2-60": 60, "N2-120": 120, "N2-180": 180}


def msg(ts, x, order="J", driving=False, y=0, serial="Z0-01", header=None):
    return Message(serial=serial, zone="0", header_id=ts if header is None else header, ts=ts, order_id=order, x=x, y=y,
                   driving=driving, faulted=False, loaded=False, raw_len=1)


def synthetic():
    """(messages, {stand name: stop message ts s}, station cells {(0, 0)})."""
    out, starts = [], {}
    t = BASE
    for k, (name, dur) in enumerate(STANDS):
        bx = 20 * k
        out.append(msg(t, bx - 10, driving=True))  # the ONE drive message, >= 6 cells from this and the previous stand
        s = t + 5
        starts[name] = s
        for j in range(0, dur, 5):
            out.append(msg(s + j, bx, driving=(name == "f")))
        t = s + dur
    out.append(msg(t, 20 * len(STANDS) - 10, driving=True))  # leaves the last stand
    return out, starts, {(0, 0)}


def flagged(name_of_start, eps):
    return "".join(sorted(name_of_start[e["start"]] for e in eps if e["start"] in name_of_start))


class SyntheticStreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.msgs, cls.starts, cls.stations = synthetic()
        cls.by_start = {s: n for n, s in cls.starts.items()}
        cls.kept = tb.kept_messages(cls.msgs)
        cls.bound = servicing.resolve("auto", cls.msgs, cls.stations, 1)["servicing_max_s"]
        cls.eps = {r: sb.rule_episodes(cls.kept, r, CELL_M, cls.stations, 1, cls.bound) for r in sb.RULES}

    def test_auto_bound_is_derivable_and_is_the_cap(self):
        # inject: pass servicing_max_s=30 -> a (45 s at the station) becomes an overrun and the ours set gains 'a'
        self.assertEqual(self.bound, 300.0)

    def test_flagged_set_per_rule(self):
        # inject: strict "<=" in the box test -> N2 flags change at the boundary; stuck_after 45 for N0-30 drops 'a'
        for rule, want in EXPECTED.items():
            with self.subTest(rule=rule):
                self.assertEqual(flagged(self.by_start, self.eps[rule]), want)

    def test_no_other_episodes(self):
        # inject: leave the drive messages at the destination cell -> extra position episodes appear
        for rule in sb.RULES:
            with self.subTest(rule=rule):
                self.assertEqual(len(self.eps[rule]), len(EXPECTED[rule]))

    def test_n2_alerts_exactly_at_stop_plus_w(self):
        # inject: build the window as [t-W, t] -> the alert moves to s+W-1 (the carried piece is the pre-stop position)
        for rule, w in WINDOW.items():
            for e in self.eps[rule]:
                with self.subTest(rule=rule, start=e["start"]):
                    self.assertEqual(e["alert"], e["start"] + w)
                    self.assertEqual(e["alert"] - w, e["start"])
            runs, _ = sb.box_condition_runs(self.kept, w, "side", CELL_M)
            firsts = {a for a, _ in runs}
            for name in EXPECTED[rule]:
                s = self.starts[name]
                with self.subTest(rule=rule, stand=name, edge="s+W-1"):
                    self.assertIn(s + w, firsts)
                    self.assertFalse(any(a <= s + w - 1 < b for a, b in runs))

    def test_n1_alert_at_stop_plus_660(self):
        # inject: sustain 601 s instead of 600 -> s+661; skip the 60 s window -> s+600
        (e,) = self.eps["N1"]
        s = self.starts["e"]
        self.assertEqual((e["start"], e["alert"]), (s, s + 660))
        runs, _ = sb.box_condition_runs(self.kept, 60, "diag", CELL_M)
        self.assertIn(s + 60, {a for a, _ in runs})  # the 60 s condition first true at s+60, then at every second

    def test_episode_end_is_first_second_the_condition_fails(self):
        # inject: end = the last stop message -> 5 s early
        d_stop = self.starts["d"]
        (d,) = [e for e in self.eps["N2-180"] if e["start"] == d_stop]
        self.assertEqual(d["end"], d_stop + 200)  # the next drive message
        self.assertEqual(d["resolution"], "moved")

    def test_n0_rules_are_the_detector_with_the_same_episodes(self):
        # inject: re-implement N0 as a velocity timer -> the spin stand 'f' (driving) would be flagged
        for rule, w in (("N0-30", 30), ("N0-60", 60)):
            det = Detector(stuck_after=w)
            ev = []
            for m in sorted(self.msgs, key=lambda m: (m.ts, m.serial)):
                ev += det.feed(m)
            ev += det.end_all()
            starts = sorted(e["start"] for e in ev if e["kind"] == "episode_open")
            self.assertEqual(starts, sorted(e["start"] for e in self.eps[rule]))

    def test_ours_station_stop_is_servicing_not_stuck(self):
        # inject: stations=None -> 'a' is flagged (ours == N0-30)
        self.assertNotIn(self.starts["a"], [e["start"] for e in self.eps["ours"]])

    def test_spin_in_place_is_still_for_a_box_but_not_for_driving(self):
        # inject: treat rotation as motion in the box rules -> f drops out of N2
        s = self.starts["f"]
        self.assertIn(s, [e["start"] for e in self.eps["N2-30"]])
        self.assertNotIn(s, [e["start"] for e in self.eps["N0-30"]])


class BoundaryTests(unittest.TestCase):
    def stream(self, dx, dy, until=200):
        # (0, 0) at t=0, the cell (dx, dy) from t=1 on; first full window at t=W holds both
        return [msg(0, 0, y=0, driving=True)] + [msg(t, dx, y=dy) for t in range(1, until)]

    def first_true(self, kind, w, dx, dy):
        runs, _ = sb.box_condition_runs(tb.kept_messages(self.stream(dx, dy)), w, kind, CELL_M)
        return runs[0][0] if runs else None

    def test_side_boundary_three_cells_qualify_four_do_not(self):
        # inject: "<=" instead of "<" -> 4 cells (2.0 m) would qualify
        self.assertEqual(self.first_true("side", 30, 3, 0), 30)  # 1.5 m at t = 30 (window holds cell 0 and cell 3)
        self.assertEqual(self.first_true("side", 30, 0, 3), 30)
        self.assertEqual(self.first_true("side", 30, 4, 0), 31)  # 2.0 m: only once cell 0 has left the window
        self.assertEqual(self.first_true("side", 30, 0, 4), 31)

    def test_diagonal_is_euclidean_cell_diagonal_times_half_metre(self):
        # inject: Manhattan or an extra cell width -> (3, 3) passes / (3, 2) fails
        for dx, dy, ok in ((2, 2, True), (3, 2, True), (3, 0, True), (3, 3, False), (4, 0, False), (0, 4, False)):
            with self.subTest(dx=dx, dy=dy):
                self.assertEqual(self.first_true("diag", 60, dx, dy), 60 if ok else 61)

    def test_sim_scale_reads_two_metres_as_two_cells(self):
        # inject: use cell_m 0.5 on the sim -> a spread of 2 cells would qualify
        stream = tb.kept_messages(self.stream(1, 0))
        runs, _ = sb.box_condition_runs(stream, 30, "side", sb.SIM_CELL_M)
        self.assertEqual(runs[0][0], 30)
        stream = tb.kept_messages(self.stream(2, 0))
        runs, _ = sb.box_condition_runs(stream, 30, "side", sb.SIM_CELL_M)
        self.assertEqual(runs[0][0], 31)

    def test_n1_needs_601_true_seconds(self):
        # inject: sustain >= 600 instead of 601 samples -> the 660 s stand alerts
        def eps(x):
            msgs = [msg(0, -10, driving=True), msg(5, 0)] + [msg(5 + j, 0) for j in range(5, x, 5)] + [msg(5 + x, 10, driving=True)]
            return sb.position_rule_episodes(tb.kept_messages(msgs), "N1", CELL_M)

        self.assertEqual(len(eps(660)), 0)  # still on [s+60, s+660) = 600 s
        (e,) = eps(661)
        self.assertEqual((e["start"], e["alert"]), (5, 665))

    def test_window_before_first_message_is_not_evaluated(self):
        # inject: evaluate from t = first ts -> the alert would be at the first message
        kept = tb.kept_messages([msg(100 + j, 0) for j in range(0, 100, 5)] + [msg(200, 50, driving=True)])
        (e,) = sb.position_rule_episodes(kept, "N2-60", CELL_M)
        self.assertEqual((e["start"], e["alert"]), (100, 160))

    def test_empty_order_anywhere_in_window_is_false(self):
        # inject: drop the orderId gate -> the idle stand is flagged
        kept = tb.kept_messages([msg(0, -10, driving=True)] + [msg(5 + j, 0, order="") for j in range(0, 200, 5)]
                                + [msg(205, 30, driving=True)])
        self.assertEqual(sb.position_rule_episodes(kept, "N2-30", CELL_M), [])
        kept = tb.kept_messages([msg(0, -10, driving=True)] + [msg(5 + j, 0, order="" if j == 60 else "J") for j in range(0, 200, 5)]
                                + [msg(205, 30, driving=True)])
        runs, _ = sb.box_condition_runs(kept, 30, "side", CELL_M)
        for t in (65, 94, 99):  # the empty message (ts 65) is in the window (t-30, t] or is its carried piece
            self.assertFalse(any(a <= t < b for a, b in runs), t)
        self.assertTrue(any(a <= 100 < b for a, b in runs))

    def test_box_span_grows_back_then_forward(self):
        # inject: forward only -> the span would start at the label message
        kept = tb.kept_messages([msg(0, -20, driving=True), msg(10, 0), msg(20, 1), msg(30, 2), msg(40, 3), msg(50, 40, driving=True)])
        self.assertEqual(sb._box_span(kept, 2, CELL_M), dict(start=10, end=50, duration_s=40))


    def test_label_without_stopped_run_has_null_latency(self):
        # inject: latency measured from the label start when no stopped run overlaps -> a number, not None
        kept = tb.kept_messages([msg(BASE + 5 * i, i, driving=True) for i in range(40)])
        native = [dict(created_at=(BASE + 10) * 1_000_000, id=1, stuck_reason="GoalObstructed"),
                  dict(created_at=(BASE + 100) * 1_000_000, id=2, stuck_reason=None)]
        eps = {r: [] for r in sb.RULES}
        eps["N2-30"] = [dict(start=BASE + 10, end=BASE + 90, alert=BASE + 40)]
        rows = sb._label_rows(7, kept, native, eps)
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["stopped_run"])
        self.assertEqual(rows[0]["rules"]["N2-30"]["alert"], BASE + 40)
        self.assertIsNone(rows[0]["rules"]["N2-30"]["alert_latency_s"])


class GapTests(unittest.TestCase):
    def stream(self, gap):
        t0 = BASE
        msgs = [msg(t0, 0, driving=True), msg(t0 + 5, 10), msg(t0 + 10, 10)]
        msgs += [msg(t0 + 10 + j, 10) for j in range(5, 200, 5)] if not gap else []
        msgs.append(msg(t0 + 210, 30, driving=True))
        return tb.kept_messages(msgs)

    def test_n2_180_fires_across_a_200_s_gap_and_counts_once(self):
        # inject: skip the carry-forward (grid only on message seconds) -> no alert; containment instead of overlap -> 0
        kept = self.stream(gap=True)
        (e,) = sb.position_rule_episodes(kept, "N2-180", CELL_M)
        self.assertEqual(e["alert"], BASE + 5 + 180)
        self.assertEqual(sum(x["gap_spanning"] for x in sb.position_rule_episodes(kept, "N2-180", CELL_M)), 1)
        self.assertEqual(sb.gaps_of(kept), [(BASE + 10, BASE + 210)])

    def test_dense_stream_has_no_gap_spanning_alert(self):
        # inject: count every alert -> 1
        kept = self.stream(gap=False)
        (e,) = sb.position_rule_episodes(kept, "N2-180", CELL_M)
        self.assertEqual(e["alert"], BASE + 5 + 180)
        self.assertFalse(e["gap_spanning"])

    def test_spans_gap_overlap_edges(self):
        # inject: ">=" on either edge -> a gap that only touches the window counts
        gaps = [(100, 200)]
        self.assertTrue(sb.spans_gap(gaps, 150, 140))   # alert inside the gap
        self.assertTrue(sb.spans_gap(gaps, 300, 199))   # window starts 1 s before the gap ends
        self.assertFalse(sb.spans_gap(gaps, 300, 200))  # window (200, 300] starts where the gap ends
        self.assertFalse(sb.spans_gap(gaps, 100, 0))    # alert at the gap's first second
        self.assertFalse(sb.spans_gap([], 100, 0))


def write_sim_run(directory, with_store=True):
    """A one-zone simulator-style run directory made of the synthetic stream (custom.stuck_event on the later stop messages
    of stands b, d, e) plus stations.json (cell (0, 0)) and, optionally, a `store` next to the zone file."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    msgs, starts, _ = synthetic()
    dur = dict(STANDS)
    prev = None
    lines = []
    for k, m in enumerate(msgs, start=1):
        # the simulator wanted the robot to move at step prev and it did not: m carries stuck_event inside a b / d / e stand
        stuck = prev is not None and any(starts[n] <= prev.ts and m.ts < starts[n] + dur[n] for n in "bde")
        obj = {"schema_version": "fleet-state/2", "headerId": k, "timestamp": iso(m.ts), "manufacturer": "sim",
               "serialNumber": "Z0-01", "orderId": m.order_id, "lastNodeId": f"{m.x}-{m.y}",
               "agvPosition": {"x": m.x, "y": m.y, "theta": 0.0, "mapId": "m"}, "driving": m.driving, "paused": False,
               "errors": [], "loads": [], "nodeStates": [], "custom": {"stuck_event": bool(stuck)}}
        lines.append((json.dumps(obj, separators=(",", ":")) + "\n").encode())
        prev = m
    with open(directory / "zone0-000.jsonl.gz", "wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as f:
        for ln in lines:
            f.write(ln)
    (directory / "stations.json").write_text(json.dumps({"stations": [[0, 0]]}))
    if with_store:
        (directory / "store").mkdir()
        (directory / "store" / "stuck_episodes.jsonl").write_text('{"episode_id": "x"}\n')
    return directory


def run_main(argv):
    out, err = StringIO(), StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = sb.main(argv)
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 2
    return code, out.getvalue(), err.getvalue()


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmpdir = Path(self.tmp.name)
        self.run_dir = write_sim_run(self.tmpdir / "run")
        self.args = ["--runs", str(self.run_dir), "--sim-stations", str(self.run_dir / "stations.json"), "--workers", "1"]

    def test_written_counts_equal_in_memory_counts(self):
        # inject: write the doc from a second computation with stuck_after 60 -> counts differ
        out = self.tmpdir / "out.json"
        code, _, err = run_main([*self.args, "--out", str(out)])
        self.assertEqual(code, 0, err)
        doc = json.loads(out.read_text())
        mem = sb.sim_run(self.run_dir, str(self.run_dir / "stations.json"), 0, 1)
        self.assertEqual(doc["sim"][str(self.run_dir)]["zones"], json.loads(json.dumps(mem["zones"])))
        zone = doc["sim"][str(self.run_dir)]["zones"]["0"]
        self.assertEqual({r: zone[r]["episodes_total"] for r in sb.RULES},
                         {"N0-30": 4, "N0-60": 3, "N1": 1, "N2-30": 5, "N2-60": 4, "N2-120": 3, "N2-180": 3, "ours": 3})
        for r in sb.POSITION_RULES:
            self.assertEqual(zone[r]["scale"], "assumed 1 cell = 1 m")
        self.assertNotIn("scale", zone["ours"])
        for key in ("detected_episodes", "truth_episodes", "matched", "precision", "recall"):
            self.assertIn(key, zone["ours"])
        self.assertEqual(doc["store_guard"]["unchanged"], True)

    def test_sim_scoring_is_score_run_unchanged(self):
        # inject: count matches with a private overlap rule -> matched differs from score_run on the same rows
        zl = sb._zone_lines(self.run_dir)
        msgs = sb._parse_zone(zl["0"])
        rows = [sb._episode_row(r["robot"], r, r["cause"]) for r in sb.detector_rows(msgs, stuck_after=30)]
        res = score_mod.score_run({"0": zl["0"]}, sb._RowsStore(rows), "x", stuck_after=30)
        mem = sb.sim_run(self.run_dir, str(self.run_dir / "stations.json"), 0, 1)["zones"]["0"]["N0-30"]
        self.assertEqual((mem["detected_episodes"], mem["truth_episodes"], mem["matched"]),
                         (res["detected_episodes"], res["truth_episodes"], res["matched"]))
        self.assertGreater(res["truth_episodes"], 0)

    def test_two_runs_give_byte_identical_json(self):
        # inject: put a timestamp or a dict in insertion order into the document
        a, b = self.tmpdir / "a.json", self.tmpdir / "b.json"
        self.assertEqual(run_main([*self.args, "--out", str(a)])[0], 0)
        self.assertEqual(run_main([*self.args, "--out", str(b)])[0], 0)
        self.assertEqual(a.read_bytes(), b.read_bytes())

    def test_store_guard_refuses_an_original_store(self):
        # inject: drop the guard in open_store_for_write -> the original store is opened
        store = self.run_dir / "store"
        with self.assertRaises(SystemExit) as cm:
            sb.open_store_for_write(store)
        self.assertIn("original store", str(cm.exception))
        with self.assertRaises(SystemExit):
            sb.guard_out_path(store / "x.json")
        (self.run_dir / "store-sb").mkdir()
        with self.assertRaises(SystemExit):
            sb.open_store_for_write(self.run_dir / "store-sb")
        copy = sb.copy_store_to_temp(store, self.tmpdir)  # the copy may be opened
        self.assertIsNotNone(sb.open_store_for_write(copy))
        sb.guard_out_path(self.tmpdir / "fine.json")

    def test_cli_exits_nonzero_when_out_is_inside_an_original_store(self):
        # inject: skip guard_out_path in main -> exit 0 and a file under the store
        before = tb.store_hash(self.run_dir / "store")
        p = subprocess.run([sys.executable, SCRIPT, *self.args, "--out", str(self.run_dir / "store" / "o.json")],
                           capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("original store", p.stderr)
        self.assertEqual(tb.store_hash(self.run_dir / "store"), before)

    def test_changed_store_exits_one_and_writes_nothing(self):
        # inject: compare hashes before only -> exit 0
        out = self.tmpdir / "out.json"
        real = sb.run_all

        def touching(*a, **k):
            (self.run_dir / "store" / "stuck_episodes.jsonl").write_text("changed\n")
            return real(*a, **k)

        with mock.patch.object(sb, "run_all", touching):
            code, _, err = run_main([*self.args, "--out", str(out)])
        self.assertEqual(code, 1)
        self.assertIn("store changed", err)
        self.assertFalse(out.exists())

    def test_hash_guard_covers_every_store_directory_of_the_run(self):
        # inject: hash only "store" -> a change under store-sb passes
        (self.run_dir / "store-sb").mkdir()
        (self.run_dir / "store-sb" / "f").write_text("1")
        keys = sorted(Path(k).name for k in sb.hash_run_stores([self.run_dir]))
        self.assertEqual(keys, ["store", "store-sb"])

    def test_reuses_existing_code_by_import(self):
        # inject: a private copy of the Detector / label match in stall_baseline
        self.assertIs(sb.Detector, Detector)
        self.assertIs(sb.moroop, moroop)
        self.assertIs(sb.score_mod, score_mod)
        self.assertIs(sb.tb, tb)
        src = Path(SCRIPT).read_text()
        for forbidden in ("class Detector", "def label_comparison", "def score_run", "def run_is_stuck", "def stopped_runs"):
            self.assertNotIn(forbidden, src)

    def test_nothing_to_do_is_an_error(self):
        # inject: default to --moroop
        self.assertNotEqual(run_main(["--out", str(self.tmpdir / "o.json")])[0], 0)

    def test_full_run_asserts_567_and_smoke_does_not(self):
        # inject: drop the 567 check from the --moroop path -> exit 0 with 540
        def fake(count_each):
            def run_all(shifts, *a, **k):
                rules = {r: dict(counts=dict(stuck_runs=count_each, hits=0, misses=0, false_alarms=count_each, ge30=0, lt30=0,
                                             episodes=0, timeouts=0, timeouts_detected=0), false_alarms_on_station_cell=0,
                                 **({"gap_spanning_alerts": 0} if r in sb.POSITION_RULES else {})) for r in sb.RULES}
                return [dict(shift=k, name=moroop.SHIFTS[k], rules=rules, labels=[]) for k in shifts]
            return run_all

        out = self.tmpdir / "m.json"
        with mock.patch.object(sb, "run_all", fake(60)):
            code, _, err = run_main(["--moroop", "--out", str(out)])
        self.assertEqual(code, 1)
        self.assertIn("567", err)
        self.assertFalse(out.exists())
        with mock.patch.object(sb, "run_all", fake(63)):
            self.assertEqual(run_main(["--moroop", "--out", str(out)])[0], 0)
        self.assertEqual(json.loads(out.read_text())["moroop"]["rules"]["N0-30"]["counts"]["stuck_runs"], 567)
        out2 = self.tmpdir / "s.json"
        with mock.patch.object(sb, "run_all", fake(60)):
            self.assertEqual(run_main(["--smoke", "--out", str(out2)])[0], 0)  # one shift: the 567 check cannot apply
        self.assertEqual(json.loads(out2.read_text())["src"]["shifts"], [sb.SMOKE_SHIFT])


def moroop_dir():
    """fleet/data/moroop of this checkout, else of the main checkout (WR_MAIN_CHECKOUT or git common dir), with raw data and
    the jsonl directory; None when absent."""
    cands = [ROOT]
    if os.environ.get("WR_MAIN_CHECKOUT"):
        cands.append(Path(os.environ["WR_MAIN_CHECKOUT"]))
    try:
        common = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                capture_output=True, text=True, check=True).stdout.strip()
        cands.append(Path(common).parent)
    except (subprocess.CalledProcessError, OSError):
        pass
    for c in cands:
        d = c / "fleet" / "data" / "moroop"
        if (d / "raw" / "data").is_dir() and (d / "jsonl-sb" / "zone1-000.jsonl.gz").is_file() and (d / "stations.json").is_file():
            return d
    return None


MOROOP = moroop_dir()


@unittest.skipUnless(MOROOP is not None and HAVE_PYARROW, "fleet/data/moroop raw data, jsonl-sb or pyarrow missing")
class SmokeTests(unittest.TestCase):
    def test_smoke_shift_1_end_to_end_under_two_minutes(self):
        # inject: run all nine shifts, or leave the Detector path O(n^2) -> over the 120 s bound
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "smoke.json"
            t0 = time.monotonic()
            with mock.patch.object(moroop, "label_comparison", wraps=moroop.label_comparison) as lc:
                code, stdout, err = run_main(["--smoke", "--moroop-dir", str(MOROOP), "--out", str(out), "--workers", "1"])
            wall = time.monotonic() - t0
            self.assertEqual(code, 0, err)
            self.assertLess(wall, 120)
            self.assertEqual(lc.call_count, len(sb.RULES))  # the adapter's label match is what scored every rule
            doc = json.loads(out.read_text())
            self.assertTrue(doc["smoke"])
            self.assertEqual(doc["src"]["shifts"], [1])
            rules = doc["moroop"]["rules"]
            self.assertEqual(sorted(rules), sorted(sb.RULES))
            ref = ROOT / "results" / "fleet"
            old = json.loads((ref / "timebudget_moroop_shifts.json").read_text())["shifts"]["1"]["label"]
            sbl = json.loads((ref / "moroop_label-sb.json").read_text())["shifts"]["1"]
            self.assertEqual(rules["N0-30"]["counts"]["stuck_runs"], old["stuck_runs"])
            self.assertEqual(rules["N0-30"]["counts"]["false_alarms"], old["false_alarms"]["count"])
            self.assertEqual({k: rules["ours"]["counts"][k] for k in ("stuck_runs", "false_alarms")},
                             {"stuck_runs": sbl["stuck_runs"], "false_alarms": sbl["false_alarms"]["count"]})
            self.assertEqual(rules["ours"]["counts"]["hits"], sbl["episodes_ge_30s"]["hits"])
            mem = sb.moroop_shift(1, MOROOP, "jsonl-sb")
            for r in sb.RULES:  # written counts == in-memory counts
                self.assertEqual(rules[r]["per_shift"]["1"], mem["rules"][r]["counts"])
            for r in sb.POSITION_RULES:
                self.assertIn("gap_spanning_alerts", rules[r])
            print(f"\nS15A smoke wall {wall:.1f} s; shift 1 stuck_runs "
                  + ", ".join(f"{r} {rules[r]['counts']['stuck_runs']}" for r in sb.RULES))


if __name__ == "__main__":
    unittest.main()

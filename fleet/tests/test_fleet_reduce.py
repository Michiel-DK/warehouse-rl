"""Tests for S18A fleet/reduce.py (keep rules R0-R5) and fleet/reduce_check.py (full vs reduced, exact comparison).

Fixtures only (CI has no data). Each discriminating case names its red demonstration in an `# inject:` comment.
Fixture time is one line per robot per 5 s; "stop" below means driving false with a non-empty orderId (the detector's run),
stuck_after is 30 s. Each rung fixture states the H it is built for.
"""
import contextlib
import gzip
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "fleet", ROOT / "src", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import reduce as rd  # noqa: E402
import reduce_check as rc  # noqa: E402
import stall_baseline as sb  # noqa: E402
import timebudget as tb  # noqa: E402
from fleet_analyser.parse import iso, parse_line  # noqa: E402

BASE = 1767225600
LAYOUT = {"0": dict(goals=[[99, 99]], shelves=[[98, 98]], pickers=set(), layout=dict(source="test"))}
SCRIPT_REDUCE = str(ROOT / "fleet" / "reduce.py")


def L(serial, h, t, order="o1", driving=False, x=0, y=0, faulted=False, theta=0.0, custom=None, mapid="m"):
    obj = {"schema_version": "fleet-state/2", "headerId": h, "timestamp": iso(BASE + t), "manufacturer": "sim",
           "serialNumber": serial, "orderId": order, "lastNodeId": f"{x}-{y}",
           "agvPosition": {"x": x, "y": y, "theta": theta, "mapId": mapid}, "driving": driving, "paused": False,
           "errors": [{"errorType": "BREAKDOWN", "errorLevel": "FATAL"}] if faulted else [], "loads": [],
           "nodeStates": []}
    if custom is not None:
        obj["custom"] = custom
    return (json.dumps(obj, separators=(",", ":")) + "\n").encode()


class Robot:
    """Builds one robot's lines: seg(t0, t1, **state) appends a line every 5 s in [t0, t1); a state value may be a function
    of t. Header ids count up per robot."""

    def __init__(self, serial, custom=None):
        self.serial, self.h, self.rows, self.custom = serial, 0, [], custom

    def seg(self, t0, t1, step=5, **st):
        for t in range(t0, t1, step):
            self.at(t, **st)
        return self

    def at(self, t, **st):
        kw = {k: (v(t) if callable(v) else v) for k, v in st.items()}
        self.h += 1
        self.rows.append((t, self.serial, self.h, kw))
        return self

    def lines(self, garbage=False):
        out = []
        for t, serial, h, kw in self.rows:
            c = None
            if self.custom is not None:
                c = {"stuck_count": 999, "junk": "g" * (h % 17 + 1), "carrying": None} if garbage else self.custom
            out.append((t, L(serial, h, t, custom=c, **kw)))
        return out


def write_gz(path, lines):
    with open(path, "wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as f:
        for ln in lines:
            f.write(ln)


def log_lines(robots, garbage=False):
    """All robots' lines in (ts, serial) order, as a zone file would carry them."""
    rows = [(t, r.serial, ln) for r in robots for t, ln in r.lines(garbage)]
    return [ln for _, _, ln in sorted(rows, key=lambda x: (x[0], x[1]))]


def scenario(custom=None):
    """A: moves, stops 100-150 at (10, 0) beside B (idle at (11, 0)), drives off with two identical lines after the ending
    line (155, 160) and moves on. C: unrelated mover that stops 20 s only."""
    a = Robot("Z0-01", custom)
    a.seg(0, 100, order="o1", driving=True, x=lambda t: t // 10, y=0)
    a.seg(100, 155, order="o1", driving=False, x=10, y=0)
    a.seg(155, 165, order="o1", driving=True, x=10, y=1)
    a.seg(165, 250, order="o1", driving=True, x=lambda t: 10 + (t - 160) // 5, y=1)
    b = Robot("Z0-02", custom)
    b.seg(0, 250, order="", driving=False, x=11, y=0)
    c = Robot("Z0-03", custom)
    c.seg(0, 60, order="o3", driving=True, x=lambda t: t // 5, y=5)
    c.seg(60, 80, order="o3", driving=False, x=12, y=5)
    c.seg(80, 250, order="o3", driving=True, x=lambda t: t // 5, y=5)
    return [a, b, c]


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def make(self, lines, name="zone0-000.jsonl.gz", sub="in"):
        d = self.tmp / sub
        d.mkdir(parents=True, exist_ok=True)
        write_gz(d / name, lines)
        return d / name

    def check(self, path, heartbeats=(60.0,), **kw):
        kw.setdefault("layouts", LAYOUT)
        return rc.check([str(path)], "t", heartbeats=heartbeats, **kw)

    @staticmethod
    def rung(doc, rule, h="60"):
        return doc["heartbeat"][h]["rungs"][rule]


class TestIdentityAndBytes(Base):
    def test_identity_and_ratio(self):
        # inject: make `all` drop the first line, or compute bytes_in_gzip from the emitter's .gz file size -> red
        lines = log_lines(scenario())
        p = self.make(lines)
        red = rd.Reducer([p])
        out = self.tmp / "all"
        red.write("all", out)
        self.assertEqual(rd.read_lines(out / p.name), lines)
        s = red.summary("all")
        self.assertEqual(s["ratio_gzip"], 1.0)
        self.assertEqual(s["line_ratio"], 1.0)
        doc = self.check(p)
        r0 = self.rung(doc, "all")
        self.assertTrue(r0["all_identical"])
        self.assertEqual(r0["ratio_gzip"], 1.0)
        self.assertNotIn("all", [doc["heartbeat"]["60"]["first_identical_rule"]])

    def test_every_output_line_is_the_input_line_at_its_source_index(self):
        # inject: strip or re-encode a kept line, or write kept lines in another order -> red
        lines = log_lines(scenario(custom={"stuck_count": 1}))
        p = self.make(lines)
        red = rd.Reducer([p])
        for rule in rd.RULES:
            for h in (30.0, 60.0):
                out = self.tmp / f"{rule}{int(h)}"
                kept = red.write(rule, out, h)
                got = rd.read_lines(out / p.name)
                src = [(li, raw) for li, raw in kept[0]]
                self.assertEqual(got, [raw for _, raw in src])
                for li, raw in src:
                    self.assertEqual(raw, lines[li])
                self.assertEqual([li for li, _ in src], sorted(li for li, _ in src))

    def test_rungs_are_nested(self):
        # inject: let R3 re-optimise the heartbeat so a gap-rung line is dropped again -> red
        p = self.make(log_lines(scenario()))
        red = rd.Reducer([p])
        for h in (30.0, 60.0):
            sets = [red.kept("all", h)] + [red.kept(r, h) for r in rd.RUNGS][::-1]
            for big, small in zip(sets, sets[1:]):
                self.assertLessEqual(small, big)

    def test_summary_keys_and_gzip_levels(self):
        p = self.make(log_lines(scenario()))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = rd.main(["--glob", str(p), "--rules", "gap", "--heartbeat-s", "30", "--out", str(self.tmp / "o")])
        self.assertEqual(code, 0)
        s = json.loads(buf.getvalue())
        for k in ("lines_in", "lines_kept", "bytes_in_raw", "bytes_kept_raw", "bytes_in_gzip", "bytes_kept_gzip",
                  "ratio_gzip", "line_ratio", "kept_lines_per_robot_hour", "lines_per_robot_hour_in", "kept_by_rule",
                  "added_by_rule"):
            self.assertIn(k, s)
        self.assertEqual(s["ratio_gzip"], s["bytes_in_gzip"] / s["bytes_kept_gzip"])
        self.assertEqual(s["line_ratio"], s["lines_in"] / s["lines_kept"])
        self.assertEqual(s["kept_by_rule"]["gap"], s["lines_kept"])
        self.assertEqual(sum(s["added_by_rule"].values()), s["lines_kept"])
        # robot-hours: 3 robots of 245 s each
        self.assertAlmostEqual(s["robot_hours"], 3 * 245 / 3600)
        self.assertAlmostEqual(s["lines_per_robot_hour_in"], s["lines_in"] / s["robot_hours"])

    def test_determinism(self):
        # inject: write the gzip with the default (wall clock) mtime or embed the file name -> red
        p = self.make(log_lines(scenario()))
        for rule in ("gap", "recovered"):
            outs = []
            for i in range(2):
                out = self.tmp / f"d{rule}{i}"
                with contextlib.redirect_stdout(io.StringIO()):
                    rd.main(["--glob", str(p), "--rules", rule, "--out", str(out)])
                outs.append((out / p.name).read_bytes())
            self.assertEqual(outs[0], outs[1])
            self.assertEqual(outs[0][4:8], b"\x00\x00\x00\x00")  # gzip header mtime

    def test_auto_servicing_bound_is_rejected(self):
        # inject: accept 'auto' (parse it as a bound) -> red
        p = self.make(log_lines(scenario()))
        args = ["--glob", str(p), "--rules", "all", "--out", str(self.tmp / "o"), "--servicing-max-s", "auto"]
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            rd.main(args)
        self.assertNotEqual(cm.exception.code, 0)
        proc = subprocess.run([sys.executable, SCRIPT_REDUCE] + args, capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("auto", proc.stderr)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            rc.main(["--glob", str(p), "--run", "t", "--out", str(self.tmp / "x.json"), "--servicing-max-s", "auto"])
        self.assertNotEqual(cm.exception.code, 0)
        self.assertFalse((self.tmp / "o").exists())

    def test_auto_stations_are_rejected(self):
        # inject: drop type=stations_path from --stations (and the Reducer guard) -> red
        p = self.make(log_lines(scenario()))
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            rd.main(["--glob", str(p), "--rules", "all", "--out", str(self.tmp / "o"), "--stations", "auto"])
        self.assertNotEqual(cm.exception.code, 0)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            rc.main(["--glob", str(p), "--run", "t", "--out", str(self.tmp / "x.json"), "--stations", "auto"])
        self.assertNotEqual(cm.exception.code, 0)
        with self.assertRaises(ValueError):
            rd.Reducer([str(p)], stations="auto")
        self.assertFalse((self.tmp / "o").exists())

    def test_out_of_order_input_stops_the_check(self):
        # inject: drop the n_out_of_order guard in reduce_check.check -> red (the comparison would run on two input views)
        p = self.make([L("r1", 1, 0), L("r1", 2, 0, x=1), L("r1", 3, 5, x=2)])
        with self.assertRaises(SystemExit) as cm:
            self.check(p)
        self.assertIn("out-of-order", str(cm.exception))


class TestCheckReportsDifferences(Base):
    def test_dropped_transition_is_a_diff(self):
        # inject: let compare() return "identical" for a missing item / drop the transitions output -> red
        r = Robot("Z0-01")
        r.seg(0, 40, driving=True, x=lambda t: t // 5)
        r.seg(40, 50, driving=False, x=8)  # a 10 s stop: two transitions (to STOPPED_WITH_ORDER and back)
        r.seg(50, 100, driving=True, x=lambda t: t // 5)
        lines = log_lines([r])
        p = self.make(lines)
        red = rd.Reducer([p])
        self.assertIn((0, 8), red.kept("change", 60.0))  # reduce keeps the stop line
        ctx = rc.Context([str(p)], "t", layouts=LAYOUT)
        full, _ = rc.analyse_dir(ctx, [str(p)])
        tampered = self.make([ln for i, ln in enumerate(lines) if i not in (8, 9)], sub="tampered")  # the stop
        got, _ = rc.analyse_dir(ctx, [str(tampered)])
        flags = {o: rc.compare(full[o], got[o]) for o in rc.OUTPUTS}
        self.assertIsInstance(flags["transitions"], dict)
        self.assertGreaterEqual(flags["transitions"]["count"], 1)
        self.assertEqual(flags["transitions"]["robots"], ["Z0-01"])
        self.assertFalse(rc.verdict_of(flags))
        self.assertEqual(flags["station_bound"], rc.NOT_APPLICABLE)

    def test_not_applicable_is_never_identical(self):
        self.assertEqual(rc.compare(None, {}), rc.NOT_APPLICABLE)
        self.assertFalse(rc.verdict_of({"a": rc.NOT_APPLICABLE}))
        self.assertFalse(rc.verdict_of({}))
        self.assertTrue(rc.verdict_of({"a": rc.NOT_APPLICABLE, "b": rc.IDENTICAL}))
        self.assertFalse(rc.verdict_of({"a": rc.IDENTICAL, "b": {"count": 1}}))
        d = rc.compare({("g", "r", "k"): dict(ts=5)}, {("g", "r", "k"): dict(ts=9)})
        self.assertEqual((d["count"], d["max_abs_diff_s"], d["robots"]), (1, 4, ["r"]))


class TestGap(Base):
    def test_gap_survives_as_gap_and_no_interval_longer_than_h(self):
        # inject: drop the "both ends of a source gap" step, or the heartbeat step -> red
        r = Robot("Z0-01")
        r.seg(0, 105, driving=False, order="", x=3)      # idle, one change-free stretch: lines 0..100
        r.seg(300, 345, driving=False, order="", x=3)    # a 195 s gap in the source (100 -> 300)
        r.seg(345, 400, driving=True, order="o1", x=lambda t: t // 5)
        r.at(445, driving=True, order="o1", x=89)         # a 45 s interval in the source (395 -> 445)
        r.seg(450, 500, driving=False, order="", x=3)
        lines = log_lines([r])
        p = self.make(lines)
        view = [m.ts - BASE for _, _, m in rd.Reducer([p]).groups["zone0"]["Z0-01"]]
        src_pairs = {(a, b) for a, b in zip(view, view[1:])}
        for h in (30.0, 60.0):
            red = rd.Reducer([p])
            kept = sorted(li for _, li in red.kept("gap", h))
            ts = [view[i] for i in kept]
            for a, b in zip(ts, ts[1:]):
                if b - a > h:
                    self.assertIn((a, b), src_pairs, f"H={h}: created interval {a}->{b}")
            self.assertIn((100, 300), list(zip(ts, ts[1:])))  # both ends kept and adjacent
            self.assertIn((395, 445), list(zip(ts, ts[1:])))
        doc = self.check(p, heartbeats=(30.0, 60.0))
        for h in ("30", "60"):
            self.assertEqual(self.rung(doc, "gap", h)["outputs"]["time_budget"], rc.IDENTICAL)
        # without the gap rule the 195 s gap becomes parked time: the budget differs
        self.assertNotEqual(self.rung(doc, "change")["outputs"]["time_budget"], rc.IDENTICAL)


    def test_source_gap_ends_are_kept_even_when_h_is_longer_than_the_gap_rule(self):
        # inject: drop the "both ends of every source interval longer than max_gap_s" step (H <= 60 hides it: the
        # heartbeat keeps both ends anyway, so this case uses H = 120) -> red
        r = Robot("Z0-01")
        r.seg(0, 105, driving=False, order="", x=3)
        r.seg(170, 275, driving=False, order="", x=3)  # a 70 s source interval (100 -> 170), longer than max_gap_s 60
        p = self.make(log_lines([r]))
        view = [m.ts - BASE for _, _, m in rd.Reducer([p]).groups["zone0"]["Z0-01"]]
        ts = [view[li] for _, li in sorted(rd.Reducer([p]).kept("gap", 120.0))]
        self.assertIn((100, 170), list(zip(ts, ts[1:])))


class TestRungs(Base):
    """Each fixture is all_identical at its rung and NOT at the rung below. Built for H = 60."""

    def rungs(self, robots, **kw):
        p = self.make(log_lines(robots))
        return self.check(p, heartbeats=(60.0,), **kw)

    def test_r3_a_stop_reduced_to_first_and_ending_line_opens_no_episode(self):
        # inject: drop the "first line at or after since + stuck_after" step of R3 -> red
        a = Robot("Z0-01")
        a.seg(0, 100, driving=True, x=lambda t: t // 10)
        a.seg(100, 155, driving=False, x=10)      # stop 100-150, ending line 155: kept 100 and 155 only under R2 (55 s < H)
        a.seg(155, 250, driving=True, x=lambda t: 10 + (t - 150) // 5)
        doc = self.rungs([a])
        gap, thr = self.rung(doc, "gap"), self.rung(doc, "threshold")
        self.assertNotEqual(gap["outputs"]["stall_list"], rc.IDENTICAL)
        self.assertFalse(gap["all_identical"])
        self.assertTrue(thr["all_identical"])
        self.assertEqual(doc["heartbeat"]["60"]["first_identical_rule"], "threshold")

    def test_r4_a_stationary_neighbour_vanishes_and_the_cause_becomes_unknown(self):
        # inject: drop the T_entry batch step of R4 -> red
        a = Robot("Z0-01")
        a.seg(0, 100, driving=True, x=lambda t: t // 10)
        a.seg(100, 155, driving=False, x=10)
        a.seg(155, 250, driving=True, x=lambda t: 10 + (t - 150) // 5)
        b = Robot("Z0-02")
        b.seg(0, 250, order="", driving=False, x=11)  # never changes: kept at 0, 60, 120, ... only (t_entry is 130)
        doc = self.rungs([a, b])
        thr, nb = self.rung(doc, "threshold"), self.rung(doc, "neighbours")
        self.assertNotEqual(thr["outputs"]["stall_list"], rc.IDENTICAL)
        self.assertEqual(thr["outputs"]["time_budget"], rc.IDENTICAL)
        self.assertFalse(thr["all_identical"])
        self.assertTrue(nb["all_identical"])
        self.assertEqual(doc["heartbeat"]["60"]["first_identical_rule"], "neighbours")

    def test_r5_the_transition_out_of_recovered_moves_under_r4(self):
        # inject: drop the "line after the ending line" step of R5 -> red
        a = Robot("Z0-01")
        a.seg(0, 100, driving=True, x=lambda t: t // 10)
        a.seg(100, 155, driving=False, x=10)
        a.seg(155, 165, driving=True, x=10, y=1)   # ending line 155 and an identical line 160, dropped by R1
        a.seg(165, 250, driving=True, x=lambda t: 10 + (t - 160) // 5, y=1)
        doc = self.rungs([a])
        nb, rec = self.rung(doc, "neighbours"), self.rung(doc, "recovered")
        self.assertNotEqual(nb["outputs"]["transitions"], rc.IDENTICAL)
        self.assertEqual(nb["outputs"]["stall_list"], rc.IDENTICAL)
        self.assertEqual(nb["outputs"]["time_budget"], rc.IDENTICAL)
        self.assertFalse(nb["all_identical"])
        self.assertTrue(rec["all_identical"])
        self.assertEqual(doc["heartbeat"]["60"]["first_identical_rule"], "recovered")

    def test_scenario_ladder(self):
        doc = self.rungs(scenario())
        h = doc["heartbeat"]["60"]
        self.assertEqual(h["first_identical_rule"], "recovered")
        self.assertEqual(h["verdict"], "identical")
        self.assertEqual(h["ratio_gzip_at_first_identical_rule"], h["rungs"]["recovered"]["ratio_gzip"])


class TestCustomIsNeverRead(Base):
    def test_garbage_custom_gives_the_same_kept_indices(self):
        # inject: let signature() / the Detector read custom, or decide on raw_len -> red
        base = scenario(custom={"stuck_count": 1, "carrying": False, "stuck_event": False})
        lines = log_lines(base)
        garbage = log_lines(base, garbage=True)
        self.assertNotEqual(lines, garbage)
        self.assertNotEqual([len(x) for x in lines], [len(x) for x in garbage])
        st = self.tmp / "stations.json"
        st.write_text(json.dumps({"stations": [[10, 0]], "shelves": []}))
        pa = self.make(lines, sub="a")
        pb = self.make(garbage, sub="b")
        for kw in (dict(), dict(stations=str(st), station_radius=1, servicing_max_s=40.0)):
            ra, rb = rd.Reducer([pa], **kw), rd.Reducer([pb], **kw)
            for rule in rd.RULES:
                for h in (30.0, 60.0):
                    self.assertEqual(ra.kept(rule, h), rb.kept(rule, h), f"{rule} H={h} {kw}")
        self.assertNotEqual(rd.Reducer([pa]).kept("change", 60.0), rd.Reducer([pa]).kept("all", 60.0))


class TestStations(Base):
    def fixture(self):
        a = Robot("Z0-01")
        a.seg(0, 100, driving=True, x=lambda t: t // 20, y=0)
        a.seg(100, 200, driving=False, x=10, y=0)   # a 100 s stop ON the station cell (10, 0)
        a.seg(200, 300, driving=True, x=lambda t: 10 + (t - 195) // 5, y=1)
        b = Robot("Z0-02")
        b.seg(0, 300, order="", driving=False, x=11)
        st = self.tmp / "stations.json"
        st.write_text(json.dumps({"stations": [[10, 0]], "shelves": [[40, 40]]}))
        return self.make(log_lines([a, b])), st

    def test_stations_reach_the_in_reducer_detector(self):
        # inject: build the in-reducer Detector without stations / servicing_max_s -> red
        p, st = self.fixture()
        plain = rd.Reducer([p])
        aware = rd.Reducer([p], stations=str(st), station_radius=0)
        self.assertNotEqual(plain.kept("neighbours", 60.0), aware.kept("neighbours", 60.0))
        self.assertEqual(aware.kept("neighbours", 60.0), aware.kept("threshold", 60.0))  # SERVICING: no episode, no batch
        bounded = rd.Reducer([p], stations=str(st), station_radius=0, servicing_max_s=60.0)
        self.assertNotEqual(bounded.kept("neighbours", 60.0), aware.kept("neighbours", 60.0))  # overrun episode at 160
        # the CLI passes the same three
        counts = {}
        for name, extra in (("plain", []), ("aware", ["--stations", str(st), "--station-radius", "0"])):
            out = self.tmp / name
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rd.main(["--glob", str(p), "--rules", "neighbours", "--out", str(out)] + extra)
            counts[name] = json.loads(buf.getvalue())["lines_kept"]
        self.assertGreater(counts["plain"], counts["aware"])

    def test_station_aware_check_reports_station_bound_outputs(self):
        p, st = self.fixture()
        doc = rc.check([str(p)], "t", stations=str(st), station_radius=0, servicing_max_s=60.0, heartbeats=(60.0,))
        self.assertTrue(doc["applicable"]["station_bound"])
        self.assertEqual(doc["args"]["servicing_max_s"], 60.0)
        self.assertEqual(doc["args"]["stations"], str(st))
        self.assertEqual(doc["args"]["station_radius"], 0)
        self.assertNotEqual(self.rung(doc, "all")["outputs"]["station_bound"], rc.NOT_APPLICABLE)
        plain = self.check(p)
        self.assertFalse(plain["applicable"]["station_bound"])
        self.assertIsNone(plain["args"]["servicing_max_s"])
        self.assertIsNone(plain["args"]["stations"])


class TestReindexing(Base):
    """A MoRoOp-shaped shift: one robot without zone prefix, theta changes on every line while it moves or is stopped away
    from the station, constant while it idles at the station. `change` drops the idle lines before the compared episodes,
    so every kept index after them shifts; the S15A rows and the label hits must agree by timestamp."""

    def fixture(self):
        r = Robot("moroop-amr-1")
        r.seg(0, 300, order="", driving=False, x=2, y=0, theta=0.5)                       # idle at the station
        r.seg(300, 400, order="o1", driving=True, x=lambda t: (t - 300) // 5, y=0, theta=lambda t: t * 1e-3)
        r.seg(400, 1300, order="o1", driving=False, x=20, y=0, theta=lambda t: t * 1e-4)   # one 900 s stop, theta jitters
        r.seg(1300, 1400, order="o1", driving=True, x=lambda t: 20 + (t - 1300) // 5, y=0, theta=lambda t: t * 1e-3)
        p = self.make(log_lines([r]))
        st = self.tmp / "stations-sf.json"
        st.write_text(json.dumps({"stations": [[2, 0]], "shelves": []}))
        rows = [dict(id=i, created_at=(BASE + t) * 1_000_000, stuck_reason="BLOCKED" if 410 <= t < 470 else None)
                for i, t in enumerate(range(0, 1400, 5))]
        native = {"robot_state_cleaned": rows, "operations": []}
        return p, st, native

    def test_s15a_rows_and_label_hits_equal_by_timestamp(self):
        # inject: compare the kept indices a / b of stall_baseline episodes instead of timestamps -> red
        p, st, native = self.fixture()
        ctx = rc.Context([str(p)], "t", stations=str(st), station_radius=1, servicing_max_s=300.0, moroop_raw="unused")
        ctx._natives[0] = native
        full, _ = rc.analyse_dir(ctx, [str(p)])
        self.assertTrue(any(k[2] == "N2-30" for k in full["s15a_rules"]))
        self.assertTrue(any(k[2] == "sf" and k[3] == "label0" for k in full["label_hits"]))
        red = rd.Reducer([p], str(st), 1, 300.0)
        out = self.tmp / "change"
        red.write("change", out)
        self.assertLess(len(rd.read_lines(out / p.name)), len(rd.read_lines(p)) - 40)  # the idle lines are gone
        got, _ = rc.analyse_dir(ctx, [str(out / p.name)])
        self.assertEqual(rc.compare(full["s15a_rules"], got["s15a_rules"]), rc.IDENTICAL)
        self.assertEqual(rc.compare(full["label_hits"], got["label_hits"]), rc.IDENTICAL)
        # the kept indices DO shift: a naive index comparison would have called this a difference
        mf = tb.kept_messages([parse_line(x)[0] for x in rd.read_lines(p)])
        mr = tb.kept_messages([parse_line(x)[0] for x in rd.read_lines(out / p.name)])
        ef = sb.position_rule_episodes(mf, "N2-30", sb.MOROOP_CELL_M)
        er = sb.position_rule_episodes(mr, "N2-30", sb.MOROOP_CELL_M)
        self.assertEqual([(e["start"], e["alert"], e["end"]) for e in ef], [(e["start"], e["alert"], e["end"]) for e in er])
        self.assertNotEqual([(e["a"], e["b"]) for e in ef], [(e["a"], e["b"]) for e in er])
        self.assertEqual(full["label_hits"][("zone0", "-", "sf", "counts")]["hits"], 1)


if __name__ == "__main__":
    unittest.main()

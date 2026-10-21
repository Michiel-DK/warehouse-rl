"""S14A station time bound: Detector(servicing_max_s=), the auto bound, --servicing-max-s on ingest / timebudget / deadlock /
moroop, the cause_label map and the causes tables. Hand-made streams use a message every 10 s, so a "60 s stop" is stopped at
0..50 s and driving again at 60 s (the ending message is the 60 s one). Each case names its red demonstration in an
`# inject:` comment."""
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "fleet", ROOT / "src", ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import _platform  # noqa: E402
import timebudget as tb  # noqa: E402
from fleet_analyser import causes, ingest as ingest_mod, servicing, store as store_mod  # noqa: E402
from fleet_analyser.detector import CAUSE_LABELS, SERVICING, STUCK, Detector  # noqa: E402
from fleet_analyser.hotspot import read_messages  # noqa: E402
from fleet_analyser.parse import Message, parse_line  # noqa: E402
from fleet_analyser.stations import load_stations  # noqa: E402

from fleet.tests.test_fleet_detector_stations import find_file  # noqa: E402
from fleet.tests.test_fleet_timebudget import BASE as TB_BASE  # noqa: E402

BASE = 1767225600
ST = {(3, 4)}


def M(step, order="o1", driving=False, x=3, y=4, faulted=False, serial="Z0-00", zone="0"):
    return Message(serial=serial, zone=zone, header_id=step, ts=BASE + 10 * step, order_id=order, x=x, y=y,
                   driving=driving, faulted=faulted, loaded=False, raw_len=1)


def stop(seconds, first=0, **kw):
    """Stopped at the station for `seconds`: stopped messages at first.. (seconds/10 - 1), then a driving message that ends it."""
    n = seconds // 10
    return [M(first + k, **kw) for k in range(n)] + [M(first + n, driving=True, x=9, y=9)]


def feed(msgs, **kw):
    det = Detector(**kw)
    ev = []
    for m in sorted(msgs, key=lambda m: m.ts):
        ev.extend(det.feed(m))
    ev.extend(det.end_all())
    return ev, det


def kinds(ev, kind):
    return [e for e in ev if e["kind"] == kind]


def to(ev, state):
    return [e for e in ev if e["kind"] == "transition" and e["to_state"] == state]


class TestBoundedStop(unittest.TestCase):
    def test_a_90s_stop_bound_60_opens_at_60_with_start_at_the_stop(self):
        # inject: open the episode at stop + 30 (stuck_after) or set start = t_entry
        ev, det = feed(stop(90), stations=ST, servicing_max_s=60)
        self.assertEqual([e["ts"] for e in to(ev, SERVICING)], [BASE + 30])
        (op,) = kinds(ev, "episode_open")
        self.assertEqual((op["t_entry"], op["start"], op["cause"], op["servicing_s"], op["blocker"],
                          op["blocker_faulted_s"]), (BASE + 60, BASE, "station_overrun", 60, None, None))
        self.assertEqual([e["ts"] for e in to(ev, STUCK)], [BASE + 60])
        (cl,) = kinds(ev, "episode_close")
        self.assertEqual((cl["end"], cl["duration_s"], cl["resolution"], cl["cause"]), (BASE + 90, 90, "moved", "station_overrun"))
        self.assertEqual((det.servicing_runs, det.station_overruns), (1, 1))

    def test_b_same_stream_without_a_bound_opens_nothing_and_adds_no_keys(self):
        # inject: let the Detector write servicing_s (or any new key) when the bound is None
        ev, det = feed(stop(90), stations=ST)
        self.assertEqual(kinds(ev, "episode_open") + kinds(ev, "episode_close"), [])
        self.assertEqual((det.servicing_runs, det.station_overruns), (1, 0))
        plain, _ = feed(stop(90), stations=ST, servicing_max_s=None)
        self.assertEqual(plain, ev)
        # servicing_s only on overrun episodes: a stuck episode off the station never has the key
        off, _ = feed(stop(90), stations={(9, 9)}, servicing_max_s=60)
        self.assertEqual(len(kinds(off, "episode_open")), 1)
        self.assertTrue(all("servicing_s" not in e for e in off))

    def test_c_exactly_at_the_bound_and_below_it_open_nothing(self):
        # inject: compare with >= on the END message instead of on a still-stopped observation
        for secs in (50, 60):
            ev, det = feed(stop(secs), stations=ST, servicing_max_s=60)
            self.assertEqual(kinds(ev, "episode_open"), [], secs)
            self.assertEqual(det.station_overruns, 0, secs)
        ev, _ = feed(stop(70), stations=ST, servicing_max_s=60)
        self.assertEqual(len(kinds(ev, "episode_open")), 1)

    def test_d_faulted_during_servicing_opens_faulted_self_as_today(self):
        # inject: let the overrun branch run before the faulted check, or open a second episode at the bound
        msgs = [M(k, faulted=k >= 4) for k in range(9)] + [M(9, driving=True, x=9, y=9)]
        ev, det = feed(msgs, stations=ST, servicing_max_s=60)
        (op,) = kinds(ev, "episode_open")
        self.assertEqual((op["cause"], op["t_entry"], op["start"]), ("faulted_self", BASE + 40, BASE))
        self.assertNotIn("servicing_s", op)
        self.assertEqual(det.station_overruns, 0)
        none, _ = feed(msgs, stations=ST)
        self.assertEqual(kinds(ev, "episode_open"), kinds(none, "episode_open"))

    def test_e_faulted_after_the_overrun_keeps_the_open_episode(self):
        # inject: re-decide the cause at the faulted message, or reopen a second episode when the fault clears
        msgs = [M(k, faulted=k in (8, 9)) for k in range(12)] + [M(12, driving=True, x=9, y=9)]
        ev, det = feed(msgs, stations=ST, servicing_max_s=60)
        self.assertEqual(len(kinds(ev, "episode_open")), 1)
        (cl,) = kinds(ev, "episode_close")
        self.assertEqual(cl["cause"], "station_overrun")
        self.assertEqual([e["ts"] for e in to(ev, "FAULTED")], [BASE + 80])
        self.assertEqual([e["ts"] for e in to(ev, STUCK)], [BASE + 60, BASE + 100])
        self.assertEqual(det.station_overruns, 1)

    def test_f_neighbour_of_an_overrun_is_blocked_by_stuck(self):
        # inject: leave the overrun robot in SERVICING so the neighbour reads traffic
        msgs = stop(150) + [M(k, serial="Z0-01", x=4, y=4, order="o2") for k in range(6, 14)] + \
            [M(14, serial="Z0-01", x=4, y=4, order="o2", driving=True)]  # its episode opens at 90 s, after the conversion at 60 s
        ev, _ = feed(msgs, stations=ST, servicing_max_s=60)
        nb = [e for e in kinds(ev, "episode_open") if e["robot"] == "Z0-01"]
        self.assertEqual([(e["cause"], e["blocker"]) for e in nb], [("blocked_by_stuck", "Z0-00")])


def station_stops(durations, zone="0", serial="Z0-00"):
    """One robot, stops at the station of the given lengths (ending message = driving elsewhere), 20 s apart."""
    msgs, step = [], 0
    for d in durations:
        msgs += [M(step + k, serial=serial, zone=zone) for k in range(d // 10)]
        step += d // 10
        msgs.append(M(step, driving=True, x=9, y=9, serial=serial, zone=zone))
        step += 2
        msgs.append(M(step - 1, driving=True, x=9, y=8, serial=serial, zone=zone))
    return msgs


def hand_t(dwells):
    """Expected auto bound, written out: type-7 positions (n - 1) * p on ln(dwell)."""
    logs = sorted(math.log(d) for d in dwells)
    n = len(logs)

    def q(p):
        h = (n - 1) * p
        lo = int(h)
        return logs[lo] + (h - lo) * (logs[min(lo + 1, n - 1)] - logs[lo])

    q1, q3 = q(0.25), q(0.75)
    return min(300.0, math.exp(q3 + 3 * (q3 - q1))), math.exp(q1), math.exp(q3)


class TestAutoBound(unittest.TestCase):
    def test_g_five_stops_20_to_600_give_231_48_and_only_the_600_converts(self):
        # inject: drop the 20 s stop from the sample (left truncation) or use raw-space quartiles
        msgs = station_stops([20, 30, 40, 50, 600])
        stats = servicing.resolve("auto", msgs, ST, 0)
        self.assertAlmostEqual(stats["servicing_max_s"], 231.48, delta=0.1)
        self.assertEqual(stats["servicing_sample_n"], 5)
        self.assertAlmostEqual(stats["servicing_q1_s"], 30, places=6)
        self.assertAlmostEqual(stats["servicing_q3_s"], 50, places=6)
        ev, det = feed(msgs, stations=ST, servicing_max_s=stats["servicing_max_s"])
        (op,) = kinds(ev, "episode_open")
        self.assertEqual(op["start"], BASE + 10 * (2 + 2 + 3 + 2 + 4 + 2 + 5 + 2))  # the 600 s stop starts after four stops
        (cl,) = kinds(ev, "episode_close")
        self.assertEqual(cl["duration_s"], 600)
        self.assertEqual(det.station_overruns, 1)

    def test_h_six_stops_use_log_space_quartiles(self):
        # inject: interpolate the quartiles of the raw dwells instead of their logs (gives 182.07 here)
        dwells = [20, 30, 40, 50, 50, 60]
        stats = servicing.resolve("auto", station_stops(dwells), ST, 0)
        want, q1, q3 = hand_t(dwells)
        self.assertAlmostEqual(want, 186.557, places=2)  # by hand: Q1 = 30 (4/3)^0.25, Q3 = 50, T = 50 (50 / Q1)^3
        self.assertAlmostEqual(stats["servicing_max_s"], want, places=6)
        self.assertAlmostEqual(stats["servicing_q1_s"], 30 * (4 / 3) ** 0.25, places=6)
        self.assertAlmostEqual(stats["servicing_q3_s"], 50, places=6)
        self.assertGreater(abs(stats["servicing_max_s"] - 182.07), 4)  # raw-space interpolation would differ

    def test_i_fewer_than_five_stops_give_300_and_a_number_is_used_as_given(self):
        # inject: compute the bound from n < 5 stops
        stats = servicing.resolve("auto", station_stops([20, 30, 40, 50]), ST, 0)
        self.assertEqual((stats["servicing_max_s"], stats["servicing_sample_n"]), (300.0, 4))
        self.assertIsNotNone(stats["servicing_q1_s"])
        given = servicing.resolve(45, station_stops([20, 30, 40, 50]), ST, 0)
        self.assertEqual((given["servicing_max_s"], given["servicing_sample_n"]), (45.0, 4))
        none = servicing.resolve("auto", [], ST, 0)
        self.assertEqual((none["servicing_max_s"], none["servicing_sample_n"], none["servicing_q1_s"]), (300.0, 0, None))

    def test_j_only_stops_starting_at_a_station_count_and_any_length(self):
        # inject: sample SERVICING runs only (>= 30 s) or every stop
        on = station_stops([10, 20, 30])
        off = [Message(serial="Z0-01", zone="0", header_id=k, ts=BASE + 10 * k, order_id="o9", x=7, y=7, driving=False,
                       faulted=False, loaded=False, raw_len=1) for k in range(6)]
        self.assertEqual(servicing.dwell_sample(on + off, ST, 0), [10, 20, 30])
        self.assertEqual(servicing.dwell_sample(on + off, ST, 0), servicing.dwell_sample(on, ST, 0))

    def test_k_sample_runs_equal_timebudget_runs(self):
        # inject: let servicing._kept keep a message that timebudget drops (equal ts)
        msgs = station_stops([20, 30, 40, 50, 600])
        kept = tb.kept_messages(msgs)
        runs, _ = tb.stopped_runs(kept)
        want = sorted(kept[b + 1].ts - kept[a].ts for a, b in runs)
        self.assertEqual(servicing.dwell_sample(msgs, ST, 0), want)

    def test_parse_spec(self):
        self.assertEqual(servicing.parse_spec("auto"), "auto")
        self.assertEqual(servicing.parse_spec("60"), 60.0)
        for bad in ("0", "-5", "x", "inf", "nan"):
            with self.assertRaises(ValueError):
                servicing.parse_spec(bad)


class TestTimebudgetPartition(unittest.TestCase):
    def budget(self, msgs, radius=0, bound=None, stations=ST):
        kept = tb.kept_messages(msgs)
        rec, starts = tb.robot_budget(kept, stations, set(), 3600, rule_radius=radius, servicing_max_s=bound)
        return rec, starts, kept

    def stream(self):
        return [M(0, driving=True, x=1, y=1), M(1, driving=True, x=2, y=2)] + stop(90, first=2) + \
            [M(13, driving=True, x=8, y=8)]

    def test_l_overrun_stop_is_all_stuck_and_the_buckets_still_partition(self):
        # inject: leave the exact-cell waiting_station branch ahead of the overrun branch
        msgs = self.stream()
        rec, starts, kept = self.budget(msgs, bound=60)
        span = kept[-1].ts - kept[0].ts
        self.assertEqual(sum(rec["seconds"].values()), span)  # check_bucket_sum would already have raised
        self.assertEqual((rec["seconds"]["stuck"], rec["seconds"]["waiting_station"]), (90, 0))
        ep = [e for e in tb.recompute_episodes(msgs, ST, 0, 60) if e["cause"] == "station_overrun"]
        self.assertEqual([e["duration_s"] for e in ep], [rec["seconds"]["stuck"]])
        self.assertEqual(starts, {(e["robot"], e["start"]) for e in ep})

    def test_m_a_stop_that_did_not_convert_is_waiting_station_whatever_the_cell(self):
        # inject: only count the exact station cell as waiting_station when the flag is given
        msgs = [M(0, driving=True, x=1, y=1)] + stop(90, first=1, x=3, y=5) + [M(12, driving=True, x=8, y=8)]
        rec0, _, _ = self.budget(msgs, radius=1)  # without the flag: off the exact cell = stopped_short
        self.assertEqual((rec0["seconds"]["stopped_short"], rec0["seconds"]["waiting_station"]), (90, 0))
        rec, _, _ = self.budget(msgs, radius=1, bound=500)
        self.assertEqual((rec["seconds"]["waiting_station"], rec["seconds"]["stopped_short"], rec["seconds"]["stuck"]),
                         (90, 0, 0))
        rec2, starts2, _ = self.budget(msgs, radius=1, bound=60)
        self.assertEqual((rec2["seconds"]["stuck"], rec2["seconds"]["waiting_station"], rec2["seconds"]["stopped_short"]),
                         (90, 0, 0))
        self.assertEqual(len(starts2), 1)

    def test_n_flag_absent_changes_no_bucket(self):
        # inject: let robot_budget read the exact-cell rule differently when servicing_max_s is None
        msgs = self.stream()
        a, _, _ = self.budget(msgs, radius=0)
        self.assertEqual((a["seconds"]["waiting_station"], a["seconds"]["stuck"]), (90, 0))
        b, _, _ = self.budget(msgs, radius=0, bound=None)
        self.assertEqual(a, b)

    def test_o_a_faulted_station_stop_is_not_an_overrun_in_the_budget_either(self):
        # inject: mark a run overrun although a fault opened its episode first
        msgs = [M(0, driving=True, x=1, y=1)] + [M(k, faulted=k >= 5) for k in range(1, 12)] + [M(12, driving=True, x=8, y=8)]
        ev = tb.recompute_episodes(msgs, ST, 0, 60)
        rec, starts, kept = self.budget(msgs, radius=0, bound=60)
        self.assertEqual([e["cause"] for e in ev], ["faulted_self"])
        self.assertFalse(tb.run_overruns(kept, (1, 11), 60))
        self.assertEqual((starts, rec["seconds"]["stuck"]), (set(), 0))  # as in S13B: the fault seconds are faulted


class TestCausesTable(unittest.TestCase):
    def test_p_order_is_seconds_desc_then_cause_key_asc(self):
        # inject: sort by episodes, or by cause key first
        eps = [dict(cause="traffic", duration_s=100), dict(cause="unknown", duration_s=100), dict(cause="blocked_by_stuck", duration_s=30),
               dict(cause="blocked_by_stuck", duration_s=30), dict(cause="station_overrun", duration_s=600),
               dict(cause="faulted_self", duration_s=None)]
        rows = causes.causes_table(eps)
        self.assertEqual([(r["cause"], r["episodes"], r["seconds"]) for r in rows],
                         [("station_overrun", 1, 600), ("traffic", 1, 100), ("unknown", 1, 100), ("blocked_by_stuck", 2, 60)])
        self.assertEqual([r["cause_label"] for r in rows], [CAUSE_LABELS[r["cause"]] for r in rows])
        block = causes.causes_block(eps, 1000)
        self.assertEqual((block["episode_seconds"], block["uncounted_open_episodes"], block["share_total"]), (860, 1, 0.86))
        self.assertEqual(block["table"][0]["share"], 0.6)
        self.assertIsNone(causes.causes_block(eps, 0)["table"][0]["share"])

    def test_q_timebudget_output_carries_the_table_per_robot_zone_and_run(self):
        # inject: build the table from the wrong robot's episodes
        msgs = TestTimebudgetPartition().stream()
        eps = tb.recompute_episodes(msgs, ST, 0, 60)
        layouts = {"0": dict(goals=[[3, 4]], shelves=[], pickers=set(), layout={})}
        zones, run = tb.compute(msgs, "r", layouts, eps, "recomputed", 3600, station_radius=0, servicing_max_s=60)
        robot = zones["0"]["robots"]["Z0-00"]["causes"]
        self.assertEqual([(r["cause"], r["seconds"], r["share"]) for r in robot["table"]], [("station_overrun", 90, 1.0)])
        self.assertEqual(zones["0"]["totals"]["causes"]["table"], robot["table"])
        self.assertEqual(run["totals"]["causes"]["table"], robot["table"])
        self.assertEqual(robot["table"][0]["cause_label"], "Station stop over time limit")


class TestLabels(unittest.TestCase):
    def test_r_label_map_is_the_six_entry_table(self):
        # inject: reword a label or drop a cause
        self.assertEqual(CAUSE_LABELS, {
            "faulted_self": "Robot fault", "blocked_by_faulted": "Blocked by a faulted robot",
            "blocked_by_stuck": "Blocked by a stuck robot", "traffic": "Traffic wait",
            "unknown": "Stopped, cause not identified", "station_overrun": "Station stop over time limit"})

    def test_s_every_episode_row_of_the_ingested_s10_none_zone0_store_has_the_label(self):
        # inject: attach the label only on episode_open rows, or in the Detector
        src = find_file("fleet", "data", "s10-none", "zone0-000.jsonl.gz")
        if src is None:
            self.skipTest("fleet/data/s10-none absent in this checkout and the main one")
        with tempfile.TemporaryDirectory() as d:
            os.symlink(src, os.path.join(d, "zone0-000.jsonl.gz"))  # no emit_ledger.json: nothing listed, nothing missing
            st = store_mod.MemoryStore()
            ing = ingest_mod.Ingester(os.path.join(d, "*.jsonl.gz"), "r", st, once=True)
            ing.run_loop()
        rows = st.select("stuck_episodes", {"run": "r"})
        closed = [r for r in rows if r["resolution"] != "open"]
        self.assertGreater(len(closed), 10)
        for r in rows:
            self.assertEqual(r["cause_label"], CAUSE_LABELS[r["cause"]])
            self.assertNotIn("servicing_s", r)
        self.assertNotIn("servicing_max_s", st.select("ingest_runs", {"run": "r"})[0])


def event_stream_sha(path, stations, **kw):
    det = Detector(stations=stations, station_radius=0, **kw)
    evs = []
    for m in read_messages(str(path)):
        evs.extend(det.feed(m))
    evs.extend(det.end_all())
    assert all("servicing_s" not in e for e in evs)
    return hashlib.sha256("\n".join(json.dumps(e, sort_keys=True) for e in evs).encode()).hexdigest()


class TestByteIdentity(unittest.TestCase):
    def test_t_bound_absent_event_stream_equals_master_on_s10_none_zone0_stations_auto(self):
        # inject: let Detector add a key to its events or change a station-less/bound-less run's state
        want = _platform.expected("fleet_stream", "s14a_s10_none_zone0_stations_auto_event_sha256")
        path = find_file("fleet", "data", "s10-none", "zone0-000.jsonl.gz")
        if path is None or not (path.parent / "emit_ledger.json").is_file():
            self.skipTest("fleet/data/s10-none (with emit_ledger.json) absent in this checkout and the main one")
        stations = load_stations("auto", str(path.parent))
        self.assertEqual(event_stream_sha(path, stations), want)
        self.assertEqual(event_stream_sha(path, stations, servicing_max_s=None), want)


class TestCli(unittest.TestCase):
    def setUp(self):
        from fleet.tests.test_fleet_timebudget import line, write_gz

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = self.d = Path(self.tmp.name)
        # A: stopped 120 s on the station (ends at the end of input); B: stopped 40 s off it; both with an order
        lines = [line("Z0-00", k, "a1", False, 3, 4) for k in range(25)] + [line("Z0-01", k, "b1", False, 7, 7) for k in range(9)]
        write_gz(d / "zone0-000.jsonl.gz", lines)
        (d / "stations.json").write_text(json.dumps({"stations": [[3, 4]], "shelves": []}))
        self.glob = str(d / "*.jsonl.gz")

    def run_py(self, script, *args, ok=True):
        r = subprocess.run([sys.executable, str(ROOT / "fleet" / script), *map(str, args)], capture_output=True, text=True)
        if ok:
            self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def ingest(self, name, *extra):
        self.run_py("ingest.py", "--glob", self.glob, "--run", "r", "--stations", self.d / "stations.json", "--store",
                    f"jsonl:{self.d / name}", "--once", *extra)
        rows = [json.loads(x) for x in (self.d / name / "stuck_episodes.jsonl").read_text().splitlines()]
        run = json.loads((self.d / name / "ingest_runs.jsonl").read_text().splitlines()[-1])
        return {r["robot"]: r for r in rows}, run

    def test_u_ingest_flag_converts_and_writes_the_ledger_keys_only_with_the_flag(self):
        # inject: write the keys without the flag, or forget station_overruns
        eps0, run0 = self.ingest("plain")
        self.assertEqual(set(eps0), {"Z0-01"})
        for k in ("servicing_max_s", "servicing_sample_n", "servicing_q1_s", "servicing_q3_s", "station_overruns"):
            self.assertNotIn(k, run0)
        eps, run = self.ingest("sb", "--servicing-max-s", "60")
        self.assertEqual(set(eps), {"Z0-00", "Z0-01"})
        self.assertEqual((eps["Z0-00"]["cause"], eps["Z0-00"]["servicing_s"], eps["Z0-00"]["start"]),
                         ("station_overrun", 60, TB_BASE))
        self.assertEqual(eps["Z0-00"]["cause_label"], "Station stop over time limit")
        self.assertNotIn("servicing_s", eps["Z0-01"])
        self.assertEqual((run["servicing_max_s"], run["station_overruns"], run["servicing_runs"]), (60.0, 1, 1))
        self.assertIn("servicing_sample_n", run)
        _, auto = self.ingest("auto", "--servicing-max-s", "auto")
        self.assertEqual(auto["servicing_sample_n"], 1)  # one station stop; fewer than 5 -> 300 s
        self.assertEqual((auto["servicing_max_s"], auto["station_overruns"]), (300.0, 0))

    def test_v_timebudget_and_deadlock_flags(self):
        # inject: accept --servicing-max-s without --station-aware, or omit the keys from the result file
        out = self.d / "t.json"
        base = ["--glob", self.glob, "--run", "r", "--stations", self.d / "stations.json", "--store", f"jsonl:{self.d / 'none'}"]
        self.run_py("timebudget.py", *base, "--out", out)
        plain = json.loads(out.read_text())
        self.assertNotIn("servicing_max_s", plain)
        r = self.run_py("timebudget.py", *base, "--servicing-max-s", "60", "--out", out, ok=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--station-aware", r.stderr)
        self.run_py("timebudget.py", *base, "--station-aware", "--servicing-max-s", "60", "--out", out)
        doc = json.loads(out.read_text())
        self.assertEqual(doc["servicing_max_s"], 60.0)
        for k in ("servicing_sample_n", "servicing_q1_s", "servicing_q3_s", "servicing_pooling"):
            self.assertIn(k, doc)
        a = doc["zones"]["0"]["robots"]["Z0-00"]
        self.assertEqual((a["seconds"]["stuck"], a["seconds"]["waiting_station"]), (120, 0))
        self.assertEqual(doc["zones"]["0"]["robots"]["Z0-00"]["causes"]["table"][0]["cause"], "station_overrun")
        self.assertEqual(doc["run"]["stuck_runs_vs_detector"]["start_sets_equal"], True)
        dl = self.d / "dl.json"
        self.run_py("deadlock.py", "--glob", self.glob, "--run", "r", "--out", dl)
        self.assertNotIn("servicing_max_s", json.loads(dl.read_text()))
        self.assertNotEqual(self.run_py("deadlock.py", "--glob", self.glob, "--run", "r", "--out", dl,
                                        "--servicing-max-s", "60", ok=False).returncode, 0)
        self.run_py("deadlock.py", "--glob", self.glob, "--run", "r", "--out", dl, "--stations", self.d / "stations.json",
                    "--servicing-max-s", "auto")
        d = json.loads(dl.read_text())
        self.assertEqual((d["servicing_max_s"], d["servicing_sample_n"]), (300.0, 1))
        self.assertIn("servicing_q3_s", d)

    def test_w_report_causes_section(self):
        # inject: drop the causes section or its ordering
        self.ingest("sb", "--servicing-max-s", "60")
        self.run_py("report.py", "--run", "r", "--store", f"jsonl:{self.d / 'sb'}", "--out", self.d / "rep" / "report.md")
        text = (self.d / "rep" / "report.md").read_text()
        self.assertIn("## Causes (episode seconds", text)
        self.assertIn("- Station stop over time limit (station_overrun): 1 episodes, 120 s, share n/a", text)
        self.assertIn("### Z0-00", text)


RAW = find_file("fleet", "data", "moroop", "raw")
STATIONS = ROOT / "fleet" / "data" / "moroop" / "stations.json"
try:
    import pyarrow  # noqa: F401
    HAVE_PYARROW = True
except ImportError:
    HAVE_PYARROW = False


@unittest.skipUnless(RAW is not None and (RAW / "data").is_dir() and HAVE_PYARROW, "MoRoOp raw dir or pyarrow absent")
class TestMoroopSmoke(unittest.TestCase):
    def test_x_station_overruns_on_the_nine_shifts(self):
        # inject: ignore servicing_max_s in moroop.run_intervals / second_buckets
        from adapters import moroop as mo

        stations_json = json.loads(STATIONS.read_text())["stations"]
        stations, near, _ = tb.cell_sets(stations_json, [])
        tot = dict(overruns=0, timeouts=0, timeouts_overlapped_by_run=0, timeouts_overlapped_by_run_before=0, timeouts_overlapped_by_overrun=0, false_alarms=0,
                   station_cell_unlabelled=0, unlabelled_before=0)
        lines = []
        for k, name in enumerate(mo.SHIFTS):
            d = mo.load_shift(RAW, name)
            msgs, _aux, _stats = mo.convert_shift(d["robot_state_cleaned"], d["operations"], d["jobs"])
            parsed = [parse_line(mo.encode_line(m))[0] for m in msgs]
            kept = tb.kept_messages(parsed)
            sv = servicing.resolve("auto", parsed, stations, 1)
            T = sv["servicing_max_s"]
            buckets = mo.second_buckets(kept, stations, near, tb, radius=1, servicing_max_s=T)
            base_buckets = mo.second_buckets(kept, stations, near, tb, radius=1)
            rec = tb.robot_budget(kept, stations, near, 3600, rule_radius=1, servicing_max_s=T)[0]
            self.assertEqual(sum(rec["seconds"].values()), kept[-1].ts - kept[0].ts)
            self.assertEqual({b: buckets.count(b) for b in tb.BUCKETS}, rec["seconds"])
            lab0 = mo.label_comparison(d["robot_state_cleaned"], kept, base_buckets, d["operations"], stations, tb, 1)
            lab = mo.label_comparison(d["robot_state_cleaned"], kept, buckets, d["operations"], stations, tb, 1, T)
            eps = lab.pop("_episodes")
            lab0.pop("_episodes")
            self.assertEqual(lab["causes"]["episode_seconds"], sum(e["duration_s"] for e in eps if e["duration_s"] is not None))
            tot["overruns"] += len(lab["overruns"])
            tot["timeouts"] += lab["timeout_operations"]["count"]
            tot["timeouts_overlapped_by_run"] += lab["timeout_operations"]["detected"]
            tot["timeouts_overlapped_by_run_before"] += lab0["timeout_operations"]["detected"]
            tot["timeouts_overlapped_by_overrun"] += sum(
                1 for o in d["operations"] if o["termination_reason"] == "TIMEOUT" and any(
                    o["finish_time"] is not None and o["start_time"] is not None
                    and e["start"] * 1_000_000 <= o["finish_time"] and o["start_time"] < e["end"] * 1_000_000
                    for e in eps if e["cause"] == "station_overrun"))
            tot["false_alarms"] += lab["false_alarms"]["count"]
            tot["station_cell_unlabelled"] += sum(1 for f in lab["false_alarms"]["list"] if f["on_station_cell"])
            tot["unlabelled_before"] += sum(1 for f in lab0["false_alarms"]["list"] if f["on_station_cell"])
            for ov in lab["overruns"]:
                lines.append(f"shift {k} T {T:.1f} s (n {sv['servicing_sample_n']}): overrun start {ov['start']} duration "
                             f"{ov['duration_s']} s cell {ov['station_cell']} overlaps TIMEOUT {ov['overlaps_timeout_operation']}")
        print("\nMoRoOp S14A smoke (radius 1, auto bound per shift):\n  " + "\n  ".join(lines) + f"\n  totals {tot}")
        # no pass bar on the outcome (Part 4: a count above 54 or a hidden 1,107 s stop is a measured negative); the checks
        # above are the structural ones (partition, causes seconds = episode seconds)
        self.assertGreaterEqual(tot["timeouts"], 8)


if __name__ == "__main__":
    unittest.main()

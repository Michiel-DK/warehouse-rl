"""S13B station-aware stuck rule: Detector(stations=, station_radius=), the one predicate detector.at_station, and the
time budget's run_is_stuck following the same rule. Hand-made streams (one step = 5 s, stuck_after 30 s), a pinned
byte-identity hash of the stations-absent event stream, and a MoRoOp shift-0 smoke.
Each case names its red demonstration in an `# inject:` comment."""
import gzip
import hashlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "fleet", ROOT / "src", ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import _platform  # noqa: E402
import timebudget as tb  # noqa: E402
from fleet_analyser import detector as detector_mod  # noqa: E402
from fleet_analyser.detector import SERVICING, STUCK, Detector, at_station  # noqa: E402
from fleet_analyser.hotspot import read_messages  # noqa: E402
from fleet_analyser.parse import Message, parse_line  # noqa: E402

BASE = 1767225600


def M(serial, step, order="o1", driving=False, x=3, y=4, zone="0", faulted=False):
    return Message(serial=serial, zone=zone, header_id=step, ts=BASE + 5 * step, order_id=order, x=x, y=y,
                   driving=driving, faulted=faulted, loaded=False, raw_len=1)


def feed(msgs, **kw):
    det = Detector(**kw)
    ev = []
    for m in sorted(msgs, key=lambda m: m.ts):
        ev.extend(det.feed(m))
    ev.extend(det.end_all())
    return ev, det


def opens(ev):
    return [e for e in ev if e["kind"] == "episode_open"]


def transitions(ev, to):
    return [e for e in ev if e["kind"] == "transition" and e["to_state"] == to]


def stop_at(x, y, first=0, last=18, serial="Z0-00", zone="0"):
    """Stopped with an order at (x, y) for (last - first) * 5 s (default 90 s)."""
    return [M(serial, s, x=x, y=y, zone=zone) for s in range(first, last + 1)]


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


def event_stream_sha(path):
    """sha256 of the Detector() event stream (stations absent) over the file's messages: json.dumps(ev, sort_keys=True)
    per event, newline-joined."""
    det = Detector()
    evs = []
    for m in read_messages(str(path)):
        evs.extend(det.feed(m))
    evs.extend(det.end_all())
    return hashlib.sha256("\n".join(json.dumps(e, sort_keys=True) for e in evs).encode()).hexdigest()


class TestStationRule(unittest.TestCase):
    def test_a_station_dwell_is_servicing_and_opens_no_episode(self):
        # inject: drop the `servicing` branch in Detector._step (the run becomes STUCK and opens an episode)
        ev, det = feed(stop_at(3, 4), stations={(3, 4)})
        self.assertEqual(opens(ev), [])
        self.assertEqual([e for e in ev if e["kind"].startswith("episode")], [])
        sv = transitions(ev, SERVICING)
        self.assertEqual([e["ts"] for e in sv], [BASE + 30])
        self.assertEqual(transitions(ev, STUCK), [])
        self.assertEqual(det.servicing_runs, 1)

    def test_b_same_stream_elsewhere_is_stuck_at_30_s(self):
        # inject: make at_station return True for every cell
        ev, det = feed(stop_at(3, 4), stations={(9, 9)})
        eps = opens(ev)
        self.assertEqual([(e["t_entry"], e["start"], e["cell"]) for e in eps], [(BASE + 30, BASE, [3, 4])])
        self.assertEqual(transitions(ev, SERVICING), [])
        self.assertEqual(det.servicing_runs, 0)
        plain, _ = feed(stop_at(3, 4))
        self.assertEqual(ev, plain)  # an off-station run behaves exactly as without stations

    def test_c_radius_is_manhattan(self):
        # inject: compare with < instead of <= or use Chebyshev distance
        msgs = stop_at(3, 5)
        self.assertEqual(len(opens(feed(msgs, stations={(3, 4)}, station_radius=0)[0])), 1)
        self.assertEqual(len(opens(feed(msgs, stations={(3, 4)}, station_radius=1)[0])), 0)
        self.assertEqual(len(opens(feed(stop_at(4, 5), stations={(3, 4)}, station_radius=1)[0])), 1)  # distance 2
        self.assertTrue(at_station(3, 5, {(3, 4)}, 1))
        self.assertFalse(at_station(3, 5, {(3, 4)}, 0))
        self.assertFalse(at_station(3, 4, None, 5))
        self.assertFalse(at_station(3, 4, set(), 5))

    def test_d_moving_off_the_station_starts_a_new_run(self):
        # inject: remember the first run's station flag across runs (second run then stays SERVICING)
        msgs = stop_at(3, 4, 0, 8) + [M("Z0-00", 9, driving=True, x=3, y=5)] + stop_at(3, 5, 10, 18)
        ev, det = feed(msgs, stations={(3, 4)})
        eps = opens(ev)
        self.assertEqual([(e["start"], e["cell"]) for e in eps], [(BASE + 50, [3, 5])])
        self.assertEqual([e["ts"] for e in transitions(ev, SERVICING)], [BASE + 30])
        self.assertEqual([e["ts"] for e in transitions(ev, STUCK)], [BASE + 80])

    def test_zone_mapping_and_wildcard(self):
        msgs = stop_at(3, 4, zone="1", serial="Z1-00")
        self.assertEqual(opens(feed(msgs, stations={"1": {(3, 4)}})[0]), [])
        self.assertEqual(len(opens(feed(msgs, stations={"0": {(3, 4)}})[0])), 1)
        self.assertEqual(opens(feed(msgs, stations={"*": {(3, 4)}})[0]), [])

    def test_docstring_and_state_tuple_name_servicing(self):
        self.assertIn("SERVICING", detector_mod.__doc__)
        self.assertEqual(detector_mod.SERVICING, "SERVICING")


class TestTimebudgetFollowsDetector(unittest.TestCase):
    def test_g_run_is_stuck_matches_the_detector_on_the_same_streams(self):
        # inject: let run_is_stuck judge by the run's LAST cell, or ignore the radius
        cases = [
            (stop_at(3, 4), {(3, 4)}, 0),
            (stop_at(3, 4), {(9, 9)}, 0),
            (stop_at(3, 5), {(3, 4)}, 0),
            (stop_at(3, 5), {(3, 4)}, 1),
            (stop_at(3, 4, 0, 8) + [M("Z0-00", 9, driving=True, x=3, y=5)] + stop_at(3, 5, 10, 18), {(3, 4)}, 0),
            (stop_at(3, 4, 0, 4), {(9, 9)}, 0),  # 20 s: short either way
        ]
        for msgs, stations, radius in cases:
            ev, _ = feed(msgs, stations=stations, station_radius=radius)
            kept = tb.kept_messages(msgs)
            runs, _ = tb.stopped_runs(kept)
            tb_starts = {kept[a].ts for a, b in runs if tb.run_is_stuck(kept, (a, b), stations, radius)}
            self.assertEqual(tb_starts, {e["start"] for e in opens(ev)}, (stations, radius))
            self.assertEqual({(e["robot"], e["start"]) for e in tb.recompute_episodes(msgs, stations, radius)},
                             {(e["robot"], e["start"]) for e in opens(ev)})

    def test_run_is_stuck_default_is_station_unaware(self):
        kept = tb.kept_messages(stop_at(3, 4))
        self.assertTrue(tb.run_is_stuck(kept, (0, len(kept) - 1)))
        self.assertFalse(tb.run_is_stuck(kept, (0, len(kept) - 1), {(3, 4)}, 0))


class TestByteIdentity(unittest.TestCase):
    def test_e_stations_absent_event_stream_equals_master_on_s10_none_zone0(self):
        # inject: let Detector add a key to its events or change the state of a station-less run
        want = _platform.expected("fleet_stream", "s13b_s10_none_zone0_event_sha256")  # SkipTest here skips visibly
        path = find_file("fleet", "data", "s10-none", "zone0-000.jsonl.gz")
        if path is None:
            self.skipTest("fleet/data/s10-none absent in this checkout and the main one")
        self.assertEqual(event_stream_sha(path), want)

    def test_i_stations_absent_event_stream_equals_master_on_sticky_phasea_zone0(self):
        # inject: let Detector add a key to its events or change the state of a station-less run
        want = _platform.expected("fleet_stream", "s13b_sticky_phasea_zone0_event_sha256")
        path = find_file("results", "closed_loop_sticky", "phaseA", "zone0-000.jsonl.gz")
        if path is None:
            self.skipTest("results/closed_loop_sticky/phaseA absent in this checkout and the main one")
        self.assertEqual(event_stream_sha(path), want)


def dumps(ev):
    return [json.dumps(e, sort_keys=True) for e in ev]


class TestFaultBeatsServicing(unittest.TestCase):
    """A faulted message is never SERVICING and never suppresses an episode open (pass 2)."""

    def test_h1_faulted_throughout_a_station_stop_equals_stations_none(self):
        # inject: restore `servicing = stuck_now and run.get("station", False)` (ignores m.faulted)
        msgs = [M("Z0-00", s, faulted=True) for s in range(0, 19)]
        want, _ = feed(msgs)
        got, det = feed(msgs, stations={(3, 4)})
        self.assertEqual(dumps(got), dumps(want))
        o = opens(got)
        self.assertEqual(len(o), 1)
        self.assertEqual((o[0]["cause"], o[0]["t_entry"], o[0]["start"]), ("faulted_self", BASE + 30, BASE))
        self.assertEqual(transitions(got, SERVICING), [])

    def test_h2_servicing_then_faulted_opens_at_first_faulted_message(self):
        # inject: restore `servicing = stuck_now and run.get("station", False)` (ignores m.faulted)
        msgs = [M("Z0-00", s, faulted=s >= 8) for s in range(0, 19)]
        ev, det = feed(msgs, stations={(3, 4)})
        self.assertEqual([e["ts"] for e in transitions(ev, SERVICING)], [BASE + 30])
        self.assertEqual([e["ts"] for e in transitions(ev, "FAULTED")], [BASE + 40])
        o = opens(ev)
        self.assertEqual(len(o), 1)
        self.assertEqual((o[0]["cause"], o[0]["t_entry"], o[0]["start"]), ("faulted_self", BASE + 40, BASE))
        self.assertEqual(det.servicing_runs, 1)  # the run stays counted: it was servicing before the fault

    def test_h3_faulted_robot_on_a_station_is_the_blocker_of_an_adjacent_robot(self):
        # inject: make the cause scan skip robots whose run is SERVICING
        msgs = [M("Z0-00", s, faulted=True) for s in range(0, 19)] + \
               [M("Z0-01", s, x=4, y=4) for s in range(0, 19)]
        want, _ = feed(msgs)
        got, _ = feed(msgs, stations={(3, 4)})
        self.assertEqual(dumps(got), dumps(want))
        nb = [e for e in opens(got) if e["robot"] == "Z0-01"]
        self.assertEqual(len(nb), 1)
        self.assertEqual((nb[0]["cause"], nb[0]["blocker"]), ("blocked_by_faulted", "Z0-00"))


class TestFlags(unittest.TestCase):
    """The CLI flags on ingest / deadlock / timebudget: absent = master's behaviour, present = the station rule."""

    def setUp(self):
        import tempfile

        from fleet.tests.test_fleet_timebudget import line, write_gz

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        self.d = d
        # robot A stopped 60 s at (3, 4); robot B stopped 60 s at (7, 7); both with an order
        lines = [line("Z0-00", k, "a1", False, 3, 4) for k in range(13)] + [line("Z0-01", k, "b1", False, 7, 7) for k in range(13)]
        write_gz(d / "zone0-000.jsonl.gz", lines)
        (d / "stations.json").write_text(json.dumps({"stations": [[3, 4]], "shelves": []}))
        self.glob = str(d / "*.jsonl.gz")

    def run_py(self, script, *args):
        r = subprocess.run([sys.executable, str(ROOT / "fleet" / script), *map(str, args)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def episodes(self, store):
        rows = [json.loads(ln) for ln in (self.d / store / "stuck_episodes.jsonl").read_text().splitlines()]
        return {r["robot"] for r in rows}

    def test_ingest_stations_flag(self):
        # inject: pass stations to the Detector but forget the ingest_runs counter, or write the key without the flag
        self.run_py("ingest.py", "--glob", self.glob, "--run", "r", "--store", f"jsonl:{self.d / 'plain'}", "--once")
        self.run_py("ingest.py", "--glob", self.glob, "--run", "r", "--stations", self.d / "stations.json",
                    "--store", f"jsonl:{self.d / 'st'}", "--once")
        self.assertEqual(self.episodes("plain"), {"Z0-00", "Z0-01"})
        self.assertEqual(self.episodes("st"), {"Z0-01"})
        plain_run = json.loads((self.d / "plain" / "ingest_runs.jsonl").read_text().splitlines()[-1])
        st_run = json.loads((self.d / "st" / "ingest_runs.jsonl").read_text().splitlines()[-1])
        self.assertNotIn("servicing_runs", plain_run)
        self.assertEqual(st_run["servicing_runs"], 1)

    def test_deadlock_and_timebudget_flags(self):
        # inject: ignore --station-radius in deadlock.main or in timebudget.main
        out = self.d / "t.json"
        base = ["--glob", self.glob, "--run", "r", "--stations", self.d / "stations.json", "--store", f"jsonl:{self.d / 'none'}"]
        self.run_py("timebudget.py", *base, "--out", out)
        plain = json.loads(out.read_text())
        self.run_py("timebudget.py", *base, "--station-aware", "--out", out)
        aware = json.loads(out.read_text())
        a, b = plain["zones"]["0"]["robots"], aware["zones"]["0"]["robots"]
        self.assertEqual(a["Z0-01"], b["Z0-01"])
        self.assertEqual(b["Z0-00"]["seconds"]["waiting_station"], a["Z0-00"]["seconds"]["waiting_station"])
        self.assertNotIn("station_aware", plain["src"])
        self.assertEqual((aware["src"]["station_aware"], aware["src"]["station_radius"]), (True, 0))
        # a robot one cell off the station: stuck without the radius, stopped_short with it
        from fleet.tests.test_fleet_timebudget import line, write_gz

        write_gz(self.d / "zone0-000.jsonl.gz", [line("Z0-00", k, "a1", False, 3, 5) for k in range(13)])
        self.run_py("timebudget.py", *base, "--station-aware", "--out", out)
        self.assertGreater(json.loads(out.read_text())["zones"]["0"]["robots"]["Z0-00"]["seconds"]["stuck"], 0)
        self.run_py("timebudget.py", *base, "--station-aware", "--station-radius", 1, "--out", out)
        r = json.loads(out.read_text())["zones"]["0"]["robots"]["Z0-00"]["seconds"]
        self.assertEqual((r["stuck"], r["stopped_short"] > 0), (0, True))
        dl = self.d / "dl.json"
        self.run_py("deadlock.py", "--glob", self.glob, "--run", "r", "--out", dl, "--stations", self.d / "stations.json",
                    "--station-radius", 1)
        self.assertEqual(json.loads(dl.read_text())["station_rule"], {"stations": str(self.d / "stations.json"), "radius": 1})


RAW = find_file("fleet", "data", "moroop", "raw")
STATIONS = ROOT / "fleet" / "data" / "moroop" / "stations.json"
try:
    import pyarrow  # noqa: F401
    HAVE_PYARROW = True
except ImportError:
    HAVE_PYARROW = False


@unittest.skipUnless(RAW is not None and (RAW / "data").is_dir() and HAVE_PYARROW, "MoRoOp raw dir or pyarrow absent")
class TestMoroopShift0(unittest.TestCase):
    def test_f_unlabelled_stuck_runs_drop_with_station_radius_1(self):
        # inject: ignore radius in moroop.run_intervals
        from adapters import moroop as mo

        name = mo.SHIFTS[0]
        d = mo.load_shift(RAW, name)
        msgs, _aux, _stats = mo.convert_shift(d["robot_state_cleaned"], d["operations"], d["jobs"])
        kept = tb.kept_messages([parse_line(mo.encode_line(m))[0] for m in msgs])
        stations, near, _ = tb.cell_sets(json.loads(STATIONS.read_text())["stations"], [])
        out = {}
        for radius in (None, 1):
            buckets = mo.second_buckets(kept, stations, near, tb, radius=radius)
            lab = mo.label_comparison(d["robot_state_cleaned"], kept, buckets, d["operations"], stations, tb, radius)
            out[radius] = (lab["stuck_runs"], lab["false_alarms"]["count"], lab["episodes_ge_30s"]["hits"],
                           lab["episodes_ge_30s"]["misses"])
        print(f"\nMoRoOp shift 0 (stuck_runs, unlabelled/false alarms, label hits, misses): "
              f"before (stations unaware) {out[None]}, after (--station-radius 1) {out[1]}")
        self.assertLess(out[1][0], out[None][0])
        self.assertLess(out[1][1], out[None][1])
        self.assertGreaterEqual(out[1][2], out[None][2] - 0)  # detected label episodes do not get lost


if __name__ == "__main__":
    unittest.main()

"""Tests for S12A fleet/timebudget.py (per-robot time budget): exact bucket seconds on a hand-made stream, the
precedence and detector-run edge cases, station waits in the stall list, the store path, determinism, same-minute stops,
jobs per robot-hour, and (T3) the auto layout against the exporter's env worker on s10-none zone 0.
Each case names its red demonstration in an `# inject:` comment. T3 skips only when fleet/data/s10-none exists neither in
this checkout nor in the main one (CI)."""
import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "fleet", ROOT / "src", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import timebudget as tb  # noqa: E402
from fleet_analyser.parse import Message, iso  # noqa: E402
from fleet_analyser.store import JsonlStore  # noqa: E402

SCRIPT = str(ROOT / "fleet" / "timebudget.py")
BASE = 1767225600
BUCKETS = tb.BUCKETS


def line(serial, k, order="", driving=False, x=0, y=0, faulted=False, loaded=False):
    obj = {"schema_version": "fleet-state/2", "headerId": k, "timestamp": iso(BASE + 5 * k), "manufacturer": "sim",
           "serialNumber": serial, "orderId": order, "lastNodeId": f"{x}-{y}",
           "agvPosition": {"x": x, "y": y, "theta": 0.0, "mapId": "m"}, "driving": driving, "paused": False,
           "errors": [{"errorType": "BREAKDOWN", "errorLevel": "FATAL"}] if faulted else [],
           "loads": [{"loadId": "l"}] if loaded else [], "nodeStates": []}
    return (json.dumps(obj, separators=(",", ":")) + "\n").encode()


def write_gz(path, lines):
    with open(path, "wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as f:
        for ln in lines:
            f.write(ln)


def msg(serial, ts, order="", driving=False, x=0, y=0, faulted=False, loaded=False, h=None):
    return Message(serial=serial, zone="0", header_id=ts if h is None else h, ts=ts, order_id=order, x=x, y=y,
                   driving=driving, faulted=faulted, loaded=loaded, raw_len=1)


def t1_lines():
    out = []
    # A: moves 20 s, waits at the station 40 s (order kept), then idles. Station (1,1).
    for k in range(16):
        if k < 4:
            out.append(line("Z0-01", k, "a1", True, 0, 0))
        elif k < 12:
            out.append(line("Z0-01", k, "a1", False, 1, 1))
        else:
            out.append(line("Z0-01", k, "", False, 1, 1))
    # B: stopped with an order for 60 s in a corridor cell (3,3), run still open at the end of its stream
    for k in range(13):
        out.append(line("Z0-02", k, "b1", False, 3, 3))
    # C: faulted 20 s while driving true, then moving 20 s
    for k in range(9):
        out.append(line("Z0-03", k, "c1", True, 2, 2, faulted=k < 4))
    # picker: stopped beside the shelf slot (5,5), empty loads, 40 s
    for k in range(9):
        out.append(line("Z0-04", k, "p1", False, 5, 6))
    return out


def run_cli(*args):
    return subprocess.run([sys.executable, SCRIPT, *map(str, args)], capture_output=True, text=True)


def data_dir():
    """fleet/data/s10-none of this checkout, else of the main checkout (WR_MAIN_CHECKOUT or git common dir), else None."""
    here = ROOT / "fleet" / "data" / "s10-none"
    if (here / "zone0-000.jsonl.gz").is_file():
        return here
    env = os.environ.get("WR_MAIN_CHECKOUT")
    cands = [Path(env)] if env else []
    try:
        common = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                capture_output=True, text=True, check=True).stdout.strip()
        cands.append(Path(common).parent)
    except (subprocess.CalledProcessError, OSError):
        pass
    for c in cands:
        d = c / "fleet" / "data" / "s10-none"
        if (d / "zone0-000.jsonl.gz").is_file() and (d / "emit_ledger.json").is_file():
            return d
    return None


def tree(root):
    return sorted((str(p.relative_to(root)), p.stat().st_size) for p in Path(root).rglob("*") if p.is_file())


def zero(**kw):
    d = {b: 0 for b in BUCKETS}
    d.update(kw)
    return d


class Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.data = cls.tmp / "data"
        cls.data.mkdir()
        write_gz(cls.data / "zone0-000.jsonl.gz", t1_lines())
        cls.stations = cls.tmp / "stations.json"
        cls.stations.write_text(json.dumps({"stations": [[1, 1]], "shelves": [[5, 5]], "pickers": ["Z0-04"]}))
        cls.out = cls.tmp / "out.json"
        cls.res = run_cli("--glob", cls.data / "*.jsonl.gz", "--run", "T", "--stations", cls.stations, "--out", cls.out)
        cls.j = json.loads(cls.out.read_text()) if cls.out.is_file() else None

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)


class TestT1(Fixture):
    def test_t1_exact_seconds(self):
        # inject: move the station cell off (1,1), or change a bucket's precedence in robot_budget
        self.assertEqual(self.res.returncode, 0, self.res.stderr)
        z = self.j["zones"]["0"]
        self.assertEqual(sorted(z["robots"]), ["Z0-01", "Z0-02", "Z0-03"])
        self.assertEqual(sorted(z["pickers"]), ["Z0-04"])
        self.assertEqual(z["robots"]["Z0-01"]["seconds"], zero(moving=20, waiting_station=40, idle=15))
        self.assertEqual(z["robots"]["Z0-02"]["seconds"], zero(stuck=60))
        self.assertEqual(z["robots"]["Z0-03"]["seconds"], zero(faulted=20, moving=20))
        self.assertEqual(z["pickers"]["Z0-04"]["seconds"], zero(waiting_shelf=40))
        for r in list(z["robots"].values()) + list(z["pickers"].values()):
            self.assertEqual(sorted(r["seconds"]), sorted(BUCKETS))
        self.assertEqual(z["robots"]["Z0-01"]["span_s"], 75)
        self.assertEqual(z["totals"]["seconds"], zero(faulted=20, moving=40, waiting_station=40, stuck=60, idle=15))
        self.assertEqual(z["totals"]["robots"], 3)
        self.assertEqual(z["totals"]["span_s"], 75 + 60 + 40)

    def test_t1_station_waits_in_stall_list(self):
        # inject: count only AGV episodes, or classify by the episode end cell instead of the run start cell
        w = self.j["zones"]["0"]["station_waits_in_stall_list"]
        self.assertEqual((w["source"], w["episodes"], w["at_station"], w["at_shelf"], w["picker_episodes"]),
                         ("recomputed", 3, 1, 1, 1))
        self.assertAlmostEqual(w["share_station"], 1 / 3)
        self.assertEqual(self.j["run"]["station_waits_in_stall_list"]["episodes"], 3)
        cmp_ = self.j["zones"]["0"]["stuck_runs_vs_detector"]
        self.assertEqual((cmp_["timebudget_stuck_runs"], cmp_["detector_episodes"], cmp_["start_sets_equal"]),
                         (3, 3, True))

    def test_t1_pickers_excluded_from_totals(self):
        # inject: add pickers into totals / n_robots
        z = self.j["zones"]["0"]
        self.assertEqual(z["same_minute_stops"]["n_robots"], 3)
        self.assertEqual(self.j["run"]["totals"]["robots"], 3)
        self.assertEqual(self.j["run"]["totals"]["seconds"]["waiting_shelf"], 0)
        self.assertEqual(self.j["src"]["store"], None)
        self.assertEqual(sorted(self.j), ["run", "src", "zones"])


class TestT2(Fixture):
    def test_t2_sum_equals_span_t1(self):
        # inject: let the last message own its trailing interval
        for z in self.j["zones"].values():
            for r in list(z["robots"].values()) + list(z["pickers"].values()):
                self.assertEqual(sum(r["seconds"].values()), r["span_s"])


class TestT3(unittest.TestCase):
    def test_t3_auto_layout_matches_exporter(self):
        # inject: build the layout in-process / reuse one process for two layouts / drop the picker kinds
        d = data_dir()
        if d is None:
            self.skipTest("fleet/data/s10-none absent in this checkout and the main one")
        import replay_export

        tmp = Path(tempfile.mkdtemp())
        try:
            shutil.copy(d / "zone0-000.jsonl.gz", tmp / "zone0-000.jsonl.gz")
            shutil.copy(d / "emit_ledger.json", tmp / "emit_ledger.json")
            out = tmp / "out.json"
            res = run_cli("--glob", tmp / "*.jsonl.gz", "--run", "s10-none", "--stations", "auto", "--out", out)
            self.assertEqual(res.returncode, 0, res.stderr)
            j = json.loads(out.read_text())
            cfg = json.loads((d / "emit_ledger.json").read_text())["config"]
            ref = replay_export.run_env_worker(dict(env_id=cfg["env_id"], steps=cfg["steps"], seed=0, zone=0, run=None))
            z = j["zones"]["0"]
            mine = tb.run_layout_worker(dict(env_id=cfg["env_id"], steps=cfg["steps"], seed=0))
            self.assertEqual(mine["goals"], ref["grid"]["goals"])
            self.assertEqual(mine["shelves"], ref["grid"]["shelves"])
            self.assertEqual(tb.kinds_of(mine, 0), ref["kinds"])
            self.assertEqual(z["cell_classes"]["n_station_cells"], len({tuple(g) for g in ref["grid"]["goals"]}))
            self.assertEqual(z["cell_classes"]["n_shelf_slots"], len(ref["grid"]["shelves"]))
            self.assertEqual(sorted(z["robots"]), sorted(s for s, k in ref["kinds"].items() if k == "agv"))
            self.assertEqual(sorted(z["pickers"]), sorted(s for s, k in ref["kinds"].items() if k == "picker"))
            self.assertEqual((len(z["robots"]), len(z["pickers"])), (8, 4))
            self.assertGreater(z["totals"]["seconds"]["waiting_station"], 0)
            self.assertGreater(z["totals"]["seconds"]["moving"], 0)
            for r in list(z["robots"].values()) + list(z["pickers"].values()):
                self.assertEqual(sum(r["seconds"].values()), r["span_s"])  # T2 on real data
            self.assertEqual(z["station_waits_in_stall_list"]["source"], "recomputed")
            self.assertTrue(z["stuck_runs_vs_detector"]["start_sets_equal"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestT4(unittest.TestCase):
    def test_t4_only_stall_at_station(self):
        # inject: classify with the shelf set only
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "d").mkdir()
            write_gz(tmp / "d" / "zone0-000.jsonl.gz",
                     [line("Z0-01", k, "a1", False, 1, 1) for k in range(10)]
                     + [line("Z0-02", k, "", False, 3, 3) for k in range(10)])
            (tmp / "s.json").write_text(json.dumps({"stations": [[1, 1]], "shelves": [[8, 8]]}))
            res = run_cli("--glob", tmp / "d" / "*.jsonl.gz", "--run", "T", "--stations", tmp / "s.json",
                          "--out", tmp / "o.json")
            self.assertEqual(res.returncode, 0, res.stderr)
            w = json.loads((tmp / "o.json").read_text())["zones"]["0"]["station_waits_in_stall_list"]
            self.assertEqual((w["episodes"], w["at_station"], w["share_station"]), (1, 1, 1.0))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestT5(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.data = self.tmp / "d"
        self.data.mkdir()
        write_gz(self.data / "zone0-000.jsonl.gz", t1_lines())
        (self.tmp / "s.json").write_text(json.dumps({"stations": [[1, 1]], "shelves": [[5, 5]], "pickers": ["Z0-04"]}))
        st = JsonlStore(self.data / "store")
        st.upsert("stuck_episodes", ["run", "episode_id"], [
            dict(run="T", episode_id=f"Z0-01@{iso(BASE + 20)}", zone="0", robot="Z0-01", start=BASE + 20, cell=[1, 1]),
            dict(run="T", episode_id=f"Z0-02@{iso(BASE)}", zone="0", robot="Z0-02", start=BASE, cell=[3, 3]),
            dict(run="other", episode_id="x", zone="0", robot="Z0-01", start=BASE, cell=[9, 9])])
        st.close()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_t5_store_read_only(self):
        # inject: open JsonlStore on a missing dir, or append to the store, or write a cache file next to --out
        before = tree(self.tmp)
        out = self.tmp / "o.json"
        res = run_cli("--glob", self.data / "*.jsonl.gz", "--run", "T", "--stations", self.tmp / "s.json", "--out", out)
        self.assertEqual(res.returncode, 0, res.stderr)
        j = json.loads(out.read_text())
        w = j["zones"]["0"]["station_waits_in_stall_list"]
        self.assertEqual((w["source"], w["episodes"], w["at_station"]), ("store", 2, 1))
        self.assertIsNotNone(j["src"]["store_sha256_before"])
        self.assertEqual(j["src"]["store_sha256_before"], j["src"]["store_sha256_after"])
        self.assertEqual(tree(self.tmp), sorted(before + [("o.json", out.stat().st_size)]))

    def test_t5_zero_rows_for_run_is_an_error(self):
        # inject: fall back to 0 episodes instead of exiting
        out = self.tmp / "o.json"
        res = run_cli("--glob", self.data / "*.jsonl.gz", "--run", "WRONG", "--stations", self.tmp / "s.json",
                      "--out", out)
        self.assertNotEqual(res.returncode, 0)
        self.assertFalse(out.exists())

    def test_t5_missing_store_not_created(self):
        # inject: open JsonlStore before the presence check
        d2 = self.tmp / "d2"
        d2.mkdir()
        shutil.copy(self.data / "zone0-000.jsonl.gz", d2)
        res = run_cli("--glob", d2 / "*.jsonl.gz", "--run", "T", "--stations", self.tmp / "s.json",
                      "--out", self.tmp / "o2.json", "--store", f"jsonl:{self.tmp / 'nostore'}")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertFalse((self.tmp / "nostore").exists())
        self.assertFalse((d2 / "store").exists())

    def test_t5_out_parent_must_exist(self):
        # inject: mkdir the parent of --out
        res = run_cli("--glob", self.data / "*.jsonl.gz", "--run", "T", "--stations", self.tmp / "s.json",
                      "--out", self.tmp / "nope" / "o.json")
        self.assertNotEqual(res.returncode, 0)
        self.assertFalse((self.tmp / "nope").exists())


class TestT6(Fixture):
    def test_t6_byte_identical(self):
        # inject: put a wall-clock value or an unsorted set into the JSON
        out2 = self.tmp / "out2.json"
        res = run_cli("--glob", self.data / "*.jsonl.gz", "--run", "T", "--stations", self.stations, "--out", out2)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.out.read_bytes(), out2.read_bytes())


class TestT7(unittest.TestCase):
    ST = {(1, 1)}
    NEAR = {(1, 1), (0, 1), (2, 1), (1, 0), (1, 2), (5, 5), (5, 6)}  # (1,1) is also shelf-adjacent: the station wins

    def budget(self, kept):
        return tb.robot_budget(kept, self.ST, self.NEAR, 3600)

    def test_t7_faulted_beats_moving_and_station(self):
        # inject: test driving before faulted
        kept = [msg("R", 0, "o", True, 0, 0, faulted=True), msg("R", 5, "o", False, 1, 1, faulted=True),
                msg("R", 10, "o", False, 1, 1), msg("R", 15, "o", True, 0, 0)]
        rec, _ = self.budget(kept)
        self.assertEqual(rec["seconds"], zero(faulted=10, waiting_station=5))

    def test_t7_station_beats_shelf_and_loaded_falls_through(self):
        # inject: test shelf adjacency before the station set, or ignore loads
        kept = [msg("R", 0, "o", False, 1, 1), msg("R", 5, "o", False, 5, 6),
                msg("R", 10, "o", False, 5, 6, loaded=True), msg("R", 15, "", False, 9, 9)]
        rec, _ = self.budget(kept)
        self.assertEqual(rec["seconds"], zero(waiting_station=5, waiting_shelf=5, stopped_short=5))
        kept = [msg("R", t, "o", False, 5, 6, loaded=True) for t in range(0, 40, 5)] + [msg("R", 40, "", False, 5, 6)]
        rec, starts = self.budget(kept)
        self.assertEqual(rec["seconds"], zero(stuck=40))
        self.assertEqual(starts, {("R", 0)})
        short = [msg("R", t, "o", False, 5, 6, loaded=True) for t in range(0, 15, 5)] + [msg("R", 15, "", False, 5, 6)]
        self.assertEqual(self.budget(short)[0]["seconds"], zero(stopped_short=15))

    def test_t7_new_run_at_ending_message_and_open_run_at_end(self):
        # inject: let a changed orderId continue the run, or ignore the run still open at stream end
        kept = [msg("R", 0, "o1", False, 9, 9), msg("R", 5, "o1", False, 9, 9)] + \
               [msg("R", t, "o2", False, 9, 9) for t in range(10, 50, 5)]
        rec, starts = self.budget(kept)
        self.assertEqual(rec["seconds"], zero(stopped_short=10, stuck=35))
        self.assertEqual(starts, {("R", 10)})
        eps = tb.recompute_episodes(kept)
        self.assertEqual({(e["robot"], e["start"]) for e in eps}, starts)
        self.assertEqual([e["resolution"] for e in eps], ["unresolved"])

    def test_t7_dropped_non_increasing_ts(self):
        # inject: skip the ts <= previous-kept-ts filter
        kept = tb.kept_messages([msg("R", 0, "", h=1), msg("R", 0, "o", h=2), msg("R", 5, "", h=3),
                                 msg("R", 4, "", h=4)])
        self.assertEqual([(m.ts, m.header_id) for m in kept], [(0, 1), (4, 4), (5, 3)])


class TestT8(unittest.TestCase):
    def robots(self, n_stopping):
        out = {}
        for i in range(5):
            s = f"R{i}"
            t = BASE + 600
            out[s] = [msg(s, t - 5, "o", True), msg(s, t if i < n_stopping else t + 120, "o", False)]
        return out

    def test_t8_same_minute_stops(self):
        # inject: threshold 0.6 instead of 0.8, or count events instead of distinct robots
        r = tb.stop_minutes(self.robots(4))
        self.assertEqual((r["count"], r["n_robots"], r["threshold"]), (1, 5, 0.8))
        self.assertEqual(r["minutes"], [iso((BASE + 600) // 60 * 60)])
        self.assertEqual(tb.stop_minutes(self.robots(3))["count"], 0)


class TestT9(unittest.TestCase):
    def test_t9_jobs_per_robot_hour(self):
        # inject: count every non-empty message, or skip the first message
        a = [msg("A", 450 * i, o) for i, o in enumerate(["", "o1", "o1", "o2", "", "o3", "o3", "o3"])]  # 3 jobs
        b = [msg("B", 450 * i, o) for i, o in enumerate(["o9", "o9", "", "o8", "o8", "", "", ""])]  # first counts: 2
        rec_a, _ = tb.robot_budget(a, set(), set(), 3600)
        rec_b, _ = tb.robot_budget(b, set(), set(), 3600)
        self.assertEqual((rec_a["jobs"], rec_b["jobs"]), (3, 2))
        lay = {"0": dict(goals=[], shelves=[], pickers=set(), layout={})}
        zones, run = tb.compute(a + b, "T", lay, [], "recomputed", 3600)
        self.assertAlmostEqual(zones["0"]["jobs_per_robot_hour"], 5 / (2 * 3150 / 3600))
        self.assertAlmostEqual(run["jobs_per_robot_hour"], 5 / (2 * 3150 / 3600))


if __name__ == "__main__":
    unittest.main()

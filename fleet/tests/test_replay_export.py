"""Tests for fleet/replay_export.py (the S8-REPLAY export) on a synthetic two-zone run built with the real pipeline
(ingest -> costmap -> outcome grade -> truth grade): payload schema, state derivation and precedence, the size cap,
publishes and their precision@20, grades per publish (another zone's forecasts must not count), episodes, the extractor
replay against the ingest checkpoint, the optional with_map layer, data.js round trip (fresh and committed) and the static
shape of the page. Unit tests, no Docker, no fleet/data and no results/ needed. One test spawns a fresh process for a
tiny real env (the grid and the cost-aware re-simulation)."""
import copy
import gzip
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "fleet", ROOT / "src", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import grade as grade_cli  # noqa: E402
import costmap  # noqa: E402
import hotspot_score  # noqa: E402
import replay_export as rx  # noqa: E402
from fleet.tests.test_fleet_ingest import ingest_dir  # noqa: E402
from fleet_analyser import forecast_grade, hotspot  # noqa: E402
from fleet_analyser.parse import Message, iso  # noqa: E402
from fleet_analyser.store import JsonlStore  # noqa: E402

BASE = 1767225600
STEPS = 120
RUN = "r"
SMALL_ENV = "tarware-small-4agvs-2pickers-globalobs-v1"
GRID = dict(width=12, height=12, highway=["1" * 12 for _ in range(12)], goals=[[0, 11], [5, 11]], shelves=[[2, 8]])
FLOOR = {"0": {"3,2": 0.6, "7,4": 0.4}, "1": {"3,2": 0.5, "4,4": 0.5}}
DOCS = ROOT / "docs" / "replay"


# ------------------------------------------------------------------------------------------------ fixture
def v2(serial, h, step, x, y, order="", driving=False, faulted=False, nxt=None, theta=0.0):
    """One fleet-state/2 line. nxt = first route node (None -> nodeStates [])."""
    nodes = [] if nxt is None else [{"nodeId": f"{nxt[0]}-{nxt[1]}", "sequenceId": 0, "released": True,
                                     "nodePosition": {"x": nxt[0], "y": nxt[1], "mapId": "m"}}]
    obj = {"schema_version": "fleet-state/2", "headerId": h, "timestamp": iso(BASE + 5 * step), "manufacturer": "sim",
           "serialNumber": serial, "orderId": order, "lastNodeId": f"{x}-{y}", "nodeStates": nodes,
           "agvPosition": {"x": x, "y": y, "theta": theta, "mapId": "m"}, "driving": driving, "paused": False,
           "errors": [{"errorType": "BREAKDOWN", "errorLevel": "FATAL"}] if faulted else [], "loads": [],
           "custom": {"stuck_count": 0, "carrying": False, "recovery_action": None, "stuck_event": False,
                      "clash_event": False}}
    return (json.dumps(obj, separators=(",", ":")) + "\n").encode()


def agv_script(serial, sx, y, stall_from, stall_to, order, faulted=()):
    """An AGV that drives to (sx, y), waits there facing the next cell with an order for steps stall_from..stall_to, then
    drives on to x = 11 (arriving at t_end) and drops the order. driving is true on every step the position changed."""
    t_end = stall_to + (11 - sx)
    out, x_prev = [], None
    for t in range(STEPS):
        if t < stall_from:
            x = min(t, sx)
        else:
            x = min(11, sx + max(0, t - stall_to))
        has_order = t <= t_end
        nxt = (x + 1, y) if has_order and x < 11 else None
        out.append((t, v2(serial, t, t, x, y, order=order if has_order else "", driving=x_prev is not None and x != x_prev,
                          faulted=t in faulted, nxt=nxt)))
        x_prev = x
    return out


def picker_script(serial, y, loading, stall):
    out = []
    for t in range(STEPS):
        order, nxt = "", None
        if loading and loading[0] <= t <= loading[1]:
            order = "o3"
        if stall and stall[0] <= t <= stall[1]:
            order, nxt = "o4", (7, y)
        out.append((t, v2(serial, t, t, 6, y, order=order, nxt=nxt)))
    return out


def zone0_lines():
    rows = []
    rows += agv_script("Z0-01", 2, 2, 3, 30, "o1")
    rows += agv_script("Z0-02", 8, 5, 9, 12, "o2", faulted=range(50, 53))
    rows += picker_script("Z0-03", 4, (40, 44), (60, 63))
    rows += [(t, v2("Z0-04", t, t, 0, 0)) for t in range(STEPS)]
    return rows


def zone1_lines():
    rows = agv_script("Z1-01", 2, 2, 3, 30, "o1")
    rows += [(t, v2("Z1-02", t, t, 0, 0)) for t in range(STEPS)]
    return rows


def interleave(rows, extra=None):
    """Lines step by step; extra = {step: [raw lines appended after that step's lines]}."""
    out = []
    for t in range(STEPS):
        out += [ln for s, ln in rows if s == t]
        out += (extra or {}).get(t, [])
    return out


def write_gz(path, lines):
    with gzip.open(path, "wb") as f:
        for ln in lines:
            f.write(ln)


def fake_env(job):
    kinds = {f"Z{job['zone']}-{i:02d}": "agv" if i <= 2 else "picker" for i in range(1, 5)}
    if job["zone"] == "1":
        kinds = {"Z1-01": "agv", "Z1-02": "picker"}
    return dict(grid=copy.deepcopy(GRID), kinds=kinds, lines=None, deliveries=None, pick_rate=None)


def build_run(directory):
    """Write the run dir (zone files, truth, emit ledger, costmap.json) and fill the store with the real pipeline."""
    d = Path(directory)
    dup = [ln for s, ln in zone0_lines() if s == 40 and b'"Z0-02"' in ln][0]
    z0 = interleave(zone0_lines(), {30: [b"this is not json\n"], 41: [dup]})
    z1 = interleave(zone1_lines())
    write_gz(d / "zone0-000.jsonl.gz", z0)
    write_gz(d / "zone1-000.jsonl.gz", z1)
    truth = dict(schema_version="fleet-truth/1", env_id=SMALL_ENV, disturb_tag="t", disturb={"floor": {"cells": 2}},
                 steps=STEPS, seed_base=0,
                 zones={z: dict(seed=int(z), floor_cells=FLOOR[z], floor_skips=[0] * STEPS, floor_skips_total=0)
                        for z in FLOOR})
    (d / "truth.json").write_text(json.dumps(truth))
    zones = []
    for z, lines, robots in (("0", z0, 4), ("1", z1, 2)):
        zones.append(dict(zone=int(z), status="complete", seed=int(z), messages=robots * STEPS, expected_messages=robots * STEPS,
                          complete=True, bytes_uncompressed=sum(map(len, lines)),
                          bytes_compressed=(d / f"zone{z}-000.jsonl.gz").stat().st_size, robots=robots, steps=STEPS,
                          files=[dict(name=f"zone{z}-000.jsonl.gz")], last_timestamp=iso(BASE + 5 * (STEPS - 1))))
    emit = dict(status="complete", config=dict(env_id=SMALL_ENV, steps=STEPS, seed_base=0, zones=2, t0=iso(BASE),
                                              policy="stuck_aware_cta", recovery={"name": "timeout", "call_human_cost": 60},
                                              disturb={"floor": {"cells": 2}}, t0_mode="fixed", rate="flat", speed=0.0),
                zones=zones, total=dict(expected_messages=6 * STEPS), truth=None)
    (d / "emit_ledger.json").write_text(json.dumps(emit))
    (d / "costmap.json").write_text(json.dumps(dict(run=RUN, zones={})))
    st = JsonlStore(d / "store")
    ingest_dir(d, st, RUN)
    msgs = hotspot.read_messages(str(d / "*.jsonl.gz"))
    costmap.build_costmap(msgs, st, RUN, publish_every=200, horizon_s=100, top_k=20)
    forecast_grade.grade_outcomes(st, RUN, min_horizon_s=50)
    grade_cli.grade_truth(st, RUN, truth)
    st.close()
    return d


class Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = build_run(cls.tmp.name)
        cls.spec = f"jsonl:{cls.dir / 'store'}"
        cls.payload = rx.build_payload(cls.dir, cls.spec, "0", env_runner=fake_env, run_dir_arg=str(cls.dir),
                                       closed_loop_arg=None)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def store(self):
        return JsonlStore(self.dir / "store")

    def robot_index(self, serial):
        return [r["serial"] for r in self.payload["robots"]].index(serial)

    def state(self, serial, step):
        return self.payload["frames"][step][self.robot_index(serial)]


# ------------------------------------------------------------------------------------------------ tests
class TestSchema(Fixture):
    def test_top_level_keys_and_types(self):
        p = self.payload
        self.assertEqual(list(p), ["meta", "grid", "robots", "frames", "obstacles", "extractor", "publishes", "grades",
                                   "episodes", "stalls"])  # no with_map without --closed-loop
        m = p["meta"]
        for key, typ in (("run", str), ("zone", str), ("env_id", str), ("steps", int), ("step_seconds", int),
                         ("t0_ts", int), ("seed", int), ("disturb", dict), ("policy", str), ("recovery", dict),
                         ("schema", str), ("source", dict)):
            self.assertIsInstance(m[key], typ, key)
        self.assertEqual((m["schema"], m["steps"], m["step_seconds"], m["t0_ts"]), ("replay/1", STEPS, 5, BASE))
        self.assertEqual(set(p["grid"]), {"width", "height", "highway", "goals", "shelves"})
        self.assertEqual(len(p["frames"]), STEPS)
        self.assertEqual([r["serial"] for r in p["robots"]], ["Z0-01", "Z0-02", "Z0-03", "Z0-04"])
        self.assertEqual([r["kind"] for r in p["robots"]], ["agv", "agv", "picker", "picker"])
        for frame in p["frames"]:
            self.assertEqual(len(frame), len(p["robots"]))
            for x, y, state in frame:
                self.assertIsInstance(x, int)
                self.assertIsInstance(y, int)
                self.assertIn(state, rx.STATES)
                self.assertTrue(0 <= x < p["grid"]["width"] and 0 <= y < p["grid"]["height"])
        for key in ("series", "totals", "check"):
            self.assertIn(key, p["extractor"])
        for pub in p["publishes"]:
            self.assertEqual(set(pub), {"t", "step", "cells", "precision_at_20", "hits_at_20", "n_flagged"})
        self.assertEqual(set(p["grades"]), {"per_publish", "timeline"})
        for e in p["episodes"]:
            self.assertEqual(set(e), {"start_step", "end_step", "robot", "cell", "cause", "resolution", "left_censored"})
        for s in p["stalls"]:
            self.assertEqual(len(s), 5)
        self.assertEqual(p["meta"]["source"], dict(run_dir=str(self.dir), store=self.spec, closed_loop=None))

    def test_documented_keys_and_types_of_every_section(self):
        p = self.payload
        num = (int, float)
        pp = p["grades"]["per_publish"]
        self.assertEqual(len(pp), len(p["publishes"]))
        for g in pp:
            self.assert_shape(g, dict(t=int, forecasts=int, outcome=dict, outcome_count=dict, truth=dict, open=int, unranked=int,
                                      outcome_kind=(str, type(None)), window_end=(int, type(None)),
                                      window_end_step=(int, type(None))))
            self.assertEqual(set(g["outcome"]), {"ok", "off"})
            self.assertEqual(set(g["outcome_count"]), {"ok", "off"})
            self.assertEqual(set(g["truth"]), {"hit", "false_alarm"})
            self.assertIn(g["outcome_kind"], ("rank", "count", "mixed", None))
        self.assertTrue(p["grades"]["timeline"])
        for e in p["grades"]["timeline"]:
            self.assert_shape(e, dict(t=int, step=int, outcome_ok=int, outcome_off=int, truth_hit=int, truth_false_alarm=int))
        for pub in p["publishes"]:
            self.assert_shape(pub, dict(t=int, step=int, cells=list, precision_at_20=num, hits_at_20=int, n_flagged=int))
            for cell, cost, stalls in pub["cells"]:
                self.assertIsInstance(cell, str)
                self.assertIsInstance(cost, num)
                self.assertIsInstance(stalls, int)
        x = p["extractor"]
        self.assertEqual(set(x), {"series", "totals", "check"})
        series_keys = set(rx.SERIES_KEYS) | {"rejected_by_reason", "coverage"}
        self.assertEqual(set(x["series"]), series_keys)
        for k in rx.SERIES_KEYS:
            self.assertEqual(len(x["series"][k]), STEPS, k)
            self.assertTrue(all(isinstance(v, int) for v in x["series"][k]), k)
        self.assertIsInstance(x["series"]["rejected_by_reason"], dict)
        self.assertTrue(x["series"]["rejected_by_reason"])
        for reason, vals in x["series"]["rejected_by_reason"].items():
            self.assertIsInstance(reason, str)
            self.assertEqual(len(vals), STEPS)
            self.assertTrue(all(isinstance(v, int) for v in vals))
        self.assertEqual(len(x["series"]["coverage"]), STEPS)
        self.assertTrue(all(c is None or isinstance(c, num) for c in x["series"]["coverage"]))
        self.assertEqual(set(x["totals"]), series_keys | {"expected_messages", "bytes_compressed"})
        for k in rx.SERIES_KEYS + ("expected_messages", "bytes_compressed"):
            self.assertIsInstance(x["totals"][k], int, k)
        self.assertIsInstance(x["totals"]["rejected_by_reason"], dict)
        self.assertIsInstance(x["totals"]["coverage"], num)
        self.assertEqual(set(x["check"]), set(rx.CHECK_KEYS))
        self.assertTrue(all(isinstance(v, int) for v in x["check"].values()))
        self.assertTrue(p["obstacles"])
        for o in p["obstacles"]:
            self.assert_shape(o, dict(kind=str, cell=str, p=num, hidden_from_analyser=bool))
            self.assertEqual(o["kind"], "floor")
        for r in p["robots"]:
            self.assert_shape(r, dict(serial=str, kind=str))
        for e in p["episodes"]:
            self.assert_shape(e, dict(start_step=int, end_step=(int, type(None)), robot=str, cell=list, cause=str,
                                      resolution=str, left_censored=bool))
        for s_ in p["stalls"]:
            robot, cell, a, b, counted = s_
            self.assertIsInstance(robot, str)
            self.assertIsInstance(a, int)
            self.assertIsInstance(b, int)
            self.assertIsInstance(counted, bool)

    def assert_shape(self, d, shape):
        self.assertEqual(set(d), set(shape))
        for k, typ in shape.items():
            self.assertIsInstance(d[k], typ, k)
            if typ is int:
                self.assertNotIsInstance(d[k], bool, k)

    def test_with_map_keys_and_types(self):
        def env(job):
            return dict(fake_env(job), lines=[ln for s, ln in zone0_lines()], deliveries=7, pick_rate=5.04)

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "cl"
            (base / "phaseA").mkdir(parents=True)
            (base / "phaseA" / "costmap.json").write_text(json.dumps(
                dict(run="p", generated_at="2026-01-01T00:41:35Z", zones={"0": {"3,2": 1.0}})))
            (base / "summary.json").write_text(json.dumps(dict(headline_arm="a", arms={"a": {"alpha": 4.0}})))
            p = rx.build_payload(self.dir, self.spec, "0", str(base), env_runner=env, closed_loop_arg=str(base))
        wm = p["with_map"]
        self.assert_shape(wm, dict(arm=str, alpha=float, map_path=str, map_generated_at=str, map_tag=(str, type(None)),
                                   deliveries=int, pick_rate=float, frames=list, episodes=list, note=str))
        self.assertEqual(len(wm["frames"]), STEPS)
        self.assertTrue(wm["episodes"])
        for e in wm["episodes"]:
            self.assert_shape(e, dict(start_step=int, end_step=(int, type(None)), robot=str, cell=list, cause=str,
                                      resolution=str, left_censored=bool))

    def test_obstacles_are_the_zones_hidden_floor_cells(self):
        obs = self.payload["obstacles"]
        self.assertEqual({o["cell"]: o["p"] for o in obs}, FLOOR["0"])
        self.assertTrue(all(o["hidden_from_analyser"] is True for o in obs))

    def test_json_is_strict(self):
        json.dumps(self.payload, allow_nan=False)


def message(**kw):
    base = dict(serial="Z0-01", zone="0", header_id=1, ts=BASE, order_id="", x=1, y=1, driving=False, faulted=False,
                loaded=False, raw_len=1, theta=0.0, next_x=None, next_y=None, nodes_reported=True)
    base.update(kw)
    return Message(**base)


class TestStateDerivation(unittest.TestCase):
    def test_precedence_case_by_case(self):
        route = dict(order_id="o", next_x=2, next_y=1)
        cases = [
            ("frozen beats stuck, stalled, loading, moving", message(faulted=True, driving=True), True, True, "frozen"),
            ("faulted alone", message(faulted=True), False, False, "frozen"),
            ("stuck beats stalled and moving", message(driving=True), True, True, "stuck"),
            ("stuck beats loading", message(order_id="o"), True, False, "stuck"),
            ("stalled beats loading", message(order_id="o"), False, True, "stalled"),
            ("stalled beats moving", message(driving=True), False, True, "stalled"),
            ("loading: order, not driving, nodeStates []", message(order_id="o"), False, False, "loading"),
            ("moving", message(driving=True), False, False, "moving"),
            ("moving with a route", message(driving=True, **route), False, False, "moving"),
            ("idle: nothing", message(), False, False, "idle"),
            ("idle: order and a route but not driving", message(**route), False, False, "idle"),
            ("idle: order, old schema without nodeStates", message(order_id="o", nodes_reported=False), False, False,
             "idle"),
        ]
        for name, msg, ep, st, want in cases:
            with self.subTest(name):
                self.assertEqual(rx.derive_state(msg, ep, st), want)

    def test_skipped_episode_rows_do_not_make_a_robot_stuck(self):
        robots = [dict(serial="Z0-01", kind="agv")]
        msgs = [message(header_id=i, ts=BASE + 5 * i, driving=True) for i in range(4)]
        base = dict(robot="Z0-01", start=BASE, end=BASE + 100, zone="0", cell=[1, 1], cause="unknown")
        for name, row, stuck in (("plain", dict(base, resolution="moved"), True),
                                 ("left_censored", dict(base, resolution="moved", left_censored=True), False),
                                 ("interrupted", dict(base, resolution="interrupted"), False),
                                 ("open, end None", dict(base, resolution="open", end=None), True)):
            with self.subTest(name):
                frames = rx.build_frames(msgs, robots, BASE, 4, [row], [], GRID)
                self.assertEqual({f[0][2] for f in frames}, {"stuck"} if stuck else {"moving"})

    def test_episodes_list_is_unfiltered_and_flags_left_censored(self):
        rows = [dict(zone="0", robot="Z0-01", start=BASE, end=BASE + 50, cell=[1, 2], cause="traffic",
                     resolution="interrupted", left_censored=False),
                dict(zone="0", robot="Z0-02", start=BASE + 5, end=None, cell=[3, 4], cause="unknown",
                     resolution="open", left_censored=True),
                dict(zone="1", robot="Z1-01", start=BASE, end=BASE + 5, cell=[0, 0], cause="unknown",
                     resolution="moved", left_censored=False)]
        out = rx.build_episodes(rows, "0", BASE)
        self.assertEqual([(e["robot"], e["start_step"], e["end_step"], e["resolution"], e["left_censored"]) for e in out],
                         [("Z0-01", 0, 10, "interrupted", False), ("Z0-02", 1, None, "open", True)])

    def test_position_outside_the_grid_raises(self):
        robots = [dict(serial="Z0-01", kind="agv")]
        with self.assertRaises(ValueError):
            rx.build_frames([message(x=12)], robots, BASE, 1, [], [], GRID)
        with self.assertRaises(ValueError):
            rx.build_frames([message(y=-1)], robots, BASE, 1, [], [], GRID)


class TestPipelineStates(Fixture):
    def test_known_positions_and_states(self):
        self.assertEqual(self.state("Z0-01", 0)[:2], [0, 2])
        self.assertEqual(self.state("Z0-01", 1), [1, 2, "moving"])
        self.assertEqual(self.state("Z0-01", 2)[:2], [2, 2])
        self.assertEqual(self.state("Z0-04", 77), [0, 0, "idle"])
        self.assertEqual(self.state("Z0-02", 5)[:2], [5, 5])
        self.assertEqual(self.state("Z0-02", 5)[2], "moving")

    def test_robot_in_a_detector_episode_is_stuck(self):
        eps = [e for e in self.store().select("stuck_episodes", {"run": RUN}) if e["robot"] == "Z0-01"]
        self.assertEqual(len(eps), 1)
        self.assertEqual(self.state("Z0-01", 20)[2], "stuck")
        self.assertEqual(self.state("Z0-01", 20)[:2], [2, 2])

    def test_stalled_without_an_episode(self):
        self.assertEqual(self.state("Z0-02", 11)[2], "stalled")  # 15 s wait, below the 30 s detector threshold
        self.assertEqual(self.state("Z0-03", 62)[2], "stalled")

    def test_errors_make_a_robot_frozen(self):
        for t in (50, 51, 52):
            self.assertEqual(self.state("Z0-02", t)[2], "frozen")
        self.assertNotEqual(self.state("Z0-02", 53)[2], "frozen")

    def test_loading(self):
        self.assertEqual(self.state("Z0-03", 42)[2], "loading")

    def test_states_follow_an_independent_derivation_from_the_store(self):
        st = self.store()
        eps = [e for e in st.select("stuck_episodes", {"run": RUN}) if e["zone"] == "0"]
        stalls = [s for s in st.select("stalls", {"run": RUN}) if s["zone"] == "0"]
        for msg in hotspot.read_messages(str(self.dir / "zone0-*.jsonl.gz")):
            step = (msg.ts - BASE) // 5
            ep = any(e["robot"] == msg.serial and e["start"] <= msg.ts <= (e["end"] if e["end"] is not None else 1e18)
                     for e in eps)
            sl = any(s["robot"] == msg.serial and s["start"] <= msg.ts <= s["end"] for s in stalls)
            want = ("frozen" if msg.faulted else "stuck" if ep else "stalled" if sl else
                    "loading" if msg.order_id and not msg.driving and msg.nodes_reported and msg.next_x is None else
                    "moving" if msg.driving else "idle")
            self.assertEqual(self.state(msg.serial, step)[2], want, (msg.serial, step))

    def test_a_position_outside_the_grid_makes_the_export_raise(self):
        def small(job):
            return dict(fake_env(job), grid=dict(GRID, width=5, highway=["1" * 5] * 12))

        with self.assertRaises(ValueError):
            rx.build_payload(self.dir, self.spec, "0", env_runner=small)


class TestWriter(Fixture):
    def test_oversize_payload_raises_and_writes_nothing(self):
        out = Path(self.tmp.name) / "big" / "data.js"
        with self.assertRaises(ValueError):
            rx.write_data_js(self.payload, out, max_bytes=1000)
        self.assertFalse(out.exists())
        self.assertFalse(out.with_name("data.js.tmp").exists())

    def test_cap_boundary_and_default_cap(self):
        out = Path(self.tmp.name) / "cap.js"
        n = rx.write_data_js(self.payload, out)
        self.assertEqual(n, out.stat().st_size)
        rx.write_data_js(self.payload, out, max_bytes=n)  # exactly at the cap is fine
        with self.assertRaises(ValueError):
            rx.write_data_js(self.payload, out, max_bytes=n - 1)
        self.assertEqual(rx.MAX_BYTES, 2097152)

    def test_fresh_file_parses_after_stripping_prefix_and_suffix(self):
        out = Path(self.tmp.name) / "fresh.js"
        rx.write_data_js(self.payload, out)
        text = out.read_text()
        self.assertTrue(text.startswith("window.REPLAY = "))
        self.assertEqual(json.loads(text[len("window.REPLAY = "):].rstrip().rstrip(";")), self.payload)
        self.assertEqual(rx.read_data_js(out), self.payload)

    def test_cli_without_closed_loop_has_no_with_map(self):
        out = Path(self.tmp.name) / "cli.js"
        with mock.patch.object(rx, "run_env_worker", fake_env):
            code = rx.main(["--run-dir", str(self.dir), "--store", self.spec, "--zone", "0", "--out", str(out)])
        self.assertEqual(code, 0)
        data = rx.read_data_js(out)
        self.assertNotIn("with_map", data)
        self.assertEqual(data["meta"]["source"]["store"], self.spec)  # as typed

    def test_export_does_not_write_the_store(self):
        before = {p.name: p.read_bytes() for p in (self.dir / "store").iterdir()}
        rx.build_payload(self.dir, self.spec, "0", env_runner=fake_env)
        after = {p.name: p.read_bytes() for p in (self.dir / "store").iterdir()}
        self.assertEqual(before, after)


class TestPublishes(Fixture):
    def costmap_maps(self):
        maps = {}
        for r in self.store().select("costmap", {"run": RUN}):
            if r["zone"] == "0":
                maps.setdefault(r["published_at"], {})[r["cell"]] = r["cost"]
        return maps

    def test_strictly_ascending_and_three_publishes(self):
        ts = [p["t"] for p in self.payload["publishes"]]
        self.assertEqual(ts, sorted(set(ts)))
        self.assertEqual(ts, [BASE + 200, BASE + 400, BASE + 595])
        self.assertEqual([p["step"] for p in self.payload["publishes"]], [40, 80, 119])

    def test_precision_at_20_equals_score_zone_and_differs_between_publishes(self):
        maps = self.costmap_maps()
        got = []
        for p in self.payload["publishes"]:
            want = hotspot_score.score_zone(maps[p["t"]], FLOOR["0"], set(), ks=(20,))["k"]["20"]
            self.assertEqual(p["precision_at_20"], want["precision"])
            self.assertEqual(p["hits_at_20"], want["hits"])
            self.assertEqual(p["n_flagged"], len(maps[p["t"]]))
            got.append(p["precision_at_20"])
        self.assertEqual(got, [0.05, 0.1, 0.1])
        self.assertGreaterEqual(len(set(got)), 2)

    def test_cells_sorted_by_cost_then_cell_and_rounded(self):
        for p in self.payload["publishes"]:
            keys = [(-c[1], c[0]) for c in p["cells"]]
            self.assertEqual(keys, sorted(keys))
            for cell, cost, stalls in p["cells"]:
                self.assertEqual(cost, round(cost, 4))
                self.assertGreaterEqual(stalls, 1)


class TestGrades(Fixture):
    def recompute(self, t):
        st = self.store()
        ids = {d["id"] for d in st.select("decisions", {"run": RUN})
               if d["kind"] == "hotspot_forecast" and d["subject"][:3] == "Z0:" and d["decided_at"] == t}
        out = dict(outcome_ok=0, outcome_off=0, hit=0, false_alarm=0, count_ok=0, count_off=0)
        for g in st.select("forecast_grades", {"run": RUN}):
            if g["id"] not in ids:
                continue
            key = {"outcome": "outcome_", "outcome_count": "count_"}.get(g["grade_source"])
            if key:
                out[key + g["verdict"]] += 1
            elif g["grade_source"] == "truth":
                out[g["verdict"]] += 1
        return ids, out

    def test_per_publish_counts_equal_an_independent_recomputation(self):
        st = self.store()
        other = {d["id"] for d in st.select("decisions", {"run": RUN}) if d["subject"].startswith("Z1:")}
        graded_other = [g for g in st.select("forecast_grades", {"run": RUN}) if g["id"] in other]
        self.assertTrue(graded_other)  # the fixture does contain another zone's forecasts and grades
        for p, g in zip(self.payload["publishes"], self.payload["grades"]["per_publish"]):
            ids, want = self.recompute(p["t"])
            self.assertEqual(g["t"], p["t"])
            self.assertEqual(g["forecasts"], len(ids))
            self.assertEqual(g["outcome"], dict(ok=want["outcome_ok"], off=want["outcome_off"]))
            self.assertEqual(g["outcome_count"], dict(ok=want["count_ok"], off=want["count_off"]))
            self.assertEqual(g["truth"], dict(hit=want["hit"], false_alarm=want["false_alarm"]))
            self.assertEqual(g["truth"]["hit"] + g["truth"]["false_alarm"], len(ids))

    def recompute_all(self, publish_ts, zones):
        """Per publish t: truth grades of hotspot_forecast decisions whose subject is in `zones`, from the raw store."""
        st = self.store()
        decs = [d for d in st.select("decisions", {"run": RUN}) if d["kind"] == "hotspot_forecast"
                and d["subject"].split(":")[0] in zones]
        out = []
        for t in publish_ts:
            ids = {d["id"] for d in decs if d["decided_at"] == t}
            out.append(sum(1 for g in st.select("forecast_grades", {"run": RUN})
                           if g["id"] in ids and g["grade_source"] == "truth"))
        return out

    def test_the_other_zone_is_not_counted(self):
        ts = [p["t"] for p in self.payload["publishes"]]
        ours = [g["truth"]["hit"] + g["truth"]["false_alarm"] for g in self.payload["grades"]["per_publish"]]
        self.assertEqual(ours, self.recompute_all(ts, {"Z0"}))
        with_z1 = self.recompute_all(ts, {"Z0", "Z1"})
        self.assertNotEqual(ours, with_z1)  # negative control: counting zone 1 as well would change the numbers
        self.assertTrue(all(a <= b for a, b in zip(ours, with_z1)))
        self.assertGreater(sum(with_z1), sum(ours))

    def test_open_forecasts_and_outcome_kind(self):
        a, b, c = self.payload["grades"]["per_publish"]
        self.assertEqual((a["open"], b["open"]), (0, 0))
        self.assertEqual((a["outcome_kind"], b["outcome_kind"], c["outcome_kind"]), ("rank", "rank", None))
        self.assertEqual(c["open"], c["forecasts"])
        self.assertEqual(c["outcome"], dict(ok=0, off=0))
        self.assertEqual(a["outcome"]["ok"] + a["outcome"]["off"], a["forecasts"])

    def test_timeline_is_cumulative_and_ends_at_the_totals(self):
        tl = self.payload["grades"]["timeline"]
        for key in ("outcome_ok", "outcome_off", "truth_hit", "truth_false_alarm"):
            vals = [e[key] for e in tl]
            self.assertEqual(vals, sorted(vals))
        per = self.payload["grades"]["per_publish"]
        self.assertEqual(tl[-1]["outcome_ok"], sum(g["outcome"]["ok"] for g in per))
        self.assertEqual(tl[-1]["truth_hit"], sum(g["truth"]["hit"] for g in per))
        self.assertEqual([e["t"] for e in tl], sorted({e["t"] for e in tl}))


class TestEpisodesAndStalls(Fixture):
    def test_episodes_equal_the_zones_store_rows(self):
        rows = [e for e in self.store().select("stuck_episodes", {"run": RUN}) if e["zone"] == "0"]
        self.assertTrue(rows)
        want = sorted(((e["start"] - BASE) // 5, e["robot"], None if e["end"] is None else (e["end"] - BASE) // 5,
                       e["cell"], e["cause"], e["resolution"], bool(e["left_censored"])) for e in rows)
        got = sorted((e["start_step"], e["robot"], e["end_step"], e["cell"], e["cause"], e["resolution"],
                      e["left_censored"]) for e in self.payload["episodes"])
        self.assertEqual(got, want)
        other = [e for e in self.store().select("stuck_episodes", {"run": RUN}) if e["zone"] == "1"]
        self.assertTrue(other)  # zone 1 has its own episode, which must not be exported
        self.assertEqual(len(rows), len(self.payload["episodes"]))

    def test_stalls_are_the_zones_stall_extraction(self):
        st = [s for s in self.store().select("stalls", {"run": RUN}) if s["zone"] == "0"]
        self.assertEqual(len(self.payload["stalls"]), len(st))
        self.assertEqual({(s[0], s[1]) for s in self.payload["stalls"]}, {(s["robot"], s["cell"]) for s in st})


class TestExtractor(Fixture):
    def test_totals_equal_the_ingest_checkpoint_counters(self):
        for zone, robots in (("0", 4), ("1", 2)):
            p = self.payload if zone == "0" else rx.build_payload(self.dir, self.spec, zone, env_runner=fake_env)
            t, c = p["extractor"]["totals"], p["extractor"]["check"]
            self.assertIsNotNone(c, zone)
            self.assertEqual((t["parsed"], t["rejected"], t["duplicates"], t["sequence_gaps"], t["accepted"],
                              t["bytes"], t["missing_messages"]),
                             (c["messages_parsed"], c["messages_rejected"], c["duplicates"], c["sequence_gaps"],
                              c["messages_accepted"], c["bytes_read_uncompressed"], c["missing_messages"]))
            self.assertEqual(t["accepted"], robots * STEPS)

    def test_one_malformed_line_and_one_duplicate(self):
        t, s = self.payload["extractor"]["totals"], self.payload["extractor"]["series"]
        self.assertEqual((t["rejected"], t["duplicates"]), (1, 1))
        self.assertEqual(t["rejected_by_reason"], {"json": 1})
        self.assertEqual((t["parsed"], t["messages"], t["accepted"]), (4 * STEPS + 1, 4 * STEPS + 2, 4 * STEPS))
        # the malformed line follows the step-30 lines: counted at step 30; the duplicate re-sends a step-40 line
        self.assertEqual((s["rejected"][29], s["rejected"][30]), (0, 1))
        self.assertEqual((s["rejected_by_reason"]["json"][29], s["rejected_by_reason"]["json"][30]), (0, 1))
        self.assertEqual((s["duplicates"][39], s["duplicates"][40]), (0, 1))

    def test_series_are_cumulative_and_end_at_the_totals(self):
        s, t = self.payload["extractor"]["series"], self.payload["extractor"]["totals"]
        for key in rx.SERIES_KEYS:
            self.assertEqual(len(s[key]), STEPS)
            self.assertEqual(s[key], sorted(s[key]), key)
            self.assertEqual(s[key][-1], t[key], key)
        cov = [c for c in s["coverage"]]
        self.assertEqual(cov, sorted(cov))
        self.assertEqual(t["coverage"], 1.0)
        self.assertEqual(t["expected_messages"], 4 * STEPS)
        self.assertEqual(t["bytes_compressed"], (self.dir / "zone0-000.jsonl.gz").stat().st_size)

    def test_disagreeing_checkpoint_raises(self):
        totals = dict(self.payload["extractor"]["totals"])
        check = dict(self.payload["extractor"]["check"], messages_parsed=1)
        with self.assertRaises(ValueError):
            rx.verify_check(totals, check)
        rx.verify_check(totals, None)

    def test_rejected_line_before_any_good_line_counts_at_step_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "zone0-000.jsonl.gz"
            write_gz(path, [b"{broken\n", v2("Z0-01", 0, 3, 0, 0), v2("Z0-01", 0, 4, 0, 0), v2("Z0-01", 5, 4, 0, 0)])
            s, t = rx.replay_extractor([path], BASE, 10, None)
            self.assertEqual(s["rejected"][0], 1)
            self.assertEqual((t["duplicates"], t["sequence_gaps"], t["missing_messages"], t["accepted"]), (1, 1, 4, 2))
            self.assertIsNone(t["coverage"])
            self.assertEqual(s["duplicates"][3], 0)
            self.assertEqual(s["duplicates"][4], 1)


class TestWithMap(Fixture):
    def closed_loop(self, tmp, **summary):
        base = Path(tmp) / "cl"
        (base / "phaseA").mkdir(parents=True)
        (base / "phaseA" / "costmap.json").write_text(json.dumps(
            dict(run="p", generated_at="2026-01-01T00:41:35Z", zones={"0": {"3,2": 1.0, "4,2": 0.5}})))
        (base / "summary.json").write_text(json.dumps(dict(headline_arm="map_a4", arms={"map_a4": {"alpha": 4.0}},
                                                           **summary)))
        return base

    def test_layer_is_added_from_a_resimulation_job(self):
        seen = {}

        def env(job):
            seen.update(job)
            lines = [ln for s, ln in zone0_lines()]  # stand-in for the re-simulated stream
            return dict(fake_env(job), lines=lines, deliveries=7, pick_rate=5.04)

        with tempfile.TemporaryDirectory() as tmp:
            cl = self.closed_loop(tmp)
            p = rx.build_payload(self.dir, self.spec, "0", str(cl), env_runner=env, closed_loop_arg=str(cl))
        wm = p["with_map"]
        self.assertEqual((wm["arm"], wm["alpha"], wm["deliveries"]), ("map_a4", 4.0, 7))
        self.assertEqual(wm["map_path"], str(cl) + "/phaseA/costmap.json")
        self.assertEqual(wm["map_generated_at"], "2026-01-01T00:41:35Z")
        self.assertIn("final map from this same run", wm["note"])
        self.assertIn("in-sample", wm["note"])
        self.assertEqual(len(wm["frames"]), STEPS)
        self.assertTrue(all(len(f) == 4 for f in wm["frames"]))
        # the detector runs over the layer's own messages: the same stuck AGV as in the main layer shows as stuck
        self.assertEqual(wm["frames"][20][0], p["frames"][20][0])
        self.assertEqual(wm["frames"][20][0][2], "stuck")
        self.assertEqual(wm["frames"], p["frames"])  # the stand-in stream is zone 0's own, so the layers must agree
        self.assertEqual(wm["episodes"], p["episodes"])
        self.assertNotIn("stuck never occurs", wm["note"])
        self.assertIn("in-sample", wm["note"])
        self.assertIn("not learned live", wm["note"])
        self.assertEqual(seen["run"]["cost_alpha"], 4.0)
        self.assertEqual(seen["run"]["cost_map"], {(3, 2): 1.0, (4, 2): 0.5})
        self.assertEqual((seen["run"]["seed"], seen["run"]["policy"]), (0, "stuck_aware_cta"))

    def test_missing_closed_loop_files_log_and_add_no_layer(self):
        logged = []
        with tempfile.TemporaryDirectory() as tmp:
            p = rx.build_payload(self.dir, self.spec, "0", str(Path(tmp) / "nope"), env_runner=fake_env, log=logged.append)
        self.assertNotIn("with_map", p)
        self.assertEqual(len(logged), 1)

    def test_a_map_with_another_tag_than_the_summary_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            cl = self.closed_loop(tmp, map_tag="0000000000")
            with self.assertRaises(ValueError):
                rx.build_payload(self.dir, self.spec, "0", str(cl), env_runner=fake_env)


class TestDeriveLayer(unittest.TestCase):
    """The with_map-style derivation (detector over the layer's own messages), exercised without an env."""

    ROBOTS = [dict(serial="Z0-01", kind="agv")]

    def standing(self, n):
        # one robot with an order, not driving, at (1, 1), for n messages 5 s apart
        return [message(header_id=i, ts=BASE + 5 * i, order_id="o") for i in range(n)]

    def test_a_robot_standing_with_an_order_longer_than_stuck_after_is_stuck(self):
        n = rx.detector.DEFAULT_STUCK_AFTER // 5 + 6
        frames, rows, stalls = rx.derive_layer(self.standing(n), self.ROBOTS, BASE, n, GRID, RUN)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["robot"], rows[0]["cell"]), ("Z0-01", [1, 1]))
        states = [f[0][2] for f in frames]
        self.assertEqual(states[-1], "stuck")
        self.assertIn("stuck", states)
        self.assertEqual(states[0], "stuck")  # an episode runs from the start of the stop, as in the store rows
        eps = rx.build_episodes(rows, "0", BASE)
        self.assertEqual((eps[0]["start_step"], eps[0]["resolution"]), (0, "unresolved"))

    def test_a_short_wait_is_stalled_not_stuck(self):
        n = rx.detector.DEFAULT_STUCK_AFTER // 5 - 2
        msgs = [message(header_id=i, ts=BASE + 5 * i, order_id="o", next_x=2, next_y=1) for i in range(n)]
        frames, rows, _ = rx.derive_layer(msgs, self.ROBOTS, BASE, n, GRID, RUN)
        self.assertEqual(rows, [])
        self.assertNotIn("stuck", {f[0][2] for f in frames})

    def test_default_stuck_after_is_the_ingest_default(self):
        from fleet_analyser import ingest
        self.assertIs(ingest.DEFAULT_STUCK_AFTER, rx.detector.DEFAULT_STUCK_AFTER)


class TestRealEnv(unittest.TestCase):
    def test_fresh_process_builds_the_grid_and_resimulates_with_a_map(self):
        cfg = dict(zone=0, seed=0, steps=12, env_id=SMALL_ENV, policy="stuck_aware_cta", disturb={"floor": {"cells": 3, "p": [0.3, 0.7]}},
                   recovery={"name": "timeout", "call_human_cost": 60}, t0=iso(BASE), cost_map={(3, 3): 0.5}, cost_alpha=4.0)
        res = rx.run_env_worker(dict(env_id=SMALL_ENV, steps=12, seed=0, zone="0", run=cfg))
        g = res["grid"]
        self.assertEqual(len(g["highway"]), g["height"])
        self.assertTrue(all(len(r) == g["width"] for r in g["highway"]))
        self.assertTrue(g["goals"] and g["shelves"])
        self.assertEqual(sorted(res["kinds"].values()), ["agv"] * 4 + ["picker"] * 2)
        self.assertEqual(sorted(res["kinds"]), [f"Z0-{i:02d}" for i in range(1, 7)])
        self.assertEqual(len(res["lines"]), 6 * 12)
        self.assertIsInstance(res["deliveries"], int)
        # grid-only path (no run cfg) agrees on the layout
        res2 = rx.run_env_worker(dict(env_id=SMALL_ENV, steps=12, seed=0, zone="0", run=None))
        self.assertEqual(res2["grid"], g)
        self.assertEqual(res2["kinds"], res["kinds"])

    def test_emitter_cfg_without_cost_map_builds_the_env_as_before(self):
        import warehouse_rl.env as env_mod
        from fleet_analyser import emitter

        calls = []

        class Stop(Exception):
            pass

        class Stub:
            def __init__(self, *a, **kw):
                calls.append(kw)
                raise Stop

        cfg = dict(zone=0, seed=0, steps=3, env_id=SMALL_ENV, policy="cta", disturb={}, recovery=None, t0=iso(BASE))
        with mock.patch.object(env_mod, "WarehouseEnv", Stub):
            for extra in ({}, {"cost_map": {(1, 1): 0.5}, "cost_alpha": 2.0}):
                with self.assertRaises(Stop):
                    emitter.run_zone(dict(cfg, **extra), mock.Mock())
        self.assertNotIn("cost_map", calls[0])
        self.assertNotIn("cost_alpha", calls[0])
        self.assertEqual((calls[1]["cost_map"], calls[1]["cost_alpha"]), ({(1, 1): 0.5}, 2.0))


class TestCommittedData(unittest.TestCase):
    @unittest.skipUnless((DOCS / "data.js").exists(), "docs/replay/data.js is absent")
    def test_committed_data_js_parses_and_is_within_the_cap(self):
        path = DOCS / "data.js"
        self.assertLessEqual(path.stat().st_size, 2097152)
        text = path.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("window.REPLAY = "))
        data = json.loads(text[len("window.REPLAY = "):].rstrip().rstrip(";"))
        meta = data["meta"]
        self.assertEqual((meta["schema"], meta["steps"], len(data["frames"])), ("replay/1", 500, 500))
        for rel in (meta["source"]["run_dir"], meta["source"]["store"].split(":", 1)[-1], meta["source"]["closed_loop"]):
            self.assertFalse(str(rel).startswith("/"), rel)
        layers = [data["frames"]] + ([data["with_map"]["frames"]] if "with_map" in data else [])
        w, h = data["grid"]["width"], data["grid"]["height"]
        for frames in layers:
            self.assertEqual(len(frames), 500)
            for frame in frames:
                self.assertEqual(len(frame), len(data["robots"]))
                for x, y, state in frame:
                    self.assertTrue(0 <= x < w and 0 <= y < h)
                    self.assertIn(state, rx.STATES)
        pubs = [p["t"] for p in data["publishes"]]
        self.assertEqual(pubs, sorted(set(pubs)))
        series = data["extractor"]["series"]
        for key in rx.SERIES_KEYS:
            self.assertEqual(series[key][-1], data["extractor"]["totals"][key])
            self.assertEqual(series[key], sorted(series[key]))
        self.assertEqual(data["grades"]["per_publish"][0]["outcome_kind"], "count")  # publish 1: the older count grade
        if "with_map" in data:
            self.assertIn("episodes", data["with_map"])
            self.assertEqual(data["with_map"]["alpha"], 4.0)
            self.assertFalse(data["with_map"]["map_path"].startswith("/"))


class TestPageStatic(unittest.TestCase):
    """The page conditions that can be checked on the files alone (the page itself is verified on the diff)."""

    @classmethod
    def setUpClass(cls):
        cls.html = (DOCS / "index.html").read_text(encoding="utf-8")
        cls.js = (DOCS / "replay.js").read_text(encoding="utf-8")
        cls.css = (DOCS / "replay.css").read_text(encoding="utf-8")

    def test_code_budget(self):
        total = sum((DOCS / n).stat().st_size for n in ("index.html", "replay.js", "replay.css"))
        self.assertLess(total, 300 * 1024)

    def test_classic_scripts_data_first_and_no_network(self):
        scripts = re.findall(r"<script[^>]*>", self.html)
        external = [s for s in scripts if "src=" in s]
        self.assertEqual([re.search(r'src="([^"]+)"', s).group(1) for s in external], ["data.js", "replay.js"])
        self.assertEqual(len(scripts) - len(external), 1)  # the one inline theme script in <head>, before first paint
        self.assertFalse(any("module" in s for s in scripts))
        for text in (self.html, self.js, self.css):
            self.assertIsNone(re.search(r"https?://", text.replace("http://www.w3.org/2000/svg", "")))
            self.assertNotIn("fetch(", text)
            self.assertNotIn("XMLHttpRequest", text)
            self.assertNotIn("@import", text)

    def test_wording(self):
        self.assertIn("still in top 20 after the horizon", self.js)
        self.assertIn("Hidden floor problems: the analyser cannot see these", self.html + self.js)
        self.assertNotIn("rank hit", (self.html + self.js).lower())
        for word in ("analyst", "AGV", "re-simulation", "ingester", "emit ledger"):
            self.assertNotIn(word, self.html + self.js, word)

    def test_rank_wording_lives_only_in_the_rank_branch(self):
        phrase = "still in top 20 after the horizon"
        self.assertEqual(self.js.count(phrase), 1)
        before = self.js[:self.js.index(phrase)]
        self.assertIn("kind === 'rank'", before.splitlines()[-1])  # same line as the rank test
        self.assertNotIn(phrase, self.html)
        self.assertIn("stall count about as claimed", self.js)

    def test_polite_live_region_is_not_written_by_the_frame_loop(self):
        draw = self.js[self.js.index("function draw()"):self.js.index("function setPlaying")]
        self.assertNotIn("'live'", draw)

    def test_keyboard_handler_leaves_controls_and_modifiers_alone(self):
        h = self.js[self.js.index("addEventListener('keydown'"):]
        for token in ("altKey", "ctrlKey", "metaKey", "'INPUT'", "'SELECT'", "'TEXTAREA'", "'BUTTON'"):
            self.assertIn(token, h)

    def test_dark_palette_is_declared_once(self):
        self.assertEqual(self.css.count("--bg: #12151a"), 1)
        self.assertNotIn("@media (prefers-color-scheme", self.css)


if __name__ == "__main__":
    unittest.main()

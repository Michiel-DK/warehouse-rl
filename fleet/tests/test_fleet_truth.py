"""S8B emitter-side tests on the real small map: heading and next node in the stream, the truth.json sidecar, the emit
ledger's byte accounting, and the x/y coordinate check (floor-skip stalls sit on floor cells with attribution "next").
Envs run strictly one at a time (Agent.counter / Shelf.counter are class attributes). Each case names its injection."""
import gzip
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "fleet", ROOT / "src", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fleet_analyser import emitter as em  # noqa: E402
from fleet_analyser import hotspot  # noqa: E402
from fleet_analyser.parse import epoch_of, parse_line  # noqa: E402
from warehouse_rl.disturb import STEP_SECONDS, resolve_disturb  # noqa: E402

SMALL = "tarware-small-4agvs-2pickers-globalobs-v1"
EMIT = str(ROOT / "fleet" / "emit.py")
FLOOR = {"floor": {"cells": 12, "p": [0.3, 0.7]}}
KEYS_V1 = ["schema_version", "headerId", "timestamp", "manufacturer", "serialNumber", "orderId", "lastNodeId",
           "agvPosition", "driving", "paused", "errors", "loads", "custom"]


class ListSink:
    def __init__(self):
        self.lines = []

    def write(self, serial, line, timestamp=None, header_id=None):
        self.lines.append(line)

    def stats(self):
        return dict(messages=len(self.lines), bytes_uncompressed=sum(map(len, self.lines)), bytes_compressed=None,
                    files=[])

    def close(self):
        pass


def cfg(disturb, steps, seed=2, zone=0):
    return dict(zone=zone, seed=seed, steps=steps, env_id=SMALL, policy="stuck_aware_cta", disturb=disturb,
                recovery={"name": "timeout", "call_human_cost": 60}, t0=em.DEFAULT_T0)


def emit_cli(directory, disturb_json, zones=2, steps=60):
    r = subprocess.run([sys.executable, EMIT, "--zones", str(zones), "--steps", str(steps), "--env", SMALL,
                        "--seed-base", "3", "--disturb", disturb_json, "--speed", "0", "--workers", "2", "--dir",
                        str(directory)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads((Path(directory) / "emit_ledger.json").read_text()), \
        json.loads((Path(directory) / "truth.json").read_text())


def observe(config):
    """In-process run_zone with observers: the env's own floor cells / skips, independent of run_zone's result."""
    sink, seen = ListSink(), dict(floor_cells=None, skipped=[], dirs=[], paths=[], counts=[])

    def on_ready(env):
        seen["floor_cells"] = dict(env.env.floor_cells)

    def on_step(step, env, info):
        hook = env.env
        seen["skipped"].append(hook.applied_floor[-1].copy())
        seen["dirs"].append([a.dir.name for a in hook.agents])
        seen["paths"].append([None if (not a.busy or not a.path) else tuple(a.path[0]) for a in hook.agents])
        seen["counts"].append(len(sink.lines))

    result = em.run_zone(config, sink, on_step=on_step, on_ready=on_ready)
    return result, sink, seen


class TestStreamFields(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, disturb = resolve_disturb(json.dumps(FLOOR))
        cls.result, cls.sink, cls.seen = observe(cfg(disturb, 120))
        cls.msgs = [json.loads(x) for x in cls.sink.lines]

    def test_key_order_and_schema_version(self):
        # inject: put nodeStates after agvPosition, or keep the version string at /1
        want = KEYS_V1[:7] + ["nodeStates"] + KEYS_V1[7:]
        for m in self.msgs:
            self.assertEqual(list(m), want)
            self.assertEqual(list(m["agvPosition"]), ["x", "y", "theta", "mapId"])
            self.assertEqual(m["schema_version"], "fleet-state/2")
            self.assertEqual(list(m["custom"]), list(em.CUSTOM_KEYS))
        self.assertEqual(list(em.TOP_KEYS), want)

    def test_theta_and_node_states_match_the_env(self):
        # inject: swap the UP / DOWN signs in theta, or read nodeStates from path[-1] / transpose x and y
        n = self.result["snapshot"]["robots"]
        want_theta = {"RIGHT": 0.0, "UP": round(math.pi / 2, 4), "LEFT": round(math.pi, 4),
                      "DOWN": round(-math.pi / 2, 4)}
        seen_nonempty = 0
        for step in range(len(self.seen["dirs"])):
            for i in range(n):
                m = self.msgs[step * n + i]
                self.assertEqual(m["agvPosition"]["theta"], want_theta[self.seen["dirs"][step][i]])
                p = self.seen["paths"][step][i]
                if p is None:
                    self.assertEqual(m["nodeStates"], [])
                else:
                    seen_nonempty += 1
                    self.assertEqual(m["nodeStates"], [{"nodeId": f"{p[0]}-{p[1]}", "sequenceId": 0, "released": True,
                                                        "nodePosition": {"x": p[0], "y": p[1],
                                                                         "mapId": SMALL}}])
        self.assertGreater(seen_nonempty, 20)

    def test_every_message_parses_with_theta(self):
        # inject: emit theta as a string
        for line in self.sink.lines:
            m, why = parse_line(line)
            self.assertIsNone(why)
            self.assertIsNotNone(m.theta)
            self.assertTrue(m.nodes_reported)


class TestSidecar(unittest.TestCase):
    def test_truth_json_matches_the_env(self):
        # inject: write (y, x) keys, drop a step from floor_skips, or write floor_cells without floor configured
        with tempfile.TemporaryDirectory() as d:
            ledger, truth = emit_cli(d, json.dumps(FLOOR))
            self.assertEqual(truth["schema_version"], "fleet-truth/2")
            self.assertEqual((truth["t0"], truth["step_seconds"]), (em.DEFAULT_T0, 5))  # resolved, never "now"
            self.assertEqual((truth["env_id"], truth["steps"], truth["seed_base"]), (SMALL, 60, 3))
            self.assertEqual(sorted(truth["zones"]), ["0", "1"])
            for z in (0, 1):
                _, disturb = resolve_disturb(json.dumps(FLOOR))
                _, _, seen = observe(cfg(disturb, 60, seed=3 + z, zone=z))
                want_cells = {f"{x},{y}": p for (x, y), p in seen["floor_cells"].items()}
                zt = truth["zones"][str(z)]
                self.assertEqual(zt["seed"], 3 + z)
                self.assertEqual(zt["floor_cells"], want_cells)
                self.assertEqual(len(want_cells), 12)
                self.assertEqual(len(zt["floor_skips"]), 60)
                self.assertEqual(sum(zt["floor_skips"]), sum(int(s.sum()) for s in seen["skipped"]))
                self.assertEqual(zt["floor_skips_total"], sum(zt["floor_skips"]))
                self.assertEqual((zt["blocked_windows"], zt["outage_windows"], zt["frozen_windows"], zt["burst"]),
                                 ([], [], [], None))  # none of these kinds configured
            self.assertGreater(sum(truth["zones"]["0"]["floor_skips"]) + sum(truth["zones"]["1"]["floor_skips"]), 0)

    def test_without_floor_the_map_is_empty(self):
        # inject: fill floor_cells from a default
        with tempfile.TemporaryDirectory() as d:
            _, truth = emit_cli(d, "breakdown-heavy", zones=1, steps=30)
            zt = truth["zones"]["0"]
            self.assertEqual(zt["floor_cells"], {})
            self.assertEqual(zt["floor_skips"], [0] * 30)

    def test_ledger_accounting_unchanged_by_the_sidecar(self):
        # inject: count truth.json bytes into a zone or the total, or leave truth null
        with tempfile.TemporaryDirectory() as d:
            ledger, _ = emit_cli(d, json.dumps(FLOOR))
            self.assertEqual(ledger["truth"], {"file": "truth.json", "bytes": os.path.getsize(Path(d) / "truth.json")})
            tot = dict(messages=0, bytes_uncompressed=0, bytes_compressed=0)
            for z in ledger["zones"]:
                files = sorted(Path(d).glob(f"zone{z['zone']}-*.jsonl.gz"))
                lines = raw = 0
                for f in files:
                    data = gzip.decompress(f.read_bytes())
                    lines += data.count(b"\n")
                    raw += len(data)
                comp = sum(os.path.getsize(f) for f in files)
                self.assertEqual((z["messages"], z["bytes_uncompressed"], z["bytes_compressed"]), (lines, raw, comp))
                tot["messages"] += lines
                tot["bytes_uncompressed"] += raw
                tot["bytes_compressed"] += comp
            for k, v in tot.items():
                self.assertEqual(ledger["total"][k], v)


class TestCoordinates(unittest.TestCase):
    def test_floor_skip_stalls_sit_on_floor_cells(self):
        # inject: transpose x / y in node_states, or attribute stalls to the current cell
        _, disturb = resolve_disturb(json.dumps({"floor": {"cells": 12, "p": [1, 1]}}))
        result, sink, seen = observe(cfg(disturb, 160))
        floor = {f"{x},{y}" for x, y in seen["floor_cells"]}
        self.assertEqual(set(result["floor_cells"]), floor)
        msgs = [parse_line(line)[0] for line in sink.lines]
        t0 = epoch_of(em.DEFAULT_T0)
        skipped = {(f"Z0-{i + 1:02d}", t0 + step * STEP_SECONDS)
                   for step, flags in enumerate(seen["skipped"]) for i, f in enumerate(flags) if f}
        self.assertTrue(skipped)
        stalls = hotspot.extract_stalls(msgs, "r")
        floor_stalls = [s for s in stalls
                        if any((s["robot"], ts) in skipped for ts in range(s["start"] + STEP_SECONDS, s["end"] + 1,
                                                                           STEP_SECONDS))]
        self.assertGreaterEqual(len(floor_stalls), 1)
        for s in floor_stalls:
            self.assertEqual(s["attribution"], "next", s)
            self.assertIn(s["cell"], floor, s)


if __name__ == "__main__":
    unittest.main()

"""Tests for fleet/deadlock.py (S12B): the per-batch blocking graph, deadlocks and knots, the detector agreement, the CLI.
D1-D3 use hand-made streams written with the emitter's field names (only the fields parse.parse_line requires); D4 also
runs the real emitter once. Envs run strictly one at a time (the emit CLI runs in a subprocess).
Each case names its red demonstration in an `# inject:` comment."""
import gzip
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "fleet", ROOT / "src", ROOT / "scripts", ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import deadlock  # noqa: E402
from fleet_analyser import hotspot  # noqa: E402
from fleet_analyser.parse import epoch_of, iso  # noqa: E402

T0 = epoch_of("2026-01-01T00:00:00Z")
EMIT = str(ROOT / "fleet" / "emit.py")
ENV = "tarware-small-4agvs-2pickers-globalobs-v1"


def line(serial, header, step, x, y, order="o1", driving=False, faulted=False):
    return (json.dumps({"headerId": header, "timestamp": iso(T0 + 5 * step), "serialNumber": serial, "orderId": order,
                        "agvPosition": {"x": x, "y": y}, "driving": driving,
                        "errors": [{"errorType": "BREAKDOWN"}] if faulted else [], "loads": []}) + "\n").encode()


def write_stream(directory, robots, steps):
    """robots: {serial: fn(step) -> (x, y, order, driving, faulted)}; one file zone0-000.jsonl.gz."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with gzip.open(directory / "zone0-000.jsonl.gz", "wb") as f:
        for step in range(steps):
            for serial, fn in sorted(robots.items()):
                x, y, order, driving, faulted = fn(step)
                f.write(line(serial, step, step, x, y, order, driving, faulted))
    return str(directory / "*.jsonl.gz")


def parked(x, y, until, faulted=False):
    """Stopped with an order from step 0, driving again from step `until` (60 s = step 12)."""
    return lambda s: (x, y, "o1", s >= until, faulted and s < until)


def messages_of(glob):
    return hotspot.read_messages(glob)


class TestGraph(unittest.TestCase):
    def test_d1_three_blocking_each_other_is_one_deadlock(self):
        # inject: lowest-serial-only edges (gives 2 robots), or no backdating of start to the stopped-run start (length 30)
        with tempfile.TemporaryDirectory() as d:
            g = write_stream(d, {f"Z0-0{i + 1}": parked(i, 0, 12) for i in range(3)}, 20)
            doc = deadlock.build_document(messages_of(g), "d1")
        z = doc["zones"]["0"]
        self.assertEqual(len(z["deadlocks"]), 1)
        dl = z["deadlocks"][0]
        self.assertEqual(dl["robots"], ["Z0-01", "Z0-02", "Z0-03"])
        self.assertEqual((dl["start"], dl["end"], dl["length_s"]), (T0, T0 + 60, 60))
        self.assertEqual(dl["resolution"], "broke_up")
        self.assertEqual(dl["cells"], ["0,0", "1,0", "2,0"])
        self.assertEqual(z["knots"], [])
        self.assertEqual(doc["total"]["deadlocks"], 1)
        self.assertEqual(doc["total"]["knots"], 0)
        self.assertEqual([r["kind"] for r in doc["decisions"]], ["deadlock"])
        self.assertEqual(doc["decisions"][0]["subject"], "0,0;1,0;2,0")

    def test_d1b_unresolved_at_end(self):
        # inject: closing an open deadlock at its start instead of the zone's last batch ts
        with tempfile.TemporaryDirectory() as d:
            g = write_stream(d, {"Z0-01": parked(0, 0, 99), "Z0-02": parked(1, 0, 99)}, 14)
            doc = deadlock.build_document(messages_of(g), "d1b")
        dl = doc["zones"]["0"]["deadlocks"][0]
        self.assertEqual((dl["resolution"], dl["end"], dl["length_s"]), ("unresolved_at_end", T0 + 5 * 13, 65))

    def test_d1c_min_s_filters_and_rate(self):
        # inject: compare min_s against the number of batches instead of length_s
        with tempfile.TemporaryDirectory() as d:
            g = write_stream(d, {f"Z0-0{i + 1}": parked(i, 0, 12) for i in range(3)}, 20)
            doc = deadlock.build_document(messages_of(g), "x", min_s=61)
            kept = deadlock.build_document(messages_of(g), "x", min_s=60)
        self.assertEqual(doc["total"]["deadlocks"], 0)
        self.assertEqual(kept["total"]["deadlocks"], 1)
        # 3 robots * 60 s over 3 robots * 95 s observed
        self.assertAlmostEqual(kept["zones"]["0"]["deadlock_s_per_robot_hour"], 3 * 60 / (3 * 95 / 3600))
        self.assertEqual([c["cell"] for c in kept["zones"]["0"]["top_cells"]], ["0,0", "1,0", "2,0"])
        self.assertTrue(all(c["deadlock_s"] == 60 for c in kept["zones"]["0"]["top_cells"]))

    def test_d2_chain_ending_at_a_faulted_head_is_a_knot(self):
        """A(0,0) stuck, B(1,0) stuck, F(2,0) faulted, A not adjacent to F. B has a faulted neighbour so B -> F only
        (blocked_by_faulted precedes blocked_by_stuck); A -> B. 'Free head' is read as 'head with no out-edge': a MOVING head
        would not be a head here either, because A and B would block each other (symmetric adjacency) and form a deadlock."""
        # inject: ignoring category precedence (B -> A edge as well) makes a 2-robot deadlock appear
        with tempfile.TemporaryDirectory() as d:
            g = write_stream(d, {"Z0-01": parked(0, 0, 12), "Z0-02": parked(1, 0, 12),
                                 "Z0-03": parked(2, 0, 12, faulted=True)}, 20)
            doc = deadlock.build_document(messages_of(g), "d2")
        z = doc["zones"]["0"]
        self.assertEqual(z["deadlocks"], [])
        self.assertEqual(len(z["knots"]), 1)
        kn = z["knots"][0]
        self.assertEqual((kn["robots"], kn["head"]), (["Z0-01", "Z0-02", "Z0-03"], "Z0-03"))
        self.assertEqual((kn["start"], kn["end"], kn["length_s"]), (T0, T0 + 60, 60))

    def test_d3_moving_robots_and_an_isolated_stuck_robot(self):
        # inject: count every STUCK robot (or every stopped run) as a deadlock
        robots = {f"Z0-0{i + 1}": (lambda s, i=i: (s, i * 3, "o1", True, False)) for i in range(3)}
        robots["Z0-09"] = lambda s: (20, 20, "o9", False, False)  # stuck all the time, nobody near
        with tempfile.TemporaryDirectory() as d:
            doc = deadlock.build_document(messages_of(write_stream(d, robots, 20)), "d3")
        self.assertEqual((doc["total"]["deadlocks"], doc["total"]["knots"]), (0, 0))
        self.assertEqual(doc["zones"]["0"]["deadlock_s_per_robot_hour"], 0.0)

    def test_traffic_edge_never_closes_a_cycle(self):
        # inject: let a traffic robot point back at the stuck robot it waits behind
        robots = {"Z0-01": parked(0, 0, 99), "Z0-02": (lambda s: (1, 0, "o2", True, False))}
        with tempfile.TemporaryDirectory() as d:
            doc = deadlock.build_document(messages_of(write_stream(d, robots, 20)), "t")
        self.assertEqual((doc["total"]["deadlocks"], doc["total"]["knots"]), (0, 0))

    def test_scc_and_chain_helpers(self):
        # inject: report a 2-node path as a knot, or drop the cycle member from the SCC
        self.assertEqual(deadlock.sccs({"a": ["b"], "b": ["a", "c"], "c": []}), [("a", "b"), ("c",)])
        self.assertEqual(deadlock.deadlocks_of({"a": ["b"], "b": ["c"]}), set())
        self.assertEqual(deadlock.chains_of({"a": ["b"], "b": ["c"]}, set()), {frozenset("abc"): ("a", "b", "c")})
        self.assertEqual(deadlock.chains_of({"a": ["b"]}, set()), {})


def hand_stream_for_agreement(d):
    """Several episode entries of every cause: a stuck line of three, a faulted robot, a stuck robot next to a faulted one,
    traffic with one and with two moving neighbours, and an isolated stuck robot."""
    robots = {}
    for i in range(3):  # blocked_by_stuck (a line)
        robots[f"Z0-0{i + 1}"] = parked(i, 0, 14)
    robots["Z0-04"] = parked(10, 0, 14, faulted=True)  # faulted_self
    robots["Z0-05"] = parked(11, 0, 14)  # blocked_by_faulted
    robots["Z0-07"] = parked(20, 0, 14)  # traffic: one moving neighbour
    robots["Z0-08"] = lambda s: (21, 0, "o8", True, False)
    robots["Z0-09"] = parked(30, 0, 14)  # traffic: two moving neighbours, no edge
    robots["Z0-10"] = lambda s: (29, 0, "o8", True, False)
    robots["Z0-11"] = lambda s: (31, 0, "o8", True, False)
    robots["Z0-12"] = parked(40, 40, 14)  # unknown
    return write_stream(d, robots, 20)


class TestAgreement(unittest.TestCase):
    def check_agreement(self, glob):
        seen = {}

        def observer(zone, ts, batch, states, edges, events, since):
            for e in events:
                if e["kind"] != "episode_open":
                    continue
                cause, targets = deadlock.category_of(batch[e["robot"]], batch, states)
                self.assertEqual(cause, e["cause"], (zone, ts, e["robot"]))
                if e["blocker"] is not None:
                    self.assertIn(e["blocker"], targets)
                seen[e["cause"]] = seen.get(e["cause"], 0) + 1

        deadlock.run_batches(messages_of(glob), observer=observer)
        return seen

    def test_d4_detector_agreement_hand_stream(self):
        # inject: recompute the category with a different precedence (stuck before faulted) or a different adjacency
        with tempfile.TemporaryDirectory() as d:
            seen = self.check_agreement(hand_stream_for_agreement(d))
        for cause in ("faulted_self", "blocked_by_faulted", "blocked_by_stuck", "traffic", "unknown"):
            self.assertGreater(seen.get(cause, 0), 0, cause)

    def test_d4_detector_agreement_real_emitter_run(self):
        # inject: as above; the run is a real breakdown-heavy small-map zone, so the episodes are the emitter's own
        with tempfile.TemporaryDirectory() as d:
            r = subprocess.run([sys.executable, EMIT, "--zones", "1", "--steps", "300", "--env", ENV, "--seed-base", "5",
                                "--speed", "0", "--workers", "1", "--dir", d], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            seen = self.check_agreement(str(Path(d) / "*.jsonl.gz"))
        self.assertGreater(sum(seen.values()), 0)


class TestCli(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "fleet" / "deadlock.py"), *map(str, args)],
                              capture_output=True, text=True)

    def test_d5_original_store_refused_and_normal_run(self):
        # inject: let --store through when it is <glob dir>/store (drop the check_copy call)
        with tempfile.TemporaryDirectory() as d:
            g = write_stream(Path(d) / "run", {f"Z0-0{i + 1}": parked(i, 0, 12) for i in range(3)}, 20)
            store = Path(d) / "run" / "store"
            store.mkdir()
            out = Path(d) / "out.json"
            r = self.run_cli("--glob", g, "--run", "r", "--out", out, "--store", f"jsonl:{store}")
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertFalse(out.exists())
            self.assertEqual(list(store.iterdir()), [])
            r = self.run_cli("--glob", g, "--run", "r", "--out", out, "--store", f"jsonl:{Path(d) / 'store-dl'}")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertRegex(r.stdout, r"deadlocks 1 knots 0 deadlock_s_per_robot_hour \d")
            doc = json.loads(out.read_text())
            self.assertEqual(doc["schema_version"], "fleet-deadlock/1")
            for key in ("run", "min_s", "definition", "zones", "total", "decisions"):
                self.assertIn(key, doc)
            for key in ("deadlocks", "knots", "deadlock_s_per_robot_hour", "top_cells"):
                self.assertIn(key, doc["zones"]["0"])
            rows = [json.loads(x) for x in (Path(d) / "store-dl" / "decisions.jsonl").read_text().splitlines()]
            self.assertEqual([x["kind"] for x in rows], ["deadlock"])
            self.assertEqual(list(store.iterdir()), [])

    def test_analyst_file_has_no_ground_sidecar_words(self):
        # inject: mention the sidecar file name or a floor key in deadlock.py (also covered by TestAnalystIsolation)
        text = (ROOT / "fleet" / "deadlock.py").read_text()
        self.assertIsNone(re.search(r"truth|floor_cells|floor_skip|floor_coin|applied_floor", text))


if __name__ == "__main__":
    unittest.main()

"""Tests for fleet/deadlock.py (S12B, renamed S12C): the per-batch blocking graph, blocking clusters and chains, the detector agreement, the CLI.
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
                        "errors": [{"errorType": "BREAKDOWN", "errorLevel": "FATAL"}] if faulted else [], "loads": []}) + "\n").encode()


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
    def test_d1_three_blocking_each_other_is_one_blocking_cluster(self):
        # inject: lowest-serial-only edges (gives 2 robots), or no backdating of start to the stopped-run start (length 30)
        with tempfile.TemporaryDirectory() as d:
            g = write_stream(d, {f"Z0-0{i + 1}": parked(i, 0, 12) for i in range(3)}, 20)
            doc = deadlock.build_document(messages_of(g), "d1")
        z = doc["zones"]["0"]
        self.assertEqual(len(z["blocking_clusters"]), 1)
        dl = z["blocking_clusters"][0]
        self.assertEqual(dl["robots"], ["Z0-01", "Z0-02", "Z0-03"])
        self.assertEqual((dl["start"], dl["end"], dl["length_s"]), (T0, T0 + 60, 60))
        self.assertEqual(dl["resolution"], "broke_up")
        self.assertEqual(dl["cells"], ["0,0", "1,0", "2,0"])
        self.assertEqual(z["blocking_chains"], [])
        self.assertEqual(doc["total"]["blocking_clusters"], 1)
        self.assertEqual(doc["total"]["blocking_chains"], 0)
        self.assertEqual([r["kind"] for r in doc["decisions"]], ["blocking_cluster"])
        self.assertEqual(doc["decisions"][0]["subject"], "0,0;1,0;2,0")

    def test_d1b_unresolved_at_end(self):
        # inject: closing an open cluster at its start instead of the zone's last batch ts
        with tempfile.TemporaryDirectory() as d:
            g = write_stream(d, {"Z0-01": parked(0, 0, 99), "Z0-02": parked(1, 0, 99)}, 14)
            doc = deadlock.build_document(messages_of(g), "d1b")
        dl = doc["zones"]["0"]["blocking_clusters"][0]
        self.assertEqual((dl["resolution"], dl["end"], dl["length_s"]), ("unresolved_at_end", T0 + 5 * 13, 65))

    def test_d1c_min_s_filters_and_rate(self):
        # inject: compare min_s against the number of batches instead of length_s
        with tempfile.TemporaryDirectory() as d:
            g = write_stream(d, {f"Z0-0{i + 1}": parked(i, 0, 12) for i in range(3)}, 20)
            doc = deadlock.build_document(messages_of(g), "x", min_s=61)
            kept = deadlock.build_document(messages_of(g), "x", min_s=60)
        self.assertEqual(doc["total"]["blocking_clusters"], 0)
        self.assertEqual(kept["total"]["blocking_clusters"], 1)
        # 3 robots * 60 s over 3 robots * 95 s observed
        self.assertAlmostEqual(kept["zones"]["0"]["blocked_s_per_robot_hour"], 3 * 60 / (3 * 95 / 3600))
        self.assertEqual([c["cell"] for c in kept["zones"]["0"]["top_cells"]], ["0,0", "1,0", "2,0"])
        self.assertTrue(all(c["blocked_s"] == 60 for c in kept["zones"]["0"]["top_cells"]))

    def test_d2_chain_ending_at_a_faulted_head_is_a_blocking_chain(self):
        """A(0,0) stuck, B(1,0) stuck, F(2,0) faulted, A not adjacent to F. B has a faulted neighbour so B -> F only
        (blocked_by_faulted precedes blocked_by_stuck); A -> B. 'Free head' is read as 'head with no out-edge': a MOVING head
        would not be a head here either, because A and B would block each other (symmetric adjacency) and form a cluster."""
        # inject: ignoring category precedence (B -> A edge as well) makes a 2-robot cluster appear
        with tempfile.TemporaryDirectory() as d:
            g = write_stream(d, {"Z0-01": parked(0, 0, 12), "Z0-02": parked(1, 0, 12),
                                 "Z0-03": parked(2, 0, 12, faulted=True)}, 20)
            doc = deadlock.build_document(messages_of(g), "d2")
        z = doc["zones"]["0"]
        self.assertEqual(z["blocking_clusters"], [])
        self.assertEqual(len(z["blocking_chains"]), 1)
        kn = z["blocking_chains"][0]
        self.assertEqual((kn["robots"], kn["head"]), (["Z0-01", "Z0-02", "Z0-03"], "Z0-03"))
        self.assertEqual((kn["start"], kn["end"], kn["length_s"]), (T0, T0 + 60, 60))

    def test_d3_moving_robots_and_an_isolated_stuck_robot(self):
        # inject: count every STUCK robot (or every stopped run) as a cluster
        robots = {f"Z0-0{i + 1}": (lambda s, i=i: (s, i * 3, "o1", True, False)) for i in range(3)}
        robots["Z0-09"] = lambda s: (20, 20, "o9", False, False)  # stuck all the time, nobody near
        with tempfile.TemporaryDirectory() as d:
            doc = deadlock.build_document(messages_of(write_stream(d, robots, 20)), "d3")
        self.assertEqual((doc["total"]["blocking_clusters"], doc["total"]["blocking_chains"]), (0, 0))
        self.assertEqual(doc["zones"]["0"]["blocked_s_per_robot_hour"], 0.0)

    def test_traffic_edge_never_closes_a_cycle(self):
        # inject: let a traffic robot point back at the stuck robot it waits behind
        robots = {"Z0-01": parked(0, 0, 99), "Z0-02": (lambda s: (1, 0, "o2", True, False))}
        with tempfile.TemporaryDirectory() as d:
            doc = deadlock.build_document(messages_of(write_stream(d, robots, 20)), "t")
        self.assertEqual((doc["total"]["blocking_clusters"], doc["total"]["blocking_chains"]), (0, 0))

    def test_scc_and_chain_helpers(self):
        # inject: report a 2-node path as a chain, or drop the cycle member from the SCC
        self.assertEqual(deadlock.sccs({"a": ["b"], "b": ["a", "c"], "c": []}), [("a", "b"), ("c",)])
        self.assertEqual(deadlock.clusters_of({"a": ["b"], "b": ["c"]}), set())
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
            self.assertRegex(r.stdout, r"blocking_clusters 1 blocking_chains 0 blocked_s_per_robot_hour \d")
            doc = json.loads(out.read_text())
            self.assertEqual(doc["schema_version"], "fleet-deadlock/2")
            for key in ("run", "min_s", "definition", "zones", "total", "decisions"):
                self.assertIn(key, doc)
            for key in ("blocking_clusters", "blocking_chains", "blocked_s_per_robot_hour", "top_cells"):
                self.assertIn(key, doc["zones"]["0"])
            rows = [json.loads(x) for x in (Path(d) / "store-dl" / "decisions.jsonl").read_text().splitlines()]
            self.assertEqual([x["kind"] for x in rows], ["blocking_cluster"])
            self.assertEqual(list(store.iterdir()), [])

    def test_analyst_file_has_no_ground_sidecar_words(self):
        # inject: mention the sidecar file name or a floor key in deadlock.py (also covered by TestAnalystIsolation)
        text = (ROOT / "fleet" / "deadlock.py").read_text()
        self.assertIsNone(re.search(r"truth|floor_cells|floor_skip|floor_coin|applied_floor", text))


def all_keys(node):
    """Every dict key anywhere in a JSON document."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from all_keys(v)
    elif isinstance(node, list):
        for v in node:
            yield from all_keys(v)


def to_v1(doc):
    """The fleet-deadlock/1 document equivalent to a v2 one: v1 key names, kind "deadlock", same values."""
    def counts(t):
        t = dict(t)
        t["deadlocks"], t["knots"] = t.pop("blocking_clusters"), t.pop("blocking_chains")
        t["deadlock_s_per_robot_hour"] = t.pop("blocked_s_per_robot_hour")
        return t

    zones = {}
    for z, zd in doc["zones"].items():
        zd = counts(zd)
        zd["top_cells"] = [dict(cell=c["cell"], deadlock_s=c["blocked_s"]) for c in zd["top_cells"]]
        zones[z] = zd
    v1_def = ("deadlock: strongly connected component (>= 2 robots) of the per-batch graph in which every STUCK robot "
              "has an edge to all adjacent faulted robots; mutually blocked cluster that persists, not a proven circular "
              "wait. knot: maximal path of >= 2 edges among robots in no such component.")
    return dict(doc, schema_version="fleet-deadlock/1", definition=v1_def, zones=zones, total=counts(doc["total"]),
                decisions=[dict(x, kind="deadlock") for x in doc["decisions"]])


class TestSchemaV2(unittest.TestCase):
    def doc(self, run="v"):
        with tempfile.TemporaryDirectory() as d:
            g = write_stream(d, {f"Z0-0{i + 1}": parked(i, 0, 12) for i in range(3)}, 20)
            return deadlock.build_document(messages_of(g), run)

    def test_v2_schema_and_no_deadlock_or_knot_key_anywhere(self):
        # inject: leave one v1 key (deadlock_s, knots) in the document
        doc = self.doc()
        self.assertEqual(doc["schema_version"], "fleet-deadlock/2")
        bad = [k for k in all_keys(doc) if "deadlock" in k.lower() or "knot" in k.lower()]
        self.assertEqual(bad, [])
        for section in (doc["total"], doc["zones"]["0"]):
            for key in ("blocking_clusters", "blocking_chains", "blocked_s_per_robot_hour"):
                self.assertIn(key, section)
        self.assertTrue(all("blocked_s" in c for c in doc["zones"]["0"]["top_cells"]))
        self.assertEqual({x["kind"] for x in doc["decisions"]}, {"blocking_cluster"})
        self.assertEqual(doc["decisions"][0]["dedup_key"].split(":")[0], "blocking_cluster")

    def test_definition_text(self):
        # inject: restore the v1 wording
        self.assertTrue(deadlock.DEFINITION.startswith(
            "blocking cluster: mutually blocked robots (strongly connected component, >= 2) that persist >= min_s; every "
            "one found so far resolves, so this is a congestion measure, not a circular wait. blocking chain: maximal "
            "path of >= 2 edges among robots in no cluster"))

    def test_sprint8_tables_prints_the_same_rows_for_v1_and_v2(self):
        # inject: read the v2 count / rate / top-cell key in the wrong column, or drop the v2 branch of the adapter
        import contextlib
        import io
        import sprint8_tables as st
        v2 = self.doc("s10-none")
        v1 = to_v1(v2)
        self.assertEqual(len(v2["decisions"]), 1)
        outs = {}
        with tempfile.TemporaryDirectory() as d:
            for name, doc in (("v1", v1), ("v2", v2)):
                p = Path(d) / f"deadlock_{name}.json"
                p.write_text(json.dumps(doc))
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    st.blocking_clusters([str(p)])
                outs[name] = buf.getvalue().splitlines()
        rows = {k: [ln for ln in v if ln.startswith("|")] for k, v in outs.items()}
        # the table is the "| ..." lines up to the first blank line; the definition paragraph is excluded
        table = {k: v[:3] for k, v in rows.items()}
        self.assertEqual(table["v1"], table["v2"])
        header, _, row = table["v2"]
        cols = [c.strip() for c in row.strip("|").split("|")]
        self.assertEqual(len(cols), len(header.strip("|").split("|")))
        self.assertEqual(cols[0], "s10-none")
        self.assertEqual(cols[1], "1")  # clusters
        self.assertEqual(cols[3], "0")  # chains
        rate = v2["total"]["blocked_s_per_robot_hour"]
        self.assertEqual(cols[6], f"{rate:.1f}")
        self.assertIn("cell 0,0: 60 s in 1 clusters", cols[8])
        para1 = [ln for ln in outs["v1"] if "The tool's own definition" in ln or "A blocking cluster is" in ln]
        para2 = [ln for ln in outs["v2"] if "A blocking cluster is" in ln]
        self.assertIn("mutually blocked robots (strongly connected component, >= 2) that persist >= min_s", para2[0])
        self.assertTrue(para1)


if __name__ == "__main__":
    unittest.main()

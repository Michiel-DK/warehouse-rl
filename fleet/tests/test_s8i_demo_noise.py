"""S8I-ONE-PAGER demo noise (criterion C4, C8): emit.py --demo-noise adds malformed lines, exact duplicates and one headerId
jump per zone as EXTRA lines. Platform-independent: nothing here compares against a stored digest, only a noisy run against
a clean run of the same seed made in the same process.

Definitions used by these tests (they are the contract of fleet_analyser/emitter.py DemoNoise):
  extra lines   the lines DemoNoise.record names (a duplicate or a malformed line right after a real message);
  jump          the difference between the two headerIds around the gap of one robot, 3..5; gap_ids = jump - 1 skipped ids;
  bookkeeping   for the transitions comparison: the keys starting "__" (the C2 definition) and `run`, the only column that
                names the ingest run rather than an event.
"""
import gzip
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "fleet", ROOT / "src", ROOT / "scripts", ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import live  # noqa: E402
import replay_export as rx  # noqa: E402
from fleet.tests.test_fleet_emit import ListSink, zone_cfg  # noqa: E402
from fleet.tests.test_fleet_ingest import ingest_dir  # noqa: E402
from fleet_analyser import emitter as em, ledger, live_state  # noqa: E402
from fleet_analyser.parse import epoch_of, parse_line  # noqa: E402
from fleet_analyser.store import JsonlStore  # noqa: E402

EMIT = str(ROOT / "fleet" / "emit.py")
SMALL = "tarware-small-4agvs-2pickers-globalobs-v1"
STEPS = 40


def run_small(noise, seed=0, steps=STEPS, ctl="/nonexistent-control-file"):
    """One in-process zone on the small map; returns (lines, result, DemoNoise instance or None)."""
    seen = []
    real = em.DemoNoise

    def spy(*a, **k):
        seen.append(real(*a, **k))
        return seen[-1]

    sink = ListSink()
    extra = dict(demo_mode=True, control_file=ctl, demo_noise=True) if noise else dict(demo_mode=True, control_file=ctl)
    with mock.patch.object(em, "DemoNoise", side_effect=spy):
        res = em.run_zone(zone_cfg(seed=seed, steps=steps, env_id=SMALL, **extra), sink)
    return sink.lines, res, (seen[0] if seen else None)


def strip_header(line):
    d = json.loads(line)
    d.pop("headerId")
    return d


def drop_extras(lines, noise, n_agents):
    """The real lines of a noisy run, using the injector's own record (step, robot, kind) of what it wrote."""
    per = {}
    for step, i, _ in noise.record:
        per[(step, i)] = per.get((step, i), 0) + 1
    out, k = [], 0
    while k < len(lines):
        out.append(lines[k])
        step, i = divmod(len(out) - 1, n_agents)
        k += 1 + per.get((step, i), 0)
    return out


class TestNoiseOffAndOn(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.clean, cls.clean_res, _ = run_small(False)
        cls.noisy, cls.noisy_res, cls.noise = run_small(True)
        cls.n = cls.noisy_res["snapshot"]["robots"]

    def test_the_injector_is_never_called_without_the_flag(self):
        boom = mock.Mock(side_effect=AssertionError("the noise injector was called"))
        with mock.patch.object(em, "DemoNoise", boom):
            res = em.run_zone(zone_cfg(seed=0, steps=6, env_id=SMALL, demo_mode=True, control_file="/nonexistent"), ListSink())
            plain = em.run_zone(zone_cfg(seed=0, steps=6, env_id=SMALL), ListSink())
        boom.assert_not_called()
        self.assertNotIn("injected_noise", res["snapshot"])
        self.assertEqual(res["snapshot"]["messages"], plain["snapshot"]["messages"])

    def test_noise_needs_demo_mode(self):
        with self.assertRaisesRegex(ValueError, "demo"):
            em.run_zone(zone_cfg(seed=0, steps=3, env_id=SMALL, demo_noise=True), ListSink())

    def test_noisy_lines_minus_extras_equal_the_clean_lines_up_to_header_ids(self):
        real = drop_extras(self.noisy, self.noise, self.n)
        self.assertEqual(len(real), len(self.clean))
        self.assertEqual([strip_header(x) for x in real], [strip_header(x) for x in self.clean])
        self.assertEqual(len(self.noisy) - len(real), self.noise.extra_lines)
        self.assertGreater(self.noise.extra_lines, 0)

    def test_exactly_one_header_jump_of_3_to_5_and_nothing_else_moves(self):
        real = drop_extras(self.noisy, self.noise, self.n)
        by_robot = {}
        for line in real:
            d = json.loads(line)
            by_robot.setdefault(d["serialNumber"], []).append(d["headerId"])
        jumps = []
        for serial, ids in by_robot.items():
            for a, b in zip(ids, ids[1:]):
                if b - a != 1:
                    jumps.append(b - a)
        self.assertEqual(len(jumps), 1)
        self.assertIn(jumps[0], (3, 4, 5))
        self.assertEqual(self.noise.counts()["gap_ids"], jumps[0] - 1)
        ids = {}
        for x in self.clean:
            d = json.loads(x)
            ids.setdefault(d["serialNumber"], []).append(d["headerId"])
        self.assertTrue(all(v == list(range(STEPS)) for v in ids.values()))  # the clean run has no jump

    def test_extra_lines_are_what_the_ledger_says(self):
        c = self.noise.counts()
        kinds = [k for _, _, k in self.noise.record if k != "dup"]
        self.assertEqual(c["malformed"], len(kinds))
        self.assertEqual(c["malformed_by_kind"], {k: kinds.count(k) for k in ("json", "timestamp", "type")})
        self.assertEqual(c["duplicates"], sum(1 for _, _, k in self.noise.record if k == "dup"))
        self.assertTrue(all(v >= 1 for v in c["malformed_by_kind"].values()), c)
        self.assertGreaterEqual(c["duplicates"], 1)
        self.assertEqual(self.noisy_res["snapshot"]["injected_noise"], c)
        # real messages only: robots * steps, extras only in the bytes
        self.assertEqual(self.noisy_res["snapshot"]["messages"], self.n * STEPS)
        self.assertEqual(self.clean_res["snapshot"]["messages"], self.n * STEPS)
        self.assertEqual(self.noisy_res["snapshot"]["bytes_uncompressed"], sum(map(len, self.noisy)))
        self.assertGreater(self.noisy_res["snapshot"]["bytes_uncompressed"], self.clean_res["snapshot"]["bytes_uncompressed"])

    def test_every_extra_line_is_a_whole_line_and_rejected_for_its_kind(self):
        kinds = iter(k for _, _, k in self.noise.record if k != "dup")
        prev = None
        for line in self.noisy:
            self.assertTrue(line.endswith(b"\n") and line.count(b"\n") == 1)
            msg, reason = parse_line(line)
            if msg is None:
                self.assertEqual(reason, next(kinds))
            elif line == prev:
                pass  # an exact duplicate
            prev = line
        self.assertEqual(list(kinds), [])

    def test_the_real_messages_are_the_same_with_and_without_noise(self):
        self.assertEqual(self.noisy_res["deliveries"], self.clean_res["deliveries"])
        self.assertEqual(self.noisy_res["floor_cells"], self.clean_res["floor_cells"])


class TestDeterminism(unittest.TestCase):
    def test_same_seed_same_lines_other_seed_other_positions(self):
        a, _, na = run_small(True, seed=2, steps=30)
        b, _, nb = run_small(True, seed=2, steps=30)
        c, _, nc = run_small(True, seed=3, steps=30)
        self.assertEqual(a, b)
        self.assertEqual(na.record, nb.record)
        self.assertNotEqual(na.record, nc.record)
        self.assertNotEqual((na.gap, sorted(na.dup_at)), (nc.gap, sorted(nc.dup_at)))

    def test_injector_alone_is_a_function_of_seed_agents_steps(self):
        one, two = em.DemoNoise(5, 6, 50), em.DemoNoise(5, 6, 50)
        self.assertEqual((one.bad_at, one.dup_at, one.gap), (two.bad_at, two.dup_at, two.gap))
        self.assertNotEqual((one.bad_at, one.gap), (em.DemoNoise(6, 6, 50).bad_at, em.DemoNoise(6, 6, 50).gap))
        step, robot, jump = one.gap
        self.assertTrue(1 <= step <= 49 and 0 <= robot < 6 and 3 <= jump <= 5)

    def test_it_never_touches_the_global_random_generator(self):
        import random

        random.seed(123)
        before = random.getstate()
        em.DemoNoise(1, 12, 100)
        self.assertEqual(random.getstate(), before)


class TestEndToEnd(unittest.TestCase):
    """emit.py as a subprocess (spawned zone), then the real ingester and the exporter's own check."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dirs = {}
        for name, noise in (("clean", False), ("noisy", True)):
            d = Path(cls.tmp.name) / name
            d.mkdir()
            args = [sys.executable, EMIT, "--zones", "1", "--steps", "30", "--env", SMALL, "--demo", "--control-file",
                    str(d / "control.jsonl"), "--dir", str(d), "--workers", "1"] + (["--demo-noise"] if noise else [])
            r = subprocess.run(args, capture_output=True, text=True)
            assert r.returncode == 0, r.stderr
            cls.dirs[name] = d
        cls.ledger = json.loads((cls.dirs["noisy"] / "emit_ledger.json").read_text())
        cls.stores = {}
        for name, d in cls.dirs.items():
            st = JsonlStore(d / "store")
            ing, _, code = ingest_dir(d, st, "r")
            assert code == 0
            cls.stores[name] = st

    @classmethod
    def tearDownClass(cls):
        for st in cls.stores.values():
            st.close()
        cls.tmp.cleanup()

    def test_ledger_messages_stay_robots_times_steps_and_noise_is_recorded(self):
        z = self.ledger["zones"][0]
        self.assertEqual((z["messages"], z["expected_messages"]), (z["robots"] * 30, z["robots"] * 30))
        self.assertIs(z["complete"], True)
        self.assertEqual(self.ledger["status"], "complete")
        self.assertEqual(self.ledger["total"]["injected_noise"], z["injected_noise"])
        self.assertIs(self.ledger["config"]["demo_noise"], True)
        clean = json.loads((self.dirs["clean"] / "emit_ledger.json").read_text())
        self.assertNotIn("injected_noise", clean["zones"][0])
        self.assertNotIn("demo_noise", clean["config"])
        self.assertGreater(z["bytes_uncompressed"], clean["zones"][0]["bytes_uncompressed"])

    def test_the_ingester_rejects_and_drops_exactly_what_was_injected(self):
        noise = self.ledger["zones"][0]["injected_noise"]
        st = self.stores["noisy"]
        rows = st.select("ingest_ledger", {"run": "r"})
        self.assertEqual(sum(r["messages_rejected"] for r in rows), noise["malformed"])
        self.assertEqual(sum(r["duplicates"] for r in rows), noise["duplicates"])
        self.assertEqual(sum(r["missing_messages"] for r in rows), noise["gap_ids"])
        self.assertEqual(sum(r["messages_accepted"] for r in rows), self.ledger["zones"][0]["messages"])
        rejects = st.select("rejects", {"run": "r"})
        self.assertEqual(len(rejects), noise["malformed"])
        self.assertTrue(all(r["reason"] for r in rejects))
        self.assertEqual({r["reason"] for r in rejects}, {"json", "timestamp", "type"})

    def test_coverage_as_the_exporter_computes_it_is_one(self):
        files = rx.zone_files(self.dirs["noisy"], "0")
        check = rx.ingest_check(self.stores["noisy"], "r", files)
        self.assertIsNotNone(check)
        self.assertEqual(ledger.coverage(check["messages_accepted"], self.ledger["zones"][0]["expected_messages"]), 1.0)
        series, totals = rx.replay_extractor(files, epoch_of(em.DEFAULT_T0), 30, self.ledger["zones"][0]["expected_messages"])
        rx.verify_check(totals, check)  # the replayed extractor agrees with the ingester on the noisy files
        self.assertEqual(totals["coverage"], 1.0)
        self.assertGreater(totals["rejected"], 0)
        self.assertGreater(totals["duplicates"], 0)

    def test_the_accepted_stream_and_the_transitions_equal_the_clean_run(self):
        def accepted(d):
            seen, out = set(), []
            for f in sorted(d.glob("zone*.jsonl.gz")):
                for line in gzip.open(f, "rb"):
                    m, _ = parse_line(line)
                    if m is None or (m.serial, m.header_id) in seen:
                        continue
                    seen.add((m.serial, m.header_id))
                    out.append(strip_header(line))
            return out

        self.assertEqual(accepted(self.dirs["noisy"]), accepted(self.dirs["clean"]))

        def tx(name):
            return [{k: v for k, v in r.items() if not k.startswith("__") and k != "run"}
                    for r in self.stores[name].select("transitions", {"run": "r"})]

        self.assertTrue(tx("clean"))
        self.assertEqual(tx("noisy"), tx("clean"))

    def test_demo_noise_without_demo_is_an_argument_error(self):
        r = subprocess.run([sys.executable, EMIT, "--demo-noise", "--steps", "3"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("--demo-noise", r.stderr)
        self.assertIn("--demo", r.stderr)


class TestLiveDefaults(unittest.TestCase):
    def test_live_has_demo_noise_on_by_default_and_a_switch(self):
        p = live.build_parser()
        self.assertIs(p.parse_args([]).demo_noise, True)
        self.assertIs(p.parse_args(["--no-demo-noise"]).demo_noise, False)
        self.assertIs(p.parse_args(["--demo-noise"]).demo_noise, True)
        self.assertIn("default ON", p.format_help().replace("\n", " ").replace("  ", " "))

    def test_the_emitter_child_gets_the_flag_only_when_on(self):
        for argv, want in (([], True), (["--no-demo-noise"], False)):
            a = live.build_parser().parse_args(argv)
            cmds = live.child_commands(a, Path("/tmp/x"), "jsonl:/tmp/x/store")
            self.assertEqual("--demo-noise" in cmds["emitter"], want)

    def test_live_state_keys_are_unchanged(self):
        self.assertEqual(len(live_state.STATE_KEYS), 10)
        with tempfile.TemporaryDirectory() as tmp:
            ctl = Path(tmp) / "c.jsonl"
            ctl.write_bytes(b"")
            inj = live_state.Injector(ctl, (25, 14), 6, lambda: 0, lead=2)
            snap = live_state.LiveState(tmp, "r", f"jsonl:{tmp}/store", str(Path(tmp) / "zone*-*.jsonl.gz"), inj).snapshot()
        self.assertEqual(set(snap), set(live_state.STATE_KEYS))

    def test_live_step_follows_message_time_not_header_ids(self):
        """A robot whose ids jumped (demo noise) must not push the displayed step ahead of the clock."""
        with tempfile.TemporaryDirectory() as tmp:
            ctl = Path(tmp) / "c.jsonl"
            ctl.write_bytes(b"")
            lines, res, noise = run_small(True, steps=30)
            with gzip.open(Path(tmp) / "zone0-000.jsonl.gz", "wb") as f:
                for line in lines:
                    f.write(line)
            inj = live_state.Injector(ctl, (25, 14), 6, lambda: 0, lead=2)
            state = live_state.LiveState(tmp, "r", f"jsonl:{tmp}/store", str(Path(tmp) / "zone*-*.jsonl.gz"), inj)
            self.assertEqual(state.snapshot()["step"], 29)
            self.assertGreater(max(json.loads(x)["headerId"] for x in lines if parse_line(x)[0]), 29)


if __name__ == "__main__":
    unittest.main()

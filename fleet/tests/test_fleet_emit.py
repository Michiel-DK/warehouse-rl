"""Tests for the S5A fleet emitter: message contract, orderId rule, errors[] vs the frozen schedule, ground truth only in
`custom`, dynamics untouched, byte reproducibility across processes, CLI errors, pacing.

Envs run strictly one at a time (Agent.counter / Shelf.counter are class attributes): the in-process runs are the only
env alive in this process while they run; comparisons against evaluate.run_seed use fresh subprocesses.
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
for _p in (ROOT / "fleet", ROOT / "src", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fleet_analyser import emitter as em  # noqa: E402
from warehouse_rl.disturb import resolve_disturb  # noqa: E402
from warehouse_rl.recovery import ACTIONS  # noqa: E402

EMIT = str(ROOT / "fleet" / "emit.py")
STEPS = 300
SEED = 3  # at 300 steps this seed has AGV and picker abandons (probed), breakdowns and stuck events


class ListSink:
    """In-memory sink with the sink interface."""

    def __init__(self):
        self.lines = []

    def write(self, serial, line, timestamp=None, header_id=None):
        self.lines.append(line)

    def stats(self):
        return dict(messages=len(self.lines), bytes_uncompressed=sum(map(len, self.lines)), bytes_compressed=None,
                    files=[])

    def close(self):
        pass


def zone_cfg(seed=SEED, steps=STEPS, zone=0, **extra):
    _, disturb = resolve_disturb("breakdown-heavy")
    cfg = dict(zone=zone, seed=seed, steps=steps, env_id=em.DEFAULT_ENV, policy="stuck_aware_cta", disturb=disturb,
               recovery={"name": "timeout", "call_human_cost": 60}, t0=em.DEFAULT_T0)
    cfg.update(extra)
    return cfg


def cli(*args, **kw):
    return subprocess.run([sys.executable, EMIT, *map(str, args)], capture_output=True, text=True, **kw)


def read_gz_lines(path):
    with gzip.open(path, "rb") as f:
        return f.read().splitlines(keepends=True)


class TestStream(unittest.TestCase):
    """One real run (seed 3, 300 steps, breakdown-heavy) observed from outside through the env state."""

    @classmethod
    def setUpClass(cls):
        cls.sink = ListSink()
        cls.abandons = []  # (step, agent id) from the env's own _abandon, not from the emitted stream
        cls.frozen = []  # applied_frozen[-1] per step
        cls.schedule = None
        cls.busy = []
        cls.delivered = []
        cur = {"step": 0}

        def on_ready(env):
            hook = env.env
            orig = hook._abandon

            def spy(agent):
                cls.abandons.append((cur["step"], agent.id))
                return orig(agent)

            hook._abandon = spy
            cls.schedule = hook.frozen_schedule.copy()

        def on_step(step, env, info):
            cur["step"] = step + 1
            cls.frozen.append(env.env.applied_frozen[-1].copy())
            cls.busy.append([a.busy for a in env.env.agents])
            cls.delivered.append(list(info["delivered_per_agent"]))

        cls.result = em.run_zone(zone_cfg(), cls.sink, on_step=on_step, on_ready=on_ready)
        cls.msgs = [json.loads(line) for line in cls.sink.lines]
        cls.n = cls.result["snapshot"]["robots"]

    def by_robot(self, i):
        serial = f"Z0-{i + 1:02d}"
        return [m for m in self.msgs if m["serialNumber"] == serial]

    def test_schema_keys_order_and_count(self):
        # inject: swap "orderId" and "serialNumber" in build_message, or emit a reset message before step 0
        self.assertEqual(self.n, 12)
        self.assertEqual((self.result["snapshot"]["agvs"], self.result["snapshot"]["pickers"]), (8, 4))
        self.assertEqual(len(self.msgs), self.n * STEPS)  # robots x steps: no reset message
        for raw, m in zip(self.sink.lines, self.msgs):
            self.assertEqual(list(m), list(em.TOP_KEYS))
            self.assertEqual(list(m["agvPosition"]), ["x", "y", "mapId"])
            self.assertEqual(list(m["custom"]), list(em.CUSTOM_KEYS))
            self.assertTrue(raw.endswith(b"\n") and raw.count(b"\n") == 1)
            self.assertEqual(raw, (json.dumps(m, separators=(",", ":")) + "\n").encode())
            self.assertEqual(m["schema_version"], "fleet-state/1")
            self.assertEqual(m["manufacturer"], "sim")
            self.assertRegex(m["serialNumber"], r"^Z0-\d\d$")
            self.assertIs(m["paused"], False)
            self.assertEqual(m["lastNodeId"], f"{m['agvPosition']['x']}-{m['agvPosition']['y']}")

    def test_header_ids_and_timestamps(self):
        # inject: start headerId at 1, or compute the timestamp from step + 1
        for i in range(self.n):
            rows = self.by_robot(i)
            self.assertEqual([m["headerId"] for m in rows], list(range(STEPS)))
            for step, m in enumerate(rows):
                self.assertEqual(m["timestamp"], em.timestamp_at(em.DEFAULT_T0, step, 5))
        self.assertEqual(self.msgs[0]["timestamp"], "2026-01-01T00:00:00Z")
        self.assertEqual(self.by_robot(0)[1]["timestamp"], "2026-01-01T00:00:05Z")

    def test_errors_nonempty_exactly_when_frozen(self):
        # inject: read frozen_schedule[:, step + 1] (or applied_frozen[-2]) instead of applied_frozen[-1]
        self.assertGreater(int(self.schedule.sum()), 0)  # breakdown-heavy seed 3 has frozen steps
        seen = 0
        for step in range(STEPS):
            self.assertEqual(list(self.frozen[step]), list(self.schedule[:, step]))  # applied == scheduled
            for i in range(self.n):
                m = self.by_robot(i)[step]
                self.assertEqual(bool(m["errors"]), bool(self.schedule[i, step]), (step, i))
                if m["errors"]:
                    seen += 1
                    self.assertEqual(m["errors"], [{"errorType": "BREAKDOWN", "errorLevel": "FATAL"}])
        self.assertGreater(seen, 0)

    def test_order_id_from_busy_transitions_in_a_real_run(self):
        # inject: key the id on custom.recovery_action, or reset k on abandon so an id repeats
        self.assertGreaterEqual(len(self.abandons), 2)
        pattern = re.compile(r"^Z0-(\d+)-o(\d+)$")
        for i in range(self.n):
            rows = self.by_robot(i)
            seen, last_k = set(), 0
            for step, m in enumerate(rows):
                oid = m["orderId"]
                self.assertEqual(oid == "", not self.busy[step][i], (step, i))  # '' exactly when not busy
                if not oid:
                    continue
                mt = pattern.match(oid)
                self.assertEqual(int(mt.group(1)), i + 1)
                k = int(mt.group(2))
                if step and rows[step - 1]["orderId"] == oid:
                    self.assertEqual(k, last_k)
                else:  # a new assignment: a never-before-used id, k incremented by exactly one
                    self.assertNotIn(oid, seen)
                    self.assertEqual(k, last_k + 1)
                seen.add(oid)
                last_k = k
        for step, agent_id in self.abandons:
            i = agent_id - 1
            rows = self.by_robot(i)
            self.assertNotEqual(rows[step - 1]["orderId"], "", (step, agent_id))
            self.assertEqual(rows[step]["orderId"], "", (step, agent_id))  # abandon is visible: id -> ''
            self.assertEqual(self.delivered[step][i], self.delivered[step - 1][i])  # and it is not a delivery
            later = next((r["orderId"] for r in rows[step:] if r["orderId"]), None)
            if later is not None:
                self.assertNotEqual(later, rows[step - 1]["orderId"])
                k_before = int(rows[step - 1]["orderId"].rsplit("-o", 1)[1])
                self.assertEqual(int(later.rsplit("-o", 1)[1]), k_before + 1)

    def test_order_tracker_scripted(self):
        # inject: drop the `target != self.target[i]` branch (a retarget keeps the old id) or reuse k after an abandon
        t = em.OrderTracker(zone=2, n_agents=1)
        seq = [(False, 0), (True, 5), (True, 5), (True, 7), (False, 0), (True, 7), (True, 7), (False, 0), (False, 0),
               (True, 5)]
        got = [t.update(0, 9, busy, target) for busy, target in seq]
        self.assertEqual(got, ["", "Z2-9-o1", "Z2-9-o1", "Z2-9-o2", "", "Z2-9-o3", "Z2-9-o3", "", "", "Z2-9-o4"])
        self.assertEqual(len(set(g for g in got if g)), 4)

    def test_ground_truth_only_in_custom(self):
        # inject: add "stuck_count" (or "recovery_action", or paused=stuck) as a top-level key in build_message
        contract = set(em.TOP_KEYS)
        for m in self.msgs:
            self.assertEqual(set(m), contract)
            self.assertEqual(set(m["custom"]), set(em.CUSTOM_KEYS))
            self.assertTrue(set(m["custom"]) == {"stuck_count", "carrying", "recovery_action", "stuck_event",
                                                 "clash_event"})
            self.assertIs(m["paused"], False)  # never a stuck signal
        for forbidden in ("stuck", "recovery", "clash"):
            self.assertFalse([k for k in contract if forbidden in k.lower()])
        customs = [m["custom"] for m in self.msgs]
        self.assertTrue(any(c["stuck_count"] > 0 for c in customs))
        self.assertTrue(any(c["stuck_event"] for c in customs))
        self.assertTrue(any(c["recovery_action"] == "wait" for c in customs))
        self.assertTrue(all(c["recovery_action"] in ACTIONS or c["recovery_action"] is None for c in customs))
        self.assertTrue(any(c["recovery_action"] == "abandon" for c in customs))
        for m in self.msgs:  # carrying <=> a load listed
            self.assertEqual(m["custom"]["carrying"], bool(m["loads"]))
            for ld in m["loads"]:
                self.assertRegex(ld["loadId"], r"^shelf-\d+$")


class TestDynamics(unittest.TestCase):
    def test_zone_runner_deliveries_equal_run_seed(self):
        # inject: reset the env with seed + 1 in run_zone (red demonstrated), or call env.step twice per iteration
        code_zone = (
            "import sys, json; sys.path[:0] = ['%s', '%s', '%s']\n"
            "from fleet_analyser import emitter as em\n"
            "from warehouse_rl.disturb import resolve_disturb\n"
            "class S:\n"
            "    n = 0\n"
            "    def write(self, *a, **k): S.n += 1\n"
            "    def stats(self): return dict(messages=S.n, bytes_uncompressed=0, bytes_compressed=None, files=[])\n"
            "    def close(self): pass\n"
            "cfg = dict(zone=0, seed=2, steps=250, env_id=em.DEFAULT_ENV, policy='stuck_aware_cta',\n"
            "           disturb=resolve_disturb('breakdown-heavy')[1], recovery={'name': 'timeout', 'call_human_cost': 60},\n"
            "           t0=em.DEFAULT_T0)\n"
            "r = em.run_zone(cfg, S())\n"
            "print(json.dumps([r['deliveries'], r['pick_rate'], S.n]))\n"
        ) % (ROOT / "fleet", ROOT / "src", ROOT / "scripts")
        code_ref = (
            "import sys, json; sys.path[:0] = ['%s', '%s']\n"
            "import evaluate as ev\n"
            "from warehouse_rl.disturb import resolve_disturb\n"
            "from warehouse_rl.recovery import normalise_recovery\n"
            "row = ev.run_seed('stuck_aware_cta', 'tarware-medium-8agvs-4pickers-globalobs-v1', 250, 2,\n"
            "                  disturb=resolve_disturb('breakdown-heavy')[1], recovery=normalise_recovery({'name': 'timeout'}))\n"
            "print(json.dumps([row['deliveries'], row['pick_rate']]))\n"
        ) % (ROOT / "src", ROOT / "scripts")
        zone = subprocess.run([sys.executable, "-c", code_zone], capture_output=True, text=True, check=True)
        ref = subprocess.run([sys.executable, "-c", code_ref], capture_output=True, text=True, check=True)
        z, r = json.loads(zone.stdout.splitlines()[-1]), json.loads(ref.stdout.splitlines()[-1])
        self.assertEqual(z[:2], r)
        self.assertGreater(z[0], 0)
        self.assertEqual(z[2], 12 * 250)

    def test_same_seed_twice_in_separate_processes_is_byte_identical(self):
        # inject: gzip mtime=None (wall clock) in FileSink, or default --t0 to the wall clock
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            for d in (a, b):
                r = cli("--zones", 2, "--steps", 60, "--speed", 0, "--sink", "file", "--dir", d, "--workers", 2)
                self.assertEqual(r.returncode, 0, r.stderr)
            names = sorted(p.name for p in Path(a).glob("zone*.jsonl.gz"))
            self.assertEqual(names, ["zone0-000.jsonl.gz", "zone1-000.jsonl.gz"])
            self.assertEqual(names, sorted(p.name for p in Path(b).glob("zone*.jsonl.gz")))
            for name in names:
                raw_a = gzip.decompress((Path(a) / name).read_bytes())
                raw_b = gzip.decompress((Path(b) / name).read_bytes())
                self.assertEqual(raw_a, raw_b)
                self.assertEqual(raw_a.count(b"\n"), 12 * 60)
                self.assertEqual((Path(a) / name).read_bytes(), (Path(b) / name).read_bytes())  # gzip mtime=0
            z0 = [json.loads(x) for x in gzip.decompress((Path(a) / names[0]).read_bytes()).splitlines()]
            z1 = [json.loads(x) for x in gzip.decompress((Path(a) / names[1]).read_bytes()).splitlines()]
            self.assertTrue(all(m["serialNumber"].startswith("Z0-") for m in z0))
            self.assertTrue(all(m["serialNumber"].startswith("Z1-") for m in z1))
            self.assertNotEqual([m["agvPosition"] for m in z0], [m["agvPosition"] for m in z1])  # seeds differ per zone


class TestCli(unittest.TestCase):
    def test_realtime_with_more_zones_than_workers_errors(self):
        # inject: drop the zones > workers check in emit.main
        with tempfile.TemporaryDirectory() as d:
            r = cli("--rate", "realtime", "--zones", 3, "--workers", 2, "--steps", 5, "--sink", "file", "--dir", d)
            self.assertEqual(r.returncode, 2)
            self.assertIn("workers", r.stderr)
            self.assertFalse(list(Path(d).iterdir()))  # nothing started
            r = cli("--rate", "realtime", "--zones", 2, "--workers", 2, "--steps", 5, "--speed", 0, "--sink", "file",
                    "--dir", d)  # zones == workers is allowed (speed 0 = flat out)
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_bad_disturb_errors(self):
        # inject: fall back to no disturbance on an unknown preset
        with tempfile.TemporaryDirectory() as d:
            for bad in ("no-such-preset", '{"breakdown": {"rate_per_hour": -1, "duration": [1, 2]}}', "{not json"):
                r = cli("--disturb", bad, "--steps", 5, "--dir", d)
                self.assertEqual(r.returncode, 2, bad)
                self.assertIn("error", r.stderr)
            self.assertFalse(list(Path(d).iterdir()))

    def test_t0_validation(self):
        # inject: accept any string as --t0
        r = cli("--t0", "yesterday", "--steps", 5, "--dir", tempfile.gettempdir() + "/s5a-never-created")
        self.assertEqual(r.returncode, 2)
        self.assertIn("--t0 must be", r.stderr)
        self.assertEqual(em.resolve_t0("2026-03-04T05:06:07Z"), "2026-03-04T05:06:07Z")
        self.assertRegex(em.resolve_t0("now"), r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")


class TestPacing(unittest.TestCase):
    def run_paced(self, **extra):
        sleeps, now = [], [100.0]

        def clock():
            return now[0]

        def sleep(s):
            sleeps.append(s)
            now[0] += s

        em.run_zone(zone_cfg(seed=0, steps=6, **extra), ListSink(), clock=clock, sleep=sleep)
        return sleeps, now[0] - 100.0

    def test_realtime_paces_against_the_schedule(self):
        # inject: sleep 5 / speed after every step (drift accumulates) instead of waiting for start + step * 5 / speed
        sleeps, elapsed = self.run_paced(rate="realtime", speed=2.0)
        self.assertAlmostEqual(elapsed, 5 * 5 / 2.0)  # step 5 is due at 5 * 5 s / speed; the sim itself takes 0 here
        self.assertEqual(len(sleeps), 5)  # step 0 is immediate

    def test_flat_and_speed_zero_never_sleep(self):
        # inject: treat speed 0 as realtime (divide by zero) or sleep in flat mode
        self.assertEqual(self.run_paced(rate="flat", speed=1.0)[0], [])
        self.assertEqual(self.run_paced(rate="realtime", speed=0)[0], [])


if __name__ == "__main__":
    unittest.main()

"""Tests for the S8F demo control file in the emitter (fleet/fleet_analyser/emitter.py, emit_ledger.py, fleet/emit.py).
Demo mode is NOT a measurement mode. Parsing / reader cases use a stub hook (no env); the realtime smoke and the CLI
cases run real envs, one at a time. Each case names the mutants (M11-M14 of the brief, plus the seam ones) it kills."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "fleet", ROOT / "src", ROOT / "scripts", ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fleet_analyser import emitter as em  # noqa: E402
from fleet_analyser.emit_ledger import EmitLedger  # noqa: E402
from warehouse_rl.disturb import resolve_disturb  # noqa: E402

EMIT = str(ROOT / "fleet" / "emit.py")
SMALL = "tarware-small-4agvs-2pickers-globalobs-v1"


class StubHook:
    grid_size = (10, 20)  # (rows, cols)
    num_agents = 6

    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def inject_floor(self, cells):
        if self.fail:
            raise ValueError("seam says no")
        self.calls.append(("floor", cells))

    def inject_breakdown(self, agent_id, duration):
        if self.fail:
            raise ValueError("seam says no")
        self.calls.append(("breakdown", agent_id, duration))


def j(**kw):
    return json.dumps(kw)


class ReaderCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "ctl.jsonl"
        self.logs = []
        self.hook = StubHook()

    def reader(self, zone=0, steps=100, hook=None):
        return em.ControlReader(self.path, zone, steps, hook or self.hook, log=self.logs.append)

    def write(self, *lines, raw=None):
        with open(self.path, "ab") as f:
            f.write(raw if raw is not None else "".join(line + "\n" for line in lines).encode())


class TestControlParsing(ReaderCase):
    def test_missing_file_means_no_commands(self):
        r = self.reader()
        self.assertEqual(r.poll(0), 0)
        self.write(j(t=None, floor={"1,1": 0.5}))
        self.assertEqual(r.poll(1), 1)  # the file appearing later is picked up

    def test_valid_lines_and_preexisting_lines(self):
        self.write(j(t=None, floor={"5,3": 0.9, "6,3": 1}), j(t=None, breakdown={"agent": 2, "duration": 7}))
        r = self.reader()
        self.assertEqual(r.poll(0), 2)  # initial offset 0: lines already in the file are applied
        self.assertEqual(self.hook.calls, [("floor", {(5, 3): 0.9, (6, 3): 1.0}), ("breakdown", 2, 7)])
        self.assertEqual(r.injections, [
            dict(step=0, kind="floor", payload={"5,3": 0.9, "6,3": 1.0}),
            dict(step=0, kind="breakdown", payload=dict(agent=2, duration=7))])
        self.assertEqual((r.malformed, r.unapplied), (0, 0))

    def test_offset_advances_and_lines_apply_once(self):  # kills M11
        self.write(j(t=None, floor={"1,1": 0.5}))
        r = self.reader()
        self.assertEqual(r.poll(0), 1)
        self.assertEqual(r.poll(1), 0)
        self.assertEqual(r.poll(2), 0)
        self.write(j(t=None, floor={"2,2": 0.5}))
        self.assertEqual(r.poll(3), 1)
        self.assertEqual(len(self.hook.calls), 2)
        self.assertEqual([i["step"] for i in r.injections], [0, 3])

    def test_partial_trailing_line_waits(self):  # kills M12
        full = j(t=None, floor={"1,1": 0.5})
        self.write(raw=(full + "\n" + full[:15]).encode())
        r = self.reader()
        self.assertEqual(r.poll(0), 1)
        self.assertEqual(r.poll(1), 0)
        self.assertEqual(r.malformed, 0)  # a half line is not malformed yet
        self.write(raw=full[15:].encode())
        self.assertEqual(r.poll(2), 0)  # still no newline
        self.write(raw=b"\n")
        self.assertEqual(r.poll(3), 1)
        self.assertEqual([i["step"] for i in r.injections], [0, 3])
        self.assertEqual(r.malformed, 0)

    def test_future_t_is_held_until_its_step(self):  # kills M14
        self.write(j(t=10, breakdown={"agent": 1, "duration": 3}), j(t=2, floor={"1,1": 0.5}))
        r = self.reader()
        self.assertEqual(r.poll(5), 1)  # t=2 <= 5: now
        self.assertEqual(r.poll(9), 0)
        self.assertEqual(self.hook.calls, [("floor", {(1, 1): 0.5})])
        self.assertEqual(r.poll(10), 1)
        self.assertEqual(r.injections[-1], dict(step=10, kind="breakdown", payload=dict(agent=1, duration=3)))
        self.assertEqual(r.poll(11), 0)

    def test_zone_filter(self):  # kills M13
        self.write(j(t=None, zone=1, floor={"1,1": 0.5}), j(t=None, zone=0, breakdown={"agent": 1, "duration": 2}),
                   j(t=None, floor={"3,3": 0.5}))
        r0, r1 = self.reader(zone=0, hook=StubHook()), self.reader(zone=1, hook=StubHook())
        self.assertEqual(r0.poll(0), 2)
        self.assertEqual(r1.poll(0), 2)
        self.assertEqual([i["kind"] for i in r0.injections], ["breakdown", "floor"])
        self.assertEqual([i["payload"] for i in r1.injections], [{"1,1": 0.5}, {"3,3": 0.5}])
        self.assertEqual((r0.malformed, r1.malformed), (0, 0))

    def test_malformed_lines_are_counted_logged_and_skipped(self):
        bad = ["not json", "[1, 2]", '"x"', "null", j(floor={"1,1": 0.5}), j(t=None),
               j(t=None, floor={"1,1": 0.5}, breakdown={"agent": 1, "duration": 2}),
               j(t=None, floor={"1,1": 0.5}, extra=1), j(t="5", floor={"1,1": 0.5}), j(t=True, floor={"1,1": 0.5}),
               j(t=1.5, floor={"1,1": 0.5}), j(t=None, zone="0", floor={"1,1": 0.5}),
               j(t=None, zone=True, floor={"1,1": 0.5}), j(t=None, floor=[]), j(t=None, floor={}),
               j(t=None, floor={"1,1": 1.5}), j(t=None, floor={"1,1": -0.1}), j(t=None, floor={"1,1": True}),
               j(t=None, floor={"1,1": "0.5"}), j(t=None, floor={"a,b": 0.5}), j(t=None, floor={"1": 0.5}),
               j(t=None, floor={"20,1": 0.5}), j(t=None, floor={"1,10": 0.5}), j(t=None, floor={"-1,1": 0.5}),
               j(t=None, floor={"1,1": 0.5, "99,1": 0.5}),
               j(t=None, breakdown={"agent": 0, "duration": 2}), j(t=None, breakdown={"agent": 7, "duration": 2}),
               j(t=None, breakdown={"agent": 1, "duration": 0}), j(t=None, breakdown={"agent": 1.0, "duration": 2}),
               j(t=None, breakdown={"agent": True, "duration": 2}), j(t=None, breakdown={"agent": 1}),
               j(t=None, breakdown={"agent": 1, "duration": 2, "x": 1}), j(t=None, breakdown=[1, 2]),
               j(t=100, zone=0, breakdown={"agent": 9, "duration": 2})]
        self.write(*bad)
        self.write(raw=b"\n   \n\t\n")  # blank lines: ignored, not counted
        self.write(j(t=None, floor={"1,1": 0.5}))
        r = self.reader()
        self.assertEqual(r.poll(0), 1)
        self.assertEqual(r.malformed, len(bad))
        self.assertEqual(len(self.logs), len(bad))
        self.assertTrue(all("malformed" in m for m in self.logs))
        self.assertEqual(r.unapplied, 0)

    def test_malformed_with_invalid_utf8(self):
        self.write(raw=b"\xff\xfe\n")
        r = self.reader()
        self.assertEqual(r.poll(0), 0)
        self.assertEqual(r.malformed, 1)

    def test_seam_value_error_is_malformed_not_fatal(self):
        self.write(j(t=None, floor={"1,1": 0.5}), j(t=None, breakdown={"agent": 1, "duration": 2}))
        r = self.reader(hook=StubHook(fail=True))
        self.assertEqual(r.poll(0), 0)
        self.assertEqual(r.malformed, 2)
        self.assertEqual(r.injections, [])

    def test_commands_at_or_after_steps_are_unapplied(self):
        self.write(j(t=10, floor={"1,1": 0.5}), j(t=11, floor={"1,1": 0.5}), j(t=9, floor={"1,1": 0.5}),
                   j(t=50, zone=3, floor={"1,1": 0.5}))
        r = self.reader(steps=10)
        self.assertEqual(r.poll(0), 0)
        self.assertEqual(r.unapplied, 2)  # the zone-3 line is not this zone's
        self.assertEqual(r.poll(9), 1)
        self.assertEqual(r.unapplied, 2)


class TestTruthAndLedger(unittest.TestCase):
    RUN = dict(env_id="e", disturb_tag="none", disturb={}, steps=5, seed_base=0)
    RES = {0: dict(seed=0, floor_cells={}, floor_skips=[0] * 5, injections=[dict(step=1, kind="floor", payload={"1,1": 1.0})],
                   malformed_commands=2, unapplied_commands=1)}

    def truth(self, run):
        with tempfile.TemporaryDirectory() as d:
            em.write_truth(Path(d) / "truth.json", run, self.RES)
            return json.loads((Path(d) / "truth.json").read_text())

    def test_truth_keys(self):
        demo = self.truth(dict(self.RUN, demo_mode=True, control_file="x"))["zones"]["0"]
        self.assertEqual(demo["injections"], self.RES[0]["injections"])
        self.assertEqual((demo["malformed_commands"], demo["unapplied_commands"]), (2, 1))
        plain = self.truth(self.RUN)
        self.assertEqual(list(plain["zones"]["0"]),
                         ["seed", "floor_cells", "floor_skips", "floor_skips_total"])  # exactly master's keys

    def test_ledger_keys_and_live_injections(self):
        cfg = dict(seed_base=0)
        snap = dict(messages=4, robots=2, steps_done=1)
        with tempfile.TemporaryDirectory() as d:
            plain = EmitLedger(Path(d) / "l.json", cfg, 2, 5)
            plain.update(0, dict(snap, injections=9), "running")
            doc = plain.document("running")
            self.assertEqual(list(doc), ["status", "config", "zones", "total", "truth"])
            self.assertEqual(list(doc["zones"][0]), ["zone", "status", "seed", "messages", "expected_messages", "complete",
                                                     "bytes_uncompressed", "bytes_compressed", "delivered",
                                                     "delivery_failed", "robots", "agvs", "pickers", "steps",
                                                     "steps_done", "first_timestamp", "last_timestamp", "files"])
            demo = EmitLedger(Path(d) / "l.json", cfg, 2, 5, demo_mode=True)
            self.assertEqual(demo.document("running")["injections"], 0)
            demo.update(0, dict(snap, injections=2), "running")
            demo.update(1, dict(snap, injections=3), "running")
            doc = demo.document("running")
            self.assertIs(doc["demo_mode"], True)
            self.assertEqual((doc["injections"], doc["zones"][0]["injections"], doc["zones"][1]["injections"]), (5, 2, 3))
            demo.update(0, dict(snap, injections=4), "running")  # live update through a later snapshot
            self.assertEqual(demo.document("running")["injections"], 7)
            demo.update(1, None, "failed")  # a None snapshot keeps the count
            self.assertEqual(demo.document("failed")["zones"][1]["injections"], 3)


class TestRealtimeSmoke(unittest.TestCase):
    def test_line_appended_during_the_run_takes_effect_at_its_step(self):
        steps = 60
        _, disturb = resolve_disturb("none")
        with tempfile.TemporaryDirectory() as d:
            ctl = Path(d) / "ctl.jsonl"
            lines, events, results = [], {}, {}

            class Sink:
                def write(self, serial, line, timestamp=None, header_id=None):
                    lines.append(line)

                def stats(self):
                    return dict(messages=len(lines), bytes_uncompressed=0, bytes_compressed=None, files=[])

                def close(self):
                    pass

            def on_step(step, env, info):
                events[step] = info["injected_events"]
                if step == 10:
                    with open(ctl, "a") as f:
                        f.write(j(t=20, floor={f"{x},{y}": 0.0 for x, y in env.env._blockable_cells[:3]}) + "\n")
                        f.write(j(t=30, breakdown={"agent": 1, "duration": 5}) + "\n")

            cfg = dict(zone=0, seed=1, steps=steps, env_id=SMALL, policy="stuck_aware_cta", disturb=disturb,
                       recovery={"name": "timeout", "call_human_cost": 60}, t0=em.DEFAULT_T0, rate="realtime",
                       speed=50, demo_mode=True, control_file=str(ctl))
            res = em.run_zone(cfg, Sink(), on_step=on_step)
        self.assertEqual({s for s, v in events.items() if v}, {20, 30})
        self.assertEqual(events[20], 1)
        self.assertEqual(events[30], 1)
        self.assertEqual([(i["step"], i["kind"]) for i in res["injections"]], [(20, "floor"), (30, "breakdown")])
        self.assertEqual((res["malformed_commands"], res["unapplied_commands"]), (0, 0))
        self.assertEqual(res["snapshot"]["injections"], 2)
        msgs = [json.loads(x) for x in lines]
        n = len(msgs) // steps
        self.assertEqual(len(msgs), n * steps)
        errs = [bool(msgs[s * n + 0]["errors"]) for s in range(steps)]  # Z0-01 = agent id 1
        self.assertEqual([s for s, e in enumerate(errs) if e], [30, 31, 32, 33, 34])
        self.assertTrue(all(m["errors"] == [em.ERROR] for m in msgs[30 * n:35 * n:n]))
        for m in msgs:  # nothing identifies a command or an injection
            blob = json.dumps(m).lower()
            self.assertNotIn("inject", blob)
            self.assertNotIn("control", blob)
            self.assertEqual(list(m), list(em.TOP_KEYS))


class TestPollBeforeAct(unittest.TestCase):
    def test_injection_is_visible_to_the_policy_at_its_step(self):
        # (B): the control file is polled BEFORE pol.act, so the policy of step t already sees a breakdown injected for
        # step t (StuckAwareCta reads frozen_now() at act time). Kills "poll moved after pol.act".
        import evaluate as ev
        from unittest import mock

        seen = {}
        real = ev.make_policy

        def recording_make_policy(name, seed):
            pol = real(name, seed)
            act, reset = pol.act, pol.reset
            box = {}

            def rec_reset(env):
                box["env"] = env
                return reset(env)

            def rec_act(obs, mask, info):
                seen[len(seen)] = bool(box["env"].env.frozen_now()[0])
                return act(obs, mask, info)

            pol.reset, pol.act = rec_reset, rec_act
            return pol

        class Sink:
            def write(self, *a, **k):
                pass

            def stats(self):
                return dict(messages=0, bytes_uncompressed=0, bytes_compressed=0, files=[], delivered=None,
                            delivery_failed=None)

            def close(self):
                pass

        _, disturb = resolve_disturb("none")
        with tempfile.TemporaryDirectory() as d:
            ctl = Path(d) / "ctl.jsonl"
            ctl.write_text(j(t=5, breakdown={"agent": 1, "duration": 3}) + "\n")
            cfg = dict(zone=0, seed=0, steps=12, env_id=SMALL, policy="stuck_aware_cta", disturb=disturb,
                       recovery={"name": "timeout", "call_human_cost": 60}, t0=em.DEFAULT_T0, demo_mode=True,
                       control_file=str(ctl))
            with mock.patch.object(ev, "make_policy", recording_make_policy):
                res = em.run_zone(cfg, Sink())
        self.assertEqual([i["step"] for i in res["injections"]], [5])
        self.assertEqual([s for s in sorted(seen) if seen[s]], [5, 6, 7])


def cli(*args):
    return subprocess.run([sys.executable, EMIT, *map(str, args)], capture_output=True, text=True, timeout=300)


class TestCli(unittest.TestCase):
    def test_flags_need_each_other(self):
        with tempfile.TemporaryDirectory() as d:
            for args in (["--demo"], ["--control-file", str(Path(d) / "c")]):
                r = cli(*args, "--dir", d)
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertIn("--demo and --control-file", r.stderr)

    def test_demo_subprocess_realtime_and_plain_run(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            ctl = d / "ctl.jsonl"
            ctl.write_text(j(t=None, floor={"2,2": 0.5}) + "\n" + j(t=3, breakdown={"agent": 2, "duration": 4}) + "\n"
                           + "garbage\n" + j(t=99, floor={"2,2": 0.5}) + "\n")
            r = cli("--demo", "--control-file", ctl, "--rate", "realtime", "--speed", 100, "--env", SMALL, "--steps",
                    15, "--zones", "1", "--workers", 1, "--dir", d / "out", "--disturb", "none")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("malformed control line", r.stderr)
            ledger = json.loads((d / "out" / "emit_ledger.json").read_text())
            self.assertIs(ledger["demo_mode"], True)
            self.assertEqual((ledger["injections"], ledger["zones"][0]["injections"]), (2, 2))
            self.assertEqual(ledger["config"]["control_file"], str(ctl))
            self.assertIs(ledger["config"]["demo_mode"], True)
            z = json.loads((d / "out" / "truth.json").read_text())["zones"]["0"]
            self.assertEqual([(i["step"], i["kind"]) for i in z["injections"]], [(0, "floor"), (3, "breakdown")])
            self.assertEqual((z["malformed_commands"], z["unapplied_commands"]), (1, 1))
            p = cli("--env", SMALL, "--steps", 5, "--zones", "1", "--workers", 1, "--dir", d / "plain", "--disturb", "none")
            self.assertEqual(p.returncode, 0, p.stderr)
            doc = json.loads((d / "plain" / "emit_ledger.json").read_text())
            self.assertNotIn("demo_mode", doc)
            self.assertNotIn("injections", doc)
            self.assertNotIn("demo_mode", doc["config"])
            self.assertNotIn("control_file", doc["config"])
            tz = json.loads((d / "plain" / "truth.json").read_text())["zones"]["0"]
            self.assertEqual(list(tz), ["seed", "floor_cells", "floor_skips", "floor_skips_total"])


if __name__ == "__main__":
    unittest.main()

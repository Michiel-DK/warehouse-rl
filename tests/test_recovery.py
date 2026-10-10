"""Tests for the recovery hook (src/warehouse_rl/recovery.py). Envs run strictly one at a time (global np.random,
Agent.counter and Shelf.counter are shared). Each case names its red-demonstration in a comment.

Terms: a STUCK event is a moving_agents-filter agent with StuckCounter.count > 0 after update; a CLASH event is the
vendor blocked-agent branch entered when other.fixing_clash == 0 (W:461). Neither is info["stuck_agents"] or info["stucks"].
"""
import importlib.util
import json
import math
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import gymnasium as gym
import numpy as np

from tarware.warehouse import Warehouse
from warehouse_rl import recovery as rc
from warehouse_rl.disturb import DisturbedWarehouse
from warehouse_rl.env import WarehouseEnv
from warehouse_rl.policy import StuckAwareCtaPolicy

_spec = importlib.util.spec_from_file_location("evaluate_script", ROOT / "scripts" / "evaluate.py")
ev = importlib.util.module_from_spec(_spec)
sys.modules["evaluate_script"] = ev  # multiprocessing pickles evaluate._job by module name
_spec.loader.exec_module(ev)

SMALL = "tarware-small-4agvs-2pickers-globalobs-v1"
MEDIUM = "tarware-medium-8agvs-4pickers-globalobs-v1"
BREAKDOWN = {"breakdown": {"rate_per_hour": 8.0, "duration": [20, 60]}}
HEAVY = {"breakdown": {"rate_per_hour": 20, "duration": [10, 30]}, "delay": {"p_skip": 0.3}}
STEPS = {SMALL: 500, MEDIUM: 300}
SEEDS = range(10)
CELLS = [(env_id, name, cfg) for env_id in (SMALL, MEDIUM) for name, cfg in (("none", {}), ("breakdown", BREAKDOWN))]
TRACE_KEYS = ("shelf_deliveries", "clashes", "stucks", "abandoned_tasks", "stuck_busy_agents", "frozen_agents")


def _is_num(v):
    return isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, bool)


def run(env_id, disturb, seed, steps, recovery=None, policy=None, swap=None, per_step=None):
    """One episode with StuckAwareCtaPolicy. recovery=None: DisturbedWarehouse. swap: a RecoveryPolicy installed on the
    hook after construction. per_step(env_e, info) is called after every step. Returns dict(trace, totals, final)."""
    env = WarehouseEnv(env_id, max_steps=steps, disturb=disturb, recovery=recovery)
    try:
        if swap is not None:
            env.env._recovery = None if swap == "none" else swap
        pol = policy or StuckAwareCtaPolicy()
        obs, info = env.reset(seed=seed)
        pol.reset(env)
        trace, totals = [], {}
        for _ in range(steps):
            obs, _, _, _, info = env.step(pol.act(obs, info["action_mask"], info))
            e = env.env
            trace.append((tuple((a.x, a.y, a.dir) for a in e.agents),) + tuple(info[k] for k in TRACE_KEYS))
            for k, v in info.items():
                if _is_num(v):
                    totals[k] = totals.get(k, 0) + v
            if per_step:
                per_step(e, info)
        final = {k: v for k, v in info.items() if isinstance(v, list)}
        return dict(trace=trace, totals=totals, final=final, decide_calls=getattr(env.env, "decide_calls", None))
    finally:
        env.close()


def timeout_cfg():
    return rc.normalise_recovery({"name": "timeout"})


_CACHE = {}


def cached(kind, env_id, name, disturb, seed):
    key = (kind, env_id, name, seed)
    if key not in _CACHE:
        steps = STEPS[env_id]
        if kind == "plain":
            _CACHE[key] = run(env_id, disturb, seed, steps)
        elif kind == "timeout":
            _CACHE[key] = run(env_id, disturb, seed, steps, recovery=timeout_cfg())
        else:
            r, a = kind
            cfg = rc.normalise_recovery({"name": "tuned_timeout", "replan": r, "abandon": a})
            _CACHE[key] = run(env_id, disturb, seed, steps, recovery=cfg)
    return _CACHE[key]


_T0 = time.time()


def tearDownModule():
    print(f"\n[test_recovery.py wall time: {time.time() - _T0:.1f} s]")


class RegressionTests(unittest.TestCase):
    # red-demonstration: change `c > self.abandon` to `c >= self.abandon` in TunedTimeoutRecovery.decide (removes the
    # dead step at c == abandon) -> test_timeout_equals_unhooked goes red on at least one cell.
    def test_mro(self):
        # red: `class RecoveryHook(_HookedVendor, DisturbedWarehouse)` -> DisturbedWarehouse's super() calls skip the ports
        # (and the order assertion goes red).
        self.assertEqual(rc.RecoveryHook.__mro__[:4],
                         (rc.RecoveryHook, DisturbedWarehouse, rc._HookedVendor, Warehouse))

    def test_timeout_equals_unhooked(self):
        for env_id, name, cfg in CELLS:
            reroutes = abandons = stucks = clashes = decides = stuck_events = 0
            for seed in SEEDS:
                with self.subTest(env=env_id, disturb=name, seed=seed):
                    plain = cached("plain", env_id, name, cfg, seed)
                    hooked = cached("timeout", env_id, name, cfg, seed)
                    self.assertGreaterEqual(len(hooked["trace"]), 300)
                    self.assertEqual(plain["trace"], hooked["trace"])
                    # episode totals of every numeric info key the UNHOOKED env emits, plus list-valued final state
                    for k, v in plain["totals"].items():
                        self.assertEqual(v, hooked["totals"][k], k)
                    self.assertEqual(plain["final"], hooked["final"])
                    t = hooked["totals"]
                    reroutes += t["recovery_reroute"]
                    abandons += t["recovery_abandon"]
                    stucks += t["stucks"]
                    clashes += t["recovery_clash_events"]
                    stuck_events += t["recovery_stuck_events"]
                    decides += hooked["decide_calls"]
                    self.assertEqual(hooked["decide_calls"], t["recovery_stuck_events"] + t["recovery_clash_events"])
            # non-vacuous, pooled over the 10 seeds of the (map, disturb) cell
            with self.subTest(env=env_id, disturb=name, pooled=True):
                self.assertGreater(reroutes, 0)
                self.assertGreater(abandons, 0)
                self.assertGreater(stucks, 0)
                self.assertGreater(clashes, 0)
                self.assertGreater(decides, 100)

    def test_tuned_variants_differ(self):
        # red: if the hook ignored the parameters (e.g. TunedTimeoutRecovery.decide hard-coded 5/15) these go red.
        # Pooled over the 10 seeds of each (map, disturb) cell; (5,14) rests on rare c == 14 steps.
        for kind in ((5, 14), (4, 15)):
            for env_id, name, cfg in CELLS:
                with self.subTest(kind=kind, env=env_id, disturb=name):
                    differs = any(cached(kind, env_id, name, cfg, s)["trace"] != cached("timeout", env_id, name, cfg, s)["trace"]
                                  for s in SEEDS)
                    self.assertTrue(differs)

    def test_tuned_5_15_equals_timeout(self):
        # red: make TimeoutRecovery use abandon 14 -> this goes red.
        for seed in range(4):
            cfg = rc.normalise_recovery({"name": "tuned_timeout", "replan": 5, "abandon": 15})
            a = run(SMALL, BREAKDOWN, seed, 300, recovery=cfg)
            b = cached("timeout", SMALL, "breakdown", BREAKDOWN, seed) if STEPS[SMALL] == 300 else run(
                SMALL, BREAKDOWN, seed, 300, recovery=timeout_cfg())
            self.assertEqual(a["trace"], b["trace"])
            self.assertEqual(a["totals"], b["totals"])

    def test_invalid_parameters(self):
        for r, a in ((5, 5), (6, 5), (-1, 3), (5.0, 15), ("5", 15), (True, 15), (5, None)):
            with self.subTest(r=r, a=a):
                with self.assertRaises(ValueError):
                    rc.TunedTimeoutRecovery(r, a)
        with self.assertRaises(ValueError):
            WarehouseEnv(SMALL, max_steps=5, disturb={}, recovery={"name": "tuned_timeout", "replan": 9, "abandon": 3})

    def test_timeout_recovery_rejects_other_layouts(self):
        # red: drop the layout check in RecoveryHook.__init__ -> this goes red.
        kwargs = dict(gym.spec(SMALL).kwargs)
        kwargs["max_steps"] = 5
        kwargs["column_height"] = 5  # 5 + 5 + 2 != 15
        with self.assertRaises(ValueError):
            rc.RecoveryHook(disturb={}, recovery=rc.TimeoutRecovery(), **kwargs)
        rc.RecoveryHook(disturb={}, recovery=rc.TunedTimeoutRecovery(5, 12), **kwargs).close()


class SpyCallHuman:
    """Installs a spy around hook._relocate; records (agent id, before cell, executed) per call."""

    def __init__(self, hook):
        self.calls = []
        orig = hook._relocate

        def spy(agent):
            before = (agent.x, agent.y)
            ok = orig(agent)
            self.calls.append((agent.id, before, ok))
            return ok

        hook._relocate = spy


class StuckHuman(rc.RecoveryPolicy):
    """call_human at every stuck event with path_len > 0; otherwise the vendor timeout rule."""
    name = "stuck_human"

    def __init__(self):
        self.base = rc.TimeoutRecovery()

    def decide(self, obs):
        if not obs["event_is_clash"] and obs["path_len"] > 0:
            return "call_human"
        return self.base.decide(obs)


class CallHumanTests(unittest.TestCase):
    def _run(self, cost):
        # red: drop `self._counts["call_human_steps"] += ...` or the counter reset in _relocate -> asserts go red.
        cfg = rc.normalise_recovery({"name": "timeout", "call_human_cost": cost})
        env = WarehouseEnv(SMALL, max_steps=300, disturb=BREAKDOWN, recovery=cfg)
        hook = env.env
        hook._recovery = StuckHuman()
        spy = SpyCallHuman(hook)
        pol = StuckAwareCtaPolicy()
        obs, info = env.reset(seed=1)
        pol.reset(env)
        executed_total = charged_total = deliveries = 0
        checked = 0
        for _ in range(300):
            n0 = len(spy.calls)
            obs, _, _, _, info = env.step(pol.act(obs, info["action_mask"], info))
            new = spy.calls[n0:]
            done = [c for c in new if c[2]]
            self.assertEqual(info["call_human_steps"], cost * len(done))
            for agent_id, before, _ in done:
                a = hook.agents[agent_id - 1]
                self.assertNotEqual((a.x, a.y), before)
                self.assertEqual(hook.stuck_counters[agent_id - 1].count, 0)
                if a.carrying_shelf:
                    self.assertEqual((a.carrying_shelf.x, a.carrying_shelf.y), (a.x, a.y))
                checked += 1
            executed_total += len(done)
            charged_total += info["call_human_steps"]
            deliveries += info["shelf_deliveries"]
        env.close()
        self.assertGreater(checked, 0, "no executed call_human in this run")
        self.assertEqual(charged_total, cost * executed_total)
        return deliveries, executed_total

    def test_two_costs(self):
        d60, n60 = self._run(60)
        d7, n7 = self._run(7)
        # cost is accounting only: same dynamics, same deliveries, same pick-rate
        self.assertEqual((d60, n60), (d7, n7))
        self.assertEqual(d60 * 3600 / (5 * 300), d7 * 3600 / (5 * 300))


class CyclingPolicy(rc.RecoveryPolicy):
    name = "cycle"

    def __init__(self):
        self.keys_ok = True
        self.n = 0

    def decide(self, obs):
        if tuple(obs) != rc.RecoveryHook.OBS_KEYS or not all(type(v) is float and math.isfinite(v) for v in obs.values()):
            self.keys_ok = False
        self.n += 1
        return rc.ACTIONS[(int(obs["stuck_count"]) + self.n) % 5]


class SafetyTests(unittest.TestCase):
    def test_cycling_policy_is_safe(self):
        # red: let _cell_free ignore agent positions (drop the `a.x, a.y == cell` test) -> back_off/call_human put two
        # same-type agents on one cell and the overlap assert goes red.
        for env_id in (SMALL, MEDIUM):
            events = {a: 0 for a in rc.ACTIONS}
            for seed in range(10):
                pol = CyclingPolicy()
                viol = []

                def check(e, info):
                    n_agv = e.num_agvs
                    pos = [(a.x, a.y) for a in e.agents]
                    if len(set(pos[:n_agv])) < n_agv or len(set(pos[n_agv:])) < e.num_agents - n_agv:
                        viol.append("overlap")
                    for a in e.agents:
                        if a.carrying_shelf and (a.carrying_shelf.x, a.carrying_shelf.y) != (a.x, a.y):
                            viol.append("shelf")
                    s = sum(info["recovery_" + a] for a in rc.ACTIONS)
                    if s != info["recovery_stuck_events"] + info["recovery_clash_events"]:
                        viol.append("counts")
                    for a in rc.ACTIONS:
                        events[a] += info["recovery_" + a]

                run(env_id, HEAVY, seed, 200, recovery=timeout_cfg(), swap=pol, per_step=check)
                with self.subTest(env=env_id, seed=seed):
                    self.assertEqual(viol, [])
                    self.assertTrue(pol.keys_ok)
            for a in rc.ACTIONS:  # the safety run really exercised every action
                self.assertGreater(events[a], 0, (env_id, a))

    def test_observation_is_pure(self):
        # red: call self.find_path inside _observe, or np.random in it -> this goes red.
        env = WarehouseEnv(SMALL, max_steps=120, disturb=BREAKDOWN, recovery=timeout_cfg())
        try:
            pol = StuckAwareCtaPolicy()
            obs, info = env.reset(seed=3)
            pol.reset(env)
            for _ in range(80):
                obs, _, _, _, info = env.step(pol.act(obs, info["action_mask"], info))
            hook = env.env
            state = np.random.get_state()
            snap = [(a.x, a.y, list(a.path), a.req_action, a.busy, hook.stuck_counters[a.id - 1].count) for a in hook.agents]
            with mock.patch.object(hook, "find_path", side_effect=AssertionError("find_path called")):
                for a in hook.agents:
                    for clash in (False, True):
                        o = hook._observe(a, clash)
                        self.assertEqual(tuple(o), rc.RecoveryHook.OBS_KEYS)
            after = np.random.get_state()
            self.assertTrue(state[0] == after[0] and (state[1] == after[1]).all() and state[2:] == after[2:])
            self.assertEqual(snap, [(a.x, a.y, list(a.path), a.req_action, a.busy, hook.stuck_counters[a.id - 1].count)
                                    for a in hook.agents])
        finally:
            env.close()


class InertTests(unittest.TestCase):
    def test_recovery_none_builds_pre_pr_types(self):
        # red: make WarehouseEnv always build RecoveryHook -> type asserts go red.
        e = WarehouseEnv(SMALL, max_steps=5, disturb={}, recovery=None)
        self.assertIs(type(e.env), DisturbedWarehouse)
        self.assertNotIn("recovery_wait", e.env.step([0] * e.num_agents)[4] if e.reset(seed=0) else {})
        e.close()
        e = WarehouseEnv(SMALL, max_steps=5)
        self.assertIs(type(e.env), Warehouse)
        e.close()

    def test_hook_with_recovery_none_is_inert(self):
        # red: let the ports call decide when _recovery is None -> decide_calls > 0 / trace differs.
        plain = run(SMALL, BREAKDOWN, 2, 300)
        hooked = run(SMALL, BREAKDOWN, 2, 300, recovery=timeout_cfg(), swap="none")
        self.assertEqual(plain["trace"], hooked["trace"])
        self.assertEqual(hooked["decide_calls"], 0)
        for k in rc.RECOVERY_INFO_KEYS:
            self.assertEqual(hooked["totals"][k], 0)

    def test_recovery_needs_disturb(self):
        # red: drop the check in WarehouseEnv.__init__ -> gym.make path silently ignores recovery.
        with self.assertRaises(ValueError):
            WarehouseEnv(SMALL, max_steps=5, disturb=None, recovery=timeout_cfg())

    def test_hooked_env_always_has_keys(self):
        e = WarehouseEnv(SMALL, max_steps=5, disturb={}, recovery=timeout_cfg())
        e.reset(seed=0)
        info = e.step([0] * e.num_agents)[4]
        for k in rc.RECOVERY_INFO_KEYS:
            self.assertEqual(info[k], 0)
        e.close()


class SpecTests(unittest.TestCase):
    def test_resolve(self):
        self.assertEqual(rc.resolve_recovery("timeout"), ("timeout", {"name": "timeout", "call_human_cost": 60}))
        tag, cfg = rc.resolve_recovery('{"name": "tuned_timeout", "replan": 4, "abandon": 15}')
        self.assertRegex(tag, r"^rec-[0-9a-f]{10}$")
        self.assertEqual(cfg, {"name": "tuned_timeout", "replan": 4, "abandon": 15, "call_human_cost": 60})
        tag2, _ = rc.resolve_recovery('{"call_human_cost": 60, "abandon": 15, "replan": 4, "name": "tuned_timeout"}')
        self.assertEqual(tag, tag2)

    def test_malformed(self):
        bad = ["", "bogus", "{", '{"name": "nope"}', '{"name": "tuned_timeout", "replan": 5}',
               '{"name": "tuned_timeout", "replan": 5, "abandon": 5}', '{"name": "tuned_timeout", "replan": -1, "abandon": 5}',
               '{"name": "tuned_timeout", "replan": true, "abandon": 5}', '{"name": "tuned_timeout", "replan": 1.5, "abandon": 5}',
               '{"name": "tuned_timeout", "replan": 1, "abandon": 5, "extra": 1}',
               '{"name": "timeout", "replan": 5}', '{"name": "timeout", "call_human_cost": -1}',
               '{"name": "timeout", "call_human_cost": 1.5}', "[]", "5"]
        for spec in bad:
            with self.subTest(spec=spec):
                with self.assertRaises(ValueError):
                    rc.resolve_recovery(spec)
        with self.assertRaises(ValueError):
            rc.resolve_recovery(5)


class EvaluateTests(unittest.TestCase):
    # red: drop `_check_same_recovery` -> the resume test goes red; drop the policy check -> test_needs_stuck_aware goes red.
    def test_needs_stuck_aware(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                ev.evaluate("cta", SMALL, 50, [0], 1, d, "none", "timeout")
            with self.assertRaises(ValueError):
                ev.evaluate("random", SMALL, 50, [0], 1, d, "none", "timeout")
            self.assertEqual(list(Path(d).iterdir()), [])

    def test_recovery_run_files_and_rows(self):
        with tempfile.TemporaryDirectory() as d:
            ev.evaluate("stuck_aware_cta", SMALL, 50, [0, 1], 1, d, "none", "timeout")
            path = Path(d) / f"stuck_aware_cta_{SMALL}_50_timeout.json"
            doc = json.loads(path.read_text())
            self.assertEqual(doc["recovery"], {"name": "timeout", "call_human_cost": 60})
            self.assertEqual(doc["recovery_tag"], "timeout")
            self.assertEqual(doc["disturb"], {})
            for r in doc["rows"]:
                self.assertEqual(r["recovery"], doc["recovery"])
                for k in ev.RECOVERY_SUMS:
                    self.assertIn(k, r)
                self.assertEqual(r["recovery_wait"] + r["recovery_back_off"] + r["recovery_reroute"] + r["recovery_abandon"]
                                 + r["recovery_call_human"], r["recovery_stuck_events"] + r["recovery_clash_events"])
                self.assertEqual(r["pick_rate"], r["deliveries"] * 3600 / (5 * 50))
            # disturbed + JSON spec: tag in filename, disturb tag before the recovery tag
            spec = '{"name": "tuned_timeout", "replan": 4, "abandon": 15, "call_human_cost": 9}'
            rtag, rcfg = rc.resolve_recovery(spec)
            from warehouse_rl.disturb import resolve_disturb
            dt, _ = resolve_disturb("breakdown-heavy")
            ev.evaluate("stuck_aware_cta", SMALL, 50, [0], 1, d, "breakdown-heavy", spec)
            path2 = Path(d) / f"stuck_aware_cta_{SMALL}_50_{dt}_{rtag}.json"
            doc2 = json.loads(path2.read_text())
            self.assertEqual(doc2["recovery"], rcfg)
            self.assertEqual(doc2["rows"][0]["recovery"], rcfg)
            # resume with a different stored recovery config at the same filename refuses
            doc2["recovery"] = dict(rcfg, call_human_cost=10)
            path2.write_text(json.dumps(doc2))
            with self.assertRaises(ValueError):
                ev.evaluate("stuck_aware_cta", SMALL, 50, [0, 1], 1, d, "breakdown-heavy", spec)
            # resume with the same config adds only the missing seed
            doc2["recovery"] = rcfg
            path2.write_text(json.dumps(doc2))
            ev.evaluate("stuck_aware_cta", SMALL, 50, [0, 1], 1, d, "breakdown-heavy", spec)
            self.assertEqual([r["seed"] for r in json.loads(path2.read_text())["rows"]], [0, 1])

    def test_malformed_spec_raises(self):
        with tempfile.TemporaryDirectory() as d:
            for spec in ("bogus", '{"name": "tuned_timeout", "replan": 5, "abandon": 5}'):
                with self.assertRaises(ValueError):
                    ev.evaluate("stuck_aware_cta", SMALL, 50, [0], 1, d, "none", spec)

    def test_without_recovery_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            ev.evaluate("stuck_aware_cta", SMALL, 50, [0], 1, d, "none")
            ev.evaluate("stuck_aware_cta", SMALL, 50, [0], 1, d, "breakdown-heavy")
            names = sorted(p.name for p in Path(d).iterdir())
            self.assertEqual(names, [f"stuck_aware_cta_{SMALL}_50.json", f"stuck_aware_cta_{SMALL}_50_breakdown-heavy.json"])
            plain = json.loads((Path(d) / names[0]).read_text())
            dist = json.loads((Path(d) / names[1]).read_text())
            self.assertNotIn("recovery", plain)
            self.assertNotIn("recovery", dist)
            self.assertNotIn("recovery_wait", dist["rows"][0])
            self.assertNotIn("recovery", plain["rows"][0])
            self.assertEqual(set(plain["rows"][0]), {"seed", "steps", "deliveries", "pick_rate", "clashes", "stucks", "wall_s"})


if __name__ == "__main__":
    unittest.main()

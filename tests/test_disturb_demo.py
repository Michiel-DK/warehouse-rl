"""Tests for the S8F demo seam in src/warehouse_rl/disturb.py (inject_floor / inject_breakdown / injected_events).
Demo mode is NOT a measurement mode. Envs run strictly one at a time (global np.random, Agent.counter, Shelf.counter).
Each case names the mutants (M1-M14 of the brief) it kills; M11-M14 live in fleet/tests/test_fleet_demo.py."""
import hashlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np

from tarware.definitions import Action

from warehouse_rl import disturb as dz
from warehouse_rl.env import WarehouseEnv
from warehouse_rl.policy import CtaPolicy
from warehouse_rl.recovery import normalise_recovery

SMALL = "tarware-small-4agvs-2pickers-globalobs-v1"
MEDIUM = "tarware-medium-8agvs-4pickers-globalobs-v1"
TIMEOUT = {"name": "timeout"}
FULL_CFG = {"floor": {"cells": 6, "p": [0.3, 0.6]}, "breakdown": {"rate_per_hour": 8.0, "duration": [20, 60]},
            "delay": {"p_skip": 0.05}, "blocked_cell": {"rate_per_hour": 20.0, "duration": [5, 20]}}


def digest(*objs):
    h = hashlib.sha256()

    def feed(o):
        if isinstance(o, np.ndarray):
            h.update(str(o.dtype).encode() + str(o.shape).encode() + np.ascontiguousarray(o).tobytes())
        elif isinstance(o, dict):
            for k in sorted(o, key=repr):
                h.update(repr(k).encode())
                feed(o[k])
        elif isinstance(o, (list, tuple)):
            h.update(b"[")
            for x in o:
                feed(x)
            h.update(b"]")
        elif isinstance(o, (set, frozenset)):
            feed(sorted(o, key=repr))
        else:
            h.update(repr(o).encode())

    for o in objs:
        feed(o)
    return h.hexdigest()


def make(env_id, disturb, steps, demo, recovery=None):
    return WarehouseEnv(env_id, max_steps=steps, disturb=disturb, recovery=recovery, demo_mode=demo)


def drive(env, seed, steps, before=None, after=None):
    """Reset and run `steps` CTA steps. before(step, env) runs between steps (the injection point)."""
    pol = CtaPolicy()
    obs, info = env.reset(seed=seed)
    pol.reset(env)
    infos = []
    for s in range(steps):
        if before:
            before(s, env)
        obs, _, _, _, info = env.step(pol.act(obs, info["action_mask"], info))
        infos.append(info)
        if after:
            after(s, env, info)
    return infos


def schedules(hook):
    return dict(floor_cells=hook.floor_cells, floor_coin=hook.floor_coin, delay=hook.delay_schedule,
                obs=hook._obstacles_by_step, burst=hook.burst_order, frozen=hook.frozen_schedule)


class TestSeamGuards(unittest.TestCase):
    def test_raise_without_demo_mode(self):  # kills M10 (inject allowed with demo_mode=False)
        for recovery in (None, normalise_recovery(TIMEOUT)):
            env = make(SMALL, {}, 20, False, recovery)
            try:
                env.reset(seed=0)
                with self.assertRaises(RuntimeError):
                    env.env.inject_floor({(1, 1): 0.5})
                with self.assertRaises(RuntimeError):
                    env.env.inject_breakdown(1, 3)
                self.assertEqual(env.env.injected_floor, {})
                self.assertFalse(env.env.frozen_schedule.any())
            finally:
                env.close()

    def test_demo_without_disturb_is_value_error(self):
        with self.assertRaises(ValueError):
            WarehouseEnv(SMALL, max_steps=10, disturb=None, demo_mode=True)

    def test_runtime_error_before_reset_and_after_episode(self):
        env = make(SMALL, {}, 5, True)
        try:
            with self.assertRaises(RuntimeError):
                env.env.inject_breakdown(1, 2)
            drive(env, 0, 5)
            self.assertEqual(env.env._t, 5)
            with self.assertRaises(RuntimeError):
                env.env.inject_floor({(1, 1): 0.5})
            with self.assertRaises(RuntimeError):
                env.env.inject_breakdown(1, 2)
            self.assertFalse(env.env.frozen_schedule.any())
        finally:
            env.close()

    def test_bad_payloads_apply_nothing(self):
        env = make(SMALL, {}, 20, True)
        try:
            env.reset(seed=0)
            h = env.env
            rows, cols = h.grid_size
            bad_floor = [{}, [], {(1, 1): -0.1}, {(1, 1): 1.1}, {(1, 1): float("nan")}, {(1, 1): True},
                         {(1, 1): "0.5"}, {(cols, 1): 0.5}, {(1, rows): 0.5}, {(-1, 1): 0.5}, {"1,1": 0.5},
                         {(1.0, 1): 0.5}, {(True, 1): 0.5}, {(1, 1, 1): 0.5},
                         {(1, 1): 0.5, (cols, 0): 0.5}]  # last: a good cell next to a bad one -> nothing applied
            for cells in bad_floor:
                with self.assertRaises(ValueError, msg=repr(cells)):
                    h.inject_floor(cells)
            n = h.num_agents
            for a, d in [(0, 3), (n + 1, 3), (True, 3), (1.0, 3), ("1", 3), (1, 0), (1, -2), (1, 2.0), (1, True)]:
                with self.assertRaises(ValueError, msg=repr((a, d))):
                    h.inject_breakdown(a, d)
            self.assertEqual(h.injected_floor, {})
            self.assertIsNone(h._demo_coin)
            self.assertFalse(h.frozen_schedule.any())
            _, _, _, _, info = env.step([0] * n)
            self.assertEqual(info["injected_events"], 0)  # calls that raised are not counted
        finally:
            env.close()

    def test_info_key_and_reset_info(self):
        env = make(SMALL, {}, 5, False)
        try:
            _, rinfo = env.reset(seed=0)
            self.assertNotIn("injected_events", rinfo)
            infos = drive(env, 0, 3)
            self.assertTrue(all(i["injected_events"] == 0 for i in infos))
        finally:
            env.close()

    def test_demo_tag(self):  # kills M5 (child rng seeded with the floor tag)
        self.assertNotEqual(dz._DEMO_TAG, dz._FLOOR_TAG)
        self.assertNotEqual(dz._DEMO_TAG, dz._SEED_TAG)

    def test_demo_coin_stream(self):  # kills M5, M4 (coin drawn at reset instead of on the first inject)
        env = make(SMALL, {}, 30, True)
        try:
            env.reset(seed=4)
            h = env.env
            self.assertIsNone(h._demo_coin)  # nothing drawn at reset
            h.inject_floor({(1, 1): 0.5})
            ss = np.random.SeedSequence([4, dz.config_hash_int({}), dz._SEED_TAG, dz._DEMO_TAG])
            want = np.random.default_rng(ss).random((h.num_agents, h.max_steps))
            np.testing.assert_array_equal(h._demo_coin, want)
            wrong = np.random.default_rng(np.random.SeedSequence(
                [4, dz.config_hash_int({}), dz._SEED_TAG, dz._FLOOR_TAG])).random((h.num_agents, h.max_steps))
            self.assertFalse(np.array_equal(h._demo_coin, wrong))
            coin = h._demo_coin
            h.inject_floor({(2, 2): 0.1})
            self.assertIs(h._demo_coin, coin)  # drawn once per episode
        finally:
            env.close()


class TestFloorInjection(unittest.TestCase):
    def test_all_cells_p1_next_step_and_never_entered(self):  # kills M7, M8, M10, M1 (wrong column), M5
        env = make(SMALL, {}, 120, True)
        try:
            h = env.env
            injected = set()
            reqs = {}
            entered = []
            state = {}
            orig = h.resolve_move_conflict

            def wrapped(agent_list):
                reqs[h._t] = {a.id: (a.req_action == Action.FORWARD, a.req_location(h.grid_size), (a.x, a.y))
                              for a in agent_list}
                return orig(agent_list)

            h.resolve_move_conflict = wrapped

            def before(s, e):
                if s == 15:
                    h.inject_floor({c: 1.0 for c in h._blockable_cells})
                    injected.update(h._blockable_cells)
                    state["pre"] = {a.id: (a.x, a.y) for a in h.agents}

            def after(s, e, info):
                if s >= 15:
                    pos = {a.id: (a.x, a.y) for a in h.agents}
                    for aid, p in pos.items():
                        if p != state["pre"][aid] and p in injected:
                            entered.append((s, aid, p))
                    state["pre"] = pos
                if s == 15:
                    state["first"] = (info["floor_skips"], info["injected_events"], list(h.applied_floor[-1]), s)
                if s == 16:
                    state["second_events"] = info["injected_events"]
                if s == 14:
                    state["before_events"] = info["injected_events"]

            drive(env, 1, 120, before, after)
            skips, events, mask, s = state["first"]
            self.assertGreater(skips, 0)
            self.assertEqual(events, 1)
            self.assertEqual(state["second_events"], 0)
            self.assertEqual(state["before_events"], 0)
            self.assertEqual(sum(mask), skips)
            for i, skipped in enumerate(mask):
                if skipped:
                    forward, target, cur = reqs[15][i + 1]
                    self.assertTrue(forward)
                    self.assertIn(target, injected)
                    self.assertNotEqual(target, cur)
            self.assertEqual(entered, [])
            self.assertEqual(h.floor_cells, {})  # never mutated
            self.assertFalse(h.floor_coin.any())
        finally:
            env.close()

    def test_p0_never_skips(self):
        env = make(SMALL, {}, 80, True)
        try:
            h = env.env
            infos = drive(env, 1, 80, lambda s, e: s == 10 and h.inject_floor({c: 0.0 for c in h._blockable_cells}))
            self.assertEqual(sum(i["floor_skips"] for i in infos), 0)
        finally:
            env.close()

    def test_reinjection_overrides_p(self):  # re-injecting a cell replaces its p (clearing a roadblock with p=0 works)
        env = make(SMALL, {}, 80, True)
        try:
            h = env.env
            cells = list(h._blockable_cells)

            def before(s, e):
                if s == 10:
                    h.inject_floor({c: 1.0 for c in cells})
                if s == 30:
                    h.inject_floor({c: 0.0 for c in cells})

            infos = drive(env, 1, 80, before)
            self.assertGreater(sum(i["floor_skips"] for i in infos[10:30]), 0)
            self.assertEqual(sum(i["floor_skips"] for i in infos[30:]), 0)
            self.assertEqual(set(h.injected_floor.values()), {0.0})
        finally:
            env.close()

    def test_override_uses_injected_p_and_demo_coin(self):  # kills M6, M1 (indexing), M5
        env = make(SMALL, FULL_CFG_FLOOR_ONLY, 150, True)
        try:
            h = env.env
            P = 0.5
            reqs = []
            orig = h.resolve_move_conflict

            def wrapped(agent_list):
                t = h._t
                rec = []
                for a in agent_list:
                    if a.req_action == Action.FORWARD and a.req_location(h.grid_size) != (a.x, a.y):
                        rec.append((a.id, a.req_location(h.grid_size)))
                reqs.append((t, rec))
                return orig(agent_list)

            h.resolve_move_conflict = wrapped
            seen = {}
            scheduled = {}

            def before(s, e):
                if s == 0:
                    scheduled.update(h.floor_cells)
                    h.inject_floor({c: P for c in h._blockable_cells})
                    seen["fc"] = dict(h.floor_cells)
                    seen["coin"] = h.floor_coin.copy()

            drive(env, 2, 150, before)
            self.assertEqual(h.floor_cells, scheduled)  # untouched
            self.assertEqual(h.floor_cells, seen["fc"])
            np.testing.assert_array_equal(h.floor_coin, seen["coin"])
            disagree = 0
            checked = 0
            for (t, rec), applied in zip(reqs, h.applied_floor):
                for aid, target in rec:
                    if target not in h.injected_floor:
                        self.assertFalse(applied[aid - 1], (t, aid, target))
                        continue
                    want = bool(h._demo_coin[aid - 1, t] < P)
                    self.assertEqual(bool(applied[aid - 1]), want, (t, aid, target))
                    checked += 1
                    if target in scheduled and (h.floor_coin[aid - 1, t] < P) != want:
                        disagree += 1
            self.assertGreater(checked, 50)
            self.assertGreater(disagree, 0, "vacuous: no request into a scheduled cell where the two coins disagree")
        finally:
            env.close()

    def test_reset_clears_injections(self):  # kills M9
        env = make(SMALL, {}, 30, True)
        try:
            drive(env, 0, 10, lambda s, e: s == 5 and (e.env.inject_floor({(1, 1): 1.0}), e.env.inject_breakdown(1, 5)))
            h = env.env
            h.inject_floor({(1, 1): 1.0})  # pending event count, never reported
            env.reset(seed=0)
            self.assertEqual(h.injected_floor, {})
            self.assertIsNone(h._demo_coin)
            self.assertFalse(h.frozen_schedule.any())
            _, _, _, _, info = env.step([0] * h.num_agents)
            self.assertEqual(info["injected_events"], 0)
        finally:
            env.close()

    def test_through_recovery_hook(self):
        env = make(SMALL, {}, 40, True, normalise_recovery(TIMEOUT))
        try:
            infos = drive(env, 0, 40, lambda s, e: s == 10 and e.env.inject_floor({c: 1.0 for c in e.env._blockable_cells}))
            self.assertEqual([i["injected_events"] for i in infos].count(1), 1)
            self.assertEqual(infos[10]["injected_events"], 1)
        finally:
            env.close()


FULL_CFG_FLOOR_ONLY = {"floor": {"cells": 6, "p": [0.3, 0.6]}}


class TestBreakdownInjection(unittest.TestCase):
    def test_exact_window(self):  # kills M2 (from _t+1), M3 (from _t-1)
        env = make(SMALL, {}, 60, True)
        try:
            h = env.env
            k, t0, d = 3, 12, 7

            drive(env, 0, 60, lambda s, e: s == t0 and h.inject_breakdown(k, d))
            frozen = np.array(h.applied_frozen)
            want = np.zeros_like(frozen)
            want[t0:t0 + d, k - 1] = True
            np.testing.assert_array_equal(frozen, want)
        finally:
            env.close()

    def test_clipped_and_other_rows_untouched(self):
        env = make(SMALL, {"breakdown": {"rate_per_hour": 8.0, "duration": [5, 10]}}, 40, True)
        try:
            h = env.env
            snap = {}

            def before(s, e):
                if s == 35:
                    snap["before"] = h.frozen_schedule.copy()
                    h.inject_breakdown(2, 100)
                    snap["after"] = h.frozen_schedule.copy()

            drive(env, 0, 40, before)
            b, a = snap["before"], snap["after"]
            self.assertEqual(a.shape, b.shape)
            self.assertTrue(a[1, 35:].all())
            np.testing.assert_array_equal(a[1, :35], b[1, :35])
            others = [i for i in range(a.shape[0]) if i != 1]
            np.testing.assert_array_equal(a[others], b[others])
        finally:
            env.close()


class TestInjectedFloorPrecedence(unittest.TestCase):
    def test_frozen_and_delayed_beat_injected_floor(self):
        # frozen > delayed > floor holds for injected cells too: a suppressed agent whose FORWARD targets an injected
        # cell is NOT a floor skip (kills "injected floor checked before the frozen/delayed suppression").
        env = make(SMALL, {"delay": {"p_skip": 0.3}}, 80, True)
        try:
            h = env.env
            injected = set(h._blockable_cells)
            reqs = {}
            orig = h.resolve_move_conflict

            def wrapped(agent_list):
                reqs[h._t] = {a.id: (a.req_action == Action.FORWARD, a.req_location(h.grid_size), (a.x, a.y))
                              for a in agent_list}
                return orig(agent_list)

            h.resolve_move_conflict = wrapped

            def before(s, e):
                if s == 15:
                    h.inject_floor({c: 1.0 for c in injected})
                    h.inject_breakdown(1, 20)
                    h.inject_breakdown(2, 20)

            drive(env, 1, 80, before)
            seen = {"frozen": 0, "delayed": 0}
            for t in range(15, 80):
                fz, dl, fl = h.applied_frozen[t], h.applied_delayed[t], h.applied_floor[t]
                for aid, (forward, target, cur) in reqs[t].items():
                    if not (forward and target != cur and target in injected):
                        continue
                    if fz[aid - 1]:
                        seen["frozen"] += 1
                        self.assertFalse(fl[aid - 1], (t, aid))
                    elif dl[aid - 1]:
                        seen["delayed"] += 1
                        self.assertFalse(fl[aid - 1], (t, aid))
                    else:
                        self.assertTrue(fl[aid - 1], (t, aid))  # p = 1.0: an unsuppressed entry always skips
            self.assertGreater(seen["frozen"], 0)  # not vacuous: the case actually occurs
            self.assertGreater(seen["delayed"], 0)
        finally:
            env.close()


class TestInertAndIsolated(unittest.TestCase):
    def _run(self, env_id, cfg, seed, steps, demo, before=None):
        env = make(env_id, cfg, steps, demo, normalise_recovery(TIMEOUT))
        try:
            hashes, pos = [], []
            pol = CtaPolicy()
            obs, info = env.reset(seed=seed)
            pol.reset(env)
            for s in range(steps):
                if before:
                    before(s, env)
                obs, r, term, trunc, info = env.step(pol.act(obs, info["action_mask"], info))
                hashes.append(digest(obs, r, term, trunc, info))
                pos.append([(a.x, a.y) for a in env.env.agents])
            return hashes, pos, digest(schedules(env.env)), schedules(env.env)
        finally:
            env.close()

    def test_inert_without_injection(self):  # hard: demo_mode=True with no injection == demo_mode=False (kills M4 effects)
        for seed in (0, 1):
            a = self._run(MEDIUM, FULL_CFG, seed, 300, False)
            b = self._run(MEDIUM, FULL_CFG, seed, 300, True)
            self.assertEqual(a[0], b[0])
            self.assertEqual(a[1], b[1])
            self.assertEqual(a[2], b[2])

    def test_schedule_isolation(self):  # kills M8 (writes floor_cells), M4/M5 (shared generator state)
        cfg = dict(FULL_CFG, burst={"start": 30, "end": 60, "extra": 3})
        k = 2
        seen = {}

        def inject(s, e):
            if s == 20:
                h = e.env
                cell = next(c for c in h._blockable_cells if c not in h.floor_cells)
                h.inject_floor({cell: 1.0})
                h.inject_breakdown(k, 15)

        a = self._run(SMALL, cfg, 3, 120, False)
        b = self._run(SMALL, cfg, 3, 120, True, before=inject)
        self.assertEqual(a[0][:20], b[0][:20])
        self.assertEqual(a[1][:20], b[1][:20])
        sa, sb = a[3], b[3]
        for key in ("floor_cells", "floor_coin", "delay", "obs", "burst"):
            self.assertEqual(digest(sa[key]), digest(sb[key]), key)
        rows = [i for i in range(sa["frozen"].shape[0]) if i != k - 1]
        self.assertEqual(digest(sa["frozen"][rows]), digest(sb["frozen"][rows]))
        self.assertTrue(sb["frozen"][k - 1, 20:35].all())
        np.testing.assert_array_equal(sa["frozen"][k - 1, :20], sb["frozen"][k - 1, :20])
        self.assertNotEqual(a[0], b[0])  # the injections did something


if __name__ == "__main__":
    unittest.main()

"""Tests for the cost-aware router (S8C): DisturbedWarehouse / WarehouseEnv(cost_map=, cost_alpha=).
Envs run strictly one at a time (global np.random, Agent.counter and Shelf.counter are shared)."""
import math
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np

from tarware.definitions import AgentType
from tarware.warehouse import Warehouse

from warehouse_rl import disturb as dz
from warehouse_rl.env import WarehouseEnv
from warehouse_rl.policy import CtaPolicy, StuckAwareCtaPolicy

SMALL = "tarware-small-4agvs-2pickers-globalobs-v1"
FLOOR12 = {"floor": {"cells": 12, "p": [0.3, 0.7]}}
BD_FLOOR = {"breakdown": {"rate_per_hour": 20, "duration": [5, 20]}, "floor": {"cells": 8, "p": [0.3, 0.7]}}
ALWAYS = {"floor": {"cells": 10, "p": [1, 1]}}
# pyastar2d is not an exact shortest-path search on weighted grids (measured on 1.0.6: with a detour of +2 steps it still
# goes straight at an extra cost of 4 and detours from 5): "alpha*cost > d" is not enough for a detour. The detour cases
# use alpha*cost = DETOUR_FACTOR * d (far above any such slack); the straight cases use alpha*cost = d - 1 < d.
DETOUR_FACTOR = 10


def make(disturb, cost_map=None, alpha=4.0, seed=0, steps=60, recovery=None):
    env = WarehouseEnv(SMALL, max_steps=steps, disturb=disturb, cost_map=cost_map, cost_alpha=alpha,
                       recovery=recovery)
    env.reset(seed=seed)
    return env


def agent_of(e, kind):
    return next(a for a in e.agents if (a.type == AgentType.PICKER) == (kind == "picker"))


def free_cells(e):
    """Highway cells (x, y), sorted."""
    return sorted((int(x), int(y)) for y, x in np.argwhere(e.highways > 0))


class TestValidation(unittest.TestCase):
    def test_bad_values_raise(self):
        bad_maps = ["nope", [(1, 1)], {"1,1": 0.5}, {(1.0, 1): 0.5}, {(True, 1): 0.5}, {(1, 2, 3): 0.5},
                    {(-1, 1): 0.5}, {(10 ** 6, 1): 0.5}, {(1, 10 ** 6): 0.5}, {(1, 1): 0}, {(1, 1): 1.01},
                    {(1, 1): -0.2}, {(1, 1): float("nan")}, {(1, 1): "0.5"}, 3]
        for m in bad_maps:
            with self.subTest(cost_map=m):
                with self.assertRaises(ValueError):
                    WarehouseEnv(SMALL, max_steps=5, disturb={}, cost_map=m)
        for a in (-1, float("nan"), float("inf"), "4", True, None):
            with self.subTest(alpha=a):
                with self.assertRaises(ValueError):
                    WarehouseEnv(SMALL, max_steps=5, disturb={}, cost_alpha=a)

    def test_good_values_accepted(self):
        for m in (None, "oracle", {}, {(1, 1): 0.5}, {(0, 0): 1}):
            with self.subTest(cost_map=m):
                WarehouseEnv(SMALL, max_steps=5, disturb={}, cost_map=m).close()
        WarehouseEnv(SMALL, max_steps=5, disturb={}, cost_alpha=0).close()

    def test_cost_map_needs_a_disturb_dict(self):
        for m in ("oracle", {(1, 1): 0.5}, {}):
            with self.assertRaises(ValueError):
                WarehouseEnv(SMALL, max_steps=5, cost_map=m)
        WarehouseEnv(SMALL, max_steps=5, cost_map=None).close()

    def test_normalise_cost_map(self):
        self.assertEqual(dz.normalise_cost_map({"3,4": 0.5, "10,0": 1.0}), {(3, 4): 0.5, (10, 0): 1.0})
        with self.assertRaises(ValueError):
            dz.normalise_cost_map({"3;4": 0.5})
        with self.assertRaises(ValueError):
            dz.normalise_cost_map({"3,4,5": 0.5})


class TestWeightedRouting(unittest.TestCase):
    def setUp(self):
        self.env = make({})
        self.e = self.env.env
        self.agv = agent_of(self.e, "agv")

    def tearDown(self):
        self.env.close()

    def _query(self):
        """A start/goal pair on the highway whose plain path has a middle cell c with a detour of extra length d >= 2.
        Returns (start_yx, goal_yx, c, plain, detour, d)."""
        e = self.e
        cells = free_cells(e)
        for sx, sy in cells:
            for gx, gy in cells:
                if abs(sx - gx) + abs(sy - gy) < 4:
                    continue
                plain = e.find_path((sy, sx), (gy, gx), self.agv, care_for_agents=False)
                for c in plain[1:-1]:
                    e._cost_map_arg = {c: 1.0}
                    e.cost_alpha = 1000.0
                    e._set_active_map()
                    detour = e.find_path((sy, sx), (gy, gx), self.agv, care_for_agents=False)
                    e._cost_map_arg, e.cost_alpha = None, 4.0
                    e._set_active_map()
                    if c not in detour and len(detour) - len(plain) >= 2:
                        return (sy, sx), (gy, gx), c, plain, detour, len(detour) - len(plain)
        self.fail("no query with a detour found")

    def _set(self, cell, alpha, cost=1.0):
        e = self.e
        e._cost_map_arg, e.cost_alpha = {cell: cost}, float(alpha)
        e._set_active_map()

    def test_detour_when_cheaper_straight_when_dearer_no_ties(self):
        start, goal, c, plain, detour, d = self._query()
        e = self.e
        # extra cost of the costed cell = alpha * cost; the detour costs d extra steps. No ties: d - 1 < d << 10 d.
        self._set(c, DETOUR_FACTOR * d)
        self.assertEqual(e.find_path(start, goal, self.agv, care_for_agents=False), detour)
        self._set(c, d - 1)
        got = e.find_path(start, goal, self.agv, care_for_agents=False)
        self.assertIn(c, got)
        self.assertEqual(len(got), len(plain))
        # cost below 1 scales the same way
        self._set(c, 2 * DETOUR_FACTOR * d, cost=0.5)
        self.assertEqual(e.find_path(start, goal, self.agv, care_for_agents=False), detour)
        self._set(c, 2 * (d - 1), cost=0.5)
        self.assertIn(c, e.find_path(start, goal, self.agv, care_for_agents=False))

    def test_detour_with_active_obstacle_uses_the_weighted_search_too(self):
        start, goal, c, plain, detour, d = self._query()
        e = self.e
        self._set(c, DETOUR_FACTOR * d)
        far = next(x for x in free_cells(e) if x not in plain and x not in detour)
        with mock.patch.object(type(e), "_obstacles_now", return_value=frozenset({far})):
            self.assertEqual(e.find_path(start, goal, self.agv, care_for_agents=False), detour)
            self._set(c, d - 1)
            self.assertIn(c, e.find_path(start, goal, self.agv, care_for_agents=False))

    def test_weights_never_open_inf_cells(self):
        # a map cell that is a wall (shelf) stays inf: the weighted path may never walk through a shelf cell
        e = self.e
        shelf_cells = [(int(x), int(y)) for y, x in np.argwhere(e.highways == 0)]
        start, goal, c, plain, detour, d = self._query()
        e._cost_map_arg = {s: 1.0 for s in shelf_cells[:20]}
        e.cost_alpha = 4.0
        e._set_active_map()
        got = e.find_path(start, goal, self.agv, care_for_agents=False)
        self.assertEqual(got, plain)

    def test_start_on_a_map_cell_is_trimmed_like_the_plain_path(self):
        start, goal, c, plain, detour, d = self._query()
        e = self.e
        sx_sy = (start[1], start[0])
        self._set(sx_sy, 4.0)  # weight on the start cell only: the route is the plain one, start still trimmed
        got = e.find_path(start, goal, self.agv, care_for_agents=False)
        self.assertEqual(got, plain)
        self.assertNotEqual(got[0], sx_sy)
        # start on a map cell AND another costed cell on the way
        e._cost_map_arg = {sx_sy: 1.0, c: 1.0}
        e.cost_alpha = float(DETOUR_FACTOR * d)
        e._set_active_map()
        got = e.find_path(start, goal, self.agv, care_for_agents=False)
        self.assertEqual(got, detour)
        self.assertNotEqual(got[0], sx_sy)
        # obstacle search path: same trim
        far = next(x for x in free_cells(e) if x not in plain and x not in detour)
        with mock.patch.object(type(e), "_obstacles_now", return_value=frozenset({far})):
            self._set(sx_sy, 4.0)
            plain_obs = e._find_path_with_obstacles(start, goal, self.agv, False, frozenset({far}))
            got = e.find_path(start, goal, self.agv, care_for_agents=False)
            self.assertEqual(got, plain_obs)
            self.assertNotEqual(got[0], sx_sy)

    def test_picker_start_fix_is_trimmed_on_the_binary_grid(self):
        # picker standing in a rack column next to an adjacent target (start_fix branch): the start stays out of the path
        e = self.e
        picker = agent_of(e, "picker")
        rack = [(int(x), int(y)) for y, x in np.argwhere(e.highways == 0)]
        tried = 0
        for (x, y) in rack:
            for gy in (y - 1, y + 1):
                if gy < 0 or gy >= e.grid_size[0]:
                    continue
                start, goal = (y, x), (gy, x)
                self._set((x, y), 4.0)
                weighted = e.find_path(start, goal, picker, care_for_agents=False)
                e._cost_map_arg = None
                e._set_active_map()
                plain = e.find_path(start, goal, picker, care_for_agents=False)
                tried += 1
                self.assertEqual(weighted, plain)
                if tried >= 30:
                    return


class TestVendorEquality(unittest.TestCase):
    """Without an active map, or with alpha 0, find_path IS the vendor Warehouse.find_path (50 queries per
    agent type x care_for_agents combination, per case, no active obstacles), and nothing else runs."""

    def _check(self, env, expect_second_search_absent=True):
        e = env.env
        rng = np.random.default_rng(7)
        rows, cols = e.grid_size
        vendor_calls = []
        orig = Warehouse.find_path

        def counting(self_, *a, **k):
            vendor_calls.append(1)
            return orig(self_, *a, **k)

        for kind in ("agv", "picker"):
            agent = agent_of(e, kind)
            for care in (True, False):
                for _ in range(50):
                    start = (int(rng.integers(rows)), int(rng.integers(cols)))
                    goal = (int(rng.integers(rows)), int(rng.integers(cols)))
                    want = orig(e, start, goal, agent, care)
                    del vendor_calls[:]
                    with mock.patch.object(Warehouse, "find_path", counting), \
                            mock.patch.object(type(e), "_find_path_with_obstacles") as slow:
                        got = e.find_path(start, goal, agent, care)
                        self.assertFalse(slow.called)
                    self.assertEqual(got, want)
                    self.assertEqual(len(vendor_calls), 1)  # the vendor method, once: no second search
        self.assertEqual(e._routes_changed, 0)

    def test_no_map(self):
        env = make(FLOOR12)
        try:
            self.assertIsNone(env.env._active_map)
            self._check(env)
        finally:
            env.close()

    def test_non_empty_map_with_alpha_zero(self):
        probe = make({})
        cells = {c: 0.9 for c in free_cells(probe.env)[::3]}
        probe.close()
        env = make(FLOOR12, cost_map=cells, alpha=0)
        try:
            self.assertTrue(env.env._active_map)
            self._check(env)
        finally:
            env.close()


class TestCounters(unittest.TestCase):
    def _run(self, disturb, cost_map, steps=60, seed=0, alpha=4.0, policy=CtaPolicy, spy=True):
        env = WarehouseEnv(SMALL, max_steps=steps, disturb=disturb, cost_map=cost_map, cost_alpha=alpha)
        try:
            pol = policy()
            obs, info = env.reset(seed=seed)
            e = env.env
            pol.reset(env)
            calls = []
            if spy:
                orig = type(e).find_path

                def watched(start, goal, agent, care_for_agents=True):
                    got = orig(e, start, goal, agent, care_for_agents)
                    # independent count: the vendor search on the same state (no obstacles in these configs)
                    calls.append(got != Warehouse.find_path(e, start, goal, agent, care_for_agents))
                    return got

                e.find_path = watched
            per_step = []
            entered_recount = []
            for _ in range(steps):
                before = [(a.x, a.y) for a in e.agents]
                n_before = len(calls)
                active = dict(e._active_map or {})
                obs, _, _, _, info = env.step(pol.act(obs, info["action_mask"], info))
                after = [(a.x, a.y) for a in e.agents]
                changed = sum(1 for p, q in zip(before, after) if p != q and q in active)
                per_step.append((info["routes_changed_by_map"], info["map_cells_entered"], info["floor_skips"]))
                entered_recount.append(changed)
                if spy:
                    self._last_calls = calls
            return per_step, entered_recount, calls, e
        finally:
            env.close()

    def test_routes_changed_matches_independent_count_all_callers(self):
        probe = make(FLOOR12)
        cells = dict(probe.env.floor_cells)
        probe.close()
        env = WarehouseEnv(SMALL, max_steps=80, disturb=FLOOR12, cost_map=cells, cost_alpha=8.0)
        try:
            pol = StuckAwareCtaPolicy()
            obs, info = env.reset(seed=0)
            e = env.env
            pol.reset(env)
            orig = type(e).find_path
            window = []

            def watched(start, goal, agent, care_for_agents=True):
                got = orig(e, start, goal, agent, care_for_agents)
                window.append(got != Warehouse.find_path(e, start, goal, agent, care_for_agents))
                return got

            e.find_path = watched
            total = 0
            for _ in range(80):
                obs, _, _, _, info = env.step(pol.act(obs, info["action_mask"], info))
                self.assertEqual(info["routes_changed_by_map"], sum(window))
                total += sum(window)
                del window[:]
            self.assertGreater(total, 0, "the map never changed a route; the test would be vacuous")
        finally:
            env.close()

    def test_zero_without_a_map_and_keys_always_present(self):
        for cm in (None, {}, "oracle"):  # oracle on a config with no floor is no map
            with self.subTest(cost_map=cm):
                env = make({"breakdown": {"rate_per_hour": 10, "duration": [5, 10]}}, cost_map=cm, steps=30)
                try:
                    pol = CtaPolicy()
                    obs, info = env.reset(seed=1)
                    pol.reset(env)
                    self.assertIsNone(env.env._active_map)
                    for _ in range(30):
                        obs, _, _, _, info = env.step(pol.act(obs, info["action_mask"], info))
                        self.assertEqual(info["routes_changed_by_map"], 0)
                        self.assertEqual(info["map_cells_entered"], 0)
                finally:
                    env.close()

    def test_keys_present_with_recovery_hook(self):
        env = make(FLOOR12, steps=10, recovery={"name": "timeout"})
        try:
            pol = StuckAwareCtaPolicy()
            obs, info = env.reset(seed=0)
            pol.reset(env)
            obs, _, _, _, info = env.step(pol.act(obs, info["action_mask"], info))
            self.assertEqual((info["routes_changed_by_map"], info["map_cells_entered"]), (0, 0))
        finally:
            env.close()

    def test_alpha_zero_counts_nothing_but_still_counts_entries(self):
        probe = make(FLOOR12)
        cells = dict(probe.env.floor_cells)
        probe.close()
        per_step, recount, _, _ = self._run(FLOOR12, cells, steps=60, alpha=0, spy=False)
        self.assertEqual([r for r, _, _ in per_step], [0] * 60)
        self.assertEqual([m for _, m, _ in per_step], recount)

    def test_map_cells_entered_matches_per_step_recount(self):
        probe = make(FLOOR12, seed=1)
        cells = dict(probe.env.floor_cells)
        probe.close()
        per_step, recount, _, _ = self._run(FLOOR12, cells, steps=120, seed=1, spy=False)
        self.assertEqual([m for _, m, _ in per_step], recount)
        self.assertGreater(sum(recount), 0, "no agent ever entered a map cell; the test would be vacuous")

    def test_floor_skip_is_not_an_entry(self):
        # p = 1: every attempt to enter a floor cell is NOOPed, so a map equal to the floor sees zero entries
        probe = make(ALWAYS)
        cells = dict(probe.env.floor_cells)
        probe.close()
        per_step, recount, _, _ = self._run(ALWAYS, cells, steps=150, spy=False)
        self.assertGreater(sum(f for _, _, f in per_step), 0, "no floor skip happened; the test would be vacuous")
        self.assertEqual(sum(m for _, m, _ in per_step), 0)
        self.assertEqual(sum(recount), 0)

    def test_counters_reset_at_reset(self):
        probe = make(FLOOR12)
        cells = dict(probe.env.floor_cells)
        probe.close()
        env = WarehouseEnv(SMALL, max_steps=40, disturb=FLOOR12, cost_map=cells, cost_alpha=8.0)
        try:
            pol = CtaPolicy()
            obs, info = env.reset(seed=0)
            pol.reset(env)
            for _ in range(30):
                obs, _, _, _, info = env.step(pol.act(obs, info["action_mask"], info))
            e = env.env
            e._routes_changed, e._map_entered = 5, 7  # pending counts at the moment of reset
            env.reset(seed=0)
            self.assertEqual((e._routes_changed, e._map_entered), (0, 0))
            self.assertEqual(e._prev_pos, [(a.x, a.y) for a in e.agents])
        finally:
            env.close()


class TestOracle(unittest.TestCase):
    def test_active_map_equals_floor_cells_after_reset(self):
        layouts = []
        for seed in (0, 1):
            env = make(FLOOR12, cost_map="oracle", seed=seed)
            try:
                e = env.env
                self.assertTrue(e.floor_cells)
                self.assertEqual(e._active_map, e.floor_cells)
                self.assertIsNot(e._active_map, e.floor_cells)  # a copy
                layouts.append(dict(e.floor_cells))
                # re-read after another reset with the same env
                env.reset(seed=seed + 5)
                self.assertEqual(e._active_map, e.floor_cells)
            finally:
                env.close()
        self.assertNotEqual(layouts[0], layouts[1])

    def test_empty_floor_is_not_an_active_map(self):
        for cfg in ({}, {"breakdown": {"rate_per_hour": 10, "duration": [5, 10]}}):
            env = make(cfg, cost_map="oracle")
            try:
                self.assertEqual(env.env.floor_cells, {})
                self.assertIsNone(env.env._active_map)
            finally:
                env.close()


class TestSchedulesIndependentOfTheMap(unittest.TestCase):
    CFG_ALL = {"breakdown": {"rate_per_hour": 20, "duration": [5, 20]}, "delay": {"p_skip": 0.1},
               "blocked_cell": {"rate_per_hour": 30, "duration": [5, 20]},
               "outage": {"rate_per_hour": 30, "duration": [5, 20]}, "burst": {"start": 10, "end": 30, "extra": 3},
               "floor": {"cells": 8, "p": [0.3, 0.7]}}

    def _schedules(self, e):
        return dict(floor_cells=dict(e.floor_cells), floor_coin=e.floor_coin.copy(),
                    frozen=e.frozen_schedule.copy(), delayed=e.delay_schedule.copy(),
                    blocked=list(e._blocked_by_step), outage=list(e._out_goals_by_step),
                    obstacles=list(e._obstacles_by_step), burst_order=list(e.burst_order),
                    config=dict(e.disturb_config))

    def _same(self, a, b):
        for k in a:
            if isinstance(a[k], np.ndarray):
                self.assertTrue(np.array_equal(a[k], b[k]), k)
            else:
                self.assertEqual(a[k], b[k], k)

    def test_identical_with_no_map_dict_map_and_oracle(self):
        for cfg in (BD_FLOOR, self.CFG_ALL):
            for seed in (0, 1):
                got = []
                for how in ("none", "dict", "oracle"):
                    cm = None
                    if how == "dict":
                        probe = make(cfg, seed=seed)
                        cm = dict(probe.env.floor_cells)
                        probe.close()
                    elif how == "oracle":
                        cm = "oracle"
                    env = make(cfg, cost_map=cm, seed=seed)
                    try:
                        got.append(self._schedules(env.env))
                    finally:
                        env.close()
                self.assertTrue(got[0]["floor_cells"])
                self._same(got[0], got[1])
                self._same(got[0], got[2])

    def test_cost_map_is_not_in_the_disturb_config(self):
        env = make(BD_FLOOR, cost_map="oracle")
        try:
            self.assertEqual(env.env.disturb_config, dz.validate_config(BD_FLOOR))
            self.assertNotIn("cost_map", env.env.disturb_config)
        finally:
            env.close()


if __name__ == "__main__":
    unittest.main()

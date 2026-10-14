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

from tarware.definitions import AgentType, CollisionLayers
from tarware.warehouse import Warehouse

from warehouse_rl import disturb as dz
from warehouse_rl.env import WarehouseEnv
from warehouse_rl.policy import CtaPolicy, StuckAwareCtaPolicy

SMALL = "tarware-small-4agvs-2pickers-globalobs-v1"
FLOOR12 = {"floor": {"cells": 12, "p": [0.3, 0.7]}}
BD_FLOOR = {"breakdown": {"rate_per_hour": 20, "duration": [5, 20]}, "floor": {"cells": 8, "p": [0.3, 0.7]}}
ALWAYS = {"floor": {"cells": 10, "p": [1, 1]}}
# The vendored pyastar2d fork (vendor/pyastar2d/src/cpp/astar.cpp L115-139) costs a path as the sum of the entered
# cells' weights plus 1 per change of direction (the turn penalty, skipped when the entered weight is >= 100), and marks a
# cell it has relaxed with `weights += 100` (so it is not an exact optimum in general). The detour tests therefore state
# E = (extra steps) + (extra turns) of the detour versus the straight path, computed by an independent exact search
# (exact_cost below), and put the single costed cell at alpha*cost = E + 1 (detour) and E - 1 (straight). For the cases
# used here the fork honours margin 1 on both sides (measured; no visited-marker deviation to report).
def make(disturb, cost_map=None, alpha=4.0, seed=0, steps=60, recovery=None):
    env = WarehouseEnv(SMALL, max_steps=steps, disturb=disturb, cost_map=cost_map, cost_alpha=alpha,
                       recovery=recovery)
    env.reset(seed=seed)
    return env


def exact_cost(shape, start, goal, blocked=frozenset(), cell=None, weight=1.0):
    """Independent exact optimum of the fork's cost model on a 4-connected grid: the sum of entered-cell weights (1, or
    `weight` on `cell`) plus 1 per direction change. States are (row, col, direction). start/goal/blocked/cell are
    (row, col). Returns the optimal cost, or None."""
    import heapq
    rows, cols = shape
    pq, seen = [(0.0, start, -1)], set()
    while pq:
        d, p, dr = heapq.heappop(pq)
        if (p, dr) in seen:
            continue
        seen.add((p, dr))
        if p == goal:
            return d
        for i, (dy, dx) in enumerate(((-1, 0), (0, -1), (0, 1), (1, 0))):
            q = (p[0] + dy, p[1] + dx)
            if 0 <= q[0] < rows and 0 <= q[1] < cols and q not in blocked:
                heapq.heappush(pq, (d + (weight if q == cell else 1.0) + (1 if dr >= 0 and dr != i else 0), q, i))
    return None


def detour_extra(shape, start, goal, c, walls=frozenset()):
    """E = optimal cost with the cell c forbidden minus the optimal cost with it free (extra steps + extra turns).
    start/goal are (row, col) as find_path takes them; c and walls are (x, y) = (col, row)."""
    blocked = {(y, x) for x, y in walls}
    free = exact_cost(shape, start, goal, blocked)
    around = exact_cost(shape, start, goal, blocked | {(c[1], c[0])})
    return around - free


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

    # (start, goal, costed cell c) in find_path's (row, col) / the map's (x, y) frames, plus the extra obstacle walls
    # ((x, y) cells) that lengthen the detour. The straight path crosses exactly ONE costed cell (the map is {c: cost}).
    CASES = (
        ((2, 5), (12, 5), (5, 7), frozenset(), 4),  # open grid: out, down, back = +2 steps +2 turns
        ((2, 5), (12, 5), (5, 7), frozenset((x, y) for y in range(6, 9) for x in (4, 6)), 6),  # walls beside c
        ((2, 5), (12, 5), (5, 7), frozenset((x, y) for y in range(5, 10) for x in (3, 4, 6, 7)), 8),
    )

    def _query(self):
        """The open-grid case: (start, goal, c, plain, detour, E)."""
        start, goal, c, walls, E = self.CASES[0]
        self.assertEqual(detour_extra(self.e.grid_size, start, goal, c), E)
        self._set(c, 0)
        plain = self.e.find_path(start, goal, self.agv, care_for_agents=False)
        self._set(c, E + 1)
        detour = self.e.find_path(start, goal, self.agv, care_for_agents=False)
        self.assertIn(c, plain)
        self.assertNotIn(c, detour)
        return start, goal, c, plain, detour, E

    def _set(self, cell, alpha, cost=1.0):
        e = self.e
        e._cost_map_arg, e.cost_alpha = {cell: cost}, float(alpha)
        e._set_active_map()

    def _fp(self, start, goal, walls):
        with mock.patch.object(type(self.e), "_obstacles_now", return_value=frozenset(walls)):
            return self.e.find_path(start, goal, self.agv, care_for_agents=False)

    def test_detour_when_cheaper_straight_when_dearer_no_ties(self):
        seen_E = set()
        for start, goal, c, walls, E in self.CASES:
            with self.subTest(E=E):
                # E from the independent exact search (extra steps + extra turns), not from the router
                self.assertEqual(detour_extra(self.e.grid_size, start, goal, c, walls), E)
                seen_E.add(E)
                self._set(c, 0)
                plain = self._fp(start, goal, walls)
                self.assertIn(c, plain)
                for cost in (1.0, 0.5):  # alpha*cost is what matters
                    self._set(c, (E + 1) / cost, cost=cost)
                    detour = self._fp(start, goal, walls)
                    self.assertNotIn(c, detour)
                    self.assertGreater(len(detour), len(plain))
                    self._set(c, (E - 1) / cost, cost=cost)
                    self.assertEqual(self._fp(start, goal, walls), plain)
        self.assertGreaterEqual(len(seen_E), 2)

    def test_detour_with_active_obstacle_uses_the_weighted_search_too(self):
        start, goal, c, plain, detour, E = self._query()
        e = self.e
        self._set(c, E + 1)
        far = next(x for x in free_cells(e) if x not in plain and x not in detour)
        with mock.patch.object(type(e), "_obstacles_now", return_value=frozenset({far})):
            self.assertEqual(e.find_path(start, goal, self.agv, care_for_agents=False), detour)
            self._set(c, E - 1)
            self.assertIn(c, e.find_path(start, goal, self.agv, care_for_agents=False))

    # Cells that are inf on the BINARY grid keep the weighted grid's `if grid[wy, wx] == 1:` guard honest. A cost is never
    # non-finite (validate_cost_map rejects it at construction, so the guard is the only thing standing between a costed
    # wall and a finite weight). Each test below costs wall cells with a tiny alpha (weight ~1.001: if the guard let it
    # through, the wall would become the cheapest shortcut) on a query where such a shortcut exists, then asserts the
    # returned path is non-empty and never enters those cells. Mutation proof: with the guard replaced by `if True:`
    # every one of these fails (see the PR body).
    TINY = 0.001

    def _cost_walls(self, cells):
        e = self.e
        e._cost_map_arg, e.cost_alpha = {c: 1.0 for c in cells}, self.TINY
        e._set_active_map()
        self.assertTrue(e._weights)  # an active map

    def test_non_finite_costs_are_rejected_not_weighted(self):
        for bad in (float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                WarehouseEnv(SMALL, max_steps=5, disturb={}, cost_map={(1, 1): bad})

    def test_costed_rack_cells_stay_walls_for_a_picker(self):
        e = self.e
        picker = agent_of(e, "picker")
        rack = {(int(x), int(y)) for y, x in np.argwhere(e.highways == 0)}
        hw = free_cells(e)
        self._cost_walls(rack)
        rng = np.random.default_rng(0)
        shortcuts = 0
        for _ in range(300):
            a, b = (hw[i] for i in rng.choice(len(hw), 2, replace=False))
            path = e.find_path((a[1], a[0]), (b[1], b[0]), picker, care_for_agents=False)
            if not Warehouse.find_path(e, (a[1], a[0]), (b[1], b[0]), picker, False):
                continue  # unroutable even without a map (e.g. the picker's bottom row is a wall)
            self.assertTrue(path, (a, b))  # still routable through the highways
            self.assertFalse(rack & set(path), (a, b))
            if len(path) > abs(a[0] - b[0]) + abs(a[1] - b[1]):  # a straight shortcut through the racks existed
                shortcuts += 1
        self.assertGreater(shortcuts, 20)  # non-vacuous: the racks really were tempting

    def test_costed_active_obstacle_cell_stays_a_wall(self):
        start, goal, c, plain, detour, E = self._query()
        e = self.e
        self._cost_walls({c})
        with mock.patch.object(type(e), "_obstacles_now", return_value=frozenset({c})):
            path = e.find_path(start, goal, self.agv, care_for_agents=False)
        self.assertTrue(path)
        self.assertNotIn(c, path)
        self.assertIn(c, plain)  # the cell was on the unobstructed route: blocking it mattered

    def test_costed_cell_under_another_agent_stays_a_wall_with_care_for_agents(self):
        start, goal, c, plain, detour, E = self._query()
        e = self.e
        self._cost_walls({c})
        layer = e.grid[CollisionLayers.AGVS]
        layer[c[1], c[0]] = 1  # another AGV stands on c
        try:
            path = e.find_path(start, goal, self.agv, care_for_agents=True)
        finally:
            layer[c[1], c[0]] = 0
        self.assertTrue(path)
        self.assertNotIn(c, path)

    def test_start_on_a_map_cell_is_trimmed_like_the_plain_path(self):
        start, goal, c, plain, detour, E = self._query()
        e = self.e
        sx_sy = (start[1], start[0])
        self._set(sx_sy, 4.0)  # weight on the start cell only: the route is the plain one, start still trimmed
        got = e.find_path(start, goal, self.agv, care_for_agents=False)
        self.assertEqual(got, plain)
        self.assertNotEqual(got[0], sx_sy)
        # start on a map cell AND another costed cell on the way
        e._cost_map_arg = {sx_sy: 1.0, c: 1.0}
        e.cost_alpha = float(E + 1)
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

    def _count_against_reference(self, disturb, steps, alpha=8.0, seed=0):
        """Run a stuck-aware CTA episode with the floor layout as the map. Every find_path call (all callers, policy
        scoring included) is checked against a reference computed OUTSIDE the env's counter code: the vendor
        Warehouse.find_path when no obstacle is active, else the obstacle port with weights=None. Returns
        (total counted, counted while an obstacle was active)."""
        probe = WarehouseEnv(SMALL, max_steps=steps, disturb=disturb)
        probe.reset(seed=seed)
        cells = dict(probe.env.floor_cells)
        probe.close()
        env = WarehouseEnv(SMALL, max_steps=steps, disturb=disturb, cost_map=cells, cost_alpha=alpha)
        try:
            pol = StuckAwareCtaPolicy()
            obs, info = env.reset(seed=seed)
            e = env.env
            pol.reset(env)
            orig = type(e).find_path
            window = []  # (changed, obstacle_active) per call since the previous step

            def watched(start, goal, agent, care_for_agents=True):
                got = orig(e, start, goal, agent, care_for_agents)
                obstacles = e._obstacles_now()
                if obstacles:
                    ref = e._find_path_with_obstacles(start, goal, agent, care_for_agents, obstacles, None)
                else:
                    ref = Warehouse.find_path(e, start, goal, agent, care_for_agents)
                window.append((got != ref, bool(obstacles)))
                return got

            e.find_path = watched
            total = with_obstacle = 0
            for _ in range(steps):
                obs, _, _, _, info = env.step(pol.act(obs, info["action_mask"], info))
                self.assertEqual(info["routes_changed_by_map"], sum(c for c, _ in window))
                total += sum(c for c, _ in window)
                with_obstacle += sum(c for c, o in window if o)
                del window[:]
            return total, with_obstacle
        finally:
            env.close()

    def test_routes_changed_matches_independent_count_all_callers(self):
        total, _ = self._count_against_reference(FLOOR12, 80)
        self.assertGreater(total, 0, "the map never changed a route; the test would be vacuous")

    def test_routes_changed_matches_independent_count_with_active_obstacles(self):
        cfg = dict(FLOOR12, blocked_cell={"rate_per_hour": 720, "duration": [20, 30]})  # onset probability 1 per step
        total, with_obstacle = self._count_against_reference(cfg, 80)
        self.assertGreater(total, 0, "the map never changed a route; the test would be vacuous")
        self.assertGreater(with_obstacle, 0, "no counted route differed while an obstacle was active; the obstacle "
                                             "branch of the count was not exercised")

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

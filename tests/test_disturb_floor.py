"""Tests for the `floor` disturbance type (src/warehouse_rl/disturb.py). Envs run strictly one at a time (global
np.random, Agent.counter and Shelf.counter are shared). Each case names the mutant it kills."""
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np

from tarware.definitions import Action, Direction

from warehouse_rl import disturb as dz
from warehouse_rl.env import WarehouseEnv
from warehouse_rl.recovery import normalise_recovery
from warehouse_rl.policy import CtaPolicy, RandomPolicy

_spec = importlib.util.spec_from_file_location("evaluate_script", ROOT / "scripts" / "evaluate.py")
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)

SMALL = "tarware-small-4agvs-2pickers-globalobs-v1"
MEDIUM = "tarware-medium-8agvs-4pickers-globalobs-v1"
FLOOR6 = {"floor": {"cells": 6, "p": [0.3, 0.6]}}
ALWAYS6 = {"floor": {"cells": 6, "p": [1, 1]}}
NEVER6 = {"floor": {"cells": 6, "p": [0, 0]}}


def episode(env_id, disturb, seed, steps, policy="random", recovery=None, on_step=None):
    """Run one episode; returns (list of per-step infos, env.env snapshot dict). on_step(env, info) after each step."""
    env = WarehouseEnv(env_id, max_steps=steps, disturb=disturb, recovery=recovery)
    try:
        pol = CtaPolicy() if policy == "cta" else RandomPolicy(seed=seed)
        obs, info = env.reset(seed=seed)
        pol.reset(env)
        infos = []
        for _ in range(steps):
            obs, _, _, _, info = env.step(pol.act(obs, info["action_mask"], info))
            infos.append(info)
            if on_step:
                on_step(env.env, info)
        e = env.env
        snap = dict(floor_cells=dict(e.floor_cells), floor_coin=e.floor_coin.copy(),
                    applied_floor=[a.copy() for a in e.applied_floor], applied_delayed=[a.copy() for a in e.applied_delayed])
        return infos, snap
    finally:
        env.close()


def reset_env(env_id, disturb, seed=0, steps=50):
    env = WarehouseEnv(env_id, max_steps=steps, disturb=disturb)
    env.reset(seed=seed)
    return env


class TestDeterminism(unittest.TestCase):
    # mutants: floor drawn lazily / from env state (cells or coins differ between policies); seed ignored.
    def test_cells_and_coin_are_a_function_of_seed_and_config(self):
        _, rnd = episode(SMALL, FLOOR6, 3, 60, "random")
        _, cta = episode(SMALL, FLOOR6, 3, 60, "cta")
        self.assertEqual(rnd["floor_cells"], cta["floor_cells"])
        self.assertEqual(len(rnd["floor_cells"]), 6)
        np.testing.assert_array_equal(rnd["floor_coin"], cta["floor_coin"])
        self.assertEqual(rnd["floor_coin"].shape, (6, 60))
        _, other = episode(SMALL, FLOOR6, 4, 60, "random")
        self.assertNotEqual(rnd["floor_cells"], other["floor_cells"])
        self.assertFalse(np.array_equal(rnd["floor_coin"], other["floor_coin"]))

    def test_realised_skips_repeat_for_same_policy_and_seed(self):
        a, _ = episode(SMALL, ALWAYS6, 1, 150, "random")
        b, _ = episode(SMALL, ALWAYS6, 1, 150, "random")
        sa, sb = [i["floor_skips"] for i in a], [i["floor_skips"] for i in b]
        self.assertEqual(sa, sb)
        self.assertGreater(sum(sa), 0)

    def test_floor_cells_are_plain_python(self):
        env = reset_env(SMALL, FLOOR6)
        try:
            for (x, y), p in env.env.floor_cells.items():
                self.assertIs(type(x), int)
                self.assertIs(type(y), int)
                self.assertIs(type(p), float)
                self.assertTrue(0.3 <= p <= 0.6)
        finally:
            env.close()


class TestCells(unittest.TestCase):
    # mutant: candidates not restricted to highway non-goal cells.
    def test_every_floor_cell_is_highway_non_goal(self):
        for env_id in (SMALL, MEDIUM):
            env = reset_env(env_id, {"floor": {"cells": 12, "p": [0.2, 0.6]}})
            try:
                e = env.env
                goals = {tuple(int(v) for v in g[::-1]) for g in e.goals}  # goals are (y, x)
                self.assertEqual(len(e.floor_cells), 12)
                for (x, y) in e.floor_cells:
                    self.assertGreater(e.highways[y, x], 0)
                    self.assertNotIn((x, y), goals)
            finally:
                env.close()

    def test_medium_has_room_and_oversize_k_raises(self):
        env = reset_env(MEDIUM, dz.PRESETS["floor-heavy"])
        try:
            self.assertGreater(len(env.env._blockable_cells), 12)
            self.assertEqual(len(env.env.floor_cells), 12)
        finally:
            env.close()
        env = WarehouseEnv(SMALL, max_steps=10, disturb={"floor": {"cells": 10 ** 6, "p": [0.1, 0.2]}})
        try:
            with self.assertRaises(ValueError):
                env.reset(seed=0)
        finally:
            env.close()

    def test_presets(self):
        self.assertEqual(dz.PRESETS["floor-light"], {"floor": {"cells": 6, "p": [0.05, 0.25]}})
        self.assertEqual(dz.PRESETS["floor-heavy"], {"floor": {"cells": 12, "p": [0.2, 0.6]}})
        for name in ("floor-light", "floor-heavy"):
            self.assertEqual(dz.resolve_disturb(name)[0], name)


class TestValidate(unittest.TestCase):
    def bad(self, floor):
        with self.assertRaises(ValueError, msg=repr(floor)):
            dz.validate_config({"floor": floor})

    def test_rejects(self):
        ok = [0.1, 0.2]
        for k in (0, -1, True, False, 2.0, 2.5, "3", None):
            self.bad({"cells": k, "p": ok})
        for p in ([0.5, 0.2], [-0.1, 0.5], [0.1, 1.5], [0.1], [0.1, 0.2, 0.3], 0.5, "ab", None, [True, 0.5],
                  [float("nan"), 0.5], [0.1, float("inf")], ["0.1", "0.2"]):
            self.bad({"cells": 3, "p": p})
        self.bad({"cells": 3})
        self.bad({"p": ok})
        self.bad({"cells": 3, "p": ok, "extra": 1})
        self.bad({})
        self.bad([3, ok])

    def test_accepts(self):
        for p in ([0, 0], [1, 1], [0.0, 1.0], (0.1, 0.2)):
            dz.validate_config({"floor": {"cells": 1, "p": p}})


class TestIsolation(unittest.TestCase):
    # mutant: main rng seeded from the full config hash (every array below changes); mutant: floor drawn from the
    # main rng before burst (burst_order changes). Not a prefix check: the floor key is added to every base config.
    BASES = {
        "breakdown-light": dz.PRESETS["breakdown-light"],
        "delay-10": dz.PRESETS["delay-10"],
        "blocked": {"blocked_cell": {"rate_per_hour": 60, "duration": [5, 20]}},
        "outage": {"outage": {"rate_per_hour": 60, "duration": [5, 20]}},
        "burst": {"burst": {"start": 10, "end": 30, "extra": 3}},
        "all": {"breakdown": {"rate_per_hour": 20, "duration": [5, 20]}, "delay": {"p_skip": 0.2},
                "blocked_cell": {"rate_per_hour": 60, "duration": [5, 20]},
                "outage": {"rate_per_hour": 60, "duration": [5, 20]},
                "burst": {"start": 10, "end": 30, "extra": 3}},
    }

    def schedules(self, cfg, seed=0):
        env = reset_env(SMALL, cfg, seed=seed, steps=200)
        try:
            e = env.env
            return dict(frozen=e.frozen_schedule.copy(), delay=e.delay_schedule.copy(),
                        blocked=list(e._blocked_by_step), out=list(e._out_goals_by_step),
                        obstacles=list(e._obstacles_by_step), burst=list(e.burst_order),
                        frozen_now=[e._masks_at(t)[0].copy() for t in range(200)])
        finally:
            env.close()

    def test_adding_floor_leaves_other_draws_untouched(self):
        bases = self.BASES
        for name, base in bases.items():
            with self.subTest(base=name):
                ref = self.schedules(base)
                got = self.schedules(dict(base, **FLOOR6))
                np.testing.assert_array_equal(ref["frozen"], got["frozen"])
                np.testing.assert_array_equal(ref["delay"], got["delay"])
                for t in range(200):
                    np.testing.assert_array_equal(ref["frozen_now"][t], got["frozen_now"][t])
                self.assertEqual(ref["blocked"], got["blocked"])
                self.assertEqual(ref["out"], got["out"])
                self.assertEqual(ref["obstacles"], got["obstacles"])
                self.assertEqual(ref["burst"], got["burst"])
        # the bases are not vacuous: something is scheduled
        ref = self.schedules(bases["all"])
        self.assertTrue(ref["frozen"].any() and ref["delay"].any())
        self.assertTrue(any(ref["blocked"]) and any(ref["out"]) and ref["burst"])

    def test_no_floor_config_has_empty_state(self):
        env = reset_env(SMALL, dz.PRESETS["delay-10"])
        try:
            self.assertEqual(env.env.floor_cells, {})
        finally:
            env.close()
        infos, snap = episode(SMALL, dz.PRESETS["delay-10"], 0, 60, "random")
        self.assertEqual([i["floor_skips"] for i in infos], [0] * 60)
        self.assertEqual(snap["floor_cells"], {})
        infos, _ = episode(SMALL, {}, 0, 20, "random")
        self.assertEqual([i["floor_skips"] for i in infos], [0] * 20)


class TestEffect(unittest.TestCase):
    # mutants: p=[1,1] still lets entries through (leave instead of enter); p=[0,0] skips; skips counted as delay.
    def test_always_and_never(self):
        infos, snap = episode(SMALL, NEVER6, 0, 200, "random")
        self.assertEqual(sum(i["floor_skips"] for i in infos), 0)
        infos, snap = episode(SMALL, ALWAYS6, 0, 200, "random")
        self.assertGreater(sum(i["floor_skips"] for i in infos), 0)
        # floor skips are not delay skips
        self.assertEqual([i["delayed_agents"] for i in infos], [0] * 200)
        self.assertFalse(any(a.any() for a in snap["applied_delayed"]))

    def test_nobody_enters_a_floor_cell_when_p_is_one(self):
        # kills "leave instead of enter": with leave semantics agents still enter floor cells freely
        state = {"prev": None, "entered": 0}

        def on_step(e, info):
            now = [(a.x, a.y) for a in e.agents]
            if state["prev"] is not None:
                for before, after in zip(state["prev"], now):
                    if after in e.floor_cells and after != before:
                        state["entered"] += 1
            state["prev"] = now

        env = WarehouseEnv(SMALL, max_steps=200, disturb=ALWAYS6)
        try:
            pol = RandomPolicy(seed=0)
            obs, info = env.reset(seed=0)
            pol.reset(env)
            state["prev"] = [(a.x, a.y) for a in env.env.agents]
            for _ in range(200):
                obs, _, _, _, info = env.step(pol.act(obs, info["action_mask"], info))
                on_step(env.env, info)
        finally:
            env.close()
        self.assertEqual(state["entered"], 0)

    def test_skip_counts_equal_applied_floor(self):
        infos, snap = episode(SMALL, ALWAYS6, 2, 100, "cta")
        self.assertEqual([i["floor_skips"] for i in infos], [int(a.sum()) for a in snap["applied_floor"]])


class TestUnitSemantics(unittest.TestCase):
    """Drive resolve_move_conflict directly on a reset env at t=0 with hand-set requests."""

    def setUp(self):
        self.env = reset_env(SMALL, ALWAYS6)
        self.e = self.env.env

    def tearDown(self):
        self.env.close()

    def prep(self, aidx=0, action=Action.FORWARD, direction=Direction.RIGHT, floor_here=False, p=1.0, coin=0.0):
        e = self.e
        a = e.agents[aidx]
        a.dir = direction
        a.req_action = action
        for o in e.agents:
            if o is not a:
                o.req_action = Action.NOOP
        a.req_action = action
        tx, ty = {Direction.RIGHT: (a.x + 1, a.y), Direction.LEFT: (a.x - 1, a.y),
                  Direction.UP: (a.x, a.y - 1), Direction.DOWN: (a.x, a.y + 1)}[direction]
        e.floor_cells = {(a.x, a.y): p} if floor_here else {(tx, ty): p}
        e.floor_coin[:] = coin
        return a, (tx, ty)

    def run_once(self):
        self.e.resolve_move_conflict(self.e.agents)
        return self.e.applied_floor[-1]

    def test_enter_skips_and_counts_once(self):
        a, _ = self.prep()
        fl = self.run_once()
        self.assertEqual(a.req_action, Action.NOOP)
        self.assertEqual(int(fl.sum()), 1)
        self.assertTrue(fl[a.id - 1])
        self.assertFalse(self.e.applied_delayed[-1].any())

    def test_coin_threshold_is_strict(self):
        a, _ = self.prep(p=0.4, coin=0.4)
        self.assertEqual(int(self.run_once().sum()), 0)
        self.assertEqual(a.req_action, Action.FORWARD)

    def test_turn_noop_toggle_never_skip(self):
        for act in (Action.LEFT, Action.RIGHT, Action.NOOP, Action.TOGGLE_LOAD):
            with self.subTest(action=act):
                a, _ = self.prep(action=act)
                self.assertEqual(int(self.run_once().sum()), 0)
                self.assertEqual(a.req_action, act)

    def test_leaving_a_floor_cell_is_free(self):
        # kills "leave instead of enter"
        a, _ = self.prep(floor_here=True)
        self.assertEqual(int(self.run_once().sum()), 0)
        self.assertEqual(a.req_action, Action.FORWARD)

    def test_frozen_and_delayed_win_over_floor(self):
        a, _ = self.prep()
        self.e.frozen_schedule[a.id - 1, 0] = True
        self.assertEqual(int(self.run_once().sum()), 0)
        self.assertEqual(a.req_action, Action.NOOP)
        self.assertTrue(self.e.applied_frozen[-1][a.id - 1])
        self.env.close()
        self.setUp()
        a, _ = self.prep()
        self.e.delay_schedule[a.id - 1, 0] = True
        self.assertEqual(int(self.run_once().sum()), 0)
        self.assertEqual(a.req_action, Action.NOOP)
        self.assertTrue(self.e.applied_delayed[-1][a.id - 1])

    def test_floor_wins_over_obstacle_only_when_the_coin_hits(self):
        a, target = self.prep(p=0.5, coin=0.1)
        self.e._obstacles_by_step[0] = frozenset({target})
        self.assertEqual(int(self.run_once().sum()), 1)
        self.env.close()
        self.setUp()
        a, target = self.prep(p=0.5, coin=0.9)
        self.e._obstacles_by_step[0] = frozenset({target})
        self.assertEqual(int(self.run_once().sum()), 0)
        self.assertEqual(a.req_action, Action.NOOP)  # the obstacle still stops it, but it is not a floor skip

    def test_skipped_agent_is_suppressed_like_a_delay(self):
        a, _ = self.prep()
        self.run_once()
        self.assertTrue(self.e._suppressed[a.id - 1])

    def test_out_of_range_step_does_not_index_the_coin(self):
        a, _ = self.prep()
        self.e._t = self.e.max_steps
        self.assertEqual(int(self.run_once().sum()), 0)


class TestStuckCounter(unittest.TestCase):
    """Observed, not assumed: what does a floor skip do to a busy agent's StuckCounter?"""

    def test_floor_skip_leaves_stuck_counter_unchanged(self):
        seen = []
        env = WarehouseEnv(SMALL, max_steps=300, disturb={"floor": {"cells": 12, "p": [1, 1]}})
        try:
            e = env.env
            real = e.resolve_move_conflict
            before = {}

            def spy(agent_list):
                before["counts"] = [c.count for c in e.stuck_counters]
                before["busy"] = [a.busy for a in e.agents]
                before["pos"] = [c.position for c in e.stuck_counters]
                return real(agent_list)

            e.resolve_move_conflict = spy
            pol = CtaPolicy()
            obs, info = env.reset(seed=0)
            pol.reset(env)
            for _ in range(300):
                obs, _, _, _, info = env.step(pol.act(obs, info["action_mask"], info))
                fl = e.applied_floor[-1]
                for i in np.flatnonzero(fl):
                    if before["busy"][i]:
                        seen.append((before["counts"][i], e.stuck_counters[i].count, before["pos"][i],
                                     e.stuck_counters[i].position))
        finally:
            env.close()
        self.assertGreater(len(seen), 0, "no busy agent was floor-skipped; test is vacuous")
        for b, after, pb, pa in seen:
            self.assertEqual(b, after)
            self.assertEqual(pb, pa)
        print(f"\n[StuckCounter observation] {len(seen)} busy floor-skipped agent-steps; count unchanged in all "
              f"(max count before = {max(s[0] for s in seen)})", file=sys.stderr)


class TestEvaluate(unittest.TestCase):
    def test_smoke_rows(self):
        row = ev.run_seed("stuck_aware_cta", SMALL, 100, 0, disturb=ALWAYS6,
                          recovery=normalise_recovery({"name": "timeout"}))
        self.assertIn("floor_skip_steps", row)
        self.assertGreater(row["floor_skip_steps"], 0)
        row = ev.run_seed("cta", SMALL, 100, 0, disturb=dz.PRESETS["delay-10"])
        self.assertEqual(row["floor_skip_steps"], 0)
        self.assertEqual(ev.DISTURB_SUMS["floor_skip_steps"], "floor_skips")


if __name__ == "__main__":
    unittest.main()

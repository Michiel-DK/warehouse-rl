"""Tests for blocked_cell.known (S10C, blind blockage) in src/warehouse_rl/disturb.py. Envs run strictly one at a
time (global np.random, Agent.counter and Shelf.counter are shared). The goldens below were computed on base afa7b2b,
BEFORE disturb.py was touched; they are pure rng outputs (no platform dependence)."""
import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np

from tarware.definitions import Action, Direction

from warehouse_rl import disturb as dz
from warehouse_rl.env import WarehouseEnv
from warehouse_rl.policy import CtaPolicy

SMALL = "tarware-small-4agvs-2pickers-globalobs-v1"
BLK = {"rate_per_hour": 8.0, "duration": [60, 240]}


def blocked_cfg(**extra):
    return {"blocked_cell": {**BLK, **extra}}


# The four S10 configs (queue item wr-s10-disturbance-measure).
S10_CONFIGS = {
    "s10-blocked": blocked_cfg(),
    "s10-outage": {"outage": {"rate_per_hour": 4.0, "duration": [120, 360]}},
    "s10-breakdown": dz.PRESETS["breakdown-heavy"],
    "s10-burst": {"burst": {"start": 100, "end": 300, "extra": 20}},
}
BREAKDOWN_FLOOR = {"breakdown": {"rate_per_hour": 8.0, "duration": [20, 60]}, "floor": {"cells": 6, "p": [0.3, 0.6]}}

# Goldens from base afa7b2b (300-step small map, seed s): sha256 of _blocked_by_step / of breakdown+floor state.
GOLD_BLOCKED = {
    0: "7fb074c561190cf504d2f1e6e23cb39ed9b6d8d102febf61c28e152c817fcbe8",
    7: "ee37e28500ea05a69d1ac0f5eb1acdac19edfd40b465b20ceb809638bcde24b5",
}
GOLD_BREAKDOWN_FLOOR_SEED0 = "bacb4b2249176a10c7c868976b45dfd4ef9c42ae15cc92c5b739158abd866c4b"


def blocked_digest(e):
    items = [[t, sorted(list(c))] for t, c in enumerate(e._blocked_by_step) if c]
    return hashlib.sha256(json.dumps(items).encode()).hexdigest()


def breakdown_floor_digest(e):
    h = hashlib.sha256()
    h.update(e.frozen_schedule.tobytes())
    h.update(json.dumps(sorted([list(k), v] for k, v in e.floor_cells.items())).encode())
    h.update(e.floor_coin.tobytes())
    return h.hexdigest()


def reset_env(disturb, seed=0, steps=300):
    env = WarehouseEnv(SMALL, max_steps=steps, disturb=disturb)
    env.reset(seed=seed)
    return env


def with_known(cfg, known):
    """cfg with blocked_cell.known set (None = key absent)."""
    out = json.loads(json.dumps(cfg))
    if "blocked_cell" in out and known is not None:
        out["blocked_cell"]["known"] = known
    return out


def schedule_of(disturb, seed, steps=300):
    env = reset_env(disturb, seed, steps)
    try:
        e = env.env
        return dict(blocked=list(e._blocked_by_step), frozen=e.frozen_schedule.copy(), delay=e.delay_schedule.copy(),
                    out=list(e._out_goals_by_step), floor_cells=dict(e.floor_cells), floor_coin=e.floor_coin.copy(),
                    burst=list(e.burst_order), digest_blocked=blocked_digest(e),
                    digest_bf=breakdown_floor_digest(e))
    finally:
        env.close()


def norm(x):
    if isinstance(x, np.ndarray):
        return x.tolist()
    if isinstance(x, dict):
        return {k: norm(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [norm(v) for v in x]
    if isinstance(x, (np.integer, np.floating, np.bool_)):
        return x.item()
    return x


def episode(disturb, seed, steps):
    """CTA episode; returns (infos, applied dict, pick-rate, obstacles, blind cells per step)."""
    env = WarehouseEnv(SMALL, max_steps=steps, disturb=disturb)
    try:
        pol = CtaPolicy()
        obs, info = env.reset(seed=seed)
        pol.reset(env)
        infos = []
        for _ in range(steps):
            obs, _, _, _, info = env.step(pol.act(obs, info["action_mask"], info))
            infos.append(norm(info))
        e = env.env
        applied = {k: [a.tolist() for a in getattr(e, "applied_" + k)] for k in ("frozen", "delayed", "floor", "blind")}
        rate = sum(i["shelf_deliveries"] for i in infos) * 3600 / (5 * steps)
        return infos, applied, rate, list(e._obstacles_by_step), list(e._blocked_by_step)
    finally:
        env.close()


class TestValidate(unittest.TestCase):
    def test_known_accepts_only_bool(self):
        for v in (True, False):
            self.assertEqual(dz.validate_config(blocked_cfg(known=v))["blocked_cell"]["known"], v)
        self.assertNotIn("known", dz.validate_config(blocked_cfg())["blocked_cell"])  # no default inserted
        for v in (0, 1, "false", None, 0.0, [True]):
            with self.subTest(v=v):
                with self.assertRaises(ValueError):
                    dz.validate_config(blocked_cfg(known=v))

    def test_known_is_an_unknown_key_in_every_other_section(self):
        cfgs = [{"outage": {**BLK, "known": False}}, {"floor": {"cells": 2, "p": [0, 1], "known": True}},
                {"breakdown": {**BLK, "known": True}}, {"delay": {"p_skip": 0.1, "known": True}},
                {"burst": {"start": 0, "end": 5, "extra": 1, "known": True}}]
        for c in cfgs:
            with self.subTest(c=c):
                with self.assertRaisesRegex(ValueError, "unknown keys"):
                    dz.validate_config(c)

    def test_draw_config_strips_known_and_copies(self):
        cfg = blocked_cfg(known=False)
        self.assertEqual(dz._draw_config(cfg), blocked_cfg())
        self.assertIn("known", cfg["blocked_cell"])  # input untouched
        self.assertEqual(dz._draw_config(blocked_cfg(known=True)), dz._draw_config(blocked_cfg()))
        self.assertEqual(dz._draw_config({"floor": {"cells": 2, "p": [0, 1]}}), {"floor": {"cells": 2, "p": [0, 1]}})


class TestScheduleEquality(unittest.TestCase):
    def test_blocked_schedule_identical_for_known_absent_true_false(self):
        for seed in (0, 7):
            base = schedule_of(blocked_cfg(), seed)
            self.assertTrue(any(base["blocked"]), "vacuous: no blocked cell drawn")
            for known in (True, False):
                with self.subTest(seed=seed, known=known):
                    self.assertEqual(schedule_of(blocked_cfg(known=known), seed)["blocked"], base["blocked"])

    def test_floor_plus_blocked_draws_identical(self):
        cfg = {"floor": {"cells": 6, "p": [0.3, 0.6]}, **blocked_cfg()}
        for seed in (0, 7):
            base = schedule_of(cfg, seed)
            self.assertTrue(any(base["blocked"]))
            for known in (True, False):
                with self.subTest(seed=seed, known=known):
                    s = schedule_of(with_known(cfg, known), seed)
                    self.assertEqual(s["floor_cells"], base["floor_cells"])
                    np.testing.assert_array_equal(s["floor_coin"], base["floor_coin"])
                    self.assertEqual(s["blocked"], base["blocked"])

    def test_every_generator_is_seeded_without_known(self):
        # main rng with the other types, plus the demo generator (own seed): identical across known values
        cfg = {**BREAKDOWN_FLOOR, **blocked_cfg(), "outage": {"rate_per_hour": 4.0, "duration": [20, 40]},
               "burst": {"start": 10, "end": 50, "extra": 3}}
        base = schedule_of(cfg, 3)
        for known in (True, False):
            s = schedule_of(with_known(cfg, known), 3)
            np.testing.assert_array_equal(s["frozen"], base["frozen"])
            self.assertEqual(s["out"], base["out"])
            self.assertEqual(s["burst"], base["burst"])
        draws = []
        for known in (None, True, False):
            env = WarehouseEnv(SMALL, max_steps=50, disturb=with_known(cfg, known), demo_mode=True)
            try:
                env.reset(seed=3)
                env.env.inject_floor({(1, 1): 0.5})
                draws.append(env.env._demo_coin.copy())
            finally:
                env.close()
        np.testing.assert_array_equal(draws[0], draws[1])
        np.testing.assert_array_equal(draws[0], draws[2])

    def test_goldens_from_base_are_reproduced(self):
        for known in (None, True, False):
            for seed, gold in GOLD_BLOCKED.items():
                with self.subTest(known=known, seed=seed):
                    self.assertEqual(schedule_of(with_known(blocked_cfg(), known), seed)["digest_blocked"], gold)
            with self.subTest(known=known, what="breakdown+floor"):
                self.assertEqual(schedule_of(BREAKDOWN_FLOOR, 0)["digest_bf"], GOLD_BREAKDOWN_FLOOR_SEED0)
        # a blocked_cell + floor config reproduces the same floor draws as floor alone does NOT hold (full cfg hashed);
        # what must hold is that known never moves them (TestScheduleEquality).


class TestBitIdentity(unittest.TestCase):
    """known absent vs known true: identical applied_* arrays, per-step info dicts and pick-rates (seeds 0-2 x 100
    steps, CTA). For configs without blocked_cell both sides are the same config: a determinism check."""

    def test_presets_and_s10_configs(self):
        cfgs = dict(dz.PRESETS)
        cfgs.update(S10_CONFIGS)
        self.assertEqual(len(cfgs), len(dz.PRESETS) + 4)
        for name, cfg in cfgs.items():
            for seed in (0, 1, 2):
                with self.subTest(cfg=name, seed=seed):
                    a = episode(with_known(cfg, None), seed, 100)
                    b = episode(with_known(cfg, True), seed, 100)
                    self.assertEqual(a[1], b[1])
                    self.assertEqual(a[0], b[0])
                    self.assertEqual(a[2], b[2])
                    self.assertEqual(a[3], b[3])
                    self.assertTrue(all(i["blind_skips"] == 0 for i in a[0]))


class TestBlindEffect(unittest.TestCase):
    """known:false on blocked rate 8.0 / [60, 240], CTA, seeds 0-2 x 300 steps (at 150 steps no robot reaches a blind cell on these seeds;
    the rate is not raised)."""

    def test_blind_cells_are_truth_not_obstacles_and_robots_hit_them(self):
        total = 0
        for seed in (0, 1, 2):
            with self.subTest(seed=seed):
                known = episode(blocked_cfg(known=True), seed, 300)
                blind = episode(blocked_cfg(known=False), seed, 300)
                self.assertEqual([i["blocked_cells"] for i in blind[0]], [i["blocked_cells"] for i in known[0]])
                self.assertEqual(blind[4], known[4])
                self.assertTrue(all(not o for o in blind[3]))
                self.assertTrue(any(known[3]))
                self.assertTrue(all(i["floor_skips"] == 0 and i["delayed_agents"] == 0 for i in blind[0]))
                self.assertFalse(any(any(x) for x in blind[1]["floor"] + blind[1]["delayed"]))
                self.assertEqual([i["blind_skips"] for i in blind[0]], [sum(x) for x in blind[1]["blind"]])
                total += sum(i["blind_skips"] for i in blind[0])
        self.assertGreater(total, 0)

    def test_outage_cells_stay_obstacles_when_blind_blockage_is_on(self):
        cfg = {**blocked_cfg(known=False), "outage": {"rate_per_hour": 8.0, "duration": [60, 240]}}
        env = reset_env(cfg, 0)
        try:
            e = env.env
            goals = {tuple(g) for g in e.goals}
            outage_steps = [t for t, g in enumerate(e._out_goals_by_step) if g]
            self.assertTrue(outage_steps)
            for t in outage_steps:
                self.assertTrue(e._obstacles_by_step[t])
                self.assertTrue(e._obstacles_by_step[t] <= goals)  # only goal cells, never a blind blocked cell
        finally:
            env.close()

    def test_determinism(self):
        a = episode(blocked_cfg(known=False), 1, 150)
        b = episode(blocked_cfg(known=False), 1, 150)
        self.assertEqual(a[1], b[1])
        self.assertEqual(a[0], b[0])

    def test_blind_skips_present_and_zero_without_blind_cells(self):
        infos = episode({}, 0, 20)[0]
        self.assertTrue(all(i["blind_skips"] == 0 and isinstance(i["blind_skips"], int) for i in infos))


class TestUnitSemantics(unittest.TestCase):
    """Constructed state at t=0, no seed search. Drive resolve_move_conflict directly."""

    FLOOR = {"floor": {"cells": 6, "p": [1, 1]}}

    def setUp(self):
        self.env = reset_env({**blocked_cfg(known=False), **self.FLOOR}, 0, 50)
        self.e = self.env.env

    def tearDown(self):
        self.env.close()

    def prep(self, aidx=0, direction=Direction.RIGHT, blind=True, known=False):
        e = self.e
        a = e.agents[aidx]
        a.dir = direction
        for o in e.agents:
            o.req_action = Action.NOOP
        a.req_action = Action.FORWARD
        tx, ty = {Direction.RIGHT: (a.x + 1, a.y), Direction.LEFT: (a.x - 1, a.y),
                  Direction.UP: (a.x, a.y - 1), Direction.DOWN: (a.x, a.y + 1)}[direction]
        e.floor_cells = {}
        e._blind_by_step[0] = frozenset({(tx, ty)}) if blind else frozenset()
        e._blocked_by_step[0] = frozenset({(tx, ty)})
        e._obstacles_by_step[0] = frozenset({(tx, ty)}) if known else frozenset()
        return a, (tx, ty)

    def go(self):
        self.e.resolve_move_conflict(self.e.agents)
        return {k: getattr(self.e, "applied_" + k)[-1] for k in ("blind", "floor", "frozen", "delayed")}

    def test_forward_into_blind_cell_is_noop_and_suppressed(self):
        a, target = self.prep()
        pos, d = (a.x, a.y), a.dir
        self.assertEqual(a.req_location(self.e.grid_size), target)
        ap = self.go()
        self.assertEqual(a.req_action, Action.NOOP)
        self.assertEqual((a.x, a.y), pos)
        self.assertEqual(a.dir, d)
        a.req_action = Action.FORWARD  # NOOPed, but the FORWARD target is still the blind cell
        self.assertEqual(a.req_location(self.e.grid_size), target)
        self.assertTrue(ap["blind"][a.id - 1])
        self.assertEqual(int(ap["blind"].sum()), 1)
        self.assertFalse(ap["floor"].any() or ap["delayed"].any() or ap["frozen"].any())
        self.assertTrue(self.e._suppressed[a.id - 1])

    def test_non_forward_actions_are_not_blind_skipped(self):
        for act in (Action.LEFT, Action.RIGHT, Action.NOOP, Action.TOGGLE_LOAD):
            with self.subTest(act=act):
                a, _ = self.prep()
                a.req_action = act
                self.assertEqual(int(self.go()["blind"].sum()), 0)
                self.assertEqual(a.req_action, act)

    def test_stuck_counter_not_advanced(self):
        a, _ = self.prep()
        for o in self.e.agents:
            o.busy = o is a
        c = self.e.stuck_counters[a.id - 1]
        c.position, c.count = (a.x, a.y), 3
        self.e.resolve_move_conflict(self.e.agents)
        self.e.resolve_stuck_agents()
        self.assertEqual(c.count, 3)
        self.assertTrue(a.busy)
        self.assertEqual(self.e._abandoned, 0)

    def test_frozen_and_delayed_beat_blind(self):
        a, _ = self.prep()
        self.e.frozen_schedule[a.id - 1, 0] = True
        ap = self.go()
        self.assertEqual(int(ap["blind"].sum()), 0)
        self.assertTrue(ap["frozen"][a.id - 1])
        self.env.close()
        self.setUp()
        a, _ = self.prep()
        self.e.delay_schedule[a.id - 1, 0] = True
        ap = self.go()
        self.assertEqual(int(ap["blind"].sum()), 0)
        self.assertTrue(ap["delayed"][a.id - 1])

    def test_floor_and_blind_on_the_same_cell_both_coin_orders(self):
        for coin, floor_n, blind_n in ((0.1, 1, 0), (0.9, 0, 1)):
            with self.subTest(coin=coin):
                self.env.close()
                self.setUp()
                a, target = self.prep()
                self.e.floor_cells = {target: 0.5}
                self.e.floor_coin[:] = coin
                ap = self.go()
                self.assertEqual(int(ap["floor"].sum()), floor_n)
                self.assertEqual(int(ap["blind"].sum()), blind_n)
                self.assertEqual(a.req_action, Action.NOOP)
                self.assertTrue(self.e._suppressed[a.id - 1])

    def test_known_obstacle_never_counts_as_blind(self):
        a, _ = self.prep(blind=False, known=True)
        ap = self.go()
        self.assertEqual(a.req_action, Action.NOOP)
        self.assertEqual(int(ap["blind"].sum()), 0)
        self.assertEqual(int(ap["floor"].sum()), 0)
        self.assertFalse(self.e._suppressed[a.id - 1])

    def test_blind_step_index_is_the_executing_step(self):
        a, target = self.prep()
        self.e._t = 3  # blind set only at t=0
        self.assertEqual(int(self.go()["blind"].sum()), 0)
        self.e._t = self.e.max_steps  # out of range must not index
        self.assertEqual(int(self.go()["blind"].sum()), 0)


if __name__ == "__main__":
    unittest.main()

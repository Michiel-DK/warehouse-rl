"""Tests for the disturbance layer (src/warehouse_rl/disturb.py). Envs run strictly one at a time: global np.random is
shared (Agent.counter / Shelf.counter are class attributes too). Each case names its red-demonstration in a comment."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np

import gymnasium as gym

import importlib.util

from warehouse_rl import disturb as dz
from warehouse_rl.env import WarehouseEnv
from warehouse_rl.policy import CtaPolicy, Policy, RandomPolicy

_spec = importlib.util.spec_from_file_location("evaluate_script", ROOT / "scripts" / "evaluate.py")
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)

SMALL = "tarware-small-4agvs-2pickers-globalobs-v1"
MEDIUM = "tarware-medium-8agvs-4pickers-globalobs-v1"
SCRIPT = str(ROOT / "scripts" / "evaluate.py")

# Heavy config for (b), (e): breakdown at 20 onsets per robot-hour (about 0.4 of robot-time frozen at 100 steps with
# 10..30 step durations) plus delay with p_skip 0.3.
HEAVY = {"breakdown": {"rate_per_hour": 20, "duration": [10, 30]}, "delay": {"p_skip": 0.3}}

# The set of types the layer implements; the PR body reports the same set.
LANDED = {"breakdown", "delay", "blocked_cell", "burst", "outage"}


class NoopPolicy(Policy):
    """All actions 0: no agent is ever assigned a task, so no agent is ever busy."""

    def act(self, obs, masks, info):
        return [0] * len(masks)


def rollout(env_id, disturb, seed, steps, policy="cta", setup=None):
    """Generator yielding (env, info) after every step. `setup(env)` runs right after reset (schedule overrides)."""
    env = WarehouseEnv(env_id, max_steps=steps, disturb=disturb)
    try:
        pol = {"cta": CtaPolicy, "noop": NoopPolicy}.get(policy, lambda: RandomPolicy(seed=seed))()
        obs, info = env.reset(seed=seed)
        pol.reset(env)
        if setup:
            setup(env.env)
        for _ in range(steps):
            obs, _, _, _, info = env.step(pol.act(obs, info["action_mask"], info))
            yield env, info
    finally:
        env.close()


def positions(e):
    return [(a.x, a.y) for a in e.agents]


def same_type_overlap(e):
    return (len({p for p in positions(e)[:e.num_agvs]}) < e.num_agvs
            or len({p for p in positions(e)[e.num_agvs:]}) < e.num_agents - e.num_agvs)


class TestEmptyConfigParity(unittest.TestCase):
    def trace(self, disturb):
        out = []
        for seed in range(10):  # sequential: never interleave two envs
            for env, info in rollout(SMALL, disturb, seed, 100):
                e = env.env
                out.append((seed, info["shelf_deliveries"], info["clashes"], info["stucks"],
                            tuple((a.x, a.y, a.dir) for a in e.agents),
                            {k: info.get(k) for k in ("frozen_agents", "delayed_agents", "frozen_fraction",
                                                       "abandoned_tasks")}))
        return out

    # (a) red if the layer's hooks diverge from vendor (stuck handling, find_path), or draw from global np.random
    def test_empty_config_matches_undisturbed(self):
        clean = self.trace(None)
        empty = self.trace({})
        self.assertEqual(len(clean), 1000)
        for c, d in zip(clean, empty):
            self.assertEqual(c[:5], d[:5])
            self.assertEqual(d[5]["frozen_agents"], 0)
            self.assertEqual(d[5]["delayed_agents"], 0)
            self.assertEqual(d[5]["frozen_fraction"], 0)
            self.assertEqual(d[5]["abandoned_tasks"], d[3])  # == info["stucks"] every step
        self.assertTrue(any(c[2] for c in clean))  # non-vacuous: clashes occur

    # (a) red if the layer seeds/draws from global np.random: the global stream after reset differs from vendor's
    def test_reset_leaves_global_rng_alone(self):
        cfg = dict(HEAVY, blocked_cell={"rate_per_hour": 100, "duration": [2, 5]},
                   outage={"rate_per_hour": 100, "duration": [2, 5]})
        env = WarehouseEnv(SMALL, max_steps=100, disturb=cfg)
        env.reset(seed=4)
        state = np.random.get_state()[1].copy()
        env.close()
        plain = WarehouseEnv(SMALL, max_steps=100)
        plain.reset(seed=4)
        np.testing.assert_array_equal(state, np.random.get_state()[1])
        plain.close()


class TestFindPathPort(unittest.TestCase):
    # (a) red if the ported find_path body diverges from vendor (e.g. the picker start_fix is dropped): with no
    # obstacles it must return exactly what Warehouse.find_path returns, for every agent and every target.
    def test_port_equals_vendor_without_obstacles(self):
        from tarware.warehouse import Warehouse
        n = 0
        for seed in range(3):
            env = WarehouseEnv(SMALL, max_steps=10, disturb={})
            env.reset(seed=seed)
            e = env.env
            for a in e.agents:
                for target in e.action_id_to_coords_map.values():  # (y, x)
                    for care in (False, True):
                        want = Warehouse.find_path(e, (a.y, a.x), target, a, care)
                        got = e._find_path_with_obstacles((a.y, a.x), target, a, care, frozenset())
                        self.assertEqual(got, want)
                        n += 1
            env.close()
        self.assertGreater(n, 1000)

    def test_port_equals_vendor_picker_start_fix_case(self):
        # pickers starting on a rack cell next to the target (the start_fix branch, W:289-296)
        from tarware.warehouse import Warehouse
        env = WarehouseEnv(SMALL, max_steps=10, disturb={})
        env.reset(seed=0)
        e = env.env
        picker = e.agents[-1]
        cells = list(e.action_id_to_coords_map.values())  # (y, x)
        racks = [c for c in cells if not e._is_highway(c[1], c[0]) and (c[1], c[0]) not in e.goals]
        n = 0
        for start in racks:
            for target in cells:
                if target[0] == start[0] and abs(target[1] - start[1]) <= 2:
                    want = Warehouse.find_path(e, start, target, picker, False)
                    self.assertEqual(e._find_path_with_obstacles(start, target, picker, False, frozenset()), want)
                    n += 1
        self.assertGreater(n, 50)
        env.close()


class TestNoSharedCell(unittest.TestCase):
    def check_map(self, env_id):
        fracs = []
        for seed in range(20):
            f = 0.0
            for env, info in rollout(env_id, HEAVY, seed, 100):
                f += info["frozen_fraction"]
                # AGV + picker on one rack cell is vendor-legal and not checked
                self.assertFalse(same_type_overlap(env.env), msg=f"{env_id} seed {seed}")
            fracs.append(f / 100)
        self.assertGreaterEqual(float(np.mean(fracs)), 0.25)

    # (b) is a SAFETY-INVARIANT test. The criterion's named injection (move the freeze NOOP to AFTER
    # super().resolve_move_conflict) is structurally unreachable (operator ruling R1): the vendor NOOPs, unconditionally,
    # any mover whose next cell equals another agent's CURRENT cell (vendor warehouse.py ~W:445-449, the
    # `(agent_new_x, agent_new_y) == (other.x, other.y)` branch), so no ordering of the freeze NOOP can put two
    # same-type agents on one cell; that mutation stays green by construction. The accepted red injection is: hide the
    # suppressed agents from the agent_list passed to super().resolve_move_conflict, which turns this test red
    # (counts in the PR body). The NOOP-before-super order is kept anyway: it lets super see a frozen agent as stationary.
    def test_small(self):
        self.check_map(SMALL)

    def test_medium(self):
        self.check_map(MEDIUM)


def schedule_digest(env_id, cfg, seed):
    env = WarehouseEnv(env_id, max_steps=100, disturb=cfg)
    env.reset(seed=seed)
    e = env.env
    h = hashlib.sha256()
    for arr in (e.frozen_schedule, e.delay_schedule):
        h.update(np.ascontiguousarray(arr).tobytes())
    h.update(repr(e._obstacles_by_step).encode())
    env.close()
    return h.hexdigest()


class TestCommonRandomNumbers(unittest.TestCase):
    CFG = dict(HEAVY, blocked_cell={"rate_per_hour": 200, "duration": [2, 8]})

    # (c) red if draws are lazy/conditional on env state: the applied masks would differ between CTA and Random
    def test_masks_identical_across_policies_and_equal_schedule(self):
        applied = {}
        for name in ("cta", "random"):
            for env, _ in rollout(SMALL, HEAVY, 3, 100, policy=name):
                pass
            e = env.env
            applied[name] = (np.array(e.applied_frozen).T, np.array(e.applied_delayed).T)
            expect_f = e.frozen_schedule
            expect_d = e.delay_schedule & ~e.frozen_schedule  # frozen takes precedence
            np.testing.assert_array_equal(applied[name][0], expect_f)
            np.testing.assert_array_equal(applied[name][1], expect_d)
            self.assertTrue(expect_f.any() and expect_d.any())
        np.testing.assert_array_equal(applied["cta"][0], applied["random"][0])
        np.testing.assert_array_equal(applied["cta"][1], applied["random"][1])

    # (c2) red if a mask depends on agent state (e.g. only freeze agents that are busy): under an all-NOOP policy no
    # agent is ever busy, so such a mask would differ from the CTA run (and from the pre-generated schedule).
    def test_masks_identical_for_all_noop_policy(self):
        for seed in (0, 1, 3):
            applied = {}
            for name in ("cta", "noop"):
                busy_seen = False
                for env, _ in rollout(SMALL, HEAVY, seed, 100, policy=name):
                    busy_seen |= any(a.busy for a in env.env.agents)
                e = env.env
                self.assertEqual(busy_seen, name == "cta")  # non-vacuous: noop never busy, cta is
                applied[name] = (np.array(e.applied_frozen).T, np.array(e.applied_delayed).T)
                np.testing.assert_array_equal(applied[name][0], e.frozen_schedule)
                np.testing.assert_array_equal(applied[name][1], e.delay_schedule & ~e.frozen_schedule)
                self.assertTrue(e.frozen_schedule.any() and e.delay_schedule.any())
            np.testing.assert_array_equal(applied["cta"][0], applied["noop"][0])
            np.testing.assert_array_equal(applied["cta"][1], applied["noop"][1])

    def test_schedule_differs_for_other_seed_and_config(self):
        base = schedule_digest(SMALL, self.CFG, 0)
        self.assertEqual(base, schedule_digest(SMALL, self.CFG, 0))
        self.assertNotEqual(base, schedule_digest(SMALL, self.CFG, 1))
        other = json.loads(json.dumps(self.CFG))
        other["delay"]["p_skip"] = 0.31
        self.assertNotEqual(base, schedule_digest(SMALL, other, 0))

    # (c) red if the seed uses Python hash() (salted per process) instead of sha256
    def test_schedule_identical_across_pythonhashseed(self):
        code = (
            "import sys; sys.path.insert(0, %r); sys.path.insert(0, %r)\n"
            "import test_disturb as t, json\n"
            "print(t.schedule_digest(t.SMALL, json.loads(%r), 0))\n"
        ) % (str(ROOT / "src"), str(ROOT / "tests"), json.dumps(self.CFG))
        digests = set()
        for hs in ("1", "2"):
            out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, timeout=120,
                                 env=dict(os.environ, PYTHONHASHSEED=hs))
            digests.add(out.stdout.strip().splitlines()[-1])
        digests.add(schedule_digest(SMALL, self.CFG, 0))
        self.assertEqual(len(digests), 1)


def find_onset(kind):
    """Dry run (empty schedule, same seed => identical trajectory up to the onset): first step s >= 3 and AGV i with
    busy, StuckCounter.count == 0 and a path of >= 2 cells."""
    for env, info in rollout(SMALL, {}, 0, 60):
        e = env.env
        s = env.step_count  # steps completed; the next step has index s
        if s < 3:
            continue
        for i, a in enumerate(e.agents[:e.num_agvs]):
            if a.busy and e.stuck_counters[i].count == 0 and len(a.path) >= 2 and not a.carrying_shelf:
                return s, i
    raise AssertionError("no onset found")


class TestStuckSuppression(unittest.TestCase):
    FREEZE = 20

    def run_freeze(self, field):
        s, i = find_onset(field)

        def setup(e):
            # deterministic schedule set after reset: AGV i is frozen/delayed for steps s .. s + FREEZE - 1
            getattr(e, field)[i, s:s + self.FREEZE] = True

        path0 = None
        n = 0
        for env, info in rollout(SMALL, {}, 0, s + self.FREEZE, setup=setup):
            e = env.env
            a = e.agents[i]
            n += 1
            if n == s:
                self.assertTrue(a.busy and len(a.path) >= 2)
                path0 = list(a.path)
            if n <= s:
                continue
            msg = f"{field} step {n}"
            self.assertTrue(a.busy, msg)
            self.assertEqual(a.path, path0, msg)
            self.assertEqual(e.stuck_counters[i].count, 0, msg)
            self.assertEqual(info["abandoned_tasks"], 0, msg)
            self.assertEqual(info["stucks"], 0, msg)
        self.assertEqual(n, s + self.FREEZE)

    # (d) red if suppression is removed: the counter climbs past 5 + column_height + 2 and the task is dropped
    def test_frozen_agv_keeps_task_and_counter(self):
        self.run_freeze("frozen_schedule")

    def test_delayed_agv_keeps_task_and_counter(self):
        self.run_freeze("delay_schedule")


class TestMetrics(unittest.TestCase):
    PIN_SEED = 13  # small map, HEAVY, 100 steps: one natural abandon, clashes and stuck agents all occur

    # (e) red if any metric is computed differently from its definition
    def test_pinned_run_metrics(self):
        log = []
        cum = 0
        seen = dict(stuck=0, clash=0, abandoned=0)

        def setup(e):
            orig = e.resolve_stuck_agents

            def wrapped():
                before = [a.busy for a in e.agents]
                r = orig()
                log.append(sum(1 for b, a in zip(before, e.agents) if b and not a.busy))
                return r
            e.resolve_stuck_agents = wrapped

        for env, info in rollout(SMALL, HEAVY, self.PIN_SEED, 100, setup=setup):
            e = env.env
            cum += info["shelf_deliveries"]
            self.assertEqual(info["stuck_agents"], sum(c.count > 0 for c in e.stuck_counters))
            self.assertEqual(info["clash_agents"], sum(a.fixing_clash > 0 for a in e.agents))
            self.assertEqual(info["abandoned_tasks"], log[-1])
            self.assertEqual(info["abandoned_tasks"], info["stucks"])
            frozen, delayed = e.applied_frozen[-1], e.applied_delayed[-1]
            self.assertEqual(info["frozen_agents"], int(frozen.sum()))
            self.assertEqual(info["delayed_agents"], int((delayed & ~frozen).sum()))
            self.assertEqual(info["frozen_fraction"], info["frozen_agents"] / e.num_agents)
            self.assertEqual(sum(info["delivered_per_agent"]), cum)
            self.assertEqual(len(info["delivered_per_agent"]), e.num_agents)
            seen["stuck"] += info["stuck_agents"]
            seen["clash"] += info["clash_agents"]
            seen["abandoned"] += info["abandoned_tasks"]
        self.assertGreater(seen["stuck"], 0)
        self.assertGreater(seen["clash"], 0)
        self.assertGreater(seen["abandoned"], 0)

    # (e) red if suppression/bookkeeping makes abandoned_tasks (busy True->False in resolve_stuck_agents) diverge from
    # the vendor's own stuck count on any step; seeds 0-4 under heavy disturbance, not only the pinned seed
    def test_abandoned_equals_stucks_heavy_seeds(self):
        total = 0
        for seed in range(5):
            for _, info in rollout(SMALL, HEAVY, seed, 100):
                self.assertEqual(info["abandoned_tasks"], info["stucks"], msg=f"seed {seed}")
                total += info["stucks"]
        self.assertGreater(total, 0)  # non-vacuous

    # (e) red if stuck_busy_agents is not "busy and count > 0"; stuck_agents (count > 0) keeps counting idle agents
    # with stale counts (vendor resets a StuckCounter only on a new assignment), so busy <= all, and strictly less
    # on at least one step of this run.
    def test_stuck_busy_agents(self):
        strictly_less = 0
        for env, info in rollout(SMALL, HEAVY, self.PIN_SEED, 100):
            e = env.env
            want = sum(a.busy and c.count > 0 for a, c in zip(e.agents, e.stuck_counters))
            self.assertEqual(info["stuck_busy_agents"], want)
            self.assertEqual(info["stuck_agents"], sum(c.count > 0 for c in e.stuck_counters))
            self.assertLessEqual(info["stuck_busy_agents"], info["stuck_agents"])
            strictly_less += info["stuck_busy_agents"] < info["stuck_agents"]
        self.assertGreater(strictly_less, 0)

    # (e) red if deliveries are credited to the wrong agent or not at all (non-vacuous: >= 3 deliveries)
    def test_delivered_per_agent_sums_to_deliveries(self):
        cum = 0
        for env, info in rollout(SMALL, {"delay": {"p_skip": 0.1}}, 0, 150):
            cum += info["shelf_deliveries"]
            self.assertEqual(sum(info["delivered_per_agent"]), cum)
        self.assertGreaterEqual(cum, 3)
        self.assertEqual(info["delivered_per_agent"][env.env.num_agvs:], [0, 0])  # pickers never deliver


class TestConfigValidation(unittest.TestCase):
    def bad(self, cfg):
        with self.assertRaises(ValueError, msg=repr(cfg)):
            WarehouseEnv(SMALL, max_steps=10, disturb=cfg)

    # (f) red if any check is dropped
    def test_fail_closed(self):
        bd = {"rate_per_hour": 1.0, "duration": [1, 2]}
        for cfg in [
            {"bogus": {}},
            {"breakdown": dict(bd, extra=1)},
            {"breakdown": {"rate_per_hour": 1.0}},
            {"breakdown": dict(bd, rate_per_hour="1")},
            {"breakdown": dict(bd, rate_per_hour=True)},
            {"breakdown": dict(bd, rate_per_hour=-1)},
            {"breakdown": dict(bd, duration=[0, 3])},
            {"breakdown": dict(bd, duration=[5, 3])},
            {"breakdown": dict(bd, duration=[1.5, 3])},
            {"breakdown": dict(bd, duration=3)},
            {"breakdown": dict(bd, agent_types=["robot"])},
            {"breakdown": dict(bd, agent_types=[])},
            {"breakdown": [1]},
            {"delay": {"p_skip": 1.1}},
            {"delay": {"p_skip": -0.1}},
            {"delay": {"p_skip": "0.1"}},
            {"delay": {"p_skip": 0.1, "duration": [2, 1]}},
            {"delay": {"p_skip": 0.1, "unknown": 1}},
            {"blocked_cell": {"rate_per_hour": -1, "duration": [1, 2]}},
            {"blocked_cell": {"rate_per_hour": 1, "duration": [0, 2]}},
            {"outage": {"rate_per_hour": 1}},
            {"burst": {"start": 5, "end": 5, "extra": 1}},
            {"burst": {"start": 1, "end": 5, "extra": 0}},
            {"burst": {"start": 1.0, "end": 5, "extra": 1}},
            "breakdown-light",
            [],
            0,
        ]:
            self.bad(cfg)

    def test_valid_configs_construct(self):
        for cfg in [{}, {"breakdown": {"rate_per_hour": 0, "duration": [1, 1], "agent_types": ["picker"]}},
                    {"delay": {"p_skip": 0}}, {"delay": {"p_skip": 1, "duration": [1, 3]}}]:
            WarehouseEnv(SMALL, max_steps=10, disturb=cfg).close()

    # (f) the landed set is hard-coded here and must equal the set reported in the PR body. All five types landed, so
    # the loop over optional types NOT in LANDED is vacuous today (it only bites if one is later removed from
    # LANDED_TYPES); the unknown-type check below is what exercises the "not implemented -> ValueError" path.
    def test_landed_set_and_unimplemented_types_raise(self):
        self.assertEqual(set(dz.LANDED_TYPES), LANDED)
        for name in ("blocked_cell", "burst", "outage"):
            if name not in LANDED:
                self.bad({name: {}})
        self.bad({"earthquake": {"rate_per_hour": 1.0, "duration": [1, 2]}})
        for name in sorted(LANDED):  # empty sub-config is invalid for every landed type (missing keys)
            self.bad({name: {}})

    def test_resolve_disturb(self):
        self.assertEqual(dz.resolve_disturb("none"), ("none", {}))
        tag, cfg = dz.resolve_disturb('{"delay": {"p_skip": 0.2}}')
        self.assertEqual(cfg, {"delay": {"p_skip": 0.2}})
        self.assertTrue(tag.startswith("cfg-") and len(tag) == 14)
        self.assertEqual(tag, "cfg-" + hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:10])
        for spec in ("nope", "{bad json", '{"delay": {"p_skip": 2}}', '[1]', 5):
            with self.assertRaises(ValueError):
                dz.resolve_disturb(spec)


class TestBlockedCell(unittest.TestCase):
    CFG = {"blocked_cell": {"rate_per_hour": 720, "duration": [20, 30]}}  # onset probability 1 per step

    # (g) red if the FORWARD-into-blocked NOOP is removed (agents enter) or find_path ignores the cells (routes through)
    def test_no_entry_and_no_path_through(self):
        total_blocked = 0
        for seed in range(3):
            prev = None
            for env, info in rollout(SMALL, self.CFG, seed, 60):
                e = env.env
                t = e._t - 1  # index of the step just executed
                obstacles = e._obstacles_by_step[t]
                total_blocked += len(obstacles)
                self.assertEqual(info["blocked_cells"], len(obstacles))
                if prev is not None:
                    for old, new in zip(prev, positions(e)):
                        self.assertFalse(new in obstacles and new != old, msg=f"entered {new} at step {t}")
                prev = positions(e)
                # paths planned for the next step avoid the cells active then
                nxt = e._obstacles_now()
                for a in e.agents[:3]:
                    for gx, gy in ((0, 2), (12, 5)):
                        goal = (gy, gx)  # find_path takes (y, x), returns (x, y) cells
                        if (gx, gy) in nxt:
                            self.assertEqual(e.find_path((a.y, a.x), goal, a, care_for_agents=False), [])
                        else:
                            path = e.find_path((a.y, a.x), goal, a, care_for_agents=False)
                            self.assertFalse(set(path) & nxt, msg=f"path through blocked at step {t}")
        self.assertGreater(total_blocked, 100)

    def test_blocked_target_yields_empty_path(self):
        env = WarehouseEnv(SMALL, max_steps=10, disturb=self.CFG)
        env.reset(seed=0)
        e = env.env
        a = e.agents[0]
        cell = next(iter(e._obstacles_by_step[0]))
        self.assertEqual(e.find_path((a.y, a.x), (cell[1], cell[0]), a, care_for_agents=False), [])
        env.close()


class TestBurst(unittest.TestCase):
    BASE = 20
    CFG = {"burst": {"start": 2, "end": 5, "extra": 2}}

    # (g) red if the burst never starts, or if the queue is not shrunk after `end`
    def test_queue_grows_then_shrinks_with_deliveries(self):
        lens, cum_after_end = [], 0
        for env, info in rollout(SMALL, self.CFG, 0, 100):
            t = env.step_count - 1  # index of the step just executed
            lens.append(info["request_queue_len"])
            self.assertEqual(info["request_queue_len"], len(env.env.request_queue))
            if t >= 5:
                cum_after_end += info["shelf_deliveries"]
            if t < 2:
                self.assertEqual(info["request_queue_len"], self.BASE)
            elif t < 5:
                self.assertEqual(info["request_queue_len"], self.BASE + 2)
            else:
                self.assertEqual(info["request_queue_len"], self.BASE + 2 - min(2, cum_after_end))
        self.assertEqual(lens[2], self.BASE + 2)  # right after start
        self.assertEqual(lens[-1], self.BASE)
        self.assertGreaterEqual(cum_after_end, 2)
        self.assertEqual(len({s.id for s in env.env.request_queue}), self.BASE)


class TestBurstOrder(unittest.TestCase):
    CFG = {"burst": {"start": 2, "end": 5, "extra": 3}}

    # (g3) red if burst shelves are drawn at run time from a state-dependent rng/choice instead of the order
    # pre-generated at reset: the order is identical for CTA, Random and all-NOOP, differs by seed, and the added
    # shelves are the first `extra` in that order that were not queued/carried. Identities are state-filtered, so burst
    # is only approximately paired across policies (see disturb.py docstring).
    def test_order_pregenerated_and_followed(self):
        orders = {}
        for name in ("cta", "random", "noop"):
            before = None
            for env, info in rollout(SMALL, self.CFG, 0, 6, policy=name):
                e = env.env
                if env.step_count == 2:  # burst starts at step index 2, which has not run yet
                    before = {s.id for s in e.request_queue}
                if env.step_count == 3:
                    carried = {a.carrying_shelf.id for a in e.agents if a.carrying_shelf}
                    added = [s.id for s in e.request_queue if s.id not in before]
                    free = [sid for sid in e.burst_order if sid not in before and sid not in carried]
                    self.assertEqual(added, free[:3])
                    self.assertEqual(len(added), 3)
            orders[name] = list(e.burst_order)
            self.assertEqual(sorted(orders[name]), sorted(s.id for s in e.shelfs))
        self.assertEqual(orders["cta"], orders["random"])
        self.assertEqual(orders["cta"], orders["noop"])
        env = WarehouseEnv(SMALL, max_steps=6, disturb=self.CFG)
        env.reset(seed=1)
        self.assertNotEqual(orders["cta"], env.env.burst_order)
        env.close()
        self.assertIn("approximately paired", dz.__doc__.lower())

    def test_no_burst_no_order(self):
        for env, _ in rollout(SMALL, {}, 0, 1):
            self.assertEqual(env.env.burst_order, [])


class TestOutage(unittest.TestCase):
    # In the clean run an AGV reaches goal index 2 (cell (6, 24)) at step 19 and delivers there at step 20.
    GOAL = 2
    STEPS = 40

    def setup(self, e):
        # deterministic schedule (the config path is covered below): goal 2 out of service for the whole window
        cell = tuple(e.goals[self.GOAL])
        for t in range(self.STEPS):
            e._out_goals_by_step[t] = (self.GOAL,)
            e._obstacles_by_step[t] = frozenset({cell})

    def clean_visits(self):
        visits = 0
        for env, _ in rollout(SMALL, {}, 0, self.STEPS):
            e = env.env
            visits += any((a.x, a.y) == tuple(e.goals[self.GOAL]) for a in e.agents[:e.num_agvs])
        return visits

    # (g) red if the goal cell is not impassable (AGV enters) or not masked in compute_action_masks
    def test_out_goal_not_entered_not_removed_and_masked(self):
        self.assertGreater(self.clean_visits(), 0)  # non-vacuous: the clean run does use this goal
        n_goals = None
        for env, info in rollout(SMALL, {}, 0, 1, setup=lambda e: None):
            n_goals = len(env.env.goals)
        cell = (6, 24)
        for env, info in rollout(SMALL, {}, 0, self.STEPS, setup=self.setup):
            e = env.env
            self.assertEqual(tuple(e.goals[self.GOAL]), cell)
            self.assertEqual(len(e.goals), n_goals)
            if env.step_count < self.STEPS:
                self.assertFalse(info["action_mask"][:e.num_agvs, 1 + self.GOAL].any())
            self.assertFalse(any((a.x, a.y) == cell for a in e.agents[:e.num_agvs]), msg=f"step {env.step_count}")
            self.assertEqual(info["outage_goals"], 1)

    # (g2) red if the outage loop in WarehouseEnv.compute_action_masks is removed. The mask hides the out goal's action
    # id (1 + goal index) for AGVs exactly on the steps it is out, and equals the carrying flag (vendor rule) otherwise.
    # The mask returned with the info after step n describes the next step to run, index e._t.
    def test_mask_hides_out_goal_exactly_while_out(self):
        window = range(10, 30)

        def setup(e):
            cell = tuple(e.goals[self.GOAL])
            for t in window:
                e._out_goals_by_step[t] = (self.GOAL,)
                e._obstacles_by_step[t] = frozenset({cell})

        in_window_carrying = out_window_carrying = 0
        n_out = n_in = 0
        for env, info in rollout(SMALL, {}, 0, 39, setup=setup):
            e = env.env
            t = e._t
            carrying = np.array(e.get_carrying_shelf_information(), dtype=bool)
            col = info["action_mask"][:e.num_agvs, 1 + self.GOAL]
            if t in window:
                n_in += 1
                self.assertFalse(col.any(), msg=f"t={t}")
                in_window_carrying += int(carrying.any())
            else:
                n_out += 1
                np.testing.assert_array_equal(col, carrying, err_msg=f"t={t}")
                out_window_carrying += int(carrying.any())
        self.assertGreater(n_in, 10)
        self.assertGreater(n_out, 10)
        self.assertGreater(in_window_carrying, 0)  # non-vacuous: hiding changed something
        self.assertGreater(out_window_carrying, 0)

    # (g) red if the config-driven schedule does not make the out goal cell impassable (the obstacle link), checked
    # on the step just executed: no AGV enters a goal cell that was out for that step. Non-vacuous: the same seed with
    # the obstacles stripped from the schedule (injection) makes an AGV enter.
    def test_config_driven_outage(self):
        cfg = {"outage": {"rate_per_hour": 120, "duration": [5, 10]}}
        seen = 0
        entries_possible = 0
        prev = None
        for env, info in rollout(SMALL, cfg, 1, 80):
            e = env.env
            t = e._t - 1  # index of the step just executed
            seen += info["outage_goals"]
            self.assertTrue(set(e.outage_goal_indices()) <= set(range(len(e.goals))))
            self.assertEqual(len(e.goals), 6)
            out_cells = {tuple(e.goals[g]) for g in e._out_goals_by_step[t]}
            self.assertEqual(out_cells, set(e._obstacles_by_step[t]))
            now = positions(e)
            if prev is not None:
                for old, new in zip(prev, now):
                    if new in out_cells:
                        self.assertEqual(new, old, msg=f"AGV entered out goal {new} at step {t}")
            prev = now
        self.assertGreater(seen, 0)


class TestEvaluateDisturb(unittest.TestCase):
    def cli(self, policy, tmp, disturb=None, seeds="0-1", steps=50):
        cmd = [sys.executable, SCRIPT, "--policy", policy, "--env", SMALL, "--seeds", seeds, "--steps", str(steps),
               "--workers", "1", "--results-dir", tmp]
        if disturb is not None:
            cmd += ["--disturb", disturb]
        return subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=300)

    # (h) red if the tag/config is not part of the filename and document, or the same-tag CTA delta is not used
    def test_disturbed_filename_config_and_paired_delta(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.cli("cta", tmp)
            self.cli("cta", tmp, "none")
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), [f"cta_{SMALL}_50.json"])
            clean = json.loads((Path(tmp) / f"cta_{SMALL}_50.json").read_text())
            self.assertNotIn("disturb", clean)
            self.assertNotIn("frozen_agent_steps", clean["rows"][0])

            self.cli("cta", tmp, "breakdown-heavy")
            path = Path(tmp) / f"cta_{SMALL}_50_breakdown-heavy.json"
            doc = json.loads(path.read_text())
            self.assertEqual(doc["disturb_tag"], "breakdown-heavy")
            self.assertEqual(doc["disturb"], dz.PRESETS["breakdown-heavy"])
            row = doc["rows"][0]
            for k in ("stuck_agent_steps", "stuck_busy_agent_steps", "abandoned_tasks", "clash_agent_steps", "frozen_agent_steps",
                      "delayed_agent_steps", "frozen_fraction", "delivered_per_agent"):
                self.assertIn(k, row)
            self.assertAlmostEqual(row["frozen_fraction"], row["frozen_agent_steps"] / (50 * 6))
            self.assertEqual(sum(row["delivered_per_agent"]), row["deliveries"])

            out = self.cli("random", tmp, "breakdown-heavy").stdout
            self.assertIn("paired delta (random - cta): n_paired=2", out)
            self.assertTrue((Path(tmp) / f"random_{SMALL}_50_breakdown-heavy.json").exists())

            # same tag, different stored config: refuse to merge
            doc["disturb"] = {"delay": {"p_skip": 0.5}}
            path.write_text(json.dumps(doc))
            with self.assertRaises(ValueError):
                ev.evaluate("cta", SMALL, 50, [0, 1], 1, tmp, "breakdown-heavy")
            r = subprocess.run([sys.executable, SCRIPT, "--policy", "cta", "--env", SMALL, "--seeds", "0",
                                "--steps", "50", "--workers", "1", "--results-dir", tmp, "--disturb",
                                "breakdown-heavy"], capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()

"""Tests for lane E: the blocker_frozen / blocker_frozen_left observation keys, InformedTimeoutRecovery, sweep letter e.
Envs run strictly one at a time (global np.random, Agent.counter and Shelf.counter are shared). Each case names its
red-demonstration in an `# inject:` comment.

Scenario geometry (small map, seed 0): row y = 11 is an empty highway row. A = AGV 1 at (2, 11) facing RIGHT, B = AGV 2 at
(3, 11), D = AGV 4 at (4, 11), P = picker 6 at (5, 11). A is busy with path [(3, 11), (4, 11)]: next cell (3, 11) is B's.
"""
import importlib.util
import json
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import _platform

import numpy as np
from tarware.definitions import Direction

from warehouse_rl import recovery as rc
from warehouse_rl.env import WarehouseEnv

_spec = importlib.util.spec_from_file_location("evaluate_script", ROOT / "scripts" / "evaluate.py")
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)

SMALL = "tarware-small-4agvs-2pickers-globalobs-v1"
SWEEP = str(ROOT / "scripts" / "recovery_sweep.py")
OLD_KEYS = ("event_is_clash", "stuck_count", "fixing_clash", "carrying", "is_picker", "path_len", "manhattan_to_target",
            "nbr_n", "nbr_e", "nbr_s", "nbr_w", "queue_pressure")
A_CELL, B_CELL, D_CELL, P_CELL = (2, 11), (3, 11), (4, 11), (5, 11)
FROZEN_FOR = 30


class Recorder(rc.RecoveryPolicy):
    """Records (hook step, obs) for every decision and always returns `action`."""
    name = "recorder"

    def __init__(self, action="wait"):
        self.action, self.seen, self.hook = action, [], None

    def decide(self, obs):
        self.seen.append((self.hook._t, dict(obs)))
        return self.action


def place(h, agent, cell, direction=Direction.RIGHT):
    agent.x, agent.y = cell
    agent.dir = direction
    agent.busy = False
    agent.path = []
    agent.req_action = 0


def scenario(action="wait", frozen=(2,), t0=0, steps=FROZEN_FOR + 5, run=True):
    """Small-map hook env with the schedule overwritten after reset: every agent id in `frozen` frozen for
    [t0, t0 + FROZEN_FOR). Returns (env, hook, recorder)."""
    env = WarehouseEnv(SMALL, max_steps=200, disturb={}, recovery={"name": "timeout"})
    rec = Recorder(action)
    env.env._recovery = rec
    env.reset(seed=0)
    h = env.env
    rec.hook = h
    h.frozen_schedule = np.zeros_like(h.frozen_schedule)
    for aid in frozen:
        h.frozen_schedule[aid - 1, t0:t0 + FROZEN_FOR] = True
    A, B, D, P = h.agents[0], h.agents[1], h.agents[3], h.agents[5]
    for ag, cell in ((A, A_CELL), (B, B_CELL), (D, D_CELL), (P, P_CELL)):
        place(h, ag, cell)
    A.busy = True
    A.path = [B_CELL, D_CELL]
    h.stuck_counters[0].reset(A_CELL)
    h._recalc_grid()
    if run:
        for _ in range(steps):
            env.step([0] * h.num_agents)
    return env, h, rec


class TestObservationKeys(unittest.TestCase):
    # inject: put the new keys first / in the middle, drop one, or reorder the old twelve
    def test_obs_keys_are_old_twelve_plus_two(self):
        self.assertEqual(rc.RecoveryHook.OBS_KEYS, OLD_KEYS + ("blocker_frozen", "blocker_frozen_left"))
        self.assertIn("decisions_while_blocker_frozen", rc.RECOVERY_INFO_KEYS)
        self.assertIn("reroutes_while_blocker_frozen", rc.RECOVERY_INFO_KEYS)
        self.assertIn("decisions_while_blocker_frozen", ev.RECOVERY_SUMS)
        self.assertIn("reroutes_while_blocker_frozen", ev.RECOVERY_SUMS)

    # inject: use a constant 1.0 flag, skip the frozen check (any occupant), count _left from step 0 instead of _t, or
    # return a constant 30 for _left; in the hook: read applied_frozen / frozen_schedule[:, 0]
    def test_flag_and_countdown_while_blocker_frozen(self):
        env, h, rec = scenario()
        try:
            self.assertTrue(rec.seen)
            by_t = {}
            for t, o in rec.seen:
                by_t.setdefault(t, []).append(o)
            for t in range(FROZEN_FOR + 5):
                self.assertIn(t, by_t, t)  # A decides every step (clash event at least)
                for o in by_t[t]:
                    if t < FROZEN_FOR:
                        self.assertEqual((o["blocker_frozen"], o["blocker_frozen_left"]), (1.0, float(FROZEN_FOR - t)), t)
                    else:  # B's frozen run ended: still standing there, not frozen
                        self.assertEqual((o["blocker_frozen"], o["blocker_frozen_left"]), (0.0, 0.0), t)
            # B really was NOOPed by the layer for exactly the frozen steps
            self.assertEqual([bool(f[1]) for f in h.applied_frozen[:FROZEN_FOR + 5]],
                             [True] * FROZEN_FOR + [False] * 5)
            self.assertEqual((h.agents[0].x, h.agents[0].y), A_CELL)  # A never got through B
            self.assertEqual((h.agents[1].x, h.agents[1].y), B_CELL)
        finally:
            env.close()

    # inject: read the frozen mask one step late (`self._masks_at(max(self._t - 1, 0))[0]` in _blocker), so the flag
    # misses the first step of a breakdown that starts after t = 0 (one step early is caught by the countdown test)
    def test_flag_turns_on_at_the_first_frozen_step(self):
        env, h, rec = scenario(frozen=(2,), t0=3, steps=6)
        try:
            by_t = {}
            for t, o in rec.seen:
                if o["stuck_count"] > 0 or o["event_is_clash"]:
                    by_t.setdefault(t, set()).add((o["blocker_frozen"], o["blocker_frozen_left"]))
            for t in (1, 2, 3, 4, 5):
                self.assertIn(t, by_t, f"A must decide at t={t} (B stands still on A's next cell)")
            self.assertEqual(by_t[2], {(0.0, 0.0)})
            self.assertEqual(by_t[3], {(1.0, float(FROZEN_FOR))})
            self.assertEqual(by_t[4], {(1.0, float(FROZEN_FOR - 1))})
            self.assertTrue(h.applied_frozen[3][1] and not h.applied_frozen[2][1])
        finally:
            env.close()

    # inject: check the frozen agent B regardless of where it stands (flag 1 for D on path[-1] swapped), or ignore the frozen run end
    def test_free_cell_and_unfrozen_occupant_give_zero(self):
        env, h, rec = scenario(run=False)
        try:
            A = h.agents[0]
            self.assertEqual(h._blocker(A), (1.0, float(FROZEN_FOR)))
            A.path = [(2, 12), (2, 13)]  # next cell free
            self.assertEqual(h._blocker(A), (0.0, 0.0))
            A.path = [D_CELL, B_CELL]  # next cell occupied by D, who is not frozen (B is, but is not on path[0])
            self.assertEqual(h._blocker(A), (0.0, 0.0))
            A.path = [B_CELL, D_CELL]
            h.frozen_schedule[1, :] = False  # B no longer frozen at all
            self.assertEqual(h._blocker(A), (0.0, 0.0))
        finally:
            env.close()

    # inject: use path[-1] instead of path[0]
    def test_path_zero_not_path_last_is_the_next_cell(self):
        env, h, rec = scenario(run=False)
        try:
            A = h.agents[0]
            A.path = [B_CELL, D_CELL]  # B (frozen) is path[0], D (not frozen) is the target path[-1]
            self.assertEqual(h._blocker(A)[0], 1.0)
            A.path = [D_CELL, B_CELL]  # now the frozen B is the target, not the next cell
            self.assertEqual(h._blocker(A)[0], 0.0)
        finally:
            env.close()

    # inject: use path[0] even when it is the agent's own cell, or return 1 for an empty path
    def test_start_cell_kept_uses_path_one_and_no_next_cell_is_zero(self):
        env, h, rec = scenario(run=False)
        try:
            A = h.agents[0]
            A.path = [A_CELL, B_CELL, D_CELL]  # vendor find_path can keep the start cell (W:307)
            self.assertEqual(h._blocker(A), (1.0, float(FROZEN_FOR)))
            A.path = [A_CELL]
            self.assertEqual(h._blocker(A), (0.0, 0.0))
            A.path = []
            self.assertEqual(h._blocker(A), (0.0, 0.0))
        finally:
            env.close()

    # inject: filter occupants on agent type or on busy, or take the first frozen occupant instead of the max
    def test_any_agent_type_and_max_over_occupants(self):
        env, h, rec = scenario(frozen=(6,), run=False)  # only the picker (id 6) is frozen
        try:
            A = h.agents[0]
            place(h, h.agents[5], B_CELL)  # picker on A's next cell (idle: busy False)
            place(h, h.agents[1], (3, 12))
            h._recalc_grid()
            self.assertEqual(h._blocker(A), (1.0, float(FROZEN_FOR)))
            self.assertFalse(h.agents[5].busy)
        finally:
            env.close()

    # inject: take the first frozen occupant's run instead of the max (`left = left or run`), or stop at the first
    # occupant found on the cell
    def test_max_over_two_frozen_occupants_on_one_cell(self):
        # an AGV and a picker share a cell (the loading handoff), so two occupants is a real case. The first in agent
        # order (AGV 2) has the SHORTER run, so first-occupant logic returns 10, max returns 25.
        env, h, rec = scenario(frozen=(), run=False)
        try:
            A = h.agents[0]
            place(h, h.agents[5], B_CELL)  # picker 6 joins AGV 2 on A's next cell
            place(h, h.agents[3], (3, 12))
            h._recalc_grid()
            h.frozen_schedule[1, 0:10] = True   # AGV 2: 10 steps
            h.frozen_schedule[5, 0:25] = True   # picker 6: 25 steps
            self.assertEqual([a.id for a in h.agents if (a.x, a.y) == B_CELL], [2, 6])
            self.assertEqual(h._blocker(A), (1.0, 25.0))
            h.frozen_schedule[1, 0:40] = True   # now the AGV has the longer run
            self.assertEqual(h._blocker(A), (1.0, 40.0))
        finally:
            env.close()

    # inject: write env state (advance a stuck counter / the RNG) inside _blocker or _observe
    def test_observation_has_no_side_effects_and_draws_no_randomness(self):
        env, h, rec = scenario(run=False)
        try:
            A = h.agents[0]
            before_rng = np.random.get_state()[1].copy(), random.getstate()
            before = (A.x, A.y, list(A.path), A.fixing_clash, h.stuck_counters[0].count, h._t,
                      h.frozen_schedule.copy(), h.decide_calls, dict(h._counts))
            o1, o2 = h._observe(A, False), h._observe(A, False)
            after = (A.x, A.y, list(A.path), A.fixing_clash, h.stuck_counters[0].count, h._t,
                     h.frozen_schedule, h.decide_calls, dict(h._counts))
            self.assertEqual(o1, o2)
            self.assertEqual(tuple(o1), rc.RecoveryHook.OBS_KEYS)
            for b, a in zip(before, after):
                if isinstance(b, np.ndarray):
                    self.assertTrue(np.array_equal(b, a))
                else:
                    self.assertEqual(b, a)
            self.assertTrue(np.array_equal(before_rng[0], np.random.get_state()[1]))
            self.assertEqual(before_rng[1], random.getstate())
        finally:
            env.close()

    # inject: count decisions only when the action is a reroute, or never count the reroutes
    def test_counters_count_decisions_while_blocker_frozen(self):
        for action in ("wait", "reroute"):
            env, h, rec = scenario(action, run=False)
            try:
                tot = {"decisions_while_blocker_frozen": 0, "reroutes_while_blocker_frozen": 0}
                for _ in range(3):
                    _, _, _, _, info = env.step([0] * h.num_agents)
                    for k in tot:
                        tot[k] += info[k]
                frozen_obs = [o for _, o in rec.seen if o["blocker_frozen"] == 1]
                self.assertGreater(len(frozen_obs), 0)
                self.assertEqual(tot["decisions_while_blocker_frozen"], len(frozen_obs))
                self.assertEqual(tot["reroutes_while_blocker_frozen"], len(frozen_obs) if action == "reroute" else 0)
            finally:
                env.close()


def random_table(n=2000, seed=7):
    rng = random.Random(seed)
    rows = []
    for _ in range(n):
        rows.append({"event_is_clash": float(rng.choice([0, 1])), "stuck_count": float(rng.randint(0, 30)),
                     "fixing_clash": float(rng.randint(0, 4)), "carrying": float(rng.choice([0, 1])),
                     "is_picker": float(rng.choice([0, 1])), "path_len": float(rng.randint(0, 5)),
                     "manhattan_to_target": float(rng.randint(0, 40)), "nbr_n": float(rng.choice([0, 1])),
                     "nbr_e": float(rng.choice([0, 1])), "nbr_s": float(rng.choice([0, 1])),
                     "nbr_w": float(rng.choice([0, 1])), "queue_pressure": rng.random(),
                     "blocker_frozen": 0.0, "blocker_frozen_left": float(rng.randint(0, 40))})
    return rows


def obs(**kw):
    o = dict(event_is_clash=0.0, stuck_count=1.0, fixing_clash=0.0, carrying=0.0, is_picker=0.0, path_len=3.0,
             manhattan_to_target=5.0, nbr_n=0.0, nbr_e=0.0, nbr_s=0.0, nbr_w=0.0, queue_pressure=0.1,
             blocker_frozen=0.0, blocker_frozen_left=0.0)
    o.update(kw)
    return o


class TestInformedPolicy(unittest.TestCase):
    # inject: wait for the timeout when the blocker is frozen, ignore path_len (reroute with an empty path), or key on
    # stuck_count > replan
    def test_flag_reroutes_at_stuck_count_one(self):
        p = rc.InformedTimeoutRecovery(5, 15, "flag")
        self.assertEqual(p.name, "informed_timeout")
        self.assertEqual(p.decide(obs(blocker_frozen=1.0, stuck_count=1.0, path_len=3.0)), "reroute")
        self.assertEqual(p.decide(obs(blocker_frozen=1.0, stuck_count=1.0, path_len=0.0)), "abandon")
        self.assertEqual(p.decide(obs(blocker_frozen=1.0, stuck_count=1.0, blocker_frozen_left=1.0)), "reroute")
        self.assertEqual(p.decide(obs(blocker_frozen=1.0, event_is_clash=1.0, path_len=0.0)), "reroute")
        self.assertEqual(p.decide(obs(blocker_frozen=0.0, stuck_count=1.0)), "wait")

    # inject: change one comparison of the fallback (c >= replan), or give the fallback different parameters
    def test_equals_tuned_timeout_when_blocker_not_frozen_both_modes(self):
        tuned = rc.TunedTimeoutRecovery(5, 15)
        table = random_table()
        for mode in ("flag", "left"):
            p = rc.InformedTimeoutRecovery(5, 15, mode)
            self.assertEqual(len(table), 2000)
            for o in table:
                self.assertEqual(p.decide(o), tuned.decide(o), (mode, o))
        self.assertEqual({tuned.decide(o) for o in table}, {"wait", "reroute", "abandon"})

    # inject: left mode fires on blocker_frozen alone (ignores blocker_frozen_left <= replan), flag mode falls back to
    # the timeout when the flag is set, or either mode lets the flag override a clash
    def test_random_table_with_blocker_frozen(self):
        tuned = rc.TunedTimeoutRecovery(5, 15)
        flag, left = rc.InformedTimeoutRecovery(5, 15, "flag"), rc.InformedTimeoutRecovery(5, 15, "left")
        rng = random.Random(11)
        table = random_table()
        n_short = n_long = 0
        for o in table:
            o = dict(o, blocker_frozen=1.0, blocker_frozen_left=float(rng.randint(1, 40)))
            fire = "reroute" if o["path_len"] > 0 else "abandon"
            if o["event_is_clash"]:
                self.assertEqual(flag.decide(o), "reroute", o)
                self.assertEqual(left.decide(o), "reroute", o)
                continue
            self.assertEqual(flag.decide(o), fire, o)
            if o["blocker_frozen_left"] > 5:
                n_long += 1
                self.assertEqual(left.decide(o), fire, o)
            else:
                n_short += 1
                self.assertEqual(left.decide(o), tuned.decide(o), o)
        self.assertGreater(n_short, 50)
        self.assertGreater(n_long, 50)

    # inject: compare >= replan, compare against replan - stuck_count, or ignore blocker_frozen_left
    def test_left_mode_boundary(self):
        p = rc.InformedTimeoutRecovery(5, 15, "left")
        self.assertEqual(p.name, "informed_timeout_left")
        tuned = rc.TunedTimeoutRecovery(5, 15)
        o = obs(blocker_frozen=1.0, stuck_count=1.0, blocker_frozen_left=5.0)  # == replan: waits like the timeout
        self.assertEqual(p.decide(o), tuned.decide(o))
        self.assertEqual(p.decide(o), "wait")
        o = obs(blocker_frozen=1.0, stuck_count=1.0, blocker_frozen_left=6.0)  # replan + 1: fires
        self.assertEqual(p.decide(o), "reroute")
        self.assertEqual(p.decide(obs(blocker_frozen=1.0, blocker_frozen_left=6.0, path_len=0.0)), "abandon")
        o = obs(blocker_frozen=0.0, stuck_count=1.0, blocker_frozen_left=40.0)  # left alone never fires
        self.assertEqual(p.decide(o), "wait")
        o = obs(blocker_frozen=1.0, event_is_clash=1.0, blocker_frozen_left=1.0)
        self.assertEqual(p.decide(o), "reroute")
        q = rc.InformedTimeoutRecovery(8, 20, "left")  # the threshold is the policy's own replan
        self.assertEqual(q.decide(obs(blocker_frozen=1.0, blocker_frozen_left=8.0)), "wait")
        self.assertEqual(q.decide(obs(blocker_frozen=1.0, blocker_frozen_left=9.0)), "reroute")

    # inject: accept a bad mode, or replan >= abandon
    def test_constructor_validation(self):
        for bad in ("flags", "", None):
            with self.assertRaises(ValueError):
                rc.InformedTimeoutRecovery(5, 15, bad)
        with self.assertRaises(ValueError):
            rc.InformedTimeoutRecovery(15, 5, "flag")

    # inject: drop a name from normalise/make, let unknown keys or a bad mode through, or lose the defaults
    def test_registry_names(self):
        n = rc.normalise_recovery({"name": "informed_timeout"})
        self.assertEqual(n, {"name": "informed_timeout", "replan": 5, "abandon": 15, "call_human_cost": 60})
        n = rc.normalise_recovery({"name": "informed_timeout_left", "replan": 3, "abandon": 9, "call_human_cost": 5})
        self.assertEqual(n, {"name": "informed_timeout_left", "replan": 3, "abandon": 9, "call_human_cost": 5})
        p = rc.make_recovery({"name": "informed_timeout"})
        self.assertEqual((type(p), p.mode, (p.replan, p.abandon)), (rc.InformedTimeoutRecovery, "flag", (5, 15)))
        p = rc.make_recovery({"name": "informed_timeout_left", "replan": 3, "abandon": 9})
        self.assertEqual((p.mode, (p.replan, p.abandon)), ("left", (3, 9)))
        for bad in ({"name": "informed_timeout", "mode": "left"}, {"name": "informed_timeout", "x": 1},
                    {"name": "informed_timeout", "replan": 15, "abandon": 5}, {"name": "informed_timeout_left", "replan": True},
                    {"name": "informed_timeout", "call_human_cost": -1}, {"name": "informed"}):
            with self.assertRaises(ValueError, msg=str(bad)):
                rc.normalise_recovery(bad)
        tag, cfg = rc.resolve_recovery('{"name": "informed_timeout_left"}')
        self.assertTrue(tag.startswith("rec-"))
        self.assertEqual(cfg["replan"], 5)


class TestExistingPoliciesBitIdentical(unittest.TestCase):
    # inject: let TimeoutRecovery read blocker_frozen (e.g. wait when it is 1), or change the key order/clock so a
    # decision's obs differs; any such change moves deliveries/recovery_* counts of seed 0 at rate 1
    def test_timeout_rows_reproduce_stored_json(self):
        path = ROOT / "results" / "recovery" / "timeout.json"
        if not path.exists():
            self.skipTest(f"{path} absent")
        import sweep
        stored_doc = json.loads(path.read_text())
        stored = [r for r in stored_doc["rows"] if r["point"] == 1 and r["seed"] in (0, 1)]
        self.assertEqual(sorted(r["seed"] for r in stored), [0, 1])
        env_id, cfg, _ = sweep.point_spec("breakdown", 1)
        fields = ["pick_rate", "deliveries", "clashes", "stucks", "call_human_steps", "stuck_busy_agent_steps",
                  "abandoned_tasks", "frozen_agent_steps"]
        fields += [k for k in ev.RECOVERY_SUMS if k.startswith("recovery_")]
        rows = []
        for r in stored:
            row = ev.run_seed("stuck_aware_cta", env_id, 500, r["seed"], disturb=cfg,
                              recovery=rc.normalise_recovery({"name": "timeout"}))
            for f in fields:
                self.assertIn(f, r, f)
            self.assertEqual(row["decisions_while_blocker_frozen"] >= 0, True)
            rows.append((r, row))
        # everything above is portable; the values are only comparable on the platform the stored file was measured on
        file_platform = _platform.results_platform(stored_doc)
        if _platform.tag() != file_platform:
            self.skipTest(f"{path.relative_to(ROOT)} measured on {file_platform}, running on {_platform.tag()}: "
                          "value comparison skipped")
        for r, row in rows:
            for f in fields:
                self.assertEqual(row[f], r[f], (r["seed"], f))


class TestLearnedFormatV3(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import torch
        cls.torch = torch
        from warehouse_rl import learned_recovery as lr
        cls.lr = lr

    # inject: leave FORMAT_VERSION at 2, or accept a v2 checkpoint, or drop either version from the message
    def test_v2_refused_v3_roundtrips(self):
        lr, torch = self.lr, self.torch
        self.assertEqual(lr.FORMAT_VERSION, 3)
        self.assertEqual(len(lr.OBS_KEYS), 14)
        self.assertEqual(set(lr.OBS_SCALE), set(lr.OBS_KEYS))
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            torch.manual_seed(0)
            sd = lr.QNet().state_dict()
            good = d / "v3.pt"
            lr.save_checkpoint(good, sd, lr.reward_constants(), {"seed": 0})
            ck = lr.load_checkpoint(good)
            self.assertEqual(ck["version"], 3)
            self.assertEqual(len(ck["obs_keys"]), 14)
            self.assertEqual(sd["net.0.weight"].shape, (64, 14))
            old = dict(torch.load(good, weights_only=True), version=2, obs_keys=list(OLD_KEYS))
            old["obs_scale"] = {k: v for k, v in old["obs_scale"].items() if k in OLD_KEYS}
            torch.save(old, d / "old.pt")  # no digits in the name: the versions must come from the message
            with self.assertRaises(ValueError) as cm:
                lr.load_checkpoint(d / "old.pt")
            msg = str(cm.exception)
            self.assertIn("checkpoint version 2 != required version 3", msg)
            self.assertIn("12-key", msg)
            self.assertIn("retrain", msg)


def run_sweep(args, results_dir):
    return subprocess.run([sys.executable, SWEEP, *args, "--results-dir", str(results_dir)], capture_output=True,
                          text=True, timeout=900)


class TestSweepE(unittest.TestCase):
    # inject: default --only gains e, e writes rows without the two counters, the plot reads recomputed timeout rows,
    # or a rerun re-runs (or rewrites) rows already on disk
    def test_smoke_rows_png_and_resume(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            r = run_sweep(["--smoke", "--only", "a", "--workers", "2"], d)
            self.assertEqual(r.returncode, 0, r.stderr)
            r = run_sweep(["--smoke", "--only", "e", "--workers", "2"], d)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("[informed] 8 jobs to run", r.stdout)
            self.assertNotIn("warning: no", r.stdout)  # the timeout rows were found
            path = d / "recovery" / "informed_smoke.json"
            doc = json.loads(path.read_text())
            rows = doc["rows"]
            self.assertEqual({(x["point"], x["config"], x["seed"]) for x in rows},
                             {(g, c, s) for g in (1, 8) for c in ("informed flag", "informed left") for s in (0, 1)})
            self.assertEqual(len(rows), 8)
            timeout_row = json.loads((d / "recovery" / "timeout_smoke.json").read_text())["rows"][0]
            for x in rows:
                self.assertEqual(set(timeout_row) - set(x), set(), "informed rows carry the timeout.json schema")
                self.assertIn("decisions_while_blocker_frozen", x)
                self.assertIn("reroutes_while_blocker_frozen", x)
                self.assertNotIn("wall_s", x)
                self.assertEqual(x["recovery"]["name"], "informed_timeout" if x["config"] == "informed flag"
                                 else "informed_timeout_left")
                self.assertEqual((x["recovery"]["replan"], x["recovery"]["abandon"]), (5, 15))
            self.assertEqual(doc["definition"]["grid"], [1, 8])
            png = d / "recovery_informed_smoke.png"
            self.assertEqual(png.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            before = path.read_bytes()
            r = run_sweep(["--smoke", "--only", "e", "--workers", "2"], d)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("[informed] 0 jobs to run (8 rows already on disk)", r.stdout)
            self.assertEqual(path.read_bytes(), before)

    # inject: the informed plot recomputes timeout rows (or skips the timeout band), pairs the delta against anything
    # but the stored timeout rows, or drops a config from either panel
    def test_plot_reads_stored_timeout_rows(self):
        import matplotlib
        matplotlib.use("Agg")
        from matplotlib.figure import Figure

        spec = importlib.util.spec_from_file_location("recovery_sweep_plot", SWEEP)
        rs = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rs)
        defn = rs.definition("informed", True)
        sentinel = {(g, s): 700.0 + 10 * g + s for g in (1, 8) for s in (0, 1)}  # impossible pick-rates
        base = [dict(point=g, config="timeout", seed=s, pick_rate=v) for (g, s), v in sentinel.items()]
        rows = [dict(point=g, config=c, seed=s, pick_rate=50.0 + s, stuck_busy_agent_steps=1, abandoned_tasks=0)
                for g in (1, 8) for c in ("informed flag", "informed left") for s in (0, 1)]
        seen_sum, seen_delta, captured = [], [], {}
        real_sum, real_delta, real_save = rs.ev.summarise, rs.ev.paired_delta, Figure.savefig

        def spy_sum(xs):
            seen_sum.append(list(xs))
            return real_sum(xs)

        def spy_delta(a, b):
            seen_delta.append((list(a), list(b)))
            return real_delta(a, b)

        def spy_save(fig, *a, **k):
            captured["labels"] = [ax.get_legend_handles_labels()[1] for ax in fig.axes]
            return real_save(fig, *a, **k)

        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "recovery").mkdir()
            (d / "recovery" / "timeout_smoke.json").write_text(json.dumps(dict(definition={}, rows=base)))
            rs.ev.summarise, rs.ev.paired_delta, Figure.savefig = spy_sum, spy_delta, spy_save
            try:
                rs.plot("informed", defn, rows, d / "out.png", d, True)
            finally:
                rs.ev.summarise, rs.ev.paired_delta, Figure.savefig = real_sum, real_delta, real_save
            self.assertTrue((d / "out.png").exists())
        for g in (1, 8):  # timeout band = the stored sentinel pick-rates, per rate
            self.assertIn([sentinel[(g, 0)], sentinel[(g, 1)]], seen_sum)
        for g in (1, 8):  # each config's delta is paired against the stored timeout rows of the same rate
            stored = [r for r in base if r["point"] == g]
            for c in ("informed flag", "informed left"):
                mine = [r for r in rows if r["point"] == g and r["config"] == c]
                self.assertIn((mine, stored), seen_delta)
        self.assertEqual(len(seen_delta), 4)
        self.assertIn("timeout", captured["labels"][0])
        for c in ("informed flag", "informed left"):
            self.assertIn(c, captured["labels"][0])
            self.assertIn(c, captured["labels"][1])

    # inject: add e to the default --only
    def test_default_only_stays_a_to_d(self):
        spec = importlib.util.spec_from_file_location("recovery_sweep_script", SWEEP)
        rs = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rs)
        self.assertEqual(rs.DEFAULT_ONLY, "a,b,c,d")
        self.assertEqual(rs.LETTERS["e"], "informed")
        self.assertEqual([lbl for lbl, _ in rs.configs("informed")], ["informed flag", "informed left"])


if __name__ == "__main__":
    unittest.main()

"""Tests for RuleRecovery and its registry entry (src/warehouse_rl/recovery.py) plus the abandon -> re-dispatch chain.
Envs run strictly one at a time (global np.random, Agent.counter). Each case names its red-demonstration in an
`# inject:` comment."""
import importlib.util
import sys
import unittest
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from tarware.heuristic import MissionType

from warehouse_rl import recovery as rc
from warehouse_rl.env import WarehouseEnv
from warehouse_rl.policy import CtaPolicy, StuckAwareCtaPolicy

_spec = importlib.util.spec_from_file_location("recovery_sweep_script", ROOT / "scripts" / "recovery_sweep.py")
rs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rs)

MEDIUM = "tarware-medium-8agvs-4pickers-globalobs-v1"
SMALL = "tarware-small-4agvs-2pickers-globalobs-v1"


def obs(c, path_len=5, clash=0):
    return dict(event_is_clash=float(clash), stuck_count=float(c), path_len=float(path_len))


def ladder(rule, path_len=5, clash=0, top=None):
    top = rule.abandon_after + 2 if top is None else top
    return [rule.decide(obs(c, path_len, clash)) for c in range(0, top + 1)]


def runs(seq):
    """Run-length encoding of an action sequence."""
    out = []
    for a in seq:
        if out and out[-1][0] == a:
            out[-1][1] += 1
        else:
            out.append([a, 1])
    return [tuple(x) for x in out]


class TestLadder(unittest.TestCase):
    # inject: swap the (v)/(vi) tests so back_off is tried before reroute, or shift any threshold by one
    def test_ladder_without_call_human(self):
        r = rc.RuleRecovery(3, 6, 15)
        self.assertEqual(runs(ladder(r)), [("wait", 3), ("back_off", 3), ("reroute", 9), ("abandon", 3)])
        seq = ladder(r)
        self.assertEqual((seq[2], seq[3], seq[5], seq[6], seq[14], seq[15], seq[17]),
                         ("wait", "back_off", "back_off", "reroute", "reroute", "abandon", "abandon"))

    # inject: drop the call_human rung, or give it precedence over abandon, or ignore path_len for it
    def test_ladder_with_call_human(self):
        r = rc.RuleRecovery(3, 6, 15, call_human_after=14)
        self.assertEqual(runs(ladder(r)),
                         [("wait", 3), ("back_off", 3), ("reroute", 8), ("call_human", 1), ("abandon", 3)])
        r2 = rc.RuleRecovery(2, 4, 12, call_human_after=7)
        self.assertEqual(runs(ladder(r2)), [("wait", 2), ("back_off", 2), ("reroute", 3), ("call_human", 5),
                                            ("abandon", 3)])

    # inject: evaluate the clash test after the abandon test, or return "wait" for clash at c < back_off_after
    def test_clash_reroutes_at_any_count(self):
        for r in (rc.RuleRecovery(3, 6, 15), rc.RuleRecovery(3, 6, 15, call_human_after=14)):
            self.assertEqual(set(ladder(r, clash=1)), {"reroute"})  # includes c >= abandon_after
            self.assertEqual(set(ladder(r, path_len=0, clash=1)), {"reroute"})

    # inject: drop the path_len == 0 guard
    def test_empty_path_waits_below_abandon_without_human(self):
        r = rc.RuleRecovery(3, 6, 15)
        self.assertEqual(runs(ladder(r, path_len=0)), [("wait", 15), ("abandon", 3)])

    # inject: put the path_len == 0 test before the call_human test
    def test_empty_path_still_calls_human(self):
        r = rc.RuleRecovery(3, 6, 15, call_human_after=14)
        self.assertEqual(runs(ladder(r, path_len=0)), [("wait", 14), ("call_human", 1), ("abandon", 3)])

    # inject: cache the last answer on self, or make decide depend on call order
    def test_pure_function_of_obs(self):
        r = rc.RuleRecovery(3, 6, 15, call_human_after=14)
        first = ladder(r)
        self.assertEqual([r.decide(obs(c)) for c in reversed(range(18))][::-1], first)
        self.assertEqual(r.decide(obs(7)), r.decide(obs(7)))
        self.assertEqual(vars(r), vars(rc.RuleRecovery(3, 6, 15, call_human_after=14)))


class TestValidationAndRegistry(unittest.TestCase):
    # inject: relax any comparison to <=, or accept bool/float thresholds
    def test_bad_thresholds_raise(self):
        bad = [(0, 2, 3), (3, 3, 6), (4, 3, 6), (1, 5, 5), (1, 5, 4), (True, 3, 6), (1, 2.0, 6), (1, "2", 6), (-1, 2, 3),
               (1, None, 3)]
        for args in bad:
            with self.assertRaises(ValueError, msg=str(args)):
                rc.RuleRecovery(*args)

    # inject: allow call_human_after at reroute_after or abandon_after, or a bool/float value
    def test_call_human_after_must_sit_strictly_between(self):
        for h in (6, 5, 15, 16, 1.5, True, "9"):
            with self.assertRaises(ValueError, msg=str(h)):
                rc.RuleRecovery(3, 6, 15, call_human_after=h)
        rc.RuleRecovery(3, 6, 15, call_human_after=7)
        rc.RuleRecovery(3, 6, 15, call_human_after=14)
        with self.assertRaises(ValueError):  # A == R + 1 leaves no room for a human rung
            rc.RuleRecovery(3, 4, 5, call_human_after=4)

    # inject: let normalise_recovery keep call_human_after absent, or change the sha input
    def test_rule_resolves_with_explicit_null_and_stable_tag(self):
        base = dict(name="rule", back_off_after=3, reroute_after=6, abandon_after=15)
        tag_a, cfg_a = rc.resolve_recovery(__import__("json").dumps(base))
        tag_b, cfg_b = rc.resolve_recovery(__import__("json").dumps(dict(base, call_human_after=None,
                                                                          call_human_cost=60)))
        self.assertEqual(cfg_a, dict(base, call_human_after=None, call_human_cost=60))
        self.assertEqual((tag_a, cfg_a), (tag_b, cfg_b))
        self.assertEqual(tag_a, "rec-83eb95dc54")  # pinned literal
        tag_c, cfg_c = rc.resolve_recovery(
            '{"name": "rule", "back_off_after": 3, "reroute_after": 6, "abandon_after": 15, '
            '"call_human_after": 14, "call_human_cost": 5}')
        self.assertEqual((tag_c, cfg_c["call_human_after"], cfg_c["call_human_cost"]), ("rec-5e88cc57cd", 14, 5))
        pol = rc.make_recovery(cfg_c)
        self.assertIsInstance(pol, rc.RuleRecovery)
        self.assertEqual((pol.back_off_after, pol.reroute_after, pol.abandon_after, pol.call_human_after), (3, 6, 15, 14))

    # inject: ignore unknown keys / missing keys / bad cost in the rule branch
    def test_rule_registry_fails_closed(self):
        ok = dict(name="rule", back_off_after=3, reroute_after=6, abandon_after=15)
        rc.normalise_recovery(ok)
        for bad in (dict(ok, replan=5), dict(ok, call_human_cost=-1), dict(ok, call_human_cost=True),
                    dict(ok, call_human_after=15), dict(ok, back_off_after=6),
                    {k: v for k, v in ok.items() if k != "reroute_after"},
                    {k: v for k, v in ok.items() if k != "abandon_after"},
                    {k: v for k, v in ok.items() if k != "back_off_after"},
                    dict(name="rule")):
            with self.assertRaises(ValueError, msg=str(bad)):
                rc.normalise_recovery(bad)
        with self.assertRaises(ValueError):
            rc.resolve_recovery('{"name": "rule", "back_off_after": 3}')
        self.assertEqual(rc.resolve_recovery("timeout")[0], "timeout")
        with self.assertRaises(ValueError):
            rc.resolve_recovery("rule")  # presets stay ['timeout'] only

    # inject: change the timeout/tuned normalisation (key set, default cost, tag input)
    def test_timeout_and_tuned_unchanged_at_73fd9ac(self):
        self.assertEqual(rc.resolve_recovery("timeout"), ("timeout", {"name": "timeout", "call_human_cost": 60}))
        self.assertEqual(rc.resolve_recovery('{"name":"timeout"}'),
                         ("rec-edd5432d8d", {"name": "timeout", "call_human_cost": 60}))
        self.assertEqual(rc.resolve_recovery('{"name":"tuned_timeout","replan":5,"abandon":15}'),
                         ("rec-78a8a91967", {"name": "tuned_timeout", "replan": 5, "abandon": 15,
                                             "call_human_cost": 60}))
        self.assertEqual(rc.resolve_recovery('{"name":"tuned_timeout","replan":3,"abandon":10,"call_human_cost":5}')[0],
                         "rec-0fc956f7ab")


# a pinned real abandon: small map, blocked cells 300/h, rule (2, 3, 6), seed 4; AGV 3 loses a PICKING order at step 166
PIN = dict(env=SMALL, seed=4, steps=500, rule=(2, 3, 6), disturb={"blocked_cell": {"rate_per_hour": 300,
                                                                                    "duration": [20, 60]}})


def find_pinned_abandon():
    """Step the real env + StuckAwareCtaPolicy until the hook's abandon leaves a non-carrying AGV with a PICKING
    mission. Returns (env, obs, info, policy, abandoner, item, step, releasee) just BEFORE the next act().

    On the loaded map (PIN: small) no AGV is idle at that moment (every one holds an order), so the re-dispatch could not
    show a new owner. One OTHER non-carrying AGV (the releasee, waiting at its own pick location) is therefore released
    by hand: busy=False, path cleared, its order dropped from the policy's books, and the other unassigned requests are
    removed from the queue so the abandoned item is the first one dispatched. The abandoner itself is untouched: its
    busy=False is the hook's doing."""
    cfg = rc.normalise_recovery(dict(name="rule", back_off_after=PIN["rule"][0], reroute_after=PIN["rule"][1],
                                     abandon_after=PIN["rule"][2]))
    env = WarehouseEnv(PIN["env"], max_steps=PIN["steps"], disturb=PIN["disturb"], recovery=cfg)
    o, info = env.reset(seed=PIN["seed"])
    pol = StuckAwareCtaPolicy()
    pol.reset(env)
    for t in range(PIN["steps"]):
        was_busy = {a: a.busy for a in pol.agvs}
        acts = pol.act(o, info["action_mask"], info)
        o, _, _, _, info = env.step(acts)
        if info["recovery_abandon"] <= 0:
            continue
        for a in pol.agvs:
            m = pol.assigned_agvs.get(a)
            if not (m is not None and m.mission_type == MissionType.PICKING and not a.carrying_shelf and was_busy[a]
                    and not a.busy and (a.x, a.y) != (m.location_x, m.location_y)):
                continue
            others = [b for b in pol.agvs if b is not a and not b.carrying_shelf and b not in pol._frozen_agvs()]
            if not others:
                continue
            item = pol.assigned_items[a]
            rel = others[0]
            rel.busy, rel.path = False, []
            pol.assigned_agvs.pop(rel, None)
            pol.assigned_items.pop(rel, None)
            pol._prev_busy[rel] = False
            keep = set(pol.assigned_items.values()) | {item}  # no other unassigned order may outrank the abandoned one
            env.env.request_queue = [i for i in env.env.request_queue if i.id in keep]
            return env, o, info, pol, a, item, t, rel
    env.close()
    return None


class TestAbandonRedispatch(unittest.TestCase):
    # inject: StuckAwareCtaPolicy._begin_act returns () without popping the abandoned mission (becomes CtaPolicy)
    def test_real_hook_abandon_reassigns_to_other_agv_but_cta_keeps_it(self):
        found = find_pinned_abandon()
        self.assertIsNotNone(found, "non-vacuity: no real PICKING abandon found on the pinned seed")
        env, o, info, sa, abandoner, item, t, rel = found
        try:
            self.assertFalse(abandoner.busy)  # the hook's abandon set busy=False
            self.assertIn(abandoner, sa.assigned_agvs)  # the policy has not noticed yet
            snap = (OrderedDict(sa.assigned_agvs), OrderedDict(sa.assigned_items), OrderedDict(sa.assigned_pickers),
                    sa.timestep)
            cta = CtaPolicy()
            cta.reset(env)
            cta.assigned_agvs, cta.assigned_items, cta.assigned_pickers, cta.timestep = (
                OrderedDict(snap[0]), OrderedDict(snap[1]), OrderedDict(snap[2]), snap[3])
            # discriminator first (act() only reads the env): CTA leaves the order on the abandoner
            cta.act(o, info["action_mask"], info)
            self.assertIn(abandoner, cta.assigned_agvs)
            self.assertEqual(cta.assigned_items.get(abandoner), item)
            # stuck-aware: the very next act() hands the item to a different AGV and frees the abandoner
            sa.act(o, info["action_mask"], info)
            owners = [a for a, i in sa.assigned_items.items() if i == item]
            self.assertEqual(len(owners), 1)
            self.assertIsNot(owners[0], abandoner)
            self.assertIs(owners[0], rel)  # the only eligible AGV
            self.assertNotIn(abandoner, sa.assigned_agvs)
            self.assertNotIn(abandoner, sa.assigned_items)
            self.assertEqual(sa.assigned_agvs[owners[0]].mission_type, MissionType.PICKING)
        finally:
            env.close()


class TestTunedEqualsTimeout(unittest.TestCase):
    # inject: make TimeoutRecovery differ from TunedTimeoutRecovery(5, 15) (e.g. abandon 14), or add per-config state
    def test_tuned_5_15_rows_equal_timeout_rows_field_by_field(self):
        rate, seed = 8, 0
        t_label, t_cfg = rs.configs("timeout")[0]
        u_cfg = rc.normalise_recovery({"name": "tuned_timeout", "replan": 5, "abandon": 15})
        _, row_t = rs._job(("timeout", rate, t_label, t_cfg, seed))
        _, row_u = rs._job(("tuned_timeout", rate, "tuned replan 5 abandon 15", u_cfg, seed))
        self.assertGreater(row_t["recovery_abandon"], 0, "non-vacuity: no abandons at this (rate, seed)")
        drop = {"recovery", "config"}
        self.assertEqual({k: v for k, v in row_t.items() if k not in drop},
                         {k: v for k, v in row_u.items() if k not in drop})
        self.assertNotEqual(row_t["recovery"]["name"], row_u["recovery"]["name"])
        self.assertEqual(set(row_t), set(row_u))
        # discriminator: _job must run the config it is given; another tuned point gives a different row
        o_cfg = rc.normalise_recovery({"name": "tuned_timeout", "replan": 3, "abandon": 10})
        _, row_o = rs._job(("tuned_timeout", rate, "tuned replan 3 abandon 10", o_cfg, seed))
        self.assertNotEqual({k: v for k, v in row_t.items() if k not in drop},
                            {k: v for k, v in row_o.items() if k not in drop})


if __name__ == "__main__":
    unittest.main()

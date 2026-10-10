"""Tests for StuckAwareCtaPolicy (src/warehouse_rl/policy.py) on constructed DisturbedWarehouse states. Envs run
strictly one at a time (global np.random, Agent.counter). Each case names its injection target in a comment."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tarware.heuristic import MissionType

from warehouse_rl.env import WarehouseEnv
from warehouse_rl.policy import CtaPolicy, StuckAwareCtaPolicy

SMALL = "tarware-small-4agvs-2pickers-globalobs-v1"
QUIET = {"breakdown": {"rate_per_hour": 0, "duration": [1, 1]}}  # layer on, nothing scheduled
HEAVY = {"breakdown": {"rate_per_hour": 20, "duration": [10, 30]}}


class Fixture:
    """Fresh env at reset (t = 0, all robots idle), one queued request unless keep_queue."""

    def __init__(self, policy_cls, disturb=QUIET, keep_queue=False, seed=0):
        self.env = WarehouseEnv(SMALL, max_steps=200, disturb=disturb)
        self.obs, self.info = self.env.reset(seed=seed)
        self.e = self.env.env
        if not keep_queue:
            self.e.request_queue = self.e.request_queue[:1]
        self.pol = policy_cls()
        self.pol.reset(self.env)

    def act(self):
        return self.pol.act(self.obs, self.info["action_mask"], self.info)

    def assignee(self):
        item = self.e.request_queue[0]
        owners = [a for a, i in self.pol.assigned_items.items() if i == item.id]
        return owners[0] if owners else None

    def close(self):
        self.env.close()


def closest_agv(policy_cls):
    f = Fixture(policy_cls)
    try:
        f.act()
        return f.assignee().id
    finally:
        f.close()


class TestFrozenFilter(unittest.TestCase):
    # (i) inject: remove the frozen exclusion in StuckAwareCtaPolicy._begin_act
    def test_closest_frozen_agv_is_skipped(self):
        target = closest_agv(CtaPolicy)
        for cls, expect_frozen_gets_it in ((CtaPolicy, True), (StuckAwareCtaPolicy, False)):
            f = Fixture(cls)
            try:
                f.e.frozen_schedule[target - 1, f.e._t] = True
                actions = f.act()
                owner = f.assignee()
                self.assertIsNotNone(owner)
                self.assertEqual(owner.id == target, expect_frozen_gets_it, cls.__name__)
                if not expect_frozen_gets_it:
                    frozen = f.e.agents[target - 1]
                    self.assertEqual(actions[target - 1], 0)
                    self.assertNotIn(frozen, f.pol.assigned_agvs)
            finally:
                f.close()

    # no look-ahead: a freeze at column t + 1 only does not exclude the AGV
    def test_only_current_column_is_read(self):  # inject: read frozen_schedule[:, _t + 1]
        target = closest_agv(CtaPolicy)
        f = Fixture(StuckAwareCtaPolicy)
        try:
            f.e.frozen_schedule[target - 1, f.e._t + 1] = True
            f.act()
            self.assertEqual(f.assignee().id, target)
        finally:
            f.close()

    # plain Warehouse (no layer): nothing is frozen, the policy still runs
    def test_no_layer_nothing_frozen(self):  # inject: drop the getattr fallback in _frozen_agvs
        env = WarehouseEnv(SMALL, max_steps=50)
        obs, info = env.reset(seed=0)
        pol = StuckAwareCtaPolicy()
        pol.reset(env)
        self.assertEqual(pol._frozen_agvs(), set())
        for _ in range(20):
            obs, _, _, _, info = env.step(pol.act(obs, info["action_mask"], info))
        env.close()

    # (ii) inject: exclude idle AGVs with StuckCounter.count > 15
    def test_stale_stuck_count_does_not_exclude(self):
        target = closest_agv(CtaPolicy)
        f = Fixture(StuckAwareCtaPolicy)
        try:
            f.e.stuck_counters[target - 1].count = 20
            f.act()
            self.assertEqual(f.assignee().id, target)
        finally:
            f.close()

    # property over a real heavy-breakdown run: no AGV that is frozen at the layer's step gets a NEW assignment
    # inject: remove the frozen exclusion
    def test_no_new_assignment_to_frozen_agv_in_a_run(self):
        f = Fixture(StuckAwareCtaPolicy, disturb=HEAVY, keep_queue=True, seed=3)
        try:
            frozen_seen = 0
            for _ in range(200):
                before = set(f.pol.assigned_agvs)
                actions = f.act()
                frozen = f.e.frozen_now()
                new = set(f.pol.assigned_agvs) - before
                frozen_seen += int(frozen[:f.e.num_agvs].sum())
                for a in new:
                    self.assertFalse(frozen[a.id - 1], f"t={f.e._t}: new mission for frozen agv {a.id}")
                f.obs, _, _, _, f.info = f.env.step(actions)
            self.assertGreater(frozen_seen, 0)  # non-vacuous
        finally:
            f.close()


class TestAbandonment(unittest.TestCase):
    def _abandon(self, cls, others_busy=False, freeze_others=False):
        """Assign the lone request, then make its AGV look abandoned (busy at the previous call, idle now)."""
        f = Fixture(cls)
        f.act()
        x = f.assignee()
        self.assertEqual(f.pol.assigned_agvs[x].mission_type, MissionType.PICKING)
        if cls is StuckAwareCtaPolicy:
            f.pol._prev_busy[x] = True
        x.busy = False
        for a in f.pol.agvs:
            if a is not x:
                a.busy = others_busy
        if freeze_others:
            for a in f.pol.agvs:
                if a is not x:
                    f.e.frozen_schedule[a.id - 1, f.e._t] = True
        return f, x

    # (iii) inject: drop the assigned_agvs/assigned_items pop in _begin_act
    def test_item_goes_to_another_agv_in_same_call(self):
        f, x = self._abandon(StuckAwareCtaPolicy)
        try:
            actions = f.act()
            new_owner = f.assignee()
            self.assertIsNotNone(new_owner)
            self.assertIsNot(new_owner, x)
            self.assertNotIn(x, f.pol.assigned_agvs)
            self.assertEqual(actions[x.id - 1], 0)
        finally:
            f.close()

    def test_plain_cta_reissues_to_same_agv(self):  # discriminates: CtaPolicy keeps the dropped mission
        f, x = self._abandon(CtaPolicy)
        try:
            actions = f.act()
            self.assertIs(f.assignee(), x)
            self.assertEqual(actions[x.id - 1], f.pol.assigned_agvs[x].location_id)
        finally:
            f.close()

    # (iii) inject: let the abandoner stay a candidate in the same call (drop it from the returned exclusion set)
    def test_only_idle_agv_is_abandoner_item_stays_unassigned_then_returns(self):
        f, x = self._abandon(StuckAwareCtaPolicy, others_busy=True)
        try:
            actions = f.act()
            self.assertIsNone(f.assignee())
            self.assertNotIn(x, f.pol.assigned_agvs)
            self.assertEqual(actions[x.id - 1], 0)
            self.assertEqual(len(f.e.request_queue), 1)  # still queued
            f.act()  # next call: eligible again
            self.assertIs(f.assignee(), x)
        finally:
            f.close()

    # inject: drop the frozen filter (only the abandoner would remain excluded)
    def test_frozen_others_never_get_the_abandoned_item(self):
        f, x = self._abandon(StuckAwareCtaPolicy, freeze_others=True)
        try:
            actions = f.act()
            self.assertIsNone(f.assignee())
            self.assertEqual(sum(1 for a in actions[:f.e.num_agvs] if a), 0)
        finally:
            f.close()

    # never busy (the find_path == [] shape at W:366): idle now but not busy at the previous call, mission kept
    def test_never_busy_mission_is_not_an_abandonment(self):  # inject: drop the _prev_busy condition in _begin_act
        f = Fixture(StuckAwareCtaPolicy)
        try:
            f.act()  # assigns; no env.step, so the AGV is still not busy at the next call
            x = f.assignee()
            self.assertFalse(x.busy)
            actions = f.act()
            self.assertIs(f.assignee(), x)
            self.assertEqual(actions[x.id - 1], f.pol.assigned_agvs[x].location_id)
        finally:
            f.close()

    # the drop comes from the vendor's own stuck timeout (resolve_stuck_agents, W:509-513), not a hand-set busy flag.
    # Real PICKING-not-carrying drops are rare (none in seeds 0-19, small and medium, heavy breakdown and none), so
    # the counter is primed; everything after that is the env's code path. inject: drop the pop in _begin_act
    def test_real_stuck_timeout_drop_is_redispatched(self):
        f = Fixture(StuckAwareCtaPolicy)
        try:
            f.obs, _, _, _, f.info = f.env.step(f.act())
            x = f.assignee()
            self.assertTrue(x.busy)
            for _ in range(10):
                c = f.e.stuck_counters[x.id - 1]
                c.position, c.count = (x.x, x.y), 15  # next vendor update -> 16 > 15: task dropped
                f.obs, _, _, _, f.info = f.env.step(f.act())  # act() records x busy before the drop
                if not x.busy:
                    break
            self.assertFalse(x.busy)
            self.assertGreaterEqual(f.info["abandoned_tasks"], 1)
            self.assertFalse(x.carrying_shelf)
            self.assertEqual(f.pol.assigned_agvs[x].mission_type, MissionType.PICKING)
            f.act()
            new_owner = f.assignee()
            self.assertIsNotNone(new_owner)
            self.assertIsNot(new_owner, x)
            self.assertNotIn(x, f.pol.assigned_agvs)
        finally:
            f.close()

    # idle at its own mission location (e.g. a stuck timeout while waiting for a picker): not an abandonment
    def test_at_location_is_not_an_abandonment(self):  # inject: drop the not-at-location check in _begin_act
        f, x = self._abandon(StuckAwareCtaPolicy)
        try:
            m = f.pol.assigned_agvs[x]
            x.x, x.y = m.location_x, m.location_y
            f.act()
            self.assertIn(x, f.pol.assigned_agvs)
        finally:
            f.close()

    # carrying a shelf: not an abandonment, the mission survives (CTA behaviour)
    def test_carrying_agv_is_not_an_abandonment(self):  # inject: drop the carrying_shelf check
        f = Fixture(StuckAwareCtaPolicy)
        try:
            f.act()
            x = f.assignee()
            f.pol._prev_busy[x] = True
            x.busy = False
            x.carrying_shelf = f.e.request_queue[0]
            f.act()
            self.assertIn(x, f.pol.assigned_agvs)
        finally:
            f.close()


class TestCommonRandomNumbers(unittest.TestCase):
    # (iv) inject: make the schedule depend on the policy or draw it lazily from global np.random
    def test_applied_frozen_identical_across_policies(self):
        traces = {}
        for cls in (CtaPolicy, StuckAwareCtaPolicy):
            f = Fixture(cls, disturb=HEAVY, keep_queue=True, seed=5)
            try:
                for _ in range(150):
                    f.obs, _, _, _, f.info = f.env.step(f.act())
                traces[cls] = [m.copy() for m in f.e.applied_frozen]
            finally:
                f.close()
        a, b = traces[CtaPolicy], traces[StuckAwareCtaPolicy]
        self.assertEqual(len(a), 150)
        self.assertTrue(all((x == y).all() for x, y in zip(a, b)))
        self.assertTrue(any(x.any() for x in a))


if __name__ == "__main__":
    unittest.main()

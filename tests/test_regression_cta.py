import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import gymnasium as gym
import numpy as np
import tarware  # noqa: F401
from tarware.heuristic import Mission, MissionType
from tarware.heuristic import heuristic_episode

from warehouse_rl.env import WarehouseEnv
from warehouse_rl.policy import CtaPolicy

ENV_ID = "tarware-small-4agvs-2pickers-globalobs-v1"
STEPS = 500
SEEDS = range(10)
# Operator observed on 2026-10-10 (informational only, not the oracle): [24, 23, 19, 21, 20, 21, 24, 18, 20, 22]


def reference_run(seed):
    env = gym.make(ENV_ID).unwrapped
    recorded = []
    orig_step = env.step

    def recording_step(actions):
        recorded.append(list(actions))
        return orig_step(actions)

    env.step = recording_step
    infos, _, _ = heuristic_episode(env, False, seed)
    assert len(infos) == STEPS
    return recorded, sum(int(i["shelf_deliveries"]) for i in infos)


def policy_run(seed):
    env = WarehouseEnv(ENV_ID, max_steps=STEPS, normalise_coordinates=True, agent_features=True, global_reward=True)
    policy = CtaPolicy()
    obs, info = env.reset(seed=seed)
    policy.reset(env)
    recorded, deliveries = [], 0
    for _ in range(STEPS):
        actions = policy.act(obs, info["action_mask"], info)
        recorded.append(list(actions))
        obs, _, _, _, info = env.step(actions)
        deliveries += int(info["shelf_deliveries"])
    return recorded, deliveries


class TestRegressionCta(unittest.TestCase):
    """The port must reproduce tarware's heuristic_episode action-for-action.

    NOTE: this regression test is vacuous for the guards (they only change behaviour where the vendor loop would
    raise or pick an unreachable target, which does not occur on these seeds). The guards have their own tests below.
    """

    def test_actions_and_deliveries_match_heuristic(self):
        ref_deliveries, new_deliveries = [], []
        for seed in SEEDS:
            ref_actions, ref_d = reference_run(seed)  # sequential, never interleaved
            new_actions, new_d = policy_run(seed)
            self.assertEqual(len(ref_actions), STEPS, seed)
            self.assertEqual(ref_actions, new_actions, f"seed {seed}: per-step actions differ")
            ref_deliveries.append(ref_d)
            new_deliveries.append(new_d)
        self.assertEqual(ref_deliveries, new_deliveries)
        for d in new_deliveries:
            self.assertGreater(d, 0)


class TestGuards(unittest.TestCase):
    def setUp(self):
        self.env = WarehouseEnv(ENV_ID, max_steps=STEPS)
        self.env.reset(seed=0)
        self.policy = CtaPolicy()
        self.policy.reset(self.env)
        self.inner = self.env.env
        self.agv = self.policy.agvs[0]

    def _prime_carrying_agv(self, mission_type):
        """Empty request queue; AGV0 stands at its mission target, idle, carrying a shelf."""
        inner = self.inner
        inner.request_queue = []
        agv = self.agv
        agv.busy = False
        agv.carrying_shelf = inner.shelfs[0]
        gx, gy = inner.goals[0]
        mission = Mission(mission_type, 1, agv.x, agv.y, 0)
        self.policy.assigned_agvs[agv] = mission
        self.policy.assigned_items[agv] = inner.shelfs[0].id
        return mission

    def test_picker_zone_miss_skips_picker_assignment(self):
        self.policy.picker_sections = [[] for _ in self.policy.picker_sections]
        actions = self.policy.act(None, None, None)  # without the guard: ValueError from list.index(True)
        self.assertEqual(len(self.policy.assigned_pickers), 0)
        self.assertEqual(len(actions), self.env.num_agents)

    def test_empty_slot_list_keeps_delivering_mission(self):
        self._prime_carrying_agv(MissionType.DELIVERING)
        self.inner.get_empty_shelf_information = lambda: np.zeros(len(self.inner.shelfs))
        self.policy.act(None, None, None)  # without the guard: ValueError from argmin of an empty list
        self.assertEqual(self.policy.assigned_agvs[self.agv].mission_type, MissionType.DELIVERING)

    def test_unreachable_item_not_assigned_to_zero_length_path(self):
        agv0 = self.agv
        inner = self.inner
        inner.find_path = lambda start, goal, agent, care_for_agents=True: [] if agent is agv0 else [(0, 0)] * 5
        self.policy.act(None, None, None)  # without the guard agv0 wins argmin with length 0
        self.assertNotIn(agv0, self.policy.assigned_agvs)
        self.assertGreater(len(self.policy.assigned_agvs), 0)

    def test_unreachable_goal_not_selected(self):
        mission = self._prime_carrying_agv(MissionType.PICKING)
        mission.at_location = True
        inner = self.inner
        gx, gy = inner.goals[0]  # stored (x, y); find_path takes (y, x)
        inner.find_path = lambda start, goal, agent, care_for_agents=True: [] if tuple(goal) == (gy, gx) else [(0, 0)] * 3
        self.policy.act(None, None, None)
        new = self.policy.assigned_agvs[self.agv]
        self.assertEqual(new.mission_type, MissionType.DELIVERING)
        self.assertNotEqual((new.location_x, new.location_y), (gx, gy))

    def test_unreachable_empty_slot_not_selected(self):
        self._prime_carrying_agv(MissionType.DELIVERING)
        inner = self.inner
        inner.get_empty_shelf_information = lambda: np.ones(len(inner.shelfs))
        last_id = max(inner.action_id_to_coords_map)
        reachable = inner.action_id_to_coords_map[last_id]
        inner.find_path = lambda start, goal, agent, care_for_agents=True: [(0, 0)] * 4 if tuple(goal) == tuple(reachable) else []
        self.policy.act(None, None, None)  # without the guard the first zero-length (unreachable) slot wins
        new = self.policy.assigned_agvs[self.agv]
        self.assertEqual(new.mission_type, MissionType.RETURNING)
        self.assertEqual(new.location_id, last_id)


if __name__ == "__main__":
    unittest.main()

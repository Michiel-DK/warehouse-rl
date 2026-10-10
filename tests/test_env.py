import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np

from warehouse_rl.env import WarehouseEnv
from warehouse_rl.policy import CtaPolicy, RandomPolicy

ENV_ID = "tarware-small-4agvs-2pickers-globalobs-v1"


def cta_rollout(env, seed=0, steps=60):
    """Generator: yields (obs, info) after reset and after every step of a CTA rollout, with the env state live
    (consume it step by step; do not collect it into a list). Envs run strictly one at a time."""
    policy = CtaPolicy()
    obs, info = env.reset(seed=seed)
    policy.reset(env)
    yield obs, info
    for _ in range(steps):
        obs, _, _, _, info = env.step(policy.act(obs, info["action_mask"], info))
        yield obs, info


def own_position_offset(agent):
    return 3 if agent.type.name == "AGV" else 0


class TestContract(unittest.TestCase):
    def test_reset_returns_obs_and_mask(self):
        env = WarehouseEnv(ENV_ID)
        res = env.reset(seed=0)
        self.assertEqual(len(res), 2)
        obs, info = res
        self.assertEqual(len(obs), env.num_agents)
        self.assertIn("action_mask", info)

    def test_step_types_and_truncation(self):
        env = WarehouseEnv(ENV_ID, max_steps=50)
        env.reset(seed=0)
        for t in range(1, 51):
            res = env.step([0] * env.num_agents)
            self.assertEqual(len(res), 5)
            obs, rewards, terminated, truncated, info = res
            self.assertIsInstance(rewards, list)
            self.assertEqual(len(rewards), env.num_agents)
            for r in rewards:
                self.assertIs(type(r), float)
            self.assertIs(type(terminated), bool)
            self.assertIs(type(truncated), bool)
            self.assertFalse(terminated)
            self.assertEqual(truncated, t == 50, t)
            self.assertIn("global_reward", info)

    def test_terminated_and_truncated_are_not_the_same_object(self):
        # False/True singletons would alias when equal; at the final step they differ (False vs True).
        env = WarehouseEnv(ENV_ID, max_steps=2)
        env.reset(seed=0)
        env.step([0] * env.num_agents)
        _, _, terminated, truncated, _ = env.step([0] * env.num_agents)
        self.assertIsNot(terminated, truncated)

    def test_global_reward_is_team_sum(self):
        env = WarehouseEnv(ENV_ID, global_reward=True)
        env.reset(seed=0)
        _, rewards, _, _, info = env.step([0] * env.num_agents)
        self.assertEqual(len(set(rewards)), 1)
        self.assertAlmostEqual(rewards[0], info["global_reward"])


class TestMasks(unittest.TestCase):
    def test_mask_shape_dtype_noop_and_oracle_equality(self):
        env = WarehouseEnv(ENV_ID)
        for obs, info in cta_rollout(env):
            mask = info["action_mask"]
            self.assertEqual(mask.dtype, np.bool_)
            self.assertEqual(mask.shape, (env.num_agents, env.env.action_size))
            self.assertTrue(mask[:, 0].all())
            oracle = env.env.compute_valid_action_masks().astype(bool)
            self.assertTrue(np.array_equal(mask, oracle))

    def test_mask_computation_is_pure(self):
        env = WarehouseEnv(ENV_ID)
        for _, last_info in cta_rollout(env, steps=30):
            pass
        e = env.env

        def snapshot():
            return (
                [s.id for s in e.request_queue],
                [(a.x, a.y) for a in e.agents],
                [a.target for a in e.agents],
                e.grid.copy(),
            )

        before = snapshot()
        m1 = env.compute_action_masks()
        m2 = env.compute_action_masks()
        after = snapshot()
        self.assertTrue(np.array_equal(m1, m2))
        self.assertTrue(np.array_equal(m1, last_info["action_mask"]))
        self.assertEqual(before[:3], after[:3])
        self.assertTrue(np.array_equal(before[3], after[3]))


class TestObservation(unittest.TestCase):
    def test_normalised_own_position_and_range(self):
        env = WarehouseEnv(ENV_ID, normalise_coordinates=True, agent_features=True)
        H, W = env.env.grid_size
        self.assertEqual((H, W), (25, 14))
        for obs, _ in cta_rollout(env):
            for agent, o in zip(env.env.agents, obs):
                self.assertEqual(o.dtype, np.float32)
                k = own_position_offset(agent)
                expected = np.array([agent.y / (H - 1), agent.x / (W - 1)]).astype(o.dtype)
                self.assertTrue(np.array_equal(o[k:k + 2], expected), (o[k:k + 2], expected))
                self.assertTrue(((o >= 0) & (o <= 1)).all())

    def test_unnormalised_has_value_above_one(self):
        env = WarehouseEnv(ENV_ID, normalise_coordinates=False)
        top = max(float(o.max()) for obs, _ in cta_rollout(env, steps=20) for o in obs)
        self.assertGreater(top, 1.0)

    def test_obs_length_matches_observation_space(self):
        for features in (True, False):
            env = WarehouseEnv(ENV_ID, agent_features=features)
            obs, _ = env.reset(seed=0)
            for o, space in zip(obs, env.observation_space):
                self.assertEqual(o.shape, space.shape)
            obs, *_ = env.step([0] * env.num_agents)
            for o, space in zip(obs, env.observation_space):
                self.assertEqual(o.shape, space.shape)
        base = WarehouseEnv(ENV_ID, agent_features=False).observation_space[0].shape[0]
        wide = WarehouseEnv(ENV_ID, agent_features=True).observation_space[0].shape[0]
        self.assertEqual(wide - base, 3 * 6)


class TestRngIsolation(unittest.TestCase):
    def _run(self, draw):
        env = WarehouseEnv(ENV_ID)
        policy = RandomPolicy(seed=123)
        obs, info = env.reset(seed=4)
        trace = []
        for _ in range(60):
            if draw:
                before = np.random.get_state()
                env.rng.random(7)
                env.rng.integers(0, 100, size=3)
                after = np.random.get_state()
                self.assertEqual(before[0], after[0])
                self.assertTrue(np.array_equal(before[1], after[1]))
                self.assertEqual(before[2:], after[2:])
            mask = info["action_mask"]
            actions = policy.act(obs, mask, info)
            for i, a in enumerate(actions):
                self.assertTrue(mask[i, a])
            obs, _, _, _, info = env.step(actions)
            trace.append((
                [(a.x, a.y) for a in env.env.agents],
                [s.id for s in env.env.request_queue],
            ))
        return trace

    def test_wrapper_draws_do_not_perturb_env(self):
        self.assertEqual(self._run(draw=True), self._run(draw=False))


if __name__ == "__main__":
    unittest.main()

"""Thin gymnasium wrapper around one TA-RWARE Warehouse. No change to the env dynamics.

One env per process: Agent.counter and Shelf.counter are class attributes.
"""
import gymnasium as gym
import numpy as np
from gymnasium import spaces

import tarware  # noqa: F401  (registers the env ids)

from warehouse_rl.disturb import DisturbedWarehouse

FIXING_CLASH_TIME = 4  # vendor warehouse._FIXING_CLASH_TIME
STUCK_CAP = 15
N_AGENT_FEATURES = 3
_RNG_TAG = 0x57524C  # fixed tag mixed into the wrapper SeedSequence


class WarehouseEnv(gym.Env):
    def __init__(
        self,
        env_id="tarware-small-4agvs-2pickers-globalobs-v1",
        max_steps=500,
        normalise_coordinates=True,
        agent_features=False,
        global_reward=False,
        disturb=None,
        assign_care_for_agents=False,
    ):
        # disturb=None: the S1 path, untouched. disturb=dict: DisturbedWarehouse (see disturb.py); {} = no disturbance.
        # Preset names / JSON strings are resolved by the caller (disturb.resolve_disturb), not here.
        if assign_care_for_agents and disturb is None:
            raise ValueError("assign_care_for_agents=True needs a disturb dict (the layer owns the toggle)")
        if disturb is None:
            self.env = gym.make(env_id, max_steps=max_steps).unwrapped
        elif isinstance(disturb, dict):
            kwargs = dict(gym.spec(env_id).kwargs)
            kwargs["max_steps"] = max_steps
            self.env = DisturbedWarehouse(disturb=disturb, assign_care_for_agents=assign_care_for_agents, **kwargs)
        else:
            raise ValueError(f"disturb must be None or a dict, got {type(disturb).__name__}")
        self.disturb = disturb
        self.max_steps = max_steps
        self.normalise_coordinates = normalise_coordinates
        self.agent_features = agent_features
        self.global_reward = global_reward
        self.num_agents = self.env.num_agents
        self.action_space = self.env.action_space
        extra = N_AGENT_FEATURES * self.num_agents if agent_features else 0
        self.observation_space = spaces.Tuple(tuple(
            spaces.Box(low=-np.inf, high=np.inf, shape=(s.shape[0] + extra,), dtype=np.float32)
            for s in self.env.observation_space
        ))
        if normalise_coordinates:
            # The Global obs space drops the constructor flag (it lands in the msg_bits slot), so set it on the instance.
            self.env.observation_space_mapper.normalised_coordinates = True
        self.rng = np.random.default_rng()
        self.step_count = 0

    def compute_action_masks(self):
        """Same rule as Warehouse.compute_valid_action_masks with default flags, built from fresh arrays."""
        e = self.env
        n_goals = len(e.goals)
        carrying = np.array(e.get_carrying_shelf_information(), dtype=bool)
        requested = np.array(e.get_shelf_request_information()) > 0
        empty = np.array(e.get_empty_shelf_information()) > 0
        t_agvs = [t - n_goals - 1 for t in e.targets_agvs if t > n_goals]
        t_pickers = [t - n_goals - 1 for t in e.targets_pickers if t > n_goals]
        n_slots = len(e.action_id_to_coords_map) - n_goals

        agv_slots = np.array(np.where(carrying[:, None], empty[None, :], requested[None, :]), dtype=bool)
        agv_slots[:, t_agvs] = False
        picker_slots = np.zeros(n_slots, dtype=bool)
        picker_slots[t_agvs] = True
        picker_slots[t_pickers] = False

        masks = np.ones((e.num_agents, e.action_size), dtype=bool)
        masks[:e.num_agvs, 1:1 + n_goals] = carrying[:, None]
        masks[:e.num_agvs, 1 + n_goals:] = agv_slots
        masks[e.num_agvs:, 1:1 + n_goals] = False
        masks[e.num_agvs:, 1 + n_goals:] = picker_slots[None, :]
        for g in getattr(e, "outage_goal_indices", lambda: ())():  # goal out of service: no AGV may be sent there
            masks[:e.num_agvs, 1 + g] = False
        return masks

    def _obs(self, raw_obs):
        if not self.agent_features:
            return tuple(raw_obs)
        e = self.env
        feats = []
        for i, agent in enumerate(e.agents):
            feats += [
                min(e.stuck_counters[i].count, STUCK_CAP) / STUCK_CAP,
                agent.fixing_clash / FIXING_CLASH_TIME,
                float(agent.busy),
            ]
        feats = np.array(feats, dtype=np.float32)
        return tuple(np.concatenate([o, feats]).astype(np.float32) for o in raw_obs)

    def reset(self, seed=None, options=None):
        raw = self.env.reset(seed=seed)
        if seed is None:
            self.rng = np.random.default_rng()
        else:
            self.rng = np.random.default_rng(np.random.SeedSequence([int(seed), _RNG_TAG]))
        self.step_count = 0
        info = {"action_mask": self.compute_action_masks(), "step_count": 0}
        return self._obs(raw), info

    def step(self, actions):
        raw, rewards, _, _, info = self.env.step(list(actions))
        self.step_count += 1
        rewards = [float(r) for r in rewards]
        total = float(sum(rewards))
        if self.global_reward:
            rewards = [total] * len(rewards)
        info = dict(info)
        info["global_reward"] = total
        info["step_count"] = self.step_count
        info["action_mask"] = self.compute_action_masks()
        truncated = bool(self.step_count >= self.max_steps)
        return self._obs(raw), rewards, False, truncated, info

    def close(self):
        self.env.close()

"""Learned recovery policy: a small Q-network over the RecoveryHook observation, choosing one of recovery.ACTIONS.

PyTorch is imported here only; nothing else in the package imports this module (evaluate.py imports it lazily for
`--recovery learned:<checkpoint>`), so torch is never loaded unless a learned policy is used.

Seam (recovery.py and env.py are untouched): `make_learned_env` builds the env with the registered timeout policy and
then, before reset, replaces the hook instance's `_recovery` with the learned policy. The hook reads `self._recovery`
at every decision. This is the ONLY way a learned policy enters an env (trainer, held-out evaluator, evaluate.py).

Reward (training only). Semi-MDP per agent: a transition starts at the agent's decision at step t and ends at its next
decision at step t' (Delta = t' - t) or at episode end. The window is the half-open step range k in [t, t'): the step in
which the decision is taken counts, the step of the next decision does not. Two decisions of one agent in the same step
give Delta = 0 (no reward, discount 1). Per step k in agent i's window:

    r_k = LINE_REWARD * own_i,k                               the agent's OWN vendored reward (credit "own", 13 Oct)
          - STUCK_PENALTY * [agent busy and StuckCounter.count > 0 after step k]   (0.0 since 13 Oct: off, see below)
          - COST_UNIT * call_human_cost * [executed call-human relocation of the agent in step k]
          - COST_UNIT * abandon_cost * [this decision is abandon]        (charged once, at the window's first step k = t,
                                                                          undiscounted: GAMMA ** 0 = 1)
    R = sum_k GAMMA ** (k - t) * r_k,   target = R + GAMMA ** Delta * max_a Q_target(s', a)   (0 bootstrap at the end)

own_i,k is entry i (agent id - 1) of the per-agent reward vector WarehouseEnv.step returns, built by the vendor with
RewardType.INDIVIDUAL (vendor tarware/warehouse.py:536-606: +0.1 to the AGV and to the picker for a load or an unload,
+1 to the AGV that delivers) and with global_reward=False (make_learned_env asserts both), minus the vendor's constant
-VENDOR_STEP_PENALTY per agent-step (warehouse.py:674), which is added back: at a fixed 500 steps it is the same for
every policy, so it is left out. Nothing is shared between agents: an agent is credited for its own loads, unloads and
deliveries only (a single fleet-shared reward is the "lazy agent" case). The evaluation metric is untouched: pick-rate
is still deliveries * 3600 / (5 * steps) from info["shelf_deliveries"].

Deliveries plus the real action costs only (13 Oct 2026): every stuck measure the recovery action itself can reset
(reroute, back_off and abandon reset the StuckCounter) is a free dodge, so the per-step stuck term is 0 and stuck time
stays an evaluation metric (stuck_busy_agents). COST_UNIT (reward units per stuck-step, the old STUCK_PENALTY value)
prices abandon and call-human in stuck-steps, so those charges did not move.

Episode end is a time-limit truncation treated as terminal: the value of the last windows is biased low.
"""
import hashlib
import os
import random
from pathlib import Path

import torch
from tarware.warehouse import RewardType
from torch import nn

from warehouse_rl.env import WarehouseEnv
from warehouse_rl.recovery import ACTIONS, DEFAULT_CALL_HUMAN_COST, RecoveryHook, RecoveryPolicy

# 2: abandon costs ABANDON_COST stuck-steps and checkpoints carry a top-level "version". v1 checkpoints were trained with
# a zero-cost abandon (the first real run learned to abandon every stuck task) and are refused by load_checkpoint.
FORMAT_VERSION = 2
OBS_KEYS = RecoveryHook.OBS_KEYS
# Fixed per-key divisors (not running statistics) so a checkpoint is portable; the loaded copy is the one used.
OBS_SCALE = {"event_is_clash": 1.0, "stuck_count": 20.0, "fixing_clash": 4.0, "carrying": 1.0, "is_picker": 1.0,
             "path_len": 50.0, "manhattan_to_target": 50.0, "nbr_n": 1.0, "nbr_e": 1.0, "nbr_s": 1.0, "nbr_w": 1.0,
             "queue_pressure": 1.0}
HIDDEN = 64

# reward constants (stored in every checkpoint under "reward")
LINE_REWARD = 1.0
STUCK_PENALTY = 0.0  # per busy stuck agent-step; off (was 0.01): resettable by the action, so gameable
COST_UNIT = 0.01  # reward units per stuck-step of an action cost
GAMMA = 0.99
CALL_HUMAN_COST = DEFAULT_CALL_HUMAN_COST  # one executed call = COST_UNIT * 60 = 0.6
ABANDON_COST = 15  # stuck-steps charged per abandon decision = the timeout rule's own abandon threshold (recovery.py)
CREDIT = "own"  # each agent's own vendored reward (RewardType.INDIVIDUAL), nothing shared
VENDOR_STEP_PENALTY = 0.001  # the vendor's constant per agent-step term (tarware/warehouse.py:674), added back


def reward_constants(call_human_cost=CALL_HUMAN_COST, abandon_cost=ABANDON_COST):
    return {"line_reward": LINE_REWARD, "stuck_penalty": STUCK_PENALTY, "cost_unit": COST_UNIT, "gamma": GAMMA,
            "call_human_cost": call_human_cost, "abandon_cost": abandon_cost, "credit": CREDIT,
            "vendor_step_penalty": "excluded"}


def obs_to_tensor(obs, obs_scale=OBS_SCALE):
    """obs dict -> float32 tensor (12,) in OBS_KEYS order, each value divided by obs_scale[key]. ValueError on missing
    or extra keys."""
    missing, extra = [k for k in OBS_KEYS if k not in obs], sorted(str(k) for k in obs if k not in OBS_KEYS)
    if missing or extra:
        raise ValueError(f"observation keys mismatch: missing {missing}, extra {extra}")
    return torch.tensor([float(obs[k]) / float(obs_scale[k]) for k in OBS_KEYS], dtype=torch.float32)


class QNet(nn.Module):
    """12 -> 64 -> 64 -> 5, ReLU. Output index order == recovery.ACTIONS."""

    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(len(OBS_KEYS), HIDDEN), nn.ReLU(), nn.Linear(HIDDEN, HIDDEN), nn.ReLU(),
                                 nn.Linear(HIDDEN, len(ACTIONS)))

    def forward(self, x):
        return self.net(x)


def greedy_index(q):
    """argmax of a 1-D tensor, ties to the lowest index (explicit, not torch.argmax's unspecified tie rule)."""
    return int((q == q.max()).nonzero()[0])


class LearnedRecovery(RecoveryPolicy):
    """decide(obs) -> argmax Q (ties to the lowest index) when epsilon == 0 (the default). With epsilon > 0 (training
    only) ONE draw u from its own random.Random(seed) per decision: u < epsilon * share -> uniform random action;
    elif u < epsilon -> the `prior` policy's action on the raw obs dict; else greedy. share = 1.0 when prior is None
    (the original epsilon-greedy, same RNG stream), else random_share in [0, 1]."""
    name = "learned"

    def __init__(self, net, obs_scale=OBS_SCALE, epsilon=0.0, seed=0, checkpoint=None, prior=None, random_share=1.0):
        if not 0.0 <= random_share <= 1.0:
            raise ValueError(f"random_share must be in [0, 1], got {random_share!r}")
        self.prior, self.random_share = prior, random_share
        self.net = net.eval()
        self.obs_scale = dict(obs_scale)
        self.epsilon = epsilon
        self.rng = random.Random(seed)
        self.checkpoint = checkpoint  # the loaded checkpoint dict, if any (reward, train_config, ...)
        self.calls = 0
        self.last_x = None  # features and action index of the latest decision (read by the trainer's recorder)
        self.last_idx = None

    def decide(self, obs):
        x = obs_to_tensor(obs, self.obs_scale)
        idx = None
        if self.epsilon > 0.0:
            u = self.rng.random()
            share = 1.0 if self.prior is None else self.random_share
            if u < self.epsilon * share:
                idx = self.rng.randrange(len(ACTIONS))
            elif u < self.epsilon:
                idx = ACTIONS.index(self.prior.decide(obs))
        if idx is None:
            with torch.no_grad():
                idx = greedy_index(self.net(x))
        self.calls += 1
        self.last_x, self.last_idx = x, idx
        return ACTIONS[idx]

    @classmethod
    def from_state_dict(cls, state_dict, obs_scale=OBS_SCALE, epsilon=0.0, seed=0, prior=None, random_share=1.0):
        net = QNet()
        net.load_state_dict(state_dict)
        return cls(net, obs_scale, epsilon, seed, prior=prior, random_share=random_share)

    @classmethod
    def load(cls, path):
        ck = load_checkpoint(path)
        pol = cls.from_state_dict(ck["state_dict"], ck["obs_scale"])
        pol.checkpoint = ck
        return pol


def save_checkpoint(path, state_dict, reward, train_config, obs_scale=OBS_SCALE):
    """Atomic torch.save of tensors and Python primitives only (loadable with weights_only=True)."""
    ck = {"version": FORMAT_VERSION, "state_dict": {k: v.detach().cpu().clone() for k, v in state_dict.items()}, "obs_keys": list(OBS_KEYS),
          "actions": list(ACTIONS), "obs_scale": dict(obs_scale), "reward": dict(reward),
          "train_config": train_config}
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    torch.save(ck, tmp)
    os.replace(tmp, path)


def load_checkpoint(path):
    ck = torch.load(path, map_location="cpu", weights_only=True)
    if ck.get("version") != FORMAT_VERSION:
        raise ValueError(f"{path}: checkpoint version {ck.get('version')!r} != {FORMAT_VERSION}; v1 checkpoints were "
                         f"trained with the zero-cost abandon reward and must be retrained")
    for key in ("state_dict", "obs_keys", "actions", "obs_scale", "reward", "train_config"):
        if key not in ck:
            raise ValueError(f"{path}: checkpoint has no {key!r}")
    if list(ck["obs_keys"]) != list(OBS_KEYS):
        raise ValueError(f"{path}: obs_keys {ck['obs_keys']} != RecoveryHook.OBS_KEYS {list(OBS_KEYS)}")
    if list(ck["actions"]) != list(ACTIONS):
        raise ValueError(f"{path}: actions {ck['actions']} != recovery.ACTIONS {list(ACTIONS)}")
    if set(ck["obs_scale"]) != set(OBS_KEYS):
        raise ValueError(f"{path}: obs_scale keys {sorted(ck['obs_scale'])} != OBS_KEYS")
    return ck


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def learned_config(path):
    """The recovery config of a checkpoint: {name, checkpoint (path as given), sha256, call_human_cost}."""
    ck = load_checkpoint(path)
    return {"name": "learned", "checkpoint": str(path), "sha256": file_sha256(path),
            "call_human_cost": int(ck["reward"]["call_human_cost"])}


def resolve_learned(path):
    """(tag, config) for `--recovery learned:<path>`. Tag = 'learned-' + first 10 hex of the checkpoint sha256."""
    cfg = learned_config(path)
    return "learned-" + cfg["sha256"][:10], cfg


def policy_from_config(cfg):
    """Load the policy named by a learned recovery config; the file's sha256 must match the config's."""
    if cfg.get("name") != "learned":
        raise ValueError(f"not a learned recovery config: {cfg!r}")
    sha = file_sha256(cfg["checkpoint"])
    if sha != cfg["sha256"]:
        raise ValueError(f"{cfg['checkpoint']}: sha256 {sha} != configured {cfg['sha256']}")
    return LearnedRecovery.load(cfg["checkpoint"])


def make_learned_env(env_id, steps, disturb, policy, call_human_cost, assign_care_for_agents=False):
    """WarehouseEnv on the RecoveryHook whose decisions all go to `policy`. The single entry point of a learned policy
    into an env: builds the hook with the registered timeout policy, then swaps the instance's `_recovery`, before
    reset."""
    torch.set_num_threads(1)  # one thread per worker process: N workers x N threads would oversubscribe the cores
    env = WarehouseEnv(env_id, max_steps=steps, disturb=disturb, assign_care_for_agents=assign_care_for_agents,
                       recovery={"name": "timeout", "call_human_cost": call_human_cost}, global_reward=False)
    hook = env.env
    if not isinstance(hook, RecoveryHook):
        raise AssertionError(f"expected a RecoveryHook, got {type(hook).__name__}")
    # own credit needs both: the wrapper must not broadcast the fleet total, the vendor must credit per agent
    if env.global_reward is not False or hook.reward_type != RewardType.INDIVIDUAL:
        raise AssertionError(f"own credit needs global_reward=False and RewardType.INDIVIDUAL, got "
                             f"{env.global_reward!r} and {hook.reward_type!r}")
    hook._recovery = policy
    if hook._recovery is not policy:
        raise AssertionError("the learned policy swap did not take")
    return env

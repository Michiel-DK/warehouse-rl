"""Recovery hook: RecoveryHook(DisturbedWarehouse) routes the vendor's two stuck/clash decision points to a policy.

vendor/ and disturb.py are never edited. The seam is the MRO:

    RecoveryHook -> DisturbedWarehouse -> _HookedVendor -> Warehouse

`_HookedVendor` holds verbatim ports of Warehouse.resolve_move_conflict (W:402-479) and resolve_stuck_agents
(W:481-514) with the decision points replaced by `self._recovery.decide(obs)`; DisturbedWarehouse's `super()` calls land
in those ports, so all of its freeze/delay/obstacle bookkeeping is kept. With `recovery=None` both ports delegate
straight to Warehouse (no decide calls, counters stay 0).

Events (exact):
  STUCK event: an agent in the vendor's `moving_agents` filter whose StuckCounter.count > 0 after `update`.
  CLASH event: the vendor's blocked-agent branch entered when `other.fixing_clash == 0` (W:461).
These are NOT info["stuck_agents"] (count > 0 over all agents) and NOT info["stucks"] (vendor abandonments).

Actions: wait, back_off, reroute, abandon, call_human. No action ever sets FORWARD: a move goes through the next step's
conflict resolution because `_execute_forward` has no occupancy check. `call_human_steps` is an accounting counter only;
pick-rate, deliveries and the reward do not read it.
"""
import hashlib
import json
import math

import networkx as nx
from tarware.definitions import Action, AgentType, CollisionLayers
from tarware.warehouse import Warehouse

from warehouse_rl.disturb import DisturbedWarehouse

# vendor constants (warehouse.py:14-15)
_FIXING_CLASH_TIME = 4
_STUCK_THRESHOLD = 5

ACTIONS = ("wait", "back_off", "reroute", "abandon", "call_human")
DEFAULT_CALL_HUMAN_COST = 60
RECOVERY_INFO_KEYS = ("recovery_wait", "recovery_back_off", "recovery_reroute", "recovery_abandon",
                      "recovery_call_human", "recovery_stuck_events", "recovery_clash_events", "recovery_fallbacks",
                      "call_human_steps")


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


# ------------------------------------------------------------------------------------------------ policies
class RecoveryPolicy:
    """decide(obs) -> one of ACTIONS. obs is a dict with keys RecoveryHook.OBS_KEYS, in that order."""
    name = "base"

    def decide(self, obs):
        raise NotImplementedError


class TunedTimeoutRecovery(RecoveryPolicy):
    """The vendor timeout rule (W:494-513) with parameters. replan < c < abandon -> reroute if path_len > 0 else
    abandon; c > abandon -> abandon; else wait (including the c == abandon dead step). Clash -> reroute."""
    name = "tuned_timeout"

    def __init__(self, replan, abandon):
        if not _is_int(replan) or not _is_int(abandon) or replan < 0 or replan >= abandon:
            raise ValueError(f"need ints 0 <= replan < abandon, got replan={replan!r} abandon={abandon!r}")
        self.replan, self.abandon = replan, abandon

    def decide(self, obs):
        if obs["event_is_clash"]:
            return "reroute"
        c = obs["stuck_count"]
        if self.replan < c < self.abandon:
            return "reroute" if obs["path_len"] > 0 else "abandon"
        if c > self.abandon:
            return "abandon"
        return "wait"


class TimeoutRecovery(TunedTimeoutRecovery):
    """The vendor behaviour on the registered maps: replan 5, abandon 5 + column_height + 2 = 15."""
    name = "timeout"

    def __init__(self):
        super().__init__(_STUCK_THRESHOLD, 15)


# ------------------------------------------------------------------------------------------------ specs
def normalise_recovery(config):
    """Fail closed. Returns the normalised config (all params present). Raises ValueError on anything else."""
    if not isinstance(config, dict):
        raise ValueError(f"recovery config must be a dict, got {type(config).__name__}")
    name = config.get("name")
    if name == "timeout":
        allowed = {"name", "call_human_cost"}
    elif name == "tuned_timeout":
        allowed = {"name", "replan", "abandon", "call_human_cost"}
    else:
        raise ValueError(f"unknown recovery name {name!r}; known: ['timeout', 'tuned_timeout']")
    unknown = set(config) - allowed
    if unknown:
        raise ValueError(f"recovery {name}: unknown keys {sorted(map(str, unknown))}")
    cost = config.get("call_human_cost", DEFAULT_CALL_HUMAN_COST)
    if not _is_int(cost) or cost < 0:
        raise ValueError(f"call_human_cost must be an int >= 0, got {cost!r}")
    out = {"name": name}
    if name == "tuned_timeout":
        missing = {"replan", "abandon"} - set(config)
        if missing:
            raise ValueError(f"recovery tuned_timeout: missing keys {sorted(missing)}")
        TunedTimeoutRecovery(config["replan"], config["abandon"])  # validates
        out["replan"], out["abandon"] = config["replan"], config["abandon"]
    out["call_human_cost"] = cost
    return out


def make_recovery(config):
    cfg = normalise_recovery(config)
    if cfg["name"] == "timeout":
        return TimeoutRecovery()
    return TunedTimeoutRecovery(cfg["replan"], cfg["abandon"])


def resolve_recovery(spec):
    """Preset 'timeout' or a JSON object string -> (tag, normalised config). JSON tag = 'rec-' + 10 hex of sha256."""
    if not isinstance(spec, str):
        raise ValueError(f"recovery spec must be a preset name or a JSON object string, got {type(spec).__name__}")
    s = spec.strip()
    if s == "timeout":
        return "timeout", normalise_recovery({"name": "timeout"})
    if not s.startswith("{"):
        raise ValueError(f"unknown recovery preset {spec!r}; presets: ['timeout']")
    try:
        config = json.loads(s)
    except json.JSONDecodeError as e:
        raise ValueError(f"recovery JSON does not parse: {e}") from e
    config = normalise_recovery(config)
    tag = "rec-" + hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:10]
    return tag, config


# ------------------------------------------------------------------------------------------------ env seam
class _HookedVendor(Warehouse):
    """Verbatim ports of Warehouse.resolve_move_conflict / resolve_stuck_agents; decision points go to the policy."""
    _recovery = None  # set by RecoveryHook.__init__

    def _init_recovery_state(self):
        self._counts = {k: 0 for k in RECOVERY_INFO_KEYS}
        self._clash_abandons = 0
        self._human_queue = {}
        self.decide_calls = 0

    # ---------------------------------------------------------------- observation (no side effects)
    def _neighbours(self, agent):
        return [(agent.x, agent.y - 1), (agent.x + 1, agent.y), (agent.x, agent.y + 1), (agent.x - 1, agent.y)]  # N E S W

    def _on_map(self, cell):
        return 0 <= cell[0] < self.grid_size[1] and 0 <= cell[1] < self.grid_size[0]

    def _cell_free(self, cell, goals_ok=True):
        """Back-off / call-human free cell: on the map, highway, no agent on it, not any agent's req_location, no
        active obstacle (and not a goal cell unless goals_ok)."""
        if not self._on_map(cell) or not self.highways[cell[1], cell[0]]:
            return False
        if not goals_ok and cell in self.goals:
            return False
        if any((a.x, a.y) == cell or a.req_location(self.grid_size) == cell for a in self.agents):
            return False
        return cell not in self._obstacles_now()

    def _observe(self, agent, is_clash):
        obstacles = self._obstacles_now()
        others = {(a.x, a.y) for a in self.agents if a.id != agent.id}
        picker = agent.type == AgentType.PICKER
        nbr = []
        for c in self._neighbours(agent):
            blocked = (not self._on_map(c) or c in others or c in obstacles
                       or (picker and not self.highways[c[1], c[0]]))
            nbr.append(1.0 if blocked else 0.0)
        if agent.path:
            tx, ty = agent.path[-1]
            manhattan = abs(tx - agent.x) + abs(ty - agent.y)
        else:
            manhattan = 0
        vals = [float(is_clash), float(self.stuck_counters[agent.id - 1].count), float(agent.fixing_clash),
                float(agent.carrying_shelf is not None), float(picker), float(len(agent.path)), float(manhattan),
                *nbr, len(self.request_queue) / self.request_queue_size]
        return dict(zip(RecoveryHook.OBS_KEYS, (float(v) for v in vals)))

    def _decide(self, agent, is_clash):
        obs = self._observe(agent, is_clash)
        for v in obs.values():
            if not math.isfinite(v):
                raise ValueError(f"non-finite observation {obs}")
        action = self._recovery.decide(obs)
        if action not in ACTIONS:
            raise ValueError(f"recovery policy returned {action!r}; must be one of {list(ACTIONS)}")
        self.decide_calls += 1
        self._counts["recovery_clash_events" if is_clash else "recovery_stuck_events"] += 1
        self._counts["recovery_" + action] += 1
        return action

    # ---------------------------------------------------------------- actions
    def _reroute_stuck(self, agent):
        """Vendor in-window branch (W:495-504)."""
        agent.req_action = Action.NOOP
        if not agent.path:
            self._counts["recovery_fallbacks"] += 1  # brief: empty path -> wait
            return
        new_path = self.find_path((agent.y, agent.x), (agent.path[-1][1], agent.path[-1][0]), agent)
        if new_path:
            agent.path = new_path
            if len(agent.path) == 1:
                return
            self.stuck_counters[agent.id - 1].reset((agent.x, agent.y))

    def _abandon(self, agent):
        self.stuck_counters[agent.id - 1].reset((agent.x, agent.y))
        agent.req_action = Action.NOOP
        agent.busy = False

    def _back_off(self, agent):
        """First free neighbour in order N, E, S, W with a path to the target. Returns True if executed."""
        if not agent.path:
            return False
        target = agent.path[-1]
        for nbr in self._neighbours(agent):
            if not self._cell_free(nbr):
                continue
            if nbr == target:
                p = []
            else:
                p = self.find_path((nbr[1], nbr[0]), (target[1], target[0]), agent, care_for_agents=True)
                if not p:
                    continue
            agent.path = [nbr] + p
            agent.req_action = Action.NOOP
            return True
        return False

    def _queue_human(self, agent):
        self._human_queue.setdefault(agent.id, agent)

    def _apply_humans(self):
        queue, self._human_queue = self._human_queue, {}
        for agent in queue.values():
            if self._relocate(agent):
                self._counts["call_human_steps"] += self._call_human_cost
            else:
                self._counts["recovery_fallbacks"] += 1

    def _relocate(self, agent):
        if not agent.path:
            return False
        target = agent.path[-1]
        cells = [(int(x), int(y)) for y, x in zip(*self.highways.nonzero())]
        cells.sort(key=lambda c: (abs(c[0] - agent.x) + abs(c[1] - agent.y), c[1], c[0]))
        for cell in cells:
            if cell == target or not self._cell_free(cell, goals_ok=False):
                continue
            p = self.find_path((cell[1], cell[0]), (target[1], target[0]), agent, care_for_agents=True)
            if not p:
                continue
            agent.x, agent.y = cell
            if agent.carrying_shelf:
                agent.carrying_shelf.x, agent.carrying_shelf.y = cell
            agent.path = p
            agent.req_action = Action.NOOP
            agent.fixing_clash = 0
            self.stuck_counters[agent.id - 1].reset(cell)
            self._recalc_grid()
            return True
        return False

    # ---------------------------------------------------------------- ports
    def resolve_move_conflict(self, agent_list):
        if self._recovery is None:
            return super().resolve_move_conflict(agent_list)
        commited_agents = set()
        G = nx.DiGraph()
        for agent in agent_list:
            start = agent.x, agent.y
            target = agent.req_location(self.grid_size)
            G.add_edge(start, target)
        wcomps = [G.subgraph(c).copy() for c in nx.weakly_connected_components(G)]
        for comp in wcomps:
            try:
                cycle = nx.algorithms.find_cycle(comp)
                if len(cycle) == 2:
                    continue
                for edge in cycle:
                    start_node = edge[0]
                    agent_id = self.grid[CollisionLayers.AGVS, start_node[1], start_node[0]]
                    if agent_id > 0:
                        commited_agents.add(agent_id)
                        continue
                    picker_id = self.grid[CollisionLayers.PICKERS, start_node[1], start_node[0]]
                    if picker_id > 0:
                        commited_agents.add(picker_id)
                        continue
            except nx.NetworkXNoCycle:
                longest_path = nx.algorithms.dag_longest_path(comp)
                for x, y in longest_path:
                    agent_id = self.grid[CollisionLayers.AGVS, y, x]
                    if agent_id:
                        commited_agents.add(agent_id)
                        continue
                    picker_id = self.grid[CollisionLayers.PICKERS, y, x]
                    if picker_id:
                        commited_agents.add(picker_id)
        clashes = 0
        for agent in agent_list:
            for other in agent_list:
                if agent.id != other.id:
                    agent_new_x, agent_new_y = agent.req_location(self.grid_size)
                    other_new_x, other_new_y = other.req_location(self.grid_size)
                    if agent.path and ((agent_new_x, agent_new_y) in [(other.x, other.y), (other_new_x, other_new_y)]):
                        if not self._is_highway(agent_new_x, agent_new_y) and (agent.type == AgentType.PICKER or other.type == AgentType.PICKER) and agent.type != other.type:
                            if ((agent.type == AgentType.PICKER and self.grid[CollisionLayers.PICKERS, agent_new_y, agent_new_x] in [0, agent.id])
                                or (agent.type == AgentType.AGV and self.grid[CollisionLayers.AGVS, agent_new_y, agent_new_x] in [0, agent.id])):
                                commited_agents.add(agent.id)
                                continue
                        if (agent_new_x, agent_new_y) == (other.x, other.y):
                            agent.req_action = Action.NOOP
                            if (other_new_x, other_new_y) in [(agent.x, agent.y), (agent_new_x, agent_new_y)] and not other.req_action in (Action.LEFT, Action.RIGHT):
                                if other.fixing_clash == 0:
                                    clashes += self._on_clash(agent)
                        elif (agent_new_x, agent_new_y) == (other_new_x, other_new_y) and (agent_new_x, agent_new_y) != (agent.x, agent.y):
                            if agent.fixing_clash == 0 and other.fixing_clash == 0:
                                agent.req_action = Action.NOOP
                                agent.fixing_clash = _FIXING_CLASH_TIME

        commited_agents = set([self.agents[id_ - 1] for id_ in commited_agents])
        failed_agents = set(agent_list) - commited_agents
        for agent in failed_agents:
            agent.req_action = Action.NOOP
        # clash-decided call_human relocations stay queued until the end of resolve_stuck_agents, so the stuck loop
        # cannot update the relocated agent's counter in the same step (count == 0 after the step it was decided)
        return clashes

    def _on_clash(self, agent):
        """The clash event (W:461 gate passed). Returns the vendor `clashes` increment (1 only for reroute)."""
        action = self._decide(agent, True)
        if action == "reroute":  # vendor exactly (W:462-468)
            agent.fixing_clash = _FIXING_CLASH_TIME
            new_path = self.find_path((agent.y, agent.x), (agent.path[-1][1], agent.path[-1][0]), agent)
            if new_path != []:
                agent.path = new_path
            else:
                agent.fixing_clash = 0
            return 1
        if action == "back_off":
            if self._back_off(agent):
                agent.fixing_clash = _FIXING_CLASH_TIME
            else:
                self._counts["recovery_fallbacks"] += 1
        elif action == "abandon":
            self._clash_abandons += 1
            self._abandon(agent)
        elif action == "call_human":
            self._queue_human(agent)
        return 0

    def resolve_stuck_agents(self):
        if self._recovery is None:
            return super().resolve_stuck_agents()
        overall_stucks = 0
        moving_agents = [
            agent
            for agent in self.agents
            if agent.busy
            and agent.req_action not in (Action.LEFT, Action.RIGHT)
            and (agent.req_action != Action.TOGGLE_LOAD or (agent.x, agent.y) in self.goals)
        ]
        for agent in moving_agents:
            if agent.id in self._human_queue:
                # call_human queued at a clash event this step: relocate here, before the counter update. On success
                # the agent is unstuck (count 0) and raises no second event; on failure it falls back to a real wait:
                # the vendor update and the normal stuck event below run as for any other agent.
                del self._human_queue[agent.id]
                if self._relocate(agent):
                    self._counts["call_human_steps"] += self._call_human_cost
                    continue
                self._counts["recovery_fallbacks"] += 1
            agent_stuck_count = self.stuck_counters[agent.id - 1]
            agent_stuck_count.update((agent.x, agent.y))
            if agent_stuck_count.count <= 0:
                continue
            action = self._decide(agent, False)
            if action == "reroute":
                self._reroute_stuck(agent)
            elif action == "abandon":
                overall_stucks += 1
                self._abandon(agent)
            elif action == "back_off":
                if not self._back_off(agent):
                    self._counts["recovery_fallbacks"] += 1
            elif action == "call_human":
                self._queue_human(agent)
        self._apply_humans()
        overall_stucks += self._clash_abandons
        self._clash_abandons_step = self._clash_abandons
        self._clash_abandons = 0
        return overall_stucks


class RecoveryHook(DisturbedWarehouse, _HookedVendor):
    OBS_KEYS = ("event_is_clash", "stuck_count", "fixing_clash", "carrying", "is_picker", "path_len",
                "manhattan_to_target", "nbr_n", "nbr_e", "nbr_s", "nbr_w", "queue_pressure")

    def __init__(self, *args, disturb, recovery, call_human_cost=DEFAULT_CALL_HUMAN_COST,
                 assign_care_for_agents=False, **kwargs):
        if recovery is not None and not isinstance(recovery, RecoveryPolicy):
            raise ValueError(f"recovery must be None or a RecoveryPolicy, got {type(recovery).__name__}")
        if not _is_int(call_human_cost) or call_human_cost < 0:
            raise ValueError(f"call_human_cost must be an int >= 0, got {call_human_cost!r}")
        self._recovery = recovery
        self._call_human_cost = call_human_cost
        self._init_recovery_state()
        self._clash_abandons_step = 0
        super().__init__(*args, disturb=disturb, assign_care_for_agents=assign_care_for_agents, **kwargs)
        if isinstance(recovery, TimeoutRecovery) and _STUCK_THRESHOLD + self.column_height + 2 != 15:
            raise ValueError(f"TimeoutRecovery assumes abandon = 5 + column_height + 2 = 15, layout has "
                             f"column_height={self.column_height}")

    def reset(self, seed=None, options=None):
        obs = super().reset(seed=seed, options=options)
        self._init_recovery_state()
        self._clash_abandons_step = 0
        return obs

    def resolve_move_conflict(self, agent_list):
        self._clash_abandons_step = 0
        return super().resolve_move_conflict(agent_list)

    def _build_info(self, *args, **kwargs):
        info = super()._build_info(*args, **kwargs)
        # a clash-branch abandon sets busy=False before DisturbedWarehouse's busy diff is taken, so add it here
        info["abandoned_tasks"] += self._clash_abandons_step
        self._clash_abandons_step = 0
        for k in RECOVERY_INFO_KEYS:
            info[k] = self._counts[k]
            self._counts[k] = 0
        return info

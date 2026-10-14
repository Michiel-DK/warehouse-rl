"""Config-driven disturbance layer: DisturbedWarehouse(Warehouse). vendor/ is never edited; this subclasses it.

Config (a plain dict, `{}` = no disturbance, validated fail-closed by `validate_config`):
  breakdown:    {rate_per_hour, duration: [lo, hi], agent_types?: ["agv", "picker"]}   freeze (REQUIRED type)
  delay:        {p_skip, duration?: [lo, hi]}                                          execution delay (REQUIRED type)
  blocked_cell: {rate_per_hour, duration: [lo, hi]}                                    map-level, highway non-goal cells
  burst:        {start, end, extra}                                                    extra requests for steps [start, end)
  outage:       {rate_per_hour, duration: [lo, hi]}                                    map-level, a goal becomes impassable
  floor:        {cells: K, p: [lo, hi]}                                                K fixed bad-floor highway non-goal cells
floor: K cells are drawn without replacement at reset, each with a slip probability p_c ~ U[lo, hi]; an agent that
requests FORWARD into one (ENTER semantics, see resolve_move_conflict) is NOOPed for that step iff its pre-drawn coin
floor_coin[agent, t] < p_c. Floor skips are counted in info["floor_skips"], never in delayed_agents / applied_delayed.
rate_per_hour is the onset rate per robot-hour (map-level for blocked_cell / outage); one step is 5 s, so the
per-step onset probability is rate_per_hour * 5 / 3600. Durations are uniform integers in [lo, hi] steps, lo >= 1.

Common random numbers: the whole schedule is generated in `reset` from an own np.random.Generator seeded by
SeedSequence([seed, sha256(config) as int, fixed tag]); nothing is drawn lazily or conditionally on env state, and the
layer never touches the global `np.random` / `random` (the vendor env seeds and draws from those). The freeze, delay,
blocked-cell and outage schedules are a pure function of (seed, config, num_agents, max_steps, layout), so they are
identical across policies. The floor draws (cells, p_c, the (agents, steps) coin matrix) come from a SEPARATE generator,
and the main generator is seeded from the config WITHOUT the `floor` key, so adding `floor` to a config never shifts
any other type's draws. The floor cells and coins are a function of (seed, full config) only; the realised skips also
depend on where the robots drive.

Burst is only APPROXIMATELY paired across policies. Its timing and size (start, end, extra) are pure functions of the
config, and the shelf identities follow a fixed priority order (a permutation of all shelves drawn at reset from the
(seed, config) rng). But at burst start the first `extra` shelves in that order that are not queued or carried are taken,
and that filter reads live state (policy dependent). The post-end shrink removes the replacement requests the vendor
draws from the global np.random stream after each delivery, which also depends on what the policy delivered. So two
policies share the burst order, not necessarily the burst shelves, and not the shrink.

Step clock: `self._t` is the index of the step being (or about to be) executed. It advances once per step, at the end,
in `_build_info`. Every hook of step s (attribute_macro_actions, find_path, resolve_move_conflict, ...) therefore sees
the schedule of step s, and after step s the layer already describes step s+1 (what action masks need).
"""
import copy
import hashlib
import json
import math

import numpy as np

from tarware.definitions import Action, AgentType, CollisionLayers
from tarware.warehouse import Warehouse
import pyastar2d

STEP_SECONDS = 5  # same constant as pick-rate = deliveries * 3600 / (5 * steps)
_SEED_TAG = 0x44495354  # fixed tag mixed into the layer SeedSequence ("DIST")
_FLOOR_TAG = 0x464C4F52  # extra tag for the separate floor generator ("FLOR")

# Types the layer implements. A key outside this set raises ValueError (never a silent no-op).
LANDED_TYPES = ("breakdown", "delay", "blocked_cell", "burst", "outage", "floor")

PRESETS = {
    "none": {},
    "breakdown-light": {"breakdown": {"rate_per_hour": 2.0, "duration": [20, 60]}},
    "breakdown-heavy": {"breakdown": {"rate_per_hour": 8.0, "duration": [20, 60]}},
    "delay-10": {"delay": {"p_skip": 0.1}},
    "floor-light": {"floor": {"cells": 6, "p": [0.05, 0.25]}},
    "floor-heavy": {"floor": {"cells": 12, "p": [0.2, 0.6]}},
}


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_real(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _check_keys(name, spec, required, optional=()):
    if not isinstance(spec, dict):
        raise ValueError(f"{name} must be a dict, got {type(spec).__name__}")
    unknown = set(spec) - set(required) - set(optional)
    if unknown:
        raise ValueError(f"{name}: unknown keys {sorted(map(str, unknown))}")
    missing = set(required) - set(spec)
    if missing:
        raise ValueError(f"{name}: missing keys {sorted(missing)}")


def _check_rate(name, v):
    if not _is_real(v) or v < 0:
        raise ValueError(f"{name} must be a real number >= 0, got {v!r}")


def _check_duration(name, v):
    if not isinstance(v, (list, tuple)) or len(v) != 2 or not all(_is_int(x) for x in v):
        raise ValueError(f"{name}.duration must be [lo, hi] with int steps, got {v!r}")
    lo, hi = v
    if lo < 1 or lo > hi:
        raise ValueError(f"{name}.duration needs 1 <= lo <= hi, got {v!r}")


def validate_config(config):
    """Fail closed: raise ValueError on anything outside the schema. Returns a JSON-normalised deep copy."""
    if not isinstance(config, dict):
        raise ValueError(f"disturb config must be a dict, got {type(config).__name__}")
    for key in config:
        if key not in LANDED_TYPES:
            raise ValueError(f"unknown or not implemented disturbance type {key!r}; implemented: {list(LANDED_TYPES)}")
    if "breakdown" in config:
        b = config["breakdown"]
        _check_keys("breakdown", b, ("rate_per_hour", "duration"), ("agent_types",))
        _check_rate("breakdown.rate_per_hour", b["rate_per_hour"])
        _check_duration("breakdown", b["duration"])
        if "agent_types" in b:
            at = b["agent_types"]
            if (not isinstance(at, (list, tuple)) or not at or not all(isinstance(x, str) for x in at)
                    or not set(at) <= {"agv", "picker"}):
                raise ValueError(f"breakdown.agent_types must be a non-empty subset of ['agv', 'picker'], got {at!r}")
    if "delay" in config:
        d = config["delay"]
        _check_keys("delay", d, ("p_skip",), ("duration",))
        if not _is_real(d["p_skip"]) or not 0 <= d["p_skip"] <= 1:
            raise ValueError(f"delay.p_skip must be in [0, 1], got {d['p_skip']!r}")
        if "duration" in d:
            _check_duration("delay", d["duration"])
    for name in ("blocked_cell", "outage"):
        if name in config:
            s = config[name]
            _check_keys(name, s, ("rate_per_hour", "duration"))
            _check_rate(f"{name}.rate_per_hour", s["rate_per_hour"])
            _check_duration(name, s["duration"])
    if "burst" in config:
        s = config["burst"]
        _check_keys("burst", s, ("start", "end", "extra"))
        if not all(_is_int(s[k]) for k in ("start", "end", "extra")):
            raise ValueError(f"burst start/end/extra must be ints, got {s!r}")
        if s["start"] < 0 or s["end"] <= s["start"] or s["extra"] < 1:
            raise ValueError(f"burst needs 0 <= start < end and extra >= 1, got {s!r}")
    if "floor" in config:
        f = config["floor"]
        _check_keys("floor", f, ("cells", "p"))
        if not _is_int(f["cells"]) or f["cells"] < 1:
            raise ValueError(f"floor.cells must be an int >= 1, got {f['cells']!r}")
        p = f["p"]
        if (not isinstance(p, (list, tuple)) or len(p) != 2 or not all(_is_real(x) for x in p)
                or not 0 <= p[0] <= p[1] <= 1):
            raise ValueError(f"floor.p must be [lo, hi] with 0 <= lo <= hi <= 1, got {p!r}")
    return json.loads(json.dumps(config))


def config_hash_int(config):
    """Stable (process independent) int from the config. NEVER use hash(): it is salted per process."""
    digest = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).digest()
    return int.from_bytes(digest[:8], "big")


def resolve_disturb(spec):
    """Preset name or JSON object string -> (tag, config). tag = preset name, else 'cfg-' + 10 hex of sha256."""
    if not isinstance(spec, str):
        raise ValueError(f"disturb spec must be a preset name or a JSON object string, got {type(spec).__name__}")
    s = spec.strip()
    if s in PRESETS:
        return s, copy.deepcopy(PRESETS[s])
    if not s.startswith("{"):
        raise ValueError(f"unknown disturbance preset {spec!r}; presets: {sorted(PRESETS)}")
    try:
        config = json.loads(s)
    except json.JSONDecodeError as e:
        raise ValueError(f"disturb JSON does not parse: {e}") from e
    config = validate_config(config)
    tag = "cfg-" + hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:10]
    return tag, config


def _onsets_to_mask(onsets, durations):
    """Union of intervals [t, t + d) for every onset (agent, t). Overlapping onsets simply merge."""
    mask = np.zeros(onsets.shape, dtype=bool)
    for a, t in np.argwhere(onsets):
        mask[a, t:t + int(durations[a, t])] = True
    return mask


_NO_CELLS = frozenset()

ORACLE = "oracle"
DEFAULT_COST_ALPHA = 4.0


def normalise_cost_map(raw):
    """JSON costmap zone ({"x,y": cost}) -> {(x, y): cost} with int tuple keys. The ONE place string keys are parsed."""
    if not isinstance(raw, dict):
        raise ValueError(f"a cost map zone must be a dict, got {type(raw).__name__}")
    out = {}
    for k, v in raw.items():
        if isinstance(k, tuple):
            out[k] = v
            continue
        try:
            xs, ys = str(k).split(",")
            out[(int(xs), int(ys))] = v
        except ValueError as e:
            raise ValueError(f"cost map key {k!r} is not 'x,y' with int x and y") from e
    return out


def validate_cost_map(cost_map, grid_size):
    """None | "oracle" | {(x, y): cost} -> same (dict copied). grid_size = (rows, cols); (x, y) is column, row.

    Anything else raises ValueError: non-int or bool coordinates, cells outside the grid, cost not in (0, 1]."""
    if cost_map is None or (isinstance(cost_map, str) and cost_map == ORACLE):
        return cost_map
    if not isinstance(cost_map, dict):
        raise ValueError(f"cost_map must be None, {ORACLE!r} or a dict, got {cost_map!r}")
    rows, cols = grid_size
    out = {}
    for k, v in cost_map.items():
        if not (isinstance(k, tuple) and len(k) == 2 and all(_is_int(c) for c in k)):
            raise ValueError(f"cost_map key {k!r} must be an (int, int) tuple")
        if not (0 <= k[0] < cols and 0 <= k[1] < rows):
            raise ValueError(f"cost_map cell {k!r} is outside the {cols}x{rows} grid")
        if not _is_real(v) or not 0 < v <= 1:
            raise ValueError(f"cost_map cost for {k!r} must be a real number in (0, 1], got {v!r}")
        out[(int(k[0]), int(k[1]))] = float(v)
    return out


class DisturbedWarehouse(Warehouse):
    def __init__(self, *args, disturb, assign_care_for_agents=False, cost_map=None, cost_alpha=DEFAULT_COST_ALPHA,
                 **kwargs):
        # cost_map (S8C, the analyst's per-zone cost map; NOT part of the disturb config, so the schedules and the floor
        # layout never depend on it): None | {(x, y): cost in (0, 1]} | "oracle". With an active (non-empty) map and
        # cost_alpha > 0 EVERY find_path of this env (macro-action assignment, vendor replans, recovery reroute, policy
        # distance scoring) is an A* on the grid with weight 1 + cost_alpha * cost on the finite map cells. This also
        # changes the distances CTA's assignment scores (it calls find_path): expected, not a side effect.
        if not _is_real(cost_alpha) or cost_alpha < 0:
            raise ValueError(f"cost_alpha must be a finite real >= 0, got {cost_alpha!r}")
        self.cost_alpha = float(cost_alpha)
        # assign_care_for_agents (router-side toggle, sweep d): True forces care_for_agents=True on the one find_path
        # call the env makes when it accepts a macro action (W:366). False (default) is the vendor behaviour.
        self.disturb_config = validate_config(disturb)
        self.assign_care_for_agents = bool(assign_care_for_agents)
        self._in_macro_actions = False
        super().__init__(*args, **kwargs)
        if not isinstance(self.max_steps, int) or self.max_steps < 1:
            raise ValueError("DisturbedWarehouse needs an int max_steps >= 1 (the schedule is pre-generated)")
        goals = set(self.goals)
        # blocked_cell candidates: highway cells that are not goals, as (x, y), fixed order
        self._blockable_cells = sorted(
            (int(x), int(y)) for y, x in np.argwhere(self.highways > 0) if (int(x), int(y)) not in goals
        )
        self._clear_schedule()
        self._cost_map_arg = validate_cost_map(cost_map, self.grid_size)
        self._active_map = None  # the non-empty {(x, y): cost} in force, else None
        self._set_active_map()
        self._clear_map_counters()

    # ---------------------------------------------------------------- cost map
    def _set_active_map(self):
        m = self._cost_map_arg
        if isinstance(m, str):
            # ORACLE ARM ONLY (the one new read of floor_cells): the simulator's ground truth, re-read after each reset.
            m = dict(self.floor_cells)
        self._active_map = dict(m) if m else None
        self._weights = self._active_map if self.cost_alpha > 0 else None

    def _clear_map_counters(self):
        self._routes_changed = 0
        self._map_entered = 0
        self._prev_pos = [(a.x, a.y) for a in getattr(self, "agents", ())]

    # ---------------------------------------------------------------- schedule
    def _clear_schedule(self):
        T, A = self.max_steps, self.num_agents
        self.frozen_schedule = np.zeros((A, T), dtype=bool)
        self.delay_schedule = np.zeros((A, T), dtype=bool)
        self._blocked_by_step = [_NO_CELLS] * T
        self._out_goals_by_step = [()] * T  # goal indices
        self._obstacles_by_step = [_NO_CELLS] * T  # blocked cells + out goal cells, (x, y)
        self._t = 0
        self.applied_frozen = []
        self.applied_delayed = []
        self.applied_floor = []  # per step: bool array, agents NOOPed by a floor skip
        self.floor_cells = {}  # (x, y) -> p_c, simulator-side ground truth; nothing outside this module reads it
        self.floor_coin = np.zeros((A, T))  # pre-drawn uniform coins; a no-floor config never reads them
        self._suppressed = np.zeros(A, dtype=bool)
        self._abandoned = 0
        self.delivered_per_agent = [0] * A
        self.burst_order = []  # shelf ids in burst priority order (pre-generated at reset when burst is configured)

    def _generate_schedule(self, seed):
        """Whole schedule for max_steps x num_agents, drawn in a fixed order. No lazy or state-dependent draws."""
        self._clear_schedule()
        cfg = self.disturb_config
        T, A = self.max_steps, self.num_agents
        s = int(seed) if seed is not None else int(np.random.SeedSequence().entropy)
        # The main rng is seeded from the config WITHOUT `floor`, so adding floor never shifts the other types' draws.
        h = config_hash_int({k: v for k, v in cfg.items() if k != "floor"})
        rng = np.random.default_rng(np.random.SeedSequence([s, h, _SEED_TAG]))
        p_step = lambda rate: min(1.0, rate * STEP_SECONDS / 3600)  # noqa: E731

        if "breakdown" in cfg:
            b = cfg["breakdown"]
            onsets = rng.random((A, T)) < p_step(b["rate_per_hour"])
            durs = rng.integers(b["duration"][0], b["duration"][1] + 1, size=(A, T))
            wanted = set(b.get("agent_types", ["agv", "picker"]))
            eligible = np.array([("picker" if t == AgentType.PICKER else "agv") in wanted for t in self._agent_types])
            self.frozen_schedule = _onsets_to_mask(onsets & eligible[:, None], durs)
        if "delay" in cfg:
            d = cfg["delay"]
            lo, hi = d.get("duration", [1, 1])
            onsets = rng.random((A, T)) < d["p_skip"]
            durs = rng.integers(lo, hi + 1, size=(A, T))
            self.delay_schedule = _onsets_to_mask(onsets, durs)

        blocked = [set() for _ in range(T)]
        if "blocked_cell" in cfg:
            c = cfg["blocked_cell"]
            onsets = rng.random(T) < p_step(c["rate_per_hour"])
            durs = rng.integers(c["duration"][0], c["duration"][1] + 1, size=T)
            cells = rng.integers(0, len(self._blockable_cells), size=T)
            for t in np.flatnonzero(onsets):
                for u in range(t, min(T, t + int(durs[t]))):
                    blocked[u].add(self._blockable_cells[int(cells[t])])
        out = [set() for _ in range(T)]
        if "outage" in cfg:
            c = cfg["outage"]
            onsets = rng.random(T) < p_step(c["rate_per_hour"])
            durs = rng.integers(c["duration"][0], c["duration"][1] + 1, size=T)
            goal_idx = rng.integers(0, len(self.goals), size=T)
            for t in np.flatnonzero(onsets):
                for u in range(t, min(T, t + int(durs[t]))):
                    out[u].add(int(goal_idx[t]))
        if "burst" in cfg:  # drawn last, so adding a burst never moves the other types' draws
            self.burst_order = [self.shelfs[int(i)].id for i in rng.permutation(len(self.shelfs))]
        if "floor" in cfg:  # own generator; fixed order: cells, p_c, coin matrix
            f = cfg["floor"]
            if f["cells"] > len(self._blockable_cells):
                raise ValueError(f"floor.cells={f['cells']} exceeds the {len(self._blockable_cells)} candidate cells")
            frng = np.random.default_rng(np.random.SeedSequence([s, config_hash_int(cfg), _SEED_TAG, _FLOOR_TAG]))
            idx = frng.choice(len(self._blockable_cells), size=f["cells"], replace=False)
            ps = frng.uniform(f["p"][0], f["p"][1], size=f["cells"])
            self.floor_cells = {self._blockable_cells[int(i)]: float(pc) for i, pc in zip(idx, ps)}
            self.floor_coin = frng.random((A, T))
        for t in range(T):
            if blocked[t]:
                self._blocked_by_step[t] = frozenset(blocked[t])
            if out[t]:
                self._out_goals_by_step[t] = tuple(sorted(out[t]))
            if blocked[t] or out[t]:
                self._obstacles_by_step[t] = frozenset(blocked[t]) | frozenset(tuple(self.goals[g]) for g in out[t])

    def reset(self, seed=None, options=None):
        obs = super().reset(seed=seed, options=options)
        self._generate_schedule(seed)
        self._set_active_map()
        self._clear_map_counters()
        return obs

    # ---------------------------------------------------------------- queries
    def _masks_at(self, t):
        if t >= self.max_steps:
            z = np.zeros(self.num_agents, dtype=bool)
            return z, z
        return self.frozen_schedule[:, t], self.delay_schedule[:, t]

    def frozen_now(self):
        """Bool array (per agent, index agent.id - 1): frozen for the step about to execute. No look-ahead."""
        return self._masks_at(self._t)[0]

    def _obstacles_now(self):
        return self._obstacles_by_step[self._t] if self._t < self.max_steps else _NO_CELLS

    def outage_goal_indices(self):
        """Goal indices (into self.goals) out of service for the step about to be executed."""
        return self._out_goals_by_step[self._t] if self._t < self.max_steps else ()

    # ---------------------------------------------------------------- hooks
    def attribute_macro_actions(self, macro_actions):
        self._in_macro_actions = True
        try:
            return super().attribute_macro_actions(macro_actions)
        finally:
            self._in_macro_actions = False

    def find_path(self, start, goal, agent, care_for_agents=True):
        if self.assign_care_for_agents and self._in_macro_actions:
            care_for_agents = True  # only the path the env computes on accepting a macro action
        obstacles = self._obstacles_now()
        if self._weights is None:  # no active map or alpha 0: the unchanged search, no second search
            if not obstacles:
                return super().find_path(start, goal, agent, care_for_agents)
            return self._find_path_with_obstacles(start, goal, agent, care_for_agents, obstacles)
        # Active map: the weighted path is the answer. The unweighted search runs ONLY here, to count
        # routes_changed_by_map (every query of every caller, policy scoring included, not only executed routes).
        weighted = self._find_path_with_obstacles(start, goal, agent, care_for_agents, obstacles, self._weights)
        if not obstacles:
            plain = super().find_path(start, goal, agent, care_for_agents)
        else:
            plain = self._find_path_with_obstacles(start, goal, agent, care_for_agents, obstacles)
        if weighted != plain:
            self._routes_changed += 1
        return weighted

    def _find_path_with_obstacles(self, start, goal, agent, care_for_agents, obstacles, weights=None):
        # Port of Warehouse.find_path (W:256-312). Only change: active blocked cells / out goals become obstacles
        # AFTER the start-cell fix, then the (effective) start is freed again; a blocked target yields [].
        # With obstacles == frozenset() it must equal the vendor method (tested in tests/test_disturb.py).
        grid = np.zeros(self.grid_size)
        if care_for_agents:
            grid += self.grid[CollisionLayers.AGVS]
            grid += self.grid[CollisionLayers.PICKERS]
        grid[goal[0], goal[1]] = 0
        if agent.type == AgentType.PICKER:
            grid += (1 - self.highways)
            grid[goal[0], goal[1]] -= not self._is_highway(goal[1], goal[0])
            for i in range(self.grid_size[1]):
                grid[self.grid_size[0] - 1, i] = 1
        start_fix = (0, 0)
        if agent.type == AgentType.PICKER and ((not self._is_highway(start[1], start[0])) and goal[0] == start[0] and abs(goal[1] - start[1]) == 1):
            if self._is_highway(start[1] - 1, start[0]):
                start_fix = (0, -1)
            if self._is_highway(start[1] + 1, start[0]):
                start_fix = (0, 1)
            grid[start[0], start[1]] = 1
        grid[start[0] + start_fix[0], start[1] + start_fix[1]] = 0
        for bx, by in obstacles:
            grid[by, bx] = 1
        grid[start[0] + start_fix[0], start[1] + start_fix[1]] = 0
        grid = [list(map(int, row)) for row in (grid != 0)]
        grid = np.array(grid, dtype=np.float32)
        grid[np.where(grid == 1)] = np.inf
        grid[np.where(grid == 0)] = 1
        # the start-cell trim reads the BINARY grid (inf = the start was blocked); weights below must not change it
        trim = 1 - int(grid[start[0], start[1]] > 1)
        if weights:  # binary grid first, then weight only the cells that are still finite; vendor (x, y) -> grid[y, x]
            for (wx, wy), cost in weights.items():
                if grid[wy, wx] == 1:
                    grid[wy, wx] = np.float32(1 + self.cost_alpha * cost)
        astar_path = pyastar2d.astar_path(grid, np.add(start, start_fix), goal, allow_diagonal=False)
        if astar_path is not None:
            astar_path = [tuple(x) for x in list(astar_path)]
            astar_path = astar_path[trim:]
        if astar_path:
            return [(x, y) for y, x in astar_path]
        return []

    def resolve_move_conflict(self, agent_list):
        # Warehouse.step calls this exactly once per step, so the per-step bookkeeping lives here.
        # The NOOPs MUST precede super(): _execute_forward has no occupancy check, so a mover can only be kept out
        # of a frozen agent's cell by the clash logic inside super seeing the frozen agent as stationary.
        t = self._t
        frozen, delayed = self._masks_at(t)
        delayed = delayed & ~frozen
        self.applied_frozen.append(frozen.copy())
        self.applied_delayed.append(delayed.copy())
        self._suppressed = frozen | delayed
        floor_skipped = np.zeros(self.num_agents, dtype=bool)
        self._abandoned = 0
        obstacles = self._obstacles_now()
        for agent in agent_list:
            if self._suppressed[agent.id - 1]:
                agent.req_action = Action.NOOP  # all micro-actions: FORWARD, LEFT, RIGHT, TOGGLE_LOAD
            elif self.floor_cells and self._floor_skips(agent, t):
                # Floor: ENTER semantics, not leave. req_location is the target cell the vendor's move resolution
                # evaluates; a move INTO a bad cell is the physical event (wheel slip on a bad patch / floor marker
                # misread on arrival). "Leave" would also fire for agents parked on a floor cell. Precedence
                # frozen > delayed > floor > obstacle, hence this branch sits between them.
                agent.req_action = Action.NOOP
                floor_skipped[agent.id - 1] = True
            elif obstacles and agent.req_action == Action.FORWARD and agent.req_location(self.grid_size) in obstacles:
                agent.req_action = Action.NOOP  # stored paths ignore the mask until replan
        self.applied_floor.append(floor_skipped)
        self._suppressed = self._suppressed | floor_skipped  # same hiding from resolve_stuck_agents as a delay skip
        return super().resolve_move_conflict(agent_list)

    def _floor_skips(self, agent, t):
        if agent.req_action != Action.FORWARD or t >= self.max_steps:
            return False
        target = agent.req_location(self.grid_size)
        if target == (agent.x, agent.y) or target not in self.floor_cells:
            return False
        return bool(self.floor_coin[agent.id - 1, t] < self.floor_cells[target])

    def resolve_stuck_agents(self):
        # Agents the layer NOOPed this step must not advance their StuckCounter, be replanned or lose their task.
        # Hide them from the vendor's `agent.busy` filter for the duration of the call, then restore.
        # Why hide-and-restore is safe (vendor W:481-514): the only read of `busy` is the `moving_agents` filter, and
        # the only writes to `busy` are `busy = False` on agents that are inside `moving_agents`. A hidden agent is
        # outside it, so none of its state (busy, path, req_action, StuckCounter) is touched by the vendor call; the
        # restore then sets busy=True only for exactly the agents that were busy before the call.
        hidden = [a for a in self.agents if a.busy and self._suppressed[a.id - 1]]
        before = [a.busy for a in self.agents]
        for a in hidden:
            a.busy = False
        try:
            stucks = super().resolve_stuck_agents()
        finally:
            for a in hidden:
                a.busy = True
        self._abandoned = sum(1 for a, b in zip(self.agents, before) if b and not a.busy)
        return stucks

    def process_shelf_deliveries(self, rewards):
        t = self._t
        cfg = self.disturb_config
        burst = cfg.get("burst")
        if burst and t == burst["start"]:
            self._start_burst(burst["extra"])
        # Who delivers: exactly the vendor condition (W:589-592), computed before super mutates request_queue.
        credited = []
        for y, x in self.goals:
            shelf_id = self.grid[CollisionLayers.CARRIED_SHELVES, x, y]
            if not shelf_id or self.shelfs[shelf_id - 1] not in self.request_queue:
                continue
            credited.append(int(self.grid[CollisionLayers.AGVS, x, y]) - 1)
        before = {s.id for s in self.request_queue}
        rewards, deliveries = super().process_shelf_deliveries(rewards)  # still draws replacements from np.random
        for idx in credited:
            self.delivered_per_agent[idx] += 1
        if burst and t >= burst["end"] and deliveries:
            replacements = [s for s in self.request_queue if s.id not in before]
            for s in replacements[:max(0, len(self.request_queue) - self.request_queue_size)][:deliveries]:
                self.request_queue.remove(s)
        return rewards, deliveries

    def _start_burst(self, extra):
        # First `extra` shelves of the pre-generated order that are not queued or carried. The order is a function of
        # (seed, config); the filter is live state, hence only approximate pairing (see module docstring).
        carried = {a.carrying_shelf.id for a in self.agents if a.carrying_shelf}
        queued = {s.id for s in self.request_queue}
        free = [sid for sid in self.burst_order if sid not in queued and sid not in carried]
        by_id = {s.id: s for s in self.shelfs}
        for sid in free[:extra]:
            self.request_queue.append(by_id[sid])

    def _build_info(self, agvs_distance_travelled, pickers_distance_travelled, clashes_count, stucks_count,
                    shelf_deliveries):
        info = super()._build_info(agvs_distance_travelled, pickers_distance_travelled, clashes_count, stucks_count,
                                   shelf_deliveries)
        t = self._t
        frozen, delayed = self.applied_frozen[-1], self.applied_delayed[-1]
        # stuck_agents is the literal count > 0. The vendor never resets a StuckCounter when an agent goes idle (only
        # on a new assignment), so it also counts idle agents with stale counts; stuck_busy_agents is the busy subset.
        info["stuck_agents"] = sum(int(c.count > 0) for c in self.stuck_counters)
        info["stuck_busy_agents"] = sum(int(a.busy and c.count > 0) for a, c in zip(self.agents, self.stuck_counters))
        info["abandoned_tasks"] = self._abandoned
        info["clash_agents"] = sum(int(a.fixing_clash > 0) for a in self.agents)
        info["frozen_agents"] = int(frozen.sum())
        info["delayed_agents"] = int(delayed.sum())
        info["floor_skips"] = int(self.applied_floor[-1].sum())
        info["frozen_fraction"] = int(frozen.sum()) / self.num_agents
        info["delivered_per_agent"] = list(self.delivered_per_agent)
        info["blocked_cells"] = len(self._blocked_by_step[t]) if t < self.max_steps else 0
        info["outage_goals"] = len(self._out_goals_by_step[t]) if t < self.max_steps else 0
        info["request_queue_len"] = len(self.request_queue)
        # S8C counters. routes_changed_by_map: find_path queries since the previous step (all callers) whose weighted
        # path differs from the unweighted one. map_cells_entered: agent-steps whose cell changed and whose new cell is in
        # the active map (a floor skip is no entry: the agent did not move).
        pos = [(a.x, a.y) for a in self.agents]
        if self._active_map:
            self._map_entered += sum(1 for p, q in zip(self._prev_pos, pos) if p != q and q in self._active_map)
        self._prev_pos = pos
        info["routes_changed_by_map"] = self._routes_changed
        info["map_cells_entered"] = self._map_entered
        self._routes_changed = 0
        self._map_entered = 0
        self._t += 1  # step t is done; the layer now describes step t + 1
        return info

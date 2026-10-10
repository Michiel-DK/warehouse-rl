"""Policies. CtaPolicy is a step-wise port of tarware.heuristic.heuristic_episode (everything before env.step)."""
from collections import OrderedDict

import numpy as np

from tarware.heuristic import Mission, MissionType
from tarware.utils.utils import flatten_list, split_list
from tarware.warehouse import AgentType


class Policy:
    def reset(self, env):
        """Called after every env.reset."""

    def act(self, obs, masks, info):
        raise NotImplementedError


class RandomPolicy(Policy):
    def __init__(self, seed=None):
        self.rng = np.random.default_rng(seed)

    def act(self, obs, masks, info):
        masks = np.asarray(masks, dtype=bool)
        return [int(self.rng.choice(np.flatnonzero(row))) for row in masks]


def _closest_reachable(paths, starts, goals):
    """Index of the shortest path among reachable candidates (first wins ties), or None.

    Unreachable = find_path returned [] while start != goal (standing on the target is legitimately length 0).
    """
    best, best_len = None, None
    for i, (p, s, g) in enumerate(zip(paths, starts, goals)):
        if len(p) == 0 and tuple(s) != tuple(g):
            continue
        if best is None or len(p) < best_len:
            best, best_len = i, len(p)
    return best


class CtaPolicy(Policy):
    def reset(self, env):
        e = self.env = env.env
        self.non_goal_location_ids = np.array(
            [id_ for id_, c in e.action_id_to_coords_map.items() if (c[1], c[0]) not in e.goals]
        )
        self.location_map = e.action_id_to_coords_map
        self.timestep = 0
        self.agents = e.agents
        self.agvs = [a for a in self.agents if a.type == AgentType.AGV]
        self.pickers = [a for a in self.agents if a.type == AgentType.PICKER]
        self.coords_original_loc_map = {v: k for k, v in e.action_id_to_coords_map.items()}
        sections = split_list(e.rack_groups, len(self.pickers))
        self.picker_sections = [flatten_list(s) for s in sections]
        self.assigned_agvs = OrderedDict()
        self.assigned_pickers = OrderedDict()
        self.assigned_items = OrderedDict()

    def act(self, obs, masks, info):
        env = self.env
        agvs, pickers = self.agvs, self.pickers
        assigned_agvs, assigned_pickers, assigned_items = self.assigned_agvs, self.assigned_pickers, self.assigned_items
        timestep = self.timestep
        location_map = self.location_map
        actions = {k: 0 for k in self.agents}

        for item in env.request_queue:
            if item.id in assigned_items.values():
                continue
            available_agvs = [a for a in agvs if not a.busy and not a.carrying_shelf]
            available_agvs = [a for a in available_agvs if a not in assigned_agvs]
            if not available_agvs:
                continue
            paths = [env.find_path((a.y, a.x), (item.y, item.x), a, care_for_agents=False) for a in available_agvs]
            k = _closest_reachable(paths, [(a.y, a.x) for a in available_agvs], [(item.y, item.x)] * len(paths))
            if k is None:  # guard: every candidate unreachable, leave item unassigned this step
                continue
            closest_agv = available_agvs[k]
            item_location_id = self.coords_original_loc_map[(item.y, item.x)]
            assigned_agvs[closest_agv] = Mission(MissionType.PICKING, item_location_id, item.x, item.y, timestep)
            assigned_items[closest_agv] = item.id  # (sic) vendor keys this by AGV; kept for exact parity

        for agv in agvs:
            if agv in assigned_agvs and agv.x == assigned_agvs[agv].location_x and agv.y == assigned_agvs[agv].location_y:
                assigned_agvs[agv].at_location = True
            if agv not in assigned_agvs or agv.busy:
                continue

            if assigned_agvs[agv].mission_type == MissionType.PICKING and assigned_agvs[agv].at_location and agv.carrying_shelf:
                goal_locations = env.goals  # stored (x, y)
                paths = [env.find_path((agv.y, agv.x), (y, x), agv, care_for_agents=False) for (x, y) in goal_locations]
                k = _closest_reachable(paths, [(agv.y, agv.x)] * len(paths), [(y, x) for (x, y) in goal_locations])
                if k is not None:  # guard: otherwise keep PICKING mission, retry next step
                    closest_goal = goal_locations[k]
                    goal_location_id = self.coords_original_loc_map[(closest_goal[1], closest_goal[0])]
                    assigned_agvs.pop(agv)
                    assigned_agvs[agv] = Mission(MissionType.DELIVERING, goal_location_id, closest_goal[0], closest_goal[1], timestep)

            if assigned_agvs[agv].mission_type == MissionType.DELIVERING and assigned_agvs[agv].at_location and agv.carrying_shelf:
                empty_shelves = env.get_empty_shelf_information()
                empty_location_ids = list(self.non_goal_location_ids[empty_shelves > 0])
                assigned_item_loc_agvs = [m.location_id for m in assigned_agvs.values()]
                empty_location_ids = [i for i in empty_location_ids if i not in assigned_item_loc_agvs]
                empty_location_yx = [location_map[i] for i in empty_location_ids]
                paths = [env.find_path((agv.y, agv.x), (y, x), agv, care_for_agents=False) for (y, x) in empty_location_yx]
                k = _closest_reachable(paths, [(agv.y, agv.x)] * len(paths), empty_location_yx)
                if k is not None:  # guard: no (reachable) empty slot, keep DELIVERING mission, retry next step
                    closest_location_id = empty_location_ids[k]
                    closest_location_yx = location_map[closest_location_id]
                    assigned_agvs.pop(agv)
                    assigned_agvs[agv] = Mission(MissionType.RETURNING, closest_location_id, closest_location_yx[1], closest_location_yx[0], timestep)

            if assigned_agvs[agv].mission_type == MissionType.RETURNING and assigned_agvs[agv].at_location and not agv.carrying_shelf:
                assigned_agvs.pop(agv)
                assigned_items.pop(agv)

        for agv, mission in assigned_agvs.items():
            if mission.mission_type in [MissionType.PICKING, MissionType.RETURNING]:
                in_pickers_zone = [(mission.location_y, mission.location_x) in p for p in self.picker_sections]
                if True not in in_pickers_zone:  # guard: location in no picker zone, skip picker assignment
                    continue
                relevant_picker = pickers[in_pickers_zone.index(True)]
                if relevant_picker not in assigned_pickers.keys():
                    assigned_pickers[relevant_picker] = Mission(MissionType.PICKING, mission.location_id, mission.location_x, mission.location_y, timestep)

        for picker in pickers:
            if picker in assigned_pickers and picker.x == assigned_pickers[picker].location_x and picker.y == assigned_pickers[picker].location_y:
                assigned_pickers[picker].at_location = True
                assigned_pickers.pop(picker)

        for agv, mission in assigned_agvs.items():
            actions[agv] = mission.location_id if not agv.busy else 0
        for picker, mission in assigned_pickers.items():
            actions[picker] = mission.location_id

        self.timestep += 1
        return list(actions.values())

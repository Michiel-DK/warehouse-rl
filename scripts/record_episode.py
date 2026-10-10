"""Record one FIFO-heuristic episode as JSON for the replay viewer.

Usage: python scripts/record_episode.py --env tarware-small-4agvs-2pickers-globalobs-v1 --seed 0 --out results/replay_small.json
"""
import argparse, json
import numpy as np
import gymnasium as gym
import tarware  # noqa: F401
from tarware.heuristic import heuristic_episode
from tarware.definitions import AgentType

p = argparse.ArgumentParser()
p.add_argument("--env", default="tarware-small-4agvs-2pickers-globalobs-v1")
p.add_argument("--seed", type=int, default=0)
p.add_argument("--out", default="results/replay_small.json")
a = p.parse_args()

env = gym.make(a.env).unwrapped
frames = []
orig_step = env.step

def snapshot():
    id2xy = env.action_id_to_coords_map
    return {
        "agents": [{
            "x": ag.x, "y": ag.y, "t": "agv" if ag.type == AgentType.AGV else "picker",
            "c": ag.carrying_shelf is not None,
            "cr": (ag.carrying_shelf in env.request_queue) if ag.carrying_shelf is not None else False,
            "tx": id2xy[ag.target][0] if ag.target in id2xy else None,
            "ty": id2xy[ag.target][1] if ag.target in id2xy else None,
        } for ag in env.agents],
        "req": [[s.x, s.y] for s in env.request_queue],
        "shelves": [[s.x, s.y] for s in env.shelfs],
    }

cum = {"deliveries": 0, "clashes": 0}
def recording_step(actions):
    frames.append(snapshot())
    out = orig_step(actions)
    info = out[4]
    cum["deliveries"] += info["shelf_deliveries"]; cum["clashes"] += info["clashes"]
    frames[-1]["deliv"] = cum["deliveries"]; frames[-1]["clash"] = cum["clashes"]
    return out
env.step = recording_step

heuristic_episode(env, False, a.seed)
H, W = env.grid_size
goals = [[x, y] for (x, y) in env.goals]
highways = [[int(env.highways[y, x]) for x in range(W)] for y in range(H)]
doc = {"env": a.env, "seed": a.seed, "H": H, "W": W, "goals": goals, "highways": highways,
       "num_agvs": env.num_agvs, "num_pickers": env.num_pickers, "frames": frames}
def _default(o):
    if isinstance(o, np.integer): return int(o)
    if isinstance(o, np.bool_): return bool(o)
    raise TypeError(type(o))
with open(a.out, "w") as f:
    json.dump(doc, f, separators=(",", ":"), default=_default)
print(f"{len(frames)} frames, grid {H}x{W}, deliveries {cum['deliveries']}, -> {a.out}")

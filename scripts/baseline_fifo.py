"""Run the TA-RWARE FIFO heuristic and record pick-rate per episode.

Usage: python scripts/baseline_fifo.py --env tarware-small-4agvs-2pickers-globalobs-v1 --episodes 5 --seed 0
Writes results/fifo_<env>.json
"""
import argparse, json, time, statistics
from pathlib import Path
import gymnasium as gym
import tarware  # noqa: F401  (registers envs)
from tarware.heuristic import heuristic_episode

p = argparse.ArgumentParser()
p.add_argument("--env", default="tarware-small-4agvs-2pickers-globalobs-v1")
p.add_argument("--episodes", type=int, default=5)
p.add_argument("--seed", type=int, default=0)
args = p.parse_args()

env = gym.make(args.env)
rows = []
for i in range(args.episodes):
    t0 = time.time()
    infos, global_return, _ = heuristic_episode(env.unwrapped, False, args.seed + i)
    deliveries = sum(x["shelf_deliveries"] for x in infos)
    clashes = sum(x["clashes"] for x in infos)
    stuck = sum(x["stucks"] for x in infos)
    T = len(infos)
    pick_rate = deliveries * 3600 / (5 * T)  # env convention: 1 step = 5 s
    rows.append(dict(seed=args.seed + i, steps=T, deliveries=deliveries, pick_rate=pick_rate,
                     clashes=clashes, stuck=stuck, global_return=global_return, wall_s=time.time() - t0))
    print(f"ep {i} seed {args.seed+i}: steps={T} deliveries={deliveries} pick_rate={pick_rate:.1f}/h "
          f"clashes={clashes} stuck={stuck} wall={rows[-1]['wall_s']:.1f}s")

pr = [r["pick_rate"] for r in rows]
summary = dict(env=args.env, episodes=args.episodes, seed0=args.seed,
               pick_rate_mean=statistics.mean(pr), pick_rate_sd=statistics.pstdev(pr) if len(pr) > 1 else 0.0,
               rows=rows)
out = Path("results") / f"fifo_{args.env}.json"
out.write_text(json.dumps(summary, indent=2))
print(f"mean pick_rate={summary['pick_rate_mean']:.1f}/h sd={summary['pick_rate_sd']:.1f} -> {out}")

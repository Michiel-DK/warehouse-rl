"""Measure env steps/s with N parallel processes (one env each) running CTA episodes.

Usage: python scripts/throughput.py --workers 4 --steps 500 --episodes 10 [--env ID] [--results-dir DIR]
Workers: --workers, else SCHED_WORKERS, else os.cpu_count() - 2. Writes <results-dir>/throughput.json.
"""
import argparse
import importlib.util
import json
import multiprocessing as mp
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def _resolve_workers(cli_value):
    spec = importlib.util.spec_from_file_location("_evaluate_for_tp", REPO / "scripts" / "evaluate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.resolve_workers(cli_value)


def worker(env_id, steps, episodes, base_seed, barrier):
    from warehouse_rl.env import WarehouseEnv
    from warehouse_rl.policy import CtaPolicy

    env = WarehouseEnv(env_id, max_steps=steps)
    policy = CtaPolicy()
    barrier.wait()
    t_start = time.time()
    done = 0
    for ep in range(episodes):
        obs, info = env.reset(seed=base_seed + ep)
        policy.reset(env)
        for _ in range(steps):
            obs, _, _, _, info = env.step(policy.act(obs, info["action_mask"], info))
            done += 1
    t_end = time.time()
    env.close()
    return done, t_start, t_end


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--workers", type=int, default=None)
    p.add_argument("--steps", type=int, default=500)
    p.add_argument("--env", default="tarware-medium-8agvs-4pickers-globalobs-v1")
    p.add_argument("--episodes", type=int, default=10, help="episodes per worker")
    p.add_argument("--results-dir", default=str(REPO / "results"))
    a = p.parse_args()
    n = _resolve_workers(a.workers)
    # Processes (not a Pool) so the Barrier can be passed at spawn time; one env per process.
    ctx = mp.get_context()
    barrier = ctx.Barrier(n)
    queue = ctx.Queue()
    procs = [ctx.Process(target=_run, args=(queue, i, a.env, a.steps, a.episodes, barrier)) for i in range(n)]
    for pr in procs:
        pr.start()
    res = [queue.get() for _ in procs]
    for pr in procs:
        pr.join()
    res = [r[1:] for r in sorted(res)]
    per = [d / (te - ts) for d, ts, te in res]
    wall = max(r[2] for r in res) - min(r[1] for r in res)
    total = sum(r[0] for r in res) / wall
    for i, v in enumerate(per):
        print(f"worker {i}: {v:.0f} steps/s")
    print(f"workers={n} mean per-worker {sum(per) / n:.0f} steps/s, total {total:.0f} steps/s, wall {wall:.1f}s")
    out = Path(a.results_dir)
    out.mkdir(parents=True, exist_ok=True)
    doc = dict(env=a.env, workers=n, steps=a.steps, episodes=a.episodes, per_worker_steps_per_s=per,
               mean_per_worker_steps_per_s=sum(per) / n, total_steps_per_s=total, wall_s=wall,
               cpu_count=os.cpu_count())
    (out / "throughput.json").write_text(json.dumps(doc, indent=2))
    print(f"wrote {out / 'throughput.json'}")


def _run(queue, idx, env_id, steps, episodes, barrier):
    queue.put((idx,) + worker(env_id, steps, episodes, 1000 * idx, barrier))


if __name__ == "__main__":
    main()

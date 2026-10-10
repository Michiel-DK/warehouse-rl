"""Sprint 2 sweeps: density, breakdown rate, delay probability, router ablation. Resumable, multiprocess.

Usage: python scripts/sweep.py --workers N [--smoke] [--only a,b,c,d] [--results-dir DIR]
  a  density     medium map, 2..16 AGVs (pickers = AGVs/2), cta, no disturbance
  b  breakdown   medium 8 AGV + 4 pickers, AGV breakdowns at 0..16 per robot-hour, cta and stuck_aware_cta
  c  delay       medium 8 AGV + 4 pickers, p_skip 0..0.3, cta and stuck_aware_cta
  d  router      density grid, cta with the env's accept-time path ignoring (cta) or respecting (cta_care) other agents
Full run: seeds 0-29, 500 steps. --smoke: seeds 0-1 and the two endpoints of each grid, files named <sweep>_smoke.json.
Every row runs through evaluate.run_seed on the disturbance layer (disturb={} = none), so it carries the stuck and
frozen sums. One mp.Pool over all pending (point, policy, seed) jobs; only the parent writes, atomically, after every
row, to <results-dir>/sweeps/<sweep>.json; (point, policy, seed) rows already on disk are skipped, and a stored sweep
definition that differs from the requested one raises. Plots: <results-dir>/sweep_<name>.png (mean with Student-t 95% CI
band, seed-paired stuck_aware_cta - cta difference for b and c). Per-sweep timing is printed, not stored.
Workers: --workers (bare or empty = unset), else SCHED_WORKERS, else os.cpu_count() - 2. Warm-up W = 0 (no discard).
"""
import argparse
import json
import multiprocessing as mp
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import evaluate as ev  # noqa: E402

STEPS = 500
SEEDS = list(range(30))
SMOKE_SEEDS = [0, 1]
MEDIUM_8 = "tarware-medium-8agvs-4pickers-globalobs-v1"
DENSITY_GRID = list(range(2, 17, 2))
BREAKDOWN_GRID = [0, 1, 2, 4, 8, 16]
BREAKDOWN_DURATION = [20, 60]
DELAY_GRID = [0, 0.05, 0.1, 0.2, 0.3]

# policy label -> (evaluate policy name, assign_care_for_agents)
LABELS = {"cta": ("cta", False), "stuck_aware_cta": ("stuck_aware_cta", False), "cta_care": ("cta", True)}

SWEEPS = {
    "density": dict(letter="a", axis="AGVs (pickers = AGVs / 2)", grid=DENSITY_GRID, policies=["cta"]),
    "breakdown": dict(letter="b", axis="AGV breakdown rate (onsets per robot-hour)", grid=BREAKDOWN_GRID,
                      policies=["cta", "stuck_aware_cta"]),
    "delay": dict(letter="c", axis="delay probability p_skip (per robot-step)", grid=DELAY_GRID,
                  policies=["cta", "stuck_aware_cta"]),
    "router": dict(letter="d", axis="AGVs (pickers = AGVs / 2)", grid=DENSITY_GRID, policies=["cta", "cta_care"]),
}


def point_spec(sweep, point):
    """(env_id, disturb config, n_agents) for one grid point."""
    if sweep in ("density", "router"):
        n = int(point)
        return f"tarware-medium-{n}agvs-{n // 2}pickers-globalobs-v1", {}, n + n // 2
    if sweep == "breakdown":
        cfg = {"breakdown": {"rate_per_hour": point, "duration": list(BREAKDOWN_DURATION), "agent_types": ["agv"]}}
        return MEDIUM_8, cfg, 12
    if sweep == "delay":
        return MEDIUM_8, {"delay": {"p_skip": point}}, 12
    raise ValueError(f"unknown sweep {sweep!r}")


def definition(sweep, smoke):
    d = SWEEPS[sweep]
    grid = [d["grid"][0], d["grid"][-1]] if smoke else d["grid"]
    return json.loads(json.dumps(dict(sweep=sweep, axis=d["axis"], grid=grid, policies=d["policies"], steps=STEPS)))


def sweep_path(results_dir, sweep, smoke):
    return Path(results_dir) / "sweeps" / f"{sweep}{'_smoke' if smoke else ''}.json"


def _write(path, defn, rows):
    rows = sorted(rows, key=lambda r: (defn["grid"].index(r["point"]), defn["policies"].index(r["policy"]), r["seed"]))
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(dict(definition=defn, rows=rows), indent=2))
    os.replace(tmp, path)


def load_rows(path, defn):
    if not path.exists():
        return []
    doc = json.loads(path.read_text())
    if doc["definition"] != defn:
        raise ValueError(f"{path} stores sweep definition {doc['definition']!r}, requested {defn!r}; refusing to merge")
    return doc["rows"]


def _job(args):
    sweep, point, label, seed = args
    env_id, cfg, n_agents = point_spec(sweep, point)
    policy, care = LABELS[label]
    row = ev.run_seed(policy, env_id, STEPS, seed, disturb=cfg, assign_care_for_agents=care)
    row.pop("wall_s")  # timing stays out of the files
    return sweep, dict(point=point, policy=label, n_agents=n_agents, **row)


def plot(sweep, defn, rows, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colors = {"cta": "#1f77b4", "stuck_aware_cta": "#d95f02", "cta_care": "#2a9d4e"}
    grid, policies = defn["grid"], defn["policies"]
    two = sweep in ("breakdown", "delay")
    fig, axes = plt.subplots(1, 3 if two else 1, figsize=(15 if two else 6, 4.2), squeeze=False)
    axes = axes[0]

    def band(ax, xs, per_point, label, color, ls="-"):
        ok = [(x, s) for x, s in zip(xs, per_point) if s["n"]]
        if not ok:
            return
        x = [p[0] for p in ok]
        ax.plot(x, [s["mean"] for _, s in ok], ls, marker="o", color=color, label=label)
        ax.fill_between(x, [s["ci95_low"] for _, s in ok], [s["ci95_high"] for _, s in ok], color=color, alpha=0.2,
                        linewidth=0)

    def pts(policy):
        return [[r for r in rows if r["point"] == g and r["policy"] == policy] for g in grid]

    for pol in policies:
        band(axes[0], grid, [ev.summarise([r["pick_rate"] for r in rs]) for rs in pts(pol)], pol, colors[pol])
    axes[0].set_xlabel(defn["axis"])
    axes[0].set_ylabel("pick-rate (lines/h)")
    axes[0].set_title("mean pick-rate, 95% CI band")
    axes[0].legend()
    if two:
        band(axes[1], grid, [ev.paired_delta(a, b) for a, b in zip(pts("stuck_aware_cta"), pts("cta"))],
             "stuck_aware_cta - cta", colors["stuck_aware_cta"])
        axes[1].axhline(0, color="grey", linewidth=0.8)
        axes[1].set_xlabel(defn["axis"])
        axes[1].set_ylabel("paired difference (lines/h)")
        axes[1].set_title("seed-paired difference, 95% CI band")
        axes[1].legend()
        for pol in policies:
            fz = [ev.summarise([r["frozen_fraction"] for r in rs]) for rs in pts(pol)]
            st = [ev.summarise([r["stuck_agent_steps"] / (r["steps"] * r["n_agents"]) for r in rs]) for rs in pts(pol)]
            band(axes[2], grid, fz, f"{pol}: frozen", colors[pol])
            band(axes[2], grid, st, f"{pol}: stuck (count > 0)", colors[pol], ls="--")
        axes[2].set_xlabel(defn["axis"])
        axes[2].set_ylabel("fraction of robot-time")
        axes[2].set_title("frozen and stuck fraction, 95% CI band")
        axes[2].legend(fontsize=7)
    for ax in axes:
        ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=110)
    plt.close(fig)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--workers", type=ev.workers_arg, nargs="?", default=None)  # bare/empty = unset
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--only", default="a,b,c,d")
    p.add_argument("--results-dir", default=str(REPO / "results"))
    a = p.parse_args()
    letters = [x.strip() for x in a.only.split(",") if x.strip()]
    by_letter = {d["letter"]: name for name, d in SWEEPS.items()}
    if not letters or any(x not in by_letter for x in letters):
        raise ValueError(f"--only must be a comma list from {sorted(by_letter)}, got {a.only!r}")
    names = [by_letter[x] for x in sorted(set(letters))]
    seeds = SMOKE_SEEDS if a.smoke else SEEDS
    results_dir = Path(a.results_dir)
    (results_dir / "sweeps").mkdir(parents=True, exist_ok=True)

    state, jobs = {}, []
    for name in names:
        defn = definition(name, a.smoke)
        path = sweep_path(results_dir, name, a.smoke)
        rows = load_rows(path, defn)
        have = {(r["point"], r["policy"], r["seed"]) for r in rows}
        todo = [(name, g, pol, s) for g in defn["grid"] for pol in defn["policies"] for s in seeds
                if (g, pol, s) not in have]
        state[name] = dict(defn=defn, path=path, rows=rows, todo=len(todo), done=0, cpu=0.0, last=None)
        jobs += todo
        print(f"[{name}] {len(todo)} jobs to run ({len(have)} rows already on disk)")

    t0 = time.time()
    if jobs:
        workers = ev.resolve_workers(a.workers, os.environ, len(jobs))
        print(f"{len(jobs)} jobs on {workers} workers")
        with mp.Pool(workers) as pool:
            for name, row in pool.imap_unordered(_job, jobs):
                st = state[name]
                st["rows"].append(row)
                st["done"] += 1
                st["last"] = time.time() - t0
                _write(st["path"], st["defn"], st["rows"])
    for name in names:
        st = state[name]
        if st["todo"]:
            print(f"[{name}] {st['done']} rows written, last row after {st['last']:.1f} s")
        plot(name, st["defn"], st["rows"], results_dir / f"sweep_{name}{'_smoke' if a.smoke else ''}.png")
        print(f"[{name}] wrote {st['path']}")
    print(f"total {time.time() - t0:.1f} s")


if __name__ == "__main__":
    main()

"""Closed loop (S8C): the analyst's cost map goes back to the central planner, measured against no map and an oracle.

Usage: python scripts/closed_loop.py [--env E] [--seeds N] [--steps S] [--disturb PRESET|JSON] [--alphas 4]
                                     [--workers W] [--out-dir DIR] [--smoke]
Phase A (no map; fleet/ is used through its CLIs only, every path under <out-dir>/phaseA, nothing under fleet/data/):
  fleet/emit.py (N zones, seeds 0..N-1, stuck_aware_cta + timeout) -> fleet/ingest.py --once -> fleet/costmap.py (no
  --publish-every: one publish at the stream end = the full-episode "yesterday's data" map) -> phaseA/costmap.json.
  Skipped when phaseA/costmap.json exists.
Phase B (evaluate.py --policy stuck_aware_cta --recovery timeout, seeds 0..N-1, --results-dir <out-dir>/<arm>):
  none        the floor disturbance on, no map
  map_a<A>    the Phase A map (zone z = seed z), cost_alpha A; one arm per alpha in --alphas
  oracle      the true floor layout as the map, cost_alpha = the headline alpha
  undisturbed --disturb none (same recovery, same seeds): the per-seed reference
Resume is evaluate's own: existing (config, seed) rows are skipped.
Writes <out-dir>/summary.json and <out-dir>/closed_loop.png. --smoke = 2 seeds on the small map, out-dir
results/closed_loop_smoke unless --out-dir is given. Headline alpha 4.0 is fixed here, before any result was looked at.

share of the floor loss recovered = mean(arm - none) / mean(undisturbed - none), all paired per seed; its 95% CI is a
seed bootstrap (1000 resamples, numpy default_rng(BOOTSTRAP_SEED)). When the mean loss is <= MIN_LOSS lines/h the share is
null with a reason (a ratio of noise). `none` means "no map, floor on", not `--disturb none`.
"""
import argparse
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

_spec = importlib.util.spec_from_file_location("evaluate_script", REPO / "scripts" / "evaluate.py")
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)

MEDIUM = "tarware-medium-8agvs-4pickers-globalobs-v1"
SMALL = "tarware-small-4agvs-2pickers-globalobs-v1"
FLOOR_REGIME = '{"floor": {"cells": 80, "p": [0.3, 0.7]}}'
HEADLINE_ALPHA = 4.0  # chosen before any result was looked at
REFERENCE_MEDIUM_30SEED = 53.66  # undisturbed stuck_aware_cta + timeout, 30 seeds x 500 (context only, not used)
MIN_LOSS = 0.5  # lines/h
N_BOOT = 1000
BOOTSTRAP_SEED = 0
MEANS = ("floor_skip_steps", "stuck_busy_agent_steps", "routes_changed_by_map", "map_cells_entered")


def _run(cmd):
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"command failed ({r.returncode}): {' '.join(map(str, cmd))}\n{r.stdout[-2000:]}\n{r.stderr[-4000:]}")
    print(f"  ok {time.time() - t0:5.1f}s  {Path(str(cmd[1])).name}")
    return r.stdout


def phase_a(out_dir, env, seeds, steps, disturb, workers):
    """Emit -> ingest -> costmap, all under out_dir/phaseA. Returns the costmap.json path."""
    pa = out_dir / "phaseA"
    costmap = pa / "costmap.json"
    if costmap.exists():
        print(f"phase A: {costmap} exists, skipped")
        return costmap
    print("phase A: emit -> ingest -> costmap")
    py = sys.executable
    w = ["--workers", str(workers)] if workers else []
    _run([py, REPO / "fleet" / "emit.py", "--zones", str(seeds), "--seed-base", "0", "--steps", str(steps), "--env", env,
          "--disturb", disturb, "--sink", "file", "--rate", "flat", "--speed", "0", "--dir", str(pa)] + w)
    glob = str(pa / "*.jsonl.gz")
    store = f"jsonl:{pa / 'store'}"
    _run([py, REPO / "fleet" / "ingest.py", "--source", "file", "--glob", glob, "--run", "closed_loop", "--store", store,
          "--once"])
    _run([py, REPO / "fleet" / "costmap.py", "--glob", glob, "--run", "closed_loop", "--store", store, "--out",
          str(costmap)])
    return costmap


def alpha_tag(a):
    return f"{a:g}"


def run_arm(out_dir, name, env, seeds, steps, disturb, extra, workers):
    d = out_dir / name
    cmd = [sys.executable, REPO / "scripts" / "evaluate.py", "--policy", "stuck_aware_cta", "--recovery", "timeout",
           "--env", env, "--seeds", f"0-{seeds - 1}", "--steps", str(steps), "--disturb", disturb,
           "--results-dir", str(d)] + extra
    if workers:
        cmd += ["--workers", str(workers)]
    print(f"phase B arm {name}")
    _run(cmd)
    files = sorted(d.glob("*.json"))
    if len(files) != 1:
        raise RuntimeError(f"expected one result file in {d}, found {files}")
    doc = json.loads(files[0].read_text())
    rows = sorted(doc["rows"], key=lambda r: r["seed"])
    if [r["seed"] for r in rows] != list(range(seeds)):
        raise RuntimeError(f"{files[0]} does not hold exactly seeds 0..{seeds - 1}")
    return doc, rows


def _mean(vals):
    vals = list(vals)
    return sum(vals) / len(vals)


def arm_summary(rows, alpha):
    s = ev.summarise([r["pick_rate"] for r in rows])
    out = dict(alpha=alpha, n=s["n"], pick_rate_mean=s["mean"], pick_rate_ci95=[s["ci95_low"], s["ci95_high"]])
    for k in MEANS:
        out[f"{k}_mean"] = _mean(r[k] for r in rows)
    return out


def share_recovered(arm_rows, none_rows, und_rows):
    """mean(arm - none) / mean(undisturbed - none), paired per seed, with a seed-bootstrap CI."""
    import numpy as np

    arm = np.array([r["pick_rate"] for r in arm_rows])
    none = np.array([r["pick_rate"] for r in none_rows])
    und = np.array([r["pick_rate"] for r in und_rows])
    delta, loss = arm - none, und - none
    mean_loss = float(loss.mean())
    if mean_loss <= MIN_LOSS:
        return dict(share=None, ci95=None, mean_loss=mean_loss,
                    reason=f"mean floor loss (undisturbed - none) {mean_loss:.3f} lines/h <= {MIN_LOSS}: a ratio of noise")
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    n = len(delta)
    idx = rng.integers(0, n, size=(N_BOOT, n))
    num, den = delta[idx].mean(axis=1), loss[idx].mean(axis=1)
    ok = den > 0
    shares = num[ok] / den[ok]
    lo, hi = (float(np.percentile(shares, 2.5)), float(np.percentile(shares, 97.5))) if len(shares) else (None, None)
    return dict(share=float(delta.mean() / mean_loss), ci95=[lo, hi], mean_loss=mean_loss, n_resamples=N_BOOT,
                n_resamples_used=int(ok.sum()), bootstrap_seed=BOOTSTRAP_SEED, reason=None)


def figure(path, summary, headline_arm):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    arms = summary["arms"]
    names = [("none", "none"), (headline_arm, f"map (alpha {alpha_tag(HEADLINE_ALPHA)})"), ("oracle", "oracle")]
    means = [arms[a]["pick_rate_mean"] for a, _ in names]
    lows = [m - arms[a]["pick_rate_ci95"][0] for (a, _), m in zip(names, means)]
    highs = [arms[a]["pick_rate_ci95"][1] - m for (a, _), m in zip(names, means)]
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar([lab for _, lab in names], means, yerr=[lows, highs], capsize=5, color=["#7f7f7f", "#1f77b4", "#2ca02c"])
    und = arms["undisturbed"]["pick_rate_mean"]
    ax.axhline(und, color="k", linestyle="--", linewidth=1, label=f"undisturbed mean {und:.1f}")
    ax.set_ylabel("pick-rate (lines/h), mean with 95% CI")
    ax.set_title(f"closed loop: {summary['n_seeds']} seeds x {summary['steps']} steps")
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--env", default=None)
    p.add_argument("--seeds", type=int, default=None)
    p.add_argument("--steps", type=int, default=500)
    p.add_argument("--disturb", default=FLOOR_REGIME)
    p.add_argument("--alphas", default="4", help="comma separated cost_alpha values, one map arm each")
    p.add_argument("--workers", type=ev.workers_arg, nargs="?", default=None)
    p.add_argument("--out-dir", default=None)
    p.add_argument("--smoke", action="store_true", help="2 seeds, small map")
    a = p.parse_args(argv)
    env = a.env or (SMALL if a.smoke else MEDIUM)
    seeds = a.seeds or (2 if a.smoke else 30)
    out_dir = Path(a.out_dir or (REPO / "results" / ("closed_loop_smoke" if a.smoke else "closed_loop")))
    alphas = sorted({float(x) for x in a.alphas.split(",") if x.strip()} | {HEADLINE_ALPHA})
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    costmap = phase_a(out_dir, env, seeds, a.steps, a.disturb, a.workers)
    cm_doc = json.loads(costmap.read_text())
    docs, rows = {}, {}
    plan = [("none", a.disturb, [], None)]
    plan += [(f"map_a{alpha_tag(al)}", a.disturb, ["--costmap", str(costmap), "--costmap-alpha", str(al)], al)
             for al in alphas]
    plan += [("oracle", a.disturb, ["--costmap-oracle", "--costmap-alpha", str(HEADLINE_ALPHA)], HEADLINE_ALPHA),
             ("undisturbed", "none", [], None)]
    for name, disturb, extra, _ in plan:
        docs[name], rows[name] = run_arm(out_dir, name, env, seeds, a.steps, disturb, extra, a.workers)

    arms, deltas, shares = {}, {}, {}
    for name, _, _, alpha in plan:
        arms[name] = arm_summary(rows[name], alpha)
        if name not in ("none", "undisturbed"):
            d = ev.paired_delta(rows[name], rows["none"])
            arms[name]["paired_delta_vs_none"] = dict(mean=d["mean"], ci95=[d["ci95_low"], d["ci95_high"]], n=d["n"])
            arms[name]["share_of_floor_loss_recovered"] = share_recovered(rows[name], rows["none"], rows["undisturbed"])
    headline_arm = f"map_a{alpha_tag(HEADLINE_ALPHA)}"
    summary = dict(
        env=env, n_seeds=seeds, steps=a.steps, disturb=a.disturb, recovery="timeout", policy="stuck_aware_cta",
        map_tag=docs[headline_arm]["costmap"].split(":")[0], map_path=str(costmap),
        map_generated_at=cm_doc.get("generated_at"), alphas=alphas,
        headline_alpha=HEADLINE_ALPHA, headline_alpha_note="fixed in scripts/closed_loop.py before any result was seen",
        headline_arm=headline_arm, reference_medium_30seed_undisturbed=REFERENCE_MEDIUM_30SEED,
        reference_note="context only; not used in any computation",
        definitions=dict(none="floor on, no map", undisturbed="--disturb none, same recovery and seeds",
                         share="mean(arm - none) / mean(undisturbed - none), paired per seed"),
        arms=arms, wall_s=time.time() - t0)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    figure(out_dir / "closed_loop.png", summary, headline_arm)
    print(f"{'arm':<14}{'pick-rate':>10}{'95% CI':>20}{'delta vs none':>15}{'share':>8}")
    for name, s in arms.items():
        dl = s.get("paired_delta_vs_none")
        sh = s.get("share_of_floor_loss_recovered", {}).get("share")
        ci = "[%.2f, %.2f]" % tuple(s["pick_rate_ci95"])
        dtxt = "%+.2f" % dl["mean"] if dl else "-"
        stxt = "%.2f" % sh if sh is not None else "-"
        print(f"{name:<14}{s['pick_rate_mean']:>10.2f}{ci:>20}{dtxt:>15}{stxt:>8}")
    print(f"wrote {out_dir / 'summary.json'} and {out_dir / 'closed_loop.png'} in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()

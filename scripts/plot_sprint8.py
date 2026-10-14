"""Sprint 8 (analyst half) figures from results files only. No simulation, no measurement.

  .venv/bin/python scripts/plot_sprint8.py

Reads  results/stuck_aware_cta_tarware-medium-8agvs-4pickers-globalobs-v1_500_{floor-light,floor-heavy,cfg-*}_timeout.json
       results/cta_tarware-medium-8agvs-4pickers-globalobs-v1_500.json          (undisturbed reference)
       results/fleet/hotspot_<tag>.json                                          (precision/recall@K per zone)
       fleet/data/<run>/costmap.json + truth.json                                (one zone's cost map vs true floor cells; optional)
Writes results/floor_severity.png, results/fleet/hotspot_precision_recall.png, results/fleet/hotspot_costmap_zone0.png
"""
import glob
import json
import math
import os
import statistics as st
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = "tarware-medium-8agvs-4pickers-globalobs-v1"
HOTSPOT_TAG = "s8b-medium-80-p03-07"
RUN_DIR = os.path.join(ROOT, "fleet", "data", "s8b-score")


def ci95(xs):
    return 1.96 * st.stdev(xs) / math.sqrt(len(xs)) if len(xs) > 1 else 0.0


def floor_rows():
    out = []
    ref = json.load(open(os.path.join(ROOT, "results", f"cta_{ENV}_500.json")))["rows"]
    pr = [r["pick_rate"] for r in ref]
    out.append({"cells": 0, "p": None, "mean": st.mean(pr), "ci": ci95(pr), "skips": 0.0, "n": len(pr), "label": "none (CTA)"})
    for f in sorted(glob.glob(os.path.join(ROOT, "results", f"stuck_aware_cta_{ENV}_500_*_timeout.json"))):
        d = json.load(open(f))
        cfg = (d.get("disturb") or {}).get("floor")
        if not cfg:
            continue
        rows = d["rows"]
        pr = [r["pick_rate"] for r in rows]
        out.append({"cells": cfg["cells"], "p": cfg["p"], "mean": st.mean(pr), "ci": ci95(pr),
                    "skips": st.mean(r.get("floor_skip_steps", 0) for r in rows), "n": len(pr),
                    "label": d.get("disturb_tag", os.path.basename(f))})
    out.sort(key=lambda r: (r["cells"], r["p"] or [0, 0]))
    return out


def plot_floor(rows, out):
    fig, ax = plt.subplots(figsize=(6.4, 4.0))
    xs = [r["cells"] for r in rows]
    ys = [r["mean"] for r in rows]
    es = [r["ci"] for r in rows]
    ax.errorbar(xs, ys, yerr=es, fmt="o-", capsize=3)
    for r in rows:
        if r["p"]:
            ax.annotate(f"p {r['p'][0]}-{r['p'][1]}\n{r['skips']:.0f} skips/ep", (r["cells"], r["mean"]),
                        textcoords="offset points", xytext=(6, 6), fontsize=7)
    ax.set_xlabel("bad floor cells (of 380 highway cells, medium map)")
    ax.set_ylabel("pick-rate (lines/h), 30 seeds, 95% CI")
    ax.set_title("Floor imperfections: pick-rate vs severity", fontsize=10)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=110)
    plt.close(fig)


def plot_hotspot(hs, out):
    ks = sorted(int(k) for k in next(iter(hs["zones"].values()))["k"])
    fig, ax = plt.subplots(figsize=(6.4, 4.0))
    for z, zd in hs["zones"].items():
        ax.plot(ks, [zd["k"][str(k)]["precision"] for k in ks], color="tab:blue", alpha=0.25, lw=1)
        ax.plot(ks, [zd["k"][str(k)]["recall"] for k in ks], color="tab:orange", alpha=0.25, lw=1)
    mean = hs["mean"]["k"] if "k" in hs.get("mean", {}) else None
    if mean is None:
        mean = {str(k): {m: st.mean(zd["k"][str(k)][m] for zd in hs["zones"].values()) for m in ("precision", "recall")} for k in ks}
    ax.plot(ks, [mean[str(k)]["precision"] for k in ks], "o-", color="tab:blue", label="precision@K (mean of zones)")
    ax.plot(ks, [mean[str(k)]["recall"] for k in ks], "s-", color="tab:orange", label="recall@K (mean of zones)")
    n_floor = next(iter(hs["zones"].values()))["n_floor"]
    ax.axhline(n_floor / 380, color="grey", ls="--", lw=1, label=f"random precision ({n_floor}/380)")
    zs = st.mean(zd["zero_stall_share"] for zd in hs["zones"].values())
    ax.axhline(1 - zs, color="tab:red", ls=":", lw=1, label=f"recall ceiling (1 - zero-stall share {zs:.2f})")
    ax.set_xlabel("K = cells flagged")
    ax.set_ylabel("score")
    ax.set_ylim(0, 1.02)
    ax.set_title(f"Hotspot map vs true floor cells, {len(hs['zones'])} zones ({hs['tag']})")
    ax.legend(fontsize=7)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=110)
    plt.close(fig)


def plot_costmap(run_dir, zone, out):
    cm = json.load(open(os.path.join(run_dir, "costmap.json")))["zones"][zone]
    truth = json.load(open(os.path.join(run_dir, "truth.json")))["zones"][zone]["floor_cells"]
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from warehouse_rl.env import WarehouseEnv  # noqa: E402
    env = WarehouseEnv(ENV, max_steps=1)
    env.reset(seed=0)
    inner = next(v for v in vars(env).values() if hasattr(v, "highways"))
    hw = inner.highways
    h, w = hw.shape
    import numpy as np  # noqa: E402
    grid = np.full((h, w), np.nan)
    grid[hw > 0] = 0.0
    for key, c in cm.items():
        x, y = (int(v) for v in key.split(","))
        grid[y, x] = c
    fig, ax = plt.subplots(figsize=(5.2, 5.8))
    ax.imshow(grid, cmap="Reds", vmin=0, vmax=1, interpolation="nearest")
    for key, p in truth.items():
        x, y = (int(v) for v in key.split(","))
        ax.add_patch(plt.Rectangle((x - 0.5, y - 0.5), 1, 1, fill=False, ec="black", lw=0.9))
    hits = sum(1 for k in truth if k in cm)
    ax.set_title(f"Zone {zone}: cost map (red) vs true bad cells (boxes)\n{len(truth)} true cells, {len(cm)} flagged, {hits} true cells flagged",
                 fontsize=9)
    ax.set_xticks([])
    ax.set_yticks([])
    fig.tight_layout()
    fig.savefig(out, dpi=110)
    plt.close(fig)


def main():
    rows = floor_rows()
    plot_floor(rows, os.path.join(ROOT, "results", "floor_severity.png"))
    print("floor severity rows:")
    for r in rows:
        print(f"  cells={r['cells']:>3} p={r['p']} mean={r['mean']:.2f} ci={r['ci']:.2f} skips={r['skips']:.0f} n={r['n']}")
    hs = json.load(open(os.path.join(ROOT, "results", "fleet", f"hotspot_{HOTSPOT_TAG}.json")))
    plot_hotspot(hs, os.path.join(ROOT, "results", "fleet", "hotspot_precision_recall.png"))
    if os.path.exists(os.path.join(RUN_DIR, "costmap.json")):
        plot_costmap(RUN_DIR, "0", os.path.join(ROOT, "results", "fleet", "hotspot_costmap_zone0.png"))
    else:
        print("no cost map run dir; skipping the heatmap")
    print("wrote results/floor_severity.png results/fleet/hotspot_precision_recall.png results/fleet/hotspot_costmap_zone0.png")


if __name__ == "__main__":
    main()

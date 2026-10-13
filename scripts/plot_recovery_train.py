"""Sprint 3 close-out: training curves of the three learned-recovery attempts, from their log.json files only.

Usage: python scripts/plot_recovery_train.py [--results-dir DIR] [--out PNG]
Reads <results-dir>/recovery_train_v1_degenerate/*/log.json (v1: stuck penalty, abandon free),
<results-dir>/recovery_train_smoke/*/log.json (v2 warm-start probes, one interval each) and
<results-dir>/recovery_train_v2_pilot_aborted/*/log.json (v2 own credit, aborted), and writes
<results-dir>/recovery_train_curves.png with three panels against the training episode:
  greedy eval pick-rate (mean over the 5 eval seeds) with the timeout reference line from the v2 logs;
  mean training return per interval (v1 and v2 rewards are NOT comparable: v1 includes a per-step stuck penalty);
  recovery decisions per training episode (interval decisions / episodes in the interval).
Single-interval logs (the probes) are drawn as markers. Nothing is hardcoded; a missing log set raises.
"""
import argparse
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SETS = [("v1 (stuck penalty, abandon free)", "recovery_train_v1_degenerate"),
        ("v2 probe", "recovery_train_smoke"),
        ("v2 pilot (own credit, aborted)", "recovery_train_v2_pilot_aborted")]


def load(results_dir):
    """[(label, run name, log dict)] in SETS order; FileNotFoundError when a set has no log.json."""
    out = []
    for label, sub in SETS:
        paths = sorted((results_dir / sub).glob("*/log.json"))
        if not paths:
            raise FileNotFoundError(f"no log.json under {results_dir / sub}")
        out += [(label, p.parent.name, json.loads(p.read_text())) for p in paths]
    return out


def per_episode_decisions(intervals):
    prev, out = 0, []
    for iv in intervals:
        out.append(iv["decisions"] / (iv["episode"] - prev))
        prev = iv["episode"]
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--results-dir", default=str(REPO / "results"))
    p.add_argument("--out", default=None)
    a = p.parse_args()
    results_dir = Path(a.results_dir)
    out = Path(a.out) if a.out else results_dir / "recovery_train_curves.png"
    runs = load(results_dir)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    refs = {json.dumps(d["reference_pick_rate"]) for _, _, d in runs if d.get("reference_pick_rate")}
    if len(refs) != 1:
        raise ValueError(f"expected one timeout reference across the v2 logs, got {sorted(refs)}")
    ref = json.loads(refs.pop())
    seeds = {tuple(d["config"]["eval_seeds"]) for _, _, d in runs}
    if len(seeds) != 1:
        raise ValueError(f"eval seeds differ between logs: {sorted(seeds)}; the reference line would not apply")

    cmap = plt.get_cmap("tab10")
    fig, axes = plt.subplots(1, 3, figsize=(17, 4.6))
    for i, (label, run, d) in enumerate(runs):
        iv = d["intervals"]
        x = [r["episode"] for r in iv]
        style = dict(color=cmap(i), label=f"{label}: {run}" + (" (aborted)" if "aborted" in d else ""))
        style.update(dict(marker="o", linestyle="none", markersize=6) if len(iv) == 1
                     else dict(marker=".", markersize=3, linewidth=1))
        axes[0].plot(x, [r["eval_pick_rate_mean"] for r in iv], **style)
        axes[1].plot(x, [r["train_reward_mean"] for r in iv], **style)
        axes[2].plot(x, per_episode_decisions(iv), **style)
    axes[0].axhline(ref["mean"], color="black", linestyle="--", linewidth=1,
                    label=f"timeout reference {ref['mean']:.2f} (eval seeds {seeds.pop()[0]}+)")
    axes[0].set_title("greedy eval pick-rate, mean of 5 eval seeds")
    axes[0].set_ylabel("pick-rate (lines/h)")
    axes[1].axhline(0, color="grey", linewidth=0.8)
    axes[1].set_title("mean training return per interval (v1 and v2 rewards differ)", fontsize=9)
    axes[1].set_ylabel("episode return")
    axes[2].set_title("recovery decisions per training episode")
    axes[2].set_ylabel("decisions / episode")
    for ax in axes:
        ax.set_xlabel("training episode")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=6)
    fig.suptitle("Learned recovery, rate 1, medium map: three attempts", fontsize=10)
    fig.tight_layout()
    fig.savefig(out, dpi=110)
    plt.close(fig)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()

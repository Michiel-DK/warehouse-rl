"""Held-out evaluation of trained LearnedRecovery checkpoints against the README best rule and timeout. Resumable.

Usage: python scripts/recovery_heldout.py --workers N [--smoke] [--results-dir DIR] [--train-dir DIR]
Configs (labels): every FINISHED checkpoint under --train-dir (default results/recovery_train: a directory named
rate<r>_seed<s> whose log.json has finished == true and which holds checkpoint.pt) as `learned rate<r> seed<s>` with the
checkpoint sha256 in the definition; `rule 5/10/25` (RuleRecovery 5/10/25, no human: the README's best rule at rates 1,
2 and 8, a fixed choice recorded in the definition); `timeout`. With zero finished checkpoints only the last two run.
Grid: AGV breakdown rate {1, 1.5, 2, 3, 4, 6} per robot-hour via sweep.point_spec("breakdown", rate), seeds 0-29, 500
steps, medium map (8 AGVs + 4 pickers), dispatcher StuckAwareCtaPolicy. Held-out: training episode seeds and the
training eval seeds (1000-1004) are disjoint from 0-29. --smoke: seeds 0,1, rates 1 and 6, files named
heldout_smoke.json / recovery_heldout_smoke.png.
Rows are exactly recovery_sweep rows (evaluate.run_seed without wall_s, plus point, config, n_agents), so the timeout row
at rate 1 seed 0 equals the committed results/recovery/timeout.json row. One mp.Pool over all pending (point, config,
seed) jobs; only the parent writes, atomically, after every row, <results-dir>/recovery/heldout[_smoke].json
({definition, rows, deltas}); rows on disk are skipped and a stored definition that differs from the requested one raises
(a changed checkpoint sha256 and an added or removed finished checkpoint included: a new checkpoint set is a new
definition; delete or rename the file). deltas = {"vs_timeout": {label: [{point, n, mean, sd, ci95_low, ci95_high}]},
"vs_rule": {...}}: evaluate.paired_delta (seed-paired, config minus baseline) per rate and config, the baseline's own
entry omitted. Plot <results-dir>/recovery_heldout[_smoke].png: mean pick-rate with Student-t 95% CI band, and the two
paired-delta panels. Timing is printed, not stored. Workers: --workers (bare or empty = unset), else SCHED_WORKERS, else
os.cpu_count() - 2. This script makes no claim about which config is better; it measures.
"""
import argparse
import json
import multiprocessing as mp
import os
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import evaluate as ev  # noqa: E402
from sweep import MEDIUM_8, SEEDS, SMOKE_SEEDS, STEPS, point_spec  # noqa: E402

from warehouse_rl.recovery import normalise_recovery  # noqa: E402

GRID = [1, 1.5, 2, 3, 4, 6]
SMOKE_GRID = [1, 6]
AXIS = "AGV breakdown rate (onsets per robot-hour)"
RULE_TRIPLE = (5, 10, 25)
RULE_LABEL = "rule 5/10/25"
TIMEOUT_LABEL = "timeout"
RUN_DIR = re.compile(r"^rate(\d+(?:\.\d+)?)_seed(\d+)$")
RULE_NOTE = ("README 'Best rule': the patient ladder 5/10/25 with no call-human rung is the best hand-written rule at "
             "rates 1, 2 and 8 (no rule beats timeout)")


def finished_checkpoints(train_dir):
    """[(rate, seed, checkpoint path)] for finished runs, sorted by (rate, seed). Rate keeps the directory's token."""
    out = []
    train_dir = Path(train_dir)
    if not train_dir.is_dir():
        return out
    for d in sorted(train_dir.iterdir()):
        m = RUN_DIR.match(d.name)
        if not (m and d.is_dir() and (d / "log.json").exists() and (d / "checkpoint.pt").exists()):
            continue
        if json.loads((d / "log.json").read_text()).get("finished") is True:
            out.append((m.group(1), int(m.group(2)), d / "checkpoint.pt"))
    return sorted(out, key=lambda t: (float(t[0]), t[1]))


def configs(train_dir):
    """[(label, recovery config used in the run, definition entry)] in plot order."""
    out = []
    ckpts = finished_checkpoints(train_dir)
    if ckpts:
        from warehouse_rl.learned_recovery import learned_config  # torch only when there is a checkpoint
    for rate, seed, path in ckpts:
        cfg = learned_config(path)
        label = f"learned rate{rate} seed{seed}"
        out.append((label, cfg, dict(label=label, kind="learned", run=f"rate{rate}_seed{seed}",
                                     sha256=cfg["sha256"], call_human_cost=cfg["call_human_cost"])))
    rule = normalise_recovery(dict(name="rule", back_off_after=RULE_TRIPLE[0], reroute_after=RULE_TRIPLE[1],
                                   abandon_after=RULE_TRIPLE[2], call_human_after=None))
    out.append((RULE_LABEL, rule, dict(label=RULE_LABEL, kind="rule", recovery=rule, note=RULE_NOTE)))
    tmo = normalise_recovery({"name": "timeout"})
    out.append((TIMEOUT_LABEL, tmo, dict(label=TIMEOUT_LABEL, kind="timeout", recovery=tmo)))
    return out


def definition(smoke, cfgs):
    return json.loads(json.dumps(dict(
        sweep="heldout", axis=AXIS, grid=SMOKE_GRID if smoke else GRID, steps=STEPS, env=MEDIUM_8,
        dispatcher="stuck_aware_cta", seeds=SMOKE_SEEDS if smoke else SEEDS, baselines=dict(timeout=TIMEOUT_LABEL,
                                                                                         rule=RULE_LABEL),
        configs=[e for _, _, e in cfgs])))


def heldout_path(results_dir, smoke):
    return Path(results_dir) / "recovery" / f"heldout{'_smoke' if smoke else ''}.json"


def compute_deltas(defn, rows):
    labels = [c["label"] for c in defn["configs"]]
    out = {}
    for key, base in (("vs_timeout", TIMEOUT_LABEL), ("vs_rule", RULE_LABEL)):
        out[key] = {}
        for lbl in labels:
            if lbl == base:
                continue
            out[key][lbl] = [dict(point=g, **ev.paired_delta([r for r in rows if r["config"] == lbl and r["point"] == g],
                                                              [r for r in rows if r["config"] == base
                                                               and r["point"] == g]))
                             for g in defn["grid"]]
    return out


def _write(path, defn, rows):
    labels = [c["label"] for c in defn["configs"]]
    rows = sorted(rows, key=lambda r: (defn["grid"].index(r["point"]), labels.index(r["config"]), r["seed"]))
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(dict(definition=defn, rows=rows, deltas=compute_deltas(defn, rows)), indent=2))
    os.replace(tmp, path)


def load_rows(path, defn):
    if not path.exists():
        return []
    doc = json.loads(path.read_text())
    if doc["definition"] != defn:
        raise ValueError(f"{path} stores heldout definition {doc['definition']!r}, requested {defn!r}; "
                         f"refusing to merge (a new checkpoint set is a new definition: delete or rename the file)")
    return doc["rows"]


def _job(args):
    point, label, recovery, seed = args
    env_id, cfg, n_agents = point_spec("breakdown", point)
    row = ev.run_seed("stuck_aware_cta", env_id, STEPS, seed, disturb=cfg, recovery=recovery)
    row.pop("wall_s")  # timing stays out of the files
    return dict(point=point, config=label, n_agents=n_agents, **row)


def plot(defn, rows, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    grid = defn["grid"]
    labels = [c["label"] for c in defn["configs"]]
    cmap = plt.get_cmap("tab20")
    colors = {lbl: cmap(i % 20) for i, lbl in enumerate(labels)}
    colors[TIMEOUT_LABEL], colors[RULE_LABEL] = "black", "tab:red"
    fig, axes = plt.subplots(1, 3, figsize=(18, 4.6))

    def band(ax, stats, label, color, ls="-"):
        ok = [(g, s) for g, s in zip(grid, stats) if s["n"]]
        if not ok:
            return
        ax.plot([g for g, _ in ok], [s["mean"] for _, s in ok], ls, marker="o", color=color, label=label, markersize=3)
        ax.fill_between([g for g, _ in ok], [s["ci95_low"] for _, s in ok], [s["ci95_high"] for _, s in ok],
                        color=color, alpha=0.12, linewidth=0)

    def at(lbl, g):
        return [r for r in rows if r["config"] == lbl and r["point"] == g]

    for lbl in labels:
        band(axes[0], [ev.summarise([r["pick_rate"] for r in at(lbl, g)]) for g in grid], lbl, colors[lbl],
             "--" if lbl in (TIMEOUT_LABEL, RULE_LABEL) else "-")
    axes[0].set_ylabel("pick-rate (lines/h)")
    axes[0].set_title("mean pick-rate, 95% CI band")
    for ax, key, base in ((axes[1], "vs_timeout", TIMEOUT_LABEL), (axes[2], "vs_rule", RULE_LABEL)):
        ax.axhline(0, color="grey", linewidth=0.8)
        for lbl in labels:
            if lbl != base:
                band(ax, [ev.paired_delta(at(lbl, g), at(base, g)) for g in grid], lbl, colors[lbl])
        ax.set_ylabel("paired difference (lines/h)")
        ax.set_title(f"seed-paired delta vs {base}, 95% CI band")
    for ax in axes:
        ax.set_xlabel(AXIS)
        ax.set_xticks(grid)
        ax.grid(alpha=0.3)
        if ax.get_legend_handles_labels()[0]:
            ax.legend(fontsize=6)
    fig.tight_layout()
    fig.savefig(out, dpi=110)
    plt.close(fig)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--workers", type=ev.workers_arg, nargs="?", default=None)  # bare/empty = unset
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--results-dir", default=str(REPO / "results"))
    p.add_argument("--train-dir", default=str(REPO / "results" / "recovery_train"))
    a = p.parse_args()
    results_dir = Path(a.results_dir)
    (results_dir / "recovery").mkdir(parents=True, exist_ok=True)
    cfgs = configs(a.train_dir)
    defn = definition(a.smoke, cfgs)
    path = heldout_path(results_dir, a.smoke)
    rows = load_rows(path, defn)
    seeds = SMOKE_SEEDS if a.smoke else SEEDS
    have = {(r["point"], r["config"], r["seed"]) for r in rows}
    todo = [(g, lbl, rec, s) for g in defn["grid"] for lbl, rec, _ in cfgs for s in seeds
            if (g, lbl, s) not in have]
    print(f"{len(cfgs)} configs ({len(cfgs) - 2} learned), {len(todo)} jobs to run ({len(have)} rows already on disk)")
    t0 = time.time()
    if todo:
        workers = ev.resolve_workers(a.workers, os.environ, len(todo))
        print(f"{len(todo)} jobs on {workers} workers")
        with mp.Pool(workers) as pool:
            for row in pool.imap_unordered(_job, todo):
                rows.append(row)
                _write(path, defn, rows)
    elif not path.exists():
        _write(path, defn, rows)
    out = results_dir / f"recovery_heldout{'_smoke' if a.smoke else ''}.png"
    plot(defn, rows, out)
    print(f"wrote {path}\nwrote {out}\ntotal {time.time() - t0:.1f} s")


if __name__ == "__main__":
    main()

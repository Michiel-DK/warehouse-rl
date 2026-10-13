"""Sprint 3 recovery sweeps: timeout baseline, tuned timeout grid, rule ladders, call-human cost. Resumable, multiprocess.

Usage: python scripts/recovery_sweep.py --workers N [--smoke] [--only a,b,c,d,e] [--results-dir DIR] [--best-rule B,R,A]
  a  timeout        {"name": "timeout"} (replan 5, abandon 15, cost 60)                                   1 config
  b  tuned_timeout  replan {3, 5, 8} x abandon {10, 15, 25}                                               9 configs
  c  rule           RuleRecovery (back_off, reroute, abandon) = (2, 5, 10) fast, (3, 6, 15) vendor-paced, (5, 10, 25)
                    patient                                                                              3 configs
  d  call_human     the "best rule" triple (a PLACEHOLDER default (3, 6, 15), not computed from sweep c; override with
                    --best-rule B,R,A, stored in the sweep definition) with call_human_after = A - 1 at costs
                    {0, 5, 15, 30, 60}, plus the same triple with no call-human rung as the reference         6 configs
  e  informed       InformedTimeoutRecovery (replan 5, abandon 15): "informed flag" (informed_timeout: reroute/abandon at
                    once when the robot on the next cell is frozen) and "informed left" (informed_timeout_left: only
                    when its remaining frozen run exceeds replan; optimistic look-ahead)                    2 configs
                    Its own queue item: the default --only stays a,b,c,d. Rows also carry
                    decisions_while_blocker_frozen / reroutes_while_blocker_frozen. Plot recovery_informed.png: pick-rate
                    with the timeout band read from recovery/timeout[_smoke].json (not recomputed), informed flag, informed
                    left, and the seed-paired delta vs timeout per rate.
Grid for every sweep: medium map, 8 AGVs + 4 pickers, AGV breakdown rate {1, 2, 4, 8} per robot-hour (sweep.py's
point_spec schedule, so it is identical to Sprint 2 and a function of (seed, config) only), seeds 0-29, 500 steps,
dispatcher StuckAwareCtaPolicy always. Full: a 120 + b 1080 + c 360 + d 720 = 2280 episodes (a-d), e 2 x 4 x 30 = 240 more. --smoke: seeds 0-1 and the
rates {1, 8}, files named <sweep>_smoke.json (a 4, b 36, c 12, d 24 = 76 episodes; e 2 x 2 x 2 = 8).
Each row is evaluate.run_seed(...) with the recovery config: pick_rate, deliveries, stuck/frozen/abandoned sums, every
per-action decision count (recovery_wait/back_off/reroute/abandon/call_human), event counts, fallbacks, call_human_steps
and the recovery config, plus point (rate), config (label) and n_agents.

call_human_cost is ACCOUNTING ONLY: it feeds call_human_steps and nothing else (relocation is instant), so the five
cost configs of sweep d have identical trajectories and identical pick-rates; the d curve is the pick-rate gained versus
the no-human reference against the human-steps spent. Whether the cost should be charged as real robot time is an
operator question. The hook's "reroute" is a re-plan, not a guaranteed other lane.

One mp.Pool over all pending (point, config, seed) jobs; only the parent writes, atomically, after every row, to
<results-dir>/recovery/<sweep>.json ({definition, rows}); rows already on disk are skipped, and a stored definition that
differs from the requested one raises. Plots <results-dir>/recovery_<sweep>.png: mean pick-rate with Student-t 95% CI
band; seed-paired delta vs the timeout rows of recovery/timeout[_smoke].json (empty, with a printed warning, when that
file is absent or shares no seeds); stuck-busy and abandoned per episode (sweep d: pick-rate delta vs the no-human
reference and call_human_steps per episode against cost). Timing is printed, not stored.
Workers: --workers (bare or empty = unset), else SCHED_WORKERS, else os.cpu_count() - 2.
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
from sweep import BREAKDOWN_DURATION, MEDIUM_8, SEEDS, SMOKE_SEEDS, STEPS, point_spec  # noqa: E402,F401

from warehouse_rl.recovery import RuleRecovery, normalise_recovery  # noqa: E402

RATES = [1, 2, 4, 8]
TUNED_REPLAN = [3, 5, 8]
TUNED_ABANDON = [10, 15, 25]
RULE_TRIPLES = [(2, 5, 10), (3, 6, 15), (5, 10, 25)]
DEFAULT_BEST_RULE = (3, 6, 15)  # placeholder, not computed from sweep c
HUMAN_COSTS = [0, 5, 15, 30, 60]
NO_HUMAN = "no human"
LETTERS = {"a": "timeout", "b": "tuned_timeout", "c": "rule", "d": "call_human", "e": "informed"}
DEFAULT_ONLY = "a,b,c,d"
AXIS = "AGV breakdown rate (onsets per robot-hour)"


def parse_best_rule(s):
    try:
        b, r, a = (int(x) for x in str(s).split(","))
    except ValueError:
        raise ValueError(f"--best-rule must be three comma-separated ints B,R,A, got {s!r}") from None
    try:
        RuleRecovery(b, r, a, a - 1)  # sweep d needs call_human_after = A - 1 inside (R, A)
    except ValueError as e:
        raise ValueError(f"--best-rule {s!r} is not usable for sweep d (needs 1 <= B < R < A - 1): {e}") from None
    return (b, r, a)


def _rule_cfg(triple, h=None, cost=None):
    cfg = dict(name="rule", back_off_after=triple[0], reroute_after=triple[1], abandon_after=triple[2],
               call_human_after=h)
    if cost is not None:
        cfg["call_human_cost"] = cost
    return normalise_recovery(cfg)


def _label_rule(t):
    return f"rule {t[0]}/{t[1]}/{t[2]}"


def configs(sweep, best_rule=DEFAULT_BEST_RULE):
    """[(label, normalised recovery config)] in grid order."""
    if sweep == "timeout":
        return [("timeout", normalise_recovery({"name": "timeout"}))]
    if sweep == "tuned_timeout":
        return [(f"tuned replan {r} abandon {a}",
                 normalise_recovery({"name": "tuned_timeout", "replan": r, "abandon": a}))
                for r in TUNED_REPLAN for a in TUNED_ABANDON]
    if sweep == "rule":
        return [(_label_rule(t), _rule_cfg(t)) for t in RULE_TRIPLES]
    if sweep == "call_human":
        t = tuple(best_rule)
        return ([(f"{_label_rule(t)} human cost {c}", _rule_cfg(t, t[2] - 1, c)) for c in HUMAN_COSTS]
                + [(f"{_label_rule(t)} {NO_HUMAN}", _rule_cfg(t))])
    if sweep == "informed":
        return [("informed flag", normalise_recovery({"name": "informed_timeout", "replan": 5, "abandon": 15})),
                ("informed left", normalise_recovery({"name": "informed_timeout_left", "replan": 5, "abandon": 15}))]
    raise ValueError(f"unknown sweep {sweep!r}")


def definition(sweep, smoke, best_rule=DEFAULT_BEST_RULE):
    d = dict(sweep=sweep, axis=AXIS, grid=[RATES[0], RATES[-1]] if smoke else list(RATES), steps=STEPS,
             env=MEDIUM_8, dispatcher="stuck_aware_cta",
             configs=[dict(label=lbl, recovery=cfg) for lbl, cfg in configs(sweep, best_rule)])
    if sweep == "call_human":
        d["best_rule"] = list(best_rule)
    return json.loads(json.dumps(d))


def sweep_path(results_dir, sweep, smoke):
    return Path(results_dir) / "recovery" / f"{sweep}{'_smoke' if smoke else ''}.json"


def _labels(defn):
    return [c["label"] for c in defn["configs"]]


def _write(path, defn, rows):
    labels = _labels(defn)
    rows = sorted(rows, key=lambda r: (defn["grid"].index(r["point"]), labels.index(r["config"]), r["seed"]))
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
    sweep, point, label, recovery, seed = args
    env_id, cfg, n_agents = point_spec("breakdown", point)
    row = ev.run_seed("stuck_aware_cta", env_id, STEPS, seed, disturb=cfg, recovery=recovery)
    row.pop("wall_s")  # timing stays out of the files
    return sweep, dict(point=point, config=label, n_agents=n_agents, **row)


def _timeout_rows(results_dir, smoke):
    p = sweep_path(results_dir, "timeout", smoke)
    if not p.exists():
        return None
    return json.loads(p.read_text())["rows"]


def plot(sweep, defn, rows, out, results_dir, smoke):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    grid, labels = defn["grid"], _labels(defn)
    cmap = plt.get_cmap("tab10")
    colors = {lbl: cmap(i % 10) for i, lbl in enumerate(labels)}
    human = sweep == "call_human"
    fig, axes = plt.subplots(1, 4 if human else 3, figsize=(20 if human else 15, 4.4), squeeze=False)
    axes = axes[0]

    def band(ax, xs, stats, label, color, ls="-"):
        ok = [(x, s) for x, s in zip(xs, stats) if s["n"]]
        if not ok:
            return
        x = [p[0] for p in ok]
        ax.plot(x, [s["mean"] for _, s in ok], ls, marker="o", color=color, label=label, markersize=3)
        ax.fill_between(x, [s["ci95_low"] for _, s in ok], [s["ci95_high"] for _, s in ok], color=color, alpha=0.15,
                        linewidth=0)

    def at(lbl, g):
        return [r for r in rows if r["config"] == lbl and r["point"] == g]

    base = _timeout_rows(results_dir, smoke)
    for lbl in labels:
        band(axes[0], grid, [ev.summarise([r["pick_rate"] for r in at(lbl, g)]) for g in grid], lbl, colors[lbl])
    if sweep == "informed" and base is not None:  # the stored timeout rows, not recomputed
        band(axes[0], grid, [ev.summarise([r["pick_rate"] for r in base if r["point"] == g]) for g in grid],
             "timeout", "black", ls="--")
    axes[0].set_title("mean pick-rate, 95% CI band")
    axes[0].set_ylabel("pick-rate (lines/h)")

    axes[1].axhline(0, color="grey", linewidth=0.8)
    axes[1].set_title("seed-paired delta vs timeout, 95% CI band")
    axes[1].set_ylabel("paired difference (lines/h)")
    if base is None:
        print(f"[{sweep}] warning: no {sweep_path(results_dir, 'timeout', smoke)}; delta panel left empty")
    else:
        stats = {lbl: [ev.paired_delta(at(lbl, g), [r for r in base if r["point"] == g]) for g in grid]
                 for lbl in labels}
        if not any(s["n"] for v in stats.values() for s in v):
            print(f"[{sweep}] warning: no common seeds with the timeout rows; delta panel left empty")
        for lbl in labels:
            band(axes[1], grid, stats[lbl], lbl, colors[lbl])

    for ax in axes[:2]:
        ax.set_xlabel(AXIS)
        ax.set_xscale("log", base=2)
        ax.set_xticks(grid)
        ax.set_xticklabels([str(g) for g in grid])
        ax.legend(fontsize=6)
    if human:
        costs = HUMAN_COSTS
        ref = f"{_label_rule(tuple(defn['best_rule']))} {NO_HUMAN}"
        by_cost = [f"{_label_rule(tuple(defn['best_rule']))} human cost {c}" for c in costs]
        for g in grid:
            d = [ev.paired_delta(at(lbl, g), at(ref, g)) for lbl in by_cost]
            band(axes[2], costs, d, f"rate {g}", cmap(grid.index(g)))
            h = [ev.summarise([r["call_human_steps"] for r in at(lbl, g)]) for lbl in by_cost]
            band(axes[3], costs, h, f"rate {g}", cmap(grid.index(g)))
        axes[2].axhline(0, color="grey", linewidth=0.8)
        axes[2].set_title("pick-rate delta vs no-human reference (flat: cost is accounting only)", fontsize=8)
        axes[2].set_ylabel("paired difference (lines/h)")
        axes[3].set_title("call_human_steps per episode", fontsize=9)
        axes[3].set_ylabel("human-steps")
        for ax in axes[2:]:
            ax.set_xlabel("call_human_cost")
            ax.legend(fontsize=7)
    else:
        for lbl in labels:
            band(axes[2], grid, [ev.summarise([r["stuck_busy_agent_steps"] for r in at(lbl, g)]) for g in grid],
                 f"{lbl}: stuck-busy", colors[lbl])
            band(axes[2], grid, [ev.summarise([r["abandoned_tasks"] for r in at(lbl, g)]) for g in grid],
                 f"{lbl}: abandoned", colors[lbl], ls="--")
        axes[2].set_xlabel(AXIS)
        axes[2].set_ylabel("agent-steps / tasks per episode")
        axes[2].set_title("stuck-busy (solid), abandoned (dashed), per episode", fontsize=9)
        axes[2].legend(fontsize=5)
    for ax in axes:
        ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=110)
    plt.close(fig)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--workers", type=ev.workers_arg, nargs="?", default=None)  # bare/empty = unset
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--only", default=DEFAULT_ONLY)
    p.add_argument("--results-dir", default=str(REPO / "results"))
    p.add_argument("--best-rule", default=None, help="B,R,A for sweep d (default 3,6,15)")
    a = p.parse_args()
    letters = [x.strip() for x in a.only.split(",") if x.strip()]
    if not letters or any(x not in LETTERS for x in letters):
        raise ValueError(f"--only must be a comma list from {sorted(LETTERS)}, got {a.only!r}")
    names = [LETTERS[x] for x in sorted(set(letters))]
    best = parse_best_rule(a.best_rule) if a.best_rule is not None else DEFAULT_BEST_RULE
    seeds = SMOKE_SEEDS if a.smoke else SEEDS
    results_dir = Path(a.results_dir)
    (results_dir / "recovery").mkdir(parents=True, exist_ok=True)

    state, jobs = {}, []
    for name in names:
        defn = definition(name, a.smoke, best)
        path = sweep_path(results_dir, name, a.smoke)
        rows = load_rows(path, defn)
        have = {(r["point"], r["config"], r["seed"]) for r in rows}
        todo = [(name, g, c["label"], c["recovery"], s) for g in defn["grid"] for c in defn["configs"] for s in seeds
                if (g, c["label"], s) not in have]
        state[name] = dict(defn=defn, path=path, rows=rows, todo=len(todo), done=0, last=None)
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
        plot(name, st["defn"], st["rows"], results_dir / f"recovery_{name}{'_smoke' if a.smoke else ''}.png",
             results_dir, a.smoke)
        print(f"[{name}] wrote {st['path']}")
    print(f"total {time.time() - t0:.1f} s")


if __name__ == "__main__":
    main()

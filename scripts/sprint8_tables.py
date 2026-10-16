"""Sprint 8 follow-up tables for the README, printed as markdown from the results JSONs (nothing is run, nothing retyped).

Usage: python scripts/sprint8_tables.py

Reads:
  results/closed_loop/summary.json, results/closed_loop_p06_09/summary.json, results/closed_loop_p08_095/summary.json,
  results/closed_loop_sticky/summary.json      -> (a) dose-response, one row per floor regime (30 seeds x 500 steps)
  results/closed_loop_sticky_1500/summary.json -> (b) the 1,500-step shift against 500 on the sticky regime
  results/guidance/sticky/{tune,best_transform,heldout}.json, plus the per-seed rows of map_tuned and of the
  closed_loop_sticky map_a4 / map_a32 arms     -> (c) guidance tuning, held-out verdict

The paired tuned-vs-fixed-map deltas are not in heldout.json (it pairs every arm against none only); they are computed
here with scripts/evaluate.py's own paired_delta (Student-t 95% CI, paired by seed), the same function heldout used.
Verdict rule: CI low > 0 -> beats; CI high < 0 -> worse; otherwise within noise. A missing file prints as missing.
"""
import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("evaluate_script", REPO / "scripts" / "evaluate.py")
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)

REGIMES = ["results/closed_loop", "results/closed_loop_p06_09", "results/closed_loop_p08_095",
           "results/closed_loop_sticky"]
STICKY, STICKY_1500 = "results/closed_loop_sticky", "results/closed_loop_sticky_1500"
GUIDANCE = "results/guidance/sticky"
ARMS = ["map_a4", "map_a32", "oracle"]


def load(rel):
    p = REPO / rel
    return json.loads(p.read_text()) if p.exists() else None


def p_range(summary):
    return "p %s-%s" % tuple(json.loads(summary["disturb"])["floor"]["p"])


def pick(arm):
    lo, hi = arm["pick_rate_ci95"]
    return f"{arm['pick_rate_mean']:.2f} ({lo:.2f}-{hi:.2f})"


def share(arm):
    s = arm.get("share_of_floor_loss_recovered") or {}
    if s.get("share") is None:
        return f"null ({s.get('reason')})" if s else "-"
    lo, hi = s["ci95"]
    return f"{100 * s['share']:.1f}% ({100 * lo:.1f}% to {100 * hi:.1f}%)"


def delta(d):
    lo, hi = d["ci95"] if "ci95" in d else (d["ci95_low"], d["ci95_high"])
    return f"{d['mean']:+.2f} ({lo:+.2f} to {hi:+.2f})"


def verdict(d):
    lo, hi = d["ci95"] if "ci95" in d else (d["ci95_low"], d["ci95_high"])
    return "beats" if lo > 0 else "worse" if hi < 0 else "within noise"


def loss(summary):
    for a in summary["arms"].values():
        s = a.get("share_of_floor_loss_recovered")
        if s:
            return s["mean_loss"]
    return None


def dose_response():
    print("| floor regime (80 cells) | floor loss (lines/h) | none | map_a4 | map_a4 share | map_a32 | map_a32 share "
          "| oracle (alpha 4) | oracle share |")
    print("|---|---|---|---|---|---|---|---|---|")
    for rel in REGIMES:
        s = load(f"{rel}/summary.json")
        if s is None:
            print(f"| `{rel}/summary.json` MISSING | | | | | | | | |")
            continue
        assert s["n_seeds"] == 30 and s["steps"] == 500, (rel, s["n_seeds"], s["steps"])
        arms = s["arms"]
        cells = [p_range(s), f"{loss(s):.2f}", pick(arms["none"])]
        for name in ARMS:
            cells += [pick(arms[name]), share(arms[name])] if name in arms else ["missing", "missing"]
        print("| " + " | ".join(cells) + " |")
    print()
    print("Pick-rate in lines/h, mean (95% CI). Share = mean(arm - none) / mean(undisturbed - none), paired per seed, "
          "with a 1000-resample seed-bootstrap CI. Sources: " + ", ".join(f"`{r}/summary.json`" for r in REGIMES) + ".")


def long_shift():
    s5, s15 = load(f"{STICKY}/summary.json"), load(f"{STICKY_1500}/summary.json")
    if s5 is None or s15 is None:
        print(f"1,500-step line: MISSING {'' if s5 else STICKY + '/summary.json '}{'' if s15 else STICKY_1500 + '/summary.json'}")
        return
    parts = []
    for name in ARMS:
        parts.append(f"{name} {share(s5['arms'][name])} at 500 -> {share(s15['arms'][name])} at 1,500")
    print(f"**1,500-step shift, sticky regime ({p_range(s15)}, 30 seeds).** Floor loss {loss(s5):.2f} lines/h at "
          f"{s5['steps']} steps, {loss(s15):.2f} at {s15['steps']}. Share of the loss recovered: " + "; ".join(parts)
          + f". Phase A maps differ (tag `{s5['map_tag']}` from a 500-step day, `{s15['map_tag']}` from a 1,500-step "
          f"day); there is no paired 500-vs-1,500 CI. Sources: `{STICKY}/summary.json`, `{STICKY_1500}/summary.json`.")


def _rows(path, seeds):
    doc = json.loads(Path(path).read_text())
    by = {r["seed"]: r for r in doc["rows"]}
    missing = [s for s in seeds if s not in by]
    if missing:
        raise ValueError(f"{path} lacks seeds {missing}")
    return [by[s] for s in seeds]


def _arm_file(rel_dir):
    files = sorted((REPO / rel_dir).glob("*.json"))
    if len(files) != 1:
        raise ValueError(f"expected one results JSON in {rel_dir}, found {[f.name for f in files]}")
    return files[0]


def guidance():
    tune, best, held = (load(f"{GUIDANCE}/{n}.json") for n in ("tune", "best_transform", "heldout"))
    missing = [n for n, d in (("tune", tune), ("best_transform", best), ("heldout", held)) if d is None]
    if missing:
        print("Guidance tuning: MISSING " + ", ".join(f"`{GUIDANCE}/{n}.json`" for n in missing))
        return
    evals = tune["evaluations"]
    ident = evals[0]
    p = best["params"]
    print(f"**Train (seeds {min(tune['train_seeds'])}-{max(tune['train_seeds'])}, {len(evals)} evaluations, random "
          f"search seed {tune['search_seed']}).** Objective = mean paired pick-rate gain over none on the train seeds. "
          f"Identity (eval 0, alpha {ident['params']['alpha']:g}, gamma {ident['params']['gamma']:g}, tau "
          f"{ident['params']['tau']:g}, dilate {ident['params']['dilate']}) {ident['objective']:+.3f}; best (eval "
          f"{best['index']}: alpha {p['alpha']:.1f}, gamma {p['gamma']:.2f}, tau {p['tau']:.3f}, dilate {p['dilate']}) "
          f"{best['objective']:+.3f} lines/h.")
    ins = held["in_sample"]["arms"]
    print(f"Check: identity objective {ident['objective']:+.3f} vs in-sample map_a4 delta "
          f"{ins['map_a4']['paired_delta_vs_none']['mean']:+.3f}; best objective {best['objective']:+.3f} vs in-sample "
          f"map_tuned delta {ins['map_tuned']['paired_delta_vs_none']['mean']:+.3f}.")
    print()
    ho = held["arms"]
    hs, ts = held["heldout_seeds"], held["in_sample"]["seeds"]
    print(f"| arm | held-out seeds {min(hs)}-{max(hs)} (n={len(hs)}): delta vs none (95% CI) | held-out share (95% CI) "
          f"| in-sample seeds {min(ts)}-{max(ts)} (n={len(ts)}): delta vs none (95% CI) | verdict vs none, held-out |")
    print("|---|---|---|---|---|")
    for name in ("map_a4", "map_a32", "map_tuned", "oracle"):
        h, i = ho[name], ins[name]
        print(f"| {name} | {delta(h['paired_delta_vs_none'])} | {share(h)} | {delta(i['paired_delta_vs_none'])} "
              f"| {verdict(h['paired_delta_vs_none'])} |")
    print()
    base = held["baseline_dir"]
    tuned_file = REPO / held["map_tuned_results_file"]  # held-out seeds only
    train_file = REPO / best["eval_results_file"]  # the chosen eval's train-seed rows (train zones only)
    print("| paired delta | held-out (95% CI) | verdict | in-sample (95% CI) |")
    print("|---|---|---|---|")
    for other in ("map_a4", "map_a32"):
        other_file = _arm_file(f"{base}/{other}")
        out = []
        for f, seeds in ((tuned_file, hs), (train_file, ts)):
            out.append(ev.paired_delta(_rows(f, seeds), _rows(other_file, seeds), seeds))
        print(f"| map_tuned - {other} | {delta(out[0])} | {verdict(out[0])} | {delta(out[1])} |")
    print()
    print(f"Sources: `{GUIDANCE}/tune.json`, `{GUIDANCE}/best_transform.json`, `{GUIDANCE}/heldout.json`; the paired "
          f"tuned-vs-fixed rows are computed by `scripts/sprint8_tables.py` from `{held['map_tuned_results_file']}` "
          f"(held-out), `{best['eval_results_file']}` (in-sample) and `{base}/{{map_a4,map_a32}}/*.json` with "
          f"`evaluate.paired_delta`.")


def main():
    print("### (a) Dose-response: map benefit by floor stickiness (30 seeds x 500 steps)\n")
    dose_response()
    print("\n### (b) Longer shift\n")
    long_shift()
    print("\n### (c) Guidance tuning (S8M), sticky regime\n")
    guidance()


if __name__ == "__main__":
    sys.exit(main())

"""Sprint 8 follow-up tables for the README, printed as markdown from the results JSONs (nothing is run, nothing retyped).

Usage: python scripts/sprint8_tables.py

Reads:
  results/closed_loop/summary.json, results/closed_loop_p06_09/summary.json, results/closed_loop_p08_095/summary.json,
  results/closed_loop_sticky/summary.json      -> (a) dose-response, one row per floor regime (30 seeds x 500 steps),
                                                  alphas 4/8/16/32 where the summary has them, plus the per-seed rows
                                                  of each fixed-alpha arm for the paired between-alpha deltas
  results/closed_loop_sticky_1500/summary.json -> (b) the 1,500-step shift against 500 on the sticky regime
  results/guidance/{sticky,p08_095}/{tune,best_transform,heldout}.json, plus the per-seed rows of map_tuned and of the
  baseline map_a4 / map_a32 arms               -> (c) guidance tuning, held-out verdict, per regime
  results/fleet/time_to_detect_sticky{500,1500}.json -> (d) time to detect per top-K
  results/fleet/hotspot_s8e-long-w{0.2,0.5,1.0}.json -> (e) lesson_persist against its chance rate
  results/fleet/hotspot_s10-{blocked,outage,breakdown,burst}.json -> (f) the analyser on other disturbances
                                                  (`truth_kinds`, flagged cells per zone, `lesson_persist_chance`)
  results/fleet/time_to_detect_{blocked,outage}.json -> (g) time to detect and time to clear per window kind
  results/fleet/hotspot_s10c-blind.json, results/fleet/time_to_detect_blind.json -> (h) planner-blind blockage next to
                                                  the known blockage of (f) and (g), same 50 windows
  results/fleet/hotspot_s10-none.json, results/fleet/amoc_blind.json (reference rows) -> (i) the undisturbed reference:
                                                  flagged cells and false alarms per hour by K next to the disturbed runs
  results/fleet/baselines_{s8b-medium-80-p03-07,closed-loop-sticky,s8e-long-w0.5,s10c-blind,s10-none}.json
                                               -> (j) map versus persistence (`baselines` block, S10D)
  results/fleet/amoc_blind.json                -> (k) AMOC: delay, misses and false alarms per hour by K and by cost

The paired tuned-vs-fixed-map and between-alpha deltas are not in the JSONs (they pair every arm against none only);
they are computed here with scripts/evaluate.py's own paired_delta (Student-t 95% CI, paired by seed), the same
function heldout used.
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
GUIDANCES = ["results/guidance/sticky", "results/guidance/p08_095"]
ARMS = ["map_a4", "map_a32", "oracle"]
ALPHA_ARMS = ["map_a4", "map_a8", "map_a16", "map_a32"]
TTD = ["results/fleet/time_to_detect_sticky500.json", "results/fleet/time_to_detect_sticky1500.json"]
LESSONS = [f"results/fleet/hotspot_s8e-long-w{w}.json" for w in ("0.2", "0.5", "1.0")]
S10 = [f"results/fleet/hotspot_s10-{k}.json" for k in ("blocked", "outage", "breakdown", "burst")]
TTD_WINDOWS = ["results/fleet/time_to_detect_blocked.json", "results/fleet/time_to_detect_outage.json"]
BLIND, KNOWN = "results/fleet/hotspot_s10c-blind.json", "results/fleet/hotspot_s10-blocked.json"
TTD_BLIND = "results/fleet/time_to_detect_blind.json"
NONE = "results/fleet/hotspot_s10-none.json"
AMOC = "results/fleet/amoc_blind.json"
BASELINES = [f"results/fleet/baselines_{t}.json" for t in ("s8b-medium-80-p03-07", "closed-loop-sticky", "s8e-long-w0.5",
                                                           "s10c-blind", "s10-none")]
S8B_COMMITTED = "results/fleet/hotspot_s8b-medium-80-p03-07.json"
REF_KS = ("10", "20", "40")
CELL_KINDS = ("floor", "blocked", "outage")
S10_KS = ("20", "40")
SECONDS_PER_STEP = 5


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
    loaded = [(rel, load(f"{rel}/summary.json")) for rel in REGIMES]
    print("| floor regime (80 cells) | floor loss (lines/h) | none (lines/h) | map_a4 share | map_a8 share "
          "| map_a16 share | map_a32 share | oracle (alpha 4) share |")
    print("|---|---|---|---|---|---|---|---|")
    for rel, s in loaded:
        if s is None:
            print(f"| `{rel}/summary.json` MISSING | | | | | | | |")
            continue
        assert s["n_seeds"] == 30 and s["steps"] == 500, (rel, s["n_seeds"], s["steps"])
        arms = s["arms"]
        cells = [p_range(s), f"{loss(s):.2f}", pick(arms["none"])]
        cells += [share(arms[n]) if n in arms else "-" for n in ALPHA_ARMS + ["oracle"]]
        print("| " + " | ".join(cells) + " |")
    print()
    print("Pick-rate by arm, lines/h, mean (95% CI):\n")
    print("| floor regime | " + " | ".join(ALPHA_ARMS) + " | oracle | undisturbed |")
    print("|---|" + "---|" * (len(ALPHA_ARMS) + 2))
    for rel, s in loaded:
        if s is not None:
            arms = s["arms"]
            print(f"| {p_range(s)} | " + " | ".join(pick(arms[n]) if n in arms else "-"
                                                      for n in ALPHA_ARMS + ["oracle", "undisturbed"]) + " |")
    print()
    print("Paired between fixed alphas (the arm with the highest mean pick-rate in each regime minus each other fixed "
          "alpha, lines/h, 95% CI):\n")
    print("| floor regime | top fixed alpha (point estimate) | minus | delta (95% CI) | verdict |")
    print("|---|---|---|---|---|")
    for rel, s in loaded:
        if s is None:
            continue
        present = [n for n in ALPHA_ARMS if n in s["arms"]]
        top = max(present, key=lambda n: s["arms"][n]["pick_rate_mean"])
        seeds = list(range(s["n_seeds"]))
        top_rows = _rows(_arm_file(f"{rel}/{top}"), seeds)
        for other in present:
            if other == top:
                continue
            d = ev.paired_delta(top_rows, _rows(_arm_file(f"{rel}/{other}"), seeds), seeds)
            print(f"| {p_range(s)} | {top} | {other} | {delta(d)} | {verdict(d)} |")
    print()
    print("Share = mean(arm - none) / mean(undisturbed - none), paired per seed, with a 1000-resample seed-bootstrap CI; "
          "\"-\" = the regime's summary has no such arm. Ties in the top-alpha pick use the first in alpha order. "
          "Sources: " + ", ".join(f"`{r}/summary.json`" for r in REGIMES) + "; the between-alpha rows are computed by "
          "`scripts/sprint8_tables.py` from `<regime>/<arm>/*.json` with `evaluate.paired_delta`.")


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


def guidance(GUIDANCE):
    tune, best, held = (load(f"{GUIDANCE}/{n}.json") for n in ("tune", "best_transform", "heldout"))
    missing = [n for n, d in (("tune", tune), ("best_transform", best), ("heldout", held)) if d is None]
    if missing:
        print("Guidance tuning: MISSING " + ", ".join(f"`{GUIDANCE}/{n}.json`" for n in missing))
        return None
    evals = tune["evaluations"]
    ident = evals[0]
    assert ident["params"] == {"alpha": 4.0, "gamma": 1.0, "tau": 0.0, "dilate": 0}, ident["params"]
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
    side = {"map_tuned - none": (ho["map_tuned"]["paired_delta_vs_none"], ins["map_tuned"]["paired_delta_vs_none"])}
    for other in ("map_a4", "map_a32"):
        other_file = _arm_file(f"{base}/{other}")
        out = []
        for f, seeds in ((tuned_file, hs), (train_file, ts)):
            out.append(ev.paired_delta(_rows(f, seeds), _rows(other_file, seeds), seeds))
        print(f"| map_tuned - {other} | {delta(out[0])} | {verdict(out[0])} | {delta(out[1])} |")
        side[f"map_tuned - {other}"] = tuple(out)
    print()
    print(f"Sources: `{GUIDANCE}/tune.json`, `{GUIDANCE}/best_transform.json`, `{GUIDANCE}/heldout.json`; the paired "
          f"tuned-vs-fixed rows are computed by `scripts/sprint8_tables.py` from `{held['map_tuned_results_file']}` "
          f"(held-out), `{best['eval_results_file']}` (in-sample) and `{base}/{{map_a4,map_a32}}/*.json` with "
          f"`evaluate.paired_delta`.")
    return p_range({"disturb": held["disturb"]}), p["alpha"], side


def guidance_side_by_side(results):
    results = [r for r in results if r is not None]
    if not results:
        return
    print("| held-out seeds 10-29, paired | " + " | ".join(f"{pr} (tuned alpha {a:.2f})" for pr, a, _ in results)
          + " |")
    print("|---|" + "---|" * len(results))
    for key in results[0][2]:
        print(f"| {key} | " + " | ".join(f"{delta(side[key][0])} **{verdict(side[key][0])}** (in-sample "
                                          f"{delta(side[key][1])})" for _, _, side in results) + " |")


def time_to_detect():
    docs = [(rel, load(rel)) for rel in TTD]
    for rel, d in docs:
        if d is None:
            print(f"Time to detect: `{rel}` MISSING")
    docs = [(rel, d) for rel, d in docs if d is not None]
    if not docs:
        return
    head = ["K (per zone)"]
    for _, d in docs:
        m = d["meta"]
        head += [f"{m['steps']} steps: truth cells seen by shift end", f"{m['steps']} steps: first detect, min, "
                 "median (p25-p75)", f"{m['steps']} steps: false flags per publish, 30 zones summed (per zone)"]
    print("| " + " | ".join(head) + " |")
    print("|---|" + "---|" * (len(head) - 1))
    ks = docs[0][1]["meta"]["top_k"]
    for k in ks:
        cells = [str(k)]
        for _, d in docs:
            sm = d["by_k"][str(k)]["summary"]
            f = sm["first_detect_s"]
            nz = len(d["meta"]["zones"])
            cells += [f"{100 * sm['share_detected_end']:.1f}%",
                      f"{f['median'] / 60:.0f} ({f['p25'] / 60:.0f}-{f['p75'] / 60:.0f})",
                      f"{sm['false_flags_per_publish_mean']:.1f} ({sm['false_flags_per_publish_mean'] / nz:.2f})"]
        print("| " + " | ".join(cells) + " |")
    print()
    for rel, d in docs:
        m = d["meta"]
        n_truth = sum(d["by_k"][str(ks[0])]["summary"][b]["n_truth"] for b in ("p_ge_0.95", "p_lt_0.95"))
        print(f"- `{rel}`: {m['steps']} steps = {m['steps'] * SECONDS_PER_STEP / 60:.1f} simulated min, "
              f"{len(m['zones'])} zones, {n_truth} truth cells, {m['n_publishes']} publishes every "
              f"{m['publish_every_s'] / 60:g} min, {m['disturb']}, phase A `{m['phase_a_dir']}`.")
    print()
    print("Times are simulated minutes since the zone's first message, over the detected cells only, so they move in "
          "steps of the publish cadence; K is the per-zone top-K of the hotspot map; a false flag is a top-K cell that "
          "is not a truth cell. Caveat (verbatim from the JSON): \"" + docs[0][1]["meta"]["caveat"] + "\"")


def lesson_persist_chance():
    print("| run tag (lesson window, h) | lessons graded (by kind) | persisted (observed rate) | chance mean "
          "(median) | lift |")
    print("|---|---|---|---|---|")
    for rel in LESSONS:
        d = load(rel)
        if d is None:
            print(f"| `{rel}` MISSING | | | | |")
            continue
        c = d["lesson_persist_chance"]
        kinds = d["lesson_grading"]["lesson_persist"]
        by_kind = ", ".join(f"{k} {v.get('ok', 0)} ok / {v.get('off', 0)} off" for k, v in sorted(kinds.items()))
        lift = "n/a" if c["lift"] is None else f"{c['lift']:.2f}"
        print(f"| {d['tag']} | {c['n_lessons']} ({by_kind}) | {c['observed_ok']} ({c['observed_rate']:.3f}) "
              f"| {c['chance_mean']:.3f} ({c['chance_median']:.3f}) | {lift} |")
    print()
    print("Chance = for each lesson, the share of its own candidate pool (every cell with >= 1 stall, or every robot "
          "with >= 1 episode, in the lesson's zone and window) that persists over the next window by the same bar; "
          "lift = observed rate / chance mean. Pools are shared between lessons of the same zone and window, and there "
          "is no CI on the lift. The window is the `--window-h` named in the run tag. Sources: "
          + ", ".join(f"`{r}`" for r in LESSONS) + " (`lesson_persist_chance`, `lesson_grading.lesson_persist`).")


def _s10_docs():
    docs = []
    for rel in S10:
        d = load(rel)
        if d is None:
            print(f"S10: `{rel}` MISSING")
        else:
            docs.append((rel, d))
    return docs


def _flagged(d, k):
    """Top-K cells summed over zones, and the zones that flag fewer than K cells (the precision denominator is still
    K * zones)."""
    n = [z["n_flagged"] for z in d["zones"].values()]
    return sum(min(int(k), x) for x in n), sum(1 for x in n if x < int(k))


def other_disturbances():
    docs = _s10_docs()
    if not docs:
        return
    print("Truth positives per run (cells are counted once per kind over the whole run, robots by distinct serial):\n")
    print("| run | disturbance | floor cells | blocked cells | outage cells | frozen robots | flagged cells per zone, "
          "mean |")
    print("|---|---|---|---|---|---|---|")
    for _, d in docs:
        tk = d["truth_kinds"]
        print(f"| {d['tag']} | `{json.dumps(d['config']['disturb'])}` | "
              + " | ".join(str(tk[k]["positives"]) for k in CELL_KINDS)
              + f" | {tk['frozen']['positives']} | {d['mean']['n_flagged']:.1f} |")
    print()
    print("Precision and recall at K, split by kind (only kinds with positives in the run; pooled over zones):\n")
    print("| run | kind | positives | " + " | ".join(f"K {k}: hits, precision, recall" for k in S10_KS)
          + " | zones flagging fewer than K cells (" + " / ".join(f"K {k}" for k in S10_KS) + ") |")
    print("|---|---|---|" + "---|" * len(S10_KS) + "---|")
    for _, d in docs:
        tk = d["truth_kinds"]
        short = " / ".join(str(_flagged(d, k)[1]) for k in S10_KS)
        kinds = [k for k in CELL_KINDS if tk[k]["positives"] > 0]
        for kind in kinds:
            cells = []
            for k in S10_KS:
                e = tk[kind]["k"][k]
                cells.append(f"{e['hits']}, {e['precision']:.4f}, {e['recall']:.2f}")
            print(f"| {d['tag']} | {kind} | {tk[kind]['positives']} | " + " | ".join(cells) + f" | {short} |")
        if not kinds:
            why = (f"{tk['frozen']['positives']} frozen robots; the map ranks cells" if tk["frozen"]["positives"]
                   else "the run has no truth cells")
            print(f"| {d['tag']} | none | 0 cells ({why}) | " + " | ".join("n/a" for _ in S10_KS) + f" | {short} |")
    print()
    print("False flags (top-K cells that are not a truth cell of any kind, summed over 10 zones, on the final map) and "
          "the forecast truth grades:\n")
    print("| run | " + " | ".join(f"K {k}: false flags (per zone)" for k in S10_KS)
          + " | hotspot_forecast truth grades: false_alarm / graded |")
    print("|---|" + "---|" * len(S10_KS) + "---|")
    for _, d in docs:
        nz = len(d["zones"])
        cells = []
        for k in S10_KS:
            flagged, _ = _flagged(d, k)
            ff = flagged - d["truth_kinds"]["any"]["k"][k]["hits"]
            cells.append(f"{ff} ({ff / nz:.1f})")
        t = d["grading_counts"].get("truth", {})
        print(f"| {d['tag']} | " + " | ".join(cells) + f" | {t.get('false_alarm', 0)} / {sum(t.values())} |")
    print()
    print("lesson_persist and its chance rate:\n")
    print("| run | stream length (s) | lesson_truth grades (by lesson kind) | lesson_persist graded | observed rate "
          "| chance mean | lift |")
    print("|---|---|---|---|---|---|---|")
    for _, d in docs:
        c = d["lesson_persist_chance"]
        lt = d["lesson_grading"].get("lesson_truth", {})
        by_kind = ", ".join(f"{k} " + ", ".join(f"{n} {v}" for v, n in sorted(vs.items()))
                            for k, vs in sorted(lt.items())) or "none"
        rate = "n/a" if c["observed_rate"] is None else f"{c['observed_rate']:.3f}"
        chance = "n/a" if c["chance_mean"] is None else f"{c['chance_mean']:.3f}"
        lift = "n/a" if c["lift"] is None else f"{c['lift']:.2f}"
        print(f"| {d['tag']} | {d['config']['steps'] * SECONDS_PER_STEP} | {by_kind} | {c['n_lessons']} | {rate} "
              f"| {chance} | {lift} |")
    print()
    print("`truth_kinds` is run-level: a cell is positive for a kind if the truth lists it at any time in the run, "
          "and the map is the final one, so a hit does not mean the cell was flagged while it was blocked (time is in "
          "(g)). Precision = hits / (K x zones), so zones that flag fewer than K cells still count K. false flags = "
          "sum over zones of min(K, flagged cells) minus the `any` hits. The floor-based `mean.k` block of these JSONs "
          "is not used: no S10 run has floor cells. lesson_persist grades a lesson with window [s, e) over [e, e + W) "
          "only when the zone's stream reaches e + W (`fleet/fleet_analyser/lessons.py` docstring); the queue item "
          "`wr-s10-disturbance-measure` ran lessons with `--window-h 0.5` (1800 s), so a 2500 s stream allows no "
          "graded lesson. Sources: " + ", ".join(f"`{r}`" for r, _ in docs)
          + " (`truth_kinds`, `zones.*.n_flagged`, `grading_counts.truth`, `lesson_grading`, "
          "`lesson_persist_chance`).")


def _q(f):
    if f["median"] is None:
        return "none"
    return f"{f['median']:g} ({f['p25']:g}-{f['p75']:g})"


def detect_and_clear():
    docs = []
    for rel in TTD_WINDOWS:
        d = load(rel)
        if d is None:
            print(f"Time to detect and clear: `{rel}` MISSING")
        else:
            docs.append((rel, d))
    if not docs:
        return
    print("| kind | K (per zone) | windows | detected (share) | missed | preflag | first detect, s, median (p25-p75) "
          "| cleared | cleared, s after end, median (p25-p75) | stale_at_end | open_at_end | false flags per publish, "
          "10 zones summed (per zone) |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for _, d in docs:
        m = d["meta"]
        nz = len(m["zones"])
        for k in m["top_k"]:
            e = d["by_k"][str(k)]
            sm = e["summary"]
            wins = [w for ws in e["windows"].values() for w in ws]
            assert len(wins) == sm["n_windows"], (m["truth_kind"], k)
            n_cleared = sum(1 for w in wins if w["cleared_s"] is not None)
            assert n_cleared == sm["n_detected"] - sm["stale_at_end"] - sm["open_at_end"], (m["truth_kind"], k)
            assert sum(1 for w in wins if w["detected"]) == sm["n_detected"], (m["truth_kind"], k)
            ff = sm["false_flags_per_publish_mean"]
            print(f"| {m['truth_kind']} | {k} | {sm['n_windows']} | {sm['n_detected']} ({sm['share_detected']:.2f}) "
                  f"| {sm['missed']} | {sm['preflag']} | {_q(sm['first_detect_s'])} | {n_cleared} "
                  f"| {_q(sm['cleared_s'])} | {sm['stale_at_end']} | {sm['open_at_end']} | {ff:.1f} ({ff / nz:.2f}) |")
    print()
    for rel, d in docs:
        m = d["meta"]
        print(f"- `{rel}`: {m['truth_kind']}, run `{m['run']}`, {m['steps']} steps = "
              f"{m['steps'] * SECONDS_PER_STEP / 60:.1f} simulated min, {len(m['zones'])} zones, {m['n_windows']} "
              f"windows (median length {m['window_len_steps_median']:g} steps), {m['n_publishes']} publishes every "
              f"{m['publish_every_s'] / 60:g} min, `{json.dumps(m['disturb'])}`, phase A `{m['phase_a_dir']}`.")
    print()
    print("Per window: detected = the cell is in the zone's top K at a publish while the window is open; preflag = in "
          "the top K at the last publish before the window opened (not a detection); first detect is seconds from "
          "the window's start. Over detected windows only: cleared = the first publish at or after the end where the "
          "cell is out of the top K (seconds from the end); stale_at_end = still in the top K at every publish after "
          "the end; open_at_end = no publish after the end, so clearing is not observed. cleared = detected - "
          "stale_at_end - open_at_end (asserted here). \"none\" = no window to take a median over. A flag counts as "
          "false only when the cell matches no truth window of any kind at that publish. Caveat (verbatim from the "
          "JSON): \"" + docs[0][1]["meta"]["caveat"] + "\"")


def _load_all(rels, what):
    out = []
    for rel in rels:
        d = load(rel)
        if d is None:
            print(f"{what}: `{rel}` MISSING")
        else:
            out.append((rel, d))
    return out


def _windows(d, k):
    return [(z, w) for z, ws in sorted(d["by_k"][k]["windows"].items()) for w in ws]


def blind_blockage():
    docs = _load_all([KNOWN, BLIND, TTD_WINDOWS[0], TTD_BLIND], "Blind blockage")
    if len(docs) < 4:
        return
    (_, hk), (_, hb), (_, tk), (_, tb) = docs
    assert tk["meta"]["truth_kind"] == tb["meta"]["truth_kind"] == "blocked"
    print("Final map (run-level, as in (f)):\n")
    print("| run | planner knows the cell | blocked cells | " + " | ".join(f"K {k}: hits, precision, recall"
                                                                       for k in S10_KS)
          + " | " + " | ".join(f"K {k}: false flags (per zone)" for k in S10_KS)
          + " | hotspot_forecast truth grades: hit / graded |")
    print("|---|---|---|" + "---|" * (2 * len(S10_KS)) + "---|")
    for d in (hk, hb):
        tk_ = d["truth_kinds"]
        known = d["config"]["disturb"]["blocked_cell"].get("known", True)
        nz = len(d["zones"])
        hits = [f"{tk_['blocked']['k'][k]['hits']}, {tk_['blocked']['k'][k]['precision']:.4f}, "
                f"{tk_['blocked']['k'][k]['recall']:.2f}" for k in S10_KS]
        ffs = []
        for k in S10_KS:
            ff = _flagged(d, k)[0] - tk_["any"]["k"][k]["hits"]
            ffs.append(f"{ff} ({ff / nz:.1f})")
        t = d["grading_counts"].get("truth", {})
        print(f"| {d['tag']} | {'yes' if known else 'no'} | {tk_['blocked']['positives']} | " + " | ".join(hits)
              + " | " + " | ".join(ffs) + f" | {t.get('hit', 0)} / {sum(t.values())} |")
    print()
    print("Over time (as in (g)), the same 50 windows on both runs:\n")
    print("| K (per zone) | run | detected (share) | missed | preflag | first detect, s, median (p25-p75) | cleared "
          "| stale_at_end | open_at_end | false flags per publish, 10 zones summed (per zone) |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    ks = [k for k in map(str, tk["meta"]["top_k"]) if k in tb["by_k"]]
    for k in ks:
        wk, wb = _windows(tk, k), _windows(tb, k)
        assert [(z, w["cell"], w["start_step"], w["end_step"]) for z, w in wk] == \
               [(z, w["cell"], w["start_step"], w["end_step"]) for z, w in wb], k
        for d in (tk, tb):
            sm = d["by_k"][k]["summary"]
            nz = len(d["meta"]["zones"])
            n_cleared = sum(1 for _, w in _windows(d, k) if w["cleared_s"] is not None)
            ff = sm["false_flags_per_publish_mean"]
            print(f"| {k} | {d['meta']['run']} | {sm['n_detected']} ({sm['share_detected']:.2f}) | {sm['missed']} "
                  f"| {sm['preflag']} | {_q(sm['first_detect_s'])} | {n_cleared} | {sm['stale_at_end']} "
                  f"| {sm['open_at_end']} | {ff:.1f} ({ff / nz:.2f}) |")
    print()
    print("Paired by window (same cell, start and end on both runs):\n")
    print("| K (per zone) | detected on both | known only | blind only | neither |")
    print("|---|---|---|---|---|")
    for k in ks:
        pairs = list(zip(_windows(tk, k), _windows(tb, k)))
        c = [sum(1 for (_, a), (_, b) in pairs if (a["detected"], b["detected"]) == want)
             for want in ((True, True), (True, False), (False, True), (False, False))]
        assert sum(c) == len(pairs)
        print(f"| {k} | " + " | ".join(map(str, c)) + " |")
    print()
    print(f"Both runs use `rate_per_hour` {tb['meta']['disturb']['blocked_cell']['rate_per_hour']:g} and duration "
          f"{tb['meta']['disturb']['blocked_cell']['duration']}, seeds 0-9, 500 steps; `known` is removed before the "
          "schedule is hashed (S10C), so the windows are identical (asserted here). With `known: false` the planner does "
          "not see the cell, a move into it is NOOPed and the robot is hidden from the StuckCounter, like a floor cell "
          "with p = 1 while the window is open. Sources: " + ", ".join(f"`{r}`" for r, _ in docs) + ".")


def _fa_per_hour(ff_per_publish_summed, n_publishes, n_zones, steps):
    return ff_per_publish_summed * n_publishes / (n_zones * steps * SECONDS_PER_STEP / 3600)


def undisturbed_reference():
    s10 = _load_all([NONE] + S10 + [BLIND], "Undisturbed reference")
    amoc = load(AMOC)
    if amoc is None:
        print(f"Undisturbed reference: `{AMOC}` MISSING")
    print("Final map (run-level; false flags = top-K cells that are not a truth cell of any kind):\n")
    print("| run | disturbance | flagged cells per zone, mean | " + " | ".join(f"K {k}: false flags (per zone)"
                                                                         for k in S10_KS) + " |")
    print("|---|---|---|" + "---|" * len(S10_KS))
    for _, d in s10:
        nz = len(d["zones"])
        cells = []
        for k in S10_KS:
            ff = _flagged(d, k)[0] - d["truth_kinds"]["any"]["k"][k]["hits"]
            cells.append(f"{ff} ({ff / nz:.1f})")
        print(f"| {d['tag']} | `{json.dumps(d['config']['disturb'])}` | {d['mean']['n_flagged']:.1f} | "
              + " | ".join(cells) + " |")
    print()
    if amoc is None:
        return
    m = amoc["meta"]
    ref_k = {str(r["K"]): r for r in amoc["amoc"]["k"]}
    ttd = _load_all(TTD_WINDOWS + [TTD_BLIND], "Undisturbed reference")
    for _, d in ttd:
        if d["meta"]["run"] == m["run"]:
            for k in REF_KS:
                sm = d["by_k"][k]["summary"]
                got = _fa_per_hour(sm["false_flags_per_publish_mean"], d["meta"]["n_publishes"],
                                   len(d["meta"]["zones"]), d["meta"]["steps"])
                assert abs(got - ref_k[k]["fa_per_hour_measured_outside_windows"]) < 1e-6, (k, got)
    nz_ref = len(m["zones"])
    print("Per publish (9 publishes every 5 min, the last at stream end), false flags per zone per publish and false "
          "alarms per zone per simulated hour:\n")
    head = [f"{m['reference_run']} (undisturbed, every flag is false)"] + [d["meta"]["run"] for _, d in ttd]
    print("| K (per zone) | " + " | ".join(f"{h}: per publish, per hour" for h in head) + " |")
    print("|---|" + "---|" * len(head))
    for k in REF_KS:
        r = ref_k[k]
        per_pub = r["fa_per_hour_reference"] * m["sim_hours_reference"] / m["n_publishes_reference"]
        cells = [f"{per_pub:.2f}, {r['fa_per_hour_reference']:.1f}"]
        for _, d in ttd:
            sm = d["by_k"][k]["summary"]
            nz = len(d["meta"]["zones"])
            fa = _fa_per_hour(sm["false_flags_per_publish_mean"], d["meta"]["n_publishes"], nz, d["meta"]["steps"])
            cells.append(f"{sm['false_flags_per_publish_mean'] / nz:.2f}, {fa:.1f}")
        print(f"| {k} | " + " | ".join(cells) + " |")
    print()
    print(f"Reference = `{m['reference_dir']}` ({nz_ref} zones x {m['steps']} steps, no disturbance, no truth), scored "
          f"by `{AMOC}` (`amoc.k[].fa_per_hour_reference`; per publish = that x {m['sim_hours_reference']:.4f} h / "
          f"{m['n_publishes_reference']} publishes). The disturbed columns count only flags that match no truth window "
          "at that publish (the S10B rule), from `time_to_detect_{blocked,outage,blind}.json`, so they are flagged cells "
          "minus the flags on an open truth window (each such flag is a detection, so at most the detected windows "
          "of (g) and (h) per publish over all zones): per hour = false flags "
          "per publish summed over zones x publishes / (zones x steps x 5 s / 3600). The conversion is asserted equal "
          f"to `amoc.k[].fa_per_hour_measured_outside_windows` for {m['run']} at K {', '.join(REF_KS)}. The unit is "
          "flag-publishes per zone per simulated hour, not distinct cells. The burst and breakdown runs have no "
          "time-to-detect file, so they appear in the final-map table only. Sources: "
          + ", ".join(f"`{r}`" for r, _ in s10 + ttd) + f", `{AMOC}`.")


def _same_sets(d, k):
    """Every zone flags fewer than K cells on the final map and the map window covers the whole stream, so the flagged
    set only grows and at every publish both top-K lists hold all of it (fleet/baselines.py docstring CONSEQUENCE)."""
    b = d["baselines"]
    covers = d["config"]["steps"] * SECONDS_PER_STEP <= b["params"]["window_hours"] * 3600
    return covers and all(z["n_flagged"] < int(k) for z in d["zones"].values())


def _delta3(p):
    lo, hi = p["ci95"]
    return f"{p['mean']:+.3f} ({lo:+.3f} to {hi:+.3f})"


def _paired(p, d, k, field):
    b = d["baselines"]
    if p["mean"] is None:
        return "n/a (0 units)", "n/a"
    if field == "truth_precision" and b["k"][k]["map"]["hits"]["positives"] == 0:
        return "n/a", "n/a, no truth positives"
    v = verdict(p)
    assert v == p["verdict"], (k, field, v, p["verdict"])
    if _same_sets(d, k):
        assert b["k"][k]["map"] == b["k"][k]["persistence"] and p["ci95"] == [0.0, 0.0], (d["tag"], k)
        return _delta3(p), "identical top-K sets"
    return _delta3(p), v


def _f(x, fmt=".3f"):
    return "n/a" if x is None else format(x, fmt)


def map_vs_persistence():
    docs = _load_all(BASELINES, "Map vs persistence")
    if not docs:
        return
    print("| run | zones | K | truth precision: map / persistence | PAI (= lift_all): map / persistence "
          "| lift_ever: map / persistence | paired truth precision, map - persistence (95% CI) | verdict "
          "| paired outcome precision (95% CI) | verdict |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for _, d in docs:
        b = d["baselines"]
        for k in S10_KS:
            mp, ps = b["k"][k]["map"], b["k"][k]["persistence"]
            for x in (mp, ps):
                assert x["pai"] == x["lift_all"] or abs(x["pai"] - x["lift_all"]) < 1e-9, (d["tag"], k)
            pr = b["paired"][k]
            td, tv = _paired(pr["truth_precision"], d, k, "truth_precision")
            od, ov = _paired(pr["outcome_precision"], d, k, "outcome_precision")
            print(f"| {d['tag']} | {pr['truth_precision']['n_zones']} | {k} | {_f(mp['truth_precision'])} / "
                  f"{_f(ps['truth_precision'])} | {_f(mp['pai'], '.2f')} / {_f(ps['pai'], '.2f')} "
                  f"| {_f(mp['lift_ever'], '.2f')} / {_f(ps['lift_ever'], '.2f')} | {td} | {tv} | {od} | {ov} |")
    print()
    print("Chance lines and units per run:\n")
    print("| run | disturbance | steps | chance_all | chance_ever | forecast units (truth / outcome) "
          "| rank forecasts graded (unranked) |")
    print("|---|---|---|---|---|---|---|")
    for _, d in docs:
        b = d["baselines"]
        rg = d["rank_grading"]
        print(f"| {d['tag']} | `{json.dumps(d['config']['disturb'])}` | {d['config']['steps']} "
              f"| {b['chance']['all']:.3f} | {b['chance']['ever']:.3f} | {b['n_units_truth']} / "
              f"{b['n_units_outcome']} | {rg['rank_graded']} ({rg['unranked']}) |")
    print()
    print("lesson_persist (hot_cell lessons) against three pools:\n")
    print("| run | hot_cell lessons graded | hot_robot excluded | observed rate | chance: window (S8S) / ever / all "
          "| lift: window / ever / all |")
    print("|---|---|---|---|---|---|")
    for _, d in docs:
        lp = d["baselines"]["lesson_persist"]
        if not lp["n_lessons"]:
            print(f"| {d['tag']} | 0 | {lp['n_hot_robot_excluded']} | n/a | n/a | n/a |")
            continue
        print(f"| {d['tag']} | {lp['n_lessons']} | {lp['n_hot_robot_excluded']} | {lp['observed_rate']:.3f} "
              f"| {lp['chance_window']:.3f} / {lp['chance_ever']:.3f} / {lp['chance_all']:.4f} "
              f"| {_f(lp['lift_window'], '.2f')} / {_f(lp['lift_ever'], '.2f')} / {_f(lp['lift_all'], '.2f')} |")
    print()
    same = [(d["tag"], k, max(z["n_flagged"] for z in d["zones"].values())) for _, d in docs for k in S10_KS
            if _same_sets(d, k)]
    same_txt = "; ".join(f"{t} at K {k} (at most {n} flagged cells per zone)" for t, k, n in same) or "no row"
    empty = [d["tag"] for _, d in docs if all(d["baselines"]["k"][k]["map"]["hits"]["positives"] == 0 for k in S10_KS)]
    few = [(d["tag"], d["baselines"]["paired"][S10_KS[0]]["truth_precision"]["n_zones"]) for _, d in docs
           if (d["baselines"]["paired"][S10_KS[0]]["truth_precision"]["n_zones"] or 99) < 5]
    p0 = docs[0][1]["baselines"]["params"]
    s8b = next((d for r, d in docs if d["tag"] == "s8b-medium-80-p03-07"), None)
    committed = load(S8B_COMMITTED)
    note = ""
    if s8b is not None and committed is not None:
        note = (f" The s8b re-score reads the store as it is on disk today, which grades {s8b['rank_grading']['rank_graded']}"
                f" rank forecasts ({s8b['rank_grading']['unranked']} unranked); the committed `{S8B_COMMITTED}` graded "
                f"{committed['rank_grading']['rank_graded']} ({committed['rank_grading']['unranked']} unranked). The "
                "`baselines` block is computed from the costmap rows, not from those grades.")
    print("Persistence = the same published rows ranked by their raw window stall count instead of the decayed cost: "
          "same window, same filter, same `min_stalls`, so decay is the only difference (`fleet/baselines.py` "
          "docstring). Truth precision here is per publish against the cells that are truth-positive over the next "
          "horizon [t, t + H], pooled over (zone, publish) units, so it is not the run-level `truth_kinds` of (f) and "
          f"(h). PAI = (hits / positives) / (K / {p0['n_cells_all']} candidate cells) and equals lift_all by definition "
          f"(asserted). Paired = per-zone map minus persistence, mean over zones, {p0['n_resamples']:,}-resample zone "
          f"bootstrap (seed {p0['bootstrap_seed']}), 2.5 / 97.5 percentiles; the verdict rule is the one at the top of this script (asserted equal to the JSON's), but the "
          "CI is a bootstrap, not `evaluate.paired_delta`'s Student-t. \"identical top-K sets\" = every zone flags fewer "
          "than K cells on the final map and the map window covers the whole stream, so both lists hold the whole "
          f"flagged set at every publish (asserted: equal blocks, CI 0 to 0): {same_txt}. "
          + "".join(f"{t} has no truth positives, so its truth columns are 0 or n/a by construction. " for t in empty)
          + "".join(f"{t} has {n} zones; a bootstrap over so few zones sits on the extreme resamples, so its verdicts "
                    "are weak. " for t, n in few)
          + "The outcome grade re-ranks with the map's own decay at "
          "t + H, so it leans toward the map; closed-loop-sticky has one publish at stream end and 0 outcome units."
          + note + " Sources: " + ", ".join(f"`{r}`" for r, _ in docs) + " (`baselines`, `rank_grading`, `config`).")


def amoc_table():
    a = load(AMOC)
    if a is None:
        print(f"AMOC: `{AMOC}` MISSING")
        return
    m, am = a["meta"], a["amoc"]

    def row(dial, r):
        q = "none" if r["median_delay_s"] is None else f"{r['median_delay_s']:g} ({r['p25']:g}-{r['p75']:g})"
        return (f"| {dial} | {r['n_detected']} / {r['n_windows']} | {r['miss_share']:.2f} | {q} "
                f"| {r['stale_at_end_share']:.2f} | {r['fa_per_hour_reference']:.1f} "
                f"| {r['fa_per_hour_measured_outside_windows']:.1f} |")

    head = ("| detected / windows | miss share | first detect, s, median (p25-p75) | stale_at_end share "
            f"| false alarms per zone-hour, {m['reference_run']} | false alarms per zone-hour, {m['run']} outside "
            "windows |")
    print("By K (flag = rank <= K in the zone's map at a publish):\n")
    print("| K (per zone) " + head)
    print("|---|---|---|---|---|---|---|")
    for r in am["k"]:
        print(row(r["K"], r))
    print()
    print("By cost threshold (flag = cost >= c at a publish):\n")
    print("| cost >= " + head)
    print("|---|---|---|---|---|---|---|")
    for r in am["cost"]:
        print(row(f"{r['cost']:g}", r))
    print()
    kb = am["k_at_miss_below_half"]
    cb = am["cost_at_miss_below_half"]
    print(f"Dial at which the miss share first drops below 0.5: K {'none at any K' if kb is None else kb}; cost "
          f"{'none at any cost' if cb is None else cb}.\n")
    print(f"Measured run `{m['phase_a_dir']}` ({m['n_windows']} planner-blind blocked windows, `{json.dumps(m['disturb'])}`),"
          f" reference `{m['reference_dir']}` (undisturbed), both {len(m['zones'])} zones x {m['steps']} steps = "
          f"{m['sim_hours']:.4f} simulated h, {m['n_publishes']} publishes every {m['publish_every_s'] / 60:g} min. "
          "False alarms are flag-publishes per zone per simulated hour: on the reference every flag counts; on the "
          "measured run only flags matching no truth window at that publish. Rows with equal numbers are saturated: "
          "the dial already flags every cell with a nonzero cost. Definitions (verbatim from the JSON): "
          + "; ".join(f"{k}: \"{v}\"" for k, v in m["amoc_definitions"].items()) + f". Source: `{AMOC}` (`amoc`).")


def main():
    print("### (a) Dose-response: map benefit by floor stickiness (30 seeds x 500 steps)\n")
    dose_response()
    print("\n### (b) Longer shift\n")
    long_shift()
    print("\n### (c) Guidance tuning (S8M), two regimes\n")
    results = []
    for g in GUIDANCES:
        print(f"**`{g}`**\n")
        results.append(guidance(g))
        print()
    print("Side by side (map_tuned on held-out seeds 10-29, paired per seed):\n")
    guidance_side_by_side(results)
    print("\n### (d) Time to detect (S8P), sticky regime\n")
    time_to_detect()
    print("\n### (e) lesson_persist against its chance rate (S8S)\n")
    lesson_persist_chance()
    print("\n### (f) Analyser on other disturbances (S10A truth v2, 10 zones x 500 steps)\n")
    other_disturbances()
    print("\n### (g) Time to detect and time to clear (S10B)\n")
    detect_and_clear()
    print("\n### (h) Planner-blind blockage next to the known blockage (S10C)\n")
    blind_blockage()
    print("\n### (i) The undisturbed reference (s10-none) next to the disturbed runs\n")
    undisturbed_reference()
    print("\n### (j) Map versus persistence (S10D)\n")
    map_vs_persistence()
    print("\n### (k) AMOC: delay, misses and false alarms per hour (S10E, planner-blind blockage)\n")
    amoc_table()


if __name__ == "__main__":
    sys.exit(main())

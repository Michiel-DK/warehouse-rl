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


if __name__ == "__main__":
    sys.exit(main())

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
  results/fleet/hotspot_{s10-none,s10c-blind,closed-loop-sticky}-gate-{baseline,persistence}.json, with the ungated
  results/fleet/hotspot_{s10-none,s10c-blind}.json -> (l) the false-alarm gate (S10F, `gate_grading`)
  results/fleet/hotspot_s10-breakdown.json     -> (m) frozen truth cells on the breakdown run (S10G, `truth_kinds.frozen`)
  results/fleet/amoc_{blind,shortmap,fast}.json -> (n) fast detector (S10I per-cell CUSUM) vs the decayed map, with the
                                                  short-memory map published at the CUSUM's 60 s as cadence control
                                                  (CUSUM parameters from fleet/data/s10c-blind/fastmap.json if present)
  results/fleet/timebudget_{s10-none,s10c-blind,s10-breakdown,closed-loop-sticky,s8b-medium-80-p03-07}.json
                                               -> (o) where the shift goes (S12A time budget, `run` block)
  results/fleet/deadlock_{s10-none,s10c-blind,s10-breakdown,closed-loop-sticky}.json, results/fleet/gapmap_s12-deadzone.json
  and `gap_grading` of results/fleet/hotspot_s12-deadzone.json
                                               -> (p) blocking clusters and chains (S12B) and the message-loss cell line
  results/fleet/timebudget_moroop.json, results/fleet/timebudget_moroop_shifts.json
                                               -> (q) a real shift: the time budget on the MoRoOp log (S13A), per shift
                                                  and pooled, against the robot's own stuck label
  every results/fleet/*-st.json of wr-s13b-rerun next to its station-unaware file
                                               -> (r) the station-aware stuck rule (S13B): old / station-aware / delta
                                                  for the headline numbers of (f), (h)-(q) that rest on the stall list
  every results/fleet/*-sb.json of wr-s14a-rerun next to its -st twin
                                               -> (s) the station stop bound (S14A): station-aware / bounded / delta for
                                                  every row of (r), the bound per run, the causes tables, the MoRoOp
                                                  overruns
  results/fleet/amoc_{blind,fast,absence}.json, results/fleet/amoc_absence_sweep.json
                                               -> (t) traffic absence (S14B) against the decayed map and the CUSUM, and
                                                  its alpha sweep

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
AMOC_ARMS = [("decayed map (S10E)", AMOC), ("short-memory map", "results/fleet/amoc_shortmap.json"),
             ("CUSUM (S10I)", "results/fleet/amoc_fast.json")]
FASTMAP_PARAMS = "fleet/data/s10c-blind/fastmap.json"
BASELINES = [f"results/fleet/baselines_{t}.json" for t in ("s8b-medium-80-p03-07", "closed-loop-sticky", "s8e-long-w0.5",
                                                           "s10c-blind", "s10-none")]
S8B_COMMITTED = "results/fleet/hotspot_s8b-medium-80-p03-07.json"
REF_KS = ("10", "20", "40")
CELL_KINDS = ("floor", "blocked", "outage")
S10_KS = ("20", "40")
GATES = ("baseline", "persistence")
GATE_RUNS = [("s10-none", NONE), ("s10c-blind", BLIND), ("closed-loop-sticky", None)]
SECONDS_PER_STEP = 5
# (o) and (p): tag -> what the run is; the tag names the results file
S12_RUNS = [("s10-none", "undisturbed"), ("s10c-blind", "planner-blind blockage"),
            ("s10-breakdown", "robot breakdowns"), ("s8b-medium-80-p03-07", "floor, 80 cells, p 0.3-0.7"),
            ("closed-loop-sticky", "sticky floor, 80 cells, p 0.9-0.99 (phase A, 30 zones)")]
BUCKETS = [("moving", "productive: travel"), ("waiting_station", "productive: load/unload, or standby: queued"),
           ("waiting_shelf", "standby: no operator"), ("stuck", "blocked, >= 30 s"),
           ("stopped_short", "blocked: congestion wait, < 30 s"), ("faulted", "unscheduled downtime"),
           ("idle", "standby: no work"), ("paused", "standby: paused or manual mode, VDA `paused`"),
           ("no_data", "unobserved: no message for more than max_gap_s")]
STREAM_T0_MINUTE = "2026-01-01T00:00:00Z"  # fleet/fleet_analyser/emitter.py DEFAULT_T0, the zone-start minute
GAPMAP, GAP_HOTSPOT = "results/fleet/gapmap_s12-deadzone.json", "results/fleet/hotspot_s12-deadzone.json"
MOROOP, MOROOP_SHIFTS = "results/fleet/timebudget_moroop.json", "results/fleet/timebudget_moroop_shifts.json"
# vendor/tarware/tarware/warehouse.py:15 (_STUCK_THRESHOLD) and :494 (replan once the stuck count passes it)
VENDOR_STUCK_THRESHOLD = 5


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
    print("Precision and recall at K, split by kind (only kinds with positives in the run; pooled over zones; frozen "
          "cells = the robot's cell at the start of each frozen window, S10G):\n")
    print("| run | kind | positives | " + " | ".join(f"K {k}: hits, precision, recall" for k in S10_KS)
          + " | zones flagging fewer than K cells (" + " / ".join(f"K {k}" for k in S10_KS) + ") |")
    print("|---|---|---|" + "---|" * len(S10_KS) + "---|")
    for _, d in docs:
        tk = d["truth_kinds"]
        short = " / ".join(str(_flagged(d, k)[1]) for k in S10_KS)
        kinds = [k for k in CELL_KINDS if tk[k]["positives"] > 0] + (["frozen"] if tk["frozen"].get("cells") else [])
        for kind in kinds:
            cells = []
            for k in S10_KS:
                e = tk[kind]["k"][k]
                cells.append(f"{e['hits']}, {e['precision']:.4f}, {e['recall']:.2f}")
            pos = tk[kind]["cells"] if kind == "frozen" else tk[kind]["positives"]
            label = "frozen cells" if kind == "frozen" else kind
            print(f"| {d['tag']} | {label} | {pos} | " + " | ".join(cells) + f" | {short} |")
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
          "graded lesson. s10-breakdown was re-emitted bit-identically and re-scored by `wr-s10g-breakdown-rerun` "
          "(S10G truth with frozen cells, lessons `--window-h 0.2`), so its row is the re-score. Sources: " + ", ".join(f"`{r}`" for r, _ in docs)
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


def _amoc_row(dial, r, fa_fmt=".1f"):
    q = "none" if r["median_delay_s"] is None else f"{r['median_delay_s']:g} ({r['p25']:g}-{r['p75']:g})"
    return (f"| {dial} | {r['n_detected']} / {r['n_windows']} | {r['miss_share']:.2f} | {q} "
            f"| {r['stale_at_end_share']:.2f} | {r['fa_per_hour_reference']:{fa_fmt}} "
            f"| {r['fa_per_hour_measured_outside_windows']:{fa_fmt}} |")


def _amoc_head(m):
    return ("| detected / windows | miss share | first detect, s, median (p25-p75) | stale_at_end share "
            f"| false alarms per zone-hour, {m['reference_run']} | false alarms per zone-hour, {m['run']} outside "
            "windows |")


def amoc_table():
    a = load(AMOC)
    if a is None:
        print(f"AMOC: `{AMOC}` MISSING")
        return
    m, am = a["meta"], a["amoc"]
    row = _amoc_row
    head = _amoc_head(m)
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


def _dominates(a, b):
    """a is at least as good as b on both axes (detected up, reference false alarms down) and better on one."""
    da, db = a["n_detected"], b["n_detected"]
    fa, fb = a["fa_per_hour_reference"], b["fa_per_hour_reference"]
    return da >= db and fa <= fb and (da > db or fa < fb)


def fast_vs_map():
    arms = _load_all([rel for _, rel in AMOC_ARMS], "Fast vs map")
    if len(arms) != len(AMOC_ARMS):
        return
    docs = [(name, rel, d) for (name, _), (rel, d) in zip(AMOC_ARMS, arms)]
    m0 = docs[0][2]["meta"]
    for _, rel, d in docs:
        m = d["meta"]
        for f in ("phase_a_dir", "reference_dir", "run", "reference_run", "truth_kind", "n_windows", "steps", "zones",
                  "disturb", "sim_hours", "sim_hours_reference"):
            assert m[f] == m0[f], (rel, f)
        for f in ("store_hash", "reference_store_hash"):
            assert m[f + "_before"] == m[f + "_after"] == m0[f + "_before"], (rel, f)
    ks = sorted(set.intersection(*({r["K"] for r in d["amoc"]["k"]} for _, _, d in docs)))
    cusum = {r["K"]: r for r in docs[-1][2]["amoc"]["k"]}
    keys = ("n_detected", "median_delay_s", "fa_per_hour_reference", "fa_per_hour_measured_outside_windows")
    assert len({tuple(r[f] for f in keys) for r in cusum.values()}) == 1, "CUSUM rows differ by K"
    print("By K (map: flag = rank <= K in the zone's map at a publish; CUSUM: flag = a flagged cell at a publish, K "
          "only caps the rank):\n")
    print("| detector | publish every, s (publishes) | K (per zone) " + _amoc_head(m0))
    print("|---|---|---|---|---|---|---|---|---|")
    for name, _, d in docs:
        m = d["meta"]
        by_k = {r["K"]: r for r in d["amoc"]["k"]}
        fmt = ".3f" if max(r["fa_per_hour_reference"] for r in by_k.values()) < 1 else ".1f"
        for k in ks:
            print(f"| {name} | {m['publish_every_s']} ({m['n_publishes']}) " + _amoc_row(k, by_k[k], fmt))
    print()
    # dominance on (detected, reference FA/h) over every row on disk: the maps' K rows and the decayed map's cost rows
    rows = {name: [(f"K {r['K']}", r) for r in d["amoc"]["k"]] + [(f"cost >= {r['cost']:g}", r)
                                                                   for r in d["amoc"].get("cost", [])]
            for name, _, d in docs}
    cname = docs[-1][0]
    c_row = cusum[ks[0]]
    over = {name: [lab for lab, r in rs if _dominates(c_row, r)] for name, rs in rows.items() if name != cname}
    under = {name: [lab for lab, r in rs if _dominates(r, c_row)] for name, rs in rows.items() if name != cname}
    same_fa = {name: [lab for lab, r in rs if r["fa_per_hour_reference"] == c_row["fa_per_hour_reference"]]
               for name, rs in rows.items() if name != cname}
    assert not any(under.values()), under
    map_min_fa = min(r["fa_per_hour_reference"] for name, rs in rows.items() if name != cname for _, r in rs)
    best_map = max(r["n_detected"] for name, rs in rows.items() if name != cname for _, r in rs)
    print("Dominance over every row on disk (detected up, false alarms per zone-hour on the reference down, one "
          "strictly): the CUSUM row is dominated by no map row; it dominates "
          + "; ".join(f"{name}: {', '.join(labs) if labs else 'none'}" for name, labs in over.items())
          + ". Map rows at the CUSUM's reference false-alarm rate ("
          f"{c_row['fa_per_hour_reference']:g}): "
          + ("none" if not any(same_fa.values()) else "; ".join(f"{n}: {', '.join(l)}" for n, l in same_fa.items() if l))
          + f". Lowest map false-alarm rate on disk {map_min_fa:.1f}; most windows any map row detects {best_map} / "
          f"{c_row['n_windows']}.\n")
    pp = REPO / FASTMAP_PARAMS
    if pp.exists():
        p = json.loads(pp.read_text())["params"]
        params = (f"CUSUM parameters (from `{FASTMAP_PARAMS}`, gitignored, not committed): k {p['k']:g}, h {p['h']:g}, "
                  f"bin {p['bin_s']} s, baseline {p['baseline_bins']} bins, count `{p['count']}`. ")
    else:
        params = f"CUSUM parameters: `{FASTMAP_PARAMS}` not on disk. "
    arms_txt = "; ".join(
        f"{name}: `{rel}`, " + (f"window {d['meta']['window_hours']:g} h, half-life {d['meta']['half_life_h']:g} h"
                                if d["meta"].get("store_suffix") != "fast" else "store-fast (prebuilt)")
        for name, rel, d in docs)
    pubs = sorted({d["meta"]["publish_every_s"] for _, _, d in docs})
    assert len(pubs) == 2 and docs[-1][2]["meta"]["publish_every_s"] == docs[1][2]["meta"]["publish_every_s"] == pubs[0]
    print(f"Same measured run (`{m0['phase_a_dir']}`, {m0['n_windows']} planner-blind blocked windows) and reference "
          f"(`{m0['reference_dir']}`) for all three, store hashes equal before and after (asserted). Ks shown are the "
          f"ones all three JSONs share ({', '.join(map(str, ks))}). " + params
          + "The CUSUM rows are identical at every K (asserted). False alarms are flag-publishes per zone per "
          f"simulated hour, so they scale with the publish rate: a detector publishing every {pubs[0]} s has "
          f"{pubs[1] / pubs[0]:g} times as many publishes per hour as one publishing every {pubs[1]} s, and more "
          "chances to catch a window while it is open. The short-memory map is published at the CUSUM's "
          f"{pubs[0]} s and is the like-for-like cadence comparison for it. Column definitions are those of (k). Sources: " + arms_txt + " (`amoc`, `meta`).")


def _publishes(d):
    """Publishes every 300 s with the last at stream end (the queue items' `--publish-every 300`)."""
    return -(-d["config"]["steps"] * SECONDS_PER_STEP // 300)


def gate_table():
    tb = load(TTD_BLIND)
    rows = []
    for tag, ungated in GATE_RUNS:
        u = load(ungated) if ungated else None
        if ungated and u is None:
            print(f"Gate: `{ungated}` MISSING")
        gated = []
        for g in GATES:
            rel = f"results/fleet/hotspot_{tag}-gate-{g}.json"
            d = load(rel)
            if d is None:
                print(f"Gate: `{rel}` MISSING")
                continue
            assert d["tag"] == f"{tag}-gate-{g}" and list(d["gate_grading"]) == [g], rel
            if u is not None:
                same = [k for k in u["truth_kinds"] if k != "frozen"]  # S10G added frozen.cells/k after these
                assert all(d["truth_kinds"][k] == u["truth_kinds"][k] for k in same) and d["zones"] == u["zones"], rel
            gated.append((rel, g, d))
        rows.append((tag, ungated, u, gated))
    if tb is not None:
        assert _publishes(load(BLIND)) == tb["meta"]["n_publishes"]
    print("| run | gate | forecasts (flags) | per zone per publish: mean over all, max | truth hits / false alarms "
          "| precision | truth cells hit / truth cells | recall (cells) |")
    print("|---|---|---|---|---|---|---|---|")
    used = []
    for tag, ungated, u, gated in rows:
        nz = len((u or gated[0][2])["zones"]) if (u or gated) else 0
        if u is not None:
            used.append(ungated)
            t = u["grading_counts"].get("truth", {})
            n, h = sum(t.values()), t.get("hit", 0)
            pos = u["truth_kinds"]["any"]["positives"]
            print(f"| {tag} | none | {n} | {n / (nz * _publishes(u)):.2f}, n/a | {h} / {t.get('false_alarm', 0)} "
                  f"| {h / n:.3f} | n/a / {pos} | n/a |")
        else:
            print(f"| {tag} | none | n/a | n/a | n/a | n/a | n/a | n/a (not comparable: the original phase A map "
                  "had one publish) |")
        for rel, g, d in gated:
            used.append(rel)
            e = d["gate_grading"][g]
            t = d["grading_counts"].get("truth", {})
            assert (e["hits"], e["false_alarms"]) == (t.get("hit", 0), t.get("false_alarm", 0)), rel
            nz = len(d["zones"])
            prec = "n/a" if e["precision"] is None else f"{e['precision']:.3f}"
            rec = "n/a (no truth cells)" if e["recall"] is None else f"{e['recall']:.3f}"
            print(f"| {tag} | {g} | {e['forecasts']} | {e['forecasts'] / (nz * _publishes(d)):.2f}, "
                  f"{e['flags_per_zone_publish']['max']} | {e['hits']} / {e['false_alarms']} | {prec} "
                  f"| {e['hit_cells']} / {e['positive_cells']} | {rec} |")
    print()
    print("Forecasts = `hotspot_forecast` claims, each graded once against the truth over the next horizon (truth hit "
          "or false alarm); a gated run publishes only the forecasts that pass the gate, and the cost map itself is "
          "unchanged (asserted here: `zones` and every `truth_kinds` kind except `frozen`, whose S10G fields the ungated JSONs predate, are equal to the ungated JSON's). Per zone per publish, "
          "mean over all = forecasts / (zones x publishes), with 9 publishes every 300 s, the last at stream end, "
          "warm-up publishes included (baseline: publishes 1-3 pass nothing; persistence: publish 1); max = "
          "`gate_grading.flags_per_zone_publish.max`, after warm-up. The ungated JSONs carry no per-publish maximum "
          "and no truth cells hit, so those are n/a; truth cells = `truth_kinds.any.positives`. Truth cells hit = "
          "distinct (zone, cell) with at least one truth-hit forecast; recall = that / truth cells. The gate runs used "
          "`--publish-every 300 --horizon-s 1245` on copies of each store (`wr-s10f-gate-run`); s10-none and "
          "s10c-blind are the same publishes as their ungated runs, the sticky phase A was originally published once, "
          "so it has no ungated row on this schedule. On the sticky run the truth cells are its 80 floor cells per "
          "zone, present for the whole run. Gate parameters: windows 3, sigma 2.0, min excess 2, min count 2 (the "
          "S10F defaults). Sources: " + ", ".join(f"`{r}`" for r in used) + " (`gate_grading`, `grading_counts.truth`, "
          "`truth_kinds`).")


def frozen_cells():
    d = load(S10[2])
    if d is None:
        print(f"Frozen cells: `{S10[2]}` MISSING")
        return
    fz = d["truth_kinds"]["frozen"]
    if "cells" not in fz:
        print(f"Frozen cells: `{S10[2]}` has no `truth_kinds.frozen.cells` (pre-S10G file)")
        return
    nz = len(d["zones"])
    flagged = sum(z["n_flagged"] for z in d["zones"].values())
    print("| run | frozen robots | frozen cells | flagged cells, final map (per zone, max) | "
          + " | ".join(f"K {k}: hits, precision, recall" for k in S10_KS)
          + " | zones flagging fewer than K cells (" + " / ".join(f"K {k}" for k in S10_KS) + ") "
          "| hotspot_forecast truth grades: hit / graded |")
    print("|---|---|---|---|" + "---|" * len(S10_KS) + "---|---|")
    cells = []
    for k in S10_KS:
        e = fz["k"][k]
        assert e["hits"] == d["truth_kinds"]["any"]["k"][k]["hits"], k
        cells.append(f"{e['hits']}, {e['precision']:.4f}, {e['recall']:.3f}")
    t = d["grading_counts"].get("truth", {})
    short = " / ".join(str(_flagged(d, k)[1]) for k in S10_KS)
    print(f"| {d['tag']} | {fz['positives']} | {fz['cells']} | {flagged} ({flagged / nz:.1f}, "
          f"{max(z['n_flagged'] for z in d['zones'].values())}) | " + " | ".join(cells)
          + f" | {short} | {t.get('hit', 0)} / {sum(t.values())} |")
    print()
    k0 = S10_KS[0]
    print(f"Frozen cells = per zone, the distinct cells a robot stood on at the start of a frozen window, summed over "
          f"zones (`truth_kinds.frozen.cells`); a hit is a final-map top-K cell that is a frozen cell of its zone at any "
          f"time in the run, so it does not mean the cell was flagged while the robot was frozen. Frozen cells are the "
          f"only truth cells of this run (asserted: frozen hits = `any` hits), so {fz['k'][k0]['hits']} of the "
          f"{flagged} flagged cells are frozen cells and the rest are false flags. Every zone flags fewer than "
          f"{k0} cells, so K {' and K '.join(S10_KS)} score the same cells. The time-matched number is the forecast "
          "truth grade: a forecast is a hit when its cell is truth-positive (here: frozen) over the next horizon "
          "(1245 s). Before S10G the same run graded 0 hits of 488 (the committed (f) of 2026-10-18), because frozen "
          "windows carried no cell. No chance line is computed for frozen cells. Source: "
          f"`{S10[2]}` (`truth_kinds.frozen`, `zones.*.n_flagged`, `grading_counts.truth`), from "
          "`wr-s10g-breakdown-rerun` (bit-identical re-emit, lessons `--window-h 0.2`).")


def time_budget():
    runs = _load_all([f"results/fleet/timebudget_{t}.json" for t, _ in S12_RUNS], "Time budget")
    if not runs:
        return
    label = dict(S12_RUNS)
    print("| run | disturbance | AGVs (zones) | " + " | ".join(f"{b} ({std})" for b, std in BUCKETS)
          + " | throughput: jobs per AGV-hour | same-minute stops: zone-start minute / later | stall list: episodes "
          "starting on a station cell, n/N (share) | starting next to a shelf, n/N (share) | picker episodes in N |")
    print("|---|---|---|" + "---|" * len(BUCKETS) + "---|---|---|---|---|")
    for rel, d in runs:
        r, t = d["run"], d["run"]["totals"]
        tag = rel.split("timebudget_", 1)[1][:-len(".json")]
        assert sum(t["seconds"].values()) == t["span_s"], rel
        assert r["stuck_runs_vs_detector"]["start_sets_equal"], rel
        w = r["station_waits_in_stall_list"]
        assert w["source"] == "store", rel
        minutes = [m for z in d["zones"].values() for m in z["same_minute_stops"]["minutes"]]
        assert len(minutes) == r["same_minute_stops_count"], rel
        at0 = sum(m == STREAM_T0_MINUTE for m in minutes)
        print(f"| {tag} | {label[tag]} | {t['robots']} ({len(d['zones'])}) | "
              + " | ".join(f"{100 * t['share'][b]:.1f}%" for b, _ in BUCKETS)
              + f" | {r['jobs_per_robot_hour']:.2f} | {at0} / {len(minutes) - at0} | "
              f"{w['at_station']}/{w['episodes']} ({100 * w['share_station']:.1f}%) | "
              f"{w['at_shelf']}/{w['episodes']} ({100 * w['share_shelf']:.1f}%) | {w['picker_episodes']} |")
    print()
    cc = {json.dumps(z["cell_classes"], sort_keys=True) for _, d in runs for z in d["zones"].values()}
    assert len(cc) == 1, cc
    cc = json.loads(cc.pop())
    src = runs[0][1]["src"]
    print("Shares are of AGV-seconds over the zone's span, summed over zones (`run.totals.share`; pickers are reported "
          "apart by the tool and are not in the shares, the AGV count or the jobs rate). Every second goes to one bucket, "
          "in the precedence no_data > faulted > paused > moving > waiting_station > waiting_shelf > stuck / "
          "stopped_short > idle, so a "
          "stop next to a shelf is `waiting_shelf` even when it lasts past the stuck threshold "
          f"({src['stuck_after']} s, the detector's own). The term in brackets is the standard class "
          "`docs/LITERATURE.md` Part 2 section 2 maps each bucket to (SEMI E10 classes, Standridge's blocked time, VDA "
          "5050 fields); where the bucket does not measure that class, the reading below says so. Station cells: "
          f"{cc['n_station_cells']} per zone. Shelf-adjacent cells: {cc['n_shelf_adjacent_cells']} per zone (the "
          f"{cc['n_shelf_slots']} shelf slots plus every cell within Manhattan {src['shelf_adjacent_manhattan']} of one, "
          "stations excluded). Throughput is jobs per AGV-hour, the MAPF word for goals reached per unit time. Same-minute "
          f"stops: minutes in which at least {100 * src['same_minute_share']:.0f}% of a zone's AGVs stop, split into the "
          f"zone-start minute ({STREAM_T0_MINUTE[11:16]}) and later minutes. Stall list: the detector's stuck episodes "
          "from the run's store (pickers included, last column); a station or shelf episode is one whose first cell is a "
          "station or shelf-adjacent cell. Asserted per run: the time-budget stuck runs and the detector episodes have "
          "the same start sets (`stuck_runs_vs_detector`), and the bucket seconds sum to the span. `faulted` counts "
          "robots with an error of error level CRITICAL or FATAL (S12C; the emitter writes only FATAL errors). "
          "`paused` is a message with VDA 5050 `paused` true; `no_data` is the whole interval between two messages "
          f"more than {src['max_gap_s']} s apart (`src.max_gap_s`). The simulator emitter never sets `paused` and "
          "sends every robot every step, so both shares are zero on these runs, as the JSONs show. Sources: "
          + ", ".join(f"`{rel}`" for rel, _ in runs) + " (`run`, `zones.*.same_minute_stops`, "
          "`zones.*.cell_classes`, `src`), from `wr-s12a-budget-run`, re-run after S12C with the new buckets "
          "(every other value unchanged).")


def _as_v1(d):
    """A fleet-deadlock/1 or /2 document in the v1 key names (deadlocks, knots, deadlock_s, kind "deadlock") that the
    S12B tables were written against. v1 is returned as is; v2 is mapped key by key, values untouched."""
    if d["schema_version"] == "fleet-deadlock/1":
        return d
    assert d["schema_version"] == "fleet-deadlock/2", d["schema_version"]

    def cnt(t):
        return dict(t, deadlocks=t["blocking_clusters"], knots=t["blocking_chains"],
                    deadlock_s_per_robot_hour=t["blocked_s_per_robot_hour"])

    zones = {z: dict(cnt(zd), top_cells=[dict(c, deadlock_s=c["blocked_s"]) for c in zd["top_cells"]])
             for z, zd in d["zones"].items()}
    dec = [dict(x, kind="deadlock" if x["kind"] == "blocking_cluster" else x["kind"]) for x in d["decisions"]]
    return dict(d, schema_version="fleet-deadlock/1", zones=zones, total=cnt(d["total"]), decisions=dec,
                _from_v2=True)


def _cluster_definition(d):
    """The cluster half of the tool's own DEFINITION text, v1 or v2 (a v2 file is read through _as_v1 first)."""
    text = d["definition"]
    if d.get("_from_v2"):
        return text.split("blocking cluster: ", 1)[1].split(". blocking chain")[0]
    return text.split(";")[1].strip().split(". knot")[0]


def _top_cell(d):
    best = None
    for z, zd in sorted(d["zones"].items(), key=lambda kv: int(kv[0])):
        for c in zd["top_cells"]:
            key = (-c["deadlock_s"], int(z), c["cell"])
            if best is None or key < best[0]:
                best = (key, z, c)
    if best is None:
        return "none", 0
    _, z, c = best
    ties = sum(1 for zd in d["zones"].values() for x in zd["top_cells"] if x["deadlock_s"] == c["deadlock_s"])
    n = sum(1 for x in d["decisions"] if x["claim"]["zone"] == z and c["cell"] in x["claim"]["cells"])
    return f"zone {z}, cell {c['cell']}: {c['deadlock_s']} s in {n} clusters", ties


def _standoffs(d):
    """Clusters of the same zone and robot set, each starting within one step of the previous one's end, merged."""
    out = {}
    for x in sorted(d["decisions"], key=lambda x: (x["claim"]["zone"], sorted(x["claim"]["robots"]), x["decided_at"]
                                                     - x["claim"]["length_s"])):
        c = x["claim"]
        end = x["decided_at"]
        start = end - c["length_s"]
        runs = out.setdefault((c["zone"], frozenset(c["robots"])), [])
        if runs and start <= runs[-1]["end"] + SECONDS_PER_STEP:
            r = runs[-1]
            r.update(end=max(r["end"], end), n=r["n"] + 1, res=c["resolution"],
                     robot_s=r["robot_s"] + c["length_s"] * len(c["robots"]))
        else:
            runs.append(dict(zone=c["zone"], robots=sorted(c["robots"]), start=start, end=end, n=1,
                             res=c["resolution"], robot_s=c["length_s"] * len(c["robots"])))
    return [r for runs in out.values() for r in runs]


def blocking_clusters(rels=None):
    """rels: paths of the deadlock JSONs (default: the committed results/fleet/deadlock_<run>.json); v1 and v2 are read."""
    tags = [t for t, _ in S12_RUNS]
    if rels is None:
        rels = [f"results/fleet/deadlock_{t}.json" for t in tags if t != "s8b-medium-80-p03-07"]
    runs = [(rel, _as_v1(d)) for rel, d in _load_all(rels, "Blocking clusters")]
    if not runs:
        return
    ref = dict(runs).get("results/fleet/deadlock_s10-none.json")
    ref_rate = ref["total"]["deadlock_s_per_robot_hour"] if ref else None
    print("| run | blocking clusters (JSON `blocking_clusters`) | broke up / still open at stream end | blocking chains "
          "(JSON `blocking_chains`) | cluster length, s: median (max) | robots per cluster, max | blocked robot-s in clusters per "
          "robot-hour | vs s10-none | top cell by cluster seconds (cells tied at that value) | standoffs (same robots, "
          "gaps of at most one step merged) | longest standoff: zone, span s, clusters, end | longest standoff's share "
          "of blocked robot-s |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for rel, d in runs:
        tot, dec = d["total"], d["decisions"]
        assert d["schema_version"] == "fleet-deadlock/1", rel
        assert len(dec) == tot["deadlocks"] and all(x["kind"] == "deadlock" for x in dec), rel
        lengths = sorted(x["claim"]["length_s"] for x in dec)
        res = [x["claim"]["resolution"] for x in dec]
        assert set(res) <= {"broke_up", "unresolved_at_end"}, set(res)
        mid = len(lengths) // 2
        med = lengths[mid] if len(lengths) % 2 else (lengths[mid - 1] + lengths[mid]) / 2
        top, ties = _top_cell(d)
        for zd in d["zones"].values():
            for x in zd["deadlocks"]:
                assert x["end"] - x["start"] == x["length_s"], rel
        st = _standoffs(d)
        assert sum(r["n"] for r in st) == len(dec), rel
        lg = max(st, key=lambda r: (r["end"] - r["start"], r["robot_s"]))
        total_rs = sum(x["claim"]["length_s"] * len(x["claim"]["robots"]) for x in dec)
        rate = tot["deadlock_s_per_robot_hour"]
        vs = f"{rate / ref_rate:.2f}x" if ref_rate else "n/a"
        print(f"| {d['run'] if d['run'] != 'closed_loop' else 'closed-loop-sticky'} | {tot['deadlocks']} | "
              f"{res.count('broke_up')} / {res.count('unresolved_at_end')} | {tot['knots']} | {med:g} ({lengths[-1]}) | "
              f"{max(len(x['claim']['robots']) for x in dec)} | {rate:.1f} | {vs} | {top} ({ties}) | {len(st)} | "
              f"zone {lg['zone']}, {lg['end'] - lg['start']} s, {lg['n']}, "
              f"{'open at stream end' if lg['res'] == 'unresolved_at_end' else 'broke up'} | "
              f"{100 * lg['robot_s'] / total_rs:.1f}% |")
    print()
    d0 = runs[0][1]
    print("A blocking cluster is a strongly connected group of at least 2 robots in the per-batch wait-for graph "
          "(`fleet/deadlock.py`), kept when it lasts at least " f"{d0['min_s']} s. The tool's own definition: \""
          + _cluster_definition(d0) + "\". Adjacency is symmetric (Manhattan 1), so "
          "any two adjacent stuck robots with no faulted neighbour form a cluster: it is congestion that persists, not "
          "the circular wait that `docs/LITERATURE.md` Part 2 section 1 calls a deadlock (Coffman et al. 1971; a cycle "
          "in the wait-for graph). So the table is a congestion measure: no circular wait survives in TA-RWARE, "
          f"because the vendor replans a robot once it has been stuck more than {VENDOR_STUCK_THRESHOLD} steps "
          "(`_STUCK_THRESHOLD`, `vendor/tarware/tarware/warehouse.py:15` and `:494`), and every cluster that ends "
          "inside the stream broke up. The clusters still open at stream end (third column) are censored, not shown "
          "to clear. A blocking chain (JSON `blocking_chains`; S12B called it a knot) is a path of at least 2 edges "
          "among robots in no cluster; Part 2 renames it because a knot in deadlock theory is the closed set that is "
          "the deadlock. Still open at stream end = censored, its "
          "length is a lower bound. Broke up = the group was gone at the next batch, which can be a single step: the "
          f"vendor planner replans a robot after more than {VENDOR_STUCK_THRESHOLD} stuck steps, frees one cell, and the same robots can block each "
          f"other again. A standoff merges clusters of the same zone and robot set that start at most one step "
          f"({SECONDS_PER_STEP} s) after the previous one ends; its span runs from the first start to the last end. Blocked robot-s per robot-hour = sum(length x robots) / robot-hours, where "
          "robot-hours include the pickers (12 robots per zone), unlike (o), which counts AGVs only. Top cell: each "
          "cluster adds its length to every cell it covers, so cells of one cluster tie; the tie rule is most seconds, "
          "then lowest zone, then cell string. Sources: " + ", ".join(f"`{rel}`" for rel, _ in runs)
          + " (`total`, `decisions`, `zones.*.top_cells`), from `wr-s12b-run`; no run of the s8b floor store.")
    print()
    g, h = load(GAPMAP), load(GAP_HOTSPOT)
    if g is None or h is None or "gap_grading" not in h:
        print(f"Message-loss cells: `{GAPMAP}` or `gap_grading` in `{GAP_HOTSPOT}` MISSING")
        return
    gg = h["gap_grading"]
    nz = len(gg["per_zone"])
    planted = gg["deadzone_cells"] // nz
    assert planted * nz == gg["deadzone_cells"]
    assert sum(z["decisions"] for z in gg["per_zone"].values()) == gg["decisions"]
    dropped = sum(c["dropped"] for z in g["zones"].values() for c in z["cells"])
    print(f"**Message-loss cells inferred from headerId gaps (S12B gap map, run `{g['run']}`).** precision@{g['top_k']} "
          f"of `gap_cell` against the {planted} planted dead cells per zone, pooled over {nz} zones: "
          f"{gg['precision_at_10']['pooled']:.2f} (ceiling {min(planted, g['top_k']) / g['top_k']:.2f}: only {planted} "
          f"of {g['top_k']} can be right); {gg['hits']} of {gg['decisions']} `gap_cell` decisions hit, and "
          f"{gg['hits']} of {gg['deadzone_cells']} planted cells are found (recall {gg['recall']:.2f}). "
          f"{dropped:g} dropped messages placed, {g['unplaced_leading_missing']} unplaced. The graded count is "
          f"{gg['decisions']}, not {nz} x {g['top_k']}: the gap map wrote {len(g['decisions'])} decisions (some zones "
          f"place fewer than {g['top_k']} cells), and the store refused {g['store_duplicates']} as duplicates of another "
          "zone's row (same cell and first-gap time; the dedup key has no zone, S12B caveat 2). **Synthetic:** the dead cells are planted by the project's own emitter (`emit.py "
          "--deadzone`, which drops every message sent from them), so the only cause of a gap is the planted cell. In a "
          "real log a gap can also be a broker- or consumer-side drop with no location cause, and a VDA 5050 robot keeps "
          "driving through a disconnect. The stall-map truth grades in the same hotspot JSON count the dead cells as "
          f"truth hits and are not read here. Sources: `{GAPMAP}` (`zones.*.cells`, `unplaced_leading_missing`, "
          f"`store_duplicates`), `{GAP_HOTSPOT}` (`gap_grading` only).")


def _pct(share, b):
    v = share[b]
    return v if isinstance(v, str) else f"{100 * v:.1f}%"


def real_shift():
    pooled, shifts = load(MOROOP), load(MOROOP_SHIFTS)
    if pooled is None or shifts is None:
        print(f"Real shift: `{MOROOP}` or `{MOROOP_SHIFTS}` MISSING")
        return
    strings = {"faulted": pooled["faulted"], "waiting_shelf": shifts["waiting_shelf"]}
    assert shifts["faulted"] == pooled["faulted"] and pooled["share"]["waiting_shelf"] == strings["waiting_shelf"]
    print("| shift | span, h | " + " | ".join(f"{b} ({std})" for b, std in BUCKETS)
          + " | throughput: jobs per robot-hour |")
    print("|---|---|" + "---|" * len(BUCKETS) + "---|")
    ss = sorted(shifts["shifts"].items(), key=lambda kv: int(kv[0]))
    for k, s in ss:
        tr = s["timebudget_robot"]
        assert sum(tr["seconds"].values()) == tr["span_s"], k
        share = dict(tr["share"], **strings)
        print(f"| {k}: {s['name']} | {tr['span_s'] / 3600:.2f} | " + " | ".join(_pct(share, b) for b, _ in BUCKETS)
              + f" | {s['jobs_per_robot_hour']:.2f} |")
    num = {b: v for b, v in pooled["seconds"].items() if not isinstance(v, str)}
    assert sum(num.values()) == pooled["span_s"]
    assert all(sum(s["timebudget_robot"]["seconds"][b] for _, s in ss) == v for b, v in num.items())
    print(f"| **pooled, {pooled['shifts']} shifts** | {pooled['span_s'] / 3600:.2f} | "
          + " | ".join(_pct(pooled["share"], b) for b, _ in BUCKETS) + f" | {pooled['jobs_per_robot_hour']:.2f} |")
    print()
    lab, c = pooled["label"], pooled["label"]["counts"]
    lsec = lab["seconds_per_bucket"]
    stuck_by_shift = {k: s["timebudget_robot"]["seconds"]["stuck"] for k, s in ss}
    top = max(stuck_by_shift, key=stuck_by_shift.get)
    on_station = sum(f["on_station_cell"] for f in lab["false_alarms"])
    st_dur = sorted(f["duration_s"] for f in lab["false_alarms"] if f["on_station_cell"])
    would = {}
    for _, s in ss:
        for b, v in s["no_data"]["would_have_been_bucket_without_gap_rule"].items():
            would[b] = would.get(b, 0) + v
    assert sum(would.values()) == num["no_data"], would
    assert len(lab["false_alarms"]) == c["false_alarms"]
    hf, prm = pooled["src"]["hf"], pooled["src"]["params"]
    print(f"**Against the robot's own label.** The stuck bucket holds {num['stuck']:,} s of the pooled "
          f"{pooled['span_s']:,} s; {stuck_by_shift[top]:,} of them are in shift {top} "
          f"({shifts['shifts'][top]['name']}, a manual intervention per the S13A lane report). The robot's stuck "
          f"label (`stuck_reason` not None) covers {sum(lsec.values())} s, of which {lsec['stuck']} s fall in the "
          f"stuck bucket. Of its {c['episodes']} episodes, {c['lt30']} are shorter than the {prm['stuck_after_s']} s "
          f"threshold; the {c['ge30']} longer ones are both detected ({c['hits']} hits, {c['misses']} misses), too "
          f"few for a rate. Of the detector's {c['stuck_runs']} stuck runs, {c['false_alarms']} have no label within {prm['stuck_after_s']} s, "
          f"and {on_station} of those {c['false_alarms']} sit on a station cell "
          f"(median {st_dur[(len(st_dur) - 1) // 2]} s, a dwell just over the threshold). "
          "Failed navigation: no label in the data. The closest is the operations that ended in TIMEOUT: "
          f"{c['timeouts']}, all {c['timeouts_detected']} overlapped by a stuck run (the lane report finds only 2 of "
          "them overlap a run off a station cell, `laptop-scheduler/reports/wr-lane-s13a-moroop-budget.md` section 5 (d), "
          f"not stored). Paused (joystick or non-autonomous rows): {num['paused']} s. `faulted` is \"" + pooled["faulted"] + "\" (the diagnostics levels "
          "are undocumented) and `waiting_shelf` is \"" + shifts["waiting_shelf"] + "\" (no shelves, no picker). "
          f"`no_data` is mostly station dwell: the log stores a row only when a value changes, and the {prm['max_gap_s']} "
          f"s rule moved {num['no_data']:,} s there, {would.get('waiting_station', 0):,} of which would otherwise be "
          f"waiting_station (`shifts.*.no_data.would_have_been_bucket_without_gap_rule`).")
    print()
    print(f"**Data.** MoRoOp ({hf['paper']}, licence {hf['license'].upper().replace('CC-BY-', 'CC BY ')}), "
          f"`{hf['repo']}` revision {hf['revision']}: one wheel.me AMR in a lab, {pooled['shifts']} shifts, "
          f"{pooled['messages']:,} messages, {pooled['parse_rejects']} parse rejects. Shares are of the shift's span "
          "(`timebudget_robot.share` per shift, `share` pooled; the pooled row sums the nine per-shift runs). The "
          "station share is set by the job generator's dwell and is not a finding. **Limit:** one robot, so no "
          "deadlock, congestion or hotspot result. Sources: "
          f"`{MOROOP}` (`seconds`, `share`, `label`, `no_data`, `src.hf`), `{MOROOP_SHIFTS}` "
          "(`shifts.*.timebudget_robot`, `shifts.*.jobs_per_robot_hour`), from the S13A lane (PR #49).")


def _st(rel):
    """The station-aware twin of a results file: results/fleet/x.json -> results/fleet/x-st.json."""
    return rel[:-len(".json")] + "-st.json"


def _old_truth(tag):
    """(path, doc) of the station-unaware file that carries `truth_kinds` for this run: the hotspot JSON, else the S10D
    baselines JSON (same scorer, same costmap; the s8b and sticky hotspot JSONs on disk predate or lack it)."""
    for rel in (f"results/fleet/hotspot_{tag}.json", f"results/fleet/baselines_{tag}.json"):
        d = load(rel)
        if d is not None and "any" in d.get("truth_kinds", {}):
            return rel, d
    return None, None


def station_aware():
    tags = [t for t, _ in S12_RUNS]
    rows = []

    def row(measure, run, old, new, dl, files):
        rows.append(f"| {measure} | {run} | {old} | {new} | {dl} | {', '.join(f'`{f}`' for f in files)} |")

    def num(o, n, fmt):
        return format(o, fmt), format(n, fmt), "n/a" if o is None else format(n - o, "+" + fmt)

    # top-20 truth precision, run level (f), (h), (i), (m), S8B
    for t in tags:
        orel, o = _old_truth(t)
        nrel = f"results/fleet/hotspot_{t}-st.json"
        n = load(nrel)
        assert o["zones"] == n["zones"], t  # the final map is the same cells, same costs
        oa, na = o["truth_kinds"]["any"], n["truth_kinds"]["any"]
        ok, nk = oa["k"]["20"], na["k"]["20"]
        assert oa["positives"] == na["positives"], t
        if na["positives"] == 0:
            row("top-20 truth precision", t, f"{ok['precision']:.3f} (no truth cells)",
                f"{nk['precision']:.3f} (no truth cells)", f"{nk['precision'] - ok['precision']:+.3f}", [orel, nrel])
            continue
        row("top-20 truth precision (hits / truth cells)", t, f"{ok['precision']:.3f} ({ok['hits']} / {oa['positives']})",
            f"{nk['precision']:.3f} ({nk['hits']} / {na['positives']})", f"{nk['precision'] - ok['precision']:+.3f}",
            [orel, nrel])
    # frozen truth cells (m)
    orel, nrel = "results/fleet/hotspot_s10-breakdown.json", "results/fleet/hotspot_s10-breakdown-st.json"
    o, n = load(orel), load(nrel)
    of, nf = o["truth_kinds"]["frozen"], n["truth_kinds"]["frozen"]
    row("frozen cells hit at K 20 / frozen cells (m)", "s10-breakdown", f"{of['k']['20']['hits']} / {of['cells']}",
        f"{nf['k']['20']['hits']} / {nf['cells']}", f"{nf['k']['20']['hits'] - of['k']['20']['hits']:+d}", [orel, nrel])
    # forecast truth grades: the ungated rows of (l) and the time-matched row of (m)
    for t in ("s10-none", "s10c-blind", "s10-breakdown"):
        orel, nrel = f"results/fleet/hotspot_{t}.json", f"results/fleet/hotspot_{t}-st.json"
        og, ng = load(orel)["grading_counts"]["truth"], load(nrel)["grading_counts"]["truth"]
        oh, nh = og.get("hit", 0), ng.get("hit", 0)
        row("ungated forecasts: truth hits / graded (l), (m)", t, f"{oh} / {oh + og.get('false_alarm', 0)}",
            f"{nh} / {nh + ng.get('false_alarm', 0)}", f"{nh - oh:+d} hits", [orel, nrel])
    for t in ("s10-none", "s10c-blind", "closed-loop-sticky"):
        row("gated forecasts, baseline and persistence gate (l)", t, "see (l)", "not rerun", "n/a",
            [f"results/fleet/hotspot_{t}-gate-{g}.json" for g in GATES])
    # S10D paired verdict (j)
    for t in tags + ["s8e-long-w0.5"]:
        orel = f"results/fleet/baselines_{t}.json"
        nrel = _st(orel)
        o, n = load(orel), load(nrel)
        if n is None:
            row("S10D map - persistence, truth precision, K 20 / K 40 (j)", t, "see (j)", "not rerun", "n/a", [orel])
            continue
        cells = []
        for d in (o, n):
            if d is None:
                cells.append("n/a (no station-unaware file)")
                continue
            parts = []
            for k in S10_KS:
                dl, v = _paired(d["baselines"]["paired"][k]["truth_precision"], d, k, "truth_precision")
                parts.append(f"K {k}: {dl}, {v}")
            cells.append("; ".join(parts))
        if o is None:
            dl = "n/a"
        else:
            for key in ("k", "paired", "chance"):
                assert o["baselines"][key] == n["baselines"][key], (t, key)
            dl = "unchanged (`k`, `paired`, `chance` blocks equal)"
        row("S10D map - persistence, truth precision, K 20 / K 40 (j)", t, cells[0], cells[1], dl,
            [r for r, d in ((orel, o), (nrel, n)) if d is not None])
    # lesson_persist against chance (e), (j)
    for t in ("s10-none", "s10c-blind"):
        orel, nrel = f"results/fleet/hotspot_{t}.json", f"results/fleet/hotspot_{t}-st.json"
        ol, nl = load(orel)["lesson_persist_chance"], load(nrel)["lesson_persist_chance"]
        assert load(_st(f"results/fleet/baselines_{t}.json"))["baselines"]["lesson_persist"] == dict(
            load(f"results/fleet/baselines_{t}.json")["baselines"]["lesson_persist"],
            n_hot_robot_excluded=load(_st(f"results/fleet/baselines_{t}.json"))["baselines"]["lesson_persist"][
                "n_hot_robot_excluded"]), t  # the hot_cell lessons of (j) are unchanged
        row("lesson_persist, hot_cell and hot_robot lessons as in (f): held / graded, lift over chance", t,
            f"{ol['observed_ok']} / {ol['n_lessons']}, lift {ol['lift']:.2f}",
            f"{nl['observed_ok']} / {nl['n_lessons']}, lift {nl['lift']:.2f}", f"lift {nl['lift'] - ol['lift']:+.2f}",
            [orel, nrel])
    # AMOC (k), (n)
    orel = AMOC
    nrel = _st(orel)
    o, n = load(orel), load(nrel)
    assert o["amoc"] == n["amoc"] and o["by_k"] == n["by_k"]
    assert n["meta"]["phase_a_dir"].endswith("-st") and n["meta"]["reference_dir"].endswith("-st")
    ok = next(r for r in o["amoc"]["k"] if r["K"] == 20)
    nk = next(r for r in n["amoc"]["k"] if r["K"] == 20)
    row("AMOC, decayed map K 20: detected while open / windows (k)", "s10c-blind", f"{ok['n_detected']} / {ok['n_windows']}",
        f"{nk['n_detected']} / {nk['n_windows']}", f"{nk['n_detected'] - ok['n_detected']:+d}", [orel, nrel])
    row("AMOC, decayed map K 20: false alarms per zone-hour, s10-none / s10c-blind outside windows (k)", "s10c-blind",
        f"{ok['fa_per_hour_reference']:.1f} / {ok['fa_per_hour_measured_outside_windows']:.1f}",
        f"{nk['fa_per_hour_reference']:.1f} / {nk['fa_per_hour_measured_outside_windows']:.1f}",
        "unchanged (`amoc` and `by_k` blocks equal)", [orel, nrel])
    row("CUSUM and short-memory map (n)", "s10c-blind", "see (n)", "not rerun", "n/a",
        ["results/fleet/amoc_fast.json", "results/fleet/amoc_shortmap.json"])
    # time budget (o)
    for t in tags:
        orel = f"results/fleet/timebudget_{t}.json"
        nrel = _st(orel)
        o, n = load(orel), load(nrel)
        assert n["src"]["station_aware"] is True and n["src"]["station_radius"] == 0, t
        os_, ns = o["run"]["totals"]["share"]["stuck"], n["run"]["totals"]["share"]["stuck"]
        row("time budget: stuck share of AGV time (o)", t, f"{100 * os_:.2f}%", f"{100 * ns:.2f}%",
            f"{100 * (ns - os_):+.2f} pts", [orel, nrel])
        ow, nw = o["run"]["station_waits_in_stall_list"], n["run"]["station_waits_in_stall_list"]
        row("stall list: episodes starting on a station cell / episodes (o)", t,
            f"{ow['at_station']} / {ow['episodes']}", f"{nw['at_station']} / {nw['episodes']}",
            f"{nw['episodes'] - ow['episodes']:+d} episodes", [orel, nrel])
    # blocking clusters (p)
    ref = {}
    for t in tags:
        orel = f"results/fleet/deadlock_{t}.json"
        nrel = _st(orel)
        o, n = load(orel), load(nrel)
        assert n["station_rule"]["radius"] == 0, t
        nt = n["total"]
        ot = _as_v1(o)["total"] if o is not None else None
        if t == "s10-none":
            ref = {"old": ot["deadlock_s_per_robot_hour"], "new": nt["blocked_s_per_robot_hour"]}
        files = [r for r, d in ((orel, o), (nrel, n)) if d is not None]
        if ot is None:
            row("blocking clusters; blocked robot-s per robot-hour (x s10-none) (p)", t, "n/a (no station-unaware run)",
                f"{nt['blocking_clusters']}; {nt['blocked_s_per_robot_hour']:.1f} "
                f"({nt['blocked_s_per_robot_hour'] / ref['new']:.2f}x)", "n/a", files)
            continue
        orate, nrate = ot["deadlock_s_per_robot_hour"], nt["blocked_s_per_robot_hour"]
        row("blocking clusters; blocked robot-s per robot-hour (x s10-none) (p)", t,
            f"{ot['deadlocks']}; {orate:.1f} ({orate / ref['old']:.2f}x)",
            f"{nt['blocking_clusters']}; {nrate:.1f} ({nrate / ref['new']:.2f}x)",
            f"{nt['blocking_clusters'] - ot['deadlocks']:+d}; {nrate - orate:+.1f}", files)
    # MoRoOp (q)
    orel, nrel, lrel = MOROOP, _st(MOROOP), "results/fleet/moroop_label-st.json"
    shrel, nshrel = MOROOP_SHIFTS, _st(MOROOP_SHIFTS)
    o, n, lab = load(orel), load(nrel), load(lrel)
    r = n["src"]["station_rule"]["radius"]
    assert lab["station_radius"] == r and lab["pooled"]["counts"] == n["label"]["counts"]
    run = f"MoRoOp, 9 shifts (radius {r})"
    row("stuck share of the span; stuck s (q)", run, f"{100 * o['share']['stuck']:.2f}%; {o['seconds']['stuck']:.0f}",
        f"{100 * n['share']['stuck']:.3f}%; {n['seconds']['stuck']:.0f}",
        f"{n['seconds']['stuck'] - o['seconds']['stuck']:+.0f} s", [orel, nrel])
    osh, nsh = load(shrel)["shifts"], load(nshrel)["shifts"]
    for b in ("stuck", "stopped_short"):
        ov, nv = osh["6"]["timebudget_robot"]["seconds"][b], nsh["6"]["timebudget_robot"]["seconds"][b]
        row(f"shift 6 (2026_07_30_morning, the manual intervention): {b} s (q)", run, f"{ov:.0f}", f"{nv:.0f}",
            f"{nv - ov:+.0f}", [shrel, nshrel])
    oc, nc = o["label"]["counts"], n["label"]["counts"]
    for key, what in (("stuck_runs", "detector stuck runs"), ("false_alarms", "stuck runs with no label within 30 s"),
                      ("hits", "label episodes >= 30 s detected"), ("timeouts_detected", "TIMEOUT operations overlapped "
                                                                                          "by a stuck run")):
        den = {"hits": "ge30", "timeouts_detected": "timeouts"}.get(key)
        ov = f"{oc[key]}" + (f" / {oc[den]}" if den else "")
        nv = f"{nc[key]}" + (f" / {nc[den]}" if den else "")
        row(f"{what} (q)", run, ov, nv, f"{nc[key] - oc[key]:+d}", [orel, nrel, lrel])
    on_st = [sum(1 for f in d["label"]["false_alarms"] if f["on_station_cell"]) for d in (o, n)]
    row("unlabelled stuck runs on a station cell (q)", run, f"{on_st[0]}", f"{on_st[1]}", f"{on_st[1] - on_st[0]:+d}",
        [orel, nrel])

    print("| measure | run | old rule | station-aware | delta | files |")
    print("|---|---|---|---|---|---|")
    print("\n".join(rows))
    print()
    print("Old rule = the station-unaware detector of Sprints 5 to 13A; station-aware = S13B (PR #50): a stopped run "
          "whose first stopped cell is within the station radius of a station goal cell becomes SERVICING after the "
          "30 s threshold, not a stuck episode. Simulator runs: stations `auto` from the emit ledger, radius 0 "
          "(asserted: `src.station_radius`, `station_rule.radius`); MoRoOp: `fleet/data/moroop/stations.json`, "
          f"radius {r} (asserted). The station-aware files come from queue item `wr-s13b-rerun`, which rebuilt each "
          "store as `store-st` with `ingest --stations auto` and re-ran costmap, lessons, grade, hotspot_score, "
          "baselines, timebudget and deadlock on it, with the original publish schedules and lesson windows, and "
          "checked that no original store or results file changed. Unchanged rows are asserted, not eyeballed: the "
          "final map (`zones`) is equal in every run, and the S10D `k`, `paired` and `chance` blocks and the AMOC "
          "`amoc` and `by_k` blocks are equal. Old top-20 precision for s8b-medium-80-p03-07 and closed-loop-sticky "
          "is read from the S10D baselines JSON, because their hotspot JSON on disk predates `truth_kinds` (s8b) or "
          "does not exist (sticky). The sticky baselines files differ in `params.horizon_s` (3600 old, 1245 new); "
          "the asserted blocks are equal anyway. s10-breakdown has no station-unaware S10D file and s8b no "
          "station-unaware blocking run, so those rows have no old value. The ratio in the blocking rows is the run's "
          "rate over the s10-none rate under the same rule. The lesson_persist rows pool hot_cell and hot_robot lessons, as "
          "(f) does (`lesson_persist_chance`); the hot_cell-only block of (j) (`baselines.lesson_persist`) is equal "
          "under both rules except `n_hot_robot_excluded` (asserted). MoRoOp unlabelled runs on a station cell are "
          "counted from `label.false_alarms[].on_station_cell`.")


def _sb(rel):
    """The bounded twin of a station-aware results file: results/fleet/x-st.json -> results/fleet/x-sb.json."""
    assert rel.endswith("-st.json"), rel
    return rel[:-len("-st.json")] + "-sb.json"


def _causes_rows(run, c, out):
    for r in c["table"]:
        out.append(f"| {run} | `{r['cause']}` | {r['cause_label']} | {r['episodes']} | {r['seconds']:,} | "
                   f"{r['share']:.3f} |")
    tot = "n/a" if c["share_total"] is None else f"{c['share_total']:.2f}"
    out.append(f"| {run} | **all** | episode seconds {c['episode_seconds']:,} / stuck bucket {c['stuck_bucket_s']:,} s "
               f"(open episodes not counted: {c['uncounted_open_episodes']}) | {sum(r['episodes'] for r in c['table'])} "
               f"| {c['episode_seconds']:,} | {tot} |")


def bounded():
    tags = [t for t, _ in S12_RUNS]
    rows = []

    def row(measure, run, old, new, dl, files):
        rows.append(f"| {measure} | {run} | {old} | {new} | {dl} | {', '.join(f'`{f}`' for f in files)} |")

    def pair(rel_st):
        return rel_st, _sb(rel_st), load(rel_st), load(_sb(rel_st))

    # hotspot side: top-20 truth precision, frozen cells, forecast grades, lesson_persist (f), (h), (i), (l), (m)
    for t in tags:
        orel, nrel, o, n = pair(f"results/fleet/hotspot_{t}-st.json")
        for key in ("zones", "truth_kinds", "grading_counts", "lesson_persist_chance"):
            assert o.get(key) == n.get(key), (t, key)
        oa, na = o["truth_kinds"]["any"], n["truth_kinds"]["any"]
        ok, nk = oa["k"]["20"], na["k"]["20"]
        if na["positives"] == 0:
            row("top-20 truth precision", t, f"{ok['precision']:.3f} (no truth cells)",
                f"{nk['precision']:.3f} (no truth cells)", f"{nk['precision'] - ok['precision']:+.3f}", [orel, nrel])
            continue
        row("top-20 truth precision (hits / truth cells)", t, f"{ok['precision']:.3f} ({ok['hits']} / {oa['positives']})",
            f"{nk['precision']:.3f} ({nk['hits']} / {na['positives']})", f"{nk['precision'] - ok['precision']:+.3f}",
            [orel, nrel])
    orel, nrel, o, n = pair("results/fleet/hotspot_s10-breakdown-st.json")
    of, nf = o["truth_kinds"]["frozen"], n["truth_kinds"]["frozen"]
    row("frozen cells hit at K 20 / frozen cells (m)", "s10-breakdown", f"{of['k']['20']['hits']} / {of['cells']}",
        f"{nf['k']['20']['hits']} / {nf['cells']}", f"{nf['k']['20']['hits'] - of['k']['20']['hits']:+d}", [orel, nrel])
    for t in ("s10-none", "s10c-blind", "s10-breakdown"):
        orel, nrel, o, n = pair(f"results/fleet/hotspot_{t}-st.json")
        og, ng = o["grading_counts"]["truth"], n["grading_counts"]["truth"]
        oh, nh = og.get("hit", 0), ng.get("hit", 0)
        row("ungated forecasts: truth hits / graded (l), (m)", t, f"{oh} / {oh + og.get('false_alarm', 0)}",
            f"{nh} / {nh + ng.get('false_alarm', 0)}", f"{nh - oh:+d} hits", [orel, nrel])
    for t in ("s10-none", "s10c-blind", "closed-loop-sticky"):
        row("gated forecasts, baseline and persistence gate (l)", t, "not rerun (see (l), (r))", "not rerun", "n/a",
            [f"results/fleet/hotspot_{t}-gate-{g}.json" for g in GATES])
    # S10D (j)
    for t in tags:
        orel, nrel, o, n = pair(f"results/fleet/baselines_{t}-st.json")
        for key in ("k", "paired", "chance", "lesson_persist"):
            assert o["baselines"][key] == n["baselines"][key], (t, key)
        cells = []
        for d in (o, n):
            parts = []
            for k in S10_KS:
                dl, v = _paired(d["baselines"]["paired"][k]["truth_precision"], d, k, "truth_precision")
                parts.append(f"K {k}: {dl}, {v}")
            cells.append("; ".join(parts))
        row("S10D map - persistence, truth precision, K 20 / K 40 (j)", t, cells[0], cells[1],
            "unchanged (`k`, `paired`, `chance`, `lesson_persist` blocks equal)", [orel, nrel])
    row("S10D map - persistence, truth precision, K 20 / K 40 (j)", "s8e-long-w0.5", "not rerun", "not rerun", "n/a",
        ["results/fleet/baselines_s8e-long-w0.5.json"])
    for t in ("s10-none", "s10c-blind"):
        orel, nrel, o, n = pair(f"results/fleet/hotspot_{t}-st.json")
        ol, nl = o["lesson_persist_chance"], n["lesson_persist_chance"]
        row("lesson_persist, hot_cell and hot_robot lessons as in (f): held / graded, lift over chance", t,
            f"{ol['observed_ok']} / {ol['n_lessons']}, lift {ol['lift']:.2f}",
            f"{nl['observed_ok']} / {nl['n_lessons']}, lift {nl['lift']:.2f}", f"lift {nl['lift'] - ol['lift']:+.2f}",
            [orel, nrel])
    # AMOC (k)
    orel, nrel, o, n = pair(_st(AMOC))
    assert o["amoc"] == n["amoc"] and o["by_k"] == n["by_k"]
    assert n["meta"]["phase_a_dir"].endswith("-sb") and n["meta"]["reference_dir"].endswith("-sb")
    ok = next(r for r in o["amoc"]["k"] if r["K"] == 20)
    nk = next(r for r in n["amoc"]["k"] if r["K"] == 20)
    row("AMOC, decayed map K 20: detected while open / windows (k)", "s10c-blind", f"{ok['n_detected']} / {ok['n_windows']}",
        f"{nk['n_detected']} / {nk['n_windows']}", f"{nk['n_detected'] - ok['n_detected']:+d}", [orel, nrel])
    row("AMOC, decayed map K 20: false alarms per zone-hour, s10-none / s10c-blind outside windows (k)", "s10c-blind",
        f"{ok['fa_per_hour_reference']:.1f} / {ok['fa_per_hour_measured_outside_windows']:.1f}",
        f"{nk['fa_per_hour_reference']:.1f} / {nk['fa_per_hour_measured_outside_windows']:.1f}",
        "unchanged (`amoc` and `by_k` blocks equal)", [orel, nrel])
    row("CUSUM and short-memory map (n)", "s10c-blind", "not rerun (see (n), (r))", "not rerun", "n/a",
        ["results/fleet/amoc_fast.json", "results/fleet/amoc_shortmap.json"])
    # time budget (o), with the overrun bookkeeping asserted: what the bound moves is exactly its overrun episodes
    bounds, causes, moved = [], [], {}
    for t in tags:
        orel, nrel, o, n = pair(f"results/fleet/timebudget_{t}-st.json")
        assert n["src"]["station_aware"] is True and n["src"]["station_radius"] == 0, t
        os_, ns = o["run"]["totals"]["share"]["stuck"], n["run"]["totals"]["share"]["stuck"]
        row("time budget: stuck share of AGV time (o)", t, f"{100 * os_:.2f}%", f"{100 * ns:.2f}%",
            f"{100 * (ns - os_):+.2f} pts", [orel, nrel])
        ow, nw = o["run"]["station_waits_in_stall_list"], n["run"]["station_waits_in_stall_list"]
        row("stall list: episodes starting on a station cell / episodes (o)", t,
            f"{ow['at_station']} / {ow['episodes']}", f"{nw['at_station']} / {nw['episodes']}",
            f"{nw['episodes'] - ow['episodes']:+d} episodes", [orel, nrel])
        c = n["run"]["totals"]["causes"]
        ov = next((r for r in c["table"] if r["cause"] == "station_overrun"), {"episodes": 0, "seconds": 0})
        osec, nsec = o["run"]["totals"]["seconds"], n["run"]["totals"]["seconds"]
        assert nsec["stuck"] - osec["stuck"] == ov["seconds"] == osec["waiting_station"] - nsec["waiting_station"], t
        assert nw["episodes"] - ow["episodes"] == ov["episodes"], t
        assert all(nsec[b] == osec[b] for b in nsec if b not in ("stuck", "waiting_station")), t
        moved[t] = (ov["episodes"], ov["seconds"], osec["stuck"], nsec["stuck"])
        bounds.append((t, n, nrel))
        causes.append((t, c))
    # blocking clusters (p)
    ref = {}
    for t in tags:
        orel, nrel, o, n = pair(f"results/fleet/deadlock_{t}-st.json")
        ot, nt = o["total"], n["total"]
        if t == "s10-none":
            ref = {"old": ot["blocked_s_per_robot_hour"], "new": nt["blocked_s_per_robot_hour"]}
        orate, nrate = ot["blocked_s_per_robot_hour"], nt["blocked_s_per_robot_hour"]
        row("blocking clusters; blocked robot-s per robot-hour (x s10-none) (p)", t,
            f"{ot['blocking_clusters']}; {orate:.1f} ({orate / ref['old']:.2f}x)",
            f"{nt['blocking_clusters']}; {nrate:.1f} ({nrate / ref['new']:.2f}x)",
            f"{nt['blocking_clusters'] - ot['blocking_clusters']:+d}; {nrate - orate:+.1f}", [orel, nrel])
    # MoRoOp (q)
    orel, nrel, o, n = pair(_st(MOROOP))
    lorel, lrel, lo, lab = pair("results/fleet/moroop_label-st.json")
    shrel, nshrel, osh, nsh = pair(_st(MOROOP_SHIFTS))
    r = lab["station_radius"]
    assert r == lo["station_radius"] == n["src"]["station_rule"]["radius"]
    assert lab["pooled"]["counts"] == n["label"]["counts"] and lab["pooled"]["causes"] == n["label"]["causes"]
    run = f"MoRoOp, 9 shifts (radius {r})"
    row("stuck share of the span; stuck s (q)", run, f"{100 * o['share']['stuck']:.3f}%; {o['seconds']['stuck']:.0f}",
        f"{100 * n['share']['stuck']:.3f}%; {n['seconds']['stuck']:.0f}",
        f"{n['seconds']['stuck'] - o['seconds']['stuck']:+.0f} s", [orel, nrel])
    for b in ("stuck", "stopped_short"):
        ov, nv = osh["shifts"]["6"]["timebudget_robot"]["seconds"][b], nsh["shifts"]["6"]["timebudget_robot"]["seconds"][b]
        row(f"shift 6 (2026_07_30_morning, the manual intervention): {b} s (q)", run, f"{ov:.0f}", f"{nv:.0f}",
            f"{nv - ov:+.0f}", [shrel, nshrel])
    oc, nc = lo["pooled"]["counts"], lab["pooled"]["counts"]
    for key, what in (("stuck_runs", "detector stuck runs"), ("false_alarms", "stuck runs with no label within 30 s"),
                      ("hits", "label episodes >= 30 s detected"), ("timeouts_detected", "TIMEOUT operations overlapped "
                                                                                          "by a stuck run")):
        den = {"hits": "ge30", "timeouts_detected": "timeouts"}.get(key)
        ov = f"{oc[key]}" + (f" / {oc[den]}" if den else "")
        nv = f"{nc[key]}" + (f" / {nc[den]}" if den else "")
        row(f"{what} (q)", run, ov, nv, f"{nc[key] - oc[key]:+d}", [lorel, lrel])
    on_st = [sum(1 for f in d["pooled"]["false_alarms"] if f["on_station_cell"]) for d in (lo, lab)]
    row("unlabelled stuck runs on a station cell (q)", run, f"{on_st[0]}", f"{on_st[1]}", f"{on_st[1] - on_st[0]:+d}",
        [lorel, lrel])

    print("| measure | run | station-aware (r) | bounded (S14A) | delta | files |")
    print("|---|---|---|---|---|---|")
    print("\n".join(rows))
    print()
    print("**The bound per run, as the files record it** (`servicing_max_s`, `servicing_sample_n`, `servicing_q1_s`, "
          "`servicing_q3_s`, `servicing_pooling`):\n")
    print("| run | bound T, s | stops in the sample | Q1, s | Q3, s | pooling | file |")
    print("|---|---|---|---|---|---|---|")
    for t, n, rel in bounds:
        print(f"| {t} | {n['servicing_max_s']:.0f} | {n['servicing_sample_n']} | {n['servicing_q1_s']:.0f} | "
              f"{n['servicing_q3_s']:.0f} | {n['servicing_pooling']} | `{rel}` |")
    assert all(len(lab[k]) == 9 for k in ("servicing_max_s", "servicing_sample_n", "servicing_q1_s", "servicing_q3_s"))
    print(f"| MoRoOp, shifts 0-8 | {', '.join(f'{x:.0f}' for x in lab['servicing_max_s'])} | "
          f"{', '.join(str(x) for x in lab['servicing_sample_n'])} | {', '.join(f'{x:.1f}' for x in lab['servicing_q1_s'])} | "
          f"{', '.join(f'{x:.1f}' for x in lab['servicing_q3_s'])} | {lab['servicing_pooling']} | `{lrel}` |")
    print()
    print("**Causes per run** (`causes` block; share = cause seconds / the time budget's stuck bucket, the file's "
          "`denominator`; `share_total` is the sum of the shares):\n")
    print("| run | cause | cause_label | episodes | episode seconds | share of the stuck bucket |")
    print("|---|---|---|---|---|---|")
    out = []
    for t, c in causes:
        _causes_rows(t, c, out)
    _causes_rows(f"MoRoOp, pooled (radius {r})", lab["pooled"]["causes"], out)
    print("\n".join(out))
    print()
    ovs = lab["pooled"]["overruns"]
    assert [x for x in ovs] == [dict(x, shift=int(k)) for k, s in sorted(lab["shifts"].items(), key=lambda kv: int(kv[0]))
                                for x in s["overruns"]]
    fa = {f["start"]: f for f in lab["pooled"]["false_alarms"]}
    print("**MoRoOp overruns** (`pooled.overruns`; the last two columns from `pooled.false_alarms` by start):\n")
    print("| shift | start | duration, s | station cell | overlaps a TIMEOUT operation | label within 30 s | "
          "first cell is a station cell |")
    print("|---|---|---|---|---|---|---|")
    for x in ovs:
        f = fa.get(x["start"])
        print(f"| {x['shift']} | {x['start']} | {x['duration_s']:,} | {x['station_cell']} | "
              f"{'yes' if x['overlaps_timeout_operation'] else 'no'} | {'no (false alarm)' if f else 'yes'} | "
              f"{'n/a' if f is None else ('yes' if f['on_station_cell'] else 'no, within radius')} |")
    print()
    s6 = nsh["shifts"]["6"]
    would = s6["no_data"]["would_have_been_bucket_without_gap_rule"]
    print(f"Station-aware = S13B, the rows of (r); bounded = S14A (PR #51): a SERVICING run still stopped at T after the "
          f"stop began becomes a stuck episode with cause `station_overrun`. T is set per run from the run's own station "
          f"stops (`--servicing-max-s auto`). The files come from queue item `wr-s14a-rerun`. It rebuilt each store as `store-sb` "
          f"with the flag and re-ran costmap, lessons, grade, hotspot_score, baselines, timebudget, deadlock and "
          f"the MoRoOp analysis on it. Same radius as (r): 0 on the simulator, {r} on MoRoOp (asserted). Unchanged "
          "rows are asserted, not eyeballed: `zones`, `truth_kinds`, `grading_counts` and `lesson_persist_chance` of "
          "every hotspot file, the S10D `k`, `paired`, `chance` and `lesson_persist` blocks, and the AMOC `amoc` and "
          "`by_k` blocks are equal under both rules. In each time budget the bound moves exactly its overrun "
          "episodes: stuck seconds rise and waiting_station seconds fall by the `station_overrun` seconds of the "
          "`causes` block, the stall list grows by its episode count, and every other bucket is equal (asserted). "
          f"Stuck seconds moved: " + "; ".join(f"{t} {m[2]:,} to {m[3]:,} s ({m[0]} overrun episodes, {m[1]:,} s)" for t, m in moved.items())
          + ". The bucket split of an overrun episode keeps the time budget's precedence, so its gap and paused "
          f"seconds stay in `no_data` and `paused`. In MoRoOp shift 6, {would['stuck']:,} s of `no_data` would "
          f"be stuck without the {o['src']['params']['max_gap_s']} s gap rule "
          "(`shifts.6.no_data.would_have_been_bucket_without_gap_rule`). The causes shares do not sum to 1, and "
          "nothing rescales them. Episode seconds span each whole episode. The stuck bucket is the time budget's "
          "per-second split, where shelf-adjacent stops are `waiting_shelf`, faulted seconds are `faulted` and "
          "gaps are `no_data`.")


def absence_vs_map():
    arms = [("decayed map K 20 (S10E)", AMOC), ("CUSUM (S10I)", "results/fleet/amoc_fast.json"),
            ("traffic absence, alpha 1e-3 (S14B default)", "results/fleet/amoc_absence.json")]
    sweep_rel = "results/fleet/amoc_absence_sweep.json"
    docs = [(name, rel, load(rel)) for name, rel in arms]
    sweep = load(sweep_rel)
    if any(d is None for _, _, d in docs) or sweep is None:
        print("Absence vs map: a results file is MISSING")
        return
    # the one sweep entry with an AMOC carries the meta the stubs lack; check it against the map and the CUSUM
    live = {a: d for a, d in sweep.items() if d.get("amoc") is not None}
    stubs = {a: d for a, d in sweep.items() if d.get("amoc") is None}
    m0 = docs[0][2]["meta"]
    for rel, d in [(rel, d) for _, rel, d in docs if d.get("amoc") is not None] + [(sweep_rel, d) for d in live.values()]:
        m = d["meta"]
        for f in ("phase_a_dir", "reference_dir", "run", "reference_run", "truth_kind", "n_windows", "steps", "zones",
                  "disturb", "sim_hours", "sim_hours_reference"):
            assert m[f] == m0[f], (rel, f)
        for f in ("store_hash", "reference_store_hash"):
            assert m[f + "_before"] == m[f + "_after"] == m0[f + "_before"], (rel, f)
    for a, d in live.items():
        assert d["detector"] == "absence" and set(d["meta"]["store_mode"].values()) == {"prebuilt"}, a
    for d in [docs[2][2]] + list(stubs.values()):
        assert d["detector"] == "absence" and d["measured_forecast_rows"] == 0 and d["amoc"] is None
    assert docs[2][2]["store_suffix"] == "absence"
    print("| detector | publish every, s (publishes) " + _amoc_head(m0))
    print("|---|---|---|---|---|---|---|---|")
    for name, rel, d in docs:
        if d["amoc"] is None:
            print(f"| {name} | n/a | no AMOC: {d['measured_forecast_rows']} forecast rows on {m0['run']} (store "
                  f"`store-{d['store_suffix']}`) | n/a | n/a | n/a | not in the file | not in the file |")
            continue
        m = d["meta"]
        r = next(x for x in d["amoc"]["k"] if x["K"] == 20)
        fmt = ".3f" if r["fa_per_hour_reference"] < 1 else ".1f"
        print(f"| {name} | {m['publish_every_s']} ({m['n_publishes']}) " + _amoc_row(20, r, fmt)[len("| 20 "):])
    print()
    print(f"**Alpha sweep** (`{sweep_rel}`, one entry per alpha; the AMOC rows by K where the entry has one):\n")
    print("| alpha | K (per zone) | publish every, s (publishes) " + _amoc_head(m0))
    print("|---|---|---|---|---|---|---|---|---|")
    for a in sorted(sweep, key=float, reverse=True):
        d = sweep[a]
        if d["amoc"] is None:
            print(f"| {a} | any | n/a | no AMOC: {d['measured_forecast_rows']} forecast rows on {m0['run']} "
                  f"(`store-{d['store_suffix']}`) | n/a | n/a | n/a | not in the file | not in the file |")
            continue
        m = d["meta"]
        for r in d["amoc"]["k"]:
            print(f"| {a} | {r['K']} | {m['publish_every_s']} ({m['n_publishes']}) " + _amoc_row(r["K"], r)[len(f"| {r['K']} "):])
    print()
    worst = {}
    for a, d in live.items():
        r = next(x for x in d["amoc"]["k"] if x["K"] == 20)
        z = max(r["fa_per_hour_reference_by_zone"], key=r["fa_per_hour_reference_by_zone"].get)
        worst[a] = (z, r["fa_per_hour_reference_by_zone"][z],
                    sum(1 for v in r["fa_per_hour_reference_by_zone"].values() if v == 0))
    pubs = sorted({d["meta"]["publish_every_s"] for _, _, d in docs if d["amoc"] is not None})
    print(f"Same measured run (`{m0['phase_a_dir']}`, {m0['n_windows']} planner-blind blocked windows) and reference "
          f"(`{m0['reference_dir']}`, undisturbed) for every row with an AMOC, and the same store hashes before and after "
          "(asserted). The absence detector (`fleet/absencemap.py`, PR #52) publishes into its own store copy. "
          "`time_to_detect` refuses a measured store with no forecast rows, so for an alpha that flags nothing "
          "the queue item `wr-s14b-amoc-run` writes a stub (`detector`, `store_suffix`, `measured_forecast_rows`, "
          "`amoc` null). The stub records the measured run only, so the reference false-alarm count is not in the "
          "file. Cadence differs: the decayed map publishes every "
          f"{pubs[-1]} s and the CUSUM and absence detectors every {pubs[0]} s. False alarms are flag-publishes per zone per "
          "simulated hour, so they scale with the publish rate. Reference false alarms at K 20 by zone: "
          + "; ".join(f"alpha {a}: zone {z} {v:.1f} per zone-hour, {nz} of {len(m0['zones'])} zones at 0"
                      for a, (z, v, nz) in worst.items())
          + ". Column definitions are those of (k). Sources: "
          + ", ".join(f"`{rel}`" for _, rel, _ in docs) + f", `{sweep_rel}`.")


def eight_hour():
    shifts = [("500 steps (S14B)", ""), ("8 hours (S14C)", "-8h")]
    arms = [("decayed map K 20 (S10E)", "blind", None), ("CUSUM (S10I)", "fast", "cusum"),
            ("traffic absence, alpha 1e-3 (S14B)", "absence", "absence")]
    rels = {(a, t): f"results/fleet/amoc_{a}{t}.json" for _, a, _ in arms for _, t in shifts}
    docs = {k: load(rel) for k, rel in rels.items()}
    if any(d is None for d in docs.values()):
        print("Eight-hour shift: a results file is MISSING")
        return
    # the map file of each shift carries the meta; every live arm of that shift must match it, stubs carry none
    maps = {t: docs[("blind", t)]["meta"] for _, t in shifts}
    for (a, t), d in docs.items():
        if d.get("amoc") is None:
            det = next(x for _, s, x in arms if s == a)
            assert det and d["detector"] == det and d["store_suffix"] == a and d["measured_forecast_rows"] == 0, rels[a, t]
            continue
        m = d["meta"]
        for f in ("phase_a_dir", "reference_dir", "run", "reference_run", "truth_kind", "n_windows", "steps", "zones",
                  "disturb", "sim_hours", "sim_hours_reference"):
            assert m[f] == maps[t][f], (rels[a, t], f)
        for f in ("store_hash", "reference_store_hash"):
            assert m[f + "_before"] == m[f + "_after"] == maps[t][f + "_before"], (rels[a, t], f)
    assert maps["-8h"]["steps"] == 5760 and maps["-8h"]["sim_hours"] == 8.0 and maps[""]["steps"] == 500
    for f in ("disturb", "env", "zones", "truth_kind"):
        assert maps["-8h"][f] == maps[""][f], f
    print("| detector | shift | publish every, s (publishes) | detected / windows | miss share "
          "| first detect, s, median (p25-p75) | stale_at_end share | false alarms per zone-hour, undisturbed reference "
          "| false alarms per zone-hour, blind run outside windows | file |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for name, a, _ in arms:
        for label, t in shifts:
            d, rel, m0 = docs[a, t], rels[a, t], maps[t]
            if d["amoc"] is None:
                print(f"| {name} | {label} | n/a | flagged nothing: {d['measured_forecast_rows']} forecast rows on "
                      f"{m0['run']}, 0 / {m0['n_windows']} | 1.00 | none | n/a | not in the file | not in the file "
                      f"| `{rel}` |")
                continue
            m = d["meta"]
            r = next(x for x in d["amoc"]["k"] if x["K"] == 20)
            fmt = ".3f" if r["fa_per_hour_reference"] < 1 else ".1f"
            print(f"| {name} | {label} | {m['publish_every_s']} ({m['n_publishes']}) "
                  + _amoc_row(20, r, fmt)[len("| 20 "):] + f" `{rel}` |")
    print()
    m8, m5 = maps["-8h"], maps[""]
    print(f"500-step rows: `{m5['phase_a_dir']}` ({m5['n_windows']} planner-blind blocked windows, {m5['sim_hours']:.2f} "
          f"simulated hours per zone) against `{m5['reference_dir']}`, the same rows as (t). 8-hour rows: "
          f"`{m8['phase_a_dir']}` ({m8['n_windows']} windows, median {m8['window_len_steps_median']} steps, "
          f"{m8['sim_hours']:g} simulated hours per zone, {len(m8['zones'])} zones x {m8['steps']:,} steps) against "
          f"`{m8['reference_dir']}`. Every live row of a shift has the same runs, windows and store hashes before and "
          "after as that shift's map row (asserted). The detectors, their defaults and the disturbance "
          f"({json.dumps(m8['disturb'])}) are those of (t); only the shift length and the seeds changed. K is 20 per "
          "zone for every live row. A stub (`amoc` null) means the detector wrote no forecast row on the blind run, so "
          "it detects 0 windows; it records the blind run only, so its reference false alarms are not in the file. "
          "Column definitions are those of (k). Reference false alarms per zone-hour at K 20 on the 8-hour run, by zone: "
          + "; ".join(f"{name.split(',')[0].split(' K ')[0]}: " + ", ".join(
              f"zone {z} {v:.1f}" for z, v in next(x for x in docs[a, '-8h']['amoc']['k'] if x['K'] == 20)
              ['fa_per_hour_reference_by_zone'].items())
              for name, a, _ in arms if docs[a, "-8h"]["amoc"] is not None) + ".")
    hits = {a: {(z, w["cell"], w["start_step"]) for z, ws in docs[a, "-8h"]["by_k"]["20"]["windows"].items()
                for w in ws if w["detected"]}
            for _, a, _ in arms if docs[a, "-8h"]["amoc"] is not None}
    if "absence" in hits:
        ab, mp = hits["absence"], hits["blind"]
        by_zone = {}
        for z, _, _ in ab:
            by_zone[z] = by_zone.get(z, 0) + 1
        print(f"\nWindow overlap on the 8-hour run at K 20 (`by_k.20.windows`): the absence test detects {len(ab - mp)} "
              f"windows the decayed map misses, the map {len(mp - ab)} that the absence test misses, both {len(ab & mp)}. "
              "Absence hits by zone: " + ", ".join(f"zone {z} {n}" for z, n in sorted(by_zone.items())) + ".")
        a20 = next(x for x in docs["absence", "-8h"]["amoc"]["k"] if x["K"] == 20)
        dom = [x for x in docs["blind", "-8h"]["amoc"]["k"]
               if x["n_detected"] >= a20["n_detected"] and x["fa_per_hour_reference"] <= a20["fa_per_hour_reference"]]
        print("Map rows of the K sweep that detect at least as many windows as the absence test at K 20 "
              f"({a20['n_detected']}) at no more reference false alarms ({a20['fa_per_hour_reference']:.1f}): "
              + ("; ".join(f"K {x['K']} {x['n_detected']} / {x['n_windows']} at {x['fa_per_hour_reference']:.1f}"
                           for x in dom) or "none") + f" (`{rels['blind', '-8h']}` `amoc.k`).")
        if docs["fast", "-8h"]["amoc"] is None:
            n = len(ab)
            print(f"Against the CUSUM, which detects none: {n} windows to 0, one-sided exact sign test p = 0.5^{n} = "
                  f"{0.5 ** n:.5f}.")


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
    print("\n### (l) The false-alarm gate (S10F): gate none / baseline / persistence\n")
    gate_table()
    print("\n### (m) Frozen truth cells on the breakdown run (S10G)\n")
    frozen_cells()
    print("\n### (n) Fast detector vs decayed map (S10I, planner-blind blockage)\n")
    fast_vs_map()
    print("\n### (o) Where the shift goes (S12A time budget)\n")
    time_budget()
    print("\n### (p) Blocking clusters and chains (S12B): a congestion measure, and message-loss cells\n")
    blocking_clusters()
    print("\n### (q) Sprint 13: a real shift (S13A, MoRoOp, one robot)\n")
    real_shift()
    print("\n### (r) The stuck rule knows where stations are (S13B): old / station-aware\n")
    station_aware()
    print("\n### (s) The station stop has an upper bound (S14A): station-aware / bounded\n")
    bounded()
    print("\n### (t) Traffic absence against the map and the CUSUM (S14B)\n")
    absence_vs_map()
    print("\n### (u) Eight-hour shift: map, CUSUM and absence on the blind blockage (S14C)\n")
    eight_hour()


if __name__ == "__main__":
    sys.exit(main())

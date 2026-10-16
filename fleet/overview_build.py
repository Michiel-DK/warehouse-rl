"""S8K-LANDING: build docs/overview/index.html, the landing page above the replay.

Reads exactly four tracked files and nothing else:
  docs/replay/data.js                                  (window.REPLAY = {...};)
  results/fleet/benchmark.json
  results/fleet/hotspot_s8b-medium-80-p03-07.json
  results/closed_loop_sticky/summary.json

Every number on the page is a <b class="num" data-src="<file>:<expression>"> element. resolve() turns a data-src into a
value, format_value() turns the value into the text shown. The template contains no typed number; per-item rows (example
stops, the lesson) are generated here from data. A build is deterministic (no clock) and refuses to write when a {name}
placeholder is left outside <script>/<style>.

    .venv/bin/python fleet/overview_build.py [--data F] [--results-root DIR] [--out F]
"""
import argparse
import html as htmllib
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOP_K = 20

DATA = "docs/replay/data.js"
BENCH = "results/fleet/benchmark.json"
HOT = "results/fleet/hotspot_s8b-medium-80-p03-07.json"
STICKY = "results/closed_loop_sticky/summary.json"
INPUTS = (DATA, BENCH, HOT, STICKY)

PLACEHOLDER = re.compile(r"\{[A-Za-z_][A-Za-z0-9_.]*\}")

# name -> (file, expression, kind). The expression grammar is in resolve(). Names must not contain digits (they sit in TEMPLATE).
W = "run_constants.worth"
NUMS = {
    "stuck_periods": (DATA, "len(episodes)", "int"),
    "robots": (DATA, "len(robots)", "int"),
    "shift_min": (DATA, "meta.steps*meta.step_seconds/60", "int"),
    "planted": (DATA, "len(obstacles)", "int"),
    "stuck_after": (BENCH, "batch.score.stuck_after", "int"),
    "n_examples": (DATA, "nexamples(episodes)", "int"),
    "msgs": (DATA, "run_constants.header.msgs", "int"),
    "noise": (DATA, "run_constants.header.noise", "int"),
    "read": (DATA, "run_constants.audit.read", "int"),
    "sent": (DATA, "run_constants.audit.sent", "int"),
    "n_changes": (DATA, "run_constants.kept.n_changes", "int"),
    "kept_pct": (DATA, "run_constants.kept.kept_pct", "pp1"),
    "n_repeats": (DATA, "run_constants.kept.n_repeats", "int"),
    "robot_rate": (DATA, "run_constants.speed.robot_rate", "f1"),
    "ingest_rate": (DATA, "run_constants.speed.ingest_rate", "int"),
    "ratio": (DATA, "run_constants.speed.ratio", "int"),
    "lag_median": (BENCH, "live.lag_p50_s", "f1"),
    "alert_median": (BENCH, "live.alert_latency_from_entry_p50_s", "int"),
    "recall": (BENCH, "batch.score.recall", "pct0"),
    "precision": (BENCH, "batch.score.precision", "pct0"),
    "bench_msgs": (BENCH, "batch.messages_expected", "mil1"),
    "hits_top": (DATA, "hits(publishes.-1.cells,obstacles,%d)" % TOP_K, "int"),
    "map_precision": (HOT, "mean.k.%d.precision" % TOP_K, "pct0"),
    "map_ceiling": (HOT, "1-mean.zero_stall_share", "pct0"),
    "lt_hit": (DATA, "run_constants.lessons_long.truth_hit", "int"),
    "lt_n": (DATA, "run_constants.lessons_long.truth_n", "int"),
    "held": (DATA, "run_constants.lessons_long.held", "int"),
    "graded": (DATA, "run_constants.lessons_long.graded", "int"),
    "persist_held": (DATA, "run_constants.lessons_long.persist_held", "int"),
    "persist_graded": (DATA, "run_constants.lessons_long.persist_graded", "int"),
    "n_seeds": (DATA, W + ".n_seeds", "int"),
    "map_share": (DATA, W + ".map_share", "pct1"),
    "map_share_lo": (DATA, W + ".map_share_ci95.0", "pct1"),
    "map_share_hi": (DATA, W + ".map_share_ci95.1", "pct1"),
    "oracle_share": (DATA, W + ".oracle_share", "pct1"),
    "oracle_share_lo": (DATA, W + ".oracle_share_ci95.0", "pct1"),
    "oracle_share_hi": (DATA, W + ".oracle_share_ci95.1", "pct1"),
    "fewer_drives": (STICKY, "1-arms.map_a32.floor_skip_steps_mean/arms.none.floor_skip_steps_mean", "pct0"),
}
BAR_KEYS = ("none", "map_a32", "oracle_a32", "undisturbed")
BAR_LABELS = ("Bad floor, no map", "With the analyser's map", "With perfect knowledge", "Clean floor")
for _i in range(4):
    for _f, _name in (("mean", "m"), ("ci95_low", "lo"), ("ci95_high", "hi")):
        NUMS["bar%d_%s" % (_i, _name)] = (DATA, "%s.bars.%d.%s" % (W, _i, _f), "f1")

KIND_BY_SRC = {"%s:%s" % (f, e): k for f, e, k in NUMS.values()}


# ------------------------------------------------------------------------------------------------ resolver
def load_inputs(data_path, results_root):
    """{input name: parsed JSON}; any missing or unreadable file raises."""
    results_root = Path(results_root)
    paths = {DATA: Path(data_path), BENCH: results_root / BENCH, HOT: results_root / HOT, STICKY: results_root / STICKY}
    out = {}
    for name, p in paths.items():
        text = p.read_text(encoding="utf-8")
        if name == DATA:
            text = text[text.index("{"):text.rindex("}") + 1]  # window.REPLAY = {...};
        out[name] = json.loads(text)
    return out


def _walk(obj, path):
    for seg in path.split("."):
        obj = obj[int(seg)] if isinstance(obj, list) else obj[seg]
    return obj


def _hits(cells, obstacles, k):
    planted = {o["cell"] for o in obstacles}
    return sum(1 for c in cells[:k] if c[0] in planted)


def example_stops(episodes):
    """One example per cause (most common cause first), the first one that is not cut off at the start of the shift."""
    order = Counter(e["cause"] for e in episodes).most_common()
    out = []
    for cause, _ in order:
        e = next((x for x in episodes if x["cause"] == cause and not x.get("left_censored")), None)
        if e is not None:
            out.append(e)
    return out


def resolve(src, inputs):
    """'<file>:<expression>' -> value. Expression: dotted paths (integer segments index lists, -1 is the last), numbers,
    + - * / ( ), len(path), nexamples(path) and hits(cells_path, obstacles_path, k). Everything resolves inside one file."""
    name, expr = src.split(":", 1)
    doc = inputs[name]
    code = re.sub(r"[A-Za-z_]\w*(?:\.-?\w+)*(?![\w.(])", lambda m: "_p(%r)" % m.group(0), expr)
    env = {"_p": lambda p: _walk(doc, p), "len": len, "hits": _hits, "nexamples": lambda eps: len(example_stops(eps))}
    return eval(code, {"__builtins__": {}}, env)  # the expression is built by this module, never read from user input


DOSE_FIELD = re.compile(r"run_constants\.dose_response\.\d+\.(p_lo|p_hi|floor_loss|arms\.\w+\.share(?:_ci95\.[01])?)$")
DOSE_KIND = {"p_lo": "g", "p_hi": "g", "floor_loss": "f1"}


def kind_of(src):
    """The format kind of a data-src: a named NUMS entry, or a run_constants.dose_response.<i>.<field> (any regime index)."""
    if src in KIND_BY_SRC:
        return KIND_BY_SRC[src]
    m = DOSE_FIELD.search(src) if src.startswith(DATA + ":") else None
    if m:
        return DOSE_KIND.get(m.group(1), "pct0")
    raise KeyError(src)


def format_value(src, value):
    kind = kind_of(src)
    if kind == "int":
        return "{:,}".format(int(round(value)))
    if kind == "f1":
        return "{:.1f}".format(value)
    if kind == "g":
        return "{:g}".format(value)
    if kind == "pct0":
        return "{:.0f}%".format(value * 100)
    if kind == "pct1":
        return "{:.1f}%".format(value * 100)
    if kind == "pp1":
        return "{:.1f}%".format(value)
    if kind == "mil1":
        return "{:.1f}".format(value / 1e6)
    raise ValueError(kind)


def num_element(name, inputs):
    f, e, _ = NUMS[name]
    return num_src("%s:%s" % (f, e), inputs)


def num_src(src, inputs):
    """<b class="num"> for any data-src that format_value knows."""
    value = resolve(src, inputs)
    if value is None:
        raise ValueError("%s is null in %s" % (src.split(":", 1)[1], src.split(":", 1)[0]))
    return '<b class="num" data-src="%s">%s</b>' % (htmllib.escape(src), htmllib.escape(format_value(src, value)))


# ------------------------------------------------------------------------------------------------ generated rows
CAUSE = {
    "unknown": ("cause: unknown", "nothing in the way"),
    "blocked_by_stuck": ("blocked by a stuck robot", "waited behind another stuck robot"),
    "traffic": ("traffic", "queued with other robots in the aisle"),
    "blocked_by_faulted": ("blocked by a broken robot", "a broken robot in the way"),
    "faulted_self": ("broke down", "its own fault flag"),
}
RES = {"order_dropped": "the job was dropped", "moved": "it moved on", "unresolved": "still stuck at the end",
       "fault_cleared": "the fault cleared"}
LESSON_TEXT = {
    "hot_cell": "One spot on the floor keeps holding robots up. Worth a look.",
    "hot_robot": "One robot gets stuck far more often than the others.",
    "recurring_pair": "Two robots keep getting in each other's way.",
}
LESSON_FALLBACK = "A pattern in the robots' waiting times."
LESSON_ICON = {"hot_cell": "▦", "hot_robot": "⚙", "recurring_pair": "⇄"}
MARKS = {"hit": "✓ real spot", "miss": "✗ not a planted spot"}


def esc(s):
    return htmllib.escape(str(s), quote=False)


def example_rows(inputs):
    d = inputs[DATA]
    step_s = d["meta"]["step_seconds"]
    rows = []
    for e in example_stops(d["episodes"]):
        tag, why = CAUSE.get(e["cause"], (e["cause"].replace("_", " "), "see the cause label"))
        secs = (e["end_step"] - e["start_step"]) * step_s
        res = RES.get(e["resolution"], str(e["resolution"]).replace("_", " "))
        rows.append('<div class="ep"><span class="who">%s</span><span>stopped at %d,%d for %d seconds, %s; %s</span>'
                    '<span class="tag">%s</span></div>' % (esc(e["robot"]), e["cell"][0], e["cell"][1], secs, esc(why), esc(res), esc(tag)))
    return "\n".join(rows)


def id_gloss(inputs):
    """One sentence that decodes the robot ids, built from the id of the first example row."""
    eps = example_stops(inputs[DATA]["episodes"])
    if not eps:
        return ""
    rid = eps[0]["robot"]
    m = re.fullmatch(r"Z(\d+)-(\d+)", rid)
    if not m:
        raise ValueError("robot id %r does not read Z<zone>-<number>" % rid)
    return '<p class="idnote"><b>%s</b> = test area %s, robot %s</p>' % (esc(rid), m.group(1), m.group(2))


def map_labels(inputs):
    """{placeholder: aria-label} of the three maps; each count is the length of the array the painting script iterates."""
    d = inputs[DATA]
    stuck = len({tuple(e["cell"]) for e in d["episodes"]})
    top = json.loads(script_data(inputs))["top"]
    lab = {
        "map_stuck_label": "Floor plan of the test area: red marks on %d distinct cells where robots got stuck" % stuck,
        "map_planted_label": "The same floor plan with %d planted cells shown" % len(d["obstacles"]),
        "map_top_label": "The same floor plan with the analyser's %d ringed cells over the planted ones; its first pick is cell %s"
                         % (len(top), top[0][0] if top else "none"),
    }
    return {k: htmllib.escape(v, quote=True) for k, v in lab.items()}


def lesson_items(inputs):
    """Newest lesson per kind, text from the per-kind template (never the raw text), the cell or robot parsed from the data."""
    newest = {}
    for l in inputs[DATA]["lessons"]:
        cur = newest.get(l["lesson_kind"])
        if cur is None or l["decided_at_step"] >= cur["decided_at_step"]:
            newest[l["lesson_kind"]] = l
    items = []
    for kind, l in sorted(newest.items(), key=lambda kv: (-kv[1]["decided_at_step"], kv[0])):
        m = re.search(r"cell (\d+,\d+)", l["text"]) if kind == "hot_cell" else (re.search(r"robot (\S+?)[ ,.]", l["text"]) if kind == "hot_robot" else None)
        where = '<b>%s</b>' % esc(m.group(1)) if m else ""
        mark_text = MARKS.get(l.get("truth"))
        mark = ' <span class="mark">%s</span>' % esc(mark_text) if mark_text else ""
        items.append('<div class="lesson" data-kind="%s"><span class="ic" aria-hidden="true">%s</span><span>%s %s%s</span></div>'
                     % (esc(kind), LESSON_ICON.get(kind, "•"), esc(LESSON_TEXT.get(kind, LESSON_FALLBACK)), where, mark))
    return "\n".join(items)


def bars_html(inputs):
    bars = inputs[DATA]["run_constants"]["worth"]["bars"]
    if tuple(b["key"] for b in bars) != BAR_KEYS:
        raise ValueError("worth.bars keys are %s, expected %s" % ([b["key"] for b in bars], list(BAR_KEYS)))
    top = max(b["ci95_high"] for b in bars) * 1.05
    rows = []
    for i, (b, label) in enumerate(zip(bars, BAR_LABELS)):
        pc = lambda v: "%.2f" % (max(0.0, v) / top * 100)
        hi = " hi" if b["key"] == "map_a32" else ""
        rows.append(
            '<div class="br%s"><span class="lab">%s</span><span class="tr" aria-hidden="true">'
            '<span class="fl" style="width:%s%%"></span>'
            '<span class="wh" style="left:%s%%;width:%s%%"></span></span>'
            '<span class="val">%s <span class="ci">(%s to %s)</span></span></div>'
            % (hi, esc(label), pc(b["mean"]), pc(b["ci95_low"]),
               "%.2f" % ((b["ci95_high"] - b["ci95_low"]) / top * 100),
               num_element("bar%d_m" % i, inputs), num_element("bar%d_lo" % i, inputs), num_element("bar%d_hi" % i, inputs)))
    return "\n        ".join(rows)


# ------------------------------------------------------------------------------------------------ S8R: when a map helps
DOSE = "run_constants.dose_response"
DOSE_STEP = 0.25          # the scale edges are multiples of this many shares (1 share = 100% of the floor loss)
DOSE_STYLE = """<style>
.dosewrap{margin-top:var(--sp-24);display:grid;gap:var(--sp-12)}
.dose{margin:0;display:grid;gap:var(--sp-10)}
.dose figcaption{font-weight:700;font-size:15px}
.dgroups{display:grid;gap:var(--sp-12)}
.dg{display:grid;gap:var(--sp-6);align-content:start;min-width:0}
.dgh{font-size:12.5px;line-height:1.3;color:var(--ink-soft)}
.dplot{position:relative;height:300px;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));background:var(--paper-deep);border-radius:6px}
.dzero{position:absolute;left:0;right:0;height:2px;margin-bottom:var(--sp-n1);background:var(--ink);z-index:2}
.dcol{position:relative}
.dbar{position:absolute;left:14%;right:14%}
.dbar.k0{background:var(--bar)} .dbar.k1{background:var(--accent)} .dbar.k2{background:var(--ink-soft)}
.dwh{position:absolute;left:50%;transform:translateX(-50%);width:2px;background:var(--ink);box-shadow:0 0 0 1px var(--white);z-index:1}
.dwh::before,.dwh::after{content:"";position:absolute;left:50%;transform:translateX(-50%);width:10px;height:2px;background:var(--ink)}
.dwh::before{bottom:0} .dwh::after{top:0}
.dvals{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));font-size:11.5px;font-weight:700;text-align:center;font-variant-numeric:tabular-nums}
.dkey{display:flex;flex-wrap:wrap;gap:var(--sp-6) var(--sp-16);font-size:12.5px;color:var(--muted)}
.dkey i{display:inline-block;width:12px;height:12px;border-radius:3px;vertical-align:-2px;margin-right:var(--sp-6)}
.dkey i.k0{background:var(--bar)} .dkey i.k1{background:var(--accent)} .dkey i.k2{background:var(--ink-soft)}
.dose-says{margin:0;font-size:14px;line-height:1.5;color:var(--ink-soft)}
@media (max-width:480px){.dgroups{grid-template-columns:minmax(0,1fr)!important}}
</style>"""
DOSE_KEY_TEXT = ("Left to right in each group: %s. The vertical line on a bar is the 95%% interval, the dark line across is zero, "
                 "and below it a setting makes the pick-rate worse. One scale for all bars.")


def arm_name(key):
    m = re.fullmatch(r"map_a(\d+)", key)
    return "map alpha " + m.group(1) if m else key


def dose_verdict(ci):
    """verdict() of scripts/sprint8_tables.py on a share interval: hurts, helps or within noise."""
    return "hurts" if ci[1] < 0 else ("helps" if ci[0] > 0 else "within noise")


def dose_scale(entries, arms):
    """(min, max) in shares: the common vertical scale, edges at multiples of DOSE_STEP, wide enough for every bar and whisker."""
    pts = [0.0]
    for e in entries:
        for a in arms:
            pts += [e["arms"][a]["share"], *e["arms"][a]["share_ci95"]]
    return math.floor(min(pts) / DOSE_STEP) * DOSE_STEP, math.ceil(max(pts) / DOSE_STEP) * DOSE_STEP


def _join(items):
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def dose_html(inputs):
    """The 'When a map helps' figure and its two sentences, read only from run_constants.dose_response of data.js."""
    entries = inputs[DATA]["run_constants"].get("dose_response")
    if not entries:
        raise ValueError("run_constants.dose_response is missing or empty in %s" % DATA)
    arms = [a for a in entries[0]["arms"] if a != "none"]
    maps = [a for a in arms if a.startswith("map_a")]
    smin, smax = dose_scale(entries, arms)
    span = smax - smin
    pct = lambda v: (v - smin) / span * 100
    src = lambda i, path: "%s:%s.%d.%s" % (DATA, DOSE, i, path)
    n = lambda i, path: num_src(src(i, path), inputs)
    fmt = lambda i, path: format_value(src(i, path), resolve(src(i, path), inputs))
    groups, aria = [], []
    for i, e in enumerate(entries):
        cols, vals = [], []
        for k, a in enumerate(arms):
            sh, (lo, hi) = e["arms"][a]["share"], e["arms"][a]["share_ci95"]
            cols.append(
                '<div class="dcol"><span class="dbar k%d" data-regime="%s" data-arm="%s" data-share="%r" data-lo="%r" data-hi="%r" '
                'style="bottom:%.3f%%;height:%.3f%%"></span><span class="dwh" style="bottom:%.3f%%;height:%.3f%%"></span></div>'
                % (k, esc(e["label"]), esc(a), sh, lo, hi, pct(min(0.0, sh)), abs(sh) / span * 100, pct(lo), (hi - lo) / span * 100))
            vals.append("<span>%s</span>" % n(i, "arms.%s.share" % a))
        groups.append(
            '<div class="dg" data-regime="%s"><div class="dgh">%s lines/h lost, p %s-%s</div>'
            '<div class="dplot"><span class="dzero" style="bottom:%.3f%%"></span>%s</div><div class="dvals">%s</div></div>'
            % (esc(e["label"]), n(i, "floor_loss"), n(i, "p_lo"), n(i, "p_hi"), pct(0), "".join(cols), "".join(vals)))
        aria.append("%s, %s lines per hour lost: %s" % (
            e["label"], fmt(i, "floor_loss"), ", ".join("%s %s" % (arm_name(a), fmt(i, "arms.%s.share" % a)) for a in arms)))
    label = htmllib.escape("When a map helps. Share of the lost pick-rate won back, by how bad the floor is. " + "; ".join(aria) + ".",
                           quote=True)
    key = '<div class="dkey">%s</div>' % "".join('<span><i class="k%d"></i>%s</span>' % (k, esc(arm_name(a))) for k, a in enumerate(arms))
    note = '<div class="legend"><span>%s</span></div>' % esc(DOSE_KEY_TEXT % ", ".join(arm_name(a) for a in arms))
    figure = ('<figure class="dose" role="img" aria-label="%s" data-scale-min="%g" data-scale-max="%g" data-scale-unit="share" '
              'data-scale-note="1 = 100%% of the floor loss"><figcaption>When a map helps</figcaption>'
              '<div class="dgroups" style="grid-template-columns:repeat(%d,minmax(0,1fr))">%s</div>%s%s</figure>'
              % (label, smin, smax, len(entries), "".join(groups), key, note))

    # sentence 1: the verdict of the strongest penalty (map_a32) per regime; a run of equal verdicts shares one verb
    target = "map_a32"
    runs = []
    for i, e in enumerate(entries):
        v = dose_verdict(e["arms"][target]["share_ci95"])
        part = '<span class="dv" data-verdict="%s" data-regime="%s">p %s-%s (share %s' % (
            v, esc(e["label"]), n(i, "p_lo"), n(i, "p_hi"), n(i, "arms.%s.share" % target))
        if v == "within noise":
            part += ", interval %s to %s" % (n(i, "arms.%s.share_ci95.0" % target), n(i, "arms.%s.share_ci95.1" % target))
        part += ")</span>"
        if runs and runs[-1][0] == v:
            runs[-1][1].append(part)
        else:
            runs.append((v, [part]))
    verb = {"hurts": "hurts at", "helps": "helps at", "within noise": "is within noise at"}
    name = arm_name(target)
    s1 = "%s %s." % (esc(name[0].upper() + name[1:]), _join(["%s %s" % (verb[v], " and ".join(parts)) for v, parts in runs]))

    # sentence 2: a map setting beats the oracle only where its interval lies wholly above the oracle's
    beats, level = [], []
    for i, e in enumerate(entries):
        o = e["arms"]["oracle"]
        for a in maps:
            m = e["arms"][a]
            if m["share_ci95"][0] > o["share_ci95"][1]:
                beats.append((i, a))
            elif m["share"] >= o["share"]:
                level.append((i, a))
    if beats:
        head = _join(["%s beats the oracle at p %s-%s (share %s, interval %s to %s, against %s, interval %s to %s)" % (
            esc(arm_name(a)), n(i, "p_lo"), n(i, "p_hi"), n(i, "arms.%s.share" % a), n(i, "arms.%s.share_ci95.0" % a),
            n(i, "arms.%s.share_ci95.1" % a), n(i, "arms.oracle.share"), n(i, "arms.oracle.share_ci95.0"),
            n(i, "arms.oracle.share_ci95.1")) for i, a in beats])
    else:
        head = "No map setting beats the oracle beyond noise"
    s2 = head[0].upper() + head[1:]
    if level:
        s2 += (";" if beats else ":") + " " + _join(["%s at p %s-%s has the higher point share (%s against %s) but the intervals overlap" % (
            esc(arm_name(a)), n(i, "p_lo"), n(i, "p_hi"), n(i, "arms.%s.share" % a), n(i, "arms.oracle.share")) for i, a in level])
    s2 += "."
    return ('<!-- dose-start --><div class="dosewrap">%s%s<p class="dose-says" data-says="target">%s</p>'
            '<p class="dose-says" data-says="oracle">%s</p></div><!-- dose-end -->' % (DOSE_STYLE, figure, s1, s2))


def script_data(inputs):
    d = inputs[DATA]
    top = d["publishes"][-1]["cells"][:TOP_K]
    data = {
        "grid": d["grid"],
        "obstacles": [[o["cell"], round(o["p"], 2)] for o in d["obstacles"]],
        "top": [[c[0], c[2]] for c in top],
        "stuck_cells": [e["cell"] for e in d["episodes"]],
    }
    return json.dumps(data, separators=(",", ":")).replace("</", "<\\/")


# ------------------------------------------------------------------------------------------------ template
TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fleet stuck analyser</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Titan+One&display=swap">
<style>
:root{
  --white:#fff; --paper:var(--white); --paper-deep:#f3f5f8; --ink:#141714; --muted:#5c5c5c; --hair:#e4e7ec;
  --accent:#1f5fbf; --card:#13233a; --card-muted:rgba(255,255,255,.72);
  --hw:#eef0f3; --shelf:#b9bfca; --goal:#cfe8d5; --planted:#7a3e00; --stuck:#b3261e;
  --wm-pink:#fc6c85; --banner-bg:#fff6d6; --banner-line:#e8d79a; --banner-ink:#4a3a00; --ink-soft:#3f4741;
  --ep-id:#9cc4ff; --tick:#2fbf94; --ink-deep:#0a0a0a; --hilite:#ffd166; --mark:#8fe3c3; --bar:#9db9e6;
  --st-ok:#1b7a4b; --st-weak:#d98c00; --st-nb:#8a8a8a; --clear:transparent;
  --white-07:rgba(255,255,255,.07); --white-08:rgba(255,255,255,.08); --white-14:rgba(255,255,255,.14);
  --white-30:rgba(255,255,255,.3); --white-75:rgba(255,255,255,.75); --white-90:rgba(255,255,255,.9);
  --card-shadow:rgba(19,35,58,.18);
  --font-logo:'Titan One',Georgia,serif; --font-display:Georgia,'Times New Roman',Times,serif; --font-sans:ui-sans-serif,system-ui,-apple-system,sans-serif; --font-mono:ui-monospace,Menlo,Consolas,monospace;
  --sp-0:0px; --sp-n1:-1px; --sp-n6:-6px; --sp-2:2px; --sp-4:4px; --sp-5:5px; --sp-6:6px; --sp-8:8px; --sp-9:9px;
  --sp-10:10px; --sp-11:11px; --sp-12:12px; --sp-13:13px; --sp-14:14px; --sp-16:16px; --sp-18:18px; --sp-20:20px;
  --sp-22:22px; --sp-24:24px; --sp-26:26px; --sp-28:28px; --sp-36:36px; --sp-40:40px; --sp-44:44px; --sp-48:48px;
  --sp-56:56px; --sp-64:64px;
}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--font-sans);font-size:16px;line-height:1.5}
.wrap{max-width:1040px;margin:0 auto;padding-left:max(var(--sp-16),env(safe-area-inset-left,var(--sp-0)));padding-right:max(var(--sp-16),env(safe-area-inset-right,var(--sp-0)))}
header.top{background:var(--ink);color:var(--white)}
header.top .wrap{display:flex;align-items:center;gap:var(--sp-18);padding-block:var(--sp-14)}
.wm{font-family:var(--font-logo);font-size:20px;text-transform:lowercase;display:inline-flex;align-items:baseline;gap:var(--sp-6)}
.wm .wmn{font-family:var(--font-sans);font-weight:300;font-size:15px;color:var(--wm-pink)}
.prod{font-family:var(--font-display);font-weight:700;font-size:17px;padding-left:var(--sp-18);border-left:1px solid var(--white-30)}
.banner{background:var(--banner-bg);border-bottom:1px solid var(--banner-line);color:var(--banner-ink)}
.banner .wrap{padding-block:var(--sp-12);font-size:14px;line-height:1.5;display:grid;gap:var(--sp-4)}
.hero .wrap{padding-block:var(--sp-64) var(--sp-40)}
h1{font-family:var(--font-display);font-weight:700;font-size:clamp(38px,6.5vw,64px);line-height:1.02;margin:0;max-width:14ch;text-wrap:balance}
.lead{margin:var(--sp-18) 0 0;font-size:19px;line-height:1.5;color:var(--ink-soft);max-width:48ch}
.flow{display:flex;align-items:center;gap:var(--sp-10);flex-wrap:wrap;margin-top:var(--sp-36)}
.flow .fb{background:var(--paper-deep);border-radius:12px;padding:var(--sp-10) var(--sp-16);font-weight:600;font-size:15px}
.flow .ar{color:var(--muted);font-size:20px}
.cta{display:inline-block;margin-top:var(--sp-28);padding:var(--sp-12) var(--sp-22);border-radius:999px;background:var(--accent);color:var(--white);font-weight:600;text-decoration:none}
.steps{display:grid;gap:0;margin-top:var(--sp-24)}
.step{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(380px,100%),1fr));gap:var(--sp-40);align-items:center;padding-block:var(--sp-56);border-top:1px solid var(--hair)}
@media (min-width:801px){.step:nth-child(even) .txt{order:2}}
.eb{font-size:13px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--accent);margin:0 0 var(--sp-10)}
h2{font-family:var(--font-display);font-weight:700;font-size:clamp(28px,4.2vw,40px);line-height:1.1;margin:0;max-width:18ch;text-wrap:balance}
.one{margin:var(--sp-14) 0 0;font-size:17px;color:var(--ink-soft);max-width:44ch}
.prior{margin:var(--sp-12) 0 0;font-size:15px;color:var(--muted);max-width:44ch}
.big{margin-top:var(--sp-26);display:flex;align-items:baseline;gap:var(--sp-12);flex-wrap:wrap}
.big b.num{font-family:var(--font-display);font-size:clamp(44px,6vw,64px);line-height:1;font-variant-numeric:tabular-nums;color:var(--accent)}
.big span{font-size:15px;color:var(--muted);max-width:30ch}
.big .sub{display:block;font-size:13px}
.pair{margin-top:var(--sp-26);display:flex;align-items:flex-start;gap:var(--sp-12) var(--sp-36);flex-wrap:wrap}
.fig{display:grid;gap:var(--sp-4);max-width:22ch}
.fignum{font-family:var(--font-display);font-size:clamp(44px,6vw,64px);line-height:1;font-variant-numeric:tabular-nums;color:var(--accent)}
.fignum b.num{font-weight:inherit}
.figlab{font-size:15px;color:var(--muted)}
b.num{font-variant-numeric:tabular-nums}
.pic{display:grid;gap:var(--sp-10)}
.map{width:100%;height:auto;display:block;border-radius:14px;background:var(--white);border:1px solid var(--hair)}
.legend{display:flex;flex-wrap:wrap;gap:var(--sp-6) var(--sp-16);font-size:12.5px;color:var(--muted)}
.legend i{display:inline-block;width:12px;height:12px;border-radius:3px;vertical-align:-2px;margin-right:var(--sp-6)}
.card{background:var(--card);color:var(--white);border-radius:22px;padding:var(--sp-22) var(--sp-22) var(--sp-24);display:grid;gap:var(--sp-12);box-shadow:0 18px 40px var(--card-shadow)}
.card .lbl{font-size:13px;font-weight:600;color:var(--card-muted)}
.funnel{display:grid;grid-template-columns:1fr auto 1fr auto 1fr;align-items:stretch;gap:var(--sp-8)}
.fx{background:var(--white-08);border-radius:14px;padding:var(--sp-14) var(--sp-12);min-width:0}
.fx .h{font-size:12px;color:var(--card-muted)} .fx .v{font-family:var(--font-display);font-size:clamp(20px,2.6vw,28px);line-height:1.1;margin-top:var(--sp-4);font-variant-numeric:tabular-nums} .fx .s{font-size:11.5px;color:var(--card-muted);margin-top:var(--sp-6);line-height:1.35}
.fx.drop{margin-top:var(--sp-8)}
.fxcol{display:grid;gap:var(--sp-8);align-content:start}
.far{align-self:center;color:var(--card-muted);font-size:22px}
.ep{display:grid;grid-template-columns:auto 1fr auto;gap:var(--sp-10);align-items:center;background:var(--white-07);border-radius:12px;padding:var(--sp-9) var(--sp-12);font-size:13.5px}
.ep .who{font-family:var(--font-mono);font-size:12px;color:var(--ep-id)} .ep .tag{font-size:11px;border:1px solid var(--white-30);border-radius:999px;padding:var(--sp-2) var(--sp-9);white-space:nowrap}
.eplist{display:grid;gap:var(--sp-8)}
.idnote{margin:0;font-size:12.5px;color:var(--card-muted)}
.ticks{display:grid;gap:var(--sp-8)}
.tk{display:flex;gap:var(--sp-10);align-items:center;font-size:14px}
.tk i{flex:none;width:20px;height:20px;border-radius:50%;background:var(--tick);color:var(--ink-deep);display:flex;align-items:center;justify-content:center;font-size:12px;font-style:normal;font-weight:700}
.lessons{display:grid;gap:var(--sp-8)}
.lesson{display:grid;grid-template-columns:auto 1fr;gap:var(--sp-12);align-items:start;background:var(--white-07);border-radius:12px;padding:var(--sp-11) var(--sp-13);font-size:14px;line-height:1.45}
.lesson .ic{width:26px;height:26px;border-radius:8px;background:var(--white-14);display:flex;align-items:center;justify-content:center;font-size:13px}
.lesson b{color:var(--hilite);font-weight:600}
.lesson .mark{display:inline-block;margin-left:var(--sp-6);color:var(--mark);font-weight:600}
.bars{display:grid;gap:var(--sp-14)}
.br{display:grid;grid-template-columns:minmax(120px,1fr) 3fr;gap:var(--sp-4) var(--sp-12);align-items:center;font-size:14px}
.br .lab{color:var(--ink-soft)}
.br .tr{position:relative;height:26px;background:var(--paper-deep);border-radius:6px}
.br .fl{position:absolute;left:0;top:0;bottom:0;border-radius:6px;background:var(--bar)}
.br.hi .fl{background:var(--accent)}
.br .wh{position:absolute;top:50%;height:2px;margin-top:var(--sp-n1);background:var(--ink)}
.br .wh::before,.br .wh::after{content:"";position:absolute;top:var(--sp-n6);width:2px;height:14px;background:var(--ink)}
.br .wh::before{left:0} .br .wh::after{right:0}
.br .val{grid-column:2;font-size:13px;font-weight:700;font-variant-numeric:tabular-nums}
.br .ci{font-weight:400;color:var(--muted)}
.closer{background:var(--paper-deep);margin-top:var(--sp-40)}
.closer .wrap{padding-block:var(--sp-48);display:grid;gap:var(--sp-22)}
.closer h2{font-size:clamp(24px,3.4vw,32px);max-width:none}
.cboxes{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(260px,100%),1fr));gap:var(--sp-22)}
.closer h3{font-family:var(--font-display);font-size:21px;margin:0 0 var(--sp-6)}
.closer p{margin:0;color:var(--muted);font-size:15px}
footer{background:var(--ink-deep);color:var(--white-75);font-size:12.5px}
footer .wrap{padding-block:var(--sp-20);display:grid;gap:var(--sp-8)}
footer .wm{color:var(--white)} footer code{font-family:var(--font-mono);font-size:11.5px;color:var(--white-90);overflow-wrap:anywhere}
.st{display:flex;align-items:flex-start;gap:var(--sp-8);margin-top:var(--sp-14);font-size:13px;line-height:1.4;color:var(--muted);max-width:46ch;background:var(--paper-deep);border-radius:10px;padding:var(--sp-8) var(--sp-11)}
.st i{flex:none;width:10px;height:10px;border-radius:50%;margin-top:var(--sp-5)}
.st.ok i{background:var(--st-ok)} .st.weak i{background:var(--st-weak)} .st.no i{background:var(--stuck)} .st.nb i{background:var(--st-nb)}
.st b{font-weight:700;color:var(--ink)}
.closer .st{background:var(--white);margin-top:var(--sp-10)}
a{color:var(--accent)}
:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
@keyframes pulse{0%,100%{opacity:.55}50%{opacity:1}}
.pulse{animation:pulse 1.6s ease-in-out infinite}
.hero .note{margin-top:var(--sp-10);font-size:14px;color:var(--muted)}
.closer .again{margin-top:var(--sp-20)}
.closer .again a{color:var(--accent);font-weight:600}
@media (prefers-reduced-motion:reduce){.pulse{animation:none}}
@media (max-width:720px){
  .hero .wrap{padding-block:var(--sp-44) var(--sp-28)}
  .step{grid-template-columns:1fr;padding-block:var(--sp-40);gap:var(--sp-24)}
  .step:nth-child(even) .txt{order:0}
  .funnel{grid-template-columns:1fr} .far{transform:rotate(90deg);justify-self:center}
  .flow .ar{display:none} .flow{gap:var(--sp-8)}
  .br{grid-template-columns:1fr} .br .val{grid-column:1}
}
@media (max-width:480px){.ep{grid-template-columns:1fr}}
</style>
</head>
<body>
<header class="top"><div class="wrap"><span class="wm">roger<span class="wmn">3000</span></span><span class="prod">fleet stuck analyser</span></div></header>

<aside class="banner" role="note"><div class="wrap">
  <div><b>Internal draft, 15 Oct 2026. What is tested and what is not.</b> Every number on this page comes from a run in the warehouse-rl repo: synthetic data from a simulator, one laptop, macOS numbers.</div>
  <div><b>Tested in simulation.</b> The log, the planted floor, the floor map. <b>Tested, weakly.</b> The "stuck" definition, the operator's list and the route planner. <b>Timing tested, reasons not.</b> When it spots a stop is measured; the reason it gives is not. <b>Not built.</b> The three onboarding steps at the bottom.</div>
</div></aside>

<main>
<section class="hero"><div class="wrap">
  <p class="eb">Warehouse robot fleets</p>
  <h1>Robots get stuck. Nobody knows why.</h1>
  <p class="lead">We read the fleet's own log as it arrives and hand operators a short, checked list of what to go and look at.</p>
  <div class="flow"><span class="fb">robot log</span><span class="ar">→</span><span class="fb">who is stuck</span><span class="ar">→</span><span class="fb">where the floor is bad</span><span class="ar">→</span><span class="fb">the operator's list</span></div>
  <a class="cta" href="../replay/index.html">See it move →</a>
  <p class="note">Everything on this page ran on simulated robots, not on a real warehouse.</p>
</div></section>

<div class="wrap"><div class="steps">

  <div class="step">
    <div class="txt">
      <p class="eb">The problem</p>
      <h2>Every stop is a log line. None of them says why.</h2>
      <p class="one">One test area, one {shift_min}-minute shift. Each red mark is a robot that sat with a job for over {stuck_after} seconds.</p>
      <p class="prior">Different from what exists: most fleet managers show the stop, not the pattern; trend tools exist, this one grades its own calls.</p>
      <div class="big">{stuck_periods}<span>stuck periods in one shift, {robots} robots</span></div>
      <div class="st weak"><i></i><span><b>Tested, weakly.</b> "Stuck" here means waited over {stuck_after} seconds with a job. Only {precision} of those stops match the simulator's own stuck flag; the others are robots waiting at a shelf by design or robots that broke down while stopped.</span></div>
    </div>
    <div class="pic"><svg id="m1" class="map" role="img" aria-label="{map_stuck_label}"></svg>
      <div class="legend"><span><i style="background:var(--hw);border:1px solid var(--hair)"></i>aisle</span><span><i style="background:var(--shelf)"></i>shelves</span><span><i style="background:var(--goal)"></i>pick stations</span><span><i style="background:var(--stuck);border-radius:50%"></i>a robot got stuck here</span></div></div>
  </div>

  <div class="step">
    <div class="txt">
      <p class="eb">What we built</p>
      <h2>A warehouse where we plant the faults ourselves.</h2>
      <p class="one">A simulator with {planted} bad floor cells hidden on the aisles. The analyser gets only the robot messages, never the answer, so every call it makes can be checked.</p>
      <div class="big">{robots}<span>robots in the test area, no hints given to the analyser</span></div>
      <div class="st ok"><i></i><span><b>Tested.</b> The planted cells and the hidden truth are in the run files; the analyser never reads them.</span></div>
    </div>
    <div class="pic"><svg id="m2" class="map" role="img" aria-label="{map_planted_label}"></svg>
      <div class="legend"><span><i style="background:var(--planted)"></i>planted bad cell, hidden from the analyser</span></div></div>
  </div>

  <div class="step">
    <div class="txt">
      <p class="eb">Step 1 · the log</p>
      <h2>Reads it live. Loses nothing.</h2>
      <p class="one">Files or a live feed, read while they are still being written. Every line counted, the useful part kept.</p>
      <div class="big">{lag_median}<span>seconds behind the robots, measured on a live feed</span></div>
      <div class="st ok"><i></i><span><b>Tested in simulation.</b> The log carried {noise} deliberately broken lines, some malformed and some repeated, and every one was counted. The kept share is measured on the store.</span></div>
    </div>
    <div class="card"><div class="lbl">One shift, one test area</div>
      <div class="funnel">
        <div class="fx"><div class="h">Arrived</div><div class="v">{msgs}</div><div class="s">messages, {noise} of them broken lines or repeats</div></div><div class="far">→</div>
        <div class="fx"><div class="h">Usable</div><div class="v">{read}</div><div class="s">messages read, the broken ones stored with their reason</div></div><div class="far">→</div>
        <div class="fxcol">
          <div class="fx"><div class="h">Kept</div><div class="v">{n_changes}</div><div class="s">changes of state, {kept_pct} of the bytes</div></div>
          <div class="fx drop"><div class="h">Dropped</div><div class="v">{n_repeats}</div><div class="s">in-between positions and repeats</div></div>
        </div>
      </div>
      <div class="ticks"><div class="tk"><i>✓</i>nothing went missing: {read} of {sent} messages read</div><div class="tk"><i>✓</i>robots send {robot_rate} messages a second, we read {ingest_rate} a second, so a fleet {ratio} times larger would keep up</div></div>
    </div>
  </div>

  <div class="step">
    <div class="txt">
      <p class="eb">Step 2 · who is stuck</p>
      <h2>Names the robot, the spot and a likely reason.</h2>
      <p class="one">{stuck_after} seconds waiting with a job means stuck. Then: a broken robot in the way, another stuck one, traffic, or nothing at all.</p>
      <div class="big">{alert_median}<span>seconds from the moment it could know to the alert</span></div>
      <div class="st no"><i></i><span><b>Timing tested, reasons not.</b> The {alert_median} seconds and the {recall} are measured. The cause labels were only compared with a proximity proxy; the simulator does not say which robot blocked which, and most cause claims could not be confirmed either way.</span></div>
    </div>
    <div class="card"><div class="lbl">{n_examples} stuck periods from this shift</div>
{id_gloss}
<div class="eplist">
{ep_rows}
</div>
      <div class="ticks"><div class="tk"><i>✓</i>finds {recall} of the stuck periods the simulator flags, over {bench_msgs} million messages</div><div class="tk"><i>✓</i>every reason is written down and checked once the stop ends</div></div>
    </div>
  </div>

  <div class="step">
    <div class="txt">
      <p class="eb">Step 3 · where the floor is bad</p>
      <h2>Draws the map from the stops nobody could explain.</h2>
      <p class="one">Unexplained hold-ups are counted per floor cell. The worst cells become the map. Blue rings are the analyser's top 20; brown is what we planted.</p>
      <div class="big">{hits_top}<span>of 20 right on the latest map of this test area; {map_precision} on average over all test areas</span></div>
      <div class="st ok"><i></i><span><b>Tested in simulation.</b> Over a batch of test areas, scored against the planted cells.</span></div>
    </div>
    <div class="pic"><svg id="m3" class="map" role="img" aria-label="{map_top_label}"></svg>
      <div class="legend"><span><i style="background:var(--planted)"></i>planted (hidden)</span><span><i style="border:2.5px solid var(--ink);box-shadow:0 0 0 2px var(--white) inset;background:var(--planted)"></i>analyser's top 20</span><span><i style="border:2.5px dashed var(--stuck);background:var(--clear)"></i>flagged, not planted</span><span>it can only find cells robots drive over: {map_ceiling} of them in one shift</span></div></div>
  </div>

  <div class="step">
    <div class="txt">
      <p class="eb">Step 4 · the operator's list</p>
      <h2>Plain sentences. Each one checked afterwards.</h2>
      <p class="one">Rules over the counts, no language model. A cell that holds robots up far more than the rest, a robot stuck far more than its peers, two robots that keep blocking each other.</p>
      <div class="pair"><div class="fig"><span class="fignum">{lt_hit}/{lt_n}</span><span class="figlab">real on the truth</span></div><div class="fig"><span class="fignum">{persist_held}/{persist_graded}</span><span class="figlab">still above the zone average next window</span></div></div>
      <div class="st weak"><i></i><span><b>Tested, weakly.</b> Checked against the hidden truth. On a longer test shift the flagged cells were real {lt_hit} of {lt_n} times; {persist_held} of {persist_graded} were still above their zone's average in the next half hour; only {held} of {graded} repeated their own peak, the bar the first version used.</span></div>
    </div>
    <div class="card"><div class="lbl">What it would tell your operators</div><div class="lessons">
{lessons_html}
</div></div>
  </div>

  <div class="step">
    <div class="txt">
      <p class="eb">What's next</p>
      <h2>Give the map to the route planner.</h2>
      <p class="one">Robots steer around the worst cells. On a floor that traps robots, the map wins back part of the lost pick-rate.</p>
      <div class="big">{map_share}<span>of the pick-rate lost to the bad floor won back with the analyser's map<span class="sub">95% interval {map_share_lo} to {map_share_hi}. With perfect knowledge: {oracle_share}, interval {oracle_share_lo} to {oracle_share_hi}.</span></span></div>
      <div class="big">{fewer_drives}<span>fewer drives into bad cells with the map on</span></div>
      <div class="st weak"><i></i><span><b>Tested, weakly.</b> On mild floor damage the gain is within noise; on damage that traps robots it is measurable.</span></div>
    </div>
    <div class="pic">
      <div class="bars">
        {bars_html}
      </div>
      <div class="legend"><span>Order lines per hour, mean of {n_seeds} shifts. The bars come from a test on a floor that traps robots, not from the shift above. Bars start at zero; the line is the 95% interval.</span></div>
{dose_html}
    </div>
  </div>

</div></div>

<section class="closer"><div class="wrap">
  <h2>What it would take on your floor</h2>
  <div class="cboxes">
    <div class="cbox"><h3>Point it at your log</h3><p>Files or a live feed. VDA 5050 out of the box, a short mapping file for anything else.</p><div class="st nb"><i></i><span><b>Not built.</b> No mapping file exists yet; only the VDA 5050 shape parses.</span></div></div>
    <div class="cbox"><h3>Tell us what "stuck" means</h3><p>Here it is {stuck_after} seconds waiting with a job. Yours may differ. One line.</p><div class="st nb"><i></i><span><b>Not built.</b> The rule is a constant in the detector, not a client setting.</span></div></div>
    <div class="cbox"><h3>Read the list</h3><p>Every call is checked against what happened next, on your floor.</p><div class="st nb"><i></i><span><b>Not built.</b> Checking exists for the simulator only; no client log has been run.</span></div></div>
  </div>
  <p class="again"><a href="../replay/index.html">See the shift this page uses, step by step →</a></p>
</div></section>
</main>

<footer><div class="wrap">
  <div><span class="wm">roger<span class="wmn">3000</span></span> &nbsp;·&nbsp; a product studio in Ericeira, Portugal</div>
  <div>Synthetic data from a simulator (TA-RWARE, medium map). Sources in the warehouse-rl repo: <code>docs/replay/data.js</code>, <code>results/fleet/benchmark.json</code>, <code>results/fleet/hotspot_s8b-medium-80-p03-07.json</code>, <code>results/closed_loop_sticky/summary.json</code>, <code>results/fleet/hotspot_s8e-long-w0.5.json</code> (the lesson counts, carried in data.js) and <code>laptop-scheduler/reports/wr-s8e-lessons-long.md</code>. Cause labels are compared with a proximity proxy, not a known answer.</div>
</div></footer>
<script>
const D = __DATA__;
const COPY = {
  aisle: 'aisle ', shelf: 'shelf ', station: 'pick station ',
  planted: 'planted bad cell ', plantedMid: ': a move into it fails ', plantedEnd: '% of the time',
  stuckHead: ' stuck period', stuckPlural: 's', stuckAt: ' at ',
  pick: 'analyser pick number ', pickCell: ', cell ', pickHit: ', a planted bad cell', pickMiss: ', not a planted cell'
};
(function () {
  var g = D.grid, W = g.width, H = g.height, C = 14, ns = 'http://www.w3.org/2000/svg';
  var planted = {}; D.obstacles.forEach(function (o) { planted[o[0]] = o[1]; });
  var goals = {}; g.goals.forEach(function (p) { goals[p.join(',')] = true; });
  var stuck = {}; D.stuck_cells.forEach(function (c) { var k = c.join(','); stuck[k] = (stuck[k] || 0) + 1; });
  function draw(id, o) {
    var svg = document.getElementById(id);
    svg.setAttribute('viewBox', '0 0 ' + (W * C) + ' ' + (H * C));
    function el(tag, attrs, title) {
      var e = document.createElementNS(ns, tag);
      Object.keys(attrs).forEach(function (k) { e.setAttribute(k, attrs[k]); });
      if (title) { var t = document.createElementNS(ns, 'title'); t.textContent = title; e.appendChild(t); }
      svg.appendChild(e);
      return e;
    }
    for (var y = 0; y < H; y++) {
      for (var x = 0; x < W; x++) {
        var key = x + ',' + y, hw = g.highway[y][x] === '1';
        var fill = hw ? 'var(--hw)' : 'var(--shelf)', t = (hw ? COPY.aisle : COPY.shelf) + key;
        if (goals[key]) { fill = 'var(--goal)'; t = COPY.station + key; }
        if (o.planted && planted[key] !== undefined) {
          fill = 'var(--planted)';
          t = COPY.planted + key + COPY.plantedMid + Math.round(planted[key] * 100) + COPY.plantedEnd;
        }
        el('rect', { x: x * C, y: y * C, width: C - 1, height: C - 1, rx: 2, fill: fill }, t);
      }
    }
    if (o.stuck) {
      Object.keys(stuck).forEach(function (k) {
        var n = stuck[k], xy = k.split(',').map(Number);
        var c = el('circle', { cx: xy[0] * C + C / 2 - 0.5, cy: xy[1] * C + C / 2 - 0.5, r: 3.2 + Math.min(n, 4) * 1.1, fill: 'var(--stuck)', opacity: 0.85 },
          n + COPY.stuckHead + (n > 1 ? COPY.stuckPlural : '') + COPY.stuckAt + k);
        c.setAttribute('class', 'pulse');
      });
    }
    if (o.flagged) {
      D.top.forEach(function (v, i) {
        var key = v[0], xy = key.split(',').map(Number), hit = planted[key] !== undefined;
        el('rect', { x: xy[0] * C + 1, y: xy[1] * C + 1, width: C - 3, height: C - 3, rx: 2.5, fill: 'none', stroke: 'var(--white)', 'stroke-width': 4.4 });
        var ring = { x: xy[0] * C + 1, y: xy[1] * C + 1, width: C - 3, height: C - 3, rx: 2.5, fill: 'none', stroke: hit ? 'var(--ink)' : 'var(--stuck)', 'stroke-width': 2.2 };
        if (!hit) ring['stroke-dasharray'] = '3 2';
        el('rect', ring, COPY.pick + (i + 1) + COPY.pickCell + key + (hit ? COPY.pickHit : COPY.pickMiss));
        if (i < 10) {
          var tx = el('text', { x: xy[0] * C + C / 2 - 0.5, y: xy[1] * C + C / 2 + 3, 'text-anchor': 'middle', 'font-size': '8.5', 'font-weight': '700', fill: 'var(--white)', stroke: 'var(--ink)', 'stroke-width': 2, 'paint-order': 'stroke', 'font-family': 'ui-sans-serif,system-ui,sans-serif', 'pointer-events': 'none' });
          tx.textContent = String(i + 1);
        }
      });
    }
  }
  draw('m1', { stuck: true });
  draw('m2', { planted: true });
  draw('m3', { planted: true, flagged: true });
})();
</script>
</body>
</html>
"""


# ------------------------------------------------------------------------------------------------ build
def visible_chunks(html_text):
    """[(is_code, text)]: <script>/<style> blocks are code, the rest is markup."""
    out, pos = [], 0
    for m in re.finditer(r"<(script|style)\b.*?</\1>", html_text, re.S):
        out.append((False, html_text[pos:m.start()]))
        out.append((True, m.group(0)))
        pos = m.end()
    out.append((False, html_text[pos:]))
    return out


def build(inputs):
    """The filled page, the placeholder tokens still left outside script/style, and {name: error} for each value that failed."""
    values, errors = {}, {}
    for name in NUMS:
        try:
            values[name] = num_element(name, inputs)
        except Exception as e:  # leaves its {name} in the page; main() names the cause and refuses to write
            errors[name] = "%s: %s" % (type(e).__name__, e)
    try:
        values.update(map_labels(inputs))
    except Exception as e:
        errors["map_labels"] = "%s: %s" % (type(e).__name__, e)
    for name, fn in (("ep_rows", example_rows), ("id_gloss", id_gloss), ("lessons_html", lesson_items), ("bars_html", bars_html), ("dose_html", dose_html)):
        try:
            values[name] = fn(inputs)
        except Exception as e:
            errors[name] = "%s: %s" % (type(e).__name__, e)
    fill = lambda m: values.get(m.group(0)[1:-1], m.group(0))
    parts = []
    for is_code, text in visible_chunks(TEMPLATE):
        parts.append(text if is_code else PLACEHOLDER.sub(fill, text))
    page = "".join(parts).replace("__DATA__", script_data(inputs))
    left = sorted({t for is_code, text in visible_chunks(page) if not is_code for t in PLACEHOLDER.findall(text)})
    return page, left, errors


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", default=str(ROOT / DATA))
    ap.add_argument("--results-root", default=str(ROOT))
    ap.add_argument("--out", default=str(ROOT / "docs" / "overview" / "index.html"))
    a = ap.parse_args(argv)
    try:
        inputs = load_inputs(a.data, a.results_root)
        page, left, errors = build(inputs)
    except Exception as e:  # missing or malformed input: nothing is written
        print("overview_build: %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 2
    if left:
        print("overview_build: placeholders left unfilled: %s" % ", ".join(left), file=sys.stderr)
        for name, err in sorted(errors.items()):
            print("overview_build:   %s <- %s" % (name, err), file=sys.stderr)
        return 3
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(page.encode("utf-8"))
    print("wrote %s (%d bytes)" % (out, len(page.encode("utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())

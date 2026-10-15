"""Lessons: one plain sentence a person would say about a zone, backed by counts, stored as a graded decision.

Reads the store tables only (stuck_episodes, stalls, transitions, ingest_checkpoints, decisions) through store.select();
nothing the emitter knows enters here (fleet/grade.py checks hot cells against the floor, in its own code).

Windows. Per zone, tumbling windows of W = window_h * 3600 s aligned on epoch multiples: [k*W, (k+1)*W). A window is
evaluated only when it is fully observed: forecast_grade.stream_end(zone) >= window_end. Episodes are counted by `start`
(left_censored episodes are INCLUDED: a censored episode is still a stuck robot in that window), stalls by `start`,
transitions by `ts`. decided_at = window_end (event time). Baselines are ZONE means (each zone is its own floor);
cause_mix is the exception, its baseline is the fleet-wide share of the same cause over the same window.

Kinds (RULES holds each support minimum n_min and threshold; every rule is `support and threshold`, >= comparisons):
  hot_cell         k = stalls at a cell, n = zone stalls, C = distinct stall cells; ratio = k / (n / C)
                   fires iff k >= 5 and ratio >= 3.0
  hot_robot        k = episodes of a robot, n = zone episodes, R = distinct robots in the zone's transitions;
                   ratio = k / (n / R); fires iff k >= 5 and ratio >= 2.0
  hot_hour         k = episodes starting in a UTC clock hour, n = zone episodes, H = whole clock hours inside the window;
                   ratio = k / (n / H); fires iff k >= 10 and ratio >= 1.5. Never fires when W < 2 h (H <= 1 makes
                   the ratio <= 1). Next-window grading looks for the same hour of day inside the next window, which
                   is a different clock hour unless W is a multiple of 24 h, so an hour lesson grades "off" by
                   construction.
  cause_mix        k = episodes of the dominant KNOWN cause, n = episodes with cause != "unknown"; value = k / n; the
                   dominant cause is never "unknown" (not a lesson a person acts on); ties break on the cause name;
                   fires iff n >= 10 and value >= 0.6. The cause is carried in claim["metric"] as "cause_share:<cause>".
  avoidable_share  per cell and per robot: k = avoidable episodes, n = the subject's episodes; value = k / n;
                   fires iff n >= 5 and value >= 0.5
  recurring_pair   k = episodes with that (blocker, robot), n = zone episodes that have a blocker; fires iff k >= 3
                   (n_min = threshold = 3: the count is the support)

Confidence. The Wilson score lower bound with z = 1.96,
    L(k, n) = (p + z^2/(2n) - z * sqrt(p(1-p)/n + z^2/(4 n^2))) / (1 + z^2/n),  p = k / n,
over s* = the share the rule needs (hot_cell threshold / C, hot_robot threshold / R, hot_hour threshold / H,
cause_mix 0.6, avoidable_share 0.5, recurring_pair 3 / n):  confidence = round(min(1, L(k, n) / s*), 3).
1.0 means the threshold still holds at the 95 % lower bound. At fixed k / n it is non-decreasing in n.

Decision. kind "lesson", subject "<lesson_kind>|<subject>", dedup_key "lesson:<lesson_kind>|<subject>:<window_end ISO>",
so a re-run is a no-op. The claim has exactly the keys in CLAIM_KEYS; claim["text"] is rendered from the claim alone
(render()), nothing else feeds it.

Grading (grade_lessons): an open lesson with window [s, e), W = e - s, is graded iff stream_end(zone) >= e + W. The same
lesson_kind and subject is recomputed over [e, e + W) with the same rule WITHOUT the support minimum (a subject with no
events has value 0); verdict "ok" iff the threshold still holds, else "off". The forecast_grades row (grade_source
"lesson") is written first, then the decision is stamped. Not eligible: nothing is written, the lesson stays open.
"""
import datetime
import json
import math

from . import decisions, forecast_grade
from .parse import iso

KIND = "lesson"
Z = 1.96
DEFAULT_WINDOW_H = 2.0

RULES = {
    "hot_cell": dict(n_min=5, threshold=3.0),
    "hot_robot": dict(n_min=5, threshold=2.0),
    "hot_hour": dict(n_min=10, threshold=1.5),
    "cause_mix": dict(n_min=10, threshold=0.6),
    "avoidable_share": dict(n_min=5, threshold=0.5),
    "recurring_pair": dict(n_min=3, threshold=3),
}
KINDS = tuple(RULES)
SUPPORT_ON_N = ("cause_mix", "avoidable_share")  # support = n; for every other kind support = k
CLAIM_KEYS = ("text", "lesson_kind", "subject", "zone", "metric", "value", "baseline", "ratio", "n", "k", "confidence",
              "threshold", "n_min", "window_start", "window_end")
UNKNOWN = "unknown"


# ------------------------------------------------------------------------------------------------ confidence
def wilson_lower(k, n, z=Z):
    """Wilson score lower bound of the proportion k / n (0 when n == 0)."""
    if n <= 0:
        return 0.0
    p = k / n
    return (p + z * z / (2 * n) - z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / (1 + z * z / n)


def confidence(k, n, s_star):
    return round(min(1.0, wilson_lower(k, n) / s_star), 3)


# ------------------------------------------------------------------------------------------------ data
def cell_of(c):
    """'x,y' from an episode's [x, y] list or a stall's 'x,y' string."""
    return c if isinstance(c, str) else f"{c[0]},{c[1]}"


class Data:
    """The run's rows, read once through store.select and indexed by zone (zone is always a string)."""

    def __init__(self, store, run):
        self.eps, self.stalls, self.trans = {}, {}, {}
        for name, into in (("stuck_episodes", self.eps), ("stalls", self.stalls), ("transitions", self.trans)):
            for r in store.select(name, {"run": run}):
                into.setdefault(str(r["zone"]), []).append(r)
        self.zones = set(self.eps) | set(self.stalls) | set(self.trans)

    def first_ts(self, zone):
        ts = [e["start"] for e in self.eps.get(zone, ())] + [s["start"] for s in self.stalls.get(zone, ())] + \
             [t["ts"] for t in self.trans.get(zone, ())]
        return min(ts) if ts else None

    def window(self, zone, ws, we):
        return dict(
            zone=zone, ws=ws, we=we,
            eps=sorted((e for e in self.eps.get(zone, ()) if ws <= e["start"] < we), key=lambda e: e["episode_id"]),
            stalls=[s for s in self.stalls.get(zone, ()) if ws <= s["start"] < we],
            robots={t["robot"] for t in self.trans.get(zone, ()) if ws <= t["ts"] < we})

    def fleet_known(self, ws, we):
        """{cause: episodes} over ALL zones' episodes in [ws, we) whose cause is known."""
        out = {}
        for rows in self.eps.values():
            for e in rows:
                if ws <= e["start"] < we and e["cause"] != UNKNOWN:
                    out[e["cause"]] = out.get(e["cause"], 0) + 1
        return out


def _counts(items):
    out = {}
    for i in items:
        out[i] = out.get(i, 0) + 1
    return out


def _stat(w, kind, subject, k, n, base, ratio, s_star, metric=None):
    """One candidate with everything the claim needs, unrounded. k is the subject count, n the base count."""
    value = k / n if kind in SUPPORT_ON_N else k
    return dict(kind=kind, subject=f"Z{w['zone']}:{subject}" if subject else f"Z{w['zone']}", metric=metric or kind,
                k=k, n=n, value=value, baseline=base, ratio=ratio, s_star=s_star)


def _ratio_stats(w, kind, subjects, n, d, label=""):
    """subjects: {name: k}; n = zone total; d = the baseline divisor (C, R or H). baseline = n / d, ratio = k * d / n
    (computed as one division so a ratio exactly on the threshold is exact)."""
    if n == 0 or d == 0:
        return []
    thr = RULES[kind]["threshold"]
    return [_stat(w, kind, f"{label}{name}", k, n, n / d, k * d / n, thr / d) for name, k in sorted(subjects.items())]


def hot_cell(w, fleet):
    cells = _counts(cell_of(s["cell"]) for s in w["stalls"])
    return _ratio_stats(w, "hot_cell", cells, len(w["stalls"]), len(cells), "cell ")


def hot_robot(w, fleet):
    return _ratio_stats(w, "hot_robot", _counts(e["robot"] for e in w["eps"]), len(w["eps"]), len(w["robots"]))


def whole_hours(ws, we):
    """Number of whole clock hours [h*3600, (h+1)*3600) inside [ws, we)."""
    return max(0, we // 3600 - (-(-ws // 3600)))


def hot_hour(w, fleet):
    hours = _counts(f"hour {int(e['start'] % 86400 // 3600):02d}" for e in w["eps"])
    return _ratio_stats(w, "hot_hour", hours, len(w["eps"]), whole_hours(w["ws"], w["we"]))


def cause_mix(w, fleet):
    known = _counts(e["cause"] for e in w["eps"] if e["cause"] != UNKNOWN)
    n = sum(known.values())
    total = sum(fleet.values()) if fleet else 0
    out = []
    for cause, k in sorted(known.items()):
        base = fleet.get(cause, 0) / total if total else None
        out.append(_stat(w, "cause_mix", None, k, n, base, (k / n) / base if base else None,
                         RULES["cause_mix"]["threshold"], metric=f"cause_share:{cause}"))
    return out


def avoidable_share(w, fleet):
    eps = w["eps"]
    if not eps:
        return []
    zone_share = sum(1 for e in eps if e["avoidable"]) / len(eps)
    out = []
    for label, key in (("cell ", lambda e: cell_of(e["cell"])), ("", lambda e: e["robot"])):
        n_of, k_of = {}, {}
        for e in eps:
            n_of[key(e)] = n_of.get(key(e), 0) + 1
            k_of[key(e)] = k_of.get(key(e), 0) + (1 if e["avoidable"] else 0)
        for name in sorted(n_of):
            ratio = (k_of[name] / n_of[name]) / zone_share if zone_share else None
            out.append(_stat(w, "avoidable_share", f"{label}{name}", k_of[name], n_of[name], zone_share, ratio,
                             RULES["avoidable_share"]["threshold"]))
    return out


def recurring_pair(w, fleet):
    pairs = [(e["blocker"], e["robot"]) for e in w["eps"] if e.get("blocker")]
    n = len(pairs)
    return [_stat(w, "recurring_pair", f"{b}->{r}", k, n, None, None, 3 / n)
            for (b, r), k in sorted(_counts(pairs).items())]


STATS = {"hot_cell": hot_cell, "hot_robot": hot_robot, "hot_hour": hot_hour, "cause_mix": cause_mix,
         "avoidable_share": avoidable_share, "recurring_pair": recurring_pair}


def measure(kind, st):
    """The number the rule's threshold is compared with (the support minimum is a separate test)."""
    if kind in ("hot_cell", "hot_robot", "hot_hour"):
        return st["ratio"] or 0
    if kind == "recurring_pair":
        return st["k"]
    return st["value"]


def fires(kind, st):
    """The full rule: support minimum AND threshold, both >=."""
    rule = RULES[kind]
    support = st["n"] if kind in SUPPORT_ON_N else st["k"]
    return support >= rule["n_min"] and measure(kind, st) >= rule["threshold"]


def dominant(stats):
    """cause_mix keeps only the dominant known cause: most episodes, ties on the cause name."""
    return [min(stats, key=lambda s: (-s["k"], s["metric"]))] if stats else []


# ------------------------------------------------------------------------------------------------ text
def _hhmm(epoch):
    return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).strftime("%H:%M")


def _pct(x):
    return f"{x * 100:.0f}%"


def render(c):
    """The one-sentence text of a claim, from the claim fields alone."""
    kind, zone = c["lesson_kind"], c["zone"]
    what = c["subject"].partition(":")[2]
    span = f"{_hhmm(c['window_start'])}-{_hhmm(c['window_end'])}"
    if kind == "hot_cell":
        return (f"In zone {zone}, {what} had {c['k']} stalls, {c['ratio']:.1f}x the zone average "
                f"(n={c['n']} stalls, {span}).")
    if kind == "hot_robot":
        return (f"In zone {zone}, robot {what} had {c['k']} stuck episodes, {c['ratio']:.1f}x the zone average "
                f"(n={c['n']} episodes, {span}).")
    if kind == "hot_hour":
        return (f"In zone {zone}, {what} UTC had {c['k']} stuck episodes, {c['ratio']:.1f}x the zone average "
                f"(n={c['n']} episodes, {span}).")
    if kind == "cause_mix":
        cause = c["metric"].partition(":")[2]
        return (f"In zone {zone}, {_pct(c['value'])} of stuck episodes with a known cause were {cause} "
                f"(n={c['n']}, fleet {_pct(c['baseline'])}, {span}).")
    if kind == "avoidable_share":
        target = what if what.startswith("cell ") else f"robot {what}"
        return (f"In zone {zone}, {c['k']} of {c['n']} stuck episodes at {target} were avoidable "
                f"({_pct(c['value'])}, zone {_pct(c['baseline'])}, {span}).")
    blocker, _, blocked = what.partition("->")
    return f"In zone {zone}, robot {blocker} blocked robot {blocked} {c['k']} times ({span})."


def _r4(x):
    return None if x is None else round(x, 4)


def make_claim(st, ws, we):
    rule = RULES[st["kind"]]
    c = dict(lesson_kind=st["kind"], subject=st["subject"], zone=st["subject"][1:].partition(":")[0],
             metric=st["metric"], value=_r4(st["value"]), baseline=_r4(st["baseline"]), ratio=_r4(st["ratio"]),
             n=st["n"], k=st["k"], confidence=confidence(st["k"], st["n"], st["s_star"]),
             threshold=rule["threshold"], n_min=rule["n_min"], window_start=ws, window_end=we)
    c["text"] = render(c)
    return c


# ------------------------------------------------------------------------------------------------ extraction
def window_span(window_h):
    w = int(round(window_h * 3600))
    if w <= 0:
        raise ValueError("window_h must be > 0")
    return w


def extract(store, run, window_h=DEFAULT_WINDOW_H, recorded_at=None):
    """Record a lesson decision for every fired rule of every fully observed window. Returns dict(created, existing,
    by_kind = {lesson_kind: lessons created}, windows = windows evaluated). Idempotent (dedup_key)."""
    span = window_span(window_h)
    data = Data(store, run)
    out = dict(created=0, existing=0, by_kind={k: 0 for k in KINDS}, windows=0)
    for zone in sorted(data.zones):
        end = forecast_grade.stream_end(store, run, zone)
        first = data.first_ts(zone)
        if end is None or first is None:
            continue
        ws = int(first // span) * span
        while ws + span <= end:  # only fully observed windows
            we = ws + span
            w = data.window(zone, ws, we)
            fleet = data.fleet_known(ws, we)
            out["windows"] += 1
            for kind in KINDS:
                sts = STATS[kind](w, fleet)
                if kind == "cause_mix":
                    sts = dominant(sts)
                for st in sts:
                    if not fires(kind, st):
                        continue
                    claim = make_claim(st, ws, we)
                    _, created = decisions.record_decision(
                        store, run=run, kind=KIND, subject=f"{kind}|{st['subject']}", start_iso=iso(we), decided_at=we,
                        claim=claim, rationale=claim["text"], expected=None, grade_after=we + span,
                        recorded_at=recorded_at)
                    out["created" if created else "existing"] += 1
                    if created:
                        out["by_kind"][kind] += 1
            ws = we
    return out


# ------------------------------------------------------------------------------------------------ grading
def claim_of(d):
    c = d["claim"]
    return json.loads(c) if isinstance(c, str) else c


def lessons(store, run):
    return store.select("decisions", {"run": run, "kind": KIND})


def next_value(data, claim):
    """(stat, passes) of the claim's lesson_kind and subject over [window_end, window_end + W), without the support
    minimum. A subject with no events in that window has value 0."""
    kind, e = claim["lesson_kind"], claim["window_end"]
    span = e - claim["window_start"]
    w = data.window(claim["zone"], e, e + span)
    sts = STATS[kind](w, data.fleet_known(e, e + span) if kind == "cause_mix" else None)
    st = next((s for s in sts if s["subject"] == claim["subject"] and s["metric"] == claim["metric"]), None)
    if st is None:
        st = dict(kind=kind, subject=claim["subject"], metric=claim["metric"], k=0, n=0, value=0, baseline=None,
                  ratio=0, s_star=None)
    return st, measure(kind, st) >= claim["threshold"]


def grade_lessons(store, run):
    """Grade every eligible open lesson (see module docstring). Returns dict(graded, open)."""
    data = None
    ends = {}
    graded = still_open = 0
    for d in lessons(store, run):
        if d["status"] != "open":
            continue
        claim = claim_of(d)
        zone, e = claim["zone"], claim["window_end"]
        span = e - claim["window_start"]
        if zone not in ends:
            ends[zone] = forecast_grade.stream_end(store, run, zone)
        end = ends[zone]
        if end is None or end < e + span:
            still_open += 1
            continue
        if data is None:
            data = Data(store, run)
        st, ok = next_value(data, claim)
        verdict = "ok" if ok else "off"
        forecast_grade.write_once(store, dict(id=d["id"], run=run, grade_source="lesson", outcome=st["value"],
                                              expected=claim["value"], error=None, verdict=verdict, horizon_s=span,
                                              graded_at=end, window_end=e + span))
        if decisions.stamp_grade(store, d["id"], st["value"], None, verdict, end):
            graded += 1
    return dict(graded=graded, open=still_open)

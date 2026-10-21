"""The station time bound of S14A: how long may a stop at a station last before it counts as stuck?

dwell_sample(messages, stations, radius) -> sorted list of dwell seconds: every stopped-with-order stretch (the detector's
stopped run: driving false, one non-empty orderId) that STARTS within `radius` (Manhattan) of a station goal cell of its
zone, of ANY length (under-30 s stretches included: a sample of the SERVICING runs only would be left-truncated at 30 s).
dwell = ending message ts - first stopped ts (the episode-duration definition); a stretch still open at the end of the
input counts with last ts - first ts (a lower bound), and a dwell of 0 s (a single message at the end of the input) is
left out because ln(0) is undefined.

auto_bound(dwells) -> dict(servicing_max_s, servicing_sample_n, servicing_q1_s, servicing_q3_s). The bound is
    T = min(300, exp(Q3L + 3 * (Q3L - Q1L)))
with Q1L, Q3L the linear-interpolated (type 7: position (n - 1) * p) quartiles of ln(dwell). That equals
min(300, Q3 * (Q3 / Q1) ** 3) with Q1 = exp(Q1L), Q3 = exp(Q3L), which are the two numbers reported. Fewer than 5 stretches
-> T = 300 and the quartiles are still reported when there is at least one stretch (docs/LITERATURE.md Part 4 verdict 1).

resolve(spec, messages, stations, radius) -> that dict for spec "auto" or a number S (S is used as given; the sample
statistics are still computed so every result file carries the same four keys). One call = one run: the caller passes all
robots of all zones of the run (each zone judged on its own station set).
"""
import math

from .detector import stations_of, at_station

CAP_S = 300.0
MIN_SAMPLE = 5
SCALE = 3.0
KEYS = ("servicing_max_s", "servicing_sample_n", "servicing_q1_s", "servicing_q3_s")


def _kept(msgs):
    """Sorted by (ts, header_id); a message whose ts <= the previous kept ts is dropped (timebudget.kept_messages)."""
    out = []
    for m in sorted(msgs, key=lambda m: (m.ts, m.header_id)):
        if out and m.ts <= out[-1].ts:
            continue
        out.append(m)
    return out


def dwell_sample(messages, stations, radius=0):
    by = {}
    for m in messages:
        by.setdefault((m.zone, m.serial), []).append(m)
    out = []
    for (zone, _serial), msgs in sorted(by.items()):
        st = stations_of(stations, zone)
        kept = _kept(msgs)
        cur = None  # (first index, order id)
        for i, m in enumerate(kept):
            if cur is not None and not (not m.driving and m.order_id == cur[1]):
                first = kept[cur[0]]
                if at_station(first.x, first.y, st, radius):
                    out.append(m.ts - first.ts)
                cur = None
            if cur is None and not m.driving and m.order_id != "":
                cur = (i, m.order_id)
        if cur is not None:
            first = kept[cur[0]]
            if at_station(first.x, first.y, st, radius):
                out.append(kept[-1].ts - first.ts)
    return sorted(d for d in out if d > 0)


def quantile(sorted_vals, p):
    """Linear interpolation between order statistics at position (n - 1) * p (numpy's default)."""
    h = (len(sorted_vals) - 1) * p
    lo = int(math.floor(h))
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (h - lo) * (sorted_vals[hi] - sorted_vals[lo])


def auto_bound(dwells):
    d = sorted(dwells)
    n = len(d)
    if n == 0:
        return dict(servicing_max_s=CAP_S, servicing_sample_n=0, servicing_q1_s=None, servicing_q3_s=None)
    logs = [math.log(x) for x in d]
    q1l, q3l = quantile(logs, 0.25), quantile(logs, 0.75)
    t = CAP_S if n < MIN_SAMPLE else min(CAP_S, math.exp(q3l + SCALE * (q3l - q1l)))
    return dict(servicing_max_s=t, servicing_sample_n=n, servicing_q1_s=math.exp(q1l), servicing_q3_s=math.exp(q3l))


def parse_spec(text):
    """argparse type of --servicing-max-s: 'auto' or a finite number > 0."""
    if text == "auto":
        return "auto"
    try:
        v = float(text)
    except ValueError:
        v = float("nan")
    if not 0 < v < float("inf"):
        raise ValueError(f"--servicing-max-s must be 'auto' or a number > 0, got {text!r}")
    return v


def resolve(spec, messages, stations, radius=0):
    stats = auto_bound(dwell_sample(messages, stations, radius))
    if spec != "auto":
        stats["servicing_max_s"] = float(spec)
    return stats

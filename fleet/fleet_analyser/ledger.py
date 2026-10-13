"""Ingest ledger: exact counters per (source, wall minute), sequence accounting, coverage, and the status / plot reports.

Coverage = sum(messages_accepted) over the run / emit-ledger total.expected_messages (null without an emit ledger). It is
the single completeness number. Invariant per row: bytes_kept + bytes_dropped == bytes_read_uncompressed (every consumed
line is dropped when read and moved to kept the moment something retains it: evidence, state_sample, a reject raw).
"""
import math
import time
from pathlib import Path

COLUMNS = ("run", "source", "minute", "bytes_read_compressed", "bytes_read_uncompressed", "messages_parsed",
           "messages_rejected", "duplicates", "sequence_gaps", "missing_messages", "messages_accepted", "lag_p50_s",
           "lag_p99_s", "behind_emitter_s", "msgs_per_s", "mb_per_s", "bytes_kept", "bytes_dropped", "backlog_bytes",
           "written_at")
_SUMS = ("bytes_read_compressed", "bytes_read_uncompressed", "messages_parsed", "messages_rejected", "duplicates",
         "sequence_gaps", "missing_messages", "messages_accepted", "bytes_kept", "bytes_dropped")


class SequenceTracker:
    """Per robot, the last accepted headerId h. check() classifies one valid message:
    headerId <= h -> duplicate (counted, not passed on); > h + 1 -> gap of headerId - h - 1 missing, then accepted;
    a robot's first message with headerId k > 0 is one gap with k missing. accepted = valid and not duplicate."""

    def __init__(self, last=None):
        self.last = dict(last or {})
        self.gaps = 0
        self.missing = 0
        self.duplicates = 0
        self.accepted = 0

    def check(self, serial, header_id):
        """Returns (accepted, missing_before): missing_before > 0 means a gap was counted."""
        h = self.last.get(serial)
        if h is not None and header_id <= h:
            self.duplicates += 1
            return False, 0
        missing = header_id if h is None else header_id - h - 1
        if missing > 0:
            self.gaps += 1
            self.missing += missing
        self.last[serial] = header_id
        self.accepted += 1
        return True, missing


def _pct(sorted_vals, q):
    if not sorted_vals:
        return None
    return sorted_vals[max(0, math.ceil(q * len(sorted_vals)) - 1)]


def lag_enabled(emit_config):
    """Lag (wall clock at parse minus message ts) only means something when the emitter runs in real time from 'now'."""
    c = emit_config or {}
    return c.get("t0_mode") == "now" and c.get("rate") == "realtime" and c.get("speed") == 1


def _blank():
    d = {k: 0 for k in _SUMS}
    d.update(lags=[], behind=None, backlog=0)
    return d


class IngestLedger:
    def __init__(self, run, source="file", clock=time.time, loop_start=None):
        self.run, self.source, self.clock = run, source, clock
        self.loop_start = clock() if loop_start is None else loop_start
        self.minutes = {}

    def preload(self, rows):
        """Continue the counters of an earlier process of the same run (resume): rows are ingest_ledger rows."""
        for r in rows:
            if r["run"] == self.run and r["source"] == self.source:
                c = self.minutes.setdefault(r["minute"], _blank())
                for k in _SUMS:
                    c[k] += r[k] or 0
                c["behind"], c["backlog"] = r.get("behind_emitter_s"), r.get("backlog_bytes") or 0

    def snapshot(self):
        """The exact counters (lag samples excluded) as JSON-able {minute: {sum: n}}; stored in every checkpoint row so
        a resume continues from counters that match the checkpoint's offsets exactly."""
        return {str(m): {k: c[k] for k in _SUMS} for m, c in self.minutes.items()}

    def restore(self, snap):
        """Replace the counters with a snapshot() taken at a checkpoint (lag samples of those minutes are lost)."""
        self.minutes = {}
        for m, sums in snap.items():
            c = self.minutes.setdefault(int(m), _blank())
            for k in _SUMS:
                c[k] = sums.get(k, 0)

    def minute_now(self):
        return int(self.clock() // 60) * 60

    def _c(self, minute=None):
        return self.minutes.setdefault(self.minute_now() if minute is None else minute, _blank())

    def fed(self, compressed):
        self._c()["bytes_read_compressed"] += compressed

    def line_read(self, nbytes):
        """One consumed line; returns the wall minute it was attributed to (needed to keep it later)."""
        m = self.minute_now()
        c = self._c(m)
        c["bytes_read_uncompressed"] += nbytes
        c["bytes_dropped"] += nbytes
        return m

    def keep(self, minute, nbytes):
        c = self._c(minute)
        c["bytes_kept"] += nbytes
        c["bytes_dropped"] -= nbytes

    def parsed(self):
        self._c()["messages_parsed"] += 1

    def rejected(self):
        self._c()["messages_rejected"] += 1

    def duplicate(self):
        self._c()["duplicates"] += 1

    def gap(self, missing):
        c = self._c()
        c["sequence_gaps"] += 1
        c["missing_messages"] += missing

    def accepted(self, lag_s=None):
        c = self._c()
        c["messages_accepted"] += 1
        if lag_s is not None:
            c["lags"].append(lag_s)

    def total(self, key):
        return sum(c[key] for c in self.minutes.values())

    def rows(self, behind_emitter_s=None, backlog_bytes=0, lag_ok=False):
        now = self.clock()
        latest = max(self.minutes) if self.minutes else None
        out = []
        for m in sorted(self.minutes):
            c = self.minutes[m]
            if m == latest:
                c["behind"], c["backlog"] = behind_emitter_s, backlog_bytes
            active = max(min(m + 60, now) - max(m, self.loop_start), 1e-3)
            lags = sorted(c["lags"]) if lag_ok else []
            row = dict(run=self.run, source=self.source, minute=m, **{k: c[k] for k in _SUMS},
                       lag_p50_s=_pct(lags, 0.5), lag_p99_s=_pct(lags, 0.99), behind_emitter_s=c["behind"],
                       msgs_per_s=c["messages_parsed"] / active, mb_per_s=c["bytes_read_uncompressed"] / 1e6 / active,
                       backlog_bytes=None if self.source == "kafka" else c["backlog"], written_at=now)  # kafka: no bytes
            # backlog; its consumer lag (messages) is in ingest_consumer_lag and printed by status_lines
            out.append({k: row[k] for k in COLUMNS})
        return out


def coverage(accepted, expected):
    """accepted / expected, None without an emit ledger (or an unknown expected count)."""
    if not expected:
        return None
    return accepted / expected


# ------------------------------------------------------------------------------------------------ reports
def _window(rows, minutes):
    if not rows:
        return []
    anchor = max(r["minute"] for r in rows)
    return [r for r in rows if r["minute"] > anchor - minutes * 60]


def _sum(rows, key):
    return sum(r[key] or 0 for r in rows)


def _active_s(row):
    """Seconds the loop was active in a row, recovered from its rate columns (parsed / msgs_per_s)."""
    return row["messages_parsed"] / row["msgs_per_s"] if row["msgs_per_s"] else 0.0


def exclusion(ep):
    """Why a stuck_episodes row is not countable, or None when it is. One precedence everywhere (scorer, report, status):
    left_censored (start unknown after a resume), then interrupted (the process died with it open), then open."""
    if ep.get("left_censored"):
        return "left_censored"
    if ep["resolution"] in ("interrupted", "open"):
        return ep["resolution"]
    return None


def countable(episodes):
    return [e for e in episodes if exclusion(e) is None]


def excluded_counts(episodes):
    out = {"left_censored": 0, "interrupted": 0, "open": 0}
    for e in episodes:
        why = exclusion(e)
        if why:
            out[why] += 1
    return out


GRADE_WINDOW_S = 86400
VERDICT_ORDER = ("confirmed", "refuted", "inconclusive")


def grade_lines(store, run):
    """One `grades last day [<kind>]` line per decision kind of the run. Window: decided_at >= (the latest decided_at of
    any decision of the run) - 86400 s, event time. Only graded decisions' verdicts are counted."""
    decs = [d for d in store.select("decisions") if d["run"] == run]
    if not decs:
        return []
    anchor = max(d["decided_at"] for d in decs)
    out = []
    for kind in sorted({d["kind"] for d in decs}):
        counts = {}
        for d in decs:
            if d["kind"] == kind and d["status"] == "graded" and d["decided_at"] >= anchor - GRADE_WINDOW_S:
                counts[d["verdict"]] = counts.get(d["verdict"], 0) + 1
        verdicts = list(VERDICT_ORDER) + sorted(v for v in counts if v not in VERDICT_ORDER and v is not None)
        a, b = counts.get("confirmed", 0), counts.get("refuted", 0)
        out.append(f"grades last day [{kind}]: " + ", ".join(f"{v} {counts.get(v, 0)}" for v in verdicts)
                   + f", accuracy {a / (a + b) if a + b else 'null'}")
    return out


def status_lines(store, run):
    """The text of `ledger.py status`: the last 1, 5, 60 minutes (back from the latest ledger minute) and total."""
    rows = store.select("ingest_ledger", {"run": run})
    out = [f"run {run}"]
    if not rows:
        out.append("no ingest ledger rows")
    for label, win in (("last 1 min", _window(rows, 1)), ("last 5 min", _window(rows, 5)),
                       ("last 60 min", _window(rows, 60)), ("total", rows)):
        if not win:
            continue
        span = max(sum(_active_s(r) for r in win), 1e-3)
        kept, dropped = _sum(win, "bytes_kept"), _sum(win, "bytes_dropped")
        for source in sorted({r["source"] for r in win}):
            w = [r for r in win if r["source"] == source]
            out.append(f"{label} [{source}]: bytes compressed {_sum(w, 'bytes_read_compressed')}, "
                       f"uncompressed {_sum(w, 'bytes_read_uncompressed')}, messages parsed {_sum(w, 'messages_parsed')}, "
                       f"accepted {_sum(w, 'messages_accepted')}, msgs/s {_sum(w, 'messages_parsed') / span:.1f}")
        out.append(f"{label}: rejects {_sum(win, 'messages_rejected')}, duplicates {_sum(win, 'duplicates')}, "
                   f"gaps {_sum(win, 'sequence_gaps')} (missing {_sum(win, 'missing_messages')}), "
                   f"kept {kept} B, dropped {dropped} B, kept ratio {kept / max(kept + dropped, 1):.4f}")
    if rows:
        latest = max(rows, key=lambda r: r["minute"])
        out.append(f"backlog_bytes (latest row): {latest['backlog_bytes']}")
    for lag in store.select("ingest_consumer_lag", {"run": run}):
        out.append(f"kafka consumer lag [{lag['topic']}]: {lag['lag_messages']} messages over {lag['partitions']} "
                   f"partitions (at the last ledger write)")
    meta = store.select("ingest_runs", {"run": run})
    expected = meta[0].get("expected_messages") if meta else None
    cov = coverage(_sum(rows, "messages_accepted"), expected)
    out.append(f"coverage: {cov} (accepted {_sum(rows, 'messages_accepted')} / expected {expected})")
    files = {}
    for f in store.select("ingest_files", {"run": run}):
        files[f["status"]] = files.get(f["status"], 0) + 1
    out.append("files: " + (", ".join(f"{k} {v}" for k, v in sorted(files.items())) or "none"))
    eps = {}
    all_eps = store.select("stuck_episodes", {"run": run})
    for e in countable(all_eps):
        eps[(e["cause"], e["resolution"])] = eps.get((e["cause"], e["resolution"]), 0) + 1
    by_cause = {}
    for (cause, _), n in eps.items():
        by_cause[cause] = by_cause.get(cause, 0) + n
    out.append("episodes per cause: " + (", ".join(f"{k} {v}" for k, v in sorted(by_cause.items())) or "none"))
    out.append("episodes per resolution: " + (", ".join(
        f"{k} {v}" for k, v in sorted({r: sum(n for (_, rr), n in eps.items() if rr == r) for _, r in eps}.items()))
        or "none"))
    ex = excluded_counts(all_eps)
    out.append(f"episodes excluded: left_censored {ex['left_censored']}, interrupted {ex['interrupted']}, "
               f"open {ex['open']}")
    decs = {}
    for d in store.select("decisions"):
        if d["run"] == run:
            decs[(d["kind"], d["status"])] = decs.get((d["kind"], d["status"]), 0) + 1
    out.append("decisions: " + (", ".join(f"{k}/{s} {v}" for (k, s), v in sorted(decs.items())) or "none"))
    out.extend(grade_lines(store, run))
    return out


def plot(store, run, path):
    """bytes/min and backlog_bytes over time, matplotlib Agg."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = sorted(store.select("ingest_ledger", {"run": run}), key=lambda r: r["minute"])
    xs = [r["minute"] for r in rows]
    fig, (a, b) = plt.subplots(2, 1, figsize=(8, 5), sharex=True)
    a.plot(xs, [r["bytes_read_uncompressed"] for r in rows], marker="o", label="uncompressed")
    a.plot(xs, [r["bytes_read_compressed"] for r in rows], marker="o", label="compressed")
    a.set_ylabel("bytes per minute")
    a.legend()
    b.plot(xs, [r["backlog_bytes"] for r in rows], marker="o", color="tab:red")
    b.set_ylabel("backlog_bytes")
    b.set_xlabel("wall minute (epoch s)")
    fig.suptitle(f"ingest ledger: {run}")
    fig.tight_layout()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)
    return path

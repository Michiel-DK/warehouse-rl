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
                       backlog_bytes=c["backlog"], written_at=now)
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
    meta = store.select("ingest_runs", {"run": run})
    expected = meta[0].get("expected_messages") if meta else None
    cov = coverage(_sum(rows, "messages_accepted"), expected)
    out.append(f"coverage: {cov} (accepted {_sum(rows, 'messages_accepted')} / expected {expected})")
    files = {}
    for f in store.select("ingest_files", {"run": run}):
        files[f["status"]] = files.get(f["status"], 0) + 1
    out.append("files: " + (", ".join(f"{k} {v}" for k, v in sorted(files.items())) or "none"))
    eps = {}
    for e in store.select("stuck_episodes", {"run": run}):
        eps[(e["cause"], e["resolution"])] = eps.get((e["cause"], e["resolution"]), 0) + 1
    by_cause = {}
    for (cause, _), n in eps.items():
        by_cause[cause] = by_cause.get(cause, 0) + n
    out.append("episodes per cause: " + (", ".join(f"{k} {v}" for k, v in sorted(by_cause.items())) or "none"))
    out.append("episodes per resolution: " + (", ".join(
        f"{k} {v}" for k, v in sorted({r: sum(n for (_, rr), n in eps.items() if rr == r) for _, r in eps}.items()))
        or "none"))
    decs = {}
    for d in store.select("decisions"):
        if d["run"] == run:
            decs[(d["kind"], d["status"])] = decs.get((d["kind"], d["status"]), 0) + 1
    out.append("decisions: " + (", ".join(f"{k}/{s} {v}" for (k, s), v in sorted(decs.items())) or "none"))
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

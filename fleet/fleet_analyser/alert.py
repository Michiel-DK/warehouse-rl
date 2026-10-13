"""Stuck alert: polls stuck_episodes and prints one line per episode not yet alerted.

An episode is alertable when left_censored is false and its resolution is anything but interrupted (open rows count: the
alert exists to fire at T_entry, long before the episode closes). Episodes present at startup are skipped unless
from_start. Line: "<robot> stuck at <x>-<y> for <int(t_entry - start)> s, <cause>", plus " <blocker> (faulted <int> s)"
for blocked_by_faulted and " <blocker>" for blocked_by_stuck. With a latency file, one JSON line per alert:
{episode_id, alert_wall, latency_from_entry_s, latency_from_start_s, meaningful}; the latencies are wall clock minus
event time and mean something only when the run's emit config is now / realtime / speed 1 (ledger.lag_enabled).
The Alerter holds no store: poll_once(store) takes one, so a live loop can reopen the store each cycle.
"""
import json
import time

from .ledger import lag_enabled


def alertable(ep):
    return not ep.get("left_censored") and ep["resolution"] != "interrupted"


def format_line(ep):
    x, y = ep["cell"][0], ep["cell"][1]
    text = f"{ep['robot']} stuck at {x}-{y} for {int(ep['t_entry'] - ep['start'])} s, {ep['cause']}"
    if ep["cause"] == "blocked_by_faulted" and ep.get("blocker"):
        text += f" {ep['blocker']}"
        if ep.get("blocker_faulted_s") is not None:
            text += f" (faulted {int(ep['blocker_faulted_s'])} s)"
    elif ep["cause"] == "blocked_by_stuck" and ep.get("blocker"):
        text += f" {ep['blocker']}"
    return text


class Alerter:
    def __init__(self, run, clock=time.time, out=print, from_start=False, latency_out=None):
        self.run, self.clock, self.out = run, clock, out
        self.from_start, self.latency_out = from_start, latency_out
        self.alerted = set()

    def meaningful(self, store):
        meta = store.select("ingest_runs", {"run": self.run})
        return bool(meta) and lag_enabled(meta[0].get("emit_config"))

    def start(self, store):
        """Skip what is already there (unless from_start) and say once whether the latencies mean anything."""
        if not self.from_start:
            self.alerted.update(e["episode_id"] for e in store.select("stuck_episodes", {"run": self.run}))
        ok = self.meaningful(store)
        why = "" if ok else " (emit config is not now / realtime / speed 1, or unknown)"
        self.out(f"alert {self.run}: latency figures meaningful: {'yes' if ok else 'no'}{why}")

    def poll_once(self, store):
        """Alert every new alertable episode (in t_entry order); returns the printed lines."""
        rows = [e for e in store.select("stuck_episodes", {"run": self.run})
                if e["episode_id"] not in self.alerted and alertable(e)]
        meaningful = self.meaningful(store) if rows and self.latency_out else False
        lines = []
        for e in sorted(rows, key=lambda e: (e["t_entry"], e["episode_id"])):
            self.alerted.add(e["episode_id"])
            wall = self.clock()
            lines.append(format_line(e))
            self.out(lines[-1])
            if self.latency_out:
                rec = dict(episode_id=e["episode_id"], alert_wall=wall, latency_from_entry_s=wall - e["t_entry"],
                           latency_from_start_s=wall - e["start"], meaningful=meaningful)
                with open(self.latency_out, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, sort_keys=True) + "\n")
        return lines

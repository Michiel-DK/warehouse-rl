"""The causes table of S14A: what stopped the robots, per cause, in the words a client reads.

causes_table(episodes) -> rows [{cause, cause_label, episodes, seconds}] ordered by seconds descending, then cause key
ascending. Seconds are EPISODE seconds (duration_s, start to end of each episode). An episode without a duration (still
open) is not counted. cause_label comes from detector.CAUSE_LABELS (the one map); a cause outside the map keeps its key as
its label.

causes_block(episodes, stuck_bucket_s) -> dict(table=rows with `share` added, episode_seconds, stuck_bucket_s,
share_total, denominator, uncounted_open_episodes). share = cause seconds / stuck_bucket_s, the time budget's stuck bucket
of the same scope (robot, zone or run); None when the bucket is 0. Why the shares need not sum to 1: the bucket holds the
seconds of stuck stopped runs that no higher bucket claims, the episodes hold whole-episode seconds. A faulted_self episode
is mostly FAULTED seconds in the budget (the faulted bucket outranks stuck), an episode over a no_data gap or a paused
message loses those seconds to those buckets, and a left-censored or unresolved-at-end episode is counted for its recorded
length. share_total is the sum of the shares so the difference is visible, never forced to 1.
"""
from .detector import CAUSE_LABELS


def causes_table(episodes):
    acc = {}
    for e in episodes:
        if e.get("duration_s") is None:
            continue
        c = e.get("cause") or "unknown"
        row = acc.setdefault(c, dict(cause=c, cause_label=CAUSE_LABELS.get(c, c), episodes=0, seconds=0))
        row["episodes"] += 1
        row["seconds"] += e["duration_s"]
    return sorted(acc.values(), key=lambda r: (-r["seconds"], r["cause"]))


def causes_block(episodes, stuck_bucket_s):
    rows = causes_table(episodes)
    for r in rows:
        r["share"] = r["seconds"] / stuck_bucket_s if stuck_bucket_s else None
    total = sum(r["seconds"] for r in rows)
    return dict(table=rows, episode_seconds=total, stuck_bucket_s=stuck_bucket_s,
                share_total=total / stuck_bucket_s if stuck_bucket_s else None,
                denominator="time budget stuck bucket",
                uncounted_open_episodes=sum(1 for e in episodes if e.get("duration_s") is None))

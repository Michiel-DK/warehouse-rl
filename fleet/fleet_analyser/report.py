"""Stuck-episode report: Python over the Store interface (select only), so it runs on the jsonl and the clickhouse store.

report_run(store, run) -> markdown text; write_report(store, run, out_path) also writes hotspots.png next to it.
Countable episodes only (left_censored false, resolution not open / interrupted); the header states what was left out.
No wall-clock text: the same store gives a byte-identical report.md. Percentiles are nearest-rank. Definitions:
docs/SCOPE.md "S5C1".
"""
import math
from pathlib import Path

from .ledger import countable, excluded_counts
from .parse import iso

AVOIDABLE_LABEL = ("avoidable (detector definition, near-tautological at 5 s steps: every closed blocked_by_faulted "
                   "episode)")
HOTSPOTS = 20
REPEAT_MIN = 3


def nearest_rank(values, q):
    """Nearest-rank percentile of a list (None when empty): the ceil(q * n)-th smallest value."""
    if not values:
        return None
    v = sorted(values)
    return v[max(0, math.ceil(q * len(v)) - 1)]


def num(v):
    if v is None:
        return "n/a"
    return str(int(v)) if float(v).is_integer() else f"{v:.2f}"


def _cell(e):
    c = e["cell"]
    return (c[0], c[1])


def _mix(values):
    out = {}
    for v in values:
        out[str(v)] = out.get(str(v), 0) + 1
    return out


def _mix_lines(mix):
    return [f"- {k}: {n}" for k, n in sorted(mix.items())] or ["- none"]


def hotspots(eps):
    """[(zone, (x, y), count)] top 20 by count, ties by zone then cell."""
    counts = {}
    for e in eps:
        key = (str(e["zone"]), _cell(e))
        counts[key] = counts.get(key, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0][0], kv[0][1]))
    return [(z, c, n) for (z, c), n in ranked[:HOTSPOTS]]


def report_run(store, run):
    all_eps = store.select("stuck_episodes", {"run": run})
    eps = countable(all_eps)
    ex = excluded_counts(all_eps)
    out = [f"# Stuck episode report: {run}", "",
           f"{len(eps)} countable episodes (excluded: left_censored {ex['left_censored']}, interrupted "
           f"{ex['interrupted']}, open {ex['open']}).", ""]

    out += [f"## Hotspots (top {HOTSPOTS} cells by episode count; ties by zone, cell)", ""]
    out += [f"- zone {z} cell {c[0]}-{c[1]}: {n}" for z, c, n in hotspots(eps)] or ["- none"]

    out += ["", "## Episodes per event hour (hour of the episode start, UTC)", ""]
    hours = {}
    for e in eps:
        h = int(e["start"] // 3600) * 3600
        hours[h] = hours.get(h, 0) + 1
    out += [f"- {iso(h)}: {n}" for h, n in sorted(hours.items())] or ["- none"]

    durations = [e["duration_s"] for e in eps if e["duration_s"] is not None]
    out += ["", "## Duration (s, start to end; nearest-rank percentiles)", "",
            f"- p50: {num(nearest_rank(durations, 0.5))}", f"- p95: {num(nearest_rank(durations, 0.95))}"]

    out += ["", "## Cause mix", ""] + _mix_lines(_mix(e["cause"] for e in eps))
    out += ["", "## Resolution mix", ""] + _mix_lines(_mix(e["resolution"] for e in eps))

    avoid = [e for e in eps if e["avoidable"]]
    minutes = sum((e["avoidable_s"] or 0) for e in avoid) / 60
    out += ["", "## Avoidable", "", f"- {AVOIDABLE_LABEL}",
            f"- episodes: {len(avoid)}", f"- minutes: {num(round(minutes, 2))}"]

    per_robot = {}
    for e in eps:
        per_robot[e["robot"]] = per_robot.get(e["robot"], 0) + 1
    repeat = sorted(((r, n) for r, n in per_robot.items() if n >= REPEAT_MIN), key=lambda rn: (-rn[1], rn[0]))
    out += ["", f"## Repeat robots (>= {REPEAT_MIN} episodes)", ""]
    out += [f"- {r}: {n}" for r, n in repeat] or ["- none"]

    waits = [e["end"] - e["t_entry"] for e in eps if e["end"] is not None]
    out += ["", "## Time from stuck to resolution (s, end minus t_entry; nearest-rank percentiles)", "",
            f"- p50: {num(nearest_rank(waits, 0.5))}", f"- p95: {num(nearest_rank(waits, 0.95))}"]

    grades = {}
    for d in store.select("decisions"):
        if d["run"] == run:
            key = (d["kind"], d["verdict"] if d["status"] == "graded" else "open")
            grades[key] = grades.get(key, 0) + 1
    out += ["", "## Decision grades per kind and verdict (open = not graded yet)", ""]
    out += [f"- {k} / {v}: {n}" for (k, v), n in sorted(grades.items())] or ["- none"]
    return "\n".join(out) + "\n"


def plot_hotspots(eps, path):
    """One heatmap per zone of episode count per cell (matplotlib Agg)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    zones = sorted({str(e["zone"]) for e in eps})
    fig, axes = plt.subplots(1, max(len(zones), 1), figsize=(5 * max(len(zones), 1), 4.5), squeeze=False)
    if not zones:
        axes[0][0].text(0.5, 0.5, "no countable episodes", ha="center", va="center")
        axes[0][0].set_axis_off()
    for ax, zone in zip(axes[0], zones):
        cells = [_cell(e) for e in eps if str(e["zone"]) == zone]
        w, h = max(c[0] for c in cells) + 1, max(c[1] for c in cells) + 1
        grid = [[0] * w for _ in range(h)]
        for x, y in cells:
            grid[y][x] += 1
        im = ax.imshow(grid, cmap="viridis", origin="upper")
        ax.set_title(f"zone {zone}: episodes per cell")
        ax.set_xlabel("x")
        ax.set_ylabel("y")
        fig.colorbar(im, ax=ax, shrink=0.8)
    fig.tight_layout()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)
    return path


def write_report(store, run, out_path):
    """Write report.md and hotspots.png (next to it); returns the two paths."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report_run(store, run), encoding="utf-8")
    png = plot_hotspots(countable(store.select("stuck_episodes", {"run": run})), out_path.parent / "hotspots.png")
    return out_path, png

"""Evaluation smoke for the fast detector (S10I): the S10E map, a short-memory map and the CUSUM, side by side at K 20.

Usage: python fleet/fastmap_smoke.py [--data-root DIR] [--out PATH] [--grid k:h,k:h,...]
DIR (default <repo>/fleet/data) holds the blind-blockage run s10c-blind (50 blocked windows, known:false) and the
undisturbed reference s10-none. Both are copied into a temp directory (zone files symlinked, store and truth copied); the
originals are never written, and nothing is written under results/. Rows, each "ROW <arm>: detected n/N, median
first-detect S s, FA/h ref X" with FA/h in the unit of the AMOC field fa_per_hour_reference (flags per zone per simulated
hour on the reference):
  a      the S10E map, read from the tracked results/fleet/amoc_blind.json (K 20 entry), not rerun
  b      short-memory map: publish 60, --window-hours 0.2, --half-life-h 0.1 (time_to_detect rerun mode)
  c      fastmap CUSUM at its defaults, publish 60 (time_to_detect prebuilt mode)
  c-end  the same with --count end (the map's end-time counting rule, for attribution)
  --grid adds (c)-style rows for other (k, h) pairs; they are tuned IN-SAMPLE on s10c-blind and labelled so.
Evaluation script like blind_smoke.py: it reads truth.json through time_to_detect on purpose; nothing in the analyser
imports it. It is not `fastmap.py --smoke` because a truth kind in fastmap.py would trip the analyst isolation scan.
"""
import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

FLEET = Path(__file__).resolve().parent
REPO = FLEET.parent
if str(FLEET) not in sys.path:
    sys.path.insert(0, str(FLEET))

import costmap  # noqa: E402
import fastmap  # noqa: E402
import time_to_detect as ttd  # noqa: E402

K = 20
EVERY = 60
RUN_MEASURED, RUN_REFERENCE = "s10c-blind", "s10-none"
AMOC_BLIND = REPO / "results" / "fleet" / "amoc_blind.json"
SHORT_WINDOW_H, SHORT_HALF_LIFE_H = 0.2, 0.1


def copy_run(src, dst):
    """Zone files symlinked, truth.json and store/ copied (the smoke may build store-* copies next to them)."""
    src, dst = Path(src), Path(dst)
    dst.mkdir(parents=True)
    for f in sorted(src.glob("*.jsonl.gz")):
        (dst / f.name).symlink_to(f.resolve())
    shutil.copy2(src / "truth.json", dst / "truth.json")
    for name in ("phaseA_meta.json",):
        if (src / name).exists():
            shutil.copy2(src / name, dst / name)
    shutil.copytree(src / "store", dst / "store")
    return dst


def entry_row(arm, e, note=""):
    return dict(arm=arm, detected=e["n_detected"], windows=e["n_windows"], median_delay_s=e["median_delay_s"],
                fa_per_hour_reference=e["fa_per_hour_reference"], note=note)


def format_row(r):
    med = "n/a" if r["median_delay_s"] is None else f"{r['median_delay_s']:.1f}"
    fa = "n/a" if r["fa_per_hour_reference"] is None else f"{r['fa_per_hour_reference']:.3f}"
    return f"ROW {r['arm']}: detected {r['detected']}/{r['windows']}, median first-detect {med} s, FA/h ref {fa}" + (
        f"  [{r['note']}]" if r["note"] else "")


def k_entry(doc, k=K):
    return next(e for e in doc["amoc"]["k"] if e["K"] == k)


def arm_a():
    d = json.loads(AMOC_BLIND.read_text())
    return entry_row("a", k_entry(d), "S10E map, results/fleet/amoc_blind.json, not rerun")


def measure(measured, reference, suffix, out, **kw):
    return ttd.run(measured, EVERY, [K], out, truth_kind="blocked", reference=reference, sweep_k=[K],
                   store_suffix=suffix, **kw)


def build_fast(root, run, suffix, rule, k, h):
    """fastmap into <root>/<run>/store-<suffix> (a prebuilt copy for time_to_detect)."""
    d = root / run
    return fastmap.run_fastmap(str(d / "*.jsonl.gz"), run, d / f"store-{suffix}", root / f"fastmap-{run}-{suffix}.json",
                        publish_every=EVERY, k=k, h=h, rule=rule)


def total_flags(doc):
    return sum(len(c) for pb in doc["publishes"] for c in pb["flagged"].values())


def empty_row(root, arm, ref_flags, note):
    """The measured run got no flag at all: time_to_detect refuses a store with no forecast row (prebuilt mode), so the row
    is written here: nothing detected, FA/h from the reference's flag count in the AMOC unit."""
    tr = json.loads((root / RUN_MEASURED / "truth.json").read_text())
    ref = json.loads((root / RUN_REFERENCE / "truth.json").read_text())
    n = sum(len(z.get("blocked_windows") or ()) for z in tr["zones"].values())
    fa = ref_flags / (len(ref["zones"]) * ttd.sim_hours(ref))
    return dict(arm=arm, detected=0, windows=n, median_delay_s=None, fa_per_hour_reference=fa,
                note=note + "; no flag on s10c-blind, row written by the smoke")


def arm_cusum(root, suffix, arm, rule, k, h, note):
    docs = {run: build_fast(root, run, suffix, rule, k, h) for run in (RUN_MEASURED, RUN_REFERENCE)}
    if total_flags(docs[RUN_MEASURED]) == 0:
        return empty_row(root, arm, total_flags(docs[RUN_REFERENCE]), note)
    doc = measure(root / RUN_MEASURED, root / RUN_REFERENCE, suffix, root / f"ttd-{suffix}.json")
    assert set(doc["meta"]["store_mode"].values()) == {"prebuilt"}
    return entry_row(arm, k_entry(doc), note)


def parse_grid(text):
    pairs = []
    for item in text.split(","):
        k, _, h = item.partition(":")
        pairs.append((float(k), float(h)))
    return pairs


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--data-root", default=str(FLEET / "data"), metavar="DIR")
    p.add_argument("--out", default=None, metavar="PATH", help="rows as JSON (refused under results/)")
    p.add_argument("--grid", default=None, metavar="k:h,k:h", help="extra CUSUM rows (in-sample on s10c-blind)")
    a = p.parse_args(argv)
    if a.out is not None and (REPO / "results").resolve() in Path(a.out).resolve().parents:
        p.error("--out must not be under results/")
    grid = parse_grid(a.grid) if a.grid else []
    root_in = Path(a.data_root)
    for run in (RUN_MEASURED, RUN_REFERENCE):
        if not (root_in / run / "truth.json").exists():
            p.error(f"{root_in / run} is not a run directory")
    t_start = time.time()
    rows = []
    with tempfile.TemporaryDirectory(prefix="fastmap-smoke-") as tmp:
        root = Path(tmp)
        copy_run(root_in / RUN_MEASURED, root / RUN_MEASURED)
        copy_run(root_in / RUN_REFERENCE, root / RUN_REFERENCE)
        rows.append(arm_a())
        doc = measure(root / RUN_MEASURED, root / RUN_REFERENCE, "shortmap", root / "ttd-shortmap.json",
                      window_hours=SHORT_WINDOW_H, half_life_h=SHORT_HALF_LIFE_H)
        rows.append(entry_row("b", k_entry(doc), f"short map: publish {EVERY}, window {SHORT_WINDOW_H} h, "
                                                 f"half-life {SHORT_HALF_LIFE_H} h"))
        rows.append(arm_cusum(root, "fast", "c", "active", fastmap.DEFAULT_K, fastmap.DEFAULT_H,
                              f"CUSUM defaults k {fastmap.DEFAULT_K} h {fastmap.DEFAULT_H}, count active, publish {EVERY}"))
        rows.append(arm_cusum(root, "fastend", "c-end", "end", fastmap.DEFAULT_K, fastmap.DEFAULT_H,
                              f"CUSUM defaults, count end, publish {EVERY}"))
        for i, (k, h) in enumerate(grid):
            rows.append(arm_cusum(root, f"grid{i}", f"c-k{k:g}-h{h:g}", "active", k, h,
                                  "IN-SAMPLE tuned on s10c-blind, not a held-out result"))
    elapsed = time.time() - t_start
    for r in rows:
        print(format_row(r))
    print(f"fastmap_smoke: {len(rows)} rows, K {K}, elapsed {elapsed:.1f} s")
    if a.out:
        costmap.write_json(a.out, dict(rows=rows, elapsed_s=elapsed))
    return 0


if __name__ == "__main__":
    sys.exit(main())

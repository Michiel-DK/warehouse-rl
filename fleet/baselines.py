"""Persistence baseline and chance lines for the published cost map (S10D). Scoring only: reads the store, never writes it.

Question: does the exponentially decayed map beat "the next window looks like the last one" (persistence), and how far
above a random draw from the cells that can stall at all (Adepeju et al. 2016)? hotspot_score.py --baselines calls
compute() and writes the result as ONE extra top-level key `baselines`; without the flag nothing here runs.

This module reads no ground-truth file and imports no truth module. hotspot_score.py passes in the truth predicate
(positives_fn) and the candidate cell set, so the fence on who reads the emitter's truth stays where it is.

Forecasts, per zone and per publish time t (the distinct published_at values of the run's costmap table; a zone with no
rows at t has an empty map):
  * map top-K = hotspot.rank_cells of the zone's published rows at t (cost desc, cell string), first K.
  * persistence top-K = the same published rows ordered by their raw `stalls` column (the window count) descending, ties
    by cell string, first K.
WINDOW CONVENTION: the `stalls` column counts stalls with t - W*3600 < end <= t, i.e. the window (t - W, t] by stall end,
passing hotspot.counted(s, exclude_occupied) and min_stalls: exactly the map's own boundary, so the ONLY difference
between the two forecasts is the exponential decay. (The task text said [t - W, t); we follow the map's boundary.) W is
the MAP window from the costmap meta, never hotspot_score's --window-h (that is the lesson window of S8S).
CONSEQUENCE: with min_stalls 1 both lists draw from the same flagged set, so at K >= n_flagged the two top-K sets are
equal and every map-minus-persistence delta is exactly 0.

Scores at every K (a short list counts its missing slots as misses, as hotspot_score.precision_recall does):
  * outcome precision = share of the K slots whose cell has rank <= K in the zone's map recomputed at t + H
    (forecast_grade.ranked_zone, the claim's own map parameters), over outcome-eligible units only: forecast_grade.
    stream_end(zone) is not None and >= t + H, and H >= forecast_grade.DEFAULT_MIN_HORIZON_S.
  * truth precision = hits / K, truth recall = hits / positives, PAI = (hits / positives) / (K / N_all), where positives =
    candidate cells with a truth positive over [t, t + H] and N_all = the number of candidate cells (the env's highway
    non-goal cells, derived by hotspot_score.py). recall and PAI are null at 0 positives. Pooled over units: precision =
    sum hits / (K * units); recall and PAI from the summed hits and summed positives. n_units_truth counts every
    (zone, t); n_units_outcome only the eligible ones. Pooled PAI equals truth lift_all exactly.
Chance (truth precision of a random K-draw from a pool = positives in pool / pool size, pooled as sum / sum): chance_all =
pool is the N_all candidate cells; chance_ever = pool is the zone's cells with >= 1 counted stall anywhere in the stream
(includes cells outside the candidate set; n_ever and n_ever_outside_candidates are reported per zone). chance_ever is not
guaranteed to be >= chance_all. lift_all / lift_ever = truth precision / chance (null when the chance is 0).
paired: per zone d_z = map minus persistence precision (over that zone's units), mean over zones, 1000-resample zone
bootstrap (random.Random(0), mean of d), ci95 = 2.5 / 97.5 percentiles, verdict by the scripts/sprint8_tables.py rule
(CI low > 0 "beats", CI high < 0 "worse", else "within noise"), for K 20 and 40, truth and outcome precision.
lesson_persist (hot_cell lessons only): observed rate against three named pools, chance_window (the S8S per-window pool,
read from the lesson_persist_chance block), chance_ever (share of the zone's ever-stalled cells that clear the persist bar
over the lesson's next window) and chance_all (the same count over N_all). A cell clears the bar iff it appears in
lessons.STATS["hot_cell"] over the next window with ratio >= lessons.PERSIST_RATIO (what lessons.next_value decides).
Usage: python fleet/baselines.py --smoke [--data-dir DIR]   (re-scores fleet/data/s8b-score with --baselines, < 120 s)
"""
import argparse
import hashlib
import json
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path

FLEET = Path(__file__).resolve().parent
REPO = FLEET.parent
if str(FLEET) not in sys.path:
    sys.path.insert(0, str(FLEET))

from fleet_analyser import forecast_grade, hotspot, lessons  # noqa: E402

KS = (20, 40, 80, 120)
PAIRED_KS = (20, 40)
BOOTSTRAP_SEED = 0
N_RESAMPLES = 1000
SMOKE_TAG = "s8b-medium-80-p03-07"
SMOKE_LIMIT_S = 120.0
FORECASTS = ("map", "persistence")


def zone_sort_key(z):
    return (0, int(z), z) if str(z).isdigit() else (1, 0, str(z))


def horizon_of(store, run):
    """The run's one hotspot_forecast horizon_s. ValueError when the claims carry none or more than one."""
    hs = set()
    for d in forecast_grade.forecasts(store, run):
        claim = json.loads(d["claim"]) if isinstance(d["claim"], str) else d["claim"]
        hs.add(claim["horizon_s"])
    if len(hs) != 1:
        raise ValueError(f"run {run}: need exactly one hotspot_forecast horizon_s in the claims, found {sorted(hs)}")
    return hs.pop()


def map_top(rows):
    """Cells of one (zone, t) published rows {cell: row}, most expensive first (hotspot.rank_cells)."""
    return [c for c, _ in hotspot.rank_cells(rows)]


def persistence_top(rows):
    """Cells by raw window count (`stalls`) descending, ties by cell string."""
    return [c for c, _ in sorted(rows.items(), key=lambda kv: (-kv[1]["stalls"], kv[0]))]


def percentile(sorted_vals, q):
    """Linear-interpolation percentile (q in 0..100) of an ascending list."""
    pos = (len(sorted_vals) - 1) * q / 100
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def verdict(lo, hi):
    return "beats" if lo > 0 else "worse" if hi < 0 else "within noise"


def paired_ci(deltas, n_resamples=N_RESAMPLES, seed=BOOTSTRAP_SEED):
    """Zone bootstrap of the mean of the per-zone deltas: {mean, ci95, verdict, n_zones}; nulls with no zone."""
    n = len(deltas)
    if not n:
        return dict(mean=None, ci95=None, verdict=None, n_zones=0)
    rng = random.Random(seed)
    means = sorted(sum(deltas[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_resamples))
    lo, hi = percentile(means, 2.5), percentile(means, 97.5)
    return dict(mean=sum(deltas) / n, ci95=[lo, hi], verdict=verdict(lo, hi), n_zones=n)


def _ratio(num, den):
    return num / den if den else None


def read_units(store, run, zones):
    """{(zone, t): {cell: costmap row}} for every zone in `zones` and every distinct published_at of the run."""
    rows = store.select("costmap", {"run": run})
    times = sorted({r["published_at"] for r in rows})
    units = {(z, t): {} for z in zones for t in times}
    for r in rows:
        key = (str(r["zone"]), r["published_at"])
        if key in units:
            units[key][r["cell"]] = r
    return times, units


def ever_pools(stalls, exclude_occupied):
    """{zone: set of cells with >= 1 counted stall anywhere in the stream}."""
    out = {}
    for s in stalls:
        if hotspot.counted(s, exclude_occupied):
            out.setdefault(str(s["zone"]), set()).add(s["cell"])
    return out


def score_units(units, zones, ks, horizon_s, candidates, positives_fn, outcome_rank_fn, ever):
    """Per forecast and K the pooled hits, plus the per-zone tallies the paired CI needs.
    outcome_rank_fn(zone, t) -> {cell: rank} at t + H, or None when the unit is not outcome-eligible."""
    n_all = len(candidates)
    tally = {f: {k: dict(hits=0, outcome_hits=0, zone={z: dict(h=0, u=0, oh=0, ou=0) for z in zones}) for k in ks}
             for f in FORECASTS}
    n_truth = n_outcome = positives = pool_all = pool_ever = pos_ever = 0
    for (z, t), rows in sorted(units.items(), key=lambda kv: (zone_sort_key(kv[0][0]), kv[0][1])):
        pos = set(positives_fn(z, t, horizon_s)) & set(candidates)
        n_truth += 1
        positives += len(pos)
        pool_all += n_all
        pool_ever += len(ever.get(z, ()))
        pos_ever += len(pos & ever.get(z, set()))
        ranks = outcome_rank_fn(z, t)
        if ranks is not None:
            n_outcome += 1
        tops = dict(map=map_top(rows), persistence=persistence_top(rows))
        for f in FORECASTS:
            for k in ks:
                top = tops[f][:k]
                h = sum(1 for c in top if c in pos)
                tl = tally[f][k]
                tl["hits"] += h
                zt = tl["zone"][z]
                zt["h"] += h
                zt["u"] += 1
                if ranks is not None:
                    oh = sum(1 for c in top if ranks.get(c, k + 1) <= k)
                    tl["outcome_hits"] += oh
                    zt["oh"] += oh
                    zt["ou"] += 1
    return tally, dict(n_truth=n_truth, n_outcome=n_outcome, positives=positives, pool_all=pool_all,
                       pool_ever=pool_ever, pos_ever=pos_ever)


def lesson_persist_block(store, run, ever, n_all, persist_block):
    """The three-pool lesson_persist comparison (hot_cell lessons only); see the module docstring."""
    empty = dict(chance_window=None, chance_ever=None, chance_all=None, lift_window=None, lift_ever=None,
                 lift_all=None, s8s_pool_is_ever=None, n_lessons=0, n_hot_robot_excluded=0, observed_rate=None,
                 pools_note="chance_window = S8S per-window pool (cells with >= 1 stall in the lesson's own window); "
                            "chance_ever = zone's ever-stalled cells clearing the persist bar over the next window; "
                            "chance_all = the same count over all candidate cells")
    per = (persist_block or {}).get("per_lesson") or []
    decisions = {d["id"]: lessons.claim_of(d) for d in lessons.lessons(store, run)}
    cell_rows = [r for r in per if r["id"] in decisions and decisions[r["id"]]["lesson_kind"] == "hot_cell"]
    out = dict(empty, n_hot_robot_excluded=sum(1 for r in per if r["id"] in decisions
                                               and decisions[r["id"]]["lesson_kind"] == "hot_robot"))
    if not cell_rows:
        return out
    data = lessons.Data(store, run)
    rates = dict(window=[], ever=[], all=[])
    same_pool = True
    for r in cell_rows:
        claim = decisions[r["id"]]
        zone, ws, we = str(claim["zone"]), r["window_start"], claim["window_end"]
        pool = ever.get(zone, set())
        own = {st["subject"] for st in lessons.STATS["hot_cell"](data.window(zone, ws, we), None)}
        same_pool = same_pool and own == {f"Z{zone}:cell {c}" for c in pool}
        shift = lessons.horizon("hot_cell", we - ws)
        nxt = lessons.STATS["hot_cell"](data.window(zone, ws + shift, we + shift), None)
        clear = {st["subject"] for st in nxt if (st["ratio"] or 0) >= lessons.PERSIST_RATIO}
        ok = sum(1 for c in pool if f"Z{zone}:cell {c}" in clear)
        rates["window"].append(r["chance"])
        rates["ever"].append(ok / len(pool) if pool else 0.0)
        rates["all"].append(ok / n_all if n_all else 0.0)
    n = len(cell_rows)
    observed = sum(1 for r in cell_rows if r["observed"]) / n
    mean = {k: sum(v) / n for k, v in rates.items()}
    out.update(chance_window=mean["window"], chance_ever=mean["ever"], chance_all=mean["all"],
               lift_window=_ratio(observed, mean["window"]), lift_ever=_ratio(observed, mean["ever"]),
               lift_all=_ratio(observed, mean["all"]), s8s_pool_is_ever=same_pool, n_lessons=n, observed_rate=observed)
    return out


def compute(store, run, zones, meta, candidates, positives_fn, persist_block=None, ks=KS):
    """The `baselines` block. zones: truth zone ids; meta: the costmap meta (window_hours, half_life_h, min_stalls,
    exclude_occupied); candidates: the cell strings of the candidate set; positives_fn(zone, t, horizon_s) -> cells that
    are truth positives over [t, t + H] (passed in by hotspot_score.py); persist_block: the lesson_persist_chance block."""
    zones = sorted((str(z) for z in zones), key=zone_sort_key)
    candidates = set(candidates)
    n_all = len(candidates)
    horizon_s = horizon_of(store, run)
    claim = {k: meta[k] for k in ("window_hours", "half_life_h", "min_stalls", "exclude_occupied")}
    stalls = store.select("stalls", {"run": run})
    stalls_by_zone = {}
    for s in stalls:
        stalls_by_zone.setdefault(str(s["zone"]), []).append(s)
    ends, rank_cache = {}, {}

    def outcome_rank(z, t):
        if horizon_s < forecast_grade.DEFAULT_MIN_HORIZON_S:
            return None
        if z not in ends:
            ends[z] = forecast_grade.stream_end(store, run, z)
        if ends[z] is None or ends[z] < t + horizon_s:
            return None
        return forecast_grade.ranked_zone(stalls_by_zone, rank_cache, z, t + horizon_s, claim)

    times, units = read_units(store, run, zones)
    ever = ever_pools(stalls, claim["exclude_occupied"])
    tally, n = score_units(units, zones, ks, horizon_s, candidates, positives_fn, outcome_rank, ever)
    chance_all = _ratio(n["positives"], n["pool_all"])
    chance_ever = _ratio(n["pos_ever"], n["pool_ever"])
    k_out = {}
    for k in ks:
        k_out[str(k)] = {}
        for f in FORECASTS:
            tl = tally[f][k]
            tp = _ratio(tl["hits"], k * n["n_truth"])
            recall = _ratio(tl["hits"], n["positives"])
            k_out[str(k)][f] = dict(
                outcome_precision=_ratio(tl["outcome_hits"], k * n["n_outcome"]), truth_precision=tp,
                truth_recall=recall,
                pai=_ratio(recall, k / n_all) if recall is not None and n_all else None,
                lift_all=_ratio(tp, chance_all) if tp is not None else None,
                lift_ever=_ratio(tp, chance_ever) if tp is not None else None,
                hits=dict(truth=tl["hits"], outcome=tl["outcome_hits"], positives=n["positives"]))
    paired = {}
    for k in PAIRED_KS:
        if k not in ks:
            continue
        zm, zp = tally["map"][k]["zone"], tally["persistence"][k]["zone"]
        truth_d = [zm[z]["h"] / (k * zm[z]["u"]) - zp[z]["h"] / (k * zp[z]["u"]) for z in zones if zm[z]["u"]]
        out_d = [zm[z]["oh"] / (k * zm[z]["ou"]) - zp[z]["oh"] / (k * zp[z]["ou"]) for z in zones if zm[z]["ou"]]
        paired[str(k)] = dict(truth_precision=paired_ci(truth_d), outcome_precision=paired_ci(out_d))
    return dict(
        params=dict(window_hours=meta["window_hours"], half_life_h=meta["half_life_h"], min_stalls=meta["min_stalls"],
                    exclude_occupied=meta["exclude_occupied"], horizon_s=horizon_s, n_cells_all=n_all, ks=list(ks),
                    bootstrap_seed=BOOTSTRAP_SEED, n_resamples=N_RESAMPLES),
        chance=dict(all=chance_all, ever=chance_ever,
                    per_zone={z: dict(n_ever=len(ever.get(z, ())), n_ever_outside_candidates=len(ever.get(z, set())
                                                                                              - candidates))
                              for z in zones}),
        k=k_out, n_units_truth=n["n_truth"], n_units_outcome=n["n_outcome"], paired=paired,
        lesson_persist=lesson_persist_block(store, run, ever, n_all, persist_block))


def store_digest(store_dir):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(store_dir).iterdir()) if p.is_file()}


def smoke(data_dir=None, log=print):
    """Re-score fleet/data/s8b-score (or --data-dir) with --baselines into a tmp dir. Exit code 0 only when the scorer
    exits 0, the output has a `baselines` key, the store files are byte-identical afterwards and it took < 120 s."""
    data = Path(data_dir) if data_dir else REPO / "fleet" / "data" / "s8b-score"
    if not (data / "truth.json").exists():
        log(f"smoke: {data} has no truth.json (fleet/data is untracked; pass --data-dir)")
        return 1
    before = store_digest(data / "store")
    with tempfile.TemporaryDirectory(prefix="baselines_smoke_") as tmp:
        out = Path(tmp) / "hotspot.json"
        t0 = time.monotonic()
        r = subprocess.run([sys.executable, str(FLEET / "hotspot_score.py"), "--run-dir", str(data), "--store",
                            f"jsonl:{data / 'store'}", "--tag", SMOKE_TAG, "--baselines", "--out", str(out)],
                           capture_output=True, text=True)
        elapsed = time.monotonic() - t0
        if r.returncode:
            log(f"smoke: hotspot_score failed ({r.returncode}): {r.stderr.strip()[-400:]}")
            return 1
        res = json.loads(out.read_text())
    if "baselines" not in res:
        log("smoke: no baselines key in the output")
        return 1
    if store_digest(data / "store") != before:
        log("smoke: the store changed")
        return 1
    log(f"smoke: baselines scored in {elapsed:.1f}s, store unchanged")
    return 0 if elapsed < SMOKE_LIMIT_S else 1


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--smoke", action="store_true", help="re-score fleet/data/s8b-score with --baselines (< 120 s)")
    p.add_argument("--data-dir", default=None, help="--smoke only: the run dir (default fleet/data/s8b-score)")
    a = p.parse_args([str(x) for x in argv] if argv is not None else None)
    if not a.smoke:
        p.error("only --smoke is available here; use hotspot_score.py --baselines to score a run")
    return smoke(a.data_dir)


if __name__ == "__main__":
    sys.exit(main())

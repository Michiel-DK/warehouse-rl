"""Score a published cost map against the emitter's floor ground truth (the only module besides grade.py that reads it).

Usage: python fleet/hotspot_score.py --run-dir DIR --store jsonl:DIR|clickhouse://... --tag NAME
       [--costmap DIR/costmap.json] [--out results/fleet/hotspot_<tag>.json]
DIR holds truth.json and emit_ledger.json (the emitter's output). Per zone and as the mean over zones, for K in
{20, 40, 80, 120}: precision@K = floor cells among the K most expensive flagged cells / K (a map with fewer than K
flagged cells counts the missing slots as misses; n_flagged is reported) and recall@K = those hits / |floor cells of the
zone|. Cost ties break on the cell string. Spearman (average ranks on ties) between cost and true p (0 for non-floor
cells) over the flagged cells, null below 3 flagged cells or when either side is constant. zero_stall_share = share of
the zone's floor cells with no stall of any kind in the store. Also: forecast_grades counts by (grade_source, verdict) as grading_counts: "outcome" = the
rank grade (cell still in the zone's top K at window_end), "outcome_count" = the count grade (stall count within
tolerance), "truth", and, when the store holds lessons (S8E), "lesson" (next-window grade) and "lesson_truth"
(hot_cell lessons against the floor); lesson rows enter nothing else; rank_grading = {top_k: sorted K values seen, rank_graded: n forecasts with an "outcome" row,
unranked: n forecasts with an "outcome_count" row but no "outcome" row (rank > K or a v1 claim)};
stall_in_episode counts by detector cause, platform.
"""
import argparse
import json
import platform
import sys
from pathlib import Path

FLEET = Path(__file__).resolve().parent
REPO = FLEET.parent
if str(FLEET) not in sys.path:
    sys.path.insert(0, str(FLEET))

from fleet_analyser import store as store_mod  # noqa: E402

KS = (20, 40, 80, 120)


def ranked_cells(costmap_zone):
    """Flagged cells, most expensive first, ties by cell string."""
    return [c for c, v in sorted(costmap_zone.items(), key=lambda kv: (-kv[1], kv[0])) if v > 0]


def precision_recall(costmap_zone, floor_cells, ks=KS):
    order = ranked_cells(costmap_zone)
    out = {}
    for k in ks:
        hits = sum(1 for c in order[:k] if c in floor_cells)
        out[k] = dict(precision=hits / k, recall=hits / len(floor_cells) if floor_cells else None, hits=hits)
    return out


def _avg_ranks(values):
    idx = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(idx):
        j = i
        while j + 1 < len(idx) and values[idx[j + 1]] == values[idx[i]]:
            j += 1
        for t in range(i, j + 1):
            ranks[idx[t]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(xs, ys):
    """Pearson correlation of the average ranks; None below 3 points or when either side is constant."""
    if len(xs) < 3:
        return None
    rx, ry = _avg_ranks(xs), _avg_ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if sxx == 0 or syy == 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(rx, ry)) / (sxx * syy) ** 0.5


def score_zone(costmap_zone, floor_cells, stall_cells, ks=KS):
    """floor_cells: {"x,y": p}; stall_cells: set of cells with any stall."""
    flagged = ranked_cells(costmap_zone)
    pr = precision_recall(costmap_zone, floor_cells, ks)
    rho = spearman([costmap_zone[c] for c in flagged], [floor_cells.get(c, 0.0) for c in flagged])
    zero = (sum(1 for c in floor_cells if c not in stall_cells) / len(floor_cells)) if floor_cells else None
    return dict(n_flagged=len(flagged), n_floor=len(floor_cells), spearman=rho, zero_stall_share=zero,
                k={str(k): v for k, v in pr.items()})


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def score_run(truth, costmap, stalls, grades, ks=KS):
    zones = {}
    for z in sorted(truth["zones"], key=lambda s: int(s) if s.isdigit() else s):
        floor = truth["zones"][z]["floor_cells"]
        cells = {s["cell"] for s in stalls if s["zone"] == z}
        zones[z] = score_zone(costmap["zones"].get(z, {}), floor, cells, ks)
    mean = dict(n_flagged=_mean([v["n_flagged"] for v in zones.values()]),
                spearman=_mean([v["spearman"] for v in zones.values()]),
                zero_stall_share=_mean([v["zero_stall_share"] for v in zones.values()]),
                k={str(k): dict(precision=_mean([v["k"][str(k)]["precision"] for v in zones.values()]),
                                recall=_mean([v["k"][str(k)]["recall"] for v in zones.values()])) for k in ks})
    grading = {}
    for g in grades:
        grading.setdefault(g["grade_source"], {}).setdefault(g["verdict"], 0)
        grading[g["grade_source"]][g["verdict"]] += 1
    outcome_ids = {g["id"] for g in grades if g["grade_source"] == "outcome"}
    count_ids = {g["id"] for g in grades if g["grade_source"] == "outcome_count"}
    rank_grading = dict(top_k=sorted({g["expected"] for g in grades if g["grade_source"] == "outcome"}),
                        rank_graded=len(outcome_ids), unranked=len(count_ids - outcome_ids))
    in_episode = {}
    for s in stalls:
        if s["in_episode"] is not None:
            in_episode[s["in_episode"]] = in_episode.get(s["in_episode"], 0) + 1
    return dict(zones=zones, mean=mean, grading_counts=grading, rank_grading=rank_grading,
                stall_in_episode=dict(total_stalls=len(stalls), in_episode=sum(in_episode.values()),
                                      by_cause=dict(sorted(in_episode.items()))))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--run-dir", required=True)
    p.add_argument("--costmap", default=None)
    p.add_argument("--store", default=None)
    p.add_argument("--tag", required=True)
    p.add_argument("--out", default=None)
    a = p.parse_args(argv)
    run_dir = Path(a.run_dir)
    truth = json.loads((run_dir / "truth.json").read_text())
    ledger_path = run_dir / "emit_ledger.json"
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {}
    costmap = json.loads(Path(a.costmap or run_dir / "costmap.json").read_text())
    run = costmap["run"]
    try:
        st = store_mod.open_store(a.store, run)
    except ValueError as e:
        p.error(str(e))
    stalls = st.select("stalls", {"run": run})
    grades = st.select("forecast_grades", {"run": run})
    st.close()
    res = score_run(truth, costmap, stalls, grades)
    res.update(tag=a.tag, run=run,
               config=dict(env_id=truth["env_id"], disturb_tag=truth["disturb_tag"], disturb=truth["disturb"],
                           steps=truth["steps"], seed_base=truth["seed_base"], zones=len(truth["zones"]),
                           emit_status=ledger.get("status"), emit_schema=(ledger.get("config") or {}).get("schema_version")),
               costmap=dict(generated_at=costmap["generated_at"], window_hours=costmap["window_hours"],
                            half_life_h=costmap["half_life_h"], min_stalls=costmap["min_stalls"],
                            exclude_occupied=costmap["exclude_occupied"]),
               platform=dict(platform=platform.platform(), python=sys.version.split()[0]))
    out = Path(a.out) if a.out else REPO / "results" / "fleet" / f"hotspot_{a.tag}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1))
    m = res["mean"]
    print(f"hotspot {a.tag}: n_flagged mean {m['n_flagged']}, spearman mean {m['spearman']}, zero-stall share "
          f"{m['zero_stall_share']}")
    for k in KS:
        rec = m['k'][str(k)]['recall']  # None when the run has no floor cells
        print(f"  K={k}: precision {m['k'][str(k)]['precision']:.3f} recall {'n/a' if rec is None else format(rec, '.3f')}")
    print(f"  grading {res['grading_counts']}; rank_grading {res['rank_grading']}; "
          f"stall_in_episode {res['stall_in_episode']}")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

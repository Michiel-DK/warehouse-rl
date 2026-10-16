"""Score a published cost map against the emitter's floor ground truth (the only module besides grade.py that reads it).

Usage: python fleet/hotspot_score.py --run-dir DIR --store jsonl:DIR|clickhouse://... --tag NAME
       [--costmap DIR/costmap.json] [--out results/fleet/hotspot_<tag>.json] [--window-h W]
DIR holds truth.json and emit_ledger.json (the emitter's output). Per zone and as the mean over zones, for K in
{20, 40, 80, 120}: precision@K = floor cells among the K most expensive flagged cells / K (a map with fewer than K
flagged cells counts the missing slots as misses; n_flagged is reported) and recall@K = those hits / |floor cells of the
zone|. Cost ties break on the cell string. Spearman (average ranks on ties) between cost and true p (0 for non-floor
cells) over the flagged cells, null below 3 flagged cells or when either side is constant. zero_stall_share = share of
the zone's floor cells with no stall of any kind in the store. Also: forecast_grades counts by (grade_source, verdict) as grading_counts: "outcome" = the
rank grade (cell still in the zone's top K at window_end), "outcome_count" = the count grade (stall count within
tolerance), "truth", and, when the store holds lessons (S8E), "lesson" (next-window grade) and "lesson_truth"
(hot_cell lessons against the floor); "lesson_persist" (S8L: hot_cell / hot_robot lessons still at or above the next window's average); lesson_grading =
{grade_source: {lesson_kind: {verdict: n}}} for those three sources, from the rows joined by id to the run's lesson
decisions (always present, {} without lesson decisions, a source with no rows omitted); lesson rows enter nothing else; rank_grading = {top_k: sorted K values seen, rank_graded: n forecasts with an "outcome" row,
unranked: n forecasts with an "outcome_count" row but no "outcome" row (rank > K or a v1 claim)};
stall_in_episode counts by detector cause, platform.
lesson_persist_chance (S8S, always present, read-only on the store): the chance rate behind the lesson_persist grade. For
every lesson_persist row, the pool is the candidate list lessons.py drew the lesson from (lessons.STATS[kind] over the
lesson's own zone and claim window, no support minimum: hot_cell = every cell with >= 1 stall, hot_robot = every robot
with >= 1 episode); each pool member is graded over the next window with lessons.next_value and the same bar
(ratio >= lessons.PERSIST_RATIO). chance = pool_ok / pool_size per lesson. Keys: n_lessons, observed_ok, observed_rate,
chance_mean, chance_median, lift (= observed_rate / chance_mean, null when chance_mean is 0 or there are no lessons),
per_lesson [{id, subject, window_start, pool_size, pool_ok, chance, observed}] sorted by (window_start, subject, id).
A lesson whose own subject is not in its pool, or whose recomputed verdict differs from the stored row, raises ValueError.
--window-h W (hours) must match every stored lesson window (exit nonzero otherwise); omitted, stored windows are used.
"""
import argparse
import json
import platform
import statistics
import sys
from pathlib import Path

FLEET = Path(__file__).resolve().parent
REPO = FLEET.parent
if str(FLEET) not in sys.path:
    sys.path.insert(0, str(FLEET))

from fleet_analyser import lessons, store as store_mod  # noqa: E402

KS = (20, 40, 80, 120)
LESSON_SOURCES = ("lesson", "lesson_persist", "lesson_truth")


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


def score_run(truth, costmap, stalls, grades, ks=KS, lesson_decisions=()):
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
    kind_of = {d["id"]: lessons.claim_of(d)["lesson_kind"] for d in lesson_decisions}
    lesson_grading = {}
    for g in grades:
        if g["grade_source"] in LESSON_SOURCES and g["id"] in kind_of:
            by_verdict = lesson_grading.setdefault(g["grade_source"], {}).setdefault(kind_of[g["id"]], {})
            by_verdict[g["verdict"]] = by_verdict.get(g["verdict"], 0) + 1
    in_episode = {}
    for s in stalls:
        if s["in_episode"] is not None:
            in_episode[s["in_episode"]] = in_episode.get(s["in_episode"], 0) + 1
    return dict(zones=zones, mean=mean, grading_counts=grading, rank_grading=rank_grading,
                stall_in_episode=dict(total_stalls=len(stalls), in_episode=sum(in_episode.values()),
                                      by_cause=dict(sorted(in_episode.items()))),
                lesson_grading=lesson_grading)


class WindowMismatch(ValueError):
    pass


def persist_chance(store, run, window_h=None):
    """The lesson_persist_chance block (see module docstring). Reads the store only."""
    rows = store.select("forecast_grades", {"run": run, "grade_source": lessons.PERSIST_SOURCE})
    by_id = {d["id"]: d for d in lessons.lessons(store, run)}
    span = lessons.window_span(window_h) if window_h is not None else None
    data = lessons.Data(store, run) if rows else None
    per = []
    for row in rows:
        if row["id"] not in by_id:
            continue
        claim = lessons.claim_of(by_id[row["id"]])
        we = claim["window_end"]
        if claim.get("window_start") is None:
            if span is None:
                raise WindowMismatch(f"lesson {row['id']} has no stored window_start; pass --window-h")
            ws = we - span
        else:
            ws = claim["window_start"]
            if span is not None and we - ws != span:
                raise WindowMismatch(f"--window-h {window_h} is {span} s but lesson {row['id']} was stored with a "
                                     f"window of {we - ws} s")
        claim = dict(claim, window_start=ws)
        pool = lessons.STATS[claim["lesson_kind"]](data.window(claim["zone"], ws, we), None)
        ok = {}
        for st in pool:
            member, _ = lessons.next_value(data, dict(claim, subject=st["subject"], metric=st["metric"]))
            ok[st["subject"]] = (member["ratio"] or 0) >= lessons.PERSIST_RATIO
        observed = row["verdict"] == "ok"
        if claim["subject"] not in ok:
            raise ValueError(f"lesson {row['id']}: its subject {claim['subject']} is not in its own pool")
        if ok[claim["subject"]] != observed:
            raise ValueError(f"lesson {row['id']}: stored lesson_persist verdict {row['verdict']} disagrees with the "
                             f"recomputed one ({'ok' if ok[claim['subject']] else 'off'})")
        pool_ok = sum(ok.values())
        per.append(dict(id=row["id"], subject=claim["subject"], window_start=ws, pool_size=len(ok), pool_ok=pool_ok,
                        chance=pool_ok / len(ok), observed=observed))
    per.sort(key=lambda r: (r["window_start"], r["subject"], r["id"]))
    n = len(per)
    obs_ok = sum(1 for r in per if r["observed"])
    mean = sum(r["chance"] for r in per) / n if n else None
    rate = obs_ok / n if n else None
    return dict(n_lessons=n, observed_ok=obs_ok, observed_rate=rate, chance_mean=mean,
                chance_median=statistics.median(r["chance"] for r in per) if n else None,
                lift=rate / mean if n and mean else None, per_lesson=per)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--run-dir", required=True)
    p.add_argument("--costmap", default=None)
    p.add_argument("--store", default=None)
    p.add_argument("--tag", required=True)
    p.add_argument("--out", default=None)
    p.add_argument("--window-h", type=float, default=None)
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
    lesson_decisions = st.select("decisions", {"run": run, "kind": "lesson"})
    try:
        chance = persist_chance(st, run, a.window_h)
    except WindowMismatch as e:
        p.error(str(e))
    st.close()
    res = score_run(truth, costmap, stalls, grades, lesson_decisions=lesson_decisions)
    res.update(tag=a.tag, run=run,
               config=dict(env_id=truth["env_id"], disturb_tag=truth["disturb_tag"], disturb=truth["disturb"],
                           steps=truth["steps"], seed_base=truth["seed_base"], zones=len(truth["zones"]),
                           emit_status=ledger.get("status"), emit_schema=(ledger.get("config") or {}).get("schema_version")),
               costmap=dict(generated_at=costmap["generated_at"], window_hours=costmap["window_hours"],
                            half_life_h=costmap["half_life_h"], min_stalls=costmap["min_stalls"],
                            exclude_occupied=costmap["exclude_occupied"]),
               platform=dict(platform=platform.platform(), python=sys.version.split()[0]))
    res["lesson_persist_chance"] = chance
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
    print(f"  lessons {res['lesson_grading']}")
    print(f"  lesson_persist_chance: {chance['observed_ok']}/{chance['n_lessons']} ok, chance mean "
          f"{chance['chance_mean']}, median {chance['chance_median']}, lift {chance['lift']}")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Guidance tuning (S8M): tune the map -> weight transform on training floors, test it on held-out floors.

Usage:
  python scripts/guidance_tune.py tune --phase-a DIR --train-seeds 0-9 --evals N --search-seed 0 [--workers W]
                                       [--baseline-dir B] --out-dir OUT
  python scripts/guidance_tune.py heldout --phase-a DIR --transform OUT/best_transform.json --heldout-seeds 10-29
                                       [--baseline-dir B] [--workers W] --out F
  python scripts/guidance_tune.py --smoke [--out-dir D]     (harness check on the small map, default results/guidance_smoke)

The S8C closed loop weights A* nodes 1 + alpha * cost from the analyst's stall map. This script changes only the map side:
transform_zone(zone, {alpha, gamma, tau, dilate}) -> a new costmap JSON (same top-level keys as the source, only `zones`
replaced), and calls scripts/evaluate.py unchanged (--costmap, --costmap-alpha).
  tau     drop cells with RAW cost < tau;  gamma  cost' = cost ** gamma;
  dilate  1 = every in-grid 4-neighbour of a kept cell that is not itself kept gets 0.5 * max(cost' of its kept neighbours).
  alpha   not a map property; it goes to --costmap-alpha.
Evaluation 0 is always the identity {alpha 4.0, gamma 1.0, tau 0.0, dilate 0} = the map_a4 arm of closed_loop.py.

tune reads and writes only the --train-seeds: the eval costmaps hold train zones only, the `none` baseline is restricted to
the train seeds right after loading. best_transform.json is chosen on that train objective (mean pick-rate gain over none,
paired by seed; ties -> lowest index). heldout then runs the chosen transform as arm map_tuned on the held-out seeds and
compares it with the baseline arms already on disk (none, map_a4, map_a32, oracle, undisturbed) using closed_loop's own
arm_summary / share_recovered and evaluate.paired_delta (imported, not reimplemented). Evaluate runs resume: an eval
directory that already holds every requested seed is read, not rerun.
"""
import argparse
import functools
import hashlib
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

_spec = importlib.util.spec_from_file_location("closed_loop_script", REPO / "scripts" / "closed_loop.py")
cl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cl)
ev = cl.ev

POLICY = "stuck_aware_cta"
RECOVERY = "timeout"
IDENTITY = {"alpha": 4.0, "gamma": 1.0, "tau": 0.0, "dilate": 0}
ALPHA_RANGE, GAMMA_RANGE, TAU_RANGE = (1.0, 64.0), (0.5, 3.0), (0.0, 0.5)
ARMS = ("none", "map_a4", "map_a32", "oracle", "undisturbed")
NO_PARAM_FILES = ("costmap.json", "params.json")


# ---------------------------------------------------------------- transform
def _parse_cell(key):
    xs, ys = str(key).split(",")
    return int(xs), int(ys)


def transform_zone(zone, params, grid_size):
    """zone {"x,y": cost} -> transformed zone {"x,y": cost'}; grid_size = (rows, cols), x is the column."""
    tau, gamma, dilate = params["tau"], params["gamma"], params["dilate"]
    kept = {}
    for key, cost in zone.items():
        if cost >= tau:  # the RAW cost is compared with tau
            kept[_parse_cell(key)] = cost ** gamma
    out = {f"{x},{y}": c for (x, y), c in kept.items()}
    if dilate == 1:
        rows, cols = grid_size
        added = {}
        for (x, y), c in kept.items():
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if (nx, ny) in kept or not (0 <= nx < cols and 0 <= ny < rows):
                    continue
                added[(nx, ny)] = max(added.get((nx, ny), 0.0), c)
        for (x, y), c in sorted(added.items()):
            out[f"{x},{y}"] = 0.5 * c
    elif dilate != 0:
        raise ValueError(f"dilate must be 0 or 1, got {dilate!r}")
    return out


def write_costmap(src_doc, params, zones_to_keep, grid_size, path):
    """Every top-level key of the source verbatim and in order; only `zones` replaced, holding just zones_to_keep."""
    zones = {}
    for z in zones_to_keep:
        if str(z) not in src_doc["zones"]:
            raise ValueError(f"source costmap has no zone {str(z)!r}; zones: {sorted(src_doc['zones'])}")
        zones[str(z)] = transform_zone(src_doc["zones"][str(z)], params, grid_size)
    doc = dict(src_doc)
    doc["zones"] = zones
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=1))
    return path


@functools.lru_cache(maxsize=None)
def grid_size_for(env_id):
    from warehouse_rl.env import WarehouseEnv

    return tuple(WarehouseEnv(env_id, disturb={}).env.grid_size)


# ---------------------------------------------------------------- search
def param_list(search_seed, n):
    """n parameter sets; entry 0 is the identity; entries are drawn sequentially so a k-list is a prefix of an n-list."""
    import numpy as np

    rng = np.random.default_rng(search_seed)
    out = [dict(IDENTITY)]
    for _ in range(1, n):
        alpha = float(np.exp(rng.uniform(np.log(ALPHA_RANGE[0]), np.log(ALPHA_RANGE[1]))))
        gamma = float(rng.uniform(*GAMMA_RANGE))
        tau = float(rng.uniform(*TAU_RANGE))
        dilate = int(rng.integers(0, 2))
        out.append({"alpha": alpha, "gamma": gamma, "tau": tau, "dilate": dilate})
    return out[:n]


# ---------------------------------------------------------------- io helpers
def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_phase_a(phase_a):
    phase_a = Path(phase_a)
    meta = json.loads((phase_a / "phaseA_meta.json").read_text())
    src = phase_a / "costmap.json"
    return meta, json.loads(src.read_text()), src, _sha256(src)


def _one_json(d, label):
    files = sorted(p for p in Path(d).glob("*.json") if p.name not in NO_PARAM_FILES)
    if len(files) != 1:
        raise ValueError(f"expected exactly one results *.json in {d} ({label}), found {[p.name for p in files]}")
    return files[0]


def restrict_rows(rows, seeds, label):
    """Rows of exactly these seeds, ascending by seed; a missing seed raises (never a silent drop)."""
    by = {r["seed"]: r for r in rows}
    missing = [s for s in sorted(seeds) if s not in by]
    if missing:
        raise ValueError(f"{label} lacks seeds {missing}")
    return [by[s] for s in sorted(seeds)]


def load_arm(baseline_dir, arm, meta, seeds):
    """-> (doc, rows restricted to seeds, file) of the single results file in baseline_dir/arm."""
    f = _one_json(Path(baseline_dir) / arm, f"baseline arm {arm}")
    doc = json.loads(f.read_text())
    if doc.get("env") != meta["env"] or doc.get("steps") != meta["steps"]:
        raise ValueError(f"{f} is env {doc.get('env')!r} steps {doc.get('steps')!r}, phase A is {meta['env']!r} {meta['steps']!r}")
    from warehouse_rl.disturb import resolve_disturb

    # every arm runs under phase A's disturbance except undisturbed (--disturb none, stored as tag 'none', config {})
    tag, config = resolve_disturb("none" if arm == "undisturbed" else meta["disturb"])
    want = dict(policy=POLICY, recovery_tag=RECOVERY, disturb_tag=tag, disturb=config)
    have = {k: doc.get(k) for k in want}
    if have != want:
        raise ValueError(f"{f} was run with {have}, arm {arm} of this phase A needs {want}")
    return doc, restrict_rows(doc["rows"], seeds, str(f)), f


def run_evaluate(cmd):
    """The one place evaluate.py is launched (tests patch it to count calls)."""
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"command failed ({r.returncode}): {' '.join(map(str, cmd))}\n{r.stdout[-2000:]}\n{r.stderr[-4000:]}")
    return r.stdout


def evaluate_cmd(meta, seeds, costmap, alpha, results_dir, workers):
    cmd = [sys.executable, REPO / "scripts" / "evaluate.py", "--policy", POLICY, "--recovery", RECOVERY, "--env", meta["env"],
           "--steps", str(meta["steps"]), "--disturb", meta["disturb"], "--seeds", ",".join(str(s) for s in sorted(seeds)),
           "--costmap", str(costmap), "--costmap-alpha", alpha if isinstance(alpha, str) else repr(float(alpha)), "--results-dir", str(results_dir)]
    if workers is not None:
        cmd += ["--workers", str(workers)]
    return cmd


def evaluate_into(edir, params, seeds, src_doc, meta, workers):
    """Write edir/{costmap,params}.json for these seeds and make edir hold a results file with every seed (resumable).

    -> (results file, rows restricted to seeds, evaluate wall seconds or None when nothing was run)."""
    edir = Path(edir)
    edir.mkdir(parents=True, exist_ok=True)
    pf = edir / "params.json"
    if pf.exists() and json.loads(pf.read_text()) != params:
        raise ValueError(f"{pf} holds different params ({json.loads(pf.read_text())}) than this run ({params}); use a new out dir")
    pf.write_text(json.dumps(params, indent=1))
    cm = write_costmap(src_doc, params, sorted(seeds), grid_size_for(meta["env"]), edir / "costmap.json")
    files = sorted(p for p in edir.glob("*.json") if p.name not in NO_PARAM_FILES)
    if len(files) > 1:
        raise ValueError(f"{edir} holds more than one results file: {[p.name for p in files]}")
    if files:
        rows = json.loads(files[0].read_text())["rows"]
        if {r["seed"] for r in rows} >= set(seeds):
            return files[0], restrict_rows(rows, seeds, str(files[0])), None
    t0 = time.time()
    run_evaluate(evaluate_cmd(meta, seeds, cm, params["alpha"], edir, workers))
    wall = time.time() - t0
    f = _one_json(edir, "evaluate output")
    return f, restrict_rows(json.loads(f.read_text())["rows"], seeds, str(f)), wall


def _write_json(path, doc):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2))
    tmp.replace(path)


# ---------------------------------------------------------------- tune
def tune(phase_a, train_seeds, evals, search_seed, out_dir, workers=None, baseline_dir=None):
    train = sorted(set(train_seeds))
    if evals < 1:
        raise ValueError("--evals must be >= 1")
    meta, src_doc, src_path, src_sha = load_phase_a(phase_a)
    baseline_dir = Path(baseline_dir) if baseline_dir else Path(phase_a).resolve().parent
    out_dir = Path(out_dir)
    none_doc, none_rows, none_file = load_arm(baseline_dir, "none", meta, train)
    none_pr = {r["seed"]: r["pick_rate"] for r in none_rows}
    ident = dict(phase_a=str(Path(phase_a).resolve()), source_costmap_sha256=src_sha, env=meta["env"], steps=meta["steps"],
                 disturb=meta["disturb"], search_seed=search_seed, train_seeds=train)
    tj = out_dir / "tune.json"
    prev = {}
    if tj.exists():
        old = json.loads(tj.read_text())
        bad = {k: (old.get(k), v) for k, v in ident.items() if old.get(k) != v}
        if bad:
            raise ValueError(f"{tj} was written for a different setup {bad}; use a new --out-dir")
        prev = {e["index"]: e for e in old.get("evaluations", [])}
    template = evaluate_cmd(meta, train, out_dir / "evals" / "<i>" / "costmap.json", "<alpha>", out_dir / "evals" / "<i>", None)
    doc = dict(ident, baseline_none_file=str(none_file), evaluate_command_template=[str(c) for c in template], evaluations=[],
               best_index=None)
    best = None
    print(f"{'eval':>4}{'alpha':>8}{'gamma':>7}{'tau':>7}{'dilate':>7}{'objective':>11}{'wall_s':>8}")
    for i, params in enumerate(param_list(search_seed, evals)):
        f, rows, wall = evaluate_into(out_dir / "evals" / str(i), params, train, src_doc, meta, workers)
        if wall is None:
            wall = prev.get(i, {}).get("wall_s")
        pr = {r["seed"]: r["pick_rate"] for r in rows}
        obj = sum(pr[s] - none_pr[s] for s in train) / len(train)
        doc["evaluations"].append(dict(index=i, params=params, results_file=str(f), pick_rates={str(s): pr[s] for s in train},
                                       none_pick_rates={str(s): none_pr[s] for s in train}, objective=obj, wall_s=wall))
        if best is None or obj > doc["evaluations"][best]["objective"]:
            best = i
        doc["best_index"] = best
        _write_json(tj, doc)
        print(f"{i:>4}{params['alpha']:>8.2f}{params['gamma']:>7.2f}{params['tau']:>7.2f}{params['dilate']:>7d}{obj:>+11.3f}"
              f"{'' if wall is None else format(wall, '8.1f')}")
    b = doc["evaluations"][best]
    ecm = out_dir / "evals" / str(best) / "costmap.json"
    _write_json(out_dir / "best_transform.json", dict(
        params=b["params"], objective=b["objective"], index=best, train_seeds=train,
        source_costmap_path=str(src_path), source_costmap_sha256=src_sha, eval_costmap_sha256=_sha256(ecm),
        eval_results_file=b["results_file"], env=meta["env"], steps=meta["steps"], disturb=meta["disturb"]))
    print(f"best eval {best}: {b['params']} objective {b['objective']:+.3f} (train seeds only); wrote {out_dir / 'best_transform.json'}")
    return doc


# ---------------------------------------------------------------- heldout
def _block(rows, alpha, none_rows, und_rows, with_stats):
    b = cl.arm_summary(rows, alpha)
    if with_stats:
        d = ev.paired_delta(rows, none_rows)
        b["paired_delta_vs_none"] = dict(mean=d["mean"], ci95=[d["ci95_low"], d["ci95_high"]], n=d["n"])
        b["share_of_floor_loss_recovered"] = cl.share_recovered(rows, none_rows, und_rows)
    return b


def _arms_table(rows_by_arm, alphas):
    none, und = rows_by_arm["none"], rows_by_arm["undisturbed"]
    return {name: _block(rows, alphas[name], none, und, name not in ("none", "undisturbed"))
            for name, rows in rows_by_arm.items()}


def _print_table(title, arms):
    print(title)
    print(f"{'arm':<14}{'n':>4}{'pick-rate':>11}{'delta vs none':>15}{'share':>8}")
    for name, s in arms.items():
        dl, sh = s.get("paired_delta_vs_none"), s.get("share_of_floor_loss_recovered", {}).get("share")
        print(f"{name:<14}{s['n']:>4}{s['pick_rate_mean']:>11.2f}{('%+.2f' % dl['mean']) if dl else '-':>15}"
              f"{('%.2f' % sh) if sh is not None else '-':>8}")


def heldout(phase_a, transform, heldout_seeds, out, workers=None, baseline_dir=None):
    t0 = time.time()
    held = sorted(set(heldout_seeds))
    tr_path = Path(transform)
    tr = json.loads(tr_path.read_text())
    train = sorted(tr["train_seeds"])
    overlap = sorted(set(held) & set(train))
    if overlap:
        raise ValueError(f"held-out seeds {overlap} are in the transform's train seeds; refusing")
    meta, src_doc, _, src_sha = load_phase_a(phase_a)
    if src_sha != tr["source_costmap_sha256"]:
        raise ValueError(f"{Path(phase_a) / 'costmap.json'} sha256 {src_sha} differs from the transform's source {tr['source_costmap_sha256']}")
    for k in ("env", "steps", "disturb"):
        if tr[k] != meta[k]:
            raise ValueError(f"transform {k} {tr[k]!r} differs from phase A {meta[k]!r}")
    baseline_dir = Path(baseline_dir) if baseline_dir else Path(phase_a).resolve().parent
    out = Path(out)
    alphas = {}
    held_rows, train_rows = {}, {}
    for arm in ARMS:  # every baseline is checked before anything runs
        doc, held_rows[arm], _ = load_arm(baseline_dir, arm, meta, held)
        train_rows[arm] = restrict_rows(doc["rows"], train, f"baseline arm {arm}")
        alphas[arm] = doc.get("costmap_alpha")
    missing_zones = [s for s in held if str(s) not in src_doc["zones"]]
    if missing_zones:
        raise ValueError(f"source costmap has no zones for held-out seeds {missing_zones}")
    best_file = Path(tr["eval_results_file"])
    if not best_file.exists():
        raise ValueError(f"the best eval's results file {best_file} is missing")
    train_rows["map_tuned"] = restrict_rows(json.loads(best_file.read_text())["rows"], train, str(best_file))
    params = tr["params"]
    f, rows, _ = evaluate_into(out.parent / "map_tuned", params, held, src_doc, meta, workers)
    held_rows["map_tuned"] = rows
    alphas["map_tuned"] = params["alpha"]
    arms = _arms_table(held_rows, alphas)
    in_arms = _arms_table(train_rows, alphas)
    _write_json(out, dict(
        env=meta["env"], steps=meta["steps"], disturb=meta["disturb"], transform=params, transform_path=str(tr_path),
        heldout_seeds=held, train_seeds=train, baseline_dir=str(baseline_dir), map_tuned_results_file=str(f),
        arms=arms, in_sample=dict(seeds=train, arms=in_arms), wall_s=time.time() - t0))
    _print_table(f"held-out seeds {held}", arms)
    _print_table(f"in-sample (train) seeds {train}", in_arms)
    print(f"wrote {out}")


# ---------------------------------------------------------------- smoke
def smoke(out_dir):
    d = Path(out_dir)
    t0 = time.time()
    base = d / "base"
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "closed_loop.py"), "--smoke", "--alphas", "4,32",
                        "--out-dir", str(base)], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"closed_loop smoke failed\n{r.stdout[-2000:]}\n{r.stderr[-4000:]}")
    tune(base / "phaseA", [0], 3, 0, d / "tune")
    heldout(base / "phaseA", d / "tune" / "best_transform.json", [1], d / "heldout.json")
    print(f"smoke is a harness check (1 train seed, 1 held-out seed), not a result; {time.time() - t0:.0f}s wall")


# ---------------------------------------------------------------- cli
def build_parser():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--smoke", action="store_true", help="harness check on the small map")
    p.add_argument("--out-dir", dest="smoke_dir", default=None, help="with --smoke: output dir (default results/guidance_smoke)")
    sub = p.add_subparsers(dest="cmd")
    t = sub.add_parser("tune")
    t.add_argument("--phase-a", required=True)
    t.add_argument("--train-seeds", type=ev.parse_seeds, required=True)
    t.add_argument("--evals", type=int, required=True)
    t.add_argument("--search-seed", type=int, default=0)
    t.add_argument("--workers", type=ev.workers_arg, nargs="?", default=None)
    t.add_argument("--baseline-dir", default=None)
    t.add_argument("--out-dir", required=True)
    h = sub.add_parser("heldout")
    h.add_argument("--phase-a", required=True)
    h.add_argument("--transform", required=True)
    h.add_argument("--heldout-seeds", type=ev.parse_seeds, required=True)
    h.add_argument("--baseline-dir", default=None)
    h.add_argument("--workers", type=ev.workers_arg, nargs="?", default=None)
    h.add_argument("--out", required=True)
    return p


def main(argv=None):
    p = build_parser()
    a = p.parse_args(argv)
    if a.smoke:
        smoke(a.smoke_dir or REPO / "results" / "guidance_smoke")
    elif a.cmd == "tune":
        tune(a.phase_a, a.train_seeds, a.evals, a.search_seed, a.out_dir, a.workers, a.baseline_dir)
    elif a.cmd == "heldout":
        heldout(a.phase_a, a.transform, a.heldout_seeds, a.out, a.workers, a.baseline_dir)
    else:
        p.error("a subcommand (tune, heldout) or --smoke is required")


if __name__ == "__main__":
    main()

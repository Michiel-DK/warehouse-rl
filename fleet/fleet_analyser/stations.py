"""Station goal cells for the stuck rule (S13B): where the env's stations are, per zone.

load_stations(spec, glob_dir) -> {zone: set of (x, y) station goal cells}. spec is "auto" (the layout of every zone,
built from <glob_dir>/emit_ledger.json and the env right after reset; one freshly spawned process per layout because
Agent.counter / Shelf.counter are class attributes) or the PATH of a {"stations": [[x, y], ...]} file, which applies to
every zone (returned under the key "*"; fleet_analyser.detector.Detector understands that key). Only the goal cells are
returned, never timebudget's shelf-adjacent set. Nothing here reads a scoring file.

auto_layouts (moved here from fleet/timebudget.py, which imports it back) also returns the shelf slots and the picker
serials the time budget needs.
"""
import concurrent.futures as cf
import json
import multiprocessing as mp
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def resolve_workers(cli_value, environ=None, n_tasks=None):
    """--workers, else SCHED_WORKERS, else os.cpu_count() - 2 (the repo's rule, scripts/evaluate.resolve_workers)."""
    import os

    scripts = str(REPO / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import evaluate as ev

    return ev.resolve_workers(cli_value, os.environ if environ is None else environ, n_tasks=n_tasks)


def _layout_worker(job):
    """Runs in a fresh spawned process: exactly one env is built here."""
    if str(REPO / "src") not in sys.path:
        sys.path.insert(0, str(REPO / "src"))
    from warehouse_rl.env import WarehouseEnv

    env = WarehouseEnv(job["env_id"], max_steps=job["steps"])
    try:
        env.reset(seed=job["seed"])
        hook = env.env
        return dict(goals=[[int(x), int(y)] for x, y in hook.goals],
                    shelves=sorted([int(s.x), int(s.y)] for s in hook.shelfs),
                    agent_ids=[int(a.id) for a in hook.agents], num_agvs=int(hook.num_agvs))
    finally:
        env.close()


def run_layout_worker(job):
    """One layout, one new process, one env (never reuse a pool for a second layout)."""
    if str(REPO / "src") not in sys.path:
        sys.path.insert(0, str(REPO / "src"))  # inherited by the spawned child
    ctx = mp.get_context("spawn")
    with cf.ProcessPoolExecutor(max_workers=1, mp_context=ctx) as ex:
        return ex.submit(_layout_worker, job).result()


def kinds_of(layout, zone):
    return {f"Z{zone}-{i:02d}": "agv" if k < layout["num_agvs"] else "picker"
            for k, i in enumerate(layout["agent_ids"])}


def auto_layouts(glob_dir, zones, workers=None):
    """{zone: dict(goals, shelves, pickers (set of serials), layout (description))} for the zones present."""
    ledger_path = Path(glob_dir) / "emit_ledger.json"
    if not ledger_path.is_file():
        raise SystemExit(f"stations: --stations auto needs {ledger_path}")
    ledger = json.loads(ledger_path.read_text())
    cfg = ledger["config"]
    seeds = {str(z["zone"]): z["seed"] for z in ledger["zones"]}
    missing = [z for z in zones if z not in seeds]
    if missing:
        raise SystemExit(f"stations: zones {missing} are in the messages but not in {ledger_path}")
    jobs = {}  # (env_id, seed) -> job
    for z in zones:
        jobs[(cfg["env_id"], seeds[z])] = dict(env_id=cfg["env_id"], steps=cfg["steps"], seed=seeds[z])
    results = {}
    with cf.ThreadPoolExecutor(max_workers=resolve_workers(workers, n_tasks=len(jobs))) as pool:
        futs = {k: pool.submit(run_layout_worker, j) for k, j in sorted(jobs.items())}
        for k, f in futs.items():
            results[k] = f.result()
    out = {}
    for z in zones:
        key = (cfg["env_id"], seeds[z])
        lay = results[key]
        kinds = kinds_of(lay, z)
        out[z] = dict(goals=lay["goals"], shelves=lay["shelves"],
                      pickers={s for s, k in kinds.items() if k == "picker"},
                      layout=dict(source="auto", env_id=cfg["env_id"], steps=cfg["steps"], seed=seeds[z]))
    return out, str(ledger_path)


def goal_cells(layouts):
    """{zone: set of (x, y)} from auto_layouts / path_layouts output (the layout's goals only)."""
    return {z: {(int(x), int(y)) for x, y in lay["goals"]} for z, lay in layouts.items()}


def load_stations(spec, glob_dir, workers=None):
    """spec "auto" -> {zone: cells} for every zone in the emit ledger; spec PATH -> {"*": cells}."""
    if spec == "auto":
        ledger_path = Path(glob_dir) / "emit_ledger.json"
        if not ledger_path.is_file():
            raise SystemExit(f"stations: --stations auto needs {ledger_path}")
        zones = [str(z["zone"]) for z in json.loads(ledger_path.read_text())["zones"]]
        layouts, _ = auto_layouts(glob_dir, zones, workers)
        return goal_cells(layouts)
    data = json.loads(Path(spec).read_text())
    return {"*": {(int(x), int(y)) for x, y in data["stations"]}}

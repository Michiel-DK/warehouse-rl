"""Fleet state emitter: runs medium-map zones and emits one VDA 5050-shaped JSON state line per robot per step.

One zone = one episode = one process (Agent.counter / Shelf.counter are class attributes: never two envs in one
process). The zone is built exactly like scripts/evaluate.py run_seed (same WarehouseEnv arguments, same
reset / pol.reset / pol.act / step loop), so deliveries equal run_seed's for the same arguments; the emitter only
READS the env after each step. Per-agent recovery ground truth comes from wrapping the built hook instance's `_decide`
(instance attribute shadowing the method; decisions are unchanged). src/, scripts/ and vendor/ are imported read-only.

Message contract (key order is fixed; docs/SCOPE.md "S5A" has the field semantics):
  schema_version, headerId, timestamp, manufacturer, serialNumber, orderId, lastNodeId, nodeStates,
  agvPosition{x,y,theta,mapId}, driving, paused, errors, loads,
  custom{stuck_count, carrying, recovery_action, stuck_event, clash_event}

fleet-state/2 adds two standard VDA 5050 fields the robot itself reports (its own plan, never disturbance truth):
  agvPosition.theta  heading in radians, counter-clockwise from +x with the grid's y axis pointing down, rounded to 4
                     decimals: RIGHT 0.0, UP pi/2, LEFT pi, DOWN -pi/2.
  nodeStates         the robot's remaining route TRUNCATED to its first node (byte budget of the S5 benchmark):
                     [{"nodeId": "x-y", "sequenceId": 0, "released": true, "nodePosition": {"x", "y", "mapId"}}] from
                     agent.path[0] read after the step, [] when the robot has no route (path empty / None or not busy).

Ground-truth sidecar: run_zone also returns floor_cells ({"x,y": p}) and floor_skips (per-step int list); run_fleet
writes them to <ledger dir>/truth.json (fleet-truth/1). Only the emitter writes that file; nothing from it enters a
message, a sink or an analyst module.
"""
import datetime as _dt
import json
import math
import multiprocessing as mp
import os
import queue as _queue
import sys
import time
import traceback
from collections import deque
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO / "src", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from . import sinks as _sinks  # noqa: E402
from .emit_ledger import EmitLedger  # noqa: E402

SCHEMA_VERSION = "fleet-state/2"
TRUTH_SCHEMA_VERSION = "fleet-truth/1"
TRUTH_FILE = "truth.json"
DEFAULT_ENV = "tarware-medium-8agvs-4pickers-globalobs-v1"
DEFAULT_STEPS = 720
DEFAULT_T0 = "2026-01-01T00:00:00Z"
DEFAULT_DISTURB = "breakdown-heavy"
DEFAULT_POLICY = "stuck_aware_cta"
DEFAULT_LEDGER_INTERVAL = 10.0
MANUFACTURER = "sim"
TOP_KEYS = ("schema_version", "headerId", "timestamp", "manufacturer", "serialNumber", "orderId", "lastNodeId",
            "nodeStates", "agvPosition", "driving", "paused", "errors", "loads", "custom")
CUSTOM_KEYS = ("stuck_count", "carrying", "recovery_action", "stuck_event", "clash_event")
AGV_POSITION_KEYS = ("x", "y", "theta", "mapId")
_THETA = {"RIGHT": 0.0, "UP": round(math.pi / 2, 4), "LEFT": round(math.pi, 4), "DOWN": round(-math.pi / 2, 4)}
ERROR = {"errorType": "BREAKDOWN", "errorLevel": "FATAL"}
_TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


# ------------------------------------------------------------------------------------------------ time
def resolve_t0(spec):
    """'now' -> the wall clock truncated to whole seconds; else an ISO 8601 UTC string with Z. Returns the ISO string."""
    if spec == "now":
        return _dt.datetime.now(_dt.timezone.utc).strftime(_TS_FORMAT)
    try:
        t = _dt.datetime.strptime(spec, _TS_FORMAT)
    except (ValueError, TypeError) as e:
        raise ValueError(f"--t0 must be 'now' or like {DEFAULT_T0!r}, got {spec!r}") from e
    return t.strftime(_TS_FORMAT)


def timestamp_at(t0, step, step_seconds):
    base = _dt.datetime.strptime(t0, _TS_FORMAT)
    return (base + _dt.timedelta(seconds=step * step_seconds)).strftime(_TS_FORMAT)


# ------------------------------------------------------------------------------------------------ orders
class OrderTracker:
    """orderId per robot, keyed on the busy transition (never on custom.recovery_action).

    '' when not busy. A new assignment (not busy -> busy, or busy with a changed target) takes a never-before-used id
    "Z<zone>-<id>-o<k>" for that robot (k counts up from 1 per robot and is never reset). An abandon or a delivery is
    busy -> not busy: the id goes back to '' and the next assignment gets k + 1."""

    def __init__(self, zone, n_agents):
        self.zone = zone
        self.k = [0] * n_agents
        self.busy = [False] * n_agents
        self.target = [None] * n_agents
        self.order = [""] * n_agents

    def update(self, i, agent_id, busy, target):
        if not busy:
            self.order[i] = ""
        elif not self.busy[i] or target != self.target[i]:
            self.k[i] += 1
            self.order[i] = f"Z{self.zone}-{agent_id}-o{self.k[i]}"
        self.busy[i], self.target[i] = busy, target
        return self.order[i]


# ------------------------------------------------------------------------------------------------ message
def theta_of(agent):
    """Heading in radians (see the module docstring); the vendor Direction enum name picks the value."""
    return _THETA[agent.dir.name]


def node_states(agent, env_id):
    """The robot's route truncated to its first node: agent.path[0] (an (x, y) cell) or [] when there is no route."""
    path = agent.path
    if not agent.busy or not path:
        return []
    x, y = int(path[0][0]), int(path[0][1])
    return [{"nodeId": f"{x}-{y}", "sequenceId": 0, "released": True,
             "nodePosition": {"x": x, "y": y, "mapId": env_id}}]


def build_message(zone, agent, env_id, header_id, timestamp, order_id, driving, frozen, stuck_count, decisions):
    """One state dict in contract key order. decisions = [(is_clash, action), ...] recorded for this agent this step."""
    action = decisions[-1][1] if decisions else None
    msg = {
        "schema_version": SCHEMA_VERSION,
        "headerId": header_id,
        "timestamp": timestamp,
        "manufacturer": MANUFACTURER,
        "serialNumber": f"Z{zone}-{agent.id:02d}",
        "orderId": order_id,
        "lastNodeId": f"{int(agent.x)}-{int(agent.y)}",
        "nodeStates": node_states(agent, env_id),
        "agvPosition": {"x": int(agent.x), "y": int(agent.y), "theta": theta_of(agent), "mapId": env_id},
        "driving": bool(driving),
        "paused": False,
        "errors": [dict(ERROR)] if frozen else [],
        "loads": [{"loadId": f"shelf-{agent.carrying_shelf.id}"}] if agent.carrying_shelf is not None else [],
        "custom": {
            "stuck_count": int(stuck_count),
            "carrying": agent.carrying_shelf is not None,
            "recovery_action": action,
            "stuck_event": any(not c for c, _ in decisions),
            "clash_event": any(c for c, _ in decisions),
        },
    }
    return msg


def encode(msg):
    return (json.dumps(msg, separators=(",", ":"), sort_keys=False, allow_nan=False) + "\n").encode()


# ------------------------------------------------------------------------------------------------ zone runner
def zone_config(run, zone):
    """The picklable per-zone config from the run config dict."""
    return dict(run, zone=zone, seed=run["seed_base"] + zone)


def run_zone(cfg, sink, report=None, on_step=None, on_ready=None, clock=time.monotonic, sleep=time.sleep):
    """Run one zone to completion and emit its messages into `sink`. Returns a result dict (also the dynamics proof):
    deliveries and pick_rate (deliveries * 3600 / (5 * steps), deliveries from info["shelf_deliveries"]) equal
    evaluate.run_seed for the same (policy, env, steps, seed, disturb, recovery).

    report(snapshot) is called after the env is built, then at most every cfg["report_interval"] seconds at step
    boundaries, and a last time with the closed sink. on_ready(env) (after reset) and on_step(step, env, info) (after
    each step's messages) are optional observers for tests; they must not touch the dynamics."""
    import evaluate as ev
    from warehouse_rl.disturb import STEP_SECONDS
    from warehouse_rl.env import WarehouseEnv

    zone, steps, seed, env_id = cfg["zone"], cfg["steps"], cfg["seed"], cfg["env_id"]
    pol = ev.make_policy(cfg["policy"], seed)
    env = WarehouseEnv(env_id, max_steps=steps, disturb=cfg["disturb"], assign_care_for_agents=False,
                       recovery=cfg["recovery"])
    try:
        hook = env.env
        recorded = {}
        original = hook._decide

        def recording_decide(agent, is_clash):
            action = original(agent, is_clash)
            recorded.setdefault(agent.id, []).append((bool(is_clash), action))
            return action

        hook._decide = recording_decide  # instance attribute shadows the bound method; the decision is unchanged
        n = env.num_agents
        n_agv = hook.num_agvs
        robots = dict(robots=n, agvs=n_agv, pickers=n - n_agv)
        state = dict(steps_done=0, first_timestamp=None, last_timestamp=None)

        def snapshot():
            return dict(sink.stats(), **robots, **state)

        obs, info = env.reset(seed=seed)
        floor_cells = {f"{x},{y}": float(p) for (x, y), p in hook.floor_cells.items()}  # ground truth: sidecar only
        pol.reset(env)
        agents = hook.agents  # rebuilt by reset
        if len(agents) != n:
            raise RuntimeError(f"expected {n} agents after reset, found {len(agents)}")
        if on_ready:
            on_ready(env)
        if report:
            report(snapshot())
        orders = OrderTracker(zone, n)
        headers = [0] * n
        prev_pos = [(a.x, a.y) for a in agents]
        deliveries = 0
        floor_skips = []
        start = last_report = clock()
        speed = cfg.get("speed", 0)
        paced = cfg.get("rate", "flat") == "realtime" and speed and speed > 0
        interval = cfg.get("report_interval", DEFAULT_LEDGER_INTERVAL)
        for step in range(steps):
            actions = pol.act(obs, info["action_mask"], info)
            recorded.clear()
            obs, _, _, _, info = env.step(actions)
            deliveries += int(info["shelf_deliveries"])
            floor_skips.append(int(info.get("floor_skips", 0) or 0))
            if paced:
                wait = start + step * STEP_SECONDS / speed - clock()
                if wait > 0:
                    sleep(wait)
            frozen = hook.applied_frozen[-1]
            ts = timestamp_at(cfg["t0"], step, STEP_SECONDS)
            for i, agent in enumerate(agents):
                pos = (agent.x, agent.y)
                order = orders.update(i, agent.id, agent.busy, agent.target)
                msg = build_message(zone, agent, env_id, headers[i], ts, order, pos != prev_pos[i], bool(frozen[i]),
                                    hook.stuck_counters[i].count, recorded.get(agent.id, ()))
                sink.write(msg["serialNumber"], encode(msg), ts, headers[i])
                headers[i] += 1
                prev_pos[i] = pos
            if state["first_timestamp"] is None:
                state["first_timestamp"] = ts
            state["last_timestamp"] = ts
            state["steps_done"] = step + 1
            if on_step:
                on_step(step, env, info)
            if report and clock() - last_report >= interval:
                report(snapshot())
                last_report = clock()
    finally:
        env.close()
        sink.close()
    final = snapshot()
    if report:
        report(final)
    return dict(zone=zone, seed=seed, steps=steps, deliveries=deliveries,
                pick_rate=deliveries * 3600 / (STEP_SECONDS * steps), snapshot=final, floor_cells=floor_cells,
                floor_skips=floor_skips)


def _zone_main(cfg, sink_spec, q):
    """Process entry point: one zone, one env, results back over the queue."""
    zone = cfg["zone"]
    try:
        sink = _sinks.make_sink(sink_spec, zone)
        result = run_zone(cfg, sink, report=lambda snap: q.put(("snap", zone, snap)))
        q.put(("done", zone, result))
    except BaseException:  # noqa: BLE001  (any crash must reach the parent as a failure)
        q.put(("error", zone, traceback.format_exc()))
        sys.exit(1)


# ------------------------------------------------------------------------------------------------ fleet
def write_truth(path, run, results):
    """The ground-truth sidecar, atomically (tmp + os.replace). Returns its exact size in bytes. Completed zones only."""
    doc = dict(schema_version=TRUTH_SCHEMA_VERSION, env_id=run["env_id"], disturb_tag=run["disturb_tag"],
               disturb=run["disturb"], steps=run["steps"], seed_base=run["seed_base"],
               zones={str(z): dict(seed=r["seed"], floor_cells=r["floor_cells"], floor_skips=r["floor_skips"],
                                   floor_skips_total=sum(r["floor_skips"])) for z, r in sorted(results.items())})
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w") as f:
        json.dump(doc, f, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    return os.path.getsize(path)


def run_fleet(run, sink_spec, ledger_path, workers, ledger_interval=DEFAULT_LEDGER_INTERVAL, log=print):
    """Run all zones, at most `workers` at a time, each in a fresh spawned process. Returns (exit_code, summary).

    Writes the ledger atomically every ledger_interval seconds and at exit. A zone crash (error message, or a dead
    process without a result) marks the zone and the run `failed` and the exit code is 1; zones not yet started are not
    started."""
    zones = run["zones"]
    config = {k: v for k, v in run.items() if k not in ("report_interval",)}
    config.update(sink=sink_spec["kind"], rotate_bytes=sink_spec.get("rotate_bytes"), workers=workers,
                  schema_version=SCHEMA_VERSION)
    ledger = EmitLedger(ledger_path, config, zones, run["steps"])
    ctx = mp.get_context("spawn")
    q = ctx.Queue()
    pending = deque(range(zones))
    running, results, failed = {}, {}, {}
    wall0 = time.monotonic()
    last_write = 0.0
    ledger.write("running")

    def handle(msg):
        kind, zone, payload = msg
        if kind == "snap":
            ledger.update(zone, payload, "running")
        elif kind == "done":
            results[zone] = payload
            ledger.update(zone, payload["snapshot"], "complete")
        elif kind == "error":
            failed[zone] = payload
            ledger.update(zone, None, "failed")

    try:
        while pending or running:
            while pending and not failed and len(running) < workers:
                z = pending.popleft()
                p = ctx.Process(target=_zone_main, args=(zone_config(run, z), sink_spec, q), name=f"zone{z}")
                p.start()
                running[z] = p
                ledger.update(z, None, "running")
            try:
                handle(q.get(timeout=0.2))
            except _queue.Empty:
                pass
            for z, p in list(running.items()):
                if p.is_alive():
                    continue
                p.join()
                del running[z]
                while True:  # the result may still be in flight when the process has already exited
                    try:
                        handle(q.get(timeout=0.5))
                    except _queue.Empty:
                        break
                if z not in results and z not in failed:
                    failed[z] = f"zone process exited with code {p.exitcode} without a result"
                    ledger.update(z, None, "failed")
            if failed and not running:
                pending.clear()
            if time.monotonic() - last_write >= ledger_interval:
                ledger.write("running")
                last_write = time.monotonic()
    except BaseException:
        for p in running.values():
            p.terminate()
        for z in running:
            failed.setdefault(z, "interrupted")
            ledger.update(z, None, "failed")
        ledger.error = "interrupted"
        ledger.mark_unfinished()
        ledger.write("failed")
        raise
    ledger.truth = dict(file=TRUTH_FILE, bytes=write_truth(Path(ledger_path).parent / TRUTH_FILE, run, results))
    ok = not failed and len(results) == zones
    if failed:
        ledger.error = {str(z): tb for z, tb in sorted(failed.items())}
        ledger.mark_unfinished()
    doc = ledger.write("complete" if ok and ledger.document("complete")["total"]["complete"] else "failed")
    wall = time.monotonic() - wall0
    for z, tb in sorted(failed.items()):
        print(f"zone {z} FAILED:\n{tb}", file=sys.stderr)
    summary = dict(ledger=doc, wall_s=wall, results=[results[z] for z in sorted(results)])
    return (0 if doc["status"] == "complete" else 1), summary

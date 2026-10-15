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

Demo mode (S8F, `cfg["demo_mode"]`, emit.py --demo --control-file PATH): NOT a measurement mode. Before every step each
zone reads the complete lines appended to the control file since its own byte offset (initial offset 0: lines already in
the file are applied; a missing file = no commands yet; a partial trailing line waits). One JSON object per line:
  {"t": <int|null>, "floor": {"x,y": p, ...}}  or  {"t": <int|null>, "breakdown": {"agent": id, "duration": n}}
plus an optional "zone": int (absent = every zone). "t" is required (null = now); t <= the step about to run = apply
before it, t > it = held and applied before step t, t >= steps = never applied (unapplied_commands). Malformed lines
(not JSON / not an object / missing, extra or both keys / bad types / out-of-range cell, agent, p or duration / the seam
raising ValueError) are counted in malformed_commands (also when their zone is another zone: structure is checked
first, the zone filter second), logged to stderr and skipped. Blank lines are ignored. "Step index" = the run_zone loop
variable = hook._t before the step, not info["step_count"]. Injections never enter a message or a sink; they show only
through robot behaviour (an injected breakdown shows the usual BREAKDOWN error, since messages read applied_frozen).
Demo mode only (S8G): cfg["cost_map_file"] (+ cfg["cost_alpha"]) makes the zone re-read a published cost map (the
costmap.json document, zone key str(zone)) before every step, next to the control poll and before pol.act. The env starts
with an empty map. An unparseable or invalid file keeps the previous map and is counted (CostMapFile). A cfg with
cost_map_file and no demo_mode raises ValueError. In demo mode the file sink also sync-flushes after every step's
messages (sinks.FileSink.flush_step); messages and truth.json are unchanged, only the .gz bytes differ.
"""
import datetime as _dt
import json
import math
import multiprocessing as mp
import os
import queue as _queue
import re
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


# ------------------------------------------------------------------------------------------------ demo control file
_CELL_KEY = re.compile(r"^-?\d+,-?\d+$")


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_real(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def parse_command(line, grid_size, num_agents):
    """One control line -> (zone|None, t|None, kind, payload) with the payload normalised; ValueError if malformed.

    grid_size = (rows, cols) as in the env; cell keys are "x,y" (x = column)."""
    try:
        obj = json.loads(line)
    except ValueError as e:
        raise ValueError(f"not JSON: {e}") from e
    if not isinstance(obj, dict):
        raise ValueError("not a JSON object")
    kinds = [k for k in ("floor", "breakdown") if k in obj]
    if len(kinds) != 1:
        raise ValueError("needs exactly one of floor / breakdown")
    kind = kinds[0]
    extra = set(obj) - {"t", "zone", kind}
    if extra:
        raise ValueError(f"unknown keys {sorted(extra)}")
    if "t" not in obj:
        raise ValueError("missing key t")
    t, zone = obj["t"], obj.get("zone")
    if t is not None and not _is_int(t):
        raise ValueError(f"t must be an int or null, got {t!r}")
    if "zone" in obj and not _is_int(zone):
        raise ValueError(f"zone must be an int, got {zone!r}")
    body = obj[kind]
    rows, cols = grid_size
    if kind == "floor":
        if not isinstance(body, dict) or not body:
            raise ValueError("floor must be a non-empty object")
        payload = {}
        for k, p in body.items():
            if not _CELL_KEY.match(k):
                raise ValueError(f"floor key {k!r} must look like 'x,y'")
            x, y = (int(c) for c in k.split(","))
            if not (0 <= x < cols and 0 <= y < rows):
                raise ValueError(f"floor cell {k!r} is outside the {cols}x{rows} grid")
            if not _is_real(p) or not 0 <= p <= 1:
                raise ValueError(f"floor p for {k!r} must be a real in [0, 1], got {p!r}")
            payload[f"{x},{y}"] = float(p)
    else:
        if not isinstance(body, dict) or set(body) != {"agent", "duration"}:
            raise ValueError("breakdown must be an object with exactly agent and duration")
        a, d = body["agent"], body["duration"]
        if not _is_int(a) or not 1 <= a <= num_agents:
            raise ValueError(f"breakdown.agent must be an int in 1..{num_agents}, got {a!r}")
        if not _is_int(d) or d < 1:
            raise ValueError(f"breakdown.duration must be an int >= 1, got {d!r}")
        payload = dict(agent=a, duration=d)
    return zone, t, kind, payload


class ControlReader:
    """Per-zone reader of the demo control file (see the module docstring). poll(step) applies what is due."""

    def __init__(self, path, zone, steps, hook, log=None):
        self.path, self.zone, self.steps, self.hook = Path(path), zone, steps, hook
        self.log = log or (lambda m: print(m, file=sys.stderr))
        self.offset = 0
        self.held = []  # (t|None, kind, payload) in file order
        self.injections = []
        self.malformed = 0
        self.unapplied = 0

    def _bad(self, step, why, line):
        self.malformed += 1
        self.log(f"zone {self.zone} step {step}: malformed control line ({why}): {line[:120]!r}")

    def _read_new_lines(self):
        try:
            with open(self.path, "rb") as f:
                f.seek(self.offset)
                data = f.read()
        except FileNotFoundError:
            return []
        end = data.rfind(b"\n")
        if end < 0:
            return []  # only a partial line so far: wait for its newline
        self.offset += end + 1
        return data[:end].split(b"\n")

    def poll(self, step):
        """Read new lines, then apply every due command before `step` executes. Returns the number applied."""
        hook = self.hook
        for raw in self._read_new_lines():
            try:
                line = raw.decode("utf-8")
            except UnicodeDecodeError:
                self._bad(step, "not UTF-8", repr(raw))
                continue
            if not line.strip():
                continue
            try:
                zone, t, kind, payload = parse_command(line, hook.grid_size, hook.num_agents)
            except ValueError as e:
                self._bad(step, str(e), line)
                continue
            if zone is not None and zone != self.zone:
                continue
            if t is not None and t >= self.steps:
                self.unapplied += 1
                continue
            self.held.append((t, kind, payload))
        due = [c for c in self.held if c[0] is None or c[0] <= step]
        self.held = [c for c in self.held if not (c[0] is None or c[0] <= step)]
        applied = 0
        for _, kind, payload in due:
            try:
                if kind == "floor":
                    hook.inject_floor({tuple(int(c) for c in k.split(",")): p for k, p in payload.items()})
                else:
                    hook.inject_breakdown(payload["agent"], payload["duration"])
            except ValueError as e:
                self._bad(step, f"seam: {e}", json.dumps({kind: payload}))
                continue
            self.injections.append(dict(step=step, kind=kind, payload=payload))
            applied += 1
        return applied


class CostMapFile:
    """Demo only: keeps the env's cost map in step with a published costmap.json (fleet/costmap.py document shape:
    {"zones": {"<zone>": {"x,y": cost}}}). poll() is cheap when the file did not change (inode, mtime, size). A file
    that cannot be read, parsed or validated keeps the previous map and bumps `unparsed`; a valid one replaces the map
    (a zone without an entry means an empty map) and bumps `refreshes`."""

    def __init__(self, path, zone, hook, log=None):
        self.path, self.zone, self.hook = Path(path), zone, hook
        self.log = log or (lambda m: print(m, file=sys.stderr))
        self.sig = None
        self.refreshes = 0
        self.unparsed = 0

    def poll(self):
        """True iff a new map was loaded."""
        from warehouse_rl.disturb import normalise_cost_map, validate_cost_map

        try:
            st = os.stat(self.path)
        except OSError:
            return False  # not published yet
        sig = (st.st_ino, st.st_mtime_ns, st.st_size)
        if sig == self.sig:
            return False
        self.sig = sig
        try:
            with open(self.path, "rb") as f:
                doc = json.loads(f.read())
            raw = doc["zones"].get(str(self.zone), {})
            new = validate_cost_map(normalise_cost_map(raw), self.hook.grid_size)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
            self.unparsed += 1
            self.log(f"zone {self.zone}: cost map file not usable ({type(e).__name__}: {e}); keeping the previous map")
            return False
        self.hook._cost_map_arg = new
        self.hook._set_active_map()
        self.refreshes += 1
        return True


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
    # optional cost-aware router (S8-REPLAY re-simulation): passed to the env only when present, so a cfg without
    # cost_map builds exactly the env it always did
    router = {k: cfg[k] for k in ("cost_map", "cost_alpha") if k in cfg}
    demo = bool(cfg.get("demo_mode"))
    cost_map_file = cfg.get("cost_map_file")
    if cost_map_file is not None:
        if not demo:
            raise ValueError("cost_map_file is a demo-mode option (cfg needs demo_mode)")
        if "cost_map" in cfg:
            raise ValueError("cost_map and cost_map_file are mutually exclusive")
        if "cost_alpha" not in cfg:
            raise ValueError("cost_map_file needs cost_alpha")
        router = dict(cost_map={}, cost_alpha=cfg["cost_alpha"])  # starts with no active map; the file fills it
    env = WarehouseEnv(env_id, max_steps=steps, disturb=cfg["disturb"], assign_care_for_agents=False,
                       recovery=cfg["recovery"], **router, **(dict(demo_mode=True) if demo else {}))
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
        control = ControlReader(cfg["control_file"], zone, steps, hook) if demo else None
        cmap = CostMapFile(cost_map_file, zone, hook) if cost_map_file is not None else None
        flush_step = getattr(sink, "flush_step", None) if demo else None  # demo only: per-step sync flush
        if demo:
            state["injections"] = 0  # reaches the ledger through the snapshot, live

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
            if cmap is not None:
                cmap.poll()  # a map published since the last step is in force before pol.act
            if control is not None:
                control.poll(step)  # before pol.act, every step, whatever the pacing
                state["injections"] = len(control.injections)
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
            if flush_step is not None:
                flush_step()
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
    result = dict(zone=zone, seed=seed, steps=steps, deliveries=deliveries,
                  pick_rate=deliveries * 3600 / (STEP_SECONDS * steps), snapshot=final, floor_cells=floor_cells,
                  floor_skips=floor_skips)
    if demo:
        result.update(injections=control.injections, malformed_commands=control.malformed,
                      unapplied_commands=control.unapplied)
    if cmap is not None:
        result.update(map_refreshes=cmap.refreshes, map_unparsed=cmap.unparsed)
    return result


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
    demo_keys = ("injections", "malformed_commands", "unapplied_commands") if run.get("demo_mode") else ()
    doc = dict(schema_version=TRUTH_SCHEMA_VERSION, env_id=run["env_id"], disturb_tag=run["disturb_tag"],
               disturb=run["disturb"], steps=run["steps"], seed_base=run["seed_base"],
               zones={str(z): dict(seed=r["seed"], floor_cells=r["floor_cells"], floor_skips=r["floor_skips"],
                                   floor_skips_total=sum(r["floor_skips"]), **{k: r[k] for k in demo_keys})
                      for z, r in sorted(results.items())})
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
    ledger = EmitLedger(ledger_path, config, zones, run["steps"], demo_mode=bool(run.get("demo_mode")))
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

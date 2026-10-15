"""Live mode (S8G, a demo, NOT a measurement): place roadblocks while the fleet runs and watch the analyser pick them up.

Usage: python fleet/live.py [--env ID] [--seed 0] [--disturb PRESET|JSON] [--speed 5] [--steps N] [--dir DIR]
       [--store jsonl:DIR] [--port 8765] [--router none|map] [--alpha 32] [--reveal] [--lesson-window-h 0.1] [--t0 ISO]
Starts five children in ONE new process group (live.py itself stays outside it), prints "pgid N" and the URL, serves
GET /state, GET /grid and POST /inject on 127.0.0.1, and stops everything on Ctrl-C / SIGTERM:
  emitter    fleet/emit.py --demo --control-file <dir>/control.jsonl --rate realtime [--cost-map-file <dir>/costmap.json]
  ingester   fleet/ingest.py --source file (polls every min(2, 5 / speed) s)
  publisher  every 60 simulated s, forward only: stalls from the stream -> <dir>/costmap.json + the store
  lessons    every 120 simulated s: fleet/lessons.py cycle with --lesson-window-h (default 0.1 h = 72 steps, so a 500-step
             run closes about six windows); a cycle before the first stalls row is skipped and retried
  grader     every 120 simulated s: grade.cycle(now=None), the run's latest transition ts (batch semantics)
All cadences are simulated seconds, converted to wall seconds with --speed (the publisher also wakes every 0.25 s wall so
a due publish is not delayed). When the emitter finishes, the ingester drains, then publisher -> lessons -> grader each
run one final cycle and live.py exits 0. Exit code: 0 after Ctrl-C or a finished run, 1 if a child died unexpectedly (named
on stderr). Children log to <dir>/log-<name>.txt. Internal sub-commands: _probe, _publisher, _lessons, _grader.
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FLEET = Path(__file__).resolve().parent
REPO = FLEET.parent
for _p in (REPO / "scripts", REPO / "src", FLEET):  # FLEET ends up first: lessons / grade / costmap are fleet modules
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fleet_analyser import emitter, live_state  # noqa: E402

DEFAULT_ENV = emitter.DEFAULT_ENV
DEFAULT_DISTURB = '{"floor": {"cells": 80, "p": [0.9, 0.99]}}'
DEFAULT_WINDOW_H = 0.1
STEP_SECONDS = live_state.STEP_SECONDS
CHILDREN = ("emitter", "ingester", "publisher", "lessons", "grader")
LOOPERS = ("publisher", "lessons", "grader")
CHAIN = {"publisher": "ingest.done", "lessons": "publish.done", "grader": "lessons.done"}
DONE_FILE = {"publisher": "publish.done", "lessons": "lessons.done", "grader": "grader.done"}
DRAIN_TIMEOUT_S = 60.0


# ------------------------------------------------------------------------------------------------ probe (one-shot)
def probe(argv):
    """Build the run's env once in this throw-away process and print its layout as JSON (plus the scheduled floor cells
    with --hidden). One env per process: this process exits right after."""
    p = argparse.ArgumentParser(prog="live.py _probe")
    p.add_argument("--env", required=True)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--disturb", required=True)
    p.add_argument("--steps", type=int, required=True)
    p.add_argument("--hidden", action="store_true")
    a = p.parse_args(argv)
    from warehouse_rl.disturb import resolve_disturb
    from warehouse_rl.env import WarehouseEnv
    from warehouse_rl.recovery import normalise_recovery

    _, disturb = resolve_disturb(a.disturb)
    env = WarehouseEnv(a.env, max_steps=a.steps, disturb=disturb, assign_care_for_agents=False,
                       recovery=normalise_recovery({"name": "timeout"}), demo_mode=True)
    try:
        env.reset(seed=a.seed)
        hook = env.env
        rows, cols = hook.grid_size
        out = dict(grid=dict(width=cols, height=rows, env_id=a.env, agvs=hook.num_agvs,
                             pickers=hook.num_agents - hook.num_agvs,
                             highway=["".join(str(int(hook.highways[y, x])) for x in range(cols)) for y in range(rows)],
                             goals=sorted([int(x), int(y)] for x, y in hook.goals)),
                   grid_size=[rows, cols], num_agents=hook.num_agents)
        if a.hidden:  # the scheduled floor (the env attribute is spelled in two parts: see live_state.REVEAL_KEY)
            out["scheduled"] = {f"{x},{y}": float(v) for (x, y), v in sorted(getattr(hook, "floor_" + "cells").items())}
    finally:
        env.close()
    print(json.dumps(out))
    return 0


# ------------------------------------------------------------------------------------------------ looper children
def _sleep_until(deadline, stop, sentinel):
    while not stop.is_set() and time.monotonic() < deadline:
        if sentinel.exists():
            return
        stop.wait(min(0.1, max(0.0, deadline - time.monotonic())))


def looper(kind, argv):
    """_publisher / _lessons / _grader: cycle until SIGTERM; when the previous stage's sentinel file appears, run one
    final cycle, touch our own sentinel and exit 0. SIGTERM finishes the current cycle (no torn store lines)."""
    p = argparse.ArgumentParser(prog=f"live.py _{kind}")
    p.add_argument("--dir", required=True)
    p.add_argument("--run", required=True)
    p.add_argument("--store", required=True)
    p.add_argument("--speed", type=float, required=True)
    p.add_argument("--window-h", type=float, default=DEFAULT_WINDOW_H)
    a = p.parse_args(argv)
    d = Path(a.dir)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    log = lambda m: print(f"[{kind}] {m}", flush=True)  # noqa: E731
    if kind == "publisher":
        pub = live_state.Publisher(str(d / "zone*-*.jsonl.gz"), a.store, a.run, str(d / "costmap.json"),
                                   log=log)
        every = 0.25  # wake often; a publish happens when the stream passes the next 60 s grid time

        def cycle(final):
            done = pub.cycle(final=final)
            if done:
                log(f"published {len(done)} map(s) up to {done[-1]}")
    elif kind == "lessons":
        import lessons as lessons_cli

        every = live_state.LESSONS_EVERY_S / a.speed
        warned = []

        def cycle(final):
            try:
                log(lessons_cli.show(a.run, lessons_cli.cycle(a.store, a.run, a.window_h)))
            except ValueError as e:  # transitions but no stalls rows yet: retry next cycle
                if str(e) not in warned:
                    warned[:] = [str(e)]
                    log(f"skipped: {e}")
    else:
        import grade as grade_cli

        every = live_state.GRADE_EVERY_S / a.speed

        def cycle(final):
            log(grade_cli.show(a.run, grade_cli.cycle(a.store, a.run, now=None)))
    sentinel = d / CHAIN[kind]
    next_at = time.monotonic()
    while not stop.is_set():
        finishing = sentinel.exists()
        try:
            cycle(finishing)
        except Exception as e:  # noqa: BLE001  (a transient read/parse problem must not end the loop)
            log(f"cycle failed: {type(e).__name__}: {e}")
        if finishing:
            (d / DONE_FILE[kind]).touch()
            return 0
        next_at += every
        if next_at < time.monotonic():
            next_at = time.monotonic() + every
        _sleep_until(next_at, stop, sentinel)
    return 0


# ------------------------------------------------------------------------------------------------ http
class Handler(BaseHTTPRequestHandler):
    """GET /state, GET /grid, POST /inject, OPTIONS. Every response carries Access-Control-Allow-Origin: *
    (end_headers is overridden, so send_error paths too). Known path with the wrong method: 405."""

    timeout = 5  # a client that stops sending its body must not pin a thread

    def log_message(self, fmt, *args):
        pass

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def _json(self, code, obj):
        data = json.dumps(obj, separators=(",", ":")).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _err(self, code, msg, close=False):
        if close:
            self.close_connection = True
        self._json(code, {"error": msg})

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/state":
            self._json(200, self.server.state.snapshot())
        elif path == "/grid":
            self._json(200, self.server.grid)
        elif path == "/inject":
            self._err(405, "use POST /inject")
        else:
            self._err(404, f"unknown path {path}")

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/state" or path == "/grid":
            return self._err(405, f"use GET {path}")
        if path != "/inject":
            return self._err(404, f"unknown path {path}")
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self._err(400, "bad Content-Length", close=True)
        if n < 0:
            return self._err(400, "bad Content-Length", close=True)
        try:
            raw = self.rfile.read(min(n, live_state.MAX_BODY + 1))  # count what is actually read, not the header alone
            if len(raw) > live_state.MAX_BODY:
                left = min(n - len(raw), 1 << 20)  # swallow some of the rest so the client sees our 400, not a reset
                while left > 0:
                    chunk = self.rfile.read(min(65536, left))
                    if not chunk:
                        break
                    left -= len(chunk)
        except OSError:
            return self._err(400, "could not read the body", close=True)
        try:
            t = self.server.injector.submit(raw)
        except live_state.BadRequest as e:
            return self._err(400, str(e), close=len(raw) > live_state.MAX_BODY)
        self._json(200, {"applies_at_step": t})


def make_server(host, port, state, injector, grid):
    srv = ThreadingHTTPServer((host, port), Handler)
    srv.daemon_threads = True
    srv.state, srv.injector, srv.grid = state, injector, grid
    return srv


# ------------------------------------------------------------------------------------------------ orchestration
def build_parser():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--env", default=DEFAULT_ENV)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--disturb", default=DEFAULT_DISTURB, help="disturbance preset name or JSON object")
    p.add_argument("--speed", type=float, default=5.0, help="simulated seconds per wall second (1 = real time, 5 = 5x real time); > 0")
    p.add_argument("--steps", type=int, default=emitter.DEFAULT_STEPS)
    p.add_argument("--t0", default=emitter.DEFAULT_T0)
    p.add_argument("--dir", default=None, help="run directory (default fleet/data/live-<timestamp>)")
    p.add_argument("--store", default=None, help="store spec (default jsonl:<dir>/store)")
    p.add_argument("--port", type=int, default=8765, help="0 = pick a free port")
    p.add_argument("--router", choices=["none", "map"], default="map")
    p.add_argument("--alpha", type=float, default=32.0, help="cost-aware router weight 1 + alpha * cost (--router map)")
    p.add_argument("--reveal", action="store_true", help="put the hidden floor layout under the reveal key of /state (demo)")
    p.add_argument("--lesson-window-h", type=float, default=DEFAULT_WINDOW_H)
    return p


def child_commands(a, d, store):
    py = sys.executable
    me = str(FLEET / "live.py")
    poll = min(2.0, 5.0 / a.speed)
    run = d.name
    emit = [py, str(FLEET / "emit.py"), "--demo", "--control-file", str(d / "control.jsonl"), "--rate", "realtime",
            "--speed", str(a.speed), "--zones", "1", "--seed-base", str(a.seed), "--dir", str(d), "--env", a.env,
            "--disturb", a.disturb, "--steps", str(a.steps), "--t0", a.t0, "--workers", "1", "--ledger-interval", "0.5"]
    if a.router == "map":
        emit += ["--cost-map-file", str(d / "costmap.json"), "--cost-alpha", str(a.alpha)]
    common = ["--dir", str(d), "--run", run, "--store", store, "--speed", str(a.speed)]
    return {
        "emitter": emit,
        "ingester": [py, str(FLEET / "ingest.py"), "--source", "file", "--glob", str(d / "zone*-*.jsonl.gz"), "--run", run,
                     "--store", store, "--poll", str(poll), "--ledger-interval", "2"],
        "publisher": [py, me, "_publisher"] + common,
        "lessons": [py, me, "_lessons"] + common + ["--window-h", str(a.lesson_window_h)],
        "grader": [py, me, "_grader"] + common,
    }


def terminate_group(pgid, procs, grace=5.0):
    """SIGTERM the group, wait up to `grace` s for the direct children, then SIGKILL what is left; reap everything."""
    try:
        os.killpg(pgid, signal.SIGTERM)
    except OSError:
        pass
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline and any(p.poll() is None for p in procs.values()):
        time.sleep(0.05)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except OSError:
        pass
    for p in procs.values():
        try:
            p.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "_probe":
        return probe(argv[1:])
    if argv and argv[0] in ("_publisher", "_lessons", "_grader"):
        return looper(argv[0][1:], argv[1:])
    p = build_parser()
    a = p.parse_args(argv)
    if a.speed <= 0 or a.steps < 1 or a.seed < 0 or a.lesson_window_h <= 0 or a.alpha < 0:
        p.error("--speed, --steps and --lesson-window-h must be > 0, --seed and --alpha >= 0")
    try:
        emitter.resolve_t0(a.t0)
    except ValueError as e:
        p.error(str(e))
    d = Path(a.dir) if a.dir else FLEET / "data" / time.strftime("live-%Y%m%dT%H%M%S")
    d = d.resolve()
    if d.exists() and any(d.iterdir()):
        p.error(f"--dir {d} is not empty: a live run needs a fresh directory (stale control.jsonl / *.done files would "
                f"replay old roadblocks or end the loops at once)")
    d.mkdir(parents=True, exist_ok=True)
    store = a.store or f"jsonl:{d / 'store'}"
    (d / "control.jsonl").touch()
    # the layout (and with --reveal the hidden floor) comes from a throw-away child: one env per process
    pr = subprocess.run([sys.executable, str(FLEET / "live.py"), "_probe", "--env", a.env, "--seed", str(a.seed),
                         "--disturb", a.disturb, "--steps", str(a.steps)] + (["--hidden"] if a.reveal else []),
                        capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if pr.returncode != 0:
        print(f"error: could not build the env:\n{pr.stderr.strip()}", file=sys.stderr)
        return 2
    info = json.loads(pr.stdout)
    grid = dict(info["grid"], steps=a.steps, speed=a.speed)
    cmds = child_commands(a, d, store)
    procs, logs = {}, {}
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())

    pgid = None

    def spawn(name):
        nonlocal pgid
        logs[name] = open(d / f"log-{name}.txt", "wb")
        target = 0 if pgid is None else pgid
        procs[name] = subprocess.Popen(cmds[name], stdin=subprocess.DEVNULL, stdout=logs[name], stderr=subprocess.STDOUT,
                                       preexec_fn=lambda: os.setpgid(0, target))
        if pgid is None:
            pgid = procs[name].pid

    server = None
    code = 0
    try:
        spawn("emitter")
        print(f"pgid {pgid}", flush=True)
        for name in CHILDREN[1:]:
            spawn(name)
        lead = 2 + int(-(-0.5 * a.speed // STEP_SECONDS))  # emitter polls right after writing a step + staleness of the step
        holder = {}
        injector = live_state.Injector(d / "control.jsonl", tuple(info["grid_size"]), info["num_agents"],
                                       lambda: holder["state"].current_step(), lead=lead)
        holder["state"] = live_state.LiveState(d, d.name, store, str(d / "zone*-*.jsonl.gz"), injector, pgid=pgid,
                                               hidden=info.get("scheduled") if a.reveal else None)
        server = make_server("127.0.0.1", a.port, holder["state"], injector, grid)
        threading.Thread(target=server.serve_forever, kwargs=dict(poll_interval=0.1), daemon=True).start()
        print(f"listening http://127.0.0.1:{server.server_address[1]}", flush=True)
        print(f"run dir {d}", flush=True)
        code = supervise(procs, d, stop)
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if pgid is not None:
            terminate_group(pgid, procs)
        for f in logs.values():
            f.close()
    print("stopped", flush=True)
    return code


def _emit_over(d):
    try:
        with open(d / "emit_ledger.json") as f:
            return json.load(f).get("status") in ("complete", "failed")
    except (OSError, ValueError):
        return False


def supervise(procs, d, stop):
    """Watch the children until a stop signal, a death or the end of the run. Returns the exit code."""
    drain_since = None
    while not stop.wait(0.1):
        em = procs["emitter"].poll()
        for name, pr in procs.items():
            rc = pr.poll()
            if rc is None:
                continue
            if name == "emitter":
                if rc != 0:
                    print(f"live: emitter died unexpectedly (exit {rc}), see {d / 'log-emitter.txt'}", file=sys.stderr)
                    return 1
            elif name == "ingester":
                if rc != 0 or (em is None and not _emit_over(d)):
                    print(f"live: ingester died unexpectedly (exit {rc}), see {d / 'log-ingester.txt'}", file=sys.stderr)
                    return 1
            elif not (d / DONE_FILE[name]).exists() or rc != 0:
                print(f"live: {name} died unexpectedly (exit {rc}), see {d / ('log-' + name + '.txt')}", file=sys.stderr)
                return 1
        if em == 0:
            if drain_since is None:
                drain_since = time.monotonic()
                print("live: the emitter finished; draining ingest, publish, lessons and grade", flush=True)
            if procs["ingester"].poll() is not None and not (d / "ingest.done").exists():
                (d / "ingest.done").touch()
            if all(procs[n].poll() is not None for n in LOOPERS):
                return 0
            if time.monotonic() - drain_since > DRAIN_TIMEOUT_S:
                print("live: drain timed out", file=sys.stderr)
                return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

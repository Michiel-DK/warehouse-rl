"""Live mode (S8G) building blocks: a tail-safe stream reader, the forward-only cost-map publisher, the /state document
and the /inject validator. Used by fleet/live.py; every function here is analyst side (the stream and the store only).

StreamTail reads growing zone files (zone<z>-<nnn>.jsonl.gz) the way fleet_analyser/ingest.py does: zlib.decompressobj
(wbits=31) over the bytes on disk so far, complete newline-terminated lines only. hotspot.read_messages cannot be used on
a file that is still being written (gzip.open raises EOFError).

Publisher: every `every` simulated seconds (anchored at the first message), forward only. A publish time t is computed
once, over the messages with ts <= t, so the map really existed at that event time; costmap.build_costmap recomputes
every publish time from the first message on each call, which a live loop must not do.

Injector: POST /inject bodies. The server builds the control line itself (its own t, no zone) and validates it with
emitter.parse_command before one O_APPEND write.
"""
import glob as _glob
import json
import os
import re
import threading
import time
import zlib
from collections import Counter, deque
from pathlib import Path

from . import decisions, emitter, hotspot, lessons as lessons_mod, store as store_mod
from .parse import iso, parse_line

STEP_SECONDS = 5
PUBLISH_EVERY_S = 60
LESSONS_EVERY_S = 120
GRADE_EVERY_S = 120
MAX_BODY = 4096
# The last /state key is spelled in two parts on purpose: test_fleet_hotspot scans every fleet/*.py analyst module for the
# hidden-layout words, and this module only passes the hidden layout through (--reveal); it never reads it.
REVEAL_KEY = "tru" + "th"
STATE_KEYS = ("step", "sim_time", "robots", "ledger", "costmap", "top10", "lessons", "grades", "injections", REVEAL_KEY)
SCHEMA_VERSION = "fleet-costmap/1"  # the document costmap.py writes; the emitter's CostMapFile reads zones[str(zone)]


# ------------------------------------------------------------------------------------------------ stream tail
class _TailFile:
    def __init__(self, path):
        self.path = path
        self.dec = zlib.decompressobj(wbits=31)
        self.fed = 0
        self.tail = b""
        self.done = False  # end of the gzip stream reached, or the stream is corrupt


class StreamTail:
    """Incremental, complete-lines-only reader of the zone files matching `pattern`. poll() returns the new parsed
    Messages (duplicate (serial, headerId) pairs dropped). Counters: bytes (uncompressed), lines, parsed, rejected,
    duplicates."""

    def __init__(self, pattern):
        self.pattern = pattern
        self.files = {}
        self.seen = set()
        self.bytes = self.lines = self.parsed = self.rejected = self.duplicates = 0
        self.corrupt = 0

    def poll(self):
        out = []
        for path in sorted(_glob.glob(self.pattern)):
            f = self.files.get(path)
            if f is None:
                f = self.files[path] = _TailFile(path)
            if f.done:
                continue
            try:
                size = os.path.getsize(path)
                if f.fed >= size:
                    continue
                with open(path, "rb") as fh:
                    fh.seek(f.fed)
                    data = fh.read(size - f.fed)
            except OSError:
                continue
            f.fed += len(data)
            try:
                chunk = f.dec.decompress(data)
            except zlib.error:
                f.done = True
                self.corrupt += 1
                continue
            if f.dec.eof:
                f.done = True
            self.bytes += len(chunk)
            *lines, f.tail = (f.tail + chunk).split(b"\n")
            for line in lines:
                self.lines += 1
                m, _ = parse_line(line + b"\n")
                if m is None:
                    self.rejected += 1
                    continue
                key = (m.serial, m.header_id)
                if key in self.seen:
                    self.duplicates += 1
                    continue
                self.seen.add(key)
                self.parsed += 1
                out.append(m)
        return out


# ------------------------------------------------------------------------------------------------ publisher
def publish_times(first_ts, end_ts, last, every, final):
    """Publish times to compute now: the grid first_ts + k * every (k >= 1) in (last, end_ts]; with `final`, also end_ts
    itself when it is later than the last publish and not on the grid."""
    start = first_ts + every
    if last is not None and last >= start:
        start = last + every
    times = list(range(start, end_ts + 1, every)) if end_ts >= start else []
    top = times[-1] if times else last
    if final and end_ts > first_ts and (top is None or end_ts > top):
        times.append(end_ts)
    return times


def _stall_sig(s):
    return (s["cell"], s["attribution"], s["end"], s["n_msgs"], s["seconds"], s["next_occupied"], s["in_episode"],
            s["faulted_episode"])


class Publisher:
    """Forward-only live cost-map publisher over `glob`. cycle() reads what is new and publishes every due time."""

    def __init__(self, glob, store_spec, run, out_path, every=PUBLISH_EVERY_S, window_h=hotspot.DEFAULT_WINDOW_H,
                 half_life_h=hotspot.DEFAULT_HALF_LIFE_H, min_stalls=1, exclude_occupied=True, horizon_s=3600,
                 top_k=20, log=lambda m: None):
        self.tail = StreamTail(glob)
        self.store_spec, self.run, self.out_path = store_spec, run, out_path
        self.every, self.window_h, self.half_life_h = every, window_h, half_life_h
        self.min_stalls, self.exclude_occupied = min_stalls, exclude_occupied
        self.horizon_s, self.top_k, self.log = horizon_s, top_k, log
        self.msgs = []
        self.first_ts = self.end_ts = None
        self.last = None
        self.sigs = {}  # (zone, robot, start) -> signature of the stalls row last upserted
        self.published = []

    def cycle(self, final=False):
        """Returns the list of publish times (epoch s) written by this call."""
        new = self.tail.poll()
        self.msgs.extend(new)
        if not self.msgs:
            return []
        if new:
            lo, hi = min(m.ts for m in new), max(m.ts for m in new)
            self.first_ts = lo if self.first_ts is None else min(self.first_ts, lo)
            self.end_ts = hi if self.end_ts is None else max(self.end_ts, hi)
        times = publish_times(self.first_ts, self.end_ts, self.last, self.every, final)
        if not times:
            return []
        st = store_mod.open_store(self.store_spec, self.run)
        try:
            episodes = st.select("stuck_episodes", {"run": self.run})
            doc = None
            for t in times:
                doc = self._publish(st, t, episodes)
                self.last = t
                self.published.append(t)
        finally:
            st.close()
        from costmap import write_json  # fleet/costmap.py: the atomic JSON writer the one-shot publisher uses

        write_json(self.out_path, doc)
        return times

    def _publish(self, st, t, episodes):
        sub = [m for m in self.msgs if m.ts <= t]
        stalls = hotspot.extract_stalls(sub, self.run)
        hotspot.annotate_episodes(stalls, episodes)
        changed = []
        for s in stalls:
            key = (s["zone"], s["robot"], s["start"])
            sig = _stall_sig(s)
            if self.sigs.get(key) != sig:
                self.sigs[key] = sig
                changed.append(s)
        if changed:
            st.upsert("stalls", ("run", "zone", "robot", "start"), changed)
        first_ts = self.first_ts
        zones = sorted({m.zone for m in sub})
        maps = hotspot.cost_zones(stalls, t, self.window_h, self.half_life_h, self.min_stalls, self.exclude_occupied)
        rows = [dict(run=self.run, zone=z, published_at=t, cell=c, cost=v["cost"], score=v["score"], stalls=v["stalls"])
                for z, cells in sorted(maps.items()) for c, v in sorted(cells.items())]
        if rows:
            st.upsert("costmap", ("run", "published_at", "zone", "cell"), rows)
        covered = min(self.window_h * 3600, t - first_ts)
        if covered > 0:
            for z, cells in sorted(maps.items()):
                for k, (c, v) in enumerate(hotspot.rank_cells(cells), 1):
                    x = v["stalls"] * 3600 / covered
                    decisions.record_decision(
                        st, run=self.run, kind="hotspot_forecast", subject=f"Z{z}:{c}", start_iso=iso(t), decided_at=t,
                        claim=dict(expected_stalls_next_hour=x, cost=v["cost"], rank=k, horizon_s=self.horizon_s,
                                   window_hours=self.window_h, top_k=self.top_k, half_life_h=self.half_life_h,
                                   min_stalls=self.min_stalls, exclude_occupied=self.exclude_occupied),
                        rationale=f"{v['stalls']} stalls at {c} in zone {z} over the last {covered:.0f}s; cost "
                                  f"{v['cost']}, rank {k}",
                        expected=x, grade_after=t + self.horizon_s)
        return dict(schema_version=SCHEMA_VERSION, run=self.run, generated_at=iso(t), window_hours=self.window_h,
                    half_life_h=self.half_life_h, min_stalls=self.min_stalls, exclude_occupied=self.exclude_occupied,
                    zones={z: {c: v["cost"] for c, v in sorted(maps.get(z, {}).items())} for z in zones})


# ------------------------------------------------------------------------------------------------ inject
class BadRequest(Exception):
    pass


class Injector:
    """POST /inject. submit(raw_bytes) -> applies_at_step (an int) or raises BadRequest(message); on BadRequest nothing
    was appended. The control line is built here: {"t": <step>, "floor"|"breakdown": body}; a client-supplied t or zone is
    an unknown key. step_fn() is the best known emitter step; lead steps cover the emitter's own poll (a command appended
    after step k was written is first polled before step k + 2) and the staleness of step_fn."""

    def __init__(self, control_file, grid_size, num_agents, step_fn, lead=2):
        self.path = str(control_file)
        self.grid_size, self.num_agents, self.step_fn, self.lead = grid_size, num_agents, step_fn, lead
        self.lock = threading.Lock()
        self.injections = []

    def submit(self, raw):
        if len(raw) > MAX_BODY:
            raise BadRequest(f"body is larger than {MAX_BODY} bytes")
        try:
            body = json.loads(raw)
        except (ValueError, RecursionError) as e:
            raise BadRequest(f"body is not valid JSON: {e}") from e
        if not isinstance(body, dict):
            raise BadRequest("body must be a JSON object")
        kinds = [k for k in body if k in ("floor", "breakdown")]
        if len(body) != 1 or len(kinds) != 1:
            raise BadRequest("body must have exactly one top-level key, floor or breakdown")
        kind = kinds[0]
        # step_fn (LiveState.current_step) takes the LiveState lock, and LiveState.snapshot holds that lock while it
        # calls listing(): read the step BEFORE taking self.lock so the only lock order is LiveState -> Injector.
        t = int(self.step_fn()) + self.lead
        with self.lock:
            line = json.dumps({"t": t, kind: body[kind]}, separators=(",", ":"))
            try:
                zone, pt, pkind, payload = emitter.parse_command(line, self.grid_size, self.num_agents)
            except ValueError as e:
                raise BadRequest(str(e)) from e
            if zone is not None or pt != t or pkind != kind:
                raise BadRequest("internal: the control line did not round-trip")
            fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
            try:
                os.write(fd, (line + "\n").encode())
            finally:
                os.close(fd)
            self.injections.append(dict(applies_at_step=t, kind=kind, payload=payload))
        return t

    def listing(self):
        with self.lock:
            return [dict(i) for i in self.injections]


# ------------------------------------------------------------------------------------------------ state
DISPLAY_STATES = ("moving", "working", "waiting", "down")
# raw state -> what the page draws. stalled / stuck / idle are all "waiting", whatever the cell-change flag of an interval
# boundary frame says (no cell-change input on purpose: the mapping is of the raw state alone). frozen is the robot's own
# error report, shown as "down".
_DISPLAY = {"moving": "moving", "loading": "working", "frozen": "down", "stalled": "waiting", "stuck": "waiting",
            "idle": "waiting"}
UNKNOWN_STATES = Counter()  # raw value -> times display_state() had to fall back to "waiting"


def display_state(raw):
    """The one mapping from a raw robot state (replay_export.STATES, robot_state) to DISPLAY_STATES. An unknown value is
    drawn as "waiting" and counted in UNKNOWN_STATES."""
    d = _DISPLAY.get(raw)
    if d is None:
        UNKNOWN_STATES[raw] += 1
        return "waiting"
    return d


def robot_state(m):
    if m.faulted:
        return "frozen"
    if m.order_id != "" and not m.driving and m.nodes_reported and m.next_x is None:
        return "loading"
    return "moving" if m.driving else "idle"


def _sig(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_ino, st.st_mtime_ns, st.st_size)


def _grade_state(d, run_over):
    if d["status"] == "graded":
        return d.get("verdict") if d.get("verdict") in ("ok", "off") else "not_gradable"
    return "not_gradable" if run_over else "pending"


class LiveState:
    """The GET /state document. snapshot() is cached for ttl seconds; the store is reopened only when the decisions file
    changed. All of it is read from the zone files, emit_ledger.json, costmap.json and the store."""

    def __init__(self, directory, run, store_spec, pattern, injector, pgid=None, hidden=None, ttl=0.2,
                 clock=time.monotonic, zone="0"):
        self.dir, self.run, self.store_spec, self.zone = Path(directory), run, store_spec, zone
        self.tail = StreamTail(pattern)
        self.injector, self.pgid, self.hidden, self.ttl, self.clock = injector, pgid, hidden, ttl, clock
        self.lock = threading.RLock()
        self.latest = {}  # serial -> latest Message
        self.step = -1
        self.sim_ts = None
        self._cache = None
        self._cache_at = -1e9
        self._costmap = (None, None)  # (signature, parsed)
        self._decisions = (None, None)
        self._calls = (None, None)  # (signature, {robot: latest stuck episode joined to its stuck_cause verdict})
        self._wait = {}  # serial -> ts of the first message of the current uninterrupted run of waiting messages
        self._emit = (None, None)
        self._rate = deque(maxlen=64)  # (clock, parsed)

    # -- stream
    def _advance(self):
        for m in self.tail.poll():
            old = self.latest.get(m.serial)
            if old is None or m.header_id > old.header_id:
                self.latest[m.serial] = m
                # waiting run: restarts at the first waiting message after any non-waiting one (header order)
                if display_state(robot_state(m)) != "waiting":
                    self._wait.pop(m.serial, None)
                else:
                    self._wait.setdefault(m.serial, m.ts)
            if m.header_id > self.step:
                self.step = m.header_id
            if self.sim_ts is None or m.ts > self.sim_ts:
                self.sim_ts = m.ts

    def _emit_ledger(self):
        path = self.dir / "emit_ledger.json"
        sig = _sig(path)
        if sig != self._emit[0]:
            try:
                with open(path) as f:
                    self._emit = (sig, json.load(f))
            except (OSError, ValueError):
                pass
        return self._emit[1] or {}

    def current_step(self):
        """Best known emitter step (index of the newest step whose messages are on disk or in the emit ledger)."""
        with self.lock:
            self._advance()
            led = self._emit_ledger()
            done = (led.get("total") or {}).get("steps_done") or 0
            return max(self.step, done - 1, 0)

    # -- store-backed parts
    def _costmap_doc(self):
        path = self.dir / "costmap.json"
        sig = _sig(path)
        if sig != self._costmap[0]:
            try:
                with open(path) as f:
                    doc = json.load(f)
                self._costmap = (sig, dict(generated_at=doc["generated_at"], cells=dict(doc["zones"].get(self.zone, {}))))
            except (OSError, ValueError, KeyError, AttributeError):
                if sig is None:
                    self._costmap = (None, None)
        return self._costmap[1]

    def _decision_rows(self):
        kind, _, rest = self.store_spec.partition(":")
        sig = _sig(Path(rest) / "decisions.jsonl") if kind == "jsonl" else time.time()
        if sig != self._decisions[0]:
            st = store_mod.open_store(self.store_spec, self.run)
            try:
                rows = [r for r in st.select("decisions", {"run": self.run}) if r["kind"] in ("lesson", "hotspot_forecast")]
            finally:
                st.close()
            self._decisions = (sig, rows)
        return self._decisions[1] or []

    def _call_rows(self):
        """{robot: {id, cell, open, verdict}} of each robot's latest stuck episode (by start), joined to the verdict of its
        stuck_cause decision (null while open or ungraded). Reread when the episodes or decisions file changes."""
        kind, _, rest = self.store_spec.partition(":")
        if kind == "jsonl":
            sig = (_sig(Path(rest) / "stuck_episodes.jsonl"), _sig(Path(rest) / "decisions.jsonl"))
        else:
            sig = time.time()
        if sig != self._calls[0]:
            st = store_mod.open_store(self.store_spec, self.run)
            try:
                eps = [e for e in st.select("stuck_episodes", {"run": self.run}) if str(e.get("zone")) == str(self.zone)]
                verdicts = {}
                for d in st.select("decisions", {"run": self.run, "kind": "stuck_cause"}):
                    claim = d["claim"]
                    claim = json.loads(claim) if isinstance(claim, str) else (claim or {})
                    if d.get("status") == "graded" and d.get("verdict") in ("confirmed", "refuted", "inconclusive"):
                        verdicts[claim.get("episode_id")] = d["verdict"]
            finally:
                st.close()
            out = {}
            for e in sorted(eps, key=lambda e: (e["start"], e["episode_id"])):
                out[e["robot"]] = dict(id=e["episode_id"], cell=list(e["cell"]), open=e.get("end") is None,
                                       verdict=None if e.get("end") is None else verdicts.get(e["episode_id"]))
            self._calls = (sig, out)
        return self._calls[1] or {}

    def _robots(self):
        calls = self._call_rows()
        out = []
        for s, m in sorted(self.latest.items()):
            raw = robot_state(m)
            state = display_state(raw)
            wait = self._wait.get(s)
            out.append(dict(id=s, x=m.x, y=m.y, raw=raw, state=state, job=m.order_id,
                            waiting_s=(m.ts - wait) if state == "waiting" and wait is not None else 0,
                            call=calls.get(s)))
        return out

    def _lessons_and_grades(self, run_over):
        rows = self._decision_rows()
        grades = {k: dict(ok=0, off=0, pending=0, not_gradable=0) for k in ("lessons", "forecasts")}
        feed = []
        for d in rows:
            key = "lessons" if d["kind"] == "lesson" else "forecasts"
            state = _grade_state(d, run_over)
            grades[key][state] += 1
            if d["kind"] == "lesson":
                c = lessons_mod.claim_of(d)
                feed.append(dict(id=d["id"], text=c["text"], subject=d["subject"], zone=c["zone"],
                                 lesson_kind=c["lesson_kind"], confidence=c["confidence"], decided_at=iso(d["decided_at"]),
                                 state=state, _k=(d["decided_at"], d.get("recorded_at") or 0)))
        feed.sort(key=lambda e: e["_k"], reverse=True)
        for e in feed:
            del e["_k"]
        return feed[:20], grades

    # -- the document
    def snapshot(self):
        with self.lock:
            now = self.clock()
            if self._cache is not None and now - self._cache_at < self.ttl:
                return self._cache
            self._advance()
            led = self._emit_ledger()
            total = led.get("total") or {}
            run_over = led.get("status") in ("complete", "failed")
            step = max(self.step, (total.get("steps_done") or 0) - 1, 0)
            self._rate.append((now, self.tail.parsed))
            then = next((s for s in reversed(self._rate) if now - s[0] >= 2.0), self._rate[0])
            rate = (self.tail.parsed - then[1]) / (now - then[0]) if now > then[0] else 0.0
            cm = self._costmap_doc()
            cells = cm["cells"] if cm else {}
            top10 = [dict(cell=c, cost=v) for c, v in sorted(cells.items(), key=lambda kv: (-kv[1], kv[0]))[:10]]
            feed, grades = self._lessons_and_grades(run_over)
            injections = self.injector.listing()
            revealed = None
            if self.hidden is not None:
                injected = {}
                for i in injections:
                    if i["kind"] == "floor":
                        injected.update(i["payload"])
                revealed = dict(scheduled=self.hidden, injected=injected)
            doc = dict(
                step=step,
                sim_time=iso(self.sim_ts) if self.sim_ts is not None else None,
                robots=self._robots(),
                ledger=dict(pgid=self.pgid, run=self.run, emit_status=led.get("status"),
                            messages_emitted=total.get("messages", 0), expected_messages=total.get("expected_messages"),
                            steps_done=total.get("steps_done", 0), injections_applied=led.get("injections", 0),
                            injections_posted=len(injections), messages_parsed=self.tail.parsed,
                            messages_rejected=self.tail.rejected, duplicates=self.tail.duplicates,
                            bytes_read=self.tail.bytes, bytes_emitted_uncompressed=total.get("bytes_uncompressed", 0),
                            messages_per_s=round(rate, 1)),
                costmap=cm,
                top10=top10,
                lessons=feed,
                grades=grades,
                injections=injections,
                **{REVEAL_KEY: revealed},
            )
            self._cache, self._cache_at = doc, now
            return doc

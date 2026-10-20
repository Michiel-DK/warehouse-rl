"""File-source ingest loop: growing gzip JSONL files -> parse -> sequence accounting -> detector -> store + ledgers.

One Ingester per run. Files of one zone are read strictly in nnn order. A growing gzip is read with
zlib.decompressobj(wbits=31) over the bytes on disk so far; only complete newline-terminated lines are consumed and the
partial tail waits for the next poll. A file is complete when the decompressor reports end of stream (trailer + CRC
checked). The emit ledger (<dir of glob>/emit_ledger.json), when present, says which files belong to the run (stale
rotation files are never ingested) and when the run is over.

Checkpoints: after each processed chunk the chunk's rows are written, then ingest_checkpoints(run, path) is upserted with
the uncompressed offset of the last consumed line, the sequence tracker and a snapshot of the ingest-ledger counters, in
one row, so a hard kill can never leave the ledger behind or ahead of the offsets (a resume restores the counters from
the newest checkpoint row, not from ingest_ledger rows, which are written only every --ledger-interval). A restart
re-decompresses a file from byte 0 and skips that many bytes (gzip cannot seek). Detector state is NOT checkpointed: it
restarts empty at the checkpoint offset. Episodes still `open` from the killed process are closed as `interrupted`; an
episode whose stopped run begins at a robot's first message after the resume is `left_censored` and writes no decision
(its start is unknown, so its dedup_key would not match the original episode's).

Retention: kept raw bytes = evidence lines + state_sample lines + reject raws; every other raw line is dropped after
parsing. Transitions, episodes and decisions are derived rows and always kept. Nothing here reads a message's `custom`.
"""
import glob as _glob
import hashlib
import json
import os
import re
import signal
import threading
import time
import zlib
from collections import OrderedDict
from pathlib import Path

from . import decisions
from .detector import DEFAULT_STUCK_AFTER, Detector
from .ledger import IngestLedger, SequenceTracker, coverage, lag_enabled
from .parse import epoch_of, parse_line

CHUNK_BYTES = 1 << 20  # compressed bytes fed to the decompressor per step
EVIDENCE_BEFORE = 25  # lines before the deciding message
EVIDENCE_AFTER = 24  # lines after it; 25 + the deciding line + 24 = 50, the bound the brief's test names
STATE_SAMPLE_EVERY = 50
REJECT_RAW_BYTES = 4096
TRUNCATE_AFTER_S = 10.0
_FILE_RE = re.compile(r"^(.*)-(\d+)\.jsonl(?:\.gz)?$")

TERMINAL = ("complete", "failed", "unlisted")


class _File:
    def __init__(self, path):
        self.path = path
        self.name = os.path.basename(path)
        m = _FILE_RE.match(self.name)
        self.zone_key, self.nnn = (m.group(1), int(m.group(2))) if m else (self.name, 0)
        self.status = "discovered"
        self.size = 0
        self.dec = zlib.decompressobj(wbits=31)
        self.fed = 0  # compressed bytes fed to the decompressor
        self.tail = b""
        self.consumed = 0  # uncompressed bytes of fully consumed lines (the checkpoint offset)
        self.skip = 0  # uncompressed bytes still to skip (resume)
        self.first_h, self.last_h = {}, {}
        self.sha256 = None
        self.in_ledger = False
        self.last_size = -1
        self.last_change = None
        self.written = None  # signature of the last ingest_files row written



class Pipeline:
    """The source-independent half: parse -> sequence accounting -> detector -> store + ledgers. A source (the file
    Ingester here, kafka_source.KafkaIngester) feeds raw lines through `_line`, writes `transitions` and a checkpoint
    row per consumed chunk and calls `_maybe_ledger`; everything else is shared, so both sources produce the same rows."""

    def __init__(self, run, store, source, label, emit_path=None, stuck_after=DEFAULT_STUCK_AFTER,
                 ledger_interval=10.0, clock=time.time, log=None, stations=None, station_radius=0):
        self.run, self.store, self.source, self.glob = run, store, source, label
        self.stuck_after, self.ledger_interval, self.clock = stuck_after, ledger_interval, clock
        self._stop = threading.Event()
        self.log = log or (lambda s: None)
        self.emit_path = Path(emit_path) if emit_path else None
        self.emit = None  # last good emit ledger document
        self._checkpoints = {}
        self._cp_seq = 0
        resuming = bool(store.select("ingest_checkpoints", {"run": run}))
        self.det = Detector(stuck_after, resumed=resuming, stations=stations, station_radius=station_radius)
        self.station_aware = stations is not None
        self.ledger = IngestLedger(run, source, clock)
        self.seq = SequenceTracker()
        self.exit_code = 0
        self._tx = []  # transition rows of the chunk in progress
        self._last_ledger_write = clock()
        self._latest_ts = None
        self._accepted_ts = {}  # zone -> ts of the last ACCEPTED message of that zone (kept apart from _latest_ts: see _behind)
        self._ring = {}  # zone -> OrderedDict seq -> entry [serial, ts, line, minute, kept]
        self._seq_of = {}  # zone -> {(serial, ts): seq}
        self._next_seq = {}  # zone -> next arrival seq
        self._ts_first_seq = {}  # zone -> {ts: first seq of that ts}
        self._pending_ev = []  # evidence waiting for its lines after the deciding message
        self._load_resume()


    # ------------------------------------------------------------------ resume
    def _load_resume(self):
        cps = self.store.select("ingest_checkpoints", {"run": self.run})
        if not cps:
            self.ledger.preload(self.store.select("ingest_ledger", {"run": self.run}))
            return
        for cp in cps:
            self._checkpoints[cp["path"]] = cp
            for serial, h in json.loads(cp["last_header_ids"]).items():
                if h > self.seq.last.get(serial, -1):
                    self.seq.last[serial] = h
        for cp in cps:  # per-zone max over the run's rows
            for zone, ts in json.loads(cp.get("last_message_ts_by_zone") or "{}").items():
                if ts > self._accepted_ts.get(zone, float("-inf")):
                    self._accepted_ts[zone] = ts
        newest = max(cps, key=lambda cp: cp.get("cp_seq") or 0)
        self._cp_seq = newest.get("cp_seq") or 0
        if newest.get("ledger_counters"):
            self.ledger.restore(json.loads(newest["ledger_counters"]))
        else:
            self.ledger.preload(self.store.select("ingest_ledger", {"run": self.run}))
        stale = [dict(ep, resolution="interrupted") for ep in self.store.select("stuck_episodes", {"run": self.run})
                 if ep.get("resolution") == "open"]
        if stale:
            self.store.upsert("stuck_episodes", ("run", "episode_id"), stale)

    def stop(self, *_):
        self._stop.set()

    # ------------------------------------------------------------------ emit ledger
    def _read_emit(self):
        if self.emit_path is None:
            return
        try:
            with open(self.emit_path) as f:
                self.emit = json.load(f)
        except (OSError, ValueError):
            pass  # absent or caught mid-rewrite (it is replaced atomically, so keep the last good one)

    def _listed(self):
        names = set()
        for z in (self.emit or {}).get("zones", []):
            names.update(f["name"] for f in z.get("files", []))
        return names

    def _lag_ok(self):
        return self.emit is not None and lag_enabled(self.emit.get("config"))

    def _behind(self):
        if self.emit is None or self._latest_ts is None:
            return None
        last = [z["last_timestamp"] for z in self.emit.get("zones", []) if z.get("last_timestamp")]
        if not last:
            return None
        return max(epoch_of(t) for t in last) - self._latest_ts

    # ------------------------------------------------------------------ lines
    def _line(self, f, line, wall, lag_ok):
        led = self.ledger
        minute = led.line_read(len(line))
        msg, reason = parse_line(line)
        if msg is None:
            led.rejected()
            led.keep(minute, min(len(line), REJECT_RAW_BYTES))
            self.store.insert("rejects", [dict(run=self.run, source=self.source, file=f.name, offset=f.consumed,
                                               reason=reason, raw=line[:REJECT_RAW_BYTES].decode("utf-8", "replace"))])
            return
        led.parsed()
        f.first_h.setdefault(msg.serial, msg.header_id)
        f.last_h[msg.serial] = max(f.last_h.get(msg.serial, 0), msg.header_id)
        accepted, missing = self.seq.check(msg.serial, msg.header_id)
        if not accepted:
            led.duplicate()
            return
        if missing:
            led.gap(missing)
        led.accepted(wall - msg.ts if lag_ok else None)
        if self._latest_ts is None or msg.ts > self._latest_ts:
            self._latest_ts = msg.ts
        zone = msg.zone
        if msg.ts > self._accepted_ts.get(zone, float("-inf")):
            self._accepted_ts[zone] = msg.ts  # only accepted messages get here: rejects and duplicates returned above
        seq = self._next_seq.get(zone, 0)
        self._next_seq[zone] = seq + 1
        entry = [msg.serial, msg.ts, line, minute, False]
        self._ring.setdefault(zone, OrderedDict())[seq] = entry
        self._seq_of.setdefault(zone, {})[(msg.serial, msg.ts)] = seq
        self._ts_first_seq.setdefault(zone, {}).setdefault(msg.ts, seq)
        if msg.header_id % STATE_SAMPLE_EVERY == 0:
            self._keep(entry)
            self.store.insert("state_sample", [dict(run=self.run, zone=zone, serial=msg.serial, header_id=msg.header_id,
                                                    ts=msg.ts, raw=line.decode("utf-8", "replace"))])
        for ev in self._pending_ev:  # lines after earlier deciding messages
            if ev["zone"] == zone and len(ev["after"]) < EVIDENCE_AFTER:
                ev["after"].append(entry)
                self._keep(entry)
        self._flush_evidence()
        self._handle(self.det.feed(msg))
        self._flush_evidence()

    def _keep(self, entry):
        if not entry[4]:
            entry[4] = True
            self.ledger.keep(entry[3], len(entry[2]))

    # ------------------------------------------------------------------ detector events
    def _handle(self, events):
        for ev in events:
            kind = ev["kind"]
            if kind == "transition":
                self._tx.append(dict(run=self.run, zone=ev["zone"], robot=ev["robot"], ts=ev["ts"],
                                     from_state=ev["from_state"], to_state=ev["to_state"], cell=ev["cell"],
                                     order_id=ev["order_id"]))
                continue
            row = {k: v for k, v in ev.items() if k not in ("kind", "decided_by")}
            row["run"] = self.run
            self.store.upsert("stuck_episodes", ("run", "episode_id"), [row])
            if ev.get("left_censored"):
                continue  # start unknown after a resume: no decision (its dedup_key would be a second key)
            if kind == "episode_open":
                self._decide("stuck_cause", ev, ev["t_entry"], dict(
                    episode_id=ev["episode_id"], cause=ev["cause"], blocker=ev["blocker"],
                    blocker_faulted_s=ev["blocker_faulted_s"], cell=ev["cell"]), None, ev["t_entry"],
                    f"{ev['robot']} stopped with order {ev['order_id']} at {ev['cell']} for {self.stuck_after}s; "
                    f"cause {ev['cause']}")
            elif ev["avoidable"]:
                self._decide("avoidable_reset", ev, ev["end"], dict(
                    episode_id=ev["episode_id"], blocker=ev["blocker"], avoidable_s=ev["avoidable_s"]),
                    ev["avoidable_s"] / 60, ev["end"],
                    f"{ev['robot']} waited {ev['avoidable_s']}s beyond {self.stuck_after}s behind faulted "
                    f"{ev['blocker']}")

    def _decide(self, kind, ev, decided_at, claim, expected, anchor, rationale):
        did, created = decisions.record_decision(
            self.store, run=self.run, kind=kind, subject=ev["robot"], start_iso=ev["start_iso"],
            decided_at=decided_at, claim=claim, rationale=rationale, expected=expected,
            grade_after=anchor + decisions.GRADE_AFTER_S, recorded_at=self.clock())
        if not created:
            return
        seq = self._seq_of.get(ev["zone"], {}).get(ev["decided_by"])
        ring = self._ring.get(ev["zone"], {})
        if seq is None or seq not in ring:
            return
        upto = min(seq + 1 + EVIDENCE_AFTER, self._next_seq[ev["zone"]])
        before = [ring[s] for s in range(max(seq - EVIDENCE_BEFORE, 0), seq) if s in ring]
        after = [ring[s] for s in range(seq + 1, upto) if s in ring]
        for e in before + [ring[seq]] + after:
            self._keep(e)
        self._pending_ev.append(dict(id=did, zone=ev["zone"], lines=before + [ring[seq]], after=after))

    def _flush_evidence(self, zone=None):
        keep = []
        for ev in self._pending_ev:
            if len(ev["after"]) >= EVIDENCE_AFTER or (zone is not None and ev["zone"] == zone):
                lines = [e[2].decode("utf-8", "replace") for e in ev["lines"] + ev["after"]]
                self.store.insert("evidence", [dict(decision_id=ev["id"], run=self.run, zone=ev["zone"], lines=lines,
                                                    line_count=len(lines), bytes=sum(len(x) for x in lines))])
            else:
                keep.append(ev)
        self._pending_ev = keep

    def _trim(self):
        """Drop ring entries no pending batch or evidence window can still need."""
        for zone, ring in self._ring.items():
            e = self.det.earliest_pending_ts(zone)
            first = self._ts_first_seq[zone]
            if e is None or e not in first:
                floor = self._next_seq[zone] - EVIDENCE_BEFORE
                first.clear()
            else:
                floor = first[e] - EVIDENCE_BEFORE
                for ts in [t for t in first if t < e]:
                    del first[ts]
            seq_of = self._seq_of[zone]
            while ring and next(iter(ring)) < floor:
                _, entry = ring.popitem(last=False)
                seq_of.pop((entry[0], entry[1]), None)


    # ------------------------------------------------------------------ checkpoints / ledger rows
    def _write_checkpoint(self, path, offset):
        """One ingest_checkpoints row per (run, path): the offset, the sequence tracker and the ledger counters."""
        self._cp_seq += 1
        self.store.upsert("ingest_checkpoints", ("run", "path"), [dict(
            run=self.run, path=path, offset_uncompressed=offset, last_header_ids=json.dumps(self.seq.last),
            ledger_counters=json.dumps(self.ledger.snapshot()), cp_seq=self._cp_seq, updated_at=self.clock(),
            last_message_ts_by_zone=json.dumps(self._accepted_ts))])

    def _write_files(self, only=None):
        pass  # file source only

    def _backlog(self):
        raise NotImplementedError

    def _after_ledger(self):
        pass  # source hook: extra rows written with every ledger write

    def _maybe_ledger(self, force):
        if not force and self.clock() - self._last_ledger_write < self.ledger_interval:
            return
        self._last_ledger_write = self.clock()
        rows = self.ledger.rows(self._behind(), self._backlog(), self._lag_ok())
        if rows:
            self.store.upsert("ingest_ledger", ("run", "source", "minute"), rows)
        expected = ((self.emit or {}).get("total") or {}).get("expected_messages")
        row = dict(
            run=self.run, glob=self.glob, emit_ledger=str(self.emit_path) if self.emit else None,
            emit_status=(self.emit or {}).get("status"), emit_config=(self.emit or {}).get("config"),
            expected_messages=expected, updated_at=self.clock())
        if self.station_aware:  # S13B: stopped runs the detector filed as SERVICING (no episode), key only with stations
            row["servicing_runs"] = self.det.servicing_runs
        self.store.upsert("ingest_runs", ("run",), [row])
        self._after_ledger()

    def finish(self):
        """End of input for every zone: open episodes close `unresolved`, evidence and ledger rows are flushed."""
        self._handle(self.det.end_all())
        if self._tx:
            self.store.insert("transitions", self._tx)
            self._tx = []
        for zone in sorted({ev["zone"] for ev in self._pending_ev}):
            self._flush_evidence(zone=zone)
        self._write_files()
        self._maybe_ledger(force=True)

    def summary(self):
        acc = self.ledger.total("messages_accepted")
        exp = ((self.emit or {}).get("total") or {}).get("expected_messages")
        return (f"accepted {acc} (parsed {self.ledger.total('messages_parsed')}, rejected "
                f"{self.ledger.total('messages_rejected')}, duplicates {self.ledger.total('duplicates')}), "
                f"coverage {coverage(acc, exp)}")


class Ingester(Pipeline):
    def __init__(self, glob, run, store, stuck_after=DEFAULT_STUCK_AFTER, poll=2.0, ledger_interval=10.0, once=False,
                 clock=time.time, sleep=None, truncate_after=TRUNCATE_AFTER_S, log=None, stations=None,
                 station_radius=0):
        self.poll, self.once, self.truncate_after = poll, once, truncate_after
        self._sleep = sleep or self._stop_wait
        self.files = {}
        super().__init__(run, store, "file", glob, os.path.join(os.path.dirname(glob) or ".", "emit_ledger.json"),
                         stuck_after, ledger_interval, clock, log, stations, station_radius)

    def _stop_wait(self, timeout):
        return self._stop.wait(timeout)

    # ------------------------------------------------------------------ discovery
    def _discover(self):
        for path in sorted(_glob.glob(self.glob)):
            if path not in self.files:
                f = _File(path)
                self.files[path] = f
                done = self.store.select("ingest_files", {"run": self.run, "path": path})
                size = os.path.getsize(path)
                if done and done[0]["status"] == "complete" and done[0]["size_bytes"] == size:
                    f.status, f.size, f.fed = "complete", size, size  # nothing left to read
                    f.sha256 = done[0].get("sha256")
                    f.first_h = json.loads(done[0]["first_header_ids"] or "{}")
                    f.last_h = json.loads(done[0]["last_header_ids"] or "{}")
                    f.consumed = (self._checkpoints.get(path) or {}).get("offset_uncompressed", 0)
                    f.in_ledger = bool(done[0]["in_emit_ledger"])
                elif path in self._checkpoints:
                    f.skip = f.consumed = self._checkpoints[path]["offset_uncompressed"]
        listed = self._listed()
        final = self.emit is not None and self.emit.get("status") in ("complete", "failed")
        for f in self.files.values():
            f.in_ledger = self.emit is not None and f.name in listed
            if f.status in ("discovered", "unlisted"):
                if self.emit is None or f.in_ledger:
                    f.status = "discovered"
                elif final:
                    f.status = "unlisted"

    def _zone_files(self):
        zones = {}
        for f in self.files.values():
            zones.setdefault(f.zone_key, []).append(f)
        return {z: sorted(fs, key=lambda f: f.nnn) for z, fs in zones.items()}

    # ------------------------------------------------------------------ one poll
    def poll_once(self):
        """Read what is on disk now. Returns True when any bytes were fed."""
        self._read_emit()
        self._discover()
        progressed = False
        for zone, fs in sorted(self._zone_files().items()):
            for f in fs:
                if f.status == "complete" or f.status == "unlisted":
                    continue
                if f.status == "failed":
                    break
                if f.status == "discovered" and self.emit is not None and not f.in_ledger:
                    break  # waiting to be listed; later files of the zone must wait too
                progressed |= self._read_file(f)
                if f.status != "complete":
                    break
        self._write_files()
        self._maybe_ledger(force=False)
        return progressed

    def _read_file(self, f):
        progressed = False
        while not self._stop.is_set():
            try:
                f.size = os.path.getsize(f.path)
            except OSError:
                return progressed
            now = self.clock()
            if f.size != f.last_size:
                f.last_size, f.last_change = f.size, now
            if f.fed >= f.size:
                if f.dec.eof:
                    break
                running = self.emit is not None and self.emit.get("status") == "running"
                if not running and now - f.last_change >= self.truncate_after:
                    self._fail(f, "truncated: no end of stream")
                break
            f.status = "reading"
            with open(f.path, "rb") as fh:
                fh.seek(f.fed)
                data = fh.read(min(CHUNK_BYTES, f.size - f.fed))
            f.fed += len(data)
            self.ledger.fed(len(data))
            progressed = True
            try:
                out = f.dec.decompress(data)
            except zlib.error as e:
                self._fail(f, f"corrupt gzip: {e}")
                break
            self._chunk(f, out)
            if f.dec.eof:
                break
        if f.dec.eof and f.status not in ("failed", "complete"):
            if f.tail:  # last line without a newline
                self._chunk(f, b"", final=True)
            f.status = "complete"
            f.sha256 = self._sha256(f.path)
            self._checkpoint(f)
            self._write_files(only=f)
        return progressed

    @staticmethod
    def _sha256(path):
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                h.update(block)
        return h.hexdigest()

    def _fail(self, f, why):
        f.status = "failed"
        self.exit_code = 1
        self.log(f"file {f.name} failed: {why}")
        self._write_files(only=f)

    # ------------------------------------------------------------------ chunk / lines
    def _chunk(self, f, out, final=False):
        if f.skip:
            cut = min(len(out), f.skip)
            out, f.skip = out[cut:], f.skip - cut
        buf = f.tail + out
        if final:
            lines, f.tail = ([buf] if buf else []), b""
        else:
            *lines, f.tail = buf.split(b"\n")
            lines = [ln + b"\n" for ln in lines]
        wall = self.clock()
        lag_ok = self._lag_ok()
        for line in lines:
            self._line(f, line, wall, lag_ok)
            f.consumed += len(line)
        if self._tx:
            self.store.insert("transitions", self._tx)
            self._tx = []
        self._checkpoint(f)
        self._trim()
        self._maybe_ledger(force=False)


    # ------------------------------------------------------------------ checkpoints / files / ledger rows
    def _checkpoint(self, f):
        self._write_checkpoint(f.path, f.consumed)

    def _write_files(self, only=None):
        rows = []
        for f in ([only] if only else self.files.values()):
            sig = (f.status, f.size, f.fed, f.consumed, f.in_ledger)
            if f.written == sig:
                continue
            f.written = sig
            rows.append(dict(run=self.run, path=f.path, size_bytes=f.size, bytes_done_uncompressed=f.consumed,
                             bytes_done_compressed=f.fed, status=f.status, sha256=f.sha256,
                             first_header_ids=json.dumps(f.first_h), last_header_ids=json.dumps(f.last_h),
                             in_emit_ledger=f.in_ledger, updated_at=self.clock()))
        if rows:
            self.store.upsert("ingest_files", ("run", "path"), rows)

    def _backlog(self):
        return sum(max(f.size - f.fed, 0) for f in self.files.values() if f.status not in ("unlisted",))


    # ------------------------------------------------------------------ loop
    def _finished(self):
        """(done, exit_code) from the emit ledger: over when it is final and every matched file is terminal."""
        if self.emit is None or self.emit.get("status") not in ("complete", "failed"):
            return False, 0
        if any(f.status not in TERMINAL for f in self.files.values()):
            return False, 0
        present = {f.name for f in self.files.values()}
        missing = self._listed() - present
        ok = self.emit["status"] == "complete" and not missing and \
            all(f.status != "failed" for f in self.files.values())
        if missing:
            self.log(f"listed in the emit ledger but not on disk: {sorted(missing)}")
        return True, 0 if ok else 1

    def run_loop(self):
        while True:
            self._read_emit()
            while self.poll_once() and not self._stop.is_set():
                pass
            done, code = self._finished()
            if done:
                self.exit_code = max(self.exit_code, code)
                break
            if self.once or self._stop.is_set():
                break
            self._sleep(self.poll)
        self.finish()
        return self.exit_code



def install_signal_handlers(ing):
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, ing.stop)


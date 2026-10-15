"""Unit tests for S8G live mode: the HTTP handlers on a fake state, the inject validator, the stream tail and the
forward-only publisher, the emitter's cost-map hook and demo-only flags, and a string-level check of the page.
No children are started here (fleet/tests/test_live_smoke.py is the end-to-end test)."""
import json
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "fleet", ROOT / "src", ROOT / "scripts", ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import live  # noqa: E402
from fleet_analyser import emitter as em, live_state, sinks  # noqa: E402

EMIT = str(ROOT / "fleet" / "emit.py")
SMALL = "tarware-small-4agvs-2pickers-globalobs-v1"
GRID = (25, 14)  # (rows, cols) of the small map


class FakeState:
    def __init__(self, truth=None):
        self.doc = {k: None for k in live_state.STATE_KEYS}
        self.doc.update(step=7, robots=[], ledger={"pgid": 1}, top10=[], lessons=[], grades={}, injections=[], truth=truth)

    def snapshot(self):
        return self.doc


class Served:
    def __init__(self, test, step=10):
        self.tmp = tempfile.TemporaryDirectory()
        test.addCleanup(self.tmp.cleanup)
        self.ctl = Path(self.tmp.name) / "control.jsonl"
        self.ctl.write_bytes(b'{"t":1,"floor":{"1,1":0.5}}\n')
        self.inj = live_state.Injector(self.ctl, GRID, 6, lambda: step, lead=2)
        self.srv = live.make_server("127.0.0.1", 0, FakeState(), self.inj, {"width": 14})
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        test.addCleanup(self._stop)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def _stop(self):
        self.srv.shutdown()
        self.srv.server_close()

    def req(self, method, path, body=None, headers=None):
        data = body if isinstance(body, bytes) or body is None else json.dumps(body).encode()
        r = urllib.request.Request(self.url + path, data=data, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(r, timeout=5) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()


class HandlerTests(unittest.TestCase):
    def test_state_keys_and_truth_null(self):
        s = Served(self)
        code, h, body = s.req("GET", "/state")
        self.assertEqual(code, 200)
        doc = json.loads(body)
        self.assertEqual(set(doc), set(live_state.STATE_KEYS))
        self.assertEqual(set(doc), {"step", "sim_time", "robots", "ledger", "costmap", "top10", "lessons", "grades",
                                    "injections", "truth"})
        self.assertIsNone(doc["truth"])
        self.assertEqual(h["Access-Control-Allow-Origin"], "*")

    def test_cors_on_every_response(self):
        s = Served(self)
        for method, path, body in (("GET", "/state", None), ("GET", "/nope", None), ("POST", "/nope", b"{}"),
                                   ("POST", "/inject", b"not json"), ("OPTIONS", "/inject", None),
                                   ("POST", "/inject", {"floor": {"2,2": 0.9}})):
            code, h, _ = s.req(method, path, body)
            self.assertEqual(h.get("Access-Control-Allow-Origin"), "*", (method, path, code))
        code, h, _ = s.req("OPTIONS", "/inject")
        self.assertIn(code, (200, 204))
        self.assertIn("POST", h["Access-Control-Allow-Methods"])

    def test_unknown_path_404_get_and_post(self):
        s = Served(self)
        self.assertEqual(s.req("GET", "/nope")[0], 404)
        self.assertEqual(s.req("POST", "/nope", {})[0], 404)
        self.assertEqual(s.ctl.read_bytes(), b'{"t":1,"floor":{"1,1":0.5}}\n')

    def test_valid_floor_and_breakdown_append_one_line(self):
        s = Served(self, step=10)
        before = s.ctl.read_bytes()
        code, _, body = s.req("POST", "/inject", {"floor": {"2,2": 0.95}})
        self.assertEqual(code, 200)
        t = json.loads(body)["applies_at_step"]
        self.assertGreaterEqual(t, 10)
        data = s.ctl.read_bytes()
        self.assertTrue(data.startswith(before))
        new = data[len(before):]
        self.assertTrue(new.endswith(b"\n"))
        self.assertEqual(new.count(b"\n"), 1)
        self.assertEqual(json.loads(new), {"t": t, "floor": {"2,2": 0.95}})
        code, _, body = s.req("POST", "/inject", {"breakdown": {"agent": 2, "duration": 5}})
        self.assertEqual(code, 200)
        lines = s.ctl.read_bytes()[len(data):]
        self.assertEqual(json.loads(lines), {"t": json.loads(body)["applies_at_step"], "breakdown": {"agent": 2, "duration": 5}})

    def test_bad_bodies_are_400_and_leave_the_file_alone(self):
        s = Served(self)
        before = s.ctl.read_bytes()
        bad = [
            b"not json", b"[1]", b'"x"', b"{}", b"",
            {"floor": {"2,2": 0.9}, "breakdown": {"agent": 1, "duration": 3}},
            {"floor": {"2,2": 0.9}, "t": 3}, {"floor": {"2,2": 0.9}, "zone": 0}, {"zone": 0}, {"other": 1},
            {"floor": {"14,2": 0.9}}, {"floor": {"2,25": 0.9}}, {"floor": {"-1,2": 0.9}}, {"floor": {"2,2": 1.5}},
            {"floor": {"2,2": -0.1}}, {"floor": {"2,2": True}}, {"floor": {"2,2": "0.5"}}, {"floor": {}}, {"floor": 3},
            {"floor": {"a,b": 0.5}},
            {"breakdown": {"agent": True, "duration": 3}}, {"breakdown": {"agent": 1, "duration": True}},
            {"breakdown": {"agent": 1.5, "duration": 3}}, {"breakdown": {"agent": 1, "duration": 2.5}},
            {"breakdown": {"agent": 0, "duration": 3}}, {"breakdown": {"agent": 7, "duration": 3}},
            {"breakdown": {"agent": 1, "duration": 0}}, {"breakdown": {"agent": 1}},
        ]
        for b in bad:
            code, h, body = s.req("POST", "/inject", b)
            self.assertEqual(code, 400, b)
            self.assertIn("error", json.loads(body))
            self.assertEqual(h["Access-Control-Allow-Origin"], "*")
            self.assertEqual(s.ctl.read_bytes(), before, b)

    def test_nan_floor_p_is_rejected(self):
        s = Served(self)
        before = s.ctl.read_bytes()
        code, _, _ = s.req("POST", "/inject", b'{"floor": {"2,2": NaN}}')
        self.assertEqual(code, 400)
        self.assertEqual(s.ctl.read_bytes(), before)

    def test_body_larger_than_4096_bytes(self):
        s = Served(self)
        before = s.ctl.read_bytes()
        big = json.dumps({"floor": {"2,2": 0.9}, "pad": "x" * 5000}).encode()
        self.assertEqual(s.req("POST", "/inject", big)[0], 400)
        exactly = json.dumps({"floor": {"2,2": 0.9}}).encode()
        pad = b" " * (4097 - len(exactly))
        self.assertEqual(s.req("POST", "/inject", exactly + pad)[0], 400)  # 4097 bytes of valid JSON
        self.assertEqual(s.ctl.read_bytes(), before)
        ok = exactly + b" " * (4096 - len(exactly))
        self.assertEqual(s.req("POST", "/inject", ok)[0], 200)  # 4096 bytes is allowed

    def test_content_length_smaller_than_body_counts_what_is_read(self):
        s = Served(self)
        before = s.ctl.read_bytes()
        # the header says 10 bytes, the body is longer: only the 10 declared bytes are read (invalid JSON) -> 400
        code, _, _ = s.req("POST", "/inject", b'{"floor": {"2,2": 0.9}}', headers={"Content-Length": "10"})
        self.assertEqual(code, 400)
        self.assertEqual(s.ctl.read_bytes(), before)

    def test_applies_at_step_is_never_before_the_step_seen(self):
        s = Served(self, step=123)
        code, _, body = s.req("POST", "/inject", {"floor": {"2,2": 0.9}})
        self.assertGreaterEqual(json.loads(body)["applies_at_step"], 123)


class LockOrderTests(unittest.TestCase):
    def test_concurrent_inject_and_snapshot_do_not_deadlock(self):
        # the real wiring: the injector's step_fn is LiveState.current_step and snapshot() calls injector.listing()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name)
        inj = live_state.Injector(d / "control.jsonl", GRID, 6, lambda: 0, lead=2)
        state = live_state.LiveState(d, "run", f"jsonl:{d / 'store'}", str(d / "zone*-*.jsonl.gz"), inj, ttl=0)
        inj.step_fn = state.current_step
        n = 300

        def posts():
            for _ in range(n):
                inj.submit(b'{"floor": {"1,1": 0.5}}')

        def gets():
            for _ in range(n):
                state.snapshot()

        threads = [threading.Thread(target=f, daemon=True) for f in (posts, gets)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        self.assertFalse(any(t.is_alive() for t in threads), "POST /inject and GET /state deadlocked")
        self.assertEqual(len((d / "control.jsonl").read_bytes().splitlines()), n)


class DirGuardTests(unittest.TestCase):
    def test_non_empty_dir_is_refused_before_anything_starts(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name)
        (d / "ingest.done").touch()
        r = subprocess.run([sys.executable, str(ROOT / "fleet" / "live.py"), "--dir", str(d), "--port", "0"],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("not empty", r.stderr)
        self.assertEqual(sorted(p.name for p in d.iterdir()), ["ingest.done"])


class StreamAndPublisherTests(unittest.TestCase):
    def _write_run(self, d, steps=40):
        """A tiny hand-made stream: robot A stalls in front of cell (3,2) from step 2 to 6."""
        sink = sinks.FileSink(d, 0, sync_flush=True)
        for step in range(steps):
            ts = em.timestamp_at("2026-01-01T00:00:00Z", step, 5)
            x = 2 if 2 <= step <= 6 else min(step, 2) if step < 2 else 2 + (step - 6)
            msg = {"schema_version": "fleet-state/2", "headerId": step, "timestamp": ts, "manufacturer": "sim",
                   "serialNumber": "Z0-01", "orderId": "Z0-1-o1", "lastNodeId": f"{x}-2",
                   "nodeStates": [{"nodeId": "3-2", "sequenceId": 0, "released": True,
                                   "nodePosition": {"x": 3, "y": 2, "mapId": "m"}}],
                   "agvPosition": {"x": x, "y": 2, "theta": 0.0, "mapId": "m"}, "driving": False, "paused": False,
                   "errors": [], "loads": [], "custom": {}}
            sink.write("Z0-01", em.encode(msg), ts, step)
            sink.flush_step()
            yield step, sink
        sink.close()

    def test_tail_reads_an_unfinished_sync_flushed_file(self):
        with tempfile.TemporaryDirectory() as d:
            tail = live_state.StreamTail(str(Path(d) / "zone*-*.jsonl.gz"))
            seen = 0
            for step, sink in self._write_run(d, 10):
                if step == 9:
                    break
                got = tail.poll()
                seen += len(got)
                self.assertEqual(seen, step + 1)  # every finished step is readable before the file is closed
            self.assertEqual(tail.rejected, 0)

    def test_publish_times_are_forward_only(self):
        pt = live_state.publish_times
        self.assertEqual(pt(0, 130, None, 60, False), [60, 120])
        self.assertEqual(pt(0, 130, 120, 60, False), [])
        self.assertEqual(pt(0, 190, 120, 60, False), [180])
        self.assertEqual(pt(0, 130, 120, 60, True), [130])
        self.assertEqual(pt(0, 120, 120, 60, True), [])

    def test_publisher_writes_each_time_once_and_only_from_the_stream(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "costmap.json"
            pub = live_state.Publisher(str(Path(d) / "zone*-*.jsonl.gz"), f"jsonl:{d}/store", "r", str(out))
            gen = self._write_run(d, 40)
            published = []
            for step, _ in gen:
                if step % 5 == 4:
                    published += pub.cycle()
            published += pub.cycle(final=True)
            first = pub.first_ts
            self.assertTrue(published)
            self.assertEqual(published, sorted(set(published)))  # never a time twice, never backwards
            self.assertEqual(published[0], first + 60)
            doc = json.loads(out.read_text())
            self.assertEqual(doc["generated_at"], live_state.iso(published[-1]))
            self.assertIn("3,2", doc["zones"]["0"])  # the stalled-in-front cell, found from messages alone


class EmitterHookTests(unittest.TestCase):
    def test_cost_map_file_changes_the_active_map_before_the_next_act_and_corrupt_keeps_it(self):
        import evaluate as ev

        with tempfile.TemporaryDirectory() as d:
            ctl, cmf = Path(d) / "c.jsonl", Path(d) / "costmap.json"
            ctl.touch()
            seen = []
            real = ev.make_policy

            class Spy:
                def __init__(self, pol):
                    self.pol, self.hook = pol, None

                def reset(self, env):
                    self.hook = env.env
                    return self.pol.reset(env)

                def act(self, *a, **k):
                    seen.append(None if self.hook._active_map is None else dict(self.hook._active_map))
                    return self.pol.act(*a, **k)

            ev.make_policy = lambda name, seed: Spy(real(name, seed))
            self.addCleanup(setattr, ev, "make_policy", real)

            def on_step(step, env, info):
                if step == 1:
                    cmf.write_text(json.dumps({"zones": {"0": {"3,2": 0.5}}}))
                elif step == 3:
                    cmf.write_text("{ not json")
                elif step == 5:
                    cmf.write_text(json.dumps({"zones": {"0": {"99,99": 0.5}}}))  # outside the grid: unusable too

            cfg = em.zone_config(dict(env_id=SMALL, steps=8, seed_base=0, zones=1, disturb={}, recovery={"name": "timeout", "call_human_cost": 60},
                                      policy="stuck_aware_cta", t0="2026-01-01T00:00:00Z", rate="flat", speed=0,
                                      demo_mode=True, control_file=str(ctl), cost_map_file=str(cmf), cost_alpha=8.0), 0)

            class NullSink:
                def write(self, *a, **k):
                    pass

                def stats(self):
                    return dict(messages=0, bytes_uncompressed=0, bytes_compressed=0, files=[], delivered=None,
                                delivery_failed=None)

                def close(self):
                    pass

            res = em.run_zone(cfg, NullSink(), on_step=on_step)
        self.assertEqual(len(seen), 8)
        self.assertIsNone(seen[0])
        self.assertIsNone(seen[1])  # written after step 1; not yet in force during it
        self.assertEqual(seen[2], {(3, 2): 0.5})  # in force before the very next pol.act
        self.assertEqual(seen[4], {(3, 2): 0.5})  # corrupt file at step 3: previous map kept
        self.assertEqual(seen[7], {(3, 2): 0.5})  # invalid file at step 5: previous map kept
        self.assertEqual((res["map_refreshes"], res["map_unparsed"]), (1, 2))

    def test_cost_map_file_without_demo_mode_raises(self):
        cfg = em.zone_config(dict(env_id=SMALL, steps=2, seed_base=0, zones=1, disturb={}, recovery={"name": "timeout", "call_human_cost": 60},
                                  policy="stuck_aware_cta", t0="2026-01-01T00:00:00Z", cost_map_file="/tmp/x.json",
                                  cost_alpha=4.0), 0)
        with self.assertRaises(ValueError):
            em.run_zone(cfg, object())

    def test_cli_rejects_cost_flags_without_demo(self):
        for extra in (["--cost-map-file", "/tmp/x.json"], ["--cost-alpha", "4"]):
            r = subprocess.run([sys.executable, EMIT, "--steps", "2"] + extra, capture_output=True, text=True)
            self.assertEqual(r.returncode, 2, extra)
            self.assertIn("demo", r.stderr)

    def test_sync_flush_is_off_by_default_and_changes_only_the_gz_bytes(self):
        def write(sync):
            with tempfile.TemporaryDirectory() as d:
                s = sinks.make_sink(dict(kind="file", dir=d, rotate_bytes=10 ** 6, **({"sync_flush": True} if sync else {})), 0)
                for i in range(30):
                    s.write("a", b'{"i":%d}\n' % i)
                    s.flush_step()
                s.close()
                raw = (Path(d) / "zone0-000.jsonl.gz").read_bytes()
                import gzip
                return raw, gzip.decompress(raw)

        off, off_text = write(False)
        on, on_text = write(True)
        self.assertEqual(off_text, on_text)
        self.assertNotEqual(off, on)


class PageStringTests(unittest.TestCase):
    def setUp(self):
        self.js = (ROOT / "docs" / "replay" / "replay.js").read_text()
        self.html = (ROOT / "docs" / "replay" / "index.html").read_text()

    def test_live_param_poll_rate_and_localhost_guard(self):
        self.assertIn("URLSearchParams", self.js)
        self.assertIn("'live'", self.js)
        self.assertIn("POLL_MS = 500", self.js)  # 2 Hz
        self.assertIn("'localhost'", self.js)
        self.assertIn("'127.0.0.1'", self.js)
        self.assertIn("/state", self.js)
        self.assertIn("/inject", self.js)
        self.assertIn("0.95", self.js)
        self.assertIn("placed by you", self.js)

    def test_offline_page_is_still_there(self):
        for needle in ('<script src="data.js"></script>', '<script src="replay.js"></script>', 'id="floor"', 'id="counters"',
                       'id="lessons"', 'id="scrub"', 'id="routerBox"'):
            self.assertIn(needle, self.html)
        self.assertLess(self.html.index("data.js"), self.html.index("replay.js"))
        self.assertIn("if (!R || !R.frames || !R.meta)", self.js)


if __name__ == "__main__":
    unittest.main()

"""End-to-end smoke for S8G live mode (fleet/live.py): real children, a real HTTP server, one roadblock placed while the
fleet runs, the analyser's cost map observed LIVE through /state, lessons, a clean pgid-checked shutdown. <= 120 s wall.

Fixed inputs (they are the test's contract): small map, seed 29, speed 20, --disturb none (no scheduled floor: the
injected patch is the only floor), --router none (the emitter gets no cost map), --steps 330 (82 s of wall time, so the
run outlasts every poll and SIGINT reaches a live process), fixed --t0, lesson window 0.2 h (144 steps), publisher
min_stalls=1 and exclude_occupied=True (the live.py defaults, which is what extract_stalls/counted below mirror).
The patch is placed when /state.step first reaches PLACE_AT; seed 29 and that step were chosen so a lesson is drawn in the
first lesson window (closing at step 144); the emitter is deterministic given the injection step, which the server picks
as the observed step + a small lead.
Steps are message timestamps at 5 s per step from --t0."""
import calendar
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "fleet", ROOT / "src", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fleet_analyser import hotspot, live_state, store as store_mod  # noqa: E402

LIVE = str(ROOT / "fleet" / "live.py")
SMALL = "tarware-small-4agvs-2pickers-globalobs-v1"
T0 = "2026-01-01T00:00:00Z"
T0_EPOCH = calendar.timegm(time.strptime(T0, "%Y-%m-%dT%H:%M:%SZ"))
SEED, SPEED, STEPS, WINDOW_H = 29, 20, 330, 0.2
PLACE_AT = 60  # place the patch once the run reaches this step
P = 0.95
EXCLUDE_OCCUPIED, MIN_STALLS = True, 1
PUBLISH_STEPS = 12  # 60 simulated s at 5 s per step
WALL_BUDGET_S = 115


def step_of(ts):
    return (ts - T0_EPOCH) // 5


def get(url, path, timeout=3):
    with urllib.request.urlopen(url + path, timeout=timeout) as r:
        return json.loads(r.read())


class LiveSmoke(unittest.TestCase):
    def test_roadblock_is_found_live_and_shutdown_is_clean(self):
        t_start = time.monotonic()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name) / "live-smoke"
        import socket

        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        proc = subprocess.Popen(
            [sys.executable, LIVE, "--env", SMALL, "--seed", str(SEED), "--disturb", "none", "--speed", str(SPEED),
             "--steps", str(STEPS), "--t0", T0, "--router", "none", "--lesson-window-h", str(WINDOW_H), "--port", str(port),
             "--dir", str(d)], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        out, err = [], []
        for stream, sink in ((proc.stdout, out), (proc.stderr, err)):
            threading.Thread(target=lambda st=stream, sk=sink: [sk.append(line) for line in st], daemon=True).start()
        pgid_box = []

        def cleanup():
            if proc.poll() is None:
                proc.kill()
            for g in pgid_box:
                try:
                    os.killpg(g, signal.SIGKILL)
                except OSError:
                    pass

        self.addCleanup(cleanup)
        url = f"http://127.0.0.1:{port}"
        # 1. it starts and says where its children live
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and not (any(l.startswith("pgid ") for l in out) and any(l.startswith("listening") for l in out)):
            self.assertIsNone(proc.poll(), f"live.py exited early: {''.join(out)} {''.join(err)}")
            time.sleep(0.1)
        pgid_lines = [l for l in out if l.startswith("pgid ")]
        self.assertTrue(pgid_lines, "live.py never printed 'pgid N'")
        pgid = int(pgid_lines[0].split()[1])
        pgid_box.append(pgid)
        self.assertNotEqual(pgid, os.getpgid(0))
        self.assertNotEqual(pgid, os.getpgid(proc.pid), "live.py must stay outside the children's group")
        # 2. wait for the run to reach PLACE_AT
        state = None
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            try:
                state = get(url, "/state")
            except OSError:
                state = None
            if state and state["step"] >= PLACE_AT:
                break
            time.sleep(0.05)
        self.assertIsNotNone(state, "no /state answer")
        self.assertGreaterEqual(state["step"], PLACE_AT, "the run never reached the placement step")
        self.assertEqual(state["ledger"]["pgid"], pgid)
        grid = get(url, "/grid")
        # 3. pick a busy highway cell from the stream so far (header ids <= PLACE_AT), never a goal, shelf or a cell that
        #    already stalled a robot (it would be on the map before the patch exists)
        tail = live_state.StreamTail(str(d / "zone*-*.jsonl.gz"))
        msgs = [m for m in tail.poll() if m.header_id <= PLACE_AT]
        self.assertGreater(len(msgs), 0, "no messages on disk")
        goals = {tuple(g) for g in grid["goals"]}
        visits = {}
        for m in msgs:
            if grid["highway"][m.y][m.x] == "1" and (m.x, m.y) not in goals:
                visits[f"{m.x},{m.y}"] = visits.get(f"{m.x},{m.y}", 0) + 1
        stalled_before = {s["cell"] for s in hotspot.extract_stalls(msgs, "r")}
        cell = next((c for c, _ in sorted(visits.items(), key=lambda kv: (-kv[1], kv[0])) if c not in stalled_before), None)
        self.assertIsNotNone(cell, "no busy highway cell without an earlier stall")
        state = get(url, "/state")
        costmap = state["costmap"]
        # (a0) absent at injection
        self.assertTrue(costmap is None or cell not in costmap["cells"], f"{cell} is on the map before the patch")
        step_before = state["step"]
        req = urllib.request.Request(url + "/inject", data=json.dumps({"floor": {cell: P}}).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3) as r:
            self.assertEqual(r.status, 200)
            inj_step = json.loads(r.read())["applies_at_step"]
        self.assertGreaterEqual(inj_step, step_before)
        # 4. observe live: the first poll that shows the cell on the map, and the first poll with a lesson
        sighting = lessons_seen = None
        deadline = t_start + WALL_BUDGET_S - 15
        while time.monotonic() < deadline and (sighting is None or lessons_seen is None):
            try:
                state = get(url, "/state")
            except OSError:
                time.sleep(0.05)
                continue
            if sighting is None and state["costmap"] and cell in state["costmap"]["cells"]:
                sighting = state["step"]
            if lessons_seen is None and state["lessons"]:
                lessons_seen = state["step"]
            self.assertEqual(set(state), set(live_state.STATE_KEYS))
            time.sleep(0.05)
        # 5. SIGINT: exit 0 within 10 s, nothing left in the group
        proc.send_signal(signal.SIGINT)
        try:
            rc = proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.fail("live.py did not exit within 10 s of SIGINT")
        self.assertEqual(rc, 0, f"live.py exit code {rc}: {''.join(err)}")
        gone = False
        for _ in range(40):
            try:
                os.killpg(pgid, 0)
            except ProcessLookupError:
                gone = True
                break
            time.sleep(0.05)
        self.assertTrue(gone, f"processes remain in group {pgid}")
        self.assertLess(time.monotonic() - t_start, 120, "smoke took longer than 120 s")
        self.assertIsNotNone(sighting, f"{cell} never showed up in /state.costmap")
        # (b) a lesson in a poll taken before SIGINT
        self.assertIsNotNone(lessons_seen, "no lesson in /state.lessons before SIGINT")
        # (c) every store line parses
        bad = []
        for f in sorted((d / "store").glob("*.jsonl")):
            for n, line in enumerate(f.read_text().splitlines(), 1):
                try:
                    json.loads(line)
                except ValueError:
                    bad.append(f"{f.name}:{n}")
        self.assertEqual(bad, [], "unparseable store lines (JsonlStore concurrent-append hazard): " + ", ".join(bad))
        # (a) from the emitted stream after the run
        all_msgs = live_state.StreamTail(str(d / "zone*-*.jsonl.gz"))
        messages = all_msgs.poll()
        stalls = hotspot.extract_stalls(messages, "live-smoke")
        st = store_mod.open_store(f"jsonl:{d / 'store'}", "live-smoke")
        try:
            hotspot.annotate_episodes(stalls, st.select("stuck_episodes", {"run": "live-smoke"}))
        finally:
            st.close()
        at = [s for s in stalls if s["cell"] == cell and hotspot.counted(s, EXCLUDE_OCCUPIED)]
        k = min((s for s in at if step_of(s["start"]) >= inj_step), key=lambda s: s["start"], default=None)
        self.assertIsNotNone(k, f"no counted stall at {cell} starting at or after step {inj_step}")
        b0_stall = min((s for s in at if step_of(s["end"]) >= inj_step - PUBLISH_STEPS), key=lambda s: s["start"])
        b0, s_end = step_of(b0_stall["start"]), step_of(k["end"])
        print(f"smoke: cell {cell} injection step {inj_step} B0 {b0} K start {step_of(k['start'])} S {s_end} "
              f"sighting {sighting} lesson first seen at step {lessons_seen} wall {time.monotonic() - t_start:.1f}s")
        self.assertGreater(sighting, b0, "the cell was on the map before any stall of it: a build that shows the patch from the injection list")
        self.assertLessEqual(sighting, s_end + 2 * PUBLISH_STEPS)


if __name__ == "__main__":
    unittest.main()

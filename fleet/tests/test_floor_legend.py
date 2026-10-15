"""S8H-FLOOR-LEGEND: the display-state mapping, replay/3 export fields, the live robots[] entry, the page text, the demo
config. The page itself is checked on its files only (no browser, no DOM)."""
import html as htmllib
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "fleet", ROOT / "src", ROOT / "scripts", ROOT / "tests", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import live  # noqa: E402
import replay_export as rx  # noqa: E402
from fleet.tests import test_replay_export as tre  # noqa: E402
from fleet_analyser import decisions, live_state  # noqa: E402
from fleet_analyser.parse import iso, parse_line  # noqa: E402
from fleet_analyser.store import JsonlStore  # noqa: E402

DOCS = ROOT / "docs" / "replay"
MAPPING = {"moving": "moving", "loading": "working", "frozen": "down", "stalled": "waiting", "stuck": "waiting",
           "idle": "waiting"}


# ------------------------------------------------------------------------------------------------ C1
class TestDisplayState(unittest.TestCase):
    def test_the_six_known_values(self):
        before = dict(live_state.UNKNOWN_STATES)
        for raw, want in MAPPING.items():
            self.assertEqual(live_state.display_state(raw), want, raw)
        self.assertEqual(dict(live_state.UNKNOWN_STATES), before)

    def test_an_unknown_value_is_waiting_and_counted_once_per_call(self):
        n = live_state.UNKNOWN_STATES["teleporting"]
        self.assertEqual(live_state.display_state("teleporting"), "waiting")
        self.assertEqual(live_state.UNKNOWN_STATES["teleporting"], n + 1)
        self.assertEqual(live_state.display_state("teleporting"), "waiting")
        self.assertEqual(live_state.UNKNOWN_STATES["teleporting"], n + 2)

    def test_every_raw_state_maps_into_the_four_display_states(self):
        self.assertEqual(live_state.DISPLAY_STATES, ("moving", "working", "waiting", "down"))
        for raw in rx.STATES:
            self.assertIn(live_state.display_state(raw), live_state.DISPLAY_STATES, raw)
        cases = (dict(faulted=True), dict(order_id="o1", nodes_reported=True), dict(driving=True), dict())
        seen = set()
        for kw in cases:
            raw = live_state.robot_state(tre.message(**kw))
            seen.add(raw)
            self.assertIn(raw, rx.STATES)
            self.assertIn(live_state.display_state(raw), live_state.DISPLAY_STATES)
        self.assertEqual(seen, {"frozen", "loading", "moving", "idle"})

    def test_the_exporter_uses_the_one_function(self):
        for raw in rx.STATES:
            self.assertEqual(live_state.display_state(raw), MAPPING[raw])
        self.assertIs(rx.live_state, live_state)
        with tempfile.TemporaryDirectory() as tmp:
            d = tre.build_run(tmp)
            spec = f"jsonl:{d / 'store'}"
            p = rx.build_payload(d, spec, "0", env_runner=tre.fake_env)
            self.assertEqual(p["meta"]["state_display"], {s: live_state.display_state(s) for s in rx.STATES})
            with mock.patch.object(live_state, "display_state", lambda raw: "down"):
                q = rx.build_payload(d, spec, "0", env_runner=tre.fake_env)
        self.assertEqual(set(q["meta"]["state_display"].values()), {"down"})
        self.assertEqual(set(q["meta"]["state_display"]), set(rx.STATES))


# ------------------------------------------------------------------------------------------------ C2
class NoInjections:
    def listing(self):
        return []


def agv_line(serial, step, x=1, y=1, order="", driving=False, faulted=False, nxt=None):
    return tre.v2(serial, step + 1, step, x, y, order=order, driving=driving, faulted=faulted, nxt=nxt)


class TestLiveRobots(unittest.TestCase):
    ROBOT_KEYS = {"id", "x", "y", "raw", "state", "job", "waiting_s", "call"}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def live(self, lines, store=None):
        tre.write_gz(self.dir / "zone0-000.jsonl.gz", lines)
        spec = f"jsonl:{self.dir / 'store'}"
        return live_state.LiveState(self.dir, "run", spec, str(self.dir / "zone*-*.jsonl.gz"), NoInjections(), ttl=0, zone="0")

    def robots(self, state):
        return {r["id"]: r for r in state.snapshot()["robots"]}

    def script_a(self, n):
        """Z0-01: waits steps 0-2, moves at 3, waits again from 4."""
        rows = [("idle", 0), ("idle", 1), ("idle", 2), ("moving", 3), ("idle", 4), ("idle", 5)][:n]
        return [agv_line("Z0-01", s, x=2 + (kind == "moving"), driving=kind == "moving") for kind, s in rows]

    def test_entry_keys_raw_state_job(self):
        lines = (self.script_a(3) + [agv_line("Z0-02", 0, driving=True, order="o7"), agv_line("Z0-02", 1, driving=True, order="o7"),
                                     agv_line("Z0-03", 0, order="o9"), agv_line("Z0-04", 0, faulted=True)])
        st = self.live(lines)
        snap = st.snapshot()
        self.assertEqual(set(snap), set(live_state.STATE_KEYS))
        self.assertEqual(len(live_state.STATE_KEYS), 10)
        last = {}
        for ln in lines:
            m, _ = parse_line(ln)
            last[m.serial] = m
        for r in snap["robots"]:
            self.assertEqual(set(r), self.ROBOT_KEYS)
            m = last[r["id"]]
            self.assertEqual(r["raw"], live_state.robot_state(m))
            self.assertEqual(r["state"], live_state.display_state(r["raw"]))
            self.assertEqual(r["job"], m.order_id)
            self.assertEqual((r["x"], r["y"]), (m.x, m.y))
            if r["state"] != "waiting":
                self.assertEqual(r["waiting_s"], 0)
        by = self.robots(st)
        self.assertEqual((by["Z0-02"]["state"], by["Z0-02"]["job"]), ("moving", "o7"))
        self.assertEqual((by["Z0-03"]["raw"], by["Z0-03"]["state"]), ("loading", "working"))
        self.assertEqual((by["Z0-04"]["raw"], by["Z0-04"]["state"]), ("frozen", "down"))
        self.assertEqual(by["Z0-01"]["job"], "")

    def test_waiting_seconds_count_the_current_uninterrupted_run(self):
        expect = {1: 0, 2: 5, 3: 10, 4: 0, 5: 0, 6: 5}  # 3 waits (0,5,10), a move, then a second run restarts at 0
        for n, want in expect.items():
            with self.subTest(messages=n):
                st = self.live(self.script_a(n))
                r = self.robots(st)["Z0-01"]
                self.assertEqual(r["waiting_s"], want)
                self.assertEqual(r["state"], "moving" if n == 4 else "waiting")

    def add_call(self, st_store, robot, start, end, verdict, graded=True):
        eid = f"{robot}@{iso(start)}"
        st_store.upsert("stuck_episodes", ("run", "episode_id"), [dict(
            run="run", episode_id=eid, zone="0", robot=robot, order_id="o1", start=start, start_iso=iso(start), t_entry=start + 30,
            cell=[3, 4], cause="unknown", blocker=None, blocker_faulted_s=None, end=end, duration_s=None if end is None else end - start,
            resolution="open" if end is None else "moved", avoidable=False, avoidable_s=None, left_censored=False)])
        did, _ = decisions.record_decision(
            st_store, run="run", kind="stuck_cause", subject=robot, start_iso=iso(start), decided_at=start + 30,
            claim=dict(episode_id=eid, cause="unknown", blocker=None, blocker_faulted_s=None, cell=[3, 4]),
            rationale="x", expected=None, grade_after=start + 3600, recorded_at=1.0)
        if graded:
            decisions.stamp_grade(st_store, did, {}, None, verdict, end)
        return eid

    def test_call_joins_the_latest_episode_to_its_stuck_cause_verdict(self):
        lines = [agv_line(f"Z0-0{i}", 0) for i in range(1, 5)]
        s = JsonlStore(self.dir / "store")
        ids = dict(
            a=self.add_call(s, "Z0-01", 1000, None, None, graded=False),
            b=self.add_call(s, "Z0-02", 1000, 1100, "confirmed"),
            c_old=self.add_call(s, "Z0-03", 1000, 1100, "refuted"),
            c_new=self.add_call(s, "Z0-03", 2000, 2100, None, graded=False))
        s.close()
        st = self.live(lines)
        by = self.robots(st)
        self.assertEqual(by["Z0-01"]["call"], dict(id=ids["a"], cell=[3, 4], open=True, verdict=None))
        self.assertEqual(by["Z0-02"]["call"], dict(id=ids["b"], cell=[3, 4], open=False, verdict="confirmed"))
        self.assertEqual(by["Z0-03"]["call"], dict(id=ids["c_new"], cell=[3, 4], open=False, verdict=None))  # the later start wins
        self.assertIsNone(by["Z0-04"]["call"])
        self.assertEqual(set(st.snapshot()), set(live_state.STATE_KEYS))

    def test_call_follows_the_store_when_its_files_change(self):
        st = self.live([agv_line("Z0-01", 0)])
        self.assertIsNone(self.robots(st)["Z0-01"]["call"])
        s = JsonlStore(self.dir / "store")
        eid = self.add_call(s, "Z0-01", 1000, 1100, "refuted")
        s.close()
        self.assertEqual(self.robots(st)["Z0-01"]["call"]["id"], eid)
        self.assertEqual(self.robots(st)["Z0-01"]["call"]["verdict"], "refuted")


# ------------------------------------------------------------------------------------------------ C3
class TestExportV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = tre.build_run(cls.tmp.name)
        cls.spec = f"jsonl:{cls.dir / 'store'}"
        s = JsonlStore(cls.dir / "store")
        base = s.select("stuck_episodes", {"run": tre.RUN, "zone": "0"})[0]
        cls.want = {base["episode_id"]: None}  # the pipeline's own decision is open: ungraded -> null
        for k, (robot, verdict) in enumerate([("Z0-02", "confirmed"), ("Z0-03", "refuted"), ("Z0-04", "inconclusive"), ("Z0-02", None)]):
            start = tre.BASE + 300 + 20 * k
            eid = f"{robot}@{iso(start)}"
            s.upsert("stuck_episodes", ("run", "episode_id"), [dict(base, episode_id=eid, robot=robot, start=start, start_iso=iso(start),
                                                                 t_entry=start + 30, end=start + 50)])
            did, _ = decisions.record_decision(
                s, run=tre.RUN, kind="stuck_cause", subject=robot, start_iso=iso(start), decided_at=start + 30,
                claim=dict(episode_id=eid, cause="unknown", blocker=None, blocker_faulted_s=None, cell=[2, 2]),
                rationale="x", expected=None, grade_after=start + 3600, recorded_at=1.0)
            if verdict:
                decisions.stamp_grade(s, did, {}, None, verdict, start + 50)
            cls.want[eid] = verdict
        s.close()
        cls.payload = rx.build_payload(cls.dir, cls.spec, "0", env_runner=tre.fake_env)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_schema_and_state_display(self):
        self.assertEqual(rx.SCHEMA, "replay/3")
        m = self.payload["meta"]
        self.assertEqual(m["schema"], "replay/3")
        self.assertEqual(m["state_display"], {s: live_state.display_state(s) for s in rx.STATES})

    def test_frames_are_x_y_raw_job_and_the_job_is_the_source_messages(self):
        from fleet_analyser import hotspot
        msgs = hotspot.read_messages(str(self.dir / "zone0-*.jsonl.gz"))
        want = {}
        for m in msgs:
            step, rem = divmod(m.ts - tre.BASE, 5)
            key = (m.serial, step)
            if not rem and (key not in want or m.header_id > want[key][0]):
                want[key] = (m.header_id, m.order_id)
        robots = [r["serial"] for r in self.payload["robots"]]
        jobs_seen = set()
        for step, frame in enumerate(self.payload["frames"]):
            for i, e in enumerate(frame):
                self.assertEqual(len(e), 4)
                x, y, raw, job = e
                self.assertIn(raw, rx.STATES)
                self.assertIsInstance(job, str)
                if (robots[i], step) in want:
                    self.assertEqual(job, want[(robots[i], step)][1], (robots[i], step))
                else:  # a carried-forward entry keeps the previous job; before the first message it is ""
                    self.assertEqual(job, self.payload["frames"][step - 1][i][3] if step else "")
                jobs_seen.add(job)
        self.assertTrue(jobs_seen - {""}, "the fixture has orders")

    def test_episode_rows_carry_episode_id_and_the_graded_verdict(self):
        got = {e["episode_id"]: e["verdict"] for e in self.payload["episodes"]}
        self.assertEqual(got, self.want)
        self.assertEqual({v for v in got.values()}, {"confirmed", "refuted", "inconclusive", None})
        for e in self.payload["episodes"]:
            self.assertEqual(e["robot"], e["episode_id"].split("@")[0])

    def test_with_map_episode_rows_have_the_keys_with_null_verdict(self):
        def env(job):
            return dict(tre.fake_env(job), lines=[ln for s, ln in tre.zone0_lines()], deliveries=7, pick_rate=5.04)

        with tempfile.TemporaryDirectory() as tmp:
            cl = tre.TestWithMap().closed_loop(tmp)
            p = rx.build_payload(self.dir, self.spec, "0", str(cl), env_runner=env, closed_loop_arg=str(cl))
        eps = p["with_map"]["episodes"]
        self.assertTrue(eps)
        for e in eps:
            self.assertIn("episode_id", e)
            self.assertIsNone(e["verdict"])
        self.assertTrue(all(len(f) == 4 for fr in p["with_map"]["frames"] for f in fr))


class TestCommittedDataV2(unittest.TestCase):
    def test_committed_data_js(self):
        path = DOCS / "data.js"
        self.assertLessEqual(path.stat().st_size, 2097152)
        d = rx.read_data_js(path)
        self.assertEqual(d["meta"]["schema"], "replay/3")
        self.assertEqual(d["meta"]["state_display"], {s: live_state.display_state(s) for s in rx.STATES})
        for frames in (d["frames"], d["with_map"]["frames"]):
            self.assertEqual(len(frames), 500)
            for frame in frames:
                self.assertTrue(all(len(e) == 4 and isinstance(e[3], str) and e[2] in rx.STATES for e in frame))
        for eps in (d["episodes"], d["with_map"]["episodes"]):
            self.assertTrue(all({"episode_id", "verdict"} <= set(e) for e in eps))
        self.assertTrue(all(e["verdict"] is None for e in d["with_map"]["episodes"]))


# ------------------------------------------------------------------------------------------------ C4
LABELS = ["Robots", "Planted by us, hidden from the analyser", "Concluded by the analyser from the log alone",
          "circle = AGV, carries shelves", "square = picker, loads and unloads, drawn grey", "moving", "working", "waiting",
          "down, the robot reported an error", "bad floor cell", "breakdown moment",
          "suspected bad floor, darker = more evidence", "the ten most suspected cells, numbered 1 to 10", "stuck call, raised after 30 s of waiting with a job",
          "the call was later marked right or wrong", "show pickers in colour", "The analyser never sees the planted items.",
          "Everything under \u201cConcluded by the analyser from the log alone\u201d it worked out from the robots' messages."]
BANNED = re.compile(r"stalled|frozen|detector episode", re.I)


def strip_js_comments(js):
    """Remove // and /* */ comments, leaving string literals (and template literals) alone."""
    out, i, n = [], 0, len(js)
    while i < n:
        c = js[i]
        if c in "'\"`":
            j = i + 1
            while j < n and js[j] != c:
                j += 2 if js[j] == "\\" else 1
            out.append(js[i:j + 1])
            i = j + 1
        elif js.startswith("//", i):
            while i < n and js[i] != "\n":
                i += 1
        elif js.startswith("/*", i):
            i = js.index("*/", i) + 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def page_problems(html_text, js_text):
    """Every way the floor panel text misses the S8H wording; [] when it is all there."""
    out = []
    text = htmllib.unescape(html_text)
    for label in LABELS:
        if label not in text:
            out.append(f"index.html lacks {label!r}")
    if "placed by you" not in html_text and "placed by you" not in js_text:
        out.append("no 'placed by you' label")
    if re.search(r'\bid="legend"', html_text):
        out.append('id="legend" is still there')
    if "legend2" in html_text:
        out.append("class legend2 is still there")
    for m in BANNED.finditer(html_text):
        out.append(f"index.html contains {m.group(0)!r}")
    code = strip_js_comments(js_text)
    for m in BANNED.finditer(code):
        a, b = m.start(), m.end()
        word = m.group(0)
        quoted = a > 0 and code[a - 1] in "'\"" and code[b:b + 1] == code[a - 1] and word == word.lower()
        key = (a == 0 or not (code[a - 1].isalnum() or code[a - 1] in "_$'\"")) and re.match(r"\s*:", code[b:]) and word == word.lower()
        if not (quoted or key):
            out.append(f"replay.js has {word!r} in user-visible text: ...{code[max(0, a - 25):b + 25]!r}")
    return out


class TestPageText(unittest.TestCase):
    def test_labels_rows_and_banned_words(self):
        problems = page_problems((DOCS / "index.html").read_text(encoding="utf-8"), (DOCS / "replay.js").read_text(encoding="utf-8"))
        self.assertEqual(problems, [])

    def test_the_checker_is_red_on_the_old_wording(self):
        old_html = '<ul class="legend" id="legend"></ul><p class="legend2">detector episode</p><p>A stall</p>'
        old_js = "var STATE_TEXT = { stalled: 'stalled', frozen: 'frozen (reports an error)' };"
        problems = page_problems(old_html, old_js)
        self.assertTrue(any("lacks 'Robots'" in p for p in problems))
        self.assertTrue(any("id=\"legend\"" in p for p in problems))
        self.assertTrue(any("detector episode" in p for p in problems))
        self.assertTrue(any("'frozen'" in p and "replay.js" in p for p in problems) or any("frozen" in p for p in problems))

    def test_comment_stripping_and_literal_rules(self):
        js = "// frozen here\nvar a = { stalled: 1 }; /* stalled */ var b = 'frozen'; var c = 'it was frozen';"
        probs = page_problems("", js)
        self.assertEqual([p for p in probs if p.startswith("replay.js")].__len__(), 1)
        self.assertIn("'it was frozen'", "".join(probs))


# ------------------------------------------------------------------------------------------------ C5
class TestDemoConfig(unittest.TestCase):
    def test_default_disturb_resolves_with_breakdowns_on_agvs_only(self):
        from warehouse_rl.disturb import resolve_disturb
        cfg = resolve_disturb(live.DEFAULT_DISTURB)[1]
        b = cfg["breakdown"]
        self.assertEqual(b["agent_types"], ["agv"])
        self.assertEqual(b["rate_per_hour"], 2.0)
        self.assertEqual(list(b["duration"]), [20, 60])
        self.assertEqual(cfg["floor"], json.loads('{"floor": {"cells": 80, "p": [0.9, 0.99]}}')["floor"])

    def test_help_text_says_how_to_include_pickers(self):
        action = next(a for a in live.build_parser()._actions if a.dest == "disturb")
        self.assertIn('"agent_types": ["agv", "picker"]', action.help)
        self.assertIn('"agent_types": ["agv", "picker"]', live.__doc__)


if __name__ == "__main__":
    unittest.main()

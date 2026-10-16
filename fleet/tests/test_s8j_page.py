"""S8J-WORDING, page side: C3 (the committed data.js and the README chain), C4 (the page text, DOM-free), C4b (the Dropped / Kept
hover), C5 (the render check under a stub DOM in Node, see test_s8j_dom.py) and C6 (the banned words).

DOM-free text rules: index.html is HTML-unescaped with its tags removed, and every <span class="big"> (a number the script fills in)
is read as the token {..}; the VISIBLE_COPY / HOVER_COPY literals of replay.js are read with the tokenizer of test_s8i_page.py and
every {name} token is read as {..}. A template is found when its normalised text is a substring of the normalised page text or of
one normalised literal; the test also states in which of the two it was found."""
import copy
import html as htmllib
import json
import math
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "fleet", ROOT / "src", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import replay_export as rx  # noqa: E402
from fleet.tests import test_s8i_page as s8i  # noqa: E402
from fleet.tests.test_s8j_dom import DOCS, run_page  # noqa: E402

TOKEN = re.compile(r"\{[A-Za-z_]+\}")


def tok(s):
    """Every {name} token of a template becomes {..}; whitespace is normalised."""
    return " ".join(TOKEN.sub("{..}", s).split())


def html_page_text(html_text):
    """index.html as text: scripts and styles dropped, each <span class="big"> read as {..}, tags removed, entities decoded."""
    t = re.sub(r"<(script|style)\b.*?</\1>", " ", html_text, flags=re.S)
    t = re.sub(r'<span class="big"[^>]*>[^<]*</span>', "{..}", t)
    t = re.sub(r"<[^>]+>", " ", t)
    return " ".join(htmllib.unescape(t).split())


def table_literals(js, name):
    a, b = s8i.const_span(js, name)
    return [tok(v) for s, e, v in s8i.scan_js(js)[0] if a <= s <= b]


def read_data(path=DOCS / "data.js"):
    return rx.read_data_js(path)


HEADINGS = ["1. The floor", "2. The log", "3. What the analyser figured out", "4. What it would tell your operators",
            "5. What is it worth?"]
FUNNEL = ["Arrived", "Usable", "Kept", "Dropped"]
# (template with {..}, where it must be found)
TEMPLATES = [
    ("Its 20 strongest picks: {..} of 20 real.", "index.html"),
    ("Of all {..} spots it flagged: {..} real, {..} not.", "index.html"),
    ("every change of state and where it happened, {..} of them, plus every decision; {..}% of the bytes", "replay.js"),
    ("{..} in-between positions and repeats", "replay.js"),
    ("Rebuilding the shift from what we kept gives every robot's state at every step, and its position at every change.", "replay.js"),
    ("Every message accounted for: {..} sent, {..} read, {..} missing, checked against the sender's own count.", "replay.js"),
    ("Checked against the hidden truth. On a longer test shift the flagged cells were real {..} of {..} times; {..} of {..} were "
     "still above their area's average in the next half hour; only {..} of {..} repeated their own peak, the bar the first version used.",
     "replay.js"),
    ("Checked against the hidden truth. On a longer test shift the flagged cells were real {..} of {..} times; only {..} of {..} "
     "repeated their own peak, the bar the first version used.", "replay.js"),
    ("Short shift, few events. On a full day the list is longer and more varied.", "replay.js"),
    ("{..}% of the lost throughput recovered, {..}% with perfect knowledge", "index.html"),
    ("On mild floor damage the gain is within noise; on damage that traps robots it is measurable.", "index.html"),
    ("Robots send {..} messages a second.", "replay.js"),
    ("We can read {..} a second, so a fleet {..}x larger would still keep up.", "replay.js"),
    ("{..} messages, {..} of them deliberately broken so you can see what the extractor does with bad lines.", "replay.js"),
]
BAR_LABELS = ["Bad floor, no map", "Bad floor, the analyser's map", "Bad floor, perfect knowledge", "Clean floor"]


class TestPageCopy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (DOCS / "index.html").read_text(encoding="utf-8")
        cls.js = (DOCS / "replay.js").read_text(encoding="utf-8")
        cls.css = (DOCS / "replay.css").read_text(encoding="utf-8")
        cls.page = html_page_text(cls.html)
        cls.visible = table_literals(cls.js, "VISIBLE_COPY")
        cls.hover = table_literals(cls.js, "HOVER_COPY")

    def test_the_five_headings_in_order_and_numbered_consistently(self):
        found = re.findall(r"<h2[^>]*>([^<]*)</h2>", self.html)
        self.assertEqual(found, HEADINGS)
        self.assertEqual([h.split(".")[0] for h in found], ["1", "2", "3", "4", "5"])
        self.assertEqual(re.findall(r'aria-labelledby="(h-[a-z]+)"', self.html), ["h-floor", "h-log", "h-ana", "h-les", "h-worth"])

    def test_the_four_funnel_boxes(self):
        log = s8i.panel(self.html, "h-log")
        self.assertEqual(re.findall(r'<div class="fbox"[^>]*>\s*<h3>([^<]*)</h3>', log), FUNNEL)

    def test_every_template_is_on_the_page_and_in_the_stated_place(self):
        where = {}
        for template, expect in TEMPLATES:
            places = []
            if tok(template) in self.page:
                places.append("index.html")
            if any(tok(template) in v for v in self.visible):
                places.append("replay.js")
            where[template] = places
            self.assertEqual(places, [expect], template)
        # the templates sit in the same order as the panels they belong to
        self.assertLess(self.page.index("Its 20 strongest picks"), self.page.index("5. What is it worth?"))

    def test_the_four_bar_labels(self):
        a, b = s8i.const_span(self.js, "VISIBLE_COPY")
        body = self.js[a:b]
        m = re.search(r"\bworth\s*:\s*\{(.*?)\n    \}", body, re.S)
        labels = [v for _, _, v in s8i.scan_js(m.group(1))[0] if v in BAR_LABELS]
        self.assertEqual(sorted(labels), sorted(BAR_LABELS))

    def test_the_coverage_bar_and_the_old_copy_are_gone(self):
        for name, text in (("index.html", self.html), ("replay.js", self.js), ("replay.css", self.css)):
            self.assertNotIn("covbar", text, name)
            self.assertNotIn("covlabel", text, name)
        for gone in ("of the time", "payoff", "Routing payoff", "Every message is read and counted",
                     "a 2% raw sample</", "carry_lessons", "lessonCap:"):
            self.assertNotIn(gone, self.page + " " + self.js, gone)
        self.assertNotIn('id="payoff"', self.html)
        self.assertEqual([t for t in s8i.big_texts(self.html) if re.search(r"[0-9]", t)], [])

    def test_no_copy_says_the_map_or_the_lessons_come_from_the_kept_data_only(self):
        # fleet/costmap.py:122 reads the raw zone files; fleet/lessons.py reads the stalls table costmap writes
        pattern = re.compile(r"(\bmap\b|lesson)[^.;]*\b(built|made|drawn|written|computed|worked out|found)\b[^.;]*\bkept\b|"
                             r"\bkept\b[^.;]*\b(map|lessons)\b", re.I)
        for text in [self.page] + self.visible + self.hover:
            self.assertIsNone(pattern.search(text), text)

    def test_the_kept_and_dropped_hover_say_a_two_percent_raw_sample_is_also_kept(self):
        a, b = s8i.const_span(self.js, "HOVER_COPY")
        hover = self.js[a:b]
        for name in ("kept", "dropped"):
            m = re.search(rf"\n    {name}: '((?:[^'\\]|\\.)*)'", hover)
            self.assertIsNotNone(m, name)
            self.assertIn("2% raw sample", m.group(1), name)
        self.assertIn("not a claim that they were deleted", hover)

    def test_the_new_strings_match_no_banned_word_and_the_regex_is_the_s8i_one(self):
        self.assertEqual(s8i.BANNED.pattern, r"\b(cost|publish|grade|horizon|stream|rank|stall|episode|zone|coverage)\w*")
        self.assertEqual(s8i.BANNED.flags & re.I, re.I)
        for template, _ in TEMPLATES:
            self.assertIsNone(s8i.BANNED.search(template), template)
        for label in BAR_LABELS + HEADINGS + FUNNEL:
            self.assertIsNone(s8i.BANNED.search(label), label)
        self.assertEqual(s8i.banned_in_html(self.html), [])
        self.assertEqual(s8i.banned_in_js(self.js), [])


class TestDocsAndReadme(unittest.TestCase):
    def test_readme_chain(self):
        lines = (DOCS / "README.md").read_text(encoding="utf-8").splitlines()
        text = "\n".join(lines)
        self.assertNotIn("--carry-lessons", text)
        self.assertNotIn("carry_lessons", text)
        cmd = "fleet/lessons.py --run s8i-demo-noise --store jsonl:$R/store --once --window-h 0.5"
        at = {k: [i for i, ln in enumerate(lines) if k in ln and ln.lstrip().startswith(".venv/bin/python")] for k in
              ("fleet/emit.py", "fleet/ingest.py", "fleet/costmap.py", cmd, "fleet/grade.py", "fleet/hotspot_score.py",
               "fleet/replay_export.py")}
        for k, v in at.items():
            self.assertEqual(len(v), 1, k)
        order = [at[k][0] for k in ("fleet/emit.py", "fleet/ingest.py", "fleet/costmap.py", cmd, "fleet/grade.py",
                                    "fleet/hotspot_score.py", "fleet/replay_export.py")]
        self.assertEqual(order, sorted(order))
        export = lines[at["fleet/replay_export.py"][0]]
        self.assertIn("--lessons-long results/fleet/hotspot_s8e-long-w0.5.json", export)
        for arm in rx.WORTH_ARMS:
            self.assertIn(f"--sticky-{arm.replace('_', '-')} results/closed_loop_sticky/{arm}/*.json", export)

    def test_demo_md_mentions_the_noise_flag_and_the_fifth_panel(self):
        demo = (ROOT / "docs" / "DEMO.md").read_text(encoding="utf-8")
        self.assertIn("--demo-noise", demo)
        self.assertRegex(demo, r"(?i)fifth panel")

    def test_only_declared_docs_changed_is_checked_on_the_diff_not_here(self):
        self.assertTrue((ROOT / "README.md").is_file())  # README.md and docs/SCOPE.md are untouched (verified on the diff)


# ------------------------------------------------------------------------------------------------ committed data.js (C3)
class TestCommittedData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = read_data()

    def test_schema_size_run(self):
        self.assertEqual(self.d["meta"]["schema"], "replay/4")
        self.assertLessEqual((DOCS / "data.js").stat().st_size, 2097152)
        self.assertEqual(self.d["meta"]["run"], "s8i-demo-noise")
        self.assertNotIn("carry_lessons", self.d["meta"]["source"])
        self.assertNotIn("carry_lessons_run", self.d["meta"]["source"])

    def test_lessons_are_this_runs_own_and_every_hot_cell_has_a_truth_verdict(self):
        ls = self.d["lessons"]
        self.assertGreater(len(ls), 0)
        for l in ls:
            self.assertEqual(l.get("run", self.d["meta"]["run"]), self.d["meta"]["run"])
            self.assertEqual(l["zone"], self.d["meta"]["zone"])
            if l["lesson_kind"] == "hot_cell":
                self.assertIn(l["truth"], ("hit", "false_alarm"))
        rx.assert_single_run(self.d)

    @unittest.skipUnless(sys.platform == "darwin", "env numbers are platform-dependent (pyastar2d tie-breaks); data.js was "
                                                   "made on macOS, so the rebuilt lessons only match there")
    def test_lessons_hold_exactly_the_lesson_decisions_of_the_run_in_the_store(self):
        """Runs the docs/replay/README.md chain up to grade.py into a temp dir (fleet/data is untracked, and a stale copy there
        proves nothing), then compares the exporter's lessons for that store with the committed data.js."""
        import subprocess
        from fleet_analyser.store import JsonlStore
        py = sys.executable
        with tempfile.TemporaryDirectory() as tmp:
            R = Path(tmp) / "s8i-demo-noise"
            R.mkdir()
            store = f"jsonl:{R}/store"
            steps = [
                ["fleet/emit.py", "--zones", "1", "--steps", "500", "--seed-base", "0", "--env",
                 "tarware-medium-8agvs-4pickers-globalobs-v1", "--disturb", '{"floor": {"cells": 80, "p": [0.3, 0.7]}}',
                 "--demo", "--demo-noise", "--control-file", f"{R}/control.jsonl", "--dir", str(R), "--workers", "1"],
                ["fleet/ingest.py", "--glob", f"{R}/*.jsonl.gz", "--store", store, "--once"],
                ["fleet/costmap.py", "--glob", f"{R}/*.jsonl.gz", "--store", store, "--publish-every", "1250",
                 "--horizon-s", "1245", "--out", f"{R}/costmap.json"],
                ["fleet/lessons.py", "--run", "s8i-demo-noise", "--store", store, "--once", "--window-h", "0.5"],
                ["fleet/grade.py", "--run", "s8i-demo-noise", "--store", store, "--once", "--truth", f"{R}/truth.json"],
            ]
            readme = (DOCS / "README.md").read_text(encoding="utf-8")
            for args in steps:  # every step here is a line of the README chain (same script, same flags)
                self.assertIn(" ".join(a if not a.startswith(str(R)) else a.replace(str(R), "$R") for a in args[:1]), readme)
                r = subprocess.run([py] + args, cwd=ROOT, capture_output=True, text=True, timeout=600)
                self.assertEqual(r.returncode, 0, f"{args[0]}: {r.stderr[-1500:]}")
            st = JsonlStore(R / "store")
            rows = st.select("decisions", {"run": "s8i-demo-noise", "kind": "lesson"})
            built = rx.build_lessons(st, "s8i-demo-noise", self.d["meta"]["t0_ts"], self.d["meta"]["step_seconds"],
                                     zone=self.d["meta"]["zone"])
            st.close()
        self.assertGreaterEqual(len(rows), 1)
        self.assertEqual(built, self.d["lessons"])
        for les in self.d["lessons"]:
            if les["lesson_kind"] == "hot_cell":
                self.assertIn(les["truth"], ("hit", "false_alarm"))

    def test_run_constants_numbers(self):
        rc = self.d["run_constants"]
        ll = rc["lessons_long"]
        self.assertEqual(ll["source"], "results/fleet/hotspot_s8e-long-w0.5.json")
        self.assertEqual((ll["truth_hit"], ll["truth_n"], ll["held"], ll["graded"]), (27, 27, 9, 31))
        summary = json.loads((ROOT / "results" / "closed_loop_sticky" / "summary.json").read_text())
        self.assertAlmostEqual(rc["worth"]["map_share"], summary["arms"]["map_a32"]["share_of_floor_loss_recovered"]["share"],
                               delta=1e-9)
        self.assertEqual((rc["header"]["msgs"], rc["header"]["noise"]), (6090, 90))
        self.assertEqual((rc["audit"]["sent"], rc["audit"]["read"], rc["audit"]["missing"]), (6000, 6000, 0))
        self.assertGreater(self.d["extractor"]["totals"]["missing_messages"], 0)  # the jump, which is not a missing message
        k = rc["kept"]
        self.assertEqual(k["n_changes"] + k["n_repeats"], self.d["extractor"]["totals"]["accepted"])
        for arm in rx.WORTH_ARMS:
            src = next(b["source"] for b in rc["worth"]["bars"] if b["key"] == arm)
            self.assertRegex(src, rf"^results/closed_loop_sticky/{arm}/[^/]+\.json$")
            self.assertTrue((ROOT / src).is_file())
        for key in ("speed", "lessons_long", "audit", "header", "worth"):
            self.assertTrue(rc[key]["source"])

    def test_the_hotspot_file_carries_the_same_run_lesson_truth_count(self):
        """C3c's key-level diff against master is in the PR body (no unittest refers to a git ref); this checks the one
        lesson-derived key the new chain adds, against the committed data.js."""
        doc = json.loads((ROOT / "results" / "fleet" / "hotspot_s8i-demo-noise.json").read_text())
        self.assertEqual(doc["run"], "s8i-demo-noise")
        n_hit = sum(1 for l in self.d["lessons"] if l["truth"] == "hit")
        self.assertEqual(doc["grading_counts"]["lesson_truth"], {"hit": n_hit})


# ------------------------------------------------------------------------------------------------ render check (C5)
def fmt(n):
    return f"{n:,}"


def pct_num(x):
    v = x * 100
    return str(int(math.floor(v + 0.5))) if v == 0 or v >= 10 else f"{v:.1f}"


def rate_num(x):
    return f"{x:.1f}" if x < 10 else fmt(int(math.floor(x + 0.5)))


def expected_panel3(d, step):
    pubs = [p for p in d["publishes"] if p["step"] <= step]
    if not pubs:
        return None
    p = pubs[-1]
    costs = [c[1] for c in p["cells"]]
    assert costs == sorted(costs, reverse=True)
    obst = {o["cell"] for o in d["obstacles"]}
    g = d["grades"]["per_publish"][d["publishes"].index(p)]
    return dict(top=sum(1 for c in p["cells"][:20] if c[0] in obst), calls=g["forecasts"], hits=g["truth"]["hit"],
                wrong=g["truth"]["false_alarm"])


IDS = ["subtitle", "noiseline", "big-arrived", "big-usable", "big-kept", "kept-unit", "big-dropped", "dropped-unit", "rebuildsentence",
       "auditline", "speed-robots", "speed-read", "s-right", "s-found", "s-checks", "s-worth", "worthlabel", "lessonshort", "lessonlong",
       "panel-worth", "big-mapshare", "big-oracleshare"]


def text_of(snap, key):
    return " ".join(snap["ids"][key]["text"].split())


class TestRender(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = read_data()
        cls.runs = None

    def scenario(self, steps, **extra):
        return dict(steps=steps, ids=IDS, hover_ids=["f-kept", "f-dropped", "f-arrived", "auditline", "s-worth", "lessonlong"], **extra)

    def write(self, tmp, d):
        p = Path(tmp) / "data.js"
        p.write_text("window.REPLAY = " + json.dumps(d, separators=(",", ":")) + ";\n", encoding="utf-8")
        return p

    # -- the committed data
    def test_the_committed_page_renders_the_payload_values_at_steps_0_250_499(self):
        d = self.d
        rc = d["run_constants"]
        out = run_page(self, self.scenario([0, 250, 499]), DOCS / "data.js")
        self.assertEqual([r["step"] for r in out], [0, 250, 499])
        for r in out:
            snap, step = r["snap"], r["step"]
            e = expected_panel3(d, step)
            if e is None:
                self.assertEqual(text_of(snap, "s-right"), "Its 20 strongest picks: — of 20 real.")
                self.assertEqual(text_of(snap, "s-checks"), "Of all — spots it flagged: — real, — not.")
            else:
                self.assertEqual(text_of(snap, "s-right"), f"Its 20 strongest picks: {e['top']} of 20 real.")
                self.assertEqual(text_of(snap, "s-checks"), f"Of all {e['calls']} spots it flagged: {e['hits']} real, {e['wrong']} not.")
        last = out[-1]["snap"]
        e = expected_panel3(d, 499)
        self.assertEqual((e["top"], e["calls"], e["hits"], e["wrong"]), (20, 60, 42, 18))
        self.assertEqual(text_of(last, "s-right"), "Its 20 strongest picks: 20 of 20 real.")
        self.assertEqual(text_of(last, "s-checks"), "Of all 60 spots it flagged: 42 real, 18 not.")
        a = rc["audit"]
        self.assertEqual(text_of(last, "auditline"), f"Every message accounted for: {fmt(a['sent'])} sent, {fmt(a['read'])} read, "
                         f"{a['missing']} missing, checked against the sender's own count.")
        self.assertEqual(text_of(last, "auditline"), "Every message accounted for: 6,000 sent, 6,000 read, 0 missing, checked "
                         "against the sender's own count.")
        h = rc["header"]
        self.assertRegex(text_of(last, "noiseline"), rf"^(6,090|6090) messages, {h['noise']} of them deliberately broken ")
        self.assertEqual(text_of(last, "noiseline"), f"{fmt(h['msgs'])} messages, {h['noise']} of them deliberately broken so you can "
                         "see what the extractor does with bad lines.")
        # the funnel
        k = rc["kept"]
        self.assertEqual(text_of(last, "big-arrived"), fmt(h["msgs"]))
        self.assertEqual(text_of(last, "big-usable"), fmt(a["read"]))
        self.assertEqual(text_of(last, "big-kept"), fmt(k["n_changes"]))
        self.assertEqual(text_of(last, "kept-unit"), f"every change of state and where it happened, {fmt(k['n_changes'])} of them, "
                         f"plus every decision; {k['kept_pct']:.1f}% of the bytes")
        self.assertEqual(text_of(last, "big-dropped"), fmt(k["n_repeats"]))
        self.assertEqual(text_of(last, "dropped-unit"), f"{fmt(k['n_repeats'])} in-between positions and repeats")
        self.assertIn("2% raw sample", last["hovers"]["f-dropped"])
        self.assertIn("2% raw sample", last["hovers"]["f-kept"])
        # running numbers: monotone, equal to the series before the last step
        arrived = [int(text_of(r["snap"], "big-arrived").replace(",", "")) for r in out]
        self.assertEqual(arrived, [self.d["extractor"]["series"]["messages"][s] for s in (0, 250)] + [h["msgs"]])
        kept_n = [int(text_of(r["snap"], "big-kept").replace(",", "")) for r in out]
        self.assertEqual(kept_n, [k["changes_by_step"][0], k["changes_by_step"][250], k["n_changes"]])
        # speed
        s = rc["speed"]
        self.assertEqual(text_of(last, "speed-robots"), f"Robots send {rate_num(s['robot_rate'])} messages a second.")
        self.assertEqual(text_of(last, "speed-read"), f"We can read {rate_num(s['ingest_rate'])} a second, so a fleet "
                         f"{fmt(s['ratio'])}x larger would still keep up.")
        # lessons footnote, panel 5
        ll = rc["lessons_long"]
        self.assertEqual(text_of(last, "lessonlong"), f"Checked against the hidden truth. On a longer test shift the flagged cells were "
                         f"real {ll['truth_hit']} of {ll['truth_n']} times; {ll['persist_held']} of {ll['persist_graded']} were still above "
                         f"their area's average in the next half hour; only {ll['held']} of {ll['graded']} repeated their own peak, "
                         "the bar the first version used.")
        self.assertEqual(text_of(last, "lessonlong"), "Checked against the hidden truth. On a longer test shift the flagged cells were "
                         "real 27 of 27 times; 18 of 25 were still above their area's average in the next half hour; only 9 of 31 "
                         "repeated their own peak, the bar the first version used.")
        w = rc["worth"]
        self.assertEqual(text_of(last, "big-mapshare"), pct_num(w["map_share"]))
        self.assertEqual(text_of(last, "big-oracleshare"), pct_num(w["oracle_share"]))
        self.assertEqual(text_of(last, "s-worth"), f"{pct_num(w['map_share'])}% of the lost throughput recovered, "
                         f"{pct_num(w['oracle_share'])}% with perfect knowledge")
        self.assertEqual([b["key"] for b in last["bars"]], list(rx.WORTH_ARMS))
        for bar, src in zip(last["bars"], w["bars"]):
            self.assertEqual(bar["value"], f"{src['mean']:.1f} lines an hour, likely range {src['ci95_low']:.1f} to {src['ci95_high']:.1f}")
        self.assertEqual([b["label"] for b in last["bars"]], BAR_LABELS)
        self.assertEqual(text_of(last, "worthlabel"), "The bars come from a 30-seed simulator test on a harder floor, one that traps "
                         "robots, not from the shift in panel 1.")

    def test_the_lessons_feed_at_step_499_is_one_hot_cell_lesson_with_a_hit_mark(self):
        out = run_page(self, self.scenario([0, 250, 499]), DOCS / "data.js")
        self.assertEqual([len(r["snap"]["lessons"]) for r in out], [0, 0, 1])
        item = out[-1]["snap"]["lessons"][0]
        self.assertEqual(item["text"], "One spot on the floor keeps holding robots up. Worth a look.")
        self.assertEqual([t["truth"] for t in item["truth"]], ["hit"])
        self.assertEqual(self.d["lessons"][0]["lesson_kind"], "hot_cell")

    # -- synthetic payloads
    def distinct(self):
        d = copy.deepcopy(self.d)
        rc = d["run_constants"]
        rc["header"].update(msgs=7001, noise=77)
        rc["audit"].update(sent=6005, read=6002, missing=3)
        rc["kept"].update(n_changes=1303, n_repeats=4701, kept_pct=12.3)
        rc["speed"].update(robot_rate=3.7, ingest_rate=1234.6, ratio=271)  # not floor(1234.6 / 3.7) = 333: a page that recomputes fails
        rc["lessons_long"].update(truth_hit=5, truth_n=6, held=7, graded=8, persist_held=3, persist_graded=4)
        rc["worth"].update(map_share=0.237, oracle_share=0.456)
        for i, (b, m) in enumerate(zip(rc["worth"]["bars"], (11.1, 22.2, 33.3, 44.4))):
            b.update(mean=m, ci95_low=m - 1.1 - i * 0.1, ci95_high=m + 1.3 + i * 0.1)
        return d

    def _no_persist_text(self, mutate):
        d = copy.deepcopy(self.d)
        mutate(d["run_constants"]["lessons_long"])
        ll = d["run_constants"]["lessons_long"]
        with tempfile.TemporaryDirectory() as tmp:
            out = run_page(self, self.scenario([499]), self.write(tmp, d))
        text = text_of(out[0]["snap"], "lessonlong")
        self.assertEqual(text, "Checked against the hidden truth. On a longer test shift the flagged cells were "
                         f"real {ll['truth_hit']} of {ll['truth_n']} times; only {ll['held']} of {ll['graded']} repeated their own "
                         "peak, the bar the first version used.")
        self.assertNotIn("null", text)
        self.assertNotIn("undefined", text)

    def test_footnote_without_persist_numbers_uses_the_short_sentence_when_null(self):
        self._no_persist_text(lambda ll: ll.update(persist_held=None, persist_graded=None))

    def test_footnote_without_persist_numbers_uses_the_short_sentence_when_absent(self):
        self._no_persist_text(lambda ll: (ll.pop("persist_held"), ll.pop("persist_graded")))

    def test_each_rendered_element_shows_its_own_field_so_a_swap_fails(self):
        d = self.distinct()
        rc = d["run_constants"]
        values = [rc["header"]["msgs"], rc["audit"]["read"], rc["kept"]["n_changes"], rc["kept"]["n_repeats"]]
        self.assertEqual(len(set(values)), 4)
        s = rc["speed"]
        self.assertEqual(len({s["robot_rate"], s["ingest_rate"], s["ratio"]}), 3)
        self.assertEqual(len({b["mean"] for b in rc["worth"]["bars"]}), 4)
        with tempfile.TemporaryDirectory() as tmp:
            out = run_page(self, self.scenario([499]), self.write(tmp, d))
        snap = out[0]["snap"]
        self.assertEqual(text_of(snap, "big-arrived"), "7,001")
        self.assertEqual(text_of(snap, "big-usable"), "6,002")
        self.assertEqual(text_of(snap, "big-kept"), "1,303")
        self.assertEqual(text_of(snap, "big-dropped"), "4,701")
        self.assertIn("12.3% of the bytes", text_of(snap, "kept-unit"))
        self.assertIn("1,303 of them", text_of(snap, "kept-unit"))
        self.assertTrue(text_of(snap, "dropped-unit").startswith("4,701 in-between"))
        self.assertEqual(text_of(snap, "noiseline"), "7,001 messages, 77 of them deliberately broken so you can see what the extractor "
                         "does with bad lines.")
        self.assertEqual(text_of(snap, "auditline"), "Every message accounted for: 6,005 sent, 6,002 read, 3 missing, checked against "
                         "the sender's own count.")
        self.assertEqual(text_of(snap, "speed-robots"), "Robots send 3.7 messages a second.")
        self.assertEqual(text_of(snap, "speed-read"), "We can read 1,235 a second, so a fleet 271x larger would still keep up.")
        self.assertEqual(text_of(snap, "lessonlong"), "Checked against the hidden truth. On a longer test shift the flagged cells were real 5 of 6 "
                         "times; 3 of 4 were still above their area's average in the next half hour; only 7 of 8 repeated their own "
                         "peak, the bar the first version used.")
        self.assertEqual(text_of(snap, "big-mapshare"), "24")
        self.assertEqual(text_of(snap, "big-oracleshare"), "46")
        by_key = {b["key"]: b["value"] for b in snap["bars"]}
        for b in rc["worth"]["bars"]:
            self.assertEqual(by_key[b["key"]], f"{b['mean']:.1f} lines an hour, likely range {b['ci95_low']:.1f} to {b['ci95_high']:.1f}")
        self.assertEqual(len(set(by_key.values())), 4)

    def lessons_payload(self, rows):
        d = copy.deepcopy(self.d)
        base = d["lessons"][0]
        d["lessons"] = [dict(base, lesson_kind=k, decided_at_step=at, truth=tr, graded_at_step=None, verdict=None,
                             text=f"{k}@{at}") for k, at, tr in rows]
        return d

    def feed(self, d, steps):
        with tempfile.TemporaryDirectory() as tmp:
            out = run_page(self, self.scenario(steps), self.write(tmp, d))
        return [[(i["key"], (i["truth"][0]["truth"] if i["truth"] else None), i["text"]) for i in r["snap"]["lessons"]] for r in out]

    def test_the_feed_shows_the_newest_lesson_per_kind_newest_first_with_a_truth_mark(self):
        # two hot_cell lessons (steps 100 and 300) and one hot_robot lesson (step 200); the order is dedup by kind, then newest first
        d = self.lessons_payload([("hot_cell", 100, "hit"), ("hot_robot", 200, None), ("hot_cell", 300, "false_alarm")])
        f50, f150, f250, f499 = self.feed(d, [50, 150, 250, 499])
        self.assertEqual(f50, [])
        self.assertEqual([x[2] for x in f150], ["One spot on the floor keeps holding robots up. Worth a look."])
        self.assertEqual([(x[0], x[1]) for x in f150], [("100:0", "hit")])
        self.assertEqual([x[0] for x in f250], ["200:1", "100:0"])  # hot_robot (200) before hot_cell (100)
        self.assertEqual([x[1] for x in f250], [None, "hit"])
        self.assertEqual([x[0] for x in f499], ["300:2", "200:1"])  # the second hot_cell replaces the first: two items
        self.assertEqual([x[1] for x in f499], ["false_alarm", None])
        self.assertEqual(len(f499), 2)

    def test_a_tie_in_decided_at_goes_to_the_later_lesson_in_the_file(self):
        d = self.lessons_payload([("hot_cell", 300, "hit"), ("hot_robot", 300, None), ("hot_cell", 300, "false_alarm")])
        (f,) = self.feed(d, [499])
        self.assertEqual([x[0] for x in f], ["300:2", "300:1"])
        self.assertEqual([x[1] for x in f], ["false_alarm", None])

    # -- live mode
    def test_live_mode_renders_no_undefined_nan_or_null(self):
        grid = dict(width=6, height=4, highway=["111111"] * 4, goals=[[0, 3]], agvs=2)
        state = dict(
            step=40, sim_time="2026-01-01T00:03:20Z",
            robots=[dict(id="Z0-01", x=1, y=1, raw="moving", state="moving", job="o1", waiting_s=0, call=None),
                    dict(id="Z0-03", x=2, y=2, raw="stuck", state="waiting", job="o2", waiting_s=35,
                         call=dict(id="e1", cell=[2, 2], open=True, verdict=None))],
            ledger=dict(pgid=1, run="live", emit_status="running", messages_emitted=480, expected_messages=None, steps_done=41,
                        injections_applied=0, injections_posted=0, messages_parsed=470, messages_rejected=6, duplicates=4,
                        bytes_read=250000, bytes_emitted_uncompressed=260000, messages_per_s=47.9),
            costmap=dict(cells={"2,2": 0.9, "3,1": 0.4}, generated_at="2026-01-01T00:03:00Z"),
            top10=[dict(cell="2,2", cost=0.9), dict(cell="3,1", cost=0.4)],
            lessons=[dict(id="l1", text="t", subject="Z0:cell 2,2", zone="0", lesson_kind="hot_cell", confidence=0.5,
                          decided_at="2026-01-01T00:02:00Z", state="pending")],
            grades=dict(lessons=dict(ok=0, off=0, pending=1, not_gradable=0), forecasts=dict(ok=1, off=0, pending=3, not_gradable=0)),
            injections=[], truth=None)
        scenario = dict(search="?live=http://127.0.0.1:8765", ids=IDS + ["big-right", "big-calls", "big-hits", "big-wrong"],
                        fetch={"/grid": grid, "/state": state})
        out = run_page(self, scenario)
        snap = out[0]["snap"]
        shown = " | ".join(snap["shown"])
        for bad in ("undefined", "NaN", "null"):
            self.assertNotIn(bad, shown)
            for key in ("subtitle", "noiseline", "auditline", "speed-robots", "speed-read", "panel-worth", "s-worth"):
                self.assertNotIn(bad, snap["ids"][key]["text"], key)
        # live mode shows its own numbers and hides the replay constants
        self.assertEqual(text_of(snap, "big-arrived"), "480")
        self.assertEqual(text_of(snap, "big-usable"), "470")
        for key in ("noiseline", "auditline", "speed-robots", "speed-read", "panel-worth", "rebuildsentence", "lessonshort"):
            self.assertTrue(snap["ids"][key]["hidden"], key)
        self.assertEqual(text_of(snap, "big-kept"), "—")
        self.assertEqual(text_of(snap, "big-dropped"), "—")


# ------------------------------------------------------------------------------------------------ S8N-PAGE-NITS (replay: 6, 7, 8)
def css_rules(css):
    """[(context, selector, body)]: context is None at top level, else the normalised @media condition of the block."""
    css = re.sub(r"/\*.*?\*/", " ", css, flags=re.S)
    out, i = [], 0
    while i < len(css):
        j = css.find("{", i)
        if j < 0:
            break
        head = " ".join(css[i:j].split())
        depth, k = 1, j + 1
        while depth:
            depth += {"{": 1, "}": -1}.get(css[k], 0)
            k += 1
        body = css[j + 1:k - 1]
        if head.startswith("@media"):
            for ctx, sel, b in css_rules(body):
                out.append((" ".join(head[len("@media"):].split()), sel, b))
        else:
            out.append((None, head, " ".join(body.split())))
        i = k
    return out


class TestS8NReplay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = read_data()
        cls.rules = css_rules((DOCS / "replay.css").read_text(encoding="utf-8"))

    def rule(self, selector, needle):
        return [ctx for ctx, sel, body in self.rules if sel == selector and needle in body]

    # nit 6: the funnel stacks at 900px, not at 1400px
    def test_the_funnel_stacking_rules_sit_only_under_max_width_900(self):
        for selector, needle in ((".funnel", "grid-template-columns: 1fr;"), (".farrow", "flex-direction: row"),
                                 (".farrow .glyph", "rotate(90deg)")):
            self.assertEqual(self.rule(selector, needle), ["(max-width: 900px)"], selector)

    def test_no_funnel_rule_is_left_in_a_1400_block_and_the_wide_layout_is_side_by_side(self):
        for ctx, sel, body in self.rules:
            if ctx and "1400" in ctx:
                self.assertIsNone(re.search(r"\.(funnel|farrow)\b", sel), (ctx, sel))
        top = {sel: body for ctx, sel, body in self.rules if ctx is None}
        self.assertEqual(top[".funnel"].count("auto"), 3)  # seven columns: box arrow box arrow box arrow box
        self.assertIn("flex-direction: column", top[".farrow"])

    def test_the_900_to_1400_band_has_its_overflow_handling_outside_any_1400_block(self):
        self.assertTrue(self.rule(".funnel > .fbox", "min-width: 0"))
        self.assertEqual(self.rule(".fbox .big", "clamp("), ["(min-width: 901px)"])
        self.assertTrue(self.rule(".fbox .big", "overflow-wrap: anywhere"))

    # nit 7: the rows of panel 5 are named groups
    def test_each_worth_bar_is_a_group_named_by_its_visible_arm_label(self):
        out = run_page(self, dict(steps=[499], ids=IDS), DOCS / "data.js")
        bars = out[-1]["snap"]["bars"]
        rows = [b for b in bars if "wbar" in b["cls"].split()]
        self.assertEqual(len(rows), 4)
        self.assertEqual(len([b for b in bars if b["role"] == "group"]), len(rows))
        for b in rows:
            self.assertEqual(b["role"], "group", b["key"])
            self.assertEqual(b["aria"], b["label"], b["key"])
        self.assertEqual([b["aria"] for b in rows], BAR_LABELS)

    # nit 8: K = min(20, cells of the rendered map)
    def cut_to_12(self):
        d = copy.deepcopy(self.d)
        for p in d["publishes"]:
            p["cells"] = p["cells"][:12]
        last = d["publishes"][-1]["cells"]
        planted = [o["cell"] for o in d["obstacles"]]
        drop = [c[0] for c in last if c[0] in planted][:3]
        d["obstacles"] = [o for o in d["obstacles"] if o["cell"] not in drop]
        n = sum(1 for c in last if c[0] in {o["cell"] for o in d["obstacles"]})
        return d, n

    def test_a_map_cut_to_12_cells_reads_its_12_strongest_picks_n_of_12_real(self):
        d, n = self.cut_to_12()
        self.assertTrue(0 < n < 12, n)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.js"
            path.write_text("window.REPLAY = " + json.dumps(d, separators=(",", ":")) + ";\n", encoding="utf-8")
            out = run_page(self, dict(steps=[0, 499], ids=IDS + ["detail-notes", "grades"], hover_ids=["s-right"]), path)
        self.assertEqual(text_of(out[0]["snap"], "s-right"), "Its 20 strongest picks: — of 20 real.")
        last = out[-1]["snap"]
        self.assertEqual(text_of(last, "s-right"), f"Its 12 strongest picks: {n} of 12 real.")
        self.assertIn("Of the 12 cells flagged most strongly", last["hovers"]["s-right"])
        self.assertIn("({}/12)".format(n), last["hovers"]["s-right"])
        self.assertNotIn("/20)", last["hovers"]["s-right"])
        self.assertIn("top-20 hit rate", text_of(last, "grades"))  # the stored field is precision_at_20 (hits / 20)
        self.assertIn(f"({n}/12)", text_of(last, "grades"))
        self.assertIn("of the 12 most-flagged cells", text_of(last, "detail-notes"))

    def test_the_committed_data_keeps_k_at_20(self):
        out = run_page(self, dict(steps=[0, 499], ids=IDS + ["detail-notes", "grades", "big-k-lead", "big-k-tail"], hover_ids=["s-right"]),
                       DOCS / "data.js")
        last = out[-1]["snap"]
        for snap in (out[0]["snap"], last):  # the two K slots are filled by the page, and read 20 on the committed data
            self.assertEqual((text_of(snap, "big-k-lead"), text_of(snap, "big-k-tail")), ("20", "20"))
        self.assertEqual(text_of(out[0]["snap"], "s-right"), "Its 20 strongest picks: — of 20 real.")
        self.assertEqual(text_of(last, "s-right"), "Its 20 strongest picks: 20 of 20 real.")
        self.assertIn("Of the 20 cells flagged most strongly", last["hovers"]["s-right"])
        self.assertIn("of the 20 most-flagged cells", text_of(last, "detail-notes"))
        self.assertIn("top-20 hit rate", text_of(last, "grades"))
        self.assertIn("(20/20)", text_of(last, "grades"))

    def test_live_mode_reads_k_from_the_costmap_when_it_has_fewer_than_20_cells(self):
        grid = dict(width=6, height=4, highway=["111111"] * 4, goals=[[0, 3]], agvs=2)
        state = dict(
            step=40, sim_time="2026-01-01T00:03:20Z",
            robots=[dict(id="Z0-01", x=1, y=1, raw="moving", state="moving", job="o1", waiting_s=0, call=None)],
            ledger=dict(pgid=1, run="live", emit_status="running", messages_emitted=480, expected_messages=None, steps_done=41,
                        injections_applied=0, injections_posted=0, messages_parsed=470, messages_rejected=6, duplicates=4,
                        bytes_read=250000, bytes_emitted_uncompressed=260000, messages_per_s=47.9),
            costmap=dict(cells={"2,2": 0.9, "3,1": 0.4}, generated_at="2026-01-01T00:03:00Z"),
            top10=[dict(cell="2,2", cost=0.9), dict(cell="3,1", cost=0.4)], lessons=[],
            grades=dict(lessons=dict(ok=0, off=0, pending=0, not_gradable=0), forecasts=dict(ok=1, off=0, pending=3, not_gradable=0)),
            injections=[], truth=dict(scheduled={"2,2": 0.5}, injected={}))
        out = run_page(self, dict(search="?live=http://127.0.0.1:8765", ids=IDS + ["big-k-lead"], hover_ids=["s-right"],
                                  fetch={"/grid": grid, "/state": state}))
        snap = out[0]["snap"]
        self.assertEqual(text_of(snap, "s-right"), "Its 2 strongest picks: 1 of 2 real.")
        self.assertIn("Of the 2 cells flagged most strongly", snap["hovers"]["s-right"])

    def test_no_copy_table_types_the_20_of_the_strongest_picks_sentence_any_more(self):
        js = (DOCS / "replay.js").read_text(encoding="utf-8")
        for table in ("VISIBLE_COPY", "HOVER_COPY", "DETAILS_COPY"):
            for lit in table_literals(js, table):
                for bad in ("20 strongest", "/20)", "the 20 cells", "20 most-flagged", "top-20"):
                    self.assertNotIn(bad, lit, table)


if __name__ == "__main__":
    sys.exit(unittest.main())

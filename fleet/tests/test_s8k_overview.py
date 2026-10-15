"""S8K-LANDING: checks of docs/overview/index.html and fleet/overview_build.py (criteria K1 to K10).

DOM-free: the HTML is read with html.parser, the inline script with the tokenizer of test_s8i_page (scan_js, const_span).
The page is not opened in a browser. Fixture builds go through --data / --results-root / --out into a temp directory.
"""
import builtins
import contextlib
import copy
import io
import json
import re
import shutil
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fleet import overview_build as ob  # noqa: E402
from fleet.tests import test_s8i_page as s8i  # noqa: E402

PAGE = ROOT / "docs" / "overview" / "index.html"
INPUTS = ["docs/replay/data.js", "results/fleet/benchmark.json",
          "results/fleet/hotspot_s8b-medium-80-p03-07.json", "results/closed_loop_sticky/summary.json"]
D, B, H, S = INPUTS
EXEMPT = "most fleet managers show the stop, not the pattern; trend tools exist, this one grades its own calls"
MILD = "On mild floor damage the gain is within noise; on damage that traps robots it is measurable."
VOID = {"meta", "link", "input", "br", "img", "hr", "source", "wbr", "area", "base", "col", "embed", "param", "track"}

# Digits the template may carry as typed text (K3): the top-K, VDA 5050, the wordmark, the interval label, step ordinals, the banner date.
ALLOWED_DIGITS = [r"\bStep [1-4]\b", r"\bVDA 5050\b", r"\b3000\b", r"\b95%", r"\b15 Oct 2026\b",
                  r"\btop %d\b" % ob.TOP_K, r"\bof %d\b" % ob.TOP_K]


# ------------------------------------------------------------------------------------------------ a small DOM
class Node:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent, self.kids = tag, dict(attrs), parent, []

    @property
    def classes(self):
        return (self.attrs.get("class") or "").split()

    def walk(self):
        yield self
        for k in self.kids:
            if isinstance(k, Node):
                yield from k.walk()

    def find_all(self, tag=None, cls=None):
        return [n for n in self.walk() if (tag is None or n.tag == tag) and (cls is None or cls in n.classes)]

    def text_nodes(self, skip=("script", "style")):
        if self.tag in skip:
            return
        for k in self.kids:
            if isinstance(k, Node):
                yield from k.text_nodes(skip)
            else:
                yield k

    def text(self, sep=""):
        return " ".join("".join(self.text_nodes()).split()) if sep == "" else " ".join(sep.join(self.text_nodes()).split())


class Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {}, None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        n = Node(tag, attrs, self.cur)
        self.cur.kids.append(n)
        if tag not in VOID:
            self.cur = n

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        n = self.cur
        while n is not None and n.tag != tag:
            n = n.parent
        if n is not None and n.parent is not None:
            self.cur = n.parent

    def handle_data(self, data):
        self.cur.kids.append(data)


def parse(text):
    t = Tree()
    t.feed(text)
    return t.root


def visible_pieces(root):
    """Text nodes outside script/style, then aria-label / title / alt values (attributes of any element)."""
    pieces = [s for s in root.text_nodes() if s.strip()]
    for n in root.walk():
        for a in ("aria-label", "title", "alt"):
            if n.attrs.get(a):
                pieces.append(n.attrs[a])
    return pieces


def copy_literals(root):
    js = "\n".join("".join(n.kids) for n in root.walk() if n.tag == "script" and not n.attrs.get("src"))
    span = s8i.const_span(js, "COPY")
    assert span is not None, "no const COPY"
    a, b = span
    return js, [v for s, e, v in s8i.scan_js(js)[0] if a <= s <= b]


def all_visible(root):
    return visible_pieces(root) + copy_literals(root)[1]


# ------------------------------------------------------------------------------------------------ fixtures
def read_js_doc(path):
    s = Path(path).read_text(encoding="utf-8")
    return json.loads(s[s.index("{"):s.rindex("}") + 1])


def write_fixture(dest, data_doc=None, mutate=None):
    """Copy the four inputs under dest (same relative layout); data_doc replaces data.js; mutate(name, doc) edits a JSON file."""
    for name in INPUTS:
        target = Path(dest) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if name == D:
            doc = data_doc if data_doc is not None else read_js_doc(ROOT / D)
            if mutate:
                mutate(name, doc)
            target.write_text("window.REPLAY = " + json.dumps(doc) + ";\n", encoding="utf-8")
        else:
            doc = json.loads((ROOT / name).read_text(encoding="utf-8"))
            if mutate:
                mutate(name, doc)
            target.write_text(json.dumps(doc), encoding="utf-8")
    return Path(dest)


def run_builder(root, out, data=None):
    err = io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
        rc = ob.main(["--data", str(data or Path(root) / D), "--results-root", str(root), "--out", str(out)])
    return rc, err.getvalue()


def setp(doc, path, value):
    segs = path.split(".")
    for s in segs[:-1]:
        doc = doc[int(s)] if isinstance(doc, list) else doc[s]
    last = segs[-1]
    if isinstance(doc, list):
        doc[int(last)] = value
    else:
        doc[last] = value


class Committed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = PAGE.read_text(encoding="utf-8")
        cls.root = parse(cls.html)
        cls.inputs = ob.load_inputs(ROOT / D, ROOT)


# ------------------------------------------------------------------------------------------------ K1, K2
class TestBuilder(unittest.TestCase):
    def test_flags_and_no_absolute_paths(self):
        src = (ROOT / "fleet" / "overview_build.py").read_text(encoding="utf-8")
        for flag in ("--data", "--results-root", "--out"):
            self.assertIn('"%s"' % flag, src)
        self.assertNotIn("/Users", src)
        self.assertIn("TEMPLATE", dir(ob))
        for bad in ("datetime", "time.time", "now("):
            self.assertNotIn(bad, src)
        self.assertEqual(ob.TOP_K, 20)

    def test_reads_exactly_the_four_inputs(self):
        with tempfile.TemporaryDirectory() as td:
            fx = write_fixture(Path(td) / "fx")
            out = Path(td) / "out" / "index.html"
            seen = set()
            real_open, real_io_open = builtins.open, io.open
            real_text, real_bytes = Path.read_text, Path.read_bytes

            def note(p, mode="r"):
                if "r" in str(mode) and not any(c in str(mode) for c in "wax+"):
                    seen.add(str(p))

            def fake_open(file, mode="r", *a, **k):
                note(file, mode)
                return real_open(file, mode, *a, **k)

            def fake_io_open(file, mode="r", *a, **k):
                note(file, mode)
                return real_io_open(file, mode, *a, **k)

            def fake_text(self, *a, **k):
                note(self)
                return real_text(self, *a, **k)

            def fake_bytes(self, *a, **k):
                note(self)
                return real_bytes(self, *a, **k)

            with mock.patch.object(builtins, "open", fake_open), mock.patch.object(io, "open", fake_io_open), \
                    mock.patch.object(Path, "read_text", fake_text), mock.patch.object(Path, "read_bytes", fake_bytes):
                rc, err = run_builder(fx, out)
            self.assertEqual(rc, 0, err)
            rel = {str(Path(p).resolve().relative_to(fx.resolve())) for p in seen}
            self.assertEqual(rel, set(INPUTS))
            self.assertNotIn("hotspot_s8e", " ".join(seen))

    def test_deterministic_and_committed_output_is_a_fresh_build(self):
        with tempfile.TemporaryDirectory() as td:
            a, b = Path(td) / "a.html", Path(td) / "b.html"
            self.assertEqual(run_builder(ROOT, a)[0], 0)
            self.assertEqual(run_builder(ROOT, b)[0], 0)
            self.assertEqual(a.read_bytes(), b.read_bytes())
            self.assertEqual(a.read_bytes(), PAGE.read_bytes())

    def test_missing_number_source_refuses_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            def drop(name, doc):
                if name == D:
                    del doc["run_constants"]["worth"]["map_share"]
            fx = write_fixture(Path(td) / "fx", mutate=drop)
            out = Path(td) / "out.html"
            rc, err = run_builder(fx, out)
            self.assertNotEqual(rc, 0)
            self.assertFalse(out.exists())
            self.assertIn("map_share", err)

    def test_leftover_placeholder_refuses_and_names_it(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "out.html"
            with mock.patch.object(ob, "TEMPLATE", ob.TEMPLATE.replace("</main>", "{oops_token}</main>")):
                rc, err = run_builder(ROOT, out)
            self.assertNotEqual(rc, 0)
            self.assertFalse(out.exists())
            self.assertIn("oops_token", err)

    def test_placeholder_like_text_in_script_and_style_is_not_refused(self):
        page, left = ob.build(ob.load_inputs(ROOT / D, ROOT))
        self.assertEqual(left, [])

    def test_missing_input_file_refuses_and_writes_nothing(self):
        for victim in INPUTS:
            with tempfile.TemporaryDirectory() as td:
                fx = write_fixture(Path(td) / "fx")
                (fx / victim).unlink()
                out = Path(td) / "out.html"
                rc, err = run_builder(fx, out)
                self.assertNotEqual(rc, 0, victim)
                self.assertFalse(out.exists(), victim)


# ------------------------------------------------------------------------------------------------ K3
REQUIRED = [
    (D, "len(episodes)"), (D, "run_constants.header.msgs"), (D, "run_constants.audit.read"),
    (D, "run_constants.kept.n_changes"), (D, "run_constants.kept.kept_pct"), (D, "run_constants.kept.n_repeats"),
    (D, "run_constants.header.noise"), (D, "run_constants.speed.robot_rate"), (D, "run_constants.speed.ingest_rate"),
    (D, "run_constants.speed.ratio"), (B, "live.lag_p50_s"), (B, "live.alert_latency_from_entry_p50_s"),
    (B, "batch.score.recall"), (B, "batch.score.precision"), (H, "mean.k.20.precision"), (H, "1-mean.zero_stall_share"),
    (D, "run_constants.lessons_long.truth_hit"), (D, "run_constants.lessons_long.truth_n"),
    (D, "run_constants.lessons_long.held"), (D, "run_constants.lessons_long.graded"),
    (D, "run_constants.worth.map_share"), (D, "run_constants.worth.map_share_ci95.0"), (D, "run_constants.worth.map_share_ci95.1"),
    (D, "run_constants.worth.oracle_share"), (D, "run_constants.worth.oracle_share_ci95.0"),
    (D, "run_constants.worth.oracle_share_ci95.1"),
    (S, "1-arms.map_a32.floor_skip_steps_mean/arms.none.floor_skip_steps_mean"),
    (D, "len(robots)"), (D, "meta.steps*meta.step_seconds/60"), (B, "batch.score.stuck_after"), (D, "len(obstacles)"),
    (D, "nexamples(episodes)"), (D, "hits(publishes.-1.cells,obstacles,20)"), (D, "run_constants.worth.n_seeds"),
] + [(D, "run_constants.worth.bars.%d.%s" % (i, f)) for i in range(4) for f in ("mean", "ci95_low", "ci95_high")]


def num_elements(root):
    return [(n.attrs.get("data-src"), n.text()) for n in root.find_all("b", "num")]


class TestNumbers(Committed):
    def test_every_num_is_sourced_and_equals_the_formatted_resolution(self):
        nums = num_elements(self.root)
        self.assertGreater(len(nums), 40)
        for src, shown in nums:
            self.assertTrue(src, shown)
            name = src.split(":", 1)[0]
            self.assertIn(name, INPUTS, src)
            self.assertNotIn("run_constants.closed_loop", src)
            self.assertNotIn("results/closed_loop/", src)
            self.assertEqual(shown, ob.format_value(src, ob.resolve(src, self.inputs)), src)

    def test_required_elements_are_present(self):
        have = {s for s, _ in num_elements(self.root)}
        for f, e in REQUIRED:
            self.assertIn("%s:%s" % (f, e), have)

    def test_resolver_values_on_the_committed_inputs(self):
        r = lambda f, e: ob.resolve("%s:%s" % (f, e), self.inputs)
        self.assertEqual(r(D, "len(episodes)"), len(self.inputs[D]["episodes"]))
        self.assertAlmostEqual(r(S, "1-arms.map_a32.floor_skip_steps_mean/arms.none.floor_skip_steps_mean"),
                               1 - 1139.1333333333334 / 1823.8333333333333)
        self.assertAlmostEqual(r(H, "1-mean.zero_stall_share"), 1 - self.inputs[H]["mean"]["zero_stall_share"])
        self.assertEqual(r(D, "hits(publishes.-1.cells,obstacles,20)"), self.expected_hits(self.inputs[D]))

    @staticmethod
    def expected_hits(doc):
        planted = {o["cell"] for o in doc["obstacles"]}
        return len([c for c in doc["publishes"][-1]["cells"][:20] if c[0] in planted])

    def test_distinct_sentinels_each_show_in_their_own_element(self):
        sent = {
            (D, "run_constants.header.msgs"): (7001, "7,001"), (D, "run_constants.audit.read"): (7002, "7,002"),
            (D, "run_constants.kept.n_changes"): (7003, "7,003"), (D, "run_constants.kept.n_repeats"): (7004, "7,004"),
            (D, "run_constants.header.noise"): (7005, "7,005"), (D, "run_constants.audit.sent"): (7006, "7,006"),
            (D, "run_constants.kept.kept_pct"): (17.77, "17.8%"),
            (D, "run_constants.speed.robot_rate"): (3.3, "3.3"), (D, "run_constants.speed.ingest_rate"): (4444.0, "4,444"),
            (D, "run_constants.speed.ratio"): (999, "999"),
            (D, "run_constants.lessons_long.truth_hit"): (11, "11"), (D, "run_constants.lessons_long.truth_n"): (12, "12"),
            (D, "run_constants.lessons_long.held"): (13, "13"), (D, "run_constants.lessons_long.graded"): (14, "14"),
            (D, "run_constants.worth.map_share"): (0.123, "12.3%"),
            (D, "run_constants.worth.map_share_ci95.0"): (0.045, "4.5%"), (D, "run_constants.worth.map_share_ci95.1"): (0.234, "23.4%"),
            (D, "run_constants.worth.oracle_share"): (0.456, "45.6%"),
            (D, "run_constants.worth.oracle_share_ci95.0"): (0.311, "31.1%"),
            (D, "run_constants.worth.oracle_share_ci95.1"): (0.567, "56.7%"),
            (D, "run_constants.worth.n_seeds"): (77, "77"),
            (D, "meta.steps"): (600, None), (D, "meta.step_seconds"): (6, None),
            (B, "live.lag_p50_s"): (5.5, "5.5"), (B, "live.alert_latency_from_entry_p50_s"): (13.4, "13"),
            (B, "batch.score.recall"): (0.61, "61%"), (B, "batch.score.precision"): (0.33, "33%"),
            (B, "batch.score.stuck_after"): (45, "45"), (B, "batch.messages_expected"): (8100000, "8.1"),
            (H, "mean.k.20.precision"): (0.88, "88%"), (H, "mean.zero_stall_share"): (0.25, None),
            (S, "arms.none.floor_skip_steps_mean"): (1000.0, None), (S, "arms.map_a32.floor_skip_steps_mean"): (600.0, None),
        }
        for i, (m, lo, hi) in enumerate([(11.1, 1.1, 12.1), (22.2, 2.2, 23.2), (33.3, 3.3, 34.3), (44.4, 4.4, 45.4)]):
            base = "run_constants.worth.bars.%d." % i
            sent[(D, base + "mean")] = (m, "%.1f" % m)
            sent[(D, base + "ci95_low")] = (lo, "%.1f" % lo)
            sent[(D, base + "ci95_high")] = (hi, "%.1f" % hi)
        expect = {(D, "meta.steps*meta.step_seconds/60"): "60", (H, "1-mean.zero_stall_share"): "75%",
                  (S, "1-arms.map_a32.floor_skip_steps_mean/arms.none.floor_skip_steps_mean"): "40%"}

        def mutate(name, doc):
            for (f, path), (val, _) in sent.items():
                if f == name:
                    setp(doc, path, val)
            if name == D:
                doc["episodes"] = doc["episodes"][:5]
                doc["robots"] = doc["robots"][:7]
                doc["obstacles"] = doc["obstacles"][:33]
                expect[(D, "len(episodes)")] = "5"
                expect[(D, "len(robots)")] = "7"
                expect[(D, "len(obstacles)")] = "33"
                expect[(D, "hits(publishes.-1.cells,obstacles,20)")] = str(self.expected_hits(doc))
                expect[(D, "nexamples(episodes)")] = str(len({e["cause"] for e in doc["episodes"] if not e.get("left_censored")}))

        with tempfile.TemporaryDirectory() as td:
            fx = write_fixture(Path(td) / "fx", mutate=mutate)
            out = Path(td) / "o.html"
            rc, err = run_builder(fx, out)
            self.assertEqual(rc, 0, err)
            nums = num_elements(parse(out.read_text(encoding="utf-8")))
        for key, (_, shown) in sent.items():
            if shown is not None:
                expect[key] = shown
        seen = 0
        for (f, e) in REQUIRED + [(D, "run_constants.audit.sent")]:
            want = expect.get((f, e))
            self.assertIsNotNone(want, e)
            texts = [t for s, t in nums if s == "%s:%s" % (f, e)]
            self.assertTrue(texts, e)
            self.assertEqual(set(texts), {want}, e)
            seen += 1
        self.assertEqual(seen, len(REQUIRED) + 1)

    def test_no_typed_numbers_in_the_template(self):
        prose = []
        for is_code, text in ob.visible_chunks(ob.TEMPLATE):
            if is_code:
                continue
            text = re.sub(r"<code>.*?</code>", " ", text, flags=re.S)
            text = re.sub(r"<[^>]*>", " ", text)  # tags and their attribute values
            prose.append(text)
        prose = " ".join(prose)
        for pat in ALLOWED_DIGITS:
            prose = re.sub(pat, " ", prose)
        self.assertEqual(re.findall(r"\S*\d\S*", prose), [])

    def test_copy_has_no_digits_and_v2_constants_are_gone(self):
        js, lits = copy_literals(self.root)
        self.assertEqual([v for v in lits if re.search(r"\d", v)], [])
        self.assertIsNone(re.search(r"\*\s*8\b", js))
        src = (ROOT / "fleet" / "overview_build.py").read_text(encoding="utf-8")
        for dead in ("0.205", "zone_robots", "KEPT =", "RANK =", "LESS ="):
            self.assertNotIn(dead, src)
            self.assertNotIn(dead, self.html)
        self.assertNotIn("Three real stuck periods", self.html)
        self.assertNotIn("Three real stuck periods", src)


# ------------------------------------------------------------------------------------------------ K4
class TestWords(Committed):
    def test_exempt_sentence_once_then_no_banned_word(self):
        text = " ".join(" ".join(all_visible(self.root)).split())
        self.assertEqual(text.count(EXEMPT), 1)
        rest = text.replace(EXEMPT, " ")
        self.assertEqual([m.group(0) for m in s8i.BANNED.finditer(rest)], [])

    def test_footer_paths_are_visible_and_pass(self):
        foot = self.root.find_all("footer")[0].text()
        for p in ("results/fleet/hotspot_s8e-long-w0.5.json", "laptop-scheduler/reports/wr-s8e-lessons-long.md"):
            self.assertIn(p, foot)
        self.assertIsNone(s8i.BANNED.search(foot))

    def test_chip_labels_verbatim(self):
        text = " ".join(self.root.text().split())
        for label in ("Tested, weakly.", "Timing tested, reasons not.", "Not built."):
            self.assertIn(label, text)


# ------------------------------------------------------------------------------------------------ K5
LEVELS = ["weak", "ok", "ok", "no", "ok", "weak", "weak", "nb", "nb", "nb"]
LABELS = {"ok": {"Tested in simulation.", "Tested."}, "weak": {"Tested, weakly."},
          "no": {"Not tested.", "Timing tested, reasons not."}, "nb": {"Not built."}}


class TestChips(Committed):
    def chips(self):
        return self.root.find_all("div", "st")

    def test_banner_is_first_after_header_and_names_the_four_levels(self):
        body = self.root.find_all("body")[0]
        kids = [k for k in body.kids if isinstance(k, Node)]
        self.assertEqual(kids[0].tag, "header")
        banner = kids[1]
        self.assertTrue(banner.attrs.get("role") == "note" or banner.tag == "aside")
        t = banner.text()
        for level in ("Tested in simulation", "Tested, but weakly", "Not tested", "Not built"):
            self.assertIn(level, t)

    def test_each_content_block_has_exactly_one_chip_with_the_right_level(self):
        blocks = self.root.find_all("div", "step") + self.root.find_all("div", "cbox")
        self.assertEqual(len(blocks), 10)
        for b in blocks:
            self.assertEqual(len(b.find_all("div", "st")), 1)
        self.assertEqual(len(self.chips()), 10)
        levels = []
        for c in self.chips():
            lv = [x for x in c.classes if x != "st"]
            self.assertEqual(len(lv), 1)
            self.assertIn(lv[0], LABELS)
            label = c.find_all("b")[0].text()
            self.assertIn(label, LABELS[lv[0]])
            levels.append(lv[0])
        self.assertEqual(levels, LEVELS)

    def test_chip_texts(self):
        chips = self.chips()
        log = chips[2].text()
        self.assertNotIn("zero rejects", log)
        self.assertNotIn("README only", log)
        self.assertIn("deliberately broken lines", log)
        self.assertIn(str(self.inputs[D]["run_constants"]["header"]["noise"]), log)
        self.assertIn("kept share is measured", log)
        route = chips[6].text()
        self.assertIn(MILD, route)
        self.assertNotIn("interval includes zero", self.html)
        lessons = chips[5].text()
        lt = self.inputs[D]["run_constants"]["lessons_long"]
        self.assertIn("Checked against the hidden truth. On a longer test shift the flagged cells were real %d of %d times, but only %d of %d "
                      "calls repeated in the next half hour; the repeat test is being reworked."
                      % (lt["truth_hit"], lt["truth_n"], lt["held"], lt["graded"]), lessons)
        self.assertEqual((lt["truth_hit"], lt["truth_n"], lt["held"], lt["graded"]), (27, 27, 9, 31))


# ------------------------------------------------------------------------------------------------ K6, K7
class TestLessonsAndRouting(Committed):
    def test_lessons_card_one_item_with_the_mark_and_no_raw_text(self):
        items = self.root.find_all("div", "lesson")
        lessons = self.inputs[D]["lessons"]
        self.assertEqual(len(lessons), 1)
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertEqual(it.attrs.get("data-kind"), "hot_cell")
        t = it.text()
        self.assertIn("One spot on the floor keeps holding robots up. Worth a look.", t)
        self.assertIn("10,20", t)
        self.assertIn("✓ real spot", t)
        visible = " ".join(all_visible(self.root))
        self.assertNotIn(lessons[0]["text"], visible)
        self.assertNotIn("In zone", visible)

    def test_lessons_card_per_kind_newest_and_truth_miss(self):
        doc = read_js_doc(ROOT / D)
        base = doc["lessons"][0]
        old = dict(base, decided_at_step=100, truth="miss", text="In zone 0, cell 1,1 had old")
        other = dict(base, lesson_kind="hot_robot", truth=None, text="In zone 0, robot Z0-03 got stuck")
        newer = dict(base, decided_at_step=400, truth="miss", text="In zone 0, cell 2,2 had new")
        doc["lessons"] = [old, base, newer, other]
        html = ob.lesson_items({D: doc})
        items = parse(html).find_all("div", "lesson")
        self.assertEqual(sorted(i.attrs["data-kind"] for i in items), ["hot_cell", "hot_robot"])
        cell = [i for i in items if i.attrs["data-kind"] == "hot_cell"][0].text()
        self.assertIn("2,2", cell)
        self.assertNotIn("✓", cell)
        self.assertNotIn("In zone", html)

    def routing_block(self):
        return [s for s in self.root.find_all("div", "step") if "What's next" in s.text()][0]

    def test_routing_beat(self):
        blk = self.routing_block()
        rows = blk.find_all("div", "br")
        self.assertEqual(len(rows), 4)
        self.assertEqual([r.find_all("span", "lab")[0].text() for r in rows],
                         ["Bad floor, no map", "With the analyser's map", "With perfect knowledge", "Clean floor"])
        bars = self.inputs[D]["run_constants"]["worth"]["bars"]
        widths = [float(re.search(r"width:([\d.]+)%", r.find_all("span", "fl")[0].attrs["style"]).group(1)) for r in rows]
        for w, b in zip(widths, bars):
            self.assertAlmostEqual(w / b["mean"], widths[0] / bars[0]["mean"], delta=0.02)  # scaled from zero
        self.assertEqual(len(blk.find_all("span", "wh")), 4)
        t = blk.text()
        self.assertIn(MILD, t)
        self.assertIn("mean of 30 shifts", t)
        self.assertIn("fewer drives into bad cells", t)
        self.assertIn("95% interval", t)
        self.assertNotIn("closed_loop/", self.html.replace("closed_loop_sticky", ""))


# ------------------------------------------------------------------------------------------------ K8, K9, K10
class TestLinksAndShell(Committed):
    def test_claims(self):
        text = " ".join(all_visible(self.root)).lower()
        self.assertNotIn("nine robots", text)
        self.assertNotIn("do not tell you", text)
        prob = [s for s in self.root.find_all("div", "step") if "The problem" in s.text()][0]
        self.assertIn(EXEMPT, prob.text())

    def test_links(self):
        links = [a for a in self.root.find_all("a") if a.attrs.get("href") == "../replay/index.html"]
        self.assertTrue(any("see it move" in a.text().lower() for a in links))
        for n in self.root.walk():
            for a in ("href", "src"):
                v = n.attrs.get(a)
                if v:
                    self.assertFalse(v.startswith("/") or v.startswith("file:") or "/Users" in v, v)
                    if re.match(r"[a-z]+://", v):
                        self.assertEqual((n.tag, v.split("/")[2]), ("link", "fonts.googleapis.com"), v)

    def test_replay_page_has_the_one_header_link(self):
        root = parse((ROOT / "docs" / "replay" / "index.html").read_text(encoding="utf-8"))
        links = [a for a in root.find_all("a") if a.attrs.get("href") == "../overview/index.html"]
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].text(), "about this project")
        node = links[0]
        while node is not None and node.tag != "header":
            node = node.parent
        self.assertIsNotNone(node)

    def test_shell(self):
        h = self.html
        self.assertTrue(h.startswith("<!doctype html>"))
        for needle in ('<html lang="en">', '<meta charset="utf-8">',
                       '<meta name="viewport" content="width=device-width, initial-scale=1">', "<title>Fleet stuck analyser</title>"):
            self.assertIn(needle, h)
        self.assertNotIn("claude:viewport-fit-sides", h)
        self.assertNotIn("prefers-color-scheme", h)
        widths = [int(w) for w in re.findall(r"@media\s*\(max-width:\s*(\d+)px\)", h)]
        self.assertTrue(widths and min(widths) <= 720 and 720 in widths)
        css = re.search(r"@media \(max-width:720px\)\{(.*?)\n\}", h, re.S).group(1)
        self.assertRegex(css, r"\.step\{grid-template-columns:1fr")
        self.assertEqual(len(self.root.find_all("h1")), 1)

    def test_readme(self):
        t = (ROOT / "docs" / "overview" / "README.md").read_text(encoding="utf-8")
        for needle in ("overview_build.py", "data.js", "synthetic", "landing page", ".venv/bin/python fleet/overview_build.py",
                       "results/fleet/benchmark.json", "results/closed_loop_sticky/summary.json"):
            self.assertIn(needle, t)


if __name__ == "__main__":
    unittest.main()

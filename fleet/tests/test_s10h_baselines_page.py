"""S10H-PERSISTENCE-ON-PAGES: run_constants.baselines (exporter, data.js), the persistence numbers on the overview and the replay page.

(a) every field of run_constants.baselines in data.js equals the value at its path in results/fleet/baselines_<label>.json;
(b) overview DOM: (b1) every map truth-precision number shares its closest .big/.pair/.st/tr/figure ancestor with the persistence
    number of the same label and K; (b2) the 97% sits in an element that also holds the s8b K20 map and persistence numbers and the
    words 'planted' and 'hidden truth';
(c) the verdict words shown equal the JSON verdicts (for every label that shows one; s10-none shows none and reads
    'nothing planted to find');
(d) no BANNED word in the new copy, aria-labels and hover text of either page;
(e) the two opening sentences of the new block, verbatim;
(f) the exporter: bad --baselines input exits non-zero and leaves data.js unchanged; the refresh changes only run_constants.baselines;
(g) the replay copy omits its clauses, with no 'null' / 'NaN' / 'undefined', when run_constants.baselines or an entry is absent.

Injection that turns each test red (each was run once, see the build report): (a) change one persistence value in data.js;
(b1) delete one persistence span of the overview; (b2) drop the sub-comparison out of the step-3 big element; (c) flip a verdict word
in the overview; (d) put the word 'stall' into VISIBLE_COPY.persist.context; (e) change a word of the first sentence in
overview_build.PERSIST_OPEN; (f) let baselines_constant skip the 'missing K' check; (g) let the replay print the sentence without the
presence check.
"""
import contextlib
import copy
import io
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "fleet"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import replay_export as rx  # noqa: E402
from fleet import overview_build as ob  # noqa: E402
from fleet.tests import test_s8i_page as s8i  # noqa: E402
from fleet.tests import test_s8k_overview as k8  # noqa: E402
from fleet.tests.test_s8j_dom import DOCS, run_page  # noqa: E402

LABELS = ["s8b-medium-80-p03-07", "closed-loop-sticky", "s8e-long-w0.5", "s10c-blind", "s10-none"]
SPECS = ["%s=results/fleet/baselines_%s.json" % (x, x) for x in LABELS]
DATA = ROOT / "docs" / "replay" / "data.js"
ARM_FIELDS = ("truth_precision", "pai", "lift_all", "lift_ever")
LESSON_FIELDS = ("lift_window", "lift_ever", "chance_window", "chance_ever", "n_lessons", "observed_rate")
OPEN = ("It does not, on any of the five runs: checked against the hidden truth, the cells that were busiest by last hour's plain "
        "counts are right as often as the map's picks, or more often.",
        "What does the work is finding the robots that got stuck and checking each call afterwards; the decayed weighting adds "
        "nothing on top.")
NOTHING = "nothing planted to find"
ANCESTORS = ("big", "pair", "st", "tr", "figure")


def baseline_json(label):
    return json.loads((ROOT / "results" / "fleet" / ("baselines_%s.json" % label)).read_text(encoding="utf-8"))["baselines"]


def read_data(path=DATA):
    return rx.read_data_js(path)


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = rx.main(argv)
        except SystemExit as e:
            rc = e.code
    return rc, err.getvalue()


def strip_key(text, name):
    """data.js text without run_constants.<name> (a `,"name":{...}` or `"name":[...]` member)."""
    key = '"%s":' % name
    assert text.count(key) == 1
    start = text.index(key)
    _, end = json.JSONDecoder().raw_decode(text, start + len(key))
    if text[start - 1] == ",":
        return text[:start - 1] + text[end:]
    return text[:start] + text[end + 1:]


# ------------------------------------------------------------------------------------------------ (a)
class TestDataJs(unittest.TestCase):
    def test_every_field_equals_the_json_value(self):
        got = read_data()["run_constants"]["baselines"]
        self.assertEqual([g["label"] for g in got], LABELS)  # the order of the --baselines flags
        for g in got:
            b = baseline_json(g["label"])
            self.assertEqual(g["src"], "results/fleet/baselines_%s.json" % g["label"])
            self.assertEqual(g["n_zones"], b["paired"]["20"]["truth_precision"]["n_zones"])
            self.assertEqual(g["chance_all"], b["chance"]["all"])
            self.assertEqual(g["chance_ever"], b["chance"]["ever"])
            for kk in ("20", "40"):
                for arm in ("map", "persistence"):
                    for f in ARM_FIELDS:
                        self.assertEqual(g["k"][kk][arm][f], b["k"][kk][arm][f], (g["label"], kk, arm, f))
                p = b["paired"][kk]["truth_precision"]
                self.assertEqual(g["k"][kk]["paired"], {"mean": p["mean"], "ci95": p["ci95"], "verdict": p["verdict"]})
            lp = b["lesson_persist"]
            if lp["n_lessons"] == 0:
                self.assertIsNone(g["lesson_persist"], g["label"])
            else:
                self.assertEqual(g["lesson_persist"], {f: lp[f] for f in LESSON_FIELDS}, g["label"])
        self.assertEqual([g["label"] for g in got if g["lesson_persist"] is None], ["s8b-medium-80-p03-07", "closed-loop-sticky"])

    def test_the_known_verdicts(self):
        v = {g["label"]: (g["k"]["20"]["paired"]["verdict"], g["k"]["40"]["paired"]["verdict"]) for g in read_data()["run_constants"]["baselines"]}
        self.assertEqual(v["s8e-long-w0.5"][0], "worse")
        self.assertEqual(v["s8b-medium-80-p03-07"], ("within noise", "worse"))
        self.assertEqual(v["closed-loop-sticky"], ("within noise", "worse"))


# ------------------------------------------------------------------------------------------------ the overview
class Overview(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = k8.PAGE.read_text(encoding="utf-8")
        cls.root = k8.parse(cls.html)
        cls.entries = read_data()["run_constants"]["baselines"]

    def src_parts(self, src):
        m = re.fullmatch(r"docs/replay/data\.js:run_constants\.baselines\.(\d+)\.(.+)", src or "")
        return (int(m.group(1)), m.group(2)) if m else None

    def closest(self, node):
        n = node.parent
        while n is not None and not any(c in n.classes or n.tag == c for c in ANCESTORS):
            n = n.parent
        return n

    def spans(self, anc):
        parts = [self.src_parts(n.attrs.get("data-src")) for n in anc.walk() if n.tag == "b" and "num" in n.classes]
        return [x for x in parts if x]


class TestOverviewPairs(Overview):
    def test_b1_each_map_number_shares_its_closest_ancestor_with_the_persistence_number(self):
        seen = 0
        for n in self.root.find_all("b", "num"):
            sp = self.src_parts(n.attrs.get("data-src"))
            if not sp or not re.fullmatch(r"k\.(20|40)\.map\.truth_precision", sp[1]):
                continue
            seen += 1
            anc = self.closest(n)
            self.assertIsNotNone(anc)
            want = (sp[0], sp[1].replace(".map.", ".persistence."))
            self.assertIn(want, self.spans(anc), (self.entries[sp[0]]["label"], sp[1]))
        self.assertEqual(seen, 5)  # the step-3 comparison and the four rows of the figure

    def test_b1_the_figure_binds_label_and_k_not_just_any_persistence_number(self):
        fig = self.root.find_all("figure")
        fig = [f for f in fig if "Top 20 right" in f.text()]
        self.assertEqual(len(fig), 1)
        for row in fig[0].find_all("div", "pr"):
            label = row.attrs["data-label"]
            idx = [e["label"] for e in self.entries].index(label)
            if label == "s10-none":
                self.assertEqual(self.spans(row), [])
                continue
            self.assertEqual({i for i, _ in self.spans(row)}, {idx}, label)  # every number of a row is that run's
            paths = {p for _, p in self.spans(row)}
            for want in ("k.20.map.truth_precision", "k.20.persistence.truth_precision", "k.20.paired.mean",
                         "k.20.paired.ci95.0", "k.20.paired.ci95.1"):
                self.assertIn(want, paths, label)

    def test_b2_the_97_percent_is_labelled_and_its_element_holds_the_same_definition_pair(self):
        hot = "results/fleet/hotspot_s8b-medium-80-p03-07.json:mean.k.20.precision"
        spans = [n for n in self.root.find_all("b", "num") if n.attrs.get("data-src") == hot]
        self.assertEqual(len(spans), 1)
        holder = spans[0].parent
        i = [e["label"] for e in self.entries].index("s8b-medium-80-p03-07")
        have = {p for j, p in self.spans(holder) if j == i}
        self.assertIn("k.20.map.truth_precision", have)
        self.assertIn("k.20.persistence.truth_precision", have)
        t = holder.text()
        self.assertIn("planted", t)
        self.assertIn("hidden truth", t)
        # the 97% is the end-of-shift score against the planted cells, said before the comparison, never as its comparand
        before = t[:t.index(spans[0].text())]
        self.assertIn("End-of-shift score against the planted cells", before)
        self.assertLess(t.index(spans[0].text()), t.index("A separate comparison"))
        big = self.closest(spans[0])
        self.assertIn("big", big.classes)
        self.assertIn(holder, list(big.walk()))

    def test_step_four_row_shows_the_plain_counts_number_without_a_verdict_and_the_two_lifts(self):
        i = [e["label"] for e in self.entries].index("s8e-long-w0.5")
        step = [s for s in self.root.find_all("div", "step") if "Step 4" in s.text()][0]
        have = {p for j, p in self.spans(step) if j == i}
        self.assertIn("k.20.persistence.truth_precision", have)
        self.assertNotIn("k.20.map.truth_precision", have)
        self.assertEqual([n for n in step.walk() if "vd" in n.classes], [])
        line = [p for p in step.find_all("p", "one") if "plain counts" in p.text()]
        self.assertEqual(len(line), 1)
        self.assertIn("top 20 by plain counts", line[0].text())
        chip = step.find_all("div", "st")[0].text()
        self.assertIn("{:.1f} times as often as chance against cells that got stuck in the same half hour".format(
            ob.Decimal(self.entries[i]["lesson_persist"]["lift_window"]).quantize(ob.Decimal("0.1"), rounding=ob.ROUND_HALF_UP)), chip)
        self.assertIn("against the cells that ever got stuck", chip)
        self.assertTrue({"lesson_persist.lift_window", "lesson_persist.lift_ever"} <= have)


# ------------------------------------------------------------------------------------------------ (c)
class TestVerdicts(Overview):
    def test_c_every_verdict_word_shown_equals_the_json_verdict(self):
        vds = [n for n in self.root.walk() if n.tag == "span" and "vd" in n.classes]
        self.assertEqual(len(vds), 5)  # step 3, plus four rows of the figure
        for n in vds:
            sp = self.src_parts(n.attrs["data-src"])
            e = self.entries[sp[0]]
            m = re.fullmatch(r"k\.(20|40)\.paired\.verdict", sp[1])
            self.assertTrue(m, sp)
            self.assertEqual(n.text(), baseline_json(e["label"])["paired"][m.group(1)]["truth_precision"]["verdict"], e["label"])

    def test_c_s10_none_reads_nothing_planted_and_shows_no_bars_and_no_verdict(self):
        i = [e["label"] for e in self.entries].index("s10-none")
        row = [r for r in self.root.find_all("div", "pr") if r.attrs["data-label"] == "s10-none"][0]
        self.assertIn(NOTHING, row.text())
        self.assertEqual(row.find_all("span", "pbf"), [])
        self.assertEqual([n for n in row.walk() if "vd" in n.classes], [])
        for n in self.root.walk():
            sp = self.src_parts(n.attrs.get("data-src"))
            self.assertFalse(sp and sp[0] == i, n.attrs.get("data-src"))
        self.assertEqual(self.html.count(NOTHING), 2)  # the row and the figure's aria-label
        self.assertEqual(len(self.root.find_all("div", "pr")), 5)
        self.assertEqual([r.attrs["data-label"] for r in self.root.find_all("div", "pr")], LABELS)

    def test_c_the_verdict_comes_from_the_data_not_from_the_page(self):
        with tempfile.TemporaryDirectory() as td:
            doc = k8.read_js_doc(DATA)
            doc["run_constants"]["baselines"][0]["k"]["20"]["paired"]["verdict"] = "beats"
            fx = k8.write_fixture(Path(td) / "fx", data_doc=doc)
            out = Path(td) / "o.html"
            rc, err = k8.run_builder(fx, out)
            self.assertEqual(rc, 0, err)
            root = k8.parse(out.read_text(encoding="utf-8"))
        self.assertEqual([n.text() for n in root.walk() if "vd" in n.classes][0], "beats")


# ------------------------------------------------------------------------------------------------ (e)
class TestBlock(Overview):
    def block(self):
        return [s for s in self.root.find_all("section", "pw")][0]

    def test_e_the_block_follows_step_three_and_opens_with_the_two_sentences(self):
        blk = self.block()
        self.assertEqual(blk.find_all("h2")[0].text(), "Does the map beat last hour's counts?")
        text = blk.find_all("p")[0].text()
        self.assertTrue(text.startswith(" ".join(OPEN)), text)
        kids = [n for n in self.root.find_all("div", "steps")[0].kids if isinstance(n, k8.Node)]
        pos = kids.index(blk)
        self.assertIn("Step 3", kids[pos - 1].text())
        self.assertIn("Step 4", kids[pos + 1].text())

    def test_e_at_most_four_body_sentences_and_every_number_has_a_source(self):
        blk = self.block()
        body = " ".join(p.text() for p in blk.find_all("p"))
        self.assertLessEqual(len(re.findall(r"[.?!](?:\s|$)", body)), 4)
        nums = blk.find_all("b", "num")
        self.assertGreaterEqual(len(nums), 16)
        for n in nums:
            self.assertTrue(self.src_parts(n.attrs.get("data-src")), n.attrs.get("data-src"))
        # numbers in the figure text outside a span: none (the two typed ones are 'top 20' and '95%')
        rest = re.sub(r"top 20|Top 20|95%", " ", blk.text(" "))
        for n in nums:
            rest = rest.replace(n.text(), " ", 1)
        self.assertEqual(re.findall(r"\d", rest), [])

    def test_figure_aria_label_carries_the_numbers(self):
        fig = self.block().find_all("figure")[0]
        label = fig.attrs["aria-label"]
        for e in self.entries:
            if e["chance_all"]:
                self.assertIn(ob.format_value("docs/replay/data.js:run_constants.baselines.0.k.20.map.truth_precision",
                                              e["k"]["20"]["map"]["truth_precision"]), label)
                self.assertIn(e["k"]["20"]["paired"]["verdict"], label)
        self.assertIn(NOTHING, label)
        self.assertEqual(fig.attrs.get("role"), "img")


# ------------------------------------------------------------------------------------------------ (d)
class TestBannedWords(Overview):
    def test_d_overview_new_copy_aria_labels_and_the_step_three_sentence(self):
        blk = self.root.find_all("section", "pw")[0]
        pieces = [blk.text(" ")] + [n.attrs["aria-label"] for n in blk.walk() if n.attrs.get("aria-label")]
        step3 = [s for s in self.root.find_all("div", "step") if "Step 3" in s.text()][0]
        pieces.append(step3.find_all("div", "big")[0].text(" "))
        pieces.append([s for s in self.root.find_all("div", "step") if "Step 4" in s.text()][0].find_all("p", "one")[-1].text(" "))
        for p in pieces:
            self.assertEqual([m.group(0) for m in s8i.BANNED.finditer(p)], [], p)
        for n in self.root.walk():
            for a in ("aria-label", "title", "alt"):
                v = n.attrs.get(a)
                if v and "hidden truth" in v:
                    self.assertIsNone(s8i.BANNED.search(v), v)
        # the data-src paths of the new spans do not carry n_zones
        self.assertNotIn("n_zones", self.html)

    def test_d_replay_additions(self):
        js = (DOCS / "replay.js").read_text(encoding="utf-8")
        lits = {}
        for name in ("VISIBLE_COPY", "HOVER_COPY"):
            a, b = s8i.const_span(js, name)
            lits[name] = [v for s, e, v in s8i.scan_js(js)[0] if a <= s <= b]
        mine = [v for v in lits["VISIBLE_COPY"] + lits["HOVER_COPY"]
                if "plain counts" in v or "times as often as chance" in v or "other test areas" in v]
        self.assertEqual(len(mine), 3)
        for v in mine:
            self.assertIsNone(s8i.BANNED.search(v), v)
        for v in lits["VISIBLE_COPY"] + lits["HOVER_COPY"]:
            self.assertNotIn("NaN", v)
        self.assertEqual(sum("{k}" in v and "hidden truth" in v for v in lits["VISIBLE_COPY"]), 1)

    def test_d_the_replay_index_html_is_unchanged_and_quotes_no_precision(self):
        html = (DOCS / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("persistence", html)
        self.assertNotIn("sentence-persist", html)


# ------------------------------------------------------------------------------------------------ (f)
class TestExporter(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.out = Path(self.td.name) / "data.js"
        self.full = DATA.read_text(encoding="utf-8")
        self.pre = strip_key(self.full, "baselines")
        self.out.write_text(self.pre, encoding="utf-8")

    def refresh(self, *specs, where=ROOT):
        import os
        old = os.getcwd()
        os.chdir(where)
        try:
            return run_main(["--refresh-constants-only", "--out", str(self.out)] + [x for s in specs for x in ("--baselines", s)])
        finally:
            os.chdir(old)

    def test_f_the_five_specs_restore_the_committed_bytes_and_change_only_baselines(self):
        rc, err = self.refresh(*SPECS)
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.out.read_text(encoding="utf-8"), self.full)
        a, b = rx.read_data_js(self.out), rx.read_data_js(DATA)
        pre = json.loads(self.pre[len(rx.PREFIX):].rstrip().removesuffix(";"))
        self.assertNotIn("baselines", pre["run_constants"])
        a["run_constants"].pop("baselines")
        self.assertEqual(a, pre)
        self.assertEqual(list(b["run_constants"])[-1], "baselines")

    def test_f_order_of_the_flags_is_kept(self):
        rc, err = self.refresh(*SPECS[::-1])
        self.assertEqual(rc, 0, err)
        self.assertEqual([e["label"] for e in rx.read_data_js(self.out)["run_constants"]["baselines"]], LABELS[::-1])

    def test_f_bad_input_exits_non_zero_and_leaves_the_file_unchanged(self):
        bad = Path(self.td.name) / "nobaselines.json"
        bad.write_text(json.dumps({"params": {}}), encoding="utf-8")
        nok = Path(self.td.name) / "nok.json"
        doc = baseline_json("s8b-medium-80-p03-07")
        del doc["k"]["40"]
        nok.write_text(json.dumps({"baselines": doc}), encoding="utf-8")
        nopaired = Path(self.td.name) / "nopaired.json"
        doc = baseline_json("s8b-medium-80-p03-07")
        del doc["paired"]["40"]
        nopaired.write_text(json.dumps({"baselines": doc}), encoding="utf-8")
        for spec in ("no-equals-sign", "x=%s" % bad, "x=%s" % nok, "x=%s" % nopaired, "x=" + str(Path(self.td.name) / "absent.json"), "=a"):
            rc, err = self.refresh(SPECS[0], spec)  # a good spec first: nothing may be written for it either
            self.assertEqual(rc, 2, spec)
            self.assertIn("error:", err)
            self.assertEqual(self.out.read_text(encoding="utf-8"), self.pre, spec)
            self.assertFalse(Path(str(self.out) + ".tmp").exists())

    def test_f_a_label_is_split_on_the_first_equals_sign_and_src_is_the_path_as_given(self):
        got = rx.baselines_constant(["x y=" + SPECS[4].split("=", 1)[1]])
        self.assertEqual((got[0]["label"], got[0]["src"]), ("x y", SPECS[4].split("=", 1)[1]))
        self.assertIsNone(rx.baselines_constant(None))
        self.assertIsNone(rx.baselines_constant([]))

    def test_f_the_flag_is_documented_and_baselines_follows_explorer(self):
        self.assertEqual(rx.RUN_CONSTANTS_ORDER[-2:], ("explorer", "baselines"))
        self.assertIn("--baselines", rx.__doc__)
        self.assertIn("baselines ", rx.__doc__)

    def test_f_a_refresh_without_any_flag_names_baselines(self):
        rc, err = run_main(["--refresh-constants-only", "--out", str(self.out)])
        self.assertEqual(rc, 2)
        self.assertIn("--baselines", err)
        self.assertEqual(self.out.read_text(encoding="utf-8"), self.pre)

    def test_data_js_stays_under_the_size_cap(self):
        self.assertLess(len(self.full.encode("utf-8")), rx.MAX_BYTES)


# ------------------------------------------------------------------------------------------------ (g)
IDS = ["s-right", "lessonlong", "sentence-persist"]


class TestReplayCopy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = read_data()

    def run_with(self, mutate):
        d = copy.deepcopy(self.d)
        mutate(d["run_constants"])
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "data.js"
            p.write_text("window.REPLAY = " + json.dumps(d, separators=(",", ":")) + ";\n", encoding="utf-8")
            out = run_page(self, dict(steps=[499], ids=IDS, hover_ids=["sentence-persist", "lessonlong"]), p)
        return out[0]["snap"]

    def shown(self, snap):
        return " ".join(snap["shown"]) if isinstance(snap["shown"], list) else str(snap["shown"])

    def assert_clean(self, snap):
        s = json.dumps(snap)
        for bad in ("null", "NaN", "undefined"):
            self.assertNotIn(bad, s.replace('"title": null', "").replace('"sentence-persist": null', ""))

    def test_g_with_the_committed_data_the_sentence_and_the_lifts_are_shown(self):
        snap = self.run_with(lambda rc: None)
        e = {x["label"]: x for x in self.d["run_constants"]["baselines"]}
        k = e["s8b-medium-80-p03-07"]["k"]["20"]
        text = " ".join(snap["ids"]["sentence-persist"]["text"].split())
        self.assertFalse(snap["ids"]["sentence-persist"]["hidden"])
        self.assertIn("{:.1f}% real".format(0.925 * 100), text)
        self.assertIn("93.3% real", text)
        self.assertIn("paired verdict for the map: " + k["paired"]["verdict"], text)
        self.assertIn("not this shift", text)
        self.assertIn("hidden truth", text)
        self.assertIn("results/fleet/baselines_s8b-medium-80-p03-07.json", snap["hovers"]["sentence-persist"])
        lesson = " ".join(snap["ids"]["lessonlong"]["text"].split())
        self.assertIn("3.0 times as often as chance against cells that got stuck in the same half hour", lesson)
        self.assertIn("3.3 times as often against the cells that ever got stuck", lesson)
        self.assertIsNone(s8i.BANNED.search(text))
        # the sentence sits beside the top-20 sentence, not in a closed block
        self.assertEqual(snap["ids"]["s-right"]["hidden"], False)

    def test_g_without_run_constants_baselines_the_clauses_are_omitted(self):
        snap = self.run_with(lambda rc: rc.pop("baselines"))
        self.assertTrue(snap["ids"]["sentence-persist"] is None or snap["ids"]["sentence-persist"]["hidden"])
        lesson = " ".join(snap["ids"]["lessonlong"]["text"].split())
        self.assertIn("were still above their area's average in the next half hour; only", lesson)
        self.assertNotIn("times as often", lesson)
        self.assert_clean(snap)
        self.assertNotIn("persistence", json.dumps(snap["shown"]))
        self.assertNotIn("other test areas", json.dumps(snap["shown"]))

    def test_g_with_baselines_set_to_null_the_clauses_are_omitted(self):
        snap = self.run_with(lambda rc: rc.update(baselines=None))
        self.assertTrue(snap["ids"]["sentence-persist"] is None or snap["ids"]["sentence-persist"]["hidden"])
        self.assertNotIn("times as often", snap["ids"]["lessonlong"]["text"])

    def test_g_without_the_two_entries_the_clauses_are_omitted(self):
        def drop(rc):
            rc["baselines"] = [e for e in rc["baselines"] if e["label"] not in ("s8b-medium-80-p03-07", "s8e-long-w0.5")]
        snap = self.run_with(drop)
        self.assertTrue(snap["ids"]["sentence-persist"] is None or snap["ids"]["sentence-persist"]["hidden"])
        self.assertNotIn("times as often", snap["ids"]["lessonlong"]["text"])
        self.assert_clean(snap)

    def test_g_a_null_lesson_persist_or_a_null_value_omits_only_the_lifts(self):
        def nulls(rc):
            for e in rc["baselines"]:
                if e["label"] == "s8e-long-w0.5":
                    e["lesson_persist"] = None
        snap = self.run_with(nulls)
        self.assertNotIn("times as often", snap["ids"]["lessonlong"]["text"])
        self.assertFalse(snap["ids"]["sentence-persist"]["hidden"])  # the floor entry is still there
        self.assert_clean(snap)

        def one_null(rc):
            for e in rc["baselines"]:
                if e["label"] == "s8e-long-w0.5":
                    e["lesson_persist"]["lift_ever"] = None
        snap = self.run_with(one_null)
        self.assertNotIn("times as often", snap["ids"]["lessonlong"]["text"])
        self.assert_clean(snap)

    def test_g_a_floor_entry_missing_a_value_omits_the_sentence(self):
        def broken(rc):
            for e in rc["baselines"]:
                if e["label"] == "s8b-medium-80-p03-07":
                    e["k"]["20"]["persistence"]["truth_precision"] = None
        snap = self.run_with(broken)
        self.assertTrue(snap["ids"]["sentence-persist"] is None or snap["ids"]["sentence-persist"]["hidden"])
        self.assert_clean(snap)


if __name__ == "__main__":
    unittest.main()

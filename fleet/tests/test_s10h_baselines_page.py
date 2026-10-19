"""S10H-PERSISTENCE-ON-PAGES: run_constants.baselines (exporter, data.js), the persistence numbers on the overview and the replay page.

(a) every field of run_constants.baselines in data.js equals the value at its path in results/fleet/baselines_<label>.json;
(b) overview DOM: (b1) every map truth-precision number shares its closest .one/.big/.pair/.st/tr/figure ancestor with the persistence
    number of the same label and K; (b2) the step-3 text column that holds the 97% also holds, in a p.one outside every .big, the s8b
    K20 map and persistence numbers, the minutes and the words 'planted', 'hidden truth' and 'different test';
(c) the verdict words shown equal the JSON verdicts (for every label that shows one; s10-none shows none and reads
    'nothing planted to find');
(d) no BANNED word in the new copy, aria-labels and hover text of either page;
(e) the two opening sentences of the new block, verbatim, in a FRESH build of the builder (which also equals the committed page),
    and the guard that ties the opening sentence to the K20 verdicts of the data;
(h) every window sentence renders round(horizon_s / 60) minutes of its own entry; 'following hour' / 'next hour' appear on neither page;
(i) the figure: points, rendered end labels, bold verdicts, a counts bar with contrast >= 3:1, no 'paired verdict' on either page;
(f) the exporter: bad --baselines input exits non-zero and leaves data.js unchanged; the refresh changes only run_constants.baselines;
(g) the replay copy omits its clauses, with no 'null' / 'NaN' / 'undefined', when run_constants.baselines or an entry is absent.

Injection that turns each test red (each was run once, see the build report): (a) change one persistence value in data.js;
(b1) delete one persistence span of the overview; (b2) put the sub-comparison back into the step-3 big element; (c) flip a verdict word
in the overview; (d) put the word 'stall' into VISIBLE_COPY.persist.context; (e) change a word of the first sentence in
overview_build.PERSIST_OPEN; (h) give one horizon_s a wrong value; (e-guard) flip a K20 verdict in data.js to 'beats'; (f) let baselines_constant skip the 'missing K' check; (g) let the replay print the sentence without the
presence check.
"""
import contextlib
import copy
import io
import json
import math
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
        "counts are right about as often as the map's picks, and on one run more often.",
        "What does the work is finding the robots that got stuck and checking each call afterwards.")
NOTHING = "nothing planted to find"
ANCESTORS = ("one", "big", "pair", "st", "tr", "figure")
SHOWN = [x for x in LABELS if x != "s10-none"]  # the entries that show a verdict


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
            self.assertEqual(g["horizon_s"], b["params"]["horizon_s"], g["label"])
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
        self.assertEqual({g["label"]: g["horizon_s"] for g in got}, {"s8b-medium-80-p03-07": 1245, "closed-loop-sticky": 3600,
                                                                      "s8e-long-w0.5": 1245, "s10c-blind": 1245, "s10-none": 1245})

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
        self.assertEqual(seen, 6)  # the step-3 and step-4 comparisons and the four rows of the figure

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
                         "k.20.paired.ci95.0", "k.20.paired.ci95.1", "horizon_s/60"):
                self.assertIn(want, paths, label)

    def step(self, n):
        return [s for s in self.root.find_all("div", "step") if "Step %d" % n in s.text()][0]

    def test_b2_the_97_percent_is_labelled_and_its_column_holds_the_same_definition_pair_outside_every_big(self):
        hot = "results/fleet/hotspot_s8b-medium-80-p03-07.json:mean.k.20.precision"
        spans = [n for n in self.root.find_all("b", "num") if n.attrs.get("data-src") == hot]
        self.assertEqual(len(spans), 1)
        big = self.closest(spans[0])
        self.assertIn("big", big.classes)
        txt = self.step(3).find_all("div", "txt")
        self.assertEqual(len(txt), 1)
        txt = txt[0]
        self.assertIn(spans[0], list(txt.walk()))
        i = [e["label"] for e in self.entries].index("s8b-medium-80-p03-07")
        have = {p for j, p in self.spans(txt) if j == i}
        self.assertIn("k.20.map.truth_precision", have)
        self.assertIn("k.20.persistence.truth_precision", have)
        self.assertIn("horizon_s/60", have)
        t = txt.text()
        for w in ("planted", "hidden truth", "different test"):
            self.assertIn(w, t)
        # no baselines span is a descendant of any .big of the page: the comparison is not a display numeral
        for b in self.root.find_all("div", "big"):
            self.assertEqual(self.spans(b), [], b.text())
        one = [p for p in txt.find_all("p", "one") if "different test" in p.text()]
        self.assertEqual(len(one), 1)
        self.assertTrue({"k.20.map.truth_precision", "k.20.persistence.truth_precision", "horizon_s/60"} <= {p for j, p in self.spans(one[0]) if j == i})
        self.assertEqual([n.text() for n in one[0].walk() if "vd" in n.classes], [self.entries[i]["k"]["20"]["paired"]["verdict"]])
        self.assertIn("hidden truth", one[0].text())
        # the 97% keeps its label, said before the number; the comparison comes after the big element
        self.assertIn("End-of-shift score against the planted cells", big.text())
        self.assertLess(big.text().index("End-of-shift score against the planted cells"), big.text().index(spans[0].text()))
        kids = [n for n in txt.kids if isinstance(n, k8.Node)]
        self.assertLess(kids.index(big), kids.index(one[0]))

    def test_step_four_pair_is_one_entry_with_its_verdict_and_the_lifts_sentence_is_unchanged(self):
        i = [e["label"] for e in self.entries].index("s8e-long-w0.5")
        step = self.step(4)
        have = {p for j, p in self.spans(step) if j == i}
        line = [p for p in step.find_all("p", "one") if "plain counts" in p.text()]
        self.assertEqual(len(line), 1)
        want = {"k.20.map.truth_precision", "k.20.persistence.truth_precision", "horizon_s/60"}
        self.assertTrue(want <= {p for j, p in self.spans(line[0]) if j == i})
        self.assertEqual({j for j, _ in self.spans(line[0])}, {i})  # every number of the pair is that one run's
        self.assertIn("hidden truth", line[0].text())
        self.assertIn("top 20 by last hour's plain counts", line[0].text())
        self.assertEqual([n.text() for n in line[0].walk() if "vd" in n.classes], [self.entries[i]["k"]["20"]["paired"]["verdict"]])
        # its own p.one, after the 27/27 and 18/25 pair
        kids = [n for n in step.find_all("div", "txt")[0].kids if isinstance(n, k8.Node)]
        self.assertLess(kids.index(step.find_all("div", "pair")[0]), kids.index(line[0]))
        chip = step.find_all("div", "st")[0].text()
        self.assertIn("{:.1f} times as often as chance against cells that got stuck in the same half hour".format(
            ob.Decimal(self.entries[i]["lesson_persist"]["lift_window"]).quantize(ob.Decimal("0.1"), rounding=ob.ROUND_HALF_UP)), chip)
        self.assertIn("against the cells that ever got stuck", chip)
        self.assertTrue({"lesson_persist.lift_window", "lesson_persist.lift_ever"} <= have)
        # the pre-existing 'zone' words of step 4 are an open operator question: unchanged
        self.assertIn("zone average", step.text())
        self.assertIn("their zone's average", chip)


# ------------------------------------------------------------------------------------------------ (c)
class TestVerdicts(Overview):
    def test_c_every_verdict_word_shown_equals_the_json_verdict(self):
        vds = [n for n in self.root.walk() if n.tag == "span" and "vd" in n.classes]
        self.assertEqual(len(vds), 6)  # step 3, step 4, plus four rows of the figure
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

    def test_e_a_fresh_build_opens_with_the_two_sentences_and_equals_the_committed_page(self):
        page, left, errors = ob.build(ob.load_inputs(DATA, ROOT))  # the builder, in-process: an edit of PERSIST_OPEN shows here
        self.assertEqual((left, errors), ([], {}))
        root = k8.parse(page)
        blk = root.find_all("section", "pw")[0]
        self.assertEqual(blk.find_all("h2")[0].text(), "Does the map beat last hour's counts?")
        text = blk.find_all("p")[0].text()
        self.assertTrue(text.startswith(" ".join(OPEN)), text)
        self.assertEqual(page, k8.PAGE.read_text(encoding="utf-8"))
        kids = [n for n in root.find_all("div", "steps")[0].kids if isinstance(n, k8.Node)]
        pos = kids.index(blk)
        self.assertIn("Step 3", kids[pos - 1].text())
        self.assertIn("Step 4", kids[pos + 1].text())

    def test_e_guard_the_opening_sentence_still_matches_the_data(self):
        verdicts = {e["label"]: e["k"]["20"]["paired"]["verdict"] for e in self.entries if e["label"] in SHOWN}
        self.assertEqual(sorted(verdicts), sorted(SHOWN))
        msg = "the opening sentence of the block no longer matches the data: %s" % verdicts
        self.assertNotIn("beats", verdicts.values(), msg)
        self.assertEqual(sum(v == "worse" for v in verdicts.values()), 1, msg)
        self.assertNotIn("beats", [n.text() for n in self.root.walk() if "vd" in n.classes], msg)

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
        for n in blk.find_all("span", "pe"):  # the whisker scale's end labels: rendered from the data-derived bound, checked in test (i)
            rest = rest.replace(n.text(" "), " ", 1)
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


# ------------------------------------------------------------------------------------------------ (h) the window
class TestWindow(Overview):
    def test_h_every_minutes_span_renders_round_horizon_of_its_own_entry(self):
        spans = [n for n in self.root.find_all("b", "num") if (n.attrs.get("data-src") or "").endswith(".horizon_s/60")]
        self.assertEqual(len(spans), 6)  # step 3, step 4, four rows of the figure: one each
        seen = set()
        for n in spans:
            i, path = self.src_parts(n.attrs["data-src"])
            e = self.entries[i]
            self.assertEqual(n.text(), str(round(baseline_json(e["label"])["params"]["horizon_s"] / 60)), e["label"])
            seen.add((e["label"], n.text()))
        self.assertEqual(seen, {("s8b-medium-80-p03-07", "21"), ("closed-loop-sticky", "60"), ("s8e-long-w0.5", "21"), ("s10c-blind", "21")})

    def test_h_each_window_sentence_names_the_entry_it_uses(self):
        sentences = [n for n in self.root.find_all("p") if "over the next" in n.text()]
        self.assertEqual(len(sentences), 2)  # step 3 and step 4
        for node in sentences:
            spans = [n for n in node.find_all("b", "num") if (n.attrs.get("data-src") or "").endswith(".horizon_s/60")]
            self.assertEqual(len(spans), 1, node.text())
            mapped = {self.src_parts(n.attrs["data-src"])[0] for n in node.find_all("b", "num") if self.src_parts(n.attrs.get("data-src"))}
            self.assertEqual(mapped, {self.src_parts(spans[0].attrs["data-src"])[0]}, node.text())
        rows = self.root.find_all("div", "pr")
        for row in rows:
            if "data-nothing" in row.attrs:
                continue
            i = [e["label"] for e in self.entries].index(row.attrs["data-label"])
            mins = [n for n in row.find_all("b", "num") if n.attrs["data-src"].endswith("horizon_s/60")]
            self.assertEqual([self.src_parts(n.attrs["data-src"])[0] for n in mins], [i])
            self.assertIn("scored over %s minutes" % mins[0].text(), row.text())
        label = [f for f in self.root.find_all("figure")][0].attrs["aria-label"]
        self.assertIn("scored over 60 minutes", label)
        self.assertEqual(label.count("scored over 21 minutes"), 3)

    def test_h_no_following_hour_or_next_hour_on_either_page(self):
        js = (DOCS / "replay.js").read_text(encoding="utf-8")
        pieces = [self.html] + [v for name in ("VISIBLE_COPY", "HOVER_COPY") for s, e, v in s8i.scan_js(js)[0]
                                if s8i.const_span(js, name)[0] <= s <= s8i.const_span(js, name)[1]]
        for p in pieces:
            self.assertNotRegex(p.lower(), r"following hour|next hour")
        # the page's own wording of the scoring window is minutes: 'over the next N minutes'
        self.assertEqual(len(re.findall(r"over the next <b", self.html)), 2)

    def test_h_a_wrong_horizon_in_the_data_changes_the_rendered_minutes(self):
        with tempfile.TemporaryDirectory() as td:
            doc = k8.read_js_doc(DATA)
            doc["run_constants"]["baselines"][0]["horizon_s"] = 1800
            fx = k8.write_fixture(Path(td) / "fx", data_doc=doc)
            out = Path(td) / "o.html"
            rc, err = k8.run_builder(fx, out)
            self.assertEqual(rc, 0, err)
            root = k8.parse(out.read_text(encoding="utf-8"))
        mins = [n.text() for n in root.find_all("b", "num") if (n.attrs.get("data-src") or "").endswith(".baselines.0.horizon_s/60")]
        self.assertEqual(mins, ["30", "30"])  # the step-3 sentence and the row of that entry; nothing typed


# ------------------------------------------------------------------------------------------------ (i) the figure
def luminance(hexcolor):
    h = hexcolor.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


class TestFigure(Overview):
    def fig(self):
        return [f for f in self.root.find_all("figure") if "Top 20 right" in f.text()][0]

    def test_i_differences_are_in_points_with_a_rendered_scale_and_bold_verdicts(self):
        fig = self.fig()
        bound = max(max(abs(v) for v in e["k"]["20"]["paired"]["ci95"] + [e["k"]["20"]["paired"]["mean"]])
                    for e in self.entries if e["chance_all"] != 0)
        b = math.ceil(bound / 0.01 - 1e-9) * 0.01
        want = ["-%g points" % round(b * 100, 6), "0", "+%g points" % round(b * 100, 6)]
        rows = [r for r in fig.find_all("div", "pr") if "data-nothing" not in r.attrs]
        self.assertEqual(len(rows), 4)
        for row in rows:
            ends = row.find_all("span", "pe")
            self.assertEqual(len(ends), 1)
            self.assertEqual([c.text() for c in ends[0].kids if isinstance(c, k8.Node)], want)
            mean = [n for n in row.find_all("b", "num") if n.attrs["data-src"].endswith("paired.mean")][0]
            self.assertTrue(mean.text().endswith(" points"), mean.text())
            self.assertNotIn("%", mean.text())
            self.assertIn("likely range", row.text())
        self.assertEqual(fig.attrs["data-scale-bound"], "%g" % b)
        css = self.html
        self.assertRegex(css, r"\.vd\{[^}]*font-weight:700")
        self.assertEqual(len([n for n in fig.walk() if "vd" in n.classes]), 4)

    def test_i_the_counts_bar_is_a_darker_neutral_with_contrast_three_to_one(self):
        m = re.search(r"\.pbf\.k1\{background:var\((--[\w-]+)\)\}", self.html)
        self.assertTrue(m)
        var = lambda name: re.search(re.escape(name) + r":(#[0-9a-fA-F]{6})", self.html).group(1)
        self.assertGreaterEqual(contrast(var(m.group(1)), var("--paper-deep")), 3.0)
        self.assertRegex(self.html, r"\.pkey i\.k1\{background:var\(%s\)\}" % re.escape(m.group(1)))

    def test_i_no_paired_verdict_text_on_either_page(self):
        js = (DOCS / "replay.js").read_text(encoding="utf-8")
        self.assertNotIn("paired verdict", self.html.lower())
        for name in ("VISIBLE_COPY", "HOVER_COPY"):
            a, b = s8i.const_span(js, name)
            for s, e, v in s8i.scan_js(js)[0]:
                if a <= s <= b:
                    self.assertNotIn("paired verdict", v.lower())
        self.assertIn("the line is the likely range of the gap", self.html)


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
        self.assertIn("the map is " + k["paired"]["verdict"] + ".", text)
        self.assertIn("over the next %d minutes" % round(e["s8b-medium-80-p03-07"]["horizon_s"] / 60), text)
        self.assertNotIn("paired", text)
        self.assertIn("not this shift", text)
        self.assertIn("hidden truth", text)
        self.assertIn("results/fleet/baselines_s8b-medium-80-p03-07.json", snap["hovers"]["sentence-persist"])
        self.assertIn("over the next 21 minutes", snap["hovers"]["sentence-persist"])
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

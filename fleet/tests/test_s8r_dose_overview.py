"""S8R-DOSE-OVERVIEW: run_constants.dose_response (exporter) and the 'When a map helps' figure on the overview page.

(a) the exporter parses the four committed summaries in the order given; (b) a summary without map_a32 raises naming the file;
(c) the refresh mode adds or replaces only the keys it was given; (d) the figure and its two sentences in the built page;
(e) the committed page is a fresh build; (f) the rest of the page is unchanged (digit multiset of master's page).
Reverting the feature (master's replay_export.py, overview_build.py, data.js and index.html) fails every class here.
"""
import contextlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fleet import overview_build as ob  # noqa: E402
from fleet import replay_export as rx  # noqa: E402
from fleet.tests import test_s8k_overview as k  # noqa: E402

SPECS = ["p 0.3-0.7=results/closed_loop/summary.json", "p 0.6-0.9=results/closed_loop_p06_09/summary.json",
         "p 0.8-0.95=results/closed_loop_p08_095/summary.json", "p 0.9-0.99=results/closed_loop_sticky/summary.json"]
DATA = ROOT / "docs/replay/data.js"
ARMS = ("none", "map_a4", "map_a32", "oracle")
# digit counts of the overview page before S8R (git show 3dca770:docs/overview/index.html)
# S10H adds four typed "top 20" (two sentences, steps 3 and 4), hence one more 2 and 0 each four times: 542 zeros, 357 twos
MASTER_DIGITS = {"0": 542, "1": 1020, "2": 357, "3": 200, "4": 211, "5": 230, "6": 179, "7": 122, "8": 140, "9": 120}


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = rx.main(argv)
        except SystemExit as e:
            rc = e.code
    return rc, err.getvalue()


@contextlib.contextmanager
def in_root():
    old = os.getcwd()
    os.chdir(ROOT)
    try:
        yield
    finally:
        os.chdir(old)


def summary(spec):
    return json.loads((ROOT / spec.split("=", 1)[1]).read_text(encoding="utf-8"))


def strip_dose(text):
    """data.js text without run_constants.dose_response (the pre-S8R file)."""
    key = ',"dose_response":'
    assert text.count(key) == 1
    start = text.index(key)
    _, end = json.JSONDecoder().raw_decode(text, start + len(key))
    return text[:start] + text[end:]


# ------------------------------------------------------------------------------------------------ (a)
class TestExporterParses(unittest.TestCase):
    def test_four_summaries_in_the_order_given(self):
        with in_root():
            got = rx.dose_response_constant(SPECS)
        self.assertEqual([g["label"] for g in got], ["p 0.3-0.7", "p 0.6-0.9", "p 0.8-0.95", "p 0.9-0.99"])
        for g, spec in zip(got, SPECS):
            s = summary(spec)
            p = json.loads(s["disturb"])["floor"]["p"]
            self.assertEqual((g["p_lo"], g["p_hi"]), tuple(p))
            self.assertEqual(g["source"], spec.split("=", 1)[1])
            self.assertEqual(list(g), ["label", "p_lo", "p_hi", "floor_loss", "arms", "source"])
            self.assertEqual(list(g["arms"]), list(ARMS))
            loss = s["arms"]["undisturbed"]["pick_rate_mean"] - s["arms"]["none"]["pick_rate_mean"]
            self.assertAlmostEqual(g["floor_loss"], loss, places=9)
            for a in ARMS:
                row, src = g["arms"][a], s["arms"][a]
                self.assertEqual(list(row), ["pick_rate_mean", "ci95", "share", "share_ci95"])
                self.assertEqual(row["pick_rate_mean"], src["pick_rate_mean"])
                self.assertEqual(row["ci95"], src["pick_rate_ci95"])
                if a == "none":
                    self.assertIsNone(row["share"])
                    self.assertIsNone(row["share_ci95"])
                else:
                    sh = src["share_of_floor_loss_recovered"]
                    self.assertEqual(row["share"], sh["share"])
                    self.assertEqual(row["share_ci95"], sh["ci95"])
                    self.assertEqual(g["floor_loss"], sh["mean_loss"])

    def test_reversed_call_gives_reversed_order(self):
        with in_root():
            fwd = rx.dose_response_constant(SPECS)
            rev = rx.dose_response_constant(SPECS[::-1])
        self.assertEqual(rev, fwd[::-1])

    def test_label_is_split_on_the_first_equals_sign(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "s.json"
            shutil.copy(ROOT / SPECS[0].split("=", 1)[1], p)
            got = rx.dose_response_constant(["x y=" + str(p)])
            self.assertEqual((got[0]["label"], got[0]["source"]), ("x y", str(p)))
            d2 = Path(td) / "a=b"
            d2.mkdir()
            shutil.copy(p, d2 / "s.json")
            got = rx.dose_response_constant(["lab=" + str(d2 / "s.json")])  # a later "=" belongs to the path
            self.assertEqual((got[0]["label"], got[0]["source"]), ("lab", str(d2 / "s.json")))

    def test_no_specs_is_none_and_bad_spec_raises(self):
        self.assertIsNone(rx.dose_response_constant(None))
        with self.assertRaisesRegex(ValueError, "LABEL=PATH"):
            rx.dose_response_constant(["no-equals-sign"])

    def test_full_export_path_accepts_the_flag(self):
        import inspect
        self.assertIn("dose_response", inspect.signature(rx.build_payload).parameters)
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "d.js"
            out.write_text(strip_dose(DATA.read_text(encoding="utf-8")), encoding="utf-8")
            with in_root():
                rc, err = run_main(["--refresh-constants-only", "--out", str(out)] + [x for s in SPECS for x in ("--dose-response", s)])
            self.assertEqual(rc, 0, err)

    def test_mean_loss_disagreement_raises_naming_the_file(self):
        with tempfile.TemporaryDirectory() as td:
            doc = summary(SPECS[1])
            doc["arms"]["map_a4"]["share_of_floor_loss_recovered"]["mean_loss"] += 0.5
            p = Path(td) / "skew.json"
            p.write_text(json.dumps(doc), encoding="utf-8")
            with self.assertRaises(ValueError) as cm:
                rx.dose_response_constant(["x=" + str(p)])
            self.assertIn("skew.json", str(cm.exception))


# ------------------------------------------------------------------------------------------------ (b)
class TestMissingArm(unittest.TestCase):
    def fixture(self, td, arm):
        doc = summary(SPECS[2])
        del doc["arms"][arm]
        p = Path(td) / ("no_%s.json" % arm)
        p.write_text(json.dumps(doc), encoding="utf-8")
        return p

    def test_summary_without_map_a32_raises_naming_file_and_arm(self):
        with tempfile.TemporaryDirectory() as td:
            p = self.fixture(td, "map_a32")
            with self.assertRaises(ValueError) as cm:
                rx.dose_response_constant(["x=" + str(p)])
            self.assertIn(str(p), str(cm.exception))
            self.assertIn("map_a32", str(cm.exception))

    def test_every_other_required_arm_is_checked_too(self):
        with tempfile.TemporaryDirectory() as td:
            for arm in ("none", "map_a4", "oracle", "undisturbed"):
                p = self.fixture(td, arm)
                with self.assertRaisesRegex(ValueError, arm):
                    rx.dose_response_constant(["x=" + str(p)])

    def test_cli_exits_non_zero_with_the_message_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            p = self.fixture(td, "map_a32")
            out = Path(td) / "data.js"
            text = strip_dose(DATA.read_text(encoding="utf-8"))
            out.write_text(text, encoding="utf-8")
            rc, err = run_main(["--refresh-constants-only", "--out", str(out), "--dose-response", "x=" + str(p)])
            self.assertNotEqual(rc, 0)
            self.assertIn("no_map_a32.json", err)
            self.assertIn("map_a32", err)
            self.assertEqual(out.read_text(encoding="utf-8"), text)


# ------------------------------------------------------------------------------------------------ (c)
class TestRefresh(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.out = Path(self.td.name) / "data.js"
        self.full = DATA.read_text(encoding="utf-8")
        self.pre = strip_dose(self.full)
        self.out.write_text(self.pre, encoding="utf-8")
        self.args = [x for s in SPECS for x in ("--dose-response", s)]

    def refresh(self, *more):
        with in_root():
            return run_main(["--refresh-constants-only", "--out", str(self.out)] + list(more))

    def test_pre_change_file_has_no_key_and_refresh_reproduces_the_committed_file_byte_for_byte(self):
        self.assertNotIn("dose_response", rx.read_data_js(self.out)["run_constants"])
        rc, err = self.refresh(*self.args)
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.out.read_text(encoding="utf-8"), self.full)

    def test_every_other_key_is_unchanged_including_lessons_long(self):
        before = rx.read_data_js(self.out)
        rc, err = self.refresh(*self.args)
        self.assertEqual(rc, 0, err)
        after = rx.read_data_js(self.out)
        self.assertEqual(set(after), set(before))
        for key in before:
            if key != "run_constants":
                self.assertEqual(json.dumps(after[key], sort_keys=True), json.dumps(before[key], sort_keys=True), key)
        self.assertEqual(set(after["run_constants"]) - set(before["run_constants"]), {"dose_response"})
        for key, val in before["run_constants"].items():
            self.assertEqual(json.dumps(after["run_constants"][key], sort_keys=True), json.dumps(val, sort_keys=True), key)
        self.assertEqual(after["run_constants"]["lessons_long"]["persist_graded"], 25)
        self.assertEqual(len(after["run_constants"]["dose_response"]), 4)

    def test_replacing_an_existing_entry_changes_only_that_value_by_text(self):
        self.assertEqual(self.refresh(*self.args)[0], 0)
        rev = [x for s in SPECS[::-1] for x in ("--dose-response", s)]
        key = '"dose_response":'
        a = self.out.read_text(encoding="utf-8")
        s0 = a.index(key) + len(key)
        _, e0 = json.JSONDecoder().raw_decode(a, s0)
        self.assertEqual(self.refresh(*rev)[0], 0)
        b = self.out.read_text(encoding="utf-8")
        s1 = b.index(key) + len(key)
        _, e1 = json.JSONDecoder().raw_decode(b, s1)
        self.assertEqual(a[:s0], b[:s1])
        self.assertEqual(a[e0:], b[e1:])
        self.assertEqual([e["label"] for e in rx.read_data_js(self.out)["run_constants"]["dose_response"]],
                         ["p 0.9-0.99", "p 0.8-0.95", "p 0.6-0.9", "p 0.3-0.7"])

    def test_both_flags_together_update_both_keys(self):
        long_ = str(ROOT / "results/fleet/hotspot_s8e-long-w0.5.json")
        rc, err = self.refresh("--lessons-long", long_, *self.args)
        self.assertEqual(rc, 0, err)
        rc_ = rx.read_data_js(self.out)["run_constants"]
        self.assertEqual(rc_["lessons_long"]["source"], long_)
        self.assertEqual(len(rc_["dose_response"]), 4)

    def test_neither_flag_is_an_argparse_error_and_changes_nothing(self):
        rc, err = self.refresh()
        self.assertEqual(rc, 2)
        self.assertIn("--dose-response", err)
        self.assertEqual(self.out.read_text(encoding="utf-8"), self.pre)

    def test_size_cap_is_respected(self):
        with in_root(), self.assertRaisesRegex(ValueError, "byte cap"):
            rx.refresh_constants(self.out, None, SPECS, max_bytes=len(self.pre))


# ------------------------------------------------------------------------------------------------ (d)
FIG_RE = re.compile(r"(?:^|;)\s*bottom:([-\d.]+)%;height:([-\d.]+)%")
NAME_DIGITS = re.compile(r"\balpha \d+\b|\b95%")  # an arm's name and the interval level are labels, not measurements


def verdict(ci):
    return "hurts" if ci[1] < 0 else ("helps" if ci[0] > 0 else "within noise")


def geometry(node):
    m = FIG_RE.search(node.attrs["style"])
    return float(m.group(1)), float(m.group(2))


class Fig(k.Committed):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dose = cls.inputs[ob.DATA]["run_constants"]["dose_response"]
        figs = [n for n in cls.root.find_all("figure") if n.attrs.get("role") == "img"
                and (n.attrs.get("aria-label") or "").startswith("When a map helps")]
        assert len(figs) == 1, len(figs)
        cls.fig = figs[0]
        cls.wrap = cls.fig.parent
        cls.says = cls.wrap.find_all("p", "dose-says")

    def resolves(self, node):
        src = node.attrs["data-src"]
        self.assertEqual(node.text(), ob.format_value(src, ob.resolve(src, self.inputs)), src)
        self.assertIn(".dose_response.", src)


class TestFigure(Fig):
    def test_placement_after_the_sticky_bars_inside_the_sandbox_step(self):
        step = [s for s in self.root.find_all("div", "step") if s.find_all("div", "bars")]
        self.assertEqual(len(step), 1)
        pic = self.wrap.parent
        self.assertIn("pic", pic.classes)
        kids = [x for x in pic.kids if isinstance(x, k.Node)]
        self.assertEqual([x.classes[0] if x.classes else x.tag for x in kids], ["bars", "legend", "dosewrap"])
        self.assertIn(pic, step[0].find_all("div", "pic"))
        self.assertEqual(self.html.count("<figure"), 2)  # S10H: the dose figure and the persistence figure

    def test_twelve_bars_four_regimes_three_settings_in_data_order(self):
        bars = self.fig.find_all("span", "dbar")
        self.assertEqual(len(bars), 12)
        self.assertEqual([(b.attrs["data-regime"], b.attrs["data-arm"]) for b in bars],
                         [(e["label"], a) for e in self.dose for a in ("map_a4", "map_a32", "oracle")])
        for b in bars:
            e = next(x for x in self.dose if x["label"] == b.attrs["data-regime"])
            arm = e["arms"][b.attrs["data-arm"]]
            self.assertEqual(float(b.attrs["data-share"]), arm["share"])
            self.assertEqual((float(b.attrs["data-lo"]), float(b.attrs["data-hi"])), tuple(arm["share_ci95"]))

    def test_one_scale_covers_every_whisker_in_share_units(self):
        smin, smax = float(self.fig.attrs["data-scale-min"]), float(self.fig.attrs["data-scale-max"])
        self.assertEqual(self.fig.attrs["data-scale-unit"], "share")  # 1 = 100% of the floor loss, not percent
        los = [e["arms"][a]["share_ci95"][0] for e in self.dose for a in ARMS[1:]]
        his = [e["arms"][a]["share_ci95"][1] for e in self.dose for a in ARMS[1:]]
        self.assertLessEqual(smin, min(los))
        self.assertLessEqual(smin, -1.965)
        self.assertGreaterEqual(smax, max(his))
        self.assertGreaterEqual(smax, 0.5)
        self.assertLess(smin, 0.0)
        self.assertGreater(smax, 0.0)
        self.assertEqual(self.fig.find_all("div", "dgroups")[0].attrs["style"].count("repeat(%d" % len(self.dose)), 1)

    def test_no_bar_or_whisker_leaves_the_plot_box_and_geometry_matches_the_data(self):
        smin, smax = float(self.fig.attrs["data-scale-min"]), float(self.fig.attrs["data-scale-max"])
        span = smax - smin
        eps = 1e-3
        for col in self.fig.find_all("div", "dcol"):
            bar, wh = col.find_all("span", "dbar")[0], col.find_all("span", "dwh")[0]
            share, lo, hi = float(bar.attrs["data-share"]), float(bar.attrs["data-lo"]), float(bar.attrs["data-hi"])
            b0, h0 = geometry(bar)
            self.assertGreaterEqual(b0, -eps)
            self.assertLessEqual(b0 + h0, 100 + eps)
            self.assertAlmostEqual(b0, (min(0.0, share) - smin) / span * 100, delta=eps)
            self.assertAlmostEqual(h0, abs(share) / span * 100, delta=eps)
            b1, h1 = geometry(wh)
            self.assertGreaterEqual(b1, -eps)
            self.assertLessEqual(b1 + h1, 100 + eps)
            self.assertAlmostEqual(b1, (lo - smin) / span * 100, delta=eps)
            self.assertAlmostEqual(h1, (hi - lo) / span * 100, delta=eps)
            self.assertGreaterEqual(h1, 0)
        self.assertEqual(len(self.fig.find_all("span", "dwh")), 12)

    def test_zero_line_in_every_group_at_the_zero_of_the_scale(self):
        smin, smax = float(self.fig.attrs["data-scale-min"]), float(self.fig.attrs["data-scale-max"])
        zeros = self.fig.find_all("span", "dzero")
        self.assertEqual(len(zeros), len(self.dose))
        for z in zeros:
            m = re.search(r"bottom:([-\d.]+)%", z.attrs["style"])
            self.assertAlmostEqual(float(m.group(1)), (0 - smin) / (smax - smin) * 100, delta=1e-3)

    def test_role_img_and_a_data_derived_aria_label(self):
        label = self.fig.attrs["aria-label"]
        self.assertEqual(self.fig.attrs["role"], "img")
        for e in self.dose:
            self.assertIn(e["label"], label)
            self.assertIn("%s lines per hour lost" % ob.format_value("%s:run_constants.dose_response.0.floor_loss" % ob.DATA,
                                                                       e["floor_loss"]), label)
            for a in ARMS[1:]:
                shown = "%s %s" % (ob.arm_name(a), "{:.0f}%".format(e["arms"][a]["share"] * 100))
                self.assertIn(shown, label)

    def test_every_number_of_figure_and_sentences_is_a_num_span_that_resolves(self):
        nums = self.wrap.find_all("b", "num")
        self.assertGreater(len(nums), 30)
        for n in nums:
            self.resolves(n)
        # the numbers asked for: loss and p range per regime, 12 shares
        have = {n.attrs["data-src"].split(":", 1)[1] for n in nums}
        for i in range(len(self.dose)):
            for f in ("floor_loss", "p_lo", "p_hi"):
                self.assertIn("run_constants.dose_response.%d.%s" % (i, f), have)
            for a in ARMS[1:]:
                self.assertIn("run_constants.dose_response.%d.arms.%s.share" % (i, a), have)
        # and nothing else with a digit: strip the num spans and the labels (alpha N, 95%)
        stripped = []
        for node in self.wrap.walk():
            if node.tag in ("style", "b"):
                continue
            stripped += [t for t in node.kids if isinstance(t, str) and node.tag != "style"]
        rest = NAME_DIGITS.sub(" ", " ".join(stripped))
        self.assertEqual(re.findall(r"\S*\d\S*", rest), [])

    def test_header_of_each_group_reads_loss_and_p_range(self):
        heads = [g.find_all("div", "dgh")[0].text() for g in self.fig.find_all("div", "dg")]
        self.assertEqual(heads, ["6.1 lines/h lost, p 0.3-0.7", "15.7 lines/h lost, p 0.6-0.9",
                                 "26.2 lines/h lost, p 0.8-0.95", "37.5 lines/h lost, p 0.9-0.99"])

    def test_sentences_follow_the_verdict_rule(self):
        self.assertEqual(len(self.says), 2)  # exactly two sentences under the figure
        s1, s2 = self.says
        want = {"hurts": [], "helps": [], "within noise": []}
        for e in self.dose:
            want[verdict(e["arms"]["map_a32"]["share_ci95"])].append(e["label"])
        self.assertEqual(want, {"hurts": ["p 0.3-0.7"], "within noise": ["p 0.6-0.9"], "helps": ["p 0.8-0.95", "p 0.9-0.99"]})
        got = {"hurts": [], "helps": [], "within noise": []}
        for sp in s1.find_all("span", "dv"):
            got[sp.attrs["data-verdict"]].append(sp.attrs["data-regime"])
        self.assertEqual(got, want)
        text = s1.text()
        self.assertTrue(text.startswith("Map alpha 32 hurts at p 0.3-0.7 (share -92%), is within noise at p 0.6-0.9 (share -10%, interval "))
        self.assertIn("and helps at p 0.8-0.95 (share 15%) and p 0.9-0.99 (share 11%).", text)

    def test_oracle_sentence_is_the_beyond_noise_rule_and_names_the_point_estimate_exception(self):
        s2 = [p for p in self.says if p.attrs.get("data-says") == "oracle"][0]
        text = s2.text()
        # independent computation of the rule
        beats, level = [], []
        for e in self.dose:
            o = e["arms"]["oracle"]
            for a in ("map_a4", "map_a32"):
                m = e["arms"][a]
                if m["share_ci95"][0] > o["share_ci95"][1]:
                    beats.append((e["label"], a))
                elif m["share"] >= o["share"]:
                    level.append((e["label"], a))
        self.assertEqual(beats, [])
        self.assertEqual(level, [("p 0.6-0.9", "map_a4")])
        self.assertEqual(text, "No map setting beats the oracle beyond noise: map alpha 4 at p 0.6-0.9 has the higher point share "
                               "(16% against 14%) but the intervals overlap.")
        self.assertNotIn("No setting beats", text)
        # the overlap claim itself
        e = self.dose[1]
        self.assertLessEqual(e["arms"]["map_a4"]["share_ci95"][0], e["arms"]["oracle"]["share_ci95"][1])
        self.assertLessEqual(e["arms"]["oracle"]["share_ci95"][0], e["arms"]["map_a4"]["share_ci95"][1])


class TestRulesOnChangedData(unittest.TestCase):
    """The sentences and the scale are computed from the data, not typed."""

    def inputs(self):
        return ob.load_inputs(DATA, ROOT)

    def test_a_real_beat_is_stated_as_one(self):
        inp = self.inputs()
        e = inp[ob.DATA]["run_constants"]["dose_response"][2]
        e["arms"]["map_a4"]["share"], e["arms"]["map_a4"]["share_ci95"] = 0.6, [0.5, 0.7]  # lo 0.5 > oracle hi 0.341
        text = k.parse(ob.dose_html(inp)).find_all("p", "dose-says")
        s2 = [p for p in text if p.attrs.get("data-says") == "oracle"][0].text()
        self.assertTrue(s2.startswith("Map alpha 4 beats the oracle at p 0.8-0.95"), s2)
        self.assertNotIn("No map setting beats", s2)

    def test_a_flipped_verdict_moves_the_regime(self):
        inp = self.inputs()
        inp[ob.DATA]["run_constants"]["dose_response"][0]["arms"]["map_a32"]["share_ci95"] = [-0.2, 0.3]
        wrap = k.parse(ob.dose_html(inp))
        spans = wrap.find_all("span", "dv")
        self.assertEqual([(s.attrs["data-regime"], s.attrs["data-verdict"]) for s in spans],
                         [("p 0.3-0.7", "within noise"), ("p 0.6-0.9", "within noise"), ("p 0.8-0.95", "helps"), ("p 0.9-0.99", "helps")])
        s1 = [p for p in wrap.find_all("p", "dose-says") if p.attrs.get("data-says") == "target"][0].text()
        self.assertEqual(s1.count("is within noise at"), 1)  # a run of equal verdicts shares one verb
        self.assertNotIn("hurts", s1)

    def test_scale_grows_with_a_longer_whisker(self):
        inp = self.inputs()
        inp[ob.DATA]["run_constants"]["dose_response"][0]["arms"]["map_a32"]["share_ci95"][0] = -3.4
        fig = k.parse(ob.dose_html(inp)).find_all("figure")[0]
        self.assertLessEqual(float(fig.attrs["data-scale-min"]), -3.4)

    def test_missing_dose_response_refuses_to_build(self):
        with tempfile.TemporaryDirectory() as td:
            def drop(name, doc):
                if name == k.D:
                    del doc["run_constants"]["dose_response"]
            fx = k.write_fixture(Path(td) / "fx", mutate=drop)
            out = Path(td) / "o.html"
            rc, err = k.run_builder(fx, out)
            self.assertNotEqual(rc, 0)
            self.assertFalse(out.exists())
            self.assertIn("dose_response", err)

    def test_the_builder_still_reads_exactly_four_inputs(self):
        self.assertEqual(len(ob.INPUTS), 4)
        self.assertNotIn("closed_loop/summary", " ".join(ob.INPUTS))


# ------------------------------------------------------------------------------------------------ (e), (f)
class TestPage(unittest.TestCase):
    def test_committed_page_is_a_byte_identical_rebuild(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "i.html"
            rc, err = k.run_builder(ROOT, out)
            self.assertEqual(rc, 0, err)
            self.assertEqual(out.read_bytes(), k.PAGE.read_bytes())

    def test_rest_of_the_page_has_the_digits_of_master(self):
        html = k.PAGE.read_text(encoding="utf-8")
        self.assertEqual(html.count("<!-- dose-start -->"), 1)
        self.assertEqual(html.count("<!-- dose-end -->"), 1)
        self.assertEqual(html.count("<!-- explorer-start -->"), 1)  # S11A: the explorer block is generated, so it is stripped too
        self.assertEqual(html.count("<!-- explorer-end -->"), 1)
        rest = re.sub(r"<!-- dose-start -->.*<!-- dose-end -->\n?", "", html, flags=re.S)
        rest = re.sub(r"<!-- explorer-start -->.*<!-- explorer-end -->\n?", "", rest, flags=re.S)
        self.assertNotIn("dosewrap", rest)
        # S10H: the persistence block and every number it (and steps 3 and 4) reads from run_constants.baselines are generated too
        self.assertEqual(html.count("<!-- persist-start -->"), 1)
        rest = re.sub(r"<!-- persist-start -->.*<!-- persist-end -->\n?", "", rest, flags=re.S)
        rest = re.sub(r'<b class="num" data-src="[^"]*run_constants\.baselines\.[^"]*">[^<]*</b>', "", rest)
        rest = re.sub(r'<span class="vd" data-src="[^"]*run_constants\.baselines\.[^"]*">[^<]*</span>', "", rest)
        self.assertEqual(dict(Counter(re.findall(r"\d", rest))), MASTER_DIGITS)
        self.assertIn("results/closed_loop_sticky/summary.json", rest)  # footer source list unchanged
        self.assertNotIn("closed_loop_p0", rest)

    def test_dose_response_is_in_the_committed_data_in_the_asked_order(self):
        dose = rx.read_data_js(DATA)["run_constants"]["dose_response"]
        self.assertEqual([d["label"] for d in dose], ["p 0.3-0.7", "p 0.6-0.9", "p 0.8-0.95", "p 0.9-0.99"])
        self.assertEqual([d["source"] for d in dose], [s.split("=", 1)[1] for s in SPECS])
        self.assertEqual(rx.read_data_js(DATA)["meta"]["schema"], "replay/4")


if __name__ == "__main__":
    unittest.main()

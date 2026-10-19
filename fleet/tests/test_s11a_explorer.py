"""S11A-EXPLORER: run_constants.explorer (exporter) and the 'Try it' section of docs/overview/index.html.

(a) the floor triples and fields against the five closed-loop summaries, the sweep stats against scripts/evaluate.summarise;
(b) dose_verdict against the 12 S8R dose verdicts; (c) the --explorer flag: round trip and refresh-preserves-explorer on copies;
(d) the section: markers, opening sentences, digit / banned-word / class rules, data-src spans; (e) a stub-DOM run of the section's
own script in Node (modelled on test_s8j_dom.py, same node rule) that drives every control stop.
"""
import contextlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fleet import overview_build as ob  # noqa: E402
from fleet import replay_export as rx  # noqa: E402
from fleet.tests import test_s8i_page as s8i  # noqa: E402
from fleet.tests import test_s8k_overview as k  # noqa: E402
from fleet.tests import test_replay_export as tre  # noqa: E402
from fleet.tests.test_s8j_dom import HARNESS, need_node  # noqa: E402

_spec = importlib.util.spec_from_file_location("evaluate_script", ROOT / "scripts" / "evaluate.py")
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)

DATA = ROOT / "docs" / "replay" / "data.js"
SPECS = ["p 0.3-0.7=results/closed_loop/summary.json", "p 0.6-0.9=results/closed_loop_p06_09/summary.json",
         "p 0.8-0.95=results/closed_loop_p08_095/summary.json", "p 0.9-0.99=results/closed_loop_sticky/summary.json"]
# (regime key, word, p range, steps, path): the brief's five files, written out here independently of the exporter
FILES = [("mild", "mild", (0.3, 0.7), 500, "results/closed_loop/summary.json"),
         ("medium", "medium", (0.6, 0.9), 500, "results/closed_loop_p06_09/summary.json"),
         ("sticky", "sticky", (0.8, 0.95), 500, "results/closed_loop_p08_095/summary.json"),
         ("very_sticky", "very sticky", (0.9, 0.99), 500, "results/closed_loop_sticky/summary.json"),
         ("very_sticky", "very sticky", (0.9, 0.99), 1500, "results/closed_loop_sticky_1500/summary.json")]
KEPT = {"none", "map_a4", "map_a8", "map_a16", "map_a32", "oracle", "undisturbed"}
OPEN = ["These are recorded measurements of a simulated warehouse, not a live simulation.", "The operator can change that later."]


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def explorer_span(text):
    """(start, end) of the value of run_constants.explorer in a data.js text."""
    key = '"explorer":'
    assert text.count(key) == 1
    start = text.index(key) + len(key)
    _, end = json.JSONDecoder().raw_decode(text, start)
    return start, end


def delete_explorer(text):
    """data.js text without run_constants.explorer: the `,"explorer":{...}` span is spliced out (S10H: "baselines" follows it,
    so the span ends at a comma or at the closing brace)."""
    start, end = explorer_span(text)
    key_start = start - len('"explorer":')
    assert text[key_start - 1] == "," and text[end] in ",}"
    return text[:key_start - 1] + text[end:]


@contextlib.contextmanager
def cwd(path):
    old = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = rx.main(argv)
        except SystemExit as e:
            rc = e.code
    return rc, err.getvalue()


class Committed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ex = rx.read_data_js(DATA)["run_constants"]["explorer"]
        cls.html = k.PAGE.read_text(encoding="utf-8")


# ------------------------------------------------------------------------------------------------ (a) the data
class TestFloor(Committed):
    def expected(self):
        out = {}
        for key, word, p, steps, path in FILES:
            doc = read(path)
            for arm in doc["arms"]:
                if arm in KEPT:
                    out[(key, steps, arm)] = (path, doc, doc["arms"][arm])
        return out

    def test_triples_equal_the_set_derived_from_the_five_summaries(self):
        exp = self.expected()
        got = [(e["regime"], e["steps"], e["arm"]) for e in self.ex["floor"]]
        self.assertEqual(len(got), len(set(got)))
        self.assertEqual(set(got), set(exp))
        self.assertEqual(len(got), 31)
        # the arms the brief names as absent are absent, not zero or null
        for gone in (("very_sticky", 500, "map_a8"), ("mild", 500, "map_a16"), ("very_sticky", 1500, "map_a8"),
                     ("very_sticky", 1500, "map_a16")):
            self.assertNotIn(gone, got)
        for arm in ("map_a2", "map_a64"):
            self.assertNotIn(arm, {e["arm"] for e in self.ex["floor"]})
        self.assertEqual({e["arm"] for e in self.ex["floor"] if e["steps"] == 1500}, {"none", "map_a4", "map_a32", "oracle", "undisturbed"})
        self.assertTrue(all(isinstance(e["mean"], float) and e["n"] == 30 for e in self.ex["floor"]))

    def test_each_entry_matches_the_source_json(self):
        exp = self.expected()
        for e in self.ex["floor"]:
            path, doc, row = exp[(e["regime"], e["steps"], e["arm"])]
            self.assertEqual(e["src"], "%s:arms.%s" % (path, e["arm"]))
            self.assertEqual((e["p_lo"], e["p_hi"]), tuple(json.loads(doc["disturb"])["floor"]["p"]))
            self.assertEqual(e["mean"], row["pick_rate_mean"])
            self.assertEqual([e["ci_lo"], e["ci_hi"]], row["pick_rate_ci95"])
            self.assertEqual(e["n"], row["n"])
            sh = row.get("share_of_floor_loss_recovered")
            if e["arm"] in ("none", "undisturbed"):
                self.assertEqual((e["share"], e["share_ci_lo"], e["share_ci_hi"]), (None, None, None))
            else:
                self.assertEqual((e["share"], e["share_ci_lo"], e["share_ci_hi"]), (sh["share"], sh["ci95"][0], sh["ci95"][1]))
            self.assertEqual(list(e), ["regime", "p_lo", "p_hi", "steps", "arm", "mean", "ci_lo", "ci_hi", "n", "share",
                                       "share_ci_lo", "share_ci_hi", "src"])

    def test_axes_carry_every_label_value(self):
        ax = self.ex["axes"]
        self.assertEqual([(r["key"], r["word"], (r["p_lo"], r["p_hi"])) for r in ax["regimes"]],
                         [(key, word, p) for key, word, p, steps, _ in FILES if steps == 500])
        self.assertEqual([a["key"] for a in ax["arms"]], ["none", "map_a4", "map_a8", "map_a16", "map_a32", "oracle"])
        for a in ax["arms"]:
            alpha = read("results/closed_loop_sticky/summary.json")["arms"].get(a["key"], {}).get("alpha")
            if alpha is None and a["key"] != "none":
                alpha = read("results/closed_loop_p06_09/summary.json")["arms"][a["key"]]["alpha"]
            self.assertEqual(a["alpha"], alpha, a["key"])
        self.assertEqual(ax["arms"][5]["alpha"], 4)  # oracle is alpha 4 in every summary
        self.assertEqual(ax["steps"], [500, 1500])
        self.assertEqual(ax["density"], read("results/sweeps/density.json")["definition"]["grid"])
        self.assertEqual(ax["breakdown"], read("results/sweeps/breakdown.json")["definition"]["grid"])
        self.assertEqual(ax["ci_level"], 95)

    def test_a_fresh_export_equals_the_committed_key_from_any_cwd(self):
        with tempfile.TemporaryDirectory() as td, cwd(td):
            self.assertEqual(rx.explorer_constant(), self.ex)  # resolved from the repo root, not the cwd


class TestSweeps(Committed):
    def test_density_stats_equal_evaluate_summarise(self):
        doc = read("results/sweeps/density.json")
        d = self.ex["sweeps"]["density"]
        self.assertEqual(d["policy"], "cta")
        self.assertIn("results/sweeps/density.json", d["src"])
        self.assertIn("policy=cta", d["src"])
        self.assertEqual(d["pickers_per_agv"], 0.5)
        self.assertEqual([p["point"] for p in d["points"]], doc["definition"]["grid"])
        for p in d["points"]:
            rows = [r for r in doc["rows"] if r["policy"] == "cta" and r["point"] == p["point"]]
            s = ev.summarise([r["pick_rate"] for r in rows])
            self.assertAlmostEqual(p["mean"], s["mean"], delta=1e-9)
            self.assertAlmostEqual(p["ci_lo"], s["ci95_low"], delta=1e-9)
            self.assertAlmostEqual(p["ci_hi"], s["ci95_high"], delta=1e-9)
            self.assertEqual(p["n"], s["n"])
            self.assertEqual(p["pickers"] / p["point"], d["pickers_per_agv"])
            self.assertEqual({r["n_agents"] for r in rows}, {p["point"] + p["pickers"]})

    def test_breakdown_stats_equal_evaluate_summarise_per_policy(self):
        doc = read("results/sweeps/breakdown.json")
        b = self.ex["sweeps"]["breakdown"]
        self.assertIn("results/sweeps/breakdown.json", b["src"])
        self.assertEqual(sorted(b["policies"]), ["cta", "stuck_aware_cta"])
        self.assertEqual({r["n_agents"] for r in doc["rows"]}, {b["robots"]})
        for pol, pts in b["policies"].items():
            self.assertEqual([p["point"] for p in pts], doc["definition"]["grid"])
            for p in pts:
                rows = [r for r in doc["rows"] if r["policy"] == pol and r["point"] == p["point"]]
                s = ev.summarise([r["pick_rate"] for r in rows])
                self.assertAlmostEqual(p["mean"], s["mean"], delta=1e-9)
                self.assertAlmostEqual(p["ci_lo"], s["ci95_low"], delta=1e-9)
                self.assertAlmostEqual(p["ci_hi"], s["ci95_high"], delta=1e-9)
                self.assertEqual(p["n"], s["n"])
        self.assertNotEqual(b["policies"]["cta"], b["policies"]["stuck_aware_cta"])


class TestVerdict(Committed):
    def test_dose_verdict_reproduces_the_twelve_s8r_dose_verdicts(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            import sprint8_tables as st
        finally:
            sys.path.pop(0)
        dose = rx.read_data_js(DATA)["run_constants"]["dose_response"]
        words = {"helps": "beats", "hurts": "worse", "within noise": "within noise"}
        seen = 0
        for i, entry in enumerate(dose):
            doc = read(SPECS[i].split("=", 1)[1])
            for arm in ("map_a4", "map_a32", "oracle"):
                ci = entry["arms"][arm]["share_ci95"]
                want = st.verdict(doc["arms"][arm]["share_of_floor_loss_recovered"])
                self.assertEqual(words[ob.dose_verdict(ci)], want, (entry["label"], arm))
                seen += 1
        self.assertEqual(seen, 12)

    def test_the_explorer_floor_agrees_with_dose_response(self):
        dose = rx.read_data_js(DATA)["run_constants"]["dose_response"]
        by = {(e["regime"], e["steps"], e["arm"]): e for e in self.ex["floor"]}
        for entry, key in zip(dose, ("mild", "medium", "sticky", "very_sticky")):
            for arm in ("map_a4", "map_a32", "oracle"):
                e = by[(key, 500, arm)]
                self.assertEqual((e["share_ci_lo"], e["share_ci_hi"]), tuple(entry["arms"][arm]["share_ci95"]))
                self.assertEqual(e["share"], entry["arms"][arm]["share"])


# ------------------------------------------------------------------------------------------------ (c) the flag
class TestFlag(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.out = Path(self.td.name) / "data.js"
        self.full = DATA.read_text(encoding="utf-8")
        self.pre = delete_explorer(self.full)
        self.out.write_text(self.pre, encoding="utf-8")

    def refresh(self, *more, where=None):
        with cwd(where or self.td.name):
            return run_main(["--refresh-constants-only", "--out", str(self.out)] + list(more))

    def test_data_js_is_one_line_and_the_explorer_key_is_second_to_last(self):
        self.assertEqual(self.full.count("\n"), 1)
        self.assertNotIn("explorer", self.pre)
        self.assertEqual(list(rx.read_data_js(DATA)["run_constants"])[-2:], ["explorer", "baselines"])  # S10H: baselines follows explorer
        self.assertEqual(rx.read_data_js(DATA)["meta"]["schema"], "replay/4")

    def test_round_trip_returns_the_committed_bytes(self):
        rc, err = self.refresh("--explorer")  # --explorer alone is accepted, from a cwd that is not the repo
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.out.read_text(encoding="utf-8"), self.full)

    def test_explorer_alone_rewrites_only_that_key(self):
        stale = self.full[:explorer_span(self.full)[0]] + "null" + self.full[explorer_span(self.full)[1]:]
        self.out.write_text(stale, encoding="utf-8")
        self.assertIsNone(rx.read_data_js(self.out)["run_constants"]["explorer"])
        rc, err = self.refresh("--explorer")
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.out.read_text(encoding="utf-8"), self.full)

    def test_dose_response_refresh_leaves_the_explorer_key_byte_identical(self):
        self.out.write_text(self.full, encoding="utf-8")
        before = self.full[slice(*explorer_span(self.full))]
        rc, err = self.refresh(*[x for s in SPECS for x in ("--dose-response", s)], where=ROOT)
        self.assertEqual(rc, 0, err)
        after = self.out.read_text(encoding="utf-8")
        self.assertEqual(after[slice(*explorer_span(after))], before)
        self.assertEqual(after, self.full)

    def test_dose_response_refresh_on_a_file_without_the_key_does_not_add_it(self):
        rc, err = self.refresh(*[x for s in SPECS for x in ("--dose-response", s)], where=ROOT)
        self.assertEqual(rc, 0, err)
        self.assertNotIn("explorer", self.out.read_text(encoding="utf-8"))

    def test_no_flag_at_all_is_still_an_argparse_error(self):
        rc, err = self.refresh()
        self.assertEqual(rc, 2)
        self.assertIn("--explorer", err)
        self.assertEqual(self.out.read_text(encoding="utf-8"), self.pre)

    def test_keys_are_inserted_in_the_full_export_order(self):
        text = delete_explorer(self.full)
        text = text.replace('"dose_response":', '"dose_response":', 1)
        start = text.index('"dose_response":')
        _, end = json.JSONDecoder().raw_decode(text, start + len('"dose_response":'))
        self.out.write_text(text[:start - 1] + text[end:], encoding="utf-8")  # neither dose_response nor explorer
        rc, err = self.refresh("--explorer", "--dose-response", SPECS[0], where=ROOT)
        self.assertEqual(rc, 0, err)
        keys = list(rx.read_data_js(self.out)["run_constants"])
        self.assertEqual(keys, [x for x in rx.RUN_CONSTANTS_ORDER if x in keys])
        self.assertEqual(keys[-3:], ["dose_response", "explorer", "baselines"])

    def test_the_flag_is_a_store_true_option(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), self.assertRaises(SystemExit):
            rx.main(["--help"])
        self.assertIn("--explorer", out.getvalue())


class TestFullExport(tre.Fixture):
    def test_a_full_export_writes_the_key_with_the_flag_and_null_without(self):
        self.assertIsNone(self.payload["run_constants"]["explorer"])
        p = rx.build_payload(self.dir, self.spec, "0", env_runner=tre.fake_env, run_dir_arg=str(self.dir), explorer=True)
        self.assertEqual(p["run_constants"]["explorer"], rx.explorer_constant())
        self.assertEqual(list(p["run_constants"])[-2:], ["explorer", "baselines"])  # S10H: baselines follows explorer
        self.assertEqual(list(p["run_constants"]), list(rx.RUN_CONSTANTS_ORDER))


# ------------------------------------------------------------------------------------------------ (d) the section
def section_text(html):
    a, b = html.index("<!-- explorer-start -->"), html.index("<!-- explorer-end -->")
    return html[a + len("<!-- explorer-start -->"):b]


class TestSection(Committed):
    def setUp(self):
        self.block = section_text(self.html)
        self.root = k.parse(self.block)
        self.sec = self.root.find_all("section")[0]

    def test_exactly_one_marker_pair_outside_the_dose_markers(self):
        for m in ("<!-- explorer-start -->", "<!-- explorer-end -->"):
            self.assertEqual(self.html.count(m), 1)
        d0, d1 = self.html.index("<!-- dose-start -->"), self.html.index("<!-- dose-end -->")
        e0, e1 = self.html.index("<!-- explorer-start -->"), self.html.index("<!-- explorer-end -->")
        self.assertTrue(e0 > d1 or e1 < d0)
        self.assertEqual(self.html.count("id=\"xp\""), 1)
        outside = self.html[:e0] + self.html[e1 + len("<!-- explorer-end -->"):]
        for needle in ("xp-", "Try it", "explorer"):
            self.assertNotIn(needle, outside)

    def test_the_template_only_gains_a_placeholder(self):
        self.assertEqual(ob.TEMPLATE.count("{explorer_html}"), 1)
        self.assertNotIn("Try it", ob.TEMPLATE)
        self.assertNotIn("xp-", ob.TEMPLATE)

    def test_page_is_a_fresh_build(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "i.html"
            rc, err = k.run_builder(ROOT, out)
            self.assertEqual(rc, 0, err)
            self.assertEqual(out.read_bytes(), k.PAGE.read_bytes())

    def test_the_two_opening_sentences_come_first_and_verbatim(self):
        ps = self.sec.find_all("p")
        self.assertEqual([p.text() for p in ps[:2]], OPEN)
        self.assertEqual(self.sec.find_all("h2")[0].text(), "Try it")
        text = " ".join(self.sec.text(" ").split())
        self.assertTrue(text.startswith("Try it " + OPEN[0] + " " + OPEN[1]), text[:200])
        for s in OPEN:
            self.assertEqual(self.html.count(s), 1)

    def test_no_forbidden_classes_no_b_num_no_const_copy(self):
        for n in self.sec.walk():
            self.assertFalse({"step", "cbox", "st", "num"} & set(n.classes), n.classes)
            self.assertNotEqual(n.tag, "b")
        scripts = [n for n in self.root.walk() if n.tag == "script"]
        js = [("".join(n.kids)) for n in scripts if not n.attrs.get("type")]
        self.assertEqual(len(js), 1)
        self.assertNotIn("const COPY", js[0])
        self.assertNotIn("const D ", js[0])
        self.assertEqual(self.html.count("const COPY"), 1)
        self.assertEqual(len(k.parse(self.html).find_all("b", "num")), len(k.num_elements(k.parse(self.html))))
        self.assertEqual(len(k.num_elements(self.root)), 0)

    def spans(self):
        return [n for n in self.sec.walk() if "data-src" in n.attrs]

    def test_every_number_span_resolves_inside_data_js_and_shows_the_formatted_value(self):
        inputs = ob.load_inputs(ROOT / "docs/replay/data.js", ROOT)
        spans = self.spans()
        self.assertGreater(len(spans), 30)
        for n in spans:
            src = n.attrs["data-src"]
            self.assertTrue(src.startswith("docs/replay/data.js:run_constants.explorer."), src)
            self.assertEqual(n.text(), ob.format_value(src, ob.resolve(src, inputs)), src)
            self.assertIn("xp-n", n.classes)
        # every digit of the visible text sits in such a span; none is typed
        stripped = []
        for t in self.sec.text_nodes():
            stripped.append(t)
        spans_txt = " ".join(n.text() for n in spans)
        text = " ".join(" ".join(stripped).split())
        for n in spans:
            text = text.replace(n.text(), " ", 1)
        self.assertEqual(re.findall(r"\S*\d\S*", text), [], spans_txt[:80])
        # the units: pick-rate one decimal, share whole percent, n an integer
        for n in spans:
            src, t = n.attrs["data-src"], n.text()
            if src.endswith((".mean", ".ci_lo", ".ci_hi")):
                self.assertRegex(t, r"^\d+\.\d$", src)
            elif src.endswith((".share", ".share_ci_lo", ".share_ci_hi")):
                self.assertRegex(t, r"^-?\d+%$", src)
            elif src.endswith(".n"):
                self.assertRegex(t, r"^\d+$", src)

    def data_numbers(self):
        """Every number of the explorer data as the page writes it: a digit in a title or aria value must be one of these."""
        out = set()

        def walk(x):
            if isinstance(x, dict):
                [walk(v) for v in x.values()]
            elif isinstance(x, list):
                [walk(v) for v in x]
            elif isinstance(x, (int, float)) and not isinstance(x, bool):
                out.update(("{:g}".format(x), "{:,}".format(int(round(x)))))
        walk({a: b for a, b in self.ex.items() if a != "floor"})
        return out

    def test_attributes_and_script_literals_carry_no_digit_and_no_banned_word(self):
        for n in self.sec.walk():
            for a, v in n.attrs.items():
                if a in ("title", "label") or a.startswith("aria-"):
                    self.assertEqual([t for t in re.findall(r"\d+(?:\.\d+)?", v) if t not in self.data_numbers()], [], (a, v))
                    self.assertIsNone(s8i.BANNED.search(v), (a, v))
        visible = " ".join(self.sec.text_nodes())
        self.assertIsNone(s8i.BANNED.search(visible), s8i.BANNED.search(visible))
        for n in self.sec.walk():
            for a in ("data-lead", "data-ref-text"):
                if a in n.attrs:
                    self.assertIsNone(s8i.BANNED.search(n.attrs[a]))
        js = [("".join(n.kids)) for n in self.root.walk() if n.tag == "script" and not n.attrs.get("type")][0]
        lits = [v for _, _, v in s8i.scan_js(js)[0]]
        self.assertGreater(len(lits), 20)
        self.assertEqual([v for v in lits if re.search(r"\d", v)], [])
        self.assertEqual([v for v in lits if s8i.BANNED.search(v)], [])
        self.assertIsNone(re.search(r"\*\s*8\b", js))
        for word in ("floor preset", "Floor preset"):
            self.assertNotIn(word, self.block)
        self.assertIn("Stickiness of the floor", self.block)

    def test_the_whole_page_still_passes_the_banned_word_scan(self):
        root = k.parse(self.html)
        text = " ".join(" ".join(k.all_visible(root)).split())
        rest = text.replace(k.EXEMPT, " ")
        for phrase in k.ZONE_EXEMPT:
            rest = rest.replace(phrase, " ")
        self.assertEqual([m.group(0) for m in s8i.BANNED.finditer(rest)], [])

    def test_embedded_data_is_the_data_js_key_without_provenance_strings(self):
        m = re.search(r'<script type="application/json" id="xp-data">(.*?)</script>', self.block, re.S)
        emb = json.loads(m.group(1))
        strip = lambda d: {a: b for a, b in d.items() if a != "src"}
        self.assertEqual(emb["axes"], self.ex["axes"])
        self.assertEqual([strip({a: b for a, b in e.items() if a != "verdict"}) for e in emb["floor"]],
                         [strip(e) for e in self.ex["floor"]])
        for e, src in zip(emb["floor"], self.ex["floor"]):  # the verdict is dose_verdict of the share interval
            want = None if src["share"] is None else ob.dose_verdict([src["share_ci_lo"], src["share_ci_hi"]])
            self.assertEqual(e["verdict"], want, src["src"])
        self.assertEqual(emb["sweeps"]["density"], strip(self.ex["sweeps"]["density"]))
        self.assertEqual(emb["sweeps"]["breakdown"], strip(self.ex["sweeps"]["breakdown"]))

    def test_no_external_load_tokens_only_and_focus_visible(self):
        self.assertNotIn("http", self.block)
        self.assertIsNone(re.search(r"(?<![\w-])src=", self.block))
        self.assertNotIn("@import", self.block)
        css = re.search(r"<style>(.*?)</style>", self.block, re.S).group(1)
        self.assertIn(":focus-visible", css)
        self.assertIn("[hidden]{display:none}", css)
        used = set(re.findall(r"var\((--[\w-]+)\)", css))
        root = k.ROOT_BLOCK.search(k.style_text(self.html)).group(0)
        for name in used:
            self.assertIn(name + ":", root, name)
        self.assertEqual(k.colour_findings(css), [])
        self.assertIn("min-width:0", css)  # the grid children may shrink: no horizontal overflow at 400px
        self.assertIsNone(re.search(r"@media\s*\(\s*prefers-color-scheme", self.html))

    def test_default_state_reads_without_script(self):
        radios = {n.attrs["value"]: n for n in self.sec.find_all("input") if n.attrs.get("name") == "xp-arm"}
        self.assertEqual([r for r, n in radios.items() if "checked" in n.attrs], ["none"])
        steps = [n for n in self.sec.find_all("input") if n.attrs.get("name") == "xp-steps"]
        self.assertEqual([n.attrs["value"] for n in steps if "checked" in n.attrs], [str(self.ex["axes"]["steps"][0])])
        reg = self.sec.find_all("input")[0]
        self.assertEqual((reg.attrs["type"], reg.attrs["value"], reg.attrs["aria-valuetext"]), ("range", "0", "mild, p 0.3\u20130.7"))
        self.assertEqual(len([n for n in self.sec.find_all("li") if "data-tick" in n.attrs]), 4)
        ticks = [re.sub(r"\s+", "", li.text()) for li in self.sec.find_all("ul")[0].find_all("li")]
        self.assertEqual(ticks, ["mildp0.3\u20130.7", "mediump0.6\u20130.9", "stickyp0.8\u20130.95", "verystickyp0.9\u20130.99"])
        verdict = self.sec.find_all("p", "xp-verdict")[0]
        self.assertEqual(verdict.attrs["data-verdict"], "reference")
        self.assertIn("reference", verdict.text())
        self.assertNotIn("beats", verdict.text())

    def test_builder_refuses_without_the_explorer_key(self):
        import tempfile as tf
        for mode in ("missing", "null"):
            with tf.TemporaryDirectory() as td:
                def drop(name, doc):
                    if name == k.D:
                        if mode == "missing":
                            del doc["run_constants"]["explorer"]
                        else:
                            doc["run_constants"]["explorer"] = None
                fx = k.write_fixture(Path(td) / "fx", mutate=drop)
                out = Path(td) / "o.html"
                rc, err = k.run_builder(fx, out)
                self.assertNotEqual(rc, 0, mode)
                self.assertFalse(out.exists(), mode)
                self.assertIn("explorer", err)

    def test_the_builder_inputs_are_unchanged(self):
        self.assertEqual(ob.INPUTS, ("docs/replay/data.js", "results/fleet/benchmark.json",
                                     "results/fleet/hotspot_s8b-medium-80-p03-07.json", "results/closed_loop_sticky/summary.json"))

    def test_kind_of_knows_every_explorer_path_and_nothing_else(self):
        d = "docs/replay/data.js:run_constants.explorer."
        self.assertEqual(ob.kind_of(d + "floor.3.mean"), "f1")
        self.assertEqual(ob.kind_of(d + "floor.3.share_ci_lo"), "pct0")
        self.assertEqual(ob.kind_of(d + "floor.3.n"), "int")
        self.assertEqual(ob.kind_of(d + "axes.regimes.0.p_lo"), "g")
        self.assertEqual(ob.kind_of(d + "sweeps.breakdown.policies.stuck_aware_cta.2.mean"), "f1")
        for bad in (d + "floor.3.src", d + "floor.3.arm", d + "axes.nope", d + "sweeps.density.src"):
            with self.assertRaises(KeyError):
                ob.kind_of(bad)


# ------------------------------------------------------------------------------------------------ (e) stub DOM in Node
TAIL = r'''
// ---- S11A tail: run the explorer script of the page against the stub DOM and drive every stop
const html = fs.readFileSync(htmlPath, 'utf8');
const dataM = /id="xp-data">([\s\S]*?)<\/script>/.exec(html);
const jsM = /<!-- explorer-start -->[\s\S]*?<script>([\s\S]*?)<\/script><!-- explorer-end -->/.exec(html);
document.getElementById('xp-data').textContent = dataM[1];
// the stub does not reflect attributes into properties: do it for the form controls, as a browser would
walk(root, function (e) {
  if (e._tag === 'input') {
    e.value = e.hasAttribute('value') ? e.getAttribute('value') : '';
    e.checked = e.hasAttribute('checked'); e.disabled = e.hasAttribute('disabled');
  }
});
vm.runInContext(jsM[1], sandbox, { filename: 'explorer.js' });
const sec = document.getElementById('xp');
function snap() {
  const spans = [];
  walk(sec, function (e) {
    if (e.hasAttribute('data-src')) {
      let h = false; for (let x = e; x && x.nodeType === 1; x = x.parentNode) if (x.hidden) h = true;
      spans.push({ src: e.getAttribute('data-src'), text: e.textContent, slot: e.getAttribute('data-slot'), ref: e.getAttribute('data-ref'), hidden: h });
    }
  });
  const ctl = function (name) {
    return query(sec, 'input[name=' + name + ']', false).map(function (e) {
      return { value: e.value, disabled: e.disabled, attr: e.hasAttribute('disabled'), title: e.getAttribute('title'),
               label_title: e.parentNode.getAttribute('title'), checked: e.checked,
               nm_text: (query(e.parentNode, '.xp-nm', false)[0] || { textContent: null }).textContent,
               nm_hidden: (query(e.parentNode, '.xp-nm', false)[0] || { hidden: null }).hidden };
    });
  };
  const style = function (id) { const e = document.getElementById(id); return { left: e.style.left || null, width: e.style.width || null, hidden: e.hidden }; };
  const v = document.getElementById('xp-verdict');
  return { spans: spans, arms: ctl('xp-arm'), steps: ctl('xp-steps'), pol: ctl('xp-pol'),
    verdict: { text: v.textContent, kind: v.getAttribute('data-verdict') },
    share_hidden: document.getElementById('xp-share').hidden,
    fill: style('xp-fill'), ci: style('xp-cibar'), ref_u: style('xp-ref-undisturbed'), ref_n: style('xp-ref-none'),
    valuetext: document.getElementById('xp-regime').getAttribute('aria-valuetext'),
    vt_dens: document.getElementById('xp-dens').getAttribute('aria-valuetext'),
    vt_brk: document.getElementById('xp-brk').getAttribute('aria-valuetext'),
    live: query(sec, '[aria-live]', false).map(function (e) { return { live: e.getAttribute('aria-live'), text: e.textContent.replace(/\s+/g, ' ').trim() }; }),
    refs: query(sec, '[data-ref]', false).map(function (e) {
      return { ref: e.getAttribute('data-ref'), text: e.textContent, src: e.getAttribute('data-src'), slot: e.getAttribute('data-slot') };
    }),
    ticks: query(sec, 'li', false).map(function (e) { return e.className; }) };
}
const out = [{ action: null, snap: snap() }];
for (const a of scenario.actions) {
  if (a.range) {
    const el = document.getElementById(a.range); el.value = String(a.value); el.dispatch('input', { target: el });
  } else {
    const el = query(sec, 'input[name=' + a.radio + ']', false).filter(function (e) { return e.value === String(a.value); })[0];
    if (!el) throw new Error('no radio ' + a.radio + '=' + a.value);
    el.dispatch('change', { target: el });
  }
  out.push({ action: a, snap: snap() });
}
process.stdout.write(JSON.stringify(out));
'''
STUB_HEAD = HARNESS.split("vm.createContext(sandbox);")[0] + "vm.createContext(sandbox);\n"
EXPLORER_HARNESS = STUB_HEAD + TAIL


def run_explorer(case, actions, page=None):
    node = need_node(case)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "harness.js").write_text(EXPLORER_HARNESS, encoding="utf-8")
        (tmp / "scenario.json").write_text(json.dumps(dict(actions=actions)), encoding="utf-8")
        r = subprocess.run([node, str(tmp / "harness.js"), str(page or k.PAGE), "-", "-", str(tmp / "scenario.json")],
                           capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        case.fail("the explorer script failed under the stub DOM: " + r.stderr[-1500:])
    return json.loads(r.stdout)


class TestDom(Committed):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.inputs = ob.load_inputs(DATA, ROOT)
        cls.D = "docs/replay/data.js:run_constants.explorer."

    def index(self, regime, steps, arm):
        return next((i for i, e in enumerate(self.ex["floor"]) if (e["regime"], e["steps"], e["arm"]) == (regime, steps, arm)), -1)

    def shown(self, src):
        return ob.format_value(self.D + src, ob.resolve(self.D + src, self.inputs))

    def vt_regime(self, ri):
        r = self.ex["axes"]["regimes"][ri]
        return "%s, p %s\u2013%s" % (r["word"], self.shown("axes.regimes.%d.p_lo" % ri), self.shown("axes.regimes.%d.p_hi" % ri))

    def check_a(self, snap, ri, steps, arm):
        regime = self.ex["axes"]["regimes"][ri]["key"]
        idx = self.index(regime, steps, arm)
        self.assertGreaterEqual(idx, 0)
        e = self.ex["floor"][idx]
        label = (regime, steps, arm)
        # every control stop maps to an entry or is disabled with the title
        for a in snap["arms"]:
            has = self.index(regime, steps, a["value"]) >= 0
            self.assertEqual((a["disabled"], a["attr"]), (not has, not has), (label, a["value"]))
            self.assertEqual(a["title"], None if has else "not measured", (label, a["value"]))
            self.assertEqual(a["label_title"], None if has else "not measured", (label, a["value"]))
            self.assertEqual(a["checked"], a["value"] == arm, (label, a["value"]))
        for s in snap["steps"]:
            has = self.index(regime, int(s["value"]), "none") >= 0
            self.assertEqual((s["disabled"], s["title"]), (not has, None if has else "not measured"), (label, s["value"]))
            self.assertEqual(s["checked"], int(s["value"]) == steps, (label, s["value"]))
        self.assertEqual(snap["valuetext"], self.vt_regime(ri))
        self.assertEqual([i for i, c in enumerate(snap["ticks"]) if "xp-on" in c.split()], [ri])
        # the data-src spans and their text are the selected entry's values
        slots = {}
        for sp in snap["spans"]:
            if sp["hidden"] and not sp["text"]:
                continue  # the share spans of a reference stop are empty and hidden
            self.assertEqual(sp["text"], self.shown(sp["src"][len(self.D):]), sp["src"])
            if sp["slot"] and not sp["ref"] and ".floor." in sp["src"]:
                slots[sp["slot"]] = sp
        for slot, field in (("mean", "mean"), ("ci_lo", "ci_lo"), ("ci_hi", "ci_hi"), ("n", "n")):
            self.assertEqual(slots[slot]["src"], "%sfloor.%d.%s" % (self.D, idx, field), label)
        refs = {sp["ref"]: sp for sp in snap["spans"] if sp["ref"]}
        for a in ("undisturbed", "none"):
            self.assertEqual(refs[a]["src"], "%sfloor.%d.mean" % (self.D, self.index(regime, steps, a)), label)
        # share row and verdict
        if e["share"] is None:
            self.assertTrue(snap["share_hidden"], label)
            self.assertEqual(snap["verdict"]["kind"], "reference")
            self.assertNotIn("beats", snap["verdict"]["text"])
            self.assertIn("reference", snap["verdict"]["text"])
        else:
            self.assertFalse(snap["share_hidden"], label)
            for slot, field in (("share", "share"), ("share_ci_lo", "share_ci_lo"), ("share_ci_hi", "share_ci_hi")):
                self.assertEqual(slots[slot]["src"], "%sfloor.%d.%s" % (self.D, idx, field), label)
                self.assertEqual(slots[slot]["text"], self.shown("floor.%d.%s" % (idx, field)), label)
            kind = ob.dose_verdict([e["share_ci_lo"], e["share_ci_hi"]])
            self.assertEqual(snap["verdict"]["kind"], kind, label)
            word = {"helps": "beats", "hurts": "worse", "within noise": "within noise"}[kind]
            self.assertTrue(snap["verdict"]["text"].startswith("Against no map, this setting "), snap["verdict"]["text"])
            self.assertIn(word, snap["verdict"]["text"])
            self.assertEqual(sum(w in snap["verdict"]["text"] for w in ("beats", "worse", "within noise")), 1)
        # bar geometry: fixed scale per (regime, steps), reference lines do not depend on the arm
        top = max(f["ci_hi"] for f in self.ex["floor"] if f["regime"] == regime and f["steps"] == steps) * 1.05
        pc = lambda v: v / top * 100
        num = lambda s: float(s.rstrip("%"))
        self.assertAlmostEqual(num(snap["fill"]["width"]), pc(e["mean"]), delta=0.01)
        self.assertAlmostEqual(num(snap["ci"]["left"]), pc(e["ci_lo"]), delta=0.01)
        self.assertAlmostEqual(num(snap["ci"]["width"]), pc(e["ci_hi"] - e["ci_lo"]), delta=0.01)
        for key, a in (("ref_u", "undisturbed"), ("ref_n", "none")):
            self.assertAlmostEqual(num(snap[key]["left"]), pc(self.ex["floor"][self.index(regime, steps, a)]["mean"]), delta=0.01)
            self.assertFalse(snap[key]["hidden"])

    def test_every_stop_of_group_a(self):
        axes = self.ex["axes"]
        actions, expect = [], []
        for ri, r in enumerate(axes["regimes"]):
            for steps in axes["steps"]:
                if self.index(r["key"], steps, "none") < 0:
                    continue
                actions.append(dict(range="xp-regime", value=ri))
                actions.append(dict(radio="xp-steps", value=steps))
                expect.append(None)
                expect.append(None)
                for a in axes["arms"]:
                    if self.index(r["key"], steps, a["key"]) < 0:
                        continue
                    actions.append(dict(radio="xp-arm", value=a["key"]))
                    expect.append((ri, steps, a["key"]))
        out = run_explorer(self, actions)
        self.assertEqual(len(out), len(actions) + 1)
        checked = 0
        for step, want in zip(out[1:], expect):
            if want is None:
                continue
            self.check_a(step["snap"], *want)
            checked += 1
        self.assertEqual(checked, len([e for e in self.ex["floor"] if e["arm"] != "undisturbed"]))  # every selectable stop, once

    def test_fallbacks_when_a_stop_disappears(self):
        # very sticky, 1500 steps, map_a32; then a milder floor: 1500 and the arm fall back to a measured stop
        out = run_explorer(self, [dict(range="xp-regime", value=3), dict(radio="xp-steps", value=1500), dict(radio="xp-arm", value="map_a32"),
                                  dict(range="xp-regime", value=1)])
        self.check_a(out[3]["snap"], 3, 1500, "map_a32")
        self.check_a(out[4]["snap"], 1, 500, "map_a32")
        out = run_explorer(self, [dict(range="xp-regime", value=3), dict(radio="xp-arm", value="map_a16"), dict(range="xp-regime", value=0)])
        self.check_a(out[2]["snap"], 3, 500, "map_a16")
        self.check_a(out[3]["snap"], 0, 500, "none")  # mild has no map_a16 at 500 steps

    def test_initial_render_equals_the_static_html(self):
        out = run_explorer(self, [])
        static = k.parse(section_text(self.html)).find_all("section")[0]
        want = [(n.attrs["data-src"], n.text()) for n in static.walk() if "data-src" in n.attrs and n.text()]
        got = [(s["src"], s["text"]) for s in out[0]["snap"]["spans"] if s["text"]]
        self.assertEqual(got, want)
        self.check_a(out[0]["snap"], 0, 500, "none")
        static_arms = [(n.attrs["value"], "disabled" in n.attrs, n.attrs.get("title")) for n in static.find_all("input")
                       if n.attrs.get("name") == "xp-arm"]
        self.assertEqual(static_arms, [(a["value"], a["disabled"], a["title"]) for a in out[0]["snap"]["arms"]])

    def test_group_b_sliders_and_toggle(self):
        sw = self.ex["sweeps"]
        actions, expect = [], []
        for i in range(len(sw["density"]["points"])):
            actions.append(dict(range="xp-dens", value=i))
            expect.append(("dens", i, None))
        for pol in ("cta", "stuck_aware_cta"):
            actions.append(dict(radio="xp-pol", value=pol))
            expect.append(("pol", 0, pol))
            for j in range(len(sw["breakdown"]["policies"][pol])):
                actions.append(dict(range="xp-brk", value=j))
                expect.append(("brk", j, pol))
        out = run_explorer(self, actions)
        self.assertEqual(len(out), len(actions) + 1)
        state = dict(dens=0, brk=0, pol="cta")
        for step, (what, i, pol) in zip(out[1:], expect):
            if what == "dens":
                state["dens"] = i
            elif what == "brk":
                state["brk"] = i
            else:
                state["pol"] = pol
            spans = step["snap"]["spans"]
            for sp in spans:
                self.assertEqual(sp["text"], self.shown(sp["src"][len(self.D):]) if sp["text"] else "", sp["src"])
            by = {}
            for sp in spans:
                if sp["src"].startswith(self.D + "sweeps.density.points."):
                    by.setdefault("dens", {})[sp["slot"]] = sp
                elif sp["src"].startswith(self.D + "sweeps.breakdown.policies."):
                    by.setdefault("brk", {})[sp["slot"]] = sp
            row = sw["density"]["points"][state["dens"]]
            for slot in ("mean", "ci_lo", "ci_hi", "n", "point", "pickers"):
                self.assertEqual(by["dens"][slot]["src"], "%ssweeps.density.points.%d.%s" % (self.D, state["dens"], slot))
                self.assertEqual(by["dens"][slot]["text"], self.shown("sweeps.density.points.%d.%s" % (state["dens"], slot)))
            self.assertEqual(by["dens"]["point"]["text"], str(row["point"]))
            for slot in ("mean", "ci_lo", "ci_hi", "n", "point"):
                self.assertEqual(by["brk"][slot]["src"],
                                 "%ssweeps.breakdown.policies.%s.%d.%s" % (self.D, state["pol"], state["brk"], slot))
            self.assertEqual([p["checked"] for p in step["snap"]["pol"]], [p == state["pol"] for p in ("cta", "stuck_aware_cta")])
        # the toggle changes the numbers: the two policies are separate series
        a = [s for s in out if s["action"] and s["action"].get("radio") == "xp-pol"]
        self.assertEqual(len(a), 2)
        self.assertNotEqual([s["text"] for s in a[0]["snap"]["spans"] if "breakdown.policies" in s["src"]],
                            [s["text"] for s in a[1]["snap"]["spans"] if "breakdown.policies" in s["src"]])


# ------------------------------------------------------------------------------------------------ (f) pass 2: design-audit fixes
def hide_entries(html, drop):
    """A copy of the page whose embedded explorer data lacks the floor entries for which drop(entry) is true."""
    m = re.search(r'(id="xp-data">)(.*?)(</script>)', html, re.S)
    data = json.loads(m.group(2).replace("<\\/", "</"))
    data["floor"] = [e for e in data["floor"] if not drop(e)]
    return html[:m.start(2)] + json.dumps(data, separators=(",", ":")).replace("</", "<\\/") + html[m.end(2):]


def box_of(sec, legend):
    return next(b for b in sec.find_all("fieldset") if "xp-box" in b.classes and b.find_all("legend")[0].text() == legend)


def lum(hexcol):
    c = [int(hexcol[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


class TestPass2(Committed):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.inputs = ob.load_inputs(DATA, ROOT)
        cls.D = "docs/replay/data.js:run_constants.explorer."

    index = TestDom.index
    shown = TestDom.shown
    vt_regime = TestDom.vt_regime

    def setUp(self):
        self.block = section_text(self.html)
        self.sec = k.parse(self.block).find_all("section")[0]

    def box_a(self):
        return box_of(self.sec, "Does the map help?")

    def box_b(self):
        return box_of(self.sec, "Robots and breakdowns")

    # F1 ---------------------------------------------------------------------------------------------------------------------
    def vt_dens(self, i):
        return "%s carrying robots" % self.shown("axes.density.%d" % i)

    def vt_brk(self, i):
        return "%s breakdowns per robot per hour" % self.shown("axes.breakdown.%d" % i)

    def test_f1_static_valuetext_on_all_three_sliders_comes_from_the_data(self):
        by = {n.attrs["id"]: n for n in self.sec.find_all("input") if n.attrs.get("type") == "range"}
        self.assertEqual(sorted(by), ["xp-brk", "xp-dens", "xp-regime"])
        self.assertEqual(by["xp-regime"].attrs["aria-valuetext"], self.vt_regime(0))
        self.assertEqual(by["xp-dens"].attrs["aria-valuetext"], self.vt_dens(0))
        self.assertEqual(by["xp-brk"].attrs["aria-valuetext"], self.vt_brk(0))

    def test_f1_input_event_and_stickiness_reset_update_valuetext(self):
        nd, nb = len(self.ex["axes"]["density"]), len(self.ex["axes"]["breakdown"])
        acts = [dict(range="xp-dens", value=i) for i in range(nd)] + [dict(range="xp-brk", value=i) for i in range(nb)]
        out = run_explorer(self, acts)
        for i in range(nd):  # path 1: the input event of the density slider
            self.assertEqual(out[1 + i]["snap"]["vt_dens"], self.vt_dens(i))
        for i in range(nb):  # path 1: the input event of the breakdown slider
            self.assertEqual(out[1 + nd + i]["snap"]["vt_brk"], self.vt_brk(i))
        # path 2: a stickiness change resets shift length and steering, and the slider text follows
        out = run_explorer(self, [dict(range="xp-regime", value=3), dict(radio="xp-steps", value=1500), dict(radio="xp-arm", value="map_a32"),
                                  dict(range="xp-regime", value=1)])
        for step, ri in zip(out[1:], (3, 3, 3, 1)):
            self.assertEqual(step["snap"]["valuetext"], self.vt_regime(ri))

    # F2 ---------------------------------------------------------------------------------------------------------------------
    def test_f2_one_polite_summary_per_group_and_no_detail_row_inside(self):
        for box in (self.box_a(), self.box_b()):
            live = [n for n in box.walk() if "aria-live" in n.attrs]
            self.assertEqual([n.attrs["aria-live"] for n in live], ["polite"])
            self.assertEqual(live[0].attrs.get("aria-atomic"), "true")
            self.assertNotIn("interval", live[0].text())
            self.assertNotIn("Mean of", live[0].text())
        self.assertEqual(len([n for n in self.sec.walk() if "aria-live" in n.attrs]), 2)

    def test_f2_group_a_summary_says_value_verdict_steering_and_shift_length(self):
        a = [n for n in self.box_a().walk() if "aria-live" in n.attrs][0]
        text = " ".join(a.text(" ").split())
        for want in (self.shown("floor.0.mean"), "no map", self.shown("axes.steps.0"), "reference"):
            self.assertIn(want, text)
        out = run_explorer(self, [dict(range="xp-regime", value=3), dict(radio="xp-steps", value=1500), dict(radio="xp-arm", value="map_a32"),
                                  dict(range="xp-regime", value=1)])
        idx = self.index("very_sticky", 1500, "map_a32")
        live = out[3]["snap"]["live"][0]["text"]
        self.assertIn(self.shown("floor.%d.mean" % idx), live)
        self.assertIn("map, steering strength " + self.shown("axes.arms.4.alpha"), live)
        self.assertIn(self.shown("axes.steps.1"), live)
        self.assertIn("Against no map", live)
        # the stickiness change resets shift length: the announcement carries the new shift length and the same steering
        reset = out[4]["snap"]["live"][0]["text"]
        j = self.index("medium", 500, "map_a32")
        self.assertIn(self.shown("axes.steps.0"), reset)
        self.assertIn("map, steering strength " + self.shown("axes.arms.4.alpha"), reset)
        self.assertIn(self.shown("floor.%d.mean" % j), reset)
        self.assertNotIn(self.shown("floor.%d.mean" % idx), reset)

    def test_f2_group_b_summary_holds_one_value_per_output(self):
        out = run_explorer(self, [dict(range="xp-dens", value=3), dict(radio="xp-pol", value="stuck_aware_cta"), dict(range="xp-brk", value=2)])
        for step, (di, bi, pol) in zip(out[1:], ((3, 0, "cta"), (3, 0, "stuck_aware_cta"), (3, 2, "stuck_aware_cta"))):
            live = [x for x in step["snap"]["live"] if x["live"] == "polite"][1]["text"]
            d = self.shown("sweeps.density.points.%d.mean" % di)
            b = self.shown("sweeps.breakdown.policies.%s.%d.mean" % (pol, bi))
            self.assertEqual(re.findall(r"\d+\.\d", live), [d, b], live)
            self.assertNotIn("interval", live)

    # F3 ---------------------------------------------------------------------------------------------------------------------
    def test_f3_disabled_stops_say_not_measured_in_visible_text_and_one_help_line(self):
        labels = [n for n in self.sec.find_all("label") if "xp-opt" in n.classes and n.find_all("input")[0].attrs.get("name") in ("xp-arm", "xp-steps")]
        disabled = 0
        for lab in labels:
            nm = [x for x in lab.find_all("span") if "xp-nm" in x.classes]
            self.assertEqual(len(nm), 1)
            off = "disabled" in lab.find_all("input")[0].attrs
            self.assertEqual("hidden" in nm[0].attrs, not off)
            if off:
                disabled += 1
                self.assertEqual(nm[0].text().strip(), "not measured")
                self.assertEqual(lab.attrs["title"], "not measured")
        self.assertGreater(disabled, 0)
        helps = [p for p in self.sec.find_all("p") if "greyed-out" in p.text().lower()]
        self.assertEqual(len(helps), 1)
        self.assertIn("not measured", helps[0].text())

    def test_f3_script_toggles_the_visible_text_with_the_disabled_state(self):
        out = run_explorer(self, [dict(range="xp-regime", value=3), dict(range="xp-regime", value=0)])
        for step in out:
            for c in step["snap"]["arms"] + step["snap"]["steps"]:
                self.assertEqual(c["nm_hidden"], not c["disabled"], c)
                if c["disabled"]:
                    self.assertEqual(c["nm_text"].strip(), "not measured")
        self.assertTrue(any(c["disabled"] for step in out for c in step["snap"]["arms"]))

    # F4 ---------------------------------------------------------------------------------------------------------------------
    def test_f4_reference_spans_do_not_share_the_selected_slot(self):
        refs = [n for n in self.sec.walk() if "data-ref" in n.attrs]
        self.assertEqual(sorted(n.attrs["data-ref"] for n in refs), ["none", "undisturbed"])
        for n in refs:
            self.assertNotIn("data-slot", n.attrs)

    def test_f4_a_missing_reference_entry_shows_not_measured_never_the_selected_value(self):
        def fixture(drop, ri=1, arm="map_a8"):
            with tempfile.TemporaryDirectory() as td:
                page = Path(td) / "fixture.html"
                page.write_text(hide_entries(self.html, drop), encoding="utf-8")
                return run_explorer(self, [dict(range="xp-regime", value=ri), dict(radio="xp-arm", value=arm)], page=page)
        # undisturbed removed for (medium, 500): the reference reads not measured at that stop, whatever arm is selected
        reg, steps = self.ex["axes"]["regimes"][1]["key"], 500
        out = fixture(lambda e: (e["regime"], e["steps"], e["arm"]) == (reg, steps, "undisturbed"))
        for step in out[1:]:
            snap = step["snap"]
            r = {x["ref"]: x for x in snap["refs"]}
            self.assertEqual((r["undisturbed"]["text"], r["undisturbed"]["src"]), ("not measured", None))
            self.assertEqual(r["none"]["text"], self.shown("floor.%d.mean" % self.index(reg, steps, "none")))
            self.assertTrue(snap["ref_u"]["hidden"])
            sel = next(sp for sp in snap["spans"] if sp["slot"] == "mean" and ".floor." in sp["src"])
            self.assertNotEqual(r["undisturbed"]["text"], sel["text"])
        # none removed for (very sticky, 1500): that shift length is then not selectable, so the reference is never drawn from the
        # selected entry; the surviving reference spans still read their own entries
        out = fixture(lambda e: (e["regime"], e["steps"], e["arm"]) == ("very_sticky", 1500, "none"), 3, "map_a4")
        for step in out[1:]:
            snap = step["snap"]
            self.assertTrue(next(s for s in snap["steps"] if s["value"] == "1500")["disabled"])
            for r in snap["refs"]:
                self.assertIsNone(r["slot"])
                if r["src"] is None:
                    self.assertEqual(r["text"], "not measured")
                else:
                    self.assertEqual(r["text"], self.shown(r["src"][len(self.D):]))
                    self.assertIn(".mean", r["src"])

    # F5 ---------------------------------------------------------------------------------------------------------------------
    def css(self):
        return re.search(r"<style>(.*?)</style>", self.block, re.S).group(1)

    def test_f5_reference_lines_differ_by_style_and_have_text_labels(self):
        css = self.css()
        u = re.search(r"\.xp-ref\.xp-u\{([^}]*)\}", css).group(1)
        z = re.search(r"\.xp-ref\.xp-z\{([^}]*)\}", css).group(1)
        self.assertIn("solid", u)
        self.assertIn("dashed", z)
        self.assertNotIn("dashed", u)
        keys = {n.attrs["id"]: n.text() for n in self.sec.find_all("span") if n.attrs.get("id", "").startswith("xp-ref-key-")}
        self.assertIn("undisturbed floor", keys["xp-ref-key-undisturbed"])
        self.assertIn("solid", keys["xp-ref-key-undisturbed"])
        self.assertIn("no map", keys["xp-ref-key-none"])
        self.assertIn("dashed", keys["xp-ref-key-none"])

    def test_f5_the_bar_is_distinguishable_from_its_track(self):
        css = self.css()
        root = k.ROOT_BLOCK.search(k.style_text(self.html)).group(0)
        tok = lambda name: re.search(re.escape(name) + r":\s*(#[0-9a-fA-F]{6})", root).group(1)
        fill = re.search(r"\.xp-fill\{[^}]*background:var\((--[\w-]+)\)", css).group(1)
        bar = re.search(r"\.xp-bar\{([^}]*)\}", css).group(1)
        track = re.search(r"background:var\((--[\w-]+)\)", bar).group(1)
        ratio = contrast(tok(fill), tok(track))
        self.assertTrue(ratio >= 3 or "border:1px solid var(--ink)" in bar, (ratio, bar))

    # F6 ---------------------------------------------------------------------------------------------------------------------
    def test_f6_one_vocabulary(self):
        text = " ".join(" ".join(self.sec.text_nodes()).split())
        text = re.sub(r"\s*\u2013\s*", "\u2013", text)
        for word in ("none", "oracle", "alpha", "AGVs", "AGV"):
            self.assertIsNone(re.search(r"\b%s\b" % word, text, re.I), word)
        self.assertIsNone(s8i.BANNED.search(text))
        for stop in ("no map", "perfect knowledge", "carrying robots"):
            self.assertIn(stop, text)
        self.assertIn("map, steering strength " + self.shown("axes.arms.1.alpha"), text)
        self.assertEqual(len(re.findall(r"\bp is the chance\b", text)), 1)
        lo, hi = self.shown("axes.regimes.0.p_lo"), self.shown("axes.regimes.0.p_hi")
        self.assertIn("p %s–%s" % (lo, hi), text)
        self.assertIsNone(re.search(r"\d-\d", text))  # an en dash, never a hyphen, between range ends


if __name__ == "__main__":
    unittest.main()

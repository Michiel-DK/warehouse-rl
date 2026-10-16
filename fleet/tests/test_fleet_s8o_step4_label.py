"""S8O-STEP4-LABEL: lessons_long gains persist_held/persist_graded, the refresh-only exporter mode, and overview step 4."""
import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fleet import overview_build as ob  # noqa: E402
from fleet import replay_export as rx  # noqa: E402
from fleet.tests import test_s8k_overview as k  # noqa: E402

LONG = "results/fleet/hotspot_s8e-long-w0.5.json"


def counts_file(td, **extra):
    gc = {"lesson": {"ok": 9, "off": 22}, "lesson_truth": {"hit": 27}}
    gc.update(extra)
    p = Path(td) / "c.json"
    p.write_text(json.dumps({"grading_counts": gc}), encoding="utf-8")
    return str(p)


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = rx.main(argv)
        except SystemExit as e:
            rc = e.code
    return rc, err.getvalue()


class TestLessonsLongConstant(unittest.TestCase):
    def test_persist_fields(self):
        with tempfile.TemporaryDirectory() as td:
            r = rx.lessons_long_constant(counts_file(td, lesson_persist={"ok": 18, "off": 7}))
            self.assertEqual((r["persist_held"], r["persist_graded"]), (18, 25))
            self.assertEqual((r["truth_hit"], r["truth_n"], r["held"], r["graded"]), (27, 27, 9, 31))

    def test_missing_off_key(self):
        with tempfile.TemporaryDirectory() as td:
            r = rx.lessons_long_constant(counts_file(td, lesson_persist={"ok": 3}))
            self.assertEqual((r["persist_held"], r["persist_graded"]), (3, 3))

    def test_missing_ok_key(self):
        with tempfile.TemporaryDirectory() as td:
            r = rx.lessons_long_constant(counts_file(td, lesson_persist={"off": 4}))
            self.assertEqual((r["persist_held"], r["persist_graded"]), (0, 4))

    def test_absent_is_null_without_error(self):
        with tempfile.TemporaryDirectory() as td:
            r = rx.lessons_long_constant(counts_file(td))
            self.assertIsNone(r["persist_held"])
            self.assertIsNone(r["persist_graded"])
            self.assertEqual((r["truth_hit"], r["truth_n"], r["held"], r["graded"]), (27, 27, 9, 31))

    def test_non_object_persist_is_a_value_error(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, "lesson_persist"):
                rx.lessons_long_constant(counts_file(td, lesson_persist=18))


class TestRefreshMode(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.out = Path(self.td.name) / "data.js"
        shutil.copy(ROOT / "docs/replay/data.js", self.out)

    def test_splice_touches_only_the_value(self):
        # start from a stale lessons_long so the refresh has something to change
        text = self.out.read_text(encoding="utf-8")
        key = '"lessons_long":'
        start = text.index(key) + len(key)
        _, end = json.JSONDecoder().raw_decode(text, start)
        stale = dict(truth_hit=1, truth_n=2, held=3, graded=4, source="x")
        self.out.write_text(text[:start] + json.dumps(stale, separators=(",", ":")) + text[end:], encoding="utf-8")
        before_text = self.out.read_text(encoding="utf-8")
        start = before_text.index(key) + len(key)
        _, end = json.JSONDecoder().raw_decode(before_text, start)
        before = rx.read_data_js(self.out)
        rc, err = run_main(["--refresh-constants-only", "--out", str(self.out), "--lessons-long", str(ROOT / LONG)])
        self.assertEqual(rc, 0, err)
        after_text = self.out.read_text(encoding="utf-8")
        after = rx.read_data_js(self.out)
        b_rc, a_rc = dict(before["run_constants"]), dict(after["run_constants"])
        self.assertEqual(b_rc.pop("lessons_long"), stale)
        new = a_rc.pop("lessons_long")
        self.assertEqual(b_rc, a_rc)
        self.assertEqual({a: v for a, v in before.items() if a != "run_constants"},
                         {a: v for a, v in after.items() if a != "run_constants"})
        self.assertEqual(new, rx.lessons_long_constant(str(ROOT / LONG)))
        self.assertEqual(before_text[:start], after_text[:start])
        new_value = json.dumps(new, separators=(",", ":"))
        self.assertEqual(after_text[start:start + len(new_value)], new_value)
        self.assertEqual(before_text[end:], after_text[start + len(new_value):])

    def test_source_is_the_path_as_given(self):
        rel = Path(self.td.name) / "rel.json"
        shutil.copy(ROOT / LONG, rel)
        rc, err = run_main(["--refresh-constants-only", "--out", str(self.out), "--lessons-long", str(rel)])
        self.assertEqual(rc, 0, err)
        self.assertEqual(rx.read_data_js(self.out)["run_constants"]["lessons_long"]["source"], str(rel))

    def test_missing_out_exits_2_and_creates_nothing(self):
        missing = Path(self.td.name) / "nope.js"
        rc, err = run_main(["--refresh-constants-only", "--out", str(missing), "--lessons-long", str(ROOT / LONG)])
        self.assertEqual(rc, 2)
        self.assertFalse(missing.exists())
        self.assertEqual(sorted(p.name for p in Path(self.td.name).iterdir()), ["data.js"])

    def test_refresh_without_lessons_long_is_an_argparse_error(self):
        rc, err = run_main(["--refresh-constants-only", "--out", str(self.out)])
        self.assertEqual(rc, 2)
        self.assertIn("--lessons-long", err)

    def test_normal_mode_still_needs_run_dir_and_store(self):
        rc, err = run_main(["--out", str(self.out), "--store", "jsonl:x"])
        self.assertEqual(rc, 2)
        self.assertIn("--run-dir", err)
        rc, err = run_main(["--out", str(self.out), "--run-dir", "x"])
        self.assertEqual(rc, 2)
        self.assertIn("--store", err)


class TestCommittedData(unittest.TestCase):
    def test_lessons_long_constant_committed(self):
        self.assertEqual(rx.read_data_js(ROOT / "docs/replay/data.js")["run_constants"]["lessons_long"],
                         dict(truth_hit=27, truth_n=27, held=9, graded=31, persist_held=18, persist_graded=25, source=LONG))


class TestOverviewStep4(k.Committed):
    def test_figures_labels_and_chip(self):
        figs = self.root.find_all(cls="fignum")
        self.assertEqual([f.text() for f in figs], ["27/27", "18/25"])
        labs = []
        for f in figs:
            sib = [n for n in f.parent.kids if isinstance(n, k.Node)]
            labs.append(sib[sib.index(f) + 1].text())
        self.assertEqual(labs, ["real on the truth", "still above the zone average next window"])
        chips = [n.text() for n in self.root.find_all(cls="st") if n.text().startswith("Tested, weakly. Checked against the hidden truth")]
        self.assertEqual(len(chips), 1)
        self.assertEqual(chips[0], "Tested, weakly. Checked against the hidden truth. On a longer test shift the flagged cells were "
                         "real 27 of 27 times; 18 of 25 were still above their zone's average in the next half hour; only 9 of 31 "
                         "repeated their own peak, the bar the first version used.")
        self.assertNotIn("being reworked", chips[0])
        self.assertNotIn("still above average next window", chips[0])

    def test_committed_page_is_a_fresh_build(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "i.html"
            rc, err = k.run_builder(ROOT, out)
            self.assertEqual(rc, 0, err)
            self.assertEqual(out.read_bytes(), k.PAGE.read_bytes())


class TestNullPersist(unittest.TestCase):
    def test_none_raises_value_error_naming_the_field(self):
        inputs = ob.load_inputs(ROOT / "docs/replay/data.js", ROOT)
        inputs[ob.DATA]["run_constants"]["lessons_long"]["persist_held"] = None
        with self.assertRaises(ValueError) as cm:
            ob.num_element("persist_held", inputs)
        self.assertIn("persist_held", str(cm.exception))

    def test_builder_refuses_and_names_the_field(self):
        with tempfile.TemporaryDirectory() as td:
            def null(name, doc):
                if name == k.D:
                    doc["run_constants"]["lessons_long"]["persist_graded"] = None
            k.write_fixture(Path(td) / "fx", mutate=null)
            out = Path(td) / "o" / "index.html"
            rc, err = k.run_builder(Path(td) / "fx", out)
            self.assertNotEqual(rc, 0)
            self.assertIn("persist_graded", err)
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()

"""Tests for the platform tag, tests/platform_expected.json and the `platform` stamp in scripts/evaluate.py result docs
(docs/PLATFORM.md). Each case names its red-demonstration in an `# inject:` comment."""
import importlib.util
import json
import platform
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import _platform
import evaluate as ev

ENV_ID = "tarware-small-4agvs-2pickers-globalobs-v1"
TAGS = ["darwin-arm64", "linux-x86_64", "linux-arm64"]
EXPECTED = json.loads(Path(_platform.EXPECTED_PATH).read_text())


def with_machine(plat, machine):
    return mock.patch.object(sys, "platform", plat), mock.patch.object(platform, "machine", return_value=machine)


class TestTag(unittest.TestCase):
    # inject: drop the aarch64 -> arm64 or AMD64 -> x86_64 mapping, or the lower()
    def test_normalisation(self):
        for plat, machine, want in [("darwin", "arm64", "darwin-arm64"), ("linux", "aarch64", "linux-arm64"),
                                    ("linux", "x86_64", "linux-x86_64"), ("win32", "AMD64", "win32-x86_64"),
                                    ("linux", "AARCH64", "linux-arm64"), ("darwin", "x86_64", "darwin-x86_64")]:
            p1, p2 = with_machine(plat, machine)
            with p1, p2:
                self.assertEqual(_platform.tag(), want)
                self.assertEqual(ev.platform_tag(), want)

    def test_real_tag_is_one_of_the_normalised_forms(self):
        self.assertRegex(_platform.tag(), r"^[a-z0-9]+-(arm64|x86_64|[a-z0-9_]+)$")
        self.assertNotIn("aarch64", _platform.tag())
        self.assertNotIn("amd64", _platform.tag())


class TestExpected(unittest.TestCase):
    # inject: delete one platform entry from the json, or a provenance note
    def test_every_key_has_all_three_platforms_with_provenance(self):
        self.assertEqual(set(EXPECTED), {"test_multi_steps_known_numbers", "rule_abandon_pin", "fleet_stream"})
        for name, per_tag in EXPECTED.items():
            for t in TAGS:
                self.assertIn(t, per_tag, (name, t))
                self.assertTrue(per_tag[t].get("provenance"), (name, t))

    def test_values_are_the_measured_ones(self):
        e = EXPECTED
        m = e["test_multi_steps_known_numbers"]
        self.assertEqual([(m[t]["deliveries_500"], m[t]["deliveries_2000"]) for t in TAGS],
                         [(24, 86), (24, 93), (24, 93)])
        self.assertEqual([e["rule_abandon_pin"][t]["seed"] for t in TAGS], [4, 14, 14])
        self.assertEqual([e["fleet_stream"][t]["seed"] for t in TAGS], [3, 1, 1])

    # inject: expected() ignores tag() and always reads the darwin entry
    def test_expected_reads_the_entry_of_the_current_tag(self):
        for t, want in zip(TAGS, [86, 93, 93]):
            with mock.patch.object(_platform, "tag", return_value=t):
                self.assertEqual(_platform.expected("test_multi_steps_known_numbers", "deliveries_2000"), want)

    # inject: expected() raises KeyError, or returns None / a default for an unknown tag
    def test_unknown_tag_is_a_visible_skip_not_a_keyerror(self):
        with mock.patch.object(_platform, "tag", return_value="darwin-x86_64"):
            for name, key in [("test_multi_steps_known_numbers", "deliveries_500"), ("rule_abandon_pin", "seed"),
                              ("fleet_stream", "seed")]:
                with self.assertRaises(unittest.SkipTest) as cm:
                    _platform.expected(name, key)
                self.assertEqual(str(cm.exception), f"no darwin-x86_64 reference yet for {name}")

    def test_results_platform_default_is_darwin_arm64(self):
        self.assertEqual(_platform.results_platform({"rows": []}), "darwin-arm64")
        self.assertEqual(_platform.results_platform({"platform": "linux-x86_64"}), "linux-x86_64")
        committed = json.loads((ROOT / "results" / "recovery" / "timeout.json").read_text())
        self.assertNotIn("platform", committed)


def run_tests_with_tag(module_path, qualname, tag_value):
    """Run one test class (or case) from a file with _platform.tag patched; returns the unittest result."""
    spec = importlib.util.spec_from_file_location(f"_probe_{Path(module_path).stem}", module_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    suite = unittest.defaultTestLoader.loadTestsFromName(qualname, mod)
    result = unittest.TestResult()
    with mock.patch.object(_platform, "tag", return_value=tag_value):
        suite.run(result)
    return result


class TestSixTestsUnderPatchedTag(unittest.TestCase):
    """The darwin gate cannot run Linux; these show the dispatch on a patched tag. Linux values are verified on the diff
    and by CI."""

    # inject: let expected() return a darwin value for a tag with no entry, or crash at module import
    def test_unknown_platform_skips_visibly_never_errors(self):
        r = run_tests_with_tag(ROOT / "tests" / "test_recovery_rule.py", "TestAbandonRedispatch", "darwin-x86_64")
        self.assertEqual((len(r.errors), len(r.failures)), (0, 0))
        self.assertGreaterEqual(len(r.skipped), 1)
        self.assertTrue(all("no darwin-x86_64 reference yet" in why for _, why in r.skipped), r.skipped)
        r = run_tests_with_tag(ROOT / "tests" / "test_evaluate.py", "TestCli.test_multi_steps_known_numbers",
                               "darwin-x86_64")
        self.assertEqual((len(r.errors), len(r.failures), len(r.skipped)), (0, 0, 1))
        self.assertIn("no darwin-x86_64 reference yet", r.skipped[0][1])

    def test_fleet_stream_class_skips_visibly_on_unknown_platform(self):
        r = run_tests_with_tag(ROOT / "fleet" / "tests" / "test_fleet_emit.py", "TestStream", "darwin-x86_64")
        self.assertEqual((len(r.errors), len(r.failures)), (0, 0))
        self.assertEqual(len(r.skipped), 1)  # setUpClass skip: the class is reported as one skip
        self.assertIn("no darwin-x86_64 reference yet for fleet_stream", r.skipped[0][1])

    # inject: skip the whole test up front, or compare values without checking the file platform
    def test_timeout_json_comparison_skips_after_portable_assertions_on_linux(self):
        for t in ("linux-x86_64", "linux-arm64"):
            r = run_tests_with_tag(ROOT / "tests" / "test_recovery_informed.py",
                                   "TestExistingPoliciesBitIdentical.test_timeout_rows_reproduce_stored_json", t)
            self.assertEqual((r.testsRun, len(r.errors), len(r.failures), len(r.skipped)), (1, 0, 0, 1), t)
            why = r.skipped[0][1]
            self.assertIn("darwin-arm64", why)
            self.assertIn(t, why)
            self.assertIn("value comparison skipped", why)


def evaluate_tiny(results_dir):
    ev.evaluate("cta", ENV_ID, 20, [0], 1, results_dir)
    return Path(results_dir) / f"cta_{ENV_ID}_20.json"


class TestEvaluateStampsPlatform(unittest.TestCase):
    # inject: stamp rows instead of the header, or omit the field
    def test_header_has_platform_rows_do_not(self):
        with tempfile.TemporaryDirectory() as d:
            doc = json.loads(evaluate_tiny(d).read_text())
        self.assertEqual(doc["platform"], ev.platform_tag())
        self.assertEqual(list(doc)[0], "platform")
        self.assertTrue(all("platform" not in r for r in doc["rows"]))

    # inject: drop _check_same_platform from evaluate(), or treat a missing field as the current platform
    def test_resume_onto_other_platform_raises_and_leaves_file_alone(self):
        with tempfile.TemporaryDirectory() as d:
            path = evaluate_tiny(d)
            doc = json.loads(path.read_text())
            doc["platform"] = "linux-x86_64" if ev.platform_tag() != "linux-x86_64" else "darwin-arm64"
            path.write_text(json.dumps(doc))
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "refusing to merge"):
                ev.evaluate("cta", ENV_ID, 20, [0, 1], 1, d)
            self.assertEqual(path.read_bytes(), before)

    def test_resume_on_same_platform_merges_and_keeps_rows(self):
        with tempfile.TemporaryDirectory() as d:
            path = evaluate_tiny(d)
            ev.evaluate("cta", ENV_ID, 20, [0, 1], 1, d)
            doc = json.loads(path.read_text())
        self.assertEqual([r["seed"] for r in doc["rows"]], [0, 1])
        self.assertEqual(doc["platform"], ev.platform_tag())

    # inject: default a missing field to the current platform instead of darwin-arm64
    def test_doc_without_platform_counts_as_darwin_arm64(self):
        with tempfile.TemporaryDirectory() as d:
            path = evaluate_tiny(d)
            doc = json.loads(path.read_text())
            del doc["platform"]
            path.write_text(json.dumps(doc))
            with mock.patch.object(ev, "platform_tag", return_value="linux-arm64"):
                with self.assertRaisesRegex(ValueError, "measured on darwin-arm64"):
                    ev.evaluate("cta", ENV_ID, 20, [0, 1], 1, d)
            with mock.patch.object(ev, "platform_tag", return_value="darwin-arm64"):
                ev.evaluate("cta", ENV_ID, 20, [0, 1], 1, d)
            self.assertEqual(json.loads(path.read_text())["platform"], "darwin-arm64")


if __name__ == "__main__":
    unittest.main()

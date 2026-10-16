"""Collector: `unittest discover -s tests` only walks tests/, so this module (load_tests protocol) pulls in the fleet
tests (fleet/tests/test_fleet_*.py) and the repo gate runs them. They are imported as fleet.tests.<module> from the
repo root, so their names cannot collide with tests/test_*.py. Fleet tests never skip."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FLEET_TESTS = ROOT / "fleet" / "tests"
for _p in (ROOT, ROOT / "fleet", ROOT / "src", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def load_tests(loader, standard_tests, pattern):
    suite = unittest.TestSuite()
    suite.addTests(standard_tests)
    suite.addTests(unittest.TestLoader().discover(str(FLEET_TESTS), pattern="test_fleet_*.py", top_level_dir=str(ROOT)))
    # S8P: the operator fixed this file's name, which test_fleet_*.py does not match, so it gets its own discover
    suite.addTests(unittest.TestLoader().discover(str(FLEET_TESTS), pattern="test_time_to_detect.py",
                                                  top_level_dir=str(ROOT)))
    return suite


class TestCollector(unittest.TestCase):
    def test_fleet_test_files_exist_and_are_discoverable(self):
        # inject: point FLEET_TESTS at a missing directory (discover then yields nothing and the gate would not notice)
        files = sorted(p.name for p in FLEET_TESTS.glob("test_fleet_emit*.py"))
        self.assertTrue(files)
        found = unittest.TestLoader().discover(str(FLEET_TESTS), pattern="test_fleet_*.py", top_level_dir=str(ROOT))
        self.assertGreater(found.countTestCases(), 0)

    def test_time_to_detect_tests_are_collected(self):
        # inject: drop the extra discover in load_tests (the file would run nowhere in the gate)
        suite = load_tests(unittest.TestLoader(), unittest.TestSuite(), "test*.py")

        def names(s):
            for t in s:
                if isinstance(t, unittest.TestSuite):
                    yield from names(t)
                else:
                    yield type(t).__module__

        self.assertIn("fleet.tests.test_time_to_detect", set(names(suite)))


if __name__ == "__main__":
    unittest.main()

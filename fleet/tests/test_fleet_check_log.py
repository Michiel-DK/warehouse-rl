"""Tests for S17A fleet/check_log.py (field-by-field contract check) and the replay page's reason keys.

Fresh emit output is platform-dependent (pyastar2d tie-break), so no test pins a hash of it: the committed fixture
fleet/tests/data/s17a_emit50 (50 steps x 12 robots, emitted once) stands in for a log that matches.
Each case names its red demonstration in an `# inject:` comment."""
import gzip
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "fleet", ROOT / "src", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import check_log  # noqa: E402
import replay_export as rx  # noqa: E402

SCRIPT = str(ROOT / "fleet" / "check_log.py")
EMIT = str(ROOT / "fleet" / "emit.py")
FIXTURE = ROOT / "fleet" / "tests" / "data" / "s17a_emit50"
REQUIRED = ["headerId", "timestamp", "serialNumber", "orderId", "agvPosition", "driving", "errors", "loads",
            "agvPosition.x", "agvPosition.y"]
BAD_LOG = [b'{"robot":"r1","time":"2026-10-23 08:00:00","x":1,"y":2}\n',
           b'{"robot":"r1","time":"2026-10-23 08:00:00","x":1,"y":2}\n', b"not json at all\n"]


def write_gz(path, lines):
    with gzip.open(path, "wb") as f:
        f.write(b"".join(lines))


def cli(*args):
    return subprocess.run([sys.executable, SCRIPT, *map(str, args)], capture_output=True, text=True)


def fixture_lines():
    with gzip.open(FIXTURE / "zone0-000.jsonl.gz", "rb") as f:
        return f.readlines()


class TestCheckLog(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_operator_bad_log_does_not_match_and_names_all_ten_fields(self):
        # inject: count a line as parsing when its fields are absent, or exit 0 on a bad log
        write_gz(self.dir / "zone0-000.jsonl.gz", BAD_LOG)
        r = cli("--glob", self.dir / "*.jsonl.gz")
        self.assertEqual(r.returncode, 2, r.stdout)
        verdict = r.stdout.splitlines()[-1]
        self.assertEqual(verdict, "check_log: DOES NOT MATCH: 10 of 10 fields missing (" + ", ".join(REQUIRED)
                         + "), 0/3 lines parse; see docs/SCOPE.md \"S5A\" and fleet/adapters/moroop.py for how a "
                           "source is adapted")
        self.assertIn("not a JSON object", r.stdout)
        self.assertIn("<missing>", r.stdout)
        self.assertIn("missing:agvPosition.y", r.stdout)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["zone0-000.jsonl.gz"])  # writes nothing

    def test_fresh_emit_run_matches(self):
        # inject: reject a field the emitter writes (e.g. require nodeStates)
        out = self.dir / "emit"
        r = subprocess.run([sys.executable, EMIT, "--zones", "1", "--steps", "50", "--sink", "file", "--dir", str(out)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        c = cli("--glob", out / "*.jsonl.gz", "--lines", 50)
        self.assertEqual(c.returncode, 0, c.stdout)
        self.assertEqual(c.stdout.splitlines()[-1], "check_log: MATCHES the fleet-state contract (50/50 lines parse)")

    def test_committed_fixture_matches_with_default_lines(self):
        # inject: ignore the default --lines 500 and read only the first line
        c = cli("--glob", FIXTURE / "*.jsonl.gz")
        self.assertEqual(c.returncode, 0, c.stdout)
        self.assertEqual(c.stdout.splitlines()[-1], "check_log: MATCHES the fleet-state contract (500/500 lines parse)")
        self.assertIn("optional", c.stdout)

    def test_local_timestamps_fail_on_the_timestamp_field_only(self):
        # inject: treat a present-but-malformed field as fine in check_field
        lines = []
        for raw in fixture_lines():
            obj = json.loads(raw)
            obj["timestamp"] = "2026-01-01 00:00:00"
            lines.append(json.dumps(obj).encode() + b"\n")
        write_gz(self.dir / "zone0-000.jsonl.gz", lines)
        c = cli("--glob", self.dir / "*.jsonl.gz")
        self.assertEqual(c.returncode, 2, c.stdout)
        verdict = c.stdout.splitlines()[-1]
        self.assertTrue(verdict.startswith("check_log: DOES NOT MATCH: 0 of 10 fields missing, failing: timestamp "
                                           "(timestamp:timestamp), 0/500 lines parse; see"), verdict)
        self.assertIn("'2026-01-01 00:00:00'", c.stdout)

    def test_plain_jsonl_and_two_files_sum(self):
        # inject: detect gzip by the .gz suffix, or read only the first matched file
        (self.dir / "a.jsonl").write_bytes(b"".join(fixture_lines()[:10]))
        write_gz(self.dir / "b.jsonl.gz", fixture_lines()[10:15])
        c = cli("--glob", self.dir / "*.jsonl*")
        self.assertEqual(c.stdout.splitlines()[-1], "check_log: MATCHES the fleet-state contract (15/15 lines parse)")

    def test_no_files_or_no_lines_is_a_one_line_error(self):
        # inject: print MATCHES for zero lines
        c = cli("--glob", self.dir / "*.jsonl.gz")
        self.assertEqual((c.returncode, len(c.stdout.splitlines())), (2, 1))
        write_gz(self.dir / "zone0-000.jsonl.gz", [])
        c = cli("--glob", self.dir / "*.jsonl.gz")
        self.assertEqual((c.returncode, len(c.stdout.splitlines())), (2, 1))

    def test_partial_failure_names_field_and_reason(self):
        # inject: only report fields that no line has
        lines = fixture_lines()[:4]
        obj = json.loads(lines[2])
        obj["agvPosition"]["x"] = 1.5
        lines[2] = json.dumps(obj).encode() + b"\n"
        write_gz(self.dir / "zone0-000.jsonl.gz", lines)
        c = cli("--glob", self.dir / "*.jsonl.gz")
        self.assertEqual(c.returncode, 2)
        self.assertIn("0 of 10 fields missing, failing: agvPosition.x (type:agvPosition.x), 3/4 lines parse;",
                      c.stdout.splitlines()[-1])

    def test_long_values_are_cut_and_output_is_deterministic(self):
        # inject: print the whole offending value, or iterate a set
        lines = fixture_lines()[:2]
        obj = json.loads(lines[1])
        obj["orderId"] = "x" * 500
        obj["driving"] = "y" * 500
        lines[1] = json.dumps(obj).encode() + b"\n"
        write_gz(self.dir / "zone0-000.jsonl.gz", lines)
        a, b = cli("--glob", self.dir / "*.jsonl.gz"), cli("--glob", self.dir / "*.jsonl.gz")
        self.assertEqual(a.stdout, b.stdout)
        self.assertNotIn("x" * 200, a.stdout)
        self.assertIn("...", a.stdout)
        self.assertIn("failing: driving (type:driving)", a.stdout)

    def test_check_log_has_no_second_list_of_the_keys(self):
        # inject: paste the key list into check_log.py
        src = Path(check_log.__file__).read_text()
        for key in ("headerId", "serialNumber", "orderId", "driving"):
            self.assertNotIn(key, src)
        self.assertIs(check_log.REQUIRED_FIELDS, __import__("fleet_analyser.parse", fromlist=["x"]).REQUIRED_FIELDS)


class TestReplayReasonKeys(unittest.TestCase):
    def test_rejected_by_reason_keeps_the_page_keys(self):
        # inject: leave the extended strings in rejected_by_reason (committed docs/replay data would change)
        lines = fixture_lines()[:6]
        bad_ts = json.loads(lines[0])
        bad_ts["timestamp"] = "2026-01-01 00:00:00"
        bad_type = json.loads(lines[1])
        bad_type["driving"] = "no"
        bad_missing = json.loads(lines[2])
        del bad_missing["orderId"]
        data = [json.dumps(bad_ts).encode() + b"\n", json.dumps(bad_type).encode() + b"\n",
                json.dumps(bad_missing).encode() + b"\n", b"[1]\n", b"junk\n"] + lines[3:]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "zone0-000.jsonl.gz"
            write_gz(path, data)
            _, totals = rx.replay_extractor([path], 1767225600, 10, None)
        self.assertEqual(totals["rejected_by_reason"], {"json": 1, "missing:orderId": 1, "timestamp": 1, "type": 2})


if __name__ == "__main__":
    unittest.main()

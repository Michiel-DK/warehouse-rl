"""S19A fleet/run_on_log.py: one command from a fleet-state log to a report. Subprocess tests on a small fixture built here
(two stopped robots, one on a station cell and one away from every station, plus a message gap) and on MoRoOp shift 1.
Each case names its red demonstration in an `# inject:` comment."""
import datetime
import gzip
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = str(ROOT / "fleet" / "run_on_log.py")
SENTENCE = ("Descriptive, not graded: this log carries no right answers, so no figure here is a hit rate. "
            "The blocking number compares shifts; it does not say where.")
BASE = 1767225600
STATION = (5, 5)
AWAY = (9, 9)
OUTPUTS = ("check_log.txt", "store", "timebudget.json", "blocking.json", "report.md")


def stamp(step):
    t = datetime.datetime.fromtimestamp(BASE + 5 * step, datetime.timezone.utc)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def obj(serial, step, x, y, order, driving):
    return {"headerId": step, "timestamp": stamp(step), "serialNumber": serial, "orderId": order,
            "agvPosition": {"x": x, "y": y}, "driving": driving, "errors": [], "loads": []}


def fixture_objects(steps=60):
    """Z0-01 stopped with an order on the station cell, Z0-02 stopped with an order away from it (both for steps 0-29, 150 s,
    then they drive off), Z0-03 drives along y=14 with a gap (no lines for steps 20-24)."""
    out = []
    for s in range(steps):
        for serial, (x0, y0) in (("Z0-01", STATION), ("Z0-02", AWAY)):
            if s < 30:
                out.append(obj(serial, s, x0, y0, "o1", False))
            else:
                out.append(obj(serial, s, x0 + s - 29, y0, "o1", True))
        if not 20 <= s <= 24:
            out.append(obj("Z0-03", s, s % 20, 14, "o2", True))
    return out


def write_log(directory, objs):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with gzip.open(directory / "zone0-000.jsonl.gz", "wb") as f:
        for o in objs:
            f.write((json.dumps(o) + "\n").encode())
    return str(directory / "*.jsonl.gz")


def write_stations(path):
    Path(path).write_text(json.dumps({"stations": [list(STATION)], "shelves": []}))
    return str(path)


def cli(*args):
    return subprocess.run([sys.executable, SCRIPT, *map(str, args)], capture_output=True, text=True)


class TestRunOnLog(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.stations = write_stations(self.tmp / "stations.json")

    def run_fixture(self, name, objs=None):
        glob = write_log(self.tmp / name / "log", objs or fixture_objects())
        out = self.tmp / name / "out"
        return glob, out, cli("--glob", glob, "--stations", self.stations, "--out", out)

    def test_a_end_to_end_station_stop_absent_away_stop_present(self):
        # inject: ingest without --stations (the station stop becomes an episode and cell 5-5 appears in the hotspots)
        glob, out, r = self.run_fixture("a")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for name in OUTPUTS:
            self.assertTrue((out / name).exists(), name)
        self.assertTrue(any((out / "store").iterdir()))
        text = (out / "report.md").read_text()
        self.assertIn("\n" + SENTENCE + "\n", text)
        self.assertLess(text.index(SENTENCE), text.index("# Stuck episode report"))
        self.assertIn(f"- input: `{glob}`, ", text)
        self.assertIn(f"- stations: `{self.stations}`", text)
        self.assertNotIn(str(out), text)
        hot = text[text.index("## Hotspots"):text.index("## Episodes per event hour")]
        self.assertIn(f"cell {AWAY[0]}-{AWAY[1]}: 1", hot)
        self.assertNotIn(f"cell {STATION[0]}-{STATION[1]}", hot)
        self.assertTrue((out / "check_log.txt").read_text().splitlines()[-1].startswith(
            "check_log: MATCHES the fleet-state contract"))

    def test_b_mismatch_exits_2_and_runs_nothing_else(self):
        # How this was checked: with the ingest step moved before the check_log step in main(), OUT/store existed, so this
        # test failed; restored afterwards. inject: run ingest before check_log
        objs = fixture_objects()
        for o in objs:
            del o["agvPosition"]
        _, out, r = self.run_fixture("b", objs)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("DOES NOT MATCH", r.stdout)
        self.assertFalse((out / "store").exists())
        for name in ("timebudget.json", "blocking.json", "report.md"):
            self.assertFalse((out / name).exists(), name)

    def test_c_two_runs_byte_identical(self):
        # inject: put OUT or a timestamp in the header
        glob = write_log(self.tmp / "c" / "log", fixture_objects())
        reports = []
        for k in (1, 2):
            out = self.tmp / "c" / f"out{k}"
            r = cli("--glob", glob, "--stations", self.stations, "--out", out)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            reports.append((out / "report.md").read_bytes())
        self.assertEqual(reports[0], reports[1])

    def test_nonempty_out_refused_untouched(self):
        # inject: write into an existing OUT
        glob = write_log(self.tmp / "n" / "log", fixture_objects())
        out = self.tmp / "n" / "out"
        out.mkdir()
        (out / "mine.txt").write_text("keep")
        r = cli("--glob", glob, "--stations", self.stations, "--out", out)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["mine.txt"])
        self.assertEqual((out / "mine.txt").read_text(), "keep")


def find_moroop(*rel):
    """The gitignored MoRoOp data: this checkout, else the main checkout (a worktree has none of it)."""
    cands = [ROOT]
    try:
        common = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                capture_output=True, text=True, check=True).stdout.strip()
        cands.append(Path(common).parent)
    except (subprocess.CalledProcessError, OSError):
        pass
    for base in cands:
        p = base.joinpath(*rel)
        if p.exists():
            return p
    return None


class TestMoroopShift1(unittest.TestCase):
    def test_d_shift_1_shares_equal_the_committed_file(self):
        # inject: drop --station-radius 1 or --servicing-max-s auto (shares move off the committed -sf values)
        gz = find_moroop("fleet", "data", "moroop", "jsonl-sf", "zone1-000.jsonl.gz")
        st = find_moroop("fleet", "data", "moroop", "stations-sf.json")
        if gz is None or st is None:
            reason = "MoRoOp shift 1 (gitignored fleet/data/moroop/jsonl-sf/zone1-000.jsonl.gz, stations-sf.json) is absent"
            print(f"SKIP test_d: {reason}", file=sys.stderr)
            self.skipTest(reason)
        committed = json.loads((ROOT / "results" / "fleet" / "timebudget_moroop_shifts-sf.json").read_text())
        want = committed["shifts"]["1"]["timebudget_robot"]["share"]
        with tempfile.TemporaryDirectory() as d:
            link = Path(d) / "shift1"  # a private glob directory, so no store of the original is next to the log
            link.mkdir()
            (link / gz.name).symlink_to(gz)
            out = Path(d) / "out"
            r = cli("--glob", link / "*.jsonl.gz", "--stations", st, "--station-radius", 1, "--servicing-max-s", "auto",
                    "--out", out)
            # Known, not fixed here (report.py is out of scope): on this shift the report step ends in an IndexError, because
            # fleet_analyser/report.py plot_hotspots indexes grid[y][x] and the open station_overrun episode sits at cell
            # (9, -3). So exit 0 is NOT asserted: the step order and timebudget.json (written before the report step) are.
            self.assertIn(r.returncode, (0, 1), r.stdout + r.stderr)
            if r.returncode == 1:
                self.assertIn("IndexError", r.stderr)
                self.assertIn("plot_hotspots", r.stderr)
            got = json.loads((out / "timebudget.json").read_text())["zones"][""]["totals"]["share"]
        self.assertEqual(got, want)  # exact equality held (same 9 buckets); no tolerance used


if __name__ == "__main__":
    unittest.main()

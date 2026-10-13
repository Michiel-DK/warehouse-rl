"""Tests for the ground-truth scorer (fleet_analyser/score.py) and the rule that nothing else reads the simulator
ground-truth block. Scripted robots with hand-placed flags exercise each rule; one real emitter run checks isolation.
Each case names its red demonstration in an `# inject:` comment. Unit tests, no Docker, none skipped."""
import ast
import copy
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

from fleet.tests.test_fleet_ingest import (BASE, GARBAGE_CUSTOM, Clock, emit_real, ingest_dir, line,  # noqa: E402
                                           tables, write_gz)
from fleet_analyser import grade, score  # noqa: E402
from fleet_analyser.store import MemoryStore  # noqa: E402

SCORE_CLI = str(ROOT / "fleet" / "score.py")
KEYS = {"run", "stuck_after", "truth_episodes", "detected_episodes", "detected_excluded", "matched", "precision",
        "recall", "unmatched_detected", "cause_proximity_agreement", "resolution_agreement", "faulted_self",
        "truth_definition"}


# ------------------------------------------------------------------------------------------------ scripted robots
def stuck_run(first, k, order="o1", end_driving=True, end_order=None, clash=False, action=None, x=0, y=0):
    """Overrides for a robot stopped with `order` at steps first..first+k-1, each flagged by the simulator on the NEXT
    message (so the flags sit on steps first+1..first+k). Step first+k is the message after the last truth step."""
    ov = {}
    for t in range(first, first + k):
        ov[t] = dict(order=order, driving=False, x=x, y=y, stuck=t > first, clash=clash and t == first + 1)
    ov[first + k] = dict(order=order if end_order is None else end_order, driving=end_driving, x=x, y=y, stuck=True,
                         action=action)
    return ov


def robot(serial, n, *runs, **fixed):
    """n lines for `serial`; later overrides win. fixed = overrides applied to every step (e.g. a frozen neighbour)."""
    ov = {}
    for r in runs:
        ov.update(r)
    out = []
    for t in range(n):
        d = dict(order="", driving=True, x=0, y=0, faulted=False, stuck=False, clash=False, action=None)
        d.update(fixed)
        d.update(ov.get(t, {}))
        custom = {"stuck_count": 0, "carrying": False, "recovery_action": d["action"], "stuck_event": d["stuck"],
                  "clash_event": d["clash"]}
        out.append(line(serial, t, t, order=d["order"], driving=d["driving"], x=d["x"], y=d["y"],
                        faulted=d["faulted"], custom=custom))
    return out


def ep(robot_, first, last, cause="unknown", resolution="moved", zone="0", cell=(0, 0), **kw):
    """A stuck_episodes row from step `first` (start) to step `last` (end), t_entry = start + 30 s."""
    start = BASE + 5 * first
    row = dict(run="r", episode_id=f"{robot_}@{start}", zone=zone, robot=robot_, order_id="o1", start=start,
               start_iso="", t_entry=start + 30, cell=list(cell), cause=cause, blocker=None, blocker_faulted_s=None,
               end=BASE + 5 * last, duration_s=5 * (last - first), resolution=resolution, avoidable=False,
               avoidable_s=None, left_censored=False)
    row.update(kw)
    return row


def run_score(lines_by_robot, episodes, stuck_after=30):
    """Score scripted robots (all in zone 0) against scripted detector rows."""
    store = MemoryStore()
    store.insert("stuck_episodes", episodes)
    return score.score_run({"0": [ln for lines in lines_by_robot for ln in lines]}, store, "r", stuck_after)


R = "Z0-00"


class TestTruth(unittest.TestCase):
    def test_a_six_step_run_counts_and_a_five_step_run_does_not(self):
        # inject: keep truth runs of end - start >= stuck_after - 5 (accept 5 steps), or > instead of >= (reject 6)
        six = run_score([robot(R, 30, stuck_run(3, 6))], [])
        five = run_score([robot(R, 30, stuck_run(3, 5))], [])
        self.assertEqual(six["truth_episodes"], 1)
        self.assertEqual(five["truth_episodes"], 0)

    def test_stuck_event_on_message_t_alone_does_not_make_t_a_stuck_step(self):
        # inject: read the flag of message t instead of message t + 1 (the alignment the scorer is built on)
        ov = {t: dict(order="o1", driving=False, stuck=t <= 5) for t in range(0, 8)}  # flags on messages 0..5 only
        res = run_score([robot(R, 20, ov)], [])
        self.assertEqual(res["truth_episodes"], 0)  # steps 0..4 have a flag on t+1 (5 steps = 25 s < 30)

    def test_truth_step_needs_no_error_an_order_and_not_driving(self):
        # inject: drop the errors-empty condition (a frozen robot with a flag would then be a truth step)
        base = stuck_run(3, 8)
        frozen = {t: dict(v, faulted=True) for t, v in base.items()}
        no_order = {t: dict(v, order="") for t, v in base.items()}
        driving = {t: dict(v, driving=True) for t, v in base.items()}
        for ov in (frozen, no_order, driving):
            self.assertEqual(run_score([robot(R, 30, ov)], [])["truth_episodes"], 0)
        self.assertEqual(run_score([robot(R, 30, base)], [])["truth_episodes"], 1)

    def test_an_order_change_splits_the_run_and_the_last_message_is_not_a_step(self):
        # inject: ignore the orderId when extending a run (the two 4-step halves would join into one 8-step episode)
        ov = {t: dict(order="o1" if t < 7 else "o2", driving=False, stuck=t > 3) for t in range(3, 11)}
        ov[11] = dict(order="o2", driving=True, stuck=True)  # two 4-step runs (20 s each); one 8-step run if joined
        self.assertEqual(run_score([robot(R, 30, ov)], [])["truth_episodes"], 0)
        # a robot whose stopped run reaches its last message has no next message: that step is not counted
        tail = {t: dict(order="o1", driving=False, stuck=t > 3) for t in range(3, 9)}  # n = 9, steps 3..8
        self.assertEqual(run_score([robot(R, 9, tail)], [])["truth_episodes"], 0)


class TestMatching(unittest.TestCase):
    TRUTH = stuck_run(3, 8)  # truth interval [3, 11] steps

    def test_overlap_matches_and_precision_recall_follow(self):
        # inject: require the detected interval to be inside the truth interval
        res = run_score([robot(R, 30, self.TRUTH)], [ep(R, 4, 12)])
        self.assertEqual((res["truth_episodes"], res["detected_episodes"], res["matched"]), (1, 1, 1))
        self.assertEqual((res["precision"], res["recall"]), (1.0, 1.0))

    def test_no_overlap_is_a_miss_and_touching_intervals_do_not_overlap(self):
        # inject: use >= 0 instead of > 0 for the overlap test (touching intervals would match)
        far = run_score([robot(R, 40, self.TRUTH)], [ep(R, 20, 30)])
        self.assertEqual((far["matched"], far["precision"], far["recall"]), (0, 0.0, 0.0))
        touch = run_score([robot(R, 40, self.TRUTH)], [ep(R, 11, 20)])  # starts exactly where the truth ends
        self.assertEqual(touch["matched"], 0)
        other_robot = run_score([robot(R, 30, self.TRUTH)], [ep("Z0-07", 4, 12)])
        self.assertEqual(other_robot["matched"], 0)

    def test_matching_is_one_to_one_and_ties_go_to_the_earliest(self):
        # inject: let a truth episode be matched by every detected episode that overlaps it
        two_detected = run_score([robot(R, 30, self.TRUTH)], [ep(R, 4, 8), ep(R, 9, 13)])
        self.assertEqual((two_detected["matched"], two_detected["precision"], two_detected["recall"]), (1, 0.5, 1.0))
        t2 = stuck_run(15, 8, order="o2")  # a second truth episode of the same robot
        both = {**self.TRUTH, **t2}
        one_detected = run_score([robot(R, 40, both)], [ep(R, 4, 20)])
        self.assertEqual((one_detected["truth_episodes"], one_detected["matched"]), (2, 1))
        self.assertEqual((one_detected["precision"], one_detected["recall"]), (1.0, 0.5))

    def test_zero_denominators_give_null_not_zero(self):
        # inject: return 0.0 instead of None when a denominator is zero
        res = run_score([robot(R, 10)], [])
        self.assertEqual((res["truth_episodes"], res["detected_episodes"]), (0, 0))
        self.assertIsNone(res["precision"])
        self.assertIsNone(res["recall"])
        self.assertIsNone(res["cause_proximity_agreement"]["agreement"])
        self.assertIsNone(res["resolution_agreement"]["agreement"])
        self.assertIsNone(res["faulted_self"]["frozen_at_entry"])

    def test_only_countable_non_faulted_self_rows_are_detected(self):
        # inject: count open rows (or left_censored rows) as detected
        rows = [ep(R, 4, 12), ep(R, 20, 21, resolution="open", end=None), ep(R, 22, 23, resolution="interrupted"),
                ep(R, 24, 25, left_censored=True), ep(R, 26, 27, cause="faulted_self", resolution="fault_cleared"),
                ep(R, 28, 29, left_censored=True, resolution="interrupted")]
        res = run_score([robot(R, 40, self.TRUTH)], rows)
        self.assertEqual(res["detected_episodes"], 1)
        self.assertEqual(res["detected_excluded"], {"left_censored": 2, "interrupted": 1, "open": 1, "faulted_self": 1})

    def test_unmatched_detected_split(self):
        # inject: report every unmatched detected episode as by_design
        short = stuck_run(3, 4)  # 20 s truth run: shorter than stuck_after
        frozen = {t: dict(order="o1", driving=False, faulted=True) for t in range(12, 20)}
        ov = {**short, **frozen}
        rows = [ep(R, 2, 8), ep(R, 12, 19), ep(R, 25, 33)]
        res = run_score([robot(R, 40, ov)], rows)
        self.assertEqual(res["matched"], 0)
        self.assertEqual(res["unmatched_detected"], {"frozen": 1, "short_truth": 1, "by_design": 1})


class TestCauseAndResolution(unittest.TestCase):
    def confusion(self, res):
        return {c: {t: n for t, n in row.items() if n} for c, row in
                res["cause_proximity_agreement"]["confusion"].items() if any(row.values())}

    def test_truth_class_clash(self):
        # inject: ignore the clash flag (the pair would fall through to `other`)
        res = run_score([robot(R, 30, stuck_run(3, 8, clash=True))], [ep(R, 3, 11, cause="traffic")])
        self.assertEqual(self.confusion(res), {"traffic": {"clash": 1}})
        self.assertEqual(res["cause_proximity_agreement"]["agreement"], 1.0)

    def test_truth_class_frozen_neighbour(self):
        # inject: require Manhattan distance 0 instead of <= 1, or look at neighbours of any zone
        neighbour = robot("Z0-01", 30, x=1, y=0, faulted=True)
        far = robot("Z0-01", 30, x=3, y=0, faulted=True)
        near = run_score([robot(R, 30, stuck_run(3, 8)), neighbour], [ep(R, 3, 11, cause="blocked_by_faulted")])
        self.assertEqual(self.confusion(near), {"blocked_by_faulted": {"frozen_neighbour": 1}})
        self.assertEqual(near["cause_proximity_agreement"]["agreement"], 1.0)
        away = run_score([robot(R, 30, stuck_run(3, 8)), far], [ep(R, 3, 11, cause="blocked_by_faulted")])
        self.assertEqual(self.confusion(away), {"blocked_by_faulted": {"other": 1}})
        self.assertEqual(away["cause_proximity_agreement"]["agreement"], 0.0)

    def test_truth_class_other_and_the_detector_cause_mapping(self):
        # inject: map unknown to frozen_neighbour, or make traffic agree only with clash
        plain = [robot(R, 30, stuck_run(3, 8))]
        for cause, agrees in (("unknown", 1.0), ("traffic", 1.0), ("blocked_by_stuck", 1.0), ("blocked_by_faulted", 0.0)):
            res = run_score(plain, [ep(R, 3, 11, cause=cause)])
            self.assertEqual(self.confusion(res), {cause: {"other": 1}}, cause)
            self.assertEqual(res["cause_proximity_agreement"]["agreement"], agrees, cause)

    def test_the_cause_figure_is_never_called_accuracy_and_carries_the_caveat(self):
        # inject: add an `accuracy` key (or metric name) to the cause block
        res = run_score([robot(R, 30, stuck_run(3, 8))], [ep(R, 3, 11)])
        self.assertEqual(set(res["cause_proximity_agreement"]), {"agreement", "confusion", "note"})
        self.assertNotIn("accuracy", score.dumps(res))
        self.assertIn("not ground truth", res["cause_proximity_agreement"]["note"])

    def test_abandon_agrees_with_order_dropped(self):
        # inject: compare the detector resolution with the abandon flag inverted, or look only before the end message
        dropped = stuck_run(3, 8, end_order="", action="abandon")
        plain = stuck_run(3, 8)
        cases = [(dropped, "order_dropped", ("order_dropped", "abandon")), (plain, "moved", ("not_order_dropped", "no_abandon")),
                 (plain, "order_dropped", ("order_dropped", "no_abandon")),
                 (dropped, "moved", ("not_order_dropped", "abandon"))]
        for ov, resolution, (row, col) in cases:
            res = run_score([robot(R, 30, ov)], [ep(R, 3, 11, resolution=resolution)])
            table = res["resolution_agreement"]["table"]
            self.assertEqual(table[row][col], 1, (resolution, row, col))
            self.assertEqual(sum(sum(v.values()) for v in table.values()), 1)
            self.assertEqual(res["resolution_agreement"]["agreement"], 1.0 if (row, col) in (
                ("order_dropped", "abandon"), ("not_order_dropped", "no_abandon")) else 0.0)

    def test_faulted_self_is_scored_apart_and_checks_the_frozen_flag_at_entry(self):
        # inject: count faulted_self rows in precision, or test the frozen flag at the episode start instead of t_entry
        frozen = {t: dict(order="o1", driving=False, faulted=True) for t in range(3, 12)}
        thawed = {t: dict(order="o1", driving=False) for t in range(20, 29)}
        rows = [ep(R, 3, 11, cause="faulted_self", resolution="fault_cleared"),
                ep("Z0-01", 20, 28, cause="faulted_self", resolution="fault_cleared")]
        res = run_score([robot(R, 40, frozen), robot("Z0-01", 40, thawed)], rows)
        self.assertEqual(res["faulted_self"], {"count": 2, "frozen_at_entry": 0.5})
        self.assertEqual(res["detected_episodes"], 0)
        self.assertEqual(res["detected_excluded"]["faulted_self"], 2)


class TestOutput(unittest.TestCase):
    def test_keys_and_byte_identical_json(self):
        # inject: drop sort_keys, or add a wall-clock field to the result
        lines = [robot(R, 30, stuck_run(3, 8, clash=True))]
        a = score.dumps(run_score(lines, [ep(R, 3, 11, cause="traffic")]))
        b = score.dumps(run_score(lines, [ep(R, 3, 11, cause="traffic")]))
        self.assertEqual(a, b)
        res = json.loads(a)
        self.assertEqual(set(res), KEYS)
        self.assertEqual(set(res["detected_excluded"]), {"left_censored", "interrupted", "open", "faulted_self"})
        self.assertEqual(set(res["unmatched_detected"]), {"frozen", "short_truth", "by_design"})
        self.assertEqual(set(res["resolution_agreement"]), {"agreement", "table"})
        self.assertEqual(set(res["faulted_self"]), {"count", "frozen_at_entry"})
        self.assertEqual(res["stuck_after"], 30)
        self.assertNotIn("\n", res["truth_definition"])

    def test_stuck_after_is_a_parameter(self):
        # inject: ignore the stuck_after argument (hard-code 30)
        lines = [robot(R, 30, stuck_run(3, 4))]
        self.assertEqual(run_score(lines, [], stuck_after=30)["truth_episodes"], 0)
        self.assertEqual(run_score(lines, [], stuck_after=20)["truth_episodes"], 1)

    def test_zone_files_are_in_numeric_order_and_the_cli_writes_score_json(self):
        # inject: sort zone files as strings (zone10 before zone2, 10 before 9)
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            for name in ("zone2-000", "zone10-000", "zone2-010", "zone2-009", "zone2-002"):
                write_gz(d / f"{name}.jsonl.gz", [])
            files = score.zone_files(str(d / "*.jsonl.gz"))
            self.assertEqual(list(files), ["2", "10"])
            self.assertEqual([Path(p).name[6:9] for p in files["2"]], ["000", "002", "009", "010"])
            data = d / "run"
            data.mkdir()
            write_gz(data / "zone0-000.jsonl.gz", robot(R, 30, stuck_run(3, 8)))
            store_dir = d / "st"
            r = subprocess.run([sys.executable, SCORE_CLI, "--run", "r", "--glob", str(data / "*.jsonl.gz"), "--store",
                                f"jsonl:{store_dir}"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads((data / "score.json").read_text())
            self.assertEqual((out["truth_episodes"], out["detected_episodes"], out["precision"]), (1, 0, None))
            bad = subprocess.run([sys.executable, SCORE_CLI, "--run", "r", "--glob", str(d / "none*.gz")],
                                 capture_output=True, text=True)
            self.assertEqual(bad.returncode, 2)


# ------------------------------------------------------------------------------------------------ isolation
CUSTOM_WORDS = ("custom", "stuck_event", "clash_event", "recovery_action", "stuck_count")
SOURCES = ["grade", "report", "alert", "ledger", "ingest", "detector", "decisions", "parse", "store", "kafka_source",
           "clickhouse_store"]


def code_strings(path):
    """Names, attributes and non-docstring string constants of a module (what code could use to reach a key)."""
    tree = ast.parse(Path(path).read_text())
    doc_nodes = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                doc_nodes.add(id(first.value))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in doc_nodes:
            out.append(node.value)
        elif isinstance(node, ast.Name):
            out.append(node.id)
        elif isinstance(node, ast.Attribute):
            out.append(node.attr)
        elif isinstance(node, ast.keyword) and node.arg:
            out.append(node.arg)
    return out


class TestIsolation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name) / "run"
        emit_real(cls.dir, 2, 300)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def garbage_dir(self):
        out = Path(self.tmp.name) / "garbage"
        out.mkdir(exist_ok=True)
        (out / "emit_ledger.json").write_bytes((self.dir / "emit_ledger.json").read_bytes())
        for p in sorted(self.dir.glob("*.jsonl.gz")):
            lines = []
            with gzip.open(p, "rb") as f:
                for raw in f:
                    obj = json.loads(raw)
                    obj["custom"] = copy.deepcopy(GARBAGE_CUSTOM)
                    lines.append((json.dumps(obj, separators=(",", ":")) + "\n").encode())
            write_gz(out / p.name, lines)
        return out

    def pipeline(self, directory):
        store = ingest_dir(directory, clock=Clock())[1]
        now = max(t["ts"] for t in store.select("transitions", {"run": "r"}))
        counts = grade.grade_run(store, "r", now)
        return store, tables(store), counts

    def test_detector_and_grader_never_read_custom(self):
        # inject: make parse_line reject any line whose custom block has stuck_event true
        _, a, counts_a = self.pipeline(self.dir)
        _, b, counts_b = self.pipeline(self.garbage_dir())
        self.assertGreaterEqual(len(a["stuck_episodes"]), 5)  # not vacuous
        self.assertGreaterEqual(len(a["decisions"]), 5)
        self.assertGreaterEqual(sum(1 for d in a["decisions"] if d["status"] == "graded"), 1)
        self.assertEqual(a["transitions"], b["transitions"])
        self.assertEqual(a["stuck_episodes"], b["stuck_episodes"])
        self.assertEqual(a["decisions"], b["decisions"])  # includes outcome, verdict, status, graded_at
        self.assertEqual(counts_a, counts_b)

    def test_the_garbage_run_does_bite_the_scorer(self):
        # inject: make score_run ignore the stuck flag (the garbage run would then score the same as the real one)
        store, _, _ = self.pipeline(self.dir)
        files = score.zone_files(str(self.dir / "*.jsonl.gz"))
        real = score.score_run({z: score.gz_lines(p) for z, p in files.items()}, store, "r")
        gfiles = score.zone_files(str(self.garbage_dir() / "*.jsonl.gz"))
        fake = score.score_run({z: score.gz_lines(p) for z, p in gfiles.items()}, store, "r")
        self.assertGreaterEqual(real["truth_episodes"], 1)
        self.assertNotEqual(real["truth_episodes"], fake["truth_episodes"])

    def test_only_score_py_names_the_ground_truth_block_in_code(self):
        # inject: add `x = "stuck_event"` to grade.py (any non-docstring use of a ground-truth key outside score.py)
        names = [f"fleet/fleet_analyser/{m}.py" for m in SOURCES] + [f"fleet/{m}.py" for m in
                                                                      ("grade", "report", "alert", "ledger", "ingest",
                                                                       "score")]
        for rel in names:
            hits = [s for s in code_strings(ROOT / rel) if any(w in s for w in CUSTOM_WORDS)]
            self.assertEqual(hits, [], rel)
        self.assertTrue([s for s in code_strings(ROOT / "fleet/fleet_analyser/score.py") if "stuck_event" in s])
        self.assertNotIn("stuck_count", " ".join(code_strings(ROOT / "fleet/fleet_analyser/score.py")))
        self.assertNotIn("accuracy", (ROOT / "fleet/fleet_analyser/score.py").read_text())


if __name__ == "__main__":
    unittest.main()

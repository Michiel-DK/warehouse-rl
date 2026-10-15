"""S8J-WORDING criterion C2: the sentence under the funnel ("Rebuilding the shift from what we kept gives every robot's state at
every step, and its position at every change.") is checked by rebuilding from the store's transition rows ALONE.

A real run is made in a temp dir by subprocess (fleet/emit.py: 1 zone, 150 steps, seed 0, the medium env of docs/replay/README.md,
the floor disturbance, --demo --demo-noise; then fleet/ingest.py --once). For every robot and every accepted message of the raw
file (parse_line, malformed lines skipped, the first copy of each (robot, ts)) the test rebuilds

  (a) the state at that ts from the transition rows (the last row at or before it) and compares it with a
      fleet_analyser.detector.Detector replay of the same raw messages, for ALL robot-steps;
  (b) at every transition row, the row's cell against the raw message's (x, y) of that robot and ts, for ALL transitions.

Between two changes the position is NOT rebuilt (the robot may have moved without a state change): the test counts those
robot-steps and prints the count. The comparison function lives in this module; it is not imported from replay_export.
"""
import bisect
import collections
import gzip
import json
import random
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "fleet", ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fleet_analyser.detector import Detector  # noqa: E402
from fleet_analyser.parse import parse_line  # noqa: E402
from fleet_analyser.store import JsonlStore  # noqa: E402

RUN = "s8j-rebuild"
STEPS = 150
ENV = "tarware-medium-8agvs-4pickers-globalobs-v1"
FLOOR = '{"floor": {"cells": 80, "p": [0.3, 0.7]}}'


# ------------------------------------------------------------------------------------------------ the rebuild
def read_accepted(path):
    """The accepted messages of a zone file, in file order: parse_line, malformed lines skipped, the first copy of each
    (robot, ts)."""
    seen, out = set(), []
    with gzip.open(path, "rb") as f:
        for raw in f:
            m, _ = parse_line(raw)
            if m is None or (m.serial, m.ts) in seen:
                continue
            seen.add((m.serial, m.ts))
            out.append(m)
    return out


def detector_states(msgs):
    """{robot: [(ts, state)]} from a Detector replay of the raw messages (every transition event, end_all included)."""
    det = Detector()
    events = []
    for m in msgs:
        events += det.feed(m)
    events += det.end_all()
    out = collections.defaultdict(list)
    for e in events:
        if e["kind"] == "transition":
            out[e["robot"]].append((e["ts"], e["to_state"]))
    return {r: sorted(v) for r, v in out.items()}


def by_robot(rows):
    """Transition rows grouped per robot and SORTED BY ts (never taken in file order)."""
    out = collections.defaultdict(list)
    for r in rows:
        out[r["robot"]].append(r)
    return {k: sorted(v, key=lambda r: r["ts"]) for k, v in out.items()}


def last_at(sorted_list, key_of, ts):
    """The last element of an ascending list whose key is <= ts, or None."""
    i = bisect.bisect_right([key_of(x) for x in sorted_list], ts) - 1
    return sorted_list[i] if i >= 0 else None


def compare(msgs, rows, reference):
    """Rebuild from `rows` (transition rows) and compare with the raw `msgs` and the detector `reference`.
    Returns a dict of counts: robot_steps, transitions, state_mismatch (robot-steps whose rebuilt state differs from the
    detector replay), cell_mismatch (transition rows whose cell is not the raw message's (x, y), or whose (robot, ts) is not an
    accepted message), moved_between (robot-steps whose raw position differs from the cell of the last change)."""
    tr = by_robot(rows)
    raw_xy = {(m.serial, m.ts): (m.x, m.y) for m in msgs}
    state_bad = moved = 0
    for m in msgs:
        mine = last_at(tr.get(m.serial, []), lambda r: r["ts"], m.ts)
        ref = last_at(reference.get(m.serial, []), lambda x: x[0], m.ts)
        if mine is None or ref is None or mine["to_state"] != ref[1]:
            state_bad += 1
        if mine is not None and tuple(mine["cell"]) != (m.x, m.y):
            moved += 1
    cell_bad = sum(1 for r in rows if raw_xy.get((r["robot"], r["ts"])) != tuple(r["cell"]))
    return dict(robot_steps=len(msgs), transitions=len(rows), state_mismatch=state_bad, cell_mismatch=cell_bad,
                moved_between=moved)


# ------------------------------------------------------------------------------------------------ tests
class TestRebuildFromTransitions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = Path(cls.tmp.name) / "run"
        d.mkdir()
        cls.dir = d
        for cmd in ([sys.executable, str(ROOT / "fleet" / "emit.py"), "--zones", "1", "--steps", str(STEPS), "--seed-base", "0",
                     "--env", ENV, "--disturb", FLOOR, "--demo", "--demo-noise", "--control-file", str(d / "control.jsonl"),
                     "--dir", str(d), "--workers", "1"],
                    [sys.executable, str(ROOT / "fleet" / "ingest.py"), "--glob", str(d / "*.jsonl.gz"), "--run", RUN,
                     "--store", f"jsonl:{d / 'store'}", "--once"]):
            r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
            if r.returncode != 0:
                raise RuntimeError(f"{cmd[1]} failed ({r.returncode}): {r.stdout[-800:]} {r.stderr[-800:]}")
        cls.msgs = read_accepted(next(d.glob("zone0-*.jsonl.gz")))
        st = JsonlStore(d / "store")
        cls.rows = st.select("transitions", {"run": RUN})
        st.close()
        cls.reference = detector_states(cls.msgs)
        cls.ledger = json.loads((d / "emit_ledger.json").read_text())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_run_carries_demo_noise_and_the_robots_times_steps_robot_steps(self):
        noise = self.ledger["total"]["injected_noise"]
        self.assertGreater(noise["malformed"] + noise["duplicates"], 0)
        robots = self.ledger["zones"][0]["robots"]
        self.assertEqual(len({m.serial for m in self.msgs}), robots)
        self.assertEqual(len(self.msgs), robots * STEPS)  # robot-steps == robots * steps

    def test_every_transition_row_is_an_accepted_message(self):
        # Detector.end_all closes batches and episodes; a transition is still written at the ts of the message that changed
        # the state, so there is nothing to exclude: n_changes in replay_export counts every row (see its docstring)
        accepted = {(m.serial, m.ts) for m in self.msgs}
        self.assertEqual([r for r in self.rows if (r["robot"], r["ts"]) not in accepted], [])
        self.assertGreater(len(self.rows), 0)

    def test_state_at_every_robot_step_equals_the_detector_replay(self):
        c = compare(self.msgs, self.rows, self.reference)
        print(f"\nrebuild: {c}")
        self.assertEqual(c["state_mismatch"], 0, c)

    def test_the_cell_at_every_change_is_the_raw_position(self):
        c = compare(self.msgs, self.rows, self.reference)
        self.assertEqual(c["cell_mismatch"], 0, c)
        self.assertEqual(c["transitions"], len(self.rows))

    def test_transitions_are_sorted_by_ts_per_robot_not_taken_in_file_order(self):
        shuffled = list(self.rows)
        random.Random(7).shuffle(shuffled)
        self.assertEqual(compare(self.msgs, shuffled, self.reference), compare(self.msgs, self.rows, self.reference))
        for robot, rows in by_robot(self.rows).items():
            ts = [r["ts"] for r in rows]
            self.assertEqual(ts, sorted(set(ts)), robot)

    def test_a_non_moving_state_occurs(self):
        states = {r["to_state"] for r in self.rows}
        self.assertGreater(len(states - {"MOVING"}), 0, states)

    def test_position_between_changes_is_not_rebuilt_and_the_count_is_printed(self):
        c = compare(self.msgs, self.rows, self.reference)
        print(f"\nrobot-steps whose position differs from the rebuilt position of the last change: {c['moved_between']} "
              f"of {c['robot_steps']}")
        self.assertGreater(c["moved_between"], 0)

    def test_the_comparison_reports_a_changed_state_and_a_changed_cell(self):
        base = compare(self.msgs, self.rows, self.reference)
        self.assertEqual((base["state_mismatch"], base["cell_mismatch"]), (0, 0))
        k = len(self.rows) // 2
        bad_state = [dict(r, to_state="NOT_A_STATE") if i == k else r for i, r in enumerate(self.rows)]
        c = compare(self.msgs, bad_state, self.reference)
        self.assertGreater(c["state_mismatch"], 0)
        self.assertEqual(c["cell_mismatch"], 0)
        bad_cell = [dict(r, cell=[r["cell"][0] + 1, r["cell"][1]]) if i == k else r for i, r in enumerate(self.rows)]
        c = compare(self.msgs, bad_cell, self.reference)
        self.assertEqual(c["cell_mismatch"], 1)
        self.assertEqual(c["state_mismatch"], 0)

    def test_the_comparison_function_is_not_imported_from_replay_export(self):
        text = Path(__file__).read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"^\s*(import|from)\s+replay_export", text, re.M))
        self.assertIn("def compare(", text)


if __name__ == "__main__":
    unittest.main()

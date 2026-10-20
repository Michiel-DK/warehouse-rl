"""Tests for S13A fleet/adapters/moroop.py (MoRoOp -> fleet-state messages).
Always run (plain dicts, no pyarrow, no data): a hand-made 20-row frame through the adapter, parse_line, Detector and
timebudget.robot_budget; the one-per-second collapse; the driving thresholds; cell_of / cell_centre; the orderId gap rule
and charging -> ""; the pyarrow-free import. Data tests run only when fleet/data/moroop/raw exists and pyarrow imports:
one real shift parses with zero rejects and the Detector, and the cleaned row count equals paper Table 7.
Each case names its red demonstration in an `# inject:` comment."""
import importlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "fleet", ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import timebudget as tb  # noqa: E402
from adapters import moroop as mo  # noqa: E402
from fleet_analyser.detector import Detector  # noqa: E402
from fleet_analyser.parse import parse_line  # noqa: E402

RAW = ROOT / "fleet" / "data" / "moroop" / "raw"
try:
    import pyarrow  # noqa: F401
    HAVE_PYARROW = True
except ImportError:
    HAVE_PYARROW = False
HAVE_DATA = RAW.is_dir() and (RAW / "data").is_dir() and HAVE_PYARROW

T0 = 1_785_132_000  # whole second, arbitrary
US = 1_000_000


def row(k, dt_us=0, x=0.2, y=0.2, vx=0.0, vy=0.0, om=0.0, state="Idle", mode="Autonomous", reason="None", charging=False):
    return dict(id=k, created_at=(T0 + k) * US + dt_us, operating_mode=mode, state=state, stuck_reason=reason, pos_x=x,
                pos_y=y, pos_theta=0.5, velocity_x=vx, velocity_y=vy, velocity_omega=om, is_robot_charging=charging,
                current_position_id=136, diagnostics='{"statuses": []}')


def op(oid, job, s, f, goal="warehouse", reason="NONE"):
    return dict(id=oid, job_id=job, start_time=None if s is None else (T0 + s) * US,
                finish_time=None if f is None else (T0 + f) * US, payload=json.dumps({"goal": goal}),
                termination_reason=reason)


def job(jid, jtype):
    return dict(id=jid, payload=json.dumps({"job_type": jtype}))


def frame20():
    """20 native rows over seconds 0..17; seconds 5 and 9 each hold two rows (the later one must win)."""
    rows = []
    for sec in range(18):
        moving = 3 <= sec < 8
        r = row(len(rows) + 1, 0, x=0.2 + 0.1 * sec, vx=0.3 if moving else 0.0, state="Navigating" if moving else "Idle")
        r["created_at"] = (T0 + sec) * US
        rows.append(r)
    late5 = row(len(rows) + 1, 0, x=9.9, vx=0.3, state="Navigating")
    late5["created_at"] = (T0 + 5) * US + 400_000
    late9 = row(len(rows) + 2, 0, x=7.7)
    late9["created_at"] = (T0 + 9) * US + 900_000
    return rows + [late5, late9]


class PureTests(unittest.TestCase):
    def test_imports_without_pyarrow(self):
        # inject: add `import pyarrow` at module top of moroop.py -> the subprocess exits 1 with ModuleNotFoundError
        code = ("import sys; sys.modules['pyarrow'] = None; sys.path.insert(0, %r); "
                "from adapters import moroop; print(moroop.cell_of(-0.01))" % str(ROOT / "fleet"))
        r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "-1")

    def test_frame20_parses_and_feeds_timebudget(self):
        # inject: emit an x as a float (drop math.floor) -> parse_line rejects with "type"
        rows = frame20()
        self.assertEqual(len(rows), 20)
        jobs = [job("J1", "kit supply")]
        ops = [op("o1", "J1", 2, 12)]
        msgs, aux, stats = mo.convert_shift(rows, ops, jobs)
        self.assertEqual(stats["native_rows"], 20)
        self.assertEqual(stats["kept_rows"], 18)
        self.assertEqual(stats["rows_collapsed"], 2)
        parsed = []
        for m in msgs:
            p, why = parse_line(mo.encode_line(m))
            self.assertIsNone(why)
            parsed.append(p)
        self.assertEqual([m["headerId"] for m in msgs], list(range(1, 19)))
        self.assertTrue(all(p.zone == "" and p.serial == "moroop-amr-1" for p in parsed))
        det = Detector()
        for p in parsed:
            det.feed(p)
        det.end_all()
        kept = tb.kept_messages(parsed)
        stations, near, _ = tb.cell_sets([], [])
        rec, _ = tb.robot_budget(kept, stations, near, 3600)
        self.assertEqual(sum(rec["seconds"].values()), rec["span_s"])
        self.assertEqual(rec["span_s"], 17)
        buckets = mo.second_buckets(kept, stations, near, tb)
        self.assertEqual(len(buckets), 17)
        self.assertEqual({b: buckets.count(b) for b in tb.BUCKETS if buckets.count(b)},
                         {b: s for b, s in rec["seconds"].items() if s})

    def test_two_rows_in_one_second_keep_the_last(self):
        # inject: keep the first row of a second -> the x of the kept row is 0.2 + 0.1 * 5 instead of 9.9
        msgs, aux, stats = mo.convert_shift(frame20(), [], [])
        sec5 = [m for m in msgs if m["timestamp"] == mo.iso(T0 + 5)]
        self.assertEqual(len(sec5), 1)
        self.assertEqual(sec5[0]["agvPosition"]["x"], mo.cell_of(9.9))
        self.assertEqual(stats["rows_collapsed"], 2)

    def test_collapsed_rows_with_stuck_reason_counted(self):
        # inject: count kept instead of dropped rows -> 0
        rows = [row(1, 0), row(2, 300_000, reason="ObstacleInTheWay"), row(3, 900_000)]
        rows[0]["created_at"] = T0 * US
        rows[1]["created_at"] = T0 * US + 300_000
        rows[2]["created_at"] = T0 * US + 900_000
        rows.append(row(4, 0))
        _, _, stats = mo.convert_shift(rows, [], [])
        self.assertEqual(stats["rows_collapsed"], 2)
        self.assertEqual(stats["collapsed_rows_with_stuck_reason"], 1)

    def test_driving_thresholds(self):
        # inject: use >= instead of > or == "Navigating" -> the 0.04 case or the boundary case flips
        self.assertFalse(mo.is_driving(row(1, vx=0.04)))
        self.assertTrue(mo.is_driving(row(1, vx=0.06)))
        self.assertTrue(mo.is_driving(row(1, om=0.06)))
        self.assertTrue(mo.is_driving(row(1, vx=0.04, vy=0.04)))  # hypot 0.0566
        self.assertFalse(mo.is_driving(row(1, vx=0.05)))  # strict
        self.assertFalse(mo.is_driving(row(1, state="Navigating")))  # state is never consulted
        self.assertTrue(mo.omega_only(row(1, om=0.06)))
        self.assertFalse(mo.omega_only(row(1, vx=0.06, om=0.06)))

    def test_paused_rule(self):
        # inject: drop the operating_mode clause -> Joystick rows stay unpaused
        self.assertTrue(mo.is_paused(row(1, state="Paused")))
        self.assertTrue(mo.is_paused(row(1, mode="Joystick")))
        self.assertFalse(mo.is_paused(row(1, state="Navigating")))

    def test_cell_of_and_centre_round_trip(self):
        # inject: replace math.floor by int() -> -0.01 maps to 0 and -1.84 to -3
        self.assertEqual(mo.cell_of(-0.01), -1)
        self.assertEqual(mo.cell_of(0.0), 0)
        self.assertEqual(mo.cell_of(-1.84), -4)
        for v in (-1.84, -0.01, 0.0, 0.24, 0.5, 8.24):
            i = mo.cell_of(v)
            self.assertEqual(mo.cell_of(mo.cell_centre(i)), i)
            self.assertLessEqual(abs(mo.cell_centre(i) - v), 0.25 + 1e-9)

    def test_order_id_gap_rule_and_charging(self):
        # inject: drop the same-job gap branch -> second 5 has orderId ""; drop the charging test -> second 14 is "C1"
        rows = [row(k, 0) for k in range(1, 18)]
        for r in rows:
            r["created_at"] = (T0 + r["id"]) * US + 500_000
        jobs = [job("J1", "kit supply"), job("J2", "kit supply"), job("C1", "charging")]
        ops = [op("a", "J1", 1, 4), op("b", "J1", 5, 8), op("c", "J2", 9, 12), op("d", "C1", 13, 16), op("n", "J2", None, 3)]
        ops[1]["start_time"] = (T0 + 5) * US + 800_000  # 1 s gap between a and b of one job
        msgs, aux, stats = mo.convert_shift(rows, ops, jobs)
        by_sec = {m["timestamp"]: m["orderId"] for m in msgs}
        at = lambda s: by_sec[mo.iso(T0 + s)]  # noqa: E731
        self.assertEqual(at(2), "J1")
        self.assertEqual(at(5), "J1")  # gap between a (finish 4) and b (start 5.8): same job
        self.assertEqual(at(9), "J2")  # c starts at 9.0 s, the row is at 9.5 -> running
        self.assertEqual(at(8), "")  # between b (finish 8.0) and c (start 9.0): jobs differ -> ""
        self.assertEqual(at(14), "")  # charging job
        self.assertTrue(aux[13]["charging_job"])
        self.assertEqual(stats["order_source_rows"].get("charging"), 3)
        self.assertEqual(stats["operations_without_start_or_finish"], 1)

    def test_overlap_takes_latest_start_and_is_counted(self):
        # inject: take the earliest start -> orderId "A" and overlap_seconds 0
        rows = [row(k, 0) for k in range(1, 6)]
        for r in rows:
            r["created_at"] = (T0 + r["id"]) * US
        ops = [op("a", "A", 0, 10), op("b", "B", 2, 10)]
        msgs, aux, stats = mo.convert_shift(rows, ops, [job("A", "kit supply"), job("B", "kit supply")])
        self.assertEqual([m["orderId"] for m in msgs], ["A", "B", "B", "B", "B"])
        self.assertEqual(stats["overlap_rows"], 4)
        self.assertEqual(stats["overlap_seconds"], 3)

    def test_message_key_order(self):
        # inject: add a "cell" key or reorder -> the list differs
        msgs, _, _ = mo.convert_shift(frame20(), [], [])
        self.assertEqual(list(msgs[0]), ["headerId", "timestamp", "manufacturer", "serialNumber", "orderId", "agvPosition",
                                        "driving", "paused", "errors", "loads"])
        self.assertEqual(list(msgs[0]["agvPosition"]), ["x", "y", "theta"])
        self.assertEqual((msgs[0]["errors"], msgs[0]["loads"]), ([], []))

    def test_stations_share_rule(self):
        # inject: threshold 0.0 -> the 4 % cell joins the station set
        rows = []
        for i in range(100):
            r = row(i, 0, x=1.2 if i < 96 else 4.2)
            r["current_position_id"] = 137
            rows.append(r)
        st, stats = mo.derive_stations([rows])
        self.assertEqual(st, {"stations": [[2, 0]], "shelves": []})
        self.assertAlmostEqual(stats["outside_station_idle_share"], 0.04)

    def test_label_comparison_hits_and_false_alarm(self):
        # inject: window without the +30 s tail -> the hit becomes a miss
        n = 200
        native = []
        for k in range(n):
            driving = not (20 <= k < 120)
            r = row(k, 0, vx=0.3 if driving else 0.0, state="Navigating" if driving else "Idle",
                    reason="ObstacleInTheWay" if 20 <= k < 70 else "None")
            r["created_at"] = (T0 + k) * US
            native.append(r)
        ops = [op("o", "J", 0, n)]
        msgs, aux, _ = mo.convert_shift(native, ops, [job("J", "kit supply")])
        parsed = [parse_line(mo.encode_line(m))[0] for m in msgs]
        kept = tb.kept_messages(parsed)
        stations, near, _ = tb.cell_sets([], [])
        buckets = mo.second_buckets(kept, stations, near, tb)
        lab = mo.label_comparison(native, kept, buckets, ops, stations, tb)
        self.assertEqual(lab["episodes_ge_30s"], dict(count=1, hits=1, misses=0, list=lab["episodes_ge_30s"]["list"]))
        self.assertEqual(lab["label_seconds"], 50)
        self.assertEqual(lab["label_seconds_per_bucket"]["stuck"], 50)
        self.assertEqual(lab["false_alarms"]["count"], 0)  # one run 20..120, label episode inside +-30 s
        # a second stuck run far from any label is a false alarm
        for k in range(150, 190):
            native[k].update(velocity_x=0.0, state="Idle")
        msgs, aux, _ = mo.convert_shift(native, ops, [job("J", "kit supply")])
        kept = tb.kept_messages([parse_line(mo.encode_line(m))[0] for m in msgs])
        buckets = mo.second_buckets(kept, stations, near, tb)
        lab = mo.label_comparison(native, kept, buckets, ops, stations, tb)
        self.assertEqual(lab["stuck_runs"], 2)
        self.assertEqual(lab["false_alarms"]["count"], 1)


@unittest.skipUnless(HAVE_DATA, "fleet/data/moroop/raw or pyarrow missing")
class DataTests(unittest.TestCase):
    NAME = "2026_07_27_morning"
    TABLE7_CLEANED = 15194

    @classmethod
    def setUpClass(cls):
        cls.d = mo.load_shift(RAW, cls.NAME)
        cls.msgs, cls.aux, cls.stats = mo.convert_shift(cls.d["robot_state_cleaned"], cls.d["operations"], cls.d["jobs"])

    def test_table7_row_count(self):
        # inject: load robot_state_raw instead of cleaned -> 15549
        self.assertEqual(len(self.d["robot_state_cleaned"]), self.TABLE7_CLEANED)
        self.assertEqual(self.stats["native_rows"], self.TABLE7_CLEANED)
        self.assertEqual(self.stats["label_rows"], 37)
        self.assertEqual(self.stats["timeout_operations"], 0)

    def test_every_message_parses_and_feeds_detector(self):
        # inject: emit a float x -> rejects > 0
        det = Detector()
        parsed = []
        for m in self.msgs:
            p, why = parse_line(mo.encode_line(m))
            self.assertIsNone(why)
            parsed.append(p)
        for p in parsed:
            det.feed(p)
        det.end_all()
        self.assertEqual(len(parsed), self.stats["kept_rows"])
        ts = [p.ts for p in parsed]
        self.assertEqual(ts, sorted(set(ts)))

    def test_bucket_sum_equals_span_on_real_shift(self):
        # inject: drop one second from second_buckets -> counts differ from robot_budget
        parsed = [parse_line(mo.encode_line(m))[0] for m in self.msgs]
        kept = tb.kept_messages(parsed)
        stations, near, _ = tb.cell_sets([[0, -4], [2, 0], [9, -3], [15, 0]], [])
        rec, _ = tb.robot_budget(kept, stations, near, 3600)
        buckets = mo.second_buckets(kept, stations, near, tb)
        self.assertEqual(sum(rec["seconds"].values()), rec["span_s"])
        self.assertEqual({b: buckets.count(b) for b in tb.BUCKETS}, rec["seconds"])


if __name__ == "__main__":
    unittest.main()

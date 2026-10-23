"""Tests for S16A: adapter --faults (diagnostics Error statuses -> VDA 5050 errors -> faulted) and fleet/moroop_faults.py.
Always run (plain dicts, no pyarrow, no data, nothing skipped). One synthetic raw shift: five 60 s stopped-with-job segments
(a) wheel status at Error, (b) /Devices/Camera 'Frequency too high.' at Warning, (c) a Stale status, (d) the same Camera
text at Error, (e) an unclassified Warning, separated by driving rows; one Error status sits in a driving row.
Each case names its red demonstration in an `# inject:` comment."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "fleet", ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import moroop_faults as mf  # noqa: E402
import timebudget as tb  # noqa: E402
from adapters import moroop as mo  # noqa: E402
from fleet_analyser.detector import Detector  # noqa: E402
from fleet_analyser.parse import parse_line  # noqa: E402

T0 = 1_785_132_000
US = 1_000_000
WHEEL = ("/Wheels/FL", "Lidar: Calibrating")
CAMERA = ("/Devices/Camera", "Frequency too high.")
STALE = ("/Wheels/BL", "Missing data")
OTHER = ("/Localization", "Warning")
DRIVE_ERR = ("/Wheels/FR", "Power Input: Not Charging.")
SEGMENTS = (("a", "Error", WHEEL), ("b", "Warning", CAMERA), ("c", "Stale", STALE), ("d", "Error", CAMERA),
            ("e", "Warning", OTHER))
SEG_LEN, GAP = 60, 10


def status(name, message, level):
    return {"hardwareId": "", "name": name, "level": level, "message": message, "values": {}}


def diag(*sts):
    # an Ok status in every row, as in the real log
    return json.dumps({"statuses": [status("/Devices", "OK", "Ok")] + [status(*s) for s in sts]})


def row(k, vx, diagnostics, mode="Autonomous"):
    return dict(id=k + 1, created_at=(T0 + k) * US, operating_mode=mode, state="Idle", stuck_reason="None", pos_x=0.2,
                pos_y=0.2, pos_theta=0.5, velocity_x=vx, velocity_y=0.0, velocity_omega=0.0, is_robot_charging=False,
                current_position_id=136, diagnostics=diagnostics, robot_uptime=1000.0 + k)


def synthetic(desc_len=None, paused_first=0):
    """(rows, starts): rows over seconds 0..; starts[letter] = first stopped second of the segment."""
    rows, starts, k = [], {}, 0
    for letter, level, (name, message) in SEGMENTS:
        for j in range(GAP):
            drv = diag((DRIVE_ERR[0], DRIVE_ERR[1], "Error")) if (k == 3 and letter == "a") else diag()
            rows.append(row(k, 0.3, drv))
            k += 1
        starts[letter] = k
        msg = message if not (desc_len and letter == "a") else "x" * desc_len
        for j in range(SEG_LEN):
            mode = "Joystick" if (letter == "a" and j < paused_first) else "Autonomous"
            rows.append(row(k, 0.0, diag((name, msg, level)), mode))
            k += 1
    for j in range(GAP):
        rows.append(row(k, 0.3, diag()))
        k += 1
    return rows, starts


OPS = [dict(id="o", job_id="J", start_time=T0 * US, finish_time=(T0 + 1000) * US, payload="{}", termination_reason="NONE")]
JOBS = [dict(id="J", payload=json.dumps({"job_type": "kit supply"}))]


def messages(faults, **kw):
    rows, starts = synthetic(**kw)
    msgs, aux, stats = mo.convert_shift(rows, OPS, JOBS, faults=faults)
    return rows, starts, msgs, stats


def segment(msgs, starts, letter):
    t = mo.iso(T0 + starts[letter])
    t2 = mo.iso(T0 + starts[letter] + SEG_LEN)
    return [m for m in msgs if t <= m["timestamp"] < t2]


def episodes_of(msgs):
    parsed = [parse_line(mo.encode_line(m))[0] for m in msgs]
    kept = tb.kept_messages(parsed)
    return [dict(shift=0, start=e["start"], duration_s=e["duration_s"], cause=e["cause"] or "unknown",
                 resolution=e.get("resolution")) for e in tb.recompute_episodes(kept)]


class AdapterFaultsTests(unittest.TestCase):
    def test_error_status_is_a_fatal_error_and_parse_says_faulted(self):
        # inject: map level 'Warning' too (is_qualifying_error uses != 'Ok') -> (b) and (e) gain errors
        rows, starts, msgs, stats = messages(True)
        for letter in ("a", "d"):
            name, message = dict((l, m) for l, _, m in SEGMENTS)[letter]
            seg = segment(msgs, starts, letter)
            self.assertEqual(len(seg), SEG_LEN)
            for m in seg:
                self.assertEqual(m["errors"], [{"errorType": name, "errorLevel": "FATAL", "errorDescription": message[:120]}])
                p, why = parse_line(mo.encode_line(m))
                self.assertIsNone(why)
                self.assertTrue(p.faulted)
        for letter in ("b", "c", "e"):
            for m in segment(msgs, starts, letter):
                self.assertEqual(m["errors"], [])
                self.assertFalse(parse_line(mo.encode_line(m))[0].faulted)
        self.assertEqual(stats["diagnostics"]["faulted"]["kept_messages"], 2 * SEG_LEN + 1)
        self.assertEqual(stats["diagnostics"]["faulted"]["seconds"], 2 * SEG_LEN + 1)

    def test_detector_files_a_as_faulted_self_and_the_rest_as_stalls(self):
        # inject: leave errors [] in the faults branch -> (a) is cause unknown
        rows, starts, msgs, _ = messages(True)
        by_start = {e["start"]: e for e in episodes_of(msgs)}
        self.assertEqual(len(by_start), 5)
        cause = {l: by_start[T0 + starts[l]]["cause"] for l in "abcde"}
        self.assertEqual(cause, {"a": "faulted_self", "b": "unknown", "c": "unknown", "d": "faulted_self", "e": "unknown"})
        for l in "abcde":
            self.assertEqual(by_start[T0 + starts[l]]["duration_s"], SEG_LEN)

    def test_description_truncated_to_120(self):
        # inject: drop the [:120] -> the description keeps 150 characters
        _, starts, msgs, _ = messages(True, desc_len=150)
        d = segment(msgs, starts, "a")[0]["errors"][0]["errorDescription"]
        self.assertEqual(d, "x" * 120)

    def test_faults_off_is_the_current_adapter(self):
        # inject: let convert_shift fill errors regardless of the flag -> a faulted message appears with faults=False
        rows, starts, off, stats_off = messages(False)
        _, _, on, stats_on = messages(True)
        self.assertTrue(all(m["errors"] == [] for m in off))
        self.assertEqual(stats_off["diagnostics"]["faulted"], "not computed")
        self.assertEqual(stats_off["errors"], "[] (diagnostics levels tabulated only)")
        self.assertNotIn("kept_messages", json.dumps(stats_off))
        blanked = [dict(m, errors=[]) for m in on]
        self.assertEqual([mo.encode_line(m) for m in off], [mo.encode_line(m) for m in blanked])
        self.assertEqual(list(off[0]), ["headerId", "timestamp", "manufacturer", "serialNumber", "orderId", "agvPosition",
                                        "driving", "paused", "errors", "loads"])
        # the default call (no kwarg) is the faults=False call
        d_msgs, _, d_stats = mo.convert_shift(rows, OPS, JOBS)
        self.assertEqual([mo.encode_line(m) for m in d_msgs], [mo.encode_line(m) for m in off])
        self.assertEqual(d_stats, stats_off)
        # mapping and deviations are the S13A text unless --faults
        self.assertIs(mo.mapping_for(False), mo.MAPPING)
        self.assertIs(mo.deviations_for(False), mo.DEVIATIONS)
        self.assertEqual(next(m for m in mo.MAPPING if m["field"] == "faulted")["rule"], "'not computed' in S13A")
        self.assertNotEqual(next(m for m in mo.mapping_for(True) if m["field"] == "faulted")["rule"], "'not computed' in S13A")

    def test_unparseable_diagnostics_gives_no_error_and_is_counted(self):
        # inject: raise or treat unparseable as faulted -> the call errors or errors is non-empty
        rows, _ = synthetic()
        rows[5]["diagnostics"] = "not json"
        rows[6]["diagnostics"] = None
        msgs, _, stats = mo.convert_shift(rows, OPS, JOBS, faults=True)
        self.assertEqual(msgs[5]["errors"], [])
        self.assertEqual(msgs[6]["errors"], [])
        self.assertEqual(stats["diagnostics"]["faulted"]["kept_messages_unparseable_diagnostics"], 2)


class ReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.starts = synthetic()
        cls.recs = {0: mf.shift_records(cls.rows)}
        _, _, cls.msgs, _ = messages(True)
        cls.eps = episodes_of(cls.msgs)

    def test_table_c_classes(self):
        # inject: classify by name only, or call every Warning 'noise' -> (e) or (d) lands in the wrong class
        rows = {(r["level"], r["name"], r["message"]): r for r in mf.table_c(self.recs)}
        self.assertEqual(rows[("Warning",) + CAMERA]["class"], "noise")
        self.assertEqual(rows[("Warning",) + CAMERA]["source"], mf.NOISE_SOURCE)
        self.assertEqual(rows[("Error",) + WHEEL]["class"], "faulted by our rule")
        self.assertEqual(rows[("Error",) + CAMERA]["class"], "faulted by our rule")
        self.assertEqual(rows[("Stale",) + STALE]["class"], "unclassified")
        self.assertEqual(rows[("Warning",) + OTHER]["class"], "unclassified")
        self.assertEqual([k for k, r in rows.items() if r["class"] == "noise"], [("Warning",) + CAMERA])
        for k, r in rows.items():
            if k != ("Warning",) + CAMERA:
                self.assertNotIn("noise", json.dumps(r))
        self.assertTrue(all(k[0] != "Ok" for k in rows))
        self.assertEqual(rows[("Warning",) + CAMERA]["status_rows"], SEG_LEN)
        self.assertEqual(rows[("Warning",) + CAMERA]["first_onset"]["robot_uptime"], 1000.0 + self.starts["b"])

    def test_table_a_driving_split_and_family_share(self):
        # inject: count only the stopped rows (drop the driving test) -> driving_s 0 and the family never refutes
        a = mf.table_a(self.recs)
        p = a["pooled"]
        self.assertEqual(p["faulted_s"], 2 * SEG_LEN + 1)
        self.assertEqual(p["faulted_driving_s"], 1)
        self.assertEqual(p["faulted_not_driving_s"], 2 * SEG_LEN)
        fam = {(f["name"], f["message"]): f for f in p["families"]}
        self.assertGreater(fam[DRIVE_ERR]["driving_share"], 0)
        self.assertEqual(fam[DRIVE_ERR]["driving_share"], 1.0)
        self.assertTrue(fam[DRIVE_ERR]["refutes_error_equals_stopped"])
        self.assertFalse(fam[WHEEL]["refutes_error_equals_stopped"])
        self.assertEqual(fam[WHEEL]["faulted_s"], SEG_LEN)
        self.assertEqual(a["per_shift"]["0"]["faulted_driving_s"], 1)
        self.assertEqual(a["label"], "Robot reported a component error")

    def test_table_b_lists_the_status_against_its_episode(self):
        # inject: match statuses by episode start only (one second) -> seconds 1 instead of 60
        b = {r["start"]: r for r in mf.episode_rows(self.eps, self.recs)}
        a = b[mo.iso(T0 + self.starts["a"])]
        self.assertEqual(a["duration_s"], SEG_LEN)
        self.assertEqual(a["statuses"], [dict(name=WHEEL[0], message=WHEEL[1], seconds=SEG_LEN, paused_seconds=0)])
        self.assertEqual(a["faulted_share"], 1.0)
        self.assertEqual(a["public_label"], "Robot reported a component error")
        for l in "bce":
            r = b[mo.iso(T0 + self.starts[l])]
            self.assertEqual((r["statuses"], r["faulted_overlap_s"], r["public_label"]), ([], 0, None))

    def test_table_b_counts_faulted_and_paused_seconds_as_paused(self):
        # inject: count the paused seconds as faulted too -> faulted_s 60 and paused_seconds 0
        rows, starts = synthetic(paused_first=20)
        recs = {0: mf.shift_records(rows)}
        a = [r for r in mf.episode_rows(self.eps, recs) if r["start"] == mo.iso(T0 + starts["a"])][0]
        self.assertEqual(a["faulted_paused_s"], 20)
        self.assertEqual(a["faulted_s"], 40)
        self.assertEqual(a["faulted_overlap_s"], 60)
        self.assertEqual(a["statuses"], [dict(name=WHEEL[0], message=WHEEL[1], seconds=40, paused_seconds=20)])
        self.assertAlmostEqual(a["faulted_share"], 40 / 60)

    def test_verdict_words_and_boundaries(self):
        # inject: use > for the 50 % test or >= for the 20 % test -> a boundary case flips
        v = mf.verdict
        self.assertEqual(v([90, 90], [180, 180], 20, 100), "fault cause")  # exactly 50 % and exactly 20 %
        self.assertEqual(v([89, 90], [180, 180], 20, 100), "mixed")
        self.assertEqual(v([90, 90], [180, 180], 21, 100), "mixed")
        self.assertEqual(v([0, 0], [47, 133], 0, 585), "unknown stays unknown")
        self.assertEqual(v([0, 1], [47, 133], 58, 585), "mixed")
        self.assertEqual(v([180, 180], [180, 180], 0, 585), "fault cause")
        self.assertEqual(v([], [], 0, 0), "mixed")
        self.assertEqual(set(mf.VERDICTS), {"fault cause", "unknown stays unknown", "mixed"})

    def test_reproduces_checks_the_label_aggregate(self):
        # inject: ignore the seconds -> the 181 s case passes
        eps = [dict(cause="unknown", duration_s=47), dict(cause="unknown", duration_s=133)]
        ok = [dict(cause="unknown", episodes=2, seconds=180)]
        self.assertIsNone(mf.reproduces(eps, ok))
        self.assertIsNotNone(mf.reproduces(eps, [dict(cause="unknown", episodes=2, seconds=181)]))

    def test_report_is_deterministic_and_has_the_top_level_verdict(self):
        # inject: add a wall-clock stamp or iterate a set -> the two dumps differ
        def run():
            recs = {0: mf.shift_records(self.rows)}
            rep = mf.build_report(recs, self.eps, self.eps, mf.cross_check(2 * SEG_LEN + 1, {0: 2 * SEG_LEN}), True)
            return json.dumps(rep, sort_keys=True, indent=1)
        first, second = run(), run()
        self.assertEqual(first, second)
        rep = json.loads(first)
        self.assertIn(rep["verdict"], mf.VERDICTS)
        self.assertEqual(rep["verdict_sentence"], "n = 2: a description, not a rate")
        self.assertEqual(rep["cross_check"]["difference"], 1)
        self.assertEqual(rep["robot_uptime_column"], "present")
        self.assertEqual(sum(1 for r in rep["table_c"] if r["class"] == "noise"), 1)


if __name__ == "__main__":
    unittest.main()

"""Tests for S16B fleet/moroop_dispatch.py on synthetic in-memory tables (times are seconds after BASE; the smoke test alone
reads the real raw parquet and skips only when pyarrow or the raw directory is missing; CI has neither).

Synthetic shift of cases 1 and 2: one stuck episode at +1000 s lasting 100 s ([1000, 1100)); each case names the mutant it
kills in an `# inject:` comment."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "fleet", ROOT / "src", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import moroop_dispatch as md  # noqa: E402

try:
    import pyarrow  # noqa: F401
    HAVE_PYARROW = True
except ImportError:
    HAVE_PYARROW = False

BASE = 1767225600
RAW_DIR = Path(os.environ.get("WR_MOROOP_RAW", str(md.DEFAULT_RAW)))
SCRIPT = str(ROOT / "fleet" / "moroop_dispatch.py")
LABEL = ROOT / "results" / "fleet" / "moroop_label-sb.json"


def us(t):
    return (BASE + t) * 1_000_000


def iso(t):
    return md.moroop.iso(BASE + t)


def episode(start, dur, lst="false_alarms"):
    return dict(list=lst, start=iso(start), duration_s=dur, start_us=us(start), end_us=us(start + dur))


_ID = [0]


def ev(t, kind, op=None, meta=None):
    _ID[0] += 1
    return dict(id=f"e{_ID[0]}", created_at=us(t), event_type=kind, operation_id=op,
                changes="[]", meta_data=json.dumps(meta or {}))


def denied(t, op, n, mx=5):
    return ev(t, "operation_start_denied", op, dict(retry_count=n, max_retries=mx, cooldown_seconds=1))


def state_row(i, t, state="Idle", mode="Autonomous"):
    return dict(id=i, created_at=us(t), state=state, operating_mode=mode)


def raw_row(i, t, **kw):
    r = dict(id=i, created_at=us(t) + 500_000, operating_mode="Autonomous", state="Navigating", stuck_reason="None",
             pos_x=1.0, pos_y=-1.0, pos_theta=0.5, velocity_x=0.2, velocity_y=0.0, velocity_omega=0.0,
             is_robot_charging=False, diagnostics=json.dumps({"statuses": [dict(name="/a", level="Ok")]}))
    r.update(kw)
    return r


def tables(events, cleaned=(), raw=(), operations=()):
    return dict(dispatch_events=list(events), robot_state_cleaned=list(cleaned), robot_state_raw=list(raw),
                operations=list(operations), jobs=[])


def by_kind(res):
    return {e["kind"].replace("operation_", ""): e for e in res["events"]}


class ClassTests(unittest.TestCase):
    def setUp(self):
        self.eps = [episode(1000, 100)]
        events = [
            ev(20, "operation_dispatcher_resumed"),  # before the first operation_started
            ev(100, "operation_started", "op1"),
            ev(1030, "operation_dispatcher_resumed"),
            denied(5000, "opA", 1),
        ] + [denied(1040 + n, "opB", n + 1) for n in range(5)] + [ev(1045, "operation_dispatcher_paused")]
        cleaned = [state_row(1, 10), state_row(2, 1020, state="Paused")]
        self.res = md.analyse_shift("s", tables(events, cleaned, operations=[dict(id="opA", job_id="jobA")]), self.eps)
        self.events = self.res["events"]

    def test_classes_exact(self):
        # inject: drop the "shift start" branch -> the t=20 resume becomes "external call"; drop the auto-pause branch
        # -> the t=1045 pause becomes "external call" and an intervention
        got = [(e["ts_us"] // 1_000_000 - BASE, e["kind"].replace("operation_", ""), e["cls"], e["intervention"])
               for e in self.events]
        self.assertEqual(got, [
            (20, "dispatcher_resumed", "shift start", False),
            (1030, "dispatcher_resumed", "external call", True),
            (1040, "start_denied", "dispatcher refused", False),
            (1041, "start_denied", "dispatcher refused", False),
            (1042, "start_denied", "dispatcher refused", False),
            (1043, "start_denied", "dispatcher refused", False),
            (1044, "start_denied", "dispatcher refused", False),
            (1045, "dispatcher_paused", "dispatcher refused", False),
            (5000, "start_denied", "dispatcher refused", False)])
        self.assertEqual(self.res["classes"], {"dispatcher refused": 7, "external call": 1, "shift start": 1})
        self.assertEqual((self.res["interventions"], self.res["auto_pauses"]), (1, 1))

    def test_episode_fields(self):
        resume = self.events[1]
        self.assertEqual(resume["in_episode"], dict(list="false_alarms", start=iso(1000), duration_s=100, delta_s=30.0))
        self.assertIsNone(resume["near_before"])
        self.assertIsNone(resume["near_after"])
        self.assertEqual((resume["offset_s"], resume["pause_precedes"]), (1020.0, False))
        shift_start = self.events[0]
        self.assertEqual((shift_start["offset_s"], shift_start["pause_precedes"]), (10.0, False))
        far = self.events[-1]
        self.assertEqual((far["job_id"], far["operation_id"], far["retry_count"], far["max_retries"]),
                         ("jobA", "opA", 1, 5))
        self.assertIsNone(far["in_episode"] or far["near_before"] or far["near_after"])
        self.assertEqual(self.res["shift_start"], iso(10))
        self.assertEqual(self.res["first_operation_started"], iso(100))

    def test_per_kind_table_exact(self):
        # inject: count a near-only event as overlap, or read the nearest state row AFTER the event
        zero = dict(count=0, overlap_episode=0, near_episode=0, in_paused_or_non_autonomous=0, no_row_before=0)
        self.assertEqual(self.res["per_kind"], {
            "operation_start_denied": dict(count=6, overlap_episode=5, near_episode=0, in_paused_or_non_autonomous=6,
                                           no_row_before=0),
            "operation_dispatcher_paused": dict(count=1, overlap_episode=1, near_episode=0,
                                                in_paused_or_non_autonomous=1, no_row_before=0),
            "operation_dispatcher_resumed": dict(count=2, overlap_episode=1, near_episode=0,
                                                 in_paused_or_non_autonomous=1, no_row_before=0),
            "operation_dispatcher_started": zero, "operation_dispatcher_stopped": zero, "operation_failed": zero})

    def test_resume_without_pause_precedes_and_after_pause(self):
        events = [ev(0, "operation_started", "o"), ev(10, "operation_dispatcher_paused"),
                  ev(20, "operation_dispatcher_resumed"), ev(30, "operation_dispatcher_resumed")]
        res = md.analyse_shift("s", tables(events, [state_row(1, 0)]), [])
        self.assertEqual([(e["kind"][21:], e["pause_precedes"]) for e in res["events"] if "offset_s" in e],
                         [("resumed", True), ("resumed", False)])


class NearTests(unittest.TestCase):
    def test_near_before_after_and_outside(self):
        # inject: make the window 121 s, or collapse near_before and near_after into one column
        eps = [episode(1000, 100)]
        events = [ev(0, "operation_started", "o"), ev(940, "operation_dispatcher_paused"),
                  ev(1160, "operation_dispatcher_paused"), ev(1221, "operation_dispatcher_paused"),
                  ev(1220, "operation_dispatcher_paused")]
        res = md.analyse_shift("s", tables(events, [state_row(1, 0)]), eps)
        got = {e["ts_us"] // 1_000_000 - BASE: (e["near_before"] and e["near_before"]["delta_s"],
                                                 e["near_after"] and e["near_after"]["delta_s"],
                                                 e["in_episode"], e["intervention"]) for e in res["events"]
               if e["kind"].endswith("paused")}
        self.assertEqual(got, {940: (60.0, None, None, True), 1160: (None, 60.0, None, True),
                               1220: (None, 120.0, None, True), 1221: (None, None, None, False)})
        self.assertEqual(res["per_kind"]["operation_dispatcher_paused"]["near_episode"], 3)
        self.assertEqual(res["per_kind"]["operation_dispatcher_paused"]["overlap_episode"], 0)


def cleaning_fixture():
    """Raw ids 1-10 on distinct seconds, cleaned lacks 1, 2, 3. Rule drops: id 1 (pos_x None: conversion raises) and id 4
    (diagnostics unparseable, kept by the authors). Ids 5 and 6 share a second (5 is a collapse drop, kept, no rule drop)."""
    raw = [raw_row(i, i * 10, state="Idle" if i == 2 else "Navigating", pos_x=2.0 + i) for i in range(1, 11)]
    raw[0]["pos_x"] = None
    raw[3]["diagnostics"] = "not json"
    raw[5]["created_at"] = raw[4]["created_at"] + 100  # same second as id 5
    raw[1]["velocity_x"] = float("nan")  # id 2: authors-only, counted as non-finite in the range table
    raw[2]["velocity_x"] = 0.7
    cleaned = [dict(r) for r in raw if r["id"] not in (1, 2, 3)]
    return raw, cleaned


class CleaningTests(unittest.TestCase):
    def test_three_way_split_and_collapse_column(self):
        # inject: count collapse drops in ours_only, or compare rule drops over all rows instead of per id
        raw, cleaned = cleaning_fixture()
        c = md.clean_shift(raw, cleaned)
        self.assertEqual((c["raw_rows"], c["cleaned_rows"], c["authors_removed"], c["rule_drops"]), (10, 7, 3, 2))
        self.assertEqual((c["both_drop"]["ids"], c["authors_only"]["ids"], c["ours_only"]["ids"]), (1, 2, 1))
        self.assertEqual(c["rule_drop_reasons"], {"convert:TypeError": 1, "diagnostics_unparseable": 1})
        self.assertEqual(c["collapse_drops"], 1)
        self.assertEqual((c["both_drop"]["collapse_drops"], c["authors_only"]["collapse_drops"],
                          c["ours_only"]["collapse_drops"], c["collapse_drops_in_no_set"]), (0, 0, 0, 1))
        self.assertEqual(c["ours_only"]["diagnostics_max_level"], {"unparseable": 1})
        self.assertEqual(c["authors_only"]["state"], {"Idle": 1, "Navigating": 1})
        self.assertEqual(c["authors_only"]["ranges"]["pos_x"], dict(min=4.0, max=5.0, none_or_nonfinite=0))
        self.assertEqual(c["authors_only"]["ranges"]["velocity_x"], dict(min=0.7, max=0.7, none_or_nonfinite=1))
        self.assertEqual(c["cleaned_ids_not_in_raw"], 0)

    def test_pooled_sum(self):
        raw, cleaned = cleaning_fixture()
        c = md.clean_shift(raw, cleaned)
        p = md.pool_cleaning([c, c])
        self.assertEqual((p["raw_rows"], p["authors_removed"], p["both_drop"]["ids"], p["authors_only"]["ids"],
                          p["collapse_drops"]), (20, 6, 2, 4, 2))
        self.assertEqual(p["authors_only"]["ranges"]["velocity_x"], dict(min=0.7, max=0.7, none_or_nonfinite=2))


class VerdictTests(unittest.TestCase):
    def test_cleaning_boundaries(self):
        # inject: > instead of >= at 0.90, or >= instead of > at 0.10
        self.assertEqual(md.cleaning_verdict(9, 1, 10), "match")
        self.assertEqual(md.cleaning_verdict(89, 11, 100), "we keep theirs")
        self.assertEqual(md.cleaning_verdict(0, 2959, 2959), "we keep theirs")
        self.assertEqual(md.cleaning_verdict(5, 1, 10), "mixed")  # 0.10 exactly is not "we keep theirs"
        self.assertEqual(md.cleaning_verdict(5, 2, 10), "we keep theirs")
        self.assertEqual(md.cleaning_verdict(0, 0, 0), "mixed")

    def test_page_sentence(self):
        self.assertEqual(md.page_sentence(2959, 140386),
                         "No row of the authors' cleaned table was rejected by our parser; the authors had already "
                         "removed 2,959 of 140,386 raw rows (2.1 %)")


def synthetic_label():
    shifts = {str(k): {l: dict(count=0, list=[]) for l in md.EPISODE_LISTS} for k in range(9)}
    shifts["6"]["false_alarms"]["list"].append(dict(start=md.INTERVENTION_START, duration_s=3245))
    shifts["1"]["episodes_ge_30s"]["list"].append(dict(start=iso(1000), duration_s=100))
    return dict(src=dict(shifts=list(md.moroop.SHIFTS)), shifts=shifts)


def synthetic_loader(resume_after_intervention_s):
    def load(raw, name):
        if name == md.INTERVENTION_SHIFT:
            t0 = md.epoch_of(md.INTERVENTION_START) - BASE
            events = [ev(t0 - 500, "operation_started", "o"), ev(t0 + 3245 + resume_after_intervention_s,
                                                                  "operation_dispatcher_resumed")]
        else:
            events = [ev(0, "operation_started", "o")]
        raw_rows, cleaned = cleaning_fixture()
        return tables(events, [state_row(1, 0)] + cleaned, raw_rows)
    return load


class RunTests(unittest.TestCase):
    def run_once(self, after):
        return md.analyse(synthetic_label(), "sha", "raw/dir", [1, 6], synthetic_loader(after), label_path="label.json")

    def test_determinism_byte_identical(self):
        # inject: a wall-clock value or a set-ordered list in the output
        a, b = md.dump(self.run_once(40)).encode(), md.dump(self.run_once(40)).encode()
        self.assertEqual(a, b)
        self.assertNotIn(str(ROOT), a.decode())

    def test_dispatcher_verdicts(self):
        r = self.run_once(40)
        self.assertEqual(r["verdicts"], dict(dispatcher="marks the intervention", cleaning="we keep theirs"))
        self.assertEqual((r["pooled"]["interventions"], r["intervention_episode_in_scope"]), (1, True))
        self.assertEqual(r["intervention_episode"], dict(shift=md.INTERVENTION_SHIFT, shift_index=6, list="false_alarms",
                                                         start=md.INTERVENTION_START, duration_s=3245))
        far = self.run_once(121)  # 121 s after the end: outside the window
        self.assertEqual(far["verdicts"]["dispatcher"], "adds nothing")
        self.assertEqual(far["pooled"]["interventions"], 0)

    def test_missing_intervention_episode_asserts(self):
        label = synthetic_label()
        label["shifts"]["6"]["false_alarms"]["list"] = []
        with self.assertRaises(AssertionError):
            md.find_intervention(label)

    def test_mixed_when_pause_near_other_episode_only(self):
        label = synthetic_label()
        events = [ev(0, "operation_started", "o"), ev(1050, "operation_dispatcher_paused")]
        res = md.analyse(label, "sha", "raw", [1, 6], lambda raw, name: tables(
            events if name == md.moroop.SHIFTS[1] else [ev(0, "operation_started", "o")], [state_row(1, 0)]),
            label_path="l")
        self.assertEqual(res["verdicts"]["dispatcher"], "mixed")


@unittest.skipUnless(HAVE_PYARROW and RAW_DIR.is_dir(), "needs pyarrow and the MoRoOp raw parquet (WR_MOROOP_RAW)")
class SmokeTest(unittest.TestCase):
    def test_smoke_shift_1(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out.json"
            subprocess.run([sys.executable, SCRIPT, "--raw", str(RAW_DIR), "--label", str(LABEL), "--out", str(out),
                            "--smoke"], check=True, capture_output=True, timeout=300)
            r = json.loads(out.read_text())
            self.assertEqual(r["scope"], "smoke")
            self.assertEqual(r["shifts_run"], ["2026_07_27_evening"])
            c = r["pooled"]["cleaning"]
            self.assertEqual((c["raw_rows"], c["authors_removed"], c["rule_drops"]), (15389, 351, 0))
            self.assertEqual(r["page_sentence"], "No row of the authors' cleaned table was rejected by our parser; the "
                             "authors had already removed 351 of 15,389 raw rows (2.3 %)")
            self.assertEqual(r["intervention_episode"]["start"], "2026-07-30T06:16:31Z")
            self.assertEqual(sorted(os.listdir(d)), ["out.json"])


if __name__ == "__main__":
    unittest.main()

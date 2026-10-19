"""Tests for S10F: costmap.py --gate baseline|persistence, --reset-forecasts and hotspot_score's gate_grading.

Synthetic streams carry hand-computed expectations; every synthetic test passes B, S, E, C and K explicitly so a
change of the CLI defaults cannot move a hand-computed value. The data tests read WR_S10_DATA (the directory holding
s10-none; default REPO/fleet/data) and skip when it is absent (CI has no data). No env, no Docker."""
import contextlib
import io
import json
import math
import os
import shutil
import statistics
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "fleet") not in sys.path:
    sys.path.insert(0, str(ROOT / "fleet"))

import costmap  # noqa: E402
import grade  # noqa: E402
import hotspot_score  # noqa: E402
import time_to_detect  # noqa: E402
from fleet_analyser import decisions  # noqa: E402
from fleet_analyser.parse import Message  # noqa: E402
from fleet_analyser.store import JsonlStore, MemoryStore  # noqa: E402

DATA = Path(os.environ.get("WR_S10_DATA") or ROOT / "fleet" / "data")
S10_NONE = DATA / "s10-none"
FIRST_TS, EVERY, N_PUBLISH = 1000, 300, 7
PARAMS = dict(gate_windows=3, gate_sigma=2.0, gate_min_excess=2, gate_min_count=2, top_k=20)


def message(zone, ts, serial=None):
    return Message(serial=serial or f"Z{zone}-01", zone=zone, header_id=ts, ts=ts, order_id="o", x=1, y=1,
                   driving=False, faulted=False, loaded=False, raw_len=1, theta=0.0, next_x=2, next_y=1,
                   nodes_reported=True)


def stall(zone, cell, window, k=0):
    """A counted stall of `cell` whose end lies in gate window `window` (1-based): (t_{w-1}, t_w], t_w = 1000 + 300 w."""
    end = FIRST_TS + EVERY * (window - 1) + 150
    return dict(run="r", zone=zone, robot=f"Z{zone}-{k:02d}", cell=cell, attribution="next", start=end - 2, end=end,
                n_msgs=1, seconds=2, next_occupied=False, in_episode=None, faulted_episode=False)


def bg_cells(n=20):
    return [f"{i:02d},0" for i in range(n)]


def stream(counts, zone="0"):
    """counts: {cell: [count in window 1, 2, ...]}. Returns (messages, stalls); the messages span exactly
    N_PUBLISH publishes (the last one at the stream end, which is also a grid point)."""
    stalls = [stall(zone, c, w, k) for c, per in counts.items() for w, n in enumerate(per, 1) for k in range(n)]
    msgs = [message(zone, FIRST_TS), message(zone, FIRST_TS + EVERY * N_PUBLISH)]
    return msgs, stalls


def run_gate(msgs, stalls, gate, store=None, **kw):
    store = MemoryStore() if store is None else store
    with mock.patch.object(costmap.hotspot, "extract_stalls", return_value=[dict(s) for s in stalls]):
        doc = costmap.build_costmap(msgs, store, "r", publish_every=EVERY, gate=gate, **{**PARAMS, **kw})
    return doc, store


def forecasts(store):
    return store.select("decisions", {"run": "r", "kind": "hotspot_forecast"})


def claim(d):
    return json.loads(d["claim"])


def by_publish(store):
    out = {}
    for d in forecasts(store):
        out.setdefault(d["decided_at"], []).append(d)
    return out


def t_of(i):
    return FIRST_TS + EVERY * i


class TestBaselineGate(unittest.TestCase):
    def setUp(self):
        counts = {c: [3] * N_PUBLISH for c in bg_cells()}
        counts["J"] = [3, 3, 3] + [9] * (N_PUBLISH - 3)
        self.msgs, self.stalls = stream(counts)
        self.doc, self.store = run_gate(self.msgs, self.stalls, "baseline")

    def test_warmup_then_exactly_j_at_publish_4(self):
        pubs = self.doc["gate"]["publishes"]
        self.assertEqual([p["published_at"] for p in pubs], [t_of(i) for i in range(1, N_PUBLISH + 1)])
        self.assertEqual([p["gate_warmup"] for p in pubs], [True] * 3 + [False] * 4)
        self.assertEqual([p["flagged"] for p in pubs[:3]], [{"0": []}] * 3)
        self.assertEqual(pubs[3]["flagged"], {"0": ["J"]})
        for p in pubs[4:]:
            self.assertEqual(p["flagged"], {"0": []})  # publish 5: m=5, sd=sqrt(8), 9 > 10.66 false; 6, 7 higher still
        got = by_publish(self.store)
        self.assertEqual(sorted(got), [t_of(4)])
        self.assertEqual([d["subject"] for d in got[t_of(4)]], ["Z0:J"])

    def test_claim_fields_hand_computed(self):
        c = claim(forecasts(self.store)[0])
        self.assertEqual((c["gate"], c["gate_reason"], c["gate_count"]), ("baseline", "above_baseline", 9))
        self.assertEqual((c["gate_mean"], c["gate_sd"]), (3, 0.0))  # windows 1-3 of J: 3, 3, 3
        self.assertEqual((c["gate_windows"], c["gate_sigma"], c["gate_min_excess"]), (3, 2.0, 2))

    def test_later_publishes_use_the_jump_in_the_baseline(self):
        # publish 5: windows 2-4 of J are 3, 3, 9 -> m = 5, sd = sqrt(8): 9 > 5 + 2 * 2.83 = 10.66 is false
        windows = costmap.gate_window_counts(self.stalls, [t_of(i) for i in range(1, N_PUBLISH + 1)], FIRST_TS)
        self.assertEqual([w["0"]["J"] for w in windows], [3, 3, 3, 9, 9, 9, 9])
        passed = costmap.gate_pass("baseline", windows, 4, "0", 20, 3, 2.0, 2, 2)
        self.assertEqual(passed, {})
        hist = [3, 3, 9]
        self.assertAlmostEqual(math.sqrt(8), statistics.pstdev(hist))
        self.assertFalse(9 > 5 + 2.0 * math.sqrt(8))

    def test_no_background_cell_is_ever_flagged(self):
        flagged = {c for p in self.doc["gate"]["publishes"] for cs in p["flagged"].values() for c in cs}
        self.assertEqual(flagged, {"J"})

    def test_gated_forecast_is_the_ungated_one_plus_gate_fields(self):
        _, plain = run_gate(self.msgs, self.stalls, "none")
        ungated = {d["id"]: d for d in forecasts(plain)}
        self.assertEqual(len(ungated), 21 * N_PUBLISH)
        for d in forecasts(self.store):
            u = ungated[d["id"]]
            c = {k: v for k, v in claim(d).items() if not k.startswith("gate")}
            self.assertEqual(c, claim(u))
            for key in ("subject", "decided_at", "expected", "grade_after", "claim_version"):
                self.assertEqual(d[key], u[key])

    def test_costmap_rows_and_values_are_unchanged_by_the_gate(self):
        doc_none, plain = run_gate(self.msgs, self.stalls, "none")
        self.assertEqual(self.store.select("costmap"), plain.select("costmap"))
        self.assertEqual({k: v for k, v in self.doc.items() if k != "gate"}, doc_none)
        self.assertNotIn("gate", doc_none)


class TestPersistenceGate(unittest.TestCase):
    def setUp(self):
        counts = {c: [3] * N_PUBLISH for c in bg_cells()}
        counts["J"] = [1, 1, 1, 5, 5, 8, 8]
        self.msgs, self.stalls = stream(counts)
        self.doc, self.store = run_gate(self.msgs, self.stalls, "persistence")

    def test_j_flagged_at_4_and_6_only(self):
        pubs = self.doc["gate"]["publishes"]
        self.assertEqual([p["gate_warmup"] for p in pubs], [True] + [False] * 6)
        self.assertEqual([p["flagged"]["0"] for p in pubs], [[], [], [], ["J"], [], ["J"], []])
        reasons = {d["decided_at"]: claim(d) for d in forecasts(self.store)}
        self.assertEqual(sorted(reasons), [t_of(4), t_of(6)])
        self.assertEqual(reasons[t_of(4)]["gate_reason"], "new_entrant+rose")
        self.assertEqual(reasons[t_of(6)]["gate_reason"], "rose")
        self.assertEqual((reasons[t_of(4)]["gate_count"], reasons[t_of(4)]["gate_prev_count"]), (5, 1))
        self.assertEqual((reasons[t_of(6)]["gate_count"], reasons[t_of(6)]["gate_prev_count"]), (8, 5))
        c = reasons[t_of(4)]
        self.assertEqual((c["gate"], c["gate_top_k"], c["gate_min_count"], c["gate_min_excess"]),
                         ("persistence", 20, 2, 2))

    def test_no_background_cell_is_ever_flagged(self):
        flagged = {c for p in self.doc["gate"]["publishes"] for cs in p["flagged"].values() for c in cs}
        self.assertEqual(flagged, {"J"})

    def test_top_k_is_ranked_within_each_zone(self):
        # zone 0: 20 cells at count 5 every window; zone 1: one cell X at 0 then 2 in window 2. A top K over both zones
        # would push X (count 2) out; within its own zone X enters at once: new entrant with count 2 >= C. E = 3
        # keeps the rise rule (2 - 0 >= 3) out of it.
        counts = {c: [5] * N_PUBLISH for c in bg_cells()}
        msgs, stalls = stream(counts, "0")
        stalls += [stall("1", "X", 2, k) for k in range(2)]
        msgs += [message("1", FIRST_TS), message("1", FIRST_TS + EVERY * N_PUBLISH)]
        doc, store = run_gate(msgs, stalls, "persistence", gate_min_excess=3)
        self.assertEqual(doc["gate"]["publishes"][1]["flagged"], {"0": [], "1": ["X"]})
        self.assertEqual(claim(forecasts(store)[0])["gate_reason"], "new_entrant")

    def test_stream_end_window_shorter_than_the_grid(self):
        # the stream ends 95 s after the last grid point: that last window is gated as it is
        msgs = [message("0", FIRST_TS), message("0", t_of(3) + 95)]
        stalls = [stall("0", "A", 4, k) for k in range(4)]
        stalls = [dict(s, end=t_of(3) + 50) for s in stalls]
        doc, _ = run_gate(msgs, stalls, "persistence")
        pubs = doc["gate"]["publishes"]
        self.assertEqual([p["published_at"] for p in pubs], [t_of(1), t_of(2), t_of(3), t_of(3) + 95])
        self.assertEqual(pubs[3]["flagged"], {"0": ["A"]})


class TestGateCli(unittest.TestCase):
    def test_gate_without_publish_every_exits_nonzero(self):
        for gate in ("baseline", "persistence"):
            with self.subTest(gate=gate), contextlib.redirect_stderr(io.StringIO()) as err:
                with self.assertRaises(SystemExit) as cm:
                    costmap.main(["--glob", "nothing/*.jsonl.gz", "--gate", gate])
            self.assertNotEqual(cm.exception.code, 0)
            self.assertIn("--publish-every", err.getvalue())

    def test_default_is_none_and_the_defaults_are_the_start_values(self):
        a = costmap.build_parser().parse_args(["--glob", "x"])
        self.assertEqual((a.gate, a.gate_windows, a.gate_sigma, a.gate_min_excess, a.gate_min_count, a.reset_forecasts),
                         ("none", 3, 2.0, 2, 2, False))

    def test_reset_forecasts_refusals(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "store").mkdir()
            cwd = os.getcwd()
            cases = [f"jsonl:{tmp / 'store'}", f"jsonl:{tmp / 'store'}/", "jsonl:./store", "clickhouse://h:1/db", None]
            os.chdir(tmp)
            try:
                for spec in cases:
                    argv = ["--glob", "nothing/*.jsonl.gz", "--reset-forecasts"] + (["--store", spec] if spec else [])
                    with self.subTest(store=spec), contextlib.redirect_stderr(io.StringIO()) as err:
                        with self.assertRaises(SystemExit) as cm:
                            costmap.main(argv)
                        self.assertNotEqual(cm.exception.code, 0)
                        self.assertIn("--reset-forecasts", err.getvalue())
            finally:
                os.chdir(cwd)
            self.assertTrue((tmp / "store").is_dir())


class TestResetForecasts(unittest.TestCase):
    def test_counts_and_a_gated_rerun_holds_only_gated_rows(self):
        counts = {c: [3] * N_PUBLISH for c in bg_cells()}
        counts["J"] = [3, 3, 3] + [9] * (N_PUBLISH - 3)
        msgs, stalls = stream(counts)
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "store-gate-baseline"
            st = JsonlStore(d)
            run_gate(msgs, stalls, "none", store=st)
            fc = forecasts(st)
            self.assertEqual(len(fc), 21 * N_PUBLISH)
            for i, f in enumerate(fc[:5]):  # a stamped grade (update record) on 5 decisions, a grade row on 4 of them
                decisions.stamp_grade(st, f["id"], 1, None, "ok", 5)
                if i < 4:
                    st.upsert("forecast_grades", ("id", "grade_source"), [dict(
                        id=f["id"], run="r", grade_source="outcome", verdict="ok", outcome=1, expected=1, error=None,
                        horizon_s=1, graded_at=1)])
            st.upsert("forecast_grades", ("id", "grade_source"), [dict(
                id="other", run="o", grade_source="outcome", verdict="ok", outcome=1, expected=1, error=None,
                horizon_s=1, graded_at=1)])
            st.upsert("costmap", ("run", "published_at", "zone", "cell"), [dict(
                run="other", zone="0", published_at=1, cell="1,1", cost=1.0, score=1.0, stalls=1)])
            n_cm = len(st.select("costmap", {"run": "r"}))
            st.close()
            self.assertEqual(costmap.reset_forecasts(d, "r"), (21 * N_PUBLISH, 4, n_cm))
            st = JsonlStore(d)
            self.assertEqual(st.select("decisions"), [])
            self.assertEqual([g["id"] for g in st.select("forecast_grades")], ["other"])
            self.assertEqual([r["run"] for r in st.select("costmap")], ["other"])
            self.assertNotIn("__upd", (d / "decisions.jsonl").read_text())
            doc, _ = run_gate(msgs, stalls, "baseline", store=st)
            st.close()
            st = JsonlStore(d)
            rerun = forecasts(st)
            self.assertEqual([claim(f)["gate"] for f in rerun], ["baseline"])
            self.assertEqual({f["status"] for f in rerun}, {"open"})
            self.assertEqual(doc["gate"]["publishes"][3]["flagged"], {"0": ["J"]})
            st.close()

    def test_a_rerun_without_the_reset_dedupes_into_the_ungated_rows(self):
        # why --reset-forecasts exists: the ids are deterministic, so the gated rerun writes nothing new
        counts = {c: [3] * N_PUBLISH for c in bg_cells()}
        counts["J"] = [3, 3, 3] + [9] * (N_PUBLISH - 3)
        msgs, stalls = stream(counts)
        st = MemoryStore()
        run_gate(msgs, stalls, "none", store=st)
        with contextlib.redirect_stderr(io.StringIO()) as err:
            run_gate(msgs, stalls, "baseline", store=st)
        self.assertIn("--reset-forecasts", err.getvalue())
        self.assertTrue(all("gate" not in claim(d) for d in forecasts(st)))


def two_msgs(zone="0"):
    return [message(zone, FIRST_TS), message(zone, FIRST_TS + EVERY * N_PUBLISH)]


def raw_stall(zone, cell, end, robot, **over):
    s = dict(run="r", zone=zone, robot=robot, cell=cell, attribution="next", start=end - 2, end=end, n_msgs=1,
             seconds=2, next_occupied=False, in_episode=None, faulted_episode=False)
    s.update(over)
    return s


class TestStallFilterInTheGate(unittest.TestCase):
    """hotspot.counted decides which stalls the gate counts. Cell X, persistence, C = 2, E = 3, no background:
    window 2 holds one plain stall, one stall of a robot inside a blocked_by_faulted episode (annotate_episodes sets
    faulted_episode from the store's stuck_episodes, as in production) and one stall with next_occupied. Counted by
    default: 1 (below C and E: not flagged). With exclude_occupied=False: 2 (plain + occupied; new entrant, count 2,
    flagged). The faulted stall never counts: counting it would make 2 by default (flagged) and 3 with occupied (a
    rise of 3 >= E, reason new_entrant+rose, count 3)."""

    def setUp(self):
        self.stalls = [raw_stall("0", "X", t_of(1) + 150, "Z0-01"),
                       raw_stall("0", "X", t_of(1) + 160, "Z0-90"),  # inside the faulted episode below
                       raw_stall("0", "X", t_of(1) + 170, "Z0-91", next_occupied=True)]
        self.episode = dict(run="r", zone="0", robot="Z0-90", start=t_of(1) + 100, end=t_of(1) + 200,
                            cause="blocked_by_faulted")
        self.times = [t_of(i) for i in range(1, N_PUBLISH + 1)]

    def run_x(self, **kw):
        st = MemoryStore()
        st.insert("stuck_episodes", [self.episode])
        return run_gate(two_msgs(), self.stalls, "persistence", store=st, gate_min_excess=3, **kw)

    def annotated(self):
        return costmap.hotspot.annotate_episodes([dict(s) for s in self.stalls], [self.episode])

    def test_default_counts_the_plain_stall_only(self):
        self.assertEqual([s["faulted_episode"] for s in self.annotated()], [False, True, False])
        self.assertEqual(costmap.gate_window_counts(self.annotated(), self.times, FIRST_TS)[1], {"0": {"X": 1}})
        doc, st = self.run_x()
        self.assertEqual([p["flagged"] for p in doc["gate"]["publishes"]], [{"0": []}] * N_PUBLISH)
        self.assertEqual(forecasts(st), [])

    def test_exclude_occupied_false_counts_the_occupied_stall_but_never_the_faulted_one(self):
        self.assertEqual(costmap.gate_window_counts(self.annotated(), self.times, FIRST_TS, False)[1],
                         {"0": {"X": 2}})
        doc, st = self.run_x(exclude_occupied=False)
        self.assertEqual([p["flagged"]["0"] for p in doc["gate"]["publishes"]], [[], ["X"]] + [[]] * 5)
        c = claim(forecasts(st)[0])
        self.assertEqual((c["gate_count"], c["gate_reason"], c["exclude_occupied"]), (2, "new_entrant", False))

    def test_cli_include_occupied_reaches_the_gate(self):
        for extra, want in (([], [[]] * N_PUBLISH), (["--include-occupied"], [[], ["X"]] + [[]] * 5)):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as tmp:
                store, out = Path(tmp) / "store-x", Path(tmp) / "c.json"
                st = JsonlStore(store)
                st.insert("stuck_episodes", [self.episode])
                st.close()
                with mock.patch.object(costmap.hotspot, "read_messages", return_value=two_msgs()), \
                        mock.patch.object(costmap.hotspot, "extract_stalls",
                                          return_value=[dict(s) for s in self.stalls]), \
                        contextlib.redirect_stdout(io.StringIO()):
                    code = costmap.main(["--glob", "x/*.jsonl.gz", "--store", f"jsonl:{store}", "--run", "r",
                                         "--publish-every", str(EVERY), "--gate", "persistence",
                                         "--gate-min-excess", "3", "--out", str(out), *extra])
                self.assertEqual(code, 0)
                doc = json.loads(out.read_text())
                self.assertEqual([p["flagged"]["0"] for p in doc["gate"]["publishes"]], want)


class TestWindowEdges(unittest.TestCase):
    def test_end_equal_to_a_publish_time_counts_in_that_window(self):
        # two stalls of Y end exactly at t_2: window 2 = (t_1, t_2] holds them, window 3 does not. Persistence
        # (C = 2, E = 3): Y is a new entrant with count 2 at publish 2; with the edge one window later it would be
        # flagged at publish 3 instead.
        stalls = [raw_stall("0", "Y", t_of(2), f"Z0-0{k}") for k in range(2)]
        w = costmap.gate_window_counts(stalls, [t_of(i) for i in range(1, N_PUBLISH + 1)], FIRST_TS)
        self.assertEqual((w[1], w[2]), ({"0": {"Y": 2}}, {}))
        doc, _ = run_gate(two_msgs(), stalls, "persistence", gate_min_excess=3)
        self.assertEqual([p["flagged"]["0"] for p in doc["gate"]["publishes"]], [[], ["Y"]] + [[]] * 5)

    def test_first_window_starts_after_first_ts_minus_one(self):
        # baseline B = 1, S = 0, E = 2. Cell P: 3 mid-window stalls in window 2. Window 1 gets a stall ending at
        # first_ts (counts) and one ending at first_ts - 1 = t_0 (does not): history m = 1, 3 - 1 >= 2: flagged with
        # gate_mean 1. Counting the t_0 stall gives m = 2 (not flagged); dropping the first_ts stall gives m = 0.
        stalls = [raw_stall("0", "P", FIRST_TS, "Z0-01"), raw_stall("0", "P", FIRST_TS - 1, "Z0-02")]
        stalls += [raw_stall("0", "P", t_of(1) + 100 + k, f"Z0-1{k}") for k in range(3)]
        w = costmap.gate_window_counts(stalls, [t_of(i) for i in range(1, N_PUBLISH + 1)], FIRST_TS)
        self.assertEqual((w[0], w[1]), ({"0": {"P": 1}}, {"0": {"P": 3}}))
        doc, st = run_gate(two_msgs(), stalls, "baseline", gate_windows=1, gate_sigma=0.0, gate_min_excess=2)
        self.assertEqual([p["flagged"]["0"] for p in doc["gate"]["publishes"]], [[], ["P"]] + [[]] * 5)
        c = claim(forecasts(st)[0])
        self.assertEqual((c["gate_mean"], c["gate_count"]), (1, 3))


class TestResetForecastsStoreRule(unittest.TestCase):
    """reset_forecasts reads a store directory by the rule of JsonlStore._load (a complete line that does not parse is
    skipped, a last line without its newline is a torn write and ignored). What it does with them: the unparsable
    complete line stays in the file verbatim, the torn fragment is not written back (a rewritten file ends without it)."""

    def make(self, tmp):
        msgs, stalls = stream({c: [3] * N_PUBLISH for c in bg_cells(2)})
        d = Path(tmp) / "store-gate-x"
        st = JsonlStore(d)
        run_gate(msgs, stalls, "none", store=st)
        n = len(forecasts(st))
        st.close()
        return d, n

    def test_torn_last_line_and_unparsable_line_are_read_like_the_store_reads_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            d, n = self.make(tmp)
            path = d / "decisions.jsonl"
            lines = path.read_text().splitlines(True)
            fragment = '{"id":"torn-fragment","kind":"hotspot_for'
            path.write_text("".join(lines[:1] + ["this is not json\n"] + lines[1:]) + fragment)
            self.assertEqual(len(JsonlStore(d).select("decisions")), n)  # the store reads it fine
            self.assertEqual(costmap.reset_forecasts(d, "r")[0], n)  # and so does reset: no JSONDecodeError
            text = path.read_text()
            self.assertNotIn("torn-fragment", text)  # the torn write is not written back, whole or torn
            self.assertEqual(text, "this is not json\n")  # the unparsable complete line is kept verbatim
            self.assertEqual(JsonlStore(d).select("decisions"), [])

    def test_a_torn_last_line_is_never_matched_even_if_it_would_parse(self):
        # a last line without its newline that happens to be valid JSON is still ignored by the store: reset must
        # not count it as a decision of the run (it would be a phantom id) or write it back
        with tempfile.TemporaryDirectory() as tmp:
            d, n = self.make(tmp)
            path = d / "decisions.jsonl"
            whole = json.loads(path.read_text().splitlines()[0])
            path.write_text(path.read_text() + json.dumps(dict(whole, id="extra-id", dedup_key="extra-key")))
            self.assertEqual(len(JsonlStore(d).select("decisions")), n)
            self.assertEqual(costmap.reset_forecasts(d, "r")[0], n)
            self.assertNotIn("extra-id", path.read_text())

    def test_a_torn_tail_in_a_file_with_nothing_to_drop_is_removed_not_completed(self):
        with tempfile.TemporaryDirectory() as tmp:
            d, _ = self.make(tmp)
            path = d / "costmap.jsonl"
            keep = '{"run":"other","zone":"0","published_at":1,"cell":"1,1","cost":1.0,"score":1.0,"stalls":1}\n'
            path.write_text(keep + '{"run":"r","zone":"0","pub')
            self.assertEqual(costmap.reset_forecasts(d, "r")[2], 0)
            self.assertEqual(path.read_text(), keep)


class TestExistingForecastWarning(unittest.TestCase):
    def test_gated_run_over_existing_forecasts_warns_once_on_stderr(self):
        counts = {c: [3] * N_PUBLISH for c in bg_cells()}
        counts["J"] = [3, 3, 3] + [9] * (N_PUBLISH - 3)
        msgs, stalls = stream(counts)

        def go(tmp, store, *extra):
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.object(costmap.hotspot, "read_messages", return_value=msgs), \
                    mock.patch.object(costmap.hotspot, "extract_stalls", return_value=[dict(s) for s in stalls]), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = costmap.main(["--glob", "x/*.jsonl.gz", "--store", f"jsonl:{store}", "--run", "r",
                                     "--publish-every", str(EVERY), "--out", str(Path(tmp) / "c.json"), *extra])
            self.assertEqual(code, 0)
            return out.getvalue(), err.getvalue()

        with tempfile.TemporaryDirectory() as tmp:
            fresh_out, fresh_err = go(tmp, Path(tmp) / "store-a", "--gate", "baseline")
            self.assertEqual(fresh_err, "")
            store = Path(tmp) / "store-b"
            go(tmp, store)  # the ungated forecasts
            out, err = go(tmp, store, "--gate", "baseline")  # rerun without --reset-forecasts
            self.assertEqual(len(err.splitlines()), 1)
            self.assertTrue(err.startswith("warning:"))
            self.assertIn("--reset-forecasts", err)
            self.assertEqual(out, fresh_out)  # stdout is what a fresh gated run prints
            out2, err2 = go(tmp, store, "--gate", "baseline", "--reset-forecasts")
            self.assertEqual(err2, "")  # with the reset there is nothing to warn about
            self.assertEqual(out2.splitlines()[1:], fresh_out.splitlines())
            self.assertTrue(out2.startswith("reset-forecasts r: dropped"))
            _, plain_err = go(tmp, store)  # no gate: a rerun is a legitimate no-op, no warning
            self.assertEqual(plain_err, "")


def capture(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = costmap.main(argv)
    return code, out.getvalue()


@unittest.skipUnless((S10_NONE / "costmap.json").exists() and (S10_NONE / "store").is_dir(),
                     f"no s10-none data under {DATA} (set WR_S10_DATA)")
class TestS10NoneData(unittest.TestCase):
    RUN = "s10-none"

    def copy(self, tmp, name, strip=False):
        dst = Path(tmp) / name
        shutil.copytree(S10_NONE / "store", dst)
        if strip:
            time_to_detect.strip_forecasts(dst, self.RUN)
            time_to_detect.strip_costmap(dst, self.RUN)
        return dst

    def argv(self, store, out, *extra):
        return ["--glob", str(S10_NONE / "*.jsonl.gz"), "--store", f"jsonl:{store}", "--run", self.RUN,
                "--publish-every", "300", "--horizon-s", "1245", "--out", str(out), *extra]

    def test_gate_none_is_byte_identical_to_the_recorded_costmap(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, out = self.copy(tmp, "store-copy", strip=True), Path(tmp) / "costmap.json"
            code, text = capture(self.argv(store, out))
            self.assertEqual(code, 0)
            self.assertNotIn("gate", text)
            self.assertEqual(out.read_bytes(), (S10_NONE / "costmap.json").read_bytes())

    def test_both_gates_flag_at_most_two_cells_per_zone_and_publish(self):
        for gate in ("baseline", "persistence"):
            with self.subTest(gate=gate), tempfile.TemporaryDirectory() as tmp:
                store = self.copy(tmp, "store-gate-x")
                n_before = len(JsonlStore(store).select("decisions", {"kind": "hotspot_forecast"}))
                out = Path(tmp) / "costmap.json"
                code, text = capture(self.argv(store, out, "--gate", gate, "--reset-forecasts"))
                self.assertEqual(code, 0)
                doc = json.loads(out.read_text())
                live = [p for p in doc["gate"]["publishes"] if not p["gate_warmup"]]
                per = [len(cells) for p in live for cells in p["flagged"].values()]
                print(f"\n[{gate}] s10-none: max flags per zone per non-warm-up publish {max(per)}, total {sum(per)}, "
                      f"{len(live)} non-warm-up publishes; reset dropped decisions {n_before}")
                self.assertLessEqual(max(per), 2)
                self.assertIn(f"dropped {n_before} hotspot_forecast decisions", text)
                self.assertIn(f"gate {gate}: flagged cells per zone per non-warm-up publish max {max(per)} total "
                              f"{sum(per)}", text)
                st = JsonlStore(store)
                fc = st.select("decisions", {"kind": "hotspot_forecast"})
                self.assertEqual(len(fc), sum(per))
                self.assertTrue(all(claim(d)["gate"] == gate for d in fc))
                flagged = {(p["published_at"], z, c) for p in doc["gate"]["publishes"]
                           for z, cells in p["flagged"].items() for c in cells}
                self.assertEqual({(d["decided_at"], d["subject"][1:].split(":")[0], d["subject"].split(":")[1])
                                  for d in fc}, flagged)
                st.close()

    def test_reset_then_grade_leaves_only_gated_grades(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self.copy(tmp, "store-gate-x")
            st = JsonlStore(store)
            fids = {d["id"] for d in st.select("decisions", {"kind": "hotspot_forecast"})}
            old_grades = len([g for g in st.select("forecast_grades") if g["id"] in fids])
            other_grades = len(st.select("forecast_grades")) - old_grades
            n_costmap = len(st.select("costmap", {"run": self.RUN}))
            st.close()
            code, text = capture(self.argv(store, Path(tmp) / "c.json", "--gate", "persistence", "--reset-forecasts"))
            self.assertEqual(code, 0)
            self.assertRegex(text, rf"dropped \d+ hotspot_forecast decisions, {old_grades} forecast_grades rows, "
                                   rf"{n_costmap} costmap rows")
            st = JsonlStore(store)
            self.assertEqual(len(st.select("forecast_grades")), other_grades)  # lesson grades stay
            self.assertFalse([g for g in st.select("forecast_grades") if g["id"] in fids])
            st.close()
            with contextlib.redirect_stdout(io.StringIO()):
                grade.main(["--run", self.RUN, "--store", f"jsonl:{store}", "--once"])
            st = JsonlStore(store)
            ids = {d["id"] for d in st.select("decisions", {"kind": "hotspot_forecast"})}
            graded = {g["id"] for g in st.select("forecast_grades", {"grade_source": "outcome_count"})}
            self.assertTrue(graded)
            self.assertTrue(graded <= ids)
            st.close()


def forecast_decision(st, zone, cell, t, gate="baseline"):
    did, _ = decisions.record_decision(
        st, run="r", kind="hotspot_forecast", subject=f"Z{zone}:{cell}", start_iso=f"T{t}", decided_at=t,
        claim=dict(rank=1, cost=1.0, top_k=20, gate=gate) if gate else dict(rank=1, cost=1.0, top_k=20),
        rationale="x", expected=1.0, grade_after=t + 10)
    return did


def truth_row(did, verdict):
    return dict(id=did, run="r", grade_source="truth", verdict=verdict, outcome=None, expected=None, error=None,
                horizon_s=None, graded_at=None)


class TestGateGrading(unittest.TestCase):
    def build(self, st):
        """baseline: Z0:1,1 hit at 100 and 200 (one cell hit twice), Z0:2,2 false alarm at 200, Z0:3,3 false alarm at
        300, Z0:5,5 at 400 without a truth row, Z1:1,1 hit at 100. persistence: one forecast without a truth row.
        (zone, decided_at) pairs of baseline: (0,100) 1, (1,100) 1, (0,200) 2, (0,300) 1, (0,400) 1."""
        rows = [(forecast_decision(st, 0, "1,1", 100), "hit"), (forecast_decision(st, 0, "1,1", 200), "hit"),
                (forecast_decision(st, 0, "2,2", 200), "false_alarm"),
                (forecast_decision(st, 0, "3,3", 300), "false_alarm"),
                (forecast_decision(st, 0, "5,5", 400), None), (forecast_decision(st, 1, "1,1", 100), "hit")]
        forecast_decision(st, 0, "7,7", 100, gate="persistence")
        forecast_decision(st, 0, "8,8", 100, gate=None)  # ungated: in no block
        st.upsert("forecast_grades", ("id", "grade_source"), [truth_row(i, v) for i, v in rows if v])
        st.upsert("forecast_grades", ("id", "grade_source"), [dict(truth_row(rows[0][0], "hit"), grade_source="outcome")])

    def test_every_field_by_hand(self):
        st = MemoryStore()
        self.build(st)
        res = hotspot_score.gate_grading(st.select("decisions"), st.select("forecast_grades"), 4)
        self.assertEqual(sorted(res), ["baseline", "persistence"])
        self.assertEqual(res["baseline"], dict(
            forecasts=6, truth_graded=5, hits=3, false_alarms=2, precision=3 / 5, hit_cells=2, positive_cells=4,
            recall=2 / 4, flags_per_zone_publish=dict(max=2, mean=6 / 5)))
        self.assertEqual(res["persistence"], dict(
            forecasts=1, truth_graded=0, hits=0, false_alarms=0, precision=None, hit_cells=0, positive_cells=4,
            recall=0.0, flags_per_zone_publish=dict(max=1, mean=1.0)))

    def test_none_without_a_gate_claim_and_null_recall_at_zero_positives(self):
        st = MemoryStore()
        forecast_decision(st, 0, "1,1", 100, gate=None)
        self.assertIsNone(hotspot_score.gate_grading(st.select("decisions"), [], 4))
        st = MemoryStore()
        forecast_decision(st, 0, "1,1", 100)
        res = hotspot_score.gate_grading(st.select("decisions"), [], 0)
        self.assertIsNone(res["baseline"]["recall"])

    def test_mean_is_over_pairs_holding_a_flag_not_over_the_zone_by_publish_grid(self):
        # gate_grading sees only the decisions, so a (zone, decided_at) pair without a forecast can never be in its
        # denominator; the grid is pinned by hand: zone 0 flags 2 cells at t=100 (zone 1 none), zone 1 flags 1 cell at
        # t=200 (zone 0 none). Pairs (0,100)=2 and (1,200)=1: mean 1.5, max 2. Averaging over every zone x decided_at
        # (2 x 2 = 4 pairs, two of them empty) would give 3 / 4 = 0.75.
        st = MemoryStore()
        forecast_decision(st, 0, "1,1", 100)
        forecast_decision(st, 0, "2,2", 100)
        forecast_decision(st, 1, "1,1", 200)
        res = hotspot_score.gate_grading(st.select("decisions"), [], 1)
        self.assertEqual(res["baseline"]["flags_per_zone_publish"], dict(max=2, mean=1.5))
        self.assertNotEqual(res["baseline"]["flags_per_zone_publish"]["mean"], 3 / 4)

    def test_main_writes_gate_grading_only_for_a_gated_run(self):
        for gated in (True, False):
            with self.subTest(gated=gated), tempfile.TemporaryDirectory() as d:
                d = Path(d)
                floor = {"1,1": 0.5, "2,2": 0.5}
                zones = {z: dict(seed=0, floor_cells=floor, floor_skips=[0] * 10, floor_skips_total=0) for z in "01"}
                (d / "truth.json").write_text(json.dumps(dict(
                    schema_version="fleet-truth/1", env_id="x", disturb_tag="x", disturb={}, steps=10, seed_base=0,
                    zones=zones)))
                (d / "costmap.json").write_text(json.dumps(dict(
                    schema_version="fleet-costmap/1", run="r", generated_at="x", window_hours=1, half_life_h=1,
                    min_stalls=1, exclude_occupied=True, zones={"0": {"1,1": 1.0}, "1": {"1,1": 1.0}})))
                st = JsonlStore(d / "store")
                if gated:
                    self.build(st)
                else:
                    forecast_decision(st, 0, "1,1", 100, gate=None)
                st.close()
                out = d / "o.json"
                text = io.StringIO()
                with contextlib.redirect_stdout(text):
                    code = hotspot_score.main(["--run-dir", str(d), "--store", f"jsonl:{d / 'store'}", "--tag", "t",
                                               "--out", str(out)])
                self.assertEqual(code, 0)
                res = json.loads(out.read_text())
                if gated:
                    self.assertEqual(res["truth_kinds"]["any"]["positives"], 4)
                    self.assertEqual(list(res)[-1], "gate_grading")
                    self.assertEqual(res["gate_grading"]["baseline"]["recall"], 2 / 4)
                    self.assertEqual(res["gate_grading"]["baseline"]["hit_cells"], 2)
                    self.assertNotIn("gate baseline", text.getvalue())  # gate_grading lives in the JSON only
                else:
                    self.assertNotIn("gate_grading", res)
                    self.assertNotIn("gate ", text.getvalue())


if __name__ == "__main__":
    unittest.main()

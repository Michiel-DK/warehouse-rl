"""Tests for the decision ledger (record_decision / stamp_grade), the stores, and the evidence the ingest keeps per
decision. Each case names its red demonstration in an `# inject:` comment."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "fleet") not in sys.path:
    sys.path.insert(0, str(ROOT / "fleet"))

from fleet.tests.test_fleet_ingest import BASE, ingest_dir, interleaved, scenario, write_gz  # noqa: E402
from fleet_analyser import decisions  # noqa: E402
from fleet_analyser.store import JsonlStore, MemoryStore  # noqa: E402

GRADING = {"status", "outcome", "error", "verdict", "graded_at"}


def make(store, start="2026-01-01T00:00:00Z", **kw):
    args = dict(run="r", kind="stuck_cause", subject="Z0-00", start_iso=start, decided_at=BASE + 30,
                claim={"episode_id": "Z0-00@" + start, "cause": "unknown"}, rationale="one line", expected=None,
                grade_after=BASE + 3630)
    args.update(kw)
    return decisions.record_decision(store, **args)


class TestRecordAndStamp(unittest.TestCase):
    def test_dedup_key_uses_event_time_and_id_is_its_sha1(self):
        # inject: leave the episode start out of the dedup key
        store = MemoryStore()
        did, created = make(store, recorded_at=111.0)
        key = "stuck_cause:Z0-00:2026-01-01T00:00:00Z"
        self.assertTrue(created)
        self.assertEqual(did, hashlib.sha1(key.encode()).hexdigest())
        row = store.select("decisions")[0]
        self.assertEqual(row["dedup_key"], key)
        self.assertEqual(row["id"], did)
        did2, created2 = make(store, recorded_at=99999.0)  # a re-run at another wall time
        self.assertEqual((did2, created2), (did, False))
        self.assertEqual(len(store.select("decisions")), 1)

    def test_row_columns_and_defaults(self):
        # inject: start a decision with status graded
        store = MemoryStore()
        make(store, recorded_at=5.0)
        row = store.select("decisions")[0]
        self.assertEqual(set(row), {"id", "run", "decided_at", "recorded_at", "kind", "subject", "claim",
                                    "claim_version", "rationale", "expected", "grade_after", "status", "outcome",
                                    "graded_at", "error", "verdict", "dedup_key"})
        self.assertEqual((row["status"], row["claim_version"], row["outcome"], row["graded_at"], row["error"],
                          row["verdict"]), ("open", 1, None, None, None, None))
        self.assertEqual(json.loads(row["claim"]), {"episode_id": "Z0-00@2026-01-01T00:00:00Z", "cause": "unknown"})
        self.assertEqual(row["recorded_at"], 5.0)

    def test_first_write_wins_nothing_is_overwritten(self):
        # inject: make record_decision an upsert (the second call would replace the claim)
        store = MemoryStore()
        make(store, claim={"cause": "first"}, rationale="first")
        make(store, claim={"cause": "second"}, rationale="second")
        row = store.select("decisions")[0]
        self.assertEqual(json.loads(row["claim"]), {"cause": "first"})
        self.assertEqual(row["rationale"], "first")

    def test_stamp_grade_once_changes_only_grading_fields(self):
        # inject: let stamp_grade overwrite a graded row, or also touch claim / expected / grade_after
        store = MemoryStore()
        did, _ = make(store, expected=1.5)
        before = store.select("decisions")[0]
        self.assertTrue(decisions.stamp_grade(store, did, outcome="hit", error=0.25, verdict="correct",
                                              graded_at=BASE + 4000))
        after = store.select("decisions")[0]
        self.assertEqual({k for k in after if after[k] != before[k]}, GRADING)
        self.assertEqual((after["status"], after["outcome"], after["error"], after["verdict"], after["graded_at"]),
                         ("graded", "hit", 0.25, "correct", BASE + 4000))
        self.assertFalse(decisions.stamp_grade(store, did, outcome="miss", error=9, verdict="wrong", graded_at=1))
        self.assertEqual(store.select("decisions")[0], after)  # all fields unchanged by the refused stamp
        self.assertFalse(decisions.stamp_grade(store, "no-such-id", "x", 0, "y", 1))

    def test_record_after_grading_is_still_a_no_op(self):
        # inject: dedup only against open decisions (a graded one then gets a duplicate)
        store = MemoryStore()
        did, _ = make(store)
        decisions.stamp_grade(store, did, "hit", 0.0, "ok", BASE + 5000)
        graded = store.select("decisions")[0]
        self.assertEqual(make(store), (did, False))
        self.assertEqual(store.select("decisions")[0], graded)


class TestStores(unittest.TestCase):
    def check_contract(self, store):
        store.insert("t", [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}])
        store.upsert("u", ("k",), [{"k": 1, "v": "old"}, {"k": 2, "v": "keep"}])
        store.upsert("u", ("k",), [{"k": 1, "v": "new"}])
        self.assertEqual(store.select("u"), [{"k": 1, "v": "new"}, {"k": 2, "v": "keep"}])
        self.assertEqual(store.select("t", {"b": "y"}), [{"a": 2, "b": "y"}])
        self.assertTrue(store.exists("t", a=1))
        self.assertFalse(store.exists("t", a=3))
        self.assertEqual(store.update_where("t", {"a": 2}, {"b": "z"}), 1)
        self.assertEqual(store.update_where("t", {"a": 99}, {"b": "z"}), 0)
        self.assertTrue(store.exists("t", b="z"))
        self.assertFalse(store.exists("t", b="y"))  # an index built before the update must not go stale
        rows = store.select("t")
        rows[0]["a"] = 1000  # select hands out copies
        self.assertTrue(store.exists("t", a=1))
        self.assertEqual(store.select("t")[0]["a"], 1)

    def test_memory_store_contract(self):
        # inject: return the live row dicts from select
        self.check_contract(MemoryStore())

    def test_jsonl_store_contract_and_restart(self):
        # inject: append upserts without the key tag (last-wins is lost on reload)
        with tempfile.TemporaryDirectory() as tmp:
            s = JsonlStore(tmp)
            self.check_contract(s)
            s.close()
            again = JsonlStore(tmp)  # a new process
            self.assertEqual(again.select("u"), [{"k": 1, "v": "new"}, {"k": 2, "v": "keep"}])
            self.assertEqual([r["b"] for r in again.select("t")], ["x", "z"])
            again.upsert("u", ("k",), [{"k": 2, "v": "later"}])
            again.close()
            self.assertEqual(JsonlStore(tmp).select("u", {"k": 2}), [{"k": 2, "v": "later"}])
            self.assertTrue((Path(tmp) / "u.jsonl").read_text().count("\n") >= 4)  # append-only: history stays

    def test_jsonl_store_ignores_a_torn_last_line(self):
        # inject: load an unterminated last line as a row
        with tempfile.TemporaryDirectory() as tmp:
            s = JsonlStore(tmp)
            s.insert("t", [{"a": 1}])
            s.close()
            with open(Path(tmp) / "t.jsonl", "a") as f:
                f.write('{"a": 2}')  # valid JSON, but the newline never made it
            self.assertEqual(JsonlStore(tmp).select("t"), [{"a": 1}])


class TestIngestDecisions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        write_gz(cls.dir / "zone0-000.jsonl.gz", interleaved(scenario()))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_decisions_per_episode_and_their_contents(self):
        # inject: change GRADE_AFTER_S from 3600
        _, store, _ = ingest_dir(self.dir, once=True)
        decs = {d["dedup_key"]: d for d in store.select("decisions")}
        self.assertEqual(sorted(decs), [
            "avoidable_reset:Z0-00:2026-01-01T00:00:00Z",
            "stuck_cause:Z0-00:2026-01-01T00:00:00Z",
            "stuck_cause:Z0-02:2026-01-01T00:00:00Z",
            "stuck_cause:Z1-00:2026-01-01T00:00:00Z"])
        cause = decs["stuck_cause:Z0-00:2026-01-01T00:00:00Z"]
        self.assertEqual((cause["decided_at"], cause["grade_after"], cause["expected"], cause["status"]),
                         (BASE + 30, BASE + 3630, None, "open"))
        self.assertEqual(json.loads(cause["claim"]), {
            "episode_id": "Z0-00@2026-01-01T00:00:00Z", "cause": "blocked_by_faulted", "blocker": "Z0-01",
            "blocker_faulted_s": 15, "cell": [0, 0]})
        reset = decs["avoidable_reset:Z0-00:2026-01-01T00:00:00Z"]
        self.assertEqual((reset["decided_at"], reset["grade_after"]), (BASE + 100, BASE + 3700))
        self.assertEqual(json.loads(reset["claim"]), {"episode_id": "Z0-00@2026-01-01T00:00:00Z",
                                                      "blocker": "Z0-01", "avoidable_s": 70})
        self.assertAlmostEqual(reset["expected"], 70 / 60)
        for d in decs.values():
            self.assertNotIn("\n", d["rationale"])
            self.assertEqual(d["run"], "r")

    def test_second_ingest_of_the_same_files_leaves_decisions_unchanged(self):
        # inject: drop the exists() check in record_decision
        ing, store, _ = ingest_dir(self.dir, once=True)
        first = [d["id"] for d in store.select("decisions")]
        n_evidence = len(store.select("evidence"))
        self.assertEqual(len(first), 4)
        ingest_dir(self.dir, store=store, once=True)  # same run: resumes, nothing left to read
        self.assertEqual(len(store.select("decisions")), 4)
        _, store, _ = ingest_dir(self.dir, store=store, run="other-run", once=True)  # re-detected from scratch
        self.assertEqual(len(store.select("stuck_episodes", {"run": "other-run"})), 3)
        self.assertEqual([d["id"] for d in store.select("decisions")], first)
        self.assertEqual(len(store.select("evidence")), n_evidence)
        self.assertTrue(all(d["run"] == "r" for d in store.select("decisions")))  # first write wins, run included

    def test_evidence_window_around_the_deciding_message(self):
        # inject: take 50 lines before the deciding message
        _, store, _ = ingest_dir(self.dir, once=True)
        decs = {d["dedup_key"]: d["id"] for d in store.select("decisions")}
        ev = {e["decision_id"]: e for e in store.select("evidence")}
        self.assertEqual(set(ev), set(decs.values()))
        for e in ev.values():
            self.assertLessEqual(e["line_count"], 50)
            self.assertEqual(e["line_count"], len(e["lines"]))
            self.assertEqual(e["bytes"], sum(len(x) for x in e["lines"]))
        e = ev[decs["stuck_cause:Z0-00:2026-01-01T00:00:00Z"]]
        parsed = [json.loads(x) for x in e["lines"]]
        self.assertTrue(all(p["serialNumber"].startswith("Z0-") for p in parsed))  # its zone only
        arrival = [(p["timestamp"], p["serialNumber"]) for p in parsed]
        self.assertEqual(arrival, sorted(arrival, key=lambda a: (a[0], a[1])))  # scenario order is (ts, serial)
        self.assertIn(("2026-01-01T00:00:30Z", "Z0-00"), arrival)  # the deciding message
        self.assertEqual(e["line_count"], 49)  # 24 before (stream edge), the deciding line, 24 after
        full = ev[decs["stuck_cause:Z0-02:2026-01-01T00:00:00Z"]]
        self.assertEqual(full["line_count"], 50)  # 25 before + deciding + 24 after: the bound
        self.assertEqual(e["zone"], "0")

    def test_evidence_at_the_end_of_input_has_fewer_lines_after(self):
        # inject: skip the end-of-input evidence flush in finish()
        sc = scenario(steps=8)  # the last batch is cut short: Z0-02's T_entry is the 7th of 8 steps
        with tempfile.TemporaryDirectory() as tmp:
            write_gz(Path(tmp) / "zone0-000.jsonl.gz", interleaved(sc))
            _, store, _ = ingest_dir(tmp, once=True)
        self.assertEqual(len(store.select("evidence")), len(store.select("decisions")))
        late = [e for e in store.select("evidence") if e["line_count"] < 49]
        self.assertTrue(late)


if __name__ == "__main__":
    unittest.main()

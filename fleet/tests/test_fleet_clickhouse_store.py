"""Tests for ClickHouseStore and schema.sql. No Docker, no network beyond a localhost stdlib HTTP server started here that
records every request and serves JSONEachRow out of an in-memory emulation of the tables it was told to create (it
reads fleet/sql/schema.sql through ClickHouseStore.ensure_schema, so the DDL is exercised too). One store-contract class
runs against MemoryStore, JsonlStore and the fake-backed ClickHouseStore. Each case names its red demonstration in an
`# inject:` comment. Real ClickHouse is covered by fleet/tests/integration_fleet_stack.py (run explicitly)."""
import json
import re
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "fleet", ROOT / "src", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fleet.tests.test_fleet_ingest import Clock, ingest_dir, interleaved, scenario, tables, write_gz  # noqa: E402
from fleet_analyser import clickhouse_store as chs  # noqa: E402
from fleet_analyser import decisions  # noqa: E402
from fleet_analyser.store import JsonlStore, MemoryStore, open_store  # noqa: E402

SCHEMA = ROOT / "fleet" / "sql" / "schema.sql"
HIDDEN = ("schema_version", "_ver", "_first")


# ------------------------------------------------------------------------------------------------ fake server
def parse_create(stmt):
    name = re.match(r"CREATE TABLE IF NOT EXISTS (\w+)", stmt).group(1)
    body = stmt.split("\n)\n", 1)
    cols = {}
    for ln in body[0].splitlines()[2:]:
        ln = ln.strip().rstrip(",")
        m = re.match(r"`?(\w+)`?\s+(.*)$", ln)
        cols[m.group(1)] = m.group(2)
    tail = body[1]
    engine = re.search(r"ENGINE = (\w+)(?:\((\w+)\))?", tail)
    order = re.search(r"ORDER BY (\([^)]*\)|[\w`]+)", tail).group(1).strip("()")
    ttl = re.search(r"TTL (.*?)(?:;|$)", tail, re.S)
    return dict(name=name, cols=cols, engine=engine.group(1), version=engine.group(2),
                order=[c.strip().strip("`") for c in order.split(",")], ttl=ttl.group(1).strip() if ttl else None)


def parse_literal(text, i):
    m = re.compile(r"'((?:[^'\\]|\\.)*)'").match(text, i)
    if m:
        return re.sub(r"\\(.)", r"\1", m.group(1)), m.end()
    m = re.compile(r"true|false|-?[0-9.e+-]+").match(text, i)
    v = m.group(0)
    return (v == "true" if v in ("true", "false") else (float(v) if re.search(r"[.e]", v) else int(v))), m.end()


def parse_where(text):
    conds, i = [], 0
    while i < len(text):
        m = re.compile(r"`(\w+)` (IS NULL|= )").match(text, i)
        col = m.group(1)
        if m.group(2) == "IS NULL":
            conds.append((col, None))
            i = m.end()
        else:
            v, i = parse_literal(text, m.end())
            conds.append((col, v))
        if text.startswith(" AND ", i):
            i += 5
    return conds


class FakeClickHouse:
    """Emulates the slice of ClickHouse's HTTP interface ClickHouseStore uses; records (params, body) of every request."""

    def __init__(self):
        self.tables, self.requests, self.fail = {}, [], None
        self.lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8")
                u = urlsplit(self.path)
                params = {k: v[0] for k, v in parse_qs(u.query).items()}
                with outer.lock:
                    outer.requests.append((params, body, dict(self.headers)))
                    try:
                        if outer.fail:
                            code, msg = outer.fail
                            raise _Http(code, msg)
                        out = outer.handle(params, body)
                        code = 200
                    except _Http as e:
                        code, out = e.code, e.msg
                data = out.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def sql(self):
        return [b.split("\n", 1)[0] if b.startswith("INSERT") else b for _, b, _ in self.requests]

    def handle(self, params, body):
        if body.startswith("CREATE DATABASE"):
            return ""
        if body.startswith("CREATE TABLE"):
            t = parse_create(body)
            self.tables.setdefault(t["name"], dict(t, rows=[]))
            return ""
        if body.startswith("INSERT INTO"):
            head, _, data = body.partition("\n")
            name = re.match(r"INSERT INTO `(\w+)` FORMAT JSONEachRow$", head).group(1)
            t = self.tables[name]
            for ln in data.splitlines():
                row = json.loads(ln)
                unknown = set(row) - set(t["cols"])
                if unknown:
                    raise _Http(400, f"Code: 117. Unknown field found while parsing JSONEachRow: {sorted(unknown)}")
                if "_ver" not in row or "schema_version" in row:
                    raise _Http(400, "Code: 117. _ver is required and schema_version is a DDL default")
                if ("_first" in t["cols"]) != ("_first" in row):
                    raise _Http(400, "Code: 117. _first is required exactly on the upsert tables")
                t["rows"].append(row)
            return ""
        m = re.match(r"SELECT (\* EXCEPT \(([\w, ]+)\)|[`\w, ]+) FROM `(\w+)`( FINAL)?(?: WHERE (.+?))?"
                     r"(?: ORDER BY (_ver|_first))?(?: LIMIT (\d+))? FORMAT JSONEachRow$", body, re.S)
        if not m:
            raise _Http(400, f"Code: 62. Syntax error (fake): {body[:200]}")
        if params.get("output_format_json_quote_64bit_integers") != "0":
            raise _Http(400, "the store must ask for unquoted 64-bit integers")
        proj, excepted, name, final, where, order, limit = m.groups()
        excepted = [c.strip() for c in excepted.split(",")] if excepted else None
        keep = None if excepted else [c.strip().strip("`") for c in proj.split(",")]
        t0 = self.tables[name]
        if excepted is not None and "_first" in t0["cols"] and order != "_first":
            raise _Http(400, "upsert tables must be read in first-write order (ORDER BY _first)")
        t = self.tables[name]
        rows = list(t["rows"])
        if final:
            if t["engine"] != "ReplacingMergeTree":
                raise _Http(400, "FINAL on a non-replacing table")
            best = {}
            for r in rows:
                k = tuple(json.dumps(r.get(c)) for c in t["order"])
                if k not in best or r["_ver"] > best[k]["_ver"]:
                    best[k] = r
            rows = list(best.values())
        for col, v in parse_where(where) if where else []:
            if col not in t["cols"]:
                raise _Http(400, f"Code: 47. Unknown identifier {col}")
            rows = [r for r in rows if r.get(col) == v]
        rows.sort(key=lambda r: r[order or "_ver"])
        if limit:
            rows = rows[:int(limit)]
        if keep is not None:
            return "".join(json.dumps({k: r[k] for k in keep}) + "\n" for r in rows)
        if sorted(excepted) != sorted(c for c in ("schema_version", "_ver", "_first") if c in t["cols"]):
            raise _Http(400, f"the store must hide exactly the DDL-added columns, got {excepted}")
        return "".join(json.dumps({k: v for k, v in r.items() if k not in HIDDEN}) + "\n" for r in rows)


class _Http(Exception):
    def __init__(self, code, msg):
        self.code, self.msg = code, msg


def fake_store(test):
    fake = FakeClickHouse()
    test.addCleanup(fake.stop)
    st = chs.ClickHouseStore(fake.url, database="fleet")
    st.ensure_schema()
    return fake, st


def schema_tables():
    return {t["name"]: t for t in map(parse_create, chs.split_statements(SCHEMA.read_text()))}


# ------------------------------------------------------------------------------------------------ the contract
def ep_row(eid, resolution="open", cell=(1, 2), **kw):
    row = dict(run="r", episode_id=eid, zone="0", robot="Z0-01", order_id="o1", start=100, start_iso="a", t_entry=130,
               cell=list(cell), cause="unknown", blocker=None, blocker_faulted_s=None, end=None, duration_s=None,
               resolution=resolution, avoidable=False, avoidable_s=None, left_censored=False)
    row.update(kw)
    return row


def contract_sequence(st):
    """One fixed call sequence; returns everything observable, rows in the order select() returned them."""
    obs = {}
    st.insert("transitions", [dict(run="r", zone="0", robot="Z0-01", ts=100 + i, from_state="IDLE", to_state="MOVING",
                                   cell=[i, 2], order_id="o1") for i in range(3)])
    obs["transitions"] = st.select("transitions")
    obs["transitions_where"] = st.select("transitions", {"robot": "Z0-01", "ts": 101})
    st.upsert("stuck_episodes", ("run", "episode_id"), [ep_row("e1"), ep_row("e2")])
    st.upsert("stuck_episodes", ("run", "episode_id"),
              [ep_row("e1", resolution="moved", end=190, duration_s=90, cell=(1, 2))])
    obs["e1"] = st.select("stuck_episodes", {"run": "r", "episode_id": "e1"})
    obs["episodes"] = st.select("stuck_episodes")  # e1 was replaced after e2 arrived: still [e1, e2]
    obs["open"] = st.select("stuck_episodes", {"resolution": "open"})
    obs["null_blocker"] = [r["episode_id"] for r in st.select("stuck_episodes", {"blocker": None})]
    st.insert("rejects", [dict(run="r", source="file", file="f's\\q", offset=0, reason="json", raw="x'\"\\n")])
    obs["rejects"] = st.select("rejects", {"file": "f's\\q"})
    st.upsert("ingest_runs", ("run",), [dict(run="r", glob="g", emit_ledger=None, emit_status=None, emit_config=None,
                                             expected_messages=None, updated_at=1.5)])
    st.upsert("ingest_runs", ("run",), [dict(run="r", glob="g", emit_ledger="/x", emit_status="running",
                                             emit_config={"rate": "flat", "n": [1, 2]}, expected_messages=720,
                                             updated_at=2.5)])
    obs["runs"] = st.select("ingest_runs", {"run": "r"})
    st.insert("evidence", [dict(decision_id="d", run="r", zone="0", lines=["a\n", "b\n"], line_count=2, bytes=4)])
    obs["evidence"] = st.select("evidence")
    ids = []
    for subject in ("Z0-01", "Z0-02"):
        did, created = decisions.record_decision(
            st, run="r", kind="stuck_cause", subject=subject, start_iso="2026-01-01T00:00:00Z", decided_at=130,
            claim={"cause": "unknown"}, rationale="why", expected=None, grade_after=3730, recorded_at=5.5)
        ids.append(did)
        obs[f"created_{subject}"] = created
    obs["again"] = decisions.record_decision(
        st, run="r", kind="stuck_cause", subject="Z0-01", start_iso="2026-01-01T00:00:00Z", decided_at=999,
        claim={}, rationale="second", expected=1, grade_after=1, recorded_at=9.9)
    obs["exists"] = (st.exists("decisions", dedup_key="stuck_cause:Z0-01:2026-01-01T00:00:00Z"),
                     st.exists("decisions", dedup_key="nope"), st.exists("decisions", id=ids[0], status="open"))
    obs["decisions_before"] = st.select("decisions")
    obs["stamp1"] = decisions.stamp_grade(st, ids[0], {"ok": True}, None, "right", 4000.5)
    obs["stamp2"] = decisions.stamp_grade(st, ids[0], "other", "e", "wrong", 5000)
    obs["raw_update"] = (st.update_where("decisions", {"id": ids[1], "status": "open"},
                                         dict(status="graded", outcome="x", error=None, verdict="v", graded_at=1)),
                         st.update_where("decisions", {"id": ids[1], "status": "open"}, dict(status="graded")),
                         st.update_where("decisions", {"id": "missing", "status": "open"}, dict(status="graded")))
    obs["decisions_after"] = st.select("decisions")
    obs["open_after"] = st.select("decisions", {"status": "open"})
    obs["graded_after"] = [d["subject"] for d in st.select("decisions", {"status": "graded"})]
    obs["one"] = st.select("decisions", {"id": ids[0]})
    obs["exists_graded"] = (st.exists("decisions", id=ids[0], status="graded"),
                            st.exists("decisions", id=ids[0], status="open"))
    obs["ids"] = ids
    return obs


class StoreContract:
    def make_store(self):
        raise NotImplementedError

    def test_same_results_as_memory_store_for_the_same_call_sequence(self):
        # inject: ClickHouseStore.select returns the schema_version column, or reads an upsert table without FINAL;
        # JsonlStore.update_where returns 0 without applying the update
        got = contract_sequence(self.make_store())
        want = contract_sequence(MemoryStore())
        self.assertEqual(got, want)

    def test_contract_facts_hold_on_their_own(self):
        # inject: ClickHouseStore versions every row with the same _ver, or reads upsert tables without FINAL
        obs = contract_sequence(self.make_store())
        self.assertEqual([{k: v for k, v in r.items() if k in ("resolution", "end", "duration_s")} for r in obs["e1"]],
                         [dict(resolution="moved", end=190, duration_s=90)])  # one row, the later values
        self.assertEqual([r["episode_id"] for r in obs["open"]], ["e2"])
        self.assertEqual(obs["null_blocker"], ["e1", "e2"])  # first-write order survives the replacement of e1
        self.assertEqual([r["episode_id"] for r in obs["episodes"]], ["e1", "e2"])
        self.assertEqual(obs["runs"][0]["expected_messages"], 720)
        self.assertEqual(obs["runs"][0]["emit_config"], {"rate": "flat", "n": [1, 2]})
        self.assertEqual(obs["rejects"][0]["raw"], "x'\"\\n")
        self.assertEqual((obs["created_Z0-01"], obs["created_Z0-02"], obs["again"][1]), (True, True, False))
        self.assertEqual(len(obs["decisions_before"]), 2)  # first write wins: the second Z0-01 was a no-op
        self.assertEqual(obs["decisions_before"][0]["rationale"], "why")
        self.assertEqual((obs["stamp1"], obs["stamp2"]), (True, False))
        self.assertEqual(obs["raw_update"], (1, 0, 0))
        d0 = obs["one"][0]
        self.assertEqual((d0["status"], d0["outcome"], d0["verdict"], d0["graded_at"], d0["error"]),
                         ("graded", {"ok": True}, "right", 4000.5, None))  # the second stamp changed nothing
        changed = {k for k in d0 if d0[k] != next(d for d in obs["decisions_before"] if d["id"] == d0["id"])[k]}
        self.assertEqual(changed, {"status", "outcome", "verdict", "graded_at"})
        self.assertEqual(set(d0), set(obs["decisions_before"][0]))  # no extra keys (schema_version, _ver, grade cols)
        self.assertEqual(obs["open_after"], [])
        self.assertEqual(obs["exists_graded"], (True, False))


class TestMemoryContract(StoreContract, unittest.TestCase):
    def make_store(self):
        return MemoryStore()


class TestJsonlContract(StoreContract, unittest.TestCase):
    def make_store(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        st = JsonlStore(tmp.name)
        self.addCleanup(st.close)
        return st


class TestClickHouseContract(StoreContract, unittest.TestCase):
    def make_store(self):
        return fake_store(self)[1]


# ------------------------------------------------------------------------------------------------ the HTTP layer
class TestClickHouseSql(unittest.TestCase):
    def setUp(self):
        self.fake, self.st = fake_store(self)
        self.fake.requests.clear()

    def test_insert_is_json_each_row_with_a_strictly_increasing_version_and_no_schema_version(self):
        # inject: drop the `+ 1` bump in _next_ver (equal ticks give equal versions), or send schema_version
        with mock.patch.object(chs.time, "time_ns", return_value=1_000):  # a clock that never moves
            self.st.upsert("ingest_runs", ("run",), [dict(run="r", glob="a", updated_at=1.0)])
            self.st.upsert("ingest_runs", ("run",), [dict(run="r", glob="b", updated_at=2.0),
                                                     dict(run="r", glob="c", updated_at=3.0)])
        reqs = [b for _, b, _ in self.fake.requests if b.startswith("INSERT")]
        self.assertEqual(len(reqs), 2)
        self.assertTrue(all(b.startswith("INSERT INTO `ingest_runs` FORMAT JSONEachRow\n") for b in reqs))
        rows = [json.loads(ln) for b in reqs for ln in b.splitlines()[1:]]
        self.assertEqual([r["glob"] for r in rows], ["a", "b", "c"])
        vers = [r["_ver"] for r in rows]
        self.assertEqual(vers, sorted(set(vers)))  # strictly increasing
        self.assertEqual({r["_first"] for r in rows}, {vers[0]})  # every version of the key carries the first write
        self.assertTrue(all("schema_version" not in r for r in rows))
        self.assertEqual(self.st.select("ingest_runs")[0]["glob"], "c")  # the later upsert wins

    def test_first_write_order_survives_a_new_process_and_replacements(self):
        # inject: start a fresh _first for a key already in the table (skip seeding from the table), or order by _ver
        key = ("run", "episode_id")
        self.st.upsert("stuck_episodes", key, [ep_row("e1"), ep_row("e2")])
        again = chs.ClickHouseStore(self.fake.url, database="fleet")  # a restarted writer: empty in-process state
        again.upsert("stuck_episodes", key, [ep_row("e1", resolution="moved"), ep_row("e3")])
        again.upsert("stuck_episodes", key, [ep_row("e2", resolution="moved")])
        got = [(r["episode_id"], r["resolution"]) for r in again.select("stuck_episodes")]
        self.assertEqual(got, [("e1", "moved"), ("e2", "moved"), ("e3", "open")])
        seed = [b for _, b, _ in self.fake.requests if b.startswith("SELECT `run`, `episode_id`, _first FROM")]
        self.assertEqual(len(seed), 2)  # once per store instance and table, not once per write
        with self.assertRaises(ValueError):
            again.upsert("stuck_episodes", ("run",), [ep_row("e4")])  # the key must be the DDL's ORDER BY

    def test_select_sql_final_only_for_upsert_tables_and_unquoted_64_bit(self):
        # inject: drop FINAL from the upsert-table query, or add it for every table
        self.st.select("ingest_runs", {"run": "r"})
        self.st.select("transitions", {"robot": "Z0-01", "ts": 5})
        self.st.exists("stuck_episodes", run="r", episode_id="e")
        sql = self.fake.sql()
        sql = [q for q in sql if not q.startswith("INSERT")]
        self.assertEqual(sql[0], "SELECT * EXCEPT (schema_version, _ver, _first) FROM `ingest_runs` FINAL WHERE "
                                 "`run` = 'r' ORDER BY _first FORMAT JSONEachRow")
        self.assertEqual(sql[1], "SELECT * EXCEPT (schema_version, _ver) FROM `transitions` WHERE `robot` = 'Z0-01' "
                                 "AND `ts` = 5 ORDER BY _ver FORMAT JSONEachRow")
        self.assertIn("FROM `stuck_episodes` FINAL WHERE `run` = 'r' AND `episode_id` = 'e' ORDER BY _first LIMIT 1",
                      sql[2])
        for params, _, _ in self.fake.requests:
            self.assertEqual(params["output_format_json_quote_64bit_integers"], "0")
            self.assertEqual(params["database"], "fleet")

    def test_string_literals_are_escaped_and_none_is_is_null(self):
        # inject: stop escaping backslash or quote in _str_lit, or render None as = NULL
        self.st.insert("rejects", [dict(run="r", source="s", file="a'b\\c", offset=1, reason="x", raw="y")])
        self.fake.requests.clear()
        self.assertEqual(len(self.st.select("rejects", {"file": "a'b\\c"})), 1)
        self.assertIn("`file` = 'a\\'b\\\\c'", self.fake.sql()[0])
        self.st.select("ingest_runs", {"emit_status": None})
        self.assertIn("`emit_status` IS NULL", self.fake.sql()[1])

    def test_decision_select_reads_grades_by_id_and_stamps_only_when_ungraded(self):
        # inject: write the grade even when decision_grades already has one for the id
        did, _ = decisions.record_decision(self.st, run="r", kind="stuck_cause", subject="s", start_iso="t",
                                           decided_at=1, claim={}, rationale="x", expected=None, grade_after=2)
        self.fake.requests.clear()
        self.assertTrue(decisions.stamp_grade(self.st, did, "o", None, "v", 3))
        self.assertEqual(self.fake.tables["decision_grades"]["rows"][0]["id"], did)
        self.assertEqual(len(self.fake.tables["decision_grades"]["rows"]), 1)
        self.assertEqual(self.fake.tables["decisions"]["rows"][0]["status"], "open")  # decisions rows never updated
        # an update_where that matches an already graded decision (no status in eq) records no second grade
        self.assertEqual(self.st.update_where("decisions", {"id": did}, dict(status="graded", verdict="again")), 0)
        self.assertEqual(len(self.fake.tables["decision_grades"]["rows"]), 1)
        with self.assertRaises(ValueError):
            self.st.update_where("decisions", {"id": did}, dict(claim="rewritten"))
        with self.assertRaises(NotImplementedError):
            self.st.update_where("stuck_episodes", {"run": "r"}, dict(resolution="x"))

    def test_http_errors_and_unreachable_server_raise_with_the_server_message(self):
        # inject: swallow the HTTPError and return an empty result
        self.fake.fail = (500, "Code: 241. Memory limit exceeded")
        with self.assertRaises(chs.ClickHouseError) as cm:
            self.st.select("transitions")
        self.assertIn("Memory limit exceeded", str(cm.exception))
        self.fake.fail = None
        dead = chs.ClickHouseStore("http://127.0.0.1:1", timeout=1)
        with self.assertRaises(chs.ClickHouseError):
            dead.select("transitions")

    def test_open_store_parses_clickhouse_urls_and_applies_the_schema(self):
        # inject: drop the clickhouse:// branch in open_store, or skip ensure_schema in it
        port = self.fake.url.rsplit(":", 1)[1]
        st = open_store(f"clickhouse://127.0.0.1:{port}/other", "r")
        self.assertIsInstance(st, chs.ClickHouseStore)
        self.assertEqual(st.database, "other")
        self.assertTrue(any(b.startswith("CREATE DATABASE IF NOT EXISTS `other`") for _, b, _ in self.fake.requests))
        self.assertEqual(set(self.fake.tables), set(schema_tables()))
        with self.assertRaises(ValueError):
            open_store("clickhouse:///nohost", "r")
        with self.assertRaises(ValueError):
            open_store("postgres://x", "r")
        s2 = chs.ClickHouseStore.from_spec("clickhouse://u:p%40ss@h/db")
        self.assertEqual((s2.url, s2.database, s2._auth), ("http://h:18123", "db", ("u", "p@ss")))


# ------------------------------------------------------------------------------------------------ DDL vs S5B1
class RecordingStore(MemoryStore):
    """Records, per table, the union of columns written and the key columns of every upsert."""

    def __init__(self):
        super().__init__()
        self.cols, self.keys = {}, {}

    def insert(self, table, rows):
        rows = list(rows)
        for r in rows:
            self.cols.setdefault(table, set()).update(r)
        super().insert(table, rows)

    def upsert(self, table, key_cols, rows):
        rows = list(rows)
        for r in rows:
            self.cols.setdefault(table, set()).update(r)
        self.keys.setdefault(table, set()).add(tuple(key_cols))
        super().upsert(table, key_cols, rows)


class TestSchema(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        sc = scenario(60)
        lines = interleaved(sc)
        write_gz(self.dir / "zone0-000.jsonl.gz", lines + [b"not json\n"])
        self.rec = RecordingStore()
        ingest_dir(self.dir, self.rec, clock=Clock(), once=True)
        self.schema = schema_tables()

    def test_every_table_and_column_s5b1_writes_is_in_the_ddl_with_the_upsert_key_as_order_by(self):
        # inject: rename a column in schema.sql, drop a table, or change an ORDER BY away from the upsert key
        written = {"decisions", "transitions", "rejects", "state_sample", "evidence", "stuck_episodes",
                   "ingest_checkpoints", "ingest_files", "ingest_ledger", "ingest_runs"}
        self.assertEqual(set(self.rec.cols), written)
        for table, cols in self.rec.cols.items():
            ddl = self.schema[table]
            self.assertEqual(set(ddl["cols"]) - set(HIDDEN), cols, table)
            self.assertIn("schema_version", ddl["cols"])
            self.assertIn("DEFAULT", ddl["cols"]["schema_version"])
        self.assertIn("decision_grades", self.schema)
        self.assertIn("schema_version", self.schema["decision_grades"]["cols"])
        for table, keys in self.rec.keys.items():
            (key,) = keys  # one key per table, as S5B1 passes it
            ddl = self.schema[table]
            self.assertEqual((ddl["engine"], ddl["version"]), ("ReplacingMergeTree", "_ver"), table)
            self.assertEqual(ddl["order"], list(key), table)
            self.assertTrue(set(key) <= set(ddl["cols"]))
        for table in written - set(self.rec.keys):
            self.assertEqual(self.schema[table]["engine"], "MergeTree", table)
        self.assertEqual(self.schema["decision_grades"]["order"], ["id"])
        self.assertEqual(self.schema["decision_grades"]["engine"], "ReplacingMergeTree")
        self.assertEqual(set(chs.UPSERT_TABLES), set(self.rec.keys) | {"decision_grades", "ingest_consumer_lag"})
        for table, key in chs.UPSERT_KEYS.items():  # the store's key table is the DDL's ORDER BY
            self.assertEqual(self.schema[table]["order"], list(key), table)
            self.assertIn("_first", self.schema[table]["cols"], table)
        for table in set(self.schema) - set(chs.UPSERT_KEYS):
            self.assertNotIn("_first", self.schema[table]["cols"], table)

    def test_results_table_layout(self):
        # inject: drop the `text` column, make value Nullable, give results a _first column, or drop schema_version
        r = self.schema["results"]
        self.assertEqual(list(r["cols"]), ["kind", "run", "key", "value", "text", "loaded_at", "schema_version", "_ver"])
        self.assertEqual((r["cols"]["value"], r["cols"]["text"]), ("Float64", "Nullable(String)"))
        self.assertIn("DEFAULT", r["cols"]["schema_version"])
        self.assertEqual((r["engine"], r["order"]), ("MergeTree", ["kind", "run", "key"]))
        self.assertNotIn("results", chs.UPSERT_KEYS)
        fake, st = fake_store(self)
        st.insert("results", [dict(kind="score", run="r", key="a.b", value=1.5, text=None, loaded_at=1.0)])
        self.assertEqual(st.select("results", {"run": "r"}),
                         [dict(kind="score", run="r", key="a.b", value=1.5, text=None, loaded_at=1.0)])

    def test_state_sample_has_a_seven_day_ttl_and_only_it(self):
        # inject: change INTERVAL 7 DAY, or add a TTL to another table
        self.assertEqual(self.schema["state_sample"]["ttl"], "toDateTime(ts) + INTERVAL 7 DAY")
        self.assertEqual([t for t, d in self.schema.items() if d["ttl"]], ["state_sample"])

    def test_ingest_through_the_fake_clickhouse_equals_ingest_into_memory(self):
        # inject: ClickHouseStore drops the last row of every insert request, or returns upsert rows without FINAL
        fake, st = fake_store(self)
        _, mem, _ = ingest_dir(self.dir, MemoryStore(), clock=Clock(), once=True)
        _, ch, _ = ingest_dir(self.dir, st, clock=Clock(), once=True)
        a, b = tables(mem), tables(ch)
        self.assertGreater(len(a["stuck_episodes"]), 0)
        self.assertGreater(len(a["decisions"]), 0)
        self.assertEqual(a, b)
        # every table, rows in the order select() returns them (first-write order), nothing sorted or left out
        for t in ("transitions", "rejects", "state_sample", "evidence", "decisions", "stuck_episodes",
                  "ingest_checkpoints", "ingest_files", "ingest_ledger", "ingest_runs"):
            self.assertEqual(mem.select(t), ch.select(t), t)
            self.assertGreater(len(mem.select(t)), 0, t)
        self.assertGreater(len(mem.select("stuck_episodes")), 1)  # open rows were replaced after later episodes opened


if __name__ == "__main__":
    unittest.main()

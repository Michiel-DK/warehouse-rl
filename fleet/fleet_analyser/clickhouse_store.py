"""ClickHouse implementation of the S5B Store interface, over the HTTP interface with the standard library only.

`clickhouse://[user:password@]host[:port]/database` (port default 18123, this repo's compose mapping). Every request is
one POST to `/?database=<db>&...`: `INSERT INTO t FORMAT JSONEachRow` followed by one JSON object per line, and
`SELECT ... FORMAT JSONEachRow` answered with one JSON object per line. The DDL is fleet/sql/schema.sql.

Contract: for the same call sequence select / exists / update_where return what MemoryStore returns, with these
documented differences. (1) Row order: insert-only tables come back in insert order (the `_ver` sequence); upsert tables
in last-write order, not first-write order. (2) Columns the DDL adds (`schema_version`, `_ver`) are never returned.
(3) A missing column comes back as NULL / the column default (MemoryStore omits the key); S5B1 always writes full rows.

Upsert tables are ReplacingMergeTree(_ver) ordered by the upsert key and read with FINAL. `_ver` is a per-process
strictly increasing integer (nanosecond clock, bumped by one on a tie), so within one writer the later upsert always wins.

`decisions` is insert-only and first-write-wins (record_decision checks the dedup_key before inserting). A grading stamp
(`update_where("decisions", ...)`, as decisions.stamp_grade does) is written to `decision_grades` and only if the decision
has no grade yet, so for a single writer a decision is graded at most once; `select("decisions")` returns each decision
overlaid with its grade. Only status / outcome / error / verdict / graded_at can be changed. Check-then-insert is not
atomic: two concurrent writers can both stamp.

Cells that are lists / dicts (and the grade values outcome / error / verdict) are stored as JSON text and parsed back.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .store import Store

DEFAULT_PORT = 18123
DEFAULT_DATABASE = "fleet"
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "sql" / "schema.sql"
HIDDEN = ("schema_version", "_ver")
GRADE_FIELDS = ("status", "outcome", "error", "verdict", "graded_at")
# (table, column) -> the cell is JSON text in ClickHouse: dumps on write, loads on read (NULL stays None).
JSON_COLS = frozenset({
    ("transitions", "cell"), ("stuck_episodes", "cell"), ("evidence", "lines"), ("ingest_runs", "emit_config"),
    ("decisions", "outcome"), ("decisions", "error"), ("decisions", "verdict"),
    ("decision_grades", "outcome"), ("decision_grades", "error"), ("decision_grades", "verdict"),
})
INSERT_BATCH = 5000


class ClickHouseError(RuntimeError):
    pass


def _ident(name):
    if not name.replace("_", "a").isalnum():
        raise ValueError(f"bad identifier {name!r}")
    return f"`{name}`"


def _str_lit(s):
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def split_statements(sql):
    """Statements of a schema file: `--` comment lines dropped, split on `;`."""
    body = "\n".join(ln for ln in sql.splitlines() if not ln.lstrip().startswith("--"))
    return [s.strip() for s in body.split(";") if s.strip()]


class ClickHouseStore(Store):
    def __init__(self, url, database=DEFAULT_DATABASE, user=None, password=None, timeout=60.0):
        self.url = url.rstrip("/")
        self.database = database
        self.timeout = timeout
        self._auth = (user, password) if user else None
        self._last_ver = 0

    @classmethod
    def from_spec(cls, spec):
        """spec = 'clickhouse://[user:password@]host[:port]/database'."""
        u = urllib.parse.urlsplit(spec)
        if u.scheme != "clickhouse" or not u.hostname:
            raise ValueError(f"--store must be clickhouse://host[:port]/db, got {spec!r}")
        db = u.path.strip("/") or DEFAULT_DATABASE
        return cls(f"http://{u.hostname}:{u.port or DEFAULT_PORT}", db, urllib.parse.unquote(u.username or "") or None,
                   urllib.parse.unquote(u.password or "") or None)

    # ------------------------------------------------------------------ HTTP
    def _post(self, body, database=True, params=None):
        q = {"output_format_json_quote_64bit_integers": "0", "input_format_null_as_default": "0",
             "wait_end_of_query": "1"}
        if database:
            q["database"] = self.database
        q.update(params or {})
        req = urllib.request.Request(f"{self.url}/?{urllib.parse.urlencode(q)}", data=body.encode("utf-8"),
                                     method="POST")
        if self._auth:
            req.add_header("X-ClickHouse-User", self._auth[0])
            req.add_header("X-ClickHouse-Key", self._auth[1] or "")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            raise ClickHouseError(f"clickhouse {e.code}: {e.read().decode('utf-8', 'replace').strip()[:500]}") from e
        except urllib.error.URLError as e:
            raise ClickHouseError(f"clickhouse unreachable at {self.url}: {e.reason}") from e

    def ensure_schema(self, path=SCHEMA_PATH):
        """CREATE DATABASE IF NOT EXISTS, then every statement of schema.sql (all IF NOT EXISTS: idempotent)."""
        self._post(f"CREATE DATABASE IF NOT EXISTS {_ident(self.database)}", database=False)
        for stmt in split_statements(Path(path).read_text()):
            self._post(stmt)

    # ------------------------------------------------------------------ encoding
    def _next_ver(self):
        self._last_ver = max(time.time_ns(), self._last_ver + 1)
        return self._last_ver

    @staticmethod
    def _enc(table, col, v):
        if (table, col) in JSON_COLS and v is not None:
            return json.dumps(v, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return v

    @staticmethod
    def _dec(table, col, v):
        if (table, col) in JSON_COLS and v is not None:
            return json.loads(v)
        return v

    def _lit(self, table, col, v):
        v = self._enc(table, col, v)
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return repr(v)
        if isinstance(v, str):
            return _str_lit(v)
        raise ValueError(f"cannot use {v!r} in a ClickHouse equality ({table}.{col})")

    def _where(self, table, eq):
        parts = []
        for col, v in (eq or {}).items():
            parts.append(f"{_ident(col)} IS NULL" if v is None else f"{_ident(col)} = {self._lit(table, col, v)}")
        return (" WHERE " + " AND ".join(parts)) if parts else ""

    def _rows_out(self, table, text):
        out = []
        for line in text.splitlines():
            if not line.strip():
                continue
            row = {k: self._dec(table, k, v) for k, v in json.loads(line).items() if k not in HIDDEN}
            out.append(row)
        return out

    def _query(self, table, eq, final, limit=None):
        sql = (f"SELECT * EXCEPT (schema_version, _ver) FROM {_ident(table)}{' FINAL' if final else ''}"
               f"{self._where(table, eq)} ORDER BY _ver{f' LIMIT {limit}' if limit else ''} FORMAT JSONEachRow")
        return self._rows_out(table, self._post(sql))

    def _write(self, table, rows):
        rows = list(rows)
        for i in range(0, len(rows), INSERT_BATCH):
            lines = []
            for r in rows[i:i + INSERT_BATCH]:
                obj = {k: self._enc(table, k, v) for k, v in r.items()}
                obj["_ver"] = self._next_ver()
                lines.append(json.dumps(obj, separators=(",", ":"), allow_nan=False))
            self._post(f"INSERT INTO {_ident(table)} FORMAT JSONEachRow\n" + "\n".join(lines) + "\n")

    # ------------------------------------------------------------------ Store interface
    def insert(self, table, rows):
        self._write(table, rows)

    def upsert(self, table, key_cols, rows):
        # The table's ORDER BY must be exactly key_cols (schema.sql); a different key would silently not dedupe.
        self._write(table, rows)

    def select(self, table, where=None):
        if table == "decisions":
            return self._select_decisions(where)
        return self._query(table, where, final=self._is_upsert(table))

    def exists(self, table, **eq):
        if table == "decisions" and any(c in GRADE_FIELDS for c in eq):
            return bool(self._select_decisions(eq))
        return bool(self._query(table, eq, final=self._is_upsert(table), limit=1))

    @staticmethod
    def _is_upsert(table):
        return table in UPSERT_TABLES

    def _select_decisions(self, where):
        where = dict(where or {})
        d_where = {c: v for c, v in where.items() if c not in GRADE_FIELDS}
        g_where = {c: v for c, v in where.items() if c in GRADE_FIELDS}
        rows = self._query("decisions", d_where, final=False)
        if not rows:
            return []
        grades = {g["id"]: g for g in self._query("decision_grades", {"id": d_where["id"]} if "id" in d_where else None,
                                                  final=True)}
        out = []
        for r in rows:
            g = grades.get(r["id"])
            if g:
                r.update({k: g[k] for k in GRADE_FIELDS if k in g})
            if all(r.get(c) == v for c, v in g_where.items()):
                out.append(r)
        return out

    def update_where(self, table, eq, values):
        if table != "decisions":
            raise NotImplementedError(f"update_where is only implemented for decisions, not {table!r}")
        bad = sorted(set(values) - set(GRADE_FIELDS))
        if bad:
            raise ValueError(f"decisions are immutable except {GRADE_FIELDS}; refused to set {bad}")
        hit = self._select_decisions(eq)
        if not hit:
            return 0
        have = {g["id"] for g in self._query("decision_grades", None, final=True)} if len(hit) > 1 else None
        stamped = 0
        for r in hit:
            if have is not None:
                already = r["id"] in have
            else:
                already = bool(self._query("decision_grades", {"id": r["id"]}, final=True, limit=1))
            if already:
                continue  # graded at most once: a stamp is recorded only if the decision has none
            self._write("decision_grades", [dict({"id": r["id"], "status": "open"}, **values)])
            stamped += 1
        return stamped


UPSERT_TABLES = frozenset({"stuck_episodes", "ingest_ledger", "ingest_files", "ingest_checkpoints", "ingest_runs",
                           "decision_grades", "ingest_consumer_lag"})

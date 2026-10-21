"""Row stores for the S5B ingest: one interface, two implementations (a ClickHouse store joins in a later lane).

Interface (all rows are plain dicts of JSON-able values):
  insert(table, rows)                  append rows
  upsert(table, key_cols, rows)        replace the row with the same key (or append it)
  select(table, where=None)            rows (copies) in first-write order; where = dict of equalities or None
  exists(table, **eq)                  True when a row matches all equalities
  update_where(table, eq, values)      set `values` on every row matching `eq`; returns the number of rows changed
Nothing in detector / ingest / ledger may depend on which store is behind this interface.
"""
import json
from bisect import bisect_left
from pathlib import Path


class Store:
    def insert(self, table, rows):
        raise NotImplementedError

    def upsert(self, table, key_cols, rows):
        raise NotImplementedError

    def select(self, table, where=None):
        raise NotImplementedError

    def exists(self, table, **eq):
        raise NotImplementedError

    def update_where(self, table, eq, values):
        raise NotImplementedError

    def close(self):
        pass


def _hk(v):
    """Hashable form of a cell value (lists/dicts from JSON become canonical strings)."""
    if isinstance(v, (list, dict)):
        return json.dumps(v, sort_keys=True)
    return v


class MemoryStore(Store):
    """Dict-backed store. Equality lookups build an index per column tuple on first use and keep it current."""

    def __init__(self):
        self._rows = {}  # table -> list of row dicts (upserts replace in place)
        self._idx = {}  # (table, cols) -> {value tuple -> [rows]}, every bucket sorted by row seq (= table order)
        self._seq = {}  # id(row) -> position of first insert (monotone, never changes; rows are never deleted)
        self._next_seq = 0

    def _table(self, table):
        return self._rows.setdefault(table, [])

    def _index(self, table, cols):
        key = (table, cols)
        idx = self._idx.get(key)
        if idx is None:
            idx = {}
            for r in self._table(table):
                idx.setdefault(tuple(_hk(r.get(c)) for c in cols), []).append(r)
            self._idx[key] = idx
        return idx

    def _add_to_indices(self, table, row):
        for (t, cols), idx in self._idx.items():
            if t == table:
                idx.setdefault(tuple(_hk(row.get(c)) for c in cols), []).append(row)

    def _append_row(self, table, row):
        self._seq[id(row)] = self._next_seq
        self._next_seq += 1
        self._table(table).append(row)
        self._add_to_indices(table, row)

    def _keys_of(self, table, row, only=None):
        """{cols: key tuple} of `row` for every index of `table` (only those whose cols meet `only`, when given)."""
        return {cols: tuple(_hk(row.get(c)) for c in cols) for (t, cols) in self._idx
                if t == table and (only is None or only.intersection(cols))}

    def _move(self, table, row, old_keys):
        """Re-file `row` in every index whose key changed, by identity, keeping each bucket seq-sorted."""
        s = self._seq[id(row)]
        seq_of = lambda r: self._seq[id(r)]  # noqa: E731
        for cols, old in old_keys.items():
            new = tuple(_hk(row.get(c)) for c in cols)
            if new == old:
                continue
            idx = self._idx[(table, cols)]
            bucket = idx[old]
            pos = bisect_left(bucket, s, key=seq_of)
            assert bucket[pos] is row
            del bucket[pos]
            if not bucket:
                del idx[old]
            bucket = idx.setdefault(new, [])
            bucket.insert(bisect_left(bucket, s, key=seq_of), row)

    def _lookup(self, table, eq):
        if not eq:
            return list(self._table(table))
        cols = tuple(sorted(eq))
        return list(self._index(table, cols).get(tuple(_hk(eq[c]) for c in cols), []))

    def insert(self, table, rows):
        for r in rows:
            self._append_row(table, dict(r))

    def upsert(self, table, key_cols, rows):
        cols = tuple(key_cols)
        for r in rows:
            r = dict(r)
            idx = self._index(table, cols)
            hit = idx.get(tuple(_hk(r.get(c)) for c in cols))
            if hit:
                old = hit[0]
                before = self._keys_of(table, old)
                old.clear()
                old.update(r)
                self._move(table, old, before)
            else:
                self._append_row(table, r)

    def select(self, table, where=None):
        return [dict(r) for r in self._lookup(table, where)]

    def exists(self, table, **eq):
        return bool(self._lookup(table, eq))

    def update_where(self, table, eq, values):
        hit = self._lookup(table, eq)
        if not hit:
            return 0
        for r in hit:
            before = self._keys_of(table, r, set(values))
            r.update(values)
            self._move(table, r, before)
        return len(hit)


class JsonlStore(Store):
    """One append-only <table>.jsonl per table under `directory`.

    insert appends rows; upsert appends the row tagged with its key columns and the last row per key wins on read;
    update_where appends an update record that is replayed on read. A table is read from disk at most once per process
    (lazily, on the first read of that table); writes go to the file and to the in-memory mirror. The directory
    survives process restarts. One writer process at a time; any number of readers."""

    def __init__(self, directory):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._mem = MemoryStore()
        self._loaded = set()
        self._files = {}

    def _path(self, table):
        return self.dir / f"{table}.jsonl"

    def _append(self, table, records):
        f = self._files.get(table)
        if f is None:
            f = self._files[table] = open(self._path(table), "a", encoding="utf-8")
        for rec in records:
            f.write(json.dumps(rec, separators=(",", ":"), allow_nan=False) + "\n")
        f.flush()

    def _load(self, table):
        if table in self._loaded:
            return
        self._loaded.add(table)
        path = self._path(table)
        if not path.exists():
            return
        with open(path, encoding="utf-8") as f:
            for line in f:
                if not line.endswith("\n"):
                    break  # a torn last line from a killed writer: ignore it
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if "__upd" in rec:
                    self._mem.update_where(table, rec["__upd"]["eq"], rec["__upd"]["values"])
                elif "__key" in rec:
                    key = rec.pop("__key")
                    self._mem.upsert(table, key, [rec])
                else:
                    self._mem.insert(table, [rec])

    def insert(self, table, rows):
        rows = list(rows)
        self._append(table, rows)
        if table in self._loaded:
            self._mem.insert(table, rows)

    def upsert(self, table, key_cols, rows):
        rows = list(rows)
        self._append(table, [dict(r, __key=list(key_cols)) for r in rows])
        if table in self._loaded:
            self._mem.upsert(table, key_cols, rows)

    def select(self, table, where=None):
        self._load(table)
        return self._mem.select(table, where)

    def exists(self, table, **eq):
        self._load(table)
        return self._mem.exists(table, **eq)

    def update_where(self, table, eq, values):
        self._load(table)
        n = self._mem.update_where(table, eq, values)
        if n:
            self._append(table, [{"__upd": {"eq": eq, "values": values}}])
        return n

    def close(self):
        for f in self._files.values():
            f.close()
        self._files = {}


def default_store_dir(run):
    return Path(__file__).resolve().parents[1] / "data" / run / "store"


def open_store(spec, run):
    """'jsonl:<dir>' (or None -> fleet/data/<run>/store) -> JsonlStore; 'clickhouse://host[:port]/db' -> ClickHouseStore."""
    if spec is None:
        return JsonlStore(default_store_dir(run))
    if spec.startswith("clickhouse://"):
        from .clickhouse_store import ClickHouseStore

        st = ClickHouseStore.from_spec(spec)
        st.ensure_schema()
        return st
    kind, _, rest = spec.partition(":")
    if kind == "jsonl" and rest:
        return JsonlStore(rest)
    raise ValueError(f"--store must be jsonl:<dir> or clickhouse://host[:port]/db, got {spec!r}")

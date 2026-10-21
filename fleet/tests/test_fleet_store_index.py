"""Tests for S14E: MemoryStore keeps its indices current on update_where / upsert instead of dropping them.

(a) property tests against an index-free full-scan reference; (b) a 500-step byte-identity test: the same stripped
s10c-blind store graded under the new MemoryStore and under master's (_OldMemoryStore, copied verbatim below, drop-indices
and all); (c) an 8 h timing test. The data tests read WR_S10_DATA (default REPO/fleet/data) and skip, naming it, when the
data is absent. No env, no Docker."""
import contextlib
import io
import json
import os
import random
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "fleet") not in sys.path:
    sys.path.insert(0, str(ROOT / "fleet"))

import grade  # noqa: E402
from fleet_analyser import store as store_mod  # noqa: E402
from fleet_analyser.store import MemoryStore, Store, _hk  # noqa: E402

DATA = Path(os.environ.get("WR_S10_DATA") or ROOT / "fleet" / "data")
STAMPS_500 = 953
LIMIT_8H_S = 120


# master's MemoryStore at f01efbe, verbatim apart from the class name: the reference for the byte-identity test
class _OldMemoryStore(Store):
    """Dict-backed store. Equality lookups build an index per column tuple on first use and keep it current."""

    def __init__(self):
        self._rows = {}  # table -> list of row dicts (upserts replace in place)
        self._idx = {}  # (table, cols) -> {value tuple -> [rows]}

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

    def _drop_indices(self, table, keep=None):
        for k in [k for k in self._idx if k[0] == table and k != keep]:
            del self._idx[k]

    def _lookup(self, table, eq):
        if not eq:
            return list(self._table(table))
        cols = tuple(sorted(eq))
        return list(self._index(table, cols).get(tuple(_hk(eq[c]) for c in cols), []))

    def insert(self, table, rows):
        t = self._table(table)
        for r in rows:
            r = dict(r)
            t.append(r)
            self._add_to_indices(table, r)

    def upsert(self, table, key_cols, rows):
        cols = tuple(key_cols)
        t = self._table(table)
        for r in rows:
            r = dict(r)
            idx = self._index(table, cols)
            hit = idx.get(tuple(_hk(r.get(c)) for c in cols))
            if hit:
                old = hit[0]
                old.clear()
                old.update(r)  # the same dict object stays in the key index (key columns unchanged)
                self._drop_indices(table, keep=(table, cols))
            else:
                t.append(r)
                self._add_to_indices(table, r)

    def select(self, table, where=None):
        return [dict(r) for r in self._lookup(table, where)]

    def exists(self, table, **eq):
        return bool(self._lookup(table, eq))

    def update_where(self, table, eq, values):
        hit = self._lookup(table, eq)
        if not hit:
            return 0
        self._drop_indices(table)
        for r in hit:
            r.update(values)
        return len(hit)


class RefStore:
    """No index at all: a plain list per table, every select / exists / update answered by a full scan in table order."""

    def __init__(self):
        self.t = {}

    @staticmethod
    def _match(r, eq):
        return all(_hk(r.get(c)) == _hk(v) for c, v in eq.items())

    def insert(self, table, rows):
        self.t.setdefault(table, []).extend(dict(r) for r in rows)

    def upsert(self, table, key_cols, rows):
        tab = self.t.setdefault(table, [])
        for r in rows:
            r = dict(r)
            hit = [x for x in tab if all(_hk(x.get(c)) == _hk(r.get(c)) for c in key_cols)]
            if hit:
                hit[0].clear()
                hit[0].update(r)
            else:
                tab.append(r)

    def select(self, table, where=None):
        return [dict(r) for r in self.t.setdefault(table, []) if self._match(r, where or {})]

    def exists(self, table, **eq):
        return bool(self.select(table, eq))

    def update_where(self, table, eq, values):
        hit = [r for r in self.t.setdefault(table, []) if self._match(r, eq)]
        for r in hit:
            r.update(values)
        return len(hit)


COLS = ("a", "b", "c")
TABLES = ("t0", "t1", "t2")
KEYS = (("a",), ("a", "b"), ("b", "a"), ("c",), ("c", "a", "b"))
DOMAIN = (0, 1, 2, "x", "y", None, [1, 2], [2, 1], {"k": 1}, {"k": 2})


def cell(rng):
    return json.loads(json.dumps(rng.choice(DOMAIN)))


def rand_row(rng):
    return {c: cell(rng) for c in COLS if rng.random() < 0.8}


def rand_eq(rng):
    return {c: cell(rng) for c in rng.sample(COLS, rng.randint(1, 3))}


class TestProperty(unittest.TestCase):
    def run_ops(self, seed, n_ops=2000):
        rng = random.Random(seed)
        new, ref = MemoryStore(), RefStore()
        counts = dict(insert=0, upsert=0, update=0, select=0, exists=0, dup=0)
        for step in range(n_ops):
            tb = rng.choice(TABLES)
            op = rng.choices(("insert", "upsert", "update", "select", "exists", "dup"), (3, 3, 4, 3, 1, 1))[0]
            counts[op] += 1
            if op == "insert":
                rows = [rand_row(rng) for _ in range(rng.randint(1, 3))]
                new.insert(tb, rows)
                ref.insert(tb, rows)
            elif op == "dup":  # byte-identical rows: equality-based removal would pick the wrong one
                r = rand_row(rng)
                new.insert(tb, [r, r])
                ref.insert(tb, [r, r])
            elif op == "upsert":
                key = rng.choice(KEYS)
                rows = [rand_row(rng) for _ in range(rng.randint(1, 2))]
                new.upsert(tb, key, rows)
                ref.upsert(tb, key, rows)
            elif op == "update":
                eq = rand_eq(rng)
                vals = {c: cell(rng) for c in rng.sample(COLS, rng.randint(1, 2))}
                if rng.random() < 0.15:
                    vals["d"] = cell(rng)  # a new column
                if rng.random() < 0.15:
                    vals = dict(eq)  # sets every eq column to the value it already has
                if rng.random() < 0.15:
                    eq = dict(eq, **{c: v for c, v in vals.items() if c in COLS})  # eq holds a column values changes
                self.assertEqual(new.update_where(tb, eq, vals), ref.update_where(tb, eq, vals), (seed, step))
            elif op == "select":
                w = None if rng.random() < 0.2 else rand_eq(rng)
                self.assertEqual(new.select(tb, w), ref.select(tb, w), (seed, step, w))
            else:
                eq = rand_eq(rng)
                self.assertEqual(new.exists(tb, **eq), ref.exists(tb, **eq), (seed, step, eq))
        for tb in TABLES:
            self.assertEqual(new.select(tb), ref.select(tb))
            for _ in range(40):
                w = rand_eq(rng)
                self.assertEqual(new.select(tb, w), ref.select(tb, w))
            for r in new.select(tb):
                self.assertLessEqual(set(r), set(COLS) | {"d"}, "a side-map seq leaked into a row")
        return counts

    def test_property_seeds(self):
        for seed in range(6):
            with self.subTest(seed=seed):
                c = self.run_ops(seed)
                self.assertGreater(c["update"], 100)

    def test_property_indices_survive_update(self):
        """The index objects are kept (not dropped) by update_where and by the update branch of upsert."""
        st = MemoryStore()
        st.insert("t", [dict(a=1, b=1), dict(a=1, b=2), dict(a=2, b=1)])
        st.select("t", {"a": 1})
        st.select("t", {"b": 1})
        st.upsert("t", ("a", "b"), [dict(a=1, b=1, c=5)])
        before = dict(st._idx)
        self.assertEqual(len(before), 3)
        st.update_where("t", {"a": 1}, dict(b=7))
        st.upsert("t", ("a", "b"), [dict(a=2, b=1, c=6)])
        self.assertEqual(set(st._idx), set(before))
        for k, v in before.items():
            self.assertIs(st._idx[k], v)
        self.assertEqual(st.select("t", {"b": 7}), [dict(a=1, b=7, c=5), dict(a=1, b=7)])

    def test_identical_duplicates_move_the_right_object(self):
        st = MemoryStore()
        st.insert("t", [dict(a=1), dict(a=1), dict(a=1)])
        st.select("t", {"a": 1})
        st.update_where("t", {"a": 1}, dict(a=2))
        self.assertEqual(st.select("t", {"a": 1}), [])
        self.assertEqual(len(st.select("t", {"a": 2})), 3)
        self.assertEqual([id(r) for r in st._idx[("t", ("a",))][(2,)]], [id(r) for r in st._rows["t"]])


def strip_grades(store_dir):
    """Drop every __upd line of decisions.jsonl and empty forecast_grades.jsonl; return the number of dropped __upd."""
    p = Path(store_dir) / "decisions.jsonl"
    keep, dropped = [], 0
    for line in p.read_text().splitlines(keepends=True):
        if "__upd" in json.loads(line):
            dropped += 1
        else:
            keep.append(line)
    p.write_text("".join(keep))
    (Path(store_dir) / "forecast_grades.jsonl").write_text("")
    return dropped


def upd_lines(store_dir):
    lines = (Path(store_dir) / "decisions.jsonl").read_text().splitlines()
    return sum(1 for line in lines if "__upd" in json.loads(line))


def grade_copy(run, store_dir, truth, old=False):
    out = io.StringIO()
    patch = mock.patch.object(store_mod, "MemoryStore", _OldMemoryStore) if old else contextlib.nullcontext()
    t0 = time.perf_counter()
    with patch, contextlib.redirect_stdout(out):
        rc = grade.main(["--run", run, "--store", f"jsonl:{store_dir}", "--once", "--truth", str(truth)])
    return rc, time.perf_counter() - t0, out.getvalue()


class TestGradeOnData(unittest.TestCase):
    def need(self, run):
        store, truth = DATA / run / "store", DATA / run / "truth.json"
        if not (store.is_dir() and truth.is_file()):
            self.skipTest(f"{store} or {truth} absent (WR_S10_DATA={DATA})")
        return store, truth

    def test_grade_byte_identity_500step(self):
        src, truth = self.need("s10c-blind")
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / "new", Path(tmp) / "old"
            for d in (a, b):
                shutil.copytree(src, d)
                self.assertEqual(strip_grades(d), STAMPS_500)
            rc_a, sec_a, out_a = grade_copy("s10c-blind", a, truth)
            rc_b, sec_b, out_b = grade_copy("s10c-blind", b, truth, old=True)
            print(f"\ngrade 500-step: new {sec_a:.2f} s, old {sec_b:.2f} s", file=sys.stderr)
            self.assertEqual((rc_a, rc_b), (0, 0))
            self.assertEqual(out_a, out_b)
            self.assertEqual(upd_lines(a), STAMPS_500)
            for name in ("decisions.jsonl", "forecast_grades.jsonl"):
                self.assertGreater((a / name).stat().st_size, 0, name)
                self.assertEqual((a / name).read_bytes(), (b / name).read_bytes(), name)

    def test_grade_8h_timing(self):
        src, truth = self.need("s10c-blind-8h")
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "store"
            shutil.copytree(src, a)
            strip_grades(a)
            rc, sec, _ = grade_copy("s10c-blind-8h", a, truth)
            print(f"\ngrade 8h: {sec:.1f} s (limit {LIMIT_8H_S} s), __upd lines {upd_lines(a)}", file=sys.stderr)
            print(f"grade 8h seconds: {sec:.1f}")
            self.assertEqual(rc, 0)
            self.assertLess(sec, LIMIT_8H_S)


if __name__ == "__main__":
    unittest.main()

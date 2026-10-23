# S14E-STORE-INDEX: MemoryStore keeps its indices current

## Before / after seconds
1. `grade --once --truth`, stripped s10c-blind (500 steps), measured in this lane (test (b), in-process): old (master MemoryStore) 1.73-1.86 s, new 0.17 s.
2. `grade --once --truth`, stripped s10c-blind-8h, new code, measured: 4.4 s and 4.7 s (two runs; limit 120 s). Before: ~50 min, derived from file mtimes (costmap.jsonl 14:34, decisions.jsonl 15:24), covering lessons + grade together, so not a like-for-like figure. Old code was not run on the 8h store.
3. JsonlStore load of the graded 8h decisions.jsonl (35,281 rows + 33,712 `__upd` lines): new 0.5 s. Old: not measured to completion, the run was stopped at the 15 minute limit (it shared the CPU with the 11-minute gate for part of that time).

## Design
- Every row gets a seq when first appended (`insert`, and the append branch of `upsert`), kept in a side map `MemoryStore._seq[id(row)]` with a monotone counter. Never a column, so nothing leaks into `select()` copies or the JSONL. `id()` is safe: rows are never deleted and the table list keeps them alive; an in-place upsert keeps the dict object, so its seq never changes.
- `update_where` and the update branch of `upsert`: old keys of the affected indices (all indices for upsert; those whose cols meet `values` for update_where) are computed before the mutation, the new keys after. For every index whose key changed, the row is removed from the old bucket and inserted into the new one, both located by `bisect_left(bucket, seq, key=seq_of)` and checked `bucket[pos] is row` (identity, no `list.remove` / `list.index`). Emptied buckets are deleted. `_lookup` still returns a list copy, so no bucket is iterated while rows leave it.
- Bucket-order option used: seq + bisect reinsertion at the order-preserving position (not a bucket rebuild from the table, which is O(table) per move). It preserves table order because seq is monotone in first-insert position and never changes, and every bucket stays sorted by seq (a full build iterates the table in order, insert appends the newest seq, a move bisects into place).
- `_drop_indices` deleted (grep of fleet, src, scripts, tests: only store.py used it). `JsonlStore._load` unchanged.

## Byte-identity test
Fields ignored: none. decisions.jsonl and forecast_grades.jsonl of the new-store copy equal the master-store copy byte for byte, and so does the printed summary line. The new copy holds exactly 953 `__upd` lines in decisions.jsonl.

## Tables the grade path writes
`decisions` (only via `stamp_grade` -> `update_where`, the `__upd` lines) and `forecast_grades` (`write_once` -> `upsert` at forecast_grade.py:62; grade.py:53/74 and forecast_grade.py:109 call `write_once`). `lessons.py` has no store writes (grepped `.insert/.upsert/.update_where` in grade.py, fleet_analyser/grade.py, forecast_grade.py, lessons.py, decisions.py; the only other write is `decisions.record_decision` insert, not on the grade path). decision_grades is ClickHouse-only.

## Tests
`fleet/tests/test_fleet_store_index.py` (collected by tests/test_fleet_collect.py via `test_fleet_*.py`): property test over 6 seeds x 2,000 ops, 3 tables, list/dict/None/missing cells, identical duplicate rows, no seq leak; index-survival and duplicate-identity tests; (b) byte identity and (c) 8h timing, both ran ok (not skipped) with WR_S10_DATA=fleet/data.

## Gate tail
`WR_S10_DATA=... .venv/bin/python -m unittest discover -s tests`
```
Ran 1132 tests in 695.523s
OK (skipped=4)
```
(the 4 skips are not in test_fleet_store_index)

SCHED_RESULT: OK 500-step grade 1.8 s -> 0.17 s, 8h grade 4.7 s (was ~50 min lessons+grade), byte-identical, old JsonlStore load not measured

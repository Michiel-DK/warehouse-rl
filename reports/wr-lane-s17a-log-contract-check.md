# S17A lane: fleet-state contract check (`fleet/check_log.py`), loud ingest failure, keyed reject reasons

Date 2026-10-23. Lane job `wr-lane-s17a-log-contract-check`, `single-lane-build` run wf_d33af879-87a (tier standard,
Sonnet builder, refuters: correctness, test-honesty, plus the auto-added invariants and scope-adherence). **PR #59,
squash-merged as 7405ded on origin/master.** Local master took it through merge commit e08f1b4. Local master holds
unpushed public-repo prep commits (22 ahead after the merge) that stay held. Master was not pushed.

Deviation from the job text: the job said `baseBranch: 'master'` and "fast-forward master". The lane was branched from
`origin/master` instead (passed as `baseBranch: 'origin/master'`). Branching from local master would have put the held
prep commits into the PR, and the squash would have published them (the S15B incident). Because local master is ahead
of origin, a fast-forward is impossible, so origin/master was merged into local master, as with 2f0535b / 31897c2.

## What was built

- `fleet/fleet_analyser/parse.py`:
  - **Contract spec.** One module-level spec, `REQUIRED_FIELDS` (ten paths in today's check order, each with its
    expected type and validity predicate), plus `OPTIONAL_FIELDS` (theta, nodeStates, paused; these degrade and never
    reject). `parse_line` iterates the spec for its missing-key checks, and `check_log` imports it, so there is no
    second list. The per-field helpers `field_value`, `field_reason` and `check_field` use the same predicates as
    `parse_line`.
  - **Reject reasons now name the key.** The reasons are: `type:line`, `type:agvPosition`, `type:headerId`,
    `type:timestamp`, `timestamp:timestamp`, `type:serialNumber`, `type:orderId`, `type:agvPosition.x`,
    `type:agvPosition.y`, `type:driving`, `type:errors`, `type:loads`. Combined conditions were split in the old order.
    `json` and `missing:<key>` are unchanged.
- `fleet/check_log.py --glob G [--lines 500]`:
  - **Input.** It detects gzip from the magic bytes, so plain JSONL works too. It reads the first N lines of each file.
  - **Table.** One row per required field: has it, parses, first offending value (120 characters), and reason. There
    is a separate "not a JSON object" row and an optional-fields block.
  - **Verdict.** It ends with one verdict line and exits 0 only on MATCHES, 2 otherwise. It writes nothing.
- `fleet/ingest.py --min-accepted SHARE` (validated to [0, 1]):
  - **Default.** `min_accepted_for(source, once, flag)` decides the share: 0.5 for the file source without `--once`;
    off with `--once` and off on kafka unless the flag is passed.
  - **On a mismatch.** The summary line shows exit 2, followed by `rejects by reason ...; top failing keys ...` and
    `ingest <run>: DOES NOT MATCH the fleet-state contract, run fleet/check_log.py`. An existing exit 1 is kept.
  - **No store changes.** Reasons are counted in memory in the ingester (`fleet_analyser/ingest.py`). Nothing new goes
    to the store.
- `fleet/timebudget.py`: when `--stations auto` finds no emit ledger, it prints the new message and exits 2. The
  message goes to **stderr**, like the old one. `stations.py` was not edited.
- `fleet/replay_export.py`: `rejected_by_reason` maps the `type:`/`timestamp:` heads back to `type` / `timestamp`, so
  the committed replay page data rebuilds unchanged. `missing:*` is untouched. `moroop_dispatch.py` was not edited: its
  `rule_drop_reasons` carries the new strings, and its committed value is `{}`.
- `docs/DEMO.md`: added only the "Before you run this on your own log" section.
- Tests:
  - New: `fleet/tests/test_fleet_check_log.py` and the committed fixture `fleet/tests/data/s17a_emit50/` (600 lines from
    `emit.py --zones 1 --steps 50`).
  - Added to: `test_fleet_parse.py` (a frozen copy of the old reject decision, a literal old->new reason table,
    split-condition cases), `test_fleet_ingest.py`, `test_fleet_timebudget.py`.
  - Updated to the new exact strings: `test_fleet_hotspot.py`, `test_s8i_demo_noise.py`.

## Observed on merged local master (e08f1b4)

| command | output (last line) | exit |
|---|---|---|
| `check_log.py` on the operator's 3-line bad log | `check_log: DOES NOT MATCH: 10 of 10 fields missing (headerId, timestamp, serialNumber, orderId, agvPosition, driving, errors, loads, agvPosition.x, agvPosition.y), 0/3 lines parse; see docs/SCOPE.md "S5A" and fleet/adapters/moroop.py for how a source is adapted` | 2 |
| `check_log.py --lines 50` on the 50-step emit | `check_log: MATCHES the fleet-state contract (50/50 lines parse)` | 0 |
| `check_log.py` on `fleet/data/moroop/jsonl-sb` | `check_log: MATCHES the fleet-state contract (4500/4500 lines parse)` | 0 |
| `ingest.py --once --min-accepted 0.5` on the bad log | `... exit 2` / `rejects by reason missing:headerId 2, json 1; top failing keys headerId 2` / `DOES NOT MATCH ...` | 2 |
| `ingest.py --once` on the bad log | `accepted 0 (parsed 0, rejected 3, duplicates 0) ... exit 0` (unchanged) | 0 |
| `timebudget.py --stations auto` with no ledger | `stations: no emit_ledger.json in /tmp/s17a-badlog/badlog (only the emitter writes one); pass --stations PATH, see fleet/data/moroop/stations.json for the format` | 2 (was 1) |

## Byte identity on matching logs

A raw sha256 of a whole jsonl store differs from run to run on unchanged code. `ingest_*` rows and
`decisions.recorded_at` carry wall-clock values. Measured: two master runs of the s10-none ingest gave different raw
hashes. The comparison therefore uses a content hash: every `*.jsonl` except `ingest_*`, with decisions re-serialised
and sorted without `recorded_at`. The same algorithm is copied into `test_fleet_ingest.py` as `store_content_hash`.
Two runs of the unchanged code gave identical content hashes, and so did before vs after:

| store (ingest `--once`) | before (master code, 23 Oct) | after (e08f1b4) |
|---|---|---|
| s10-none `-sb` leg (`--stations auto --servicing-max-s auto`) | 91480e9f8d77314de23f889ccd7ba930c5bcc6733bcff3be1c6b02fa0b1a7f74 | same |
| MoRoOp `jsonl-sb` (`--stations stations.json --station-radius 1 --servicing-max-s auto`) | f4597a6edc08f13c84548d591d1f8e5b39b55a3753d1a09872a369ae35c0b674 | same |
| 50-step emit fixture | 233700cb3016c31c8706a56376537a22c4f3fec7b4df98158dca9a475225e27a | same (pinned in a test) |

The parse refactor was checked separately. Two refuters ran a differential fuzz of the old `parse_line` against the
new one over 200,000 and 60,000 mutated lines. Accept/reject and the Message were identical on every line, and every
old `type` / `timestamp` reason maps to its keyed form.

## Review round

- **Criterion pre-review.** Sound, with four advisories, all carried into this report.
- **python-reviewer** found two majors, both fixed in 77aa9e0 and re-verified:
  1. Two exact assertions in `fleet/tests/test_s8i_demo_noise.py` still expected `timestamp` / `type` and failed on the
     PR head. **The repo gate did not see this.** `tests/test_fleet_collect.py` only collects `test_fleet_*.py` from
     `fleet/tests`, and `test_s8i_*`, `test_s8k_*` and similar modules are outside the gate. Fixed with an exact
     per-kind map: json -> `json`, timestamp -> `timestamp:timestamp`, type -> `type:agvPosition.x`.
  2. No test pinned the `--min-accepted` default. Fixed by `min_accepted_for` (used on both paths) with a unit test,
     plus a no-`--once` end-to-end run on the fixture. A mutation that applies the default under `--once` fails 2 tests.
- **Refuters.**
  - correctness, test-honesty and invariants: did not refute.
  - scope-adherence: refuted on `OPTIONAL_FIELDS` / the optional block, the "not a JSON object" row, gzip-by-magic,
    the 120-character truncation and the `_share` validator. **Overruled:** the brief (tasks 1 and 3) asked for each of
    these. The refuter judged against the criterion only.
- **Fix-commit refuter** (verify-gate, correctness and test-honesty): survives, high confidence. Its note was that the
  end-to-end comment overstated what the test proves (a matching log exits 0 with or without the default). The comment
  was reworded in 6d850aa.
- **Minors left open:**
  - When `agvPosition` is not an object, `check_log` lists `agvPosition.x/.y` as `missing:` under it. The verdict, the
    exit code and the `agvPosition` row (`type:agvPosition`) are right.
  - The `fleet/fleet_analyser/emitter.py:293` docstring still says "reasons json / timestamp / type". It is a stale
    comment, and the file is outside the lane.
  - The `type:line` reject shows up as top key "line".

## Gate

- **PR head 77aa9e0.** `.venv/bin/python -m unittest discover -s tests`: Ran 1293 tests in 707 s, FAILED (failures=1,
  skipped=10). The one failure is `test_committed_page_is_a_fresh_build`, which is known red on origin/master.
- **All of `fleet/tests`** (`discover -s fleet/tests -t . -p 'test_*.py'`): 1284 tests, 6 failures. All six are overview
  or page freshness tests that fail identically on an origin/master worktree (s8r, s8o, s8k x2, s10h, s11a). The two
  s8i tests now pass.
- **Merged local master e08f1b4.** `discover -s tests`: **Ran 1293 tests in 704 s, OK.** Outside the gate,
  `test_s8k_overview` `test_footer_paths_are_visible_and_pass` fails, and it fails identically on the pre-merge local
  master 3c6caa6. It is pre-existing and noted in the S16 readme report.

## Open for the operator

1. **The default 0.5 never fires on the case it was made for.** Without `--once`, the file source never ends on a
   directory that has no `emit_ledger.json`: it was still running after 20 s on master, and the merge did not change
   that. Any stranger's log is in that state. With `--once` (the form that ends), the default is off by your
   instruction. So a stranger running `ingest.py` without flags either waits forever or, with `--once`, gets exit 0.
   Only `--once --min-accepted 0.5` refuses loudly. Two options: make the default apply under `--once` too, or end the
   file source when no ledger exists. Both change today's behaviour, so the choice is yours.
2. **The old timebudget exit was 1, not 0.** On master, timebudget without a ledger exited 1 (SystemExit with a string),
   not 0 as the 23 Oct note said. Now it is 2.
3. **The repo gate skips some fleet test modules.** `tests/test_fleet_collect.py` does not collect `fleet/tests/test_s*`
   modules (s8i, s8k, s8r, s10h, s11a and others). This lane's only real regression was in one of them. Six of those
   modules are red on origin/master, and one (the s8k footer test) is red on local master.
4. **Plain `.jsonl` is checked but not ingested.** `check_log` reads uncompressed `.jsonl`, but `ingest.py` still only
   reads gzip, so a plain file fails ingest with exit 1.

SCHED_RESULT: OK wr-lane-s17a-log-contract-check PR #59 merged (7405ded, local master e08f1b4); check_log + ingest --min-accepted + keyed reasons; -sb/MoRoOp/fixture store content hashes unchanged; gate 1293 OK on local master; open: no-ledger file source never ends so default 0.5 never fires on a stranger's log

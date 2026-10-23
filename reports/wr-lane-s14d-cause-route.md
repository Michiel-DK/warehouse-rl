# wr-lane-s14d-cause-route: cause labels split by the next route node

Lane S14D, 21 Oct 2026. PR #54 (branch worktree-wf_17800c14-507-2), squash-merged as e3d2b52; master fast-forwarded. Build: sonnet via single-lane-build (tier full), head
eda9d75. Review round 1: correctness and test-honesty refuted, both on the missing report (the builder's harness blocked
`.md` writes) and test-honesty on two surviving mutants. The main loop fixed both in 17a4664 and wrote this report. Three
fresh refuters then re-checked (correctness, regression with nodeStates absent, test-honesty). Rules from
docs/LITERATURE.md Part 5 section 2 (rename) and Part 6 row 6 (next route node). Deviation below.

## What changed

- `fleet/fleet_analyser/detector.py` `_cause` returns `(cause, blocker, blocker_faulted_s, blocker_on_route)`.
  - Keys and precedence are unchanged: faulted_self > blocked_by_faulted > blocked_by_stuck > traffic > unknown.
  - Within the chosen category only, the robot standing on the message's next node (`next_x`, `next_y`, same batch) is
    the blocker; otherwise the lowest serial, as before. An on-route stuck robot never beats an off-route faulted one.
  - `blocker_faulted_s` comes from the chosen blocker, and traffic keeps `blocker` None.
  - `blocker_on_route` applies to the three neighbour causes only:
    - None when the message reports no route (`nodes_reported` false or `next_x` None, i.e. key absent or `[]`);
    - otherwise True iff the chosen blocker stands on the next node (for traffic: any robot of the adjacent set).
  - `blocker_on_route` is None for faulted_self, unknown and station_overrun.
  - Every episode event carries the key: it is initialised None and set with the cause.
- `cause_label(cause, blocker_on_route)`, with `CAUSE_LABELS` as the default text (off route or route unknown) and
  `ROUTE_LABELS` for the True case:

  | key | blocker_on_route True | False / None |
  |---|---|---|
  | faulted_self | n/a | Robot error, cannot continue order |
  | blocked_by_faulted | Blocked by a broken robot | Stopped next to a broken robot |
  | blocked_by_stuck | Blocked by a stuck robot | Stopped next to a stuck robot |
  | traffic | Traffic wait | Stopped next to another robot |
  | unknown | n/a | Stopped, cause not identified (unchanged) |
  | station_overrun | n/a | Station stop over time limit (unchanged) |

  Rename relative to S14A, as seen on an old-schema stream:

  | S14A label | label now |
  |---|---|
  | Robot fault | Robot error, cannot continue order |
  | Blocked by a faulted robot | Stopped next to a broken robot |
  | Blocked by a stuck robot | Stopped next to a stuck robot |
  | Traffic wait | Stopped next to another robot |
- `fleet/fleet_analyser/causes.py` `causes_table` groups by (cause, cause_label), so one key can give two rows.
  - Sort order: -seconds, then cause, then cause_label.
  - The report, timebudget and MoRoOp causes tables all use it, so the split shows in all three without edits there.
- `fleet/fleet_analyser/ingest.py:227` writes `cause_label(cause, blocker_on_route)`. The `stuck_cause` decision payload is
  unchanged, and a test asserts the key is not in it.
- `fleet/sql/schema.sql`: `blocker_on_route Nullable(Bool)` in the stuck_episodes CREATE, plus
  `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, as S14A did for cause_label. Not exercised against a running ClickHouse.

**Files against the declared set.** The operator's list named `fleet/report.py`, `fleet/timebudget.py` and
`fleet/adapters/moroop.py`. None needed an edit, because they consume `causes_block`. The label, grouping and column live
in `causes.py`, `ingest.py` and `schema.sql`, which are changed. `fleet/fleet_analyser/report.py:65` already prints
`cause_label (cause)` per row and needed nothing. Further files touched:
- the two existing sha-pin tests (`test_fleet_detector_stations.py`, `test_fleet_detector_servicing_bound.py`);
- `tests/platform_expected.json`, which holds the new pin.

`grafana/cause_mix.sql` and the dashboard alias the cause KEY as `cause_label` and are untouched. The README, LITERATURE and
the pages still carry the old strings; renaming them is the docs item.

**Deviation from Part 5.** Part 5's table says "Stopped next to a robot in error" for blocked_by_faulted. This lane uses the
operator's strings from the brief instead: "Stopped next to a broken robot" and, on route, "Blocked by a broken robot".
"Blocked by" is used only when the neighbour stands on the robot's reported next node. Part 6 row 6 calls that "a
directional geometry fact, still not Part 5 §2's 'blocked by'", because a planner log is what would prove it. The operator
chose "Blocked by" for this case; Part 6's caveat stands, and the client text overstates it by that much.

## Tests

`fleet/tests/test_fleet_cause_route.py`, 14 tests through the real Detector (hand-made `parse.Message` batches, a message
every 10 s):
- (a) a faulted robot on the next node (5,4) gives True / "Blocked by a broken robot", and the close row carries it too.
- (b) the same robot on (4,5) gives False / "Stopped next to a broken robot"; (b2) a neighbour on (5,5) with next node
  (5,3) shares x but not y and gives False (added in the final commit).
- (c) no nodeStates key gives None / "Stopped next to"; (c2) `nodeStates []` gives None.
- (d) the higher-serial on-route robot beats the lower-serial off-route one, and `blocker_faulted_s` comes from it.
- (e) traffic with a neighbour on the next node gives "Traffic wait"; a neighbour beside the route gives "Stopped next to
  another robot".
- (e2) traffic where the on-route neighbour is not the lowest serial (added in 17a4664).
- (e3) a station_overrun episode with a faulted robot on the next node stays None (added in 17a4664).
- (f) precedence: an on-route stuck robot plus an off-route faulted one gives blocked_by_faulted, False.
- (g) blocked_by_stuck on route, and with no nodeStates key gives None (no-route case added in the final commit).
- (h) faulted_self, unknown and station_overrun labels.
- (i) causes_table splits one key into two rows. The False row comes first and the seconds tie, so only the label
  tie-break puts "Blocked by" first.
- (j) ingest writes the label from the function, and stuck_cause decisions have no blocker_on_route.

Results:
- **On master:** the builder ran the file on a master worktree (c5ef842) with a `cause_label` shim of the master
  behaviour; all 11 tests of eda9d75 fail there (10 errors on the missing key, 1 failure on the table split). e2, e3 and b2
  were not run on master; all need the key, which master lacks.
- **Mutants:** M3 (the traffic flag tests only the first adjacent robot) is killed by e2, and M4 (station_overrun gets
  False) by e3. These were the pass-1 survivors.
- The re-verify refuter ran 16 mutants on 17a4664. Its three real survivors are killed in the final commit, and the main
  loop re-ran each one (FAILED):
  - M8, the y comparison dropped, killed by b2;
  - M5b, the stuck flag coerced to bool, killed by g;
  - M9, the label dropped from the sort key, killed by i.
- The survivors left are equivalent mutants: `next_x` alone for `routed`, `is True` loosened, and dropping the None
  initialiser (`ep.update` overwrites it).
- **Pins:** the S13B/S14A event-stream sha pins hash the stream with `blocker_on_route` popped, and still equal their old
  values (c43c6ce3…, 88056846…, 82e3c5e9…). So no other key moved.
- **New pin:** `test_u` pins the S14A stations-auto stream of s10-none zone0 WITH the key:
  `39972a6c708aecb4a4341cd4a9155cb3212f102fc5b32b920f96d31ee1ff3493`. It is darwin-arm64 only, so it skips on Linux, like
  the others.

## Byte identity, nodeStates absent

Setup:
- Input: fleet/data/s10-none zone0-000.jsonl.gz with the `nodeStates` key deleted from every message (6000/6000 had it,
  0 after; `/tmp/s14d_patch/mkstrip.py`), plus emit_ledger.json, in `/tmp/s14d_work/strip`.
- Code: master c5ef842 (a separate worktree) against the branch.
- Legs (`/tmp/s14d_patch/legs.sh`): `ingest.py --stations auto --servicing-max-s auto --once` into a jsonl store, then
  `timebudget.py --stations auto --station-aware --servicing-max-s auto` on it, then `fleet/report.py`.
- Both sides ran under `/tmp/s14d_patch/fixedclock.py` (a fixed clock), because recorded_at and updated_at differ run to
  run otherwise.
- Ingest prints `exit 1` on both sides with the same counts (accepted 6000, rejected 0). Its coverage check fails because
  the ledger lists 10 zones and only zone0 was copied. The store is written either way.

Compare script `/tmp/s14d_patch/compare.py`, rerun by the main loop:

```
rows 130 130
canonical sha master minus {blocker_on_route,cause_label}: 0a0a920d45b245acfc080bffbdcbbe481df146620aebd40f6c219fc64d0e8e89
canonical sha branch minus {blocker_on_route,cause_label}: 0a0a920d45b245acfc080bffbdcbbe481df146620aebd40f6c219fc64d0e8e89
equal: True
blocker_on_route values on branch: ['None'] | on master keys present: False
label pairs master->branch: [('Stopped, cause not identified', 'Stopped, cause not identified'), ('Traffic wait', 'Stopped next to another robot')]
rename table exact: True
timebudget JSON identical after label mapping: True | raw identical: False
```

Store files, sha256 prefix, master and branch:

| file | master | branch |
|---|---|---|
| decisions.jsonl | d27d97728d4d9b45 | d27d97728d4d9b45 |
| evidence.jsonl | 134bdae9127fe32f | 134bdae9127fe32f |
| ingest_checkpoints.jsonl | 3ac6abed39a557d1 | 3ac6abed39a557d1 |
| ingest_files.jsonl | 49bd12a52c446f4a | 49bd12a52c446f4a |
| ingest_ledger.jsonl | 9dfcd92834357e72 | 9dfcd92834357e72 |
| ingest_runs.jsonl | c251423b144cc92f | c251423b144cc92f |
| state_sample.jsonl | 9732c72995c64166 | 9732c72995c64166 |
| transitions.jsonl | ea49a56901823b25 | ea49a56901823b25 |
| stuck_episodes.jsonl | 08efd531397000f0 | 2101fd347527114f (rows differ only by the two keys, above) |

Notes:
- The timebudget JSON is identical after mapping labels, apart from `src.store` / `src.store_sha256_*` (store path and
  the episode file's own hash).
- report.md differs only on the "Traffic wait (traffic)" line.
- This zone has only traffic and unknown episodes, so the stripped check does not exercise the blocked_by_* renames; the
  unit tests cover them.

**Unstripped zone0** (routed, branch code), the episode count per (cause, blocker_on_route, label), 65 episodes:
- unknown / None: 54
- traffic / True / "Traffic wait": 5
- traffic / False: 1
- traffic / None: 5, where the stopped robot reported `nodeStates []`

So on this zone, 5 of 11 traffic stops read "Traffic wait", against 11 of 11 in S14A. This is informative only and not a
README number. The builder's "10 / 2 / 10 / 108" counted open and close rows; the figures here are distinct episodes.

## Queue item

The `wr-s14d-rerun` command, installed by the main loop in `laptop-scheduler/queues/warehouse-rl.json` (commit 4138e30
holds only this item added to HEAD's file, via hash-object / update-index; the other uncommitted queue edits are
untouched). It is NOT run:
cores 4, est 8 min, max 30.

How it is built:
- It mirrors `wr-s14a-rerun`: same RUNS, the snap hash guard over every original `$R/store` file and every pre-existing
  `results/fleet/*.json` (excluding `-sd.json`), and exit 1 on a change.
- `timebudget.py` reads episodes from `--store` when the directory exists (timebudget.py:420-443), and store-sb has no
  blocker_on_route. So each leg re-ingests into `$R/store-sd` first.
- The MoRoOp outputs hold no episode rows, so the null assertion runs the Detector over `$M/jsonl-sd/zone*-000.jsonl.gz`.
  It also checks that no table row of `timebudget_moroop_shifts-sd.json` has a route label.

```sh
setopt shwordsplit 2>/dev/null || true
set -e
P=.venv/bin/python
RUNS="fleet/data/s10-none fleet/data/s10c-blind fleet/data/s10-breakdown fleet/data/s8b-score results/closed_loop_sticky/phaseA"
sums() { find "$1" -type f | sort | xargs shasum -a 256; }
snap() { { for R in $RUNS; do sums "$R/store"; done; ls results/fleet/*.json | grep -v -- '-sd\.json$' | sort | xargs shasum -a 256; } > "$1"; }
H0=$(mktemp); H1=$(mktemp)
snap "$H0"
mkdir -p results/fleet
# S14D: store-sd holds blocker_on_route; timebudget reads episodes from --store when it exists (timebudget.py), and store-sb has no such column, so every leg re-ingests first
leg() {
  R=$1; RUN=$2; TAG=$3
  rm -rf "$R/store-sd"
  $P fleet/ingest.py --glob "$R/*.jsonl.gz" --run "$RUN" --stations auto --servicing-max-s auto --store "jsonl:$R/store-sd" --once
  $P fleet/timebudget.py --glob "$R/*.jsonl.gz" --run "$RUN" --stations auto --station-aware --servicing-max-s auto --store "jsonl:$R/store-sd" --out "results/fleet/timebudget_$TAG-sd.json"
}
leg fleet/data/s10-none s10-none s10-none
leg fleet/data/s10c-blind s10c-blind s10c-blind
leg fleet/data/s10-breakdown s10-breakdown s10-breakdown
leg fleet/data/s8b-score s8b-score s8b-medium-80-p03-07
leg results/closed_loop_sticky/phaseA closed_loop closed-loop-sticky
# MoRoOp: same rebuild as wr-s14a-rerun into jsonl-sd / budget-sd, then --analyse --suffix sd
M=fleet/data/moroop
$P fleet/adapters/moroop.py --raw $M/raw --out $M/jsonl-sd --stations $M/stations-sd.json --servicing-max-s auto
cmp $M/stations-sd.json $M/stations.json
mkdir -p $M/budget-sd
k=0
for S in 2026_07_27_morning 2026_07_27_evening 2026_07_28_morning 2026_07_28_evening 2026_07_29_morning 2026_07_29_evening 2026_07_30_morning 2026_07_31_morning 2026_07_31_evening; do
  $P fleet/timebudget.py --glob "$M/jsonl-sd/zone$k-000.jsonl.gz" --run "moroop-$S" --stations $M/stations.json --station-aware --station-radius 1 --servicing-max-s auto --out "$M/budget-sd/zone$k.json"
  k=$((k+1))
done
$P fleet/adapters/moroop.py --analyse --raw $M/raw --jsonl $M/jsonl-sd --budget $M/budget-sd --stations $M/stations.json --station-radius 1 --servicing-max-s auto --suffix sd
# MoRoOp has no nodeStates, so no episode may carry a route flag. The adapter outputs hold no episode rows (the shift episodes are
# popped before writing), so the episodes are the Detector's over $M/jsonl-sd/zone*-000.jsonl.gz (the messages the adapter analyses):
# count blocker_on_route True/False/None over every episode_open, and require that no cause row of results/fleet/timebudget_moroop_shifts-sd.json
# (every list under a key named table) carries a route label. Exit 1 unless True and False are both 0.
$P -I -c 'import sys,glob,json; sys.path.insert(0,"fleet"); from fleet_analyser.detector import Detector, ROUTE_LABELS; from fleet_analyser.hotspot import read_messages; c={True:0,False:0,None:0}
for f in sorted(glob.glob(sys.argv[1]+"/zone*-000.jsonl.gz")):
    d=Detector(); ev=[]
    for m in read_messages(f): ev.extend(d.feed(m))
    ev.extend(d.end_all())
    for e in ev:
        if e["kind"]=="episode_open": c[e["blocker_on_route"]]+=1
rl=set(ROUTE_LABELS.values()); bad=[0]
def walk(o):
    if isinstance(o,dict):
        for k,v in o.items():
            if k=="table" and isinstance(v,list): bad[0]+=sum(1 for r in v if isinstance(r,dict) and r.get("cause_label") in rl and r.get("cause") in ROUTE_LABELS)
            walk(v)
    elif isinstance(o,list):
        for v in o: walk(v)
walk(json.load(open("results/fleet/timebudget_moroop_shifts-sd.json")))
print("moroop blocker_on_route over episode_open of",sys.argv[1],"True",c[True],"False",c[False],"None",c[None],"| route-label cause rows in results/fleet/timebudget_moroop_shifts-sd.json (table rows):",bad[0])
sys.exit(1 if c[True] or c[False] or bad[0] else 0)' $M/jsonl-sd
snap "$H1"
if ! cmp -s "$H0" "$H1"; then echo "S14D rerun: an original store or a pre-existing results/fleet/*.json changed" >&2; diff "$H0" "$H1" >&2 || true; exit 1; fi
echo "SCHED_RESULT: OK wr-s14d-rerun 5 runs + MoRoOp into *-sd outputs, blocker_on_route null on MoRoOp, originals unchanged"
```

**Smoke** (builder): a one-leg variant (RUNS=s10-none, the other four `leg` lines removed, everything else as above) ran
under zsh in a sandbox copy `/tmp/s14d_smoke` (code plus copies of fleet/data/s10-none and moroop). Exit 0, 33 s wall. Its
last lines:

```
moroop blocker_on_route over episode_open of fleet/data/moroop/jsonl-sd True 0 False 0 None 567 | route-label cause rows in results/fleet/timebudget_moroop_shifts-sd.json (table rows): 0
SCHED_RESULT: OK wr-s14d-rerun 5 runs + MoRoOp into *-sd outputs, blocker_on_route null on MoRoOp, originals unchanged
```

Checks on the sandbox:
- No `-sd` file exists in the real fleet/data/s10-none, fleet/data/moroop or results/fleet (checked by the main loop
  after the smoke).
- The other four legs differ only in arguments and were not smoked.

## Review

Round 1 (workflow wf_17800c14-507, head eda9d75):
- Reviewer python-reviewer failed it on the missing report.
- Refuters: correctness REFUTED (report missing); regression not refuted; test-honesty REFUTED (report missing, plus
  mutants M3 and M4); scope-adherence and invariants not refuted.

Re-verify on 17a4664, three fresh verify-gate refuters:
- correctness: not refuted. Its strongest objection is that the on-route choice changes `blocker` against master on routed
  streams, which is the intent. The effect on grade and lesson numbers is unmeasured; it shows only after a rerun.
- regression (nodeStates absent): not refuted. It reproduced independently on a master worktree; the Detector event
  streams minus the key are `cmp`-identical at stuck_after 30, 10 and 5.
- test-honesty: refuted narrowly, on M8, M5b and M9. All three are fixed in the final commit, which changes only
  `fleet/tests/test_fleet_cause_route.py`, and the main loop re-ran each mutant.

The size of that last change follows from its scope: tests only, and all three mutants verified killed.

## Gate tail

`WR_S10_DATA=fleet/data .venv/bin/python -m unittest discover -s tests`

- On 3cf86be, the final code and tests:

  ```
  Ran 1147 tests in 687.412s
  OK (skipped=4)
  ```

- Also on 17a4664: Ran 1146, OK (skipped=4).
- Also on eda9d75 (builder): Ran 1143, OK (skipped=4).

The new tests ran ok, not skipped, on darwin-arm64 in a verbose targeted run (test_u, test_e2 and test_e3 shown "ok").

SCHED_RESULT: OK wr-lane-s14d PR #54; blocker_on_route + "Blocked by" only on the next route node, else "Stopped next to"; nodeStates-absent stream identical to master except the new null field and the renames (episode rows minus 2 keys sha 0a0a920d…); gate 1147 OK; wr-s14d-rerun written, not run

# S14B-TRAFFIC-ABSENCE lane report

Branch `worktree-wf_ed9acb38-88a-2`, base master (7f916b4). Declared files only: `fleet/absencemap.py`,
`fleet/time_to_detect.py`, `fleet/tests/test_fleet_absencemap.py`, `fleet/tests/test_time_to_detect.py`,
`fleet/tests/test_fleet_hotspot.py` (isolation set only), this report. README.md, docs/SCOPE.md, vendor/, fleet/data/,
results/ and the laptop-scheduler repo are untouched.

## What was built

`fleet/absencemap.py`: a second fast detector next to the CUSUM. A blind blockage produces silence, not stalls; this
detector counts passes per cell and flags a cell nobody has crossed for far longer than its own rate explains.
It publishes `hotspot_forecast` decisions (claim `detector: "absence"`) into a jsonl copy of the run's store, so
`time_to_detect.py` measures it on the same AMOC harness as the CUSUM.

`fleet/time_to_detect.py`: prebuilt mode accepts `claim.detector` in {cusum, absence}, one per store (a mix raises
ValueError), writes a top-level `"detector"` key only when it is not `cusum`, and raises ValueError when the measured run
and the reference disagree (a zero-row reference adopts the measured run's detector; a non-cusum detector against a side
that was not prebuilt raises). Module docstring updated. `check_prebuilt_rows` now returns the detector; new
`resolve_detector`; `rerun_on_copy` gets an optional `detectors` out-dict (same pattern as `modes`).

## The rule as implemented

Passes: one robot's first message on a (zone, cell) per visit (by headerId order; standing still adds none). Cell =
`hotspot.cell_str(x, y)`. Time axis: ONE origin for the run, `first_ts` = the first message ts over all files of the glob
(as fastmap does; the brief allowed either, and the zones of the emitted runs start together). Bins and the publish grid are
fastmap's (`n_bins_of`, `costmap.publish_times`).

Per (zone, cell), at every bin end t: `r = passes_unflagged / observed_unflagged_s`, both frozen while flagged, the
releasing pass counts; eligible when `r * observed_unflagged_s >= min_expected` (default 10; the product equals the
unflagged pass count, so the code compares the count and avoids a float round trip); flag when `exp(-r*gap) < alpha`
(default 1e-3), gap = t - last pass; release at the next pass; score `r * gap`; per zone ranked by (-score, cell).

Deviations from HERE US 10847029 / 11270578 (stated in the module docstring too):
- no time-of-day model: one rate per cell over the whole observed span;
- no labelled threshold: alpha is the only dial and nothing is fitted to labels;
- no hysteresis: a cell is released at its first pass, nothing else;
- eligibility counts passes over the whole unflagged observed span (`r * observed >= 10`), not over the tested window
  (HERE's 10 is the expected count inside the tested window, `r * gap >= 10`);
- the rate is re-evaluated at every bin end (the denominator keeps growing during the open gap, so r falls and the
  threshold `ln(1/alpha)/r` rises). The Part 4 formula `ceil(ln(1/alpha)/(r*bin_s))` is a constant-rate approximation of
  that; the code implements the per-bin-end rule, not the closed form.

## Detours (Pan et al. 2013): not built

One 2,495 s run gives one 30-minute slot and no history to compare a detour rate against, and the stream carries no planned
route (`emitter.py`: `nodeStates` holds only the first route node), so there is nothing to detour from.

## Findings the next step needs (not interpretation of the rule, measured on the real runs)

Full 10-zone runs, publish 60, bin 60 (flag-publishes summed over zones and publishes; wall 0-2 s per run):

| alpha | s10c-blind flag-publishes | s10-none flag-publishes |
|---|---|---|
| 1e-2 | 129 | 126 |
| 1e-3 (default) | 0 | 0 |
| 1e-4 | 0 | 0 |

At the default alpha and `min_expected` 10 the detector flags nothing on either run: on s10c-blind the busiest cell of the
run has 23 passes in 2,495 s and 441 of 4,273 (zone, cell) pairs reach 10, so few cells are eligible and the long gap
ln(1000)/r is rarely reached. At alpha 1e-2 it
flags 129 vs 126 flag-publishes on blind vs undisturbed, and the AMOC smoke shows 0/50 windows detected at K=20 with false
flags per publish 3.07 (smoke on the /tmp copy, not a result file). That is a smoke, not the measurement; the measurement is
the queue item below. `time_to_detect` raises on a measured store with zero forecast rows, so the queue command writes a stub
document `{"detector": "absence", "measured_forecast_rows": 0, "amoc": null}` for an alpha that flags nothing instead of
dying under `set -e`.

## Smoke (T4)

`fleet/tests/test_fleet_absencemap.py::TestRealDataSmoke::test_t4_smoke_on_real_zone0` RAN (not skipped; the real data is at
the absolute path), via subprocess: exit 0, wall 0.2 s (limit 120 s), real store `decisions.jsonl` sha unchanged, directory
listing unchanged. Printed line:

```
absencemap smoke s10c-blind zone 0: 42 publishes, 0 distinct flagged cells, 0 flag-publishes, 0.2s
```

Flagged cells on s10c-blind zone 0 at the default alpha: 0 (see the table above: none in any zone).
The smoke builds a temp layout with the zone0 files and the store SYMLINKED (the brief said copy the store; a symlink keeps
the original-store hash guard on the real file, and nothing is written under fleet/data).

## Byte identity of the S10I prebuilt command

Command (cwd = the worktree with `fleet/data/s10c-blind` and `fleet/data/s10-none` temporarily symlinked to the main
checkout's, removed afterwards, never committed; this makes `meta.phase_a_dir` the relative `fleet/data/s10c-blind` that the
tracked file holds):

```
.venv/bin/python fleet/time_to_detect.py --phase-a fleet/data/s10c-blind --truth-kind blocked --publish-every 60 --top-k 20 --sweep-k 5,10,20,40 --reference fleet/data/s10-none --store-suffix fast --out /tmp/s14b-af-<before|after>.json
```

- before the change (master code): `1b3bcc7cf98326efdc0e67b783858a521bddbb9224767b5b5ab233ce4421ed06`
- after the change: `1b3bcc7cf98326efdc0e67b783858a521bddbb9224767b5b5ab233ce4421ed06`
- tracked `results/fleet/amoc_fast.json`: `1b3bcc7cf98326efdc0e67b783858a521bddbb9224767b5b5ab233ce4421ed06` (not modified).

## Tests

`fleet/tests/test_fleet_absencemap.py`: T1 (exact first flag bin by independent per-bin-end stepping, (4,4) the only
flagged cell, frozen rate, release at the first bin end after the re-crossing), T2 (9 passes never flag, 10 do), T3
(standing still = one pass), T4 (real-data smoke), T5 (copy guard: original store, `store`-named dir, glob dir, inside the
store, a parent, non-jsonl; nothing deleted), T6 (determinism: `--out` bytes equal; decision rows equal except the store's
wall-clock `recorded_at` stamp, the same exception test_fleet_fastmap makes), T7 (exact claim keys, detector `absence`),
plus flag validation and a no-`truth` / no-redefinition scan. `fleet/tests/test_time_to_detect.py`: T8
(`TestPrebuiltDetector.test_t8...`: absence store accepted and recorded, cusum output has no `detector` key and its key
order is unchanged), T9 (mixed or unknown detectors raise) and a reference-agreement test.
Mutation spot checks run by hand: `>=` to `>` on the eligibility count fails T2; an unfrozen observed time fails T1 and T2.
`absencemap.py` is in the required-names set of `test_no_ground_truth_in_analyst_code` and in no exemption tuple;
`grep -n truth fleet/absencemap.py` is empty.

## Queue command wr-s14b-amoc-run

cores 4, ram_gb 2, est_minutes 3, max_minutes 20. Basis: absencemap 0-2 s per run (10 zones in one process) x 2 runs x 4
builds, plus 3 ttd runs of about 2 s each; the whole command measured 11 s wall in the /tmp smoke below; the S10I fast run
took 1.0 min for fastmap + ttd on both runs. Run from the repo root.

```zsh
setopt shwordsplit 2>/dev/null || true
set -e
P=.venv/bin/python
RUNS="s10c-blind s10-none"
sums() { find "$1" -type f | sort | xargs shasum -a 256; }
snap() { { for R in $RUNS; do sums "fleet/data/$R/store"; done; ls results/fleet/*.json | grep -v '/amoc_absence' | sort | xargs shasum -a 256; } > "$1"; }
H0=$(mktemp); H1=$(mktemp)
snap "$H0"
mkdir -p results/fleet
build() {
  for R in $RUNS; do
    $P fleet/absencemap.py --glob "fleet/data/$R/*.jsonl.gz" --run "$R" --store "jsonl:fleet/data/$R/store-$1" --publish-every 60 $2 --out "fleet/data/$R/absencemap$3.json"
  done
}
amoc() {
  # time_to_detect refuses a measured store with zero forecast rows; an alpha that flags nothing gets a stub document
  if grep -q absence "fleet/data/s10c-blind/store-$1/decisions.jsonl"; then
    $P fleet/time_to_detect.py --phase-a fleet/data/s10c-blind --truth-kind blocked --publish-every 60 --top-k 20 --sweep-k 5,10,20,40 --reference fleet/data/s10-none --store-suffix "$1" --out "$2"
  else
    echo "wr-s14b-amoc-run: store-$1 flagged nothing on s10c-blind; no AMOC, stub document"
    $P -c 'import json,sys; json.dump({"detector": "absence", "store_suffix": sys.argv[1], "measured_forecast_rows": 0, "amoc": None}, open(sys.argv[2], "w"), indent=1)' "$1" "$2"
  fi
}
build absence "" ""
amoc absence results/fleet/amoc_absence.json
for A in 1e-2 1e-3 1e-4; do
  build "absence-a$A" "--alpha $A" "-a$A"
  amoc "absence-a$A" "results/fleet/amoc_absence_a$A.json"
done
$P -c 'import json,sys; out={a: json.load(open("results/fleet/amoc_absence_a%s.json" % a)) for a in ("1e-2","1e-3","1e-4")}; json.dump(out, open("results/fleet/amoc_absence_sweep.json","w"), indent=1)'
snap "$H1"
if ! cmp -s "$H0" "$H1"; then echo "S14B amoc run: an original store or a pre-existing results/fleet/*.json changed" >&2; diff "$H0" "$H1" >&2 || true; exit 1; fi
echo "SCHED_RESULT: OK wr-s14b-amoc-run absence detector on s10c-blind + s10-none, AMOC alpha 1e-3 + sweep 1e-2/1e-3/1e-4 -> results/fleet/amoc_absence*.json, originals unchanged"
```

Smoke of the whole command on a /tmp copy (zone files symlinked, store + truth + ledger copied, `fleet/data/` and
`results/fleet` rewritten by sed to `/tmp/s14b-smoke/...`, run from the worktree so the lane's code ran): exit code 0, wall
11 s. The real `fleet/data/s10c-blind/store/decisions.jsonl` and `fleet/data/s10-none/store/decisions.jsonl` hashes and the
real `results/fleet` listing were identical before and after. Outputs in the /tmp tree: `amoc_absence.json`,
`amoc_absence_a1e-{2,3,4}.json`, `amoc_absence_sweep.json`; the a1e-2 document has keys
`schema_version, detector, meta, by_k, amoc` with `detector` `absence` and `store_mode` prebuilt for both runs.
Note: the hash-guard excludes `amoc_absence*.json` by the regexp `/amoc_absence`, and the command only writes
`fleet/data/<run>/store-absence*` and `absencemap*.json` outside results/.

## Gate

GATE_PLACEHOLDER

SCHED_RESULT: OK wr-lane-s14b-traffic-absence PR open against master, not merged

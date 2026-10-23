# wr-dev-s16-readme: README (x) and SCOPE Sprint 16

Date 2026-10-23. Unattended docs job (laptop scheduler). Docs direct to master, explicit paths, not pushed (local master
holds the unpushed public-repo prep commits).

## What was written

- README "Sprint 16" section with tables (x1) time budget `-sb` / `-sf` with `faulted` computed, (x2) causes before /
  after the diagnostics lookup with the noise family named, (x3) dispatcher events and the cleaning three-way split;
  Part 9 section 5 refute lines answered with numbers; caveats.
- docs/SCOPE.md "Sprint 16" block (shape of Sprint 15): ticks, three refute verdicts, one new finding, open operator
  questions.
- Committed with them: `results/fleet/moroop_faults.json`, `results/fleet/moroop_dispatch.json`,
  `results/fleet/moroop_label-sf.json`, `results/fleet/timebudget_moroop-sf.json`,
  `results/fleet/timebudget_moroop_shifts-sf.json` (untracked before; written by `wr-s16a-run` and `wr-s16b-run`, both
  exit 0). grep for `/Users/` and `/tmp/` in the five files: no match. The `-sb` files the tables also read were
  already tracked.

## Verdicts (from the files)

- S16A: mixed (`moroop_faults.json` `verdict`). Overlaps 0/47 s and 1/133 s; driving share 58/585 = 0.099.
- S16B dispatcher: marks the intervention (`moroop_dispatch.json` `verdicts.dispatcher`); external resume 46.6 s
  after the 3,245 s episode.
- S16B cleaning: file says "we keep theirs" = Part 9's "our ingest keeps rows the authors removed": rule drops 0 of
  2,959, 2,959 pass.

## Deviations from the brief

1. The brief puts the "not computed" faulted row and the undocumented-levels bullet in (r). They are in (q)
   (README table (q) and its third caveat). (x1) says so and supersedes the (q) caveat "in part": Part 9 identified
   the levels at rank B (inferred), wheel.me's own docs are UNTESTED, so "sourced" would overstate it. Part 9
   section 1's correction sentence is quoted verbatim.
2. (x1) compares `-sf` against `-sb`, not against (q): `-sf` = `-sb` + `--faults`, and `--faults` moves the stuck,
   stopped_short, waiting_station, moving and idle buckets too (pooled deltas sum to 0, printed).
3. The forbidden `faulted_self` cause label still sits in `moroop_label-sf.json` / `timebudget_moroop-sf.json`
   (`cause_label`). The printer substitutes `public_label` ("Robot reported a component error"); the new README text
   was grepped for "cannot continue": 0 matches in section (x) (the one README match is the pre-existing simulator
   row in (v)).
4. README.md had an uncommitted front-page rewrite in the working tree (not this job's). It was NOT committed: the
   committed README is `HEAD:README.md` + section (x); the working tree is the draft + section (x) again. The draft
   has two lines that are now stale ("0 rejected by our parser", "Sprint 16B, queued, not measured"); they are listed
   in the SCOPE open questions, the draft was not edited.

## Checks

- Tests that read docs or the S16 code: `.venv/bin/python -m unittest fleet.tests.test_fleet_s8o_step4_label
  fleet.tests.test_s8k_overview fleet.tests.test_s8j_page fleet.tests.test_fleet_moroop_faults
  fleet.tests.test_fleet_moroop_dispatch`: Ran 129 tests, FAILED (failures=1). The failure is
  `test_s8k_overview.TestWords.test_footer_paths_are_visible_and_pass`: it expects
  `laptop-scheduler/reports/wr-s8e-lessons-long.md` in the committed `docs/overview` footer. Observed with `git show
  <rev>:...  | grep -c`: the page has the string at bacfab7~1 (1) and not from bacfab7 on (0 at bacfab7, 233f82f and
  HEAD~1), while the test expects it at all four. So the test is red on local master since bacfab7, before this
  commit; 233f82f's message reports a green gate, which this does not explain (not inspected). This diff touches no
  file under docs/overview or fleet/tests. S17A gates on local master and will meet this red test. No test reads the root README content (grep of tests and
  fleet/tests). The full gate (~13 min) was not run: this commit is docs plus result JSON only.
- Every number in (x1)-(x3) comes from the printer output below or is a sum or difference of printed values (51 =
  20 + 1 + 29 + 1 combinations; 06:01:31 to 06:16:31 = 15 min), except "39 start denials" in the (x3) class header,
  read from `moroop_dispatch.json` `pooled.per_kind.operation_start_denied.count` (39) and not printed by the script.

## The printer (read-only, run as `python3 -I /tmp/wr_s16/s16_tables.py results/fleet`)

```python
"""Read-only printer for README (x), Sprint 16. Reads five results files, writes nothing."""
import json
import sys

R = sys.argv[1] if len(sys.argv) > 1 else "results/fleet"


def load(name):
    with open(f"{R}/{name}") as fh:
        return json.load(fh)


tb_sb = load("timebudget_moroop-sb.json")
tb_sf = load("timebudget_moroop-sf.json")
sh_sb = load("timebudget_moroop_shifts-sb.json")
sh_sf = load("timebudget_moroop_shifts-sf.json")
lab_sb = load("moroop_label-sb.json")
lab_sf = load("moroop_label-sf.json")
flt = load("moroop_faults.json")
dsp = load("moroop_dispatch.json")
PUBLIC = flt["public_label"]


def pct(x, nd=2):
    return x if isinstance(x, str) else f"{100 * x:.{nd}f}%"


def cnt(x):
    return x if isinstance(x, str) else f"{x:,}"


# ---- table (x1): time budget, -sb next to -sf ----
print("#### (x1)\n")
order = ["moving", "waiting_station", "waiting_shelf", "stuck", "stopped_short", "faulted", "idle", "paused", "no_data"]
print("| bucket | -sb s | -sb share | -sf s | -sf share | delta s |")
print("|---|---|---|---|---|---|")
tot = 0
for b in order:
    a, c = tb_sb["seconds"][b], tb_sf["seconds"][b]
    if isinstance(a, int) and isinstance(c, int):
        d = c - a
        tot += d
        ds = f"{d:+,}"
    elif isinstance(c, int):
        d = c
        tot += d
        ds = f"+{c:,} (was {a})"
    else:
        ds = "n/a"
    print(f"| {b} | {cnt(a)} | {pct(tb_sb['share'][b])} | {cnt(c)} | {pct(tb_sf['share'][b])} | {ds} |")
print(f"| span | {tb_sb['span_s']:,} | | {tb_sf['span_s']:,} | | sum of deltas {tot:+d} |")
print()
print("| shift | faulted s, -sf | faulted share of span | faulted s from raw (moroop_faults) | stuck s -sb | stuck s -sf |")
print("|---|---|---|---|---|---|")
for k in sorted(sh_sf["faulted"], key=int):
    f = sh_sf["faulted"][k]
    raw = flt["table_a"]["per_shift"][k]["faulted_s"]
    name = sh_sf["shifts"][k]["name"]
    s_b = sh_sb["shifts"][k]["timebudget_robot"]["seconds"]["stuck"]
    s_f = sh_sf["shifts"][k]["timebudget_robot"]["seconds"]["stuck"]
    print(f"| {k}: {name} | {f['seconds']} | {pct(f['share'], 3)} | {raw} | {s_b} | {s_f} |")
cc = flt["cross_check"]
p = flt["table_a"]["pooled"]
print(f"| **pooled** | {tb_sf['faulted']['seconds']} | {pct(tb_sf['faulted']['share'], 3)} | {p['faulted_s']} | "
      f"{tb_sb['seconds']['stuck']} | {tb_sf['seconds']['stuck']} |")
print(f"\ncross_check: bucket {cc['faulted_bucket_seconds']} vs raw {cc['faulted_seconds_from_raw']}, "
      f"difference {cc['difference']}: {cc['note']}")
print(f"raw faulted while driving {p['faulted_driving_s']} of {p['faulted_s']} (share {p['driving_share']:.3f}), "
      f"in paused rows {p['faulted_paused_s']}")
print(f"label counts -sb {lab_sb['pooled']['counts']}")
print(f"label counts -sf {lab_sf['pooled']['counts']}")

# ---- table (x2): causes before/after ----
print("\n#### (x2)\n")
print("| cause | public label | -sb episodes | -sb s | -sf episodes | -sf s |")
print("|---|---|---|---|---|---|")
cb = {r["cause"]: r for r in lab_sb["pooled"]["causes"]["table"]}
cf = {r["cause"]: r for r in lab_sf["pooled"]["causes"]["table"]}
for c in ["station_overrun", "faulted_self", "unknown"]:
    lb = cb.get(c) or cf.get(c)
    label = PUBLIC if c == "faulted_self" else lb["cause_label"]
    eb, sb_ = (cb[c]["episodes"], cb[c]["seconds"]) if c in cb else (0, 0)
    ef, sf_ = (cf[c]["episodes"], cf[c]["seconds"]) if c in cf else (0, 0)
    print(f"| {c} | {label} | {eb} | {sb_:,} | {ef} | {sf_:,} |")
print()
print("| shift | start | s | cause -sb | cause -sf | s under an Error status (share) | statuses over the stall |")
print("|---|---|---|---|---|---|---|")
sbmap = {(e["shift"], e["start"]): e for e in flt["table_b"]["sb"]}
for e in flt["table_b"]["sf"]:
    b = sbmap.get((e["shift"], e["start"]))
    st = "; ".join(f"{s['name']} \"{s['message']}\" {s['seconds']} s" for s in e["statuses"]) or "none"
    print(f"| {e['shift']} | {e['start']} | {e['duration_s']} | {b['cause'] if b else 'no episode'} | {e['cause']} | "
          f"{e['faulted_overlap_s']} ({e['faulted_overlap_share']:.3f}) | {st} |")
for e in flt["table_b"]["sb"]:
    if not any((x["shift"], x["start"]) == (e["shift"], e["start"]) for x in flt["table_b"]["sf"]):
        print(f"| {e['shift']} | {e['start']} | {e['duration_s']} | {e['cause']} | no episode | "
              f"{e['faulted_overlap_s']} | |")
print()
noise = [r for r in flt["table_c"] if r["class"] == "noise"]
for r in noise:
    print(f"noise: {r['name']} \"{r['message']}\" at {r['level']}: {r['status_rows']:,} rows, {r['seconds']:,} s, "
          f"source {r['source']}")
from collections import Counter
print("table_c classes:", dict(Counter((r["class"], r["level"]) for r in flt["table_c"])))
print("verdict:", flt["verdict"], "|", flt["verdict_sentence"])
for e in flt["verdict_inputs"]["episodes"]:
    print(f"  sb unknown {e['shift']} {e['start']} {e['duration_s']} s overlap {e['faulted_overlap_s']} "
          f"({e['faulted_overlap_share']:.3f})")
print("pooled driving share", round(flt["verdict_inputs"]["pooled_driving_share"], 3))
fam = {f"{f['name']} | {f['message']}": f for f in p["families"]}
for k in flt["verdict_inputs"]["families_refuting_error_equals_stopped"]:
    f = fam[k]
    print(f"  refutes ERROR=stopped: {k}: {f['driving_s']} of {f['faulted_s']} s driving ({f['driving_share']:.2f})")
for f in sorted(p["families"], key=lambda f: -f["faulted_s"])[:4]:
    print(f"  largest: {f['name']} | {f['message']}: {f['faulted_s']} s, driving {f['driving_share']:.2f}")

# ---- table (x3): dispatcher events and cleaning ----
print("\n#### (x3)\n")
po = dsp["pooled"]
print("| class | events |")
print("|---|---|")
for k, v in po["classes"].items():
    print(f"| {k} | {v} |")
print(f"\nauto_pauses {po['auto_pauses']}, interventions {po['interventions']}, resumes_vs_pauses {po['resumes_vs_pauses']}")
print("\n| shift | event | time | class | inside a stuck episode | after a stuck episode | intervention |")
print("|---|---|---|---|---|---|---|")
for i, s in enumerate(dsp["shifts"]):
    for e in s["events"]:
        if e["kind"] in ("operation_dispatcher_paused", "operation_dispatcher_resumed") and e["cls"] != "shift start":
            ie = e["in_episode"]
            na = e["near_after"]
            ins = f"{ie['duration_s']} s episode, {ie['delta_s']:.1f} s in" if ie else "no"
            aft = f"{na['delta_s']:.1f} s after the {na['duration_s']} s episode" if na else "no"
            kind = e["kind"].replace("operation_dispatcher_", "")
            ap = " (auto-pause)" if e["auto_pause"] else ""
            print(f"| {i}: {s['shift']} | {kind}{ap} | {e['ts']} | {e['cls']} | {ins} | {aft} | "
                  f"{'yes' if e['intervention'] else 'no'} |")
cl = po["cleaning"]
au = cl["authors_only"]
print("\n| raw ids | count | share of authors-removed | collapse drops among them |")
print("|---|---|---|---|")
rem = cl["authors_removed"]
for name, blk in (("both drop (authors and our rules)", cl["both_drop"]), ("authors only", au),
                  ("ours only", cl["ours_only"])):
    print(f"| {name} | {blk['ids']:,} | {pct(blk['ids'] / rem, 1)} | {blk['collapse_drops']:,} |")
print(f"\nraw {cl['raw_rows']:,}, cleaned {cl['cleaned_rows']:,}, authors removed {rem:,} "
      f"({pct(rem / cl['raw_rows'], 1)}), rule drops {cl['rule_drops']}, collapse drops {cl['collapse_drops']:,} "
      f"(in no set {cl['collapse_drops_in_no_set']:,}), cleaned ids not in raw {cl['cleaned_ids_not_in_raw']}")
print("authors-only state", au["state"], "mode", au["operating_mode"], "diag", au["diagnostics_max_level"])
print("authors-only ranges", {k: (round(v["min"], 2), round(v["max"], 2), v["none_or_nonfinite"])
                              for k, v in au["ranges"].items()})
print("verdicts", dsp["verdicts"], "| page_sentence_holds", dsp["page_sentence_holds"])
print("page_sentence:", dsp["page_sentence"])
```

## Its output

```
#### (x1)

| bucket | -sb s | -sb share | -sf s | -sf share | delta s |
|---|---|---|---|---|---|
| moving | 106,171 | 40.41% | 106,113 | 40.39% | -58 |
| waiting_station | 107,005 | 40.73% | 107,188 | 40.80% | +183 |
| waiting_shelf | n/a | n/a | n/a | n/a | n/a |
| stuck | 1,773 | 0.67% | 1,264 | 0.48% | -509 |
| stopped_short | 1,870 | 0.71% | 1,763 | 0.67% | -107 |
| faulted | not computed | not computed | 508 | 0.19% | +508 (was not computed) |
| idle | 25,767 | 9.81% | 25,750 | 9.80% | -17 |
| paused | 161 | 0.06% | 161 | 0.06% | +0 |
| no_data | 19,970 | 7.60% | 19,970 | 7.60% | +0 |
| span | 262,717 | | 262,717 | | sum of deltas +0 |

| shift | faulted s, -sf | faulted share of span | faulted s from raw (moroop_faults) | stuck s -sb | stuck s -sf |
|---|---|---|---|---|---|
| 0: 2026_07_27_morning | 31 | 0.106% | 31 | 0 | 0 |
| 1: 2026_07_27_evening | 42 | 0.145% | 42 | 160 | 152 |
| 2: 2026_07_28_morning | 98 | 0.330% | 98 | 0 | 0 |
| 3: 2026_07_28_evening | 28 | 0.096% | 28 | 0 | 0 |
| 4: 2026_07_29_morning | 37 | 0.128% | 37 | 0 | 0 |
| 5: 2026_07_29_evening | 50 | 0.172% | 50 | 0 | 0 |
| 6: 2026_07_30_morning | 35 | 0.119% | 35 | 1107 | 1107 |
| 7: 2026_07_31_morning | 120 | 0.415% | 197 | 282 | 5 |
| 8: 2026_07_31_evening | 67 | 0.228% | 67 | 224 | 0 |
| **pooled** | 508 | 0.193% | 585 | 1773 | 1264 |

cross_check: bucket 508 vs raw 585, difference 77: the bucket loses seconds to no_data, which outranks faulted
raw faulted while driving 58 of 585 (share 0.099), in paused rows 0
label counts -sb {'episodes': 77, 'false_alarms': 5, 'ge30': 2, 'hits': 2, 'lt30': 75, 'misses': 0, 'stuck_runs': 6, 'timeouts': 8, 'timeouts_detected': 5}
label counts -sf {'episodes': 77, 'false_alarms': 3, 'ge30': 2, 'hits': 2, 'lt30': 75, 'misses': 0, 'stuck_runs': 4, 'timeouts': 8, 'timeouts_detected': 3}

#### (x2)

| cause | public label | -sb episodes | -sb s | -sf episodes | -sf s |
|---|---|---|---|---|---|
| station_overrun | Station stop over time limit | 4 | 4,250 | 2 | 3,563 |
| faulted_self | Robot reported a component error | 0 | 0 | 8 | 1,237 |
| unknown | Stopped, cause not identified | 2 | 180 | 1 | 47 |

| shift | start | s | cause -sb | cause -sf | s under an Error status (share) | statuses over the stall |
|---|---|---|---|---|---|---|
| 1 | 2026-07-27T19:03:16Z | 318 | station_overrun | station_overrun | 8 (0.025) | /Wheels "Error" 8 s; /Wheels/FL "Lidar: Calibrating" 8 s |
| 2 | 2026-07-28T09:24:05Z | 41 | no episode | faulted_self | 41 (1.000) | /System "Error" 41 s; /System/Clock "Not synchronized" 41 s |
| 6 | 2026-07-30T06:16:31Z | 3245 | station_overrun | station_overrun | 0 (0.000) | none |
| 6 | 2026-07-30T07:10:44Z | 47 | unknown | unknown | 0 (0.000) | none |
| 6 | 2026-07-30T07:35:38Z | 37 | no episode | faulted_self | 2 (0.054) | /Wheels "Error" 2 s; /Wheels/FL "Lidar: Calibrating" 2 s |
| 6 | 2026-07-30T10:53:31Z | 36 | no episode | faulted_self | 2 (0.056) | /Wheels "Error" 2 s; /Wheels/BR "Lidar: Calibrating" 2 s |
| 7 | 2026-07-31T06:42:16Z | 41 | no episode | faulted_self | 2 (0.049) | /Wheels "Error" 2 s; /Wheels/BR "Lidar: Calibrating" 2 s |
| 7 | 2026-07-31T10:00:24Z | 343 | station_overrun | faulted_self | 7 (0.020) | /Wheels "Error" 7 s; /Wheels/BR "Lidar: Calibrating" 7 s |
| 7 | 2026-07-31T12:18:25Z | 262 | no episode | faulted_self | 164 (0.626) | /Navigation "Error" 164 s; /Navigation/Robot Stuck ": Goal is obstructed. Remove obstacle from goal location." 164 s |
| 7 | 2026-07-31T12:23:06Z | 133 | unknown | faulted_self | 1 (0.008) | /Navigation "Error" 1 s; /Navigation/Robot Stuck ": Goal is obstructed. Remove obstacle from goal location." 1 s |
| 8 | 2026-07-31T17:43:15Z | 344 | station_overrun | faulted_self | 23 (0.067) | /Wheels "Error" 23 s; /Wheels/BR "Lidar: Calibration failed" 23 s |

noise: /Devices/Camera "Frequency too high." at Warning: 1,830 rows, 3,685 s, source diagnostic_updater FrequencyStatus, rank A, Part 9 section 2
table_c classes: {('faulted by our rule', 'Error'): 20, ('unclassified', 'Stale'): 1, ('unclassified', 'Warning'): 29, ('noise', 'Warning'): 1}
verdict: mixed | n = 2: a description, not a rate
  sb unknown 6 2026-07-30T07:10:44Z 47 s overlap 0 (0.000)
  sb unknown 7 2026-07-31T12:23:06Z 133 s overlap 1 (0.008)
pooled driving share 0.099
  refutes ERROR=stopped: /Navigation/Robot Stuck | : Blocked by obstacle. Check robot surroundings.: 31 of 39 s driving (0.79)
  refutes ERROR=stopped: /Wheels/BL | Power Input: Not Charging.: 5 of 5 s driving (1.00)
  refutes ERROR=stopped: /Wheels/BR | Power Input: Not Charging.: 5 of 5 s driving (1.00)
  refutes ERROR=stopped: /Wheels/FL | Power Input: Not Charging.: 4 of 4 s driving (1.00)
  refutes ERROR=stopped: /Wheels/FR | Power Input: Not Charging.: 1 of 1 s driving (1.00)
  largest: /Wheels | Error: 310 s, driving 0.02
  largest: /Navigation | Error: 206 s, driving 0.16
  largest: /Navigation/Robot Stuck | : Goal is obstructed. Remove obstacle from goal location.: 167 s, driving 0.01
  largest: /Wheels/FL | Lidar: Calibrating: 159 s, driving 0.00

#### (x3)

| class | events |
|---|---|
| dispatcher refused | 41 |
| external call | 3 |
| neither | 10 |
| shift start | 9 |

auto_pauses 2, interventions 2, resumes_vs_pauses {'pauses': 3, 'resumes': 11, 'resumes_with_pause_precedes': 3, 'resumes_without_pause_precedes': 8}

| shift | event | time | class | inside a stuck episode | after a stuck episode | intervention |
|---|---|---|---|---|---|---|
| 6: 2026_07_30_morning | paused | 2026-07-30T06:01:31Z | external call | no | no | no |
| 6: 2026_07_30_morning | paused (auto-pause) | 2026-07-30T06:21:15Z | dispatcher refused | 3245 s episode, 284.2 s in | no | no |
| 6: 2026_07_30_morning | resumed | 2026-07-30T07:11:22Z | external call | 47 s episode, 38.6 s in | 46.6 s after the 3245 s episode | yes |
| 7: 2026_07_31_morning | paused (auto-pause) | 2026-07-31T12:23:29Z | dispatcher refused | 127 s episode, 18.7 s in | 42.7 s after the 250 s episode | no |
| 7: 2026_07_31_morning | resumed | 2026-07-31T12:25:42Z | external call | no | 24.4 s after the 127 s episode | yes |

| raw ids | count | share of authors-removed | collapse drops among them |
|---|---|---|---|
| both drop (authors and our rules) | 0 | 0.0% | 0 |
| authors only | 2,959 | 100.0% | 1,314 |
| ours only | 0 | 0.0% | 0 |

raw 140,386, cleaned 137,427, authors removed 2,959 (2.1%), rule drops 0, collapse drops 6,444 (in no set 5,130), cleaned ids not in raw 0
authors-only state {'Idle': 314, 'Navigating': 2645} mode {'Autonomous': 2959} diag {'Error': 2, 'Ok': 2758, 'Warning': 184, 'none': 15}
authors-only ranges {'pos_x': (0.39, 8.21, 0), 'pos_y': (-1.84, 0.41, 0), 'velocity_omega': (-0.3, 0.4, 0), 'velocity_x': (-0.01, 0.8, 0), 'velocity_y': (-0.07, 0.16, 0)}
verdicts {'cleaning': 'we keep theirs', 'dispatcher': 'marks the intervention'} | page_sentence_holds True
page_sentence: No row of the authors' cleaned table was rejected by our parser; the authors had already removed 2,959 of 140,386 raw rows (2.1 %)
```

# wr-dev-s15-readme: Sprint 15 docs pass (README (w), SCOPE Sprint 15, COMPETITION pointer)

Docs job, 23 Oct 2026, unattended. Committed to local master and **not pushed**: local master still holds the 7
public-repo prep commits the operator asked to hold.

## Inputs

- `results/fleet/stall_baseline.json` was written by `wr-s15a-run` (laptop-scheduler `state/done.json`: exit 0,
  finished 12:35:33, 1.0 min). Its log ends `SCHED_RESULT: OK ... refute line (Part 8 s3): commodity via N0-60`.
  `smoke` is false.
- `results/fleet/duration_spread.json` was written by `wr-s15b-run` (exit 0, finished 12:20:31, 1.0 min). Its log
  ends `SCHED_RESULT: OK wr-s15b-run verdict=mixed`. `smoke` is false.
- Both files were untracked. They are committed in this commit, by explicit path. `hotspot_blind.json`,
  `hotspot_none.json` and the `closed_loop*` trees stay untracked and were not touched.

## What was written

- **README "Sprint 15"**, tables (w1) S15A and (w2) S15B, one per test. Each Part 8 section 3 line is answered
  explicitly:
  - **S15A: commodity.** N0-60 reaches 2/2 labelled hits with 10 stuck runs, against a line of ≤ 12. The documented
    InOrbit forms do not meet the line: N2-180 hits 1/2 with 7 runs, and N1 hits 0/2.
  - **S15B: mixed**, which is `verdict.verdict` in the file.
    - Median ρ against the blocking number: 0.13 for p95 / median and 0.06 for the mean.
    - A statistic is ≥ the blocking number on truth in 2 runs and 1 run.
    - The blocking number beats both statistics on truth in 3 of 5 runs.
  - New in "Reading the numbers": the median ρ(blocking, truth) is 0.04. The blocking figure does not rank zones by
    truth stuck time on these runs either.
- **SCOPE "Sprint 15"** follows the Sprint 14 block's shape: ticks, both verdicts, the new finding and six open
  operator questions.
- **COMPETITION**: one paragraph after the pass-4 table, pointing at README (w). No vendor cell changed (diff: 9 added
  lines, 0 removed).

## How the tables were made (nothing retyped)

`scripts/sprint8_tables.py` has no section (w). Adding one is code, so it is a lane item (listed in SCOPE). The two
tables were printed by the read-only script below, run as `python3 -I /tmp/s15docs/gen.py <repo>`, and pasted
verbatim. The secondary simulator sums in "Reading the numbers" come from its `SIM pooled` lines. The prose numbers
were read off the same output and the JSON fields named next to them.

```python
import json, sys
root = sys.argv[1]
sb = json.load(open(root + "/results/fleet/stall_baseline.json"))
ds = json.load(open(root + "/results/fleet/duration_spread.json"))
lab = sb["moroop"]["labels"]
print("| rule | stuck runs | labelled hits (of 2) | misses | false alarms | of them on a station cell | alerts spanning a > 60 s gap | alert latency, label 1 / label 2 (s) | 2/2 with <= 12 runs |")
print("|---|---|---|---|---|---|---|---|---|")
for r in sb["rules"]:
    v = sb["moroop"]["rules"][r]; c = v["counts"]
    lat = " / ".join("miss" if l["rules"][r]["alert_latency_s"] is None else str(l["rules"][r]["alert_latency_s"]) for l in lab)
    gap = v.get("gap_spanning_alerts"); gap = "n/a" if gap is None else str(gap)
    line = c["hits"] == c["ge30"] and c["stuck_runs"] <= 12
    print(f"| {r} | {c['stuck_runs']:,} | {c['hits']} | {c['misses']} | {c['false_alarms']:,} | {v['false_alarms_on_station_cell']:,} | {gap} | {lat} | {'reference' if r == 'ours' else ('yes' if line else 'no')} |")
for l in lab:
    print("LABEL", l["shift"], l["label_start"], l["label_duration_s"], l["stopped_run"]["duration_s"], l["box_stillness"]["duration_s"])
print()
print("SIM pooled: rule -> run: matched/truth, scored detected, precision")
for run, v in sb["sim"].items():
    parts = []
    for r in sb["rules"]:
        m = sum(z[r]["matched"] for z in v["zones"].values()); t = sum(z[r]["truth_episodes"] for z in v["zones"].values()); d = sum(z[r]["detected_episodes"] for z in v["zones"].values())
        parts.append(f"{r} {m}/{t} p={m/d if d else float('nan'):.2f}")
    print(run, "; ".join(parts))
print()
print("| run | zones | completed jobs | ρ(p95/median, blocking) | top-3 | ρ(mean, blocking) | top-3 | ρ(p95/median, truth) | ρ(mean, truth) | ρ(blocking, truth) | blocking beats both on truth |")
print("|---|---|---|---|---|---|---|---|---|---|---|")
f = lambda x: "null" if x is None else f"{x:.2f}"
for run, v in ds["runs"].items():
    a = v["agreement"]
    rb = a["blocking|truth"]["rho"]; rp = a["p95_over_median|truth"]["rho"]; rm = a["mean_s|truth"]["rho"]
    beats = rb > rp and rb > rm
    print(f"| {run} | {a['mean_s|blocking']['n']} | {v['counts']['completed']:,} | {f(a['p95_over_median|blocking']['rho'])} | {a['p95_over_median|blocking']['top3_overlap']}/3 | {f(a['mean_s|blocking']['rho'])} | {a['mean_s|blocking']['top3_overlap']}/3 | {f(rp)} | {f(rm)} | {f(rb)} | {'yes' if beats else 'no'} |")
s = ds["agreement_summary"]
print(f"| median over 5 runs | | | {f(s['p95_over_median|blocking']['median_rho'])} | {s['p95_over_median|blocking']['median_top3_fraction']:.2f} | {f(s['mean_s|blocking']['median_rho'])} | {s['mean_s|blocking']['median_top3_fraction']:.2f} | {f(s['p95_over_median|truth']['median_rho'])} | {f(s['mean_s|truth']['median_rho'])} | {f(s['blocking|truth']['median_rho'])} | {ds['verdict']['runs_blocking_beats_both_on_truth']} of {ds['verdict']['n_runs']} |")
print(json.dumps(ds["verdict"]["conditions"]), ds["verdict"]["verdict"], ds["verdict"]["both_median_rho_vs_blocking_below_0_4"])
for run, v in ds["runs"].items():
    a=v["agreement"]["blocking|truth"]; print(run, "bt p", a["tau_b_p"], "top3", a["top3_overlap"], "ties", a["ties_at_boundary"], {k:v["counts"][k] for k in ["ended_to_new_order","open_at_start","open_at_end","zones_below_min_jobs"]})
print("descr medians", {k: round(x["median_rho"],2) for k,x in s.items()})
```

## Checks

- **Doc-reading tests.** I ran `fleet.tests.test_s8k_overview`, `test_s8j_page`, `test_s8i_page`, `test_s8j_rebuild`,
  `test_fleet_detector`, `test_fleet_deadlock` and `test_s11a_explorer`: `Ran 174 tests`, **3 failures**.
  - The same 3 fail with my three files stashed: `test_s8k_overview` `...is_a_fresh_build` and
    `test_footer_paths_are_visible_and_pass`, and `test_s11a_explorer` `test_page_is_a_fresh_build`.
  - The cause is the `reports/` versus `laptop-scheduler/reports/` path drift the S15B lane report traced to
    `bacfab7`. This job did not cause it and did not fix it, because it is code (`overview_build.py`).
- **Full gate.** Not run. Docs only, and the gate takes about 13 min.
- **Cross-check.** The S15A dev-run counts in the lane report equal the queue run's counts (the table above against
  the lane report's table).

## Things the operator should know

- The S15A refute line reads **commodity**, so the page claim "our station filter removes the false alarms a naive
  rule raises" holds only against the 30 s rule. The sample is 2 labelled stops in one shift, and the margin is 1
  false alarm.
- LITERATURE Part 8 §1 says both labelled stops are hit by "one `driving`-false run of 133 s". The S15A file shows two
  stopped runs, 262 s (label 1) and 133 s (label 2). README follows the file. Part 8 was not edited.
- Ours alerts 413 s into the first labelled stop, after the label ended; N0-60 alerts at 98 s. The mechanism was not
  inspected (open question in SCOPE).
- Both result files contain absolute `/Users/...` paths. Scrub them before any public push.
- Nothing was pushed to origin.

## Correction after self-review (follow-up commit)

A review pass before closing found four wording errors in the first commit. All four are fixed in README and SCOPE:
- **The (w) intro misstated a vendor claim.** It said pass 4 found no readable vendor documenting a station-aware
  stall list. Pass 4 actually scored InOrbit column 11 present, as a rule a customer writes. The intro now says that.
- **"Its three beats" became "two of its three".** On s10c-blind the blocking number's ρ with truth (0.48) beats the
  statistics' (0.09 and -0.27). That is a real win, not one produced by a statistic going negative.
- **The top-3 evidence for s10c-blind is dropped.** s10-none also has a blocking|truth top-3 of 2, at ρ 0.00.
- **The "radius 1 / 300 s bound" guess for the 413 s alert is dropped.** The timestamps do not support it: a 300 s
  bound from the stop start at 1785500305 would fire at about 605, but the alert is at 718, which is label 2's alert
  time. That item now reads "not inspected".

# wr-dev-s18-readme: README (y) + summary row, SCOPE Sprint 18 (2026-10-30)

Unattended docs job. Precondition: `gh pr view 60 --json state` -> `{"state":"MERGED"}`; `git pull --ff-only` -> already
up to date at 4c50c3e. The results files are the ones committed with PR #60 (4c50c3e); the eight-hour queue item
`wr-s18a-run` was not run (queue note: skipped by the operator), so `s10-none-8h` / `s10c-blind-8h` are absent.

## What changed

- README intro "What did not": appended "keeping less of the log (report by exception, S18): identical, not worth it".
  Nothing added to "What survived".
- README summary table: one row, "Keeping less of the log (report by exception, S18)", placed right after the stall-list
  row (both are "works, but something cheaper does as well"; here the cheaper thing is gzip). Numbers at H = 30 s (the
  VDA 5050 heartbeat); H = 60 s is in (y). Where = (y).
- README notebook: `## Sprint 18: keeping less of the log (2026-10-30)` and `#### (y) Keeping less of the log (S18A)` after
  (x3): rung ladder, one table per run (every rung, both H), a first-identical summary table, the three Part 10
  references, the two required caveats (MoRoOp already change-only; VDA 5050 `state` change-only + 30 s heartbeat, so
  the sim ratio is the best case), the headerId-hole caveat and the not-run 8 h runs (both from the lane report), and
  the result file names.
- `docs/SCOPE.md`: `### Sprint 18` before "Compute and timing" with a dated close line: "2026-10-30: S18 CLOSED, verdict
  identical, not worth it". No Sprint 17 section was created.

## Verdict word

`heartbeat.<H>.verdict` is `identical` in all four (run, H) cells; ratio_gzip at the first identical rung is below 3 in
all four. So the row says "Identical, not worth it" (the lane report's wording is "not worth pitching").

## Provenance: the read-only script and its output

Every number in the tables and the row was printed by this script from the two results files (run with `python3 -I
/tmp/s18gen/gen.py <repo>`). Rungs are printed in ladder order R0-R5 (the JSON stores them alphabetically, which puts
`threshold` last), and the script asserts that the first identical rung after `all` equals `first_identical_rule`, and
that its ratio_gzip equals `ratio_gzip_at_first_identical_rule`, in all four cells (both asserts passed).

```python
import json, sys
ROOT = sys.argv[1]
ORDER = ["all", "change", "gap", "threshold", "neighbours", "recovered"]
OUTS = ["time_budget", "stall_list", "transitions", "station_bound", "s15a_rules", "label_hits"]
FILES = [("s10-none", "results/fleet/reduce_s10-none.json"), ("moroop-sf", "results/fleet/reduce_moroop-sf.json")]
def diff(v):
    bad = []
    for o in OUTS:
        x = v["outputs"][o]
        if x in ("identical", "not_applicable"): continue
        bad.append(f"{o} {x['count']:,}")
    return "none" if not bad else ", ".join(bad)
summ = {}
for run, f in FILES:
    d = json.load(open(f"{ROOT}/{f}"))
    assert set(d["heartbeat"]["30"]["rungs"]) == set(ORDER)
    na = [o for o in OUTS if not d["applicable"][o]]
    print(f"**{run}** (`{f}`): {d['robots']} robots, {d['robot_hours']:.1f} robot-hours, "
          f"{d['heartbeat']['30']['rungs']['all']['lines_in']:,} lines in, "
          f"{d['heartbeat']['30']['rungs']['all']['kept_lines_per_robot_hour']:.1f} lines per robot-hour in; "
          f"outputs not applicable: {', '.join(na) if na else 'none'}.\n")
    print("| rung | H | lines kept | line ratio | ratio_gzip | kept lines/robot-h | outputs that differ (items) | identical |")
    print("|---|---|---|---|---|---|---|---|")
    for r in ORDER:
        for hb in ("30", "60"):
            v = d["heartbeat"][hb]["rungs"][r]
            print(f"| {r} | {hb} s | {v['lines_kept']:,} | {v['line_ratio']:.4f} | {v['ratio_gzip']:.4f} | "
                  f"{v['kept_lines_per_robot_hour']:.1f} | {diff(v)} | {'yes' if v['all_identical'] else 'no'} |")
    print()
    for hb in ("30", "60"):
        h = d["heartbeat"][hb]
        first = next(r for r in ORDER[1:] if h["rungs"][r]["all_identical"])
        assert first == h["first_identical_rule"], (run, hb, first)
        assert abs(h["rungs"][first]["ratio_gzip"] - h["ratio_gzip_at_first_identical_rule"]) < 1e-12
        v = h["rungs"][first]; s = v["sequence"]
        summ[(run, hb)] = (first, h["verdict"], v["ratio_gzip"], v["line_ratio"], s["sequence_gaps"], s["missing_messages"])
print("| run | H | first identical rung | verdict | ratio_gzip | line ratio | headerId gaps / missing at that rung |")
print("|---|---|---|---|---|---|---|")
for (run, hb), (first, verdict, rg, lr, g, m) in summ.items():
    print(f"| {run} | {hb} s | {first} | {verdict} | {rg:.4f} | {lr:.4f} | {g:,} / {m:,} |")
```

Output (pasted into README (y) verbatim):

**s10-none** (`results/fleet/reduce_s10-none.json`): 120 robots, 83.2 robot-hours, 60,000 lines in, 721.4 lines per robot-hour in; outputs not applicable: station_bound, s15a_rules, label_hits.

| rung | H | lines kept | line ratio | ratio_gzip | kept lines/robot-h | outputs that differ (items) | identical |
|---|---|---|---|---|---|---|---|
| all | 30 s | 60,000 | 1.0000 | 1.0000 | 721.4 | none | yes |
| all | 60 s | 60,000 | 1.0000 | 1.0000 | 721.4 | none | yes |
| change | 30 s | 33,340 | 1.7996 | 1.2646 | 400.9 | time_budget 117, stall_list 627, transitions 8,230 | no |
| change | 60 s | 33,340 | 1.7996 | 1.2646 | 400.9 | time_budget 117, stall_list 627, transitions 8,230 | no |
| gap | 30 s | 37,188 | 1.6134 | 1.2185 | 447.2 | stall_list 41, transitions 5,425 | no |
| gap | 60 s | 35,080 | 1.7104 | 1.2040 | 421.8 | time_budget 26, stall_list 233, transitions 6,470 | no |
| threshold | 30 s | 37,193 | 1.6132 | 1.2183 | 447.2 | stall_list 37, transitions 5,420 | no |
| threshold | 60 s | 35,732 | 1.6792 | 1.2088 | 429.6 | stall_list 40, transitions 5,420 | no |
| neighbours | 30 s | 39,746 | 1.5096 | 1.1843 | 477.9 | transitions 5,187 | no |
| neighbours | 60 s | 38,443 | 1.5608 | 1.1839 | 462.2 | transitions 5,187 | no |
| recovered | 30 s | 39,944 | 1.5021 | 1.1820 | 480.3 | none | yes |
| recovered | 60 s | 38,641 | 1.5528 | 1.1816 | 464.6 | none | yes |

**moroop-sf** (`results/fleet/reduce_moroop-sf.json`): 9 robots, 73.0 robot-hours, 132,838 lines in, 1820.3 lines per robot-hour in; outputs not applicable: none.

| rung | H | lines kept | line ratio | ratio_gzip | kept lines/robot-h | outputs that differ (items) | identical |
|---|---|---|---|---|---|---|---|
| all | 30 s | 132,838 | 1.0000 | 1.0000 | 1820.3 | none | yes |
| all | 60 s | 132,838 | 1.0000 | 1.0000 | 1820.3 | none | yes |
| change | 30 s | 132,740 | 1.0007 | 1.0004 | 1818.9 | time_budget 1, transitions 2, s15a_rules 4 | no |
| change | 60 s | 132,740 | 1.0007 | 1.0004 | 1818.9 | time_budget 1, transitions 2, s15a_rules 4 | no |
| gap | 30 s | 132,801 | 1.0003 | 1.0001 | 1819.8 | transitions 1 | no |
| gap | 60 s | 132,785 | 1.0004 | 1.0002 | 1819.5 | transitions 1 | no |
| threshold | 30 s | 132,802 | 1.0003 | 1.0001 | 1819.8 | none | yes |
| threshold | 60 s | 132,786 | 1.0004 | 1.0002 | 1819.6 | none | yes |
| neighbours | 30 s | 132,802 | 1.0003 | 1.0001 | 1819.8 | none | yes |
| neighbours | 60 s | 132,786 | 1.0004 | 1.0002 | 1819.6 | none | yes |
| recovered | 30 s | 132,802 | 1.0003 | 1.0001 | 1819.8 | none | yes |
| recovered | 60 s | 132,786 | 1.0004 | 1.0002 | 1819.6 | none | yes |

| run | H | first identical rung | verdict | ratio_gzip | line ratio | headerId gaps / missing at that rung |
|---|---|---|---|---|---|---|
| s10-none | 30 s | recovered | identical | 1.1820 | 1.5021 | 6,466 / 20,056 |
| s10-none | 60 s | recovered | identical | 1.1816 | 1.5528 | 5,481 / 21,359 |
| moroop-sf | 30 s | threshold | identical | 1.0001 | 1.0003 | 42 / 45 |
| moroop-sf | 60 s | threshold | identical | 1.0002 | 1.0004 | 44 / 61 |

## Gate

- `.venv/bin/python -m unittest discover -s tests`: `Ran 1313 tests in 957.921s` / `OK`.
- `tests/` has no README reader, so the page tests that read README files were run too:
  `.venv/bin/python -m unittest fleet.tests.test_s8j_page fleet.tests.test_s8i_page fleet.tests.test_s8k_overview`:
  `Ran 80 tests in 13.305s` / `OK`. (They read `docs/replay/README.md` and `docs/overview/README.md`, not the root README.)

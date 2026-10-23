# wr-lane-s10h-persistence-on-pages — persistence baseline next to every map precision

Date: 2026-10-19. Lane `single-lane-build`, tier standard, buildModel sonnet, base master.

**Outcome: MERGED.** PR #43 was squash-merged as **a83c9a4**, and local master was fast-forwarded to it. The lane took 2 passes.
- Pass 2 review round was clean: 0 of 4 refuters refuted (correctness, test-honesty, scope-adherence, invariants).
- python-reviewer passed with minors only.
- The CI `gate` check passed in 21m21s.

## What changed

**Exporter (`fleet/replay_export.py`)**
- New repeatable flag `--baselines LABEL=PATH`. It writes `run_constants.baselines`, one entry per label, in the order the flags are given.
- Each entry carries:
  - `label`, `src`, `n_zones`, `horizon_s`, `chance_all`, `chance_ever`.
  - Per K in 20 and 40: `map` and `persistence` (`truth_precision`, `pai`, `lift_all`, `lift_ever`), plus `paired` (`mean`, `ci95`, `verdict`).
  - `lesson_persist`, which is null when `n_lessons` is 0.
- The flag is wired into `--refresh-constants-only` and into `RUN_CONSTANTS_ORDER`.
- Bad input exits 2 and leaves data.js unchanged. Bad input means a spec without `=`, a file without a `baselines` key, a missing K, or a missing file.

**`docs/replay/data.js`**
- Regenerated with `--refresh-constants-only` from the five files, in this order: s8b-medium-80-p03-07, closed-loop-sticky, s8e-long-w0.5, s10c-blind, s10-none.
- The parsed payload differs from master only by `run_constants.baselines`. The builder checked this, and the correctness refuter checked it again on head 1ed50f0.

**Overview (`fleet/overview_build.py` → `docs/overview/index.html`)**
- A fresh build is byte-identical to the committed page (checked by the refuter with `cmp`).
- Step 3 keeps the 97%, relabelled "End-of-shift score against the planted cells". That number comes from `hotspot_s8b…:mean.k.20.precision`, which is a different score: per area, at end of shift, against the planted floor cells.
- Under it, a separate line: "A different test, against the hidden truth over the next 21 minutes: the map's top 20 were right 92.5%, the top 20 by last hour's plain counts 93.3%; the map is within noise."
- Step 4 adds: "On that longer shift, against the hidden truth over the next 21 minutes: the map's top 20 were right 97.7%, the top 20 by last hour's plain counts 98.5%; the map is worse."
- The step-4 "still above" sentence gains both lifts:
  - 3.0× against cells that got stuck in the same half hour.
  - 3.3× against the cells that ever got stuck. This is `lift_ever`; the brief's word "stalled" is banned on the pages.
- A new block after step 3, "Does the map beat last hour's counts?", has four body sentences and a five-run figure:
  - Each row shows map vs counts at K 20, map minus counts in points with its ci95 whisker, the scoring window in minutes, and the verdict in bold.
  - The "Nothing planted" row (s10-none) reads "nothing planted to find", with no bars and no verdict.
- Opening sentences as shipped:
  > It does not, on any of the five runs: checked against the hidden truth, the cells that were busiest by last hour's plain counts are right about as often as the map's picks, and on one run more often. What does the work is finding the robots that got stuck and checking each call afterwards.
- Figure values (K 20, truth precision, map / counts, delta and ci95 in points, window, verdict):

  | Run | Map | Counts | Delta (ci95) | Window | Verdict |
  |---|---|---|---|---|---|
  | Floor | 92.5% | 93.3% | −0.8 (−2.0 to 0.5) | 21 min | within noise |
  | Sticky floor | 95.5% | 95.3% | 0.2 (−1.0 to 1.7) | 60 min | within noise |
  | Long shift | 97.7% | 98.5% | −0.8 (−1.9 to −0.2) | 21 min | worse |
  | Hidden blockage | 0.8% | 0.9% | −0.1 (−0.2 to 0.0) | 21 min | within noise |
  | Nothing planted | — | — | — | — | — |

**Replay page (`docs/replay/replay.js`)**
- New `VISIBLE_COPY.persist.context` sentence (`#sentence-persist`, after `#s-right`, the panel-3 top-20 figure). It uses the s8b entry and is labelled "from a batch of other test areas with the same floor setup, not this shift".
  - The replay run s8i-demo-noise has no baselines file, so none was computed.
  - The hover (`HOVER_COPY.persistHover`) cites `src`, the delta and its range.
- `VISIBLE_COPY.lesson.long` carries the two lifts through a `{lifts}` slot, using the `lesson.lifts` sub-template.
- Both clauses are omitted when `baselines`, the entry or a value is missing. This null path is tested in the stub-DOM harness.

**One-pager (`docs/replay/index.html`)**
- Untouched: it quotes no precision number, so item 4 of the brief was a no-op.

**Tests**
- New `fleet/tests/test_s10h_baselines_page.py` with 38 tests:
  - Data.js against the JSONs, for every label and K.
  - DOM pairing of map and persistence spans for the same label and K.
  - No baselines span inside `.big`.
  - Verdict words from the data, including a mutated "beats" fixture.
  - A guard that fails when any shown K20 verdict becomes "beats" or the count of "worse" is not 1. This ties the prose sentence to the JSON.
  - Window minutes against the raw `params.horizon_s`.
  - BANNED words.
  - A fresh in-process build that holds the two sentences.
  - Exporter bad input.
  - Replay null paths.
- Six legacy page tests were updated mechanically: the new key order, the step-4 text, the figure count and the s8r digit counts.

## Passes

- **Criterion pre-review halted the first launch.** Clause (2) both required the 97% to sit beside a persistence span and forbade pairing it with a persistence number scored differently. I adopted the reviewer's single-correction rewrite (2a/2b split) and relaunched.
- **Pass 1: refuters did not refute, but reviewers found a real defect.**
  - The copy said the numbers were scored "over the following hour". `params.horizon_s` is 1245 s (about 21 min) for four runs and 3600 s only for closed-loop-sticky.
  - My first mandated sentence ("or more often") was loose: on the sticky floor run the map is 0.17 points ahead, within noise.
  - Test (e) compared the committed HTML with a typed constant, so editing the source sentence stayed green.
  - The design audit, slop lens, run from the main loop because builders lack the Agent tool, returned 6 majors:
    - The comparison sat inside `.big` and rendered as 64px numerals.
    - The step-4 counts number had no map number next to it.
    - The figure showed "%" for differences that are percentage points, had no scale labels and used a low-contrast counts bar.
    - Two majors were about the opening sentences; the first was resolved by the F3 rewording plus the guard test.
    - The sixth was the pre-existing "zone" wording; I did not act on it (see Open).
- **Pass 2 fixed all of these (F1–F6):**
  - Window minutes are read from `horizon_s`.
  - The step-3 comparison moved into its own `p.one`.
  - The F3 sentences were reworded, with the guard test above.
  - Step 4 now shows the map number next to the counts number, with the verdict.
  - The figure uses points, has end labels, bold verdicts and a darker counts bar.
  - Test (e) builds the page fresh.
- **Injections:** the builder recorded each pass-1 and pass-2 injection as red, for example PERSIST_OPEN edited without a rebuild → 1 failure. One injection (pass-1 g) stayed green until a new test was added. The builder ran the injection check as red/green only, without reading each failure message.

## Evidence

- Pass-2 builder: `unittest discover -s tests` Ran 930, OK (skipped=1). `unittest discover -s fleet/tests -t .` Ran 921, OK (skipped=1).
- CI `gate`: pass, 21m21s (run 39274466309).
- After the merge, on master a83c9a4, from the main loop: `unittest fleet.tests.test_s10h_baselines_page fleet.tests.test_s8k_overview fleet.tests.test_s8j_page fleet.tests.test_s8r_dose_overview fleet.tests.test_s11a_explorer` → Ran 185, OK.
- Not verified: neither page was rendered in a browser. Layout was checked only through HTML parsing and the stub DOM. The design audit was not re-run on the pass-2 diff.

## Open (operator)

1. **"zone" on the overview.** Step 4 still reads "still above the zone average next window" and "their zone's average". This is pre-existing and was deliberately left, because the S8Q question about "area's" vs "zone's" is still open. "zone" matches the BANNED regex, and the replay page says "area's".
2. **Two windows on one page.** Step 4 now states "next 21 minutes" (map and counts) next to the lessons' "next half hour" (the lesson window). Both are correct, but a reader sees two windows.
3. **Typed constants.** "five runs", "top 20" and "95%" are typed in the copy. The s8r digit test guards them, and the guard test ties "five runs … on one run more often" to the verdicts. If a sixth run or a "beats" verdict appears, that test fails, and the opening sentence must be rewritten by hand.
4. **Scope of "does not beat".** The headline is about truth precision only. On outcome precision, s8e-long-w0.5 is "beats" (K20 and K40). The pages say "against the hidden truth" everywhere the comparison appears.
5. **Unrelated local change.** `results/fleet/hotspot_s10-breakdown.json` shows as modified in the main checkout. This lane did not touch it, and it is left as found.

SCHED_RESULT: OK S10H merged PR #43 -> a83c9a4; run_constants.baselines (5 runs, K20/40, horizon_s) + persistence next to every map precision on overview and replay, new block "Does the map beat last hour's counts?" (map never beats counts on truth precision; 1 worse, 3 within noise, 1 nothing planted); 2 passes, pass 2 0/4 refuted, CI gate green; design-audit pass 1 only

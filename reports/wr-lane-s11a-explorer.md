# wr-lane-s11a-explorer — S11A-EXPLORER (18 Oct 2026)

**Outcome: MERGED.** PR #37 was squash-merged as d655d96, and master was fast-forwarded (24cb0b7..d655d96).
single-lane-build ran at tier standard with a Sonnet builder, in two passes on one branch:

- **Pass 1** (run wf_6b488a6a-fb7, head dde6279) was a clean round. The correctness, test-honesty and invariants
  refuters were all "not refuted", the python-reviewer and typescript-reviewer both passed, and CI gate was green.
  It was not merged: the main loop ran design-audit and found majors.
- **Pass 2** (run wf_7ed31dff-109, head cf79cb5) was a fix pass for those findings. It was also a clean round: the
  same three refuters were "not refuted" and the python-reviewer passed. The typescript-reviewer gave "n-a" because
  it stopped while CI was still running. CI gate was green.

## Criterion pre-review halts (no build was spent on them)
Four launches halted at the criterion pre-review before pass 1 built anything, and one more halted before pass 2.
Every halt was valid:

1. Frozen digit tests (s8r MASTER_DIGITS, the s8k typed-number tests) conflicted with the new section. Resolved with
   one marker pair and the section generated outside TEMPLATE, like the S8R dose figure. Exactly one existing test
   was edited: in s8r, the explorer block is stripped from the digit count, and `closed_loop_p0` is now checked on
   the rest of the page.
2. data-src had to resolve inside data.js, because INPUTS are unchanged. The results paths are kept only as `src`
   provenance strings. The script and data had to sit inside the markers.
3. The "all digits from data" rule had no scope. It now covers visible text, aria/title attributes and script
   strings, and exempts CSS and code. A refresh without `--explorer` must preserve the key.
4. Pass-2 F6 vocabulary rule: its scope was set to the explorer section only.

Lesson (same as S5A): a page lane that sits next to digit-guard tests needs the marker, provenance and digit-scope
rules written into the first criterion.

## What changed
- `fleet/replay_export.py`:
  - New `--explorer` flag, also valid alone with `--refresh-constants-only`. It writes `run_constants.explorer`
    = {axes, floor, sweeps, source_note}.
  - `floor` has 31 entries. Each one is a (regime, arm, steps) triple taken from the `arms` of the five closed-loop
    summaries, intersected with {none, map_a4, map_a8, map_a16, map_a32, oracle, undisturbed}.
  - Missing triples are absent, never zero. These are: mild α16, very sticky α8, and α8/α16 at 1500 steps.
  - `sweeps` covers density (cta) and breakdown (cta and stuck_aware_cta) per point. Each point uses
    `evaluate.summarise` over 30 per-seed rows, so real CIs are shown and the "no CI, Sprint 2 summary" label was not
    needed.
  - **Behaviour change:** `refresh_constants` now inserts a missing key in full-export order instead of appending
    it. This was needed for the s8r round-trip test, and it is disclosed and tested.
- `docs/replay/data.js`: purely additive, an insertion of the explorer key only (byte prefix/suffix comparison in
  the PR). Schema stays `replay/4`.
- `fleet/overview_build.py` + `docs/overview/index.html`: new "Try it" section.
  - It opens with the two mandated sentences, verbatim.
  - Group A controls:
    - Stickiness: a 4-stop range with the p range (en dash) and the words mild / medium / sticky / very sticky.
    - Steering: no map, map with steering strength 4 / 8 / 16 / 32, or perfect knowledge.
    - Shift length: 500 or 1500; 1500 only for very sticky.
    - Unmeasured stops are disabled, show visible text "not measured" plus a title, and the section has one help
      line about greyed-out stops.
  - Group A output:
    - Mean with a 95% CI bar.
    - Solid line for undisturbed and dashed line for none, both text-labelled.
    - Share recovered with its CI, and n.
    - A verdict from `dose_verdict` on the share CI: beats / within noise / worse, against none.
  - Group B controls and output: a carrying-robot count slider and a breakdown-rate slider with a cta / stuck-aware
    toggle, each showing mean, CI and n.
  - Every number is in a data-src span pointing into data.js.
  - Vanilla inline JS and existing tokens only.
  - Accessibility: `aria-valuetext` on all three sliders, and one short polite live summary per group.
- Tests: new `fleet/tests/test_s11a_explorer.py` with 47 tests, including a Node stub-DOM run over every control
  stop and the 12 S8R verdicts. The minimal key-set additions in `test_s8i_exporter.py` and `test_s8j_exporter.py`
  are listed in the PR.

## Design audit (main loop; the builder had no Agent tool)
I ran `design-audit` on the pass-1 diff with the slop and a11y lenses.

- **a11y majors:**
  - The two sliders announced stop indexes.
  - The live regions announced fragments.
  - The disabled reason was in `title` only.
- **slop majors:**
  - Jargon and vocabulary that didn't match (AGVs / alpha / oracle / p).
  - The mandated sentence (kept: the operator's call).
- **Minors:**
  - The reference lines were told apart by red and green only.
  - The bar fill had about 1.9:1 contrast against its track.
  - Ranges used a hyphen instead of an en dash.
  - The latent reference-span bug both reviewers flagged: a missing reference would have shown the selected arm's
    value.

All of these except the mandated sentence were fixed in pass 2 as F1–F6. Each fix has a test that fails on dde6279
and passes on cf79cb5; the python-reviewer confirmed this. The audit was not re-run on pass 2. The page was never
rendered in a browser.

## Evidence (main loop)
- Gate on a `git archive` of cf79cb5 (the results/ tree copied in):
  - `fleet/tests`: Ran 801, OK, 0 skipped. `WR_STICKY_PHASEA` ran because phaseA was copied in.
  - `tests/`: Ran 828, FAILED (errors=2). Both errors are `git status` exit 128 in `test_closed_loop` smoke and
    `test_guidance_tune` hygiene, because the archive is not a git repo. After `git init` plus a commit in the
    archive, both tests ran OK (Ran 2, OK).
- On merged master d655d96:
  - `overview_build.py --out` followed by `cmp` against the committed index.html: identical.
  - `test_s11a_explorer`, `test_s8k_overview` and `test_s8r_dose_overview`: Ran 116, OK.
- Spot check of data.js against S8R: mild map α32 is 41.86 lines/h, share −0.922 (CI −1.965 to −0.497).
- CI only collects `test_fleet_*`, so the new tests ran locally only.

## Open / operator questions
1. "The operator can change that later." is kept verbatim. The slop lens's top finding is that a visitor can't tell
   who "the operator" is or what "that" refers to, and the page elsewhere uses "operators" for fleet staff. Keep it
   or reword it?
2. Range inputs carry structural index digits (min/max/step/value) outside the digit-origin rule. These are the
   typescript-reviewer's nit, accepted as code.
3. If the undisturbed entry is missing at the default state, the static build fails loudly with a KeyError rather
   than showing "not measured". This can't happen with the files on disk.
4. `docs/replay/README.md` has no schema line for `explorer`: the file was out of scope. Docs go direct to master,
   so this is a follow-up.
5. The worktrees `.claude/worktrees/wf_6b488a6a-fb7-2` and `wf_7ed31dff-109-2` are left in place. The first has an
   index that is out of sync with HEAD; do not commit from it.
6. A live simulator (server + public repo) is still undecided; this is stage 1.

SCHED_RESULT: OK S11A merged PR #37 -> d655d96; explorer block in data.js (31 floor triples + density/breakdown sweeps with CIs), 'Try it' on overview; 2 passes, 0/3 refuted each, design-audit fixes F1-F6 in pass 2, CI green

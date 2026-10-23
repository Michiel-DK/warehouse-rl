# wr-dev-s10i-readme — README + SCOPE table (n), fast detector against the decayed map (19 Oct 2026)

**Outcome: DONE, pushed to master** (`9417ea2..802f966`).
- `3568f68` adds the results JSONs by explicit path: `results/fleet/amoc_fast.json` and `results/fleet/amoc_shortmap.json`.
- `29b17e6` changes `scripts/sprint8_tables.py`, `README.md` and `docs/SCOPE.md`.
- `802f966` fixes a README bullet after the final review. The short-memory map and the decayed map differ in cadence and in memory, so the comparison between them is not "cadence alone". The fair cadence comparison is short-memory map against CUSUM, both at 60 s.

## Inputs checked
- `laptop-scheduler/log/wr-s10i-fast-run.exit` is 0. The log's AMOC lines match the JSONs.
- All three JSONs (`amoc_blind`, `amoc_shortmap`, `amoc_fast`) share the same measured run (`fleet/data/s10c-blind`, 50 windows), the same reference (`fleet/data/s10-none`), and the same store hashes before and after. The script asserts all of this.

## What changed
- **`scripts/sprint8_tables.py`**
  - New section (n) `fast_vs_map`, which prints the AMOC columns of (k) for each detector and each shared K (5, 10, 20, 40).
  - `amoc_table`'s row and header were moved into `_amoc_row` / `_amoc_head` so (k) and (n) use identical columns.
  - Assertions: same run, reference, windows and hashes; CUSUM rows identical at every K; no map row dominates the CUSUM.
  - Dominance is computed over every row on disk, including (k)'s cost rows.
  - Full run: rc 0, 0 MISSING. The (a)–(m) output is byte-identical to the output before the change (diff).
  - `fleet.tests.test_s11a_explorer` imports the script: 47 tests OK.
- **README**
  - New subsection "Sprint 10, S10I: fast detector against the decayed map".
  - It contains the (n) output, reading bullets and caveats.
- **SCOPE**
  - Reports list now covers (f) to (n).
  - Ticked: S10I (PR #45, 9417ea2), and the run `wr-s10i-fast-run` (README (n)).
  - Open items added: the in-sample (k, h) pairs need a held-out run; the map with the active counting rule was not measured.

## Verdict, as written in the README
Neither detector catches more windows while open at the same false-alarm rate.
- **CUSUM** (defaults k 1, h 3): detects 2 of 50 at 0.000 false alarms per zone-hour on the reference.
- **Maps:** detect 3 to 6 of 50 at 59.2 to 451.9 across K.
- No map row on disk reaches 0; the lowest is cost >= 0.8 at 37.7.

The CUSUM matches or beats two of the decayed map's cost rows: cost >= 0.6 (2/50 at 50.3) and cost >= 0.8 (1/50 at 37.7). The README says this, with three confounds:
- it rests on 2 windows;
- the CUSUM publishes every 60 s against 300 s;
- the lane report found that the detection comes from the active counting rule.

The short-memory map detects the same 6/50 as the decayed map at K 20, at 451.9 false alarms against 177.8. Publish rate and memory both differ between the two, so this run cannot separate the two effects.

## Deviations
- **I added a third arm, `amoc_shortmap.json`, as a cadence control and committed it.** The brief named two JSONs. The same queue item wrote the third one, and without it the 60 s against 300 s publish-rate difference cannot be separated from the detector.
- **The CUSUM parameters in the (n) footnote are read from the gitignored `fleet/data/s10c-blind/fastmap.json` when it exists.** That file is not committed. `amoc_fast.json` does not record k and h.
- **The lane report's in-sample (k, h) table (k0 h3 17/50) is not quoted in the README.** No results JSON holds it.
- **The README cites the c-end result ("with the end rule, the same CUSUM flags nothing") from the lane report, not from a results JSON.**

SCHED_RESULT: OK S10I readme pushed (3568f68 JSONs, 29b17e6 README/SCOPE/tables (n), 802f966 README fix); CUSUM 2/50 at 0.000 FA/h vs maps 3-6/50 at 59.2-451.9, no shared FA rate -> neither wins at equal false alarms

# Platform: absolute numbers depend on the machine, paired comparisons do not

Operator decision B3 (14 Oct 2026). Short version: the same seed gives the same run on one machine every time, but not
the same run on a Mac and on Linux. Compare policies on one platform; do not compare absolute numbers across platforms.

## The finding

The simulator plans AGV routes with `pyastar2d`, an A* written in C++. When two routes cost the same, which one A*
returns depends on how `std::priority_queue` orders ties, and that depends on the C++ standard library it was compiled
against: libc++ on macOS (Apple clang), libstdc++ on Linux (gcc). So the compiler toolchain, Xcode included, is part of
the platform. Nothing in `vendor/` or in `src/` differs; the same source gives different tie-breaks.

Different tie-break, different route, different traffic, and from there a different run. The first 500 steps of seed 0
CTA on the small map agree (24 deliveries on both). They diverge later:

| platform | deliveries at 500 steps | deliveries at 2000 steps |
|---|---|---|
| darwin-arm64 | 24 | 86 |
| linux-x86_64 | 24 | 93 |
| linux-arm64 | 24 | 93 |

Evidence: GitHub CI (ubuntu, x86_64) gate runs 38441952462 and 38538691628, and Docker `python:3.10` probes on
linux/arm64 and linux/amd64. The two Linux platforms agree with each other; macOS differs.

## What is portable

- Portable: paired comparisons inside one platform (policy A vs policy B on the same seeds, same machine).
- Not portable: absolute deliveries and pick-rates, and anything pinned to a seed's trajectory (which seed has an
  abandon, which step a robot freezes).
- Committed `results/*.json` and the README tables were measured on darwin-arm64.

## How results files record the platform

- `scripts/evaluate.py` writes `platform` (for example `darwin-arm64`) in the result-doc header, not in rows.
- A file without the field predates it and was measured on darwin-arm64.
- Resuming onto an existing doc whose platform differs from the current machine raises `ValueError`, so rows from
  another machine are never relabelled.
- `sweep.py`, `recovery_sweep.py` and `recovery_heldout.py` do not stamp the platform yet.

## How the tests handle it

`tests/platform_expected.json` holds the per-platform values for three things: the CTA delivery counts
(`test_multi_steps_known_numbers`), the seed for the abandon re-dispatch test (`rule_abandon_pin`), and the seed for the
fleet emitter stream test (`fleet_stream`). Each entry carries a provenance note. `tests/_platform.py` reads it:
`expected(test, key)` raises a visible skip (`no <tag> reference yet`) when the current platform has no entry.

The two tests that compare against the committed `results/recovery/timeout.json` run all their portable assertions
everywhere and skip only the value comparison when the file's platform differs from the machine.

## Adding a platform

1. Measure the CTA deliveries at 500 and 2000 steps (seed 0, small map) and add them under the new tag.
2. Search a seed for `rule_abandon_pin`: run the whole `TestAbandonRedispatch` class with `PIN["seed"]` set to each
   candidate and keep one that passes.
3. Do the same for `fleet_stream` with the whole `TestStream` class.
4. Add the three entries, each with a provenance note, to `tests/platform_expected.json`. `tests/test_platform.py`
   checks that every key has all listed platforms; add the new tag to its `TAGS`.

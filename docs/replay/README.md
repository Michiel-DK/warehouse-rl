# Fleet replay (docs/replay)

A one-page, no-server view of one simulated warehouse shift: the floor with its robots, what happened to the robot log on
its way in (arrived, usable, kept, dropped), what the analyser worked out from the log alone, the plain-language lines it would
hand to the operators, and what the routing gain is worth (a fifth panel, from a separate 30-seed simulator test). Everything on the page comes from `data.js` (replay) or from the live `/state` document (live
mode). Nothing is typed into the HTML.

**The data is synthetic.** It comes from a simulator, with floor problems we planted and a small amount of deliberate log
noise (malformed lines, exact duplicates, one jump in message numbers) so the log panel has something to show. Real
logs will differ.

## Open it

- Replay: open `docs/replay/index.html` in a browser (it also works from `file://`), or serve the folder:
  `python3 -m http.server --directory docs/replay 8000` and open `http://localhost:8000/`.
- GitHub Pages: publish the `docs` folder; every path on the page is relative (`data.js`, `replay.js`, `replay.css`).
- Live (a demo, not a measurement): `.venv/bin/python fleet/live.py`, then open the URL it prints. Demo log noise is ON by
  default there; `--no-demo-noise` turns it off.

## How `data.js` was made

`fleet/data/` is not in git, so this is the whole chain (repo root, one shell, about 20 s on a laptop). The run is one
zone of the medium map, 500 steps, seed 0, 80 planted floor cells, with demo noise. The lessons are drawn on this very run
(`lessons.py`, after the map and before the grading); nothing is carried over from another run:

```sh
R=fleet/data/s8i-demo-noise && rm -rf $R && mkdir -p $R
.venv/bin/python fleet/emit.py --zones 1 --steps 500 --seed-base 0 --env tarware-medium-8agvs-4pickers-globalobs-v1 --disturb '{"floor": {"cells": 80, "p": [0.3, 0.7]}}' --demo --demo-noise --control-file $R/control.jsonl --dir $R --workers 1
.venv/bin/python fleet/ingest.py --glob "$R/*.jsonl.gz" --store jsonl:$R/store --once
.venv/bin/python fleet/costmap.py --glob "$R/*.jsonl.gz" --store jsonl:$R/store --publish-every 1250 --horizon-s 1245 --out $R/costmap.json
.venv/bin/python fleet/lessons.py --run s8i-demo-noise --store jsonl:$R/store --once --window-h 0.5
.venv/bin/python fleet/grade.py --run s8i-demo-noise --store jsonl:$R/store --once --truth $R/truth.json
.venv/bin/python fleet/hotspot_score.py --run-dir $R --store jsonl:$R/store --tag s8i-demo-noise
.venv/bin/python fleet/replay_export.py --run-dir $R --store jsonl:$R/store --zone 0 --out docs/replay/data.js --closed-loop results/closed_loop --benchmark results/fleet/benchmark.json --hotspot results/fleet/hotspot_s8i-demo-noise.json --closed-loop-summary results/closed_loop_sticky/summary.json --lessons-long results/fleet/hotspot_s8e-long-w0.5.json --sticky-none results/closed_loop_sticky/none/*.json --sticky-map-a32 results/closed_loop_sticky/map_a32/*.json --sticky-oracle-a32 results/closed_loop_sticky/oracle_a32/*.json --sticky-undisturbed results/closed_loop_sticky/undisturbed/*.json
```

Notes:

- `--window-h 0.5` was picked from the independent longer run (`results/fleet/hotspot_s8e-long-w0.5.json`), not from this
  shift. On this 42-minute shift it gives one window and one lesson (a hot cell); `grade.py --truth` then writes its
  `lesson_truth` verdict. The lesson's next-window grade stays open, because the shift has no next window. The exporter
  raises (`assert_single_run`) when any exported element belongs to another run or zone.
- `--lessons-long` and the four `--sticky-*` row files (one file per arm directory; the shell expands the `*`) are context for
  the footnote under the lessons and for panel 5. They come from other runs than the replay, and the page says so.
  Re-running `hotspot_score.py` after `lessons.py` and `grade.py` adds `grading_counts.lesson_truth` to
  `results/fleet/hotspot_s8i-demo-noise.json`; nothing else in that file changes.
- The exporter reads the numbers it shows (`run_constants`) from `results/fleet/benchmark.json`,
  `results/fleet/hotspot_s8i-demo-noise.json` (committed, a demo artifact), `results/closed_loop_sticky/summary.json`, the
  `--lessons-long` file and the four sticky row files, and from the emit ledger (sent, noise) and the replayed extractor. It records
  the source of each next to its value. The page's footer lists them.
- The map is built by `fleet/costmap.py` from the raw zone files (`hotspot.read_messages` on the glob), and the lessons from the
  `stalls` table that `costmap.py` writes. Neither reads only the kept tables, and the page does not say they do. The funnel
  claim is narrower: from the kept transitions you can rebuild every robot's state at every step and its position at every
  change (`fleet/tests/test_s8j_rebuild.py`).
- The kept share is computed by the exporter from the store (formula in the docstring of `fleet/replay_export.py` and in
  `run_constants.kept.formula`).
- The with-map layer is re-simulated from `results/closed_loop`, as before.
- Env numbers depend on the platform (path-finding tie-breaks): a Linux run will not reproduce this file byte for byte.

## Test

`.venv/bin/python -m unittest discover -s fleet/tests` (page text, banned-word and Pages-readiness checks are in
`fleet/tests/test_s8i_page.py` and `fleet/tests/test_s8j_page.py`; the page is also run under a stub DOM in Node by
`test_s8j_page.py`, which needs `node` on the PATH) and `node --check docs/replay/replay.js`.

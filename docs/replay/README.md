# Fleet replay (docs/replay)

A one-page, no-server view of one simulated warehouse shift: the floor with its robots, what happened to the robot log on
its way in (arrived, usable, kept), what the analyser worked out from the log alone, and the plain-language lines it would
hand to the operators. Everything on the page comes from `data.js` (replay) or from the live `/state` document (live
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

`fleet/data/` is not in git, so this is the whole chain (repo root, one shell, about 15 s on a laptop). The run is one
zone of the medium map, 500 steps, seed 0, 80 planted floor cells, with demo noise:

```sh
R=fleet/data/s8i-demo-noise && rm -rf $R && mkdir -p $R
.venv/bin/python fleet/emit.py --zones 1 --steps 500 --seed-base 0 --env tarware-medium-8agvs-4pickers-globalobs-v1 --disturb '{"floor": {"cells": 80, "p": [0.3, 0.7]}}' --demo --demo-noise --control-file $R/control.jsonl --dir $R --workers 1
.venv/bin/python fleet/ingest.py --glob "$R/*.jsonl.gz" --store jsonl:$R/store --once
.venv/bin/python fleet/costmap.py --glob "$R/*.jsonl.gz" --store jsonl:$R/store --publish-every 1250 --horizon-s 1245 --out $R/costmap.json
.venv/bin/python fleet/grade.py --run s8i-demo-noise --store jsonl:$R/store --once --truth $R/truth.json
.venv/bin/python fleet/hotspot_score.py --run-dir $R --store jsonl:$R/store --tag s8i-demo-noise
.venv/bin/python fleet/replay_export.py --run-dir $R --store jsonl:$R/store --zone 0 --out docs/replay/data.js --closed-loop results/closed_loop --benchmark results/fleet/benchmark.json --hotspot results/fleet/hotspot_s8i-demo-noise.json --closed-loop-summary results/closed_loop_sticky/summary.json --carry-lessons docs/replay/data.js
```

Notes:

- `--carry-lessons docs/replay/data.js` reads the lessons from the existing `data.js` before it is overwritten. This run's
  store has no lesson decisions, so the 15 lessons (written on run `s8b-score`, same seed and floor, without log noise) are
  carried over unchanged, and `meta.source.carry_lessons_run` keeps saying `s8b-score` when the chain is run again.
- The exporter reads the numbers it shows (`run_constants`) from `results/fleet/benchmark.json`,
  `results/fleet/hotspot_s8i-demo-noise.json` (committed, a demo artifact) and
  `results/closed_loop_sticky/summary.json`, and records the path of each next to its value. The page's footer lists them.
- The kept share is computed by the exporter from the store (formula in the docstring of `fleet/replay_export.py` and in
  `run_constants.kept.formula`).
- The with-map layer is re-simulated from `results/closed_loop`, as before.
- Env numbers depend on the platform (path-finding tie-breaks): a Linux run will not reproduce this file byte for byte.

## Test

`.venv/bin/python -m unittest discover -s fleet/tests` (page text, banned-word and Pages-readiness checks are in
`fleet/tests/test_s8i_page.py`) and `node --check docs/replay/replay.js`.

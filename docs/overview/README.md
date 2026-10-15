# docs/overview: the landing page

`index.html` is the landing page above the replay (`../replay/index.html`, the demo). It says what the fleet stuck
analyser is, what has been tested and what has not (a banner and one status chip per block), and links to the replay
("see it move"). The replay links back with "about this project".

All data is **synthetic**: a TA-RWARE simulator run, one laptop, macOS numbers. Nothing here comes from a client log.

## It is built, not hand-edited

`fleet/overview_build.py` fills the template (a module constant `TEMPLATE`) and writes `index.html`. Every number on the
page is a `<b class="num" data-src="<file>:<expression>">`; the builder resolves each data-src from the inputs below and
formats it. Nothing is typed into the template.

Rebuild (from the repo root):

```sh
.venv/bin/python fleet/overview_build.py
```

Flags: `--data` (default `docs/replay/data.js`), `--results-root` (default the repo root), `--out` (default
`docs/overview/index.html`). The build is deterministic: the same inputs give the same bytes. It refuses to write (non-zero
exit, no file) if an input is missing or any `{name}` placeholder is left in the page.

## Inputs (and only these)

- `docs/replay/data.js` (`window.REPLAY`): the shift, floor, stuck periods, map, lesson, and `run_constants`
  (including `lessons_long`, the counts from `results/fleet/hotspot_s8e-long-w0.5.json`, and `worth`, the sticky-floor
  routing test).
- `results/fleet/benchmark.json`
- `results/fleet/hotspot_s8b-medium-80-p03-07.json`
- `results/closed_loop_sticky/summary.json`

The routing beat uses the sticky-floor `worth` block, not `run_constants.closed_loop` and not `results/closed_loop/`.

## Checks

`.venv/bin/python -m unittest fleet.tests.test_s8k_overview` (also part of `discover -s fleet/tests`).

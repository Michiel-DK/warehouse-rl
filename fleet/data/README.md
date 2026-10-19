# fleet/data: single-kind disturbance configs for the medium map (S10A calibration, 18 Oct 2026)

fleet/data/ is gitignored except this file (`git add -f fleet/data/README.md`). Emitter runs write their output here.

## Stall share

Map `tarware-medium-8agvs-4pickers-globalobs-v1`, 2 zones x 500 steps (seed base 0, policy stuck_aware_cta, timeout
recovery), `emit.py` then `ingest.py --once`. Stall share = the share of the 1000 zone-steps (steps 0..499 of each of the
2 zones, pooled) in which at least one robot of that zone is inside a `stuck_episodes` row (step of start <= step < step
of end; end null = stream end; last row per episode id). Target band [0.05, 0.40]. The union reading (a step counts if
either zone has a robot stuck, over 500 steps) is printed as well; it is never lower.

Baseline `{}` (no disturbance): share 0.982 (union 0.994, 138 episodes). Background traffic on this map keeps a
robot in a stuck episode almost all the time, so no disturbance config can sit inside the band: every kind is OUT OF BAND.
The configs below move it by -0.005 to +0.014 from the baseline (a disturbance can also lower it slightly: fewer
episodes, e.g. robots rerouting round a blocked cell instead of queueing).

| kind | config (`--disturb` JSON or preset) | stall share | union | episodes | band |
|---|---|---|---|---|---|
| baseline | `{}` | 0.982 | 0.994 | 138 | out (background) |
| blocked | `{"blocked_cell":{"rate_per_hour":2.0,"duration":[60,240]}}` (placeholder) | 0.981 | 0.994 | 137 | out |
| blocked | `{"blocked_cell":{"rate_per_hour":0.5,"duration":[30,120]}}` | 0.982 | 0.994 | 138 | out |
| blocked | `{"blocked_cell":{"rate_per_hour":8.0,"duration":[60,240]}}` | 0.977 | 0.994 | 122 | out, closest |
| outage | `{"outage":{"rate_per_hour":1.0,"duration":[120,360]}}` (placeholder) | 0.982 | 0.994 | 138 | out |
| outage | `{"outage":{"rate_per_hour":0.25,"duration":[60,180]}}` | 0.980 | 0.994 | 138 | out, closest |
| outage | `{"outage":{"rate_per_hour":4.0,"duration":[120,360]}}` | 0.982 | 0.994 | 132 | out |
| breakdown | `breakdown-heavy` (placeholder) | 0.996 | 0.998 | 114 | out |
| breakdown | `breakdown-light` | 0.989 | 0.994 | 120 | out, closest |
| burst | `{"burst":{"start":100,"end":300,"extra":20}}` (placeholder) | 0.981 | 0.994 | 121 | out, closest |
| burst | `{"burst":{"start":150,"end":250,"extra":5}}` | 0.982 | 0.994 | 136 | out |

Closest-to-band is meaningless here (the share does not separate a disturbed run from an undisturbed one), so the
queue item `wr-s10-disturbance-measure` uses configs chosen on a second criterion instead: enough truth to grade on
10 zones x 500 steps (seeds 0-9). Truth windows counted from the schedule (pure function of seed and config):

| kind | config | truth windows, 10 zones | zones with none | stall share (2 zones) |
|---|---|---|---|---|
| blocked | `{"blocked_cell":{"rate_per_hour":2.0,"duration":[60,240]}}` | 16 | 2 | 0.981 |
| blocked | **`{"blocked_cell":{"rate_per_hour":8.0,"duration":[60,240]}}`** | 50 | 0 | 0.977 |
| outage | `{"outage":{"rate_per_hour":0.25,"duration":[60,180]}}` | 1 | 9 | 0.980 |
| outage | `{"outage":{"rate_per_hour":1.0,"duration":[120,360]}}` | 7 | 6 | 0.982 |
| outage | **`{"outage":{"rate_per_hour":4.0,"duration":[120,360]}}`** | 20 | 1 | 0.982 |
| breakdown | `breakdown-light` | 126 frozen | 0 | 0.989 |
| breakdown | **`breakdown-heavy`** | 426 frozen | 0 | 0.996 |
| burst | **`{"burst":{"start":100,"end":300,"extra":20}}`** | (no cells, by design) | - | 0.981 |

Chosen (bold): blocked 8/h [60,240], outage 4/h [120,360], breakdown-heavy, burst 100-300 +20. Caveat for the
breakdown run: 426 frozen windows over 120 robots means nearly every robot is a frozen-truth positive, so hot_robot
lesson precision against truth is close to trivially high there; read it next to the positives count. The stall-share
band [0.05, 0.40] is unreachable with this definition on this map; changing the definition is the operator's call.
The definition was not changed to fit the band.

## Other readings of "stall share" (main loop check, 18 Oct, after the merge)

The band test above uses one reading (stuck_episodes, open episode = to stream end). Same 2 zones x 500 steps, three
configs, five readings (zone-steps with >= 1 robot inside the interval, except the last column = mean share of
robot-steps inside a `stalls` row):

| config | episodes (as above) | closed episodes only | `stalls` rows | `stalls` with in_episode | robot-steps stalled |
|---|---|---|---|---|---|
| `{}` | 0.982 | 0.972 | 0.334 | 0.099 | 0.038 |
| blocked 8/h [60,240] | 0.977 | 0.954 | 0.323 | 0.109 | 0.034 |
| breakdown-heavy | 0.996 | 0.961 | 0.236 | 0.190 | 0.025 |

Under the `stalls` reading the baseline itself is inside the band and the disturbances LOWER it; only breakdown separates
from the baseline, and only on the in_episode reading. No reading turns the config into a knob for the band, so the
configs stay chosen by truth coverage (table above). Two zones are a small sample; these are smoke-level numbers.

## truth.json: `blocked_windows[].known` (S10C)

Each `blocked_windows` entry is `{cell, start_step, end_step, known}`. `known` is the bool of the run's
`blocked_cell.known` config key (default true): true = the planner routes around the cell, false = a blind blockage
(a spill nobody told the planner about; robots drive into it and wait). It is informational. A blocked window is truth
either way, so `fleet/truth.py` does not read it and answers identically with the key absent (older truth files), true
or false. Config `known` values never change a schedule draw; they only change whether the cell is an obstacle.

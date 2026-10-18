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
The share cannot fall below the baseline, and the configs below move it by -0.005 to +0.014.

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

Chosen for the four single-kind configs (all out of band, closest to the band listed as "closest"): blocked
`{"blocked_cell":{"rate_per_hour":8.0,"duration":[60,240]}}` (0.977), outage
`{"outage":{"rate_per_hour":0.25,"duration":[60,180]}}` (0.980), breakdown `breakdown-light` (0.989), burst
`{"burst":{"start":100,"end":300,"extra":20}}` (0.981). Closeness is only the distance to 0.40; none of them differs from
the baseline 0.982 by more than 0.014, so the share does not separate a disturbed run from an undisturbed one.
The definition was not changed to fit the band.

# Stuck episode report: bench-live-20261014T133703

138 countable episodes (excluded: left_censored 0, interrupted 0, open 0).

## Hotspots (top 20 cells by episode count; ties by zone, cell)

- zone 0 cell 10-3: 2
- zone 0 cell 18-12: 2
- zone 1 cell 12-4: 2
- zone 1 cell 12-7: 2
- zone 1 cell 14-14: 2
- zone 2 cell 3-7: 2
- zone 2 cell 3-17: 2
- zone 2 cell 16-7: 2
- zone 2 cell 17-8: 2
- zone 3 cell 4-6: 2
- zone 3 cell 6-15: 2
- zone 3 cell 18-5: 2
- zone 4 cell 10-12: 2
- zone 4 cell 12-5: 2
- zone 4 cell 14-17: 2
- zone 5 cell 10-3: 2
- zone 5 cell 11-13: 2
- zone 5 cell 18-12: 2
- zone 6 cell 7-15: 2
- zone 6 cell 7-19: 2

## Episodes per event hour (hour of the episode start, UTC)

- 2026-10-14T13:00:00Z: 70
- 2026-10-14T14:00:00Z: 68

## Duration (s, start to end; nearest-rank percentiles)

- p50: 175
- p95: 545

## Cause mix

- blocked_by_faulted: 7
- blocked_by_stuck: 2
- faulted_self: 45
- traffic: 10
- unknown: 74

## Resolution mix

- fault_cleared: 20
- moved: 16
- order_dropped: 44
- unresolved: 58

## Avoidable

- avoidable (detector definition, near-tautological at 5 s steps: every closed blocked_by_faulted episode)
- episodes: 4
- minutes: 7.33

## Repeat robots (>= 3 episodes)

- Z1-10: 4
- Z3-02: 3
- Z3-06: 3
- Z3-07: 3
- Z4-08: 3
- Z6-07: 3

## Time from stuck to resolution (s, end minus t_entry; nearest-rank percentiles)

- p50: 145
- p95: 515

## Decision grades per kind and verdict (open = not graded yet)

- avoidable_reset / open: 4
- stuck_cause / open: 138

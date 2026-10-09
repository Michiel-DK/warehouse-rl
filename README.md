# warehouse-rl

Does a learned task-allocation policy beat a FIFO dispatcher on pick-rate in a simulated robot warehouse?

Environment: [TA-RWARE](https://github.com/uoe-agents/task-assignment-robotic-warehouse) (Edinburgh, MIT).
Metric: pick-rate in order-lines per hour, same map, same seeds, against the FIFO heuristic that ships with the env.

Plan and sprint log: [docs/SCOPE.md](docs/SCOPE.md).

## Setup (macOS)

```
./scripts/setup.sh
.venv/bin/python scripts/baseline_fifo.py --env tarware-small-4agvs-2pickers-globalobs-v1 --episodes 10
```

Hardware this was built on: M1 Pro, 10 cores, 16 GB, CPU only. The env steps at roughly 1,700 steps/s on the small map (500-step episode in 0.3 s), so all training here is local.

## Baselines (FIFO heuristic, 10 seeds, 2026-10-09)

| Map | Agents | Pick-rate mean (lines/h) | SD |
| --- | --- | --- | --- |
| small, global obs | 4 AGV + 2 pickers | 30.5 | 2.8 |
| small, partial obs | 4 AGV + 2 pickers | 30.5 | 2.8 |
| medium, global obs | 8 AGV + 4 pickers | 54.4 | 6.6 |

Raw per-episode numbers are in `results/fifo_*.json`. The heuristic does not read observations, so partial and global give identical results.

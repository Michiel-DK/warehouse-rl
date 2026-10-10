# warehouse-rl

Can a learned policy make a simulated robot warehouse recover from stuck robots better than a timeout or a hand-written rule? And, as the original question, does a learned task-allocation policy beat the Closest-Task-Assignment (CTA) heuristic on pick-rate?

Environment: [TA-RWARE](https://github.com/uoe-agents/task-assignment-robotic-warehouse) (Edinburgh, MIT).
Metric: pick-rate in order-lines per hour, same map, same seeds, against the CTA heuristic that ships with the env (nearest free AGV per request).

Plan, decision log, review findings and sprint plan: [docs/SCOPE.md](docs/SCOPE.md). Current direction (2026-10-10): Sprint 1 evaluation harness, Sprint 2 disturbance layer and density/failure sweeps with CTA only, Sprint 3 learned stuck-recovery vs timeout vs hand-written rule. Dispatcher learning is optional Sprint 4. Short summary page: https://claude.ai/artifact/33YWuNCVFjQxH3LdYXRbS3

Replay of one CTA episode: open `results/replay_small.html` in a browser (made by `scripts/record_episode.py` + `scripts/replay_template.html`).

## Setup (macOS)

```
./scripts/setup.sh
.venv/bin/python scripts/evaluate.py --policy cta --env tarware-medium-8agvs-4pickers-globalobs-v1 --seeds 0-9 --steps 500
```

`scripts/evaluate.py` is resumable and multiprocess (`--workers`, else `SCHED_WORKERS`, else cpu_count - 2) and writes `results/<policy>_<env>_<steps>.json`. `scripts/throughput.py` measures steps/s per worker and in total.

Hardware this was built on: M1 Pro, 10 cores, 16 GB, CPU only. The env steps at roughly 1,700 steps/s on the small map (500-step episode in 0.3 s), so all training here is local.

## Baselines (CTA heuristic, 10 seeds, 2026-10-09)

| Map | Agents | Pick-rate mean (lines/h) | SD | 95% CI |
| --- | --- | --- | --- | --- |
| medium, global obs | 8 AGV + 4 pickers | 54.4 | 6.9 | 49.5 to 59.4 |
| small, global obs | 4 AGV + 2 pickers | 30.5 | 2.9 | 28.4 to 32.6 |
| small, partial obs | 4 AGV + 2 pickers | 30.5 | 2.9 | 28.4 to 32.6 |

SD is the sample SD (ddof=1) and the CI is a Student-t 95% interval over the 10 seeds, both recomputed with `evaluate.summarise` from the rows in `results/fifo_tarware-medium-8agvs-4pickers-globalobs-v1.json`, `results/fifo_tarware-small-4agvs-2pickers-globalobs-v1.json` and `results/fifo_tarware-small-4agvs-2pickers-partialobs-v1.json`. The SD convention changed from the population SD used in the first version of this table (2.8 and 6.6).

Raw per-episode numbers are in `results/fifo_*.json`; these files predate the rename (the CTA heuristic was called FIFO in this repo before 2026-10-10). The heuristic does not read observations, so partial and global give identical results.

The medium map is the paper's "GTP Small" (Krnjaic et al. 2023), where the paper reports 52.7 lines/h for the same heuristic. At 500 steps one delivery is 1.44 lines/h and the 95% CI over 10 seeds is about +/- 2 lines/h, so these numbers cannot resolve a 5% effect; Sprint 1 fixes the evaluation length and seed count.

Evaluation resolution: pending (scheduler item wr-dev-s1-readme)

# Demo v0: fleet stuck analyser, end to end on one laptop

This is the walkthrough you can show today. The polished demo pack is Sprint 9 (S9D); this is its draft.

**Timing: about 4 min of command wall time** (12 s stack up, 4 s emit, 5 s file ingest + status, 207 s live Kafka
leg, 4 s scoring, 4 s teardown), run on 14 Oct 2026 from 16:15:45 to about 16:21 (last stamp 16:20:03, then 4 s of scoring and 4 s of teardown). The 207 s live leg sets the length.
Allow 10 minutes once you add talking and a look at Grafana.

Every command below was run as written in that session, from the repo root, on master `a6a305a`. The run names it
used were `demo-20261014T1616` (file) and `demo-live-20261014T1616` (Kafka); yours will carry your own timestamp.
Every "you see" block is pasted from that run and trimmed. One step was not run: the full volume wipe in step 6. It
is marked `UNVERIFIED` and the reason is given there.

What the viewer is looking at: a simulator (TA-RWARE, small map, 6 robots per zone) writes a robot-fleet state log.
The analyser reads that log the way it would read a real fleet's files or Kafka topic. It finds robots that are stuck,
names a likely cause, and keeps two ledgers: one for volume (what it read and kept) and one for decisions (every call,
graded later).

## 1. Preconditions and the stack

```sh
docker info --format '{{.ServerVersion}}'
.venv/bin/python --version
df -h . | tail -1
fleet/compose.sh up
docker exec fleet-redpanda-1 rpk cluster info | head -6
curl -s localhost:18123/ping
curl -s localhost:13000/api/health
ls /tmp/ck/confluent_kafka | head -3
```

You see (12 s):

```
24.0.5
Python 3.10.6
/dev/disk3s5   926Gi   827Gi    59Gi    94%    5.5M  620M    1%   /System/Volumes/Data
 Container fleet-clickhouse-1  Healthy
 Container fleet-redpanda-1  Healthy
 Container fleet-grafana-1  Healthy
CLUSTER
=======
redpanda.ba60397c-dcce-4b52-b38f-2b44e9cd0801
Ok.
{ "database": "ok", "version": "11.2.0", ... }
__init__.py
__pycache__
_model
```

`fleet/compose.sh up` wraps `docker compose -f fleet/docker-compose.yml up -d --wait`. It starts Redpanda (Kafka API on
`localhost:19092`), ClickHouse (HTTP on `localhost:18123`) and Grafana (`http://localhost:13000`, admin/admin). Each
container has a memory cap: redpanda 1.5g, clickhouse 3g, grafana 512m. The data lives in the Docker named volumes
`fleet_*`, and those count toward the 8 GB data cap. Disk was 94% used with 59 GiB free; the demo itself writes
about 0.2 MB of files.

The Kafka client is not in `.venv`. The lanes installed it with `pip install --target /tmp/ck confluent-kafka==2.5.3`,
and this demo uses that copy through `PYTHONPATH=/tmp/ck`. The install was not run in this job because the copy was
already there (the `ls` above). macOS clears `/tmp` on reboot. If the `ls` fails, run the install before step 3b, or
the Kafka leg stops with `ModuleNotFoundError: No module named 'confluent_kafka'`.

## 2. Emit a fleet log (small map, file sink)

```sh
.venv/bin/python fleet/emit.py --env tarware-small-4agvs-2pickers-globalobs-v1 --zones 2 --steps 720 --seed-base 0 \
  --disturb breakdown-heavy --t0 now --speed 0 --sink file --dir fleet/data/demo-20261014T1616
```

You see (4 s):

```
status complete: 8640 messages (expected 8640) in 3.18 s wall, 2716 messages/s, 1.40 MB/s uncompressed, 0.02 MB/s compressed, ratio 57.7x
zone 0 seed 0: deliveries 12 pick_rate 12.00
zone 1 seed 1: deliveries 15 pick_rate 15.00
ledger: fleet/data/demo-20261014T1616/emit_ledger.json
```

That is 2 zones x 6 robots x 720 steps of 5 s, so one simulated hour per zone with one message per robot per step.
`emit_ledger.json` is the denominator: it records how much was emitted, and coverage is measured against it.

## 3. Ingest it and read the volume ledger

### 3a. File path (into ClickHouse)

```sh
.venv/bin/python fleet/ingest.py --glob 'fleet/data/demo-20261014T1616/*.jsonl.gz' --run demo-20261014T1616 \
  --store clickhouse://localhost:18123/fleet --once
.venv/bin/python fleet/ledger.py status --run demo-20261014T1616 --store clickhouse://localhost:18123/fleet
```

You see (5 s):

```
ingest demo-20261014T1616: accepted 8640 (parsed 8640, rejected 0, duplicates 0), coverage 1.0, 2904 messages/s over 2.98 s wall, exit 0
run demo-20261014T1616
total [file]: bytes compressed 77158, uncompressed 4450873, messages parsed 8640, accepted 8640, msgs/s 2911.5
total: rejects 0, duplicates 0, gaps 0 (missing 0), kept 1697940 B, dropped 2752933 B, kept ratio 0.3815
backlog_bytes (latest row): 0
coverage: 1.0 (accepted 8640 / expected 8640)
files: complete 2
episodes per cause: blocked_by_faulted 4, blocked_by_stuck 1, faulted_self 33, traffic 3, unknown 36
episodes per resolution: fault_cleared 20, moved 11, order_dropped 42, unresolved 4
episodes excluded: left_censored 0, interrupted 0, open 0
decisions: avoidable_reset/open 3, stuck_cause/open 77
```

The status output also repeats the `total` lines for the last 1, 5 and 60 minutes; those are trimmed above. What to
point at: bytes read and kept, messages, gaps, backlog and coverage against the emit ledger. For the file path,
`status` reports backlog in bytes. It has no lag line. Lag in seconds is a benchmark figure; see README "Sprint 5".

### 3b. Kafka path, live (with the alert tail from step 4 running)

Three processes run in three terminals, in this order. The emitter is paced at 20x real time
(`--rate realtime --speed 20`), so one simulated hour takes about 3 minutes.

```sh
# terminal 1: emitter -> Redpanda
PYTHONPATH=/tmp/ck .venv/bin/python fleet/emit.py --env tarware-small-4agvs-2pickers-globalobs-v1 --zones 2 --steps 720 \
  --seed-base 0 --disturb breakdown-heavy --t0 now --rate realtime --speed 20 --sink kafka --bootstrap localhost:19092 \
  --topic fleet.demo-live-20261014T1616 --ledger-dir fleet/data/demo-live-20261014T1616
# terminal 2 (3 s later): ingester <- Redpanda
PYTHONPATH=/tmp/ck .venv/bin/python fleet/ingest.py --source kafka --bootstrap localhost:19092 \
  --topic fleet.demo-live-20261014T1616 --group demo-live-20261014T1616 --run demo-live-20261014T1616 \
  --store clickhouse://localhost:18123/fleet --emit-ledger fleet/data/demo-live-20261014T1616/emit_ledger.json --until-idle 20
# terminal 3: live alerts (step 4)
PYTHONPATH=/tmp/ck .venv/bin/python fleet/alert.py --run demo-live-20261014T1616 --store clickhouse://localhost:18123/fleet --poll 2
# any terminal, while it runs (this one was taken at 63 s):
.venv/bin/python fleet/ledger.py status --run demo-live-20261014T1616 --store clickhouse://localhost:18123/fleet
```

You see from the mid-run status at 63 s. Coverage is climbing and the consumer lag is a dozen messages:

```
total [kafka]: bytes compressed 0, uncompressed 1550134, messages parsed 2970, accepted 2970, msgs/s 49.7
total: rejects 0, duplicates 0, gaps 0 (missing 0), kept 673901 B, dropped 876233 B, kept ratio 0.4347
backlog_bytes (latest row): None
kafka consumer lag [fleet.demo-live-20261014T1616]: 12 messages over 1 partitions (at the last ledger write)
coverage: 0.34375 (accepted 2970 / expected 8640)
episodes per cause: faulted_self 9, traffic 2, unknown 15
episodes excluded: left_censored 0, interrupted 0, open 8
```

At the end (emitter exited at 182 s, ingester at 202 s after 20 s idle):

```
status complete: 8640 messages (expected 8640) in 181.56 s wall, 48 messages/s, 0.02 MB/s uncompressed
ingest demo-live-20261014T1616: accepted 8640 (parsed 8640, rejected 0, duplicates 0), coverage 1.0, 43 messages/s over 199.51 s wall, exit 0
kafka consumer lag [fleet.demo-live-20261014T1616]: 0 messages over 1 partitions (at the last ledger write)
coverage: 1.0 (accepted 8640 / expected 8640)
episodes per cause: blocked_by_faulted 4, blocked_by_stuck 1, faulted_self 33, traffic 3, unknown 36
```

The same seeds give the same episodes on both paths: the cause counts match 3a exactly.

## 4. Breakdowns, the live stuck alert, and the Grafana panel that moves

**There is no "inject now" command.** Breakdowns come from the disturbance preset passed to the emitter:
`--disturb breakdown-heavy`. That is the emitter's default and the preset the S5 lanes and the benchmark used:
`{"breakdown": {"rate_per_hour": 8.0, "duration": [20, 60]}}` in `src/warehouse_rl/disturb.py`. The schedule is fixed
by (seed, config). So "injecting a breakdown" in this demo means starting step 3b with that preset. Injecting a
breakdown on a key press is not built and is not in the current plan.

You see in terminal 3 within seconds of the start (78 lines over the run; first lines):

```
alert demo-live-20261014T1616: latency figures meaningful: no (emit config is not now / realtime / speed 1, or unknown)
Z1-01 stuck at 10-7 for 30 s, unknown
Z0-04 stuck at 10-12 for 30 s, unknown
Z0-03 stuck at 2-16 for 30 s, unknown
Z0-06 stuck at 5-19 for 30 s, faulted_self
Z1-06 stuck at 8-23 for 30 s, faulted_self
```

The first line is honest about itself: at `--speed 20` the alert latency figures mean nothing. Only `--speed 1` gives
real-time latency (see README "Sprint 5", live table).

**Grafana.** Open `http://localhost:13000/d/fleet-stuck-analyser/fleet-stuck-analyser`, the dashboard **"Fleet stuck
analyser"** provisioned from `fleet/grafana/dashboard.json`. It has 23 panels in rows INTEGRATION, SIMULATION and
RESULTS. Pick the run in the **`run`** drop-down at the top. It sorts newest-name-first, and older runs such as
`s8b-score` sort above `demo-*`, so select yours by hand. The panel to watch is **"Cause mix"** (SIMULATION row). It is the only
panel checked in this run, and only on the file run `demo-20261014T1616`. **"Coverage (accepted / emitted)"** and
**"Consumer lag (messages)"** (INTEGRATION row) should move during the live leg. That was not checked.

In this job nobody opened a browser, so there is no screenshot. Instead, the "Cause mix" panel's own SQL was sent
through Grafana's datasource API, the same path the panel uses, before and after the ingest:

```sh
curl -s -u admin:admin localhost:13000/api/dashboards/uid/fleet-stuck-analyser   # -> "Fleet stuck analyser", 23 panels
cat > /tmp/gq.json <<EOF
{"queries":[{"refId":"A","datasource":{"type":"grafana-clickhouse-datasource","uid":"fleet-clickhouse"},"rawSql":"SELECT ifNull(cause, 'None') AS cause_label, count() AS episodes FROM stuck_episodes FINAL WHERE run = 'demo-20261014T1616' AND NOT left_censored AND resolution NOT IN ('open', 'interrupted') GROUP BY cause_label ORDER BY cause_label ASC","format":1,"queryType":"table","editorType":"sql"}],"from":"now-6h","to":"now"}
EOF
curl -s -u admin:admin -H 'Content-Type: application/json' localhost:13000/api/ds/query --data @/tmp/gq.json \
  | .venv/bin/python -c "import json,sys;r=json.load(sys.stdin)['results']['A'];f=r['frames'][0];print(r.get('status'), list(zip(*f['data']['values'])))"
```

You see: the panel was empty before the ingest (the same SQL against ClickHouse returned no rows). After it, Grafana
returned:

```
200 [('blocked_by_faulted', 4), ('blocked_by_stuck', 1), ('faulted_self', 33), ('traffic', 3), ('unknown', 36)]
```

## 5. The after-the-fact report and the scoring against ground truth

```sh
.venv/bin/python fleet/grade.py --run demo-20261014T1616 --store clickhouse://localhost:18123/fleet --once
.venv/bin/python fleet/score.py --run demo-20261014T1616 --glob 'fleet/data/demo-20261014T1616/*.jsonl.gz' \
  --store clickhouse://localhost:18123/fleet
.venv/bin/python fleet/report.py --run demo-20261014T1616 --store clickhouse://localhost:18123/fleet
```

You see (4 s):

```
grade demo-20261014T1616: stamped 80, not due 0, skipped_kind 0, verdicts avoidable_reset: reset_happened 3; stuck_cause: confirmed 20, inconclusive 57; forecasts {'outcome': {'graded': 0, 'open': 0}}
score demo-20261014T1616: truth 4, detected 44, matched 4, precision 0.09090909090909091, recall 1.0 -> .../fleet/data/demo-20261014T1616/score.json
.../fleet/data/demo-20261014T1616/report.md
.../fleet/data/demo-20261014T1616/hotspots.png
```

`report.md` excerpt:

```
# Stuck episode report: demo-20261014T1616
77 countable episodes (excluded: left_censored 0, interrupted 0, open 0).
## Hotspots (top 20 cells by episode count; ties by zone, cell)
- zone 1 cell 2-12: 4
- zone 0 cell 10-14: 3
- zone 1 cell 11-3: 3
## Duration (s, start to end; nearest-rank percentiles)
- p50: 280
- p95: 1065
## Resolution mix
- fault_cleared: 20
- moved: 11
- order_dropped: 42
- unresolved: 4
## Avoidable
- avoidable (detector definition, near-tautological at 5 s steps: every closed blocked_by_faulted episode)
- episodes: 3
```

`score.json` breaks down the unmatched detections: `"unmatched_detected": {"by_design": 20, "frozen": 20, "short_truth": 0}`.

How to read it: in one simulated hour on the small map, the detector caught all 4 stuck episodes the simulator itself
flags (recall 1.0, n = 4). It also flagged 40 more. Half of those are robots stopped on purpose (`by_design`); the other
half are robots frozen inside the episode (`frozen`). Hence precision 0.09. This is the definition gap README "Sprint 5"
describes: the detector calls any robot stopped with an order for 30 s "stuck", and the simulator does not. With n = 4
this is a demo, not a measurement. The measured numbers are the benchmark's (batch recall 0.698, precision 0.216,
`results/fleet/benchmark.json`).

## 6. Tear down and reset

What was run (4 s). It deletes only this demo's data and stops the stack, but keeps the volumes:

```sh
for t in evidence costmap stalls results rejects ingest_runs ingest_ledger stuck_episodes ingest_files transitions \
         forecast_grades decisions state_sample ingest_consumer_lag ingest_checkpoints; do
  curl -s localhost:18123/ --data-binary "ALTER TABLE fleet.$t DELETE WHERE run LIKE 'demo-%' SETTINGS mutations_sync=1"
done
curl -s localhost:18123/ --data-binary "SELECT count() FROM fleet.stuck_episodes WHERE run LIKE 'demo-%'"
docker exec fleet-redpanda-1 rpk topic delete fleet.demo-live-20261014T1616
rm -rf fleet/data/demo-20261014T1616 fleet/data/demo-live-20261014T1616
fleet/compose.sh down
fleet/compose.sh status
```

You see:

```
0
TOPIC                          STATUS
fleet.demo-live-20261014T1616  OK
 Container fleet-clickhouse-1  Removed
 Network fleet_default  Removed
VOLUME NAME        LINKS     SIZE
fleet_clickhouse   0         1.449GB
fleet_redpanda     0         6.558MB
fleet_grafana      0         41.15MB
```

The data is well under the 8 GB cap: about 1.5 GB in volumes plus 50 MB in `fleet/data/`.

**Full wipe: `UNVERIFIED` (not run).**

```sh
fleet/compose.sh reset      # = docker compose -f fleet/docker-compose.yml down, then docker volume rm fleet_redpanda fleet_clickhouse fleet_grafana
```

This is the brief's `docker compose down -v`. The named volumes are declared `name: fleet_*`, so `compose.sh reset`
removes them explicitly. It was not run in this job because `fleet_clickhouse` (1.45 GB) holds the Sprint 5
benchmark run and the `results` table behind the dashboard's RESULTS row. Rebuilding those means re-queuing the
41-minute exclusive benchmark item. Nobody was there to approve that. The committed numbers live in
`results/fleet/` either way. Run the reset only when you mean to lose the benchmark store.

## 7. What this is not, and what we need from you

What this is not: the logs are synthetic, written by a simulator. They are clean: zero rejects, zero gaps and zero
duplicates is what a simulator produces, not what a real fleet produces. The robots follow simulator rules on a
simulated warehouse map, not a real site. Nothing here is a claim about how the analyser would score on a real
fleet. The cause labels are compared against a proximity proxy, not against true cause. "Stuck" is our definition
(stopped with an order for 30 s), and that is why precision is low.

What we need from you (the Sprint 5 brief's open operator items, before Stage 2):

- The fleet's log field list, or one anonymised day of logs, so we can write the mapping file
  `fleet/mapping/<client>.yaml`.
- Your definition of "stuck". For example, does a robot waiting 30 s at a shelf count?
- Your definition of "manual reset".
- Whether the fleet manager speaks VDA 5050.
- How the files arrive: size, cadence, format, compression.

## 8. Live mode: place a roadblock and watch the analyser find it

This is a demo, not a measurement. One command starts a fleet, the ingester, a cost-map publisher, the lessons and the
grader, and serves what the analyser knows over HTTP on `127.0.0.1`. The replay page can then poll it.

```sh
# terminal 1 (medium map, the default regime: 80 hidden sticky floor cells, p 0.9-0.99; --speed 5 = 5x real time)
.venv/bin/python fleet/live.py --speed 5 --steps 500 --port 8765
# prints:  pgid <N>   listening http://127.0.0.1:8765   run dir fleet/data/live-<timestamp>
# terminal 2: serve the page (do not open it from a script)
python3 -m http.server 8000 --directory docs/replay
# in a browser: http://localhost:8000/?live=http://localhost:8765
#   click a highway cell, keep p at 0.95, press Place: the cell gets a blue outline ("placed by you").
#   It turns red only when the analyser's own cost map (built from the robots' messages) contains the cell.
# stop everything: Ctrl-C in terminal 1 (exit code 0, the whole process group is gone)
```

Without the page, the same thing from a shell (this is a real run, `--steps 400 --speed 20 --lesson-window-h 0.05`,
trimmed; the page itself was not opened in a browser):

```text
$ curl -s localhost:8765/state        # at ~20 s wall: step 74, sim_time 2026-01-01T00:06:10Z, truth null
$ curl -s -X POST -H 'Content-Type: application/json' -d '{"floor":{"5,3":0.95}}' localhost:8765/inject
{"applies_at_step":78}
$ curl -s localhost:8765/state        # 30 s later
step 194, costmap cells 31, "5,3" in costmap.cells: True, top10[0] = {"cell": "18,11", "cost": 1.0}
$ kill -INT <live.py>                 # exit code 0
```

What the viewer sees: robots move on the floor; the extractor panel counts messages read from the growing files; every
60 simulated seconds the cost map is rebuilt from stalls found in those messages (forward only, never from the
injection list); every 120 simulated seconds lessons are drawn and graded. `applies_at_step` is the step the emitter
will apply the roadblock at (it was 78 for an observed step of 74: the emitter polls the control file right after it
writes a step, plus a small lead). Add `--reveal` to get `/state.truth` and a toggle on the page that shows the hidden
roadblocks. `--router none` runs the fleet without the cost-aware router (the map is still published and shown).
`live.py` runs 720 steps unless you pass `--steps 500`.

Why the default regime is sticky floor, computed from `results/closed_loop_sticky/summary.json` (30 seeds):

| arm | pick rate (lines/h) |
|---|---|
| `none` (floor on, no map) | 16.13 |
| `map_a32` (cost map, alpha 32) | 20.30 |

Paired delta `map_a32` minus `none`: +4.18 lines/h, CI95 [2.20, 6.15], which is 11.1 % of the 37.5 lines/h the floor
costs (undisturbed reference 53.66). Measured config: `stuck_aware_cta` with `timeout` recovery, medium map, 500 steps.

The live demo refreshes the cost map from its own stream every 60 simulated seconds. That was NOT what was measured: the
measurement used one fixed map built in a separate phase-A run (`phaseA/costmap.json`). The live demo shows the
mechanism, not the number.

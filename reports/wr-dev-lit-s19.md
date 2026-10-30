# wr-dev-lit-s19: fleet log shapes a converter must read (2026-10-30)

Unattended docs job (opus). Output: `docs/LITERATURE.md` Part 11 (73 lines), the lane brief
`laptop-scheduler/jobs/wr-lane-s19b-converter.md` rewritten in place (DRAFT header removed, "what changed" at the top).
The brief edit lives in the laptop-scheduler working tree (that repo's jobs/ edits are not committed by docs jobs).

## Verdicts
1. **No public shape carries the contract as-is.** VDA 5050 2.x is closest, but its `orderId` is sticky: the schema says
   "the current order or the previous finished order ... kept until a new order is received". Busy = `nodeStates`
   non-empty. A converter (or a client) that passes VDA orderId straight through turns every finished, idle robot into
   "stopped with an order", which inflates stuck time. Part 2 §2 already said idle is derived from nodeStates; Part 11
   makes it a mapping key (`order.active_if_nonempty`).
2. **Mapping keys** (Part 11 item 2): layout wide|long (Formant exports are long, one line per stream value), time
   format + UTC + floor + keep last per second, header generate|column, robot/manufacturer const|column, position with
   unit and cell_m (floor), driving bool|enum|speed+omega strict, order column|intervals (MoRoOp's operations join with
   the gap rule and the charging blank via jobs.payload.job_type), errors const|levelled list, paused any-of predicates,
   loads, zone (file with an explicit order|column), stations block.
3. **Stations:** LIF file (OTTO documents a LIF export whose docks/chargers become stations) or an Open-RMF nav graph
   first; else a position-id column + dwell-share rule (generalised moroop.py, pooled over all files); else exit 2.
   Never from dwell positions alone (that would make the station filter hide the stall spots).
4. **Refute line:** `generic.py` with `maps/moroop.json` differs from `moroop.py` in any field -> not general enough. Part 11
   names no deviations.

## Found while checking (for the lane and the operator)
- **Zone order trap:** sorted MoRoOp file names put `2026_07_27_evening` before `..._morning`, while `moroop.SHIFTS`
  puts morning first (checked with python `sorted`). `zone.from: file` therefore needs an explicit `order` list, or
  shift 1 compares against the wrong shift.
- **S19A dependency:** `fleet/run_on_log.py` does not exist on master (ls, 30 Oct). The brief now FAILs early if it is still
  missing.
- **Operator question (not acted on):** the README calls the contract VDA 5050-shaped. A raw VDA 2.x stream FAILS
  `check_log.py` on agvPosition.x/y (float metres; `parse._is_int`, parse.py L59-60). Once a converter maps the cells but
  passes orderId straight through, check_log MATCHES and the stuck numbers are still wrong (verdict 1). Worth one
  sentence in "Run it on your own log".

- **Spec details the MoRoOp byte test depends on** (added to Part 11 and the brief after review): headerId per
  (zone, robot); orderId resolved at the native µs time, not the floored second; stations counted over native rows
  before the collapse.

## Sources (all verified@2026-10-30)
| shape | source | how read | rank |
|---|---|---|---|
| VDA 5050 2.0.0 | `json_schemas/state.schema`, tag 2.0.0 sha a8974b1 (the 2.0.0 `VDA5050_EN.md` raw path returned 14 bytes: not read) | curl raw | A |
| VDA 5050 2.1.0 | `state.schema` + `VDA5050_EN.md`, tag 2.1.0 sha 511d01d | curl raw, grep | A |
| MassRobotics | `AMR_Interop_Standard.json` + `examples/statusReport1.json`, main f9357a4 (PDF not read) | curl raw | A |
| Open-RMF | rmf_internal_msgs main 0e7ab42 (RobotState, RobotMode, Location, FleetState .msg); rmf_api_msgs main 5da2210 `robot_state.json`; rmf_ros2 main b892a9a `parse_graph.cpp` | curl raw | A |
| ROS 2 | common_interfaces rolling 05a5c4e `Odometry.msg`, `Twist.msg`; REP 103 (units), REP 105 (odom drift quote) | curl | A |
| Formant | llms.txt (502 lines, "Data export" section); `exporting-data-from-the-web-application.md` (updated 2025-11-11), `how-data-export-works.md` | curl | A |
| OTTO | `30495-31067-exporting-from-otto-fleet-analytics.html`, `30495-122774-robot-statuses.html`, `30495-136209-export-the-map-in-lif-format.html` (Software 2.36) | curl | A |
| InOrbit | https://developer.inorbit.ai/docs, WebFetch characters 0-100k of 198k only | WebFetch | A for what was read; export absence UNTESTED |
| VDMA LIF guideline | not found (search returned a third-party schema, continua-systems/vdma-lif, whose raw fetch did not parse as JSON) | WebSearch | UNTESTED |
| other COMPETITION.md vendors | not re-swept, per the brief | - | UNTESTED |

## Query log
- curl: VDA5050 raw files at tags 2.0.0 / 2.1.0; `git ls-remote` for tag and branch shas; GitHub tree API for
  MassRobotics; GitHub org repos API for VDA5050 (only `VDA5050`, `vd-m-a-5050`: no LIF repo there).
- WebSearch: "InOrbit developer docs export robot data CSV timeline pose" (nothing from InOrbit);
  "docs.ottomotors.com fleet analytics export CSV data" (nothing from OTTO; found the page through the OTTO nav instead);
  "VDMA LIF Layout Interchange Format stations interactionNodeIds stationPosition specification github".
- WebFetch: OTTO fleet analytics concepts page (nav only, first 100k); developer.inorbit.ai/docs (first 100k).

## Limits
Absence claims: InOrbit bulk export (half of one page read), OTTO per-robot state export (public tech docs only), and the
LIF standard text are all UNTESTED, not absent. MassRobotics position units: not stated in the JSON schema. The PDF was
not read. Formant's ms unit is inferred from a 13-digit example (B). Nothing was run against MoRoOp; the refute test is
the lane's.

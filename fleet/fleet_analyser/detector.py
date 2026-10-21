"""Stuck detector: a deterministic per-robot state machine over parsed Messages, event time only.

Vocabulary (docs/SCOPE.md "S5B"): a *stopped run* is a stretch of one robot's messages with driving false and one
non-empty orderId; a *stuck episode* is a stopped run that lasted >= stuck_after seconds. Neither has anything to do with
the ingest run name or with the env's StuckCounter / stuck_count. The detector consumes `Message` objects only: the
message's `custom` block never reaches it (parse drops it) and it must stay that way.

Input is processed in complete (zone, ts) batches: a zone's batch for T closes when a message of that zone with ts > T
arrives, or at end_zone(). Inside a batch robots are processed in serial order, and every cause is decided after the
whole batch's states are known, so the output does not depend on message order within a batch or on where a read
boundary splits one.

feed / end_zone / end_all return a list of event dicts:
  {"kind": "transition", ...}      one per state change per robot
  {"kind": "episode_open", ...}    at T_entry, with the cause (resolution "open")
  {"kind": "episode_close", ...}   at the ending message (or at end of input, resolution "unresolved")
FAULTED = some error with errorLevel CRITICAL or FATAL (VDA 5050: WARNING/URGENT can continue the order).

SERVICING (S13B, only when the Detector is given `stations`): a stopped run whose cell is at a station (productive
load/unload or a standby queue, docs/LITERATURE.md Part 2: never "blocked") and that has lasted >= stuck_after seconds.
It takes the place of STUCK for that run: no episode opens, no cause is computed, the transitions are still emitted. The
run's cell is the cell of the run's FIRST stopped message (the same definition in fleet/timebudget.py). A robot that
moves off the station and stops again starts a new run, judged on its own cell. `at_station(x, y, stations, radius)` is
the one predicate (Manhattan distance <= radius to any station goal cell; False when stations is None). With
stations=None nothing here changes: every output is byte-identical to the detector without this option.

SERVICING BOUND (S14A, only with `stations` AND `servicing_max_s=T`; default None = everything above, byte-identical): a
station stop that lasts far longer than a normal dwell is a stop, not service. The first still-stopped, non-faulted
observation of a SERVICING run with ts - run start >= T converts the run: ONE stuck episode opens at that observation
(episode_open, t_entry = that ts), start = the run's stop time, cause "station_overrun", blocker None, servicing_s = T,
and the state is STUCK for the rest of the run. The episode duration is the whole stop (end message ts - stop time), as
for every episode. "The stop lasted more than T" and "episode_open at the first observation >= stop + T" agree because the
observation at stop + T is itself still stopped: a stop whose ending message (the robot driving again, or another order)
is at exactly stop + T opens nothing. If T < stuck_after the conversion happens at the first SERVICING observation
(stuck_after). servicing_runs still counts the run; station_overruns counts the conversions. A faulted message before T
opens faulted_self as above, that episode stays the run's only one (no conversion; when the fault clears the run is
SERVICING again). A faulted message after the conversion makes the state FAULTED and leaves the open station_overrun
episode as it is (the cause is decided once, as for every open episode); when the fault clears the state is STUCK again.
With the bound None no key is added to any event: servicing_s exists only on overrun episodes. CAUSE_LABELS maps each
cause key to the default client text and cause_label(cause, blocker_on_route) picks the on-route wording (S14D); the ingest
and export layers attach it, never this module's events. Every episode event carries blocker_on_route (see _cause).
Every event also has "zone", "robot", and a "decided_by" = (serial, ts) naming the message that triggered it.
"""
from .parse import iso

STEP_S = 5
DEFAULT_STUCK_AFTER = 30

FAULTED, IDLE, MOVING, STUCK, STOPPED_WITH_ORDER, RECOVERED, SERVICING = (
    "FAULTED", "IDLE", "MOVING", "STUCK", "STOPPED_WITH_ORDER", "RECOVERED", "SERVICING")
CAUSES = ("faulted_self", "blocked_by_faulted", "blocked_by_stuck", "traffic", "unknown", "station_overrun")
# S14D: CAUSE_LABELS is the per-key default text, the NOT-on-route (or route unknown) wording: a neighbour at
# Manhattan <= 1 only licenses "Stopped next to ...". ROUTE_LABELS is the wording when that neighbour stands on the
# robot's reported next route node (blocker_on_route True). cause_label(cause, blocker_on_route) is the one function.
CAUSE_LABELS = {
    "faulted_self": "Robot error, cannot continue order",
    "blocked_by_faulted": "Stopped next to a broken robot",
    "blocked_by_stuck": "Stopped next to a stuck robot",
    "traffic": "Stopped next to another robot",
    "unknown": "Stopped, cause not identified",
    "station_overrun": "Station stop over time limit",
}
ROUTE_LABELS = {
    "blocked_by_faulted": "Blocked by a broken robot",
    "blocked_by_stuck": "Blocked by a stuck robot",
    "traffic": "Traffic wait",
}


def cause_label(cause, blocker_on_route=None):
    """The client text of a stop cause: ROUTE_LABELS when blocker_on_route is True, else CAUSE_LABELS; a key outside the
    maps is its own label."""
    if blocker_on_route is True and cause in ROUTE_LABELS:
        return ROUTE_LABELS[cause]
    return CAUSE_LABELS.get(cause, cause)
RESOLUTIONS = ("moved", "order_dropped", "fault_cleared", "unresolved")


class _Robot:
    __slots__ = ("state", "last_ts", "fault_since", "run", "episode")
    # run["censored"]: the run began at the robot's first message after a resume, so its true start is unknown

    def __init__(self):
        self.state = None
        self.last_ts = None
        self.fault_since = None  # ts at which the current consecutive faulted streak began
        self.run = None  # dict(order, since, cell, faulted_last) while in a stopped run
        self.episode = None  # the open episode dict


class _Zone:
    def __init__(self):
        self.pending = {}  # ts -> [Message]
        self.max_ts = None
        self.robots = {}


def _near(a, b):
    return abs(a.x - b.x) + abs(a.y - b.y) <= 1


def stations_of(stations, zone):
    """The station goal cells of one zone: `stations` is a set (every zone), a mapping zone -> set (key "*" = every
    other zone) or None."""
    if stations is None or not hasattr(stations, "get"):
        return stations
    got = stations.get(zone)
    return got if got is not None else stations.get("*")


def at_station(x, y, stations, radius=0):
    """True iff (x, y) is within Manhattan distance <= radius of a station goal cell. False when stations is None/empty."""
    if not stations:
        return False
    return any(abs(x - sx) + abs(y - sy) <= radius for sx, sy in stations)


class Detector:
    def __init__(self, stuck_after=DEFAULT_STUCK_AFTER, resumed=False, stations=None, station_radius=0,
                 servicing_max_s=None):
        """resumed=True: this detector starts mid-stream at a checkpoint. A stopped run that begins at a robot's first
        message seen here may have started before the checkpoint; episodes from such a run carry left_censored=True
        (their start and duration are lower bounds).
        stations: a set of (x, y) station GOAL cells, or a mapping zone -> such a set (key "*" = every other zone), or
        None (default: the rule is unaware of stations). A stopped run starting within `station_radius` (Manhattan) of
        one is SERVICING instead of STUCK. servicing_runs counts the runs that became SERVICING.
        A FAULTED message is never SERVICING and never suppresses an episode: the state is FAULTED and an episode opens
        (cause faulted_self, start = run start) at the first faulted message once the run is >= stuck_after old, as with
        stations=None. A run that was servicing and then faulted stays counted in servicing_runs (it was counted when it
        became SERVICING); if the fault clears while still stopped on the station the state returns to SERVICING and the
        open episode stays open until the run ends.
        servicing_max_s: S14A, see the module docstring (None = no bound; has an effect only with stations)."""
        self.stuck_after = stuck_after
        self.resumed = resumed
        self.stations = stations
        self.station_radius = station_radius
        self.servicing_max_s = servicing_max_s
        self.servicing_runs = 0
        self.station_overruns = 0
        self._zones = {}

    def _stations_of(self, zone):
        return stations_of(self.stations, zone)

    # ------------------------------------------------------------------ input
    def feed(self, msg):
        z = self._zones.setdefault(msg.zone, _Zone())
        z.pending.setdefault(msg.ts, []).append(msg)
        events = []
        if z.max_ts is None or msg.ts > z.max_ts:
            z.max_ts = msg.ts
        for ts in sorted(t for t in z.pending if t < z.max_ts):
            events.extend(self._process_batch(msg.zone, z, ts, z.pending.pop(ts)))
        return events

    def earliest_pending_ts(self, zone):
        z = self._zones.get(zone)
        return min(z.pending) if z is not None and z.pending else None

    def end_zone(self, zone):
        """All input of the zone is in: close the open batches, then close open episodes as `unresolved`."""
        z = self._zones.get(zone)
        if z is None:
            return []
        events = []
        for ts in sorted(z.pending):
            events.extend(self._process_batch(zone, z, ts, z.pending.pop(ts)))
        for serial in sorted(z.robots):
            r = z.robots[serial]
            if r.episode is not None:
                events.append(self._close(zone, serial, r, r.last_ts, "unresolved", (serial, r.last_ts)))
        return events

    def end_all(self):
        events = []
        for zone in sorted(self._zones):
            events.extend(self.end_zone(zone))
        return events

    # ------------------------------------------------------------------ batch
    def _process_batch(self, zone, z, ts, msgs):
        events = []
        msgs = sorted(msgs, key=lambda m: m.serial)
        entering = []  # (robot, msg, episode) opened by this batch
        states = {}
        batch = {}
        for m in msgs:
            r = z.robots.setdefault(m.serial, _Robot())
            if r.last_ts is not None and m.ts <= r.last_ts:
                continue  # out of order for this robot: event time must move forward
            state, closed, opened = self._step(zone, r, m)
            if closed is not None:
                events.append(closed)
            if state != r.state:
                events.append(dict(kind="transition", zone=zone, robot=m.serial, ts=m.ts, from_state=r.state or "NONE",
                                   to_state=state, cell=[m.x, m.y], order_id=m.order_id, decided_by=(m.serial, m.ts)))
            r.state = state
            r.last_ts = m.ts
            states[m.serial] = state
            batch[m.serial] = m
            if opened is not None:
                entering.append((r, m, opened))
        for r, m, ep in entering:
            if "servicing_s" in ep:  # S14A: a converted station stop, its cause is fixed
                cause, blocker, blocker_faulted_s, on_route = "station_overrun", None, None, None
            else:
                cause, blocker, blocker_faulted_s, on_route = self._cause(z, m, batch, states)
            ep.update(cause=cause, blocker=blocker, blocker_faulted_s=blocker_faulted_s, blocker_on_route=on_route)
            events.append(self._row("episode_open", zone, m.serial, ep, (m.serial, m.ts)))
        return events

    def _step(self, zone, r, m):
        """Advance one robot by one message. Returns (state, closed_episode_event | None, opened_episode | None)."""
        r.fault_since = (r.fault_since if r.fault_since is not None else m.ts) if m.faulted else None
        run = r.run
        continues = run is not None and not m.driving and m.order_id == run["order"]
        closed = None
        recovered = False
        if run is not None and not continues:  # m is the ending message E
            if r.episode is not None:
                if m.order_id != run["order"]:
                    resolution = "order_dropped"
                elif run["faulted_last"]:
                    resolution = "fault_cleared"
                else:
                    resolution = "moved"
                closed = self._close(zone, m.serial, r, m.ts, resolution, (m.serial, m.ts))
                recovered = True
            r.run = run = None
        if run is None and not m.driving and m.order_id != "":
            r.run = run = dict(order=m.order_id, since=m.ts, cell=[m.x, m.y], faulted_last=m.faulted,
                               censored=self.resumed and r.last_ts is None)
            if self.stations is not None:
                run["station"] = at_station(m.x, m.y, self._stations_of(zone), self.station_radius)
        elif run is not None:
            run["faulted_last"] = m.faulted
        stuck_now = run is not None and m.ts - run["since"] >= self.stuck_after
        servicing = stuck_now and run.get("station", False) and not m.faulted
        if servicing and not run.get("counted"):
            run["counted"] = True
            self.servicing_runs += 1
        overrun = False
        if servicing and self.servicing_max_s is not None and not run.get("overrun") and r.episode is None \
                and m.ts - run["since"] >= self.servicing_max_s:
            run["overrun"] = overrun = True
            self.station_overruns += 1
        if run is not None and run.get("overrun"):
            servicing = False  # converted: STUCK for the rest of the run (a fault in between shows as FAULTED)
        if recovered:
            state = RECOVERED
        elif m.faulted:
            state = FAULTED
        elif m.order_id == "":
            state = IDLE
        elif m.driving:
            state = MOVING
        elif servicing:
            state = SERVICING
        elif stuck_now:
            state = STUCK
        else:
            state = STOPPED_WITH_ORDER
        opened = None
        if stuck_now and not servicing and r.episode is None:
            start = run["since"]
            r.episode = opened = dict(episode_id=f"{m.serial}@{iso(start)}", zone=zone, robot=m.serial,
                                      order_id=run["order"], start=start, start_iso=iso(start), t_entry=m.ts,
                                      cell=list(run["cell"]), cause=None, blocker=None, blocker_faulted_s=None,
                                      blocker_on_route=None,
                                      end=None, duration_s=None, resolution="open", avoidable=False,
                                      avoidable_s=None, left_censored=run["censored"])
            if overrun:
                opened["servicing_s"] = self.servicing_max_s
        return state, closed, opened

    def _cause(self, z, m, batch, states):
        """(cause, blocker serial, blocker_faulted_s, blocker_on_route) of an episode entered on message m.

        The category precedence is faulted_self > blocked_by_faulted > blocked_by_stuck > traffic > unknown. Within the
        chosen category only, a robot standing on m's next route node (m.next_x, m.next_y, same batch) is the blocker,
        else the lowest serial; an on-route stuck robot never beats an off-route faulted one. blocker_faulted_s comes
        from the chosen blocker; traffic has no blocker (None). blocker_on_route (neighbour causes only): None when m
        reports no route (nodeStates absent, [] or unusable), else True iff the chosen blocker (traffic: any robot of
        the adjacent set) stands on the next node. faulted_self and unknown have no neighbour: None."""
        if m.faulted:
            return "faulted_self", None, None, None
        others = [o for s, o in sorted(batch.items()) if s != m.serial and _near(m, o)]
        routed = m.nodes_reported and m.next_x is not None

        def pick(group):
            on = [o for o in group if routed and o.x == m.next_x and o.y == m.next_y]
            return (on or group)[0], (bool(on) if routed else None)

        faulted = [o for o in others if o.faulted]
        if faulted:
            b, on_route = pick(faulted)
            return "blocked_by_faulted", b.serial, m.ts - z.robots[b.serial].fault_since, on_route
        stuck = [o for o in others if states[o.serial] == STUCK]
        if stuck:
            b, on_route = pick(stuck)
            return "blocked_by_stuck", b.serial, None, on_route
        if others:
            return "traffic", None, None, pick(others)[1]
        return "unknown", None, None, None

    def _close(self, zone, serial, r, end, resolution, decided_by):
        ep = r.episode
        r.episode = None
        duration = end - ep["start"]
        avoidable = ep["cause"] == "blocked_by_faulted" and resolution != "unresolved" and duration > self.stuck_after
        ep.update(end=end, duration_s=duration, resolution=resolution, avoidable=avoidable,
                  avoidable_s=duration - self.stuck_after if avoidable else None)
        return self._row("episode_close", zone, serial, ep, decided_by)

    @staticmethod
    def _row(kind, zone, serial, ep, decided_by):
        return dict(ep, kind=kind, zone=zone, robot=serial, decided_by=decided_by)

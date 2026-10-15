"""The emit ledger: exact counts of what the emitter produced; the denominator for every later coverage number.

One document per run, rewritten atomically (tmp file in the same directory + os.replace). Each zone reports a snapshot
(see ZONE_FIELDS); totals are computed here as exact sums of the zones, never stored separately.
The top-level `truth` is null until the ground-truth sidecar truth.json is written, then {file, bytes}; it is in no zone
or total field.
Zone states: pending, running, complete, failed, not_started. Run status: running | complete | failed.
A zone is `complete` only when messages == expected (robots * steps), it did not fail and (kafka) no record failed
delivery; the run is `complete` only when every configured zone is. Demo noise runs (S8I) add `injected_noise`
{malformed, malformed_by_kind {json, timestamp, type}, duplicates, gap_ids} per zone and, summed, in total (absent
otherwise); the extra lines count in bytes_uncompressed but not in messages / expected_messages. Kafka zones also carry integer `delivered` and
`delivery_failed` (delivered + delivery_failed == messages once the sink is closed); file zones carry null for both.
"""
import json
import os
from pathlib import Path

ZONE_FIELDS = ("messages", "bytes_uncompressed", "bytes_compressed", "files", "first_timestamp", "last_timestamp",
               "steps_done", "robots", "agvs", "pickers", "delivered", "delivery_failed")


NOISE_KINDS = ("json", "timestamp", "type")


def _blank_noise():
    return dict(malformed=0, malformed_by_kind=dict.fromkeys(NOISE_KINDS, 0), duplicates=0, gap_ids=0)


def _blank_zone():
    return dict(state="pending", messages=0, bytes_uncompressed=0, bytes_compressed=0, files=[], first_timestamp=None,
                last_timestamp=None, steps_done=0, robots=None, agvs=None, pickers=None, delivered=None,
                delivery_failed=None)


class EmitLedger:
    def __init__(self, path, config, zones, steps, demo_mode=False, demo_noise=False):
        self.path = Path(path)
        self.config = dict(config)
        self.steps = steps
        self.zones = {z: _blank_zone() for z in range(zones)}
        # S8F demo runs only: applied injections per zone (an int), kept OUT of ZONE_FIELDS / _blank_zone so a non-demo
        # document has exactly the old keys
        self.demo_mode = bool(demo_mode)
        self.injections = {z: 0 for z in range(zones)}
        self.demo_noise = bool(demo_noise)  # S8I: per-zone injected_noise, only in the document of a noise run
        self.noise = {z: _blank_noise() for z in range(zones)}
        self.error = None
        self.truth = None  # {file, bytes} once the emitter has written the sidecar; never counted in any zone / total

    def update(self, zone, snapshot=None, state=None):
        z = self.zones[zone]
        if snapshot:
            for k in ZONE_FIELDS:
                if k in snapshot:
                    z[k] = snapshot[k]
        if state is not None:
            z["state"] = state
        if self.demo_mode and snapshot and "injections" in snapshot:
            self.injections[zone] = snapshot["injections"]
        if self.demo_noise and snapshot and "injected_noise" in snapshot:
            self.noise[zone] = snapshot["injected_noise"]

    def mark_unfinished(self):
        """After a failure: zones that never started are not_started; running ones stay as they were reported."""
        for z in self.zones.values():
            if z["state"] == "pending":
                z["state"] = "not_started"

    def _zone_doc(self, zone, z):
        expected = z["robots"] * self.steps if z["robots"] is not None else None
        complete = expected is not None and z["messages"] == expected and z["state"] != "failed" \
            and not (z["delivery_failed"] or 0) > 0  # kafka: a record that was not delivered is not emitted
        doc = dict(zone=zone, status=z["state"], seed=self.config["seed_base"] + zone, messages=z["messages"],
                    expected_messages=expected, complete=complete, bytes_uncompressed=z["bytes_uncompressed"],
                    bytes_compressed=z["bytes_compressed"], delivered=z["delivered"],
                    delivery_failed=z["delivery_failed"], robots=z["robots"], agvs=z["agvs"], pickers=z["pickers"],
                    steps=self.steps, steps_done=z["steps_done"], first_timestamp=z["first_timestamp"],
                    last_timestamp=z["last_timestamp"], files=z["files"])
        if self.demo_mode:
            doc["injections"] = self.injections[zone]
        if self.demo_noise:
            doc["injected_noise"] = self.noise[zone]
        return doc

    def document(self, status):
        zdocs = [self._zone_doc(z, self.zones[z]) for z in sorted(self.zones)]

        def total_of(key):
            vals = [d[key] for d in zdocs]
            return None if any(v is None for v in vals) else sum(vals)

        total_expected = total_of("expected_messages")
        messages = sum(d["messages"] for d in zdocs)
        total = dict(messages=messages, expected_messages=total_expected,
                     complete=total_expected is not None and messages == total_expected
                     and all(d["complete"] for d in zdocs),
                     bytes_uncompressed=sum(d["bytes_uncompressed"] for d in zdocs),
                     bytes_compressed=total_of("bytes_compressed"), delivered=total_of("delivered"),
                     delivery_failed=total_of("delivery_failed"), robots=total_of("robots"),
                     agvs=total_of("agvs"), pickers=total_of("pickers"),
                     steps_done=sum(d["steps_done"] for d in zdocs))
        doc = dict(status=status, config=self.config, zones=zdocs, total=total, truth=self.truth)
        if self.demo_mode:
            doc["demo_mode"] = True
            doc["injections"] = sum(self.injections.values())
        if self.demo_noise:
            doc["total"]["injected_noise"] = dict(
                malformed=sum(d["injected_noise"]["malformed"] for d in zdocs),
                malformed_by_kind={k: sum(d["injected_noise"]["malformed_by_kind"][k] for d in zdocs) for k in NOISE_KINDS},
                duplicates=sum(d["injected_noise"]["duplicates"] for d in zdocs),
                gap_ids=sum(d["injected_noise"]["gap_ids"] for d in zdocs))
        if self.error:
            doc["error"] = self.error
        return doc

    def write(self, status):
        """Atomic: the document goes to <name>.tmp in the same directory, then os.replace."""
        doc = self.document(status)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        with open(tmp, "w") as f:
            json.dump(doc, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)
        return doc

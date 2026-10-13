"""Tests for the Kafka source (fake consumer) and the KafkaSink delivery accounting (fake producer). No broker, no
confluent_kafka, no network. Each case names its red demonstration in an `# inject:` comment. The live path (Redpanda)
is covered by the one-time smoke run recorded in the PR, not by the gate."""
import io
import json
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "fleet", ROOT / "src", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fleet.tests.test_fleet_ingest import Clock, interleaved, scenario  # noqa: E402
from fleet_analyser import emit_ledger as el  # noqa: E402
from fleet_analyser import kafka_source as ks  # noqa: E402
from fleet_analyser import ledger, sinks  # noqa: E402
from fleet_analyser.store import MemoryStore  # noqa: E402

TOPIC = "fleet.state"


# ------------------------------------------------------------------------------------------------ source fakes
class Msg:
    def __init__(self, offset, value, partition=0, topic=TOPIC, err=None):
        self._o, self._v, self._p, self._t, self._e = offset, value, partition, topic, err

    def offset(self):
        return self._o

    def value(self):
        return self._v

    def partition(self):
        return self._p

    def topic(self):
        return self._t

    def error(self):
        return self._e


class TP:
    def __init__(self, topic, partition, offset=-1001):
        self.topic, self.partition, self.offset = topic, partition, offset


class FakeConsumer:
    """consume() hands out the prepared batches in order, then empty lists; every call advances the fake clock one second
    (the poll timeout). on_commit() runs at the moment commit() is called, so a test can look at the store then."""

    def __init__(self, batches, clock=None, high=None):
        self.batches, self.clock, self.calls, self.commits, self.on_commit = list(batches), clock, 0, 0, None
        self.high = high  # high watermark per partition, for the lag
        self.closed = False
        self._next = {}

    def consume(self, num_messages=1, timeout=1.0):
        self.calls += 1
        if self.clock is not None:
            self.clock.t += 1
        batch = self.batches.pop(0) if self.batches else []
        for m in batch:
            self._next[m.partition()] = m.offset() + 1
        return batch

    def commit(self, asynchronous=True, **kw):
        assert asynchronous is False, "the source must commit synchronously"
        if self.on_commit:
            self.on_commit()
        self.commits += 1

    def assignment(self):
        return [TP(TOPIC, p) for p in sorted(self._next)]

    def position(self, tps):
        return [TP(t.topic, t.partition, self._next[t.partition]) for t in tps]

    def get_watermark_offsets(self, tp, timeout=None, cached=False):
        return 0, (self.high or {}).get(tp.partition, self._next[tp.partition])

    def close(self):
        self.closed = True


def messages(steps=60, start=0, extra=()):
    """The S5B1 scenario as kafka messages in arrival order (both zones, one partition) + optional raw extras."""
    vals = list(interleaved(scenario(steps))) + list(extra)
    return [Msg(start + i, v) for i, v in enumerate(vals)]


def run(batches, store=None, until_idle=2, clock=None, **kw):
    clock = clock or Clock()
    store = MemoryStore() if store is None else store
    consumer = FakeConsumer(batches, clock)
    ing = ks.KafkaIngester("r", store, consumer, TOPIC, until_idle=until_idle, clock=clock, ledger_interval=1e9, **kw)
    code = ing.run_loop()
    return ing, store, consumer, code


class LoggingStore(MemoryStore):
    """Logs every write as ('write', table) and, via the consumer's on_commit, every commit, in one sequence."""

    def __init__(self, log, fail_on=None):
        super().__init__()
        self.log, self.fail_on = log, fail_on

    def _check(self, table):
        if self.fail_on == table:
            raise RuntimeError(f"store is down ({table})")
        self.log.append(("write", table))

    def insert(self, table, rows):
        self._check(table)
        super().insert(table, rows)

    def upsert(self, table, key_cols, rows):
        self._check(table)
        super().upsert(table, key_cols, rows)


class TestKafkaCommitOrder(unittest.TestCase):
    def test_commit_happens_only_after_the_batch_checkpoint_ledger_and_rows_are_in_the_store(self):
        # inject: call consumer.commit() at the top of process_batch (before the rows), or before _write_checkpoint
        clock = Clock()
        log = []
        store = LoggingStore(log)
        all_msgs = messages()
        batches = [all_msgs[:100], all_msgs[100:230], all_msgs[230:]]
        consumer = FakeConsumer(batches, clock)
        seen = []

        def on_commit():
            log.append(("commit",))
            led = store.select("ingest_ledger", {"run": "r"})
            cps = store.select("ingest_checkpoints", {"run": "r"})
            seen.append(dict(accepted=sum(r["messages_accepted"] for r in led), cp=cps[0]["offset_uncompressed"],
                             tx=len(store.select("transitions")), eps=len(store.select("stuck_episodes")),
                             decs=len(store.select("decisions"))))

        consumer.on_commit = on_commit
        ing = ks.KafkaIngester("r", store, consumer, TOPIC, until_idle=2, clock=clock, ledger_interval=1e9)
        self.assertEqual(ing.run_loop(), 0)
        self.assertEqual(consumer.commits, 3)
        # at commit k the checkpoint and the ingest ledger cover exactly the messages of batches 1..k
        self.assertEqual([s["cp"] for s in seen], [100, 230, len(all_msgs)])
        self.assertEqual([s["accepted"] for s in seen], [100, 230, len(all_msgs)])
        # the rows derived so far are already stored: compare with a run that stops at the same batch boundary
        for k, cut in enumerate((100, 230, len(all_msgs))):
            ref2 = ks.KafkaIngester("r", MemoryStore(), FakeConsumer([]), TOPIC, clock=Clock(), ledger_interval=1e9)
            ref2.process_batch(all_msgs[:cut])
            self.assertEqual(seen[k]["tx"], len(ref2.store.select("transitions")))
            self.assertEqual(seen[k]["eps"], len(ref2.store.select("stuck_episodes")))
            self.assertEqual(seen[k]["decs"], len(ref2.store.select("decisions")))
        self.assertGreater(seen[-1]["decs"], 0)
        # event order: per batch, checkpoint + ledger + runs writes come before that batch's commit
        commits = [i for i, e in enumerate(log) if e == ("commit",)]
        start = 0
        for c in commits:
            window = {e[1] for e in log[start:c] if e[0] == "write"}
            self.assertTrue({"ingest_checkpoints", "ingest_ledger", "ingest_runs"} <= window, window)
            if start == 0:
                self.assertIn("transitions", window)
            start = c + 1

    def test_a_store_error_anywhere_in_the_batch_means_no_commit(self):
        # inject: wrap the store writes of process_batch in try/except and commit anyway
        msgs = messages(extra=[b"this is not json\n"])
        for table in ("transitions", "stuck_episodes", "decisions", "evidence", "state_sample", "rejects",
                      "ingest_checkpoints", "ingest_ledger", "ingest_runs"):
            with self.subTest(table=table):
                clock = Clock()
                store = LoggingStore([], fail_on=table)
                consumer = FakeConsumer([msgs], clock)
                ing = ks.KafkaIngester("r", store, consumer, TOPIC, until_idle=2, clock=clock, ledger_interval=1e9)
                with self.assertRaisesRegex(RuntimeError, f"store is down \\({table}\\)"):
                    ing.run_loop()
                self.assertEqual(consumer.commits, 0)
        clock = Clock()  # control: the same input with a healthy store commits and writes every one of those tables
        log = []
        _, store, consumer, code = run([msgs], store=LoggingStore(log))
        self.assertEqual((code, consumer.commits), (0, 1))
        self.assertTrue({"transitions", "stuck_episodes", "decisions", "evidence", "state_sample", "rejects",
                         "ingest_checkpoints", "ingest_ledger", "ingest_runs"} <= {t for _, t in log})

    def test_a_redelivered_batch_is_counted_as_duplicates_and_decides_nothing_twice(self):
        # inject: count a redelivered message as accepted again, or run the detector on it
        msgs = messages()
        _, ref, _, _ = run([msgs])
        clock = Clock()
        store = MemoryStore()
        consumer = FakeConsumer([msgs, msgs], clock)  # the broker redelivers the whole batch
        ing = ks.KafkaIngester("r", store, consumer, TOPIC, until_idle=2, clock=clock, ledger_interval=1e9)
        ing.run_loop()
        rows = store.select("ingest_ledger", {"run": "r"})
        self.assertEqual(sum(r["messages_accepted"] for r in rows), len(msgs))
        self.assertEqual(sum(r["duplicates"] for r in rows), len(msgs))
        self.assertEqual(sum(r["messages_parsed"] for r in rows), 2 * len(msgs))
        self.assertEqual([d["id"] for d in store.select("decisions")], [d["id"] for d in ref.select("decisions")])
        kinds = [d["kind"] for d in store.select("decisions")]
        self.assertEqual(len(kinds), len(set((d["dedup_key"]) for d in store.select("decisions"))))  # no second decision
        self.assertGreater(kinds.count("stuck_cause"), 0)
        self.assertEqual(len(store.select("stuck_episodes")), len(ref.select("stuck_episodes")))
        self.assertEqual(len(store.select("transitions")), len(ref.select("transitions")))

    def test_restart_with_the_same_store_resumes_from_the_checkpoint(self):
        # inject: skip restoring the sequence tracker from ingest_checkpoints on resume
        msgs = messages()
        store = MemoryStore()
        run([msgs[:150]], store=store, until_idle=0)
        ing, _, _, _ = run([msgs[100:]], store=store, until_idle=0)  # the new process is redelivered 50 old messages
        rows = store.select("ingest_ledger", {"run": "r"})
        self.assertEqual(sum(r["messages_accepted"] for r in rows), len(msgs))
        self.assertEqual(sum(r["duplicates"] for r in rows), 50)


class TestKafkaLedger(unittest.TestCase):
    def test_source_name_backlog_null_and_consumer_lag_in_status(self):
        # inject: write source "file", a numeric backlog_bytes, or drop the lag row / status line
        clock = Clock()
        store = MemoryStore()
        msgs = messages()
        consumer = FakeConsumer([msgs], clock, high={0: len(msgs) + 25})
        ing = ks.KafkaIngester("r", store, consumer, TOPIC, until_idle=2, clock=clock, ledger_interval=1e9)
        ing.run_loop()
        rows = store.select("ingest_ledger", {"run": "r"})
        self.assertTrue(rows)
        self.assertEqual({r["source"] for r in rows}, {"kafka"})
        self.assertTrue(all(r["backlog_bytes"] is None for r in rows))
        self.assertEqual(store.select("ingest_runs", {"run": "r"})[0]["glob"], f"kafka:{TOPIC}")
        lag = store.select("ingest_consumer_lag", {"run": "r"})
        self.assertEqual([(r["topic"], r["lag_messages"], r["partitions"]) for r in lag], [(TOPIC, 25, 1)])
        text = "\n".join(ledger.status_lines(store, "r"))
        self.assertIn("total [kafka]", text)
        self.assertIn("backlog_bytes (latest row): None", text)
        self.assertIn(f"kafka consumer lag [{TOPIC}]: 25 messages over 1 partitions", text)
        self.assertEqual(sum(r["messages_accepted"] for r in rows), len(msgs))

    def test_coverage_against_an_emit_ledger_given_with_emit_path(self):
        # inject: ignore emit_path (coverage stays None)
        msgs = messages()
        with tempfile.TemporaryDirectory() as d:
            doc = {"status": "complete", "config": {"t0_mode": "fixed", "rate": "flat", "speed": 0.0}, "zones": [],
                   "total": {"expected_messages": len(msgs)}}
            (Path(d) / "emit_ledger.json").write_text(json.dumps(doc))
            clock = Clock()
            store = MemoryStore()
            ing = ks.KafkaIngester("r", store, FakeConsumer([msgs], clock), TOPIC, emit_path=Path(d) / "emit_ledger.json",
                                   until_idle=1, clock=clock, ledger_interval=1e9)
            ing.run_loop()
        acc = sum(r["messages_accepted"] for r in store.select("ingest_ledger"))
        self.assertEqual(ledger.coverage(acc, store.select("ingest_runs")[0]["expected_messages"]), 1.0)

    def test_broker_errors_are_logged_and_skipped_and_none_values_are_rejects(self):
        # inject: pass messages with error() through to the pipeline
        clock = Clock()
        log = []
        good = messages(steps=3)
        batch = [Msg(99, b"x", err="boom")] + good + [Msg(len(good), None)]
        store = MemoryStore()
        consumer = FakeConsumer([batch], clock)
        ing = ks.KafkaIngester("r", store, consumer, TOPIC, until_idle=1, clock=clock, ledger_interval=1e9,
                               log=log.append)
        ing.run_loop()
        self.assertEqual(log, ["kafka error: boom"])
        rej = store.select("rejects")
        self.assertEqual([(r["source"], r["file"], r["offset"], r["reason"]) for r in rej],
                         [("kafka", f"{TOPIC}/0", len(good), "json")])


class TestUntilIdle(unittest.TestCase):
    def test_input_ends_after_s_seconds_without_messages_and_open_episodes_close(self):
        # inject: compare with > instead of >=, start the idle timer once instead of after every batch, or never stop
        for idle in (0, 2, 5):
            with self.subTest(idle=idle):
                _, store, consumer, code = run([messages()], until_idle=idle)
                self.assertEqual(consumer.calls, 1 + max(idle, 1))  # the batch, then `idle` empty seconds (min one call)
                self.assertEqual(code, 0)
                self.assertIn("unresolved", {e["resolution"] for e in store.select("stuck_episodes")})
        # the timer restarts after every batch: a gap shorter than S between two batches does not end the input
        clock = Clock()
        a, b = messages()[:100], messages()[100:]
        consumer = FakeConsumer([a, [], [], b], clock)
        store = MemoryStore()
        ing = ks.KafkaIngester("r", store, consumer, TOPIC, until_idle=3, clock=clock, ledger_interval=1e9)
        ing.run_loop()
        self.assertEqual(sum(r["messages_accepted"] for r in store.select("ingest_ledger")), len(a) + len(b))
        self.assertEqual(consumer.calls, 4 + 3)

    def test_stop_ends_the_loop_without_until_idle(self):
        # inject: ignore self._stop in run_loop
        clock = Clock()
        consumer = FakeConsumer([messages(steps=3)], clock)
        ing = ks.KafkaIngester("r", MemoryStore(), consumer, TOPIC, until_idle=None, clock=clock, ledger_interval=1e9)
        orig = consumer.consume

        def consume(**kw):
            out = orig(**kw)
            if consumer.calls == 3:
                ing.stop()
            return out

        consumer.consume = consume
        ing.run_loop()
        self.assertEqual(consumer.calls, 3)


# ------------------------------------------------------------------------------------------------ CLI / consumer factory
class TestConsumerFactoryAndCli(unittest.TestCase):
    def test_make_consumer_configures_group_topic_and_manual_commit(self):
        # inject: enable.auto.commit True, another default group or topic
        made = {}

        class Consumer:
            def __init__(self, conf):
                made["conf"] = conf

            def subscribe(self, topics):
                made["topics"] = topics

        fake = types.ModuleType("confluent_kafka")
        fake.Consumer = Consumer
        with mock.patch.dict(sys.modules, {"confluent_kafka": fake}):
            ks.make_consumer("localhost:19092")
        self.assertEqual(made["conf"], {"bootstrap.servers": "localhost:19092", "group.id": "stuck-analyser",
                                        "enable.auto.commit": False, "auto.offset.reset": "earliest"})
        self.assertEqual(made["topics"], ["fleet.state"])

    def test_missing_library_is_one_line_naming_the_requirements_file(self):
        # inject: import confluent_kafka at module level in kafka_source, or drop the pip hint
        import ingest as cli

        with mock.patch.dict(sys.modules, {"confluent_kafka": None}):
            with self.assertRaises(ks.SourceError) as cm:
                ks.make_consumer("x")
            self.assertIn("pip install -r fleet/requirements.txt", str(cm.exception))
            self.assertNotIn("\n", str(cm.exception))
            err = io.StringIO()
            with redirect_stderr(err):
                code = cli.main(["--source", "kafka", "--bootstrap", "localhost:19092", "--run", "x"])
            self.assertEqual(code, 2)
            self.assertEqual(len(err.getvalue().strip().splitlines()), 1)
            self.assertIn("pip install -r fleet/requirements.txt", err.getvalue())

    def test_cli_kafka_source_runs_to_idle_and_reports_coverage_line(self):
        # inject: do not pass --until-idle / --emit-ledger / --topic through to the ingester
        import ingest as cli

        msgs = messages()
        consumer = FakeConsumer([msgs], Clock())
        with tempfile.TemporaryDirectory() as d:
            doc = {"status": "complete", "config": {}, "zones": [], "total": {"expected_messages": len(msgs)}}
            (Path(d) / "emit_ledger.json").write_text(json.dumps(doc))
            out = io.StringIO()
            with mock.patch.object(ks, "make_consumer", return_value=consumer) as mk, redirect_stdout(out):
                code = cli.main(["--source", "kafka", "--bootstrap", "b:1", "--topic", "t.x", "--run", "k1",
                                 "--emit-ledger", str(Path(d) / "emit_ledger.json"), "--until-idle", "0",
                                 "--store", f"jsonl:{d}/store"])
            self.assertEqual(code, 0)
            mk.assert_called_once_with("b:1", "t.x", "stuck-analyser")
            self.assertIn("ingest k1:", out.getvalue())
            self.assertIn("coverage 1.0", out.getvalue())
            self.assertTrue(consumer.closed)
            self.assertEqual(consumer.commits, 1)

    def test_kafka_without_bootstrap_keeps_the_s5b1_stub_line(self):
        # inject: drop the early return for a missing --bootstrap
        import ingest as cli

        err = io.StringIO()
        with redirect_stderr(err), redirect_stdout(io.StringIO()):
            code = cli.main(["--source", "kafka"])
        self.assertEqual((code, err.getvalue().strip()), (2, "kafka source: S5B2"))


# ------------------------------------------------------------------------------------------------ KafkaSink accounting
class DeliveryProducer:
    """A fake producer that acknowledges at poll()/flush() like librdkafka: callbacks fire there, not in produce().
    fail: indexes (of accepted produce calls) whose delivery fails; buffer_full: produce attempts (1-based) that raise
    BufferError; flush_leaves: how many pending records flush() gives up on (callbacks never fire) and reports."""

    def __init__(self, fail=(), buffer_full=(), flush_leaves=0):
        self.fail, self.buffer_full, self.flush_leaves = set(fail), set(buffer_full), flush_leaves
        self.attempts = 0
        self.accepted = []  # (key, value) of accepted produces, in order
        self.pending = []  # (index, callback)
        self.polls = []
        self.flushes = 0

    def produce(self, topic, key=None, value=None, on_delivery=None):
        self.attempts += 1
        if self.attempts in self.buffer_full:
            raise BufferError("Local: Queue full")
        self.pending.append((len(self.accepted), on_delivery))
        self.accepted.append((key, value))

    def _deliver(self, items):
        for idx, cb in items:
            cb("boom" if idx in self.fail else None, None)

    def poll(self, timeout=0):
        self.polls.append(timeout)
        if timeout:
            items, self.pending = self.pending, []
            self._deliver(items)
        return 0

    def flush(self):
        self.flushes += 1
        keep = self.pending[len(self.pending) - self.flush_leaves:] if self.flush_leaves else []
        items = self.pending[:len(self.pending) - self.flush_leaves]
        self.pending = []
        self._deliver(items)
        return len(keep)


ROBOTS, STEPS = 2, 5


def emit_doc_for(sink, state="complete", robots=ROBOTS, steps=STEPS):
    """Write the sink's final stats through an EmitLedger exactly like run_fleet does, return the document."""
    led = el.EmitLedger(Path(tempfile.gettempdir()) / "unused-emit-ledger.json", {"seed_base": 0}, zones=1, steps=steps)
    led.update(0, dict(sink.stats(), robots=robots, agvs=1, pickers=1, steps_done=steps, first_timestamp="a",
                       last_timestamp="b"), state)
    return led.document("complete")


def produce_all(sink, n=ROBOTS * STEPS):
    for i in range(n):
        sink.write(f"Z0-{i % ROBOTS:02d}", f'{{"i":{i}}}\n'.encode(), "t", i)


class TestKafkaSinkDelivery(unittest.TestCase):
    def check_totals(self, doc, delivered, failed, complete):
        n = ROBOTS * STEPS
        z = doc["zones"][0]
        for entry in (z, doc["total"]):
            self.assertIs(type(entry["delivered"]), int)
            self.assertIs(type(entry["delivery_failed"]), int)
            self.assertEqual((entry["delivered"], entry["delivery_failed"]), (delivered, failed))
            self.assertEqual(entry["delivered"] + entry["delivery_failed"], entry["messages"])
            self.assertEqual(entry["messages"], n)
            self.assertIs(entry["complete"], complete)

    def test_all_delivered(self):
        # inject: count `delivered` at produce time instead of in the callback, or leave out the ledger fields
        p = DeliveryProducer()
        sink = sinks.KafkaSink(TOPIC, producer=p)
        produce_all(sink)
        sink.close()
        self.check_totals(emit_doc_for(sink), 10, 0, True)
        self.assertEqual(p.flushes, 1)

    def test_a_failed_delivery_callback_counts_as_failed_not_delivered_and_the_zone_is_incomplete(self):
        # inject: ignore err in _on_delivery (count it delivered), or leave `complete` independent of delivery_failed
        p = DeliveryProducer(fail={1, 6, 7})
        sink = sinks.KafkaSink(TOPIC, producer=p)
        produce_all(sink)
        sink.close()
        self.check_totals(emit_doc_for(sink), 7, 3, False)
        # the callback in isolation
        s2 = sinks.KafkaSink(TOPIC, producer=DeliveryProducer())
        s2._on_delivery("err", None)
        self.assertEqual((s2.delivered, s2.delivery_failed), (0, 1))
        s2._on_delivery(None, object())
        self.assertEqual((s2.delivered, s2.delivery_failed), (1, 1))

    def test_buffer_error_is_polled_and_retried_without_changing_the_produced_count(self):
        # inject: count messages before the produce succeeds, drop the retry, or poll(0) instead of poll(0.5)
        p = DeliveryProducer(buffer_full={1, 2, 5})  # attempts 1, 2 (the first message twice) and 5 are refused
        sink = sinks.KafkaSink(TOPIC, producer=p)
        produce_all(sink)
        sink.close()
        self.assertEqual(sink.messages, 10)
        self.assertEqual(p.attempts, 13)
        self.assertEqual(len(p.accepted), 10)
        self.assertEqual(len({v for _, v in p.accepted}), 10)  # every message accepted exactly once
        self.assertEqual(p.polls.count(0.5), 3)
        self.assertEqual(sink.stats()["messages"], 10)
        self.check_totals(emit_doc_for(sink), 10, 0, True)

    def test_flush_remainder_is_delivery_failed_and_the_zone_is_not_complete(self):
        # inject: ignore the return value of flush(), or add it to delivered
        p = DeliveryProducer(flush_leaves=4)
        sink = sinks.KafkaSink(TOPIC, producer=p)
        produce_all(sink)
        self.assertEqual((sink.delivered, sink.delivery_failed), (0, 0))  # nothing acknowledged before close
        sink.close()
        self.check_totals(emit_doc_for(sink), 6, 4, False)
        sink.close()  # idempotent: no second flush, no double count
        self.assertEqual((p.flushes, sink.delivery_failed), (1, 4))

    def test_failed_callbacks_and_flush_remainder_add_up(self):
        # inject: count the flush remainder over the records whose callback already failed
        p = DeliveryProducer(fail={0}, flush_leaves=2)
        sink = sinks.KafkaSink(TOPIC, producer=p)
        produce_all(sink)
        sink.close()
        self.check_totals(emit_doc_for(sink), 7, 3, False)

    def test_file_sink_zones_carry_null_and_are_otherwise_unchanged(self):
        # inject: report 0 instead of None for file zones, or add the fields to the file sink's complete rule
        with tempfile.TemporaryDirectory() as d:
            fs = sinks.FileSink(d, 0)
            produce_all(fs)
            fs.close()
            doc = emit_doc_for(fs)
        z = doc["zones"][0]
        self.assertIsNone(z["delivered"])
        self.assertIsNone(z["delivery_failed"])
        self.assertIsNone(doc["total"]["delivered"])
        self.assertIsNone(doc["total"]["delivery_failed"])
        self.assertIs(z["complete"], True)
        self.assertIs(doc["total"]["complete"], True)
        self.assertIsNotNone(z["bytes_compressed"])

    def test_missing_snapshot_fields_leave_the_ledger_fields_null(self):
        # inject: default delivered to 0 in the blank zone
        led = el.EmitLedger(Path(tempfile.gettempdir()) / "unused-emit-ledger.json", {"seed_base": 0}, zones=1, steps=5)
        doc = led.document("running")
        self.assertIsNone(doc["zones"][0]["delivered"])
        self.assertIsNone(doc["total"]["delivery_failed"])

    def test_end_to_end_run_zone_into_a_kafka_sink_reports_delivery_in_the_ledger_document(self):
        # inject: build the zone snapshot without sink.stats() delivered / delivery_failed
        from fleet_analyser import emitter as em
        from warehouse_rl.disturb import resolve_disturb

        cfg = dict(zone=0, seed=1, steps=30, env_id=em.DEFAULT_ENV, policy="stuck_aware_cta",
                   disturb=resolve_disturb("breakdown-heavy")[1], recovery={"name": "timeout", "call_human_cost": 60},
                   t0=em.DEFAULT_T0)
        p = DeliveryProducer(fail={3})
        sink = sinks.KafkaSink(TOPIC, producer=p)
        snaps = []
        result = em.run_zone(cfg, sink, report=snaps.append)
        led = el.EmitLedger(Path(tempfile.gettempdir()) / "unused-emit-ledger.json", {"seed_base": 0}, zones=1,
                            steps=30)
        led.update(0, result["snapshot"], "complete")
        doc = led.document("complete")
        z = doc["zones"][0]
        self.assertEqual(z["messages"], 12 * 30)
        self.assertEqual((z["delivered"], z["delivery_failed"]), (12 * 30 - 1, 1))
        self.assertIs(z["complete"], False)
        self.assertIs(doc["total"]["complete"], False)
        self.assertEqual(doc["total"]["delivered"] + doc["total"]["delivery_failed"], doc["total"]["messages"])
        self.assertEqual(snaps[-1]["delivery_failed"], 1)


if __name__ == "__main__":
    unittest.main()

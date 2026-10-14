-- S5B ingest schema for ClickHouse. One statement per `;`, one column per line (ClickHouseStore.ensure_schema and the
-- unit-test fake both read it that way). Applied by ClickHouseStore.ensure_schema into the database named in the
-- --store URL (the database itself is created by the applier, not here).
--
-- Conventions
--   schema_version : DDL version of the table layout (a column DEFAULT; unrelated to the VDA 5050 message field of the
--                    same name). ClickHouseStore.select() never returns it.
--   _ver           : writer-side strictly increasing UInt64 (ns clock, bumped on ties). It is the ReplacingMergeTree
--                    version of the upsert tables, so the later upsert always wins, and the read order of the others.
--   Upsert tables  : ReplacingMergeTree(_ver) ORDER BY exactly the key columns S5B1 passes to store.upsert; always read
--                    with FINAL. `_first` is the `_ver` of the key's first write, carried by every later version of the
--                    key, so reads (ORDER BY _first) return rows in first-write order, like MemoryStore.
--   decisions      : insert-only (first write wins, enforced by record_decision's dedup_key check). A grading stamp goes
--                    to decision_grades, once per decision id; ClickHouseStore.select('decisions') merges the two.
--   JSON cells     : lists / dicts / grade values are stored as JSON text (String) and parsed back on read.

CREATE TABLE IF NOT EXISTS transitions
(
    run String,
    zone String,
    robot String,
    ts Int64,
    from_state String,
    to_state String,
    cell String,
    order_id String,
    schema_version UInt8 DEFAULT 1,
    _ver UInt64
)
ENGINE = MergeTree
ORDER BY (run, zone, robot, ts);

CREATE TABLE IF NOT EXISTS rejects
(
    run String,
    source String,
    file String,
    `offset` Int64,
    reason String,
    raw String,
    schema_version UInt8 DEFAULT 1,
    _ver UInt64
)
ENGINE = MergeTree
ORDER BY (run, source, file, `offset`);

CREATE TABLE IF NOT EXISTS state_sample
(
    run String,
    zone String,
    serial String,
    header_id Int64,
    ts Int64,
    raw String,
    schema_version UInt8 DEFAULT 1,
    _ver UInt64
)
ENGINE = MergeTree
ORDER BY (run, zone, serial, ts)
TTL toDateTime(ts) + INTERVAL 7 DAY;

CREATE TABLE IF NOT EXISTS evidence
(
    decision_id String,
    run String,
    zone String,
    lines String,
    line_count Int64,
    bytes Int64,
    schema_version UInt8 DEFAULT 1,
    _ver UInt64
)
ENGINE = MergeTree
ORDER BY (run, zone, decision_id);

CREATE TABLE IF NOT EXISTS decisions
(
    id String,
    run String,
    decided_at Float64,
    recorded_at Float64,
    kind String,
    subject String,
    claim String,
    claim_version Int64,
    rationale String,
    expected Nullable(Float64),
    grade_after Float64,
    status String,
    outcome Nullable(String),
    graded_at Nullable(Float64),
    error Nullable(String),
    verdict Nullable(String),
    dedup_key String,
    schema_version UInt8 DEFAULT 1,
    _ver UInt64
)
ENGINE = MergeTree
ORDER BY dedup_key;

CREATE TABLE IF NOT EXISTS decision_grades
(
    id String,
    status String,
    outcome Nullable(String),
    error Nullable(String),
    verdict Nullable(String),
    graded_at Nullable(Float64),
    schema_version UInt8 DEFAULT 1,
    _ver UInt64,
    _first UInt64
)
ENGINE = ReplacingMergeTree(_ver)
ORDER BY id;

CREATE TABLE IF NOT EXISTS stuck_episodes
(
    run String,
    episode_id String,
    zone String,
    robot String,
    order_id String,
    `start` Float64,
    start_iso String,
    t_entry Float64,
    cell String,
    cause Nullable(String),
    blocker Nullable(String),
    blocker_faulted_s Nullable(Float64),
    `end` Nullable(Float64),
    duration_s Nullable(Float64),
    resolution String,
    avoidable Bool,
    avoidable_s Nullable(Float64),
    left_censored Bool,
    schema_version UInt8 DEFAULT 1,
    _ver UInt64,
    _first UInt64
)
ENGINE = ReplacingMergeTree(_ver)
ORDER BY (run, episode_id);

CREATE TABLE IF NOT EXISTS ingest_checkpoints
(
    run String,
    path String,
    offset_uncompressed Int64,
    last_header_ids String,
    ledger_counters Nullable(String),
    cp_seq Int64,
    updated_at Float64,
    last_message_ts_by_zone Nullable(String),
    schema_version UInt8 DEFAULT 1,
    _ver UInt64,
    _first UInt64
)
ENGINE = ReplacingMergeTree(_ver)
ORDER BY (run, path);

-- JSON {zone: event-time ts of the last accepted message of that zone}: the per-zone "observed up to" mark the forecast
-- grader reads. ensure_schema runs every statement, so a stack created before this column gets it here.
ALTER TABLE ingest_checkpoints ADD COLUMN IF NOT EXISTS last_message_ts_by_zone Nullable(String) AFTER updated_at;

CREATE TABLE IF NOT EXISTS ingest_files
(
    run String,
    path String,
    size_bytes Int64,
    bytes_done_uncompressed Int64,
    bytes_done_compressed Int64,
    status String,
    sha256 Nullable(String),
    first_header_ids String,
    last_header_ids String,
    in_emit_ledger Bool,
    updated_at Float64,
    schema_version UInt8 DEFAULT 1,
    _ver UInt64,
    _first UInt64
)
ENGINE = ReplacingMergeTree(_ver)
ORDER BY (run, path);

CREATE TABLE IF NOT EXISTS ingest_ledger
(
    run String,
    source String,
    minute Int64,
    bytes_read_compressed Int64,
    bytes_read_uncompressed Int64,
    messages_parsed Int64,
    messages_rejected Int64,
    duplicates Int64,
    sequence_gaps Int64,
    missing_messages Int64,
    messages_accepted Int64,
    lag_p50_s Nullable(Float64),
    lag_p99_s Nullable(Float64),
    behind_emitter_s Nullable(Float64),
    msgs_per_s Float64,
    mb_per_s Float64,
    bytes_kept Int64,
    bytes_dropped Int64,
    backlog_bytes Nullable(Int64),
    written_at Float64,
    schema_version UInt8 DEFAULT 1,
    _ver UInt64,
    _first UInt64
)
ENGINE = ReplacingMergeTree(_ver)
ORDER BY (run, source, minute);

CREATE TABLE IF NOT EXISTS ingest_runs
(
    run String,
    glob String,
    emit_ledger Nullable(String),
    emit_status Nullable(String),
    emit_config Nullable(String),
    expected_messages Nullable(Int64),
    updated_at Float64,
    schema_version UInt8 DEFAULT 1,
    _ver UInt64,
    _first UInt64
)
ENGINE = ReplacingMergeTree(_ver)
ORDER BY run;

-- Written only by the kafka source: consumer lag in messages (sum over partitions of high watermark - position).
CREATE TABLE IF NOT EXISTS ingest_consumer_lag
(
    run String,
    topic String,
    lag_messages Int64,
    partitions Int64,
    updated_at Float64,
    schema_version UInt8 DEFAULT 1,
    _ver UInt64,
    _first UInt64
)
ENGINE = ReplacingMergeTree(_ver)
ORDER BY (run, topic);

-- Written by fleet_analyser.bench.load_results from benchmark.json and score.json: one row per numeric leaf, `key` is the
-- dotted path. Insert-only (a reload appends; readers take argMax(value, loaded_at) per (kind, run, key)).
CREATE TABLE IF NOT EXISTS results
(
    kind String,
    run String,
    `key` String,
    value Float64,
    `text` Nullable(String),
    loaded_at Float64,
    schema_version UInt8 DEFAULT 1,
    _ver UInt64
)
ENGINE = MergeTree
ORDER BY (kind, run, `key`);

-- S8B hotspot tables (written by fleet/costmap.py and fleet/grade.py, never by ingest).
-- One row per stall: a maximal run of consecutive messages of one robot that kept its cell, heading and order.
CREATE TABLE IF NOT EXISTS stalls
(
    run String,
    zone String,
    robot String,
    cell String,
    attribution String,
    `start` Int64,
    `end` Int64,
    n_msgs Int64,
    seconds Int64,
    next_occupied Bool,
    in_episode Nullable(String),
    faulted_episode Bool,
    schema_version UInt8 DEFAULT 1,
    _ver UInt64,
    _first UInt64
)
ENGINE = ReplacingMergeTree(_ver)
ORDER BY (run, zone, robot, start);

-- One row per zone + cell + publish (nonzero cells only); published_at is the publish's event time in epoch seconds.
CREATE TABLE IF NOT EXISTS costmap
(
    run String,
    zone String,
    published_at Int64,
    cell String,
    cost Float64,
    score Float64,
    stalls Int64,
    schema_version UInt8 DEFAULT 1,
    _ver UInt64,
    _first UInt64
)
ENGINE = ReplacingMergeTree(_ver)
ORDER BY (run, published_at, zone, cell);

-- Grades of hotspot_forecast decisions, one row per (decision id, grade_source): "outcome" (later stream, also stamped on
-- the decision) and "truth" (against the emitter's floor ground truth, never touches the decision).
CREATE TABLE IF NOT EXISTS forecast_grades
(
    id String,
    run String,
    grade_source String,
    outcome Nullable(Float64),
    expected Nullable(Float64),
    error Nullable(Float64),
    verdict String,
    horizon_s Nullable(Float64),
    graded_at Nullable(Float64),
    window_end Nullable(Float64),
    schema_version UInt8 DEFAULT 1,
    _ver UInt64,
    _first UInt64
)
ENGINE = ReplacingMergeTree(_ver)
ORDER BY (id, grade_source);

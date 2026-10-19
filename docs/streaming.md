# Phase 4: streaming

```
data/replay/events.jsonl ──> replay producer ──> Kafka: supplychain.events (3 partitions)
 (real GDACS events,           (Python, in time order,            │
  oldest first)                 sped up, idempotent)              ▼
                                                     Spark Structured Streaming (stream_events.py)
                                                       ├─ invalid ──────────> Kafka: supplychain.events.dlq
                                                       ├─ enrich with gold: ports, nearest port, downstream dependents
                                                       ├─ alerts ───────────> Kafka: supplychain.alerts
                                                       ├─ events + alerts ──> PostgreSQL (idempotent insert)
                                                       └─ daily counts with a watermark ──> console
                                                     checkpoints on HDFS: /lake/checkpoints
```

## Run it

```bash
python scripts/spark_run.py export_replay            # once: real events -> data/replay/events.jsonl
python scripts/kafka_topics.py --reset               # clean slate (topics, checkpoints, events/alerts tables)
python scripts/spark_run.py stream_events            # terminal 1, runs until Ctrl-C
python -m ingestion.replay_producer --from 2019-09-01 --to 2019-10-31 --speed 86400 --bad 3   # terminal 2
```

Watch: Kafka UI http://localhost:8080 (topics, messages), Spark job UI http://localhost:4040 (Structured Streaming tab).

## Why not random data

The producer sends real GDACS events from 2019-2023, oldest first, keeping the real gaps between them
(sped up: `--speed 86400` = one day of history per second). A replay is reproducible - the same input
gives the same alerts every time - and every alert can be checked against what actually happened.

## Alert rule

An event becomes an alert if any of these hold:

| Rule | Why |
|---|---|
| GDACS alert level Orange or Red | GDACS's own impact estimate |
| Tropical cyclone over a country with one of our 45 major ports | cyclones are large; country-level exposure is enough |
| Flood within 300 km of a major port | floods are local; distance matters |

Severity: HIGH = Red, or Orange in a country with a major port · MEDIUM = other Orange, or cyclone on a
port country · LOW = the rest (floods near ports).

**Why not just trust GDACS:** GDACS rated Typhoon Hagibis (Oct 2019) **Green**. Our own weather data
measured 162 km/h gusts at Tokyo port on 12 Oct 2019, and Hagibis was one of the most damaging typhoons
to hit Japan. The port rule raised it as MEDIUM. One source alone would have missed it.

Each alert carries its context from the gold layer, e.g. for Typhoon Lingling (Red, CHN/JPN):
*"major ports there: Shanghai, Ningbo, ... | downstream: IND gets 58% of its electronics from CHN"*.

## Concepts

**Dead-letter queue.** Messages that fail validation (not JSON, missing time, impossible coordinates,
unknown type) go to `supplychain.events.dlq` with the reason, instead of crashing the job or vanishing.

**Checkpointing.** After every micro-batch Spark records on HDFS which Kafka offsets it has finished.
A restarted job continues from exactly there.

**Idempotent sink.** Events and alerts are written to staging tables, then copied into Postgres with
`ON CONFLICT DO NOTHING` / `NOT EXISTS`. A batch that is re-run after a crash adds nothing twice.
(The Kafka alert topic is at-least-once: a crash in the middle of a batch can resend that batch's alerts.
Consumers de-duplicate by `event_key`.)

**Watermark.** The daily-count query accepts events up to 2 days late (in event time). Once the
watermark passes a day, that day's count is final and printed, and later stragglers are dropped.

**Back-pressure.** `maxOffsetsPerTrigger = 2000` caps each micro-batch, so a backlog is worked off in
steady pieces instead of one huge batch.

## Results (2026-10-19)

| Test | Result |
|---|---|
| Replay Sep-Oct 2019 + 3 broken messages | 869 events processed, 3 rejected to the DLQ with reasons, 55 alerts |
| Unplanned crash (a bug in batch 1), fixed and restarted | resumed from the checkpoint: 869 of 869 events, none twice |
| Planned crash: driver killed (`kill -9`) mid-November | count froze at 943 while the producer kept sending |
| Restart | caught up to **1,297 = 869 + 428, all distinct**; Kafka alerts 73 = Postgres alerts 73 |

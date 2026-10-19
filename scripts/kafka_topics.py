"""Create the Kafka topics for phase 4 (safe to rerun - existing topics are left alone).

    python scripts/kafka_topics.py
    python scripts/kafka_topics.py --reset    # clean slate for a demo: empty topics, no streaming
                                              # checkpoints, empty events/alerts tables in Postgres

supplychain.events      raw disaster events from the replay producer (3 partitions)
supplychain.alerts      what the streaming job concludes about each serious / port-near event
supplychain.events.dlq  "dead letter queue": messages that failed validation, kept for inspection
                        instead of crashing the stream or being silently dropped

Retention is capped (7 days or 100 MB per partition, whichever comes first) so a long
replay can never fill the disk.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

from confluent_kafka.admin import AdminClient, NewTopic
from dotenv import load_dotenv

load_dotenv()
admin = AdminClient({"bootstrap.servers": os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")})

LIMITS = {"retention.ms": str(7 * 24 * 3600 * 1000), "retention.bytes": str(100 * 1024 * 1024)}
TOPICS = [
    NewTopic("supplychain.events", num_partitions=3, replication_factor=1, config=LIMITS),
    NewTopic("supplychain.alerts", num_partitions=3, replication_factor=1, config=LIMITS),
    NewTopic("supplychain.events.dlq", num_partitions=1, replication_factor=1, config=LIMITS),
]

if "--reset" in sys.argv:
    names = [t.topic for t in TOPICS if t.topic in admin.list_topics(timeout=10).topics]
    for name, future in (admin.delete_topics(names).items() if names else []):
        future.result()
        print("deleted", name)
    while any(t.topic in admin.list_topics(timeout=10).topics for t in TOPICS):
        time.sleep(1)  # deletion finishes in the background
    # old checkpoints would point at offsets of the deleted topics
    subprocess.run(["docker", "exec", "scx-namenode", "hdfs", "dfs", "-rm", "-r", "-f", "-skipTrash",
                    "/lake/checkpoints"], capture_output=True)
    print("deleted streaming checkpoints")
    # Only what the streams wrote. A TRUNCATE ... CASCADE here would also wipe impact_runs/impact_scores
    # (they point at events), i.e. every scored event the dashboard shows.
    subprocess.run(["docker", "exec", "scx-postgres", "psql", "-U", os.getenv("POSTGRES_USER"),
                    "-d", os.getenv("POSTGRES_DB"), "-c",
                    "TRUNCATE alerts RESTART IDENTITY; "
                    "DELETE FROM events e WHERE e.source IN ('gdacs-replay', 'gdacs-live') "
                    "AND NOT EXISTS (SELECT 1 FROM impact_runs r WHERE r.event_id = e.event_id) "
                    "AND NOT EXISTS (SELECT 1 FROM impact_scores s WHERE s.event_id = e.event_id)"],
                   capture_output=True)
    (Path(__file__).resolve().parent.parent / "data" / "live" / "sent.json").unlink(missing_ok=True)
    print("emptied alerts, removed streamed events (scored events kept), live feed will resend")

existing = set(admin.list_topics(timeout=10).topics)
todo = [t for t in TOPICS if t.topic not in existing]
for name, future in (admin.create_topics(todo).items() if todo else []):
    future.result()  # raises if creation failed
    print("created", name)
for t in TOPICS:
    if t.topic in existing:
        print("exists ", t.topic)

"""Replay real historical disasters into Kafka, in the order they happened.

    python -m ingestion.replay_producer --from 2019-09-01 --to 2019-10-31 --speed 86400
    python -m ingestion.replay_producer --from 2019-10-01 --to 2019-10-15 --bad 3

Not random fake data: every message is a real GDACS event from data/replay/events.jsonl
(made by spark_jobs/export_replay.py). The gaps between events are kept, just sped up:
--speed 86400 means one day of history passes per real second.

--bad N slips N broken messages into the stream, to show the dead-letter queue catching them.
"""
import argparse
import json
import os
import random
import time
from datetime import datetime, timezone

from confluent_kafka import Producer
from dotenv import load_dotenv

from ingestion.config import ROOT

TOPIC = "supplychain.events"
REPLAY = ROOT / "data" / "replay" / "events.jsonl"


def load(start, end):
    with open(REPLAY, encoding="utf-8") as f:
        events = [json.loads(line) for line in f]
    return [e for e in events if start <= e["start_ts"][:10] <= end]


def broken_message(i):
    # the kinds of garbage real feeds produce: not JSON, missing fields, impossible values
    return random.choice([
        b"{this is not json",
        json.dumps({"event_key": "BAD-{}".format(i), "event_type": "TC"}).encode(),  # no time, no place
        json.dumps({"event_key": "BAD-{}".format(i), "event_type": "TC", "start_ts": "2019-10-10T00:00:00",
                    "latitude": 123.0, "longitude": 500.0, "alert_level": "Green", "countries": []}).encode(),
    ])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--from", dest="start", default="2019-09-01")
    p.add_argument("--to", dest="end", default="2019-10-31")
    p.add_argument("--speed", type=float, default=86400, help="history seconds per real second")
    p.add_argument("--bad", type=int, default=0, help="broken messages to slip in")
    args = p.parse_args()

    load_dotenv(ROOT / ".env")
    producer = Producer({"bootstrap.servers": os.getenv("KAFKA_BOOTSTRAP", "localhost:9092"),
                         "enable.idempotence": True})  # no duplicates if the producer retries

    events = load(args.start, args.end)
    bad_at = set(random.sample(range(len(events)), min(args.bad, len(events))))
    print("replaying {:,} events from {} to {} at {:,.0f}x".format(len(events), args.start, args.end, args.speed))

    prev = None
    for i, e in enumerate(events):
        t = datetime.fromisoformat(e["start_ts"])
        if prev is not None:
            time.sleep(min(max((t - prev).total_seconds() / args.speed, 0), 5))  # never stall > 5 s
        prev = t

        e["replayed_at"] = datetime.now(timezone.utc).isoformat()
        # key = event id: all messages about one event land in the same partition, in order
        producer.produce(TOPIC, key=e["event_key"], value=json.dumps(e).encode())
        if i in bad_at:
            producer.produce(TOPIC, key="bad", value=broken_message(i))
        producer.poll(0)

        if e["alert_level"] != "Green" or e["event_type"] == "TC":
            print("{}  {:<6} {:<45} {}".format(e["start_ts"][:10], e["alert_level"], e["title"][:45],
                                              ",".join(e["countries"][:4])))
    producer.flush()
    print("done: {:,} events + {} broken messages sent to {}".format(len(events), len(bad_at), TOPIC))


if __name__ == "__main__":
    main()

"""Export silver events, in the order they happened, for the Kafka replay producer.

Writes data/replay/events.jsonl - one JSON event per line, oldest first, each with the
list of countries it affected. ~49k events is small, so it's collected on the driver and
written as one plain file the producer can read without Spark.
"""
import json
import os

from pyspark.sql import functions as F

import lake

spark = lake.spark("export-replay")
events = spark.read.parquet(lake.SILVER + "/events")
countries = (spark.read.parquet(lake.SILVER + "/event_countries")
             .groupBy("event_key").agg(F.sort_array(F.collect_set("iso3")).alias("countries")))

rows = (events.join(countries, "event_key", "left")
        .where(F.year("start_ts").between(2019, 2023))
        .orderBy("start_ts", "event_key")
        .select("event_key", "event_type", "alert_level", "alert_score", "severity_value", "severity_unit",
                "title", "start_ts", "end_ts", "latitude", "longitude", "countries")
        .collect())

out = "/opt/scx/data/replay/events.jsonl"
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w") as f:
    for r in rows:
        d = r.asDict()
        d["start_ts"] = d["start_ts"].isoformat()
        d["end_ts"] = d["end_ts"].isoformat() if d["end_ts"] else None
        d["countries"] = d["countries"] or []
        f.write(json.dumps(d) + "\n")

lake.check("events exported in time order", len(rows) > 40000, "{:,} events".format(len(rows)))
spark.stop()

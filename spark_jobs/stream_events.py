"""Phase 4: Spark Structured Streaming over the live disaster feed.

Kafka supplychain.events
   -> validate      broken messages go to supplychain.events.dlq with the reason
   -> enrich        major ports in the affected countries, nearest major port (km),
                    who depends on the affected countries' exports (gold/dependencies, 2023)
   -> decide        alert if GDACS says Orange/Red, OR a cyclone hits a country with a major port,
                    OR a flood is within 300 km of one. (GDACS rated Typhoon Hagibis "Green" -
                    one source alone is not enough.)
   -> write         alerts to Kafka supplychain.alerts; events + alerts into Postgres

Second query: events per day and type in event time, with a watermark (late data handling).

Checkpoints live on HDFS: kill this job at any point and restart it, and it carries on from the
exact Kafka offsets it had finished - nothing lost, nothing counted twice.
"""
import os

from pyspark.sql import functions as F, Window

import lake

KAFKA = "kafka:19092"
CHECKPOINTS = "/lake/checkpoints"
spark = lake.spark("stream-events")
spark.conf.set("spark.sql.shuffle.partitions", "4")  # tiny micro-batches - 200 would be pure overhead (E1)

PG_URL = "jdbc:postgresql://postgres:5432/" + os.environ["POSTGRES_DB"]
PG = {"user": os.environ["POSTGRES_USER"], "password": os.environ["POSTGRES_PASSWORD"],
      "driver": "org.postgresql.Driver"}

SCHEMA = ("event_key STRING, event_type STRING, alert_level STRING, alert_score DOUBLE, "
          "severity_value DOUBLE, severity_unit STRING, title STRING, start_ts STRING, end_ts STRING, "
          "latitude DOUBLE, longitude DOUBLE, countries ARRAY<STRING>, replayed_at STRING, feed STRING")
TYPES = ["EQ", "TC", "FL", "VO", "DR", "WF"]

# ---------- static lookups, loaded once (stream-static joins) ----------
ports = (spark.read.parquet(lake.SILVER + "/ports").where("is_major")
         .select(F.col("port_name"), F.col("iso3").alias("port_iso3"),
                 F.col("latitude").alias("port_lat"), F.col("longitude").alias("port_lon"))).cache()
dependents = (spark.read.parquet(lake.GOLD + "/dependencies").where("year = 2023 AND trade_share >= 0.15")
              .select(F.col("supplier_iso3").alias("iso3"), "importer_iso3", "hs2", "trade_share")).cache()
hs_names = spark.createDataFrame([(k, v[0]) for k, v in lake.HS_CHAPTERS.items()], ["hs2", "product"])
dependents = dependents.join(F.broadcast(hs_names), "hs2").cache()

# ---------- the stream ----------
raw = (spark.readStream.format("kafka")
       .option("kafka.bootstrap.servers", KAFKA)
       .option("subscribe", "supplychain.events")
       .option("startingOffsets", "earliest")
       .option("maxOffsetsPerTrigger", 2000)       # back-pressure: at most 2,000 messages per batch
       .load())

msgs = raw.select(F.col("key").cast("string").alias("kafka_key"),
                  F.col("value").cast("string").alias("json"))
parsed = (msgs.withColumn("e", F.from_json("json", SCHEMA))
          .select("kafka_key", "json", "e.*")
          .withColumn("event_time", F.to_timestamp("start_ts")))

reason = (F.when(F.col("event_key").isNull(), "not valid JSON or no event_key")
          .when(~F.col("event_type").isin(TYPES), "unknown event_type")
          .when(F.col("event_time").isNull(), "missing or bad start_ts")
          .when(~F.col("latitude").between(-90, 90) | ~F.col("longitude").between(-180, 180),
                "coordinates out of range"))
checked = parsed.withColumn("reject_reason", reason)
valid = checked.where("reject_reason IS NULL")


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = (F.col(c) for c in (lat1, lon1, lat2, lon2))  # names -> columns
    dlat, dlon = F.radians(lat2 - lat1), F.radians(lon2 - lon1)
    a = F.sin(dlat / 2) ** 2 + F.cos(F.radians(lat1)) * F.cos(F.radians(lat2)) * F.sin(dlon / 2) ** 2
    return 2 * 6371 * F.asin(F.sqrt(a))


def pg_sql(statement):
    jvm = spark.sparkContext._jvm
    loader = jvm.java.lang.Thread.currentThread().getContextClassLoader()
    props = jvm.java.util.Properties()
    props.setProperty("user", PG["user"])
    props.setProperty("password", PG["password"])
    conn = loader.loadClass("org.postgresql.Driver").newInstance().connect(PG_URL, props)
    try:
        conn.createStatement().execute(statement)
    finally:
        conn.close()


def process_batch(batch, batch_id):
    batch = batch.persist()

    # 1. rejects -> dead-letter topic, with the reason attached
    bad = batch.where("reject_reason IS NOT NULL")
    n_bad = bad.count()
    if n_bad:
        (bad.select(F.coalesce("kafka_key", F.lit("unknown")).alias("key"),
                    F.to_json(F.struct(F.col("json").alias("original"), "reject_reason",
                                       F.lit(batch_id).alias("batch_id"))).alias("value"))
            .write.format("kafka").option("kafka.bootstrap.servers", KAFKA)
            .option("topic", "supplychain.events.dlq").save())

    good = batch.where("reject_reason IS NULL").dropDuplicates(["event_key"]).persist()
    n_good = good.count()
    if n_good == 0:
        print("batch {}: 0 events, {} rejected".format(batch_id, n_bad))
        batch.unpersist()
        return

    # 2. enrich
    affected = good.select("event_key", F.explode("countries").alias("iso3"))
    port_names = (affected.join(F.broadcast(ports), F.col("iso3") == F.col("port_iso3"))
                  .groupBy("event_key").agg(F.sort_array(F.collect_set("port_name")).alias("ports_in_country")))
    nearest = (good.select("event_key", "latitude", "longitude").crossJoin(F.broadcast(ports))
               .withColumn("km", haversine_km("latitude", "longitude", "port_lat", "port_lon"))
               .withColumn("r", F.row_number().over(Window.partitionBy("event_key").orderBy("km")))
               .where("r = 1").select("event_key", F.col("port_name").alias("nearest_port"),
                                      F.round("km").cast("int").alias("nearest_port_km")))
    downstream = (affected.join(F.broadcast(dependents), "iso3")
                  .withColumn("r", F.row_number().over(Window.partitionBy("event_key").orderBy(F.desc("trade_share"))))
                  .where("r <= 3")
                  .groupBy("event_key").agg(F.collect_list(F.format_string(
                      "%s gets %.0f%% of its %s from %s", "importer_iso3", F.col("trade_share") * 100,
                      F.lower("product"), "iso3")).alias("downstream")))

    e = (good.join(port_names, "event_key", "left").join(nearest, "event_key", "left")
         .join(downstream, "event_key", "left")
         .withColumn("ports_in_country", F.coalesce("ports_in_country", F.array().cast("array<string>")))
         .withColumn("downstream", F.coalesce("downstream", F.array().cast("array<string>"))))

    # 3. decide
    serious = F.col("alert_level").isin("Orange", "Red")
    cyclone_on_port_country = (F.col("event_type") == "TC") & (F.size("ports_in_country") > 0)
    flood_near_port = (F.col("event_type") == "FL") & (F.col("nearest_port_km") <= 300)
    e = (e.withColumn("alert", serious | cyclone_on_port_country | flood_near_port)
          .withColumn("why", F.concat_ws("; ",
              F.when(serious, F.concat(F.lit("GDACS "), F.col("alert_level"))),
              F.when(cyclone_on_port_country, F.lit("cyclone over a country with major ports")),
              F.when(flood_near_port, F.lit("flood near a major port"))))
          .withColumn("severity", F.when((F.col("alert_level") == "Red") |
                                         ((F.col("alert_level") == "Orange") & (F.size("ports_in_country") > 0)), "HIGH")
                                   .when(serious | cyclone_on_port_country, "MEDIUM").otherwise("LOW"))
          .withColumn("message", F.concat_ws(" | ",
              F.concat(F.col("title"), F.lit(" ("), F.col("alert_level"), F.lit(")")),
              F.concat(F.lit("why: "), F.col("why")),
              F.concat(F.lit("countries: "), F.concat_ws(",", "countries")),
              F.when(F.size("ports_in_country") > 0,
                     F.concat(F.lit("major ports there: "), F.concat_ws(", ", "ports_in_country"))),
              F.concat(F.lit("nearest major port: "), F.col("nearest_port"), F.lit(" ("),
                       F.col("nearest_port_km").cast("string"), F.lit(" km)")),
              F.when(F.size("downstream") > 0, F.concat(F.lit("downstream: "), F.concat_ws("; ", "downstream")))))
          .persist())
    alerts = e.where("alert")

    # 4. write: alerts -> Kafka
    (alerts.select(F.col("event_key").alias("key"),
                   F.to_json(F.struct("event_key", "event_type", "alert_level", "severity", "start_ts",
                                      "countries", "ports_in_country", "nearest_port", "nearest_port_km",
                                      "downstream", "message")).alias("value"))
        .write.format("kafka").option("kafka.bootstrap.servers", KAFKA)
        .option("topic", "supplychain.alerts").save())

    # events + alerts -> Postgres. Written to staging tables first, then copied with
    # ON CONFLICT / NOT EXISTS, so a batch that gets re-run after a crash adds no duplicates.
    (e.select(F.col("event_key").alias("event_id"), F.col("event_time").alias("ts"), "event_type",
              F.element_at("countries", 1).alias("iso3"), "latitude", "longitude",
              F.when(F.col("alert_level") == "Red", 1.0).when(F.col("alert_level") == "Orange", 0.6)
               .otherwise(0.2).cast("float").alias("severity"),
              F.coalesce("feed", F.lit("gdacs-replay")).alias("source"))  # live messages say gdacs-live
        .write.jdbc(PG_URL, "events_stage", mode="overwrite", properties=dict(PG, truncate="true")))
    (alerts.select(F.col("event_key").alias("event_id"), "severity", "message")
        .write.jdbc(PG_URL, "alerts_stage", mode="overwrite", properties=dict(PG, truncate="true")))
    pg_sql("""INSERT INTO events (event_id, ts, event_type, country_id, latitude, longitude, severity, source)
              SELECT s.event_id, s.ts, s.event_type, c.country_id, s.latitude, s.longitude, s.severity, s.source
              FROM events_stage s LEFT JOIN countries c ON c.iso3 = s.iso3
              ON CONFLICT (event_id) DO NOTHING""")
    # one alert per event and severity: a live cyclone upgraded from MEDIUM to HIGH raises a new alert,
    # but a re-run batch or a resent message with nothing new adds nothing
    pg_sql("""INSERT INTO alerts (event_id, severity, message)
              SELECT s.event_id, s.severity, s.message FROM alerts_stage s
              WHERE NOT EXISTS (SELECT 1 FROM alerts a WHERE a.event_id = s.event_id AND a.severity = s.severity)""")

    by_level = {r["severity"]: r["count"] for r in alerts.groupBy("severity").count().collect()}
    print("batch {}: {} events, {} rejected -> DLQ, {} alerts {}".format(
        batch_id, n_good, n_bad, sum(by_level.values()), by_level or ""), flush=True)
    for r in alerts.where("severity != 'LOW'").select("severity", "message").collect():
        print("   ALERT [{}] {}".format(r["severity"], r["message"]), flush=True)

    e.unpersist()
    good.unpersist()
    batch.unpersist()


alerts_query = (checked.writeStream.foreachBatch(process_batch)
                .option("checkpointLocation", CHECKPOINTS + "/stream_events")
                .trigger(processingTime="5 seconds")
                .queryName("alerts").start())

# Event-time counts. The watermark says: accept events up to 2 days late, then the day is final.
# In append mode a day is only printed once the watermark has passed it, so the numbers never change later.
daily = (valid.withWatermark("event_time", "2 days")
         .groupBy(F.window("event_time", "1 day").alias("day"), "event_type").count())
counts_query = (daily.select(F.date_format("day.start", "yyyy-MM-dd").alias("day"), "event_type", "count")
                .writeStream.outputMode("append").format("console").option("truncate", False)
                .option("numRows", 12)
                .option("checkpointLocation", CHECKPOINTS + "/stream_counts")
                .trigger(processingTime="30 seconds")
                .queryName("daily_counts").start())

print("streaming started - waiting for events on supplychain.events", flush=True)
spark.streams.awaitAnyTermination()

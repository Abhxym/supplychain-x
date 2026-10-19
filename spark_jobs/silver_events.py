"""Silver: one row per disaster event, plus one row per (event, affected country).

bronze/events/gdacs ->
    silver/events           unique events, latest episode, typed dates, normalised alert level
    silver/event_countries  event x affected country (a drought can hit 5 countries at once)
"""
from pyspark.sql import functions as F, Window

import lake

spark = lake.spark("silver-events")
# the bronze folders are named by download month, which is not the event's own date - drop it
raw = spark.read.parquet(lake.BRONZE + "/events/gdacs").drop("year")
raw_rows = raw.count()

events = (raw
    .withColumn("event_key", F.concat_ws("-", "eventtype", "eventid"))
    .withColumn("alert_level", F.initcap(F.trim("alertlevel")))   # 'GREEN' and 'Green' -> 'Green'
    .withColumn("start_ts", F.to_timestamp("fromdate"))
    .withColumn("end_ts", F.to_timestamp("todate"))
    .withColumn("modified_ts", F.to_timestamp("datemodified"))
    # GDACS has the odd event that ends before it starts (FL-1101126: 28 Sep -> 1 Sep 2021).
    # We can't tell which date is wrong, so keep the event, treat the duration as unknown, and flag it.
    .withColumn("date_fixed", F.col("end_ts") < F.col("start_ts"))
    .withColumn("end_ts", F.when(F.col("date_fixed"), F.col("start_ts")).otherwise(F.col("end_ts"))))

# long events show up once per month they span; keep the most recently updated version of each
latest = Window.partitionBy("event_key").orderBy(F.desc("modified_ts"), F.desc("episodeid"))
events = events.withColumn("rn", F.row_number().over(latest)).where("rn = 1").drop("rn")

sev = F.from_json("severitydata", "severity DOUBLE, severitytext STRING, severityunit STRING")
events = events.select(
    "event_key",
    F.col("eventtype").alias("event_type"),     # EQ TC FL VO DR WF
    F.col("eventid").cast("long").alias("event_id"),
    F.col("eventname").alias("event_name"),
    F.col("name").alias("title"),
    "alert_level",
    F.col("alertscore").cast("double").alias("alert_score"),
    sev["severity"].alias("severity_value"),
    sev["severityunit"].alias("severity_unit"),
    sev["severitytext"].alias("severity_text"),
    "start_ts", "end_ts",
    (F.datediff("end_ts", "start_ts") + 1).alias("duration_days"),
    "date_fixed",
    F.col("iso3").alias("main_iso3"),
    "latitude", "longitude",
    "affectedcountries",
    F.year("start_ts").alias("year"),
)

affected = F.from_json("affectedcountries", "array<struct<iso2:string,iso3:string,countryname:string>>")
event_countries = (events
    .select("event_key", "year", F.explode_outer(affected).alias("c"), "main_iso3")
    # a few events list no affected countries - fall back to the main country
    .select("event_key", "year",
            F.coalesce("c.iso3", "main_iso3").alias("iso3"),
            F.col("c.countryname").alias("country_name"))
    .where(F.col("iso3").rlike("^[A-Z]{3}$"))
    .dropDuplicates(["event_key", "iso3"]))
events = events.drop("affectedcountries")

n = events.count()
lake.check("event_key is unique", events.select("event_key").distinct().count() == n)
levels = {r[0] for r in events.select("alert_level").distinct().collect()}
lake.check("alert levels normalised", levels <= {"Green", "Orange", "Red"}, sorted(levels))
lake.check("end is not before start", events.where("end_ts < start_ts").count() == 0,
           "{} event(s) had swapped dates, flagged date_fixed".format(events.where("date_fixed").count()))
# ~6k small events are at sea (ocean-ridge quakes, cyclones that never made landfall) and have no
# country - fine. But every serious event must be tied to at least one country.
no_country = events.join(event_countries, "event_key", "left_anti")
lake.check("every orange/red event has a country",
           no_country.where("alert_level != 'Green'").count() == 0,
           "{:,} green events at sea without a country, {:,} event-country rows".format(
               no_country.count(), event_countries.count()))

events.write.mode("overwrite").partitionBy("year").parquet(lake.SILVER + "/events")
event_countries.write.mode("overwrite").partitionBy("year").parquet(lake.SILVER + "/event_countries")
print("bronze rows {:,} -> {:,} unique events".format(raw_rows, n))
events.groupBy("alert_level").count().orderBy("alert_level").show()
spark.stop()

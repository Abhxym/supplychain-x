"""Gold: how often each country and port gets hit.

silver/events + silver/event_countries -> gold/country_event_features (country x year)
silver/weather + silver/ports          -> gold/port_weather_features   (port x year)

These are the "historical exposure" inputs for the ML layer and the impact score later.
"""
from pyspark.sql import functions as F

import lake

spark = lake.spark("gold-risk-features")

events = spark.read.parquet(lake.SILVER + "/events").select(
    "event_key", "event_type", "alert_level", "duration_days", "start_ts")
event_countries = spark.read.parquet(lake.SILVER + "/event_countries").drop("year")

# the event's own start year, not the folder it happened to be filed under
hits = (event_countries.join(events, "event_key")
        .withColumn("year", F.year("start_ts"))
        .where(F.col("year").between(2019, 2023))
        .withColumn("serious", F.col("alert_level").isin("Orange", "Red")))

totals = (hits.groupBy("iso3", "year")
          .agg(F.count("*").alias("n_events"),
               F.sum(F.col("serious").cast("int")).alias("n_serious"),
               F.sum(F.when(F.col("alert_level") == "Red", 1).otherwise(0)).alias("n_red"),
               F.sum("duration_days").alias("event_days")))
# pivot: one column per disaster type instead of one row per type
by_type = (hits.groupBy("iso3", "year").pivot("event_type", ["EQ", "TC", "FL", "VO", "DR", "WF"])
           .count().fillna(0))
for t in ["EQ", "TC", "FL", "VO", "DR", "WF"]:
    by_type = by_type.withColumnRenamed(t, "n_" + t.lower())
country_feats = totals.join(by_type, ["iso3", "year"])

ports = spark.read.parquet(lake.SILVER + "/ports").select("wpi_number", "iso3")
weather = spark.read.parquet(lake.SILVER + "/weather")
port_feats = (weather.groupBy("wpi_number", "port_name", "year")
              .agg(F.sum(F.col("severe_day").cast("int")).alias("severe_days"),
                   F.sum(F.col("heavy_rain").cast("int")).alias("heavy_rain_days"),
                   F.sum(F.col("storm_gust").cast("int")).alias("storm_gust_days"),
                   F.sum(F.col("extreme_heat").cast("int")).alias("extreme_heat_days"),
                   F.max("gust_max_kmh").alias("max_gust_kmh"),
                   F.max("precip_mm").alias("max_precip_mm"))
              .join(F.broadcast(ports), "wpi_number", "left"))

lake.check("one row per country per year",
           country_feats.count() == country_feats.select("iso3", "year").distinct().count())
lake.check("type counts add up to the total",
           country_feats.where("n_eq + n_tc + n_fl + n_vo + n_dr + n_wf != n_events").count() == 0)
lake.check("45 ports x 5 years", port_feats.count() == 225, port_feats.count())
lake.check("every port has a country", port_feats.where("iso3 IS NULL").count() == 0)

country_feats.write.mode("overwrite").partitionBy("year").parquet(lake.GOLD + "/country_event_features")
port_feats.write.mode("overwrite").partitionBy("year").parquet(lake.GOLD + "/port_weather_features")

print("Countries with the most serious (orange/red) events, 2019-23:")
(country_feats.groupBy("iso3").agg(F.sum("n_serious").alias("serious"), F.sum("n_events").alias("all_events"))
    .orderBy(F.desc("serious")).show(8))
print("Ports with the most severe-weather days, 2019-23:")
(port_feats.groupBy("port_name", "iso3").agg(F.sum("severe_days").alias("severe_days"),
                                             F.max("max_gust_kmh").alias("max_gust"))
    .orderBy(F.desc("severe_days")).show(8))
spark.stop()

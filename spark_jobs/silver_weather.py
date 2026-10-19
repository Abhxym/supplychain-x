"""Silver: daily port weather with typed columns and severe-weather flags.

bronze/weather/<wpi>.parquet -> silver/weather (partitioned by year)

Flag thresholds are from public definitions, not tuned to our data:
    heavy_rain       >= 64.5 mm/day   India Meteorological Department "heavy rainfall"
    very_heavy_rain  >= 115.6 mm/day  IMD "very heavy rainfall"
    storm_gust       >= 89 km/h       Beaufort force 10 ("storm")
    extreme_heat     >= 40 C max temperature
    thunderstorm     WMO weather codes 95, 96, 99
"""
from pyspark.sql import functions as F

import lake

spark = lake.spark("silver-weather")
raw = spark.read.parquet(lake.BRONZE + "/weather")

weather = raw.select(
    F.col("wpi_number").cast("int"),
    "port_name",
    F.to_date("time").alias("date"),
    F.col("weather_code").cast("int"),
    F.col("temperature_2m_max").alias("temp_max_c"),
    F.col("temperature_2m_min").alias("temp_min_c"),
    F.col("precipitation_sum").alias("precip_mm"),
    F.col("wind_speed_10m_max").alias("wind_max_kmh"),
    F.col("wind_gusts_10m_max").alias("gust_max_kmh"),
).withColumn("year", F.year("date"))

weather = (weather
    .withColumn("heavy_rain", F.col("precip_mm") >= 64.5)
    .withColumn("very_heavy_rain", F.col("precip_mm") >= 115.6)
    .withColumn("storm_gust", F.col("gust_max_kmh") >= 89)
    .withColumn("extreme_heat", F.col("temp_max_c") >= 40)
    .withColumn("thunderstorm", F.col("weather_code").isin(95, 96, 99))
    .withColumn("severe_day", F.col("very_heavy_rain") | F.col("storm_gust") | F.col("extreme_heat")))

n = weather.count()
per_port = weather.groupBy("wpi_number").count()
lake.check("one row per port per day", weather.select("wpi_number", "date").distinct().count() == n)
lake.check("every port has all 1,826 days", per_port.where("count != 1826").count() == 0,
           "{} ports".format(per_port.count()))
lake.check("no missing measurements",
           weather.where("precip_mm IS NULL OR gust_max_kmh IS NULL OR temp_max_c IS NULL").count() == 0)

weather.write.mode("overwrite").partitionBy("year").parquet(lake.SILVER + "/weather")
print("weather rows: {:,}".format(n))
(weather.groupBy("year")
    .agg(F.sum(F.col("heavy_rain").cast("int")).alias("heavy_rain_days"),
         F.sum(F.col("storm_gust").cast("int")).alias("storm_gust_days"),
         F.sum(F.col("severe_day").cast("int")).alias("severe_days"))
    .orderBy("year").show())
spark.stop()

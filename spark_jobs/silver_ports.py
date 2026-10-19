"""Silver: one row per port, with a proper ISO3 country and numeric types.

bronze/ports/wpi.parquet (111 string columns) -> silver/ports
"""
from pyspark.sql import functions as F, Window

import lake

spark = lake.spark("silver-ports")
raw = spark.read.parquet(lake.BRONZE + "/ports/wpi.parquet")
countries = spark.read.parquet(lake.SILVER + "/countries")


def num(col):
    # bronze keeps everything as text; blanks become null instead of failing the cast
    return F.when(F.trim(col) == "", None).otherwise(F.trim(col)).cast("double")


def text(col):
    return F.when(F.trim(col).isin("", "Unknown"), None).otherwise(F.trim(col))


ports = raw.select(
    num("world_port_index_number").cast("int").alias("wpi_number"),
    num("oid").cast("int").alias("oid"),
    F.trim("main_port_name").alias("port_name"),
    text("alternate_port_name").alias("alt_name"),
    F.regexp_replace("un_locode", " ", "").alias("un_locode"),
    F.trim("country_code").alias("country_name"),   # WPI calls it a code, it's a name
    text("region_name").alias("region"),
    text("world_water_body").alias("water_body"),
    num("latitude").alias("latitude"),
    num("longitude").alias("longitude"),
    text("harbor_size").alias("harbor_size"),
    text("harbor_type").alias("harbor_type"),
    num("channel_depth_m").alias("channel_depth_m"),
    num("cargo_pier_depth_m").alias("cargo_pier_depth_m"),
    num("maximum_vessel_length_m").alias("max_vessel_length_m"),
    text("facilities_container").alias("container_facilities"),
).withColumn("un_locode", F.when(F.col("un_locode") == "", None).otherwise(F.col("un_locode")))

# two index numbers are used twice in WPI (400: same Icelandic port spelled two ways,
# 46135: two different Nigerian ports). Keep the older entry so wpi_number stays a key.
first = Window.partitionBy("wpi_number").orderBy("oid")
dupes = ports.groupBy("wpi_number").count().where("count > 1").count()
ports = ports.withColumn("rn", F.row_number().over(first)).where("rn = 1").drop("rn", "oid")

# country name -> ISO3: the alias table first, then an exact match on the UN name
aliases = spark.createDataFrame(list(lake.WPI_COUNTRY_ISO3.items()), ["country_name", "alias_iso3"])
by_name = countries.select(F.col("name").alias("country_name"), F.col("iso3").alias("name_iso3"))
ports = (ports.join(F.broadcast(aliases), "country_name", "left")
              .join(F.broadcast(by_name), "country_name", "left")
              .withColumn("iso3", F.coalesce("alias_iso3", "name_iso3"))
              .drop("alias_iso3", "name_iso3"))

# the 45 ports we pulled weather for are the "major" ones the impact engine starts from
major = (spark.read.parquet(lake.BRONZE + "/weather")
         .select(F.col("wpi_number").cast("int")).distinct().withColumn("is_major", F.lit(True)))
ports = ports.join(F.broadcast(major), "wpi_number", "left").fillna(False, ["is_major"])

n = ports.count()
unmatched = ports.where("iso3 IS NULL")
lake.check("wpi_number is unique", ports.select("wpi_number").distinct().count() == n,
           "{} duplicated number(s) resolved".format(dupes))
lake.check("coordinates in range",
           ports.where("abs(latitude) > 90 OR abs(longitude) > 180 OR latitude IS NULL").count() == 0)
lake.check("all ports have an ISO3 country", unmatched.count() == 0,
           [r[0] for r in unmatched.select("country_name").distinct().collect()])
lake.check("all 45 major ports present", ports.where("is_major").count() == 45)

ports.coalesce(1).write.mode("overwrite").parquet(lake.SILVER + "/ports")
print("ports written: {:,} ({} countries)".format(n, ports.select("iso3").distinct().count()))
spark.stop()

"""Export the gold layer as graph files for Neo4j (data/graph/*.json).

Spark does the joins and filtering on the cluster; the result (a few tens of thousands of
edges) is small enough to collect and hand to the Neo4j loader as plain JSON.

Nodes:  Country, Product, Port (the 45 major ones), Industry
Edges:  SUPPLIES   supplier -> importer, per product, 2023: share of the importer's imports + value
        EXPORTS    country -> product (total exported to our 20 importers, 2023)
        LOCATED_IN port -> country
        USED_BY    product -> industry
"""
import json
import os

from pyspark.sql import functions as F

import lake

YEAR = 2023
MIN_SHARE = 0.01  # links under 1% of an importer's supply are noise for cascade purposes

spark = lake.spark("export-graph")
OUT = "/opt/scx/data/graph"
os.makedirs(OUT, exist_ok=True)


def dump(name, df):
    rows = [r.asDict(recursive=True) for r in df.collect()]
    with open("{}/{}.json".format(OUT, name), "w") as f:
        json.dump(rows, f)
    print("{:<12} {:>7,} rows".format(name, len(rows)))
    return rows


deps = spark.read.parquet(lake.GOLD + "/dependencies").where(F.col("year") == YEAR)
conc = spark.read.parquet(lake.GOLD + "/concentration").where(F.col("year") == YEAR)
countries = spark.read.parquet(lake.SILVER + "/countries")
events = spark.read.parquet(lake.GOLD + "/country_event_features")
ports = spark.read.parquet(lake.SILVER + "/ports").where("is_major")
port_weather = spark.read.parquet(lake.GOLD + "/port_weather_features")

supplies = (deps.where(F.col("trade_share") >= MIN_SHARE)
            .select(F.col("supplier_iso3").alias("src"), F.col("importer_iso3").alias("dst"), "hs2",
                    F.round("trade_share", 4).alias("share"),
                    F.round("import_value_usd").alias("value_usd"), F.col("supplier_rank").alias("rank")))

in_graph = (supplies.select(F.col("src").alias("iso3")).union(supplies.select(F.col("dst").alias("iso3")))
            .distinct())
risk = events.groupBy("iso3").agg(F.sum("n_events").alias("events_5y"), F.sum("n_serious").alias("serious_5y"))
reporters = deps.select(F.col("importer_iso3").alias("iso3")).distinct().withColumn("is_reporter", F.lit(True))
country_nodes = (in_graph.join(countries.select("iso3", "name"), "iso3", "left")
                 .join(risk, "iso3", "left").join(reporters, "iso3", "left")
                 .fillna(0, ["events_5y", "serious_5y"]).fillna(False, ["is_reporter"])
                 .withColumn("name", F.coalesce("name", "iso3")))

exports = (deps.groupBy(F.col("supplier_iso3").alias("iso3"), "hs2")
           .agg(F.round(F.sum("import_value_usd")).alias("value_usd")))

port_nodes = (ports.join(port_weather.groupBy("wpi_number")
                         .agg(F.sum("severe_days").alias("severe_days_5y"), F.max("max_gust_kmh").alias("max_gust_kmh")),
                         "wpi_number", "left")
              .select("wpi_number", "port_name", "iso3", "country_name", "latitude", "longitude",
                      "severe_days_5y", "max_gust_kmh"))

dump("countries", country_nodes)
dump("supplies", supplies)
dump("exports", exports)
dump("ports", port_nodes)
dump("concentration", conc.select(F.col("importer_iso3").alias("iso3"), "hs2", F.round("hhi", 4).alias("hhi"),
                                  "top_supplier_iso3", F.round("top_share", 4).alias("top_share")))
with open(OUT + "/products.json", "w") as f:
    json.dump([{"hs2": k, "name": v[0], "category": v[1], "industries": lake.PRODUCT_INDUSTRIES[k]}
               for k, v in lake.HS_CHAPTERS.items()], f)
print("products         12 rows")
spark.stop()

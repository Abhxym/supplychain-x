"""Gold: who depends on whom, for what.

silver/trade + silver/trade_totals ->
    gold/dependencies    importer x product x supplier x year: value, share of the importer's imports, rank
    gold/concentration   importer x product x year: how many suppliers, HHI, the top supplier

trade_share = imports from that supplier / importer's world imports of that product.
The denominator is the world total, which still contains "Areas, nes", so shares of real
countries add up to a bit under 1 - that gap is trade nobody can trace, not a bug.

HHI (Herfindahl-Hirschman Index) = sum of squared shares. 1.0 = one single supplier,
near 0 = spread over many. Above 0.25 counts as highly concentrated (US DOJ/FTC convention).
"""
from pyspark.sql import functions as F, Window

import lake

spark = lake.spark("gold-dependencies")

imports = (spark.read.parquet(lake.SILVER + "/trade")
           .where("flow = 'M'")
           .select("year", F.col("reporter_iso3").alias("importer_iso3"), "hs2",
                   F.col("partner_iso3").alias("supplier_iso3"), F.col("value_usd").alias("import_value_usd")))
world = (spark.read.parquet(lake.SILVER + "/trade_totals")
         .where("flow = 'M'")
         .select("year", F.col("reporter_iso3").alias("importer_iso3"), "hs2",
                 F.col("world_value_usd").alias("world_import_usd")))

# 2,400 total rows vs ~160k supplier rows: broadcast the small side so the big one never shuffles
deps = (imports.join(F.broadcast(world), ["year", "importer_iso3", "hs2"])
        .where("world_import_usd > 0")
        .withColumn("trade_share", F.col("import_value_usd") / F.col("world_import_usd")))

by_importer = Window.partitionBy("year", "importer_iso3", "hs2").orderBy(F.desc("import_value_usd"))
deps = deps.withColumn("supplier_rank", F.row_number().over(by_importer)).cache()

conc = (deps.groupBy("year", "importer_iso3", "hs2", "world_import_usd")
        .agg(F.count("*").alias("n_suppliers"),
             F.sum(F.col("trade_share") * F.col("trade_share")).alias("hhi"),
             F.sum("trade_share").alias("traced_share"),
             F.max(F.when(F.col("supplier_rank") == 1, F.col("supplier_iso3"))).alias("top_supplier_iso3"),
             F.max(F.when(F.col("supplier_rank") == 1, F.col("trade_share"))).alias("top_share"))
        .withColumn("concentration", F.when(F.col("hhi") > 0.25, "high")
                                      .when(F.col("hhi") > 0.15, "moderate").otherwise("low")))

n = deps.count()
lake.check("shares between 0 and 1", deps.where("trade_share < 0 OR trade_share > 1").count() == 0)
lake.check("suppliers never add up to more than the world total",
           conc.where("traced_share > 1.001").count() == 0)
lake.check("one row per importer/product/year", conc.count() == 20 * 12 * 5, conc.count())
lake.check("india electronics 2023 present",
           conc.where("importer_iso3 = 'IND' AND hs2 = '85' AND year = 2023").count() == 1)

deps.write.mode("overwrite").partitionBy("year").parquet(lake.GOLD + "/dependencies")
conc.write.mode("overwrite").partitionBy("year").parquet(lake.GOLD + "/concentration")
print("dependencies: {:,} rows, concentration: {:,} rows".format(n, conc.count()))

print("Most concentrated imports in 2023 (top supplier share):")
(conc.where("year = 2023").orderBy(F.desc("hhi"))
     .select("importer_iso3", "hs2", "top_supplier_iso3",
             F.round("top_share", 2).alias("top_share"), F.round("hhi", 2).alias("hhi"), "n_suppliers")
     .show(10))
spark.stop()

"""Silver: clean bilateral trade + each reporter's world totals.

bronze/trade (50 raw Comtrade columns) ->
    silver/trade         one row per year, reporter, partner, HS chapter, flow (country partners only)
    silver/trade_totals  the partner = World rows, kept apart - they are the denominator for shares
"""
from pyspark.sql import functions as F

import lake

spark = lake.spark("silver-trade")
raw = spark.read.parquet(lake.BRONZE + "/trade")
raw_rows = raw.count()

# we asked the API for totals only - make sure that's really what came back
lake.check("only partner2/customs/transport totals",
           raw.where("partner2Code != 0 OR customsCode != 'C00' OR motCode != 0").count() == 0)

trade = raw.select(
    F.col("refYear").cast("int").alias("year"),
    F.col("reporterISO").alias("reporter_iso3"),
    F.col("partnerCode").cast("int").alias("partner_code"),
    F.when(F.col("partnerCode") == lake.TAIWAN_CODE, "TWN").otherwise(F.col("partnerISO")).alias("partner_iso3"),
    F.when(F.col("partnerCode") == lake.TAIWAN_CODE, "Taiwan").otherwise(F.col("partnerDesc")).alias("partner_name"),
    F.col("cmdCode").alias("hs2"),
    F.col("flowCode").alias("flow"),                       # M = import, X = export
    F.col("primaryValue").cast("double").alias("value_usd"),
    F.col("netWgt").cast("double").alias("net_weight_kg"),
)

key = ["year", "reporter_iso3", "partner_iso3", "hs2", "flow"]

totals = (trade.where("partner_code = 0")
          .select("year", "reporter_iso3", "hs2", "flow", F.col("value_usd").alias("world_value_usd")))
bilateral = (trade.where(~F.col("partner_code").isin(list(lake.NON_COUNTRY_PARTNERS)))
             .where(F.col("partner_iso3").rlike("^[A-Z]{3}$"))
             .where(F.col("partner_iso3") != F.col("reporter_iso3"))
             .dropDuplicates(key)
             .drop("partner_code"))

# how much trade sits in "Areas, nes", bunkers etc. - dropped from bilateral, still inside the totals
t_sum = totals.agg(F.sum("world_value_usd")).first()[0]
b_sum = bilateral.agg(F.sum("value_usd")).first()[0]
n = bilateral.count()

lake.check("no duplicate keys", bilateral.select(key).distinct().count() == n)
lake.check("no negative values", bilateral.where("value_usd < 0").count() == 0)
lake.check("one world total per reporter/hs2/flow/year",
           totals.count() == totals.select("year", "reporter_iso3", "hs2", "flow").distinct().count())
lake.check("bilateral never exceeds world total", b_sum <= t_sum * 1.001,
           "{:.1%} of world value is country-to-country".format(b_sum / t_sum))

bilateral.write.mode("overwrite").partitionBy("year").parquet(lake.SILVER + "/trade")
totals.write.mode("overwrite").partitionBy("year").parquet(lake.SILVER + "/trade_totals")
print("bronze rows {:,} -> silver trade {:,} + totals {:,}".format(raw_rows, n, totals.count()))
spark.stop()

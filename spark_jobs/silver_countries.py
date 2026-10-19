"""Silver: one row per country, keyed by ISO3, built from the Comtrade reference lists.

ISO3 (IND, CHN, USA) is the country key everywhere downstream - trade, ports, events and the graph.
"""
from pyspark.sql import functions as F, Window

import lake

spark = lake.spark("silver-countries")

partners = (spark.read.option("multiLine", True).json(lake.BRONZE + "/reference/partners.json")
            .select(F.explode("results").alias("p")).select("p.*"))
reporters = (spark.read.option("multiLine", True).json(lake.BRONZE + "/reference/reporters.json")
             .select(F.explode("results").alias("r")).select("r.*"))

current = partners.where(~F.col("isGroup") & F.col("entryExpiredDate").isNull())
reporter_codes = reporters.where(F.col("entryExpiredDate").isNull()).select(
    F.col("reporterCode").alias("PartnerCode"), F.lit(True).alias("is_reporter"))

countries = (current
    .where(~F.col("PartnerCode").isin(list(lake.NON_COUNTRY_PARTNERS)))
    .withColumn("iso3", F.when(F.col("PartnerCode") == lake.TAIWAN_CODE, "TWN")
                         .otherwise(F.trim("PartnerCodeIsoAlpha3")))
    .withColumn("name", F.when(F.col("PartnerCode") == lake.TAIWAN_CODE, "Taiwan")
                         .otherwise(F.col("PartnerDesc")))
    .where(F.col("iso3").rlike("^[A-Z]{3}$"))
    .join(reporter_codes, "PartnerCode", "left")
    .select(F.col("PartnerCode").alias("comtrade_code"), "iso3", "name",
            F.coalesce("is_reporter", F.lit(False)).alias("is_reporter")))

# a few ISO3 codes have more than one current Comtrade code - keep the one that also reports trade
w = Window.partitionBy("iso3").orderBy(F.desc("is_reporter"), "comtrade_code")
countries = countries.withColumn("rn", F.row_number().over(w)).where("rn = 1").drop("rn")

n = countries.count()
lake.check("iso3 is unique", countries.select("iso3").distinct().count() == n)
lake.check("taiwan present", countries.where("iso3 = 'TWN'").count() == 1)
lake.check("india uses current code 699", countries.where("iso3 = 'IND'").first()["comtrade_code"] == 699)

countries.coalesce(1).write.mode("overwrite").parquet(lake.SILVER + "/countries")
print("countries written:", n)
spark.stop()

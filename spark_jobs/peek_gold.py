"""Quick look at one importer/product in gold - used to sanity-check against known facts."""
import sys

from pyspark.sql import functions as F

import lake

importer, hs2, year = sys.argv[1], sys.argv[2], int(sys.argv[3])
spark = lake.spark("peek-gold")
(spark.read.parquet(lake.GOLD + "/dependencies")
    .where((F.col("importer_iso3") == importer) & (F.col("hs2") == hs2) & (F.col("year") == year))
    .orderBy("supplier_rank").limit(5)
    .select("supplier_rank", "supplier_iso3", F.round(F.col("import_value_usd") / 1e9, 1).alias("bn_usd"),
            F.round("trade_share", 3).alias("share"))
    .show())
spark.stop()

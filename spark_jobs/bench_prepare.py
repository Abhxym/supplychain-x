"""Build the benchmark inputs for phase 3.

Our real lake is ~10 MB - too small to time anything (Spark's own start-up would dominate).
So the real silver trade rows are copied SCALE times, with a copy_id column. Same values,
same distribution, just more of it. This is a stress copy for timing only, never used for analysis.

Writes to /lake/bench:
    trade_part   parquet, partitioned by year   (for partition pruning)
    trade_flat   parquet, one folder, no partitions (the "before" for pruning)
    trade_csv    plain text, for the MapReduce vs Spark comparison (MapReduce reads lines)

Bench files use 32 MB HDFS blocks instead of our 1 MB demo blocks - with 1 MB blocks MapReduce
would start hundreds of tiny map tasks and lose for a reason that has nothing to do with the engine.
"""
import sys

from pyspark.sql import functions as F

import lake

SCALE = int(sys.argv[1]) if len(sys.argv) > 1 else 10

spark = lake.spark("bench-prepare")
spark.sparkContext._jsc.hadoopConfiguration().set("dfs.blocksize", str(32 * 1024 * 1024))

trade = spark.read.parquet(lake.SILVER + "/trade")
copies = spark.range(SCALE).withColumnRenamed("id", "copy_id")
big = trade.crossJoin(F.broadcast(copies))

# same row order for both copies, so the ONLY difference is the year folders. (A plain
# repartition(8) for the flat copy shuffled rows randomly and made it 7x bigger - Parquet compresses
# runs of similar rows - which would have turned the pruning test into a file-size test.)
ordered = big.repartition(8, "year").sortWithinPartitions("year", "reporter_iso3", "hs2")
ordered.write.mode("overwrite").partitionBy("year").parquet("/lake/bench/trade_part")
ordered.write.mode("overwrite").parquet("/lake/bench/trade_flat")
(big.select("year", "reporter_iso3", "partner_iso3", "hs2", "flow", "value_usd")
    .repartition(8)
    .write.mode("overwrite").option("header", False).csv("/lake/bench/trade_csv"))

n = spark.read.parquet("/lake/bench/trade_flat").count()
lake.check("scaled copy has SCALE x the rows", n == trade.count() * SCALE, "{:,} rows (x{})".format(n, SCALE))
spark.stop()

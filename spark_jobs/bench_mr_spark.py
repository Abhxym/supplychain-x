"""Spark's side of the MapReduce vs Spark race (phase 3, E6).

Exactly the job mapreduce/mapper.cpp + reducer.cpp do: read the same CSV from HDFS,
total value_usd per reporter|hs2, write the result back to HDFS as "key<TAB>total" lines.
"""
from pyspark.sql import functions as F

import lake

spark = lake.spark("bench-mr-spark")
schema = "year INT, reporter_iso3 STRING, partner_iso3 STRING, hs2 STRING, flow STRING, value_usd DOUBLE"

(spark.read.schema(schema).csv("/lake/bench/trade_csv")
    .groupBy(F.concat_ws("|", "reporter_iso3", "hs2").alias("key"))
    .agg(F.sum("value_usd").alias("total"))
    .select(F.concat_ws("\t", "key", F.format_string("%.2f", "total")))
    .coalesce(2)  # same number of output files as the 2 MapReduce reducers
    .write.mode("overwrite").text("/lake/bench/out_spark"))
spark.stop()

"""Check the Spark cluster can read the bronze layer from HDFS.

    docker exec scx-spark-master /opt/spark/bin/spark-submit /opt/scx/spark_jobs/smoke_test.py
"""
from pyspark.sql import SparkSession, functions as F

spark = SparkSession.builder.appName("smoke-test").getOrCreate()

# no hdfs:// prefix needed - fs.defaultFS in spark-defaults.conf points at the namenode
trade = spark.read.parquet("/lake/bronze/trade")

print("partitions read:", trade.rdd.getNumPartitions())
(trade
    .where(F.col("partnerCode") == 0)  # world total rows only
    .groupBy("year", "flowCode")
    .agg(F.round(F.sum("primaryValue") / 1e12, 2).alias("trillion_usd"))
    .orderBy("year", "flowCode")
    .show())

workers = spark.sparkContext._jsc.sc().getExecutorMemoryStatus().size() - 1  # minus the driver
print("executors used:", workers)
spark.stop()

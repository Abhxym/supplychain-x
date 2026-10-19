"""Phase 3 Spark experiments on the x10 benchmark copy (/lake/bench).

    bench_spark.py settings   E0-E4: file format, shuffle partitions, join strategy, pruning, caching
    bench_spark.py cores N    E5: the dependency workload with N cores (2 = one worker, 4 = both)

Every measurement: 1 untimed warm-up, then REPS timed runs. Each run ends in the "noop" sink,
which executes the whole plan but writes nothing, so we time the computation and not a disk write.
Results are printed as RESULT {json} lines that scripts/bench.py collects.
"""
import json
import statistics
import sys
import time

from pyspark.sql import SparkSession, functions as F, Window

import lake

REPS = 3
mode = sys.argv[1] if len(sys.argv) > 1 else "settings"
builder = SparkSession.builder.appName("bench-" + mode + ("-" + sys.argv[2] if len(sys.argv) > 2 else ""))
if mode == "cores":
    # must be set before the session starts: caps how many cores the app may take from the cluster.
    # executors have 2 cores each (spark-defaults.conf), so 2 = one executor = one worker.
    builder = builder.config("spark.cores.max", sys.argv[2])
spark = builder.getOrCreate()
PART, FLAT, CSV = "/lake/bench/trade_part", "/lake/bench/trade_flat", "/lake/bench/trade_csv"


def run(df):
    df.write.format("noop").mode("overwrite").save()


def measure(experiment, setting, make_df, note=""):
    """make_df builds a fresh DataFrame each time, so no run reuses another's result."""
    run(make_df())  # warm-up, not timed
    times = []
    for _ in range(REPS):
        t = time.perf_counter()
        run(make_df())
        times.append(time.perf_counter() - t)
    out = {"experiment": experiment, "setting": str(setting), "median_s": round(statistics.median(times), 3),
           "min_s": round(min(times), 3), "runs": [round(x, 3) for x in times], "note": note}
    print("RESULT " + json.dumps(out))


def dependency_workload(path=PART):
    """The real gold job: import shares per supplier, supplier rank, then HHI per importer/product."""
    trade = spark.read.parquet(path)
    imports = trade.where("flow = 'M'")
    world = (spark.read.parquet(lake.SILVER + "/trade_totals").where("flow = 'M'")
             .select("year", "reporter_iso3", "hs2", "world_value_usd"))
    deps = (imports.join(world, ["year", "reporter_iso3", "hs2"])
            .withColumn("share", F.col("value_usd") / F.col("world_value_usd")))
    w = Window.partitionBy("copy_id", "year", "reporter_iso3", "hs2").orderBy(F.desc("value_usd"))
    deps = deps.withColumn("rank", F.row_number().over(w))
    return deps.groupBy("copy_id", "year", "reporter_iso3", "hs2").agg(
        F.sum(F.col("share") * F.col("share")).alias("hhi"), F.max("rank").alias("n"))


def value_by_reporter_product(df):
    return df.groupBy("reporter_iso3", "hs2").agg(F.sum("value_usd").alias("total"))


if mode == "cores":
    cores = int(sys.argv[2])
    # executors register a few seconds after the session starts - wait for them before timing
    for _ in range(30):
        got = spark.sparkContext._jsc.sc().getExecutorMemoryStatus().size() - 1  # minus the driver
        if got >= cores // 2:
            break
        time.sleep(1)
    lake.check("running on the requested cores", got == cores // 2, "{} executor(s)".format(got))
    measure("E5 parallelism", "{} cores ({} worker{})".format(cores, cores // 2, "s" if cores > 2 else ""),
            dependency_workload)

else:
    # E0: same aggregation from CSV text vs columnar Parquet
    csv_schema = "year INT, reporter_iso3 STRING, partner_iso3 STRING, hs2 STRING, flow STRING, value_usd DOUBLE"
    measure("E0 file format", "CSV (92 MB)",
            lambda: value_by_reporter_product(spark.read.schema(csv_schema).csv(CSV)))
    measure("E0 file format", "Parquet (4.5 MB)",
            lambda: value_by_reporter_product(spark.read.parquet(FLAT)))

    # E1: how many pieces the shuffle is cut into (Spark's default is 200)
    for n in [1, 4, 8, 16, 64, 200]:
        spark.conf.set("spark.sql.shuffle.partitions", str(n))
        measure("E1 shuffle partitions", n, dependency_workload)
    spark.conf.set("spark.sql.shuffle.partitions", "8")

    # E2: joining 3.3M trade rows with the 2,400-row totals table
    world = lambda: spark.read.parquet(lake.SILVER + "/trade_totals").select(
        "year", "reporter_iso3", "hs2", "flow", "world_value_usd")
    join_agg = lambda w: (spark.read.parquet(PART).join(w, ["year", "reporter_iso3", "hs2", "flow"])
                          .groupBy("reporter_iso3").agg(F.sum(F.col("value_usd") / F.col("world_value_usd"))))
    spark.conf.set("spark.sql.autoBroadcastJoinThreshold", "-1")  # forbid automatic broadcast
    measure("E2 join strategy", "sort-merge join (both sides shuffled)", lambda: join_agg(world()))
    measure("E2 join strategy", "broadcast join (small side copied to workers)",
            lambda: join_agg(F.broadcast(world())))
    spark.conf.unset("spark.sql.autoBroadcastJoinThreshold")

    # E3: one year out of five - partitioned folders let Spark skip 4/5 of the files
    one_year = lambda path: (spark.read.parquet(path).where("year = 2023")
                             .groupBy("reporter_iso3").agg(F.sum("value_usd")))
    measure("E3 partition pruning", "flat files, filter year = 2023", lambda: one_year(FLAT))
    measure("E3 partition pruning", "year=... folders, filter year = 2023", lambda: one_year(PART))

    # E4: three different questions asked of the same filtered data
    def three_queries(cache):
        base = spark.read.parquet(PART).where("flow = 'M' AND value_usd > 0")
        if cache:
            base = base.cache()
        a = base.groupBy("reporter_iso3").agg(F.sum("value_usd"))
        b = base.groupBy("partner_iso3").agg(F.count("*"))
        c = base.groupBy("hs2").agg(F.avg("value_usd"))
        result = a.crossJoin(F.broadcast(b.limit(1))).crossJoin(F.broadcast(c.limit(1)))
        return result, base

    def no_cache():
        return three_queries(False)[0]

    def with_cache():
        # cache is per run: unpersist first so every timed run pays for filling it once
        spark.catalog.clearCache()
        return three_queries(True)[0]

    measure("E4 caching", "no cache (source re-read for each query)", no_cache)
    measure("E4 caching", "cache() the filtered data, reuse 3x", with_cache)

    # the other side: the cache is filled once up front, and only the queries are timed
    spark.catalog.clearCache()
    warm = three_queries(True)
    warm[1].count()  # fills the cache
    measure("E4 caching", "queries on an already-filled cache", lambda: three_queries(True)[0],
            note="cache filled once before timing")
    spark.catalog.clearCache()

spark.stop()

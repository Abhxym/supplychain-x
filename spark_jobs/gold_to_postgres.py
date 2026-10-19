"""Load gold tables into PostgreSQL, where the API will read them.

Spark writes straight to Postgres over JDBC - each worker sends its own partitions,
so the load is parallel too. Loads: countries, commodities, dependencies.

Credentials come in as environment variables (scripts/spark_run.py passes them from .env).
"""
import os

from pyspark.sql import functions as F

import lake

spark = lake.spark("gold-to-postgres")
URL = "jdbc:postgresql://postgres:5432/" + os.environ["POSTGRES_DB"]
PROPS = {"user": os.environ["POSTGRES_USER"], "password": os.environ["POSTGRES_PASSWORD"],
         "driver": "org.postgresql.Driver"}


def sql(statement):
    # plain SQL (TRUNCATE etc.) through the same JDBC driver, run once on the driver
    # --packages puts the driver in Spark's class loader, not the JVM's default one,
    # so load it from there and connect with it directly (DriverManager wouldn't find it)
    jvm = spark.sparkContext._jvm
    loader = jvm.java.lang.Thread.currentThread().getContextClassLoader()
    driver = loader.loadClass("org.postgresql.Driver").newInstance()
    props = jvm.java.util.Properties()
    props.setProperty("user", PROPS["user"])
    props.setProperty("password", PROPS["password"])
    conn = driver.connect(URL, props)
    try:
        conn.createStatement().execute(statement)
    finally:
        conn.close()


def write(df, table):
    df.write.jdbc(URL, table, mode="append", properties=dict(PROPS, batchsize="5000"))


def read(table):
    return spark.read.jdbc(URL, table, properties=PROPS)


# full reload every run, so rerunning never duplicates rows.
# CASCADE also empties tables that point at countries (ports, events, ...) - they get reloaded by their own jobs.
sql("TRUNCATE countries, commodities, dependencies RESTART IDENTITY CASCADE")

countries = spark.read.parquet(lake.SILVER + "/countries").select("iso3", F.col("name").alias("country_name"))
write(countries, "countries")

chapters = spark.createDataFrame(
    [(hs, name, cat) for hs, (name, cat) in lake.HS_CHAPTERS.items()],
    ["hs_code", "commodity_name", "category"])
write(chapters, "commodities")

# the database hands out ids; read them back to translate ISO3 / HS codes into foreign keys
c_ids = read("countries").select("country_id", "iso3")
h_ids = read("commodities").select("commodity_id", "hs_code")

deps = spark.read.parquet(lake.GOLD + "/dependencies")
rows = (deps
    .join(F.broadcast(c_ids.withColumnRenamed("country_id", "source_country")
                           .withColumnRenamed("iso3", "supplier_iso3")), "supplier_iso3")
    .join(F.broadcast(c_ids.withColumnRenamed("country_id", "target_country")
                           .withColumnRenamed("iso3", "importer_iso3")), "importer_iso3")
    .join(F.broadcast(h_ids.withColumnRenamed("hs_code", "hs2")), "hs2")
    .select("source_country", "target_country", "commodity_id", F.col("year").cast("short"),
            F.col("trade_share").cast("float"),
            # for now the score is the plain share; phase 5 swaps in the full impact weighting
            F.col("trade_share").cast("float").alias("dependency_score")))
write(rows.repartition(4), "dependencies")

expected = deps.count()
loaded = read("dependencies").count()
lake.check("every country key matched", countries.count() == read("countries").count())
lake.check("all 12 commodities loaded", read("commodities").count() == 12)
lake.check("every dependency row loaded", loaded == expected, "{:,} of {:,}".format(loaded, expected))
spark.stop()

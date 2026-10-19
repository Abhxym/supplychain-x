"""Read every silver and gold table end to end and print a fingerprint of each.

Used by the fault-tolerance demo: if a DataNode is down and every table still gives the same
row count and checksum, then every block was read from its surviving copy.
"""
from pyspark.sql import functions as F

import lake

spark = lake.spark("verify-lake")

# table -> a numeric column to sum, so we check the values and not just the row count
TABLES = [
    ("silver/countries", None),
    ("silver/trade", "value_usd"),
    ("silver/trade_totals", "world_value_usd"),
    ("silver/events", "alert_score"),
    ("silver/event_countries", None),
    ("silver/ports", "latitude"),
    ("silver/weather", "precip_mm"),
    ("gold/dependencies", "trade_share"),
    ("gold/concentration", "hhi"),
    ("gold/country_event_features", "n_events"),
    ("gold/port_weather_features", "severe_days"),
]

total = 0
for path, col in TABLES:
    df = spark.read.parquet("/lake/" + path)
    if col:
        row = df.agg(F.count("*").alias("n"), F.sum(col).alias("s")).first()
        n, checksum = row["n"], "{:.6g}".format(row["s"] or 0)
    else:
        n, checksum = df.count(), "-"
    total += n
    print("TABLE {:<30} rows {:>9,}  checksum {}".format(path, n, checksum))
print("TOTAL rows read: {:,}".format(total))
spark.stop()

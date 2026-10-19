"""Have a quick look at any parquet file or folder in the data lake.

    python scripts/peek.py data/bronze/trade
    python scripts/peek.py data/bronze/trade/year=2023/reporter=IND.parquet --cols reporterISO partnerISO cmdCode flowCode primaryValue
"""
import argparse

import pandas as pd
import pyarrow.dataset as ds

p = argparse.ArgumentParser()
p.add_argument("path")
p.add_argument("--cols", nargs="+")
p.add_argument("-n", type=int, default=10)
args = p.parse_args()

# "hive" partitioning turns folder names like year=2023 into real columns
dataset = ds.dataset(args.path, format="parquet", partitioning="hive")
print(f"files:   {len(dataset.files)}")
print(f"rows:    {dataset.count_rows():,}")
print(f"columns: {len(dataset.schema.names)}")
print()

df = dataset.head(args.n, columns=args.cols).to_pandas()
pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 20)
print(df)

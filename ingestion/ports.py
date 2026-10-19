"""Download the World Port Index (NGA Pub. 150) into bronze.

~3,800 ports with location, harbor size, depths and facilities. Public, no key.
Keeps the original CSV untouched and writes a parquet copy next to it.

    python -m ingestion.ports
"""
import io
import re
from datetime import datetime, timezone

import pandas as pd
import requests

from ingestion.config import BRONZE

URL = "https://msi.nga.mil/api/publications/download?key=16920959/SFH00000/UpdatedPub150.csv&type=view"


def snake(name):
    # Spark refuses parquet columns with spaces / brackets ("Tidal Range (m)"), so normalise them.
    # Only the names change - every column and value is kept as-is.
    return re.sub(r"[^0-9a-z]+", "_", name.strip().lower()).strip("_")


def main():
    out = BRONZE / "ports"
    out.mkdir(parents=True, exist_ok=True)

    r = requests.get(URL, timeout=120)
    r.raise_for_status()
    (out / "wpi_raw.csv").write_bytes(r.content)

    # everything as string in bronze - typing happens in silver
    df = pd.read_csv(io.BytesIO(r.content), encoding="utf-8-sig", dtype=str, keep_default_na=False)
    df.columns = [snake(c) for c in df.columns]
    df["_ingested_at"] = datetime.now(timezone.utc).isoformat()
    df["_source"] = "nga_world_port_index"
    df.to_parquet(out / "wpi.parquet", index=False)

    print(f"saved {len(df)} ports, {len(df.columns)} columns -> {out / 'wpi.parquet'}")


if __name__ == "__main__":
    main()

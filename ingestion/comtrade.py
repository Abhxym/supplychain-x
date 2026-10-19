"""Download annual bilateral trade from UN Comtrade into the bronze layer.

One API call = one reporter, one year, all our HS chapters, imports + exports.
Output: data/bronze/trade/year=YYYY/reporter=ISO3.parquet

Already-downloaded files are skipped, so you can stop and rerun any time
(the free key is limited to ~500 calls a day).

    python -m ingestion.comtrade
    python -m ingestion.comtrade --years 2023 --reporters IND CHN
"""
import argparse
import os
import time
from datetime import datetime, timezone

import pandas as pd
import requests
from dotenv import load_dotenv

from ingestion import config
from ingestion.reference import load

API = "https://comtradeapi.un.org/data/v1/get/C/A/HS"  # C = commodities, A = annual
MAX_RECORDS = 100_000


def reporter_codes():
    """ISO3 -> current Comtrade numeric code (skips expired historical codes like India-1974)."""
    codes = {}
    for r in load("reporters"):
        if not r["isGroup"] and r.get("entryExpiredDate") is None:
            codes[r["reporterCodeIsoAlpha3"]] = r["reporterCode"]
    return codes


def fetch(session, reporter_code, year):
    params = {
        "reporterCode": reporter_code,
        "period": year,
        "cmdCode": ",".join(config.COMMODITIES),
        "flowCode": ",".join(config.FLOWS),
        # Comtrade also splits every partner by "2nd partner", customs procedure and transport mode,
        # each with its own total row. Asking for only the totals avoids counting trade 2-3 times.
        "partner2Code": 0,
        "customsCode": "C00",
        "motCode": 0,
        "includeDesc": "true",
        "maxRecords": MAX_RECORDS,
    }
    for attempt in range(5):
        r = session.get(API, params=params, timeout=120)
        if r.status_code == 429:  # rate limited - back off and retry
            wait = 2 ** attempt * 5
            print(f"    rate limited, waiting {wait}s")
            time.sleep(wait)
            continue
        r.raise_for_status()
        body = r.json()
        if body.get("error"):
            raise RuntimeError(body["error"])
        return body["data"]
    raise RuntimeError("still rate limited after 5 tries")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--years", nargs="+", type=int, default=config.YEARS)
    p.add_argument("--reporters", nargs="+", default=config.REPORTERS)
    args = p.parse_args()

    load_dotenv(config.ROOT / ".env")
    key = os.getenv("COMTRADE_API_KEY")
    if not key:
        raise SystemExit("COMTRADE_API_KEY missing in .env")

    codes = reporter_codes()
    session = requests.Session()
    session.headers["Ocp-Apim-Subscription-Key"] = key

    calls = 0
    for year in args.years:
        for iso3 in args.reporters:
            out = config.BRONZE / "trade" / f"year={year}" / f"reporter={iso3}.parquet"
            if out.exists():
                print(f"skip  {year} {iso3} (already have it)")
                continue

            rows = fetch(session, codes[iso3], year)
            calls += 1
            if not rows:
                # some countries report late - not an error, just nothing published yet
                print(f"empty {year} {iso3}")
                continue
            if len(rows) >= MAX_RECORDS:
                print(f"WARN  {year} {iso3} hit the {MAX_RECORDS} row cap, data is truncated")

            df = pd.DataFrame(rows)
            df["_ingested_at"] = datetime.now(timezone.utc).isoformat()
            df["_source"] = "un_comtrade_v1"
            out.parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(out, index=False)
            print(f"saved {year} {iso3}: {len(df):>5} rows")

            time.sleep(1.5)  # be polite to the API

    print(f"done, {calls} API calls used")


if __name__ == "__main__":
    main()

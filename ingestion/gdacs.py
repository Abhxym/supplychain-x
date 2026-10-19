"""Download GDACS disaster alerts (earthquakes, cyclones, floods, volcanoes, droughts, wildfires) into bronze.

GDACS = Global Disaster Alert and Coordination System (UN + EU JRC). Public API, no key.
Output: data/bronze/events/gdacs/year=YYYY/MM.parquet

The API silently returns at most 100 events per request, so we page through
each month until a page comes back short.

    python -m ingestion.gdacs
    python -m ingestion.gdacs --years 2021
"""
import argparse
import calendar
import json
import time
from datetime import datetime, timezone

import pandas as pd
import requests

from ingestion import config

API = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"
EVENT_TYPES = "EQ;TC;FL;VO;DR;WF"
PAGE_SIZE = 100


def fetch_month(session, year, month):
    last_day = calendar.monthrange(year, month)[1]
    features, page = [], 1
    while True:
        r = session.get(API, timeout=120, params={
            "eventlist": EVENT_TYPES,
            "fromDate": f"{year}-{month:02d}-01",
            "toDate": f"{year}-{month:02d}-{last_day}",
            "alertlevel": "Green;Orange;Red",
            "pagesize": PAGE_SIZE,
            "pagenumber": page,
        })
        # past the last page GDACS answers with an empty body / 204 / 404 instead of an empty list
        if r.status_code in (204, 404) or not r.text.strip():
            break
        r.raise_for_status()
        batch = r.json().get("features", [])
        features.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        page += 1
        time.sleep(0.5)
    return features


def to_frame(features):
    rows = []
    for f in features:
        props = dict(f["properties"])
        lon, lat = f["geometry"]["coordinates"][:2]
        props["longitude"], props["latitude"] = lon, lat
        # nested bits (urls, affected countries, severity) stay as JSON text so nothing is lost
        for k, v in props.items():
            if isinstance(v, (dict, list)):
                props[k] = json.dumps(v)
        rows.append(props)
    df = pd.DataFrame(rows)
    df["_ingested_at"] = datetime.now(timezone.utc).isoformat()
    df["_source"] = "gdacs"
    return df


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--years", nargs="+", type=int, default=config.YEARS)
    args = p.parse_args()

    session = requests.Session()
    total = 0
    for year in args.years:
        for month in range(1, 13):
            out = config.BRONZE / "events" / "gdacs" / f"year={year}" / f"{month:02d}.parquet"
            if out.exists():
                print(f"skip  {year}-{month:02d}")
                continue
            features = fetch_month(session, year, month)
            if not features:
                print(f"empty {year}-{month:02d}")
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            to_frame(features).to_parquet(out, index=False)
            total += len(features)
            print(f"saved {year}-{month:02d}: {len(features):>4} events")
    print(f"done, {total} new events")


if __name__ == "__main__":
    main()

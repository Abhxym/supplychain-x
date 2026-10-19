"""Download daily historical weather for the major ports from Open-Meteo into bronze.

Open-Meteo's archive API is free with no key (ERA5 reanalysis underneath).
Output: data/bronze/weather/<wpi_number>.parquet - one file per port, all years.

Needs the ports bronze file first:  python -m ingestion.ports

    python -m ingestion.weather
"""
import time
from datetime import datetime, timezone

import pandas as pd
import requests

from ingestion import config

API = "https://archive-api.open-meteo.com/v1/archive"
DAILY = [
    "weather_code",
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "wind_speed_10m_max",
    "wind_gusts_10m_max",
]


def fetch(session, lat, lon):
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": f"{min(config.YEARS)}-01-01",
        "end_date": f"{max(config.YEARS)}-12-31",
        "daily": ",".join(DAILY),
        "timezone": "UTC",
    }
    # The free tier counts a 5-year request as many "calls", so we can hit the
    # per-minute / per-hour limit. On 429 just wait a minute and retry.
    for _ in range(70):
        r = session.get(API, params=params, timeout=120)
        if r.status_code == 429:
            print(f"    rate limited ({r.json().get('reason', '')}), waiting 60s")
            time.sleep(60)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("still rate limited after ~70 minutes")


def main():
    ports = pd.read_parquet(config.BRONZE / "ports" / "wpi.parquet")
    ports["wpi"] = ports["world_port_index_number"].astype(float).astype(int)
    ports = ports.set_index("wpi")

    out_dir = config.BRONZE / "weather"
    out_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()

    for wpi in config.MAJOR_PORTS:
        out = out_dir / f"{wpi}.parquet"
        port = ports.loc[wpi]
        if out.exists():
            print(f"skip  {wpi} {port.main_port_name}")
            continue

        body = fetch(session, float(port.latitude), float(port.longitude))
        df = pd.DataFrame(body["daily"])  # one row per day, one column per variable
        df.insert(0, "wpi_number", wpi)
        df.insert(1, "port_name", port.main_port_name)
        # Open-Meteo snaps to its grid cell, keep both so we know how far off we are
        df["port_lat"], df["port_lon"] = float(port.latitude), float(port.longitude)
        df["grid_lat"], df["grid_lon"] = body["latitude"], body["longitude"]
        df["_ingested_at"] = datetime.now(timezone.utc).isoformat()
        df["_source"] = "open_meteo_archive"
        df.to_parquet(out, index=False)
        print(f"saved {wpi} {port.main_port_name}: {len(df)} days")

        time.sleep(10)


if __name__ == "__main__":
    main()

"""Small shared loaders for the Phase 6 ML scripts.

The data here is tiny (a few MB), so plain pandas on the bronze parquet files is enough - no Spark.
Filters mirror silver_trade: imports only, real partner countries, the TOTAL rows (no transport-mode or
customs-procedure breakdowns), positive values.
"""
import glob
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent

# Comtrade codes Taiwan as "Other Asia, nes" (S19); the graph calls it TWN
PARTNER_FIX = {"S19": "TWN"}


def trade_imports():
    """One row per reporter x partner x HS2 x year with the import value in USD."""
    cols = ["refYear", "reporterISO", "flowCode", "partnerISO", "partner2Code", "motCode", "customsCode",
            "cmdCode", "primaryValue"]
    files = glob.glob(str(ROOT / "data" / "bronze" / "trade" / "**" / "*.parquet"), recursive=True)
    d = pd.concat(pd.read_parquet(f, columns=cols) for f in files)
    d = d[(d.flowCode == "M") & (d.partner2Code == 0) & (d.motCode == 0) & (d.customsCode == "C00")
          & (d.primaryValue > 0)]
    d["partnerISO"] = d.partnerISO.replace(PARTNER_FIX)
    # drop World and the Comtrade group codes (areas nes, bunkers, free zones ...)
    d = d[d.partnerISO.str.fullmatch(r"[A-Z]{3}") & ~d.partnerISO.str.match(r"^(W00|X|_)")]
    d = (d.groupby(["refYear", "reporterISO", "partnerISO", "cmdCode"], as_index=False).primaryValue.sum()
           .rename(columns={"refYear": "year", "reporterISO": "reporter", "partnerISO": "partner",
                            "cmdCode": "hs2", "primaryValue": "value_usd"}))
    return d


def ports():
    with open(ROOT / "data" / "graph" / "ports.json", encoding="utf-8") as f:
        return pd.DataFrame(json.load(f))


def port_weather():
    """Daily weather for the 45 major ports, with the port's country."""
    p = ports()[["wpi_number", "iso3"]]
    files = glob.glob(str(ROOT / "data" / "bronze" / "weather" / "*.parquet"))
    cols = ["wpi_number", "port_name", "time", "precipitation_sum", "wind_gusts_10m_max",
            "wind_speed_10m_max", "temperature_2m_max", "temperature_2m_min"]
    w = pd.concat(pd.read_parquet(f, columns=cols) for f in files)
    return w.merge(p, on="wpi_number", how="left")


def events():
    with open(ROOT / "data" / "replay" / "events.jsonl", encoding="utf-8") as f:
        return [json.loads(line) for line in f]

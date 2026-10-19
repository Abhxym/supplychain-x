"""SUPPLYCHAIN-X API + the Cascade Explorer UI.

    uvicorn api.main:app --port 8000
    open http://localhost:8000          (UI)   http://localhost:8000/docs   (API docs)

GET  /api/events          events the engine has scored, highest impact first
GET  /api/impact/{id}     full cascade for one event
POST /api/simulate        what-if: pick countries, severity, duration -> cascade
GET  /api/countries       countries in the graph with centrality and coordinates (for the map)
GET  /api/anomalies       unusual trade drops from Isolation Forest (Phase 6), optionally for some countries
"""
import json
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from impact.engine import _neo4j, simulate
from impact.run_events import connect

ROOT = Path(__file__).resolve().parent.parent
app = FastAPI(title="SUPPLYCHAIN-X", description="Supply-chain disruption intelligence and cascading impact")
app.mount("/static", StaticFiles(directory=ROOT / "ui"), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(ROOT / "ui" / "index.html")


@lru_cache(maxsize=1)
def iso_numeric():
    """ISO3 -> ISO numeric code, which is how the world map identifies countries.
    Comtrade lists the ISO code plus its own variants (USA 840 and 842): the lowest is the ISO one.
    India only appears as 699 there; its ISO code is 356."""
    with open(ROOT / "data" / "bronze" / "reference" / "partners.json", encoding="utf-8") as f:
        partners = json.load(f)["results"]
    codes = {}
    for p in partners:
        if not p["isGroup"] and p.get("entryExpiredDate") is None:
            iso3 = p["PartnerCodeIsoAlpha3"]
            codes[iso3] = min(codes.get(iso3, 9999), p["PartnerCode"])
    codes["IND"] = 356
    return {k: str(v).zfill(3) for k, v in codes.items()}


@app.get("/api/countries")
def countries():
    with _neo4j().session() as s:
        rows = s.run("""MATCH (c:Country)
                        OPTIONAL MATCH (p:Port)-[:LOCATED_IN]->(c)
                        RETURN c.iso3 AS iso3, c.name AS name, c.betweenness_norm AS centrality,
                               c.supply_strength AS supply_strength, c.community AS community,
                               c.is_reporter AS is_reporter,
                               avg(p.latitude) AS port_lat, avg(p.longitude) AS port_lon,
                               collect(p.name) AS ports
                        ORDER BY c.name""").data()
    codes = iso_numeric()
    for r in rows:
        r["numeric"] = codes.get(r["iso3"])
    return rows


@app.get("/api/events")
def events(limit: int = 200, q: Optional[str] = None):
    sql = """SELECT event_id, result->'event'->>'title', result->'event'->>'alert_level',
                    result->'event'->>'event_type', result->'event'->>'start_ts',
                    (result->'parameters'->>'severity_in')::float, (result->'parameters'->>'severity_used')::float,
                    max_score, countries, result->'event'->'countries'
             FROM impact_runs {} ORDER BY max_score DESC LIMIT %s"""
    with connect() as db:
        if q:
            rows = db.execute(sql.format("WHERE result->'event'->>'title' ILIKE %s"), ("%" + q + "%", limit)).fetchall()
        else:
            rows = db.execute(sql.format(""), (limit,)).fetchall()
    keys = ["event_id", "title", "alert_level", "event_type", "start_ts", "severity_in", "severity_used",
            "max_score", "countries", "sources"]
    return [dict(zip(keys, r)) for r in rows]


@app.get("/api/impact/{event_id}")
def impact(event_id: str):
    with connect() as db:
        row = db.execute("SELECT result FROM impact_runs WHERE event_id = %s", (event_id,)).fetchone()
    if not row:
        raise HTTPException(404, "no impact run for " + event_id)
    return row[0]


@lru_cache(maxsize=1)
def _stats():
    """Dashboard-wide numbers: weekly disaster intensity and monthly severe port-weather days."""
    import pandas as pd

    ev = pd.read_json(ROOT / "data" / "replay" / "events.jsonl", lines=True)
    ev["week"] = pd.to_datetime(ev["start_ts"]).dt.to_period("W").dt.start_time.dt.strftime("%Y-%m-%d")
    ev["serious"] = ev["alert_level"].isin(["Orange", "Red"])
    weekly = ev.groupby("week").agg(all=("event_key", "size"), serious=("serious", "sum")).reset_index()

    frames = [pd.read_parquet(f, columns=["time", "precipitation_sum", "wind_gusts_10m_max"])
              for f in (ROOT / "data" / "bronze" / "weather").glob("*.parquet")]
    w = pd.concat(frames)
    w["severe"] = (w.precipitation_sum >= 115.6) | (w.wind_gusts_10m_max >= 89)
    monthly = w.groupby(w.time.str[:7]).severe.sum().reset_index().rename(columns={"time": "month", "severe": "days"})

    with connect() as db:
        boosted = db.execute("""SELECT count(*) FROM impact_runs WHERE (result->'parameters'->>'severity_used')::float
                                > (result->'parameters'->>'severity_in')::float""").fetchone()[0]
        scored = db.execute("SELECT count(*) FROM impact_runs").fetchone()[0]
    levels = ev["alert_level"].value_counts().to_dict()
    return {
        "total_events": int(len(ev)),
        "levels": {k: int(levels.get(k, 0)) for k in ("Green", "Orange", "Red")},
        "weather_boosted": int(boosted), "scored": int(scored),
        "weekly": weekly.astype({"all": int, "serious": int}).to_dict("records"),
        "monthly_severe": monthly.astype({"days": int}).to_dict("records"),
    }


@app.get("/api/stats")
def stats():
    return _stats()


@app.get("/api/anomalies")
def anomalies(limit: int = 12, countries: Optional[str] = None):
    """Unusual import drops found by Isolation Forest (python -m ml.anomalies), strangest first.
    countries=CHN,JPN keeps the drops where the importer or the supplier is one of them."""
    sql = """SELECT a.year, a.reporter, r.country_name, a.partner, p.country_name, a.hs2, c.commodity_name,
                    a.value_prev::float, a.value::float, a.dshare, a.score
             FROM ml_trade_anomalies a
             LEFT JOIN countries r ON r.iso3 = a.reporter
             LEFT JOIN countries p ON p.iso3 = a.partner
             LEFT JOIN commodities c ON c.hs_code = a.hs2
             {} ORDER BY a.score DESC LIMIT %s"""
    codes = [c.strip().upper() for c in (countries or "").split(",") if c.strip()]
    with connect() as db:
        if codes:
            rows = db.execute(sql.format("WHERE a.reporter = ANY(%s) OR a.partner = ANY(%s)"),
                              (codes, codes, limit)).fetchall()
            total = db.execute("SELECT count(*) FROM ml_trade_anomalies WHERE reporter = ANY(%s) OR partner = ANY(%s)",
                               (codes, codes)).fetchone()[0]
        else:
            rows = db.execute(sql.format(""), (limit,)).fetchall()
            total = db.execute("SELECT count(*) FROM ml_trade_anomalies").fetchone()[0]
    keys = ["year", "importer", "importer_name", "supplier", "supplier_name", "hs2", "product",
            "value_before", "value_after", "share_change", "score"]
    items = [dict(zip(keys, r)) for r in rows]
    for it in items:
        it["change"] = it["value_after"] / it["value_before"] - 1
    return {"total": total, "items": items}


class Simulation(BaseModel):
    countries: List[str] = Field(..., examples=[["CHN"]])
    severity: float = Field(0.8, ge=0, le=1)
    duration_days: int = Field(14, ge=1, le=365)
    decay: float = Field(0.6, gt=0, le=1)
    min_share: float = Field(0.05, ge=0.01, le=0.5)
    weights: Optional[dict] = None


@app.post("/api/simulate")
def run_simulation(sim: Simulation):
    if not sim.countries:
        raise HTTPException(400, "pick at least one country")
    return simulate(sim.countries, severity=sim.severity, duration_days=sim.duration_days,
                    decay=sim.decay, min_share=sim.min_share, weights=sim.weights)

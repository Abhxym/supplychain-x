"""Cascading impact engine.

Given a disruption (which countries are hit, how badly, for how long), follow the supply links in
Neo4j outward hop by hop and score every country - and the industries in it - that depends on what
was hit.

    from impact.engine import simulate
    simulate(["CHN"], severity=0.8, duration_days=14)

Impact score (weights are configurable parameters, not universal truths):

    ImpactScore = (w1*S + w2*D + w3*E + w4*C + w5*T) * decay^hop

    S  severity of the event, 0..1 (raised to >= 0.8 if our own weather data shows storm-force winds
       or very heavy rain at a major port in the hit country during the event)
    D  dependency: the strongest chain of shares from the hit country to this one
       (CHN supplies 58% of IND electronics -> 0.58; one hop further, 0.58 x the next share)
    E  exposure: dollar value of the imports at risk, log-scaled to 0..1 within this result
    C  centrality: the country's normalised betweenness from graph.algorithms
    T  temporal persistence: duration / 30 days, capped at 1
    decay  each hop away keeps only part of the impact (default 0.6)

A cascade follows ONE product at a time: a shortage of Chinese electronics hits India's electronics
imports, and from there India's electronics exports - it does not jump from electronics to cereals.
"""
import math
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from graph.load_neo4j import driver

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WEIGHTS = {"severity": 0.30, "dependency": 0.30, "exposure": 0.15, "centrality": 0.10, "duration": 0.15}

CASCADE = """
MATCH p = (s:Country)-[rels:SUPPLIES*1..3]->(t:Country)
WHERE s.iso3 IN $sources AND NOT t.iso3 IN $sources
  AND all(r IN rels WHERE r.share >= $min_share AND r.hs2 = head(rels).hs2)
  AND size(apoc.coll.toSet(nodes(p))) = length(p) + 1
WITH t, p, rels, reduce(d = 1.0, r IN rels | d * r.share) AS dep
WITH t, head(rels).hs2 AS hs2, head(rels).product AS product, p, dep, last(rels).value_usd AS value
ORDER BY dep DESC
WITH t, hs2, product, collect({path: [n IN nodes(p) | n.iso3],
                               shares: [r IN relationships(p) | r.share], dep: dep, value: value})[0] AS best
RETURN t.iso3 AS iso3, t.name AS name, t.betweenness_norm AS centrality, t.community AS community,
       hs2, product, best.dep AS dependency, best.value AS value_usd, best.path AS path, best.shares AS shares
"""

CASCADE_NO_APOC = CASCADE.replace("AND size(apoc.coll.toSet(nodes(p))) = length(p) + 1",
                                  "AND all(n IN nodes(p) WHERE single(m IN nodes(p) WHERE m = n))")

SOURCES = """
MATCH (c:Country) WHERE c.iso3 IN $sources
OPTIONAL MATCH (port:Port)-[:LOCATED_IN]->(c)
RETURN c.iso3 AS iso3, c.name AS name, c.betweenness_norm AS centrality,
       collect(port {.wpi, .name, .latitude, .longitude}) AS ports
"""

INDUSTRIES = "MATCH (p:Product)-[:USED_BY]->(i:Industry) RETURN p.hs2 AS hs2, collect(i.name) AS industries"


_driver = None


def _neo4j():
    # one connection pool for the whole process - opening a new one per simulation costs seconds
    global _driver
    if _driver is None:
        _driver = driver()
    return _driver


_weather_cache = {}


def _weather(wpi):
    if wpi not in _weather_cache:
        f = ROOT / "data" / "bronze" / "weather" / "{}.parquet".format(wpi)
        _weather_cache[wpi] = (pd.read_parquet(f, columns=["time", "precipitation_sum", "wind_gusts_10m_max"])
                               if f.exists() else None)
    return _weather_cache[wpi]


def weather_evidence(ports, start, end):
    """Severe days at the hit country's major ports during the event, from our own weather data.
    Same thresholds as silver_weather: >= 115.6 mm rain or >= 89 km/h gusts."""
    if not ports or not start:
        return []
    end = end or start
    found = []
    for port in ports:
        w = _weather(port["wpi"])
        if w is None:
            continue
        w = w[(w.time >= str(start)) & (w.time <= str(end))]
        bad = w[(w.precipitation_sum >= 115.6) | (w.wind_gusts_10m_max >= 89)]
        for _, r in bad.iterrows():
            found.append({"port": port["name"], "date": r.time, "gust_kmh": round(float(r.wind_gusts_10m_max)),
                          "rain_mm": round(float(r.precipitation_sum))})
    return found


def simulate(sources, severity=0.6, duration_days=7, start=None, end=None, weights=None,
             decay=0.6, min_share=0.05, max_results=40):
    w = dict(DEFAULT_WEIGHTS, **(weights or {}))
    total = sum(w.values())
    w = {k: v / total for k, v in w.items()}  # keep the weights summing to 1
    sources = [s.upper() for s in sources]

    with _neo4j().session() as s:
        src_rows = s.run(SOURCES, sources=sources).data()
        try:
            rows = s.run(CASCADE, sources=sources, min_share=min_share).data()
        except Exception:  # APOC not installed - same result, slower path check
            rows = s.run(CASCADE_NO_APOC, sources=sources, min_share=min_share).data()
        industries = {r["hs2"]: r["industries"] for r in s.run(INDUSTRIES).data()}

    ports = [p for r in src_rows for p in r["ports"]]
    evidence = weather_evidence(ports, start, end)
    S = max(severity, 0.8) if evidence else severity
    T = min(duration_days / 30.0, 1.0)
    max_log = max([math.log1p(r["value_usd"] or 0) for r in rows] or [1.0]) or 1.0

    # one row per country x product; keep the product chains, then roll up to the country
    by_country = {}
    for r in rows:
        hop = len(r["path"]) - 1
        D, C = r["dependency"], r["centrality"] or 0.0
        E = math.log1p(r["value_usd"] or 0) / max_log
        score = (w["severity"] * S + w["dependency"] * D + w["exposure"] * E +
                 w["centrality"] * C + w["duration"] * T) * decay ** hop
        chain = {"hs2": r["hs2"], "product": r["product"], "path": r["path"], "shares": r["shares"],
                 "hop": hop, "dependency": round(D, 4), "value_usd": r["value_usd"], "score": round(score, 4),
                 "components": {"S": round(S, 3), "D": round(D, 3), "E": round(E, 3),
                                "C": round(C, 3), "T": round(T, 3)},
                 "industries": industries.get(r["hs2"], [])}
        c = by_country.setdefault(r["iso3"], {"iso3": r["iso3"], "name": r["name"], "community": r["community"],
                                              "centrality": round(C, 3), "chains": []})
        c["chains"].append(chain)

    affected = []
    for c in by_country.values():
        c["chains"].sort(key=lambda x: -x["score"])
        top = c["chains"][0]
        c.update(score=top["score"], hop=top["hop"], dependency=top["dependency"],
                 exposure_usd=sum(x["value_usd"] or 0 for x in c["chains"]))
        affected.append(c)
    affected.sort(key=lambda x: -x["score"])

    # industries: per affected country, the industries using its most exposed products
    industry_hits = {}
    for c in affected:
        for ch in c["chains"]:
            for ind in ch["industries"]:
                key = (c["iso3"], ind)
                if ch["score"] > industry_hits.get(key, {}).get("score", 0):
                    industry_hits[key] = {"iso3": c["iso3"], "industry": ind, "product": ch["product"],
                                          "score": ch["score"], "hop": ch["hop"]}
    top_industries = sorted(industry_hits.values(), key=lambda x: -x["score"])[:15]

    return {
        "sources": [{"iso3": r["iso3"], "name": r["name"], "centrality": round(r["centrality"] or 0, 3),
                     "ports": r["ports"]} for r in src_rows],
        "parameters": {"severity_in": severity, "severity_used": S, "duration_days": duration_days,
                       "weights": w, "decay": decay, "min_share": min_share},
        "weather_evidence": evidence,
        "summary": {"countries": len(affected), "max_hop": max([c["hop"] for c in affected] or [0]),
                    "high": sum(1 for c in affected if c["score"] >= 0.5),
                    "products": sorted({ch["product"] for c in affected for ch in c["chains"]}),
                    "exposure_usd": sum(c["exposure_usd"] for c in affected)},
        "affected": affected[:max_results],
        "industries": top_industries,
    }


def severity_for(alert_level):
    return {"Red": 1.0, "Orange": 0.6}.get(alert_level, 0.3)


def simulate_event(event):
    """Run the engine for one GDACS event (a row from data/replay/events.jsonl)."""
    start = event["start_ts"][:10]
    end = (event.get("end_ts") or event["start_ts"])[:10]
    days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    result = simulate(event["countries"], severity=severity_for(event["alert_level"]),
                      duration_days=days, start=start, end=end)
    result["event"] = {k: event.get(k) for k in ("event_key", "event_type", "alert_level", "title",
                                                  "start_ts", "end_ts", "latitude", "longitude", "countries")}
    return result

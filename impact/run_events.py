"""Run the impact engine over historical events and store the results in Postgres.

    python -m impact.run_events            # every Orange/Red event + every tropical cyclone, 2019-2023

Cyclones are all included because GDACS can under-rate them (it called Typhoon Hagibis "Green");
the engine's weather check decides how bad they were.

Writes per event:
    events        the event itself (if not there yet)
    impact_scores one row per affected country and industry (replaced on rerun)
    impact_runs   the full engine output as JSON, for the UI
"""
import json
import os
import time
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from impact.engine import severity_for, simulate_event

ROOT = Path(__file__).resolve().parent.parent


def connect():
    load_dotenv(ROOT / ".env")
    return psycopg.connect(host="localhost", port=os.getenv("POSTGRES_PORT", "5433"),
                           user=os.getenv("POSTGRES_USER"), password=os.getenv("POSTGRES_PASSWORD"),
                           dbname=os.getenv("POSTGRES_DB"))


def main():
    with open(ROOT / "data" / "replay" / "events.jsonl", encoding="utf-8") as f:
        events = [json.loads(line) for line in f]
    chosen = [e for e in events if e["countries"] and (e["alert_level"] in ("Orange", "Red") or e["event_type"] == "TC")]
    print("running the engine on {} events".format(len(chosen)))

    t0 = time.time()
    with connect() as db:
        db.execute((ROOT / "db" / "init" / "002_impact_runs.sql").read_text())
        ids = dict(db.execute("SELECT iso3, country_id FROM countries").fetchall())
        stored, boosted = 0, 0
        for e in chosen:
            r = simulate_event(e)
            key = e["event_key"]
            db.execute("""INSERT INTO events (event_id, ts, event_type, country_id, latitude, longitude, severity, source)
                          VALUES (%s, %s, %s, %s, %s, %s, %s, 'gdacs') ON CONFLICT (event_id) DO NOTHING""",
                       (key, e["start_ts"], e["event_type"], ids.get(e["countries"][0]), e["latitude"],
                        e["longitude"], severity_for(e["alert_level"])))
            db.execute("DELETE FROM impact_scores WHERE event_id = %s", (key,))
            rows = [(key, "country", c["iso3"], c["hop"], c["chains"][0]["components"]["E"], c["centrality"], c["score"])
                    for c in r["affected"]]
            rows += [(key, "industry", "{}:{}".format(i["iso3"], i["industry"]), i["hop"], None, None, i["score"])
                     for i in r["industries"]]
            with db.cursor() as cur:
                cur.executemany("""INSERT INTO impact_scores (event_id, entity_type, entity_id, hop_level,
                                   exposure_score, centrality_score, impact_score) VALUES (%s,%s,%s,%s,%s,%s,%s)""", rows)
            db.execute("""INSERT INTO impact_runs (event_id, result, max_score, countries) VALUES (%s, %s, %s, %s)
                          ON CONFLICT (event_id) DO UPDATE SET result = EXCLUDED.result, max_score = EXCLUDED.max_score,
                          countries = EXCLUDED.countries, created_at = now()""",
                       (key, json.dumps(r), max([c["score"] for c in r["affected"]] or [0]), len(r["affected"])))
            stored += 1
            boosted += bool(r["weather_evidence"]) and r["parameters"]["severity_in"] < r["parameters"]["severity_used"]
        db.commit()
    print("stored {} events in {:.0f}s; weather data raised the severity of {}".format(stored, time.time() - t0, boosted))


if __name__ == "__main__":
    main()

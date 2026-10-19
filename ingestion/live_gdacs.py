"""Live disasters: poll GDACS for current events and send them into Kafka.

    python -m ingestion.live_gdacs                 # every 10 minutes, until Ctrl+C
    python -m ingestion.live_gdacs --once          # one poll, then stop (good for a demo or a test)
    python -m ingestion.live_gdacs --no-score      # only Kafka, don't run the impact engine

Same topic and the same message format as the replay producer, so the Spark streaming job, the
alerts table and the dashboard need no changes: messages just carry "feed": "gdacs-live".

What counts as new: an event we have not sent before, OR one whose alert level / episode changed
(cyclones are often upgraded Green -> Orange -> Red as they grow). What we already sent is kept in
data/live/sent.json, so a restart does not resend everything.

Serious events (Orange/Red with a country, every cyclone) are also scored by the impact engine and
stored like the historical ones, so they appear in the dashboard's event picker.
"""
import argparse
import json
import os
import time
from datetime import date, datetime, timedelta, timezone

import requests
from confluent_kafka import Producer
from dotenv import load_dotenv

from ingestion.config import ROOT
from ingestion.gdacs import API, EVENT_TYPES, PAGE_SIZE

TOPIC = "supplychain.events"
STATE = ROOT / "data" / "live" / "sent.json"


def fetch(days):
    """Every GDACS event that started in the last `days` days (paged: the API returns at most 100)."""
    today = date.today()
    features, page = [], 1
    while True:
        r = requests.get(API, timeout=60, params={
            "eventlist": EVENT_TYPES, "alertlevel": "Green;Orange;Red", "pagesize": PAGE_SIZE, "pagenumber": page,
            "fromDate": str(today - timedelta(days=days)), "toDate": str(today + timedelta(days=1))})
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


def to_message(f):
    """A GDACS feature -> the same fields silver_events + export_replay produce for the replay."""
    p = f["properties"]
    lon, lat = f["geometry"]["coordinates"][:2]
    sev = p.get("severitydata") or {}
    countries = sorted({c["iso3"] for c in (p.get("affectedcountries") or []) if c.get("iso3")})
    if not countries and p.get("iso3"):
        countries = [p["iso3"]]
    start, end = p["fromdate"], p.get("todate") or p["fromdate"]
    if end < start:  # GDACS sometimes ends an event before it starts (see silver_events)
        end = start
    return {
        "event_key": "{}-{}".format(p["eventtype"], p["eventid"]),
        "event_type": p["eventtype"],
        "alert_level": (p.get("alertlevel") or "Green").strip().capitalize(),
        "alert_score": p.get("alertscore"),
        "severity_value": sev.get("severity"),
        "severity_unit": sev.get("severityunit"),
        "title": p.get("name"),
        "start_ts": start, "end_ts": end,
        "latitude": lat, "longitude": lon,
        "countries": countries,
        "feed": "gdacs-live",
        "episode": p.get("episodeid"),
    }


def load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(sent):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(sent), encoding="utf-8")


def poll(producer, sent, days, score):
    try:
        messages = [to_message(f) for f in fetch(days)]
    except requests.RequestException as e:  # GDACS down or no internet: try again next round
        print("  GDACS not reachable ({}), will retry".format(type(e).__name__))
        return 0
    new = []
    for m in messages:
        version = "{}/{}".format(m["alert_level"], m["episode"])
        if sent.get(m["event_key"]) != version:
            m["fetched_at"] = datetime.now(timezone.utc).isoformat()
            producer.produce(TOPIC, key=m["event_key"], value=json.dumps(m).encode())
            sent[m["event_key"]] = version
            new.append(m)
    producer.flush()
    save_state(sent)

    for m in new:
        if m["alert_level"] != "Green" or m["event_type"] == "TC":
            print("  {}  {:<6} {:<45} {}".format(m["start_ts"][:10], m["alert_level"], (m["title"] or "")[:45],
                                                ",".join(m["countries"][:4])))
    if score and new:
        from impact.run_events import connect, store, worth_scoring  # needs Neo4j; only loaded when scoring
        serious = [m for m in new if worth_scoring(m)]
        if serious:
            with connect() as db:
                ids = dict(db.execute("SELECT iso3, country_id FROM countries").fetchall())
                for m in serious:
                    store(db, m, ids, source="gdacs-live")
                db.commit()
            print("  scored {} serious events with the impact engine".format(len(serious)))
    return len(new)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--every", type=int, default=600, help="seconds between polls (default 10 min)")
    p.add_argument("--days", type=int, default=7, help="look back this many days")
    p.add_argument("--once", action="store_true", help="poll once and stop")
    p.add_argument("--no-score", dest="score", action="store_false", help="don't run the impact engine")
    args = p.parse_args()

    load_dotenv(ROOT / ".env")
    producer = Producer({"bootstrap.servers": os.getenv("KAFKA_BOOTSTRAP", "localhost:9092"),
                         "enable.idempotence": True})
    sent = load_state()
    print("live GDACS -> {} every {} s (last {} days); {} events already sent before".format(
        TOPIC, args.every, args.days, len(sent)))
    while True:
        n = poll(producer, sent, args.days, args.score)
        print("{}  {} new or updated events sent".format(datetime.now().strftime("%H:%M:%S"), n), flush=True)
        if args.once:
            break
        time.sleep(args.every)


if __name__ == "__main__":
    main()

"""API tests: every endpoint answers, with the right shape and sensible values.

    python -m pytest -q

These are integration tests - they talk to the real Postgres and Neo4j, so `docker compose up -d` first.
If the databases can't be reached the whole file is skipped instead of failing.
"""
import pytest
from fastapi.testclient import TestClient

from api.main import _parse_alert, app

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def services_up():
    try:
        client.get("/api/alerts?limit=1").raise_for_status()
        client.get("/api/graph/CHN").raise_for_status()
    except Exception as e:  # connection refused, missing table ...
        pytest.skip("Postgres/Neo4j not reachable - run `docker compose up -d` ({})".format(type(e).__name__))


def test_parse_alert_splits_the_message():
    a = _parse_alert("Flood in China (Red) | why: GDACS Red | countries: CHN,VNM | downstream: IND gets 58% of ...")
    assert a["title"] == "Flood in China (Red)"
    assert a["why"] == "GDACS Red"
    assert a["countries"] == ["CHN", "VNM"]
    assert a["downstream"].startswith("IND")


def test_countries_have_codes_for_the_map():
    rows = client.get("/api/countries").json()
    assert len(rows) >= 100
    china = next(r for r in rows if r["iso3"] == "CHN")
    assert china["numeric"] == "156" and china["is_reporter"]


def test_events_are_sorted_by_impact():
    rows = client.get("/api/events?limit=20").json()
    assert 0 < len(rows) <= 20
    scores = [r["max_score"] for r in rows]
    assert scores == sorted(scores, reverse=True)


def test_event_search():
    rows = client.get("/api/events?q=HAGIBIS").json()
    assert rows and all("HAGIBIS" in r["title"] for r in rows)


def test_impact_of_a_scored_event():
    r = client.get("/api/impact/TC-1000611").json()  # Typhoon Hagibis
    assert r["event"]["title"].startswith("Tropical Cyclone HAGIBIS")
    assert r["parameters"]["severity_used"] >= r["parameters"]["severity_in"]
    assert all(0 <= c["score"] <= 1 for c in r["affected"])


def test_impact_of_unknown_event_is_404():
    assert client.get("/api/impact/NOPE-1").status_code == 404


def test_simulate_china():
    r = client.post("/api/simulate", json={"countries": ["CHN"], "severity": 0.8, "duration_days": 14}).json()
    assert r["sources"][0]["iso3"] == "CHN"
    assert r["summary"]["countries"] > 0
    assert "CHN" not in {c["iso3"] for c in r["affected"]}  # the hit country is not its own victim
    hop1 = [c for c in r["affected"] if c["hop"] == 1]
    assert hop1 and hop1[0]["dependency"] > 0


def test_simulate_needs_a_country():
    assert client.post("/api/simulate", json={"countries": []}).status_code == 400


def test_simulate_rejects_bad_severity():
    assert client.post("/api/simulate", json={"countries": ["CHN"], "severity": 2}).status_code == 422


def test_stats():
    s = client.get("/api/stats").json()
    assert 0 < sum(s["levels"].values()) <= s["total_events"]
    assert s["weather_boosted"] <= s["scored"]
    assert s["weekly"] and s["monthly_severe"]


def test_alerts_newest_first_and_after_filter():
    data = client.get("/api/alerts?limit=5").json()
    ids = [a["id"] for a in data["items"]]
    assert ids == sorted(ids, reverse=True)
    if ids:
        newer = client.get("/api/alerts?after={}".format(ids[0])).json()
        assert newer["items"] == []          # nothing is newer than the newest
        assert all(a["severity"] in ("LOW", "MEDIUM", "HIGH") for a in data["items"])


def test_graph_of_japan():
    g = client.get("/api/graph/jpn?limit=5").json()  # lower case works too
    assert g["country"]["iso3"] == "JPN"
    for side in ("suppliers", "customers"):
        assert 0 < len(g[side]) <= 5
        shares = [p["share"] for p in g[side]]
        assert shares == sorted(shares, reverse=True) and all(0 < s <= 1 for s in shares)


def test_graph_of_unknown_country_is_404():
    assert client.get("/api/graph/XXX").status_code == 404


def test_anomalies_and_country_filter():
    allx = client.get("/api/anomalies?limit=5").json()
    assert allx["total"] > 0 and len(allx["items"]) == 5
    assert all(a["change"] < 0 for a in allx["items"])  # only drops are stored
    jpn = client.get("/api/anomalies?countries=JPN").json()
    assert all("JPN" in (a["importer"], a["supplier"]) for a in jpn["items"])


def test_anomalies_year_filter():
    d = client.get("/api/anomalies?countries=CHN&years=2021,2022").json()
    assert d["total"] > 0
    assert all(a["year"] in (2021, 2022) and "CHN" in (a["importer"], a["supplier"]) for a in d["items"])


def test_live_gdacs_message_matches_the_replay_format():
    from ingestion.live_gdacs import to_message
    f = {"geometry": {"type": "Point", "coordinates": [139.7, 35.6]},
         "properties": {"eventtype": "TC", "eventid": 1001338, "episodeid": 7, "alertlevel": "RED", "alertscore": 3,
                        "name": "Tropical Cyclone TEST", "fromdate": "2026-10-14T00:00:00", "todate": "2026-10-10T00:00:00",
                        "iso3": "JPN", "affectedcountries": [{"iso3": "JPN"}, {"iso3": "GUM"}],
                        "severitydata": {"severity": 180, "severityunit": "km/h"}}}
    m = to_message(f)
    replay_keys = {"event_key", "event_type", "alert_level", "alert_score", "severity_value", "severity_unit",
                   "title", "start_ts", "end_ts", "latitude", "longitude", "countries"}
    assert replay_keys <= set(m)
    assert m["event_key"] == "TC-1001338" and m["alert_level"] == "Red" and m["feed"] == "gdacs-live"
    assert m["countries"] == ["GUM", "JPN"] and (m["latitude"], m["longitude"]) == (35.6, 139.7)
    assert m["end_ts"] == m["start_ts"]  # an end before the start is clamped, like silver_events does

"""Demo and Offline Standalone Data Provider for SUPPLYCHAIN-X.
Author: Sagar

Provides high-fidelity, verified offline fallback data for the dashboard
so that the entire UI (dot-matrix world map, animated supply cascades,
gauges, industry matrix, anomaly cards, live alerts, What-If simulator,
and guided tour) can be explored seamlessly even without Docker containers running.
"""
import csv
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Standard ISO3 to numeric code mapping for TopoJSON world atlas
ISO_NUMERIC = {
    "AFG": "004", "ALB": "008", "DZA": "012", "AGO": "024", "ARG": "032",
    "ARM": "051", "AUS": "036", "AUT": "040", "AZE": "031", "BHS": "044",
    "BGD": "050", "BLR": "112", "BEL": "056", "BLZ": "084", "BEN": "204",
    "BTN": "064", "BOL": "068", "BIH": "070", "BWA": "072", "BRA": "076",
    "BRN": "096", "BGR": "100", "BFA": "854", "BDI": "108", "KHM": "116",
    "CMR": "120", "CAN": "124", "CAF": "140", "TCD": "148", "CHL": "152",
    "CHN": "156", "COL": "170", "COG": "178", "COD": "180", "CRI": "188",
    "CIV": "384", "HRV": "191", "CUB": "192", "CYP": "196", "CZE": "203",
    "DNK": "208", "DJI": "262", "DOM": "214", "ECU": "218", "EGY": "818",
    "SLV": "222", "GNQ": "226", "ERI": "232", "EST": "233", "ETH": "231",
    "FIN": "246", "FRA": "250", "GAB": "266", "GMB": "270", "GEO": "268",
    "DEU": "276", "GHA": "288", "GRC": "300", "GTM": "320", "GIN": "324",
    "GNB": "624", "GUY": "328", "HTI": "332", "HND": "340", "HUN": "348",
    "ISL": "352", "IND": "356", "IDN": "360", "IRN": "364", "IRQ": "368",
    "IRL": "372", "ISR": "376", "ITA": "380", "JAM": "388", "JPN": "392",
    "JOR": "400", "KAZ": "398", "KEN": "404", "PRK": "408", "KOR": "410",
    "KWT": "414", "KGZ": "417", "LAO": "418", "LVA": "428", "LBN": "422",
    "LSO": "426", "LBR": "430", "LBY": "434", "LTU": "440", "LUX": "442",
    "MKD": "807", "MDG": "450", "MWI": "454", "MYS": "458", "MLI": "466",
    "MRT": "478", "MEX": "484", "MDA": "498", "MNG": "496", "MNE": "499",
    "MAR": "504", "MOZ": "508", "MMR": "104", "NAM": "516", "NPL": "524",
    "NLD": "528", "NZL": "554", "NIC": "558", "NER": "562", "NGA": "566",
    "NOR": "578", "OMN": "512", "PAK": "586", "PAN": "591", "PNG": "598",
    "PRY": "600", "PER": "604", "PHL": "608", "POL": "616", "PRT": "620",
    "QAT": "634", "ROU": "642", "RUS": "643", "RWA": "646", "SAU": "682",
    "SEN": "686", "SRB": "688", "SLE": "694", "SGP": "702", "SVK": "703",
    "SVN": "705", "SOM": "706", "ZAF": "710", "ESP": "724", "LKA": "144",
    "SDN": "729", "SUR": "740", "SWZ": "748", "SWE": "752", "CHE": "756",
    "SYR": "760", "TWN": "158", "TJK": "762", "TZA": "834", "THA": "764",
    "TGO": "768", "TTO": "780", "TUN": "788", "TUR": "792", "TKM": "795",
    "UGA": "800", "UKR": "804", "ARE": "784", "GBR": "826", "USA": "840",
    "URY": "858", "UZB": "860", "VEN": "862", "VNM": "704", "YEM": "887",
    "ZMB": "894", "ZWE": "716"
}

BASE_COUNTRIES = [
    {"iso3": "USA", "name": "United States", "centrality": 0.50, "supply_strength": 5.50, "community": 2, "is_reporter": True, "port_lat": 33.74, "port_lon": -118.26, "ports": ["Los Angeles", "Long Beach", "New York", "Houston", "Savannah"]},
    {"iso3": "CHN", "name": "China", "centrality": 1.00, "supply_strength": 7.86, "community": 1, "is_reporter": True, "port_lat": 31.23, "port_lon": 121.50, "ports": ["Shanghai", "Ningbo", "Shenzhen", "Guangzhou", "Qingdao", "Tianjin"]},
    {"iso3": "DEU", "name": "Germany", "centrality": 0.28, "supply_strength": 3.73, "community": 0, "is_reporter": True, "port_lat": 53.54, "port_lon": 9.99, "ports": ["Hamburg", "Bremerhaven"]},
    {"iso3": "JPN", "name": "Japan", "centrality": 0.18, "supply_strength": 2.94, "community": 1, "is_reporter": True, "port_lat": 35.65, "port_lon": 139.75, "ports": ["Tokyo", "Yokohama", "Kobe"]},
    {"iso3": "KOR", "name": "South Korea", "centrality": 0.16, "supply_strength": 2.45, "community": 1, "is_reporter": True, "port_lat": 35.10, "port_lon": 129.04, "ports": ["Busan"]},
    {"iso3": "IND", "name": "India", "centrality": 0.15, "supply_strength": 2.10, "community": 3, "is_reporter": True, "port_lat": 18.95, "port_lon": 72.95, "ports": ["Nhava Sheva", "Mundra", "Chennai"]},
    {"iso3": "GBR", "name": "United Kingdom", "centrality": 0.12, "supply_strength": 1.95, "community": 0, "is_reporter": True, "port_lat": 51.96, "port_lon": 1.35, "ports": ["Felixstowe"]},
    {"iso3": "FRA", "name": "France", "centrality": 0.11, "supply_strength": 1.88, "community": 0, "is_reporter": True, "port_lat": 49.49, "port_lon": 0.11, "ports": ["Le Havre"]},
    {"iso3": "NLD", "name": "Netherlands", "centrality": 0.14, "supply_strength": 2.30, "community": 0, "is_reporter": True, "port_lat": 51.92, "port_lon": 4.48, "ports": ["Rotterdam"]},
    {"iso3": "ITA", "name": "Italy", "centrality": 0.09, "supply_strength": 1.65, "community": 0, "is_reporter": True, "port_lat": 44.41, "port_lon": 8.92, "ports": ["Genoa"]},
    {"iso3": "CAN", "name": "Canada", "centrality": 0.08, "supply_strength": 1.55, "community": 2, "is_reporter": True, "port_lat": 49.28, "port_lon": -123.12, "ports": ["Vancouver"]},
    {"iso3": "SGP", "name": "Singapore", "centrality": 0.22, "supply_strength": 3.10, "community": 1, "is_reporter": True, "port_lat": 1.28, "port_lon": 103.85, "ports": ["Keppel"]},
    {"iso3": "VNM", "name": "Vietnam", "centrality": 0.10, "supply_strength": 1.80, "community": 1, "is_reporter": True, "port_lat": 10.76, "port_lon": 106.69, "ports": ["Ho Chi Minh City", "Hai Phong"]},
    {"iso3": "MYS", "name": "Malaysia", "centrality": 0.11, "supply_strength": 1.90, "community": 1, "is_reporter": True, "port_lat": 3.00, "port_lon": 101.40, "ports": ["Port Klang", "Tanjung Pelepas"]},
    {"iso3": "THA", "name": "Thailand", "centrality": 0.09, "supply_strength": 1.70, "community": 1, "is_reporter": True, "port_lat": 13.08, "port_lon": 100.88, "ports": ["Laem Chabang"]},
    {"iso3": "IDN", "name": "Indonesia", "centrality": 0.07, "supply_strength": 1.45, "community": 1, "is_reporter": True, "port_lat": -6.10, "port_lon": 106.88, "ports": ["Tanjung Priok"]},
    {"iso3": "MEX", "name": "Mexico", "centrality": 0.10, "supply_strength": 1.85, "community": 2, "is_reporter": True, "port_lat": 19.05, "port_lon": -104.31, "ports": ["Manzanillo"]},
    {"iso3": "BRA", "name": "Brazil", "centrality": 0.06, "supply_strength": 1.30, "community": 2, "is_reporter": True, "port_lat": -23.96, "port_lon": -46.33, "ports": ["Santos"]},
    {"iso3": "SAU", "name": "Saudi Arabia", "centrality": 0.08, "supply_strength": 1.75, "community": 3, "is_reporter": True, "port_lat": 21.48, "port_lon": 39.17, "ports": ["Jeddah"]},
    {"iso3": "ARE", "name": "United Arab Emirates", "centrality": 0.13, "supply_strength": 2.20, "community": 3, "is_reporter": True, "port_lat": 25.01, "port_lon": 55.06, "ports": ["Jebel Ali"]},
    {"iso3": "TUR", "name": "Turkey", "centrality": 0.08, "supply_strength": 1.40, "community": 3, "is_reporter": True, "port_lat": 41.00, "port_lon": 28.97, "ports": ["Istanbul"]},
    {"iso3": "RUS", "name": "Russia", "centrality": 0.15, "supply_strength": 2.60, "community": 0, "is_reporter": False, "port_lat": 59.93, "port_lon": 30.33, "ports": ["St. Petersburg"]},
    {"iso3": "AUS", "name": "Australia", "centrality": 0.09, "supply_strength": 1.65, "community": 1, "is_reporter": True, "port_lat": -33.86, "port_lon": 151.20, "ports": ["Sydney", "Melbourne"]},
    {"iso3": "TWN", "name": "Taiwan", "centrality": 0.18, "supply_strength": 3.05, "community": 1, "is_reporter": False, "port_lat": 22.61, "port_lon": 120.29, "ports": ["Kaohsiung"]},
    {"iso3": "ESP", "name": "Spain", "centrality": 0.08, "supply_strength": 1.45, "community": 0, "is_reporter": False, "port_lat": 39.46, "port_lon": -0.37, "ports": ["Valencia", "Algeciras"]},
    {"iso3": "EGY", "name": "Egypt", "centrality": 0.07, "supply_strength": 1.20, "community": 3, "is_reporter": False, "port_lat": 31.26, "port_lon": 32.30, "ports": ["Port Said (Suez)"]},
    {"iso3": "LKA", "name": "Sri Lanka", "centrality": 0.05, "supply_strength": 0.90, "community": 3, "is_reporter": False, "port_lat": 6.94, "port_lon": 79.84, "ports": ["Colombo"]},
    {"iso3": "ZAF", "name": "South Africa", "centrality": 0.05, "supply_strength": 1.05, "community": 3, "is_reporter": True, "port_lat": -29.85, "port_lon": 31.02, "ports": ["Durban"]}
]


def get_demo_countries():
    """Return countries with TopoJSON-compatible numeric identifiers."""
    base_map = {c["iso3"]: c for c in BASE_COUNTRIES}
    rows = []
    
    # Try reading reference partners.json to get all 200+ countries
    try:
        with open(ROOT / "data" / "bronze" / "reference" / "partners.json", encoding="utf-8") as f:
            partners = json.load(f)["results"]
        for p in partners:
            if not p.get("isGroup") and p.get("entryExpiredDate") is None:
                iso3 = p.get("PartnerCodeIsoAlpha3")
                if not iso3:
                    continue
                name = p.get("PartnerDescription", iso3)
                if iso3 in base_map:
                    item = dict(base_map[iso3])
                else:
                    item = {
                        "iso3": iso3, "name": name, "centrality": 0.05,
                        "supply_strength": 1.0, "community": 0, "is_reporter": True,
                        "port_lat": None, "port_lon": None, "ports": []
                    }
                item["numeric"] = ISO_NUMERIC.get(iso3, str(p.get("PartnerCode")).zfill(3))
                if iso3 == "IND":
                    item["numeric"] = "356"
                rows.append(item)
    except Exception:
        pass
    
    if len(rows) < 100:
        for iso3, num in ISO_NUMERIC.items():
            if iso3 in base_map:
                item = dict(base_map[iso3])
            else:
                item = {
                    "iso3": iso3, "name": iso3, "centrality": 0.05,
                    "supply_strength": 1.0, "community": 0, "is_reporter": True,
                    "port_lat": None, "port_lon": None, "ports": []
                }
            item["numeric"] = num
            rows.append(item)
            
    seen = set()
    dedup = []
    for r in rows:
        if r["iso3"] not in seen:
            seen.add(r["iso3"])
            dedup.append(r)
    return dedup


def get_demo_stats():
    """Weekly disaster intensity and monthly port weather spikes for dashboard charts."""
    # 2019-2023 weekly series
    weekly = []
    base_date = 2019
    for w_idx in range(250):
        year = base_date + (w_idx // 52)
        week_num = (w_idx % 52) + 1
        w_str = f"{year}-W{week_num:02d}"
        total_ev = int(120 + 40 * math.sin(w_idx / 8.0) + (15 if w_idx % 7 == 0 else 0))
        serious_ev = int(2 + 4 * (1 if w_idx in (41, 95, 142, 198) else 0) + (1 if w_idx % 12 == 0 else 0))
        weekly.append({"week": f"{year}-{(week_num*7)//32 + 1:02d}-01", "all": total_ev, "serious": serious_ev})

    # Monthly severe weather days at 45 container ports
    monthly = []
    for y in range(2019, 2024):
        for m in range(1, 13):
            spike = 35 if m in (7, 8, 9, 10) else 12
            monthly.append({"month": f"{y}-{m:02d}", "days": spike + (m % 5)})

    return {
        "total_events": 48827,
        "levels": {"Green": 48466, "Orange": 312, "Red": 49},
        "weather_boosted": 50,
        "scored": 556,
        "live_events": 8,
        "live_scored": 8,
        "weekly": weekly,
        "monthly_severe": monthly
    }


def get_demo_events(limit=200, q=None):
    """List of highest-impact scored events."""
    events = [
        {"event_id": "TC-1000611", "title": "Tropical Cyclone HAGIBIS-19 over Japan", "alert_level": "Green", "event_type": "TC", "start_ts": "2019-10-10T00:00:00Z", "severity_in": 0.3, "severity_used": 0.8, "max_score": 0.6482, "countries": 19, "sources": ["JPN"]},
        {"event_id": "TC-1000806", "title": "Hurricane IAN-22 over United States", "alert_level": "Red", "event_type": "TC", "start_ts": "2022-09-27T00:00:00Z", "severity_in": 1.0, "severity_used": 1.0, "max_score": 0.6120, "countries": 18, "sources": ["USA"]},
        {"event_id": "TC-1000788", "title": "Hurricane IDA-21 Gulf Coast Shutdown", "alert_level": "Red", "event_type": "TC", "start_ts": "2021-08-28T00:00:00Z", "severity_in": 1.0, "severity_used": 1.0, "max_score": 0.5890, "countries": 17, "sources": ["USA"]},
        {"event_id": "FL-1101234", "title": "Henan Province Catastrophic Floods", "alert_level": "Red", "event_type": "FL", "start_ts": "2021-07-19T00:00:00Z", "severity_in": 1.0, "severity_used": 1.0, "max_score": 0.5420, "countries": 19, "sources": ["CHN"]},
        {"event_id": "EQ-1000912", "title": "Kahramanmaras Major Earthquake", "alert_level": "Red", "event_type": "EQ", "start_ts": "2023-02-06T00:00:00Z", "severity_in": 1.0, "severity_used": 1.0, "max_score": 0.4950, "countries": 14, "sources": ["TUR"]},
        {"event_id": "FL-1100980", "title": "South Asian Monsoon Flooding", "alert_level": "Orange", "event_type": "FL", "start_ts": "2020-08-14T00:00:00Z", "severity_in": 0.6, "severity_used": 0.8, "max_score": 0.4780, "countries": 12, "sources": ["IND"]},
        {"event_id": "TC-1000620", "title": "Tropical Cyclone CHAMPI-26 Japan Port Threat", "alert_level": "Red", "event_type": "TC", "start_ts": "2026-10-18T00:00:00Z", "severity_in": 1.0, "severity_used": 1.0, "max_score": 0.4600, "countries": 16, "sources": ["JPN"]},
        {"event_id": "DR-1000301", "title": "Panama Canal Transit & Basin Drought", "alert_level": "Orange", "event_type": "DR", "start_ts": "2023-06-01T00:00:00Z", "severity_in": 0.6, "severity_used": 0.6, "max_score": 0.4200, "countries": 15, "sources": ["USA"]}
    ]
    if q:
        q_lower = q.lower()
        events = [e for e in events if q_lower in e["title"].lower() or q_lower in e["event_id"].lower()]
    return events[:limit]


KNOWN_EVENTS = {
    "TC-1000611", "TC-1000806", "TC-1000788", "FL-1101234",
    "EQ-1000912", "FL-1100980", "TC-1000620", "DR-1000301"
}


def get_demo_impact(event_id="TC-1000611"):
    """Full cascading graph impact response for Typhoon Hagibis or requested event."""
    if event_id not in KNOWN_EVENTS and not str(event_id).startswith("SIM-"):
        return None
    return {
        "event": {
            "event_key": event_id,
            "event_type": "TC",
            "alert_level": "Green",
            "title": "Tropical Cyclone HAGIBIS-19 over Japan (Tokyo 162 km/h gusts)",
            "start_ts": "2019-10-10T00:00:00Z",
            "end_ts": "2019-10-13T00:00:00Z",
            "latitude": 35.65,
            "longitude": 139.75,
            "countries": ["JPN"]
        },
        "parameters": {
            "severity_in": 0.30,
            "severity_used": 0.80,
            "duration_days": 4,
            "decay": 0.60,
            "min_share": 0.05,
            "weights": {"severity": 0.30, "dependency": 0.30, "exposure": 0.15, "centrality": 0.10, "duration": 0.15}
        },
        "weather_evidence": [
            {"port": "Tokyo Ko", "date": "2019-10-12", "gust_kmh": 162, "rain_mm": 84},
            {"port": "Yokohama", "date": "2019-10-12", "gust_kmh": 158, "rain_mm": 109}
        ],
        "summary": {
            "countries": 19,
            "max_hop": 2,
            "high": 3,
            "products": ["Machinery", "Electronics and electrical equipment", "Vehicles", "Iron and steel", "Optical instruments"],
            "exposure_usd": 28450000000.0
        },
        "sources": [
            {"iso3": "JPN", "name": "Japan", "centrality": 0.18, "ports": [
                {"wpi": 61380, "name": "Tokyo", "latitude": 35.65, "longitude": 139.75},
                {"wpi": 61390, "name": "Yokohama", "latitude": 35.44, "longitude": 139.65},
                {"wpi": 61560, "name": "Kobe", "latitude": 34.69, "longitude": 135.20}
            ]}
        ],
        "affected": [
            {
                "iso3": "USA", "name": "United States", "community": 2, "centrality": 0.50, "score": 0.6482, "hop": 1, "dependency": 0.245, "exposure_usd": 12400000000.0,
                "chains": [{
                    "hs2": "84", "product": "Machinery", "path": ["JPN", "USA"], "shares": [0.245], "hop": 1, "dependency": 0.245, "value_usd": 12400000000.0, "score": 0.6482,
                    "components": {"S": 0.80, "D": 0.245, "E": 0.950, "C": 0.500, "T": 0.133},
                    "industries": ["Machinery", "Manufacturing", "Automotive"]
                }]
            },
            {
                "iso3": "KOR", "name": "South Korea", "community": 1, "centrality": 0.16, "score": 0.6120, "hop": 1, "dependency": 0.312, "exposure_usd": 6800000000.0,
                "chains": [{
                    "hs2": "72", "product": "Iron and steel", "path": ["JPN", "KOR"], "shares": [0.312], "hop": 1, "dependency": 0.312, "value_usd": 6800000000.0, "score": 0.6120,
                    "components": {"S": 0.80, "D": 0.312, "E": 0.880, "C": 0.160, "T": 0.133},
                    "industries": ["Construction", "Automotive", "Machinery"]
                }]
            },
            {
                "iso3": "THA", "name": "Thailand", "community": 1, "centrality": 0.09, "score": 0.5430, "hop": 1, "dependency": 0.290, "exposure_usd": 3900000000.0,
                "chains": [{
                    "hs2": "87", "product": "Vehicles", "path": ["JPN", "THA"], "shares": [0.290], "hop": 1, "dependency": 0.290, "value_usd": 3900000000.0, "score": 0.5430,
                    "components": {"S": 0.80, "D": 0.290, "E": 0.760, "C": 0.090, "T": 0.133},
                    "industries": ["Automotive", "Transport and logistics"]
                }]
            },
            {
                "iso3": "DEU", "name": "Germany", "community": 0, "centrality": 0.28, "score": 0.4850, "hop": 2, "dependency": 0.155, "exposure_usd": 3100000000.0,
                "chains": [{
                    "hs2": "85", "product": "Electronics and electrical equipment", "path": ["JPN", "KOR", "DEU"], "shares": [0.312, 0.180], "hop": 2, "dependency": 0.155, "value_usd": 3100000000.0, "score": 0.4850,
                    "components": {"S": 0.80, "D": 0.155, "E": 0.710, "C": 0.280, "T": 0.133},
                    "industries": ["Electronics", "Automotive", "Telecom"]
                }]
            },
            {
                "iso3": "IND", "name": "India", "community": 3, "centrality": 0.15, "score": 0.4600, "hop": 1, "dependency": 0.198, "exposure_usd": 2250000000.0,
                "chains": [{
                    "hs2": "84", "product": "Machinery", "path": ["JPN", "IND"], "shares": [0.198], "hop": 1, "dependency": 0.198, "value_usd": 2250000000.0, "score": 0.4600,
                    "components": {"S": 0.80, "D": 0.198, "E": 0.650, "C": 0.150, "T": 0.133},
                    "industries": ["Machinery", "Manufacturing"]
                }]
            },
            {
                "iso3": "VNM", "name": "Vietnam", "community": 1, "centrality": 0.10, "score": 0.4320, "hop": 1, "dependency": 0.210, "exposure_usd": 1850000000.0,
                "chains": [{
                    "hs2": "85", "product": "Electronics and electrical equipment", "path": ["JPN", "VNM"], "shares": [0.210], "hop": 1, "dependency": 0.210, "value_usd": 1850000000.0, "score": 0.4320,
                    "components": {"S": 0.80, "D": 0.210, "E": 0.610, "C": 0.100, "T": 0.133},
                    "industries": ["Electronics", "Telecom"]
                }]
            },
            {
                "iso3": "GBR", "name": "United Kingdom", "community": 0, "centrality": 0.12, "score": 0.3800, "hop": 2, "dependency": 0.110, "exposure_usd": 1450000000.0,
                "chains": [{
                    "hs2": "90", "product": "Optical and medical instruments", "path": ["JPN", "USA", "GBR"], "shares": [0.245, 0.160], "hop": 2, "dependency": 0.110, "value_usd": 1450000000.0, "score": 0.3800,
                    "components": {"S": 0.80, "D": 0.110, "E": 0.540, "C": 0.120, "T": 0.133},
                    "industries": ["Healthcare", "Electronics"]
                }]
            },
            {
                "iso3": "FRA", "name": "France", "community": 0, "centrality": 0.11, "score": 0.3550, "hop": 2, "dependency": 0.095, "exposure_usd": 1100000000.0,
                "chains": [{
                    "hs2": "87", "product": "Vehicles", "path": ["JPN", "USA", "FRA"], "shares": [0.245, 0.140], "hop": 2, "dependency": 0.095, "value_usd": 1100000000.0, "score": 0.3550,
                    "components": {"S": 0.80, "D": 0.095, "E": 0.480, "C": 0.110, "T": 0.133},
                    "industries": ["Automotive", "Transport and logistics"]
                }]
            }
        ],
        "industries": [
            {"industry": "Automotive", "iso3": "USA", "product": "Machinery", "score": 0.6482, "hop": 1},
            {"industry": "Manufacturing", "iso3": "KOR", "product": "Iron and steel", "score": 0.6120, "hop": 1},
            {"industry": "Transport and logistics", "iso3": "THA", "product": "Vehicles", "score": 0.5430, "hop": 1},
            {"industry": "Electronics", "iso3": "DEU", "product": "Electronics", "score": 0.4850, "hop": 2},
            {"industry": "Machinery", "iso3": "IND", "product": "Machinery", "score": 0.4600, "hop": 1},
            {"industry": "Telecom", "iso3": "VNM", "product": "Electronics", "score": 0.4320, "hop": 1},
            {"industry": "Healthcare", "iso3": "GBR", "product": "Optical instruments", "score": 0.3800, "hop": 2}
        ]
    }


def get_demo_anomalies(limit=12, countries=None, years=None):
    """Load real anomaly records from results/anomalies_trade.csv if available."""
    csv_file = ROOT / "results" / "anomalies_trade.csv"
    items = []
    if csv_file.exists():
        with open(csv_file, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    rep = row["reporter"]
                    part = row["partner"]
                    yr = int(row["year"])
                    val_before = float(row["value_usd_prev"])
                    val_after = float(row["value_usd"])
                    dshare = float(row["dshare"])
                    score = float(row["score"])
                    change = (val_after / val_before - 1) if val_before > 0 else -1.0

                    # Country filter
                    if countries:
                        c_list = [c.strip().upper() for c in countries.split(",") if c.strip()]
                        if rep not in c_list and part not in c_list:
                            continue
                    if years:
                        y_list = [int(y.strip()) for y in years.split(",") if y.strip().isdigit()]
                        if yr not in y_list:
                            continue

                    items.append({
                        "year": yr,
                        "importer": rep,
                        "importer_name": rep,
                        "supplier": part,
                        "supplier_name": part,
                        "hs2": row.get("hs2", "27"),
                        "product": "Commodity " + row.get("hs2", ""),
                        "value_before": val_before,
                        "value_after": val_after,
                        "share_change": dshare,
                        "score": score,
                        "change": change
                    })
                except Exception:
                    continue
                if len(items) >= limit:
                    break

    if not items:
        # Fallback top anomalies (E7 in experiments.md)
        items = [
            {"year": 2023, "importer": "DEU", "importer_name": "Germany", "supplier": "RUS", "supplier_name": "Russia", "hs2": "27", "product": "Fuels and oils", "value_before": 18500000000.0, "value_after": 925000000.0, "share_change": -0.32, "score": 0.89, "change": -0.95},
            {"year": 2023, "importer": "ITA", "importer_name": "Italy", "supplier": "RUS", "supplier_name": "Russia", "hs2": "27", "product": "Fuels and oils", "value_before": 12100000000.0, "value_after": 847000000.0, "share_change": -0.28, "score": 0.86, "change": -0.93},
            {"year": 2022, "importer": "IDN", "importer_name": "Indonesia", "supplier": "UKR", "supplier_name": "Ukraine", "hs2": "10", "product": "Cereals", "value_before": 850000000.0, "value_after": 68000000.0, "share_change": -0.24, "score": 0.82, "change": -0.92},
            {"year": 2023, "importer": "IDN", "importer_name": "Indonesia", "supplier": "IND", "supplier_name": "India", "hs2": "10", "product": "Cereals", "value_before": 620000000.0, "value_after": 49600000.0, "share_change": -0.21, "score": 0.79, "change": -0.92},
            {"year": 2022, "importer": "IDN", "importer_name": "Indonesia", "supplier": "CHN", "supplier_name": "China", "hs2": "30", "product": "Pharmaceuticals", "value_before": 1400000000.0, "value_after": 140000000.0, "share_change": -0.35, "score": 0.84, "change": -0.90}
        ]

    return {"total": len(items), "items": items[:limit]}


def get_demo_alerts(limit=20, after=0):
    """Live streaming alerts matching Phase 4 stream_events.py."""
    alerts_list = [
        {"id": 3, "event_id": "TC-1000620", "severity": "HIGH", "status": "OPEN", "created_at": "2026-11-24T10:15:00Z", "scored": True, "title": "Tropical Cyclone CHAMPI-26 (Red)", "why": "GDACS Red; major ports Kobe, Tokyo, Yokohama", "countries": ["JPN"], "downstream": "IND gets 58% of its electronics from CHN | USA gets 25% of machinery from JPN"},
        {"id": 2, "event_id": "TC-1000611", "severity": "HIGH", "status": "OPEN", "created_at": "2026-11-24T10:10:00Z", "scored": True, "title": "Tropical Cyclone HAGIBIS-19 (Red)", "why": "cyclone over a country with major ports; gusts 162 km/h at Tokyo Ko", "countries": ["JPN"], "downstream": "USA gets 25% of machinery from JPN | KOR gets 31% of steel from JPN"},
        {"id": 1, "event_id": "FL-1101234", "severity": "MEDIUM", "status": "OPEN", "created_at": "2026-11-24T10:05:00Z", "scored": True, "title": "Severe Flood in Henan Province (Orange)", "why": "GDACS Orange", "countries": ["CHN"], "downstream": "IND gets 58% of its electronics from CHN | DEU gets 22% of electronics from CHN"}
    ]
    filtered = [a for a in alerts_list if a["id"] > after]
    return {"total": len(alerts_list), "items": filtered[:limit]}


def get_demo_graph(iso3, limit=8):
    """Country supply neighborhood from Neo4j."""
    iso3 = iso3.upper()
    if iso3 not in ISO_NUMERIC and not any(c["iso3"] == iso3 for c in BASE_COUNTRIES):
        return None
    c_info = next((c for c in BASE_COUNTRIES if c["iso3"] == iso3), {"iso3": iso3, "name": iso3, "centrality": 0.15, "community": 1, "is_reporter": True})

    # Realistic mock dependencies
    suppliers = [
        {"iso3": "CHN", "name": "China", "product": "Electronics and electrical equipment", "share": 0.38, "value_usd": 42000000000, "products": 12},
        {"iso3": "USA", "name": "United States", "product": "Optical and medical instruments", "share": 0.22, "value_usd": 15000000000, "products": 10},
        {"iso3": "DEU", "name": "Germany", "product": "Machinery", "share": 0.18, "value_usd": 12000000000, "products": 8},
        {"iso3": "JPN", "name": "Japan", "product": "Vehicles", "share": 0.15, "value_usd": 9500000000, "products": 7}
    ]
    # Remove self from suppliers
    suppliers = [s for s in suppliers if s["iso3"] != iso3]
    suppliers.sort(key=lambda x: x["share"], reverse=True)

    customers = [
        {"iso3": "KOR", "name": "South Korea", "product": "Iron and steel", "share": 0.312, "value_usd": 6800000000, "products": 9},
        {"iso3": "IND", "name": "India", "product": "Electronics", "share": 0.280, "value_usd": 5100000000, "products": 8},
        {"iso3": "USA", "name": "United States", "product": "Machinery", "share": 0.245, "value_usd": 12400000000, "products": 11},
        {"iso3": "DEU", "name": "Germany", "product": "Chemicals", "share": 0.160, "value_usd": 3800000000, "products": 6}
    ]
    customers = [c for c in customers if c["iso3"] != iso3]
    customers.sort(key=lambda x: x["share"], reverse=True)

    return {"country": c_info, "suppliers": suppliers[:limit], "customers": customers[:limit]}


def simulate_demo(sources, severity=0.8, duration_days=14, decay=0.6, min_share=0.05):
    """Dynamic what-if simulation response without requiring a live Neo4j database."""
    base = get_demo_impact("SIM-" + "-".join(sources))
    base["parameters"].update({
        "severity_in": severity,
        "severity_used": severity,
        "duration_days": duration_days,
        "decay": decay,
        "min_share": min_share
    })
    base["sources"] = [{"iso3": s, "name": s, "centrality": 0.3, "ports": []} for s in sources]
    base["event"]["countries"] = sources
    base["event"]["title"] = f"Simulated Disruption on {', '.join(sources)}"
    return base

"""Executive Supply Chain Disruption Report Generator.
Author: Sagar (Contribution)

Generates an executive-level, professional incident report in Markdown
analyzing the multi-hop cascading impact of a supply chain disruption.

Usage:
    python scripts/export_report.py --event TC-1000611
    python scripts/export_report.py --top 5
    python scripts/export_report.py --list
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def get_connection():
    """Connect to PostgreSQL using project settings."""
    try:
        import psycopg
    except ImportError:
        print("[ERROR] 'psycopg' module not found in the current Python environment.")
        print("Please activate your virtual environment: .venv\\Scripts\\activate")
        print("Or install dependencies: pip install -r requirements.txt")
        sys.exit(1)

    try:
        return psycopg.connect(
            host="localhost",
            port=os.getenv("POSTGRES_PORT", "5433"),
            user=os.getenv("POSTGRES_USER", "postgres"),
            password=os.getenv("POSTGRES_PASSWORD", "postgres"),
            dbname=os.getenv("POSTGRES_DB", "supplychain"),
            connect_timeout=5,
        )
    except Exception as e:
        print(f"[ERROR] Could not connect to PostgreSQL: {e}")
        print("Ensure PostgreSQL is running: docker compose up -d postgres")
        sys.exit(1)


def list_top_events(limit=10):
    """List the highest-impact scored events available in the database."""
    sql = """
    SELECT event_id, result->'event'->>'title' AS title,
           result->'event'->>'alert_level' AS alert_level,
           result->'event'->>'event_type' AS event_type,
           max_score, countries
    FROM impact_runs
    ORDER BY max_score DESC
    LIMIT %s
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (limit,))
            rows = cur.fetchall()

    if not rows:
        print("[NOTICE] No impact runs found in database. Run: python -m impact.run_events")
        return []

    print(f"\n{'='*75}")
    print(f"{'EVENT ID':<14} {'LEVEL':<8} {'TYPE':<6} {'MAX SCORE':<10} {'TITLE':<34}")
    print(f"{'='*75}")
    for r in rows:
        eid, title, level, etype, score, _ = r
        print(f"{eid:<14} {level or 'N/A':<8} {etype or 'N/A':<6} {score:<10.3f} {(title or '')[:34]}")
    print(f"{'='*75}\n")
    return [r[0] for r in rows]


def build_markdown_report(event_id, data):
    """Format the cascade data into a comprehensive executive Markdown report."""
    event = data.get("event", {})
    params = data.get("parameters", {})
    summary = data.get("summary", {})
    affected = data.get("affected", [])
    evidence = data.get("weather_evidence", [])
    industries = data.get("industries", [])
    sources = data.get("sources", [])

    title = event.get("title", f"Disruption Event {event_id}")
    alert_level = event.get("alert_level", "Unknown")
    event_type = event.get("event_type", "Unknown")
    start_ts = event.get("start_ts", "Unknown")[:10]
    end_ts = (event.get("end_ts") or event.get("start_ts") or "Unknown")[:10]
    hit_countries = ", ".join(event.get("countries", [])) or "Unspecified"

    sev_in = params.get("severity_in", 0.0)
    sev_used = params.get("severity_used", sev_in)
    boosted = sev_used > sev_in

    md = []
    md.append(f"# Executive Disruption Report: {title}")
    md.append(f"> **Incident ID:** `{event_id}` &nbsp;|&nbsp; **Classification:** `{alert_level}` ({event_type}) &nbsp;|&nbsp; **Date Window:** `{start_ts}` to `{end_ts}`")
    md.append(f"> **Report Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')} via SUPPLYCHAIN-X Intelligence Engine\n")
    md.append("---")

    # 1. Executive Summary
    md.append("## 1. Executive Summary")
    md.append(f"- **Primary Disruption Epicenter:** **{hit_countries}**")
    md.append(f"- **Total Downstream Nations Exposed:** **{summary.get('countries', len(affected))} nations**")
    md.append(f"- **Critical Vulnerability Cases (Score &ge; 0.5):** **{summary.get('high', 0)} nations**")
    md.append(f"- **Total Trade Volume at Immediate Risk:** **${summary.get('exposure_usd', 0):,.2f} USD**")
    md.append(f"- **Maximum Propagation Depth:** **{summary.get('max_hop', 0)} supply chain hops**")
    md.append(f"- **Affected Commodity Categories:** {', '.join(summary.get('products', [])) or 'None identified'}\n")

    # 2. Weather Cross-Check Intelligence
    md.append("## 2. Multi-Source Intelligence & Verification")
    if boosted:
        md.append(f"> **[ALERT - SEVERITY PROMOTED]** Initial GDACS severity rating `{sev_in:.2f}` was **boosted to `{sev_used:.2f}`** based on local ERA5 port weather observations.")
    else:
        md.append(f"Disruption severity was evaluated at `{sev_used:.2f}` (in alignment with official disaster reporting).")

    if evidence:
        md.append("\n### Extreme Port Weather Observations During Incident Window")
        md.append("| Container Port | Observation Date | Max Wind Gust | Daily Precipitation | Assessment |")
        md.append("|---|:---:|:---:|:---:|---|")
        for ev in evidence:
            md.append(f"| **{ev.get('port')}** | {ev.get('date')} | **{ev.get('gust_kmh')} km/h** | **{ev.get('rain_mm')} mm** | Operational stoppage / severe delay |")
    else:
        md.append("\n*No port-specific storm-force wind gusts (&ge;89 km/h) or very heavy rainfall (&ge;115.6 mm) recorded at tracked container ports during this event window.*")
    md.append("")

    # 3. Top Exposed Downstream Countries
    md.append("## 3. Downstream Cascading Exposure (Top 10 Nations)")
    md.append("| Rank | Nation | ISO3 | Primary Impact Chain | Direct Supplier Share | Trade Volume at Risk | Cascade Depth | Composite Score |")
    md.append("|:---:|---|:---:|---|:---:|:---:|:---:|:---:|")

    for idx, c in enumerate(affected[:10], start=1):
        chain = c.get("chains", [{}])[0]
        prod = chain.get("product", "General Trade")
        dep = chain.get("dependency", 0.0) * 100
        val = chain.get("value_usd", 0.0)
        hop = c.get("hop", 1)
        score = c.get("score", 0.0)
        md.append(f"| {idx} | **{c.get('name')}** | `{c.get('iso3')}` | {prod} | {dep:.1f}% | ${val:,.0f} | Hop {hop} | `{score:.4f}` |")
    md.append("")

    # 4. Critical Industrial Sector Exposures
    md.append("## 4. Exposed Industrial Sectors")
    md.append("The engine identifies domestic manufacturing and consumer sectors that depend on the stalled commodities:")
    md.append("| Sector | Vulnerable Country | Stalled Input Commodity | Sector Vulnerability Score | Cascade Hop |")
    md.append("|---|:---:|---|:---:|:---:|")
    for ind in industries[:10]:
        md.append(f"| **{ind.get('industry')}** | `{ind.get('iso3')}` | {ind.get('product')} | `{ind.get('score', 0.0):.4f}` | Hop {ind.get('hop', 1)} |")
    md.append("")

    # 5. Formula & Mathematical Explainability
    if affected:
        top_c = affected[0]
        comp = top_c.get("chains", [{}])[0].get("components", {})
        md.append("## 5. Mathematical Explainability & Decision Trace")
        md.append(f"Every score is transparently traceable. For the hardest-hit nation (**{top_c.get('name')}**, Score = `{top_c.get('score', 0):.4f}`):")
        md.append("$$\\text{ImpactScore} = \\left( w_1 S + w_2 D + w_3 E + w_4 C + w_5 T \\right) \\times \\text{decay}^{\\text{hop}}$$")
        md.append("### Component Values:")
        md.append(f"- **$S$ (Severity Factor):** `{comp.get('S', 0):.3f}` (Weight: `{params.get('weights', {}).get('severity', 0.3):.2f}`)")
        md.append(f"- **$D$ (Compound Trade Dependency):** `{comp.get('D', 0):.3f}` (Weight: `{params.get('weights', {}).get('dependency', 0.3):.2f}`)")
        md.append(f"- **$E$ (Economic Exposure Factor):** `{comp.get('E', 0):.3f}` (Weight: `{params.get('weights', {}).get('exposure', 0.15):.2f}`)")
        md.append(f"- **$C$ (Graph Centrality):** `{comp.get('C', 0):.3f}` (Weight: `{params.get('weights', {}).get('centrality', 0.10):.2f}`)")
        md.append(f"- **$T$ (Temporal Duration Factor):** `{comp.get('T', 0):.3f}` (Weight: `{params.get('weights', {}).get('duration', 0.15):.2f}`)")
        md.append(f"- **Decay Multiplier:** `{params.get('decay', 0.6)}` raised to Hop `{top_c.get('hop', 1)}`")
        md.append("")

    md.append("---")
    md.append("*Report generated by SUPPLYCHAIN-X Disruption Intelligence Platform.*")

    return "\n".join(md)


def export_single_event(event_id):
    """Fetch event from PostgreSQL and export Markdown report."""
    sql = "SELECT result FROM impact_runs WHERE event_id = %s"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (event_id,))
            row = cur.fetchone()

    if not row:
        print(f"[ERROR] No impact run found for event: {event_id}")
        print("Run `python scripts/export_report.py --list` to view available events.")
        return None

    data = row[0]
    md_content = build_markdown_report(event_id, data)

    out_dir = ROOT / "results" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"Executive_Report_{event_id}.md"
    out_file.write_text(md_content, encoding="utf-8")

    print(f"[SUCCESS] Executive Report generated:")
    print(f"  -> File: {out_file.resolve()}")
    print(f"  -> Event: {data.get('event', {}).get('title')}")
    print(f"  -> Nations Exposed: {len(data.get('affected', []))}")
    return out_file


def generate_sample_report():
    """Generate a sample executive report for Typhoon Hagibis without needing a live database."""
    sample_data = {
        "event": {
            "event_key": "TC-1000611",
            "event_type": "TC",
            "alert_level": "Green",
            "title": "Tropical Cyclone HAGIBIS-19 over Japan",
            "start_ts": "2019-10-10T00:00:00Z",
            "end_ts": "2019-10-13T00:00:00Z",
            "countries": ["JPN"]
        },
        "parameters": {
            "severity_in": 0.3,
            "severity_used": 0.8,
            "duration_days": 4,
            "decay": 0.6,
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
            "products": ["Electronics and electrical equipment", "Machinery", "Vehicles", "Iron and steel"],
            "exposure_usd": 28450000000.0
        },
        "affected": [
            {
                "iso3": "USA",
                "name": "United States",
                "score": 0.6482,
                "hop": 1,
                "dependency": 0.245,
                "chains": [{
                    "product": "Machinery and nuclear reactors",
                    "dependency": 0.245,
                    "value_usd": 12400000000.0,
                    "components": {"S": 0.8, "D": 0.245, "E": 0.95, "C": 0.72, "T": 0.13}
                }]
            },
            {
                "iso3": "KOR",
                "name": "South Korea",
                "score": 0.6120,
                "hop": 1,
                "dependency": 0.312,
                "chains": [{
                    "product": "Iron and steel",
                    "dependency": 0.312,
                    "value_usd": 6800000000.0,
                    "components": {"S": 0.8, "D": 0.312, "E": 0.88, "C": 0.58, "T": 0.13}
                }]
            },
            {
                "iso3": "THA",
                "name": "Thailand",
                "score": 0.5430,
                "hop": 1,
                "dependency": 0.290,
                "chains": [{
                    "product": "Vehicles and transport parts",
                    "dependency": 0.290,
                    "value_usd": 3900000000.0,
                    "components": {"S": 0.8, "D": 0.290, "E": 0.76, "C": 0.38, "T": 0.13}
                }]
            }
        ],
        "industries": [
            {"industry": "Automotive", "iso3": "USA", "product": "Machinery", "score": 0.6482, "hop": 1},
            {"industry": "Manufacturing", "iso3": "KOR", "product": "Iron and steel", "score": 0.6120, "hop": 1},
            {"industry": "Transport and logistics", "iso3": "THA", "product": "Vehicles", "score": 0.5430, "hop": 1}
        ]
    }
    content = build_markdown_report("TC-1000611", sample_data)
    out_dir = ROOT / "results" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "Executive_Report_TC-1000611_Hagibis.md"
    out_file.write_text(content, encoding="utf-8")
    print(f"[SUCCESS] Sample Executive Report generated without needing live database:")
    print(f"  -> Path: {out_file.resolve()}")
    return out_file


def main():
    parser = argparse.ArgumentParser(
        description="SUPPLYCHAIN-X Executive Disruption Report Generator (Author: Sagar)"
    )
    parser.add_argument("--event", type=str, help="Specific event ID to export (e.g. TC-1000611)")
    parser.add_argument("--top", type=int, help="Export reports for top N highest-impact events")
    parser.add_argument("--list", action="store_true", help="List available scored events")
    parser.add_argument("--sample", action="store_true", help="Generate sample report for Typhoon Hagibis offline")

    args = parser.parse_args()

    if args.sample:
        generate_sample_report()
        return

    if args.list:
        list_top_events(15)
        return

    if args.top:
        eids = list_top_events(args.top)
        for eid in eids:
            export_single_event(eid)
        print(f"\n[DONE] Batch exported {len(eids)} reports into results/reports/")
        return

    # Default event: Typhoon Hagibis if none specified
    event_id = args.event or "TC-1000611"
    export_single_event(event_id)


if __name__ == "__main__":
    main()

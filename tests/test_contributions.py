"""Unit and integration tests for User Contributions.
Author: Sagar

Verifies that the Executive Disruption Report Generator runs correctly,
formats multi-hop cascade metrics, and generates valid Markdown output.
Can be run with pytest: python -m pytest tests/test_contributions.py
Or directly: python tests/test_contributions.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import pytest
except ImportError:
    pytest = None

from scripts.export_report import build_markdown_report


def sample_event_data():
    """Mock cascade result mimicking impact_runs JSON structure."""
    return {
        "event": {
            "event_key": "TC-TEST-001",
            "event_type": "TC",
            "alert_level": "Red",
            "title": "Tropical Cyclone TEST over Japan",
            "start_ts": "2023-10-12T00:00:00Z",
            "end_ts": "2023-10-15T00:00:00Z",
            "countries": ["JPN"]
        },
        "parameters": {
            "severity_in": 0.6,
            "severity_used": 0.8,
            "duration_days": 4,
            "decay": 0.6,
            "min_share": 0.05,
            "weights": {
                "severity": 0.30,
                "dependency": 0.30,
                "exposure": 0.15,
                "centrality": 0.10,
                "duration": 0.15
            }
        },
        "weather_evidence": [
            {
                "port": "Tokyo Ko",
                "date": "2023-10-13",
                "gust_kmh": 162,
                "rain_mm": 120
            }
        ],
        "summary": {
            "countries": 5,
            "max_hop": 2,
            "high": 2,
            "products": ["Electronics", "Vehicles"],
            "exposure_usd": 1500000000.0
        },
        "affected": [
            {
                "iso3": "USA",
                "name": "United States",
                "score": 0.725,
                "hop": 1,
                "dependency": 0.35,
                "chains": [
                    {
                        "product": "Electronics and electrical equipment",
                        "dependency": 0.35,
                        "value_usd": 850000000.0,
                        "components": {"S": 0.8, "D": 0.35, "E": 0.9, "C": 0.85, "T": 0.13}
                    }
                ]
            },
            {
                "iso3": "KOR",
                "name": "South Korea",
                "score": 0.580,
                "hop": 1,
                "dependency": 0.28,
                "chains": [
                    {
                        "product": "Iron and steel",
                        "dependency": 0.28,
                        "value_usd": 420000000.0,
                        "components": {"S": 0.8, "D": 0.28, "E": 0.7, "C": 0.60, "T": 0.13}
                    }
                ]
            }
        ],
        "industries": [
            {
                "industry": "Automotive",
                "iso3": "USA",
                "product": "Electronics and electrical equipment",
                "score": 0.725,
                "hop": 1
            }
        ]
    }


def test_script_exists():
    """Verify that export_report.py exists in scripts/."""
    script_path = ROOT / "scripts" / "export_report.py"
    assert script_path.exists(), "export_report.py must exist"


def test_build_markdown_report(data=None):
    """Verify that build_markdown_report generates expected sections."""
    if data is None:
        data = sample_event_data()
    report = build_markdown_report("TC-TEST-001", data)

    assert "# Executive Disruption Report" in report
    assert "Tropical Cyclone TEST over Japan" in report
    assert "Tokyo Ko" in report
    assert "162 km/h" in report
    assert "United States" in report
    assert "Automotive" in report
    assert "ImpactScore" in report


if __name__ == "__main__":
    print("Running contribution tests...")
    test_script_exists()
    test_build_markdown_report()
    print("[SUCCESS] All contribution tests passed successfully!")


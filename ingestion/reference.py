"""Download Comtrade reference lists (countries, partner areas, HS codes) into bronze.

These are small and public (no API key), and everything else joins against them.

    python -m ingestion.reference
"""
import json

import requests

from ingestion.config import BRONZE

BASE = "https://comtradeapi.un.org/files/v1/app/reference"
FILES = {
    "reporters": "Reporters.json",
    "partners": "partnerAreas.json",
    "hs": "HS.json",
}


def load(name):
    """Read a downloaded reference list back as a list of dicts."""
    with open(BRONZE / "reference" / f"{name}.json", encoding="utf-8") as f:
        return json.load(f)["results"]


def main():
    out = BRONZE / "reference"
    out.mkdir(parents=True, exist_ok=True)
    for name, fname in FILES.items():
        r = requests.get(f"{BASE}/{fname}", timeout=60)
        r.raise_for_status()
        # bronze = exactly what the source gave us, so save the raw bytes
        (out / f"{name}.json").write_bytes(r.content)
        print(f"{name:10} {len(r.json()['results']):>6} rows -> {out / (name + '.json')}")


if __name__ == "__main__":
    main()

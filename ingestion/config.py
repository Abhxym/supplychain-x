"""What we pull in phase 1. Kept small on purpose - widen it once the pipeline works end to end."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRONZE = ROOT / "data" / "bronze"

# Major trading economies + the Asian manufacturing/shipping hubs most supply-chain stories go through.
# ISO3 here; the Comtrade numeric codes are looked up from the reference file (India is 699 in Comtrade,
# not its UN M49 code 356, so hardcoding numbers is a good way to get the wrong country).
REPORTERS = [
    "CHN", "USA", "IND", "DEU", "JPN", "KOR", "VNM", "SGP", "NLD", "MYS",
    "THA", "IDN", "BRA", "MEX", "GBR", "FRA", "ITA", "CAN", "SAU", "ARE",
]

# HS2 chapters - the commodity groups that keep showing up in disruption cases
COMMODITIES = {
    "10": "Cereals",
    "15": "Animal/vegetable fats and oils",
    "27": "Mineral fuels, oils",
    "29": "Organic chemicals",
    "30": "Pharmaceutical products",
    "39": "Plastics",
    "72": "Iron and steel",
    "76": "Aluminium",
    "84": "Machinery, nuclear reactors, boilers",
    "85": "Electrical machinery and electronics",
    "87": "Vehicles",
    "90": "Optical, medical, measuring instruments",
}

# 2019-2023 covers covid, the Suez blockage (Mar 2021) and the Russia-Ukraine shock (2022),
# which gives us real disruptions to validate against later.
YEARS = [2019, 2020, 2021, 2022, 2023]

FLOWS = ["M", "X"]  # imports, exports

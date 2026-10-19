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

# Busiest container ports + chokepoint hubs, by World Port Index number.
# Picked by hand: WPI's "harbor_size" is physical size, not traffic (it calls Ningbo "Small"),
# and several big Chinese ports + Singapore have no UN/LOCODE in WPI, so the index number is the safe key.
MAJOR_PORTS = [
    59970,  # Shanghai, China
    59940,  # Ningbo, China
    57857,  # Yantian (Shenzhen), China
    57777,  # Shekou (Shenzhen), China
    60140,  # Qingdao, China
    57830,  # Guangzhou, China
    60190,  # Tianjin Xin Gang, China
    57870,  # Xiamen, China
    50000,  # Singapore (Keppel)
    60390,  # Busan, South Korea
    57840,  # Hong Kong
    48276,  # Jebel Ali, UAE
    31140,  # Rotterdam, Netherlands
    31250,  # Antwerp, Belgium
    49930,  # Port Klang, Malaysia
    51587,  # Tanjung Pelepas, Malaysia
    57920,  # Kaohsiung, Taiwan
    16080,  # Los Angeles, USA
    16070,  # Long Beach, USA
    7640,   # New York, USA
    8530,   # Savannah, USA
    9240,   # Houston, USA
    30780,  # Hamburg, Germany
    30810,  # Bremerhaven, Germany
    61380,  # Tokyo, Japan
    61390,  # Yokohama, Japan
    61560,  # Kobe, Japan
    48845,  # Nhava Sheva (JNPT, Mumbai), India
    48617,  # Mundra, India
    49450,  # Chennai, India
    57580,  # Ho Chi Minh City, Vietnam
    57680,  # Hai Phong, Vietnam
    57462,  # Laem Chabang, Thailand
    50970,  # Jakarta (Tanjung Priok), Indonesia
    49240,  # Colombo, Sri Lanka
    31560,  # Felixstowe, UK
    35840,  # Le Havre, France
    39470,  # Genoa, Italy
    38480,  # Valencia, Spain
    38310,  # Algeciras, Spain
    45140,  # Port Said, Egypt (Suez canal)
    12970,  # Santos, Brazil
    15770,  # Manzanillo, Mexico
    18150,  # Vancouver, Canada
    48140,  # Jeddah, Saudi Arabia
]

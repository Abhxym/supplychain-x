"""Shared bits for the Spark jobs: lake paths, session, data-quality checks, lookup tables.

Note: the Spark image runs Python 3.8, so no `list[str]` hints or match statements in here.
"""
from pyspark.sql import SparkSession

BRONZE = "/lake/bronze"
SILVER = "/lake/silver"
GOLD = "/lake/gold"


def spark(app_name):
    return SparkSession.builder.appName(app_name).getOrCreate()


def check(name, ok, detail=""):
    """Data-quality gate: print the result, and stop the job if it fails.
    A silver table that silently breaks a rule is worse than no table."""
    print("[{}] {}{}".format("PASS" if ok else "FAIL", name, " - " + str(detail) if detail else ""))
    if not ok:
        raise SystemExit("data quality check failed: " + name)


# Comtrade partner codes that are not countries: regions, "areas not elsewhere specified",
# ship fuel (bunkers), free zones. They can't be nodes in a dependency graph.
# 490 "Other Asia, nes" is NOT in here - it's how the UN reports Taiwan, mapped to TWN below.
NON_COUNTRY_PARTNERS = {0, 129, 221, 290, 471, 472, 473, 488, 492, 527, 536, 568, 577,
                        636, 637, 697, 830, 837, 838, 839, 872, 879, 899}
TAIWAN_CODE = 490

# Our 12 HS chapters: short names (the official ones run to 200 characters) and a broad category
HS_CHAPTERS = {
    "10": ("Cereals", "Food"),
    "15": ("Fats and oils", "Food"),
    "27": ("Fuels and oils", "Energy"),
    "29": ("Organic chemicals", "Chemicals"),
    "30": ("Pharmaceuticals", "Chemicals"),
    "39": ("Plastics", "Chemicals"),
    "72": ("Iron and steel", "Metals"),
    "76": ("Aluminium", "Metals"),
    "84": ("Machinery", "Machinery and electronics"),
    "85": ("Electronics and electrical equipment", "Machinery and electronics"),
    "87": ("Vehicles", "Transport"),
    "90": ("Optical and medical instruments", "Machinery and electronics"),
}

# Which industries use each product group. A deliberately simple mapping (a real one would come
# from input-output tables) so the impact engine can go one step past countries.
PRODUCT_INDUSTRIES = {
    "10": ["Food processing"],
    "15": ["Food processing"],
    "27": ["Energy", "Transport and logistics"],
    "29": ["Chemicals", "Pharmaceuticals"],
    "30": ["Healthcare"],
    "39": ["Packaging", "Automotive"],
    "72": ["Construction", "Automotive", "Machinery"],
    "76": ["Automotive", "Packaging", "Construction"],
    "84": ["Machinery", "Manufacturing"],
    "85": ["Electronics", "Automotive", "Telecom"],
    "87": ["Automotive", "Transport and logistics"],
    "90": ["Healthcare", "Electronics"],
}

# World Port Index writes country names its own way. These are the ones that don't match the
# UN Comtrade names exactly; everything else is matched by name.
WPI_COUNTRY_ISO3 = {
    "United States": "USA", "Russia": "RUS", "Turkey": "TUR", "Dominican Republic": "DOM",
    "Vietnam": "VNM", "South Korea": "KOR", "North Korea": "PRK", "Puerto Rico": "PRI",
    "Faroe Islands": "FRO", "Tanzania": "TZA", "Taiwan": "TWN", "Burma": "MMR",
    "Solomon Islands": "SLB", "U.S. Virgin Islands": "VIR", "The Bahamas": "BHS",
    "Brunei": "BRN", "Cote D'Ivoire": "CIV", "Reunion": "REU", "Congo (Brazzaville)": "COG",
    "Congo (Kinshasa)": "COD", "Federated States of Micronesia": "FSM", "Guadeloupe": "GLP",
    "Curacao": "CUW", "Caribbean Netherlands": "BES", "Marshall Islands": "MHL",
    "Northern Mariana Islands": "MNP", "Svalbard": "SJM", "Turks and Caicos Islands": "TCA",
    "South Georgia and South Sandwich Islands": "SGS", "Sint Maarten": "SXM",
    "Cayman Islands": "CYM", "Isle of Man": "IMN", "Monaco": "MCO", "British Virgin Islands": "VGB",
    "Christmas Island": "CXR", "Bosnia and Herzegovina": "BIH",
    "Johnson Atoll": "UMI", "Midway Islands": "UMI", "Wake Island": "UMI",
    "Norfolk Island": "NFK", "Hong Kong": "HKG", "Macau": "MAC", "French Guiana": "GUF",
    "Falkland Islands (Islas Malvinas)": "FLK", "Nauru": "NRU", "British Indian Ocean Territory": "IOT",
    "Martinique": "MTQ", "Saint Vincent and the Grenadines (Windward Islands)": "VCT",
    "Cook Islands": "COK", "Wallis and Futuna": "WLF", "The Gambia": "GMB",
    "Saint Helena, Ascension, and Tristan da Cunha": "SHN",
}

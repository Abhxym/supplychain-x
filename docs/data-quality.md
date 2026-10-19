# Data quality

Every silver job ends with checks. If one fails, the job stops and nothing is written -
a silver table that quietly breaks a rule is worse than no table at all.

Run them all: `python scripts/spark_run.py silver`

## What the checks found

| Where | Problem in the source data | What we did |
|---|---|---|
| Comtrade | Each partner is also split by "2nd partner", customs type and transport mode, each with its own total - summing everything counts trade 2-3x | Ingestion asks for totals only; silver checks no split rows got through |
| Comtrade | Taiwan is reported as "Other Asia, nes" (code 490), worth $3.2T over 2019-23 | Mapped to `TWN` instead of dropped |
| Comtrade | "Areas, nes", regions, ship bunkers, free zones appear as partners | Dropped from `silver/trade` (not countries), still inside `trade_totals`, so shares use the full denominator. 96.2% of value is country-to-country |
| Comtrade | Countries have expired codes (India 356 before 1974, 699 now) | Only current codes kept; check that India is 699 |
| GDACS | Long events repeat in every monthly download | Kept the latest version of each event: 54,989 rows -> 48,827 events |
| GDACS | Alert level written as `Green` and `GREEN` | Normalised to `Green / Orange / Red` |
| GDACS | One flood (FL-1101126) ends 27 days before it starts | Kept, duration treated as unknown, flagged `date_fixed` |
| GDACS | 6,109 events have no country | All Green, all at sea (ocean-ridge quakes, cyclones that never landed) - allowed. Rule enforced: every Orange/Red event has a country |
| GDACS | A drought can hit several countries | `silver/event_countries`: one row per event x country (43,785 rows) |
| WPI | "Country code" column holds names, and 50 of them differ from the UN's ("United States" vs "USA") | Alias table in `spark_jobs/lake.py`, every one of 3,805 ports gets an ISO3 |
| WPI | Index numbers 400 and 46135 used twice | Kept the older entry so `wpi_number` is a key |
| WPI | Everything stored as text, blanks and "Unknown" mixed in | Cast to numbers, blanks/"Unknown" -> null |
| Weather | (clean) | Checked: 45 ports x 1,826 days, no gaps, no missing values |

## Mistakes the checks caught in our own code

Worth saying in a viva - the checks exist for exactly this.

- Searching partner names for "nes" (not elsewhere specified) also matched French Poly**nes**ia,
  which got dropped as a non-country. The "every port has an ISO3" check failed on it.
- Spark wrote silver with 3 copies per block while HDFS was set up for 2: replication is chosen
  by the client that writes, and Spark never saw `hadoop.env`. `hdfs fsck` showed 109/109 blocks
  under-replicated. Fixed in `spark/spark-defaults.conf`, existing files fixed with `hdfs dfs -setrep`.
- `severe_day` first included "max temperature >= 40 C". In gold, Jebel Ali (Dubai) came out as the
  most weather-hit port with 301 severe days - but its strongest gust was only 78 km/h. Those were
  ordinary Gulf summer days, which the port is built for. A fixed heat line doesn't suit every climate,
  so `severe_day` is now very heavy rain or storm-force gusts only; `extreme_heat` stays as its own
  column. A fairer heat flag would compare each port with its own normal (e.g. its 99th percentile).

## Severe-weather thresholds

Taken from public definitions, not tuned on our data.

| Flag | Rule | Source |
|---|---|---|
| `heavy_rain` | >= 64.5 mm/day | India Meteorological Department |
| `very_heavy_rain` | >= 115.6 mm/day | India Meteorological Department |
| `storm_gust` | gusts >= 89 km/h | Beaufort force 10 |
| `extreme_heat` | max temp >= 40 C (not part of `severe_day`) | |
| `thunderstorm` | WMO weather code 95, 96, 99 | WMO |

`severe_day` = `very_heavy_rain` OR `storm_gust`.

## Gold checks

| Table | Check |
|---|---|
| dependencies | every share between 0 and 1 |
| concentration | suppliers of one importer/product never add up to more than its world total |
| concentration | exactly 20 importers x 12 products x 5 years = 1,200 rows |
| country_event_features | per-type counts add up to the total |
| port_weather_features | 45 ports x 5 years = 225 rows, every port has a country |
| Postgres load | every one of the 142,735 dependency rows arrives |

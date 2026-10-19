"""Anomaly detection with Isolation Forest.

    python -m ml.anomalies

Isolation Forest builds many random trees that split the data at random points. A normal point sits in
a crowd and needs many splits to be cut off on its own; an unusual point is isolated in a few. The
average number of splits becomes the anomaly score. No labels are needed.

1. Trade: one row per (importer, supplier, product, year) for 2020-2023, described by
   - dlog   change of log import value vs the year before (a fall from $100M to $50M is -0.69)
   - dshare change of the supplier's share of the importer's imports of that product
   - size   log of last year's value (a 50% drop in a $20M flow is less surprising than in a $20B one)
   We keep anomalies that are DROPS (dlog < 0): flows that fell in an unusual way.
2. Port weather: one row per port-day, features scaled per port (what is extreme for Mumbai is not
   for Rotterdam). We compare what the forest finds with the fixed thresholds used since Phase 2.

Writes Postgres tables ml_trade_anomalies / ml_weather_anomalies and results/anomalies_trade.csv.
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from impact.run_events import connect
from ml.data import ROOT, port_weather, trade_imports

MIN_FLOW_USD = 10e6   # ignore tiny flows - they jump around for no reason
CONTAMINATION = 0.02  # we ask the forest for its strangest 2%


def trade_features():
    d = trade_imports()
    d["share"] = d.value_usd / d.groupby(["year", "reporter", "hs2"]).value_usd.transform("sum")
    prev = d[["year", "reporter", "partner", "hs2", "value_usd", "share"]].copy()
    prev["year"] += 1
    f = d.merge(prev, on=["year", "reporter", "partner", "hs2"], suffixes=("", "_prev"))
    f = f[f.value_usd_prev >= MIN_FLOW_USD].copy()
    f["dlog"] = np.log(f.value_usd) - np.log(f.value_usd_prev)
    f["dshare"] = f.share - f.share_prev
    f["size"] = np.log10(f.value_usd_prev)
    return f


def trade_anomalies():
    f = trade_features()
    X = f[["dlog", "dshare", "size"]].to_numpy()
    forest = IsolationForest(n_estimators=300, contamination=CONTAMINATION, random_state=42).fit(X)
    f["score"] = -forest.score_samples(X)          # higher = more unusual
    f["anomaly"] = forest.predict(X) == -1
    drops = f[f.anomaly & (f.dlog < 0)].sort_values("score", ascending=False)
    print("trade: {:,} flows, {:,} anomalies, {:,} of them drops".format(len(f), int(f.anomaly.sum()), len(drops)))
    print(drops.groupby("year").size().rename("drops per year").to_string())
    return f, drops


def weather_anomalies():
    w = port_weather().dropna(subset=["precipitation_sum", "wind_gusts_10m_max"])
    w["trange"] = w.temperature_2m_max - w.temperature_2m_min
    feats = ["precipitation_sum", "wind_gusts_10m_max", "wind_speed_10m_max", "trange"]
    z = w.groupby("wpi_number")[feats].transform(lambda s: (s - s.mean()) / (s.std() or 1))
    forest = IsolationForest(n_estimators=300, contamination=0.005, random_state=42).fit(z)
    w["score"] = -forest.score_samples(z)
    w["anomaly"] = forest.predict(z) == -1
    w["threshold"] = (w.precipitation_sum >= 115.6) | (w.wind_gusts_10m_max >= 89)
    both = int((w.anomaly & w.threshold).sum())
    print("weather: {:,} port-days, forest flags {:,}, thresholds flag {:,}, both {:,}".format(
        len(w), int(w.anomaly.sum()), int(w.threshold.sum()), both))
    return w[w.anomaly | w.threshold]


def main():
    flows, drops = trade_anomalies()
    weather = weather_anomalies()

    out = drops[["year", "reporter", "partner", "hs2", "value_usd_prev", "value_usd", "dlog", "dshare", "score"]]
    out.round(4).to_csv(ROOT / "results" / "anomalies_trade.csv", index=False)
    with connect() as db:
        db.execute("""DROP TABLE IF EXISTS ml_trade_anomalies;
            CREATE TABLE ml_trade_anomalies (year smallint, reporter text, partner text, hs2 text,
                value_prev numeric, value numeric, dlog real, dshare real, score real)""")
        db.execute("""DROP TABLE IF EXISTS ml_weather_anomalies;
            CREATE TABLE ml_weather_anomalies (wpi integer, port text, iso3 text, day date, rain_mm real,
                gust_kmh real, score real, forest boolean, threshold boolean)""")
        with db.cursor() as cur:
            cur.executemany("INSERT INTO ml_trade_anomalies VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                            [tuple(r) for r in out.itertuples(index=False)])
            cur.executemany("INSERT INTO ml_weather_anomalies VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                            [(int(r.wpi_number), r.port_name, r.iso3, r.time, float(r.precipitation_sum),
                              float(r.wind_gusts_10m_max), float(r.score), bool(r.anomaly), bool(r.threshold))
                             for r in weather.itertuples()])
    print("\nstrangest drops:")
    print(out.head(15).to_string(index=False))


if __name__ == "__main__":
    main()

"""Severity classifier - a side component, not the headline.

    python -m ml.severity

Can we guess GDACS's alert level (Green = low, Orange = medium, Red = high) from CONTEXT alone?
We deliberately leave out the physical size of the event (magnitude, wind speed, GDACS's own score),
because GDACS computes the alert from exactly those - using them would be copying the answer.

Features per event:
    event type (EQ, TC, FL, ...), duration in days, number of countries hit
    weather   strongest gust / heaviest rain / severe days at the hit countries' major ports during the event
    history   events and Orange/Red events in the same countries in the 365 days BEFORE the event
    trade     the hit countries' 2023 exports into our 20 economies (log $) and their largest supply share
    ports     how many of our 45 major ports are in the hit countries

Train on 2019-2022, test on 2023 (a time split: the model never sees the future).
Compared with a baseline that always answers "low".
"""
import math
from collections import defaultdict
from datetime import date, timedelta

import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, confusion_matrix, f1_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from ml.data import ROOT, events, port_weather, ports

LABEL = {"Green": "low", "Orange": "medium", "Red": "high"}
CLASSES = ["low", "medium", "high"]
TYPES = ["EQ", "TC", "FL", "DR", "WF", "VO"]
MAX_WINDOW = 30  # days of weather looked at per event


def build():
    import json
    with open(ROOT / "data" / "graph" / "supplies.json", encoding="utf-8") as f:
        sup = pd.DataFrame(json.load(f))
    exports = sup.groupby("src").value_usd.sum().to_dict()
    top_share = sup.groupby("src").share.max().to_dict()
    n_ports = ports().groupby("iso3").size().to_dict()

    w = port_weather()
    w["day"] = pd.to_datetime(w.time).dt.date
    w["severe"] = (w.precipitation_sum >= 115.6) | (w.wind_gusts_10m_max >= 89)
    daily = w.groupby(["iso3", "day"]).agg(gust=("wind_gusts_10m_max", "max"), rain=("precipitation_sum", "max"),
                                           severe=("severe", "sum"))
    by_country = {c: g.droplevel(0) for c, g in daily.groupby(level=0)}

    evs = sorted((e for e in events() if e["alert_level"] in LABEL), key=lambda e: e["start_ts"])
    history = defaultdict(list)  # country -> [(day, serious)] of events seen so far
    rows = []
    for e in evs:
        start = date.fromisoformat(e["start_ts"][:10])
        end = date.fromisoformat((e["end_ts"] or e["start_ts"])[:10])
        cs = e["countries"]
        gust = rain = severe = 0.0
        for c in cs:
            if c in by_country:
                win = by_country[c].loc[start:min(end, start + timedelta(days=MAX_WINDOW))]
                if len(win):
                    gust, rain = max(gust, win.gust.max()), max(rain, win.rain.max())
                    severe += win.severe.sum()
        year_ago = start - timedelta(days=365)
        past = [s for c in cs for d, s in history[c] if year_ago <= d < start]
        row = {"year": start.year, "label": LABEL[e["alert_level"]],
               "duration": (end - start).days + 1, "n_countries": len(cs),
               "port_gust": gust, "port_rain": rain, "port_severe_days": severe,
               "past_events": len(past), "past_serious": sum(past),
               "exports_log": math.log10(1 + sum(exports.get(c, 0) for c in cs)),
               "top_share": max([top_share.get(c, 0) for c in cs] or [0]),
               "ports": sum(n_ports.get(c, 0) for c in cs)}
        row.update({"type_" + t: int(e["event_type"] == t) for t in TYPES})
        rows.append(row)
        for c in cs:
            history[c].append((start, e["alert_level"] != "Green"))
    return pd.DataFrame(rows)


def main():
    d = build()
    feats = [c for c in d.columns if c not in ("year", "label")]
    train, test = d[d.year <= 2022], d[d.year == 2023]
    print("events: train {:,} (2019-22), test {:,} (2023)".format(len(train), len(test)))
    print("label mix in test:", test.label.value_counts().to_dict())

    models = {
        "baseline (always low)": DummyClassifier(strategy="most_frequent"),
        "logistic regression": make_pipeline(StandardScaler(), LogisticRegression(max_iter=5000, class_weight="balanced")),
        "random forest": RandomForestClassifier(n_estimators=300, min_samples_leaf=5, class_weight="balanced",
                                                random_state=42, n_jobs=-1),
    }
    lines, summary = [], []
    for name, m in models.items():
        m.fit(train[feats], train.label)
        pred = m.predict(test[feats])
        cm = confusion_matrix(test.label, pred, labels=CLASSES)
        rep = classification_report(test.label, pred, labels=CLASSES, zero_division=0, digits=3)
        macro = f1_score(test.label, pred, labels=CLASSES, average="macro", zero_division=0)
        summary.append({"model": name, "macro_f1": round(macro, 3),
                        **{"f1_" + c: round(v, 3) for c, v in zip(CLASSES, f1_score(
                            test.label, pred, labels=CLASSES, average=None, zero_division=0))}})
        lines += ["== " + name, rep, "confusion matrix (rows = truth, cols = predicted; low, medium, high)",
                  pd.DataFrame(cm, index=CLASSES, columns=CLASSES).to_string(), ""]

    rf = models["random forest"]
    imp = permutation_importance(rf, test[feats], test.label, scoring="f1_macro", n_repeats=5, random_state=42)
    order = np.argsort(-imp.importances_mean)
    lines += ["== random forest permutation importance (drop in macro F1 on 2023 when a feature is shuffled)"]
    lines += ["{:18s} {:+.4f}".format(feats[i], imp.importances_mean[i]) for i in order]

    report = "\n".join(lines)
    print(report)
    (ROOT / "results" / "severity_classifier.txt").write_text(report + "\n", encoding="utf-8")
    pd.DataFrame(summary).to_csv(ROOT / "results" / "severity_classifier.csv", index=False)
    print(pd.DataFrame(summary).to_string(index=False))


if __name__ == "__main__":
    main()

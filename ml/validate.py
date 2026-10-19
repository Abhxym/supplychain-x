"""Does the impact engine put the countries that were really hit near the top?

    python -m ml.validate

For every known case in ml/ground_truth.json the engine ranks the countries in the cascade.
We compare three versions of the score (same engine, different weights):

    A  severity only                 S                     (+ hop decay)
    B  + trade dependency/exposure   S, D, E, T            (+ hop decay)
    C  + graph centrality            S, D, E, C, T         (+ hop decay) - the default engine

and a random ranking of the same countries as the floor. Metrics, for K = 1, 3, 5:

    Precision@K  of the top K countries, the share that were really hit
    Recall@K     of the countries really hit, the share found in the top K
    Hit@K        1 if at least one really-hit country is in the top K

Ties: in A every country at the same hop has the same score. We do not break ties in anyone's favour -
we report the EXPECTED value over all orders of the tied countries (computed exactly).

A second, noisier ground truth (GT2) uses our own data: for each Red event 2019-2022, the importers
whose imports from the hit country had an unusual drop (Isolation Forest, ml.anomalies) that year or the next.
Annual trade cannot tell which event caused a drop, so GT2 is a sanity check, not proof.
"""
import json
from math import comb

import pandas as pd

from impact.engine import DEFAULT_WEIGHTS, severity_for, simulate
from impact.run_events import connect
from ml.data import ROOT, events

VARIANTS = {
    "A severity only": {"severity": 1, "dependency": 0, "exposure": 0, "centrality": 0, "duration": 0},
    "B + dependency/exposure": {"severity": .30, "dependency": .30, "exposure": .15, "centrality": 0, "duration": .15},
    "C + centrality": DEFAULT_WEIGHTS,
}
KS = (1, 3, 5)


def run(sources, severity, days, start=None, end=None, weights=None):
    r = simulate(sources, severity=severity, duration_days=days, start=start, end=end,
                 weights=weights, max_results=500)
    return [(c["iso3"], c["score"]) for c in r["affected"]]


def expected_at_k(ranking, truth, k):
    """Expected hits and P(at least one hit) in the top k, averaging over orders of tied scores."""
    groups = {}
    for iso, s in ranking:
        groups.setdefault(round(s, 6), []).append(iso)
    hits, p_none, taken = 0.0, 1.0, 0
    for s in sorted(groups, reverse=True):
        g = groups[s]
        h = sum(1 for x in g if x in truth)
        m = min(len(g), k - taken)
        if m <= 0:
            break
        hits += m * h / len(g)
        p_none *= comb(len(g) - h, m) / comb(len(g), m)
        taken += m
    return hits, 1 - p_none


def random_at_k(ranking, truth, k):
    n = len(ranking)
    h = sum(1 for iso, _ in ranking if iso in truth)
    m = min(k, n)
    return m * h / n if n else 0.0, (1 - comb(n - h, m) / comb(n, m)) if n else 0.0


def score_case(ranking, truth):
    row = {}
    for k in KS:
        hits, p_hit = expected_at_k(ranking, truth, k)
        row.update({"P@%d" % k: hits / k, "R@%d" % k: hits / len(truth), "Hit@%d" % k: p_hit})
    return row


def score_random(ranking, truth):
    row = {}
    for k in KS:
        hits, p_hit = random_at_k(ranking, truth, k)
        row.update({"P@%d" % k: hits / k, "R@%d" % k: hits / len(truth), "Hit@%d" % k: p_hit})
    return row


def case_inputs(case, by_key):
    if "event_key" in case:
        e = by_key[case["event_key"]]
        start, end = e["start_ts"][:10], (e["end_ts"] or e["start_ts"])[:10]
        days = (pd.Timestamp(end) - pd.Timestamp(start)).days + 1
        return dict(sources=case["sources"], severity=severity_for(e["alert_level"]), days=days, start=start, end=end)
    return dict(sources=case["sources"], severity=case["severity"], days=case["duration_days"])


def evaluate(cases, label):
    """cases: list of (case_id, engine inputs, set of truly-hit countries). Returns per-case rows."""
    rows = []
    for cid, inp, truth in cases:
        rankings = {v: run(weights=w, **inp) for v, w in VARIANTS.items()}
        for v, rk in rankings.items():
            rows.append({"gt": label, "case": cid, "variant": v, "n_ranked": len(rk), "n_truth": len(truth),
                         "truth_reached": sum(1 for i, _ in rk if i in truth),
                         "top5": " ".join("{}{}".format(i, "*" if i in truth else "") for i, _ in rk[:5]),
                         **score_case(rk, truth)})
        rk = rankings["C + centrality"]
        rows.append({"gt": label, "case": cid, "variant": "random", "n_ranked": len(rk), "n_truth": len(truth),
                     "truth_reached": sum(1 for i, _ in rk if i in truth), "top5": "",
                     **score_random(rk, truth)})
    return rows


def gt1(by_key, min_confidence=("strong", "medium", "weak")):
    with open(ROOT / "ml" / "ground_truth.json", encoding="utf-8") as f:
        gt = json.load(f)
    cases = []
    for c in gt["cases"]:
        truth = {iso for iso, a in c["affected"].items() if a["confidence"] in min_confidence}
        if truth:
            cases.append((c["id"], case_inputs(c, by_key), truth))
    return cases, gt


def gt2(by_key):
    drops = pd.read_csv(ROOT / "results" / "anomalies_trade.csv")
    with connect() as db:
        keys = [k for (k,) in db.execute("SELECT event_id FROM impact_runs")]
    cases = []
    for k in keys:
        e = by_key[k]
        y = int(e["start_ts"][:4])
        if e["alert_level"] != "Red" or y > 2022:
            continue
        d = drops[drops.partner.isin(e["countries"]) & drops.year.isin([y, y + 1])]
        truth = set(d.reporter) - set(e["countries"])
        if truth:
            cases.append((k, case_inputs({"event_key": k, "sources": e["countries"]}, by_key), truth))
    return cases


def summarise(rows):
    df = pd.DataFrame(rows)
    cols = ["P@1", "P@3", "P@5", "R@3", "R@5", "Hit@1", "Hit@3"]
    order = list(VARIANTS) + ["random"]
    return (df.groupby(["gt", "variant"])[cols].mean().round(3)
              .reindex(pd.MultiIndex.from_product([df["gt"].unique(), order])).dropna(how="all"))


def bootstrap(rows, by_key, label, metric="P@3", n=5000):
    """95% interval for the difference between two variants. Events hitting the same countries share
    most of their answer, so we resample source-country groups (cluster bootstrap), not single events."""
    import numpy as np
    df = pd.DataFrame(rows)
    df = df[df["gt"] == label].pivot(index="case", columns="variant", values=metric)
    cluster = df.index.map(lambda k: "+".join(by_key[k]["countries"]) if k in by_key else k)
    groups = [df[cluster == c] for c in cluster.unique()]
    rng = np.random.default_rng(0)
    pairs = [("B + dependency/exposure", "random"), ("C + centrality", "random"), ("A severity only", "random"),
             ("B + dependency/exposure", "A severity only"), ("C + centrality", "B + dependency/exposure")]
    out = []
    for a, b in pairs:
        stats = []
        for _ in range(n):
            pick = pd.concat([groups[i] for i in rng.integers(0, len(groups), len(groups))])
            stats.append((pick[a] - pick[b]).mean())
        out.append({"gt": label, "metric": metric, "comparison": "{} minus {}".format(a, b),
                    "diff": round((df[a] - df[b]).mean(), 3), "ci_low": round(np.percentile(stats, 2.5), 3),
                    "ci_high": round(np.percentile(stats, 97.5), 3), "clusters": len(groups)})
    return out


def main():
    by_key = {e["event_key"]: e for e in events()}
    cases, gt = gt1(by_key)
    rows = evaluate(cases, "GT1 news (all labels)")
    strong, _ = gt1(by_key, ("strong", "medium"))
    rows += evaluate(strong, "GT1 news (strong+medium)")
    g2 = gt2(by_key)
    print("GT2: {} Red events 2019-22 with an unusual import drop from the hit country".format(len(g2)))
    rows += evaluate(g2, "GT2 trade drops")

    per_case = pd.DataFrame(rows)
    per_case.round(3).to_csv(ROOT / "results" / "validation_cases.csv", index=False)
    summary = summarise(rows)
    summary.to_csv(ROOT / "results" / "validation_summary.csv")
    pd.set_option("display.width", 200)
    print(per_case[per_case["gt"].str.startswith("GT1 news (all")][
        ["case", "variant", "n_ranked", "n_truth", "truth_reached", "P@3", "R@5", "Hit@1", "top5"]].round(3).to_string(index=False))
    print()
    print(summary.to_string())

    boot = pd.DataFrame(bootstrap(rows, by_key, "GT2 trade drops", "P@1") + bootstrap(rows, by_key, "GT2 trade drops", "P@3")
                        + bootstrap(rows, by_key, "GT1 news (all labels)", "P@3"))
    boot.to_csv(ROOT / "results" / "validation_bootstrap.csv", index=False)
    print()
    print(boot.to_string(index=False))

    # negative control: what does the engine say for an event with no reported overseas impact?
    for nc in gt["negative_controls"]:
        rk = run(weights=DEFAULT_WEIGHTS, **case_inputs(nc, by_key))
        print("\nnegative control {}: {} countries ranked, top 3 {}".format(
            nc["id"], len(rk), [(i, round(s, 3)) for i, s in rk[:3]]))


if __name__ == "__main__":
    main()

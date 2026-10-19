"""Load the supply-chain graph into Neo4j from data/graph/*.json (made by spark_jobs/export_graph.py).

    python -m graph.load_neo4j

Wipes the graph and rebuilds it, so rerunning is safe. Uses UNWIND: one query per batch of rows
instead of one query per row.

    (:Port)-[:LOCATED_IN]->(:Country)
    (:Country)-[:SUPPLIES {hs2, product, share, value_usd, rank}]->(:Country)    supplier -> importer
    (:Country)-[:EXPORTS {value_usd}]->(:Product)
    (:Product)-[:USED_BY]->(:Industry)
"""
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "graph"


def rows(name):
    with open(DATA / (name + ".json"), encoding="utf-8") as f:
        return json.load(f)


def driver():
    load_dotenv(ROOT / ".env")
    return GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", os.environ["NEO4J_PASSWORD"]))


def batched(session, query, data, size=1000):
    for i in range(0, len(data), size):
        session.run(query, rows=data[i:i + size]).consume()


def main():
    products = rows("products")
    names = {p["hs2"]: p["name"] for p in products}
    supplies = rows("supplies")
    for s in supplies:
        s["product"] = names[s["hs2"]]

    with driver() as d, d.session() as s:
        s.run("MATCH (n) DETACH DELETE n").consume()
        for label, key in [("Country", "iso3"), ("Product", "hs2"), ("Port", "wpi"), ("Industry", "name")]:
            s.run("CREATE CONSTRAINT IF NOT EXISTS FOR (n:{0}) REQUIRE n.{1} IS UNIQUE".format(label, key)).consume()

        batched(s, """UNWIND $rows AS r
            MERGE (c:Country {iso3: r.iso3})
            SET c.name = r.name, c.events_5y = r.events_5y, c.serious_5y = r.serious_5y,
                c.is_reporter = r.is_reporter""", rows("countries"))
        batched(s, """UNWIND $rows AS r
            MERGE (p:Product {hs2: r.hs2}) SET p.name = r.name, p.category = r.category
            WITH p, r UNWIND r.industries AS ind
            MERGE (i:Industry {name: ind})
            MERGE (p)-[:USED_BY]->(i)""", products)
        batched(s, """UNWIND $rows AS r
            // a port can sit in a country with no big trade link to our 20 importers - Colombo is a
            // transshipment hub, Sri Lanka itself barely trades with them - so create the country if needed
            MERGE (c:Country {iso3: r.iso3})
              ON CREATE SET c.name = r.country_name, c.events_5y = 0, c.serious_5y = 0, c.is_reporter = false
            MERGE (p:Port {wpi: r.wpi_number})
            SET p.name = r.port_name, p.latitude = r.latitude, p.longitude = r.longitude,
                p.severe_days_5y = r.severe_days_5y, p.max_gust_kmh = r.max_gust_kmh
            MERGE (p)-[:LOCATED_IN]->(c)""", rows("ports"))
        batched(s, """UNWIND $rows AS r
            MATCH (a:Country {iso3: r.src}), (b:Country {iso3: r.dst})
            CREATE (a)-[:SUPPLIES {hs2: r.hs2, product: r.product, share: r.share,
                                   value_usd: r.value_usd, rank: r.rank}]->(b)""", supplies)
        batched(s, """UNWIND $rows AS r
            MATCH (c:Country {iso3: r.iso3}), (p:Product {hs2: r.hs2})
            MERGE (c)-[e:EXPORTS]->(p) SET e.value_usd = r.value_usd""", rows("exports"))

        counts = s.run("""MATCH (n) WITH labels(n)[0] AS label, count(*) AS n RETURN label, n ORDER BY label""").data()
        rels = s.run("""MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS n ORDER BY type""").data()
    for c in counts:
        print("{:<10} {:>6,} nodes".format(c["label"], c["n"]))
    for r in rels:
        print("{:<10} {:>6,} relationships".format(r["type"], r["n"]))


if __name__ == "__main__":
    main()

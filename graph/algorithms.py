"""Run Neo4j Graph Data Science algorithms on the trade graph and write the results onto the nodes.

    python -m graph.algorithms

The trade graph for the algorithms: one edge per supplier -> importer pair, using the strongest
product link between them (max share). Edge cost = -log(share): path costs ADD, but dependence
MULTIPLIES (58% of 40% is 23%), and -log turns one into the other - so the cheapest path between
two countries is the strongest chain of dependence.

Written to each Country node:
    out_degree        how many importers it supplies (with >= 1% share)
    in_degree         how many suppliers it relies on
    supply_strength   sum of its shares across importers - how much others lean on it
    betweenness       how often it sits on the strongest dependence chains between other countries
    betweenness_norm  the same scaled to 0..1 (used by the impact score)
    pagerank          influence: being relied on by countries that are themselves relied on
    community         Louvain cluster of countries that trade mostly with each other
"""
from graph.load_neo4j import driver

PROJECT = """
MATCH (a:Country)-[r:SUPPLIES]->(b:Country)
WITH a, b, max(r.share) AS share
RETURN gds.graph.project($name, a, b,
    {relationshipProperties: {share: share, cost: -log(share)}},
    {undirectedRelationshipTypes: $undirected})
"""


def main():
    with driver() as d, d.session() as s:
        for name in ("trade", "trade_undirected"):
            s.run("CALL gds.graph.drop($name, false) YIELD graphName", name=name).consume()
        s.run(PROJECT, name="trade", undirected=[]).consume()
        s.run(PROJECT, name="trade_undirected", undirected=["*"]).consume()

        s.run("CALL gds.degree.write('trade', {writeProperty: 'out_degree'})").consume()
        s.run("CALL gds.degree.write('trade', {orientation: 'REVERSE', writeProperty: 'in_degree'})").consume()
        s.run("""CALL gds.degree.write('trade', {relationshipWeightProperty: 'share',
                                                 writeProperty: 'supply_strength'})""").consume()
        s.run("""CALL gds.betweenness.write('trade', {relationshipWeightProperty: 'cost',
                                                      writeProperty: 'betweenness'})""").consume()
        s.run("""CALL gds.pageRank.write('trade', {relationshipWeightProperty: 'share',
                                                   writeProperty: 'pagerank'})""").consume()
        s.run("""CALL gds.louvain.write('trade_undirected', {relationshipWeightProperty: 'share',
                                                             writeProperty: 'community'})""").consume()
        # countries with no trade links (Sri Lanka: Colombo is transshipment) aren't in the projection
        s.run("""MATCH (c:Country)
                 SET c.out_degree = coalesce(c.out_degree, 0), c.in_degree = coalesce(c.in_degree, 0),
                     c.supply_strength = coalesce(c.supply_strength, 0.0),
                     c.betweenness = coalesce(c.betweenness, 0.0), c.pagerank = coalesce(c.pagerank, 0.0)
              """).consume()
        s.run("""MATCH (c:Country) WITH max(c.betweenness) AS top
                 MATCH (c:Country) SET c.betweenness_norm = CASE WHEN top > 0 THEN c.betweenness / top ELSE 0 END
              """).consume()

        for prop, label in [("supply_strength", "relied on the most (sum of shares)"),
                            ("betweenness", "bridges on dependence chains (betweenness)"),
                            ("pagerank", "most influential (PageRank)")]:
            top = s.run("MATCH (c:Country) RETURN c.iso3 AS iso3, c.name AS name, c[$p] AS v "
                        "ORDER BY v DESC LIMIT 6", p=prop).data()
            print("\n" + label + ":")
            for r in top:
                print("   {:<4} {:<28} {:.3f}".format(r["iso3"], (r["name"] or "")[:28], r["v"]))

        groups = s.run("""MATCH (c:Country) WITH c.community AS g, collect(c.iso3) AS members, count(*) AS n
                          WHERE n >= 4 RETURN n, members ORDER BY n DESC LIMIT 5""").data()
        print("\ntrade communities (Louvain):")
        for g in groups:
            print("   {:>2} countries: {}".format(g["n"], ", ".join(sorted(g["members"])[:14])))


if __name__ == "__main__":
    main()

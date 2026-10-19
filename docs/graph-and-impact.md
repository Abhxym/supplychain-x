# Phase 5: supply-chain graph and cascading impact

```bash
python scripts/spark_run.py export_graph   # gold -> data/graph/*.json (Spark)
python -m graph.load_neo4j                 # build the graph in Neo4j
python -m graph.algorithms                 # centrality + communities (Neo4j GDS)
python -m impact.run_events                # score 556 historical events -> Postgres
python -m uvicorn api.main:app --port 8000 # Cascade Explorer: http://localhost:8000
```

## The graph (Neo4j, 2023 trade)

| Nodes | | Relationships | |
|---|---|---|---|
| Country | 102 | `SUPPLIES {product, share, value_usd}` supplier -> importer | 3,554 (links >= 1% share) |
| Product | 12 | `EXPORTS` country -> product | 1,220 |
| Industry | 13 | `USED_BY` product -> industry | 24 |
| Port | 45 | `LOCATED_IN` port -> country | 45 |

Explore it at http://localhost:7474, e.g.
`MATCH p=(:Country {iso3:'CHN'})-[:SUPPLIES {product:'Electronics and electrical equipment'}]->() RETURN p`

**Caveat:** trade comes from our 20 reporting countries, so `SUPPLIES` arrows only point *into* those 20.
Centrality means "importance to these 20 economies", not to the whole world.

**Trade data has a blind spot: transshipment.** Colombo (Sri Lanka) is a top-25 container port, but the
cargo it handles is just passing through, so Sri Lanka has no trade link >= 1% into our 20 countries.
Its port node is kept and the country node created from the port.

## Graph algorithms (Neo4j Graph Data Science)

Edge cost = `-log(share)`: path costs add while dependence multiplies (58% of 40% = 23%), and the log
turns one into the other - so the cheapest path is the strongest chain of dependence.

| Algorithm | Top result | Meaning |
|---|---|---|
| Weighted degree (sum of shares) | China 7.86, USA 5.50, Germany 3.73 | who the most importers lean on |
| Betweenness (cost = -log share) | China 518, USA 259, Germany 148 | bridges on the strongest dependence chains |
| PageRank (share-weighted) | USA, Singapore, China | relied on by countries that are themselves relied on |
| Louvain communities | 4 blocs | Europe · Asia-Pacific · Americas · Middle East + India - found with no geography given |

## Impact score

```
ImpactScore = (w1*S + w2*D + w3*E + w4*C + w5*T) * decay^hop
default weights 0.30, 0.30, 0.15, 0.10, 0.15 (configurable, always normalised to sum 1), decay 0.6
```

| Term | Meaning | Source |
|---|---|---|
| S severity | Red 1.0, Orange 0.6, Green 0.3 - **raised to >= 0.8 if our weather data shows storm-force gusts (>= 89 km/h) or very heavy rain (>= 115.6 mm) at a major port of a hit country during the event** | GDACS + Open-Meteo |
| D dependency | product of shares along the strongest chain, e.g. CHN -> IND electronics 0.58 | gold/dependencies |
| E exposure | yearly value of the affected imports, log-scaled 0..1 within the result | gold/dependencies |
| C centrality | normalised betweenness | Neo4j GDS |
| T duration | days / 30, capped at 1 | GDACS |

The cascade is a variable-length Cypher match (up to 3 hops), only following links with >= 5% share and
**staying on one product** - Chinese electronics -> India's electronics -> India's electronics customers.
It never jumps from electronics to cereals. Industries come from a simple product -> industry mapping.

The weights are parameters of the framework, not claimed to be universally correct. Phase 6 compares
variants (severity only / + exposure / + centrality) against historical cases.

## Results

556 events scored (every Orange/Red event with a country + every tropical cyclone, 2019-2023), 0.6 s each.

- **Our own weather data raised the severity of 50 of them.** Typhoon Hagibis: GDACS Green (0.3) ->
  engine 0.8 after finding 162 km/h gusts at Tokyo, 158 km/h + 109 mm rain at Yokohama on 12 Oct 2019.
- Highest-impact events found: Hurricane Eta (2020), China floods (2021), **Hurricane Ian (2022)**,
  **Hurricane Ida (2021)** - the last two famously shut Gulf of Mexico ports and refineries.
- "What if China is disrupted": all 19 other tracked economies are hit at the first hop, led by India
  (58% of its electronics from China) - China is central enough that everyone depends on it directly.

## Disruption Intelligence dashboard (UI)

`api/main.py` (FastAPI) + `ui/` (D3, canvas). http://localhost:8000, API docs at /docs.

- **Dot-matrix world map** (canvas): every land pixel on a 5 px grid is a dot. Countries in the cascade
  heat up wave by wave (teal -> yellow -> orange -> red by impact) over a blurred glow; supply links animate
  out hop by hop on an SVG layer; the hit country pulses with a warning marker, the three hardest-hit get
  orange markers, and our weather evidence appears as an incident chip ("162 km/h gusts · Tokyo Ko").
  Countries are found per dot with a bounding-box pre-check + `d3.geoContains`, built once per resize.
- **Left:** weekly disaster intensity 2019-2023 (orange tips = orange/red weeks, red line = selected event)
  and monthly severe port-weather days as spikes; an insight card explaining the result in one sentence.
- **Right:** gauge rings - countries in the cascade, peak impact, severity (cyan when our weather data raised it).
- **Bottom:** industry x country dot matrix of the cascade, and events by alert level.
- **Top bar:** event picker (556 scored events, searchable) and the what-if simulator (countries, severity,
  duration, decay, minimum link share).

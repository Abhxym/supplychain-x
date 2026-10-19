# Architecture

```
                    SUPPLYCHAIN-X
                          │
             ┌────────────┴────────────┐
             ↓                         ↓
       BIG DATA ENGINE             GRAPH ENGINE
       Spark + Kafka               Neo4j + GDS
             └────────────┬────────────┘
                          ↓
                 DISRUPTION INTELLIGENCE
                          ↓
                CASCADING IMPACT ANALYSIS
                          ↓
                    WHAT-IF SIMULATION
```

## Data flow

```
 UN Comtrade ─┐
 Open-Meteo  ─┼─> ingestion scripts ─> bronze (raw parquet)
 GDACS       ─┤                           │ spark ETL: clean, dedupe, schema check
 Port index  ─┘                           ↓
                                        silver (clean parquet, partitioned by year/country)
                                          │ spark: joins, features, dependency scores
                                          ↓
                                        gold (analytics tables)
                                          │
                       ┌──────────────────┼──────────────────┐
                       ↓                  ↓                  ↓
                   PostgreSQL           Neo4j            ML models
                  (API tables)     (dependency graph)  (anomaly, severity)
                       └──────────────────┼──────────────────┘
                                          ↓
                                    impact engine
                                          ↓
                                       FastAPI ──> React dashboard
                                          ↑
 historical events ─> replay producer ─> Kafka ─> Spark Structured Streaming
```

## Why each piece is there

**Parquet + bronze/silver/gold.** Bronze keeps the raw download untouched so any later step can be rerun.
Silver is cleaned and typed. Gold is shaped for the questions we ask. Parquet is columnar, so a query that
needs 3 columns out of 40 only reads those 3. It's also compressed, and partitioning by year/country lets
Spark skip whole folders (partition pruning).

**Spark.** All the heavy transformations (joining millions of trade rows with events, computing shares and
windows) are written once in PySpark and run in parallel across partitions. The same DataFrame API is
used for streaming, so batch logic carries over.

**Kafka.** A durable, ordered log of events. Producers (our replay script) and consumers (Spark streaming,
the alert service) don't need to know about each other, and a consumer can restart from where it left off.

**Neo4j.** "Who depends on whom, through what, 3 hops away" is a traversal, which is awkward and slow
as recursive SQL joins. In a graph it's a single pattern match, and GDS gives us centrality and
community detection on top.

**PostgreSQL.** Plain structured data the API needs fast: countries, events, impact scores, alerts.

## Graph model

```
(:Country)-[:EXPORTS {value, year}]->(:Commodity)
(:Country)-[:IMPORTS {value, year}]->(:Commodity)
(:Country)-[:DEPENDS_ON {commodity, share}]->(:Country)
(:Port)-[:LOCATED_IN]->(:Country)
(:Port)-[:HANDLES]->(:Commodity)
(:Commodity)-[:USED_BY]->(:Industry)
(:Event)-[:AFFECTS]->(:Port | :Country)
```

## Impact score

```
ImpactScore = w1·S + w2·D + w3·E + w4·C + w5·T     (w1 + ... + w5 = 1)

S = event severity          D = dependency (trade share)
E = economic exposure       C = graph centrality
T = temporal persistence (duration)
```

The weights are configurable parameters of the framework, not claimed to be universally correct.
Impact is decayed per hop (level 0 = direct, 1 = direct partners, 2/3 = downstream).
Validation is done against historical disruptions using Precision@K / Recall@K.

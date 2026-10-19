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
 Open-Meteo  ─┼─> ingestion scripts ─> local landing zone (data/bronze)
 GDACS       ─┤                                   │ hdfs dfs -put
 Port index  ─┘                                   ↓
                     ┌──────────── HDFS (NameNode + 2 DataNodes, replication 2) ────────────┐
                     │  /lake/bronze  ── Spark ETL ──>  /lake/silver  ── Spark ──>  /lake/gold │
                     │  raw parquet     clean, dedupe   clean, typed,   joins,     analytics  │
                     │                  schema check    partitioned     features   tables     │
                     └──────────────────────────────────────────────────────────────────────┘
                                                                    │
                                        ┌───────────────────────────┼──────────────────┐
                                        ↓                           ↓                  ↓
                                    PostgreSQL                    Neo4j            ML models
                                   (API tables)              (dependency graph) (anomaly, severity)
                                        └───────────────────────────┼──────────────────┘
                                                                    ↓
                                                              impact engine
                                                                    ↓
                                                                 FastAPI ──> D3 dashboard
                                                                    ↑
 historical events ─> replay producer ─> Kafka ─> Spark Structured Streaming

 Spark runs as a standalone cluster: 1 master + 2 workers, all in Docker.
```

## Why each piece is there

**Parquet + bronze/silver/gold.** Bronze keeps the raw download untouched so any later step can be rerun.
Silver is cleaned and typed. Gold is shaped for the questions we ask. Parquet is columnar, so a query that
needs 3 columns out of 40 only reads those 3. It's also compressed, and partitioning by year/country lets
Spark skip whole folders (partition pruning).

**Hadoop HDFS.** The lake lives in a distributed file system instead of a plain folder. Files are cut
into blocks and every block is stored on 2 DataNodes. Block size is 1 MB here (real clusters use 128 MB)
so our few-MB files visibly split; at real scale tiny blocks would overload the NameNode's memory.
The NameNode only keeps the map of which block is where. If one DataNode dies, every block still has a
live copy, so nothing is lost and jobs keep running. On a single laptop this gives no speed-up (both
DataNodes share one disk); the point is the storage model, which is the same one a real cluster uses.
Spark runs on its own standalone scheduler rather than YARN. YARN and MapReduce are only started for
one phase 3 experiment (`docker compose --profile mapreduce up -d`): the same job written as a C++
Hadoop Streaming job and in Spark, timed against each other ([experiments.md](experiments.md)).

**Spark.** All the heavy transformations (joining millions of trade rows with events, computing shares and
windows) are written once in PySpark and run in parallel across partitions. The same DataFrame API is
used for streaming, so batch logic carries over.

**Kafka.** A durable, ordered log of events. Producers (our replay script) and consumers (Spark streaming,
the alert service) don't need to know about each other, and a consumer can restart from where it left off.

**Neo4j.** "Who depends on whom, through what, 3 hops away" is a traversal, which is awkward and slow
as recursive SQL joins. In a graph it's a single pattern match, and GDS gives us centrality and
community detection on top.

**PostgreSQL.** Plain structured data the API needs fast: countries, events, impact scores, alerts.

**D3 instead of React.** The plan said React. The dashboard was built with D3 and plain JavaScript instead:
the hard part is drawing (a dot-matrix map, cascade animation, network view), which is D3's job either way,
and React would add a build step and a framework without adding a feature. FastAPI serves the three
files in `ui/` as they are.

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

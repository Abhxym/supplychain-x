# SUPPLYCHAIN-X

**A distributed big-data platform for supply-chain disruption detection and graph-based cascading impact analysis.**

When a port shuts down, a cyclone hits, or a route gets cut off, the damage rarely stops at that one place.
It moves through whoever depends on it: the commodities that pass through, the countries that import them,
and the industries that need those goods. SUPPLYCHAIN-X tries to make that chain visible.

It brings together trade, weather and disruption-event data, stores it in a Hadoop HDFS data lake,
processes it with Apache Spark (batch) and Kafka + Spark Structured Streaming (live), models the dependencies as a graph in Neo4j, and scores how far
and how hard a disruption is likely to spread.

## Research questions

1. Can heterogeneous supply-chain, environmental and event data be integrated through distributed
   batch/stream processing and graph analytics to identify the downstream entities likely to be affected
   by a disruption?
2. Does graph-based dependency analysis give more interpretable disruption-impact results than an
   isolated prediction model?

## Architecture (short version)

```
 Historical data ──> HDFS data lake (Parquet: bronze/silver/gold) ──┐
                                                                   ├──> Spark ──> PostgreSQL / Neo4j / ML ──> Impact engine ──> FastAPI ──> React dashboard
 Live events ─────> Kafka topics ──> Structured Streaming ─────────┘
```

More detail in [docs/architecture.md](docs/architecture.md).

## Stack

| Layer          | Tool                                  |
|----------------|---------------------------------------|
| Storage        | Hadoop HDFS (2 DataNodes) + Parquet, bronze/silver/gold |
| Batch          | Apache Spark cluster (PySpark, Spark SQL), 1 master + 2 workers |
| Baseline       | Hadoop MapReduce (one job, to compare against Spark) |
| Streaming      | Apache Kafka + Spark Structured Streaming |
| Graph          | Neo4j + Graph Data Science            |
| Relational     | PostgreSQL                            |
| ML             | scikit-learn (Isolation Forest, RF)   |
| API            | FastAPI                               |
| Frontend       | React                                 |

## Data sources (V1 core)

- **UN Comtrade** – bilateral trade by commodity (HS code)
- **Open-Meteo historical API** – weather observations
- **GDACS / EM-DAT** – natural disaster events
- **World Port Index** – port locations

Extensions (later): GDELT news events, AIS/maritime data.

## Running it

You need Docker Desktop (give it ~8 GB of RAM) and Python 3.12. Spark and Hadoop run in Docker,
nothing else to install.

```bash
cp .env.example .env                     # then add your COMTRADE_API_KEY
docker compose up -d                     # kafka, postgres, neo4j, hdfs, spark
python -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt
python scripts/check_services.py         # all five should say [ok]

# phase 1: download the raw data into the local landing zone
python -m ingestion.reference
python -m ingestion.comtrade
python -m ingestion.ports
python -m ingestion.gdacs
python -m ingestion.weather

# put it into HDFS and check Spark can read it
python scripts/hdfs_load_bronze.py
docker exec scx-spark-master /opt/spark/bin/spark-submit /opt/scx/spark_jobs/smoke_test.py
```

| Service          | URL                      |
|------------------|--------------------------|
| HDFS NameNode    | http://localhost:9870    |
| Spark master     | http://localhost:8081    |
| Spark job (live) | http://localhost:4040    |
| Kafka UI         | http://localhost:8080    |
| Neo4j            | http://localhost:7474    |
| Postgres         | localhost:5433           |

More on what to look at where: [docs/where-to-look.md](docs/where-to-look.md).

## Project status

Work in progress – see [docs/roadmap.md](docs/roadmap.md) for the plan and what's done so far.

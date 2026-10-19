# SUPPLYCHAIN-X

**A distributed big-data platform for supply-chain disruption detection and graph-based cascading impact analysis.**

When a port shuts down, a cyclone hits, or a route gets cut off, the damage rarely stops at that one place.
It moves through whoever depends on it: the commodities that pass through, the countries that import them,
and the industries that need those goods. SUPPLYCHAIN-X tries to make that chain visible.

It brings together trade, weather and disruption-event data, processes it with Apache Spark (batch) and
Kafka + Spark Structured Streaming (live), models the dependencies as a graph in Neo4j, and scores how far
and how hard a disruption is likely to spread.

## Research questions

1. Can heterogeneous supply-chain, environmental and event data be integrated through distributed
   batch/stream processing and graph analytics to identify the downstream entities likely to be affected
   by a disruption?
2. Does graph-based dependency analysis give more interpretable disruption-impact results than an
   isolated prediction model?

## Architecture (short version)

```
 Historical data ──> Data lake (Parquet: bronze/silver/gold) ──┐
                                                              ├──> Spark ──> PostgreSQL / Neo4j / ML ──> Impact engine ──> FastAPI ──> React dashboard
 Live events ─────> Kafka topics ──> Structured Streaming ────┘
```

More detail in [docs/architecture.md](docs/architecture.md).

## Stack

| Layer          | Tool                                  |
|----------------|---------------------------------------|
| Storage        | Parquet data lake (bronze/silver/gold)|
| Batch          | Apache Spark (PySpark, Spark SQL)     |
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

## Running the infrastructure

You need Docker Desktop running.

```bash
cp .env.example .env
docker compose up -d
python scripts/check_services.py
```

| Service   | URL                      |
|-----------|--------------------------|
| Kafka UI  | http://localhost:8080    |
| Neo4j     | http://localhost:7474    |
| Postgres  | localhost:5432           |

## Project status

Work in progress – see [docs/roadmap.md](docs/roadmap.md) for the plan and what's done so far.

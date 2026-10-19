# Roadmap

Each phase ends with something that runs. Don't start the next one until the current one works.

## Phase 0 – Foundation  ✅ done
- [x] Repo layout, README, architecture notes
- [x] docker-compose: Kafka (KRaft), Kafka UI, Postgres, Neo4j + GDS
- [x] Postgres schema
- [x] Everyone can `docker compose up -d` and pass `scripts/check_services.py`

**Install:** Docker Desktop, Git, Python 3.11/3.12. Spark and Hadoop run in Docker - nothing else to install.

## Phase 1 – Ingestion (bronze layer)  ✅ done
- [x] Countries + HS commodity reference tables
- [x] UN Comtrade downloader → `data/bronze/trade/` (20 countries, 12 HS chapters, 2019-23, ~330k rows)
- [x] Open-Meteo daily weather for 45 major ports → `data/bronze/weather/` (2019-23, 82k rows)
- [x] GDACS disaster events → `data/bronze/events/gdacs/` (2019-23, ~49k unique events, 361 orange/red)
- [x] World Port Index → `data/bronze/ports/` (3,807 ports)

Rule: bronze is never edited by hand. Every file comes from a script, so the whole lake can be rebuilt.

Rebuild everything: `ingestion.reference` → `ingestion.comtrade` → `ingestion.ports` → `ingestion.gdacs` → `ingestion.weather`

Data issues found, to fix in silver:
- GDACS: long events repeat in every month they span; alert level written as both `Green` and `GREEN`;
  one event can list several countries (`affectedcountries`)
- WPI: `country_code` holds country names, not codes; index numbers 400 and 46135 are used twice;
  coordinates are strings
- Comtrade: partner `W00` / code 0 is the World total row, not a country - exclude it when computing shares

## Phase 2 – Hadoop + Spark ETL (silver + gold)  ✅ done
- [x] HDFS cluster in Docker: 1 NameNode + 2 DataNodes, replication 2, 1 MB blocks (demo setting, real clusters use 128 MB)
- [x] Spark standalone cluster: 1 master + 2 workers (2 cores, 1.5 GB each), reads/writes HDFS
- [x] `scripts/hdfs_load_bronze.py` copies the local landing zone into `hdfs:///lake/bronze`
- [x] Smoke test: Spark sums world trade per year straight from HDFS on both workers
- [x] Silver layer on HDFS, one Spark job per source with data-quality gates
      (`python scripts/spark_run.py silver`, details in [data-quality.md](data-quality.md)):
      `countries` (245, ISO3 key) · `trade` (326,775) + `trade_totals` (2,400) · `events` (48,827)
      + `event_countries` (43,785) · `ports` (3,805, all with ISO3) · `weather` (82,170, severe-day flags)
- [x] Gold on HDFS (`python scripts/spark_run.py gold`):
      `dependencies` (142,735: importer x product x supplier x year, trade share, rank) ·
      `concentration` (1,200: supplier count, HHI, top supplier) ·
      `country_event_features` (disasters per country/year, by type) · `port_weather_features` (225)
- [x] Countries, commodities and dependencies loaded into Postgres over JDBC (Spark writes in parallel)
- [x] Fault tolerance demo: DataNode stopped, Spark still read all 653,082 rows with identical
      checksums, HDFS healed itself on restart ([hdfs-failover-demo.md](hdfs-failover-demo.md))

Flow: ingestion scripts → local landing zone (`data/bronze`) → HDFS `/lake/bronze` → Spark → `/lake/silver` → `/lake/gold`

## Phase 3 – Optimization experiments  ✅ done
Measured on a x10 copy of the real trade data (3.3M rows), median of 3 runs after a warm-up.
Full write-up: [experiments.md](experiments.md), raw numbers: `results/benchmarks.csv`.
- [x] E0 Parquet vs CSV: 2.9x faster
- [x] E1 shuffle partitions 1 -> 8: 2.0x faster, no gain beyond 8
- [x] E2 broadcast join: 1.7x faster than sort-merge
- [x] E3 partition pruning: 1.3x (Parquet min/max stats already skip most data)
- [x] E4 caching: 1.9x once filled, but slower if filled for only 3 quick queries
- [x] E5 1 vs 2 workers: 1.06x - fixed costs dominate at this size
- [x] E6 **Hadoop MapReduce vs Spark**: same job, same output, same hardware budget - Spark 2.0x faster
      (MapReduce side written in C++ with Hadoop Streaming, run on YARN)

## Phase 4 – Streaming
- Topics: `supplychain.events`, `supplychain.weather`, `supplychain.alerts`
- Replay producer: pushes historical events in timestamp order (with a speed-up factor)
- Spark Structured Streaming consumer: validate schema → enrich with gold tables → write alerts
- Checkpointing + watermarks

## Phase 5 – Graph + impact engine
- Load gold tables into Neo4j
- Degree + betweenness centrality, shortest paths, optional Louvain communities
- Cascading impact: BFS from the hit node, score per hop, store in `impact_scores`

## Phase 6 – ML + validation
- Isolation Forest on trade / weather series for anomalies
- Severity classifier (RF / logistic regression) – a side component, not the headline
- Experiment: severity only vs + exposure vs + centrality, compared with Precision@K / Recall@K
  against known historical disruptions

## Phase 7 – API + dashboard
- FastAPI: `/events`, `/impact/{event_id}`, `/graph/{entity_id}`, `/alerts`, `POST /simulate`
- React: risk map, live events, graph view, analytics, what-if simulator

## Phase 8 – Freeze + write-up
Experiments, report, paper, demo script, viva prep. No new features.

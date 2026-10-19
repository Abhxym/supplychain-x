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

## Phase 4 – Streaming  ✅ done
Details and results: [streaming.md](streaming.md)
- [x] Topics `supplychain.events`, `supplychain.alerts`, `supplychain.events.dlq` (retention capped)
- [x] Replay producer: real GDACS events in time order, sped up, idempotent, can inject broken messages
- [x] Spark Structured Streaming: validate -> DLQ, enrich with gold (ports, nearest port, downstream
      dependents), alert rule, alerts to Kafka + events/alerts to Postgres (idempotent)
- [x] Checkpointing on HDFS: driver killed mid-stream, restart caught up to exactly 1,297 events, none twice
- [x] Watermark: daily event counts in event time, 2 days allowed lateness
- [x] Found: GDACS rated Typhoon Hagibis Green - our port rule still raised it

## Phase 5 – Graph + impact engine  ✅ done
Details: [graph-and-impact.md](graph-and-impact.md)
- [x] Gold -> Neo4j: 102 countries, 12 products, 13 industries, 45 ports, 3,554 SUPPLIES links (2023)
- [x] GDS: weighted degree, betweenness (cost = -log share), PageRank, Louvain (4 trade blocs found)
- [x] Cascading impact engine: one-product chains up to 3 hops, configurable weighted score with decay
- [x] Weather cross-check raises severity (50 of 556 events, incl. Typhoon Hagibis)
- [x] 556 historical events scored into `impact_scores` + `impact_runs`
- [x] Cascade Explorer UI (FastAPI + D3): animated world map, what-if simulator

## Phase 6 – ML + validation  ✅ done
- [x] Isolation Forest on trade drops and port weather (`python -m ml.anomalies`) - the strangest drops are
      political (Russian fuel 2023, Ukrainian cereals 2022), not weather
- [x] Severity classifier (RF / logistic regression), a side component (`python -m ml.severity`):
      macro F1 0.45 vs 0.33 for "always Green"; context alone cannot replace the event's physical size
- [x] Sourced ground truth of known disruptions (`ml/ground_truth.json`): 4 cases + 1 negative control,
      exclusions documented
- [x] Experiment: severity only vs + trade vs + centrality, Precision@K / Recall@K / Hit@K, random floor,
      cluster bootstrap (`python -m ml.validate`). No variant proven better; trade dependency helps,
      centrality shows a hub bias. Write-up in [experiments.md](experiments.md)

## Phase 7 – API + dashboard  ✅ done
- [x] FastAPI: `/api/events`, `/api/impact/{event_id}`, `/api/graph/{iso3}`, `/api/alerts`, `POST /api/simulate`
      (+ `/api/countries`, `/api/stats`, `/api/anomalies`); docs at http://localhost:8000/docs
- [x] Dashboard: risk map, **live alerts** (polls the streaming job's alerts every 5 s), **graph view**
      (click a country: its suppliers and dependents), analytics, what-if simulator, unusual trade drops
- [x] D3 + plain JavaScript instead of React - same features, no build step (reason in architecture.md)
- [x] API tests: `python -m pytest -q` - 14 tests over every endpoint, skipped when the databases are down

## Phase 8 – Freeze + write-up
Experiments, report, paper, demo script, viva prep. No new features.

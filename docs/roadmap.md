# Roadmap

Each phase ends with something that runs. Don't start the next one until the current one works.

## Phase 0 – Foundation  ✅ done
- [x] Repo layout, README, architecture notes
- [x] docker-compose: Kafka (KRaft), Kafka UI, Postgres, Neo4j + GDS
- [x] Postgres schema
- [x] Everyone can `docker compose up -d` and pass `scripts/check_services.py`

**Install:** Docker Desktop, Git, Python 3.11/3.12, Java 17 (needed later for Spark).

## Phase 1 – Ingestion (bronze layer)  🔄 in progress
- [x] Countries + HS commodity reference tables
- [x] UN Comtrade downloader → `data/bronze/trade/` (20 countries, 12 HS chapters, 2019-23, ~330k rows)
- [ ] Open-Meteo historical weather for port/country coordinates → `data/bronze/weather/`
- [ ] GDACS disaster events → `data/bronze/events/`
- [ ] World Port Index → `data/bronze/ports/`

Rule: bronze is never edited by hand. Every file comes from a script, so the whole lake can be rebuilt.

## Phase 2 – Spark ETL (silver + gold)
- Spark dev container (avoids the winutils/Hadoop pain of running Spark natively on Windows)
- Clean, type, dedupe each source → silver, partitioned by `year` (and `country` where it helps)
- Features: trade_share, supplier_concentration (HHI), event_frequency, weather_severity flags
- Dependencies table → gold, loaded into Postgres

## Phase 3 – Optimization experiments
Measure, on our own data, baseline vs:
- partitioning + partition pruning
- broadcast join (small country/port lookups)
- caching reused DataFrames
- 1 / 4 / 8 / 16 shuffle partitions

Record real timings in `docs/experiments.md`. Never invent numbers.

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

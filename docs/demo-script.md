# Demo script (8-10 minutes)

Every timing below was measured in a full dry run on 2026-10-19 on the project laptop.
Rule for the day: **show, don't type.** Everything is started before the examiners sit down;
during the demo you only press Enter on commands that are already typed in a terminal.

## 30 minutes before

```bash
docker compose up -d                        # all containers (~1-2 min)
python scripts/check_services.py            # must print 5 x [ok]: kafka, postgres, neo4j, hdfs, spark
python scripts/kafka_topics.py --reset      # empty topics + alerts; scored events are kept
python -m uvicorn api.main:app --port 8000  # terminal A: the dashboard
python -m pytest -q                         # 16 passed - proof everything answers
```

Then open these tabs, in this order, and leave them open:

| Tab | URL | Shows |
|---|---|---|
| 1 Dashboard | http://localhost:8000 | the product |
| 2 HDFS | http://localhost:9870 -> Utilities -> Browse -> `/lake` | the data lake |
| 3 Kafka UI | http://localhost:8080 | topics, messages, the DLQ |
| 4 Spark | http://localhost:8081 (cluster), http://localhost:4040 (running job) | the cluster at work |
| 5 Neo4j | http://localhost:7474 | the graph |

Prepare two more terminals with the commands **typed but not run**:

```bash
python scripts/spark_run.py stream_events                                                     # terminal B
python -m ingestion.replay_producer --from 2019-09-01 --to 2019-10-31 --speed 86400 --bad 3   # terminal C
python -m ingestion.live_gdacs --once                                                         # terminal C, later
```

Start terminal B (streaming) **now**, not during the demo: it needs ~20-40 s to start and is then idle.
Check the internet works (the live step needs gdacs.org). Close everything else; Docker needs the memory.

## The demo

| Time | Show | Say (in your own words) |
|---|---|---|
| 0:00 | README diagram | "When a port or a country is hit, the damage travels through whoever depends on it. SUPPLYCHAIN-X makes that chain visible: trade, weather and disaster data, in a Hadoop data lake, processed by Spark in batch and in streaming, modelled as a graph in Neo4j, and scored." |
| 0:45 | Tab 2 HDFS | `/lake/bronze`, `silver`, `gold`. "Bronze is the raw download, never edited. Silver is cleaned with quality checks - a failed check stops the job. Gold is shaped for our questions. 2 DataNodes, every block stored twice - I stopped one DataNode and Spark still read all 653,082 rows with identical checksums." |
| 1:45 | Tab 4 Spark | 1 master, 2 workers. "All heavy work runs here. Same job on MapReduce in C++ took 34.7 s, Spark 17.4 s - 2x, because Spark keeps data in memory between steps." |
| 2:30 | Terminal C: **replay** | Press Enter. "These are 869 real GDACS disasters from Sep-Oct 2019, replayed into Kafka, one day of history per second. I slipped in 3 broken messages on purpose." |
| 2:40 | Tab 1, **Live alerts** card | Alerts start arriving (~30 s after the replay starts; all 55 within 90 s), new ones flash red. "The page asks the API every 5 s for alerts newer than the last one it has." |
| 3:30 | Tab 3 Kafka UI | `supplychain.events.dlq`: 3 messages, each with its reject reason. "Bad data doesn't crash the stream or disappear - it goes to a dead-letter queue with the reason." |
| 4:00 | Tab 1, pick **Typhoon Hagibis** (event picker or its alert) | "GDACS rated Hagibis Green. Our own port weather data found 162 km/h gusts in Tokyo on 12 Oct 2019, so the engine raised severity from 0.3 to 0.8." Watch the cascade spread hop by hop. |
| 5:00 | Industry matrix: **click a dot** | The breakdown card: "every score is explainable - 5 factors, the formula with the real numbers." |
| 5:30 | Map: **click Japan** | Graph view. "Thailand and Korea depend on Japan for steel, the UAE for vehicles - straight from Neo4j." Click China to walk the graph. |
| 6:15 | Simulator: China, severity 0.8 | "What if China is disrupted? All 19 other economies are hit at the first hop - India gets 58% of its electronics from China." |
| 7:00 | Terminal C: **live** | Press Enter (~36 s). "Now today's real disasters." Live alerts shows events from the last week; e.g. on 2026-10-19 the Red cyclone CHAMPI-26 over Japan. Click it -> its cascade. |
| 8:00 | Unusual trade drops card | "Machine learning - Isolation Forest - flags strange drops in yearly trade. It follows the event. Honest finding: the strangest drops are sanctions and wars, not storms; a 2-week closure vanishes in a year of trade." |
| 8:45 | `docs/experiments.md`, E9 table | "We tested the score against real cases - Japan 2011, Thailand 2011, Texas 2021, Turkiye 2023. Trade dependency helps; graph centrality has a hub bias; with fair statistics no version is proven better. The engine measures exposure, not confirmed damage." |
| 9:30 | stop | "Questions?" |

If time is short, drop 5:00 and 8:00. Never drop 4:00 (Hagibis) - it is the best single story.

## If something goes wrong

| Problem | Do this |
|---|---|
| No internet / gdacs.org down | Skip the live step. Say: "the live feed polls GDACS every 10 minutes; here is its first run" and show the Live mode section of `docs/streaming.md` (392 events -> 10 alerts). |
| Live step finds nothing new | It remembers what it already sent (`data/live/sent.json`). Run `--reset` beforehand, or delete that file. |
| Streaming job won't start | `python scripts/check_services.py`; then `docker compose restart spark-master spark-worker-1 spark-worker-2`. Meanwhile show the dashboard, which works without streaming. |
| Alerts don't appear | Is terminal B running and printing `batch ...` lines? A replay before the streaming job started is fine - it reads from the earliest offset. |
| Dashboard empty / event picker empty | `python -m impact.run_events` (~6 min) re-scores the 556 historical events. |
| Dashboard shows old behaviour or an API 404 | The API process is old: stop terminal A and start it again (`--reload` does not always notice changes on this laptop). |
| Port 8000 busy | `python -m uvicorn api.main:app --port 8010` and use that URL. |
| Laptop very slow | `docker compose stop kafka-ui` - nothing needs it except tab 3. |
| Everything broken | Screenshots in this order: dashboard with Hagibis cascade, Live alerts, graph view, Kafka DLQ - and walk through `docs/`. Take them during the rehearsal. |

## After the demo

`Ctrl+C` in terminals B and C, then stop the Spark driver too (Ctrl+C on the launcher does not):

```bash
docker exec scx-spark-master pkill -f stream_events.py
docker compose stop
```

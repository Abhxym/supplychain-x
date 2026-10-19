# Where to look at what

No extra setup per phase - one editor plus the web UIs the containers already give you.

| What                     | Where                                   | How                                              |
|--------------------------|-----------------------------------------|--------------------------------------------------|
| Code, docs, data folders | VS Code                                 | open the project folder                          |
| Parquet files (lake)     | terminal                                | `python scripts/peek.py data/bronze/trade`       |
|                          | VS Code                                 | "Parquet Viewer" extension, click any `.parquet` |
| Containers running?      | Docker Desktop → Containers             | or `docker compose ps`                           |
| Container logs           | Docker Desktop → click container → Logs | or `docker logs scx-kafka`                       |
| Kafka topics / messages  | Kafka UI                                | http://localhost:8080 (from phase 4)             |
| Postgres tables          | DBeaver (free)                          | host localhost, port **5433**, db supplychainx, user scx |
|                          | terminal                                | `docker exec -it scx-postgres psql -U scx -d supplychainx` |
| Neo4j graph              | Neo4j Browser                           | http://localhost:7474, user neo4j (from phase 5) |
| HDFS files, blocks, datanodes | HDFS NameNode UI                   | http://localhost:9870 → Utilities → Browse the file system |
|                          | terminal                                | `docker exec scx-namenode hdfs dfs -ls -R /lake` |
| Spark cluster / workers  | Spark master UI                         | http://localhost:8081                            |
| Spark job while running  | Spark job UI                            | http://localhost:4040 (only while a job runs)    |
| API                      | FastAPI docs                            | http://localhost:8000/docs (from phase 7)        |
| Dashboard                | browser                                 | http://localhost:5173 (from phase 7)             |
| Code history             | GitHub                                  | github.com/Abhxym/supplychain-x                  |

Passwords are in your `.env`.

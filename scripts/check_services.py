"""Quick sanity check that Kafka, Postgres and Neo4j are up and reachable.

Run after `docker compose up -d`:
    python scripts/check_services.py
"""
import os
import sys

from dotenv import load_dotenv

load_dotenv()


def check_kafka():
    from confluent_kafka.admin import AdminClient

    admin = AdminClient({"bootstrap.servers": os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")})
    meta = admin.list_topics(timeout=10)
    return f"{len(meta.brokers)} broker(s), {len(meta.topics)} topic(s)"


def check_postgres():
    import psycopg

    with psycopg.connect(
        host="localhost",
        port=os.getenv("POSTGRES_PORT", "5432"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
        dbname=os.getenv("POSTGRES_DB"),
    ) as conn:
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        ).fetchall()
    return f"{len(rows)} tables: " + ", ".join(sorted(r[0] for r in rows))


def check_neo4j():
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", os.getenv("NEO4J_PASSWORD")))
    with driver.session() as s:
        gds = s.run("RETURN gds.version() AS v").single()["v"]
    driver.close()
    return f"GDS {gds}"


def check_hdfs():
    import requests

    # the namenode's JMX endpoint reports cluster health as JSON
    url = "http://localhost:9870/jmx?qry=Hadoop:service=NameNode,name=FSNamesystemState"
    state = requests.get(url, timeout=5).json()["beans"][0]
    return f"{state['NumLiveDataNodes']} live datanode(s), {state['FilesTotal']} files"


def check_spark():
    import requests

    master = requests.get("http://localhost:8081/json/", timeout=5).json()
    alive = [w for w in master["workers"] if w["state"] == "ALIVE"]
    return f"{len(alive)} worker(s), {sum(w['cores'] for w in alive)} cores"


if __name__ == "__main__":
    failed = False
    checks = [
        ("kafka", check_kafka), ("postgres", check_postgres), ("neo4j", check_neo4j),
        ("hdfs", check_hdfs), ("spark", check_spark),
    ]
    for name, fn in checks:
        try:
            print(f"[ok]   {name:9} {fn()}")
        except Exception as e:  # noqa: BLE001 - we just want to report whatever broke
            failed = True
            print(f"[FAIL] {name:9} {e}")
    sys.exit(1 if failed else 0)

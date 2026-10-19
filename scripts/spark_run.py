"""Run a Spark job from spark_jobs/ on the cluster.

    python scripts/spark_run.py silver_countries
    python scripts/spark_run.py silver          # all silver jobs in order
    python scripts/spark_run.py gold            # gold tables + load into Postgres
    python scripts/spark_run.py stream_events   # phase 4 streaming job - runs until Ctrl-C

Spark's own INFO logging is hidden; our prints and errors come through.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

GROUPS = {
    "silver": ["silver_countries", "silver_trade", "silver_events", "silver_ports", "silver_weather"],
    "gold": ["gold_dependencies", "gold_risk_features", "gold_to_postgres"],
}
PG_DRIVER = "org.postgresql:postgresql:42.7.4"
KAFKA_CONNECTOR = "org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.3"
# jobs that talk to Postgres get the JDBC driver and the credentials; streaming jobs also get the Kafka connector
JDBC_JOBS = {"gold_to_postgres", "stream_events"}
STREAM_JOBS = {"stream_events"}

NOISE = (" INFO ", " WARN ", "WARNING: ", ":: ", "found org.", "downloading ", "[SUCCESSFUL ]",
         "confs: [default]", "Ivy Default Cache", "The jars for the packages", "artifacts copied",
         "retrieving ::", "loading settings", "resolving dependencies", "module:",
         "added as a dependency", "from central in")
# batch output tables never contain these, but a streaming console table does
TABLE_NOISE = ("---------", "|  ")

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def build(job, args=()):
    cmd, packages, conf = ["docker", "exec"], [], []
    if job in JDBC_JOBS:
        for var in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"):
            cmd += ["-e", "{}={}".format(var, os.environ[var])]
        packages.append(PG_DRIVER)
    if job in STREAM_JOBS:
        packages.append(KAFKA_CONNECTOR)
        # a streaming job holds its executors for as long as it runs: give it one worker (2 cores)
        # so the other worker stays free for batch jobs
        conf += ["--conf", "spark.cores.max=2"]
    if packages:
        # the spark user has no writable home, so point the package cache at /tmp
        conf += ["--packages", ",".join(packages), "--conf", "spark.jars.ivy=/tmp/.ivy2"]
    return cmd + ["scx-spark-master", "/opt/spark/bin/spark-submit",
                  "--conf", "spark.ui.showConsoleProgress=false",
                  "--conf", "spark.log.level=ERROR",  # spark 3.5+: only real errors, no plan dumps
                  *conf, "/opt/scx/spark_jobs/{}.py".format(job), *args]


def submit(job, args=()):
    print("=== " + " ".join((job,) + tuple(args)))
    start = time.time()
    r = subprocess.run(build(job, args), capture_output=True, text=True)
    kept = [l for l in r.stdout.splitlines() + r.stderr.splitlines()
            if l.strip() and not any(n in l for n in NOISE + TABLE_NOISE)]
    for line in kept:
        print("  " + line)
    print("  ({:.0f}s)".format(time.time() - start))
    if r.returncode != 0:
        raise SystemExit(job + " failed")
    return kept


def stream(job):
    """Long-running job: print its output as it happens, until it stops or Ctrl-C."""
    print("=== {} (Ctrl-C to stop)".format(job), flush=True)
    p = subprocess.Popen(build(job), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    try:
        for line in p.stdout:
            if line.strip() and not any(n in line for n in NOISE):
                print(line.rstrip(), flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        # stopping docker exec doesn't stop spark-submit inside the container, so kill it there too
        subprocess.run(["docker", "exec", "scx-spark-master", "pkill", "-f", "spark_jobs/" + job],
                       capture_output=True)
        p.terminate()
    return p.wait()


if __name__ == "__main__":
    for name in sys.argv[1:] or ["silver"]:
        for job in GROUPS.get(name, [name]):
            if job in STREAM_JOBS:
                sys.exit(stream(job))
            submit(job)

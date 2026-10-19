"""Run a Spark job from spark_jobs/ on the cluster.

    python scripts/spark_run.py silver_countries
    python scripts/spark_run.py silver          # all silver jobs in order
    python scripts/spark_run.py gold            # gold tables + load into Postgres

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
# jobs that talk to Postgres get the JDBC driver (downloaded once from Maven) and the credentials
JDBC_JOBS = {"gold_to_postgres"}
PG_DRIVER = "org.postgresql:postgresql:42.7.4"

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def submit(job):
    print("=== " + job)
    start = time.time()
    cmd = ["docker", "exec"]
    extra = []
    if job in JDBC_JOBS:
        for var in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"):
            cmd += ["-e", "{}={}".format(var, os.environ[var])]
        # the spark user has no writable home, so point the package cache at /tmp
        extra = ["--packages", PG_DRIVER, "--conf", "spark.jars.ivy=/tmp/.ivy2"]
    cmd += ["scx-spark-master", "/opt/spark/bin/spark-submit",
            "--conf", "spark.ui.showConsoleProgress=false",
            "--conf", "spark.log.level=ERROR",  # spark 3.5+: only real errors, no plan dumps
            *extra,
            "/opt/scx/spark_jobs/{}.py".format(job)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    noise = (" INFO ", " WARN ", "WARNING: ", ":: ", "found org.", "downloading ", "[SUCCESSFUL ]",
             "confs: [default]", "Ivy Default Cache", "The jars for the packages", "artifacts copied",
             "retrieving ::", "loading settings", "resolving dependencies", "---------", "|  ", "module:",
             "added as a dependency", "from central in")
    for line in r.stdout.splitlines() + r.stderr.splitlines():
        if line.strip() and not any(n in line for n in noise):
            print("  " + line)
    print("  ({:.0f}s)".format(time.time() - start))
    if r.returncode != 0:
        raise SystemExit(job + " failed")


if __name__ == "__main__":
    for name in sys.argv[1:] or ["silver"]:
        for job in GROUPS.get(name, [name]):
            submit(job)

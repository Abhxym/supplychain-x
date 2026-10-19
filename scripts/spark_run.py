"""Run a Spark job from spark_jobs/ on the cluster.

    python scripts/spark_run.py silver_countries
    python scripts/spark_run.py silver          # all silver jobs in order

Spark's own INFO logging is hidden; our prints and errors come through.
"""
import subprocess
import sys
import time

GROUPS = {
    "silver": ["silver_countries", "silver_trade", "silver_events", "silver_ports", "silver_weather"],
}


def submit(job):
    print("=== " + job)
    start = time.time()
    r = subprocess.run(
        ["docker", "exec", "scx-spark-master", "/opt/spark/bin/spark-submit",
         "--conf", "spark.ui.showConsoleProgress=false",
         "/opt/scx/spark_jobs/{}.py".format(job)],
        capture_output=True, text=True,
    )
    noise = (" INFO ", " WARN ", "WARNING: ")
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

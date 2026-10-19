"""E6: Hadoop MapReduce vs Spark on the same job, same data, same hardware budget.

    docker compose --profile mapreduce up -d     # YARN, needed once
    python scripts/build_mapreduce.py            # compile the C++ mapper/reducer
    python scripts/bench_mapreduce.py

Job: total trade value per reporter|product from the 92 MB CSV copy (3.3M lines).
    MapReduce: C++ mapper + combiner + reducer via Hadoop Streaming on YARN (2 NodeManagers x 2 cores)
    Spark:     the same aggregation in PySpark on the standalone cluster (2 workers x 2 cores)
Both are timed as the whole command, start to finish (job start-up included - that's part of
what each engine costs you), 1 warm-up + 3 timed runs, median reported. Both outputs are then
compared line by line, so we know they computed the same thing.
"""
import csv
import platform
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "benchmarks.csv"
PAUSE = ["scx-kafka", "scx-kafka-ui", "scx-neo4j", "scx-postgres"]
REPS = 3

MR = ["docker", "exec", "scx-resourcemanager", "mapred", "streaming",
      "-D", "mapreduce.job.reduces=2",
      "-files", "/opt/scx/mapreduce/bin/mapper,/opt/scx/mapreduce/bin/reducer",
      "-mapper", "mapper", "-combiner", "reducer", "-reducer", "reducer",
      "-input", "/lake/bench/trade_csv", "-output", "/lake/bench/out_mr"]
SPARK = [sys.executable, str(ROOT / "scripts" / "spark_run.py"), "bench_mr_spark"]


def hdfs(*args):
    return subprocess.run(["docker", "exec", "scx-namenode", "hdfs", "dfs", *args],
                          capture_output=True, text=True).stdout


def timed(cmd, before=None):
    if before:
        before()
    t = time.perf_counter()
    r = subprocess.run(cmd, capture_output=True, text=True)
    took = time.perf_counter() - t
    if r.returncode != 0:
        print(r.stdout[-2000:], r.stderr[-3000:])
        raise SystemExit("command failed: " + " ".join(cmd[:6]))
    return took


def race(name, cmd, before=None):
    timed(cmd, before)  # warm-up
    runs = [timed(cmd, before) for _ in range(REPS)]
    print("{:<10} runs {}  median {:.1f}s".format(name, ["{:.1f}".format(x) for x in runs], statistics.median(runs)))
    return runs


def output(path):
    lines = [l for l in hdfs("-cat", path + "/part-*").splitlines() if l.strip()]
    return {k: float(v) for k, v in (l.split("\t") for l in lines)}


if __name__ == "__main__":
    subprocess.run(["docker", "stop", *PAUSE], capture_output=True)
    try:
        mr = race("MapReduce", MR, before=lambda: hdfs("-rm", "-r", "-f", "-skipTrash", "/lake/bench/out_mr"))
        sp = race("Spark", SPARK)
    finally:
        subprocess.run(["docker", "start", *PAUSE], capture_output=True)

    a, b = output("/lake/bench/out_mr"), output("/lake/bench/out_spark")
    same = a.keys() == b.keys() and all(abs(a[k] - b[k]) <= 0.01 * max(1.0, abs(a[k])) * 1e-6 + 0.01 for k in a)
    print("same answer: {} ({} keys each)".format("YES" if same else "NO", len(a)))
    if not same:
        raise SystemExit("outputs differ - not a fair comparison")

    run_id = datetime.now().strftime("%Y-%m-%d %H:%M")
    with OUT.open("a", newline="") as f:
        w = csv.writer(f)
        for setting, runs, note in [
            ("Hadoop MapReduce (C++ streaming, combiner, 2 reducers, YARN 2x2 cores)", mr, "whole command"),
            ("Spark (PySpark, 2 workers x 2 cores)", sp, "whole command incl. spark-submit start-up"),
        ]:
            w.writerow([run_id, platform.node(), "E6 MapReduce vs Spark", setting,
                        round(statistics.median(runs), 3), round(min(runs), 3),
                        " ".join("{:.3f}".format(x) for x in runs), note])
    print("speed-up: Spark is {:.1f}x faster".format(statistics.median(mr) / statistics.median(sp)))

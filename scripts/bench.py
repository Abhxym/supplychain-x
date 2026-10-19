"""Run the phase 3 Spark experiments and save every measurement.

    python scripts/bench.py

Pauses kafka, kafka-ui, neo4j and postgres while timing (they are not used here and would
compete for CPU), runs spark_jobs/bench_spark.py, appends the results to
results/benchmarks.csv and restarts the paused services.
"""
import csv
import json
import platform
import subprocess
from datetime import datetime
from pathlib import Path

from spark_run import submit

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "benchmarks.csv"
PAUSE = ["scx-kafka", "scx-kafka-ui", "scx-neo4j", "scx-postgres"]


def collect(lines):
    return [json.loads(l.split("RESULT ", 1)[1]) for l in lines if "RESULT " in l]


if __name__ == "__main__":
    run_id = datetime.now().strftime("%Y-%m-%d %H:%M")
    subprocess.run(["docker", "stop", *PAUSE], capture_output=True)
    try:
        results = collect(submit("bench_spark", ["settings"]))
        for cores in ("2", "4"):
            # spark.cores.max caps the whole app: 2 cores = one executor = one worker
            results += collect(submit("bench_spark", ["cores", cores]))
    finally:
        subprocess.run(["docker", "start", *PAUSE], capture_output=True)

    new = not OUT.exists()
    with OUT.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["run", "machine", "experiment", "setting", "median_s", "min_s", "runs", "note"])
        for r in results:
            w.writerow([run_id, platform.node(), r["experiment"], r["setting"], r["median_s"], r["min_s"],
                        " ".join(str(x) for x in r["runs"]), r["note"]])

    print("\n{:<24} {:<48} {:>9}".format("experiment", "setting", "median s"))
    for r in results:
        print("{:<24} {:<48} {:>9.2f}".format(r["experiment"], r["setting"], r["median_s"]))
    print("\nsaved {} results to {}".format(len(results), OUT.relative_to(ROOT)))

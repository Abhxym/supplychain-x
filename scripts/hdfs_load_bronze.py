"""Copy the local bronze layer into HDFS at /lake/bronze.

The ingestion scripts download to data/bronze on this machine (the "landing zone").
This pushes that into HDFS, where Spark reads it from.

Runs `hdfs dfs` inside the namenode container, which sees ./data as /landing.
(Writing to HDFS straight from Windows doesn't work well - the client has to reach
every datanode directly, and those only exist on the docker network.)

    python scripts/hdfs_load_bronze.py
"""
import subprocess


def run(*args):
    r = subprocess.run(["docker", "exec", "scx-namenode", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"{' '.join(args)} failed:\n{r.stderr}")
    return r.stdout


def hdfs(*args):
    return run("hdfs", "dfs", *args)


if __name__ == "__main__":
    # right after a (re)start the namenode is read-only ("safe mode") until the
    # datanodes have reported their blocks - wait for that instead of failing
    run("hdfs", "dfsadmin", "-safemode", "wait")
    hdfs("-mkdir", "-p", "/lake")
    # -f overwrites, so rerunning after a new download is safe
    hdfs("-put", "-f", "/landing/bronze", "/lake/")
    print(hdfs("-du", "-h", "/lake/bronze"))

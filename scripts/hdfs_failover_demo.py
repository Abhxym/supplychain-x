"""HDFS fault-tolerance demo: switch off a DataNode and show nothing is lost.

    python scripts/hdfs_failover_demo.py

1. read the whole lake with Spark and fingerprint every table (both DataNodes up)
2. stop datanode2 - half of the "cluster" is gone
3. wait until the NameNode declares it dead, show fsck (every block still has a live copy)
4. read the whole lake again - same rows, same checksums
5. bring datanode2 back and show HDFS heal itself

Needs `dfs.namenode.heartbeat.recheck-interval=15000` in hadoop.env, otherwise step 3 takes ~10 minutes.
"""
import re
import subprocess
import sys
import time

VICTIM = "scx-datanode2"


def sh(*cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.stdout + r.stderr


def hdfs(*args):
    return sh("docker", "exec", "scx-namenode", "hdfs", *args)


def step(text):
    print("\n" + "=" * 70 + "\n" + text + "\n" + "=" * 70)


def datanodes():
    report = hdfs("dfsadmin", "-report")
    live = re.search(r"Live datanodes \((\d+)\)", report)
    dead = re.search(r"Dead datanodes \((\d+)\)", report)
    return int(live.group(1)) if live else 0, int(dead.group(1)) if dead else 0


def fsck():
    out = hdfs("fsck", "/lake")
    keep = ("Status:", "Total blocks", "Under-replicated", "Missing blocks:", "Corrupt blocks:")
    for line in out.splitlines():
        if line.strip().startswith(keep):
            print("   " + line.strip())


def read_lake():
    start = time.time()
    out = sh(sys.executable, "scripts/spark_run.py", "verify_lake")
    lines = [l.strip() for l in out.splitlines() if "TABLE" in l or "TOTAL" in l or "FAIL" in l]
    for l in lines:
        print("   " + l)
    print("   ({:.0f}s)".format(time.time() - start))
    return [l for l in lines if l.startswith("TABLE")]


step("1. Both DataNodes up - read every silver and gold table with Spark")
print("   live/dead datanodes: {} / {}".format(*datanodes()))
before = read_lake()

step("2. Stopping {} - one of the two machines holding the data".format(VICTIM))
print("   " + sh("docker", "stop", VICTIM).strip() + " stopped")

step("3. Waiting for the NameNode to notice (no heartbeat -> declared dead)")
t0 = time.time()
while datanodes()[1] == 0:
    if time.time() - t0 > 300:
        raise SystemExit("datanode not declared dead after 5 min - is the recheck interval set?")
    time.sleep(5)
print("   declared dead after {:.0f}s, live/dead: {} / {}".format(time.time() - t0, *datanodes()))
fsck()

step("4. Reading the whole lake again with only ONE DataNode left")
after = read_lake()
same = before == after
print("\n   every table identical to step 1: {}".format("YES" if same else "NO"))

step("5. Bringing {} back - HDFS heals itself".format(VICTIM))
sh("docker", "start", VICTIM)
t0 = time.time()
while datanodes() != (2, 0):
    time.sleep(5)
print("   rejoined after {:.0f}s, live/dead: {} / {}".format(time.time() - t0, *datanodes()))
time.sleep(10)
fsck()

sys.exit(0 if same else 1)

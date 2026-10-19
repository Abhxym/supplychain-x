# HDFS fault-tolerance demo

Switch off one of the two DataNodes and show that Spark still reads every table, byte for byte.

```bash
python scripts/hdfs_failover_demo.py
```

Takes about 3 minutes. Needs the demo setting `dfs.namenode.heartbeat.recheck-interval=15000` in
`hadoop.env`; with the default a silent DataNode is only declared dead after ~10.5 minutes.

## Result (2026-10-19)

| Step | What happened |
|---|---|
| 1. Both DataNodes up | Spark read all 11 silver/gold tables: 653,082 rows, checksum per table |
| 2. `docker stop scx-datanode2` | Half of the storage gone |
| 3. NameNode notices | Declared dead after 62 s. `fsck`: 413 blocks, **413 under-replicated, 0 missing**, HEALTHY |
| 4. Read everything again | Same 653,082 rows, every checksum identical |
| 5. `docker start scx-datanode2` | Rejoined after 10 s, under-replicated back to 0 on its own |

## What it shows

- **Replication is what saves the data.** Every block had a second copy on datanode1, so the reader
  simply used that one. "Under-replicated" means "only one copy left", which is a warning, not data loss.
- **Missing blocks stayed at 0.** That would only happen if *both* copies were gone.
- **Nobody had to tell Spark anything.** It asked the NameNode where the blocks were and was sent to
  the surviving DataNode.
- **HDFS heals itself.** When the node came back it reported its blocks and the cluster was fully
  replicated again without any manual step.

With only 2 DataNodes and replication 2, HDFS can't make a new copy while one node is down - there's
nowhere to put it. Real clusters use 3+ nodes and replication 3, so they re-copy blocks onto the
remaining machines automatically and can survive a second failure too.

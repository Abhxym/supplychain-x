# Phase 3 experiments

All numbers measured on our own machine (Windows 11, 12 logical cores, 16 GB RAM, Docker with 7.6 GB),
2026-10-19. Raw measurements, every run: [results/benchmarks.csv](../results/benchmarks.csv).

Re-run: `python scripts/bench.py` (E0-E5) and `python scripts/bench_mapreduce.py` (E6).

## Method

- **Data:** the real silver trade table copied 10 times (`copy_id` column) = 3,267,750 rows, built by
  `spark_jobs/bench_prepare.py`. Our real lake is ~10 MB, too small to time - Spark's fixed start-up cost
  would hide everything. The copy keeps the real values and their distribution, and is never used for analysis.
- **Cluster:** Spark standalone, 2 workers x 2 cores x 1.5 GB. For E6, YARN with 2 NodeManagers x 2 cores x 1.5 GB.
- **Timing:** each setting runs once untimed (warm-up), then 3 timed runs; we report the **median**.
  Spark runs end in the `noop` sink, which executes the whole plan but writes nothing.
- **Quiet machine:** Kafka, Kafka UI, Neo4j and Postgres are paused during the runs.
- **Repeated:** E0-E5 were run twice; both runs agree (table shows run 2, run 1 in the CSV).

## Results

| # | Experiment | Setting | Median | Speed-up |
|---|---|---|---|---|
| E0 | File format | CSV, 92 MB | 1.72 s | |
| | | Parquet, 4.5 MB | 0.59 s | **2.9x** |
| E1 | Shuffle partitions | 1 | 2.94 s | |
| | | 4 | 1.93 s | |
| | | 8 | 1.50 s | **2.0x** vs 1 |
| | | 16 / 64 / 200 | 1.67 / 1.45 / 1.82 s | no further gain |
| E2 | Join 3.3M rows with 2,400 totals | sort-merge (both sides shuffled) | 1.54 s | |
| | | broadcast (small table copied to every worker) | 0.89 s | **1.7x** |
| E3 | Read 1 year of 5 | flat files | 0.35 s | |
| | | `year=` folders (partition pruning) | 0.26 s | 1.3x |
| E4 | 3 queries on the same filtered data | no cache | 0.93 s | |
| | | cache filled inside the timed run | 2.13 s | 0.4x (slower) |
| | | cache already filled | 0.49 s | **1.9x** |
| E5 | Dependency workload | 1 worker (2 cores) | 2.54 s | |
| | | 2 workers (4 cores) | 2.40 s | 1.06x |
| E6 | Total value per reporter x product, 92 MB CSV | Hadoop MapReduce (C++ streaming, YARN) | 34.7 s | |
| | | Spark | 17.4 s | **2.0x** |

## What each result means

**E0 Parquet vs CSV.** Parquet is columnar and compressed: the query needs 3 of 7 columns, so only those
are read, and the file is 20x smaller. CSV has to be read and parsed in full, every time.

**E1 Shuffle partitions.** A `groupBy` or window moves rows between workers (a shuffle) into N pieces.
With 1 piece, one core does all the work while the other three wait. 8 pieces keep all 4 cores busy.
Beyond that the differences (±0.2 s) are within run-to-run noise. Spark's default of 200 hurts less than
expected because Spark 3's Adaptive Query Execution merges tiny pieces on its own while the job runs.

**E2 Broadcast join.** A normal join shuffles both tables so matching keys meet. When one side is tiny
(2,400 rows) Spark can send a full copy of it to every worker and skip shuffling the 3.3M-row side.
Our gold job does exactly this (`F.broadcast(world)` in `gold_dependencies.py`).

**E3 Partition pruning.** Smaller gain than expected, for a good reason: the flat files are sorted by
year, and Parquet stores min/max values per chunk, so Spark already skips most non-2023 chunks without
folders (predicate pushdown). The folders let it skip whole files without even opening them. The data is
also tiny when compressed (4.5 MB), so there is little to save. On unsorted or larger data the gap grows.

**E4 Caching is a trade-off.** Filling the cache costs more than re-reading 4.5 MB of Parquet, so caching
for just 3 quick queries made it *slower*. Once filled, the queries run 1.9x faster. Cache when the data
is reused many times or is expensive to recompute - not by reflex.

**E5 More workers.** Only 6% faster with twice the cores. At 3 million rows, fixed costs (scheduling tasks,
the shuffle between workers, start-up of each stage) are a large part of the time and don't shrink with
more cores (Amdahl's law). Both "workers" also share one laptop. More workers pay off on bigger data.

**E6 MapReduce vs Spark.** Same job, same data, same hardware budget (2 nodes x 2 cores x 1.5 GB), and
the outputs were checked to be identical (240 keys). Spark is 2x faster. Notes for a fair reading:
- The mapper and reducer are compiled C++ with a combiner, which cut 3.3M records to 1,920 before the
  shuffle - a strong MapReduce setup, not a straw man.
- Both times are the whole command, start-up included. MapReduce's very first (cold) run took 116 s while
  YARN shipped the programs to the nodes and started its Java processes; that run is the warm-up and not
  in the median.
- This is a single-pass job, MapReduce's best case. In a multi-step pipeline like our gold job,
  MapReduce would write every intermediate result to HDFS and read it back; Spark keeps it in memory.

## Limits of these experiments

- One laptop: all "machines" share the same CPU, memory and disk.
- The x10 copy repeats real values, so Parquet compresses it unusually well (3.3M rows in 4.5 MB).
- Each setting has 3 timed runs - enough to separate 2x effects from noise, not 5% effects.

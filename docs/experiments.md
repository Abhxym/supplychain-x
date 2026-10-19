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

---

# Phase 6 experiments: ML and validating the impact score

```bash
python -m ml.anomalies   # Isolation Forest on trade drops + port weather -> Postgres, results/anomalies_trade.csv
python -m ml.severity    # side classifier -> results/severity_classifier.{txt,csv}
python -m ml.validate    # the key experiment -> results/validation_{cases,summary,bootstrap}.csv
```

The data is a few MB, so these run with pandas + scikit-learn on the laptop, reading the bronze files with
the same filters as the silver jobs. Spark would add start-up cost and nothing else here.

## E7 Anomaly detection (Isolation Forest)

**Idea:** a forest of random trees cuts the data at random points. A normal point sits in a crowd and needs
many cuts to be alone; an odd point is isolated in a few. No labels needed.

**Trade:** 35,580 flows (importer x supplier x product x year, 2020-23, flows >= $10M the year before),
described by the change in log value, the change in the supplier's share and the size of the flow.
The forest's strangest 2% gave 449 unusual *drops*. The top of the list is not weather but politics:

| Drop | What happened |
|---|---|
| Germany, Italy, Netherlands: fuels from Russia, 2023 (-95%, -93%, -76%) | EU sanctions / embargo |
| Indonesia: cereals from Ukraine, 2022 (-92%) | the war closed Black Sea exports |
| Indonesia: cereals from India, 2023 (-92%) | India's 2022-23 export restrictions |
| Indonesia: pharmaceuticals from China, 2022 (-90%) | end of the COVID vaccine wave |
| Germany: organic chemicals from China, 2023 (-76%) | |

Lesson: the biggest breaks in yearly trade come from wars, sanctions and policy. Natural disasters
rarely show up in **annual** totals - a 2-week port closure is averaged away over 12 months.

**Port weather:** 82,170 port-days, each port scaled to its own normal. The forest flagged 411 days; our
fixed thresholds (>= 115.6 mm rain or >= 89 km/h gusts) flag 472; 182 days are flagged by both. The forest
also finds days that are extreme *for that port* (a big storm in a calm port) that fixed thresholds miss,
and ignores days that are normal for a stormy port. The engine keeps the thresholds because they are
explainable; the forest is a second opinion.

## E8 Severity classifier (side component)

**Question:** can we guess GDACS's Green / Orange / Red from *context* - weather at the hit country's ports,
past events there, its exports, its ports, event type and duration - without the physical size of the event?
(GDACS computes the alert from magnitude / wind speed, so giving the model those would be copying the answer.)

Train 2019-22 (34,696 events), test 2023 (14,106: 14,020 Green, 57 Orange, 29 Red).

| Model | Macro F1 | F1 low | F1 medium | F1 high | Red caught | Green wrongly raised |
|---|---|---|---|---|---|---|
| Always "low" (baseline) | 0.332 | 0.997 | 0.000 | 0.000 | 0 / 29 | 0 |
| Logistic regression (balanced) | 0.402 | 0.947 | 0.033 | 0.226 | 14 / 29 | 1,388 |
| Random forest (balanced) | **0.449** | 0.994 | 0.145 | 0.208 | 5 / 29 | 100 |

- **The accuracy trap:** the useless baseline is 99.4% "accurate", because 99.4% of events are Green.
  That is why we report per-class F1 and the confusion matrices (`results/severity_classifier.txt`).
- What the forest uses most (permutation importance): event type, duration, and past serious events in the
  country. Port weather, exports and port count add almost nothing - they say *where* an event is, not how
  strong. Context alone cannot replace the physical measurement; this stays a side component, not part of
  the impact score.

## E9 Does the impact score rank the really-hit countries first? (the key experiment)

**Method.** For known disruptions, the engine ranks the countries in the cascade. We compare three
versions of the same score, plus a random order as the floor:

| Variant | Score |
|---|---|
| A severity only | S x decay^hop |
| B + trade | (S, D dependency, E exposure, T duration) x decay^hop |
| C + centrality | (S, D, E, C, T) x decay^hop - the default engine |
| random | the same countries in random order |

Within one event S and T are the same for every country, so they change *how big* the scores are, not the
order. In A every country at the same hop ties; we report the **expected** result over all orders of tied
countries (computed exactly), so ties never help or hurt a variant.

Metrics for K = 1, 3, 5: **Precision@K** (share of the top K that were really hit), **Recall@K** (share of
the really-hit countries found in the top K), **Hit@K** (at least one in the top K).

**Ground truth 1 - news (`ml/ground_truth.json`, with URLs).** Countries that published reports tie to the
event. Only our 20 reporting economies can be labels, because only they have incoming links in the graph.

| Case | Hit country (confidence) | Evidence |
|---|---|---|
| Japan earthquake 2011 (what-if on JPN) | USA, FRA, DEU (strong) | GM Shreveport, PSA France, Opel Eisenach halted for Japanese parts |
| Thailand floods 2011 (what-if on THA) | JPN (strong), USA (medium) | IHS: Japan worst hit after Thailand; Toyota US slowdown, HDD shortage |
| Texas freeze 2021 (what-if on USA) | MEX (medium), CAN (weak) | Toyota Mexico hit by petrochemical shortage; Honda Canada, cause mixed |
| Turkiye earthquake 2023 (GDACS Red) | DEU, FRA, ITA, NLD (weak) | Turkish textile exports to the EU fell 26%; EU named, not member states |
| Negative control: Typhoon Hagibis 2019 | none reported | Subaru: US plant not affected, no North American shortage |

Searched but **excluded**, with the reason recorded in the JSON: Hurricanes Ida and Ian (big US Gulf
shutdowns, but no report naming a foreign country hit), Henan floods 2021 (Foxconn reported no direct
impact), Malaysia floods 2021 (no downstream country named), Typhoon Hinnamnor 2022 (it hit Korea's POSCO,
but GDACS lists only Japan), Taiwan drought 2021 (TSMC said output was not affected).

**Ground truth 2 - our own trade data.** For each Red event 2019-22, the importers whose imports from the
hit country had an unusual drop (E7) that year or the next: 44 events. Noisy on purpose - yearly data cannot
say which event caused a drop, and many drops are political (E7). A sanity check, not proof.

**Results** (`results/validation_summary.csv`, per case in `validation_cases.csv`):

| | P@1 | P@3 | P@5 | R@3 | R@5 | Hit@3 |
|---|---|---|---|---|---|---|
| **GT1 news, 4 cases** - A severity only | 0.19 | 0.19 | 0.20 | 0.21 | 0.35 | 0.55 |
| B + trade | 0.25 | 0.25 | 0.30 | 0.31 | 0.56 | 0.50 |
| C + centrality | **0.50** | **0.33** | **0.30** | **0.44** | **0.58** | **0.75** |
| random | 0.15 | 0.15 | 0.15 | 0.16 | 0.26 | 0.39 |
| **GT2 trade drops, 44 events** - A severity only | 0.21 | 0.20 | 0.20 | 0.12 | 0.21 | 0.42 |
| B + trade | **0.30** | **0.27** | 0.28 | **0.18** | 0.33 | **0.52** |
| C + centrality | 0.14 | 0.21 | **0.31** | 0.12 | **0.34** | 0.43 |
| random | 0.20 | 0.20 | 0.20 | 0.13 | 0.21 | 0.41 |

**How sure are we?** 95% intervals for the differences by a *cluster* bootstrap: events that hit the same
countries share most of their answer (9 of the 44 GT2 events are China events), so we resample the 28
source-country groups, not single events (`validation_bootstrap.csv`):

| Difference (GT2, P@3) | Mean | 95% interval |
|---|---|---|
| B minus random | +0.075 | -0.006 to +0.172 |
| B minus A | +0.072 | -0.004 to +0.161 |
| C minus B | -0.061 | -0.128 to +0.009 |
| A minus random | +0.003 | -0.012 to +0.018 |

A first, naive bootstrap over single events gave intervals that excluded zero. Counting the 9 China events
as 9 independent proofs was the mistake; with the cluster bootstrap **every interval includes zero.**
No variant is proven better.

**What the results suggest (directions, not proof):**

1. **Severity alone does not rank countries** - A is no better than random (+0.003). Expected: severity is
   the same for everyone in one event. Severity is for comparing *events*, not for choosing *who* is hit.
2. **Trade dependency helps** in both ground truths (B above A and random). It is the part of the score
   that actually separates countries.
3. **Centrality helps on the news cases and hurts on the trade-drop cases.** In the top-5 lists, C puts
   **China first** for Japan 2011, Thailand 2011 and Hagibis, though China was not reported as hit; on GT2 it
   puts India first in 11 of 44 events. Centrality says how much of a *hub* a country is in general, not how
   much it depends on the country that was hit, so it pulls the same hubs up in every cascade ("hub bias").
   A better place for centrality may be the *source* side (how important the hit country is).
4. **Japan 2011: no variant has a really-hit country in its top 3** (A and B: THA, KOR, ARE; C: CHN, THA,
   KOR, then USA at 4). The real damage came from a few
   critical components - Renesas microcontrollers, Hitachi airflow sensors - small in dollars and hard to
   replace. HS2 trade totals (all of chapter 85 together) cannot see them. This is the biggest known limit
   of a trade-weighted score.
5. **Negative control:** for Hagibis the engine still produces a 19-country cascade (top score 0.34, China
   first), while reports say there was no overseas shortage. The engine knows nothing about inventory,
   other suppliers or how fast a plant restarts, so it measures **exposure**, not **confirmed impact**.

The default weights (C) are left unchanged: the evidence is too thin to justify re-tuning, and tuning on
these same 4 cases would only fit the test.

## Limits of the Phase 6 experiments

- **4 news cases** (3 with strong/medium labels), two of them before our 2019-23 data and run on the 2023
  graph. One case moves an average by 25%: GT1 numbers are examples, not statistics.
- **Ground truth is incomplete:** a country not named in a report was not necessarily unaffected, so
  precision is a lower bound. Labels rest on one or two news/industry reports per country.
- **The graph is saturated:** every case reaches all 19 other reporters, so the test is only about *order*.
- **GT2 shares a source with the score:** both use Comtrade; big shares (D) and big drops can go together,
  which could flatter B and C. That is why it is only a sanity check.
- Annual trade data hides short disruptions; monthly Comtrade data would be the natural next step.

# Finding and Fixing Pipeline Inefficiency with Cortex Code

A self-contained, synthetic Snowflake demo. It builds a deliberately inefficient
ingestion pipeline, lets it generate real telemetry, then uses **Cortex Code** to
investigate, diagnose and fix it — and measures the fix.

> Run this only in a sandbox or demo account. All data is synthetic.

---

## What

The demo creates an isolated database (`PIPELINE_COST_DEMO`) and a small set of
`DEMO_*` warehouses running scheduled tasks that reproduce four inefficiency
patterns common in production ingestion workloads:

| Pattern | How the demo reproduces it |
|---|---|
| **Incremental MERGE that reads the whole table** | A 5,000-row batch is merged into a 20M-row (~6 GB) ledger, but the MERGE source runs a window function over the full ledger every run. |
| **Join key with no clustering** | The MERGE key is MD5-derived, so it is scattered across every micro-partition and pruning is close to zero. |
| **Resizing instead of fixing** | The same workload runs on X-Small and Small warehouses side by side. The larger warehouse is faster but scans exactly the same bytes, at twice the hourly rate. |
| **Clock-driven jobs and silent failures** | Tasks run on fixed 1–5 minute schedules whether or not new data has arrived. A reporting job full-scans the ledger every 5 minutes, and an enrichment task fails about 35% of the time with no auto-retry. |

## Why

When pipeline costs rise, the usual first move is to increase the warehouse size.
That often makes jobs faster but more expensive, and leaves the real cause in
place: scan volume. The telltale sign is warehouses that are mostly idle yet
still spill on every run of the dominant job.

The demo makes that visible and measurable, and shows how Cortex Code can:

1. Attribute credits to the warehouses and recurring workloads driving them.
2. Separate sizing effects from workload effects (volume, scanning, idle time, failures).
3. Pull the actual query profile (pruning, bytes scanned, spill per operator).
4. Propose a fix that reduces scan volume, then prove it with before-and-after numbers.

The takeaway: **reduce what each query reads, run jobs when data changes, and
size warehouses to the fixed workload.** Don't keep paying for a larger warehouse
to hide the problem.

## How

### Files

| File | Purpose |
|---|---|
| `pipeline_cost_optimization_demo.ipynb` | The full guided walkthrough (Snowflake Notebook). **Start here.** |
| `pipeline_cost_optimization_setup.sql` | Plain-SQL version of the build, if you prefer a worksheet. |
| `pipeline_cost_optimization_cleanup.sql` | Emergency stop, verification and full teardown. |

### Prerequisites

- A sandbox Snowflake account and the `ACCOUNTADMIN` role. The demo creates a
  resource monitor and warehouses.
- Cortex Code (CLI or in Snowsight).

### Cost and safety

- **Build and seed:** about 2 credits (about 4 minutes on a temporary Large warehouse).
- **Running pipeline:** about 3.5 credits per hour.
- **Cost guard:** the `DEMO_COST_GUARD` resource monitor caps demo warehouses at
  40 credits per day and suspends them at 100%.
- Tasks are created **suspended**. Nothing runs continuously until you resume them.

### Walkthrough

1. **Build** (notebook Part 1, or `setup.sql`). Creates the cost guard, warehouses,
   database, the 20M-row ledger, the feed generator, the inefficient procedures and
   the tasks. It also runs each task once so telemetry is available right away.
2. **Start the pipeline** (Part 2). Resume the tasks and let them run:

   | Running time | What you can demonstrate |
   |---|---|
   | Seed only | Query-level diagnosis (Prompt 2) |
   | 15 min | Task failure analysis (Prompt 3) |
   | 45–60 min | Account-level cost analysis (Prompt 1) |

3. **Confirm the problem** (Part 3). Check clustering depth, bytes scanned and runtime
   per warehouse tier, per-operator pruning and spill, credits by warehouse, and
   task outcomes. This gives you ground truth to check Cortex Code's answers against.
4. **Hand it to Cortex Code** (Part 4). First set your context so the analysis stays
   on the demo:

   ```sql
   USE DATABASE PIPELINE_COST_DEMO;
   USE SCHEMA INGESTION;
   ```

   Then run the three prompts. The full text is in the notebook:
   - **Prompt 1: Find the problem.** Read-only analysis of 24 hours of
     consumption, attributing cost to volume, sizing, scanning, idle time or failures.
   - **Prompt 2: Diagnose and quantify the fix.** Profile the dominant MERGE with
     `GET_QUERY_OPERATOR_STATS` (pruning, scan, spill) and estimate the savings.
   - **Prompt 3: Turn it into a deliverable.** Correlate task failures with the
     pipeline run log and query history, and recommend recovery settings.

5. **Prove the fix** (Part 5). Run a corrected, bounded MERGE, then re-run the Part 3
   checks to compare before and after.
6. **Stop and clean up** (Part 6, or `cleanup.sql`).
   - **Stop** as soon as the session ends. This suspends tasks and aborts running queries.
   - **Teardown** removes all demo objects: tasks, warehouses, resource monitor and database.
   - If Cortex Code created anything outside `PIPELINE_COST_DEMO`, check with
     `SHOW WAREHOUSES; SHOW RESOURCE MONITORS; SHOW TASKS IN ACCOUNT;`.

### Tips

- Don't reduce the ledger much below 20M rows. At smaller sizes the sort fits in
  memory, the spill disappears, and one of the findings goes with it.
- `ACCOUNT_USAGE` views lag (query history by up to 45 minutes, metering by up to
  3 hours). The notebook uses `INFORMATION_SCHEMA` table functions and
  `GET_QUERY_OPERATOR_STATS` for real-time evidence.
- To reset between sessions, re-run notebook cell 1.7 to restore the inefficient
  procedure, then Part 2. A full rebuild takes about 10 minutes and 2 credits.

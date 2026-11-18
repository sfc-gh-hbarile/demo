import json, uuid

cells = []
def _id(): return uuid.uuid4().hex[:8]
def md(s): cells.append({"cell_type": "markdown", "id": _id(), "metadata": {}, "source": s.strip("\n").splitlines(True)})
def sql(name, s):
    cells.append({"cell_type": "code", "id": _id(), "execution_count": None, "outputs": [],
                  "metadata": {"language": "sql", "name": name, "resultVariableName": name, "codeCollapsed": False},
                  "source": (f"%%sql -r {name}\n" + s.strip("\n")).splitlines(True)})
def py(s):
    cells.append({"cell_type": "code", "id": _id(), "execution_count": None, "outputs": [], "metadata": {},
                  "source": s.strip("\n").splitlines(True)})

# =====================================================================  TITLE
md("""
# Zero to Snowflake — BP Edition

The standard Snowflake **Zero to Snowflake** vignettes, taught with **your** data story: Fluxx grants, Salesforce donors, an on-prem SQL Server with 10 years of stored procedures, and 500+ Tableau reports.

| Vignette | Snowflake fundamentals | Your ask it answers | ⏱ |
|---|---|---|---|
| **0** | Snowsight tour, Snowflake 101 | "We're all new to Snowflake" | 2 |
| **1. Getting Started** | Files & COPY INTO, warehouses, **scale up for loads and queries**, caching, **cloning**, **Time Travel** | Can we load our exports? How fast, and what does compute cost? Can we recover from mistakes? | 12 |
| **2. Simple Data Pipelines** | Semi-structured JSON, Snowpipe, **Dynamic Tables** | Replace stored procs; meet the 10-min publishing SLA | 6 |
| **3. Cortex AI** | AI functions, AI at scale, AI-assisted dev, conversational BI | Replace 500+ static Tableau reports for 8,000 users | 8 |
| **4. Governance with Horizon** | Roles, **classification**, **masking**, **row access** | Program officers see only their portfolio; donor/grantee PII protected | 5 |
| **5. Apps & Collaboration** | **Marketplace** enrichment, sharing | Add global context (road deaths, air quality) to grants | 2 |
| **Wrap** | **Cost Management in Snowsight** | What does all this cost, and how do we control it? | 2 |
| | **Total ≈ 37 min of demo, leaving ~8 min for questions** (Vignette 5 is the one to drop if time is short) | | |
| Appendix | Fluxx API pull, Snowpipe vs COPY INTO, error handling, guardrails | Production automation | ref |

### How to use this notebook
1. Run cells **top to bottom** with **Shift + Enter** (or the ▶ on each cell). Grey **SQL** cells run SQL; **Python** cells run Python.
2. **👉 Do** notes point to where to click in Snowsight.
3. Uses database `BP_DEMO` and warehouse `BP_DEMO_WH` (built by `bp_demo/01–07*.sql`). Run as **ACCOUNTADMIN**.
4. After today, attendees get the **Tasty Bytes Zero to Snowflake** lab to repeat every vignette hands-on.

> Organization, donor and contact names are fictional. Program areas and initiatives reflect BP's focus areas.
""")

# =====================================================================  0
md("""
## 0. Snowflake 101 and the Snowsight interface

| Idea | What it means | SQL Server equivalent |
|---|---|---|
| **Storage ≠ compute** | Data sits in compressed cloud storage; compute is paid for only while it runs | CPU + disk on one box, paid 24×7 |
| **Virtual warehouse** | Compute you start, stop and resize in seconds; many can read the same data at once | The SQL Server instance |
| **Fully managed SaaS** | No patching, indexes, vacuuming or backups; Time Travel and failover built in | DBA + infrastructure team |

**Hierarchy:** Account → Database → Schema → Table / View / Stage / Pipe / Task / Dynamic Table …

### 👉 Do: the 60-second tour (left navigation)
| Menu | Show |
|---|---|
| **Projects → Workspaces** | Where this notebook and SQL files live (Git-connectable) |
| **Catalog → Database Explorer** | `BP_DEMO` → `RAW` / `CURATED` / `AI` / `GOV`. Click a table → *Columns*, *Data Preview*, *Lineage* |
| **Monitoring → Query History** | Every query, its warehouse, duration and *Query Profile* |
| **Monitoring → Dynamic Tables / Task History / Copy History** | Pipeline health, built in |
| **Admin → Warehouses** | Create, resize and suspend compute |
| **Admin → Cost Management** | Credits by warehouse and service; budgets (we finish here) |
| **Catalog → Data Products → Marketplace** | Third-party data (Vignette 5) |
| **AI & ML → Snowflake Intelligence** | The chat experience (Vignette 3) |
| **Bottom-left: your name → Switch Role** | Roles control what you see (Vignette 4) |
""")

sql("whoami", """
SELECT CURRENT_USER() AS user_name, CURRENT_ROLE() AS role_name, CURRENT_WAREHOUSE() AS warehouse, CURRENT_REGION() AS region
""")

# =====================================================================  V1 (v2 ordering)
md("""
---
# Vignette 1 — Getting Started: loading files, warehouses, scaling up, caching, cloning, Time Travel

## 1.1 Loading files: stage → LIST → COPY INTO
Your team will get regular exports: Fluxx 2DB dumps, finance spreadsheets, partner files. This is the 101 pattern.

- A **stage** is a folder for files (internal = managed by Snowflake; external = your Azure Blob container).
- `LIST` shows the files, and you can **query a file before loading it**.
- `COPY INTO` loads them. Snowflake **remembers which files it already loaded**, so re-running doesn't create duplicates.
- Loading needs **compute**: `COPY INTO` runs on a *virtual warehouse*. Section 1.2 explains how those are sized and billed.

Today: a **grantee contact directory**, exported as one CSV per region.
""")

py(r"""
# Diagram: Vignette 1 batch load (CSV files -> stage -> COPY INTO on a warehouse -> table), static picture
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle

fig, ax = plt.subplots(figsize=(11, 5.6))
ax.set_xlim(0, 11); ax.set_ylim(0, 5.8); ax.axis("off")

C_SRC, C_STG, C_WH, C_TBL = "#F2F3F4", "#E8EEF4", "#D6EAF8", "#E8F6F3"

def box(x, y, w, h, title, sub, color, edge="#34495E", bold=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.04,rounding_size=0.12",
                                fc=color, ec=edge, lw=2.2 if bold else 1.1))
    ax.text(x + w / 2, y + h - 0.2, title, ha="center", va="top", fontsize=10, weight="bold")
    ax.text(x + w / 2, y + h - 0.58, sub, ha="center", va="top", fontsize=8.5, color="#2C3E50", linespacing=1.35)

def arrow(x1, y1, x2, y2, label=None):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=14, lw=1.5, color="#566573"))
    if label:
        ax.text((x1 + x2) / 2, y1 + 0.18, label, ha="center", fontsize=8, color="#566573", family="monospace")

# compute band: COPY INTO runs on a virtual warehouse
ax.add_patch(Rectangle((5.0, 0.7), 2.9, 4.4, fc="#EBF5FB", ec="#2E86C1", lw=1.2, ls="--", zorder=0))
ax.text(6.45, 4.85, "COMPUTE: virtual warehouse", ha="center", fontsize=9.5, weight="bold", color="#2E86C1")

box(0.1, 2.0, 2.2, 2.2, "Regional CSV exports", "grantee contacts\none file per region\n(3 files)", C_SRC)
box(2.75, 2.0, 2.0, 2.2, "@SAMPLE_FILES", "internal stage\nLIST  /  query files\nINFER_SCHEMA", C_STG)
box(5.25, 2.0, 2.4, 2.2, "COPY INTO", "runs on BP_DEMO_WH\n(XS, per-second billing)\nskips files already loaded", C_WH, edge="#2E86C1", bold=True)
box(8.1, 2.0, 2.8, 2.2, "GOV.GRANTEE_DIRECTORY", "regular table\ncolumns from inferred schema\nready to query", C_TBL, edge="#17A589")

arrow(2.35, 3.1, 2.7, 3.1)
arrow(4.8, 3.1, 5.2, 3.1)
arrow(7.7, 3.1, 8.05, 3.1)

ax.text(6.45, 1.0, "Same warehouse, resized XS → MEDIUM in 1.3\nfor the 229-file / 4 GB load", ha="center", fontsize=8.3, color="#2E86C1", style="italic")
ax.text(5.5, 0.2, "Batch load: files on a stage → COPY INTO (warehouse compute) → table.  Serverless Snowpipe comes in Vignette 2.",
        ha="center", fontsize=9, color="#2C3E50")
ax.set_title("Loading files: stage → COPY INTO on a warehouse → table", fontsize=13.5, weight="bold", loc="left")
plt.tight_layout()
plt.show()
""")


sql("list_files", """
LIST @BP_DEMO.RAW.SAMPLE_FILES
""")

sql("dir_table", """
-- The stage's DIRECTORY TABLE: the same file list, queryable like a table
SELECT relative_path, size, last_modified FROM DIRECTORY(@BP_DEMO.RAW.SAMPLE_FILES)
""")

sql("peek_csv", """
-- Peek inside a file before loading (no table needed)
SELECT $1 AS grantee_id, $2 AS organization_name, $3 AS program_area, $4 AS country, METADATA$FILENAME AS file
FROM @BP_DEMO.RAW.SAMPLE_FILES/grantee_directory_emea.csv (FILE_FORMAT => 'BP_DEMO.RAW.FF_CSV_PEEK')
LIMIT 5
""")

sql("infer_schema", """
-- Let Snowflake work out the columns and types from the files themselves
SELECT column_name, type, nullable, filenames
FROM TABLE(INFER_SCHEMA(LOCATION => '@BP_DEMO.RAW.SAMPLE_FILES', FILE_FORMAT => 'BP_DEMO.RAW.FF_CSV'))
""")

sql("create_and_copy", """
-- Create the table from the inferred schema, then MANUAL COPY INTO
CREATE OR REPLACE TABLE BP_DEMO.GOV.GRANTEE_DIRECTORY USING TEMPLATE (
  SELECT ARRAY_AGG(OBJECT_CONSTRUCT(*)) WITHIN GROUP (ORDER BY order_id)
  FROM TABLE(INFER_SCHEMA(LOCATION => '@BP_DEMO.RAW.SAMPLE_FILES', FILE_FORMAT => 'BP_DEMO.RAW.FF_CSV')));

COPY INTO BP_DEMO.GOV.GRANTEE_DIRECTORY
  FROM @BP_DEMO.RAW.SAMPLE_FILES
  FILE_FORMAT = (FORMAT_NAME = 'BP_DEMO.RAW.FF_CSV')
  MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE
  ON_ERROR = 'ABORT_STATEMENT';
""")

sql("copy_again", """
-- Run it again: 0 files loaded, because Snowflake skips files it already loaded (no duplicates)
COPY INTO BP_DEMO.GOV.GRANTEE_DIRECTORY
  FROM @BP_DEMO.RAW.SAMPLE_FILES
  FILE_FORMAT = (FORMAT_NAME = 'BP_DEMO.RAW.FF_CSV')
  MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE
""")

sql("grantees", """
SELECT region, COUNT(*) AS grantees, ROUND(SUM(annual_budget_usd)/1e6, 1) AS combined_budget_musd
FROM BP_DEMO.GOV.GRANTEE_DIRECTORY GROUP BY 1 ORDER BY 2 DESC
""")

md("""
Three small files loaded in a second or two on the smallest compute there is. What happens when the export is 200+ files and 4 GB? That is where warehouse size comes in.

## 1.2 Warehouses: how compute and cost work
- Compute is billed in **credits per second** while a warehouse runs (60s minimum per start). `AUTO_SUSPEND = 60` stops it when idle, and `AUTO_RESUME` restarts it on the next query.
- **Storage** is billed separately per compressed TB per month. **Serverless** features (Snowpipe, AI, Search) bill their own credits.
- Credit price depends on edition, region and contract.

| Size | XS | S | M | L | XL | 2XL |
|---|---|---|---|---|---|---|
| Credits / hour | 1 | 2 | 4 | 8 | 16 | 32 |

Each size **doubles compute and rate**. For parallel work it roughly halves runtime, so **similar cost, much faster**.

| | **Scale UP** (size) | **Scale OUT** (multi-cluster) |
|---|---|---|
| Fixes | One big or slow job | Many concurrent users (8,000 report users at 9am) |
| How | `SET WAREHOUSE_SIZE = 'MEDIUM'` | `MIN_CLUSTER_COUNT = 1, MAX_CLUSTER_COUNT = 4` (Enterprise+) |
| Back down | Resize any time | Clusters retire automatically |

**Metered vs attributed credits**
- **Metered (what you're billed):** every second the warehouse is *running*, at its size's rate, with a **60-second minimum each time it resumes**, plus idle time until `AUTO_SUSPEND` stops it. It doesn't matter how many queries ran.
- **Attributed (who used it):** each job's share = its run time × the rate. Label jobs with `QUERY_TAG` and you can roll cost up by job, team or warehouse config.
- Metered ≥ attributed. The gap is idle time, resume minimums and any other work sharing the warehouse.

**101 rules:** one warehouse per workload (`LOAD_WH`, `TRANSFORM_WH`, `BI_WH`); start XS/S; keep AUTO_SUSPEND at 60s.
""")

sql("wh_show", """
SHOW WAREHOUSES LIKE 'BP_DEMO_WH'
""")

md("""
## 1.3 Scaling up for a load job
Same files, same table definition, two warehouse sizes. A load runs **one file per thread**, so a bigger warehouse only helps when there are **many files**.

### 👉 Do: look at the files, then load them on XS and on MEDIUM
(~230 compressed CSVs unloaded from the shared `TPCDS_10TB.CUSTOMER` table by `08_scale_data.sql`. Unloading data from Snowflake to a stage is just `COPY INTO @stage FROM table`.)
""")

py("""
# One label per demo run, so rehearsals never mix with the live numbers (also in ACCOUNT_USAGE later)
from datetime import datetime
run_id = datetime.now().strftime("%m%d_%H%M")
print(f"Query tags for this run: bp_demo:{run_id}:<job>:<size>")
""")

sql("bulk_files", """
SELECT COUNT(*) AS files, ROUND(SUM(size)/1e9, 2) AS gb, ROUND(AVG(size)/1e6, 1) AS avg_file_mb
FROM DIRECTORY(@BP_DEMO.RAW.BULK_FILES)
""")

sql("load_xs", """
ALTER SESSION SET QUERY_TAG = 'bp_demo:{{run_id}}:load:xs';          -- label this job so its cost can be attributed
ALTER WAREHOUSE BP_DEMO_WH SET WAREHOUSE_SIZE = 'XSMALL';
USE WAREHOUSE BP_DEMO_WH;
CREATE OR REPLACE TABLE BP_DEMO.RAW.LOAD_TEST_XS LIKE TPCDS_10TB.TPCDS_SF10TCL.CUSTOMER;
COPY INTO BP_DEMO.RAW.LOAD_TEST_XS
  FROM @BP_DEMO.RAW.BULK_FILES/customer/
  FILE_FORMAT = (FORMAT_NAME = 'BP_DEMO.RAW.FF_CSV_BULK') MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE
->> SELECT COUNT(*) AS files_loaded, SUM("rows_loaded") AS rows_loaded FROM $1
""")

sql("load_m", """
ALTER SESSION SET QUERY_TAG = 'bp_demo:{{run_id}}:load:medium';
ALTER WAREHOUSE BP_DEMO_WH SET WAREHOUSE_SIZE = 'MEDIUM';   -- scale UP: seconds, no downtime
CREATE OR REPLACE TABLE BP_DEMO.RAW.LOAD_TEST_M LIKE TPCDS_10TB.TPCDS_SF10TCL.CUSTOMER;
COPY INTO BP_DEMO.RAW.LOAD_TEST_M
  FROM @BP_DEMO.RAW.BULK_FILES/customer/
  FILE_FORMAT = (FORMAT_NAME = 'BP_DEMO.RAW.FF_CSV_BULK') MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE
->> SELECT COUNT(*) AS files_loaded, SUM("rows_loaded") AS rows_loaded FROM $1
""")

sql("load_compare", """
ALTER WAREHOUSE BP_DEMO_WH SET WAREHOUSE_SIZE = 'XSMALL';  -- scale DOWN straight away
ALTER SESSION UNSET QUERY_TAG;
-- Every query carries its tag, so cost and time roll up by job, team or warehouse config
SELECT query_tag, warehouse_size, ROUND(total_elapsed_time / 1000, 1) AS seconds,
       DECODE(warehouse_size, 'X-Small', 1, 'Small', 2, 'Medium', 4, 'Large', 8) AS credits_per_hour,
       ROUND(seconds * credits_per_hour / 3600, 4) AS est_credits
FROM TABLE(BP_DEMO.INFORMATION_SCHEMA.QUERY_HISTORY(RESULT_LIMIT => 500))
WHERE query_tag LIKE 'bp_demo:{{run_id}}:load:%' AND query_type = 'COPY' AND execution_status = 'SUCCESS'
ORDER BY start_time DESC LIMIT 2
""")

md("""
4× the compute, about 3–4× faster, roughly the same credits, and we resized back down the moment it finished. The catch: with only 3 files, MEDIUM would have been wasted money. **Size for the number of files, not the number of rows.** For continuous small files, Snowpipe (Vignette 2) is serverless and needs no warehouse at all.

## 1.4 Scaling up for a query job
Loading is one workload; analytics is the other. Here the data is Snowflake's shared **TPC-DS 10 TB** sample: `STORE_SALES` has **28.8 billion rows**, and we scan 4 months of it (~100 GB), joined to the item and date tables. It is already in the account, so there is nothing to copy.

### 👉 Do: run the same query on XS, then on MEDIUM
Result caching is switched off so each run is real compute. The query text is identical on both runs.
""")

sql("tpcds_size", """
SELECT table_name, row_count, ROUND(bytes/1e9, 0) AS gb
FROM TPCDS_10TB.INFORMATION_SCHEMA.TABLES
WHERE table_schema = 'TPCDS_SF10TCL' AND table_name IN ('STORE_SALES', 'ITEM', 'DATE_DIM')
ORDER BY bytes DESC
""")

sql("query_xs", """
ALTER SESSION SET QUERY_TAG = 'bp_demo:{{run_id}}:query:xs';         -- label this job so its cost can be attributed
ALTER SESSION SET USE_CACHED_RESULT = FALSE;          -- measure real compute
ALTER WAREHOUSE BP_DEMO_WH SET WAREHOUSE_SIZE = 'XSMALL';
USE WAREHOUSE BP_DEMO_WH;
SELECT i.i_category, COUNT(*) AS line_items, ROUND(SUM(ss.ss_net_paid)/1e6, 1) AS net_paid_musd,
       COUNT(DISTINCT ss.ss_customer_sk) AS customers
FROM TPCDS_10TB.TPCDS_SF10TCL.STORE_SALES ss
JOIN TPCDS_10TB.TPCDS_SF10TCL.DATE_DIM d ON ss.ss_sold_date_sk = d.d_date_sk
JOIN TPCDS_10TB.TPCDS_SF10TCL.ITEM i ON ss.ss_item_sk = i.i_item_sk
WHERE d.d_year = 2001 AND d.d_moy BETWEEN 1 AND 4
GROUP BY 1 ORDER BY 3 DESC
""")

sql("query_m", """
ALTER SESSION SET QUERY_TAG = 'bp_demo:{{run_id}}:query:medium';
ALTER WAREHOUSE BP_DEMO_WH SET WAREHOUSE_SIZE = 'MEDIUM';   -- scale UP: seconds, no downtime
SELECT i.i_category, COUNT(*) AS line_items, ROUND(SUM(ss.ss_net_paid)/1e6, 1) AS net_paid_musd,
       COUNT(DISTINCT ss.ss_customer_sk) AS customers
FROM TPCDS_10TB.TPCDS_SF10TCL.STORE_SALES ss
JOIN TPCDS_10TB.TPCDS_SF10TCL.DATE_DIM d ON ss.ss_sold_date_sk = d.d_date_sk
JOIN TPCDS_10TB.TPCDS_SF10TCL.ITEM i ON ss.ss_item_sk = i.i_item_sk
WHERE d.d_year = 2001 AND d.d_moy BETWEEN 1 AND 4
GROUP BY 1 ORDER BY 3 DESC
""")

sql("query_compare", """
ALTER WAREHOUSE BP_DEMO_WH SET WAREHOUSE_SIZE = 'XSMALL';  -- scale DOWN straight away
ALTER SESSION SET USE_CACHED_RESULT = TRUE;
ALTER SESSION UNSET QUERY_TAG;
SELECT query_tag, warehouse_size, ROUND(total_elapsed_time / 1000, 1) AS seconds,
       DECODE(warehouse_size, 'X-Small', 1, 'Small', 2, 'Medium', 4, 'Large', 8) AS credits_per_hour,
       ROUND(seconds * credits_per_hour / 3600, 4) AS est_credits,
       ROUND(bytes_scanned / 1e9, 0) AS gb_scanned
FROM TABLE(BP_DEMO.INFORMATION_SCHEMA.QUERY_HISTORY(RESULT_LIMIT => 200))
WHERE query_tag LIKE 'bp_demo:{{run_id}}:query:%' AND query_type = 'SELECT' AND execution_status = 'SUCCESS'
ORDER BY start_time DESC LIMIT 2
""")

md("""
Same query, same answer, 4× the compute: about 4× faster for about the same credits, then back to XS. A big analytic scan is exactly the case where bigger is cheaper per answer. Try that with an on-prem server.

**Cost attribution:** `ALTER SESSION SET QUERY_TAG = '...'` labels every query in the session (also settable per user, per task, or from BI tools and dbt). Use a consistent scheme such as `team:job:size`. Billed credits per tag arrive later in `SNOWFLAKE.ACCOUNT_USAGE.QUERY_ATTRIBUTION_HISTORY` (`WHERE query_tag LIKE 'bp_demo:<run_id>:%'`, `GROUP BY query_tag`, `SUM(credits_attributed_compute)`), with a delay of a few hours. The run ID in the tag keeps rehearsals separate from the live run. Pair it with **object tags on warehouses** for chargeback.

## 1.5 Caching: the second run is free
Snowflake keeps every query result for **24 hours**. If the same query runs again and the data hasn't changed, it returns instantly **without using a warehouse**, even on a different warehouse size. That's ideal for dashboards that 8,000 people open at 9am.

### 👉 Do: re-run the exact same 4-month query on the **XS** warehouse
""")

sql("cache_run", """
ALTER SESSION SET QUERY_TAG = 'bp_demo:{{run_id}}:query:cached';
ALTER SESSION SET USE_CACHED_RESULT = TRUE;           -- turn the result cache back on (1.4 switched it off to measure compute)
-- Identical query text to the earlier runs -> served from the RESULT CACHE, on XS, with no compute
SELECT i.i_category, COUNT(*) AS line_items, ROUND(SUM(ss.ss_net_paid)/1e6, 1) AS net_paid_musd,
       COUNT(DISTINCT ss.ss_customer_sk) AS customers
FROM TPCDS_10TB.TPCDS_SF10TCL.STORE_SALES ss
JOIN TPCDS_10TB.TPCDS_SF10TCL.DATE_DIM d ON ss.ss_sold_date_sk = d.d_date_sk
JOIN TPCDS_10TB.TPCDS_SF10TCL.ITEM i ON ss.ss_item_sk = i.i_item_sk
WHERE d.d_year = 2001 AND d.d_moy BETWEEN 1 AND 4
GROUP BY 1 ORDER BY 3 DESC
""")

sql("cache_proof", """
-- Scorecard: every tagged job in THIS run vs what the warehouse was actually metered
ALTER SESSION UNSET QUERY_TAG;
WITH runs AS (
  SELECT query_tag, warehouse_size, start_time, total_elapsed_time / 1000 AS seconds, bytes_scanned
  FROM TABLE(BP_DEMO.INFORMATION_SCHEMA.QUERY_HISTORY(RESULT_LIMIT => 1000))
  WHERE query_tag LIKE 'bp_demo:{{run_id}}:%' AND query_type IN ('COPY', 'SELECT') AND execution_status = 'SUCCESS'
), jobs AS (
  SELECT 1 AS sort, start_time, query_tag AS line_item,
         IFF(bytes_scanned = 0 AND warehouse_size IS NULL, 'result cache', warehouse_size) AS ran_on,
         ROUND(seconds, 1) AS seconds,
         ROUND(seconds * COALESCE(DECODE(warehouse_size, 'X-Small', 1, 'Small', 2, 'Medium', 4, 'Large', 8), 0) / 3600, 4) AS credits
  FROM runs
), other AS (   -- untagged work on the same warehouse in the same window (Dynamic Table refreshes, other users)
  SELECT SUM(execution_time) / 1000 AS seconds,
         SUM(execution_time / 1000 * DECODE(warehouse_size, 'X-Small', 1, 'Small', 2, 'Medium', 4, 'Large', 8) / 3600) AS credits
  FROM TABLE(BP_DEMO.INFORMATION_SCHEMA.QUERY_HISTORY_BY_WAREHOUSE(WAREHOUSE_NAME => 'BP_DEMO_WH',
         END_TIME_RANGE_START => DATEADD('hour', -3, CURRENT_TIMESTAMP()), RESULT_LIMIT => 10000))
  WHERE start_time >= DATE_TRUNC('hour', (SELECT MIN(start_time) FROM runs)) AND execution_status = 'SUCCESS'
    AND warehouse_size IS NOT NULL AND COALESCE(query_tag, '') NOT LIKE 'bp_demo:{{run_id}}:%'
), metered AS (
  SELECT SUM(credits_used_compute) AS credits
  FROM TABLE(BP_DEMO.INFORMATION_SCHEMA.WAREHOUSE_METERING_HISTORY(
         DATE_RANGE_START => DATEADD('hour', -3, CURRENT_TIMESTAMP()), WAREHOUSE_NAME => 'BP_DEMO_WH'))
  WHERE start_time >= DATE_TRUNC('hour', (SELECT MIN(start_time) FROM runs))
)
SELECT line_item, ran_on, seconds, credits FROM (
  SELECT * FROM jobs
  UNION ALL SELECT 2, NULL, 'ATTRIBUTED: sum of tagged jobs', NULL, SUM(seconds), SUM(credits) FROM jobs
  UNION ALL SELECT 3, NULL, 'OTHER: untagged work on BP_DEMO_WH (Dynamic Tables, other users)', NULL, ROUND(seconds, 1), ROUND(credits, 4) FROM other
  UNION ALL SELECT 4, NULL, 'METERED: BP_DEMO_WH compute billed, hour(s) of this run', NULL, NULL, ROUND(credits, 4) FROM metered
  UNION ALL SELECT 5, NULL, 'GAP ≈ idle before auto-suspend + 60s resume minimums', NULL, NULL,
                   ROUND((SELECT credits FROM metered) - (SELECT SUM(credits) FROM jobs) - COALESCE((SELECT credits FROM other), 0), 4)
) ORDER BY sort, start_time
""")

md("""
Each tagged job shows its seconds and its share of credits; the cached run cost nothing. The metered line is the bill: it's higher because the warehouse also bills idle seconds before it suspends, a 60-second minimum on each resume, and anything else on this warehouse: our Dynamic Tables refresh here too, and they keep it awake. That's why each workload gets its own warehouse, and why the tags matter.

> Metering is reported per hour, so the METERED line covers whole clock hours from the first tagged job. Run `99_reset.sql` section E before the live demo, and rehearse in a different clock hour, so METERED only counts the live run. Each run of the `run_id` cell gives new tags, so rehearsal rows never appear here or in `ACCOUNT_USAGE` under the live run's tag.

👉 *Do:* open **Monitoring → Query History**, click the newest query → *Query Profile* shows **"QUERY RESULT REUSE"**. (There is also a **warehouse cache**: recently read data stays on the warehouse's local disk while it's running.)
""")

md("""
## 1.6 Zero-copy cloning: a full dev copy in seconds, at no extra storage cost
A clone shares the original's storage until you change something. Typical uses: **dev/test environments, safe experiments, a frozen month-end snapshot**, or a sandbox per attendee. Works on tables, schemas and whole databases.
""")

sql("clone", """
CREATE OR REPLACE TABLE BP_DEMO.GOV.GRANTEE_DIRECTORY_DEV CLONE BP_DEMO.GOV.GRANTEE_DIRECTORY;
-- A whole database works the same way (instant, regardless of size):
-- CREATE DATABASE BP_DEMO_DEV CLONE BP_DEMO;
SELECT 'prod' AS copy, COUNT(*) AS row_count FROM BP_DEMO.GOV.GRANTEE_DIRECTORY
UNION ALL SELECT 'dev clone', COUNT(*) FROM BP_DEMO.GOV.GRANTEE_DIRECTORY_DEV
""")

md("""
## 1.7 Time Travel: undo mistakes
Snowflake keeps the history of every change (1 day by default, up to 90 on Enterprise). You can **query the past**, **restore** it, and **UNDROP** dropped objects.

### 👉 Do: make a mistake on purpose (in the dev clone)
""")

sql("oops", """
-- Note the time, then make the mistake: an UPDATE with no WHERE clause wipes every budget
SET before_oops = CURRENT_TIMESTAMP();
UPDATE BP_DEMO.GOV.GRANTEE_DIRECTORY_DEV SET annual_budget_usd = 0;
SET bad_query_id = LAST_QUERY_ID();
SELECT SUM(annual_budget_usd) AS total_budget_now FROM BP_DEMO.GOV.GRANTEE_DIRECTORY_DEV
""")

sql("travel", """
-- Query the table as it was just BEFORE the bad statement, or AT a point in time (TIMESTAMP or OFFSET => -seconds)
SELECT 'before the mistake (by statement)' AS version, SUM(annual_budget_usd) AS total_budget
FROM BP_DEMO.GOV.GRANTEE_DIRECTORY_DEV BEFORE (STATEMENT => $bad_query_id)
UNION ALL
SELECT 'at a timestamp', SUM(annual_budget_usd) FROM BP_DEMO.GOV.GRANTEE_DIRECTORY_DEV AT (TIMESTAMP => $before_oops)
UNION ALL
SELECT 'now', SUM(annual_budget_usd) FROM BP_DEMO.GOV.GRANTEE_DIRECTORY_DEV
""")

sql("restore", """
-- Restore: overwrite with the historical version
INSERT OVERWRITE INTO BP_DEMO.GOV.GRANTEE_DIRECTORY_DEV
  SELECT * FROM BP_DEMO.GOV.GRANTEE_DIRECTORY_DEV BEFORE (STATEMENT => $bad_query_id);
SELECT SUM(annual_budget_usd) AS restored_total FROM BP_DEMO.GOV.GRANTEE_DIRECTORY_DEV
""")

sql("undrop", """
-- Even DROP is reversible
DROP TABLE BP_DEMO.GOV.GRANTEE_DIRECTORY_DEV;
UNDROP TABLE BP_DEMO.GOV.GRANTEE_DIRECTORY_DEV;
SELECT COUNT(*) AS rows_back FROM BP_DEMO.GOV.GRANTEE_DIRECTORY_DEV
""")

md("""
Clone + Time Travel combined: `CREATE TABLE … CLONE … AT (TIMESTAMP => '…')` gives you yesterday's data as a new table. No restore tickets, no backup tapes.
""")

# =====================================================================  V2
md("""
---
# Vignette 2 — Simple Data Pipelines: semi-structured JSON + Dynamic Tables
""")

py(r"""
# Diagram: Vignette 2 pipeline architecture (static picture, no queries)
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle

fig, ax = plt.subplots(figsize=(16, 6.6))
ax.set_xlim(0, 16); ax.set_ylim(0, 6.6); ax.axis("off")

C_SRC, C_STG, C_PIPE, C_RAW, C_DT, C_AI, C_SLA, C_USE = (
    "#F2F3F4", "#E8EEF4", "#FCF3CF", "#E8EEF4", "#D6EAF8", "#FDEBD0", "#D5F5E3", "#EDE7F6")

def box(x, y, w, h, title, sub, color, edge="#34495E", bold=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.04,rounding_size=0.12",
                                fc=color, ec=edge, lw=2.2 if bold else 1.1))
    ax.text(x + w / 2, y + h - 0.2, title, ha="center", va="top", fontsize=8.9, weight="bold")
    ax.text(x + w / 2, y + h - 0.55, sub, ha="center", va="top", fontsize=7.6, color="#2C3E50", linespacing=1.3)

def arrow(x1, y1, x2, y2, rad=0.0, dashed=False, color="#566573"):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=13, lw=1.4, color=color,
                                 connectionstyle=f"arc3,rad={rad}", linestyle="--" if dashed else "-"))

# zone bands
ax.add_patch(Rectangle((3.05, 0.55), 4.6, 5.35, fc="#FEF9E7", ec="none", zorder=0))
ax.add_patch(Rectangle((7.75, 0.55), 6.15, 5.35, fc="#EBF5FB", ec="none", zorder=0))
ax.text(5.35, 6.05, "INGEST: serverless, no warehouse", ha="center", fontsize=9.5, weight="bold", color="#B7950B")
ax.text(10.8, 6.05, "TRANSFORM: Dynamic Tables on BP_DEMO_WH", ha="center", fontsize=9.5, weight="bold", color="#2E86C1")
ax.text(1.4, 6.05, "SOURCES", ha="center", fontsize=9.5, weight="bold", color="#7F8C8D")
ax.text(14.95, 6.05, "CONSUME", ha="center", fontsize=9.5, weight="bold", color="#7F8C8D")

# sources
box(0.1, 3.6, 2.6, 1.3, "Fluxx \"2DB\" export", "grant applications\nJSON, nested arrays", C_SRC)
box(0.1, 1.3, 2.6, 1.3, "Salesforce extract", "donor opportunities\nJSON", C_SRC)
ax.text(1.4, 0.75, "demo: RAW.GEN_MOCK_FILES / task T_FEED\nsimulates the deliveries", ha="center", fontsize=7.3, color="#7F8C8D", style="italic")

# stage + pipes + raw
box(3.15, 2.2, 1.55, 1.9, "@LANDING_STAGE", "internal stage\n/fluxx/  /sfdc/\ndirectory table", C_STG)
box(4.95, 3.65, 1.25, 1.2, "PIPE_FLUXX", "Snowpipe\n(COPY INTO)", C_PIPE, edge="#B7950B")
box(4.95, 1.45, 1.25, 1.2, "PIPE_SFDC", "Snowpipe\n(COPY INTO)", C_PIPE, edge="#B7950B")
box(6.4, 3.65, 1.2, 1.2, "RAW_FLUXX", "VARIANT\nraw JSON", C_RAW)
box(6.4, 1.45, 1.2, 1.2, "RAW_SFDC", "VARIANT\nraw JSON", C_RAW)

# dynamic tables
box(7.9, 3.65, 1.75, 1.2, "DT_GRANTS_FLAT", "FLATTEN + types\nlatest version", C_DT)
box(7.9, 1.45, 1.75, 1.2, "DT_OPPS_FLAT", "FLATTEN + types\nlatest version", C_DT)
box(7.9, 5.0, 1.75, 0.68, "DT_GRANT_BUDGET", "budget lines", C_DT)
box(9.9, 3.65, 1.75, 1.2, "DT_GRANTS_ENRICHED", "AI_COMPLETE\nAI_CLASSIFY", C_AI, edge="#E67E22", bold=True)
box(9.9, 1.45, 1.75, 1.2, "DT_OPPS_ENRICHED", "SENTIMENT", C_AI, edge="#E67E22", bold=True)
box(11.95, 2.3, 1.85, 1.7, "DT_GRANT_PIPELINE", "grant + AI + donor\npipeline, one row/grant\nTARGET_LAG 5 min", C_SLA, edge="#27AE60", bold=True)

# consumers
box(14.05, 3.95, 1.85, 1.1, "Semantic view", "SV_GRANT_PIPELINE", C_USE)
box(14.05, 2.6, 1.85, 1.1, "Agent", "Philanthropy\nInsights Agent", C_USE)
box(14.05, 1.25, 1.85, 1.1, "SQL / BI", "notebook, Tableau", C_USE)

# arrows
arrow(2.75, 4.25, 3.1, 3.6); arrow(2.75, 1.95, 3.1, 2.7)
arrow(4.75, 3.6, 4.9, 4.2); arrow(4.75, 2.7, 4.9, 2.05)
arrow(6.25, 4.25, 6.35, 4.25); arrow(6.25, 2.05, 6.35, 2.05)
arrow(7.65, 4.25, 7.85, 4.25); arrow(7.65, 2.05, 7.85, 2.05)
arrow(8.78, 4.9, 8.78, 4.98)            # grants flat -> budget
arrow(9.7, 4.25, 9.85, 4.25); arrow(9.7, 2.05, 9.85, 2.05)
arrow(11.7, 4.2, 11.9, 3.6); arrow(11.7, 2.1, 11.9, 2.75)
arrow(13.85, 3.6, 14.0, 4.4); arrow(13.85, 3.15, 14.0, 3.15); arrow(13.85, 2.7, 14.0, 1.85)

ax.text(8.0, 0.2,
        "File lands → Snowpipe loads it once → JSON stays raw in VARIANT → Dynamic Tables flatten, dedup, add AI and join, "
        "refreshed (mostly incrementally) to meet a 5-minute SLA.   Replaces: 2DB → SQL Server staging → stored procs → SQL Agent.",
        ha="center", fontsize=8.6, color="#2C3E50")
ax.set_title("Vignette 2: simple data pipeline architecture (Snowpipe + Dynamic Tables)", fontsize=13.5, weight="bold", loc="left")
plt.tight_layout()
plt.show()
""")

md("""
- **VARIANT** stores raw JSON as-is, with nested arrays and no schema up front. When Fluxx adds a field, nothing breaks.
- **Snowpipe** is a serverless COPY INTO that loads each file once. In production it fires on cloud events (Azure Event Grid). On this internal stage we trigger it with `ALTER PIPE … REFRESH`.
- **Dynamic Table**: write the SELECT, set how fresh it must be (`TARGET_LAG`), and Snowflake handles scheduling, dependencies and incremental refresh. **This replaces the stored procedures and SQL Agent jobs.**

## 2.1 New files arrive → Snowpipe loads them
""")

sql("land_files", """
-- Simulate a delivery: 5 grant applications (40% are status updates) + 5 donor opportunities
CALL BP_DEMO.RAW.GEN_MOCK_FILES(5, 5, 0.4)
""")

sql("list_landing", """
ALTER STAGE BP_DEMO.RAW.LANDING_STAGE REFRESH;   -- sync the directory table so the new files show up
SELECT relative_path, size, last_modified FROM DIRECTORY(@BP_DEMO.RAW.LANDING_STAGE) ORDER BY last_modified DESC LIMIT 6
""")

sql("pipe_refresh", """
ALTER STAGE BP_DEMO.RAW.LANDING_STAGE REFRESH;
ALTER PIPE BP_DEMO.RAW.PIPE_FLUXX REFRESH;      -- simulates auto-ingest
ALTER PIPE BP_DEMO.RAW.PIPE_SFDC  REFRESH;
""")

py("""
import time; time.sleep(30)   # Snowpipe is asynchronous: usually seconds
print("waited 30s")
""")

sql("copy_hist", """
SELECT table_name, file_name, last_load_time, row_count, status, first_error_message
FROM TABLE(BP_DEMO.INFORMATION_SCHEMA.COPY_HISTORY(TABLE_NAME => 'BP_DEMO.RAW.RAW_FLUXX', START_TIME => DATEADD('hour', -2, CURRENT_TIMESTAMP())))
UNION ALL
SELECT table_name, file_name, last_load_time, row_count, status, first_error_message
FROM TABLE(BP_DEMO.INFORMATION_SCHEMA.COPY_HISTORY(TABLE_NAME => 'BP_DEMO.RAW.RAW_SFDC', START_TIME => DATEADD('hour', -2, CURRENT_TIMESTAMP())))
ORDER BY last_load_time DESC LIMIT 8
""")

sql("raw_json", """
-- Raw JSON, unchanged: click a PAYLOAD cell to expand the nested arrays
SELECT file_name, loaded_at, payload FROM BP_DEMO.RAW.RAW_FLUXX ORDER BY loaded_at DESC LIMIT 3
""")

md("""
## 2.2 Querying JSON: path notation, casting, FLATTEN
""")

sql("json_paths", """
-- Dot/colon paths + ::casts read JSON like columns; FLATTEN turns arrays into rows
SELECT r.value:grant_id::STRING          AS grant_id,
       r.value:organization_name::STRING AS organization_name,
       r.value:program_area::STRING      AS program_area,
       b.value:line_item::STRING         AS budget_line,
       b.value:amount::NUMBER(14,2)      AS amount
FROM BP_DEMO.RAW.RAW_FLUXX t,
     LATERAL FLATTEN(INPUT => t.payload:records) r,
     LATERAL FLATTEN(INPUT => r.value:budget_breakdown) b
LIMIT 12
""")

md("""
## 2.3 Dynamic Tables replace the stored procedures
👉 *Do:* show `bp_demo/legacy_sp_example.sql` (temp tables, OPENJSON, a cursor, TRUNCATE/INSERT, SQL Agent), then open **Catalog → BP_DEMO → CURATED → DT_GRANT_PIPELINE → Graph**.
""")

py(r"""
# Diagram: how Dynamic Table refresh works (static picture, no queries)
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

fig, ax = plt.subplots(figsize=(15, 6.4))
ax.set_xlim(0, 15); ax.set_ylim(0.5, 7.0); ax.axis("off")

C_SRC, C_DOWN, C_SLA, C_ENG, C_NOTE = "#E8EEF4", "#D6EAF8", "#D5F5E3", "#FDEBD0", "#F4F6F7"

def box(x, y, w, h, title, sub, color, edge="#34495E", bold=False, fs=8.3):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.05,rounding_size=0.15",
                                fc=color, ec=edge, lw=2.2 if bold else 1.2))
    ax.text(x + w / 2, y + h - 0.25, title, ha="center", va="top", fontsize=10, weight="bold")
    ax.text(x + w / 2, y + h - 0.62, sub, ha="center", va="top", fontsize=fs, color="#2C3E50", linespacing=1.35)

def arrow(x1, y1, x2, y2, label=None, rad=0.0, dashed=False, color="#566573", dy=0.13):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=14, lw=1.5, color=color,
                                 connectionstyle=f"arc3,rad={rad}", linestyle="--" if dashed else "-"))
    if label:
        ax.text((x1 + x2) / 2, (y1 + y2) / 2 + dy, label, ha="center", fontsize=7.6, color=color, style="italic")

# ---- top row: the DAG with lag settings
box(0.1, 4.6, 1.9, 1.5, "RAW_FLUXX\nRAW_SFDC", "\nbase tables\nCHANGE_TRACKING = TRUE", C_SRC)
box(2.7, 4.6, 2.3, 1.5, "*_FLAT + BUDGET  (3)", "TARGET_LAG = DOWNSTREAM\nrefresh: INCREMENTAL", C_DOWN)
box(5.7, 4.6, 2.5, 1.5, "*_ENRICHED  (2)", "TARGET_LAG = DOWNSTREAM\nrefresh: INCREMENTAL\n(AI runs on new rows only)", C_DOWN)
box(8.9, 4.4, 2.6, 1.9, "DT_GRANT_PIPELINE", "TARGET_LAG = '5 minutes'\nrefresh: FULL\n(join + GROUP BY: cheap,\nno AI here)", C_SLA, edge="#27AE60", bold=True)
box(12.2, 4.6, 2.6, 1.5, "Consumers", "semantic view, agent,\nTableau, notebook\ntarget: ≤ 5 min behind", "#EDE7F6")

arrow(2.05, 5.35, 2.65, 5.35)
arrow(5.05, 5.35, 5.65, 5.35)
arrow(8.25, 5.35, 8.85, 5.35)
arrow(11.55, 5.35, 12.15, 5.35)
for x, t in [(1.05, "SOURCE"), (3.85, "INTERMEDIATE"), (6.95, "INTERMEDIATE"), (10.2, "THE ONLY SLA"), (13.5, "READ")]:
    ax.text(x, 6.5, t, ha="center", fontsize=9, weight="bold", color="#7F8C8D")

# ---- pull arrow: lag propagates upstream
arrow(10.2, 4.35, 3.85, 4.35, "the 5-min SLA is pushed UPSTREAM: DOWNSTREAM tables refresh only when the SLA table needs them",
      rad=0.0, dashed=True, color="#27AE60", dy=-0.32)

# ---- bottom: the refresh engine, step by step
box(0.1, 1.15, 3.4, 2.15, "① Scheduler (Snowflake-managed)",
    "Checks every DT against its lag.\nNo cron, no SQL Agent job,\nno dependency ordering to code.\nUses warehouse BP_DEMO_WH\nonly while refreshing.", C_ENG, edge="#E67E22")
box(3.85, 1.15, 3.6, 2.15, "② Change detection",
    "Change tracking on the sources\nsays which rows were inserted,\nupdated or deleted since the\nlast refresh. Nothing changed\n→ NO_DATA (skipped, ~free).", C_ENG, edge="#E67E22")
box(7.8, 1.15, 3.6, 2.15, "③ Refresh in dependency order",
    "INCREMENTAL: merge only the\nchanged rows (most DTs here).\nFULL: recompute the whole\nquery (Snowflake picks it when\nthat's simpler: AUTO mode).", C_ENG, edge="#E67E22")
box(11.75, 1.15, 3.1, 2.15, "④ Consistent snapshot",
    "All DTs in one refresh share a\nsingle data_timestamp, so\nreaders never see half-updated\ndata. History lives in\nDYNAMIC_TABLE_REFRESH_HISTORY.", C_ENG, edge="#E67E22")
arrow(3.55, 2.2, 3.8, 2.2); arrow(7.5, 2.2, 7.75, 2.2); arrow(11.45, 2.2, 11.7, 2.2)

ax.text(7.5, 3.55, "HOW A REFRESH RUNS", ha="center", fontsize=9.5, weight="bold", color="#7F8C8D")
ax.text(7.5, 0.72,
        "Legacy: SQL Agent job → stored proc → temp tables → TRUNCATE/INSERT on a fixed schedule.   "
        "Here: declare the SELECT + the freshness you need; Snowflake does the rest.",
        ha="center", fontsize=8.8, color="#2C3E50")
ax.set_title("Dynamic Tables: how refresh works (DT_GRANT_PIPELINE, section 2.3)", fontsize=13.5, weight="bold", loc="left")
plt.tight_layout()
plt.show()
""")

md("""
Only the last table has a business SLA: 5 minutes. Everything upstream is set to DOWNSTREAM, so it refreshes only when that SLA needs it. Snowflake works out the order, reads only what changed, and skips the run entirely if nothing did. No SQL Agent, no cursors, no TRUNCATE/INSERT.

👉 *Do: open the live graph*
1. **Catalog → Database Explorer → BP_DEMO → CURATED → Dynamic Tables → DT_GRANT_PIPELINE**
2. Click the **Graph** tab: the same chain as the picture, RAW tables through to the SLA table, with each node's lag and status.
3. Click a node, e.g. **DT_GRANTS_ENRICHED**, then the **Refresh History** tab: INCREMENTAL / NO_DATA / FULL per refresh, rows changed, duration.
4. (Optional) **Monitoring → Dynamic Tables** for every DT on the account in one list.

Then come back and run the next cells (`dt_ddl`, `dt_refresh`, `dt_status`, `dt_history`) to show the same facts in SQL.
""")

sql("dt_ddl", """
SELECT GET_DDL('DYNAMIC_TABLE', 'BP_DEMO.CURATED.DT_GRANTS_FLAT') AS flatten_and_dedup,
       GET_DDL('DYNAMIC_TABLE', 'BP_DEMO.CURATED.DT_GRANT_PIPELINE') AS conformed_sla_table
""")

sql("dt_refresh", """
-- Skip the 5-minute wait during the demo: refresh now (upstream tables refresh too)
ALTER DYNAMIC TABLE BP_DEMO.CURATED.DT_GRANT_PIPELINE REFRESH
""")

sql("dt_status", """
SHOW DYNAMIC TABLES IN DATABASE BP_DEMO
->> SELECT "name", "target_lag", "refresh_mode", "scheduling_state", "data_timestamp" FROM $1 ORDER BY "name"
""")

sql("dt_history", """
SELECT name, refresh_action, state, refresh_start_time,
       DATEDIFF('second', refresh_start_time, refresh_end_time) AS seconds
FROM TABLE(BP_DEMO.INFORMATION_SCHEMA.DYNAMIC_TABLE_REFRESH_HISTORY())
WHERE name LIKE 'DT_%' ORDER BY refresh_start_time DESC LIMIT 12
""")

md("""
About 120 lines of declarative SQL replace the stored procedures, the cursor and the scheduler. **INCREMENTAL** means only new rows are processed. The 10-minute SLA becomes a setting: `TARGET_LAG = '5 minutes'`.

*Continuous feed:* `ALTER TASK BP_DEMO.RAW.T_FEED RESUME;` lands new files every 3 minutes (a **Task** is the built-in scheduler, replacing SQL Agent). See Appendix B for **Snowpipe vs. triggered COPY INTO**.
""")

# =====================================================================  V3
md("""
---
# Vignette 3 — Snowflake Cortex AI

| Theme | What we show |
|---|---|
| **Experimentation** | Call an LLM from SQL on one record; try it in **AI & ML → Playground** |
| **Scalable analysis** | AI functions inside the pipeline on every row (incremental), and `AI_AGG` across hundreds of rows |
| **AI-assisted development** | **Cortex Code / Copilot** in Snowsight and Workspaces writes and explains SQL for you |
| **Conversational BI** | Semantic View + Cortex Agent in **Snowflake Intelligence** replacing static reports |

The data never leaves Snowflake and is governed by the same roles and policies as everything else.

## 3.1 Experiment: one record, one prompt
""")

sql("ai_experiment", """
SELECT organization_name, program_area,
       AI_COMPLETE('llama3.3-70b',
         'You are a philanthropy program director. In 3 bullet points, list the key risks and one question to ask the applicant:\\n\\n'
         || reviewer_notes) AS ai_brief
FROM BP_DEMO.CURATED.DT_GRANTS_FLAT
WHERE status = 'Under Review'
ORDER BY requested_amount DESC LIMIT 1
""")

md("""
👉 *Do:* **AI & ML → Playground**: paste a reviewer note and compare models side by side. No code.

## 3.2 Scalable analysis: AI on every row, inside the pipeline
`DT_GRANTS_ENRICHED` and `DT_OPPS_ENRICHED` run these on each new or changed row, once:

| Column | Function |
|---|---|
| `ai_reviewer_summary` | `AI_COMPLETE`: one-sentence executive summary |
| `ai_primary_risk` | `AI_CLASSIFY`: risk theme |
| `donor_sentiment` | `SENTIMENT`: −1 to +1 |
""")

py(r"""
# Diagram: how the AI columns are produced by the Dynamic Table pipeline (static picture, no queries)
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

fig, ax = plt.subplots(figsize=(15, 6.4))
ax.set_xlim(0, 15); ax.set_ylim(0, 6.4); ax.axis("off")

C_RAW, C_DT, C_AI, C_SLA, C_USE = "#E8EEF4", "#D6EAF8", "#FDEBD0", "#D5F5E3", "#EDE7F6"

def box(x, y, w, h, title, sub, color, edge="#34495E", bold=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.05,rounding_size=0.15",
                                fc=color, ec=edge, lw=2.2 if bold else 1.2))
    ax.text(x + w / 2, y + h - 0.28, title, ha="center", va="top", fontsize=10.5, weight="bold")
    ax.text(x + w / 2, y + h - 0.68, sub, ha="center", va="top", fontsize=8.3, color="#2C3E50", linespacing=1.35)

def arrow(x1, y1, x2, y2, label=None, rad=0.0, dashed=False):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=14, lw=1.4, color="#566573",
                                 connectionstyle=f"arc3,rad={rad}", linestyle="--" if dashed else "-"))
    if label:
        ax.text((x1 + x2) / 2, (y1 + y2) / 2 + 0.12, label, ha="center", fontsize=7.5, color="#566573", style="italic")

# column headers
for x, t in [(0.9, "1. LAND (Snowpipe)"), (3.85, "2. FLATTEN + DEDUP"), (7.0, "3. AI ENRICHMENT"), (10.2, "4. SLA TABLE"), (13.1, "5. CONSUME")]:
    ax.text(x, 6.15, t, ha="center", fontsize=9.5, weight="bold", color="#7F8C8D")

# raw
box(0.1, 3.5, 1.6, 1.6, "RAW_FLUXX", "Fluxx JSON\n(VARIANT)", C_RAW)
box(0.1, 1.0, 1.6, 1.6, "RAW_SFDC", "Salesforce JSON\n(VARIANT)", C_RAW)

# flatten DTs
box(2.7, 3.5, 2.3, 1.6, "DT_GRANTS_FLAT", "FLATTEN + typing\nQUALIFY latest version\nINCREMENTAL", C_DT)
box(2.7, 1.0, 2.3, 1.6, "DT_OPPS_FLAT", "FLATTEN + typing\nQUALIFY latest version\nINCREMENTAL", C_DT)

# AI DTs
box(5.75, 3.2, 2.5, 2.2, "DT_GRANTS_ENRICHED",
    "AI_COMPLETE(llama3.3-70b)\n→ ai_reviewer_summary\nAI_CLASSIFY(6 themes)\n→ ai_primary_risk\nINCREMENTAL: each row once", C_AI, edge="#E67E22", bold=True)
box(5.75, 0.7, 2.5, 2.0, "DT_OPPS_ENRICHED",
    "SENTIMENT(notes)\n→ donor_sentiment (-1..1)\n→ donor_health bucket\nINCREMENTAL: each row once", C_AI, edge="#E67E22", bold=True)

# SLA
box(9.0, 2.0, 2.4, 2.4, "DT_GRANT_PIPELINE", "grant + AI fields\n+ donor pipeline rollup\nTARGET_LAG = 5 min\n(drives everything\nupstream: DOWNSTREAM lag)", C_SLA, edge="#27AE60", bold=True)

# consumers
box(12.1, 4.3, 2.8, 1.25, "Semantic View + Agent", "SV_GRANT_PIPELINE →\nPhilanthropy Insights Agent", C_USE)
box(12.1, 2.6, 2.8, 1.25, "Cortex Search", "CSS_GRANT_REVIEWS\nCSS_DONOR_NOTES", C_USE)
box(12.1, 0.9, 2.8, 1.25, "SQL / notebook / Tableau", "ai_grants, ai_donors,\nrisk_mix cells (3.2)", C_USE)

arrow(1.75, 4.3, 2.65, 4.3, "FLATTEN")
arrow(1.75, 1.8, 2.65, 1.8, "FLATTEN")
arrow(5.05, 4.3, 5.7, 4.3)
arrow(5.05, 1.8, 5.7, 1.8)
arrow(8.3, 4.2, 8.95, 3.6)
arrow(8.3, 1.7, 8.95, 2.6)
arrow(11.45, 3.6, 12.05, 4.9)        # pipeline -> semantic view / agent
arrow(11.45, 2.6, 12.05, 1.5)        # pipeline -> SQL / notebook
arrow(8.3, 5.2, 12.05, 3.55, rad=-0.35, dashed=True)   # grants enriched -> search (over the SLA box)
arrow(8.3, 0.85, 12.05, 2.75, rad=0.35, dashed=True)   # opps enriched -> search (under the SLA box)
ax.text(10.2, 5.75, "reviewer notes + AI summaries indexed (dashed)", ha="center", fontsize=7.5, color="#566573", style="italic")

ax.text(7.5, 0.15,
        "New file lands → Snowpipe → only the NEW / CHANGED rows flow right → AI is called once per new row → "
        "results are ordinary columns.   Orange = Cortex AI inside the pipeline.",
        ha="center", fontsize=8.8, color="#2C3E50")
ax.set_title("Dynamic Tables: how the AI-driven output is produced (BP_DEMO)", fontsize=13.5, weight="bold", loc="left")
plt.tight_layout()
plt.show()
""")

md("""
The AI isn't a separate step someone runs. It's a column definition inside a Dynamic Table. When a new Fluxx file lands, only those new rows flow through, AI scores each one once, and the 5-minute SLA table on the right drives the whole chain. The next cells just read those columns.

👉 *Do (live version of this picture):* **Catalog → BP_DEMO → CURATED → DT_GRANT_PIPELINE → Graph**.
""")

sql("ai_grants", """
SELECT organization_name, program_area, status, requested_amount,
       LEFT(reviewer_notes, 250) || '…' AS reviewer_notes_excerpt, ai_reviewer_summary, ai_primary_risk
FROM BP_DEMO.AI.DT_GRANTS_ENRICHED ORDER BY requested_amount DESC LIMIT 5
""")

sql("ai_donors", """
SELECT account_name, donor_type, stage, donor_engagement_notes, ROUND(donor_sentiment, 2) AS sentiment, donor_health
FROM BP_DEMO.AI.DT_OPPS_ENRICHED ORDER BY donor_sentiment LIMIT 5
""")

sql("risk_mix", """
SELECT program_area, ai_primary_risk, COUNT(*) AS grants
FROM BP_DEMO.AI.DT_GRANTS_ENRICHED WHERE status = 'Under Review' GROUP BY ALL ORDER BY program_area, grants DESC
""")

py("""
import altair as alt
alt.renderers.enable("mimetype")
df = risk_mix.to_pandas()          # small aggregate (~30 rows)
alt.Chart(df).mark_bar().encode(
    x=alt.X("GRANTS:Q", title="Grants under review"), y=alt.Y("PROGRAM_AREA:N", title=None),
    color=alt.Color("AI_PRIMARY_RISK:N", title="AI risk theme"),
    tooltip=["PROGRAM_AREA", "AI_PRIMARY_RISK", "GRANTS"],
).properties(title="What reviewers are worried about (AI_CLASSIFY)", width=600, height=220)
""")

sql("ai_agg", """
-- AI_AGG: read ALL the summaries in a group and synthesise themes (one call per program area)
SELECT program_area,
       AI_AGG(ai_reviewer_summary, 'In 2 sentences, what are the most common reasons these grant applications are at risk?') AS portfolio_themes
FROM BP_DEMO.AI.DT_GRANTS_ENRICHED
WHERE status = 'Under Review'
GROUP BY 1
""")

md("""
## 3.3 AI-assisted development
👉 *Do:* in a Workspace SQL file, open **Cortex Code** and ask: *"Write a query showing approval rate by program officer from BP_DEMO.CURATED.DT_GRANT_PIPELINE"*, then *"Explain this query"* on `DT_GRANTS_FLAT`'s DDL.
Your team doesn't need to be SQL experts on day one.

## 3.4 Conversational BI: Semantic View + Cortex Agent
- **Semantic View** `AI.SV_GRANT_PIPELINE`: the business definitions (*awarded*, *approval rate*, *weighted pipeline*, *sentiment*, synonyms, 4 verified queries), defined once for every user, agent and tool.
- **Cortex Search** over reviewer and donor notes, for the "why" questions.
- **Cortex Agent** `BP_GRANTS_AGENT`: picks the tool, writes the SQL, and answers. 👉 *Do:* **AI & ML → Snowflake Intelligence → Philanthropy Insights Agent**.
""")

sql("sv_yaml", """
SELECT SYSTEM$READ_YAML_FROM_SEMANTIC_VIEW('BP_DEMO.AI.SV_GRANT_PIPELINE') AS semantic_view_yaml
""")

sql("sv_query", """
SELECT * FROM SEMANTIC_VIEW(
  BP_DEMO.AI.SV_GRANT_PIPELINE
  DIMENSIONS grants.program_area
  METRICS grants.grant_count, grants.total_requested_amount, grants.total_approved_amount,
          grants.approval_rate, opportunities.avg_donor_sentiment)
WHERE program_area IS NOT NULL ORDER BY total_requested_amount DESC
""")

md("""
**Questions to ask** (in Snowflake Intelligence, or edit `question` below):
1. What is the total requested amount for Arts and Education grants currently under review?
2. What is our approval rate and total awarded by program area?
3. Show the top 5 Environment grants by requested amount with their AI summaries.
4. Which program officers have the most dollars under review, and what's the most common AI risk theme in their portfolio?
5. Break down requested budgets by line item for Government Innovation. How much goes to Evaluation & Data?
6. Summarize the main concerns reviewers raised on Public Health grants under review. *(Search)*
7. Which Arts organizations have the best reviewer scores, and what strengths did reviewers highlight? *(mixed)*
8. Which corporate partners are at risk, and which relationship managers own them? *(Analyst + Search)*
9. What is our probability-weighted co-funding pipeline by donor type?
10. Which program area has the lowest average donor sentiment, and what are those donors saying?
""")

py("""
import json
from snowflake.snowpark.context import get_active_session
session = get_active_session()

question = "What is the total requested amount for Arts and Education grants currently under review?"

body = json.dumps({"messages": [{"role": "user", "content": [{"type": "text", "text": question}]}]})
# DATA_AGENT_RUN needs a constant request body, so pass it as a $$-quoted literal
raw = session.sql(f"SELECT SNOWFLAKE.CORTEX.DATA_AGENT_RUN('BP_DEMO.AI.BP_GRANTS_AGENT', $${body.replace('$$', '')}$$) AS r").collect()[0]["R"]
resp = json.loads(raw)
tools = [c["tool_use"]["name"] for c in resp.get("content", []) if c.get("type") == "tool_use"]
print("Tools used:", ", ".join(dict.fromkeys(tools)) or "-")
print("-" * 80)
print("\\n".join(c["text"] for c in resp.get("content", []) if c.get("type") == "text"))
""")

sql("truth_check", """
-- Trust but verify: the same answer in plain SQL
SELECT program_area, COUNT(*) AS grants, SUM(requested_amount) AS total_requested
FROM BP_DEMO.CURATED.DT_GRANT_PIPELINE
WHERE status = 'Under Review' AND program_area IN ('Arts', 'Education') GROUP BY 1
""")

md("""
Each of those would have been a separate Tableau report. Now 8,000 users get one governed semantic layer, and every answer can be traced back to SQL.
""")

# =====================================================================  V4
md("""
---
# Vignette 4 — Governance with Horizon: roles, classification, masking, row access

**The ask:** program officers should see **only their own portfolio**, and grantee contact **PII** (names, emails, phones, tax IDs) must be protected. In Snowflake you define each rule **once on the data**, and it applies everywhere: SQL, notebooks, Tableau, the AI agent.

| Control | Answers | Object |
|---|---|---|
| **Roles (RBAC)** | *Who can access which objects?* | `BP_ANALYST`, `BP_PO_PUBLIC_HEALTH`, `BP_PO_ENVIRONMENT`, `BP_GRANTS_COMPLIANCE` |
| **Classification** | *Where is our sensitive data?* | `SYSTEM$CLASSIFY` |
| **Masking policy** | *Which column values can this role see?* | `MASK_PII_STRING`, `MASK_EMAIL`, `MASK_TAX_ID` |
| **Row access policy** | *Which rows can this role see?* | `RAP_PROGRAM_AREA` + mapping table |

> ⚠️ **Review before running.** The cells below create roles and attach policies to `BP_DEMO.GOV.GRANTEE_DIRECTORY`. Undo statements are at the end of `bp_demo/07_governance.sql`.

## 4.1 Classification: find the PII automatically
""")

sql("classify", """
-- Detect sensitive columns (auto_tag = false: report only, apply nothing)
CALL SYSTEM$CLASSIFY('BP_DEMO.GOV.GRANTEE_DIRECTORY', {'auto_tag': false})
""")

sql("classify_readable", """
SELECT f.key AS column_name,
       f.value:recommendation:semantic_category::STRING AS semantic_category,
       f.value:recommendation:privacy_category::STRING  AS privacy_category,
       f.value:recommendation:confidence::STRING        AS confidence
FROM TABLE(RESULT_SCAN(LAST_QUERY_ID())) r,
     LATERAL FLATTEN(INPUT => r.$1:classification_result) f
WHERE semantic_category IS NOT NULL
ORDER BY privacy_category, column_name
""")

md("""
👉 *Do:* the UI version is **Catalog → Database Explorer → GRANTEE_DIRECTORY → … → Classify**, or **Governance & Security → Trust Center / Data Classification** for automatic classification across the whole account.

## 4.2 Roles: who can access what
""")

sql("roles", """
CREATE ROLE IF NOT EXISTS BP_ANALYST           COMMENT = 'Grants analytics: all program areas, PII masked';
CREATE ROLE IF NOT EXISTS BP_PO_PUBLIC_HEALTH  COMMENT = 'Program officers - Public Health portfolio only';
CREATE ROLE IF NOT EXISTS BP_PO_ENVIRONMENT    COMMENT = 'Program officers - Environment portfolio only';
CREATE ROLE IF NOT EXISTS BP_GRANTS_COMPLIANCE COMMENT = 'Grants compliance: all areas, full PII';
GRANT ROLE BP_ANALYST, BP_PO_PUBLIC_HEALTH, BP_PO_ENVIRONMENT, BP_GRANTS_COMPLIANCE TO ROLE SYSADMIN;
""")

sql("role_grants", """
GRANT USAGE ON WAREHOUSE BP_DEMO_WH TO ROLE BP_ANALYST;
GRANT USAGE ON WAREHOUSE BP_DEMO_WH TO ROLE BP_PO_PUBLIC_HEALTH;
GRANT USAGE ON WAREHOUSE BP_DEMO_WH TO ROLE BP_PO_ENVIRONMENT;
GRANT USAGE ON WAREHOUSE BP_DEMO_WH TO ROLE BP_GRANTS_COMPLIANCE;
GRANT USAGE ON DATABASE BP_DEMO TO ROLE BP_ANALYST;
GRANT USAGE ON DATABASE BP_DEMO TO ROLE BP_PO_PUBLIC_HEALTH;
GRANT USAGE ON DATABASE BP_DEMO TO ROLE BP_PO_ENVIRONMENT;
GRANT USAGE ON DATABASE BP_DEMO TO ROLE BP_GRANTS_COMPLIANCE;
GRANT USAGE ON SCHEMA BP_DEMO.GOV TO ROLE BP_ANALYST;
GRANT USAGE ON SCHEMA BP_DEMO.GOV TO ROLE BP_PO_PUBLIC_HEALTH;
GRANT USAGE ON SCHEMA BP_DEMO.GOV TO ROLE BP_PO_ENVIRONMENT;
GRANT USAGE ON SCHEMA BP_DEMO.GOV TO ROLE BP_GRANTS_COMPLIANCE;
GRANT SELECT ON TABLE BP_DEMO.GOV.GRANTEE_DIRECTORY TO ROLE BP_ANALYST;
GRANT SELECT ON TABLE BP_DEMO.GOV.GRANTEE_DIRECTORY TO ROLE BP_PO_PUBLIC_HEALTH;
GRANT SELECT ON TABLE BP_DEMO.GOV.GRANTEE_DIRECTORY TO ROLE BP_PO_ENVIRONMENT;
GRANT SELECT ON TABLE BP_DEMO.GOV.GRANTEE_DIRECTORY TO ROLE BP_GRANTS_COMPLIANCE;
-- let the presenter use the Snowsight role picker
SET me = CURRENT_USER();
GRANT ROLE BP_ANALYST TO USER IDENTIFIER($me);
GRANT ROLE BP_PO_PUBLIC_HEALTH TO USER IDENTIFIER($me);
GRANT ROLE BP_PO_ENVIRONMENT TO USER IDENTIFIER($me);
GRANT ROLE BP_GRANTS_COMPLIANCE TO USER IDENTIFIER($me);
""")

sql("show_grants", """
SHOW GRANTS TO ROLE BP_PO_PUBLIC_HEALTH
""")

md("""
## 4.3 Masking policies: protect columns
""")

sql("masking", """
CREATE OR REPLACE MASKING POLICY BP_DEMO.GOV.MASK_PII_STRING AS (val STRING) RETURNS STRING ->
  CASE WHEN CURRENT_ROLE() IN ('ACCOUNTADMIN', 'BP_GRANTS_COMPLIANCE') THEN val ELSE '*** MASKED ***' END;

CREATE OR REPLACE MASKING POLICY BP_DEMO.GOV.MASK_EMAIL AS (val STRING) RETURNS STRING ->
  CASE WHEN CURRENT_ROLE() IN ('ACCOUNTADMIN', 'BP_GRANTS_COMPLIANCE') THEN val
       ELSE REGEXP_REPLACE(val, '^[^@]+', '*****') END;           -- keep the domain

CREATE OR REPLACE MASKING POLICY BP_DEMO.GOV.MASK_TAX_ID AS (val STRING) RETURNS STRING ->
  CASE WHEN CURRENT_ROLE() IN ('ACCOUNTADMIN', 'BP_GRANTS_COMPLIANCE') THEN val
       ELSE 'XX-XXX' || RIGHT(val, 4) END;                         -- last 4 only

ALTER TABLE BP_DEMO.GOV.GRANTEE_DIRECTORY MODIFY
  COLUMN contact_name  SET MASKING POLICY BP_DEMO.GOV.MASK_PII_STRING,
  COLUMN contact_phone SET MASKING POLICY BP_DEMO.GOV.MASK_PII_STRING,
  COLUMN contact_email SET MASKING POLICY BP_DEMO.GOV.MASK_EMAIL,
  COLUMN tax_id        SET MASKING POLICY BP_DEMO.GOV.MASK_TAX_ID;
""")

md("""
## 4.4 Row access policy: program officers see only their portfolio
The **mapping table** is owned by the business. Granting a new officer access to *Education* is an INSERT, not a code change.
""")

sql("row_access", """
CREATE OR REPLACE TABLE BP_DEMO.GOV.PROGRAM_AREA_ACCESS (role_name STRING, program_area STRING);
INSERT INTO BP_DEMO.GOV.PROGRAM_AREA_ACCESS VALUES
  ('BP_PO_PUBLIC_HEALTH', 'Public Health'),
  ('BP_PO_ENVIRONMENT',   'Environment');

CREATE OR REPLACE ROW ACCESS POLICY BP_DEMO.GOV.RAP_PROGRAM_AREA AS (area STRING) RETURNS BOOLEAN ->
  CURRENT_ROLE() IN ('ACCOUNTADMIN', 'BP_ANALYST', 'BP_GRANTS_COMPLIANCE')
  OR EXISTS (SELECT 1 FROM BP_DEMO.GOV.PROGRAM_AREA_ACCESS m
             WHERE m.role_name = CURRENT_ROLE() AND m.program_area = area);

ALTER TABLE BP_DEMO.GOV.GRANTEE_DIRECTORY ADD ROW ACCESS POLICY BP_DEMO.GOV.RAP_PROGRAM_AREA ON (program_area);
""")

md("""
## 4.5 Prove it: the same query, four roles
`EXECUTE USING POLICY_CONTEXT` simulates a role without switching. 👉 *Do (more visual):* switch role in the bottom-left picker to **BP_PO_PUBLIC_HEALTH** and run `SELECT * FROM BP_DEMO.GOV.GRANTEE_DIRECTORY` in a worksheet.
""")

sql("as_compliance", """
EXECUTE USING POLICY_CONTEXT(CURRENT_ROLE => 'BP_GRANTS_COMPLIANCE') AS
SELECT program_area, organization_name, contact_name, contact_email, tax_id
FROM BP_DEMO.GOV.GRANTEE_DIRECTORY ORDER BY program_area LIMIT 8
""")

sql("as_analyst", """
EXECUTE USING POLICY_CONTEXT(CURRENT_ROLE => 'BP_ANALYST') AS
SELECT program_area, organization_name, contact_name, contact_email, tax_id
FROM BP_DEMO.GOV.GRANTEE_DIRECTORY ORDER BY program_area LIMIT 8
""")

sql("as_po_health", """
EXECUTE USING POLICY_CONTEXT(CURRENT_ROLE => 'BP_PO_PUBLIC_HEALTH') AS
SELECT program_area, organization_name, contact_name, contact_email, tax_id
FROM BP_DEMO.GOV.GRANTEE_DIRECTORY ORDER BY program_area LIMIT 8
""")

sql("rows_by_role", """
-- Row counts per role, side by side
EXECUTE USING POLICY_CONTEXT(CURRENT_ROLE => 'BP_PO_ENVIRONMENT') AS
SELECT 'BP_PO_ENVIRONMENT' AS role, program_area, COUNT(*) AS visible_rows
FROM BP_DEMO.GOV.GRANTEE_DIRECTORY GROUP BY ALL
""")

sql("policy_refs", """
-- Governance audit: which policies protect this table?
SELECT policy_name, policy_kind, ref_column_name, policy_status
FROM TABLE(BP_DEMO.INFORMATION_SCHEMA.POLICY_REFERENCES(REF_ENTITY_NAME => 'BP_DEMO.GOV.GRANTEE_DIRECTORY', REF_ENTITY_DOMAIN => 'table'))
""")

md("""
The rule lives with the data. Tableau, the AI agent, a notebook or an Excel connection all get the same answer for the same role. Policies are **inherited by clones** too, so the dev copy is protected automatically.

**Going further:** **tag-based masking** (attach a policy to a `PII` tag, so every classified column is protected automatically), **access history** (who read what), and **Trust Center** security posture.
""")

# =====================================================================  V5
md("""
---
# Vignette 5 — Apps & Collaboration: enrich with the Snowflake Marketplace

The **Marketplace** offers thousands of live datasets, apps and AI models from third parties. Data is **shared, not copied**: no ETL and always current. BP programs are global, so let's add country context.

👉 *Do:* **Catalog → Marketplace** → search **"Snowflake Public Data (Free)"** → *Get*. (Already installed in this account as `SNOWFLAKE_PUBLIC_DATA_FREE`.) It includes World Bank, WHO, IMF, Our World in Data and more.

**Question:** *Are our Road Safety and Clean Air dollars going where the need is greatest?*
""")

sql("mkt_join", """
WITH wb AS (
  SELECT g.geo_name AS country, t.variable, t.value
  FROM SNOWFLAKE_PUBLIC_DATA_FREE.PUBLIC_DATA_FREE.WORLD_BANK_TIMESERIES t
  JOIN SNOWFLAKE_PUBLIC_DATA_FREE.PUBLIC_DATA_FREE.GEOGRAPHY_INDEX g
    ON g.geo_id = t.geo_id AND g.level = 'Country'
  WHERE t.variable IN ('WDI_SH.STA.TRAF.P5',      -- road traffic deaths per 100k
                       'ESG_EN.ATM.PM25.MC.M3')   -- PM2.5 air pollution
  QUALIFY ROW_NUMBER() OVER (PARTITION BY g.geo_name, t.variable ORDER BY t.date DESC) = 1)
SELECT p.country,
       COUNT(DISTINCT p.grant_id)                                                    AS grants,
       ROUND(SUM(IFF(p.initiative = 'Road Safety', p.requested_amount, 0)) / 1e6, 2)  AS road_safety_musd,
       ROUND(SUM(IFF(p.initiative = 'Clean Air Cities', p.requested_amount, 0)) / 1e6, 2) AS clean_air_musd,
       MAX(IFF(wb.variable = 'WDI_SH.STA.TRAF.P5', wb.value, NULL))                   AS road_deaths_per_100k,
       ROUND(MAX(IFF(wb.variable = 'ESG_EN.ATM.PM25.MC.M3', wb.value, NULL)), 1)      AS pm25_ug_m3
FROM BP_DEMO.CURATED.DT_GRANT_PIPELINE p
LEFT JOIN wb ON wb.country = p.country
GROUP BY 1
ORDER BY road_deaths_per_100k DESC NULLS LAST
""")

py("""
import altair as alt
alt.renderers.enable("mimetype")
df = mkt_join.to_pandas()      # 23 countries
alt.Chart(df).mark_circle(opacity=0.8).encode(
    x=alt.X("ROAD_DEATHS_PER_100K:Q", title="Road traffic deaths per 100k (World Bank)"),
    y=alt.Y("ROAD_SAFETY_MUSD:Q", title="Road Safety requested ($M)"),
    size=alt.Size("GRANTS:Q", title="All grants"),
    tooltip=["COUNTRY", "GRANTS", "ROAD_SAFETY_MUSD", "ROAD_DEATHS_PER_100K", "PM25_UG_M3"],
).properties(title="Road Safety funding vs. need", width=600, height=320)
""")

md("""
**Collaboration beyond the Marketplace**
- **Secure data sharing:** share live, governed grant-outcome data with co-funders or grantees, with no file transfers:
  ```sql
  CREATE SHARE BP_COFUNDER_OUTCOMES;
  GRANT USAGE ON DATABASE BP_DEMO TO SHARE BP_COFUNDER_OUTCOMES;  -- + schema/view grants
  ALTER SHARE BP_COFUNDER_OUTCOMES ADD ACCOUNTS = <partner_account>;
  ```
- **Data clean rooms:** measure overlap with partner foundations without exposing either party's data.
- **Apps:** Streamlit apps for program staff, and Native Apps from the Marketplace, all running inside Snowflake.
""")

# =====================================================================  WRAP: COST
md("""
---
# Wrap-up — Cost Management in Snowsight

👉 *Do:* **Admin → Cost Management**
| Tab | Shows |
|---|---|
| **Account Overview** | Spend trend and top warehouses / services |
| **Consumption** | Credits by warehouse, service (AI, Snowpipe, Search, Dynamic Tables), tag, user; filter to `BP_DEMO_WH` |
| **Budgets** | Monthly spending limits with alerts, including serverless and AI |
| **Resource Monitors** | Hard caps that notify or suspend warehouses |

The same data is in SQL (`SNOWFLAKE.ACCOUNT_USAGE`, refreshed with up to ~3 hours' latency):
""")

sql("cost_wh", """
SELECT DATE_TRUNC('hour', start_time) AS hour, ROUND(SUM(credits_used), 4) AS credits
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
WHERE warehouse_name = 'BP_DEMO_WH' AND start_time >= DATEADD('day', -7, CURRENT_TIMESTAMP())
GROUP BY 1 ORDER BY 1 DESC
""")

sql("cost_services", """
-- Account-wide credits by service type, last 7 days (includes other workloads in this account)
SELECT service_type, ROUND(SUM(credits_billed), 3) AS total_credits_billed
FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY
WHERE usage_date >= DATEADD('day', -7, CURRENT_DATE())
GROUP BY 1 HAVING total_credits_billed > 0 ORDER BY 2 DESC
""")

sql("cost_pipe", """
SELECT pipe_name, ROUND(SUM(credits_used), 4) AS credits, SUM(files_inserted) AS files
FROM SNOWFLAKE.ACCOUNT_USAGE.PIPE_USAGE_HISTORY
WHERE start_time >= DATEADD('day', -7, CURRENT_TIMESTAMP()) AND pipe_name IN ('PIPE_FLUXX', 'PIPE_SFDC')
GROUP BY 1
""")

md("""
### Cost levers
| Lever | Effect |
|---|---|
| AUTO_SUSPEND 60s, right-size, warehouse per workload | No idle spend; clear chargeback |
| Result cache | Repeat queries within 24h are free |
| `TARGET_LAG` / `DOWNSTREAM` | Refresh only as often as the SLA needs |
| Incremental DTs for AI | AI cost only on new or changed rows |
| Budgets + resource monitors (Appendix D) | No surprises |

### Recap: what we covered
| Vignette | Fundamentals | Your outcome |
|---|---|---|
| 1 | Warehouses, cache, files + COPY INTO, clone, Time Travel | Load exports, elastic and recoverable |
| 2 | JSON, Snowpipe, Dynamic Tables | Stored procs retired; 5-min freshness |
| 3 | Cortex AI end to end | Self-service answers replace static reports |
| 4 | Roles, classification, masking, row access | Portfolio-level security; PII protected |
| 5 | Marketplace, sharing | Global context; partner collaboration |

**Next:** the hands-on **Tasty Bytes Zero to Snowflake** lab repeats every vignette step by step.

🧹 After the session, run section A of `bp_demo/99_reset.sql`.
""")

# =====================================================================  APPENDIX A — API
md("""
---
# Appendix A — Pulling directly from the Fluxx API every 3–10 minutes

```
 Task (every 5 min) ─► Python stored proc ─► HTTPS (External Access Integration) ─► Fluxx REST API
                                   └─► append JSON to RAW.RAW_FLUXX ─► Dynamic Tables pick it up (unchanged)
```
1. **Network rule**: allow-list the Fluxx host (egress is off by default). 2. **Secret**: OAuth client credentials, encrypted. 3. **External access integration**: binds the two. 4. **Python procedure**: token, records changed since the high-water mark, pagination, append. 5. **Task**: schedule.

> ⚠️ **Template, not executed.** Confirm your Fluxx instance URL, endpoint/model names, filter syntax and pagination in your Fluxx API documentation. Integrations require ACCOUNTADMIN (or a delegated role).

```sql
CREATE OR REPLACE NETWORK RULE BP_DEMO.RAW.FLUXX_EGRESS
  MODE = EGRESS TYPE = HOST_PORT VALUE_LIST = ('yourorg.fluxx.io:443');

CREATE OR REPLACE SECRET BP_DEMO.RAW.FLUXX_OAUTH
  TYPE = GENERIC_STRING SECRET_STRING = '{"client_id":"<id>","client_secret":"<secret>"}';

CREATE OR REPLACE EXTERNAL ACCESS INTEGRATION FLUXX_API_EAI
  ALLOWED_NETWORK_RULES = (BP_DEMO.RAW.FLUXX_EGRESS)
  ALLOWED_AUTHENTICATION_SECRETS = (BP_DEMO.RAW.FLUXX_OAUTH)
  ENABLED = TRUE;

CREATE OR REPLACE PROCEDURE BP_DEMO.RAW.PULL_FLUXX_API()
RETURNS VARIANT LANGUAGE PYTHON RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python', 'requests')
EXTERNAL_ACCESS_INTEGRATIONS = (FLUXX_API_EAI)
SECRETS = ('cred' = BP_DEMO.RAW.FLUXX_OAUTH)
HANDLER = 'run'
AS $$
import _snowflake, json, requests
BASE = "https://yourorg.fluxx.io"                         # <-- your instance

def run(session):
    cred = json.loads(_snowflake.get_generic_secret_string('cred'))
    tok = requests.post(f"{BASE}/oauth/token", data={
        "grant_type": "client_credentials",
        "client_id": cred["client_id"], "client_secret": cred["client_secret"]}, timeout=30).json()["access_token"]

    # high-water mark: only records modified since the last successful pull
    since = session.sql("SELECT COALESCE(MAX(r.value:last_modified::string), '1900-01-01') "
                        "FROM BP_DEMO.RAW.RAW_FLUXX t, LATERAL FLATTEN(t.payload:records) r").collect()[0][0]
    records, page = [], 1
    while True:
        resp = requests.get(f"{BASE}/api/rest/v2/grant_request",      # <-- confirm model/endpoint
                            headers={"Authorization": f"Bearer {tok}"},
                            params={"page": page, "per_page": 200,
                                    "filter": json.dumps({"updated_at": {"gt": since}})},  # <-- confirm filter syntax
                            timeout=60)
        resp.raise_for_status()
        batch = resp.json().get("records", {}).get("grant_request", [])
        if not batch: break
        records += batch; page += 1
    if records:
        session.create_dataframe([[json.dumps({"records": records})]], schema=["P"]) \\
               .select_expr("PARSE_JSON(P) AS PAYLOAD", "'api_pull' AS FILE_NAME", "CURRENT_TIMESTAMP() AS LOADED_AT") \\
               .write.mode("append").save_as_table("BP_DEMO.RAW.RAW_FLUXX", column_order="name")
    return {"pulled": len(records), "since": since}
$$;

CREATE OR REPLACE TASK BP_DEMO.RAW.T_PULL_FLUXX
  SCHEDULE = '5 MINUTE' USER_TASK_MANAGED_INITIAL_WAREHOUSE_SIZE = 'XSMALL'   -- serverless task
AS CALL BP_DEMO.RAW.PULL_FLUXX_API();
-- ALTER TASK BP_DEMO.RAW.T_PULL_FLUXX RESUME;
```
**Design for:** rate limits (back off on HTTP 429), Fluxx field names (adjust `DT_GRANTS_FLAT`), deletes, and failure alerts.
**Salesforce:** prefer managed connectors (e.g. **Openflow**) or Salesforce Data Cloud **zero-copy** sharing over custom code. Confirm availability for your org.
""")

# =====================================================================  APPENDIX B
md("""
---
# Appendix B — Snowpipe vs. triggered COPY INTO

| | **Snowpipe** | **COPY INTO run by a Task** |
|---|---|---|
| Compute | Serverless | Your warehouse (per second, 60s minimum) |
| Trigger | Cloud event (external stage) / REST API / `ALTER PIPE … REFRESH` | Schedule, or **triggered** by a stream on the stage's directory table |
| Latency | Seconds to ~1 min | Interval, or near real time if triggered |
| Best for | Many small files, continuously, at scale | **Modest volumes**, batch drops, new teams |
| Error handling | Asynchronous: `COPY_HISTORY`, `VALIDATE_PIPE_LOAD`, error notifications | **Synchronous**: per-file results immediately; `VALIDATION_MODE`, `ON_ERROR`, procedure logic can `RAISE`, so the task fails and alerts |
| Load history | 14 days | 64 days |

**Recommendation for low file volumes:** a triggered COPY INTO is simple, easy to debug and cheap. Move to Snowpipe auto-ingest when volume or latency needs it.
""")

sql("trig_setup", """
CREATE TABLE IF NOT EXISTS BP_DEMO.RAW.RAW_FLUXX_COPY LIKE BP_DEMO.RAW.RAW_FLUXX;
CREATE TABLE IF NOT EXISTS BP_DEMO.RAW.LANDING_FILE_LOG (relative_path STRING, size NUMBER, logged_at TIMESTAMP_LTZ);
CREATE OR REPLACE STREAM BP_DEMO.RAW.LANDING_FILES_STREAM ON STAGE BP_DEMO.RAW.LANDING_STAGE;

CREATE OR REPLACE TASK BP_DEMO.RAW.T_COPY_FLUXX
  WAREHOUSE = BP_DEMO_WH
  WHEN SYSTEM$STREAM_HAS_DATA('BP_DEMO.RAW.LANDING_FILES_STREAM')      -- triggered: no schedule
AS
BEGIN
  COPY INTO BP_DEMO.RAW.RAW_FLUXX_COPY (payload, file_name, loaded_at)
    FROM (SELECT $1, METADATA$FILENAME, CURRENT_TIMESTAMP() FROM @BP_DEMO.RAW.LANDING_STAGE/fluxx/)
    FILE_FORMAT = (FORMAT_NAME = 'BP_DEMO.RAW.FF_JSON')
    ON_ERROR = 'SKIP_FILE';
  INSERT INTO BP_DEMO.RAW.LANDING_FILE_LOG (relative_path, size, logged_at)   -- consumes the stream
    SELECT relative_path, size, CURRENT_TIMESTAMP() FROM BP_DEMO.RAW.LANDING_FILES_STREAM
    WHERE METADATA$ACTION = 'INSERT';
END;
-- ALTER TASK BP_DEMO.RAW.T_COPY_FLUXX RESUME;
""")

# =====================================================================  APPENDIX C
md("""
---
# Appendix C — Error handling: a corrupt file
""")

py("""
import io
from snowflake.snowpark.context import get_active_session
session = get_active_session()
bad = b'{"records": [{"grant_id": "FLX-BAD-0001", "organization_name": "Truncated Export Org", "requested_amount": 50000'
session.file.put_stream(io.BytesIO(bad), "@BP_DEMO.RAW.LANDING_STAGE/badfiles/fluxx_corrupt.json", auto_compress=False, overwrite=True)
print("landed a corrupt file at @LANDING_STAGE/badfiles/")
""")

sql("validate_first", """
-- 1) DRY RUN: returns the error, loads nothing (VALIDATION_MODE needs a plain COPY, so use a scratch table)
CREATE TEMPORARY TABLE IF NOT EXISTS BP_DEMO.RAW._VALIDATE_JSON (payload VARIANT);
COPY INTO BP_DEMO.RAW._VALIDATE_JSON FROM @BP_DEMO.RAW.LANDING_STAGE/badfiles/
  FILE_FORMAT = (FORMAT_NAME = 'BP_DEMO.RAW.FF_JSON') VALIDATION_MODE = RETURN_ERRORS
""")

sql("skip_file", """
-- 2) SKIP_FILE: the bad file is reported as LOAD_FAILED; the job carries on
COPY INTO BP_DEMO.RAW.RAW_FLUXX_COPY (payload, file_name, loaded_at)
  FROM (SELECT $1, METADATA$FILENAME, CURRENT_TIMESTAMP() FROM @BP_DEMO.RAW.LANDING_STAGE/badfiles/)
  FILE_FORMAT = (FORMAT_NAME = 'BP_DEMO.RAW.FF_JSON') ON_ERROR = 'SKIP_FILE'
""")

sql("error_audit", """
-- 3) AUDIT trail
SELECT file_name, status, row_count, error_count, first_error_message, last_load_time
FROM TABLE(BP_DEMO.INFORMATION_SCHEMA.COPY_HISTORY(TABLE_NAME => 'BP_DEMO.RAW.RAW_FLUXX_COPY', START_TIME => DATEADD('hour', -1, CURRENT_TIMESTAMP())))
ORDER BY last_load_time DESC
""")

sql("cleanup_bad", """
REMOVE @BP_DEMO.RAW.LANDING_STAGE/badfiles/
""")

md("""
**Production patterns:** quarantine rejected files; wrap COPY in a procedure that `RAISE`s so the task fails and an **alert** fires (email, Slack or Teams via a notification integration); use `VALIDATE_PIPE_LOAD` for Snowpipe; add **Data Metric Functions** (nulls, freshness) on `DT_GRANT_PIPELINE`.

---
# Appendix D — Cost guardrails
```sql
CREATE OR REPLACE RESOURCE MONITOR BP_DEMO_RM WITH CREDIT_QUOTA = 20 FREQUENCY = MONTHLY START_TIMESTAMP = IMMEDIATELY
  TRIGGERS ON 80 PERCENT DO NOTIFY ON 100 PERCENT DO SUSPEND;
ALTER WAREHOUSE BP_DEMO_WH SET RESOURCE_MONITOR = BP_DEMO_RM;
ALTER WAREHOUSE BP_DEMO_WH SET STATEMENT_TIMEOUT_IN_SECONDS = 1800;
```
Resource monitors cover warehouses. Use **Budgets** (Admin → Cost Management) for serverless and AI spend, and tag objects (`cost_center = 'grants'`) for chargeback.
""")

nb = {"cells": cells,
      "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                   "language_info": {"codemirror_mode": {"name": "ipython", "version": 3}, "file_extension": ".py",
                                     "mimetype": "text/x-python", "name": "python", "nbconvert_exporter": "python",
                                     "pygments_lexer": "ipython3", "version": "3.11.0"}},
      "nbformat": 4, "nbformat_minor": 5}
out = "/Users/hbarile/Dev/dev/profiles/hbtraining/bp_demo/BP_Zero_to_Snowflake_Demo_v2.ipynb"
json.dump(nb, open(out, "w"), indent=1)
print(out, len(cells), "cells")

"""Build BP_Demo_v3_40min.ipynb: a 40-minute tell / show / tell cut of the v2 notebook.

Code cells are copied from BP_Zero_to_Snowflake_Demo_v2.ipynb by cell id (already tested);
the markdown is new and written for an audience that is new to Snowflake.
"""
import copy, json, os, uuid

HERE = os.path.dirname(os.path.abspath(__file__))
NB_DIR = os.path.dirname(HERE) if os.path.basename(HERE) == "tmp" else HERE
V2 = json.load(open(os.path.join(NB_DIR, "BP_Zero_to_Snowflake_Demo_v2.ipynb")))
V2_BY_ID = {c["id"][:8]: c for c in V2["cells"]}

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
def reuse(v2_id):
    c = copy.deepcopy(V2_BY_ID[v2_id]); c["id"] = _id(); c["outputs"] = []; c["execution_count"] = None
    cells.append(c)

# ===================================================================== WELCOME
md("""
# Snowflake for Bloomberg Philanthropies — a 40-minute tour

**Your situation today:** Fluxx grants and Salesforce donors land as file exports. An on-prem SQL Server runs 10 years of stored procedures and SQL Agent jobs, and the results feed 500+ static Tableau reports for about 8,000 people.

**What we'll show:** the same data story on Snowflake, one building block at a time.

| # | Building block | The question it answers for you | ⏱ |
|---|---|---|---|
| 1 | Load your files | *Can we get our exports in?* | 5 |
| 2 | Pay only for what you use | *How fast is it, and what does compute cost?* | 5 |
| 3 | Safety nets | *What if someone makes a mistake?* | 4 |
| 4 | Pipelines without stored procedures | *Can we retire SQL Agent and meet a 10-minute SLA?* | 7 |
| 5 | AI on your data | *Can people ask questions instead of hunting through 500 reports?* | 7 |
| 6 | Governance | *Can a program officer see only their own portfolio, with PII protected?* | 5 |
| 7 | Outside data | *Can we add World Bank / WHO context without ETL?* | 3 |
| 8 | Cost and next steps | *How do we keep spend under control?* | 2 |

Each section follows the same pattern: **what it is → see it run → what it means for you.**

> Organization, donor and contact names are fictional. Program areas reflect BP's focus areas.
""")

md("""
### Snowflake in three ideas
1. **Storage and compute are separate.** Your data sits in one place. Compute (a *warehouse*) is switched on only while it works, and you pay by the second.
2. **A warehouse is just compute.** Start it, stop it or resize it in seconds. Different teams can each have their own without copying data.
3. **Fully managed.** No servers, patching, index tuning or backups to run.

### Snowflake words → what you already know
| Snowflake | Think of it as |
|---|---|
| **Warehouse** | The CPU of your SQL Server, but you can resize it in seconds and it turns off when idle |
| **Database / schema / table** | Same as SQL Server |
| **Stage** | A folder that holds files waiting to be loaded |
| **Snowpipe** | An automatic file loader |
| **Dynamic Table** | A stored procedure and its SQL Agent job, combined into one SQL statement |
| **Role** | A security group |
| **Snowsight** | This web interface |
""")

reuse("ed8aaf74")   # whoami

# ===================================================================== 1 LOAD
md("""
---
# 1. Load your files
**What it is:** files go into a **stage** (a folder), and `COPY INTO` loads them into a table using a warehouse. Snowflake remembers which files it already loaded, so re-running never creates duplicates.

**Today:** a grantee contact directory, exported as one CSV per region.
""")
reuse("ba8be6ea")   # diagram: stage -> COPY INTO on a warehouse -> table

sql("list_files", """
-- What files are waiting in the folder?
LIST @BP_DEMO.RAW.SAMPLE_FILES
""")

sql("create_and_copy", """
-- Create the table by reading the column names from the files, then load them
CREATE OR REPLACE TABLE BP_DEMO.GOV.GRANTEE_DIRECTORY USING TEMPLATE (
  SELECT ARRAY_AGG(OBJECT_CONSTRUCT(*)) WITHIN GROUP (ORDER BY order_id)
  FROM TABLE(INFER_SCHEMA(LOCATION => '@BP_DEMO.RAW.SAMPLE_FILES', FILE_FORMAT => 'BP_DEMO.RAW.FF_CSV')));

COPY INTO BP_DEMO.GOV.GRANTEE_DIRECTORY
  FROM @BP_DEMO.RAW.SAMPLE_FILES
  FILE_FORMAT = (FORMAT_NAME = 'BP_DEMO.RAW.FF_CSV')
  MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE
  ON_ERROR = 'ABORT_STATEMENT';
""")

sql("grantees", """
-- The data is ready to query straight away
SELECT region, COUNT(*) AS grantees, ROUND(SUM(annual_budget_usd)/1e6, 1) AS combined_budget_musd
FROM BP_DEMO.GOV.GRANTEE_DIRECTORY GROUP BY 1 ORDER BY 2 DESC
""")

md("""
> **What this means for you:** Fluxx dumps, finance spreadsheets and partner files load with a few lines of SQL. You don't need to define the table in advance or run an ETL server.

👉 *Do:* **Catalog → Database Explorer → BP_DEMO → GOV → GRANTEE_DIRECTORY → Data Preview**.
""")

# ===================================================================== 2 COMPUTE
md("""
---
# 2. Pay only for what you use
**What it is:** a warehouse is billed **per second** while it runs, and turns itself off when idle. Each size up doubles the compute and the price per hour, so a big job finishes about twice as fast **for about the same cost**.

| Size | XS | S | M | L |
|---|---|---|---|---|
| Credits / hour | 1 | 2 | 4 | 8 |

**Today:** one analytics query over Snowflake's shared sample data, **28.8 billion sales rows**, scanning about 100 GB. We run it on the smallest size, then on one 4× bigger.
""")

reuse("a23e9e79")   # run_id for query tags

sql("query_xs", """
-- Run 1: the smallest warehouse (XS). Result caching is switched off so we measure real work.
ALTER SESSION SET QUERY_TAG = 'bp_demo:{{run_id}}:query:xs';
ALTER SESSION SET USE_CACHED_RESULT = FALSE;
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
-- Run 2: resize to MEDIUM (4x) in one line, with no downtime, and run the same query
ALTER SESSION SET QUERY_TAG = 'bp_demo:{{run_id}}:query:medium';
ALTER WAREHOUSE BP_DEMO_WH SET WAREHOUSE_SIZE = 'MEDIUM';
SELECT i.i_category, COUNT(*) AS line_items, ROUND(SUM(ss.ss_net_paid)/1e6, 1) AS net_paid_musd,
       COUNT(DISTINCT ss.ss_customer_sk) AS customers
FROM TPCDS_10TB.TPCDS_SF10TCL.STORE_SALES ss
JOIN TPCDS_10TB.TPCDS_SF10TCL.DATE_DIM d ON ss.ss_sold_date_sk = d.d_date_sk
JOIN TPCDS_10TB.TPCDS_SF10TCL.ITEM i ON ss.ss_item_sk = i.i_item_sk
WHERE d.d_year = 2001 AND d.d_moy BETWEEN 1 AND 4
GROUP BY 1 ORDER BY 3 DESC
""")

sql("query_compare", """
-- Size back down, then compare the two runs: time and estimated credits
ALTER WAREHOUSE BP_DEMO_WH SET WAREHOUSE_SIZE = 'XSMALL';
ALTER SESSION SET USE_CACHED_RESULT = TRUE;
ALTER SESSION UNSET QUERY_TAG;
SELECT warehouse_size, ROUND(total_elapsed_time / 1000, 1) AS seconds,
       DECODE(warehouse_size, 'X-Small', 1, 'Small', 2, 'Medium', 4, 'Large', 8) AS credits_per_hour,
       ROUND(seconds * credits_per_hour / 3600, 4) AS est_credits
FROM TABLE(BP_DEMO.INFORMATION_SCHEMA.QUERY_HISTORY(RESULT_LIMIT => 200))
WHERE query_tag LIKE 'bp_demo:{{run_id}}:query:%' AND query_type = 'SELECT' AND execution_status = 'SUCCESS'
ORDER BY start_time DESC LIMIT 2
""")

md("""
**Result:** about 4× faster for roughly the same credits, and it's already back to XS.

**The second run is free:** Snowflake keeps every query result for 24 hours. If the same query runs again and the data hasn't changed, the answer comes back instantly with **no compute**. That's ideal when 8,000 people open the same dashboard at 9am.
""")

sql("cache_run", """
-- The exact same query again: answered from the result cache in well under a second
ALTER SESSION SET USE_CACHED_RESULT = TRUE;
SELECT i.i_category, COUNT(*) AS line_items, ROUND(SUM(ss.ss_net_paid)/1e6, 1) AS net_paid_musd,
       COUNT(DISTINCT ss.ss_customer_sk) AS customers
FROM TPCDS_10TB.TPCDS_SF10TCL.STORE_SALES ss
JOIN TPCDS_10TB.TPCDS_SF10TCL.DATE_DIM d ON ss.ss_sold_date_sk = d.d_date_sk
JOIN TPCDS_10TB.TPCDS_SF10TCL.ITEM i ON ss.ss_item_sk = i.i_item_sk
WHERE d.d_year = 2001 AND d.d_moy BETWEEN 1 AND 4
GROUP BY 1 ORDER BY 3 DESC
""")

md("""
> **What this means for you:** no capacity planning. Size compute for the job, give each team its own warehouse, and stop paying the moment it's idle.

👉 *Do:* **Monitoring → Query History** → click the newest query → *Query Profile* shows **QUERY RESULT REUSE**.
""")

# ===================================================================== 3 SAFETY
md("""
---
# 3. Safety nets: cloning and Time Travel
**What it is:**
- **Clone:** an instant full copy of a table, schema or whole database. It costs no extra storage until you change something, which makes it ideal for dev and test.
- **Time Travel:** Snowflake keeps the history of every change, so you can query the past and put it back.

**Today:** clone the directory, wipe every budget by mistake, then undo it.
""")

sql("clone", """
-- An instant dev copy
CREATE OR REPLACE TABLE BP_DEMO.GOV.GRANTEE_DIRECTORY_DEV CLONE BP_DEMO.GOV.GRANTEE_DIRECTORY;
SELECT 'prod' AS copy, COUNT(*) AS row_count FROM BP_DEMO.GOV.GRANTEE_DIRECTORY
UNION ALL SELECT 'dev clone', COUNT(*) FROM BP_DEMO.GOV.GRANTEE_DIRECTORY_DEV
""")

sql("oops", """
-- The mistake: an UPDATE with no WHERE clause sets every budget to 0
SET before_oops = CURRENT_TIMESTAMP();
UPDATE BP_DEMO.GOV.GRANTEE_DIRECTORY_DEV SET annual_budget_usd = 0;
SET bad_query_id = LAST_QUERY_ID();
SELECT SUM(annual_budget_usd) AS total_budget_now FROM BP_DEMO.GOV.GRANTEE_DIRECTORY_DEV
""")

sql("travel", """
-- Look at the table as it was just before the mistake, and as it is now
SELECT 'before the mistake' AS version, SUM(annual_budget_usd) AS total_budget
FROM BP_DEMO.GOV.GRANTEE_DIRECTORY_DEV AT (TIMESTAMP => $before_oops)
UNION ALL
SELECT 'now', SUM(annual_budget_usd) FROM BP_DEMO.GOV.GRANTEE_DIRECTORY_DEV
""")

sql("restore", """
-- Put the old version back
INSERT OVERWRITE INTO BP_DEMO.GOV.GRANTEE_DIRECTORY_DEV
  SELECT * FROM BP_DEMO.GOV.GRANTEE_DIRECTORY_DEV BEFORE (STATEMENT => $bad_query_id);
SELECT SUM(annual_budget_usd) AS restored_total FROM BP_DEMO.GOV.GRANTEE_DIRECTORY_DEV
""")

md("""
> **What this means for you:** no restore tickets and no backup tapes. Dropped a table by accident? `UNDROP TABLE` brings it back. History is kept for 1 day by default, and up to 90 days on Enterprise.
""")

# ===================================================================== 4 PIPELINES
md("""
---
# 4. Pipelines without stored procedures
**What it is:**
- **Snowpipe** loads new files automatically as they arrive. It's serverless, so no warehouse is needed.
- Raw JSON is stored as-is. When Fluxx adds a field, nothing breaks.
- A **Dynamic Table** is a SELECT statement plus a freshness target, such as "no more than 5 minutes old". Snowflake handles scheduling, ordering and processing only the rows that changed. **This replaces the stored procedures and SQL Agent jobs.**
""")
reuse("5f1cad4d")   # diagram: Vignette 2 pipeline architecture

sql("landing_before", """
-- BEFORE: how many files are already in the landing folder
LIST @BP_DEMO.RAW.LANDING_STAGE
->> SELECT SPLIT_PART("name", '/', 2) AS folder, COUNT(*) AS files_before
FROM $1 GROUP BY 1 ORDER BY 1
""")

sql("land_files", """
-- Simulate a delivery. GEN_MOCK_FILES is a Snowpark PYTHON stored procedure that writes
-- 2 new JSON files: 1 Fluxx file (5 grant applications) + 1 Salesforce file (5 donor opportunities).
-- (The last argument, 42, is a fixed seed, so every rehearsal delivers the same records.)
SET gen_start = CURRENT_TIMESTAMP();          -- remember when the delivery started
CALL BP_DEMO.RAW.GEN_MOCK_FILES(5, 5, 0.4, 42)
""")

sql("landing_after", """
-- AFTER: only the files that arrived since the delivery started (expect 2: one fluxx, one sfdc)
LIST @BP_DEMO.RAW.LANDING_STAGE
->> SELECT SPLIT_PART("name", '/', 2) AS folder,
       SPLIT_PART("name", '/', -1) AS new_file,
       "size" AS bytes
FROM $1
WHERE TO_TIMESTAMP_NTZ("last_modified", 'DY, DD MON YYYY HH24:MI:SS GMT')
      >= DATEADD('second', -2, CONVERT_TIMEZONE('UTC', $gen_start)::TIMESTAMP_NTZ)
ORDER BY 1
""")

sql("pipe_refresh", """
-- Tell Snowpipe to check the folder (in production this happens automatically when a file arrives).
-- Snowpipe remembers what it already loaded, so only the 2 new files are actually loaded.
ALTER STAGE BP_DEMO.RAW.LANDING_STAGE REFRESH;
ALTER PIPE BP_DEMO.RAW.PIPE_FLUXX REFRESH;
ALTER PIPE BP_DEMO.RAW.PIPE_SFDC  REFRESH
->> SELECT 'Snowpipe is loading the new files in the background' AS status
""")

py(r"""
# Snowpipe loads in the background, usually within seconds. Wait until both new files are loaded (max 2 min).
import time
from snowflake.snowpark.context import get_active_session
session = get_active_session()
# Safety net in case the pipe_refresh cell was skipped: tell Snowpipe about the new files (it never loads a file twice)
for stmt in ("ALTER STAGE BP_DEMO.RAW.LANDING_STAGE REFRESH",
             "ALTER PIPE BP_DEMO.RAW.PIPE_FLUXX REFRESH",
             "ALTER PIPE BP_DEMO.RAW.PIPE_SFDC REFRESH"):
    session.sql(stmt).collect()
for waited in range(0, 125, 5):
    loaded = session.sql(
        "SELECT (SELECT COUNT(*) FROM TABLE(BP_DEMO.INFORMATION_SCHEMA.COPY_HISTORY(TABLE_NAME => 'BP_DEMO.RAW.RAW_FLUXX', START_TIME => $gen_start)))"
        " + (SELECT COUNT(*) FROM TABLE(BP_DEMO.INFORMATION_SCHEMA.COPY_HISTORY(TABLE_NAME => 'BP_DEMO.RAW.RAW_SFDC', START_TIME => $gen_start)))"
    ).collect()[0][0]
    if loaded >= 2:
        break
    time.sleep(5)
print(f"Snowpipe loaded {loaded} new file(s) in about {waited} seconds")
""")

sql("copy_hist", """
-- Proof: the files Snowpipe loaded since the delivery started, and how many rows each held
SELECT table_name, file_name, last_load_time, row_count, status
FROM TABLE(BP_DEMO.INFORMATION_SCHEMA.COPY_HISTORY(TABLE_NAME => 'BP_DEMO.RAW.RAW_FLUXX', START_TIME => $gen_start))
UNION ALL
SELECT table_name, file_name, last_load_time, row_count, status
FROM TABLE(BP_DEMO.INFORMATION_SCHEMA.COPY_HISTORY(TABLE_NAME => 'BP_DEMO.RAW.RAW_SFDC', START_TIME => $gen_start))
ORDER BY table_name
""")

md("""
### Step 1: what the files look like
Fluxx and Salesforce send **JSON**: records nested inside records (a grant with a list of budget lines, a donor with a list of meetings). Snowflake stores it **exactly as it arrived** in a `VARIANT` column. No table design up front, and nothing breaks when Fluxx adds a field.
""")

sql("raw_fluxx", """
-- One Fluxx file, as delivered. Click the PAYLOAD cell to expand it.
SELECT file_name, loaded_at, payload FROM BP_DEMO.RAW.RAW_FLUXX ORDER BY loaded_at DESC LIMIT 1
""")

sql("raw_sfdc", """
-- One Salesforce file, as delivered: opportunities with their engagement history
SELECT file_name, loaded_at, payload FROM BP_DEMO.RAW.RAW_SFDC ORDER BY loaded_at DESC LIMIT 1
""")

md("""
### Step 2: read the JSON with plain SQL
- `payload:records` → go into the JSON, like a folder path.
- `::STRING`, `::NUMBER` → turn the value into a normal column type.
- `FLATTEN` → turn a list into rows (one grant with 6 budget lines becomes 6 rows).
""")

sql("json_paths", """
-- Each grant's budget list becomes one row per budget line
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
### Step 3: why 6 Dynamic Tables?
Each Dynamic Table does **one job** and feeds the next one, like an assembly line. Smaller steps are easier to understand, test and reuse, and Snowflake only re-processes the steps whose input changed.
""")

py(r"""
# Diagram: the 6 Dynamic Tables and how they feed each other (static picture, no queries)
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

fig, ax = plt.subplots(figsize=(14, 6.2))
ax.set_xlim(0, 14); ax.set_ylim(0, 6.6); ax.axis("off")

C_RAW, C_CLEAN, C_AI, C_PUB = "#E8EEF4", "#D6EAF8", "#FDEBD0", "#D5F5E3"

def box(x, y, w, h, title, sub, color, edge="#34495E", bold=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.05,rounding_size=0.15",
                                fc=color, ec=edge, lw=2.2 if bold else 1.2))
    ax.text(x + w / 2, y + h - 0.22, title, ha="center", va="top", fontsize=10.5, weight="bold")
    ax.text(x + w / 2, y + h - 0.62, sub, ha="center", va="top", fontsize=8.6, color="#2C3E50", linespacing=1.3)

def arrow(x1, y1, x2, y2):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=15, lw=1.6, color="#566573"))

for x, t, c in [(1.1, "RAW (Snowpipe)", "#7F8C8D"), (4.25, "CLEAN", "#2E86C1"),
                (7.7, "AI", "#CA6F1E"), (11.6, "PUBLISH", "#1E8449")]:
    ax.text(x, 6.3, t, ha="center", fontsize=10.5, weight="bold", color=c)

# grants row (top) and donors row (bottom)
box(0.1, 3.3, 2.0, 1.3, "RAW_FLUXX", "grant JSON files", C_RAW)
box(0.1, 0.6, 2.0, 1.3, "RAW_SFDC", "donor JSON files", C_RAW)
box(3.0, 3.3, 2.5, 1.3, "① DT_GRANTS_FLAT", "JSON → columns\nlatest version per grant", C_CLEAN, edge="#2E86C1")
box(3.0, 0.6, 2.5, 1.3, "② DT_OPPS_FLAT", "JSON → columns\nlatest version per opp", C_CLEAN, edge="#2E86C1")
box(3.0, 5.0, 2.5, 1.05, "③ DT_GRANT_BUDGET", "1 row per budget line", C_CLEAN, edge="#2E86C1")
box(6.3, 3.3, 2.8, 1.3, "④ DT_GRANTS_ENRICHED", "+ AI summary (AI_COMPLETE)\n+ AI risk theme (AI_CLASSIFY)", C_AI, edge="#CA6F1E", bold=True)
box(6.3, 0.6, 2.8, 1.3, "⑤ DT_OPPS_ENRICHED", "+ donor sentiment\n(SENTIMENT, −1 to +1)", C_AI, edge="#CA6F1E", bold=True)
box(10.0, 1.8, 3.2, 1.6, "⑥ DT_GRANT_PIPELINE", "grants + donor funding\nused by reports & the AI agent\nTARGET_LAG = 5 minutes", C_PUB, edge="#1E8449", bold=True)

arrow(2.15, 3.95, 2.95, 3.95)      # RAW_FLUXX -> 1
arrow(2.15, 1.25, 2.95, 1.25)      # RAW_SFDC  -> 2
arrow(4.25, 4.65, 4.25, 4.95)      # 1 -> 3
arrow(5.55, 3.95, 6.25, 3.95)      # 1 -> 4
arrow(5.55, 1.25, 6.25, 1.25)      # 2 -> 5
arrow(9.15, 3.8, 9.95, 3.0)        # 4 -> 6
arrow(9.15, 1.4, 9.95, 2.2)        # 5 -> 6

ax.text(11.6, 4.1, "the only deadline:\n≤ 5 minutes old", ha="center", fontsize=9, color="#1E8449", style="italic")
ax.text(11.6, 1.2, "①–⑤ = DOWNSTREAM:\nrefresh when ⑥ needs them", ha="center", fontsize=9, color="#1E8449", style="italic")
ax.text(7.0, 0.1, "Read left to right. Orange = Cortex AI runs here, once per new row.  ③ feeds budget questions in the semantic view.",
        ha="center", fontsize=9, color="#2C3E50")
ax.set_title("The 6 Dynamic Tables: one job each, chained together", fontsize=13.5, weight="bold", loc="left")
plt.tight_layout()
plt.show()
""")

md("""
| # | Layer | Dynamic Table | Reads from | Its one job | AI? |
|---|---|---|---|---|---|
| 1 | Clean | `CURATED.DT_GRANTS_FLAT` | RAW_FLUXX (JSON) | Turn grant JSON into columns; keep the latest version of each grant | — |
| 2 | Clean | `CURATED.DT_OPPS_FLAT` | RAW_SFDC (JSON) | Same for Salesforce donor opportunities | — |
| 3 | Clean | `CURATED.DT_GRANT_BUDGET` | ① DT_GRANTS_FLAT | One row per budget line (Step 2's FLATTEN) | — |
| 4 | **AI** | `AI.DT_GRANTS_ENRICHED` | ① DT_GRANTS_FLAT | Add a one-sentence **AI summary** and an **AI risk theme** to every grant | ✅ `AI_COMPLETE`, `AI_CLASSIFY` |
| 5 | **AI** | `AI.DT_OPPS_ENRICHED` | ② DT_OPPS_FLAT | Add a **donor sentiment score** (−1 to +1) and a health label | ✅ `SENTIMENT` |
| 6 | Publish | `CURATED.DT_GRANT_PIPELINE` | ④ + ⑤ | Join grants to their donor funding: **the one table reports and the AI agent use** | (carries the AI columns) |

**How they trigger each other:** only ⑥ has a business deadline: *no more than 5 minutes old*. Tables ①–⑤ are set to `DOWNSTREAM`, meaning "refresh when the table after me needs it". So a new Fluxx file flows ① → ④ → ⑥ automatically, and the AI only runs on the **new** grants.
""")

sql("dt_ddl", """
-- What a Dynamic Table really is: Step 2's SELECT plus a freshness setting (TARGET_LAG)
SELECT GET_DDL('DYNAMIC_TABLE', 'BP_DEMO.CURATED.DT_GRANTS_FLAT') AS dt_1_grants_flat
""")

sql("dt_ai_ddl", """
-- The AI step: AI functions are just columns in the SELECT
SELECT GET_DDL('DYNAMIC_TABLE', 'BP_DEMO.AI.DT_GRANTS_ENRICHED') AS dt_4_ai_enriched
""")

md("""
### Step 4: how a refresh runs
You never schedule these tables. Snowflake checks ⑥'s 5-minute deadline, works out which of ①–⑤ have new data, refreshes only those in the right order, and skips the rest.
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
box(2.7, 4.6, 2.3, 1.5, "①②③ FLAT + BUDGET", "TARGET_LAG = DOWNSTREAM\nrefresh: AUTO", C_DOWN)
box(5.7, 4.6, 2.5, 1.5, "④⑤ ENRICHED (AI)", "TARGET_LAG = DOWNSTREAM\nrefresh: INCREMENTAL\n(AI runs on new rows only)", C_DOWN)
box(8.9, 4.4, 2.6, 1.9, "⑥ DT_GRANT_PIPELINE", "TARGET_LAG = '5 minutes'\nrefresh: FULL\n(join + GROUP BY: cheap,\nno AI here)", C_SLA, edge="#27AE60", bold=True)
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
box(0.1, 1.15, 3.4, 2.15, "Step 1 · Scheduler (Snowflake-managed)",
    "Checks every DT against its lag.\nNo cron, no SQL Agent job,\nno dependency ordering to code.\nUses warehouse BP_DEMO_WH\nonly while refreshing.", C_ENG, edge="#E67E22")
box(3.85, 1.15, 3.6, 2.15, "Step 2 · Change detection",
    "Change tracking on the sources\nsays which rows were inserted,\nupdated or deleted since the\nlast refresh. Nothing changed\n→ NO_DATA (skipped, ~free).", C_ENG, edge="#E67E22")
box(7.8, 1.15, 3.6, 2.15, "Step 3 · Refresh in order",
    "INCREMENTAL: merge only the\nchanged rows (AI tables ④⑤).\nFULL: recompute the whole\nquery (Snowflake picks it when\nthat's simpler: AUTO mode).", C_ENG, edge="#E67E22")
box(11.75, 1.15, 3.1, 2.15, "Step 4 · Consistent snapshot",
    "All DTs in one refresh share a\nsingle data_timestamp, so\nreaders never see half-updated\ndata. History lives in\nDYNAMIC_TABLE_REFRESH_HISTORY.", C_ENG, edge="#E67E22")
arrow(3.55, 2.2, 3.8, 2.2); arrow(7.5, 2.2, 7.75, 2.2); arrow(11.45, 2.2, 11.7, 2.2)

ax.text(7.5, 3.55, "HOW A REFRESH RUNS", ha="center", fontsize=9.5, weight="bold", color="#7F8C8D")
ax.text(7.5, 0.72,
        "Legacy: SQL Agent job → stored proc → temp tables → TRUNCATE/INSERT on a fixed schedule.   "
        "Here: declare the SELECT + the freshness you need; Snowflake does the rest.",
        ha="center", fontsize=8.8, color="#2C3E50")
ax.set_title("Dynamic Tables: how a refresh runs", fontsize=13.5, weight="bold", loc="left")
plt.tight_layout()
plt.show()
""")   # diagram: Dynamic Table refresh architecture

sql("dt_refresh", """
-- Push the files that GEN_MOCK_FILES created through all 6 Dynamic Tables now, instead of
-- waiting up to 5 minutes. "No new data" means Snowflake had already done it on its own.
ALTER DYNAMIC TABLE BP_DEMO.CURATED.DT_GRANT_PIPELINE REFRESH
""")

sql("new_grants_through", """
-- Proof: the grants from the file the stored procedure just generated, now cleaned and AI-enriched
SELECT grant_id, organization_name, program_area, status, ai_reviewer_summary, ai_primary_risk, source_file
FROM BP_DEMO.AI.DT_GRANTS_ENRICHED
WHERE source_file = (SELECT MAX_BY(file_name, loaded_at) FROM BP_DEMO.RAW.RAW_FLUXX)
""")

sql("dt_status", """
-- Every Dynamic Table, its freshness target and whether it's running
SHOW DYNAMIC TABLES IN DATABASE BP_DEMO
->> SELECT "name", "target_lag", "refresh_mode", "scheduling_state", "data_timestamp" FROM $1 ORDER BY "name"
""")

md("""
👉 *Do:* **Catalog → Database Explorer → BP_DEMO → CURATED → Dynamic Tables → DT_GRANT_PIPELINE → Graph** shows the live version of the picture above. Click a node → **Refresh History** to see each refresh and whether it was incremental.

> **What this means for you:** about 120 lines of SQL replace the stored procedures, cursors and SQL Agent schedule. The 10-minute publishing SLA becomes a single setting.
""")

# ===================================================================== 5 AI
md("""
---
# 5. AI on your data
**What it is:** large language models run **inside Snowflake**, callable from SQL. Your data never leaves the platform and stays under the same security rules.

**Three steps today:**
1. **Try** a prompt on one grant.
2. **Scale** it to every grant, automatically, inside the pipeline.
3. **Ask** questions in plain English instead of opening a report.
""")

sql("ai_experiment", """
-- 1. Try: ask an LLM to brief a program director on one large application.
-- Swap the model by changing one name, e.g. 'llama3.3-70b' (open source) or 'claude-opus-5-5' (Anthropic).
SELECT organization_name, program_area,
       AI_COMPLETE('claude-opus-5-5',
         'You are a philanthropy program director. In 3 bullet points, list the key risks and one question to ask the applicant:\\n\\n'
         || reviewer_notes) AS ai_brief
FROM BP_DEMO.CURATED.DT_GRANTS_FLAT
WHERE status = 'Under Review'
ORDER BY requested_amount DESC LIMIT 1
""")

md("""
**2. Scale:** the same AI calls are written into the Dynamic Tables as ordinary columns. Each new grant gets a summary and a risk theme **once**, as it arrives. No separate AI job is needed.
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

# column headers (same layers as the Step 3 diagram)
for x, t in [(0.9, "RAW (Snowpipe)"), (3.85, "CLEAN"), (7.0, "AI"), (10.2, "PUBLISH"), (13.5, "CONSUME")]:
    ax.text(x, 6.15, t, ha="center", fontsize=9.5, weight="bold", color="#7F8C8D")

box(0.1, 3.5, 1.6, 1.6, "RAW_FLUXX", "Fluxx JSON\n(VARIANT)", C_RAW)
box(0.1, 1.0, 1.6, 1.6, "RAW_SFDC", "Salesforce JSON\n(VARIANT)", C_RAW)
box(2.7, 3.5, 2.3, 1.6, "① DT_GRANTS_FLAT", "FLATTEN + typing\nlatest version per grant\nrefresh: AUTO", C_DT)
box(2.7, 1.0, 2.3, 1.6, "② DT_OPPS_FLAT", "FLATTEN + typing\nlatest version per opp\nrefresh: AUTO", C_DT)
box(5.75, 3.2, 2.5, 2.2, "④ DT_GRANTS_ENRICHED",
    "AI_COMPLETE(llama3.3-70b)\n→ ai_reviewer_summary\nAI_CLASSIFY(6 themes)\n→ ai_primary_risk\nINCREMENTAL: each row once", C_AI, edge="#E67E22", bold=True)
box(5.75, 0.7, 2.5, 2.0, "⑤ DT_OPPS_ENRICHED",
    "SENTIMENT(notes)\n→ donor_sentiment (-1..1)\n→ donor_health bucket\nINCREMENTAL: each row once", C_AI, edge="#E67E22", bold=True)
box(9.0, 2.0, 2.4, 2.4, "⑥ DT_GRANT_PIPELINE", "grant + AI fields\n+ donor pipeline rollup\nTARGET_LAG = 5 min\n(drives everything\nupstream: DOWNSTREAM lag)", C_SLA, edge="#27AE60", bold=True)
box(12.1, 4.3, 2.8, 1.25, "Semantic View + Agent", "SV_GRANT_PIPELINE (⑥ + ⑤ + ③)\n→ Philanthropy Insights Agent", C_USE)
box(12.1, 2.6, 2.8, 1.25, "Cortex Search", "CSS_GRANT_REVIEWS\nCSS_DONOR_NOTES", C_USE)
box(12.1, 0.9, 2.8, 1.25, "SQL / notebook / Tableau", "ai_grants and risk_mix\ncells below", C_USE)

arrow(1.75, 4.3, 2.65, 4.3, "FLATTEN")
arrow(1.75, 1.8, 2.65, 1.8, "FLATTEN")
arrow(5.05, 4.3, 5.7, 4.3)
arrow(5.05, 1.8, 5.7, 1.8)
arrow(8.3, 4.2, 8.95, 3.6)
arrow(8.3, 1.7, 8.95, 2.6)
arrow(11.45, 3.6, 12.05, 4.9)        # pipeline -> semantic view / agent
arrow(11.45, 2.6, 12.05, 1.5)        # pipeline -> SQL / notebook
arrow(8.3, 5.2, 12.05, 3.55, rad=-0.35, dashed=True)   # grants enriched -> search
arrow(8.3, 0.85, 12.05, 2.75, rad=0.35, dashed=True)   # opps enriched -> search
ax.text(10.2, 5.75, "reviewer notes + AI summaries indexed (dashed)", ha="center", fontsize=7.5, color="#566573", style="italic")

ax.text(7.5, 0.15,
        "New file lands → Snowpipe → only the NEW / CHANGED rows flow right → AI is called once per new row → "
        "results are ordinary columns.   Orange = Cortex AI inside the pipeline.",
        ha="center", fontsize=8.8, color="#2C3E50")
ax.set_title("Where the AI runs: the Dynamic Table pipeline", fontsize=13.5, weight="bold", loc="left")
plt.tight_layout()
plt.show()
""")   # diagram: Dynamic Tables -> AI output

sql("ai_grants", """
-- AI summary and risk theme on every grant, kept up to date by the pipeline
SELECT organization_name, program_area, status, requested_amount, ai_reviewer_summary, ai_primary_risk
FROM BP_DEMO.AI.DT_GRANTS_ENRICHED ORDER BY requested_amount DESC LIMIT 5
""")

sql("risk_mix", """
-- What reviewers are worried about, by program area (classified by AI)
SELECT program_area, ai_primary_risk, COUNT(*) AS grants
FROM BP_DEMO.AI.DT_GRANTS_ENRICHED WHERE status = 'Under Review' GROUP BY ALL ORDER BY program_area, grants DESC
""")

reuse("a6211606")   # Altair chart of risk_mix

md("""
**3. Ask:** a **Cortex Agent** reads a *semantic view*, a single shared definition of terms such as "awarded" and "approval rate", and writes the SQL for you. This is what replaces hunting through 500 static reports.

👉 *Do:* **AI & ML → Snowflake Intelligence → Philanthropy Insights Agent**, and ask the question below. Or run the cell.
""")

reuse("38bda7b1")   # agent call

sql("truth_check", """
-- Trust, but verify: the same answer in plain SQL
SELECT program_area, COUNT(*) AS grants, SUM(requested_amount) AS total_requested
FROM BP_DEMO.CURATED.DT_GRANT_PIPELINE
WHERE status = 'Under Review' AND program_area IN ('Arts', 'Education') GROUP BY 1
""")

md("""
> **What this means for you:** 8,000 users get answers from one governed definition of the numbers, and every answer can be traced back to SQL.

**More questions to try:** *What is our approval rate by program area?* · *Which corporate partners are at risk, and who owns them?* · *Summarize reviewers' concerns on Public Health grants under review.*
""")

# ===================================================================== 6 GOVERNANCE
md("""
---
# 6. Governance: the right people see the right data
**What it is:** security rules are attached **to the data itself**, once. They then apply everywhere: SQL, notebooks, Tableau, Excel and the AI agent.

| Control | Answers |
|---|---|
| **Classification** | *Where is our personal data?* |
| **Masking** | *Which values can this role see?* (e.g. hide emails and tax IDs) |
| **Row access** | *Which rows can this role see?* (e.g. Public Health officers see only Public Health) |
""")

sql("classify", """
-- Snowflake scans the table and reports which columns contain personal data (it doesn't change anything)
CALL SYSTEM$CLASSIFY('BP_DEMO.GOV.GRANTEE_DIRECTORY', {'auto_tag': false})
""")

sql("classify_readable", """
-- The same result as a readable list
SELECT f.key AS column_name,
       f.value:recommendation:semantic_category::STRING AS semantic_category,
       f.value:recommendation:privacy_category::STRING  AS privacy_category
FROM TABLE(RESULT_SCAN(LAST_QUERY_ID())) r,
     LATERAL FLATTEN(INPUT => r.$1:classification_result) f
WHERE semantic_category IS NOT NULL
ORDER BY privacy_category, column_name
""")

sql("roles", """
-- Roles are security groups
CREATE ROLE IF NOT EXISTS BP_ANALYST           COMMENT = 'Grants analytics: all program areas, PII masked';
CREATE ROLE IF NOT EXISTS BP_PO_PUBLIC_HEALTH  COMMENT = 'Program officers - Public Health portfolio only';
CREATE ROLE IF NOT EXISTS BP_PO_ENVIRONMENT    COMMENT = 'Program officers - Environment portfolio only';
CREATE ROLE IF NOT EXISTS BP_GRANTS_COMPLIANCE COMMENT = 'Grants compliance: all areas, full PII';
GRANT ROLE BP_ANALYST, BP_PO_PUBLIC_HEALTH, BP_PO_ENVIRONMENT, BP_GRANTS_COMPLIANCE TO ROLE SYSADMIN;
""")

sql("masking", """
-- Masking: only Compliance sees real names, phones, emails and tax IDs
CREATE OR REPLACE MASKING POLICY BP_DEMO.GOV.MASK_PII_STRING AS (val STRING) RETURNS STRING ->
  CASE WHEN CURRENT_ROLE() IN ('ACCOUNTADMIN', 'BP_GRANTS_COMPLIANCE') THEN val ELSE '*** MASKED ***' END;

CREATE OR REPLACE MASKING POLICY BP_DEMO.GOV.MASK_EMAIL AS (val STRING) RETURNS STRING ->
  CASE WHEN CURRENT_ROLE() IN ('ACCOUNTADMIN', 'BP_GRANTS_COMPLIANCE') THEN val
       ELSE REGEXP_REPLACE(val, '^[^@]+', '*****') END;

CREATE OR REPLACE MASKING POLICY BP_DEMO.GOV.MASK_TAX_ID AS (val STRING) RETURNS STRING ->
  CASE WHEN CURRENT_ROLE() IN ('ACCOUNTADMIN', 'BP_GRANTS_COMPLIANCE') THEN val
       ELSE 'XX-XXX' || RIGHT(val, 4) END;

ALTER TABLE BP_DEMO.GOV.GRANTEE_DIRECTORY MODIFY
  COLUMN contact_name  SET MASKING POLICY BP_DEMO.GOV.MASK_PII_STRING,
  COLUMN contact_phone SET MASKING POLICY BP_DEMO.GOV.MASK_PII_STRING,
  COLUMN contact_email SET MASKING POLICY BP_DEMO.GOV.MASK_EMAIL,
  COLUMN tax_id        SET MASKING POLICY BP_DEMO.GOV.MASK_TAX_ID;
""")

sql("row_access", """
-- Row access: a business-owned mapping table decides which program areas each role sees
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
### Prove it: the same query, run as two different roles
""")

sql("as_analyst", """
-- As an ANALYST: every program area, but personal data is masked
EXECUTE USING POLICY_CONTEXT(CURRENT_ROLE => 'BP_ANALYST') AS
SELECT program_area, organization_name, contact_name, contact_email, tax_id
FROM BP_DEMO.GOV.GRANTEE_DIRECTORY ORDER BY program_area LIMIT 8
""")

sql("as_po_health", """
-- As a PUBLIC HEALTH program officer: only Public Health rows, and personal data still masked
EXECUTE USING POLICY_CONTEXT(CURRENT_ROLE => 'BP_PO_PUBLIC_HEALTH') AS
SELECT program_area, organization_name, contact_name, contact_email, tax_id
FROM BP_DEMO.GOV.GRANTEE_DIRECTORY ORDER BY program_area LIMIT 8
""")

md("""
> **What this means for you:** write the rule once and it holds everywhere: Tableau, Excel, notebooks and the AI agent. Giving an officer access to Education is one INSERT into the mapping table, not a code change.
""")

# ===================================================================== 7 MARKETPLACE
md("""
---
# 7. Add outside data from the Marketplace
The **Snowflake Marketplace** offers thousands of live datasets from third parties. The data is **shared, not copied**: no ETL, no files, always current, and you pay nothing to store it.

👉 *Do:* **Catalog → Marketplace** → search **"Snowflake Public Data (Free)"** → *Get*. (Already installed here as `SNOWFLAKE_PUBLIC_DATA_FREE`.) It includes World Bank, WHO, IMF and Our World in Data.

**Question:** *Are our Road Safety and Clean Air dollars going where the need is greatest?*
""")

reuse("7b253a8b")   # mkt_join
reuse("2763751a")   # chart

md("""
> **What this means for you:** your grants and World Bank need indicators sit side by side in one query, with no download and no refresh job. The same sharing works the other way: you can share live, governed grant outcomes with co-funders without sending files.
""")

# ===================================================================== 8 COST + NEXT
md("""
---
# 8. Cost control and next steps
👉 *Do:* **Admin → Cost Management**
- **Consumption:** credits by warehouse and by service (AI, Snowpipe, Dynamic Tables).
- **Budgets:** monthly limits with alerts.
- **Resource monitors:** hard caps that suspend a warehouse.

The same numbers are available in SQL (they arrive with up to ~3 hours' delay):
""")

reuse("af43246a")   # cost_wh

md("""
### Recap
| Building block | What you saw | Outcome for BP |
|---|---|---|
| Load files | Stage + COPY INTO | Exports in, with no ETL server |
| Elastic compute | XS → MEDIUM, result cache | Fast when needed, $0 when idle |
| Safety nets | Clone, Time Travel | Dev copies in seconds; mistakes undone |
| Pipelines | Snowpipe + Dynamic Tables | Stored procs and SQL Agent retired; 5-minute freshness |
| AI | AI_COMPLETE, AI_CLASSIFY, Cortex Agent | Answers instead of 500 static reports |
| Governance | Classification, masking, row access | Portfolio-level security; PII protected |

### Suggested follow-up sessions
| Session | Covers |
|---|---|
| **Data engineering deep dive** | Loading 200+ files (sizing for loads), JSON querying and FLATTEN, Snowpipe vs scheduled COPY INTO, error handling for bad files |
| **Fluxx and Salesforce integration** | Pulling from the Fluxx API on a schedule; Salesforce connectors and zero-copy sharing |
| **Snowflake Intelligence workshop** | Building the semantic view and agent with your real report definitions |
| **Governance and security** | Tag-based masking, access history, Trust Center, SSO |
| **Marketplace and collaboration** | Enriching grants with World Bank and WHO data; secure sharing with co-funders |
| **Cost management** | Budgets, resource monitors, chargeback with query and object tags |

**Hands-on next step:** the free **Zero to Snowflake (Tasty Bytes)** quickstart repeats every building block step by step.
""")

nb = {"cells": cells, "metadata": V2["metadata"], "nbformat": 4, "nbformat_minor": 5}
out = os.path.join(NB_DIR, "BP_Demo_v3_40min.ipynb")
json.dump(nb, open(out, "w"), indent=1)
print(out, len(cells), "cells")

-- =============================================================================
-- DATA LOADING & WAREHOUSE SIZING BEST PRACTICES DEMO
-- =============================================================================
--
-- PURPOSE:
--   Demonstrate how to load data into Snowflake efficiently and how to
--   right-size warehouses for bulk loading workloads. This is a hands-on
--   demo — run each section in order and observe the results.
--
-- AUDIENCE:  Any Snowflake customer evaluating loading patterns
-- RUNTIME:   ~15-20 minutes end-to-end
-- COST:      ~1-2 credits total
-- DATA:      Uses TPCDS_10TB.TPCDS_SF10TCL.CUSTOMER (~65M rows, ~2.3GB)
--
-- PREREQUISITES:
--   The TPCDS_10TB sample data share must be imported into your account.
--   If it is not already available, import it from the Snowflake Marketplace:
--     1. In Snowsight, go to Data Products → Marketplace
--     2. Search for "TPC-DS" and select the Snowflake-provided listing
--     3. Click "Get" and accept the terms — this creates the TPCDS_10TB database
--   Alternatively, use any table with 10M+ rows as the source. The demo
--   principles apply regardless of the specific dataset.
--
-- =============================================================================
-- KEY PRINCIPLES DEMONSTRATED
-- =============================================================================
--
--  1. FILE SIZING MATTERS
--     Snowflake recommends 100-250 MB compressed files for optimal parallel
--     processing. Too many small files = overhead. Too few large files =
--     underutilized warehouse threads.
--     (Ref: https://docs.snowflake.com/en/user-guide/data-load-considerations-prepare)
--
--  2. WAREHOUSE SIZING: BIGGER IS NOT ALWAYS BETTER
--     Each warehouse size doubles compute AND credits/hour. For loading,
--     the parallel thread count determines how many files load simultaneously.
--     If your file count is low, a huge warehouse wastes threads (and money).
--     The goal: find the size where elapsed time drops meaningfully without
--     overpaying for idle threads.
--
--  3. CREDIT ECONOMICS — "SAME COST, FASTER"
--     A MEDIUM warehouse costs 4x an XSMALL per hour. But if it finishes
--     4x faster, the total credit spend is identical — you just get the
--     data loaded sooner. Per-second billing makes right-sizing free.
--       XS = 1 cr/hr  |  S = 2 cr/hr  |  M = 4 cr/hr  |  L = 8 cr/hr
--
--  4. DEDICATED LOAD WAREHOUSES
--     Separate warehouses for loading vs. querying. Loading is I/O-heavy
--     and bursty; mixing it with analytical queries causes queueing.
--     (Ref: https://docs.snowflake.com/en/user-guide/data-load-considerations-plan)
--
--  5. DIRECTORY-LEVEL COPY — LET SNOWFLAKE PARALLELIZE
--     Point COPY INTO at a stage path. Snowflake distributes files across
--     all available warehouse threads automatically. No need for FILES lists,
--     PATTERN regex, or per-file COPY commands.
--
--  6. TAG YOUR LOADS FOR COST ATTRIBUTION
--     Use QUERY_TAG to label load operations. This makes it easy to query
--     INFORMATION_SCHEMA or ACCOUNT_USAGE to see exactly what each load cost.
--
--  7. AUTO_SUSPEND LOW, AUTO_RESUME ON
--     Per-second billing (60-second minimum). Set AUTO_SUSPEND to 60 seconds
--     so the warehouse shuts down quickly after loading completes. AUTO_RESUME
--     ensures it starts automatically on the next COPY.
--     (Ref: https://docs.snowflake.com/en/user-guide/warehouses-considerations)
--
-- DEMO FLOW:
--   Section 0 — Setup (database, file format, stage, warehouse, table)
--   Section 1 — Generate test data (unload to stage)
--   Section 2 — Inspect staged files (count, size, format)
--   Section 3 — Load tests (XS → S → M → L), 5 runs each
--   Section 4 — Analyze results (timing comparison + credit estimates)
--   Section 5 — Cost queries (recent + historical)
--   Section 6 — Cleanup
--
-- HOW TO RUN:
--   Execute each section top-to-bottom in a Snowflake worksheet.
--   Sections marked [PAUSE] are good stopping points for discussion.
-- =============================================================================


-- =============================================================================
-- SECTION 0: SETUP
-- =============================================================================
-- Creates a dedicated database, named file format, internal stage, and
-- a per-user warehouse for the demo. Using SYSADMIN for object creation
-- follows least-privilege principles — ACCOUNTADMIN is only needed for
-- cost queries in Section 5.
-- =============================================================================

USE ROLE SYSADMIN;

CREATE DATABASE IF NOT EXISTS LOAD_TEST
  COMMENT = 'Demo: data loading & warehouse sizing best practices';

USE DATABASE LOAD_TEST;
USE SCHEMA PUBLIC;

-- Named file format — reusable, self-documenting, and avoids inline repetition.
-- CSV with GZIP compression is the most common bulk loading format.
-- For Parquet workloads, create a second format: TYPE = PARQUET, COMPRESSION = SNAPPY.
CREATE OR REPLACE FILE FORMAT CSV_GZIP
  TYPE            = CSV
  COMPRESSION     = GZIP
  FIELD_OPTIONALLY_ENCLOSED_BY = '"'
  SKIP_HEADER     = 1
  COMMENT         = 'Standard CSV/GZIP format for bulk loading demos';

-- Internal stage using the named file format.
-- You can also use external stages (S3/Azure/GCS) — the loading principles
-- are identical. Internal stages are convenient for demos.
CREATE OR REPLACE STAGE LOAD_STAGE
  FILE_FORMAT = CSV_GZIP
  COMMENT     = 'Internal stage for loading demo data';

-- Per-user warehouse. Naming convention: <USER>_LOAD_WH
-- This pattern avoids collisions when multiple people run the demo.
-- Key settings:
--   INITIALLY_SUSPENDED = TRUE — don't burn credits until first use
--   AUTO_RESUME = TRUE         — starts automatically on first query
--   AUTO_SUSPEND = 60          — shuts down after 60s of idle (minimum recommended)
SELECT CURRENT_USER() AS DEMO_USER;
SET wh_name = CURRENT_USER() || '_LOAD_WH';

CREATE OR REPLACE WAREHOUSE IDENTIFIER($wh_name)
  WAREHOUSE_SIZE      = 'XSMALL'
  INITIALLY_SUSPENDED = TRUE
  AUTO_RESUME         = TRUE
  AUTO_SUSPEND        = 60
  COMMENT             = 'Dedicated loading warehouse — right-sized per test';

USE WAREHOUSE IDENTIFIER($wh_name);


-- =============================================================================
-- SECTION 1: GENERATE TEST DATA — Unload to Stage
-- =============================================================================
-- We unload TPCDS_SF10TCL.CUSTOMER (~65M rows, ~2.3GB compressed) to the
-- internal stage. This creates the files we will load back in Section 3.
--
-- PRINCIPLE: HOW UNLOAD FILE COUNT AND SIZE ARE DETERMINED
--
-- The warehouse thread count controls how many files are written in parallel.
-- Each thread receives a portion of the rows and writes them to files, capping
-- each file at MAX_FILE_SIZE bytes (measured PRE-compression).
--
--   Thread count by warehouse size:
--     XS = 8  |  S = 16  |  M = 32  |  L = 64  |  XL = 128
--
-- The interaction between thread count and MAX_FILE_SIZE determines total files:
--
--   Data per thread = total_data / thread_count
--   Files per thread = CEIL(data_per_thread / MAX_FILE_SIZE)
--   Total files      = thread_count × files_per_thread
--
-- EXAMPLE with CUSTOMER (~2.3GB raw, XS warehouse = 8 threads):
--
--   MAX_FILE_SIZE = 16MB (default):
--     Each thread has ~290MB of data → 290/16 = ~18 files per thread
--     Total: ~144 files, each ~3-5MB compressed ← TOO SMALL
--
--   MAX_FILE_SIZE = 1GB (this demo):
--     Each thread has ~290MB of data → fits in 1 file per thread
--     Total: 8 files, each ~150-300MB compressed ← IN THE SWEET SPOT
--
-- KEY INSIGHT FOR CUSTOMERS:
--   The default MAX_FILE_SIZE (16MB) is NOT optimized for loading — it is a
--   conservative default that works for any scenario. For bulk load workflows,
--   ALWAYS increase it so that compressed files land in the 100-250MB range.
--   (The 16MB default is coincidentally the same as Snowflake's internal
--   micro-partition size, but the two are completely unrelated.)
--
-- WHY FILE COUNT MATTERS FOR LOADING:
--   When you load those files back (Section 3), the warehouse thread count
--   determines how many files load in parallel. If you have 8 files and use
--   an XS (8 threads), all files load simultaneously. Use a LARGE (64 threads)
--   and 56 threads sit idle — you pay 8x the credit rate for no benefit.
--   This is why right-sizing the warehouse to match the file count is critical.
--
-- NOTE: For a faster demo with fewer files, add a LIMIT clause:
--   SELECT * FROM TPCDS_10TB.TPCDS_SF10TCL.CUSTOMER LIMIT 15000000
-- For a larger test (more files, clearer sizing differences), use
-- STORE_SALES or CATALOG_SALES — but expect longer unload times.
-- =============================================================================

COPY INTO @LOAD_STAGE/CUSTOMER/
  FROM TPCDS_10TB.TPCDS_SF10TCL.CUSTOMER
  FILE_FORMAT = (TYPE = CSV COMPRESSION = GZIP)
  MAX_FILE_SIZE = 1073741824       -- 1 GB pre-compression → ~150-300 MB compressed per file
  HEADER      = TRUE
  OVERWRITE   = TRUE;

-- >>> [PAUSE] — The unload is complete. Now let's inspect what was created.


-- =============================================================================
-- SECTION 2: INSPECT STAGED FILES
-- =============================================================================
-- Before loading, always check your staged files. Key things to verify:
--   - File count: Are there enough files to keep the warehouse busy?
--   - File size: Are files in the 100-250MB range?
--   - Total volume: Does this match your expectations?
--
-- PRINCIPLE: The number of files that load in parallel cannot exceed the
-- warehouse thread count. If you have 4 files and an XL warehouse (128
-- threads), 124 threads sit idle. Conversely, if you have 10,000 tiny
-- files, the per-file overhead dominates.
-- =============================================================================

-- List all files in the stage path and save the query ID
LIST @LOAD_STAGE/CUSTOMER/;
SET list_qid = LAST_QUERY_ID();

-- Preview the data (sanity check — are columns aligned?)
SELECT $1, $2, $3 FROM @LOAD_STAGE/CUSTOMER/ LIMIT 10;

-- File count, average size, and total volume
-- Uses the saved LIST query ID for reliable RESULT_SCAN reference.
SELECT
    COUNT(*)                                         AS NUM_FILES,
    ROUND(AVG("size") / POWER(1024, 2), 1)           AS AVG_FILE_SIZE_MB,
    ROUND(SUM("size") / POWER(1024, 3), 2)           AS TOTAL_COMPRESSED_GB
FROM TABLE(RESULT_SCAN($list_qid));

-- >>> [PAUSE] — Discussion points:
-- >>>   - How many files were created? (Typically 8-20 for this dataset)
-- >>>   - What is the average file size? (Should be ~100-250MB compressed)
-- >>>   - Snowflake auto-splits the unload into well-sized chunks.
-- >>>   - If your source system produces tiny files (1-10MB), aggregate them
-- >>>     before loading. The overhead per file is non-trivial at scale.
-- >>>
-- >>> FILE SIZING RULE OF THUMB:
-- >>>   - Target 100-250 MB compressed per file
-- >>>   - Minimum: enough files to keep the warehouse threads busy
-- >>>   - Maximum: no single file should exceed a few GB
-- >>>   (Ref: https://docs.snowflake.com/en/user-guide/data-load-considerations-prepare)


-- =============================================================================
-- SECTION 3: LOAD TESTS — Warehouse Sizing Comparison
-- =============================================================================
-- We load the same data 5 times at each warehouse size (XS, S, M, L).
-- QUERY_TAG labels each run so we can compare them in Section 4.
--
-- WHY 5 RUNS?
--   The first run may include warehouse startup time (cold start) and
--   cache warming. Subsequent runs show steady-state performance.
--   We compare averages to smooth out variance.
--
-- FORCE = TRUE tells Snowflake to reload even though these files were
-- already loaded (the dedup metadata would otherwise skip them).
--
-- WAREHOUSE THREAD COUNTS (determines max parallel file loads):
--   XS  =  8 threads   |   M  = 32 threads
--   S   = 16 threads   |   L  = 64 threads
--   XL  = 128 threads  |  2XL = 256 threads
--
-- CREDIT RATES (per hour of continuous use):
--   XS = 1 cr/hr  |  S = 2 cr/hr  |  M = 4 cr/hr  |  L = 8 cr/hr
--
-- PRINCIPLE: If a MEDIUM finishes in 1/4 the time of XSMALL, total
-- credits are the same (4x rate × 1/4 time = 1x cost). You get the
-- data loaded faster for the same price. Per-second billing makes this
-- work — you only pay for the seconds the warehouse is running.
-- =============================================================================

-- Create the target table (matching TPCDS CUSTOMER schema)
CREATE OR REPLACE TABLE CUSTOMER LIKE TPCDS_10TB.TPCDS_SF10TCL.CUSTOMER;


-- ---------------------------------------------------------------------------
-- TEST 1: XSMALL (1 credit/hour, 8 threads)
-- ---------------------------------------------------------------------------
ALTER WAREHOUSE IDENTIFIER($wh_name) SET WAREHOUSE_SIZE = 'XSMALL';
ALTER SESSION SET QUERY_TAG = 'LOAD_TEST_XSMALL';

TRUNCATE TABLE CUSTOMER;
COPY INTO CUSTOMER FROM @LOAD_STAGE/CUSTOMER/ FORCE = TRUE;
COPY INTO CUSTOMER FROM @LOAD_STAGE/CUSTOMER/ FORCE = TRUE;
COPY INTO CUSTOMER FROM @LOAD_STAGE/CUSTOMER/ FORCE = TRUE;
COPY INTO CUSTOMER FROM @LOAD_STAGE/CUSTOMER/ FORCE = TRUE;
COPY INTO CUSTOMER FROM @LOAD_STAGE/CUSTOMER/ FORCE = TRUE;


-- ---------------------------------------------------------------------------
-- TEST 2: SMALL (2 credits/hour, 16 threads)
-- ---------------------------------------------------------------------------
TRUNCATE TABLE CUSTOMER;
ALTER WAREHOUSE IDENTIFIER($wh_name) SET WAREHOUSE_SIZE = 'SMALL';
ALTER SESSION SET QUERY_TAG = 'LOAD_TEST_SMALL';

COPY INTO CUSTOMER FROM @LOAD_STAGE/CUSTOMER/ FORCE = TRUE;
COPY INTO CUSTOMER FROM @LOAD_STAGE/CUSTOMER/ FORCE = TRUE;
COPY INTO CUSTOMER FROM @LOAD_STAGE/CUSTOMER/ FORCE = TRUE;
COPY INTO CUSTOMER FROM @LOAD_STAGE/CUSTOMER/ FORCE = TRUE;
COPY INTO CUSTOMER FROM @LOAD_STAGE/CUSTOMER/ FORCE = TRUE;


-- ---------------------------------------------------------------------------
-- TEST 3: MEDIUM (4 credits/hour, 32 threads)
-- ---------------------------------------------------------------------------
TRUNCATE TABLE CUSTOMER;
ALTER WAREHOUSE IDENTIFIER($wh_name) SET WAREHOUSE_SIZE = 'MEDIUM';
ALTER SESSION SET QUERY_TAG = 'LOAD_TEST_MEDIUM';

COPY INTO CUSTOMER FROM @LOAD_STAGE/CUSTOMER/ FORCE = TRUE;
COPY INTO CUSTOMER FROM @LOAD_STAGE/CUSTOMER/ FORCE = TRUE;
COPY INTO CUSTOMER FROM @LOAD_STAGE/CUSTOMER/ FORCE = TRUE;
COPY INTO CUSTOMER FROM @LOAD_STAGE/CUSTOMER/ FORCE = TRUE;
COPY INTO CUSTOMER FROM @LOAD_STAGE/CUSTOMER/ FORCE = TRUE;


-- ---------------------------------------------------------------------------
-- TEST 4: LARGE (8 credits/hour, 64 threads)
-- ---------------------------------------------------------------------------
TRUNCATE TABLE CUSTOMER;
ALTER WAREHOUSE IDENTIFIER($wh_name) SET WAREHOUSE_SIZE = 'LARGE';
ALTER SESSION SET QUERY_TAG = 'LOAD_TEST_LARGE';

COPY INTO CUSTOMER FROM @LOAD_STAGE/CUSTOMER/ FORCE = TRUE;
COPY INTO CUSTOMER FROM @LOAD_STAGE/CUSTOMER/ FORCE = TRUE;
COPY INTO CUSTOMER FROM @LOAD_STAGE/CUSTOMER/ FORCE = TRUE;
COPY INTO CUSTOMER FROM @LOAD_STAGE/CUSTOMER/ FORCE = TRUE;
COPY INTO CUSTOMER FROM @LOAD_STAGE/CUSTOMER/ FORCE = TRUE;

-- Clear the tag
ALTER SESSION SET QUERY_TAG = '';
TRUNCATE TABLE CUSTOMER;


-- =============================================================================
-- SECTION 4: ANALYZE RESULTS — Find the Optimal Warehouse Size
-- =============================================================================
-- We query INFORMATION_SCHEMA.QUERY_HISTORY_BY_WAREHOUSE to compare the
-- load performance across all four warehouse sizes.
--
-- KEY METRICS:
--   - EXECUTION_TIME: actual compute time (excludes queueing/compilation)
--   - TOTAL_ELAPSED_TIME: wall-clock time including all overhead
--   - Estimated credits: (credits_per_hour / 3,600,000) × elapsed_ms
--
-- WHAT TO LOOK FOR:
--   - Does doubling warehouse size halve the load time?
--   - At what point do you see diminishing returns?
--   - Which size gives the best time-to-value per credit spent?
-- =============================================================================

-- Capture recent query history for this warehouse
CREATE OR REPLACE TEMPORARY TABLE LOAD_TIMINGS AS
SELECT *
FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY_BY_WAREHOUSE(
    WAREHOUSE_NAME => $wh_name,
    RESULT_LIMIT   => 10000
))
WHERE QUERY_TAG LIKE 'LOAD_TEST_%'
  AND QUERY_TYPE = 'COPY';

-- ---------------------------------------------------------------------------
-- SUMMARY: Average load time and estimated credits by warehouse size
-- ---------------------------------------------------------------------------
-- This is the key comparison table. Look for the "sweet spot" where
-- load time drops meaningfully without the credit cost increasing.
SELECT
    QUERY_TAG                                                      AS TEST,
    WAREHOUSE_SIZE                                                 AS WH_SIZE,
    COUNT(*)                                                       AS RUNS,
    ROUND(AVG(EXECUTION_TIME)   / 1000, 2)                        AS AVG_EXEC_SEC,
    ROUND(MIN(EXECUTION_TIME)   / 1000, 2)                        AS MIN_EXEC_SEC,
    ROUND(MAX(EXECUTION_TIME)   / 1000, 2)                        AS MAX_EXEC_SEC,
    ROUND(AVG(TOTAL_ELAPSED_TIME) / 1000, 2)                      AS AVG_ELAPSED_SEC,
    -- Credit rate per warehouse size
    CASE WAREHOUSE_SIZE
        WHEN 'X-Small'  THEN 1
        WHEN 'Small'    THEN 2
        WHEN 'Medium'   THEN 4
        WHEN 'Large'    THEN 8
    END                                                            AS CREDITS_PER_HR,
    -- Estimated credits per load = (cr/hr) × (elapsed_sec / 3600)
    ROUND(
        CASE WAREHOUSE_SIZE
            WHEN 'X-Small'  THEN 1
            WHEN 'Small'    THEN 2
            WHEN 'Medium'   THEN 4
            WHEN 'Large'    THEN 8
        END * (AVG(TOTAL_ELAPSED_TIME) / 1000.0) / 3600.0
    , 4)                                                           AS AVG_CREDITS_PER_LOAD,
    -- Estimated cost at $3/credit (Enterprise edition)
    ROUND(
        CASE WAREHOUSE_SIZE
            WHEN 'X-Small'  THEN 1
            WHEN 'Small'    THEN 2
            WHEN 'Medium'   THEN 4
            WHEN 'Large'    THEN 8
        END * (AVG(TOTAL_ELAPSED_TIME) / 1000.0) / 3600.0 * 3.0
    , 4)                                                           AS AVG_COST_USD
FROM LOAD_TIMINGS
GROUP BY QUERY_TAG, WAREHOUSE_SIZE
ORDER BY
    CASE WAREHOUSE_SIZE
        WHEN 'X-Small'  THEN 1
        WHEN 'Small'    THEN 2
        WHEN 'Medium'   THEN 3
        WHEN 'Large'    THEN 4
    END;

-- >>> [PAUSE] — THE KEY TAKEAWAY
-- >>>
-- >>> Look at AVG_CREDITS_PER_LOAD across warehouse sizes.
-- >>> You will typically see one of two patterns:
-- >>>
-- >>>   PATTERN A (few files, small data):
-- >>>     Credits are roughly EQUAL across sizes. Bigger warehouse finishes
-- >>>     faster but costs the same. Choose the size that gives acceptable
-- >>>     load latency.
-- >>>
-- >>>   PATTERN B (many files, large data):
-- >>>     Bigger warehouses show LOWER total credits because they process
-- >>>     more files in parallel, reducing per-file overhead. There is a
-- >>>     sweet spot — going beyond it wastes threads on idle capacity.
-- >>>
-- >>> GENERAL GUIDANCE (from Snowflake docs):
-- >>>   "Unless you are bulk loading a large number of files concurrently
-- >>>    (hundreds or thousands), a smaller warehouse (Small, Medium, Large)
-- >>>    is generally sufficient. Using a larger warehouse (X-Large, 2X-Large)
-- >>>    will consume more credits and may not result in any performance increase."
-- >>>   (Ref: https://docs.snowflake.com/en/user-guide/data-load-considerations-plan)


-- ---------------------------------------------------------------------------
-- DETAIL: All individual runs (for deeper analysis)
-- ---------------------------------------------------------------------------
SELECT
    QUERY_TAG                                                  AS TEST,
    WAREHOUSE_SIZE                                             AS WH_SIZE,
    ROUND(TOTAL_ELAPSED_TIME / 1000, 2)                        AS ELAPSED_SEC,
    ROUND(EXECUTION_TIME / 1000, 2)                            AS EXEC_SEC,
    ROUND(COMPILATION_TIME / 1000, 2)                          AS COMPILE_SEC,
    ROUND(QUEUED_OVERLOAD_TIME / 1000, 2)                      AS QUEUED_SEC,
    ROUND(LIST_EXTERNAL_FILE_TIME / 1000, 2)                   AS LIST_FILES_SEC,
    ROWS_INSERTED,
    QUERY_ID,
    START_TIME
FROM LOAD_TIMINGS
ORDER BY
    CASE WAREHOUSE_SIZE
        WHEN 'X-Small'  THEN 1
        WHEN 'Small'    THEN 2
        WHEN 'Medium'   THEN 3
        WHEN 'Large'    THEN 4
    END,
    START_TIME;


-- =============================================================================
-- SECTION 5: COST ANALYSIS — Query Actual Credit Usage
-- =============================================================================
-- Two approaches depending on how recently the loads ran:
--   A) INFORMATION_SCHEMA (last ~45 minutes, no latency)
--   B) QUERY_ATTRIBUTION_HISTORY (per-query actual credits, up to 8hr latency)
--   C) ACCOUNT_USAGE.QUERY_HISTORY (historical, up to 365 days, ~45 min latency)
--   D) Cloud Services breakdown
--
-- These queries require ACCOUNTADMIN or a role with MONITOR privileges.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 5A: Recent loads (within the last hour) — INFORMATION_SCHEMA
-- ---------------------------------------------------------------------------
-- Cloud Services credits for COPY operations.
-- Note: Cloud Services charges are waived up to 10% of daily warehouse credits.
USE ROLE ACCOUNTADMIN;

SELECT
    WAREHOUSE_NAME,
    WAREHOUSE_SIZE,
    QUERY_TAG,
    ROUND(EXECUTION_TIME / 1000, 2)                    AS EXEC_SEC,
    ROUND(TOTAL_ELAPSED_TIME / 1000, 2)                AS ELAPSED_SEC,
    ROUND(CREDITS_USED_CLOUD_SERVICES, 6)              AS CS_CREDITS,
    QUERY_ID
FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY(
    DATE_RANGE_START => DATEADD('hours', -1, CURRENT_TIMESTAMP()),
    DATE_RANGE_END   => CURRENT_TIMESTAMP()
))
WHERE QUERY_TYPE = 'COPY'
  AND QUERY_TAG LIKE 'LOAD_TEST_%'
ORDER BY CREDITS_USED_CLOUD_SERVICES DESC
LIMIT 20;


-- ---------------------------------------------------------------------------
-- 5B: Per-Query Attributed Credits — QUERY_ATTRIBUTION_HISTORY (recommended)
-- ---------------------------------------------------------------------------
-- This view (available since Aug 2024) provides the actual compute credits
-- attributed to each query — far more accurate than manual estimates.
-- Latency: up to 8 hours. Run this after the demo to see true costs.
-- Requires ACCOUNTADMIN or USAGE_VIEWER database role on SNOWFLAKE DB.
-- (Ref: https://docs.snowflake.com/en/sql-reference/account-usage/query_attribution_history)

SELECT
    qah.QUERY_TAG,
    qah.WAREHOUSE_NAME,
    COUNT(*)                                                AS RUNS,
    ROUND(SUM(qah.CREDITS_ATTRIBUTED_COMPUTE), 6)          AS TOTAL_ATTRIBUTED_CREDITS,
    ROUND(AVG(qah.CREDITS_ATTRIBUTED_COMPUTE), 6)          AS AVG_CREDITS_PER_LOAD,
    ROUND(AVG(qah.CREDITS_ATTRIBUTED_COMPUTE) * 3.0, 4)    AS AVG_COST_USD_AT_3
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_ATTRIBUTION_HISTORY qah
WHERE qah.QUERY_TAG LIKE 'LOAD_TEST_%'
  AND qah.START_TIME >= DATEADD('day', -7, CURRENT_TIMESTAMP())
GROUP BY qah.QUERY_TAG, qah.WAREHOUSE_NAME
ORDER BY
    CASE SPLIT_PART(qah.QUERY_TAG, '_', 3)
        WHEN 'XSMALL'  THEN 1
        WHEN 'SMALL'   THEN 2
        WHEN 'MEDIUM'  THEN 3
        WHEN 'LARGE'   THEN 4
    END;

-- >>> NOTE: If this returns no rows, wait a few hours — latency is up to 8 hours.
-- >>> Compare CREDITS_ATTRIBUTED_COMPUTE (actual) to AVG_CREDITS_PER_LOAD
-- >>> from Section 4 (estimated). They should be in the same ballpark.


-- ---------------------------------------------------------------------------
-- 5C: Historical loads (last 30 days) — ACCOUNT_USAGE.QUERY_HISTORY
-- ---------------------------------------------------------------------------
-- Run this query later (after ~45 min latency) to see full credit details.
-- Useful for showing customers how to audit loading costs over time.

SELECT
    WAREHOUSE_NAME,
    WAREHOUSE_SIZE,
    QUERY_TAG,
    ROWS_INSERTED,
    ROUND(EXECUTION_TIME / 1000, 2)                    AS EXEC_SEC,
    ROUND(TOTAL_ELAPSED_TIME / 1000, 2)                AS ELAPSED_SEC,
    ROUND(CREDITS_USED_CLOUD_SERVICES, 6)              AS CS_CREDITS,
    START_TIME
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE QUERY_TYPE = 'COPY'
  AND QUERY_TAG LIKE 'LOAD_TEST_%'
  AND START_TIME >= DATEADD('day', -30, CURRENT_TIMESTAMP())
ORDER BY START_TIME DESC
LIMIT 20;


-- ---------------------------------------------------------------------------
-- 5D: Cloud Services breakdown by query type (last hour)
-- ---------------------------------------------------------------------------
-- Shows whether COPY operations are contributing significant CS credits.
-- If CS credits < 10% of warehouse credits for the day, they are free.

SELECT
    QUERY_TYPE,
    COUNT(*)                                            AS NUM_QUERIES,
    ROUND(SUM(CREDITS_USED_CLOUD_SERVICES), 4)          AS TOTAL_CS_CREDITS
FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY(
    DATE_RANGE_START => DATEADD('hours', -1, CURRENT_TIMESTAMP()),
    DATE_RANGE_END   => CURRENT_TIMESTAMP()
))
WHERE CREDITS_USED_CLOUD_SERVICES > 0
GROUP BY QUERY_TYPE
ORDER BY TOTAL_CS_CREDITS DESC
LIMIT 10;


-- =============================================================================
-- SECTION 6: CLEANUP
-- =============================================================================
-- Remove all demo objects. Uncomment and run when done.
-- =============================================================================

USE ROLE SYSADMIN;

-- DROP DATABASE LOAD_TEST;

-- SET wh_name = CURRENT_USER() || '_LOAD_WH';
-- DROP WAREHOUSE IDENTIFIER($wh_name);

-- >>> To clean up, uncomment the DROP statements above and execute.
-- >>> The warehouse auto-suspends after 60 seconds regardless.


-- =============================================================================
-- SUMMARY OF BEST PRACTICES
-- =============================================================================
--
--  PRACTICE                          WHY IT MATTERS
--  --------------------------------  ------------------------------------------------
--  Files: 100-250 MB compressed      Maximizes parallel throughput per warehouse thread
--  Directory-level COPY INTO         One listing, one dedup pass, one lock acquisition
--  Dedicated load warehouse          Isolates load I/O from query workloads
--  Right-size the warehouse          Match thread count to file count; avoid idle threads
--  AUTO_SUSPEND = 60, AUTO_RESUME    Per-second billing — only pay for active seconds
--  QUERY_TAG on every load           Enables cost attribution and performance auditing
--  Named FILE FORMAT objects         Reusable, self-documenting, avoids inline errors
--  SYSADMIN for operations           Least privilege; ACCOUNTADMIN only for cost queries
--
--  REFERENCES:
--    - File sizing:      https://docs.snowflake.com/en/user-guide/data-load-considerations-prepare
--    - Planning loads:   https://docs.snowflake.com/en/user-guide/data-load-considerations-plan
--    - Loading data:     https://docs.snowflake.com/en/user-guide/data-load-considerations-load
--    - Warehouse sizing: https://docs.snowflake.com/en/user-guide/warehouses-considerations
--    - Compute costs:    https://docs.snowflake.com/en/user-guide/cost-understanding-compute
--    - Cost attribution: https://docs.snowflake.com/en/sql-reference/account-usage/query_attribution_history
-- =============================================================================

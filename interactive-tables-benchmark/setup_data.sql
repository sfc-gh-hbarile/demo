-- =============================================================================
-- Interactive Tables Benchmark: Data Setup
-- =============================================================================
-- This script creates sample asset management data for the benchmark.
-- Adjust the row counts, database/schema names, and column definitions
-- to match your use case.
--
-- INSTRUCTIONS:
--   1. Replace YOUR_DATABASE / YOUR_SCHEMA with your actual names
--   2. Adjust row counts (default: 100M positions, 1M accounts, 100K securities)
--   3. Run each step sequentially in a Snowflake worksheet
--   4. Update config.yaml with the table names you created
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Step 0: Create database and schema (skip if you already have them)
-- ---------------------------------------------------------------------------

-- CREATE DATABASE IF NOT EXISTS YOUR_DATABASE;
-- CREATE SCHEMA IF NOT EXISTS YOUR_DATABASE.YOUR_SCHEMA;
USE DATABASE YOUR_DATABASE;
USE SCHEMA YOUR_SCHEMA;

-- ---------------------------------------------------------------------------
-- Step 1: Create a standard warehouse for the benchmark (XS is recommended)
-- ---------------------------------------------------------------------------

CREATE WAREHOUSE IF NOT EXISTS BENCHMARK_STANDARD_WH
    WAREHOUSE_SIZE = 'XSMALL'
    AUTO_SUSPEND = 60
    AUTO_RESUME = TRUE
    COMMENT = 'Standard warehouse for Interactive Tables benchmark';

-- ---------------------------------------------------------------------------
-- Step 2: Create an interactive warehouse
-- ---------------------------------------------------------------------------
-- NOTE: Interactive warehouses require the Interactive Tables feature enabled.
-- Contact your Snowflake account team if not yet available.

CREATE WAREHOUSE IF NOT EXISTS BENCHMARK_INTERACTIVE_WH
    WAREHOUSE_TYPE = 'STANDARD'  -- Will be INTERACTIVE when feature is enabled
    WAREHOUSE_SIZE = 'XSMALL'
    AUTO_SUSPEND = 0             -- Always-on (interactive warehouses don't suspend)
    AUTO_RESUME = TRUE
    COMMENT = 'Interactive warehouse for benchmark';

-- To convert to interactive (requires feature enabled):
-- ALTER WAREHOUSE BENCHMARK_INTERACTIVE_WH SET WAREHOUSE_TYPE = 'SNOWPARK-OPTIMIZED';
-- Note: actual syntax depends on your Snowflake version. Check docs.

-- ---------------------------------------------------------------------------
-- Step 3: Securities reference data (100K rows)
-- ---------------------------------------------------------------------------

CREATE OR REPLACE TABLE SECURITIES AS
SELECT
    ROW_NUMBER() OVER (ORDER BY SEQ4()) AS security_id,
    'SEC-' || LPAD(ROW_NUMBER() OVER (ORDER BY SEQ4()), 8, '0') AS cusip,
    'Security ' || ROW_NUMBER() OVER (ORDER BY SEQ4()) AS security_name,
    CASE MOD(SEQ4(), 5)
        WHEN 0 THEN 'EQUITY'
        WHEN 1 THEN 'FIXED_INCOME'
        WHEN 2 THEN 'ALTERNATIVES'
        WHEN 3 THEN 'CASH'
        WHEN 4 THEN 'DERIVATIVES'
    END AS asset_class,
    CASE MOD(SEQ4(), 11)
        WHEN 0 THEN 'TECHNOLOGY'
        WHEN 1 THEN 'HEALTHCARE'
        WHEN 2 THEN 'FINANCIALS'
        WHEN 3 THEN 'ENERGY'
        WHEN 4 THEN 'CONSUMER'
        WHEN 5 THEN 'INDUSTRIALS'
        WHEN 6 THEN 'UTILITIES'
        WHEN 7 THEN 'REAL_ESTATE'
        WHEN 8 THEN 'MATERIALS'
        WHEN 9 THEN 'TELECOM'
        WHEN 10 THEN 'STAPLES'
    END AS sector,
    CASE MOD(SEQ4(), 3)
        WHEN 0 THEN 'USD'
        WHEN 1 THEN 'EUR'
        WHEN 2 THEN 'GBP'
    END AS currency
FROM TABLE(GENERATOR(ROWCOUNT => 100000));

-- ---------------------------------------------------------------------------
-- Step 4: Accounts (1M rows)
-- ---------------------------------------------------------------------------

CREATE OR REPLACE TABLE ACCOUNTS AS
SELECT
    ROW_NUMBER() OVER (ORDER BY SEQ4()) AS account_id,
    'ACCT-' || LPAD(ROW_NUMBER() OVER (ORDER BY SEQ4()), 10, '0') AS account_number,
    CASE MOD(SEQ4(), 4)
        WHEN 0 THEN 'INSTITUTIONAL'
        WHEN 1 THEN 'RETAIL'
        WHEN 2 THEN 'PENSION'
        WHEN 3 THEN 'ENDOWMENT'
    END AS account_type,
    CASE MOD(SEQ4(), 3)
        WHEN 0 THEN 'ACTIVE'
        WHEN 1 THEN 'ACTIVE'
        WHEN 2 THEN 'DORMANT'
    END AS status
FROM TABLE(GENERATOR(ROWCOUNT => 1000000));

-- ---------------------------------------------------------------------------
-- Step 5: Positions (100M rows) — this is the large fact table
-- ---------------------------------------------------------------------------
-- NOTE: This will take several minutes on an XS warehouse.
-- Consider using a MEDIUM warehouse for data generation, then switching back.

-- ALTER WAREHOUSE BENCHMARK_STANDARD_WH SET WAREHOUSE_SIZE = 'MEDIUM';

CREATE OR REPLACE TABLE POSITIONS AS
SELECT
    ROW_NUMBER() OVER (ORDER BY SEQ8()) AS position_id,
    UNIFORM(1, 1000000, RANDOM()) AS account_id,
    UNIFORM(1, 100000, RANDOM()) AS security_id,
    DATEADD('day', -UNIFORM(0, 90, RANDOM()), CURRENT_DATE()) AS trade_date,
    UNIFORM(1, 10000, RANDOM()) AS quantity,
    ROUND(UNIFORM(100, 1000000, RANDOM()) * 0.01, 2) AS market_value,
    ROUND(UNIFORM(80, 900000, RANDOM()) * 0.01, 2) AS cost_basis,
    0.0 AS unrealized_pnl  -- computed below
FROM TABLE(GENERATOR(ROWCOUNT => 100000000));

-- Compute unrealized P&L
UPDATE POSITIONS SET unrealized_pnl = market_value - cost_basis;

-- ---------------------------------------------------------------------------
-- Step 6: Create clustered Interactive Tables
-- ---------------------------------------------------------------------------
-- Interactive Tables are clustered for fast point lookups.
-- Cluster on the columns used in your WHERE clause.

CREATE OR REPLACE INTERACTIVE TABLE POSITIONS_INTERACTIVE
    CLUSTER BY (account_id, trade_date)
AS SELECT * FROM POSITIONS;

CREATE OR REPLACE INTERACTIVE TABLE SECURITIES_INTERACTIVE
    CLUSTER BY (security_id)
AS SELECT * FROM SECURITIES;

-- ---------------------------------------------------------------------------
-- Step 7: (Optional) Create a PAT token for automated benchmark runs
-- ---------------------------------------------------------------------------
-- PAT tokens bypass MFA, making automated testing possible.

-- ALTER USER <your_user> ADD PAT benchmark_token
--     DAYS_TO_EXPIRY = 30
--     COMMENT = 'Interactive Tables benchmark - bypasses MFA';
-- 
-- Copy the token_secret from the output and set:
--   export SNOWFLAKE_PAT_TOKEN="<token_secret>"

-- ---------------------------------------------------------------------------
-- Step 8: Verify row counts
-- ---------------------------------------------------------------------------

SELECT 'POSITIONS' AS table_name, COUNT(*) AS row_count FROM POSITIONS
UNION ALL
SELECT 'ACCOUNTS', COUNT(*) FROM ACCOUNTS
UNION ALL
SELECT 'SECURITIES', COUNT(*) FROM SECURITIES
UNION ALL
SELECT 'POSITIONS_INTERACTIVE', COUNT(*) FROM POSITIONS_INTERACTIVE
UNION ALL
SELECT 'SECURITIES_INTERACTIVE', COUNT(*) FROM SECURITIES_INTERACTIVE;

-- ---------------------------------------------------------------------------
-- Done! Now update config.yaml with:
--   - Your database/schema names
--   - The warehouse names created above
--   - The table names (POSITIONS, SECURITIES, POSITIONS_INTERACTIVE, etc.)
-- ---------------------------------------------------------------------------

-- ============================================================================
-- Pipeline Cost Optimization Demo - Generic Setup
--
-- Customer-facing, synthetic demo. Run only in a sandbox/demo account.
-- Creates PIPELINE_COST_DEMO with intentionally inefficient workloads that
-- Cortex Code can investigate and optimize.
--
-- Safety:
--   * DEMO_COST_GUARD caps demo warehouse consumption at 40 credits/day.
--   * Tasks are created suspended.
--   * Continuous execution starts only after the ALTER TASK ... RESUME lines
--     near the end are run explicitly.
--
-- Cost:
--   * Build and seed: approximately 2 credits.
--   * Active pipeline: approximately 3.5 credits/hour.
--
-- The target table is intentionally large (20M rows, approximately 6 GB) so
-- the bad MERGE produces meaningful scan, runtime, and spill telemetry.
-- ============================================================================

USE ROLE ACCOUNTADMIN;

-- 1. Cost guard
CREATE OR REPLACE RESOURCE MONITOR DEMO_COST_GUARD
  WITH CREDIT_QUOTA = 40
       FREQUENCY = DAILY
       START_TIMESTAMP = IMMEDIATELY
  TRIGGERS ON 50 PERCENT DO NOTIFY
           ON 75 PERCENT DO NOTIFY
           ON 90 PERCENT DO NOTIFY
           ON 100 PERCENT DO SUSPEND_IMMEDIATE;

-- 2. Warehouses
CREATE OR REPLACE WAREHOUSE DEMO_INGEST_WH_XS
    WAREHOUSE_SIZE = 'XSMALL'
    AUTO_SUSPEND = 300
    AUTO_RESUME = TRUE
    INITIALLY_SUSPENDED = TRUE
    STATEMENT_TIMEOUT_IN_SECONDS = 900
    RESOURCE_MONITOR = DEMO_COST_GUARD
    COMMENT = 'DEMO - synthetic ingestion tier X-Small';

CREATE OR REPLACE WAREHOUSE DEMO_INGEST_WH_S
    WAREHOUSE_SIZE = 'SMALL'
    AUTO_SUSPEND = 300
    AUTO_RESUME = TRUE
    INITIALLY_SUSPENDED = TRUE
    STATEMENT_TIMEOUT_IN_SECONDS = 900
    RESOURCE_MONITOR = DEMO_COST_GUARD
    COMMENT = 'DEMO - synthetic ingestion tier Small';

CREATE OR REPLACE WAREHOUSE DEMO_REPORTING_WH
    WAREHOUSE_SIZE = 'XSMALL'
    AUTO_SUSPEND = 300
    AUTO_RESUME = TRUE
    INITIALLY_SUSPENDED = TRUE
    STATEMENT_TIMEOUT_IN_SECONDS = 900
    RESOURCE_MONITOR = DEMO_COST_GUARD
    COMMENT = 'DEMO - synthetic reporting tier';

CREATE OR REPLACE WAREHOUSE DEMO_BUILD_WH
    WAREHOUSE_SIZE = 'LARGE'
    AUTO_SUSPEND = 60
    AUTO_RESUME = TRUE
    INITIALLY_SUSPENDED = TRUE
    STATEMENT_TIMEOUT_IN_SECONDS = 1800
    RESOURCE_MONITOR = DEMO_COST_GUARD
    COMMENT = 'DEMO - temporary build warehouse';

-- 3. Isolated database and schema
CREATE OR REPLACE DATABASE PIPELINE_COST_DEMO
    COMMENT = 'DEMO - synthetic inefficient pipeline for Cortex Code';
CREATE OR REPLACE SCHEMA PIPELINE_COST_DEMO.INGESTION;

USE WAREHOUSE DEMO_BUILD_WH;
USE DATABASE PIPELINE_COST_DEMO;
USE SCHEMA INGESTION;

-- 4. Deliberately unclustered target table
CREATE OR REPLACE TABLE TRANSACTION_LEDGER (
    TXN_KEY        STRING,
    ENTITY_ID      STRING,
    PRODUCT_ID     STRING,
    REGION         STRING,
    QUANTITY       NUMBER(18,4),
    AMOUNT         NUMBER(18,2),
    TXN_STATUS     STRING,
    VERSION_NO     NUMBER,
    LAST_UPDATED   TIMESTAMP_NTZ,
    PAYLOAD        STRING
)
COMMENT = 'DEMO - synthetic ledger with deliberately unclustered merge key';

-- MD5-derived keys scatter across micro-partitions. The wide payload makes the
-- intentionally bad window operation memory-intensive.
INSERT INTO TRANSACTION_LEDGER
SELECT
    'TXN-' || MD5(seq::STRING),
    'ENT-' || LPAD(UNIFORM(1, 200000, RANDOM())::STRING, 7, '0'),
    'PRD-' || LPAD(UNIFORM(1, 50000, RANDOM())::STRING, 6, '0'),
    ARRAY_CONSTRUCT('NA-EAST','NA-WEST','UK','DE','FR','JP','HK','AU','SG','BR')
        [UNIFORM(0, 9, RANDOM())]::STRING,
    UNIFORM(1, 500000, RANDOM()),
    UNIFORM(1000, 99999999, RANDOM()) / 100,
    ARRAY_CONSTRUCT('COMPLETE','PENDING','FAILED','PARTIAL')
        [UNIFORM(0, 3, RANDOM())]::STRING,
    1,
    DATEADD(second, -UNIFORM(0, 7776000, RANDOM()), CURRENT_TIMESTAMP())::TIMESTAMP_NTZ,
    RANDSTR(400, RANDOM())
FROM (SELECT SEQ8() AS seq FROM TABLE(GENERATOR(ROWCOUNT => 20000000)));

-- 5. Staging feed and application run log
CREATE OR REPLACE TABLE TRANSACTION_FEED_STAGING (
    PIPELINE_NAME  STRING,
    TXN_KEY        STRING,
    ENTITY_ID      STRING,
    PRODUCT_ID     STRING,
    REGION         STRING,
    QUANTITY       NUMBER(18,4),
    AMOUNT         NUMBER(18,2),
    TXN_STATUS     STRING,
    LAST_UPDATED   TIMESTAMP_NTZ,
    PAYLOAD        STRING,
    BATCH_ID       STRING
)
COMMENT = 'DEMO - synthetic feed batches isolated by pipeline';

CREATE OR REPLACE TABLE PIPELINE_RUN_LOG (
    RUN_ID         STRING,
    PIPELINE_NAME  STRING,
    STARTED_AT     TIMESTAMP_NTZ,
    ENDED_AT       TIMESTAMP_NTZ,
    ROWS_IN_BATCH  NUMBER,
    STATUS         STRING,
    MESSAGE        STRING
)
COMMENT = 'DEMO - application-level pipeline run log';

-- 6. Feed generator. Each pipeline has its own staging rows so the two merge
-- tasks can run concurrently without truncating one another's input.
CREATE OR REPLACE PROCEDURE SP_GENERATE_FEED_BATCH(
    P_BATCH_ROWS NUMBER,
    P_PIPELINE_NAME STRING
)
RETURNS STRING
LANGUAGE SQL
AS
$$
BEGIN
    DELETE FROM TRANSACTION_FEED_STAGING
    WHERE PIPELINE_NAME = :P_PIPELINE_NAME;

    INSERT INTO TRANSACTION_FEED_STAGING
    WITH RAW_BATCH AS (
        SELECT
            :P_PIPELINE_NAME AS PIPELINE_NAME,
            'TXN-' || MD5(UNIFORM(1, 24000000, RANDOM())::STRING) AS TXN_KEY,
            'ENT-' || LPAD(UNIFORM(1, 200000, RANDOM())::STRING, 7, '0') AS ENTITY_ID,
            'PRD-' || LPAD(UNIFORM(1, 50000, RANDOM())::STRING, 6, '0') AS PRODUCT_ID,
            ARRAY_CONSTRUCT('NA-EAST','NA-WEST','UK','DE','FR','JP','HK','AU','SG','BR')
                [UNIFORM(0, 9, RANDOM())]::STRING AS REGION,
            UNIFORM(1, 500000, RANDOM()) AS QUANTITY,
            UNIFORM(1000, 99999999, RANDOM()) / 100 AS AMOUNT,
            ARRAY_CONSTRUCT('COMPLETE','PENDING','FAILED','PARTIAL')
                [UNIFORM(0, 3, RANDOM())]::STRING AS TXN_STATUS,
            CURRENT_TIMESTAMP()::TIMESTAMP_NTZ AS LAST_UPDATED,
            RANDSTR(400, RANDOM()) AS PAYLOAD,
            UUID_STRING() AS BATCH_ID,
            SEQ8() AS SEQ
        FROM TABLE(GENERATOR(ROWCOUNT => 5000))
    )
    SELECT PIPELINE_NAME, TXN_KEY, ENTITY_ID, PRODUCT_ID, REGION, QUANTITY,
           AMOUNT, TXN_STATUS, LAST_UPDATED, PAYLOAD, BATCH_ID
    FROM RAW_BATCH
    QUALIFY ROW_NUMBER() OVER (PARTITION BY TXN_KEY ORDER BY SEQ) = 1;

    RETURN 'feed batch generated for ' || :P_PIPELINE_NAME;
END;
$$;

-- 7. Deliberately inefficient MERGE procedure
--
-- The full-table LAST_VALUE/ROW_NUMBER pass runs on every execution even though
-- each batch contains only 5,000 rows. The join key is unclustered, so pruning
-- is poor. The procedure is scheduled regardless of whether data arrived.
CREATE OR REPLACE PROCEDURE SP_MERGE_TRANSACTIONS(P_PIPELINE_NAME STRING)
RETURNS STRING
LANGUAGE SQL
AS
$$
DECLARE
    v_run_id   STRING DEFAULT UUID_STRING();
    v_started  TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()::TIMESTAMP_NTZ;
    v_rows     NUMBER DEFAULT 0;
BEGIN
    CALL SP_GENERATE_FEED_BATCH(5000, :P_PIPELINE_NAME);

    SELECT COUNT(*) INTO :v_rows
    FROM TRANSACTION_FEED_STAGING
    WHERE PIPELINE_NAME = :P_PIPELINE_NAME;

    MERGE INTO TRANSACTION_LEDGER AS tgt
    USING (
        SELECT
            s.TXN_KEY, s.ENTITY_ID, s.PRODUCT_ID, s.REGION,
            s.QUANTITY, s.AMOUNT, s.TXN_STATUS, s.LAST_UPDATED,
            COALESCE(d.PRIOR_PAYLOAD, s.PAYLOAD) AS PAYLOAD,
            COALESCE(d.VERSION_NO, 0) + 1 AS NEXT_VERSION
        FROM TRANSACTION_FEED_STAGING s
        LEFT JOIN (
            SELECT TXN_KEY, VERSION_NO,
                   LAST_VALUE(PAYLOAD) OVER (
                       PARTITION BY TXN_KEY
                       ORDER BY LAST_UPDATED
                       ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                   ) AS PRIOR_PAYLOAD,
                   ROW_NUMBER() OVER (
                       PARTITION BY TXN_KEY
                       ORDER BY LAST_UPDATED DESC
                   ) AS RN
            FROM TRANSACTION_LEDGER
        ) d
          ON d.TXN_KEY = s.TXN_KEY
         AND d.RN = 1
        WHERE s.PIPELINE_NAME = :P_PIPELINE_NAME
    ) AS src
      ON tgt.TXN_KEY = src.TXN_KEY
    WHEN MATCHED THEN UPDATE SET
        tgt.QUANTITY     = src.QUANTITY,
        tgt.AMOUNT       = src.AMOUNT,
        tgt.TXN_STATUS   = src.TXN_STATUS,
        tgt.VERSION_NO   = src.NEXT_VERSION,
        tgt.LAST_UPDATED = src.LAST_UPDATED,
        tgt.PAYLOAD      = src.PAYLOAD
    WHEN NOT MATCHED THEN INSERT
        (TXN_KEY, ENTITY_ID, PRODUCT_ID, REGION, QUANTITY,
         AMOUNT, TXN_STATUS, VERSION_NO, LAST_UPDATED, PAYLOAD)
    VALUES
        (src.TXN_KEY, src.ENTITY_ID, src.PRODUCT_ID, src.REGION, src.QUANTITY,
         src.AMOUNT, src.TXN_STATUS, 1, src.LAST_UPDATED, src.PAYLOAD);

    INSERT INTO PIPELINE_RUN_LOG
        (RUN_ID, PIPELINE_NAME, STARTED_AT, ENDED_AT, ROWS_IN_BATCH, STATUS, MESSAGE)
    SELECT :v_run_id, :P_PIPELINE_NAME, :v_started,
           CURRENT_TIMESTAMP()::TIMESTAMP_NTZ, :v_rows, 'SUCCESS', NULL;

    RETURN 'merged batch of ' || :v_rows || ' rows';
END;
$$;

-- 8. Fixed-cadence reporting refresh
CREATE OR REPLACE PROCEDURE SP_REFRESH_LEDGER_SUMMARY()
RETURNS STRING
LANGUAGE SQL
AS
$$
BEGIN
    CREATE OR REPLACE TABLE LEDGER_SUMMARY AS
    SELECT
        ENTITY_ID,
        REGION,
        COUNT(*) AS TXN_COUNT,
        SUM(AMOUNT) AS TOTAL_AMOUNT,
        SUM(CASE WHEN TXN_STATUS = 'FAILED' THEN AMOUNT ELSE 0 END) AS AMOUNT_AT_RISK,
        MAX(PAYLOAD) AS LAST_PAYLOAD
    FROM TRANSACTION_LEDGER
    GROUP BY ENTITY_ID, REGION
    ORDER BY TOTAL_AMOUNT DESC;

    RETURN 'summary refreshed';
END;
$$;

-- 9. Intermittently failing stored-procedure task
CREATE OR REPLACE PROCEDURE SP_VARIANT_ENRICHMENT()
RETURNS STRING
LANGUAGE SQL
AS
$$
DECLARE
    SIM_FAILURE EXCEPTION (-20001, 'SQL execution internal error: processing aborted in enrichment step');
    v_roll NUMBER;
BEGIN
    SELECT UNIFORM(1, 100, RANDOM()) INTO :v_roll;

    INSERT INTO PIPELINE_RUN_LOG
        (RUN_ID, PIPELINE_NAME, STARTED_AT, ENDED_AT, ROWS_IN_BATCH, STATUS, MESSAGE)
    SELECT UUID_STRING(), 'T_VARIANT_ENRICHMENT', CURRENT_TIMESTAMP()::TIMESTAMP_NTZ,
           NULL, NULL,
           CASE WHEN :v_roll <= 35 THEN 'FAILED' ELSE 'SUCCESS' END,
           'roll=' || :v_roll;

    IF (:v_roll <= 35) THEN
        RAISE SIM_FAILURE;
    END IF;

    RETURN 'enrichment completed';
END;
$$;

-- 10. Tasks are created suspended by default.
CREATE OR REPLACE TASK T_INGEST_MERGE_XS
    WAREHOUSE = DEMO_INGEST_WH_XS
    SCHEDULE = '3 MINUTE'
    COMMENT = 'DEMO - fixed-cadence MERGE on X-Small, no change predicate'
AS CALL PIPELINE_COST_DEMO.INGESTION.SP_MERGE_TRANSACTIONS('INGEST_XS');

CREATE OR REPLACE TASK T_INGEST_MERGE_S
    WAREHOUSE = DEMO_INGEST_WH_S
    SCHEDULE = '1 MINUTE'
    COMMENT = 'DEMO - identical work on Small, simulating a resize'
AS CALL PIPELINE_COST_DEMO.INGESTION.SP_MERGE_TRANSACTIONS('INGEST_S');

CREATE OR REPLACE TASK T_REPORTING_REFRESH
    WAREHOUSE = DEMO_REPORTING_WH
    SCHEDULE = '5 MINUTE'
    COMMENT = 'DEMO - full-table reporting refresh on a fixed cadence'
AS CALL PIPELINE_COST_DEMO.INGESTION.SP_REFRESH_LEDGER_SUMMARY();

CREATE OR REPLACE TASK T_VARIANT_ENRICHMENT
    WAREHOUSE = DEMO_REPORTING_WH
    SCHEDULE = '2 MINUTE'
    COMMENT = 'DEMO - intermittent stored-procedure failure without auto-retry'
AS CALL PIPELINE_COST_DEMO.INGESTION.SP_VARIANT_ENRICHMENT();

-- 11. Seed representative telemetry without starting continuous execution.
-- These run asynchronously on the task-assigned warehouses.
EXECUTE TASK T_INGEST_MERGE_XS;
EXECUTE TASK T_INGEST_MERGE_S;
EXECUTE TASK T_REPORTING_REFRESH;

-- The variant task is intentionally failure-prone. Let it run after activation
-- so the expected task failure appears in TASK_HISTORY during the demo.

-- 12. Drop the build warehouse after switching away from it.
USE WAREHOUSE DEMO_REPORTING_WH;
DROP WAREHOUSE IF EXISTS DEMO_BUILD_WH;

USE DATABASE PIPELINE_COST_DEMO;
USE SCHEMA INGESTION;

-- 13. Confirm setup. Tasks should be SUSPENDED.
SHOW TASKS IN SCHEMA PIPELINE_COST_DEMO.INGESTION;

SELECT TABLE_NAME, ROW_COUNT, ROUND(BYTES / POWER(1024, 3), 2) AS GB
FROM PIPELINE_COST_DEMO.INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = 'INGESTION'
ORDER BY BYTES DESC NULLS LAST;

-- 14. Start continuous execution only when ready. Run explicitly:
-- ALTER TASK T_INGEST_MERGE_XS    RESUME;
-- ALTER TASK T_INGEST_MERGE_S     RESUME;
-- ALTER TASK T_REPORTING_REFRESH  RESUME;
-- ALTER TASK T_VARIANT_ENRICHMENT RESUME;

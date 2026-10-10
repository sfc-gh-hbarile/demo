-- =====================================================================
-- 05 - Stored procedures used as agent custom tools
--   RUN_SCENARIO            -> agent tool run_scenario
--   SUBMIT_REVIEW_PACKAGE   -> agent tool submit_review_package (creates PENDING_APPROVAL only)
--   APPROVE_REVIEW_PACKAGE  -> human-only step, NOT exposed to the agent
-- =====================================================================
USE ROLE FPA_DEMO_ROLE; USE WAREHOUSE FPA_DEMO_WH;

CREATE OR REPLACE PROCEDURE FPA_DEMO.FPA.RUN_SCENARIO(
  VOLUME_CHANGE_PCT FLOAT, PRICE_CHANGE_PCT FLOAT, HIRING_DELAY_QUARTERS NUMBER, ENTITY_REGION VARCHAR)
RETURNS VARIANT
LANGUAGE SQL
COMMENT = 'What-if on the current Oct-Dec forecast: volume %, price %, and hiring delay in quarters. ENTITY_REGION is ALL, North America, EMEA, or APAC.'
AS
$$
DECLARE
  result VARIANT;
BEGIN
  WITH base AS (
    SELECT f.forecast_version, f.period_month, f.revenue_fcst, f.cogs_fcst, f.opex_fcst, f.hiring_cost_fcst,
           f.revenue_plan, f.cogs_plan, f.opex_plan,
           DATEDIFF(month, MIN(f.period_month) OVER (), f.period_month) AS month_idx
    FROM FPA_DEMO.FPA.FACT_FORECAST f
    JOIN FPA_DEMO.FPA.DIM_ENTITY e ON e.entity_id = f.entity_id
    WHERE f.forecast_version = (SELECT forecast_version FROM FPA_DEMO.FPA.FACT_FORECAST ORDER BY version_date DESC LIMIT 1)
      AND (UPPER(:ENTITY_REGION) = 'ALL' OR UPPER(e.region) = UPPER(:ENTITY_REGION))
  ),
  calc AS (
    SELECT forecast_version, revenue_fcst, cogs_fcst, opex_fcst, revenue_plan, cogs_plan, opex_plan,
      revenue_fcst * (1 + :VOLUME_CHANGE_PCT/100) * (1 + :PRICE_CHANGE_PCT/100) AS revenue_s,
      cogs_fcst * (1 + :VOLUME_CHANGE_PCT/100) AS cogs_s,
      opex_fcst - IFF(month_idx < :HIRING_DELAY_QUARTERS * 3, hiring_cost_fcst, 0) AS opex_s
    FROM base
  )
  SELECT OBJECT_CONSTRUCT(
    'forecast_version', MAX(forecast_version),
    'region', :ENTITY_REGION,
    'inputs', OBJECT_CONSTRUCT('volume_change_pct', :VOLUME_CHANGE_PCT, 'price_change_pct', :PRICE_CHANGE_PCT, 'hiring_delay_quarters', :HIRING_DELAY_QUARTERS),
    'baseline', OBJECT_CONSTRUCT('revenue', ROUND(SUM(revenue_fcst)), 'gross_margin_pct', ROUND(100*(1-SUM(cogs_fcst)/SUM(revenue_fcst)),1),
                 'opex', ROUND(SUM(opex_fcst)), 'operating_income', ROUND(SUM(revenue_fcst - cogs_fcst - opex_fcst))),
    'scenario', OBJECT_CONSTRUCT('revenue', ROUND(SUM(revenue_s)), 'gross_margin_pct', ROUND(100*(1-SUM(cogs_s)/SUM(revenue_s)),1),
                 'opex', ROUND(SUM(opex_s)), 'operating_income', ROUND(SUM(revenue_s - cogs_s - opex_s))),
    'change_vs_baseline_operating_income', ROUND(SUM(revenue_s - cogs_s - opex_s) - SUM(revenue_fcst - cogs_fcst - opex_fcst)),
    'plan_operating_income', ROUND(SUM(revenue_plan - cogs_plan - opex_plan)),
    'assumptions', ARRAY_CONSTRUCT(
      'Baseline is the latest forecast version for Oct-Dec 2026',
      'Revenue moves with volume and price; cost of goods moves with volume only',
      'A hiring delay removes planned hiring cost (6 percent of opex) for the first 3 months per quarter delayed',
      'Illustrative driver logic; finance should confirm before using externally')
  ) INTO :result
  FROM calc;
  RETURN result;
END;
$$;

CREATE OR REPLACE PROCEDURE FPA_DEMO.FPA.SUBMIT_REVIEW_PACKAGE(PERIOD VARCHAR, SUMMARY VARCHAR)
RETURNS VARIANT
LANGUAGE SQL
COMMENT = 'Creates a forecast review package in PENDING_APPROVAL status and queues held notifications for each regional finance owner. Nothing is sent until a human approves.'
AS
$$
DECLARE
  pkg_id VARCHAR DEFAULT 'RP-' || TO_VARCHAR(CURRENT_TIMESTAMP(), 'YYYYMMDDHH24MISS');
  n NUMBER;
BEGIN
  INSERT INTO FPA_DEMO.FPA.REVIEW_PACKAGE_LOG (package_id, created_at, period, summary, status, created_by)
    SELECT :pkg_id, CURRENT_TIMESTAMP(), :PERIOD, :SUMMARY, 'PENDING_APPROVAL', CURRENT_USER();
  INSERT INTO FPA_DEMO.FPA.NOTIFICATION_OUTBOX (package_id, recipient_name, recipient_email, region, message, status)
    SELECT :pkg_id, finance_owner_name, finance_owner_email, region,
           'Forecast review package for ' || :PERIOD || ' is ready for your review once FP&A approves it.', 'HELD_UNTIL_APPROVED'
    FROM FPA_DEMO.FPA.DIM_ENTITY;
  SELECT COUNT(*) INTO :n FROM FPA_DEMO.FPA.NOTIFICATION_OUTBOX WHERE package_id = :pkg_id;
  RETURN OBJECT_CONSTRUCT('package_id', :pkg_id, 'status', 'PENDING_APPROVAL', 'notifications_queued', :n,
    'next_step', 'An FP&A approver must run APPROVE_REVIEW_PACKAGE before notifications are released');
END;
$$;

CREATE OR REPLACE PROCEDURE FPA_DEMO.FPA.APPROVE_REVIEW_PACKAGE(PACKAGE_ID VARCHAR)
RETURNS VARIANT
LANGUAGE SQL
COMMENT = 'Human approval step. NOT exposed to the agent. Releases held notifications.'
AS
$$
BEGIN
  UPDATE FPA_DEMO.FPA.REVIEW_PACKAGE_LOG SET status = 'APPROVED', approved_by = CURRENT_USER(), approved_at = CURRENT_TIMESTAMP()
    WHERE package_id = :PACKAGE_ID;
  UPDATE FPA_DEMO.FPA.NOTIFICATION_OUTBOX SET status = 'READY_TO_SEND' WHERE package_id = :PACKAGE_ID;
  RETURN OBJECT_CONSTRUCT('package_id', :PACKAGE_ID, 'status', 'APPROVED');
END;
$$;

-- Validation 1: expect baseline OI ~3,449,333 vs plan ~3,696,454; scenario ~3,378,021 (-71K)
CALL FPA_DEMO.FPA.RUN_SCENARIO(-8, 2, 1, 'ALL');

-- Validation 2: submit -> approve -> check -> clean up (leaves no test rows)
CALL FPA_DEMO.FPA.SUBMIT_REVIEW_PACKAGE('TEST', 'test package');
SET pkg = (SELECT MAX(package_id) FROM FPA_DEMO.FPA.REVIEW_PACKAGE_LOG);
CALL FPA_DEMO.FPA.APPROVE_REVIEW_PACKAGE($pkg);
SELECT (SELECT status FROM FPA_DEMO.FPA.REVIEW_PACKAGE_LOG WHERE package_id = $pkg) AS pkg_status,      -- APPROVED
       (SELECT COUNT(*) FROM FPA_DEMO.FPA.NOTIFICATION_OUTBOX WHERE package_id = $pkg AND status = 'READY_TO_SEND') AS ready_notes; -- 3
DELETE FROM FPA_DEMO.FPA.REVIEW_PACKAGE_LOG;
DELETE FROM FPA_DEMO.FPA.NOTIFICATION_OUTBOX;

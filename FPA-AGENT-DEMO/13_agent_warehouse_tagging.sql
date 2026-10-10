-- =====================================================================
-- 13 - Accurate cost attribution: dedicated agent warehouse + tagged runs
--
-- How cost is attributed:
--  * Agent token credits: exact per request (CORTEX_AGENT_USAGE_HISTORY).
--  * Warehouse compute behind the agent: every query an agent tool runs is
--    tagged by Snowflake with QUERY_TAG = 'cortex-agent-<request_id>'.
--    QUERY_ATTRIBUTION_HISTORY gives exact compute credits per query.
--  * Full warehouse cost incl. idle and 60s resume minimums: the agent's tools
--    run on the dedicated FPA_AGENT_WH, so its metering is agent-only.
--  * Runs: START_COST_RUN / END_COST_RUN record who ran what, when, and set a
--    session QUERY_TAG so harness/demo queries are labelled and excluded.
-- =====================================================================

-- 1. Dedicated warehouse for agent tools (ACCOUNTADMIN for the monitor link)
USE ROLE ACCOUNTADMIN;
CREATE WAREHOUSE IF NOT EXISTS FPA_AGENT_WH
  WAREHOUSE_SIZE = 'XSMALL' AUTO_SUSPEND = 60 AUTO_RESUME = TRUE INITIALLY_SUSPENDED = TRUE
  COMMENT = 'Dedicated to FPA_AGENT tool queries; its metering = warehouse cost behind the agent';
ALTER WAREHOUSE FPA_AGENT_WH SET RESOURCE_MONITOR = FPA_DEMO_RM;
GRANT OWNERSHIP ON WAREHOUSE FPA_AGENT_WH TO ROLE FPA_DEMO_ROLE COPY CURRENT GRANTS;
-- Agents need the user's default warehouse; point the demo user at the agent warehouse
ALTER USER FPA_DEMO_USER SET DEFAULT_WAREHOUSE = FPA_AGENT_WH;

-- 2. Re-run 07_agent.sql (its tool_resources now use FPA_AGENT_WH)

-- 3. Tagged runs
USE ROLE FPA_DEMO_ROLE; USE WAREHOUSE FPA_DEMO_WH; USE SCHEMA FPA_DEMO.FPA;

CREATE TABLE IF NOT EXISTS FPA_DEMO.FPA.COST_RUNS (
  run_id VARCHAR, run_label VARCHAR, run_type VARCHAR,   -- LOAD_TEST or DEMO_SESSION
  user_name VARCHAR, start_ts TIMESTAMP_LTZ, end_ts TIMESTAMP_LTZ, query_tag VARCHAR);

CREATE OR REPLACE PROCEDURE FPA_DEMO.FPA.START_COST_RUN(RUN_LABEL VARCHAR, RUN_TYPE VARCHAR)
RETURNS VARCHAR
LANGUAGE SQL
COMMENT = 'Starts a tagged cost run for the current user and sets the session QUERY_TAG. Returns run_id.'
EXECUTE AS CALLER
AS
$$
DECLARE
  rid VARCHAR DEFAULT 'RUN-' || TO_VARCHAR(CURRENT_TIMESTAMP(), 'YYYYMMDDHH24MISSFF3');
  tag VARCHAR;
BEGIN
  tag := TO_VARCHAR(OBJECT_CONSTRUCT('app', 'fpa_cost_run', 'run_id', rid, 'label', RUN_LABEL, 'type', RUN_TYPE));
  INSERT INTO FPA_DEMO.FPA.COST_RUNS (run_id, run_label, run_type, user_name, start_ts, query_tag)
    SELECT :rid, :RUN_LABEL, UPPER(:RUN_TYPE), CURRENT_USER(), CURRENT_TIMESTAMP(), :tag;
  EXECUTE IMMEDIATE 'ALTER SESSION SET QUERY_TAG = ''' || REPLACE(tag, '''', '''''') || '''';
  RETURN rid;
END;
$$;

CREATE OR REPLACE PROCEDURE FPA_DEMO.FPA.END_COST_RUN(RUN_ID VARCHAR)
RETURNS VARCHAR
LANGUAGE SQL
COMMENT = 'Closes a tagged cost run and clears the session QUERY_TAG.'
EXECUTE AS CALLER
AS
$$
BEGIN
  UPDATE FPA_DEMO.FPA.COST_RUNS SET end_ts = CURRENT_TIMESTAMP() WHERE run_id = :RUN_ID AND end_ts IS NULL;
  ALTER SESSION UNSET QUERY_TAG;
  RETURN RUN_ID;
END;
$$;

-- Live demo usage (Snowsight worksheet or SQL session):
--   CALL FPA_DEMO.FPA.START_COST_RUN('customer_demo_acme', 'DEMO_SESSION');   -- note the run_id
--   ... ask the agent questions (Snowsight agent playground or DATA_AGENT_RUN) as the same user ...
--   CALL FPA_DEMO.FPA.END_COST_RUN('<run_id>');
-- Only agent requests by that user inside the run window are counted for that run.

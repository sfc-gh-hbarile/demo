-- =====================================================================
-- 10 - Cost model views: per-request costs, load-test join, calibration
-- Run as FPA_DEMO_ROLE (reads ACCOUNT_USAGE via SNOWFLAKE.USAGE_VIEWER).
-- ACCOUNT_USAGE lags by up to a few hours.
-- =====================================================================
USE ROLE FPA_DEMO_ROLE; USE WAREHOUSE FPA_DEMO_WH; USE SCHEMA FPA_DEMO.FPA;

-- One row per agent request x service x model, with tokens and credits split by
-- input / cache read / cache write / output.
-- CREDITS_GRANULAR shape: [ { <request_id>: { <service>: { <model>: {input, cache_read_input,
--                            cache_write_input, output} }, start_time } } ]
CREATE OR REPLACE VIEW V_AGENT_REQUEST_COSTS AS
SELECT
  h.request_id, h.start_time, h.end_time, h.user_name,
  h.agent_database_name || '.' || h.agent_schema_name || '.' || h.agent_name AS agent_fqn,
  h.metadata:interaction_interface::STRING AS interface,
  h.metadata:role_name::STRING AS role_name,
  f3.key AS service_type,
  f4.key AS model,
  tk:input::NUMBER             AS input_tokens,
  tk:cache_read_input::NUMBER  AS cache_read_tokens,
  tk:cache_write_input::NUMBER AS cache_write_tokens,
  tk:output::NUMBER            AS output_tokens,
  f4.value:input::FLOAT             AS input_credits,
  f4.value:cache_read_input::FLOAT  AS cache_read_credits,
  f4.value:cache_write_input::FLOAT AS cache_write_credits,
  f4.value:output::FLOAT            AS output_credits,
  f4.value:input::FLOAT + f4.value:cache_read_input::FLOAT
    + f4.value:cache_write_input::FLOAT + f4.value:output::FLOAT AS token_credits,
  h.token_credits AS request_token_credits,
  -- SQL credits are reported per request; attach them to one row only to avoid double counting
  IFF(ROW_NUMBER() OVER (PARTITION BY h.request_id ORDER BY f3.key, f4.key) = 1,
      COALESCE(h.metadata:sql_query_credits::FLOAT, 0), 0) AS sql_query_credits
FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AGENT_USAGE_HISTORY h,
  LATERAL FLATTEN(h.credits_granular) f1,
  LATERAL FLATTEN(f1.value) f2,
  LATERAL FLATTEN(f2.value) f3,
  LATERAL FLATTEN(f3.value) f4,
  LATERAL (SELECT GET(GET(GET(GET(h.tokens_granular, f1.index), f2.key), f3.key), f4.key) AS tk)
WHERE h.agent_name = 'FPA_AGENT'
  AND h.agent_database_name = 'FPA_DEMO'
  AND IS_OBJECT(f3.value);              -- skip the start_time sibling key

-- One row per request (what most cost questions need)
CREATE OR REPLACE VIEW V_AGENT_REQUESTS AS
SELECT request_id, MIN(start_time) AS start_time, MAX(end_time) AS end_time, MAX(user_name) AS user_name,
       MAX(interface) AS interface, LISTAGG(DISTINCT model, ',') AS models,
       SUM(input_tokens) AS input_tokens, SUM(cache_read_tokens) AS cache_read_tokens,
       SUM(cache_write_tokens) AS cache_write_tokens, SUM(output_tokens) AS output_tokens,
       SUM(cache_read_credits) AS cache_read_credits, SUM(cache_write_credits) AS cache_write_credits,
       SUM(input_credits + output_credits) AS io_credits,
       SUM(token_credits) AS token_credits, SUM(sql_query_credits) AS sql_query_credits
FROM V_AGENT_REQUEST_COSTS GROUP BY request_id;

-- Load-test log written by RUN_AGENT_LOAD_TEST (script 11)
CREATE TABLE IF NOT EXISTS AGENT_LOAD_TEST_LOG (
  run_id VARCHAR, run_label VARCHAR, seq NUMBER, question_id NUMBER, question VARCHAR,
  attempt VARCHAR,            -- FIRST = first time asked in this run, REPEAT = asked again
  user_name VARCHAR, start_ts TIMESTAMP_LTZ, end_ts TIMESTAMP_LTZ, ok BOOLEAN, response_snippet VARCHAR);

-- Join each logged call to its usage row: same user, request starts inside the call
-- window, first match only (calls run back to back, so wider windows double count)
CREATE OR REPLACE VIEW V_LOAD_TEST_COSTS AS
SELECT l.run_id, l.run_label, l.seq, l.question_id, l.question, l.attempt, l.ok,
       r.request_id, r.start_time, r.token_credits, r.sql_query_credits,
       r.cache_read_credits, r.cache_write_credits, r.io_credits,
       r.cache_read_tokens, r.cache_write_tokens, r.input_tokens, r.output_tokens
FROM AGENT_LOAD_TEST_LOG l
LEFT JOIN V_AGENT_REQUESTS r
  ON r.user_name = l.user_name
 AND r.start_time >= DATEADD(second, -2, l.start_ts)
 AND r.start_time <  l.end_ts
QUALIFY ROW_NUMBER() OVER (PARTITION BY l.run_id, l.seq ORDER BY r.start_time) = 1;

-- Calibration numbers used by the cost estimator app
CREATE OR REPLACE VIEW V_COST_CALIBRATION AS
WITH all_req AS (
  SELECT 'ALL_REQUESTS' AS segment, COUNT(*) AS requests,
         AVG(token_credits) AS avg_token_credits, AVG(sql_query_credits) AS avg_sql_credits,
         SUM(cache_read_credits) / NULLIF(SUM(token_credits), 0) AS cache_read_share,
         SUM(cache_write_credits) / NULLIF(SUM(token_credits), 0) AS cache_write_share,
         SUM(cache_read_tokens) / NULLIF(SUM(cache_read_tokens + cache_write_tokens + input_tokens), 0) AS cache_hit_ratio_tokens
  FROM V_AGENT_REQUESTS),
lt AS (
  SELECT 'LOAD_TEST_' || attempt AS segment, COUNT(request_id) AS requests,
         AVG(token_credits), AVG(sql_query_credits),
         SUM(cache_read_credits) / NULLIF(SUM(token_credits), 0),
         SUM(cache_write_credits) / NULLIF(SUM(token_credits), 0),
         SUM(cache_read_tokens) / NULLIF(SUM(cache_read_tokens + cache_write_tokens + input_tokens), 0)
  FROM V_LOAD_TEST_COSTS WHERE request_id IS NOT NULL GROUP BY attempt)
SELECT * FROM all_req UNION ALL SELECT * FROM lt;

-- Validation: granular credits must reconcile with token_credits for every request
SELECT COUNT(*) AS requests,
       SUM(IFF(ABS(r.token_credits - h.token_credits) < 0.000001, 1, 0)) AS reconciled
FROM V_AGENT_REQUESTS r
JOIN SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AGENT_USAGE_HISTORY h USING (request_id);

SELECT * FROM V_COST_CALIBRATION;

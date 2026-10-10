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

-- =====================================================================
-- Exact attribution (see 13_agent_warehouse_tagging.sql)
-- =====================================================================

-- Every query an agent tool ran. Snowflake tags them with the agent request_id:
--   'cortex-agent-<request_id>'            (Analyst SQL, skill LISTs, procedure CALLs via API/SQL)
--   'snowflake-intelligence-<request_id>'  (procedure CALLs from the Snowsight agent playground / CoWork)
-- Statements inside a stored procedure are NOT tagged; QUERY_ATTRIBUTION_HISTORY links them to the
-- tagged CALL through ROOT_QUERY_ID, so compute is rolled up to the tagged root query.
-- Attributed compute excludes warehouse idle time (see metered_agent_wh in V_RUN_COSTS).
CREATE OR REPLACE VIEW V_AGENT_TOOL_QUERIES AS
WITH roots AS (
  SELECT REGEXP_SUBSTR(q.query_tag, '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}') AS request_id,
         q.query_id, q.start_time, q.user_name, q.role_name, q.warehouse_name, q.warehouse_size,
         q.query_type, q.execution_status, q.total_elapsed_time / 1000 AS elapsed_s, q.execution_time / 1000 AS execution_s
  FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
  WHERE (q.query_tag LIKE 'cortex-agent-%' OR q.query_tag LIKE 'snowflake-intelligence-%')
    AND q.start_time >= '2026-10-01'),
attr AS (
  SELECT COALESCE(a.root_query_id, a.query_id) AS root_id,
         SUM(a.credits_attributed_compute) AS compute_credits,
         SUM(COALESCE(a.credits_used_query_acceleration, 0)) AS qas_credits,
         COUNT(*) AS attributed_queries
  FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_ATTRIBUTION_HISTORY a
  WHERE a.start_time >= '2026-10-01'
  GROUP BY 1)
SELECT r.*, COALESCE(attr.compute_credits, 0) AS compute_credits, COALESCE(attr.qas_credits, 0) AS qas_credits,
       COALESCE(attr.attributed_queries, 0) AS attributed_queries
FROM roots r LEFT JOIN attr ON attr.root_id = r.query_id;

-- One row per agent question: exact token credits + exact warehouse compute of its tool queries,
-- scoped to a tagged run (COST_RUNS) by user and time window.
CREATE OR REPLACE VIEW V_AGENT_QUESTION_COSTS AS
WITH tq AS (
  SELECT request_id, COUNT(*) AS tool_queries, SUM(execution_s) AS tool_execution_s,
         SUM(compute_credits + qas_credits) AS tagged_wh_credits,
         LISTAGG(DISTINCT warehouse_name, ',') AS warehouses
  FROM V_AGENT_TOOL_QUERIES GROUP BY request_id)
SELECT r.request_id, r.start_time, r.user_name, r.interface, r.models,
       c.run_id, c.run_label, c.run_type,
       r.token_credits,
       COALESCE(tq.tagged_wh_credits, 0) AS tagged_wh_credits,
       r.token_credits + COALESCE(tq.tagged_wh_credits, 0) AS total_credits,
       r.sql_query_credits AS reported_sql_credits,       -- cross-check: should equal tagged_wh_credits
       COALESCE(tq.tool_queries, 0) AS tool_queries, tq.tool_execution_s, tq.warehouses,
       r.cache_read_credits, r.cache_write_credits, r.io_credits
FROM V_AGENT_REQUESTS r
LEFT JOIN tq ON tq.request_id = r.request_id
LEFT JOIN FPA_DEMO.FPA.COST_RUNS c
  ON c.user_name = r.user_name
 AND r.start_time >= DATEADD(second, -2, c.start_ts)
 AND r.start_time <= COALESCE(c.end_ts, CURRENT_TIMESTAMP());

-- One row per tagged run.
--  tagged_wh_credits  = exact compute of the agent's tool queries (marginal warehouse cost)
--  metered_agent_wh   = FPA_AGENT_WH metered credits in the hours the run touched (includes idle
--                       and 60s resume minimums; hourly granularity, so shared with anything else
--                       on that warehouse in the same hour - by design only agent tools use it)
--  harness_credits    = the test harness's own queries in the window (excluded from agent cost)
CREATE OR REPLACE VIEW V_RUN_COSTS AS
WITH q AS (
  SELECT run_id, COUNT(*) AS questions, SUM(token_credits) AS token_credits,
         SUM(tagged_wh_credits) AS tagged_wh_credits, SUM(reported_sql_credits) AS reported_sql_credits,
         SUM(tool_queries) AS tool_queries
  FROM V_AGENT_QUESTION_COSTS WHERE run_id IS NOT NULL GROUP BY run_id),
m AS (
  SELECT c.run_id, SUM(w.credits_used) AS metered_agent_wh
  FROM FPA_DEMO.FPA.COST_RUNS c
  JOIN SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY w
    ON w.warehouse_name = 'FPA_AGENT_WH'
   AND w.start_time >= DATE_TRUNC('hour', c.start_ts)
   AND w.start_time <= COALESCE(c.end_ts, CURRENT_TIMESTAMP())
  GROUP BY c.run_id),
h AS (
  -- Everything else the run's user ran in the window (harness, worksheet), excluding agent tool
  -- queries and statements whose root is an agent tool query (procedure internals)
  SELECT c.run_id, SUM(a.credits_attributed_compute) AS harness_credits
  FROM FPA_DEMO.FPA.COST_RUNS c
  JOIN SNOWFLAKE.ACCOUNT_USAGE.QUERY_ATTRIBUTION_HISTORY a
    ON a.user_name = c.user_name
   AND a.start_time BETWEEN c.start_ts AND COALESCE(c.end_ts, CURRENT_TIMESTAMP())
  WHERE COALESCE(a.root_query_id, a.query_id) NOT IN (SELECT query_id FROM V_AGENT_TOOL_QUERIES)
  GROUP BY c.run_id)
SELECT c.run_id, c.run_label, c.run_type, c.user_name, c.start_ts, c.end_ts,
       COALESCE(q.questions, 0) AS questions,
       ROUND(q.token_credits, 6) AS token_credits,
       ROUND(q.tagged_wh_credits, 6) AS tagged_wh_credits,
       ROUND(q.reported_sql_credits, 6) AS reported_sql_credits,
       ROUND(m.metered_agent_wh, 6) AS metered_agent_wh,
       ROUND(h.harness_credits, 6) AS harness_credits_excluded,
       q.tool_queries,
       ROUND(q.token_credits / NULLIF(q.questions, 0), 6) AS token_credits_per_question,
       ROUND(q.tagged_wh_credits / NULLIF(q.questions, 0), 6) AS wh_credits_per_question,
       ROUND(100 * q.token_credits / NULLIF(q.token_credits + q.tagged_wh_credits, 0), 2) AS token_pct,
       ROUND(100 * q.tagged_wh_credits / NULLIF(q.token_credits + q.tagged_wh_credits, 0), 2) AS wh_pct
FROM FPA_DEMO.FPA.COST_RUNS c
LEFT JOIN q ON q.run_id = c.run_id
LEFT JOIN m ON m.run_id = c.run_id
LEFT JOIN h ON h.run_id = c.run_id;

-- Validation: tagged warehouse compute should equal the agent's reported sql_query_credits
SELECT COUNT(*) AS requests,
       ROUND(SUM(tagged_wh_credits), 6) AS tagged, ROUND(SUM(reported_sql_credits), 6) AS reported
FROM V_AGENT_QUESTION_COSTS;
SELECT * FROM V_RUN_COSTS ORDER BY start_ts;

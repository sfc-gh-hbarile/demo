-- =====================================================================
-- 09 - Cost monitoring (runs as FPA_DEMO_ROLE via SNOWFLAKE.USAGE_VIEWER)
-- ACCOUNT_USAGE views lag by up to a few hours; empty results right after
-- testing are expected. See README "Monitoring agent costs" for the model.
-- =====================================================================
USE ROLE FPA_DEMO_ROLE; USE WAREHOUSE FPA_DEMO_WH;

-- 1. Agent cost summary: requests, token credits, and warehouse SQL credits
--    attributed to the agent's tool calls
SELECT COUNT(*) AS requests,
       ROUND(SUM(token_credits), 4) AS token_credits,
       ROUND(SUM(metadata:sql_query_credits::FLOAT), 4) AS sql_query_credits,
       ROUND(SUM(token_credits) / NULLIF(COUNT(*), 0), 4) AS avg_token_credits_per_request,
       MAX(start_time) AS last_request
FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AGENT_USAGE_HISTORY
WHERE agent_name = 'FPA_AGENT';

-- 2. Agent credits by day and user (agent API, SQL, and Snowsight requests;
--    CoWork requests are in SNOWFLAKE_COWORK_USAGE_HISTORY)
SELECT DATE_TRUNC('day', start_time) AS usage_day, user_name,
       COUNT(DISTINCT request_id) AS requests, ROUND(SUM(token_credits), 4) AS token_credits
FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AGENT_USAGE_HISTORY
WHERE agent_name = 'FPA_AGENT' AND start_time >= DATEADD(day, -7, CURRENT_TIMESTAMP())
GROUP BY 1, 2 ORDER BY 1 DESC;

-- 3. Per-request detail: which interface, how many tokens, what it cost
SELECT start_time, user_name, request_id,
       metadata:interaction_interface::STRING AS interface,
       tokens,
       ROUND(token_credits, 6) AS token_credits,
       ROUND(metadata:sql_query_credits::FLOAT, 6) AS sql_query_credits
FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AGENT_USAGE_HISTORY
WHERE agent_name = 'FPA_AGENT'
ORDER BY start_time DESC LIMIT 20;

-- 4. Breakdown by service and model (orchestration vs Cortex Analyst)
SELECT DATE_TRUNC('day', h.start_time) AS usage_day,
       g.value:service_type::STRING AS service_type,
       g.value:model::STRING AS model,
       ROUND(SUM(COALESCE(g.value:input::FLOAT, 0) + COALESCE(g.value:cache_read_input::FLOAT, 0)
               + COALESCE(g.value:cache_write_input::FLOAT, 0) + COALESCE(g.value:output::FLOAT, 0)), 6) AS credits
FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AGENT_USAGE_HISTORY h,
     LATERAL FLATTEN(input => h.credits_granular) g
WHERE h.agent_name = 'FPA_AGENT' AND h.start_time >= DATEADD(day, -7, CURRENT_TIMESTAMP())
GROUP BY 1, 2, 3 ORDER BY 1 DESC, credits DESC;

-- 5. Cortex Search service cost (serving and indexing, billed separately from the agent)
SELECT usage_date, consumption_type, ROUND(SUM(credits), 6) AS credits
FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_SEARCH_DAILY_USAGE_HISTORY
WHERE service_name = 'FPA_ASSUMPTIONS_SEARCH' AND usage_date >= DATEADD(day, -7, CURRENT_DATE())
GROUP BY 1, 2 ORDER BY 1 DESC;

-- 6. Warehouse credits for the demo warehouse (all SQL: Analyst queries,
--    procedures, search refresh, and anything run manually)
SELECT DATE_TRUNC('day', start_time) AS usage_day, ROUND(SUM(credits_used), 4) AS warehouse_credits
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
WHERE warehouse_name = 'FPA_DEMO_WH' AND start_time >= DATEADD(day, -7, CURRENT_TIMESTAMP())
GROUP BY 1 ORDER BY 1 DESC;

-- 7. Resource monitor status (quota used vs 10 credits per month)
SHOW RESOURCE MONITORS LIKE 'FPA_DEMO_RM';

-- Plain-language alternative in CoCo (cost-intelligence skill):
--   "Using cost-intelligence, show Cortex Agent credits for FPA_AGENT and
--    warehouse credits for FPA_DEMO_WH by day for the last 7 days."

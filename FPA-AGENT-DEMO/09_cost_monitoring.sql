-- =====================================================================
-- 09 - Cost monitoring (runs as FPA_DEMO_ROLE via SNOWFLAKE.USAGE_VIEWER)
-- ACCOUNT_USAGE views lag by up to a few hours; empty results right after
-- testing are expected.
-- =====================================================================
USE ROLE FPA_DEMO_ROLE; USE WAREHOUSE FPA_DEMO_WH;

-- Agent credits by day and user (agent API, SQL, and Snowsight requests;
-- CoWork requests are in SNOWFLAKE_COWORK_USAGE_HISTORY)
SELECT DATE_TRUNC('day', start_time) AS usage_day, user_name,
       COUNT(DISTINCT request_id) AS requests, ROUND(SUM(token_credits), 4) AS token_credits
FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AGENT_USAGE_HISTORY
WHERE agent_name = 'FPA_AGENT' AND start_time >= DATEADD(day, -7, CURRENT_TIMESTAMP())
GROUP BY 1, 2 ORDER BY 1 DESC;

-- Warehouse credits for the demo warehouse
SELECT DATE_TRUNC('day', start_time) AS usage_day, ROUND(SUM(credits_used), 4) AS warehouse_credits
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
WHERE warehouse_name = 'FPA_DEMO_WH' AND start_time >= DATEADD(day, -7, CURRENT_TIMESTAMP())
GROUP BY 1 ORDER BY 1 DESC;

-- Resource monitor status (quota used vs 10 credits)
SHOW RESOURCE MONITORS LIKE 'FPA_DEMO_RM';

-- Plain-language alternative in CoCo (cost-intelligence skill):
--   "Using cost-intelligence, show Cortex Agent credits for FPA_AGENT and
--    warehouse credits for FPA_DEMO_WH by day for the last 7 days."

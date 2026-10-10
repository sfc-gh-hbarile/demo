-- =====================================================================
-- 08 - Test the five demo questions against FPA_AGENT via SQL
-- DATA_AGENT_RUN needs a constant request argument, so one INSERT per question.
-- Each call can take 30-90s. Resets the workflow tables at the end.
-- =====================================================================
USE ROLE FPA_DEMO_ROLE; USE WAREHOUSE FPA_DEMO_WH;

CREATE OR REPLACE TABLE FPA_DEMO.FPA.AGENT_TEST_RESULTS (q_num INT, question VARCHAR, resp VARIANT);

INSERT INTO FPA_DEMO.FPA.AGENT_TEST_RESULTS SELECT 1, 'EMEA margin', TRY_PARSE_JSON(SNOWFLAKE.CORTEX.DATA_AGENT_RUN('FPA_DEMO.FPA.FPA_AGENT',
 $${"messages":[{"role":"user","content":[{"type":"text","text":"Why is gross margin below plan in EMEA this quarter?"}]}]}$$));
INSERT INTO FPA_DEMO.FPA.AGENT_TEST_RESULTS SELECT 2, 'Forecast changes', TRY_PARSE_JSON(SNOWFLAKE.CORTEX.DATA_AGENT_RUN('FPA_DEMO.FPA.FPA_AGENT',
 $${"messages":[{"role":"user","content":[{"type":"text","text":"What changed in the forecast since last cycle, and why?"}]}]}$$));
INSERT INTO FPA_DEMO.FPA.AGENT_TEST_RESULTS SELECT 3, 'Scenario', TRY_PARSE_JSON(SNOWFLAKE.CORTEX.DATA_AGENT_RUN('FPA_DEMO.FPA.FPA_AGENT',
 $${"messages":[{"role":"user","content":[{"type":"text","text":"What happens to operating income if volume declines 8%, hiring is delayed one quarter, and pricing rises 2%?"}]}]}$$));
INSERT INTO FPA_DEMO.FPA.AGENT_TEST_RESULTS SELECT 4, 'Headcount', TRY_PARSE_JSON(SNOWFLAKE.CORTEX.DATA_AGENT_RUN('FPA_DEMO.FPA.FPA_AGENT',
 $${"messages":[{"role":"user","content":[{"type":"text","text":"What assumptions were documented for the headcount plan?"}]}]}$$));
INSERT INTO FPA_DEMO.FPA.AGENT_TEST_RESULTS SELECT 5, 'Review package', TRY_PARSE_JSON(SNOWFLAKE.CORTEX.DATA_AGENT_RUN('FPA_DEMO.FPA.FPA_AGENT',
 $${"messages":[{"role":"user","content":[{"type":"text","text":"Prepare the forecast review package and notify the budget owners."}]}]}$$));

-- Tools used and answer text per question
-- Expected tools: 1 server_skill+fpa_analyst+fpa_search | 2 fpa_analyst+fpa_search | 3 run_scenario | 4 fpa_search | 5 submit_review_package
SELECT q_num,
  ARRAY_TO_STRING(ARRAY_AGG(IFF(c.value:type = 'tool_use', c.value:tool_use:name::STRING, NULL)), ',') AS tools,
  ARRAY_TO_STRING(ARRAY_AGG(IFF(c.value:type = 'text', c.value:text::STRING, NULL)), '\n') AS answer
FROM FPA_DEMO.FPA.AGENT_TEST_RESULTS r, LATERAL FLATTEN(r.resp:content) c
GROUP BY q_num ORDER BY q_num;

-- Q5 check: expect 1 package PENDING_APPROVAL and 3 HELD_UNTIL_APPROVED notifications
SELECT package_id, status FROM FPA_DEMO.FPA.REVIEW_PACKAGE_LOG;
SELECT region, recipient_name, status FROM FPA_DEMO.FPA.NOTIFICATION_OUTBOX;

-- Reset so the live demo starts clean
CALL FPA_DEMO.FPA.RESET_DEMO_WORKFLOW();
DROP TABLE IF EXISTS FPA_DEMO.FPA.AGENT_TEST_RESULTS;

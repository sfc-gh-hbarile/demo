-- =====================================================================
-- 11 - Agent load test: measures real cost per question and the effect of
-- prompt caching when the same questions are asked again.
-- Each call costs ~0.05-0.3 AI credits and takes 20-90 seconds.
--   CALL RUN_AGENT_LOAD_TEST(8,  'smoke');    -- 4 unique questions x 2  (~1.5-2 credits)
--   CALL RUN_AGENT_LOAD_TEST(10, 'tier_10');  -- one user at 10 questions (~2-3 credits)
--   CALL RUN_AGENT_LOAD_TEST(25, 'tier_25');  -- ~5-7 credits, ~20 min
--   CALL RUN_AGENT_LOAD_TEST(50, 'tier_50');  -- ~10-14 credits, ~40 min
-- Questions cycle Q1..Q4, so call 1-4 are FIRST asks and later calls are REPEATs.
-- The review-package question is excluded so the test never writes workflow rows.
-- Each run is registered in COST_RUNS (script 13). Results land in V_RUN_COSTS and
-- V_LOAD_TEST_COSTS once ACCOUNT_USAGE catches up (a few hours).
-- =====================================================================
USE ROLE FPA_DEMO_ROLE; USE WAREHOUSE FPA_DEMO_WH; USE SCHEMA FPA_DEMO.FPA;

CREATE OR REPLACE PROCEDURE FPA_DEMO.FPA.RUN_AGENT_LOAD_TEST(NUM_QUESTIONS NUMBER, RUN_LABEL VARCHAR)
RETURNS VARIANT
LANGUAGE SQL
COMMENT = 'Calls FPA_AGENT NUM_QUESTIONS times, cycling the read-only demo questions, and logs each call to AGENT_LOAD_TEST_LOG.'
EXECUTE AS CALLER
AS
$$
DECLARE
  run_id VARCHAR DEFAULT 'LT-' || TO_VARCHAR(CURRENT_TIMESTAMP(), 'YYYYMMDDHH24MISS');
  q ARRAY DEFAULT ARRAY_CONSTRUCT(
    'Why is gross margin below plan in EMEA this quarter?',
    'What changed in the forecast since last cycle, and why?',
    'What happens to operating income if volume declines 8%, hiring is delayed one quarter, and pricing rises 2%?',
    'What assumptions were documented for the headcount plan?');
  qid NUMBER;
  qtext VARCHAR;
  body VARCHAR;
  t0 TIMESTAMP_LTZ;
  t1 TIMESTAMP_LTZ;
  resp VARCHAR;
  ok BOOLEAN;
  n_ok NUMBER DEFAULT 0;
BEGIN
  -- Register the run so costs can be scoped to it (see 13_agent_warehouse_tagging.sql)
  INSERT INTO FPA_DEMO.FPA.COST_RUNS (run_id, run_label, run_type, user_name, start_ts)
    SELECT :run_id, :RUN_LABEL, 'LOAD_TEST', CURRENT_USER(), CURRENT_TIMESTAMP();
  FOR i IN 1 TO NUM_QUESTIONS DO
    qid := MOD(i - 1, ARRAY_SIZE(q)) + 1;
    qtext := GET(q, qid - 1)::VARCHAR;
    body := TO_VARCHAR(OBJECT_CONSTRUCT('messages', ARRAY_CONSTRUCT(OBJECT_CONSTRUCT(
              'role', 'user', 'content', ARRAY_CONSTRUCT(OBJECT_CONSTRUCT('type', 'text', 'text', qtext))))));
    t0 := CURRENT_TIMESTAMP();
    BEGIN
      -- DATA_AGENT_RUN needs a constant request argument, so build the statement dynamically
      EXECUTE IMMEDIATE 'SELECT SNOWFLAKE.CORTEX.DATA_AGENT_RUN(''FPA_DEMO.FPA.FPA_AGENT'', ''' || REPLACE(body, '''', '''''') || ''') AS r';
      SELECT LEFT(r, 500) INTO :resp FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));
      ok := TRUE;
      n_ok := n_ok + 1;
    EXCEPTION
      WHEN OTHER THEN
        resp := LEFT(SQLERRM, 500);
        ok := FALSE;
    END;
    t1 := CURRENT_TIMESTAMP();
    INSERT INTO FPA_DEMO.FPA.AGENT_LOAD_TEST_LOG
      (run_id, run_label, seq, question_id, question, attempt, user_name, start_ts, end_ts, ok, response_snippet)
      SELECT :run_id, :RUN_LABEL, :i, :qid, :qtext,
             IFF(:i <= 4, 'FIRST', 'REPEAT'), CURRENT_USER(), :t0, :t1, :ok, :resp;
  END FOR;
  UPDATE FPA_DEMO.FPA.COST_RUNS SET end_ts = CURRENT_TIMESTAMP() WHERE run_id = :run_id;
  RETURN OBJECT_CONSTRUCT('run_id', run_id, 'run_label', RUN_LABEL, 'calls', NUM_QUESTIONS, 'succeeded', n_ok,
    'next_step', 'Costs appear in FPA_DEMO.FPA.V_RUN_COSTS / V_LOAD_TEST_COSTS after ACCOUNT_USAGE latency (up to a few hours)');
END;
$$;

-- Smoke run: 4 unique questions, each asked twice
CALL FPA_DEMO.FPA.RUN_AGENT_LOAD_TEST(8, 'smoke');

-- Immediately: call log (durations, success)
SELECT run_id, seq, question_id, attempt, ok, DATEDIFF(second, start_ts, end_ts) AS seconds
FROM FPA_DEMO.FPA.AGENT_LOAD_TEST_LOG ORDER BY run_id, seq;

-- A few hours later: cost per call and first-vs-repeat comparison
SELECT run_label, attempt, COUNT(request_id) AS matched_calls,
       ROUND(AVG(token_credits), 4) AS avg_token_credits,
       ROUND(AVG(cache_write_credits), 4) AS avg_cache_write_credits,
       ROUND(AVG(cache_read_credits), 4) AS avg_cache_read_credits,
       ROUND(AVG(sql_query_credits), 5) AS avg_sql_credits
FROM FPA_DEMO.FPA.V_LOAD_TEST_COSTS GROUP BY 1, 2 ORDER BY 1, 2;

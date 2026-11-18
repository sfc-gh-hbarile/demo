-- =====================================================================
-- 00_pre_demo.sql : run ~15 min before the live demo, and before every rehearsal (after 99_reset.sql)
-- 1) resumes everything 99_reset.sql section A paused
-- 2) readiness check: every row should say OK. Any '<<< FIX': run 99_reset.sql again, then this file.
-- =====================================================================
USE ROLE ACCOUNTADMIN;
USE WAREHOUSE BP_DEMO_WH;

-- ---------------------------------------------------------------- 1. resume
ALTER PIPE BP_DEMO.RAW.PIPE_FLUXX SET PIPE_EXECUTION_PAUSED = FALSE;   -- no-op unless someone paused it
ALTER PIPE BP_DEMO.RAW.PIPE_SFDC  SET PIPE_EXECUTION_PAUSED = FALSE;
ALTER DYNAMIC TABLE BP_DEMO.CURATED.DT_GRANT_PIPELINE RESUME;   -- upstream DOWNSTREAM-lag DTs resume with it
ALTER CORTEX SEARCH SERVICE BP_DEMO.AI.CSS_GRANT_REVIEWS RESUME INDEXING;
ALTER CORTEX SEARCH SERVICE BP_DEMO.AI.CSS_DONOR_NOTES  RESUME INDEXING;
ALTER SESSION SET USE_CACHED_RESULT = TRUE;
ALTER STAGE BP_DEMO.RAW.LANDING_STAGE REFRESH;   -- so the stage-file check below sees the current files


-- ---------------------------------------------------------------- 2. readiness check
SELECT check_name, actual, expected, IFF(ok, 'OK', '<<< FIX') AS status FROM (
  SELECT 'Vignette 1: CSV files on @RAW.SAMPLE_FILES' AS check_name,
         (SELECT COUNT(*) FROM DIRECTORY(@BP_DEMO.RAW.SAMPLE_FILES))::STRING AS actual, '3' AS expected,
         (SELECT COUNT(*) FROM DIRECTORY(@BP_DEMO.RAW.SAMPLE_FILES)) = 3 AS ok
  UNION ALL
  SELECT 'Vignette 1: bulk files on @RAW.BULK_FILES (08)',
         (SELECT COUNT(*) FROM DIRECTORY(@BP_DEMO.RAW.BULK_FILES))::STRING, '~229',
         (SELECT COUNT(*) FROM DIRECTORY(@BP_DEMO.RAW.BULK_FILES)) > 200
  UNION ALL
  SELECT 'Vignette 1: GRANTEE_DIRECTORY not pre-created (notebook builds it)',
         (SELECT COUNT(*) FROM BP_DEMO.INFORMATION_SCHEMA.TABLES WHERE table_schema = 'GOV' AND table_name = 'GRANTEE_DIRECTORY')::STRING, '0',
         (SELECT COUNT(*) FROM BP_DEMO.INFORMATION_SCHEMA.TABLES WHERE table_schema = 'GOV' AND table_name = 'GRANTEE_DIRECTORY') = 0
  UNION ALL
  SELECT 'Vignette 2: RAW at baseline (no rehearsal data left)',
         ((SELECT COUNT(*) FROM BP_DEMO.RAW.RAW_FLUXX) + (SELECT COUNT(*) FROM BP_DEMO.RAW.RAW_SFDC))::STRING,
         (SELECT COUNT(*) FROM BP_DEMO.RAW.DEMO_BASELINE)::STRING || ' files',
         (SELECT COUNT(*) FROM BP_DEMO.RAW.RAW_FLUXX WHERE file_name NOT IN (SELECT file_name FROM BP_DEMO.RAW.DEMO_BASELINE))
       + (SELECT COUNT(*) FROM BP_DEMO.RAW.RAW_SFDC  WHERE file_name NOT IN (SELECT file_name FROM BP_DEMO.RAW.DEMO_BASELINE)) = 0
  UNION ALL
  SELECT 'Vignette 2: landing stage at baseline (no leftover files)',
         (SELECT COUNT(*) FROM DIRECTORY(@BP_DEMO.RAW.LANDING_STAGE) WHERE relative_path LIKE 'fluxx/%' OR relative_path LIKE 'sfdc/%')::STRING,
         (SELECT COUNT(*) FROM BP_DEMO.RAW.DEMO_BASELINE)::STRING || ' files',
         (SELECT COUNT(*) FROM DIRECTORY(@BP_DEMO.RAW.LANDING_STAGE) WHERE relative_path LIKE 'fluxx/%' OR relative_path LIKE 'sfdc/%')
       = (SELECT COUNT(*) FROM BP_DEMO.RAW.DEMO_BASELINE)
  UNION ALL
  SELECT 'Vignette 2: grants in DT_GRANT_PIPELINE = grants in RAW',
         (SELECT COUNT(*) FROM BP_DEMO.CURATED.DT_GRANT_PIPELINE)::STRING,
         (SELECT COUNT(DISTINCT r.value:grant_id) FROM BP_DEMO.RAW.RAW_FLUXX t, LATERAL FLATTEN(t.payload:records) r)::STRING,
         (SELECT COUNT(*) FROM BP_DEMO.CURATED.DT_GRANT_PIPELINE)
       = (SELECT COUNT(DISTINCT r.value:grant_id) FROM BP_DEMO.RAW.RAW_FLUXX t, LATERAL FLATTEN(t.payload:records) r)
  UNION ALL
  SELECT 'Vignette 2: opportunities in DT_OPPS_ENRICHED = opps in RAW',
         (SELECT COUNT(*) FROM BP_DEMO.AI.DT_OPPS_ENRICHED)::STRING,
         (SELECT COUNT(DISTINCT o.value:opp_id) FROM BP_DEMO.RAW.RAW_SFDC t, LATERAL FLATTEN(t.payload:opportunities) o)::STRING,
         (SELECT COUNT(*) FROM BP_DEMO.AI.DT_OPPS_ENRICHED)
       = (SELECT COUNT(DISTINCT o.value:opp_id) FROM BP_DEMO.RAW.RAW_SFDC t, LATERAL FLATTEN(t.payload:opportunities) o)
  UNION ALL
  SELECT 'Vignette 2: API pull installed (09_api_pull.sql), no API rows left over',
         (SELECT COUNT(*) FROM BP_DEMO.INFORMATION_SCHEMA.PROCEDURES
           WHERE procedure_schema = 'RAW' AND procedure_name = 'PULL_MOCK_FLUXX_API')::STRING
           || ' proc, no api_pull rows: ' ||
         ((SELECT COUNT(*) FROM BP_DEMO.RAW.RAW_FLUXX WHERE file_name LIKE 'api_pull/%') = 0)::STRING,
         '1 proc, no api_pull rows: true',
         (SELECT COUNT(*) FROM BP_DEMO.INFORMATION_SCHEMA.PROCEDURES
           WHERE procedure_schema = 'RAW' AND procedure_name = 'PULL_MOCK_FLUXX_API') = 1
         AND (SELECT COUNT(*) FROM BP_DEMO.RAW.RAW_FLUXX WHERE file_name LIKE 'api_pull/%') = 0
  UNION ALL
  SELECT 'Vignette 3: grants missing an AI summary',
         (SELECT COUNT_IF(ai_reviewer_summary IS NULL) FROM BP_DEMO.AI.DT_GRANTS_ENRICHED)::STRING, '0',
         (SELECT COUNT_IF(ai_reviewer_summary IS NULL) FROM BP_DEMO.AI.DT_GRANTS_ENRICHED) = 0
  UNION ALL
  SELECT 'Vignette 3: Arts + Education under review BEFORE the live delivery (agent answers after it; check truth_check)',
         (SELECT TO_VARCHAR(SUM(requested_amount), '$999,999,999') FROM BP_DEMO.CURATED.DT_GRANT_PIPELINE
          WHERE status = 'Under Review' AND program_area IN ('Arts', 'Education')),
         'same every run', TRUE
);
-- these SHOW commands cover what the query above can't
SHOW AGENTS LIKE 'BP_GRANTS_AGENT' IN SCHEMA BP_DEMO.AI;   -- expect 1 row
SHOW ROLES LIKE 'BP\\_%';                                    -- expect NO rows (Vignette 4 creates them live)
SHOW WAREHOUSES LIKE 'BP_DEMO_WH';             -- expect size X-Small, state SUSPENDED or STARTED
SHOW DYNAMIC TABLES IN DATABASE BP_DEMO;       -- expect scheduling_state ACTIVE
SHOW TASKS LIKE 'T_PULL_MOCK_FLUXX' IN SCHEMA BP_DEMO.RAW;   -- expect state suspended (Section 4 runs it with EXECUTE TASK)
-- Section 4 API pull: proves GitHub is reachable through the External Access Integration, writes nothing.
-- Expect returned_by_api = 3 and would_pull = 3. would_pull = 0 means API rows are still loaded: run 99_reset.sql.
CALL BP_DEMO.RAW.PULL_MOCK_FLUXX_API(TRUE);

-- =====================================================================
-- 99_reset.sql : stop costs between rehearsals, or full teardown
-- =====================================================================

-- ---------- A. PAUSE (keep everything, stop credits)
ALTER TASK IF EXISTS BP_DEMO.RAW.T_FEED SUSPEND;
ALTER TASK IF EXISTS BP_DEMO.RAW.T_COPY_FLUXX SUSPEND;     -- notebook Appendix B
ALTER WAREHOUSE IF EXISTS BP_DEMO_WH SET WAREHOUSE_SIZE = 'XSMALL';   -- in case the sizing demo was left on LARGE
ALTER PIPE IF EXISTS BP_DEMO.RAW.PIPE_FLUXX SET PIPE_EXECUTION_PAUSED = TRUE;
ALTER PIPE IF EXISTS BP_DEMO.RAW.PIPE_SFDC  SET PIPE_EXECUTION_PAUSED = TRUE;
ALTER DYNAMIC TABLE IF EXISTS BP_DEMO.CURATED.DT_GRANT_PIPELINE SUSPEND;   -- upstream DOWNSTREAM-lag DTs stop too
ALTER CORTEX SEARCH SERVICE IF EXISTS BP_DEMO.AI.CSS_GRANT_REVIEWS SUSPEND INDEXING;
ALTER CORTEX SEARCH SERVICE IF EXISTS BP_DEMO.AI.CSS_DONOR_NOTES  SUSPEND INDEXING;

-- ---------- B. RESUME before the session
-- ALTER PIPE BP_DEMO.RAW.PIPE_FLUXX SET PIPE_EXECUTION_PAUSED = FALSE;
-- ALTER PIPE BP_DEMO.RAW.PIPE_SFDC  SET PIPE_EXECUTION_PAUSED = FALSE;
-- ALTER DYNAMIC TABLE BP_DEMO.CURATED.DT_GRANT_PIPELINE RESUME;
-- ALTER CORTEX SEARCH SERVICE BP_DEMO.AI.CSS_GRANT_REVIEWS RESUME INDEXING;
-- ALTER CORTEX SEARCH SERVICE BP_DEMO.AI.CSS_DONOR_NOTES  RESUME INDEXING;
-- ALTER TASK BP_DEMO.RAW.T_FEED RESUME;              -- optional: continuous 3-min feed

-- ---------- C. FULL TEARDOWN (then rebuild with 01 -> 07 + preload in RUNBOOK.md)
-- DROP ROLE IF EXISTS BP_ANALYST; DROP ROLE IF EXISTS BP_PO_PUBLIC_HEALTH;
-- DROP ROLE IF EXISTS BP_PO_ENVIRONMENT; DROP ROLE IF EXISTS BP_GRANTS_COMPLIANCE;
-- DROP DATABASE IF EXISTS BP_DEMO;
-- DROP WAREHOUSE IF EXISTS BP_DEMO_WH;

-- ---------- D. v2 notebook scale demo teardown (08_scale_data.sql objects)
-- DROP TABLE IF EXISTS BP_DEMO.RAW.LOAD_TEST_XS; DROP TABLE IF EXISTS BP_DEMO.RAW.LOAD_TEST_M;
-- DROP STAGE IF EXISTS BP_DEMO.RAW.BULK_FILES;  -- then re-run 08_scale_data.sql to rebuild

-- ---------- E. v2 notebook: reset after a rehearsal (run 1+ hour before the live demo)
-- Keeps the stage and files. Rehearsal history can't be deleted; the notebook isolates each
-- run by the run_id in its query tags, so old runs never mix into the live scorecard.
ALTER WAREHOUSE IF EXISTS BP_DEMO_WH SET WAREHOUSE_SIZE = 'XSMALL';
DROP TABLE IF EXISTS BP_DEMO.RAW.LOAD_TEST_XS;
DROP TABLE IF EXISTS BP_DEMO.RAW.LOAD_TEST_M;
ALTER SESSION UNSET QUERY_TAG;
ALTER SESSION SET USE_CACHED_RESULT = TRUE;
-- Suspend so the XS run starts cold (no warm local disk cache). Errors harmlessly if already suspended.
ALTER WAREHOUSE IF EXISTS BP_DEMO_WH SUSPEND;

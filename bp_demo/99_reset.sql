-- =====================================================================
-- 99_reset.sql : stop costs between rehearsals, or full teardown
-- Practice loop: run this whole file -> 00_pre_demo.sql -> notebook top to bottom. Repeat any time.
-- Running it executes A (pause), F (undo notebook objects), G (rewind data), E (cold warehouse).
-- =====================================================================

-- ---------- A. PAUSE (keep everything, stop credits)
ALTER TASK IF EXISTS BP_DEMO.RAW.T_FEED SUSPEND;
ALTER TASK IF EXISTS BP_DEMO.RAW.T_COPY_FLUXX SUSPEND;     -- notebook Appendix B
ALTER TASK IF EXISTS BP_DEMO.RAW.T_PULL_MOCK_FLUXX SUSPEND; -- 09_api_pull.sql (Section 4 runs it with EXECUTE TASK)
ALTER WAREHOUSE IF EXISTS BP_DEMO_WH SET WAREHOUSE_SIZE = 'XSMALL';   -- in case the sizing demo was left on LARGE
-- Pipes are left RUNNING on purpose: Snowpipe only bills when it loads a file, and with T_FEED
-- suspended no files arrive between rehearsals. A paused pipe can take up to ~7 min to resume.
-- ALTER PIPE IF EXISTS BP_DEMO.RAW.PIPE_FLUXX SET PIPE_EXECUTION_PAUSED = TRUE;
-- ALTER PIPE IF EXISTS BP_DEMO.RAW.PIPE_SFDC  SET PIPE_EXECUTION_PAUSED = TRUE;
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

-- ---------- C. FULL TEARDOWN (then rebuild: 01 -> 02 -> 03 -> preload -> 04 -> 05 -> 06 -> 08 -> 09; see RUNBOOK.md.
--            Do NOT pre-run 07: notebook Vignette 4 creates the roles and policies live.)
-- ALTER TASK IF EXISTS BP_DEMO.RAW.T_FEED SUSPEND; ALTER TASK IF EXISTS BP_DEMO.RAW.T_COPY_FLUXX SUSPEND;
-- DROP ROLE IF EXISTS BP_ANALYST; DROP ROLE IF EXISTS BP_PO_PUBLIC_HEALTH;
-- DROP ROLE IF EXISTS BP_PO_ENVIRONMENT; DROP ROLE IF EXISTS BP_GRANTS_COMPLIANCE;
-- ALTER TASK IF EXISTS BP_DEMO.RAW.T_PULL_MOCK_FLUXX SUSPEND;
-- DROP INTEGRATION IF EXISTS BP_MOCK_FLUXX_EAI;   -- account-level: DROP DATABASE does NOT remove it (09_api_pull.sql)
-- DROP DATABASE IF EXISTS BP_DEMO;
-- DROP WAREHOUSE IF EXISTS BP_DEMO_WH;

-- ---------- D. v2 notebook scale demo teardown (08_scale_data.sql objects)
-- DROP TABLE IF EXISTS BP_DEMO.RAW.LOAD_TEST_XS; DROP TABLE IF EXISTS BP_DEMO.RAW.LOAD_TEST_M;
-- DROP STAGE IF EXISTS BP_DEMO.RAW.BULK_FILES;  -- then re-run 08_scale_data.sql to rebuild

-- ---------- F. v2 notebook: undo what the notebook creates live, so the next run starts clean
-- (Vignette 1 GRANTEE_DIRECTORY + DEV clone, Vignette 4 roles/policies, Appendix B/C objects).
-- Keeps everything 01-06 + 08 built. Safe to re-run.
USE ROLE ACCOUNTADMIN;
ALTER TASK IF EXISTS BP_DEMO.RAW.T_COPY_FLUXX SUSPEND;
DROP TASK IF EXISTS BP_DEMO.RAW.T_COPY_FLUXX;
DROP STREAM IF EXISTS BP_DEMO.RAW.LANDING_FILES_STREAM;
DROP TABLE IF EXISTS BP_DEMO.RAW.RAW_FLUXX_COPY;
DROP TABLE IF EXISTS BP_DEMO.RAW.LANDING_FILE_LOG;
DROP TABLE IF EXISTS BP_DEMO.RAW._VALIDATE_JSON;
REMOVE @BP_DEMO.RAW.LANDING_STAGE/badfiles/;
-- dropping the tables detaches their policies; then the policies themselves can go
DROP TABLE IF EXISTS BP_DEMO.GOV.GRANTEE_DIRECTORY_DEV;
DROP TABLE IF EXISTS BP_DEMO.GOV.GRANTEE_DIRECTORY;
DROP TABLE IF EXISTS BP_DEMO.GOV.PROGRAM_AREA_ACCESS;
DROP ROW ACCESS POLICY IF EXISTS BP_DEMO.GOV.RAP_PROGRAM_AREA;
DROP MASKING POLICY IF EXISTS BP_DEMO.GOV.MASK_PII_STRING;
DROP MASKING POLICY IF EXISTS BP_DEMO.GOV.MASK_EMAIL;
DROP MASKING POLICY IF EXISTS BP_DEMO.GOV.MASK_TAX_ID;
DROP ROLE IF EXISTS BP_ANALYST;
DROP ROLE IF EXISTS BP_PO_PUBLIC_HEALTH;
DROP ROLE IF EXISTS BP_PO_ENVIRONMENT;
DROP ROLE IF EXISTS BP_GRANTS_COMPLIANCE;

-- ---------- G. REWIND DATA to the clean baseline, so every rehearsal starts from identical data
-- The baseline = the files loaded by the rebuild preload (everything loaded within 5 minutes of
-- the very first load). It is captured once and kept; a full rebuild drops it with the database.
CREATE TABLE IF NOT EXISTS BP_DEMO.RAW.DEMO_BASELINE AS
WITH f AS (SELECT file_name, loaded_at FROM BP_DEMO.RAW.RAW_FLUXX
           UNION ALL SELECT file_name, loaded_at FROM BP_DEMO.RAW.RAW_SFDC)
SELECT file_name, loaded_at FROM f
WHERE loaded_at <= (SELECT DATEADD('minute', 5, MIN(loaded_at)) FROM f);

-- Remove every rehearsal file from the landing stage (loaded or not), then the rows they loaded.
-- The DELETE also removes the rows the Section 4 API pull loaded (file_name 'api_pull/...'): those are not
-- in the baseline, so the API watermark empties and the next run pulls the same 3 grants again.
-- Nothing reloads in between: files only arrive when the notebook generates them. Delete-only changes let the
-- Dynamic Tables catch up incrementally: AI re-runs only for the few grants a rehearsal had updated.
ALTER STAGE BP_DEMO.RAW.LANDING_STAGE REFRESH;
EXECUTE IMMEDIATE $$
DECLARE
  files CURSOR FOR
    SELECT relative_path FROM DIRECTORY(@BP_DEMO.RAW.LANDING_STAGE)
    WHERE (relative_path LIKE 'fluxx/%' OR relative_path LIKE 'sfdc/%')
      AND relative_path NOT IN (SELECT file_name FROM BP_DEMO.RAW.DEMO_BASELINE);
  removed INT DEFAULT 0;
BEGIN
  FOR f IN files DO
    EXECUTE IMMEDIATE 'REMOVE @BP_DEMO.RAW.LANDING_STAGE/' || f.relative_path;
    removed := removed + 1;
  END FOR;
  DELETE FROM BP_DEMO.RAW.RAW_FLUXX WHERE file_name NOT IN (SELECT file_name FROM BP_DEMO.RAW.DEMO_BASELINE);
  DELETE FROM BP_DEMO.RAW.RAW_SFDC  WHERE file_name NOT IN (SELECT file_name FROM BP_DEMO.RAW.DEMO_BASELINE);
  RETURN 'Rewind: removed ' || removed || ' rehearsal files from the stage';
END;
$$;
ALTER STAGE BP_DEMO.RAW.LANDING_STAGE REFRESH;
-- Push the rewind through all 6 Dynamic Tables now (works while they are suspended)
ALTER DYNAMIC TABLE BP_DEMO.CURATED.DT_GRANT_PIPELINE REFRESH;

-- ---------- E. v2 notebook: reset after a rehearsal (run 1+ hour before the live demo)
-- Keeps the stage and files. Rehearsal history can't be deleted; the notebook isolates each
-- run by the run_id in its query tags, so old runs never mix into the live scorecard.
ALTER WAREHOUSE IF EXISTS BP_DEMO_WH SET WAREHOUSE_SIZE = 'XSMALL';
DROP TABLE IF EXISTS BP_DEMO.RAW.LOAD_TEST_XS;
DROP TABLE IF EXISTS BP_DEMO.RAW.LOAD_TEST_M;
ALTER SESSION UNSET QUERY_TAG;
ALTER SESSION SET USE_CACHED_RESULT = TRUE;
-- Suspend so the XS run starts cold (no warm local disk cache). Ignores "already suspended".
EXECUTE IMMEDIATE $$
BEGIN
  ALTER WAREHOUSE IF EXISTS BP_DEMO_WH SUSPEND;
  RETURN 'BP_DEMO_WH suspended';
EXCEPTION
  WHEN OTHER THEN RETURN 'BP_DEMO_WH was already suspended';
END;
$$;

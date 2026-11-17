-- =====================================================================
-- 03_ingest.sql : Snowpipe on an INTERNAL stage + simulated feed
--
-- Auto-ingest relies on cloud event notifications and therefore needs an
-- EXTERNAL stage (S3/ADLS/GCS). For an internal stage we trigger Snowpipe
-- with ALTER PIPE ... REFRESH, which queues any not-yet-loaded files
-- (docs: sql-reference/sql/alter-pipe). Snowflake positions REFRESH for
-- short-term use - fine for a demo; production would use auto-ingest on
-- an external stage or the Snowpipe REST API (insertFiles).
-- =====================================================================
USE SCHEMA BP_DEMO.RAW;
USE WAREHOUSE BP_DEMO_WH;

-- Fluxx grant applications
CREATE OR REPLACE PIPE PIPE_FLUXX
  COMMENT = 'Snowpipe: Fluxx 2DB JSON exports -> RAW_FLUXX'
AS
COPY INTO RAW_FLUXX (payload, file_name, loaded_at)
FROM (SELECT $1, METADATA$FILENAME, CURRENT_TIMESTAMP() FROM @LANDING_STAGE/fluxx/)
FILE_FORMAT = (FORMAT_NAME = 'FF_JSON');

-- Salesforce opportunities
CREATE OR REPLACE PIPE PIPE_SFDC
  COMMENT = 'Snowpipe: Salesforce opportunity JSON extracts -> RAW_SFDC'
AS
COPY INTO RAW_SFDC (payload, file_name, loaded_at)
FROM (SELECT $1, METADATA$FILENAME, CURRENT_TIMESTAMP() FROM @LANDING_STAGE/sfdc/)
FILE_FORMAT = (FORMAT_NAME = 'FF_JSON');

-- Simulated continuous feed: every 3 minutes land new files, then nudge both pipes
CREATE OR REPLACE PROCEDURE RUN_FEED_CYCLE(N_GRANTS INT, N_OPPS INT, UPDATE_PCT FLOAT)
RETURNS VARIANT
LANGUAGE SQL
AS
$$
DECLARE
  res VARIANT;
BEGIN
  CALL BP_DEMO.RAW.GEN_MOCK_FILES(:N_GRANTS, :N_OPPS, :UPDATE_PCT) INTO :res;
  ALTER STAGE BP_DEMO.RAW.LANDING_STAGE REFRESH;
  ALTER PIPE BP_DEMO.RAW.PIPE_FLUXX REFRESH;
  ALTER PIPE BP_DEMO.RAW.PIPE_SFDC REFRESH;
  RETURN res;
END;
$$;

CREATE OR REPLACE TASK T_FEED
  WAREHOUSE = BP_DEMO_WH
  SCHEDULE = '3 MINUTE'
  COMMENT = 'Simulates Fluxx + Salesforce files arriving every 3 minutes'
AS
  CALL BP_DEMO.RAW.RUN_FEED_CYCLE(12, 10, 0.3);

-- Start the feed when ready (leave suspended between rehearsals to save credits):
-- ALTER TASK BP_DEMO.RAW.T_FEED RESUME;
-- ALTER TASK BP_DEMO.RAW.T_FEED SUSPEND;

-- ---------------------------------------------------------------- live demo snippets
-- CALL BP_DEMO.RAW.GEN_MOCK_FILES(5, 5, 0.4);                -- files land
-- LIST @BP_DEMO.RAW.LANDING_STAGE/fluxx/;                    -- show them
-- ALTER PIPE BP_DEMO.RAW.PIPE_FLUXX REFRESH;                 -- "auto-ingest"
-- ALTER PIPE BP_DEMO.RAW.PIPE_SFDC  REFRESH;
-- SELECT SYSTEM$PIPE_STATUS('BP_DEMO.RAW.PIPE_FLUXX');
-- SELECT * FROM TABLE(INFORMATION_SCHEMA.COPY_HISTORY(TABLE_NAME=>'BP_DEMO.RAW.RAW_FLUXX',
--          START_TIME=>DATEADD('hour',-1,CURRENT_TIMESTAMP()))) ORDER BY LAST_LOAD_TIME DESC;
-- SELECT file_name, loaded_at, payload FROM BP_DEMO.RAW.RAW_FLUXX ORDER BY loaded_at DESC LIMIT 5;

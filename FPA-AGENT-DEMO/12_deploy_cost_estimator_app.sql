-- =====================================================================
-- 12 - Deploy the cost estimator Streamlit app (container runtime)
-- Option A (snow CLI, from FP&A/cost_estimator_app):
--   snow streamlit deploy --replace -c <connection> --role FPA_DEMO_ROLE --warehouse FPA_DEMO_WH
-- Option B (pure SQL, used for this build) - below.
-- Prereqs: scripts 10 and 11. PUBLIC has USAGE on SYSTEM_COMPUTE_POOL_CPU in this
-- account; if not in yours: GRANT USAGE ON COMPUTE POOL <pool> TO ROLE FPA_DEMO_ROLE;
-- Find the default pool: SHOW PARAMETERS LIKE 'DEFAULT_STREAMLIT_COMPUTE_POOL' IN ACCOUNT;
-- =====================================================================
USE ROLE FPA_DEMO_ROLE; USE WAREHOUSE FPA_DEMO_WH;

CREATE STAGE IF NOT EXISTS FPA_DEMO.FPA.APP_STAGE
  DIRECTORY = (ENABLE = TRUE) COMMENT = 'Source for FPA_AGENT_COST_ESTIMATOR';

-- Adjust the local path if you run from a different directory
PUT 'file:///Users/hbarile/Dev/dev/profiles/hbtraining/FP&A/cost_estimator_app/streamlit_app.py'
  @FPA_DEMO.FPA.APP_STAGE/cost_estimator/ AUTO_COMPRESS = FALSE OVERWRITE = TRUE;

CREATE OR REPLACE STREAMLIT FPA_DEMO.FPA.FPA_AGENT_COST_ESTIMATOR
  FROM '@FPA_DEMO.FPA.APP_STAGE/cost_estimator'
  MAIN_FILE = 'streamlit_app.py'
  QUERY_WAREHOUSE = FPA_DEMO_WH
  RUNTIME_NAME = 'SYSTEM$ST_CONTAINER_RUNTIME_PY3_11'
  COMPUTE_POOL = SYSTEM_COMPUTE_POOL_CPU
  TITLE = 'FP&A Agent Cost Estimator'
  COMMENT = 'Synthetic Acme Corp demo: projects FPA_AGENT cost from measured usage';

-- Validation: expect one row owned by FPA_DEMO_ROLE
SHOW STREAMLITS LIKE 'FPA_AGENT_COST_ESTIMATOR' IN SCHEMA FPA_DEMO.FPA;
-- Open: Snowsight > Projects > Streamlit > FP&A Agent Cost Estimator

-- =====================================================================
-- 12 - Deploy the FP&A Agent Cost Estimator (Streamlit, container runtime)
-- Files: cost_estimator_app/streamlit_app.py and cost_estimator_app/pyproject.toml
-- Runs on the SPCS compute pool with the packages included in Streamlit in Snowflake;
-- no external access integration is needed.
-- Prereqs: scripts 10, 11 and 13 (cost views). Run from a client that supports PUT,
-- or use the Snowsight option in the README instead.
-- =====================================================================
USE ROLE FPA_DEMO_ROLE; USE WAREHOUSE FPA_DEMO_WH;

CREATE STAGE IF NOT EXISTS FPA_DEMO.FPA.APP_STAGE
  DIRECTORY = (ENABLE = TRUE) COMMENT = 'Source for FPA_AGENT_COST_ESTIMATOR';

-- Adjust the local path to where you cloned the repo
PUT 'file:///Users/hbarile/Dev/dev/profiles/hbtraining/FP&A/cost_estimator_app/streamlit_app.py'
  @FPA_DEMO.FPA.APP_STAGE/cost_estimator/ AUTO_COMPRESS = FALSE OVERWRITE = TRUE;
PUT 'file:///Users/hbarile/Dev/dev/profiles/hbtraining/FP&A/cost_estimator_app/pyproject.toml'
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

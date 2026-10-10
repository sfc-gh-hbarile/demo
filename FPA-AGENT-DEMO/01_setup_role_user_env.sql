-- =====================================================================
-- 01 - Demo role, user, database, warehouse, cost guardrail
-- Run as ACCOUNTADMIN. All data in this demo is SYNTHETIC (Acme Corp).
-- =====================================================================
USE ROLE ACCOUNTADMIN;

-- Demo role owns every demo object, so a user on this role sees a clean account
CREATE ROLE IF NOT EXISTS FPA_DEMO_ROLE COMMENT = 'Owns the synthetic Acme Corp FP&A demo';
GRANT ROLE FPA_DEMO_ROLE TO ROLE SYSADMIN;          -- keep standard role hierarchy
SET builder_user = CURRENT_USER();                   -- the admin running this build
GRANT ROLE FPA_DEMO_ROLE TO USER IDENTIFIER($builder_user);

CREATE DATABASE IF NOT EXISTS FPA_DEMO;
CREATE WAREHOUSE IF NOT EXISTS FPA_DEMO_WH
  WAREHOUSE_SIZE = 'XSMALL' AUTO_SUSPEND = 60 AUTO_RESUME = TRUE INITIALLY_SUSPENDED = TRUE;

-- Cost guardrail (requires ACCOUNTADMIN)
CREATE OR REPLACE RESOURCE MONITOR FPA_DEMO_RM WITH CREDIT_QUOTA = 10 FREQUENCY = MONTHLY
  START_TIMESTAMP = IMMEDIATELY TRIGGERS ON 80 PERCENT DO NOTIFY ON 100 PERCENT DO SUSPEND;
ALTER WAREHOUSE FPA_DEMO_WH SET RESOURCE_MONITOR = FPA_DEMO_RM;

-- Hand ownership to the demo role
GRANT OWNERSHIP ON DATABASE FPA_DEMO TO ROLE FPA_DEMO_ROLE COPY CURRENT GRANTS;
GRANT OWNERSHIP ON SCHEMA FPA_DEMO.PUBLIC TO ROLE FPA_DEMO_ROLE COPY CURRENT GRANTS;
GRANT OWNERSHIP ON WAREHOUSE FPA_DEMO_WH TO ROLE FPA_DEMO_ROLE COPY CURRENT GRANTS;
GRANT MONITOR ON RESOURCE MONITOR FPA_DEMO_RM TO ROLE FPA_DEMO_ROLE;

-- Cortex AI + read-only usage views for cost/observability
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE FPA_DEMO_ROLE;
GRANT DATABASE ROLE SNOWFLAKE.USAGE_VIEWER TO ROLE FPA_DEMO_ROLE;       -- metering, agent/search usage, query attribution
GRANT DATABASE ROLE SNOWFLAKE.GOVERNANCE_VIEWER TO ROLE FPA_DEMO_ROLE;  -- QUERY_HISTORY (tagged agent tool queries)
-- (CREATE AGENT is a schema-level privilege; the role owns the schema so no grant is needed)

-- Demo user. Cortex Agents use the user's DEFAULT role and DEFAULT warehouse.
CREATE USER IF NOT EXISTS FPA_DEMO_USER
  DISPLAY_NAME = 'FP&A Demo User'
  DEFAULT_ROLE = FPA_DEMO_ROLE
  DEFAULT_WAREHOUSE = FPA_DEMO_WH
  DEFAULT_NAMESPACE = 'FPA_DEMO.FPA'
  DEFAULT_SECONDARY_ROLES = ()
  COMMENT = 'Synthetic FP&A demo user';
GRANT ROLE FPA_DEMO_ROLE TO USER FPA_DEMO_USER;
-- Set the password yourself (do not commit it):
-- ALTER USER FPA_DEMO_USER SET PASSWORD = '<choose-a-password>' MUST_CHANGE_PASSWORD = FALSE;

-- Build everything else as the demo role
USE ROLE FPA_DEMO_ROLE;
CREATE SCHEMA IF NOT EXISTS FPA_DEMO.FPA;
USE WAREHOUSE FPA_DEMO_WH;

-- Validation
SHOW USERS LIKE 'FPA_DEMO_USER';

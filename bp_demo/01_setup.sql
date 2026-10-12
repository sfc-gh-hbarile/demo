-- =====================================================================
-- BP Modernization Demo
-- 01_setup.sql : database, schemas, warehouse, stage, raw tables
-- =====================================================================
USE ROLE ACCOUNTADMIN;

CREATE WAREHOUSE IF NOT EXISTS BP_DEMO_WH
  WAREHOUSE_SIZE = XSMALL AUTO_SUSPEND = 60 AUTO_RESUME = TRUE
  COMMENT = 'BP modernization demo';

CREATE DATABASE IF NOT EXISTS BP_DEMO COMMENT = 'Fluxx + Salesforce modernization demo';
CREATE SCHEMA IF NOT EXISTS BP_DEMO.RAW     COMMENT = 'Landing zone: stage + VARIANT tables';
CREATE SCHEMA IF NOT EXISTS BP_DEMO.CURATED COMMENT = 'Dynamic Tables replacing SQL Server stored procs';
CREATE SCHEMA IF NOT EXISTS BP_DEMO.AI      COMMENT = 'Cortex enrichment, semantic view, search, agent';

USE WAREHOUSE BP_DEMO_WH;
USE SCHEMA BP_DEMO.RAW;

-- Req 1.1 : internal stage with directory table = landing zone (stands in for the "2DB" export tool)
CREATE FILE FORMAT IF NOT EXISTS FF_JSON TYPE = JSON STRIP_OUTER_ARRAY = FALSE;

CREATE STAGE IF NOT EXISTS LANDING_STAGE
  DIRECTORY = (ENABLE = TRUE)
  FILE_FORMAT = FF_JSON
  COMMENT = 'Folders: /fluxx/ (grant applications), /sfdc/ (opportunities)';

-- Req 1.3 : raw tables keep the whole payload in a VARIANT - no rigid schema
CREATE TABLE IF NOT EXISTS RAW_FLUXX (
  payload   VARIANT,
  file_name STRING,
  loaded_at TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP()
) CHANGE_TRACKING = TRUE;

CREATE TABLE IF NOT EXISTS RAW_SFDC (
  payload   VARIANT,
  file_name STRING,
  loaded_at TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP()
) CHANGE_TRACKING = TRUE;

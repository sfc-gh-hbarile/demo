-- =====================================================================
-- 06_sample_files.sql : small CSV file set for Vignette 1 (LIST / manual
-- COPY INTO / clone / Time Travel) and Vignette 4 (PII to classify + mask).
-- Creates 3 regional "grantee contact directory" exports on a stage.
-- =====================================================================
USE WAREHOUSE BP_DEMO_WH;
CREATE SCHEMA IF NOT EXISTS BP_DEMO.GOV COMMENT = 'Governance: roles mapping, policies, governed objects';

CREATE FILE FORMAT IF NOT EXISTS BP_DEMO.RAW.FF_CSV
  TYPE = CSV PARSE_HEADER = TRUE FIELD_OPTIONALLY_ENCLOSED_BY = '"' NULL_IF = ('');
-- positional ($1, $2 ...) format for peeking at files before loading
CREATE FILE FORMAT IF NOT EXISTS BP_DEMO.RAW.FF_CSV_PEEK
  TYPE = CSV SKIP_HEADER = 1 FIELD_OPTIONALLY_ENCLOSED_BY = '"';

CREATE STAGE IF NOT EXISTS BP_DEMO.RAW.SAMPLE_FILES
  DIRECTORY = (ENABLE = TRUE)
  COMMENT = 'Grantee contact directory exports (CSV) - one file per region';

-- Build the export contents from the grant data (one row per grantee organization)
CREATE OR REPLACE TEMPORARY TABLE _grantee_src AS
WITH orgs AS (
  SELECT organization_name, ANY_VALUE(program_area) AS program_area, ANY_VALUE(country) AS country,
         ANY_VALUE(region) AS region, COUNT(*) AS grants_to_date
  FROM BP_DEMO.CURATED.DT_GRANTS_FLAT GROUP BY 1)
SELECT
  'GR-' || LPAD(ROW_NUMBER() OVER (ORDER BY organization_name), 4, '0')               AS grantee_id,
  organization_name,
  program_area, country, region,
  LPAD(UNIFORM(10, 99, RANDOM()), 2, '0') || '-' || LPAD(UNIFORM(1000000, 9999999, RANDOM()), 7, '0') AS tax_id,
  ARRAY_CONSTRUCT('Amina','David','Lucia','Wei','Fatima','James','Sofia','Kwame','Priya','Tom')[UNIFORM(0,9,RANDOM())]::STRING
    || ' ' || ARRAY_CONSTRUCT('Okafor','Smith','Garcia','Chen','Khan','Brown','Rossi','Mensah','Sharma','Miller')[UNIFORM(0,9,RANDOM())]::STRING AS contact_name,
  LOWER(REGEXP_REPLACE(organization_name, '[^A-Za-z]', '')) AS _dom,
  'executive.director@' || LEFT(_dom, 18) || '.org'                                     AS contact_email,
  '+1-' || UNIFORM(200, 989, RANDOM()) || '-' || UNIFORM(200, 989, RANDOM()) || '-' || LPAD(UNIFORM(0, 9999, RANDOM()), 4, '0') AS contact_phone,
  UNIFORM(250000, 60000000, RANDOM())                                                  AS annual_budget_usd,
  grants_to_date,
  DATEADD('day', -UNIFORM(30, 3000, RANDOM()), CURRENT_DATE())                          AS first_grant_date
FROM orgs;

-- Unload: one CSV per region group (this is also how you EXPORT data from Snowflake)
COPY INTO @BP_DEMO.RAW.SAMPLE_FILES/grantee_directory_americas.csv
  FROM (SELECT * EXCLUDE _dom FROM _grantee_src WHERE region IN ('North America', 'Latin America'))
  FILE_FORMAT = (TYPE = CSV COMPRESSION = NONE FIELD_OPTIONALLY_ENCLOSED_BY = '"') HEADER = TRUE SINGLE = TRUE OVERWRITE = TRUE;
COPY INTO @BP_DEMO.RAW.SAMPLE_FILES/grantee_directory_emea.csv
  FROM (SELECT * EXCLUDE _dom FROM _grantee_src WHERE region IN ('Europe', 'Africa'))
  FILE_FORMAT = (TYPE = CSV COMPRESSION = NONE FIELD_OPTIONALLY_ENCLOSED_BY = '"') HEADER = TRUE SINGLE = TRUE OVERWRITE = TRUE;
COPY INTO @BP_DEMO.RAW.SAMPLE_FILES/grantee_directory_apac.csv
  FROM (SELECT * EXCLUDE _dom FROM _grantee_src WHERE region IN ('South Asia', 'East Asia & Pacific'))
  FILE_FORMAT = (TYPE = CSV COMPRESSION = NONE FIELD_OPTIONALLY_ENCLOSED_BY = '"') HEADER = TRUE SINGLE = TRUE OVERWRITE = TRUE;

ALTER STAGE BP_DEMO.RAW.SAMPLE_FILES REFRESH;

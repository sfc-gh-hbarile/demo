-- =====================================================================
-- 08_scale_data.sql : data for the "scale up" demos in Vignette 1 (v2 notebook)
--   * Query scaling uses the shared TPCDS_10TB database (must exist in the account).
--   * Load scaling needs many files: unload TPCDS CUSTOMER (65M rows) to ~230 gzip CSVs.
-- Run once before the demo (about 1-2 min on LARGE). Safe to re-run.
-- =====================================================================
USE ROLE ACCOUNTADMIN;
USE WAREHOUSE BP_DEMO_WH;

-- sanity check: fails fast if the shared database is missing
SELECT COUNT(*) AS item_rows FROM TPCDS_10TB.TPCDS_SF10TCL.ITEM;

CREATE STAGE IF NOT EXISTS BP_DEMO.RAW.BULK_FILES
  DIRECTORY = (ENABLE = TRUE)
  COMMENT = 'Multi-file extract used for the load-scaling demo (v2 notebook)';

-- bulk-load format: header-driven columns, unloaded NULLs arrive as \N
CREATE FILE FORMAT IF NOT EXISTS BP_DEMO.RAW.FF_CSV_BULK
  TYPE = CSV PARSE_HEADER = TRUE FIELD_OPTIONALLY_ENCLOSED_BY = '"' NULL_IF = ('\\N', '');

ALTER WAREHOUSE BP_DEMO_WH SET WAREHOUSE_SIZE = 'LARGE';   -- unload faster; demo resizes it itself
REMOVE @BP_DEMO.RAW.BULK_FILES/customer/;

COPY INTO @BP_DEMO.RAW.BULK_FILES/customer/
  FROM (SELECT * FROM TPCDS_10TB.TPCDS_SF10TCL.CUSTOMER)
  FILE_FORMAT = (TYPE = CSV COMPRESSION = GZIP FIELD_OPTIONALLY_ENCLOSED_BY = '"')
  HEADER = TRUE MAX_FILE_SIZE = 20000000 OVERWRITE = TRUE;

ALTER STAGE BP_DEMO.RAW.BULK_FILES REFRESH;
ALTER WAREHOUSE BP_DEMO_WH SET WAREHOUSE_SIZE = 'XSMALL';

-- expect ~230 files, ~3.9 GB
SELECT COUNT(*) AS files, ROUND(SUM(size)/1e9, 2) AS gb FROM DIRECTORY(@BP_DEMO.RAW.BULK_FILES);

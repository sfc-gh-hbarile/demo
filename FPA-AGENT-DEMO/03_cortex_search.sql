-- =====================================================================
-- 03 - Cortex Search service over the planning documents
-- =====================================================================
USE ROLE FPA_DEMO_ROLE; USE WAREHOUSE FPA_DEMO_WH;

CREATE OR REPLACE CORTEX SEARCH SERVICE FPA_DEMO.FPA.FPA_ASSUMPTIONS_SEARCH
  ON doc_text
  ATTRIBUTES doc_title, doc_type, entity
  WAREHOUSE = FPA_DEMO_WH
  TARGET_LAG = '1 day'
AS (SELECT doc_id, doc_title, doc_type, entity, doc_text FROM FPA_DEMO.FPA.ASSUMPTION_DOCS);

-- Validation: expect "FY26 Headcount Plan" as the top result
SELECT PARSE_JSON(SNOWFLAKE.CORTEX.SEARCH_PREVIEW('FPA_DEMO.FPA.FPA_ASSUMPTIONS_SEARCH',
  '{"query":"headcount plan hiring","columns":["doc_title","doc_type"],"limit":3}')):results AS results;

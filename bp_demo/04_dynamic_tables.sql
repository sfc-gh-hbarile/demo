-- =====================================================================
-- 04_dynamic_tables.sql : declarative pipeline replacing SQL Server
-- stored procedures. Layers:
--   CURATED.DT_GRANTS_FLAT   / DT_OPPS_FLAT     FLATTEN + typed + dedup
--   CURATED.DT_GRANT_BUDGET                     nested budget array -> rows
--   AI.DT_GRANTS_ENRICHED    / DT_OPPS_ENRICHED Cortex AI (incremental)
--   CURATED.DT_GRANT_PIPELINE                   conformed grant + donor view
-- Only the final table carries the business SLA (TARGET_LAG 5 min);
-- upstream tables use DOWNSTREAM so they refresh only when needed.
-- Cortex AI functions are supported in incremental DTs (release note 2025-09-11),
-- so each new/changed row is scored once instead of on every refresh.
-- =====================================================================
USE WAREHOUSE BP_DEMO_WH;

-- ---------------------------------------------------------------- 1. flatten + dedup
CREATE OR REPLACE DYNAMIC TABLE BP_DEMO.CURATED.DT_GRANTS_FLAT
  TARGET_LAG = DOWNSTREAM WAREHOUSE = BP_DEMO_WH REFRESH_MODE = AUTO
  COMMENT = 'Fluxx grant applications: latest version per grant_id'
AS
SELECT
  r.value:grant_id::STRING                  AS grant_id,
  r.value:organization_name::STRING         AS organization_name,
  r.value:program_area::STRING              AS program_area,
  r.value:initiative::STRING                AS initiative,
  r.value:grant_type::STRING                AS grant_type,
  r.value:region::STRING                    AS region,
  r.value:country::STRING                   AS country,
  r.value:program_officer::STRING           AS program_officer,
  r.value:requested_amount::NUMBER(14,2)    AS requested_amount,
  r.value:approved_amount::NUMBER(14,2)     AS approved_amount,
  r.value:duration_months::INT              AS duration_months,
  r.value:status::STRING                    AS status,
  r.value:submitted_date::DATE              AS submitted_date,
  r.value:decision_date::DATE               AS decision_date,
  r.value:risk_rating::STRING               AS risk_rating,
  r.value:matching_funds_required::BOOLEAN  AS matching_funds_required,
  r.value:reviewer_score::NUMBER(3,1)       AS reviewer_score,
  r.value:reviewer_notes::STRING            AS reviewer_notes,
  r.value:budget_breakdown                  AS budget_breakdown,
  r.value:outcome_targets                   AS outcome_targets,
  r.value:last_modified::TIMESTAMP_NTZ      AS last_modified,
  t.file_name                               AS source_file
FROM BP_DEMO.RAW.RAW_FLUXX t,
     LATERAL FLATTEN(INPUT => t.payload:records) r
QUALIFY ROW_NUMBER() OVER (PARTITION BY r.value:grant_id::STRING
                           ORDER BY r.value:last_modified::TIMESTAMP_NTZ DESC) = 1;

CREATE OR REPLACE DYNAMIC TABLE BP_DEMO.CURATED.DT_OPPS_FLAT
  TARGET_LAG = DOWNSTREAM WAREHOUSE = BP_DEMO_WH REFRESH_MODE = AUTO
  COMMENT = 'Salesforce opportunities: latest version per opp_id'
AS
SELECT
  o.value:opp_id::STRING                    AS opp_id,
  o.value:account_name::STRING              AS account_name,
  o.value:donor_type::STRING                AS donor_type,
  o.value:grant_id_ref::STRING              AS grant_id_ref,
  o.value:program_area_interest::STRING     AS program_area_interest,
  o.value:stage::STRING                     AS stage,
  o.value:probability_pct::INT              AS probability_pct,
  o.value:amount::NUMBER(14,2)              AS amount,
  o.value:close_date::DATE                  AS close_date,
  o.value:relationship_manager::STRING      AS relationship_manager,
  ARRAY_SIZE(o.value:engagement_history)    AS touchpoint_count,
  o.value:engagement_history                AS engagement_history,
  o.value:donor_engagement_notes::STRING    AS donor_engagement_notes,
  o.value:last_modified::TIMESTAMP_NTZ      AS last_modified
FROM BP_DEMO.RAW.RAW_SFDC t,
     LATERAL FLATTEN(INPUT => t.payload:opportunities) o
QUALIFY ROW_NUMBER() OVER (PARTITION BY o.value:opp_id::STRING
                           ORDER BY o.value:last_modified::TIMESTAMP_NTZ DESC) = 1;

-- nested array -> rows (the kind of logic that took cursors/temp tables in T-SQL)
CREATE OR REPLACE DYNAMIC TABLE BP_DEMO.CURATED.DT_GRANT_BUDGET
  TARGET_LAG = DOWNSTREAM WAREHOUSE = BP_DEMO_WH REFRESH_MODE = AUTO
  COMMENT = 'Grant budget line items flattened from nested JSON'
AS
SELECT g.grant_id, g.program_area, g.status,
       b.value:line_item::STRING        AS budget_line,
       b.value:amount::NUMBER(14,2)     AS budget_amount
FROM BP_DEMO.CURATED.DT_GRANTS_FLAT g,
     LATERAL FLATTEN(INPUT => g.budget_breakdown) b;

-- ---------------------------------------------------------------- 2. Cortex AI enrichment
CREATE OR REPLACE DYNAMIC TABLE BP_DEMO.AI.DT_GRANTS_ENRICHED
  TARGET_LAG = DOWNSTREAM WAREHOUSE = BP_DEMO_WH REFRESH_MODE = INCREMENTAL
  COMMENT = 'Grants + AI executive summary and primary risk theme'
AS
SELECT g.* EXCLUDE (budget_breakdown, outcome_targets),
  AI_COMPLETE('llama3.3-70b',
    'Summarize this grant reviewer assessment in ONE concise executive sentence (max 30 words). '
    || 'Return only the sentence.\n\n' || g.reviewer_notes)::STRING                   AS ai_reviewer_summary,
  AI_CLASSIFY(g.reviewer_notes,
    ['Financial capacity', 'Outcome measurement', 'Political or regulatory risk',
     'Execution capacity', 'Program overlap', 'Budget concerns']):labels[0]::STRING    AS ai_primary_risk
FROM BP_DEMO.CURATED.DT_GRANTS_FLAT g;

CREATE OR REPLACE DYNAMIC TABLE BP_DEMO.AI.DT_OPPS_ENRICHED
  TARGET_LAG = DOWNSTREAM WAREHOUSE = BP_DEMO_WH REFRESH_MODE = INCREMENTAL
  COMMENT = 'Opportunities + donor sentiment score (-1..1)'
AS
SELECT s.*,
  CASE WHEN s.donor_sentiment >=  0.25 THEN 'Positive'
       WHEN s.donor_sentiment <= -0.25 THEN 'At Risk'
       ELSE 'Neutral' END                                                           AS donor_health
FROM (
  SELECT o.* EXCLUDE (engagement_history),
    SNOWFLAKE.CORTEX.SENTIMENT(o.donor_engagement_notes)                            AS donor_sentiment
  FROM BP_DEMO.CURATED.DT_OPPS_FLAT o
) s;

-- ---------------------------------------------------------------- 3. conformed pipeline (SLA table)
CREATE OR REPLACE DYNAMIC TABLE BP_DEMO.CURATED.DT_GRANT_PIPELINE
  TARGET_LAG = '5 minutes' WAREHOUSE = BP_DEMO_WH REFRESH_MODE = AUTO
  COMMENT = 'One row per grant: Fluxx application + AI fields + Salesforce funding pipeline. 5-min SLA.'
AS
SELECT
  g.grant_id, g.organization_name, g.program_area, g.initiative, g.grant_type,
  g.region, g.country, g.program_officer, g.status, g.risk_rating, g.reviewer_score,
  g.matching_funds_required, g.requested_amount, g.approved_amount, g.duration_months,
  g.submitted_date, g.decision_date, g.ai_reviewer_summary, g.ai_primary_risk, g.reviewer_notes,
  COUNT(o.opp_id)                                                        AS opp_count,
  COALESCE(SUM(o.amount), 0)                                             AS pipeline_amount,
  COALESCE(SUM(o.amount * o.probability_pct / 100), 0)                   AS weighted_pipeline_amount,
  COALESCE(SUM(IFF(o.stage IN ('Committed', 'Closed Won'), o.amount, 0)), 0) AS committed_amount,
  AVG(o.donor_sentiment)                                                 AS avg_donor_sentiment,
  g.last_modified
FROM BP_DEMO.AI.DT_GRANTS_ENRICHED g
LEFT JOIN BP_DEMO.AI.DT_OPPS_ENRICHED o
  ON o.grant_id_ref = g.grant_id
GROUP BY ALL;

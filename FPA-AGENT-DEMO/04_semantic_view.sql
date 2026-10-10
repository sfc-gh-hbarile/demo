-- =====================================================================
-- 04 - Semantic view (approved finance metrics) used by the agent's Analyst tool
-- =====================================================================
USE ROLE FPA_DEMO_ROLE; USE WAREHOUSE FPA_DEMO_WH;

CREATE OR REPLACE SEMANTIC VIEW FPA_DEMO.FPA.FPA_SEMANTIC_VIEW
  TABLES (
    pl AS FPA_DEMO.FPA.FACT_PL COMMENT = 'Closed months Jan-Sep 2026: actuals and plan by month, entity, and product',
    fcst AS FPA_DEMO.FPA.FACT_FORECAST COMMENT = 'Open months Oct-Dec 2026: forecast by version, with plan for the same months and a forecast note explaining changes',
    entity AS FPA_DEMO.FPA.DIM_ENTITY PRIMARY KEY (entity_id) WITH SYNONYMS = ('region','geography','business unit','market'),
    product AS FPA_DEMO.FPA.DIM_PRODUCT PRIMARY KEY (product_id) WITH SYNONYMS = ('product line','offering')
  )
  RELATIONSHIPS (
    pl_to_entity AS pl (entity_id) REFERENCES entity,
    pl_to_product AS pl (product_id) REFERENCES product,
    fcst_to_entity AS fcst (entity_id) REFERENCES entity,
    fcst_to_product AS fcst (product_id) REFERENCES product
  )
  DIMENSIONS (
    entity.region AS entity.region,
    entity.entity_name AS entity.entity_name,
    product.product_name AS product.product_name,
    pl.period_month AS pl.period_month COMMENT = 'Month of a closed period',
    pl.period_quarter AS DATE_TRUNC('quarter', pl.period_month) COMMENT = 'Calendar quarter; Q3 = Jul-Sep',
    fcst.forecast_period_month AS fcst.period_month COMMENT = 'Forecast month, Oct-Dec 2026',
    fcst.forecast_version AS fcst.forecast_version COMMENT = 'FY26_SEP is the current forecast, FY26_AUG is the prior cycle',
    fcst.version_date AS fcst.version_date,
    fcst.forecast_note AS fcst.forecast_note COMMENT = 'Reason for the forecast assumption or change'
  )
  METRICS (
    pl.total_revenue_actual AS SUM(pl.revenue_actual),
    pl.total_revenue_plan AS SUM(pl.revenue_plan),
    pl.total_cogs_actual AS SUM(pl.cogs_actual),
    pl.total_cogs_plan AS SUM(pl.cogs_plan),
    pl.gross_margin_pct_actual AS 100 * (SUM(pl.revenue_actual) - SUM(pl.cogs_actual)) / NULLIF(SUM(pl.revenue_actual), 0)
      WITH SYNONYMS = ('gross margin','GM','gross margin percent') COMMENT = 'Actual gross margin as a percent of revenue',
    pl.gross_margin_pct_plan AS 100 * (SUM(pl.revenue_plan) - SUM(pl.cogs_plan)) / NULLIF(SUM(pl.revenue_plan), 0) COMMENT = 'Plan gross margin as a percent of revenue',
    pl.total_opex_actual AS SUM(pl.opex_actual),
    pl.total_opex_plan AS SUM(pl.opex_plan),
    pl.operating_income_actual AS SUM(pl.revenue_actual) - SUM(pl.cogs_actual) - SUM(pl.opex_actual) WITH SYNONYMS = ('operating income','EBIT','operating profit'),
    pl.operating_income_plan AS SUM(pl.revenue_plan) - SUM(pl.cogs_plan) - SUM(pl.opex_plan),
    pl.total_units_actual AS SUM(pl.units_actual),
    pl.total_units_plan AS SUM(pl.units_plan),
    pl.avg_price_actual AS SUM(pl.revenue_actual) / NULLIF(SUM(pl.units_actual), 0) COMMENT = 'Realized price per unit',
    pl.avg_price_plan AS SUM(pl.revenue_plan) / NULLIF(SUM(pl.units_plan), 0),
    pl.avg_unit_cost_actual AS SUM(pl.cogs_actual) / NULLIF(SUM(pl.units_actual), 0) COMMENT = 'Actual cost per unit',
    pl.avg_unit_cost_plan AS SUM(pl.cogs_plan) / NULLIF(SUM(pl.units_plan), 0),
    fcst.forecast_revenue AS SUM(fcst.revenue_fcst),
    fcst.forecast_cogs AS SUM(fcst.cogs_fcst),
    fcst.forecast_opex AS SUM(fcst.opex_fcst),
    fcst.forecast_gross_margin_pct AS 100 * (SUM(fcst.revenue_fcst) - SUM(fcst.cogs_fcst)) / NULLIF(SUM(fcst.revenue_fcst), 0),
    fcst.forecast_operating_income AS SUM(fcst.revenue_fcst) - SUM(fcst.cogs_fcst) - SUM(fcst.opex_fcst),
    fcst.plan_revenue_open_months AS SUM(fcst.revenue_plan),
    fcst.plan_operating_income_open_months AS SUM(fcst.revenue_plan) - SUM(fcst.cogs_plan) - SUM(fcst.opex_plan)
  )
  COMMENT = 'Acme Corp FP&A: actuals, plan, and forecast versions by region and product. All data is synthetic.'
  AI_SQL_GENERATION 'Fiscal year is calendar 2026. Closed months are Jan-Sep 2026 (table pl). Open months are Oct-Dec 2026 (table fcst). Q3 means Jul-Sep 2026. "This quarter" means Q3 2026 unless the user says otherwise. Gross margin is a percent of revenue. "Below plan" compares actual to plan; report the difference in percentage points for margins and in dollars for amounts. For "why" questions, break the variance into price effect, volume effect, and unit cost effect using avg_price, total_units, and avg_unit_cost, and break it out by product within the region. The current forecast is forecast_version FY26_SEP and the prior forecast is FY26_AUG. When comparing forecast versions, compare the same entity, product, and month and show forecast_note. Always filter or group by region when the user mentions a region.'
  AI_QUESTION_CATEGORIZATION 'Questions about actuals, plan, variance, margin, price, volume, cost, or forecast versions are in scope. Scenario what-if questions with percentage changes to volume, price, or hiring are NOT answered with SQL; they must use the run_scenario tool. Questions about assumptions, policies, or documents are NOT answered with SQL; they must use the search tool.';

-- Validation (SQL generated by Cortex Analyst for "Gross margin actual vs plan for EMEA in Q3 2026 by product")
-- Expect: Advisory Services ~-8.4 pts, Core Platform ~-1.9 pts, Data Products ~0
SELECT product_name, ROUND(gross_margin_pct_actual,1) AS gm_act, ROUND(gross_margin_pct_plan,1) AS gm_plan,
       ROUND(gross_margin_pct_actual - gross_margin_pct_plan,1) AS gap_pts
FROM SEMANTIC_VIEW(
    FPA_DEMO.FPA.FPA_SEMANTIC_VIEW
    METRICS gross_margin_pct_actual, gross_margin_pct_plan
    DIMENSIONS product.product_name, entity.region
    WHERE entity.region = 'EMEA' AND pl.period_month >= '2026-07-01' AND pl.period_month < '2026-10-01'
) ORDER BY gap_pts;

# FP&A Agentic Finance Demo: One-Prompt Build

A single prompt you paste into Snowflake CoCo (Cortex Code) in a **demo account**. It builds a complete, synthetic FP&A environment and a working finance agent, then lets you demo five questions in about 15 minutes. Nothing here references a specific customer, so you can reuse it with any FP&A team.

## What it builds

| Layer | Object | Purpose |
|---|---|---|
| Environment | `FPA_DEMO` database, `FPA` schema, `FPA_DEMO_WH` warehouse (XS), resource monitor | Isolated sandbox with a spend cap |
| Synthetic data | `DIM_ENTITY`, `DIM_PRODUCT`, `FACT_PL` (Jan-Sep actuals and plan), `FACT_FORECAST` (two forecast versions for Oct-Dec), `ASSUMPTION_DOCS` | Three regions, three products, one hidden story in EMEA |
| Semantic layer | `FPA_SEMANTIC_VIEW` | Approved finance metrics defined once |
| Search | `FPA_ASSUMPTIONS_SEARCH` (Cortex Search) | Planning documents and assumptions |
| Tool calls | `RUN_SCENARIO`, `SUBMIT_REVIEW_PACKAGE`, `APPROVE_REVIEW_PACKAGE` (stored procedures) | Scenario modeling and a human-approved workflow action |
| Skill | `fpa-variance-review` (CoCo skill) | Repeatable variance-review method and commentary template |
| Agent | `FPA_AGENT` | Analyst + Search + two custom tools + charts |
| Cost | Usage queries on `ACCOUNT_USAGE` | Show what the demo costs |

## The hidden story in the data

- **EMEA gross margin is below plan in Q3 2026** (about 53% vs 57% plan). Two drivers: Core Platform price discounting (about -6%) and Advisory Services unit cost (about +12%, contractor rates).
- NA is on plan. APAC is slightly ahead.
- The current forecast (`FY26_SEP`) differs from the prior one (`FY26_AUG`), and each changed row carries a note explaining why.
- Modeled "today" is early October 2026: Jan-Sep are closed months, Oct-Dec are forecast.

## The five demo questions (15 minutes)

| # | Question | Capability | Time |
|---|---|---|---|
| 1 | Why is gross margin below plan in EMEA this quarter? | Cortex Analyst on the semantic view; price, volume, and cost drivers | 3 min |
| 2 | What changed in the forecast since last cycle, and why? | Forecast versions plus the change notes | 3 min |
| 3 | What happens to operating income if volume declines 8%, hiring is delayed one quarter, and pricing rises 2%? | `RUN_SCENARIO` stored procedure as a tool | 3 min |
| 4 | What assumptions were documented for the headcount plan? | Cortex Search over documents | 2 min |
| 5 | Prepare the forecast review package and notify the budget owners. | `SUBMIT_REVIEW_PACKAGE` tool, held until a human approves | 3 min |

Then 1 minute on cost (Step 9). Suggested talk track is at the end of this file.

## Before you run it

- Use a **demo account**, not a production or shared internal account. The prompt creates and replaces objects.
- Use a role that can create databases, warehouses, and resource monitors (ACCOUNTADMIN is simplest in a demo account). The role needs Cortex access (`SNOWFLAKE.CORTEX_USER` is granted to PUBLIC by default).
- Your user needs a **default role** and a **default warehouse** with USAGE granted. Cortex Agents decide permissions from the user's default role, so agent calls can fail if either is missing. Step 1 of the prompt sets this up.
- Open CoCo with the connection pointing at the demo account, then paste everything inside the box below.
- Allow 10-15 minutes for the build. Run it before the call, not during.

---

## THE PROMPT (copy everything inside the box)

````markdown
You are building a complete, self-contained FP&A demo in this Snowflake account. All data is SYNTHETIC. Do not mention any real company names anywhere; the fictional company is "Acme Corp". Work step by step. After each step, run the validation check, and if anything fails, fix it and retry before moving on. Keep a short running log. If a step needs a privilege you do not have, stop and tell me exactly which privilege.

Before you start: confirm the active connection and role, tell me the account name, and ask me to confirm this is a demo account. Wait for my answer. Then proceed without asking again unless blocked.

Use the sql-author skill for SQL, the agent-studio skill for the semantic view and the agent, and the skill-development skill for the skill. If any syntax below fails, check current documentation with `cortex search docs` and adapt it.

## STEP 1: Environment

```sql
CREATE DATABASE IF NOT EXISTS FPA_DEMO;
CREATE SCHEMA IF NOT EXISTS FPA_DEMO.FPA;
CREATE WAREHOUSE IF NOT EXISTS FPA_DEMO_WH WAREHOUSE_SIZE = 'XSMALL' AUTO_SUSPEND = 60 AUTO_RESUME = TRUE INITIALLY_SUSPENDED = TRUE;
USE DATABASE FPA_DEMO; USE SCHEMA FPA; USE WAREHOUSE FPA_DEMO_WH;
```

Cost guardrail (skip with a note if I lack ACCOUNTADMIN):

```sql
CREATE OR REPLACE RESOURCE MONITOR FPA_DEMO_RM WITH CREDIT_QUOTA = 10 FREQUENCY = MONTHLY START_TIMESTAMP = IMMEDIATELY
  TRIGGERS ON 80 PERCENT DO NOTIFY ON 100 PERCENT DO SUSPEND;
ALTER WAREHOUSE FPA_DEMO_WH SET RESOURCE_MONITOR = FPA_DEMO_RM;
```

Cortex Agents use the user's DEFAULT role and DEFAULT warehouse. Check my user with DESCRIBE USER. If the default warehouse is empty, set it to FPA_DEMO_WH and make sure my default role has USAGE on it. Tell me what you changed.

## STEP 2: Synthetic data (run from FPA_DEMO.FPA)

Dimensions:

```sql
CREATE OR REPLACE TABLE DIM_ENTITY AS
SELECT * FROM VALUES
 (1,'Acme North America','North America','Jordan Lee','jordan.lee@example.com'),
 (2,'Acme EMEA','EMEA','Priya Raman','priya.raman@example.com'),
 (3,'Acme APAC','APAC','Kenji Mori','kenji.mori@example.com')
 AS t(entity_id, entity_name, region, finance_owner_name, finance_owner_email);

CREATE OR REPLACE TABLE DIM_PRODUCT AS
SELECT * FROM VALUES (1,'Core Platform'),(2,'Advisory Services'),(3,'Data Products') AS t(product_id, product_name);
```

Closed-period actuals and plan, Jan-Sep 2026, grain month x entity x product. EMEA has the planted story from July onward (Core Platform price -6%, Advisory Services unit cost +12%, opex +3%). APAC Data Products price is +3%.

```sql
CREATE OR REPLACE TABLE FACT_PL AS
WITH months AS (SELECT DATEADD(month, SEQ4(), '2026-01-01'::DATE) AS period_month FROM TABLE(GENERATOR(ROWCOUNT => 9))),
ent AS (SELECT * FROM VALUES (1,1.0),(2,0.6),(3,0.4) AS t(entity_id, scale)),
prod AS (SELECT * FROM VALUES (1,1000,1200,360),(2,400,2500,1750),(3,600,900,180) AS t(product_id, base_units, base_price, base_cost)),
grid AS (
  SELECT m.period_month, e.entity_id, p.product_id,
    ROUND(p.base_units*e.scale*POWER(1.015, DATEDIFF(month,'2026-01-01',m.period_month))) AS units_plan,
    p.base_price AS price_plan, p.base_cost AS unit_cost_plan,
    (MOD(ABS(HASH(e.entity_id, p.product_id, m.period_month)), 1000)/1000.0 - 0.5)*0.04 AS noise
  FROM months m CROSS JOIN ent e CROSS JOIN prod p),
act AS (
  SELECT *, ROUND(units_plan*(1+noise)) AS units_actual,
    price_plan*(1+noise*0.25)*CASE WHEN entity_id=2 AND product_id=1 AND period_month>='2026-07-01' THEN 0.94
         WHEN entity_id=3 AND product_id=3 AND period_month>='2026-07-01' THEN 1.03 ELSE 1 END AS price_actual,
    unit_cost_plan*(1+noise*0.25)*CASE WHEN entity_id=2 AND product_id=2 AND period_month>='2026-07-01' THEN 1.12 ELSE 1 END AS unit_cost_actual
  FROM grid)
SELECT period_month, entity_id, product_id,
  units_plan, units_actual, price_plan, ROUND(price_actual,2) AS price_actual,
  unit_cost_plan, ROUND(unit_cost_actual,2) AS unit_cost_actual,
  ROUND(units_plan*price_plan,2) AS revenue_plan, ROUND(units_actual*price_actual,2) AS revenue_actual,
  ROUND(units_plan*unit_cost_plan,2) AS cogs_plan, ROUND(units_actual*unit_cost_actual,2) AS cogs_actual,
  ROUND(units_plan*price_plan*0.38,2) AS opex_plan,
  ROUND(units_plan*price_plan*0.38*(1+noise*0.5)*CASE WHEN entity_id=2 AND period_month>='2026-07-01' THEN 1.03 ELSE 1 END,2) AS opex_actual
FROM act;
```

Forecast versions for the open months Oct-Dec 2026. FY26_AUG is the prior cycle (assumed a recovery). FY26_SEP is the current cycle (reflects what was learned). Each changed row has a note that explains why. hiring_cost_fcst is the part of opex from planned Q4 hires (6%).

```sql
CREATE OR REPLACE TABLE FACT_FORECAST AS
WITH months AS (SELECT DATEADD(month, 9 + SEQ4(), '2026-01-01'::DATE) AS period_month FROM TABLE(GENERATOR(ROWCOUNT => 3))),
ent AS (SELECT * FROM VALUES (1,1.0),(2,0.6),(3,0.4) AS t(entity_id, scale)),
prod AS (SELECT * FROM VALUES (1,1000,1200,360),(2,400,2500,1750),(3,600,900,180) AS t(product_id, base_units, base_price, base_cost)),
ver AS (SELECT * FROM VALUES ('FY26_AUG','2026-08-15'::DATE),('FY26_SEP','2026-10-06'::DATE) AS t(forecast_version, version_date)),
base AS (
  SELECT m.period_month, e.entity_id, p.product_id,
    ROUND(p.base_units*e.scale*POWER(1.015, DATEDIFF(month,'2026-01-01',m.period_month))) AS units_plan,
    p.base_price, p.base_cost
  FROM months m CROSS JOIN ent e CROSS JOIN prod p),
calc AS (
  SELECT v.forecast_version, v.version_date, b.period_month, b.entity_id, b.product_id,
    b.units_plan*b.base_price AS revenue_plan,
    b.units_plan*b.base_cost AS cogs_plan,
    b.units_plan*b.base_price*0.38 AS opex_plan,
    IFF(v.forecast_version='FY26_SEP',
        CASE WHEN b.entity_id=2 AND b.product_id=1 THEN 0.94
             WHEN b.entity_id=1 AND b.product_id=3 THEN 1.05
             WHEN b.entity_id=3 AND b.product_id=1 THEN 1.03 ELSE 1 END, 1) AS rev_adj,
    IFF(v.forecast_version='FY26_SEP' AND b.entity_id=2 AND b.product_id=2, 1.12, 1) AS cogs_adj,
    IFF(v.forecast_version='FY26_SEP' AND b.entity_id=2, 1.03, 1) AS opex_adj
  FROM base b CROSS JOIN ver v)
SELECT forecast_version, version_date, period_month, entity_id, product_id,
  ROUND(revenue_plan*rev_adj,2) AS revenue_fcst,
  ROUND(cogs_plan*cogs_adj,2) AS cogs_fcst,
  ROUND(opex_plan*opex_adj,2) AS opex_fcst,
  ROUND(opex_plan*opex_adj*0.06,2) AS hiring_cost_fcst,
  ROUND(revenue_plan,2) AS revenue_plan, ROUND(cogs_plan,2) AS cogs_plan, ROUND(opex_plan,2) AS opex_plan,
  CASE
    WHEN forecast_version='FY26_AUG' AND entity_id=2 THEN 'Aug forecast assumed EMEA pricing recovers to plan and contractor rates stabilize in Q4'
    WHEN forecast_version='FY26_SEP' AND entity_id=2 AND product_id=1 THEN 'Revenue lowered 6%: Q3 discounting on EMEA Core Platform now assumed to continue through Q4'
    WHEN forecast_version='FY26_SEP' AND entity_id=2 AND product_id=2 THEN 'Cost raised 12%: contractor rates up in EMEA Advisory Services; opex raised 3% for backfill'
    WHEN forecast_version='FY26_SEP' AND entity_id=2 AND product_id=3 THEN 'Opex raised 3%: EMEA backfill and contractor ramp'
    WHEN forecast_version='FY26_SEP' AND entity_id=1 AND product_id=3 THEN 'Revenue raised 5%: new logo wins in NA Data Products'
    WHEN forecast_version='FY26_SEP' AND entity_id=3 AND product_id=1 THEN 'Revenue raised 3%: APAC Core Platform pipeline converting above plan'
  END AS forecast_note
FROM calc;
```

Planning documents for Cortex Search (write 6 short, realistic documents, each 3-5 sentences, fictional company Acme Corp):

```sql
CREATE OR REPLACE TABLE ASSUMPTION_DOCS (doc_id NUMBER, doc_title VARCHAR, doc_type VARCHAR, entity VARCHAR, effective_date DATE, doc_text VARCHAR);
INSERT INTO ASSUMPTION_DOCS VALUES
 (1,'FY26 Headcount Plan','headcount','All','2026-01-15','The FY26 headcount plan ends the year at 412 FTE. Net new hiring is concentrated in Q4 with 14 planned hires: 6 in EMEA, 5 in North America, and 3 in APAC, mostly delivery and customer success roles. Q4 hiring cost is modeled at about 6 percent of forecast operating expense. Hiring is gated on the Q3 close and can be delayed by one quarter if volume softens. Approver for any change is the VP Finance.'),
 (2,'FY26 Pricing and Discount Policy','pricing','All','2026-01-15','List prices are unchanged for FY26. Discounts above 10 percent require regional finance approval. The plan assumes an average realized discount of 4 percent on Core Platform. Annual price increases of up to 3 percent are allowed at renewal with VP Sales sign-off.'),
 (3,'EMEA Q3 Business Review Notes','review','EMEA','2026-10-02','EMEA Core Platform deals closed with deeper discounts than planned in Q3 because of competitive pressure in two large accounts. Advisory Services relied on contractors to cover a delivery backlog, and contractor rates rose about 12 percent. Management expects discounting to persist through Q4. A pricing review is scheduled for November.'),
 (4,'FY26 FX and Currency Assumptions','fx','All','2026-01-15','Plan rates assume EUR/USD of 1.08 and no material change in APAC currencies. A 5 percent move in EUR is estimated to change EMEA revenue by about 5 percent and operating income by about 3 percent. Hedging covers 50 percent of forecast EUR exposure through Q4.'),
 (5,'Forecast Methodology','methodology','All','2026-01-15','The forecast is refreshed monthly after close. Baseline forecast equals plan adjusted for known run-rate changes. Every change versus the prior forecast needs a written reason in the forecast note. Scenario analysis uses approved driver logic: revenue moves with volume and price, cost of goods moves with volume, and operating expense moves with hiring timing.'),
 (6,'Variance Commentary Standards','policy','All','2026-01-15','Management commentary must state the headline variance, the top two drivers with amounts, the outlook for the next quarter, and recommended actions. Variances above 2 percent of revenue or 1 point of gross margin must be explained. All commentary is reviewed and approved by FP&A before distribution.');
```

Workflow tables:

```sql
CREATE OR REPLACE TABLE REVIEW_PACKAGE_LOG (package_id VARCHAR, created_at TIMESTAMP_LTZ, period VARCHAR, summary VARCHAR, status VARCHAR, created_by VARCHAR, approved_by VARCHAR, approved_at TIMESTAMP_LTZ);
CREATE OR REPLACE TABLE NOTIFICATION_OUTBOX (package_id VARCHAR, recipient_name VARCHAR, recipient_email VARCHAR, region VARCHAR, message VARCHAR, status VARCHAR);
```

VALIDATION for step 2: run this and confirm EMEA Q3 gross margin is near 53% vs about 57.4% plan, and NA and APAC are near plan. Show me the result.

```sql
SELECT e.region, IFF(f.period_month>='2026-07-01','Q3','H1') AS per,
  ROUND(100*(1-SUM(f.cogs_actual)/SUM(f.revenue_actual)),1) AS gm_actual_pct,
  ROUND(100*(1-SUM(f.cogs_plan)/SUM(f.revenue_plan)),1) AS gm_plan_pct
FROM FACT_PL f JOIN DIM_ENTITY e USING (entity_id) GROUP BY 1,2 ORDER BY 1,2;
```

## STEP 3: Cortex Search over the documents

```sql
CREATE OR REPLACE CORTEX SEARCH SERVICE FPA_DEMO.FPA.FPA_ASSUMPTIONS_SEARCH
  ON doc_text
  ATTRIBUTES doc_title, doc_type, entity
  WAREHOUSE = FPA_DEMO_WH
  TARGET_LAG = '1 day'
AS (SELECT doc_id, doc_title, doc_type, entity, doc_text FROM FPA_DEMO.FPA.ASSUMPTION_DOCS);
```

Validation: wait until the service is ready, then run a test search for "headcount plan hiring" and confirm the FY26 Headcount Plan document is returned.

## STEP 4: Semantic view (approved finance metrics)

Create this semantic view. If the DDL has any error, fix it using the documentation and keep the same metric names and meanings.

```sql
CREATE OR REPLACE SEMANTIC VIEW FPA_DEMO.FPA.FPA_SEMANTIC_VIEW
  TABLES (
    pl AS FPA_DEMO.FPA.FACT_PL
      COMMENT = 'Closed months Jan-Sep 2026: actuals and plan by month, entity, and product',
    fcst AS FPA_DEMO.FPA.FACT_FORECAST
      COMMENT = 'Open months Oct-Dec 2026: forecast by version, with plan for the same months and a forecast note explaining changes',
    entity AS FPA_DEMO.FPA.DIM_ENTITY PRIMARY KEY (entity_id)
      WITH SYNONYMS = ('region','geography','business unit','market'),
    product AS FPA_DEMO.FPA.DIM_PRODUCT PRIMARY KEY (product_id)
      WITH SYNONYMS = ('product line','offering')
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
    pl.gross_margin_pct_plan AS 100 * (SUM(pl.revenue_plan) - SUM(pl.cogs_plan)) / NULLIF(SUM(pl.revenue_plan), 0)
      COMMENT = 'Plan gross margin as a percent of revenue',
    pl.total_opex_actual AS SUM(pl.opex_actual),
    pl.total_opex_plan AS SUM(pl.opex_plan),
    pl.operating_income_actual AS SUM(pl.revenue_actual) - SUM(pl.cogs_actual) - SUM(pl.opex_actual)
      WITH SYNONYMS = ('operating income','EBIT','operating profit'),
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
```

Validation: ask the semantic view "Gross margin actual vs plan for EMEA in Q3 2026 by product" and confirm EMEA Core Platform and Advisory Services show the largest gaps. Show me the generated SQL.

## STEP 5: Stored procedures (tool calls)

All table names are fully qualified so the agent can call these from any session.

```sql
CREATE OR REPLACE PROCEDURE FPA_DEMO.FPA.RUN_SCENARIO(
  VOLUME_CHANGE_PCT FLOAT, PRICE_CHANGE_PCT FLOAT, HIRING_DELAY_QUARTERS NUMBER, ENTITY_REGION VARCHAR)
RETURNS VARIANT
LANGUAGE SQL
COMMENT = 'What-if on the current Oct-Dec forecast: volume %, price %, and hiring delay in quarters. ENTITY_REGION is ALL, North America, EMEA, or APAC.'
AS
$$
DECLARE
  result VARIANT;
BEGIN
  WITH base AS (
    SELECT f.forecast_version, f.period_month, f.revenue_fcst, f.cogs_fcst, f.opex_fcst, f.hiring_cost_fcst,
           f.revenue_plan, f.cogs_plan, f.opex_plan,
           DATEDIFF(month, MIN(f.period_month) OVER (), f.period_month) AS month_idx
    FROM FPA_DEMO.FPA.FACT_FORECAST f
    JOIN FPA_DEMO.FPA.DIM_ENTITY e ON e.entity_id = f.entity_id
    WHERE f.forecast_version = (SELECT forecast_version FROM FPA_DEMO.FPA.FACT_FORECAST ORDER BY version_date DESC LIMIT 1)
      AND (UPPER(:ENTITY_REGION) = 'ALL' OR UPPER(e.region) = UPPER(:ENTITY_REGION))
  ),
  calc AS (
    SELECT forecast_version, revenue_fcst, cogs_fcst, opex_fcst, revenue_plan, cogs_plan, opex_plan,
      revenue_fcst * (1 + :VOLUME_CHANGE_PCT/100) * (1 + :PRICE_CHANGE_PCT/100) AS revenue_s,
      cogs_fcst * (1 + :VOLUME_CHANGE_PCT/100) AS cogs_s,
      opex_fcst - IFF(month_idx < :HIRING_DELAY_QUARTERS * 3, hiring_cost_fcst, 0) AS opex_s
    FROM base
  )
  SELECT OBJECT_CONSTRUCT(
    'forecast_version', MAX(forecast_version),
    'region', :ENTITY_REGION,
    'inputs', OBJECT_CONSTRUCT('volume_change_pct', :VOLUME_CHANGE_PCT, 'price_change_pct', :PRICE_CHANGE_PCT, 'hiring_delay_quarters', :HIRING_DELAY_QUARTERS),
    'baseline', OBJECT_CONSTRUCT('revenue', ROUND(SUM(revenue_fcst)), 'gross_margin_pct', ROUND(100*(1-SUM(cogs_fcst)/SUM(revenue_fcst)),1),
                 'opex', ROUND(SUM(opex_fcst)), 'operating_income', ROUND(SUM(revenue_fcst - cogs_fcst - opex_fcst))),
    'scenario', OBJECT_CONSTRUCT('revenue', ROUND(SUM(revenue_s)), 'gross_margin_pct', ROUND(100*(1-SUM(cogs_s)/SUM(revenue_s)),1),
                 'opex', ROUND(SUM(opex_s)), 'operating_income', ROUND(SUM(revenue_s - cogs_s - opex_s))),
    'change_vs_baseline_operating_income', ROUND(SUM(revenue_s - cogs_s - opex_s) - SUM(revenue_fcst - cogs_fcst - opex_fcst)),
    'plan_operating_income', ROUND(SUM(revenue_plan - cogs_plan - opex_plan)),
    'assumptions', ARRAY_CONSTRUCT(
      'Baseline is the latest forecast version for Oct-Dec 2026',
      'Revenue moves with volume and price; cost of goods moves with volume only',
      'A hiring delay removes planned hiring cost (6 percent of opex) for the first 3 months per quarter delayed',
      'Illustrative driver logic; finance should confirm before using externally')
  ) INTO :result
  FROM calc;
  RETURN result;
END;
$$;

CREATE OR REPLACE PROCEDURE FPA_DEMO.FPA.SUBMIT_REVIEW_PACKAGE(PERIOD VARCHAR, SUMMARY VARCHAR)
RETURNS VARIANT
LANGUAGE SQL
COMMENT = 'Creates a forecast review package in PENDING_APPROVAL status and queues held notifications for each regional finance owner. Nothing is sent until a human approves.'
AS
$$
DECLARE
  pkg_id VARCHAR DEFAULT 'RP-' || TO_VARCHAR(CURRENT_TIMESTAMP(), 'YYYYMMDDHH24MISS');
  n NUMBER;
BEGIN
  INSERT INTO FPA_DEMO.FPA.REVIEW_PACKAGE_LOG (package_id, created_at, period, summary, status, created_by)
    SELECT :pkg_id, CURRENT_TIMESTAMP(), :PERIOD, :SUMMARY, 'PENDING_APPROVAL', CURRENT_USER();
  INSERT INTO FPA_DEMO.FPA.NOTIFICATION_OUTBOX (package_id, recipient_name, recipient_email, region, message, status)
    SELECT :pkg_id, finance_owner_name, finance_owner_email, region,
           'Forecast review package for ' || :PERIOD || ' is ready for your review once FP&A approves it.', 'HELD_UNTIL_APPROVED'
    FROM FPA_DEMO.FPA.DIM_ENTITY;
  SELECT COUNT(*) INTO :n FROM FPA_DEMO.FPA.NOTIFICATION_OUTBOX WHERE package_id = :pkg_id;
  RETURN OBJECT_CONSTRUCT('package_id', :pkg_id, 'status', 'PENDING_APPROVAL', 'notifications_queued', :n,
    'next_step', 'An FP&A approver must run APPROVE_REVIEW_PACKAGE before notifications are released');
END;
$$;

CREATE OR REPLACE PROCEDURE FPA_DEMO.FPA.APPROVE_REVIEW_PACKAGE(PACKAGE_ID VARCHAR)
RETURNS VARIANT
LANGUAGE SQL
COMMENT = 'Human approval step. NOT exposed to the agent. Releases held notifications.'
AS
$$
BEGIN
  UPDATE FPA_DEMO.FPA.REVIEW_PACKAGE_LOG SET status = 'APPROVED', approved_by = CURRENT_USER(), approved_at = CURRENT_TIMESTAMP()
    WHERE package_id = :PACKAGE_ID;
  UPDATE FPA_DEMO.FPA.NOTIFICATION_OUTBOX SET status = 'READY_TO_SEND' WHERE package_id = :PACKAGE_ID;
  RETURN OBJECT_CONSTRUCT('package_id', :PACKAGE_ID, 'status', 'APPROVED');
END;
$$;
```

Validation: call the scenario directly and show me the result. Expect the baseline operating income to be below plan, and the scenario operating income to be close to baseline (the hiring delay offsets most of the lost margin from lower volume).

```sql
CALL FPA_DEMO.FPA.RUN_SCENARIO(-8, 2, 1, 'ALL');
```

Do not leave test packages behind: after testing SUBMIT_REVIEW_PACKAGE, delete the test rows from REVIEW_PACKAGE_LOG and NOTIFICATION_OUTBOX.

## STEP 6: CoCo skill "fpa-variance-review"

Using the skill-development skill, create a skill named `fpa-variance-review` in my global skills location with this content (YAML frontmatter plus body). It captures a repeatable variance-review method I can reuse in CoCo.

```markdown
---
name: fpa-variance-review
description: Repeatable FP&A variance review for plan vs actual vs forecast. Use when asked why a margin, revenue, or cost line is off plan, what changed in the forecast, or to draft management commentary. Triggers: variance, below plan, forecast change, margin, management commentary, review package.
---

# FP&A Variance Review

## Method
1. Confirm scope: region, product, period (closed months vs open forecast months), and which forecast version.
2. Quantify the headline variance: actual vs plan in dollars and in margin points.
3. Decompose the variance:
   - Price effect = (actual price - plan price) x actual units
   - Volume effect = (actual units - plan units) x plan price
   - Unit cost effect = (actual unit cost - plan unit cost) x actual units
   Report the top two drivers by size, by product.
4. Check the forecast notes and planning documents for the business reason. Do not invent reasons; if no source supports a reason, say so.
5. State the outlook: how the current forecast treats the driver for the next quarter.
6. Recommend actions and name the owner role.

## Output template
- Headline (one sentence with the number)
- Drivers (table: driver, amount, source)
- Outlook
- Recommended actions
- Status: DRAFT, pending FP&A approval

## Guardrails
- Show the SQL or tool used for every number.
- Scenario what-ifs use the approved scenario procedure, never ad hoc math.
- Never send or publish a review package without explicit human approval.
- State assumptions and data period on every output.
```

## STEP 7: The agent

Create the agent with a SQL specification. Use the agent-studio skill to validate it. If the custom tool resource syntax fails, check `cortex search docs "Cortex Agents custom tool stored procedure"` and adapt it.

```sql
CREATE OR REPLACE AGENT FPA_DEMO.FPA.FPA_AGENT
  COMMENT = 'Acme Corp FP&A assistant: variance analysis, forecast changes, scenarios, assumptions, and review workflow (synthetic data)'
  PROFILE = '{"display_name": "FP&A Assistant", "color": "blue"}'
  FROM SPECIFICATION
  $$
  models:
    orchestration: auto
  orchestration:
    budget:
      seconds: 90
      tokens: 32000
  instructions:
    response: "You are an FP&A assistant for finance teams. Lead with the answer and the number. Use tables for drivers. Always state the period and forecast version used. Show the numbers you relied on. Label any commentary as DRAFT pending FP&A approval. Keep answers concise."
    orchestration: "Use the analyst tool for actuals, plan, variance, margin, price, volume, cost, and forecast version comparisons. For why questions, decompose into price, volume, and unit cost effects by product and cite the forecast_note. Use the search tool for assumptions, policies, headcount plan, pricing policy, and methodology. Use run_scenario for any what-if with percentage changes to volume, price, or hiring timing; never calculate scenarios yourself. Use submit_review_package only when the user asks to prepare a review package or notify owners; always tell the user that the package is pending human approval and nothing is sent until approved. Closed months are Jan-Sep 2026. Open months are Oct-Dec 2026. The current forecast is FY26_SEP."
    sample_questions:
      - question: "Why is gross margin below plan in EMEA this quarter?"
      - question: "What changed in the forecast since last cycle, and why?"
      - question: "What happens to operating income if volume declines 8%, hiring is delayed one quarter, and pricing rises 2%?"
      - question: "What assumptions were documented for the headcount plan?"
      - question: "Prepare the forecast review package and notify the budget owners."
  tools:
    - tool_spec:
        type: "cortex_analyst_text_to_sql"
        name: "fpa_analyst"
        description: "Answers questions about actuals, plan, variance, margins, price, volume, unit cost, and forecast versions using the approved FP&A semantic view"
    - tool_spec:
        type: "cortex_search"
        name: "fpa_search"
        description: "Searches planning documents: headcount plan, pricing and discount policy, regional business review notes, FX assumptions, forecast methodology, commentary standards"
    - tool_spec:
        type: "generic"
        name: "run_scenario"
        description: "Runs a what-if on the current Oct-Dec forecast. Use for questions that change volume, price, or hiring timing. Returns baseline vs scenario revenue, gross margin, opex, and operating income."
        input_schema:
          type: "object"
          properties:
            volume_change_pct:
              type: "number"
              description: "Percent change in volume, for example -8 for a decline of 8 percent"
            price_change_pct:
              type: "number"
              description: "Percent change in price, for example 2 for an increase of 2 percent"
            hiring_delay_quarters:
              type: "number"
              description: "Number of quarters to delay planned hiring, 0 for none"
            entity_region:
              type: "string"
              description: "ALL, North America, EMEA, or APAC"
          required: ["volume_change_pct", "price_change_pct", "hiring_delay_quarters", "entity_region"]
    - tool_spec:
        type: "generic"
        name: "submit_review_package"
        description: "Creates a forecast review package in pending-approval status and queues held notifications to regional finance owners. Nothing is sent until a human approves."
        input_schema:
          type: "object"
          properties:
            period:
              type: "string"
              description: "Period covered, for example Q3 2026 close and Q4 forecast"
            summary:
              type: "string"
              description: "Short summary of the key findings to include in the package"
          required: ["period", "summary"]
    - tool_spec:
        type: "data_to_chart"
        name: "data_to_chart"
        description: "Generates charts from query results"
  tool_resources:
    fpa_analyst:
      semantic_view: "FPA_DEMO.FPA.FPA_SEMANTIC_VIEW"
      execution_environment:
        type: "warehouse"
        warehouse: "FPA_DEMO_WH"
    fpa_search:
      search_service: "FPA_DEMO.FPA.FPA_ASSUMPTIONS_SEARCH"
      max_results: "4"
      title_column: "doc_title"
      id_column: "doc_id"
    run_scenario:
      type: "procedure"
      identifier: "FPA_DEMO.FPA.RUN_SCENARIO"
      execution_environment:
        type: "warehouse"
        warehouse: "FPA_DEMO_WH"
    submit_review_package:
      type: "procedure"
      identifier: "FPA_DEMO.FPA.SUBMIT_REVIEW_PACKAGE"
      execution_environment:
        type: "warehouse"
        warehouse: "FPA_DEMO_WH"
  $$;
```

Grant my current role USAGE on the agent, and make sure the role can use the semantic view, search service, procedures, and warehouse. Then run `DESCRIBE AGENT FPA_DEMO.FPA.FPA_AGENT` and confirm it was created.

## STEP 8: Test the five demo questions

Run each question against FPA_AGENT (use the Snowsight agent playground instructions if you cannot call it from here, and in that case test each tool directly with SQL). For each, tell me the tool used, the key numbers, and whether the answer matches what is expected. Fix the semantic view, instructions, or tools if not.

1. "Why is gross margin below plan in EMEA this quarter?" Expect: EMEA Q3 gross margin about 53% vs about 57% plan; drivers are Core Platform price (about -6%) and Advisory Services unit cost (about +12%).
2. "What changed in the forecast since last cycle, and why?" Expect: FY26_SEP vs FY26_AUG differences with the forecast notes: EMEA Core Platform revenue down, EMEA Advisory Services cost up, NA Data Products up, APAC Core Platform up.
3. "What happens to operating income if volume declines 8%, hiring is delayed one quarter, and pricing rises 2%?" Expect: a run_scenario call, baseline operating income below plan, scenario close to baseline because the hiring delay offsets most of the volume impact.
4. "What assumptions were documented for the headcount plan?" Expect: 412 FTE, 14 Q4 hires (6 EMEA, 5 NA, 3 APAC), hiring gated on Q3 close.
5. "Prepare the forecast review package and notify the budget owners." Expect: a package ID in PENDING_APPROVAL, 3 held notifications, and a statement that nothing is sent until approved.

After testing, reset the workflow tables (delete test rows from REVIEW_PACKAGE_LOG and NOTIFICATION_OUTBOX) so the live demo starts clean.

## STEP 9: Cost monitoring

Create these as saved queries or show them, and run them now. ACCOUNT_USAGE views can lag by a few hours, so recent activity may not appear yet; say so if the results are empty.

```sql
-- Agent credits by day and user (requests from the agent API, SQL, and Snowsight; CoWork requests are in SNOWFLAKE_COWORK_USAGE_HISTORY)
SELECT DATE_TRUNC('day', start_time) AS usage_day, user_name, COUNT(DISTINCT request_id) AS requests, ROUND(SUM(token_credits), 4) AS token_credits
FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AGENT_USAGE_HISTORY
WHERE agent_name = 'FPA_AGENT' AND start_time >= DATEADD(day, -7, CURRENT_TIMESTAMP())
GROUP BY 1, 2 ORDER BY 1 DESC;

-- Warehouse credits for the demo warehouse
SELECT DATE_TRUNC('day', start_time) AS usage_day, ROUND(SUM(credits_used), 4) AS warehouse_credits
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
WHERE warehouse_name = 'FPA_DEMO_WH' AND start_time >= DATEADD(day, -7, CURRENT_TIMESTAMP())
GROUP BY 1 ORDER BY 1 DESC;
```

Also show me how to ask the cost-intelligence skill for the same information in plain language.

## STEP 10: Final report

Give me a short summary with: every object created (full names), the results of each validation, the five questions with the answers you observed, anything you changed from this prompt, the credits used so far, and a cleanup script (DROP statements for the agent, search service, procedures, semantic view, tables, warehouse, resource monitor, database, and the skill). Do not run the cleanup.
````

---

## Suggested talk track (15 minutes)

| Time | What to do | What to say |
|---|---|---|
| 0:00 | Show the schema in Snowsight, 30 seconds | "This is the FP&A data you already keep in Snowflake. We add a semantic layer and an agent on top." |
| 0:30 | Open the semantic view | "Metrics are defined once: gross margin, operating income, price and unit cost. Dashboards and the agent share them." |
| 1:30 | Q1 (variance) | Point to the SQL the agent wrote and the price vs cost drivers. "Finance can verify every number." |
| 4:30 | Q2 (forecast change) | "Every forecast change carries a reason, so the explanation comes from your own process." |
| 7:30 | Q3 (scenario) | "The agent does not do math in its head. It calls approved scenario logic, a stored procedure you own." |
| 10:30 | Q4 (documents) | "Same question box, but now it reads planning documents. Governed the same way." |
| 12:00 | Q5 (workflow) | Show the package in `PENDING_APPROVAL`. Run `CALL FPA_DEMO.FPA.APPROVE_REVIEW_PACKAGE('<id>')` and show the outbox flip to `READY_TO_SEND`. "Human in the loop." |
| 15:00 | Cost, 1 minute | Show the usage queries. "A pilot costs a few credits, capped by the resource monitor." |

## Suggestions to make it land better

1. **Pre-warm before the call.** Run questions 1-5 once, 30 minutes ahead, so the warehouse and search service are warm and responses are fast. Reset the workflow tables afterward.
2. **Name the customer's real terms live.** Rename the regions or products in `DIM_ENTITY` and `DIM_PRODUCT` to match the audience. It takes 30 seconds and makes the demo feel built for them.
3. **Add a dashboard slide.** Say the same semantic view and curated views feed Power BI or a Snowflake-native dashboard, so the agent and the dashboards never disagree.
4. **Show the guardrails explicitly.** Mention role-based access, masking, and the approval step. Finance buyers care about controls before they care about AI.
5. **Offer the "build it together" next step.** Close with the sandbox plan: same prompt, their own schema, their metrics, and a spend cap.
6. **Optional extras if time allows:** add verified queries to the semantic view for the top finance questions; run Cortex Agent evaluations on a 20-question test set; replace the simulated notification outbox with email through a notification integration once the customer approves it.
7. **Know the limits.** The scenario logic is deliberately simple (revenue moves with volume and price, cost moves with volume, hiring delay removes a fixed share of opex). Position it as the pattern, with the customer's own driver models plugged in later.
8. **Expect small number differences.** Figures are deterministic but approximate in this doc; use the numbers the agent returns on the day.

## Cleanup

Step 10 of the prompt generates the cleanup script. At minimum: drop the agent, the search service, the semantic view, the database `FPA_DEMO`, the warehouse `FPA_DEMO_WH`, and the resource monitor `FPA_DEMO_RM`.

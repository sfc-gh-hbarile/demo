-- =====================================================================
-- 02 - Synthetic data (Acme Corp, all values fictional)
-- Run as FPA_DEMO_ROLE.
-- Planted story: from July 2026, EMEA Core Platform price -6%, EMEA Advisory
-- Services unit cost +12%, EMEA opex +3%. APAC Data Products price +3%.
-- =====================================================================
USE ROLE FPA_DEMO_ROLE; USE WAREHOUSE FPA_DEMO_WH; USE SCHEMA FPA_DEMO.FPA;

CREATE OR REPLACE TABLE DIM_ENTITY AS
SELECT * FROM VALUES
 (1,'Acme North America','North America','Jordan Lee','jordan.lee@example.com'),
 (2,'Acme EMEA','EMEA','Priya Raman','priya.raman@example.com'),
 (3,'Acme APAC','APAC','Kenji Mori','kenji.mori@example.com')
 AS t(entity_id, entity_name, region, finance_owner_name, finance_owner_email);

CREATE OR REPLACE TABLE DIM_PRODUCT AS
SELECT * FROM VALUES (1,'Core Platform'),(2,'Advisory Services'),(3,'Data Products') AS t(product_id, product_name);

-- Closed months Jan-Sep 2026: actuals and plan
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

-- Open months Oct-Dec 2026: forecast versions FY26_AUG (prior) and FY26_SEP (current)
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
    b.units_plan*b.base_price AS revenue_plan, b.units_plan*b.base_cost AS cogs_plan, b.units_plan*b.base_price*0.38 AS opex_plan,
    IFF(v.forecast_version='FY26_SEP',
        CASE WHEN b.entity_id=2 AND b.product_id=1 THEN 0.94 WHEN b.entity_id=1 AND b.product_id=3 THEN 1.05
             WHEN b.entity_id=3 AND b.product_id=1 THEN 1.03 ELSE 1 END, 1) AS rev_adj,
    IFF(v.forecast_version='FY26_SEP' AND b.entity_id=2 AND b.product_id=2, 1.12, 1) AS cogs_adj,
    IFF(v.forecast_version='FY26_SEP' AND b.entity_id=2, 1.03, 1) AS opex_adj
  FROM base b CROSS JOIN ver v)
SELECT forecast_version, version_date, period_month, entity_id, product_id,
  ROUND(revenue_plan*rev_adj,2) AS revenue_fcst, ROUND(cogs_plan*cogs_adj,2) AS cogs_fcst, ROUND(opex_plan*opex_adj,2) AS opex_fcst,
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

-- Planning documents (indexed by Cortex Search in script 03)
CREATE OR REPLACE TABLE ASSUMPTION_DOCS (doc_id NUMBER, doc_title VARCHAR, doc_type VARCHAR, entity VARCHAR, effective_date DATE, doc_text VARCHAR);
INSERT INTO ASSUMPTION_DOCS VALUES
 (1,'FY26 Headcount Plan','headcount','All','2026-01-15','The FY26 headcount plan ends the year at 412 FTE. Net new hiring is concentrated in Q4 with 14 planned hires: 6 in EMEA, 5 in North America, and 3 in APAC, mostly delivery and customer success roles. Q4 hiring cost is modeled at about 6 percent of forecast operating expense. Hiring is gated on the Q3 close and can be delayed by one quarter if volume softens. Approver for any change is the VP Finance.'),
 (2,'FY26 Pricing and Discount Policy','pricing','All','2026-01-15','List prices are unchanged for FY26. Discounts above 10 percent require regional finance approval. The plan assumes an average realized discount of 4 percent on Core Platform. Annual price increases of up to 3 percent are allowed at renewal with VP Sales sign-off.'),
 (3,'EMEA Q3 Business Review Notes','review','EMEA','2026-10-02','EMEA Core Platform deals closed with deeper discounts than planned in Q3 because of competitive pressure in two large accounts. Advisory Services relied on contractors to cover a delivery backlog, and contractor rates rose about 12 percent. Management expects discounting to persist through Q4. A pricing review is scheduled for November.'),
 (4,'FY26 FX and Currency Assumptions','fx','All','2026-01-15','Plan rates assume EUR/USD of 1.08 and no material change in APAC currencies. A 5 percent move in EUR is estimated to change EMEA revenue by about 5 percent and operating income by about 3 percent. Hedging covers 50 percent of forecast EUR exposure through Q4.'),
 (5,'Forecast Methodology','methodology','All','2026-01-15','The forecast is refreshed monthly after close. Baseline forecast equals plan adjusted for known run-rate changes. Every change versus the prior forecast needs a written reason in the forecast note. Scenario analysis uses approved driver logic: revenue moves with volume and price, cost of goods moves with volume, and operating expense moves with hiring timing.'),
 (6,'Variance Commentary Standards','policy','All','2026-01-15','Management commentary must state the headline variance, the top two drivers with amounts, the outlook for the next quarter, and recommended actions. Variances above 2 percent of revenue or 1 point of gross margin must be explained. All commentary is reviewed and approved by FP&A before distribution.');

-- Workflow tables (written by the review package procedures)
CREATE OR REPLACE TABLE REVIEW_PACKAGE_LOG (package_id VARCHAR, created_at TIMESTAMP_LTZ, period VARCHAR, summary VARCHAR, status VARCHAR, created_by VARCHAR, approved_by VARCHAR, approved_at TIMESTAMP_LTZ);
CREATE OR REPLACE TABLE NOTIFICATION_OUTBOX (package_id VARCHAR, recipient_name VARCHAR, recipient_email VARCHAR, region VARCHAR, message VARCHAR, status VARCHAR);

-- Validation: expect EMEA Q3 GM ~53.1% vs 57.4% plan; NA and APAC near plan
SELECT e.region, IFF(f.period_month>='2026-07-01','Q3','H1') AS per,
  ROUND(100*(1-SUM(f.cogs_actual)/SUM(f.revenue_actual)),1) AS gm_actual_pct,
  ROUND(100*(1-SUM(f.cogs_plan)/SUM(f.revenue_plan)),1) AS gm_plan_pct
FROM FACT_PL f JOIN DIM_ENTITY e USING (entity_id) GROUP BY 1,2 ORDER BY 1,2;

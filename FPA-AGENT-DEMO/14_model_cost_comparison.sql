-- =====================================================================
-- 14 - Model cost comparison: same agent spec pinned to claude-sonnet-4-6
-- FPA_AGENT uses orchestration: auto (resolved to claude-opus-4-8 in testing).
-- This copy shows the cost lever of choosing the orchestration model.
-- Result (10 Oct 2026, 4 questions, one run each): same numbers on Q1-Q4,
-- ~31% fewer credits (0.130 vs 0.190 average).
-- =====================================================================
USE ROLE FPA_DEMO_ROLE; USE WAREHOUSE FPA_DEMO_WH;

CREATE OR REPLACE AGENT FPA_DEMO.FPA.FPA_AGENT_SONNET
  COMMENT = 'Cost comparison copy (claude-sonnet-4-6) of the Acme Corp FP&A assistant: variance analysis, forecast changes, scenarios, assumptions, and review workflow (synthetic data)'
  PROFILE = '{"display_name": "FP&A Assistant", "color": "blue"}'
  FROM SPECIFICATION
  $$
  models:
    orchestration: claude-sonnet-4-6
  orchestration:
    budget:
      seconds: 90
      tokens: 32000
  instructions:
    response: "You are an FP&A assistant for finance teams. Lead with the answer and the number. Use tables for drivers. Always state the period and forecast version used. Show the numbers you relied on. Label any commentary as DRAFT pending FP&A approval. Keep answers concise."
    orchestration: "Use the analyst tool for actuals, plan, variance, margin, price, volume, cost, and forecast version comparisons. For why questions, decompose into price, volume, and unit cost effects by product and cite the forecast_note. Use the search tool for assumptions, policies, headcount plan, pricing policy, and methodology. Use run_scenario for any what-if with percentage changes to volume, price, or hiring timing; never calculate scenarios yourself. Use submit_review_package only when the user asks to prepare a review package or notify owners; always tell the user that the package is pending human approval and nothing is sent until approved. Use the fpa-variance-review skill for variance explanations and management commentary. Closed months are Jan-Sep 2026. Open months are Oct-Dec 2026. The current forecast is FY26_SEP."
    sample_questions:
      - question: "Why is gross margin below plan in EMEA this quarter?"
      - question: "What changed in the forecast since last cycle, and why?"
      - question: "What happens to operating income if volume declines 8%, hiring is delayed one quarter, and pricing rises 2%?"
      - question: "What assumptions were documented for the headcount plan?"
      - question: "Prepare the forecast review package and notify the budget owners."
  skills:
    - name: "fpa-variance-review"
      source:
        type: "STAGE"
        path: "@FPA_DEMO.FPA.AGENT_SKILLS/skills/fpa-variance-review"
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
        warehouse: "FPA_AGENT_WH"
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
        warehouse: "FPA_AGENT_WH"
    submit_review_package:
      type: "procedure"
      identifier: "FPA_DEMO.FPA.SUBMIT_REVIEW_PACKAGE"
      execution_environment:
        type: "warehouse"
        warehouse: "FPA_AGENT_WH"
  $$;

-- Ask the same questions and capture token usage from the response metadata
CREATE OR REPLACE TABLE FPA_DEMO.FPA.MODEL_COMPARE_ANSWERS (model VARCHAR, q_num INT, resp VARIANT, asked_at TIMESTAMP_LTZ);
INSERT INTO FPA_DEMO.FPA.MODEL_COMPARE_ANSWERS SELECT 'claude-sonnet-4-6', 1, TRY_PARSE_JSON(SNOWFLAKE.CORTEX.DATA_AGENT_RUN('FPA_DEMO.FPA.FPA_AGENT_SONNET', $${"messages":[{"role":"user","content":[{"type":"text","text":"Why is gross margin below plan in EMEA this quarter?"}]}]}$$)), CURRENT_TIMESTAMP();
INSERT INTO FPA_DEMO.FPA.MODEL_COMPARE_ANSWERS SELECT 'claude-sonnet-4-6', 2, TRY_PARSE_JSON(SNOWFLAKE.CORTEX.DATA_AGENT_RUN('FPA_DEMO.FPA.FPA_AGENT_SONNET', $${"messages":[{"role":"user","content":[{"type":"text","text":"What changed in the forecast since last cycle, and why?"}]}]}$$)), CURRENT_TIMESTAMP();
INSERT INTO FPA_DEMO.FPA.MODEL_COMPARE_ANSWERS SELECT 'claude-sonnet-4-6', 3, TRY_PARSE_JSON(SNOWFLAKE.CORTEX.DATA_AGENT_RUN('FPA_DEMO.FPA.FPA_AGENT_SONNET', $${"messages":[{"role":"user","content":[{"type":"text","text":"What happens to operating income if volume declines 8%, hiring is delayed one quarter, and pricing rises 2%?"}]}]}$$)), CURRENT_TIMESTAMP();
INSERT INTO FPA_DEMO.FPA.MODEL_COMPARE_ANSWERS SELECT 'claude-sonnet-4-6', 4, TRY_PARSE_JSON(SNOWFLAKE.CORTEX.DATA_AGENT_RUN('FPA_DEMO.FPA.FPA_AGENT_SONNET', $${"messages":[{"role":"user","content":[{"type":"text","text":"What assumptions were documented for the headcount plan?"}]}]}$$)), CURRENT_TIMESTAMP();

-- Price the Sonnet run from Service Consumption Table 6(d) rates (AI Credits per 1M tokens:
-- input 1.95, output 9.76, cache write 2.44, cache read 0.20) and compare with measured Opus first asks
WITH s AS (
  SELECT q_num, t.value:input_tokens:cache_read::NUMBER cr, t.value:input_tokens:cache_write::NUMBER cw,
         t.value:input_tokens:uncached::NUMBER inp, t.value:output_tokens:total::NUMBER outp
  FROM FPA_DEMO.FPA.MODEL_COMPARE_ANSWERS a, LATERAL FLATTEN(a.resp:metadata:usage:tokens_consumed) t),
sc AS (SELECT q_num, (SUM(inp)*1.95 + SUM(outp)*9.76 + SUM(cw)*2.44 + SUM(cr)*0.20)/1e6 AS sonnet_credits FROM s GROUP BY q_num),
o AS (SELECT l.question_id q_num, AVG(r.token_credits) opus_credits
      FROM FPA_DEMO.FPA.V_LOAD_TEST_COSTS l JOIN FPA_DEMO.FPA.V_AGENT_REQUESTS r ON r.request_id = l.request_id
      WHERE l.attempt = 'FIRST' GROUP BY 1)
SELECT q_num, ROUND(opus_credits, 4) opus_credits, ROUND(sonnet_credits, 4) sonnet_credits,
       ROUND(100 * (1 - sonnet_credits / opus_credits)) pct_cheaper
FROM sc JOIN o USING (q_num) ORDER BY 1;

-- Billing reconciliation: per-request agent credits vs the metered CORTEX_AGENTS line
SELECT (SELECT ROUND(SUM(token_credits), 4) FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AGENT_USAGE_HISTORY
        WHERE start_time >= '2026-10-09') AS agent_view_credits,
       (SELECT ROUND(SUM(credits_used), 4) FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY
        WHERE service_type = 'CORTEX_AGENTS' AND usage_date >= '2026-10-09') AS metered_cortex_agents_credits;

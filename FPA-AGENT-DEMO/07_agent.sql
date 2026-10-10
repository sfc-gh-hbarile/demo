-- =====================================================================
-- 07 - Cortex Agent: semantic view + search + custom tools + chart + skill
-- Prereqs: scripts 02-06. Owned by FPA_DEMO_ROLE (so USAGE is implicit).
-- =====================================================================
USE ROLE FPA_DEMO_ROLE; USE WAREHOUSE FPA_DEMO_WH;

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

-- Validation: expect owner FPA_DEMO_ROLE, 5 tools, 1 skill
DESCRIBE AGENT FPA_DEMO.FPA.FPA_AGENT;

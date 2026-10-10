# Acme Corp FP&A Agent Demo

A self-contained FP&A demo for Snowflake. A Cortex Agent answers variance, forecast, scenario, and policy questions for the fictional company **Acme Corp**, and drafts a review package that waits for human approval. **All data is synthetic.**

The agent includes:

| Component | Object | Purpose |
|---|---|---|
| Semantic view (Cortex Analyst tool `fpa_analyst`) | `FPA_DEMO.FPA.FPA_SEMANTIC_VIEW` | Approved metrics for actuals, plan, and forecast versions |
| Cortex Search tool `fpa_search` | `FPA_DEMO.FPA.FPA_ASSUMPTIONS_SEARCH` | Planning documents and policies |
| Custom tool `run_scenario` | `FPA_DEMO.FPA.RUN_SCENARIO` | What-ifs on the Oct-Dec forecast using approved driver logic |
| Custom tool `submit_review_package` | `FPA_DEMO.FPA.SUBMIT_REVIEW_PACKAGE` | Creates a PENDING_APPROVAL package with held notifications |
| Chart tool | `data_to_chart` | Charts from query results |
| Agent skill | `@FPA_DEMO.FPA.AGENT_SKILLS/skills/fpa-variance-review` | Repeatable variance-review method and commentary template |
| Orchestration and response instructions | in the agent spec | Tool routing, period and version rules, DRAFT labelling |
| Human-only step (not given to the agent) | `FPA_DEMO.FPA.APPROVE_REVIEW_PACKAGE` | Releases held notifications |

## Clean demo login

Every demo object is owned by **`FPA_DEMO_ROLE`**. Log in as **`FPA_DEMO_USER`**, whose only role is `FPA_DEMO_ROLE`, and you see only the demo objects instead of everything ACCOUNTADMIN sees.

- Default role `FPA_DEMO_ROLE`, default warehouse `FPA_DEMO_WH`, default namespace `FPA_DEMO.FPA`, secondary roles off. Cortex Agents use the user's **default** role and warehouse.
- Grants: ownership of `FPA_DEMO` and `FPA_DEMO_WH`, `SNOWFLAKE.CORTEX_USER`, `SNOWFLAKE.USAGE_VIEWER` (for the cost queries), and MONITOR on `FPA_DEMO_RM`.
- `FPA_DEMO_ROLE` is also granted to SYSADMIN and to the admin who runs the build.
- Set the password yourself after the build. Do not commit it:
  ```sql
  ALTER USER FPA_DEMO_USER SET PASSWORD = '<choose-a-password>' MUST_CHANGE_PASSWORD = FALSE;
  ```

## Files (run in order)

| # | File | Run as | What it does | Validation |
|---|---|---|---|---|
| 01 | `01_setup_role_user_env.sql` | ACCOUNTADMIN | Role, user, database, schema, warehouse, resource monitor (10 credits/month), grants | Demo user defaults shown |
| 02 | `02_synthetic_data.sql` | FPA_DEMO_ROLE | Dimensions, `FACT_PL` (Jan-Sep actuals and plan), `FACT_FORECAST` (Oct-Dec, FY26_AUG and FY26_SEP), 6 planning docs, workflow tables | EMEA Q3 GM **53.1% vs 57.4%** plan |
| 03 | `03_cortex_search.sql` | FPA_DEMO_ROLE | Cortex Search service over the docs | "headcount plan hiring" returns **FY26 Headcount Plan** |
| 04 | `04_semantic_view.sql` | FPA_DEMO_ROLE | Semantic view with metrics and AI instructions | EMEA Q3 gap: Advisory Services **-8.4 pts**, Core Platform **-1.9 pts** |
| 05 | `05_procedures.sql` | FPA_DEMO_ROLE | Scenario, submit, and approve procedures, with a self-cleaning test | Baseline OI $3.449M vs $3.696M plan; scenario $3.378M |
| 06 | `06_agent_skill_upload.sql` | FPA_DEMO_ROLE | Creates the stage and uploads `agent_skills/fpa-variance-review/SKILL.md` (needs a client that supports PUT) | `LS` shows SKILL.md |
| 07 | `07_agent.sql` | FPA_DEMO_ROLE | Creates `FPA_DEMO.FPA.FPA_AGENT` | `DESCRIBE AGENT` shows 5 tools and 1 skill |
| 08 | `08_test_agent_questions.sql` | FPA_DEMO_ROLE | Runs the 5 demo questions through `DATA_AGENT_RUN`, then resets the workflow tables | See expected results below |
| 09 | `09_cost_monitoring.sql` | FPA_DEMO_ROLE | Agent token credits, warehouse credits, resource monitor | May be empty for a few hours (ACCOUNT_USAGE lag) |
| 99 | `99_cleanup.sql` | ACCOUNTADMIN | Drops everything. **Run only when finished.** | |

`FPA_Agentic_Finance_Demo_Prompt.md` is the original build prompt.

## The planted story

- From July 2026, **EMEA Core Platform** price is down 6% (competitive discounting) and **EMEA Advisory Services** unit cost is up 12% (contractor rates). EMEA opex is up 3%.
- APAC Data Products price is up 3%.
- Forecast **FY26_AUG** (prior cycle) assumed EMEA would recover. **FY26_SEP** (current cycle) carries the EMEA pressures into Q4 and raises NA Data Products (+5%) and APAC Core Platform (+3%). Every changed row has a `forecast_note`.

## Demo script (5 questions)

Ask these in Snowsight (**AI & ML » Agents » FP&A Assistant**) or in CoWork, logged in as `FPA_DEMO_USER`.

| # | Question | Expected tools | Expected answer |
|---|---|---|---|
| 1 | Why is gross margin below plan in EMEA this quarter? | skill, fpa_analyst, fpa_search | 53.1% vs 57.4% (-4.3 pts). Advisory Services unit cost +$208/unit (about $165K); Core Platform price -6% (about $150K). Reasons cited from the EMEA Q3 review notes |
| 2 | What changed in the forecast since last cycle, and why? | fpa_analyst, fpa_search | FY26_SEP vs FY26_AUG: EMEA Advisory Services -$199K, EMEA Core Platform -$179K, EMEA Data Products -$13K, NA Data Products +$94K, APAC Core Platform +$50K operating income. Net -$247K, with notes |
| 3 | What happens to operating income if volume declines 8%, hiring is delayed one quarter, and pricing rises 2%? | run_scenario | $3.378M vs $3.449M baseline (-$71K, -2.1%). The $439K hiring saving offsets most of the volume loss |
| 4 | What assumptions were documented for the headcount plan? | fpa_search | 412 FTE; 14 Q4 hires (6 EMEA, 5 NA, 3 APAC); about 6% of opex; gated on Q3 close; VP Finance approves |
| 5 | Prepare the forecast review package and notify the budget owners. | submit_review_package | Package `RP-…` in PENDING_APPROVAL with 3 held notifications; nothing is sent until approved |

**Approval step (human, after Q5):**
```sql
SELECT * FROM FPA_DEMO.FPA.REVIEW_PACKAGE_LOG;            -- PENDING_APPROVAL
CALL FPA_DEMO.FPA.APPROVE_REVIEW_PACKAGE('<package_id>');  -- the human approves
SELECT * FROM FPA_DEMO.FPA.NOTIFICATION_OUTBOX;           -- READY_TO_SEND
```
**Reset before the next run:**
```sql
DELETE FROM FPA_DEMO.FPA.REVIEW_PACKAGE_LOG; DELETE FROM FPA_DEMO.FPA.NOTIFICATION_OUTBOX;
```

## Notes

- `CREATE AGENT` is a schema-level privilege, not an account-level one. The demo role owns the schema, so it has the privilege without a grant.
- `SNOWFLAKE.CORTEX.DATA_AGENT_RUN` requires a constant request string, which is why script 08 runs one statement per question.
- To edit the skill, change `agent_skills/fpa-variance-review/SKILL.md` and re-run script 06. The agent reads the skill from the stage on demand, so you don't need to recreate the agent.
- Cost guardrail: `FPA_DEMO_RM` notifies at 80% and suspends `FPA_DEMO_WH` at 100% of 10 credits per month.

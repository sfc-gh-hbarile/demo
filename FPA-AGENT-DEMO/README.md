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
| 09 | `09_cost_monitoring.sql` | FPA_DEMO_ROLE | Agent cost summary, per user, per request, by service and model; Cortex Search; warehouse; resource monitor (see **Monitoring agent costs**) | May be empty for a few hours (ACCOUNT_USAGE lag) |
| 10 | `10_cost_views.sql` | FPA_DEMO_ROLE | Cost model views: `V_AGENT_REQUEST_COSTS`, `V_AGENT_REQUESTS`, `V_LOAD_TEST_COSTS`, `V_COST_CALIBRATION`, plus the `AGENT_LOAD_TEST_LOG` table | Granular credits match `TOKEN_CREDITS` for every request |
| 11 | `11_load_test.sql` | FPA_DEMO_ROLE | `RUN_AGENT_LOAD_TEST(n, label)`: asks the agent n questions (first asks, then repeats) and logs each call | 8/8 calls succeed; costs appear after the usage lag |
| 12 | `12_deploy_cost_estimator_app.sql` + `cost_estimator_app/` | FPA_DEMO_ROLE | Deploys the **FP&A Agent Cost Estimator** Streamlit app | `SHOW STREAMLITS` returns one row |
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

## Monitoring agent costs

### What an agent call costs

One question to `FPA_AGENT` can incur three kinds of cost:

| Cost | Where it comes from | Where to see it |
|---|---|---|
| **Agent token credits** | LLM tokens for orchestration (planning, choosing tools, writing the answer) and for Cortex Analyst generating SQL from the semantic view | `SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AGENT_USAGE_HISTORY.TOKEN_CREDITS`, split by service and model in `CREDITS_GRANULAR` |
| **Warehouse compute** | SQL the tools run on `FPA_DEMO_WH`: Analyst queries, `RUN_SCENARIO`, `SUBMIT_REVIEW_PACKAGE` | Per request: `METADATA:sql_query_credits` in the agent view. In total: `WAREHOUSE_METERING_HISTORY` |
| **Cortex Search** | Serving and indexing for `FPA_ASSUMPTIONS_SEARCH` (billed on its own, not per agent call) | `SNOWFLAKE.ACCOUNT_USAGE.CORTEX_SEARCH_DAILY_USAGE_HISTORY` |

Each row in `CORTEX_AGENT_USAGE_HISTORY` is one agent request, with user, role, interface (`metadata:interaction_interface`, for example `sql_function` or `agent_admin_ui`), tokens, and credits. **Requests made in Snowflake CoWork are not in this view**; they are recorded in `SNOWFLAKE_COWORK_USAGE_HISTORY`.

### Observed cost in this account (synthetic test run, 9 Oct 2026)

| Metric | Value |
|---|---|
| Agent requests | 6 |
| Token credits | 1.28 total, about **0.21 per question** |
| Warehouse SQL credits attributed to agent calls | 0.045 |
| `FPA_DEMO_WH` total for the build day | about 0.19 (includes setup and testing) |

Multi-step questions such as the EMEA "why" question and the review package use the most tokens, because the agent loads the skill and makes several tool calls. Single-tool questions such as the headcount lookup or the scenario cost much less.

### How to monitor

Run `09_cost_monitoring.sql` as `FPA_DEMO_ROLE`. It includes:
1. **Summary:** requests, token credits, SQL credits, average credits per request
2. **Daily by user:** credits per day per user
3. **Per request:** interface, tokens, and credits for the last 20 calls
4. **By service and model:** orchestration (`cortex_agents`) vs `cortex_analyst`, from `CREDITS_GRANULAR`
5. **Cortex Search:** credits by day and consumption type
6. **Warehouse:** daily `FPA_DEMO_WH` credits
7. **Resource monitor:** quota used vs 10 credits per month

Notes:
- **Latency:** `ACCOUNT_USAGE` views lag by up to a few hours. Check costs after the demo, not during it.
- **Access:** `FPA_DEMO_ROLE` reads these views through the `SNOWFLAKE.USAGE_VIEWER` database role, so the demo user doesn't need ACCOUNTADMIN.
- **Guardrail scope:** `FPA_DEMO_RM` caps only warehouse compute; it suspends `FPA_DEMO_WH` at 10 credits per month. Agent token credits are serverless, so the resource monitor does not cap them. Track them with the queries above, or set a Snowflake budget for AI spend.
- **Plain language:** in CoCo, ask: *"Using cost-intelligence, show Cortex Agent credits for FPA_AGENT and warehouse credits for FPA_DEMO_WH by day for the last 7 days."*

## Cost estimator (projecting customer cost)

### Three steps
1. **Measure:** run `CALL FPA_DEMO.FPA.RUN_AGENT_LOAD_TEST(8, 'smoke');` (script 11). It asks the 4 read-only demo questions, then asks them again, and logs each call. It costs about 1.5 credits and takes about 8 minutes. For more data, run `(10,'tier_10')`, `(25,'tier_25')` or `(50,'tier_50')`, at roughly 0.15–0.2 credits per call.
2. **Wait** a few hours for `ACCOUNT_USAGE`. `V_COST_CALIBRATION` then reports average credits for a first ask and for a repeat, and the cache shares.
3. **Project:** open **Snowsight » Projects » Streamlit » FP&A Agent Cost Estimator** and adjust the inputs.

### Dashboard inputs
| Input | Default |
|---|---|
| Price per credit | **$3.00** (editable) |
| Number of users | 25 |
| Questions per user per day | presets **10 / 25 / 50**, or custom |
| Working days per month | 21 (weekly = 5 days, yearly = 12 months) |
| Repeated questions % | 30% |
| Credits per question | measured first-ask and repeat values, or your own override |
| Warehouse cost | attributed SQL credits per question, **or** warehouse awake hours per day × 1 credit/hour (XS) |
| Cortex Search credits per day | measured 14-day average |

**Outputs:**
- daily, weekly, monthly and yearly credits and dollars, split into agent tokens, warehouse and search
- a comparison of 10, 25 and 50 questions per user
- a chart of monthly cost by number of users
- the observed actuals: requests measured, credits per question, cache-hit %, cache-write share, and first ask vs repeat

### Formula
```
questions/day   = users × questions per user per day
agent credits   = questions × (1 - repeat%) × first_ask_credits + questions × repeat% × repeat_credits
warehouse       = questions × sql_credits_per_question     (or awake_hours × 1 credit/hr for XS)
total credits   = agent + warehouse + search_per_day;  week = ×5, month = ×working days, year = month × 12
cost ($)        = total credits × price per credit
```
I unit-tested the app's formula against a hand calculation (25 users × 10 questions, 30% repeats, 0.25/0.15 credits, $3), and it matched for every period and for both warehouse methods.

### Measured in this account (synthetic demo, 9 Oct 2026, model `claude-opus-4-8` via `auto`)
| Segment | Calls | Avg token credits | Cache-write share | Input served from cache |
|---|---|---|---|---|
| All requests | 15 | 0.181 | 55% | 83% |
| Load test: first ask | 5 | **0.196** | 58% | 81% |
| Load test: repeat | 4 | **0.114** (42% cheaper) | 42% | 89% |

Warehouse SQL attributed to agent calls averaged about 0.003 credits per question. Cortex Search was close to 0 for this small corpus.

**What the caching numbers mean:**
- Most of the cost is **cache writes**: the agent's instructions, tool definitions and context are written to the model's prompt cache. A recent repeat reuses more of that cache.
- The saving depends on the question:

| Question | First ask | Repeat | Saving |
|---|---|---|---|
| Q2 forecast changes | 0.341 | 0.177 | 48% |
| Q4 headcount | 0.118 | 0.045 | 62% |
| Q1 EMEA margin | 0.202 | 0.188 | about 7% |
| Q3 scenario | 0.053 | 0.047 | about 12% |

- The answer itself is **not** cached; every repeat still runs the tools. The saving comes only from token-level prompt caching, and only while the cache is warm (calls minutes apart). Don't assume a fixed discount.
- These figures come from a small sample (one call per question per attempt). Run larger tiers before quoting a customer.

### Example: measured rates, 25 users, 30% repeats, $3.00/credit
| Questions / user / day | Daily | Weekly | Monthly | Yearly |
|---|---|---|---|---|
| 10 | 43.6 cr / $131 | 218 cr / $654 | 915 cr / $2,746 | 10,982 cr / $32,946 |
| 25 | 109 cr / $327 | 545 cr / $1,634 | 2,288 cr / $6,864 | 27,455 cr / $82,366 |
| 50 | 218 cr / $654 | 1,090 cr / $3,268 | 4,576 cr / $13,728 | 54,911 cr / $164,732 |

**Caveats:**
- These are estimates based on this demo's question mix, tools and model.
- Longer multi-turn threads, more tools, different models or a customer's own questions will change the cost per question. Re-measure with their questions.
- The warehouse "attributed" method understates real warehouse cost, because XS warehouses bill a 60-second minimum on each resume. For steady use, use the "awake hours" method.

## Notes

- `CREATE AGENT` is a schema-level privilege, not an account-level one. The demo role owns the schema, so it has the privilege without a grant.
- `SNOWFLAKE.CORTEX.DATA_AGENT_RUN` requires a constant request string, which is why script 08 runs one statement per question.
- To edit the skill, change `agent_skills/fpa-variance-review/SKILL.md` and re-run script 06. The agent reads the skill from the stage on demand, so you don't need to recreate the agent.
- Cost guardrail: `FPA_DEMO_RM` notifies at 80% and suspends `FPA_DEMO_WH` at 100% of 10 credits per month.

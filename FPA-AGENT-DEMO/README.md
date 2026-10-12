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

## Presentation

**[FPA_Agent_Demo_Presentation.html](FPA_Agent_Demo_Presentation.html)** is a 14-slide presenter aid structured as **Tell, Show, Tell**. Download it and open it in a browser; use the arrow keys or the on-screen buttons to move between slides.

| Phase | Slides | Content |
|---|---|---|
| Tell | 1 to 3 | The FP&A problem, the planted EMEA story, and the architecture that was built |
| Show | 4 to 8 | Run sheet for the five questions with expected answers, then one slide per capability: variance, forecast change and scenario, documents and the approval workflow, and cost |
| Tell | 9 to 11 | What the audience saw, nine ways to extend it for FP&A teams, and a six-week path from demo to pilot |
| Appendix | 12 to 14 | Build and run order; presenter checklist with reset steps, timing, and troubleshooting; built-in cost tools vs the demo views |

Every number in the deck comes from this demo's validations and tagged cost runs. Update the deck if you change the data or re-measure costs.

## Clean demo login

Every demo object is owned by **`FPA_DEMO_ROLE`**. Log in as **`FPA_DEMO_USER`**, whose only role is `FPA_DEMO_ROLE`, and you see only the demo objects instead of everything ACCOUNTADMIN sees.

- Default role `FPA_DEMO_ROLE`, default warehouse `FPA_AGENT_WH` (set in script 13; script 01 starts it on `FPA_DEMO_WH`), default namespace `FPA_DEMO.FPA`, secondary roles off. Cortex Agents use the user's **default** role and warehouse.
- Grants: ownership of `FPA_DEMO`, `FPA_DEMO_WH` and `FPA_AGENT_WH`; `SNOWFLAKE.CORTEX_USER`; `SNOWFLAKE.USAGE_VIEWER` (metering, agent and search usage, query attribution); `SNOWFLAKE.GOVERNANCE_VIEWER` (`QUERY_HISTORY`, needed to find the agent's tagged tool queries); and MONITOR on `FPA_DEMO_RM`.
- Streamlit apps run with **only** the owner role (no secondary roles), so every view the dashboard reads must be readable by `FPA_DEMO_ROLE` alone. Test with `USE SECONDARY ROLES NONE;`.
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
| 05 | `05_procedures.sql` | FPA_DEMO_ROLE | Scenario, submit, approve, and reset procedures, `V_REVIEW_PACKAGE_STATUS`, with a self-cleaning test | Baseline OI $3.449M vs $3.696M plan; scenario $3.378M |
| 06 | `06_agent_skill_upload.sql` | FPA_DEMO_ROLE | Creates the stage and uploads `agent_skills/fpa-variance-review/SKILL.md` (needs a client that supports PUT) | `LS` shows SKILL.md |
| 07 | `07_agent.sql` | FPA_DEMO_ROLE | Creates `FPA_DEMO.FPA.FPA_AGENT` | `DESCRIBE AGENT` shows 5 tools and 1 skill |
| 08 | `08_test_agent_questions.sql` | FPA_DEMO_ROLE | Runs the 5 demo questions through `DATA_AGENT_RUN`, then resets the workflow tables | See expected results below |
| 09 | `09_cost_monitoring.sql` | FPA_DEMO_ROLE | Agent cost summary, per user, per request, by service and model; Cortex Search; warehouse; resource monitor (see **Monitoring agent costs**) | May be empty for a few hours (ACCOUNT_USAGE lag) |
| 10 | `10_cost_views.sql` | FPA_DEMO_ROLE | Cost model views: `V_AGENT_REQUEST_COSTS`, `V_AGENT_REQUESTS`, `V_LOAD_TEST_COSTS`, `V_COST_CALIBRATION`, plus the `AGENT_LOAD_TEST_LOG` table | Granular credits match `TOKEN_CREDITS` for every request |
| 11 | `11_load_test.sql` | FPA_DEMO_ROLE | `RUN_AGENT_LOAD_TEST(n, label)`: asks the agent n questions (first asks, then repeats) and logs each call | 8/8 calls succeed; costs appear after the usage lag |
| 12 | `12_deploy_cost_estimator_app.sql` + `cost_estimator_app/` | FPA_DEMO_ROLE | Deploys the **FP&A Agent Cost Estimator** Streamlit app | `SHOW STREAMLITS` returns one row |
| 13 | `13_agent_warehouse_tagging.sql` | ACCOUNTADMIN, then FPA_DEMO_ROLE | Dedicated `FPA_AGENT_WH` for agent tools, `COST_RUNS` table, `START_COST_RUN` / `END_COST_RUN` | Tagged warehouse credits = agent-reported SQL credits for 20 of 20 requests |
| 14 | `14_model_cost_comparison.sql` | FPA_DEMO_ROLE | `FPA_AGENT_SONNET` (same spec, claude-sonnet-4-6), the 4-question comparison, and billing reconciliation | Same answers; about 31% fewer credits; agent credits = metered `CORTEX_AGENTS` |
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

### Review-package workflow (Q5): run it, approve it, reset it

The 3 approvers (Jordan Lee, Priya Raman, Kenji Mori) are stored in `DIM_ENTITY` and are **never deleted**. Each time the agent submits a package, `SUBMIT_REVIEW_PACKAGE` queues one held notification per owner.

```sql
-- 0. Before the demo: start clean (owners are untouched)
CALL FPA_DEMO.FPA.RESET_DEMO_WORKFLOW();

-- 1. In a NEW agent chat ask: "Prepare the forecast review package and notify the budget owners."
--    The agent returns a package_id such as RP-20261009212033.

-- 2. Show it is held: 1 package PENDING_APPROVAL, 3 notifications HELD_UNTIL_APPROVED
SELECT * FROM FPA_DEMO.FPA.V_REVIEW_PACKAGE_STATUS;

-- 3. The human approves. Use the id exactly, without < >; the procedure also strips them if pasted.
CALL FPA_DEMO.FPA.APPROVE_REVIEW_PACKAGE('RP-20261009212033');
--    returns {"status":"APPROVED","notifications_released":3}

-- 4. Show the result: package APPROVED, 3 notifications READY_TO_SEND
SELECT * FROM FPA_DEMO.FPA.V_REVIEW_PACKAGE_STATUS;

-- 5. After the demo: reset for next time
CALL FPA_DEMO.FPA.RESET_DEMO_WORKFLOW();
```

**Troubleshooting:**
- **Asking again doesn't create a package:** start a **new chat**. In the same thread the agent sees it already prepared one and may not call the tool again. Check with `SELECT * FROM FPA_DEMO.FPA.REVIEW_PACKAGE_LOG;`.
- **Approval returns `NOT_FOUND_OR_NOT_PENDING`:** the id doesn't exist (for example, the tables were reset after it was created) or it's already approved. The response lists any `pending_packages`.
- **Use `RESET_DEMO_WORKFLOW()` instead of manual `DELETE`s**, and only between demo runs, never between submit and approve.

## Understanding and controlling agent costs

### What one question costs
Each question asked to `FPA_AGENT` can incur three kinds of cost. They are billed in two different units.

| Cost | What drives it | Billed in | Price used in this demo |
|---|---|---|---|
| **Agent tokens** | LLM tokens for orchestration (planning, choosing tools, writing the answer) and Cortex Analyst SQL generation | **AI Credits** | $2.00 on demand (global). Capacity contracts are tiered; see Table 2(b) of the Snowflake Service Consumption Table |
| **Cortex Search** | Indexed data served by `FPA_ASSUMPTIONS_SEARCH` (per GB per month, not per question) | **AI Credits** | $2.00 |
| **Warehouse compute** | SQL the agent's tools run on `FPA_AGENT_WH`: Analyst queries, `RUN_SCENARIO`, `SUBMIT_REVIEW_PACKAGE` | **Platform Credits** | $3.00 (Enterprise, AWS US East); your contract rate applies |

Token rates per million tokens depend on the orchestration model and are published in **Table 6(d)** of the Service Consumption Table (Cortex Agents). For example, `claude-opus-4-8` is 3.25 input, 16.26 output, 4.07 cache write, and 0.33 cache read AI Credits per million tokens.

### Measured in this demo (synthetic data, October 2026)
| Measure | Value |
|---|---|
| Orchestration model | `auto`, which resolved to `claude-opus-4-8` |
| Context sent per question | about 148K input tokens (instructions, tool definitions, semantic view, skill, tool results); 81% served from the prompt cache |
| Agent tokens, first ask | **0.196 AI Credits**, about $0.39 |
| Agent tokens, repeated question | **0.114 AI Credits**, about $0.23 (42% less, from prompt caching) |
| Warehouse per question | about **0.003 Platform Credits**, about $0.01 |
| **Total per question** | **about $0.40 first ask, $0.24 repeat** |
| Share of cost | about 97% AI tokens, 3% warehouse |
| Same agent pinned to `claude-sonnet-4-6` (`FPA_AGENT_SONNET`, script 14) | same answers on Q1 to Q4, about **31% fewer credits** (0.130 vs 0.190 average, about $0.27 per question) |

Per question, measured first ask vs repeat (AI Credits):

| Question | First ask | Repeat | Saving |
|---|---|---|---|
| Q1 EMEA margin | 0.202 | 0.188 | about 7% |
| Q2 forecast changes | 0.341 | 0.177 | 48% |
| Q3 scenario | 0.053 | 0.047 | about 12% |
| Q4 headcount | 0.118 | 0.045 | 62% |

Multi-step questions (the EMEA "why" question, the forecast comparison, the review package) cost the most, because the agent loads the skill and makes several tool calls. Single-tool questions cost much less. Only the model's prompt is cached, never the answer, so every repeat still runs the tools; the saving applies while the cache is warm (calls a few minutes apart). These figures come from a small sample on the demo's questions.

### How the numbers were verified
| Check | Result |
|---|---|
| Rates | The credits billed per million tokens match the published rates in Service Consumption Table 6(d). |
| Bill | Per-request credits in `CORTEX_AGENT_USAGE_HISTORY` (4.059) equal the `CORTEX_AGENTS` line in `METERING_DAILY_HISTORY` (4.059) for the same period. |
| Warehouse | Per-question warehouse credits from tagged agent queries equal the agent's own reported `sql_query_credits` for every request (20 of 20). |
| Snowsight | Snowsight **Cost Management** shows the same totals; see below. |

### Levers that reduce cost
- **Pick the orchestration model.** `auto` picks a model for you; pinning a smaller model (for example `claude-sonnet-4-6`) cut credits by about 31% here with the same answers. Test accuracy on your own questions first.
- **Keep the context lean.** Instructions, tool descriptions, and the semantic view are sent with every question. Shorter instructions and fewer, well-described tools reduce tokens.
- **Use one thread for follow-ups.** Follow-up questions in the same conversation reuse the prompt cache.
- **Use approved tools for heavy logic.** A stored procedure (like `RUN_SCENARIO`) is cheaper and more reliable than having the model reason through calculations.
- **Keep the warehouse small and isolated.** An XS warehouse with `AUTO_SUSPEND = 60` dedicated to the agent keeps warehouse cost at about 3% and makes it easy to see.

### Built-in Snowflake cost tools (out of the box)
Use these first. They need no setup and are the source of truth for the bill.

| Where | What to look at | What it tells you |
|---|---|---|
| **Snowsight » Admin » Cost Management » Consumption** | Usage Type **AI Services** → service type **CORTEX_AGENTS** (also CORTEX_SEARCH, SNOWFLAKE_COWORK) | Daily AI Credits for all agents in the account |
| Same page | Usage Type **Compute**, Service Type **Warehouse** → **FPA_AGENT_WH** | Warehouse credits behind the agent, including idle time |
| **Cost Management » Budgets** | The account budget, or a custom budget that contains `FPA_AGENT` (Cortex Agents are supported objects) | Monthly spending limit with forecast-based notifications, optionally calling a stored procedure. This is the control for AI Credits. Refreshes up to every 6.5 hours (hourly as a low-latency budget) |
| **Budgets » per-user quotas** | Credit limits for individual users | Caps how much one user can consume |
| **Cost Management » Resource Monitors** | `FPA_DEMO_RM` | Caps and suspends warehouses (`FPA_DEMO_WH`, `FPA_AGENT_WH`). Doesn't cover AI Credits |
| **Cost Management » Anomalies** | Unusual daily spend | Alerts when consumption deviates from the normal pattern |
| `SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY` | `SERVICE_TYPE = 'CORTEX_AGENTS'` | The same daily totals in SQL |
| `SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AGENT_USAGE_HISTORY` | One row per agent request | User, agent, interface, tokens, and credits, split by model and token type |
| `SNOWFLAKE.ACCOUNT_USAGE.SNOWFLAKE_COWORK_USAGE_HISTORY` | Requests made in Snowflake CoWork | CoWork usage, which isn't in the agent usage view |
| **Cortex Code** | *"Using cost-intelligence, show Cortex Agent credits for FPA_AGENT and warehouse credits for FPA_AGENT_WH by day for the last 7 days."* | The same information in plain language |

When comparing Snowsight with SQL, note that Snowsight groups days in **UTC** and its warehouse chart shows compute credits without cloud services. All of these sources update hourly, with a delay of up to a few hours.

### Built-in tools vs. the demo's cost views
| | Snowsight Cost Management | Demo views and estimator |
|---|---|---|
| Purpose | The bill: what the account spent | Unit economics: what one question costs, and why |
| Granularity | Per day or hour, per warehouse or service type | Per question and per tagged run |
| Agent cost | One `CORTEX_AGENTS` line for all agents | Per agent and per request, split into cache read, cache write, input, and output |
| Warehouse behind the agent | Whole-warehouse totals | Only the queries the agent ran (exact, from `QUERY_ATTRIBUTION_HISTORY`), plus the dedicated warehouse for idle time |
| Excludes build and test work | No | Yes, by run tagging |
| First ask vs repeat, model comparison | No | Yes |
| Projection by users and questions per user | No | Yes, with separate AI Credit and Platform Credit prices |
| Budgets, per-user quotas, resource monitors, anomaly alerts | **Yes** | No; use the built-in tools |
| Update latency | Hourly, up to a few hours | Same, and per-query attribution can take several hours longer |

Use both: Snowsight to monitor and control spend, and the demo views to explain cost per question and to forecast. On a period with only tagged agent activity, `V_RUN_COSTS` totals match Snowsight's `CORTEX_AGENTS` line plus the `FPA_AGENT_WH` line.

### Monitoring queries
Run `09_cost_monitoring.sql` as `FPA_DEMO_ROLE`. It includes:
1. **Summary:** requests, token credits, SQL credits, average credits per request
2. **Daily by user:** credits per day per user
3. **Per request:** interface, tokens, and credits for the last 20 calls
4. **By model and token type:** cache read, cache write, and input and output credits
5. **Cortex Search:** credits by day and consumption type
6. **Warehouse:** daily warehouse credits
7. **Resource monitor:** quota used vs 10 credits per month

`FPA_DEMO_ROLE` reads these views through the `SNOWFLAKE.USAGE_VIEWER` and `SNOWFLAKE.GOVERNANCE_VIEWER` database roles, so the demo user doesn't need ACCOUNTADMIN.

## Cost estimator (projecting cost at scale)

### Three steps
1. **Measure:** `CALL FPA_DEMO.FPA.RUN_AGENT_LOAD_TEST(8, 'smoke');` (script 11) asks the 4 read-only demo questions twice and logs each call. It uses about 1.5 AI Credits and takes about 8 minutes. For more data, run `(10,'tier_10')`, `(25,'tier_25')` or `(50,'tier_50')`; each call uses roughly 0.05 to 0.35 AI Credits.
2. **Wait** a few hours for `ACCOUNT_USAGE`. `V_COST_CALIBRATION` then reports average credits for a first ask and a repeat, and the cache shares.
3. **Project:** open the **FP&A Agent Cost Estimator** Streamlit app and adjust the inputs. To create it, paste `cost_estimator_app/streamlit_app_paste_into_snowsight.py` into a new Snowsight Streamlit app (warehouse runtime).

### Dashboard inputs
| Input | Default |
|---|---|
| AI Credit price | **$2.00** (editable). Agent tokens and Cortex Search bill in AI Credits |
| Warehouse (Platform) Credit price | **$3.00** (editable). Warehouse compute bills in Platform Credits |
| Number of users | 25 |
| Questions per user per day | presets **10 / 25 / 50**, or custom |
| Working days per month | 21 (weekly = 5 days, yearly = 12 months) |
| Repeated questions % | 30% |
| Credits per question | measured first-ask and repeat values from selected tagged runs, or your own values |
| Warehouse cost | attributed SQL credits per question, **or** warehouse awake hours per day × 1 credit per hour (XS) |
| Cortex Search credits per day | measured 14-day average |

**Outputs:**
- daily, weekly, monthly, and yearly credits and dollars, split into agent tokens, warehouse, and search
- AI token, warehouse, and search share of cost
- a comparison of 10, 25, and 50 questions per user
- a chart of monthly cost by number of users
- observed actuals: requests measured, credits per question, cache-hit %, cache-write share, first ask vs repeat, and tagged runs

### Formula
```
questions/day   = users × questions per user per day
agent credits   = questions × (1 - repeat%) × first_ask_credits + questions × repeat% × repeat_credits
warehouse       = questions × sql_credits_per_question     (or awake_hours × 1 credit/hr for XS)
total credits   = agent + warehouse + search_per_day;  week = ×5, month = ×working days, year = month × 12
cost ($)        = (agent + search credits) × AI Credit price + warehouse credits × Platform Credit price
```
Check: one first-ask question = 0.196 × $2.00 + 0.003 × $3.00 = **$0.40**.

### Example: 25 users, 30% repeats, measured rates, $2.00 per AI Credit and $3.00 per Platform Credit
| Questions / user / day | Daily | Weekly | Monthly | Yearly |
|---|---|---|---|---|
| 10 | $88 | $440 | $1,847 | $22,163 |
| 25 | $220 | $1,099 | $4,617 | $55,408 |
| 50 | $440 | $2,199 | $9,235 | $110,817 |

**To estimate your own cost:**
- Use your contract's AI Credit and Platform Credit prices.
- Measure with your own questions (`RUN_AGENT_LOAD_TEST` or a tagged pilot session).
- Compare `auto` with a pinned orchestration model.
- Longer multi-turn conversations, more tools, or larger documents change the cost per question.
- The "attributed" warehouse method counts only query time. When the warehouse is idle most of the day, the 60-second minimum on each resume adds cost; use the "awake hours" method instead.

## Accurate cost attribution (tagged runs)

Use this method to count **only** the agent's work, never the build, setup, app, or anything else on the account.

### What gets tagged and how
| Cost | Exact source | How it is linked to a question |
|---|---|---|
| **AI tokens** | `CORTEX_AGENT_USAGE_HISTORY.TOKEN_CREDITS` | One row per agent request (`REQUEST_ID`) |
| **Warehouse compute behind the agent** | `QUERY_ATTRIBUTION_HISTORY.CREDITS_ATTRIBUTED_COMPUTE` | Snowflake tags every agent tool query with `QUERY_TAG = 'cortex-agent-<request_id>'`. Procedure calls from the Snowsight playground or CoWork are tagged `'snowflake-intelligence-<request_id>'`. Statements *inside* a stored procedure aren't tagged; they roll up to the tagged CALL through `ROOT_QUERY_ID`. |
| **Full warehouse cost incl. idle** | `WAREHOUSE_METERING_HISTORY` for **`FPA_AGENT_WH`** | The agent's tools (`fpa_analyst`, `run_scenario`, `submit_review_package`) run only on this dedicated warehouse, so its metering is agent-only. It's hourly, so accurate to the hour. |
| **Run scope** | `FPA_DEMO.FPA.COST_RUNS` | Each run is a named window for one user. Only agent requests by that user inside the window count. The harness's own queries are reported separately and excluded. |

Validation in this account: across 20 agent requests, the tagged warehouse credits (0.044798) **exactly equal** the agent's own reported `sql_query_credits`, request by request.

### Run it
```sql
-- Load test: registers the run automatically
CALL FPA_DEMO.FPA.RUN_AGENT_LOAD_TEST(10, 'tier_10');

-- Live demo or pilot: wrap the session
CALL FPA_DEMO.FPA.START_COST_RUN('pilot_wk1', 'DEMO_SESSION');   -- returns run_id
--   ... ask the agent questions as the same user (Snowsight agent, CoWork, or SQL) ...
CALL FPA_DEMO.FPA.END_COST_RUN('<run_id>');

-- A few hours later (ACCOUNT_USAGE lag):
SELECT run_label, questions, token_credits, tagged_wh_credits, metered_agent_wh,
       harness_credits_excluded, token_pct, wh_pct
FROM FPA_DEMO.FPA.V_RUN_COSTS ORDER BY start_ts DESC;

-- Per question
SELECT * FROM FPA_DEMO.FPA.V_AGENT_QUESTION_COSTS WHERE run_label = 'tier_10';
```

### Which number to use
- **Cost per question** = `token_credits + tagged_wh_credits`. This is exact, and it's what the estimator uses.
- **Full warehouse cost** = `metered_agent_wh`. It adds idle time and the 60-second minimum on each resume. Use it when the warehouse sits mostly idle between questions.
- **Token % vs warehouse %** = `token_pct` and `wh_pct` in `V_RUN_COSTS`. Measured so far: tokens about 98% of attributed **credits** and about 97% of **dollars** (AI Credits at $2.00, warehouse at $3.00).

### Notes
- `QUERY_ATTRIBUTION_HISTORY` lags more than the agent usage view, sometimes several hours. Until it catches up, `tagged_wh_credits` shows 0 for a recent run; the agent's `reported_sql_credits` lags in the same way.
- Agents also issue a skill-lookup `LIST` on the **user's default warehouse**. That's why `FPA_DEMO_USER`'s default is `FPA_AGENT_WH`. These queries are tagged, so they're still counted wherever they run.
- `START_COST_RUN` also sets a session `QUERY_TAG` with the run_id, for readability in query history. Some clients set their own query tag, which replaces it; attribution doesn't depend on it, because it uses Snowflake's agent tags and the run window.
- The estimator app's **Calibration source** picker lets you calibrate from selected tagged runs only.

## Notes

- `CREATE AGENT` is a schema-level privilege, not an account-level one. The demo role owns the schema, so it has the privilege without a grant.
- `SNOWFLAKE.CORTEX.DATA_AGENT_RUN` requires a constant request string, which is why script 08 runs one statement per question.
- To edit the skill, change `agent_skills/fpa-variance-review/SKILL.md` and re-run script 06. The agent reads the skill from the stage on demand, so you don't need to recreate the agent.
- Cost guardrail: `FPA_DEMO_RM` notifies at 80% and suspends `FPA_DEMO_WH` and `FPA_AGENT_WH` at 100% of 10 credits per month. It covers warehouses only; use a Snowflake budget for AI Credits.

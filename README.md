# Snowflake Demos

Self-contained Snowflake demos built with synthetic data. Each folder has its own README with setup, run, and cleanup steps.

## Featured: Agentic FP&A on Snowflake

**[FPA-AGENT-DEMO](FPA-AGENT-DEMO/)**: a Cortex Agent for finance teams, using a fictional company (Acme Corp) and synthetic data. The agent:
- explains why gross margin is below plan, broken down by price, volume, and unit cost
- compares forecast versions and shows the reason behind each change
- runs what-if scenarios on an approved stored procedure
- answers from planning documents with Cortex Search
- prepares a forecast review package that a person has to approve before anything is sent

It also includes exact cost attribution (AI tokens vs warehouse, per question) and a Streamlit cost estimator.

| Start here | What it is |
|---|---|
| [Presentation (Tell / Show / Tell)](FPA-AGENT-DEMO/FPA_Agent_Demo_Presentation.html) | 13-slide presenter aid: the problem, what was built, a five-question run sheet with expected answers, measured costs, and nine ways to extend it for FP&A teams. Download it and open it in a browser; use the arrow keys to move between slides. |
| [Demo README](FPA-AGENT-DEMO/README.md) | Build order, demo script, review-package workflow, cost monitoring, and cleanup |
| [Cost estimator app](FPA-AGENT-DEMO/cost_estimator_app/streamlit_app_paste_into_snowsight.py) | Paste into a new Snowsight Streamlit app to project daily, weekly, monthly, and yearly cost |

## All demos

| Folder / file | Description |
|---|---|
| [FPA-AGENT-DEMO](FPA-AGENT-DEMO/) | Agentic FP&A: semantic view, Cortex Search, Cortex Agent with custom tools and an agent skill, human-approved workflow, tagged cost attribution, cost estimator |
| [COCO-PIPELINE-COST-OPTIMIZE](COCO-PIPELINE-COST-OPTIMIZE/) | Find and fix pipeline inefficiency with Cortex Code: build a deliberately inefficient pipeline, diagnose it, fix it, and measure the fix |
| [interactive-tables-benchmark](interactive-tables-benchmark/) | Concurrent load-test harness comparing Interactive Tables with standard warehouses at 10 to 100+ threads |
| [BCR-DASHBOARD](BCR-DASHBOARD/) | BCR tracking dashboard materials |
| [101_prompts_RBAC.md](101_prompts_RBAC.md) | Cortex Code first prompts, sandbox training, and a least-privilege RBAC plan |
| [1-loading_sizing_Demo.sql](1-loading_sizing_Demo.sql) | Data loading and warehouse sizing best practices |

All data in these demos is synthetic. Company and person names are fictional.

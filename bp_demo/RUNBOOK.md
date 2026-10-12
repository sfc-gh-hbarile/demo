# BP – Snowflake Modernization Demo Runbook (≤30 min)

On-prem SQL Server + Fluxx + Salesforce + 500 Tableau reports  →  Snowflake: Snowpipe → Dynamic Tables → Cortex AI → Semantic View → Cortex Agent.

## Objects (account `hbtraining`, role ACCOUNTADMIN, warehouse `BP_DEMO_WH`)
| Layer | Object | Purpose |
|---|---|---|
| Landing | `BP_DEMO.RAW.LANDING_STAGE` (internal, directory on) | `/fluxx/` + `/sfdc/` JSON files |
| Generator | `RAW.GEN_MOCK_FILES(n_grants, n_opps, update_pct)` | Writes BP-themed JSON (stands in for "2DB" + SF extract) |
| Ingest | `RAW.PIPE_FLUXX`, `RAW.PIPE_SFDC` → `RAW_FLUXX`, `RAW_SFDC` (VARIANT) | Snowpipe, triggered with `ALTER PIPE … REFRESH` |
| Feed | `RAW.RUN_FEED_CYCLE` + Task `RAW.T_FEED` (3 min) | Generate files + refresh both pipes |
| Transform | `CURATED.DT_GRANTS_FLAT`, `DT_OPPS_FLAT`, `DT_GRANT_BUDGET` | FLATTEN, typing, dedup (incremental) |
| AI | `AI.DT_GRANTS_ENRICHED` (AI_COMPLETE summary + AI_CLASSIFY risk), `AI.DT_OPPS_ENRICHED` (SENTIMENT) | Incremental – each row scored once |
| SLA table | `CURATED.DT_GRANT_PIPELINE` — **TARGET_LAG 5 min** | Conformed grant + donor pipeline |
| Semantic | `AI.SV_GRANT_PIPELINE` | 3 tables, 27 dimensions, 12 metrics, 4 verified queries |
| Search | `AI.CSS_GRANT_REVIEWS`, `AI.CSS_DONOR_NOTES` | Qualitative retrieval |
| Agent | `AI.BP_GRANTS_AGENT` ("Philanthropy Insights Agent") | Analyst + 2 Search tools |

Data: ~650 grants across Public Health, Environment, Education, Government Innovation, Arts; real initiative names (Beyond Coal, Tobacco Control, Road Safety, What Works Cities, Mayors Challenge, Public Art Challenge…), 6 regions / 23 countries, program officers, budget line items, outcome KPIs, 150–250-word reviewer assessments; ~450 Salesforce opportunities across 6 donor types with engagement history. Organization and donor names are fictional.

## Build from scratch
Run in order in Snowsight: `01_setup.sql` → `02_generator.sql` → `03_ingest.sql`, then preload:
```sql
CALL BP_DEMO.RAW.RUN_FEED_CYCLE(600, 0, 0);     -- grants first
-- wait ~30s
CALL BP_DEMO.RAW.RUN_FEED_CYCLE(100, 450, 0.5); -- opportunities + status updates
```
Then `04_dynamic_tables.sql` (first AI refresh ≈ a few minutes) → `05_semantic_agent.sql` → `06_sample_files.sql` (CSV files for Vignette 1).
`07_governance.sql` is **not** pre-run: the notebook's Vignette 4 creates the roles and policies live. Undo statements are at the bottom of that file.

**Presenter notebook:** `BP_Zero_to_Snowflake_Demo.ipynb` (regenerate with `python3 build_notebook.py`) follows the 5 Zero to Snowflake vignettes. Run it top to bottom: Vignette 1 recreates `GOV.GRANTEE_DIRECTORY`, which Vignette 4 then protects.
In Snowsight → AI & ML → Snowflake Intelligence, select **Philanthropy Insights Agent** (if your account uses the SI object, run the `ALTER SNOWFLAKE INTELLIGENCE … ADD AGENT` line at the end of 05).

## Pre-session checklist (T-15 min)
- Resume objects (section B of `99_reset.sql`). Optionally `ALTER TASK BP_DEMO.RAW.T_FEED RESUME;`
- Open tabs: Snowsight worksheet with the snippets below · Dynamic Table graph for `DT_GRANT_PIPELINE` · `legacy_sp_example.sql` · Snowflake Intelligence with the agent.
- Run one warm-up agent question.

## Talk track

### 1. Ingestion – Snowpipe on JSON (6 min)
"Today 2DB lands Fluxx data into rigid SQL Server staging tables. Here files just land."
```sql
CALL BP_DEMO.RAW.GEN_MOCK_FILES(5, 5, 0.4);              -- new Fluxx + SF files arrive
LIST @BP_DEMO.RAW.LANDING_STAGE/fluxx/;
ALTER PIPE BP_DEMO.RAW.PIPE_FLUXX REFRESH;                -- simulates auto-ingest
ALTER PIPE BP_DEMO.RAW.PIPE_SFDC  REFRESH;
SELECT SYSTEM$PIPE_STATUS('BP_DEMO.RAW.PIPE_FLUXX');
SELECT file_name, loaded_at, payload FROM BP_DEMO.RAW.RAW_FLUXX ORDER BY loaded_at DESC LIMIT 3;
```
Click into a `payload`: nested `budget_breakdown` and `outcome_targets` arrays intact – no schema defined.
*Talking point:* production uses auto-ingest from an external stage (Azure Blob + Event Grid) or the Snowpipe REST API; `ALTER PIPE … REFRESH` is used here to trigger the same pipe on an internal stage (Snowflake documents REFRESH as intended for short-term/backfill use).

### 2. Dynamic Tables replace stored procs (6 min)
Show `legacy_sp_example.sql` (temp tables, OPENJSON WITH, cursor, TRUNCATE/INSERT, SQL Agent schedule) → then `04_dynamic_tables.sql`: declarative SELECTs, `LATERAL FLATTEN`, `QUALIFY` dedup.
- Open the DAG view: RAW → FLAT → ENRICHED → `DT_GRANT_PIPELINE`.
- Point at `TARGET_LAG = '5 minutes'` – "your SLA is 10; we schedule nothing."
```sql
ALTER DYNAMIC TABLE BP_DEMO.CURATED.DT_GRANT_PIPELINE REFRESH;   -- don't wait on screen
SELECT name, refresh_action, state, refresh_start_time
FROM TABLE(BP_DEMO.INFORMATION_SCHEMA.DYNAMIC_TABLE_REFRESH_HISTORY())
ORDER BY refresh_start_time DESC LIMIT 10;
```
Note `INCREMENTAL` actions on the flatten / AI tables.

### 3. Cortex AI in the pipeline (6 min)
```sql
SELECT grant_id, organization_name, program_area, LEFT(reviewer_notes, 400) AS notes_excerpt,
       ai_reviewer_summary, ai_primary_risk
FROM BP_DEMO.AI.DT_GRANTS_ENRICHED ORDER BY requested_amount DESC LIMIT 5;

SELECT account_name, donor_type, stage, donor_engagement_notes, ROUND(donor_sentiment, 2) AS sentiment, donor_health
FROM BP_DEMO.AI.DT_OPPS_ENRICHED ORDER BY donor_sentiment LIMIT 5;
```
*Talking points:* AI_COMPLETE (one-sentence summary), AI_CLASSIFY (risk theme), SENTIMENT (-1..1) run inside an incremental Dynamic Table, so only new or changed rows are scored.

### 4. Agent replaces static Tableau (10 min)
Show the semantic view YAML: `SELECT SYSTEM$READ_YAML_FROM_SEMANTIC_VIEW('BP_DEMO.AI.SV_GRANT_PIPELINE');`
Then ask in Snowflake Intelligence:

**Validated**
1. *What is the total requested amount for Arts and Education grants currently under review?* → Analyst (verified query). At build time: Education $9,566,000 (25), Arts $7,476,000 (14), total $17,042,000; numbers change as the feed runs.
2. *Summarize the main concerns reviewers raised on Public Health grants under review.* → GrantReviewSearch; themes: reporting capacity, financial reserves, KPI baselines, political/industry risk.

**More questions to try – executive / program**
3. Which program area has the lowest average donor sentiment, and what are those donors saying?  *(Analyst + DonorNotesSearch)*
4. Show the top 5 Environment grants by requested amount with their AI summaries.
5. What is our approval rate and total awarded by program area?
6. How much have we awarded to Beyond Coal versus Clean Energy Transition this year?
7. Which program officers have the most dollars under review, and what's the most common AI risk theme in their portfolio?
8. Break down requested budgets by line item for Government Innovation – how much goes to Evaluation & Data?
9. Which regions have the highest share of high-risk applications?

**Donor / fundraising**
10. What is our probability-weighted co-funding pipeline by donor type?
11. Which corporate partners are at risk, and which relationship managers own them?
12. Which large grants under review have committed co-funding, and which have none?

**Mixed (shows orchestration)**
13. List Public Health grants over $1M under review and explain why reviewers are hesitant on each.
14. Which Arts organizations have the best reviewer scores, and what strengths did reviewers highlight?

## Validation (done at build)
- `ALTER PIPE … REFRESH` loads internal-stage files within seconds (`SYSTEM$PIPE_STATUS` pendingFileCount 0).
- 650 grants / 450 opportunities; 0 null AI summaries; sentiment −0.44…0.87; 132 grants Under Review.
- Flatten and AI DTs are INCREMENTAL; `DT_GRANT_PIPELINE` chose FULL (join + aggregate, no AI – cheap).
- Feed cycle → new rows propagated end-to-end via 5-min lag (650→654 grants, 450→456 opps).
- Agent Q1 matched direct SQL exactly; Q2 routed to GrantReviewSearch.

## After the session
Run section A of `99_reset.sql` (suspends Task, pipes, DTs, search indexing). Full teardown: section C.

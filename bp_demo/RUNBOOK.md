# BP – Snowflake Modernization Demo Runbook (≤30 min)

On-prem SQL Server + Fluxx + Salesforce + 500 Tableau reports  →  Snowflake: Snowpipe → Dynamic Tables → Cortex AI → Semantic View → Cortex Agent.

## Objects (account `hbtraining`, role ACCOUNTADMIN, warehouse `BP_DEMO_WH`)
| Layer | Object | Purpose |
|---|---|---|
| Landing | `BP_DEMO.RAW.LANDING_STAGE` (internal, directory on) | `/fluxx/` + `/sfdc/` JSON files |
| Generator | `RAW.GEN_MOCK_FILES(n_grants, n_opps, update_pct)` | Writes BP-themed JSON (stands in for "2DB" + SF extract) |
| Ingest | `RAW.PIPE_FLUXX`, `RAW.PIPE_SFDC` → `RAW_FLUXX`, `RAW_SFDC` (VARIANT) | Snowpipe, triggered with `ALTER PIPE … REFRESH` |
| Feed | `RAW.RUN_FEED_CYCLE` + Task `RAW.T_FEED` (3 min) | Generate files + refresh both pipes |
| API pull (`09_api_pull.sql`) | Task `RAW.T_PULL_MOCK_FLUXX` (suspended) → `RAW.PULL_MOCK_FLUXX_API(DRY_RUN)` → network rule `RAW.MOCK_FLUXX_EGRESS` + integration `BP_MOCK_FLUXX_EAI` | Pulls 3 grants from a mock Fluxx API (`fluxx_mock/grant_request.json` in github.com/sfc-gh-hbarile/demo, branch `main`) into `RAW_FLUXX` as `api_pull/...` rows. Watermark is per source (API rows only) |
| Transform | `CURATED.DT_GRANTS_FLAT`, `DT_OPPS_FLAT`, `DT_GRANT_BUDGET` | FLATTEN, typing, dedup (incremental) |
| AI | `AI.DT_GRANTS_ENRICHED` (AI_COMPLETE summary + AI_CLASSIFY risk), `AI.DT_OPPS_ENRICHED` (SENTIMENT) | Incremental – each row scored once |
| SLA table | `CURATED.DT_GRANT_PIPELINE` — **TARGET_LAG 5 min** | Conformed grant + donor pipeline |
| Semantic | `AI.SV_GRANT_PIPELINE` | 3 tables, 27 dimensions, 12 metrics, 4 verified queries |
| Search | `AI.CSS_GRANT_REVIEWS`, `AI.CSS_DONOR_NOTES` | Qualitative retrieval |
| Agent | `AI.BP_GRANTS_AGENT` ("Philanthropy Insights Agent") | Analyst + 2 Search tools |

Data: ~650 grants across Public Health, Environment, Education, Government Innovation, Arts; real initiative names (Beyond Coal, Tobacco Control, Road Safety, What Works Cities, Mayors Challenge, Public Art Challenge…), 6 regions / 23 countries, program officers, budget line items, outcome KPIs, 150–250-word reviewer assessments; ~450 Salesforce opportunities across 6 donor types with engagement history. Organization and donor names are fictional.

## v2 notebook: the demo you run (`BP_Zero_to_Snowflake_Demo_v2.ipynb`)
Everything below was rebuilt from scratch and the notebook run top to bottom on 16 Nov 2026 (two full passes, all cells green).

### A. Every time you present or rehearse (≈20 min of prep)
| When | Run | What it does |
|---|---|---|
| ≥ 1 hour before | **`99_reset.sql`** (whole file) | Pauses pipes/DTs/search, drops everything the notebook creates live (GRANTEE_DIRECTORY, DEV clone, BP_* roles, masking + row access policies, Appendix B/C objects, LOAD_TEST tables), sets warehouse XS and suspends it |
| T-15 min | **`00_pre_demo.sql`** (whole file) | Resumes pipes, DTs and search, then a readiness check: every row must say **OK**, `SHOW AGENTS` shows 1 row, `SHOW ROLES LIKE 'BP\\_%'` shows **none** |
| T-10 min | Open tabs | Notebook v2 · Snowflake Intelligence → **Philanthropy Insights Agent** (ask one warm-up question) · Catalog → `DT_GRANT_PIPELINE` → Graph · `legacy_sp_example.sql` |
| Live | Notebook v2, **top to bottom** | Vignette 1 builds `GOV.GRANTEE_DIRECTORY`; Vignette 4 creates roles and policies on it |

Why ≥ 1 hour before: the cost scorecard (1.5) reads hourly metering, so a rehearsal in the same clock hour inflates the METERED line. Each run gets a new `run_id`, so rehearsal rows never mix into the live rows.

### B. Full rebuild from nothing (≈10 min; only if objects are missing or broken)
1. Teardown: section C of `99_reset.sql` (uncomment). Drops `BP_DEMO`, the BP_* roles and `BP_DEMO_WH`. Notebooks live in your workspace and are not affected.
2. `01_setup.sql` → `02_generator.sql` (**only creates the generator procedure; it writes no files on its own**) → `03_ingest.sql`
3. Preload the data (this is the step that was missed before, and it is why everything downstream was empty):
```sql
CALL BP_DEMO.RAW.RUN_FEED_CYCLE(600, 0, 0);       -- 600 grants
CALL SYSTEM$WAIT(45);
CALL BP_DEMO.RAW.RUN_FEED_CYCLE(100, 450, 0.5);   -- 100 grants (half are status updates) + 450 opportunities
CALL SYSTEM$WAIT(45);
SELECT COUNT(*) FROM BP_DEMO.RAW.RAW_FLUXX;       -- expect 7 files = 650 grants
-- Record these files as the clean baseline that 99_reset.sql rewinds to before every rehearsal
CREATE OR REPLACE TABLE BP_DEMO.RAW.DEMO_BASELINE AS
  SELECT file_name, loaded_at FROM BP_DEMO.RAW.RAW_FLUXX
  UNION ALL SELECT file_name, loaded_at FROM BP_DEMO.RAW.RAW_SFDC;
```
4. `04_dynamic_tables.sql` (≈1 min; the first AI scoring runs here) → `05_semantic_agent.sql` → re-add the agent to Snowflake Intelligence:
   `ALTER SNOWFLAKE INTELLIGENCE SNOWFLAKE_INTELLIGENCE_OBJECT_DEFAULT ADD AGENT BP_DEMO.AI.BP_GRANTS_AGENT;`
5. `06_sample_files.sql` (3 CSVs, about 52 grantees) → `08_scale_data.sql` (229 gzip files, 3.9 GB, ~10 s on LARGE) → `09_api_pull.sql` (API pull for Section 4; its last line is a dry run that should show `returned_by_api: 3`)
   - The integration `BP_MOCK_FLUXX_EAI` is account-level, so a teardown with `DROP DATABASE` leaves it behind. Section C of `99_reset.sql` drops it explicitly. `09` uses `CREATE OR REPLACE`, so re-running it is always safe.
6. **Do not pre-run `07_governance.sql`.** Vignette 4 does it live; the file is the reference copy.
7. Then follow section A.

### What a good run looks like (from the 16 Nov rehearsal)
| Cell | Expected |
|---|---|
| 1.1 `create_and_copy` / `copy_again` | 3 files LOADED (52 rows) / "0 files processed" (load history prevents duplicates) |
| 1.3 load XS vs MEDIUM | 229 files, 65M rows; **~54 s on XS vs ~17 s on MEDIUM**, about the same credits |
| 1.4 query XS vs MEDIUM | 47 GB scanned; **~48 s vs ~18 s** |
| 1.5 cache | ~0.4 s, ran on "result cache", 0 credits |
| 1.7 Time Travel | "by statement" and "at a timestamp" both show the original total; "now" = 0; restore brings it back |
| 2 pipeline | COPY_HISTORY shows Loaded; DT refresh INCREMENTAL on flatten/AI tables, FULL on DT_GRANT_PIPELINE |
| 3 agent | the agent's answer matches the `truth_check` SQL to the dollar |
| 4 governance | compliance sees full PII · analyst sees masked values · Public Health officer sees only Public Health rows · 5 policies ACTIVE |

### Fixes made on 16 Nov
- `03_ingest.sql`: pipes now use fully-qualified names. `ALTER PIPE … REFRESH` from the notebook failed with "RAW_FLUXX does not exist".
- Notebook 1.5 cache cell re-enables `USE_CACHED_RESULT`. 1.4 turns it off, so the "free second run" had been running again for 39 s.
- Notebook 1.6 clone: `AS rows` is a reserved word, renamed to `row_count`.
- Notebook 1.7 Time Travel: replaced `OFFSET => -60` with a timestamp captured just before the mistake. In a fast live run, "60 seconds ago" already showed 0.
- Notebook 2.1 `list_landing` refreshes the directory table first, so the new files appear.
- Notebook wrap-up `cost_services`: an alias clashed with a column in HAVING.
- `06_sample_files.sql` sets the role; `99_reset.sql` gained section F (post-rehearsal cleanup); new `00_pre_demo.sql`.
- The same notebook fixes were applied to `build_notebook_v2.py`, so regenerating keeps them.

### Original v1 presenter notebook
`BP_Zero_to_Snowflake_Demo.ipynb` (regenerate with `python3 build_notebook.py`) is the older flow. It does not use `08` or the scaling demos. Use v2.

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
- Feed cycle → new rows propagated end-to-end via 5-min lag (650→654 grant
## V3: the 40-minute customer cut (`BP_Demo_v3_40min.ipynb`)
Use this one for audiences new to Snowflake. v2 stays the full reference version.

> ⚠️ **Edit `BP_Demo_v3_40min.ipynb` directly; do not regenerate it.** `tmp/build_notebook_v3.py` is out of date: it predates Section 7 (Marketplace), Appendix A and the Section 4 API pull, so running it would remove them.

### Practice loop: repeat as often as you like
| Step | When | What it does | Time |
|---|---|---|---|
| 1. Run all of `99_reset.sql` | After each rehearsal (and ≥ 1 hour before the live demo) | Pauses the Dynamic Tables, search and warehouse, drops the roles/policies/tables the notebook creates, **rewinds the data** to the clean baseline (removes rehearsal files from the stage and their rows from RAW, then refreshes the 6 Dynamic Tables), suspends the warehouse | ~30 s |
| 2. Run all of `00_pre_demo.sql` | Before each rehearsal, and at T-15 for the live demo | Resumes Dynamic Tables and search (pipes stay on: an idle Snowpipe costs nothing); readiness check. Its last line dry-runs the API pull: expect `would_pull: 3` (proves GitHub is reachable; writes nothing) | ~15 s |
| 3. Run V3 top to bottom | | | ~40 min |

**Every readiness row must say OK.** If one says `<<< FIX`, run step 1 again, then step 2.

**What stays the same every run** (rewind + the fixed seed `42` in `land_files`):
| Check | Value |
|---|---|
| `landing_before` | fluxx 8, sfdc 6 |
| `land_files` | 2 files: 3 new grants + 2 status updates, 5 donor opportunities |
| `query_compare` / `cache_run` → `cache_hit` | XS ≈ 60 s vs MEDIUM ≈ 15 s, about the same credits (both with `USE_CACHED_RESULT = FALSE`, full 47 GB scan). `cache_run` turns caching back on and runs the query on MEDIUM (≈ 15 s, result saved); `cache_hit` repeats it on XS: ≈ 0.3 s, no warehouse, 0 bytes scanned. **If Section 2 ran in the last 24 hours** (same role), `cache_run` is already instant because it reuses that earlier result: still a real cache hit, but the before/after is lost. For the live demo, don't rehearse Section 2 within 24 hours, or say "this ran earlier today" |
| `landing_after` / `copy_hist` | exactly those 2 files |
| Grants after the delivery | 656 |
| API pull cell (`T_PULL_MOCK_FLUXX`) | task SUCCEEDED, **3 grants pulled**: FLX-2026-00901 (Kenya), 00902 (Bangladesh), 00903 (Peru) |
| Grants after the API pull + `dt_refresh` | **659** |
| `new_grants_through` | the delivered file's grants **plus** the 3 API grants, each with an AI summary and risk theme |
| Agent + `truth_check` (Arts + Education under review) | **$21,913,000**: Education 19 grants $11,598,000 · Arts 23 grants $10,315,000 |
| Pre-demo readiness row (before the delivery) | $22,288,000 |

**What will still vary** (and that's fine to say out loud): the AI's wording (the one-prompt brief, the agent's sentences), query timings (XS ≈ 60 s, MEDIUM ≈ 15–18 s), and the cost table. The generator uses today's date, so the delivered records can differ from one day to the next, but every rehearsal on the same day matches. Always trust `truth_check`.

| Min | Section | Run live | Click in Snowsight |
|---|---|---|---|
| 0–3 | Welcome, 3 ideas, glossary | whoami | — |
| 3–8 | 1. Load files | list_files, create_and_copy, grantees | Database Explorer → GRANTEE_DIRECTORY |
| 8–14 | 2. Compute + cache | query_xs (~60 s), query_m (~15 s), query_compare, cache_run (~15 s), cache_hit (~0.3 s) | Query History → Query Profile |
| 14–18 | 3. Clone + Time Travel | clone, oops, travel, restore | — |
| 18–29 | 4. Pipelines | landing_before → land_files → landing_after → pipe_refresh → wait → copy_hist; **API pull** (run task + api_raw, ~1 min); JSON steps 1–2; the 6 Dynamic Tables (diagram + table + 2 definitions); refresh diagram, dt_refresh, new_grants_through, dt_status | DT_GRANT_PIPELINE → Graph |
| 29–35 | 5. AI | ai_experiment, ai_grants, risk_mix + chart, agent, truth_check | Snowflake Intelligence (optional) |
| 35–38 | 6. Governance | classify → as_po_health | — |
| 38–40 | 7. Cost + recap + follow-ups | cost_wh | Admin → Cost Management |

**Running late?**
- Talk over `query_xs` while it runs (~60 s).
- Skip section 3.
- In section 4, show just one of the two Dynamic Table definitions.
- In section 4, the API pull cells can be skipped: nothing later depends on them (the grant count is then 656 instead of 659).
- In section 5, skip the chart and use only the agent cell.

**Verified (17 Nov):** two back-to-back practice loops gave identical results (table above). Each reset took about 30 s; the notebook's wait cell saw both new files load in 10–15 s.
**API pull added and verified (17 Nov):** `99_reset.sql` → `00_pre_demo.sql` (all rows OK, dry run `would_pull: 3`) → Section 4: task SUCCEEDED in ~10–15 s, 3 grants pulled, `dt_refresh` 659 grants, all 3 API grants AI-enriched, `truth_check` unchanged at $21,913,000 → `99_reset.sql` back to 653 grants and 0 API rows. If the API cell says 0 pulled, the reset was skipped; if the task FAILED, check GitHub reachability with `CALL BP_DEMO.RAW.PULL_MOCK_FLUXX_API(TRUE);`.

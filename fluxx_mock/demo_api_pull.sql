-- Appendix A, live: pull from a (mock) Fluxx API
-- EXECUTE TASK -> PULL_MOCK_FLUXX_API() -> HTTPS (EAI) -> GitHub raw JSON
--   -> RAW.RAW_FLUXX -> DT_GRANTS_FLAT -> DT_GRANTS_ENRICHED (AI) -> DT_GRANT_PIPELINE

-- 1. What's wired up
SHOW EXTERNAL ACCESS INTEGRATIONS LIKE 'BP_MOCK_FLUXX_EAI';
SHOW TASKS LIKE 'T_PULL_MOCK_FLUXX' IN SCHEMA BP_DEMO.RAW;

-- 2. Pull now (same code the task runs every 5 min); returns {pulled, grant_ids, since, ...}
CALL BP_DEMO.RAW.PULL_MOCK_FLUXX_API();
-- or, to show the scheduler path:  EXECUTE TASK BP_DEMO.RAW.T_PULL_MOCK_FLUXX;

-- 3. The new rows landed in RAW
SELECT file_name, loaded_at, ARRAY_SIZE(payload:records) AS records
FROM BP_DEMO.RAW.RAW_FLUXX
WHERE file_name LIKE 'api_pull/%'
ORDER BY loaded_at DESC;

-- 4. Refresh (instead of waiting for the 5-min lag) and see the new grants with AI fields
ALTER DYNAMIC TABLE BP_DEMO.CURATED.DT_GRANT_PIPELINE REFRESH;

SELECT grant_id, organization_name, country, initiative, requested_amount, risk_rating,
       ai_primary_risk, ai_reviewer_summary
FROM BP_DEMO.CURATED.DT_GRANT_PIPELINE
WHERE grant_id LIKE 'FLX-2026-009%'
ORDER BY grant_id;

-- 5. Run the pull again: pulled = 0 (high-water mark, incremental)
CALL BP_DEMO.RAW.PULL_MOCK_FLUXX_API();

-- Reset for the next rehearsal (removes the API-pulled rows)
-- DELETE FROM BP_DEMO.RAW.RAW_FLUXX WHERE file_name LIKE 'api_pull/%';
-- Optional: run it on a schedule
-- ALTER TASK BP_DEMO.RAW.T_PULL_MOCK_FLUXX RESUME;   -- and SUSPEND afterwards

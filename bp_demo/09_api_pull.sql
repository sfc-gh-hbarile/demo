-- =====================================================================
-- 09_api_pull.sql : live "pull from an API" source for Section 4 of the V3 notebook
-- Stands in for the Fluxx REST API (Appendix A). The mock endpoint is a JSON file in a
-- public GitHub repo, so the call is real HTTPS egress, but needs no credentials:
--   https://raw.githubusercontent.com/sfc-gh-hbarile/demo/main/fluxx_mock/grant_request.json
--   (reference copy: bp_demo/fluxx_mock/grant_request.json)
--
--   EXECUTE TASK T_PULL_MOCK_FLUXX ─► PULL_MOCK_FLUXX_API() ─► HTTPS (External Access) ─► GitHub
--        └─► records newer than the API watermark ─► RAW.RAW_FLUXX (file_name 'api_pull/...')
--        └─► the same 6 Dynamic Tables pick them up, unchanged
--
-- Run once after 04_dynamic_tables.sql (safe to re-run). Requires ACCOUNTADMIN
-- (network rules + external access integrations).
-- Reset: 99_reset.sql section G deletes the api_pull rows, so every rehearsal pulls the same 3 grants.
-- =====================================================================
USE ROLE ACCOUNTADMIN;

-- 1. Egress is off by default: allow-list only the mock host
CREATE OR REPLACE NETWORK RULE BP_DEMO.RAW.MOCK_FLUXX_EGRESS
  MODE = EGRESS TYPE = HOST_PORT VALUE_LIST = ('raw.githubusercontent.com:443')
  COMMENT = 'Demo: mock Fluxx API hosted in public GitHub repo';

-- 2. Integration (account-level object: NOT removed by DROP DATABASE; see 99_reset.sql section C).
--    Real Fluxx adds ALLOWED_AUTHENTICATION_SECRETS for the OAuth secret (Appendix A).
CREATE OR REPLACE EXTERNAL ACCESS INTEGRATION BP_MOCK_FLUXX_EAI
  ALLOWED_NETWORK_RULES = (BP_DEMO.RAW.MOCK_FLUXX_EGRESS)
  ENABLED = TRUE
  COMMENT = 'Demo: mock Fluxx API pull (09_api_pull.sql)';

-- 3. The pull. DRY_RUN = TRUE calls the API and reports what would load, without writing
--    (00_pre_demo.sql uses it to prove GitHub is reachable before you go live).
DROP PROCEDURE IF EXISTS BP_DEMO.RAW.PULL_MOCK_FLUXX_API();   -- earlier version had no argument
CREATE OR REPLACE PROCEDURE BP_DEMO.RAW.PULL_MOCK_FLUXX_API(DRY_RUN BOOLEAN DEFAULT FALSE)
RETURNS VARIANT
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python', 'requests')
EXTERNAL_ACCESS_INTEGRATIONS = (BP_MOCK_FLUXX_EAI)
HANDLER = 'run'
COMMENT = 'Demo: pull grant_request records from a mock Fluxx API (GitHub raw) into RAW_FLUXX'
AS
$$
import json, time, requests
from datetime import datetime, timezone

# Mock Fluxx endpoint. Real Fluxx: https://<org>.fluxx.io/api/rest/v2/grant_request + OAuth token (Appendix A).
URL = "https://raw.githubusercontent.com/sfc-gh-hbarile/demo/main/fluxx_mock/grant_request.json"

def _ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)

def run(session, dry_run):
    # High-water mark for THIS source only (rows this procedure loaded). A watermark over all of
    # RAW_FLUXX would skip API records whenever a newer file arrived through Snowpipe first.
    since = session.sql(
        "SELECT COALESCE(MAX(r.value:last_modified::TIMESTAMP_NTZ), '1900-01-01'::TIMESTAMP_NTZ) "
        "FROM BP_DEMO.RAW.RAW_FLUXX t, LATERAL FLATTEN(t.payload:records) r "
        "WHERE t.file_name LIKE 'api_pull/%'").collect()[0][0]

    resp = requests.get(URL, params={"t": int(time.time())}, timeout=30)   # cache-buster
    resp.raise_for_status()
    batch = resp.json().get("records", {}).get("grant_request", [])
    new = [r for r in batch if _ts(r["last_modified"]) > since]

    file_name = None
    if new and not dry_run:
        file_name = "api_pull/fluxx_api_" + datetime.utcnow().strftime("%Y%m%d_%H%M%S") + ".json"
        session.create_dataframe([[json.dumps({"records": new}), file_name]], schema=["P", "F"]) \
               .select_expr("PARSE_JSON(P) AS PAYLOAD", "F AS FILE_NAME", "CURRENT_TIMESTAMP() AS LOADED_AT") \
               .write.mode("append").save_as_table("BP_DEMO.RAW.RAW_FLUXX", column_order="name")

    return {"source": URL, "dry_run": dry_run, "since": str(since), "returned_by_api": len(batch),
            "would_pull": len(new), "pulled": 0 if dry_run else len(new),
            "grant_ids": [r["grant_id"] for r in new], "file_name": file_name}
$$;

-- 4. Schedule (serverless). Left SUSPENDED: the notebook runs it on demand with EXECUTE TASK.
CREATE OR REPLACE TASK BP_DEMO.RAW.T_PULL_MOCK_FLUXX
  SCHEDULE = '5 MINUTE'
  USER_TASK_MANAGED_INITIAL_WAREHOUSE_SIZE = 'XSMALL'
  COMMENT = 'Demo: pull mock Fluxx API every 5 min (left suspended; run with EXECUTE TASK)'
AS CALL BP_DEMO.RAW.PULL_MOCK_FLUXX_API();
-- ALTER TASK BP_DEMO.RAW.T_PULL_MOCK_FLUXX RESUME;   -- only to show it on a schedule; SUSPEND afterwards

-- 5. Smoke test: expect returned_by_api = 3 (would_pull = 3 right after 99_reset.sql)
CALL BP_DEMO.RAW.PULL_MOCK_FLUXX_API(TRUE);

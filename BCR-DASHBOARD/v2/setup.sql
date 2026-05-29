-- =============================================================================
-- Snowflake BCR Tracker — Setup Script (v2)
-- =============================================================================
-- WHAT THIS SCRIPT DOES:
--   1. Drops and recreates the BCR_TRACKER_DB database (clean slate)
--   2. Creates all tables, procedures, tasks, and network rules
--   3. Runs an initial sync to load active BCR bundles + descriptions
--
-- RUN TIME: ~2-3 minutes (network fetches for BCR descriptions)
--
-- PREREQUISITE: Update the warehouse name below if yours is not COMPUTE_WH
-- =============================================================================

SET BCR_WH  = 'COMPUTE_WH';   -- ← update to your warehouse name if needed
SET BCR_DB  = 'BCR_TRACKER_DB';
SET BCR_SCH = 'TRACKING';

-- =============================================================================
-- STEP 1 — DROP EVERYTHING (clean slate)
-- =============================================================================
-- Drops the entire database including all tables, procedures, tasks, and data.
-- This ensures no stale schema, missing columns, or old procedure overloads.
DROP DATABASE IF EXISTS BCR_TRACKER_DB;

-- =============================================================================
-- STEP 2 — CREATE DATABASE AND SCHEMA
-- =============================================================================
CREATE DATABASE IDENTIFIER($BCR_DB);
USE DATABASE    IDENTIFIER($BCR_DB);
USE WAREHOUSE   IDENTIFIER($BCR_WH);
CREATE SCHEMA   IDENTIFIER($BCR_SCH);
USE SCHEMA      IDENTIFIER($BCR_SCH);

-- ─── Tables ───────────────────────────────────────────────────────────────────

CREATE TABLE BCR_REGISTRY (
    BCR_ID          VARCHAR(80)  NOT NULL,
    BUNDLE_ID       VARCHAR(15)  NOT NULL,
    UNBUNDLED       BOOLEAN      DEFAULT FALSE,
    BUNDLE_STATUS   VARCHAR(30),
    CATEGORY        VARCHAR(200),
    TITLE           VARCHAR(500),
    DESCRIPTION     TEXT,
    IMPACT_DEFAULT  VARCHAR(10),
    DBD             VARCHAR(30),
    EBD             VARCHAR(30),
    GE              VARCHAR(30),
    DOCS_URL        VARCHAR(500),
    FETCHED_AT      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    CONSTRAINT pk_bcr_registry PRIMARY KEY (BCR_ID)
);

CREATE TABLE BCR_ASSESSMENTS (
    ASSESSMENT_ID   NUMBER AUTOINCREMENT PRIMARY KEY,
    BCR_ID          VARCHAR(80)  NOT NULL REFERENCES BCR_REGISTRY(BCR_ID),
    BUNDLE_ID       VARCHAR(15),
    NONPROD_STATUS  VARCHAR(30)  DEFAULT 'Not Started',
    PROD_STATUS     VARCHAR(30)  DEFAULT 'Not Started',
    IMPACT_OVERRIDE VARCHAR(10),
    OWNER           VARCHAR(200),
    NOTES           TEXT,
    SIGN_OFF_DATE   DATE,
    CASE_ID         VARCHAR(50),
    RISK_ACCEPTED   BOOLEAN      DEFAULT FALSE,
    COE_BRIEF       TEXT,
    LAST_UPDATED_BY VARCHAR(200) DEFAULT CURRENT_USER(),
    LAST_UPDATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    CONSTRAINT uq_assessment UNIQUE (BCR_ID)
);

CREATE TABLE BCR_DETECTION_QUERIES (
    QUERY_ID        NUMBER AUTOINCREMENT PRIMARY KEY,
    BCR_ID          VARCHAR(80)  NOT NULL REFERENCES BCR_REGISTRY(BCR_ID),
    DETECTION_SQL   TEXT,
    GENERATED_BY    VARCHAR(20)  DEFAULT 'manual',
    APPROVED        BOOLEAN      DEFAULT FALSE,
    APPROVED_BY     VARCHAR(200),
    CREATED_AT      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    UPDATED_AT      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    CONSTRAINT uq_detection_query UNIQUE (BCR_ID)
);

CREATE TABLE BCR_DETECTION_RESULTS (
    RESULT_ID        NUMBER AUTOINCREMENT PRIMARY KEY,
    BCR_ID           VARCHAR(80)  NOT NULL REFERENCES BCR_REGISTRY(BCR_ID),
    RUN_AT           TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    AFFECTED_COUNT   NUMBER        DEFAULT 0,
    AFFECTED_OBJECTS VARIANT,
    SIGNAL_SUMMARY   TEXT,
    NOTES            TEXT,
    DETECTION_SQL    TEXT,
    RUN_BY           VARCHAR(200)  DEFAULT CURRENT_USER()
);

CREATE TABLE BCR_REGRESSION_SNAPSHOTS (
    SNAPSHOT_ID         NUMBER AUTOINCREMENT PRIMARY KEY,
    BUNDLE_ID           VARCHAR(15)  NOT NULL,
    SNAPSHOT_DATE       DATE         NOT NULL,
    TOTAL_QUERIES       NUMBER       DEFAULT 0,
    ERROR_COUNT         NUMBER       DEFAULT 0,
    ERROR_RATE          FLOAT        DEFAULT 0,
    BASELINE_ERROR_RATE FLOAT,
    DELTA_VS_BASELINE   FLOAT,
    CREATED_AT          TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    CONSTRAINT uq_regression_snapshot UNIQUE (BUNDLE_ID, SNAPSHOT_DATE)
);

CREATE TABLE BCR_CONFIG (
    SETTING_KEY   VARCHAR(100) NOT NULL PRIMARY KEY,
    SETTING_VALUE TEXT,
    UPDATED_AT    TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

INSERT INTO BCR_CONFIG (SETTING_KEY, SETTING_VALUE)
VALUES ('LAST_REFRESH', NULL);

-- =============================================================================
-- STEP 3 — EXTERNAL NETWORK ACCESS (to fetch BCR docs from docs.snowflake.com)
-- =============================================================================
CREATE OR REPLACE NETWORK RULE SNOWFLAKE_DOCS_RULE
    TYPE       = HOST_PORT
    MODE       = EGRESS
    VALUE_LIST = ('docs.snowflake.com');

CREATE OR REPLACE EXTERNAL ACCESS INTEGRATION SNOWFLAKE_DOCS_ACCESS
    ALLOWED_NETWORK_RULES = (SNOWFLAKE_DOCS_RULE)
    ENABLED               = TRUE;

-- =============================================================================
-- STEP 4 — STORED PROCEDURES
-- =============================================================================
-- =============================================================================
-- PROCEDURE: FETCH_BCR_BUNDLE  (v2 — .md URL with HTML fallback)
-- =============================================================================
CREATE OR REPLACE PROCEDURE FETCH_BCR_BUNDLE(BUNDLE_ID STRING, BUNDLE_STATUS STRING)
RETURNS STRING
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python', 'requests')
EXTERNAL_ACCESS_INTEGRATIONS = (SNOWFLAKE_DOCS_ACCESS)
HANDLER = 'fetch_bundle'
AS $$
import requests
import re
from datetime import datetime

BASE = "https://docs.snowflake.com/en/release-notes/bcr-bundles/"
HDR  = {"User-Agent": "Mozilla/5.0"}


# =============================================================================
# fetch_doc — THE ONLY PLACE that knows about .md vs HTML
# =============================================================================
def fetch_doc(url: str, timeout: int = 10) -> tuple:
    """
    Try .md URL first (clean markdown, no JS/navigation).
    Fall back to plain HTML URL if .md returns 404 or errors.

    This mirrors the Snowflake CLI's own behaviour:
      "Markdown URL (preferred for web_fetch, falls back to URL above on 404)"

    Returns: (text: str, is_markdown: bool)
      is_markdown=True  → caller parses as Markdown (# headings, **bold**)
      is_markdown=False → caller parses as HTML (strip tags, extract <main>)
    """
    base    = url.rstrip("/").removesuffix(".md")
    md_url  = base + ".md"

    try:
        r = requests.get(md_url, timeout=timeout, headers=HDR)
        if r.status_code == 200:
            return (r.text, True)
    except Exception:
        pass

    # .md failed — fall back to HTML
    try:
        r = requests.get(base, timeout=timeout, headers=HDR)
        if r.status_code == 200:
            return (r.text, False)
    except Exception:
        pass

    return ("", True)   # empty; callers check for empty string


def fetch_bundle(session, bundle_id: str, bundle_status: str) -> str:
    bundle_id = bundle_id.strip()
    base_url  = f"{BASE}{bundle_id}_bundle"

    source, is_md = fetch_doc(base_url, timeout=15)
    if not source:
        return f"ERROR: Could not fetch bundle page for {bundle_id} (tried .md and HTML)"

    dates    = parse_dates(source)
    bcr_rows = parse_bcr_rows(source, bundle_id, dates)

    if not bcr_rows:
        anchors = len(re.findall(r'/bcr-\d+', source))
        idx     = source.find('/bcr-')
        snippet = repr(source[max(0, idx-200):idx+200]) if idx >= 0 else repr(source[:400])
        return (
            f"WARN: Parsed 0 BCRs (tried {'markdown' if is_md else 'HTML'}). "
            f"BCR anchor count={anchors}. Snippet: {snippet}"
        )

    existing = {
        r[0] for r in session.sql(
            "SELECT BCR_ID FROM BCR_REGISTRY WHERE BUNDLE_ID = ?", [bundle_id]
        ).collect()
    }
    new_rows = [r for r in bcr_rows if r["bcr_id"] not in existing]

    if not new_rows:
        session.sql("""
            UPDATE BCR_REGISTRY SET BUNDLE_STATUS = ?
            WHERE BUNDLE_ID = ? AND UNBUNDLED IS DISTINCT FROM TRUE
        """, [bundle_status, bundle_id]).collect()
        return f"OK: 0 new BCRs (all {len(bcr_rows)} already loaded for {bundle_id})"

    for row in new_rows:
        title, synopsis = fetch_title_and_synopsis(row["url"])
        if title:    row["title"]       = title
        if synopsis: row["description"] = synopsis

    for row in new_rows:
        session.sql("""
            INSERT INTO BCR_REGISTRY
                (BCR_ID, BUNDLE_ID, UNBUNDLED, BUNDLE_STATUS, CATEGORY,
                 TITLE, DESCRIPTION, IMPACT_DEFAULT, DBD, EBD, GE, DOCS_URL)
            SELECT ?,?,FALSE,?,?,?,?,?,?,?,?,?
            WHERE NOT EXISTS (SELECT 1 FROM BCR_REGISTRY WHERE BCR_ID = ?)
        """, [
            row["bcr_id"], bundle_id, bundle_status, row["category"],
            row["title"], row["description"], row["impact"],
            row.get("dbd",""), row.get("ebd",""), row.get("ge",""),
            row["url"], row["bcr_id"]
        ]).collect()

        session.sql("""
            INSERT INTO BCR_ASSESSMENTS (BCR_ID, BUNDLE_ID)
            SELECT ?,? WHERE NOT EXISTS (
                SELECT 1 FROM BCR_ASSESSMENTS WHERE BCR_ID = ?
            )
        """, [row["bcr_id"], bundle_id, row["bcr_id"]]).collect()

    session.sql("""
        UPDATE BCR_CONFIG SET SETTING_VALUE=?, UPDATED_AT=CURRENT_TIMESTAMP()
        WHERE SETTING_KEY='LAST_REFRESH'
    """, [datetime.utcnow().isoformat()]).collect()

    return f"OK: {len(new_rows)} new BCRs added from bundle {bundle_id}"


def fetch_title_and_synopsis(url: str) -> tuple:
    text, is_md = fetch_doc(url)
    if not text:
        return ("", "")

    if is_md:
        # ── Markdown path (preferred) ──────────────────────────────────────
        # Some .md files contain JSX/HTML tags (<dl>, <dt>, <dd>, <span>).
        # Strip inline tags per-line so stored text is clean for display
        # and Cortex prompts without losing line structure.
        title = ""
        h1 = re.search(r'^#\s+(.+)$', text, re.MULTILINE)
        if h1:
            title = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', h1.group(1)).strip()

        skip = re.compile(
            r'^(#|This behavior change is in|For the current status|'
            r'For more information|See also|Ref:\s*\d)',
            re.IGNORECASE
        )
        parts, chars = [], 0
        for line in text.splitlines():
            # Strip inline HTML tags before evaluating the line
            line = re.sub(r'<[^>]+>', '', line).strip()
            if not line or len(line) < 3 or skip.match(line): continue
            if chars > 1500: break
            parts.append(line)
            chars += len(line)

        return (title[:500], "\n".join(parts)[:2000])

    else:
        # ── HTML fallback — extract <main>/<article>, strip scripts ───────
        main_m = (
            re.search(r'<main[^>]*>(.*?)</main>',       text, re.DOTALL | re.IGNORECASE) or
            re.search(r'<article[^>]*>(.*?)</article>', text, re.DOTALL | re.IGNORECASE)
        )
        content = main_m.group(1) if main_m else text
        content = re.sub(r'<script[^>]*>.*?</script>', '', content, flags=re.DOTALL | re.IGNORECASE)
        content = re.sub(r'<style[^>]*>.*?</style>',   '', content, flags=re.DOTALL | re.IGNORECASE)
        plain   = re.sub(r'<[^>]+>', ' ', content)
        plain   = re.sub(r'\{[^}]*\}', ' ', plain)
        plain   = re.sub(r'\s+', ' ', plain).strip()

        title = ""
        h1 = re.search(r'<h1[^>]*>(.*?)</h1>', text, re.IGNORECASE | re.DOTALL)
        if h1:
            title = re.sub(r'<[^>]+>', '', h1.group(1)).strip()

        return (title[:500], plain[:2000])


def fetch_title(url: str) -> str:
    return fetch_title_and_synopsis(url)[0]


def parse_dates(source: str) -> dict:
    dates = {"dbd": "", "ebd": "", "ge": ""}
    text  = re.sub(r'<[^>]+>', ' ', source)
    text  = re.sub(r'\s+', ' ', text)

    dbd = re.search(r'Introduced in the [^\(]+\(([^)]+)\)', text, re.IGNORECASE)
    ebd = (
        re.search(r'Status changed in the [^\(]+\(([^)]+)\)', text, re.IGNORECASE) or
        re.search(
            r'planned to change in ([A-Za-z]+ [\d,\-]+ \d{4}|[A-Za-z]+ \d{4})'
            r'[^.]{0,60}?to[^.]{0,30}?Enabled by Default',
            text, re.IGNORECASE
        )
    )
    ge = re.search(
        r'planned to change in ([A-Za-z]+ [\d,\-]+ \d{4}|[A-Za-z]+ \d{4})'
        r'[^.]{0,60}?to[^.]{0,30}?Generally Enabled',
        text, re.IGNORECASE
    )

    if dbd: dates["dbd"] = dbd.group(1).strip()
    if ebd: dates["ebd"] = ebd.group(1).strip()
    if ge:  dates["ge"]  = ge.group(1).strip()
    return dates


def parse_bcr_rows(source: str, bundle_id: str, dates: dict) -> list:
    results          = []
    current_category = "General"

    row_pat = re.compile(
        r'<tr[^>]*>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>',
        re.DOTALL | re.IGNORECASE
    )

    for m in row_pat.finditer(source):
        col1 = m.group(1).strip()
        col2 = m.group(2).strip()

        bcr_match = (
            re.search(
                r'href=["\'](?:/en)?/release-notes/bcr-bundles/(\d{4}_\d{2}/bcr-(\d+))["\']',
                col1,
            ) or
            re.search(
                r'\[\]\(/(?:en/)?release-notes/bcr-bundles/(\d{4}_\d{2}/bcr-(\d+))\)',
                col1,
            )
        )

        if not bcr_match:
            strong = re.search(r'<(?:strong|b)[^>]*>([^<]+)</(?:strong|b)>', col1)
            if strong:
                cat = strong.group(1).strip()
            else:
                md = re.match(r'^\*\*(.+?)\*\*$', col1.strip())
                cat = md.group(1).strip() if md else None
            if cat and cat not in ('Impact Score', 'Additional Notes', 'Notes', 'Comments'):
                current_category = cat
            continue

        bcr_path = bcr_match.group(1)
        bcr_num  = bcr_match.group(2)
        bcr_id   = f"{bundle_id}/bcr-{bcr_num}"
        full_url = f"https://docs.snowflake.com/en/release-notes/bcr-bundles/{bcr_path}"
        impact   = normalize_impact(re.sub(r'<[^>]+>', '', col2).strip())

        results.append({
            "bcr_id":      bcr_id,
            "category":    current_category,
            "title":       f"BCR-{bcr_num}",
            "description": "",
            "impact":      impact,
            "url":         full_url,
            **dates,
        })

    return results


def normalize_impact(raw: str) -> str:
    r = raw.strip().lower()
    if r == "high":   return "High"
    if r == "medium": return "Medium"
    if r == "low":    return "Low"
    return "TBD"
$$;

-- =============================================================================
-- PROCEDURE: ENRICH_BCR_DESCRIPTIONS  (v2 — shares same fetch_doc() pattern)
-- =============================================================================
-- Drop the old 1-param signature first to avoid overload ambiguity.
-- Snowflake rejects CREATE OR REPLACE when an existing 1-param version
-- and a new 2-param version (with a default) would both match a 1-arg call.
DROP PROCEDURE IF EXISTS ENRICH_BCR_DESCRIPTIONS(INT);
CREATE OR REPLACE PROCEDURE ENRICH_BCR_DESCRIPTIONS(LIMIT_N INT, FORCE_ALL BOOLEAN DEFAULT FALSE)
RETURNS STRING
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python', 'requests')
EXTERNAL_ACCESS_INTEGRATIONS = (SNOWFLAKE_DOCS_ACCESS)
HANDLER = 'enrich'
AS $$
import requests, re

HDR = {"User-Agent": "Mozilla/5.0"}

def fetch_doc(url: str, timeout: int = 10) -> tuple:
    """Try .md first; fall back to HTML. Returns (text, is_markdown)."""
    base   = url.rstrip("/").removesuffix(".md")
    md_url = base + ".md"
    try:
        r = requests.get(md_url, timeout=timeout, headers=HDR)
        if r.status_code == 200:
            return (r.text, True)
    except Exception:
        pass
    try:
        r = requests.get(base, timeout=timeout, headers=HDR)
        if r.status_code == 200:
            return (r.text, False)
    except Exception:
        pass
    return ("", True)


def fetch_title_and_synopsis(url: str) -> tuple:
    text, is_md = fetch_doc(url)
    if not text:
        return ("", "")

    if is_md:
        title = ""
        h1 = re.search(r'^#\s+(.+)$', text, re.MULTILINE)
        if h1:
            title = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', h1.group(1)).strip()
        skip = re.compile(
            r'^(#|This behavior change is in|For the current status|'
            r'For more information|See also|Ref:\s*\d)',
            re.IGNORECASE
        )
        parts, chars = [], 0
        for line in text.splitlines():
            line = re.sub(r'<[^>]+>', '', line).strip()  # strip inline HTML tags
            if not line or len(line) < 3 or skip.match(line): continue
            if chars > 1500: break
            parts.append(line)
            chars += len(line)
        return (title[:500], "\n".join(parts)[:2000])
    else:
        main_m = (
            re.search(r'<main[^>]*>(.*?)</main>',       text, re.DOTALL | re.IGNORECASE) or
            re.search(r'<article[^>]*>(.*?)</article>', text, re.DOTALL | re.IGNORECASE)
        )
        content = main_m.group(1) if main_m else text
        content = re.sub(r'<script[^>]*>.*?</script>', '', content, flags=re.DOTALL | re.IGNORECASE)
        content = re.sub(r'<style[^>]*>.*?</style>',   '', content, flags=re.DOTALL | re.IGNORECASE)
        plain   = re.sub(r'<[^>]+>', ' ', content)
        plain   = re.sub(r'\{[^}]*\}', ' ', plain)
        plain   = re.sub(r'\s+', ' ', plain).strip()
        title   = ""
        h1 = re.search(r'<h1[^>]*>(.*?)</h1>', text, re.IGNORECASE | re.DOTALL)
        if h1:
            title = re.sub(r'<[^>]+>', '', h1.group(1)).strip()
        return (title[:500], plain[:2000])


def enrich(session, limit_n: int, force_all: bool = False) -> str:
    if force_all:
        where = "DOCS_URL IS NOT NULL AND DOCS_URL != '' AND UNBUNDLED IS DISTINCT FROM TRUE"
    else:
        where = "(DESCRIPTION IS NULL OR DESCRIPTION = '' OR TITLE LIKE 'BCR-%') AND DOCS_URL IS NOT NULL AND DOCS_URL != '' AND UNBUNDLED IS DISTINCT FROM TRUE"

    rows = session.sql(f"""
        SELECT BCR_ID, DOCS_URL FROM BCR_TRACKER_DB.TRACKING.BCR_REGISTRY
        WHERE {where}
        ORDER BY FETCHED_AT DESC
        LIMIT ?
    """, [limit_n]).collect()

    updated = 0
    for row in rows:
        bcr_id, docs_url = row[0], row[1]
        title, synopsis = fetch_title_and_synopsis(docs_url)
        if not title and not synopsis:
            continue
        if force_all:
            # Force overwrite — replace whatever is stored
            session.sql("""
                UPDATE BCR_TRACKER_DB.TRACKING.BCR_REGISTRY
                SET TITLE       = COALESCE(NULLIF(?, ''), TITLE),
                    DESCRIPTION = ?
                WHERE BCR_ID = ?
            """, [title, synopsis, bcr_id]).collect()
        else:
            session.sql("""
                UPDATE BCR_TRACKER_DB.TRACKING.BCR_REGISTRY
                SET TITLE       = COALESCE(NULLIF(?, ''), TITLE),
                    DESCRIPTION = COALESCE(NULLIF(?, ''), DESCRIPTION)
                WHERE BCR_ID = ?
            """, [title, synopsis, bcr_id]).collect()
        updated += 1

    mode = "force re-fetch" if force_all else "backfill"
    return f"OK: {mode} enriched {updated} of {len(rows)} BCR descriptions"
$$;

-- =============================================================================
-- PROCEDURE: SYNC_ACTIVE_BUNDLES
-- =============================================================================
CREATE OR REPLACE PROCEDURE SYNC_ACTIVE_BUNDLES()
RETURNS STRING
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python')
HANDLER = 'sync_bundles'
AS $$
import json

def sync_bundles(session) -> str:
    raw     = session.sql("SELECT SYSTEM$SHOW_ACTIVE_BEHAVIOR_CHANGE_BUNDLES()").collect()[0][0]
    bundles = json.loads(raw)

    results = []
    for b in bundles:
        bundle_id  = b.get("name", "")
        if not bundle_id:
            continue
        is_default = b.get("isDefault", False)
        is_enabled = b.get("isEnabled", False)
        if is_default and is_enabled:   status = "Enabled by Default"
        elif not is_default and not is_enabled: status = "Disabled by Default"
        elif is_enabled:                status = "Enabled"
        else:                           status = "Draft"

        res = session.sql(
            "CALL BCR_TRACKER_DB.TRACKING.FETCH_BCR_BUNDLE(?, ?)",
            [bundle_id, status]
        ).collect()[0][0]
        results.append(f"{bundle_id} ({status}): {res}")

    try:
        enrich = session.sql(
            "CALL BCR_TRACKER_DB.TRACKING.ENRICH_BCR_DESCRIPTIONS(50, FALSE)"
        ).collect()[0][0]
        results.append(f"Enrichment: {enrich}")
    except Exception as e:
        results.append(f"Enrichment skipped: {e}")

    return "\n".join(results) if results else "No active bundles returned by SYSTEM$ function"
$$;

-- =============================================================================
-- PROCEDURE: RUN_REGRESSION_SNAPSHOT
-- =============================================================================
CREATE OR REPLACE PROCEDURE RUN_REGRESSION_SNAPSHOT()
RETURNS STRING
LANGUAGE SQL
AS
$$
BEGIN
    MERGE INTO BCR_TRACKER_DB.TRACKING.BCR_REGRESSION_SNAPSHOTS tgt
    USING (
        SELECT
            'ACCOUNT_WIDE'                                              AS BUNDLE_ID,
            DATE_TRUNC('day', START_TIME)::DATE                         AS SNAPSHOT_DATE,
            COUNT(*)                                                     AS TOTAL_QUERIES,
            COUNT_IF(ERROR_CODE IS NOT NULL)                             AS ERROR_COUNT,
            ROUND(DIV0(COUNT_IF(ERROR_CODE IS NOT NULL)::FLOAT * 100,
                       COUNT(*)), 4)                                     AS ERROR_RATE
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD('day', -30, CURRENT_DATE())
          AND START_TIME <  CURRENT_DATE()
        GROUP BY DATE_TRUNC('day', START_TIME)::DATE
    ) src
    ON  tgt.BUNDLE_ID     = src.BUNDLE_ID
    AND tgt.SNAPSHOT_DATE = src.SNAPSHOT_DATE
    WHEN NOT MATCHED THEN INSERT
        (BUNDLE_ID, SNAPSHOT_DATE, TOTAL_QUERIES, ERROR_COUNT, ERROR_RATE)
    VALUES
        (src.BUNDLE_ID, src.SNAPSHOT_DATE, src.TOTAL_QUERIES,
         src.ERROR_COUNT, src.ERROR_RATE);

    RETURN 'OK: regression snapshots updated';
END;
$$;

-- =============================================================================
-- STEP 5 — SCHEDULED TASKS
-- =============================================================================
CREATE TASK BCR_WEEKLY_SYNC
    WAREHOUSE = IDENTIFIER($BCR_WH)
    SCHEDULE  = 'USING CRON 0 7 * * 1 UTC'
    COMMENT   = 'Auto-discovers active BCR bundles via SYSTEM$ and fetches new BCR content'
AS
    CALL BCR_TRACKER_DB.TRACKING.SYNC_ACTIVE_BUNDLES();

CREATE TASK BCR_NIGHTLY_REGRESSION
    WAREHOUSE = IDENTIFIER($BCR_WH)
    SCHEDULE  = 'USING CRON 0 6 * * * UTC'
    COMMENT   = 'Daily error rate snapshot for regression monitoring'
AS
    CALL BCR_TRACKER_DB.TRACKING.RUN_REGRESSION_SNAPSHOT();

ALTER TASK BCR_WEEKLY_SYNC       RESUME;
ALTER TASK BCR_NIGHTLY_REGRESSION RESUME;

-- =============================================================================
-- STEP 6 — INITIAL LOAD
-- Fetches active BCR bundles from Snowflake + descriptions from docs.
-- This takes ~2 minutes. When it completes, the verify query below should
-- show BCR_COUNT > 0 and WITH_DESC > 0 for each active bundle.
-- =============================================================================
CALL SYNC_ACTIVE_BUNDLES();

-- =============================================================================
-- VERIFY — expected output: BCR_COUNT > 0, WITH_DESC > 0 per bundle
-- =============================================================================
SELECT r.BUNDLE_ID, r.BUNDLE_STATUS, COUNT(*) AS BCR_COUNT,
       COUNT_IF(r.IMPACT_DEFAULT='High')   AS HIGH,
       COUNT_IF(r.IMPACT_DEFAULT='Medium') AS MEDIUM,
       COUNT_IF(r.IMPACT_DEFAULT='Low')    AS LOW,
       COUNT_IF(r.DESCRIPTION IS NOT NULL AND r.DESCRIPTION != '') AS WITH_DESC
FROM BCR_REGISTRY r
WHERE r.UNBUNDLED IS DISTINCT FROM TRUE
GROUP BY 1, 2
ORDER BY 1 DESC;

SELECT 'BCR Tracker v2 setup complete — paste streamlit_app.py into Snowsight to deploy the app.' AS STATUS;

# Cortex Code: First Prompts, Sandbox Training and RBAC Plan

A starter guide for teams adopting **Cortex Code (CoCo)** in Snowsight. Learn the
workflow in a sandbox, run read-only investigations in production, then put a
least-privilege role design and session guardrails in place.

| Part | Focus |
|---|---|
| **A: Sandbox** | Learn the CoCo workflow in a dev account. Safe to experiment. Do this first. |
| **B: Production** | Read-only investigation prompts for common platform issues. |
| **C: RBAC and guardrails** | A dedicated, least-privilege CoCo role design, cost controls and approval boundaries. |

---

## What is Cortex Code?

Cortex Code is an AI assistant built into Snowsight. It can read your account
context (warehouses, databases, tables, roles, query history) and help you
investigate, plan and build. It doesn't make changes unless you ask it to and
approve the SQL it generates.

## Ground rules for every session

- **Read first, change later.** Start with read-only prompts. Review any DDL, DML or GRANT line by line before you run it.
- **State your context.** Tell CoCo the account, role, warehouse and database you're working in.
- **Review everything.** CoCo writes the SQL; you decide whether to run it.
- **No secrets in prompts.** Never paste passwords, tokens, connection strings or sensitive data.
- **No ACCOUNTADMIN for routine work.** Use a functional role (for example `COCO_READER`).
- **Reset when you switch topics.** Start a new session for each investigation so context doesn't mix.

## The workflow

**Understand → Inspect → Plan → Approve → Implement → Review → Verify**

For anything beyond a single statement, ask CoCo to *"plan this first and wait
for my approval"*, then approve one step at a time.

---

# Part A: Sandbox / dev account

## Getting started in Snowsight

1. Sign in to your **dev** account.
2. Open **Projects → Workspaces** and create or open a SQL file.
3. Click the **CoCo** icon in the lower-right corner.
4. Confirm the role, warehouse, database and schema match your dev environment.
5. Paste a prompt below and press Enter.

> If you don't see the CoCo icon, ask your admin to confirm Cortex Code is enabled
> and that your role has the `SNOWFLAKE.COPILOT_USER` and `SNOWFLAKE.CORTEX_USER`
> database roles.

### S1: Hello world (read-only)

```text
I'm working in a development account.
Confirm the active account name, my current role, warehouse, database, and schema.
List any databases and warehouses you can see.
Summarize what objects are available to me and what my role can access.
Do not change anything. Just tell me what you see.
```

**Expect:** the account, role, and a list of databases and warehouses. If CoCo sees nothing, your role needs grants.

### S2: Explore a table (read-only)

Type `@` in the prompt to pick any object from the catalog.

**Option A: table detail**
```text
Explain this table: @{DATABASE}.{SCHEMA}.{TABLE}
Show me the column names, data types, row count, clustering keys (if any),
when it was last modified, and the most common recent queries against it.
Do not change anything.
```

**Option B: short form**
```text
Explain the structure, row count, clustering, and recent query
patterns for [TABLE_NAME]. Do not modify the table.
```

### S3: Write SQL (read-only)

```text
Write me a SQL query that shows the 20 most recent rows
from @{DATABASE}.{SCHEMA}.{TABLE}
ordered by the most recent timestamp or date column.
Show the SQL but do not execute it. I want to review it first.
```

**Expect:** a SELECT statement. Check the columns and ORDER BY, then run it yourself.

### S4: Create and clean up (DDL, dev only)

```text
Create a transient table called COCO_TEST in my current schema.
Give it three columns: ID (NUMBER), DESCRIPTION (VARCHAR),
CREATED_AT (TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()).
Insert 5 sample rows with made-up data.
Then run a SELECT * to show me the result.
After I confirm it works, show me the DROP TABLE statement to clean up.
```

**Expect:** CREATE, INSERT and SELECT statements to review, then a DROP to clean up.

### S5: Follow-up questions (read-only)

```text
Find the longest-running queries in the past 7 days for my current
warehouse in this dev account. Show duration, bytes scanned, remote spill,
and partition pruning ratio (partitions scanned / partitions total).
Do not modify anything.
```

Then ask a follow-up: *"For the slowest query you just found, explain what it does and whether it could be optimized."*

Once you're comfortable with S1–S5, you're ready for Part B.

---

# Part B: Production investigations (all read-only)

Switch to your production account in Snowsight before pasting these prompts.

### P1: Orient

```text
I'm working in our production account.
Confirm the active account, my role, warehouse, database, and schema.
List the databases you can see that follow our naming pattern (like [PREFIX]_*).
Summarize what my role can access in those databases.
Do not change anything. Just show me what you see.
```

### P2: Longest-running task queries

```text
Show me the top 10 longest-running task queries in this account
from the last 14 days using SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY.
For each, show the parameterized query hash, average duration,
number of executions, average bytes scanned, average bytes spilled
to remote storage, and the warehouse used.
Sort by average duration descending. Do not change anything.
```

**Look for:** long, high-scan task patterns. These are candidates for Dynamic Tables or query rewrites.

### P3: Who is using ACCOUNTADMIN or SECURITYADMIN?

```text
Using SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY from the last 30 days,
show me which users are running queries with ROLE_NAME = 'ACCOUNTADMIN'
or ROLE_NAME = 'SECURITYADMIN'.
Group by USER_NAME and ROLE_NAME and show the query count, distinct statement
types (SELECT, INSERT, CREATE, GRANT, etc.), and the most recent query date.
Using SNOWFLAKE.ACCOUNT_USAGE.USERS, label each user as a human user or a
service/application user (TYPE = SERVICE / LEGACY_SERVICE, or no human login).
Sort by query count descending. Do not change grants. Summarize what you find.
```

**Look for:** people running routine queries under admin roles. Move them to a functional role (see Part C).

### P4: Workload latency and pruning

```text
Using SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY from the last 14 days,
find queries running against warehouses that contain '[WAREHOUSE_PATTERN]' in the name.
Show the top 20 queries by total execution time (sum of all runs).
For each, show the parameterized query hash, execution count,
average duration, average bytes scanned, average partitions scanned
vs total partitions, and average bytes spilled to remote storage.
Highlight any query where partitions scanned / total partitions > 0.5
(poor pruning). Do not change anything.
```

**Look for:** queries scanning more than 50% of partitions are clustering candidates. Heavy remote spill points to sizing or a join that could be rewritten.

### P5: Client driver inventory

**Option A: inventory**
```text
Using SNOWFLAKE.ACCOUNT_USAGE.SESSIONS or LOGIN_HISTORY,
show me the distinct client application names, client driver versions,
and client operating systems that have connected in the last 30 days.
Group by application name + driver version + OS and show the session count.
Sort by session count descending. Do not change anything.
Also show the account and user-level TIMEZONE parameter settings
for the service users those apps connect as.
```

**Option B: upgrade readiness**
```text
Review the client driver versions in use by application sessions in this
account. Identify connection-pool behavior, async patterns, and timezone
settings that may be affected by a driver upgrade. Do not edit anything.
```

> In Snowsight, CoCo sees what Snowflake records (driver versions, sessions,
> parameters). It can't read your application source code. For a code-level review,
> use the CLI prompt (C1) from your repository.

### P6: Error rate by error code

```text
Using SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY from the last 14 days,
show me all failed queries (EXECUTION_STATUS != 'SUCCESS')
where the warehouse or database name contains '[WORKLOAD_PATTERN]'.
Group by ERROR_CODE and ERROR_MESSAGE (truncated to 100 chars)
and show the count for each. Sort by count descending.
Do not change anything.
```

**Look for:** recurring noise errors, such as 002003 (object already exists). Adding `IF NOT EXISTS` guards removes the noise so real errors stand out.

### P7: Plan a Dynamic Table conversion (plan only)

**Option A: let CoCo find a candidate**
```text
I want to explore whether Dynamic Tables could replace one of the
task chains in this account.
First, find the longest-running task using
SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY from the last 14 days.
Then explain:
- What the task does (show me its SQL if visible)
- What tables it reads from and writes to
- Whether its logic is a candidate for a Dynamic Table
- What the target lag would be
- What would need to change
Do not create or modify anything. Just give me a plan I can review.
```

**Option B: a task you already know**
```text
Look at the task [TASK_NAME] and its dependencies.
Could this be replaced with a Dynamic Table?
Compare refresh behavior, latency, retry logic, and downstream
impact. Do not create or replace objects.
```

### P8: Handoff summary

```text
Create a concise handoff for another engineer based on this session.
Include the goal, account and role used, objects and queries inspected,
evidence collected (with numbers), open questions, risks, and the exact next step.
Separate observed facts from hypotheses.
Do not claim anything is fixed without validation evidence. Do not change anything.
```

---

# Part C: Production RBAC plan

## Problem

Running CoCo under ACCOUNTADMIN means a developer approving generated SQL quickly
could execute DDL, GRANT or DROP statements with account-level privileges. CoCo
doesn't run changes on its own, but the role sets how much damage a mistaken
approval can do. Use a dedicated least-privilege role.

## Proposed role hierarchy

| Role | Purpose | Key privileges | Who |
|---|---|---|---|
| `COCO_READER` | Read-only investigations | USAGE on warehouses, SELECT on data, IMPORTED PRIVILEGES on SNOWFLAKE | All CoCo users (default role) |
| `COCO_DEVELOPER` | Prototyping in a dev sandbox schema | Inherits reader, plus CREATE in a sandbox schema and OPERATE on dev warehouses | Approved engineers |
| `PLATFORM_ADMIN` | Platform administration; replaces routine ACCOUNTADMIN | MANAGE GRANTS, CREATE/ALTER WAREHOUSE, MONITOR | 1–2 platform owners |

```sql
-- Run as SECURITYADMIN (one-time setup)
CREATE ROLE IF NOT EXISTS COCO_READER    COMMENT = 'Read-only Cortex Code role';
CREATE ROLE IF NOT EXISTS COCO_DEVELOPER COMMENT = 'Cortex Code role for dev sandbox schemas only';
CREATE ROLE IF NOT EXISTS PLATFORM_ADMIN COMMENT = 'Platform admin; replaces routine ACCOUNTADMIN use';

GRANT ROLE COCO_READER    TO ROLE COCO_DEVELOPER;
GRANT ROLE COCO_DEVELOPER TO ROLE PLATFORM_ADMIN;
GRANT ROLE PLATFORM_ADMIN TO ROLE SYSADMIN;

-- Required for CoCo in Snowsight
GRANT DATABASE ROLE SNOWFLAKE.COPILOT_USER TO ROLE COCO_READER;
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER  TO ROLE COCO_READER;
```

### Reader grants

```sql
GRANT USAGE ON WAREHOUSE <QUERY_WH> TO ROLE COCO_READER;

-- Repeat for each database the team needs
GRANT USAGE  ON DATABASE <DB>                 TO ROLE COCO_READER;
GRANT USAGE  ON ALL SCHEMAS IN DATABASE <DB>  TO ROLE COCO_READER;
GRANT SELECT ON ALL TABLES  IN DATABASE <DB>  TO ROLE COCO_READER;
GRANT SELECT ON ALL VIEWS   IN DATABASE <DB>  TO ROLE COCO_READER;
GRANT SELECT ON FUTURE TABLES IN DATABASE <DB> TO ROLE COCO_READER;
GRANT SELECT ON FUTURE VIEWS  IN DATABASE <DB> TO ROLE COCO_READER;

-- ACCOUNT_USAGE access (query history, warehouse history, etc.)
GRANT IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE TO ROLE COCO_READER;
```

### Developer grants (sandbox schema only)

```sql
CREATE SCHEMA IF NOT EXISTS <DEV_DB>.COCO_SANDBOX
  COMMENT = 'Sandbox for CoCo experimentation; safe to drop objects here';

GRANT USAGE ON DATABASE <DEV_DB>                         TO ROLE COCO_DEVELOPER;
GRANT USAGE ON SCHEMA <DEV_DB>.COCO_SANDBOX              TO ROLE COCO_DEVELOPER;
GRANT CREATE TABLE         ON SCHEMA <DEV_DB>.COCO_SANDBOX TO ROLE COCO_DEVELOPER;
GRANT CREATE VIEW          ON SCHEMA <DEV_DB>.COCO_SANDBOX TO ROLE COCO_DEVELOPER;
GRANT CREATE FUNCTION      ON SCHEMA <DEV_DB>.COCO_SANDBOX TO ROLE COCO_DEVELOPER;
GRANT CREATE DYNAMIC TABLE ON SCHEMA <DEV_DB>.COCO_SANDBOX TO ROLE COCO_DEVELOPER;
GRANT OPERATE ON WAREHOUSE <DEV_WH>                      TO ROLE COCO_DEVELOPER;
```

> **Safety boundary:** `COCO_DEVELOPER` can't create, alter or drop anything in
> production databases. `COCO_SANDBOX` is the only schema it can write to.

### Assign users

```sql
GRANT ROLE COCO_READER    TO USER <USER_1>;
GRANT ROLE COCO_DEVELOPER TO USER <USER_1>;
GRANT ROLE PLATFORM_ADMIN TO USER <PLATFORM_OWNER>;
ALTER USER <USER_1> SET DEFAULT_ROLE = 'COCO_READER';
```

## Cost controls

```sql
CREATE OR REPLACE RESOURCE MONITOR COCO_MONITOR
  WITH CREDIT_QUOTA = 50          -- adjust to current 7-day average + 25%
  FREQUENCY = WEEKLY
  START_TIMESTAMP = IMMEDIATELY
  TRIGGERS ON 75 PERCENT DO NOTIFY
           ON 90 PERCENT DO NOTIFY
           ON 100 PERCENT DO NOTIFY;   -- notify only during the pilot

ALTER WAREHOUSE <QUERY_WH> SET RESOURCE_MONITOR = 'COCO_MONITOR';
```

Use notify-only triggers during the pilot. Once you have a stable 2–3 week
baseline, consider a suspend trigger on **non-critical** warehouses only. Never
auto-suspend warehouses that serve customer-facing workloads without a manual review.

## Session guardrails (Restricted Session Scope)

RBAC controls what the user can access. A **Restricted Session Scope (RSS)**
adds a second limit on what the CoCo session itself can do.

**Production preset: `PROD_READ_ONLY`**
- Open `/guardrails` and create a named scope that allows **data read** only.
- Block switching to high-privilege roles (ACCOUNTADMIN, SECURITYADMIN, USERADMIN, SYSADMIN).
- Allow only the approved reader role (`COCO_READER`).
- Activate the scope before any production investigation, and confirm it with `/guardrails status`.

**Sandbox preset: `DEV_SANDBOX`**
- Create a separate scope allowing data read plus the minimum write privileges for `COCO_SANDBOX`.
- Don't give it account-wide object management or production access.
- Start a fresh session when moving from sandbox to production.

> Activate RSS through the `/guardrails` panel, not `ALTER SESSION`. If RSS blocks
> an operation, adjust the scope rather than switching to ACCOUNTADMIN.

## Approval boundaries

| Change type | Example | Approver | Where |
|---|---|---|---|
| Read-only investigation | SELECT, SHOW, DESCRIBE, EXPLAIN | Self | Any environment |
| Test object | CREATE TRANSIENT TABLE in COCO_SANDBOX | Self | Dev sandbox only |
| Query optimization | ALTER TABLE ... CLUSTER BY | Peer review + Platform Admin | Dev first, then prod |
| Task/pipeline change | CREATE OR REPLACE DYNAMIC TABLE | Peer review + Platform Admin | Dev first, then prod |
| RBAC change | GRANT, REVOKE, CREATE ROLE | Platform Admin | Prod, after a documented plan |
| Warehouse sizing | ALTER WAREHOUSE ... SET SIZE | Platform Admin | Prod, after cost analysis |
| Account-level change | Network policy, parameters | ACCOUNTADMIN + change control | Your change-management process |

**Never do these without approval:**
- Run GRANT or REVOKE from CoCo-generated SQL without Platform Admin review.
- DROP production objects, even as part of a suggested replacement.
- Resize a production warehouse to mask a query problem. Investigate the query first.
- CREATE OR REPLACE a production table or task. Test with versioned names in dev first.
- Paste query results containing sensitive data back into a prompt.

## Rollout sequence

1. Create the roles and grants (one-time, SECURITYADMIN).
2. Assign 2–3 pilot users to `COCO_READER`.
3. Run Part A in the dev account.
4. Run Part B in production under `COCO_READER`.
5. Promote users to `COCO_DEVELOPER` after they finish the sandbox exercises.
6. Each week, review QUERY_HISTORY for the CoCo roles to confirm no unauthorized changes.
7. Expand based on measured outcomes.

---

# Adding CoCo Desktop or CLI later

| Mode | Best for | Setup |
|---|---|---|
| Snowsight (start here) | SQL work, investigation, Parts A and B | None |
| CoCo Desktop | Local repo with a graphical experience | Install the desktop app |
| CoCo CLI | Terminal workflows, application code, dbt, CI/CD | Install the CLI |

**CLI install (Windows PowerShell):**
```powershell
irm https://ai.snowflake.com/static/cc-scripts/install.ps1 | iex
cortex --version
```
For macOS, Linux or WSL, follow the installer in the official CLI docs. Then start a
session from your repository root with `cortex -c <your-dev-connection>`.

### C1: Driver upgrade code review (CLI, read-only until approved)

Run this from the root of an application repository:

```text
Review this repository for a planned Snowflake client driver upgrade.
Find:
- Exception handling around async open/close of connections
- Logic that assumes a faulted connection ends in a specific state
- Connection-pool settings
- Session timezone and TIMESTAMP_LTZ handling
- Certificate revocation (CRL) settings
- Large-number conversions that could overflow
Return file locations, evidence, recommended tests, and unresolved questions.
Do not edit files until I approve the plan.
```

---

# What good looks like after week 1

- [ ] Complete S1–S5 in the sandbox, including creating and dropping a test table
- [ ] Run at least one read-only production investigation (P2–P7)
- [ ] Ask CoCo to plan a multi-step task and approve it one step at a time
- [ ] Review generated SQL line by line before running it
- [ ] Produce a findings summary for your team (P8)
- [ ] Know when to reset and start a fresh session

# Quick reference

| Prompt | Account | What it does | Safety |
|---|---|---|---|
| S1 Hello world | Dev | Confirm what CoCo can see | Read-only |
| S2 Explore table | Dev | Explain a table | Read-only |
| S3 Write SQL | Dev | Draft a query to review | Read-only |
| S4 Create and clean up | Dev | Create, verify, drop cycle | DDL, dev only |
| S5 Follow-up | Dev | Slow queries, then a follow-up | Read-only |
| P1 Orient | Prod | Confirm account, databases, access | Read-only |
| P2 Long tasks | Prod | Profile long-running task queries | Read-only |
| P3 Admin roles | Prod | ACCOUNTADMIN/SECURITYADMIN usage | Read-only |
| P4 Latency | Prod | Latency, pruning and spill for a workload | Read-only |
| P5 Drivers | Prod | Driver inventory or upgrade readiness | Read-only |
| P6 Errors | Prod | Failed queries by error code | Read-only |
| P7 DT plan | Prod | Dynamic Table conversion plan | Plan only |
| P8 Handoff | Prod | Summarize findings | Read-only |
| C1 Code review | CLI + repo | Driver upgrade impact scan | Read-only until approved |

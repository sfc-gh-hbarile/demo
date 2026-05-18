# Interactive Tables Benchmark Kit

A concurrent load test harness that compares **Interactive Tables** (always-on, clustered, sub-second point lookups) against **Standard Warehouses** under realistic production concurrency (10-100+ threads).

## What This Measures

- **Latency** (p50/p95/p99) at each concurrency level
- **Throughput** (queries per second) under sustained load
- **Cost efficiency** (queries completed per credit consumed)
- **Failure patterns** (Interactive's 5-second SLA enforcement vs standard queueing)

## Quick Start

### 1. Prerequisites

- Python 3.11+
- Java 17+ (for JDBC driver)
- Snowflake account with Interactive Tables enabled

```bash
# Install Python dependencies
pip install -r requirements.txt

# Verify Java
java -version   # needs 17+
export JAVA_HOME=$(/usr/libexec/java_home -v 17)  # macOS
```

### 2. Set Up Data

Run `setup_data.sql` in a Snowflake worksheet. This creates:
- 100M positions (fact table)
- 1M accounts
- 100K securities
- Interactive table copies (clustered by account_id, trade_date)

Adjust row counts and schema to match your scale.

### 3. Configure

Edit `config.yaml`:

```yaml
connection:
  database: "YOUR_DATABASE"
  schema: "YOUR_SCHEMA"

warehouses:
  standard: "YOUR_STANDARD_WH"
  interactive: "YOUR_INTERACTIVE_WH"

tables:
  standard:
    positions_table: "POSITIONS"
    securities_table: "SECURITIES"
  interactive:
    positions_table: "POSITIONS_INTERACTIVE"
    securities_table: "SECURITIES_INTERACTIVE"
```

**Queries:** The default queries are asset management point lookups and portfolio aggregations. Replace with your own queries in the `queries:` section. Use `{placeholders}` for randomized parameters.

### 4. Set Environment Variables

```bash
export SNOWFLAKE_ACCOUNT_URL="your-org-account.snowflakecomputing.com"
export SNOWFLAKE_USER="your_user"
export SNOWFLAKE_PAT_TOKEN="<your PAT token>"   # Recommended (bypasses MFA)
# OR: export SNOWFLAKE_PASSWORD="<password>"    # May trigger MFA prompts
```

**Creating a PAT token** (recommended for automated runs):
```sql
ALTER USER <your_user> ADD PAT benchmark_token
    DAYS_TO_EXPIRY = 30
    COMMENT = 'Interactive Tables benchmark';
-- Copy token_secret from output
```

### 5. Run

> **IMPORTANT: Point Lookups vs Mixed Mode**
>
> Interactive Tables are optimized for **point lookups** (key-based reads with sub-second SLA).
> Aggregation queries that scan large amounts of data **will timeout** due to the 5-second
> SLA enforcement on Interactive Warehouses. This is by design.
>
> - **First run (recommended):** Use the default `point_lookups_only: true` in config.yaml.
>   This gives a clean apples-to-apples comparison for the workload Interactive Tables are built for.
> - **Second run (optional):** Set `point_lookups_only: false` to demonstrate SLA enforcement
>   behavior with aggregation queries.

```bash
# Recommended first run — point lookups only (default config)
./run_benchmark.sh

# Override concurrency/duration on the command line
./run_benchmark.sh --concurrency "10,25,50" --duration 60

# Explicitly force point-lookups-only (overrides config.yaml)
./run_benchmark.sh --point-lookups-only

# Mixed workload (aggregations WILL timeout on Interactive — demonstrates SLA enforcement)
./run_benchmark.sh --concurrency "10,25,50" --duration 60 --mixed-workload

# Full suite (point lookups only)
./run_benchmark.sh --concurrency "10,25,50,75,100" --duration 120
```

**Command-line flags:**
| Flag | Effect |
|------|--------|
| `--point-lookups-only` | Only run point lookup queries (overrides config.yaml) |
| `--mixed-workload` | Include aggregation queries (overrides config.yaml) |
| `--concurrency "10,25,50"` | Set concurrency levels (comma-separated) |
| `--duration 60` | Seconds per concurrency level |
| `--interactive-only` | Only benchmark the Interactive warehouse |
| `--standard-only` | Only benchmark the Standard warehouse |

### 6. View Results

After a benchmark run completes, launch the interactive dashboard:

```bash
streamlit run benchmark_dashboard.py
```

The dashboard opens in your browser at `http://localhost:8501`.

**Data sources:** The dashboard automatically loads results from:
1. **Snowflake table** (default) — reads from the `BENCHMARK_RESULTS` table using the same env vars (`SNOWFLAKE_ACCOUNT_URL`, `SNOWFLAKE_USER`, `SNOWFLAKE_PAT_TOKEN`)
2. **CSV fallback** — toggle "Load from CSV" in the sidebar to read from `benchmark_results.csv` (no Snowflake connection required)

**Dashboard tabs:**
- **Latency** — p50/p95/p99 across concurrency levels
- **Throughput** — QPS and total queries completed
- **Cost Analysis** — cost per query, time to serve daily volume
- **Failures & Timeouts** — Interactive's 5-sec SLA enforcement
- **Raw Data** — full query-level results

## How It Works

1. Opens N concurrent JDBC connections (one per thread)
2. Each thread runs queries in a tight loop for the configured duration
3. Every query uses `USE_CACHED_RESULT=false` and randomized parameters to defeat caching
4. Results (latency, success/failure, timestamps) are collected per-query
5. Results are saved to CSV and optionally uploaded to a Snowflake table

### Query Tagging

All benchmark queries are tagged: `IT_BENCH_{warehouse}_{concurrency}_{run_id}`

You can query costs after a run:
```sql
SELECT query_tag, warehouse_name, COUNT(*), AVG(total_elapsed_time)
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE query_tag LIKE 'IT_BENCH_%'
  AND start_time > DATEADD('hour', -4, CURRENT_TIMESTAMP())
GROUP BY query_tag, warehouse_name;
```

## Customizing Queries

Edit the `queries:` section in `config.yaml`. Each query needs:

```yaml
queries:
  - name: "MY_LOOKUP"          # Identifier (appears in results)
    category: "point_lookup"    # "point_lookup" or "aggregation"
    weight: 80                  # Relative frequency
    sql: |
      SELECT * FROM {my_table}
      WHERE id = {account_id}
      LIMIT 100
```

Available placeholders:
| Placeholder | Description |
|---|---|
| `{account_id}` | Random int 1..max_account_id |
| `{security_id}` | Random int 1..max_security_id |
| `{trade_date}` | Random date within last N days |
| `{start_date}` | Same as trade_date |
| `{end_date}` | trade_date + 30 days |
| `{positions_table}` | Auto-mapped per warehouse type |
| `{securities_table}` | Auto-mapped per warehouse type |

Add any custom table placeholders in the `tables:` section of config.yaml.

## Two-Run Strategy (Recommended)

**Run 1: Point lookups only (default)** — clean apples-to-apples comparison for the workload Interactive Tables are designed for. No timeouts, no noise.

```bash
./run_benchmark.sh --concurrency "10,25,50" --duration 60
```

**Run 2: Mixed workload (optional)** — shows that aggregation queries hit the 5-second timeout on Interactive (by design). Demonstrates SLA enforcement.

```bash
./run_benchmark.sh --concurrency "10,25,50" --duration 60 --mixed-workload
```

## File Structure

```
├── config.yaml              # YOUR configuration (edit this)
├── benchmark_driver.py      # Load generator (don't need to edit)
├── benchmark_dashboard.py   # Streamlit dashboard
├── run_benchmark.sh         # One-command runner
├── setup_data.sql           # Sample data creation script
├── requirements.txt         # Python dependencies
└── README.md                # This file
```

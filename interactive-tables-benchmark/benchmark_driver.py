#!/usr/bin/env python3
"""
Interactive Tables Benchmark Driver
====================================
Runs concurrent queries against Standard vs Interactive warehouses using
the Snowflake JDBC driver (via jaydebeapi/jpype) to measure latency under load.

Usage:
    python benchmark_driver.py --config config.yaml
    python benchmark_driver.py --concurrency 10,25,50 --duration 60
    python benchmark_driver.py --point-lookups-only

Requirements:
    pip install -r requirements.txt
    Download snowflake-jdbc-*.jar (auto-downloaded by run_benchmark.sh)
"""

import argparse
import csv
import datetime
import logging
import os
import random
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import jaydebeapi
import jpype
import pandas as pd
import yaml


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class BenchmarkConfig:
    """All configuration for a benchmark run."""
    # Connection
    account_url: str = ""
    username: str = ""
    password: str = ""
    pat_token: str = ""
    database: str = ""
    schema: str = ""
    role: str = "SYSADMIN"

    # JDBC
    jdbc_jar_path: str = ""

    # Warehouses
    standard_warehouse: str = ""
    interactive_warehouse: str = ""

    # Table mappings (per warehouse type)
    tables_standard: dict = field(default_factory=dict)
    tables_interactive: dict = field(default_factory=dict)

    # Queries (loaded from config.yaml)
    queries: list = field(default_factory=list)

    # Benchmark parameters
    concurrency_levels: list = field(default_factory=lambda: [10, 25, 50, 75, 100])
    duration_seconds: int = 120
    warmup_queries: int = 20
    point_lookups_only: bool = False

    # Random parameter ranges
    max_account_id: int = 1_000_000
    max_security_id: int = 100_000
    trade_date_range_days: int = 90

    # Output
    results_csv: str = "benchmark_results.csv"
    upload_to_snowflake: bool = True
    results_table: str = "BENCHMARK_RESULTS"

    @classmethod
    def from_yaml(cls, path: str) -> "BenchmarkConfig":
        """Load config from YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f)

        config = cls()

        # Connection
        conn = data.get("connection", {})
        config.account_url = conn.get("account_url", config.account_url)
        config.username = conn.get("username", config.username)
        config.database = conn.get("database", config.database)
        config.schema = conn.get("schema", config.schema)
        config.role = conn.get("role", config.role)

        # Warehouses
        wh = data.get("warehouses", {})
        config.standard_warehouse = wh.get("standard", config.standard_warehouse)
        config.interactive_warehouse = wh.get("interactive", config.interactive_warehouse)

        # Benchmark params
        bench = data.get("benchmark", {})
        config.concurrency_levels = bench.get("concurrency_levels", config.concurrency_levels)
        config.duration_seconds = bench.get("duration_seconds", config.duration_seconds)
        config.warmup_queries = bench.get("warmup_queries", config.warmup_queries)
        config.point_lookups_only = bench.get("point_lookups_only", config.point_lookups_only)

        # Queries
        config.queries = data.get("queries", [])

        # Tables
        tables = data.get("tables", {})
        config.tables_standard = tables.get("standard", {})
        config.tables_interactive = tables.get("interactive", {})

        # Params
        params = data.get("params", {})
        config.max_account_id = params.get("max_account_id", config.max_account_id)
        config.max_security_id = params.get("max_security_id", config.max_security_id)
        config.trade_date_range_days = params.get("trade_date_range_days", config.trade_date_range_days)

        # Output
        output = data.get("output", {})
        config.results_csv = output.get("results_csv", config.results_csv)
        config.upload_to_snowflake = output.get("upload_to_snowflake", config.upload_to_snowflake)
        config.results_table = output.get("results_table", config.results_table)

        return config

    def apply_env_overrides(self):
        """Apply environment variable overrides (credentials, JDBC path)."""
        self.account_url = os.environ.get("SNOWFLAKE_ACCOUNT_URL", self.account_url)
        self.username = os.environ.get("SNOWFLAKE_USER", self.username)
        self.password = os.environ.get("SNOWFLAKE_PASSWORD", self.password)
        self.pat_token = os.environ.get("SNOWFLAKE_PAT_TOKEN", self.pat_token)
        self.jdbc_jar_path = os.environ.get("SNOWFLAKE_JDBC_JAR", self.jdbc_jar_path)
        self.role = os.environ.get("SNOWFLAKE_ROLE", self.role)


# ---------------------------------------------------------------------------
# JDBC Connection Management
# ---------------------------------------------------------------------------

def get_jdbc_url(config: BenchmarkConfig, warehouse: str, query_tag: str) -> str:
    """Build JDBC connection URL."""
    return (
        f"jdbc:snowflake://{config.account_url}/?"
        f"db={config.database}&"
        f"schema={config.schema}&"
        f"warehouse={warehouse}&"
        f"role={config.role}&"
        f"USE_CACHED_RESULT=false&"
        f"QUERY_TAG={query_tag}"
    )


def get_auth_credential(config: BenchmarkConfig) -> str:
    """Return credential (PAT token preferred, bypasses MFA)."""
    if config.pat_token:
        return config.pat_token
    return config.password


def create_connection(config: BenchmarkConfig, warehouse: str, query_tag: str):
    """Create a single JDBC connection."""
    url = get_jdbc_url(config, warehouse, query_tag)
    credential = get_auth_credential(config)
    conn = jaydebeapi.connect(
        "net.snowflake.client.jdbc.SnowflakeDriver",
        url,
        [config.username, credential],
        config.jdbc_jar_path,
    )
    return conn


# ---------------------------------------------------------------------------
# Query Execution
# ---------------------------------------------------------------------------

@dataclass
class QueryResult:
    """Single query execution result."""
    run_id: str
    run_timestamp: str
    warehouse_name: str
    warehouse_type: str
    concurrency_level: int
    query_type: str
    thread_id: int
    query_start: str
    query_end: str
    latency_ms: float
    success: bool
    error_message: str = ""
    benchmark_mode: str = "MIXED"


def generate_random_params(config: BenchmarkConfig) -> dict:
    """Generate random query parameters to defeat caching."""
    today = datetime.date.today()
    random_days_back = random.randint(0, config.trade_date_range_days - 1)
    trade_date = today - datetime.timedelta(days=random_days_back)
    end_date = trade_date + datetime.timedelta(days=30)
    return {
        "account_id": random.randint(1, config.max_account_id),
        "security_id": random.randint(1, config.max_security_id),
        "trade_date": trade_date.strftime("%Y-%m-%d"),
        "start_date": trade_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
    }


def pick_query(config: BenchmarkConfig) -> dict:
    """Pick a query from the config based on weights and mode."""
    available = config.queries
    if config.point_lookups_only:
        available = [q for q in available if q.get("category") == "point_lookup"]

    if not available:
        raise ValueError("No queries available for the current mode. Check config.yaml.")

    # Weighted random selection
    weights = [q.get("weight", 1) for q in available]
    total = sum(weights)
    r = random.uniform(0, total)
    cumulative = 0
    for q in available:
        cumulative += q.get("weight", 1)
        if r <= cumulative:
            return q
    return available[-1]


def build_query(query_def: dict, config: BenchmarkConfig, warehouse_type: str) -> tuple:
    """Build a concrete SQL query with random parameters. Returns (name, sql)."""
    params = generate_random_params(config)

    # Get table mappings for this warehouse type
    if warehouse_type == "INTERACTIVE":
        tables = config.tables_interactive
    else:
        tables = config.tables_standard

    # Merge params + table mappings for format string
    format_vars = {**params, **tables}

    sql = query_def["sql"].format(**format_vars)
    return query_def["name"], sql


def worker_thread(
    thread_id: int,
    config: BenchmarkConfig,
    warehouse: str,
    warehouse_type: str,
    concurrency_level: int,
    run_id: str,
    run_timestamp: str,
    duration_seconds: int,
    results: list,
    stop_event,
):
    """Worker thread: opens connection, runs queries in loop until duration expires."""
    query_tag = f"IT_BENCH_{warehouse}_{concurrency_level}_{run_id}"
    conn = None

    try:
        conn = create_connection(config, warehouse, query_tag)
        cursor = conn.cursor()

        start_time = time.time()

        while time.time() - start_time < duration_seconds and not stop_event.is_set():
            query_def = pick_query(config)
            query_type, sql = build_query(query_def, config, warehouse_type)

            query_start = datetime.datetime.now()
            t0 = time.perf_counter()

            try:
                cursor.execute(sql)
                _ = cursor.fetchall()
                t1 = time.perf_counter()
                latency_ms = (t1 - t0) * 1000
                query_end = datetime.datetime.now()

                results.append(QueryResult(
                    run_id=run_id,
                    run_timestamp=run_timestamp,
                    warehouse_name=warehouse,
                    warehouse_type=warehouse_type,
                    concurrency_level=concurrency_level,
                    query_type=query_type,
                    thread_id=thread_id,
                    query_start=query_start.isoformat(),
                    query_end=query_end.isoformat(),
                    latency_ms=latency_ms,
                    success=True,
                    benchmark_mode="POINT_LOOKUPS_ONLY" if config.point_lookups_only else "MIXED",
                ))
            except Exception as e:
                t1 = time.perf_counter()
                latency_ms = (t1 - t0) * 1000
                query_end = datetime.datetime.now()

                results.append(QueryResult(
                    run_id=run_id,
                    run_timestamp=run_timestamp,
                    warehouse_name=warehouse,
                    warehouse_type=warehouse_type,
                    concurrency_level=concurrency_level,
                    query_type=query_type,
                    thread_id=thread_id,
                    query_start=query_start.isoformat(),
                    query_end=query_end.isoformat(),
                    latency_ms=latency_ms,
                    success=False,
                    error_message=str(e)[:500],
                    benchmark_mode="POINT_LOOKUPS_ONLY" if config.point_lookups_only else "MIXED",
                ))

        cursor.close()
    except Exception as e:
        logging.error(f"Thread {thread_id} connection error: {e}")
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Benchmark Orchestrator
# ---------------------------------------------------------------------------

def run_warmup(config: BenchmarkConfig, warehouse: str, warehouse_type: str):
    """Run warmup queries to prime the warehouse."""
    logging.info(f"  Warming up {warehouse} with {config.warmup_queries} queries...")
    query_tag = f"IT_BENCH_WARMUP_{warehouse}"
    conn = create_connection(config, warehouse, query_tag)
    cursor = conn.cursor()

    for i in range(config.warmup_queries):
        query_def = pick_query(config)
        _, sql = build_query(query_def, config, warehouse_type)
        try:
            cursor.execute(sql)
            cursor.fetchall()
        except Exception as e:
            logging.warning(f"  Warmup query {i} failed: {e}")

    cursor.close()
    conn.close()
    logging.info(f"  Warmup complete for {warehouse}")


def run_concurrency_level(
    config: BenchmarkConfig,
    warehouse: str,
    warehouse_type: str,
    concurrency: int,
    run_id: str,
) -> list:
    """Run benchmark at a specific concurrency level."""
    run_timestamp = datetime.datetime.now().isoformat()
    results = []
    stop_event = threading.Event()

    logging.info(
        f"  Running {concurrency} concurrent threads against {warehouse} "
        f"for {config.duration_seconds}s..."
    )

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = []
        for thread_id in range(concurrency):
            future = executor.submit(
                worker_thread,
                thread_id=thread_id,
                config=config,
                warehouse=warehouse,
                warehouse_type=warehouse_type,
                concurrency_level=concurrency,
                run_id=run_id,
                run_timestamp=run_timestamp,
                duration_seconds=config.duration_seconds,
                results=results,
                stop_event=stop_event,
            )
            futures.append(future)

        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                logging.error(f"  Thread raised: {e}")

    return results


def print_summary(results: list, warehouse: str, concurrency: int):
    """Print quick summary stats for a run."""
    if not results:
        logging.warning(f"  No results for {warehouse} @ {concurrency}")
        return

    latencies = [r.latency_ms for r in results if r.success]
    if not latencies:
        logging.warning(f"  All queries failed for {warehouse} @ {concurrency}")
        return

    latencies.sort()
    n = len(latencies)
    p50 = latencies[int(n * 0.50)]
    p95 = latencies[int(n * 0.95)]
    p99 = latencies[int(n * 0.99)]
    errors = sum(1 for r in results if not r.success)

    logging.info(
        f"  {warehouse} @ {concurrency} threads: "
        f"queries={n}, p50={p50:.0f}ms, p95={p95:.0f}ms, p99={p99:.0f}ms, "
        f"errors={errors}"
    )


# ---------------------------------------------------------------------------
# Results Persistence
# ---------------------------------------------------------------------------

def save_results_csv(all_results: list, filepath: str):
    """Save all results to CSV."""
    if not all_results:
        return

    fieldnames = [
        "run_id", "run_timestamp", "warehouse_name", "warehouse_type",
        "concurrency_level", "query_type", "thread_id", "query_start",
        "query_end", "latency_ms", "success", "error_message", "benchmark_mode",
    ]

    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in all_results:
            writer.writerow({
                "run_id": r.run_id,
                "run_timestamp": r.run_timestamp,
                "warehouse_name": r.warehouse_name,
                "warehouse_type": r.warehouse_type,
                "concurrency_level": r.concurrency_level,
                "query_type": r.query_type,
                "thread_id": r.thread_id,
                "query_start": r.query_start,
                "query_end": r.query_end,
                "latency_ms": r.latency_ms,
                "success": r.success,
                "error_message": r.error_message,
                "benchmark_mode": r.benchmark_mode,
            })

    logging.info(f"Results saved to {filepath} ({len(all_results)} records)")


def upload_results_to_snowflake(all_results: list, config: BenchmarkConfig):
    """Upload results to Snowflake BENCHMARK_RESULTS table."""
    try:
        import snowflake.connector
        from snowflake.connector.pandas_tools import write_pandas

        credential = get_auth_credential(config)
        conn = snowflake.connector.connect(
            account=config.account_url.replace(".snowflakecomputing.com", ""),
            user=config.username,
            password=credential,
            database=config.database,
            schema=config.schema,
            role=config.role,
            warehouse=config.standard_warehouse,
        )

        # Auto-create results table if it doesn't exist
        conn.cursor().execute(f"""
            CREATE TABLE IF NOT EXISTS {config.results_table} (
                RUN_ID VARCHAR(50),
                RUN_TIMESTAMP VARCHAR(50),
                WAREHOUSE_NAME VARCHAR(100),
                WAREHOUSE_TYPE VARCHAR(20),
                CONCURRENCY_LEVEL INTEGER,
                QUERY_TYPE VARCHAR(50),
                THREAD_ID INTEGER,
                QUERY_START VARCHAR(50),
                QUERY_END VARCHAR(50),
                LATENCY_MS FLOAT,
                SUCCESS BOOLEAN,
                ERROR_MESSAGE VARCHAR(1000),
                BENCHMARK_MODE VARCHAR(30)
            )
        """)

        df = pd.DataFrame([{
            "RUN_ID": r.run_id,
            "RUN_TIMESTAMP": r.run_timestamp,
            "WAREHOUSE_NAME": r.warehouse_name,
            "WAREHOUSE_TYPE": r.warehouse_type,
            "CONCURRENCY_LEVEL": r.concurrency_level,
            "QUERY_TYPE": r.query_type,
            "THREAD_ID": r.thread_id,
            "QUERY_START": r.query_start,
            "QUERY_END": r.query_end,
            "LATENCY_MS": r.latency_ms,
            "SUCCESS": r.success,
            "ERROR_MESSAGE": r.error_message,
            "BENCHMARK_MODE": r.benchmark_mode,
        } for r in all_results])

        write_pandas(
            conn, df,
            table_name=config.results_table,
            database=config.database,
            schema=config.schema,
            auto_create_table=False,
            overwrite=False,
            quote_identifiers=False,
        )

        conn.close()
        logging.info(f"Uploaded {len(all_results)} results to {config.results_table}")

    except Exception as e:
        logging.error(f"Failed to upload results to Snowflake: {e}")
        logging.info("Results are still saved locally in CSV.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Interactive Tables Benchmark — concurrent load test harness"
    )
    parser.add_argument(
        "--config", type=str, default="config.yaml",
        help="Path to config YAML file (default: config.yaml)"
    )
    parser.add_argument(
        "--concurrency", type=str, default=None,
        help="Override concurrency levels (comma-separated, e.g. 10,25,50)"
    )
    parser.add_argument(
        "--duration", type=int, default=None,
        help="Override duration in seconds per concurrency level"
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Override output CSV file path"
    )
    parser.add_argument(
        "--no-upload", action="store_true",
        help="Skip uploading results to Snowflake"
    )
    parser.add_argument(
        "--standard-only", action="store_true",
        help="Only run against standard warehouse"
    )
    parser.add_argument(
        "--interactive-only", action="store_true",
        help="Only run against interactive warehouse"
    )
    parser.add_argument(
        "--point-lookups-only", action="store_true",
        help="Only run point lookup queries (no aggregations)"
    )
    parser.add_argument(
        "--mixed-workload", action="store_true",
        help="Include aggregation queries (overrides config.yaml point_lookups_only=true)"
    )
    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # Load config from YAML
    config_path = args.config
    if not os.path.exists(config_path):
        logging.error(f"Config file not found: {config_path}")
        logging.error("Copy config.yaml.example to config.yaml and edit it for your account.")
        sys.exit(1)

    config = BenchmarkConfig.from_yaml(config_path)
    config.apply_env_overrides()

    # CLI overrides
    if args.concurrency:
        config.concurrency_levels = [int(x) for x in args.concurrency.split(",")]
    if args.duration:
        config.duration_seconds = args.duration
    if args.output:
        config.results_csv = args.output
    if args.no_upload:
        config.upload_to_snowflake = False
    if args.point_lookups_only:
        config.point_lookups_only = True
    if args.mixed_workload:
        config.point_lookups_only = False

    # Validate
    if not config.account_url:
        logging.error("SNOWFLAKE_ACCOUNT_URL env var or config.yaml connection.account_url required")
        sys.exit(1)
    if not config.username:
        logging.error("SNOWFLAKE_USER env var or config.yaml connection.username required")
        sys.exit(1)
    if not config.pat_token and not config.password:
        logging.error(
            "Authentication required. Set one of:\n"
            "  export SNOWFLAKE_PAT_TOKEN='<token>'   (recommended, bypasses MFA)\n"
            "  export SNOWFLAKE_PASSWORD='<password>'\n\n"
            "To generate a PAT token:\n"
            "  ALTER USER <user> ADD PAT benchmark_token DAYS_TO_EXPIRY = 30;\n"
            "  -- Copy the token_secret from output"
        )
        sys.exit(1)
    if config.pat_token:
        logging.info("  Auth: Using PAT token (MFA bypassed)")
    else:
        logging.info("  Auth: Using password (MFA may be triggered)")
    if not config.jdbc_jar_path:
        logging.error("SNOWFLAKE_JDBC_JAR env var required (path to snowflake-jdbc-*.jar)")
        sys.exit(1)
    if not os.path.exists(config.jdbc_jar_path):
        logging.error(f"JDBC jar not found: {config.jdbc_jar_path}")
        sys.exit(1)
    if not config.queries:
        logging.error("No queries defined in config.yaml. Add at least one query.")
        sys.exit(1)

    # Start JVM
    if not jpype.isJVMStarted():
        jpype.startJVM(
            "--add-opens=java.base/java.nio=ALL-UNNAMED",
            classpath=[config.jdbc_jar_path],
        )

    # Run benchmark
    run_id = str(uuid.uuid4())[:8]
    all_results = []

    query_mode = "POINT LOOKUPS ONLY" if config.point_lookups_only else "MIXED"
    logging.info("=" * 70)
    logging.info("INTERACTIVE TABLES BENCHMARK")
    logging.info(f"  Run ID:        {run_id}")
    logging.info(f"  Account:       {config.account_url}")
    logging.info(f"  Database:      {config.database}.{config.schema}")
    logging.info(f"  Concurrency:   {config.concurrency_levels}")
    logging.info(f"  Duration:      {config.duration_seconds}s per level")
    logging.info(f"  Standard WH:   {config.standard_warehouse}")
    logging.info(f"  Interactive WH: {config.interactive_warehouse}")
    logging.info(f"  Query Mode:    {query_mode}")
    logging.info(f"  Queries:       {[q['name'] for q in config.queries]}")
    logging.info("=" * 70)

    # Define which warehouses to test
    warehouses = []
    if not args.interactive_only:
        warehouses.append((config.standard_warehouse, "STANDARD"))
    if not args.standard_only:
        warehouses.append((config.interactive_warehouse, "INTERACTIVE"))

    for concurrency in config.concurrency_levels:
        logging.info(f"\n{'='*70}")
        logging.info(f"CONCURRENCY LEVEL: {concurrency}")
        logging.info(f"{'='*70}")

        for warehouse, wh_type in warehouses:
            run_warmup(config, warehouse, wh_type)

            results = run_concurrency_level(
                config, warehouse, wh_type, concurrency, run_id
            )
            all_results.extend(results)
            print_summary(results, warehouse, concurrency)

            if len(warehouses) > 1:
                time.sleep(5)

        logging.info(f"  Pausing 10s before next concurrency level...")
        time.sleep(10)

    # Save results
    logging.info(f"\n{'='*70}")
    logging.info("BENCHMARK COMPLETE")
    logging.info(f"{'='*70}")
    logging.info(f"  Total queries executed: {len(all_results)}")

    save_results_csv(all_results, config.results_csv)

    if config.upload_to_snowflake:
        upload_results_to_snowflake(all_results, config)

    # Final summary
    logging.info("\n  SUMMARY:")
    logging.info(f"  {'Warehouse':<25} {'Conc':<8} {'Queries':<10} {'p50 ms':<10} {'p95 ms':<10} {'Errors':<8}")
    logging.info(f"  {'-'*71}")

    for concurrency in config.concurrency_levels:
        for warehouse, wh_type in warehouses:
            subset = [r for r in all_results
                      if r.concurrency_level == concurrency
                      and r.warehouse_name == warehouse]
            success = [r for r in subset if r.success]
            errors = len(subset) - len(success)
            if success:
                lats = sorted([r.latency_ms for r in success])
                n = len(lats)
                logging.info(
                    f"  {warehouse:<25} {concurrency:<8} {n:<10} "
                    f"{lats[int(n*0.5)]:<10.0f} "
                    f"{lats[int(n*0.95)]:<10.0f} "
                    f"{errors:<8}"
                )


if __name__ == "__main__":
    main()
    # Force exit — JPype JVM daemon threads can prevent clean shutdown
    os._exit(0)

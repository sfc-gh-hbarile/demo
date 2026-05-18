#!/usr/bin/env python3
"""
Interactive Tables Benchmark Dashboard
========================================
Streamlit app that visualizes benchmark results from BENCHMARK_RESULTS table
or a local CSV file. Shows latency comparison, throughput, and cost analysis.

Usage:
    streamlit run benchmark_dashboard.py
    streamlit run benchmark_dashboard.py -- --csv benchmark_results.csv
"""

import argparse
import os
from datetime import datetime

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# Page Config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Interactive Tables Benchmark",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Data Loading
# ---------------------------------------------------------------------------

def _is_running_in_sis() -> bool:
    """Detect if running inside Streamlit-in-Snowflake."""
    try:
        from snowflake.snowpark.context import get_active_session
        get_active_session()
        return True
    except Exception:
        return False


@st.cache_data(ttl=60)
def load_from_snowflake() -> pd.DataFrame:
    """Load benchmark results from Snowflake.

    Automatically detects whether running in SiS (uses active session)
    or locally (uses env vars / PAT token for connection).
    """
    if _is_running_in_sis():
        # Running inside Streamlit-in-Snowflake — use the session connection
        from snowflake.snowpark.context import get_active_session
        session = get_active_session()
        df = session.sql("""
            SELECT *
            FROM BENCHMARK_RESULTS
            ORDER BY run_timestamp DESC, concurrency_level, warehouse_type
        """).to_pandas()
    else:
        # Running locally — connect with PAT token or password
        import snowflake.connector
        credential = os.environ.get("SNOWFLAKE_PAT_TOKEN") or os.environ.get("SNOWFLAKE_PASSWORD", "")
        if not credential:
            raise ValueError(
                "Set SNOWFLAKE_PAT_TOKEN or SNOWFLAKE_PASSWORD to connect, "
                "or use a local CSV file instead."
            )
        conn = snowflake.connector.connect(
            account=os.environ.get("SNOWFLAKE_ACCOUNT", ""),
            user=os.environ.get("SNOWFLAKE_USER", ""),
            password=credential,
            database=os.environ.get("SNOWFLAKE_DATABASE", ""),
            schema=os.environ.get("SNOWFLAKE_SCHEMA", ""),
            role=os.environ.get("SNOWFLAKE_ROLE", "SYSADMIN"),
            warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", ""),
        )
        df = pd.read_sql("""
            SELECT *
            FROM BENCHMARK_RESULTS
            ORDER BY run_timestamp DESC, concurrency_level, warehouse_type
        """, conn)
        conn.close()

    # Normalize column names to lowercase
    df.columns = [c.lower() for c in df.columns]
    return df


@st.cache_data
def load_from_csv(path: str) -> pd.DataFrame:
    """Load benchmark results from local CSV."""
    df = pd.read_csv(path)
    df.columns = [c.lower() for c in df.columns]
    return df


def load_data(csv_path: str = None) -> pd.DataFrame:
    """Load data from CSV or Snowflake."""
    if csv_path and os.path.exists(csv_path):
        df = load_from_csv(csv_path)
    else:
        df = load_from_snowflake()

    # Normalize success column to boolean
    if "success" in df.columns:
        df["success"] = df["success"].map(
            lambda x: x if isinstance(x, bool) else str(x).lower() in ("true", "1", "yes")
        )

    return df


# ---------------------------------------------------------------------------
# Statistics Helpers
# ---------------------------------------------------------------------------

def compute_percentiles(df: pd.DataFrame) -> pd.DataFrame:
    """Compute p50/p95/p99 per warehouse_type and concurrency_level."""
    stats = df.groupby(["warehouse_type", "concurrency_level"]).agg(
        query_count=("latency_ms", "count"),
        p50=("latency_ms", lambda x: np.percentile(x, 50)),
        p95=("latency_ms", lambda x: np.percentile(x, 95)),
        p99=("latency_ms", lambda x: np.percentile(x, 99)),
        avg=("latency_ms", "mean"),
        min_latency=("latency_ms", "min"),
        max_latency=("latency_ms", "max"),
    ).reset_index()
    return stats


def compute_throughput(df: pd.DataFrame, duration_seconds: int = 120) -> pd.DataFrame:
    """Compute QPS per warehouse_type and concurrency_level."""
    throughput = df.groupby(["warehouse_type", "concurrency_level"]).agg(
        total_queries=("latency_ms", "count"),
    ).reset_index()
    throughput["qps"] = throughput["total_queries"] / duration_seconds
    return throughput


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

st.sidebar.title("Benchmark Controls")

# Data source
csv_default = os.path.join(os.path.dirname(__file__), "benchmark_results.csv")
data_source = st.sidebar.radio(
    "Data Source",
    ["Snowflake (BENCHMARK_RESULTS)", "Local CSV"],
    index=0 if not os.path.exists(csv_default) else 1,
)

csv_path = None
if data_source == "Local CSV":
    csv_path = st.sidebar.text_input("CSV Path", value=csv_default)

# Load data
try:
    df = load_data(csv_path)
except Exception as e:
    st.error(f"Failed to load data: {e}")
    st.info("Set SNOWFLAKE_PAT_TOKEN env var, or switch to 'Local CSV' in the sidebar.")
    st.stop()

if df.empty:
    st.warning("No benchmark results found. Run benchmark_driver.py first.")
    st.stop()

# Run selector
available_runs = sorted(df["run_id"].unique(), reverse=True)
selected_run = st.sidebar.selectbox("Benchmark Run", available_runs)
df = df[df["run_id"] == selected_run]

# Benchmark mode indicator
if "benchmark_mode" in df.columns:
    run_mode = df["benchmark_mode"].iloc[0] if not df.empty else "MIXED"
    st.sidebar.info(f"Mode: {run_mode}")

# Query type filter
query_types = ["All"] + sorted(df["query_type"].unique().tolist())
selected_query_type = st.sidebar.selectbox("Query Type", query_types)
if selected_query_type != "All":
    df = df[df["query_type"] == selected_query_type]

# Split into successful and failed queries
df_all = df.copy()
df_success = df[df["success"] == True].copy()
df_failed = df[df["success"] == False].copy()

# Duration (for QPS calc)
duration_seconds = st.sidebar.number_input(
    "Run Duration (sec)", value=120, min_value=10, max_value=600
)

st.sidebar.divider()

# Cost parameters
st.sidebar.subheader("Cost Parameters")
credit_price = st.sidebar.slider("Credit Price ($/credit)", 1.0, 6.0, 2.50, 0.25)
daily_queries = st.sidebar.number_input(
    "Daily Query Volume", value=500_000, min_value=1000, step=10000
)
hours_per_day = st.sidebar.slider("Operating Hours/Day", 1, 24, 16)

# ---------------------------------------------------------------------------
# Page 1: Latency Comparison
# ---------------------------------------------------------------------------

st.title("Interactive Tables vs Standard Warehouse Benchmark")
st.caption(f"Run: {selected_run} | Query Type: {selected_query_type} | "
           f"Total: {len(df_all):,} queries ({len(df_success):,} success, {len(df_failed):,} failed)")

stats = compute_percentiles(df_success)

# Top-level metrics
col1, col2, col3, col4 = st.columns(4)

std_stats = stats[stats["warehouse_type"] == "STANDARD"]
int_stats = stats[stats["warehouse_type"] == "INTERACTIVE"]

if not std_stats.empty and not int_stats.empty:
    max_conc = stats["concurrency_level"].max()
    std_p50_max = std_stats[std_stats["concurrency_level"] == max_conc]["p50"].values
    int_p50_max = int_stats[int_stats["concurrency_level"] == max_conc]["p50"].values

    if len(std_p50_max) > 0 and len(int_p50_max) > 0:
        speedup = std_p50_max[0] / max(int_p50_max[0], 1)
        col1.metric("Speedup @ Max Concurrency", f"{speedup:.1f}x")
    col2.metric("Max Concurrency Tested", f"{max_conc}")
    col3.metric("Total Queries", f"{len(df_all):,}")
    col4.metric(
        "Std p95 @ Max Conc.",
        f"{std_stats[std_stats['concurrency_level'] == max_conc]['p95'].values[0]:.0f} ms"
        if not std_stats[std_stats["concurrency_level"] == max_conc].empty else "N/A"
    )

st.divider()

# Latency vs Concurrency Chart
tab1, tab2, tab3, tab4, tab5 = st.tabs(["Latency", "Throughput", "Cost Analysis", "Failures & Timeouts", "Raw Data"])

with tab1:
    st.subheader("Latency vs Concurrency")

    # Melt for charting
    chart_data = stats.melt(
        id_vars=["warehouse_type", "concurrency_level"],
        value_vars=["p50", "p95", "p99"],
        var_name="percentile",
        value_name="latency_ms",
    )

    # p50 comparison (primary chart)
    p50_data = chart_data[chart_data["percentile"] == "p50"]

    # Use bar chart when only 1 concurrency level, line chart otherwise
    n_levels = len(stats["concurrency_level"].unique())
    if n_levels == 1:
        p50_chart = alt.Chart(p50_data).mark_bar(size=60).encode(
            x=alt.X("warehouse_type:N", title="Warehouse Type"),
            y=alt.Y("latency_ms:Q", title="p50 Latency (ms)"),
            color=alt.Color("warehouse_type:N", scale=alt.Scale(
                domain=["STANDARD", "INTERACTIVE"],
                range=["#e74c3c", "#2ecc71"]
            ), title="Warehouse Type"),
        ).properties(
            width=700, height=400,
            title="p50 Latency: Standard (red) vs Interactive (green)"
        )
    else:
        p50_chart = alt.Chart(p50_data).mark_line(point=alt.OverlayMarkDef(size=100), strokeWidth=3).encode(
            x=alt.X("concurrency_level:Q", title="Concurrent Threads", scale=alt.Scale(domain=[0, max(stats["concurrency_level"]) + 5])),
            y=alt.Y("latency_ms:Q", title="p50 Latency (ms)"),
            color=alt.Color("warehouse_type:N", scale=alt.Scale(
                domain=["STANDARD", "INTERACTIVE"],
                range=["#e74c3c", "#2ecc71"]
            ), title="Warehouse Type"),
            strokeDash=alt.StrokeDash("warehouse_type:N"),
        ).properties(
            width=700, height=400,
            title="p50 Latency: Standard (red) vs Interactive (green)"
        )
    st.altair_chart(p50_chart, use_container_width=True)

    # All percentiles chart
    st.subheader("Latency Distribution by Percentile")
    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown("**Standard Warehouse**")
        std_chart_data = chart_data[chart_data["warehouse_type"] == "STANDARD"]
        std_chart = alt.Chart(std_chart_data).mark_line(point=True).encode(
            x=alt.X("concurrency_level:Q", title="Concurrent Threads"),
            y=alt.Y("latency_ms:Q", title="Latency (ms)"),
            color=alt.Color("percentile:N", scale=alt.Scale(
                domain=["p50", "p95", "p99"],
                range=["#3498db", "#f39c12", "#e74c3c"]
            )),
        ).properties(width=350, height=300)
        st.altair_chart(std_chart, use_container_width=True)

    with col_right:
        st.markdown("**Interactive Warehouse**")
        int_chart_data = chart_data[chart_data["warehouse_type"] == "INTERACTIVE"]
        int_chart = alt.Chart(int_chart_data).mark_line(point=True).encode(
            x=alt.X("concurrency_level:Q", title="Concurrent Threads"),
            y=alt.Y("latency_ms:Q", title="Latency (ms)"),
            color=alt.Color("percentile:N", scale=alt.Scale(
                domain=["p50", "p95", "p99"],
                range=["#3498db", "#f39c12", "#e74c3c"]
            )),
        ).properties(width=350, height=300)
        st.altair_chart(int_chart, use_container_width=True)

    # Speedup table
    st.subheader("Speedup Ratio by Concurrency Level")
    if not std_stats.empty and not int_stats.empty:
        merged = std_stats.merge(
            int_stats, on="concurrency_level", suffixes=("_std", "_int")
        )
        merged["speedup_p50"] = merged["p50_std"] / merged["p50_int"].clip(lower=1)
        merged["speedup_p95"] = merged["p95_std"] / merged["p95_int"].clip(lower=1)
        merged["speedup_p99"] = merged["p99_std"] / merged["p99_int"].clip(lower=1)

        display_df = merged[[
            "concurrency_level", "p50_std", "p50_int", "speedup_p50",
            "p95_std", "p95_int", "speedup_p95"
        ]].rename(columns={
            "concurrency_level": "Concurrency",
            "p50_std": "Std p50 (ms)",
            "p50_int": "Interactive p50 (ms)",
            "speedup_p50": "Speedup (p50)",
            "p95_std": "Std p95 (ms)",
            "p95_int": "Interactive p95 (ms)",
            "speedup_p95": "Speedup (p95)",
        })
        st.dataframe(
            display_df.style.format({
                "Std p50 (ms)": "{:.0f}",
                "Interactive p50 (ms)": "{:.0f}",
                "Speedup (p50)": "{:.1f}x",
                "Std p95 (ms)": "{:.0f}",
                "Interactive p95 (ms)": "{:.0f}",
                "Speedup (p95)": "{:.1f}x",
            }),
            use_container_width=True,
        )

# ---------------------------------------------------------------------------
# Page 2: Throughput
# ---------------------------------------------------------------------------

with tab2:
    st.subheader("Throughput: Queries Completed per Run")

    throughput = compute_throughput(df_success, duration_seconds)

    # QPS bar chart
    qps_chart = alt.Chart(throughput).mark_bar().encode(
        x=alt.X("concurrency_level:O", title="Concurrent Threads"),
        y=alt.Y("qps:Q", title="Queries per Second (QPS)"),
        color=alt.Color("warehouse_type:N", scale=alt.Scale(
            domain=["STANDARD", "INTERACTIVE"],
            range=["#e74c3c", "#2ecc71"]
        )),
        xOffset="warehouse_type:N",
    ).properties(width=700, height=400, title="Sustained QPS by Concurrency Level")
    st.altair_chart(qps_chart, use_container_width=True)

    # Total queries chart
    total_chart = alt.Chart(throughput).mark_bar().encode(
        x=alt.X("concurrency_level:O", title="Concurrent Threads"),
        y=alt.Y("total_queries:Q", title="Total Queries in Run"),
        color=alt.Color("warehouse_type:N", scale=alt.Scale(
            domain=["STANDARD", "INTERACTIVE"],
            range=["#e74c3c", "#2ecc71"]
        )),
        xOffset="warehouse_type:N",
    ).properties(width=700, height=300, title="Total Queries Completed (2 min run)")
    st.altair_chart(total_chart, use_container_width=True)

    # Throughput table
    st.subheader("Throughput Summary")
    st.dataframe(
        throughput.style.format({"qps": "{:.1f}", "total_queries": "{:,.0f}"}),
        use_container_width=True,
    )

# ---------------------------------------------------------------------------
# Page 3: Cost Analysis
# ---------------------------------------------------------------------------

with tab3:
    st.subheader("Cost & Efficiency: Interactive vs Standard")

    st.markdown("""
    Based on **actual benchmark telemetry**: same time window, same warehouse size —
    how much work gets done, and what does each query cost?
    """)

    # -----------------------------------------------------------------------
    # Compute per-run efficiency metrics from real data
    # -----------------------------------------------------------------------

    # Group by warehouse_type and concurrency to get real counts and latencies
    efficiency = df_success.groupby(["warehouse_type", "concurrency_level"]).agg(
        total_queries=("latency_ms", "count"),
        avg_latency_ms=("latency_ms", "mean"),
        p50_latency_ms=("latency_ms", "median"),
        p95_latency_ms=("latency_ms", lambda x: np.percentile(x, 95)),
        total_time_ms=("latency_ms", "sum"),  # total query-milliseconds consumed
    ).reset_index()

    # XS warehouse = 1 credit/hour. During each benchmark run, the warehouse is active
    # for the full duration. Cost = (duration_seconds / 3600) * 1 credit * credit_price
    run_duration_hours = duration_seconds / 3600.0
    credits_per_run = run_duration_hours * 1.0  # XS = 1 credit/hr

    efficiency["credits_consumed"] = credits_per_run
    efficiency["cost_per_run"] = credits_per_run * credit_price
    efficiency["cost_per_query"] = efficiency["cost_per_run"] / efficiency["total_queries"]
    efficiency["cost_per_1000_queries"] = efficiency["cost_per_query"] * 1000
    efficiency["qps"] = efficiency["total_queries"] / duration_seconds

    # -----------------------------------------------------------------------
    # Top-level insight metrics at max concurrency
    # -----------------------------------------------------------------------
    max_conc = efficiency["concurrency_level"].max()
    std_eff = efficiency[(efficiency["warehouse_type"] == "STANDARD") & (efficiency["concurrency_level"] == max_conc)]
    int_eff = efficiency[(efficiency["warehouse_type"] == "INTERACTIVE") & (efficiency["concurrency_level"] == max_conc)]

    st.subheader(f"At Peak Concurrency ({max_conc} threads)")

    if not std_eff.empty and not int_eff.empty:
        std_queries = std_eff["total_queries"].values[0]
        int_queries = int_eff["total_queries"].values[0]
        std_cost_per_q = std_eff["cost_per_1000_queries"].values[0]
        int_cost_per_q = int_eff["cost_per_1000_queries"].values[0]
        std_qps = std_eff["qps"].values[0]
        int_qps = int_eff["qps"].values[0]
        std_p50 = std_eff["p50_latency_ms"].values[0]
        int_p50 = int_eff["p50_latency_ms"].values[0]

        col1, col2, col3, col4 = st.columns(4)
        col1.metric(
            "Queries Completed",
            f"{int_queries:,.0f} vs {std_queries:,.0f}",
            delta=f"Interactive did {int_queries - std_queries:,.0f} more",
        )
        col2.metric(
            "Cost per 1000 Queries",
            f"${int_cost_per_q:.4f} vs ${std_cost_per_q:.4f}",
            delta=f"{std_cost_per_q / max(int_cost_per_q, 0.0001):.1f}x cheaper on Interactive",
        )
        col3.metric(
            "Throughput (QPS)",
            f"{int_qps:.1f} vs {std_qps:.1f}",
            delta=f"{int_qps / max(std_qps, 0.1):.1f}x more throughput",
        )
        col4.metric(
            "p50 Latency",
            f"{int_p50:.0f}ms vs {std_p50:.0f}ms",
            delta=f"{std_p50 / max(int_p50, 1):.1f}x faster response",
        )

    st.divider()

    # -----------------------------------------------------------------------
    # Cost per Query across concurrency levels
    # -----------------------------------------------------------------------
    st.subheader("Cost per 1000 Queries (by concurrency)")
    st.caption(
        f"Both warehouses are XS (1 credit/hr). Each run = {duration_seconds}s. "
        f"Cost per query = (credits consumed during run) ÷ (queries completed). "
        f"Interactive completes more queries in the same billing window → lower cost per query."
    )

    cost_chart = alt.Chart(efficiency).mark_bar().encode(
        x=alt.X("concurrency_level:O", title="Concurrent Threads"),
        y=alt.Y("cost_per_1000_queries:Q", title="Cost per 1000 Queries ($)"),
        color=alt.Color("warehouse_type:N", scale=alt.Scale(
            domain=["STANDARD", "INTERACTIVE"],
            range=["#e74c3c", "#2ecc71"]
        )),
        xOffset="warehouse_type:N",
    ).properties(width=700, height=350, title="Cost per 1000 Queries — Lower is Better")
    st.altair_chart(cost_chart, use_container_width=True)

    # -----------------------------------------------------------------------
    # Queries Completed (same time window)
    # -----------------------------------------------------------------------
    st.subheader("Work Done in Same Time Window")
    st.caption(
        f"Both warehouses ran for exactly {duration_seconds}s at each concurrency level. "
        "Interactive handles more queries because there's no queuing — "
        "queries execute immediately from memory."
    )

    work_chart = alt.Chart(efficiency).mark_bar().encode(
        x=alt.X("concurrency_level:O", title="Concurrent Threads"),
        y=alt.Y("total_queries:Q", title=f"Queries Completed in {duration_seconds}s"),
        color=alt.Color("warehouse_type:N", scale=alt.Scale(
            domain=["STANDARD", "INTERACTIVE"],
            range=["#e74c3c", "#2ecc71"]
        )),
        xOffset="warehouse_type:N",
    ).properties(width=700, height=350, title="Total Queries Served (same time, same cost)")
    st.altair_chart(work_chart, use_container_width=True)

    # -----------------------------------------------------------------------
    # Time to serve a fixed workload
    # -----------------------------------------------------------------------
    st.subheader("Time to Serve Your Daily Workload")
    st.caption(
        f"How many hours would each warehouse (XS) need to serve {daily_queries:,} queries/day "
        f"at the measured throughput? If hours > 24, a single XS cannot keep up — "
        f"you would need to scale up (S, M) or add multi-cluster warehouses."
    )

    efficiency["hours_for_daily_volume"] = (daily_queries / efficiency["qps"]) / 3600.0
    efficiency["daily_credits"] = efficiency["hours_for_daily_volume"] * 1.0  # XS = 1 credit/hr
    efficiency["daily_cost"] = efficiency["daily_credits"] * credit_price

    # Add a 24-hour reference line to the chart
    time_chart = alt.Chart(efficiency).mark_bar().encode(
        x=alt.X("concurrency_level:O", title="Concurrent Threads"),
        y=alt.Y("hours_for_daily_volume:Q", title="Hours to Serve Daily Volume"),
        color=alt.Color("warehouse_type:N", scale=alt.Scale(
            domain=["STANDARD", "INTERACTIVE"],
            range=["#e74c3c", "#2ecc71"]
        )),
        xOffset="warehouse_type:N",
    ).properties(width=700, height=350,
                 title=f"Hours Required to Serve {daily_queries:,} Queries/Day")

    # 24-hour threshold line
    rule = alt.Chart(pd.DataFrame({"y": [24]})).mark_rule(
        color="#ff9800", strokeDash=[5, 5], strokeWidth=2
    ).encode(y="y:Q")

    rule_label = alt.Chart(pd.DataFrame({"y": [24], "label": ["24h (1 day)"]})).mark_text(
        align="right", dx=-5, dy=-8, color="#ff9800", fontWeight="bold"
    ).encode(y="y:Q", text="label:N")

    st.altair_chart(time_chart + rule + rule_label, use_container_width=True)

    # Warning if any warehouse exceeds 24h
    over_24 = efficiency[efficiency["hours_for_daily_volume"] > 24]
    if not over_24.empty:
        st.warning(
            f"**Standard warehouse exceeds 24 hours** at some concurrency levels. "
            f"This means a single XS warehouse physically cannot serve {daily_queries:,} "
            f"queries/day — the customer would need to scale up to S/M or use "
            f"multi-cluster warehousing. Interactive Tables serve the same volume "
            f"in a fraction of the time with no scaling required."
        )

    # -----------------------------------------------------------------------
    # Summary Table
    # -----------------------------------------------------------------------
    st.divider()
    st.subheader("Efficiency Summary")

    display_eff = efficiency[[
        "warehouse_type", "concurrency_level", "total_queries", "qps",
        "avg_latency_ms", "cost_per_1000_queries", "hours_for_daily_volume", "daily_cost"
    ]].rename(columns={
        "warehouse_type": "Warehouse",
        "concurrency_level": "Concurrency",
        "total_queries": "Queries Done",
        "qps": "QPS",
        "avg_latency_ms": "Avg Latency (ms)",
        "cost_per_1000_queries": "$/1000 Queries",
        "hours_for_daily_volume": f"Hrs for {daily_queries:,}/day",
        "daily_cost": "Daily Cost ($)",
    })
    st.dataframe(
        display_eff.style.format({
            "QPS": "{:.1f}",
            "Avg Latency (ms)": "{:.0f}",
            "$/1000 Queries": "${:.5f}",
            f"Hrs for {daily_queries:,}/day": "{:.1f}",
            "Daily Cost ($)": "${:.2f}",
        }),
        use_container_width=True,
    )

    with st.expander("How costs are calculated"):
        st.markdown(f"""
        **Both warehouses are XS = 1 credit/hour when running.**

        The key difference is **how much work gets done per credit**:

        - During the benchmark, each warehouse ran for exactly **{duration_seconds} seconds**
        - That's **{credits_per_run:.4f} credits** consumed (1 credit/hr × {duration_seconds}s ÷ 3600)
        - **Cost per query** = credits consumed ÷ queries completed
        - Interactive completes more queries in the same time → lower cost per query

        **For daily cost projection:**
        - We use the measured **QPS** (queries per second) at each concurrency level
        - Hours needed = daily_queries ÷ QPS ÷ 3600
        - Daily credits = hours × 1 credit/hr
        - Daily cost = credits × ${credit_price:.2f}/credit

        **Why Interactive is more efficient:**
        - No queuing (standard XS queues beyond 8 concurrent queries)
        - Sub-second response from memory vs cold-start + scan on standard
        - More queries completed per unit of compute time
        """)

# ---------------------------------------------------------------------------
# Page 4: Failures & Timeouts
# ---------------------------------------------------------------------------

with tab4:
    st.subheader("Query Failures & Timeouts")

    if df_failed.empty:
        st.success("No query failures in this benchmark run.")
        st.info("This is expected for point-lookups-only mode or when all queries "
                "complete within the Interactive Warehouse's 5-second timeout.")
    else:
        # Top-level failure metrics
        total_failed = len(df_failed)
        total_all = len(df_all)
        failure_rate = (total_failed / total_all * 100) if total_all > 0 else 0

        col1, col2, col3 = st.columns(3)
        col1.metric("Total Failed Queries", f"{total_failed:,}")
        col2.metric("Overall Failure Rate", f"{failure_rate:.1f}%")
        col3.metric("Successful Queries", f"{len(df_success):,}")

        st.divider()

        # Failures by warehouse and concurrency
        st.subheader("Failure Count by Warehouse & Concurrency")
        failure_summary = df_all.groupby(["warehouse_type", "concurrency_level"]).agg(
            total=("success", "count"),
            failed=("success", lambda x: (~x).sum()),
            succeeded=("success", "sum"),
        ).reset_index()
        failure_summary["failure_rate_%"] = (failure_summary["failed"] / failure_summary["total"] * 100)

        # Bar chart of failures
        failure_chart = alt.Chart(failure_summary).mark_bar().encode(
            x=alt.X("concurrency_level:O", title="Concurrent Threads"),
            y=alt.Y("failed:Q", title="Failed Queries"),
            color=alt.Color("warehouse_type:N", scale=alt.Scale(
                domain=["STANDARD", "INTERACTIVE"],
                range=["#e74c3c", "#2ecc71"]
            )),
            xOffset="warehouse_type:N",
        ).properties(
            width=700, height=350,
            title="Failed Queries by Concurrency Level"
        )
        st.altair_chart(failure_chart, use_container_width=True)

        # Failure rate chart
        rate_chart = alt.Chart(failure_summary).mark_bar().encode(
            x=alt.X("concurrency_level:O", title="Concurrent Threads"),
            y=alt.Y("failure_rate_%:Q", title="Failure Rate (%)"),
            color=alt.Color("warehouse_type:N", scale=alt.Scale(
                domain=["STANDARD", "INTERACTIVE"],
                range=["#e74c3c", "#2ecc71"]
            )),
            xOffset="warehouse_type:N",
        ).properties(
            width=700, height=300,
            title="Failure Rate (%) — Interactive enforces 5-second SLA"
        )
        st.altair_chart(rate_chart, use_container_width=True)

        # Failures by query type
        st.subheader("Failures by Query Type")
        if "query_type" in df_failed.columns:
            type_failures = df_failed.groupby(["warehouse_type", "query_type"]).size().reset_index(name="count")
            type_chart = alt.Chart(type_failures).mark_bar().encode(
                x=alt.X("query_type:N", title="Query Type"),
                y=alt.Y("count:Q", title="Failed Queries"),
                color=alt.Color("warehouse_type:N", scale=alt.Scale(
                    domain=["STANDARD", "INTERACTIVE"],
                    range=["#e74c3c", "#2ecc71"]
                )),
                xOffset="warehouse_type:N",
            ).properties(width=700, height=300, title="Failures by Query Type & Warehouse")
            st.altair_chart(type_chart, use_container_width=True)

        # Error message breakdown
        st.subheader("Error Messages")
        if "error_message" in df_failed.columns:
            error_counts = df_failed["error_message"].value_counts().head(10).reset_index()
            error_counts.columns = ["error_message", "count"]
            # Truncate long messages for display
            error_counts["error_summary"] = error_counts["error_message"].str[:120]
            st.dataframe(error_counts[["error_summary", "count"]], use_container_width=True)

        # Key insight callout
        int_failures = df_failed[df_failed["warehouse_type"] == "INTERACTIVE"]
        std_failures = df_failed[df_failed["warehouse_type"] == "STANDARD"]
        if not int_failures.empty and std_failures.empty:
            st.warning(
                f"**{len(int_failures):,} queries failed on Interactive Warehouse** "
                f"(0 on Standard). This is by design: Interactive Warehouses enforce a "
                f"5-second statement timeout. Queries that scan too much data "
                f"(like portfolio aggregations over 100M rows) are rejected to protect SLAs. "
                f"Run with `--point-lookups-only` for a clean apples-to-apples comparison."
            )

        # Failure summary table
        st.subheader("Failure Summary Table")
        st.dataframe(
            failure_summary.style.format({
                "failure_rate_%": "{:.1f}%",
                "total": "{:,.0f}",
                "failed": "{:,.0f}",
                "succeeded": "{:,.0f}",
            }),
            use_container_width=True,
        )

# ---------------------------------------------------------------------------
# Page 5: Raw Data
# ---------------------------------------------------------------------------

with tab5:
    st.subheader("Raw Benchmark Results")

    col1, col2 = st.columns([2, 1])
    with col1:
        st.dataframe(
            df_all,
            use_container_width=True,
            height=500,
        )
    with col2:
        st.markdown("**Run Metadata**")
        metadata = {
            "run_id": selected_run,
            "total_records": len(df_all),
            "successful": len(df_success),
            "failed": len(df_failed),
            "concurrency_levels": sorted(df_all["concurrency_level"].unique().tolist()),
            "warehouse_types": sorted(df_all["warehouse_type"].unique().tolist()),
            "query_types": sorted(df_all["query_type"].unique().tolist()),
        }
        if "benchmark_mode" in df_all.columns:
            metadata["benchmark_mode"] = df_all["benchmark_mode"].iloc[0] if not df_all.empty else "MIXED"
        st.json(metadata)

    # Download button
    csv_export = df_all.to_csv(index=False)
    st.download_button(
        label="Download Results CSV",
        data=csv_export,
        file_name=f"benchmark_{selected_run}_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv",
    )

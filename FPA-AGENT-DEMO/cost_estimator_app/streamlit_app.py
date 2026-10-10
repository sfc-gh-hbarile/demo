"""Acme Corp FP&A Agent - cost estimator (synthetic demo).

Calibrates cost per question from real FPA_AGENT usage, then projects daily, weekly,
monthly, and yearly cost for a given number of users, questions per user, price per
credit, and share of repeated (cache-friendly) questions.
"""
import os

import altair as alt
import pandas as pd
import streamlit as st

st.set_page_config(page_title="FP&A Agent Cost Estimator", layout="wide")

conn = st.connection("snowflake", connection_name=os.getenv("SNOWFLAKE_DEFAULT_CONNECTION_NAME") or "default")

XS_CREDITS_PER_HOUR = 1.0
TIERS = [10, 25, 50]


@st.cache_data(ttl=600)
def load_calibration() -> pd.DataFrame:
    df = conn.query("SELECT * FROM FPA_DEMO.FPA.V_COST_CALIBRATION", ttl=600)
    df.columns = [c.lower() for c in df.columns]
    return df


@st.cache_data(ttl=600)
def load_requests() -> pd.DataFrame:
    df = conn.query(
        """SELECT start_time, user_name, interface, models, input_tokens, cache_read_tokens,
                  cache_write_tokens, output_tokens, token_credits, sql_query_credits
           FROM FPA_DEMO.FPA.V_AGENT_REQUESTS ORDER BY start_time DESC LIMIT 200""",
        ttl=600,
    )
    df.columns = [c.lower() for c in df.columns]
    return df


@st.cache_data(ttl=600)
def load_load_test() -> pd.DataFrame:
    df = conn.query(
        """SELECT run_label, attempt, question_id, COUNT(request_id) AS matched_calls,
                  AVG(token_credits) AS avg_token_credits, AVG(cache_write_credits) AS avg_cache_write,
                  AVG(cache_read_credits) AS avg_cache_read, AVG(sql_query_credits) AS avg_sql_credits
           FROM FPA_DEMO.FPA.V_LOAD_TEST_COSTS
           GROUP BY 1, 2, 3 ORDER BY 1, 3, 2""",
        ttl=600,
    )
    df.columns = [c.lower() for c in df.columns]
    return df


@st.cache_data(ttl=600)
def load_runs() -> pd.DataFrame:
    df = conn.query("SELECT * FROM FPA_DEMO.FPA.V_RUN_COSTS ORDER BY start_ts DESC", ttl=600)
    df.columns = [c.lower() for c in df.columns]
    return df


@st.cache_data(ttl=600)
def load_question_costs() -> pd.DataFrame:
    """One row per agent question in a tagged run, with FIRST/REPEAT from the load-test log."""
    df = conn.query(
        """SELECT q.run_id, q.run_label, q.request_id, q.start_time, q.token_credits, q.tagged_wh_credits,
                  q.reported_sql_credits, q.tool_queries, q.warehouses, q.cache_read_credits,
                  q.cache_write_credits, COALESCE(l.attempt, 'FIRST') AS attempt, l.question_id
           FROM FPA_DEMO.FPA.V_AGENT_QUESTION_COSTS q
           LEFT JOIN FPA_DEMO.FPA.V_LOAD_TEST_COSTS l ON l.request_id = q.request_id
           WHERE q.run_id IS NOT NULL""",
        ttl=600,
    )
    df.columns = [c.lower() for c in df.columns]
    return df


@st.cache_data(ttl=3600)
def load_search_daily() -> float:
    df = conn.query(
        """SELECT COALESCE(AVG(daily), 0) AS avg_daily FROM (
             SELECT usage_date, SUM(credits) AS daily
             FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_SEARCH_DAILY_USAGE_HISTORY
             WHERE service_name = 'FPA_ASSUMPTIONS_SEARCH'
               AND usage_date >= DATEADD(day, -14, CURRENT_DATE())
             GROUP BY usage_date)""",
        ttl=3600,
    )
    return float(df.iloc[0, 0] or 0)


def project(users, qpu_day, repeat_pct, cred_first, cred_repeat, sql_per_q,
            wh_mode, wh_hours_day, search_day, work_days_month, price, wh_price=None):
    """Credits and dollars per day / week / month / year. price = $/AI Credit, wh_price = $/Platform Credit."""
    q_day = users * qpu_day
    first_q = q_day * (1 - repeat_pct / 100)
    repeat_q = q_day * repeat_pct / 100
    agent = first_q * cred_first + repeat_q * cred_repeat
    wh = q_day * sql_per_q if wh_mode == "attributed" else wh_hours_day * XS_CREDITS_PER_HOUR
    day = {"Agent tokens": agent, "Warehouse": wh, "Cortex Search": search_day}
    factors = {"Daily": 1, "Weekly": 5, "Monthly": work_days_month, "Yearly": work_days_month * 12}
    rows = []
    for period, f in factors.items():
        credits = {k: v * f for k, v in day.items()}
        total = sum(credits.values())
        # Agent tokens and Cortex Search bill in AI Credits; warehouse compute bills in Platform Credits
        dollars = (credits["Agent tokens"] + credits["Cortex Search"]) * price \
            + credits["Warehouse"] * (price if wh_price is None else wh_price)
        rows.append({"Period": period, "Questions": q_day * f, **credits,
                     "Total credits": total, "Total $": dollars})
    return pd.DataFrame(rows)


st.title("FP&A Agent Cost Estimator")
st.caption("Acme Corp synthetic demo · agent `FPA_DEMO.FPA.FPA_AGENT` · calibrated from "
           "`SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AGENT_USAGE_HISTORY` (lags up to a few hours)")

calib = load_calibration()
seg = {r["segment"]: r for _, r in calib.iterrows()}
all_req = seg.get("ALL_REQUESTS")
runs = load_runs()
qc = load_question_costs()

with st.sidebar:
    st.header("Calibration source")
    run_opts = runs[runs["questions"] > 0]
    labels = {r["run_id"]: f'{r["run_label"]} ({r["run_type"]}, {int(r["questions"])} q)' for _, r in run_opts.iterrows()}
    selected_runs = st.multiselect("Tagged runs to calibrate from", list(labels), default=list(labels),
                                   format_func=lambda k: labels[k],
                                   help="Only agent requests inside these tagged runs are used. Build, "
                                        "setup, and app queries are never counted.")

sel = qc[qc["run_id"].isin(selected_runs)]
if not sel.empty:
    measured_all = float(sel["token_credits"].mean())
    firsts, repeats = sel[sel["attempt"] == "FIRST"], sel[sel["attempt"] == "REPEAT"]
    measured_first = float(firsts["token_credits"].mean()) if not firsts.empty else measured_all
    measured_repeat = float(repeats["token_credits"].mean()) if not repeats.empty else measured_all
    measured_sql = float(sel["tagged_wh_credits"].mean())
    has_load_test = not repeats.empty
else:
    measured_all = float(all_req["avg_token_credits"]) if all_req is not None and all_req["requests"] else 0.21
    measured_first = measured_repeat = measured_all
    measured_sql = float(all_req["avg_sql_credits"] or 0) if all_req is not None else 0.0075
    has_load_test = False

# ---------------- Inputs ----------------
with st.sidebar:
    st.header("Inputs")
    price = st.number_input("AI Credit price ($)", min_value=0.0, value=2.00, step=0.10, format="%.2f",
                            help="Agent tokens and Cortex Search bill in AI Credits ($2.00 on demand, global).")
    wh_price = st.number_input("Warehouse (Platform) Credit price ($)", min_value=0.0, value=3.00, step=0.25, format="%.2f",
                               help="Warehouse compute bills in Platform Credits (e.g. $3.00 Enterprise, AWS US East).")
    users = st.number_input("Number of users", min_value=1, value=25, step=1)
    preset = st.segmented_control("Questions per user per day", ["10", "25", "50", "Custom"], default="10")
    qpu_day = (st.number_input("Custom questions per user per day", min_value=1, value=15, step=1)
               if preset == "Custom" else int(preset or 10))
    work_days = st.number_input("Working days per month", min_value=1, max_value=31, value=21, step=1)
    repeat_pct = st.slider("Repeated questions (%)", 0, 100, 30,
                           help="Share of questions that repeat a recent question. Repeats reuse the "
                                "prompt cache and usually cost less.")

    st.subheader("Credits per question")
    use_measured = st.toggle("Use measured values", value=True,
                             help="From this account's real agent requests. Turn off to enter your own.")
    if use_measured:
        cred_first, cred_repeat = measured_first, measured_repeat
        st.caption(f"First ask: **{cred_first:.4f}** · Repeat: **{cred_repeat:.4f}** credits"
                   + ("" if has_load_test else "  \n(no load-test results yet, using overall average for both)"))
    else:
        cred_first = st.number_input("First-ask credits", min_value=0.0, value=round(measured_first, 4), format="%.4f")
        cred_repeat = st.number_input("Repeat credits", min_value=0.0, value=round(measured_repeat, 4), format="%.4f")

    st.subheader("Warehouse")
    wh_label = st.radio("Warehouse cost method", ["Attributed SQL per question", "Warehouse uptime hours"],
                        help="Attributed = SQL credits Snowflake attributes to each agent call. Uptime = "
                             "hours the XS warehouse is awake per day (includes auto-suspend minimums).")
    wh_mode = "attributed" if wh_label.startswith("Attributed") else "uptime"
    sql_per_q = st.number_input("SQL credits per question", min_value=0.0, value=round(measured_sql, 5),
                                format="%.5f", disabled=wh_mode != "attributed")
    wh_hours = st.number_input("Warehouse awake hours per day (XS = 1 credit/hr)", min_value=0.0,
                               value=2.0, step=0.5, disabled=wh_mode != "uptime")
    search_day = st.number_input("Cortex Search credits per day", min_value=0.0,
                                 value=round(load_search_daily(), 4), format="%.4f",
                                 help="Defaults to the measured 14-day average for FPA_ASSUMPTIONS_SEARCH.")

# ---------------- Projection ----------------
proj = project(users, qpu_day, repeat_pct, cred_first, cred_repeat, sql_per_q,
               wh_mode, wh_hours, search_day, work_days, price, wh_price)
by = proj.set_index("Period")

c1, c2, c3, c4 = st.columns(4)
for col, period in zip((c1, c2, c3, c4), ("Daily", "Weekly", "Monthly", "Yearly")):
    col.metric(f"{period} cost", f"${by.loc[period, 'Total $']:,.0f}",
               f"{by.loc[period, 'Total credits']:,.1f} credits", delta_color="off", border=True)

split = by.loc["Daily", ["Agent tokens", "Warehouse", "Cortex Search"]]
tot = float(split.sum()) or 1.0
s1, s2, s3 = st.columns(3)
s1.metric("AI token share", f"{split['Agent tokens'] / tot:.1%}", border=True)
s2.metric("Warehouse share", f"{split['Warehouse'] / tot:.1%}", border=True)
s3.metric("Cortex Search share", f"{split['Cortex Search'] / tot:.1%}", border=True)

st.subheader("Projection")
st.dataframe(
    proj, hide_index=True, use_container_width=True,
    column_config={
        "Questions": st.column_config.NumberColumn(format="localized"),
        "Agent tokens": st.column_config.NumberColumn("Agent token credits", format="%.2f"),
        "Warehouse": st.column_config.NumberColumn("Warehouse credits", format="%.2f"),
        "Cortex Search": st.column_config.NumberColumn("Search credits", format="%.2f"),
        "Total credits": st.column_config.NumberColumn(format="%.2f"),
        "Total $": st.column_config.NumberColumn(format="dollar"),
    },
)
st.caption(f"{users} users × {qpu_day} questions/day = {users * qpu_day:,} questions/day · weekly = 5 working "
           f"days · monthly = {work_days} days · yearly = 12 months · ${price:.2f}/AI Credit · ${wh_price:.2f}/Platform Credit")

left, right = st.columns(2)
with left:
    st.subheader("10 / 25 / 50 questions per user")
    tier_rows = []
    for t in TIERS:
        m = project(users, t, repeat_pct, cred_first, cred_repeat, sql_per_q,
                    wh_mode, wh_hours, search_day, work_days, price, wh_price).set_index("Period")
        tier_rows.append({"Questions / user / day": t, "Daily $": m.loc["Daily", "Total $"],
                          "Monthly $": m.loc["Monthly", "Total $"], "Yearly $": m.loc["Yearly", "Total $"],
                          "Monthly credits": m.loc["Monthly", "Total credits"]})
    st.dataframe(pd.DataFrame(tier_rows), hide_index=True, use_container_width=True,
                 column_config={k: st.column_config.NumberColumn(format="dollar")
                                for k in ("Daily $", "Monthly $", "Yearly $")} |
                               {"Monthly credits": st.column_config.NumberColumn(format="%.1f")})
with right:
    st.subheader("Monthly cost by number of users")
    curve = []
    for u in sorted({1, 5, 10, 25, 50, 100, 250, 500, int(users)}):
        for t in TIERS:
            m = project(u, t, repeat_pct, cred_first, cred_repeat, sql_per_q,
                        wh_mode, wh_hours, search_day, work_days, price, wh_price).set_index("Period")
            curve.append({"Users": u, "Questions/user/day": str(t), "Monthly $": m.loc["Monthly", "Total $"]})
    st.altair_chart(
        alt.Chart(pd.DataFrame(curve)).mark_line(point=True).encode(
            x="Users:Q", y=alt.Y("Monthly $:Q", axis=alt.Axis(format="$,.0f")),
            color="Questions/user/day:N", tooltip=["Users", "Questions/user/day", alt.Tooltip("Monthly $", format="$,.0f")]),
        use_container_width=True)

# ---------------- Observed actuals ----------------
st.divider()
st.subheader("Observed actuals (this account)")
if all_req is not None and all_req["requests"]:
    a1, a2, a3, a4 = st.columns(4)
    a1.metric("Agent requests measured", f"{int(all_req['requests'])}", border=True)
    a2.metric("Avg token credits / question", f"{measured_all:.4f}", f"${measured_all * price + measured_sql * wh_price:.2f} per question",
              delta_color="off", border=True)
    a3.metric("Input tokens served from cache", f"{float(all_req['cache_hit_ratio_tokens'] or 0):.0%}", border=True)
    a4.metric("Credits spent on cache writes", f"{float(all_req['cache_write_share'] or 0):.0%}", border=True)

st.markdown("**Tagged runs** (exact: agent tokens + warehouse compute of the agent's own tool queries)")
st.dataframe(
    runs[["run_label", "run_type", "user_name", "start_ts", "questions", "token_credits", "tagged_wh_credits",
          "metered_agent_wh", "harness_credits_excluded", "token_pct", "wh_pct"]],
    hide_index=True, use_container_width=True,
    column_config={"token_pct": st.column_config.NumberColumn("Token %", format="%.2f%%"),
                   "wh_pct": st.column_config.NumberColumn("Warehouse %", format="%.2f%%"),
                   "metered_agent_wh": st.column_config.NumberColumn("Metered FPA_AGENT_WH (incl. idle)"),
                   "harness_credits_excluded": st.column_config.NumberColumn("Harness (excluded)")})

lt = load_load_test()
if not lt.empty and lt["matched_calls"].sum() > 0:
    st.markdown("**Load test: first ask vs repeat** (same question asked again)")
    st.dataframe(lt, hide_index=True, use_container_width=True)
    if has_load_test and measured_first:
        st.info(f"Repeated questions cost {measured_repeat / measured_first:.0%} of a first ask "
                f"({measured_repeat:.4f} vs {measured_first:.4f} credits).")
else:
    st.caption("No load-test results yet. Run `CALL FPA_DEMO.FPA.RUN_AGENT_LOAD_TEST(8, 'smoke');` "
               "and check back after ACCOUNT_USAGE latency (a few hours).")

with st.expander("Recent agent requests"):
    st.dataframe(load_requests(), hide_index=True, use_container_width=True)

with st.expander("How this estimate works"):
    st.markdown(
        f"""
- **Calibration** uses only agent requests inside the selected tagged runs (`FPA_DEMO.FPA.COST_RUNS`).
  Token credits come from `CORTEX_AGENT_USAGE_HISTORY`; warehouse credits are the attributed compute of
  queries Snowflake tagged `cortex-agent-<request_id>` / `snowflake-intelligence-<request_id>`
  (stored procedure internals rolled up via `ROOT_QUERY_ID`).
- **Questions/day** = users × questions per user per day.
- **Agent token credits/day** = first asks × first-ask credits + repeats × repeat credits.
  Repeats reuse the model's prompt cache. Cache reads are billed far below cache writes.
- **Warehouse credits/day** = questions × attributed SQL credits per question, *or* awake hours × 1 credit/hour (XS).
- **Cortex Search credits/day** = measured or entered daily serving cost (not per question).
- **Week** = 5 working days, **month** = working days per month, **year** = 12 months. **$** = AI Credits (tokens, search) × AI Credit price + warehouse credits × Platform Credit price.
- Estimates reflect this demo's question mix and model (`auto` orchestration). Longer conversations,
  more tools, or different models change cost per question. Re-measure with your own questions.
- The resource monitor on `FPA_DEMO_WH` caps **warehouse** credits only. Agent token credits are serverless;
  use a Snowflake budget to cap AI spend.
"""
    )

# FP&A Agent Cost Estimator - self-contained Streamlit in Snowflake app (synthetic Acme Corp demo)
# Paste into: Snowsight > Projects > Streamlit > + Streamlit App
#   Role: FPA_DEMO_ROLE   Location: FPA_DEMO.FPA   Warehouse: FPA_DEMO_WH   Runtime: Run on warehouse
# No pyproject.toml, packages, or external access integration needed (streamlit, pandas, altair are built in).
import altair as alt
import pandas as pd
import streamlit as st
from snowflake.snowpark.context import get_active_session

st.set_page_config(page_title="FP&A Agent Cost Estimator", layout="wide")
session = get_active_session()

XS_CREDITS_PER_HOUR = 1.0
TIERS = [10, 25, 50]


def q(sql: str) -> pd.DataFrame:
    df = session.sql(sql).to_pandas()
    df.columns = [c.lower() for c in df.columns]
    return df


@st.cache_data(ttl=600)
def load_runs() -> pd.DataFrame:
    return q("SELECT * FROM FPA_DEMO.FPA.V_RUN_COSTS ORDER BY start_ts DESC")


@st.cache_data(ttl=600)
def load_question_costs() -> pd.DataFrame:
    return q("""SELECT q.run_id, q.run_label, q.request_id, q.start_time, q.token_credits, q.tagged_wh_credits,
                       q.reported_sql_credits, q.tool_queries, q.warehouses, q.cache_read_credits,
                       q.cache_write_credits, COALESCE(l.attempt, 'FIRST') AS attempt, l.question_id
                FROM FPA_DEMO.FPA.V_AGENT_QUESTION_COSTS q
                LEFT JOIN FPA_DEMO.FPA.V_LOAD_TEST_COSTS l ON l.request_id = q.request_id
                WHERE q.run_id IS NOT NULL""")


@st.cache_data(ttl=600)
def load_all_requests() -> pd.DataFrame:
    return q("""SELECT COUNT(*) AS requests, AVG(token_credits) AS avg_token_credits,
                       AVG(sql_query_credits) AS avg_sql_credits,
                       SUM(cache_read_tokens) / NULLIF(SUM(cache_read_tokens + cache_write_tokens + input_tokens), 0) AS cache_hit,
                       SUM(cache_write_credits) / NULLIF(SUM(token_credits), 0) AS cache_write_share
                FROM FPA_DEMO.FPA.V_AGENT_REQUESTS""")


@st.cache_data(ttl=600)
def load_recent_requests() -> pd.DataFrame:
    return q("""SELECT start_time, user_name, interface, models, cache_read_tokens, cache_write_tokens,
                       output_tokens, token_credits, sql_query_credits
                FROM FPA_DEMO.FPA.V_AGENT_REQUESTS ORDER BY start_time DESC LIMIT 200""")


@st.cache_data(ttl=3600)
def load_search_daily() -> float:
    df = q("""SELECT COALESCE(AVG(daily), 0) AS avg_daily FROM (
                SELECT usage_date, SUM(credits) AS daily
                FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_SEARCH_DAILY_USAGE_HISTORY
                WHERE service_name = 'FPA_ASSUMPTIONS_SEARCH' AND usage_date >= DATEADD(day, -14, CURRENT_DATE())
                GROUP BY usage_date)""")
    return float(df.iloc[0, 0] or 0)


def project(users, qpu_day, repeat_pct, cred_first, cred_repeat, sql_per_q,
            wh_mode, wh_hours_day, search_day, work_days_month, price):
    """Credits and dollars per day / week / month / year."""
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
        rows.append({"Period": period, "Questions": q_day * f, **credits,
                     "Total credits": total, "Total $": total * price})
    return pd.DataFrame(rows)


def money(x: float) -> str:
    return f"${x:,.0f}"


st.title("FP&A Agent Cost Estimator")
st.caption("Acme Corp synthetic demo | agent FPA_DEMO.FPA.FPA_AGENT | calibrated from tagged runs "
           "(CORTEX_AGENT_USAGE_HISTORY + tagged tool-query compute; ACCOUNT_USAGE lags a few hours)")

# ---------------- Calibration ----------------
try:
    runs = load_runs()
    qc = load_question_costs()
    allreq = load_all_requests().iloc[0]
    search_default = load_search_daily()
except Exception as e:  # views missing or no privilege: still let the user enter values manually
    st.warning(f"Could not read cost views ({e}). Enter credits per question manually.")
    runs, qc, allreq, search_default = pd.DataFrame(), pd.DataFrame(), None, 0.0

st.sidebar.header("Calibration source")
selected_runs = []
if not runs.empty:
    run_opts = runs[runs["questions"] > 0]
    labels = {r["run_id"]: f'{r["run_label"]} ({r["run_type"]}, {int(r["questions"])} q)'
              for _, r in run_opts.iterrows()}
    selected_runs = st.sidebar.multiselect("Tagged runs to calibrate from", list(labels), default=list(labels),
                                           format_func=lambda k: labels[k],
                                           help="Only agent requests inside these tagged runs are used. "
                                                "Build, setup, and app queries are never counted.")

sel = qc[qc["run_id"].isin(selected_runs)] if not qc.empty else qc
if not sel.empty:
    measured_all = float(sel["token_credits"].mean())
    firsts, repeats = sel[sel["attempt"] == "FIRST"], sel[sel["attempt"] == "REPEAT"]
    measured_first = float(firsts["token_credits"].mean()) if not firsts.empty else measured_all
    measured_repeat = float(repeats["token_credits"].mean()) if not repeats.empty else measured_all
    measured_sql = float(sel["tagged_wh_credits"].mean())
    has_repeat = not repeats.empty
else:
    measured_all = float(allreq["avg_token_credits"]) if allreq is not None and allreq["requests"] else 0.20
    measured_first = measured_repeat = measured_all
    measured_sql = float(allreq["avg_sql_credits"] or 0) if allreq is not None else 0.003
    has_repeat = False

# ---------------- Inputs ----------------
st.sidebar.header("Inputs")
price = st.sidebar.number_input("Price per credit ($)", min_value=0.0, value=3.00, step=0.25, format="%.2f")
users = int(st.sidebar.number_input("Number of users", min_value=1, value=25, step=1))
preset = st.sidebar.radio("Questions per user per day", ["10", "25", "50", "Custom"], horizontal=True)
qpu_day = (int(st.sidebar.number_input("Custom questions per user per day", min_value=1, value=15, step=1))
           if preset == "Custom" else int(preset))
work_days = int(st.sidebar.number_input("Working days per month", min_value=1, max_value=31, value=21, step=1))
repeat_pct = st.sidebar.slider("Repeated questions (%)", 0, 100, 30,
                               help="Share of questions that repeat a recent question. Repeats reuse the "
                                    "prompt cache and usually cost less.")

st.sidebar.subheader("Credits per question")
use_measured = st.sidebar.checkbox("Use measured values", value=True)
if use_measured:
    cred_first, cred_repeat = measured_first, measured_repeat
    st.sidebar.caption(f"First ask: {cred_first:.4f} | Repeat: {cred_repeat:.4f} credits"
                       + ("" if has_repeat else " (no repeat data yet, overall average used)"))
else:
    cred_first = st.sidebar.number_input("First-ask credits", min_value=0.0, value=round(measured_first, 4), format="%.4f")
    cred_repeat = st.sidebar.number_input("Repeat credits", min_value=0.0, value=round(measured_repeat, 4), format="%.4f")

st.sidebar.subheader("Warehouse")
wh_label = st.sidebar.radio("Warehouse cost method", ["Attributed SQL per question", "Warehouse uptime hours"],
                            help="Attributed = exact compute of the agent's tagged tool queries. Uptime = hours "
                                 "the XS warehouse is awake per day (includes idle and 60s resume minimums).")
wh_mode = "attributed" if wh_label.startswith("Attributed") else "uptime"
if wh_mode == "attributed":
    sql_per_q = st.sidebar.number_input("SQL credits per question", min_value=0.0,
                                        value=round(measured_sql, 5), format="%.5f")
    wh_hours = 0.0
else:
    sql_per_q = 0.0
    wh_hours = st.sidebar.number_input("Warehouse awake hours per day (XS = 1 credit/hr)",
                                       min_value=0.0, value=2.0, step=0.5)
search_day = st.sidebar.number_input("Cortex Search credits per day", min_value=0.0,
                                     value=round(search_default, 4), format="%.4f")

# ---------------- Projection ----------------
proj = project(users, qpu_day, repeat_pct, cred_first, cred_repeat, sql_per_q,
               wh_mode, wh_hours, search_day, work_days, price)
by = proj.set_index("Period")

cols = st.columns(4)
for col, period in zip(cols, ("Daily", "Weekly", "Monthly", "Yearly")):
    col.metric(f"{period} cost", money(by.loc[period, "Total $"]), f"{by.loc[period, 'Total credits']:,.1f} credits",
               delta_color="off")

split = by.loc["Daily", ["Agent tokens", "Warehouse", "Cortex Search"]]
tot = float(split.sum()) or 1.0
s1, s2, s3 = st.columns(3)
s1.metric("AI token share", f"{split['Agent tokens'] / tot:.1%}")
s2.metric("Warehouse share", f"{split['Warehouse'] / tot:.1%}")
s3.metric("Cortex Search share", f"{split['Cortex Search'] / tot:.1%}")

st.subheader("Projection")
show = proj.copy()
for c in ("Agent tokens", "Warehouse", "Cortex Search", "Total credits"):
    show[c] = show[c].map(lambda v: f"{v:,.2f}")
show["Questions"] = show["Questions"].map(lambda v: f"{v:,.0f}")
show["Total $"] = proj["Total $"].map(money)
st.dataframe(show, hide_index=True, use_container_width=True)
st.caption(f"{users} users x {qpu_day} questions/day = {users * qpu_day:,} questions/day | weekly = 5 working days | "
           f"monthly = {work_days} days | yearly = 12 months | ${price:.2f}/credit")

left, right = st.columns(2)
with left:
    st.subheader("10 / 25 / 50 questions per user")
    tier_rows = []
    for t in TIERS:
        m = project(users, t, repeat_pct, cred_first, cred_repeat, sql_per_q,
                    wh_mode, wh_hours, search_day, work_days, price).set_index("Period")
        tier_rows.append({"Questions / user / day": t, "Daily": money(m.loc["Daily", "Total $"]),
                          "Monthly": money(m.loc["Monthly", "Total $"]), "Yearly": money(m.loc["Yearly", "Total $"]),
                          "Monthly credits": f'{m.loc["Monthly", "Total credits"]:,.1f}'})
    st.dataframe(pd.DataFrame(tier_rows), hide_index=True, use_container_width=True)
with right:
    st.subheader("Monthly cost by number of users")
    curve = []
    for u in sorted({1, 5, 10, 25, 50, 100, 250, 500, users}):
        for t in TIERS:
            m = project(u, t, repeat_pct, cred_first, cred_repeat, sql_per_q,
                        wh_mode, wh_hours, search_day, work_days, price).set_index("Period")
            curve.append({"Users": u, "Questions/user/day": str(t), "Monthly $": m.loc["Monthly", "Total $"]})
    chart = alt.Chart(pd.DataFrame(curve)).mark_line(point=True).encode(
        x="Users:Q", y=alt.Y("Monthly $:Q", axis=alt.Axis(format="$,.0f")),
        color="Questions/user/day:N",
        tooltip=["Users", "Questions/user/day", alt.Tooltip("Monthly $:Q", format="$,.0f")])
    st.altair_chart(chart, use_container_width=True)

# ---------------- Observed actuals ----------------
st.divider()
st.subheader("Observed actuals (this account)")
if allreq is not None and allreq["requests"]:
    a1, a2, a3, a4 = st.columns(4)
    a1.metric("Agent requests measured", f"{int(allreq['requests'])}")
    a2.metric("Avg token credits / question", f"{measured_all:.4f}", f"${measured_all * price:.2f} per question",
              delta_color="off")
    a3.metric("Input tokens served from cache", f"{float(allreq['cache_hit'] or 0):.0%}")
    a4.metric("Credits spent on cache writes", f"{float(allreq['cache_write_share'] or 0):.0%}")

if not runs.empty:
    st.markdown("**Tagged runs** (agent tokens + exact compute of the agent's own tool queries)")
    st.dataframe(runs[["run_label", "run_type", "user_name", "start_ts", "questions", "token_credits",
                       "tagged_wh_credits", "metered_agent_wh", "harness_credits_excluded", "token_pct", "wh_pct"]],
                 hide_index=True, use_container_width=True)

if not sel.empty and has_repeat:
    st.info(f"Repeated questions cost {measured_repeat / measured_first:.0%} of a first ask "
            f"({measured_repeat:.4f} vs {measured_first:.4f} credits).")

with st.expander("Per-question costs in selected runs"):
    st.dataframe(sel, hide_index=True, use_container_width=True)

with st.expander("Recent agent requests"):
    try:
        st.dataframe(load_recent_requests(), hide_index=True, use_container_width=True)
    except Exception as e:
        st.write(f"Unavailable: {e}")

with st.expander("How this estimate works"):
    st.markdown(f"""
- **Calibration** uses only agent requests inside the selected tagged runs (`FPA_DEMO.FPA.COST_RUNS`).
  Token credits come from `CORTEX_AGENT_USAGE_HISTORY`. Warehouse credits are the attributed compute of queries
  Snowflake tagged `cortex-agent-<request_id>` or `snowflake-intelligence-<request_id>` (procedure internals rolled up).
- **Questions/day** = users x questions per user per day.
- **Agent token credits/day** = first asks x first-ask credits + repeats x repeat credits.
- **Warehouse credits/day** = questions x SQL credits per question, *or* awake hours x 1 credit/hour (XS).
- **Cortex Search credits/day** = measured or entered daily serving cost.
- **Week** = 5 working days, **month** = working days per month, **year** = 12 months, **$** = credits x price.
- Estimates reflect this demo's questions and model. Re-measure with your own questions before quoting.
- The resource monitor caps **warehouse** credits only; use a Snowflake budget to cap AI spend.
""")

# =============================================================================
# Snowflake BCR Tracker v2 — Streamlit in Snowflake
# =============================================================================
# Deploy: Snowsight > Projects > Streamlit > + Streamlit App
# DB: BCR_TRACKER_DB  |  Schema: TRACKING  |  WH: COMPUTE_WH
# Run setup.sql first.
# =============================================================================

import streamlit as st
import pandas as pd
import altair as alt
import json
import re
from datetime import datetime, date

st.set_page_config(
    page_title="BCR Tracker",
    page_icon="❄️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Constants ────────────────────────────────────────────────────────────────
SF_BLUE    = "#29B5E8"
DB         = "BCR_TRACKER_DB.TRACKING"
STATUSES   = ["Not Started", "In Review", "Tested", "Confirmed Safe", "Action Required", "N/A"]
IMPACTS    = ["High", "Medium", "Low", "TBD"]

STATUS_COLORS = {
    "Enabled by Default":  ("#27ae60", "🟢"),
    "Disabled by Default": ("#f39c12", "🟡"),
    "Enforced":            ("#7f8c8d", "✅"),
    "Draft":               ("#95a5a6", "⚪"),
}
IMPACT_COLORS = {"High": "#e74c3c", "Medium": "#e67e22", "Low": "#27ae60", "TBD": "#95a5a6"}

# ─── Session ──────────────────────────────────────────────────────────────────
@st.cache_resource
def get_session():
    try:
        # Running inside Snowsight (Streamlit in Snowflake)
        from snowflake.snowpark.context import get_active_session
        return get_active_session()
    except Exception:
        # Running locally — uses named connection from ~/.snowflake/connections.toml
        # Set BCR_CONNECTION env var to override, default = "demo"
        import os
        from snowflake.snowpark import Session
        conn = os.environ.get("BCR_CONNECTION", "demo")
        return Session.builder.config("connection_name", conn).create()

session = get_session()

# ─── Data loaders ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=120)
def load_registry() -> pd.DataFrame:
    return session.sql(f"""
        SELECT r.BCR_ID, r.BUNDLE_ID, r.UNBUNDLED, r.BUNDLE_STATUS,
               r.CATEGORY, r.TITLE, r.DESCRIPTION,
               r.IMPACT_DEFAULT, r.DBD, r.EBD, r.GE, r.DOCS_URL, r.FETCHED_AT,
               COALESCE(a.IMPACT_OVERRIDE, r.IMPACT_DEFAULT) AS EFFECTIVE_IMPACT,
               COALESCE(a.NONPROD_STATUS, 'Not Started')     AS NONPROD_STATUS,
               COALESCE(a.PROD_STATUS,    'Not Started')     AS PROD_STATUS,
               a.OWNER, a.NOTES, a.SIGN_OFF_DATE, a.CASE_ID,
               COALESCE(a.RISK_ACCEPTED, FALSE)               AS RISK_ACCEPTED,
               a.IMPACT_OVERRIDE,
               a.LAST_UPDATED_BY, a.LAST_UPDATED_AT
        FROM {DB}.BCR_REGISTRY r
        LEFT JOIN {DB}.BCR_ASSESSMENTS a ON r.BCR_ID = a.BCR_ID
        ORDER BY r.BUNDLE_ID DESC, r.UNBUNDLED, r.IMPACT_DEFAULT, r.CATEGORY
    """).to_pandas()

@st.cache_data(ttl=30)
def load_active_bundles() -> list:
    """Returns bundle list from SYSTEM$ with isDefault/isEnabled flags."""
    try:
        raw  = session.sql("SELECT SYSTEM$SHOW_ACTIVE_BEHAVIOR_CHANGE_BUNDLES()").collect()[0][0]
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except Exception:
        return []

@st.cache_data(ttl=120)
def load_config() -> dict:
    rows = session.sql(f"SELECT SETTING_KEY, SETTING_VALUE FROM {DB}.BCR_CONFIG").collect()
    return {r[0]: r[1] for r in rows}

@st.cache_data(ttl=60)
def load_detection_queries() -> pd.DataFrame:
    return session.sql(f"""
        SELECT BCR_ID, DETECTION_SQL, GENERATED_BY, APPROVED, APPROVED_BY, UPDATED_AT
        FROM {DB}.BCR_DETECTION_QUERIES
    """).to_pandas()

@st.cache_data(ttl=600)
def load_regression_snapshots() -> pd.DataFrame:
    return session.sql(f"""
        SELECT BUNDLE_ID, SNAPSHOT_DATE, TOTAL_QUERIES,
               ERROR_COUNT, ERROR_RATE, BASELINE_ERROR_RATE, DELTA_VS_BASELINE
        FROM {DB}.BCR_REGRESSION_SNAPSHOTS
        ORDER BY BUNDLE_ID, SNAPSHOT_DATE
    """).to_pandas()

def clear_all_cache():
    load_registry.clear()
    load_active_bundles.clear()
    load_config.clear()
    load_detection_queries.clear()
    load_regression_snapshots.clear()

# ─── Helpers ──────────────────────────────────────────────────────────────────
def strip_sql_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r'^```[a-zA-Z]*\s*\n?', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n?```\s*$', '', text)
    return text.strip()


def parse_bcr_sections(description: str) -> dict:
    """
    Extract structured sections from a BCR description.
    Preserves newlines and markdown so content renders correctly.
    Returns dict with keys: before, after, what_to_do, code_examples.

    The "What you need to do" section often contains the exact SQL pattern
    that broke — that's the highest-quality signal for detection queries.
    """
    if not description:
        return {"before": "", "after": "", "what_to_do": "", "code_examples": []}

    # Strip inline HTML but PRESERVE newlines — collapsing to spaces loses
    # bullet lists, code blocks and section structure
    clean = re.sub(r'<[^>]+>', '', description)

    def extract(pattern, text):
        m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        return m.group(1).strip() if m else ""

    before     = extract(r'Before the change[:\s]+(.*?)(?=After the change|What you need|$)', clean)
    after      = extract(r'After the change[:\s]+(.*?)(?=What you need to do|What to do|$)', clean)
    what_to_do = extract(r'What you need to do[:\s]+(.*?)$', clean)

    # Extract ALL code blocks (``` ... ```) from the full description
    # These are the concrete SQL patterns Snowflake says will be affected
    code_examples = re.findall(r'```(?:sql)?\s*\n?(.*?)```', description, re.DOTALL | re.IGNORECASE)
    code_examples = [c.strip() for c in code_examples if c.strip() and len(c.strip()) > 10]

    # Also extract inline backtick SQL references from "What you need to do"
    # e.g. `SELECT TO_CHAR(...)` — these signal the function to search for
    sql_functions = re.findall(
        r'\b(TO_CHAR|TO_DATE|TO_TIMESTAMP|JOIN\s+\w+\s+USING|COPY_HISTORY|'
        r'METERING_HISTORY|ALERT_HISTORY|SHOW\s+\w+|GRANT\s+\w+)\b',
        what_to_do + " " + after,
        re.IGNORECASE
    )

    return {
        "before":        before[:800],
        "after":         after[:900],
        "what_to_do":    what_to_do[:1000],
        "code_examples": code_examples[:4],
        "sql_functions": list(dict.fromkeys(f.strip() for f in sql_functions))[:5],
    }



def parse_ebd_days(ebd_str: str):
    """Returns days until EBD, or None if unparseable."""
    if not ebd_str or ebd_str.strip() in ("", "TBD"):
        return None
    for fmt in ("%B %d, %Y", "%B %d %Y", "%b %d, %Y",
                "%b %d %Y", "%m/%Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(ebd_str.strip(), fmt).date()
            return (dt - date.today()).days
        except ValueError:
            continue
    return None

def bundle_status_from_flags(is_default: bool, is_enabled: bool) -> str:
    if is_default and is_enabled:   return "Enabled by Default"
    if not is_default and not is_enabled: return "Disabled by Default"
    if is_enabled:                  return "Enabled"
    return "Draft"

# ─── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(f"<h2 style='color:{SF_BLUE}'>❄️ BCR Tracker</h2>", unsafe_allow_html=True)
    page = st.radio("", ["🏠 Dashboard", "📋 Assessment",
                         "🔬 Detection Lab", "📈 Regression",
                         "⚙️ Settings"],
                    label_visibility="collapsed")
    st.divider()
    cfg          = load_config()
    last_refresh = cfg.get("LAST_REFRESH") or "Never"
    if last_refresh != "Never":
        try:
            last_refresh = datetime.fromisoformat(last_refresh).strftime("%b %d %H:%M UTC")
        except Exception:
            pass
    st.caption(f"Last sync: **{last_refresh}**")
    if st.button("⟳ Sync Now", use_container_width=True, type="primary"):
        with st.spinner("Syncing active bundles…"):
            try:
                result = session.sql(f"CALL {DB}.SYNC_ACTIVE_BUNDLES()").collect()[0][0]
                st.sidebar.success("Done")
                for line in result.split("\n"):
                    st.sidebar.caption(line)
                clear_all_cache()
                st.rerun()
            except Exception as e:
                st.sidebar.error(str(e))

# =============================================================================
# PAGE: DASHBOARD
# =============================================================================
if page == "🏠 Dashboard":
    df = load_registry()
    active_bundles = load_active_bundles()

    # ── Header ────────────────────────────────────────────────────────────────
    st.markdown(f"<h1 style='color:{SF_BLUE};margin-bottom:2px'>Snowflake BCR Tracker</h1>",
                unsafe_allow_html=True)
    st.caption(
        "📅 **DBD** Disabled by Default (opt-in testing)  ·  "
        "**EBD** Enabled by Default (change activates)  ·  "
        "**GE** Generally Enabled (permanent, no opt-out)"
    )

    if df.empty:
        st.warning("No BCR data loaded yet. Click **⟳ Sync Now** in the sidebar.")
        st.stop()

    # ── Status color map for NONPROD status badges ────────────────────────────
    STATUS_BADGE = {
        "Action Required": ("#e74c3c", "white"),
        "In Review":       ("#f39c12", "white"),
        "Tested":          ("#2980b9", "white"),
        "Confirmed Safe":  ("#27ae60", "white"),
        "Not Started":     ("#ecf0f1", "#555"),
        "N/A":             ("#bdc3c7", "white"),
    }
    def status_badge(status: str) -> str:
        bg, fg = STATUS_BADGE.get(status or "Not Started", ("#ecf0f1", "#555"))
        s = status or "Not Started"
        return (f"<span style='background:{bg};color:{fg};padding:2px 8px;"
                f"border-radius:3px;font-size:11px;white-space:nowrap'>{s}</span>")

    def _first_date(rows, col):
        if rows.empty or col not in rows.columns: return None
        v = rows[col].dropna()
        v = v[v.astype(str).str.strip() != ""]
        return str(v.iloc[0]).strip() if not v.empty else None

    # ── Build bundle metadata ─────────────────────────────────────────────────
    bundle_meta = {}
    for b in active_bundles:
        bid    = b.get("name", "")
        status = bundle_status_from_flags(b.get("isDefault", False), b.get("isEnabled", False))
        brows  = df[(df["BUNDLE_ID"] == bid) & (~df["UNBUNDLED"].fillna(False))]
        total  = len(brows)
        assessed = len(brows[~brows["NONPROD_STATUS"].isin(["Not Started", None, ""])])
        bundle_meta[bid] = {
            "status":   status,
            "dbd":      _first_date(brows, "DBD") or "—",
            "ebd":      _first_date(brows, "EBD") or "—",
            "ge":       _first_date(brows, "GE")  or "—",
            "days":     parse_ebd_days(_first_date(brows, "EBD")),
            "total":    total,
            "high":     len(brows[brows["EFFECTIVE_IMPACT"] == "High"]),
            "action":   len(brows[brows["NONPROD_STATUS"]   == "Action Required"]),
            "safe":     len(brows[brows["NONPROD_STATUS"]   == "Confirmed Safe"]),
            "assessed": assessed,
        }

    reg_bundles = sorted(
        df[~df["UNBUNDLED"].fillna(False)]["BUNDLE_ID"].dropna().unique().tolist(),
        reverse=True
    )
    historical = [b for b in reg_bundles if b not in bundle_meta]

    # ── "Needs Attention" alert ───────────────────────────────────────────────
    # Surface High/Medium BCRs with EBD < 30 days that haven't been started
    urgent = df[
        (~df["UNBUNDLED"].fillna(False)) &
        (df["EFFECTIVE_IMPACT"].isin(["High", "Medium"])) &
        (df["NONPROD_STATUS"].isin(["Not Started", None, ""]))
    ].copy()

    # Filter to bundles with EBD < 30 days
    urgent_bundles = [
        bid for bid, meta in bundle_meta.items()
        if meta["days"] is not None and 0 <= meta["days"] <= 30
    ]
    urgent = urgent[urgent["BUNDLE_ID"].isin(urgent_bundles)]

    if not urgent.empty:
        high_urgent   = len(urgent[urgent["EFFECTIVE_IMPACT"] == "High"])
        medium_urgent = len(urgent[urgent["EFFECTIVE_IMPACT"] == "Medium"])
        ebd_days      = min(
            (meta["days"] for meta in bundle_meta.values()
             if meta["days"] is not None and 0 <= meta["days"] <= 30),
            default=30
        )
        st.error(
            f"⚠️ **{len(urgent)} unreviewed BCRs approaching enforcement** — "
            f"{high_urgent} High · {medium_urgent} Medium · "
            f"EBD in **{ebd_days} days**. "
            f"Go to **Assessment** to update statuses."
        )
    else:
        # Check for any action required items
        action_count = sum(m["action"] for m in bundle_meta.values())
        if action_count:
            st.warning(f"⚠️ **{action_count} BCR(s) marked Action Required** — review in Assessment.")

    # ── Bundle Status Cards ───────────────────────────────────────────────────
    st.subheader("Active Bundles")
    if bundle_meta:
        bundle_order = sorted(bundle_meta.keys(), reverse=True)
        if ("selected_bundle" not in st.session_state or
                st.session_state["selected_bundle"] not in bundle_meta):
            st.session_state["selected_bundle"] = bundle_order[0]

        cols = st.columns(len(bundle_meta))
        for col, bid in zip(cols, bundle_order):
            meta   = bundle_meta[bid]
            color, icon = STATUS_COLORS.get(meta["status"], ("#95a5a6", "⚪"))
            is_sel = st.session_state["selected_bundle"] == bid
            days   = meta["days"]
            border = f"3px solid {color}" if is_sel else f"1px solid {color}44"
            bg     = "#f0f8ff" if is_sel else "white"

            # EBD label + color
            if days is None:
                ebd_color, days_label = "#95a5a6", ""
            elif days < 0:
                ebd_color, days_label = "#7f8c8d", "enforced"
            elif days < 30:
                ebd_color, days_label = "#e74c3c", f"⚠️ {days}d"
            elif days < 60:
                ebd_color, days_label = "#e67e22", f"{days}d"
            else:
                ebd_color, days_label = "#27ae60", f"{days}d"

            # Assessment progress
            pct     = int(meta["assessed"] / meta["total"] * 100) if meta["total"] else 0
            pct_bar = f"<div style='background:#e0e0e0;border-radius:4px;height:5px;margin-top:6px'>" \
                      f"<div style='background:{color};width:{pct}%;height:5px;border-radius:4px'></div></div>"

            with col:
                st.markdown(
                    f"""<div style='border:{border};border-radius:10px;padding:16px;
                        background:{bg};margin-bottom:8px'>
                    <div style='font-size:20px;font-weight:700;color:{SF_BLUE}'>{bid}</div>
                    <div style='font-size:12px;color:{color};font-weight:600;margin:3px 0 6px'>
                        {icon} {meta['status']}</div>
                    <div style='font-size:12px;line-height:2;color:#444'>
                        <b>DBD</b>&nbsp; {meta['dbd']}<br>
                        <b style='color:{ebd_color}'>EBD</b>&nbsp; {meta['ebd']}
                        {f"&nbsp;<b style='color:{ebd_color}'>{days_label}</b>" if days_label else ""}<br>
                        <b>GE</b>&nbsp;&nbsp; {meta['ge']}
                    </div>
                    <hr style='margin:8px 0;border-color:#eee'>
                    <div style='font-size:12px;display:flex;justify-content:space-between'>
                        <span><b>{meta['total']}</b> BCRs</span>
                        <span style='color:{IMPACT_COLORS["High"]}'><b>{meta['high']}</b> High</span>
                        <span style='color:#e74c3c'><b>{meta['action']}</b> Action</span>
                        <span style='color:#27ae60'><b>{meta['safe']}</b> Safe</span>
                    </div>
                    <div style='font-size:11px;color:#888;margin-top:4px'>
                        {meta['assessed']}/{meta['total']} assessed
                        {pct_bar}
                    </div>
                    </div>""",
                    unsafe_allow_html=True,
                )
                if st.button(
                    "✓ Viewing" if is_sel else "View BCRs",
                    key=f"card_{bid}",
                    use_container_width=True,
                    type="primary" if is_sel else "secondary",
                ):
                    st.session_state["selected_bundle"] = bid
                    st.rerun()
    else:
        st.info("No active bundles found. Click **⟳ Sync Now** to load.")

    # Historical bundles
    if historical:
        with st.expander(
            f"📁 Historical — {', '.join(historical[:5])}{'…' if len(historical) > 5 else ''}"
        ):
            hcols = st.columns(min(len(historical), 5))
            for col, bid in zip(hcols * 10, historical):
                brows = df[df["BUNDLE_ID"] == bid]
                with col:
                    if st.button(bid, key=f"hist_{bid}", use_container_width=True):
                        st.session_state["selected_bundle"] = bid
                        st.rerun()
                    st.caption(f"{len(brows)} BCRs")

    st.divider()

    # ── BCR list — grouped by category, color-coded status ───────────────────
    sel       = st.session_state.get("selected_bundle", "")
    bundle_df = df[(df["BUNDLE_ID"] == sel) & (~df["UNBUNDLED"].fillna(False))].copy()

    if sel:
        meta = bundle_meta.get(sel, {})
        ebd_str  = meta.get("ebd", "—")
        days_rem = meta.get("days")
        days_msg = (f" · ⚠️ **{days_rem}d to EBD**" if days_rem is not None and 0 <= days_rem <= 30
                    else f" · {days_rem}d to EBD" if days_rem and days_rem > 0 else "")
        st.subheader(f"Bundle {sel}{days_msg}")
    else:
        st.subheader("Select a bundle above")

    if not bundle_df.empty:
        # ── Filter bar ────────────────────────────────────────────────────────
        fc1, fc2, fc3 = st.columns([2, 2, 4])
        cats      = ["All"] + sorted(bundle_df["CATEGORY"].dropna().unique().tolist())
        sel_cat   = fc1.selectbox("Category", cats, key="d_cat")
        sel_st    = fc2.selectbox("Status", ["All"] + STATUSES, key="d_st")
        search    = fc3.text_input("Search", placeholder="keyword…", key="d_search")

        view = bundle_df.copy()
        if sel_cat != "All": view = view[view["CATEGORY"] == sel_cat]
        if sel_st  != "All": view = view[view["NONPROD_STATUS"].fillna("Not Started") == sel_st]
        if search:
            mask = view["TITLE"].fillna("").str.contains(search, case=False)
            view = view[mask]

        # Sort: Action Required first, then High impact, then others
        view["_sort"] = view["NONPROD_STATUS"].map({
            "Action Required": 0, "Not Started": 1, "In Review": 2,
            "Tested": 3, "Confirmed Safe": 4, "N/A": 5
        }).fillna(1)
        view["_imp"] = view["EFFECTIVE_IMPACT"].map(
            {"High": 0, "Medium": 1, "Low": 2, "TBD": 3}
        ).fillna(2)
        view = view.sort_values(["_sort", "_imp"])

        total_v   = len(view)
        act_req   = len(view[view["NONPROD_STATUS"] == "Action Required"])
        not_start = len(view[view["NONPROD_STATUS"].fillna("Not Started") == "Not Started"])
        st.caption(
            f"**{total_v}** BCRs"
            + (f"  ·  🔴 **{act_req} Action Required**" if act_req else "")
            + (f"  ·  ⚪ {not_start} Not Started" if not_start else "")
        )

        # ── Column headers ────────────────────────────────────────────────────
        h1, h2, h3, h4, h5 = st.columns([4, 2, 1, 2, 1])
        h1.caption("BCR")
        h2.caption("Category")
        h3.caption("Impact")
        h4.caption("NONPROD Status")
        h5.caption("Docs")
        st.markdown("<hr style='margin:4px 0 6px;border-color:#eee'>", unsafe_allow_html=True)

        # ── BCR rows ──────────────────────────────────────────────────────────
        prev_cat = None
        for _, row in view.iterrows():
            cat = row.get("CATEGORY") or "Other"
            # Category divider when grouping changes
            if cat != prev_cat and sel_cat == "All":
                st.markdown(
                    f"<div style='background:#f8f9fa;padding:4px 8px;margin:8px 0 4px;"
                    f"border-radius:4px;font-size:12px;font-weight:600;color:#666'>"
                    f"{cat}</div>",
                    unsafe_allow_html=True,
                )
                prev_cat = cat

            ic       = IMPACT_COLORS.get(row["EFFECTIVE_IMPACT"], "#95a5a6")
            docs_url = row.get("DOCS_URL") or ""
            status   = row["NONPROD_STATUS"] or "Not Started"

            r1, r2, r3, r4, r5 = st.columns([4, 2, 1, 2, 1])
            r1.markdown(f"**{row['TITLE'] or row['BCR_ID']}**")
            r2.caption(cat if sel_cat != "All" else "")
            r3.markdown(
                f"<span style='background:{ic};color:white;padding:2px 6px;"
                f"border-radius:3px;font-size:11px'>{row['EFFECTIVE_IMPACT']}</span>",
                unsafe_allow_html=True,
            )
            r4.markdown(status_badge(status), unsafe_allow_html=True)
            if docs_url:
                r5.markdown(f"[↗]({docs_url})")

    # ── Unbundled changes ─────────────────────────────────────────────────────
    unbundled = df[df["UNBUNDLED"].fillna(False)].copy()
    if not unbundled.empty:
        with st.expander(f"🔗 Unbundled Changes ({len(unbundled)}) — ad-hoc outside bundle system"):
            h1, h2, h3, h4 = st.columns([4, 2, 1, 1])
            h1.caption("Change"); h2.caption("Category"); h3.caption("GE"); h4.caption("Status")
            for _, row in unbundled.iterrows():
                ic = IMPACT_COLORS.get(row["EFFECTIVE_IMPACT"], "#95a5a6")
                c1, c2, c3, c4 = st.columns([4, 2, 1, 1])
                c1.markdown(f"**{row['TITLE'] or row['BCR_ID']}**")
                c2.caption(row.get("CATEGORY") or "—")
                c3.caption(row.get("GE") or "—")
                c4.markdown(status_badge(row.get("NONPROD_STATUS")), unsafe_allow_html=True)



# =============================================================================
# PAGE: ASSESSMENT
# =============================================================================
elif page == "📋 Assessment":
    df = load_registry()

    st.markdown(f"<h1 style='color:{SF_BLUE}'>Impact Assessment</h1>", unsafe_allow_html=True)
    st.caption("Edit inline. Every field is overridable. Save persists to BCR_ASSESSMENTS.")

    fc1, fc2, fc3 = st.columns([2, 2, 2])
    bundles     = ["All"] + sorted(df["BUNDLE_ID"].dropna().unique().tolist(), reverse=True)
    sel_bundle  = fc1.selectbox("Bundle",         bundles, key="a_bundle")
    sel_status  = fc2.selectbox("NONPROD Status", ["All"] + STATUSES, key="a_status")
    show_unbund = fc3.checkbox("Include unbundled", value=True)

    disp = df.copy()
    if sel_bundle != "All": disp = disp[disp["BUNDLE_ID"] == sel_bundle]
    if sel_status != "All": disp = disp[disp["NONPROD_STATUS"] == sel_status]
    if not show_unbund:     disp = disp[~disp["UNBUNDLED"].fillna(False)]

    edit_df = disp[[
        "BCR_ID","BUNDLE_ID","CATEGORY","TITLE","EFFECTIVE_IMPACT",
        "NONPROD_STATUS","PROD_STATUS","OWNER","NOTES",
        "SIGN_OFF_DATE","CASE_ID","RISK_ACCEPTED",
    ]].copy()

    edited = st.data_editor(
        edit_df,
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        column_config={
            "BCR_ID":     st.column_config.TextColumn("BCR ID",   disabled=True, width="medium"),
            "BUNDLE_ID":  st.column_config.TextColumn("Bundle",   disabled=True, width="small"),
            "CATEGORY":   st.column_config.TextColumn("Category", disabled=True, width="medium"),
            "TITLE":      st.column_config.TextColumn("Title",    disabled=True, width="large"),
            "EFFECTIVE_IMPACT":  st.column_config.SelectboxColumn("Impact ✏️",  options=IMPACTS, width="small"),
            "NONPROD_STATUS":    st.column_config.SelectboxColumn("NONPROD ✏️", options=STATUSES, width="medium"),
            "PROD_STATUS":       st.column_config.SelectboxColumn("PROD ✏️",    options=STATUSES, width="medium"),
            "OWNER":      st.column_config.TextColumn("Owner ✏️",       width="medium"),
            "NOTES":      st.column_config.TextColumn("Notes ✏️",       width="large"),
            "SIGN_OFF_DATE": st.column_config.DateColumn("Sign-off ✏️", width="small"),
            "CASE_ID":    st.column_config.TextColumn("Case ID ✏️",     width="small"),
            "RISK_ACCEPTED": st.column_config.CheckboxColumn("Risk Accepted ✏️", width="small"),
        },
        key="assessment_editor",
    )

    sc1, sc2 = st.columns([2, 8])
    if sc1.button("💾 Save Changes", type="primary"):
        saved = 0
        errors = []
        orig_impact = {r["BCR_ID"]: r["IMPACT_DEFAULT"] for _, r in df.iterrows()}
        for _, row in edited.iterrows():
            override = row["EFFECTIVE_IMPACT"] \
                if row["EFFECTIVE_IMPACT"] != orig_impact.get(row["BCR_ID"]) else None
            try:
                session.sql(f"""
                    MERGE INTO {DB}.BCR_ASSESSMENTS t
                    USING (SELECT ? AS BCR_ID) s ON t.BCR_ID = s.BCR_ID
                    WHEN MATCHED THEN UPDATE SET
                        NONPROD_STATUS=?, PROD_STATUS=?, IMPACT_OVERRIDE=?,
                        OWNER=?, NOTES=?, SIGN_OFF_DATE=?, CASE_ID=?,
                        RISK_ACCEPTED=?, LAST_UPDATED_BY=CURRENT_USER(),
                        LAST_UPDATED_AT=CURRENT_TIMESTAMP()
                    WHEN NOT MATCHED THEN INSERT
                        (BCR_ID,BUNDLE_ID,NONPROD_STATUS,PROD_STATUS,IMPACT_OVERRIDE,
                         OWNER,NOTES,SIGN_OFF_DATE,CASE_ID,RISK_ACCEPTED)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                """, [
                    row["BCR_ID"],
                    row["NONPROD_STATUS"], row["PROD_STATUS"], override,
                    row["OWNER"], row["NOTES"],
                    str(row["SIGN_OFF_DATE"]) if pd.notna(row.get("SIGN_OFF_DATE")) else None,
                    row["CASE_ID"], bool(row["RISK_ACCEPTED"]),
                    row["BCR_ID"], row["BUNDLE_ID"],
                    row["NONPROD_STATUS"], row["PROD_STATUS"], override,
                    row["OWNER"], row["NOTES"],
                    str(row["SIGN_OFF_DATE"]) if pd.notna(row.get("SIGN_OFF_DATE")) else None,
                    row["CASE_ID"], bool(row["RISK_ACCEPTED"]),
                ]).collect()
                saved += 1
            except Exception as e:
                errors.append(f"{row['BCR_ID']}: {e}")
        if errors:
            st.error(f"{len(errors)} errors:\n" + "\n".join(errors[:3]))
        else:
            st.success(f"Saved {saved} assessments.")
            load_registry.clear()
            st.rerun()

    if sc2.button("📥 Export CSV"):
        st.download_button(
            "Download",
            edited.to_csv(index=False).encode(),
            f"bcr_assessment_{date.today()}.csv",
            "text/csv",
        )


# =============================================================================
# PAGE: DETECTION LAB
# =============================================================================
elif page == "🔬 Detection Lab":
    df = load_registry()

    st.markdown(f"<h1 style='color:{SF_BLUE}'>Detection Lab</h1>", unsafe_allow_html=True)

    # ── Query window selector ─────────────────────────────────────────────────
    # Shown at the top — affects templates, Cortex prompts, and query execution.
    # Critical for large accounts: QUERY_HISTORY can have millions of rows.
    hdr1, hdr2 = st.columns([3, 2])
    with hdr1:
        st.caption(
            "Write or generate SQL to detect if your account is affected by each BCR. "
            "Queries run against ACCOUNT_USAGE / INFORMATION_SCHEMA."
        )
    with hdr2:
        window_label = st.radio(
            "Query window",
            ["Last 1 day", "Last 7 days", "Last 30 days"],
            index=1,
            horizontal=True,
            help=(
                "Limits DATEADD lookback in QUERY_HISTORY. "
                "Use '1 day' on large accounts to avoid scanning millions of rows. "
                "Applied automatically to templates and Cortex-generated queries."
            ),
        )
    WINDOW_DAYS = {"Last 1 day": 1, "Last 7 days": 7, "Last 30 days": 30}
    days = WINDOW_DAYS[window_label]
    st.caption(
        f"⚠️ Window: **{window_label}** ({days}d). "
        f"Increase only if you need a broader history scan."
        if days <= 1 else
        f"Window: **{window_label}** — templates and Cortex queries use `DATEADD('day', -{days}, CURRENT_DATE())`."
    )

    dq_df  = load_detection_queries()
    dq_map = {r["BCR_ID"]: r for _, r in dq_df.iterrows()}

    # Bundle filter first, then BCR select
    bundles    = sorted(df["BUNDLE_ID"].dropna().unique().tolist(), reverse=True)
    sel_bundle = st.selectbox("Bundle", bundles, key="det_bundle")
    bundle_df  = df[df["BUNDLE_ID"] == sel_bundle]
    bcr_opts   = bundle_df["BCR_ID"].tolist()
    bcr_labels = {r["BCR_ID"]: f"{r['CATEGORY']} — {r['TITLE'] or r['BCR_ID']}"
                  for _, r in bundle_df.iterrows()}

    if not bcr_opts:
        st.info("No BCRs found for this bundle.")
        st.stop()

    sel_bcr = st.selectbox("BCR", options=bcr_opts, format_func=lambda x: bcr_labels.get(x, x))

    if not sel_bcr:
        st.stop()

    bcr_row = bundle_df[bundle_df["BCR_ID"] == sel_bcr].iloc[0]
    dq_row  = dq_map.get(sel_bcr)

    # ── BCR-specific session state key ────────────────────────────────────────
    # Using a per-BCR key prevents stale SQL from a previous BCR appearing
    # in the editor when the user switches BCRs.
    sql_key = f"sql_{sel_bcr.replace('/', '_').replace('-', '_')}"
    if sql_key not in st.session_state:
        st.session_state[sql_key] = dq_row["DETECTION_SQL"] \
            if dq_row is not None and pd.notna(dq_row.get("DETECTION_SQL")) else ""

    # Show Cortex success banner that survives st.rerun()
    if st.session_state.pop("_cortex_ok", False):
        st.success("✅ SQL generated by Cortex and loaded into the editor below.")

    title_display = bcr_row['TITLE'] or bcr_row['BCR_ID']
    desc_display  = bcr_row['DESCRIPTION'] or ""
    category      = bcr_row.get("CATEGORY", "") or ""
    docs_url      = bcr_row.get("DOCS_URL", "") or ""
    impact        = bcr_row.get("EFFECTIVE_IMPACT", "TBD") or "TBD"
    ebd           = bcr_row.get("EBD", "") or ""

    # ── BCR Card ──────────────────────────────────────────────────────────────
    ic = IMPACT_COLORS.get(impact, "#95a5a6")
    ebd_label = f"EBD: {ebd}" if ebd else "EBD: TBD"

    st.markdown(
        f"""<div style='border-left:4px solid {ic};padding:10px 16px;
            background:#fafafa;border-radius:0 6px 6px 0;margin-bottom:8px'>
        <div style='font-size:17px;font-weight:700'>{title_display}</div>
        <div style='font-size:12px;color:#666;margin-top:4px'>
            {category} &nbsp;|&nbsp; {sel_bundle} &nbsp;|&nbsp;
            <span style='background:{ic};color:white;padding:1px 7px;
                border-radius:3px;font-size:11px'>{impact}</span>
            &nbsp;|&nbsp; {ebd_label}
            {'&nbsp;|&nbsp;<a href="' + docs_url + '" target="_blank">📄 Snowflake Docs ↗</a>'
             if docs_url else ''}
        </div>
        </div>""",
        unsafe_allow_html=True,
    )

    # ── Structured BCR content: Before / After / What to do ──────────────────
    secs = parse_bcr_sections(desc_display)

    if secs["before"] or secs["after"]:
        # ── Before / After side by side ───────────────────────────────────
        bc, ac = st.columns(2)
        with bc:
            st.markdown(
                "<div style='background:#fff3f3;border-left:4px solid #e74c3c;"
                "padding:8px 12px;border-radius:0 4px 4px 0;margin-bottom:4px'>"
                "<b style='color:#e74c3c;font-size:13px'>⬛ Before the change</b></div>",
                unsafe_allow_html=True,
            )
            st.markdown(secs["before"])
        with ac:
            st.markdown(
                "<div style='background:#f0fff4;border-left:4px solid #27ae60;"
                "padding:8px 12px;border-radius:0 4px 4px 0;margin-bottom:4px'>"
                "<b style='color:#27ae60;font-size:13px'>✅ After the change</b></div>",
                unsafe_allow_html=True,
            )
            st.markdown(secs["after"])

        # ── What you need to do ───────────────────────────────────────────
        if secs["what_to_do"]:
            st.markdown(
                "<div style='background:#fff8e1;border-left:4px solid #f39c12;"
                "padding:8px 12px;border-radius:0 4px 4px 0;margin:8px 0 4px'>"
                "<b style='color:#e67e22;font-size:13px'>🔧 What you need to do</b></div>",
                unsafe_allow_html=True,
            )
            st.markdown(secs["what_to_do"])

        # ── Code examples from docs ───────────────────────────────────────
        if secs["code_examples"]:
            st.markdown("**📋 SQL examples from Snowflake docs** *(basis for detection)*")
            for i, ex in enumerate(secs["code_examples"]):
                st.code(ex, language="sql")

            # Offer to build detection query from docs examples
            if secs["sql_functions"] or secs["code_examples"]:
                # Build a targeted QUERY_HISTORY search from the identified patterns
                patterns = secs["sql_functions"]
                if not patterns and secs["code_examples"]:
                    # Extract first meaningful token from code examples as fallback
                    first_line = secs["code_examples"][0].split('\n')[0]
                    tok = re.search(r'\b([A-Z_]{3,})\s*\(', first_line, re.IGNORECASE)
                    if tok:
                        patterns = [tok.group(1).upper()]

                if patterns:
                    ilike_clauses = "\n    OR ".join(
                        f"QUERY_TEXT ILIKE '%{p.split()[0]}%'" for p in patterns
                    )
                    detection_from_docs = (
                        f"-- Detection query built from Snowflake's own docs examples\n"
                        f"-- Patterns identified: {', '.join(patterns)}\n\n"
                        f"SELECT QUERY_ID, QUERY_TEXT, START_TIME, USER_NAME, WAREHOUSE_NAME\n"
                        f"FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY\n"
                        f"WHERE (\n"
                        f"    {ilike_clauses}\n"
                        f")\n"
                        f"  AND START_TIME >= DATEADD('day', -{days}, CURRENT_DATE())\n"
                        f"  AND EXECUTION_STATUS = 'SUCCESS'\n"
                        f"ORDER BY START_TIME DESC\n"
                        f"LIMIT 200;"
                    )
                    if st.button(
                        f"⚡ Load detection SQL from docs examples ({', '.join(patterns[:2])})",
                        key="load_from_docs",
                        help="Builds a QUERY_HISTORY search based on the SQL patterns in Snowflake's own docs",
                    ):
                        st.session_state[sql_key] = detection_from_docs
                        st.rerun()

        if docs_url:
            st.markdown(f"[View full BCR on Snowflake Docs ↗]({docs_url})")

    elif desc_display:
        st.caption(desc_display[:300] + ("…" if len(desc_display) > 300 else ""))
        if docs_url:
            st.markdown(f"[View full BCR on Snowflake Docs ↗]({docs_url})")
    else:
        if docs_url:
            st.info(
                f"No description loaded yet — [view BCR on Snowflake Docs ↗]({docs_url})  \n"
                f"Run **Settings → 📖 Enrich Descriptions** to fetch Before/After content."
            )
        else:
            st.info("Run **Settings → 📖 Enrich Descriptions** to fetch Before/After content.")

    # ── COE Impact Brief ──────────────────────────────────────────────────────
    # Cached per BCR in session state — one Cortex call, reused across rerenders.
    # This is the primary tool for a Platform COE lead to assess impact quickly.
    brief_key = f"brief_{sel_bcr.replace('/', '_').replace('-', '_')}"
    brief = st.session_state.get(brief_key)

    with st.expander("🏢 COE Impact Brief", expanded=brief is not None):
        if brief is None:
            st.caption(
                "Generate a structured impact brief for this BCR: plain-English explanation, "
                "affected-if/safe-if conditions, detection hint, and recommended action. "
                "Uses the full BCR description — run Enrich Descriptions first for best results."
            )
            if st.button("Generate COE Impact Brief", type="primary"):
                coe_prompt = (
                    f"You are a Platform COE lead at a large enterprise using Snowflake. "
                    f"A Snowflake Behavior Change Release is upcoming.\n\n"
                    f"BCR Title: {title_display}\n"
                    f"Category: {category}\n"
                    f"Impact: {impact}\n"
                    f"EBD: {ebd or 'TBD'}\n"
                    f"Full description from Snowflake docs:\n{desc_display or title_display}\n\n"
                    f"Generate a COE impact brief in EXACTLY this key: value format, one per line:\n"
                    f"PLAIN_ENGLISH: [1-2 sentences - what Snowflake is changing, no jargon]\n"
                    f"AFFECTED_IF: [specific condition — what exact query pattern / workload / config means you're impacted]\n"
                    f"SAFE_IF: [when this change has zero impact on your account]\n"
                    f"DETECTION_VIEW: [the single best ACCOUNT_USAGE view or INFORMATION_SCHEMA to query, e.g. QUERY_HISTORY]\n"
                    f"DETECTION_KEYWORD: [exact keyword or function name to ILIKE search in QUERY_TEXT, e.g. COPY_HISTORY]\n"
                    f"PRIORITY: [HIGH / MEDIUM / LOW based on blast radius and likelihood of impact]\n"
                    f"ACTION: [the single most important concrete action a DBA should take before the EBD]\n"
                    f"SNOWFLAKE_DIAGNOSTIC: [copy the 'Suggested diagnostic steps' or 'Customer readiness' text from the description above, if present. Otherwise write NONE]"
                )
                with st.spinner("Cortex is generating your COE Impact Brief…"):
                    try:
                        raw = session.sql(
                            "SELECT SNOWFLAKE.CORTEX.COMPLETE('mistral-large2', ?)",
                            [coe_prompt]
                        ).collect()[0][0]
                        parsed = {}
                        for line in strip_sql_fences(raw).splitlines():
                            if ":" in line:
                                k, _, v = line.partition(":")
                                parsed[k.strip().upper()] = v.strip()
                        st.session_state[brief_key] = parsed
                        st.rerun()
                    except Exception as e:
                        st.error(f"Cortex error: {e}")
        else:
            # Render the COE brief
            priority = brief.get("PRIORITY", "").upper()
            p_color  = {"HIGH": "#e74c3c", "MEDIUM": "#f39c12", "LOW": "#27ae60"}.get(priority, "#95a5a6")

            # Summary row
            pc1, pc2, pc3 = st.columns([1, 1, 1])
            pc1.markdown(
                f"<span style='background:{p_color};color:white;padding:4px 12px;"
                f"border-radius:4px;font-weight:700'>Priority: {priority or 'TBD'}</span>",
                unsafe_allow_html=True,
            )
            dview = brief.get("DETECTION_VIEW", "")
            if dview:
                pc2.markdown(f"**Query:** `{dview}`")
            dkw = brief.get("DETECTION_KEYWORD", "")
            if dkw:
                pc3.markdown(f"**Keyword:** `{dkw}`")

            st.divider()

            if brief.get("PLAIN_ENGLISH"):
                st.markdown(f"**📌 What is changing:** {brief['PLAIN_ENGLISH']}")
            col_a, col_b = st.columns(2)
            with col_a:
                if brief.get("AFFECTED_IF"):
                    st.error(f"**⚠️ You ARE affected if:**\n\n{brief['AFFECTED_IF']}")
            with col_b:
                if brief.get("SAFE_IF"):
                    st.success(f"**✅ You are SAFE if:**\n\n{brief['SAFE_IF']}")

            if brief.get("ACTION"):
                st.warning(f"**🔧 Recommended action:** {brief['ACTION']}")

            # Snowflake's own diagnostic steps (from the docs page)
            snowflake_diag = brief.get("SNOWFLAKE_DIAGNOSTIC", "NONE")
            if snowflake_diag and snowflake_diag.upper() != "NONE":
                st.info(f"**📋 Snowflake's suggested diagnostic steps:**\n\n{snowflake_diag}")

            # One-click: pre-load detection SQL from COE brief
            if dkw and dview:
                if st.button(
                    f"⚡ Build detection SQL from this brief ({dkw} in {dview})",
                    help="Auto-populates the editor below with a detection query based on the COE brief"
                ):
                    keyword_sql = (
                        f"-- Detection query based on COE Impact Brief\n"
                        f"-- Looking for: {dkw}\n"
                        f"-- Source: {dview}\n\n"
                        f"SELECT QUERY_ID, QUERY_TEXT, START_TIME, USER_NAME, WAREHOUSE_NAME\n"
                        f"FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY\n"
                        f"WHERE (\n"
                        f"    QUERY_TEXT ILIKE '%{dkw}%'\n"
                        f")\n"
                        f"  AND START_TIME >= DATEADD('day', -{days}, CURRENT_DATE())\n"
                        f"  AND EXECUTION_STATUS = 'SUCCESS'\n"
                        f"ORDER BY START_TIME DESC\n"
                        f"LIMIT 200;"
                        if "QUERY_HISTORY" in dview.upper() else
                        f"-- Detection query based on COE Impact Brief\n"
                        f"-- Looking for: {dkw}\n"
                        f"-- Source: {dview}\n\n"
                        f"SELECT *\n"
                        f"FROM SNOWFLAKE.ACCOUNT_USAGE.{dview.upper().split('.')[-1]}\n"
                        f"WHERE DELETED_ON IS NULL\n"
                        f"LIMIT 200;"
                    )
                    st.session_state[sql_key] = keyword_sql
                    st.rerun()

            # Allow regenerating
            if st.button("↺ Regenerate", help="Regenerate the COE brief"):
                del st.session_state[brief_key]
                st.rerun()

    st.divider()

    TEMPLATES = {
        "SQL Changes": (
            f"-- Detect queries using patterns affected by this SQL change\n"
            f"-- Update the ILIKE pattern to match the specific syntax from the BCR title\n"
            f"SELECT QUERY_ID, QUERY_TEXT, START_TIME, USER_NAME, WAREHOUSE_NAME\n"
            f"FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY\n"
            f"WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_DATE())\n"
            f"  AND EXECUTION_STATUS = 'SUCCESS'\n"
            f"  AND QUERY_TEXT ILIKE '%JOIN%USING%'  -- update pattern for this BCR\n"
            f"ORDER BY START_TIME DESC\n"
            f"LIMIT 200;"
        ),
        "Security": (
            f"-- Detect accounts/users/roles affected by this security change\n"
            f"SELECT GRANTEE_NAME, GRANTED_ON, NAME, PRIVILEGE, GRANTED_BY\n"
            f"FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_ROLES\n"
            f"WHERE DELETED_ON IS NULL\n"
            f"ORDER BY GRANTED_ON DESC\n"
            f"LIMIT 200;"
        ),
        "Data Lake": (
            f"-- Detect Iceberg tables that may be affected\n"
            f"SELECT TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE, CREATED\n"
            f"FROM INFORMATION_SCHEMA.TABLES\n"
            f"WHERE TABLE_TYPE ILIKE '%ICEBERG%'\n"
            f"ORDER BY CREATED DESC;"
        ),
        "Warehouse": (
            f"-- Detect warehouses affected by this change\n"
            f"SELECT NAME, SIZE, TYPE, AUTO_SUSPEND, RESOURCE_MONITOR\n"
            f"FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSES\n"
            f"WHERE DELETED_ON IS NULL\n"
            f"ORDER BY NAME;"
        ),
        "Data Pipeline": (
            f"-- Detect Snowpipe / task objects that may be affected\n"
            f"SELECT PIPE_CATALOG, PIPE_SCHEMA, PIPE_NAME, DEFINITION, CREATED\n"
            f"FROM INFORMATION_SCHEMA.PIPES\n"
            f"ORDER BY CREATED DESC;"
        ),
        "Usage Views": (
            f"-- Detect queries that SELECT from the affected view/function\n"
            f"SELECT QUERY_ID, QUERY_TEXT, START_TIME, USER_NAME\n"
            f"FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY\n"
            f"WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_DATE())\n"
            f"  AND QUERY_TEXT ILIKE '%QUERY_HISTORY%'  -- update view name for this BCR\n"
            f"ORDER BY START_TIME DESC\n"
            f"LIMIT 200;"
        ),
    }
    # Pick closest matching template
    template_sql = ""
    for key, sql in TEMPLATES.items():
        if key.lower() in category.lower():
            template_sql = sql
            break
    if not template_sql:
        template_sql = TEMPLATES["SQL Changes"]  # default

    # ── Workflow guide ────────────────────────────────────────────────────────
    with st.expander("ℹ️ How to use Detection Lab", expanded=False):
        st.markdown("""
**Workflow — follow these steps in order:**

| Step | Button | What it does |
|---|---|---|
| **1** | 📋 **Load Template** | Inserts a pre-built SQL query matched to this BCR's category (SQL Changes, Security, Iceberg, etc.). Use this as your starting point — it queries the right ACCOUNT_USAGE view with the selected time window. |
| **2** | ✏️ **Edit the SQL** | Update the `ILIKE` pattern or conditions in the editor to match the specific syntax/object in this BCR's title. The template is a starting point, not a final answer. |
| **2b** | ⚡ **Generate via Cortex** | Alternative to manual editing — AI reads the BCR description and writes a more specific query. Works best after **Settings → Enrich Descriptions** has been run. Replaces whatever is in the editor. |
| **3** | 💾 **Save SQL** | Saves the current editor contents to the database. Saved queries persist across sessions. |
| **4** | ✅ **Approve** | Marks the query as reviewed and ready for use. Sets `APPROVED = TRUE` — useful for team workflows where a DBA reviews before running in PROD. |
| **5** | ▶️ **Run Detection** | Executes the saved/edited SQL against `ACCOUNT_USAGE` / `INFORMATION_SCHEMA`. The selected query window (1/7/30 days) is applied at run-time — you don't need to edit the SQL to change the window. |

**Important:** Load Template and Generate via Cortex both overwrite the editor.
Save your edits before clicking either if you want to keep them.
        """)

    col_sql, col_meta = st.columns([3, 1])

    with col_meta:
        # Query status
        if dq_row is not None:
            gen_by   = dq_row.get("GENERATED_BY", "manual")
            approved = dq_row.get("APPROVED", False)
            st.markdown(f"**Source:** `{gen_by}`")
            st.markdown(f"**Approved:** {'✅ Yes' if approved else '❌ No'}")
            if dq_row.get("APPROVED_BY"):
                st.caption(f"By: {dq_row['APPROVED_BY']}")
        else:
            st.caption("No query saved yet.")

        st.divider()

        # Step 1 — Load Template
        st.markdown("**Step 1 — Starting point**")
        if st.button(
            "📋 Load Template",
            use_container_width=True,
            help=(
                f"Inserts a {category.split('—')[0].strip() or 'category'}-matched SQL query "
                f"using the {days}-day window. Edit the ILIKE pattern to match this BCR."
            ),
        ):
            st.session_state[sql_key] = template_sql
            st.rerun()

        # Step 2b — Generate via Cortex
        st.markdown("**Step 2b — AI-assisted (optional)**")
        if st.button(
            "⚡ Generate via Cortex",
            use_container_width=True,
            help=(
                "Cortex reads the BCR title + description and writes a targeted SQL query. "
                "Run Settings → Enrich Descriptions first for best results. "
                "This REPLACES the current editor content."
            ),
        ):
            secs_for_cortex = parse_bcr_sections(desc_display)
            # Build a context-rich prompt using structured sections
            # The "What you need to do" section + code examples are the highest-quality
            # signal — they're written by Snowflake engineers who know exactly what breaks
            what_to_do_ctx = (
                f"\nSnowflake's 'What you need to do' guidance:\n{secs_for_cortex['what_to_do']}"
                if secs_for_cortex.get("what_to_do") else ""
            )
            examples_ctx = ""
            if secs_for_cortex.get("code_examples"):
                examples_ctx = "\nSQL examples from Snowflake docs (search for queries using these patterns):\n"
                examples_ctx += "\n---\n".join(secs_for_cortex["code_examples"][:3])

            prompt = (
                f"You are a Snowflake SQL expert writing impact detection queries.\n\n"
                f"Snowflake BCR: {title_display}\n"
                f"Category: {category}\n\n"
                f"Before the change:\n{secs_for_cortex.get('before') or 'see title'}\n\n"
                f"After the change:\n{secs_for_cortex.get('after') or 'see title'}\n"
                f"{what_to_do_ctx}\n"
                f"{examples_ctx}\n\n"
                f"Task: Write a Snowflake SQL query that searches SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY "
                f"for queries in this account that match the patterns shown in the docs examples above. "
                f"If the docs show a function like TO_CHAR or a clause like JOIN...USING, search "
                f"QUERY_TEXT with ILIKE for those exact patterns.\n\n"
                f"Rules:\n"
                f"- Use DATEADD('day', -{days}, CURRENT_DATE()) for START_TIME\n"
                f"- Wrap multiple OR conditions in parentheses\n"
                f"- Add LIMIT 200\n"
                f"- Return ONLY valid Snowflake SQL. No markdown fences. No explanation."
            )
            with st.spinner("Asking Cortex…"):
                try:
                    raw = session.sql(
                        "SELECT SNOWFLAKE.CORTEX.COMPLETE('mistral-large2', ?)", [prompt]
                    ).collect()[0][0]
                    # Strip markdown fences — Cortex wraps output in ```sql...```
                    # even when told not to, causing SQL parse errors on execution
                    generated = strip_sql_fences(raw)
                    # Save to DB
                    session.sql(f"""
                        MERGE INTO {DB}.BCR_DETECTION_QUERIES t
                        USING (SELECT ? AS BID) s ON t.BCR_ID = s.BID
                        WHEN MATCHED THEN UPDATE SET
                            DETECTION_SQL = ?, GENERATED_BY = 'cortex',
                            APPROVED = FALSE, UPDATED_AT = CURRENT_TIMESTAMP()
                        WHEN NOT MATCHED THEN INSERT
                            (BCR_ID, DETECTION_SQL, GENERATED_BY, APPROVED)
                        VALUES (?, ?, 'cortex', FALSE)
                    """, [sel_bcr, generated, sel_bcr, generated]).collect()
                    load_detection_queries.clear()
                    # Update session state then rerun so the text_area picks up the new SQL.
                    # Without rerun, Streamlit widgets capture session state at the START of the
                    # render cycle — setting it mid-run won't update the text_area this cycle.
                    st.session_state[sql_key] = generated
                    st.session_state["_cortex_ok"] = True
                    st.rerun()
                except Exception as e:
                    st.error(f"Cortex error: {e}")

    with col_sql:
        sql_input = st.text_area(
            "✏️ Step 2 — Edit SQL (load a template or generate via Cortex, then customise here)",
            key=sql_key,
            height=320,
            help=(
                "Edit the SQL directly. "
                "Update ILIKE patterns to match the specific syntax in this BCR's title. "
                "The query window selector above controls the DATEADD lookback at run-time."
            ),
        )

    act1, act2, act3 = st.columns([2, 2, 2])

    if act1.button(
        "💾 Step 3 — Save SQL",
        help="Persists the current editor contents. Saved queries reload next session.",
    ):
        if not sql_input.strip():
            st.warning("Nothing to save.")
        else:
            try:
                session.sql(f"""
                    MERGE INTO {DB}.BCR_DETECTION_QUERIES t
                    USING (SELECT ? AS BID) s ON t.BCR_ID = s.BID
                    WHEN MATCHED THEN UPDATE SET
                        DETECTION_SQL = ?, GENERATED_BY = ?,
                        UPDATED_AT = CURRENT_TIMESTAMP()
                    WHEN NOT MATCHED THEN INSERT
                        (BCR_ID, DETECTION_SQL, GENERATED_BY, APPROVED)
                    VALUES (?, ?, ?, FALSE)
                """, [
                    sel_bcr, sql_input,
                    dq_row["GENERATED_BY"] if dq_row is not None else "manual",
                    sel_bcr, sql_input,
                    dq_row["GENERATED_BY"] if dq_row is not None else "manual",
                ]).collect()
                load_detection_queries.clear()
                st.success("SQL saved.")
            except Exception as e:
                st.error(f"Save error: {e}")

    if act2.button(
        "✅ Step 4 — Approve",
        help="Marks this query as reviewed by a DBA. Approved queries are flagged for PROD use.",
    ):
        try:
            session.sql(f"""
                UPDATE {DB}.BCR_DETECTION_QUERIES
                SET APPROVED = TRUE, APPROVED_BY = CURRENT_USER(),
                    UPDATED_AT = CURRENT_TIMESTAMP()
                WHERE BCR_ID = ?
            """, [sel_bcr]).collect()
            load_detection_queries.clear()
            st.success("Approved.")
        except Exception as e:
            st.error(f"Approve error: {e}")

    if act3.button(
        "▶️ Step 5 — Run Detection",
        type="primary",
        help=(
            f"Runs the SQL against ACCOUNT_USAGE / INFORMATION_SCHEMA. "
            f"The {days}-day window is applied automatically — "
            f"you don't need to edit the SQL to change the window."
        ),
    ):
        if not sql_input.strip() or sql_input.strip().startswith("--"):
            st.warning("No executable SQL. Generate or write a detection query first.")
        else:
            # Apply the selected query window at run-time.
            # Replaces any existing DATEADD day value so saved queries respect
            # the current window selection without needing to re-save the SQL.
            sql_to_run = re.sub(
                r"DATEADD\s*\(\s*'day'\s*,\s*-\d+\s*,",
                f"DATEADD('day', -{days},",
                sql_input,
                flags=re.IGNORECASE,
            )
            if sql_to_run != sql_input:
                st.caption(f"ℹ️ Query window adjusted to {days}d at run-time.")

            with st.spinner(f"Running against ACCOUNT_USAGE (last {days}d)…"):
                try:
                    results = session.sql(sql_to_run).to_pandas()
                    count   = len(results)
                    # Use SELECT instead of VALUES — PARSE_JSON(?) in a VALUES clause
                    # causes "Invalid expression" because Snowflake can't resolve the
                    # bind parameter type at compile time. SELECT resolves it correctly.
                    session.sql(f"""
                        INSERT INTO {DB}.BCR_DETECTION_RESULTS
                            (BCR_ID, AFFECTED_COUNT, AFFECTED_OBJECTS, SIGNAL_SUMMARY)
                        SELECT ?, ?, PARSE_JSON(?), ?
                    """, [
                        sel_bcr, count,
                        results.head(100).to_json(orient="records"),
                        f"{count} affected object(s) found (last {days}d)",
                    ]).collect()
                    load_detection_queries.clear()
                    if count > 0:
                        st.warning(f"⚠️ {count} affected objects found (last {days}d)")
                    else:
                        st.success(f"✅ No affected objects found in this account (last {days}d).")
                    st.dataframe(results, use_container_width=True)
                except Exception as e:
                    error_str = str(e)
                    st.error(f"Query error: {error_str}")
                    # Store failed SQL + error so user can request Cortex fix
                    st.session_state["_failed_sql"]   = sql_to_run
                    st.session_state["_failed_error"] = error_str

    # ── Auto-fix banner (shown after a run error) ─────────────────────────────
    if "_failed_sql" in st.session_state and "_failed_error" in st.session_state:
        st.warning(
            f"The last query failed. Click below to let Cortex diagnose and fix the SQL."
        )
        if st.button("🔧 Auto-fix with Cortex", type="primary"):
            fix_prompt = (
                f"Fix this Snowflake SQL that returned an error.\n\n"
                f"Error:\n{st.session_state['_failed_error']}\n\n"
                f"SQL:\n{st.session_state['_failed_sql']}\n\n"
                f"Return ONLY the corrected Snowflake SQL. "
                f"No explanation. No markdown fences. "
                f"Ensure AND/OR operator precedence is correct. "
                f"Use ILIKE for text matching. Add LIMIT 200."
            )
            with st.spinner("Cortex is fixing the SQL…"):
                try:
                    fixed_raw = session.sql(
                        "SELECT SNOWFLAKE.CORTEX.COMPLETE('mistral-large2', ?)",
                        [fix_prompt]
                    ).collect()[0][0]
                    fixed = strip_sql_fences(fixed_raw)
                    st.session_state[sql_key] = fixed
                    del st.session_state["_failed_sql"]
                    del st.session_state["_failed_error"]
                    st.session_state["_cortex_ok"] = True
                    st.rerun()
                except Exception as fix_e:
                    st.error(f"Fix attempt failed: {fix_e}")

    # Recent run history
    st.divider()
    st.subheader("Detection History")
    try:
        hist = session.sql(f"""
            SELECT RUN_AT, AFFECTED_COUNT, SIGNAL_SUMMARY, RUN_BY
            FROM {DB}.BCR_DETECTION_RESULTS
            WHERE BCR_ID = ?
            ORDER BY RUN_AT DESC LIMIT 10
        """, [sel_bcr]).to_pandas()
        if hist.empty:
            st.info("No detection runs yet for this BCR.")
        else:
            st.dataframe(hist, use_container_width=True, hide_index=True)
    except Exception as e:
        st.warning(f"Could not load history: {e}")


# =============================================================================
# PAGE: REGRESSION MONITOR
# =============================================================================
elif page == "📈 Regression":
    st.markdown(f"<h1 style='color:{SF_BLUE}'>Regression Monitor</h1>", unsafe_allow_html=True)
    st.caption("Tracks daily error rates from ACCOUNT_USAGE.QUERY_HISTORY to surface BCR-related breakage.")

    col_chart, col_controls = st.columns([3, 1])

    with col_controls:
        threshold_pct = st.slider("Alert threshold (%)", 0.0, 10.0, 2.0, 0.1)
        if st.button("Run Snapshot Now"):
            with st.spinner("Running…"):
                try:
                    r = session.sql(f"CALL {DB}.RUN_REGRESSION_SNAPSHOT()").collect()[0][0]
                    st.success(r)
                    load_regression_snapshots.clear()
                    st.rerun()
                except Exception as e:
                    st.error(str(e))

    with col_chart:
        st.subheader("Error Rate — Last 30 Days (Live)")
        try:
            live = session.sql("""
                SELECT DATE_TRUNC('day', START_TIME)::DATE              AS DAY,
                       COUNT(*)                                          AS TOTAL,
                       COUNT_IF(ERROR_CODE IS NOT NULL)                  AS ERRORS,
                       ROUND(DIV0(COUNT_IF(ERROR_CODE IS NOT NULL)::FLOAT,
                                  COUNT(*)) * 100, 2)                   AS ERROR_RATE_PCT
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                WHERE START_TIME >= DATEADD('day', -30, CURRENT_DATE())
                GROUP BY 1 ORDER BY 1
            """).to_pandas()

            if live.empty:
                st.info("No query history available yet (ACCOUNT_USAGE has ~1h latency).")
            else:
                chart = (
                    alt.Chart(live)
                    .mark_area(line={"color": SF_BLUE},
                               color=alt.Gradient(
                                   gradient="linear",
                                   stops=[alt.GradientStop(color=SF_BLUE, offset=0),
                                          alt.GradientStop(color="white",   offset=1)],
                                   x1=1, x2=1, y1=1, y2=0))
                    .encode(
                        x=alt.X("DAY:T", title="Date"),
                        y=alt.Y("ERROR_RATE_PCT:Q", title="Error Rate (%)"),
                        tooltip=["DAY:T", "TOTAL:Q", "ERRORS:Q", "ERROR_RATE_PCT:Q"],
                    ).properties(height=260)
                )
                st.altair_chart(chart, use_container_width=True)

                mean_r = live["ERROR_RATE_PCT"].mean()
                std_r  = live["ERROR_RATE_PCT"].std()
                anomalies = live[live["ERROR_RATE_PCT"] > mean_r + 2 * std_r]
                if not anomalies.empty:
                    st.warning(f"⚠️ {len(anomalies)} days with anomalous error rates detected")
                    st.dataframe(anomalies, use_container_width=True, hide_index=True)
                else:
                    st.success("✅ No anomalous spikes detected in the last 30 days.")
        except Exception as e:
            st.error(f"Could not query ACCOUNT_USAGE: {e}")


# =============================================================================
# PAGE: SETTINGS
# =============================================================================
elif page == "⚙️ Settings":
    st.markdown(f"<h1 style='color:{SF_BLUE}'>Settings</h1>", unsafe_allow_html=True)

    # ── Active bundle status from SYSTEM$ ─────────────────────────────────────
    st.subheader("Active Bundles (from Snowflake)")
    st.caption("Driven by `SYSTEM$SHOW_ACTIVE_BEHAVIOR_CHANGE_BUNDLES()` — no manual configuration needed.")
    active = load_active_bundles()
    if active:
        rows = []
        for b in active:
            rows.append({
                "Bundle": b.get("name"),
                "Status": bundle_status_from_flags(b.get("isDefault", False), b.get("isEnabled", False)),
                "isEnabled":   b.get("isEnabled"),
                "isDefault":   b.get("isDefault"),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.warning("Could not read SYSTEM$ function.")

    if st.button("⟳ Sync All Active Bundles", type="primary"):
        with st.spinner("Syncing…"):
            try:
                result = session.sql(f"CALL {DB}.SYNC_ACTIVE_BUNDLES()").collect()[0][0]
                for line in result.split("\n"):
                    st.markdown(line)
                clear_all_cache()
                st.rerun()
            except Exception as e:
                st.error(str(e))

    # Load a specific historical bundle manually
    st.divider()
    st.subheader("Load Historical Bundle")
    st.caption("Active bundles are auto-synced weekly. Use this to load older bundles (e.g. 2025_07).")
    hcol1, hcol2 = st.columns([2, 2])
    hist_id = hcol1.text_input("Bundle ID", placeholder="e.g. 2025_07")
    hist_status = hcol2.selectbox(
        "Status", ["Enforced", "Disabled by Default", "Enabled by Default", "Draft"]
    )
    if st.button("Load Bundle"):
        if not hist_id.strip() or not re.match(r"^\d{4}_\d{2}$", hist_id.strip()):
            st.error("Invalid bundle ID format. Use YYYY_NN e.g. 2025_07")
        else:
            with st.spinner(f"Fetching {hist_id}…"):
                try:
                    res = session.sql(
                        f"CALL {DB}.FETCH_BCR_BUNDLE(?, ?)",
                        [hist_id.strip(), hist_status]
                    ).collect()[0][0]
                    st.markdown(f"**{hist_id}:** {res}")
                    clear_all_cache()
                except Exception as e:
                    st.error(str(e))

    st.divider()

    # ── Backfill descriptions (one-time / repair tool) ────────────────────────
    st.subheader("Backfill BCR Descriptions")
    st.caption(
        "**You should not need this regularly.** "
        "The weekly sync (⟳ Sync Now) already fetches Before/After content for every new BCR automatically. "
        "Use this only to fix BCRs that have empty or corrupted descriptions "
        "— for example, after the initial setup or after a parser fix was deployed."
    )
    enrich_n = st.number_input("Max BCRs to backfill", min_value=1, max_value=100, value=20)
    if st.button("🔧 Backfill Empty Descriptions"):
        with st.spinner(f"Fetching individual BCR pages for up to {enrich_n} BCRs with missing descriptions…"):
            try:
                res = session.sql(
                    f"CALL {DB}.ENRICH_BCR_DESCRIPTIONS(?)", [int(enrich_n)]
                ).collect()[0][0]
                st.success(res)
                clear_all_cache()
            except Exception as e:
                st.error(str(e))

    # ── Add Unbundled BCR ─────────────────────────────────────────────────────
    st.divider()
    st.subheader("Add Unbundled BCR")
    st.caption(
        "Unbundled changes are ad-hoc Snowflake changes outside the bundle system. "
        "Add them here to track in your assessment workflow."
    )
    with st.form("unbundled_form"):
        uf1, uf2 = st.columns(2)
        u_title    = uf1.text_input("Title *", placeholder="e.g. Snowpark Python PYPI_REPOSITORY_USER")
        u_category = uf2.text_input("Category", placeholder="e.g. Developer / Extensibility")
        uf3, uf4, uf5 = st.columns(3)
        u_impact = uf3.selectbox("Impact", IMPACTS)
        u_ge     = uf4.text_input("GE Date", placeholder="e.g. 5/2026")
        u_caseid = uf5.text_input("Case ID / BCR ref", placeholder="e.g. bcr-2156")
        u_notes  = st.text_area("Notes", height=80)
        u_docs   = st.text_input("Docs URL (optional)")
        submitted = st.form_submit_button("+ Add Unbundled BCR", type="primary")

        if submitted:
            if not u_title.strip():
                st.error("Title is required.")
            else:
                bcr_id = f"unbundled/{u_caseid.strip() or u_title.strip()[:30].replace(' ','_').lower()}"
                try:
                    session.sql(f"""
                        INSERT INTO {DB}.BCR_REGISTRY
                            (BCR_ID, BUNDLE_ID, UNBUNDLED, BUNDLE_STATUS,
                             CATEGORY, TITLE, DESCRIPTION,
                             IMPACT_DEFAULT, GE, DOCS_URL)
                        SELECT ?, 'unbundled', TRUE, 'Unbundled',
                               ?, ?, ?, ?, ?, ?
                        WHERE NOT EXISTS (SELECT 1 FROM {DB}.BCR_REGISTRY WHERE BCR_ID = ?)
                    """, [
                        bcr_id, u_category, u_title, u_notes,
                        u_impact, u_ge, u_docs or None, bcr_id
                    ]).collect()
                    session.sql(f"""
                        INSERT INTO {DB}.BCR_ASSESSMENTS (BCR_ID, BUNDLE_ID)
                        SELECT ?, 'unbundled'
                        WHERE NOT EXISTS (
                            SELECT 1 FROM {DB}.BCR_ASSESSMENTS WHERE BCR_ID = ?
                        )
                    """, [bcr_id, bcr_id]).collect()
                    st.success(f"Added: {u_title}")
                    load_registry.clear()
                except Exception as e:
                    st.error(f"Error: {e}")

    # ── DB Summary ────────────────────────────────────────────────────────────
    st.divider()
    st.subheader("Database Summary")
    try:
        counts = session.sql(f"""
            SELECT 'BCR_REGISTRY'               AS TABLE_NAME, COUNT(*) AS ROW_COUNT FROM {DB}.BCR_REGISTRY
            UNION ALL SELECT 'BCR_ASSESSMENTS',              COUNT(*) FROM {DB}.BCR_ASSESSMENTS
            UNION ALL SELECT 'BCR_DETECTION_QUERIES',        COUNT(*) FROM {DB}.BCR_DETECTION_QUERIES
            UNION ALL SELECT 'BCR_DETECTION_RESULTS',        COUNT(*) FROM {DB}.BCR_DETECTION_RESULTS
            UNION ALL SELECT 'BCR_REGRESSION_SNAPSHOTS',     COUNT(*) FROM {DB}.BCR_REGRESSION_SNAPSHOTS
        """).to_pandas()
        st.dataframe(counts, use_container_width=True, hide_index=True)
    except Exception as e:
        st.warning(f"Could not load counts: {e}")

    # ── Task Status ───────────────────────────────────────────────────────────
    st.divider()
    st.subheader("Scheduled Task Status")
    try:
        # SHOW TASKS is the most reliable way — no latency, no permission issues
        # INFORMATION_SCHEMA.TASK_HISTORY is a table function (not a view) and
        # must be called as TABLE(BCR_TRACKER_DB.INFORMATION_SCHEMA.TASK_HISTORY(...))
        tasks = session.sql("""
            SHOW TASKS IN SCHEMA BCR_TRACKER_DB.TRACKING
        """).to_pandas()
        if not tasks.empty:
            # Keep only useful columns
            keep = ["name", "state", "schedule", "definition"]
            tasks = tasks[[c for c in keep if c in tasks.columns]]
            st.dataframe(tasks, use_container_width=True, hide_index=True)
        else:
            st.info("No tasks found in BCR_TRACKER_DB.TRACKING.")
    except Exception as e:
        st.warning(f"Could not load task status: {e}")

    # ── Danger zone ───────────────────────────────────────────────────────────
    with st.expander("⚠️ Danger Zone"):
        st.warning("Clears ALL BCR data. Only use to reset a demo environment.")
        confirm = st.text_input('Type "RESET" to confirm', key="danger")
        if confirm == "RESET":
            if st.button("🗑️ Clear All BCR Data"):
                for tbl in ["BCR_DETECTION_RESULTS","BCR_DETECTION_QUERIES",
                             "BCR_ASSESSMENTS","BCR_REGRESSION_SNAPSHOTS","BCR_REGISTRY"]:
                    session.sql(f"DELETE FROM {DB}.{tbl}").collect()
                clear_all_cache()
                st.success("All data cleared.")

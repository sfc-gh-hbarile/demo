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
    """
    if not description:
        return {"before": "", "after": "", "what_to_do": "", "code_examples": [], "sql_functions": []}

    # Strip inline HTML but PRESERVE newlines — collapsing to spaces loses
    # bullet lists, code blocks and section structure
    clean = re.sub(r'<[^>]+>', '', description)

    def extract(pattern, text):
        m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        return m.group(1).strip() if m else ""

    before     = extract(r'Before the change[:\s]+(.*?)(?=After the change|What you need|$)', clean)
    after      = extract(r'After the change[:\s]+(.*?)(?=What you need to do|What to do|$)', clean)
    what_to_do = extract(r'What you need to do[:\s]+(.*?)$', clean)

    # ── Code block extraction — multiple formats ──────────────────────────────
    code_examples = []

    # 1. Fenced code blocks ``` ... ``` (with or without language tag)
    fenced = re.findall(r'```(?:[a-zA-Z]*)?\s*\n?(.*?)```', description, re.DOTALL)
    code_examples += [c.strip() for c in fenced if c.strip() and len(c.strip()) > 10]

    # 2. 4-space or tab indented code blocks (common in older Snowflake docs)
    if not code_examples:
        indented_blocks = re.findall(
            r'(?:(?:^|\n)(?:    |\t)[^\n]+)+', description, re.MULTILINE
        )
        code_examples += [
            re.sub(r'^(?:    |\t)', '', b, flags=re.MULTILINE).strip()
            for b in indented_blocks
            if len(b.strip()) > 15 and any(
                kw in b.upper() for kw in ("SELECT", "INSERT", "UPDATE", "CREATE", "ALTER", "DROP", "WITH", "FROM")
            )
        ]

    # 3. Admonition / note blocks (:::note, :::tip etc.) that contain SQL
    admonition_sql = re.findall(
        r':::(?:note|tip|warning|caution)[^\n]*\n(.*?):::', description, re.DOTALL | re.IGNORECASE
    )
    for block in admonition_sql:
        inner = block.strip()
        if any(kw in inner.upper() for kw in ("SELECT", "CREATE", "ALTER", "DROP")):
            code_examples.append(inner)

    # Deduplicate, cap at 8
    seen = set()
    unique_examples = []
    for ex in code_examples:
        key = ex[:80]
        if key not in seen:
            seen.add(key)
            unique_examples.append(ex)
    code_examples = unique_examples[:8]

    # Identify SQL function keywords for detection hints
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
        "code_examples": code_examples,
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
    st.caption(
        "For each BCR: review what is changing, generate a COE Impact Brief, "
        "and run a detection query to assess your account's exposure. "
        "Briefs and saved queries persist to the database — your team picks up where you left off."
    )

    dq_df  = load_detection_queries()
    dq_map = {r["BCR_ID"]: r for _, r in dq_df.iterrows()}

    # ── BCR selector ──────────────────────────────────────────────────────────
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

    bcr_row       = bundle_df[bundle_df["BCR_ID"] == sel_bcr].iloc[0]
    dq_row        = dq_map.get(sel_bcr)
    title_display = bcr_row["TITLE"] or bcr_row["BCR_ID"]
    desc_display  = bcr_row["DESCRIPTION"] or ""
    category      = bcr_row.get("CATEGORY", "") or ""
    docs_url      = bcr_row.get("DOCS_URL", "") or ""
    impact        = bcr_row.get("EFFECTIVE_IMPACT", "TBD") or "TBD"
    ebd           = bcr_row.get("EBD", "") or ""

    sql_key   = f"sql_{sel_bcr.replace('/', '_').replace('-', '_')}"
    brief_key = f"brief_{sel_bcr.replace('/', '_').replace('-', '_')}"

    if st.session_state.pop("_cortex_ok", False):
        st.success("SQL loaded into the editor below.")

    # ── BCR Card ──────────────────────────────────────────────────────────────
    ic        = IMPACT_COLORS.get(impact, "#95a5a6")
    ebd_label = f"EBD: {ebd}" if ebd else "EBD: TBD"
    st.markdown(
        f"""<div style='border-left:4px solid {ic};padding:10px 16px;
            background:#fafafa;border-radius:0 6px 6px 0;margin-bottom:12px'>
        <div style='font-size:17px;font-weight:700'>{title_display}</div>
        <div style='font-size:12px;color:#666;margin-top:4px'>
            {category} &nbsp;|&nbsp; {sel_bundle} &nbsp;|&nbsp;
            <span style='background:{ic};color:white;padding:1px 7px;
                border-radius:3px;font-size:11px'>{impact}</span>
            &nbsp;|&nbsp; {ebd_label}
            {'&nbsp;|&nbsp;<a href="' + docs_url + '" target="_blank">📄 Snowflake Docs ↗</a>'
             if docs_url else ''}
        </div></div>""",
        unsafe_allow_html=True,
    )

    # ── Before / After / What to do / Code examples ───────────────────────────
    # This is the primary content — drawn directly from Snowflake's own docs.
    # It is the ground truth for what the BCR does and what you need to fix.
    secs = parse_bcr_sections(desc_display)

    if secs["before"] or secs["after"]:
        bc, ac = st.columns(2)
        with bc:
            st.markdown(
                "<div style='background:#fff3f3;border-left:4px solid #e74c3c;"
                "padding:8px 12px;border-radius:0 4px 4px 0;margin-bottom:6px'>"
                "<b style='color:#e74c3c;font-size:13px'>⬛ Before the change</b></div>",
                unsafe_allow_html=True,
            )
            st.markdown(secs["before"] or "_Not available — run Enrich Descriptions in Settings._")
        with ac:
            st.markdown(
                "<div style='background:#f0fff4;border-left:4px solid #27ae60;"
                "padding:8px 12px;border-radius:0 4px 4px 0;margin-bottom:6px'>"
                "<b style='color:#27ae60;font-size:13px'>✅ After the change</b></div>",
                unsafe_allow_html=True,
            )
            st.markdown(secs["after"] or "_Not available — run Enrich Descriptions in Settings._")

        if secs["what_to_do"]:
            st.markdown(
                "<div style='background:#fff8e1;border-left:4px solid #f39c12;"
                "padding:8px 12px;border-radius:0 4px 4px 0;margin:8px 0 6px'>"
                "<b style='color:#e67e22;font-size:13px'>🔧 What you need to do</b></div>",
                unsafe_allow_html=True,
            )
            st.markdown(secs["what_to_do"])

        if secs["code_examples"]:
            st.markdown(
                "<div style='background:#f0f4ff;border-left:4px solid #2980b9;"
                "padding:8px 12px;border-radius:0 4px 4px 0;margin:8px 0 6px'>"
                "<b style='color:#2980b9;font-size:13px'>📋 SQL examples from Snowflake docs</b>"
                "<span style='color:#666;font-size:11px;margin-left:8px'>"
                "— these are the exact patterns affected by this change</span></div>",
                unsafe_allow_html=True,
            )
            for ex in secs["code_examples"]:
                st.code(ex.strip(), language="sql")

    elif not desc_display:
        st.info(
            "No description loaded yet.  \n"
            + (f"[View BCR on Snowflake Docs ↗]({docs_url})  \n" if docs_url else "")
            + "Run **Settings → Backfill Empty Descriptions** to fetch content."
        )

    # ── Cortex Code Prompt ────────────────────────────────────────────────────
    # Shown OPEN, right after the change description.
    # The Cortex Code sidebar in Snowsight has full account context (schema,
    # ACCOUNT_USAGE, INFORMATION_SCHEMA) — it generates far more precise
    # detection SQL than any generic query can.
    st.divider()
    st.markdown(
        "<div style='background:#f8f4ff;border-left:4px solid #8e44ad;"
        "padding:10px 14px;border-radius:0 6px 6px 0;margin-bottom:8px'>"
        "<b style='color:#8e44ad;font-size:14px'>✦ Cortex Code Prompt</b>"
        "<span style='color:#666;font-size:12px;margin-left:10px'>"
        "Ready to use — copy and paste into the Cortex Code sidebar in Snowsight</span>"
        "</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "**How to use:**  \n"
        "1. Copy the prompt below  \n"
        "2. Open any Snowsight worksheet → click **✦ Cortex Code** (top-right corner)  \n"
        "3. Paste the prompt — Cortex Code has access to your account's schema, "
        "INFORMATION_SCHEMA and ACCOUNT_USAGE and will generate a targeted detection query  \n"
        "4. Paste the resulting SQL into the **Detection Query** editor below → **Save** → **Run**"
    )

    # Build the prompt — always include all available context
    cortex_prompt_text = (
        f"I need to check if my Snowflake account is affected by a BCR "
        f"(Behavior Change Release) and write a detection query.\n\n"
        f"BCR: {title_display}\n"
        f"Category: {category}\n"
        f"Enforcement date (EBD): {ebd or 'TBD'}\n"
        f"Impact level: {impact}\n"
    )
    if secs.get("before"):
        cortex_prompt_text += f"\n## BEFORE the change (current behavior):\n{secs['before']}\n"
    if secs.get("after"):
        cortex_prompt_text += f"\n## AFTER the change (new behavior after enforcement):\n{secs['after']}\n"
    if secs.get("what_to_do"):
        cortex_prompt_text += f"\n## Snowflake's guidance — what you need to do:\n{secs['what_to_do']}\n"
    if secs.get("code_examples"):
        cortex_prompt_text += f"\n## SQL examples from Snowflake docs (the exact patterns affected):\n"
        for i, ex in enumerate(secs["code_examples"], 1):
            cortex_prompt_text += f"\nExample {i}:\n```sql\n{ex}\n```\n"
    elif desc_display and not secs.get("before"):
        # Fallback: include raw description if structured parse got nothing
        cortex_prompt_text += f"\n## BCR description:\n{desc_display[:1500]}\n"

    cortex_prompt_text += (
        "\n## Please do the following:\n"
        "1. Based on the change description and SQL examples above, write a precise SQL query "
        "against SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY to find queries in the last 7 days "
        "that match the affected pattern\n"
        "2. If QUERY_HISTORY is not the right surface for this BCR (e.g. it involves a "
        "configuration change, new column in SHOW output, or schema-level object change), "
        "identify the correct ACCOUNT_USAGE view or INFORMATION_SCHEMA table to query instead\n"
        "3. Write a second query that counts affected vs total queries to estimate blast radius percentage\n"
        "4. Note any INFORMATION_SCHEMA views or objects I should inspect to confirm exposure"
    )

    st.code(cortex_prompt_text, language=None)

    st.divider()

    # ── COE Impact Brief ──────────────────────────────────────────────────────
    # Persisted to BCR_ASSESSMENTS.COE_BRIEF — survives navigation and sessions.
    st.subheader("COE Impact Brief")

    # Load from DB on first render; fall back to session cache on re-render
    if brief_key not in st.session_state:
        try:
            row = session.sql(
                f"SELECT COE_BRIEF FROM {DB}.BCR_ASSESSMENTS WHERE BCR_ID = ?",
                [sel_bcr],
            ).collect()
            if row and row[0][0]:
                import json as _json
                stored = _json.loads(row[0][0])
                st.session_state[brief_key] = stored if isinstance(stored, dict) else None
            else:
                st.session_state[brief_key] = None
        except Exception:
            st.session_state[brief_key] = None

    brief = st.session_state.get(brief_key)

    if brief:
        priority = brief.get("PRIORITY", "").upper()
        p_color  = {"HIGH": "#e74c3c", "MEDIUM": "#f39c12", "LOW": "#27ae60"}.get(priority, "#95a5a6")
        hb1, hb2 = st.columns([5, 1])
        hb1.markdown(
            f"<span style='background:{p_color};color:white;padding:4px 12px;"
            f"border-radius:4px;font-weight:700'>Priority: {priority or 'TBD'}</span>"
            f"<span style='color:#888;font-size:11px;margin-left:12px'>Saved to database</span>",
            unsafe_allow_html=True,
        )
        if hb2.button("↺ Regenerate", key="regen_brief"):
            st.session_state[brief_key] = None
            try:
                session.sql(
                    f"UPDATE {DB}.BCR_ASSESSMENTS SET COE_BRIEF = NULL WHERE BCR_ID = ?",
                    [sel_bcr],
                ).collect()
            except Exception:
                pass
            st.rerun()
        st.markdown("")
        if brief.get("PLAIN_ENGLISH"):
            st.markdown(f"**📌 What is changing:** {brief['PLAIN_ENGLISH']}")
        ca, cb = st.columns(2)
        with ca:
            if brief.get("AFFECTED_IF"):
                st.error(f"**⚠️ You ARE affected if:**\n\n{brief['AFFECTED_IF']}")
        with cb:
            if brief.get("SAFE_IF"):
                st.success(f"**✅ You are SAFE if:**\n\n{brief['SAFE_IF']}")
        if brief.get("ACTION"):
            st.warning(f"**🔧 Recommended action:** {brief['ACTION']}")
        diag = brief.get("SNOWFLAKE_DIAGNOSTIC", "NONE")
        if diag and diag.upper() != "NONE":
            st.info(f"**📋 Snowflake diagnostic steps:**\n\n{diag}")
    else:
        st.caption(
            "A structured impact brief: plain-English explanation, affected-if / safe-if, "
            "and recommended action. Generated once and saved to the database."
        )
        if st.button("Generate COE Impact Brief", type="primary", key="gen_brief"):
            coe_prompt = (
                f"You are a Platform COE lead at a large enterprise using Snowflake. "
                f"A Snowflake Behavior Change Release is upcoming.\n\n"
                f"BCR Title: {title_display}\n"
                f"Category: {category}\n"
                f"Impact: {impact}\n"
                f"EBD: {ebd or 'TBD'}\n"
                f"Full description from Snowflake docs:\n{desc_display or title_display}\n\n"
                f"Generate a COE impact brief in EXACTLY this key: value format, one per line:\n"
                f"PLAIN_ENGLISH: [1-2 sentences — what Snowflake is changing, no jargon]\n"
                f"AFFECTED_IF: [specific condition — exact query pattern, workload, or config that means you are impacted]\n"
                f"SAFE_IF: [when this change has zero impact on your account]\n"
                f"ACTION: [the single most important concrete action a DBA should take before the EBD]\n"
                f"PRIORITY: [HIGH / MEDIUM / LOW based on blast radius and likelihood of impact]\n"
                f"SNOWFLAKE_DIAGNOSTIC: [copy the Suggested diagnostic steps or Customer readiness text from the description above if present, otherwise write NONE]"
            )
            with st.spinner("Generating COE Impact Brief…"):
                try:
                    raw = session.sql(
                        "SELECT SNOWFLAKE.CORTEX.COMPLETE('mistral-large2', ?)",
                        [coe_prompt],
                    ).collect()[0][0]
                    parsed = {}
                    for line in strip_sql_fences(raw).splitlines():
                        if ":" in line:
                            k, _, v = line.partition(":")
                            parsed[k.strip().upper()] = v.strip()
                    if parsed:
                        st.session_state[brief_key] = parsed
                        import json as _json
                        try:
                            session.sql(
                                f"UPDATE {DB}.BCR_ASSESSMENTS SET COE_BRIEF = ? WHERE BCR_ID = ?",
                                [_json.dumps(parsed), sel_bcr],
                            ).collect()
                        except Exception:
                            pass
                        st.rerun()
                except Exception as e:
                    st.error(f"Cortex error: {e}")

    st.divider()

    # ── Detection Query ───────────────────────────────────────────────────────
    st.subheader("Detection Query")
    st.markdown(
        "After running the Cortex Code prompt above, **paste the generated SQL here**. "
        "Save it to record your detection approach for this BCR, then run it to validate "
        "against your account. Approved queries are visible to your whole team."
    )

    # Query time window
    window_label = st.radio(
        "Query window",
        ["Last 1 day", "Last 7 days", "Last 30 days"],
        index=1,
        horizontal=True,
        help="Limits QUERY_HISTORY lookback. The window is applied when you click Run.",
    )
    days = {"Last 1 day": 1, "Last 7 days": 7, "Last 30 days": 30}[window_label]

    # Pre-load: saved query from DB only — never auto-generate ILIKE
    if sql_key not in st.session_state:
        if dq_row is not None and pd.notna(dq_row.get("DETECTION_SQL")):
            st.session_state[sql_key] = dq_row["DETECTION_SQL"]
        else:
            st.session_state[sql_key] = ""

    if st.session_state.pop("_cortex_ok", False):
        st.success("Query updated.")

    # Status banner
    if dq_row is not None and pd.notna(dq_row.get("DETECTION_SQL")):
        approved = dq_row.get("APPROVED", False)
        src      = dq_row.get("GENERATED_BY", "manual")
        badge_c  = "#27ae60" if approved else "#f39c12"
        badge_t  = "✅ Approved" if approved else "⏳ Saved — not yet approved"
        st.markdown(
            f"<div style='background:#f8f9fa;border-left:3px solid {badge_c};"
            f"padding:6px 12px;border-radius:0 4px 4px 0;font-size:12px'>"
            f"<b>{badge_t}</b> &nbsp;·&nbsp; source: <code>{src}</code>"
            + (f" &nbsp;·&nbsp; approved by: <code>{dq_row['APPROVED_BY']}</code>" if dq_row.get("APPROVED_BY") else "")
            + "</div>",
            unsafe_allow_html=True,
        )
    else:
        st.caption("No detection query saved yet for this BCR. Paste one from Cortex Code above.")

    current_sql = st.text_area(
        "Detection SQL",
        key=sql_key,
        height=240,
        label_visibility="collapsed",
        placeholder=(
            "Paste the SQL generated by Cortex Code here.\n\n"
            "Example:\nSELECT QUERY_ID, QUERY_TEXT, START_TIME, USER_NAME\n"
            "FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY\n"
            "WHERE QUERY_TEXT ILIKE '%TO_CHAR%'\n"
            "  AND START_TIME >= DATEADD('day', -7, CURRENT_DATE())\n"
            "LIMIT 200;"
        ),
    )

    sa1, sa2, sa3 = st.columns(3)
    with sa1:
        if st.button("💾 Save Query", use_container_width=True,
                     help="Save this SQL — it will persist across sessions and be visible to your team"):
            if not current_sql.strip():
                st.warning("Nothing to save — paste a query first.")
            else:
                try:
                    if dq_row is None:
                        session.sql(f"""
                            INSERT INTO {DB}.BCR_DETECTION_QUERIES
                                (BCR_ID, DETECTION_SQL, GENERATED_BY, APPROVED)
                            SELECT ?, ?, 'cortex_code', FALSE
                            WHERE NOT EXISTS (
                                SELECT 1 FROM {DB}.BCR_DETECTION_QUERIES WHERE BCR_ID = ?
                            )""", [sel_bcr, current_sql, sel_bcr]).collect()
                    else:
                        session.sql(f"""
                            UPDATE {DB}.BCR_DETECTION_QUERIES
                            SET DETECTION_SQL = ?, GENERATED_BY = 'cortex_code', APPROVED = FALSE
                            WHERE BCR_ID = ?""", [current_sql, sel_bcr]).collect()
                    load_detection_queries.clear()
                    st.success("Query saved.")
                except Exception as e:
                    st.error(f"Save failed: {e}")
    with sa2:
        if dq_row is not None and not dq_row.get("APPROVED"):
            if st.button("✅ Approve Query", use_container_width=True,
                         help="Mark this query as reviewed and validated — it will be flagged as approved for your team"):
                try:
                    session.sql(f"""
                        UPDATE {DB}.BCR_DETECTION_QUERIES
                        SET APPROVED = TRUE, APPROVED_BY = CURRENT_USER()
                        WHERE BCR_ID = ?""", [sel_bcr]).collect()
                    load_detection_queries.clear()
                    st.success("Approved.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Approve failed: {e}")
        elif dq_row is not None and dq_row.get("APPROVED"):
            st.success("✅ Approved", icon=None)
    with sa3:
        run_btn = st.button("▶ Run Detection", use_container_width=True, type="primary",
                            help="Run the query against ACCOUNT_USAGE / INFORMATION_SCHEMA")

    # Run detection
    if run_btn:
        if not current_sql.strip():
            st.warning("Paste a detection query first, then click Run.")
        else:
            run_sql = re.sub(
                r"DATEADD\s*\(\s*['\"]?day['\"]?\s*,\s*-\d+\s*,",
                f"DATEADD('day', -{days},",
                current_sql,
                flags=re.IGNORECASE,
            )
            with st.spinner("Running…"):
                try:
                    result_df = session.sql(run_sql).to_pandas()
                    affected  = len(result_df)
                    m1, m2 = st.columns(2)
                    m1.metric("Rows matched", affected)
                    m2.metric(
                        "Result",
                        "⚠️ Potentially affected" if affected > 0 else "✅ No matches",
                    )
                    if result_df.empty:
                        st.success(
                            "No matching queries found in the selected window. "
                            "Account appears unaffected — or consider widening the window "
                            "or refining the detection pattern with Cortex Code."
                        )
                    else:
                        st.dataframe(result_df.head(200), use_container_width=True, hide_index=True)

                    # Notes on this run
                    run_note = st.text_input(
                        "Add a note about this result (optional)",
                        placeholder="e.g. '3 affected queries — all from ETL pipeline, team notified' or '0 results — confirmed safe'",
                        key=f"run_note_{sel_bcr}",
                    )
                    if st.button("💾 Save result + note", key="save_result"):
                        try:
                            summary = f"{affected} rows matched in {window_label}"
                            if not result_df.empty and "QUERY_TEXT" in result_df.columns:
                                examples = result_df["QUERY_TEXT"].dropna().head(3).str[:200].tolist()
                                summary += " | Examples: " + " /// ".join(examples)
                            session.sql(f"""
                                INSERT INTO {DB}.BCR_DETECTION_RESULTS
                                    (BCR_ID, AFFECTED_COUNT, SIGNAL_SUMMARY, NOTES, DETECTION_SQL, RUN_BY)
                                VALUES (?, ?, ?, ?, ?, CURRENT_USER())
                            """, [sel_bcr, affected, summary[:2000],
                                  run_note.strip() or None,
                                  run_sql]).collect()
                            st.success("Result saved to Detection History.")
                        except Exception as e:
                            st.error(f"Could not save: {e}")
                except Exception as e:
                    st.session_state["_failed_sql"]   = current_sql
                    st.session_state["_failed_error"] = str(e)
                    st.error(f"Query error: {e}")

    # Auto-fix on error
    if "_failed_sql" in st.session_state and "_failed_error" in st.session_state:
        bad_sql   = st.session_state["_failed_sql"]
        bad_error = st.session_state["_failed_error"]
        if st.button("🔧 Auto-fix with Cortex", key="autofix"):
            fix_prompt = (
                f"Fix this Snowflake SQL query. Return ONLY the corrected SQL, no explanation.\n\n"
                f"Error: {bad_error}\n\nSQL:\n{bad_sql}"
            )
            with st.spinner("Fixing…"):
                try:
                    fixed = strip_sql_fences(
                        session.sql(
                            "SELECT SNOWFLAKE.CORTEX.COMPLETE('mistral-large2', ?)",
                            [fix_prompt],
                        ).collect()[0][0]
                    )
                    del st.session_state["_failed_sql"]
                    del st.session_state["_failed_error"]
                    st.session_state[sql_key] = fixed
                    st.session_state["_cortex_ok"] = True
                    st.rerun()
                except Exception as fix_e:
                    st.error(f"Fix attempt failed: {fix_e}")

    st.divider()

    # ── Detection History ──────────────────────────────────────────────────────
    st.subheader("Detection History")
    st.caption("Each saved run shows the result count, your notes, and the exact SQL that was executed.")
    try:
        hist = session.sql(f"""
            SELECT RESULT_ID, RUN_AT, AFFECTED_COUNT, NOTES, SIGNAL_SUMMARY, DETECTION_SQL, RUN_BY
            FROM {DB}.BCR_DETECTION_RESULTS
            WHERE BCR_ID = ?
            ORDER BY RUN_AT DESC LIMIT 20
        """, [sel_bcr]).to_pandas()
        if hist.empty:
            st.caption("No detection runs saved yet for this BCR.")
        else:
            for _, row in hist.iterrows():
                affected_n = int(row["AFFECTED_COUNT"]) if pd.notna(row["AFFECTED_COUNT"]) else 0
                result_color = "#e74c3c" if affected_n > 0 else "#27ae60"
                result_label = f"⚠️ {affected_n} rows matched" if affected_n > 0 else "✅ 0 rows — unaffected"
                run_at = str(row["RUN_AT"])[:16] if pd.notna(row["RUN_AT"]) else ""
                run_by = str(row["RUN_BY"]) if pd.notna(row["RUN_BY"]) else ""
                notes  = str(row["NOTES"]) if pd.notna(row["NOTES"]) else ""

                with st.expander(
                    f"{run_at}  ·  {result_label}  ·  {run_by}"
                    + (f"  ·  📝 {notes[:60]}{'…' if len(notes) > 60 else ''}" if notes else ""),
                    expanded=False,
                ):
                    if notes:
                        st.markdown(f"**📝 Notes:** {notes}")
                    sig = str(row["SIGNAL_SUMMARY"]) if pd.notna(row["SIGNAL_SUMMARY"]) else ""
                    if sig:
                        st.caption(f"Summary: {sig[:300]}")
                    sql_ran = str(row["DETECTION_SQL"]) if pd.notna(row["DETECTION_SQL"]) else ""
                    if sql_ran:
                        st.markdown("**SQL that was executed:**")
                        st.code(sql_ran, language="sql")
                    else:
                        st.caption("SQL not recorded for this run.")
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

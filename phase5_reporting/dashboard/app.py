"""
app.py
======
HFCL EMS — Phase 5 Interactive Dashboard
KPI & Alarm Analytics for 4G/5G Network Elements

Launch with:
    streamlit run app.py

Reads the CSV reports produced by Phase 4 from:
    output/reports/phase4/

All charts are built with Plotly for full interactivity (zoom, pan,
hover tooltips, legend toggle). Missing report files are handled
gracefully with styled empty-state cards instead of crashes.
"""

import warnings
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

warnings.filterwarnings("ignore")

# ═══════════════════════════════════════════════════════════════════════════════
# 0.  PAGE CONFIG & SHARED CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="HFCL EMS — Network Analytics",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

PHASE4_REPORTS = Path("output") / "reports" / "phase4"

# ── Colour palette ──────────────────────────────────────────────────────────
C_BLUE   = "#2B5EA7"
C_AMBER  = "#E59500"
C_RED    = "#D64045"
C_GREEN  = "#3D9970"
C_PURPLE = "#7B61FF"
C_TEAL   = "#1ABC9C"
C_GREY   = "#8A9BB0"

SEV_COLOURS = {
    "Critical": C_RED,
    "Major":    C_AMBER,
    "Minor":    C_BLUE,
    "Warning":  C_GREEN,
}

KPI_LABELS = {
    "throughput_mbps":           "Throughput (Mbps)",
    "availability_pct":          "Availability (%)",
    "utilization_pct":           "Utilization (%)",
    "latency_ms":                "Latency (ms)",
    "rtwp_dbm":                  "RTWP (dBm)",
    "handover_success_rate_pct": "HO Success Rate (%)",
    "call_drop_rate_pct":        "Call Drop Rate (%)",
    "rach_success_rate_pct":     "RACH Success Rate (%)",
}

# ── Shared Plotly layout defaults ───────────────────────────────────────────
_LAYOUT_BASE = dict(
    plot_bgcolor="rgba(0,0,0,0)",
    paper_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Inter, Arial, sans-serif", size=12),
    margin=dict(l=10, r=10, t=40, b=10),
    hoverlabel=dict(
        bgcolor="rgba(20,28,40,0.93)",
        font_size=12,
        font_color="#E8F0FA",
        bordercolor="rgba(126,184,247,0.25)",
    ),
)


# ═══════════════════════════════════════════════════════════════════════════════
# 1.  CSS INJECTION
# ═══════════════════════════════════════════════════════════════════════════════

def inject_css() -> None:
    st.markdown(
        """
        <style>
        /* ── Typography ───────────────────────────────────────────────── */
        html, body, [class*="css"] {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont,
                         'Segoe UI', sans-serif;
        }

        /* ── Core layout ──────────────────────────────────────────────── */
        .block-container {
            padding-top: 0.6rem !important;
            padding-bottom: 1.5rem !important;
        }

        /* ── Sidebar dark theme ───────────────────────────────────────── */
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #0b1623 0%, #132033 50%, #0f1c2e 100%);
            border-right: 1px solid rgba(126,184,247,0.08);
        }
        [data-testid="stSidebar"][data-sidebar-user-expanded="true"] {
            min-width: 270px;
            max-width: 292px;
        }
        /* Recolour all sidebar text for dark background */
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] .stMarkdown p,
        [data-testid="stSidebar"] .stMarkdown li,
        [data-testid="stSidebar"] span:not([class*="badge"]) {
            color: #b8cee6 !important;
        }
        [data-testid="stSidebar"] h3 {
            color: #7eb8f7 !important;
            font-size: 0.68rem !important;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 1.4px;
            margin-top: 4px !important;
        }
        /* Sidebar checkbox */
        [data-testid="stSidebar"] [data-testid="stCheckbox"] span {
            color: #b8cee6 !important;
        }
        /* Sidebar caption */
        [data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {
            color: #5d7a9a !important;
            font-size: 0.7rem;
        }
        /* Sidebar button */
        [data-testid="stSidebar"] .stButton button {
            background: rgba(43,94,167,0.22);
            border: 1px solid rgba(126,184,247,0.25);
            color: #7eb8f7;
            font-weight: 600;
            font-size: 0.8rem;
            border-radius: 8px;
            transition: all 0.2s ease;
        }
        [data-testid="stSidebar"] .stButton button:hover {
            background: rgba(43,94,167,0.40);
            border-color: rgba(126,184,247,0.5);
        }

        /* ── Dashboard header card ────────────────────────────────────── */
        .ems-header {
            background: linear-gradient(135deg, #0b1623 0%, #142d4c 55%, #0d2038 100%);
            border-radius: 14px;
            padding: 22px 26px 18px;
            margin-bottom: 18px;
            border: 1px solid rgba(43,94,167,0.28);
            position: relative;
            overflow: hidden;
        }
        /* Decorative glow orb */
        .ems-header::after {
            content: "";
            position: absolute;
            top: -40px; right: -40px;
            width: 180px; height: 180px;
            background: radial-gradient(circle,
                rgba(43,94,167,0.22) 0%, transparent 68%);
            border-radius: 50%;
            pointer-events: none;
        }
        .ems-header h1 {
            font-size: 1.52rem;
            font-weight: 800;
            color: #ffffff;
            margin: 0 0 5px;
            line-height: 1.2;
            letter-spacing: -0.3px;
        }
        .ems-header .sub {
            font-size: 0.80rem;
            color: #7eb8f7;
            margin: 0;
            opacity: 0.9;
        }
        /* Version badges */
        .ems-badge {
            display: inline-block;
            padding: 2px 9px;
            border-radius: 20px;
            font-size: 0.66rem;
            font-weight: 700;
            letter-spacing: 0.8px;
            text-transform: uppercase;
            background: rgba(43,94,167,0.30);
            border: 1px solid rgba(126,184,247,0.35);
            color: #7eb8f7;
            margin-right: 5px;
        }
        /* Status chips */
        .chip {
            display: inline-flex;
            align-items: center;
            gap: 5px;
            font-size: 0.70rem;
            font-weight: 600;
            padding: 3px 10px;
            border-radius: 20px;
            margin-right: 5px;
            margin-top: 3px;
        }
        .chip-ok   { background:rgba(61,153,112,0.14); color:#3D9970; border:1px solid rgba(61,153,112,0.28); }
        .chip-warn { background:rgba(229,149,0,0.14);  color:#E59500; border:1px solid rgba(229,149,0,0.28); }
        .chip-err  { background:rgba(214,64,69,0.14);  color:#D64045; border:1px solid rgba(214,64,69,0.28); }

        /* ── KPI metric cards ─────────────────────────────────────────── */
        [data-testid="stMetric"] {
            background: var(--secondary-background-color);
            border: 1px solid rgba(43,94,167,0.16);
            border-left: 3px solid #2B5EA7;
            border-radius: 10px;
            padding: 14px 16px 12px;
            transition: box-shadow 0.18s ease, transform 0.18s ease;
        }
        [data-testid="stMetric"]:hover {
            box-shadow: 0 4px 18px rgba(43,94,167,0.16);
            transform: translateY(-1px);
        }
        [data-testid="stMetricLabel"] {
            font-size: 0.71rem !important;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.6px;
            opacity: 0.70;
            color: var(--text-color) !important;
        }
        [data-testid="stMetricValue"] {
            font-size: 1.30rem !important;
            font-weight: 800 !important;
            color: var(--text-color) !important;
        }
        [data-testid="stMetricDelta"] {
            font-size: 0.73rem !important;
        }

        /* ── Tabs ─────────────────────────────────────────────────────── */
        [data-testid="stTabs"] {
            border-bottom: 2px solid rgba(43,94,167,0.14);
        }
        [data-testid="stTabs"] button {
            font-size: 0.83rem;
            font-weight: 600;
            padding: 8px 20px;
            border-radius: 7px 7px 0 0;
        }
        [data-testid="stTabs"] button[aria-selected="true"] {
            color: #2B5EA7 !important;
        }

        /* ── Section accent banners ───────────────────────────────────── */
        .tab-banner {
            border-radius: 0 8px 8px 0;
            padding: 10px 15px;
            margin-bottom: 18px;
        }
        .tab-banner b { font-size: 0.78rem; }
        .tab-banner p {
            margin: 4px 0 0;
            font-size: 0.77rem;
            opacity: 0.85;
        }
        .banner-blue   { background:rgba(43,94,167,0.09);  border-left:3px solid #2B5EA7; }
        .banner-amber  { background:rgba(229,149,0,0.09);  border-left:3px solid #E59500; }
        .banner-purple { background:rgba(123,97,255,0.09); border-left:3px solid #7B61FF; }

        /* Section mini-title */
        .sec-title {
            font-size: 0.72rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 1.1px;
            color: #2B5EA7;
            margin-bottom: 10px;
        }

        /* ── Empty state cards ────────────────────────────────────────── */
        .empty-card {
            text-align: center;
            padding: 30px 16px 28px;
            border: 1px dashed rgba(138,155,176,0.35);
            border-radius: 10px;
            color: #8A9BB0;
        }
        .empty-card .icon { font-size: 1.9rem; margin-bottom: 8px; }
        .empty-card p     { font-size: 0.80rem; margin: 0; }
        .empty-card code  { color: #7eb8f7; background:rgba(43,94,167,0.12); padding:1px 5px; border-radius:4px; }

        /* ── Expanders ────────────────────────────────────────────────── */
        [data-testid="stExpander"] {
            border: 1px solid rgba(43,94,167,0.14) !important;
            border-radius: 10px !important;
        }

        /* ── Dataframes ───────────────────────────────────────────────── */
        .stDataFrame { border-radius: 8px; overflow: hidden; }

        /* ── Plotly chart rounded wrapper ─────────────────────────────── */
        .stPlotlyChart { border-radius: 10px; }

        /* ── Thin scrollbar ───────────────────────────────────────────── */
        ::-webkit-scrollbar { width: 5px; height: 5px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: rgba(43,94,167,0.28); border-radius: 4px; }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 2.  DATA LOADERS
# ═══════════════════════════════════════════════════════════════════════════════

def _load(filename: str, warn: bool = True) -> pd.DataFrame | None:
    """Load a Phase 4 CSV. Returns None on missing/error; shows warning when requested."""
    path = PHASE4_REPORTS / filename
    if not path.exists():
        if warn:
            st.warning(
                f"⚠️  **Report not found:** `{path}`  \n"
                "Generate it via `python main.py --phase 4` from the project root.",
            )
        return None
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception as exc:
        st.error(f"❌  Failed to load `{filename}`: {exc}")
        return None


@st.cache_data(ttl=300, show_spinner="⏳  Loading Phase 4 reports…")
def load_all() -> dict:
    """Load every Phase 4 CSV into memory once; cache for 5 minutes."""
    return {
        # ── KPI ──────────────────────────────────────────────────────────────
        "breach_metric":   _load("breach_summary_per_metric.csv"),
        "breach_site":     _load("breach_summary_per_site.csv"),
        "breach_tech":     _load("breach_summary_per_technology.csv"),
        "breach_temporal": _load("breach_summary_temporal.csv"),
        "degradation":     _load("kpi_degradation_periods.csv"),
        # ── Alarm ─────────────────────────────────────────────────────────────
        "alarm_type":      _load("alarm_by_type.csv"),
        "alarm_severity":  _load("alarm_by_severity.csv"),
        "alarm_hour":      _load("alarm_by_hour.csv", warn=False),
        "alarm_ne":        _load("alarm_by_ne.csv"),
        "alarm_category":  _load("alarm_by_category.csv"),
        # ── Correlation ───────────────────────────────────────────────────────
        "corr_lag":        _load("correlation_lag_summary.csv"),
        "corr_coo":        _load("correlation_cooccurrence.csv"),
        "corr_ranked":     _load("correlation_root_cause_candidates.csv"),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 3.  SHARED HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _all_nodes(data: dict) -> list[str]:
    """Collect unique network_element_id values across all site-level tables."""
    ids: set[str] = set()
    for key in ("breach_site", "alarm_ne", "degradation"):
        df = data.get(key)
        if df is not None and "network_element_id" in df.columns:
            ids.update(df["network_element_id"].dropna().astype(str).unique())
    return sorted(ids)


def _filter_ne(df: pd.DataFrame | None, nodes: list[str]) -> pd.DataFrame | None:
    """Filter a DataFrame by network_element_id if the column exists."""
    if df is None or df.empty:
        return df
    if "network_element_id" in df.columns:
        return df[df["network_element_id"].astype(str).isin(nodes)].copy()
    return df


def _data_status(data: dict) -> tuple[int, int]:
    """Return (loaded_count, total_count) for live status display."""
    total  = len(data)
    loaded = sum(1 for v in data.values() if v is not None)
    return loaded, total


def _empty_state(msg: str, icon: str = "📭") -> None:
    """Render a styled empty / missing-data card."""
    st.markdown(
        f"""
        <div class="empty-card">
          <div class="icon">{icon}</div>
          <p>{msg}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _sec_title(label: str) -> None:
    """Render a small uppercase section label."""
    st.markdown(f'<div class="sec-title">{label}</div>', unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# 4.  SIDEBAR
# ═══════════════════════════════════════════════════════════════════════════════

def build_sidebar(data: dict) -> list[str]:
    """Render the sidebar; return the user-selected node IDs."""
    with st.sidebar:
        # ── Brand + live status indicator ─────────────────────────────────────
        loaded, total = _data_status(data)
        dot_color  = "#3D9970" if loaded == total else ("#E59500" if loaded > 0 else "#D64045")
        dot_label  = "All reports loaded" if loaded == total else f"{loaded} / {total} reports"

        st.markdown(
            f"""
            <div style="padding:18px 14px 12px;">
              <div style="display:flex; align-items:center; gap:11px; margin-bottom:12px;">
                <span style="font-size:28px; line-height:1;">📡</span>
                <div>
                  <div style="color:#ffffff; font-size:15px; font-weight:800;
                              letter-spacing:-0.2px; line-height:1.15;">HFCL EMS</div>
                  <div style="color:#4d7fac; font-size:0.65rem; font-weight:600;
                              text-transform:uppercase; letter-spacing:1.3px; margin-top:1px;">
                    Network Analytics
                  </div>
                </div>
              </div>
              <div style="
                  background:rgba(255,255,255,0.05);
                  border:1px solid rgba(126,184,247,0.12);
                  border-radius:8px; padding:7px 11px;
                  display:flex; align-items:center; gap:8px;
              ">
                <div style="
                    width:7px; height:7px; border-radius:50%;
                    background:{dot_color}; flex-shrink:0;
                    box-shadow:0 0 7px {dot_color};
                "></div>
                <div style="color:#8daecf; font-size:0.70rem; font-weight:600;">
                  {dot_label}
                </div>
              </div>
            </div>
            <div style="height:1px; background:rgba(126,184,247,0.08); margin:0 0 14px;"></div>
            """,
            unsafe_allow_html=True,
        )

        # ── Site filter ───────────────────────────────────────────────────────
        st.markdown("### 🗂️ Site Filter")
        all_nodes = _all_nodes(data)

        if not all_nodes:
            st.info("No site data found. Run Phase 4 first.")
            return []

        if "select_all" not in st.session_state:
            st.session_state.select_all = True

        select_all = st.checkbox(
            "Select all sites",
            value=st.session_state.select_all,
            key="select_all_cb",
        )
        st.session_state.select_all = select_all

        selected: list[str] = st.multiselect(
            label="Node ID filter",
            options=all_nodes,
            default=all_nodes if select_all else [],
            help="Filters KPI and alarm charts. Correlation charts are always fleet-wide.",
            placeholder="Choose sites…",
        )
        if not selected:
            st.caption("ℹ️ No selection — defaulting to all sites.")
            selected = all_nodes

        # Coverage badge
        pct = len(selected) / max(len(all_nodes), 1) * 100
        st.markdown(
            f"""
            <div style="
                text-align:center; padding:5px 10px; margin:7px 0 14px;
                background:rgba(43,94,167,0.16);
                border-radius:7px; color:#7eb8f7;
                font-size:0.70rem; font-weight:700;
            ">
              {len(selected)} / {len(all_nodes)} sites &nbsp;·&nbsp; {pct:.0f}% coverage
            </div>
            """,
            unsafe_allow_html=True,
        )

        # ── Controls ──────────────────────────────────────────────────────────
        st.markdown(
            "<div style='height:1px; background:rgba(126,184,247,0.08); margin:0 0 14px;'></div>",
            unsafe_allow_html=True,
        )
        st.markdown("### ⚙️ Controls")

        if st.button("🔄  Refresh Data", use_container_width=True):
            st.cache_data.clear()
            st.session_state["last_refresh"] = datetime.now().strftime("%H:%M:%S")
            st.rerun()

        if "last_refresh" in st.session_state:
            st.caption(f"Last refresh · {st.session_state['last_refresh']}")

        st.markdown(
            f"""
            <div style="
                margin-top:14px; padding:10px 12px;
                background:rgba(255,255,255,0.03);
                border:1px solid rgba(126,184,247,0.07);
                border-radius:8px;
            ">
              <div style="color:#4d6f8a; font-size:0.67rem; line-height:1.75;">
                📁 <code style="color:#5d93c4; background:rgba(43,94,167,0.14);
                                padding:1px 5px; border-radius:4px;">
                  {PHASE4_REPORTS}
                </code><br>
                ♻️ Cache TTL · 5 min<br>
                🗄️ Phase 5 · v1.0
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    return selected


# ═══════════════════════════════════════════════════════════════════════════════
# 5.  DASHBOARD HEADER
# ═══════════════════════════════════════════════════════════════════════════════

def render_header(data: dict, nodes: list[str]) -> None:
    """Full-width branded header with live status chips."""
    loaded, total = _data_status(data)
    chip_cls = "chip-ok" if loaded == total else "chip-warn"
    chip_txt = f"✓ {loaded}/{total} Reports" if loaded == total else f"⚠ {loaded}/{total} Reports"

    st.markdown(
        f"""
        <div class="ems-header">
          <div style="display:flex; justify-content:space-between;
                      align-items:flex-start; flex-wrap:wrap; gap:12px;">
            <div style="position:relative; z-index:1;">
              <h1>📡 HFCL EMS — Network Analytics</h1>
              <p class="sub">
                Phase 5 · KPI breaches, alarm volumes, and root-cause correlations
                across 4G / 5G network elements. All data from Phase 4 report CSVs.
              </p>
            </div>
            <div style="display:flex; flex-direction:column; align-items:flex-end;
                        gap:5px; position:relative; z-index:1;">
              <div><span class="ems-badge">Phase 5</span><span class="ems-badge">v1.0</span></div>
              <div style="font-size:0.65rem; color:#3d5c78; margin-top:2px;">4G / 5G EMS</div>
            </div>
          </div>
          <div style="margin-top:14px; position:relative; z-index:1;">
            <span class="chip {chip_cls}">{chip_txt}</span>
            <span class="chip chip-ok">🖧 {len(nodes)} Sites Active</span>
            <span class="chip chip-ok">📊 Phase 4 CSVs</span>
            <span class="chip chip-ok">⚡ 5-min Cache</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 6.  HEADLINE KPI CARDS
# ═══════════════════════════════════════════════════════════════════════════════

def show_headline_cards(data: dict, nodes: list[str]) -> None:
    """Four at-a-glance metric cards pinned to the top of the dashboard."""
    breach_metric = data.get("breach_metric")
    breach_site   = _filter_ne(data.get("breach_site"), nodes)
    alarm_ne      = _filter_ne(data.get("alarm_ne"),    nodes)
    corr_ranked   = data.get("corr_ranked")

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        label, delta = "—", None
        if breach_metric is not None and not breach_metric.empty:
            row   = breach_metric.sort_values("breach_rate_pct", ascending=False).iloc[0]
            label = str(row.get("display_name", "—"))
            delta = f"{row.get('breach_rate_pct', 0):.1f}% breach rate"
        st.metric(
            "🔴 Worst KPI",
            label,
            delta=delta,
            delta_color="inverse",
            help="Fleet-wide KPI metric with the most threshold violations.",
        )

    with c2:
        label, delta = "—", None
        if (breach_site is not None and not breach_site.empty
                and "any_breach_pct" in breach_site.columns):
            row   = breach_site.sort_values("any_breach_pct", ascending=False).iloc[0]
            label = str(row["network_element_id"])
            delta = f"{row['any_breach_pct']:.1f}% overall breach"
        st.metric(
            "📍 Worst Site",
            label,
            delta=delta,
            delta_color="inverse",
            help="Site with the highest proportion of KPI threshold violations.",
        )

    with c3:
        label, noisiest = "—", ""
        if alarm_ne is not None and not alarm_ne.empty:
            label    = f"{int(alarm_ne['total_alarms'].sum()):,}"
            noisiest = str(
                alarm_ne.sort_values("total_alarms", ascending=False)
                        .iloc[0]["network_element_id"]
            )
        st.metric(
            "🔔 Total Alarms",
            label,
            delta=f"Noisiest: {noisiest}" if noisiest else None,
            delta_color="off",
            help="Cumulative alarm count across all selected sites.",
        )

    with c4:
        label, delta = "—", None
        if corr_ranked is not None and not corr_ranked.empty:
            row   = corr_ranked.iloc[0]
            kpi_d = KPI_LABELS.get(
                str(row.get("kpi_metric", "")),
                str(row.get("kpi_display", row.get("kpi_metric", "—"))),
            )
            label = str(row.get("alarm_type", "—"))
            delta = f"→ {kpi_d}  · score {row.get('combined_score', 0):.3f}"
        st.metric(
            "🔗 Top Root Cause",
            label,
            delta=delta,
            delta_color="off",
            help="Alarm type with strongest combined lag + co-occurrence evidence.",
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 7.  CHART BUILDERS — KPI TAB
# ═══════════════════════════════════════════════════════════════════════════════

def _kpi_breach_by_metric(breach_metric: pd.DataFrame | None) -> go.Figure | None:
    """Horizontal bar: breach rate per KPI metric."""
    if breach_metric is None or breach_metric.empty:
        return None

    df = breach_metric.sort_values("breach_rate_pct", ascending=True).copy()
    fig = px.bar(
        df,
        x="breach_rate_pct",
        y="display_name",
        orientation="h",
        color="breach_rate_pct",
        color_continuous_scale=[[0, C_GREEN], [0.4, C_AMBER], [1, C_RED]],
        range_color=[0, df["breach_rate_pct"].max() * 1.05],
        text="breach_rate_pct",
        custom_data=["threshold", "breach_direction", "breach_count", "total_observations"],
        labels={"breach_rate_pct": "Breach Rate (%)", "display_name": "KPI Metric"},
    )
    fig.update_traces(
        texttemplate="%{text:.1f}%",
        textposition="outside",
        hovertemplate=(
            "<b>%{y}</b><br>"
            "Breach Rate : <b>%{x:.2f}%</b><br>"
            "Threshold   : %{customdata[0]} (%{customdata[1]})<br>"
            "Breach Count: %{customdata[2]:,} / %{customdata[3]:,}<extra></extra>"
        ),
    )
    fig.update_layout(
        **_LAYOUT_BASE,
        height=340,
        coloraxis_showscale=False,
        xaxis=dict(title="Breach Rate (%)", range=[0, df["breach_rate_pct"].max() * 1.25]),
        yaxis_title="",
        title="Breach Rate by KPI Metric (fleet-wide)",
    )
    return fig


def _kpi_breach_by_hour(breach_temporal: pd.DataFrame | None) -> go.Figure | None:
    """Bar chart: KPI breach rate by hour of day."""
    if breach_temporal is None or breach_temporal.empty:
        return None

    bt      = breach_temporal.copy()
    q75     = bt["breach_rate_pct"].quantile(0.75)
    colours = [C_RED if v >= q75 else C_BLUE for v in bt["breach_rate_pct"]]

    fig = go.Figure(
        go.Bar(
            x=bt["hour"],
            y=bt["breach_rate_pct"],
            marker_color=colours,
            hovertemplate="<b>%{x}:00</b><br>Breach Rate: %{y:.2f}%<extra></extra>",
            name="",
        )
    )
    fig.add_vrect(
        x0=7.5, x1=21.5,
        fillcolor=C_BLUE, opacity=0.06,
        annotation_text="Peak hours (08–22)",
        annotation_position="top left",
        annotation_font_size=10,
        line_width=0,
    )
    fig.update_layout(
        **_LAYOUT_BASE,
        height=300,
        title="Breach Rate by Hour of Day",
        xaxis=dict(title="Hour of Day", dtick=2, tick0=0),
        yaxis_title="Breach Rate (%)",
        showlegend=False,
    )
    return fig


def _kpi_site_heatmap(breach_site: pd.DataFrame | None) -> go.Figure | None:
    """Annotated heatmap: sites × KPI metric breach rates."""
    if breach_site is None or breach_site.empty:
        return None

    breach_cols = [c for c in breach_site.columns if c.endswith("_breach_pct")]
    if not breach_cols:
        return None

    heat = breach_site.set_index("network_element_id")[breach_cols].copy()
    heat.columns = [
        KPI_LABELS.get(c.replace("_breach_pct", ""), c.replace("_breach_pct", ""))
        for c in breach_cols
    ]
    if "any_breach_pct" in breach_site.columns:
        order = (
            breach_site.set_index("network_element_id")["any_breach_pct"]
            .sort_values(ascending=False).index.tolist()
        )
        heat = heat.reindex([s for s in order if s in heat.index])

    z   = heat.values.tolist()
    txt = [[f"{v:.1f}%" for v in row] for row in heat.values]

    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=heat.columns.tolist(),
            y=heat.index.tolist(),
            colorscale="RdYlGn_r",
            zmin=0, zmax=100,
            text=txt,
            texttemplate="%{text}",
            textfont=dict(size=10),
            colorbar=dict(title="Breach %", thickness=14, len=0.85),
            hovertemplate=(
                "Site: <b>%{y}</b><br>"
                "KPI: %{x}<br>"
                "Breach Rate: <b>%{z:.1f}%</b><extra></extra>"
            ),
        )
    )
    fig.update_layout(
        **_LAYOUT_BASE,
        height=max(280, len(heat) * 26 + 100),
        title="Per-Site KPI Breach Rate Heatmap (filtered)",
        xaxis_title="KPI Metric",
        yaxis_title="",
        xaxis_tickangle=-30,
    )
    return fig


# ═══════════════════════════════════════════════════════════════════════════════
# 8.  CHART BUILDERS — ALARM TAB
# ═══════════════════════════════════════════════════════════════════════════════

def _alarm_pareto(alarm_type: pd.DataFrame | None) -> go.Figure | None:
    """Pareto combo chart: bars = alarm count by type, line = cumulative %."""
    if alarm_type is None or alarm_type.empty:
        return None

    at = alarm_type.sort_values("count", ascending=False).copy().reset_index(drop=True)
    if "cumulative_pct" not in at.columns:
        at["cumulative_pct"] = (at["count"].cumsum() / at["count"].sum() * 100).round(2)

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(
            x=at["alarm_type"],
            y=at["count"],
            name="Alarm Count",
            marker_color=C_BLUE,
            marker_line_width=0,
            hovertemplate=(
                "<b>%{x}</b><br>"
                "Count : <b>%{y:,}</b><br>"
                "Category : %{customdata[0]}<br>"
                "Avg Duration : %{customdata[1]:.0f} min<extra></extra>"
            ),
            customdata=at[["alarm_category", "avg_duration_min"]].values
            if "alarm_category" in at.columns else at[["count", "count"]].values,
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=at["alarm_type"],
            y=at["cumulative_pct"],
            name="Cumulative %",
            mode="lines+markers",
            line=dict(color=C_RED, width=2.5),
            marker=dict(size=4, color=C_RED),
            hovertemplate="%{x}<br>Cumulative: <b>%{y:.1f}%</b><extra></extra>",
        ),
        secondary_y=True,
    )
    fig.add_hline(
        y=80, secondary_y=True,
        line_dash="dot", line_color=C_AMBER, line_width=1.5,
        annotation_text=" 80% (Pareto)",
        annotation_position="bottom right",
        annotation_font_color=C_AMBER,
    )
    fig.update_layout(
        **_LAYOUT_BASE,
        height=400,
        title="Alarm Volume Pareto — by Type (fleet-wide)",
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="right", x=1),
        xaxis_tickangle=-38,
        bargap=0.08,
    )
    fig.update_yaxes(title_text="Alarm Count",    secondary_y=False)
    fig.update_yaxes(title_text="Cumulative (%)", secondary_y=True,
                     range=[0, 106], showgrid=False)
    return fig


def _alarm_severity_bar(alarm_severity: pd.DataFrame | None) -> go.Figure | None:
    """Grouped bar: alarm count + average duration per severity level."""
    if alarm_severity is None or alarm_severity.empty:
        return None

    sev = alarm_severity.sort_values(
        "severity_rank" if "severity_rank" in alarm_severity.columns else "count"
    ).copy()

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(
            x=sev["severity"],
            y=sev["count"],
            name="Count",
            marker_color=[SEV_COLOURS.get(s, C_GREY) for s in sev["severity"]],
            text=sev["count"].apply(lambda v: f"{v:,}"),
            textposition="outside",
            hovertemplate="<b>%{x}</b><br>Count: %{y:,}<extra></extra>",
        ),
        secondary_y=False,
    )
    if "avg_duration_min" in sev.columns:
        fig.add_trace(
            go.Scatter(
                x=sev["severity"],
                y=sev["avg_duration_min"],
                name="Avg Duration (min)",
                mode="markers+lines",
                marker=dict(size=10, color=C_PURPLE, symbol="diamond"),
                line=dict(color=C_PURPLE, dash="dot", width=2),
                hovertemplate="%{x}<br>Avg Duration: %{y:.1f} min<extra></extra>",
            ),
            secondary_y=True,
        )
    fig.update_layout(
        **_LAYOUT_BASE,
        height=300,
        title="Alarms by Severity",
        showlegend=True,
        legend=dict(orientation="h", y=1.1),
    )
    fig.update_yaxes(title_text="Count",              secondary_y=False)
    fig.update_yaxes(title_text="Avg Duration (min)", secondary_y=True, showgrid=False)
    return fig


def _alarm_category_donut(alarm_category: pd.DataFrame | None) -> go.Figure | None:
    """Donut chart: alarm volume share by root-cause category."""
    if alarm_category is None or alarm_category.empty:
        return None

    palette = [C_BLUE, C_AMBER, C_RED, C_GREEN, C_PURPLE, C_TEAL, C_GREY]
    fig = go.Figure(
        go.Pie(
            labels=alarm_category["alarm_category"],
            values=alarm_category["count"],
            hole=0.50,
            textinfo="label+percent",
            hovertemplate=(
                "<b>%{label}</b><br>"
                "Count: %{value:,}<br>"
                "Share: %{percent}<extra></extra>"
            ),
            marker=dict(colors=palette[: len(alarm_category)]),
        )
    )
    fig.update_layout(**_LAYOUT_BASE)
    fig.update_layout(
        title="Alarm Category Distribution",
        margin=dict(l=10, r=10, t=40, b=10),
    )
    return fig


def _alarm_site_stacked(alarm_ne: pd.DataFrame | None, max_sites: int = 20) -> go.Figure | None:
    """Stacked horizontal bar: top sites by alarm volume, broken by severity."""
    if alarm_ne is None or alarm_ne.empty:
        return None

    ne = (
        alarm_ne.sort_values("total_alarms", ascending=False)
        .head(max_sites)
        .sort_values("total_alarms", ascending=True)
        .copy()
    )

    sev_col_map = {
        "critical_count": "Critical",
        "major_count":    "Major",
        "minor_count":    "Minor",
        "warning_count":  "Warning",
    }
    available = {k: v for k, v in sev_col_map.items() if k in ne.columns}

    if not available:
        fig = px.bar(
            ne, x="total_alarms", y="network_element_id",
            orientation="h",
            title=f"Top {max_sites} Sites by Alarm Volume",
            labels={"total_alarms": "Total Alarms", "network_element_id": ""},
        )
        fig.update_layout(**_LAYOUT_BASE, height=max(280, len(ne) * 26 + 80))
        return fig

    fig = go.Figure()
    for col, sev_label in available.items():
        fig.add_trace(
            go.Bar(
                x=ne[col],
                y=ne["network_element_id"],
                orientation="h",
                name=sev_label,
                marker_color=SEV_COLOURS.get(sev_label, C_GREY),
                hovertemplate=f"<b>%{{y}}</b><br>{sev_label}: %{{x:,}}<extra></extra>",
            )
        )
    fig.update_layout(
        **_LAYOUT_BASE,
        barmode="stack",
        height=max(300, len(ne) * 28 + 120),
        title=f"Top {len(ne)} Sites by Alarm Volume (Severity Breakdown) — filtered",
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="right", x=1),
        xaxis_title="Total Alarms",
        yaxis_title="",
    )
    return fig


# ═══════════════════════════════════════════════════════════════════════════════
# 9.  CHART BUILDERS — CORRELATION TAB
# ═══════════════════════════════════════════════════════════════════════════════

def _rc_scatter(ranked: pd.DataFrame) -> go.Figure:
    """Root-cause priority scatter map."""
    df = ranked.copy()
    df["cooccurrence_rate"] = (
        df.get("cooccurrence_rate", pd.Series(0.0, index=df.index)).fillna(0.0)
    )
    df["size_px"]  = (df["cooccurrence_rate"] * 80 + 8).clip(8, 80)
    df["kpi_disp"] = df["kpi_metric"].map(KPI_LABELS).fillna(
        df.get("kpi_display", df["kpi_metric"])
    )
    df["label"]    = df["alarm_type"] + "\n→ " + df["kpi_disp"]

    def _band(score: float) -> str:
        if score >= 0.66:
            return "HIGH"
        if score >= 0.33:
            return "MEDIUM"
        return "LOW"

    df["Priority"] = df["combined_score"].apply(_band)
    palette = {"HIGH": C_RED, "MEDIUM": C_AMBER, "LOW": C_GREEN}

    fig = px.scatter(
        df,
        x="combined_score",
        y="n_alarm_events",
        size="size_px",
        size_max=55,
        color="Priority",
        color_discrete_map=palette,
        hover_name="alarm_type",
        hover_data={
            "kpi_disp":          True,
            "combined_score":    ":.3f",
            "cooccurrence_rate": ":.3f",
            "peak_lag_hours":    True,
            "interpretation":    True,
            "size_px":           False,
            "Priority":          False,
        },
        text="alarm_type",
        labels={
            "combined_score":    "Combined Causal Score (0 → 1)",
            "n_alarm_events":    "Number of Alarm Events",
            "kpi_disp":          "Affected KPI",
            "cooccurrence_rate": "Co-occ. Rate",
        },
    )
    fig.update_traces(
        textposition="top center",
        textfont=dict(size=9, color="#333333"),
    )

    median_y = float(df["n_alarm_events"].median())
    fig.add_vline(x=0.5,      line_dash="dot", line_color=C_GREY, opacity=0.45)
    fig.add_hline(y=median_y, line_dash="dot", line_color=C_GREY, opacity=0.45)

    x_max = float(df["combined_score"].max())
    y_q90 = float(df["n_alarm_events"].quantile(0.85))
    y_q10 = float(df["n_alarm_events"].quantile(0.15))

    for txt, px_, py_, col in [
        ("High score / Frequent\n→ URGENT investigate", x_max * 0.88, y_q90, C_RED),
        ("High score / Rare\n→ Monitor",                x_max * 0.88, y_q10, C_AMBER),
    ]:
        fig.add_annotation(
            x=px_, y=py_, text=txt, showarrow=False,
            font=dict(color=col, size=9), align="right",
            bgcolor="rgba(255,255,255,0.7)",
        )

    fig.update_layout(
        **_LAYOUT_BASE,
        height=500,
        title="Root-Cause Priority Scatter Map  (size = co-occurrence rate)",
        legend_title="Priority",
    )
    return fig


def _rc_top_bar(ranked: pd.DataFrame, top_n: int = 15) -> go.Figure:
    """Horizontal bar: top N root-cause candidates by combined score."""
    df = ranked.head(top_n).copy()
    df["kpi_disp"] = df["kpi_metric"].map(KPI_LABELS).fillna(
        df.get("kpi_display", df["kpi_metric"])
    )
    df["label"] = df["alarm_type"] + "  →  " + df["kpi_disp"]
    df = df.sort_values("combined_score", ascending=True)

    fig = go.Figure(
        go.Bar(
            x=df["combined_score"],
            y=df["label"],
            orientation="h",
            marker=dict(
                color=df["combined_score"].tolist(),
                colorscale=[[0, C_GREEN], [0.5, C_AMBER], [1, C_RED]],
                showscale=True,
                colorbar=dict(title="Score", thickness=12, len=0.7),
            ),
            text=df["combined_score"].apply(lambda v: f"{v:.3f}"),
            textposition="outside",
            hovertemplate=(
                "<b>%{y}</b><br>"
                "Combined Score : %{x:.3f}<br>"
                "<extra></extra>"
            ),
        )
    )
    fig.update_layout(**_LAYOUT_BASE)
    fig.update_layout(
        height=max(280, top_n * 28 + 80),
        title=f"Top {top_n} Candidates by Combined Score",
        xaxis=dict(title="Combined Score", range=[0, 1.12]),
        yaxis=dict(title="", autorange="reversed"),
        margin=dict(l=10, r=80, t=40, b=10),
    )
    return fig


def _rc_coo_heatmap(coo_df: pd.DataFrame) -> go.Figure | None:
    """Heatmap: alarm type × KPI metric co-occurrence rates."""
    if coo_df is None or coo_df.empty:
        return None

    try:
        pivot = (
            coo_df.pivot_table(
                index="alarm_type",
                columns="kpi_metric",
                values="cooccurrence_rate",
                aggfunc="mean",
            ).fillna(0)
        )
    except Exception:
        return None

    pivot.columns = [KPI_LABELS.get(c, c) for c in pivot.columns]

    fig = go.Figure(
        go.Heatmap(
            z=pivot.values,
            x=pivot.columns.tolist(),
            y=pivot.index.tolist(),
            colorscale=[[0, "#EFF6FF"], [0.5, "#3B82F6"], [1, "#1E3A8A"]],
            zmin=0, zmax=1.0,
            text=[[f"{v:.2f}" for v in row] for row in pivot.values],
            texttemplate="%{text}",
            textfont=dict(size=9),
            colorbar=dict(title="Co-occ. Rate", thickness=12, len=0.8),
            hovertemplate=(
                "Alarm  : <b>%{y}</b><br>"
                "KPI    : %{x}<br>"
                "Rate   : <b>%{z:.3f}</b>"
                " (fraction of degradation events preceded by this alarm)"
                "<extra></extra>"
            ),
        )
    )
    fig.update_layout(**_LAYOUT_BASE)
    fig.update_layout(
        height=max(300, len(pivot) * 28 + 110),
        title="Co-Occurrence Rate: Alarm Type × KPI Metric",
        xaxis_tickangle=-35,
        margin=dict(l=10, r=10, t=40, b=80),
    )
    return fig


# ═══════════════════════════════════════════════════════════════════════════════
# 10.  TAB RENDERERS
# ═══════════════════════════════════════════════════════════════════════════════

def tab_kpi(data: dict, nodes: list[str]) -> None:
    """Render the KPI Performance Trends tab."""
    breach_metric   = data.get("breach_metric")
    breach_site     = _filter_ne(data.get("breach_site"),     nodes)
    breach_temporal = data.get("breach_temporal")
    degradation     = _filter_ne(data.get("degradation"),     nodes)

    # ── Tab description banner ───────────────────────────────────────────────
    st.markdown(
        """
        <div class="tab-banner banner-blue">
          <b style="color:#2B5EA7;">📈 KPI Performance Trends</b>
          <p>
            Threshold breach analysis from Phase 4. A <em>breach</em> is recorded each time
            a KPI crosses its SLA/operational limit. Degradation <em>events</em> are sustained
            windows of ≥ 4 consecutive 15-min intervals in breach (≥ 1 continuous hour).
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Row 1: Metric bar + Hourly bar ───────────────────────────────────────
    col_a, col_b = st.columns([1.5, 1])
    with col_a:
        fig = _kpi_breach_by_metric(breach_metric)
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        else:
            _empty_state(
                "breach_summary_per_metric.csv not found.<br>"
                "Run <code>python main.py --phase 4</code> to generate it.",
                "📁",
            )
    with col_b:
        fig2 = _kpi_breach_by_hour(breach_temporal)
        if fig2:
            st.plotly_chart(fig2, use_container_width=True)
        else:
            _empty_state("breach_summary_temporal.csv not found.", "🕐")

    st.divider()

    # ── Row 2: Site heatmap ───────────────────────────────────────────────────
    _sec_title("Per-Site Breach Heatmap")
    fig3 = _kpi_site_heatmap(breach_site)
    if fig3:
        st.plotly_chart(fig3, use_container_width=True)
    elif breach_site is not None and breach_site.empty:
        _empty_state("No matching sites for the current selection.", "🔍")
    else:
        _empty_state("breach_summary_per_site.csv not found.", "📁")

    st.divider()

    # ── Row 3: Degradation period explorer ───────────────────────────────────
    _sec_title("⏱️ Sustained Degradation Events")

    if degradation is not None and not degradation.empty:
        deg = degradation.copy()

        mc1, mc2, mc3, mc4 = st.columns(4)
        mc1.metric("Total Events", f"{len(deg):,}")
        mc2.metric(
            "Sites Affected",
            deg["network_element_id"].nunique()
            if "network_element_id" in deg.columns else "—",
        )
        mc3.metric(
            "Longest Event",
            f"{deg['duration_hours'].max():.1f} h"
            if "duration_hours" in deg.columns else "—",
        )
        top_kpi = (
            deg["metric"].value_counts().idxmax()
            if "metric" in deg.columns and not deg["metric"].empty else "—"
        )
        mc4.metric("Most Affected KPI", KPI_LABELS.get(top_kpi, top_kpi))

        if "duration_hours" in deg.columns and "metric" in deg.columns:
            fig_dur = px.histogram(
                deg,
                x="duration_hours",
                color="metric",
                color_discrete_sequence=px.colors.qualitative.Safe,
                nbins=30,
                labels={"duration_hours": "Event Duration (h)", "metric": "KPI Metric"},
                title="Duration Distribution of Degradation Events",
            )
            fig_dur.update_layout(
                **_LAYOUT_BASE, height=260, legend_title="KPI Metric", bargap=0.05
            )
            st.plotly_chart(fig_dur, use_container_width=True)

        with st.expander("📋 View event table (top 100 by duration)", expanded=False):
            display_cols = [c for c in [
                "network_element_id", "metric", "start", "end",
                "duration_hours", "worst_value", "mean_value",
                "threshold", "breach_direction",
            ] if c in deg.columns]
            st.dataframe(
                deg.sort_values("duration_hours", ascending=False)
                   .head(100)[display_cols],
                use_container_width=True,
                hide_index=True,
            )
    else:
        _empty_state(
            "kpi_degradation_periods.csv not available, or no sustained events "
            "exist for the selected sites.",
            "✅",
        )


def tab_alarms(data: dict, nodes: list[str]) -> None:
    """Render the Alarm Frequencies tab."""
    alarm_type     = data.get("alarm_type")
    alarm_severity = data.get("alarm_severity")
    alarm_ne       = _filter_ne(data.get("alarm_ne"), nodes)
    alarm_category = data.get("alarm_category")

    # ── Tab description banner ───────────────────────────────────────────────
    st.markdown(
        """
        <div class="tab-banner banner-amber">
          <b style="color:#E59500;">🔔 Alarm Frequencies</b>
          <p>
            Alarm volume profiling from Phase 4. The <b>Pareto chart</b> identifies
            the vital-few alarm types that account for the majority of events (80/20 rule).
            Site-level charts respect the Node ID filter in the sidebar.
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Pareto chart (fleet-wide) ─────────────────────────────────────────────
    _sec_title("Alarm Volume Pareto")
    fig_p = _alarm_pareto(alarm_type)
    if fig_p:
        st.plotly_chart(fig_p, use_container_width=True)
        st.caption(
            "ℹ️ Pareto is computed fleet-wide. "
            "Per-site alarm counts below respect the sidebar filter."
        )
    else:
        _empty_state("alarm_by_type.csv not found.", "📭")

    st.divider()

    # ── Severity breakdown + Category donut ──────────────────────────────────
    col_a, col_b = st.columns(2)
    with col_a:
        _sec_title("Severity Breakdown")
        fig_s = _alarm_severity_bar(alarm_severity)
        if fig_s:
            st.plotly_chart(fig_s, use_container_width=True)
        else:
            _empty_state("alarm_by_severity.csv not found.", "📊")

    with col_b:
        _sec_title("Category Distribution")
        fig_d = _alarm_category_donut(alarm_category)
        if fig_d:
            st.plotly_chart(fig_d, use_container_width=True)
        else:
            _empty_state("alarm_by_category.csv not found.", "🍩")

    st.divider()

    # ── Top sites stacked bar ─────────────────────────────────────────────────
    _sec_title("Top Sites by Alarm Volume")
    ctrl_col, _ = st.columns([1, 3])
    with ctrl_col:
        max_sites = st.slider(
            "Max sites to display",
            min_value=5, max_value=30, value=20,
            key="alarm_sites_slider",
        )

    fig_ne = _alarm_site_stacked(alarm_ne, max_sites=max_sites)
    if fig_ne:
        st.plotly_chart(fig_ne, use_container_width=True)
    elif alarm_ne is not None and alarm_ne.empty:
        _empty_state("No alarm data for the selected sites.", "🔍")
    else:
        _empty_state("alarm_by_ne.csv not found.", "📭")


def tab_correlation(data: dict) -> None:
    """Render the Root-Cause Correlations tab."""
    ranked = data.get("corr_ranked")
    coo_df = data.get("corr_coo")

    # ── Tab description banner ───────────────────────────────────────────────
    st.markdown(
        """
        <div class="tab-banner banner-purple">
          <b style="color:#7B61FF;">🔗 Root-Cause Correlations</b>
          <p>
            Two analytical engines: <b>lag profile analysis</b> (does a KPI worsen in the
            hours <em>after</em> an alarm fires?) and <b>co-occurrence analysis</b> (does this
            alarm type frequently precede sustained KPI degradation events?).
            The <em>combined score</em> (0–1) fuses both signals into a single root-cause rank.
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if ranked is None or ranked.empty:
        _empty_state(
            "correlation_root_cause_candidates.csv not found.<br>"
            "Run <code>python main.py --phase 4</code> to generate it.",
            "🔬",
        )
        return

    ranked = ranked.copy()

    # ── Priority scatter ──────────────────────────────────────────────────────
    _sec_title("🗺️ Root-Cause Priority Scatter Map")
    st.caption(
        "Each bubble = one (alarm type, KPI) pair.  "
        "**X** = combined causal score · **Y** = alarm frequency · "
        "**Bubble size** = co-occurrence rate · **Colour** = priority tier."
    )
    fig_sc = _rc_scatter(ranked)
    st.plotly_chart(fig_sc, use_container_width=True)

    st.divider()

    # ── Top candidates bar + Co-occurrence heatmap ────────────────────────────
    col_a, col_b = st.columns([1, 1.1])

    with col_a:
        _sec_title("Top N Candidates")
        top_n = st.slider(
            "Top N candidates",
            min_value=5,
            max_value=min(30, len(ranked)),
            value=min(15, len(ranked)),
            key="top_n_rc",
        )
        fig_bar = _rc_top_bar(ranked, top_n)
        st.plotly_chart(fig_bar, use_container_width=True)

    with col_b:
        _sec_title("Co-Occurrence Rate Heatmap")
        st.caption(
            "Fraction of sustained KPI degradation events preceded by each alarm type "
            "within a 6-hour lookback window. **1.0** = alarm *always* occurred before "
            "that KPI degraded."
        )
        fig_heat = _rc_coo_heatmap(coo_df)
        if fig_heat:
            st.plotly_chart(fig_heat, use_container_width=True)
        else:
            _empty_state("correlation_cooccurrence.csv not found.", "🌡️")

    st.divider()

    # ── Full candidate table ──────────────────────────────────────────────────
    with st.expander("📋 Full Root-Cause Candidate Table", expanded=False):
        display_cols = [c for c in [
            "rank", "alarm_type", "kpi_metric",
            "combined_score", "lag_score", "cooccurrence_rate",
            "peak_lag_hours", "degrades_kpi",
            "n_alarm_events", "cooccurrence_count",
            "interpretation",
        ] if c in ranked.columns]

        styled = ranked[display_cols].copy()
        if "kpi_metric" in styled.columns:
            styled["kpi_metric"] = styled["kpi_metric"].map(
                lambda v: KPI_LABELS.get(v, v)
            )

        col_cfg: dict = {}
        if "combined_score" in styled.columns:
            col_cfg["combined_score"] = st.column_config.ProgressColumn(
                "Combined Score", max_value=1.0, format="%.3f"
            )
        if "lag_score" in styled.columns:
            col_cfg["lag_score"] = st.column_config.ProgressColumn(
                "Lag Score", max_value=1.0, format="%.3f"
            )
        if "cooccurrence_rate" in styled.columns:
            col_cfg["cooccurrence_rate"] = st.column_config.ProgressColumn(
                "Co-occ. Rate", max_value=1.0, format="%.3f"
            )
        if "interpretation" in styled.columns:
            col_cfg["interpretation"] = st.column_config.TextColumn(
                "Interpretation", width="large"
            )

        st.dataframe(
            styled,
            use_container_width=True,
            hide_index=True,
            column_config=col_cfg,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 11.  MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    inject_css()

    # ── Load data (cached, 5-min TTL) ─────────────────────────────────────────
    data = load_all()

    # ── Sidebar (must run before header so node count is known) ───────────────
    selected_nodes = build_sidebar(data)

    # ── Branded header ────────────────────────────────────────────────────────
    render_header(data, selected_nodes)

    # ── At-a-glance headline cards ────────────────────────────────────────────
    show_headline_cards(data, selected_nodes)

    st.divider()

    # ── Main tab navigation ───────────────────────────────────────────────────
    tab1, tab2, tab3 = st.tabs([
        "📈  KPI Performance Trends",
        "🔔  Alarm Frequencies",
        "🔗  Root-Cause Correlations",
    ])

    with tab1:
        tab_kpi(data, selected_nodes)

    with tab2:
        tab_alarms(data, selected_nodes)

    with tab3:
        tab_correlation(data)


if __name__ == "__main__":
    main()

"""
app.py  ·  HFCL EMS — Network Operations Dashboard
=====================================================
Phase 5 · KPI breach, alarm volume & root-cause correlation analytics
for 4G/5G network elements.

Run with:
    streamlit run app.py

Data source:  output/reports/phase4/  (Phase 4 CSVs)
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

# ─────────────────────────────────────────────────────────────────────────────
# 0.  PAGE CONFIG
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="HFCL EMS — Network Ops",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

PHASE4_REPORTS = Path("output") / "reports" / "phase4"

# ── Colour vocabulary ────────────────────────────────────────────────────────
C_BLUE   = "#2B5EA7"
C_ACCENT = "#3B82F6"   # interactive / informational
C_AMBER  = "#F5A623"   # major / warning
C_RED    = "#E53E3E"   # critical
C_GREEN  = "#1EC88A"   # healthy / clear
C_PURPLE = "#8B5CF6"   # analytical / correlation
C_TEAL   = "#14B8A6"   # supplementary
C_GREY   = "#5A7A9A"   # muted / secondary
C_MUTED  = "#8A9BB0"   # tertiary text

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

# ── Shared Plotly layout — bespoke, not default ──────────────────────────────
_LAYOUT_BASE = dict(
    plot_bgcolor="rgba(0,0,0,0)",
    paper_bgcolor="rgba(0,0,0,0)",
    font=dict(
        family="'JetBrains Mono','Fira Code','Courier New',monospace",
        size=11,
        color="#8A9BB0",
    ),
    margin=dict(l=10, r=10, t=48, b=10),
    hoverlabel=dict(
        bgcolor="rgba(7,13,20,0.97)",
        font_size=12,
        font_color="#E8F0FA",
        bordercolor="rgba(59,130,246,0.30)",
    ),
    xaxis=dict(
        gridcolor="rgba(90,122,154,0.07)",
        linecolor="rgba(90,122,154,0.12)",
        zerolinecolor="rgba(90,122,154,0.10)",
        tickfont=dict(size=10),
    ),
    yaxis=dict(
        gridcolor="rgba(90,122,154,0.07)",
        linecolor="rgba(90,122,154,0.12)",
        zerolinecolor="rgba(90,122,154,0.10)",
        tickfont=dict(size=10),
    ),
)


# ─────────────────────────────────────────────────────────────────────────────
# 1.  STYLE CSS — all custom polish lives here
# ─────────────────────────────────────────────────────────────────────────────

def style_css() -> None:
    """Inject the full custom stylesheet. Called exactly once at startup."""
    st.markdown(
        """
        <style>
        /* ── Typefaces: JetBrains Mono (terminal feel for numbers) ───── */
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Inter:wght@400;500;600;700;800&display=swap');

        html, body, [class*="css"] {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont,
                         'Segoe UI', sans-serif;
        }

        /* ── Page canvas ─────────────────────────────────────────────── */
        .block-container {
            padding-top: 0.9rem !important;
            padding-bottom: 2.5rem !important;
            max-width: 100% !important;
        }

        /* ── Sidebar: dark with scan-line texture (signature element) ── */
        /*    The repeating-linear-gradient creates a subtle radar /       */
        /*    oscilloscope feel — unmistakably NOC, not generic SaaS.     */
        [data-testid="stSidebar"] {
            background:
                repeating-linear-gradient(
                    0deg,
                    rgba(0,0,0,0.055) 0px,
                    rgba(0,0,0,0.055) 1px,
                    transparent 1px,
                    transparent 4px
                ),
                linear-gradient(180deg, #070D14 0%, #0D1825 65%, #09141E 100%);
            border-right: 1px solid rgba(59,130,246,0.07);
        }
        [data-testid="stSidebar"][data-sidebar-user-expanded="true"] {
            min-width: 268px;
            max-width: 290px;
        }
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] .stMarkdown p,
        [data-testid="stSidebar"] .stMarkdown li,
        [data-testid="stSidebar"] span:not([class*="badge"]) {
            color: #b8cee6 !important;
        }
        [data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {
            color: #4d6f8a !important;
            font-size: 0.69rem;
        }
        [data-testid="stSidebar"] .stButton button {
            background: rgba(43,94,167,0.18);
            border: 1px solid rgba(59,130,246,0.22);
            color: #7eb8f7;
            font-weight: 600;
            font-size: 0.79rem;
            border-radius: 7px;
            transition: all 0.18s ease;
        }
        [data-testid="stSidebar"] .stButton button:hover {
            background: rgba(43,94,167,0.36);
            border-color: rgba(59,130,246,0.44);
        }

        /* ── NOC header strip ────────────────────────────────────────── */
        .noc-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-end;
            flex-wrap: wrap;
            gap: 14px;
            padding: 20px 26px 18px;
            background: #070D14;
            border: 1px solid rgba(59,130,246,0.10);
            border-radius: 12px;
            margin-bottom: 22px;
            position: relative;
            overflow: hidden;
        }
        /* Three-colour gradient top-rule — brand fingerprint */
        .noc-header::before {
            content: "";
            position: absolute;
            top: 0; left: 0; right: 0;
            height: 2px;
            background: linear-gradient(
                90deg,
                #2B5EA7 0%, #3B82F6 28%,
                #1EC88A 62%, transparent 100%
            );
            opacity: 0.65;
        }
        .noc-header__brand {
            display: flex;
            align-items: center;
            gap: 14px;
        }
        .noc-header__icon {
            font-size: 2.1rem;
            line-height: 1;
            filter: drop-shadow(0 0 12px rgba(59,130,246,0.45));
        }
        .noc-header__title {
            font-family: 'JetBrains Mono', monospace;
            font-size: 1.18rem;
            font-weight: 700;
            color: #E8F0FA;
            letter-spacing: -0.5px;
            line-height: 1;
        }
        .noc-header__sub {
            font-size: 0.67rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 1.9px;
            color: #3B82F6;
            margin-top: 5px;
        }
        .noc-header__tagline {
            font-size: 0.81rem;
            color: #4d6f8a;
            margin-top: 11px;
            font-style: italic;
            letter-spacing: 0.1px;
        }
        .noc-header__chips {
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            align-items: center;
            padding-bottom: 2px;
        }

        /* ── Status chips ─────────────────────────────────────────────── */
        .chip {
            display: inline-flex;
            align-items: center;
            gap: 5px;
            font-size: 0.67rem;
            font-weight: 600;
            font-family: 'JetBrains Mono', monospace;
            padding: 4px 10px;
            border-radius: 20px;
            letter-spacing: 0.2px;
        }
        .chip-ok   { background:rgba(30,200,138,0.10); color:#1EC88A;
                     border:1px solid rgba(30,200,138,0.24); }
        .chip-warn { background:rgba(245,166,35,0.10);  color:#F5A623;
                     border:1px solid rgba(245,166,35,0.24); }
        .chip-err  { background:rgba(229,62,62,0.10);   color:#E53E3E;
                     border:1px solid rgba(229,62,62,0.24); }
        .chip-blue { background:rgba(59,130,246,0.10);  color:#3B82F6;
                     border:1px solid rgba(59,130,246,0.24); }

        /* ── KPI Cards — completely replaces st.metric() ─────────────── */
        /*    Left-accent border colour is set via --accent CSS var.       */
        /*    Monospace numerals give terminal-instrument feel.            */
        .kpi-card {
            background: #0D1825;
            border: 1px solid rgba(90,122,154,0.11);
            border-left: 3px solid var(--accent, #3B82F6);
            border-radius: 0 10px 10px 0;
            padding: 17px 19px 15px;
            height: 100%;
            box-sizing: border-box;
            transition: transform 0.17s ease, box-shadow 0.17s ease;
        }
        .kpi-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 30px rgba(0,0,0,0.32);
        }
        .kpi-eyebrow {
            font-family: 'JetBrains Mono', 'Fira Code', monospace;
            font-size: 0.57rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 1.9px;
            color: var(--accent, #3B82F6);
            margin-bottom: 9px;
        }
        .kpi-num {
            font-family: 'JetBrains Mono', 'Fira Code', monospace;
            font-size: 1.28rem;
            font-weight: 700;
            color: #E8F0FA;
            line-height: 1.15;
            margin-bottom: 5px;
            letter-spacing: -0.4px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .kpi-num--large {
            font-size: 1.62rem;
            letter-spacing: -0.6px;
        }
        .kpi-ctx {
            font-size: 0.72rem;
            color: #5A7A9A;
            line-height: 1.5;
        }
        .kpi-delta {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.68rem;
            margin-top: 7px;
            color: var(--accent, #3B82F6);
            opacity: 0.80;
        }

        /* ── Section label: sentence-case + coloured left rule ──────── */
        .section-label {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 13px;
            margin-top: 4px;
        }
        .section-label__rule {
            width: 3px;
            height: 14px;
            background: var(--rule-color, #3B82F6);
            border-radius: 2px;
            flex-shrink: 0;
        }
        .section-label__text {
            font-size: 0.73rem;
            font-weight: 700;
            color: #8A9BB0;
            letter-spacing: 0.3px;
        }

        /* ── Section gap — replaces st.divider() ────────────────────── */
        .section-gap     { height: 30px; }
        .section-gap--sm { height: 16px; }

        /* ── Tab intro banners ───────────────────────────────────────── */
        .tab-intro {
            display: flex;
            gap: 14px;
            align-items: flex-start;
            padding: 12px 17px;
            border-radius: 0 8px 8px 0;
            margin-bottom: 22px;
            border-left: 3px solid var(--intro-color, #3B82F6);
            background: rgba(59,130,246,0.05);
        }
        .tab-intro--amber {
            --intro-color: #F5A623;
            background: rgba(245,166,35,0.05);
        }
        .tab-intro--purple {
            --intro-color: #8B5CF6;
            background: rgba(139,92,246,0.05);
        }
        .tab-intro__label {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.61rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 1.6px;
            color: var(--intro-color, #3B82F6);
            margin-bottom: 5px;
        }
        .tab-intro__body {
            font-size: 0.77rem;
            color: #5A7A9A;
            line-height: 1.65;
            margin: 0;
        }
        .tab-intro__body b { color: #7A94B0; font-weight: 600; }

        /* ── Degradation event mini-stat tiles ───────────────────────── */
        .deg-stat {
            background: rgba(13,24,37,0.70);
            border: 1px solid rgba(90,122,154,0.12);
            border-radius: 8px;
            padding: 12px 14px;
            text-align: center;
        }
        .deg-stat__label {
            font-size: 0.60rem;
            text-transform: uppercase;
            letter-spacing: 1.3px;
            color: #4A6A88;
            margin-bottom: 5px;
        }
        .deg-stat__val {
            font-family: 'JetBrains Mono', monospace;
            font-size: 1.15rem;
            font-weight: 700;
            color: #D8E8FA;
        }

        /* ── Empty state ─────────────────────────────────────────────── */
        .empty-card {
            text-align: center;
            padding: 34px 20px;
            border: 1px dashed rgba(90,122,154,0.20);
            border-radius: 10px;
            color: #5A7A9A;
        }
        .empty-card .icon { font-size: 1.85rem; margin-bottom: 9px; }
        .empty-card p     { font-size: 0.79rem; margin: 0; line-height: 1.6; }
        .empty-card code  {
            color: #3B82F6;
            background: rgba(59,130,246,0.10);
            padding: 1px 5px;
            border-radius: 4px;
            font-size: 0.75rem;
        }

        /* ── Tabs ────────────────────────────────────────────────────── */
        [data-testid="stTabs"] {
            border-bottom: 1px solid rgba(59,130,246,0.10);
        }
        [data-testid="stTabs"] button {
            font-size: 0.82rem;
            font-weight: 600;
            padding: 9px 20px;
            color: #5A7A9A !important;
            border-radius: 6px 6px 0 0;
        }
        [data-testid="stTabs"] button[aria-selected="true"] {
            color: #3B82F6 !important;
            border-bottom: 2px solid #3B82F6 !important;
        }

        /* ── Expanders ───────────────────────────────────────────────── */
        [data-testid="stExpander"] {
            border: 1px solid rgba(59,130,246,0.10) !important;
            border-radius: 9px !important;
        }
        [data-testid="stExpander"] summary {
            font-size: 0.80rem;
            font-weight: 600;
            color: #8A9BB0;
        }

        /* ── Dataframes ──────────────────────────────────────────────── */
        .stDataFrame { border-radius: 8px; overflow: hidden; }

        /* ── Thin scrollbar ──────────────────────────────────────────── */
        ::-webkit-scrollbar { width: 5px; height: 5px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb {
            background: rgba(59,130,246,0.22);
            border-radius: 4px;
        }

        /* ── Sidebar brand block ─────────────────────────────────────── */
        .sb-brand { padding: 16px 14px 12px; }
        .sb-brand__title {
            font-family: 'JetBrains Mono', monospace;
            color: #ffffff;
            font-size: 14px;
            font-weight: 700;
            letter-spacing: -0.2px;
            line-height: 1.15;
        }
        .sb-brand__subtitle {
            color: #3B82F6;
            font-size: 0.62rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 1.6px;
            margin-top: 3px;
        }
        .sb-status {
            display: flex;
            align-items: center;
            gap: 9px;
            background: rgba(255,255,255,0.038);
            border: 1px solid rgba(59,130,246,0.09);
            border-radius: 7px;
            padding: 6px 11px;
            margin-top: 11px;
        }
        .sb-status__dot {
            width: 7px; height: 7px;
            border-radius: 50%;
            flex-shrink: 0;
        }
        .sb-status__text {
            color: #8daecf;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.67rem;
            font-weight: 500;
        }
        .sb-divider {
            height: 1px;
            background: rgba(59,130,246,0.07);
            margin: 13px 0;
        }
        .sb-section-label {
            font-size: 0.59rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 1.7px;
            color: #2E4D6A;
            padding: 0 2px;
            margin-bottom: 9px;
        }
        .sb-coverage {
            text-align: center;
            padding: 5px 10px;
            margin: 8px 0 14px;
            background: rgba(43,94,167,0.14);
            border-radius: 6px;
            color: #7eb8f7;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.67rem;
            font-weight: 600;
        }
        .sb-info {
            padding: 9px 12px;
            background: rgba(255,255,255,0.02);
            border: 1px solid rgba(59,130,246,0.06);
            border-radius: 7px;
            color: #3a5570;
            font-size: 0.64rem;
            line-height: 1.85;
            margin-top: 10px;
        }
        .sb-info code {
            color: #4d83b0;
            background: rgba(43,94,167,0.12);
            padding: 1px 4px;
            border-radius: 3px;
            font-size: 0.61rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2.  DATA LOADERS
# ─────────────────────────────────────────────────────────────────────────────

def _load(filename: str, warn: bool = True) -> pd.DataFrame | None:
    """Load a Phase 4 CSV. Returns None on missing/error."""
    path = PHASE4_REPORTS / filename
    if not path.exists():
        if warn:
            st.warning(
                f"⚠️ **Report not found:** `{path}`  \n"
                "Generate it via `python main.py --phase 4` from the project root.",
            )
        return None
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception as exc:
        st.error(f"❌ Failed to load `{filename}`: {exc}")
        return None


@st.cache_data(ttl=300, show_spinner="Loading Phase 4 reports…")
def load_all() -> dict:
    """Load every Phase 4 CSV into memory once; cache for 5 minutes."""
    return {
        # KPI
        "breach_metric":   _load("breach_summary_per_metric.csv"),
        "breach_site":     _load("breach_summary_per_site.csv"),
        "breach_tech":     _load("breach_summary_per_technology.csv"),
        "breach_temporal": _load("breach_summary_temporal.csv"),
        "degradation":     _load("kpi_degradation_periods.csv"),
        # Alarm
        "alarm_type":      _load("alarm_by_type.csv"),
        "alarm_severity":  _load("alarm_by_severity.csv"),
        "alarm_hour":      _load("alarm_by_hour.csv", warn=False),
        "alarm_ne":        _load("alarm_by_ne.csv"),
        "alarm_category":  _load("alarm_by_category.csv"),
        # Correlation
        "corr_lag":        _load("correlation_lag_summary.csv"),
        "corr_coo":        _load("correlation_cooccurrence.csv"),
        "corr_ranked":     _load("correlation_root_cause_candidates.csv"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3.  SHARED HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _all_nodes(data: dict) -> list[str]:
    """Collect unique network_element_id values across all site-level tables."""
    ids: set[str] = set()
    for key in ("breach_site", "alarm_ne", "degradation"):
        df = data.get(key)
        if df is not None and "network_element_id" in df.columns:
            ids.update(df["network_element_id"].dropna().astype(str).unique())
    return sorted(ids)


def _filter_ne(df: pd.DataFrame | None, nodes: list[str]) -> pd.DataFrame | None:
    """Filter a DataFrame by network_element_id if that column exists."""
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
        f"""<div class="empty-card">
          <div class="icon">{icon}</div>
          <p>{msg}</p>
        </div>""",
        unsafe_allow_html=True,
    )


def _section_label(text: str, color: str = C_ACCENT) -> None:
    """Sentence-case section heading with a coloured left-rule accent.
    The rule colour encodes the section's severity / context at a glance."""
    st.markdown(
        f"""<div class="section-label">
          <span class="section-label__rule" style="background:{color};"></span>
          <span class="section-label__text">{text}</span>
        </div>""",
        unsafe_allow_html=True,
    )


def _section_gap(small: bool = False) -> None:
    """CSS-only section separator — invisible rhythm, not visible chrome.
    Replaces every st.divider() call."""
    cls = "section-gap--sm" if small else "section-gap"
    st.markdown(f'<div class="{cls}"></div>', unsafe_allow_html=True)


def _kpi_card(
    eyebrow: str,
    value: str,
    context: str,
    accent: str = C_ACCENT,
    large: bool = False,
    delta: str = "",
) -> str:
    """Return HTML for a premium KPI card.

    Args:
        eyebrow: Tiny all-caps label above the value (encodes the metric type).
        value:   The main displayed number or name.
        context: One-line supporting text below the value.
        accent:  CSS colour for the left-rule and the eyebrow text.
        large:   True for the hero card (2× font size on the value).
        delta:   Optional sub-text below context (e.g. 'fleet-wide breach rate').
    """
    num_cls   = "kpi-num kpi-num--large" if large else "kpi-num"
    delta_html = f'<div class="kpi-delta">{delta}</div>' if delta else ""
    return (
        f'<div class="kpi-card" style="--accent:{accent};">'
        f'  <div class="kpi-eyebrow">{eyebrow}</div>'
        f'  <div class="{num_cls}">{value}</div>'
        f'  <div class="kpi-ctx">{context}</div>'
        f'  {delta_html}'
        f'</div>'
    )


# ─────────────────────────────────────────────────────────────────────────────
# 4.  SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────

def build_sidebar(data: dict) -> list[str]:
    """Render the sidebar; return the user-selected node IDs."""
    with st.sidebar:
        loaded, total = _data_status(data)
        dot_color = (
            C_GREEN if loaded == total
            else (C_AMBER if loaded > 0 else C_RED)
        )
        dot_label = (
            "All reports loaded"
            if loaded == total
            else f"{loaded}/{total} reports"
        )

        # Brand + live indicator
        st.markdown(
            f"""<div class="sb-brand">
              <div style="display:flex;align-items:center;gap:12px;">
                <span style="font-size:26px;line-height:1;
                             filter:drop-shadow(0 0 9px rgba(59,130,246,0.45));">📡</span>
                <div>
                  <div class="sb-brand__title">HFCL EMS</div>
                  <div class="sb-brand__subtitle">Network Ops · 4G/5G</div>
                </div>
              </div>
              <div class="sb-status">
                <div class="sb-status__dot"
                     style="background:{dot_color};
                            box-shadow:0 0 7px {dot_color};"></div>
                <div class="sb-status__text">{dot_label}</div>
              </div>
            </div>
            <div class="sb-divider"></div>""",
            unsafe_allow_html=True,
        )

        # Site filter
        st.markdown(
            '<div class="sb-section-label">Site filter</div>',
            unsafe_allow_html=True,
        )
        all_nodes = _all_nodes(data)

        if not all_nodes:
            st.info("No site data yet — run Phase 4 to populate.")
            return []

        if "select_all" not in st.session_state:
            st.session_state.select_all = True

        select_all = st.checkbox(
            "Show all sites",
            value=st.session_state.select_all,
            key="select_all_cb",
        )
        st.session_state.select_all = select_all

        selected: list[str] = st.multiselect(
            label="Node IDs",
            options=all_nodes,
            default=all_nodes if select_all else [],
            help="Filters KPI and alarm charts. Correlation is always fleet-wide.",
            placeholder="Choose sites…",
        )
        if not selected:
            st.caption("No selection — showing all sites.")
            selected = all_nodes

        pct = len(selected) / max(len(all_nodes), 1) * 100
        st.markdown(
            f'<div class="sb-coverage">'
            f'{len(selected)} / {len(all_nodes)} sites'
            f' &nbsp;·&nbsp; {pct:.0f}% coverage'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Controls
        st.markdown('<div class="sb-divider"></div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="sb-section-label">Controls</div>',
            unsafe_allow_html=True,
        )

        if st.button("↺  Refresh data", use_container_width=True):
            st.cache_data.clear()
            st.session_state["last_refresh"] = datetime.now().strftime("%H:%M:%S")
            st.rerun()

        if "last_refresh" in st.session_state:
            st.caption(f"Refreshed at {st.session_state['last_refresh']}")

        # Metadata footer
        st.markdown(
            f"""<div class="sb-info">
              📁 <code>{PHASE4_REPORTS}</code><br>
              ♻ Cache · 5 min TTL<br>
              🗄 Phase 5 · v1.0
            </div>""",
            unsafe_allow_html=True,
        )

    return selected


# ─────────────────────────────────────────────────────────────────────────────
# 5.  DASHBOARD HEADER
# ─────────────────────────────────────────────────────────────────────────────

def render_header(data: dict, nodes: list[str]) -> None:
    """Slim NOC-style branded header with three-colour gradient rule."""
    loaded, total = _data_status(data)
    chip_cls = "chip-ok" if loaded == total else "chip-warn"
    chip_txt = (
        f"✓ {loaded}/{total} reports"
        if loaded == total
        else f"⚠ {loaded}/{total} reports"
    )

    st.markdown(
        f"""<div class="noc-header">
          <div>
            <div class="noc-header__brand">
              <span class="noc-header__icon">📡</span>
              <div>
                <div class="noc-header__title">HFCL EMS</div>
                <div class="noc-header__sub">
                  Network Operations Center &nbsp;·&nbsp; 4G / 5G Fleet
                </div>
              </div>
            </div>
            <div class="noc-header__tagline">
              Watching your fleet so you don't have to look away.
            </div>
          </div>
          <div class="noc-header__chips">
            <span class="chip {chip_cls}">{chip_txt}</span>
            <span class="chip chip-blue">🖧 {len(nodes)} sites</span>
            <span class="chip chip-blue">Phase 5</span>
            <span class="chip chip-ok">⚡ 5-min cache</span>
          </div>
        </div>""",
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 6.  HEADLINE KPI CARDS
# ─────────────────────────────────────────────────────────────────────────────

def show_headline_cards(data: dict, nodes: list[str]) -> None:
    """Four at-a-glance signal cards.

    Layout: [2, 1, 1, 1]  — the worst-KPI card is the visual focal point;
    the other three are deliberately smaller so the eye lands on the alert
    before scanning the context. No st.metric() anywhere.
    """
    breach_metric = data.get("breach_metric")
    breach_site   = _filter_ne(data.get("breach_site"), nodes)
    alarm_ne      = _filter_ne(data.get("alarm_ne"),    nodes)
    corr_ranked   = data.get("corr_ranked")

    # ── Derive card values ────────────────────────────────────────────────────

    # Card 1 — Worst KPI (hero)
    kpi_val = kpi_ctx = kpi_delta = "—"
    kpi_accent = C_RED
    if breach_metric is not None and not breach_metric.empty:
        row       = breach_metric.sort_values("breach_rate_pct", ascending=False).iloc[0]
        kpi_val   = str(row.get("display_name", "—"))
        kpi_ctx   = "Highest threshold violation rate across all monitored KPIs"
        kpi_delta = f"{row.get('breach_rate_pct', 0):.1f}% breach rate fleet-wide"

    # Card 2 — Worst site
    site_val = site_ctx = "—"
    site_accent = C_AMBER
    if (
        breach_site is not None
        and not breach_site.empty
        and "any_breach_pct" in breach_site.columns
    ):
        row      = breach_site.sort_values("any_breach_pct", ascending=False).iloc[0]
        site_val = str(row["network_element_id"])
        site_ctx = f"{row['any_breach_pct']:.1f}% overall breach rate"

    # Card 3 — Total alarms
    alarm_val = alarm_ctx = "—"
    alarm_accent = C_AMBER
    if alarm_ne is not None and not alarm_ne.empty:
        total_    = int(alarm_ne["total_alarms"].sum())
        alarm_val = f"{total_:,}"
        noisiest  = str(
            alarm_ne.sort_values("total_alarms", ascending=False)
                    .iloc[0]["network_element_id"]
        )
        alarm_ctx = f"Noisiest site: {noisiest}"

    # Card 4 — Top root cause
    rc_val = rc_ctx = "—"
    rc_accent = C_PURPLE
    if corr_ranked is not None and not corr_ranked.empty:
        row    = corr_ranked.iloc[0]
        kpi_d  = KPI_LABELS.get(
            str(row.get("kpi_metric", "")),
            str(row.get("kpi_metric", "—")),
        )
        rc_val = str(row.get("alarm_type", "—"))
        rc_ctx = f"→ {kpi_d}  ·  score {row.get('combined_score', 0):.3f}"

    # ── Render: hero card (2×) + three secondaries ────────────────────────────
    col_hero, col_b, col_c, col_d = st.columns([2, 1, 1, 1])

    with col_hero:
        st.markdown(
            _kpi_card(
                "⚠  Worst-performing KPI",
                kpi_val,
                kpi_ctx,
                accent=kpi_accent,
                large=True,
                delta=kpi_delta,
            ),
            unsafe_allow_html=True,
        )

    with col_b:
        st.markdown(
            _kpi_card("📍 Worst site", site_val, site_ctx, accent=site_accent),
            unsafe_allow_html=True,
        )

    with col_c:
        st.markdown(
            _kpi_card("🔔 Total alarms", alarm_val, alarm_ctx, accent=alarm_accent),
            unsafe_allow_html=True,
        )

    with col_d:
        st.markdown(
            _kpi_card("🔬 Top root cause", rc_val, rc_ctx, accent=rc_accent),
            unsafe_allow_html=True,
        )


# ─────────────────────────────────────────────────────────────────────────────
# 7.  CHART BUILDERS — SIGNAL HEALTH TAB
# ─────────────────────────────────────────────────────────────────────────────

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
        labels={"breach_rate_pct": "Breach Rate (%)", "display_name": ""},
    )
    
    fig.update_traces(
        texttemplate="%{text:.1f}%",
        textposition="outside",
        marker_line_width=0,
        hovertemplate=(
            "<b>%{y}</b><br>"
            "Breach rate · <b>%{x:.2f}%</b><br>"
            "Threshold · %{customdata[0]} (%{customdata[1]})<br>"
            "Events · %{customdata[2]:,} of %{customdata[3]:,}"
            "<extra></extra>"
        ),
    )
    
    # 1. Update general configurations using your base global dictionary mapping
    fig.update_layout(
        **_LAYOUT_BASE,
        height=340,
        coloraxis_showscale=False,
        yaxis_title="",
        title=dict(
            text="Where breach pressure is concentrated",
            font=dict(size=13, color="#8A9BB0", family="Inter, sans-serif"),
        ),
    )
    
    # 2. FIX: Modify specific x-axis overrides cleanly to prevent keyword collisions
    fig.update_xaxes(
        title="Breach rate (%)",
        range=[0, df["breach_rate_pct"].max() * 1.28],
        gridcolor="rgba(90,122,154,0.07)"
    )
    
    return fig

def _kpi_breach_by_hour(breach_temporal: pd.DataFrame | None) -> go.Figure | None:
    """Line chart: breach intensity trend by hour of the day using bulletproof Graph Objects."""
    if breach_temporal is None or breach_temporal.empty:
        return None

    # 1. Sort cleanly by hour matrix sequence
    df = breach_temporal.sort_values("hour").copy()

    # 2. Extract arrays explicitly to prevent any internal Pandas index/column inspection
    hours_list = df["hour"].tolist()
    rates_list = df["breach_rate_pct"].tolist()

    # 3. Create the figure using lower-level Graph Objects (Circumvents Plotly Express KeyErrors)
    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=hours_list,
            y=rates_list,
            mode="lines+markers",
            line=dict(color=C_ACCENT, width=2.5),
            marker=dict(size=6, color=C_ACCENT),
            name="Breach Rate",
            hovertemplate="Hour <b>%{x}:00</b><br>Breach Rate: <b>%{y:.2f}%</b><extra></extra>"
        )
    )

    # 4. Apply clean layout dimensions and clear margins explicitly
    fig.update_layout(
        margin=dict(l=45, r=20, t=45, b=40),
        hovermode="closest",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=300,
        yaxis_title="Breach Rate (%)",
        title=dict(
            text="Hourly Activity Signature",
            font=dict(size=13, color="#8A9BB0", family="Inter, sans-serif"),
        ),
        showlegend=False
    )

    # 5. Safely apply axis grid formatting directly
    fig.update_xaxes(
        tickmode="linear",
        tick0=0,
        dtick=2,
        gridcolor="rgba(90,122,154,0.07)",
        zeroline=False,
        title="Hour of day (0-23)"
    )
    
    fig.update_yaxes(
        gridcolor="rgba(90,122,154,0.07)",
        zeroline=False
    )

    return fig

def _kpi_site_heatmap(breach_site: pd.DataFrame | None) -> go.Figure | None:
    """Heatmap matrix: site vs metric breach intensities."""
    if breach_site is None or breach_site.empty:
        return None

    df = breach_site.copy()

    # 1. FIX: Fallback to 'metric' if 'display_name' does not exist in the CSV columns
    if "display_name" not in df.columns and "metric" in df.columns:
        df["display_name"] = df["metric"].map(lambda x: KPI_LABELS.get(x, x))
    elif "display_name" not in df.columns:
        df["display_name"] = "Unknown Metric"

    # Verify required tracking columns exist before building pivot matrix
    y_col = "display_name"
    x_col = "network_element_id" if "network_element_id" in df.columns else df.columns[0]
    z_col = "breach_count" if "breach_count" in df.columns else df.columns[1]

    # 2. Pivot dataframe values appropriately for intensity rendering
    pivot_df = df.pivot(
        index=y_col, columns=x_col, values=z_col
    ).fillna(0)

    if pivot_df.empty:
        return None

    # 3. Use lower-level go.Heatmap to ensure total safety against global template trace collisions
    fig = go.Figure(
        data=go.Heatmap(
            z=pivot_df.values,
            x=pivot_df.columns.tolist(),
            y=pivot_df.index.tolist(),
            colorscale=[[0, "#1E222B"], [0.1, "rgba(43,94,167,0.4)"], [1, C_RED]],
            hovertemplate="Node: <b>%{x}</b><br>Metric: <b>%{y}</b><br>Breaches: <b>%{z:,}</b><extra></extra>"
        )
    )

    # 4. Clean styling variables
    fig.update_layout(
        margin=dict(l=40, r=20, t=35, b=40),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=380,
    )

    # Isolate specific configuration updates for X and Y axes cleanly
    fig.update_xaxes(tickangle=45, gridcolor="rgba(90,122,154,0.05)", title="Network Node / Site ID")
    fig.update_yaxes(gridcolor="rgba(90,122,154,0.05)")

    return fig

# ─────────────────────────────────────────────────────────────────────────────
# 8.  CHART BUILDERS — NOISE FLOOR TAB
# ─────────────────────────────────────────────────────────────────────────────

def _alarm_pareto(alarm_type: pd.DataFrame | None) -> go.Figure | None:
    """Pareto combo: bars = alarm count by type, line = cumulative %."""
    if alarm_type is None or alarm_type.empty:
        return None

    at = alarm_type.sort_values("count", ascending=False).copy().reset_index(drop=True)
    if "cumulative_pct" not in at.columns:
        at["cumulative_pct"] = (
            at["count"].cumsum() / at["count"].sum() * 100
        ).round(2)

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(
            x=at["alarm_type"],
            y=at["count"],
            name="Alarm count",
            marker_color=C_BLUE,
            marker_line_width=0,
            hovertemplate=(
                "<b>%{x}</b><br>"
                "Count · <b>%{y:,}</b><br>"
                "Category · %{customdata[0]}<br>"
                "Avg duration · %{customdata[1]:.0f} min<extra></extra>"
            ),
            customdata=(
                at[["alarm_category", "avg_duration_min"]].values
                if "alarm_category" in at.columns
                else at[["count", "count"]].values
            ),
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=at["alarm_type"],
            y=at["cumulative_pct"],
            name="Cumulative %",
            mode="lines+markers",
            line=dict(color=C_RED, width=2),
            marker=dict(size=4, color=C_RED),
            hovertemplate="%{x}<br>Cumulative · <b>%{y:.1f}%</b><extra></extra>",
        ),
        secondary_y=True,
    )
    fig.add_hline(
        y=80, secondary_y=True,
        line_dash="dot", line_color=C_AMBER, line_width=1.5,
        annotation_text=" 80% mark",
        annotation_position="bottom right",
        annotation_font_color=C_AMBER,
        annotation_font_size=10,
    )
    fig.update_layout(
        **_LAYOUT_BASE,
        height=400,
        title=dict(
            text="The vital few alarm types — fleet-wide Pareto",
            font=dict(size=13, color="#8A9BB0", family="Inter, sans-serif"),
        ),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.01,
            xanchor="right", x=1, font=dict(size=10),
        ),
        xaxis_tickangle=-38,
        bargap=0.08,
    )
    fig.update_yaxes(title_text="Alarm count",    secondary_y=False)
    fig.update_yaxes(
        title_text="Cumulative (%)", secondary_y=True,
        range=[0, 106], showgrid=False,
    )
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
            marker_line_width=0,
            text=sev["count"].apply(lambda v: f"{v:,}"),
            textposition="outside",
            hovertemplate="<b>%{x}</b><br>Count · %{y:,}<extra></extra>",
        ),
        secondary_y=False,
    )
    if "avg_duration_min" in sev.columns:
        fig.add_trace(
            go.Scatter(
                x=sev["severity"],
                y=sev["avg_duration_min"],
                name="Avg duration (min)",
                mode="markers+lines",
                marker=dict(size=9, color=C_PURPLE, symbol="diamond"),
                line=dict(color=C_PURPLE, dash="dot", width=2),
                hovertemplate="%{x}<br>Avg duration · %{y:.1f} min<extra></extra>",
            ),
            secondary_y=True,
        )
    fig.update_layout(
        **_LAYOUT_BASE,
        height=300,
        title=dict(
            text="How severe is the noise?",
            font=dict(size=13, color="#8A9BB0", family="Inter, sans-serif"),
        ),
        showlegend=True,
        legend=dict(orientation="h", y=1.08, font=dict(size=10)),
    )
    fig.update_yaxes(title_text="Count",               secondary_y=False)
    fig.update_yaxes(
        title_text="Avg duration (min)",
        secondary_y=True, showgrid=False,
    )
    return fig


def _alarm_category_donut(alarm_category: pd.DataFrame | None) -> go.Figure | None:
    """Donut chart: alarm volume share by root-cause category.
    Uses a monochromatic blue family instead of a rainbow."""
    if alarm_category is None or alarm_category.empty:
        return None

    # Monochromatic palette — sophisticated, not a carnival
    palette = [
        C_BLUE, "#4A7FC1", C_TEAL, C_GREY,
        C_PURPLE, C_MUTED, "#1A3A5A", "#2E6098",
    ]
    fig = go.Figure(
        go.Pie(
            labels=alarm_category["alarm_category"],
            values=alarm_category["count"],
            hole=0.52,
            textinfo="label+percent",
            textfont=dict(size=10),
            hovertemplate=(
                "<b>%{label}</b><br>"
                "Count · %{value:,}<br>"
                "Share · %{percent}<extra></extra>"
            ),
            marker=dict(
                colors=palette[: len(alarm_category)],
                line=dict(color="#070D14", width=2),
            ),
        )
    )
    fig.update_layout(
        **_LAYOUT_BASE,
        title=dict(
            text="What's triggering the most alarms",
            font=dict(size=13, color="#8A9BB0", family="Inter, sans-serif"),
        ),
        margin=dict(l=10, r=10, t=48, b=10),
    )
    return fig


def _alarm_site_stacked(
    alarm_ne: pd.DataFrame | None, max_sites: int = 20
) -> go.Figure | None:
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
            ne,
            x="total_alarms", y="network_element_id",
            orientation="h",
            labels={"total_alarms": "Total alarms", "network_element_id": ""},
        )
        fig.update_layout(
            **_LAYOUT_BASE,
            height=max(280, len(ne) * 26 + 80),
            title=dict(
                text=f"Your {max_sites} noisiest sites",
                font=dict(size=13, color="#8A9BB0", family="Inter, sans-serif"),
            ),
        )
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
                marker_line_width=0,
                hovertemplate=(
                    f"<b>%{{y}}</b><br>{sev_label} · %{{x:,}}<extra></extra>"
                ),
            )
        )
    fig.update_layout(
        **_LAYOUT_BASE,
        barmode="stack",
        height=max(300, len(ne) * 28 + 120),
        title=dict(
            text=f"Your noisiest sites, by alarm class (top {len(ne)})",
            font=dict(size=13, color="#8A9BB0", family="Inter, sans-serif"),
        ),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.01,
            xanchor="right", x=1, font=dict(size=10),
        ),
        xaxis_title="Total alarms",
        yaxis_title="",
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# 9.  CHART BUILDERS — ROOT CAUSE TAB
# ─────────────────────────────────────────────────────────────────────────────

def _rc_scatter(ranked: pd.DataFrame) -> go.Figure:
    """Priority scatter map: bubble = (alarm type, KPI) causal pair."""
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
            "combined_score":    "Combined causal score (0 → 1)",
            "n_alarm_events":    "Alarm event count",
            "kpi_disp":          "Affected KPI",
            "cooccurrence_rate": "Co-occ. rate",
        },
    )
    fig.update_traces(
        textposition="top center",
        textfont=dict(size=9, color="#8A9BB0"),
    )

    median_y = float(df["n_alarm_events"].median())
    fig.add_vline(x=0.5,      line_dash="dot", line_color=C_GREY, opacity=0.35)
    fig.add_hline(y=median_y, line_dash="dot", line_color=C_GREY, opacity=0.35)

    x_max = float(df["combined_score"].max())
    y_q90 = float(df["n_alarm_events"].quantile(0.85))
    y_q10 = float(df["n_alarm_events"].quantile(0.15))

    for txt, px_, py_, col in [
        ("high score · frequent → investigate now", x_max * 0.88, y_q90, C_RED),
        ("high score · rare → watch list",          x_max * 0.88, y_q10, C_AMBER),
    ]:
        fig.add_annotation(
            x=px_, y=py_, text=txt, showarrow=False,
            font=dict(
                color=col, size=9,
                family="'JetBrains Mono',monospace",
            ),
            align="right",
            bgcolor="rgba(7,13,20,0.82)",
            borderpad=4,
        )

    fig.update_layout(
        **_LAYOUT_BASE,
        height=500,
        title=dict(
            text="Where to look first  (bubble size = co-occurrence rate)",
            font=dict(size=13, color="#8A9BB0", family="Inter, sans-serif"),
        ),
        legend_title="Priority tier",
    )
    return fig


def _rc_top_bar(ranked: pd.DataFrame, top_n: int = 15) -> go.Figure:
    """Horizontal bar: top N root-cause candidates ranked by combined score."""
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
                colorbar=dict(
                    title="Score", thickness=11, len=0.7,
                    tickfont=dict(size=10),
                ),
            ),
            marker_line_width=0,
            text=df["combined_score"].apply(lambda v: f"{v:.3f}"),
            textposition="outside",
            hovertemplate="<b>%{y}</b><br>Score · %{x:.3f}<extra></extra>",
        )
    )
    fig.update_layout(
        **_LAYOUT_BASE,
        height=max(280, top_n * 28 + 80),
        title=dict(
            text=f"Strongest causal signals (top {top_n})",
            font=dict(size=13, color="#8A9BB0", family="Inter, sans-serif"),
        ),
        xaxis=dict(title="Combined score", range=[0, 1.14]),
        yaxis=dict(title="", autorange="reversed"),
        margin=dict(l=10, r=82, t=48, b=10),
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
            # Monochromatic brand-blue scale — not the generic blue-white default
            colorscale=[[0, "#0D1825"], [0.45, "#2B5EA7"], [1, "#3B82F6"]],
            zmin=0, zmax=1.0,
            text=[[f"{v:.2f}" for v in row] for row in pivot.values],
            texttemplate="%{text}",
            textfont=dict(size=9),
            colorbar=dict(
                title="Rate", thickness=11, len=0.8,
                tickfont=dict(size=10),
            ),
            hovertemplate=(
                "Alarm · <b>%{y}</b><br>"
                "KPI   · %{x}<br>"
                "Rate  · <b>%{z:.3f}</b>"
                " (fraction of KPI degradation events preceded by this alarm)"
                "<extra></extra>"
            ),
        )
    )
    fig.update_layout(
        **_LAYOUT_BASE,
        height=max(300, len(pivot) * 28 + 110),
        title=dict(
            text="How reliably each alarm precedes KPI degradation",
            font=dict(size=13, color="#8A9BB0", family="Inter, sans-serif"),
        ),
        xaxis_tickangle=-35,
        margin=dict(l=10, r=10, t=48, b=80),
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# 10.  TAB RENDERERS
# ─────────────────────────────────────────────────────────────────────────────

def tab_kpi(data: dict, nodes: list[str]) -> None:
    """Render the Signal Health tab with error boundaries and data checks."""
    breach_metric   = data.get("breach_metric")
    breach_site     = _filter_ne(data.get("breach_site"),     nodes)
    breach_temporal = data.get("breach_temporal")
    degradation     = _filter_ne(data.get("degradation"),     nodes)

    # Tab intro — product copy, not API docs
    st.markdown(
        """<div class="tab-intro">
          <div>
            <div class="tab-intro__label">Signal Health · KPI breach analysis</div>
            <p class="tab-intro__body">
              A <b>breach</b> fires each time a KPI crosses its SLA or operational limit.
              A <b>degradation event</b> is a sustained window of ≥ 4 consecutive 15-min
              intervals in breach — at least one continuous hour below threshold.
              Charts respect your current site selection.
            </p>
          </div>
        </div>""",
        unsafe_allow_html=True,
    )

    # ── Row 1: focal-point wide chart + narrow temporal sidebar ──────────────
    col_a, col_b = st.columns([1.5, 1])
    with col_a:
        # Check if the dataframe is completely missing or empty before passing to Plotly builders
        if breach_metric is not None and not breach_metric.empty:
            fig = _kpi_breach_by_metric(breach_metric)
            if fig is not None:
                st.plotly_chart(fig, use_container_width=True)
            else:
                _empty_state("No structural chart details generated for metric breach profiles.", "📊")
        else:
            _empty_state(
                "breach_summary_per_metric.csv not found.<br>"
                "Run <code>python main.py --phase 4</code> to generate it.",
                "📁",
            )
            
    with col_b:
        if breach_temporal is not None and not breach_temporal.empty:
            fig2 = _kpi_breach_by_hour(breach_temporal)
            if fig2 is not None:
                st.plotly_chart(fig2, use_container_width=True)
            else:
                _empty_state("No data trend lines could be rendered for this sequence selection.", "🕐")
        else:
            _empty_state("breach_summary_temporal.csv not found.", "🕐")

    _section_gap()

    # ── Row 2: site heatmap — full width, high information density ────────────
    _section_label(
        "Site-by-site exposure — how much each location contributes to the signal"
    )
    
    if breach_site is not None and not breach_site.empty:
        fig3 = _kpi_site_heatmap(breach_site)
        if fig3 is not None:
            st.plotly_chart(fig3, use_container_width=True)
        else:
            _empty_state("The density mapping metrics for these sites yielded an empty visual canvas.", "🗺️")
    elif breach_site is not None and breach_site.empty:
        _empty_state("No matching sites for the current selection.", "🔍")
    else:
        _empty_state("breach_summary_per_site.csv not found.", "📁")

    _section_gap()

    # ── Row 3: sustained degradation events ───────────────────────────────────
    _section_label(
        "Sustained degradation — prolonged outages, not just blips",
        color=C_RED,
    )

    if degradation is not None and not degradation.empty:
        deg = degradation.copy()

        # Summary stats — custom HTML tiles, not st.metric()
        total_events   = len(deg)
        sites_affected = (
            deg["network_element_id"].nunique()
            if "network_element_id" in deg.columns else "—"
        )
        longest = (
            f"{deg['duration_hours'].max():.1f} h"
            if "duration_hours" in deg.columns else "—"
        )
        top_kpi_raw = (
            deg["metric"].value_counts().idxmax()
            if "metric" in deg.columns and not deg["metric"].empty else "—"
        )
        top_kpi = KPI_LABELS.get(top_kpi_raw, top_kpi_raw)

        d1, d2, d3, d4 = st.columns(4)
        with d1:
            st.markdown(
                f'<div class="deg-stat">'
                f'<div class="deg-stat__label">Total events</div>'
                f'<div class="deg-stat__val">{total_events:,}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        with d2:
            st.markdown(
                f'<div class="deg-stat">'
                f'<div class="deg-stat__label">Sites affected</div>'
                f'<div class="deg-stat__val">{sites_affected}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        with d3:
            st.markdown(
                f'<div class="deg-stat">'
                f'<div class="deg-stat__label">Longest event</div>'
                f'<div class="deg-stat__val">{longest}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        with d4:
            st.markdown(
                f'<div class="deg-stat">'
                f'<div class="deg-stat__label">Most affected KPI</div>'
                f'<div class="deg-stat__val"'
                f'     style="font-size:0.82rem;">{top_kpi}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        _section_gap(small=True)

        # Duration histogram — monochromatic blue family, NOT qualitative rainbow
        if "duration_hours" in deg.columns and "metric" in deg.columns:
            unique_kpis  = sorted(deg["metric"].unique())
            n            = max(len(unique_kpis), 1)
            mono_palette = [
                f"hsl({205 + int(i * 28 % 50)}, {68 - int(i * 5 % 20)}%, "
                f"{38 + int(i * 9 % 28)}%)"
                for i in range(n)
            ]
            color_map = dict(zip(unique_kpis, mono_palette))

            fig_dur = px.histogram(
                deg,
                x="duration_hours",
                color="metric",
                color_discrete_map=color_map,
                nbins=30,
                labels={
                    "duration_hours": "Event duration (h)",
                    "metric":         "KPI metric",
                },
                opacity=0.86,
            )
            fig_dur.update_layout(
                **_LAYOUT_BASE,
                height=260,
                title=dict(
                    text="How long degradation events lasted — most are short, some linger",
                    font=dict(size=13, color="#8A9BB0", family="Inter, sans-serif"),
                ),
                legend_title="KPI metric",
                bargap=0.04,
            )
            
            # Explicit safety boundary check for the histogram output
            if fig_dur is not None:
                st.plotly_chart(fig_dur, use_container_width=True)
            else:
                _empty_state("Unable to project standard duration distribution parameters.", "📊")

        # Event log expander — fully configured dataframe
        with st.expander(
            "View full event log (sorted by duration, top 100)", expanded=False
        ):
            display_cols = [
                c for c in [
                    "network_element_id", "metric", "start", "end",
                    "duration_hours", "worst_value", "mean_value",
                    "threshold", "breach_direction",
                ]
                if c in deg.columns
            ]
            col_cfg: dict = {}
            if "duration_hours" in deg.columns:
                col_cfg["duration_hours"] = st.column_config.NumberColumn(
                    "Duration (h)", format="%.2f h"
                )
            if "metric" in deg.columns:
                col_cfg["metric"] = st.column_config.TextColumn("KPI metric")
            if "network_element_id" in deg.columns:
                col_cfg["network_element_id"] = st.column_config.TextColumn("Site ID")
            if "worst_value" in deg.columns:
                col_cfg["worst_value"] = st.column_config.NumberColumn(
                    "Worst value", format="%.3f"
                )
            if "mean_value" in deg.columns:
                col_cfg["mean_value"] = st.column_config.NumberColumn(
                    "Mean value", format="%.3f"
                )

            st.dataframe(
                deg.sort_values("duration_hours", ascending=False)
                   .head(100)[display_cols],
                use_container_width=True,
                hide_index=True,
                column_config=col_cfg,
            )
    else:
        _empty_state(
            "No sustained degradation events for the selected sites, "
            "or <code>kpi_degradation_periods.csv</code> hasn't been generated yet.",
            "✅",
        )

def tab_alarms(data: dict, nodes: list[str]) -> None:
    """Render the Noise Floor tab."""
    alarm_type     = data.get("alarm_type")
    alarm_severity = data.get("alarm_severity")
    alarm_ne       = _filter_ne(data.get("alarm_ne"), nodes)
    alarm_category = data.get("alarm_category")

    st.markdown(
        """<div class="tab-intro tab-intro--amber">
          <div>
            <div class="tab-intro__label">Noise Floor · Alarm volume profiling</div>
            <p class="tab-intro__body">
              The <b>Pareto chart</b> applies the 80/20 rule to alarm types — find the
              vital few that account for the bulk of noise. Severity and category charts
              show how urgent the problems are and where they cluster. Site charts
              respect the Node ID filter in the sidebar.
            </p>
          </div>
        </div>""",
        unsafe_allow_html=True,
    )

    # ── Pareto — full-width hero chart ────────────────────────────────────────
    _section_label(
        "The vital few — which alarm types are drowning out the signal",
        color=C_AMBER,
    )
    fig_p = _alarm_pareto(alarm_type)
    if fig_p:
        st.plotly_chart(fig_p, use_container_width=True)
        st.caption(
            "Pareto is computed fleet-wide. "
            "Per-site counts below respect the sidebar filter."
        )
    else:
        _empty_state("alarm_by_type.csv not found.", "📭")

    _section_gap()

    # ── Severity + Category — equal split ────────────────────────────────────
    col_a, col_b = st.columns(2)
    with col_a:
        _section_label("Severity breakdown", color=C_RED)
        fig_s = _alarm_severity_bar(alarm_severity)
        if fig_s:
            st.plotly_chart(fig_s, use_container_width=True)
        else:
            _empty_state("alarm_by_severity.csv not found.", "📊")

    with col_b:
        _section_label("Category distribution", color=C_TEAL)
        fig_d = _alarm_category_donut(alarm_category)
        if fig_d:
            st.plotly_chart(fig_d, use_container_width=True)
        else:
            _empty_state("alarm_by_category.csv not found.", "🍩")

    _section_gap()

    # ── Per-site stacked bar ──────────────────────────────────────────────────
    _section_label(
        "Per-site noise — which sites are generating the most alarms",
        color=C_AMBER,
    )
    ctrl_col, _ = st.columns([1, 3])
    with ctrl_col:
        max_sites = st.slider(
            "Sites to display",
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
    """Render the Root Cause tab."""
    ranked = data.get("corr_ranked")
    coo_df = data.get("corr_coo")

    st.markdown(
        """<div class="tab-intro tab-intro--purple">
          <div>
            <div class="tab-intro__label">Root Cause · Causal signal analysis</div>
            <p class="tab-intro__body">
              Two analytical engines run in parallel: <b>lag profile analysis</b>
              (does a KPI worsen in the hours <em>after</em> an alarm fires?) and
              <b>co-occurrence analysis</b> (does this alarm type frequently precede
              sustained KPI degradation?). The <em>combined score</em> (0–1) fuses
              both signals into a single root-cause rank.
            </p>
          </div>
        </div>""",
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

    # ── Priority scatter — full-width hero ────────────────────────────────────
    _section_label("Priority map — where to focus your investigation", color=C_PURPLE)
    st.caption(
        "Each bubble is an (alarm type, KPI) pair.  "
        "**X** = combined causal score · **Y** = alarm frequency · "
        "**Size** = co-occurrence rate · **Color** = priority tier"
    )
    fig_sc = _rc_scatter(ranked)
    st.plotly_chart(fig_sc, use_container_width=True)

    _section_gap()

    # ── Top candidates bar + co-occurrence heatmap ────────────────────────────
    col_a, col_b = st.columns([1, 1.1])

    with col_a:
        _section_label("Ranked candidates by causal strength", color=C_PURPLE)
        top_n = st.slider(
            "Show top N candidates",
            min_value=5,
            max_value=min(30, len(ranked)),
            value=min(15, len(ranked)),
            key="top_n_rc",
        )
        fig_bar = _rc_top_bar(ranked, top_n)
        st.plotly_chart(fig_bar, use_container_width=True)

    with col_b:
        _section_label("Co-occurrence heatmap — alarm × KPI", color=C_BLUE)
        st.caption(
            "Fraction of sustained KPI degradation events preceded by each alarm type "
            "within a 6-hour lookback window.  "
            "**1.0** = alarm always preceded that KPI degrading."
        )
        fig_heat = _rc_coo_heatmap(coo_df)
        if fig_heat:
            st.plotly_chart(fig_heat, use_container_width=True)
        else:
            _empty_state("correlation_cooccurrence.csv not found.", "🌡️")

    _section_gap()

    # ── Full candidate table ──────────────────────────────────────────────────
    with st.expander("Full root-cause candidate table", expanded=False):
        display_cols = [
            c for c in [
                "rank", "alarm_type", "kpi_metric",
                "combined_score", "lag_score", "cooccurrence_rate",
                "peak_lag_hours", "degrades_kpi",
                "n_alarm_events", "cooccurrence_count",
                "interpretation",
            ]
            if c in ranked.columns
        ]

        styled = ranked[display_cols].copy()
        if "kpi_metric" in styled.columns:
            styled["kpi_metric"] = styled["kpi_metric"].map(
                lambda v: KPI_LABELS.get(v, v)
            )

        col_cfg: dict = {}
        if "combined_score" in styled.columns:
            col_cfg["combined_score"] = st.column_config.ProgressColumn(
                "Combined score", max_value=1.0, format="%.3f"
            )
        if "lag_score" in styled.columns:
            col_cfg["lag_score"] = st.column_config.ProgressColumn(
                "Lag score", max_value=1.0, format="%.3f"
            )
        if "cooccurrence_rate" in styled.columns:
            col_cfg["cooccurrence_rate"] = st.column_config.ProgressColumn(
                "Co-occ. rate", max_value=1.0, format="%.3f"
            )
        if "interpretation" in styled.columns:
            col_cfg["interpretation"] = st.column_config.TextColumn(
                "Interpretation", width="large"
            )
        if "alarm_type" in styled.columns:
            col_cfg["alarm_type"] = st.column_config.TextColumn(
                "Alarm type", width="medium"
            )
        if "kpi_metric" in styled.columns:
            col_cfg["kpi_metric"] = st.column_config.TextColumn(
                "KPI metric", width="medium"
            )
        if "n_alarm_events" in styled.columns:
            col_cfg["n_alarm_events"] = st.column_config.NumberColumn(
                "Alarm events", format="%d"
            )
        if "peak_lag_hours" in styled.columns:
            col_cfg["peak_lag_hours"] = st.column_config.NumberColumn(
                "Peak lag (h)", format="%.1f h"
            )

        st.dataframe(
            styled,
            use_container_width=True,
            hide_index=True,
            column_config=col_cfg,
        )


# ─────────────────────────────────────────────────────────────────────────────
# 11.  MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    style_css()

    # Load data (cached, 5-min TTL)
    data = load_all()

    # Sidebar must run before header so node count is known
    selected_nodes = build_sidebar(data)

    # Header
    render_header(data, selected_nodes)

    # Headline KPI cards
    show_headline_cards(data, selected_nodes)

    _section_gap()

    # Main navigation — human-centric tab names
    tab1, tab2, tab3 = st.tabs([
        "📶  Signal Health",
        "📻  Noise Floor",
        "🔬  Root Cause",
    ])

    with tab1:
        tab_kpi(data, selected_nodes)

    with tab2:
        tab_alarms(data, selected_nodes)

    with tab3:
        tab_correlation(data)


if __name__ == "__main__":
    main()

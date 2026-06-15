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
gracefully with contextual warning banners instead of crashes.
"""

import warnings
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

# Phase 4 report directory (relative to project root where app.py lives)
PHASE4_REPORTS = Path("output") / "reports" / "phase4"

# ── Colour palette (aligned with Phase 4 matplotlib constants) ────────────────
C_BLUE     = "#2B5EA7"
C_AMBER    = "#E59500"
C_RED      = "#D64045"
C_GREEN    = "#3D9970"
C_PURPLE   = "#7B61FF"
C_TEAL     = "#1ABC9C"
C_GREY     = "#8A9BB0"
C_BG       = "#F8F9FA"

# Plotly severity colour map
SEV_COLOURS = {
    "Critical": C_RED,
    "Major":    C_AMBER,
    "Minor":    C_BLUE,
    "Warning":  C_GREEN,
}

# Human-readable KPI labels (mirrors Phase 4 KPI_LABELS)
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

# Common Plotly layout defaults
_LAYOUT_BASE = dict(
    plot_bgcolor="rgba(0,0,0,0)",   # Makes chart backgrounds transparent
    paper_bgcolor="rgba(0,0,0,0)",  # Failsafe container transparency
    font=dict(family="Inter, Arial, sans-serif", size=12, color="gray"), # Let theme colors guide primary elements
    margin=dict(l=10, r=10, t=30, b=10),
    hoverlabel=dict(bgcolor="rgba(255,255,255,0.9)", font_size=12),
)


# ═══════════════════════════════════════════════════════════════════════════════
# 1.  DATA LOADERS  — cached, graceful on missing files
# ═══════════════════════════════════════════════════════════════════════════════

def _load(filename: str, warn: bool = True) -> pd.DataFrame | None:
    """
    Load a Phase 4 CSV report.

    Returns the DataFrame on success, None on failure.
    Missing files emit a contextual Streamlit warning (not an exception).
    """
    path = PHASE4_REPORTS / filename
    if not path.exists():
        if warn:
            st.warning(
                f"⚠️  **Report not found:** `{path}`  \n"
                "Generate it by running `python main.py --phase 4` from the project root.",
            )
        return None
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception as exc:
        st.error(f"❌  Failed to load `{filename}`: {exc}")
        return None


@st.cache_data(ttl=300, show_spinner="Loading Phase 4 reports…")
def load_all() -> dict:
    """Load every Phase 4 CSV into memory once; cache for 5 minutes."""
    return {
        # ── KPI Trending ──────────────────────────────────────────────────────
        "breach_metric":   _load("breach_summary_per_metric.csv"),
        "breach_site":     _load("breach_summary_per_site.csv"),
        "breach_tech":     _load("breach_summary_per_technology.csv"),
        "breach_temporal": _load("breach_summary_temporal.csv"),
        "degradation":     _load("kpi_degradation_periods.csv"),
        # ── Alarm Frequency ───────────────────────────────────────────────────
        "alarm_type":      _load("alarm_by_type.csv"),
        "alarm_severity":  _load("alarm_by_severity.csv"),
        "alarm_hour":      _load("alarm_by_hour.csv", warn=False),   # pivot – optional
        "alarm_ne":        _load("alarm_by_ne.csv"),
        "alarm_category":  _load("alarm_by_category.csv"),
        # ── Correlation ───────────────────────────────────────────────────────
        "corr_lag":        _load("correlation_lag_summary.csv"),
        "corr_coo":        _load("correlation_cooccurrence.csv"),
        "corr_ranked":     _load("correlation_root_cause_candidates.csv"),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 2.  SIDEBAR — SITE FILTER  +  META CONTROLS
# ═══════════════════════════════════════════════════════════════════════════════

def _all_nodes(data: dict) -> list[str]:
    """Collect unique network_element_id values across all site-level tables."""
    ids: set[str] = set()
    for key in ("breach_site", "alarm_ne", "degradation"):
        df = data.get(key)
        if df is not None and "network_element_id" in df.columns:
            ids.update(df["network_element_id"].dropna().astype(str).unique())
    return sorted(ids)


def build_sidebar(data: dict) -> list[str]:
    """Render sidebar; return the user-selected node IDs."""
    with st.sidebar:
        # ── Brand header ──────────────────────────────────────────────────────
        st.markdown(
            """
            <div style="
                background: linear-gradient(135deg, #2B5EA7 0%, #1a3d6e 100%);
                border-radius: 10px;
                padding: 14px 18px 12px 18px;
                margin-bottom: 18px;
            ">
              <div style="color:#FFFFFF; font-size:18px; font-weight:700;
                          letter-spacing:0.5px; font-family: 'Arial Black', sans-serif;">
                📡 HFCL EMS
              </div>
              <div style="color:#A8C4F0; font-size:11px; margin-top:2px;">
                Network Analytics · Phase 5
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("### 🗂️ Filters")

        all_nodes = _all_nodes(data)
        if not all_nodes:
            st.info("No site data found. Run Phase 4 first.")
            return []

        # "Select All" toggle
        select_all = st.checkbox("Select all sites", value=True)

        selected: list[str] = st.multiselect(
            label="Site Node ID",
            options=all_nodes,
            default=all_nodes if select_all else [],
            help="Filter KPI trend and alarm charts by network element. "
                 "Correlation charts are fleet-wide and are not filtered.",
        )
        if not selected:
            st.caption("⚠️ No sites selected — showing all sites.")
            selected = all_nodes

        st.markdown("---")
        st.markdown("### ⚙️ Settings")
        if st.button("🔄 Refresh Data", width='stretch'):
            st.cache_data.clear()
            st.rerun()

        st.caption(
            f"📁 Reports: `{PHASE4_REPORTS}`  \n"
            "♻️ Cache TTL: 5 min"
        )

    return selected


def _filter_ne(df: pd.DataFrame | None, nodes: list[str]) -> pd.DataFrame | None:
    """Filter a DataFrame by network_element_id if the column exists."""
    if df is None or df.empty:
        return df
    if "network_element_id" in df.columns:
        return df[df["network_element_id"].astype(str).isin(nodes)].copy()
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# 3.  HEADLINE KPI CARDS
# ═══════════════════════════════════════════════════════════════════════════════

def show_headline_cards(data: dict, nodes: list[str]) -> None:
    """Four metric cards across the top of the dashboard."""
    breach_metric = data.get("breach_metric")
    breach_site   = _filter_ne(data.get("breach_site"), nodes)
    alarm_ne      = _filter_ne(data.get("alarm_ne"),    nodes)
    corr_ranked   = data.get("corr_ranked")

    c1, c2, c3, c4 = st.columns(4)

    # Card 1 — worst KPI metric by breach rate
    with c1:
        label, delta = "—", None
        if breach_metric is not None and not breach_metric.empty:
            row   = breach_metric.sort_values("breach_rate_pct", ascending=False).iloc[0]
            label = str(row.get("display_name", "—"))
            delta = f"{row.get('breach_rate_pct', 0):.1f}% breach rate"
        st.metric(
            "🔴 Highest-Breach KPI",
            label,
            delta=delta,
            delta_color="inverse",
            help="Fleet-wide KPI metric with the most threshold violations.",
        )

    # Card 2 — worst site by breach rate
    with c2:
        label, delta = "—", None
        if (breach_site is not None and not breach_site.empty
                and "any_breach_pct" in breach_site.columns):
            row   = breach_site.sort_values("any_breach_pct", ascending=False).iloc[0]
            label = str(row["network_element_id"])
            delta = f"{row['any_breach_pct']:.1f}% overall breach"
        st.metric(
            "📍 Worst Site (Breach %)",
            label,
            delta=delta,
            delta_color="inverse",
            help="Site with the highest proportion of KPI threshold violations.",
        )

    # Card 3 — total alarms for selected sites
    with c3:
        label = "—"
        noisiest = ""
        if alarm_ne is not None and not alarm_ne.empty:
            label    = f"{int(alarm_ne['total_alarms'].sum()):,}"
            noisiest = str(alarm_ne.sort_values("total_alarms", ascending=False)
                           .iloc[0]["network_element_id"])
        st.metric(
            "🔔 Total Alarms (Sites)",
            label,
            delta=f"Noisiest: {noisiest}" if noisiest else None,
            delta_color="off",
            help="Cumulative alarm count across all selected sites.",
        )

    # Card 4 — top root-cause candidate
    with c4:
        label, delta = "—", None
        if corr_ranked is not None and not corr_ranked.empty:
            row   = corr_ranked.iloc[0]
            kpi_d = KPI_LABELS.get(str(row.get("kpi_metric", "")),
                                   str(row.get("kpi_display", row.get("kpi_metric", "—"))))
            label = str(row.get("alarm_type", "—"))
            delta = f"→ {kpi_d}  score {row.get('combined_score', 0):.3f}"
        st.metric(
            "🔗 Top Root-Cause Alarm",
            label,
            delta=delta,
            delta_color="off",
            help="Alarm type with the strongest combined lag + co-occurrence evidence.",
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 4.  TAB 1 — KPI PERFORMANCE TRENDS
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

    bt = breach_temporal.copy()
    q75 = bt["breach_rate_pct"].quantile(0.75)
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
    # Peak-hour shading band
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
    # Sort sites by any_breach_pct desc if available
    if "any_breach_pct" in breach_site.columns:
        order = (breach_site.set_index("network_element_id")["any_breach_pct"]
                 .sort_values(ascending=False).index.tolist())
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


def tab_kpi(data: dict, nodes: list[str]) -> None:
    """Render the KPI Performance Trends tab."""
    st.subheader("📈 KPI Performance Trends")
    st.caption(
        "Threshold breach analysis from Phase 4. A *breach* is recorded each time a KPI "
        "crosses its SLA/operational limit. Degradation *events* are sustained windows of "
        "≥ 4 consecutive 15-minute intervals in breach (≥ 1 continuous hour)."
    )

    breach_metric   = data.get("breach_metric")
    breach_site     = _filter_ne(data.get("breach_site"),     nodes)
    breach_temporal = data.get("breach_temporal")
    degradation     = _filter_ne(data.get("degradation"),     nodes)

    # ── Row 1 : Metric bar + Hourly bar ──────────────────────────────────────
    col_a, col_b = st.columns([1.5, 1])

    with col_a:
        fig = _kpi_breach_by_metric(breach_metric)
        if fig:
            st.plotly_chart(fig, width='stretch')
        else:
            st.info("breach_summary_per_metric.csv not found.")

    with col_b:
        fig2 = _kpi_breach_by_hour(breach_temporal)
        if fig2:
            st.plotly_chart(fig2, width='stretch')
        else:
            st.info("breach_summary_temporal.csv not found.")

    st.markdown("---")

    # ── Row 2 : Site heatmap ─────────────────────────────────────────────────
    fig3 = _kpi_site_heatmap(breach_site)
    if fig3:
        st.plotly_chart(fig3, width='stretch')
    elif breach_site is not None and breach_site.empty:
        st.info("No matching sites for the current selection.")
    else:
        st.info("breach_summary_per_site.csv not found.")

    st.markdown("---")

    # ── Row 3 : Degradation period explorer ──────────────────────────────────
    st.markdown("##### ⏱️ Sustained Degradation Events")

    if degradation is not None and not degradation.empty:
        deg = degradation.copy()

        # Summary metrics
        mc1, mc2, mc3, mc4 = st.columns(4)
        mc1.metric("Total Events",     f"{len(deg):,}")
        mc2.metric("Sites Affected",
                   deg["network_element_id"].nunique() if "network_element_id" in deg.columns else "—")
        mc3.metric("Longest Event",
                   f"{deg['duration_hours'].max():.1f} h" if "duration_hours" in deg.columns else "—")
        top_kpi = (deg["metric"].value_counts().idxmax()
                   if "metric" in deg.columns and not deg["metric"].empty else "—")
        mc4.metric("Most Affected KPI", KPI_LABELS.get(top_kpi, top_kpi))

        # Duration histogram
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
            fig_dur.update_layout(**_LAYOUT_BASE, height=260,
                                   legend_title="KPI Metric",
                                   bargap=0.05)
            st.plotly_chart(fig_dur, width='stretch')

        # Detail table
        with st.expander("View event table (top 100 by duration)", expanded=False):
            display_cols = [c for c in [
                "network_element_id", "metric", "start", "end",
                "duration_hours", "worst_value", "mean_value", "threshold", "breach_direction",
            ] if c in deg.columns]
            st.dataframe(
                deg.sort_values("duration_hours", ascending=False)
                   .head(100)[display_cols],
                width='stretch',
                hide_index=True,
            )
    else:
        st.info(
            "kpi_degradation_periods.csv not available, or no sustained events "
            "exist for the selected sites."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 5.  TAB 2 — ALARM FREQUENCIES
# ═══════════════════════════════════════════════════════════════════════════════

def _alarm_pareto(alarm_type: pd.DataFrame | None) -> go.Figure | None:
    """Pareto combo chart: bars = alarm count by type, line = cumulative %."""
    if alarm_type is None or alarm_type.empty:
        return None

    at = alarm_type.sort_values("count", ascending=False).copy().reset_index(drop=True)
    if "cumulative_pct" not in at.columns:
        at["cumulative_pct"] = (at["count"].cumsum() / at["count"].sum() * 100).round(2)

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # Bars
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

    # Cumulative line
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

    # 80 % reference line
    fig.add_hline(y=80, secondary_y=True,
                  line_dash="dot", line_color=C_AMBER, line_width=1.5,
                  annotation_text=" 80% (Pareto)",
                  annotation_position="bottom right",
                  annotation_font_color=C_AMBER)

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
    fig.update_yaxes(title_text="Count",            secondary_y=False)
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
            marker=dict(colors=palette[:len(alarm_category)]),
        )
    )

    # Apply base layout properties first, then apply modifications sequentially
    fig.update_layout(**_LAYOUT_BASE)
    fig.update_layout(
        title="Alarm Category Distribution",
        margin=dict(l=10, r=10, t=40, b=10)
    )
    return fig


def _alarm_site_stacked(alarm_ne: pd.DataFrame | None, max_sites: int = 20) -> go.Figure | None:
    """Stacked horizontal bar: top sites by alarm volume, broken by severity."""
    if alarm_ne is None or alarm_ne.empty:
        return None

    ne = (alarm_ne.sort_values("total_alarms", ascending=False)
          .head(max_sites)
          .sort_values("total_alarms", ascending=True)   # ascending for horizontal bars
          .copy())

    sev_col_map = {
        "critical_count": "Critical",
        "major_count":    "Major",
        "minor_count":    "Minor",
        "warning_count":  "Warning",
    }
    available = {k: v for k, v in sev_col_map.items() if k in ne.columns}

    if not available:
        # Fallback: single bar
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
        fig.add_trace(go.Bar(
            x=ne[col],
            y=ne["network_element_id"],
            orientation="h",
            name=sev_label,
            marker_color=SEV_COLOURS.get(sev_label, C_GREY),
            hovertemplate=(
                f"<b>%{{y}}</b><br>{sev_label}: %{{x:,}}<extra></extra>"
            ),
        ))

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


def tab_alarms(data: dict, nodes: list[str]) -> None:
    """Render the Alarm Frequencies tab."""
    st.subheader("🔔 Alarm Frequencies")
    st.caption(
        "Alarm volume profiling from Phase 4. The **Pareto chart** identifies the vital few "
        "alarm types that account for the majority of events (Pareto 80/20 rule). "
        "Site-level charts respect the Node ID filter in the sidebar."
    )

    alarm_type     = data.get("alarm_type")
    alarm_severity = data.get("alarm_severity")
    alarm_ne       = _filter_ne(data.get("alarm_ne"), nodes)
    alarm_category = data.get("alarm_category")

    # ── Pareto chart (fleet-wide) ─────────────────────────────────────────────
    fig_p = _alarm_pareto(alarm_type)
    if fig_p:
        st.plotly_chart(fig_p, width='stretch')
        st.caption(
            "ℹ️ Pareto is computed fleet-wide. Individual site alarm counts are shown "
            "in the stacked bar chart below, which respects the sidebar filter."
        )
    else:
        st.info("alarm_by_type.csv not found.")

    st.markdown("---")

    # ── Severity breakdown + Category donut ───────────────────────────────────
    col_a, col_b = st.columns(2)

    with col_a:
        fig_s = _alarm_severity_bar(alarm_severity)
        if fig_s:
            st.plotly_chart(fig_s, width='stretch')
        else:
            st.info("alarm_by_severity.csv not found.")

    with col_b:
        fig_d = _alarm_category_donut(alarm_category)
        if fig_d:
            st.plotly_chart(fig_d, width='stretch')
        else:
            st.info("alarm_by_category.csv not found.")

    st.markdown("---")

    # ── Top sites stacked bar ─────────────────────────────────────────────────
    max_sites = st.slider("Max sites to display", 5, 30, 20, key="alarm_sites_slider")
    fig_ne = _alarm_site_stacked(alarm_ne, max_sites=max_sites)
    if fig_ne:
        st.plotly_chart(fig_ne, width='stretch')
    elif alarm_ne is not None and alarm_ne.empty:
        st.info("No alarm data for the selected sites.")
    else:
        st.info("alarm_by_ne.csv not found.")


# ═══════════════════════════════════════════════════════════════════════════════
# 6.  TAB 3 — ROOT-CAUSE CORRELATIONS
# ═══════════════════════════════════════════════════════════════════════════════

def _rc_scatter(ranked: pd.DataFrame) -> go.Figure:
    """
    Root-cause priority scatter map.

    X = combined_score (0–1),   Y = alarm event frequency,
    Size = co-occurrence rate,  Colour = priority band (H/M/L).
    """
    df = ranked.copy()
    df["cooccurrence_rate"] = df.get("cooccurrence_rate", pd.Series(0.0, index=df.index)).fillna(0.0)
    df["size_px"]  = (df["cooccurrence_rate"] * 80 + 8).clip(8, 80)
    df["kpi_disp"] = df["kpi_metric"].map(KPI_LABELS).fillna(
        df.get("kpi_display", df["kpi_metric"])
    )
    df["label"]    = df["alarm_type"] + "\n→ " + df["kpi_disp"]

    def _band(score: float) -> str:
        if score >= 0.66: return "HIGH"
        if score >= 0.33: return "MEDIUM"
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
            "combined_score":   "Combined Causal Score (0 → 1)",
            "n_alarm_events":   "Number of Alarm Events",
            "kpi_disp":         "Affected KPI",
            "cooccurrence_rate": "Co-occ. Rate",
        },
    )
    fig.update_traces(
        textposition="top center",
        textfont=dict(size=9, color="#333333"),
    )

    # Quadrant guides
    median_y = float(df["n_alarm_events"].median())
    fig.add_vline(x=0.5,      line_dash="dot", line_color=C_GREY, opacity=0.45)
    fig.add_hline(y=median_y, line_dash="dot", line_color=C_GREY, opacity=0.45)

    # Quadrant annotation
    x_max  = float(df["combined_score"].max())
    y_q90  = float(df["n_alarm_events"].quantile(0.85))
    y_q10  = float(df["n_alarm_events"].quantile(0.15))

    for txt, px_, py_, col in [
        ("High score / Frequent\n→ URGENT investigate", x_max * 0.88, y_q90, C_RED),
        ("High score / Rare\n→ Monitor", x_max * 0.88, y_q10, C_AMBER),
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
    df["label"]    = df["alarm_type"] + "  →  " + df["kpi_disp"]
    df = df.sort_values("combined_score", ascending=True)   # ascending for horizontal

    # Colour map: green → amber → red
    norm   = df["combined_score"] / max(df["combined_score"].max(), 1e-6)
    colours = [
        f"rgb({int(c[0]*255)},{int(c[1]*255)},{int(c[2]*255)})"
        for c in [
            (
                max(0, min(1, 2*(1-v))),      # R: 0 when v=0 → 1 when v>=0.5
                max(0, min(1, 2*v if v < 0.5 else 2*(1-v))),  # G: peaks at 0.5
                0,
            )
            for v in norm
        ]
    ]

    fig = go.Figure(
        go.Bar(
            x=df["combined_score"],
            y=df["label"],
            orientation="h",
            marker=dict(color=df["combined_score"].tolist(),
                        colorscale=[[0, C_GREEN], [0.5, C_AMBER], [1, C_RED]],
                        showscale=True,
                        colorbar=dict(title="Score", thickness=12, len=0.7)),
            text=df["combined_score"].apply(lambda v: f"{v:.3f}"),
            textposition="outside",
            hovertemplate=(
                "<b>%{y}</b><br>"
                "Combined Score : %{x:.3f}<br>"
                "<extra></extra>"
            ),
        )
    )

    # Base layout configurations followed by specific key overrides to prevent keyword collisions
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
            )
            .fillna(0)
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

    # Base layout configurations followed by specific key overrides to prevent keyword collisions
    fig.update_layout(**_LAYOUT_BASE)
    fig.update_layout(
        height=max(300, len(pivot) * 28 + 110),
        title="Co-Occurrence Rate: Alarm Type × KPI Metric",
        xaxis_tickangle=-35,
        margin=dict(l=10, r=10, t=40, b=80),
    )
    return fig


def tab_correlation(data: dict) -> None:
    """Render the Root-Cause Correlations tab."""
    st.subheader("🔗 Root-Cause Correlations")
    st.caption(
        "Phase 4 combined two analytical engines: **lag profile analysis** "
        "(does a KPI worsen in the hours *after* an alarm fires?) and "
        "**co-occurrence analysis** (does this alarm type frequently precede "
        "sustained KPI degradation events?). The *combined score* (0–1) fuses "
        "both signals into a single root-cause priority rank."
    )

    ranked  = data.get("corr_ranked")
    coo_df  = data.get("corr_coo")

    # Guard: nothing to show
    if ranked is None or ranked.empty:
        st.warning(
            "⚠️  **correlation_root_cause_candidates.csv** not found.  \n"
            "Run `python main.py --phase 4` to generate it.",
        )
        return

    ranked = ranked.copy()

    # ── Scatter priority map ─────────────────────────────────────────────────
    st.markdown("##### 🗺️ Root-Cause Priority Scatter Map")
    st.caption(
        "Each bubble = one (alarm type, KPI metric) pair. "
        "**X** = combined causal score (higher → stronger evidence). "
        "**Y** = how frequently this alarm type occurs. "
        "**Bubble size** = co-occurrence rate (fraction of degradation events "
        "this alarm preceded). "
        "Colour = priority tier."
    )
    fig_sc = _rc_scatter(ranked)
    st.plotly_chart(fig_sc, width='stretch')

    st.markdown("---")

    # ── Top candidates bar + Co-occurrence heatmap ────────────────────────────
    col_a, col_b = st.columns([1, 1.1])

    with col_a:
        top_n = st.slider(
            "Top N candidates to display",
            min_value=5,
            max_value=min(30, len(ranked)),
            value=min(15, len(ranked)),
            key="top_n_rc",
        )
        fig_bar = _rc_top_bar(ranked, top_n)
        st.plotly_chart(fig_bar, width='stretch')

    with col_b:
        st.markdown("##### Co-Occurrence Rate Heatmap")
        st.caption(
            "Fraction of sustained KPI degradation events preceded by each alarm type "
            "within a 6-hour lookback window.  "
            "A value of **1.0** means the alarm *always* occurred before that KPI degraded."
        )
        fig_heat = _rc_coo_heatmap(coo_df)
        if fig_heat:
            st.plotly_chart(fig_heat, width='stretch')
        else:
            st.info("correlation_cooccurrence.csv not found.")

    st.markdown("---")

    # ── Sortable data table ───────────────────────────────────────────────────
    st.markdown("##### 📋 Full Root-Cause Candidate Table")
    with st.expander("Expand ranked table", expanded=False):
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
            width='stretch',
            hide_index=True,
            column_config=col_cfg,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 7.  GLOBAL CUSTOM CSS
# ═══════════════════════════════════════════════════════════════════════════════

def inject_css() -> None:
    st.markdown(
        """
        <style>
        /* Safely adjust sidebar width only when it is active/expanded */
        [data-testid="stSidebar"][data-sidebar-user-expanded="true"] {
            min-width: 265px;
            max-width: 285px;
            width: 275px;
        }

        /* Metric card styling using responsive theme variables */
        [data-testid="stMetric"] {
            background: var(--background-color);      /* Uses dark bg in dark mode, light bg in light mode */
            border: 1px solid var(--secondary-background-color); 
            border-radius: 10px;
            padding: 12px 16px;
            border-left: 4px solid #2B5EA7;           /* Keep branding strip constant */
        }
        
        /* Force clear visibility overrides for metric elements */
        [data-testid="stMetricLabel"] { 
            font-size: 0.78rem; 
            color: var(--text-color) !important;      /* Dynamically flips between dark/light text */
            opacity: 0.8;
        }
        [data-testid="stMetricValue"] { 
            font-size: 1.15rem; 
            font-weight: 700; 
            color: var(--text-color) !important;      /* Dynamically flips between dark/light text */
        }

        /* Tab label styling */
        [data-testid="stTabs"] button {
            font-size: 0.88rem;
            font-weight: 600;
            padding: 6px 14px;
        }

        /* Remove excessive top padding on main content */
        .block-container { padding-top: 1.2rem; padding-bottom: 1rem; }

        /* Plotly chart container adjustments */
        .element-container iframe { 
            border-radius: 8px; 
            background: transparent !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 8.  MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    inject_css()

    # Page header
    col_title, col_badge = st.columns([5, 1])
    with col_title:
        st.title("📡 HFCL EMS — Network Analytics Dashboard")
        st.markdown(
            "**Phase 5 · Interactive Dashboard** — KPI breaches, alarm volumes, "
            "and root-cause correlations across 4G/5G network elements.  "
            "All data is sourced from Phase 4 report CSVs in `output/reports/phase4/`."
        )
    with col_badge:
        st.markdown(
            "<div style='text-align:right; margin-top:14px; "
            "color:#2B5EA7; font-size:0.8rem; font-weight:600;'>"
            "Phase 5 · v1.0</div>",
            unsafe_allow_html=True,
        )

    # Load data (cached)
    data = load_all()

    # Sidebar filters
    selected_nodes = build_sidebar(data)

    # Headline cards
    show_headline_cards(data, selected_nodes)
    st.markdown("---")

    # Navigation tabs
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
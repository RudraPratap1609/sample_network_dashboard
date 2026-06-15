"""
phase4_analysis/alarm_frequency.py
=====================================
Phase 4 — Alarm Frequency Analysis

Four dimensions of alarm frequency are computed and visualised:

  1. By alarm type      — Pareto chart; which alarm codes account for 80% of volume.
  2. By severity        — Severity distribution with MTTR (mean-time-to-repair) breakdown.
  3. By time of day     — Hour × severity heatmap; identify shift-specific patterns.
  4. By network element — Horizontal bar ranking; find the noisiest sites.

All plots are written to disk; no interactive windows are opened.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import seaborn as sns

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.logger import get_logger
from config.settings import SEVERITY_ORDER, ALARM_CATEGORY_MAP

log = get_logger(__name__)

# ── Colour palette ────────────────────────────────────────────────────────────

_SEVERITY_COLOURS = {
    "Critical": "#D64045",
    "Major":    "#E59500",
    "Minor":    "#2B5EA7",
    "Warning":  "#6C757D",
}
_DEFAULT_COLOURS = list(_SEVERITY_COLOURS.values())
_C_GRID = "#E0E0E0"


def _safe_mkdir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _apply_plot_style() -> None:
    plt.rcParams.update({
        "figure.facecolor":  "#F8F9FA",
        "axes.facecolor":    "#FFFFFF",
        "axes.spines.top":   False,
        "axes.spines.right": False,
        "grid.color":        _C_GRID,
        "grid.linestyle":    "--",
        "grid.alpha":        0.7,
        "font.size":         11,
        "axes.titlesize":    13,
        "axes.labelsize":    11,
    })


# ═══════════════════════════════════════════════════════════════════════════════
# 1. SUMMARY TABLES
# ═══════════════════════════════════════════════════════════════════════════════

def alarm_by_type_summary(alarm_df: pd.DataFrame) -> pd.DataFrame:
    """
    Summarise alarm volume per alarm type, sorted descending by count.

    Returns
    -------
    DataFrame with columns: alarm_type, alarm_category, count, pct_of_total,
    cumulative_pct, avg_duration_min, severity_mix (dict-as-str).
    """
    log.info("  Computing alarm frequency by type…")
    if alarm_df.empty or "alarm_type" not in alarm_df.columns:
        log.warning("    'alarm_type' column missing — returning empty summary.")
        return pd.DataFrame()

    total = len(alarm_df)
    grp = alarm_df.groupby("alarm_type")

    rows = []
    for alarm_type, g in grp:
        category = g["alarm_category"].mode().iloc[0] if "alarm_category" in g.columns and len(g) else "Unknown"
        sev_mix  = g["severity"].value_counts().to_dict() if "severity" in g.columns else {}
        avg_dur  = round(g["duration_minutes"].mean(), 1) if "duration_minutes" in g.columns else None
        rows.append({
            "alarm_type":          alarm_type,
            "alarm_category":      category,
            "count":               len(g),
            "pct_of_total":        round(len(g) / total * 100, 2),
            "avg_duration_min":    avg_dur,
            "severity_mix":        str(sev_mix),
        })

    df = pd.DataFrame(rows).sort_values("count", ascending=False).reset_index(drop=True)
    df["cumulative_pct"] = df["pct_of_total"].cumsum().round(2)
    log.info(f"    {len(df)} distinct alarm types — "
             f"top type: {df.iloc[0]['alarm_type']} ({df.iloc[0]['pct_of_total']:.1f}%)")
    return df


def alarm_by_severity_summary(alarm_df: pd.DataFrame) -> pd.DataFrame:
    """
    Summarise alarm volume per severity level, ordered by severity rank.

    Returns
    -------
    DataFrame with columns: severity, severity_rank, count, pct_of_total,
    avg_duration_min, median_duration_min, critical_sites (nunique NEs).
    """
    log.info("  Computing alarm frequency by severity…")
    if alarm_df.empty or "severity" not in alarm_df.columns:
        return pd.DataFrame()

    total = len(alarm_df)
    rows = []
    for sev, grp in alarm_df.groupby("severity"):
        rank = SEVERITY_ORDER.get(sev, 99)
        rows.append({
            "severity":            sev,
            "severity_rank":       rank,
            "count":               len(grp),
            "pct_of_total":        round(len(grp) / total * 100, 2),
            "avg_duration_min":    round(grp["duration_minutes"].mean(), 1)   if "duration_minutes" in grp else None,
            "median_duration_min": round(grp["duration_minutes"].median(), 1) if "duration_minutes" in grp else None,
            "affected_sites":      grp["network_element_id"].nunique() if "network_element_id" in grp else None,
        })

    df = pd.DataFrame(rows).sort_values("severity_rank").reset_index(drop=True)
    log.info(f"    Severity distribution: { {r['severity']: r['count'] for _, r in df.iterrows()} }")
    return df


def alarm_by_hour_summary(alarm_df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute alarm counts broken down by hour of day and severity.

    Returns a pivot table: rows = hour (0–23), columns = severity levels,
    values = alarm count.
    """
    log.info("  Computing alarm frequency by hour of day…")
    hr_col = "hour_of_day" if "hour_of_day" in alarm_df.columns else (
             "hour" if "hour" in alarm_df.columns else None)
    if hr_col is None or "severity" not in alarm_df.columns:
        log.warning("    Hour or severity column missing — skipping hourly breakdown.")
        return pd.DataFrame()

    pivot = (
        alarm_df.groupby([hr_col, "severity"])
                .size()
                .unstack(fill_value=0)
    )
    # Ensure all severity levels appear as columns, in severity order
    for sev in SEVERITY_ORDER:
        if sev not in pivot.columns:
            pivot[sev] = 0
    ordered_cols = [s for s in sorted(SEVERITY_ORDER, key=SEVERITY_ORDER.get) if s in pivot.columns]
    pivot = pivot[ordered_cols]
    pivot.index.name = "hour"
    pivot = pivot.reset_index()
    return pivot


def alarm_by_ne_summary(alarm_df: pd.DataFrame, top_n: int = 20) -> pd.DataFrame:
    """
    Rank network elements by total alarm volume and compute per-severity breakdown.

    Returns
    -------
    DataFrame with columns: network_element_id, region, technology, total_alarms,
    critical_count, major_count, minor_count, warning_count, avg_duration_min,
    sorted descending by total_alarms (top_n rows).
    """
    log.info(f"  Computing alarm frequency by network element (top {top_n})…")
    if alarm_df.empty or "network_element_id" not in alarm_df.columns:
        return pd.DataFrame()

    rows = []
    for ne, grp in alarm_df.groupby("network_element_id"):
        sev_counts = grp["severity"].value_counts() if "severity" in grp.columns else pd.Series(dtype=int)
        rows.append({
            "network_element_id": ne,
            "region":             grp["region"].mode().iloc[0]     if "region"     in grp.columns else "?",
            "technology":         grp["technology"].mode().iloc[0] if "technology" in grp.columns else "?",
            "total_alarms":       len(grp),
            "critical_count":     int(sev_counts.get("Critical", 0)),
            "major_count":        int(sev_counts.get("Major",    0)),
            "minor_count":        int(sev_counts.get("Minor",    0)),
            "warning_count":      int(sev_counts.get("Warning",  0)),
            "avg_duration_min":   round(grp["duration_minutes"].mean(), 1) if "duration_minutes" in grp else None,
            "site_mttr_min":      round(grp["site_mttr_min"].iloc[0],  1) if "site_mttr_min"    in grp else None,
        })

    df = (
        pd.DataFrame(rows)
          .sort_values("total_alarms", ascending=False)
          .head(top_n)
          .reset_index(drop=True)
    )
    log.info(f"    Noisiest site: {df.iloc[0]['network_element_id']} ({df.iloc[0]['total_alarms']} alarms)")
    return df


def alarm_by_category_summary(alarm_df: pd.DataFrame) -> pd.DataFrame:
    """
    Summarise alarm volume per root-cause category (Radio/Transport/Power/etc.)
    as defined in ALARM_CATEGORY_MAP from settings.

    Returns
    -------
    DataFrame with columns: alarm_category, count, pct_of_total,
    avg_duration_min, severity_mix.
    """
    log.info("  Computing alarm frequency by category…")
    if alarm_df.empty or "alarm_category" not in alarm_df.columns:
        log.warning("    'alarm_category' column missing — was Phase 3 ETL run?")
        return pd.DataFrame()

    total = len(alarm_df)
    rows = []
    for cat, grp in alarm_df.groupby("alarm_category"):
        sev_mix = grp["severity"].value_counts().to_dict() if "severity" in grp.columns else {}
        rows.append({
            "alarm_category":   cat,
            "count":            len(grp),
            "pct_of_total":     round(len(grp) / total * 100, 2),
            "avg_duration_min": round(grp["duration_minutes"].mean(), 1) if "duration_minutes" in grp else None,
            "severity_mix":     str(sev_mix),
        })

    return pd.DataFrame(rows).sort_values("count", ascending=False).reset_index(drop=True)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. PLOTTING FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def plot_alarm_type_pareto(
    alarm_df: pd.DataFrame,
    save_dir: str | Path,
    top_n: int = 15,
) -> None:
    """
    Pareto chart (bar + cumulative % line) for the top_n alarm types.

    The 80% cumulative line shows which alarm types account for the bulk
    of operational noise — a direct input to prioritisation decisions.
    """
    if alarm_df.empty or "alarm_type" not in alarm_df.columns:
        return

    _apply_plot_style()
    save_dir = _safe_mkdir(save_dir)

    counts = alarm_df["alarm_type"].value_counts().head(top_n)
    cum_pct = (counts.cumsum() / counts.sum() * 100)

    # Colour bars by severity mode per alarm type
    def severity_colour(atype: str) -> str:
        sub = alarm_df[alarm_df["alarm_type"] == atype]
        mode_sev = sub["severity"].mode().iloc[0] if len(sub) and "severity" in sub.columns else "Minor"
        return _SEVERITY_COLOURS.get(mode_sev, "#6C757D")

    colours = [severity_colour(t) for t in counts.index]

    fig, ax1 = plt.subplots(figsize=(13, 5))
    ax2 = ax1.twinx()

    bars = ax1.bar(range(len(counts)), counts.values, color=colours,
                   edgecolor="white", linewidth=0.5, zorder=2)
    ax2.plot(range(len(counts)), cum_pct.values, color="#1A1A2E",
             linewidth=2, marker="o", markersize=4, zorder=3, label="Cumulative %")
    ax2.axhline(80, color=_SEVERITY_COLOURS["Warning"], linewidth=1.2,
                linestyle="--", label="80% threshold")

    ax1.set_xticks(range(len(counts)))
    ax1.set_xticklabels(counts.index, rotation=30, ha="right", fontsize=9)
    ax1.set_ylabel("Alarm Count")
    ax1.set_xlabel("Alarm Type")
    ax2.set_ylabel("Cumulative % of Total Alarms")
    ax2.set_ylim(0, 105)
    ax2.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    ax1.grid(True, axis="y", zorder=0)

    # Legend for severity colours
    patches = [plt.Rectangle((0, 0), 1, 1, color=c, label=s)
               for s, c in _SEVERITY_COLOURS.items() if any(severity_colour(t) == c for t in counts.index)]
    handles, labels = ax2.get_legend_handles_labels()
    ax2.legend(loc="center right", framealpha=0.85)

    ax1.set_title(f"Alarm Type Pareto Chart — Top {top_n} Types", fontweight="bold", pad=12)
    plt.tight_layout()

    fname = save_dir / "alarm_type_pareto.png"
    plt.savefig(fname, dpi=130, bbox_inches="tight")
    plt.close(fig)
    log.info(f"  Saved: {fname}")


def plot_severity_distribution(
    alarm_df: pd.DataFrame,
    save_dir: str | Path,
) -> None:
    """
    Two-panel chart: (left) severity count bar chart, (right) MTTR box plot
    per severity. Together they show not just volume but operational impact.
    """
    if alarm_df.empty or "severity" not in alarm_df.columns:
        return

    _apply_plot_style()
    save_dir = _safe_mkdir(save_dir)

    sev_order = [s for s in sorted(SEVERITY_ORDER, key=SEVERITY_ORDER.get) if s in alarm_df["severity"].unique()]
    counts    = alarm_df["severity"].value_counts().reindex(sev_order, fill_value=0)
    colours   = [_SEVERITY_COLOURS.get(s, "#6C757D") for s in sev_order]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    # Left: count bar chart
    bars = ax1.bar(sev_order, counts.values, color=colours, edgecolor="white", linewidth=0.5)
    for bar, val in zip(bars, counts.values):
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + counts.max() * 0.01,
                 f"{val:,}", ha="center", va="bottom", fontsize=10, fontweight="bold")
    ax1.set_title("Alarm Count by Severity", fontweight="bold")
    ax1.set_xlabel("Severity Level")
    ax1.set_ylabel("Count")
    ax1.grid(True, axis="y")

    # Right: MTTR box plot per severity
    if "duration_minutes" in alarm_df.columns:
        data_by_sev = [alarm_df[alarm_df["severity"] == s]["duration_minutes"].dropna().values
                       for s in sev_order]
        bp = ax2.boxplot(data_by_sev, patch_artist=True, notch=False,
                         medianprops={"color": "black", "linewidth": 2},
                         whiskerprops={"linewidth": 1.2},
                         flierprops={"marker": "o", "markersize": 2.5, "alpha": 0.4})
        for patch, colour in zip(bp["boxes"], colours):
            patch.set_facecolor(colour)
            patch.set_alpha(0.75)
        ax2.set_xticks(range(1, len(sev_order) + 1))
        ax2.set_xticklabels(sev_order)
        ax2.set_title("MTTR Distribution by Severity", fontweight="bold")
        ax2.set_xlabel("Severity Level")
        ax2.set_ylabel("Duration (minutes)")
        ax2.set_yscale("log")
        ax2.grid(True, axis="y")
    else:
        ax2.text(0.5, 0.5, "'duration_minutes' not found", ha="center", va="center", transform=ax2.transAxes)

    plt.suptitle("Alarm Severity Analysis", fontsize=14, fontweight="bold", y=1.01)
    plt.tight_layout()

    fname = save_dir / "alarm_severity_distribution.png"
    plt.savefig(fname, dpi=130, bbox_inches="tight")
    plt.close(fig)
    log.info(f"  Saved: {fname}")


def plot_hourly_heatmap(
    alarm_df: pd.DataFrame,
    save_dir: str | Path,
) -> None:
    """
    Heatmap of alarm counts: rows = severity (Critical … Warning),
    columns = hour of day (00–23).

    Reveals shift-specific alarm patterns (e.g. overnight hardware failures,
    morning traffic surge alarms, or maintenance-window artefacts).
    """
    hr_col = "hour_of_day" if "hour_of_day" in alarm_df.columns else (
             "hour" if "hour" in alarm_df.columns else None)
    if hr_col is None or "severity" not in alarm_df.columns or alarm_df.empty:
        log.warning("  plot_hourly_heatmap: required columns missing — skipping.")
        return

    _apply_plot_style()
    save_dir = _safe_mkdir(save_dir)

    sev_order = [s for s in sorted(SEVERITY_ORDER, key=SEVERITY_ORDER.get) if s in alarm_df["severity"].unique()]
    pivot = (
        alarm_df.groupby(["severity", hr_col])
                .size()
                .unstack(fill_value=0)
                .reindex(sev_order)
    )
    # Ensure all 24 hours appear
    for h in range(24):
        if h not in pivot.columns:
            pivot[h] = 0
    pivot = pivot[sorted(pivot.columns)]

    fig, ax = plt.subplots(figsize=(15, 4))
    sns.heatmap(
        pivot,
        cmap="YlOrRd",
        linewidths=0.3,
        linecolor="#E8E8E8",
        cbar_kws={"label": "Alarm count", "shrink": 0.7},
        annot=True, fmt="d", annot_kws={"size": 7.5},
        ax=ax,
    )
    ax.set_title("Alarm Frequency Heatmap — Severity × Hour of Day", fontweight="bold", pad=12)
    ax.set_xlabel("Hour of Day")
    ax.set_ylabel("Severity")
    ax.set_xticklabels([f"{h:02d}:00" for h in sorted(pivot.columns)],
                       rotation=45, ha="right", fontsize=8)
    plt.tight_layout()

    fname = save_dir / "alarm_hourly_heatmap.png"
    plt.savefig(fname, dpi=130, bbox_inches="tight")
    plt.close(fig)
    log.info(f"  Saved: {fname}")


def plot_ne_alarm_ranking(
    alarm_df: pd.DataFrame,
    save_dir: str | Path,
    top_n: int = 20,
) -> None:
    """
    Horizontal stacked bar chart ranking the top_n noisiest network elements.

    Bars are stacked by severity so the chart shows both total volume and
    the criticality composition per site.
    """
    if alarm_df.empty or "network_element_id" not in alarm_df.columns:
        return

    _apply_plot_style()
    save_dir = _safe_mkdir(save_dir)

    sev_order = [s for s in sorted(SEVERITY_ORDER, key=SEVERITY_ORDER.get) if s in alarm_df["severity"].unique()]

    # Compute stacked counts per site
    pivot = (
        alarm_df.groupby(["network_element_id", "severity"])
                .size()
                .unstack(fill_value=0)
                .assign(total=lambda df: df.sum(axis=1))
                .sort_values("total", ascending=False)
                .head(top_n)
                .drop(columns="total")
    )
    for s in sev_order:
        if s not in pivot.columns:
            pivot[s] = 0
    pivot = pivot[sev_order]

    fig, ax = plt.subplots(figsize=(11, max(5, top_n * 0.45)))
    lefts = np.zeros(len(pivot))
    for sev in sev_order:
        values = pivot[sev].values
        colour = _SEVERITY_COLOURS.get(sev, "#6C757D")
        bars = ax.barh(pivot.index, values, left=lefts, color=colour,
                       label=sev, edgecolor="white", linewidth=0.4)
        lefts += values

    # Add total count label at end of each bar
    totals = pivot.sum(axis=1)
    for i, (ne, total) in enumerate(totals.items()):
        ax.text(total + totals.max() * 0.01, i, f"{int(total):,}",
                va="center", fontsize=8)

    ax.set_title(f"Top {top_n} Network Elements by Alarm Volume", fontweight="bold", pad=12)
    ax.set_xlabel("Alarm Count")
    ax.set_ylabel("Network Element ID")
    ax.legend(title="Severity", loc="lower right", framealpha=0.85)
    ax.grid(True, axis="x")
    plt.tight_layout()

    fname = save_dir / "alarm_ne_ranking.png"
    plt.savefig(fname, dpi=130, bbox_inches="tight")
    plt.close(fig)
    log.info(f"  Saved: {fname}")


def plot_alarm_category_donut(
    alarm_df: pd.DataFrame,
    save_dir: str | Path,
) -> None:
    """
    Donut chart showing alarm distribution across root-cause categories
    (Radio, Transport, Power, Hardware, Software).
    """
    if alarm_df.empty or "alarm_category" not in alarm_df.columns:
        return

    _apply_plot_style()
    save_dir = _safe_mkdir(save_dir)

    cat_counts = alarm_df["alarm_category"].value_counts()
    colours = plt.cm.Set2.colors

    fig, ax = plt.subplots(figsize=(7, 6))
    wedges, texts, autotexts = ax.pie(
        cat_counts.values,
        labels=cat_counts.index,
        autopct="%1.1f%%",
        startangle=90,
        colors=colours[:len(cat_counts)],
        wedgeprops={"width": 0.55, "edgecolor": "white", "linewidth": 1.5},
        pctdistance=0.78,
    )
    for t in autotexts:
        t.set_fontsize(9)
    ax.set_title("Alarm Distribution by Root-Cause Category", fontweight="bold", pad=12)
    plt.tight_layout()

    fname = save_dir / "alarm_category_donut.png"
    plt.savefig(fname, dpi=130, bbox_inches="tight")
    plt.close(fig)
    log.info(f"  Saved: {fname}")


# ═══════════════════════════════════════════════════════════════════════════════
# 3. MAIN RUNNER
# ═══════════════════════════════════════════════════════════════════════════════

def run_alarm_frequency_analysis(
    alarm_df: pd.DataFrame,
    save_dir: str | Path,
    generate_plots: bool = True,
    top_n_sites: int = 20,
) -> dict:
    """
    Orchestrate all Phase 4 alarm frequency analyses.

    Parameters
    ----------
    alarm_df       : Processed alarm DataFrame from Phase 3 ETL.
    save_dir       : Base output directory.
    generate_plots : If False, skip all matplotlib output.
    top_n_sites    : Number of sites to show in the network-element ranking.

    Returns
    -------
    dict with keys:
      'by_type'       : DataFrame — alarm frequency by type
      'by_severity'   : DataFrame — alarm frequency by severity
      'by_hour'       : DataFrame — hourly pivot (hour × severity)
      'by_ne'         : DataFrame — alarm ranking by network element
      'by_category'   : DataFrame — alarm frequency by category
      'highlights'    : dict of scalar findings
    """
    log.info("=" * 65)
    log.info("PHASE 4 — Alarm Frequency Analysis")
    log.info("=" * 65)

    plots_dir   = _safe_mkdir(Path(save_dir) / "plots"   / "phase4" / "alarm_frequency")
    reports_dir = _safe_mkdir(Path(save_dir) / "reports" / "phase4")

    # ── Summary tables ────────────────────────────────────────────────────────
    by_type      = alarm_by_type_summary(alarm_df)
    by_severity  = alarm_by_severity_summary(alarm_df)
    by_hour      = alarm_by_hour_summary(alarm_df)
    by_ne        = alarm_by_ne_summary(alarm_df, top_n=top_n_sites)
    by_category  = alarm_by_category_summary(alarm_df)

    # Save tables
    for name, df in [("alarm_by_type", by_type), ("alarm_by_severity", by_severity),
                     ("alarm_by_hour", by_hour), ("alarm_by_ne", by_ne), ("alarm_by_category", by_category)]:
        if not df.empty:
            out = reports_dir / f"{name}.csv"
            df.to_csv(out, index=False)
            log.info(f"  Saved report: {out}")

    # ── Highlights ─────────────────────────────────────────────────────────────
    top_type     = by_type.iloc[0]["alarm_type"] if len(by_type) else "N/A"
    top_type_pct = by_type.iloc[0]["pct_of_total"] if len(by_type) else None
    top_sev      = by_severity.iloc[0]["severity"] if len(by_severity) else "N/A"
    top_ne       = by_ne.iloc[0]["network_element_id"] if len(by_ne) else "N/A"

    # How many types needed to reach 80% (Pareto 80/20 rule)
    pareto_80 = None
    if "cumulative_pct" in by_type.columns:
        pareto_mask = by_type[by_type["cumulative_pct"] >= 80]
        pareto_80 = int(pareto_mask.index[0]) + 1 if len(pareto_mask) else len(by_type)

    highlights = {
        "top_alarm_type":            top_type,
        "top_alarm_type_pct":        top_type_pct,
        "dominant_severity":         top_sev,
        "noisiest_site":             top_ne,
        "noisiest_site_alarm_count": int(by_ne.iloc[0]["total_alarms"]) if len(by_ne) else None,
        "pareto_80_type_count":      pareto_80,
        "total_alarms":              len(alarm_df),
        "distinct_alarm_types":      alarm_df["alarm_type"].nunique() if "alarm_type" in alarm_df.columns else None,
    }

    log.info(f"  Top alarm type  : {top_type} ({top_type_pct}% of total)")
    log.info(f"  Pareto 80/20    : {pareto_80} alarm types → 80% of volume")
    log.info(f"  Noisiest site   : {top_ne} ({highlights['noisiest_site_alarm_count']} alarms)")

    # ── Plots ─────────────────────────────────────────────────────────────────
    if generate_plots:
        log.info("  Generating alarm frequency plots…")
        plot_alarm_type_pareto(alarm_df, plots_dir)
        plot_severity_distribution(alarm_df, plots_dir)
        plot_hourly_heatmap(alarm_df, plots_dir)
        plot_ne_alarm_ranking(alarm_df, plots_dir, top_n=top_n_sites)
        plot_alarm_category_donut(alarm_df, plots_dir)
        log.info(f"  All alarm frequency plots saved to: {plots_dir}")

    log.info("PHASE 4 — Alarm Frequency Analysis complete.")
    return {
        "by_type":      by_type,
        "by_severity":  by_severity,
        "by_hour":      by_hour,
        "by_ne":        by_ne,
        "by_category":  by_category,
        "highlights":   highlights,
        "plot_dir":     plots_dir,
        "reports_dir":  reports_dir,
    }
"""
phase2_ingestion/alarm_profiler.py
====================================
Phase 2 — Alarm Table Profiling

Produces:
  1. Console schema report (shape, null %, severity & status breakdown).
  2. Alarm type frequency bar chart.
  3. Severity distribution (bar + pie).
  4. Temporal patterns — alarms by hour-of-day, day-of-week.
  5. Per-site alarm count heatmap.
  6. Duration box-plot by severity.
  7. (Optional) ydata-profiling HTML report.
"""

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import seaborn as sns
import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.logger import get_logger
from config.settings import PATHS, SEVERITY_ORDER

log = get_logger(__name__)

# Consistent colour palette keyed by severity
SEVERITY_COLORS = {
    "Critical": "#D94F3D",
    "Major":    "#E8953F",
    "Minor":    "#F5C842",
    "Warning":  "#5BA85A",
}


# ─────────────────────────────────────────────────────────────────────────────
# 1. Schema & Quality Report
# ─────────────────────────────────────────────────────────────────────────────

def profile_alarms(df: pd.DataFrame) -> dict:
    """
    Print a detailed schema and quality report for the alarm DataFrame.

    Returns
    -------
    dict with keys: n_rows, n_sites, date_range, null_pct,
                    severity_counts, status_counts, alarm_type_counts,
                    duration_stats.
    """
    BORDER = "=" * 65
    log.info(BORDER)
    log.info("PHASE 2 — Alarm Table Profile")
    log.info(BORDER)

    n_rows, n_cols = df.shape
    sites = sorted(df["network_element_id"].unique())
    date_min = df["timestamp"].min()
    date_max = df["timestamp"].max()

    log.info(f"  Rows      : {n_rows:,}")
    log.info(f"  Columns   : {n_cols}")
    log.info(f"  Sites     : {len(sites)}  →  {sites}")
    log.info(f"  Date range: {date_min}  →  {date_max}")

    # ── Null analysis ────────────────────────────────────────────────────────
    log.info("")
    log.info("  Null / missing values:")
    null_pct = (df.isnull().sum() / n_rows * 100).round(2)
    for col, pct in null_pct.items():
        status = "  ⚠" if pct > 0 else "  ✔"
        log.info(f"{status}  {col:<26} {pct:5.2f} % missing")

    # ── Severity distribution ────────────────────────────────────────────────
    log.info("")
    log.info("  Severity distribution:")
    severity_counts = df["severity"].value_counts()
    for sev in sorted(severity_counts.index, key=lambda s: SEVERITY_ORDER.get(s, 99)):
        log.info(f"    {sev:<10} {severity_counts[sev]:4d}  ({severity_counts[sev]/n_rows*100:.1f} %)")

    # ── Status distribution ──────────────────────────────────────────────────
    log.info("")
    log.info("  Status distribution:")
    status_counts = df["status"].value_counts()
    for st, cnt in status_counts.items():
        log.info(f"    {st:<12} {cnt:4d}  ({cnt/n_rows*100:.1f} %)")

    # Active alarms (not yet cleared) → no duration or cleared_timestamp
    active_alarms = df[df["status"] == "Active"]
    if len(active_alarms):
        log.info(f"\n  ⚠  {len(active_alarms)} alarm(s) still ACTIVE (cleared_timestamp = NaT)")
        log.info(f"      Sites: {active_alarms['network_element_id'].tolist()}")
        log.info(f"      Types: {active_alarms['alarm_type'].tolist()}")

    # ── Alarm type frequency ─────────────────────────────────────────────────
    log.info("")
    log.info("  Alarm type frequency (top 12):")
    alarm_type_counts = df["alarm_type"].value_counts().head(12)
    for atype, cnt in alarm_type_counts.items():
        log.info(f"    {atype:<30} {cnt:4d}")

    # ── Duration stats ───────────────────────────────────────────────────────
    log.info("")
    log.info("  Alarm duration (minutes) — cleared alarms only:")
    dur = df["duration_minutes"].dropna()
    duration_stats = dur.describe().round(1).to_dict()
    log.info(f"    Mean  {duration_stats['mean']:6.1f} min")
    log.info(f"    Std   {duration_stats['std']:6.1f} min")
    log.info(f"    Min   {duration_stats['min']:6.1f} min")
    log.info(f"    Max   {duration_stats['max']:6.1f} min")

    log.info("")
    log.info("  Duration by severity (mean):")
    dur_by_sev = (
        df.dropna(subset=["duration_minutes"])
          .groupby("severity")["duration_minutes"]
          .mean()
          .round(1)
    )
    for sev in sorted(dur_by_sev.index, key=lambda s: SEVERITY_ORDER.get(s, 99)):
        log.info(f"    {sev:<10} {dur_by_sev[sev]:5.1f} min avg")

    log.info(BORDER)

    return {
        "n_rows": n_rows,
        "n_sites": len(sites),
        "date_range": (date_min, date_max),
        "null_pct": null_pct.to_dict(),
        "severity_counts": severity_counts.to_dict(),
        "status_counts": status_counts.to_dict(),
        "alarm_type_counts": alarm_type_counts.to_dict(),
        "duration_stats": duration_stats,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 2. Alarm Type Frequency Chart
# ─────────────────────────────────────────────────────────────────────────────

def plot_alarm_type_frequency(
    df: pd.DataFrame,
    top_n: int = 12,
    save_dir: str = None,
) -> None:
    """Horizontal bar chart of top_n most frequent alarm types."""
    save_dir = Path(save_dir or PATHS["plots"])
    save_dir.mkdir(parents=True, exist_ok=True)

    counts = df["alarm_type"].value_counts().head(top_n).sort_values()

    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.barh(counts.index, counts.values, color="#4878CF", edgecolor="white", linewidth=0.5)

    # Annotate bars with count
    for bar, val in zip(bars, counts.values):
        ax.text(bar.get_width() + 0.3, bar.get_y() + bar.get_height() / 2,
                str(val), va="center", ha="left", fontsize=9)

    ax.set_xlabel("Number of alarms", fontsize=10)
    ax.set_title(f"Top {top_n} Alarm Types — Frequency", fontsize=12, fontweight="bold")
    ax.grid(True, axis="x", alpha=0.3, linestyle="--")
    ax.xaxis.set_major_locator(mticker.MaxNLocator(integer=True))

    plt.tight_layout()
    fname = save_dir / "alarm_type_frequency.png"
    plt.savefig(fname, dpi=130, bbox_inches="tight")
    plt.close()
    log.info(f"Alarm type frequency chart saved → {fname}")


# ─────────────────────────────────────────────────────────────────────────────
# 3. Severity Distribution
# ─────────────────────────────────────────────────────────────────────────────

def plot_severity_distribution(df: pd.DataFrame, save_dir: str = None) -> None:
    """Stacked bar (count + %) and pie chart of alarm severity."""
    save_dir = Path(save_dir or PATHS["plots"])
    save_dir.mkdir(parents=True, exist_ok=True)

    order  = [s for s in SEVERITY_ORDER if s in df["severity"].unique()]
    counts = df["severity"].value_counts().reindex(order).fillna(0).astype(int)
    colors = [SEVERITY_COLORS.get(s, "#888888") for s in order]

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    fig.suptitle("Alarm Severity Distribution", fontsize=13, fontweight="bold")

    # Bar chart
    ax = axes[0]
    bars = ax.bar(counts.index, counts.values, color=colors, edgecolor="white", linewidth=0.5)
    for bar, val in zip(bars, counts.values):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.4,
                str(val), ha="center", va="bottom", fontsize=10, fontweight="bold")
    ax.set_xlabel("Severity", fontsize=10)
    ax.set_ylabel("Count", fontsize=10)
    ax.set_title("Count by severity", fontsize=10)
    ax.grid(True, axis="y", alpha=0.3, linestyle="--")

    # Pie chart
    ax2 = axes[1]
    wedges, texts, autotexts = ax2.pie(
        counts.values,
        labels=counts.index,
        colors=colors,
        autopct="%1.1f%%",
        startangle=90,
        wedgeprops=dict(edgecolor="white", linewidth=1),
    )
    for at in autotexts:
        at.set_fontsize(9)
    ax2.set_title("Share by severity", fontsize=10)

    plt.tight_layout()
    fname = save_dir / "alarm_severity_distribution.png"
    plt.savefig(fname, dpi=130, bbox_inches="tight")
    plt.close()
    log.info(f"Severity distribution chart saved → {fname}")


# ─────────────────────────────────────────────────────────────────────────────
# 4. Temporal Patterns
# ─────────────────────────────────────────────────────────────────────────────

def plot_alarm_temporal_patterns(df: pd.DataFrame, save_dir: str = None) -> None:
    """
    Two subplots:
      (a) Alarm count by hour-of-day, coloured by severity.
      (b) Alarm count by day-of-week, coloured by severity.
    """
    save_dir = Path(save_dir or PATHS["plots"])
    save_dir.mkdir(parents=True, exist_ok=True)

    df2 = df.copy()
    df2["hour"]       = df2["timestamp"].dt.hour
    df2["dayofweek"]  = df2["timestamp"].dt.dayofweek   # 0=Mon
    day_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    order = [s for s in SEVERITY_ORDER if s in df2["severity"].unique()]

    fig, axes = plt.subplots(1, 2, figsize=(16, 5))
    fig.suptitle("Alarm Temporal Patterns", fontsize=13, fontweight="bold")

    # Hour-of-day
    ax = axes[0]
    hour_sev = (
        df2.groupby(["hour", "severity"])
           .size()
           .unstack("severity")
           .reindex(columns=order, fill_value=0)
    )
    hour_sev.plot.bar(
        ax=ax, stacked=True,
        color=[SEVERITY_COLORS[s] for s in order],
        edgecolor="white", linewidth=0.3, width=0.8,
    )
    ax.set_xlabel("Hour of day (0–23)", fontsize=10)
    ax.set_ylabel("Alarm count", fontsize=10)
    ax.set_title("Alarms by hour of day", fontsize=10)
    ax.tick_params(axis="x", rotation=0, labelsize=8)
    ax.legend(title="Severity", fontsize=8)
    ax.grid(True, axis="y", alpha=0.3, linestyle="--")

    # Day-of-week
    ax2 = axes[1]
    dow_sev = (
        df2.groupby(["dayofweek", "severity"])
           .size()
           .unstack("severity")
           .reindex(columns=order, fill_value=0)
    )
    dow_sev.index = [day_labels[i] for i in dow_sev.index]
    dow_sev.plot.bar(
        ax=ax2, stacked=True,
        color=[SEVERITY_COLORS[s] for s in order],
        edgecolor="white", linewidth=0.3, width=0.65,
    )
    ax2.set_xlabel("Day of week", fontsize=10)
    ax2.set_ylabel("Alarm count", fontsize=10)
    ax2.set_title("Alarms by day of week", fontsize=10)
    ax2.tick_params(axis="x", rotation=0, labelsize=9)
    ax2.legend(title="Severity", fontsize=8)
    ax2.grid(True, axis="y", alpha=0.3, linestyle="--")

    plt.tight_layout()
    fname = save_dir / "alarm_temporal_patterns.png"
    plt.savefig(fname, dpi=130, bbox_inches="tight")
    plt.close()
    log.info(f"Temporal patterns chart saved → {fname}")


# ─────────────────────────────────────────────────────────────────────────────
# 5. Per-Site Alarm Heatmap
# ─────────────────────────────────────────────────────────────────────────────

def plot_alarm_site_heatmap(df: pd.DataFrame, save_dir: str = None) -> None:
    """Heatmap: alarm type (rows) × site (columns) — count of alarms."""
    save_dir = Path(save_dir or PATHS["plots"])
    save_dir.mkdir(parents=True, exist_ok=True)

    pivot = (
        df.groupby(["alarm_type", "network_element_id"])
          .size()
          .unstack("network_element_id")
          .fillna(0)
          .astype(int)
    )

    fig, ax = plt.subplots(figsize=(14, 7))
    sns.heatmap(
        pivot, ax=ax,
        cmap="YlOrRd",
        linewidths=0.4,
        linecolor="white",
        annot=True,
        fmt="d",
        annot_kws={"size": 8},
        cbar_kws={"label": "Alarm count"},
    )
    ax.set_title("Alarm Count — Type × Site", fontsize=12, fontweight="bold")
    ax.set_xlabel("Site", fontsize=10)
    ax.set_ylabel("Alarm type", fontsize=10)
    ax.tick_params(axis="y", labelsize=9)
    plt.tight_layout()
    fname = save_dir / "alarm_site_heatmap.png"
    plt.savefig(fname, dpi=130, bbox_inches="tight")
    plt.close()
    log.info(f"Site heatmap saved → {fname}")


# ─────────────────────────────────────────────────────────────────────────────
# 6. Duration by Severity
# ─────────────────────────────────────────────────────────────────────────────

def plot_duration_by_severity(df: pd.DataFrame, save_dir: str = None) -> None:
    """Box-plot of alarm duration (minutes) stratified by severity."""
    save_dir = Path(save_dir or PATHS["plots"])
    save_dir.mkdir(parents=True, exist_ok=True)

    cleared = df.dropna(subset=["duration_minutes"])
    order   = [s for s in SEVERITY_ORDER if s in cleared["severity"].unique()]

    fig, ax = plt.subplots(figsize=(9, 5))
    groups = [cleared[cleared["severity"] == sev]["duration_minutes"].values for sev in order]
    colors = [SEVERITY_COLORS.get(s, "#888") for s in order]

    bp = ax.boxplot(groups, labels=order, patch_artist=True, notch=False,
                    medianprops=dict(color="black", linewidth=2))
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.75)

    ax.set_xlabel("Severity", fontsize=10)
    ax.set_ylabel("Duration (minutes)", fontsize=10)
    ax.set_title("Alarm Duration Distribution by Severity", fontsize=12, fontweight="bold")
    ax.grid(True, axis="y", alpha=0.3, linestyle="--")

    plt.tight_layout()
    fname = save_dir / "alarm_duration_by_severity.png"
    plt.savefig(fname, dpi=130, bbox_inches="tight")
    plt.close()
    log.info(f"Duration boxplot saved → {fname}")


# ─────────────────────────────────────────────────────────────────────────────
# 7. Optional HTML Profiling Report
# ─────────────────────────────────────────────────────────────────────────────

def generate_alarm_profiling_report(df: pd.DataFrame, save_dir: str = None) -> None:
    """Generate a ydata-profiling HTML report for the alarm DataFrame."""
    try:
        from ydata_profiling import ProfileReport
    except ImportError:
        log.warning("ydata-profiling not installed. Skipping HTML report.")
        return

    save_dir = Path(save_dir or PATHS["profiling"])
    save_dir.mkdir(parents=True, exist_ok=True)

    log.info("Generating alarm profiling HTML report…")
    profile = ProfileReport(df, title="HFCL EMS — Alarm Data Profile", minimal=True)
    out = save_dir / "alarm_profile_report.html"
    profile.to_file(out)
    log.info(f"Alarm profiling report saved → {out}")


# ─────────────────────────────────────────────────────────────────────────────
# Convenience runner
# ─────────────────────────────────────────────────────────────────────────────

def run_alarm_profiling(df: pd.DataFrame, generate_html_report: bool = False) -> dict:
    """Run all alarm profiling steps."""
    summary = profile_alarms(df)
    plot_alarm_type_frequency(df)
    plot_severity_distribution(df)
    plot_alarm_temporal_patterns(df)
    plot_alarm_site_heatmap(df)
    plot_duration_by_severity(df)
    if generate_html_report:
        generate_alarm_profiling_report(df)
    return summary


if __name__ == "__main__":
    from phase2_ingestion.data_loader import load_alarm_data
    alarm = load_alarm_data()
    run_alarm_profiling(alarm)
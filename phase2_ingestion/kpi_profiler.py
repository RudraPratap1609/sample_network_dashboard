"""
phase2_ingestion/kpi_profiler.py
=================================
Phase 2 — KPI Table Profiling

Produces:
  1. Console schema report (shape, granularity, null %, per-metric stats).
  2. Distribution plots (histograms + boxplots) saved to outputs/plots/.
  3. Time-series trend plots per site for selected KPIs.
  4. (Optional) Full ydata-profiling HTML report in outputs/profiling_reports/.

All functions accept a raw or lightly cleaned DataFrame and return either
a printed report or a dict of computed stats — making them reusable in
Phase 4 analysis as well.
"""

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")   # non-interactive backend for headless environments
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import seaborn as sns
import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.logger import get_logger
from config.settings import PATHS, KPI_THRESHOLDS, KPI_DEFINITIONS

log = get_logger(__name__)

# Numeric KPI columns (exclude ID / timestamp / categorical columns)
KPI_METRICS = [
    "throughput_mbps",
    "availability_pct",
    "utilization_pct",
    "latency_ms",
    "rtwp_dbm",
    "handover_success_rate_pct",
    "call_drop_rate_pct",
    "rach_success_rate_pct",
]


# ─────────────────────────────────────────────────────────────────────────────
# 1. Schema & Quality Report
# ─────────────────────────────────────────────────────────────────────────────

def profile_kpi(df: pd.DataFrame) -> dict:
    """
    Print a detailed schema and data quality report for the KPI DataFrame.
    Returns a summary dict for programmatic use.

    Parameters
    ----------
    df : Raw or minimally preprocessed KPI DataFrame.

    Returns
    -------
    dict with keys: n_rows, n_sites, granularity_minutes, date_range,
                    null_pct (per column), stats (per metric).
    """
    BORDER = "=" * 65
    log.info(BORDER)
    log.info("PHASE 2 — KPI Table Profile")
    log.info(BORDER)

    # ── Basic shape ──────────────────────────────────────────────────────────
    n_rows, n_cols = df.shape
    sites          = sorted(df["network_element_id"].unique())
    technologies   = sorted(df["technology"].unique())
    regions        = sorted(df["region"].unique())

    ts_sorted = df["timestamp"].sort_values()
    date_min  = ts_sorted.iloc[0]
    date_max  = ts_sorted.iloc[-1]

    # Infer granularity from mode of consecutive timestamp diffs per site
    deltas = (
        df.sort_values(["network_element_id", "timestamp"])
          .groupby("network_element_id")["timestamp"]
          .diff()
          .dropna()
    )
    granularity_minutes = int(deltas.mode().iloc[0].total_seconds() / 60)

    log.info(f"  Rows        : {n_rows:,}")
    log.info(f"  Columns     : {n_cols}")
    log.info(f"  Sites       : {len(sites)}  →  {sites}")
    log.info(f"  Technologies: {technologies}")
    log.info(f"  Regions     : {regions}")
    log.info(f"  Date range  : {date_min}  →  {date_max}")
    log.info(f"  Granularity : {granularity_minutes} minutes per record per site")
    log.info(f"  Expected rows per site: {int((date_max - date_min).total_seconds() / (granularity_minutes * 60)) + 1}")

    # ── Null analysis ────────────────────────────────────────────────────────
    log.info("")
    log.info("  Null / missing values:")
    null_pct = (df.isnull().sum() / n_rows * 100).round(2)
    for col, pct in null_pct.items():
        status = "  ⚠" if pct > 0 else "  ✔"
        log.info(f"{status}  {col:<34} {pct:5.2f} % missing")

    # ── Per-metric descriptive stats ─────────────────────────────────────────
    log.info("")
    log.info("  KPI descriptive statistics:")
    log.info(f"  {'Metric':<34} {'Min':>8} {'Mean':>8} {'Median':>8} {'Max':>8} {'Std':>8} {'Threshold'}")
    log.info("  " + "-" * 88)

    stats = {}
    for metric in KPI_METRICS:
        if metric not in df.columns:
            log.warning(f"  Column '{metric}' not found — skipping")
            continue
        col = df[metric].dropna()
        direction, threshold = KPI_THRESHOLDS[metric]
        breach_mask = col > threshold if direction == "above" else col < threshold
        breach_pct  = breach_mask.mean() * 100
        stats[metric] = {
            "min": col.min(), "mean": col.mean(), "median": col.median(),
            "max": col.max(), "std": col.std(), "breach_pct": breach_pct,
        }
        log.info(
            f"  {'  ' + metric:<34} "
            f"{col.min():8.2f} {col.mean():8.2f} {col.median():8.2f} "
            f"{col.max():8.2f} {col.std():8.2f}  "
            f"{'>' if direction == 'above' else '<'}{threshold} "
            f"({breach_pct:.1f}% breach)"
        )

    # ── Technology breakdown ─────────────────────────────────────────────────
    log.info("")
    log.info("  Rows by technology:")
    for tech, count in df["technology"].value_counts().items():
        log.info(f"    {tech:<6} {count:,}")

    log.info("")
    log.info("  Rows by region:")
    for region, count in df["region"].value_counts().items():
        log.info(f"    {region:<8} {count:,}")

    summary = {
        "n_rows": n_rows,
        "n_sites": len(sites),
        "granularity_minutes": granularity_minutes,
        "date_range": (date_min, date_max),
        "null_pct": null_pct.to_dict(),
        "stats": stats,
    }
    log.info(BORDER)
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# 2. Distribution Plots
# ─────────────────────────────────────────────────────────────────────────────

def plot_kpi_distributions(
    df: pd.DataFrame,
    save_dir: str = None,
) -> None:
    """
    Plot a histogram + KDE for every KPI metric, with threshold lines overlaid.
    One figure per metric; saved to save_dir (defaults to PATHS['plots']).
    """
    save_dir = Path(save_dir or PATHS["plots"])
    save_dir.mkdir(parents=True, exist_ok=True)

    log.info("Generating KPI distribution plots…")

    for metric in KPI_METRICS:
        if metric not in df.columns:
            continue

        direction, threshold = KPI_THRESHOLDS[metric]
        data = df[metric].dropna()

        fig, axes = plt.subplots(1, 2, figsize=(14, 4.5))
        fig.suptitle(f"KPI Distribution — {metric}", fontsize=13, fontweight="bold", y=1.01)

        # ── Left: histogram + KDE ────────────────────────────────────────────
        ax = axes[0]
        ax.hist(data, bins=60, density=True, color="#4878CF", alpha=0.65, edgecolor="white", linewidth=0.3)
        data.plot.kde(ax=ax, color="#4878CF", linewidth=1.8)
        ax.axvline(threshold, color="#E84A3F", linewidth=1.5, linestyle="--",
                   label=f"Threshold ({'>' if direction == 'above' else '<'}{threshold})")
        ax.axvline(data.mean(), color="#F5A623", linewidth=1.2, linestyle="-.",
                   label=f"Mean ({data.mean():.2f})")
        ax.set_xlabel(metric, fontsize=10)
        ax.set_ylabel("Density", fontsize=10)
        ax.set_title("Distribution (all sites)", fontsize=10)
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3, linestyle="--")

        # ── Right: boxplot grouped by technology ─────────────────────────────
        ax2 = axes[1]
        tech_groups = [grp[metric].dropna().values for _, grp in df.groupby("technology")]
        tech_labels  = [label for label, _ in df.groupby("technology")]
        bp = ax2.boxplot(tech_groups, labels=tech_labels, patch_artist=True, notch=False,
                         medianprops=dict(color="black", linewidth=1.5))
        colors = ["#4878CF", "#6ACC65"]
        for patch, color in zip(bp["boxes"], colors):
            patch.set_facecolor(color)
            patch.set_alpha(0.7)
        ax2.axhline(threshold, color="#E84A3F", linewidth=1.5, linestyle="--",
                    label=f"Threshold ({threshold})")
        ax2.set_xlabel("Technology", fontsize=10)
        ax2.set_ylabel(metric, fontsize=10)
        ax2.set_title("By technology", fontsize=10)
        ax2.legend(fontsize=8)
        ax2.grid(True, alpha=0.3, linestyle="--", axis="y")

        plt.tight_layout()
        fname = save_dir / f"kpi_dist_{metric}.png"
        plt.savefig(fname, dpi=130, bbox_inches="tight")
        plt.close()
        log.info(f"  Saved → {fname}")


# ─────────────────────────────────────────────────────────────────────────────
# 3. Time-Series Trend Plots
# ─────────────────────────────────────────────────────────────────────────────

def plot_kpi_time_series(
    df: pd.DataFrame,
    site: str = None,
    metrics: list = None,
    save_dir: str = None,
) -> None:
    """
    Plot KPI trends over time for a given site (or the aggregate of all sites).

    Parameters
    ----------
    df      : KPI DataFrame.
    site    : network_element_id to filter on. If None, plots the mean over all sites.
    metrics : List of metric names to include. Defaults to all KPI_METRICS.
    save_dir: Directory to save the figure. Defaults to PATHS['plots'].
    """
    save_dir = Path(save_dir or PATHS["plots"])
    save_dir.mkdir(parents=True, exist_ok=True)
    metrics  = metrics or KPI_METRICS

    if site:
        data = df[df["network_element_id"] == site].copy()
        title_suffix = f"Site: {site}"
        fname_suffix = site
    else:
        # Hourly mean across all sites
        data = (
            df.set_index("timestamp")[metrics]
              .resample("1h").mean()
              .reset_index()
        )
        title_suffix = "All sites (hourly mean)"
        fname_suffix = "all_sites"

    n = len(metrics)
    fig, axes = plt.subplots(n, 1, figsize=(16, 2.8 * n), sharex=True)
    if n == 1:
        axes = [axes]

    fig.suptitle(f"KPI Trends — {title_suffix}", fontsize=13, fontweight="bold")

    for ax, metric in zip(axes, metrics):
        if metric not in data.columns:
            continue

        ts_col = "timestamp" if "timestamp" in data.columns else data.index
        if "timestamp" in data.columns:
            xs = data["timestamp"]
        else:
            xs = data.index

        ax.plot(xs, data[metric], linewidth=0.8, color="#4878CF", alpha=0.9)

        # Threshold line
        direction, threshold = KPI_THRESHOLDS[metric]
        ax.axhline(threshold, color="#E84A3F", linewidth=1.0, linestyle="--",
                   label=f"threshold ({threshold})", alpha=0.7)

        # Shade breach regions
        breach = data[metric] > threshold if direction == "above" else data[metric] < threshold
        if isinstance(xs, pd.Series):
            ax.fill_between(xs, data[metric], threshold, where=breach,
                            color="#E84A3F", alpha=0.15, label="breach")
        ax.set_ylabel(metric, fontsize=8)
        ax.legend(fontsize=7, loc="upper right")
        ax.grid(True, alpha=0.3, linestyle="--")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))

    plt.tight_layout()
    fname = save_dir / f"kpi_timeseries_{fname_suffix}.png"
    plt.savefig(fname, dpi=130, bbox_inches="tight")
    plt.close()
    log.info(f"Time-series plot saved → {fname}")


def plot_kpi_heatmap(
    df: pd.DataFrame,
    metric: str = "throughput_mbps",
    save_dir: str = None,
) -> None:
    """
    Plot a heatmap of a single KPI:  hour-of-day (rows) × site (columns).
    Useful for spotting peak-hour patterns across sites.
    """
    save_dir = Path(save_dir or PATHS["plots"])
    save_dir.mkdir(parents=True, exist_ok=True)

    pivot = (
        df.assign(hour=df["timestamp"].dt.hour)
          .groupby(["hour", "network_element_id"])[metric]
          .mean()
          .unstack("network_element_id")
    )

    fig, ax = plt.subplots(figsize=(14, 6))
    sns.heatmap(
        pivot, ax=ax,
        cmap="YlOrRd",
        linewidths=0.3,
        linecolor="white",
        fmt=".1f",
        annot=True,
        annot_kws={"size": 7},
    )
    ax.set_title(f"Hourly avg {metric} by site (all days)", fontsize=12, fontweight="bold")
    ax.set_xlabel("Site", fontsize=10)
    ax.set_ylabel("Hour of day", fontsize=10)
    plt.tight_layout()
    fname = save_dir / f"kpi_heatmap_{metric}.png"
    plt.savefig(fname, dpi=130, bbox_inches="tight")
    plt.close()
    log.info(f"KPI heatmap saved → {fname}")


# ─────────────────────────────────────────────────────────────────────────────
# 4. Optional: Full ydata-profiling Report
# ─────────────────────────────────────────────────────────────────────────────

def generate_profiling_report(
    df: pd.DataFrame,
    report_name: str = "kpi_profile_report.html",
    save_dir: str = None,
) -> None:
    """
    Generate a full ydata-profiling HTML report for the KPI DataFrame.
    Skip gracefully if ydata-profiling is not installed.
    """
    try:
        from ydata_profiling import ProfileReport
    except ImportError:
        log.warning("ydata-profiling not installed. Skipping HTML report.")
        log.info("  → Install with: pip install ydata-profiling")
        return

    save_dir = Path(save_dir or PATHS["profiling"])
    save_dir.mkdir(parents=True, exist_ok=True)

    log.info("Generating ydata-profiling HTML report (this may take a minute)…")
    profile = ProfileReport(
        df,
        title="HFCL EMS — KPI Data Profile",
        minimal=False,
        explorative=True,
    )
    out_path = save_dir / report_name
    profile.to_file(out_path)
    log.info(f"Profiling report saved → {out_path}")


# ─────────────────────────────────────────────────────────────────────────────
# Convenience runner
# ─────────────────────────────────────────────────────────────────────────────

def run_kpi_profiling(df: pd.DataFrame, generate_html_report: bool = False) -> dict:
    """Run all KPI profiling steps and return the summary dict."""
    summary = profile_kpi(df)
    plot_kpi_distributions(df)
    # Plot time series for all sites individually
    for site in df["network_element_id"].unique():
        plot_kpi_time_series(df, site=site)
    # Overall trend (all sites, hourly mean)
    plot_kpi_time_series(df, site=None)
    # Heatmap for throughput
    plot_kpi_heatmap(df, metric="throughput_mbps")
    if generate_html_report:
        generate_profiling_report(df)
    return summary


if __name__ == "__main__":
    from phase2_ingestion.data_loader import load_kpi_data
    kpi = load_kpi_data()
    run_kpi_profiling(kpi, generate_html_report=False)
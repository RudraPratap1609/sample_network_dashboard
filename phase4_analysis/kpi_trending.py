"""
phase4_analysis/kpi_trending.py
================================
Phase 4 — KPI Trending & Breach Analysis

Three analysis layers built on top of the Phase 3 processed KPI DataFrame:

  1. Breach summary      — count / rate of threshold violations per metric,
                           per technology, per site, and across hours of day.
  2. Degradation periods — sustained breach windows (≥ N consecutive 15-min
                           slots) that signal persistent impairment, not
                           transient spikes.
  3. Time-series plots   — per-metric charts with threshold line, 6-hour
                           rolling average overlay, and breach shading.

All plots are written to disk (no interactive windows opened).
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")   # non-interactive backend — safe for headless servers
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.dates as mdates
import seaborn as sns

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.logger import get_logger
from config.settings import KPI_THRESHOLDS, TECH_THROUGHPUT_THRESHOLDS

log = get_logger(__name__)

# ── Module-level constants ────────────────────────────────────────────────────

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

_C_PRIMARY    = "#2B5EA7"   # deep blue — main series
_C_ROLLING    = "#E59500"   # amber    — rolling average
_C_THRESHOLD  = "#D64045"   # red      — threshold line
_C_BREACH_BG  = "#FFE6E6"   # pale red — breach-shaded regions
_C_GRID       = "#E0E0E0"


# ═══════════════════════════════════════════════════════════════════════════════
# 1. BREACH SUMMARY
# ═══════════════════════════════════════════════════════════════════════════════

def compute_breach_summary(kpi_df: pd.DataFrame) -> dict:
    """
    Compute threshold-breach statistics from the processed KPI DataFrame.

    Expects columns produced by Phase 3 preprocessing:
      • <metric>_breach   (Boolean)
      • any_breach        (Boolean)
      • critical_kpi_count (int — number of KPIs simultaneously in breach)
      • hour              (int 0-23)

    Returns
    -------
    dict with keys:
      'per_metric'     : breach count/rate per KPI metric (DataFrame, sorted desc)
      'per_technology' : breach rates broken down by technology (DataFrame)
      'per_site'       : breach stats per network element (DataFrame, sorted desc)
      'temporal'       : avg breach rate per hour of day (DataFrame)
      'highlights'     : dict of key scalar findings for quick reporting
    """
    log.info("Computing KPI breach summary…")

    breach_cols = [f"{m}_breach" for m in KPI_METRICS if f"{m}_breach" in kpi_df.columns]
    if not breach_cols:
        log.warning("  No <metric>_breach columns found — was Phase 3 ETL run?")
        return {}

    total_rows = len(kpi_df)

    # ── Per-metric ────────────────────────────────────────────────────────────
    per_metric_rows = []
    for col in breach_cols:
        metric = col.replace("_breach", "")
        direction, threshold = KPI_THRESHOLDS.get(metric, ("?", float("nan")))
        count = int(kpi_df[col].sum())
        rate  = round(float(kpi_df[col].mean()) * 100, 2)
        per_metric_rows.append({
            "metric":            metric,
            "display_name":      KPI_LABELS.get(metric, metric),
            "breach_direction":  direction,
            "threshold":         threshold,
            "breach_count":      count,
            "breach_rate_pct":   rate,
            "total_observations": total_rows,
        })
    per_metric_df = (
        pd.DataFrame(per_metric_rows)
          .sort_values("breach_rate_pct", ascending=False)
          .reset_index(drop=True)
    )
    log.info(
        f"  Breach summary — {len(per_metric_df)} metrics evaluated, "
        f"worst: {per_metric_df.iloc[0]['display_name']} "
        f"@ {per_metric_df.iloc[0]['breach_rate_pct']:.1f}%"
    )

    # ── Per-technology ────────────────────────────────────────────────────────
    per_tech_rows = []
    if "technology" in kpi_df.columns:
        for tech, grp in kpi_df.groupby("technology"):
            row = {"technology": tech, "n_observations": len(grp)}
            for col in breach_cols:
                metric = col.replace("_breach", "")
                row[f"{metric}_breach_pct"] = round(grp[col].mean() * 100, 2)
            row["any_breach_pct"] = round(grp["any_breach"].mean() * 100, 2) if "any_breach" in grp else None
            per_tech_rows.append(row)
    per_tech_df = pd.DataFrame(per_tech_rows).reset_index(drop=True)

    # ── Per-site (top 20 by overall breach rate) ──────────────────────────────
    per_site_rows = []
    if "network_element_id" in kpi_df.columns:
        for ne, grp in kpi_df.groupby("network_element_id"):
            row = {
                "network_element_id": ne,
                "technology": grp["technology"].mode().iloc[0] if "technology" in grp.columns else "?",
                "region":     grp["region"].mode().iloc[0]     if "region"     in grp.columns else "?",
                "n_observations": len(grp),
            }
            for col in breach_cols:
                metric = col.replace("_breach", "")
                row[f"{metric}_breach_pct"] = round(grp[col].mean() * 100, 2)
            row["any_breach_pct"]      = round(grp["any_breach"].mean() * 100, 2) if "any_breach" in grp else None
            row["avg_health_score"]    = round(grp["kpi_health_score"].mean(), 1) if "kpi_health_score" in grp else None
            row["avg_simultaneous_kpi_breaches"] = round(grp["critical_kpi_count"].mean(), 2) if "critical_kpi_count" in grp else None
            per_site_rows.append(row)
    per_site_df = (
        pd.DataFrame(per_site_rows)
          .sort_values("any_breach_pct", ascending=False)
          .reset_index(drop=True)
    )

    # ── Temporal pattern (breach rate by hour of day) ─────────────────────────
    temporal_df = pd.DataFrame()
    if "hour" in kpi_df.columns and "any_breach" in kpi_df.columns:
        temporal_df = (
            kpi_df.groupby("hour")["any_breach"]
              .mean()
              .mul(100)
              .round(2)
              .rename("breach_rate_pct")
              .reset_index()
        )

    # ── Key highlights ─────────────────────────────────────────────────────────
    worst_site = per_site_df.iloc[0]["network_element_id"] if len(per_site_df) else "N/A"
    worst_metric = per_metric_df.iloc[0]["metric"] if len(per_metric_df) else "N/A"
    peak_breach_hour = (
        temporal_df.sort_values("breach_rate_pct", ascending=False).iloc[0]["hour"]
        if len(temporal_df) else "N/A"
    )

    highlights = {
        "worst_metric":              worst_metric,
        "worst_metric_breach_rate":  per_metric_df.iloc[0]["breach_rate_pct"] if len(per_metric_df) else None,
        "worst_site":                worst_site,
        "worst_site_breach_rate":    per_site_df.iloc[0]["any_breach_pct"]    if len(per_site_df)   else None,
        "peak_breach_hour":          peak_breach_hour,
        "pct_rows_any_breach":       round(kpi_df["any_breach"].mean() * 100, 2) if "any_breach" in kpi_df else None,
    }

    log.info(f"  Overall any-breach rate : {highlights['pct_rows_any_breach']}%")
    log.info(f"  Worst site              : {worst_site} ({per_site_df.iloc[0]['any_breach_pct']}%)")

    return {
        "per_metric":     per_metric_df,
        "per_technology": per_tech_df,
        "per_site":       per_site_df,
        "temporal":       temporal_df,
        "highlights":     highlights,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 2. DEGRADATION PERIOD DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

def identify_degradation_periods(
    kpi_df: pd.DataFrame,
    metric: str,
    min_consecutive: int = 4,
) -> pd.DataFrame:
    """
    Find sustained KPI degradation windows — consecutive 15-min intervals where
    <metric>_breach is True — lasting at least `min_consecutive` periods.

    Rationale: a single-interval breach could be a measurement glitch; breaches
    spanning ≥ 1 hour (4 × 15 min) indicate genuine network impairment.

    Parameters
    ----------
    kpi_df          : Processed KPI DataFrame (Phase 3 output).
    metric          : KPI column name (e.g. 'throughput_mbps').
    min_consecutive : Minimum consecutive breach intervals to qualify
                      as a degradation period (default 4 = 1 hour).

    Returns
    -------
    DataFrame with columns:
      network_element_id, start, end, duration_periods, duration_hours,
      worst_value, mean_value, metric
    """
    breach_col = f"{metric}_breach"
    if breach_col not in kpi_df.columns:
        log.warning(f"Column '{breach_col}' not found — skipping degradation detection.")
        return pd.DataFrame()
    if metric not in kpi_df.columns:
        log.warning(f"Column '{metric}' not found — skipping degradation detection.")
        return pd.DataFrame()

    records = []
    direction, threshold = KPI_THRESHOLDS.get(metric, ("?", float("nan")))

    for ne, grp in kpi_df.groupby("network_element_id"):
        grp = grp.sort_values("timestamp").reset_index(drop=True)

        # Identify contiguous blocks of breach=True using group-by-change trick
        grp["_run_id"] = (grp[breach_col] != grp[breach_col].shift()).cumsum()
        for run_id, run in grp.groupby("_run_id"):
            if not run[breach_col].iloc[0]:     # non-breach run — skip
                continue
            if len(run) < min_consecutive:       # too short — skip
                continue

            worst = (run[metric].min() if direction == "below"
                     else run[metric].max())
            records.append({
                "network_element_id": ne,
                "metric":             metric,
                "start":              run["timestamp"].iloc[0],
                "end":                run["timestamp"].iloc[-1],
                "duration_periods":   len(run),
                "duration_hours":     round(len(run) * 15 / 60, 2),
                "worst_value":        round(worst, 4),
                "mean_value":         round(run[metric].mean(), 4),
                "threshold":          threshold,
                "breach_direction":   direction,
            })

    result = pd.DataFrame(records).sort_values("duration_hours", ascending=False).reset_index(drop=True)
    log.info(
        f"  Degradation periods [{metric}]: "
        f"{len(result)} events (≥ {min_consecutive} consecutive 15-min slots)"
    )
    return result


def identify_all_degradation_periods(
    kpi_df: pd.DataFrame,
    min_consecutive: int = 4,
) -> pd.DataFrame:
    """
    Run identify_degradation_periods for every KPI metric and combine results.

    Returns a single DataFrame with a 'metric' column to distinguish events.
    """
    all_parts = []
    for metric in KPI_METRICS:
        if f"{metric}_breach" in kpi_df.columns:
            part = identify_degradation_periods(kpi_df, metric, min_consecutive)
            if not part.empty:
                all_parts.append(part)

    if not all_parts:
        return pd.DataFrame()

    combined = pd.concat(all_parts, ignore_index=True)
    log.info(f"  Total degradation periods across all KPIs: {len(combined)}")
    return combined


# ═══════════════════════════════════════════════════════════════════════════════
# 3. PLOTTING FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def _apply_plot_style() -> None:
    """Apply a consistent, clean style to all Phase 4 plots."""
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
        "legend.fontsize":   9,
        "xtick.labelsize":   9,
        "ytick.labelsize":   9,
    })


def _safe_mkdir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def plot_kpi_time_series(
    kpi_df: pd.DataFrame,
    metric: str,
    save_dir: str | Path,
) -> None:
    """
    Plot the time series for a single KPI metric, aggregated daily by technology.

    The chart shows:
      • Daily mean value per technology (coloured lines)
      • 7-day rolling average (dashed, same colour, slightly transparent)
      • SLA/operational threshold (red dashed horizontal line)
      • Background shading on days where breach rate > 50%

    Parameters
    ----------
    kpi_df   : Processed KPI DataFrame.
    metric   : KPI column name (e.g. 'throughput_mbps').
    save_dir : Directory in which to save the PNG file.
    """
    if metric not in kpi_df.columns:
        log.warning(f"  plot_kpi_time_series: column '{metric}' not found — skipping.")
        return

    _apply_plot_style()
    save_dir = _safe_mkdir(save_dir)

    breach_col = f"{metric}_breach"
    direction, threshold = KPI_THRESHOLDS.get(metric, ("?", float("nan")))
    label = KPI_LABELS.get(metric, metric)

    # Aggregate to daily mean per technology
    agg = (
        kpi_df.assign(date=kpi_df["timestamp"].dt.date)
              .groupby(["date", "technology"])
              .agg(
                  mean_val=(metric, "mean"),
                  breach_rate=(breach_col, "mean") if breach_col in kpi_df.columns else (metric, lambda x: 0),
              )
              .reset_index()
    )
    agg["date"] = pd.to_datetime(agg["date"])

    techs = sorted(agg["technology"].unique()) if "technology" in agg.columns else []
    colours = plt.cm.tab10.colors

    fig, ax = plt.subplots(figsize=(14, 5))

    for i, tech in enumerate(techs):
        tech_data = agg[agg["technology"] == tech].sort_values("date")
        colour = colours[i % len(colours)]

        # Raw daily mean
        ax.plot(
            tech_data["date"], tech_data["mean_val"],
            color=colour, linewidth=1.4, alpha=0.9, label=tech,
        )
        # 7-day rolling average
        rolling = tech_data["mean_val"].rolling(7, center=True, min_periods=1).mean()
        ax.plot(
            tech_data["date"], rolling,
            color=colour, linewidth=2.2, linestyle="--", alpha=0.55,
        )

        # Shade high-breach days
        if "breach_rate" in tech_data.columns:
            high_breach = tech_data[tech_data["breach_rate"] > 0.50]
            for _, row in high_breach.iterrows():
                ax.axvspan(
                    row["date"] - pd.Timedelta(hours=12),
                    row["date"] + pd.Timedelta(hours=12),
                    color=_C_BREACH_BG, alpha=0.35, zorder=0,
                )

    # Threshold line
    if not np.isnan(threshold):
        ax.axhline(
            threshold, color=_C_THRESHOLD, linewidth=1.5,
            linestyle=":", label=f"Threshold ({threshold})",
        )

    ax.set_title(f"KPI Trend — {label}", fontweight="bold", pad=12)
    ax.set_xlabel("Date")
    ax.set_ylabel(label)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d-%b"))
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
    fig.autofmt_xdate(rotation=30)
    ax.grid(True, axis="y")
    ax.legend(loc="upper right", framealpha=0.85)

    # Legend patch for breach shading
    breach_patch = mpatches.Patch(color=_C_BREACH_BG, alpha=0.7, label="> 50% breach day")
    handles, labels_leg = ax.get_legend_handles_labels()
    ax.legend(handles + [breach_patch], labels_leg + ["> 50% breach day"],
              loc="upper right", framealpha=0.85)

    plt.tight_layout()
    fname = save_dir / f"kpi_trend_{metric}.png"
    plt.savefig(fname, dpi=130, bbox_inches="tight")
    plt.close(fig)
    log.info(f"  Saved: {fname}")


def plot_breach_heatmap(
    kpi_df: pd.DataFrame,
    save_dir: str | Path,
    top_n_sites: int = 20,
) -> None:
    """
    Heatmap of breach rates: rows = top_n_sites, columns = KPI metrics.

    Colour intensity shows how often each site breaches each KPI threshold.
    Red = high breach rate, green = low.
    """
    _apply_plot_style()
    save_dir = _safe_mkdir(save_dir)

    breach_cols = [c for c in kpi_df.columns if c.endswith("_breach") and c.replace("_breach", "") in KPI_METRICS]
    if not breach_cols:
        log.warning("  plot_breach_heatmap: no breach columns found — skipping.")
        return

    # Compute per-site breach rates
    site_breach = (
        kpi_df.groupby("network_element_id")[breach_cols]
              .mean()
              .mul(100)
              .rename(columns=lambda c: KPI_LABELS.get(c.replace("_breach", ""), c.replace("_breach", "")))
    )

    # Select top_n most-breaching sites
    site_breach["_any"] = kpi_df.groupby("network_element_id")["any_breach"].mean() * 100 if "any_breach" in kpi_df.columns else 0
    site_breach = site_breach.sort_values("_any", ascending=False).drop(columns="_any").head(top_n_sites)

    if site_breach.empty:
        log.warning("  plot_breach_heatmap: no site data — skipping.")
        return

    fig_h = max(5, len(site_breach) * 0.38)
    fig, ax = plt.subplots(figsize=(13, fig_h))

    sns.heatmap(
        site_breach,
        annot=True, fmt=".1f", annot_kws={"size": 8},
        cmap="RdYlGn_r",
        vmin=0, vmax=100,
        linewidths=0.4, linecolor="#E0E0E0",
        cbar_kws={"label": "Breach rate (%)", "shrink": 0.6},
        ax=ax,
    )
    ax.set_title(
        f"KPI Breach Rate Heatmap — Top {len(site_breach)} Sites",
        fontweight="bold", pad=12,
    )
    ax.set_xlabel("KPI Metric")
    ax.set_ylabel("Network Element ID")
    plt.xticks(rotation=25, ha="right", fontsize=9)
    plt.yticks(rotation=0, fontsize=8)
    plt.tight_layout()

    fname = save_dir / "kpi_breach_heatmap.png"
    plt.savefig(fname, dpi=130, bbox_inches="tight")
    plt.close(fig)
    log.info(f"  Saved: {fname}")


def plot_kpi_health_trend(
    kpi_df: pd.DataFrame,
    save_dir: str | Path,
) -> None:
    """
    Line chart of average KPI health score over time, split by technology.

    The health score (0–100) is the composite weighted KPI score computed in
    Phase 3 preprocessing. A downward trend indicates systemic degradation.
    """
    if "kpi_health_score" not in kpi_df.columns:
        log.warning("  plot_kpi_health_trend: 'kpi_health_score' column missing — skipping.")
        return

    _apply_plot_style()
    save_dir = _safe_mkdir(save_dir)

    daily = (
        kpi_df.assign(date=kpi_df["timestamp"].dt.date)
              .groupby(["date", "technology"])["kpi_health_score"]
              .mean()
              .reset_index()
    )
    daily["date"] = pd.to_datetime(daily["date"])

    fig, ax = plt.subplots(figsize=(14, 4))
    colours = plt.cm.tab10.colors

    for i, (tech, grp) in enumerate(daily.groupby("technology")):
        grp = grp.sort_values("date")
        colour = colours[i % len(colours)]
        ax.plot(grp["date"], grp["kpi_health_score"], color=colour, linewidth=1.6, label=tech)
        # 7-day rolling average
        rolling = grp["kpi_health_score"].rolling(7, center=True, min_periods=1).mean()
        ax.plot(grp["date"], rolling, color=colour, linewidth=2.4, linestyle="--", alpha=0.55)

    ax.axhline(80, color="#E59500", linewidth=1.2, linestyle=":", label="Good threshold (80)")
    ax.axhline(60, color=_C_THRESHOLD, linewidth=1.2, linestyle=":", label="Warning threshold (60)")
    ax.fill_between(daily["date"].unique(), 0, 60, alpha=0.05, color="red")

    ax.set_ylim(0, 105)
    ax.set_title("Composite KPI Health Score Over Time", fontweight="bold", pad=12)
    ax.set_xlabel("Date")
    ax.set_ylabel("Health Score (0–100)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d-%b"))
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
    fig.autofmt_xdate(rotation=30)
    ax.grid(True, axis="y")
    ax.legend(loc="lower right", framealpha=0.85)

    plt.tight_layout()
    fname = save_dir / "kpi_health_trend.png"
    plt.savefig(fname, dpi=130, bbox_inches="tight")
    plt.close(fig)
    log.info(f"  Saved: {fname}")


def plot_breach_rate_by_hour(
    kpi_df: pd.DataFrame,
    save_dir: str | Path,
) -> None:
    """
    Bar chart: average KPI breach rate per hour of day (0–23).

    Useful for identifying peak-traffic degradation windows vs.
    maintenance-hour issues.
    """
    if "hour" not in kpi_df.columns or "any_breach" not in kpi_df.columns:
        log.warning("  plot_breach_rate_by_hour: 'hour' or 'any_breach' missing — skipping.")
        return

    _apply_plot_style()
    save_dir = _safe_mkdir(save_dir)

    hourly = (
        kpi_df.groupby("hour")["any_breach"]
              .mean()
              .mul(100)
              .reset_index()
              .rename(columns={"any_breach": "breach_rate_pct"})
    )

    fig, ax = plt.subplots(figsize=(12, 4))
    colours = [_C_THRESHOLD if r > hourly["breach_rate_pct"].quantile(0.75) else _C_PRIMARY
               for r in hourly["breach_rate_pct"]]
    bars = ax.bar(hourly["hour"], hourly["breach_rate_pct"], color=colours, edgecolor="white", linewidth=0.5)

    ax.set_title("KPI Breach Rate by Hour of Day", fontweight="bold", pad=12)
    ax.set_xlabel("Hour of Day (0 = midnight)")
    ax.set_ylabel("Breach Rate (%)")
    ax.set_xticks(range(24))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:.1f}%"))
    ax.grid(True, axis="y")

    # Shade peak hours (08:00–22:00)
    ax.axvspan(7.5, 21.5, alpha=0.06, color="#2B5EA7", label="Peak hours (08–22)")
    ax.legend(loc="upper left", framealpha=0.85)

    plt.tight_layout()
    fname = save_dir / "kpi_breach_by_hour.png"
    plt.savefig(fname, dpi=130, bbox_inches="tight")
    plt.close(fig)
    log.info(f"  Saved: {fname}")


def plot_all_kpi_time_series(
    kpi_df: pd.DataFrame,
    save_dir: str | Path,
) -> None:
    """
    Save one time-series PNG per KPI metric (calls plot_kpi_time_series in loop).
    """
    for metric in KPI_METRICS:
        if metric in kpi_df.columns:
            plot_kpi_time_series(kpi_df, metric, save_dir)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. MAIN RUNNER
# ═══════════════════════════════════════════════════════════════════════════════

def run_kpi_trending(
    kpi_df: pd.DataFrame,
    save_dir: str | Path,
    generate_plots: bool = True,
    min_degradation_periods: int = 4,
) -> dict:
    """
    Orchestrate all Phase 4 KPI trending analyses.

    Parameters
    ----------
    kpi_df                 : Processed KPI DataFrame from Phase 3 ETL.
    save_dir               : Base output directory (plots saved to save_dir/plots/,
                             tables to save_dir/reports/).
    generate_plots         : If False, skip all matplotlib output.
    min_degradation_periods: Minimum consecutive breach intervals for a degradation
                             event (default 4 = 1 hour at 15-min granularity).

    Returns
    -------
    dict with keys:
      'breach_summary'        : output of compute_breach_summary()
      'degradation_periods'   : combined degradation DataFrame (all metrics)
      'plot_dir'              : Path to saved plots
    """
    log.info("=" * 65)
    log.info("PHASE 4 — KPI Trending Analysis")
    log.info("=" * 65)

    plots_dir   = _safe_mkdir(Path(save_dir) / "plots"   / "phase4" / "kpi_trending")
    reports_dir = _safe_mkdir(Path(save_dir) / "reports" / "phase4")

    # 1. Breach summary
    breach_summary = compute_breach_summary(kpi_df)
    if breach_summary:
        for key in ["per_metric", "per_site", "per_technology", "temporal"]:
            if key in breach_summary and not breach_summary[key].empty:
                out = reports_dir / f"breach_summary_{key}.csv"
                breach_summary[key].to_csv(out, index=False)
                log.info(f"  Saved report: {out}")

    # 2. Degradation periods
    degradation_df = identify_all_degradation_periods(kpi_df, min_degradation_periods)
    if not degradation_df.empty:
        out = reports_dir / "kpi_degradation_periods.csv"
        degradation_df.to_csv(out, index=False)
        log.info(f"  Saved {len(degradation_df)} degradation events → {out}")

    # 3. Plots
    if generate_plots:
        log.info("  Generating KPI trend plots…")
        plot_all_kpi_time_series(kpi_df, plots_dir)
        plot_breach_heatmap(kpi_df, plots_dir)
        plot_kpi_health_trend(kpi_df, plots_dir)
        plot_breach_rate_by_hour(kpi_df, plots_dir)
        log.info(f"  All KPI trending plots saved to: {plots_dir}")

    log.info("PHASE 4 — KPI Trending complete.")
    return {
        "breach_summary":      breach_summary,
        "degradation_periods": degradation_df,
        "plot_dir":            plots_dir,
        "reports_dir":         reports_dir,
    }
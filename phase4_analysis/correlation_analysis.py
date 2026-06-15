"""
phase4_analysis/correlation_analysis.py
========================================
Phase 4 — KPI–Alarm Correlation & Root-Cause Analysis

Three complementary methods map alarm events to KPI degradation:

  1. Alarm presence matrix
     For each 15-min KPI interval on a given site, mark which alarm types
     were active at that time.  Enables direct time-aligned correlation.

  2. Event-conditioned lag profiles
     For each (alarm_type, KPI_metric) pair, compute the average KPI value
     at offsets −4h … +4h relative to every alarm occurrence on the same
     site.  Comparing this profile to the overall KPI baseline reveals:
       • Pre-alarm KPI trends (KPI was already degrading → alarm is a symptom)
       • Simultaneous drops  (alarm coincides with KPI failure)
       • Post-alarm recovery (restoration follows alarm resolution)

  3. Co-occurrence with degradation events
     Identify sustained KPI degradation windows (≥ 1 h in breach) and count
     which alarm types were raised on the same site in the preceding 6 h.
     High co-occurrence = strong root-cause candidate.

  The final ranking merges cross-correlation strength and co-occurrence
  frequency into a single priority score per (alarm_type, KPI_metric) pair.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import seaborn as sns
from scipy.stats import pearsonr

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.logger import get_logger
from config.settings import (
    KPI_THRESHOLDS,
    KPI_GRANULARITY_MINUTES,
)
from phase4_analysis.kpi_trending import (
    KPI_METRICS,
    KPI_LABELS,
    identify_degradation_periods,
)

log = get_logger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_C_POSITIVE_CORR = "#D64045"   # red — alarm raises (degrades KPI)
_C_NEGATIVE_CORR = "#2B5EA7"   # blue — alarm has no / positive association
_C_ZERO          = "#E0E0E0"
_C_GRID          = "#E0E0E0"


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
        "font.size":         10,
        "axes.titlesize":    11,
        "axes.labelsize":    10,
    })


def _slugify(text: str) -> str:
    """Convert an alarm type string to a safe column-name slug."""
    return text.lower().replace(" ", "_").replace("/", "_").replace("-", "_")


# ═══════════════════════════════════════════════════════════════════════════════
# 1. ALARM PRESENCE MATRIX
# ═══════════════════════════════════════════════════════════════════════════════

def build_alarm_presence_matrix(
    kpi_df: pd.DataFrame,
    alarm_df: pd.DataFrame,
    granularity_minutes: int = None,
) -> pd.DataFrame:
    """
    Augment the KPI DataFrame with binary alarm-presence columns.

    For every (network_element_id, 15-min timestamp) in kpi_df, add a
    Boolean column ``alarm_<slug>`` for each alarm type in alarm_df.
    Value is 1 if any alarm of that type was *active* (raised but not yet
    cleared) at that timestamp on that site, else 0.

    Parameters
    ----------
    kpi_df              : Processed KPI DataFrame (Phase 3 output).
    alarm_df            : Processed alarm DataFrame (Phase 3 output).
    granularity_minutes : KPI collection granularity in minutes (default from
                          config.settings.KPI_GRANULARITY_MINUTES).

    Returns
    -------
    kpi_df augmented with alarm_<slug> columns.

    Note
    ----
    Building the presence matrix requires iterating over alarm rows to expand
    each alarm interval into discrete bins.  For large datasets (> 100k alarms)
    consider chunking by network element.
    """
    gran = granularity_minutes or KPI_GRANULARITY_MINUTES
    freq = f"{gran}min"

    if alarm_df.empty:
        log.warning("  build_alarm_presence_matrix: alarm_df is empty — returning kpi_df unchanged.")
        return kpi_df.copy()

    log.info(f"  Building alarm presence matrix ({len(alarm_df):,} alarms × {gran}-min bins)…")

    alarm_types = sorted(alarm_df["alarm_type"].unique())
    log.info(f"    Alarm types to encode: {alarm_types}")

    # ── Step 1: Expand each alarm interval into discrete 15-min bins ──────────
    # Build a list of (network_element_id, ts_bin, alarm_type) records
    presence_records: list[dict] = []
    for _, row in alarm_df.iterrows():
        ne    = row["network_element_id"]
        start = pd.Timestamp(row["timestamp"])
        end   = pd.Timestamp(row["cleared_timestamp"]) if pd.notna(row.get("cleared_timestamp")) else start + pd.Timedelta(hours=4)

        # Snap to granularity boundaries
        start_bin = start.floor(freq)
        end_bin   = end.ceil(freq)

        # Clamp to a maximum of 24 h per alarm to avoid runaway expansion
        if (end_bin - start_bin).total_seconds() / 3600 > 24:
            end_bin = start_bin + pd.Timedelta(hours=24)

        bins = pd.date_range(start_bin, end_bin, freq=freq)
        alarm_type = row["alarm_type"]
        for b in bins:
            presence_records.append({
                "network_element_id": ne,
                "ts_bin":             b,
                "alarm_type":         alarm_type,
            })

    if not presence_records:
        log.warning("  No presence records generated — returning kpi_df unchanged.")
        return kpi_df.copy()

    presence_df = pd.DataFrame(presence_records).drop_duplicates(
        subset=["network_element_id", "ts_bin", "alarm_type"]
    )

    # ── Step 2: Pivot to wide binary format ───────────────────────────────────
    presence_wide = (
        presence_df
        .assign(value=1)
        .pivot_table(
            index=["network_element_id", "ts_bin"],
            columns="alarm_type",
            values="value",
            aggfunc="max",
            fill_value=0,
        )
    )
    presence_wide.columns = [f"alarm_{_slugify(c)}" for c in presence_wide.columns]
    presence_wide = presence_wide.reset_index().rename(columns={"ts_bin": "timestamp"})

    # ── Step 3: Merge with KPI DataFrame ──────────────────────────────────────
    kpi_out = kpi_df.copy()
    kpi_out["timestamp"] = pd.to_datetime(kpi_out["timestamp"])

    # Snap KPI timestamps to granularity boundary for merge key
    kpi_out["_ts_bin"] = kpi_out["timestamp"].dt.floor(freq)
    presence_wide.rename(columns={"timestamp": "_ts_bin"}, inplace=True)

    kpi_out = kpi_out.merge(
        presence_wide,
        left_on=["network_element_id", "_ts_bin"],
        right_on=["network_element_id", "_ts_bin"],
        how="left",
    ).drop(columns=["_ts_bin"])

    # Fill NaN (no active alarm) → 0
    alarm_cols = [c for c in kpi_out.columns if c.startswith("alarm_") and c not in kpi_df.columns]
    kpi_out[alarm_cols] = kpi_out[alarm_cols].fillna(0).astype(int)

    n_alarm_cols = len(alarm_cols)
    log.info(f"    Alarm presence matrix built: {n_alarm_cols} alarm columns added.")
    return kpi_out


# ═══════════════════════════════════════════════════════════════════════════════
# 2. EVENT-CONDITIONED LAG PROFILES
# ═══════════════════════════════════════════════════════════════════════════════

def compute_lag_profiles(
    kpi_df: pd.DataFrame,
    alarm_df: pd.DataFrame,
    kpi_metrics: list[str] = None,
    alarm_types: list[str] = None,
    max_lag_hours: float = 4.0,
    granularity_minutes: int = None,
) -> dict:
    """
    Compute event-conditioned KPI profiles around each alarm type.

    For every (alarm_type, KPI_metric) pair, collect the KPI values at time
    offsets relative to each alarm occurrence and average them across events.

    The "lag profile" answers: "On average, what does KPI metric X look like
    before, during, and after an alarm of type Y is raised on the same site?"

    Comparing the profile to the global KPI mean reveals:
      • Pre-alarm KPI trends  → alarm is a symptom of prior degradation
      • Simultaneous drops    → alarm coincides with KPI failure (same root cause)
      • Post-alarm recovery   → KPI recovers after alarm resolution
      • No effect             → alarm is unrelated to this KPI

    Parameters
    ----------
    kpi_df              : Processed KPI DataFrame.
    alarm_df            : Processed alarm DataFrame.
    kpi_metrics         : Subset of KPI metrics to analyse (None = all 8).
    alarm_types         : Subset of alarm types to analyse (None = all).
    max_lag_hours       : Window size on each side of the alarm (hours).
    granularity_minutes : KPI collection interval (default from settings).

    Returns
    -------
    dict:  {alarm_type → {kpi_metric → {'lags_h': list, 'mean_kpi': list,
                                         'baseline_mean': float,
                                         'n_events': int}}}
    """
    gran     = granularity_minutes or KPI_GRANULARITY_MINUTES
    freq     = pd.tseries.frequencies.to_offset(f"{gran}min")
    max_lags = int(max_lag_hours * 60 / gran)

    metrics  = [m for m in (kpi_metrics or KPI_METRICS) if m in kpi_df.columns]
    a_types  = alarm_types or sorted(alarm_df["alarm_type"].unique())

    log.info(
        f"  Computing lag profiles: {len(a_types)} alarm types × "
        f"{len(metrics)} KPI metrics, window ±{max_lag_hours}h…"
    )

    # Pre-sort KPI by (ne, timestamp) for efficient label-based lookup
    kpi_sorted = kpi_df.sort_values(["network_element_id", "timestamp"]).copy()
    kpi_sorted["timestamp"] = pd.to_datetime(kpi_sorted["timestamp"])

    # Global KPI baselines (overall mean across all rows)
    baselines = {m: kpi_sorted[m].mean() for m in metrics}

    lag_steps = list(range(-max_lags, max_lags + 1))
    lag_hours = [s * gran / 60 for s in lag_steps]

    results: dict = {}

    for alarm_type in a_types:
        type_alarms = alarm_df[alarm_df["alarm_type"] == alarm_type].copy()
        if type_alarms.empty:
            continue

        results[alarm_type] = {}

        for metric in metrics:
            kpi_values_at_lags: dict[int, list] = {s: [] for s in lag_steps}

            for _, alarm_row in type_alarms.iterrows():
                ne         = alarm_row["network_element_id"]
                alarm_time = pd.Timestamp(alarm_row["timestamp"])

                # Slice KPI data for this site
                site_kpi = kpi_sorted[kpi_sorted["network_element_id"] == ne].copy()
                if site_kpi.empty:
                    continue

                # For each lag step, look up the KPI value at alarm_time + lag
                for lag_step in lag_steps:
                    target_time = alarm_time + pd.Timedelta(minutes=gran * lag_step)
                    # Find the closest KPI row within ½ granularity interval
                    diff = (site_kpi["timestamp"] - target_time).abs()
                    idx  = diff.idxmin()
                    if diff.loc[idx] <= pd.Timedelta(minutes=gran // 2):
                        val = site_kpi.loc[idx, metric]
                        if pd.notna(val):
                            kpi_values_at_lags[lag_step].append(float(val))

            mean_profile  = [np.mean(kpi_values_at_lags[s]) if kpi_values_at_lags[s] else np.nan
                             for s in lag_steps]
            n_events_used = len(kpi_values_at_lags[0]) if len(kpi_values_at_lags) > 0 else 0

            results[alarm_type][metric] = {
                "lags_h":        lag_hours,
                "lag_steps":     lag_steps,
                "mean_kpi":      mean_profile,
                "baseline_mean": baselines[metric],
                "n_events":      len(type_alarms),
                "n_with_kpi":    n_events_used,
            }

        log.info(f"    [{alarm_type}] profiles computed for {len(metrics)} KPIs ({len(type_alarms)} events)")

    return results


def summarise_lag_profiles(lag_profiles: dict) -> pd.DataFrame:
    """
    Convert nested lag profile results into a flat summary DataFrame.

    For each (alarm_type, KPI_metric) pair, extract:
      • Peak deviation from baseline (max |mean_kpi - baseline| in window)
      • Lag at peak deviation (hours)
      • Signed effect at lag=0 (alarm raised → KPI value vs baseline)
      • Direction: 'degrades' if alarm coincides with KPI worsening, else 'none'

    This summary drives the root-cause ranking.
    """
    rows = []
    for alarm_type, metrics_dict in lag_profiles.items():
        for metric, profile in metrics_dict.items():
            baseline = profile["baseline_mean"]
            mean_kpi = np.array(profile["mean_kpi"])
            lags_h   = np.array(profile["lags_h"])

            if np.all(np.isnan(mean_kpi)):
                continue

            deviations = mean_kpi - baseline
            abs_dev    = np.abs(deviations)
            valid_mask = ~np.isnan(abs_dev)

            if not valid_mask.any():
                continue

            peak_idx    = np.nanargmax(abs_dev)
            peak_dev    = float(deviations[peak_idx])
            peak_lag_h  = float(lags_h[peak_idx])

            # Effect at alarm onset (lag = 0)
            zero_idx    = np.argmin(np.abs(lags_h))
            effect_at_0 = float(deviations[zero_idx]) if not np.isnan(mean_kpi[zero_idx]) else np.nan

            # Determine breach direction to interpret "degrades"
            direction, threshold = KPI_THRESHOLDS.get(metric, ("above", float("nan")))
            if direction == "above":
                degrades = peak_dev > 0        # metric going UP is bad
            else:
                degrades = peak_dev < 0        # metric going DOWN is bad

            rows.append({
                "alarm_type":        alarm_type,
                "kpi_metric":        metric,
                "kpi_display":       KPI_LABELS.get(metric, metric),
                "n_alarm_events":    profile["n_events"],
                "n_with_kpi_data":   profile["n_with_kpi"],
                "baseline_mean":     round(baseline, 4),
                "peak_deviation":    round(peak_dev, 4),
                "peak_lag_hours":    round(peak_lag_h, 2),
                "effect_at_onset":   round(effect_at_0, 4) if not np.isnan(effect_at_0) else None,
                "degrades_kpi":      degrades,
                "abs_deviation":     round(float(np.abs(peak_dev)), 4),
                # Normalised by baseline (percentage deviation)
                "pct_deviation":     round(peak_dev / baseline * 100, 2) if baseline and baseline != 0 else None,
            })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("abs_deviation", ascending=False).reset_index(drop=True)
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# 3. CO-OCCURRENCE WITH KPI DEGRADATION EVENTS
# ═══════════════════════════════════════════════════════════════════════════════

def cooccurrence_analysis(
    alarm_df: pd.DataFrame,
    kpi_df: pd.DataFrame,
    lookback_hours: float = 6.0,
    min_consecutive: int = 4,
) -> pd.DataFrame:
    """
    Count how often each alarm type co-occurs with sustained KPI degradation.

    For every KPI degradation event (sustained breach ≥ min_consecutive 15-min
    intervals) on a given site, look back `lookback_hours` and count how many
    alarms of each type were raised on the same site in that window.

    High co-occurrence indicates the alarm frequently precedes degradation
    → a strong root-cause candidate.

    Parameters
    ----------
    alarm_df         : Processed alarm DataFrame.
    kpi_df           : Processed KPI DataFrame.
    lookback_hours   : Hours before degradation onset to scan for alarms.
    min_consecutive  : Min consecutive breach intervals for degradation event.

    Returns
    -------
    DataFrame with columns: alarm_type, kpi_metric, cooccurrence_count,
    total_degradation_events, cooccurrence_rate (fraction of degradation events
    preceded by at least one alarm of that type).
    """
    log.info(
        f"  Running co-occurrence analysis "
        f"(lookback = {lookback_hours}h, min_consecutive = {min_consecutive})…"
    )

    lookback_td = pd.Timedelta(hours=lookback_hours)
    all_rows: list[dict] = []

    for metric in KPI_METRICS:
        if f"{metric}_breach" not in kpi_df.columns:
            continue

        # Get degradation events for this metric
        deg_events = identify_degradation_periods(kpi_df, metric, min_consecutive)
        if deg_events.empty:
            continue

        total_events = len(deg_events)
        cooccurrence: dict[str, int] = {}   # alarm_type → count of events with ≥1 alarm

        for _, event in deg_events.iterrows():
            ne         = event["network_element_id"]
            onset      = pd.Timestamp(event["start"])
            window_start = onset - lookback_td
            window_end   = onset

            # Alarms on the same site in the lookback window
            precursor_alarms = alarm_df[
                (alarm_df["network_element_id"] == ne) &
                (alarm_df["timestamp"] >= window_start) &
                (alarm_df["timestamp"] <= window_end)
            ]

            seen_types = precursor_alarms["alarm_type"].unique() if not precursor_alarms.empty else []
            for atype in seen_types:
                cooccurrence[atype] = cooccurrence.get(atype, 0) + 1

        for atype, count in cooccurrence.items():
            all_rows.append({
                "alarm_type":                atype,
                "kpi_metric":               metric,
                "kpi_display":              KPI_LABELS.get(metric, metric),
                "cooccurrence_count":        count,
                "total_degradation_events":  total_events,
                "cooccurrence_rate":         round(count / total_events, 4),
            })

    if not all_rows:
        log.info("  No co-occurrence data generated.")
        return pd.DataFrame()

    df = (
        pd.DataFrame(all_rows)
          .sort_values("cooccurrence_count", ascending=False)
          .reset_index(drop=True)
    )
    log.info(
        f"  Co-occurrence analysis complete: {len(df)} (alarm_type, kpi_metric) pairs evaluated."
    )
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# 4. ROOT-CAUSE CANDIDATE RANKING
# ═══════════════════════════════════════════════════════════════════════════════

def rank_root_cause_candidates(
    lag_summary: pd.DataFrame,
    cooccurrence_df: pd.DataFrame,
    top_n: int = 15,
) -> pd.DataFrame:
    """
    Merge lag-analysis and co-occurrence evidence into a unified priority ranking.

    Scoring:
      normalised_lag_score       = abs_deviation / max(abs_deviation)  (0–1)
      normalised_cooccurrence    = cooccurrence_rate / max(rate)         (0–1)
      combined_score             = 0.5 × lag + 0.5 × cooccurrence        (0–1)

    Only pairs that appear in both analyses are ranked; pairs in only one source
    are listed at the bottom with partial scores.

    Parameters
    ----------
    lag_summary      : Output of summarise_lag_profiles().
    cooccurrence_df  : Output of cooccurrence_analysis().
    top_n            : Number of top candidates to return (None = all).

    Returns
    -------
    DataFrame ranked by combined_score descending, with columns:
      rank, alarm_type, kpi_metric, kpi_display, n_alarm_events,
      abs_deviation, pct_deviation, peak_lag_hours, degrades_kpi,
      cooccurrence_rate, cooccurrence_count, lag_score, coocurrence_score,
      combined_score, interpretation.
    """
    log.info("  Ranking root-cause candidates…")

    if lag_summary.empty and cooccurrence_df.empty:
        log.warning("  Both lag_summary and cooccurrence_df are empty — nothing to rank.")
        return pd.DataFrame()

    # Normalise lag scores
    lag_df = lag_summary.copy()
    if not lag_df.empty and "abs_deviation" in lag_df.columns:
        max_dev = lag_df["abs_deviation"].max()
        lag_df["lag_score"] = (lag_df["abs_deviation"] / max_dev).round(4) if max_dev > 0 else 0.0
    else:
        lag_df["lag_score"] = 0.0

    # Normalise co-occurrence scores
    coo_df = cooccurrence_df.copy()
    if not coo_df.empty and "cooccurrence_rate" in coo_df.columns:
        max_rate = coo_df["cooccurrence_rate"].max()
        coo_df["cooccurrence_score"] = (coo_df["cooccurrence_rate"] / max_rate).round(4) if max_rate > 0 else 0.0
    else:
        coo_df["cooccurrence_score"] = 0.0

    # Merge on (alarm_type, kpi_metric)
    merged = pd.merge(
        lag_df[["alarm_type", "kpi_metric", "kpi_display", "n_alarm_events",
                "abs_deviation", "pct_deviation", "peak_lag_hours",
                "degrades_kpi", "effect_at_onset", "lag_score"]],
        coo_df[["alarm_type", "kpi_metric",
                "cooccurrence_rate", "cooccurrence_count",
                "total_degradation_events", "cooccurrence_score"]],
        on=["alarm_type", "kpi_metric"],
        how="outer",
    )

    merged["lag_score"]          = merged["lag_score"].fillna(0.0)
    merged["cooccurrence_score"] = merged["cooccurrence_score"].fillna(0.0)
    merged["combined_score"]     = ((merged["lag_score"] + merged["cooccurrence_score"]) / 2).round(4)

    # ── Plain-language interpretation ─────────────────────────────────────────
    def interpret(row: pd.Series) -> str:
        lag_h = row.get("peak_lag_hours", np.nan)
        deg   = row.get("degrades_kpi", False)
        coo_r = row.get("cooccurrence_rate", 0.0)
        pct   = row.get("pct_deviation", 0.0)

        if pd.isna(lag_h) or pd.isna(deg):
            return "Insufficient data"

        lag_label = (
            f"KPI worsens {abs(lag_h):.1f}h {'after' if lag_h > 0 else 'before'} alarm onset"
            if abs(lag_h) > 0.25 else "KPI worsens simultaneously with alarm"
        )
        coo_label = f"present before {coo_r*100:.0f}% of degradation events" if coo_r else "no co-occurrence data"

        if deg and coo_r >= 0.5:
            return f"HIGH priority — {lag_label}; {coo_label}. Likely root cause."
        elif deg and coo_r >= 0.2:
            return f"MEDIUM priority — {lag_label}; {coo_label}. Investigate correlation."
        elif deg:
            return f"LOW-MEDIUM — {lag_label}; {coo_label}. Weak signal."
        else:
            return f"LOW — no KPI degradation signal (pct_dev={pct}%); {coo_label}."

    merged["interpretation"] = merged.apply(interpret, axis=1)

    ranked = (
        merged
        .sort_values("combined_score", ascending=False)
        .reset_index(drop=True)
    )
    if top_n:
        ranked = ranked.head(top_n)

    ranked.insert(0, "rank", range(1, len(ranked) + 1))

    log.info(f"  Root-cause ranking complete — top candidate: "
             f"{ranked.iloc[0]['alarm_type']} × {ranked.iloc[0]['kpi_metric']} "
             f"(score = {ranked.iloc[0]['combined_score']:.3f})" if len(ranked) else "  No candidates found.")
    return ranked


# ═══════════════════════════════════════════════════════════════════════════════
# 5. PLOTTING FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def plot_lag_profiles(
    lag_profiles: dict,
    lag_summary: pd.DataFrame,
    save_dir: str | Path,
    top_n_pairs: int = 9,
) -> None:
    """
    Multi-panel subplot grid: one panel per top (alarm_type, KPI_metric) pair.

    Each panel shows the event-conditioned mean KPI vs. lag hours, with the
    global baseline as a dashed reference line.  Red shading in the ±30-min
    window around alarm onset highlights the critical period.

    Parameters
    ----------
    lag_profiles   : Output of compute_lag_profiles().
    lag_summary    : Output of summarise_lag_profiles() — used to pick top pairs.
    save_dir       : Directory to save the PNG.
    top_n_pairs    : Number of (alarm_type, KPI) pairs to plot (max 9 for legibility).
    """
    _apply_plot_style()
    save_dir = _safe_mkdir(save_dir)

    if lag_summary.empty:
        log.warning("  plot_lag_profiles: empty lag_summary — skipping.")
        return

    # Select top pairs by abs_deviation, only those that actually degrade the KPI
    top_pairs = lag_summary[lag_summary["degrades_kpi"] == True].head(top_n_pairs)
    if top_pairs.empty:
        top_pairs = lag_summary.head(top_n_pairs)

    n = min(len(top_pairs), top_n_pairs)
    if n == 0:
        return

    ncols = min(3, n)
    nrows = (n + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(5.5 * ncols, 4 * nrows))
    axes = np.array(axes).flatten() if n > 1 else np.array([axes])

    for i, (_, row) in enumerate(top_pairs.iterrows()):
        if i >= len(axes):
            break
        ax = axes[i]
        alarm_type = row["alarm_type"]
        metric     = row["kpi_metric"]

        if alarm_type not in lag_profiles or metric not in lag_profiles[alarm_type]:
            ax.set_visible(False)
            continue

        profile   = lag_profiles[alarm_type][metric]
        lags_h    = profile["lags_h"]
        mean_kpi  = profile["mean_kpi"]
        baseline  = profile["baseline_mean"]
        n_events  = profile["n_events"]
        label     = KPI_LABELS.get(metric, metric)

        # Replace NaN with baseline for plotting continuity
        mean_kpi_plot = [v if not np.isnan(v) else baseline for v in mean_kpi]

        ax.plot(lags_h, mean_kpi_plot, color="#2B5EA7", linewidth=2, label="Conditioned mean")
        ax.axhline(baseline, color="#555555", linewidth=1.2, linestyle="--",
                   alpha=0.75, label=f"Baseline ({baseline:.2f})")

        # Shade ±30-min alarm onset window
        gran_h = KPI_GRANULARITY_MINUTES / 60
        ax.axvspan(-2 * gran_h, 2 * gran_h, color="#FFE6E6", alpha=0.6, label="Alarm onset ±30 min")
        ax.axvline(0, color=_C_POSITIVE_CORR, linewidth=1.0, linestyle=":", alpha=0.85)

        # Shade the full window if the KPI dips/spikes substantially
        direction, threshold = KPI_THRESHOLDS.get(metric, ("above", float("nan")))
        if not np.isnan(threshold):
            ax.axhline(threshold, color=_C_POSITIVE_CORR, linewidth=0.8, linestyle=":",
                       alpha=0.55, label=f"Threshold ({threshold})")

        ax.set_title(f"{alarm_type}\n→ {label}", fontsize=9, fontweight="bold")
        ax.set_xlabel("Hours relative to alarm (0 = onset)", fontsize=8)
        ax.set_ylabel(label, fontsize=8)
        ax.set_xlim(min(lags_h), max(lags_h))
        ax.legend(fontsize=7, loc="best", framealpha=0.75)
        ax.text(0.02, 0.97, f"n = {n_events} events", transform=ax.transAxes,
                fontsize=7, va="top", color="#555555")

    # Hide unused subplots
    for j in range(len(top_pairs), len(axes)):
        axes[j].set_visible(False)

    fig.suptitle("Event-Conditioned KPI Lag Profiles\n(KPI behaviour before / after alarm onset)",
                 fontsize=13, fontweight="bold", y=1.01)
    plt.tight_layout()

    fname = save_dir / "correlation_lag_profiles.png"
    plt.savefig(fname, dpi=130, bbox_inches="tight")
    plt.close(fig)
    log.info(f"  Saved: {fname}")


def plot_cooccurrence_heatmap(
    cooccurrence_df: pd.DataFrame,
    save_dir: str | Path,
) -> None:
    """
    Heatmap of alarm type × KPI metric co-occurrence rates.

    Cell colour shows what fraction of sustained KPI degradation events were
    preceded (within 6 h) by at least one alarm of that type.
    """
    _apply_plot_style()
    save_dir = _safe_mkdir(save_dir)

    if cooccurrence_df.empty:
        log.warning("  plot_cooccurrence_heatmap: empty DataFrame — skipping.")
        return

    pivot = cooccurrence_df.pivot_table(
        index="alarm_type",
        columns="kpi_display",
        values="cooccurrence_rate",
        aggfunc="mean",
    ).fillna(0)

    if pivot.empty:
        return

    fig_h = max(5, len(pivot) * 0.45)
    fig, ax = plt.subplots(figsize=(min(14, len(pivot.columns) * 1.4), fig_h))

    sns.heatmap(
        pivot,
        cmap="YlOrRd",
        vmin=0, vmax=1,
        annot=True, fmt=".2f", annot_kws={"size": 8},
        linewidths=0.4, linecolor="#E0E0E0",
        cbar_kws={"label": "Co-occurrence rate (0–1)", "shrink": 0.6},
        ax=ax,
    )
    ax.set_title("Alarm → KPI Degradation Co-occurrence Rate\n"
                 "(fraction of sustained KPI degradation events preceded by alarm within 6 h)",
                 fontweight="bold", pad=12)
    ax.set_xlabel("KPI Metric")
    ax.set_ylabel("Alarm Type")
    plt.xticks(rotation=30, ha="right", fontsize=9)
    plt.yticks(rotation=0, fontsize=8)
    plt.tight_layout()

    fname = save_dir / "correlation_cooccurrence_heatmap.png"
    plt.savefig(fname, dpi=130, bbox_inches="tight")
    plt.close(fig)
    log.info(f"  Saved: {fname}")


def plot_root_cause_ranking(
    ranked_df: pd.DataFrame,
    save_dir: str | Path,
    top_n: int = 15,
) -> None:
    """
    Horizontal bar chart showing the top root-cause candidates by combined score.

    Bars are coloured by the 'degrades_kpi' flag:
      • Red   — alarm co-occurs with KPI degradation (root-cause candidate)
      • Blue  — weak or no degradation signal
    """
    _apply_plot_style()
    save_dir = _safe_mkdir(save_dir)

    if ranked_df.empty:
        log.warning("  plot_root_cause_ranking: empty DataFrame — skipping.")
        return

    df = ranked_df.head(top_n).copy()
    df["label"] = df["alarm_type"] + "\n→ " + df.get("kpi_display", df["kpi_metric"])
    colours = [_C_POSITIVE_CORR if deg else _C_NEGATIVE_CORR for deg in df.get("degrades_kpi", [True] * len(df))]

    fig, ax = plt.subplots(figsize=(11, max(5, len(df) * 0.55)))
    bars = ax.barh(df["label"][::-1], df["combined_score"][::-1],
                   color=colours[::-1], edgecolor="white", linewidth=0.4)

    # Annotation labels
    for bar, score in zip(bars, df["combined_score"][::-1]):
        ax.text(score + 0.005, bar.get_y() + bar.get_height() / 2,
                f"{score:.3f}", va="center", fontsize=8.5)

    ax.set_xlim(0, 1.1)
    ax.set_xlabel("Combined Priority Score (0–1)")
    ax.set_title(f"Top {len(df)} Root-Cause Candidates\n(Lag analysis + co-occurrence evidence)",
                 fontweight="bold", pad=12)
    ax.grid(True, axis="x")

    from matplotlib.patches import Patch
    legend_els = [
        Patch(facecolor=_C_POSITIVE_CORR, label="Degrades KPI"),
        Patch(facecolor=_C_NEGATIVE_CORR, label="No degradation signal"),
    ]
    ax.legend(handles=legend_els, loc="lower right", framealpha=0.85)
    plt.tight_layout()

    fname = save_dir / "correlation_root_cause_ranking.png"
    plt.savefig(fname, dpi=130, bbox_inches="tight")
    plt.close(fig)
    log.info(f"  Saved: {fname}")


# ═══════════════════════════════════════════════════════════════════════════════
# 6. MAIN RUNNER
# ═══════════════════════════════════════════════════════════════════════════════

def run_correlation_analysis(
    kpi_df: pd.DataFrame,
    alarm_df: pd.DataFrame,
    save_dir: str | Path,
    generate_plots: bool = True,
    max_lag_hours: float = 4.0,
    lookback_hours: float = 6.0,
    top_n_candidates: int = 15,
    kpi_metrics: list[str] = None,
    alarm_types: list[str] = None,
) -> dict:
    """
    Orchestrate the full Phase 4 correlation analysis pipeline.

    Steps
    -----
    1. Build alarm presence matrix (augment kpi_df with binary alarm columns).
    2. Compute event-conditioned lag profiles.
    3. Summarise lag profiles into a flat ranking DataFrame.
    4. Run co-occurrence analysis (alarm types that precede degradation events).
    5. Rank root-cause candidates by combined score.
    6. (Optional) Generate all correlation plots.

    Parameters
    ----------
    kpi_df              : Processed KPI DataFrame (Phase 3 ETL output).
    alarm_df            : Processed alarm DataFrame (Phase 3 ETL output).
    save_dir            : Base output directory.
    generate_plots      : If False, skip matplotlib output.
    max_lag_hours       : Lag window size (hours) for lag profile analysis.
    lookback_hours      : Lookback window (hours) for co-occurrence analysis.
    top_n_candidates    : Number of root-cause candidates to return.
    kpi_metrics         : Subset of KPI metrics (None = all).
    alarm_types         : Subset of alarm types (None = all).

    Returns
    -------
    dict with keys:
      'presence_matrix'   : Augmented KPI DataFrame with alarm presence columns
      'lag_profiles'      : Raw lag profile dicts
      'lag_summary'       : Flat lag profile summary DataFrame
      'cooccurrence'      : Co-occurrence analysis DataFrame
      'ranked_candidates' : Root-cause candidate ranking DataFrame
    """
    log.info("=" * 65)
    log.info("PHASE 4 — KPI–Alarm Correlation Analysis")
    log.info("=" * 65)

    plots_dir   = _safe_mkdir(Path(save_dir) / "plots"   / "phase4" / "correlation")
    reports_dir = _safe_mkdir(Path(save_dir) / "reports" / "phase4")

    # 1. Alarm presence matrix
    log.info("Step 1/5: Building alarm presence matrix…")
    presence_matrix = build_alarm_presence_matrix(kpi_df, alarm_df)

    # 2. Lag profiles
    log.info("Step 2/5: Computing event-conditioned lag profiles…")
    lag_profiles = compute_lag_profiles(
        kpi_df, alarm_df,
        kpi_metrics=kpi_metrics,
        alarm_types=alarm_types,
        max_lag_hours=max_lag_hours,
    )

    # 3. Lag summary
    log.info("Step 3/5: Summarising lag profiles…")
    lag_summary = summarise_lag_profiles(lag_profiles)
    if not lag_summary.empty:
        out = reports_dir / "correlation_lag_summary.csv"
        lag_summary.to_csv(out, index=False)
        log.info(f"  Saved: {out}")

    # 4. Co-occurrence
    log.info("Step 4/5: Running co-occurrence analysis…")
    cooccurrence_df = cooccurrence_analysis(
        alarm_df, kpi_df,
        lookback_hours=lookback_hours,
    )
    if not cooccurrence_df.empty:
        out = reports_dir / "correlation_cooccurrence.csv"
        cooccurrence_df.to_csv(out, index=False)
        log.info(f"  Saved: {out}")

    # 5. Rank root-cause candidates
    log.info("Step 5/5: Ranking root-cause candidates…")
    ranked_df = rank_root_cause_candidates(lag_summary, cooccurrence_df, top_n=top_n_candidates)
    if not ranked_df.empty:
        out = reports_dir / "correlation_root_cause_candidates.csv"
        ranked_df.to_csv(out, index=False)
        log.info(f"  Saved: {out}")
        log.info("\n  ── TOP 5 ROOT-CAUSE CANDIDATES ──")
        for _, r in ranked_df.head(5).iterrows():
            log.info(f"    #{int(r['rank'])}  {r['alarm_type']} → {r['kpi_metric']}  "
                     f"(score={r['combined_score']:.3f})  {r['interpretation']}")

    # 6. Plots
    if generate_plots:
        log.info("  Generating correlation plots…")
        plot_lag_profiles(lag_profiles, lag_summary, plots_dir)
        plot_cooccurrence_heatmap(cooccurrence_df, plots_dir)
        plot_root_cause_ranking(ranked_df, plots_dir, top_n=top_n_candidates)
        log.info(f"  All correlation plots saved to: {plots_dir}")

    log.info("PHASE 4 — Correlation Analysis complete.")
    return {
        "presence_matrix":   presence_matrix,
        "lag_profiles":      lag_profiles,
        "lag_summary":       lag_summary,
        "cooccurrence":      cooccurrence_df,
        "ranked_candidates": ranked_df,
        "plot_dir":          plots_dir,
        "reports_dir":       reports_dir,
    }
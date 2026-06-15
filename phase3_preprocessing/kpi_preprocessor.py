"""
phase3_preprocessing/kpi_preprocessor.py
==========================================
Phase 3 — KPI Data Preprocessing

Transforms the raw KPI DataFrame into an analysis-ready one by:

  1. Timestamp normalisation      — parse, sort, set to UTC-aware if needed.
  2. Missing value imputation     — forward-fill, interpolation, or flagging.
  3. Gap detection & filling      — ensure a complete regular time index per site.
  4. Threshold breach flagging    — Boolean breach columns for each KPI.
  5. Feature engineering          — rolling averages, rate-of-change, peak-hour
                                    flags, and KPI composite health score.

All functions accept and return DataFrames with the canonical column schema
defined in config/settings.py — no hard-coded column renaming needed here.
"""

import sys
from pathlib import Path

import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.logger import get_logger
from config.settings import (
    KPI_THRESHOLDS,
    KPI_MISSING_STRATEGY,
    KPI_GRANULARITY_MINUTES,
    ROLLING_WINDOWS,
    PEAK_HOURS,
    TECH_THROUGHPUT_THRESHOLDS,
    PATHS,
)

log = get_logger(__name__)

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

# Weight of each KPI in the composite health score (higher = more important).
# Direction: +1 means "higher is better", -1 means "lower is better".
KPI_HEALTH_WEIGHTS = {
    "throughput_mbps":            (+1, 0.20),
    "availability_pct":           (+1, 0.25),
    "utilization_pct":            (-1, 0.10),
    "latency_ms":                 (-1, 0.15),
    "rtwp_dbm":                   (-1, 0.10),
    "handover_success_rate_pct":  (+1, 0.10),
    "call_drop_rate_pct":         (-1, 0.05),
    "rach_success_rate_pct":      (+1, 0.05),
}


# ─────────────────────────────────────────────────────────────────────────────
# Step 1 — Timestamp Normalisation
# ─────────────────────────────────────────────────────────────────────────────

def normalize_kpi_timestamps(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure the timestamp column is a proper datetime, sorted per site.

    - Coerces unparseable values to NaT (flagged and dropped).
    - Sorts by [network_element_id, timestamp].
    - Strips timezone info to keep everything naive (consistent with EMS exports).
    """
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")

    nat_count = df["timestamp"].isna().sum()
    if nat_count:
        log.warning(f"  {nat_count} rows with unparseable timestamps — dropping them")
        df = df.dropna(subset=["timestamp"])

    # Remove timezone info if present (EMS CSVs are typically local time)
    if hasattr(df["timestamp"].dt, "tz") and df["timestamp"].dt.tz is not None:
        df["timestamp"] = df["timestamp"].dt.tz_localize(None)

    df = df.sort_values(["network_element_id", "timestamp"]).reset_index(drop=True)
    log.info(f"Timestamps normalised — {len(df):,} rows retained")
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Step 2 — Gap Detection & Regular Index
# ─────────────────────────────────────────────────────────────────────────────

def ensure_regular_index(df: pd.DataFrame) -> pd.DataFrame:
    """
    For each site, create a full regular DatetimeIndex at KPI_GRANULARITY_MINUTES
    intervals and reindex the data into it — making gaps explicit as NaN rows.

    Real EMS data often has collection gaps (maintenance, connectivity loss).
    This step makes gaps visible before imputation.
    """
    freq = f"{KPI_GRANULARITY_MINUTES}min"
    parts = []

    for site, grp in df.groupby("network_element_id"):
        grp = grp.set_index("timestamp").sort_index()
        full_idx = pd.date_range(start=grp.index.min(), end=grp.index.max(), freq=freq)
        grp = grp.reindex(full_idx)

        # Restore categorical / ID columns after reindex (they become NaN)
        grp["network_element_id"] = site
        grp["technology"] = grp["technology"].ffill()
        grp["region"]     = grp["region"].ffill()

        grp.index.name = "timestamp"
        grp = grp.reset_index()
        parts.append(grp)

    out = pd.concat(parts, ignore_index=True)
    new_nulls = out[KPI_METRICS].isna().sum().sum()
    log.info(f"Regular index enforced — {new_nulls:,} NaN values introduced in gaps")
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Step 3 — Missing Value Imputation
# ─────────────────────────────────────────────────────────────────────────────

def handle_missing_kpi(
    df: pd.DataFrame,
    strategy: str = None,
) -> pd.DataFrame:
    """
    Impute or flag missing KPI values using one of three strategies:

    'ffill'       — Forward-fill within each site (telecom default; assumes
                    KPI stays at its last known value over short gaps).
    'interpolate' — Linear interpolation per site (smoother, but assumes
                    linear change — valid only for short gaps).
    'flag'        — Leave NaN as-is and add a Boolean missing_flag column
                    per metric (useful when you want to track gap locations).

    Parameters
    ----------
    df       : DataFrame with a regular time index (output of ensure_regular_index).
    strategy : Override KPI_MISSING_STRATEGY from settings. One of the above.
    """
    strategy = strategy or KPI_MISSING_STRATEGY
    df = df.copy()

    before = df[KPI_METRICS].isna().sum().sum()
    if before == 0:
        log.info(f"No missing values found — imputation skipped (strategy = '{strategy}')")
        return df

    log.info(f"Imputing {before:,} missing KPI values using strategy = '{strategy}'")

    if strategy == "ffill":
        for site, grp_idx in df.groupby("network_element_id").groups.items():
            df.loc[grp_idx, KPI_METRICS] = (
                df.loc[grp_idx, KPI_METRICS].ffill().bfill()
            )

    elif strategy == "interpolate":
        for site, grp_idx in df.groupby("network_element_id").groups.items():
            df.loc[grp_idx, KPI_METRICS] = (
                df.loc[grp_idx, KPI_METRICS]
                  .interpolate(method="linear", limit_direction="both")
            )

    elif strategy == "flag":
        for metric in KPI_METRICS:
            if metric in df.columns:
                df[f"{metric}_missing"] = df[metric].isna()
        log.info("  Missing flags added (columns: <metric>_missing)")

    else:
        raise ValueError(f"Unknown strategy '{strategy}'. Choose: ffill, interpolate, flag.")

    after = df[KPI_METRICS].isna().sum().sum()
    log.info(f"  Missing values remaining after imputation: {after:,}")
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Step 4 — Threshold Breach Flagging
# ─────────────────────────────────────────────────────────────────────────────

def flag_threshold_breaches(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add a Boolean breach column (<metric>_breach) for each KPI metric.

    Uses technology-specific throughput thresholds when available, and the
    generic KPI_THRESHOLDS for all other metrics.

    Also adds:
    - any_breach        : True if ANY KPI is in breach for that row.
    - critical_kpi_count: Number of KPIs in simultaneous breach.
    """
    df = df.copy()
    breach_cols = []

    for metric, (direction, generic_threshold) in KPI_THRESHOLDS.items():
        if metric not in df.columns:
            continue

        col_name = f"{metric}_breach"
        breach_cols.append(col_name)

        if metric == "throughput_mbps" and "technology" in df.columns:
            # Apply per-technology threshold
            df[col_name] = False
            for tech, tech_thresh in TECH_THROUGHPUT_THRESHOLDS.items():
                tech_mask = df["technology"] == tech
                if direction == "above":
                    df.loc[tech_mask, col_name] = df.loc[tech_mask, metric] > tech_thresh
                else:
                    df.loc[tech_mask, col_name] = df.loc[tech_mask, metric] < tech_thresh
        else:
            if direction == "above":
                df[col_name] = df[metric] > generic_threshold
            else:
                df[col_name] = df[metric] < generic_threshold

    df["any_breach"]         = df[breach_cols].any(axis=1)
    df["critical_kpi_count"] = df[breach_cols].sum(axis=1)

    total_breaches = df["any_breach"].sum()
    breach_pct     = total_breaches / len(df) * 100
    log.info(f"Threshold breach flags added — {total_breaches:,} rows in breach "
             f"({breach_pct:.1f} % of all KPI records)")
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Step 5 — Feature Engineering
# ─────────────────────────────────────────────────────────────────────────────

def engineer_kpi_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add derived features to the KPI DataFrame:

    Time features
    -------------
    - hour              : Hour of day (0–23)
    - dayofweek         : Day of week (0=Mon, 6=Sun)
    - is_weekend        : Boolean
    - is_peak_hour      : Boolean (based on PEAK_HOURS in settings)
    - time_slot         : 'peak' | 'off_peak'

    Rolling statistics (per site)
    ------------------------------
    For each window in ROLLING_WINDOWS and each KPI metric:
    - <metric>_roll_<window>_mean : rolling mean
    - <metric>_roll_<window>_std  : rolling std (volatility)

    Rate of change (per site)
    -------------------------
    - <metric>_delta   : period-over-period absolute change
    - <metric>_pct_chg : period-over-period percentage change

    Composite health score
    ----------------------
    - kpi_health_score : 0–100 score; 100 = all KPIs nominal, 0 = all in breach.
    """
    df = df.copy()
    df = df.sort_values(["network_element_id", "timestamp"]).reset_index(drop=True)

    # ── Time features ────────────────────────────────────────────────────────
    df["hour"]       = df["timestamp"].dt.hour
    df["dayofweek"]  = df["timestamp"].dt.dayofweek
    df["is_weekend"] = df["dayofweek"] >= 5
    df["is_peak_hour"] = (
        (df["hour"] >= PEAK_HOURS[0]) & (df["hour"] < PEAK_HOURS[1])
    )
    df["time_slot"] = df["is_peak_hour"].map({True: "peak", False: "off_peak"})

    log.info("  Time features added: hour, dayofweek, is_weekend, is_peak_hour, time_slot")

    # ── Rolling statistics ────────────────────────────────────────────────────
    for window_name, n_periods in ROLLING_WINDOWS.items():
        for metric in KPI_METRICS:
            if metric not in df.columns:
                continue
            rolled = (
                df.groupby("network_element_id")[metric]
                  .transform(lambda x: x.rolling(n_periods, min_periods=1).mean())
            )
            df[f"{metric}_roll_{window_name}_mean"] = rolled.round(4)

            rolled_std = (
                df.groupby("network_element_id")[metric]
                  .transform(lambda x: x.rolling(n_periods, min_periods=2).std())
            )
            df[f"{metric}_roll_{window_name}_std"] = rolled_std.round(4)

    log.info(f"  Rolling features added for windows: {list(ROLLING_WINDOWS.keys())}")

    # ── Rate of change ────────────────────────────────────────────────────────
    for metric in KPI_METRICS:
        if metric not in df.columns:
            continue
        df[f"{metric}_delta"] = (
            df.groupby("network_element_id")[metric]
              .transform(lambda x: x.diff())
              .round(4)
        )
        df[f"{metric}_pct_chg"] = (
            df.groupby("network_element_id")[metric]
              .transform(lambda x: x.pct_change() * 100)
              .round(2)
        )

    log.info("  Rate-of-change features added: <metric>_delta, <metric>_pct_chg")

    # ── Composite health score ─────────────────────────────────────────────────
    df["kpi_health_score"] = _compute_health_score(df)
    log.info("  Composite KPI health score added: kpi_health_score (0–100)")

    return df


def _compute_health_score(df: pd.DataFrame) -> pd.Series:
    """
    Compute a 0–100 composite health score per row.

    Method: min-max normalise each KPI to [0, 1] across the full dataset,
    flip direction for "lower is better" metrics, then compute a
    weighted average scaled to 100.

    Score of 100  →  all KPIs at their best observed value.
    Score of 0    →  all KPIs at their worst observed value.
    """
    score = pd.Series(np.zeros(len(df)), index=df.index)
    total_weight = 0.0

    for metric, (direction, weight) in KPI_HEALTH_WEIGHTS.items():
        if metric not in df.columns:
            continue
        col = df[metric]
        col_min, col_max = col.min(), col.max()

        if col_max == col_min:
            normalised = pd.Series(1.0, index=df.index)   # constant column
        else:
            normalised = (col - col_min) / (col_max - col_min)

        if direction == -1:   # lower is better → flip
            normalised = 1 - normalised

        score += normalised * weight
        total_weight += weight

    if total_weight > 0:
        score = (score / total_weight) * 100

    return score.round(2)


# ─────────────────────────────────────────────────────────────────────────────
# Convenience runner
# ─────────────────────────────────────────────────────────────────────────────

def run_kpi_preprocessing(df: pd.DataFrame, save: bool = True) -> pd.DataFrame:
    """
    Run the full KPI preprocessing pipeline:
      normalise → regular index → impute → flag breaches → engineer features.

    Parameters
    ----------
    df   : Raw KPI DataFrame from data_loader.load_kpi_data().
    save : If True, write the processed DataFrame to PATHS['processed_kpi'].

    Returns
    -------
    Fully preprocessed KPI DataFrame.
    """
    log.info("=" * 60)
    log.info("PHASE 3 — KPI Preprocessing Pipeline")
    log.info("=" * 60)

    df = normalize_kpi_timestamps(df)
    df = ensure_regular_index(df)
    df = handle_missing_kpi(df)
    df = flag_threshold_breaches(df)
    df = engineer_kpi_features(df)

    log.info(f"Preprocessing complete — final shape: {df.shape}")
    log.info(f"  Columns added: {[c for c in df.columns if c not in ['timestamp', 'network_element_id', 'technology', 'region'] + KPI_METRICS]}")

    if save:
        out_path = PATHS["processed_kpi"]
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_path, index=False)
        log.info(f"Processed KPI data saved → {out_path}")

    return df


if __name__ == "__main__":
    from phase2_ingestion.data_loader import load_kpi_data
    raw = load_kpi_data()
    processed = run_kpi_preprocessing(raw, save=True)
    print(processed.head(3).T)
"""
phase3_preprocessing/alarm_preprocessor.py
============================================
Phase 3 — Alarm Data Preprocessing

Transforms the raw alarm DataFrame into an analysis-ready one by:

  1. Timestamp normalisation  — parse + sort both raised and cleared timestamps.
  2. Active alarm handling    — impute estimated cleared time / flag as open.
  3. Flapping dedup           — remove spurious repeat alarms within a short window.
  4. Feature enrichment       — time-of-day, shift, day type, alarm category,
                                inter-alarm gap (MTBF proxy), MTTR computation.
  5. Schema validation        — check that mandatory columns are present.
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
    ALARM_FLAPPING_WINDOW_MINUTES,
    SEVERITY_ORDER,
    ALARM_CATEGORY_MAP,
    PATHS,
)

log = get_logger(__name__)

REQUIRED_ALARM_COLUMNS = [
    "alarm_id", "timestamp", "cleared_timestamp",
    "network_element_id", "technology", "region",
    "alarm_type", "alarm_code", "severity", "severity_rank",
    "status", "description", "duration_minutes",
]

# Shift boundaries (hour-of-day)
SHIFTS = {
    "morning":   (6,  14),   # 06:00–13:59
    "afternoon": (14, 22),   # 14:00–21:59
    "night":     (22, 24),   # 22:00–23:59  (plus 00:00–05:59)
}


# ─────────────────────────────────────────────────────────────────────────────
# Step 0 — Schema validation
# ─────────────────────────────────────────────────────────────────────────────

def validate_alarm_schema(df: pd.DataFrame) -> None:
    """
    Warn about any missing mandatory columns so issues surface early
    rather than causing obscure errors in later steps.
    """
    missing = [c for c in REQUIRED_ALARM_COLUMNS if c not in df.columns]
    if missing:
        log.warning(f"Alarm DataFrame is missing expected columns: {missing}")
        log.warning("  → Check ALARM_COLUMN_MAP in config/settings.py")
    else:
        log.info("Alarm schema validated — all mandatory columns present")


# ─────────────────────────────────────────────────────────────────────────────
# Step 1 — Timestamp Normalisation
# ─────────────────────────────────────────────────────────────────────────────

def normalize_alarm_timestamps(df: pd.DataFrame) -> pd.DataFrame:
    """
    Parse both 'timestamp' (raised) and 'cleared_timestamp' to proper datetimes.
    Sort by [network_element_id, timestamp].
    """
    df = df.copy()

    df["timestamp"]         = pd.to_datetime(df["timestamp"], errors="coerce")
    df["cleared_timestamp"] = pd.to_datetime(df["cleared_timestamp"], errors="coerce")

    # Remove timezone info
    for col in ["timestamp", "cleared_timestamp"]:
        if hasattr(df[col].dt, "tz") and df[col].dt.tz is not None:
            df[col] = df[col].dt.tz_localize(None)

    nat_raised = df["timestamp"].isna().sum()
    if nat_raised:
        log.warning(f"  {nat_raised} alarms with unparseable raised timestamps — dropping")
        df = df.dropna(subset=["timestamp"])

    df = df.sort_values(["network_element_id", "timestamp"]).reset_index(drop=True)
    log.info(f"Alarm timestamps normalised — {len(df):,} alarms retained")
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Step 2 — Handle Active (Uncleared) Alarms
# ─────────────────────────────────────────────────────────────────────────────

def handle_active_alarms(
    df: pd.DataFrame,
    analysis_end_ts: pd.Timestamp = None,
) -> pd.DataFrame:
    """
    For alarms with status = 'Active' (cleared_timestamp = NaT):
      - Set cleared_timestamp to analysis_end_ts (or the dataset's latest timestamp)
        to allow duration calculation.
      - Add flag column is_active = True.
      - Recalculate duration_minutes.

    Parameters
    ----------
    df               : Alarm DataFrame post timestamp normalisation.
    analysis_end_ts  : Upper bound for active alarm duration.
                       Defaults to max(timestamp) in the dataset.
    """
    df = df.copy()
    active_mask = df["status"] == "Active"
    n_active = active_mask.sum()

    if n_active == 0:
        log.info("No active alarms found — all alarms are cleared")
        df["is_active"] = False
        return df

    if analysis_end_ts is None:
        analysis_end_ts = df["timestamp"].max()

    log.info(f"Handling {n_active} active (uncleared) alarms")
    log.info(f"  Setting cleared_timestamp = {analysis_end_ts} for active alarms")

    df.loc[active_mask, "cleared_timestamp"] = analysis_end_ts

    # Recalculate duration for all alarms (clears inconsistencies from raw data)
    df["duration_minutes"] = (
        (df["cleared_timestamp"] - df["timestamp"]).dt.total_seconds() / 60
    ).round(1)

    # Flag
    df["is_active"] = active_mask
    log.info(f"  is_active column added — {n_active} True entries")
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Step 3 — Flapping Alarm Deduplication
# ─────────────────────────────────────────────────────────────────────────────

def deduplicate_flapping_alarms(
    df: pd.DataFrame,
    window_minutes: int = None,
) -> pd.DataFrame:
    """
    Remove spurious "flapping" alarms: repeated instances of the same
    alarm type on the same site within a short time window.

    Strategy:
      Within each (network_element_id, alarm_type) group, compute the gap
      between consecutive timestamps. If the gap < window_minutes, the repeat
      alarm is considered a flap and is flagged / dropped.

    Parameters
    ----------
    df             : Alarm DataFrame.
    window_minutes : Time window (minutes). Defaults to ALARM_FLAPPING_WINDOW_MINUTES.

    Returns
    -------
    DataFrame with flapping alarms removed and a 'is_flap' flag retained
    in the output for auditing (already excluded from return).
    """
    window = window_minutes or ALARM_FLAPPING_WINDOW_MINUTES
    df = df.copy().sort_values(["network_element_id", "alarm_type", "timestamp"])

    # Compute gap to previous alarm of the same type on the same site
    df["_prev_ts"] = df.groupby(["network_element_id", "alarm_type"])["timestamp"].shift(1)
    df["_gap_min"] = (df["timestamp"] - df["_prev_ts"]).dt.total_seconds() / 60

    df["is_flap"] = df["_gap_min"] < window

    n_flap = df["is_flap"].sum()
    log.info(f"Flapping alarm deduplication (window = {window} min):")
    log.info(f"  {n_flap} flapping alarms identified out of {len(df):,} total")

    if n_flap > 0:
        flap_types = df[df["is_flap"]]["alarm_type"].value_counts()
        log.info(f"  Most common flapping alarm types:")
        for atype, cnt in flap_types.head(5).items():
            log.info(f"    {atype:<30} {cnt} flaps")

    # Drop the flapping alarms (keep only the first occurrence per burst)
    df_clean = df[~df["is_flap"]].copy()
    df_clean = df_clean.drop(columns=["_prev_ts", "_gap_min", "is_flap"])

    log.info(f"  After dedup: {len(df_clean):,} alarms remain")
    return df_clean


# ─────────────────────────────────────────────────────────────────────────────
# Step 4 — Feature Enrichment
# ─────────────────────────────────────────────────────────────────────────────

def enrich_alarm_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add derived features to the alarm DataFrame:

    Time features
    -------------
    - hour          : Hour alarm was raised (0–23).
    - dayofweek     : 0=Mon, 6=Sun.
    - is_weekend    : Boolean.
    - shift         : 'morning' | 'afternoon' | 'night'.
    - day_type      : 'weekday' | 'weekend'.

    Alarm context
    -------------
    - alarm_category : Radio | Transport | Power | Hardware | Software | Other.
    - severity_rank  : Confirmed/re-mapped from severity string (1=Critical).
    - duration_band  : 'short' (< 15 min) | 'medium' (15–60 min) | 'long' (> 60 min).

    Inter-alarm gap & MTTR (per site, per alarm type)
    --------------------------------------------------
    - inter_alarm_gap_min : Minutes since previous alarm of any type on same site.
    - site_mtbf_hrs       : Mean time between alarms (MTBF proxy) per site.
    - site_mttr_min       : Mean time to repair per site (= mean duration).
    """
    df = df.copy().sort_values(["network_element_id", "timestamp"]).reset_index(drop=True)

    # ── Time features ────────────────────────────────────────────────────────
    df["hour"]       = df["timestamp"].dt.hour
    df["dayofweek"]  = df["timestamp"].dt.dayofweek
    df["is_weekend"] = df["dayofweek"] >= 5
    df["day_type"]   = df["is_weekend"].map({True: "weekend", False: "weekday"})

    def get_shift(hour):
        if SHIFTS["morning"][0] <= hour < SHIFTS["morning"][1]:
            return "morning"
        elif SHIFTS["afternoon"][0] <= hour < SHIFTS["afternoon"][1]:
            return "afternoon"
        else:
            return "night"

    df["shift"] = df["hour"].apply(get_shift)
    log.info("  Time features added: hour, dayofweek, is_weekend, shift, day_type")

    # ── Alarm category ────────────────────────────────────────────────────────
    # Build a reverse map: alarm_type → category
    type_to_category = {}
    for category, alarm_types in ALARM_CATEGORY_MAP.items():
        for atype in alarm_types:
            type_to_category[atype] = category

    df["alarm_category"] = df["alarm_type"].map(type_to_category).fillna("Other")
    log.info("  alarm_category added (Radio/Transport/Power/Hardware/Software/Other)")

    # ── Severity rank (normalise from string) ─────────────────────────────────
    df["severity_rank"] = df["severity"].map(SEVERITY_ORDER).fillna(99).astype(int)

    # ── Duration band ─────────────────────────────────────────────────────────
    def duration_band(mins):
        if pd.isna(mins):
            return "unknown"
        if mins < 15:
            return "short"
        elif mins <= 60:
            return "medium"
        else:
            return "long"

    df["duration_band"] = df["duration_minutes"].apply(duration_band)
    log.info("  duration_band added: short (<15 min) | medium (15–60 min) | long (>60 min)")

    # ── Inter-alarm gap (MTBF proxy) ──────────────────────────────────────────
    df["inter_alarm_gap_min"] = (
        df.groupby("network_element_id")["timestamp"]
          .transform(lambda x: x.diff().dt.total_seconds() / 60)
    ).round(1)

    # ── Per-site MTBF and MTTR ────────────────────────────────────────────────
    site_mtbf = (
        df.groupby("network_element_id")["inter_alarm_gap_min"]
          .mean()
          .div(60)        # convert to hours
          .rename("site_mtbf_hrs")
          .round(2)
    )
    site_mttr = (
        df.groupby("network_element_id")["duration_minutes"]
          .mean()
          .rename("site_mttr_min")
          .round(1)
    )
    df = df.merge(site_mtbf, on="network_element_id", how="left")
    df = df.merge(site_mttr, on="network_element_id", how="left")
    log.info("  site_mtbf_hrs and site_mttr_min added")

    return df


# ─────────────────────────────────────────────────────────────────────────────
# Convenience runner
# ─────────────────────────────────────────────────────────────────────────────

def run_alarm_preprocessing(df: pd.DataFrame, save: bool = True) -> pd.DataFrame:
    """
    Run the full alarm preprocessing pipeline:
      validate → normalise timestamps → handle active → dedup flapping → enrich.

    Parameters
    ----------
    df   : Raw alarm DataFrame from data_loader.load_alarm_data().
    save : If True, write to PATHS['processed_alarm'].

    Returns
    -------
    Fully preprocessed alarm DataFrame.
    """
    log.info("=" * 60)
    log.info("PHASE 3 — Alarm Preprocessing Pipeline")
    log.info("=" * 60)

    validate_alarm_schema(df)
    df = normalize_alarm_timestamps(df)
    df = handle_active_alarms(df)
    df = deduplicate_flapping_alarms(df)
    df = enrich_alarm_features(df)

    log.info(f"Alarm preprocessing complete — final shape: {df.shape}")
    base_cols = set(REQUIRED_ALARM_COLUMNS)
    new_cols  = [c for c in df.columns if c not in base_cols]
    log.info(f"  Columns added: {new_cols}")

    if save:
        out_path = PATHS["processed_alarm"]
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_path, index=False)
        log.info(f"Processed alarm data saved → {out_path}")

    return df


if __name__ == "__main__":
    from phase2_ingestion.data_loader import load_alarm_data
    raw   = load_alarm_data()
    processed = run_alarm_preprocessing(raw, save=True)
    print(processed.head(3).T)
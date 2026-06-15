"""
phase2_ingestion/data_loader.py
================================
Phase 2 — Data Ingestion

Loads raw KPI and alarm data from either:
  (a) CSV flat files  (DATA_SOURCE = 'csv')  — default for synthetic data
  (b) Live EMS DB     (DATA_SOURCE = 'sql')  — for production use

Applying KPI_COLUMN_MAP / ALARM_COLUMN_MAP from settings renames any
non-standard column names to the project's canonical names, so all
downstream code is database-agnostic.
"""

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.logger import get_logger
from config.settings import (
    DATA_SOURCE,
    CSV_PATHS,
    DB_CONNECTION_STRING,
    TABLE_NAMES,
    KPI_COLUMN_MAP,
    ALARM_COLUMN_MAP,
    DATE_FILTER,
)

log = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _apply_column_map(df: pd.DataFrame, col_map: dict) -> pd.DataFrame:
    """
    Rename raw DB / CSV columns to canonical project names using col_map.
    Only renames entries where the mapped value is not None.
    """
    rename = {v: k for k, v in col_map.items() if v is not None}
    missing = [v for v in rename if v not in df.columns]
    if missing:
        log.warning(f"Columns expected by column map but not found in data: {missing}")
    return df.rename(columns=rename)


def _apply_date_filter(df: pd.DataFrame, ts_col: str = "timestamp") -> pd.DataFrame:
    """
    Restrict the DataFrame to the date window defined in DATE_FILTER.
    Skips silently if start/end are both None.
    """
    start = DATE_FILTER.get("start")
    end   = DATE_FILTER.get("end")

    if start is None and end is None:
        return df

    ts = pd.to_datetime(df[ts_col], errors="coerce")
    mask = pd.Series(True, index=df.index)
    if start:
        mask &= ts >= pd.Timestamp(start)
    if end:
        mask &= ts <= pd.Timestamp(end)

    original = len(df)
    df = df.loc[mask].copy()
    log.info(f"Date filter ({start} → {end}): {original:,} → {len(df):,} rows")
    return df


# ─────────────────────────────────────────────────────────────────────────────
# CSV loaders
# ─────────────────────────────────────────────────────────────────────────────

def _load_kpi_csv() -> pd.DataFrame:
    path = CSV_PATHS["kpi"]
    log.info(f"Loading KPI data from CSV: {path}")
    df = pd.read_csv(path, parse_dates=["timestamp"])
    log.info(f"  Loaded {len(df):,} rows × {df.shape[1]} columns")
    return df


def _load_alarm_csv() -> pd.DataFrame:
    path = CSV_PATHS["alarm"]
    log.info(f"Loading alarm data from CSV: {path}")
    df = pd.read_csv(
        path,
        parse_dates=["timestamp", "cleared_timestamp"],
    )
    log.info(f"  Loaded {len(df):,} rows × {df.shape[1]} columns")
    return df


# ─────────────────────────────────────────────────────────────────────────────
# SQL loaders
# ─────────────────────────────────────────────────────────────────────────────

def _build_date_clause(ts_col: str) -> str:
    """Return a SQL WHERE clause fragment based on DATE_FILTER settings."""
    clauses = []
    if DATE_FILTER.get("start"):
        clauses.append(f"{ts_col} >= '{DATE_FILTER['start']}'")
    if DATE_FILTER.get("end"):
        clauses.append(f"{ts_col} <= '{DATE_FILTER['end']} 23:59:59'")
    return ("WHERE " + " AND ".join(clauses)) if clauses else ""


def _load_kpi_sql() -> pd.DataFrame:
    from sqlalchemy import create_engine

    table = TABLE_NAMES["kpi"]
    where = _build_date_clause("timestamp")
    query = f"SELECT * FROM {table} {where} ORDER BY timestamp"

    log.info(f"Loading KPI data from DB table '{table}'")
    engine = create_engine(DB_CONNECTION_STRING)
    df = pd.read_sql(query, engine, parse_dates=["timestamp"])
    log.info(f"  Loaded {len(df):,} rows × {df.shape[1]} columns")
    return df


def _load_alarm_sql() -> pd.DataFrame:
    from sqlalchemy import create_engine

    table = TABLE_NAMES["alarm"]
    where = _build_date_clause("timestamp")
    query = f"SELECT * FROM {table} {where} ORDER BY timestamp"

    log.info(f"Loading alarm data from DB table '{table}'")
    engine = create_engine(DB_CONNECTION_STRING)
    df = pd.read_sql(query, engine, parse_dates=["timestamp", "cleared_timestamp"])
    log.info(f"  Loaded {len(df):,} rows × {df.shape[1]} columns")
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Public interface
# ─────────────────────────────────────────────────────────────────────────────

def load_kpi_data() -> pd.DataFrame:
    """
    Load raw KPI data from the configured source (CSV or SQL).

    Returns a DataFrame with canonical column names, parsed timestamps,
    and optional date filtering applied.
    """
    if DATA_SOURCE == "csv":
        df = _load_kpi_csv()
    elif DATA_SOURCE == "sql":
        df = _load_kpi_sql()
    else:
        raise ValueError(f"Unknown DATA_SOURCE '{DATA_SOURCE}'. Set 'csv' or 'sql'.")

    df = _apply_column_map(df, KPI_COLUMN_MAP)
    df = _apply_date_filter(df, ts_col="timestamp")

    # Ensure timestamp is datetime type
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")

    log.info(f"KPI data ready: {df.shape[0]:,} rows, sites={df['network_element_id'].nunique()}, "
             f"period={df['timestamp'].min()} → {df['timestamp'].max()}")
    return df


def load_alarm_data() -> pd.DataFrame:
    """
    Load raw alarm data from the configured source (CSV or SQL).

    Returns a DataFrame with canonical column names, parsed timestamps,
    and optional date filtering applied.
    """
    if DATA_SOURCE == "csv":
        df = _load_alarm_csv()
    elif DATA_SOURCE == "sql":
        df = _load_alarm_sql()
    else:
        raise ValueError(f"Unknown DATA_SOURCE '{DATA_SOURCE}'. Set 'csv' or 'sql'.")

    df = _apply_column_map(df, ALARM_COLUMN_MAP)
    df = _apply_date_filter(df, ts_col="timestamp")

    # Ensure timestamp fields are datetime
    df["timestamp"]         = pd.to_datetime(df["timestamp"], errors="coerce")
    df["cleared_timestamp"] = pd.to_datetime(df["cleared_timestamp"], errors="coerce")

    log.info(f"Alarm data ready: {df.shape[0]:,} rows, severity={df['severity'].value_counts().to_dict()}")
    return df


if __name__ == "__main__":
    kpi   = load_kpi_data()
    alarm = load_alarm_data()
    print("\nKPI DataFrame head:")
    print(kpi.head(3))
    print("\nAlarm DataFrame head:")
    print(alarm.head(3))
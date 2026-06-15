"""
config/settings.py
==================
Central configuration for the HFCL EMS Data Analysis project.

TO SWITCH FROM SYNTHETIC CSV DATA TO REAL EMS DATA:
  1. Set DATA_SOURCE = 'sql'
  2. Fill in DB_CONNECTION_STRING with your actual EMS DB credentials
  3. Set TABLE_NAMES to match your production schema
  4. Adjust KPI_THRESHOLDS if the real system uses different SLA targets
  Everything else (phases, ETL, analysis) works unchanged.
"""

import os
from pathlib import Path

# ── Project root ──────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent

# ── Data source configuration ─────────────────────────────────────────────────
# Options: 'csv'  →  load from flat files in data/raw/
#          'sql'  →  load via SQLAlchemy from the live EMS DB
DATA_SOURCE = "csv"

# CSV paths (used when DATA_SOURCE = 'csv')
CSV_PATHS = {
    "kpi":   str(BASE_DIR / "data" / "raw" / "ems_kpi_data.csv"),
    "alarm": str(BASE_DIR / "data" / "raw" / "ems_alarm_data.csv"),
}

# SQL connection (used when DATA_SOURCE = 'sql')
# Best practice: store credentials in a .env file and load with python-dotenv.
# Example .env:
#   EMS_DB_USER=analyst
#   EMS_DB_PASSWORD=secret
#   EMS_DB_HOST=10.0.0.5
#   EMS_DB_PORT=5432
#   EMS_DB_NAME=ems_prod
DB_CONNECTION_STRING = (
    "postgresql+psycopg2://"
    "{user}:{password}@{host}:{port}/{db}".format(
        user=os.getenv("EMS_DB_USER", "analyst"),
        password=os.getenv("EMS_DB_PASSWORD", "password"),
        host=os.getenv("EMS_DB_HOST", "localhost"),
        port=os.getenv("EMS_DB_PORT", "5432"),
        db=os.getenv("EMS_DB_NAME", "ems_prod"),
    )
)

# Table / view names in the real EMS database (update to match actual schema)
TABLE_NAMES = {
    "kpi":   "ems_kpi_metrics",
    "alarm": "ems_alarm_log",
}

# Optional: restrict analysis to a specific date window (ISO strings or None)
DATE_FILTER = {
    "start": None,   # e.g. "2025-01-01"
    "end":   None,   # e.g. "2025-01-31"
}

# ── Column name mapping ───────────────────────────────────────────────────────
# If the real DB uses different column names, map them here.
# The ETL pipeline will rename to these canonical names before processing.
# Values on the LEFT are canonical names; values on the RIGHT are raw DB names.
# Set value = None to skip renaming (column name already matches canonical).
KPI_COLUMN_MAP = {
    "timestamp":                  None,   # e.g. "collected_at" in real DB
    "network_element_id":         None,   # e.g. "ne_id"
    "technology":                 None,   # e.g. "rat_type"
    "region":                     None,
    "throughput_mbps":            None,
    "availability_pct":           None,
    "utilization_pct":            None,
    "latency_ms":                 None,
    "rtwp_dbm":                   None,
    "handover_success_rate_pct":  None,
    "call_drop_rate_pct":         None,
    "rach_success_rate_pct":      None,
}

ALARM_COLUMN_MAP = {
    "alarm_id":           None,
    "timestamp":          None,   # e.g. "raised_at"
    "cleared_timestamp":  None,   # e.g. "cleared_at"
    "network_element_id": None,
    "technology":         None,
    "region":             None,
    "alarm_type":         None,
    "alarm_code":         None,
    "severity":           None,
    "severity_rank":      None,
    "status":             None,
    "description":        None,
    "duration_minutes":   None,
}

# ── KPI thresholds (SLA / operational limits) ────────────────────────────────
# Alarms are raised (or KPIs are flagged) when values cross these boundaries.
# Adjust to match your operator's actual SLA targets.
KPI_THRESHOLDS = {
    # Metric                      : (breach_direction, threshold)
    # breach_direction: 'below' means breach when value < threshold
    #                   'above' means breach when value > threshold
    "throughput_mbps":            ("below",  10.0),   # < 10 Mbps → degraded
    "availability_pct":           ("below",  99.5),   # < 99.5 % → SLA breach
    "utilization_pct":            ("above",  80.0),   # > 80 % → congestion risk
    "latency_ms":                 ("above",  50.0),   # > 50 ms → degraded UX
    "rtwp_dbm":                   ("above", -90.0),   # > -90 dBm → high interference
    "handover_success_rate_pct":  ("below",  95.0),   # < 95 % → mobility issues
    "call_drop_rate_pct":         ("above",   2.0),   # > 2 % → poor voice quality
    "rach_success_rate_pct":      ("below",  95.0),   # < 95 % → access failure
}

# Technology-specific throughput thresholds (override the generic one above)
TECH_THROUGHPUT_THRESHOLDS = {
    "4G": 10.0,    # Mbps
    "5G": 50.0,    # Mbps
}

# ── Alarm severity ordering ───────────────────────────────────────────────────
SEVERITY_ORDER = {
    "Critical": 1,
    "Major":    2,
    "Minor":    3,
    "Warning":  4,
}

# Alarm types classified by root-cause category (for Phase 4 grouping)
ALARM_CATEGORY_MAP = {
    "Radio":        ["High Interference", "RTWP High", "RACH Congestion", "HO Failure Rate High",
                     "Call Drop Rate High", "High Utilization", "Low Throughput"],
    "Transport":    ["Link Down", "Transmission Fault", "High Latency"],
    "Power":        ["Battery Backup Fail"],
    "Hardware":     ["Fan Unit Failure"],
    "Software":     ["SW Process Restart"],
}

# ── Preprocessing parameters ─────────────────────────────────────────────────
# KPI data granularity (in minutes) — matches data collection frequency
KPI_GRANULARITY_MINUTES = 15

# Rolling window sizes expressed as number of KPI periods
# e.g. 4 periods × 15 min = 1 hour moving average
ROLLING_WINDOWS = {
    "1h":  4,    # 4 × 15 min
    "6h":  24,   # 24 × 15 min
    "24h": 96,   # 96 × 15 min
}

# Hours considered "peak" traffic (inclusive range, 24-hour clock)
PEAK_HOURS = (8, 22)   # 08:00–22:00

# Alarms raised within this many minutes of a preceding identical alarm
# on the same site are treated as "flapping" and removed
ALARM_FLAPPING_WINDOW_MINUTES = 10

# KPI missing-value imputation strategy: 'ffill', 'interpolate', or 'flag'
KPI_MISSING_STRATEGY = "ffill"

# ── Output paths ──────────────────────────────────────────────────────────────
PATHS = {
    "processed_kpi":   str(BASE_DIR / "data" / "processed" / "kpi_processed.csv"),
    "processed_alarm": str(BASE_DIR / "data" / "processed" / "alarm_processed.csv"),
    "plots":           str(BASE_DIR / "outputs" / "plots"),
    "reports":         str(BASE_DIR / "outputs" / "reports"),
    "profiling":       str(BASE_DIR / "outputs" / "profiling_reports"),
}

# ── Telecom domain reference (Phase 1 study material) ─────────────────────────
KPI_DEFINITIONS = {
    "throughput_mbps":            "Total user data transferred per unit time (Mbps). "
                                  "Key measure of network capacity utilisation.",
    "availability_pct":           "Percentage of time the network element is operational. "
                                  "Target typically ≥ 99.5 %.",
    "utilization_pct":            "Fraction of radio resources (PRBs) actively used. "
                                  "High values indicate congestion risk.",
    "latency_ms":                 "Round-trip time for a data packet (ms). "
                                  "High latency degrades real-time services.",
    "rtwp_dbm":                   "Received Total Wideband Power — total power seen at the "
                                  "antenna, including interference (dBm). "
                                  "Values > -90 dBm indicate interference.",
    "handover_success_rate_pct":  "Percentage of handovers (cell changes) that complete "
                                  "successfully. Low values cause dropped calls in motion.",
    "call_drop_rate_pct":         "Percentage of established calls that are dropped "
                                  "unintentionally. A key voice quality KPI.",
    "rach_success_rate_pct":      "Random Access Channel success rate — measures how "
                                  "reliably UEs can attach to the network.",
}

ALARM_TAXONOMY = {
    "Critical": "Immediate impact on service; requires urgent attention (< 15 min response).",
    "Major":    "Significant performance degradation; action needed within 1 hour.",
    "Minor":    "Limited impact; schedule resolution within 4 hours.",
    "Warning":  "Pre-emptive indicator; monitor and review.",
}
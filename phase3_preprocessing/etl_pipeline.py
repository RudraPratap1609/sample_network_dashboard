"""
phase3_preprocessing/etl_pipeline.py
======================================
Phase 3 — Combined ETL Pipeline

Orchestrates the complete data flow from raw source to processed outputs:

  load_kpi_data()      ─→  run_kpi_preprocessing()   ─→  kpi_processed.csv
  load_alarm_data()    ─→  run_alarm_preprocessing()  ─→  alarm_processed.csv

Also provides:
  - load_processed_data()  : reload previously saved processed files.
  - print_etl_summary()    : print a concise table of what the ETL produced.

Usage (from project root)
-------------------------
  python -m phase3_preprocessing.etl_pipeline          # run full ETL
  python -m phase3_preprocessing.etl_pipeline --kpi    # KPI only
  python -m phase3_preprocessing.etl_pipeline --alarm  # alarm only
"""

import sys
import argparse
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.logger import get_logger
from config.settings import PATHS
from phase2_ingestion.data_loader import load_kpi_data, load_alarm_data
from phase3_preprocessing.kpi_preprocessor import run_kpi_preprocessing
from phase3_preprocessing.alarm_preprocessor import run_alarm_preprocessing

log = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Sub-pipeline runners
# ─────────────────────────────────────────────────────────────────────────────

def run_kpi_etl(save: bool = True) -> pd.DataFrame:
    """Load raw KPI data and run the full preprocessing pipeline."""
    log.info("Starting KPI ETL pipeline…")
    raw_kpi = load_kpi_data()
    processed_kpi = run_kpi_preprocessing(raw_kpi, save=save)
    return processed_kpi


def run_alarm_etl(save: bool = True) -> pd.DataFrame:
    """Load raw alarm data and run the full preprocessing pipeline."""
    log.info("Starting alarm ETL pipeline…")
    raw_alarm = load_alarm_data()
    processed_alarm = run_alarm_preprocessing(raw_alarm, save=save)
    return processed_alarm


def run_full_etl(save: bool = True) -> dict:
    """
    Run both KPI and alarm ETL pipelines end-to-end.

    Parameters
    ----------
    save : Write processed DataFrames to data/processed/*.csv.

    Returns
    -------
    dict with keys 'kpi' and 'alarm', each holding the processed DataFrame.
    """
    log.info("=" * 65)
    log.info("PHASE 3 — Full ETL Pipeline starting")
    log.info("=" * 65)

    kpi   = run_kpi_etl(save=save)
    alarm = run_alarm_etl(save=save)

    print_etl_summary(kpi, alarm)
    return {"kpi": kpi, "alarm": alarm}


# ─────────────────────────────────────────────────────────────────────────────
# Load previously processed data
# ─────────────────────────────────────────────────────────────────────────────

def load_processed_data() -> dict:
    """
    Reload the processed KPI and alarm DataFrames from data/processed/*.csv.
    Raises FileNotFoundError if ETL has not been run yet.

    Returns
    -------
    dict with keys 'kpi' and 'alarm'.
    """
    kpi_path   = PATHS["processed_kpi"]
    alarm_path = PATHS["processed_alarm"]

    for path in [kpi_path, alarm_path]:
        if not Path(path).exists():
            raise FileNotFoundError(
                f"Processed file not found: {path}\n"
                "Run run_full_etl() first to generate processed data."
            )

    kpi = pd.read_csv(
        kpi_path,
        parse_dates=["timestamp"],
        dtype={"network_element_id": str, "technology": str, "region": str},
    )
    alarm = pd.read_csv(
        alarm_path,
        parse_dates=["timestamp", "cleared_timestamp"],
        dtype={"network_element_id": str, "alarm_type": str, "severity": str},
    )

    log.info(f"Loaded processed KPI   : {kpi.shape}")
    log.info(f"Loaded processed alarms: {alarm.shape}")
    return {"kpi": kpi, "alarm": alarm}


# ─────────────────────────────────────────────────────────────────────────────
# ETL summary report
# ─────────────────────────────────────────────────────────────────────────────

def print_etl_summary(kpi: pd.DataFrame, alarm: pd.DataFrame) -> None:
    """Print a concise summary of what the ETL produced."""
    BORDER = "=" * 65
    log.info(BORDER)
    log.info("PHASE 3 — ETL Summary")
    log.info(BORDER)

    # KPI
    log.info("  KPI DATASET")
    log.info(f"    Shape          : {kpi.shape[0]:,} rows × {kpi.shape[1]} cols")
    log.info(f"    Sites          : {kpi['network_element_id'].nunique()}")
    log.info(f"    Technologies   : {sorted(kpi['technology'].unique())}")
    log.info(f"    Date range     : {kpi['timestamp'].min()} → {kpi['timestamp'].max()}")
    log.info(f"    Breach rows    : {kpi['any_breach'].sum():,} ({kpi['any_breach'].mean()*100:.1f}%)")
    log.info(f"    Avg health     : {kpi['kpi_health_score'].mean():.1f} / 100")
    log.info(f"    New columns    : {kpi.shape[1] - 12} features added by ETL")

    # Alarm
    log.info("")
    log.info("  ALARM DATASET")
    log.info(f"    Shape          : {alarm.shape[0]:,} rows × {alarm.shape[1]} cols")
    log.info(f"    Sites          : {alarm['network_element_id'].nunique()}")
    log.info(f"    Severity mix   : {alarm['severity'].value_counts().to_dict()}")
    log.info(f"    Categories     : {alarm['alarm_category'].value_counts().to_dict()}")
    log.info(f"    Mean MTTR      : {alarm['duration_minutes'].mean():.1f} min")
    log.info(f"    Active alarms  : {alarm.get('is_active', pd.Series([False])).sum()}")

    # Output files
    log.info("")
    log.info("  OUTPUT FILES")
    for key in ["processed_kpi", "processed_alarm"]:
        p = Path(PATHS[key])
        if p.exists():
            size_kb = p.stat().st_size / 1024
            log.info(f"    ✔  {p.name:<35} {size_kb:6.1f} KB")
        else:
            log.info(f"    –  {PATHS[key]}  (not saved)")

    log.info(BORDER)
    log.info("Phase 3 ETL complete. Proceed to Phase 4: KPI & Alarm Analysis.")
    log.info(BORDER)


# ─────────────────────────────────────────────────────────────────────────────
# CLI entrypoint
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HFCL EMS — Phase 3 ETL Runner")
    parser.add_argument("--kpi",   action="store_true", help="Run KPI ETL only")
    parser.add_argument("--alarm", action="store_true", help="Run alarm ETL only")
    parser.add_argument("--no-save", dest="save", action="store_false",
                        help="Skip saving processed CSVs")
    parser.set_defaults(save=True)
    args = parser.parse_args()

    if args.kpi and not args.alarm:
        run_kpi_etl(save=args.save)
    elif args.alarm and not args.kpi:
        run_alarm_etl(save=args.save)
    else:
        run_full_etl(save=args.save)
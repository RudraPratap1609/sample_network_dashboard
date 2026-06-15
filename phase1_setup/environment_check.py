"""
phase1_setup/environment_check.py
===================================
Phase 1 — Domain & Environment Setup

Responsibilities
----------------
1. Verify all required Python packages are installed and print their versions.
2. Test data connectivity (CSV files or live DB).
3. Print a formatted reference guide covering:
   - Telecom KPI definitions and SLA targets
   - EMS alarm taxonomy (severity levels, response times)
   - Project file/folder overview
"""

import importlib
import sys
from pathlib import Path

# Add project root to path so config is importable when run directly
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.logger import get_logger
from config.settings import (
    DATA_SOURCE, CSV_PATHS, DB_CONNECTION_STRING,
    KPI_DEFINITIONS, KPI_THRESHOLDS, ALARM_TAXONOMY, PATHS,
)

log = get_logger(__name__)

# ── Required packages and their pip install names ─────────────────────────────
REQUIRED_PACKAGES = {
    "pandas":       "pandas",
    "numpy":        "numpy",
    "matplotlib":   "matplotlib",
    "seaborn":      "seaborn",
    "plotly":       "plotly",
    "scipy":        "scipy",
    "sklearn":      "scikit-learn",
    "sqlalchemy":   "SQLAlchemy",
    "openpyxl":     "openpyxl",
    "dotenv":       "python-dotenv",
    "tqdm":         "tqdm",
}

# ydata-profiling is optional (large install); check separately
OPTIONAL_PACKAGES = {
    "ydata_profiling": "ydata-profiling",
    "statsmodels":     "statsmodels",
}


# ─────────────────────────────────────────────────────────────────────────────
# 1. Package Verification
# ─────────────────────────────────────────────────────────────────────────────

def check_packages() -> bool:
    """
    Import every required package and print its version.
    Returns True if all required packages are present, False otherwise.
    """
    log.info("=" * 60)
    log.info("PHASE 1 — Checking installed packages")
    log.info("=" * 60)

    all_ok = True
    for import_name, pip_name in REQUIRED_PACKAGES.items():
        try:
            mod = importlib.import_module(import_name)
            version = getattr(mod, "__version__", "n/a")
            log.info(f"  ✔  {pip_name:<25} {version}")
        except ImportError:
            log.error(f"  ✘  {pip_name:<25} NOT INSTALLED — run: pip install {pip_name}")
            all_ok = False

    log.info("")
    log.info("Optional packages:")
    for import_name, pip_name in OPTIONAL_PACKAGES.items():
        try:
            mod = importlib.import_module(import_name)
            version = getattr(mod, "__version__", "n/a")
            log.info(f"  ✔  {pip_name:<25} {version}")
        except ImportError:
            log.info(f"  –  {pip_name:<25} not installed (optional — pip install {pip_name})")

    log.info("")
    return all_ok


# ─────────────────────────────────────────────────────────────────────────────
# 2. Data Connectivity Test
# ─────────────────────────────────────────────────────────────────────────────

def check_data_connectivity() -> bool:
    """
    Depending on DATA_SOURCE in settings.py:
      - CSV mode  : verify the files exist and can be read.
      - SQL mode  : attempt a lightweight SELECT 1 against the EMS DB.
    Returns True if connection is healthy.
    """
    log.info("=" * 60)
    log.info(f"PHASE 1 — Testing data connectivity  (source = '{DATA_SOURCE}')")
    log.info("=" * 60)

    if DATA_SOURCE == "csv":
        return _check_csv_files()
    elif DATA_SOURCE == "sql":
        return _check_sql_connection()
    else:
        log.error(f"Unknown DATA_SOURCE '{DATA_SOURCE}'. Set 'csv' or 'sql' in config/settings.py.")
        return False


def _check_csv_files() -> bool:
    import pandas as pd

    ok = True
    for key, path in CSV_PATHS.items():
        p = Path(path)
        if not p.exists():
            log.error(f"  ✘  {key} CSV not found: {path}")
            ok = False
        else:
            df = pd.read_csv(path, nrows=3)
            log.info(f"  ✔  {key:<10}  {p.name}  |  {len(pd.read_csv(path)):,} rows  |  cols: {list(df.columns)}")
    return ok


def _check_sql_connection() -> bool:
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(DB_CONNECTION_STRING)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        log.info("  ✔  Database connection successful")
        return True
    except Exception as exc:
        log.error(f"  ✘  Database connection failed: {exc}")
        log.info("      → Check DB_CONNECTION_STRING in config/settings.py")
        log.info("      → Or set DATA_SOURCE = 'csv' to use local CSV files")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# 3. Output Directory Setup
# ─────────────────────────────────────────────────────────────────────────────

def create_output_dirs():
    """Create all project output directories if they do not already exist."""
    log.info("=" * 60)
    log.info("PHASE 1 — Creating output directories")
    log.info("=" * 60)
    for name, path in PATHS.items():
        p = Path(path)
        # Skip keys that point to files (e.g. processed CSVs), only create dirs
        if p.suffix == "":
            p.mkdir(parents=True, exist_ok=True)
            log.info(f"  ✔  {name:<20} {p}")
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            log.info(f"  ✔  {name:<20} parent dir ready: {p.parent}")


# ─────────────────────────────────────────────────────────────────────────────
# 4. Domain Reference Printout
# ─────────────────────────────────────────────────────────────────────────────

def print_domain_reference():
    """
    Print a human-readable reference covering KPI definitions, thresholds,
    and alarm taxonomy — useful for onboarding or a quick team refresher.
    """
    BORDER = "=" * 60

    print(f"\n{BORDER}")
    print("TELECOM KPI REFERENCE")
    print(BORDER)
    print(f"{'KPI':<34} {'Threshold':<20} Definition")
    print("-" * 100)
    for metric, definition in KPI_DEFINITIONS.items():
        direction, value = KPI_THRESHOLDS[metric]
        threshold_str = f"{'>' if direction == 'above' else '<'} {value}"
        short_def = definition[:60] + "…" if len(definition) > 60 else definition
        print(f"  {metric:<32} {threshold_str:<20} {short_def}")

    print(f"\n{BORDER}")
    print("EMS ALARM TAXONOMY")
    print(BORDER)
    for severity, desc in ALARM_TAXONOMY.items():
        print(f"  {severity:<10} — {desc}")

    print(f"\n{BORDER}")
    print("COMMON ALARM TYPES IN THIS DATASET")
    print(BORDER)
    alarm_info = {
        "Call Drop Rate High":  "CDR exceeds threshold; often linked to interference or HO failures.",
        "Battery Backup Fail":  "AC power lost; site running on battery — risk of outage.",
        "Link Down":            "Backhaul connectivity lost; impacts all users on the cell.",
        "High Interference":    "RTWP elevated; indicates external interference or pilot pollution.",
        "High Latency":         "Round-trip time > 50 ms; real-time services degraded.",
        "SW Process Restart":   "Software watchdog triggered; possible memory leak or crash.",
        "Transmission Fault":   "Transport layer error on feeder/microwave link.",
        "Fan Unit Failure":     "Cooling failure — risk of equipment shutdown due to overheating.",
        "Low Throughput":       "User data rate below acceptable floor.",
        "High Utilization":     "PRB utilisation > 80 %; near-congestion state.",
        "HO Failure Rate High": "Handover failures elevated — mobile users experience drops.",
        "RACH Congestion":      "Access channel overloaded; UEs cannot attach reliably.",
    }
    for alarm, desc in alarm_info.items():
        print(f"  {alarm:<28} — {desc}")

    print(f"\n{BORDER}\n")


# ─────────────────────────────────────────────────────────────────────────────
# Entrypoint
# ─────────────────────────────────────────────────────────────────────────────

def run_phase1():
    """Run all Phase 1 checks in sequence."""
    packages_ok   = check_packages()
    data_ok       = check_data_connectivity()
    create_output_dirs()
    print_domain_reference()

    log.info("=" * 60)
    log.info("PHASE 1 SUMMARY")
    log.info("=" * 60)
    log.info(f"  Packages OK  : {'YES' if packages_ok else 'NO — see errors above'}")
    log.info(f"  Data OK      : {'YES' if data_ok    else 'NO — see errors above'}")
    log.info(f"  Source mode  : {DATA_SOURCE.upper()}")
    if packages_ok and data_ok:
        log.info("  → Ready to proceed to Phase 2 (Data Ingestion & Exploration)")
    else:
        log.warning("  → Fix the issues above before running Phase 2")
    log.info("")
    return packages_ok and data_ok


if __name__ == "__main__":
    run_phase1()
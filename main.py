"""
HFCL EMS Data Analysis Project — Master Runner

Runs all five phases in sequence, or individual phases on demand.

Usage
-----
  python main.py                     # run Phase 1 → 2 → 3 → 4 → 5 in order
  python main.py --phase 1           # environment check only
  python main.py --phase 2           # profiling only (requires Phase 1 passed)
  python main.py --phase 3           # ETL only
  python main.py --phase 4           # KPI & Alarm correlation analysis only
  python main.py --phase 5           # Excel report only (requires Phase 4 CSVs on disk)
  python main.py --phase 3 4         # ETL + Phase 4 analysis
  python main.py --phase 4 5         # analytics + Phase 5 report generation
  python main.py --no-plots          # skip matplotlib figure generation
  python main.py --html-profile      # generate ydata-profiling HTML reports
  python main.py --no-report         # run Phase 5 block but skip Excel report generation
"""

import sys
import argparse
from pathlib import Path

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.logger import get_logger

log = get_logger("main")


# ─────────────────────────────────────────────────────────────────────────────
# Phase runner functions
# Each function uses a lazy import so only the modules required for the
# selected phases are loaded — keeping startup fast and dependencies minimal.
# ─────────────────────────────────────────────────────────────────────────────

def run_phase1():
    from phase1_setup.environment_check import run_phase1 as _run
    return _run()


def run_phase2(generate_plots: bool = True, generate_html: bool = False):
    from phase2_ingestion.data_loader import load_kpi_data, load_alarm_data
    from phase2_ingestion.kpi_profiler import run_kpi_profiling
    from phase2_ingestion.alarm_profiler import run_alarm_profiling

    log.info("=" * 60)
    log.info("PHASE 2 — Data Ingestion & Exploration")
    log.info("=" * 60)

    kpi   = load_kpi_data()
    alarm = load_alarm_data()

    kpi_summary   = run_kpi_profiling(kpi,   generate_html_report=generate_html) if generate_plots else {}
    alarm_summary = run_alarm_profiling(alarm, generate_html_report=generate_html) if generate_plots else {}

    return kpi, alarm


def run_phase3(save: bool = True):
    from phase3_preprocessing.etl_pipeline import run_full_etl
    return run_full_etl(save=save)


def run_phase4(kpi_df, alarm_df, generate_plots: bool = True, save_dir: str | Path = "output"):
    """
    Executes Phase 4 analytical pipelines sequentially:
      1. KPI Trending & Breach Analysis
      2. Alarm Frequency Analysis
      3. KPI-Alarm Correlation & Root-Cause Discovery
    """
    from phase4_analysis.kpi_trending import run_kpi_trending
    from phase4_analysis.alarm_frequency import run_alarm_frequency_analysis
    from phase4_analysis.correlation_analysis import run_correlation_analysis

    log.info("=" * 60)
    log.info("PHASE 4 — Advanced Analytics & Correlation Engine")
    log.info("=" * 60)

    # 1. Run KPI Trending Engine
    kpi_trending_results = run_kpi_trending(
        kpi_df=kpi_df,
        save_dir=save_dir,
        generate_plots=generate_plots
    )

    # 2. Run Alarm Frequency Profiler
    alarm_freq_results = run_alarm_frequency_analysis(
        alarm_df=alarm_df,
        save_dir=save_dir,
        generate_plots=generate_plots
    )

    # 3. Run KPI-Alarm Cross-Correlation Matrix & Root-Cause Engine
    correlation_results = run_correlation_analysis(
        kpi_df=kpi_df,
        alarm_df=alarm_df,
        save_dir=save_dir,
        generate_plots=generate_plots
    )

    return {
        "kpi_trending": kpi_trending_results,
        "alarm_frequency": alarm_freq_results,
        "correlation": correlation_results
    }


def run_phase5(
    output_dir: str | Path = "output",
    phase4_subpath: str = "reports/phase4",
) -> Path:
    """
    Executes Phase 5 Part 3 — Automated Corporate Reporting Engine.

    Reads the Phase 4 analytical CSV exports from:
        <output_dir>/<phase4_subpath>/

    Produces the styled Weekly Network Health Summary workbook at:
        <output_dir>/reports/Weekly_Network_Health_Summary.xlsx

    Five sheets are generated:
        1. Executive Summary       — KPI breach overview & operational highlights
        2. Root-Cause Candidates   — Top-10 ranked alarm × KPI correlation pairs
        3. Degradation Windows     — Critical node KPI degradation events
        4. Alarm Frequency         — Pareto · NE ranking · category breakdown
        5. KPI Site Ranking        — Per-site breach rate table (all metrics)

    Parameters
    ----------
    output_dir
        Root output directory; must align with the ``--output-dir`` used
        for Phase 4 so that Phase 4 CSV inputs are discoverable.
    phase4_subpath
        Sub-path under ``output_dir`` that contains the Phase 4 CSV exports.
        Mirrors the ``--phase4-subpath`` flag of the Phase 4 engine.
        Default: ``reports/phase4``.

    Returns
    -------
    Path
        Absolute path to the generated ``.xlsx`` workbook.
    """
    # Lazy import — consistent with the pattern used by run_phase1..4.
    # Keeps openpyxl and pandas out of the import graph unless Phase 5 runs.
    from phase5_reporting.reporting.report_generator import generate_report

    log.info("=" * 60)
    log.info("PHASE 5 — Dashboards & Automated Reports")
    log.info("  Part 3: Weekly Excel Workbook Generation")
    log.info("=" * 60)

    report_path = generate_report(
        output_dir=output_dir,
        phase4_reports_subpath=phase4_subpath,
    )

    return report_path


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="HFCL EMS Data Analysis — Phase Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # ── Core phase selector ──────────────────────────────────────────────────
    # Phase 5 added to choices and to the default run list so that a bare
    # `python main.py` automatically covers the full ingestion → report cycle.
    parser.add_argument(
        "--phase", nargs="+", type=int, choices=[1, 2, 3, 4, 5],
        default=[1, 2, 3, 4, 5],
        help="Which phase(s) to run (default: all five)",
    )

    # ── Existing flags (unchanged) ───────────────────────────────────────────
    parser.add_argument(
        "--no-plots", dest="plots", action="store_false",
        help="Skip matplotlib plot generation",
    )
    parser.add_argument(
        "--html-profile", dest="html_profile", action="store_true",
        help="Generate ydata-profiling HTML reports (slow, large install)",
    )
    parser.add_argument(
        "--no-save", dest="save", action="store_false",
        help="Do not save processed DataFrames to disk",
    )
    parser.add_argument(
        "--output-dir", type=str, default="output",
        help="Base folder directory for saving reports and analytics plots",
    )

    # ── New Phase 5 flags ────────────────────────────────────────────────────
    parser.add_argument(
        "--phase4-subpath", dest="phase4_subpath", type=str,
        default="reports/phase4",
        metavar="SUBPATH",
        help=(
            "Sub-directory under --output-dir where Phase 4 CSV exports live; "
            "consumed by the Phase 5 report generator. "
            "(default: reports/phase4)"
        ),
    )
    parser.add_argument(
        "--no-report", dest="report", action="store_false",
        help=(
            "Skip Excel workbook generation when Phase 5 is in the run list. "
            "Useful when you only want to re-launch the interactive Dash "
            "dashboard (app.py) without re-building the report."
        ),
    )

    parser.set_defaults(plots=True, html_profile=False, save=True, report=True)
    args = parser.parse_args()

    phases = sorted(set(args.phase))
    log.info(f"Running phases: {phases}")

    results = {}

    # ── Phase 1: Environment validation ─────────────────────────────────────
    if 1 in phases:
        ok = run_phase1()
        if not ok:
            log.error("Phase 1 failed — fix environment issues before continuing.")
            sys.exit(1)

    # ── Phase 2: Data ingestion & profiling ──────────────────────────────────
    if 2 in phases:
        kpi, alarm = run_phase2(generate_plots=args.plots, generate_html=args.html_profile)
        results["raw_kpi"]   = kpi
        results["raw_alarm"] = alarm

    # ── Phase 3: ETL preprocessing ───────────────────────────────────────────
    if 3 in phases:
        etl_result = run_phase3(save=args.save)
        results["processed_kpi"]   = etl_result["kpi"]
        results["processed_alarm"] = etl_result["alarm"]

    # ── Phase 4: Advanced analytics & correlation engine ─────────────────────
    if 4 in phases:
        # Check if Phase 3 was loaded in the current run execution loop
        if "processed_kpi" not in results or "processed_alarm" not in results:
            log.warning("Phase 4 requested without running Phase 3 in context.")
            log.info("Attempting to fall back on executing an active ETL compilation window...")
            etl_result = run_phase3(save=args.save)
            results["processed_kpi"]   = etl_result["kpi"]
            results["processed_alarm"] = etl_result["alarm"]

        phase4_res = run_phase4(
            kpi_df=results["processed_kpi"],
            alarm_df=results["processed_alarm"],
            generate_plots=args.plots,
            save_dir=args.output_dir
        )
        results["phase4_analytics"] = phase4_res

    # ── Phase 5: Dashboards & automated reporting ────────────────────────────
    if 5 in phases:
        if not args.report:
            # User explicitly requested --no-report; skip Excel generation but
            # surface the dashboard launch command for convenience.
            log.info("Phase 5 report generation skipped (--no-report flag active).")
            log.info(
                "  →  Launch the interactive dashboard independently with: "
                "python phase5_reporting/dashboard/app.py"
            )
        else:
            # Phase 5 consumes Phase 4 CSV exports from disk, not the in-memory
            # DataFrames.  Three cases are handled:
            #
            #   A) Phase 4 ran in this session → CSVs were just written; proceed.
            #   B) Phase 4 was skipped but prior CSVs exist on disk → proceed
            #      from the cached exports (log an informational notice).
            #   C) Phase 4 was skipped AND no CSVs exist yet → auto-trigger the
            #      Phase 3 → Phase 4 pipeline so the report has complete data.
            #
            if "phase4_analytics" not in results:
                phase4_csv_dir = Path(args.output_dir) / args.phase4_subpath
                csv_available  = (
                    phase4_csv_dir.is_dir()
                    and any(phase4_csv_dir.glob("*.csv"))
                )

                if csv_available:
                    # Case B — cached CSVs found; nothing extra needed.
                    log.info(
                        "Phase 4 was not run in this session — existing CSV exports "
                        f"found at: {phase4_csv_dir}"
                    )
                    log.info("Proceeding with Phase 5 report generation from cached CSVs.")
                else:
                    # Case C — no CSVs on disk; auto-run Phase 3 → Phase 4 first.
                    log.warning(
                        "Phase 5 requires Phase 4 CSV outputs, but none were found at: "
                        f"{phase4_csv_dir}"
                    )
                    log.info(
                        "Auto-running Phase 3 → Phase 4 to generate the required "
                        "analytical CSV inputs before building the report…"
                    )

                    if "processed_kpi" not in results or "processed_alarm" not in results:
                        log.info("  ↳  Phase 3 (ETL) not yet in context — running now…")
                        etl_result = run_phase3(save=args.save)
                        results["processed_kpi"]   = etl_result["kpi"]
                        results["processed_alarm"] = etl_result["alarm"]

                    phase4_res = run_phase4(
                        kpi_df=results["processed_kpi"],
                        alarm_df=results["processed_alarm"],
                        generate_plots=args.plots,
                        save_dir=args.output_dir,
                    )
                    results["phase4_analytics"] = phase4_res

            # Generate the styled Excel workbook from Phase 4 CSV exports.
            report_path = run_phase5(
                output_dir=args.output_dir,
                phase4_subpath=args.phase4_subpath,
            )
            results["phase5_report"] = report_path

    # ── Final summary ─────────────────────────────────────────────────────────
    log.info("=" * 60)
    log.info(f"All requested phases ({phases}) completed successfully.")
    if "phase5_report" in results:
        log.info(f"  Weekly report  →  {results['phase5_report']}")
        log.info(
            "  Dashboard      →  "
            "python phase5_reporting/dashboard/app.py"
        )
    log.info("=" * 60)
    return results


if __name__ == "__main__":
    main()
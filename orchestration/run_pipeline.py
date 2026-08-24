"""
run_pipeline.py

Orchestrates the full pipeline end to end, in order, with logging and
failure handling -- the role a scheduler (Windows Task Scheduler / cron /
Prefect) would play in production. Run this nightly in a real deployment.

    python3 orchestration/run_pipeline.py
"""

import logging
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    handlers=[logging.FileHandler(ROOT / "output" / "pipeline_run.log"), logging.StreamHandler()],
)
log = logging.getLogger("pipeline")


def run_step(name: str, cmd: list[str], cwd: Path):
    log.info(f"START  {name}")
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        log.error(f"FAILED {name}\n{result.stderr}")
        raise SystemExit(f"Pipeline halted at step: {name}")
    log.info(f"OK     {name}")
    if result.stdout.strip():
        for line in result.stdout.strip().splitlines():
            log.info(f"       {line}")


def main():
    (ROOT / "output").mkdir(exist_ok=True)
    log.info("=== Foundation data pipeline run starting ===")

    run_step("Generate synthetic source data", ["python3", "generate_synthetic_data.py"], ROOT / "data_generation")
    run_step("Run Alteryx-style prep workflow", ["python3", "alteryx_style_workflow.py"], ROOT)
    run_step("Compute mart metrics (pandas)", ["python3", "build_dashboard_data.py"], ROOT / "data_generation")
    run_step("Run data quality unit tests", ["python3", "-m", "pytest", "tests/", "-q"], ROOT)
    run_step("Build dashboard", ["python3", "build_html.py"], ROOT / "dashboard")
    run_step("Build paginated reconciliation statement", ["python3", "generate_paginated_statement.py"], ROOT / "reporting")

    log.info("=== Pipeline run complete ===")
    log.info("Note: SQL warehouse steps (sql/01-06) require a live Postgres")
    log.info("instance and are run separately -- see README.md for psql commands.")


if __name__ == "__main__":
    main()

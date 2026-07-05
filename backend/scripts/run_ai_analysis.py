from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.cli import configure_logging, run_json_command  # noqa: E402
from app.services import AiAnalysisService  # noqa: E402


logger = configure_logging("backend_run_ai_analysis")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate explanatory AI analysis from structured chart data.")
    parser.add_argument("--date", dest="analysis_date", help="Analysis date, for example 2026-06-29.")
    parser.add_argument("--limit", type=int, default=20)
    return parser.parse_args()


def main() -> dict:
    args = parse_args()
    analysis_date = date.fromisoformat(args.analysis_date) if args.analysis_date else None
    with AiAnalysisService() as service:
        result = service.generate_daily_summary(analysis_date=analysis_date, limit=args.limit)
    logger.info("ai analysis finished")
    return result


if __name__ == "__main__":
    run_json_command(main, logger, "ai analysis failed", indent=2)

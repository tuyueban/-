from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.cli import configure_logging, run_json_command  # noqa: E402
from app.db import init_db  # noqa: E402
from app.services import AiAnalysisService, HeatScoreService  # noqa: E402


logger = configure_logging("backend_run_heat_score")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute daily heat scores and optional AI analysis.")
    parser.add_argument("--date", dest="score_date", help="Score date, for example 2026-06-29.")
    parser.add_argument("--limit", type=int, default=None, help="Limit computed songs, mostly for testing.")
    parser.add_argument("--ai", action="store_true", help="Generate AI heat analysis after score calculation.")
    return parser.parse_args()


def main() -> dict:
    args = parse_args()
    init_db()
    score_date = date.fromisoformat(args.score_date) if args.score_date else None
    with HeatScoreService() as service:
        result = service.compute_daily(score_date=score_date, limit=args.limit)
    if args.ai and result.get("status") == "success":
        with AiAnalysisService() as service:
            result["ai_analysis"] = service.generate_daily_summary(
                analysis_date=date.fromisoformat(str(result["score_date"])),
                limit=20,
            )
    logger.info("heat score finished")
    return result


if __name__ == "__main__":
    run_json_command(main, logger, "heat score failed", indent=2)

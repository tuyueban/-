from __future__ import annotations

import argparse
import json
import logging
import sys
import traceback
from datetime import date, datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.db import init_db  # noqa: E402
from app.services import AiAnalysisService, CrawlerService, HeatScoreService  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run daily crawl and heat score job.")
    parser.add_argument("--date", dest="target_date", help="Target date, for example 2026-06-29.")
    parser.add_argument("--with-ai", action="store_true", help="Generate AI summary after heat calculation.")
    parser.add_argument("--skip-crawl", action="store_true", help="Skip crawler.")
    parser.add_argument("--skip-heat", action="store_true", help="Skip heat score calculation.")
    return parser.parse_args()


def setup_logger(target_date: date) -> logging.Logger:
    log_dir = BACKEND_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("daily_job")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    log_file = log_dir / f"daily_job_{target_date.strftime('%Y%m%d')}.log"
    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(handler)

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(console)

    return logger


def main() -> None:
    args = parse_args()
    target_date = date.fromisoformat(args.target_date) if args.target_date else date.today()
    logger = setup_logger(target_date)

    started_at = datetime.now()
    result = {
        "status": "success",
        "job_date": target_date.isoformat(),
        "crawl_result": None,
        "heat_result": None,
        "ai_result": None,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": None,
    }

    try:
        init_db()
        logger.info("Daily job started, target_date=%s", target_date)

        if not args.skip_crawl:
            logger.info("Running crawler")
            result["crawl_result"] = CrawlerService().run_all(chart_date=target_date, persist=True)

        if not args.skip_heat:
            logger.info("Computing heat score")
            with HeatScoreService() as service:
                result["heat_result"] = service.compute_daily(score_date=target_date)

        if args.with_ai:
            logger.info("Generating AI analysis")
            with AiAnalysisService() as service:
                result["ai_result"] = service.generate_daily_summary(
                    analysis_date=target_date,
                    limit=20,
                )

        result["finished_at"] = datetime.now().isoformat(timespec="seconds")
        logger.info("Daily job finished")
        print(json.dumps(result, ensure_ascii=False, indent=2))

    except Exception as exc:
        logger.exception("Daily job failed")
        result["status"] = "failed"
        result["error"] = str(exc)
        result["traceback"] = traceback.format_exc()
        result["finished_at"] = datetime.now().isoformat(timespec="seconds")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.cli import configure_logging, run_json_command  # noqa: E402
from app.db import init_db  # noqa: E402
from app.services import CrawlerService  # noqa: E402


logger = configure_logging("backend_run_crawler")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run song crawlers and save data to MySQL.")
    parser.add_argument("--platform", default="all", choices=["all", "netease", "qq", "kugou"])
    parser.add_argument("--date", dest="chart_date", help="Chart date, for example 2026-06-29.")
    parser.add_argument("--no-persist", action="store_true", help="Fetch only, do not save to MySQL.")
    parser.add_argument("--init-db", action="store_true", help="Create MySQL tables before crawling.")
    parser.add_argument("--artists-only", action="store_true", help="Crawl artist rankings only.")
    return parser.parse_args()


def main() -> dict[str, Any]:
    args = parse_args()
    if args.init_db:
        init_db()

    chart_date = date.fromisoformat(args.chart_date) if args.chart_date else None
    service = CrawlerService()
    persist = not args.no_persist
    if args.artists_only:
        result = (
            service.run_artist_all(chart_date=chart_date, persist=persist)
            if args.platform == "all"
            else service.run_artist_platform(args.platform, chart_date=chart_date, persist=persist)
        )
    elif args.platform == "all":
        result = service.run_all(chart_date=chart_date, persist=persist)
    else:
        result = service.run_platform(
            args.platform,
            chart_date=chart_date,
            persist=persist,
        )
    logger.info("crawler finished")
    return result


if __name__ == "__main__":
    run_json_command(main, logger, "crawler failed", indent=2)

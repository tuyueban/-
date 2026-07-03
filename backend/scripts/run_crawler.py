from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.db import init_db  # noqa: E402
from app.services import CrawlerService  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run song crawlers and save data to MySQL.")
    parser.add_argument("--platform", default="all", choices=["all", "netease", "qq", "kugou"])
    parser.add_argument("--date", dest="chart_date", help="Chart date, for example 2026-06-29.")
    parser.add_argument("--no-persist", action="store_true", help="Fetch only, do not save to MySQL.")
    parser.add_argument("--init-db", action="store_true", help="Create MySQL tables before crawling.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.init_db:
        init_db()

    chart_date = date.fromisoformat(args.chart_date) if args.chart_date else None
    service = CrawlerService()
    if args.platform == "all":
        result = service.run_all(chart_date=chart_date, persist=not args.no_persist)
    else:
        result = service.run_platform(
            args.platform,
            chart_date=chart_date,
            persist=not args.no_persist,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

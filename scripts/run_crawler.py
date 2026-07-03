from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services import CrawlerService  # noqa: E402


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("run_crawler")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run music chart crawler")
    parser.add_argument("--platform", default="all", choices=["all", "netease", "qq", "kugou"])
    parser.add_argument("--date", dest="chart_date", type=date.fromisoformat)
    parser.add_argument("--no-persist", action="store_true")
    parser.add_argument("--artists-only", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    service = CrawlerService()
    persist = not args.no_persist
    if args.artists_only:
        result: dict[str, Any] = (
            service.run_artist_all(args.chart_date, persist)
            if args.platform == "all"
            else service.run_artist_platform(args.platform, args.chart_date, persist)
        )
    else:
        result = (
            service.run_all(args.chart_date, persist)
            if args.platform == "all"
            else service.run_platform(args.platform, args.chart_date, persist)
        )
    logger.info("crawler finished")
    print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        logger.exception("crawler failed")
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1) from exc

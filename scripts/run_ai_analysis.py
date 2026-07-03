from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services import AiAnalysisService  # noqa: E402


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("run_ai_analysis")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate explanatory AI analysis from structured chart data")
    parser.add_argument("--date", dest="analysis_date", type=date.fromisoformat)
    parser.add_argument("--limit", type=int, default=20)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with AiAnalysisService() as service:
        result = service.generate_daily_summary(analysis_date=args.analysis_date, limit=args.limit)
    logger.info("ai analysis finished")
    print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        logger.exception("ai analysis failed")
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1) from exc

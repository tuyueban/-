from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services import AiAnalysisService, HeatScoreService  # noqa: E402


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("run_heat_score")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute daily heat score")
    parser.add_argument("--date", dest="score_date", type=date.fromisoformat)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--ai", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.limit:
        logger.warning("--limit is for testing only. Do not use it in demo/production data generation.")
    with HeatScoreService() as service:
        result = service.compute_daily(score_date=args.score_date, limit=args.limit)
    if args.ai and result.get("status") == "success":
        with AiAnalysisService() as service:
            result["ai_analysis"] = service.generate_daily_summary(
                analysis_date=date.fromisoformat(str(result["score_date"])),
                limit=20,
            )
    logger.info("heat score finished")
    print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        logger.exception("heat score failed")
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1) from exc

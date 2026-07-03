from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.db.session import SessionLocal  # noqa: E402
from app.models import AiHeatAnalysis  # noqa: E402


BAD_KEYWORDS = (
    "AI call failed",
    "401 Authorization Required",
    "Client error",
    "本地兜底",
    "兜底分析",
    "接口失败",
    "公开搜索来源",
    "数据侧观察",
    "不确定性",
    "### 结论",
    "### 证据",
    "外部因素",
    "风险提示",
    "注意事项",
    "无法确定",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean saved AI analysis rows that contain old technical error text.")
    parser.add_argument("--apply", action="store_true", help="Delete matched rows. Without this flag, only prints a dry-run summary.")
    args = parser.parse_args()

    with SessionLocal() as db:
        rows = db.query(AiHeatAnalysis).all()
        matched = [
            row
            for row in rows
            if any(keyword in (row.content or "") for keyword in BAD_KEYWORDS)
        ]

        for row in matched:
            print(f"{row.id}\t{row.analysis_date}\t{row.analysis_type}\t{row.model_name}")

        if not args.apply:
            print(f"Dry run: {len(matched)} row(s) matched. Re-run with --apply to delete them.")
            return

        for row in matched:
            db.delete(row)
        db.commit()
        print(f"Deleted {len(matched)} row(s).")


if __name__ == "__main__":
    main()

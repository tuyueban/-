from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.db.session import SessionLocal  # noqa: E402
from scripts.demo_data_utils import DEFAULT_DEMO_DATA_PATH, DEMO_MODELS, row_to_dict  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export current MySQL data as a portable demo dataset.")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_DEMO_DATA_PATH,
        help="Output JSON path. Defaults to demo_data/demo_dataset.json.",
    )
    return parser.parse_args()


def main() -> dict[str, Any]:
    args = parse_args()
    output_path = args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)

    db = SessionLocal()
    try:
        tables: dict[str, list[dict[str, Any]]] = {}
        counts: dict[str, int] = {}
        for model in DEMO_MODELS:
            primary_keys = [column.asc() for column in model.__table__.primary_key.columns]
            rows = db.query(model).order_by(*primary_keys).all()
            tables[model.__tablename__] = [row_to_dict(row) for row in rows]
            counts[model.__tablename__] = len(rows)

        payload = {
            "metadata": {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "source": "music_hot_analysis MySQL export",
                "table_order": [model.__tablename__ for model in DEMO_MODELS],
                "counts": counts,
            },
            "tables": tables,
        }
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"status": "success", "output": str(output_path), "counts": counts}
    finally:
        db.close()


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False, indent=2))

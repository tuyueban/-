from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import delete


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.db import init_db  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from scripts.demo_data_utils import DEFAULT_DEMO_DATA_PATH, DEMO_MODELS, MODEL_BY_TABLE, dict_to_row  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import the bundled demo dataset into MySQL.")
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_DEMO_DATA_PATH,
        help="Input JSON path. Defaults to demo_data/demo_dataset.json.",
    )
    parser.add_argument("--reset", action="store_true", help="Clear demo tables before importing.")
    return parser.parse_args()


def main() -> dict[str, Any]:
    args = parse_args()
    init_db()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    tables: dict[str, list[dict[str, Any]]] = payload.get("tables") or {}

    db = SessionLocal()
    try:
        if args.reset:
            for model in reversed(DEMO_MODELS):
                db.execute(delete(model))
            db.flush()

        counts: dict[str, int] = {}
        for table_name in payload.get("metadata", {}).get("table_order", tables.keys()):
            model = MODEL_BY_TABLE.get(table_name)
            if model is None:
                continue
            rows = [dict_to_row(model, row) for row in tables.get(table_name, [])]
            if rows:
                db.bulk_save_objects(rows)
            counts[table_name] = len(rows)

        db.commit()
        return {"status": "success", "input": str(args.input), "reset": args.reset, "counts": counts}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False, indent=2))

import json
import logging
from collections.abc import Callable
from typing import Any

def configure_logging(name: str) -> logging.Logger:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return logging.getLogger(name)

def print_json(payload: Any, *, indent: int | None = None) -> None:
    print(json.dumps(payload, ensure_ascii=False, default=str, indent=indent))

def run_json_command(command: Callable[[], Any], logger: logging.Logger, failure_message: str, *, indent: int | None = None) -> Any:
    try:
        result = command()
    except Exception as exc:  # noqa: BLE001
        logger.exception(failure_message)
        print_json({"status": "failed", "error": str(exc)}, indent=indent)
        raise SystemExit(1) from exc
    print_json(result, indent=indent)
    return result

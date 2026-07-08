from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.models import (
    AiHeatAnalysis,
    Artist,
    ArtistChart,
    ArtistChartItem,
    Chart,
    ChartSong,
    EtlLog,
    HeatScoreDaily,
    MusicStyle,
    PlatformSong,
    Song,
    SongArtist,
    SongMetric,
)


PROJECT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DEMO_DATA_PATH = PROJECT_DIR / "demo_data" / "demo_dataset.json"

DEMO_MODELS = [
    MusicStyle,
    Song,
    Artist,
    Chart,
    ArtistChart,
    PlatformSong,
    SongArtist,
    ChartSong,
    SongMetric,
    HeatScoreDaily,
    ArtistChartItem,
    AiHeatAnalysis,
    EtlLog,
]

MODEL_BY_TABLE = {model.__tablename__: model for model in DEMO_MODELS}


def serialize_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def deserialize_value(value: Any, python_type: type[Any] | None) -> Any:
    if value is None:
        return None
    if python_type is date:
        return date.fromisoformat(value)
    if python_type is datetime:
        return datetime.fromisoformat(value)
    if python_type is Decimal:
        return Decimal(str(value))
    return value


def column_python_type(column: Any) -> type[Any] | None:
    try:
        return column.type.python_type
    except NotImplementedError:
        return None


def row_to_dict(row: Any) -> dict[str, Any]:
    return {
        column.name: serialize_value(getattr(row, column.name))
        for column in row.__table__.columns
    }


def dict_to_row(model: type[Any], row: dict[str, Any]) -> Any:
    values = {}
    for column in model.__table__.columns:
        if column.name in row:
            values[column.name] = deserialize_value(row[column.name], column_python_type(column))
    return model(**values)

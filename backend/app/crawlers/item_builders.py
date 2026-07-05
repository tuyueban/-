import json
from datetime import datetime
from typing import Any

from app.crawlers.dtos import ArtistChartItem, ChartSongItem
from app.crawlers.utils import clean_artist_name, clean_song_name, detect_version_type

def build_chart_song_item(*, platform: str, chart: Any, rank: int, raw_song_name: str, raw_artist_name: str, artist_names: list[str], platform_song_id: str, chart_date: Any, raw_metadata: dict[str, Any], source_url: str | None = None, **platform_fields: Any) -> ChartSongItem:
    return ChartSongItem(
        platform=platform,
        chart_name=chart.name,
        chart_type=chart.chart_type,
        rank=rank,
        song_name=clean_song_name(raw_song_name),
        artist_name=clean_artist_name(raw_artist_name),
        raw_song_name=raw_song_name,
        raw_artist_name=raw_artist_name,
        display_artist_name=raw_artist_name,
        artist_names=artist_names,
        primary_artist_name=artist_names[0] if artist_names else None,
        version_type=detect_version_type(raw_song_name),
        platform_song_id=platform_song_id,
        extra_metadata=json.dumps(raw_metadata, ensure_ascii=False),
        chart_date=chart_date,
        collect_time=datetime.now(),
        source_url=source_url,
        style_key=chart.style_key,
        style_name=chart.style_name,
        **platform_fields,
    )

def build_artist_chart_item(*, platform: str, chart: Any, rank: int, artist_name: str, platform_artist_id: str, chart_date: Any, raw_metadata: dict[str, Any], source_url: str | None = None, **platform_fields: Any) -> ArtistChartItem:
    return ArtistChartItem(platform=platform, chart_name=chart.name, chart_type=chart.chart_type, rank=rank, artist_name=artist_name, platform_artist_id=platform_artist_id, extra_metadata=json.dumps(raw_metadata, ensure_ascii=False), chart_date=chart_date, collect_time=datetime.now(), source_url=source_url, **platform_fields)

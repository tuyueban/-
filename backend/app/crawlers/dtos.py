from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass(frozen=True)
class ChartConfig:
    key: str
    name: str
    chart_type: str
    source_id: str
    style_key: str | None = None
    style_name: str | None = None


@dataclass(frozen=True)
class ArtistChartConfig:
    key: str
    name: str
    chart_type: str
    source_id: str


@dataclass
class ChartSongItem:
    platform: str
    chart_name: str
    chart_type: str
    rank: int
    song_name: str
    artist_name: str
    platform_song_id: str
    chart_date: date
    collect_time: datetime
    chart_size: int | None = None
    raw_song_name: str | None = None
    raw_artist_name: str | None = None
    display_artist_name: str | None = None
    artist_names: list[str] = field(default_factory=list)
    primary_artist_name: str | None = None
    version_type: str | None = None
    platform_song_mid: str | None = None
    album_id: str | None = None
    album_mid: str | None = None
    song_hash: str | None = None
    extra_metadata: str | None = None
    album_name: str | None = None
    song_url: str | None = None
    cover_url: str | None = None
    artist_avatar_url: str | None = None
    source_url: str | None = None
    style_key: str | None = None
    style_name: str | None = None

@dataclass
class ArtistChartItem:
    platform: str
    chart_name: str
    chart_type: str
    rank: int
    artist_name: str
    platform_artist_id: str
    chart_date: date
    collect_time: datetime
    artist_avatar_url: str | None = None
    artist_url: str | None = None
    extra_metadata: str | None = None
    source_url: str | None = None


@dataclass
class SongMetricItem:
    platform: str
    platform_song_id: str
    metric_time: datetime
    is_success: bool
    song_name: str | None = None
    artist_name: str | None = None
    comment_count: int | None = None
    metric_source: str | None = None
    fail_reason: str | None = None


@dataclass
class PlatformCrawlResult:
    platform_key: str
    platform: str
    chart_date: date
    chart_songs: list[ChartSongItem] = field(default_factory=list)
    artist_charts: list[ArtistChartItem] = field(default_factory=list)
    metrics: list[SongMetricItem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def chart_count(self) -> int:
        return len(self.chart_songs)

    @property
    def artist_chart_count(self) -> int:
        return len(self.artist_charts)

    @property
    def metric_count(self) -> int:
        return len(self.metrics)

    @property
    def success_metric_count(self) -> int:
        return sum(1 for metric in self.metrics if metric.is_success)

    @property
    def comment_count_success_count(self) -> int:
        return sum(1 for metric in self.metrics if metric.comment_count is not None)

    @property
    def failed_metric_count(self) -> int:
        return max(0, self.metric_count - self.success_metric_count)

    def field_success_rates(self) -> dict[str, float]:
        total = self.metric_count or 1
        return {
            "comment_count_success_rate": round(self.comment_count_success_count / total, 4),
        }

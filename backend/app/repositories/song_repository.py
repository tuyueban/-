from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.crawlers.dtos import ArtistChartItem as ArtistChartDto, ChartSongItem, PlatformCrawlResult, SongMetricItem
from app.db.session import SessionLocal
from app.models import Artist, ArtistChart, ArtistChartItem, Chart, ChartSong, EtlLog, PlatformSong, Song, SongArtist, SongMetric
from app.crawlers.utils import (
    clean_artist_name,
    clean_song_name,
    is_instrumental,
    split_artist_names,
    canonical_artist_name,
    canonical_artist_key,
)

class SongRepository:
    def __init__(self, db: Session | None = None) -> None:
        self.db = db or SessionLocal()
        self._owns_session = db is None

    def close(self) -> None:
        if self._owns_session:
            self.db.close()

    def __enter__(self) -> "SongRepository":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        self.close()

    def save_result(self, result: PlatformCrawlResult) -> dict[str, int | str]:
        start_time = datetime.now()
        try:
            for item in result.chart_songs:
                self.upsert_chart_song(item)
            for item in result.artist_charts:
                self.upsert_artist_chart_item(item)
            for item in result.metrics:
                self.upsert_metric(item)

            status = "success" if not result.errors else "partial_success"
            if result.metric_count and result.success_metric_count < result.metric_count:
                status = "partial_success"
            self.db.add(
                EtlLog(
                    task_name="song_crawler",
                    platform=result.platform,
                    start_time=start_time,
                    end_time=datetime.now(),
                    status=status,
                    chart_count=result.chart_count,
                    metric_count=result.metric_count,
                    error_message=_etl_message(result),
                )
            )
            self.db.commit()
            return {
                "status": status,
                "chart_count": result.chart_count,
                "artist_chart_count": result.artist_chart_count,
                "metric_count": result.metric_count,
                "success_metric_count": result.success_metric_count,
            }
        except Exception:
            self.db.rollback()
            raise

    def upsert_chart_song(self, item: ChartSongItem) -> ChartSong:
        display_artist_name = _song_display_artist_name(item)
        song = self._get_or_create_song(item.song_name, display_artist_name, item.album_name)
        self._link_song_artists(song, item)
        self._upsert_platform_song(song, item)
        chart = self._get_or_create_chart(
            item.platform,
            item.chart_name,
            item.chart_type,
            item.style_key,
            item.style_name,
        )

        existing = self.db.execute(
            select(ChartSong).where(
                ChartSong.chart_id == chart.chart_id,
                ChartSong.song_id == song.song_id,
                ChartSong.chart_date == item.chart_date,
            )
        ).scalar_one_or_none()
        chart_size = max(item.chart_size or settings.crawler_top_n, item.rank)
        rank_score = round(max(0, (chart_size + 1 - item.rank) / chart_size * 100), 2)
        if existing:
            existing.rank = item.rank
            existing.rank_score = rank_score
            existing.collect_time = item.collect_time
            return existing

        chart_song = ChartSong(
            chart_id=chart.chart_id,
            song_id=song.song_id,
            rank=item.rank,
            rank_score=rank_score,
            chart_date=item.chart_date,
            collect_time=item.collect_time,
        )
        self.db.add(chart_song)
        self.db.flush()
        return chart_song

    def upsert_platform_song_snapshot(
        self,
        canonical_song: ChartSongItem,
        platform_item: ChartSongItem,
    ) -> PlatformSong:
        display_artist_name = _song_display_artist_name(canonical_song)
        song = self._get_or_create_song(
            canonical_song.song_name,
            display_artist_name,
            canonical_song.album_name,
        )
        self._link_song_artists(song, canonical_song)
        platform_item.song_name = canonical_song.song_name
        platform_item.artist_name = display_artist_name
        platform_item.display_artist_name = display_artist_name
        return self._upsert_platform_song(song, platform_item)

    def upsert_artist_chart_item(self, item: ArtistChartDto) -> ArtistChartItem:
        artist = self._upsert_artist(item.artist_name, item.artist_avatar_url)
        if artist is None:
            raise ValueError("artist_name is empty")
        chart = self._get_or_create_artist_chart(item.platform, item.chart_name, item.chart_type)

        existing = self.db.execute(
            select(ArtistChartItem).where(
                ArtistChartItem.chart_id == chart.chart_id,
                ArtistChartItem.artist_id == artist.artist_id,
                ArtistChartItem.chart_date == item.chart_date,
            )
        ).scalar_one_or_none()
        top_n = max(settings.crawler_top_n, item.rank)
        rank_score = round(max(0, (top_n + 1 - item.rank) / top_n * 100), 2)
        values = {
            "platform_artist_id": item.platform_artist_id,
            "rank": item.rank,
            "rank_score": rank_score,
            "chart_date": item.chart_date,
            "collect_time": item.collect_time,
            "artist_url": item.artist_url,
            "extra_metadata": item.extra_metadata,
        }
        if existing:
            for key, value in values.items():
                setattr(existing, key, value)
            return existing

        chart_item = ArtistChartItem(
            chart_id=chart.chart_id,
            artist_id=artist.artist_id,
            **values,
        )
        self.db.add(chart_item)
        self.db.flush()
        return chart_item

    def upsert_metric(self, item: SongMetricItem) -> SongMetric:
        song = self._find_song_by_platform(item.platform, item.platform_song_id)
        if song is None:
            song = self._get_or_create_song(item.song_name or "", item.artist_name or "", None)

        metric_date = item.metric_time.date()
        existing = self.db.execute(
            select(SongMetric).where(
                SongMetric.song_id == song.song_id,
                SongMetric.platform == item.platform,
                SongMetric.metric_date == metric_date,
            )
        ).scalar_one_or_none()

        values = {
            "platform_song_id": item.platform_song_id,
            "comment_count": item.comment_count,
            "collect_count": int(item.collect_count or 0),
            "metric_date": metric_date,
            "collect_time": item.metric_time,
            "metric_source": item.metric_source,
            "is_success": item.is_success,
            "fail_reason": item.fail_reason,
        }
        if existing:
            if existing.comment_count is not None and item.comment_count is None:
                values.pop("comment_count", None)
                values.pop("collect_count", None)
                values["is_success"] = True
            for key, value in values.items():
                setattr(existing, key, value)
            return existing

        metric = SongMetric(song_id=song.song_id, platform=item.platform, **values)
        self.db.add(metric)
        self.db.flush()
        return metric

    def _get_or_create_song(self, song_name: str, artist_name: str, album_name: str | None) -> Song:
        cleaned_song = clean_song_name(song_name) or song_name.strip() or "未知歌曲"
        cleaned_artist = _fit_text(clean_artist_name(artist_name) or artist_name.strip() or "未知歌手", 150)
        song = self.db.execute(
            select(Song).where(Song.song_name == cleaned_song, Song.artist_name == cleaned_artist)
        ).scalar_one_or_none()
        if song:
            if album_name and not song.album_name:
                song.album_name = album_name
            return song

        song = Song(
            song_name=cleaned_song,
            artist_name=cleaned_artist,
            album_name=album_name,
            is_instrumental=is_instrumental(song_name),
        )
        self.db.add(song)
        self.db.flush()
        return song

    def _upsert_platform_song(self, song: Song, item: ChartSongItem) -> PlatformSong:
        platform_song = self.db.execute(
            select(PlatformSong).where(
                PlatformSong.platform == item.platform,
                PlatformSong.platform_song_id == item.platform_song_id,
            )
        ).scalar_one_or_none()
        if platform_song:
            platform_song.song_id = song.song_id
            platform_song.platform_song_mid = item.platform_song_mid
            platform_song.album_id = item.album_id
            platform_song.album_mid = item.album_mid
            platform_song.song_hash = item.song_hash
            platform_song.extra_metadata = item.extra_metadata
            platform_song.raw_song_name = item.raw_song_name
            platform_song.raw_artist_name = item.raw_artist_name
            platform_song.version_type = item.version_type
            platform_song.song_url = item.song_url
            platform_song.cover_url = item.cover_url
            return platform_song

        platform_song = PlatformSong(
            song_id=song.song_id,
            platform=item.platform,
            platform_song_id=item.platform_song_id,
            platform_song_mid=item.platform_song_mid,
            album_id=item.album_id,
            album_mid=item.album_mid,
            song_hash=item.song_hash,
            extra_metadata=item.extra_metadata,
            raw_song_name=item.raw_song_name,
            raw_artist_name=item.raw_artist_name,
            version_type=item.version_type,
            song_url=item.song_url,
            cover_url=item.cover_url,
        )
        self.db.add(platform_song)
        self.db.flush()
        return platform_song

    def _upsert_artist(self, artist_name: str, avatar_url: str | None) -> Artist | None:
        canonical_name = canonical_artist_name(artist_name)
        normalized_name = canonical_artist_key(artist_name)

        if not canonical_name or not normalized_name:
            return None

        matched_artists = self.db.execute(
            select(Artist).where(
                or_(
                    Artist.normalized_name == normalized_name,
                    Artist.artist_name == canonical_name,
                )
            )
        ).scalars().all()
        artist = _choose_artist_match(matched_artists, canonical_name, normalized_name)

        if artist:
            artist_name_taken = any(
                matched.artist_id != artist.artist_id
                and matched.artist_name == canonical_name
                for matched in matched_artists
            )
            normalized_name_taken = any(
                matched.artist_id != artist.artist_id
                and matched.normalized_name == normalized_name
                for matched in matched_artists
            )

            if artist.artist_name != canonical_name and not artist_name_taken:
                artist.artist_name = canonical_name

            if not artist.canonical_name:
                artist.canonical_name = canonical_name

            if not artist.normalized_name and not normalized_name_taken:
                artist.normalized_name = normalized_name

            if avatar_url and not artist.avatar_url:
                artist.avatar_url = avatar_url

            return artist

        artist = Artist(
            artist_name=canonical_name,
            canonical_name=canonical_name,
            normalized_name=normalized_name,
            avatar_url=avatar_url,
        )

        self.db.add(artist)
        self.db.flush()

        return artist

    def _link_song_artists(self, song: Song, item: ChartSongItem) -> None:
        artist_names = _artist_names_for_item(item)

        seen: set[str] = set()
        cleaned_artist_names: list[str] = []

        for artist_name in artist_names:
            key = canonical_artist_key(artist_name)

            if not key:
                continue

            if key in seen:
                continue

            seen.add(key)
            cleaned_artist_names.append(artist_name)

        self.db.execute(
            delete(SongArtist).where(SongArtist.song_id == song.song_id)
        )

        for index, artist_name in enumerate(cleaned_artist_names):
            artist = self._upsert_artist(
                artist_name,
                item.artist_avatar_url if index == 0 else None,
            )

            if artist is None:
                continue

            self.db.add(
                SongArtist(
                    song_id=song.song_id,
                    artist_id=artist.artist_id,
                    role="primary" if index == 0 else "featured",
                    sort_order=index,
                )
            )

        self.db.flush()

    def _get_or_create_chart(
            self,
            platform: str,
            chart_name: str,
            chart_type: str,
            style_key: str | None = None,
            style_name: str | None = None,
    ) -> Chart:
        chart = self.db.execute(
            select(Chart).where(
                Chart.platform == platform,
                Chart.chart_name == chart_name,
            )
        ).scalar_one_or_none()

        if chart:
            chart.chart_type = chart_type
            chart.style_key = style_key
            chart.style_name = style_name
            return chart

        chart = Chart(
            platform=platform,
            chart_name=chart_name,
            chart_type=chart_type,
            style_key=style_key,
            style_name=style_name,
        )
        self.db.add(chart)
        self.db.flush()
        return chart

    def _get_or_create_artist_chart(self, platform: str, chart_name: str, chart_type: str) -> ArtistChart:
        chart = self.db.execute(
            select(ArtistChart).where(ArtistChart.platform == platform, ArtistChart.chart_name == chart_name)
        ).scalar_one_or_none()
        if chart:
            chart.chart_type = chart_type
            return chart

        chart = ArtistChart(platform=platform, chart_name=chart_name, chart_type=chart_type)
        self.db.add(chart)
        self.db.flush()
        return chart

    def _find_song_by_platform(self, platform: str, platform_song_id: str) -> Song | None:
        platform_song = self.db.execute(
            select(PlatformSong).where(
                PlatformSong.platform == platform,
                PlatformSong.platform_song_id == platform_song_id,
            )
        ).scalar_one_or_none()
        return platform_song.song if platform_song else None


def _etl_message(result: PlatformCrawlResult) -> str | None:
    lines = []
    if result.artist_chart_count:
        lines.append(f"artist_chart_count={result.artist_chart_count}")
    lines.extend(result.errors)
    return "\n".join(lines) if lines else None


def _choose_artist_match(
    artists: list[Artist],
    canonical_name: str,
    normalized_name: str,
) -> Artist | None:
    if not artists:
        return None

    for artist in artists:
        if artist.artist_name == canonical_name:
            return artist

    for artist in artists:
        if artist.normalized_name == normalized_name:
            return artist

    return artists[0]


def _song_display_artist_name(item: ChartSongItem) -> str:
    for artist_name in [
        item.display_artist_name,
        item.primary_artist_name,
        *(_artist_names_for_item(item)[:1]),
        item.artist_name,
    ]:
        if artist_name and artist_name.strip():
            return _fit_text(artist_name.strip(), 150)
    return "未知歌手"


def _fit_text(value: str, max_length: int) -> str:
    return value[:max_length] if len(value) > max_length else value


def _artist_names_for_item(item: ChartSongItem) -> list[str]:
    if getattr(item, "artist_names", None):
        names = [
            name.strip()
            for name in item.artist_names
            if name and name.strip()
        ]
        if names:
            return names

    raw_artist_name = (
        getattr(item, "raw_artist_name", None)
        or getattr(item, "display_artist_name", None)
        or item.artist_name
    )

    names = split_artist_names(raw_artist_name)

    if names:
        return names

    return [item.artist_name] if item.artist_name else []

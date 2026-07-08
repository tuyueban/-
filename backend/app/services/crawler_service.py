from __future__ import annotations

from datetime import date, datetime
from typing import Callable

from sqlalchemy import select

from app.core.config import Settings, settings
from app.crawlers import KugouMusicCrawler, NeteaseMusicCrawler, QQMusicCrawler
from app.crawlers.base import BaseMusicCrawler
from app.crawlers.dtos import ChartSongItem, PlatformCrawlResult, SongMetricItem
from app.models import HeatScoreDaily, PlatformSong, Song
from app.repositories import SongRepository


CrawlerFactory = Callable[[], BaseMusicCrawler]


class CrawlerService:
    def __init__(self, app_settings: Settings = settings) -> None:
        self.settings = app_settings
        self.factories: dict[str, CrawlerFactory] = {
            "netease": self._factory(NeteaseMusicCrawler),
            "qq": self._factory(QQMusicCrawler),
            "kugou": self._factory(KugouMusicCrawler),
        }

    def platforms(self) -> list[dict[str, str]]:
        return [
            {"key": platform_key, "name": self._platform_display_name(platform_key)}
            for platform_key in self.factories
        ]

    def run_platform(
        self,
        platform_key: str,
        chart_date: date | None = None,
        persist: bool = True,
    ) -> dict[str, object]:
        if platform_key not in self.factories:
            supported = ", ".join(self.factories)
            raise ValueError(f"unsupported platform: {platform_key}; supported: {supported}")

        crawler = self.factories[platform_key]()
        try:
            result = crawler.crawl(chart_date=chart_date, top_n=self.settings.crawler_top_n)
        finally:
            crawler.close()

        saved = None
        if persist:
            with SongRepository() as repository:
                saved = repository.save_result(result)

        return self._summary(result, saved)

    def run_all(self, chart_date: date | None = None, persist: bool = True) -> dict[str, object]:
        platform_results = [
            self.run_platform(platform_key, chart_date=chart_date, persist=persist)
            for platform_key in self.factories
        ]
        return {
            "status": "success" if all(item["status"] == "success" for item in platform_results) else "partial_success",
            "platforms": platform_results,
            "chart_count": sum(int(item["chart_count"]) for item in platform_results),
            "artist_chart_count": sum(int(item["artist_chart_count"]) for item in platform_results),
            "metric_count": sum(int(item["metric_count"]) for item in platform_results),
            "success_metric_count": sum(int(item["success_metric_count"]) for item in platform_results),
            "field_success_rates": _aggregate_field_rates(platform_results),
        }

    def complete_analysis_songs(self, score_date: date, limit: int | None = None) -> dict[str, int]:
        with SongRepository() as repository:
            songs = _analysis_songs(repository, score_date, limit)
            result = self._complete_missing_platforms(songs, repository, score_date)
            repository.db.commit()
            return {
                "analysis_song_count": len(songs),
                **result,
            }

    def _complete_missing_platforms(
        self,
        songs: list[Song],
        repository: SongRepository,
        score_date: date,
    ) -> dict[str, int]:
        platform_names = self._platform_names()
        skipped = 0
        queried = 0
        completed = 0
        missing = 0
        metric_count = 0

        for song in songs:
            existing_platforms = _existing_platform_keys(repository, song.song_id, platform_names)
            if len(existing_platforms) >= len(self.factories):
                skipped += 1
                continue

            source_song = _chart_item_from_song(song, score_date)
            keyword = _search_keyword(source_song)
            for platform_key in self.factories.keys() - existing_platforms:
                queried += 1
                crawler = self.factories[platform_key]()
                try:
                    platform_song = crawler.search_song(keyword)
                    if platform_song is None:
                        missing += 1
                        repository.upsert_metric(_missing_metric(crawler, source_song))
                        metric_count += 1
                        continue

                    repository.upsert_platform_song_snapshot(source_song, platform_song)
                    try:
                        repository.upsert_metric(crawler.fetch_metric(platform_song))
                    except Exception as exc:  # noqa: BLE001
                        repository.upsert_metric(_failed_metric(crawler, platform_song, exc))
                    completed += 1
                    metric_count += 1
                except Exception as exc:  # noqa: BLE001
                    missing += 1
                    repository.upsert_metric(_failed_metric(crawler, source_song, exc))
                    metric_count += 1
                finally:
                    crawler.close()

        return {
            "skipped_complete_song_count": skipped,
            "platform_query_count": queried,
            "completed_platform_count": completed,
            "missing_platform_count": missing,
            "metric_count": metric_count,
        }

    def run_artist_platform(
        self,
        platform_key: str,
        chart_date: date | None = None,
        persist: bool = True,
    ) -> dict[str, object]:
        if platform_key not in self.factories:
            supported = ", ".join(self.factories)
            raise ValueError(f"unsupported platform: {platform_key}; supported: {supported}")

        current_chart_date = chart_date or date.today()
        crawler = self.factories[platform_key]()
        result = PlatformCrawlResult(
            platform_key=crawler.platform_key,
            platform=crawler.platform_name,
            chart_date=current_chart_date,
        )
        try:
            for chart in crawler.artist_chart_configs:
                try:
                    result.artist_charts.extend(
                        crawler.fetch_artist_chart(chart, current_chart_date, self.settings.crawler_top_n)
                    )
                except Exception as exc:  # noqa: BLE001
                    result.errors.append(f"{chart.name}: {exc}")
        finally:
            crawler.close()

        saved = None
        if persist:
            with SongRepository() as repository:
                saved = repository.save_result(result)
        return self._summary(result, saved)

    def run_artist_all(self, chart_date: date | None = None, persist: bool = True) -> dict[str, object]:
        platform_results = [
            self.run_artist_platform(platform_key, chart_date=chart_date, persist=persist)
            for platform_key in self.factories
        ]
        return {
            "status": "success" if all(item["status"] == "success" for item in platform_results) else "partial_success",
            "platforms": platform_results,
            "artist_chart_count": sum(int(item["artist_chart_count"]) for item in platform_results),
        }

    def _factory(self, crawler_cls: type[BaseMusicCrawler]) -> CrawlerFactory:
        return lambda: crawler_cls(
            timeout_seconds=self.settings.crawler_timeout_seconds,
            retry_times=self.settings.crawler_retry_times,
            delay_seconds=self.settings.crawler_delay_seconds,
            metric_concurrency=self.settings.crawler_metric_concurrency,
            metric_delay_seconds=self.settings.crawler_metric_delay_seconds,
        )

    def _platform_names(self) -> dict[str, str]:
        names: dict[str, str] = {}
        for platform_key in self.factories:
            names[platform_key] = self._platform_display_name(platform_key)
        return names

    def _platform_display_name(self, platform_key: str) -> str:
        crawler = self.factories[platform_key]()
        try:
            return crawler.platform_name
        finally:
            crawler.close()

    @staticmethod
    def _summary(result: PlatformCrawlResult, saved: dict[str, int | str] | None) -> dict[str, object]:
        status = "success" if not result.errors else "partial_success"
        if saved:
            status = str(saved["status"])
        if result.metric_count and result.success_metric_count < result.metric_count:
            status = "partial_success"
        return {
            "status": status,
            "platform_key": result.platform_key,
            "platform": result.platform,
            "chart_date": result.chart_date.isoformat(),
            "chart_count": result.chart_count,
            "artist_chart_count": result.artist_chart_count,
            "metric_count": result.metric_count,
            "success_metric_count": result.success_metric_count,
            "comment_count_success_count": result.comment_count_success_count,
            "failed_metric_count": result.failed_metric_count,
            **result.field_success_rates(),
            "errors": result.errors,
            "persisted": saved is not None,
        }


def _aggregate_field_rates(platform_results: list[dict[str, object]]) -> dict[str, float]:
    metric_count = sum(int(item.get("metric_count", 0)) for item in platform_results)
    if metric_count <= 0:
        return {
            "comment_count_success_rate": 0,
        }
    return {
        "comment_count_success_rate": round(
            sum(int(item.get("comment_count_success_count", 0)) for item in platform_results) / metric_count,
            4,
        ),
    }


def _analysis_songs(repository: SongRepository, score_date: date, limit: int | None) -> list[Song]:
    statement = (
        select(Song)
        .join(HeatScoreDaily, HeatScoreDaily.song_id == Song.song_id)
        .where(HeatScoreDaily.score_date == score_date)
        .order_by(HeatScoreDaily.rank)
    )
    if limit:
        statement = statement.limit(limit)
    return list(repository.db.execute(statement).scalars().all())


def _existing_platform_keys(
    repository: SongRepository,
    song_id: int,
    platform_names: dict[str, str],
) -> set[str]:
    platforms = repository.db.execute(
        select(PlatformSong.platform).where(PlatformSong.song_id == song_id)
    ).scalars().all()
    return {
        platform_key
        for platform in platforms
        for platform_key, platform_name in platform_names.items()
        if platform == platform_name
    }


def _chart_item_from_song(song: Song, score_date: date) -> ChartSongItem:
    return ChartSongItem(
        platform="analysis",
        chart_name="analysis_completion",
        chart_type="analysis_completion",
        rank=0,
        song_name=song.song_name,
        artist_name=song.artist_name,
        platform_song_id="",
        chart_date=score_date,
        collect_time=datetime.now(),
        album_name=song.album_name,
    )


def _search_keyword(item: ChartSongItem) -> str:
    artist = item.primary_artist_name or item.artist_name
    return " ".join(part for part in [item.song_name, artist] if part)


def _missing_metric(crawler: BaseMusicCrawler, source_song: ChartSongItem) -> SongMetricItem:
    return SongMetricItem(
        platform=crawler.platform_name,
        platform_song_id="",
        song_name=source_song.song_name,
        artist_name=source_song.artist_name,
        metric_time=datetime.now(),
        is_success=False,
        metric_source="analysis_platform_completion",
        fail_reason="search_not_found; is_on_chart=false",
    )


def _failed_metric(crawler: BaseMusicCrawler, song: ChartSongItem, exc: Exception) -> SongMetricItem:
    return SongMetricItem(
        platform=crawler.platform_name,
        platform_song_id=song.platform_song_id,
        song_name=song.song_name,
        artist_name=song.artist_name,
        metric_time=datetime.now(),
        is_success=False,
        metric_source=song.song_url or "analysis_platform_completion",
        fail_reason=f"analysis_platform_completion_failed: {exc}",
    )

from __future__ import annotations

from datetime import date
from typing import Callable

from app.core.config import Settings, settings
from app.crawlers import KugouMusicCrawler, NeteaseMusicCrawler, QQMusicCrawler
from app.crawlers.base import BaseMusicCrawler
from app.crawlers.dtos import PlatformCrawlResult
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
            {"key": "netease", "name": "网易云音乐"},
            {"key": "qq", "name": "QQ音乐"},
            {"key": "kugou", "name": "酷狗音乐"},
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
            self.run_platform(platform, chart_date=chart_date, persist=persist)
            for platform in self.factories
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
            self.run_artist_platform(platform, chart_date=chart_date, persist=persist)
            for platform in self.factories
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

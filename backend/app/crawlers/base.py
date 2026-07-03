from __future__ import annotations

import time
from threading import Lock
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from os import getenv
from typing import Any

import httpx

from app.crawlers.dtos import ArtistChartConfig, ArtistChartItem, ChartConfig, ChartSongItem, PlatformCrawlResult, SongMetricItem
from app.crawlers.utils import canonical_artist_key, clean_song_name


class BaseMusicCrawler(ABC):
    platform_key: str
    platform_name: str
    chart_configs: tuple[ChartConfig, ...]
    artist_chart_configs: tuple[ArtistChartConfig, ...] = ()

    def __init__(
        self,
        timeout_seconds: float = 20,
        retry_times: int = 2,
        delay_seconds: float = 0.8,
        metric_concurrency: int = 2,
        metric_delay_seconds: float = 0.8,
    ) -> None:
        self.retry_times = retry_times
        self.delay_seconds = delay_seconds
        self.metric_concurrency = max(1, metric_concurrency)
        self.metric_delay_seconds = max(0.0, metric_delay_seconds)
        self._metric_request_lock = Lock()
        self._metric_cache_lock = Lock()
        self._last_metric_request_at = 0.0
        self._metric_success_cache: dict[str, int] = {}
        self._metric_failure_cache: dict[str, datetime] = {}
        default_user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0 Safari/537.36"
        )
        headers = {
            "User-Agent": getenv("CRAWLER_USER_AGENT") or default_user_agent,
            "Accept": "application/json,text/html,*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        cookie = getenv(f"{self.platform_key.upper()}_COOKIE") or getenv("CRAWLER_COOKIE")
        if cookie:
            headers["Cookie"] = cookie
        authorization = getenv(f"{self.platform_key.upper()}_AUTHORIZATION")
        if authorization:
            headers["Authorization"] = authorization

        self.client = httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=True,
            headers=headers,
        )

    def close(self) -> None:
        self.client.close()

    def crawl(self, chart_date: date | None = None, top_n: int = 100) -> PlatformCrawlResult:
        current_chart_date = chart_date or date.today()
        result = PlatformCrawlResult(
            platform_key=self.platform_key,
            platform=self.platform_name,
            chart_date=current_chart_date,
        )
        metric_seen: set[str] = set()

        for chart in self.chart_configs:
            if chart.source_id.upper().startswith("TODO"):
                continue

            try:
                songs = self.fetch_chart(chart, current_chart_date, top_n)
                if not songs:
                    result.errors.append(f"{chart.name}: no songs returned")
                    self._sleep()
                    continue

                for song in songs:
                    if song.chart_size is None:
                        song.chart_size = len(songs)
                result.chart_songs.extend(songs)
                if chart.chart_type != "genre":
                    metric_songs = []
                    for song in songs:
                        metric_key = _metric_song_key(song)
                        if metric_key in metric_seen:
                            continue
                        metric_seen.add(metric_key)
                        metric_songs.append(song)
                    result.metrics.extend(self._fetch_metrics(metric_songs))
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"{chart.name}: {exc}")
            self._sleep()

        for chart in self.artist_chart_configs:
            try:
                artists = self.fetch_artist_chart(chart, current_chart_date, top_n)
                if not artists:
                    result.errors.append(f"{chart.name}: no artists returned")
                    self._sleep()
                    continue
                result.artist_charts.extend(artists)
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"{chart.name}: {exc}")
            self._sleep()

        return result

    def request_json(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        response = self._request(method, url, **kwargs)
        return response.json()

    def request_text(self, method: str, url: str, **kwargs: Any) -> str:
        response = self._request(method, url, **kwargs)
        return response.text

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(self.retry_times + 1):
            try:
                response = self.client.request(method, url, **kwargs)
                response.raise_for_status()
                return response
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt < self.retry_times:
                    time.sleep(0.6 * (attempt + 1))
        raise RuntimeError(f"request failed: {url}; {last_error}") from last_error

    def _sleep(self) -> None:
        if self.delay_seconds > 0:
            time.sleep(self.delay_seconds)

    def _fetch_metrics(self, songs: list[ChartSongItem]) -> list[SongMetricItem]:
        unique_songs = _unique_metric_songs(songs)
        if self.metric_concurrency <= 1 or len(unique_songs) <= 1:
            return [self._fetch_metric_safely(song) for song in unique_songs]

        max_workers = min(self.metric_concurrency, len(unique_songs))
        metrics: list[SongMetricItem] = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(self._fetch_metric_safely, song) for song in unique_songs]
            for future in as_completed(futures):
                metrics.append(future.result())
        return metrics

    def _fetch_metric_safely(self, song: ChartSongItem) -> SongMetricItem:
        cached = self._metric_from_cache(song)
        if cached is not None:
            return cached

        try:
            self._sleep_before_metric_request()
            metric = self.fetch_metric(song)
        except Exception as exc:  # noqa: BLE001
            metric = SongMetricItem(
                platform=self.platform_name,
                platform_song_id=song.platform_song_id,
                song_name=song.song_name,
                artist_name=song.artist_name,
                metric_time=datetime.now(),
                is_success=False,
                fail_reason=f"metric fetch failed: {exc}",
                metric_source=song.song_url,
            )
        self._store_metric_cache(song, metric)
        return metric

    def _sleep_before_metric_request(self) -> None:
        if self.metric_delay_seconds <= 0:
            return
        with self._metric_request_lock:
            now = time.monotonic()
            wait_seconds = self.metric_delay_seconds - (now - self._last_metric_request_at)
            if wait_seconds > 0:
                time.sleep(wait_seconds)
            self._last_metric_request_at = time.monotonic()

    def metric_cache_keys(self, song: ChartSongItem, metric_date: date | None = None) -> list[str]:
        current_date = metric_date or date.today()
        keys: list[str] = []
        if song.platform_song_id:
            keys.append(self._metric_cache_key("song_id", song.platform_song_id, current_date))
        if song.platform_song_mid:
            keys.append(self._metric_cache_key("song_mid", song.platform_song_mid, current_date))
        if song.song_hash:
            keys.append(self._metric_cache_key("song_hash", song.song_hash, current_date))
        return keys

    def _metric_cache_key(self, identifier_type: str, identifier: str, metric_date: date | None = None) -> str:
        current_date = metric_date or date.today()
        return f"{self.platform_key}|{identifier_type}|{identifier}|{current_date.isoformat()}"

    def cached_comment_count(self, identifier_type: str, identifier: str, metric_date: date | None = None) -> int | None:
        key = self._metric_cache_key(identifier_type, identifier, metric_date)
        with self._metric_cache_lock:
            return self._metric_success_cache.get(key)

    def has_recent_metric_failure(self, identifier_type: str, identifier: str, metric_date: date | None = None) -> bool:
        key = self._metric_cache_key(identifier_type, identifier, metric_date)
        cutoff = datetime.now() - timedelta(hours=6)
        with self._metric_cache_lock:
            failed_at = self._metric_failure_cache.get(key)
            if failed_at is None:
                return False
            if failed_at < cutoff:
                self._metric_failure_cache.pop(key, None)
                return False
            return True

    def store_comment_success(self, identifier_type: str, identifier: str, comment_count: int, metric_date: date | None = None) -> None:
        key = self._metric_cache_key(identifier_type, identifier, metric_date)
        with self._metric_cache_lock:
            self._metric_success_cache[key] = comment_count
            self._metric_failure_cache.pop(key, None)

    def store_comment_failure(self, identifier_type: str, identifier: str, metric_date: date | None = None) -> None:
        key = self._metric_cache_key(identifier_type, identifier, metric_date)
        with self._metric_cache_lock:
            self._metric_failure_cache[key] = datetime.now()

    def _metric_from_cache(self, song: ChartSongItem) -> SongMetricItem | None:
        metric_date = date.today()
        with self._metric_cache_lock:
            for key in self.metric_cache_keys(song, metric_date):
                comment_count = self._metric_success_cache.get(key)
                if comment_count is not None:
                    return SongMetricItem(
                        platform=self.platform_name,
                        platform_song_id=song.platform_song_id,
                        song_name=song.song_name,
                        artist_name=song.artist_name,
                        metric_time=datetime.now(),
                        is_success=True,
                        comment_count=comment_count,
                        metric_source="process_metric_success_cache",
                    )
        return None

    def _store_metric_cache(self, song: ChartSongItem, metric: SongMetricItem) -> None:
        metric_date = metric.metric_time.date()
        keys = self.metric_cache_keys(song, metric_date)
        if not keys:
            return
        with self._metric_cache_lock:
            if metric.comment_count is not None:
                for key in keys:
                    self._metric_success_cache[key] = metric.comment_count
                    self._metric_failure_cache.pop(key, None)
            else:
                for key in keys:
                    self._metric_failure_cache[key] = datetime.now()

    @abstractmethod
    def fetch_chart(
        self, chart: ChartConfig, chart_date: date, top_n: int
    ) -> list[ChartSongItem]:
        raise NotImplementedError

    @abstractmethod
    def fetch_metric(self, song: ChartSongItem) -> SongMetricItem:
        raise NotImplementedError

    def fetch_artist_chart(
        self, chart: ArtistChartConfig, chart_date: date, top_n: int
    ) -> list[ArtistChartItem]:
        return []


def _unique_metric_songs(songs: list[ChartSongItem]) -> list[ChartSongItem]:
    seen: set[str] = set()
    result: list[ChartSongItem] = []
    for song in songs:
        key = _metric_song_key(song)
        if key in seen:
            continue
        seen.add(key)
        result.append(song)
    return result


def _metric_song_key(song: ChartSongItem) -> str:
    if song.platform_song_id:
        return f"{song.platform}|id|{song.platform_song_id}"
    if song.platform_song_mid:
        return f"{song.platform}|mid|{song.platform_song_mid}"
    if song.song_hash:
        return f"{song.platform}|hash|{song.song_hash}"
    song_key = clean_song_name(song.song_name).strip().lower().replace(" ", "")
    artist_key = canonical_artist_key(song.artist_name)
    return f"{song.platform}|identity|{song_key}|{artist_key}"

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any
from urllib.parse import urlencode

from app.crawlers.base import BaseMusicCrawler
from app.crawlers.dtos import ArtistChartConfig, ArtistChartItem, ChartConfig, ChartSongItem, SongMetricItem
from app.crawlers.metric_sources import (
    MetricValues,
    build_metric_item,
    fetch_configured_metric_attempts,
    log_comment_attempt_failure,
    parse_extra_metadata,
    parse_json_or_jsonp,
)
from app.crawlers.utils import clean_artist_name, clean_song_name, detect_version_type, parse_count, split_artist_names, split_artist_title


class KugouMusicCrawler(BaseMusicCrawler):
    platform_key = "kugou"
    platform_name = "酷狗音乐"
    rank_api = "https://m.kugou.com/rank/info/"
    singer_rank_api = "https://m.kugou.com/singer/list/{page}"
    comment_api = "https://mcomment.kugou.com/index.php"
    chart_configs = (
        ChartConfig("kugou_top500", "TOP500", "hot", "8888"),
        ChartConfig("kugou_soaring", "飙升榜", "soaring", "6666"),
        ChartConfig("kugou_new", "新歌榜", "new", "31308"),
    )
    chart_configs = chart_configs + (
        ChartConfig("kugou_folk", "民谣榜", "genre", "51341", style_key="folk", style_name="民谣"),
        ChartConfig("kugou_electronic", "电音榜", "genre", "33160", style_key="electronic", style_name="电子音乐"),
        ChartConfig("kugou_rock", "摇滚榜", "genre", "59896", style_key="rock", style_name="摇滚"),
        ChartConfig("kugou_dj", "DJ热歌榜", "genre", "24971", style_key="electronic", style_name="电子音乐"),
        ChartConfig("kugou_guofeng", "国乐榜", "genre", "80025", style_key="guofeng", style_name="国风 / 古风"),
        ChartConfig("kugou_rnb", "R&B榜", "genre", "59895", style_key="rnb", style_name="R&B / Soul"),
        ChartConfig("kugou_rap", "说唱先锋榜", "genre", "44412", style_key="rap", style_name="说唱 / Hip-Hop"),
        ChartConfig("kugou_acg", "ACG新歌榜", "genre", "33162", style_key="acg", style_name="ACG / 二次元"),
        ChartConfig("kugou_ost", "影视金曲榜", "genre", "33163", style_key="ost", style_name="OST / 影视音乐"),
        ChartConfig("kugou_classical", "古典榜", "genre", "59899", style_key="classical", style_name="古典"),
    )
    artist_chart_configs = (
        ArtistChartConfig("kugou_artist_top", "歌手榜", "artist_hot", "singer_list"),
    )

    def fetch_chart(
        self, chart: ChartConfig, chart_date: date, top_n: int
    ) -> list[ChartSongItem]:
        items: list[ChartSongItem] = []
        page = 1
        max_pages = max(4, (top_n // 30) + 2)
        while len(items) < top_n and page <= max_pages:
            data = self.request_json(
                "GET",
                self.rank_api,
                params={"rankid": chart.source_id, "page": page, "json": "true"},
                headers={"Referer": "https://m.kugou.com/rank/list"},
            )
            raw_items = _extract_rank_items(data)
            if not raw_items:
                break
            for raw in raw_items:
                if len(items) >= top_n:
                    break
                song_hash = str(raw.get("hash") or raw.get("Hash") or "")
                if not song_hash:
                    continue
                raw_artist_name, raw_song_name = split_artist_title(
                    raw.get("filename") or raw.get("songname"),
                    raw.get("singername") or raw.get("singer_name"),
                )
                artist_names = split_artist_names(raw_artist_name)
                rank = len(items) + 1
                items.append(
                    ChartSongItem(
                        platform=self.platform_name,
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
                        album_name=raw.get("album_name") or raw.get("albumname"),
                        platform_song_id=song_hash,
                        album_id=str(raw.get("album_id") or raw.get("albumid") or raw.get("album_audio_id") or "") or None,
                        song_hash=song_hash,
                        extra_metadata=json.dumps(raw, ensure_ascii=False),
                        song_url=f"https://www.kugou.com/song/#hash={song_hash}",
                        cover_url=_normalize_kugou_cover(raw.get("imgurl") or raw.get("image")),
                        chart_date=chart_date,
                        collect_time=datetime.now(),
                        style_key=chart.style_key,
                        style_name=chart.style_name,
                        source_url=f"https://www.kugou.com/yy/rank/home/1-{chart.source_id}.html",
                    )
                )
            page += 1
            self._sleep()
        return items

    def fetch_metric(self, song: ChartSongItem) -> SongMetricItem:
        attempts = fetch_configured_metric_attempts(self, song)
        attempts.append(self._fetch_public_comment_metric(song))
        return build_metric_item(
            self.platform_name,
            song,
            attempts,
            "metric fields not found from Kugou metric sources",
        )

    def fetch_artist_chart(
        self, chart: ArtistChartConfig, chart_date: date, top_n: int
    ) -> list[ArtistChartItem]:
        items: list[ArtistChartItem] = []
        page = 1
        max_pages = max(4, (top_n // 30) + 2)
        while len(items) < top_n and page <= max_pages:
            data = self.request_json(
                "GET",
                self.singer_rank_api.format(page=page),
                params={"json": "true"},
                headers={"Referer": "https://m.kugou.com/singer/list"},
            )
            raw_artists = _extract_artist_items(data)
            if not raw_artists:
                break
            for raw in raw_artists:
                if len(items) >= top_n:
                    break
                artist_id = str(raw.get("singerid") or raw.get("singer_id") or raw.get("id") or "")
                artist_name = str(raw.get("singername") or raw.get("singer_name") or raw.get("name") or "")
                if not artist_id or not artist_name:
                    continue
                rank = len(items) + 1
                items.append(
                    ArtistChartItem(
                        platform=self.platform_name,
                        chart_name=chart.name,
                        chart_type=chart.chart_type,
                        rank=rank,
                        artist_name=artist_name,
                        platform_artist_id=artist_id,
                        artist_avatar_url=_normalize_kugou_cover(raw.get("imgurl") or raw.get("image") or raw.get("pic")),
                        artist_url=f"https://www.kugou.com/singer/{artist_id}.html",
                        extra_metadata=json.dumps(raw, ensure_ascii=False),
                        chart_date=chart_date,
                        collect_time=datetime.now(),
                        source_url="https://m.kugou.com/singer/list",
                    )
                )
            page += 1
            self._sleep()
        return items

    def _fetch_public_comment_metric(self, song: ChartSongItem) -> MetricValues:
        for identifier_type, identifier in _kugou_comment_identifiers(song):
            values = self._fetch_public_comment_by_identifier(song, identifier_type, identifier)
            if values.is_success:
                return values
        return MetricValues(
            source_name="kugou_public_comment",
            source_url=self.comment_api,
            fail_reason="comment_count not found from Kugou comment sources",
        )

    def _fetch_public_comment_by_identifier(
        self,
        song: ChartSongItem,
        identifier_type: str,
        identifier: str,
    ) -> MetricValues:
        params = {
            "r": "commentsv2/getCommentWithLike",
            "code": "fc4be23b4e972707f36b8a828a93ba8a",
            "extdata": identifier,
            "p": "1",
            "pagesize": "20",
        }
        source_name = _kugou_source_name(identifier_type)
        source_url = f"{self.comment_api}?{urlencode(params)}"
        cached_comment_count = self.cached_comment_count(identifier_type, identifier)
        if cached_comment_count is not None:
            return MetricValues(
                source_name=f"{source_name}_cache",
                source_url=source_url,
                comment_count=cached_comment_count,
            )
        if self.has_recent_metric_failure(identifier_type, identifier):
            return MetricValues(
                source_name=f"{source_name}_failure_cache",
                source_url=source_url,
                fail_reason="skipped by recent failure cache",
            )
        status_code = None
        content_type = None
        snippet = None
        comment_count = None
        fail_reason = None
        try:
            response = self.client.get(
                self.comment_api,
                params=params,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
                    "Referer": song.song_url or "https://www.kugou.com/",
                    "Accept": "application/json,text/javascript,*/*;q=0.1",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                },
            )
            status_code = response.status_code
            content_type = response.headers.get("content-type")
            snippet = response.text
            response.raise_for_status()
            data = parse_json_or_jsonp(response.text)
            if isinstance(data, dict):
                comment_count = _extract_kugou_comment_count(data)
            else:
                fail_reason = "Kugou comment response is not JSON/JSONP object"
            if comment_count is None:
                fail_reason = fail_reason or "comment_count not found"
        except Exception as exc:  # noqa: BLE001
            fail_reason = f"Kugou comment request failed: {exc}"

        if comment_count is None:
            self.store_comment_failure(identifier_type, identifier)
            log_comment_attempt_failure(
                platform=self.platform_name,
                song=song,
                source_name=source_name,
                source_url=source_url,
                identifier_type=identifier_type,
                identifier=identifier,
                status_code=status_code,
                response_content_type=content_type,
                response_snippet=snippet,
                fail_reason=fail_reason or "comment_count not found",
            )
        else:
            self.store_comment_success(identifier_type, identifier, comment_count)

        return MetricValues(
            source_name=source_name,
            source_url=source_url,
            comment_count=comment_count,
            fail_reason=fail_reason,
        )


def _extract_rank_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    payload = data.get("data") if isinstance(data.get("data"), dict) else data
    raw_items = (
        payload.get("songs")
        or payload.get("list")
        or payload.get("info")
        or data.get("info")
        or []
    )
    if isinstance(raw_items, dict):
        raw_items = raw_items.get("list") or raw_items.get("info") or []
    return [item for item in raw_items if isinstance(item, dict)]


def _extract_artist_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    payload = data.get("data") if isinstance(data.get("data"), dict) else data
    raw_items = (
        payload.get("singers")
        or payload.get("singer")
        or payload.get("list")
        or payload.get("info")
        or data.get("info")
        or []
    )
    if isinstance(raw_items, dict):
        nested = raw_items.get("list") or raw_items.get("info") or []
        if isinstance(nested, dict):
            nested = nested.get("info") or nested.get("list") or []
        raw_items = nested
    expanded: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        nested_singers = item.get("singer")
        if isinstance(nested_singers, list):
            expanded.extend(nested for nested in nested_singers if isinstance(nested, dict))
        else:
            expanded.append(item)
    if expanded:
        return expanded
    return [item for item in raw_items if isinstance(item, dict)]


def _normalize_kugou_cover(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    return text.replace("{size}", "400")


def _kugou_comment_identifiers(song: ChartSongItem) -> list[tuple[str, str]]:
    extra = parse_extra_metadata(song)
    candidates = [
        ("hash", song.song_hash),
        ("song_hash", song.platform_song_id),
        ("hash", extra.get("hash") or extra.get("Hash") or extra.get("FileHash") or extra.get("file_hash")),
        ("album_audio_id", extra.get("album_audio_id")),
        ("audio_id", extra.get("audio_id")),
        ("mixsongid", extra.get("mixsongid")),
    ]
    seen: set[str] = set()
    items: list[tuple[str, str]] = []
    for identifier_type, value in candidates:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        items.append((identifier_type, text))
    return items


def _kugou_source_name(identifier_type: str) -> str:
    names = {
        "hash": "kugou_comment_by_hash",
        "song_hash": "kugou_comment_by_song_hash",
        "album_audio_id": "kugou_comment_by_album_audio_id",
        "audio_id": "kugou_comment_by_audio_id",
        "mixsongid": "kugou_comment_by_mixsongid",
    }
    return names.get(identifier_type, "kugou_configured_comment_source")


def _extract_kugou_comment_count(data: dict[str, Any]) -> int | None:
    paths = [
        ("data", "count"),
        ("data", "total"),
        ("data", "total_count"),
        ("data", "comment_count"),
        ("data", "commentCount"),
        ("data", "comments", "total"),
        ("data", "comments", "count"),
        ("data", "page", "total"),
        ("data", "page", "count"),
        ("data", "paging", "total"),
        ("data", "paging", "count"),
        ("data", "info", "total"),
        ("data", "info", "count"),
        ("data", "data", "count"),
        ("data", "data", "total"),
        ("data", "data", "total_count"),
        ("data", "data", "comment_count"),
        ("data", "data", "commentCount"),
        ("data", "data", "comments", "total"),
        ("data", "data", "comments", "count"),
        ("data", "data", "page", "total"),
        ("data", "data", "page", "count"),
        ("data", "data", "paging", "total"),
        ("data", "data", "paging", "count"),
        ("data", "data", "info", "total"),
        ("data", "data", "info", "count"),
        ("count",),
        ("total",),
        ("total_count",),
        ("comment_count",),
        ("commentCount",),
    ]
    for path in paths:
        value: Any = data
        for key in path:
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(key)
        parsed = parse_count(value)
        if parsed is not None:
            return parsed
    return None

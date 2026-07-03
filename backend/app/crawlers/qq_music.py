from __future__ import annotations

import json
from datetime import date, datetime
from os import getenv
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
from app.crawlers.utils import clean_artist_name, clean_song_name, detect_version_type, extract_artist_names, join_artists, parse_count


class QQMusicCrawler(BaseMusicCrawler):
    platform_key = "qq"
    platform_name = "QQ音乐"
    toplist_api = "https://u.y.qq.com/cgi-bin/musicu.fcg"
    comment_api = "https://c.y.qq.com/base/fcgi-bin/fcg_global_comment_h5.fcg"
    chart_configs = (
        ChartConfig("qq_hot", "热歌榜", "hot", "26"),
        ChartConfig("qq_new", "新歌榜", "new", "27"),
        ChartConfig("qq_soaring", "飙升榜", "soaring", "62"),
        ChartConfig("qq_popular_index", "流行指数榜", "popular_index", "4"),
    )
    chart_configs = chart_configs + (
        ChartConfig("qq_rap", "说唱榜", "genre", "58", style_key="rap", style_name="说唱 / Hip-Hop"),
        ChartConfig("qq_electronic", "电音榜", "genre", "57", style_key="electronic", style_name="电子音乐"),
        ChartConfig("qq_game", "游戏音乐榜", "genre", "73", style_key="acg", style_name="ACG / 二次元"),
        ChartConfig("qq_anime", "动漫音乐榜", "genre", "72", style_key="acg", style_name="ACG / 二次元"),
        ChartConfig("qq_ost", "影视金曲榜", "genre", "29", style_key="ost", style_name="OST / 影视音乐"),
        ChartConfig("qq_guofeng", "国风热歌榜", "genre", "65", style_key="guofeng", style_name="国风 / 古风"),
        ChartConfig("qq_douyin", "抖音热歌榜", "genre", "60", style_key="short_video", style_name="短视频热歌"),
        ChartConfig("qq_dj", "DJ舞曲榜", "genre", "63", style_key="electronic", style_name="电子音乐"),
    )
    artist_chart_configs = (
        ArtistChartConfig("qq_artist_top", "歌手榜", "artist_hot", "singer_list"),
    )

    def fetch_chart(
        self, chart: ChartConfig, chart_date: date, top_n: int
    ) -> list[ChartSongItem]:
        payload = {
            "comm": {"ct": 24, "cv": 0},
            "req_1": {
                "module": "musicToplist.ToplistInfoServer",
                "method": "GetDetail",
                "param": {"topId": int(chart.source_id), "offset": 0, "num": top_n, "period": ""},
            },
        }
        data = self.request_json(
            "GET",
            self.toplist_api,
            params={
                "format": "json",
                "data": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            },
            headers={"Referer": "https://y.qq.com/"},
        )
        detail = ((data.get("req_1") or {}).get("data") or {})
        raw_songs = _extract_song_list(detail)
        source_url = f"https://y.qq.com/n/ryqq/toplist/{chart.source_id}"

        items: list[ChartSongItem] = []
        for rank, raw in enumerate(raw_songs[:top_n], start=1):
            song_id = str(raw.get("id") or "")
            song_mid = str(raw.get("mid") or raw.get("songmid") or "")
            if not song_id:
                continue
            album = raw.get("album") or {}
            album_mid = album.get("mid") or album.get("pmid")
            singer_mid = _first_singer_mid(raw.get("singer") or [])
            raw_song_name = str(raw.get("title") or raw.get("name") or raw.get("songname") or "")
            raw_artist_name = join_artists(raw.get("singer") or [])
            artist_names = extract_artist_names(raw.get("singer") or [])
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
                    album_name=str(album.get("name") or "") or None,
                    platform_song_id=song_id,
                    platform_song_mid=song_mid or None,
                    album_id=str(album.get("id") or "") or None,
                    album_mid=str(album_mid or "") or None,
                    extra_metadata=json.dumps(raw, ensure_ascii=False),
                    song_url=f"https://y.qq.com/n/ryqq/songDetail/{song_mid or song_id}",
                    cover_url=_qq_cover_url(album_mid),
                    artist_avatar_url=_qq_singer_avatar_url(singer_mid),
                    chart_date=chart_date,
                    collect_time=datetime.now(),
                    source_url=source_url,
                    style_key=chart.style_key,
                    style_name=chart.style_name,
                )
            )
        return items

    def fetch_metric(self, song: ChartSongItem) -> SongMetricItem:
        attempts = fetch_configured_metric_attempts(self, song)
        attempts.append(self._fetch_public_comment_metric(song))
        return build_metric_item(
            self.platform_name,
            song,
            attempts,
            "metric fields not found from QQ Music metric sources",
        )

    def fetch_artist_chart(
        self, chart: ArtistChartConfig, chart_date: date, top_n: int
    ) -> list[ArtistChartItem]:
        payload = {
            "comm": {"ct": 24, "cv": 0},
            "req_1": {
                "module": "Music.SingerListServer",
                "method": "get_singer_list",
                "param": {
                    "area": -100,
                    "sex": -100,
                    "genre": -100,
                    "index": -100,
                    "sin": 0,
                    "cur_page": 1,
                },
            },
        }
        data = self.request_json(
            "GET",
            self.toplist_api,
            params={
                "format": "json",
                "data": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            },
            headers={"Referer": "https://y.qq.com/"},
        )
        raw_artists = _extract_singer_list((data.get("req_1") or {}).get("data") or data)
        source_url = "https://y.qq.com/n/ryqq/singer_list"
        items: list[ArtistChartItem] = []
        for rank, raw in enumerate(raw_artists[:top_n], start=1):
            artist_id = str(raw.get("singer_id") or raw.get("id") or raw.get("singerid") or "")
            artist_mid = str(raw.get("singer_mid") or raw.get("mid") or raw.get("singermid") or "")
            artist_name = str(raw.get("singer_name") or raw.get("name") or raw.get("singername") or "")
            platform_artist_id = artist_mid or artist_id
            if not platform_artist_id or not artist_name:
                continue
            items.append(
                ArtistChartItem(
                    platform=self.platform_name,
                    chart_name=chart.name,
                    chart_type=chart.chart_type,
                    rank=rank,
                    artist_name=artist_name,
                    platform_artist_id=platform_artist_id,
                    artist_avatar_url=_qq_singer_avatar_url(artist_mid),
                    artist_url=f"https://y.qq.com/n/ryqq/singer/{platform_artist_id}",
                    extra_metadata=json.dumps(raw, ensure_ascii=False),
                    chart_date=chart_date,
                    collect_time=datetime.now(),
                    source_url=source_url,
                )
            )
        return items

    def _fetch_public_comment_metric(self, song: ChartSongItem) -> MetricValues:
        attempts: list[MetricValues] = []
        for identifier_type, identifier in _qq_comment_identifiers(song):
            for param_name in _qq_param_names(identifier_type):
                attempts.append(self._fetch_public_comment_by_identifier(song, identifier_type, identifier, param_name))
                if attempts[-1].is_success:
                    return attempts[-1]
        return MetricValues(
            source_name="qq_public_comment",
            source_url=self.comment_api,
            fail_reason="comment_count not found from QQ comment sources",
        )

    def _fetch_public_comment_by_identifier(
        self,
        song: ChartSongItem,
        identifier_type: str,
        identifier: str,
        param_name: str,
    ) -> MetricValues:
        params = {
            "g_tk": _qq_g_tk(),
            "loginUin": "0",
            "hostUin": "0",
            "format": "json",
            "inCharset": "utf8",
            "outCharset": "utf-8",
            "notice": "0",
            "platform": "yqq.json",
            "needNewCode": "0",
            "cid": "205360772",
            "reqtype": "2",
            "biztype": "1",
            param_name: identifier,
            "cmd": "8",
            "pagenum": "0",
            "pagesize": "1",
            "lasthotcommentid": "",
            "domain": "qq.com",
        }
        source_name = _qq_source_name(identifier_type, param_name)
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
        headers = {
            "Referer": "https://y.qq.com/",
            "Origin": "https://y.qq.com",
            "Accept": "application/json,text/javascript,*/*;q=0.1",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        cookie = getenv("QQ_COOKIE")
        if cookie:
            headers["Cookie"] = cookie
        fail_reason = None
        status_code = None
        content_type = None
        snippet = None
        comment_count = None
        try:
            response = self.client.get(self.comment_api, params=params, headers=headers)
            status_code = response.status_code
            content_type = response.headers.get("content-type")
            snippet = response.text
            response.raise_for_status()
            data = parse_json_or_jsonp(response.text)
            if isinstance(data, dict):
                comment_count = _extract_qq_comment_count(data)
            else:
                fail_reason = "QQ comment response is not JSON/JSONP object"
            if comment_count is None:
                fail_reason = fail_reason or "comment_count not found"
        except Exception as exc:  # noqa: BLE001
            fail_reason = f"QQ comment request failed: {exc}"

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


def _extract_song_list(detail: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(detail.get("songInfoList"), list):
        return [item for item in detail["songInfoList"] if isinstance(item, dict)]

    songs: list[dict[str, Any]] = []
    for raw in detail.get("song") or detail.get("songlist") or []:
        if not isinstance(raw, dict):
            continue
        song_info = raw.get("songInfo") or raw.get("data") or raw
        if isinstance(song_info, dict):
            songs.append(song_info)
    return songs


def _extract_singer_list(detail: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items = (
        detail.get("singerlist")
        or detail.get("singerList")
        or detail.get("list")
        or detail.get("singers")
        or []
    )
    return [item for item in raw_items if isinstance(item, dict)]


def _qq_cover_url(album_mid: Any) -> str | None:
    if not album_mid:
        return None
    return f"https://y.qq.com/music/photo_new/T002R300x300M000{album_mid}.jpg"


def _first_singer_mid(singers: list[dict[str, Any]]) -> str | None:
    if not singers:
        return None
    value = singers[0].get("mid") or singers[0].get("singer_mid")
    return str(value) if value else None


def _qq_singer_avatar_url(singer_mid: str | None) -> str | None:
    if not singer_mid:
        return None
    return f"https://y.qq.com/music/photo_new/T001R300x300M000{singer_mid}.jpg"


def _qq_comment_identifiers(song: ChartSongItem) -> list[tuple[str, str]]:
    extra = parse_extra_metadata(song)
    candidates = [
        ("song_id", song.platform_song_id),
        ("song_mid", song.platform_song_mid),
        ("extra_id", extra.get("id") or extra.get("songid")),
        ("extra_mid", extra.get("mid") or extra.get("songmid")),
    ]
    seen: set[tuple[str, str]] = set()
    items: list[tuple[str, str]] = []
    for identifier_type, value in candidates:
        text = str(value or "").strip()
        if not text:
            continue
        key = (identifier_type, text)
        if key in seen:
            continue
        seen.add(key)
        items.append(key)
    return items


def _qq_param_names(identifier_type: str) -> tuple[str, ...]:
    if "mid" in identifier_type:
        return ("songmid", "mid")
    return ("topid", "id")


def _qq_source_name(identifier_type: str, param_name: str) -> str:
    if identifier_type == "song_id":
        return f"qq_comment_by_song_id_{param_name}"
    if identifier_type == "song_mid":
        return f"qq_comment_by_song_mid_{param_name}"
    if identifier_type == "extra_id":
        return f"qq_comment_by_extra_id_{param_name}"
    if identifier_type == "extra_mid":
        return f"qq_comment_by_extra_mid_{param_name}"
    return "qq_configured_comment_source"


def _qq_g_tk() -> str:
    configured = getenv("QQ_GTK", "").strip()
    if configured:
        return configured
    cookie = getenv("QQ_COOKIE", "")
    skey_match = re_search_cookie(cookie, ("p_skey", "skey"))
    if skey_match:
        return str(calc_qq_g_tk(skey_match))
    return "5381"


def re_search_cookie(cookie: str, names: tuple[str, ...]) -> str | None:
    for name in names:
        for part in cookie.split(";"):
            key, _, value = part.strip().partition("=")
            if key == name and value:
                return value
    return None


def calc_qq_g_tk(skey: str) -> int:
    hash_value = 5381
    for char in skey:
        hash_value += (hash_value << 5) + ord(char)
    return hash_value & 0x7FFFFFFF


def _extract_qq_comment_count(data: dict[str, Any]) -> int | None:
    paths = [
        ("comment", "commenttotal"),
        ("comment", "comment_total"),
        ("comment", "total"),
        ("comment", "commentCount"),
        ("comment", "comment_count"),
        ("data", "commenttotal"),
        ("data", "comment_total"),
        ("data", "total"),
        ("data", "commentCount"),
        ("data", "comment_count"),
        ("req_0", "data", "commenttotal"),
        ("req_0", "data", "total"),
        ("req_0", "data", "commentCount"),
        ("req_0", "data", "comment_count"),
        ("req_1", "data", "commenttotal"),
        ("req_1", "data", "total"),
        ("req_1", "data", "commentCount"),
        ("req_1", "data", "comment_count"),
        ("commenttotal",),
        ("comment_total",),
        ("total",),
        ("commentCount",),
        ("comment_count",),
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

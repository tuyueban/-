from __future__ import annotations

from datetime import date
from typing import Any

from app.crawlers.base import BaseMusicCrawler
from app.crawlers.dtos import ArtistChartConfig, ArtistChartItem, ChartConfig, ChartSongItem, SongMetricItem
from app.crawlers.item_builders import build_artist_chart_item, build_chart_song_item
from app.crawlers.metric_sources import (
    MetricValues,
    build_metric_item,
    fetch_configured_metric_attempts,
)
from app.crawlers.utils import extract_artist_names, join_artists, parse_count


class NeteaseMusicCrawler(BaseMusicCrawler):
    platform_key = "netease"
    platform_name = "网易云音乐"
    playlist_api = "https://music.163.com/api/playlist/detail"
    comment_api = "https://music.163.com/api/v1/resource/comments/R_SO_4_{song_id}"
    artist_rank_api = "https://music.163.com/api/artist/top"
    chart_configs = (
        ChartConfig("netease_hot", "热歌榜", "hot", "3778678"),
        ChartConfig("netease_new", "新歌榜", "new", "3779629"),
        ChartConfig("netease_soaring", "飙升榜", "soaring", "19723756"),
        ChartConfig("netease_original", "原创榜", "original", "2884035"),
        ChartConfig("netease_rap","网易云说唱榜","genre","TODO_CONFIRM_ID",style_key="rap",style_name="说唱",
        ),
    )
    chart_configs = tuple(
        chart for chart in chart_configs if chart.source_id != "TODO_CONFIRM_ID"
    ) + (
        ChartConfig("netease_classical", "网易云古典榜", "genre", "71384707", style_key="classical", style_name="古典"),
        ChartConfig("netease_electronic", "网易云电音榜", "genre", "1978921795", style_key="electronic", style_name="电子音乐"),
        ChartConfig("netease_rap", "网易云中文说唱榜", "genre", "991319590", style_key="rap", style_name="说唱 / Hip-Hop"),
        ChartConfig("netease_acg", "网易云ACG榜", "genre", "71385702", style_key="acg", style_name="ACG / 二次元"),
        ChartConfig("netease_rock", "网易云摇滚榜", "genre", "5059633707", style_key="rock", style_name="摇滚"),
        ChartConfig("netease_guofeng", "网易云国风榜", "genre", "5059642708", style_key="guofeng", style_name="国风 / 古风"),
        ChartConfig("netease_folk", "网易云民谣榜", "genre", "5059661515", style_key="folk", style_name="民谣"),
        ChartConfig("netease_rnb", "网易云欧美R&B榜", "genre", "12225155968", style_key="rnb", style_name="R&B / Soul"),
    )
    artist_chart_configs = (
        ArtistChartConfig("netease_artist_top", "歌手榜", "artist_hot", "top"),
    )

    def search_song(self, keyword: str) -> ChartSongItem | None:
        data = self.request_json(
            "GET",
            "https://music.163.com/api/search/get/web",
            params={"s": keyword, "type": 1, "offset": 0, "limit": 20},
            headers={"Referer": "https://music.163.com/"},
        )
        songs = ((data.get("result") or {}).get("songs") or [])
        candidates: list[ChartSongItem] = []
        for raw in songs:
            song_id = str(raw.get("id") or "")
            if not song_id:
                continue
            artists = raw.get("artists") or raw.get("ar") or []
            album = raw.get("album") or raw.get("al") or {}
            candidates.append(
                build_chart_song_item(
                    platform=self.platform_name,
                    chart=ChartConfig("netease_search", "搜索结果", "explore", "search"),
                    rank=1,
                    artist_names=extract_artist_names(artists),
                    raw_song_name=str(raw.get("name") or ""),
                    raw_artist_name=join_artists(artists),
                    platform_song_id=song_id,
                    chart_date=date.today(),
                    raw_metadata=raw,
                    album_name=_album_name(album),
                    album_id=str(album.get("id") or "") or None,
                    cover_url=_album_cover(album),
                    song_url=f"https://music.163.com/song?id={song_id}",
                )
            )
        return _best_search_candidate(keyword, candidates)

    def fetch_chart(
        self, chart: ChartConfig, chart_date: date, top_n: int
    ) -> list[ChartSongItem]:
        data = self.request_json(
            "GET",
            self.playlist_api,
            params={"id": chart.source_id, "limit": top_n},
            headers={"Referer": "https://music.163.com/"},
        )
        playlist = data.get("playlist") or data.get("result") or {}
        tracks = playlist.get("tracks") or []
        source_url = f"https://music.163.com/discover/toplist?id={chart.source_id}"

        items: list[ChartSongItem] = []
        for rank, raw in enumerate(tracks[:top_n], start=1):
            song_id = str(raw.get("id") or "")
            if not song_id:
                continue
            artists = raw.get("ar") or raw.get("artists") or []
            album = raw.get("al") or raw.get("album") or {}
            raw_song_name = str(raw.get("name") or "")
            raw_artist_name = join_artists(artists)
            artist_names = extract_artist_names(artists)
            items.append(
                build_chart_song_item(
                    platform=self.platform_name,
                    chart=chart,
                    rank=rank,
                    artist_names=artist_names,
                    raw_song_name=raw_song_name,
                    raw_artist_name=raw_artist_name,
                    platform_song_id=song_id,
                    chart_date=chart_date,
                    raw_metadata=raw,
                    source_url=source_url,
                    album_name=_album_name(album),
                    album_id=str(album.get("id") or "") or None,
                    song_url=f"https://music.163.com/song?id={song_id}",
                    cover_url=_album_cover(album),
                    artist_avatar_url=_artist_avatar(artists),
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
            "metric fields not found from NetEase metric sources",
        )

    def fetch_artist_chart(
        self, chart: ArtistChartConfig, chart_date: date, top_n: int
    ) -> list[ArtistChartItem]:
        data = self.request_json(
            "GET",
            self.artist_rank_api,
            params={"offset": 0, "total": "true", "limit": top_n},
            headers={"Referer": "https://music.163.com/discover/artist"},
        )
        raw_artists = _extract_artist_items(data)
        source_url = "https://music.163.com/discover/artist"
        items: list[ArtistChartItem] = []
        for rank, raw in enumerate(raw_artists[:top_n], start=1):
            artist_id = str(raw.get("id") or "")
            artist_name = str(raw.get("name") or raw.get("artistName") or "")
            if not artist_id or not artist_name:
                continue
            items.append(
                build_artist_chart_item(
                    platform=self.platform_name,
                    chart=chart,
                    rank=rank,
                    artist_name=artist_name,
                    platform_artist_id=artist_id,
                    chart_date=chart_date,
                    raw_metadata=raw,
                    source_url=source_url,
                    artist_avatar_url=_artist_raw_avatar(raw),
                    artist_url=f"https://music.163.com/artist?id={artist_id}",
                )
            )
        return items

    def _fetch_public_comment_metric(self, song: ChartSongItem) -> MetricValues:
        metric_source = self.comment_api.format(song_id=song.platform_song_id)
        data = self.request_json(
            "GET",
            metric_source,
            params={"limit": 1, "offset": 0},
            headers={"Referer": song.song_url or "https://music.163.com/"},
        )
        comment_count = parse_count(data.get("total") or data.get("commentCount"))
        fail_reason = None
        if comment_count is None:
            fail_reason = "comment_count not found"

        return MetricValues(
            source_name="netease_public_comment",
            source_url=metric_source,
            comment_count=comment_count,
            fail_reason=fail_reason,
        )


def _album_name(album: dict[str, Any]) -> str | None:
    value = album.get("name")
    return str(value) if value else None


def _album_cover(album: dict[str, Any]) -> str | None:
    value = album.get("picUrl") or album.get("picurl")
    return str(value) if value else None


def _artist_avatar(artists: list[dict[str, Any]]) -> str | None:
    if not artists:
        return None
    value = artists[0].get("img1v1Url") or artists[0].get("picUrl")
    return str(value) if value else None


def _extract_artist_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items = (
        data.get("artists")
        or data.get("list")
        or ((data.get("data") or {}).get("artists") if isinstance(data.get("data"), dict) else None)
        or ((data.get("result") or {}).get("artists") if isinstance(data.get("result"), dict) else None)
        or []
    )
    return [item for item in raw_items if isinstance(item, dict)]


def _artist_raw_avatar(raw: dict[str, Any]) -> str | None:
    value = raw.get("img1v1Url") or raw.get("picUrl") or raw.get("avatar") or raw.get("cover")
    return str(value) if value else None


def _best_search_candidate(keyword: str, candidates: list[ChartSongItem]) -> ChartSongItem | None:
    if not candidates:
        return None
    query = _normalize_search_text(keyword)
    return max(candidates, key=lambda item: _search_score(query, item))


def _search_score(query: str, item: ChartSongItem) -> int:
    song = _normalize_search_text(item.song_name)
    artist = _normalize_search_text(item.artist_name)
    score = 0
    if song and song in query:
        score += 100
    if artist and artist in query:
        score += 100
    if song and query in song:
        score += 50
    return score


def _normalize_search_text(value: str | None) -> str:
    return "".join(str(value or "").lower().split())

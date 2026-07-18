from __future__ import annotations

import asyncio
import json
import math
import re
import time
import traceback
from dataclasses import dataclass
from datetime import date, datetime
from html import unescape
from typing import Any, Callable
from urllib.parse import quote_plus
from uuid import uuid4

import httpx

from app.core.config import settings
from app.crawlers.dtos import ChartSongItem
from app.crawlers.kugou import KugouMusicCrawler
from app.crawlers.netease import NeteaseMusicCrawler
from app.crawlers.qq_music import QQMusicCrawler
from app.crawlers.utils import extract_artist_names, join_artists, split_artist_names, split_artist_title
from app.services.song_entity_service import identify_song_entity


AI_FAILURE_MESSAGE = "AI分析生成失败，请稍后重试。"
TTL_SECONDS = 600
MAX_CACHE_SIZE = 1000
PLATFORM_ORDER = ("netease", "qq", "kugou")

_EXPLORE_CACHE: dict[str, tuple[float, float, Any]] = {}
_SESSION_KEYS: dict[str, set[str]] = {}
_SEARCH_ENTITIES: dict[str, dict[str, Any]] = {}


@dataclass(frozen=True)
class PlatformSpec:
    code: str
    name: str
    crawler_factory: Callable[[], Any]
    searcher: Callable[[Any, str], ChartSongItem | None]


def _crawler(factory: type) -> Any:
    return factory(
        timeout_seconds=settings.crawler_timeout_seconds,
        retry_times=settings.crawler_retry_times,
        delay_seconds=0.1,
        metric_delay_seconds=0.1,
    )


PLATFORMS = (
    PlatformSpec("netease", "网易云音乐", lambda: _crawler(NeteaseMusicCrawler), lambda crawler, keyword: _search_netease(crawler, keyword)),
    PlatformSpec("qq", "QQ音乐", lambda: _crawler(QQMusicCrawler), lambda crawler, keyword: _search_qq(crawler, keyword)),
    PlatformSpec("kugou", "酷狗音乐", lambda: _crawler(KugouMusicCrawler), lambda crawler, keyword: _search_kugou(crawler, keyword)),
)


class SongExplorerService:
    async def search_song(self, keyword: str) -> dict[str, Any]:
        text = keyword.strip()
        if not text:
            return {"session_id": str(uuid4()), "canonical_song": {}, "platforms": [], "heat_score": 0}

        entity = identify_song_entity(text, _call_ai)
        search_keyword = " ".join(
            item for item in [
                str(entity.get("song_name") or text).strip(),
                str(entity.get("artist_name") or "").strip(),
            ] if item
        )
        _SEARCH_ENTITIES[search_keyword] = entity
        print(f"用户输入：{text}")
        print(f"AI识别：{entity.get('artist_name') or ''} - {entity.get('song_name') or text}")
        print(f"最终搜索：{search_keyword}")

        session_id = str(uuid4())
        platform_rows = await asyncio.gather(*[
            asyncio.to_thread(_platform_snapshot, spec, search_keyword)
            for spec in PLATFORMS
        ])
        _SEARCH_ENTITIES.pop(search_keyword, None)
        result = _explore_result(session_id, platform_rows)
        result["success"] = True
        result["keyword"] = text
        result["search_keyword"] = search_keyword
        result["entity"] = entity
        song_hash = _song_hash(
            result["canonical_song"].get("song_name"),
            result["canonical_song"].get("artist_name"),
        )
        cache_key = f"explore:{session_id}:{song_hash}"
        _cache_set(cache_key, result)
        _SESSION_KEYS[session_id] = {cache_key}
        return result

    def generate_ai_analysis(self, song_name: str, artist_name: str) -> dict[str, str]:
        song_hash = _song_hash(song_name, artist_name)
        cache_key = f"explore:ai:{song_hash}"
        cached = _cache_get(cache_key)
        if cached:
            return {"analysis": str(cached)}

        try:
            evidence = _cached_song_evidence(song_name, artist_name)
            search_results = _web_search_many(song_name, artist_name)
            analysis = _call_ai(_build_ai_prompt(song_name, artist_name), {
                "song_name": song_name,
                "artist_name": artist_name,
                "platform_data": evidence,
                "web_search_results": search_results,
            })
            content = _clean_ai_text(analysis)
            if not content:
                raise RuntimeError("empty AI content")
        except Exception:
            return {"analysis": AI_FAILURE_MESSAGE}

        _cache_set(cache_key, content)
        return {"analysis": content}

    def cleanup_session_cache(self, session_id: str) -> dict[str, Any]:
        keys = _SESSION_KEYS.pop(session_id, set())
        for key in keys:
            _EXPLORE_CACHE.pop(key, None)
        return {"deleted": len(keys)}


def _platform_snapshot(spec: PlatformSpec, keyword: str) -> dict[str, Any]:
    crawler = spec.crawler_factory()
    print(f"开始搜索 {spec.name}")
    print(f"keyword={keyword}")
    print(type(crawler))

    try:
        print("calling searcher...")
        song = spec.searcher(crawler, keyword)

        if song is None:
            print(f"{spec.name} returned None")
            return {
                "platform": spec.code,
                "platform_name": spec.name,
                "found": False,
                "charts": [],
            }

        print(f"found song={song.song_name} artist={song.artist_name}")
        print(f"{spec.name}结果：{song.artist_name} - {song.song_name}")

        comment_count = None
        collect_count = None
        metric_error = None
        try:
            metric = crawler.fetch_metric(song)
            comment_count = metric.comment_count
            collect_count = metric.collect_count
        except Exception as e:
            metric_error = str(e)
            print(f"{spec.name} comment failed")
            print(traceback.format_exc())

        charts = []
        chart_error = None
        try:
            charts = _chart_coverage(crawler, song)
        except Exception as e:
            chart_error = str(e)
            print(f"{spec.name} chart failed")
            print(traceback.format_exc())

        row = {
            "platform": spec.code,
            "platform_name": spec.name,
            "found": True,
            "song_name": song.song_name,
            "artist_name": song.artist_name,
            "album_name": song.album_name,
            "release_time": _metadata_value(song, "release_time"),
            "cover_url": song.cover_url,
            "song_url": song.song_url,
            "comment_count": comment_count,
            "collect_count": collect_count,
            "in_chart": bool(charts),
            "chart_name": charts[0]["chart_name"] if charts else None,
            "rank": charts[0]["rank"] if charts else None,
            "charts": charts,
        }

        if metric_error or chart_error:
            row["error"] = "; ".join(
                error for error in [metric_error, chart_error] if error
            )

        return row

    except Exception as e:
        print(f"{spec.name} search failed")
        print(traceback.format_exc())
        return {
            "platform": spec.code,
            "platform_name": spec.name,
            "found": False,
            "error": str(e),
            "charts": [],
        }

    finally:
        crawler.close()


def _search_netease(crawler: Any, keyword: str) -> ChartSongItem | None:
    data = crawler.request_json(
        "GET",
        "https://music.163.com/api/search/get/web",
        params={"s": keyword, "type": 1, "offset": 0, "limit": 10},
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
            _chart_song(
                platform=crawler.platform_name,
                song_name=str(raw.get("name") or ""),
                artist_name=join_artists(artists),
                artist_names=extract_artist_names(artists),
                platform_song_id=song_id,
                album_name=album.get("name"),
                album_id=str(album.get("id") or "") or None,
                cover_url=album.get("picUrl") or album.get("picurl"),
                song_url=f"https://music.163.com/song?id={song_id}",
                raw_metadata=raw,
            )
        )
    return _best_candidate(candidates, _entity_for_keyword(keyword))


def _search_qq(crawler: Any, keyword: str) -> ChartSongItem | None:
    return crawler.search_song(keyword)


def _search_kugou(crawler: Any, keyword: str) -> ChartSongItem | None:
    data = crawler.request_json(
        "GET",
        "https://songsearch.kugou.com/song_search_v2",
        params={
            "keyword": keyword,
            "page": 1,
            "pagesize": 10,
            "userid": -1,
            "clientver": 2000,
            "platform": "WebFilter",
            "tag": "em",
            "filter": 2,
            "iscorrection": 1,
            "privilege_filter": 0,
        },
        headers={"Referer": "https://www.kugou.com/"},
    )
    songs = ((data.get("data") or {}).get("lists") or [])
    candidates: list[ChartSongItem] = []
    for raw in songs:
        song_hash = str(raw.get("FileHash") or raw.get("Hash") or raw.get("hash") or "")
        if not song_hash:
            continue
        artist_name, song_name = split_artist_title(
            _clean_html(str(raw.get("FileName") or raw.get("SongName") or raw.get("songname") or "")),
            _clean_html(str(raw.get("SingerName") or raw.get("singername") or "")),
        )
        candidates.append(
            _chart_song(
                platform=crawler.platform_name,
                song_name=song_name,
                artist_name=artist_name,
                artist_names=split_artist_names(artist_name),
                platform_song_id=song_hash,
                song_hash=song_hash,
                album_name=raw.get("AlbumName") or raw.get("album_name"),
                album_id=str(raw.get("AlbumID") or raw.get("album_id") or raw.get("AlbumAudioID") or "") or None,
                cover_url=_kugou_cover(raw.get("Image") or raw.get("imgurl")),
                song_url=f"https://www.kugou.com/song/#hash={song_hash}",
                raw_metadata=raw,
            )
        )
    return _best_candidate(candidates, _entity_for_keyword(keyword))


def _chart_song(
    *,
    platform: str,
    song_name: str,
    artist_name: str,
    artist_names: list[str],
    platform_song_id: str,
    raw_metadata: dict[str, Any],
    **extra: Any,
) -> ChartSongItem:
    return ChartSongItem(
        platform=platform,
        chart_name="搜索结果",
        chart_type="explore",
        rank=1,
        song_name=song_name,
        artist_name=artist_name,
        display_artist_name=artist_name,
        artist_names=artist_names,
        primary_artist_name=artist_names[0] if artist_names else None,
        platform_song_id=platform_song_id,
        chart_date=date.today(),
        collect_time=datetime.now(),
        extra_metadata=json.dumps(raw_metadata, ensure_ascii=False),
        **extra,
    )


def _entity_for_keyword(keyword: str) -> dict[str, Any]:
    return _SEARCH_ENTITIES.get(keyword) or {"song_name": keyword, "artist_name": "", "confidence": 0.0}


def _best_candidate(candidates: list[ChartSongItem], entity: dict[str, Any]) -> ChartSongItem | None:
    if not candidates:
        return None
    scored = [(candidate, _candidate_score(candidate, entity)) for candidate in candidates]
    scored.sort(key=lambda item: item[1], reverse=True)
    best, score = scored[0]
    print(f"selected candidate score={score} song={best.song_name} artist={best.artist_name}")
    return best


def _candidate_score(song: ChartSongItem, entity: dict[str, Any]) -> int:
    score = 0
    target_song = _normalize_song(entity.get("song_name"))
    target_artist = _normalize_artist(entity.get("artist_name"))
    song_name = _normalize_song(song.song_name)
    artist_name = _normalize_artist(song.artist_name)

    if target_song and song_name == target_song:
        score += 100
    if target_artist and artist_name == target_artist:
        score += 80
    elif target_artist and target_artist in artist_name:
        score += 50
    if target_artist and artist_name == target_artist:
        score += 20

    comment_count = _candidate_comment_count(song)
    if comment_count > 0:
        score += min(20, int(math.log10(comment_count + 1) * 4))

    text = f"{song.raw_song_name or song.song_name} {song.album_name or ''}".lower()
    penalties = (
        ("dj", -50),
        ("remix", -50),
        ("翻唱", -50),
        ("cover", -50),
        ("live", -30),
        ("现场", -30),
        ("伴奏", -50),
        ("instrumental", -50),
        ("钢琴", -40),
        ("深情", -20),
        ("完整版", -10),
    )
    for word, penalty in penalties:
        if word in text:
            score += penalty
    return score


def _candidate_comment_count(song: ChartSongItem) -> int:
    if not song.extra_metadata:
        return 0
    try:
        raw = json.loads(song.extra_metadata)
    except json.JSONDecodeError:
        return 0
    for key in ("comment_count", "commentCount", "commenttotal", "totalComments", "comments"):
        value = raw.get(key) if isinstance(raw, dict) else None
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return 0


def _chart_coverage(crawler: Any, target: ChartSongItem) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for chart in crawler.chart_configs:
        try:
            songs = crawler.fetch_chart(chart, date.today(), settings.crawler_top_n)
        except Exception:
            continue
        for song in songs:
            if _same_song(target.song_name, target.artist_name, song.song_name, song.artist_name):
                rows.append({"chart_name": chart.name, "rank": song.rank})
                break
    return rows


def _explore_result(session_id: str, platform_rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(platform_rows, key=lambda item: PLATFORM_ORDER.index(item["platform"]))
    target_song_key = _target_song_key(ordered)
    if target_song_key:
        ordered = [
            item if not item.get("found") or _normalize_song(item.get("song_name")) == target_song_key
            else {"platform": item["platform"], "platform_name": item["platform_name"], "found": False, "charts": []}
            for item in ordered
        ]
    found = [item for item in ordered if item.get("found")]
    canonical = _canonical_song(found)
    return {
        "session_id": session_id,
        "canonical_song": canonical,
        "platforms": ordered,
        "heat_score": _calculate_heat_score(ordered),
    }


def _target_song_key(platforms: list[dict[str, Any]]) -> str:
    counts: dict[str, int] = {}
    for item in platforms:
        key = _normalize_song(item.get("song_name"))
        if item.get("found") and key:
            counts[key] = counts.get(key, 0) + 1
    if not counts:
        return ""
    return max(counts, key=lambda key: counts[key])


def _canonical_song(platforms: list[dict[str, Any]]) -> dict[str, Any]:
    if not platforms:
        return {}
    first = platforms[0]
    song_name = first.get("song_name") or ""
    artist_name = first.get("artist_name") or ""
    return {
        "song_name": song_name,
        "artist_name": artist_name,
        "song_name_normalized": _normalize_song(song_name),
        "artist_name_normalized": _normalize_artist(artist_name),
        "album_name": first.get("album_name"),
        "release_time": first.get("release_time"),
        "cover_url": next((item.get("cover_url") for item in platforms if item.get("cover_url")), None),
        "platform_coverage": [item["platform"] for item in platforms],
    }


def _calculate_heat_score(platforms: list[dict[str, Any]]) -> int:
    comments = [int(item["comment_count"]) for item in platforms if item.get("comment_count") is not None]
    best_ranks = [int(chart["rank"]) for item in platforms for chart in item.get("charts", []) if chart.get("rank")]
    comment_score = min(math.log10(max(comments) + 1) / 6 * 100, 100) if comments else 0
    rank_score = max(0, 101 - min(best_ranks)) if best_ranks else 0
    return round(0.6 * comment_score + 0.4 * rank_score)


def _cached_song_evidence(song_name: str, artist_name: str) -> dict[str, Any]:
    target_hash = _song_hash(song_name, artist_name)
    for key in list(_EXPLORE_CACHE):
        value = _cache_get(key)
        if not value or not key.startswith("explore:"):
            continue
        canonical = value.get("canonical_song") or {}
        if _song_hash(canonical.get("song_name"), canonical.get("artist_name")) == target_hash:
            return value
    return {}


def _web_search_many(song_name: str, artist_name: str) -> list[dict[str, str]]:
    queries = [
        f"{song_name} {artist_name} 抖音",
        f"{song_name} {artist_name} 翻红",
        f"{song_name} {artist_name} 演唱会",
        f"{song_name} {artist_name} 热度变化",
    ]
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for query in queries:
        for item in _web_search(query):
            if item["url"] in seen:
                continue
            seen.add(item["url"])
            results.append(item)
            if len(results) >= 8:
                return results
    return results


def _web_search(query: str) -> list[dict[str, str]]:
    url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
    try:
        with httpx.Client(timeout=12, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as client:
            text = client.get(url).text
    except Exception:
        return []

    titles = re.findall(r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', text, flags=re.S)
    snippets = re.findall(r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', text, flags=re.S)
    rows: list[dict[str, str]] = []
    for index, (raw_url, raw_title) in enumerate(titles[:4]):
        rows.append({
            "title": _clean_html(raw_title),
            "snippet": _clean_html(snippets[index] if index < len(snippets) else ""),
            "url": unescape(raw_url),
        })
    return rows


def _call_ai(system_prompt: str, payload: dict[str, Any]) -> str:
    if not (settings.ai_enabled and settings.ai_api_key):
        raise RuntimeError("AI not configured")
    api_base = settings.ai_api_base.rstrip("/")
    request = {
        "model": settings.ai_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
        ],
        "temperature": 0.25,
    }
    with httpx.Client(timeout=settings.ai_timeout_seconds) as client:
        response = client.post(
            f"{api_base}/chat/completions",
            headers={"Authorization": f"Bearer {settings.ai_api_key}", "Content-Type": "application/json"},
            json=request,
        )
        response.raise_for_status()
        data = response.json()
    return data["choices"][0]["message"]["content"]


def _build_ai_prompt(song_name: str, artist_name: str) -> str:
    return f"""
你是音乐平台的实时热度分析助手。请基于输入的歌曲实时平台数据和网页搜索结果，分析《{song_name}》{artist_name}近期热度变化原因。

要求：
只输出自然语言段落，不要 JSON、不要项目符号、不要表格、不要标题。
必须围绕抖音传播、翻唱/二创、演唱会或现场、影视综艺使用、怀旧情绪、歌迷创作等外部传播因素展开。
可以结合评论数、榜单覆盖、平台差异判断热度来源。
不要编造具体事实；证据不足时用谨慎的自然表达。
字数控制在 120 到 260 字。
""".strip()


def _normalize_song(value: str | None) -> str:
    text = str(value or "").lower()
    text = re.sub(r"[\(\[（【].*?[\)\]）】]", "", text)
    text = re.sub(r"(live|remix|dj|伴奏|现场版|完整版|翻唱|cover|2025版|新版|纯音乐|instrumental)", "", text, flags=re.I)
    text = re.sub(r"\s+", "", text)
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", text)


def _normalize_artist(value: str | None) -> str:
    text = str(value or "").lower()
    text = re.sub(r"(feat\.?|ft\.?|featuring|with|、|，|,|/|&|\+|和|与)", "", text, flags=re.I)
    text = re.sub(r"\s+", "", text)
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", text)


def _same_song(left_name: str, left_artist: str, right_name: str, right_artist: str) -> bool:
    return _normalize_song(left_name) == _normalize_song(right_name) and (
        not _normalize_artist(left_artist)
        or not _normalize_artist(right_artist)
        or _normalize_artist(left_artist) in _normalize_artist(right_artist)
        or _normalize_artist(right_artist) in _normalize_artist(left_artist)
    )


def _song_hash(song_name: str | None, artist_name: str | None) -> str:
    return f"{_normalize_song(song_name)}:{_normalize_artist(artist_name)}"


def _cache_set(key: str, value: Any, ttl: int = TTL_SECONDS) -> None:
    _purge_expired()
    if len(_EXPLORE_CACHE) >= MAX_CACHE_SIZE:
        oldest = min(_EXPLORE_CACHE, key=lambda item: _EXPLORE_CACHE[item][1])
        _EXPLORE_CACHE.pop(oldest, None)
    _EXPLORE_CACHE[key] = (time.monotonic() + ttl, time.monotonic(), value)


def _cache_get(key: str) -> Any | None:
    item = _EXPLORE_CACHE.get(key)
    if not item:
        return None
    expires_at, _, value = item
    if expires_at < time.monotonic():
        _EXPLORE_CACHE.pop(key, None)
        return None
    return value


def _purge_expired() -> None:
    now = time.monotonic()
    for key, (expires_at, _, _) in list(_EXPLORE_CACHE.items()):
        if expires_at < now:
            _EXPLORE_CACHE.pop(key, None)


def _metadata_value(song: ChartSongItem, key: str) -> Any:
    if not song.extra_metadata:
        return None
    try:
        value = json.loads(song.extra_metadata)
    except json.JSONDecodeError:
        return None
    return value.get(key)


def _kugou_cover(value: Any) -> str | None:
    return str(value).replace("{size}", "400") if value else None


def _clean_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def _clean_ai_text(value: str | None) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text.strip("` \n")

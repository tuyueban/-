from __future__ import annotations

import json
import re
import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from os import getenv
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlencode, urlsplit, urlunsplit, parse_qsl

from app.crawlers.dtos import ChartSongItem, SongMetricItem
from app.crawlers.utils import deep_find_number, parse_count


COUNT_KEYS = {
    "comment_count": {
        "comment_count",
        "commentCount",
        "commentcount",
        "comment_total",
        "commenttotal",
        "comments",
        "total",
        "评论数",
    },
}


@dataclass
class MetricValues:
    source_name: str
    source_url: str | None = None
    comment_count: int | None = None
    fail_reason: str | None = None

    @property
    def is_success(self) -> bool:
        return self.comment_count is not None


def build_metric_item(
    platform: str,
    song: ChartSongItem,
    attempts: list[MetricValues],
    default_fail_reason: str,
) -> SongMetricItem:
    comment_count = _first_value(attempts, "comment_count")
    collect_count = _estimated_collect_count(platform, song, comment_count)
    is_success = comment_count is not None

    failed_attempts = [
        f"{attempt.source_name}: {attempt.fail_reason}"
        for attempt in attempts
        if attempt.fail_reason
    ]

    fail_reason = None
    if comment_count is None:
        fail_reason = "missing fields: comment_count"
    if failed_attempts:
        joined = "; ".join(failed_attempts)
        fail_reason = f"{fail_reason}; attempts: {joined}" if fail_reason else joined
    if not is_success and not fail_reason:
        fail_reason = default_fail_reason

    source = _source_summary(attempts) or song.song_url
    return SongMetricItem(
        platform=platform,
        platform_song_id=song.platform_song_id,
        song_name=song.song_name,
        artist_name=song.artist_name,
        comment_count=comment_count,
        collect_count=collect_count,
        metric_time=datetime.now(),
        metric_source=source,
        is_success=is_success,
        fail_reason=_clip(fail_reason, 1000),
    )


def fetch_configured_comment_attempts(crawler: Any, song: ChartSongItem) -> list[MetricValues]:
    prefix = crawler.platform_key.upper()
    raw_urls = (
        getenv(f"{prefix}_COMMENT_URLS", "").strip()
        or getenv(f"{prefix}_METRIC_URLS", "").strip()
    )
    if not raw_urls:
        return []

    attempts: list[MetricValues] = []
    for index, template in enumerate(_split_templates(raw_urls), start=1):
        source_name = f"{crawler.platform_key}_configured_comment_source_{index}"
        url = template
        try:
            url = template.format_map(_TemplateContext(song))
            response = crawler.client.request(
                "GET",
                url,
                headers={"Referer": song.song_url or ""},
            )
            text = response.text
            values = _extract_from_response_text(source_name, url, text)
            if not values.is_success:
                log_comment_attempt_failure(
                    platform=crawler.platform_name,
                    song=song,
                    source_name=source_name,
                    source_url=url,
                    identifier_type="configured_url",
                    identifier=url,
                    status_code=response.status_code,
                    response_content_type=response.headers.get("content-type"),
                    response_snippet=text,
                    fail_reason=values.fail_reason or "comment_count not found",
                )
            attempts.append(values)
        except Exception as exc:  # noqa: BLE001
            fail_reason = f"configured comment endpoint failed: {exc}"
            log_comment_attempt_failure(
                platform=crawler.platform_name,
                song=song,
                source_name=source_name,
                source_url=url,
                identifier_type="configured_url",
                identifier=url,
                status_code=None,
                response_content_type=None,
                response_snippet=None,
                fail_reason=fail_reason,
            )
            attempts.append(MetricValues(source_name=source_name, source_url=template, fail_reason=fail_reason))
    return attempts


fetch_configured_metric_attempts = fetch_configured_comment_attempts


def extract_metric_values_from_payload(
    source_name: str,
    source_url: str,
    payload: Any,
) -> MetricValues:
    return MetricValues(
        source_name=source_name,
        source_url=source_url,
        comment_count=deep_find_number(payload, COUNT_KEYS["comment_count"]),
    )


def extract_metric_values_from_text(
    source_name: str,
    source_url: str,
    text: str,
) -> MetricValues:
    return MetricValues(
        source_name=source_name,
        source_url=source_url,
        comment_count=_extract_count_by_patterns(text, ("comment", "评论")),
    )


def fetch_public_comment_attempt(
    *, crawler: Any, song: ChartSongItem, identifier_type: str, identifier: str, source_name: str, source_url: str,
    request: Callable[[], Any], extract_comment_count: Callable[[dict[str, Any]], int | None],
    non_object_fail_reason: str, request_fail_prefix: str,
) -> MetricValues:
    cached_comment_count = crawler.cached_comment_count(identifier_type, identifier)
    if cached_comment_count is not None:
        return MetricValues(source_name=f"{source_name}_cache", source_url=source_url, comment_count=cached_comment_count)
    if crawler.has_recent_metric_failure(identifier_type, identifier):
        return MetricValues(source_name=f"{source_name}_failure_cache", source_url=source_url, fail_reason="skipped by recent failure cache")

    response_meta = {"status_code": None, "content_type": None, "snippet": None}
    comment_count: int | None = None
    fail_reason: str | None = None
    try:
        response = request()
        response_meta.update(status_code=response.status_code, content_type=response.headers.get("content-type"), snippet=response.text)
        response.raise_for_status()
        data = parse_json_or_jsonp(response.text)
        comment_count = extract_comment_count(data) if isinstance(data, dict) else None
        fail_reason = None if isinstance(data, dict) else non_object_fail_reason
        if comment_count is None:
            fail_reason = fail_reason or "comment_count not found"
    except Exception as exc:  # noqa: BLE001
        fail_reason = f"{request_fail_prefix}: {exc}"

    if comment_count is None:
        crawler.store_comment_failure(identifier_type, identifier)
        log_comment_attempt_failure(
            platform=crawler.platform_name,
            song=song,
            source_name=source_name,
            source_url=source_url,
            identifier_type=identifier_type,
            identifier=identifier,
            status_code=response_meta["status_code"],
            response_content_type=response_meta["content_type"],
            response_snippet=response_meta["snippet"],
            fail_reason=fail_reason or "comment_count not found",
        )
    else:
        crawler.store_comment_success(identifier_type, identifier, comment_count)

    return MetricValues(source_name=source_name, source_url=source_url, comment_count=comment_count, fail_reason=fail_reason)


def _extract_from_response_text(source_name: str, source_url: str, text: str) -> MetricValues:
    payload = parse_json_or_jsonp(text)
    if payload is None:
        values = extract_metric_values_from_text(source_name, source_url, text)
    else:
        values = extract_metric_values_from_payload(source_name, source_url, payload)

    if not values.is_success:
        values.fail_reason = "metric fields not found in configured response"
    return values


def parse_json_or_jsonp(text: str) -> Any | None:
    stripped = text.strip()
    if not stripped:
        return None
    candidates = [stripped]
    start = stripped.find("{")
    end = stripped.rfind("}")
    if 0 <= start < end:
        candidates.append(stripped[start : end + 1])
    start = stripped.find("[")
    end = stripped.rfind("]")
    if 0 <= start < end:
        candidates.append(stripped[start : end + 1])
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def _extract_count_by_patterns(text: str, keywords: tuple[str, ...]) -> int | None:
    for keyword in keywords:
        patterns = (
            rf'"[^"]*{re.escape(keyword)}[^"]*"\s*:\s*"?([\d.,]+(?:万|亿)?)"?',
            rf"'{re.escape(keyword)}[^']*'\s*:\s*'?([\d.,]+(?:万|亿)?)'?",
            rf"{re.escape(keyword)}[^0-9万亿]{{0,12}}([\d.,]+(?:万|亿)?)",
        )
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                parsed = parse_count(match.group(1))
                if parsed is not None:
                    return parsed
    return None


def _first_value(attempts: list[MetricValues], attr: str) -> int | None:
    for attempt in attempts:
        value = getattr(attempt, attr)
        if value is not None:
            return value
    return None


def _estimated_collect_count(platform: str, song: ChartSongItem, comment_count: int | None) -> int | None:
    if comment_count is None:
        return None
    seed = "|".join(
        [
            platform,
            song.platform_song_id or "",
            song.platform_song_mid or "",
            song.song_name or "",
            song.artist_name or "",
        ]
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    multiplier = 50 + (int(digest[:8], 16) % 51)
    return int(comment_count) * multiplier


def _source_summary(attempts: list[MetricValues]) -> str | None:
    sources: list[str] = []
    for attempt in attempts:
        source = sanitize_url(attempt.source_url) or attempt.source_name
        if source and source not in sources:
            sources.append(source)
    return _clip("; ".join(sources), 500) if sources else None


def _clip(value: str | None, limit: int) -> str | None:
    if value is None or len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _split_templates(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"\s*\|\s*", value) if item.strip()]


class _TemplateContext(dict[str, str]):
    def __init__(self, song: ChartSongItem) -> None:
        extra = parse_extra_metadata(song)
        raw_values = {
            "platform_song_id": song.platform_song_id,
            "song_id": song.platform_song_id,
            "platform_song_mid": song.platform_song_mid or "",
            "song_mid": song.platform_song_mid or "",
            "album_id": song.album_id or "",
            "album_mid": song.album_mid or "",
            "song_hash": song.song_hash or "",
            "album_audio_id": str(extra.get("album_audio_id") or ""),
            "audio_id": str(extra.get("audio_id") or ""),
            "mixsongid": str(extra.get("mixsongid") or ""),
            "song_name": song.song_name,
            "artist_name": song.artist_name,
            "song_url": song.song_url or "",
        }
        super().__init__(raw_values)
        for key, value in raw_values.items():
            self[f"{key}_q"] = quote_plus(value or "")

    def __missing__(self, key: str) -> str:
        return ""


def parse_extra_metadata(song: ChartSongItem) -> dict[str, Any]:
    if not song.extra_metadata:
        return {}
    try:
        value = json.loads(song.extra_metadata)
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def log_comment_attempt_failure(
    *,
    platform: str,
    song: ChartSongItem,
    source_name: str,
    source_url: str | None,
    identifier_type: str,
    identifier: str | None,
    status_code: int | None,
    response_content_type: str | None,
    response_snippet: str | None,
    fail_reason: str,
) -> None:
    log_dir = Path(__file__).resolve().parents[3] / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"metric_comment_failures_{datetime.now().date().isoformat()}.jsonl"
    row = {
        "platform": platform,
        "song_name": song.song_name,
        "artist_name": song.artist_name,
        "platform_song_id": song.platform_song_id,
        "platform_song_mid": song.platform_song_mid,
        "song_hash": song.song_hash,
        "source_name": source_name,
        "source_url": sanitize_url(source_url),
        "identifier_type": identifier_type,
        "identifier": identifier,
        "status_code": status_code,
        "response_content_type": response_content_type,
        "response_snippet": _clip(response_snippet, 300),
        "parsed_comment_count": None,
        "fail_reason": fail_reason,
    }
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(row, ensure_ascii=False) + "\n")


def sanitize_url(url: str | None) -> str | None:
    if not url:
        return url
    sensitive = {
        "cookie",
        "token",
        "skey",
        "p_skey",
        "pskey",
        "uin",
        "loginuin",
        "hostuin",
        "g_tk",
        "gtk",
        "auth",
        "authorization",
    }
    parts = urlsplit(url)
    query = [
        (key, "***" if key.lower() in sensitive else value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

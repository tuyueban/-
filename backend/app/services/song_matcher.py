from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.crawlers.utils import canonical_artist_key, clean_artist_name, split_artist_names


VERSION_WORDS = (
    "live",
    "remix",
    "remastered",
    "acoustic",
    "cover",
    "instrumental",
    "radio edit",
    "edit",
    "sped up",
    "slowed",
    "version",
    "现场版",
    "现场",
    "伴奏",
    "翻唱",
    "重制版",
    "版",
)

ARTIST_SEPARATORS = re.compile(
    r"\s*(?:,|，|、|/|／|&|＆|\+|feat\.?|ft\.?|featuring|with|和|与)\s*",
    flags=re.IGNORECASE,
)

ARTIST_GROUP_ALIASES = {
    "mfbty": ["尹美莱", "Tiger JK", "Bizzy"],
}


def normalize_song_title(title: str | None) -> str:
    text = unicodedata.normalize("NFKC", title or "").strip().lower()
    if not text:
        return ""

    text = text.replace("（", "(").replace("）", ")")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"\[[^\]]*\]", "", text)
    text = re.sub(r"【[^】]*】", "", text)

    text = _strip_version_suffix(text)
    text = re.sub(r"\s*[-_]\s*[\u4e00-\u9fff]{1,8}$", "", text)
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[^\w\u4e00-\u9fff]+", "", text, flags=re.UNICODE)
    return text


def normalize_artists(artists: str | list[str] | tuple[str, ...] | set[str] | None) -> list[str]:
    if artists is None:
        raw_items: list[str] = []
    elif isinstance(artists, str):
        raw_items = _split_artist_text(artists)
    else:
        raw_items = []
        for item in artists:
            raw_items.extend(_split_artist_text(str(item)))

    result: set[str] = set()
    for item in raw_items:
        key = canonical_artist_key(item)
        if key:
            result.add(key)
            for alias in ARTIST_GROUP_ALIASES.get(key, []):
                alias_key = canonical_artist_key(alias)
                if alias_key:
                    result.add(alias_key)
    return sorted(result)


def artist_display_names(artists: str | list[str] | tuple[str, ...] | set[str] | None) -> list[str]:
    if artists is None:
        raw_items: list[str] = []
    elif isinstance(artists, str):
        raw_items = _split_artist_text(artists)
    else:
        raw_items = []
        for item in artists:
            raw_items.extend(_split_artist_text(str(item)))

    seen: set[str] = set()
    result: list[str] = []
    for item in raw_items:
        name = clean_artist_name(item)
        key = canonical_artist_key(name)
        if name and key not in seen:
            seen.add(key)
            result.append(name)
    return result


def artists_overlap(left: Any, right: Any) -> bool:
    left_set = set(normalize_artists(left))
    right_set = set(normalize_artists(right))
    if not left_set or not right_set:
        return True
    return bool(left_set & right_set) or left_set <= right_set or right_set <= left_set


def should_merge_songs(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_title = normalize_song_title(left.get("song_name") or left.get("title") or left.get("name"))
    right_title = normalize_song_title(right.get("song_name") or right.get("title") or right.get("name"))
    if not left_title or left_title != right_title:
        return False
    return artists_overlap(
        left.get("artist_names") or left.get("artist_name") or left.get("artists"),
        right.get("artist_names") or right.get("artist_name") or right.get("artists"),
    )


def song_identity_key(song_name: str | None, artist_name: str | None) -> str:
    return f"{normalize_song_title(song_name)}|{'|'.join(normalize_artists(artist_name))}"


def _split_artist_text(value: str) -> list[str]:
    text = clean_artist_name(value)
    if not text:
        return []
    names = split_artist_names(text)
    if len(names) <= 1 and " " in text:
        protected = re.sub(r"\bTiger\s+JK\b", "Tiger_JK", text, flags=re.IGNORECASE)
        parts = [clean_artist_name(item).replace("Tiger_JK", "Tiger JK") for item in re.split(r"\s{1,}", protected) if item.strip()]
        if len(parts) > 1:
            return parts
    return [name for name in names if name]


def _strip_version_suffix(text: str) -> str:
    escaped = [re.escape(word) for word in VERSION_WORDS]
    version_pattern = "|".join(escaped)
    text = re.sub(rf"\s*[-_/]\s*(?:{version_pattern})\s*$", "", text, flags=re.IGNORECASE)
    text = re.sub(rf"\s+(?:{version_pattern})\s*$", "", text, flags=re.IGNORECASE)
    return text.strip(" -_")

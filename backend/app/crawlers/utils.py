from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable
from typing import Any


VERSION_PATTERN = r"(live|remix|dj|伴奏|instrumental|karaoke|片段|现场|完整版|新版|特别版|影视|主题曲|片尾曲|插曲|cover|翻唱|版)"

INSTRUMENTAL_WORDS = (
    "伴奏",
    "Instrumental",
    "instrumental",
    "Karaoke",
    "karaoke",
    "纯音乐版",
    "无人声版",
    "伴唱版",
)

ARTIST_ALIAS_MAP = {
    "gem邓紫棋": "G.E.M.邓紫棋",
    "g.e.m邓紫棋": "G.E.M.邓紫棋",
    "g.e.m.邓紫棋": "G.E.M.邓紫棋",
    "邓紫棋": "G.E.M.邓紫棋",
    "jaychou": "周杰伦",
    "jaychou": "周杰伦",
    "easonchan": "陈奕迅",
    "easonchan": "陈奕迅",
}

ARTIST_SPLIT_PATTERN = re.compile(
    r"\s*(?:,|，|、|/|／|&|＆|\+|feat\.?|ft\.?|featuring|with|和|与)\s*",
    flags=re.IGNORECASE,
)


def clean_song_name(value: str | None) -> str:
    text = (value or "").strip()
    text = re.sub(r"\s+", " ", text)
    text = text.replace("（", "(").replace("）", ")")
    text = re.sub(rf"\([^)]*{VERSION_PATTERN}[^)]*\)", "", text, flags=re.IGNORECASE)
    text = re.sub(rf"\[[^\]]*{VERSION_PATTERN}[^\]]*\]", "", text, flags=re.IGNORECASE)
    text = re.sub(rf"（[^）]*{VERSION_PATTERN}[^）]*）", "", text, flags=re.IGNORECASE)
    return text.strip(" -_")


def clean_artist_name(value: str | None) -> str:
    text = (value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text.strip(" ,")


def split_artist_names(raw_artist_name: str | None) -> list[str]:
    text = clean_artist_name(raw_artist_name)
    if not text:
        return []
    names = [clean_artist_name(item) for item in ARTIST_SPLIT_PATTERN.split(text)]
    return [name for name in names if name]


def artist_normalized_key(name: str | None) -> str:
    if not name:
        return ""

    text = unicodedata.normalize("NFKC", name)
    text = text.strip()
    text = re.sub(r"\s+", "", text)
    text = text.replace("．", ".")
    text = text.replace("。", ".")
    text = text.replace("·", ".")
    text = text.lower()
    return text


ARTIST_ALIAS_MAP = {
    "gem邓紫棋": "G.E.M.邓紫棋",
    "g.e.m邓紫棋": "G.E.M.邓紫棋",
    "g.e.m.邓紫棋": "G.E.M.邓紫棋",
    "邓紫棋": "G.E.M.邓紫棋",

    "jaychou": "周杰伦",
    "周杰伦": "周杰伦",

    "easonchan": "陈奕迅",
    "陈奕迅": "陈奕迅",

    "jjlin": "林俊杰",
    "林俊杰": "林俊杰",

    "mayday": "五月天",
    "五月天": "五月天",
}


def canonical_artist_name(name: str | None) -> str:
    if not name:
        return ""

    raw_name = clean_artist_name(name)
    key = artist_normalized_key(raw_name)
    return ARTIST_ALIAS_MAP.get(key, raw_name)


def canonical_artist_key(name: str | None) -> str:
    canonical = canonical_artist_name(name)
    return artist_normalized_key(canonical)


def extract_artist_names(items: Iterable[Any]) -> list[str]:
    names: list[str] = []
    for item in items:
        name = None
        if isinstance(item, str):
            name = item
        elif isinstance(item, dict):
            name = item.get("name") or item.get("singer_name") or item.get("singername")
        if name:
            names.append(clean_artist_name(str(name)))
    return [name for name in names if name]


def is_instrumental(song_name: str | None) -> bool:
    return detect_version_type(song_name) == "instrumental"


def detect_version_type(value: str | None) -> str:
    text = value or ""
    lower = text.lower()

    if "伴奏" in text or "instrumental" in lower or "karaoke" in lower:
        return "instrumental"
    if "live" in lower or "现场" in text:
        return "live"
    if "remix" in lower or "混音" in text:
        return "remix"
    if "dj" in lower:
        return "dj"
    if "片段" in text or "snippet" in lower:
        return "snippet"
    if "cover" in lower or "翻唱" in text:
        return "cover"
    if "影视" in text or "主题曲" in text or "片尾曲" in text or "插曲" in text:
        return "version"
    if "版" in text:
        return "version"
    return "original"


def join_artists(items: Iterable[Any]) -> str:
    return clean_artist_name(", ".join(extract_artist_names(items)))


def parse_count(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if math.isfinite(value) else None

    text = str(value).strip().replace(",", "")
    if not text or text in {"-", "--", "null", "None"}:
        return None

    multiplier = 1
    if text.endswith("万"):
        multiplier = 10_000
        text = text[:-1]
    elif text.endswith("亿"):
        multiplier = 100_000_000
        text = text[:-1]

    match = re.search(r"-?\d+(\.\d+)?", text)
    if not match:
        return None
    return int(float(match.group(0)) * multiplier)


def deep_find_number(payload: Any, keys: set[str]) -> int | None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in keys:
                parsed = parse_count(value)
                if parsed is not None:
                    return parsed
            found = deep_find_number(value, keys)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = deep_find_number(item, keys)
            if found is not None:
                return found
    return None


def split_artist_title(filename: str | None, fallback_artist: str | None = None) -> tuple[str, str]:
    text = (filename or "").strip()
    if " - " in text:
        artist, title = text.split(" - ", 1)
        return clean_artist_name(fallback_artist or artist), clean_song_name(title)
    return clean_artist_name(fallback_artist), clean_song_name(text)

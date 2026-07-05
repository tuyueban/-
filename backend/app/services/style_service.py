from __future__ import annotations

import re
from typing import Any


CORE_STYLES = [
    "流行",
    "说唱 / Hip-Hop",
    "电子 / Dance",
    "国风 / 古风",
    "OST / 影视音乐",
    "R&B / Soul",
    "摇滚",
    "民谣",
    "ACG / 二次元",
    "古典",
    "短视频热歌",
]


UNCLASSIFIED_STYLE_LABELS = {"其他", "其他榜", "未分类", "未识别", "unknown", "misc", "other"}
GENERIC_HOT_CHART_PATTERNS = (r"热歌榜", r"新歌榜", r"飙升榜", r"综合榜", r"top\s*500", r"热门歌曲", r"评论热度榜", r"平台总榜")


def normalize_style_name(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text:
        return None

    compact = re.sub(r"[\s_\-－—/]+", "", text).lower()
    if text in UNCLASSIFIED_STYLE_LABELS or compact in UNCLASSIFIED_STYLE_LABELS:
        return None

    if re.search(r"说唱|嘻哈|rap|hip-?hop|hiphop", text, flags=re.I):
        return "说唱 / Hip-Hop"
    if re.search(r"电子|电音|dance|edm|electro|dj", text, flags=re.I):
        return "电子 / Dance"
    if re.search(r"国风|古风|中国风|古风国风|国乐", text):
        return "国风 / 古风"
    if re.search(r"ost|影视|原声|影视原声|影视音乐|电影|剧集", text, flags=re.I):
        return "OST / 影视音乐"
    if re.search(r"r&b|rnb|soul|节奏布鲁斯", text, flags=re.I):
        return "R&B / Soul"
    if re.search(r"摇滚|rock", text, flags=re.I):
        return "摇滚"
    if re.search(r"民谣|folk", text, flags=re.I):
        return "民谣"
    if re.search(r"acg|二次元|动漫|动画|游戏", text, flags=re.I):
        return "ACG / 二次元"
    if re.search(r"古典|classical", text, flags=re.I):
        return "古典"
    if re.search(r"短视频|抖音|快手|tiktok", text, flags=re.I):
        return "短视频热歌"
    if compact in {"流行指数榜", "popularindex"}:
        return "流行"
    if any(re.search(pattern, text, flags=re.I) for pattern in GENERIC_HOT_CHART_PATTERNS):
        return None
    if compact in {"pop", "cpop", "mandopop", "mandarinpop", "流行", "流行pop", "pop流行", "流行榜"} or re.search(r"华语流行|中文流行|国语流行|mandarin\s*pop|c-?pop", text, flags=re.I):
        return "流行"

    return None


def ensure_core_styles_visible(style_stats: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    items = [item for item in style_stats if item.get("style") in CORE_STYLES and int(item.get("count") or item.get("song_count") or 0) > 0]
    items.sort(key=lambda item: int(item.get("count") or item.get("song_count") or 0), reverse=True)

    pop_index = next(
        (
            index
            for index, item in enumerate(items)
            if item.get("style") == "流行" and int(item.get("count") or item.get("song_count") or 0) > 0
        ),
        -1,
    )
    if pop_index >= limit:
        pop_item = items.pop(pop_index)
        items.insert(max(0, limit - 1), pop_item)
    return items

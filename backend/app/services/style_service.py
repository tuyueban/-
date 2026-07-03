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
    "其他",
]


def normalize_style_name(value: str | None) -> str:
    text = (value or "").strip()
    if not text:
        return "其他"

    compact = re.sub(r"[\s_]+", "", text).lower()
    compact = compact.replace("－", "-").replace("—", "-")

    if re.search(r"说唱|嘻哈|rap|hip-?hop|hiphop", text, flags=re.I):
        return "说唱 / Hip-Hop"
    if re.search(r"电子|电音|dance|edm|electro", text, flags=re.I):
        return "电子 / Dance"
    if re.search(r"国风|古风|中国风|古风国风|国乐", text):
        return "国风 / 古风"
    if re.search(r"ost|影视|原声|影视原声|影视音乐|电影", text, flags=re.I):
        return "OST / 影视音乐"
    if re.search(r"r&b|rnb|soul|节奏布鲁斯", text, flags=re.I):
        return "R&B / Soul"
    if re.search(r"摇滚|rock", text, flags=re.I):
        return "摇滚"
    if re.search(r"民谣|folk", text, flags=re.I):
        return "民谣"
    if re.search(r"acg|二次元|动漫|动画|动漫音乐|游戏音乐", text, flags=re.I):
        return "ACG / 二次元"
    if re.search(r"古典|classical", text, flags=re.I):
        return "古典"
    if re.search(r"短视频|抖音|快手|tiktok", text, flags=re.I):
        return "短视频热歌"
    if (
        compact in {"pop", "c-pop", "cpop", "mandopop", "mandarinpop"}
        or "流行" in text
        or text in {"华语", "国语", "热歌", "热门", "热歌榜", "流行榜"}
        or "热歌榜" in text
        or "流行榜" in text
        or "流行指数" in text
        or "热门" in text
    ):
        return "流行"

    return "其他"


def ensure_core_styles_visible(style_stats: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    items = sorted(style_stats, key=lambda item: int(item.get("count") or item.get("song_count") or 0), reverse=True)
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
        insert_at = max(0, limit - 1)
        items.insert(insert_at, pop_item)
    return items

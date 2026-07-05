from __future__ import annotations

import json
import re
from typing import Any, Callable


AiCall = Callable[[str, dict[str, Any]], str]


def identify_song_entity(keyword: str, call_ai: AiCall) -> dict[str, Any]:
    text = keyword.strip()
    if not text:
        return {"song_name": "", "artist_name": "", "confidence": 0.0}

    try:
        content = call_ai(_build_entity_prompt(text), {"keyword": text})
        entity = _parse_entity_json(content)
        song_name = str(entity.get("song_name") or text).strip()
        artist_name = str(entity.get("artist_name") or "").strip()
        confidence = float(entity.get("confidence") or 0)
    except Exception:
        return {"song_name": text, "artist_name": "", "confidence": 0.0}

    user_artist = _user_artist_hint(text)
    if user_artist:
        artist_name = user_artist

    return {
        "song_name": song_name or text,
        "artist_name": artist_name,
        "confidence": max(0.0, min(confidence, 1.0)),
    }


def _build_entity_prompt(keyword: str) -> str:
    return f"""
你是音乐搜索实体识别助手。

用户搜索关键词：
{keyword}

任务：
识别用户最可能想搜索的歌曲名称和歌手名称。

要求：
1. 优先返回原唱版本。
2. 优先返回知名度最高版本。
3. 不要返回 DJ版、翻唱版、深情版、伴奏版、Live版、Remix版、钢琴版。
4. 如果用户已经输入歌手，例如“晴天 周杰伦”，必须保留用户指定歌手。
5. 只返回 JSON，不要解释，不要 Markdown。

返回格式：
{{"song_name":"","artist_name":"","confidence":0.0}}

示例：
输入：晴天
输出：{{"song_name":"晴天","artist_name":"周杰伦","confidence":0.99}}

输入：演员
输出：{{"song_name":"演员","artist_name":"薛之谦","confidence":0.99}}

输入：唯一
输出：{{"song_name":"唯一","artist_name":"告五人","confidence":0.92}}
""".strip()


def _parse_entity_json(content: str) -> dict[str, Any]:
    text = str(content or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("AI entity result is not an object")
    return value


def _user_artist_hint(keyword: str) -> str:
    parts = [item.strip() for item in re.split(r"\s+|-|—|_", keyword.strip()) if item.strip()]
    if len(parts) >= 2:
        return parts[-1]
    return ""

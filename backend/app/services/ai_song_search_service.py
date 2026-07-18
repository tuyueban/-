from __future__ import annotations

import json
import logging
import re
from difflib import SequenceMatcher
from typing import Any

import httpx
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import HeatScoreDaily, PlatformSong, Song
from app.services.analytics_service import AnalyticsService
from app.services.style_service import normalize_style_intent


logger = logging.getLogger(__name__)

EXPLORE_MODES = {
    "style": {
        "label": "相似风格探索",
        "focus": "分析歌曲曲风、音乐元素、歌手风格、听众群体。",
    },
    "emotion": {
        "label": "相似情绪探索",
        "focus": "分析歌曲情绪、歌词表达、适合场景、用户心理。",
    },
    "trend": {
        "label": "热门趋势探索",
        "focus": "结合歌曲热度数据、平台排名变化、传播情况，分析歌曲增长潜力。",
    },
}

EMOTION_STYLE_HINTS = {
    "伤感": ["流行"],
    "emo": ["流行"],
    "治愈": ["流行", "民谣"],
    "温柔": ["流行", "R&B / Soul"],
    "安静": ["民谣", "流行"],
    "热血": ["摇滚", "说唱 / Hip-Hop"],
    "快乐": ["流行", "电子 / Dance"],
    "浪漫": ["R&B / Soul", "流行"],
}

SCENE_STYLE_HINTS = {
    "学习": ["民谣", "流行"],
    "通勤": ["流行", "R&B / Soul"],
    "运动": ["电子 / Dance", "说唱 / Hip-Hop"],
    "派对": ["电子 / Dance", "说唱 / Hip-Hop"],
    "夜晚": ["R&B / Soul", "流行"],
    "开车": ["摇滚", "流行"],
    "短视频": ["短视频热歌", "流行"],
}


class AiSongSearchService:
    def __init__(self, db: Session | None = None) -> None:
        self.db = db or SessionLocal()
        self._owns_session = db is None

    def close(self) -> None:
        if self._owns_session:
            self.db.close()

    def __enter__(self) -> "AiSongSearchService":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        self.close()

    def search(self, query: str, limit: int = 5, mode: str = "style") -> dict[str, Any]:
        explore_mode = normalize_explore_mode(mode)
        intent = self._parse_intent(query, explore_mode)
        styles = intent.get("styles") or []

        latest_score_date = self.db.execute(select(func.max(HeatScoreDaily.score_date))).scalar_one_or_none()
        if latest_score_date is None:
            return _search_response(
                query=query,
                mode=explore_mode,
                styles=styles,
                songs=[],
                intent=_intent_label(intent),
                intent_detail=intent,
                results=[],
                analysis="当前暂无热度数据，AI 已完成意图解析，但还不能生成数据库推荐。",
            )

        candidates = self._collect_candidates(intent, explore_mode, latest_score_date, limit)
        expanded = not any(item.get("source") in {"exact", "artist"} for item in candidates.values())
        ranked = self._rank_candidates(query, intent, explore_mode, candidates)
        songs = [item["song"] for item in ranked[:limit]]
        results = self._generate_explorations(query, explore_mode, songs, intent)

        return _search_response(
            query=query,
            mode=explore_mode,
            styles=styles,
            songs=songs,
            intent=_intent_label(intent),
            intent_detail=intent,
            results=results,
            explorations=results,
            expanded=expanded,
            analysis=_search_analysis(intent, explore_mode, results, expanded),
        )

    def _collect_candidates(
        self,
        intent: dict[str, Any],
        mode: str,
        latest_score_date: Any,
        limit: int,
    ) -> dict[int, dict[str, Any]]:
        candidates: dict[int, dict[str, Any]] = {}
        self._merge_candidates(candidates, self._direct_candidates(intent, latest_score_date, limit * 5), "exact")
        self._merge_candidates(candidates, self._artist_candidates(intent, latest_score_date, limit * 5), "artist")
        self._merge_candidates(candidates, self._style_candidates(intent, latest_score_date, limit * 6), "style")
        if mode in {"emotion", "trend"} or len(candidates) < limit:
            self._merge_candidates(candidates, self._expanded_style_candidates(intent, latest_score_date, limit * 6), "expanded")
        if mode == "trend" or len(candidates) < limit:
            self._merge_candidates(candidates, self._hot_candidates(latest_score_date, limit * 6), "hot")
        return candidates

    def _direct_candidates(self, intent: dict[str, Any], latest_score_date: Any, limit: int) -> list[dict[str, Any]]:
        has_named_target = bool(str(intent.get("song_name") or "").strip() or str(intent.get("artist_name") or "").strip())
        terms = [
            intent.get("song_name"),
            intent.get("artist_name"),
            *intent.get("keywords", []),
        ]
        terms = [str(term).strip() for term in terms if str(term or "").strip()]
        if not terms:
            return []
        conditions = []
        for term in terms[:6]:
            like = f"%{term}%"
            conditions.extend([
                Song.song_name.ilike(like),
                Song.artist_name.ilike(like),
                Song.album_name.ilike(like),
            ])
        rows = self.db.execute(
            select(HeatScoreDaily, Song)
            .join(Song, HeatScoreDaily.song_id == Song.song_id)
            .where(HeatScoreDaily.score_date == latest_score_date, or_(*conditions))
            .order_by(desc(HeatScoreDaily.heat_score))
            .limit(limit)
        ).all()
        source = "exact" if has_named_target else "text"
        return [self._candidate_from_row(score, song, source) for score, song in rows]

    def _artist_candidates(self, intent: dict[str, Any], latest_score_date: Any, limit: int) -> list[dict[str, Any]]:
        artist_name = str(intent.get("artist_name") or "").strip()
        if not artist_name:
            return []
        rows = self.db.execute(
            select(HeatScoreDaily, Song)
            .join(Song, HeatScoreDaily.song_id == Song.song_id)
            .where(HeatScoreDaily.score_date == latest_score_date, Song.artist_name.ilike(f"%{artist_name}%"))
            .order_by(desc(HeatScoreDaily.heat_score))
            .limit(limit)
        ).all()
        return [self._candidate_from_row(score, song, "artist") for score, song in rows]

    def _style_candidates(self, intent: dict[str, Any], latest_score_date: Any, limit: int) -> list[dict[str, Any]]:
        style_songs = self._style_song_map(intent.get("styles") or [])
        return self._candidates_by_song_ids(style_songs, latest_score_date, limit, "style")

    def _expanded_style_candidates(self, intent: dict[str, Any], latest_score_date: Any, limit: int) -> list[dict[str, Any]]:
        expanded_styles = _styles_for_emotion_scene(intent)
        style_songs = self._style_song_map(expanded_styles)
        return self._candidates_by_song_ids(style_songs, latest_score_date, limit, "expanded")

    def _hot_candidates(self, latest_score_date: Any, limit: int) -> list[dict[str, Any]]:
        rows = self.db.execute(
            select(HeatScoreDaily, Song)
            .join(Song, HeatScoreDaily.song_id == Song.song_id)
            .where(HeatScoreDaily.score_date == latest_score_date)
            .order_by(desc(HeatScoreDaily.heat_score))
            .limit(limit)
        ).all()
        return [self._candidate_from_row(score, song, "hot") for score, song in rows]

    def _candidates_by_song_ids(
        self,
        style_songs: dict[int, dict[str, Any]],
        latest_score_date: Any,
        limit: int,
        source: str,
    ) -> list[dict[str, Any]]:
        if not style_songs:
            return []
        rows = self.db.execute(
            select(HeatScoreDaily, Song)
            .join(Song, HeatScoreDaily.song_id == Song.song_id)
            .where(HeatScoreDaily.score_date == latest_score_date, Song.song_id.in_(style_songs.keys()))
            .order_by(desc(HeatScoreDaily.heat_score))
            .limit(limit)
        ).all()
        return [
            self._candidate_from_row(score, song, source, style_songs.get(song.song_id, {}))
            for score, song in rows
        ]

    def _candidate_from_row(
        self,
        score: HeatScoreDaily,
        song: Song,
        source: str,
        style_item: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        style_item = style_item or {}
        return {
            "source": source,
            "song": {
                "song_id": song.song_id,
                "song_name": song.song_name,
                "artist_name": song.artist_name,
                "album_name": song.album_name,
                "cover_url": style_item.get("cover_url") or self._cover_for_song(song.song_id),
                "style": style_item.get("style") or _infer_style_from_text(song.song_name, song.album_name),
                "heat_score": _float(score.heat_score),
                "rank": score.rank,
                "rank_delta": score.rank_delta,
                "trend_label": score.trend_label,
                "platform_count": score.platform_count,
                "dominant_platform": score.dominant_platform,
                "platform_scores": {
                    "netease": _float(score.netease_score),
                    "qq": _float(score.qq_score),
                    "kugou": _float(score.kugou_score),
                },
                "score_date": score.score_date.isoformat(),
                "charts": style_item.get("charts") or [],
                "chart_name": style_item.get("chart_name"),
            },
        }

    def _merge_candidates(self, target: dict[int, dict[str, Any]], items: list[dict[str, Any]], source: str) -> None:
        for item in items:
            song = item.get("song") or {}
            song_id = song.get("song_id")
            if not song_id:
                continue
            actual_source = item.get("source") or source
            existing = target.get(int(song_id))
            if existing is None:
                target[int(song_id)] = item
                continue
            existing_sources = set(existing.get("sources") or [existing.get("source")])
            existing_sources.add(actual_source)
            existing["sources"] = sorted(value for value in existing_sources if value)

    def _rank_candidates(
        self,
        query: str,
        intent: dict[str, Any],
        mode: str,
        candidates: dict[int, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        ranked = []
        for item in candidates.values():
            song = item["song"]
            score = _candidate_similarity_score(query, intent, mode, song, item.get("source"), item.get("sources") or [])
            song["search_score"] = round(score, 2)
            ranked.append({**item, "score": score})
        ranked.sort(key=lambda item: item["score"], reverse=True)
        return ranked

    def _parse_intent(self, query: str, mode: str) -> dict[str, Any]:
        fallback = _fallback_intent(query, mode)
        if not (settings.ai_enabled and settings.ai_api_key):
            return fallback
        try:
            content = self._call_ai(_build_intent_prompt(mode), {"query": query, "mode": mode})
            return _merge_intent(fallback, _parse_intent_json(content))
        except Exception:  # noqa: BLE001
            logger.exception("AI song search intent parsing failed")
            return fallback

    def _generate_explorations(
        self,
        query: str,
        mode: str,
        songs: list[dict[str, Any]],
        intent: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        fallback = [_fallback_exploration(song, mode) for song in songs]
        if not songs or not (settings.ai_enabled and settings.ai_api_key):
            return fallback

        try:
            content = self._call_ai(
                _build_explore_prompt(mode),
                {"query": query, "mode": mode, "intent": intent or {}, "songs": songs},
            )
            parsed = _parse_exploration_items(content)
        except Exception:  # noqa: BLE001
            logger.exception("AI song exploration generation failed")
            return fallback

        return _align_explorations(songs, parsed, fallback)

    @staticmethod
    def _call_ai(system_prompt: str, payload: dict[str, Any]) -> str:
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
                headers={
                    "Authorization": f"Bearer {settings.ai_api_key}",
                    "Content-Type": "application/json",
                },
                json=request,
            )
            response.raise_for_status()
            data = response.json()
        return data["choices"][0]["message"]["content"]

    def _style_song_map(self, styles: list[str]) -> dict[int, dict[str, Any]]:
        distribution = AnalyticsService(self.db).get_style_distribution(days=30, limit=500)
        style_set = set(styles)
        songs: dict[int, dict[str, Any]] = {}
        for bucket in distribution.get("items") or []:
            style = bucket.get("style") or bucket.get("style_name")
            if style not in style_set:
                continue
            for song in bucket.get("songs") or []:
                song_id = song.get("song_id")
                if not song_id:
                    continue
                item = songs.setdefault(
                    int(song_id),
                    {
                        "style": style,
                        "cover_url": song.get("cover_url"),
                        "charts": [],
                        "chart_name": None,
                    },
                )
                chart_name = song.get("chart_name")
                rank = song.get("rank")
                if chart_name:
                    chart = {
                        "chart_name": chart_name,
                        "rank": rank,
                        "chart_date": distribution.get("chart_date"),
                    }
                    if chart not in item["charts"]:
                        item["charts"].append(chart)
                    current = item.get("chart_name")
                    if not current or (rank is not None and rank < item.get("_best_rank", 999999)):
                        item["chart_name"] = chart_name
                        item["_best_rank"] = rank if rank is not None else 999999

        for item in songs.values():
            item.pop("_best_rank", None)
        return songs

    def _cover_for_song(self, song_id: int) -> str | None:
        return self.db.execute(
            select(PlatformSong.cover_url)
            .where(PlatformSong.song_id == song_id, PlatformSong.cover_url.is_not(None))
            .order_by(PlatformSong.id)
            .limit(1)
        ).scalar_one_or_none()


def _float(value: Any) -> float:
    return round(float(value or 0), 2)


def normalize_explore_mode(mode: str | None) -> str:
    value = str(mode or "style").strip().lower()
    return value if value in EXPLORE_MODES else "style"


def _search_response(
    query: str,
    mode: str,
    styles: list[str],
    songs: list[dict[str, Any]],
    intent: str,
    intent_detail: dict[str, Any] | None = None,
    results: list[dict[str, Any]] | None = None,
    analysis: str = "",
    explorations: list[dict[str, Any]] | None = None,
    expanded: bool = False,
) -> dict[str, Any]:
    result_items = results or explorations or []
    return {
        "results": [_public_result(item) for item in result_items],
        "analysis": analysis,
        "intent": intent,
        "intent_detail": intent_detail or {},
        "styles": styles,
        "mode": mode,
        "mode_label": EXPLORE_MODES[mode]["label"],
        "query": query,
        "expanded": expanded,
        "songs": songs,
        "explorations": explorations or result_items,
    }


def _public_result(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "song": str(item.get("song") or ""),
        "artist": str(item.get("artist") or ""),
        "similarity": str(item.get("similarity") or ""),
        "tags": list(item.get("tags") or [])[:4],
        "reason": str(item.get("reason") or ""),
    }


def _build_intent_prompt(mode: str) -> str:
    return f"""
你是音乐搜索意图解析器。请从用户输入中提取歌曲探索意图，并只输出 JSON。

当前模式：{EXPLORE_MODES[mode]["label"]}

输出字段：
{{"song_name":"","artist_name":"","styles":[],"emotions":[],"scenes":[],"keywords":[]}}

规则：
1. song_name 和 artist_name 没有明确提到就留空。
2. styles 可使用：流行、说唱 / Hip-Hop、电子 / Dance、国风 / 古风、OST / 影视音乐、R&B / Soul、摇滚、民谣、ACG / 二次元、古典、短视频热歌。
3. emotions 记录伤感、治愈、热血、浪漫、安静、快乐、孤独等情绪。
4. scenes 记录学习、通勤、运动、派对、夜晚、开车、短视频等场景。
5. keywords 保留能帮助数据库搜索的短词，不要超过 6 个。
""".strip()


def _build_explore_prompt(mode: str) -> str:
    mode_config = EXPLORE_MODES[mode]
    return f"""
你是音乐平台的 AI 歌曲探索助手。请基于用户描述和候选歌曲数据，生成 {mode_config["label"]} 的结构化结果。

本次分析重点：{mode_config["focus"]}

要求：
1. 保持候选歌曲顺序，不要新增候选列表之外的歌曲。
2. 只输出 JSON 数组，不要 Markdown，不要解释。
3. 数组中每个对象必须包含并仅包含以下字段：
{{"song":"","artist":"","similarity":"","tags":[],"reason":"","trend_analysis":""}}
4. similarity 使用简短中文或百分比表达，例如 "风格贴合 91%"、"情绪贴合 88%"、"趋势潜力 86%"。
5. tags 输出 2 到 4 个短标签。
6. reason 用一句话解释为什么推荐。
7. trend_analysis 在 trend 模式下写增长潜力；在 style 或 emotion 模式下可简短说明热度或传播观察。
8. 不要编造具体事件；数据不足时用保守表达。
""".strip()


def _fallback_intent(query: str, mode: str) -> dict[str, Any]:
    text = str(query or "").strip()
    song_name, artist_name = _guess_song_artist(text)
    styles = normalize_style_intent(text)
    emotions = _keyword_hits(text, EMOTION_STYLE_HINTS.keys())
    scenes = _keyword_hits(text, SCENE_STYLE_HINTS.keys())
    for style in _styles_for_terms(emotions, EMOTION_STYLE_HINTS) + _styles_for_terms(scenes, SCENE_STYLE_HINTS):
        if style not in styles:
            styles.append(style)
    if mode == "trend" and "流行" not in styles:
        styles.append("流行")
    return {
        "song_name": song_name,
        "artist_name": artist_name,
        "styles": styles,
        "emotions": emotions,
        "scenes": scenes,
        "keywords": _fallback_keywords(text, song_name, artist_name, styles, emotions, scenes),
    }


def _parse_intent_json(content: str | None) -> dict[str, Any]:
    text = str(content or "").strip()
    if not text:
        return {}
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            return {}
        try:
            value = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
    return value if isinstance(value, dict) else {}


def _merge_intent(base: dict[str, Any], parsed: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key in ("song_name", "artist_name"):
        value = str(parsed.get(key) or "").strip()
        if value:
            result[key] = value
    for key in ("styles", "emotions", "scenes", "keywords"):
        values = parsed.get(key) or []
        if not isinstance(values, list):
            values = [values]
        for value in values:
            text = str(value or "").strip()
            if text and text not in result[key]:
                result[key].append(text)
    normalized_styles: list[str] = []
    for value in result.get("styles") or []:
        for style in normalize_style_intent(value) or [value]:
            if style and style not in normalized_styles:
                normalized_styles.append(style)
    result["styles"] = normalized_styles
    return result


def _guess_song_artist(text: str) -> tuple[str, str]:
    cleaned = re.sub(r"^(推荐|搜索|找|我想听|想听|来点|有没有|有没有类似)\s*", "", text).strip()
    for sep in (" - ", "-", "｜", "|", " / ", "/", "，", ","):
        if sep in cleaned:
            parts = [part.strip(" 《》\"'") for part in cleaned.split(sep) if part.strip()]
            if len(parts) >= 2 and all(len(part) <= 40 for part in parts[:2]):
                return parts[0], parts[1]
    space_parts = [part.strip(" 《》\"'") for part in cleaned.split() if part.strip()]
    if len(space_parts) == 2 and all(1 < len(part) <= 30 for part in space_parts):
        if not any(re.search(r"推荐|类似|适合|热门|最近|歌曲|风格|情绪|场景", part) for part in space_parts):
            return space_parts[0], space_parts[1]
    match = re.search(r"[《\"]([^《》\"]{1,40})[》\"]\s*([^，,。 ]{1,30})?", cleaned)
    if match:
        return match.group(1).strip(), (match.group(2) or "").strip()
    if len(cleaned) <= 24 and not re.search(r"风格|情绪|场景|推荐|类似|适合|热门|最近|歌曲|歌", cleaned):
        return cleaned, ""
    return "", ""


def _keyword_hits(text: str, values: Any) -> list[str]:
    return [str(value) for value in values if str(value) and str(value).lower() in text.lower()]


def _styles_for_terms(terms: list[str], mapping: dict[str, list[str]]) -> list[str]:
    styles: list[str] = []
    for term in terms:
        for style in mapping.get(term, []):
            if style not in styles:
                styles.append(style)
    return styles


def _styles_for_emotion_scene(intent: dict[str, Any]) -> list[str]:
    styles = list(intent.get("styles") or [])
    for style in _styles_for_terms(intent.get("emotions") or [], EMOTION_STYLE_HINTS):
        if style not in styles:
            styles.append(style)
    for style in _styles_for_terms(intent.get("scenes") or [], SCENE_STYLE_HINTS):
        if style not in styles:
            styles.append(style)
    if not styles:
        styles.append("流行")
    return styles


def _fallback_keywords(
    text: str,
    song_name: str,
    artist_name: str,
    styles: list[str],
    emotions: list[str],
    scenes: list[str],
) -> list[str]:
    blocked = {"推荐", "搜索", "歌曲", "歌", "类似", "适合", "想听", "来点", "最近", "很火"}
    seeds = [song_name, artist_name, *styles, *emotions, *scenes]
    words = re.split(r"[\s,，。.!！?？、]+", text)
    for word in words:
        value = word.strip(" 《》\"'")
        if 1 < len(value) <= 16 and value not in blocked:
            seeds.append(value)
    result: list[str] = []
    for value in seeds:
        if value and value not in result:
            result.append(value)
        if len(result) >= 6:
            break
    return result


def _candidate_similarity_score(
    query: str,
    intent: dict[str, Any],
    mode: str,
    song: dict[str, Any],
    source: str | None,
    sources: list[str],
) -> float:
    source_set = set(sources or [])
    if source:
        source_set.add(source)
    text = " ".join(str(song.get(key) or "") for key in ("song_name", "artist_name", "album_name", "style"))
    score = SequenceMatcher(None, _compact(query), _compact(text)).ratio() * 35
    heat_score = min(100.0, float(song.get("heat_score") or 0))
    score += heat_score * (0.24 if mode == "trend" else 0.16)
    if "exact" in source_set:
        score += 28
    if "artist" in source_set:
        score += 18
    if "style" in source_set:
        score += 18 if mode == "style" else 12
    if "expanded" in source_set:
        score += 12 if mode == "emotion" else 8
    if "hot" in source_set:
        score += 18 if mode == "trend" else 7
    if _compact(intent.get("song_name")) and _compact(intent.get("song_name")) in _compact(song.get("song_name")):
        score += 25
    if _compact(intent.get("artist_name")) and _compact(intent.get("artist_name")) in _compact(song.get("artist_name")):
        score += 18
    if song.get("style") in (intent.get("styles") or []):
        score += 20 if mode == "style" else 12
    if mode == "emotion" and (intent.get("emotions") or intent.get("scenes")):
        style_hints = _styles_for_emotion_scene(intent)
        if song.get("style") in style_hints:
            score += 18
    if mode == "trend":
        rank_delta = song.get("rank_delta")
        if isinstance(rank_delta, int) and rank_delta > 0:
            score += min(12, rank_delta)
        if song.get("trend_label"):
            score += 6
    return min(score, 100)


def _compact(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").lower())


def _infer_style_from_text(song_name: str | None, album_name: str | None) -> str:
    text = f"{song_name or ''} {album_name or ''}"
    styles = normalize_style_intent(text)
    return styles[0] if styles else ""


def _intent_label(intent: dict[str, Any]) -> str:
    values = [
        intent.get("song_name"),
        intent.get("artist_name"),
        *(intent.get("styles") or []),
        *(intent.get("emotions") or []),
        *(intent.get("scenes") or []),
    ]
    label = " / ".join(str(value) for value in values if value)
    return label or "AI 扩展探索"


def _search_analysis(
    intent: dict[str, Any],
    mode: str,
    results: list[dict[str, Any]],
    expanded: bool,
) -> str:
    mode_label = EXPLORE_MODES[mode]["label"]
    if not results:
        return "AI 已完成意图解析，但当前数据库样本不足，暂时无法形成推荐。"
    prefix = "未命中精确歌曲，已自动扩大探索范围" if expanded else "已结合精确线索和扩展候选"
    focus = {
        "style": "优先匹配曲风、音乐元素和相近听众群体。",
        "emotion": "优先匹配情绪表达、使用场景和相近心理需求。",
        "trend": "优先匹配综合热度、排名变化和传播潜力。",
    }[mode]
    return f"{prefix}，本次按「{mode_label}」处理。{focus}共发现 {len(results)} 首相关歌曲。"


def _parse_exploration_items(content: str | None) -> list[dict[str, Any]]:
    text = str(content or "").strip()
    if not text:
        return []
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"(\[.*\]|\{.*\})", text, flags=re.S)
        if not match:
            return []
        try:
            value = json.loads(match.group(1))
        except json.JSONDecodeError:
            return []

    if isinstance(value, dict):
        value = value.get("items") or value.get("songs") or [value]
    if not isinstance(value, list):
        return []
    return [_normalize_exploration_item(item) for item in value if isinstance(item, dict)]


def _normalize_exploration_item(item: dict[str, Any]) -> dict[str, Any]:
    tags = item.get("tags") or []
    if not isinstance(tags, list):
        tags = [str(tags)]
    return {
        "song": str(item.get("song") or item.get("song_name") or "").strip(),
        "artist": str(item.get("artist") or item.get("artist_name") or "").strip(),
        "similarity": str(item.get("similarity") or "").strip(),
        "tags": [str(tag).strip() for tag in tags if str(tag).strip()][:4],
        "reason": str(item.get("reason") or "").strip(),
        "trend_analysis": str(item.get("trend_analysis") or item.get("trend") or "").strip(),
    }


def _align_explorations(
    songs: list[dict[str, Any]],
    parsed: list[dict[str, Any]],
    fallback: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    by_key = {
        _song_key(item.get("song"), item.get("artist")): item
        for item in parsed
        if item.get("song")
    }
    for index, song in enumerate(songs):
        key = _song_key(song.get("song_name"), song.get("artist_name"))
        item = by_key.get(key) or (parsed[index] if index < len(parsed) else {})
        ai_values = {k: v for k, v in item.items() if v and k not in {"song", "artist"}}
        merged = {**fallback[index], **ai_values}
        if not merged.get("tags"):
            merged["tags"] = fallback[index]["tags"]
        results.append(_normalize_exploration_item(merged))
    return results


def _fallback_exploration(song: dict[str, Any], mode: str) -> dict[str, Any]:
    heat_score = _float(song.get("heat_score"))
    match_score = round(float(song.get("search_score") or heat_score or 0))
    chart_name = song.get("chart_name") or _first_chart_name(song)
    style = song.get("style") or "热门风格"
    base = {
        "song": str(song.get("song_name") or ""),
        "artist": str(song.get("artist_name") or ""),
        "tags": [str(style), "综合热度", chart_name or "榜单可见"][:3],
    }
    if mode == "emotion":
        return {
            **base,
            "similarity": f"情绪贴合 {min(98, max(70, match_score))}%",
            "reason": "旋律气质和听感表达更适合从相近情绪与使用场景继续探索。",
            "trend_analysis": f"当前综合热度 {heat_score}，可结合评论反馈和榜单可见度观察情绪共鸣。",
        }
    if mode == "trend":
        return {
            **base,
            "similarity": f"趋势潜力 {min(99, max(70, match_score))}%",
            "reason": "候选歌曲在近期热度排序中表现靠前，适合作为趋势观察对象。",
            "trend_analysis": _fallback_trend_text(song, heat_score, chart_name),
        }
    return {
        **base,
        "similarity": f"风格贴合 {min(98, max(70, match_score))}%",
        "reason": "曲风标签和近期热门池匹配度较高，适合沿相似音乐元素继续探索。",
        "trend_analysis": f"当前综合热度 {heat_score}，说明该风格在近期样本中仍具备稳定可见度。",
    }


def _first_chart_name(song: dict[str, Any]) -> str:
    charts = song.get("charts")
    if isinstance(charts, list) and charts:
        return str((charts[0] or {}).get("chart_name") or "")
    return ""


def _fallback_trend_text(song: dict[str, Any], heat_score: float, chart_name: str) -> str:
    rank_delta = song.get("rank_delta")
    trend_label = song.get("trend_label")
    dominant_platform = song.get("dominant_platform")
    rank_text = f"排名 {song.get('rank')}" if song.get("rank") else "排名待观察"
    if rank_delta:
        try:
            rank_text = f"{rank_text}，较前期变化 {int(rank_delta):+}"
        except (TypeError, ValueError):
            rank_text = f"{rank_text}，较前期变化 {rank_delta}"
    platform_text = f"，主要热度来自 {dominant_platform}" if dominant_platform else ""
    label_text = f"，趋势标签为 {trend_label}" if trend_label else ""
    return f"当前综合热度 {heat_score}，{rank_text}{platform_text}{label_text}，{chart_name or '相关榜单'}表现可作为增长潜力参考。"


def _song_key(song_name: Any, artist_name: Any) -> str:
    return re.sub(r"\s+", "", f"{song_name or ''}:{artist_name or ''}").lower()

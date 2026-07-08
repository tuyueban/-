from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date
from html import unescape
from typing import Any, Callable
from urllib.parse import quote_plus

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.analytics_service import AnalyticsService
from app.services.cache import TtlCache


logger = logging.getLogger(__name__)
DETAIL_AI_CACHE: TtlCache[dict[str, Any]] = TtlCache(ttl_seconds=60 * 60 * 6, max_size=512)


TECHNICAL_PATTERNS = (
    r"AI\s*call\s*failed[:：]?.*",
    r"Client error.*",
    r"\b401\b.*",
    r"Authorization Required.*",
    r"HTTP\s*\d+.*",
    r"本地兜底",
    r"兜底分析",
    r"接口失败",
    r"API错误",
    r"后台错误",
    r"公开搜索来源",
    r"系统内",
    r"数据侧观察[:：]?",
    r"不确定性[:：]?",
    r"歌手概览[:：]?",
    r"近况观察[:：]?",
    r"音乐风格变化[:：]?",
    r"百度百科",
    r"维基百科",
    r"搜狐",
)

SONG_REPORT_PATTERNS = (
    r"###",
    r"结论[:：]?",
    r"证据[:：]?",
    r"外部因素[:：]?",
    r"风险提示[:：]?",
    r"注意事项[:：]?",
    r"无法确定",
    r"缺乏直接证据",
)


@dataclass
class SearchResult:
    title: str
    snippet: str
    url: str


class DetailAiService:
    def __init__(self, db: Session | None = None) -> None:
        self.db = db or SessionLocal()
        self._owns_session = db is None

    def close(self) -> None:
        if self._owns_session:
            self.db.close()

    def __enter__(self) -> "DetailAiService":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        self.close()

    def song_analysis(self, song_id: int, strict_ai: bool = False) -> dict[str, Any] | None:
        analytics = AnalyticsService(self.db)
        detail = analytics.song_detail(song_id)
        if detail is None:
            return None

        song = detail["song"]
        latest_score = detail.get("latest_score") or {}
        cache_key = ("song", song_id, latest_score.get("score_date"), strict_ai, settings.ai_model)
        cached = DETAIL_AI_CACHE.get(cache_key)
        if cached is not None:
            return cached
        evidence = {
            "song": song,
            "latest_score": latest_score,
            "recent_metrics": detail.get("metrics", [])[:12],
            "recent_charts": detail.get("chart_records", [])[:12],
            "trend": detail.get("trend", [])[-14:],
        }
        evidence.update(_song_summary_evidence(evidence))
        search_results = _web_search(f"{song.get('song_name')} {song.get('artist_name')} 热度 上升 原因")
        prompt = build_song_prompt(
            song_name=str(song.get("song_name") or "该歌曲"),
            artist_name=str(song.get("artist_name") or ""),
            trend_summary=evidence["trend_summary"],
            rank_change_summary=evidence["rank_change_summary"],
            platform_summary=evidence["platform_summary"],
            chart_summary=evidence["chart_summary"],
            external_summary=_external_summary(search_results),
        )
        content, mode, error = self._generate(
            prompt,
            evidence,
            search_results,
            _local_song_analysis,
            expose_error=True,
            strict_ai=strict_ai,
        )
        display_content = _strict_song_display_text(content) if strict_ai else _song_display_text(content, evidence)
        return DETAIL_AI_CACHE.set(cache_key, _response("song_heat_reason", display_content, mode, error, evidence, search_results))

    def artist_analysis(self, artist_name: str, score_date: date | None = None, strict_ai: bool = False) -> dict[str, Any]:
        analytics = AnalyticsService(self.db)
        detail = analytics.artist_detail(artist_name=artist_name, score_date=score_date, limit=50)
        canonical_name = detail.get("canonical_artist_name") or artist_name
        cache_key = ("artist", canonical_name, detail.get("score_date"), strict_ai, settings.ai_model)
        cached = DETAIL_AI_CACHE.get(cache_key)
        if cached is not None:
            return cached
        songs = detail.get("songs", [])[:20]
        trend = detail.get("trend", [])[-30:]
        song_names = unique_song_names(songs)
        evidence = {
            "artist_name": canonical_name,
            "score_date": detail.get("score_date"),
            "ranked_songs": songs,
            "song_names": song_names,
            "trend": trend,
            "raw_artist_names": detail.get("raw_artist_names", []),
        }
        prompt = build_artist_prompt(
            artist_name=canonical_name,
            songs=song_names,
            trend_summary=_trend_summary(trend),
            style_summary=_style_summary(songs),
            platform_summary=_platform_summary(songs),
        )
        search_results = _web_search(f"{canonical_name} 歌手 近况 音乐风格")
        content, mode, error = self._generate(
            prompt,
            evidence,
            search_results,
            _local_artist_analysis,
            strict_ai=strict_ai,
        )
        display_content = _strict_artist_display_text(content) if strict_ai else _artist_display_text(content, evidence)
        return DETAIL_AI_CACHE.set(cache_key, _response("artist_profile_style", display_content, mode, error, evidence, []))

    def _generate(
        self,
        system_prompt: str,
        evidence: dict[str, Any],
        search_results: list[SearchResult],
        local_builder: Callable[[dict[str, Any], list[SearchResult]], str],
        expose_error: bool = False,
        strict_ai: bool = False,
    ) -> tuple[str, str, str | None]:
        payload = {
            "database_evidence": evidence,
            "web_search_results": [result.__dict__ for result in search_results],
        }
        if strict_ai and not (settings.ai_enabled and settings.ai_api_key):
            raise RuntimeError("AI 服务未配置，无法生成热度变化分析。")

        if settings.ai_enabled and settings.ai_api_key:
            try:
                content = sanitize_ai_text(self._call_ai(system_prompt, payload))
                if content:
                    return content, "ai", None
                if strict_ai:
                    raise RuntimeError("AI 未返回有效分析内容，请稍后重试。")
            except RuntimeError:
                logger.exception("Detail AI generation failed")
                if strict_ai:
                    raise
                if expose_error:
                    return sanitize_ai_text(local_builder(evidence, search_results)), "fallback", None
            except Exception as exc:  # noqa: BLE001
                logger.exception("Detail AI generation failed")
                if strict_ai:
                    raise RuntimeError("AI 分析生成失败，请检查 AI 服务配置或稍后重试。") from exc
                if expose_error:
                    return sanitize_ai_text(local_builder(evidence, search_results)), "fallback", None
        if strict_ai:
            raise RuntimeError("AI 服务未配置，无法生成热度变化分析。")
        return sanitize_ai_text(local_builder(evidence, search_results)), "fallback", None

    @staticmethod
    def _call_ai(system_prompt: str, payload: dict[str, Any]) -> str:
        api_base = settings.ai_api_base.rstrip("/")
        if not api_base.startswith(("http://", "https://")):
            raise RuntimeError("AI_API_BASE must be a full URL")
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


def _web_search(query: str, limit: int = 5) -> list[SearchResult]:
    url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
    try:
        with httpx.Client(timeout=12, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as client:
            text = client.get(url).text
    except Exception:
        return []

    titles = re.findall(r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', text, flags=re.S)
    snippets = re.findall(r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', text, flags=re.S)
    results: list[SearchResult] = []
    for index, (raw_url, raw_title) in enumerate(titles[:limit]):
        snippet = snippets[index] if index < len(snippets) else ""
        results.append(SearchResult(title=_clean_html(raw_title), snippet=_clean_html(snippet), url=unescape(raw_url)))
    return results


def _clean_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", "", value)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _response(
    analysis_type: str,
    content: str,
    mode: str,
    error: str | None,
    evidence: dict[str, Any],
    search_results: list[SearchResult],
) -> dict[str, Any]:
    return {
        "status": "success",
        "analysis_type": analysis_type,
        "mode": mode,
        "error": error,
        "content": content,
        "sources": [result.__dict__ for result in search_results],
        "database_evidence": evidence,
    }


def build_song_prompt(
    song_name: str,
    artist_name: str | None = None,
    trend_summary: str | None = None,
    rank_change_summary: str | None = None,
    platform_summary: str | None = None,
    chart_summary: str | None = None,
    external_summary: str | None = None,
) -> str:
    return f"""
你是音乐数据分析系统的前端文案生成助手。请根据歌曲热度趋势、榜单排名变化、平台分布和可用的外部传播线索，为歌曲生成一段适合展示在前端页面的自然中文分析文案。

要求：
1. 只输出一段话，不要分点，不要编号，不要小标题。
2. 不要使用 Markdown 格式，不要出现“### 结论”“证据”“外部因素”“风险提示”等报告式结构。
3. 不要出现“系统内”“AI分析”“兜底”“接口失败”“数据侧观察”“无法确定”“风险提示”等后台化表达。
4. 不要罗列搜索来源名称，不要直接堆叠搜索结果。
5. 可以自然提到“从当前榜单表现来看”“平台热度主要集中在某平台”“可能与短视频传播、怀旧内容、用户共鸣有关”等表达。
6. 如果外部原因证据不足，不要写“缺乏直接证据”“无法确定”，改成自然保守表达，例如“更可能与经典歌曲再传播和平台推荐有关”。
7. 字数控制在 120 到 220 字。
8. 只输出最终文案。

输入：
歌曲名称：{song_name}
歌手：{artist_name or ''}
热度趋势：{trend_summary or '出现一定回升'}
排名变化：{rank_change_summary or '近期榜单位置有所变化'}
平台表现：{platform_summary or '当前热度主要来自已接入平台'}
榜单信息：{chart_summary or '近期在相关榜单中保持可见度'}
外部传播线索：{external_summary or '可能与经典歌曲再传播、平台推荐和用户情绪共鸣有关'}
""".strip()


def build_artist_prompt(
    artist_name: str,
    songs: list[str],
    trend_summary: str | None = None,
    style_summary: str | None = None,
    platform_summary: str | None = None,
) -> str:
    return f"""
你是音乐数据分析系统的前端文案生成助手。
请根据输入信息，为歌手生成一段适合展示在网页上的自然中文介绍。

要求：
1. 只输出一段话，不要分点，不要小标题，不要编号。
2. 不要出现“歌手概览、近况观察、音乐风格变化、数据侧观察、不确定性”等报告式标题。
3. 不要出现“AI分析、系统内、兜底、公开搜索来源、外部搜索摘要、接口失败、HTTP状态码”等后台表达。
4. 不要罗列百度百科、维基百科、搜狐等来源名称。
5. 语气要像音乐平台中的歌手介绍，简洁自然，有数据分析感。
6. 如果资料不足，只根据当前榜单表现做保守描述。
7. 字数控制在120到200字。
8. 只输出最终文案。

歌手名称：{artist_name}
上榜歌曲：{'、'.join(songs[:8]) or '近期仍保持一定可见度'}
热度趋势：{trend_summary or '整体热度表现较为平稳'}
风格信息：{style_summary or '以情绪表达和流行作品为主'}
平台表现：{platform_summary or '相关作品体现出稳定的听众基础'}
""".strip()


def unique_song_names(songs: list[Any] | None) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()

    for song in songs or []:
        if isinstance(song, dict):
            raw_name = song.get("song_name") or song.get("name") or song.get("title")
        else:
            raw_name = str(song)

        name = str(raw_name or "").strip()
        if not name:
            continue

        key = re.sub(r"\s+", "", name).lower()
        if key in seen:
            continue

        seen.add(key)
        names.append(name)

    return names


def build_natural_artist_fallback(
    artist_name: str,
    songs: list[Any] | None = None,
    trend_summary: str | None = None,
    style_summary: str | None = None,
    platform_summary: str | None = None,
) -> str:
    song_names = unique_song_names(songs)
    selected_songs = song_names[:4]
    if selected_songs:
        song_text = "、".join(f"《{name}》" for name in selected_songs)
    else:
        song_text = "多首代表作品"

    style_text = "抒情流行和情绪表达类作品"
    if style_summary:
        if isinstance(style_summary, list):
            style_text = "、".join(str(item) for item in style_summary[:3])
        else:
            style_text = str(style_summary)

    return (
        f"{artist_name}是华语流行乐坛具有代表性的音乐人，作品兼具鲜明的个人辨识度与较强的情绪表达。"
        f"从当前榜单表现来看，{song_text}等歌曲仍保持较高可见度，说明其作品在多个平台上具有持续传播力。"
        f"近期上榜歌曲以{style_text}为主，整体风格较为稳定，同时体现出较强的听众共鸣和长尾热度。"
    )


def sanitize_ai_text(text: str | None) -> str:
    value = str(text or "").strip()
    if not value:
        return ""

    for pattern in TECHNICAL_PATTERNS:
        value = re.sub(pattern, "", value, flags=re.I)

    value = re.sub(r"^[\s:：,，;；。]+", "", value)
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"(。){2,}", "。", value)
    return value.strip()


def _artist_display_text(text: str | None, evidence: dict[str, Any]) -> str:
    content = sanitize_ai_text(text)
    if len(content) < 40 or len(content) > 220 or _has_blocked_display_text(content):
        content = _local_artist_analysis(evidence, [])
    return sanitize_ai_text(content)


def _song_display_text(text: str | None, evidence: dict[str, Any]) -> str:
    content = sanitize_ai_text(text)
    if len(content) < 40 or len(content) > 260 or _has_blocked_song_text(content):
        content = _local_song_analysis(evidence, [])
    return sanitize_ai_text(content)


def _strict_artist_display_text(text: str | None) -> str:
    content = sanitize_ai_text(text)
    if not content or _has_blocked_display_text(content):
        raise RuntimeError("AI 未返回有效分析内容，请稍后重试。")
    return content


def _strict_song_display_text(text: str | None) -> str:
    content = sanitize_ai_text(text)
    if not content or _has_blocked_song_text(content):
        raise RuntimeError("AI 未返回有效分析内容，请稍后重试。")
    return content


def _has_blocked_display_text(text: str) -> bool:
    return any(re.search(pattern, text, flags=re.I) for pattern in TECHNICAL_PATTERNS)


def _has_blocked_song_text(text: str) -> bool:
    patterns = TECHNICAL_PATTERNS + SONG_REPORT_PATTERNS
    return any(re.search(pattern, text, flags=re.I) for pattern in patterns)


def build_natural_song_fallback(
    song_name: str,
    artist_name: str | None = None,
    trend_label: str | None = None,
    rank_summary: str | None = None,
    platform_summary: str | None = None,
    chart_summary: str | None = None,
    external_summary: str | None = None,
) -> str:
    artist_text = f"{artist_name}的" if artist_name else ""
    trend_text = trend_label or "出现一定回升"
    rank_text = rank_summary or "近期榜单位置有所变化"
    platform_text = platform_summary or "当前热度主要来自已接入平台"
    external_text = external_summary or "可能与经典歌曲再传播、平台推荐和用户情绪共鸣有关"
    chart_text = f"，并在{chart_summary}中保持可见度" if chart_summary else ""
    return (
        f"{artist_text}《{song_name}》近期热度{trend_text}，{rank_text}，说明歌曲在当前榜单中获得了更高关注。"
        f"从平台表现来看，{platform_text}{chart_text}，体现出较强的平台可见度和传播基础。"
        f"结合歌曲本身的受众基础和内容传播特点来看，本轮热度变化{external_text}，整体呈现出一定的回温趋势。"
    )


def _local_song_analysis(evidence: dict[str, Any], search_results: list[SearchResult]) -> str:
    song = evidence.get("song") or {}
    song_name = song.get("song_name") or "该歌曲"
    artist_name = song.get("artist_name") or "该歌手"
    summaries = _song_summary_evidence(evidence)
    return build_natural_song_fallback(
        song_name=str(song_name),
        artist_name=str(artist_name) if artist_name else None,
        trend_label=summaries["trend_summary"],
        rank_summary=summaries["rank_change_summary"],
        platform_summary=summaries["platform_summary"],
        chart_summary=summaries["chart_summary"],
        external_summary=_external_summary(search_results),
    )


def _local_artist_analysis(evidence: dict[str, Any], search_results: list[SearchResult]) -> str:
    songs = evidence.get("ranked_songs") or []
    return build_natural_artist_fallback(
        artist_name=str(evidence.get("artist_name") or "该歌手"),
        songs=songs,
        trend_summary=_trend_summary(evidence.get("trend") or []),
        style_summary=_style_summary(songs),
        platform_summary=_platform_summary(songs),
    )


def _song_summary_evidence(evidence: dict[str, Any]) -> dict[str, str]:
    score = evidence.get("latest_score") or {}
    trend = evidence.get("trend") or []
    charts = evidence.get("recent_charts") or []
    return {
        "trend_summary": _song_trend_summary(score, trend),
        "rank_change_summary": _rank_change_summary(score, trend),
        "platform_summary": _song_platform_summary(score),
        "chart_summary": _chart_summary(charts),
    }


def _song_trend_summary(score: dict[str, Any], trend: list[dict[str, Any]]) -> str:
    label = str(score.get("trend_label") or "").strip()
    if label:
        if "爆发" in label or "上升" in label:
            return "呈现明显上升趋势"
        if "稳定" in label:
            return "保持稳定可见度"
        return label
    if len(trend) >= 2:
        first = float(trend[0].get("heat_score") or 0)
        last = float(trend[-1].get("heat_score") or 0)
        if last > first * 1.08:
            return "呈现明显上升趋势"
        if last < first * 0.92:
            return "短期有所波动"
    return "出现一定回升"


def _rank_change_summary(score: dict[str, Any], trend: list[dict[str, Any]]) -> str:
    current_rank = score.get("rank")
    rank_delta = score.get("rank_delta")
    if current_rank and rank_delta:
        try:
            previous_rank = int(current_rank) + int(rank_delta)
            direction = "升至" if int(rank_delta) > 0 else "调整至"
            return f"榜单排名从{previous_rank}位{direction}{current_rank}位"
        except (TypeError, ValueError):
            pass
    if current_rank:
        return f"当前榜单排名位于{current_rank}位附近"
    if len(trend) >= 2:
        return "近期榜单位置有所变化"
    return "近期榜单可见度有所提升"


def _song_platform_summary(score: dict[str, Any]) -> str:
    platform = score.get("dominant_platform")
    platform_count = score.get("platform_count")
    if platform and platform_count:
        return f"当前热度主要集中在{platform}，并覆盖{platform_count}个接入平台"
    if platform:
        return f"当前热度主要集中在{platform}"
    if platform_count:
        return f"当前歌曲覆盖{platform_count}个接入平台"
    return "当前热度主要来自已接入平台"


def _chart_summary(charts: list[dict[str, Any]]) -> str:
    names: list[str] = []
    seen: set[str] = set()
    for chart in charts:
        name = str(chart.get("chart_name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
        if len(names) >= 3:
            break
    return "、".join(names)


def _external_summary(search_results: list[SearchResult]) -> str:
    joined = " ".join(f"{item.title} {item.snippet}" for item in search_results[:5])
    if re.search(r"短视频|抖音|快手|翻唱|二创|挑战", joined, flags=re.I):
        return "可能与短视频传播、二创内容扩散和用户情绪共鸣有关"
    if re.search(r"影视|综艺|演出|现场|翻红", joined, flags=re.I):
        return "可能与近期内容曝光、经典片段再传播和平台推荐有关"
    return "可能与经典歌曲再传播、平台推荐和用户情绪共鸣有关"


def _trend_summary(trend: list[dict[str, Any]]) -> str:
    if len(trend) >= 2:
        first = float(trend[0].get("heat_score") or 0)
        last = float(trend[-1].get("heat_score") or 0)
        if last > first * 1.08:
            return "近期热度呈现温和上升"
        if last < first * 0.92:
            return "近期仍保持一定可见度"
    return "整体热度表现较为平稳"


def _style_summary(songs: list[dict[str, Any]]) -> str:
    joined = " ".join(str(song.get("song_name") or "") for song in songs[:10]).lower()
    if re.search(r"ost|影视|剧|片尾|主题曲", joined, flags=re.I):
        return "影视音乐和抒情流行作品"
    if re.search(r"rap|hip|说唱", joined, flags=re.I):
        return "流行表达和节奏感作品"
    if re.search(r"dj|remix|电子", joined, flags=re.I):
        return "流行旋律和电子化表达作品"
    return "抒情流行和情绪表达类作品"


def _platform_summary(songs: list[dict[str, Any]]) -> str:
    platform_count = max((int(song.get("platform_count") or 0) for song in songs), default=0)
    if platform_count >= 3:
        return "多个平台上具有持续传播力"
    if platform_count >= 2:
        return "主要音乐平台上保持稳定触达"
    return "当前榜单中保持一定传播力"

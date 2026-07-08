from __future__ import annotations

import json
from datetime import date
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import AiHeatAnalysis
from app.services.heat_score_service import HeatScoreService


PROMPT_VERSION = "v1"


class AiAnalysisService:
    def __init__(self, db: Session | None = None) -> None:
        self.db = db or SessionLocal()
        self._owns_session = db is None

    def close(self) -> None:
        if self._owns_session:
            self.db.close()

    def __enter__(self) -> "AiAnalysisService":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        self.close()

    def generate_daily_summary(self, analysis_date: date | None = None, limit: int = 20) -> dict[str, Any]:
        heat_service = HeatScoreService(self.db)
        summary = heat_service.top_daily_summary(score_date=analysis_date, limit=limit)
        if not summary["top_songs"]:
            return {"status": "empty", "message": "no heat score data found"}

        content = self._generate_content(summary)
        score_date = date.fromisoformat(summary["score_date"])
        row = self._upsert_analysis(
            analysis_date=score_date,
            analysis_type="daily_heat_summary",
            input_summary=json.dumps(summary, ensure_ascii=False, default=str),
            content=content,
        )
        self.db.commit()
        return {
            "status": "success",
            "analysis_date": row.analysis_date.isoformat(),
            "analysis_type": row.analysis_type,
            "model_name": row.model_name,
            "content": row.content,
        }

    def _generate_content(self, summary: dict[str, Any]) -> str:
        if settings.ai_enabled and settings.ai_api_key:
            try:
                return self._call_ai(summary)
            except Exception as exc:  # noqa: BLE001
                return self._local_summary(summary, fallback_reason=f"AI接口调用失败：{exc}")
        return self._local_summary(summary)

    def _call_ai(self, summary: dict[str, Any]) -> str:
        prompt = (
            "你是一名音乐数据分析师。请只根据输入的热度榜数据生成分析报告，"
            "不要编造未提供的歌曲、平台或数值。报告包含：总体概况、TOP歌曲解读、"
            "平台表现洞察、运营建议、数据风险提示。"
        )
        payload = {
            "model": settings.ai_model,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(summary, ensure_ascii=False)},
            ],
            "temperature": 0.3,
        }
        with httpx.Client(timeout=settings.ai_timeout_seconds) as client:
            response = client.post(
                f"{settings.ai_api_base.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.ai_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        return data["choices"][0]["message"]["content"]

    @staticmethod
    def _local_summary(summary: dict[str, Any], fallback_reason: str | None = None) -> str:
        songs = summary["top_songs"]
        top = songs[:5]
        rising = [song for song in songs if song.get("rank_delta") and song["rank_delta"] > 0][:5]

        lines = [f"{summary['score_date']} 歌曲热度分析"]
        if fallback_reason:
            lines.append(f"说明：{fallback_reason}，已使用本地规则生成分析。")
        lines.append(f"本次榜单共读取 TOP {len(songs)} 首歌曲。")
        lines.append("TOP歌曲：" + "；".join(f"{song['rank']}. {song['song_name']} - {song['artist_name']}（{song['heat_score']}）" for song in top))
        if rising:
            lines.append("上升关注：" + "；".join(f"{song['song_name']}（排名变化 {song['rank_delta']}）" for song in rising))
        lines.append("平台表现：当前综合分主要由网易云音乐、QQ音乐、酷狗音乐的榜单排名和跨平台覆盖度计算得到。")
        lines.append("运营建议：优先关注高热度且趋势为“新上榜”或“爆发上升”的歌曲，并结合后续多日趋势观察持续性。")
        lines.append("数据风险提示：AI只基于结构化分数做解释，不直接修改排行榜分数；评论数仅作为互动参考，不参与当前主热度公式。")
        return "\n".join(lines)

    def _upsert_analysis(
        self,
        analysis_date: date,
        analysis_type: str,
        input_summary: str,
        content: str,
    ) -> AiHeatAnalysis:
        existing = self.db.execute(
            select(AiHeatAnalysis).where(
                AiHeatAnalysis.analysis_date == analysis_date,
                AiHeatAnalysis.analysis_type == analysis_type,
            )
        ).scalar_one_or_none()
        model_name = settings.ai_model if settings.ai_enabled and settings.ai_api_key else "local-rule"
        if existing:
            existing.model_name = model_name
            existing.prompt_version = PROMPT_VERSION
            existing.input_summary = input_summary
            existing.content = content
            return existing

        row = AiHeatAnalysis(
            analysis_date=analysis_date,
            analysis_type=analysis_type,
            model_name=model_name,
            prompt_version=PROMPT_VERSION,
            input_summary=input_summary,
            content=content,
        )
        self.db.add(row)
        self.db.flush()
        return row

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services import DetailAiService


router = APIRouter(prefix="/ai", tags=["ai"])


class SongHeatAnalysisRequest(BaseModel):
    song_id: int | None = None
    song_name: str | None = None
    artist_name: str | None = None
    heat_trend: list[dict[str, Any]] = Field(default_factory=list)
    platform_performance: list[dict[str, Any]] = Field(default_factory=list)
    representative_metrics: dict[str, Any] = Field(default_factory=dict)
    enable_web_search: bool = True


class ArtistHeatAnalysisRequest(BaseModel):
    artist_name: str
    score_date: date | None = None
    representative_songs: list[dict[str, Any]] = Field(default_factory=list)
    platform_performance: list[dict[str, Any]] = Field(default_factory=list)
    heat_trend: list[dict[str, Any]] = Field(default_factory=list)
    enable_web_search: bool = True


def _analysis_response(item: dict[str, Any] | None) -> dict[str, Any]:
    if item is None:
        raise HTTPException(status_code=404, detail="分析对象不存在")

    analysis = str(item.get("analysis") or item.get("content") or "").strip()
    if not analysis:
        raise HTTPException(status_code=502, detail="AI 未返回有效分析内容，请稍后重试。")

    return {
        "analysis": analysis,
        "mode": item.get("mode") or "ai",
        "sources": item.get("sources") or [],
    }


@router.post("/analyze-song-heat")
def analyze_song_heat(payload: SongHeatAnalysisRequest) -> dict[str, Any]:
    if payload.song_id is None:
        raise HTTPException(status_code=400, detail="缺少 song_id，无法调用真实歌曲 AI 分析。")

    try:
        with DetailAiService() as service:
            item = service.song_analysis(payload.song_id, strict_ai=True)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return _analysis_response(item)


@router.post("/analyze-artist-heat")
def analyze_artist_heat(payload: ArtistHeatAnalysisRequest) -> dict[str, Any]:
    try:
        with DetailAiService() as service:
            item = service.artist_analysis(
                artist_name=payload.artist_name,
                score_date=payload.score_date,
                strict_ai=True,
            )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return _analysis_response(item)

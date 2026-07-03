from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services import AiAnalysisService, HeatScoreService


router = APIRouter(prefix="/heat", tags=["heat"])


class HeatComputeRequest(BaseModel):
    score_date: date | None = None
    limit: int | None = Field(default=None, ge=1, le=500)
    generate_ai: bool = False


class AiAnalysisRequest(BaseModel):
    analysis_date: date | None = None
    limit: int = Field(default=20, ge=1, le=100)


@router.post("/compute")
def compute_heat_score(payload: HeatComputeRequest) -> dict[str, object]:
    with HeatScoreService() as service:
        result = service.compute_daily(score_date=payload.score_date, limit=payload.limit)
    if payload.generate_ai and result.get("status") == "success":
        with AiAnalysisService() as service:
            result["ai_analysis"] = service.generate_daily_summary(
                analysis_date=date.fromisoformat(str(result["score_date"])),
                limit=20,
            )
    return result


@router.get("/daily")
def list_daily_heat(score_date: date | None = None, limit: int = 50) -> dict[str, object]:
    with HeatScoreService() as service:
        rows = service.list_daily(score_date=score_date, limit=limit)
    return {"items": rows, "count": len(rows)}


@router.post("/ai/analyze")
def generate_ai_analysis(payload: AiAnalysisRequest) -> dict[str, object]:
    with AiAnalysisService() as service:
        return service.generate_daily_summary(
            analysis_date=payload.analysis_date,
            limit=payload.limit,
        )

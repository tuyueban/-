from datetime import date

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.config import settings
from app.services import AnalyticsService, PipelineService


router = APIRouter(prefix="/ops", tags=["ops"])


class RunDailyRequest(BaseModel):
    target_date: date | None = None
    crawl: bool = True
    ai: bool = True


class RunBackfillRequest(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    days: int = Field(default=30, ge=1, le=60)
    crawl: bool = True
    ai: bool = False


@router.get("/logs")
def etl_logs(
    limit: int = Query(default=50, ge=1, le=200),
    task_name: str | None = None,
) -> dict[str, object]:
    with AnalyticsService() as service:
        items = service.etl_logs(limit=limit, task_name=task_name)
    return {"items": items, "count": len(items)}


@router.post("/run-daily")
def run_daily(payload: RunDailyRequest) -> dict[str, object]:
    return PipelineService().run_daily(
        target_date=payload.target_date,
        crawl=payload.crawl,
        ai=payload.ai,
    )


@router.post("/run-backfill")
def run_backfill(payload: RunBackfillRequest) -> dict[str, object]:
    try:
        return PipelineService().run_backfill(
            start_date=payload.start_date,
            end_date=payload.end_date,
            days=payload.days,
            crawl=payload.crawl,
            ai=payload.ai,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/ai-status")
def ai_status() -> dict[str, object]:
    return {
        "enabled": settings.ai_enabled,
        "configured": bool(settings.ai_enabled and settings.ai_api_key),
        "api_base": settings.ai_api_base,
        "model": settings.ai_model,
        "mode": "large_model" if settings.ai_enabled and settings.ai_api_key else "local_rule_fallback",
    }

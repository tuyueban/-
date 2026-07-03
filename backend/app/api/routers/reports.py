from datetime import date

from fastapi import APIRouter, Query

from app.services import AnalyticsService


router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/")
def reports(limit: int = Query(default=30, ge=1, le=100)) -> dict[str, object]:
    with AnalyticsService() as service:
        items = service.reports(limit=limit)
    return {"items": items, "count": len(items)}


@router.get("/latest")
def latest_report(analysis_date: date | None = None) -> dict[str, object]:
    with AnalyticsService() as service:
        item = service.latest_report(analysis_date=analysis_date)
    return {"item": item}

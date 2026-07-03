from datetime import date

from fastapi import APIRouter, HTTPException, Query

from app.services import AnalyticsService, DetailAiService


router = APIRouter(prefix="/artists", tags=["artists"])


@router.get("/rank")
def artist_rank(score_date: date | None = None, limit: int = Query(default=50, ge=1, le=200)) -> dict[str, object]:
    with AnalyticsService() as service:
        items = service.artist_rank(score_date=score_date, limit=limit)
    return {"items": items, "count": len(items)}


@router.get("/{artist_name}")
def artist_detail(
    artist_name: str,
    score_date: date | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, object]:
    with AnalyticsService() as service:
        return service.artist_detail(artist_name=artist_name, score_date=score_date, limit=limit)


@router.get("/{artist_name}/platform-performance")
def artist_platform_performance(
    artist_name: str,
    chart_type: str = "hot",
) -> dict[str, object]:
    with AnalyticsService() as service:
        return service.artist_platform_performance(artist_name=artist_name, chart_type=chart_type)


@router.get("/{artist_name}/analysis")
def artist_ai_analysis(
    artist_name: str,
    score_date: date | None = None,
) -> dict[str, object]:
    try:
        with DetailAiService() as service:
            return service.artist_analysis(artist_name=artist_name, score_date=score_date)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

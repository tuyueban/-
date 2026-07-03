from fastapi import APIRouter, HTTPException, Query

from app.services import AnalyticsService, DetailAiService


router = APIRouter(prefix="/songs", tags=["songs"])


@router.get("/search")
def search_songs(keyword: str = Query(min_length=1), limit: int = Query(default=20, ge=1, le=100)) -> dict[str, object]:
    with AnalyticsService() as service:
        items = service.search_songs(keyword=keyword, limit=limit)
    return {"items": items, "count": len(items)}


@router.get("/{song_id}")
def song_detail(song_id: int) -> dict[str, object]:
    with AnalyticsService() as service:
        item = service.song_detail(song_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Song not found")
    return item


@router.get("/{song_id}/platform-performance")
def song_platform_performance(song_id: int, chart_type: str = "hot") -> dict[str, object]:
    with AnalyticsService() as service:
        item = service.song_platform_performance(song_id=song_id, chart_type=chart_type)
    if item is None:
        raise HTTPException(status_code=404, detail="Song not found")
    return item


@router.get("/{song_id}/analysis")
def song_ai_analysis(song_id: int) -> dict[str, object]:
    try:
        with DetailAiService() as service:
            item = service.song_analysis(song_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="Song not found")
    return item

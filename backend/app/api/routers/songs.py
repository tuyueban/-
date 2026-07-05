from fastapi import APIRouter, Query

from app.api.route_utils import analytics_call, detail_ai_call, items_response, require_found


router = APIRouter(prefix="/songs", tags=["songs"])


@router.get("/search")
def search_songs(keyword: str = Query(min_length=1), limit: int = Query(default=20, ge=1, le=100)) -> dict[str, object]:
    items = analytics_call(lambda service: service.search_songs(keyword=keyword, limit=limit))
    return items_response(items)


@router.get("/{song_id}")
def song_detail(song_id: int) -> dict[str, object]:
    item = analytics_call(lambda service: service.song_detail(song_id))
    return require_found(item, "Song not found")


@router.get("/{song_id}/platform-performance")
def song_platform_performance(song_id: int, chart_type: str = "hot") -> dict[str, object]:
    item = analytics_call(lambda service: service.song_platform_performance(song_id=song_id, chart_type=chart_type))
    return require_found(item, "Song not found")


@router.get("/{song_id}/analysis")
def song_ai_analysis(song_id: int) -> dict[str, object]:
    item = detail_ai_call(lambda service: service.song_analysis(song_id))
    return require_found(item, "Song not found")

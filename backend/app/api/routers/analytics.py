from datetime import date

from fastapi import APIRouter, Query

from app.api.route_utils import analytics_call, require_found


router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/platform-song-counts")
def platform_song_counts(chart_date: date | None = None, chart_type: str = "hot") -> dict[str, object]:
    return analytics_call(lambda service: service.platform_song_counts(chart_date=chart_date, chart_type=chart_type))


@router.get("/topn-overlap")
def topn_overlap(chart_date: date | None = None, chart_type: str = "hot") -> dict[str, object]:
    return analytics_call(lambda service: service.topn_overlap(chart_date=chart_date, chart_type=chart_type))


@router.get("/platform-similarity")
def platform_similarity(chart_date: date | None = None, chart_type: str = "hot") -> dict[str, object]:
    return analytics_call(lambda service: service.platform_similarity(chart_date=chart_date, chart_type=chart_type))


@router.get("/coverage-distribution")
def coverage_distribution(chart_date: date | None = None, chart_type: str = "hot") -> dict[str, object]:
    return analytics_call(lambda service: service.coverage_distribution(chart_date=chart_date, chart_type=chart_type))


@router.get("/common-songs-summary")
def common_songs_summary(chart_date: date | None = None, chart_type: str = "hot") -> dict[str, object]:
    return analytics_call(lambda service: service.common_songs_summary(chart_date=chart_date, chart_type=chart_type))


@router.get("/all-platform-hot-songs")
def all_platform_hot_songs(
    chart_date: date | None = None,
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, object]:
    return analytics_call(lambda service: service.all_platform_hot_songs(chart_date=chart_date, limit=limit))


@router.get("/song-score-breakdown/{song_id}")
def song_score_breakdown(song_id: int) -> dict[str, object]:
    data = analytics_call(lambda service: service.song_score_breakdown(song_id=song_id))
    return require_found(data, "歌曲不存在")


@router.get("/platform-exclusive-songs")
def platform_exclusive_songs(chart_date: date | None = None) -> dict[str, object]:
    return analytics_call(lambda service: service.platform_exclusive_songs(chart_date=chart_date))


@router.get("/platform-top-artists")
def platform_top_artists(
    chart_date: date | None = None,
    limit: int = Query(default=10, ge=1, le=50),
) -> dict[str, object]:
    return analytics_call(lambda service: service.platform_top_artists(chart_date=chart_date, limit=limit))


@router.get("/platform-interaction-avg")
def platform_interaction_avg(metric_date: date | None = None) -> dict[str, object]:
    return analytics_call(lambda service: service.platform_interaction_avg(metric_date=metric_date))

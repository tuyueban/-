from datetime import date

from fastapi import APIRouter, Query

from app.services import AnalyticsService


router = APIRouter(prefix="/charts", tags=["charts"])


@router.get("/dashboard")
def dashboard(target_date: date | None = None) -> dict[str, object]:
    with AnalyticsService() as service:
        return service.dashboard(target_date=target_date)


@router.get("/daily-hot")
def daily_hot(score_date: date | None = None, limit: int = Query(default=50, ge=1, le=500)) -> dict[str, object]:
    with AnalyticsService() as service:
        items = service.daily_hot(score_date=score_date, limit=limit)
    return {"items": items, "count": len(items)}


@router.get("/weekly-hot")
def weekly_hot(end_date: date | None = None, limit: int = Query(default=50, ge=1, le=500)) -> dict[str, object]:
    with AnalyticsService() as service:
        items = service.weekly_hot(end_date=end_date, limit=limit)
    message = _weekly_message(items)
    return {"items": items, "count": len(items), "message": message}


@router.get("/monthly-hot")
def monthly_hot(end_date: date | None = None, limit: int = Query(default=50, ge=1, le=500)) -> dict[str, object]:
    return weekly_hot(end_date=end_date, limit=limit)


def _weekly_message(items: list[dict[str, object]]) -> str:
    if not items:
        return "暂无周榜数据"

    available_days = max(int(item.get("available_days") or 0) for item in items)
    if available_days >= 7:
        return "正式周榜"

    return f"当前仅累计 {available_days} 天数据，暂展示近 {available_days} 日累计榜；连续采集 7 天后生成正式周榜。"


@router.get("/rising")
def rising(score_date: date | None = None, limit: int = Query(default=50, ge=1, le=500)) -> dict[str, object]:
    with AnalyticsService() as service:
        return service.rising_result(score_date=score_date, limit=limit)


@router.get("/new-songs")
def new_songs(chart_date: date | None = None, limit: int = Query(default=50, ge=1, le=500)) -> dict[str, object]:
    with AnalyticsService() as service:
        items = service.new_songs(chart_date=chart_date, limit=limit)
    return {"items": items, "count": len(items)}


@router.get("/interaction-heat")
def interaction_heat(metric_date: date | None = None, limit: int = Query(default=50, ge=1, le=500)) -> dict[str, object]:
    with AnalyticsService() as service:
        items = service.interaction_heat(metric_date=metric_date, limit=limit)
    return {"items": items, "count": len(items)}


@router.get("/platform")
def platform_chart(
    chart_date: date | None = None,
    platform: str | None = None,
    chart_name: str | None = None,
    days: int = Query(default=30, ge=1, le=90),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, object]:
    with AnalyticsService() as service:
        items = service.chart_songs(
            chart_date=chart_date,
            platform=platform,
            chart_name=chart_name,
            limit=limit,
        )
    return {"items": items, "count": len(items)}

@router.get("/style-buckets")
def style_buckets(
    chart_date: date | None = None,
    days: int = Query(default=30, ge=1, le=90),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, object]:
    with AnalyticsService() as service:
        data = service.get_style_distribution(chart_date=chart_date, days=days, limit=limit)

    return {
        **data,
        "count": len(data["items"]),
        "message": "基于统一风格标准化统计，兼容风格字段与榜单名称推断",
    }

from fastapi import HTTPException

from app.services import AnalyticsService, DetailAiService

def analytics_call(action):
    with AnalyticsService() as service:
        return action(service)

def detail_ai_call(action):
    try:
        with DetailAiService() as service:
            return action(service)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

def items_response(items):
    return {"items": items, "count": len(items)}

def require_found(item, detail: str):
    if item is None:
        raise HTTPException(status_code=404, detail=detail)
    return item

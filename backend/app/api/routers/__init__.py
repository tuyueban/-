from app.api.routers.ai import router as ai_router
from app.api.routers.analytics import router as analytics_router
from app.api.routers.artists import router as artists_router
from app.api.routers.charts import router as charts_router
from app.api.routers.crawler import router as crawler_router
from app.api.routers.heat import router as heat_router
from app.api.routers.ops import router as ops_router
from app.api.routers.reports import router as reports_router
from app.api.routers.songs import router as songs_router

__all__ = [
    "analytics_router",
    "ai_router",
    "artists_router",
    "charts_router",
    "crawler_router",
    "heat_router",
    "ops_router",
    "reports_router",
    "songs_router",
]

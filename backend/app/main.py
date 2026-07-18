import logging
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from app.api.routers import (
    analytics_router,
    ai_router,
    artists_router,
    charts_router,
    crawler_router,
    explore_router,
    heat_router,
    ops_router,
    reports_router,
    song_alias_router,
    songs_router,
)
from app.core.config import settings
from app.db import init_db
from app.tasks import start_scheduler


FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
logger = logging.getLogger("app.request_timing")

app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:8001",
        "http://localhost:8001",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "null",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(charts_router, prefix=settings.api_prefix)
app.include_router(ai_router, prefix=settings.api_prefix)
app.include_router(songs_router, prefix=settings.api_prefix)
app.include_router(song_alias_router, prefix=settings.api_prefix)
app.include_router(artists_router, prefix=settings.api_prefix)
app.include_router(analytics_router, prefix=settings.api_prefix)
app.include_router(reports_router, prefix=settings.api_prefix)
app.include_router(ops_router, prefix=settings.api_prefix)
app.include_router(crawler_router, prefix=settings.api_prefix)
app.include_router(heat_router, prefix=settings.api_prefix)
app.include_router(explore_router, prefix=settings.api_prefix)


@app.middleware("http")
async def log_request_timing(request: Request, call_next):  # type: ignore[no-untyped-def]
    start = perf_counter()
    response = await call_next(request)
    duration_ms = (perf_counter() - start) * 1000
    logger.info(
        "%s %s -> %s %.1fms",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    response.headers["X-Process-Time-ms"] = f"{duration_ms:.1f}"
    return response


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    start_scheduler()
    for path in app.openapi().get("paths", {}):
        print(path, flush=True)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def frontend_index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/app.js")
def frontend_app_js() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "app.js", media_type="application/javascript")


@app.get("/api.js")
def frontend_api_js() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "api.js", media_type="application/javascript")


@app.get("/render.js")
def frontend_render_js() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "render.js", media_type="application/javascript")


@app.get("/utils.js")
def frontend_utils_js() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "utils.js", media_type="application/javascript")


@app.get("/dashboard-cache.js")
def frontend_dashboard_cache_js() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "dashboard-cache.js", media_type="application/javascript")


@app.get("/styles.css")
def frontend_styles() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "styles.css", media_type="text/css")

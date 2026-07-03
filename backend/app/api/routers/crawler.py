from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services import CrawlerService


router = APIRouter(prefix="/crawler", tags=["crawler"])


class CrawlRequest(BaseModel):
    platform: str = Field(default="all", description="all, netease, qq or kugou")
    chart_date: date | None = None
    persist: bool = True


@router.get("/platforms")
def list_platforms() -> dict[str, object]:
    return {"platforms": CrawlerService().platforms()}


@router.post("/run")
def run_crawler(payload: CrawlRequest) -> dict[str, object]:
    service = CrawlerService()
    try:
        if payload.platform == "all":
            return service.run_all(chart_date=payload.chart_date, persist=payload.persist)
        return service.run_platform(
            payload.platform,
            chart_date=payload.chart_date,
            persist=payload.persist,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/run-artists")
def run_artist_crawler(payload: CrawlRequest) -> dict[str, object]:
    service = CrawlerService()
    try:
        if payload.platform == "all":
            return service.run_artist_all(chart_date=payload.chart_date, persist=payload.persist)
        return service.run_artist_platform(
            payload.platform,
            chart_date=payload.chart_date,
            persist=payload.persist,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

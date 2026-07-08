from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.services.ai_analysis_service import AiAnalysisService
from app.services.crawler_service import CrawlerService
from app.services.heat_score_service import HeatScoreService


class PipelineService:
    def run_daily(self, target_date: date | None = None, crawl: bool = True, ai: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {"status": "success", "target_date": target_date.isoformat() if target_date else None}
        if crawl:
            result["crawler"] = CrawlerService().run_all(chart_date=target_date, persist=True)
        with HeatScoreService() as service:
            heat = service.compute_daily(score_date=target_date)
        result["heat"] = heat
        if heat.get("status") == "success":
            score_date = date.fromisoformat(str(heat["score_date"]))
            result["completion"] = CrawlerService().complete_analysis_songs(score_date=score_date)
        if ai and heat.get("status") == "success":
            with AiAnalysisService() as service:
                result["ai_analysis"] = service.generate_daily_summary(
                    analysis_date=date.fromisoformat(str(heat["score_date"])),
                    limit=20,
                )
        return result

    def run_backfill(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        days: int = 30,
        crawl: bool = True,
        ai: bool = False,
    ) -> dict[str, Any]:
        current_end = end_date or date.today()
        current_start = start_date or (current_end - timedelta(days=max(days, 1) - 1))
        if current_start > current_end:
            raise ValueError("start_date must be earlier than or equal to end_date")

        results: list[dict[str, Any]] = []
        day = current_start
        while day <= current_end:
            results.append(self.run_daily(target_date=day, crawl=crawl, ai=ai))
            day += timedelta(days=1)

        return {
            "status": "success",
            "start_date": current_start.isoformat(),
            "end_date": current_end.isoformat(),
            "days": len(results),
            "results": results,
        }

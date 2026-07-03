from apscheduler.schedulers.background import BackgroundScheduler

from app.core.config import settings
from app.services import PipelineService


scheduler = BackgroundScheduler(timezone=settings.scheduler_timezone)


def crawl_all_job() -> None:
    PipelineService().run_daily()


def start_scheduler() -> None:
    if not settings.scheduler_enabled or scheduler.running:
        return
    scheduler.add_job(
        crawl_all_job,
        trigger="cron",
        hour=settings.scheduler_hour,
        minute=settings.scheduler_minute,
        id="daily_song_crawler",
        replace_existing=True,
    )
    scheduler.start()

from dataclasses import dataclass
from functools import lru_cache
from os import getenv
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import URL


BACKEND_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_DIR / ".env")


def _bool_env(name: str, default: bool = False) -> bool:
    value = getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str = getenv("APP_NAME", "Music Hot Analysis API")
    api_prefix: str = getenv("API_PREFIX", "/api")

    database_url: str | None = getenv("DATABASE_URL")
    mysql_host: str = getenv("MYSQL_HOST", "127.0.0.1")
    mysql_port: int = int(getenv("MYSQL_PORT", "3306"))
    mysql_database: str = getenv("MYSQL_DATABASE", "music_hot_analysis")
    mysql_username: str = getenv("MYSQL_USERNAME", "root")
    mysql_password: str = getenv("MYSQL_PASSWORD", "")
    mysql_charset: str = getenv("MYSQL_CHARSET", "utf8mb4")

    crawler_timeout_seconds: float = float(getenv("CRAWLER_TIMEOUT_SECONDS", "20"))
    crawler_retry_times: int = int(getenv("CRAWLER_RETRY_TIMES", "2"))
    crawler_delay_seconds: float = float(getenv("CRAWLER_DELAY_SECONDS", "0.8"))
    crawler_top_n: int = int(getenv("CRAWLER_TOP_N", "100"))
    crawler_metric_concurrency: int = int(getenv("CRAWLER_METRIC_CONCURRENCY", "2"))
    crawler_metric_delay_seconds: float = float(getenv("CRAWLER_METRIC_DELAY_SECONDS", "0.8"))
    qq_cookie: str = getenv("QQ_COOKIE", "")
    qq_gtk: str = getenv("QQ_GTK", "")

    scheduler_enabled: bool = _bool_env("SCHEDULER_ENABLED", False)
    scheduler_hour: int = int(getenv("SCHEDULER_HOUR", "2"))
    scheduler_minute: int = int(getenv("SCHEDULER_MINUTE", "0"))
    scheduler_timezone: str = getenv("SCHEDULER_TIMEZONE", "Asia/Shanghai")

    ai_enabled: bool = _bool_env("AI_ENABLED", False)
    ai_api_base: str = getenv("AI_API_BASE", "https://api.openai.com/v1")
    ai_api_key: str = getenv("AI_API_KEY", "")
    ai_model: str = getenv("AI_MODEL", "gpt-4.1-mini")
    ai_timeout_seconds: float = float(getenv("AI_TIMEOUT_SECONDS", "30"))

    def database_dsn(self) -> str:
        if self.database_url:
            return self.database_url

        return URL.create(
            "mysql+pymysql",
            username=self.mysql_username,
            password=self.mysql_password,
            host=self.mysql_host,
            port=self.mysql_port,
            database=self.mysql_database,
            query={"charset": self.mysql_charset},
        ).render_as_string(hide_password=False)

    def mysql_server_dsn(self) -> str:
        return URL.create(
            "mysql+pymysql",
            username=self.mysql_username,
            password=self.mysql_password,
            host=self.mysql_host,
            port=self.mysql_port,
            query={"charset": self.mysql_charset},
        ).render_as_string(hide_password=False)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

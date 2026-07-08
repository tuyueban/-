from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(
    settings.database_dsn(),
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    from app.models import music  # noqa: F401

    ensure_database_exists()
    Base.metadata.create_all(bind=engine)
    ensure_schema_extensions()


def ensure_database_exists() -> None:
    if settings.database_url:
        return

    server_engine = create_engine(settings.mysql_server_dsn(), pool_pre_ping=True, future=True)
    database_name = settings.mysql_database.replace("`", "``")
    with server_engine.begin() as connection:
        connection.execute(
            text(
                f"CREATE DATABASE IF NOT EXISTS `{database_name}` "
                "DEFAULT CHARACTER SET utf8mb4 "
                "DEFAULT COLLATE utf8mb4_unicode_ci"
            )
        )
    server_engine.dispose()


def ensure_schema_extensions() -> None:
    platform_song_columns = {
        "platform_song_mid": "VARCHAR(100) NULL",
        "album_id": "VARCHAR(100) NULL",
        "album_mid": "VARCHAR(100) NULL",
        "song_hash": "VARCHAR(100) NULL",
        "extra_metadata": "TEXT NULL",
        "raw_song_name": "VARCHAR(200) NULL",
        "raw_artist_name": "VARCHAR(200) NULL",
        "version_type": "VARCHAR(50) NULL",
    }
    heat_score_columns = {
        "platform_count": "INT NULL",
        "platform_coverage_score": "DECIMAL(8,2) NULL",
        "dominant_platform": "VARCHAR(50) NULL",
    }
    song_metric_columns = {
        "play_count": "BIGINT NULL",
        "favorite_count": "BIGINT NULL",
    }
    artist_chart_columns = {
        "style_key": "VARCHAR(50) NULL",
        "style_name": "VARCHAR(100) NULL",
    }
    with engine.begin() as connection:
        _ensure_columns(connection, "PlatformSong", platform_song_columns)
        _ensure_columns(connection, "HeatScoreDaily", heat_score_columns)
        _ensure_columns(connection, "SongMetric", song_metric_columns)
        _ensure_columns(connection, "ArtistChart", artist_chart_columns)
        _ensure_column_types(
            connection,
            "Song",
            {
                "song_name": "VARCHAR(300) NOT NULL",
                "artist_name": "VARCHAR(150) NOT NULL",
                "album_name": "VARCHAR(300) NULL",
            },
        )
        _ensure_indexes(
            connection,
            {
                "ChartSong": {
                    "ix_chart_song_date_rank": "(`chart_date`, `rank`)",
                    "ix_chart_song_song_date": "(`song_id`, `chart_date`)",
                },
                "SongMetric": {
                    "ix_song_metric_date_song": "(`metric_date`, `song_id`)",
                },
                "HeatScoreDaily": {
                    "ix_heat_score_date_score": "(`score_date`, `heat_score`)",
                    "ix_heat_score_date_delta": "(`score_date`, `rank_delta`)",
                },
                "ArtistChartItem": {
                    "ix_artist_chart_item_date_artist": "(`chart_date`, `artist_id`)",
                },
            },
        )


def _ensure_columns(connection, table_name: str, columns: dict[str, str]) -> None:  # type: ignore[no-untyped-def]
    existing_columns = {
        row[0]
        for row in connection.execute(
            text(
                "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table_name"
            ),
            {"schema": settings.mysql_database, "table_name": table_name},
        )
    }
    for column_name, column_type in columns.items():
        if column_name not in existing_columns:
            connection.execute(text(f"ALTER TABLE `{table_name}` ADD COLUMN `{column_name}` {column_type}"))


def _ensure_column_types(connection, table_name: str, columns: dict[str, str]) -> None:  # type: ignore[no-untyped-def]
    for column_name, column_type in columns.items():
        connection.execute(text(f"ALTER TABLE `{table_name}` MODIFY COLUMN `{column_name}` {column_type}"))


def _ensure_indexes(connection, indexes: dict[str, dict[str, str]]) -> None:  # type: ignore[no-untyped-def]
    for table_name, table_indexes in indexes.items():
        existing_indexes = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT INDEX_NAME FROM information_schema.STATISTICS "
                    "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table_name"
                ),
                {"schema": settings.mysql_database, "table_name": table_name},
            )
        }
        for index_name, columns_sql in table_indexes.items():
            if index_name not in existing_indexes:
                connection.execute(text(f"CREATE INDEX `{index_name}` ON `{table_name}` {columns_sql}"))

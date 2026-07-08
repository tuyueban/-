from __future__ import annotations
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    UniqueConstraint,
    Unicode,
    UnicodeText,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from datetime import date, datetime

class MusicStyle(Base):
    __tablename__ = "MusicStyle"

    style_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    style_name: Mapped[str] = mapped_column(Unicode(50), nullable=False, unique=True)
    style_desc: Mapped[str | None] = mapped_column(Unicode(500))


class Song(Base):
    __tablename__ = "Song"
    __table_args__ = (
        UniqueConstraint("song_name", "artist_name", name="uq_song_name_artist"),
    )

    song_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    song_name: Mapped[str] = mapped_column(Unicode(300), nullable=False)
    artist_name: Mapped[str] = mapped_column(Unicode(150), nullable=False)
    album_name: Mapped[str | None] = mapped_column(Unicode(300))
    style_id: Mapped[int | None] = mapped_column(ForeignKey("MusicStyle.style_id"))
    is_instrumental: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))

    style: Mapped[MusicStyle | None] = relationship()
    platform_songs: Mapped[list["PlatformSong"]] = relationship(back_populates="song")
    chart_songs: Mapped[list["ChartSong"]] = relationship(back_populates="song")
    metrics: Mapped[list["SongMetric"]] = relationship(back_populates="song")


class PlatformSong(Base):
    __tablename__ = "PlatformSong"
    __table_args__ = (
        UniqueConstraint("platform", "platform_song_id", name="uq_platform_song"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    song_id: Mapped[int] = mapped_column(ForeignKey("Song.song_id"), nullable=False)
    platform: Mapped[str] = mapped_column(Unicode(50), nullable=False)
    platform_song_id: Mapped[str] = mapped_column(Unicode(100), nullable=False)
    platform_song_mid: Mapped[str | None] = mapped_column(Unicode(100))
    album_id: Mapped[str | None] = mapped_column(Unicode(100))
    album_mid: Mapped[str | None] = mapped_column(Unicode(100))
    song_hash: Mapped[str | None] = mapped_column(Unicode(100))
    extra_metadata: Mapped[str | None] = mapped_column(UnicodeText)
    raw_song_name: Mapped[str | None] = mapped_column(Unicode(200))
    raw_artist_name: Mapped[str | None] = mapped_column(Unicode(200))
    version_type: Mapped[str | None] = mapped_column(Unicode(50))
    song_url: Mapped[str | None] = mapped_column(Unicode(500))
    cover_url: Mapped[str | None] = mapped_column(Unicode(500))

    song: Mapped[Song] = relationship(back_populates="platform_songs")


class Chart(Base):
    __tablename__ = "Chart"
    __table_args__ = (
        UniqueConstraint("platform", "chart_name", name="uq_platform_chart"),
    )
    style_key: Mapped[str | None] = mapped_column(Unicode(50))
    style_name: Mapped[str | None] = mapped_column(Unicode(100))
    chart_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(Unicode(50), nullable=False)
    chart_name: Mapped[str] = mapped_column(Unicode(100), nullable=False)
    chart_type: Mapped[str | None] = mapped_column(Unicode(50))

    chart_songs: Mapped[list["ChartSong"]] = relationship(back_populates="chart")


class ChartSong(Base):
    __tablename__ = "ChartSong"
    __table_args__ = (
        UniqueConstraint("chart_id", "song_id", "chart_date", name="uq_chart_song_daily"),
        Index("ix_chart_song_date_rank", "chart_date", "rank"),
        Index("ix_chart_song_song_date", "song_id", "chart_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chart_id: Mapped[int] = mapped_column(ForeignKey("Chart.chart_id"), nullable=False)
    song_id: Mapped[int] = mapped_column(ForeignKey("Song.song_id"), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    rank_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    chart_date: Mapped[Date] = mapped_column(Date, nullable=False)
    collect_time: Mapped[DateTime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    chart: Mapped[Chart] = relationship(back_populates="chart_songs")
    song: Mapped[Song] = relationship(back_populates="chart_songs")


class SongMetric(Base):
    __tablename__ = "SongMetric"
    __table_args__ = (
        UniqueConstraint("song_id", "platform", "metric_date", name="uq_song_metric_daily"),
        Index("ix_song_metric_date_song", "metric_date", "song_id"),
    )

    metric_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    song_id: Mapped[int] = mapped_column(ForeignKey("Song.song_id"), nullable=False)
    platform: Mapped[str] = mapped_column(Unicode(50), nullable=False)
    platform_song_id: Mapped[str | None] = mapped_column(Unicode(100))
    play_count: Mapped[int | None] = mapped_column(BigInteger)
    favorite_count: Mapped[int | None] = mapped_column(BigInteger)
    comment_count: Mapped[int | None] = mapped_column(BigInteger)
    metric_date: Mapped[Date] = mapped_column(Date, nullable=False)
    collect_time: Mapped[DateTime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    metric_source: Mapped[str | None] = mapped_column(Unicode(500))
    is_success: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))
    fail_reason: Mapped[str | None] = mapped_column(Unicode(1000))

    song: Mapped[Song] = relationship(back_populates="metrics")


class HeatScoreDaily(Base):
    __tablename__ = "HeatScoreDaily"
    __table_args__ = (
        UniqueConstraint("song_id", "score_date", name="uq_heat_score_daily"),
        Index("ix_heat_score_date_score", "score_date", "heat_score"),
        Index("ix_heat_score_date_delta", "score_date", "rank_delta"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    song_id: Mapped[int] = mapped_column(ForeignKey("Song.song_id"), nullable=False)
    score_date: Mapped[Date] = mapped_column(Date, nullable=False)
    netease_score: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False, server_default=text("0"))
    qq_score: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False, server_default=text("0"))
    kugou_score: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False, server_default=text("0"))
    main_platform_score: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False, server_default=text("0"))
    heat_score: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False, server_default=text("0"))
    platform_count: Mapped[int | None] = mapped_column(Integer)
    platform_coverage_score: Mapped[float | None] = mapped_column(Numeric(8, 2))
    dominant_platform: Mapped[str | None] = mapped_column(Unicode(50))
    rank: Mapped[int | None] = mapped_column(Integer)
    rank_delta: Mapped[int | None] = mapped_column(Integer)
    trend_label: Mapped[str | None] = mapped_column(Unicode(50))
    created_at: Mapped[DateTime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[DateTime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    song: Mapped[Song] = relationship()


class AiHeatAnalysis(Base):
    __tablename__ = "AiHeatAnalysis"
    __table_args__ = (
        UniqueConstraint("analysis_date", "analysis_type", name="uq_ai_heat_analysis_daily"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analysis_date: Mapped[Date] = mapped_column(Date, nullable=False)
    analysis_type: Mapped[str] = mapped_column(Unicode(50), nullable=False)
    model_name: Mapped[str | None] = mapped_column(Unicode(100))
    prompt_version: Mapped[str] = mapped_column(Unicode(50), nullable=False, server_default=text("'v1'"))
    input_summary: Mapped[str | None] = mapped_column(UnicodeText)
    content: Mapped[str] = mapped_column(UnicodeText, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))


class Artist(Base):
    __tablename__ = "Artist"

    artist_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    artist_name: Mapped[str] = mapped_column(Unicode(100), nullable=False, unique=True)
    normalized_name: Mapped[str | None] = mapped_column(Unicode(150), unique=True)
    canonical_name: Mapped[str | None] = mapped_column(Unicode(100))
    avatar_url: Mapped[str | None] = mapped_column(Unicode(500))
    main_style: Mapped[str | None] = mapped_column(Unicode(50))


class SongArtist(Base):
    __tablename__ = "SongArtist"
    __table_args__ = (
        UniqueConstraint("song_id", "artist_id", name="uq_song_artist"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    song_id: Mapped[int] = mapped_column(ForeignKey("Song.song_id"), nullable=False)
    artist_id: Mapped[int] = mapped_column(ForeignKey("Artist.artist_id"), nullable=False)
    role: Mapped[str | None] = mapped_column(Unicode(30))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    song: Mapped["Song"] = relationship()
    artist: Mapped["Artist"] = relationship()


class ArtistChart(Base):
    __tablename__ = "ArtistChart"
    __table_args__ = (
        UniqueConstraint("platform", "chart_name", name="uq_platform_artist_chart"),
    )

    chart_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(Unicode(50), nullable=False)
    chart_name: Mapped[str] = mapped_column(Unicode(100), nullable=False)
    chart_type: Mapped[str | None] = mapped_column(Unicode(50))
    style_key: Mapped[str | None] = mapped_column(Unicode(50))
    style_name: Mapped[str | None] = mapped_column(Unicode(100))

    chart_items: Mapped[list["ArtistChartItem"]] = relationship(back_populates="chart")


class ArtistChartItem(Base):
    __tablename__ = "ArtistChartItem"
    __table_args__ = (
        UniqueConstraint("chart_id", "artist_id", "chart_date", name="uq_artist_chart_item"),
        Index("ix_artist_chart_item_date_artist", "chart_date", "artist_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chart_id: Mapped[int] = mapped_column(ForeignKey("ArtistChart.chart_id"), nullable=False)
    artist_id: Mapped[int] = mapped_column(ForeignKey("Artist.artist_id"), nullable=False)
    platform_artist_id: Mapped[str | None] = mapped_column(Unicode(100))
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    rank_score: Mapped[float | None] = mapped_column(Numeric(8, 2))
    chart_date: Mapped[date] = mapped_column(Date, nullable=False)
    collect_time: Mapped[datetime | None] = mapped_column(DateTime)
    artist_url: Mapped[str | None] = mapped_column(Unicode(500))
    extra_metadata: Mapped[str | None] = mapped_column(UnicodeText)

    chart: Mapped["ArtistChart"] = relationship(back_populates="chart_items")
    artist: Mapped["Artist"] = relationship()


class EtlLog(Base):
    __tablename__ = "EtlLog"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_name: Mapped[str] = mapped_column(Unicode(100), nullable=False)
    platform: Mapped[str | None] = mapped_column(Unicode(50))
    start_time: Mapped[DateTime] = mapped_column(DateTime, nullable=False)
    end_time: Mapped[DateTime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(Unicode(30), nullable=False)
    chart_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    metric_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    error_message: Mapped[str | None] = mapped_column(UnicodeText)

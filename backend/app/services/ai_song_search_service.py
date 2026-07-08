from __future__ import annotations

from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import HeatScoreDaily, PlatformSong, Song
from app.services.analytics_service import AnalyticsService
from app.services.style_service import normalize_style_intent


class AiSongSearchService:
    def __init__(self, db: Session | None = None) -> None:
        self.db = db or SessionLocal()
        self._owns_session = db is None

    def close(self) -> None:
        if self._owns_session:
            self.db.close()

    def __enter__(self) -> "AiSongSearchService":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        self.close()

    def search(self, query: str, limit: int = 5) -> dict[str, Any]:
        styles = normalize_style_intent(query)
        if not styles:
            return {"intent": "", "styles": [], "songs": []}

        latest_score_date = self.db.execute(select(func.max(HeatScoreDaily.score_date))).scalar_one_or_none()
        if latest_score_date is None:
            return {"intent": " / ".join(styles), "styles": styles, "songs": []}

        style_songs = self._style_song_map(styles)
        if not style_songs:
            return {"intent": " / ".join(styles), "styles": styles, "songs": []}

        rows = self.db.execute(
            select(HeatScoreDaily, Song)
            .join(Song, HeatScoreDaily.song_id == Song.song_id)
            .where(
                HeatScoreDaily.score_date == latest_score_date,
                Song.song_id.in_(style_songs.keys()),
            )
            .order_by(desc(HeatScoreDaily.heat_score))
            .limit(limit * 4)
        ).all()

        songs = []
        seen_song_ids: set[int] = set()
        for score, song in rows:
            if song.song_id in seen_song_ids:
                continue
            seen_song_ids.add(song.song_id)
            style_item = style_songs.get(song.song_id, {})
            songs.append(
                {
                    "song_id": song.song_id,
                    "song_name": song.song_name,
                    "artist_name": song.artist_name,
                    "album_name": song.album_name,
                    "cover_url": style_item.get("cover_url") or self._cover_for_song(song.song_id),
                    "style": style_item.get("style"),
                    "heat_score": _float(score.heat_score),
                    "rank": score.rank,
                    "score_date": score.score_date.isoformat(),
                    "charts": style_item.get("charts") or [],
                    "chart_name": style_item.get("chart_name"),
                }
            )
            if len(songs) >= limit:
                break

        return {
            "intent": " / ".join(styles),
            "styles": styles,
            "songs": songs,
        }

    def _style_song_map(self, styles: list[str]) -> dict[int, dict[str, Any]]:
        distribution = AnalyticsService(self.db).get_style_distribution(days=30, limit=500)
        style_set = set(styles)
        songs: dict[int, dict[str, Any]] = {}
        for bucket in distribution.get("items") or []:
            style = bucket.get("style") or bucket.get("style_name")
            if style not in style_set:
                continue
            for song in bucket.get("songs") or []:
                song_id = song.get("song_id")
                if not song_id:
                    continue
                item = songs.setdefault(
                    int(song_id),
                    {
                        "style": style,
                        "cover_url": song.get("cover_url"),
                        "charts": [],
                        "chart_name": None,
                    },
                )
                chart_name = song.get("chart_name")
                rank = song.get("rank")
                if chart_name:
                    chart = {
                        "chart_name": chart_name,
                        "rank": rank,
                        "chart_date": distribution.get("chart_date"),
                    }
                    if chart not in item["charts"]:
                        item["charts"].append(chart)
                    current = item.get("chart_name")
                    if not current or (rank is not None and rank < item.get("_best_rank", 999999)):
                        item["chart_name"] = chart_name
                        item["_best_rank"] = rank if rank is not None else 999999

        for item in songs.values():
            item.pop("_best_rank", None)
        return songs

    def _cover_for_song(self, song_id: int) -> str | None:
        return self.db.execute(
            select(PlatformSong.cover_url)
            .where(PlatformSong.song_id == song_id, PlatformSong.cover_url.is_not(None))
            .order_by(PlatformSong.id)
            .limit(1)
        ).scalar_one_or_none()


def _float(value: Any) -> float:
    return round(float(value or 0), 2)

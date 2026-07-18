from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import Chart, ChartSong, HeatScoreDaily, PlatformSong, Song, SongMetric


MAIN_PLATFORM_KEYS = {
    "网易云音乐": "netease_score",
    "QQ音乐": "qq_score",
    "酷狗音乐": "kugou_score",
}


HEAT_PLATFORM_WEIGHT = 0.55
HEAT_ENGAGEMENT_WEIGHT = 0.30
HEAT_COVERAGE_WEIGHT = 0.15


class HeatScoreService:
    def __init__(self, db: Session | None = None) -> None:
        self.db = db or SessionLocal()
        self._owns_session = db is None

    def close(self) -> None:
        if self._owns_session:
            self.db.close()

    def __enter__(self) -> "HeatScoreService":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        self.close()

    def latest_chart_date(self) -> date | None:
        return self.db.execute(select(func.max(ChartSong.chart_date))).scalar_one_or_none()

    def compute_daily(self, score_date: date | None = None, limit: int | None = None) -> dict[str, Any]:
        current_date = score_date or self.latest_chart_date()
        if current_date is None:
            return {"status": "empty", "message": "no chart data found"}

        try:
            chart_rows = self._load_chart_rows(current_date)
            if not chart_rows:
                return {"status": "empty", "score_date": current_date.isoformat(), "message": "no chart rows"}

            per_song: dict[int, dict[str, Any]] = {}
            for row in chart_rows:
                song = row[3]
                version_type = row[4]
                if song.is_instrumental or version_type == "instrumental":
                    continue
                bucket = per_song.setdefault(
                    row.song_id,
                    {
                        "song_id": row.song_id,
                        "platform_ranks": {},
                        "song": song,
                    },
                )
                platform_rows = bucket["platform_ranks"].setdefault(row.platform, [])
                platform_rows.append(float(row.rank_score or 0))

            metric_map = self._load_metric_map(set(per_song))
            max_collect_count = max((item["collect_count"] for item in metric_map.values()), default=0)
            max_comment_count = max((item["comment_count"] for item in metric_map.values()), default=0)

            results: list[dict[str, Any]] = []
            for song_id, item in per_song.items():
                platform_scores = self._calculate_platform_scores(item["platform_ranks"])
                metrics = metric_map.get(song_id, {"collect_count": 0, "comment_count": 0})
                score = _calculate_static_heat_score(
                    platform_scores=platform_scores,
                    collect_count=int(metrics.get("collect_count") or 0),
                    comment_count=int(metrics.get("comment_count") or 0),
                    max_collect_count=max_collect_count,
                    max_comment_count=max_comment_count,
                )
                dominant_platform = max(platform_scores, key=platform_scores.get)

                results.append(
                    {
                        "song_id": song_id,
                        "song": item["song"],
                        "netease_score": platform_scores["网易云音乐"],
                        "qq_score": platform_scores["QQ音乐"],
                        "kugou_score": platform_scores["酷狗音乐"],
                        "main_platform_score": score["platform_score"],
                        "heat_score": score["heat_score"],
                        "platform_count": score["platform_count"],
                        "platform_coverage_score": score["coverage_score"],
                        "engagement_score": score["engagement_score"],
                        "collect_score": score["collect_score"],
                        "comment_score": score["comment_score"],
                        "collect_count": metrics.get("collect_count", 0),
                        "comment_count": metrics.get("comment_count", 0),
                        "dominant_platform": dominant_platform,
                    }
                )

            results.sort(key=lambda item: item["heat_score"], reverse=True)
            if limit:
                results = results[:limit]

            for index, item in enumerate(results, start=1):
                item["rank"] = index
                item["rank_delta"] = None
                item["trend_label"] = "静态热度"
                self._upsert_heat_score(current_date, item)

            self.db.commit()
            return {
                "status": "success",
                "score_date": current_date.isoformat(),
                "computed_count": len(results),
                "top": [self._public_item(item) for item in results[:10]],
            }
        except Exception:
            self.db.rollback()
            raise

    def list_daily(self, score_date: date | None = None, limit: int = 50) -> list[dict[str, Any]]:
        current_date = score_date or self.db.execute(select(func.max(HeatScoreDaily.score_date))).scalar_one_or_none()
        if current_date is None:
            return []

        rows = self.db.execute(
            select(HeatScoreDaily, Song)
            .join(Song, HeatScoreDaily.song_id == Song.song_id)
            .where(HeatScoreDaily.score_date == current_date)
            .order_by(HeatScoreDaily.rank)
            .limit(limit)
        ).all()
        return [self._score_row_to_dict(score, song) for score, song in rows]

    def top_daily_summary(self, score_date: date | None = None, limit: int = 20) -> dict[str, Any]:
        rows = self.list_daily(score_date=score_date, limit=limit)
        current_date = rows[0]["score_date"] if rows else None
        return {
            "score_date": current_date,
            "top_songs": rows,
        }

    def _load_chart_rows(self, score_date: date) -> list[Any]:
        return self.db.execute(
            select(
                ChartSong.song_id,
                ChartSong.rank_score,
                Chart.platform,
                Song,
                PlatformSong.version_type,
            )
            .join(Chart, ChartSong.chart_id == Chart.chart_id)
            .join(Song, ChartSong.song_id == Song.song_id)
            .outerjoin(
                PlatformSong,
                and_(PlatformSong.song_id == Song.song_id, PlatformSong.platform == Chart.platform),
            )
            .where(ChartSong.chart_date == score_date)
        ).all()

    def _load_metric_map(self, song_ids: set[int]) -> dict[int, dict[str, int]]:
        if not song_ids:
            return {}
        rows = self.db.execute(
            select(
                SongMetric.song_id,
                func.sum(func.coalesce(SongMetric.collect_count, 0)).label("collect_count"),
                func.sum(func.coalesce(SongMetric.comment_count, 0)).label("comment_count"),
            )
            .where(SongMetric.song_id.in_(song_ids))
            .group_by(SongMetric.song_id)
        ).all()
        return {
            int(row.song_id): {
                "collect_count": int(row.collect_count or 0),
                "comment_count": int(row.comment_count or 0),
            }
            for row in rows
        }

    def _calculate_platform_scores(
        self,
        platform_ranks: dict[str, list[float]],
    ) -> dict[str, float]:
        scores = {platform: 0.0 for platform in MAIN_PLATFORM_KEYS}
        for platform in scores:
            rank_scores = platform_ranks.get(platform, [])
            scores[platform] = max(rank_scores) if rank_scores else 0
        return scores

    @staticmethod
    def _trend_label(rank_delta: int | None, heat_score: float) -> str:
        if rank_delta is None:
            return "新上榜"
        if rank_delta >= 10 or heat_score >= 85:
            return "爆发上升"
        if rank_delta >= 3:
            return "上升"
        if rank_delta <= -10:
            return "明显回落"
        if rank_delta <= -3:
            return "回落"
        return "稳定"

    def _upsert_heat_score(self, score_date: date, item: dict[str, Any]) -> HeatScoreDaily:
        existing = self.db.execute(
            select(HeatScoreDaily).where(
                HeatScoreDaily.song_id == item["song_id"],
                HeatScoreDaily.score_date == score_date,
            )
        ).scalar_one_or_none()
        values = {
            "netease_score": _round(item["netease_score"]),
            "qq_score": _round(item["qq_score"]),
            "kugou_score": _round(item["kugou_score"]),
            "main_platform_score": _round(item["main_platform_score"]),
            "heat_score": _round(item["heat_score"]),
            "platform_count": item.get("platform_count"),
            "platform_coverage_score": _round(item.get("platform_coverage_score")),
            "dominant_platform": item.get("dominant_platform"),
            "rank": item["rank"],
            "rank_delta": item["rank_delta"],
            "trend_label": item["trend_label"],
            "updated_at": datetime.now(),
        }
        if existing:
            for key, value in values.items():
                setattr(existing, key, value)
            return existing

        row = HeatScoreDaily(song_id=item["song_id"], score_date=score_date, **values)
        self.db.add(row)
        self.db.flush()
        return row

    @staticmethod
    def _public_item(item: dict[str, Any]) -> dict[str, Any]:
        song = item["song"]
        return {
            "rank": item["rank"],
            "song_id": item["song_id"],
            "song_name": song.song_name,
            "artist_name": song.artist_name,
            "heat_score": _round(item["heat_score"]),
            "main_platform_score": _round(item["main_platform_score"]),
            "platform_count": item.get("platform_count", 0),
            "platform_coverage_score": _round(item.get("platform_coverage_score")),
            "dominant_platform": item.get("dominant_platform"),
            "trend_label": item["trend_label"],
            "engagement_score": _round(item.get("engagement_score")),
            "collect_score": _round(item.get("collect_score")),
            "comment_score": _round(item.get("comment_score")),
            "collect_count": int(item.get("collect_count") or 0),
            "comment_count": int(item.get("comment_count") or 0),
        }

    @staticmethod
    def _score_row_to_dict(score: HeatScoreDaily, song: Song) -> dict[str, Any]:
        return {
            "score_date": score.score_date.isoformat(),
            "rank": score.rank,
            "rank_delta": score.rank_delta,
            "trend_label": score.trend_label,
            "song_id": song.song_id,
            "song_name": song.song_name,
            "artist_name": song.artist_name,
            "album_name": song.album_name,
            "heat_score": float(score.heat_score),
            "main_platform_score": float(score.main_platform_score),
            "netease_score": float(score.netease_score),
            "qq_score": float(score.qq_score),
            "kugou_score": float(score.kugou_score),
            "platform_count": score.platform_count if score.platform_count is not None else _platform_count(score),
            "platform_coverage_score": float(score.platform_coverage_score or (_platform_count(score) / 3 * 100)),
            "dominant_platform": score.dominant_platform or _dominant_platform(score),
        }


def _calculate_static_heat_score(
    *,
    platform_scores: dict[str, float],
    collect_count: int,
    comment_count: int,
    max_collect_count: int,
    max_comment_count: int,
) -> dict[str, float | int]:
    platform_values = [_normalize_score(value) for value in platform_scores.values() if float(value or 0) > 0]
    platform_count = min(len(platform_values), 3)
    platform_score = sum(platform_values) / len(platform_values) if platform_values else 0.0
    collect_score = _normalize_count(collect_count, max_collect_count)
    comment_score = _normalize_count(comment_count, max_comment_count)
    engagement_score = collect_score * 0.6 + comment_score * 0.4
    coverage_score = platform_count / 3 * 100
    heat_score = (
        platform_score * HEAT_PLATFORM_WEIGHT
        + engagement_score * HEAT_ENGAGEMENT_WEIGHT
        + coverage_score * HEAT_COVERAGE_WEIGHT
    )
    return {
        "heat_score": _round(heat_score),
        "platform_score": _round(platform_score),
        "engagement_score": _round(engagement_score),
        "coverage_score": _round(coverage_score),
        "collect_score": _round(collect_score),
        "comment_score": _round(comment_score),
        "platform_count": platform_count,
    }


def _normalize_count(value: int | float | None, max_value: int | float | None) -> float:
    if not value or not max_value or float(max_value) <= 0:
        return 0.0
    return _normalize_score(float(value) / float(max_value) * 100)


def _normalize_score(value: int | float | None) -> float:
    return max(0.0, min(100.0, float(value or 0)))


def _round(value: float) -> float:
    return round(_normalize_score(value), 2)


def _platform_count(score: HeatScoreDaily) -> int:
    return sum(
        1
        for value in (score.netease_score, score.qq_score, score.kugou_score)
        if float(value or 0) > 0
    )


def _dominant_platform(score: HeatScoreDaily) -> str | None:
    values = {
        "网易云音乐": float(score.netease_score or 0),
        "QQ音乐": float(score.qq_score or 0),
        "酷狗音乐": float(score.kugou_score or 0),
    }
    platform = max(values, key=values.get)
    return platform if values[platform] > 0 else None


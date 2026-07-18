from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import (
    AiHeatAnalysis,
    Artist,
    ArtistChart,
    ArtistChartItem,
    Chart,
    ChartSong,
    EtlLog,
    HeatScoreDaily,
    PlatformSong,
    Song,
    SongArtist,
    SongMetric,
)
from app.crawlers.utils import canonical_artist_name, canonical_artist_key
from app.services.cache import TtlCache
from app.services.song_matcher import (
    artist_display_names,
    normalize_artists,
    normalize_song_title,
    should_merge_songs,
    song_identity_key,
)
from app.services.style_service import ensure_core_styles_visible, normalize_style_name


logger = logging.getLogger(__name__)
HOME_DASHBOARD_CACHE: TtlCache[dict[str, Any]] = TtlCache(ttl_seconds=180, max_size=24)

class AnalyticsService:
    def __init__(self, db: Session | None = None) -> None:
        self.db = db or SessionLocal()
        self._owns_session = db is None
        self._cover_cache: dict[int, str | None] = {}
        self._artist_avatar_cache: dict[str, str | None] = {}
        self._artist_names_cache: dict[int, list[str]] = {}
        self._primary_artist_cache: dict[int, str | None] = {}

    def rising_result(self, score_date: date | None = None, limit: int = 50) -> dict[str, Any]:
        current_date = score_date or self.latest_score_date()
        if current_date is None:
            return {
                "items": [],
                "count": 0,
                "status": "empty",
                "message": "暂无热度数据",
            }

        previous_date = self.db.execute(
            select(func.max(HeatScoreDaily.score_date)).where(HeatScoreDaily.score_date < current_date)
        ).scalar_one_or_none()

        if previous_date is None:
            return {
                "items": [],
                "count": 0,
                "status": "insufficient_history",
                "message": "暂无飙升数据，需至少连续采集 2 天后生成",
            }

        items = self.rising(score_date=current_date, limit=limit)

        return {
            "items": items,
            "count": len(items),
            "status": "success",
            "message": "",
        }

    def get_style_distribution(self, chart_date: date | None = None, days: int = 30, limit: int = 50) -> dict[str, Any]:
        current_date = chart_date or self.latest_chart_date()
        if current_date is None:
            return {
                "chart_date": None,
                "days": days,
                "total_count": 0,
                "total_canonical_songs": 0,
                "classified_song_count": 0,
                "unclassified_song_count": 0,
                "items": [],
                "debug": [],
                "unclassified_style_diagnostics": [],
            }
        start_date = current_date - timedelta(days=max(days, 1) - 1)

        rows = self.db.execute(
            select(Chart, ChartSong, Song)
            .join(ChartSong, ChartSong.chart_id == Chart.chart_id)
            .join(Song, ChartSong.song_id == Song.song_id)
            .where(ChartSong.chart_date.between(start_date, current_date))
            .order_by(desc(ChartSong.chart_date), Chart.platform, ChartSong.rank)
        ).all()

        if not rows:
            return {
                "chart_date": current_date.isoformat(),
                "days": days,
                "total_count": 0,
                "total_canonical_songs": 0,
                "classified_song_count": 0,
                "unclassified_song_count": 0,
                "items": [],
                "debug": [],
                "unclassified_style_diagnostics": [],
            }

        buckets: dict[str, dict[str, Any]] = {}
        debug_counts: dict[tuple[str, str | None], int] = {}
        all_song_keys: set[str] = set()
        classified_song_styles: dict[str, str] = {}
        unclassified_diagnostics: dict[str, dict[str, Any]] = {}

        for chart, chart_song, song in rows:
            song_key = _song_identity_key_for_song(song)
            all_song_keys.add(song_key)
            raw_style, style_name = _style_for_song_chart(song, chart)
            debug_counts[(raw_style, style_name)] = debug_counts.get((raw_style, style_name), 0) + 1

            if not style_name:
                if song_key in classified_song_styles:
                    continue
                unclassified_diagnostics.setdefault(
                    song_key,
                    {
                        "song_name": song.song_name,
                        "artist_name": song.artist_name,
                        "chart_name": chart.chart_name,
                        "chart_type": chart.chart_type,
                        "raw_style": raw_style,
                    },
                )
                continue

            if song_key in classified_song_styles and classified_song_styles[song_key] != style_name:
                continue

            classified_song_styles.setdefault(song_key, style_name)
            unclassified_diagnostics.pop(song_key, None)
            bucket = buckets.setdefault(
                style_name,
                {
                    "style_key": style_name,
                    "style": style_name,
                    "style_name": style_name,
                    "raw_styles": set(),
                    "platforms": set(),
                    "songs": [],
                    "song_keys": set(),
                },
            )

            bucket["raw_styles"].add(raw_style)
            bucket["platforms"].add(chart.platform)

            if song_key not in bucket["song_keys"]:
                bucket["song_keys"].add(song_key)
                bucket["songs"].append(
                    {
                        "song_id": song.song_id,
                        "song_name": song.song_name,
                        "artist_name": song.artist_name,
                        "cover_url": self._cover_for_song(song.song_id),
                        "rank": chart_song.rank,
                        "rank_score": _float(chart_song.rank_score),
                        "platform": chart.platform,
                        "chart_name": chart.chart_name,
                        "style": style_name,
                        "raw_style": raw_style,
                    }
                )

        result = []
        for bucket in buckets.values():
            songs = sorted(bucket["songs"], key=lambda item: item["rank"])[:limit]
            count = len(bucket["song_keys"])
            result.append(
                {
                    "style_key": bucket["style_key"],
                    "style": bucket["style"],
                    "style_name": bucket["style_name"],
                    "raw_styles": sorted(bucket["raw_styles"]),
                    "platforms": sorted(bucket["platforms"]),
                    "platform_count": len(bucket["platforms"]),
                    "song_count": count,
                    "count": count,
                    "songs": songs,
                    "top_songs": songs[:3],
                }
            )

        classified_song_count = len(classified_song_styles)
        unclassified_song_count = max(len(all_song_keys) - classified_song_count, 0)
        denominator = classified_song_count or 1
        for item in result:
            item["percentage"] = round(int(item["count"]) / denominator * 100, 2)

        result = ensure_core_styles_visible(result, limit=limit)
        debug = [
            {"raw_style": raw_style, "normalized_style": normalized_style, "count": count}
            for (raw_style, normalized_style), count in sorted(
                debug_counts.items(),
                key=lambda item: (-item[1], item[0][1] or "", item[0][0] or ""),
            )
        ]
        logger.debug("Style distribution debug: %s", debug)
        if unclassified_song_count:
            logger.debug("Unclassified style diagnostics: %s", list(unclassified_diagnostics.values())[:30])
        if not any(item["style"] == "流行" and int(item["count"]) > 0 for item in result):
            logger.debug("未从当前数据中识别到流行风格，请检查 chart_name / genre 映射。")

        return {
            "chart_date": current_date.isoformat(),
            "days": days,
            "total_count": classified_song_count,
            "total_canonical_songs": len(all_song_keys),
            "classified_song_count": classified_song_count,
            "unclassified_song_count": unclassified_song_count,
            "items": result[:limit],
            "debug": debug,
            "unclassified_style_diagnostics": list(unclassified_diagnostics.values())[:50],
        }

    def style_buckets(self, chart_date: date | None = None, limit: int = 50) -> list[dict[str, Any]]:
        return self.get_style_distribution(chart_date=chart_date, days=30, limit=limit)["items"]

    def close(self) -> None:
        if self._owns_session:
            self.db.close()

    def __enter__(self) -> "AnalyticsService":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        self.close()

    def latest_score_date(self) -> date | None:
        return self.db.execute(select(func.max(HeatScoreDaily.score_date))).scalar_one_or_none()

    def latest_chart_date(self) -> date | None:
        return self.db.execute(select(func.max(ChartSong.chart_date))).scalar_one_or_none()

    def latest_artist_chart_date(self) -> date | None:
        return self.db.execute(select(func.max(ArtistChartItem.chart_date))).scalar_one_or_none()

    def dashboard(self, target_date: date | None = None) -> dict[str, Any]:
        score_date = target_date or self.latest_score_date()
        chart_date = target_date or self.latest_chart_date()
        latest_report = self.latest_report(score_date) if score_date else None

        return {
            "score_date": score_date.isoformat() if score_date else None,
            "chart_date": chart_date.isoformat() if chart_date else None,
            "cards": {
                "songs": self.db.execute(select(func.count()).select_from(Song)).scalar_one(),
                "charts": self.db.execute(select(func.count()).select_from(Chart)).scalar_one(),
                "chart_records": self.db.execute(select(func.count()).select_from(ChartSong)).scalar_one(),
                "metric_records": self.db.execute(select(func.count()).select_from(SongMetric)).scalar_one(),
            },
            "daily_hot_top10": self.daily_hot(score_date, limit=10) if score_date else [],
            "rising_top10": [],
            "weekly_hot_top10": [],
            "new_song_top10": [],
            "interaction_heat_top10": [],
            "artist_top10": [],
            "platform_records": [],
            "latest_report": latest_report,
        }

    def home_dashboard(self, target_date: date | None = None, limit: int = 50) -> dict[str, Any]:
        score_date = target_date or self.latest_score_date()
        chart_date = target_date or self.latest_chart_date()
        cache_key = (
            score_date.isoformat() if score_date else None,
            chart_date.isoformat() if chart_date else None,
            limit,
        )
        cached = HOME_DASHBOARD_CACHE.get(cache_key)
        if cached is not None:
            return cached

        dashboard = self.dashboard(target_date=target_date)
        daily = self.daily_hot(score_date=score_date, limit=limit) if score_date else []
        weekly = self.weekly_hot(end_date=score_date, limit=limit) if score_date else []
        artists = self.artist_rank(score_date=score_date, limit=limit) if score_date else []
        rising = self.rising_result(score_date=score_date, limit=limit)
        new_songs = self.new_songs(chart_date=chart_date, limit=limit) if chart_date else []
        interaction_heat = self.interaction_heat(metric_date=chart_date, limit=limit) if chart_date else []
        style_buckets = self.get_style_distribution(chart_date=chart_date, days=30, limit=limit) if chart_date else {
            "chart_date": None,
            "days": 30,
            "total_count": 0,
            "total_canonical_songs": 0,
            "classified_song_count": 0,
            "unclassified_song_count": 0,
            "items": [],
            "debug": [],
            "unclassified_style_diagnostics": [],
        }
        payload = {
            "dashboard": dashboard,
            "daily": {"items": daily, "count": len(daily)},
            "weekly": {"items": weekly, "count": len(weekly), "message": _weekly_message(weekly)},
            "artists": {"items": artists, "count": len(artists)},
            "rising": rising,
            "newSongs": {"items": new_songs, "count": len(new_songs)},
            "interactionHeat": {"items": interaction_heat, "count": len(interaction_heat)},
            "styleBuckets": {
                **style_buckets,
                "count": len(style_buckets.get("items") or []),
                "message": "基于统一风格标准化统计，兼容风格字段与榜单名称推断",
            },
        }
        return HOME_DASHBOARD_CACHE.set(cache_key, payload)

    def daily_hot(self, score_date: date | None = None, limit: int = 50) -> list[dict[str, Any]]:
        current_date = score_date or self.latest_score_date()
        if current_date is None:
            return []
        rows = self.db.execute(
            select(HeatScoreDaily, Song)
            .join(Song, HeatScoreDaily.song_id == Song.song_id)
            .where(HeatScoreDaily.score_date == current_date)
            .order_by(desc(HeatScoreDaily.heat_score))
            .limit(limit)
        ).all()
        self._prime_song_display_cache([song for _score, song in rows])
        return _rerank([self._heat_row(score, song) for score, song in rows])

    def weekly_hot(self, end_date: date | None = None, limit: int = 50) -> list[dict[str, Any]]:
        current_date = end_date or self.latest_score_date()
        if current_date is None:
            return []
        start_date = current_date - timedelta(days=6)
        rows = self.db.execute(
            select(
                Song.song_id,
                Song.song_name,
                Song.artist_name,
                Song.album_name,
                func.avg(HeatScoreDaily.heat_score).label("avg_score"),
                func.max(HeatScoreDaily.heat_score).label("peak_score"),
                func.count(HeatScoreDaily.id).label("available_days"),
            )
            .join(Song, HeatScoreDaily.song_id == Song.song_id)
            .where(HeatScoreDaily.score_date.between(start_date, current_date))
            .group_by(Song.song_id, Song.song_name, Song.artist_name, Song.album_name)
            .order_by(desc("avg_score"))
            .limit(limit * 3)
        ).all()
        self._prime_song_cover_cache([row.song_id for row in rows])
        self._prime_artist_avatar_cache({row.artist_name for row in rows if row.artist_name})
        items = [
            {
                "rank": index,
                "song_id": row.song_id,
                "song_name": row.song_name,
                "artist_name": row.artist_name,
                "album_name": row.album_name,
                "cover_url": self._cover_for_song(row.song_id),
                "artist_avatar_url": self._artist_avatar_for_name(row.artist_name),
                "avg_heat_score": _float(row.avg_score),
                "heat_score": _float(row.avg_score),
                "peak_heat_score": _float(row.peak_score),
                "available_days": int(row.available_days),
                "start_date": start_date.isoformat(),
                "end_date": current_date.isoformat(),
                "period_type": "weekly",
                "is_formal_weekly": int(row.available_days) >= 7,
                "period_message": (
                    "正式周榜"
                ),
            }
            for index, row in enumerate(rows, start=1)
        ]
        items = _merge_song_items(items)
        items.sort(key=lambda item: (item.get("adjustedHeat") or item.get("adjusted_heat") or 0), reverse=True)
        return _rerank(items)[:limit]

    def monthly_hot(self, end_date: date | None = None, limit: int = 50) -> list[dict[str, Any]]:
        return self.weekly_hot(end_date=end_date, limit=limit)

    def rising(self, score_date: date | None = None, limit: int = 50) -> list[dict[str, Any]]:
        current_date = score_date or self.latest_score_date()
        if current_date is None:
            return []
        previous_date = self.db.execute(
            select(func.max(HeatScoreDaily.score_date)).where(HeatScoreDaily.score_date < current_date)
        ).scalar_one_or_none()
        if previous_date is None:
            return []
        rows = self.db.execute(
            select(HeatScoreDaily, Song)
            .join(Song, HeatScoreDaily.song_id == Song.song_id)
            .where(HeatScoreDaily.score_date == current_date)
            .order_by(desc(HeatScoreDaily.rank_delta), desc(HeatScoreDaily.heat_score))
            .limit(limit * 3)
        ).all()
        self._prime_song_display_cache([song for _score, song in rows])
        items = [self._heat_row(score, song) for score, song in rows]
        return _rerank(_merge_song_items(items))[:limit]

    def new_songs(self, chart_date: date | None = None, limit: int = 50) -> list[dict[str, Any]]:
        current_date = chart_date or self.latest_chart_date()
        if current_date is None:
            return []
        return self._merged_chart_songs_by_type(current_date, "new", limit)

    def interaction_heat(self, metric_date: date | None = None, limit: int = 50) -> list[dict[str, Any]]:
        current_date = metric_date or self.db.execute(select(func.max(SongMetric.metric_date))).scalar_one_or_none()
        if current_date is None:
            return []
        rows = self.db.execute(
            select(
                Song,
                func.sum(func.coalesce(SongMetric.comment_count, 0)).label("comment_count"),
                func.count(func.distinct(SongMetric.platform)).label("platform_count"),
                func.count(SongMetric.comment_count).label("comment_success_count"),
            )
            .join(SongMetric, SongMetric.song_id == Song.song_id)
            .where(SongMetric.metric_date == current_date)
            .group_by(Song.song_id, Song.song_name, Song.artist_name, Song.album_name)
        ).all()

        max_comment = max((int(row.comment_count or 0) for row in rows), default=0)
        scored_rows = []
        for song, comment_count, platform_count, comment_success_count in rows:
            completeness_score = _score_norm(comment_success_count, max(int(platform_count or 0), 1))
            interaction_score = (
                _score_norm(comment_count, max_comment) * 0.80
                + _score_norm(platform_count, 3) * 0.20
            )
            scored_rows.append((song, int(comment_count or 0), int(platform_count or 0), completeness_score, interaction_score))
        scored_rows.sort(key=lambda row: row[4], reverse=True)
        self._prime_song_display_cache([song for song, *_rest in scored_rows[:limit]])
        items = [
            {
                "rank": index,
                **self._song_display_fields(song, avatar_artist_name=song.artist_name),
                "comment_count": comment_count,
                "platform_count": platform_count,
                "data_completeness_score": _float(completeness_score),
                "interaction_heat_score": _float(interaction_score),
                "metric_date": current_date.isoformat(),
            }
            for index, (song, comment_count, platform_count, completeness_score, interaction_score) in enumerate(scored_rows, start=1)
        ]
        return _rerank(_merge_song_items(items))[:limit]

    def chart_songs(
        self,
        chart_date: date | None = None,
        platform: str | None = None,
        chart_name: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        current_date = chart_date or self.latest_chart_date()
        if current_date is None:
            return []
        query = (
            select(ChartSong, Chart, Song)
            .join(Chart, ChartSong.chart_id == Chart.chart_id)
            .join(Song, ChartSong.song_id == Song.song_id)
            .where(ChartSong.chart_date == current_date)
        )
        if platform:
            query = query.where(Chart.platform == platform)
        if chart_name:
            query = query.where(Chart.chart_name == chart_name)
        rows = self.db.execute(query.order_by(Chart.platform, Chart.chart_name, ChartSong.rank).limit(limit)).all()
        return [self._chart_row(chart_song, chart, song) for chart_song, chart, song in rows]

    def song_detail(self, song_id: int) -> dict[str, Any] | None:
        song = self.db.get(Song, song_id)
        if song is None:
            return None
        latest_score = self.db.execute(
            select(HeatScoreDaily)
            .where(HeatScoreDaily.song_id == song_id)
            .order_by(desc(HeatScoreDaily.score_date))
            .limit(1)
        ).scalar_one_or_none()
        platform_rows = self.db.execute(
            select(PlatformSong).where(PlatformSong.song_id == song_id).order_by(PlatformSong.platform)
        ).scalars().all()
        chart_rows = self.db.execute(
            select(ChartSong, Chart)
            .join(Chart, ChartSong.chart_id == Chart.chart_id)
            .where(ChartSong.song_id == song_id)
            .order_by(desc(ChartSong.chart_date), Chart.platform, Chart.chart_name)
            .limit(30)
        ).all()
        metric_rows = self.db.execute(
            select(SongMetric)
            .where(SongMetric.song_id == song_id)
            .order_by(desc(SongMetric.metric_date), SongMetric.platform)
            .limit(30)
        ).scalars().all()
        trend_rows = self.db.execute(
            select(HeatScoreDaily)
            .where(HeatScoreDaily.song_id == song_id)
            .order_by(HeatScoreDaily.score_date)
            .limit(60)
        ).scalars().all()

        return {
            "song": {
                "song_id": song.song_id,
                "song_name": song.song_name,
                "artist_name": song.artist_name,
                "display_artist_name": song.artist_name,
                "primary_artist_name": self._primary_artist_name_for_song(song.song_id) or song.artist_name,
                "album_name": song.album_name,
                "cover_url": self._cover_for_song(song.song_id),
                "artist_avatar_url": self._artist_avatar_for_name(
                    self._primary_artist_name_for_song(song.song_id) or song.artist_name
                ),
                "artist_names": self._artist_names_for_song(song.song_id),
                "is_instrumental": bool(song.is_instrumental),
            },
            "latest_score": self._heat_score_only(latest_score) if latest_score else None,
            "platform_links": [
                {
                    "platform": row.platform,
                    "platform_song_id": row.platform_song_id,
                    "song_url": row.song_url,
                    "cover_url": row.cover_url,
                }
                for row in platform_rows
            ],
            "chart_records": [
                {
                    "platform": chart.platform,
                    "chart_name": chart.chart_name,
                    "chart_type": chart.chart_type,
                    "rank": chart_song.rank,
                    "rank_score": _float(chart_song.rank_score),
                    "chart_date": chart_song.chart_date.isoformat(),
                }
                for chart_song, chart in chart_rows
            ],
            "metrics": [
                {
                    "platform": metric.platform,
                    "comment_count": metric.comment_count,
                    "collect_count": int(metric.collect_count or 0),
                    "metric_date": metric.metric_date.isoformat(),
                    "is_success": bool(metric.is_success),
                    "fail_reason": metric.fail_reason,
                }
                for metric in metric_rows
            ],
            "trend": [self._heat_score_only(row) for row in trend_rows],
        }

    def song_collect(self, song_id: int, platform: str = "netease") -> dict[str, Any] | None:
        song = self.db.get(Song, song_id)
        if song is None:
            return None
        platform_code = _platform_code(platform)
        metrics = self.db.execute(
            select(SongMetric)
            .where(SongMetric.song_id == song_id)
            .order_by(desc(SongMetric.metric_date), desc(SongMetric.collect_time))
        ).scalars().all()
        selected = next((metric for metric in metrics if _platform_code(metric.platform) == platform_code), None)
        selected = selected or (metrics[0] if metrics else None)
        return {
            "song": song.song_name,
            "artist": song.artist_name,
            "platform": selected.platform if selected else _platform_display_name(platform_code),
            "collect_count": int(selected.collect_count or 0) if selected else 0,
            "update_time": selected.collect_time.isoformat(timespec="seconds") if selected else None,
        }

    def search_songs(self, keyword: str, limit: int = 20) -> list[dict[str, Any]]:
        pattern = f"%{keyword}%"
        rows = self.db.execute(
            select(Song)
            .where(or_(Song.song_name.like(pattern), Song.artist_name.like(pattern)))
            .order_by(Song.song_name)
            .limit(limit)
        ).scalars().all()
        items = [
            {
                "song_id": row.song_id,
                "song_name": row.song_name,
                "artist_name": row.artist_name,
                "artist_names": self._artist_names_for_song(row.song_id) or [row.artist_name],
                "album_name": row.album_name,
                "cover_url": self._cover_for_song(row.song_id),
                "artist_avatar_url": self._artist_avatar_for_name(row.artist_name),
            }
            for row in rows
        ]
        return _merge_song_items(items)[:limit]

    def artist_rank(self, score_date: date | None = None, limit: int = 50) -> list[dict[str, Any]]:
        current_date = score_date or self.latest_artist_chart_date()
        if current_date is None:
            return []

        rows = self.db.execute(
            select(Artist, ArtistChartItem, ArtistChart)
            .join(ArtistChartItem, ArtistChartItem.artist_id == Artist.artist_id)
            .join(ArtistChart, ArtistChartItem.chart_id == ArtistChart.chart_id)
            .where(ArtistChartItem.chart_date == current_date)
        ).all()

        buckets: dict[str, dict[str, Any]] = {}

        for artist, chart_item, chart in rows:
            canonical_name = artist.canonical_name or canonical_artist_name(artist.artist_name)
            canonical_key = artist.normalized_name or canonical_artist_key(artist.artist_name)

            if not canonical_name or not canonical_key:
                continue

            bucket = buckets.setdefault(
                canonical_key,
                {
                    "artist_name": canonical_name,
                    "artist_avatar_url": artist.avatar_url,
                    "rank_scores": [],
                    "best_artist_chart_rank": None,
                    "source_platforms": set(),
                },
            )

            score = float(chart_item.rank_score or 0)
            bucket["rank_scores"].append(score)
            bucket["source_platforms"].add(chart.platform)

            if bucket["best_artist_chart_rank"] is None:
                bucket["best_artist_chart_rank"] = chart_item.rank
            else:
                bucket["best_artist_chart_rank"] = min(bucket["best_artist_chart_rank"], chart_item.rank)

            if not bucket["artist_avatar_url"] and artist.avatar_url:
                bucket["artist_avatar_url"] = artist.avatar_url

        scored_rows: list[dict[str, Any]] = []

        for bucket in buckets.values():
            rank_scores = bucket["rank_scores"]
            if not rank_scores:
                continue

            best_artist_chart_score = max(rank_scores)
            avg_artist_chart_score = sum(rank_scores) / len(rank_scores)
            source_platforms = sorted(bucket["source_platforms"])
            platform_count = len(source_platforms)
            platform_coverage_score = round(min(platform_count, 3) / 3 * 100, 2)

            artist_heat_score = round(
                best_artist_chart_score * 0.40
                + avg_artist_chart_score * 0.40
                + platform_coverage_score * 0.20,
                2,
            )

            scored_rows.append(
                {
                    "artist_name": bucket["artist_name"],
                    "artist_avatar_url": bucket["artist_avatar_url"],
                    "best_artist_chart_score": round(best_artist_chart_score, 2),
                    "avg_artist_chart_score": round(avg_artist_chart_score, 2),
                    "best_artist_chart_rank": bucket["best_artist_chart_rank"],
                    "platform_count": platform_count,
                    "platform_coverage_score": platform_coverage_score,
                    "source_platforms": source_platforms,
                    "artist_heat_score": artist_heat_score,
                    "total_score": artist_heat_score,
                    "score_date": current_date.isoformat(),
                    "score_formula": "best_artist_chart_score*0.40 + avg_artist_chart_score*0.40 + platform_coverage_score*0.20",
                }
            )

        scored_rows.sort(key=lambda item: item["artist_heat_score"], reverse=True)

        return [
            {
                **item,
                "rank": index,
            }
            for index, item in enumerate(scored_rows[:limit], start=1)
        ]

    def artist_detail(self, artist_name: str, score_date: date | None = None, limit: int = 50) -> dict[str, Any]:
        current_date = score_date or self.latest_score_date()

        canonical_name = canonical_artist_name(artist_name)
        canonical_key = canonical_artist_key(artist_name)

        if not canonical_key:
            return {
                "artist_name": artist_name,
                "canonical_artist_name": artist_name,
                "artist_avatar_url": None,
                "score_date": current_date.isoformat() if current_date else None,
                "songs": [],
                "trend": [],
            }

        # 找到所有属于同一标准歌手的 Artist 记录
        all_artists = self.db.execute(select(Artist)).scalars().all()

        matched_artists = [
            artist
            for artist in all_artists
            if (artist.normalized_name or canonical_artist_key(artist.artist_name)) == canonical_key
        ]

        artist_ids = [artist.artist_id for artist in matched_artists]

        if not artist_ids:
            return {
                "artist_name": canonical_name,
                "canonical_artist_name": canonical_name,
                "artist_avatar_url": self._artist_avatar_for_name(canonical_name),
                "score_date": current_date.isoformat() if current_date else None,
                "songs": [],
                "trend": [],
            }

        avatar_url = None
        for artist in matched_artists:
            if artist.avatar_url:
                avatar_url = artist.avatar_url
                break

        rows = []
        trend_rows = []

        if current_date:
            rows = self.db.execute(
                select(HeatScoreDaily, Song)
                .join(Song, HeatScoreDaily.song_id == Song.song_id)
                .join(SongArtist, SongArtist.song_id == Song.song_id)
                .join(Artist, Artist.artist_id == SongArtist.artist_id)
                .where(HeatScoreDaily.score_date == current_date)
                .where(Artist.artist_id.in_(artist_ids))
                .order_by(HeatScoreDaily.rank)
                .limit(limit)
            ).all()

            start_date = current_date - timedelta(days=29)

            trend_rows = self.db.execute(
                select(
                    HeatScoreDaily.score_date,
                    func.sum(HeatScoreDaily.heat_score).label("heat_score"),
                )
                .join(Song, HeatScoreDaily.song_id == Song.song_id)
                .join(SongArtist, SongArtist.song_id == Song.song_id)
                .join(Artist, Artist.artist_id == SongArtist.artist_id)
                .where(HeatScoreDaily.score_date.between(start_date, current_date))
                .where(Artist.artist_id.in_(artist_ids))
                .group_by(HeatScoreDaily.score_date)
                .order_by(HeatScoreDaily.score_date)
            ).all()

        song_items = [self._heat_row(score, song) for score, song in rows]
        songs = _merge_song_items(song_items)
        canonical_groups = self._canonical_song_groups(current_date, chart_type="hot") if current_date else []
        group_by_key = {_canonical_group_key(group): group for group in canonical_groups}
        group_by_song_id = {
            song_id: group
            for group in canonical_groups
            for song_id in group.get("song_ids", set())
        }
        for song in songs:
            group = group_by_key.get(song.get("canonical_key"))
            if group is None:
                group = next((group_by_song_id.get(song_id) for song_id in song.get("song_ids", []) if group_by_song_id.get(song_id)), None)
            if group:
                platforms = _ordered_platforms(group.get("source_platforms") or [])
                song["source_platforms"] = platforms
                song["source_platform_names"] = [_platform_display_name(platform) for platform in platforms]
                song["platform_count"] = len(platforms)
                song["platform_performance"] = _platform_performance_from_group(group)
        songs.sort(key=lambda item: (item.get("rank") or 9999, -float(item.get("heat_score") or 0)))

        representative_songs = _representative_song_items(songs, 3)

        return {
            "artist_name": canonical_name,
            "canonical_artist_name": canonical_name,
            "artist_avatar_url": avatar_url or self._artist_avatar_for_name(canonical_name),
            "score_date": current_date.isoformat() if current_date else None,
            "matched_artist_ids": artist_ids,
            "raw_artist_names": [artist.artist_name for artist in matched_artists],
            "representative_songs": representative_songs,
            "charted_songs": songs[:limit],
            "songs": songs[:limit],
            "trend": [
                {
                    "score_date": row.score_date.isoformat(),
                    "heat_score": _float(row.heat_score),
                }
                for row in trend_rows
            ],
        }

    def artist_platform_performance(
        self,
        artist_name: str,
        chart_date: date | None = None,
        chart_type: str = "hot",
    ) -> dict[str, Any]:
        current_date = chart_date or self.latest_chart_date()
        canonical_name = canonical_artist_name(artist_name)
        canonical_key = canonical_artist_key(artist_name)
        if current_date is None or not canonical_key:
            return {
                "artist_name": canonical_name or artist_name,
                "chart_date": current_date.isoformat() if current_date else None,
                "chart_type": chart_type,
                "platforms": [],
                "strongest_platform": None,
                "strongest_platform_name": None,
            }

        groups = self._canonical_song_groups(current_date, chart_type=chart_type)
        buckets: dict[str, dict[str, Any]] = {
            platform: {
                "platform": platform,
                "platform_name": _platform_display_name(platform),
                "song_keys": set(),
                "ranks": [],
                "heat_scores": [],
                "songs": [],
            }
            for platform in ("netease", "qq", "kugou")
        }

        for group in groups:
            artist_keys = set(normalize_artists(group.get("artist_names") or group.get("artist_name")))
            if canonical_key not in artist_keys:
                continue
            canonical_song_key = _canonical_group_key(group)
            for platform in group["source_platforms"]:
                bucket = buckets.setdefault(
                    platform,
                    {
                        "platform": platform,
                        "platform_name": _platform_display_name(platform),
                        "song_keys": set(),
                        "ranks": [],
                        "heat_scores": [],
                        "songs": [],
                    },
                )
                if canonical_song_key in bucket["song_keys"]:
                    continue
                rank = group["platform_ranks"].get(platform)
                heat = _float(group["platform_rank_scores"].get(platform))
                bucket["song_keys"].add(canonical_song_key)
                if rank is not None:
                    bucket["ranks"].append(int(rank))
                bucket["heat_scores"].append(heat)
                bucket["songs"].append({"song_name": group["song_name"], "rank": rank, "heat_score": heat})

        items = []
        for platform in ("netease", "qq", "kugou"):
            bucket = buckets[platform]
            ranks = bucket["ranks"]
            heats = bucket["heat_scores"]
            songs = sorted(bucket["songs"], key=lambda item: (item.get("rank") or 9999, -item.get("heat_score", 0)))
            best_song = songs[0]["song_name"] if songs else None
            items.append(
                {
                    "platform": platform,
                    "platform_name": _platform_display_name(platform),
                    "song_count": len(bucket["song_keys"]),
                    "best_rank": min(ranks) if ranks else None,
                    "best_rank_song": best_song,
                    "avg_rank": _float(sum(ranks) / len(ranks)) if ranks else None,
                    "avg_heat_score": _float(sum(heats) / len(heats)) if heats else None,
                    "representative_songs": [item["song_name"] for item in songs[:3]],
                }
            )

        strongest = max(
            items,
            key=lambda item: (
                item["avg_heat_score"] if item["avg_heat_score"] is not None else -1,
                item["song_count"],
            ),
            default=None,
        )
        if strongest and strongest["song_count"] <= 0:
            strongest = None

        return {
            "artist_name": canonical_name or artist_name,
            "chart_date": current_date.isoformat(),
            "chart_type": chart_type,
            "platforms": items,
            "strongest_platform": strongest["platform"] if strongest else None,
            "strongest_platform_name": strongest["platform_name"] if strongest else None,
        }

    def etl_logs(self, limit: int = 50, task_name: str | None = None) -> list[dict[str, Any]]:
        query = select(EtlLog).order_by(desc(EtlLog.id)).limit(limit)
        if task_name:
            query = select(EtlLog).where(EtlLog.task_name == task_name).order_by(desc(EtlLog.id)).limit(limit)
        rows = self.db.execute(query).scalars().all()
        return [
            {
                "id": row.id,
                "task_name": row.task_name,
                "platform": row.platform,
                "start_time": row.start_time.isoformat() if row.start_time else None,
                "end_time": row.end_time.isoformat() if row.end_time else None,
                "status": row.status,
                "chart_count": row.chart_count,
                "metric_count": row.metric_count,
                "error_message": row.error_message,
            }
            for row in rows
        ]

    def reports(self, limit: int = 30) -> list[dict[str, Any]]:
        rows = self.db.execute(
            select(AiHeatAnalysis).order_by(desc(AiHeatAnalysis.analysis_date), desc(AiHeatAnalysis.id)).limit(limit)
        ).scalars().all()
        return [self._report_row(row, include_content=False) for row in rows]

    def latest_report(self, analysis_date: date | None = None) -> dict[str, Any] | None:
        query = select(AiHeatAnalysis).order_by(desc(AiHeatAnalysis.analysis_date), desc(AiHeatAnalysis.id)).limit(1)
        if analysis_date:
            query = (
                select(AiHeatAnalysis)
                .where(AiHeatAnalysis.analysis_date == analysis_date)
                .order_by(desc(AiHeatAnalysis.id))
                .limit(1)
            )
        row = self.db.execute(query).scalar_one_or_none()
        return self._report_row(row, include_content=True) if row else None

    def platform_record_counts(self, chart_date: date) -> list[dict[str, Any]]:
        rows = self.db.execute(
            select(Chart.platform, func.count(ChartSong.id).label("records"))
            .join(ChartSong, ChartSong.chart_id == Chart.chart_id)
            .where(ChartSong.chart_date == chart_date)
            .group_by(Chart.platform)
            .order_by(Chart.platform)
        ).all()
        return [{"platform": row.platform, "records": int(row.records)} for row in rows]

    def platform_song_counts(self, chart_date: date | None = None, chart_type: str = "hot") -> dict[str, Any]:
        current_date = chart_date or self.latest_chart_date()
        if current_date is None:
            return {"chart_date": None, "items": [], "count": 0}

        platform_map = self._platform_song_map(current_date, chart_type=chart_type)
        items = [
            {
                "platform": platform,
                "platform_name": _platform_display_name(platform),
                "song_count": len(songs),
                "avg_heat_score": _float(
                    sum(float(item.get("best_rank_score") or 0) for item in songs.values()) / len(songs)
                    if songs
                    else 0
                ),
            }
            for platform, songs in platform_map.items()
        ]
        items.sort(key=lambda item: item["platform_name"])
        return {"chart_date": current_date.isoformat(), "chart_type": chart_type, "items": items, "count": len(items)}

    def topn_overlap(
        self,
        chart_date: date | None = None,
        top_ns: list[int] | None = None,
        chart_type: str = "hot",
    ) -> dict[str, Any]:
        current_date = chart_date or self.latest_chart_date()
        if current_date is None:
            return {"chart_date": None, "x_axis": [], "series": []}

        top_ns = top_ns or [10, 20, 50]
        platform_map = self._platform_song_map(current_date, chart_type=chart_type)
        platforms = _ordered_platforms(platform_map.keys())
        pairs = [(left, right) for index, left in enumerate(platforms) for right in platforms[index + 1 :]]
        x_axis = [f"Top{value}" for value in top_ns]

        series = []
        for left, right in pairs:
            data = []
            for top_n in top_ns:
                left_keys = set(self._top_platform_song_keys(platform_map.get(left, {}), top_n))
                right_keys = set(self._top_platform_song_keys(platform_map.get(right, {}), top_n))
                denom = min(top_n, len(left_keys), len(right_keys))
                rate = len(left_keys & right_keys) / denom * 100 if denom else 0
                data.append(round(rate, 2))
            series.append(
                {
                    "name": f"{_platform_display_name(left)} vs {_platform_display_name(right)}",
                    "platforms": [left, right],
                    "data": data,
                }
            )

        if len(platforms) >= 3:
            data = []
            for top_n in top_ns:
                top_sets = [set(self._top_platform_song_keys(platform_map.get(platform, {}), top_n)) for platform in platforms[:3]]
                denom = min([top_n, *[len(item) for item in top_sets]])
                rate = len(set.intersection(*top_sets)) / denom * 100 if denom else 0
                data.append(round(rate, 2))
            series.append({"name": "三平台共同", "platforms": platforms[:3], "data": data})

        return {"chart_date": current_date.isoformat(), "chart_type": chart_type, "x_axis": x_axis, "series": series}

    def platform_similarity(self, chart_date: date | None = None, chart_type: str = "hot") -> dict[str, Any]:
        current_date = chart_date or self.latest_chart_date()
        if current_date is None:
            return {"chart_date": None, "items": [], "count": 0}

        platform_map = self._platform_song_map(current_date, chart_type=chart_type)
        platforms = _ordered_platforms(platform_map.keys())
        items = []
        for index, left in enumerate(platforms):
            left_set = set(platform_map.get(left, {}))
            for right in platforms[index + 1 :]:
                right_set = set(platform_map.get(right, {}))
                union = left_set | right_set
                intersection = left_set & right_set
                items.append(
                    {
                        "pair": f"{_platform_display_name(left)} - {_platform_display_name(right)}",
                        "platforms": [left, right],
                        "intersection_count": len(intersection),
                        "union_count": len(union),
                        "jaccard": round(len(intersection) / len(union) * 100, 2) if union else 0,
                    }
                )
        return {"chart_date": current_date.isoformat(), "chart_type": chart_type, "items": items, "count": len(items)}

    def coverage_distribution(self, chart_date: date | None = None, chart_type: str = "hot") -> dict[str, Any]:
        current_date = chart_date or self.latest_chart_date()
        if current_date is None:
            return {"chart_date": None, "chart_type": chart_type, "items": [], "count": 0}

        groups = self._canonical_song_groups(current_date, chart_type=chart_type)
        counts = {1: 0, 2: 0, 3: 0}
        labels = {1: "单平台", 2: "双平台", 3: "三平台"}
        for group in groups:
            coverage = max(1, min(len(group["source_platforms"]), 3))
            counts[coverage] += 1
        items = [
            {"coverage_count": coverage, "label": labels[coverage], "song_count": counts[coverage]}
            for coverage in (1, 2, 3)
        ]
        return {"chart_date": current_date.isoformat(), "chart_type": chart_type, "items": items, "count": len(items)}

    def common_songs_summary(self, chart_date: date | None = None, chart_type: str = "hot") -> dict[str, Any]:
        current_date = chart_date or self.latest_chart_date()
        if current_date is None:
            return {
                "chart_date": None,
                "chart_type": chart_type,
                "total_canonical_songs": 0,
                "one_platform_count": 0,
                "two_platform_count": 0,
                "three_platform_count": 0,
                "three_platform_avg_heat": 0,
                "three_platform_avg_rank": 0,
                "sample_common_songs": [],
            }

        groups = self._canonical_song_groups(current_date, chart_type=chart_type)
        heat_map = self._latest_heat_score_map({song_id for group in groups for song_id in group["song_ids"]})
        counts = {1: 0, 2: 0, 3: 0}
        common_rows: list[dict[str, Any]] = []
        for group in groups:
            coverage = max(1, min(len(group["source_platforms"]), 3))
            counts[coverage] += 1
            if coverage == 3:
                heat_score = max((heat_map.get(song_id, 0) for song_id in group["song_ids"]), default=0)
                rank_values = list(group["platform_ranks"].values())
                common_rows.append(
                    {
                        "song_name": group["song_name"],
                        "artist_name": ", ".join(group["artist_names"]),
                        "platforms": _ordered_platforms(group["source_platforms"]),
                        "avg_rank": _float(sum(rank_values) / len(rank_values)) if rank_values else 0,
                        "heat_score": heat_score,
                    }
                )
        heat_values = [row["heat_score"] for row in common_rows if row["heat_score"] > 0]
        rank_values = [row["avg_rank"] for row in common_rows if row["avg_rank"] > 0]
        common_rows.sort(key=lambda item: item["heat_score"], reverse=True)
        return {
            "chart_date": current_date.isoformat(),
            "chart_type": chart_type,
            "total_canonical_songs": len(groups),
            "one_platform_count": counts[1],
            "two_platform_count": counts[2],
            "three_platform_count": counts[3],
            "three_platform_avg_heat": _float(sum(heat_values) / len(heat_values)) if heat_values else 0,
            "three_platform_avg_rank": _float(sum(rank_values) / len(rank_values)) if rank_values else 0,
            "sample_common_songs": common_rows[:5],
        }

    def all_platform_hot_songs(self, chart_date: date | None = None, limit: int = 50) -> dict[str, Any]:
        current_date = chart_date or self.latest_score_date() or self.latest_chart_date()
        if current_date is None:
            return {"chart_date": None, "items": [], "count": 0}

        chart_map = self._platform_song_map(current_date)
        chart_by_key = {
            key: item
            for songs in chart_map.values()
            for key, item in songs.items()
        }
        items = [
            item
            for item in self.daily_hot(score_date=current_date, limit=500)
            if item.get("platform_count") == 3
        ][:limit]
        for item in items:
            chart_item = chart_by_key.get(item.get("canonical_key"))
            if chart_item:
                item["platform_ranks"] = chart_item.get("platform_ranks", {})
                item["platform_rank_scores"] = chart_item.get("platform_rank_scores", {})
        return {"chart_date": current_date.isoformat(), "items": _rerank(items), "count": len(items)}

    def song_score_breakdown(self, song_id: int) -> dict[str, Any] | None:
        song = self.db.get(Song, song_id)
        if song is None:
            return None

        latest_score = self.db.execute(
            select(HeatScoreDaily)
            .where(HeatScoreDaily.song_id == song_id)
            .order_by(desc(HeatScoreDaily.score_date))
            .limit(1)
        ).scalar_one_or_none()

        rank_score = _float(latest_score.main_platform_score) if latest_score else 0
        coverage_score = _float(latest_score.platform_coverage_score) if latest_score else 0
        items = [
            {
                "key": "rank",
                "name": "榜单排名得分",
                "value": rank_score,
                "description": "来自歌曲在各平台榜单中的排名表现",
                "missing": latest_score is None,
            },
            {
                "key": "coverage",
                "name": "跨平台覆盖得分",
                "value": coverage_score,
                "description": "来自歌曲覆盖平台数量",
                "missing": latest_score is None,
            },
            {
                "key": "chart_type",
                "name": "榜单类型得分",
                "value": 100 if latest_score else 0,
                "description": "当前主榜口径的基础分",
                "missing": latest_score is None,
            },
        ]

        return {
            "song_id": song.song_id,
            "song_name": song.song_name,
            "artist_name": song.artist_name,
            "score_date": latest_score.score_date.isoformat() if latest_score else None,
            "final_heat_score": _float(latest_score.heat_score) if latest_score else 0,
            "rank": latest_score.rank if latest_score else None,
            "trend_label": latest_score.trend_label if latest_score else None,
            "platform_count": latest_score.platform_count if latest_score else 0,
            "confidence_label": _coverage_confidence(latest_score.platform_count if latest_score else 0),
            "items": items,
        }

    def song_platform_performance(self, song_id: int, chart_date: date | None = None, chart_type: str = "hot") -> dict[str, Any] | None:
        song = self.db.get(Song, song_id)
        if song is None:
            return None
        current_date = chart_date or self.latest_chart_date()
        if current_date is None:
            return {
                "canonical_key": _song_identity_key_for_song(song),
                "song_name": song.song_name,
                "artist_name": song.artist_name,
                "chart_date": None,
                "chart_type": chart_type,
                "platforms": [],
            }

        target = {
            "song_id": song.song_id,
            "song_name": song.song_name,
            "artist_name": song.artist_name,
            "artist_names": self._artist_names_for_song(song.song_id) or [song.artist_name],
        }
        platform_map = self._platform_song_map(current_date, chart_type=chart_type)
        matched: dict[str, Any] | None = None
        for songs in platform_map.values():
            for item in songs.values():
                if song.song_id in set(item.get("song_ids") or [item.get("song_id")]) or should_merge_songs(item, target):
                    matched = item
                    break
            if matched:
                break

        song_ids = set(matched.get("song_ids") or [song_id]) if matched else {song_id}
        metric_map = self._latest_metric_map(song_ids)
        platform_song_map = self._platform_song_snapshot_map(song_ids)
        platforms = []
        for platform in ("netease", "qq", "kugou"):
            platform_item = None
            if matched and platform in (matched.get("source_platforms") or []):
                platform_item = matched
            metric_values = metric_map.get(platform) or {}
            comment_count = metric_values.get("comment_count")
            collect_count = metric_values.get("collect_count")
            has_comment = comment_count is not None and comment_count > 0
            has_collect = collect_count is not None and collect_count > 0
            platform_song = platform_song_map.get(platform)
            row = {
                "platform": platform,
                "platform_name": _platform_display_name(platform),
                "has_platform_data": platform_song is not None or has_comment or has_collect,
                "platform_song_id": platform_song.platform_song_id if platform_song else None,
                "platform_song_mid": platform_song.platform_song_mid if platform_song else None,
                "song_url": platform_song.song_url if platform_song else None,
                "cover_url": platform_song.cover_url if platform_song else None,
                "chart_name": None,
                "rank": None,
                "rank_score": None,
                "heat_score": None,
                "in_current_chart": False,
                "comment_count": comment_count if has_comment else None,
                "collect_count": collect_count if has_collect else None,
                "available_metrics": _available_metric_names(has_comment, has_collect),
            }
            if platform_item:
                chart_names = platform_item.get("platform_chart_names", {}).get(platform) or platform_item.get("chart_names") or []
                rank_score = _float((platform_item.get("platform_rank_scores") or {}).get(platform))
                row.update(
                    {
                        "chart_name": "、".join(chart_names) if chart_names else None,
                        "rank": (platform_item.get("platform_ranks") or {}).get(platform),
                        "rank_score": rank_score,
                        "heat_score": rank_score,
                        "in_current_chart": True,
                    }
                )
            platforms.append(row)

        return {
            "canonical_key": matched.get("canonical_key") if matched else _song_identity_key_for_song(song),
            "song_name": matched.get("song_name") if matched else song.song_name,
            "artist_name": matched.get("artist_name") if matched else song.artist_name,
            "chart_date": current_date.isoformat(),
            "chart_type": chart_type,
            "platforms": platforms,
        }

    def _platform_song_snapshot_map(self, song_ids: set[int]) -> dict[str, PlatformSong]:
        if not song_ids:
            return {}
        rows = self.db.execute(
            select(PlatformSong)
            .where(PlatformSong.song_id.in_(song_ids))
            .order_by(PlatformSong.id)
        ).scalars().all()
        snapshots: dict[str, PlatformSong] = {}
        for row in rows:
            platform = _platform_code(row.platform)
            if platform in {"netease", "qq", "kugou"} and platform not in snapshots:
                snapshots[platform] = row
        return snapshots

    def platform_exclusive_songs(self, chart_date: date | None = None) -> dict[str, Any]:
        current_date = chart_date or self.latest_chart_date()
        if current_date is None:
            return {"chart_date": None, "items": [], "count": 0}

        platform_map = self._platform_song_map(current_date)
        platforms = _ordered_platforms(platform_map.keys())
        items = []
        for platform in platforms:
            other_keys = set().union(*(set(platform_map.get(other, {})) for other in platforms if other != platform))
            exclusive_keys = set(platform_map.get(platform, {})) - other_keys
            items.append(
                {
                    "platform": platform,
                    "platform_name": _platform_display_name(platform),
                    "total_song_count": len(platform_map.get(platform, {})),
                    "exclusive_count": len(exclusive_keys),
                    "total_count": len(platform_map.get(platform, {})),
                    "exclusive_rate": round(
                        len(exclusive_keys) / max(len(platform_map.get(platform, {})), 1) * 100,
                        2,
                    ),
                }
            )
        return {"chart_date": current_date.isoformat(), "items": items, "count": len(items)}

    def platform_top_artists(self, chart_date: date | None = None, limit: int = 10) -> dict[str, Any]:
        current_date = chart_date or self.latest_chart_date()
        if current_date is None:
            return {"chart_date": None, "items": [], "count": 0}

        platform_map = self._platform_song_map(current_date)
        items = []
        for platform, songs in platform_map.items():
            counts: dict[str, int] = {}
            display_names: dict[str, str] = {}
            for item in songs.values():
                for artist_name in artist_display_names(item.get("artist_names") or item.get("artist_name")):
                    artist_key = canonical_artist_key(artist_name)
                    if not artist_key:
                        continue
                    counts[artist_key] = counts.get(artist_key, 0) + 1
                    display_names.setdefault(artist_key, artist_name)
            artists = [
                {"rank": index, "artist_name": display_names.get(key, key), "song_count": count}
                for index, (key, count) in enumerate(
                    sorted(counts.items(), key=lambda row: (-row[1], row[0]))[:limit],
                    start=1,
                )
            ]
            items.append(
                {
                    "platform": platform,
                    "platform_name": _platform_display_name(platform),
                    "artists": artists,
                }
            )
        items.sort(key=lambda item: item["platform_name"])
        return {"chart_date": current_date.isoformat(), "items": items, "count": len(items)}

    def platform_interaction_avg(self, metric_date: date | None = None) -> dict[str, Any]:
        current_date = metric_date or self.db.execute(select(func.max(SongMetric.metric_date))).scalar_one_or_none()
        if current_date is None:
            return {"metric_date": None, "items": [], "count": 0}

        rows = self.db.execute(
            select(
                SongMetric.platform,
                func.avg(SongMetric.comment_count).label("avg_comment_count"),
                func.count(SongMetric.comment_count).label("comment_sample_count"),
                func.count(SongMetric.metric_id).label("song_count"),
            )
            .where(SongMetric.metric_date == current_date)
            .group_by(SongMetric.platform)
        ).all()

        items = []
        for row in rows:
            platform = _platform_code(row.platform)
            items.append(
                {
                    "platform": platform,
                    "platform_name": _platform_display_name(platform),
                    "song_count": int(row.song_count or 0),
                    "avg_comment_count": _nullable_float(row.avg_comment_count),
                    "comment_sample_count": int(row.comment_sample_count or 0),
                }
            )
        items.sort(key=lambda item: item["platform_name"])
        return {"metric_date": current_date.isoformat(), "items": items, "count": len(items)}

    def _platform_song_map(self, chart_date: date, chart_type: str = "hot") -> dict[str, dict[str, dict[str, Any]]]:
        canonical_groups = self._canonical_song_groups(chart_date, chart_type=chart_type)
        platform_map: dict[str, dict[str, dict[str, Any]]] = {}
        for group in canonical_groups:
            source_platforms = _ordered_platforms(group["source_platforms"])
            canonical_key = _canonical_group_key(group)
            for platform in source_platforms:
                bucket = platform_map.setdefault(platform, {})
                bucket[canonical_key] = {
                    "canonical_key": canonical_key,
                    "song_id": group["song_id"],
                    "song_ids": sorted(group["song_ids"]),
                    "song_name": group["song_name"],
                    "display_song_name": group["song_name"],
                    "artist_name": ", ".join(group["artist_names"]),
                    "display_artist_name": ", ".join(group["artist_names"]),
                    "artist_names": group["artist_names"],
                    "source_platforms": source_platforms,
                    "source_platform_names": [_platform_display_name(item) for item in source_platforms],
                    "platform_count": len(source_platforms),
                    "coverage_text": f"{len(source_platforms)}/3",
                    "confidence_level": _coverage_confidence(len(source_platforms)),
                    "best_rank": group["platform_ranks"][platform],
                    "best_rank_score": group["platform_rank_scores"][platform],
                    "chart_names": sorted(group["platform_chart_names"].get(platform, set())),
                    "platform_ranks": dict(group["platform_ranks"]),
                    "platform_rank_scores": dict(group["platform_rank_scores"]),
                    "platform_chart_names": {
                        key: sorted(value)
                        for key, value in group["platform_chart_names"].items()
                    },
                }

        return {platform: platform_map[platform] for platform in _ordered_platforms(platform_map.keys())}

    def _canonical_song_groups(self, chart_date: date, chart_type: str = "hot") -> list[dict[str, Any]]:
        query = (
            select(Chart.platform, Chart.chart_name, ChartSong, Song)
            .join(ChartSong, ChartSong.chart_id == Chart.chart_id)
            .join(Song, ChartSong.song_id == Song.song_id)
            .where(ChartSong.chart_date == chart_date)
            .order_by(Chart.platform, ChartSong.rank)
        )
        if chart_type and chart_type != "all":
            query = query.where(Chart.chart_type == chart_type)
        rows = self.db.execute(
            query
        ).all()

        canonical_groups: list[dict[str, Any]] = []
        title_index: dict[str, list[int]] = {}
        for platform_value, chart_name, chart_song, song in rows:
            platform = _platform_code(platform_value)
            incoming = {
                "song_id": song.song_id,
            "song_name": song.song_name,
            "artist_name": song.artist_name,
                "artist_names": self._artist_names_for_song(song.song_id) or [song.artist_name],
            }
            normalized_title = normalize_song_title(song.song_name)
            group = None
            for candidate_index in title_index.get(normalized_title, []):
                existing = canonical_groups[candidate_index]
                if should_merge_songs(existing, incoming):
                    group = existing
                    break

            if group is None:
                group = {
                    "song_id": song.song_id,
                    "song_ids": set(),
                    "song_name": song.song_name,
                    "artist_name": song.artist_name,
                    "artist_names": artist_display_names(incoming["artist_names"]),
                    "source_platforms": set(),
                    "platform_ranks": {},
                    "platform_rank_scores": {},
                    "platform_chart_names": {},
                }
                canonical_groups.append(group)
                title_index.setdefault(normalized_title, []).append(len(canonical_groups) - 1)
            elif len(song.song_name or "") > len(group.get("song_name") or ""):
                group["song_name"] = song.song_name
                group["song_id"] = song.song_id

            group["song_ids"].add(song.song_id)
            group["source_platforms"].add(platform)
            group["platform_ranks"][platform] = min(group["platform_ranks"].get(platform, chart_song.rank), chart_song.rank)
            group["platform_rank_scores"][platform] = max(
                group["platform_rank_scores"].get(platform, 0),
                _float(chart_song.rank_score),
            )
            group["platform_chart_names"].setdefault(platform, set()).add(chart_name)

            for name in artist_display_names(incoming["artist_names"]):
                key = canonical_artist_key(name)
                if key and key not in {canonical_artist_key(value) for value in group["artist_names"]}:
                    group["artist_names"].append(name)
        return canonical_groups

    @staticmethod
    def _top_platform_song_keys(songs: dict[str, dict[str, Any]], top_n: int) -> list[str]:
        return [
            key
            for key, _item in sorted(songs.items(), key=lambda row: (row[1]["best_rank"], row[1]["song_name"]))[:top_n]
        ]

    def _latest_heat_score_map(self, song_ids: set[int]) -> dict[int, float]:
        if not song_ids:
            return {}
        current_date = self.latest_score_date()
        if current_date is None:
            return {}
        rows = self.db.execute(
            select(HeatScoreDaily.song_id, HeatScoreDaily.heat_score)
            .where(HeatScoreDaily.score_date == current_date, HeatScoreDaily.song_id.in_(song_ids))
        ).all()
        return {row.song_id: _float(row.heat_score) for row in rows}

    def _latest_comment_metric_map(self, song_ids: set[int]) -> dict[str, int]:
        return {
            platform: int(values["comment_count"])
            for platform, values in self._latest_metric_map(song_ids).items()
            if values.get("comment_count") is not None
        }

    def _latest_metric_map(self, song_ids: set[int]) -> dict[str, dict[str, int]]:
        if not song_ids:
            return {}
        latest_metric_date = self.db.execute(
            select(func.max(SongMetric.metric_date)).where(SongMetric.song_id.in_(song_ids))
        ).scalar_one_or_none()
        if latest_metric_date is None:
            return {}
        rows = self.db.execute(
            select(
                SongMetric.platform,
                func.max(SongMetric.comment_count).label("comment_count"),
                func.max(SongMetric.collect_count).label("collect_count"),
            )
            .where(
                SongMetric.song_id.in_(song_ids),
                SongMetric.metric_date == latest_metric_date,
            )
            .group_by(SongMetric.platform)
        ).all()
        result: dict[str, dict[str, int]] = {}
        for row in rows:
            values: dict[str, int] = {}
            if row.comment_count is not None and int(row.comment_count) > 0:
                values["comment_count"] = int(row.comment_count)
            if row.collect_count is not None and int(row.collect_count) > 0:
                values["collect_count"] = int(row.collect_count)
            if values:
                result[_platform_code(row.platform)] = values
        return result

    def _chart_songs_by_type(self, chart_date: date, chart_type: str, limit: int) -> list[dict[str, Any]]:
        rows = self.db.execute(
            select(ChartSong, Chart, Song)
            .join(Chart, ChartSong.chart_id == Chart.chart_id)
            .join(Song, ChartSong.song_id == Song.song_id)
            .where(and_(ChartSong.chart_date == chart_date, Chart.chart_type == chart_type))
            .order_by(Chart.platform, ChartSong.rank)
            .limit(limit)
        ).all()
        return [self._chart_row(chart_song, chart, song) for chart_song, chart, song in rows]

    def _merged_chart_songs_by_type(self, chart_date: date, chart_type: str, limit: int) -> list[dict[str, Any]]:
        rows = self.db.execute(
            select(ChartSong, Chart, Song)
            .join(Chart, ChartSong.chart_id == Chart.chart_id)
            .join(Song, ChartSong.song_id == Song.song_id)
            .where(and_(ChartSong.chart_date == chart_date, Chart.chart_type == chart_type))
        ).all()
        if not rows:
            return []

        grouped: dict[str, dict[str, Any]] = {}
        for chart_song, chart, song in rows:
            song_key = _song_identity_key_for_song(song)
            item = grouped.setdefault(
                song_key,
                {
                    "song": song,
                    "song_id": song.song_id,
                    "rank_scores": [],
                    "platforms": set(),
                    "best_rank": chart_song.rank,
                },
            )
            item["rank_scores"].append(float(chart_song.rank_score or 0))
            item["platforms"].add(chart.platform)
            item["best_rank"] = min(item["best_rank"], chart_song.rank)

        scored = []
        for item in grouped.values():
            song_id = item["song_id"]
            platform_count = len(item["platforms"])
            new_rank_score = max(item["rank_scores"]) if item["rank_scores"] else 0
            platform_coverage_score = platform_count / 3 * 100
            chart_type_score = 100
            new_song_score = new_rank_score * 0.75 + platform_coverage_score * 0.20 + chart_type_score * 0.05
            scored.append((song_id, item, new_song_score, new_rank_score, platform_coverage_score))
        scored.sort(key=lambda row: row[2], reverse=True)
        self._prime_song_display_cache([item["song"] for _song_id, item, *_rest in scored[:limit]])

        return [
            {
                "rank": index,
                "song_id": song_id,
                "song_name": item["song"].song_name,
                "artist_name": item["song"].artist_name,
                "display_artist_name": item["song"].artist_name,
                "artist_names": self._artist_names_for_song(song_id),
                "primary_artist_name": self._primary_artist_name_for_song(song_id) or item["song"].artist_name,
                "album_name": item["song"].album_name,
                "cover_url": self._cover_for_song(song_id),
                "artist_avatar_url": self._artist_avatar_for_name(item["song"].artist_name),
                "platform_count": len(item["platforms"]),
                "source_platforms": sorted(item["platforms"]),
                "new_song_score": _float(new_song_score),
                "rank_score": _float(new_rank_score),
                "platform_coverage_score": _float(platform_coverage_score),
                "chart_date": chart_date.isoformat(),
            }
            for index, (song_id, item, new_song_score, new_rank_score, platform_coverage_score) in enumerate(scored[:limit], start=1)
        ]

    def _heat_row(self, score: HeatScoreDaily, song: Song) -> dict[str, Any]:
        item = AnalyticsService._heat_score_only(score)
        item.update(self._song_display_fields(song))
        return item

    @staticmethod
    def _heat_score_only(score: HeatScoreDaily) -> dict[str, Any]:
        item = {
            "score_date": score.score_date.isoformat(),
            "rank": score.rank,
            "rank_delta": score.rank_delta,
            "trend_label": score.trend_label,
            "heat_score": _float(score.heat_score),
            "main_platform_score": _float(score.main_platform_score),
            "netease_score": _float(score.netease_score),
            "qq_score": _float(score.qq_score),
            "kugou_score": _float(score.kugou_score),
            "platform_count": score.platform_count if score.platform_count is not None else _heat_platform_count(score),
            "platform_coverage_score": _float(score.platform_coverage_score or (_heat_platform_count(score) / 3 * 100)),
            "dominant_platform": score.dominant_platform or _heat_dominant_platform(score),
        }
        return _apply_heat_confidence(item)

    def _chart_row(self, chart_song: ChartSong, chart: Chart, song: Song) -> dict[str, Any]:
        return {
            "platform": chart.platform,
            "chart_name": chart.chart_name,
            "chart_type": chart.chart_type,
            "chart_date": chart_song.chart_date.isoformat(),
            "rank": chart_song.rank,
            "rank_score": _float(chart_song.rank_score),
            **self._song_display_fields(song),
        }

    def _prime_song_display_cache(self, songs: list[Song]) -> None:
        song_ids = sorted({song.song_id for song in songs if song})
        if not song_ids:
            return

        self._prime_song_cover_cache(song_ids)

        missing_artist_names = [song_id for song_id in song_ids if song_id not in self._artist_names_cache]
        if missing_artist_names:
            for song_id in missing_artist_names:
                self._artist_names_cache[song_id] = []
                self._primary_artist_cache.setdefault(song_id, None)
            artist_rows = self.db.execute(
                select(SongArtist.song_id, Artist.artist_name)
                .join(Artist, SongArtist.artist_id == Artist.artist_id)
                .where(SongArtist.song_id.in_(missing_artist_names))
                .order_by(SongArtist.song_id, SongArtist.sort_order)
            ).all()
            for row in artist_rows:
                names = self._artist_names_cache.setdefault(row.song_id, [])
                names.append(row.artist_name)
                self._primary_artist_cache.setdefault(row.song_id, row.artist_name)
                if self._primary_artist_cache[row.song_id] is None:
                    self._primary_artist_cache[row.song_id] = row.artist_name

        avatar_names = {
            name
            for song in songs
            for name in (song.artist_name, self._primary_artist_cache.get(song.song_id))
            if name
        }
        self._prime_artist_avatar_cache(avatar_names)

    def _prime_song_cover_cache(self, song_ids: list[int]) -> None:
        missing_covers = [song_id for song_id in song_ids if song_id not in self._cover_cache]
        if missing_covers:
            for song_id in missing_covers:
                self._cover_cache[song_id] = None
            cover_rows = self.db.execute(
                select(PlatformSong.song_id, PlatformSong.cover_url)
                .where(PlatformSong.song_id.in_(missing_covers), PlatformSong.cover_url.is_not(None))
                .order_by(PlatformSong.song_id, PlatformSong.id)
            ).all()
            for row in cover_rows:
                if not self._cover_cache.get(row.song_id):
                    self._cover_cache[row.song_id] = row.cover_url

    def _prime_artist_avatar_cache(self, artist_names: set[str]) -> None:
        missing_names = sorted(name for name in artist_names if name and name not in self._artist_avatar_cache)
        if not missing_names:
            return
        for name in missing_names:
            self._artist_avatar_cache[name] = None
        rows = self.db.execute(
            select(Artist.artist_name, Artist.avatar_url)
            .where(Artist.artist_name.in_(missing_names), Artist.avatar_url.is_not(None))
        ).all()
        for row in rows:
            self._artist_avatar_cache[row.artist_name] = row.avatar_url

    def _song_display_fields(self, song: Song, avatar_artist_name: str | None = None) -> dict[str, Any]:
        primary_artist_name = self._primary_artist_name_for_song(song.song_id) or song.artist_name
        return {
            "song_id": song.song_id,
            "song_name": song.song_name,
            "artist_name": song.artist_name,
            "display_artist_name": song.artist_name,
            "artist_names": self._artist_names_for_song(song.song_id),
            "primary_artist_name": primary_artist_name,
            "album_name": song.album_name,
            "cover_url": self._cover_for_song(song.song_id),
            "artist_avatar_url": self._artist_avatar_for_name(avatar_artist_name if avatar_artist_name is not None else primary_artist_name),
        }

    def _cover_for_song(self, song_id: int) -> str | None:
        if song_id in self._cover_cache:
            return self._cover_cache[song_id]
        cover_url = self.db.execute(
            select(PlatformSong.cover_url)
            .where(PlatformSong.song_id == song_id, PlatformSong.cover_url.is_not(None))
            .order_by(PlatformSong.id)
            .limit(1)
        ).scalar_one_or_none()
        self._cover_cache[song_id] = cover_url
        return cover_url

    def _artist_avatar_for_name(self, artist_name: str | None) -> str | None:
        if not artist_name:
            return None
        if artist_name in self._artist_avatar_cache:
            return self._artist_avatar_cache[artist_name]
        avatar_url = self.db.execute(
            select(Artist.avatar_url)
            .where(Artist.artist_name == artist_name, Artist.avatar_url.is_not(None))
            .limit(1)
        ).scalar_one_or_none()
        self._artist_avatar_cache[artist_name] = avatar_url
        return avatar_url

    def _artist_names_for_song(self, song_id: int) -> list[str]:
        if song_id in self._artist_names_cache:
            return self._artist_names_cache[song_id]
        rows = self.db.execute(
            select(Artist.artist_name)
            .join(SongArtist, SongArtist.artist_id == Artist.artist_id)
            .where(SongArtist.song_id == song_id)
            .order_by(SongArtist.sort_order)
        ).all()
        names = [row.artist_name for row in rows]
        self._artist_names_cache[song_id] = names
        if song_id not in self._primary_artist_cache:
            self._primary_artist_cache[song_id] = names[0] if names else None
        return names

    def _primary_artist_name_for_song(self, song_id: int) -> str | None:
        if song_id in self._primary_artist_cache:
            return self._primary_artist_cache[song_id]
        artist_name = self.db.execute(
            select(Artist.artist_name)
            .join(SongArtist, SongArtist.artist_id == Artist.artist_id)
            .where(SongArtist.song_id == song_id)
            .order_by(SongArtist.sort_order)
            .limit(1)
        ).scalar_one_or_none()
        self._primary_artist_cache[song_id] = artist_name
        return artist_name

    @staticmethod
    def _report_row(row: AiHeatAnalysis, include_content: bool) -> dict[str, Any]:
        item = {
            "id": row.id,
            "analysis_date": row.analysis_date.isoformat(),
            "analysis_type": row.analysis_type,
            "model_name": row.model_name,
            "prompt_version": row.prompt_version,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        if include_content:
            item["content"] = row.content
            item["input_summary"] = row.input_summary
        return item

def _float(value: Any) -> float:
    return round(float(value or 0), 2)

def _score_norm(value: Any, max_value: int | float) -> float:
    number = float(value or 0)
    if max_value <= 0:
        return 0
    return min(number / float(max_value) * 100, 100)

def _song_identity_key_for_song(song: Song) -> str:
    return _song_identity_key(song.song_name, song.artist_name)

def _song_identity_key(song_name: str | None, artist_name: str | None) -> str:
    return song_identity_key(song_name, artist_name)

def _merge_song_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for item in items:
        enriched = _apply_heat_confidence(dict(item))
        target = None
        for group in groups:
            if should_merge_songs(group, enriched):
                target = group
                break
        if target is None:
            groups.append(_new_song_group(enriched))
        else:
            _merge_into_song_group(target, enriched)

    for group in groups:
        _finalize_song_group(group)
    return groups

def _new_song_group(item: dict[str, Any]) -> dict[str, Any]:
    item["_song_ids"] = set()
    item["_artist_keys"] = set(normalize_artists(item.get("artist_names") or item.get("artist_name")))
    item["_artist_display"] = artist_display_names(item.get("artist_names") or item.get("artist_name"))
    _merge_set_fields(item, item)
    return item

def _merge_into_song_group(group: dict[str, Any], item: dict[str, Any]) -> None:
    if len(str(item.get("song_name") or "")) > len(str(group.get("song_name") or "")):
        group["song_name"] = item.get("song_name")
    for key in ("netease_score", "qq_score", "kugou_score", "main_platform_score", "heat_score", "avg_heat_score", "peak_heat_score"):
        group[key] = max(float(group.get(key) or 0), float(item.get(key) or 0))
    if item.get("rank") and (not group.get("rank") or int(item["rank"]) < int(group["rank"])):
        group["rank"] = item["rank"]
    if item.get("song_id") and (not group.get("song_id") or float(item.get("heat_score") or 0) >= float(group.get("heat_score") or 0)):
        group["song_id"] = item["song_id"]
        group["cover_url"] = item.get("cover_url") or group.get("cover_url")
    if item.get("artist_avatar_url") and not group.get("artist_avatar_url"):
        group["artist_avatar_url"] = item["artist_avatar_url"]
    group["_artist_keys"].update(normalize_artists(item.get("artist_names") or item.get("artist_name")))
    for name in artist_display_names(item.get("artist_names") or item.get("artist_name")):
        key = canonical_artist_key(name)
        if key and key not in {canonical_artist_key(value) for value in group["_artist_display"]}:
            group["_artist_display"].append(name)
    _merge_set_fields(group, item)

def _merge_set_fields(group: dict[str, Any], item: dict[str, Any]) -> None:
    group.setdefault("_song_ids", set())
    if item.get("song_id"):
        group["_song_ids"].add(item["song_id"])

    platforms = set(group.get("_source_platforms") or [])
    for platform in item.get("source_platforms") or item.get("platforms") or []:
        platforms.add(_platform_code(platform))
    for score_key, platform in (("netease_score", "netease"), ("qq_score", "qq"), ("kugou_score", "kugou")):
        if float(item.get(score_key) or 0) > 0:
            platforms.add(platform)
    group["_source_platforms"] = platforms

def _platform_performance_from_group(group: dict[str, Any]) -> list[dict[str, Any]]:
    ranks = group.get("platform_ranks") or {}
    scores = group.get("platform_rank_scores") or {}
    chart_names = group.get("platform_chart_names") or {}
    return [
        {
            "platform": platform,
            "platform_name": _platform_display_name(platform),
            "rank": ranks.get(platform),
            "heat_score": _float(scores.get(platform)),
            "rank_score": _float(scores.get(platform)),
            "chart_names": sorted(chart_names.get(platform, set())),
            "entered_chart": ranks.get(platform) is not None,
        }
        for platform in _ordered_platforms(group.get("source_platforms") or [])
    ]

def _representative_song_items(songs: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    def sort_key(item: dict[str, Any]) -> tuple[float, int, int, int]:
        heat = float(
            item.get("heat_score")
            or item.get("avg_heat")
            or item.get("avg_heat_score")
            or item.get("score")
            or item.get("adjusted_heat")
            or item.get("total_score")
            or 0
        )
        platform_count = int(item.get("platform_count") or len(item.get("source_platform_names") or []) or 0)
        rank = int(item.get("best_rank") or item.get("rank") or 999999)
        source_count = len(item.get("source_platform_names") or item.get("source_platforms") or [])
        return (-heat, -platform_count, rank, -source_count)

    return sorted((song for song in songs if song), key=sort_key)[:limit]

def _finalize_song_group(group: dict[str, Any]) -> None:
    artists = group.get("_artist_display") or artist_display_names(group.get("artist_name"))
    if artists:
        group["artist_names"] = artists
        group["artist_name"] = ", ".join(artists)
        group["display_artist_name"] = group["artist_name"]
        group["primary_artist_name"] = artists[0]

    platform_order = {"netease": 0, "qq": 1, "kugou": 2}
    source_platforms = sorted(group.get("_source_platforms") or [], key=lambda value: platform_order.get(value, 99))
    group["source_platforms"] = source_platforms
    group["source_platform_names"] = [_platform_display_name(platform) for platform in source_platforms]
    group["platform_count"] = len(source_platforms)
    group["platform_coverage_score"] = round(min(group["platform_count"], 3) / 3 * 100, 2)
    if group.get("_song_ids"):
        group["song_ids"] = sorted(group["_song_ids"])

    group["canonical_key"] = _canonical_group_key(group)
    group["display_song_name"] = group.get("song_name")
    group["display_artist_name"] = group.get("display_artist_name") or group.get("artist_name")
    _apply_heat_confidence(group)
    group["heat_score"] = group["adjusted_heat"]
    group["dominant_platform"] = _dominant_platform_code_from_item(group)
    group["dominant_platform_name"] = _platform_display_name(group["dominant_platform"]) if group["dominant_platform"] else None

    for key in ("_song_ids", "_artist_keys", "_artist_display", "_source_platforms"):
        group.pop(key, None)

def _apply_heat_confidence(item: dict[str, Any]) -> dict[str, Any]:
    score_values = [
        float(item.get(key) or 0)
        for key in ("netease_score", "qq_score", "kugou_score")
        if float(item.get(key) or 0) > 0
    ]
    raw_heat = _float(sum(score_values) / len(score_values)) if score_values else _float(
        item.get("rawHeat") or item.get("raw_heat") or item.get("heat_score") or item.get("avg_heat_score")
    )
    platform_count = int(item.get("platform_count") or _platform_count_from_item(item))
    platform_count = max(0, min(platform_count, 3))
    weight = _coverage_weight(platform_count)
    adjusted_heat = round(raw_heat * weight, 2)
    confidence = _coverage_confidence(platform_count)

    item["rawHeat"] = raw_heat
    item["raw_heat"] = raw_heat
    item["adjustedHeat"] = adjusted_heat
    item["adjusted_heat"] = adjusted_heat
    item["coverageCount"] = platform_count
    item["coverage_count"] = platform_count
    item["coverageText"] = f"{platform_count}/3"
    item["coverage_text"] = item["coverageText"]
    item["confidenceLevel"] = confidence
    item["confidence_level"] = confidence
    item["coverage_weight"] = weight
    item["platform_count"] = platform_count
    return item

def _platform_count_from_item(item: dict[str, Any]) -> int:
    platforms = set()
    for platform in item.get("source_platforms") or item.get("platforms") or []:
        platforms.add(_platform_code(platform))
    for key, platform in (("netease_score", "netease"), ("qq_score", "qq"), ("kugou_score", "kugou")):
        if float(item.get(key) or 0) > 0:
            platforms.add(platform)
    return len(platforms)

def _platform_song_group_key(bucket: dict[str, dict[str, Any]], item: dict[str, Any]) -> str:
    title = normalize_song_title(item.get("song_name"))
    base_key = title or _song_identity_key(item.get("song_name"), item.get("artist_name"))
    if base_key not in bucket:
        return base_key
    if should_merge_songs(bucket[base_key], item):
        return base_key
    artists = normalize_artists(item.get("artist_names") or item.get("artist_name"))
    suffix = "|".join(artists) or "unknown"
    candidate = f"{base_key}|{suffix}"
    index = 2
    while candidate in bucket and not should_merge_songs(bucket[candidate], item):
        candidate = f"{base_key}|{suffix}|{index}"
        index += 1
    return candidate

def _canonical_group_key(group: dict[str, Any]) -> str:
    title = normalize_song_title(group.get("song_name") or group.get("display_song_name"))
    artists = normalize_artists(group.get("artist_names") or group.get("artist_name") or group.get("display_artist_name"))
    artist_part = "|".join(artists) if artists else "unknown"
    return f"{title}|{artist_part}"

def _dominant_platform_code_from_item(item: dict[str, Any]) -> str | None:
    values = {
        "netease": float(item.get("netease_score") or 0),
        "qq": float(item.get("qq_score") or 0),
        "kugou": float(item.get("kugou_score") or 0),
    }
    platform = max(values, key=values.get)
    return platform if values[platform] > 0 else None

def _coverage_weight(platform_count: int) -> float:
    if platform_count >= 3:
        return 1.0
    if platform_count == 2:
        return 0.9
    if platform_count == 1:
        return 0.78
    return 0.0

def _coverage_confidence(platform_count: int) -> str:
    if platform_count >= 3:
        return "高"
    if platform_count == 2:
        return "中"
    if platform_count == 1:
        return "低"
    return "待补充"

def _rerank(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for index, item in enumerate(items, start=1):
        item["rank"] = index
    return items

def _weekly_message(items: list[dict[str, Any]]) -> str:
    if not items:
        return "暂无周榜数据"
    available_days = max(int(item.get("available_days") or 0) for item in items)
    return "正式周榜" if available_days >= 7 else "周榜预览"

def _nullable_float(value: Any) -> float | None:
    if value is None:
        return None
    return round(float(value), 2)

def _platform_code(platform: str | None) -> str:
    text = (platform or "").strip().lower()
    if "网易" in text or "netease" in text or "163" in text:
        return "netease"
    if "qq" in text or "tencent" in text or "qq音乐" in text:
        return "qq"
    if "酷狗" in text or "kugou" in text:
        return "kugou"
    return text or "unknown"

def _platform_display_name(platform: str | None) -> str:
    names = {
        "netease": "网易云音乐",
        "qq": "QQ音乐",
        "kugou": "酷狗音乐",
    }
    code = _platform_code(platform)
    return names.get(code, platform or "未知平台")

def _available_metric_names(has_comment: bool, has_collect: bool) -> list[str]:
    names = []
    if has_comment:
        names.append("comment_count")
    if has_collect:
        names.append("collect_count")
    return names

def _style_for_song_chart(song: Song, chart: Chart) -> tuple[str, str | None]:
    candidates = _style_candidates(song, chart)
    for candidate in candidates:
        normalized = normalize_style_name(candidate)
        if normalized:
            return str(candidate), normalized
    raw = next((str(candidate) for candidate in candidates if candidate), "")
    return raw, None

def _style_candidates(song: Song, chart: Chart) -> list[str]:
    values: list[str] = []
    if song.style and song.style.style_name:
        values.append(song.style.style_name)
    for value in (chart.style_name, chart.style_key, chart.chart_type, chart.chart_name):
        if value:
            values.append(str(value))
    values.extend(_metadata_style_candidates(song))
    return values

def _metadata_style_candidates(song: Song) -> list[str]:
    values: list[str] = []
    for platform_song in getattr(song, "platform_songs", []) or []:
        raw = getattr(platform_song, "extra_metadata", None)
        if not raw:
            continue
        try:
            metadata = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(metadata, dict):
            continue
        for key in ("style", "genre", "tag", "tags"):
            value = metadata.get(key)
            if isinstance(value, list):
                values.extend(str(item) for item in value if item)
            elif value:
                values.append(str(value))
    return values

def _ordered_platforms(platforms: Any) -> list[str]:
    preferred = ["netease", "qq", "kugou"]
    codes = {_platform_code(platform) for platform in platforms if platform}
    ordered = [platform for platform in preferred if platform in codes]
    ordered.extend(sorted(code for code in codes if code not in preferred))
    return ordered

def _heat_platform_count(score: HeatScoreDaily) -> int:
    return sum(
        1
        for value in (score.netease_score, score.qq_score, score.kugou_score)
        if float(value or 0) > 0
    )

def _heat_dominant_platform(score: HeatScoreDaily) -> str | None:
    values = {
        "网易云音乐": float(score.netease_score or 0),
        "QQ音乐": float(score.qq_score or 0),
        "酷狗音乐": float(score.kugou_score or 0),
    }
    platform = max(values, key=values.get)
    return platform if values[platform] > 0 else None

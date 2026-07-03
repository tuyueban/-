import sys
import unittest
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.db.session import Base  # noqa: E402
from app.crawlers.dtos import ChartSongItem, SongMetricItem  # noqa: E402
from app.models import Artist  # noqa: E402
from app.repositories.song_repository import SongRepository  # noqa: E402


class SongRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.session = sessionmaker(bind=engine)()

    def tearDown(self) -> None:
        self.session.close()

    def test_upsert_artist_reuses_existing_artist_name_when_normalized_name_missing(self) -> None:
        existing = Artist(
            artist_name="Crabbit",
            canonical_name="Crabbit",
            normalized_name=None,
        )
        self.session.add(existing)
        self.session.flush()

        repository = SongRepository(self.session)
        artist = repository._upsert_artist("Crabbit", "https://example.test/avatar.jpg")

        self.assertIsNotNone(artist)
        self.assertEqual(artist.artist_id, existing.artist_id)
        self.assertEqual(artist.normalized_name, "crabbit")
        self.assertEqual(artist.avatar_url, "https://example.test/avatar.jpg")
        self.assertEqual(self.session.query(Artist).count(), 1)

    def test_upsert_artist_does_not_overwrite_taken_normalized_name(self) -> None:
        name_match = Artist(
            artist_name="AIR",
            canonical_name="AIR",
            normalized_name=None,
        )
        key_match = Artist(
            artist_name="air",
            canonical_name="air",
            normalized_name="air",
        )
        self.session.add_all([name_match, key_match])
        self.session.flush()

        repository = SongRepository(self.session)
        artist = repository._upsert_artist("AIR", None)

        self.assertIsNotNone(artist)
        self.assertEqual(artist.artist_id, name_match.artist_id)
        self.assertIsNone(name_match.normalized_name)
        self.assertEqual(key_match.normalized_name, "air")

    def test_failed_metric_does_not_overwrite_existing_success_comment_count(self) -> None:
        repository = SongRepository(self.session)
        collect_time = datetime(2026, 7, 2, 10, 0, 0)
        repository.upsert_chart_song(
            ChartSongItem(
                platform="QQ音乐",
                chart_name="热歌榜",
                chart_type="hot",
                rank=1,
                song_name="Song A",
                artist_name="Artist A",
                platform_song_id="qq-song-1",
                chart_date=date(2026, 7, 2),
                collect_time=collect_time,
            )
        )
        repository.upsert_metric(
            SongMetricItem(
                platform="QQ音乐",
                platform_song_id="qq-song-1",
                metric_time=collect_time,
                is_success=True,
                song_name="Song A",
                artist_name="Artist A",
                comment_count=12345,
                metric_source="success",
            )
        )

        metric = repository.upsert_metric(
            SongMetricItem(
                platform="QQ音乐",
                platform_song_id="qq-song-1",
                metric_time=datetime(2026, 7, 2, 11, 0, 0),
                is_success=False,
                song_name="Song A",
                artist_name="Artist A",
                comment_count=None,
                metric_source="failed",
                fail_reason="comment endpoint returned empty",
            )
        )

        self.assertEqual(metric.comment_count, 12345)
        self.assertTrue(metric.is_success)
        self.assertEqual(metric.fail_reason, "comment endpoint returned empty")


if __name__ == "__main__":
    unittest.main()

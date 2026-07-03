import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.song_matcher import normalize_song_title, should_merge_songs  # noqa: E402


class SongMatcherTest(unittest.TestCase):
    def test_angel_title_variants_merge(self) -> None:
        titles = ["ANGEL", "Angel", "ANGEL（天使）"]
        self.assertEqual({normalize_song_title(title) for title in titles}, {"angel"})

    def test_angel_artist_variants_merge(self) -> None:
        self.assertTrue(
            should_merge_songs(
                {"song_name": "ANGEL", "artist_name": "尹美莱, Tiger JK"},
                {"song_name": "ANGEL（天使）", "artist_name": "尹美莱, Tiger JK, Bizzy"},
            )
        )

    def test_angel_baby_does_not_merge_to_angel(self) -> None:
        self.assertFalse(
            should_merge_songs(
                {"song_name": "Angel", "artist_name": "Troye Sivan"},
                {"song_name": "Angel Baby", "artist_name": "Troye Sivan"},
            )
        )

    def test_live_version_merges_to_main_song(self) -> None:
        self.assertTrue(
            should_merge_songs(
                {"song_name": "雨过后的风景", "artist_name": "歌手A"},
                {"song_name": "雨过后的风景 (Live)", "artist_name": "歌手A"},
            )
        )

    def test_remix_version_merges_for_main_chart_strategy(self) -> None:
        self.assertTrue(
            should_merge_songs(
                {"song_name": "怎么能", "artist_name": "歌手A"},
                {"song_name": "怎么能 Remix", "artist_name": "歌手A"},
            )
        )


if __name__ == "__main__":
    unittest.main()

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.analytics_service import _merge_song_items  # noqa: E402


class SongAggregationConsistencyTest(unittest.TestCase):
    def test_source_platforms_and_dominant_platform_are_separate(self) -> None:
        songs = _merge_song_items(
            [
                {
                    "song_id": 1,
                    "song_name": "ANGEL",
                    "artist_name": "MFBTY",
                    "netease_score": 80,
                    "qq_score": 0,
                    "kugou_score": 0,
                    "heat_score": 80,
                },
                {
                    "song_id": 2,
                    "song_name": "ANGEL（天使）",
                    "artist_name": "尹美莱, Tiger JK, Bizzy",
                    "netease_score": 0,
                    "qq_score": 90,
                    "kugou_score": 70,
                    "heat_score": 90,
                },
            ]
        )

        self.assertEqual(len(songs), 1)
        song = songs[0]
        self.assertEqual(song["platform_count"], len(song["source_platforms"]))
        self.assertEqual(set(song["source_platforms"]), {"netease", "qq", "kugou"})
        self.assertEqual(song["coverage_text"], "3/3")
        self.assertEqual(song["confidence_level"], "高")
        self.assertEqual(song["dominant_platform"], "qq")
        self.assertEqual(song["dominant_platform_name"], "QQ音乐")
        self.assertEqual(song["adjusted_heat"], song["heat_score"])


if __name__ == "__main__":
    unittest.main()

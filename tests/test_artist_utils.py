import unittest
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.crawlers.utils import split_artist_names  # noqa: E402


class ArtistUtilsTest(unittest.TestCase):
    def test_split_comma_artists(self) -> None:
        self.assertEqual(
            split_artist_names("尹美莱, Tiger JK, Bizzy"),
            ["尹美莱", "Tiger JK", "Bizzy"],
        )

    def test_split_slash_artists(self) -> None:
        self.assertEqual(split_artist_names("周杰伦 / aMEI"), ["周杰伦", "aMEI"])

    def test_split_feat_artists(self) -> None:
        self.assertEqual(split_artist_names("林俊杰 feat. 蔡卓妍"), ["林俊杰", "蔡卓妍"])

    def test_split_ampersand_artists(self) -> None:
        self.assertEqual(split_artist_names("王力宏 & 卢巧音"), ["王力宏", "卢巧音"])

    def test_split_mixed_name_artists(self) -> None:
        self.assertEqual(split_artist_names("G.E.M.邓紫棋, 艾热AIR"), ["G.E.M.邓紫棋", "艾热AIR"])


if __name__ == "__main__":
    unittest.main()

import sys
import unittest
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

STYLE_SERVICE_PATH = ROOT / "backend" / "app" / "services" / "style_service.py"
spec = importlib.util.spec_from_file_location("style_service", STYLE_SERVICE_PATH)
style_service = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(style_service)
normalize_style_name = style_service.normalize_style_name


class StyleServiceTest(unittest.TestCase):
    def test_pop_aliases_normalize_to_popular(self) -> None:
        values = [
            "流行",
            "Pop",
            "华语流行",
            "国语流行",
            "流行/Pop",
            "C-Pop",
            "Mandopop",
            "热歌榜",
            "流行榜",
        ]

        self.assertEqual({normalize_style_name(value) for value in values}, {"流行"})

    def test_common_chart_names_normalize_to_styles(self) -> None:
        self.assertEqual(normalize_style_name("说唱榜"), "说唱 / Hip-Hop")
        self.assertEqual(normalize_style_name("电子音乐榜"), "电子 / Dance")
        self.assertEqual(normalize_style_name("影视原声"), "OST / 影视音乐")


if __name__ == "__main__":
    unittest.main()

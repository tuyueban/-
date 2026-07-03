import sys
import unittest
import logging
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.detail_ai_service import (  # noqa: E402
    DetailAiService,
    _artist_display_text,
    _song_display_text,
    build_natural_song_fallback,
    build_natural_artist_fallback,
    sanitize_ai_text,
    unique_song_names,
)


class DetailAiServiceTest(unittest.TestCase):
    def test_unique_song_names_removes_duplicates(self) -> None:
        songs = [
            {"song_name": "唯一"},
            {"song_name": "唯一"},
            {"song_name": "多远都要在一起"},
            {"song_name": "泡沫"},
            {"song_name": "多远都要在一起"},
        ]

        self.assertEqual(unique_song_names(songs), ["唯一", "多远都要在一起", "泡沫"])

    def test_natural_artist_fallback_has_no_backend_terms(self) -> None:
        content = build_natural_artist_fallback(
            "G.E.M.邓紫棋",
            [{"song_name": "唯一", "platform_count": 3}, {"song_name": "唯一", "platform_count": 3}],
        )

        self.assertIn("G.E.M.邓紫棋", content)
        self.assertEqual(content.count("《唯一》"), 1)
        for blocked in ("AI call failed", "本地兜底", "不确定性", "公开搜索来源", "数据侧观察"):
            self.assertNotIn(blocked, content)

    def test_sanitize_ai_text_removes_technical_errors(self) -> None:
        content = sanitize_ai_text("本地兜底 AI call failed: Client error '401 Authorization Required' 百度百科")

        for blocked in ("AI call failed", "Client error", "401", "Authorization Required", "本地兜底", "百度百科"):
            self.assertNotIn(blocked, content)

    def test_artist_display_replaces_report_style_ai_text(self) -> None:
        content = _artist_display_text(
            "歌手概览：测试歌手。近况观察：系统内当前关联上榜歌曲包括 A。不确定性：当前为 AI 兜底分析。",
            {"artist_name": "测试歌手", "ranked_songs": [{"song_name": "A"}, {"song_name": "A"}, {"song_name": "B"}]},
        )

        self.assertIn("测试歌手", content)
        self.assertIn("《A》、《B》", content)
        for blocked in ("歌手概览", "近况观察", "系统内", "不确定性", "兜底"):
            self.assertNotIn(blocked, content)

    def test_natural_song_fallback_has_no_report_terms(self) -> None:
        content = build_natural_song_fallback(
            "有何不可",
            artist_name="许嵩",
            trend_label="呈现明显上升趋势",
            rank_summary="榜单排名从245位升至220位",
            platform_summary="当前热度主要集中在QQ音乐",
            chart_summary="抖音热歌榜、热歌榜",
        )

        self.assertIn("许嵩的《有何不可》", content)
        self.assertNotIn("\n", content)
        for blocked in ("###", "结论", "证据", "外部因素", "风险提示", "AI call failed"):
            self.assertNotIn(blocked, content)

    def test_song_display_replaces_markdown_report_ai_text(self) -> None:
        content = _song_display_text(
            "### 结论\n歌曲近期爆发上升。\n### 证据\n* 热度趋势。\n### 风险提示\n无法确定。",
            {
                "song": {"song_name": "有何不可", "artist_name": "许嵩"},
                "latest_score": {"rank": 220, "rank_delta": 25, "dominant_platform": "QQ音乐", "platform_count": 2},
                "trend": [],
                "recent_charts": [{"chart_name": "抖音热歌榜"}, {"chart_name": "热歌榜"}],
            },
        )

        self.assertIn("许嵩的《有何不可》", content)
        for blocked in ("###", "结论", "证据", "外部因素", "风险提示", "无法确定"):
            self.assertNotIn(blocked, content)

    def test_generate_fallback_hides_ai_error(self) -> None:
        logging.disable(logging.CRITICAL)
        self.addCleanup(lambda: logging.disable(logging.NOTSET))
        service = DetailAiService.__new__(DetailAiService)

        def fail_call(*_args: object, **_kwargs: object) -> str:
            raise RuntimeError("401 Authorization Required")

        service._call_ai = fail_call  # type: ignore[method-assign]
        content, mode, error = service._generate(
            "prompt",
            {"artist_name": "G.E.M.邓紫棋", "ranked_songs": [{"song_name": "泡沫"}]},
            [],
            lambda _evidence, _sources: "自然展示文案",
        )

        self.assertEqual(content, "自然展示文案")
        self.assertEqual(mode, "fallback")
        self.assertIsNone(error)


if __name__ == "__main__":
    unittest.main()

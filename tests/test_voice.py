"""语音模块测试：emoji 剥离、TTS 文本清洗。"""
import pytest


class TestStripEmojis:
    def test_plain_text_unchanged(self):
        from openmemo.voice import strip_emojis
        assert strip_emojis("你好世界") == "你好世界"

    def test_basic_emoji_removed(self):
        from openmemo.voice import strip_emojis
        assert strip_emojis("你好😊世界") == "你好世界"

    def test_emoji_only(self):
        from openmemo.voice import strip_emojis
        assert strip_emojis("😂😂😂") == ""

    def test_flag_removed(self):
        from openmemo.voice import strip_emojis
        assert strip_emojis("中国🇨🇳加油") == "中国加油"

    def test_symbols_removed(self):
        from openmemo.voice import strip_emojis
        assert "⏰" not in strip_emojis("⏰ 该起床了")

    def test_arrow_removed(self):
        from openmemo.voice import strip_emojis
        # ➡️ 带变体选择符的箭头是 emoji；纯 → 不是
        assert "➡️" not in strip_emojis("去跑步 ➡️ 加油")
        assert strip_emojis("去跑步 → 加油") == "去跑步 → 加油"

    def test_multi_space_collapse(self):
        from openmemo.voice import strip_emojis
        assert strip_emojis("你好  😊  世界") == "你好 世界"

    def test_none_input(self):
        from openmemo.voice import strip_emojis
        assert strip_emojis(None) == ""

    def test_empty_input(self):
        from openmemo.voice import strip_emojis
        assert strip_emojis("") == ""

    def test_heart_removed(self):
        from openmemo.voice import strip_emojis
        assert "❤" not in strip_emojis("爱你❤")

    def test_star_removed(self):
        from openmemo.voice import strip_emojis
        assert "✨" not in strip_emojis("加油✨")

    def test_chinese_punct_kept(self):
        from openmemo.voice import strip_emojis
        assert strip_emojis("你好，世界！") == "你好，世界！"


class TestVoiceMapping:
    def test_chinese_voices_present(self):
        from openmemo.voice import CHINESE_VOICES
        for key in ["xiaoxiao", "xiaoyi", "yunjian", "yunxi", "yunxia", "yunyang"]:
            assert key in CHINESE_VOICES

    def test_default_voice_is_xiaoxiao(self):
        from openmemo.voice import CHINESE_VOICES
        assert CHINESE_VOICES["xiaoxiao"] == "zh-CN-XiaoxiaoNeural"

    def test_all_voices_valid_format(self):
        from openmemo.voice import CHINESE_VOICES
        for v in CHINESE_VOICES.values():
            assert v.startswith("zh-CN-")

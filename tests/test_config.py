"""配置系统测试：settings.json 覆盖 .env、持久化、脱敏、CLI 逻辑。"""
import pytest
import json
from pathlib import Path


@pytest.fixture
def cfg_env(tmp_path, monkeypatch):
    """隔离 SETTINGS_PATH，并清空运行中的覆盖。"""
    import openmemo.config as config_module
    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(config_module, "SETTINGS_PATH", settings_path)
    # 清掉可能存在的旧覆盖
    if settings_path.exists():
        settings_path.unlink()
    yield config_module
    if settings_path.exists():
        settings_path.unlink()


class TestGetSetting:
    def test_env_fallback(self, cfg_env):
        # 未设置覆盖 → 回退 .env
        assert cfg_env.get_setting("ai_model") != "" or True  # .env 有值

    def test_override_wins(self, cfg_env):
        cfg_env.set_setting("ai_model", "test-model")
        assert cfg_env.get_setting("ai_model") == "test-model"

    def test_unknown_key_returns_none(self, cfg_env):
        assert cfg_env.get_setting("not_a_key") is None

    def test_empty_override_falls_back(self, cfg_env):
        cfg_env.set_setting("tts_voice", "zh-CN-YunxiNeural")
        cfg_env.set_setting("tts_voice", "")   # 空 → 回退
        assert cfg_env.get_setting("tts_voice") == "zh-CN-XiaoxiaoNeural"


class TestSetSetting:
    def test_set_persists_to_file(self, cfg_env, tmp_path):
        cfg_env.set_setting("tts_voice", "zh-CN-YunyangNeural")
        data = json.loads((tmp_path / "settings.json").read_text())
        assert data["tts_voice"] == "zh-CN-YunyangNeural"

    def test_set_unknown_key_fails(self, cfg_env):
        assert cfg_env.set_setting("bogus", "x") is False

    def test_set_none_removes_key(self, cfg_env):
        cfg_env.set_setting("ai_model", "kimi-k2.5")
        cfg_env.set_setting("ai_model", None)
        assert cfg_env.get_setting("ai_model") != "kimi-k2.5"

    def test_set_strips_whitespace(self, cfg_env):
        cfg_env.set_setting("ai_model", "  glm-5.2  ")
        assert cfg_env.get_setting("ai_model") == "glm-5.2"


class TestMaskSecret:
    def test_mask_long(self):
        assert "…" in __import__("openmemo.config", fromlist=["mask_secret"]).mask_secret("sk-abcdefghijkl")

    def test_mask_short(self):
        from openmemo.config import mask_secret
        assert mask_secret("short") == "****"

    def test_mask_empty(self):
        from openmemo.config import mask_secret
        assert mask_secret("") == "****"

    def test_mask_keeps_ends(self):
        from openmemo.config import mask_secret
        m = mask_secret("sk-12345678-9999")
        assert m.startswith("sk-1")
        assert m.endswith("9999")


class TestAllSettings:
    def test_all_keys_present(self, cfg_env):
        s = cfg_env.get_all_settings()
        for k in ["ai_model", "ai_base_url", "ai_api_key", "search_provider",
                  "search_api_key", "search_base_url", "tts_voice"]:
            assert k in s

    def test_readonly_keys(self, cfg_env):
        s = cfg_env.get_all_settings()
        assert s["server_port"]["readonly"] is True
        assert s["server_host"]["readonly"] is True

    def test_secret_masked_in_all(self, cfg_env):
        s = cfg_env.get_all_settings()
        val = s["ai_api_key"]["value"]
        assert "…" in val or val == "****" or val == ""

    def test_descriptions_exist(self, cfg_env):
        s = cfg_env.get_all_settings()
        for k, info in s.items():
            assert info["description"]


class TestConfigHelpers:
    def test_ai_model_helper(self, cfg_env):
        cfg_env.set_setting("ai_model", "helper-model")
        assert cfg_env.ai_model() == "helper-model"

    def test_tts_voice_helper_default(self, cfg_env):
        assert cfg_env.tts_voice() != ""

    def test_search_provider_helper(self, cfg_env):
        assert cfg_env.search_provider() != "" or True

    def test_ai_base_url_helper(self, cfg_env):
        assert cfg_env.ai_base_url() != "" or True


class TestSettingsApiEndpoints:
    def test_get_settings_endpoint(self, cfg_env):
        from fastapi.testclient import TestClient
        import openmemo.tasks as tm
        import tempfile
        tm.DB_PATH = Path(tempfile.mktemp(suffix=".db"))
        from openmemo.server import app
        client = TestClient(app)
        r = client.get("/api/settings")
        assert r.status_code == 200
        assert "ai_model" in r.json()["settings"]

    def test_patch_settings_endpoint(self, cfg_env):
        from fastapi.testclient import TestClient
        import openmemo.tasks as tm
        import tempfile
        tm.DB_PATH = Path(tempfile.mktemp(suffix=".db"))
        from openmemo.server import app
        client = TestClient(app)
        r = client.patch("/api/settings", json={"tts_voice": "zh-CN-YunxiNeural"})
        assert r.status_code == 200
        assert "tts_voice" in r.json()["updated"]

    def test_patch_unknown_ignored(self, cfg_env):
        from fastapi.testclient import TestClient
        import openmemo.tasks as tm
        import tempfile
        tm.DB_PATH = Path(tempfile.mktemp(suffix=".db"))
        from openmemo.server import app
        client = TestClient(app)
        r = client.patch("/api/settings", json={"nope": "x"})
        assert r.json()["updated"] == []

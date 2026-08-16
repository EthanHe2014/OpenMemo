"""对话动作执行测试：AI JSON → 建任务/完成/删除/编辑 + 安全网路径。"""
import pytest
import sqlite3
from pathlib import Path


@pytest.fixture
def conv_env(tmp_path, monkeypatch):
    """隔离 DB，返回 conversation 模块 + TaskManager。"""
    import openmemo.config as config_module
    import openmemo.tasks as tasks_module

    db = tmp_path / "conv.db"
    monkeypatch.setattr(config_module, "DB_PATH", db)
    monkeypatch.setattr(tasks_module, "DB_PATH", db)
    tasks_module.init_db()
    mgr = tasks_module.TaskManager()
    yield mgr
    # 清理
    conn = sqlite3.connect(str(db))
    conn.execute("DELETE FROM tasks")
    conn.commit()
    conn.close()


class TestCreateTaskFromAi:
    def test_basic_create(self, conv_env):
        from openmemo.conversation import _create_task_from_ai_task
        t = _create_task_from_ai_task({"content": "喝水", "time": "2026-09-01 08:00"}, "s1")
        assert t is not None
        assert t["content"] == "喝水"
        assert t["trigger_time"] == "2026-09-01 08:00"

    def test_content_fallback_reminder_text(self, conv_env):
        from openmemo.conversation import _create_task_from_ai_task
        t = _create_task_from_ai_task({"reminder_text": "该吃药啦，记得按时", "time": "2026-09-01 08:00"}, "s1")
        assert t is not None
        assert "吃药" in t["content"]

    def test_no_content_no_reminder(self, conv_env):
        from openmemo.conversation import _create_task_from_ai_task
        t = _create_task_from_ai_task({"time": "2026-09-01 08:00"}, "s1")
        # 无内容无 reminder_text → 用"提醒"兜底
        assert t is not None

    def test_empty_task_dict(self, conv_env):
        from openmemo.conversation import _create_task_from_ai_task
        assert _create_task_from_ai_task(None, "s1") is None
        assert _create_task_from_ai_task({}, "s1") is None

    def test_past_time_rejected(self, conv_env):
        from datetime import datetime, timedelta
        from openmemo.conversation import _create_task_from_ai_task
        past = (datetime.now() - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")
        t = _create_task_from_ai_task({"content": "过期", "time": past}, "s1")
        assert t is None

    def test_recurring_kept(self, conv_env):
        from openmemo.conversation import _create_task_from_ai_task
        t = _create_task_from_ai_task({"content": "吃药", "time": "每天 08:00", "recurring": "每天"}, "s1")
        assert t is not None
        assert t["is_recurring"] == "每天"

    def test_recurring_in_time_field_rejected(self, conv_env):
        """回归：recurring 误放进 time 字段时，不建成一次性任务。"""
        from openmemo.conversation import _create_task_from_ai_task
        t = _create_task_from_ai_task({"content": "喝水", "time": "每2小时"}, "s1")
        assert t is not None
        assert t["trigger_time"] is None   # 无时间 → 普通待办，不是一次性

    def test_multi_daily_times(self, conv_env):
        from openmemo.conversation import _create_task_from_ai_task
        t = _create_task_from_ai_task({"content": "吃药", "recurring": "每天08:00和21:00"}, "s1")
        assert t is not None
        # 应拆成两个任务
        from openmemo.tasks import TaskManager
        all_tasks = TaskManager().list_tasks()
        assert len(all_tasks) >= 2

    def test_what_to_do_stored_in_meta(self, conv_env):
        from openmemo.conversation import _create_task_from_ai_task
        t = _create_task_from_ai_task({"content": "查天气", "what_to_do": "查询北京天气并播报", "time": "2026-09-01 08:00"}, "s1")
        assert t is not None
        assert t["meta_data"]["what_to_do"] == "查询北京天气并播报"

    def test_priority_default_medium(self, conv_env):
        from openmemo.conversation import _create_task_from_ai_task
        t = _create_task_from_ai_task({"content": "x", "time": "2026-09-01 08:00"}, "s1")
        assert t["priority"] == "medium"

    def test_priority_high(self, conv_env):
        from openmemo.conversation import _create_task_from_ai_task
        t = _create_task_from_ai_task({"content": "x", "time": "2026-09-01 08:00", "priority": "high"}, "s1")
        assert t["priority"] == "high"


class TestApplyAiAction:
    def test_task_completed(self, conv_env):
        import asyncio
        from openmemo.conversation import _apply_ai_action
        t = conv_env.add_task("交作业", trigger_time="2026-09-01 08:00")
        asyncio.run(_apply_ai_action({"action": "task_completed", "task": {"content": "交作业"}}, "s1"))
        assert conv_env.get_task(t["task_id"])["status"] == "completed"

    def test_task_deleted(self, conv_env):
        import asyncio
        from openmemo.conversation import _apply_ai_action
        t = conv_env.add_task("交房租", trigger_time="2026-09-01 08:00")
        asyncio.run(_apply_ai_action({"action": "task_deleted", "task": {"content": "交房租"}}, "s1"))
        # 软删除：普通列表看不到，但回收站可恢复
        assert conv_env.get_task(t["task_id"])["deleted_at"] is not None
        assert all(x["task_id"] != t["task_id"] for x in conv_env.list_tasks())
        assert any(x["task_id"] == t["task_id"] for x in conv_env.list_deleted_tasks())

    def test_task_restored(self, conv_env):
        import asyncio
        from openmemo.conversation import _apply_ai_action
        t = conv_env.add_task("买牛奶", trigger_time="2026-09-01 08:00")
        conv_env.delete_task(t["task_id"])
        asyncio.run(_apply_ai_action({"action": "task_restored", "task": {"content": "买牛奶"}}, "s1"))
        restored = conv_env.get_task(t["task_id"])
        assert restored["deleted_at"] is None
        assert restored["status"] == "pending"
        assert any(x["task_id"] == t["task_id"] for x in conv_env.list_tasks())

    def test_task_restored_no_match(self, conv_env):
        import asyncio
        from openmemo.conversation import _apply_ai_action
        asyncio.run(_apply_ai_action({"action": "task_restored", "task": {"content": "不存在"}}, "s1"))  # 不崩即可

    def test_task_restored_prefers_exact(self, conv_env):
        import asyncio
        from openmemo.conversation import _apply_ai_action
        a = conv_env.add_task("买牛奶", trigger_time="2026-09-01 08:00")
        b = conv_env.add_task("帮妈妈买牛奶", trigger_time="2026-09-01 09:00")
        conv_env.delete_task(a["task_id"])
        conv_env.delete_task(b["task_id"])
        asyncio.run(_apply_ai_action({"action": "task_restored", "task": {"content": "买牛奶"}}, "s1"))
        # 精确匹配的"买牛奶"被恢复，"帮妈妈买牛奶"仍在回收站
        assert conv_env.get_task(a["task_id"])["deleted_at"] is None
        assert conv_env.get_task(b["task_id"])["deleted_at"] is not None

    def test_task_updated_content(self, conv_env):
        import asyncio
        from openmemo.conversation import _apply_ai_action
        t = conv_env.add_task("晨跑", trigger_time="2026-09-01 07:00")
        asyncio.run(_apply_ai_action({"action": "task_updated", "task": {"content": "晨跑", "new_content": "晚上跑步"}}, "s1"))
        assert conv_env.get_task(t["task_id"])["content"] == "晚上跑步"

    def test_task_updated_time(self, conv_env):
        import asyncio
        from openmemo.conversation import _apply_ai_action
        t = conv_env.add_task("晨跑", trigger_time="2026-09-01 07:00")
        asyncio.run(_apply_ai_action({"action": "task_updated", "task": {"content": "晨跑", "time": "2026-09-02 06:00"}}, "s1"))
        assert conv_env.get_task(t["task_id"])["trigger_time"] == "2026-09-02 06:00"

    def test_task_updated_status(self, conv_env):
        import asyncio
        from openmemo.conversation import _apply_ai_action
        t = conv_env.add_task("晨跑", trigger_time="2026-09-01 07:00")
        asyncio.run(_apply_ai_action({"action": "task_updated", "task": {"content": "晨跑", "status": "completed"}}, "s1"))
        assert conv_env.get_task(t["task_id"])["status"] == "completed"

    def test_task_updated_no_match(self, conv_env):
        import asyncio
        from openmemo.conversation import _apply_ai_action
        asyncio.run(_apply_ai_action({"action": "task_updated", "task": {"content": "不存在"}}, "s1"))  # 不崩即可

    def test_task_added_single(self, conv_env):
        import asyncio
        from openmemo.conversation import _apply_ai_action
        asyncio.run(_apply_ai_action({"action": "task_added", "task": {"content": "买牛奶", "time": "2026-09-01 09:00"}}, "s1"))
        tasks = conv_env.list_tasks()
        assert any(t["content"] == "买牛奶" for t in tasks)

    def test_task_added_multi(self, conv_env):
        import asyncio
        from openmemo.conversation import _apply_ai_action
        asyncio.run(_apply_ai_action({"action": "task_added", "tasks": [
            {"content": "任务A", "time": "2026-09-01 09:00"},
            {"content": "任务B", "time": "2026-09-01 10:00"},
        ]}, "s1"))
        tasks = conv_env.list_tasks()
        assert sum(1 for t in tasks if t["content"] in ("任务A", "任务B")) == 2

    def test_task_added_dedup_within_response(self, conv_env):
        """同一轮 AI 回复里 内容+时间 相同的任务只建一个。"""
        import asyncio
        from openmemo.conversation import _apply_ai_action
        asyncio.run(_apply_ai_action({"action": "task_added", "tasks": [
            {"content": "重复", "time": "2026-09-01 09:00"},
            {"content": "重复", "time": "2026-09-01 09:00"},
        ]}, "s1"))
        tasks = conv_env.list_tasks()
        assert sum(1 for t in tasks if t["content"] == "重复") == 1

    def test_reminder_set_with_appointment(self, conv_env):
        import asyncio
        from openmemo.conversation import _apply_ai_action
        asyncio.run(_apply_ai_action({"action": "reminder_set", "appointment": {"at": "2026-09-01 09:00", "read_aloud": "开会啦"}}, "s1"))
        tasks = conv_env.list_tasks()
        assert len(tasks) >= 1

    def test_chat_action_noop(self, conv_env):
        import asyncio
        from openmemo.conversation import _apply_ai_action
        asyncio.run(_apply_ai_action({"action": "chat", "reply": "你好"}, "s1"))  # 不崩

    def test_task_deleted_prefers_exact_match(self, conv_env):
        """回归：删"买牛奶"不得误删"帮妈妈买牛奶"（精确匹配优先）。"""
        import asyncio
        from openmemo.conversation import _apply_ai_action, _match_task_by_content
        a = conv_env.add_task("买牛奶", trigger_time="2026-09-01 08:00")
        b = conv_env.add_task("帮妈妈买牛奶", trigger_time="2026-09-01 09:00")

        target = _match_task_by_content("买牛奶")
        assert target["task_id"] == a["task_id"], f"应精确匹配买牛奶，却命中: {target['content']}"

        asyncio.run(_apply_ai_action({"action": "task_deleted", "task": {"content": "买牛奶"}}, "s1"))
        assert conv_env.get_task(a["task_id"])["deleted_at"] is not None
        assert conv_env.get_task(b["task_id"])["deleted_at"] is None, "帮妈妈买牛奶 被误删！"

    def test_match_prefers_pending(self, conv_env):
        from openmemo.conversation import _match_task_by_content
        done = conv_env.add_task("写作业", trigger_time="2026-09-01 08:00")
        conv_env.complete_task(done["task_id"])
        pending = conv_env.add_task("写作业", trigger_time="2026-09-02 08:00")
        target = _match_task_by_content("写作业")
        assert target["task_id"] == pending["task_id"]

    def test_match_no_result(self, conv_env):
        from openmemo.conversation import _match_task_by_content
        assert _match_task_by_content("不存在的东西") is None
        assert _match_task_by_content("") is None
        assert _match_task_by_content(None) is None

    def test_collecting_noop(self, conv_env):
        import asyncio
        from openmemo.conversation import _apply_ai_action
        asyncio.run(_apply_ai_action({"action": "collecting"}, "s1"))  # 不崩


class TestMultiDailyExtract:
    def test_two_times(self):
        from openmemo.conversation import _extract_multi_daily_times
        assert _extract_multi_daily_times("每天08:00和21:00") == ["08:00", "21:00"]

    def test_two_chinese_times(self):
        from openmemo.conversation import _extract_multi_daily_times
        assert _extract_multi_daily_times("每天8点和21点") == ["08:00", "21:00"]

    def test_single_time_empty(self):
        from openmemo.conversation import _extract_multi_daily_times
        assert _extract_multi_daily_times("每天08:00") == []

    def test_none_empty(self):
        from openmemo.conversation import _extract_multi_daily_times
        assert _extract_multi_daily_times(None) == []

    def test_three_times(self):
        from openmemo.conversation import _extract_multi_daily_times
        assert _extract_multi_daily_times("每天08:00、12:00和21:00") == ["08:00", "12:00", "21:00"]


class TestDeriveContent:
    def test_content_wins(self):
        from openmemo.conversation import _derive_content
        assert _derive_content({"content": "任务", "reminder_text": "提醒"}) == "任务"

    def test_reminder_fallback(self):
        from openmemo.conversation import _derive_content
        assert _derive_content({"reminder_text": "该吃药啦"}) == "该吃药啦"

    def test_reminder_truncated(self):
        from openmemo.conversation import _derive_content
        long = "很" * 100
        r = _derive_content({"reminder_text": long})
        assert len(r) <= 41

    def test_time_only(self):
        from openmemo.conversation import _derive_content
        assert _derive_content({"time": "2026-09-01 08:00"}) == "提醒"

    def test_nothing(self):
        from openmemo.conversation import _derive_content
        assert _derive_content({}) is None

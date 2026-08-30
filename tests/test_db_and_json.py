"""JSON 提取/修复深度测试 + 更多数据库操作测试。"""
import pytest
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path


class TestExtractJsonDeep:
    def test_exact(self):
        from openmemo.ai import _extract_json
        assert _extract_json('{"a":1}') == {"a": 1}

    def test_markdown_block(self):
        from openmemo.ai import _extract_json
        r = _extract_json('```json\n{"action":"chat"}\n```')
        assert r == {"action": "chat"}

    def test_embedded_text(self):
        from openmemo.ai import _extract_json
        r = _extract_json('好的{"action":"chat"}完成')
        assert r == {"action": "chat"}

    def test_truncated_brace_repair(self):
        from openmemo.ai import _extract_json
        r = _extract_json('{"action":"task_added","task":{"content":"x"}')
        assert r is not None
        assert r["task"]["content"] == "x"

    def test_truncated_string_repair(self):
        from openmemo.ai import _extract_json
        r = _extract_json('{"reply":"你好')
        assert r is not None
        assert "reply" in r

    def test_trailing_comma(self):
        from openmemo.ai import _extract_json
        r = _extract_json('{"action":"chat","reply":"ok",}')
        assert r["reply"] == "ok"

    def test_nested_trailing_comma(self):
        from openmemo.ai import _extract_json
        r = _extract_json('{"a":{"b":1,},}')
        assert r["a"]["b"] == 1

    def test_garbage_none(self):
        from openmemo.ai import _extract_json
        assert _extract_json("不是json") is None

    def test_empty_none(self):
        from openmemo.ai import _extract_json
        assert _extract_json("") is None

    def test_non_dict_json_none(self):
        from openmemo.ai import _extract_json
        assert _extract_json("[1,2,3]") is None

    def test_repair_candidates_count(self):
        from openmemo.ai import _repair_candidates
        assert len(list(_repair_candidates('{"a":1'))) >= 5


class TestTaskManagerDeep:
    @pytest.fixture
    def mgr(self, tmp_path, monkeypatch):
        import openmemo.config as cfg
        import openmemo.tasks as tm
        db = tmp_path / "db.sqlite"
        monkeypatch.setattr(cfg, "DB_PATH", db)
        monkeypatch.setattr(tm, "DB_PATH", db)
        tm.init_db()
        return tm.TaskManager()

    def test_roundtrip(self, mgr):
        t = mgr.add_task("任务", trigger_time="2026-09-01 08:00", priority="high")
        got = mgr.get_task(t["task_id"])
        assert got["content"] == "任务"
        assert got["priority"] == "high"
        assert got["status"] == "pending"

    def test_meta_data_roundtrip(self, mgr):
        t = mgr.add_task("任务", meta_data={"what_to_do": "执行", "nested": {"a": 1}})
        got = mgr.get_task(t["task_id"])
        assert got["meta_data"]["what_to_do"] == "执行"

    def test_list_empty(self, mgr):
        assert mgr.list_tasks() == []

    def test_list_status_filter(self, mgr):
        mgr.add_task("A")
        t = mgr.add_task("B")
        mgr.complete_task(t["task_id"])
        assert len(mgr.list_tasks(status="pending")) == 1
        assert len(mgr.list_tasks(status="completed")) == 1

    def test_list_limit(self, mgr):
        for i in range(5):
            mgr.add_task(f"T{i}")
        assert len(mgr.list_tasks(limit=3)) == 3

    def test_update_ignores_unknown_field(self, mgr):
        t = mgr.add_task("A")
        mgr.update_task(t["task_id"], bogus_field="x", content="B")
        assert mgr.get_task(t["task_id"])["content"] == "B"

    def test_mark_reminded(self, mgr):
        t = mgr.add_task("A")
        mgr.mark_reminded(t["task_id"])
        assert mgr.get_task(t["task_id"])["reminder_sent"] == 1

    def test_get_pending_reminders(self, mgr):
        past = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
        mgr.add_task("到期", trigger_time=past)
        mgr.add_task("未来", trigger_time="2026-09-01 08:00")
        rem = mgr.get_pending_reminders()
        assert len(rem) == 1
        assert rem[0]["content"] == "到期"

    def test_delete_finished_old_keeps_pending(self, mgr):
        import openmemo.tasks as tm
        done = mgr.add_task("完成")
        mgr.complete_task(done["task_id"])
        pending = mgr.add_task("待办")
        conn = sqlite3.connect(str(tm.DB_PATH))
        conn.execute(
            "UPDATE tasks SET updated_at = datetime('now','localtime','-25 hours') WHERE task_id=?",
            (done["task_id"],),
        )
        conn.commit()
        conn.close()
        n = mgr.delete_finished_old(older_than_hours=24)
        assert n == 1
        assert mgr.get_task(pending["task_id"]) is not None

    def test_delete_logs_for_watchdog(self, mgr):
        """删除任务必须留痕（看护区分 已删 vs 从未建）。"""
        import openmemo.tasks as tm
        t = mgr.add_task("买牛奶")
        mgr.delete_task(t["task_id"])
        conn = sqlite3.connect(str(tm.DB_PATH))
        row = conn.execute("SELECT content, deleted_by FROM task_deletions").fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "买牛奶"
        assert row[1] == "user"

    def test_delete_log_cleanup_tag(self, mgr):
        """自动清理删除也要留痕，标记 deleted_by='cleanup'。"""
        import openmemo.tasks as tm
        t = mgr.add_task("旧完成")
        mgr.complete_task(t["task_id"])
        conn = sqlite3.connect(str(tm.DB_PATH))
        conn.execute(
            "UPDATE tasks SET updated_at = datetime('now','localtime','-25 hours') WHERE task_id=?",
            (t["task_id"],),
        )
        conn.commit()
        conn.close()
        mgr.delete_finished_old(older_than_hours=24)
        conn = sqlite3.connect(str(tm.DB_PATH))
        row = conn.execute(
            "SELECT deleted_by FROM task_deletions WHERE task_id=?", (t["task_id"],)
        ).fetchone()
        conn.close()
        assert row is not None and row[0] == "cleanup"

    def test_reminders_crud(self, mgr):
        mgr.add_reminder(1, "内容", "消息")
        mgr.add_reminder(1, "内容", "消息2")
        rs = mgr.list_reminders()
        assert len(rs) == 2
        rs2 = mgr.list_reminders(after_id=1)
        assert len(rs2) == 1

    def test_alerts_dedup(self, mgr):
        mgr.add_alert("promise", "同一消息")
        assert mgr.alert_exists("同一消息") is True
        assert mgr.alert_exists("别的消息") is False

    def test_alerts_list(self, mgr):
        mgr.add_alert("autofix", "修复了")
        mgr.add_alert("promise", "未落地")
        alerts = mgr.list_alerts()
        assert len(alerts) == 2
        assert alerts[0]["type"] == "promise"  # 最新在前


class TestConversationManagerDeep:
    @pytest.fixture
    def cm(self, tmp_path, monkeypatch):
        import openmemo.config as cfg
        import openmemo.tasks as tm
        db = tmp_path / "db.sqlite"
        monkeypatch.setattr(cfg, "DB_PATH", db)
        monkeypatch.setattr(tm, "DB_PATH", db)
        tm.init_db()
        return tm.ConversationManager()

    def test_history_limit(self, cm):
        for i in range(15):
            cm.add_message("s", "user", f"m{i}")
        h = cm.get_history("s", limit=5)
        assert len(h) == 5
        # 最新 5 条
        assert h[-1]["content"] == "m14"

    def test_context_for_ai_strips_intent(self, cm):
        cm.add_message("s", "user", "你好", intent="chat")
        ctx = cm.get_context_for_ai("s")
        assert ctx == [{"role": "user", "content": "你好"}]

    def test_session_isolation(self, cm):
        cm.add_message("a", "user", "A的消息")
        cm.add_message("b", "user", "B的消息")
        assert len(cm.get_history("a")) == 1

    def test_pending_slots_roundtrip(self, cm):
        cm.save_pending_slots("s", {"content": "任务"}, ["time"], "原话")
        p = cm.get_pending_slots("s")
        assert p["partial_slots"]["content"] == "任务"
        assert p["missing_slots"] == ["time"]
        assert p["original_message"] == "原话"

    def test_pending_slots_replaced(self, cm):
        cm.save_pending_slots("s", {"content": "A"}, ["time"])
        cm.save_pending_slots("s", {"content": "B"}, ["time", "date"])
        p = cm.get_pending_slots("s")
        assert p["partial_slots"]["content"] == "B"

    def test_list_sessions_ordering(self, cm):
        cm.add_message("s1", "user", "先")
        cm.add_message("s2", "user", "后")
        sessions = cm.list_sessions()
        assert sessions[0]["session_id"] == "s2"

    def test_list_sessions_title(self, cm):
        # 隐私：侧边栏绝不显示消息内容
        cm.add_message("s1", "user", "我的第一个任务")
        sessions = cm.list_sessions()
        assert "我的第一个任务" not in sessions[0]["title"]
        assert sessions[0]["title"] == "匿名聊天"

    def test_list_sessions_speaker_title(self, cm):
        # 说话人专属会话 → 「X 的聊天」，不显示内容
        cm.add_message("speaker_Ethan", "user", "明天什么天儿啊")
        sessions = cm.list_sessions()
        assert sessions[0]["title"] == "Ethan 的聊天"

    def test_list_sessions_custom_title(self, cm):
        # 匿名会话：有自定义标题才显示
        cm.add_message("s1", "user", "内容内容内容")
        cm.rename_session("s1", "我的标签")
        sessions = cm.list_sessions()
        assert sessions[0]["title"] == "我的标签"

    def test_delete_session(self, cm):
        cm.add_message("s1", "user", "x")
        cm.add_message("s1", "assistant", "y")
        cm.delete_session("s1")
        assert cm.get_history("s1") == []

    def test_delete_session_clears_pending(self, cm):
        cm.save_pending_slots("s1", {"a": 1}, ["b"])
        cm.delete_session("s1")
        assert cm.get_pending_slots("s1") is None

"""Unit tests for OpenMemo task management"""
import pytest
import os
import tempfile
from openmemo.tasks import TaskManager, ConversationManager, init_db


@pytest.fixture
def task_manager(tmp_path):
    """Create a TaskManager with a temporary database"""
    # Override DB path for testing
    import openmemo.tasks as tasks_module
    original_db = tasks_module.DB_PATH
    tasks_module.DB_PATH = tmp_path / "test.db"
    init_db()
    tm = TaskManager()
    yield tm
    tasks_module.DB_PATH = original_db


@pytest.fixture
def conv_manager(tmp_path):
    """Create a ConversationManager with a temporary database"""
    import openmemo.tasks as tasks_module
    original_db = tasks_module.DB_PATH
    tasks_module.DB_PATH = tmp_path / "test.db"
    init_db()
    cm = ConversationManager()
    yield cm
    tasks_module.DB_PATH = original_db


class TestTaskManager:
    def test_add_task(self, task_manager):
        task = task_manager.add_task("Test task", trigger_time="2026-07-25 10:00")
        assert task is not None
        assert task["content"] == "Test task"
        assert task["trigger_time"] == "2026-07-25 10:00"
        assert task["status"] == "pending"
        assert task["priority"] == "medium"
    
    def test_get_task(self, task_manager):
        task = task_manager.add_task("Get test")
        fetched = task_manager.get_task(task["task_id"])
        assert fetched["content"] == "Get test"
    
    def test_complete_task(self, task_manager):
        task = task_manager.add_task("Complete test")
        result = task_manager.complete_task(task["task_id"])
        assert result["status"] == "completed"
    
    def test_cancel_task(self, task_manager):
        task = task_manager.add_task("Cancel test")
        result = task_manager.cancel_task(task["task_id"])
        assert result["status"] == "cancelled"
    
    def test_delete_task(self, task_manager):
        task = task_manager.add_task("Delete test")
        success = task_manager.delete_task(task["task_id"])
        assert success is True
        assert task_manager.get_task(task["task_id"]) is None
    
    def test_list_tasks(self, task_manager):
        task_manager.add_task("Task 1", priority="high")
        task_manager.add_task("Task 2", priority="low")
        task_manager.add_task("Task 3", priority="medium")
        
        all_tasks = task_manager.list_tasks()
        assert len(all_tasks) == 3
        
        pending = task_manager.list_tasks(status="pending")
        assert len(pending) == 3
    
    def test_search_tasks(self, task_manager):
        task_manager.add_task("Buy groceries")
        task_manager.add_task("Buy milk")
        task_manager.add_task("Walk the dog")
        
        results = task_manager.search_tasks("Buy")
        assert len(results) == 2
    
    def test_update_task(self, task_manager):
        task = task_manager.add_task("Original")
        updated = task_manager.update_task(task["task_id"], content="Updated", priority="high")
        assert updated["content"] == "Updated"
        assert updated["priority"] == "high"
    
    def test_priority_ordering(self, task_manager):
        task_manager.add_task("Low task", priority="low")
        task_manager.add_task("High task", priority="high")
        task_manager.add_task("Medium task", priority="medium")
        
        tasks = task_manager.list_tasks()
        # High priority should come first
        assert tasks[0]["priority"] == "high"

    def test_delete_finished_old(self, task_manager):
        """已完结超 24h 的任务被清理；待办任务绝不动。"""
        import openmemo.tasks as tasks_module
        import sqlite3

        # 建 4 个任务
        done_old = task_manager.add_task("老完成", priority="medium")
        done_new = task_manager.add_task("新完成", priority="medium")
        cancelled_old = task_manager.add_task("老取消", priority="medium")
        pending = task_manager.add_task("待办", priority="medium")

        # 完成/取消
        task_manager.complete_task(done_old["task_id"])
        task_manager.complete_task(done_new["task_id"])
        task_manager.cancel_task(cancelled_old["task_id"])

        # 把 done_old / cancelled_old 的 updated_at 改到 25 小时前
        conn = tasks_module.get_db()
        cur = conn.cursor()
        cur.execute(
            "UPDATE tasks SET updated_at = datetime('now', 'localtime', '-25 hours') WHERE task_id IN (?, ?)",
            (done_old["task_id"], cancelled_old["task_id"]),
        )
        conn.commit()
        conn.close()

        deleted = task_manager.delete_finished_old(older_than_hours=24)
        assert deleted == 2, f"应删除 2 条，实际 {deleted}"

        # 老的任务没了，新的完成/取消还在，待办还在
        assert task_manager.get_task(done_old["task_id"]) is None
        assert task_manager.get_task(cancelled_old["task_id"]) is None
        assert task_manager.get_task(done_new["task_id"]) is not None
        assert task_manager.get_task(pending["task_id"]) is not None


class TestConversationManager:
    def test_add_and_get_history(self, conv_manager):
        conv_manager.add_message("session1", "user", "Hello")
        conv_manager.add_message("session1", "assistant", "Hi there!")
        
        history = conv_manager.get_history("session1")
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[1]["role"] == "assistant"
    
    def test_session_isolation(self, conv_manager):
        conv_manager.add_message("session1", "user", "Message 1")
        conv_manager.add_message("session2", "user", "Message 2")
        
        history1 = conv_manager.get_history("session1")
        history2 = conv_manager.get_history("session2")
        
        assert len(history1) == 1
        assert len(history2) == 1
        assert history1[0]["content"] == "Message 1"
    
    def test_pending_slots(self, conv_manager):
        conv_manager.save_pending_slots("session1", 
                                         {"content": "Meeting"}, 
                                         ["time"],
                                         "Add a meeting")
        
        pending = conv_manager.get_pending_slots("session1")
        assert pending is not None
        assert pending["partial_slots"]["content"] == "Meeting"
        assert "time" in pending["missing_slots"]
    
    def test_clear_pending_slots(self, conv_manager):
        conv_manager.save_pending_slots("session1", {"content": "Test"}, ["time"])
        conv_manager.clear_pending_slots("session1")
        
        pending = conv_manager.get_pending_slots("session1")
        assert pending is None
    
    def test_get_context_for_ai(self, conv_manager):
        conv_manager.add_message("session1", "user", "Hello")
        conv_manager.add_message("session1", "assistant", "Hi!")
        
        context = conv_manager.get_context_for_ai("session1")
        assert len(context) == 2
        assert context[0] == {"role": "user", "content": "Hello"}

    def test_get_history_returns_newest_first_window(self, conv_manager):
        """回归测试：历史必须返回【最新】的 limit 条（按时间正序），
        而不是最早的那几条——否则长对话里 AI 看不到最近上下文。"""
        for i in range(1, 8):
            conv_manager.add_message("s_hist", "user", f"msg-{i}")

        history = conv_manager.get_history("s_hist", limit=3)
        assert len(history) == 3
        # 应该是最新的 3 条：msg-5/6/7（正序）
        assert [m["content"] for m in history] == ["msg-5", "msg-6", "msg-7"]

    def test_get_context_for_ai_uses_latest(self, conv_manager):
        """回归测试：AI 上下文应基于最近消息（V1.0 修复的 get_history 顺序 bug）。"""
        for i in range(1, 10):
            conv_manager.add_message("s_ctx", "user", f"ctx-{i}")

        context = conv_manager.get_context_for_ai("s_ctx", limit=4)
        contents = [m["content"] for m in context]
        assert contents == ["ctx-6", "ctx-7", "ctx-8", "ctx-9"]



"""Unit tests for OpenMemo task management"""
import pytest
import os
import tempfile
from openmemo.tasks import TaskManager, ConversationManager, init_db
from openmemo.conversation import parse_time_string


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


class TestTimeParsing:
    def test_tomorrow(self):
        from datetime import datetime, timedelta
        result = parse_time_string("明天 3点")
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        assert result.startswith(tomorrow)
    
    def test_today(self):
        from datetime import datetime
        result = parse_time_string("今天下午2点")
        today = datetime.now().strftime("%Y-%m-%d")
        assert result.startswith(today)
        assert "14" in result or "15" in result
    
    def test_specific_time(self):
        result = parse_time_string("2026-07-25 15:30")
        assert result == "2026-07-25 15:30"
    
    def test_tonight(self):
        from datetime import datetime
        result = parse_time_string("今晚8点")
        today = datetime.now().strftime("%Y-%m-%d")
        assert result.startswith(today)
        assert "20" in result
    
    def test_none_input(self):
        result = parse_time_string(None)
        assert result is None
    
    def test_empty_input(self):
        result = parse_time_string("")
        assert result is None

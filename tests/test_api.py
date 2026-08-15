"""API-level tests: FastAPI endpoints with temp DB (no external calls)."""
import pytest
import os
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Point DB to temp BEFORE importing app modules
import openmemo.tasks as tasks_module
_tmpdir = tempfile.mkdtemp()
tasks_module.DB_PATH = __import__('pathlib').Path(_tmpdir) / "test_api.db"
tasks_module.init_db()

from openmemo.server import app
from openmemo.tasks import TaskManager
from openmemo.scheduler import schedule_task, scheduler
from fastapi.testclient import TestClient

client = TestClient(app)
tm = TaskManager()


@pytest.fixture(autouse=True)
def cleanup_tasks():
    yield
    # 清掉所有测试任务（直接清表）
    import sqlite3
    conn = sqlite3.connect(str(tasks_module.DB_PATH))
    conn.execute("DELETE FROM tasks")
    conn.execute("DELETE FROM conversations")
    conn.execute("DELETE FROM reminders")
    conn.execute("DELETE FROM alerts")
    conn.commit()
    conn.close()


class TestHealth:
    def test_health(self):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "running"
        assert r.json()["version"] == "1.0.0"

    def test_no_cache_header(self):
        r = client.get("/api/health")
        assert r.headers.get("Cache-Control") == "no-store"


class TestTasksAPI:
    def test_create_task(self):
        r = client.post("/api/tasks", json={"content": "买牛奶", "trigger_time": "2026-09-01 08:00"})
        assert r.status_code == 200
        d = r.json()
        assert d["success"] is True
        assert d["task"]["content"] == "买牛奶"

    def test_create_task_requires_content(self):
        r = client.post("/api/tasks", json={})
        assert r.status_code == 400

    def test_list_tasks(self):
        client.post("/api/tasks", json={"content": "A"})
        client.post("/api/tasks", json={"content": "B", "status": None})
        r = client.get("/api/tasks")
        assert r.status_code == 200
        assert r.json()["count"] >= 2

    def test_list_tasks_by_status(self):
        client.post("/api/tasks", json={"content": "C"})
        r = client.get("/api/tasks", params={"status": "pending"})
        assert all(t["status"] == "pending" for t in r.json()["tasks"])

    def test_get_task_404(self):
        r = client.get("/api/tasks/999999")
        assert r.status_code == 404

    def test_update_task_status(self):
        t = client.post("/api/tasks", json={"content": "D"}).json()["task"]
        r = client.patch(f"/api/tasks/{t['task_id']}", json={"status": "completed"})
        assert r.status_code == 200
        assert r.json()["task"]["status"] == "completed"

    def test_delete_task(self):
        t = client.post("/api/tasks", json={"content": "E"}).json()["task"]
        r = client.delete(f"/api/tasks/{t['task_id']}")
        assert r.json()["success"] is True
        assert client.get(f"/api/tasks/{t['task_id']}").status_code == 404

    def test_chat_requires_message(self):
        r = client.post("/api/chat", json={})
        assert r.status_code == 400

    def test_speak_requires_text(self):
        r = client.post("/api/speak", json={})
        assert r.status_code == 400


class TestSessionsAPI:
    def test_sessions_empty(self):
        r = client.get("/api/sessions")
        assert r.status_code == 200
        assert "sessions" in r.json()

    def test_delete_session(self):
        r = client.delete("/api/sessions/nonexistent_xyz")
        assert r.json()["success"] is True


class TestSchedulerIntegration:
    def test_schedule_future_task(self):
        """未来任务应被调度（job 存在）"""
        future = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
        t = tm.add_task("调度测试", trigger_time=future)
        schedule_task(t["task_id"], future)
        assert scheduler.get_job(f"task_{t['task_id']}") is not None

    def test_schedule_past_task_skipped(self):
        """过去时间不应调度（静默跳过）"""
        past = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
        t = tm.add_task("过期任务", trigger_time=past)
        schedule_task(t["task_id"], past)
        assert scheduler.get_job(f"task_{t['task_id']}") is None

    def test_reschedule_replaces_job(self):
        """同任务二次调度应替换旧 job 而非叠加"""
        f1 = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
        f2 = (datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")
        t = tm.add_task("重排", trigger_time=f1)
        schedule_task(t["task_id"], f1)
        schedule_task(t["task_id"], f2)
        job = scheduler.get_job(f"task_{t['task_id']}")
        assert job is not None
        # replace_existing=True → 只有一个 job
        assert str(job.trigger) == str(scheduler.get_job(f"task_{t['task_id']}").trigger)


class TestReminderAndAlert:
    def test_reminders_endpoint(self):
        r = client.get("/api/reminders")
        assert r.status_code == 200
        assert "reminders" in r.json()

    def test_alerts_endpoint(self):
        r = client.get("/api/alerts")
        assert r.status_code == 200
        assert "alerts" in r.json()

    def test_add_reminder_then_list(self):
        tm.add_reminder(1, "喝水", "该喝水啦")
        r = client.get("/api/reminders")
        assert any(x["message"] == "该喝水啦" for x in r.json()["reminders"])

"""多层防御监控测试：兑现校验、AI 健康、调度巡检、语音送达。"""
import pytest
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path


@pytest.fixture
def mon_env(tmp_path, monkeypatch):
    """隔离 DB（config/tasks/watchdog/monitor 各处绑定）。"""
    import openmemo.config as config_module
    import openmemo.tasks as tasks_module
    import openmemo.watchdog as watchdog_module
    import openmemo.monitor as monitor_module

    db = tmp_path / "mon.db"
    monkeypatch.setattr(config_module, "DB_PATH", db)
    monkeypatch.setattr(tasks_module, "DB_PATH", db)
    monkeypatch.setattr(watchdog_module, "DB_PATH", db)
    tasks_module.init_db()
    mgr = tasks_module.TaskManager()
    yield {"mgr": mgr, "mon": monitor_module}
    conn = sqlite3.connect(str(db))
    conn.execute("DELETE FROM tasks")
    conn.execute("DELETE FROM alerts")
    conn.commit()
    conn.close()


class TestPromiseDetection:
    def test_reply_promises(self, mon_env):
        mon = mon_env["mon"]
        assert mon.reply_promises("好的，已帮你记下明天的任务") is True
        assert mon.reply_promises("我会提醒你的") is True
        assert mon.reply_promises("今天天气不错") is False
        assert mon.reply_promises("") is False
        assert mon.reply_promises(None) is False

    def test_user_intent(self, mon_env):
        mon = mon_env["mon"]
        assert mon.user_has_task_intent("提醒我明天买牛奶") is True
        assert mon.user_has_task_intent("记住吃药") is True
        assert mon.user_has_task_intent("你好呀") is False
        assert mon.user_has_task_intent("给我讲个笑话") is False


class TestVerifyLanding:
    def test_no_promise_no_problem(self, mon_env):
        mon = mon_env["mon"]
        p = mon.verify_landing("今天天气怎么样", "今天晴天", "chat", 0, "s1")
        assert p == []

    def test_promise_but_nothing_created(self, mon_env):
        mon = mon_env["mon"]
        p = mon.verify_landing("提醒我明天买牛奶", "好的，已帮你记下", "chat", 0, "s1")
        assert len(p) >= 1
        assert "承诺" in p[0] or "兑现" in p[0]

    def test_task_added_but_zero_landed(self, mon_env):
        mon = mon_env["mon"]
        p = mon.verify_landing("提醒我买牛奶", "已建好", "task_added", 0, "s1")
        assert len(p) >= 1

    def test_promise_fulfilled_no_problem(self, mon_env):
        mon = mon_env["mon"]
        p = mon.verify_landing("提醒我买牛奶", "好的，已帮你记下", "task_added", 1, "s1")
        assert p == []

    def test_alert_dedup(self, mon_env):
        mon = mon_env["mon"]
        mon.verify_landing("提醒我买牛奶", "好的，已帮你记下", "chat", 0, "s1")
        p2 = mon.verify_landing("提醒我买牛奶", "好的，已帮你记下", "chat", 0, "s1")
        # 24h 去重：第二次不再产生新告警（alert_exists 挡住）
        alerts = mon_env["mgr"].list_alerts()
        assert len(alerts) <= 1


class TestAiHealth:
    def test_failure_threshold_alerts(self, mon_env):
        mon = mon_env["mon"]
        # 重置模块状态（跨测试隔离）
        mon._ai_failures = 0
        mon._AI_FAILURE_ALERTED = False
        alert_msg = None
        for _ in range(5):
            r = mon.note_ai_failure(False)
            if r:
                alert_msg = r
        assert alert_msg is not None, "达到阈值应产生告警消息"
        assert "AI" in alert_msg
        # 告警确实入库
        alerts = mon_env["mgr"].list_alerts()
        assert any("AI健康" in a["message"] for a in alerts)

    def test_success_resets_counter(self, mon_env):
        mon = mon_env["mon"]
        mon._ai_failures = 0
        mon._AI_FAILURE_ALERTED = False
        mon.note_ai_failure(False)
        mon.note_ai_failure(False)
        assert mon.note_ai_failure(True) is None
        # 重置后再失败不会立刻告警
        assert mon.note_ai_failure(False) is None

    def test_alert_only_once(self, mon_env):
        mon = mon_env["mon"]
        mon._ai_failures = 0
        mon._AI_FAILURE_ALERTED = False
        for _ in range(10):
            mon.note_ai_failure(False)
        alerts = mon_env["mgr"].list_alerts()
        ai_alerts = [a for a in alerts if "AI健康" in a["message"] or "AI" in a["message"]]
        assert len(ai_alerts) <= 1


class TestReconcileJobs:
    def test_missing_job_rearmed(self, mon_env):
        mon = mon_env["mon"]
        import openmemo.scheduler as sch
        future = (datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")
        t = mon_env["mgr"].add_task("待提醒", trigger_time=future)
        fixed = mon.reconcile_jobs()
        # 至少补排了当前任务（若此前已有 job 则 fixed 可能为 0，但任务必须有 job）
        job = sch.scheduler.get_job(f"task_{t['task_id']}")
        assert job is not None, f"任务 {t['task_id']} 应被补排"

    def test_existing_job_not_duplicated(self, mon_env):
        mon = mon_env["mon"]
        import openmemo.scheduler as sch
        future = (datetime.now() + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")
        t = mon_env["mgr"].add_task("已有job", trigger_time=future)
        sch.schedule_task(t["task_id"], future)
        fixed = mon.reconcile_jobs()
        assert fixed == 0
        assert sch.scheduler.get_job(f"task_{t['task_id']}") is not None

    def test_past_task_not_rearmed(self, mon_env):
        mon = mon_env["mon"]
        past = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
        t = mon_env["mgr"].add_task("已过期", trigger_time=past)
        fixed = mon.reconcile_jobs()
        assert fixed == 0   # 过去的任务不补排（交给看护处理）


class TestSpeakMonitor:
    def test_success_no_alert(self, mon_env):
        mon = mon_env["mon"]
        assert mon.monitor_speak_ok(True, "内容", 1) is True
        assert mon_env["mgr"].list_alerts() == []

    def test_failure_alerts(self, mon_env):
        mon = mon_env["mon"]
        assert mon.monitor_speak_ok(False, "播报失败的内容", 42) is False
        alerts = mon_env["mgr"].list_alerts()
        assert len(alerts) == 1
        assert "42" in alerts[0]["message"]

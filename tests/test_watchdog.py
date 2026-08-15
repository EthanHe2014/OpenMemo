"""Watchdog 自动化修复逻辑测试（完全隔离的临时 DB）。"""
import pytest
import sqlite3
from datetime import datetime, timedelta


@pytest.fixture
def wd_env(tmp_path, monkeypatch):
    """把 DB_PATH（config/tasks/watchdog 三处绑定）指向临时文件。"""
    import openmemo.config as config_module
    import openmemo.tasks as tasks_module
    import openmemo.watchdog as watchdog_module
    from openmemo.watchdog import run_watchdog

    db = tmp_path / "wd.db"
    # watchdog._db() 用自己模块里 from .config import DB_PATH 的快照值
    monkeypatch.setattr(config_module, "DB_PATH", db)
    monkeypatch.setattr(tasks_module, "DB_PATH", db)
    monkeypatch.setattr(watchdog_module, "DB_PATH", db)
    tasks_module.init_db()
    mgr = tasks_module.TaskManager()

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    yield {"mgr": mgr, "conn": conn, "run": run_watchdog}
    conn.close()


class TestWatchdogAutoFix:
    def test_overdue_task_cancelled(self, wd_env):
        """近 24h 新建、时间已过、未提醒的任务 → 自动取消"""
        mgr = wd_env["mgr"]
        past = (datetime.now() - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")
        t = mgr.add_task("过期任务", trigger_time=past)

        problems = wd_env["run"](hours=24)
        assert any("过期" in p for p in problems), f"应报过期问题: {problems}"
        assert mgr.get_task(t["task_id"])["status"] == "cancelled"

    def test_duplicate_tasks_deduped(self, wd_env):
        """同内容同时 3 分钟内 → 删除后建的，保留先建的"""
        mgr = wd_env["mgr"]
        conn = wd_env["conn"]
        t1 = mgr.add_task("重复任务", trigger_time="2026-09-01 09:00")
        t2 = mgr.add_task("重复任务", trigger_time="2026-09-01 09:00")
        # 把 t1 的 created_at 改早 1 分钟
        conn.execute(
            "UPDATE tasks SET created_at = datetime('now','localtime','-1 minutes') WHERE task_id=?",
            (t1["task_id"],),
        )
        conn.commit()

        problems = wd_env["run"](hours=24)
        assert any("重复" in p for p in problems), f"应报重复问题: {problems}"
        assert mgr.get_task(t1["task_id"]) is not None, "先建的应保留"
        assert mgr.get_task(t2["task_id"]) is None, "后建的应删除"

    def test_normal_task_untouched(self, wd_env):
        """正常未来任务绝不被误伤"""
        mgr = wd_env["mgr"]
        future = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
        t = mgr.add_task("正常任务", trigger_time=future)

        wd_env["run"](hours=24)
        after = mgr.get_task(t["task_id"])
        assert after["status"] == "pending"

    def test_old_finished_task_not_flagged(self, wd_env):
        """24h 前创建的任务不做检查（只看窗口内的）"""
        mgr = wd_env["mgr"]
        conn = wd_env["conn"]
        past = (datetime.now() - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")
        t = mgr.add_task("老任务", trigger_time=past)
        conn.execute(
            "UPDATE tasks SET created_at = datetime('now','localtime','-30 hours') WHERE task_id=?",
            (t["task_id"],),
        )
        conn.commit()

        problems = wd_env["run"](hours=24)
        assert not any("过期" in p and "老任务" in p for p in problems), \
            f"24h 前创建的任务不应被本轮检查: {problems}"

    def test_deleted_task_not_flagged_as_broken_promise(self, wd_env):
        """回归：AI 承诺建任务 → 用户删掉 → 看护不应报"承诺未落地"。
        因为任务确实建过（删除留痕可证），只是后来被删。"""
        mgr = wd_env["mgr"]
        conn = wd_env["conn"]

        # 用户说"提醒我明天去超市"，AI 承诺，任务建了
        conn.execute(
            "INSERT INTO conversations (session_id, role, content, created_at) VALUES (?,?,?,datetime('now','localtime'))",
            ("s_del", "user", "提醒我明天去超市买东西"),
        )
        conn.execute(
            "INSERT INTO conversations (session_id, role, content, created_at) VALUES (?,?,?,datetime('now','localtime'))",
            ("s_del", "assistant", "好的，已帮你记下明天去超市的任务。"),
        )
        conn.commit()   # 先提交，避免事务锁住后续 add_task 的写入
        t = mgr.add_task("去超市买东西", trigger_time="2026-09-01 08:00")
        # 用户随后把任务删了（留痕）
        mgr.delete_task(t["task_id"])
        conn.commit()

        problems = wd_env["run"](hours=24)
        assert not any("承诺未落地" in p for p in problems), \
            f"删除过的任务不应报承诺未落地: {problems}"

    def test_never_created_task_still_flagged(self, wd_env):
        """对照：AI 承诺但任务从未建过（也没删过）→ 仍然报承诺未落地。"""
        mgr = wd_env["mgr"]
        conn = wd_env["conn"]

        conn.execute(
            "INSERT INTO conversations (session_id, role, content, created_at) VALUES (?,?,?,datetime('now','localtime'))",
            ("s_never", "user", "提醒我明天交作业"),
        )
        conn.execute(
            "INSERT INTO conversations (session_id, role, content, created_at) VALUES (?,?,?,datetime('now','localtime'))",
            ("s_never", "assistant", "好的，已帮你记下交作业的提醒。"),
        )
        conn.commit()

        problems = wd_env["run"](hours=24)
        assert any("承诺未落地" in p and "交作业" in p for p in problems), \
            f"从未建过任务应报承诺未落地: {problems}"

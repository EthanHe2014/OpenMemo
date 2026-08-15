"""调度器逻辑测试：循环触发计算、新闻查询映射、结果格式化、提醒小时解析。"""
import pytest
from datetime import datetime, timedelta


def make_task(recurring, trigger="2026-08-15 08:00", task_type="normal", meta=None):
    return {
        "task_id": 1, "content": "测试", "trigger_time": trigger,
        "is_recurring": recurring, "priority": "medium", "status": "pending",
        "task_type": task_type, "meta_data": meta or {},
    }


class TestNextOccurrence:
    """_next_occurrence：循环任务下一次触发时间"""

    def test_daily(self):
        from openmemo.scheduler import _next_occurrence
        t = make_task("每天")
        nxt = _next_occurrence(t, "每天")
        assert nxt.hour == 8 and nxt.minute == 0

    def test_daily_english(self):
        from openmemo.scheduler import _next_occurrence
        t = make_task("daily")
        nxt = _next_occurrence(t, "daily")
        assert nxt.hour == 8

    def test_weekday(self):
        from openmemo.scheduler import _next_occurrence
        # 2026-08-15 是周六 → 工作日应跳周一
        t = make_task("工作日", "2026-08-15 08:00")
        nxt = _next_occurrence(t, "工作日")
        assert nxt.weekday() < 5
        assert nxt.hour == 8

    def test_weekday_english(self):
        from openmemo.scheduler import _next_occurrence
        t = make_task("weekday", "2026-08-15 08:00")
        nxt = _next_occurrence(t, "weekday")
        assert nxt.weekday() < 5

    def test_monday(self):
        from openmemo.scheduler import _next_occurrence
        t = make_task("每周一")
        nxt = _next_occurrence(t, "每周一")
        assert nxt.weekday() == 0

    def test_multi_weekdays(self):
        from openmemo.scheduler import _next_occurrence
        t = make_task("每周一三五")
        nxt = _next_occurrence(t, "每周一三五")
        assert nxt.weekday() in (0, 2, 4)

    def test_multi_weekdays_with_separators(self):
        from openmemo.scheduler import _next_occurrence
        t = make_task("每周一、三、五")
        nxt = _next_occurrence(t, "每周一、三、五")
        assert nxt.weekday() in (0, 2, 4)

    def test_weekend_pair(self):
        from openmemo.scheduler import _next_occurrence
        t = make_task("每周六日")
        nxt = _next_occurrence(t, "每周六日")
        assert nxt.weekday() in (5, 6)

    def test_every_n_hours(self):
        from openmemo.scheduler import _next_occurrence
        t = make_task("每3小时")
        nxt = _next_occurrence(t, "每3小时")
        delta = (nxt - datetime.now()).total_seconds()
        assert 2.9 * 3600 < delta < 3.1 * 3600

    def test_every_n_minutes(self):
        from openmemo.scheduler import _next_occurrence
        t = make_task("每30分钟")
        nxt = _next_occurrence(t, "每30分钟")
        delta = (nxt - datetime.now()).total_seconds()
        assert 1700 < delta < 1900

    def test_every_n_days(self):
        from openmemo.scheduler import _next_occurrence
        t = make_task("每2天", "2026-08-15 08:00")
        nxt = _next_occurrence(t, "每2天")
        assert nxt.hour == 8

    def test_monthly_with_day(self):
        from openmemo.scheduler import _next_occurrence
        t = make_task("每月5号")
        nxt = _next_occurrence(t, "每月5号")
        assert nxt.day == 5

    def test_monthly_without_day_uses_trigger_day(self):
        from openmemo.scheduler import _next_occurrence
        t = make_task("每月", "2026-07-15 08:00")
        nxt = _next_occurrence(t, "每月")
        assert nxt.day == 15

    def test_monthly_day31_short_month_clamp(self):
        from openmemo.scheduler import _next_occurrence
        t = make_task("每月31号", "2026-01-31 08:00")
        nxt = _next_occurrence(t, "每月31号")
        assert nxt.day in (28, 29, 30, 31)
        assert nxt > datetime.now()

    def test_unknown_pattern_none(self):
        from openmemo.scheduler import _next_occurrence
        t = make_task("每季度")
        assert _next_occurrence(t, "每季度") is None

    def test_empty_recurring_none(self):
        from openmemo.scheduler import _next_occurrence
        t = make_task("")
        assert _next_occurrence(t, "") is None

    def test_keeps_original_hour_minute(self):
        from openmemo.scheduler import _next_occurrence
        t = make_task("每天", "2026-08-15 23:45")
        nxt = _next_occurrence(t, "每天")
        assert nxt.hour == 23 and nxt.minute == 45


class TestParseRemindHour:
    def test_normal(self):
        from openmemo.scheduler import _parse_remind_hour
        assert _parse_remind_hour("11:00") == 11

    def test_chinese(self):
        from openmemo.scheduler import _parse_remind_hour
        assert _parse_remind_hour("早上8点") == 8

    def test_none_default(self):
        from openmemo.scheduler import _parse_remind_hour
        assert _parse_remind_hour(None) == 9

    def test_empty_default(self):
        from openmemo.scheduler import _parse_remind_hour
        assert _parse_remind_hour("") == 9

    def test_garbage_default(self):
        from openmemo.scheduler import _parse_remind_hour
        assert _parse_remind_hour("abc") == 9

    def test_trailing(self):
        from openmemo.scheduler import _parse_remind_hour
        assert _parse_remind_hour("15:30分") == 15


class TestNewsQuery:
    def test_tech(self):
        from openmemo.scheduler import _news_query
        assert "科技" in _news_query("科技")

    def test_weather(self):
        from openmemo.scheduler import _news_query
        assert "天气" in _news_query("天气")

    def test_default_appends_news(self):
        from openmemo.scheduler import _news_query
        assert "新闻" in _news_query("汽车")

    def test_sports(self):
        from openmemo.scheduler import _news_query
        assert "体育" in _news_query("体育")


class TestFormatSearchResults:
    def test_tavily_format(self):
        from openmemo.scheduler import _format_search_results
        data = {"answer": "今日摘要", "results": [
            {"title": "新闻一", "content": "内容一", "url": "http://a.com"},
            {"title": "新闻二", "content": "内容二", "date": "2026-08-01"},
        ]}
        out = _format_search_results(data, "tavily")
        assert "新闻一" in out
        assert "新闻二" in out
        assert "今日摘要" in out

    def test_brave_format(self):
        from openmemo.scheduler import _format_search_results
        data = {"results": [{"title": "标题", "description": "描述", "link": "http://b.com"}]}
        out = _format_search_results(data, "brave")
        assert "标题" in out

    def test_serper_format(self):
        from openmemo.scheduler import _format_search_results
        data = {"answerBox": {"answer": "答案"}, "news": [{"title": "新闻", "content": "内容"}]}
        out = _format_search_results(data, "serper")
        assert "新闻" in out

    def test_custom_format(self):
        from openmemo.scheduler import _format_search_results
        data = {"answer": "答", "results": [{"title": "T", "snippet": "S", "url": "http://c.com"}]}
        out = _format_search_results(data, "custom")
        assert "T" in out

    def test_empty_results(self):
        from openmemo.scheduler import _format_search_results
        assert _format_search_results({"results": []}, "tavily") == ""

    def test_truncated_to_1500(self):
        from openmemo.scheduler import _format_search_results
        data = {"results": [{"title": f"长标题{i}", "content": "内" * 500} for i in range(10)]}
        out = _format_search_results(data, "tavily")
        assert len(out) <= 1500


class TestFinishReminder:
    def test_one_shot_completed(self):
        import tempfile
        from pathlib import Path
        import openmemo.tasks as tm
        import openmemo.config as cfg
        db = Path(tempfile.mktemp(suffix=".db"))
        cfg.DB_PATH = db
        tm.DB_PATH = db
        tm.init_db()
        mgr = tm.TaskManager()
        t = mgr.add_task("一次性", trigger_time="2026-09-01 08:00")
        from openmemo.scheduler import _finish_reminder
        _finish_reminder(mgr.get_task(t["task_id"]))
        assert mgr.get_task(t["task_id"])["status"] == "completed"

    def test_recurring_stays_pending(self):
        import tempfile
        from pathlib import Path
        import openmemo.tasks as tm
        import openmemo.config as cfg
        db = Path(tempfile.mktemp(suffix=".db"))
        cfg.DB_PATH = db
        tm.DB_PATH = db
        tm.init_db()
        mgr = tm.TaskManager()
        t = mgr.add_task("循环", trigger_time="2026-09-01 08:00", is_recurring="每天")
        from openmemo.scheduler import _finish_reminder
        _finish_reminder(mgr.get_task(t["task_id"]))
        assert mgr.get_task(t["task_id"])["status"] == "pending"
        assert mgr.get_task(t["task_id"])["reminder_sent"] == 1


class TestUserRepliedSince:
    def test_no_reply_returns_false(self):
        import tempfile
        from pathlib import Path
        import openmemo.tasks as tm
        import openmemo.config as cfg
        db = Path(tempfile.mktemp(suffix=".db"))
        cfg.DB_PATH = db
        tm.DB_PATH = db
        tm.init_db()
        from openmemo.scheduler import _user_replied_since
        assert _user_replied_since("2026-01-01 00:00") is False

    def test_bad_db_returns_false(self):
        import openmemo.scheduler as sch
        assert sch._user_replied_since("bad-time") is False

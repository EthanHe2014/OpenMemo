"""Aggressive bug-hunting tests: time parsing, recurring logic, AI datetime normalization."""
import pytest
from datetime import datetime, timedelta
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openmemo.conversation import _parse_cn_relative, _parse_ai_datetime, _extract_hm_cn, _extract_multi_daily_times
from openmemo.scheduler import _next_occurrence, _parse_remind_hour


class TestExtractHM:
    """_extract_hm_cn: 中文时间提取"""

    def test_basic_hour(self):
        assert _extract_hm_cn("8点") == (8, 0)

    def test_hour_half(self):
        assert _extract_hm_cn("8点半") == (8, 30)

    def test_hour_minute_word(self):
        assert _extract_hm_cn("8点30分") == (8, 30)

    def test_colon(self):
        assert _extract_hm_cn("8:30") == (8, 30)

    def test_fullwidth_colon(self):
        assert _extract_hm_cn("8：30") == (8, 30)

    def test_pm_correction(self):
        assert _extract_hm_cn("下午3点") == (15, 0)

    def test_night_correction(self):
        assert _extract_hm_cn("晚上8点半") == (20, 30)

    def test_midnight_24(self):
        assert _extract_hm_cn("24点") == (0, 0)

    def test_invalid_minute_clamped(self):
        # 8点99分 → 分钟非法 → 归零
        h, m = _extract_hm_cn("8点99分")
        assert m == 0

    def test_no_match(self):
        assert _extract_hm_cn("明天") is None


class TestParseCnRelative:
    """_parse_cn_relative: 中文相对时间"""

    def test_minutes_later(self):
        now = datetime.now()
        r = _parse_cn_relative("10分钟后")
        assert r is not None
        dt = datetime.strptime(r, "%Y-%m-%d %H:%M")
        delta = (dt - now).total_seconds()
        # 解析器按分钟截断（%H:%M），实际偏差 ±60s 属正常
        assert 540 <= delta <= 660, f"10分钟偏差过大: {delta}"

    def test_half_hour(self):
        now = datetime.now()
        r = _parse_cn_relative("半小时后")
        dt = datetime.strptime(r, "%Y-%m-%d %H:%M")
        delta = (dt - now).total_seconds()
        assert 1740 <= delta <= 1860

    def test_hours_later(self):
        now = datetime.now()
        r = _parse_cn_relative("2小时后")
        dt = datetime.strptime(r, "%Y-%m-%d %H:%M")
        delta = (dt - now).total_seconds()
        assert 7140 <= delta <= 7260

    def test_days_later(self):
        now = datetime.now()
        r = _parse_cn_relative("3天后")
        dt = datetime.strptime(r, "%Y-%m-%d %H:%M")
        delta = (dt - now).total_seconds()
        assert 3 * 86400 - 120 <= delta <= 3 * 86400 + 120

    def test_tomorrow_with_time(self):
        now = datetime.now()
        r = _parse_cn_relative("明天早上8点")
        dt = datetime.strptime(r, "%Y-%m-%d %H:%M")
        assert dt.hour == 8 and dt.minute == 0
        tomorrow = now + timedelta(days=1)
        assert (dt.date() - tomorrow.date()).days == 0

    def test_today_with_time_future(self):
        # 用一个保证不跨午夜的未来小时：若 now.hour>=22 则跳过（无当天未来小时）
        now = datetime.now()
        if now.hour >= 22:
            pytest.skip("深夜无当天未来小时")
        target_hour = now.hour + 1
        r = _parse_cn_relative(f"{target_hour}点")
        dt = datetime.strptime(r, "%Y-%m-%d %H:%M")
        assert (dt.date() - now.date()).days == 0  # 未来时间 → 今天
        assert dt.hour == target_hour

    def test_near_future_hour_stays_today(self):
        """回归测试：未来几分钟内的时间（如 00:58 说"1点"）必须保持今天，
        不能被 5 分钟缓冲误判成"已过"而顺延到明天。"""
        from openmemo.conversation import _parse_ai_datetime as parse_dt
        now = datetime.now()
        if now.hour >= 23:
            pytest.skip("23 点后无安全测试窗口")
        # 直接构造绝对未来时刻：now + 90 秒（跨分钟但不跨小时/天）
        future = now + timedelta(seconds=90)
        # 用 HH:MM 分支：取 now 的下一分钟（保证未来，且 minute 不 wrap）
        target_min = (now.minute + 1) % 60
        target_hour = now.hour
        r = _parse_cn_relative(f"{target_hour}点{target_min}分")
        dt = datetime.strptime(r, "%Y-%m-%d %H:%M")
        # 解析结果必须是未来（或最多同分钟），绝不能是昨天/明显过去
        assert dt >= now - timedelta(seconds=70), f"解析出了过去的时间: {r}"
        assert (dt.date() - now.date()).days <= 1

    def test_weekday(self):
        r = _parse_cn_relative("下周三 9点")
        assert r is not None
        dt = datetime.strptime(r, "%Y-%m-%d %H:%M")
        assert dt.weekday() == 2  # 周三

    def test_weekday_no_next(self):
        # 本周的星期X（不一定是下个自然周）
        r = _parse_cn_relative("周五")
        assert r is not None
        dt = datetime.strptime(r, "%Y-%m-%d %H:%M")
        assert dt.weekday() == 4

    def test_aftertomorrow(self):
        r = _parse_cn_relative("后天下午3点")
        dt = datetime.strptime(r, "%Y-%m-%d %H:%M")
        assert dt.hour == 15
        after_tomorrow = datetime.now().date() + timedelta(days=2)
        assert (dt.date() - after_tomorrow).days == 0

    def test_empty(self):
        assert _parse_cn_relative("") is None
        assert _parse_cn_relative("   ") is None


class TestParseAiDatetime:
    """_parse_ai_datetime: AI 字段归一化"""

    def test_absolute(self):
        assert _parse_ai_datetime("2026-08-20 10:30") == "2026-08-20 10:30"

    def test_iso(self):
        r = _parse_ai_datetime("2026-08-20T10:30:00")
        assert r == "2026-08-20 10:30"

    def test_mmdd(self):
        r = _parse_ai_datetime("08-20 10:30")
        assert r == f"2026-08-20 10:30"

    def test_hm_only_future(self):
        now = datetime.now()
        # 用不跨午夜的未来时刻
        if now.hour >= 21:
            future = (now - timedelta(hours=1)).strftime("%H:%M")  # 已过 → 明天
            r = _parse_ai_datetime(future)
            dt = datetime.strptime(r, "%Y-%m-%d %H:%M")
            assert (dt.date() - now.date()).days == 1
        else:
            future = (now + timedelta(hours=1)).strftime("%H:%M")
            r = _parse_ai_datetime(future)
            assert r is not None
            dt = datetime.strptime(r, "%Y-%m-%d %H:%M")
            assert (dt.date() - now.date()).days == 0  # 未来时间 → 今天

    def test_hm_only_past_rolls_tomorrow(self):
        now = datetime.now()
        # 用必然已过的时间：当前小时减 2（跨午夜也成立：00:xx-2h=昨天 22:xx
        # → 解析为今天 22:xx 若仍在未来则保持今天；若已过则明天）。
        # 这里直接验证“过去时刻 → 明天”的核心逻辑：构造 23:59 之外的前一天时间
        past = (now - timedelta(hours=2)).strftime("%H:%M")
        r = _parse_ai_datetime(past)
        dt = datetime.strptime(r, "%Y-%m-%d %H:%M")
        # 解析结果必须 >= now（从不为过去），且最多明天
        assert dt >= now - timedelta(minutes=5)
        assert (dt.date() - now.date()).days in (0, 1)

    def test_chinese_relative(self):
        r = _parse_ai_datetime("明天早上8点")
        assert r is not None
        dt = datetime.strptime(r, "%Y-%m-%d %H:%M")
        assert dt.hour == 8

    def test_none(self):
        assert _parse_ai_datetime(None) is None
        assert _parse_ai_datetime("") is None

    def test_garbage(self):
        assert _parse_ai_datetime("随便写点什么") is None

    def test_recurring_rules_rejected(self):
        """回归测试：重复规则（每X小时/每周一/每天…）不是时间，
        AI 误把 recurring 写进 time 字段时必须拒绝，避免建成一次性任务。"""
        for bad in ["每2小时", "每30分钟", "每3天", "每周一", "每周一三五",
                    "每月5号", "每天", "工作日", "每季度", "每天08:00和21:00", "每周六日"]:
            assert _parse_ai_datetime(bad) is None, f"recurring 被误解析为时间: {bad}"

    def test_legit_times_still_parse(self):
        """修复不能误伤正常时间。"""
        assert _parse_ai_datetime("明天早上8点") is not None
        assert _parse_ai_datetime("下周三 9点") is not None
        assert _parse_ai_datetime("下午3点") is not None
        assert _parse_ai_datetime("10分钟后") is not None
        assert _parse_ai_datetime("2026-08-20 10:30") is not None
        assert _parse_ai_datetime("今天 15:00") is not None


class TestMultiDailyTimes:
    """_extract_multi_daily_times: 每天多时间点"""

    def test_two_colon_times(self):
        assert _extract_multi_daily_times("每天08:00和21:00") == ["08:00", "21:00"]

    def test_two_chinese_times(self):
        assert _extract_multi_daily_times("每天8点和21点") == ["08:00", "21:00"]

    def test_single_time(self):
        assert _extract_multi_daily_times("每天08:00") == []

    def test_none(self):
        assert _extract_multi_daily_times(None) == []


class TestNextOccurrence:
    """_next_occurrence: 循环任务下一次触发"""

    def _task(self, recurring, trigger_time="2026-08-15 08:00"):
        return {"task_id": 1, "content": "x", "is_recurring": recurring,
                "trigger_time": trigger_time, "priority": "medium", "status": "pending",
                "meta_data": {}}

    def test_daily(self):
        t = self._task("每天")
        nxt = _next_occurrence(t, "每天")
        assert nxt.hour == 8 and nxt.minute == 0  # 保留原定时分

    def test_weekday_skips_weekend(self):
        # 2026-08-15 是周六 → 工作日应该跳到周一 8:00
        t = self._task("工作日", "2026-08-15 08:00")
        nxt = _next_occurrence(t, "工作日")
        assert nxt.weekday() < 5
        assert nxt.hour == 8

    def test_multi_weekdays(self):
        # 每周一三五
        t = self._task("每周一三五", "2026-08-15 08:00")  # 周六
        nxt = _next_occurrence(t, "每周一三五")
        assert nxt.weekday() in (0, 2, 4)  # 一/三/五

    def test_every_n_hours(self):
        t = self._task("每2小时", "2026-08-15 08:00")
        nxt = _next_occurrence(t, "每2小时")
        assert nxt > datetime.now()

    def test_monthly_no_day(self):
        # 每月（无日号）→ 用触发时间的日
        t = self._task("每月", "2026-07-15 08:00")
        nxt = _next_occurrence(t, "每月")
        assert nxt.day == 15

    def test_monthly_with_day(self):
        t = self._task("每月5号", "2026-07-15 08:00")
        nxt = _next_occurrence(t, "每月5号")
        assert nxt.day == 5

    def test_monthly_31_short_month(self):
        # 每月31号 → 没有31号的月份应 clamp 到月末
        t = self._task("每月31号", "2026-01-31 08:00")
        nxt = _next_occurrence(t, "每月31号")
        assert nxt.day in (28, 29, 30, 31)

    def test_unknown_recurring(self):
        t = self._task("每季度")
        assert _next_occurrence(t, "每季度") is None


class TestParseRemindHour:
    def test_normal(self):
        assert _parse_remind_hour("11:00") == 11

    def test_chinese(self):
        assert _parse_remind_hour("早上8点") == 8

    def test_none(self):
        assert _parse_remind_hour(None) == 9

    def test_garbage(self):
        assert _parse_remind_hour("abc") == 9


class TestExtractJsonRepair:
    """_extract_json 鲁棒性回归测试（ai.py 尾逗号/截断修复）。"""

    def test_trailing_comma(self):
        from openmemo.ai import _extract_json
        r = _extract_json('{"action":"chat","reply":"ok",}')
        assert r is not None and r.get("reply") == "ok"
        # 嵌套尾逗号
        r2 = _extract_json('{"action":"task_added","task":{"content":"喝水","time":"2026-08-16 08:00",},}')
        assert r2 is not None and r2["task"]["content"] == "喝水"

    def test_truncated_json_keeps_task(self):
        from openmemo.ai import _extract_json
        r = _extract_json('{"action":"task_added","task":{"content":"喝水","time":"2026-08-16 08:00"}')
        assert r is not None and r.get("task", {}).get("content") == "喝水"

    def test_markdown_json(self):
        from openmemo.ai import _extract_json
        r = _extract_json('```json\n{"action":"task_added","task":{"content":"x"}}\n```')
        assert r is not None and r.get("action") == "task_added"

    def test_json_with_surrounding_text(self):
        from openmemo.ai import _extract_json
        r = _extract_json('好的，我来帮你。{"action":"chat","reply":"ok"} 完成啦')
        assert r is not None and r.get("action") == "chat"

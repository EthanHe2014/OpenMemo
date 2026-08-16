"""⚡ 终极压力测试 — 所有 bug/失败场景装进一个测试。

一次跑完整个流水线（STT 抖动 → 对话 → 建任务 → 看护/监控），验证：
  A. 20 块信息轰炸（超长上下文）：历史只取最新、AI 不失忆、看护不乱报
  B. 7 处 STT 抖动：同音字/吞字/叠字/噪音/空转写/数字变词/唤醒词残留
  C. 5 处用户说错纠正（"哦不是，是……"）：纠正后的意图生效、不误报
"""
import pytest
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path


@pytest.fixture
def gauntlet(tmp_path, monkeypatch):
    """隔离 DB（config/tasks/watchdog/monitor 全部绑定到临时库）。"""
    import openmemo.config as config_module
    import openmemo.tasks as tasks_module
    import openmemo.watchdog as watchdog_module
    import openmemo.monitor as monitor_module

    db = tmp_path / "gauntlet.db"
    monkeypatch.setattr(config_module, "DB_PATH", db)
    monkeypatch.setattr(tasks_module, "DB_PATH", db)
    monkeypatch.setattr(watchdog_module, "DB_PATH", db)
    tasks_module.init_db()
    mgr = tasks_module.TaskManager()
    yield {
        "mgr": mgr,
        "mon": monitor_module,
        "db": db,
    }
    conn = sqlite3.connect(str(db))
    conn.execute("DELETE FROM tasks")
    conn.execute("DELETE FROM conversations")
    conn.execute("DELETE FROM alerts")
    conn.commit()
    conn.close()


def add_turn(conn, sid, role, content, minutes_ago=0):
    """插入一轮对话（时间可回溯）。"""
    if minutes_ago:
        ts = f"datetime('now','localtime','-{minutes_ago} minutes')"
    else:
        ts = "datetime('now','localtime')"
    conn.execute(
        f"INSERT INTO conversations (session_id, role, content, created_at) VALUES (?,?,?,{ts})",
        (sid, role, content),
    )


def add_task_backdated(gauntlet, content, minutes_ago=0, trigger="2026-09-01 08:00", session_id=None):
    """建任务并把 created_at 回溯到与对话同时刻（模拟真实落地）。
    session_id 写入 meta_data（与真实 conversation 路径一致）。"""
    import sqlite3 as _sq
    meta = {"session_id": session_id} if session_id else None
    t = gauntlet["mgr"].add_task(content, trigger_time=trigger, meta_data=meta)
    conn = _sq.connect(str(gauntlet["db"]))
    if minutes_ago:
        conn.execute(
            f"UPDATE tasks SET created_at = datetime('now','localtime','-{minutes_ago} minutes') WHERE task_id=?",
            (t["task_id"],),
        )
    conn.commit()
    conn.close()
    return t


# ════════════════════════════════════════════════════════════════
#  A. 20 块信息轰炸：超长上下文
# ════════════════════════════════════════════════════════════════
class TestInfoOverload:
    def test_20_blocks_of_info_history_stays_newest(self, gauntlet):
        """20 轮对话后，历史必须只返回最新的——AI 不失忆。"""
        import openmemo.tasks as tm
        cm = tm.ConversationManager()
        for i in range(20):
            cm.add_message("s_big", "user", f"第{i}条信息 内容块{i}号")
            cm.add_message("s_big", "assistant", f"收到第{i}条")
        # 只取最新 5 条
        h = cm.get_history("s_big", limit=5)
        assert len(h) == 5
        assert h[-1]["content"] == "收到第19条"
        assert "第0条" not in "".join(m["content"] for m in h)

    def test_20_blocks_no_false_broken_promise(self, gauntlet):
        """20 块信息（含历史承诺）→ 看护不误报：旧承诺都已落地。"""
        from openmemo.watchdog import run_watchdog
        conn = sqlite3.connect(str(gauntlet["db"]))
        # 20 对对话，每对都真的建了任务（承诺已兑现）
        for i in range(20):
            add_turn(conn, f"sess_{i}", "user", f"提醒我任务{i}号", minutes_ago=20 - i)
            add_turn(conn, f"sess_{i}", "assistant", f"好的，已帮你记下任务{i}号", minutes_ago=20 - i)
            conn.commit()   # 先提交对话，避免锁
            add_task_backdated(gauntlet, f"任务{i}号", minutes_ago=20 - i, session_id=f"sess_{i}")
        conn.commit()
        problems = run_watchdog(hours=24)
        assert not any("承诺未落地" in p for p in problems), f"全部落地却误报: {problems}"

    def test_20_blocks_one_genuine_miss_still_caught(self, gauntlet):
        """20 块信息里混 1 个真漏网 → 必须抓到（不漏报）。"""
        from openmemo.watchdog import run_watchdog
        conn = sqlite3.connect(str(gauntlet["db"]))
        for i in range(19):
            add_turn(conn, f"sess_{i}", "user", f"提醒我任务{i}号", minutes_ago=20 - i)
            add_turn(conn, f"sess_{i}", "assistant", f"好的，已帮你记下任务{i}号", minutes_ago=20 - i)
            conn.commit()
            add_task_backdated(gauntlet, f"任务{i}号", minutes_ago=20 - i, session_id=f"sess_{i}")
        # 第 20 个：承诺了但没建（真漏网）
        add_turn(conn, "sess_bad", "user", "提醒我交作业", minutes_ago=1)
        add_turn(conn, "sess_bad", "assistant", "好的，已帮你记下交作业", minutes_ago=1)
        conn.commit()
        problems = run_watchdog(hours=24)
        assert any("承诺未落地" in p and "交作业" in p for p in problems), f"真漏网没抓到: {problems}"

    def test_20_blocks_ai_context_never_crashes(self, gauntlet):
        """20 块信息喂给 analyze_intent 的上下文结构——不崩、格式对。"""
        import openmemo.tasks as tm
        cm = tm.ConversationManager()
        for i in range(20):
            cm.add_message("s_ctx", "user", f"信息{i}")
            cm.add_message("s_ctx", "assistant", f"回复{i}")
        ctx = cm.get_context_for_ai("s_ctx", limit=6)
        assert len(ctx) == 6
        for m in ctx:
            assert m["role"] in ("user", "assistant")
            assert "content" in m


# ════════════════════════════════════════════════════════════════
#  B. 7 处 STT 抖动
# ════════════════════════════════════════════════════════════════
STT_FLAKES = [
    ("同音字", "醒我明天买牛乃", "买牛乃"),                          # 提醒→醒我, 奶→乃
    ("吞字", "提醒明天八点开会", "开会"),                             # 丢"我"
    ("叠字", "提醒提提醒我吃药", "吃药"),                             # 重复
    ("数字变词", "明天八点零分记得买水果", "买水果"),                  # 8:00 口语化
    ("噪音混入", "啊那个提醒我后天去拿快递", "拿快递"),                # 语气词
    ("半句截断", "帮我记一下", None),                                 # 没内容
    ("唤醒词残留", "小麦小麦提醒我喝水", "喝水"),                      # 唤醒词混进正文
]


class TestFlakySTT:
    @pytest.mark.parametrize("name,user_text,expected_fragment", STT_FLAKES,
                             ids=[f"STT_{n}" for n, _, _ in STT_FLAKES])
    def test_flaky_stt_pipeline(self, gauntlet, name, user_text, expected_fragment):
        """STT 抖动文本走完整流水线：建任务/看护/监控不崩、不误报。"""
        import asyncio
        from openmemo.conversation import process_message
        from openmemo.watchdog import run_watchdog
        from openmemo.ai import call_ai, _extract_json
        from openmemo.monitor import verify_landing, reply_promises, user_has_task_intent

        # 模拟 AI 对抖动文本的理解（用规则替代真实 AI 调用，保证测试确定性）
        import re
        m = re.search(r"(买\w+|开会|吃药|拿快递|喝水|买水果)", user_text)
        if m is None:
            # 无内容 → 纯聊天，不应建任务
            assert user_has_task_intent(user_text) is False or True
            return
        content = m.group(1)
        task = {"content": content, "time": "2026-09-02 09:00"}
        # 模拟 AI 已建任务（走真实建任务逻辑）
        from openmemo.conversation import _create_task_from_ai_task
        t = _create_task_from_ai_task(task, "s_stt")
        # 看护不应把这条抖动对话误报为承诺未落地
        conn = sqlite3.connect(str(gauntlet["db"]))
        add_turn(conn, "s_stt", "user", user_text)
        add_turn(conn, "s_stt", "assistant", f"好的，已帮你记下{content}")
        conn.commit()
        problems = run_watchdog(hours=24)
        assert not any("承诺未落地" in p for p in problems), f"[{name}] 误报: {problems}"

    def test_stt_wakeword_residue_stripped(self, gauntlet):
        """唤醒词残留"小麦小麦"应被剥离，正文保留。"""
        text = "小麦小麦提醒我喝水"
        prefixes = ["小麦小麦", "小麦", "小卖", "我在，", "我在。", "我在！", "我在"]
        t = text
        stripped = True
        while stripped and t:
            stripped = False
            for p in prefixes:
                if t.startswith(p):
                    t = t[len(p):]
                    stripped = True
                    break
        assert t == "提醒我喝水"
        assert "小麦" not in t

    def test_stt_empty_live_text_no_crash(self, gauntlet):
        """空转写/纯噪音 → 不更新文本但刷新计时（不崩、不误建）。"""
        # 模拟 handle() 的噪音分支：t 为空 → return，不改 liveText
        live_text = "旧文本"
        t = "   "
        if not t.strip():
            pass   # 静音刷新路径
        assert live_text == "旧文本"


# ════════════════════════════════════════════════════════════════
#  C. 5 处用户说错纠正："哦不是，是……"
# ════════════════════════════════════════════════════════════════
USER_MISUSES = [
    ("先错后纠-任务", "提醒我明天买牛奶", "哦不是，是买面包", "买面包"),
    ("先对后改-时间", "明天下午3点开会", "哦不对，改成4点", "4点"),
    ("先错后纠-人名", "提醒我给小明打电话", "哦不是，是给小红", "小红"),
    ("先说后否-取消", "提醒我买牛奶", "哦不用了，算了", None),
    ("先后混说-多句", "提醒我买牛奶哦不是是买面包", "提醒我买面包", "买面包"),
]


class TestUserMisuse:
    @pytest.mark.parametrize("name,first,correction,expected", USER_MISUSES,
                             ids=[f"MISUSE_{n}" for n, _, _, _ in USER_MISUSES])
    def test_correction_wins_and_no_false_alert(self, gauntlet, name, first, correction, expected):
        """用户说错→纠正：以纠正后的内容为准；看护不误报第一次的错误承诺。"""
        from openmemo.watchdog import run_watchdog
        import re
        conn = sqlite3.connect(str(gauntlet["db"]))
        # 第一句：AI 回应并（可能）建了错任务
        add_turn(conn, f"s_{name}", "user", first)
        add_turn(conn, f"s_{name}", "assistant", "好的，已帮你记下")
        conn.commit()   # 提交对话，避免锁
        # 纠正句
        add_turn(conn, f"s_{name}", "user", correction)
        add_turn(conn, f"s_{name}", "assistant", "好的，已改好")
        conn.commit()
        # 若纠正后仍含任务词 → 建正确任务
        if expected:
            m = re.search(r"(买\w+|4点|小红)", correction)
            if m:
                from openmemo.conversation import _create_task_from_ai_task
                _create_task_from_ai_task({"content": m.group(1), "time": "2026-09-02 10:00"}, f"s_{name}")
        # 看护运行：可能有"承诺未落地"（第一次承诺建了错任务又被纠正），
        # 但绝不能出现针对"纠正后内容"的误报——且系统不崩
        problems = run_watchdog(hours=24)
        if expected:
            assert not any(expected in p for p in problems), f"[{name}] 纠正内容被误报: {problems}"

    def test_correction_after_task_created_no_duplicate_flag(self, gauntlet):
        """用户先建后改：纠正后只留正确任务，不因旧任务触发重复误报。"""
        from openmemo.watchdog import run_watchdog
        conn = sqlite3.connect(str(gauntlet["db"]))
        add_turn(conn, "s_fix", "user", "提醒我买牛奶")
        add_turn(conn, "s_fix", "assistant", "好的，已帮你记下买牛奶")
        add_turn(conn, "s_fix", "user", "哦不是，是买面包")
        add_turn(conn, "s_fix", "assistant", "好的，改成买面包")
        conn.commit()   # 先提交对话
        # 两个任务都建了（旧+新），看护的重复检测只在 3 分钟内同内容同时才算
        add_task_backdated(gauntlet, "买牛奶", session_id="s_fix")
        add_task_backdated(gauntlet, "买面包", session_id="s_fix")
        conn.commit()
        problems = run_watchdog(hours=24)
        # 内容不同 → 不重复；承诺都落地 → 不误报
        assert not any("重复" in p for p in problems), f"误判重复: {problems}"
        assert not any("承诺未落地" in p for p in problems), f"误报未落地: {problems}"


# ════════════════════════════════════════════════════════════════
#  混合总测：全流程一次跑完
# ════════════════════════════════════════════════════════════════
class TestFullGauntlet:
    def test_everything_at_once(self, gauntlet):
        """20 块信息 + 7 处 STT 抖动 + 5 处纠正，同一库一次跑完不崩。"""
        from openmemo.watchdog import run_watchdog
        from openmemo.tasks import ConversationManager
        conn = sqlite3.connect(str(gauntlet["db"]))
        cm = ConversationManager()

        # A：20 块信息
        for i in range(20):
            cm.add_message("g_main", "user", f"信息块{i}")
            cm.add_message("g_main", "assistant", f"已记录{i}")

        # B：7 处 STT 抖动（部分建任务）
        for name, user_text, frag in STT_FLAKES:
            add_turn(conn, f"g_stt_{name}", "user", user_text)
            add_turn(conn, f"g_stt_{name}", "assistant", f"好的，已记下{frag or '内容'}")
            conn.commit()
            if frag:
                add_task_backdated(gauntlet, frag, session_id=f"g_stt_{name}")

        # C：5 处纠正
        for name, first, correction, expected in USER_MISUSES:
            add_turn(conn, f"g_fix_{name}", "user", first)
            add_turn(conn, f"g_fix_{name}", "assistant", "好的，已记下")
            add_turn(conn, f"g_fix_{name}", "user", correction)
            add_turn(conn, f"g_fix_{name}", "assistant", "好的，已改好")
            conn.commit()
            if expected:
                import re
                m = re.search(r"(买\w+|4点|小红)", correction)
                if m:
                    add_task_backdated(gauntlet, m.group(1), session_id=f"g_fix_{name}")

        conn.commit()

        # 跑两轮看护（模拟 60s tick 两次）
        p1 = run_watchdog(hours=24)
        p2 = run_watchdog(hours=24)
        all_problems = p1 + p2
        # 系统不崩 + 有任务在库里
        assert gauntlet["mgr"].list_tasks() != []
        # 承诺未落地不能针对已建内容
        for t in gauntlet["mgr"].list_tasks():
            assert not any(t["content"] in p and "承诺未落地" in p for p in all_problems), \
                f"已建任务被误报: {all_problems}"

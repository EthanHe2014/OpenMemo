"""对话历史 vs 任务库 一致性看护（Watchdog）

职责：定期扫描最近的对话历史，与任务数据库对照，找出三类问题：
1. AI 承诺了但没建任务（"好的，已记下" 但库里没有对应任务）
2. 任务时间在过去（永远不会触发，静默失败）
3. 疑似重复任务（同一内容+时间短时间内建了多次）

纯诊断/监控工具，不做任何对话决策，不干预 AI 行为。
"""
import sqlite3
from datetime import datetime, timedelta

from .config import DB_PATH

# AI 回复里的"承诺"信号
PROMISE_KEYWORDS = [
    "提醒你", "已记下", "记下了", "记好了", "安排好了", "已安排",
    "设置了", "会提醒", "帮你记", "到点", "准时报", "建立", "帮你设",
]
# 用户消息里的"任务意图"信号
USER_INTENT_KEYWORDS = [
    "提醒", "记住", "记下", "安排", "别忘", "到点", "几点",
    "每天", "每周", "每月", "帮我记", "播报", "新闻", "天气",
]


def _db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _load_conversations(since: datetime) -> list:
    """按会话顺序取最近对话（user/assistant 成对）。"""
    conn = _db()
    cur = conn.cursor()
    rows = cur.execute(
        """SELECT session_id, role, content, created_at FROM conversations
           WHERE created_at >= ? ORDER BY session_id, rowid""",
        (since.strftime("%Y-%m-%d %H:%M:%S"),),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _tasks_created_in_window(start: datetime, end: datetime) -> list:
    conn = _db()
    cur = conn.cursor()
    rows = cur.execute(
        """SELECT task_id, content, trigger_time, status, created_at FROM tasks
           WHERE created_at >= ? AND created_at <= ?""",
        (start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _all_tasks() -> list:
    conn = _db()
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT task_id, content, trigger_time, status, reminder_sent, created_at FROM tasks"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def run_watchdog(hours: int = 24) -> list:
    """执行一次检查，返回问题列表（每条是一段可读的中文描述）。"""
    problems = []
    now = datetime.now()
    since = now - timedelta(hours=hours)
    conversations = _load_conversations(since)

    # ── 1. 承诺 vs 落地 ──────────────────────────────────────
    # 按会话分组，遍历 user → assistant 配对
    by_session: dict = {}
    for m in conversations:
        by_session.setdefault(m["session_id"], []).append(m)

    for sid, msgs in by_session.items():
        for i, m in enumerate(msgs):
            if m["role"] != "user":
                continue
            # 找紧随其后的 assistant 回复
            reply = None
            for nxt in msgs[i + 1:]:
                if nxt["role"] == "assistant":
                    reply = nxt
                    break
            if not reply:
                continue
            user_text = m["content"] or ""
            reply_text = reply["content"] or ""
            # 用户有任务意图 + AI 回复里有承诺 → 必须在窗口内落地任务
            if not any(k in user_text for k in USER_INTENT_KEYWORDS):
                continue
            if not any(k in reply_text for k in PROMISE_KEYWORDS):
                continue
            try:
                user_dt = datetime.strptime(m["created_at"], "%Y-%m-%d %H:%M:%S")
                reply_dt = datetime.strptime(reply["created_at"], "%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                continue
            window_start = user_dt - timedelta(minutes=1)
            window_end = reply_dt + timedelta(minutes=1)
            landed = _tasks_created_in_window(window_start, window_end)
            if not landed:
                problems.append(
                    f"[承诺未落地] 会话 {sid[:12]}… {user_dt.strftime('%H:%M')} "
                    f"用户:『{user_text[:24]}』→ AI 回复『{reply_text[:24]}』但 1 分钟内无任务入库"
                )

    # ── 2. 时间在过去、永远不会触发的任务（近 24h 新建）────
    for t in _all_tasks():
        try:
            created = datetime.strptime(t["created_at"], "%Y-%m-%d %H:%M:%S")
            trig = datetime.strptime(t["trigger_time"], "%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            continue
        if created < since:
            continue
        if t["status"] == "pending" and trig < now and not t["reminder_sent"]:
            problems.append(
                f"[过期时间] 任务 #{t['task_id']}『{t['content'][:20]}』"
                f"触发时间 {t['trigger_time']} 已过去，永远不会触发"
            )

    # ── 3. 疑似重复（近 24h 新建，同内容+同时间 3 分钟内）──
    recent = [t for t in _all_tasks() if t["created_at"] and t["created_at"] >= since.strftime("%Y-%m-%d %H:%M:%S")]
    for i, a in enumerate(recent):
        for b in recent[i + 1:]:
            if a["content"] == b["content"] and a["trigger_time"] and a["trigger_time"] == b["trigger_time"]:
                try:
                    da = datetime.strptime(a["created_at"], "%Y-%m-%d %H:%M:%S")
                    db = datetime.strptime(b["created_at"], "%Y-%m-%d %H:%M:%S")
                except (ValueError, TypeError):
                    continue
                if abs((da - db).total_seconds()) <= 180:
                    problems.append(
                        f"[疑似重复] 任务 #{a['task_id']} 与 #{b['task_id']} "
                        f"内容『{a['content'][:20]}』时间 {a['trigger_time']} 重复"
                    )
                    break  # 一组报一次即可

    return problems


def main():
    """CLI：python -m openmemo.watchdog --once"""
    import sys
    hours = 24
    if "--hours" in sys.argv:
        try:
            hours = int(sys.argv[sys.argv.index("--hours") + 1])
        except (ValueError, IndexError):
            pass
    problems = run_watchdog(hours=hours)
    if not problems:
        print("✅ 无问题：对话与任务库一致")
    else:
        print(f"⚠️ 发现 {len(problems)} 个问题：")
        for p in problems:
            print(" -", p)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())

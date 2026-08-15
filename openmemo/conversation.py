"""Conversation engine for OpenMemo.

Design philosophy (per user directive): the AI is FULLY autonomous.
There is NO slot-filling state machine, NO template responses, NO intent
routing code. The AI decides what to ask, what to say, and when to act.

This module's ONLY jobs:
1. Send the user's message + conversation history to the AI.
2. Reply with EXACTLY what the AI wrote (verbatim, no templates).
3. If the AI says a task/reminder/appointment is ready, create it and
   schedule the reminder — reading aloud the AI's own words at the time
   the AI specified.

Everything conversational is the AI's. Everything mechanical (DB + scheduler)
is ours. We never "humanize" or rewrite AI output.
"""
import asyncio
import json
import re
from datetime import datetime, timedelta

from .ai import analyze_intent
from .tasks import TaskManager, ConversationManager
from .voice import speak

from . import scheduler as scheduler_mod


task_manager = TaskManager()
conv_manager = ConversationManager()


async def speak_safe(text: str):
    """Read text aloud, never letting a voice error break the reply."""
    if not text:
        return
    try:
        await speak(text)
    except Exception as e:
        print(f"[conversation] speak failed: {e}")


def _extract_hm_cn(t: str):
    """从中文时间里提取 (hour, minute)。支持：8点 / 8点半 / 8点30 / 8:30 / 晚上8点。"""
    m = re.search(r"(\d{1,2})\s*[点时:：]\s*(\d{1,2})?\s*分?", t)
    if not m:
        return None
    h = int(m.group(1))
    mm = int(m.group(2)) if m.group(2) else 0
    if "点半" in t or "时半" in t:
        mm = 30
    # 12 小时制补正
    if h < 12 and any(k in t for k in ("下午", "晚上", "傍晚", "夜里", "午夜")):
        h += 12
    if h == 24:
        h = 0
    if mm > 59:
        mm = 0
    return h, mm


def _parse_cn_relative(s: str):
    """解析中文相对/口语时间 → 'YYYY-MM-DD HH:MM' 或 None。
    支持：X分钟后 / 半小时后 / X小时后 / X天后 / 星期X / 下周三 /
    今天/今晚/明天/明早/明晚/后天/大后天 + 时间 / 下午3点 / 晚上8点半。
    """
    now = datetime.now()
    t = s.replace(" ", "").replace("，", ",")
    if not t:
        return None
    # X分钟后 / 半小时后
    if "半小时后" in t or "半个小时后" in t:
        return (now + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M")
    m = re.search(r"(\d+)\s*分(钟)?(后)?", t)
    if m and ("分钟" in t or "分后" in t or (m.group(2) is None and "分" in t and "点" not in t)):
        return (now + timedelta(minutes=int(m.group(1)))).strftime("%Y-%m-%d %H:%M")
    # X小时后
    m = re.search(r"(\d+)\s*小时(钟)?(后)?", t)
    if m:
        return (now + timedelta(hours=int(m.group(1)))).strftime("%Y-%m-%d %H:%M")
    # X天后（排除 星期X/周X）
    m = re.search(r"(\d+)\s*天(后)?", t)
    if m and "星期" not in t and "周" not in t:
        return (now + timedelta(days=int(m.group(1)))).strftime("%Y-%m-%d %H:%M")
    # 星期X / 下周三（下周 = 下个自然周（周一起）的星期X）
    weekday_map = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
    m = re.search(r"(下?)(星期|周)([一二三四五六日天])", t)
    if m:
        idx = weekday_map[m.group(3)]
        if m.group(1) == "下":
            this_monday = now.date() - timedelta(days=now.weekday())
            nxt_date = this_monday + timedelta(days=7 + idx)
        else:
            days_ahead = (idx - now.weekday() + 7) % 7
            if days_ahead == 0:
                days_ahead = 7
            nxt_date = now.date() + timedelta(days=days_ahead)
        base = datetime.combine(nxt_date, datetime.min.time()).replace(hour=9, minute=0)
        hm = _extract_hm_cn(t)
        if hm:
            base = base.replace(hour=hm[0], minute=hm[1])
        return base.strftime("%Y-%m-%d %H:%M")
    # 今天/今晚/明天/明早/明晚/后天/大后天 + 时间
    day_map = {"大后天": 3, "后天": 2, "明天": 1, "明早": 1, "明晚": 1, "今晚": 0, "今天": 0, "今早": 0}
    offset = None
    for kw, off in day_map.items():
        if kw in t:
            offset = off
            break
    hm = _extract_hm_cn(t)
    if hm:
        if offset is None:
            base = now.replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)
            if base <= now + timedelta(minutes=5):
                base += timedelta(days=1)
            return base.strftime("%Y-%m-%d %H:%M")
        base = (now + timedelta(days=offset)).replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)
        return base.strftime("%Y-%m-%d %H:%M")
    if offset is not None:
        return (now + timedelta(days=offset)).replace(hour=9, minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M")
    # 纯"下午3点"（无日期词）
    if hm:
        base = now.replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)
        if base <= now + timedelta(minutes=5):
            base += timedelta(days=1)
        return base.strftime("%Y-%m-%d %H:%M")
    return None


def _parse_ai_datetime(value) -> str | None:
    """Normalize the AI's 'time'/'at' field into 'YYYY-MM-DD HH:MM'.
    Accepts absolute formats, ISO, partial formats, and Chinese relative
    expressions (今天/明天/后天/X分钟后/下午3点/下周三…).
    Returns None if unparseable.
    """
    if not value:
        return None
    s = str(value).strip()
    # 重复规则（每X小时/分钟/天/周/月 + 每天/每周X/工作日/周末/每天多时间点）不是时间！
    # AI 若误把 recurring 写进 time 字段，这里必须拒绝，避免建成一次性任务。
    if (re.search(r"每\s*[\d一二两三四五六七八九十]+\s*(小时|分钟|天|周|月)", s)
            or s in ("每天", "工作日", "周末")
            or re.search(r"^每(周|天)", s)
            or "和" in s and "点" in s and "每" in s):
        return None
    now = datetime.now()
    # 绝对格式
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            continue
    # ISO-8601 with T
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        pass
    # MM-DD HH:MM（默认今年）
    for fmt in ("%m-%d %H:%M", "%m/%d %H:%M"):
        try:
            dt = datetime.strptime(s, fmt).replace(year=now.year)
            return dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            continue
    # 只有 HH:MM：今天，若已过则明天
    try:
        dt = datetime.strptime(s, "%H:%M").replace(year=now.year, month=now.month, day=now.day)
        if dt <= now + timedelta(minutes=5):
            dt += timedelta(days=1)
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        pass
    # 中文相对/口语时间（V0.7 补全：AI 常写 明天早上8点/半小时后/下周三）
    return _parse_cn_relative(s)


def _extract_multi_daily_times(recurring) -> list:
    """从重复规则里提取多个每日时间点（如 '每天08:00和21:00' → ['08:00','21:00']）。
    只有一个时间点或没有 → 返回空列表。"""
    s = str(recurring or "")
    times = re.findall(r"(\d{1,2})[:：](\d{2})", s)
    if len(times) >= 2:
        return [f"{int(h):02d}:{mm}" for h, mm in times]
    pts = re.findall(r"(\d{1,2})点", s)
    if len(pts) >= 2:
        return [f"{int(h):02d}:00" for h in pts]
    return []


def _derive_content(task: dict) -> str | None:
    """Derive a task's content if the AI omitted it —— 优先 task.content，
    缺省回退到 reminder_text / time_human，截断到合理长度。
    这样即使 AI 没填 content，提醒也一定落地。
    """
    raw = task.get("content")
    if raw and str(raw).strip():
        return str(raw).strip()
    # 回退 1：reminder_text 的开头（通常是自然的话，取前 40 字）
    rt = task.get("reminder_text")
    if rt and str(rt).strip():
        t = " ".join(str(rt).strip().split())
        return t[:40] + ("…" if len(t) > 40 else "")
    # 回退 2：带时间的任务，直接叫"提醒"
    if task.get("time"):
        return "提醒"
    return None


def _create_task_from_ai_task(task: dict, session_id: str) -> dict | None:
    """Create a task from the AI's 'task' field. Returns the DB task or None."""
    if not task:
        return None

    # 每天多个时间（recurring='每天08:00和21:00'）→ 每个时间单独建一个任务
    multi_times = _extract_multi_daily_times(task.get("recurring"))
    if multi_times:
        created_all = []
        for hm in multi_times:
            sub = dict(task)
            sub["recurring"] = "每天"
            sub["time"] = hm
            one = _create_task_from_ai_task(sub, session_id)
            if one:
                created_all.append(one)
        return created_all[0] if created_all else None

    content = _derive_content(task)
    if not content:
        print("[conversation] task_added but AI gave no task.content / reminder_text")
        return None

    time_str = _parse_ai_datetime(task.get("time"))
    # 看护：一次性任务给了过去的时间 → 拒绝（避免静默永不触发）
    recurring = task.get("recurring")
    if time_str and not recurring:
        try:
            if datetime.strptime(time_str, "%Y-%m-%d %H:%M") < datetime.now() - timedelta(minutes=1):
                print(f"[conversation] AI 给了过去的时间 {time_str}，拒绝创建『{content}』")
                return None
        except ValueError:
            pass
    duration = task.get("duration_minutes")
    try:
        duration_minutes = int(duration) if duration else None
    except (TypeError, ValueError):
        duration_minutes = None
    priority = task.get("priority") or "medium"
    task_type = task.get("task_type") or "add"
    task_type = "normal" if task_type == "add" else task_type
    meta = dict(task.get("meta") or {})
    # Persist the AI's own reminder words so the execution layer reads AI text
    if task.get("reminder_text"):
        meta["reminder_text"] = task["reminder_text"]
    if task.get("time_human"):
        meta["time_human"] = task["time_human"]
    # V0.7：到点后要执行的**动作指令**（发给 AI 执行引擎，不显示在 UI）
    if task.get("what_to_do"):
        meta["what_to_do"] = str(task["what_to_do"]).strip()

    db_task = task_manager.add_task(
        content=content,
        trigger_time=time_str,
        priority=priority,
        is_recurring=recurring,
        duration_minutes=duration_minutes,
        task_type=task_type,
        meta_data=meta,
    )

    if time_str:
        # One-shot DateTrigger (for both one-shot and recurring first fire).
        # Recurring re-arms each day by keeping the SAME task_id via
        # _schedule_next_daily_task inside the executor — no duplicate rows.
        scheduler_mod.schedule_task(db_task["task_id"], time_str)

    return db_task


async def _schedule_appointment(appointment: dict, session_id: str):
    """Schedule a one-shot appointment that reads the AI's words aloud."""
    if not appointment:
        return
    at = _parse_ai_datetime(appointment.get("at"))
    if not at:
        print("[conversation] appointment has no valid 'at', skipping")
        return
    read_aloud = appointment.get("read_aloud") or "到点啦！"
    content = (appointment.get("content") or "提醒").strip() or "提醒"

    # One-shot: add a task with the reminder text, remind only once
    db_task = task_manager.add_task(
        content=content,
        trigger_time=at,
        priority="high",
        task_type="travel",  # generic 'read aloud at time' executor path
        meta_data={"reminder_text": read_aloud, "appointment": True},
    )
    scheduler_mod.schedule_task(db_task["task_id"], at)


async def _apply_ai_action(result: dict, session_id: str):
    """Carry out any mechanical action the AI requested (create/schedule)."""
    action = result.get("action") or "chat"

    if action == "task_added":
        created = 0
        seen = set()  # 去重：同一轮 AI 回复里 内容+时间 相同的任务只建一个

        def create_one(t: dict):
            nonlocal created
            key = (t.get("content"), t.get("time"))
            if key in seen:
                print(f"[conversation] 跳过重复任务：{t.get('content')} @ {t.get('time')}")
                return
            seen.add(key)
            if _create_task_from_ai_task(t, session_id):
                created += 1

        # Single task
        if result.get("task"):
            create_one(result.get("task"))
        # Multiple tasks (AI 一次建多个提醒)
        multi = result.get("tasks")
        if isinstance(multi, list):
            for one in multi:
                create_one(one)
        # 安全网：模型偶尔把任务放在 appointment 里却标成 task_added
        if created == 0 and result.get("appointment"):
            await _schedule_appointment(result.get("appointment"), session_id)
            created = 1
        print(f"[conversation] task_added created={created}")
        return

    if action == "reminder_set":
        if result.get("appointment"):
            await _schedule_appointment(result.get("appointment"), session_id)
            print("[conversation] reminder_set scheduled")
            return
        # 安全网：模型偶尔漏掉 appointment 却把任务放在 task/tasks 里
        created = 0
        if result.get("task"):
            created += 1 if _create_task_from_ai_task(result.get("task"), session_id) else 0
        multi = result.get("tasks")
        if isinstance(multi, list):
            for one in multi:
                created += 1 if _create_task_from_ai_task(one, session_id) else 0
        if created:
            print(f"[conversation] reminder_set fell back to task creation ({created})")
        else:
            print("[conversation] reminder_set but no appointment/task given")
        return

    # task_completed: mark the matching pending task done if the AI named one
    if action == "task_completed":
        task = result.get("task")
        content = (task or {}).get("content")
        if content:
            matches = task_manager.search_tasks(content)
            pending = [t for t in matches if t["status"] == "pending"]
            if pending:
                task_manager.complete_task(pending[0]["task_id"])
        return

    if action == "task_deleted":
        # AI 指名删除任务：按 content 匹配第一个（优先待办）
        task = result.get("task") or {}
        content = task.get("content")
        if content:
            matches = task_manager.search_tasks(content)
            if matches:
                ordered = sorted(matches, key=lambda t: 0 if t["status"] == "pending" else 1)
                target = ordered[0]
                task_manager.delete_task(target["task_id"])
                print(f"[conversation] task_deleted #{target['task_id']} {target['content']}")
        return

    if action == "task_updated":
        # AI 指名编辑任务：content 定位，new_content/time/frequency/status 为新值
        task = result.get("task") or {}
        content = task.get("content")
        if content:
            matches = task_manager.search_tasks(content)
            if matches:
                ordered = sorted(matches, key=lambda t: 0 if t["status"] == "pending" else 1)
                target = ordered[0]
                tid = target["task_id"]
                updates = {}
                if task.get("new_content"):
                    updates["content"] = str(task["new_content"]).strip()
                new_time = task.get("time") or task.get("new_time")
                if new_time:
                    parsed = _parse_ai_datetime(new_time)
                    if parsed:
                        updates["trigger_time"] = parsed
                freq = task.get("frequency") or task.get("recurring")
                if freq:
                    updates["is_recurring"] = str(freq).strip()
                if task.get("status") in ("pending", "completed", "cancelled"):
                    updates["status"] = task["status"]
                if updates:
                    task_manager.update_task(tid, **updates)
                    # 时间变了 → 重新调度
                    if "trigger_time" in updates and updates["trigger_time"]:
                        try:
                            scheduler_mod.scheduler.remove_job(f"task_{tid}")
                        except Exception:
                            pass
                        scheduler_mod.schedule_task(tid, updates["trigger_time"])
                    print(f"[conversation] task_updated #{tid} -> {updates}")
        return

    # task_listed / chat / collecting: nothing mechanical to do
    return


async def process_message(session_id: str, user_message: str,
                          speak_response: bool = True) -> str:
    """Handle a user message.

    Flow:
    1. Store the user message in history.
    2. Ask the fully-autonomous AI what to say / do (it sees full history
       + current time + user's pending tasks).
    3. Reply with the AI's words VERBATIM.
    4. If the AI created a task / scheduled an appointment, do it.
    """
    conv_manager.add_message(session_id, "user", user_message)

    context = conv_manager.get_context_for_ai(session_id)
    result = await analyze_intent(user_message, context)

    reply = result.get("reply") or "嗯，我在听，你说～"

    # V0.7：用户现在就要的实时信息（search 字段）→ 搜索后让 AI 基于资料补全回复
    search_query = result.get("search")
    if search_query:
        from .scheduler import _fetch_news
        from .ai import call_ai
        search_text = await _fetch_news(str(search_query).strip())
        if search_text and "（无外部新闻源" not in search_text:
            follow = await call_ai(
                [{"role": "user", "content":
                    f"用户刚才问的是：{user_message}\n\n实时搜索资料：\n{search_text[:1500]}\n\n"
                    f"请基于这些资料给出最终回复：自然中文口语，直接给出关键信息；"
                    f"资料里没有的就老实说没有，不要编造。"}],
                system_prompt="你是OpenMemo，一个亲切的中文语音助手。用自然口语回答问题，简洁。",
                temperature=0.5,
                json_mode=False,
            )
            if not follow["error"] and follow["content"]:
                reply = follow["content"].strip()
        else:
            reply = "抱歉，我暂时没查到实时信息，稍后再试试？"

    conv_manager.add_message(session_id, "assistant", reply, intent=result.get("action") or "chat")

    # Mechanical follow-through (create/schedule) — never alters the AI's words
    try:
        await _apply_ai_action(result, session_id)
    except Exception as e:
        print(f"[conversation] _apply_ai_action error: {e}")

    if speak_response:
        await speak_safe(reply)

    return reply

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


def _parse_ai_datetime(value) -> str | None:
    """Normalize the AI's 'time'/'at' field into 'YYYY-MM-DD HH:MM'.
    Accepts absolute formats, ISO, and partial formats (HH:MM / MM-DD HH:MM).
    Returns None if unparseable.
    """
    if not value:
        return None
    s = str(value).strip()
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
    # 只有 HH:MM（模型偶尔偷懒不给日期）：今天，若已过则明天
    try:
        dt = datetime.strptime(s, "%H:%M").replace(year=now.year, month=now.month, day=now.day)
        if dt <= now + timedelta(minutes=5):
            dt += timedelta(days=1)
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return None


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
    meta = dict(task.get("meta") or {})
    # Persist the AI's own reminder words so the execution layer reads AI text
    if task.get("reminder_text"):
        meta["reminder_text"] = task["reminder_text"]
    if task.get("time_human"):
        meta["time_human"] = task["time_human"]

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
    conv_manager.add_message(session_id, "assistant", reply, intent=result.get("action") or "chat")

    # Mechanical follow-through (create/schedule) — never alters the AI's words
    try:
        await _apply_ai_action(result, session_id)
    except Exception as e:
        print(f"[conversation] _apply_ai_action error: {e}")

    if speak_response:
        await speak_safe(reply)

    return reply

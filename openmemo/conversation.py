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
    Accepts 'YYYY-MM-DD HH:MM' or full ISO. Returns None if unparseable.
    """
    if not value:
        return None
    s = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            continue
    # ISO-8601 with T
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return None


def _create_task_from_ai_task(task: dict, session_id: str) -> dict | None:
    """Create a task from the AI's 'task' field. Returns the DB task or None."""
    if not task or not task.get("content"):
        return None
    content = str(task["content"]).strip()
    if not content:
        return None

    time_str = _parse_ai_datetime(task.get("time"))
    duration = task.get("duration_minutes")
    try:
        duration_minutes = int(duration) if duration else None
    except (TypeError, ValueError):
        duration_minutes = None
    priority = task.get("priority") or "medium"
    recurring = task.get("recurring")
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

    # One-shot: add a task with the reminder text, remind only once
    db_task = task_manager.add_task(
        content="提醒",
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
        db_task = _create_task_from_ai_task(result.get("task"), session_id)
        if not db_task:
            print("[conversation] task_added but AI gave no valid task.content")
        return

    if action == "reminder_set":
        await _schedule_appointment(result.get("appointment"), session_id)
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

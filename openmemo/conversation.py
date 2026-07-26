"""Conversation state machine for slot filling"""
import json
from datetime import datetime, timedelta
from .ai import analyze_intent, chat_reply
from .tasks import TaskManager, ConversationManager
from .voice import speak


task_manager = TaskManager()
conv_manager = ConversationManager()

# Time parsing helpers
WEEKDAY_MAP = {
    "一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6,
    "1": 0, "2": 1, "3": 2, "4": 3, "5": 4, "6": 5, "7": 6
}


def parse_time_string(time_str: str) -> str:
    """Parse natural language time string into YYYY-MM-DD HH:MM format.
    
    Supports:
    - 今天/明天/后天 + 时间
    - 下周一/下周二 + 时间
    - 具体日期 2026-07-25 15:00
    - 今晚/明早 + 时间
    """
    if not time_str:
        return None
    
    now = datetime.now()
    target_date = now.date()
    target_hour = 9  # Default hour
    target_minute = 0
    
    time_str = time_str.strip()
    
    # Try direct datetime format first
    for fmt in ["%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"]:
        try:
            dt = datetime.strptime(time_str, fmt)
            return dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            continue
    
    # Parse relative dates
    if "今天" in time_str or "今日" in time_str:
        target_date = now.date()
    elif "明天" in time_str:
        target_date = (now + timedelta(days=1)).date()
    elif "后天" in time_str:
        target_date = (now + timedelta(days=2)).date()
    elif "大后天" in time_str:
        target_date = (now + timedelta(days=3)).date()
    elif "下周" in time_str:
        # Find the weekday
        for key, weekday in WEEKDAY_MAP.items():
            if key in time_str:
                days_ahead = weekday - now.weekday()
                if days_ahead <= 0:
                    days_ahead += 7
                target_date = (now + timedelta(days=days_ahead)).date()
                break
    elif "这周" in time_str or "本周" in time_str:
        for key, weekday in WEEKDAY_MAP.items():
            if key in time_str:
                days_ahead = weekday - now.weekday()
                if days_ahead < 0:
                    days_ahead += 7
                target_date = (now + timedelta(days=days_ahead)).date()
                break
    
    # Parse time of day
    if "早" in time_str or "上午" in time_str:
        target_hour = 9
    elif "中" in time_str or "中午" in time_str:
        target_hour = 12
    elif "下" in time_str or "下午" in time_str:
        target_hour = 15
    elif "晚" in time_str or "晚上" in time_str or "今晚" in time_str:
        target_hour = 20
    
    # Try to extract specific hour/minute
    import re
    hour_match = re.search(r'(\d{1,2})[点时:：](\d{0,2})', time_str)
    if hour_match:
        h = int(hour_match.group(1))
        m = int(hour_match.group(2)) if hour_match.group(2) else 0
        
        # Handle PM times
        if "下午" in time_str or "晚" in time_str or "pm" in time_str.lower():
            if h < 12:
                h += 12
        elif "上午" in time_str or "早" in time_str or "am" in time_str.lower():
            if h == 12:
                h = 0
        
        target_hour = h
        target_minute = m
    
    # Handle "X点" without minutes
    hour_simple = re.search(r'(\d{1,2})[点时]', time_str)
    if hour_simple and not hour_match:
        h = int(hour_simple.group(1))
        if "下午" in time_str or "晚" in time_str:
            if h < 12:
                h += 12
        target_hour = h
        target_minute = 0
    
    result = datetime(target_date.year, target_date.month, target_date.day,
                      target_hour, target_minute)
    return result.strftime("%Y-%m-%d %H:%M")


async def process_message(session_id: str, user_message: str, 
                          speak_response: bool = True) -> str:
    """Process an incoming user message through the full pipeline.
    
    This is the main entry point for the conversation state machine:
    1. Check if there are pending slots to fill
    2. If yes, merge new info with existing slots
    3. If no, run intent analysis
    4. Based on intent, create task / query / chat
    
    Args:
        session_id: Session identifier (e.g., Feishu user ID)
        user_message: The user's message text
        speak_response: Whether to speak the response
    
    Returns:
        str: The reply text to send back to user
    """
    # Save user message
    conv_manager.add_message(session_id, "user", user_message)
    
    # Check for cancellation/interruption
    cancel_keywords = ["算了", "取消", "不用了", "别了", "放弃", "不要了"]
    if any(kw in user_message for kw in cancel_keywords):
        pending = conv_manager.get_pending_slots(session_id)
        if pending:
            conv_manager.clear_pending_slots(session_id)
            reply = "好的，已取消。"
            conv_manager.add_message(session_id, "assistant", reply, intent="CANCEL")
            if speak_response:
                await speak(reply)
            return reply
    
    # Check if we have pending slots to fill
    pending = conv_manager.get_pending_slots(session_id)
    
    if pending:
        # User is in a slot-filling conversation
        # Analyze the new message to extract missing info
        context = conv_manager.get_context_for_ai(session_id)
        result = await analyze_intent(user_message, context)
        
        # Merge slots
        merged_slots = {**pending["partial_slots"], **result["slots"]}
        still_missing = [s for s in pending["missing_slots"] if s not in result["slots"]]
        
        if not still_missing:
            # All slots filled! Create the task
            conv_manager.clear_pending_slots(session_id)
            reply = await _create_task_from_slots(merged_slots, session_id)
            if speak_response:
                await speak(reply)
            return reply
        else:
            # Still missing some slots, ask again
            conv_manager.save_pending_slots(session_id, merged_slots, still_missing)
            
            # Generate follow-up question
            slot_names = {
                "time": "时间",
                "content": "任务内容",
                "priority": "优先级"
            }
            missing_names = [slot_names.get(s, s) for s in still_missing]
            reply = result.get("reply") or f"还需要知道{'和'.join(missing_names)}，请补充一下？"
            
            conv_manager.add_message(session_id, "assistant", reply, 
                                    intent="SLOT_FILL", slots=merged_slots)
            if speak_response:
                await speak(reply)
            return reply
    
    # No pending slots - fresh message, analyze intent
    context = conv_manager.get_context_for_ai(session_id)
    result = await analyze_intent(user_message, context)
    
    # Save intent info
    conv_manager.add_message(session_id, "user", user_message, 
                            intent=result["intent"], slots=result["slots"])
    
    if result["intent"] == "ADD_TASK":
        # Check if we have enough info
        if result["missing_slots"]:
            # Save partial slots and ask for more info
            conv_manager.save_pending_slots(
                session_id, result["slots"], result["missing_slots"], user_message
            )
            reply = result["reply"]
            conv_manager.add_message(session_id, "assistant", reply, 
                                    intent="SLOT_FILL", slots=result["slots"])
        else:
            # All info present, create task
            reply = await _create_task_from_slots(result["slots"], session_id)
        
        if speak_response:
            await speak(reply)
        return reply
    
    elif result["intent"] == "QUERY_TASK":
        reply = await _handle_query(result["slots"], session_id)
        conv_manager.add_message(session_id, "assistant", reply, intent="QUERY")
        if speak_response:
            await speak(reply)
        return reply
    
    elif result["intent"] == "COMPLETE_TASK":
        reply = await _handle_complete(result["slots"], session_id)
        conv_manager.add_message(session_id, "assistant", reply, intent="COMPLETE")
        if speak_response:
            await speak(reply)
        return reply
    
    else:  # CHAT
        reply = result["reply"] or await chat_reply(user_message, context)
        conv_manager.add_message(session_id, "assistant", reply, intent="CHAT")
        if speak_response:
            await speak(reply)
        return reply


async def _create_task_from_slots(slots: dict, session_id: str) -> str:
    """Create a task from filled slots and return confirmation message"""
    content = slots.get("content", "未命名任务")
    time_str = slots.get("time")
    priority = slots.get("priority", "medium")
    recurring = slots.get("recurring")
    
    # Parse the time
    trigger_time = parse_time_string(time_str) if time_str else None
    
    # Create the task
    task = task_manager.add_task(
        content=content,
        trigger_time=trigger_time,
        priority=priority,
        is_recurring=recurring
    )
    
    # Schedule reminder if time is set
    if trigger_time:
        from .scheduler import schedule_task
        schedule_task(task["task_id"], trigger_time)
    
    # Build confirmation message
    reply_parts = [f"已添加任务：{content}"]
    if trigger_time:
        reply_parts.append(f"提醒时间：{trigger_time}")
    if priority == "high":
        reply_parts.append("优先级：高")
    if recurring:
        reply_parts.append(f"循环：{recurring}")
    
    reply = "，".join(reply_parts) + "。"
    
    conv_manager.add_message(session_id, "assistant", reply, 
                            intent="TASK_CREATED", slots=slots)
    return reply


async def _handle_query(slots: dict, session_id: str) -> str:
    """Handle task query intent"""
    content = slots.get("content", "")
    
    if content:
        tasks = task_manager.search_tasks(content)
    else:
        tasks = task_manager.list_tasks(status="pending", limit=5)
    
    if not tasks:
        return "目前没有相关任务。"
    
    reply_parts = ["当前任务："]
    for i, task in enumerate(tasks[:5], 1):
        status_emoji = "✅" if task["status"] == "completed" else "⏳"
        time_info = f"（{task['trigger_time']}）" if task["trigger_time"] else ""
        reply_parts.append(f"{i}. {status_emoji} {task['content']}{time_info}")
    
    return "\n".join(reply_parts)


async def _handle_complete(slots: dict, session_id: str) -> str:
    """Handle task completion intent"""
    content = slots.get("content", "")
    
    if content:
        tasks = task_manager.search_tasks(content)
        pending = [t for t in tasks if t["status"] == "pending"]
        
        if pending:
            task = pending[0]
            task_manager.complete_task(task["task_id"])
            return f"已完成任务：{task['content']} ✅"
        else:
            return f"没有找到相关待办任务：{content}"
    
    return "请告诉我完成了哪个任务？"

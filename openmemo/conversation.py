"""Conversation state machine for slot filling"""
import json
import re
from datetime import datetime, timedelta
from .ai import analyze_intent
from .tasks import TaskManager, ConversationManager
from .voice import speak


task_manager = TaskManager()
conv_manager = ConversationManager()


def parse_time_string(time_str: str) -> str | None:
    """解析自然语言时间字符串为 YYYY-MM-DD HH:MM 格式。
    
    支持中文和英文：
    - 今天/明天/后天 + 时间
    - 下周一/下周二 + 时间
    - 2小时后、30分钟后
    - 今晚/明早 + 时间
    - 下午3点、3:30、15:00
    - today/tomorrow, next Monday, in 2 hours
    """
    if not time_str:
        return None
    
    now = datetime.now()
    target_date = now.date()
    target_hour = 9
    target_minute = 0
    time_str = time_str.strip().lower()
    
    # 先尝试直接日期时间格式
    for fmt in ["%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"]:
        try:
            dt = datetime.strptime(time_str, fmt)
            return dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            continue
    
    # 解析"X小时后/X分钟后"
    in_match = re.search(r'(\d+)\s*(小时|分钟|hour|hr|minute|min)后?', time_str)
    if in_match:
        amount = int(in_match.group(1))
        unit = in_match.group(2)
        if unit.startswith('小时') or unit.startswith('hour') or unit.startswith('hr'):
            target = now + timedelta(hours=amount)
        else:
            target = now + timedelta(minutes=amount)
        return target.strftime("%Y-%m-%d %H:%M")
    
    # 解析相对日期 - 中文
    if "今天" in time_str or "今日" in time_str:
        target_date = now.date()
    elif "明天" in time_str:
        target_date = (now + timedelta(days=1)).date()
    elif "后天" in time_str:
        target_date = (now + timedelta(days=2)).date()
    elif "大后天" in time_str:
        target_date = (now + timedelta(days=3)).date()
    # 解析相对日期 - 英文
    elif "today" in time_str:
        target_date = now.date()
    elif "tomorrow" in time_str:
        target_date = (now + timedelta(days=1)).date()
    elif "day after tomorrow" in time_str:
        target_date = (now + timedelta(days=2)).date()
    
    # 解析星期 - 中文
    weekday_cn = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
    if "下周" in time_str or "这周" in time_str or "本周" in time_str:
        for key, weekday in weekday_cn.items():
            if key in time_str:
                days_ahead = weekday - now.weekday()
                if days_ahead <= 0:
                    days_ahead += 7
                target_date = (now + timedelta(days=days_ahead)).date()
                break
    
    # 解析星期 - 英文
    weekday_en = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6,
        "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6
    }
    for name, weekday in weekday_en.items():
        if name in time_str:
            days_ahead = weekday - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            target_date = (now + timedelta(days=days_ahead)).date()
            break
    
    # 解析时间段 - 中文
    if "早" in time_str or "上午" in time_str:
        target_hour = 9
    elif "中午" in time_str:
        target_hour = 12
    elif "下午" in time_str:
        target_hour = 15
    elif "晚" in time_str or "今晚" in time_str:
        target_hour = 20
    # 解析时间段 - 英文
    elif "morning" in time_str:
        target_hour = 9
    elif "noon" in time_str:
        target_hour = 12
    elif "afternoon" in time_str:
        target_hour = 15
    elif "evening" in time_str or "tonight" in time_str:
        target_hour = 20
    elif "night" in time_str:
        target_hour = 21
    
    # 提取具体时间 - 中文格式 X点/X时
    cn_time = re.search(r'(\d{1,2})[点时:：](\d{0,2})', time_str)
    if cn_time:
        h = int(cn_time.group(1))
        m = int(cn_time.group(2)) if cn_time.group(2) else 0
        if ("下午" in time_str or "晚" in time_str) and h < 12:
            h += 12
        target_hour = h
        target_minute = m
    
    # 提取具体时间 - 英文格式 3pm, 3:30pm, 15:00
    en_time = re.search(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)?', time_str)
    if en_time and not cn_time:
        h = int(en_time.group(1))
        m = int(en_time.group(2)) if en_time.group(2) else 0
        ampm = en_time.group(3)
        
        if ampm == "pm" and h < 12:
            h += 12
        elif ampm == "am" and h == 12:
            h = 0
        elif ("下午" in time_str or "晚" in time_str) and h < 12:
            h += 12
        
        target_hour = h
        target_minute = m
    
    result = datetime(target_date.year, target_date.month, target_date.day,
                      target_hour, target_minute)
    return result.strftime("%Y-%m-%d %H:%M")


async def process_message(session_id: str, user_message: str, 
                          speak_response: bool = True) -> str:
    """处理用户消息的主入口。"""
    # 保存用户消息
    conv_manager.add_message(session_id, "user", user_message)
    
    # 检查取消意图
    cancel_keywords = ["算了", "取消", "不用了", "放弃", "cancel", "never mind", "forget it"]
    if any(kw in user_message.lower() for kw in cancel_keywords):
        pending = conv_manager.get_pending_slots(session_id)
        if pending:
            conv_manager.clear_pending_slots(session_id)
            reply = "好的，已取消！有需要随时找我。"
            conv_manager.add_message(session_id, "assistant", reply, intent="CANCEL")
            if speak_response:
                await speak(reply)
            return reply
    
    # 检查是否有待补充的信息
    pending = conv_manager.get_pending_slots(session_id)
    
    if pending:
        context = conv_manager.get_context_for_ai(session_id)
        result = await analyze_intent(user_message, context)
        
        merged_slots = {**pending["partial_slots"], **result["slots"]}
        still_missing = [s for s in pending["missing_slots"] if s not in result["slots"] or not result["slots"].get(s)]
        
        if not still_missing:
            conv_manager.clear_pending_slots(session_id)
            reply = await _create_task_from_slots(merged_slots, session_id)
            if speak_response:
                await speak(reply)
            return reply
        else:
            conv_manager.save_pending_slots(session_id, merged_slots, still_missing)
            slot_labels = {"time": "时间", "content": "任务内容", "priority": "优先级"}
            missing_labels = [slot_labels.get(s, s) for s in still_missing]
            reply = f"还需要知道{'和'.join(missing_labels)}，请补充一下？"
            conv_manager.add_message(session_id, "assistant", reply, 
                                    intent="SLOT_FILL", slots=merged_slots)
            if speak_response:
                await speak(reply)
            return reply
    
    # 新消息，分析意图
    context = conv_manager.get_context_for_ai(session_id)
    result = await analyze_intent(user_message, context)
    
    if result["intent"] == "ADD_TASK":
        if result["missing_slots"]:
            conv_manager.save_pending_slots(
                session_id, result["slots"], result["missing_slots"], user_message
            )
            reply = result["reply"]
            conv_manager.add_message(session_id, "assistant", reply, 
                                    intent="SLOT_FILL", slots=result["slots"])
        else:
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
        reply = result["reply"]
        conv_manager.add_message(session_id, "assistant", reply, intent="CHAT")
        if speak_response:
            await speak(reply)
        return reply


async def _create_task_from_slots(slots: dict, session_id: str) -> str:
    """从已填充的信息创建任务并返回确认消息"""
    content = slots.get("content", "未命名任务")
    time_str = slots.get("time")
    priority = slots.get("priority", "medium")
    recurring = slots.get("recurring")
    
    trigger_time = parse_time_string(time_str) if time_str else None
    
    task = task_manager.add_task(
        content=content,
        trigger_time=trigger_time,
        priority=priority,
        is_recurring=recurring
    )
    
    if trigger_time:
        from .scheduler import schedule_task
        schedule_task(task["task_id"], trigger_time)
    
    parts = [f"任务已添加：{content} 📝"]
    if trigger_time:
        parts.append(f"提醒时间：{trigger_time} ⏰")
    if priority == "high":
        parts.append("优先级：高 🔴")
    if recurring:
        parts.append(f"循环：{recurring} 🔄")
    
    reply = "，".join(parts) + "。"
    
    conv_manager.add_message(session_id, "assistant", reply, 
                            intent="TASK_CREATED", slots=slots)
    return reply


async def _handle_query(slots: dict, session_id: str) -> str:
    """处理查询任务意图"""
    content = slots.get("content", "")
    
    if content:
        tasks = task_manager.search_tasks(content)
    else:
        tasks = task_manager.list_tasks(status="pending", limit=5)
    
    if not tasks:
        return "目前没有待办任务，你很清闲！🎉"
    
    lines = ["你目前的任务："]
    for i, task in enumerate(tasks[:5], 1):
        status = "✅" if task["status"] == "completed" else "⏳"
        time_info = f"（{task['trigger_time']}）" if task.get("trigger_time") else ""
        lines.append(f"{i}. {status} {task['content']}{time_info}")
    
    return "\n".join(lines)


async def _handle_complete(slots: dict, session_id: str) -> str:
    """处理完成任务意图"""
    content = slots.get("content", "")
    
    if content:
        tasks = task_manager.search_tasks(content)
        pending = [t for t in tasks if t["status"] == "pending"]
        
        if pending:
            task = pending[0]
            task_manager.complete_task(task["task_id"])
            return f"已完成：{task['content']} ✅"
        else:
            return f"没有找到待办任务：{content}"
    
    return "你完成了哪个任务？告诉我名字我帮你标记。"

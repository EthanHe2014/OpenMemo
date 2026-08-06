"""Conversation state machine for slot filling"""
import json
import re
from datetime import datetime, timedelta
from .ai import analyze_intent
from .tasks import TaskManager, ConversationManager
from .voice import speak


task_manager = TaskManager()
conv_manager = ConversationManager()


# Slots that should always be proactively asked if missing
FILLABLE_SLOTS = {"time": "时间", "duration": "预计耗时", "content": "任务内容", "priority": "优先级"}


def parse_duration_string(duration_str: str) -> int | None:
    """解析自然语言耗时字符串为分钟数。
    
    支持：
    - 30分钟 / 半小时
    - 1小时 / 一个半小时 / 1.5小时 / 2个小时
    - 1.5h / 90min / 45 mins
    - "一小时左右"、"大约半小时"
    返回分钟数，失败返回 None。
    """
    if not duration_str:
        return None
    s = duration_str.strip().lower()
    
    # 直接数字分钟
    m = re.search(r'(\d+)\s*(分钟|minute|min|mins)', s)
    if m:
        return int(m.group(1))
    
    # 一个半小时 = 1.5小时（必须先于“半”判断）
    if re.search(r'一个半小时|一个半小時', s):
        return 90
    
    # 半小时/半小時
    if re.search(r'半\s*(小时|小時)?', s):
        return 30
    
    # 小时缩写 + 分钟（1h30m、1h30、1h 30m）——必须放在小时判断之前
    hm = re.search(r'(\d+)\s*(h|hr)\s*(\d+)\s*(m|min)?', s)
    if hm:
        return int(hm.group(1)) * 60 + int(hm.group(3))
    
    # 小时（含小数、分数）  如 1小时、1.5小时、2个小时、90分钟
    h = re.search(r'(\d+(?:\.\d+)?)\s*(个)?\s*(小时|小時|h|hr)', s)
    if h:
        return int(float(h.group(1)) * 60)
    
    # 中文数字小时（如“三个小时”），但“一个半小时”已提前处理
    if re.search(r'([一二两三四五六七八九十]+)\s*(个)?\s*小时', s):
        cn_map = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
        num = re.search(r'([一二两三四五六七八九十]+)\s*(个)?\s*小时', s).group(1)
        if num == "十":
            return 600  # 十小时 → 600分钟
        val = 0
        for ch in num:
            val += cn_map.get(ch, 0)
        return val * 60
    
    # 英文单词小时（one hour / two hours / half an hour / an hour）
    en_num = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
              "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
    if re.search(r'\b(half\s+an?|an?)\s+hour', s):
        if "half" in s:
            return 30
        return 60
    em = re.search(r'\b(' + "|".join(en_num.keys()) + r')\s+hours?', s)
    if em:
        return en_num[em.group(1)] * 60
    
    # 直接数字（没有单位）——保守猜测为分钟；但含时间标记（点/时/o'clock/am/pm）的不算
    if re.search(r'[点时]|o\s*\'?clock|\b(am|pm)\b', s):
        return None
    plain = re.search(r'(\d+)', s)
    if plain:
        return int(plain.group(1))
    
    return None


def _extract_time_from_text(text: str) -> str | None:
    """从文本中确定性地提取时间（若有），返回解析后的 'YYYY-MM-DD HH:MM' 格式。
    仅当文本确实包含时间表达时才返回，否则返回 None。
    """
    if not text:
        return None
    t = text.lower().strip()
    
    # 检查是否包含时间相关关键词
    time_keywords = [
        '今天', '明天', '后天', '下午', '晚上', '今晚', '明早', '上午', '中午', '早上', '零点', '凌晨',
        'today', 'tomorrow', 'tonight', 'am', 'pm', 'noon', 'morning', 'afternoon', 'evening', 'night',
    ]
    has_time_word = any(kw in t for kw in time_keywords)
    # 也检查明确的“X点/X时/数字冒号” 模式，如 "3点"、"15:00"、"3:30"（排除“一小时/个半小时”这类时长）
    has_time_format = bool(
        re.search(r'\d\s*[点时:：]', t)          # 3点 / 3时 / 3: / 3：
        or re.search(r'\d{1,2}:\d{2}', t)       # 15:00
        or re.search(r'\d{1,2}\s*(am|pm)', t)   # 3pm
    )
    
    if not has_time_word and not has_time_format:
        return None
    
    return parse_time_string(text)


def find_conflicts(new_time: str, duration_minutes: int | None, exclude_task_id: int = None) -> list:
    """检查新任务时间是否与已有待办任务冲突。
    
    返回冲突任务列表。需要用自然语言 duration 解析的结果和 trigger_time 计算时间区间。
    """
    if not new_time:
        return []
    try:
        new_start = datetime.strptime(new_time, "%Y-%m-%d %H:%M")
    except ValueError:
        return []
    
    dur = duration_minutes or 60  # 默认1小时
    new_end = new_start + timedelta(minutes=dur)
    
    conflicts = []
    for task in task_manager.list_tasks(status="pending", limit=40):
        if exclude_task_id and task["task_id"] == exclude_task_id:
            continue
        t = task.get("trigger_time")
        if not t or t == new_time:
            # 若时间完全相同但非同一任务，视为冲突
            if t == new_time and not (exclude_task_id and task["task_id"] == exclude_task_id):
                conflicts.append(task)
            continue
        try:
            start = datetime.strptime(t, "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        # 已有任务时长未知，按默认60分钟估计其区间
        end = start + timedelta(minutes=task.get("duration_minutes") or 60)
        # 区间重叠判断
        if new_start < end and start < new_end:
            overlaps_start = new_start if new_start > start else start
            overlaps_end = new_end if new_end < end else end
            if overlaps_end > overlaps_start:
                conflicts.append(task)
    
    return conflicts


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
    
    # 提取具体时间 - 中文格式 X点/X时/X点半（阿拉伯数字）
    cn_time = re.search(r'(\d{1,2})[点时:：](半|\d{0,2})', time_str)
    if cn_time:
        h = int(cn_time.group(1))
        frac = cn_time.group(2)
        if frac == "半":
            m = 30
        elif frac:
            m = int(frac)
        else:
            m = 0
        if ("下午" in time_str or "晚" in time_str) and h < 12:
            h += 12
        target_hour = h
        target_minute = m
    else:
        # 中文数字小时：三点半、下午三点、五点
        cn_hour_map = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
                       "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12}
        cn_time2 = re.search(r'([零一二两三四五六七八九十]+)[点时](半|\d{0,1})', time_str)
        if cn_time2 and cn_time2.group(1) in cn_hour_map:
            h = cn_hour_map[cn_time2.group(1)]
            frac = cn_time2.group(2)
            m = 30 if frac == "半" else (int(frac) if frac else 0)
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
        pending_intent = pending.get("intent", "ADD_TASK")
        
        # pending 分支：保留已确定的字段（AI 可能重写 content 等关键信息）
        merged_slots = dict(pending["partial_slots"])
        for k, v in result["slots"].items():
            if k not in merged_slots or not merged_slots.get(k):
                merged_slots[k] = v
        still_missing = [s for s in pending["missing_slots"] if s not in result["slots"] or not result["slots"].get(s)]
        
        # 确定性补充：从本次用户消息挖出缺失的字段（不依赖AI提取）
        # ADD_TASK：time / duration
        if pending_intent == "ADD_TASK":
            parsed_t = _extract_time_from_text(user_message)
            if parsed_t and "time" in still_missing:
                merged_slots["time"] = parsed_t
                still_missing = [s for s in still_missing if s != "time"]
            if "duration" in still_missing:
                parsed_dur = parse_duration_string(user_message)
                if parsed_dur is not None:
                    merged_slots["duration"] = user_message
                    merged_slots["duration_minutes"] = parsed_dur
                    still_missing = [s for s in still_missing if s != "duration"]
            if merged_slots.get("time") and not merged_slots.get("duration") and "duration" not in still_missing:
                still_missing.append("duration")
        # TRAVEL_EVENT：commute_minutes / flight_type
        elif pending_intent == "TRAVEL_EVENT":
            if "commute_minutes" in still_missing:
                cm = re.search(r'(\d{1,3})\s*(分钟|min|mins)?', user_message)
                if cm:
                    merged_slots["commute_minutes"] = int(cm.group(1))
                    still_missing = [s for s in still_missing if s != "commute_minutes"]
            if "flight_type" in still_missing:
                if any(k in user_message for k in ["国际", "international", "境外"]):
                    merged_slots["flight_type"] = "international"
                    still_missing = [s for s in still_missing if s != "flight_type"]
                elif any(k in user_message for k in ["国内", "domestic"]):
                    merged_slots["flight_type"] = "domestic"
                    still_missing = [s for s in still_missing if s != "flight_type"]
        # NEWS_JOB：time / topic
        elif pending_intent == "NEWS_JOB":
            # 数字+点 = 时间
            tm = re.search(r'(\d{1,2})\s*[点时]', user_message)
            if tm and "time" in still_missing:
                merged_slots["time"] = f"每天{tm.group(1)}点"
                still_missing = [s for s in still_missing if s != "time"]
            # topic 从消息里找已知类型词
            topic_map = {"科技": "科技", "tech": "科技", "体育": "体育", "sport": "体育",
                         "财经": "财经", "金融": "财经", "weather": "天气", "天气": "天气",
                         "综合": "综合", "要闻": "综合", "娱乐": "娱乐", "游戏": "游戏"}
            for key, val in topic_map.items():
                if key in user_message and "topic" in still_missing:
                    merged_slots["topic"] = val
                    still_missing = [s for s in still_missing if s != "topic"]
                    break
        # SCHEDULE：tasks / deadline / remind_time
        elif pending_intent == "SCHEDULE":
            if "tasks" in still_missing:
                # 尝试解析 "我有X、Y、Z" 或 "X和Y"
                t_rewrite = re.sub(r'(我有|包括|需要写|作业有|清单：?)', '', user_message)
                # 用顿号/逗号/“和”分割
                parts = re.split(r'[、，,和及空格]+', t_rewrite.strip())
                parts = [p for p in parts if p and len(p) <= 20 and not _looks_like_date(p)]
                if parts:
                    merged_slots["tasks"] = parts
                    still_missing = [s for s in still_missing if s != "tasks"]
            if "deadline" in still_missing:
                dl = re.search(r'(?:\d{1,2})[月/](?:\d{1,2})日?', user_message)
                if dl:
                    merged_slots["deadline"] = dl.group(0)
                    still_missing = [s for s in still_missing if s != "deadline"]
                elif any(k in user_message for k in ["明天", "后天"]):
                    merged_slots["deadline"] = "明天" if "明天" in user_message else "后天"
                    still_missing = [s for s in still_missing if s != "deadline"]
            if "remind_time" in still_missing:
                rt = re.search(r'(\d{1,2})\s*点', user_message)
                if rt:
                    merged_slots["remind_time"] = f"{rt.group(1)}:00"
                    still_missing = [s for s in still_missing if s != "remind_time"]
        
        if not still_missing:
            conv_manager.clear_pending_slots(session_id)
            # 按意图路由到正确的最终处理
            if pending_intent == "TRAVEL_EVENT":
                reply = await _handle_travel_event({"intent":"TRAVEL_EVENT","slots":merged_slots,"missing_slots":[]}, session_id, speak_response)
                return reply
            elif pending_intent == "NEWS_JOB":
                reply = await _handle_news_job({"intent":"NEWS_JOB","slots":merged_slots,"missing_slots":[]}, session_id, speak_response)
                return reply
            elif pending_intent == "SCHEDULE":
                reply = await _handle_schedule({"intent":"SCHEDULE","slots":merged_slots,"missing_slots":[]}, session_id, speak_response)
                return reply
            else:
                reply = await _create_task_from_slots(merged_slots, session_id)
            if speak_response:
                await speak(reply)
            return reply
        else:
            conv_manager.save_pending_slots(session_id, merged_slots, still_missing, intent=pending_intent)
            reply = _humanize_missing_ask(merged_slots, still_missing, result.get("reply"))
            conv_manager.add_message(session_id, "assistant", reply, 
                                    intent="SLOT_FILL", slots=merged_slots)
            if speak_response:
                await speak(reply)
            return reply
    
    # 新消息，分析意图
    context = conv_manager.get_context_for_ai(session_id)
    result = await analyze_intent(user_message, context)
    
    if result["intent"] == "ADD_TASK":
        # 确定性地补充缺失的 slot 检查（AI 可能漏掉）
        slots = result["slots"]
        missing = result.get("missing_slots", [])
        
        # 确定性补充：直接从原始消息挖 time/duration
        if not slots.get("time"):
            raw_t = _extract_time_from_text(user_message)
            if raw_t:
                slots["time"] = user_message  # 存原始文本，conversation._create 会 parse
        if not slots.get("duration") and not slots.get("duration_minutes"):
            raw_dur = parse_duration_string(user_message)
            if raw_dur is not None:
                slots["duration"] = user_message
                slots["duration_minutes"] = raw_dur
        
        # 如果有 content 但没 time，强制追问时间
        if slots.get("content") and not slots.get("time") and "time" not in missing:
            missing.append("time")
        # 只有已有明确时间时才追问 duration（避免一次性问太多）
        if slots.get("time") and not slots.get("duration") and "duration" not in missing:
            missing.append("duration")
        
        if missing:
            conv_manager.save_pending_slots(
                session_id, slots, missing, user_message
            )
            reply = _humanize_missing_ask(slots, missing, result.get("reply"))
            conv_manager.add_message(session_id, "assistant", reply, 
                                    intent="SLOT_FILL", slots=slots)
        else:
            reply = await _create_task_from_slots(slots, session_id)
        
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
    
    elif result["intent"] == "NEWS_JOB":
        return await _handle_news_job(result, session_id, speak_response)
    
    elif result["intent"] == "TRAVEL_EVENT":
        return await _handle_travel_event(result, session_id, speak_response)
    
    elif result["intent"] == "SCHEDULE":
        return await _handle_schedule(result, session_id, speak_response)
    
    else:  # CHAT
        reply = result["reply"]
        conv_manager.add_message(session_id, "assistant", reply, intent="CHAT")
        if speak_response:
            await speak(reply)
        return reply


def _humanize_missing_ask(slots: dict, still_missing: list, ai_reply: str = None) -> str:
    """追问缺失信息，用自然对话语气（优先用 AI 的 reply，否则用模板）。"""
    content = slots.get("content", "")
    # 利用 AI 提供的自然追问（若只缺一个 slot，AI 通常提供了更好的问法）
    if ai_reply and len(still_missing) == 1:
        # 但避免 AI 重复创建任务或幻觉名词（reply 里若含“已添加”/“添加了”则改用模板；
        # 追问 duration 时 AI 常幻觉名词，直接用确定性模板）
        if "已添加" not in ai_reply and "添加了" not in ai_reply and still_missing[0] != "duration":
            return ai_reply
    
    asks = []
    for s in still_missing:
        if s == "time":
            asks.append(f"{content}想安排在几点呀？")
        elif s == "duration":
            asks.append(f"{content}大概要多久呀？")
        elif s == "content":
            asks.append("想做什么呢？")
        elif s == "priority":
            asks.append("这个任务重要吗？")
        else:
            asks.append(f"请补充{FILLABLE_SLOTS.get(s, s)}：")
    
    if len(asks) == 1:
        return asks[0]
    prefix = f"关于{content}，" if content else ""
    return prefix + "、".join(asks[:-1]) + "，还有" + asks[-1]


async def _create_task_from_slots(slots: dict, session_id: str) -> str:
    """从已填充的信息创建任务并返回确认消息"""
    content = slots.get("content", "未命名任务")
    time_str = slots.get("time")
    priority = slots.get("priority", "medium")
    recurring = slots.get("recurring")
    duration_str = slots.get("duration_minutes") or slots.get("duration")
    
    trigger_time = parse_time_string(time_str) if time_str else None
    
    # 解析耗时
    duration_minutes = None
    if isinstance(duration_str, int):
        duration_minutes = duration_str
    elif duration_str:
        duration_minutes = parse_duration_string(str(duration_str))
    
    task = task_manager.add_task(
        content=content,
        trigger_time=trigger_time,
        priority=priority,
        is_recurring=recurring,
        duration_minutes=duration_minutes
    )
    
    if trigger_time:
        from .scheduler import schedule_task
        schedule_task(task["task_id"], trigger_time)
    
    parts = [f"任务已添加：{content} 📝"]
    if trigger_time:
        parts.append(f"提醒时间：{trigger_time} ⏰")
    if duration_minutes:
        parts.append(f"预计耗时：{duration_minutes}分钟 ⏱️")
    if priority == "high":
        parts.append("优先级：高 🔴")
    if recurring:
        parts.append(f"循环：{recurring} 🔄")
    
    reply = "，".join(parts) + "。"
    
    # 冲突检测
    if trigger_time:
        conflicts = find_conflicts(trigger_time, duration_minutes, exclude_task_id=task["task_id"])
        if conflicts:
            conflict_lines = []
            for c in conflicts[:3]:
                t = c.get("trigger_time") or "时间未知"
                c_dur = c.get("duration_minutes")
                dur_txt = f"（约{c_dur}分钟）" if c_dur else ""
                conflict_lines.append(f"· {t} {c['content']}{dur_txt}")
            warn = (f"\n\n⚠️ 注意时间冲突！你{trigger_time}安排的项目与以下任务重叠：\n"
                    + "\n".join(conflict_lines)
                    + "\n需要调整时间吗？")
            reply += warn
    
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


# ============ SMART INTENT HANDLERS (NEWS_JOB / TRAVEL_EVENT / SCHEDULE) ============

def _store_schedule_md(meta_data: dict) -> str:
    """把日程表 meta_data 转成 markdown 字符串（供每天提醒时读取）。"""
    lines = [f"# {meta_data.get('content', '任务日程')}", ""]
    for day in meta_data.get("schedule", []):
        head = day.get("date")  # 'YYYY-MM-DD'
        items = day.get("items", [])
        if head:
            try:
                dt = datetime.strptime(head, "%Y-%m-%d")
                head_disp = f"{dt.month}月{dt.day}日（周{['一','二','三','四','五','六','日'][dt.weekday()]}）"
            except ValueError:
                head_disp = head
            lines.append(f"## {head_disp}")
            for it in items:
                lines.append(f"- {it}")
            lines.append("")
    return "\n".join(lines)


def _build_schedule_plan(tasks: list, deadline_str: str, start_date=None) -> list:
    """把任务清单按天均匀分配到 deadline 之前。
    tasks: ["习字", "西游记", ...]
    deadline_str: "8月10日" / "2026-08-10" / "后天"
    返回 [{date, items}, ...]
    """
    from datetime import datetime
    now = datetime.now()
    
    # 解析 deadline
    deadline = None
    dl = deadline_str.strip().lower() if deadline_str else ""
    
    # 直接日期
    for fmt in ["%Y-%m-%d", "%Y/%m/%d"]:
        try:
            deadline = datetime.strptime(dl, fmt)
            break
        except ValueError:
            continue
    if deadline is None:
        # "8月10日" / "8/10"
        m = re.search(r'(\d{1,2})[月/](\d{1,2})日?', dl)
        if m:
            month, day = int(m.group(1)), int(m.group(2))
            deadline = datetime(now.year, month, day)
    if deadline is None and "明天" in dl:
        deadline = now + timedelta(days=1)
    if deadline is None and "后天" in dl:
        deadline = now + timedelta(days=2)
    if deadline is None:
        # 默认7天后
        deadline = now + timedelta(days=7)
    
    if deadline.date() <= now.date():
        deadline = now + timedelta(days=1)
    
    start = start_date or now
    days_available = max((deadline.date() - start.date()).days, 1)
    
    # 生成按天分布
    plan = []
    task_list = [t for t in tasks if t and str(t).strip()]
    if not task_list:
        return [{"date": start.strftime("%Y-%m-%d"), "items": []}]
    
    # 简单的轮询分配：每个任务尽量错开
    for i in range(days_available):
        d = (start + timedelta(days=i)).strftime("%Y-%m-%d")
        # 取属于这一天的任务（轮询）
        day_tasks = task_list[i::days_available]
        plan.append({"date": d, "items": day_tasks})
    
    # 如果任务太少，把没分配完的天补空
    return plan


def _build_travel_reminder_time(event_time: str, commute_minutes: int, flight_type: str) -> str:
    """反算出发提醒时间。
    event_time 例如 '2026-08-06 13:00'
    commute_minutes: 去机场/车站耗时（分钟）
    flight_type: domestic 国内提前2h / international 国际提前3h
    返回 'YYYY-MM-DD HH:MM' 的提醒时间。
    """
    try:
        evt = datetime.strptime(event_time, "%Y-%m-%d %H:%M")
    except ValueError:
        return event_time  # 无法解析就原样
    
    buffer_hours = 3 if flight_type == "international" else 2
    remind = evt - timedelta(minutes=commute_minutes) - timedelta(hours=buffer_hours)
    return remind.strftime("%Y-%m-%d %H:%M")


def _looks_like_date(s: str) -> bool:
    """粗略判断一个词是否像日期（用于SCHEDULE任务清单拆分时的过滤）。"""
    s = s.strip()
    return bool(re.search(r'(\d{1,2})[月/](\d{1,2})', s)) or s in ("明天", "后天", "今天")

async def _handle_news_job(result: dict, session_id: str, speak_response: bool = True) -> str:
    """NEWS_JOB：动态信息任务（每天推送新闻/天气等）。
    如果信息不全，先追问；信息全了，创建 news 类型的循环任务。
    """
    slots = dict(result.get("slots") or {})
    missing = list(result.get("missing_slots") or [])
    
    # 追问缺失信息
    if missing:
        conv_manager.save_pending_slots(session_id, slots, missing, intent="NEWS_JOB")
        reply = result.get("reply") or _humanize_missing_ask(slots, missing)
        conv_manager.add_message(session_id, "assistant", reply, intent="SLOT_FILL", slots=slots)
        if speak_response:
            await speak(reply)
        return reply
    
    # 信息全了 → 创建 news 类型
    topic = slots.get("topic") or "综合"
    schedule_time = slots.get("time") or "每天9点"
    # 解析每天几点
    import re as _re
    time_match = _re.search(r'(\d{1,2})\s*[点时]', schedule_time)
    daily_hour = int(time_match.group(1)) if time_match else 9
    
    task = task_manager.add_task(
        content=f"每日{topic}新闻",
        trigger_time=None,
        priority="medium",
        is_recurring="每天",
        task_type="news",
        meta_data={"topic": topic, "daily_hour": daily_hour, "time_desc": schedule_time}
    )
    
    reply = f"明白！每天{daily_hour}点给你推送{topic}新闻 📰，到时候准时送上新鲜内容！"
    # news任务由 scheduler 里的智能回调处理循环
    
    conv_manager.add_message(session_id, "assistant", reply, intent="NEWS_JOB", slots=slots)
    if speak_response:
        await speak(reply)
    return reply


async def _handle_travel_event(result: dict, session_id: str, speak_response: bool = True) -> str:
    """TRAVEL_EVENT：出行事件，反算出发提醒时间。
    """
    slots = dict(result.get("slots") or {})
    missing = list(result.get("missing_slots") or [])
    
    if missing:
        conv_manager.save_pending_slots(session_id, slots, missing, intent="TRAVEL_EVENT")
        reply = result.get("reply") or _humanize_missing_ask(slots, missing)
        conv_manager.add_message(session_id, "assistant", reply, intent="SLOT_FILL", slots=slots)
        if speak_response:
            await speak(reply)
        return reply
    
    # 信息全了 → 反算
    content = slots.get("content") or "出行"
    event_time_raw = slots.get("event_time") or ""
    event_time = parse_time_string(event_time_raw) if event_time_raw else None
    if not event_time:
        # 无法解析事件时间，给个兜底
        reply = "出行时间我还没太确定，能再说一下具体几点吗？"
        conv_manager.add_message(session_id, "assistant", reply, intent="TRAVEL_EVENT")
        if speak_response:
            await speak(reply)
        return reply
    
    commute = int(slots.get("commute_minutes") or 60)
    ftype = slots.get("flight_type") or "domestic"
    remind_time = _build_travel_reminder_time(event_time, commute, ftype)
    
    task = task_manager.add_task(
        content=f"出发去{content}",
        trigger_time=remind_time,
        priority="high",
        task_type="travel",
        meta_data={"event_time": event_time, "commute_minutes": commute, "flight_type": ftype}
    )
    
    from .scheduler import schedule_task
    schedule_task(task["task_id"], remind_time)
    
    # 生成人性化确认
    buf = "国际" if ftype == "international" else "国内"
    buffer_desc = "3小时" if ftype == "international" else "2小时"
    hint = f"你是{buf}出行，建议提前{buffer_desc}到机场/车站，路上{commute}分钟。"
    reply = f"收到！{event_time}的{buf}出行，{hint}我会在{remind_time}提醒你出发 ✈️"
    
    conv_manager.add_message(session_id, "assistant", reply, intent="TRAVEL_EVENT", slots=slots)
    if speak_response:
        await speak(reply)
    return reply


async def _handle_schedule(result: dict, session_id: str, speak_response: bool = True) -> str:
    """SCHEDULE：带日程表的任务集（如暑假作业），自动按天生成日程表。
    """
    slots = dict(result.get("slots") or {})
    missing = list(result.get("missing_slots") or [])
    
    if missing:
        conv_manager.save_pending_slots(session_id, slots, missing, intent="SCHEDULE")
        reply = result.get("reply") or _humanize_missing_ask(slots, missing)
        conv_manager.add_message(session_id, "assistant", reply, intent="SLOT_FILL", slots=slots)
        if speak_response:
            await speak(reply)
        return reply
    
    content = slots.get("content") or "任务"
    tasks = slots.get("tasks") or []
    deadline = slots.get("deadline")
    remind_time = slots.get("remind_time") or "11:00"
    
    # 生成按天日程
    plan = _build_schedule_plan(tasks, deadline)
    meta = {
        "content": content,
        "tasks": tasks,
        "deadline": deadline,
        "remind_time": remind_time,
        "schedule": plan
    }
    schedule_md = _store_schedule_md(meta)
    
    # 保存为 schedule 类型任务（一次创建,存 meta_data 里的完整日程）
    task = task_manager.add_task(
        content=f"{content}（每日提醒）",
        trigger_time=None,
        priority="medium",
        is_recurring="每天",
        task_type="schedule",
        meta_data=meta
    )
    
    # 每天提醒时间提示
    day_count = len(plan)
    deadline_disp = meta.get("deadline") or "截止日"
    reply = (f"收到！{content}，共{len(tasks)}项作业，{deadline_disp}前完成。"
             f"我生成了{day_count}天的安排，每天{remind_time}提醒你当天该做的内容 📅")
    
    conv_manager.add_message(session_id, "assistant", reply, intent="SCHEDULE", slots=slots)
    if speak_response:
        await speak(reply)
    return reply

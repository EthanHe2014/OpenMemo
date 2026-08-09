"""调度模块 —— 基于 APScheduler 的任务提醒"""
import asyncio
import re
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.cron import CronTrigger
from .tasks import TaskManager
from .voice import speak
from .ai import call_ai


scheduler = AsyncIOScheduler()
task_manager = TaskManager()

# AI prompt for generating natural, varied reminder messages
REMINDER_PROMPT = """你是OpenMemo的提醒功能。现在有一个任务到了提醒时间，你需要生成一段提醒消息。

## 核心原则
你是一个有个性、有温度的智能助手，不是复读机。每次提醒都要像朋友在提醒你一样——自然、多样、有惊喜感。

## 上下文信息
你会收到：当前时间、任务内容、优先级、用户今天其他待办任务。利用这些信息让提醒更贴心、更智能。

## 生成规则
1. 必须用中文
2. **绝对不要重复同一个句式**——每次都要换花样，可以用：
   - 直接提醒型：「嘿，该去做XX了！」
   - 关心型：「XX的时间到了，别太累哦～」
   - 幽默型：「叮咚！XX来敲门了，快去迎接吧」
   - 鼓励型：「XX的时间到啦，你可以的，冲！」
   - 场景联想型：「下午茶时间？不，是XX时间！加油」
   - 时间感知型：「都这个点了，XX该安排上了」
   - 任务关联型：「做完XX，今天还剩Y件事，继续加油！」
   - 或者任何你想得到的创意方式
3. 根据任务内容智能调整语气：
   - 工作/会议 → 稍正式但不死板
   - 生活/购物 → 轻松活泼
   - 重要/紧急 → 语气稍强但不焦虑
   - 日常小事 → 随意亲切
4. 利用上下文：
   - 早上可以说「新的一天从XX开始」
   - 晚上可以说「别忘了一天最后一件XX」
   - 如果今天任务多，可以说「还有X件事，XX先做吧」
   - 如果今天很清闲，可以说「今天就这一件事，轻松搞定」
5. 语音版要口语化、自然，像朋友在跟你说话（2-3句话）
6. 可以偶尔加一些小幽默、小鼓励、或者跟任务相关的小建议

返回JSON格式：
{
  "speech": "语音播报文本（口语化，自然，2-3句）"
}

只返回JSON，不要其他内容。"""


async def _generate_reminder_message(content: str, priority: str) -> dict:
    """用AI生成自然、多样的提醒消息——带完整上下文"""
    now = datetime.now()
    priority_desc = {"high": "重要/紧急", "medium": "普通", "low": "不太紧急"}.get(priority, "普通")
    
    # 获取用户今天的其他待办任务，给AI更多上下文
    pending_tasks = task_manager.list_tasks(status="pending", limit=10)
    other_tasks = [t for t in pending_tasks if t["content"] != content]
    task_summary = ""
    if other_tasks:
        task_lines = [f"  - {t['content']}（{t.get('trigger_time', '无时间')}）" for t in other_tasks[:5]]
        task_summary = f"\n用户今天其他待办：\n" + "\n".join(task_lines)
    else:
        task_summary = "\n用户今天没有其他待办任务了。"
    
    # 时间感知
    hour = now.hour
    if 5 <= hour < 9:
        time_desc = "早上"
    elif 9 <= hour < 12:
        time_desc = "上午"
    elif 12 <= hour < 14:
        time_desc = "中午"
    elif 14 <= hour < 18:
        time_desc = "下午"
    elif 18 <= hour < 21:
        time_desc = "晚上"
    else:
        time_desc = "深夜"
    
    user_msg = (
        f'当前时间：{now.strftime("%Y年%m月%d日 %H:%M")}（{time_desc}）\n'
        f'到期任务："{content}"，优先级：{priority_desc}\n'
        f'{task_summary}\n'
        f'请生成提醒消息。'
    )
    
    result = await call_ai(
        [{"role": "user", "content": user_msg}],
        system_prompt=REMINDER_PROMPT,
        temperature=0.85  # 更高温度 = 更有创意
    )
    
    if result["error"] or not result["content"]:
        # AI失败时用备用模板（随机选，不重复）
        import random
        fallbacks = [
            f"嘿，{content}的时间到啦，快去行动吧！",
            f"提醒你一下，{content}该做啦，加油！",
            f"时间不早啦，{content}该安排上了！",
            f"叮咚！{content}来敲门了，快去迎接吧！",
            f"别偷懒啦，{content}等着你呢！",
        ]
        return {"speech": random.choice(fallbacks)}
    
    # 解析AI返回的JSON
    from .ai import _extract_json
    parsed = _extract_json(result["content"])
    
    if parsed and "speech" in parsed:
        return parsed
    
    # JSON解析失败，用AI原始文本
    text = result["content"].strip()
    return {"speech": text}


async def reminder_callback(task_id: int):
    """提醒触发时调用——AI生成消息 + 本地语音播报（App 轮询 reminder_sent 感知提醒）"""
    task = task_manager.get_task(task_id)
    if not task or task["status"] != "pending":
        return
    
    content = task["content"]
    priority = task["priority"]
    task_type = task.get("task_type", "normal")
    
    # 智能任务类型：news / travel / schedule 走专门的执行逻辑
    if task_type == "news":
        await _execute_news_job(task)
        return
    if task_type == "travel":
        await _execute_travel_reminder(task)
        return
    if task_type == "schedule":
        await _execute_schedule_reminder(task)
        return
    
    # 普通任务：用AI生成自然、多样的提醒消息
    try:
        messages = await _generate_reminder_message(content, priority)
        speech = messages["speech"]
    except Exception as e:
        print(f"[提醒] AI生成消息失败，使用备用：{e}")
        speech = f"嘿，{content}的时间到啦，快去行动吧！"
    
    print(f"[提醒] 语音：{speech}")

    # 本地语音播报（Mac mini 扬声器）
    try:
        await speak(speech, rate="+0%")
    except Exception as e:
        print(f"[提醒] 语音播报出错：{e}")

    # 标记已提醒（App 通过轮询 reminder_sent 感知提醒）
    task_manager.mark_reminded(task_id)
    
    # 循环任务：安排下一次
    if task["is_recurring"]:
        schedule_recurring(task_id, task["is_recurring"], task["content"], task["priority"])


def schedule_recurring(task_id: int, recurring: str, content: str, priority: str):
    """安排循环任务的下一次"""
    recurring_lower = recurring.lower() if recurring else ""
    
    if recurring_lower in ("每天", "daily"):
        trigger = CronTrigger(hour=9, minute=0)
    elif recurring_lower in ("每周一", "every monday"):
        trigger = CronTrigger(day_of_week='mon', hour=9, minute=0)
    elif recurring_lower in ("每周二", "every tuesday"):
        trigger = CronTrigger(day_of_week='tue', hour=9, minute=0)
    elif recurring_lower in ("每周三", "every wednesday"):
        trigger = CronTrigger(day_of_week='wed', hour=9, minute=0)
    elif recurring_lower in ("每周四", "every thursday"):
        trigger = CronTrigger(day_of_week='thu', hour=9, minute=0)
    elif recurring_lower in ("每周五", "every friday"):
        trigger = CronTrigger(day_of_week='fri', hour=9, minute=0)
    elif recurring_lower in ("每周六", "every saturday"):
        trigger = CronTrigger(day_of_week='sat', hour=9, minute=0)
    elif recurring_lower in ("每周日", "every sunday"):
        trigger = CronTrigger(day_of_week='sun', hour=9, minute=0)
    elif "工作日" in recurring_lower or "weekday" in recurring_lower:
        trigger = CronTrigger(day_of_week='mon-fri', hour=9, minute=0)
    else:
        print(f"[调度器] 未知循环模式：{recurring}")
        return
    
    new_task = task_manager.add_task(
        content=content,
        priority=priority,
        is_recurring=recurring
    )
    
    if new_task and new_task.get("trigger_time"):
        schedule_task(new_task["task_id"], new_task["trigger_time"])


def schedule_task(task_id: int, trigger_time: str):
    """安排任务提醒"""
    try:
        dt = datetime.strptime(trigger_time, "%Y-%m-%d %H:%M")
        
        if dt <= datetime.now():
            print(f"[调度器] 任务 {task_id} 的时间已过，跳过")
            return
        
        scheduler.add_job(
            reminder_callback,
            trigger=DateTrigger(run_date=dt),
            args=[task_id],
            id=f"task_{task_id}",
            replace_existing=True
        )
        print(f"[调度器] 已安排任务 {task_id}，提醒时间：{trigger_time}")
    except ValueError as e:
        print(f"[调度器] 任务 {task_id} 时间格式无效：{e}")


def load_existing_tasks():
    """启动时加载并安排所有待办任务"""
    tasks = task_manager.list_tasks(status="pending")
    now = datetime.now()
    
    for task in tasks:
        if task["trigger_time"]:
            try:
                dt = datetime.strptime(task["trigger_time"], "%Y-%m-%d %H:%M")
                if dt > now and not task["reminder_sent"]:
                    schedule_task(task["task_id"], task["trigger_time"])
                elif dt <= now and not task["reminder_sent"]:
                    print(f"[调度器] 任务 {task['task_id']} 已过期，立即触发")
                    scheduler.add_job(
                        reminder_callback,
                        args=[task["task_id"]],
                        id=f"task_{task['task_id']}_overdue"
                    )
            except ValueError:
                print(f"[调度器] 任务 {task['task_id']} 时间格式无效：{task['trigger_time']}")
        # 每日循环的智能任务（news/schedule）：重启后重新武装明天的触发
        elif task.get("task_type") in ("news", "schedule") and task.get("is_recurring"):
            meta = task.get("meta_data") or {}
            hour = meta.get("daily_hour") or _parse_remind_hour(meta.get("remind_time"))
            # 若今天还没触发且时间未过，补一个今天的
            # 直接武装明天的
            try:
                from datetime import timedelta
                tomorrow = (now + timedelta(days=1)).replace(hour=hour, minute=0, second=0, microsecond=0)
                scheduler.add_job(
                    reminder_callback,
                    trigger=DateTrigger(run_date=tomorrow),
                    args=[task["task_id"]],
                    id=f"task_{task['task_id']}",
                    replace_existing=True
                )
                print(f"[调度器] 已重装备智能任务 {task['content']} 明天 {hour:02d}:00")
            except Exception as e:
                print(f"[调度器] 重装备智能任务出错：{e}")


def start_scheduler():
    """启动调度器并加载已有任务"""
    load_existing_tasks()
    scheduler.start()
    print("[调度器] 已启动")


def stop_scheduler():
    """停止调度器"""
    scheduler.shutdown()
    print("[调度器] 已停止")

# ============ SMART TASK EXECUTION ============

NEWS_PROMPT = """你是OpenMemo，现在你需要为用户提供最新的{topic}新闻摘要。
今天是{date}，请搜索并汇总近期的{topic}类重要新闻。

## 要求
1. 挑选3-5条最重要的新闻，每条1-2句话
2. 每条的格式：📰 标题
3. 保持客观、简洁
4. 如果{topic}是"天气"，只给天气情况，不要新闻
5. 结尾可以加一句小评论或建议

直接输出新闻内容，不要JSON格式。"""

SCHEDULE_REMIND_PROMPT = """你是OpenMemo，现在需要提醒用户今天该完成的任务。
用户有一个"{content}"日程表，今天需要完成以下任务：
{today_tasks}

## 要求
1. 用鼓励的语气提醒
2. 如果有多项，鼓励用户按顺序完成
3. 2-3句语音版本，自然口语化
4. 直接输出提醒内容，不要JSON格式。"""


async def _fetch_news(topic: str, max_retries: int = 1) -> str:
    """通过 Tavily 搜索实时新闻（topic: news），失败则降级由 AI 生成。"""
    try:
        import httpx
        from .config import TAVILY_API_KEY, TAVILY_BASE_URL
        if not TAVILY_API_KEY:
            return "（无新闻源，AI生成内容）"
        # 把用户topic映射成更自然的搜索关键词
        query_map = {
            "科技": "科技 新闻",
            "体育": "体育 新闻",
            "财经": "财经 新闻",
            "国际": "国际 新闻",
            "天气": "天气 预报",
        }
        query = query_map.get(topic, f"{topic} 新闻")
        payload = {
            "api_key": TAVILY_API_KEY,
            "query": query,
            "topic": "news",
            "search_depth": "basic",
            "max_results": 6,
            "include_answer": True,
        }
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(f"{TAVILY_BASE_URL}/search", json=payload)
            if resp.status_code == 200:
                data = resp.json()
                answer = data.get("answer", "") or ""
                items = []
                for r in data.get("results", [])[:5]:
                    title = r.get("title", "")
                    content = r.get("content", "")
                    date = r.get("published_date", "")
                    line = title
                    if date:
                        line += f"（{date[:10]}）"
                    if content:
                        line += f"：{content[:120]}"
                    items.append(line)
                combined = (answer + "\n\n" + "\n".join(items)) if items else answer
                if combined.strip():
                    return combined[:1500]
                return "（Tavily无结果，AI生成内容）"
            else:
                print(f"[新闻] Tavily 返回 {resp.status_code}")
                return "（无外部新闻源，AI生成内容）"
    except Exception as e:
        print(f"[新闻] Tavily 获取失败：{e}，使用AI生成")

    # 降级：由AI生成模拟内容
    return "（无外部新闻源，AI生成内容）"


async def _execute_news_job(task: dict):
    """执行新闻推送任务。"""
    content = task["content"]
    meta = task.get("meta_data") or {}
    topic = meta.get("topic", "综合")
    daily_hour = meta.get("daily_hour", 9)

    print(f"[新闻] 执行新闻推送：{topic}")

    # 获取新闻
    news_text = await _fetch_news(topic)

    # 用AI生成新闻摘要
    from datetime import datetime
    prompt = NEWS_PROMPT.format(
        topic=topic,
        date=datetime.now().strftime("%Y-%m-%d %H:%M")
    )
    if news_text and news_text != "（无外部新闻源，AI生成内容）":
        user_msg = f"今天的{topic}新闻。\n\n参考资料：{news_text[:1000]}"
    else:
        user_msg = f"今天是{datetime.now().strftime('%m月%d日')}，请给我播报今天的{topic}新闻/资讯。"

    result = await call_ai(
        [{"role": "user", "content": user_msg}],
        system_prompt=prompt,
        temperature=0.7
    )

    news_summary = result["content"] if not result["error"] and result["content"] else (
        f"今天{datetime.now().strftime('%m月%d日')}的{topic}资讯：暂无最新消息。"
    )

    # 语音播报
    try:
        await speak(news_summary, rate="+0%")
    except Exception as e:
        print(f"[新闻] 语音播报出错：{e}")

    # 语音播报
    try:
        await speak(news_summary, rate="+0%")
    except Exception as e:
        print(f"[新闻] 语音播报出错：{e}")

    # 循环任务：安排明天同一时间继续
    await _schedule_next_daily_task(task, daily_hour)


async def _execute_travel_reminder(task: dict):
    """执行出行提醒——提醒用户出发。"""
    content = task["content"]
    meta = task.get("meta_data") or {}
    # 优先念 AI 亲笔写的提醒原文
    remind_text = meta.get("reminder_text")
    if remind_text:
        speech = remind_text
    else:
        event_time = meta.get("event_time", "未知时间")
        commute_minutes = meta.get("commute_minutes", 60)
        flight_type = meta.get("flight_type", "domestic")
        ftype_desc = "国内" if flight_type == "domestic" else "国际"
        speech = f"叮咚！该出发了！你的{ftype_desc}出行{content}，{event_time}的时间，路上要{commute_minutes}分钟，现在出发刚刚好，别迟到哦！"

    print(f"[出行] 提醒出发：{content}")

    try:
        await speak(speech, rate="+5%")
    except Exception as e:
        print(f"[出行] 语音播报出错：{e}")
    task_manager.mark_reminded(task["task_id"])


async def _execute_schedule_reminder(task: dict):
    """执行日程表提醒——提醒今天该做的作业/任务。"""
    content = task["content"]
    meta = task.get("meta_data") or {}
    schedule = meta.get("schedule", [])

    if not schedule:
        # 如果后端没生成 schedule 数组，但 AI 给了 reminder_text（新架构：AI 全权负责内容），
        # 直接念 AI 写好的提醒原文。
        remind_text = meta.get("reminder_text")
        if remind_text:
            print(f"[日程] 执行AI原文提醒：{content}")
            try:
                await speak(remind_text, rate="+0%")
            except Exception as e:
                print(f"[日程] 语音播报出错：{e}")
            task_manager.mark_reminded(task["task_id"])
            remind_hour = _parse_remind_hour(meta.get("remind_time"))
            await _schedule_next_daily_task(task, remind_hour)
            return
        print(f"[日程] 任务 {task['task_id']} 没有日程数据")
        return

    # 找到今天的安排
    today_str = datetime.now().strftime("%Y-%m-%d")
    today_items = []
    for day in schedule:
        if day.get("date") == today_str:
            today_items = day.get("items", [])
            break

    if not today_items:
        # 今天没安排，跳过去
        task_manager.mark_reminded(task["task_id"])
        return

    # 用AI生成友好的提醒
    deadline = meta.get("deadline", "未知")
    tasks_str = "\n".join([f"  {i+1}. {item}" for i, item in enumerate(today_items)])

    prompt = SCHEDULE_REMIND_PROMPT.format(
        content=content,
        today_tasks=tasks_str,
        deadline=deadline
    )

    result = await call_ai(
        [{"role": "user", "content": f"今天是{today_str}，提醒我完成今日任务。"}],
        system_prompt=prompt,
        temperature=0.8
    )

    reminder_text = result["content"] if not result["error"] and result["content"] else (
        f"今天的任务来啦：\n{tasks_str}"
    )

    # 语音
    try:
        await speak(reminder_text, rate="+0%")
    except Exception as e:
        print(f"[日程] 语音播报出错：{e}")

    # 安排明天继续
    remind_hour = _parse_remind_hour(meta.get("remind_time"))
    await _schedule_next_daily_task(task, remind_hour)


def _parse_remind_hour(remind_time: str) -> int:
    """从'remind_time'解析小时（如 '11:00' -> 11, '早上8点' -> 8）。"""
    if not remind_time:
        return 9
    try:
        return int(re.search(r'(\d{1,2})', remind_time).group(1))
    except Exception:
        return 9


async def _schedule_next_daily_task(task: dict, hour: int):
    """为每日循环的智能任务（news/schedule）安排明天的触达。
    复用同一 task_id，通过恢复 pending 状态 + DateTrigger 在明天 hour 点触发。
    """
    from datetime import datetime, timedelta
    try:
        # 取消旧 job（如果有）
        try:
            scheduler.remove_job(f"task_{task['task_id']}")
        except Exception:
            pass
        # 重置提醒状态，保证明天还能触发（status保持pending即可）
        task_manager.mark_reminded(task["task_id"])
        tomorrow = (datetime.now() + timedelta(days=1)).replace(hour=hour, minute=0, second=0, microsecond=0)
        scheduler.add_job(
            reminder_callback,
            trigger=DateTrigger(run_date=tomorrow),
            args=[task["task_id"]],
            id=f"task_{task['task_id']}",
            replace_existing=True
        )
        print(f"[调度器] 已安排 {task['content']} 明天 {hour:02d}:00 继续")
    except Exception as e:
        print(f"[调度器] 安排次日任务出错：{e}")


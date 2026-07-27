"""Scheduler module - APScheduler for task reminders"""
import asyncio
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.cron import CronTrigger
from .tasks import TaskManager
from .voice import speak
from .feishu import feishu_bot
from .ai import call_ai


scheduler = AsyncIOScheduler()
task_manager = TaskManager()

# Default Feishu user（单用户模式）
from .config import FEISHU_DEFAULT_USER
DEFAULT_FEISHU_USER = FEISHU_DEFAULT_USER or "ou_ec77a32e32b880f53607efa4944cfb24"

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
6. 飞书版简洁带emoji（1-2句话）
7. 可以偶尔加一些小幽默、小鼓励、或者跟任务相关的小建议

返回JSON格式：
{
  "speech": "语音播报文本（口语化，自然，2-3句）",
  "feishu": "飞书消息文本（带emoji，简洁，1-2句）"
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
            {"speech": f"嘿，{content}的时间到啦，快去行动吧！", "feishu": f"⏰ {content}的时间到了～"},
            {"speech": f"提醒你一下，{content}该做啦，加油！", "feishu": f"💡 别忘了：{content}"},
            {"speech": f"时间不早啦，{content}该安排上了！", "feishu": f"🔔 该做{content}啦"},
            {"speech": f"叮咚！{content}来敲门了，快去迎接吧！", "feishu": f"🎯 {content}，该行动了！"},
            {"speech": f"别偷懒啦，{content}等着你呢！", "feishu": f"⚡ {content}，冲！"},
        ]
        return random.choice(fallbacks)
    
    # 解析AI返回的JSON
    from .ai import _extract_json
    parsed = _extract_json(result["content"])
    
    if parsed and "speech" in parsed and "feishu" in parsed:
        return parsed
    
    # JSON解析失败，用AI原始文本
    text = result["content"].strip()
    return {"speech": text, "feishu": f"⏰ {content}"}


async def reminder_callback(task_id: int):
    """提醒触发时调用——AI生成消息 + 本地语音播报 + 飞书消息推送"""
    task = task_manager.get_task(task_id)
    if not task or task["status"] != "pending":
        return
    
    content = task["content"]
    priority = task["priority"]
    
    # 用AI生成自然、多样的提醒消息
    try:
        messages = await _generate_reminder_message(content, priority)
        speech = messages["speech"]
        feishu_msg = messages["feishu"]
    except Exception as e:
        print(f"[提醒] AI生成消息失败，使用备用：{e}")
        speech = f"嘿，{content}的时间到啦，快去行动吧！"
        feishu_msg = f"⏰ {content}的时间到了～"
    
    print(f"[提醒] 语音：{speech}")
    print(f"[提醒] 飞书：{feishu_msg}")

    # 1. 本地语音播报（Mac mini 扬声器）
    try:
        await speak(speech, rate="+0%")
    except Exception as e:
        print(f"[提醒] 语音播报出错：{e}")

    # 2. 飞书消息推送
    try:
        user_open_id = _get_user_open_id(task_id)
        if user_open_id:
            success = await feishu_bot.send_message(user_open_id, feishu_msg)
            if success:
                print(f"[提醒] 飞书消息已发送给 {user_open_id}")
            else:
                print(f"[提醒] 飞书消息发送失败")
        else:
            print(f"[提醒] 未找到用户open_id，跳过飞书通知")
    except Exception as e:
        print(f"[提醒] 飞书推送出错：{e}")
    
    # 标记已提醒
    task_manager.mark_reminded(task_id)
    
    # 循环任务：安排下一次
    if task["is_recurring"]:
        schedule_recurring(task_id, task["is_recurring"], task["content"], task["priority"])


def _get_user_open_id(task_id: int) -> str:
    """从对话历史中找到用户的open_id"""
    import sqlite3
    from .config import DB_PATH
    
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT session_id FROM conversations 
            WHERE intent = 'TASK_CREATED' AND slots LIKE ?
            ORDER BY conv_id DESC LIMIT 1
        """, (f'%task_id":{task_id}%',))
        
        row = cursor.fetchone()
        if row and row["session_id"] != "default_user":
            conn.close()
            return row["session_id"]
        
        cursor.execute("""
            SELECT DISTINCT session_id FROM conversations 
            WHERE session_id != 'default_user' AND session_id LIKE 'ou_%'
            ORDER BY conv_id DESC LIMIT 1
        """)
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return row["session_id"]
    except Exception as e:
        print(f"[提醒] 查找用户出错：{e}")
    
    return DEFAULT_FEISHU_USER


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


def start_scheduler():
    """启动调度器并加载已有任务"""
    load_existing_tasks()
    scheduler.start()
    print("[调度器] 已启动")


def stop_scheduler():
    """停止调度器"""
    scheduler.shutdown()
    print("[调度器] 已停止")

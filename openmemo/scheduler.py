"""Scheduler module - APScheduler for task reminders"""
import asyncio
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.cron import CronTrigger
from .tasks import TaskManager
from .voice import speak


scheduler = AsyncIOScheduler()
task_manager = TaskManager()


async def reminder_callback(task_id: int):
    """Called when a task reminder fires"""
    task = task_manager.get_task(task_id)
    if not task or task["status"] != "pending":
        return
    
    # Generate speech reminder
    content = task["content"]
    priority = task["priority"]
    
    if priority == "high":
        prefix = "重要提醒！"
    elif priority == "low":
        prefix = "提醒："
    else:
        prefix = "提醒："
    
    message = f"{prefix}{content}"
    
    print(f"[Reminder] {message}")
    
    # Speak the reminder
    await speak(message)
    
    # Mark as reminded
    task_manager.mark_reminded(task_id)
    
    # For recurring tasks, schedule next occurrence
    if task["is_recurring"]:
        schedule_recurring(task_id, task["is_recurring"], task["content"], task["priority"])


def schedule_recurring(task_id: int, recurring: str, content: str, priority: str):
    """Schedule the next occurrence of a recurring task"""
    if recurring == "每天":
        trigger = CronTrigger(hour=9, minute=0)  # Default 9am daily
    elif recurring == "每周一":
        trigger = CronTrigger(day_of_week='mon', hour=9, minute=0)
    elif recurring == "每周五":
        trigger = CronTrigger(day_of_week='fri', hour=9, minute=0)
    else:
        return  # Unknown recurring pattern
    
    # Create a new task for next occurrence
    new_task = task_manager.add_task(
        content=content,
        priority=priority,
        is_recurring=recurring
    )
    
    # Schedule the new task
    if new_task and new_task.get("trigger_time"):
        schedule_task(new_task["task_id"], new_task["trigger_time"])


def schedule_task(task_id: int, trigger_time: str):
    """Schedule a reminder for a task at the given time"""
    try:
        # Parse the trigger time
        dt = datetime.strptime(trigger_time, "%Y-%m-%d %H:%M")
        
        # Don't schedule if time is in the past
        if dt <= datetime.now():
            print(f"[Scheduler] Task {task_id} trigger time is in the past, skipping")
            return
        
        scheduler.add_job(
            reminder_callback,
            trigger=DateTrigger(run_date=dt),
            args=[task_id],
            id=f"task_{task_id}",
            replace_existing=True
        )
        print(f"[Scheduler] Scheduled task {task_id} for {trigger_time}")
    except ValueError as e:
        print(f"[Scheduler] Invalid time format for task {task_id}: {e}")


def load_existing_tasks():
    """Load and schedule all pending tasks from database on startup"""
    tasks = task_manager.list_tasks(status="pending")
    now = datetime.now()
    
    for task in tasks:
        if task["trigger_time"]:
            try:
                dt = datetime.strptime(task["trigger_time"], "%Y-%m-%d %H:%M")
                if dt > now and not task["reminder_sent"]:
                    schedule_task(task["task_id"], task["trigger_time"])
                elif dt <= now and not task["reminder_sent"]:
                    # Task is overdue, trigger immediately
                    print(f"[Scheduler] Task {task['task_id']} is overdue, triggering")
                    scheduler.add_job(
                        reminder_callback,
                        args=[task["task_id"]],
                        id=f"task_{task['task_id']}_overdue"
                    )
            except ValueError:
                print(f"[Scheduler] Invalid time for task {task['task_id']}: {task['trigger_time']}")


def start_scheduler():
    """Start the scheduler and load existing tasks"""
    load_existing_tasks()
    scheduler.start()
    print("[Scheduler] Started")


def stop_scheduler():
    """Stop the scheduler"""
    scheduler.shutdown()
    print("[Scheduler] Stopped")

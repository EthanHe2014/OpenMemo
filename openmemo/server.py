"""OpenMemo FastAPI 服务 —— 主入口"""
import json
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from .config import SERVER_HOST, SERVER_PORT, AI_MODEL
from .conversation import process_message
from .tasks import TaskManager, ConversationManager
from .scheduler import start_scheduler, stop_scheduler
from .voice import speak


# Lifespan manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start scheduler on startup, stop on shutdown"""
    print("🚀 OpenMemo starting up...")
    start_scheduler()
    print()
    print("=" * 56)
    print("  ✅ OpenMemo 已启动！接下来这样用：")
    print("=" * 56)
    print(f"  1. 网页仪表盘（先在浏览器试一下）")
    print(f"     http://localhost:{SERVER_PORT}/")  
    print(f"  2. 直接对话（在仪表盘输入框里，或调用 API）")
    print(f"     例：'明天下午3点开会'  '每天上午11点提醒我写作业'")
    print(f"  3. 手机 App（真正的使用入口）")
    print(f"     git clone https://github.com/EthanHe2014/OpenMemoApp")
    print(f"     用 Xcode 跑起来，在 App 设置页把服务器地址改成你的地址")
    print(f"  4. 提醒会通过：Mac 语音 + macOS 通知 + 手机本地通知 送达")
    print("=" * 56)
    print()
    yield
    print("👋 OpenMemo shutting down...")
    stop_scheduler()


# Create FastAPI app
app = FastAPI(
    title="OpenMemo",
    description="AI-powered personal voice assistant with memory",
    version="0.1.0",
    lifespan=lifespan
)


@app.middleware("http")
async def no_cache_api(request: Request, call_next):
    """API 响应一律 no-store：App 轮询必须拿到最新数据，不能被 iOS URLCache 缓存。"""
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response

task_manager = TaskManager()
conv_manager = ConversationManager()


# ─── REST API ───────────────────────────────────────────────

@app.get("/")
async def root():
    """Serve the dashboard"""
    dashboard_path = Path(__file__).parent / "dashboard.html"
    return FileResponse(dashboard_path)


@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {
        "name": "OpenMemo",
        "version": "0.1.0",
        "status": "running",
        "model": AI_MODEL or ""
    }


@app.get("/api/tasks")
async def list_tasks(status: str = None, limit: int = 20):
    """List all tasks"""
    tasks = task_manager.list_tasks(status=status, limit=limit)
    return {"tasks": tasks, "count": len(tasks)}


@app.get("/api/reminders")
async def list_reminders(after_id: int = 0, limit: int = 20):
    """已触发的提醒记录（AI 生成的原文），App 轮询后显示横幅。"""
    reminders = task_manager.list_reminders(after_id=after_id, limit=limit)
    return {"reminders": reminders, "count": len(reminders)}


@app.get("/api/alerts")
async def list_alerts(after_id: int = 0, limit: int = 20):
    """看护告警（watchdog 发现的问题/自动处理），App 轮询后显示横幅。"""
    alerts = task_manager.list_alerts(after_id=after_id, limit=limit)
    return {"alerts": alerts, "count": len(alerts)}


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: int):
    """Get a specific task"""
    task = task_manager.get_task(task_id)
    if not task:
        return JSONResponse({"error": "Task not found"}, status_code=404)
    return {"task": task}


@app.post("/api/tasks")
async def create_task(request: Request):
    """Create a new task manually"""
    body = await request.json()
    content = body.get("content", "")
    if not content:
        return JSONResponse({"error": "Content is required"}, status_code=400)
    
    task = task_manager.add_task(
        content=content,
        trigger_time=body.get("trigger_time"),
        priority=body.get("priority", "medium"),
        is_recurring=body.get("is_recurring"),
        notes=body.get("notes"),
        duration_minutes=body.get("duration_minutes"),
        task_type=body.get("task_type", "normal"),
        meta_data=body.get("meta_data")
    )
    
    # Schedule if time is set
    if task.get("trigger_time"):
        from .scheduler import schedule_task
        schedule_task(task["task_id"], task["trigger_time"])
    
    return {"task": task, "success": True}


@app.patch("/api/tasks/{task_id}")
async def update_task(task_id: int, request: Request):
    """Update a task"""
    body = await request.json()
    task = task_manager.update_task(task_id, **body)
    if not task:
        return JSONResponse({"error": "Task not found"}, status_code=404)
    return {"task": task, "success": True}


@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: int):
    """Delete a task"""
    success = task_manager.delete_task(task_id)
    return {"success": success}


@app.post("/api/chat")
async def chat(request: Request):
    """Chat with OpenMemo（App 聊天入口）"""
    body = await request.json()
    message = body.get("message", "")
    session_id = body.get("session_id", "api_user")
    speak_response = body.get("speak", False)
    
    if not message:
        return JSONResponse({"error": "Message is required"}, status_code=400)
    
    reply = await process_message(session_id, message, speak_response=speak_response)
    return {"reply": reply, "success": True}


@app.post("/api/speak")
async def speak_text(request: Request):
    """Directly speak text (for testing)"""
    body = await request.json()
    text = body.get("text", "")
    if not text:
        return JSONResponse({"error": "Text is required"}, status_code=400)
    
    success = await speak(text)
    return {"success": success}


@app.get("/api/conversations/{session_id}")
async def get_conversations(session_id: str, limit: int = 20):
    """Get conversation history"""
    messages = conv_manager.get_history(session_id, limit)
    return {"messages": messages, "count": len(messages)}


@app.get("/api/sessions")
async def list_sessions():
    """List all chat sessions (most recent first) for the sidebar."""
    sessions = conv_manager.list_sessions()
    return {"sessions": sessions, "count": len(sessions)}


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a session and all its history."""
    conv_manager.delete_session(session_id)
    return {"success": True, "deleted": session_id}


# ─── Run Server ─────────────────────────────────────────────

def run_server():
    """Run the FastAPI server"""
    import uvicorn
    uvicorn.run(
        "openmemo.server:app",
        host=SERVER_HOST,
        port=SERVER_PORT,
        reload=False,
        log_level="info"
    )


if __name__ == "__main__":
    run_server()

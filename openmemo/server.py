"""OpenMemo FastAPI server - Main entry point"""
import json
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from .config import SERVER_HOST, SERVER_PORT
from .feishu import feishu_bot
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

# Deduplication: Track recently processed message IDs
_processed_messages = set()
_MAX_PROCESSED = 1000  # Keep last 1000 message IDs


task_manager = TaskManager()
conv_manager = ConversationManager()


# ─── Feishu Webhook ─────────────────────────────────────────

@app.post("/webhook/feishu")
async def feishu_webhook(request: Request):
    """Handle incoming Feishu bot events"""
    body = await request.json()
    
    # Verify the event
    if not feishu_bot.verify_event(body):
        return JSONResponse({"error": "Verification failed"}, status_code=403)
    
    # Handle URL verification challenge
    if body.get("type") == "url_verification":
        return feishu_bot.handle_challenge(body)
    
    # Handle message event - Feishu v2.0 schema puts event_type in header
    event = body.get("event", {})
    event_type = event.get("type", "")
    header = body.get("header", {})
    header_event_type = header.get("event_type", "")
    
    # Check both locations for event type
    matched_type = event_type or header_event_type
    
    if matched_type == "im.message.receive_v1":
        # Extract message
        msg_data = feishu_bot.extract_message(body)
        text = msg_data["text"]
        open_id = msg_data["open_id"]
        message_id = msg_data.get("message_id", "")
        is_bot = msg_data.get("is_bot", False)
        
        # CRITICAL: Skip messages from bots (including ourselves) to prevent infinite loops
        if is_bot:
            print(f"[Feishu] BOT MESSAGE SKIPPED")
            return {"status": "ok"}
        
        # DEDUPLICATION: Skip if we already processed this message
        if message_id:
            if message_id in _processed_messages:
                print(f"[Feishu] DUPLICATE SKIPPED: {message_id}")
                return {"status": "ok"}
            # Add to processed set BEFORE processing to prevent race conditions
            _processed_messages.add(message_id)
            # Keep it from growing too big
            if len(_processed_messages) > _MAX_PROCESSED:
                _processed_messages.pop()
        
        if not text:
            return {"status": "ok"}
        
        # IMPORTANT: Return 200 immediately so Feishu doesn't retry!
        # Process the message in background
        asyncio.create_task(_handle_feishu_message(open_id, text, message_id))
        
        return {"status": "ok"}
    
    return {"status": "ok"}


async def _handle_feishu_message(open_id: str, text: str, message_id: str):
    """Process a Feishu message in the background and send reply."""
    try:
        print(f"[Feishu] Message from {open_id}: {text}")
        
        # Process the message with a timeout so Feishu always gets a reply
        try:
            reply = await asyncio.wait_for(
                process_message(open_id, text, speak_response=False),
                timeout=25.0  # Max 25s for the whole AI pipeline
            )
        except asyncio.TimeoutError:
            print(f"[Feishu] AI processing timed out for {open_id}")
            reply = "AI 服务正在忙，请稍后再试或换个问题问我 🙏"
        
        # Send reply back via Feishu
        success = await feishu_bot.send_message(open_id, reply)
        if success:
            print(f"[Feishu] Reply sent to {open_id}: {reply[:50]}...")
        else:
            print(f"[Feishu] Failed to send reply to {open_id}")
    except Exception as e:
        print(f"[Feishu] Error handling message: {e}")
        # Last resort: try to notify the user
        try:
            await feishu_bot.send_message(open_id, "出错了，请稍后再试 🙏")
        except:
            pass


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
        "status": "running"
    }


@app.get("/api/tasks")
async def list_tasks(status: str = None, limit: int = 20):
    """List all tasks"""
    tasks = task_manager.list_tasks(status=status, limit=limit)
    return {"tasks": tasks, "count": len(tasks)}


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
    """Chat with OpenMemo (for testing without Feishu)"""
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

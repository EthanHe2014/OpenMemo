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
    
    # Handle message event
    event = body.get("event", {})
    event_type = event.get("type", "")
    
    if event_type == "im.message.receive_v1":
        # Extract message
        msg_data = feishu_bot.extract_message(body)
        text = msg_data["text"]
        open_id = msg_data["open_id"]
        
        if not text:
            return {"status": "ok"}
        
        print(f"[Feishu] Message from {open_id}: {text}")
        
        # Process the message through conversation pipeline
        # Don't speak for Feishu messages (user is on phone, not near Mac)
        reply = await process_message(open_id, text, speak_response=False)
        
        # Send reply back via Feishu
        await feishu_bot.send_message(open_id, reply)
        
        return {"status": "ok"}
    
    return {"status": "ok"}


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
        notes=body.get("notes")
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

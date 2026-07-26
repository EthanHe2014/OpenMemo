"""Task management with SQLite storage"""
import sqlite3
import json
from datetime import datetime
from typing import Optional, List
from .config import DB_PATH


def get_db() -> sqlite3.Connection:
    """Get a database connection with row factory"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize the database schema"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tasks (
        task_id INTEGER PRIMARY KEY AUTOINCREMENT,
        content TEXT NOT NULL,
        trigger_time TEXT,
        priority TEXT DEFAULT 'medium',
        status TEXT DEFAULT 'pending',
        is_recurring TEXT DEFAULT NULL,
        created_at TEXT DEFAULT (datetime('now', 'localtime')),
        updated_at TEXT DEFAULT (datetime('now', 'localtime')),
        reminder_sent INTEGER DEFAULT 0,
        notes TEXT DEFAULT NULL
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS conversations (
        conv_id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        intent TEXT DEFAULT NULL,
        slots TEXT DEFAULT NULL,
        created_at TEXT DEFAULT (datetime('now', 'localtime'))
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pending_slots (
        pending_id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        partial_slots TEXT NOT NULL,
        missing_slots TEXT NOT NULL,
        original_message TEXT,
        created_at TEXT DEFAULT (datetime('now', 'localtime'))
    )
    """)
    
    conn.commit()
    conn.close()
    print(f"Database initialized at {DB_PATH}")


class TaskManager:
    """Manages tasks in SQLite"""
    
    def __init__(self):
        init_db()
    
    def add_task(self, content: str, trigger_time: str = None, 
                 priority: str = "medium", is_recurring: str = None,
                 notes: str = None) -> dict:
        """Add a new task"""
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("""
        INSERT INTO tasks (content, trigger_time, priority, is_recurring, notes)
        VALUES (?, ?, ?, ?, ?)
        """, (content, trigger_time, priority, is_recurring, notes))
        
        task_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return self.get_task(task_id)
    
    def get_task(self, task_id: int) -> Optional[dict]:
        """Get a task by ID"""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return dict(row)
        return None
    
    def list_tasks(self, status: str = None, limit: int = 20) -> List[dict]:
        """List tasks, optionally filtered by status"""
        conn = get_db()
        cursor = conn.cursor()
        
        if status:
            cursor.execute(
                """SELECT * FROM tasks WHERE status = ? 
                   ORDER BY 
                     CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 ELSE 2 END,
                     trigger_time ASC LIMIT ?""",
                (status, limit)
            )
        else:
            cursor.execute(
                """SELECT * FROM tasks 
                   ORDER BY 
                     CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 ELSE 2 END,
                     trigger_time ASC LIMIT ?""",
                (limit,)
            )
        
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    def update_task(self, task_id: int, **kwargs) -> Optional[dict]:
        """Update a task's fields"""
        allowed_fields = ['content', 'trigger_time', 'priority', 'status', 
                         'is_recurring', 'notes', 'reminder_sent']
        
        updates = []
        values = []
        for field, value in kwargs.items():
            if field in allowed_fields:
                updates.append(f"{field} = ?")
                values.append(value)
        
        if not updates:
            return self.get_task(task_id)
        
        updates.append("updated_at = datetime('now', 'localtime')")
        values.append(task_id)
        
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE task_id = ?", values)
        conn.commit()
        conn.close()
        
        return self.get_task(task_id)
    
    def complete_task(self, task_id: int) -> Optional[dict]:
        """Mark a task as completed"""
        return self.update_task(task_id, status="completed")
    
    def cancel_task(self, task_id: int) -> Optional[dict]:
        """Cancel a task"""
        return self.update_task(task_id, status="cancelled")
    
    def delete_task(self, task_id: int) -> bool:
        """Delete a task"""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
        affected = cursor.rowcount
        conn.commit()
        conn.close()
        return affected > 0
    
    def get_pending_reminders(self) -> List[dict]:
        """Get tasks that need reminders (trigger_time <= now, not yet reminded)"""
        conn = get_db()
        cursor = conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        cursor.execute("""
            SELECT * FROM tasks 
            WHERE status = 'pending' 
            AND trigger_time <= ? 
            AND reminder_sent = 0
            ORDER BY priority DESC
        """, (now,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    def mark_reminded(self, task_id: int):
        """Mark a task as reminded"""
        self.update_task(task_id, reminder_sent=1)
    
    def get_overdue_tasks(self) -> List[dict]:
        """Get tasks that are past their trigger time and still pending"""
        conn = get_db()
        cursor = conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        cursor.execute("""
            SELECT * FROM tasks 
            WHERE status = 'pending' 
            AND trigger_time < ? 
            AND reminder_sent = 1
            ORDER BY priority DESC
        """, (now,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    def search_tasks(self, query: str) -> List[dict]:
        """Search tasks by content"""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM tasks WHERE content LIKE ? AND status != 'cancelled' ORDER BY trigger_time ASC",
            (f"%{query}%",)
        )
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]


class ConversationManager:
    """Manages conversation history and pending slot states"""
    
    def __init__(self):
        init_db()
    
    def add_message(self, session_id: str, role: str, content: str,
                    intent: str = None, slots: dict = None):
        """Add a message to conversation history"""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO conversations (session_id, role, content, intent, slots)
        VALUES (?, ?, ?, ?, ?)
        """, (session_id, role, content, intent, json.dumps(slots) if slots else None))
        conn.commit()
        conn.close()
    
    def get_history(self, session_id: str, limit: int = 10) -> list:
        """Get recent conversation history for a session"""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
        SELECT * FROM conversations 
        WHERE session_id = ? 
        ORDER BY conv_id ASC LIMIT ?
        """, (session_id, limit))
        rows = cursor.fetchall()
        conn.close()
        
        # Return in chronological order (already ASC by conv_id)
        messages = []
        for row in rows:
            msg = {"role": row["role"], "content": row["content"]}
            if row["intent"]:
                msg["intent"] = row["intent"]
            messages.append(msg)
        return messages
    
    def get_context_for_ai(self, session_id: str, limit: int = 6) -> list:
        """Get conversation context formatted for AI API"""
        history = self.get_history(session_id, limit)
        return [{"role": m["role"], "content": m["content"]} for m in history]
    
    def save_pending_slots(self, session_id: str, partial_slots: dict, 
                           missing_slots: list, original_message: str = None):
        """Save partially filled slots awaiting user completion"""
        # Remove any existing pending for this session
        self.clear_pending_slots(session_id)
        
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO pending_slots (session_id, partial_slots, missing_slots, original_message)
        VALUES (?, ?, ?, ?)
        """, (session_id, json.dumps(partial_slots), json.dumps(missing_slots), original_message))
        conn.commit()
        conn.close()
    
    def get_pending_slots(self, session_id: str) -> Optional[dict]:
        """Get pending slots for a session"""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
        SELECT * FROM pending_slots 
        WHERE session_id = ? 
        ORDER BY created_at DESC LIMIT 1
        """, (session_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                "partial_slots": json.loads(row["partial_slots"]),
                "missing_slots": json.loads(row["missing_slots"]),
                "original_message": row["original_message"]
            }
        return None
    
    def clear_pending_slots(self, session_id: str):
        """Clear pending slots for a session"""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM pending_slots WHERE session_id = ?", (session_id,))
        conn.commit()
        conn.close()

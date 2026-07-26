# OpenMemo MVP Flow

## Core Loop

```
User → Feishu message → Webhook → AI (glm-5.1) → Task/Reply → Edge TTS → Speaker
```

## Detailed Flow

### 1. Message Input
- User sends text or voice message via Feishu
- Feishu webhook delivers event to OpenMemo server
- Voice messages: Feishu provides built-in STT (speech-to-text)

### 2. Intent Analysis
- Text sent to glm-5.1 with intent recognition prompt
- AI classifies intent: ADD_TASK, QUERY_TASK, COMPLETE_TASK, CHAT
- For ADD_TASK: extracts slots (content, time, priority, recurring)

### 3. Slot Filling State Machine
- If all required slots present → create task
- If slots missing → save partial state, ask follow-up question
- User can cancel anytime with "算了", "取消" etc.
- Next message merges with saved partial slots

### 4. Task Management
- Tasks stored in SQLite with status tracking
- APScheduler sets reminders based on trigger_time
- At reminder time → Edge TTS generates audio → afplay on Mac mini speakers

### 5. Voice Output
- Edge TTS generates Chinese speech (zh-CN-XiaoxiaoNeural)
- Audio cached by text hash (avoid regenerating same text)
- Played via macOS `afplay` command

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | /webhook/feishu | Feishu bot webhook |
| GET | /api/tasks | List tasks |
| GET | /api/tasks/{id} | Get task |
| POST | /api/tasks | Create task |
| PATCH | /api/tasks/{id} | Update task |
| DELETE | /api/tasks/{id} | Delete task |
| POST | /api/chat | Chat with AI |
| POST | /api/speak | Speak text |
| GET | /api/conversations/{id} | Get conversation history |

## Data Model

### Tasks Table
| Field | Type | Description |
|-------|------|-------------|
| task_id | INTEGER PK | Auto-increment ID |
| content | TEXT | Task description |
| trigger_time | TEXT | When to remind (YYYY-MM-DD HH:MM) |
| priority | TEXT | high/medium/low |
| status | TEXT | pending/confirmed/completed/cancelled |
| is_recurring | TEXT | Recurring pattern (每天/每周一 etc.) |
| reminder_sent | INTEGER | Whether reminder was sent |
| notes | TEXT | Additional notes |

### Conversations Table
| Field | Type | Description |
|-------|------|-------------|
| conv_id | INTEGER PK | Auto-increment ID |
| session_id | TEXT | User session identifier |
| role | TEXT | user/assistant |
| content | TEXT | Message content |
| intent | TEXT | Detected intent |
| slots | TEXT | Extracted slots (JSON) |

### Pending Slots Table
| Field | Type | Description |
|-------|------|-------------|
| pending_id | INTEGER PK | Auto-increment ID |
| session_id | TEXT | User session |
| partial_slots | TEXT | Partially filled slots (JSON) |
| missing_slots | TEXT | List of missing slot names (JSON) |
| original_message | TEXT | Original user message |

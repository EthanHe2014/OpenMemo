# OpenMemo

AI-powered personal voice assistant with memory.

## Architecture

- **Input**: Feishu bot (text + voice messages with built-in STT)
- **AI**: glm-5.1 via custom endpoint (intent recognition, slot filling, conversation)
- **Output**: Mac mini speakers (Edge TTS → afplay)
- **Storage**: SQLite
- **Scheduler**: APScheduler for task reminders

## Core Loop

```
User → Feishu message → Webhook → AI (glm-5.1) → Task/Reply → Edge TTS → Speaker
```

1. User sends text/voice via Feishu
2. Mac mini receives webhook, Feishu provides STT for voice
3. AI identifies intent, extracts task info (time, content, priority)
4. If info missing → AI asks follow-up questions
5. Task stored in SQLite, scheduler sets reminders
6. At reminder time → Edge TTS generates audio → plays on Mac mini speakers

## MVP Scope

### Does:
- Feishu text/voice input
- AI intent recognition + slot filling
- Task CRUD with scheduling
- Follow-up questions when info is incomplete
- Voice broadcast on Mac mini speakers
- Basic conversation memory
- Single user mode

### Does NOT (V2):
- Multi-user support
- Handoff between devices
- Proactive news push
- Mobile app
- Interest decay algorithm
- Environment sensing

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Server | Python 3.14 + FastAPI |
| AI | glm-5.1 (custom endpoint) |
| STT | Feishu built-in |
| TTS | Edge TTS |
| Storage | SQLite |
| Scheduler | APScheduler |
| Input | Feishu Bot Webhook |
| Output | Mac mini speakers (afplay) |

## Setup

```bash
pip install fastapi uvicorn apscheduler edge-tts httpx
python -m openmemo.server
```

## Project Structure

```
OpenMemo/
├── README.md
├── requirements.txt
├── openmemo/
│   ├── __init__.py
│   ├── server.py          # FastAPI server + Feishu webhook
│   ├── ai.py              # glm-5.1 integration
│   ├── tasks.py           # Task management + SQLite
│   ├── scheduler.py       # APScheduler reminders
│   ├── voice.py           # Edge TTS + speaker output
│   ├── conversation.py    # Conversation state + memory
│   └── config.py          # Configuration
├── data/                  # SQLite DB + audio files
├── tests/
│   └── test_tasks.py
└── docs/
    └── mvp-flow.md
```

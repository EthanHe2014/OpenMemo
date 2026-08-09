"""AI 接入模块 —— 通过可配置的 OpenAI 兼容接口调用大模型"""
import asyncio
import json
import re
import httpx
from .config import AI_BASE_URL, AI_API_KEY, AI_MODEL

SYSTEM_PROMPT = """你是OpenMemo，一个智能个人任务助手。你运行在手机App里，帮用户管理任务和提醒。

## 关键规则 - 语言
你必须且只能用中文回复。即使用户用英文写消息，你也必须用中文回复。这是最重要的规则。

## 你的身份
- 你的名字叫OpenMemo。被问到名字时，始终介绍自己是OpenMemo。
- 你是一个聪明、友善、流畅的助手——像一个永远不会忘记事情、又很有分寸的朋友。
- 你能记住用户的待办任务、动态信息任务（如每日新闻）、出行事件（如赶飞机）、带日程表的任务集（如暑假作业）。

## 你的工作方式（非常重要）
你完全自由地引导对话：**没有任何外部程序替你做判断**——所有该问什么、怎么问、何时收拢信息、何时创建任务，都由你独立决定。你只需返回下面这个 JSON 结构（顺序按下方，task/appointment 在前，reply 在最后，这样即使输出被截断也优先保住任务字段）：

{
  "action": "task_added | task_listed | task_completed | reminder_set | chat | collecting",
  "task": {...},
  "appointment": {...},
  "reply": "你现在要对用户说的话（你所能想到的最自然、最平滑的中文）"
}

## 每个字段的含义
- **reply**：你此刻的回复。**必须是你自己写的自然语言**，用你想要的方式问问题、回应、确认。绝不套模板。
- **action**：这一轮你做了什么。
  - 信息还没收集完，想继续追问 → `collecting`
  - 信息齐了、创建了任务/提醒 → `task_added`（任务写进 task 字段）
  - 用户问任务 → `task_listed`
  - 用户说做完了 → `task_completed`
  - 只是普通到点提醒/闹钟，不建任务 → `reminder_set`（提醒写进 appointment）
  - 闲聊、回答无关问题 → `chat`
- **task.time**：你算好的确切提醒时间（当前日期时间会注入给你）。出行提醒就是出发提醒时间，每天推送就是每天几点，作业提醒就是每天提醒时间。
- **task.reminder_text**：重要！这是到点后要念给用户听的**原文**——你亲笔写的、具体又贴心的提醒。
- **appointment.content / at / read_aloud**：一次性到点提醒用这个，不需要存成任务。content 是提醒的简短内容（忠于用户原意，如'喝水'），at 是触发时间，read_aloud 是到点念的内容。二者与 task 择一填写即可；都不需要时填 null。

## 引导对话的准则
- **你决定问什么、怎么问。** 连续、自然地问，一次只推进一个关键点，别一次丢一堆问题。
- **顺着用户的话走。** 用户问无关问题或岔开话题时，先用一两句自然回应（可带人情味），再把话题拉回当前任务，但别生硬。
- **用户放弃/否定时，立刻放手。** 用户说'算了/不是/我没说/不告诉你了/换个话题'等，就大方收场（可带幽默），绝不固执追问。
- **绝不复读同一个问题。** 用户没正面回答时，换个问法，或先回应一下再继续。
- **信息够了就动手。** 只要关键信息（做什么、什么时间）齐了就创建任务/设提醒，不要反复确认。琐事（买瓶牛奶）不用追时间，直接记下。
- **承诺了就必须落地（极其重要）。** 一旦你在回复里向用户确认'我会在X点提醒你'或'已帮你安排好提醒'，那么**同一轮**你必须同时返回 `task_added`（或 `reminder_set`）+ 填好 task.time / appointment.at —— 绝不能只写话、不落地。
  - 用户一次想要**多个不同时间的提醒**（如'提前3小时提醒收拾行李 + 提前2小时出发'）：请把它们拆成**多条 task** 依次放进 `tasks` 数组字段（或至少把最重要的一个按时落地，并在 reply 里说明其余可选）。每个提醒都要有 content 和 time。
  - task 里**必须包含 content**（任务内容）。如果你漏写了 content，服务端就无法落地——请始终把用户要提醒的事写进 content，把到点要说的话写进 reminder_text。
  - 用户对某个提醒时间说'可以 / 行 / 好 / 就这个'，这就是**落地的信号**：本轮就创建提醒，不要再拖到下一轮。
  - 例：你提出6:30提醒，用户回'可以'，你既要在 reply 里确认，也必须在 task 里把触发时间设为 6:30（或 appointment.at=6:30），action 必须是 task_added/reminder_set，否则服务器不会真正创建提醒。
  - 检查：如果这条 reply 里提到了任何已敲定的提醒时间，那 task.time 或 appointment.at 必须等于这个时间，两者不能为空。
- **任务内容只认用户说的原意**，绝不擅自改名。用户说'赶飞机'就是赶飞机，说'开会'就是开会。
- **时间冲突和提醒策略你自己判断。** 比如赶飞机，你会想提前几小时提醒出发——算进 task.time 或 appointment.at，把临场话写进 reminder_text/read_aloud。

## 意图/场景举例（用来帮你理解，不是模板）
- 赶飞机/高铁：问几点出发、到站要多久、国内/国际；然后你决定提前多久提醒出发，把提醒时间算进 task.time 或 appointment.at，把临场提醒话写进 reminder_text/read_aloud。
- 每天新闻：问几点看、看什么类型 → task_type=news，recurring=每天，time=每天几点，reminder_text=到点后播新闻的引导语。
- 暑假作业：问有哪些作业、哪天写完、每天几点提醒 → task_type=schedule，recurring=每天。
- 普通任务（开会/打电话/买牛奶）：信息齐了就 task_added；琐事不必追问时间。
- 用户问'我有什么任务' → task_listed。
- 用户说'牛奶买好了' → task_completed。

## 处理已有任务的动作（task_listed / task_completed）
- task_listed：reply 里直接列出用户当前的任务即可（哪些内容、什么时候）。
- task_completed：reply 里确认完成哪个任务即可。

## 规则
1. 必须用中文回复，即使用户用英文写消息也要用中文回复。
2. reply 和 reminder_text 必须是你自然写出的话，**绝对不要套模板**。
3. 回复简短，任务确认最多1-2句。
4. 适度用 emoji（⏰提醒、✅完成、📝新任务、🔄循环、📰新闻、✈️出行、📅日程）。
5. 只返回一个合法的 JSON 对象（含上面所有字段，缺的填 null 或空对象），不要 markdown、不要代码块、不要额外文字。
6. 计算时间记得参考注入给你的当前时间。
7. 若本条消息不需要任何动作（纯聊天），task 填 null，appointment 填 null，action 填 chat 即可。"""




async def call_ai(messages: list, system_prompt: str = None, retries: int = 1,
                    temperature: float = None, max_tokens: int = None) -> dict:
    """Call the AI API and return the response.
    
    Uses STREAMING because some OpenAI-compatible endpoints only respond
    to stream=true requests (non-streaming may hang/timeout).
    
    Args:
        messages: Conversation messages
        system_prompt: System prompt (default: main SYSTEM_PROMPT)
        retries: Number of retries on failure
        temperature: Sampling temperature (default 0.3 for precision, use 0.8+ for creativity)
        max_tokens: Max response tokens (default 1500 — JSON 可能较长，勿设过小以免截断丢字段)
    """
    if not AI_API_KEY:
        return {"content": None, "error": "AI API key not configured"}
    
    if system_prompt is None:
        system_prompt = SYSTEM_PROMPT
    
    full_messages = [{"role": "system", "content": system_prompt}] + messages
    
    url = f"{AI_BASE_URL.rstrip('/')}/chat/completions"
    
    payload = {
        "model": AI_MODEL,
        "messages": full_messages,
        "temperature": temperature if temperature is not None else 0.3,
        "max_tokens": max_tokens or 1500,  # 足够大，避免 JSON 被截断导致任务/提醒丢失
        "stream": True  # CRITICAL: endpoint only works with streaming
    }
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {AI_API_KEY}"
    }
    
    last_error = None
    for attempt in range(retries + 1):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                content_parts = []
                async with client.stream("POST", url, json=payload, headers=headers) as response:
                    if response.status_code != 200:
                        body = (await response.aread()).decode(errors="ignore")
                        last_error = f"API error {response.status_code}: {body[:200]}"
                        if attempt < retries:
                            await asyncio.sleep(1)
                            continue
                        return {"content": None, "error": last_error}
                    
                    # Accumulate streaming deltas
                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        choices = chunk.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            piece = delta.get("content")
                            if piece:
                                content_parts.append(piece)
                
                content = "".join(content_parts).strip()
                if not content:
                    return {"content": None, "error": "Empty streaming response"}
                return {"content": content, "error": None}
        except httpx.HTTPStatusError as e:
            last_error = f"API error {e.response.status_code}: {e.response.text[:200]}"
        except httpx.ConnectError as e:
            last_error = f"Connection failed: {str(e)[:100]}"
        except Exception as e:
            last_error = f"Request failed: {str(e)[:100]}"
        
        if attempt < retries:
            await asyncio.sleep(1)
    
    return {"content": None, "error": last_error or "Unknown error"}


def _extract_json(content: str) -> dict | None:
    """Robustly extract JSON from AI response, handling various formats.

    Also attempts to repair JSON truncated by max_tokens: if the closing
    brace is missing, we try progressively appending closing braces/quotes
    so task/appointment fields (placed first) survive.
    """
    content = content.strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    json_match = re.search(r'```(?:json)?\s*(.*?)\s*```', content, re.DOTALL)
    if json_match:
        candidate = json_match.group(1).strip()
        parsed = _try_parse_or_repair(candidate)
        if parsed:
            return parsed

    brace_start = content.find('{')
    brace_end = content.rfind('}')
    if brace_start != -1:
        if brace_end > brace_start:
            parsed = _try_parse_or_repair(content[brace_start:brace_end + 1])
            if parsed:
                return parsed
        else:
            # no closing brace at all -> truncated; repair from '{' to end
            parsed = _try_parse_or_repair(content[brace_start:])
            if parsed:
                return parsed

    return None


def _try_parse_or_repair(text: str) -> dict | None:
    """Try json.loads, then attempt several truncation repairs."""
    for candidate in _repair_candidates(text):
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict) and obj:
                return obj
        except json.JSONDecodeError:
            continue
    return None


def _repair_candidates(text: str) -> list:
    """Yield increasingly aggressive repairs for a truncated JSON object."""
    yield text
    # 1) Missing closing brace(s)
    for n in range(1, 6):
        yield text + '}' * n
    # 2) Unclosed string at the very end -> close it then brace(s)
    for n in range(1, 6):
        yield text + '"' + '}' * n
    # 3) Trailing comma before closing
    stripped = text.rstrip()
    if stripped.endswith(','):
        for candidate in _repair_candidates(stripped[:-1]):
            yield candidate
    return


async def analyze_intent(user_message: str, conversation_context: list = None) -> dict:
    """Analyze user message for intent and extract slots.
    
    Injects current time and task context so the AI can be smarter
    (e.g., "3点" resolves to today vs tomorrow based on current time).
    """
    from datetime import datetime
    from .tasks import TaskManager
    
    # Build context-aware system prompt
    now = datetime.now()
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
    
    time_context = f"\n\n## 当前时间\n现在是 {now.strftime('%Y年%m月%d日 %H:%M')}（{time_desc}，星期{['一','二','三','四','五','六','日'][now.weekday()]}）。解析时间时请参考当前时间。"
    
    # Add task context
    try:
        tm = TaskManager()
        pending = tm.list_tasks(status="pending", limit=5)
        if pending:
            task_lines = [f"  - {t['content']}（{t.get('trigger_time', '无时间')}，{t['status']}）" for t in pending]
            task_context = f"\n\n## 用户当前待办任务\n" + "\n".join(task_lines)
        else:
            task_context = "\n\n## 用户当前待办任务\n（无待办任务）"
    except Exception:
        task_context = ""
    
    enhanced_prompt = SYSTEM_PROMPT + time_context + task_context
    
    messages = []
    
    if conversation_context:
        messages.extend(conversation_context[-6:])
    
    messages.append({"role": "user", "content": user_message})
    
    result = await call_ai(messages, enhanced_prompt)
    
    if result["error"]:
        return {
            "action": "chat",
            "reply": "抱歉，AI服务暂时不可用，请稍后再试。",
            "task": None,
            "appointment": None
        }

    parsed = _extract_json(result["content"])

    if parsed and "reply" in parsed:
        return {
            "action": parsed.get("action", "chat"),
            "reply": parsed.get("reply", ""),
            "task": parsed.get("task"),
            "tasks": parsed.get("tasks"),
            "appointment": parsed.get("appointment"),
        }

    return {
        "action": "chat",
        "reply": result["content"] if result["content"] else "我没太理解，能再说一遍吗？",
        "task": None,
        "appointment": None
    }

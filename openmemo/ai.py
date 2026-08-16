"""AI 接入模块 —— 通过可配置的 OpenAI 兼容接口调用大模型"""
import asyncio
import json
import re
import httpx
from .config import ai_base_url, ai_api_key, ai_model

from .prompts import SYSTEM_PROMPT




async def call_ai(messages: list, system_prompt: str = None, retries: int = 1,
                    temperature: float = None, max_tokens: int = None,
                    json_mode: bool = True) -> dict:
    """Call the AI API and return the response.

    Uses STREAMING because some OpenAI-compatible endpoints only respond
    to stream=true requests (non-streaming may hang/timeout).

    Args:
        messages: Conversation messages
        system_prompt: System prompt (default: main SYSTEM_PROMPT)
        retries: Number of retries on failure
        temperature: Sampling temperature (default 0.3 for precision, use 0.8+ for creativity)
        max_tokens: Max response tokens (default 1500 — JSON 可能较长，勿设过小以免截断丢字段)
        json_mode: 强制模型输出 JSON（response_format=json_object）。
           对话/任务解析用 True；纯文本生成（提醒文案/新闻等）用 False。
           若接口不支持该参数（返回 400），会自动去掉重试，不影响其它提供商。
    """
    # 运行时配置（settings.json 覆盖 .env，改模型/地址/密钥即时生效，无需重启）
    key = ai_api_key()
    base_url = ai_base_url()
    model = ai_model()
    if not key:
        return {"content": None, "error": "AI API key not configured"}
    if not base_url:
        return {"content": None, "error": "AI base URL not configured"}
    if not model:
        return {"content": None, "error": "AI model not configured"}

    if system_prompt is None:
        system_prompt = SYSTEM_PROMPT
    
    full_messages = [{"role": "system", "content": system_prompt}] + messages
    
    url = f"{base_url.rstrip('/')}/chat/completions"
    
    use_json_mode = json_mode
    # json 模式走非流式：部分接口（如 DeepSeek）stream + json_object 会返回空流；
    # 纯文本生成保持流式（原行为，兼容只支持流式的接口）。
    use_stream = not json_mode
    last_error = None
    # 尝试预算：常规重试 + json 空白响应重试 + 换流式重试
    max_attempts = retries + 4
    for attempt in range(max_attempts):
        payload = {
            "model": model,
            "messages": full_messages,
            "temperature": temperature if temperature is not None else 0.3,
            "max_tokens": max_tokens or 1500,  # 足够大，避免 JSON 被截断导致任务/提醒丢失
            "stream": use_stream
        }
        if use_json_mode:
            payload["response_format"] = {"type": "json_object"}
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}"
        }
        
        try:
            async with httpx.AsyncClient(timeout=60.0 if not use_stream else 10.0) as client:
                if use_stream:
                    content_parts = []
                    async with client.stream("POST", url, json=payload, headers=headers) as response:
                        if response.status_code == 400 and use_json_mode:
                            # 接口不支持 response_format → 去掉它并切回流式重试（兼容 Ollama 等）
                            body = (await response.aread()).decode(errors="ignore")
                            if "response_format" in body:
                                print("[ai] 接口不支持 json_object，自动降级为普通流式模式")
                                use_json_mode = False
                                use_stream = True
                                continue
                            last_error = f"API error 400: {body[:200]}"
                            if attempt < retries:
                                await asyncio.sleep(1)
                                continue
                            return {"content": None, "error": last_error}
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
                else:
                    response = await client.post(url, json=payload, headers=headers)
                    if response.status_code == 400 and use_json_mode:
                        body = response.text
                        if "response_format" in body:
                            print("[ai] 接口不支持 json_object，自动降级为普通流式模式")
                            use_json_mode = False
                            use_stream = True
                            continue
                        last_error = f"API error 400: {body[:200]}"
                        if attempt < retries:
                            await asyncio.sleep(1)
                            continue
                        return {"content": None, "error": last_error}
                    if response.status_code != 200:
                        last_error = f"API error {response.status_code}: {response.text[:200]}"
                        if attempt < retries:
                            await asyncio.sleep(1)
                            continue
                        return {"content": None, "error": last_error}
                    data = response.json()
                    choices = data.get("choices") or []
                    content = (choices[0].get("message", {}).get("content") or "").strip() if choices else ""
                
                if content:
                    return {"content": content, "error": None}
                
                # 空内容（DeepSeek json_object 偶发返回纯空白）→ 同模式重试；
                # 非流式重试耗尽后再换流式兜底一次。
                last_error = "Empty response"
                if not use_stream:
                    if attempt < max_attempts - 2:
                        await asyncio.sleep(1)
                        continue
                    use_stream = True
                    continue
                return {"content": None, "error": last_error}
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
        obj = json.loads(content)
        # 只接受 dict（AI 契约是对象）；list/其它类型不是合法回复
        return obj if isinstance(obj, dict) and obj else None
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
    # 4) 任意位置的多余尾逗号：把 ",}" 修成 "}"（含嵌套，如 {"a":{"b":1,},}）
    fixed = re.sub(r",\s*(?=[}\]])", "", text)
    if fixed != text:
        yield fixed
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
        print(f"[ai] call_ai error: {result['error']}")
        # L5：AI 健康监控 —— 连续失败阈值告警（不改变回复内容）
        try:
            from .monitor import note_ai_failure
            note_ai_failure(False)
        except Exception:
            pass
        return {
            "action": "chat",
            "reply": "抱歉，AI服务暂时不可用，请稍后再试。",
            "task": None,
            "appointment": None
        }
    try:
        from .monitor import note_ai_failure
        note_ai_failure(True)
    except Exception:
        pass

    parsed = _extract_json(result["content"])

    if parsed and isinstance(parsed, dict):
        has_mechanical = any(parsed.get(k) for k in ("task", "tasks", "appointment"))
        if "reply" in parsed or has_mechanical:
            return {
                "action": parsed.get("action", "chat"),
                "reply": parsed.get("reply") or ("好的，已记下。" if has_mechanical else ""),
                "task": parsed.get("task"),
                "tasks": parsed.get("tasks"),
                "appointment": parsed.get("appointment"),
                "search": parsed.get("search"),
            }

    return {
        "action": "chat",
        "reply": result["content"] if result["content"] else "我没太理解，能再说一遍吗？",
        "task": None,
        "appointment": None
    }

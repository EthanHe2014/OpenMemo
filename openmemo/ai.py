"""AI integration module - glm-5.1 via custom endpoint"""
import asyncio
import json
import httpx
from .config import AI_BASE_URL, AI_API_KEY, AI_MODEL

# System prompt for intent recognition and slot filling
INTENT_SYSTEM_PROMPT = """你是OpenMemo，一个智能任务助手。你的工作是分析用户消息的意图。

判断意图类型：
- ADD_TASK: 用户想添加任务/提醒/待办
- QUERY_TASK: 用户查询任务/问有什么事
- COMPLETE_TASK: 用户说完成了某事/取消了某事
- CHAT: 普通聊天/闲聊

如果是ADD_TASK，提取以下信息：
- content: 任务内容（必填，简短描述）
- time: 时间描述（如"明天下午3点"，"今晚8点"）
- priority: 优先级 high/medium/low（默认medium）
- recurring: 是否循环（如"每天"、"每周一"，无则为null）

如果content缺失，必须追问。如果time缺失，可以追问但不是必须的。

严格返回以下JSON格式，不要加任何其他文字：
{"intent":"ADD_TASK","slots":{"content":"开会","time":"明天下午3点","priority":"medium","recurring":null},"missing_slots":[],"reply":"好的，已添加任务：明天下午3点开会"}

示例2（缺少时间）：
{"intent":"ADD_TASK","slots":{"content":"买牛奶","time":null,"priority":"medium","recurring":null},"missing_slots":["time"],"reply":"好的，请问什么时候去买牛奶？"}

示例3（查询）：
{"intent":"QUERY_TASK","slots":{"content":null},"missing_slots":[],"reply":"你目前有3个待办任务..."}

示例4（完成）：
{"intent":"COMPLETE_TASK","slots":{"content":"买牛奶"},"missing_slots":[],"reply":"已完成：买牛奶 ✅"}

示例5（聊天）：
{"intent":"CHAT","slots":{},"missing_slots":[],"reply":"你好呀！有什么可以帮你的？"}

注意：只返回JSON，不要返回其他内容。"""

CHAT_SYSTEM_PROMPT = """你是OpenMemo，一个友好的个人AI助手。你可以帮助用户管理任务和提醒。
保持回复简洁自然，像朋友一样说话。如果用户只是聊天，轻松回应即可。"""


async def call_ai(messages: list, system_prompt: str = None, retries: int = 2) -> dict:
    """Call the AI API and return the response.
    
    Args:
        messages: List of message dicts with role and content
        system_prompt: Optional system prompt override
        retries: Number of retries on failure
    
    Returns:
        dict with 'content' (str) and 'error' (str|None)
    """
    if not AI_API_KEY:
        return {"content": None, "error": "AI API key not configured"}
    
    if system_prompt is None:
        system_prompt = CHAT_SYSTEM_PROMPT
    
    full_messages = [{"role": "system", "content": system_prompt}] + messages
    
    url = f"{AI_BASE_URL.rstrip('/')}/chat/completions"
    
    payload = {
        "model": AI_MODEL,
        "messages": full_messages,
        "temperature": 0.7,
        "max_tokens": 1000
    }
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {AI_API_KEY}"
    }
    
    last_error = None
    for attempt in range(retries + 1):
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, json=payload, headers=headers)
                
                if response.status_code != 200:
                    last_error = f"API error {response.status_code}: {response.text[:200]}"
                    if attempt < retries:
                        await asyncio.sleep(1)
                        continue
                    return {"content": None, "error": last_error}
                
                try:
                    result = response.json()
                except Exception as e:
                    last_error = f"Invalid API response: {str(e)[:100]}"
                    if attempt < retries:
                        await asyncio.sleep(1)
                        continue
                    return {"content": None, "error": last_error}
                
                if "choices" not in result:
                    return {"content": None, "error": f"Unexpected API response: {str(result)[:200]}"}
                
                content = result["choices"][0]["message"]["content"]
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


async def analyze_intent(user_message: str, conversation_context: list = None) -> dict:
    """Analyze user message for intent and extract slots.
    
    Args:
        user_message: The user's message text
        conversation_context: Previous messages in this conversation
    
    Returns:
        dict with intent, slots, missing_slots, reply, is_task
    """
    messages = []
    
    # Add conversation context if any
    if conversation_context:
        messages.extend(conversation_context[-6:])  # Last 3 exchanges
    
    messages.append({"role": "user", "content": user_message})
    
    result = await call_ai(messages, INTENT_SYSTEM_PROMPT)
    
    if result["error"]:
        return {
            "intent": "CHAT",
            "slots": {},
            "missing_slots": [],
            "reply": f"抱歉，AI服务暂时不可用：{result['error']}",
            "is_task": False
        }
    
    # Try to parse JSON from response
    content = result["content"].strip()
    parsed = None
    
    try:
        # Try direct JSON parse
        parsed = json.loads(content)
    except json.JSONDecodeError:
        # Try to extract JSON from markdown code block
        import re
        json_match = re.search(r'```(?:json)?\s*(.*?)\s*```', content, re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass
        
        # Try to find JSON object in text
        if not parsed:
            json_match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
            if json_match:
                try:
                    parsed = json.loads(json_match.group(0))
                except json.JSONDecodeError:
                    pass
        
        # Try nested braces (more complex JSON)
        if not parsed:
            brace_start = content.find('{')
            brace_end = content.rfind('}')
            if brace_start != -1 and brace_end > brace_start:
                try:
                    parsed = json.loads(content[brace_start:brace_end+1])
                except json.JSONDecodeError:
                    pass
    
    if parsed and "intent" in parsed:
        return {
            "intent": parsed.get("intent", "CHAT"),
            "slots": parsed.get("slots", {}),
            "missing_slots": parsed.get("missing_slots", []),
            "reply": parsed.get("reply", ""),
            "is_task": parsed.get("is_task", False)
        }
    
    # Fallback: treat as chat
    return {
        "intent": "CHAT",
        "slots": {},
        "missing_slots": [],
        "reply": content,
        "is_task": False
    }


async def chat_reply(user_message: str, conversation_context: list = None) -> str:
    """Simple chat reply without intent analysis.
    
    Args:
        user_message: The user's message
        conversation_context: Previous messages
    
    Returns:
        str: AI reply text
    """
    messages = []
    if conversation_context:
        messages.extend(conversation_context[-6:])
    messages.append({"role": "user", "content": user_message})
    
    result = await call_ai(messages, CHAT_SYSTEM_PROMPT)
    
    if result["error"]:
        return f"抱歉，出了点问题：{result['error']}"
    
    return result["content"]

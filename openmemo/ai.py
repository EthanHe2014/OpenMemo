"""AI integration module - glm-5.1 via custom endpoint"""
import asyncio
import json
import re
import httpx
from .config import AI_BASE_URL, AI_API_KEY, AI_MODEL

SYSTEM_PROMPT = """你是OpenMemo，一个智能个人任务助手。你运行在飞书里，帮助用户管理任务和提醒。

## 关键规则 - 语言
你必须且只能用中文回复。即使用户用英文写消息，你也必须用中文回复。这是最重要的规则，违反此规则是严重错误。

## 你的身份
- 你的名字叫OpenMemo。如果被问到名字，始终介绍自己是OpenMemo。
- 你是一个有帮助、简洁、友好的助手——像一个不会忘记事情的朋友。

## 你的能力
- 添加任务和提醒（带时间、优先级、循环）
- 查询和列出已有任务
- 标记任务为已完成
- 日常聊天

## 工作方式
当用户发送消息时，判断意图并回复。你必须返回以下JSON格式：

{
  "intent": "ADD_TASK | QUERY_TASK | COMPLETE_TASK | CHAT",
  "slots": { ... },
  "reply": "你的回复（必须用中文）"
}

### 意图：ADD_TASK
用户想创建任务、提醒或待办。
提取以下信息：
- content: 简短任务描述（必填——如果缺失必须追问）
- time: 提醒时间（如"明天下午3点"、"下周一9点"、"2小时后"）——可选，自然追问即可
- priority: "high"、"medium"或"low"（默认"medium"）
- recurring: 循环模式如"每天"、"每周一"、"工作日"（无则为null）

如果content缺失，必须追问。如果time缺失，直接创建任务不设提醒——不要反复追问。

示例：
用户："提醒我明天下午3点给妈妈打电话"
→ {"intent":"ADD_TASK","slots":{"content":"给妈妈打电话","time":"明天下午3点","priority":"medium","recurring":null},"reply":"好的！已添加提醒：明天下午3点给妈妈打电话 ⏰"}

用户："我需要买牛奶"
→ {"intent":"ADD_TASK","slots":{"content":"买牛奶","time":null,"priority":"medium","recurring":null},"reply":"任务已添加：买牛奶 📝"}

用户："每周一早上9点有站会"
→ {"intent":"ADD_TASK","slots":{"content":"站会","time":"每周一9点","priority":"medium","recurring":"每周一"},"reply":"循环任务已添加：每周一早上9点站会 🔄"}

用户："Remind me to call mom tomorrow at 3pm"（英文输入）
→ {"intent":"ADD_TASK","slots":{"content":"给妈妈打电话","time":"明天下午3点","priority":"medium","recurring":null},"reply":"好的！已添加提醒：明天下午3点给妈妈打电话 ⏰"}

### 意图：QUERY_TASK
用户询问任务、日程或待办事项。
slots: content（可选搜索关键词）

示例：
用户："我有什么任务？"
→ {"intent":"QUERY_TASK","slots":{"content":null},"reply":"你目前的待办任务：\\n1. ⏳ 给妈妈打电话（明天下午3点）\\n2. ⏳ 买牛奶"}

用户："有没有会议？"
→ {"intent":"QUERY_TASK","slots":{"content":"会议"},"reply":"没有找到包含"会议"的任务。"}

### 意图：COMPLETE_TASK
用户说完成了或取消了某个任务。
slots: content（哪个任务）

示例：
用户："牛奶买好了"
→ {"intent":"COMPLETE_TASK","slots":{"content":"买牛奶"},"reply":"已完成：买牛奶 ✅"}

用户："打完电话了"
→ {"intent":"COMPLETE_TASK","slots":{"content":"给妈妈打电话"},"reply":"已完成：给妈妈打电话 ✅"}

### 意图：CHAT
日常聊天，不属于以上任何意图。
slots: 空对象

聊天时要有个性！你可以：
- 开玩笑、卖萌、吐槽
- 根据当前时间打招呼（早上好、晚上好等）
- 聊到任务时主动建议
- 偶尔用网络流行语
- 像朋友一样自然对话

示例：
用户："你好"
→ {"intent":"CHAT","slots":{},"reply":"嘿！我是OpenMemo，你的任务小助手～有啥需要帮忙的？"}

用户："你叫什么名字？"
→ {"intent":"CHAT","slots":{},"reply":"我叫OpenMemo！帮你记事提醒的，不会忘事的那种朋友 😎"}

用户："谢谢"
→ {"intent":"CHAT","slots":{},"reply":"客气啥！随时找我～"}

用户："好无聊"
→ {"intent":"CHAT","slots":{},"reply":"无聊的话，要不要看看你还有啥待办？或者咱聊聊天也行～"}

## 规则
1. 必须用中文回复——即使用户用英文写消息也要用中文回复
2. 被问到名字时始终说自己是OpenMemo
3. 回复要简短——任务确认最多1-2句话
4. 适度使用emoji（⏰提醒、✅完成、📝新任务、🔄循环）
5. 只返回JSON对象——不要markdown、不要代码块、不要额外文字
6. 如果用户用英文发消息，理解意图但用中文回复"""


async def call_ai(messages: list, system_prompt: str = None, retries: int = 2,
                    temperature: float = None, max_tokens: int = None) -> dict:
    """Call the AI API and return the response.
    
    Args:
        messages: Conversation messages
        system_prompt: System prompt (default: main SYSTEM_PROMPT)
        retries: Number of retries on failure
        temperature: Sampling temperature (default 0.3 for precision, use 0.8+ for creativity)
        max_tokens: Max response tokens (default 500)
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
        "max_tokens": max_tokens or 500
    }
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {AI_API_KEY}"
    }
    
    last_error = None
    for attempt in range(retries + 1):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
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


def _extract_json(content: str) -> dict | None:
    """Robustly extract JSON from AI response, handling various formats."""
    content = content.strip()
    
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    
    json_match = re.search(r'```(?:json)?\s*(.*?)\s*```', content, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass
    
    brace_start = content.find('{')
    brace_end = content.rfind('}')
    if brace_start != -1 and brace_end > brace_start:
        try:
            return json.loads(content[brace_start:brace_end+1])
        except json.JSONDecodeError:
            pass
    
    return None


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
            "intent": "CHAT",
            "slots": {},
            "missing_slots": [],
            "reply": "抱歉，AI服务暂时不可用，请稍后再试。"
        }
    
    parsed = _extract_json(result["content"])
    
    if parsed and "intent" in parsed:
        return {
            "intent": parsed.get("intent", "CHAT"),
            "slots": parsed.get("slots", {}),
            "missing_slots": parsed.get("missing_slots", []),
            "reply": parsed.get("reply", "")
        }
    
    return {
        "intent": "CHAT",
        "slots": {},
        "missing_slots": [],
        "reply": result["content"] if result["content"] else "我没太理解，能再说一遍吗？"
    }

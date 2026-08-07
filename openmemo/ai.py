"""AI integration module - glm-5.2 via custom endpoint"""
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
- 智能识别不同场景：动态信息任务（如每日新闻）、出行事件（如赶飞机）、带日程表的任务集（如暑假作业）
- 日常聊天

## 工作方式
当用户发送消息时，判断意图并回复。你必须返回以下JSON格式：

{
  "intent": "NEWS_JOB | TRAVEL_EVENT | SCHEDULE | ADD_TASK | QUERY_TASK | COMPLETE_TASK | CHAT",
  "slots": { ... },
  "missing_slots": ["..."],
  "reply": "你的回复（必须用中文）"
}

## 意图选择原则（先想清楚再选，别乱套）
判断用户消息属于哪种意图，问对问题：

1. NEWS_JOB：用户要每天/每周推送、看新闻、资讯、天气预报这类周期性信息获取任务。
2. TRAVEL_EVENT：用户提到赶飞机、航班、坐高铁、乘火车去某地、出差这类出行事件。
3. SCHEDULE：用户提到写作业、暑假作业、寒假作业、学习计划、多个任务每天提醒这类带清单+截止日期、需要按天安排的事情。
4. ADD_TASK：普通单次或循环任务（开会、打电话、买牛奶等）。
5. 其他意图不变。

关键：每个意图问的问题不同，绝对不要问错误的问题：
- NEWS_JOB 不问耗时、不问优先级，问几点看 + 看什么类型。
- TRAVEL_EVENT 不问要多久完成/飞行时长，问去机场/车站要多久 + 国内还是国际。
- SCHEDULE 不问单个作业耗时，问有哪些作业/任务 + 哪天做完 + 每天几点提醒。
- ADD_TASK 才问耗时(duration)用于冲突检测。

---

### 意图：NEWS_JOB（动态信息任务）
用户想每天/定期获取信息（新闻、资讯、天气、股票等）。
提取：
- time: 每天几点（如"每天8点"）
- topic: 内容类型（科技/体育/综合/财经/天气等）
- 如果 time 或 topic 缺失，加入 missing_slots 并追问

示例：
用户："每天给我看新闻"
→ {"intent":"NEWS_JOB","slots":{"time":null,"topic":null},"missing_slots":["time","topic"],"reply":"好呀！每天几点给你看新闻？想看什么类型的？（科技、体育、财经还是综合？）"}

用户："每天8点看科技新闻"
→ {"intent":"NEWS_JOB","slots":{"time":"每天8点","topic":"科技"},"missing_slots":[],"reply":"明白！每天8点给你推送科技新闻 📰，到时候准时送上！"}

用户："每天早上给我报天气"
→ {"intent":"NEWS_JOB","slots":{"time":"每天早","topic":"天气"},"missing_slots":[],"reply":"没问题！每天早上报天气 ⛅，让你出门前就知道冷暖！"}

### 意图：TRAVEL_EVENT（出行事件）
用户要赶飞机/高铁/火车/长途出行。
识别信号词：赶飞机、航班、坐高铁、乘火车、出差、机场、车站。
提取：
- content: 出行内容（如"赶飞机"）
- event_time: 事件实际时间（如"明天13:00"）——这是出行本身的时间
- commute_minutes: 去机场/车站要多久（分钟）
- flight_type: "domestic"国内 / "international"国际 / null未定
- 若 event_time 有了但 commute_minutes/flight_type 缺失，追问（缺哪个问哪个）。

后端会反算提醒时间：event_time - commute_minutes - 建议提前量(国内2小时/国际3小时) = 出发提醒时间。

示例：
用户："我明天1点要赶飞机"
→ {"intent":"TRAVEL_EVENT","slots":{"content":"赶飞机","event_time":"明天13:00","commute_minutes":null,"flight_type":null},"missing_slots":["commute_minutes","flight_type"],"reply":"好的，明天13:00的航班，你到机场要多久？是国内还是国际航班？"}

用户："40分钟，国内"
→ {"intent":"TRAVEL_EVENT","slots":{"content":"赶飞机","event_time":"明天13:00","commute_minutes":40,"flight_type":"domestic"},"missing_slots":[],"reply":"收到！国内航班提前2小时到机场比较稳妥，出发路上40分钟。我会在明早10:00提醒你出发 ✈️"}

用户："后天下午3点的高铁，去杭州出差"
→ {"intent":"TRAVEL_EVENT","slots":{"content":"去杭州出差","event_time":"后天15:00","commute_minutes":null,"flight_type":null},"missing_slots":["commute_minutes"],"reply":"后天15:00去杭州的高铁，你到车站要多久呀？"}

### 意图：SCHEDULE（带日程表的任务集）
用户有一批任务/作业，需要在截止日期前按天安排完成，每天提醒当天该做的内容。
识别信号词：写作业、暑假作业、寒假作业、学习计划、每天提醒我、安排一下这些。
提取：
- content: 任务集名称（如"暑假作业"）
- tasks: 任务清单（数组，如["习字","西游记","英语阅读"]），若缺失追问
- deadline: 截止日期（如"8月10日"），若缺失追问
- remind_time: 每天提醒时间（如"11:00"），若缺失追问
- 不问单个任务的耗时，不重要。

示例：
用户："妈妈让我写作业，每天提醒我"
→ {"intent":"SCHEDULE","slots":{"content":"写作业","tasks":[],"deadline":null,"remind_time":null},"missing_slots":["tasks","deadline","remind_time"],"reply":"好呀！都布置了什么作业？什么时候要全部做完？我帮你每天安排提醒～"}

用户："我有习字、西游记、英语阅读，8月10号做完，每天11点提醒我"
→ {"intent":"SCHEDULE","slots":{"content":"暑假作业","tasks":["习字","西游记","英语阅读"],"deadline":"8月10日","remind_time":"11:00"},"missing_slots":[],"reply":"收到！习字、西游记、英语阅读，8月10号前完成。我帮你生成每天日程，每天早上11点提醒你当天该做的内容 📅"}

---

### 意图：ADD_TASK
用户想创建普通单次或循环任务（非上述三类）。
提取以下信息：
- content: 简短任务描述（必填，如果缺失必须追问）
- time: 提醒时间（如"明天下午3点"、"下周一9点"、"2小时后"）
- duration: 预计耗时（如"1小时"、"30分钟"、"2个小时"），用于冲突检测
- priority: "high"、"medium"或"low"（默认"medium"）
- recurring: 循环模式如"每天"、"每周一"、"工作日"（无则为null）

同时注意主动提问（用户没说全时）：
- "我要去游泳" → 时间缺失 → 追问"游泳不错！打算几点去呀？"
- 用户回答"下午3点" → 时间已给但duration也缺失 → 追问"大概要多久呀？一个多小时？"
- 用户回答"一个小时" → 信息齐了，创建任务。
- 买牛奶这类琐事不用追问时间和耗时。

示例：
用户："提醒我明天下午3点给妈妈打电话"
→ {"intent":"ADD_TASK","slots":{"content":"给妈妈打电话","time":"明天下午3点","duration":"30分钟","priority":"medium","recurring":null},"reply":"好的！已添加提醒：明天下午3点给妈妈打电话 ⏰"}

用户："我需要买牛奶"
→ {"intent":"ADD_TASK","slots":{"content":"买牛奶","time":null,"duration":null,"priority":"medium","recurring":null},"reply":"任务已添加：买牛奶 📝"}

用户："每周一早上9点有站会"
→ {"intent":"ADD_TASK","slots":{"content":"站会","time":"每周一9点","duration":"30分钟","priority":"medium","recurring":"每周一"},"reply":"循环任务已添加：每周一早上9点站会 🔄"}

用户："我要去游泳"
→ {"intent":"ADD_TASK","slots":{"content":"游泳","time":null,"duration":null,"priority":"medium","recurring":null},"missing_slots":["time"],"reply":"游泳不错！打算几点去呀？⏰"}

### 意图：QUERY_TASK
用户询问任务、日程或待办事项。
slots: content（可选搜索关键词）

示例：
用户："我有什么任务？"
→ {"intent":"QUERY_TASK","slots":{"content":null},"reply":"你目前的待办任务：\n1. ⏳ 给妈妈打电话（明天下午3点）\n2. ⏳ 买牛奶"}

### 意图：COMPLETE_TASK
用户说完成了或取消了某个任务。
slots: content（哪个任务）

示例：
用户："牛奶买好了"
→ {"intent":"COMPLETE_TASK","slots":{"content":"买牛奶"},"reply":"已完成：买牛奶 ✅"}

### 意图：CHAT
日常聊天，不属于以上任何意图。
slots: 空对象
聊天时要有个性，可以开玩笑、卖萌、吐槽，像朋友一样。

示例：
用户："你好"
→ {"intent":"CHAT","slots":{},"reply":"嘿！我是OpenMemo，你的任务小助手～有啥需要帮忙的？"}

## 规则
1. 必须用中文回复，即使用户用英文写消息也要用中文回复。
2. 被问到名字时始终说自己是OpenMemo。
3. 回复要简短，任务确认最多1-2句话。
4. 适度使用emoji（⏰提醒、✅完成、📝新任务、🔄循环、📰新闻、✈️出行、📅日程）。
5. 只返回JSON对象，不要markdown、不要代码块、不要额外文字。
6. missing_slots 数组列出当前还缺的关键信息，缺哪些列哪些，不缺就空数组。
7. 如果用户用英文发消息，理解意图但用中文回复。

## 多轮对话与“别死磕”原则（非常重要）
你是在一个多轮对话里帮助用户，用户可能中途改主意、开玩笑、拒绝、转移话题。你要像人一样灵活，绝对不要像个卡住的机器人。

- **绝不重复同一个问题**：如果上一轮你已经问了某个问题，这一轮用户没有直接回答（而是说别的、拒绝、否定、开玩笑），⚠️ 绝对不要再问一遍同样的话。
  - 用户说“我没说要赶飞机啊”、“我没有”、“不告诉你了” → 说明用户不想继续这个话题。此时**放弃/取消当前正在收集的任务**：把 slots 置空或清掉，missing_slots 置空，回复里带点幽默/理解地结束这个话题，转到 CHAT 或看用户是否要开新任务。不要固执追问。
  - 用户否定当前任务主题（如“我不是说出差”、“不说飞机了”）→ 理解为放弃离开当前位置的主题，转为 CHAT 或用新信息重新开始。
- **识别放弃/否定信号词**：『算了、取消、不用了、放弃、不弄了、不讲了、我不说、没说、不是X、不要X、没说要、不告诉你、不想说、换个话题、算了算了』。
- **用户给新信息时，顺着新信息走**：比如上一轮在问任务A，用户却说了一件完全无关的事B，那就把B当作当前话题，重新判断意图，不要还纠结A。
- **耐心但不要固执**：收集信息时一次只追问最关键的1个问题，问完停。用户在开玩笑就陪他玩一下，别把玩笑当真。
- **对话要有人情味**：用户拒绝时别冷冰冰，可以“哈哈，好呀，那我就不多问啦～”这样自然收场。"""


async def call_ai(messages: list, system_prompt: str = None, retries: int = 1,
                    temperature: float = None, max_tokens: int = None) -> dict:
    """Call the AI API and return the response.
    
    Uses STREAMING because the yuanyuaicloud endpoint only responds to
    stream=true requests (non-streaming hangs/times out).
    
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
        "max_tokens": max_tokens or 500,
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

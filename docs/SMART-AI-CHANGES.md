# OpenMemo AI 升级计划 — "智能理解" 阶段

## 背景

当前 OpenMemo 的 AI 只能理解 4 种意图：`ADD_TASK` / `QUERY_TASK` / `COMPLETE_TASK` / `CHAT`。
用户想要的是 OpenMemo 能**智能区分不同场景**，问对问题，做出对的动作。

### 目标场景（三个原型）

| 场景 | 用户说 | 当前行为（错误） | 期望行为（正确） |
|---|---|---|---|
| 1️⃣ 动态信息任务 | "每天给我看新闻" | 创建一个"看新闻"任务，每天同一时间提醒，内容固定 | 识别为**信息获取型重复任务**，问"几点看"+"看什么类型的新闻"，每次运行时搜索新闻，输出当天新鲜内容 |
| 2️⃣ 出行提醒 | "明天1点赶飞机" | 问"要多久"（误以为问飞行时长），创建任务"赶飞机 明天13:00" | 识别为**出行事件**，问"去机场要多久"+"国内还是国际"→反推出出发提醒时间（13:00-40min-2h缓冲=10:00提醒），创建出发提醒 |
| 3️⃣ 动态每日提醒 | "妈妈让我写作业，每天提醒我" | 创建"写作业 每天11:00"的静态循环任务 | 识别为**带日程表的重复任务**，问"有哪些作业"+"什么时候做完"，自动生成按天分配的日程表，每天提醒当天具体内容，内容随日期变化 |

---

## 一、架构变更：扩展意图模型

### 新增意图类型

```
ADD_TASK       → 原有（单次/循环任务）
QUERY_TASK     → 原有
COMPLETE_TASK → 原有
CHAT          → 原有
NEWS_JOB      → 新增 🆕  信息获取型重复任务
TRAVEL_EVENT  → 新增 🆕  出行事件（需要反算提醒时间）
SCHEDULE      → 新增 🆕  带日程表的任务集（动态每日内容）
```

### 核心原则：问对问题

每种意图触发不同的追问逻辑：

| 意图 | 追问 1 | 追问 2 | 追问 3 | 不做 |
|---|---|---|---|---|---|
| `NEWS_JOB` | "几点看？" | "看什么类型的新闻？（科技/体育/综合）" | — | 不问耗时、优先级 |
| `TRAVEL_EVENT` | "去机场/车站要多久？" | "国内还是国际航班？" | — | 不问"要多久完成"（那是飞行时长，不需要） |
| `SCHEDULE` | "有什么作业？" | "什么时候做完？" | "每天几点提醒？" | 不问单次耗时（不同作业耗时不同，不重要） |
| `ADD_TASK`（原有） | "几点？" | "要多久？" | — | 不问"看什么类型" |

---

## 二、实现细节

### 2.1 `ai.py` — 系统提示扩展

需要在 SYSTEM_PROMPT 中新增三个意图的定义和示例，并在 `analyze_intent` 中处理新意图的 JSON 格式。

**NEWS_JOB 格式：**
```json
{
  "intent": "NEWS_JOB",
  "slots": {
    "time": "每天8点",
    "topic": "科技",
    // 新闻主题：科技/体育/综合/财经等
  },
  "reply": "好的！每天8点给你推送科技新闻 📰"
}
```

**TRAVEL_EVENT 格式：**
```json
{
  "intent": "TRAVEL_EVENT",
  "slots": {
    "content": "赶飞机",
    "event_time": "明天13:00",
    // 事件时间（不是提醒时间）
    "commute_minutes": 40,        // 去机场耗时（分钟）
    "flight_type": "domestic"       // "domestic" 国内 / "nternational" 国际
  },
  "reply": "好的！13:00的国内航班，去机场要40分钟，建议10:00出发，我会在10:00提醒你 ✈️"
}
```

**SCHEDULE 格式：**
```json
{
  "intent": "SCHEDULE",
  "slots": {
    "content": "暑假作业",
    "deadline": "8月10日",          // 截止日期
    "tasks": ["习字", "西游记", "英语阅读", ...], // 所有作业列表
    "daily_remind_time": "11:00",    // 每天提醒时间
    "afternoon_remind_time": "14:00" // 下午提醒时间（可选）
  },
  "reply": "好的！已经记住了你的暑假作业清单。我来帮你安排……从今天到8月10日，每天提醒你当天该做的内容！"}
```

### 2.2 `conversation.py` — 路由扩展

当前 `process_message` 只处理 `ADD_TASK / QUERY_TASK / COMPLETE_TASK / CHAT`。
需要新增路由分支：

```python
if result["intent"] == "NEWS_JOB":
    # → 创建循环 cron 任务（通过 OpenClaw 或内置调度器）
    # → 存储 topic + time
    # → 每次触发时调用 web_search / webfetch 获取当日新闻
    # → 用 TTS 朗读 并推送消息到 App

elif result["intent"] == "TRAVEL_EVENT":
    # → 反算提醒时间
    # event_tiem - commmute_minutes - buffer (国内2h/国际3h) = depature_time
    # → 创建一条"出发提醒"任务在 departure_time
    # → 同时可创建一条"check-in提醒"在 earlier

elif result["intent"] == "SCHEDULE":
    # → 接收 tasks 列表和 deadline
    # → 自动按天分配任务（算法见下文）
    # → 生成一个 schedule 表（类似 homework-schedule.md）
    # → 每天按 schedule 提醒当日内容
```

### 2.3 日程自动分配算法（for SCHEDULE）

```
输入：tasks_list, deadline, start_date（=今天）
输出：按天分配的日程表

1. 过滤出需要"按天分配"的任务（不是所有任务都需要）
   - 像"习字20首"可分配为每天1首×20天
   - 像"家长签字"只需要最后一天
2. 计算可用天数 = (deadline - start_date).days
3. 将任务均匀分配到可用天数
4. 生成 markdown 日程表文件（类似 homework-schedule.md 格式）
```

### 2.4 新文件建议

可以保持文件结构干净的方式：

- `openmemo/intents/` 目录（可选，如果代码量大了再分）
- 或者直接在 `ai.py` + `conversation.py` 中扩展路由

推荐在 **`ai.py` 中加意图定义和 prompt**，在 **`conversation.py` 中加处理逻辑**，保持现有架构。

### 2.5 数据层变更

`tasks` 表可能需要新字段：
- `task_type`：TEXT, "normal" / "news" / "travel" / "schedule"
- `meta_data`：TEXT, JSON 存储各意图特有信息（如 topic、commute_minutes、schedule_content）

或者新表：
- `news_jobs`：job_id, time, topic, last_run_at
- `schedules`：schedule_id, content, deadline, daily_time, tasks_json

推荐：先在 `tasks` 表加 `task_type` + `meta_data`，简单统一。

---

## 三、实现顺序

### Phase 1 — 意图识别升级（高优先级）
1. 扩展 `ai.py` 的 SYSTEM_PROMPT，加入 NEWS_JOB、TRAVEL_EVENT、SCHEDULE 的定义和示例
2. `analyze_intent` 返回新意图
3. 测试 AI 能否正确分类

### Phase 2 — 处理逻辑（中优先级）
4. `conversation.py` 中为 NEWS_JOB 添加路由（保存配置，设置循环执行）
5. `conversation.py` 中为 TRAVEL_EVENT 添加路由（反算时间，创建出发提醒）
6. `conversation.py` 中为 SCHEDULE 添加路由（自动分配日程，生成日程表）

### Phase 3 — 执行层（高优先级）
7. NEWS_JOB 的执行：循环触发时，搜索新闻 + 生成内容 + 推送给用户
8. SCHEDULE 的执行：每天按日程表提醒当天内容
9. TRAVEL_EVENT 的执行：出发时间到了提醒用户

### Phase 4 — 数据持久化（低优先级）
10. 如果需要重启后保留配置，把 jobs 信息存到 tasks 表或新表

---

## 四、技术约束

- 当前 OpenMemo 运行在 Ethan 的 Mac mini 上，通过 cloudflared tunel 对外暴露
- 没有外网持久化存储，重启后内存状态丢失（cron 等）
- NEWS_JOB 的 web_search 能力需要集成一个搜索 API（webfetch 或 tavily 或 serpapi）
- 无 IM 推送通道（App 纯 REST，提醒通过任务状态 + Mac 扬声器播报）
- TTS 已打通，用 `edge-tts` + `afplay`
- OpenMemo 后端是 Python，无外部依赖（除了 httpx）

---

## 五、不做的事情

- 不做环境感知
- 不做兴趣衰减算法
- 不做多用户支持（V2 再说）
- 不做设备间流转

---

## 六、实施进度（2026-08-05 已实现 ✅）

以下内容**已完成编码、单元测试、并通过真实 HTTP 服务端到端验证**：

### Phase 1 — 意图识别（✅ 完成）
- `ai.py` SYSTEM_PROMPT 扩展为 7 种意图：新增 `NEWS_JOB` / `TRAVEL_EVENT` / `SCHEDULE`
- 每种意图带「问对问题」原则 + 示例
- 已验证：`analyze_intent` 正确识别 3 个新意图并返回正确 `missing_slots`

### Phase 2 — 路由（✅ 完成）
- `conversation.py` 新增 `_handle_news_job` / `_handle_travel_event` / `_handle_schedule`
- `pending_slots` 表新增 `intent` 列，多轮追问按意图正确完成
- 反算出发时间：`event_time − commute − (国内2h/国际3h)`
- 自动生成按天日程表（`_build_schedule_plan`）
- 意图感知的确定性补全（不依赖 AI 提取，保证追问发生）

### Phase 3 — 执行层（✅ 完成）
- `scheduler.py` `reminder_callback` 按 `task_type` 分流：
  - **news**：触发时 `_execute_news_job` 生成当日新闻摘要 + 语音播报
  - **travel**：触发时 `_execute_travel_reminder` 提醒出发（带路程/提前量上下文）
  - **schedule**：触发时 `_execute_schedule_reminder` 读取当天日程提醒
- 每日智能任务自调度次日（`_schedule_next_daily_task`），重启后 `load_existing_tasks` 重装备

### Phase 4 — 数据持久化（✅ 完成）
- `tasks` 表新增 `task_type`（normal/news/travel/schedule）+ `meta_data`（JSON）列
- `TaskManager.add_task` / `get_task` / `list_tasks` 均支持存取
- `POST /api/tasks` 支持 `task_type` + `meta_data` 字段

### 已验证场景（真实 HTTP 服务）
| 输入 | 结果 |
|---|---|
| "每天给我看体育新闻" → "每天早上8点吧" | 创建 news 任务，每天8点推送体育新闻 ✅ |
| "后天下午3点高铁去杭州出差" → "30分钟，国内" | 反算出 **8/7 12:30** 出发提醒 ✅ |
| "我要写作业" → "暑假作业，口算和阅读，8月15号做完，每天下午2点提醒我" | 生成 10 天日程，每天 14:00 提醒 ✅ |

### 待办（可选的后续增强）
- NEWS_JOB 的真实 web_search 集成（当前用 AI 生成 + 可选 RSS 降级，无稳定搜索 API）
- iOS App 端新增 smart-task 创建界面（后端已支持）

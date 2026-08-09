# OpenMemo 流程说明

## 核心流程（当前架构）

```
iOS App → POST /api/chat → OpenMemo 服务端（FastAPI）
   │
   ├─ 把"用户消息 + 历史 + 当前时间"交给 AI（默认 glm-5.2）
   ├─ AI 返回结构化 JSON：{ reply, action, task{time, reminder_text, ...}, appointment{at, read_aloud} }
   ├─ 服务端 ①原样回复 AI 的话 ②把任务/提醒存进 SQLite 并按时间调度
   └─ 到点 → Edge TTS 生成语音 → Mac 扬声器播放（afplay）
```

## 设计原则：AI 全权负责对话

- **没有任何确定性"话术/模板/槽位填充"逻辑**。问什么、怎么问、是否追问、写什么话，全部由 AI 自主决定。
- 服务端只有一个轻量程序：解析 AI 的 JSON → 原样回复 → 存任务 → 按时播报。
- 智能任务类型由 AI 判定：`normal` / `travel`（出行，AI 反算出发时间）/ `news`（每日新闻，Tavily 搜索）/ `schedule`（带日程的重复任务，如暑假作业）。

## 详细流程

### 1. 消息输入
- 用户通过 iOS App 发送文本消息，App 调用 `POST /api/chat`。
- 服务端把消息连同会话历史、当前时间一起交给 AI。

### 2. AI 决策
- AI 独立判断该回复什么、要不要创建任务/提醒。
- AI 返回结构化 JSON；"承诺就必须落地"：一旦确认提醒时间，同轮必须返回创建动作。

### 3. 任务管理
- 任务存入 SQLite（`data/openmemo.db`），带状态跟踪。
- APScheduler 根据 `trigger_time` 设置提醒。
- 到提醒时间 → Edge TTS 生成中文语音 → Mac mini 扬声器播放（afplay）。
- 任务标记 `reminder_sent`，App 轮询任务列表感知提醒。

### 4. 语音输出
- Edge TTS 生成中文语音（zh-CN-XiaoxiaoNeural）。
- 音频按文本哈希缓存（避免重复生成相同文本）。
- 通过 macOS `afplay` 命令播放。

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | Web 仪表盘（辅助查看） |
| GET | `/api/health` | 健康检查 |
| GET | `/api/tasks` | 任务列表 |
| GET | `/api/tasks/{id}` | 获取任务 |
| POST | `/api/tasks` | 创建任务 |
| PATCH | `/api/tasks/{id}` | 更新任务 |
| DELETE | `/api/tasks/{id}` | 删除任务 |
| POST | `/api/chat` | 与 AI 对话（核心） |
| POST | `/api/speak` | 语音播报 |
| GET | `/api/conversations/{id}` | 获取对话历史 |
| GET | `/api/sessions` | 会话列表 |
| DELETE | `/api/sessions/{id}` | 删除会话 |

## 数据模型

### 任务表（Tasks）
| 字段 | 类型 | 说明 |
|------|------|------|
| task_id | INTEGER PK | 自增 ID |
| content | TEXT | 任务描述 |
| task_type | TEXT | normal / travel / news / schedule |
| trigger_time | TEXT | 提醒时间（YYYY-MM-DD HH:MM） |
| priority | TEXT | 优先级 high/medium/low |
| status | TEXT | 状态 pending / completed / cancelled |
| is_recurring | TEXT | 循环模式（每天/每周一 等） |
| reminder_sent | INTEGER | 是否已发送提醒 |
| meta_data | TEXT | JSON，含 AI 写的 `reminder_text` 等 |
| notes | TEXT | 附加备注 |

### 会话表（Conversations）
| 字段 | 类型 | 说明 |
|------|------|------|
| conv_id | INTEGER PK | 自增 ID |
| session_id | TEXT | 用户会话标识 |
| role | TEXT | user/assistant 用户/助手 |
| content | TEXT | 消息内容 |
| intent | TEXT | 动作类型（task_added / chat 等） |
| slots | TEXT | 任务信息（JSON） |

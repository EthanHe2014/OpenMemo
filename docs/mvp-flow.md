# OpenMemo MVP 流程

## 核心流程

```
用户 → 飞书消息 → Webhook → AI (glm-5.1) → 任务/回复 → Edge TTS → 扬声器
```

## 详细流程

### 1. 消息输入
- 用户通过飞书发送文本或语音消息
- 飞书 Webhook 将事件投递到 OpenMemo 服务端
- 语音消息：飞书提供内置 STT（语音转文字）

### 2. 意图分析
- 文本携带意图识别提示词发给 glm-5.1
- AI 识别意图：ADD_TASK（新增任务）、QUERY_TASK（查询）、COMPLETE_TASK（完成）、CHAT（闲聊）
- ADD_TASK 会提取槽位（内容、时间、优先级、是否循环）

### 3. 槽位补全状态机
- 必填槽位齐全 → 直接创建任务
- 槽位缺失 → 保存部分状态，主动追问
- 用户随时可用「算了」「取消」等取消当前操作
- 下一条消息与已保存的部分槽位合并

### 4. 任务管理
- 任务存入 SQLite，带状态跟踪
- APScheduler 根据 trigger_time 设置提醒
- 到提醒时间 → Edge TTS 生成语音 → Mac mini 扬声器播放（afplay）

### 5. 语音输出
- Edge TTS 生成中文语音（zh-CN-XiaoxiaoNeural）
- 音频按文本哈希缓存（避免重复生成相同文本）
- 通过 macOS `afplay` 命令播放

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /webhook/feishu | 飞书机器人 Webhook |
| GET | /api/tasks | 任务列表 |
| GET | /api/tasks/{id} | 获取任务 |
| POST | /api/tasks | 创建任务 |
| PATCH | /api/tasks/{id} | 更新任务 |
| DELETE | /api/tasks/{id} | 删除任务 |
| POST | /api/chat | 与 AI 对话 |
| POST | /api/speak | 语音播报 |
| GET | /api/conversations/{id} | 获取对话历史 |

## 数据模型

### 任务表（Tasks）
| 字段 | 类型 | 说明 |
|------|------|------|
| task_id | INTEGER PK | 自增 ID |
| content | TEXT | 任务描述 |
| trigger_time | TEXT | 提醒时间（YYYY-MM-DD HH:MM） |
| priority | TEXT | 优先级 high/medium/low |
| status | TEXT | 状态 pending/confirmed/completed/cancelled |
| is_recurring | TEXT | 循环模式（每天/每周一 等） |
| reminder_sent | INTEGER | 是否已发送提醒 |
| notes | TEXT | 附加备注 |

### 对话表（Conversations）
| 字段 | 类型 | 说明 |
|------|------|------|
| conv_id | INTEGER PK | 自增 ID |
| session_id | TEXT | 用户会话标识 |
| role | TEXT | user/assistant 用户/助手 |
| content | TEXT | 消息内容 |
| intent | TEXT | 识别到的意图 |
| slots | TEXT | 提取的槽位（JSON） |

### 槽位补全表（Pending Slots）
| 字段 | 类型 | 说明 |
|------|------|------|
| pending_id | INTEGER PK | 自增 ID |
| session_id | TEXT | 用户会话 |
| partial_slots | TEXT | 已填部分槽位（JSON） |
| missing_slots | TEXT | 缺失槽位列表（JSON） |
| original_message | TEXT | 原始用户消息 |

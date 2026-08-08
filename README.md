# OpenMemo

AI 驱动的个人语音助手 —— 会对话、会记任务、会在你需要的时候主动提醒你。

OpenMemo 的核心 AI 基于 `glm-5.2`。它的特别之处在于：**AI 负责所有"思考"和"说话"**，服务端只有一个轻量程序，负责把 AI 的结构化输出解析出来、存任务、按时间把 AI 写的提醒念出来。

---

## 一、它能做什么

- 🗣️ **自然对话**：像真人一样聊天、追问、确认，由 AI 自主决定问什么、怎么问。
- 📝 **记任务**：你说"明天开会"，它自动记下；你说"每天提醒我写作业"，它建立每日循环提醒。
- ✈️ **出行提醒**：你说"明天13:00赶飞机"，它会主动问你到机场要多久、国内还是国际，然后**反推出出发提醒时间**（提前留出堵车/值机/安检缓冲），到点念给你听。
- 📰 **每日新闻**：你说"每天给我看新闻"，它每天到点搜索当天新鲜新闻播给你。
- 📅 **带日程的重复任务**：暑假作业按天分配，每天提醒当天具体内容。
- 🔈 **语音播报**：Mac mini 扬声器用中文读出提醒（Edge TTS）。
- 📱 **iOS App**：手机上看任务、对话、管理会话（DeepSeek 风格侧边栏）。

### 智能任务类型

| 类型 | 触发场景 | 行为 |
|------|----------|------|
| `normal` | 普通任务（开会/打电话/买东西） | 到点提醒 |
| `travel` | 出行事件（赶飞机/高铁） | AI 问清出发时间、到站耗时、国内/国际 → 反算出发提醒时间 |
| `news` | 每日新闻 | 每天到点搜索当天实时新闻并播报 |
| `schedule` | 带日程的重复任务（暑假作业） | 每天提醒当天具体内容，内容随日期变化 |

---

## 二、架构

**AI 自主架构**（2026-08 新版）：

```
用户（飞书 / iOS App）
   │  发送消息
   ▼
OpenMemo 服务端（FastAPI）
   │  【唯一行为逻辑：把消息交给 AI，解析 AI 返回的 JSON】
   │  1. 把"用户消息 + 历史 + 当前时间"发给 glm-5.2
   │  2. AI 返回 { reply, action, task{time, reminder_text, ...}, appointment{at, read_aloud} }
   │  3. 服务端 ①原样回复 AI 的话 ②把任务/提醒存进 SQLite 并按时间调度
   │  4. 到点 → 把 AI 写的 reminder_text 用 Edge TTS 生成语音 → Mac 扬声器播报
   ▼
飞书机器人 / iOS App / Mac 扬声器
```

- **AI 全权负责对话**：问什么、怎么问、是否放弃追问、写什么样的话，全部由 AI 自己决定。
- **服务端不做任何"话术/模板/槽位填充"**：它只负责解析 AI 的 JSON、存任务、按时播报。
- **模型**：`glm-5.2`（通过自定义接口 `https://yuanyuaicloud.cn/v1`，仅支持流式请求）。

### 技术栈

| 组件 | 技术 |
|------|------|
| 服务端 | Python 3.14 + FastAPI |
| AI | glm-5.2（自定义接口，流式） |
| 实时新闻 | Tavily 搜索 API |
| STT（语音转文字） | 飞书内置 |
| TTS（文字转语音） | Edge TTS（zh-CN-XiaoxiaoNeural） |
| 存储 | SQLite |
| 调度 | APScheduler |
| 消息入口 | 飞书机器人 Webhook / iOS App |
| 语音输出 | Mac mini 扬声器（afplay） |
| 手机端 | SwiftUI iOS App（OpenMemoApp 独立仓库） |

---

## 三、项目结构

```
OpenMemo/
├── README.md
├── requirements.txt      # 依赖清单
├── start.sh              # 一键启动脚本
├── .env.example          # 配置模板（复制为 .env 填真实值）
├── openmemo/
│   ├── __init__.py
│   ├── server.py         # FastAPI 服务 + 飞书 Webhook + 全部 API
│   ├── ai.py             # glm-5.2 接入 + SYSTEM_PROMPT（AI 的"人设"）
│   ├── conversation.py   # 核心：把消息交给 AI，解析 JSON，原样回复
│   ├── scheduler.py      # APScheduler 提醒调度 + 按任务类型执行
│   ├── tasks.py          # 任务/会话/槽位 的 SQLite 存取
│   ├── feishu.py         # 飞书机器人接入（发消息给用户）
│   ├── voice.py          # Edge TTS 生成语音 + Mac 扬声器播放
│   └── config.py         # 配置读取（.env）
├── data/                 # SQLite 数据库 + 音频缓存（自动创建）
├── tests/
│   └── test_tasks.py
└── docs/
    └── mvp-flow.md
```

> 📱 **iOS App 在独立仓库**：`github.com/EthanHe2014/OpenMemoApp`（SwiftUI，零外部依赖，单独构建）。

---

## 四、部署启动（Step by Step）

### 步骤 1：准备环境

需要：一台能联网的 Mac（负责跑服务 + 播报语音）、一个飞书开放平台应用、一个可用的 AI API Key。

```bash
cd OpenMemo
python3 -m venv .venv                # 创建虚拟环境
source .venv/bin/activate            # 激活（或直接 .venv/bin/python）
pip install -r requirements.txt      # 安装依赖
```

### 步骤 2：配置

```bash
cp .env.example .env
# 编辑 .env，填入真实值
```

`.env` 里需要填：
- `AI_BASE_URL` / `AI_API_KEY` / `AI_MODEL`：AI 接口（模型填 `glm-5.2`）
- `TAVILY_API_KEY`：Tavily 搜索 Key（用于每日新闻）
- `FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `FEISHU_VERIFICATION_TOKEN` / `FEISHU_ENCRYPT_KEY`：飞书机器人凭据
- `FEISHU_DEFAULT_USER`：接收提醒的用户 open_id（用于主动推送）
- `SERVER_PORT`：默认 `18890`

### 步骤 3：启动服务

```bash
./start.sh
# 或手动：
.venv/bin/python -u -m openmemo.server
```

启动成功后日志会显示：`Application startup complete` + `[调度器] 已启动`。服务跑在 `http://0.0.0.0:18890`。

### 步骤 4：打通飞书

飞书机器人需要能被公网访问。用 **Cloudflare 快速隧道** 把本地端口暴露出去：

```bash
cloudflared tunnel --url http://localhost:18890
```

把输出的 `https://xxx.trycloudflare.com` 填到飞书开放平台的**事件订阅地址**：
- 事件订阅 URL：`https://xxx.trycloudflare.com/webhook/feishu`

> ⚠️ 快速隧道重启后 URL 会变，需要在飞书后台更新订阅地址；iOS App 的 `baseURL` 也需要同步更新成最新隧道地址。

### 步骤 5：在飞书里使用 / 手机用 App

- **飞书**：直接给机器人发中文消息即可，支持文字和语音。
- **iOS App**：打开 `OpenMemoApp` 仓库，把 `Networking/OpenMemoAPI.swift` 里的 `baseURL` 改成最新隧道地址，用 Xcode 构建运行到模拟器或真机。

---

## 五、使用指南（Step by Step）

### 🗣️ 先跟它打个招呼

在飞书或 App 里发：
```
你好
```
它会用中文自然回应，介绍自己能干什么。**注意：所有对话用中文，即使你发英文，它也会用中文回你。**

### 📝 记一个普通任务

```
明天下午3点开会
```
它会确认任务内容与时间并记下，到点提醒你。

**琐事不用给时间**：
```
帮妈妈买牛奶
```
它会直接记下，不追问时间。

### ⏰ 设置每日循环提醒

```
每天上午11点提醒我写作业
```
它会建立每日循环任务，每天 11:00 播报提醒。

### ✈️ 出行提醒（自动反算出出发时间）

```
明天13:00赶飞机，从家到机场要1小时，国际航班
```
它会：
1. 主动问你"几点起飞 / 到机场多久 / 国内还是国际"（信息不全时它自己会问）
2. 帮你**反算出发时间**（国际航班会留出更长缓冲）
3. 到点念一段贴心提醒给你听，比如：
   > "早上好！该出发去机场啦。请检查好护照、签证和登机牌，带齐行李，路上注意安全！"

### 📰 每日新闻

```
每天给我看新闻
```
它会问你想几点看、看什么类型，然后每天到点搜索当天实时新闻播报。

### 📅 暑假作业（带日程的重复任务）

```
妈妈让我写作业，每天提醒我
```
它会问有哪些作业、什么时候做完、每天几点提醒，然后每天提醒当天该做的具体内容。

### ✅ 查看 / 完成 / 删除任务

```
我有什么任务          # 查看任务列表
牛奶买好了            # 标记"买牛奶"完成
把明天的会取消掉      # 删除任务
```

### 🚫 说错了 / 不想继续

随时可以打断它，它会大方收场，绝不追问：
```
算了 / 不是 / 我没说这个 / 不告诉你了 / 换个话题
```

---

## 六、API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/webhook/feishu` | 飞书机器人 Webhook |
| GET | `/` | Web 仪表盘 |
| GET | `/api/health` | 健康检查 |
| GET | `/api/tasks` | 任务列表 |
| GET | `/api/tasks/{id}` | 获取单个任务 |
| POST | `/api/tasks` | 创建任务 |
| PATCH | `/api/tasks/{id}` | 更新任务 |
| DELETE | `/api/tasks/{id}` | 删除任务 |
| POST | `/api/chat` | 与 AI 对话（核心） |
| POST | `/api/speak` | 播报一段文字 |
| GET | `/api/conversations/{session_id}` | 获取会话历史 |
| GET | `/api/sessions` | 会话列表（侧边栏） |
| DELETE | `/api/sessions/{session_id}` | 删除会话 |

---

## 七、数据模型

### 任务表（tasks）
| 字段 | 说明 |
|------|------|
| task_id | 自增 ID |
| content | 任务描述 |
| task_type | `normal` / `travel` / `news` / `schedule` |
| trigger_time | 提醒时间（YYYY-MM-DD HH:MM） |
| priority | 优先级 |
| status | `pending` / `completed` / `cancelled` |
| is_recurring | 循环模式（每天/每周一 等） |
| reminder_sent | 是否已发送提醒 |
| meta_data | JSON，含 AI 写的 `reminder_text` 等 |

### 会话相关
- **conversations**：每条消息（role / content / intent）
- **sessions**：会话列表（标题 = 第一条用户消息）
- **pending_slots**：多轮追问状态（已弃用，改为 AI 自主处理）

---

## 八、常见问题

**Q：模型用哪个？**
`glm-5.2`。必须是这个确切名字，不要在代码/配置里写错大小写。

**Q：AI 不创建任务怎么办？**
新版已内置"承诺就必须落地"规则：AI 一旦向你确认提醒时间，同一轮就必须返回创建任务的动作，服务端才会真正调度。若仍遇到"说了但不建"的情况，检查服务日志是否有 `[调度器] 已安排任务 X`。

**Q：飞书收不到提醒？**
确认 `FEISHU_DEFAULT_USER` 填了接收者的 open_id，且服务日志里 `[推送]` 成功。

**Q：App 连不上？**
基本是隧道 URL 变了。把 `OpenMemoAPI.swift` 的 `baseURL` 和飞书事件订阅地址都更新成最新隧道地址。

**Q：Mac 没声音？**
检查系统输出设备是不是 Mac 自带扬声器（ToDesk 等远程工具会挂虚拟声卡抢占输出）。

---

## 九、免责 / 依赖

- 依赖一个可用的 AI 接口（默认 `https://yuanyuaicloud.cn/v1`，模型 `glm-5.2`）。
- 语音播报依赖本机 `edge-tts` + `afplay`，需要能访问 Edge TTS 服务。
- 每日新闻依赖 Tavily API Key。

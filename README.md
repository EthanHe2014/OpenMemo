# OpenMemo

AI 驱动的个人语音助手 —— 会对话、会记任务、会在你需要的时候主动提醒你。

OpenMemo 的核心是一个**可配置的大模型对话 AI**（默认 `glm-5.2`，你也可以换成任何 OpenAI 兼容接口，见下文 [配置你自己的 AI](#配置你自己的-ai-base-url--api-key--模型)）。它的特别之处在于：**AI 负责所有"思考"和"说话"**，服务端只有一个轻量程序，负责把 AI 的结构化输出解析出来、存任务、按时间把 AI 写的提醒念出来。

---

## 一、它能做什么

- 🗣️ **自然对话**：像真人一样聊天、追问、确认，由 AI 自主决定问什么、怎么问。
- 📝 **记任务**：你说"明天开会"，它自动记下；你说"每天提醒我写作业"，它建立每日循环提醒。
- ✈️ **出行提醒**：你说"明天13:00赶飞机"，它会主动问你到机场要多久、国内还是国际，然后**反推出出发提醒时间**（提前留出堵车/值机/安检缓冲），到点念给你听。
- 📰 **每日新闻**：你说"每天给我看新闻"，它每天到点搜索当天新鲜新闻播给你。
- 📅 **带日程的重复任务**：暑假作业按天分配，每天提醒当天具体内容。
- 🔈 **语音播报**：Mac mini 扬声器用中文读出提醒（Edge TTS）。
- 📱 **iOS App**：手机上看任务、对话、管理会话（DeepSeek 风格侧边栏）。> ⚠️ 尚未上架 App Store，需 Mac + Xcode 源码构建（见 [iOS 使用指南](docs/setup-ios-xcode.md)）。

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
   │  1. 把"用户消息 + 历史 + 当前时间"发给你的 AI 接口（默认 glm-5.2）
   │  2. AI 返回 { reply, action, task{time, reminder_text, ...}, appointment{at, read_aloud} }
   │  3. 服务端 ①原样回复 AI 的话 ②把任务/提醒存进 SQLite 并按时间调度
   │  4. 到点 → 把 AI 写的 reminder_text 用 Edge TTS 生成语音 → Mac 扬声器播报
   ▼
飞书机器人 / iOS App / Mac 扬声器
```

- **AI 全权负责对话**：问什么、怎么问、是否放弃追问、写什么样的话，全部由 AI 自己决定。
- **服务端不做任何"话术/模板/槽位填充"**：它只负责解析 AI 的 JSON、存任务、按时播报。
- **模型**：可配置。默认 `glm-5.2`（通过自定义接口 `https://yuanyuaicloud.cn/v1`，仅支持流式请求）；可在 `.env` 里改成你自己的 BaseURL / API Key / 模型名，任意 OpenAI 兼容接口都能用。

### 技术栈

| 组件 | 技术 |
|------|------|
| 服务端 | Python 3.14 + FastAPI |
| AI | 可配置大模型（默认 glm-5.2，任意 OpenAI 兼容接口） |
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
    ├── mvp-flow.md            # MVP 流程说明
    ├── setup-feishu.md        # 飞书接入指南
    ├── setup-ios-xcode.md     # iOS App（Xcode）使用指南
    ├── setup-dingtalk.md      # 钉钉接入指南
    └── setup-wecom.md         # 企业微信接入指南
```

> 📱 **iOS App 在独立仓库**：`github.com/EthanHe2014/OpenMemoApp`（SwiftUI，零外部依赖，单独构建）。
>
> ⚠️ **iOS App 尚未上架 App Store**——需要一台 Mac 安装 Xcode，用源码构建到模拟器或真机运行。详见 [iOS 使用指南（Xcode）](docs/setup-ios-xcode.md)。

---

## 配置你自己的 AI（Base URL / API Key / 模型）

OpenMemo 的对话大脑可以是**任何 OpenAI 兼容的模型服务**，不局限于某一家。你只需在 `.env` 里填三样东西：

```bash
# 示例：用自己的服务
AI_BASE_URL=https://你的模型服务域名/v1      # 通常是 .../v1
AI_API_KEY=sk-你的密钥
AI_MODEL=你的模型名                          # 如 deepseek-chat / glm-5.2 / 你公司部署的模型
```

- 接口只要**兼容 OpenAI 的 `/chat/completions` 且支持流式（stream）响应**即可。
- 不填 `AI_BASE_URL` / `AI_MODEL` 时使用默认值（`https://yuanyuaicloud.cn/v1` + `glm-5.2`），但 `AI_API_KEY` 必须填。
- 改完 `.env` 后需**重启服务**生效。

> ⚠️ 注意：本项目核心逻辑依赖模型的**结构化 JSON 输出**（`{reply, action, task, appointment}`）与流式响应。若换的模型输出不稳定，任务创建可能受影响。推荐先用默认模型跑通，再切换实验。

---

## 四、部署启动（Step by Step）

> 🚀 **一键启动**：只需一个命令，脚本会自动创建环境、装依赖、生成配置、启动服务——不用手动建库、不用手动装环境。

```bash
git clone https://github.com/EthanHe2014/OpenMemo.git   # 或下载解压
cd OpenMemo
./start.sh
```

首次运行会自动：
1. 创建虚拟环境 `.venv`（不存在才建）
2. 安装全部依赖（`requirements.txt`）
3. 从 `.env.example` 生成 `.env`（不存在才生成）
4. 启动后端服务（端口 `18890`，自动建好数据库 `data/openmemo.db`）

看到 `Application startup complete` + `[调度器] 已启动` 即成功。

---

### 只需一步：配置你的凭据

先跑一次 `./start.sh` 生成 `.env`，然后编辑它填入真实凭据，再重启即可：

```bash
nano .env   # 或 vim / 文本编辑器
```

`.env` 里需要填：
- `AI_API_KEY`：**必填**，你的 AI 接口 Key（见下方 [配置你自己的 AI](#配置你自己的-ai-base-url--api-key--模型)）。
- `AI_BASE_URL` / `AI_MODEL`：可选，默认 `https://yuanyuaicloud.cn/v1` + `glm-5.2`；想用自己的服务就改。
- `TAVILY_API_KEY`：可选，用于每日新闻（不填则新闻功能不可用）。
- `FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `FEISHU_VERIFICATION_TOKEN` / `FEISHU_ENCRYPT_KEY`：可选，飞书机器人凭据（不填则飞书不可用）。
- `FEISHU_DEFAULT_USER`：接收提醒的用户 open_id（用于主动推送）。
- `SERVER_PORT`：默认 `18890`。

> 以后每次启动：只要 `./start.sh` 即可，环境已建好会秒起，不会重复安装。

### 手动方式（不用一键脚本）

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env          # 然后编辑 .env
.venv/bin/python -u -m openmemo.server
```

### 打通消息渠道（飞书 / 钉钉 / 企业微信 / iOS）

OpenMemo 支持多种入口，选一个（可多选）：

| 渠道 | 难度 | 说明 | 指南 |
|------|------|------|------|
| **飞书** | ⭐ 最易（内置支持） | 开箱即用，文字+语音，支持主动推送 | [飞书接入指南](docs/setup-feishu.md) |
| **iOS App** | ⭐⭐ 需 Xcode | 手机 App，但未上架 App Store，需 Mac + Xcode 构建 | [iOS 使用指南](docs/setup-ios-xcode.md) |
| **钉钉** | ⭐⭐⭐ 需加适配模块 | 企业内部应用机器人，需新增 dingtalk.py | [钉钉接入指南](docs/setup-dingtalk.md) |
| **企业微信** | ⭐⭐⭐ 需加适配模块 | 自建应用，XML+AES 回调，需新增 wecom.py | [企业微信接入指南](docs/setup-wecom.md) |

以飞书为例（最快）：

```bash
cloudflared tunnel --url http://localhost:18890
```

把输出的 `https://xxx.trycloudflare.com` 填到飞书开放平台的**事件订阅地址**：

```
https://xxx.trycloudflare.com/webhook/feishu
```

> ⚠️ 快速隧道重启后 URL 会变，需要在对应平台后台更新订阅地址；iOS App 的 `baseURL` 也需要同步更新成最新隧道地址。

### 在飞书里使用 / 手机用 App

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

**Q：模型一定要用 glm-5.2 吗？**
不必。AI 接口完全可配置：在 `.env` 里改 `AI_BASE_URL`、`AI_API_KEY`、`AI_MODEL` 即可用任何 OpenAI 兼容服务（前提是该服务支持流式响应）。`glm-5.2` 只是默认值。

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

- 依赖一个可用的、支持流式的 OpenAI 兼容 AI 接口（默认 `https://yuanyuaicloud.cn/v1`，模型 `glm-5.2`，可在 `.env` 换成自己的）。
- 语音播报依赖本机 `edge-tts` + `afplay`，需要能访问 Edge TTS 服务。
- 每日新闻依赖 Tavily API Key。

# OpenMemo

AI 驱动的个人语音助手 —— 会对话、会记任务、会在你需要的时候主动提醒你。

OpenMemo 的核心是一个**可配置的大模型对话 AI**：任何 OpenAI 兼容的接口都能接（BaseURL + API Key + 模型名都由你在设置向导里填）。它的特别之处在于：**AI 负责所有"思考"和"说话"**，服务端只有一个轻量程序，负责把 AI 的结构化输出解析出来、存任务、按时间把 AI 写的提醒念出来。

> 📱 **使用方式**：本项目通过 **iOS App** 使用（Web 仪表盘 `/` 辅助查看）。无飞书 / 钉钉 / 企业微信 等 IM 通道——纯自家 App。

---

## 一、它能做什么

- 🗣️ **自然对话**：像真人一样聊天、追问、确认，由 AI 自主决定问什么、怎么问。
- 📝 **记任务**：你说"明天开会"，它自动记下；你说"每天提醒我写作业"，它建立每日循环提醒。
- ✈️ **出行提醒**：你说"明天13:00赶飞机"，它会主动问你到机场要多久、国内还是国际，然后**反推出出发提醒时间**（提前留出堵车/值机/安检缓冲），到点念给你听。
- 📰 **每日新闻**：你说"每天给我看新闻"，它每天到点搜索当天新鲜新闻播给你。
- 📅 **带日程的重复任务**：暑假作业按天分配，每天提醒当天具体内容。
- 🔈 **语音播报**：Mac mini 扬声器用中文读出提醒（Edge TTS）。
- 📱 **iOS App + 本地通知**：手机上看任务、对话、管理会话（侧边栏）；提醒时间到了手机也会弹本地通知（即使不在 Mac 旁）。> ⚠️ 尚未上架 App Store，需 Mac + Xcode 源码构建（见 [iOS 使用指南](docs/setup-ios-xcode.md)）。

### 智能任务类型

| 类型 | 触发场景 | 行为 |
|------|----------|------|
| `normal` | 普通任务（开会/打电话/买东西） | 到点提醒 |
| `travel` | 出行事件（赶飞机/高铁） | AI 问清出发时间、到站耗时、国内/国际 → 反算出发提醒时间 |
| `news` | 每日新闻 | 每天到点搜索当天实时新闻并播报 |
| `schedule` | 带日程的重复任务（暑假作业） | 每天提醒当天具体内容，内容随日期变化 |

---

## 二、快速开始（就一条命令）

> 🚀 **只需一个命令，别的都不用你管。**

```bash
git clone https://github.com/EthanHe2014/OpenMemo.git   # 或下载解压
cd OpenMemo
./start.sh
```

`./start.sh` 会自动完成：

1. **检查 Python 3.10+**（没有会提示你安装）
2. **创建虚拟环境** `.venv`（仅首次）
3. **安装全部依赖**（仅首次）
4. **进入交互式设置向导**（首次或配置不完整时自动出现）——它会`一步一步`带你：
   - **选择 AI 提供商**：OpenAI / DeepSeek / 智谱 / Moonshot / Ollama（本地）/ 自定义，接口地址自动预填、可修改
   - **填入 AI 接口密钥 + 模型名** —— 密钥输入时不回显，不怕被偷看
   - **选择新闻搜索服务**（可选）：Tavily / Brave / Serper / 自定义 / 不配置
   - **服务端口 / 语音音色** 等偏好
5. **启动服务**（端口 `18890`，首次启动自动建好数据库 `data/openmemo.db`）

看到 `Application startup complete` + `[调度器] 已启动` 即成功。**服务会打印一份「接下来这样用」的指引**——浏览器打开 `http://localhost:18890/` 的仪表盘就能立刻对话测试。

**以后每次启动**：直接 `./start.sh` 即可，配置已保存，环境秒起，不再重复安装、不再重复询问。

---

## 三、配置你自己的 AI（设置向导）

OpenMemo 的对话大脑可以是**任何 OpenAI 兼容的模型服务**，不局限于某一家、也没有内置默认模型。运行一次 `./start.sh`，设置向导会先让你**选择 AI 提供商**（OpenAI / DeepSeek / 智谱 / Moonshot / Ollama 本地 / 自定义），选好后自动预填对应接口地址（可改），再引导你填三样东西：

| 配置项 | 说明 |
|--------|------|
| `AI_BASE_URL` | 你的模型服务接口地址，通常是 `.../v1` |
| `AI_API_KEY` | 你的接口密钥（输入时不回显） |
| `AI_MODEL` | 你的模型名 |

- 接口只要**兼容 OpenAI 的 `/chat/completions` 且支持流式（stream）响应**即可。
- **没有任何默认模型、默认地址、默认密钥**——这三项不填服务不会启动。
- 想改配置，随时重跑向导：
  ```bash
  python setup.py          # 走一遍：改 AI / 搜索 / 偏好
  python setup.py --reset  # 清空旧值，从零配
  ```
- 配置保存在 `.env`（已 gitignore，不会泄露到仓库）。改完 `setup.py` 里的值后**重启服务**生效。

> ⚠️ 本项目的核心逻辑依赖模型**稳定的结构化 JSON 输出**（`{action, task, appointment, reply}`）与**流式响应**。若换的模型输出不稳定，任务创建可能受影响。

---

## 四、架构

**AI 自主架构**（2026-08 新版）：

```
iOS App
   │  发送消息（/api/chat）
   ▼
OpenMemo 服务端（FastAPI）
   │  【唯一行为逻辑：把消息交给 AI，解析 AI 返回的 JSON】
   │  1. 把"用户消息 + 历史 + 当前时间"发给你的 AI 接口
   │  2. AI 返回 { action, task{time, reminder_text, ...}, appointment{at, read_aloud}, reply }
   │  3. 服务端 ①原样回复 AI 的话 ②把任务/提醒存进 SQLite 并按时间调度
   │  4. 到点 → 把 AI 写的 reminder_text 用 Edge TTS 生成语音 → Mac 扬声器播报
   ▼
iOS App（任务列表 / 提醒状态 / 本地通知） / Mac 扬声器
```

- **AI 全权负责对话**：问什么、怎么问、是否放弃追问、写什么样的话，全部由 AI 自己决定。
- **服务端不做任何"话术/模板/槽位填充"**：它只负责解析 AI 的 JSON、存任务、按时播报。
- **模型完全可配置**：通过设置向导填入 BaseURL / API Key / 模型名，任意 OpenAI 兼容接口都能用。

### 技术栈

| 组件 | 技术 |
|------|------|
| 服务端 | Python 3.10+ + FastAPI |
| AI | 任意 OpenAI 兼容接口（可配置，无默认） |
| 实时新闻 | 可配置的新闻搜索 API（向导中自选提供商，可选） |
| TTS（文字转语音） | Edge TTS（zh-CN-XiaoxiaoNeural） |
| 存储 | SQLite |
| 调度 | APScheduler |
| 消息入口 | iOS App（REST API） |
| 语音输出 | Mac mini 扬声器（afplay） |
| 手机端 | SwiftUI iOS App（`OpenMemoApp/` 子目录，同仓库） |

---

## 五、项目结构

```
OpenMemo/
├── README.md
├── requirements.txt      # 依赖清单
├── start.sh              # 一键启动：环境 + 依赖 + 设置向导 + 启动
├── setup.py              # 交互式设置向导（配 AI / 搜索 / 偏好）
├── .env.example          # 配置模板（空值；真实配置由 setup.py 生成 .env）
├── openmemo/
│   ├── __init__.py
│   ├── server.py         # FastAPI 服务 + 全部 REST API
│   ├── ai.py             # AI 接口接入 + SYSTEM_PROMPT（AI 的"人设"）
│   ├── conversation.py   # 核心：把消息交给 AI，解析 JSON，原样回复
│   ├── scheduler.py      # APScheduler 提醒调度 + 按任务类型执行
│   ├── tasks.py          # 任务/会话 的 SQLite 存取
│   ├── voice.py          # Edge TTS 生成语音 + Mac 扬声器播放
│   └── config.py         # 配置读取（.env，纯环境变量，无硬编码密钥）
├── data/                 # SQLite 数据库 + 音频缓存（自动创建）
├── OpenMemoApp/          # iOS + Mac 客户端（SwiftUI，同仓库）
│   ├── OpenMemoApp.xcodeproj
│   └── OpenMemoApp/
│       ├── Views/        # 聊天 / 任务 / 设置界面
│       ├── ViewModels/   # 任务轮询 + 提醒横幅逻辑
│       ├── Networking/   # REST API 客户端
│       └── Services/     # 本地通知
├── tests/
│   └── test_tasks.py
└── docs/
    ├── mvp-flow.md            # MVP 流程说明
    ├── setup-ios-xcode.md     # iOS App（Xcode）使用指南
    └── SMART-AI-CHANGES.md    # AI 架构变更记录（内部开发）
```

> 📱 **客户端就在本仓库**：`OpenMemoApp/` 子目录（SwiftUI，零外部依赖）。无需单独克隆。
>
> ⚠️ **iOS App 尚未上架 App Store**——需要一台 Mac 安装 Xcode，用源码构建到模拟器或真机运行。详见 [iOS 使用指南（Xcode）](docs/setup-ios-xcode.md)。

---

## 六、部署到服务器（可选）

`start.sh` 默认在本机前台运行（Ctrl+C 停止）。要长期在服务器/后台跑：

```bash
# 方式一：nohup 后台运行
nohup ./start.sh > openmemo.log 2>&1 &

# 方式二：或直接用虚拟环境跑（配置好 .env 之后）
.venv/bin/python -u -m openmemo.server > openmemo.log 2>&1 &
```

服务默认监听 `0.0.0.0:18890`（可在设置向导里改端口）。手机用 App 时，要么用隧道把端口暴露到公网，要么让手机与 Mac 在同一局域网用 `http://<Mac的IP>:18890` 直连。

### 手机用 App（iOS）

后端跑起来后，iOS App 通过 REST API 连接你的服务：

1. 若想手机在公网访问后端，用隧道暴露本机端口（本地模拟器则无需）：
   ```bash
   cloudflared tunnel --url http://localhost:18890
   ```
2. 打开 `OpenMemoApp/`（本仓库子目录），在 App 的**设置页**里把服务器地址改成你的服务地址（隧道 URL 或局域网 IP；模拟器可用 `http://127.0.0.1:18890`）。
3. 用 Xcode 构建运行到模拟器或真机（详见 [iOS 使用指南](docs/setup-ios-xcode.md)）。

⚠️ 快速隧道重启后 URL 会变，需要同步更新 App 的 `baseURL`。

---

## 七、使用指南（Step by Step）

iOS App 就是你与 OpenMemo 对话的入口。

### 🗣️ 先跟它打个招呼

在 App 对话框里发：
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
   > "该出发去机场啦。请检查好护照、签证和登机牌，带齐行李，路上注意安全！"

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

## 八、API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | Web 仪表盘（辅助查看） |
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

## 九、数据模型

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

---

## 十、常见问题

**Q：为什么要设置向导？不能直接跑吗？**
OpenMemo 需要至少一个可用的 AI 接口（BaseURL + Key + 模型）才能对话与建提醒。首次运行时 `./start.sh` 会自动弹出设置向导带你配好——之后就不用再配了。

**Q：AI 不创建任务怎么办？**
服务端内置了"承诺就必须落地"规则：AI 一旦向你确认提醒时间，同一轮就必须返回创建任务的动作，服务端才会真正调度。若仍遇到"说了但不建"：
1. 检查服务日志是否有 `[调度器] 已安排任务 X`；
2. 确认你配置的模型**输出稳定的 JSON**（设置向导里填的模型名是否正确）；
3. 确认模型服务**支持流式响应**。

**Q：App 连不上？**
基本是隧道 URL 变了。把 `OpenMemoAPI.swift` 的 `baseURL` 更新成最新隧道地址（局域网或模拟器直连请用对应 IP）。

**Q：Mac 没声音？**
检查系统输出设备是不是 Mac 自带扬声器（ToDesk 等远程工具会挂虚拟声卡抢占输出）。

---

## 十一、免责 / 依赖

- 需要你配置一个**支持流式的 OpenAI 兼容 AI 接口**（本项目不内置、不默认任何模型/密钥）。
- 语音播报依赖本机 `edge-tts` + `afplay`，需要能访问 Edge TTS 服务。
- 每日新闻可选外部搜索 API（在设置向导里选择提供商并填入密钥；不配置则新闻由 AI 生成）。

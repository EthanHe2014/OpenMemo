# OpenMemo — 功能总览 & 更新日志

> AI 语音助手 + 任务/提醒管理。服务端（Python/FastAPI）+ 客户端（SwiftUI，Mac Catalyst + iPhone）。

---

# 一、功能总览 (FEATURES)

## 🧠 核心能力

### 1. 对话（AI 聊天）
- 与 DeepSeek 模型自然对话（`.env` 配置，无内置默认值，防止泄露）
- 会话管理：新建 / 历史列表 / 删除（侧边栏）
- **AI 回复自动朗读**：Edge TTS `zh-CN-XiaoxiaoNeural`，与提醒同声
  - 回复文本即时显示，语音后台播放（不阻塞）
  - 新播放自动打断旧播放；录音时自动停止（防回声）

### 2. 语音输入（STT）
- 麦克风按钮 🎤：点击开始，实时中文转写（SFSpeechRecognizer zh-CN）
- **静音 2 秒自动发送**；USB 麦克风可用
- 权限首次点击时才申请；每次会话全新音频引擎（稳定不崩）

### 3. 任务与提醒
- AI 对话中直接创建：待办事项 + 提醒时间
- 重复规则：每日 / 每周 / 每月 / 工作日 / 自定义重复（自动重新武装，不产生重复行）
- 提醒触发：Mac 语音朗读（Edge TTS）+ macOS 通知横幅 + 手机本地通知
- 状态体系（简化版）：**待办 / 已完成 / 已取消**（提醒触发后任务自动标记"已完成"）
- 手动管理：勾选完成、取消、删除、重新打开

### 4. 一致性看护（Watchdog）
- 每 60 秒扫描最近 24h 对话 vs 任务库
- **自动修复**：重复任务自动删除（保留第一个）、过期未提醒任务自动取消
- 承诺未落地 → 生成告警；App 内橙色横幅展示（24h 去重）

### 5. 界面（SwiftUI）
- 任务页：统计卡片（待办 / 今日提醒 / 已完成）+ 状态分组 + 相对时间
- 聊天页：欢迎卡片 + 可点击建议语 + 渐变头像 + 打字动画
- 设置页：Logo 头图 + 连接测试 + 使用提示
- 全部使用 Apple SF Symbols（无 emoji）；品牌元素 = 橙色→粉色渐变 sparkles Logo
- 输入框：回车 = 发送，Ctrl+回车 = 换行

## 🏗️ 架构

```
OpenMemo/
├── openmemo/          # 服务端 (Python/FastAPI)
│   ├── server.py      # HTTP API (端口 18890)
│   ├── conversation.py# AI 对话 + 任务动作执行（AI 全自主）
│   ├── ai.py          # DeepSeek 调用 (JSON 输出)
│   ├── tasks.py       # 任务/会话/提醒 DB 管理 (SQLite)
│   ├── scheduler.py   # 提醒调度 + 看护启动
│   ├── watchdog.py    # 对话 vs 任务 一致性看护
│   └── voice.py       # Edge TTS + 播放/打断 + 通知
├── OpenMemoApp/       # 客户端 (SwiftUI, xcodegen 生成工程)
│   ├── Views/         # 聊天/任务/设置/输入框
│   ├── ViewModels/    # ChatViewModel / TaskListViewModel
│   ├── Services/      # VoiceInputManager (STT) / OpenMemoAPI
│   └── Models/        # Task / ChatSession 等
├── scripts/           # 测试脚本 (test_watchdog.py 等)
├── docs/              # 设计文档
├── data/              # SQLite DB + TTS 音频缓存
└── start.sh           # 一键启动
```

## 🔌 API 速览

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/chat` | 聊天（`speak:true` 自动朗读回复）|
| POST | `/api/stop-speak` | 打断当前语音播放 |
| GET | `/api/tasks` | 任务列表 |
| POST | `/api/tasks` | 创建任务 |
| PATCH | `/api/tasks/{id}` | 更新任务 |
| DELETE | `/api/tasks/{id}` | 删除任务 |
| GET | `/api/reminders` | 提醒列表 |
| GET | `/api/alerts` | 看护告警 |
| GET | `/api/sessions` | 会话列表 |
| GET | `/api/conversations/{id}` | 对话历史 |
| DELETE | `/api/sessions/{id}` | 删除会话 |
| GET | `/api/health` | 健康检查 |

## 🚀 快速开始

```bash
./start.sh          # 一键启动（需先配置 .env：AI_BASE_URL / AI_MODEL / API_KEY / TTS_VOICE）
```

## ⚠️ 已知注意事项

- **构建 Mac App 必须用** `-destination 'platform=macOS,variant=Mac Catalyst'`：
  `platform=macOS` 会静默产出 iphoneos 产物（跑的是旧包）
- App 连服务端：模拟器/Mac 直连 `http://127.0.0.1:18890`；手机连公网 IP
- Git 推送需走本地代理：`git -c http.proxy=http://127.0.0.1:7897 ... push`
- 服务端重启：`lsof -ti tcp:18890 | xargs kill` 后 `nohup .venv/bin/python -u -m openmemo.server`

---

# 二、更新日志 (CHANGELOG)

## v0.6 — 2026-08-13：AI 回复朗读 + STT 稳定化

### 新增
- **AI 回复自动朗读**：聊天中每条 AI 回复由服务端 Edge TTS（`zh-CN-XiaoxiaoNeural`）生成并播放——与提醒完全同声。
  - 播放为后台任务：回复文本即时返回，不阻塞聊天 UI
  - 新播放自动打断上一条（防止语音叠加）
  - 新增 `POST /api/stop-speak`：App 点麦克风录音时先打断播放，防止回声
- **STT 语音留言**（麦克风按钮 🎤）：USB 麦克风实时转写（zh-CN）+ 静音 2 秒自动发送
  - 权限在首次点击麦克风时才申请（不再启动时申请，避免卡死）

### 修复
- **STT"只能用一次"的终极修复**：每次语音会话全新 `AVAudioEngine` + 全新 recognition request，结束后彻底销毁（`8d3013b`）。复用引擎导致的 `nullptr == Tap()` 崩溃彻底消除
- Swift 6 隔离崩溃系列（Catalyst 血泪）：
  - tap 闭包必须 `@Sendable` 且语法正确（`{ @Sendable (buffer, _) in }`，修饰整个闭包而非参数）
  - `AVAudioEngine.start()` 必须后台线程（`Task.detached`），主线程调用会卡死 App
  - SwiftUI Button 手势回调不在 MainActor 执行器 → 按钮动作全部包进 `Task { @MainActor }`
  - Swift 6 `sending` 检查：tap 安装在 `nonisolated` 静态方法，引擎捕获走 Sendable 盒子
- 输入框占位提示与语音转写文字重叠：placeholder 改用「实际显示文字」判断（`d91a779`）
- 构建坑（重要）：xcodegen 重新生成后 `-destination 'platform=macOS'` 会产出 iphoneos 产物
  ——Mac App 实际在跑旧包。正确命令见上文「已知注意事项」

## v0.5 — 2026-08-12：对话/任务一致性看护（Watchdog）

### 新增
- **Watchdog 看护进程**（每 60 秒）：
  - 扫描最近 24h 对话 vs 任务库，发现"承诺了但没落地"的任务
  - **自动处理**：重复任务自动删除（保留第一个）、过期未提醒任务自动取消
  - 告警写入 alerts 表，App 内橙色横幅展示（去重 24h）
  - 一键测试：`python -m openmemo.watchdog --once` / `scripts/test_watchdog.py`
- **TTS 不读 emoji**：朗读前剥离表情符号（显示保留原文）

### 修复
- 测试脚本忽略环境 SOCKS 代理（`trust_env=False`），避免缺 socksio 报错

## v0.4 — 2026-08-11：App UI 全面精修

### 变更
- **状态简化**：只保留 待办 / 已完成 / 已取消（移除易混淆的"已执行"）；提醒触发后任务自动标记"已完成"
- 任务页：统计卡片（待办 / 今日提醒 / 已完成）+ 状态分组 + 相对时间
- 聊天页：欢迎卡片 + 可点击建议语 + 渐变头像 + 打字动画
- 设置页：Logo 头图 + 自动连接测试 + 使用提示
- **全部 Apple emoji 换成 SF Symbols**（保留自创橙色→粉色渐变 sparkles Logo）
- 输入框：回车=发送、Ctrl+回车=换行（硬件键盘）

### 修复
- 输入框光标与 placeholder 重叠、光标隐藏等系列问题

## v0.3 — 2026-08-10：AI 任务管理能力 + 核心缺陷修复

### 新增
- **AI 获得任务管理权限**：对话中可直接创建任务、安排提醒（每日/每周/每月/工作日/重复）、取消/删除/完成任务
- 重复任务自动重新武装（同一任务 ID，不产生重复行）
- 提醒触发 → 任务自动标记已完成

### 修复
- 提醒可靠性：`response_format=json_object` + 非流式请求
- AI 时间解析：支持 HH:MM / MM-DD / 斜杠分隔等多种格式
- AI 动作与回复文本不一致时以动作结果为准（跨字段安全网）

## v0.2 — 2026-08-09：仓库合并

- OpenMemo（服务端）与 OpenMemoApp（iOS/Mac 客户端）合并为单一仓库
- AppIcon、Catalyst 设置、签名 Team ID 配置完成

## v0.1 — 早期：基础版

- 服务端：FastAPI 任务/提醒/对话 API + 调度器（Edge TTS 语音提醒 + macOS 通知）
- App：任务列表、对话界面、设置
- 一键启动：`./start.sh`（无默认模型/API，全部从 `.env` 读取）

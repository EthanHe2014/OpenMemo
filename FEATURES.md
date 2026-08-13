# OpenMemo 功能总览 (FEATURES)

> AI 语音助手 + 任务/提醒管理。服务端（Python/FastAPI）+ 客户端（SwiftUI，Mac Catalyst + iPhone）。

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
- 状态体系（简化版）：**待办 / 已完成 / 已取消**
  - 提醒触发后任务自动标记"已完成"
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

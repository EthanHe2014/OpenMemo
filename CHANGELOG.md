# OpenMemo — 功能总览 & 更新日志

> AI 语音助手 + 任务/提醒管理。服务端（Python/FastAPI）+ 客户端（SwiftUI，Mac Catalyst + iPhone）。

---

# 二、更新日志 (CHANGELOG)

## v1.2.1 (2026-09-06) — 情绪落库 + 时间戳精简

### 修复
- **情绪/说话人/声音事件落库**：conversations 表新增 `emotion` / `event` / `speaker` 列（启动自动迁移），历史接口返回这些字段——翻旧聊天记录时情绪标签仍然可见（旧消息无法回填，新消息从本次起全部保留）
- **历史加载丢字段**：App 加载历史时不再丢弃 emotion/speaker（原来只靠解析 `[名字]` 前缀，情绪直接丢失）

### 优化
- **时间戳胶囊精简**：只在「跨天」或「与上一条间隔 ≥30 分钟」时显示；跨天时自动带日期（今天只显时间 / 昨天 / M/d），正常对话不再刷屏

---
## v1.2.0 (2026-08-31) — 语音情绪识别（SenseVoice）

### 新增：本地语音情绪识别（完全离线，SenseVoice via sherpa-onnx）
- **情绪检测**：说话时本地识别情绪（高兴/悲伤/生气/恐惧/惊讶/中性），识别结果注入 AI 上下文，AI 会直接告诉你"你听起来有点生气/挺平静的"，并按情绪调整语气（生气先安抚、难过温柔些、开心一起开心）
- **声音事件**：检测笑声/哭声/咳嗽/掌声等声音事件（文本里看不到的东西），AI 会接梗、关心咳嗽、安慰哭声
- **反讽识别**：高置信规则 —— 庆祝类文字（"太棒了""满分"）+ 悲伤/生气/平静声音 → 直接点破"这话听着像反话"；双向验证（开心文字+悲伤声音 / 悲伤文字+开心声音都能识破）
- **气泡情绪标签**：消息气泡说话人名旁显示彩色情绪标签（高兴绿/悲伤蓝/生气红/恐惧紫/惊讶橙/中性灰）

### 新增：其他
- **唤醒打断**：TTS 播放中说「小麦小麦」→ 立即停掉当前语音，应答"我在！"（录音在静默中开始，无 TTS 尾巴污染）
- **唤醒词身份**：AI 知道「小麦小麦」是它的另一个名字，听到不纠正；且**绝不自己说出唤醒词**（防回声循环）
- **本地模型降级**：云端 AI 故障时自动降级到本地 DeepSeek-R1（14B，CPU），永不"服务不可用"
- **侧边栏隐私**：只显示干净标签（"Ethan 的聊天"/"Michelle 的聊天"/一个"匿名聊天"），永不显示消息内容；顶部标题同样干净
- **5 分钟时间戳**：聊天消息顶部居中时间戳，每 5 分钟显示一次
- **侧边栏暗色极光 UI**：灰盒子 → 紫色极光玻璃拟态

### 修复（关键）
- 情绪传递链路 3 个 bug：CAF 格式不兼容（App 录音是 CAF，接口只认 WAV）、ChatRequest.CodingKeys 漏掉 emotion 字段（编码器静默丢弃）、SenseVoice 需要 ≥3.5s 音频（短录音永远 UNKNOWN）
- 看护 bling 循环：同一告警每 60 秒弹通知（131 次）→ 只对新问题通知 + 落地窗口放宽到 ±3min
- 隐私：任务/提醒/告警按说话人隔离（owner 过滤，跨用户 403）；AI 上下文不再泄露别人的任务
- 崩溃：时间戳视图越界崩溃（ForEach 快照回查 live 数组）→ 用快照元素 + 边界检查
- SI：短录音被 2.5s 裁剪吃光 → 回到 1.5s 裁剪
- 版本：全面同步 1.2.0（Xcode 工程经 xcodegen 重新生成，含 schemes 配置）

---
## v1.1.0 (2026-08-28) — 说话人识别（SI）上线

### 新增：说话人识别（全部在 App 内完成，无需终端 / Xcode / 重新编译）
- **登记向导**：6 步流程 —— 输入名字 → 3 次真实录音（点开始 → 说话 → 点停止，随时可重录）→ 训练页 → 完成页；下一步在样本保存后才解锁
- **App 内训练**：Create ML（MLSoundClassifier）直接在 App 里训练，模型存 Documents，即训即用；支持「重新训练模型 / 训练模型」文案自适应（名字已存在与否）
- **单人也能训练**：自动生成合成「背景噪音」类别满足 Create ML 至少两类的要求；识别时过滤该类别
- **自动识别说话人**：每次语音留言用 SoundAnalysis 识别，置信度 ≥ 0.6 生效；消息气泡底部显示说话人名字
- **说话人专属会话**：识别后消息进入 `speaker_<名字>` 会话，AI 上下文按人隔离，互不泄露
- **服务端身份 + 隐私**：/api/chat 接收 speaker 字段 → AI 知道对话对象；已识别用户可见自己的任务/提醒；未识别视为访客，不透露任何已登记用户信息，并建议训练语音或匿名对话
- **唤醒词体验**：唤醒后 4 秒思考时间（无语音才关闭），说话后静音 2.5 秒发送

### 修复
- Catalyst + USB 麦克风录音崩溃（EXC_BAD_ACCESS / EXC_BREAKPOINT）：engine 主线程启动 → 后台启动；双引擎抢麦 → 录音前暂停唤醒监听；AVAudioFile 写文件异常 → 改 AVAudioRecorder；SoundAnalysis 读 WAV 容器静默失败 → 改 CAF 容器（A/B 验证）
- CreateML 仅 macOS 可用 → 条件编译，iOS 构建恢复

### 版本
- App：1.1.0 (build 11)；服务端 / 仪表盘：1.1.0

---

# 三、功能总览 (FEATURES)

## 🧠 核心能力

### 0. 说话人识别（SI，v1.1.0）
- App 内登记：输入名字 → 3 次录音 → App 内训练（Create ML）→ 即训即用
- 自动识别语音留言的说话人，气泡底部标注；消息路由到说话人专属会话
- 服务端身份 + 隐私：本人看自己的任务，访客不泄露任何隐私并获训练建议
- 单人可训练（自动背景噪音类）；识别混了可重录重训

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
- **免手唤醒（「小麦小麦」）**：耳朵按钮开启后持续监听，说唤醒词 → 电脑应答「我在！」→ 接着直接说命令即可（麦克风全程不断）；唤醒词与应答绝不会变成消息内容；说完自动重新挂起监听

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

## v0.7 — 2026-08-13：「小麦小麦」唤醒词 + AI 提示词重写 + 任务执行层

### 新增（客户端）
- **免手唤醒**：App 启动即监听「小麦小麦」，应答「我在！」后直接说话，全程免手（无按钮）
- 静音 2.5 秒自动发送；唤醒词/应答绝不算 STT 内容
- **会话代数（epoch）隔离**：旧会话迟到回调不再误杀新会话——修复「唤醒后 STT 接不上」

### 新增（服务端 · V0.7 执行层重构）
- **AI 提示词重写**（`openmemo/prompts.py`）：420+ 场景关键词目录（基础提醒/健康/出行/
  周期/动态信息/学习/工作/复杂多步骤/杂务/查询），信息不全自动反问（一次一问、带选项）
- **任务新契约**：JSON 含 time + recurring + **what_to_do**（到点执行的动作指令，不显示在 UI）
- **到点执行引擎**：what_to_do → AI 执行引擎（EXECUTOR_PROMPT）→ 播报结果并存档；
  需实时信息时返回 need_search → 系统搜索（SEARCH_PROVIDER）→ AI 基于资料播报
- **跟进机制**："若10分钟没回复再提醒"自动创建跟进任务（skip_if_user_replied 跳过；
  代码级防无限循环）
- **中文相对时间解析**：今天/明天/X分钟后/半小时后/下周三/下午3点/晚上8点半等
- **重复规则补全**：每周一三五、每N小时/天、每天多时间点（自动拆分任务）
- **兜底机制**：执行 AI 失败/超时 → 念 reminder_text/任务内容，绝不静默；
  提醒触发立即标记，看护不再误取消执行中任务

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

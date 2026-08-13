# OpenMemo 更新日志 (CHANGELOG)

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
  ——Mac App 实际在跑旧包。正确命令见 `docs/`，务必用
  `-destination 'platform=macOS,variant=Mac Catalyst'`

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

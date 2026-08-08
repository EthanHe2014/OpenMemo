# OpenMemo

AI 驱动的个人语音助手，带记忆与主动提醒能力。

## 架构

- **输入**：飞书机器人（文本 + 语音消息，内置 STT 语音识别）
- **AI**：glm-5.1（自定义接口）—— 负责意图识别、槽位补全与对话
- **输出**：Mac mini 扬声器（Edge TTS → afplay）
- **存储**：SQLite
- **调度**：APScheduler 任务提醒

## 核心流程

```
用户 → 飞书消息 → Webhook → AI (glm-5.1) → 任务/回复 → Edge TTS → 扬声器
```

1. 用户通过飞书发送文本/语音消息
2. Mac mini 接收 Webhook，飞书提供语音转文字（STT）
3. AI 识别意图，提取任务信息（时间、内容、优先级）
4. 信息不完整时 → AI 主动追问补全
5. 任务存入 SQLite，调度器设定提醒
6. 到提醒时间 → Edge TTS 生成语音 → Mac mini 扬声器播报

## MVP 范围

### 已实现
- 飞书文本/语音输入
- AI 意图识别 + 槽位补全
- 任务增删改查 + 定时调度
- 信息不完整时的追问
- Mac mini 扬声器语音播报
- 基础对话记忆
- 单用户模式

### 暂未实现（V2）
- 多用户支持
- 多设备切换
- 主动新闻推送
- 手机 App
- 兴趣衰减算法
- 环境感知

## 技术栈

| 组件 | 技术 |
|------|------|
| 服务端 | Python 3.14 + FastAPI |
| AI | glm-5.1（自定义接口） |
| STT | 飞书内置 |
| TTS | Edge TTS |
| 存储 | SQLite |
| 调度 | APScheduler |
| 输入 | 飞书机器人 Webhook |
| 输出 | Mac mini 扬声器（afplay） |

## 部署启动

```bash
pip install fastapi uvicorn apscheduler edge-tts httpx
python -m openmemo.server
```

## 项目结构

```
OpenMemo/
├── README.md
├── requirements.txt
├── openmemo/
│   ├── __init__.py
│   ├── server.py          # FastAPI 服务 + 飞书 Webhook
│   ├── ai.py              # glm-5.1 接入
│   ├── tasks.py           # 任务管理 + SQLite
│   ├── scheduler.py       # APScheduler 提醒
│   ├── voice.py           # Edge TTS + 扬声器输出
│   ├── conversation.py    # 对话状态 + 记忆
│   └── config.py          # 配置
├── data/                  # SQLite 数据库 + 音频文件
├── tests/
│   └── test_tasks.py
└── docs/
    └── mvp-flow.md
```

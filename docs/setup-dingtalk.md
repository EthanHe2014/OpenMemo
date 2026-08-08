# 钉钉（DingTalk）接入指南

> 📌 **当前状态**：OpenMemo 目前内置了**飞书**通道；钉钉需要新增一个**通道适配模块**（与 `openmemo/feishu.py` 类似的 `dingtalk.py` + 一个 webhook 端点），代码量不大。本指南讲清楚钉钉机器人怎么建、事件怎么配、适配模块要写什么。
>
> 如果你只想要"开箱即用"，当前建议直接用飞书或 iOS App。若客户明确要求钉钉，按本文第 5 节补一个适配模块即可。

---

## 1. 钉钉机器人的两种形态

| 形态 | 适用 | 说明 |
|------|------|------|
| **企业内部应用机器人**（推荐） | 企业内部使用 | 在钉钉开放平台建应用，走企业内消息接收与回复 |
| 自定义机器人（Webhook 群机器人） | 群里推送告警 | 只能主动往群里推消息，**不能接收用户消息并回复**，不适合做对话助手 |

> ⚠️ 要做"能对话、能回复"的助手，必须用**企业内部应用机器人**。

## 2. 创建企业内部应用

1. 打开 [钉钉开放平台](https://open-dev.dingtalk.com/)（用企业管理员账号登录）。
2. **创建应用 → 企业内部应用**，填名称（如 "OpenMemo 助手"）和 Logo。
3. 创建后进入应用详情，拿到 **AppKey** 和 **AppSecret**。

## 3. 开启机器人能力

1. 应用详情 → **机器人** → 添加机器人，填机器人名称、头像、简介。
2. 记下机器人的 **RobotCode**（发消息时用）。

## 4. 配置消息接收（事件订阅）

1. 应用详情 → **事件与回调 → 添加事件**：
   - 选择 `机器人回调` 里的 **`机器人接收到消息`（`robot_robot_message_receive`）**。
   - 这个是接收用户发来的消息并能回复的关键事件。
2. **请求地址 URL** 填（钉钉要求 HTTPS）：
   ```
   https://你的隧道地址/webhook/dingtalk
   ```
   （隧道地址由 `cloudflared tunnel --url http://localhost:18890` 生成）
3. 配置 **加密/签名**：
   - `Token` 和 `AES_KEY`（加解密密钥）会生成，妥善保存 → 填入适配模块的配置。
   - **AES 加密方案**：钉钉用 AES 加解密消息体，需要写加解密逻辑（钉钉官方提供 SDK/示例）。

## 5. OpenMemo 需要新增的适配模块（钉钉）

在 `openmemo/` 新增 `dingtalk.py` 和 `server.py` 里加 `/webhook/dingtalk` 端点，核心逻辑：

```python
# openmemo/dingtalk.py（示意）
class DingTalkBot:
    def __init__(self, app_key, app_secret, robot_code, token, aes_key):
        ...
    def encrypt(self, text):  ...   # AES 加密（回应钉钉要求）
    def decrypt(self, data):  ...   # AES 解密（收到消息）
    def verify(self, headers): ...  # 验签（timestamp + sign）
```

```python
# server.py 里加（示意）
@app.post("/webhook/dingtalk")
async def dingtalk_webhook(request: Request):
    body = await request.json()
    if dingtalk_bot.verify(...):        # 验签
        text = dingtalk_bot.decrypt(...) # AES 解密出消息内容
        sender = ...                       # 发送者 staffId
        asyncio.create_task(_handle_message(sender, text))  # 复用现有 AI 对话逻辑
    return dingtalk_bot.encrypt("success") # 必须返回加密后的响应
```

> 好消息：对话/AI/任务/提醒的**核心逻辑全部复用**，钉钉只是新增一个"入口 + 出口"（收消息 → 喂给现有 `conversation.py`，把 AI 回复通过 `robot/.../messages` 接口发回）。参考 `feishu.py` 的写法即可。

## 6. 回复用户消息（机器人发消息）

拿到 AI 的回复后，调用钉钉机器人发消息接口：
- `POST /robot/robotMessages/send`（普通企业内部机器人）
- 需要 `RobotCode` + 接收者的 `staffId`，并对请求体做签名/加密

## 7. 权限与发布

- 应用详情 → **权限管理**：开通 `机器人发送消息`、`读取通讯录`（拿 staffId）等。
- 企业内部应用一般在企业内直接可用，通常**无需上架应用市场**，审核更快。

---

## 常见问题

**Q：钉钉机器人能像飞书那样"主动提醒"吗？**
- 可以。记录用户的 `staffId`，定时任务到点调用机器人发消息接口推送即可（参考飞书的 `FEISHU_DEFAULT_USER` 机制，钉钉对应 `staffId`）。

**Q：为什么推荐企业内部应用而不是"自定义群机器人"？**
- 群机器人只能单向推送，无法接收用户消息后由 AI 回复，做不了对话助手。

**Q：我没写代码，能用钉钉吗？**
- 需要补上述适配模块。若你希望我帮忙加一个可用的钉钉通道，告诉我，我可以照 `feishu.py` 写一个 `dingtalk.py` 并接上。

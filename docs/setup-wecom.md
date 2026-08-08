# 企业微信（WeChat Work / WeCom）接入指南

> 📌 **当前状态**：OpenMemo 目前内置了**飞书**通道；企业微信需要新增一个**通道适配模块**（与 `openmemo/feishu.py` 类似的 `wecom.py` + 一个 webhook 端点）。本指南讲清楚企业微信应用怎么建、回调怎么配、适配模块要写什么。
>
> 若你只想要"开箱即用"，当前建议直接用飞书或 iOS App。若客户明确要求企业微信，按本文第 5 节补一个适配模块即可。

---

## 1. 准备工作

- 一个**企业微信**（企业主体认证，个人号不行）。
- 管理员权限（在企业微信管理后台建应用、配回调）。

## 2. 创建自建应用

1. 登录 [企业微信管理后台](https://work.weixin.qq.com/wework_admin/frame)。
2. **应用管理 → 自建 → 创建应用**，填名称（如 "OpenMemo 助手"）、Logo、可见范围（哪些成员能用）。
3. 创建后进入应用，拿到：
   - **CorpID**（企业 ID，在"我的企业"里）
   - **AgentId**（应用 ID）
   - **Secret**（应用密钥，点"查看"）

## 3. 配置回调（接收消息）

这是"用户发消息 → AI 回复"的关键。

1. 应用详情 → **接收消息** → 设置 **API 接收**：
2. **URL** 填（企业微信要求 HTTPS）：
   ```
   https://你的隧道地址/webhook/wecom
   ```
   （隧道地址由 `cloudflared tunnel --url http://localhost:18890` 生成）
3. **Token** 和 **EncodingAESKey**：点"随机获取"生成，妥善保存。
4. 保存时会触发一次 **URL 验证**：企业微信会对你的 URL 发送一个带 `msg_signature`、`timestamp`、`nonce`、`echostr` 的 GET 请求。OpenMemo 需要实现回调验证逻辑来应答。

## 4. 开启 API 权限

应用详情 → **API 权限**，开通：
- `接收消息`（`messages`）
- `发送消息` / `应用消息推送`（机器人发消息给成员，用于回复和提醒）
- 必要时 `通讯录同步`（拿到成员的 `userid`）

## 5. OpenMemo 需要新增的适配模块（企业微信）

在 `openmemo/` 新增 `wecom.py` + `server.py` 里加 `/webhook/wecom`，核心逻辑：

```python
# openmemo/wecom.py（示意）
import hashlib, base64, xml.etree.ElementTree as ET
from Crypto.Cipher import AES  # pycryptodome

class WeComBot:
    def __init__(self, corp_id, agent_id, secret, token, aes_key):
        ...
    def verify_signature(self, msg_signature, timestamp, nonce, echostr): ...
        # 按 企业微信 官方算法：sha1(sort(token, timestamp, nonce, encrypt)) 比对
    def decrypt(self, encrypted): ...   # AES-CBC 解密出明文 XML
    def encrypt(self, reply_xml):  ...  # AES 加密回包 + 生成 msg_signature
```

```python
# server.py 里加（示意）
@app.get("/webhook/wecom")
async def wecom_verify(request: Request):  # URL 验证（GET echostr）
    # 验签通过后，解密 echostr 原样返回

@app.post("/webhook/wecom")
async def wecom_webhook(request: Request):  # 接收消息（POST）
    body_xml = await request.body()
    msg = wecom_bot.decrypt(body)                # 解密出 <Content>、<FromUserName>
    text, userid = parse_xml(msg)
    asyncio.create_task(_handle_message(userid, text))  # 复用现有 AI 对话逻辑
    return wecom_bot.encrypt("<xml><ToUserName>...</ToUserName><MsgType>text</MsgType><Content>success</Content></xml>")
```

> 对话/AI/任务/提醒的**核心逻辑全部复用**，企业微信只是新增"入口 + 出口"（收消息 → 喂给现有 `conversation.py`，把 AI 回复通过 `message/send` 接口发回）。参考 `feishu.py` 写即可。

## 6. 回复与主动提醒

- 拿 AI 回复后，调用企业微信 **应用消息推送** 接口：
  - `POST /cgi-bin/message/send`（需 `access_token` + `agentid` + `touser`）
- 主动提醒同理：到点调用 `message/send` 推送给成员（对应飞书的 `FEISHU_DEFAULT_USER`，企微用 `userid`）。

## 7. 测试与发布

- 企业微信自建应用**无需上架应用市场**，配置好回调 + 把应用加到"可见范围"即可在应用列表里使用。
- 用企业微信 App → 工作台 → 打开你建的 "OpenMemo 助手" → 发消息测试。

---

## 常见问题

**Q：企业微信回调验证失败？**
- 确认服务已启动且公网可访问（浏览器打开 `https://隧道地址/api/health` 应返回 ok）。
- 仔细核对 `Token`、`EncodingAESKey`、`CorpID` 与代码里一致；验签算法按官方规范实现（`sha1(sort(token, timestamp, nonce, encrypt))`）。

**Q：为什么企业微信比飞书麻烦？**
- 企微用 **XML + AES 加解密 + 双向验签**，比飞书的 JSON 复杂一些，需要引入 `pycryptodome`。核心对话逻辑不变。

**Q：没写代码能用吗？**
- 需要补上述适配模块。若你希望我帮忙加一个可用的企业微信通道，告诉我，我可以照 `feishu.py` 写一个 `wecom.py` 并接上。

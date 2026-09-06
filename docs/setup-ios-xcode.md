# iOS App 使用指南（基于 Xcode）

> ⚠️ **OpenMemo iOS App 尚未上架 App Store**，无法直接搜索下载。
> 需要一台 **Mac**，安装 **Xcode**，用源码构建运行到模拟器或真机。

---

## 1. 准备条件

- 一台 **Mac**（推荐 macOS 14+）
- 安装 **Xcode**（App Store 免费下载，或 `xcode-select --install` 装命令行工具）
- **Xcode 账号**（免费 Apple ID 即可跑模拟器；跑真机需要登录 Apple ID 并信任开发者证书）

## 2. 获取代码

iOS App 就在 OpenMemo 主仓库的 `OpenMemoApp/` 子目录里：

```bash
git clone https://github.com/EthanHe2014/OpenMemo.git
cd OpenMemo/OpenMemoApp
```

（`OpenMemoApp.xcodeproj` 已随仓库提交，直接用 Xcode 打开即可；如需重新生成工程文件，用 `xcodegen`：`brew install xcodegen && xcodegen generate`，配置见 `project.yml`。）

## 3. 配置服务器地址（关键）

App 通过 `Networking/OpenMemoAPI.swift` 里的 `baseURL` 连接后端：

```swift
// OpenMemoApp/Networking/OpenMemoAPI.swift
var baseURL = "https://你的隧道地址.trycloudflare.com"
```

把 `baseURL` 改成你后端（OpenMemo 服务）的公网地址：
- 本地开发：`http://localhost:18890`（模拟器可用；真机不行，真机要走局域网或隧道）
- 远程/真机：`https://你的隧道地址.trycloudflare.com`

> 也可以在 **App 的"设置"页** 直接填服务器地址（Settings 里有"服务器连接"和"测试连接"）。

## 4. 用 Xcode 打开并运行

1. 双击打开 `OpenMemoApp.xcodeproj`。
2. 顶部选择运行设备：
   - **模拟器**：选一个 iPhone 机型（如 iPhone 16 Pro）。
   - **真机**：把你的 iPhone 用数据线连 Mac，选它；首次需要到 `设置 → 通用 → VPN与设备管理` 信任开发者 App。
3. 点击 **运行（▶）**，等待构建完成。
4. App 启动后默认进入**全新对话**，底部有 3 个 Tab：
   - **对话**：和 AI 聊天（DeepSeek 风格，左上角 ☰ 打开历史会话侧边栏）
   - **任务**：查看/管理已创建的任务
   - **设置**：改服务器地址、测连接

## 5. 手动创建 Xcode 项目（可选）

如果不方便用 xcodegen，可手动操作：`File → New → Project → iOS App`，把所有 `.swift` 文件 + `Assets.xcassets` + `Info.plist` 拖进去，设置 `OpenMemoApp` 为入口 SwiftUI App。

## 6. 发布到真机测试

模拟器验证通过后，想装到真机：
1. Xcode `Signing & Capabilities` 里选你的 Team（Apple ID）。
2. 连接 iPhone，选为运行设备，运行。
3. iPhone 上首次打开会提示"未受信任的开发者"，去 `设置 → 通用 → VPN与设备管理` 信任即可。

---

## 常见问题

**Q：App 里打字打不出中文？**
- 模拟器情况：`I/O → Keyboard → Connect Hardware Keyboard` 要**取消勾选**，才会弹出系统中文输入法。
- 真机：用系统中文键盘即可。

**Q：App 连不上后端 / 列表是空的？**
- 99% 是隧道地址变了（快速隧道重启后 URL 变化）。去 `设置` 页更新服务器地址，或改 `baseURL` 重新构建。
- 生产建议用固定域名（如 `openmemo.你的域名.com`）避免此问题。

**Q：什么时候能上 App Store？**
- 目前是源码 + Xcode 自构建阶段。要上架需 Apple 开发者账号（$99/年）、配置签名、App 审核。交给客户验收阶段一般先用 TestFlight 或真机直装。

**Q：真机连不上 localhost？**
- 真机不能用 `localhost`（那是手机自己）。用 Mac 的局域网 IP（`设置→Wi-Fi→详情` 看 IP）+ `18890`，或直接走隧道公网地址。

## 说话人识别（SI）使用说明

> v1.1.0 起，**全部在 App 内完成**，不需要终端 / Xcode / 重新编译。

1. **登记**：设置 → 说话人识别 → 管理 → 输入名字 → 录 3 个样本（点麦克风开始 → 按提示说话 → 再点停止）。
2. **训练**：点「训练模型 / 重新训练模型」，约 30 秒完成，模型即训即用。
3. **使用**：语音留言自动识别说话人，气泡底部标注名字；消息进入该说话人专属会话，AI 上下文按人隔离。
4. **隐私**：未识别的人视为访客，AI 不会透露任何已登记用户的任务/提醒，并建议访客先训练语音。
5. **注意**：训练功能依赖 Create ML，仅在 **Mac 版（Catalyst）** 可用；iPhone 上训练按钮会提示「仅支持 Mac 版」，识别功能本身两端都可用。

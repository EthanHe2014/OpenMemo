# Android / 不兼容手机的 STT 方案（落地版）

> 2026-08-17 落地。之前只做了推荐，这次把**本地离线 STT** 真正装进了服务器。

## 三层 STT 架构（自动降级）

| 设备/浏览器 | 识别引擎 | 实现 |
|---|---|---|
| iPhone Safari | Apple 系统识别 | Web Speech API（`webkitSpeechRecognition`） |
| Android Chrome | Android 系统识别 | Web Speech API（`webkitSpeechRecognition`） |
| **不兼容浏览器/平台** | **本地离线 STT** | **服务器 sherpa-onnx（本次新增）** |

## 本地离线 STT（sherpa-onnx）

- **模型**：`sherpa-onnx-streaming-zipformer-zh-14M-2023-02-23`（~71MB，流式中英，离线）
  - 下载位置：`models/sherpa-onnx-streaming-zipformer-zh-14M-2023-02-23/`
  - 来源：https://github.com/k2-fsa/sherpa-onnx/releases/tag/asr-models
- **代码**：`openmemo/stt.py`
  - `local_stt_available()` — 模型齐全检查（缺模型优雅降级，不崩）
  - `transcribe_wav(path)` — WAV → 文本（16kHz 16-bit mono；其它采样率自动 ffmpeg 重采样）
- **API**：`POST /api/stt`
  - Body：WAV 二进制
  - 返回：`{"text": "...", "engine": "sherpa-onnx"}`；空 body → 400；模型缺失 → 501
- **依赖**：`pip install sherpa-onnx`（已装 1.13.5）

## 浏览器端（dashboard.html）

- 自动检测 `window.SpeechRecognition || window.webkitSpeechRecognition`
- 有 → 系统引擎（`zh-CN`，实时转写进输入框）
- 无 → 麦克风录音 → 降采样 16kHz → WAV → POST `/api/stt` → 文本进输入框
- 顶部 `#stt-status` 徽章实时显示当前引擎（"Apple 系统识别 / Android 系统识别 / 本地离线 STT"）
- 录音时 🎤 变 ⏹ 红点脉冲，点一下停止并识别

## App 端（SwiftUI，Apple 平台）

- `Services/STTEngine.swift` 统一 `STTProvider` 协议 + 平台自动检测：
  - Apple 平台 → `AppleSTTProvider`（SFSpeechRecognizer，系统识别）
  - **智能降级**：Apple 识别不可用（权限被拒/引擎不支持）时自动切到
    `LocalSTTProvider`（服务器 sherpa-onnx 离线转写），语音始终可用
  - Android 移植版 → `AndroidSTTProvider`（Kotlin 按同协议实现 SpeechRecognizer）
  - 其它/未知 → `LocalSTTProvider`
- `Services/LocalSTTProvider.swift`（真实实现）：
  - App 内 AVAudioEngine 录音（16kHz 单声道 WAV）
  - POST 服务器 `{baseURL}/api/stt` → sherpa-onnx 离线转写 → 文本回调
  - 服务器可达性探测（空 body → 400 即证明端点存在）
  - 与 Apple 引擎同款纪律：每次会话全新 AVAudioEngine，stop 后销毁
- SwiftUI 包本身只跑 Apple 平台，Android/本地实现在移植版按协议实现即可，上层零改动。

## 模型重装指引（如果换机器）

```bash
pip install sherpa-onnx
mkdir -p models && cd models
curl -L -o zh.tar.bz2 "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-streaming-zipformer-zh-14M-2023-02-23.tar.bz2"
tar xjf zh.tar.bz2 && rm zh.tar.bz2
```

## 测试

- `tests/test_stt.py`：6 个用例（模型检测 / 非法音频 400 / 静音不崩 / 合法 WAV 200）
- 全量：`python -m pytest tests/ -q` → 288 passed（286 + 2 skipped）

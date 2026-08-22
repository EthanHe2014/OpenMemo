import Foundation
import AVFoundation

// MARK: - 本地离线 STT（服务器 sherpa-onnx 版）
//
// 场景：Apple 系统识别不可用（权限被拒 / 引擎不支持）或未来 Android/其它平台。
// 实现：App 内 AVAudioEngine 录音 → 16kHz WAV → POST 服务器 /api/stt
//      → 服务器 sherpa-onnx 离线转写（音频不出本机局域网）→ 文本回调。
//
// 与 AppleSTTProvider 行为一致：startVoiceInput 开始留言，stop 停止并提交。

@MainActor
final class LocalSTTProvider: STTProvider {
    let platform: STTPlatform = .local

    // 服务器地址（与 OpenMemoAPI 共用；iPhone 上应改为 Mac mini 的局域网 IP）
    var serverURL: String {
        OpenMemoAPI.shared.baseURL
    }

    /// 可用条件：服务器可达（本地 STT 端点存在）。做一次轻量探测。
    var isAvailable: Bool {
        let semaphore = DispatchSemaphore(value: 0)
        var ok = false
        Task {
            ok = await checkServer()
            semaphore.signal()
        }
        _ = semaphore.wait(timeout: .now() + 3)
        return ok
    }

    var onMessageReady: ((String) -> Void)?
    var liveText: String = "" {
        didSet { print("[本地STT] liveText: \(liveText)") }
    }
    var isTranscribing: Bool = false
    var isWakeArmed: Bool = false
    var isListening: Bool = false
    var lastSessionAudioURL: URL? { nil }   // 本地 STT 走服务器，暂无本地音频

    private var engine: AVAudioEngine?
    private var isStoppingForSubmit = false

    // MARK: - 协议实现

    func startVoiceInput() {
        guard !isListening else { return }
        isTranscribing = true
        isListening = true
        isWakeArmed = false
        liveText = ""

        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(.record, mode: .measurement)
            try session.setActive(true, options: .notifyOthersOnDeactivation)
        } catch {
            print("[本地STT] 音频会话失败: \(error.localizedDescription)")
        }

        // 全新引擎（与 Apple 引擎同款纪律：绝不复用，stop 后销毁）
        let engine = AVAudioEngine()
        self.engine = engine

        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0 else {
            print("[本地STT] 无输入设备")
            stop()
            return
        }

        // 用 AVAudioFile 直接写 WAV（16kHz 单声道；格式不对时由服务器 ffmpeg 重采样）
        let targetFormat = AVAudioFormat(standardFormatWithSampleRate: 16000, channels: 1)!
        let tempURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("localstt_\(UUID().uuidString).wav")

        do {
            let file = try AVAudioFile(forWriting: tempURL, settings: targetFormat.settings)
            input.installTap(onBus: 0, bufferSize: 4096, format: format) { [weak self] buffer, _ in
                // 转成 16k mono 再写文件
                guard let self else { return }
                let converter = AVAudioConverter(from: format, to: targetFormat)
                let ratio = 16000.0 / format.sampleRate
                let outCapacity = AVAudioFrameCount(Double(buffer.frameLength) * ratio) + 1024
                guard let outBuffer = AVAudioPCMBuffer(
                    pcmFormat: targetFormat,
                    frameCapacity: outCapacity
                ) else { return }
                var error: NSError?
                let status = converter?.convert(to: outBuffer, error: &error) { _, outStatus in
                    outStatus.pointee = .haveData
                    return buffer
                }
                if status == .haveData {
                    try? file.write(from: outBuffer)
                }
            }
            try engine.start()
            print("[本地STT] 录音开始")
        } catch {
            print("[本地STT] 启动失败: \(error.localizedDescription)")
            stop()
        }
    }

    func setWakeMode(_ enabled: Bool) {
        // 本地 STT 不做唤醒词（常驻录音费电费流量）；开关仅记录
        print("[本地STT] 唤醒词模式：本地引擎不支持（\(enabled ? "请求开" : "关")）")
    }

    func stop() {
        guard isListening || isTranscribing else { return }
        isStoppingForSubmit = true

        if let engine {
            if engine.isRunning { engine.stop() }
            engine.inputNode.removeTap(onBus: 0)
        }
        engine = nil
        isListening = false
        isWakeArmed = false

        // 找到刚写的临时 WAV → 上传识别
        let tempURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("localstt_")
        let candidate = (try? FileManager.default.contentsOfDirectory(
            at: tempURL.deletingLastPathComponent(),
            includingPropertiesForKeys: nil
        ))?.first { $0.lastPathComponent.hasPrefix("localstt_") && $0.pathExtension == "wav" }

        isTranscribing = false
        guard let wavURL = candidate, FileManager.default.fileExists(atPath: wavURL.path) else {
            isStoppingForSubmit = false
            return
        }

        // 上传识别（后台）
        Task { [weak self] in
            defer { try? FileManager.default.removeItem(at: wavURL) }
            guard let self else { return }
            let text = await self.transcribe(wavURL)
            self.isStoppingForSubmit = false
            if !text.isEmpty {
                self.liveText = text
                self.onMessageReady?(text)
            } else {
                print("[本地STT] 未识别到内容")
            }
        }
    }

    // MARK: - 服务器通信

    private func checkServer() async -> Bool {
        do {
            let url = URL(string: serverURL)!.appendingPathComponent("api/stt")
            var req = URLRequest(url: url)
            req.httpMethod = "POST"
            req.httpBody = Data()  // 空 body → 400，但能证明端点存在
            req.timeoutInterval = 3
            let (_, resp) = try await URLSession.shared.data(for: req)
            // 400 = 端点存在（空 body 被拒）；501 = 模型缺失；200 不可能（空音频）
            return (resp as? HTTPURLResponse)?.statusCode == 400
                || (resp as? HTTPURLResponse)?.statusCode == 501
        } catch {
            return false
        }
    }

    private func transcribe(_ wavURL: URL) async -> String {
        do {
            let data = try Data(contentsOf: wavURL)
            let url = URL(string: serverURL)!.appendingPathComponent("api/stt")
            var req = URLRequest(url: url)
            req.httpMethod = "POST"
            req.setValue("audio/wav", forHTTPHeaderField: "Content-Type")
            req.timeoutInterval = 30
            let (data2, resp) = try await URLSession.shared.upload(for: req, from: data)
            guard (resp as? HTTPURLResponse)?.statusCode == 200 else {
                print("[本地STT] 服务器返回 \(String(describing: (resp as? HTTPURLResponse)?.statusCode))")
                return ""
            }
            let obj = try JSONSerialization.jsonObject(with: data2) as? [String: Any]
            return (obj?["text"] as? String) ?? ""
        } catch {
            print("[本地STT] 上传失败: \(error.localizedDescription)")
            return ""
        }
    }
}

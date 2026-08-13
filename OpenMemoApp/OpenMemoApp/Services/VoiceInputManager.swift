import Foundation
import Speech
import AVFoundation

/// 语音输入管理器：STT 语音留言 + 静音 2 秒自动发送 + "memo memo" 唤醒词。
/// 前台常听（唤醒词模式）时丢弃普通语音，识别到 "memo memo" 后进入留言模式，
/// 留言结束（2 秒无新语音）自动回调提交。
///
/// 注意（Catalyst 血泪教训）：
/// - 完成回调在后台线程 → 闭包必须 @Sendable，数据先取出再跳 MainActor
/// - AVAudioEngine.start() 在 Catalyst + USB 麦克风上可能卡住 → 必须在后台线程启动，
///   绝不能在主线程调用（否则 App 无响应）
/// 非 Sendable 对象的线程安全盒子（音频回调线程往里 append 缓冲）
final class RecognitionRequestBox: @unchecked Sendable {
    var request: SFSpeechAudioBufferRecognitionRequest?
}

/// AVAudioEngine 盒子：允许在后台线程 start()（Catalyst 上主线程 start 会卡死 App）
final class AudioEngineBox: @unchecked Sendable {
    let engine = AVAudioEngine()
}

@MainActor
@Observable
final class VoiceInputManager {
    /// 状态
    var isListening = false       // 音频引擎是否在跑
    var isTranscribing = false    // 是否处于留言模式（唤醒后 / 直接按麦）
    var liveText = ""             // 实时转写文本（输入框用）

    /// 回调
    var onMessageReady: ((String) -> Void)?   // 留言结束（静音2秒）→ 提交
    var onWakeWord: (() -> Void)?             // 唤醒词触发（可用来震动/提示）

    private let recognizer: SFSpeechRecognizer? =
        SFSpeechRecognizer(locale: Locale(identifier: "zh-CN"))
    private let engineBox = AudioEngineBox()
    private let reqBox = RecognitionRequestBox()
    nonisolated(unsafe) private var request: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?

    private var wakeArmed = true              // 唤醒词监听中
    private var lastTextTime = Date()
    private var silenceTimer: Timer?
    private var isStarting = false

    // MARK: - 权限

    nonisolated static func requestAuthorization() async -> Bool {
        await withCheckedContinuation { cont in
            // 完成回调在后台线程：闭包必须 @Sendable（不继承 MainActor），
            // 再 Task { @MainActor } 跳回主线程 resume，否则 Swift 6 隔离断言崩溃
            SFSpeechRecognizer.requestAuthorization { @Sendable status in
                Task { @MainActor in
                    cont.resume(returning: status == .authorized)
                }
            }
        }
    }

    // MARK: - 控制

    /// 开始聆听（唤醒词模式：听到 "memo memo" 才进入留言）
    func startWakeListening() {
        startEngine(wakeMode: true)
    }

    /// 直接进入留言模式（用户点了麦克风）
    func startVoiceInput() {
        if isListening && isTranscribing { return }
        startEngine(wakeMode: false)
    }

    /// 停止聆听（取消/退出）
    func stop() {
        silenceTimer?.invalidate()
        silenceTimer = nil
        recognitionTask?.cancel()
        recognitionTask = nil
        request?.endAudio()
        request = nil
        reqBox.request = nil
        if engineBox.engine.isRunning {
            engineBox.engine.stop()
            engineBox.engine.inputNode.removeTap(onBus: 0)
        }
        isListening = false
        isTranscribing = false
        wakeArmed = true
        liveText = ""
    }

    private func startEngine(wakeMode: Bool) {
        guard !isStarting, !isListening, let recognizer, recognizer.isAvailable else { return }
        isStarting = true

        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playAndRecord, mode: .default, options: [.defaultToSpeaker, .allowBluetooth])
            try session.setActive(true, options: .notifyOthersOnDeactivation)
        } catch {
            print("[语音] 音频会话失败：\(error.localizedDescription)")
        }

        let req = SFSpeechAudioBufferRecognitionRequest()
        req.shouldReportPartialResults = true
        req.taskHint = .dictation
        request = req
        reqBox.request = req

        recognitionTask = recognizer.recognitionTask(with: req) { @Sendable [weak self] result, error in
            // 在后台线程先取出 Sendable 数据（String），避免把非 Sendable 的 result 传进 MainActor
            let text = result?.bestTranscription.formattedString ?? ""
            let shouldCleanup = (error != nil) || (result?.isFinal == true)
            Task { @MainActor in
                guard let self else { return }
                if !text.isEmpty {
                    self.handle(text: text)
                }
                if shouldCleanup {
                    // 引擎自动结束（如长时间静音）——静默重挂
                    self.cleanupEngine()
                }
            }
        }

        let format = engineBox.engine.inputNode.outputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0 else {
            print("[语音] 没有可用的麦克风输入格式")
            isStarting = false
            return
        }
        // 音频线程回调：通过 Sendable 盒子追加缓冲（不能捕获非 Sendable 的 req）
        let box = reqBox
        engineBox.engine.inputNode.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in
            box.request?.append(buffer)
        }
        engineBox.engine.prepare()

        // ⚠️ 关键：Catalyst 上 audioEngine.start() 可能卡住（USB 麦克风），
        // 必须在后台线程启动，主线程保持响应
        let engBox = engineBox
        Task.detached(priority: .userInitiated) {
            do {
                try engBox.engine.start()
            } catch {
                print("[语音] 引擎启动失败：\(error.localizedDescription)")
            }
        }

        isListening = true
        isTranscribing = !wakeMode
        wakeArmed = wakeMode
        lastTextTime = Date()
        startSilenceTimer()
        isStarting = false
    }

    private func cleanupEngine() {
        silenceTimer?.invalidate()
        silenceTimer = nil
        recognitionTask?.cancel()
        recognitionTask = nil
        request = nil
        reqBox.request = nil
        if engineBox.engine.isRunning {
            engineBox.engine.stop()
            engineBox.engine.inputNode.removeTap(onBus: 0)
        }
        isListening = false
        isTranscribing = false
        wakeArmed = true
    }

    // MARK: - 转写处理

    private func handle(text: String) {
        liveText = text
        // 唤醒词模式：等 "memo memo"
        if wakeArmed && !isTranscribing {
            let lower = text.lowercased()
            if lower.contains("memo memo") || lower.contains("memo memo memo") {
                isTranscribing = true
                wakeArmed = false
                liveText = ""          // 唤醒词本身不算留言
                lastTextTime = Date()
                onWakeWord?()
            }
            return
        }
        // 留言模式：持续更新，重置静音计时
        if isTranscribing {
            lastTextTime = Date()
        }
    }

    private func startSilenceTimer() {
        silenceTimer?.invalidate()
        silenceTimer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] _ in
            Task { @MainActor in
                self?.checkSilence()
            }
        }
    }

    /// 留言模式：2 秒没有新语音 → 自动提交
    private func checkSilence() {
        guard isTranscribing else { return }
        let idle = Date().timeIntervalSince(lastTextTime)
        if idle >= 2.0 {
            let text = liveText.trimmingCharacters(in: .whitespacesAndNewlines)
            let finalText = text
            // 提交前先停引擎，避免重复触发
            stop()
            if !finalText.isEmpty {
                onMessageReady?(finalText)
            }
        }
    }
}

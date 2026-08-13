import Foundation
import Speech
import AVFoundation

/// 语音输入管理器：STT 语音留言 + 静音 2 秒自动发送 + "memo memo" 唤醒词。
/// 前台常听（唤醒词模式）时丢弃普通语音，识别到 "memo memo" 后进入留言模式，
/// 留言结束（2 秒无新语音）自动回调提交。
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
    private let audioEngine = AVAudioEngine()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?

    private var wakeArmed = true              // 唤醒词监听中
    private var lastTextTime = Date()
    private var silenceTimer: Timer?
    private var isStarting = false

    // MARK: - 权限

    static func requestAuthorization() async -> Bool {
        await withCheckedContinuation { cont in
            SFSpeechRecognizer.requestAuthorization { status in
                // 完成回调在后台线程，必须跳回 MainActor 再 resume，否则崩溃
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
        if audioEngine.isRunning {
            audioEngine.stop()
            audioEngine.inputNode.removeTap(onBus: 0)
        }
        isListening = false
        isTranscribing = false
        wakeArmed = true
        liveText = ""
    }

    private func startEngine(wakeMode: Bool) {
        guard !isStarting, !isListening, let recognizer, recognizer.isAvailable else { return }
        isStarting = true
        defer { isStarting = false }

        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playAndRecord, mode: .default, options: [.defaultToSpeaker, .allowBluetooth])
            try session.setActive(true, options: .notifyOthersOnDeactivation)
        } catch {
            print("[语音] 音频会话失败：\(error.localizedDescription)")
        }

        request = SFSpeechAudioBufferRecognitionRequest()
        guard let request else { return }
        request.shouldReportPartialResults = true
        request.taskHint = .dictation

        recognitionTask = recognizer.recognitionTask(with: request) { [weak self] result, error in
            Task { @MainActor in
                guard let self else { return }
                if let result {
                    let text = result.bestTranscription.formattedString
                    self.handle(text: text)
                }
                if error != nil || result?.isFinal == true {
                    // 引擎自动结束（如长时间静音）——静默重挂
                    self.cleanupEngine()
                }
            }
        }

        let format = audioEngine.inputNode.outputFormat(forBus: 0)
        // 音频线程回调：不碰 self（MainActor），直接捕获 request 追加缓冲
        let req = request
        audioEngine.inputNode.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in
            req.append(buffer)
        }

        audioEngine.prepare()
        do {
            try audioEngine.start()
            isListening = true
            isTranscribing = !wakeMode
            wakeArmed = wakeMode
            lastTextTime = Date()
            startSilenceTimer()
        } catch {
            print("[语音] 启动失败：\(error.localizedDescription)")
        }
    }

    private func cleanupEngine() {
        silenceTimer?.invalidate()
        silenceTimer = nil
        recognitionTask?.cancel()
        recognitionTask = nil
        request = nil
        if audioEngine.isRunning {
            audioEngine.stop()
            audioEngine.inputNode.removeTap(onBus: 0)
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

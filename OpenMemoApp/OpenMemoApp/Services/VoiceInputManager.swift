import Foundation
import Speech
import AVFoundation

/// 语音输入管理器：STT 语音留言 + 静音 2.5 秒自动发送。
///
/// ⚠️ Catalyst 血泪教训（不要再"优化"回去）：
/// 1. **每次会话全新 AVAudioEngine + 全新 recognition request**，stop 后彻底销毁。
///    复用同一个引擎（start/stop/installTap/removeTap 循环）会触发
///    "nullptr == Tap()" / 状态残留崩溃——这是"只能用一次"的根源。
/// 2. 音频 tap 回调线程不是 MainActor → 闭包必须显式 @Sendable，
///    语法是 `{ @Sendable (参数) in }`（@Sendable 修饰整个闭包）。
///    写 `{ @Sendable 参数 in }` 只会标记参数，闭包仍继承 MainActor → 照样崩溃。
///    Swift 6 下捕获非 Sendable 的 req 会报 data race → 用 RecognitionRequestBox 中转。
/// 3. AVAudioEngine.start() 在 Catalyst + USB 麦克风上会卡住主线程 → 必须 Task.detached 后台启动。
/// 4. 完成回调在后台线程 → 先取出 String，再 Task { @MainActor } 跳回主线程。
/// 5. SwiftUI Button 手势回调在 Catalyst 上不在 MainActor 执行器 → 按钮动作里
///    不能直接碰 @MainActor 状态，全部包进 Task { @MainActor }。

/// 非 Sendable 对象的线程安全盒子（音频回调线程往里 append 缓冲）
final class RecognitionRequestBox: @unchecked Sendable {
    var request: SFSpeechAudioBufferRecognitionRequest?
}

/// 引擎盒子：允许在后台线程 start()（Swift 6 sending 检查要求捕获 Sendable 值）
final class AudioEngineBox: @unchecked Sendable {
    let engine: AVAudioEngine
    init(_ engine: AVAudioEngine) { self.engine = engine }
}

@MainActor
@Observable
final class VoiceInputManager {
    /// 状态
    var isListening = false       // 音频引擎是否在跑
    var isTranscribing = false    // 是否处于留言模式（唤醒后 / 直接按麦）
    var isWakeArmed = false       // 唤醒词待命中（听到 "hey memo" 才进入留言）
    var liveText = ""             // 实时转写文本（输入框用）

    /// 回调
    var onMessageReady: ((String) -> Void)?   // 留言结束（静音2秒）→ 提交

    private let recognizer: SFSpeechRecognizer? =
        SFSpeechRecognizer(locale: Locale(identifier: "zh-CN"))

    // ⚠️ 每会话状态：全部在 start 时新建、stop 时销毁。绝不跨会话复用。
    private var engine: AVAudioEngine?
    /// 本会话录音文件（供说话人识别）；会话结束即生成，识别完可删除
    private(set) var lastSessionAudioURL: URL?
    private var sessionAudioFile: AVAudioFile?
    private var sessionAudioFormat: AVAudioFormat?
    private let reqBox = RecognitionRequestBox()   // @unchecked Sendable：音频线程往里 append
    private var recognitionTask: SFSpeechRecognitionTask?
    private var silenceTimer: Timer?
    private var lastTextTime = Date()
    private var isStarting = false
    private var sessionCount = 0   // 日志用
    private var wakeModeEnabled = true   // 唤醒词常开（无按钮，App 启动即监听「小麦小麦」）
    private var isRearming = false       // 防重入：stop 后自动重新挂起唤醒监听
    private var rearmToken = 0           // 唤醒接管时作废所有待执行的自动重挂
    private var currentSessionEpoch = 0  // 会话代数：旧会话的迟到回调不得影响新会话
    private var stripAckUntil: Date?     // 留言会话初期：剥离服务器应答"我在"被麦克风拾取的残余

    // MARK: - 权限

    nonisolated static func requestAuthorization() async -> Bool {
        await withCheckedContinuation { cont in
            // 完成回调在后台线程：闭包必须 @Sendable，再 Task { @MainActor } 跳回主线程
            SFSpeechRecognizer.requestAuthorization { @Sendable status in
                Task { @MainActor in
                    cont.resume(returning: status == .authorized)
                }
            }
        }
    }

    // MARK: - 控制

    /// 开/关唤醒词监听（"hey memo" / "memo memo"）
    func setWakeMode(_ enabled: Bool) {
        wakeModeEnabled = enabled
        if enabled {
            startWakeListening()
        } else {
            if isWakeArmed && !isTranscribing {
                stop()
            }
        }
    }

    /// 挂起唤醒监听：常听，命中 "hey memo" 才进入留言模式
    func startWakeListening() {
        guard !isStarting, !isListening, wakeModeEnabled else { return }
        startEngine(wakeMode: true)
    }

    /// 直接进入留言模式（用户点了麦克风）
    func startVoiceInput() {
        if isListening && isTranscribing { return }
        if isListening {
            // 唤醒监听中直接按麦：先停掉唤醒会话（禁止自动重挂），再开留言会话
            isRearming = true
            stop()
            isRearming = false
        }
        startEngine(wakeMode: false)
    }

    /// 停止并彻底销毁本次会话的所有音频对象
    func stop() {
        silenceTimer?.invalidate()
        silenceTimer = nil
        recognitionTask?.cancel()
        recognitionTask = nil
        reqBox.request?.endAudio()
        reqBox.request = nil
        if let engine {
            if engine.isRunning { engine.stop() }
            engine.inputNode.removeTap(onBus: 0)
        }
        engine = nil
        // 说话人识别音频：关闭文件并保留 URL（供 SpeakerRecognizer 用）
        if let sessionAudioFile {
            lastSessionAudioURL = sessionAudioFile.url
        }
        sessionAudioFile = nil
        sessionAudioFormat = nil
        isListening = false
        isTranscribing = false
        isWakeArmed = false
        liveText = ""
        sessionCount += 1
        print("[语音] 会话结束 #\(sessionCount)，引擎已销毁")

        // 唤醒词开着且本次不是手动接管 → 短暂延迟后自动重新挂起监听（免手无感续听）
        if wakeModeEnabled && !isRearming {
            isRearming = true
            let token = rearmToken
            Task { @MainActor [weak self] in
                try? await Task.sleep(nanoseconds: 1_000_000_000)
                // 若期间发生了唤醒接管（handleWakeWord），此重挂已作废
                guard let self, token == self.rearmToken else { return }
                self.isRearming = false
                self.startWakeListening()
            }
        }
    }

    private func startEngine(wakeMode: Bool) {
        guard !isStarting, !isListening, let recognizer, recognizer.isAvailable else { return }
        isStarting = true
        sessionCount += 1
        print("[语音] 会话开始 #\(sessionCount)：全新引擎 + 全新 request")

        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playAndRecord, mode: .default, options: [.defaultToSpeaker, .allowBluetooth])
            try session.setActive(true, options: .notifyOthersOnDeactivation)
        } catch {
            print("[语音] 音频会话失败：\(error.localizedDescription)")
        }

        // 全新 request —— 只属于本次会话
        currentSessionEpoch += 1
        let epoch = currentSessionEpoch
        let req = SFSpeechAudioBufferRecognitionRequest()
        req.shouldReportPartialResults = true
        req.taskHint = .dictation
        reqBox.request = req

        // 全新引擎 —— 只属于本次会话（绝不复用，避免 tap 状态残留）
        let engine = AVAudioEngine()
        self.engine = engine

        recognitionTask = recognizer.recognitionTask(with: req) { @Sendable [weak self] result, error in
            // 后台线程先取出 Sendable 数据，再跳 MainActor
            let text = result?.bestTranscription.formattedString ?? ""
            let shouldCleanup = (error != nil) || (result?.isFinal == true)
            Task { @MainActor in
                guard let self else { return }
                // 旧会话的迟到回调（会话已被销毁/替换）一律忽略，
                // 否则会误杀刚开的新会话（唤醒接管时必现）
                guard epoch == self.currentSessionEpoch else { return }
                if !text.isEmpty {
                    self.handle(text: text)
                }
                if shouldCleanup {
                    self.stop()
                }
            }
        }

        let format = engine.inputNode.outputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0 else {
            print("[语音] 没有可用的麦克风输入格式")
            isStarting = false
            return
        }

        // ⚠️ 正确写法：@Sendable 修饰整个闭包（音频线程可安全调用）；
        // 在 nonisolated 静态方法里安装 tap：避免 Swift 6 "sending" 参数检查
        // （MainActor 上下文创建的闭包传给 sending 参数会报 data race）
        Self.installTap(on: engine, format: format, box: reqBox)

        // 说话人识别：同一路麦克风再写一份 WAV（会话结束供 SpeakerRecognizer 推理）
        do {
            let tmp = FileManager.default.temporaryDirectory
                .appendingPathComponent("session_audio_\(UUID().uuidString).wav")
            let wavFormat = AVAudioFormat(standardFormatWithSampleRate: 16000, channels: 1)!
            let wavFile = try AVAudioFile(forWriting: tmp, settings: wavFormat.settings)
            sessionAudioFile = wavFile
            sessionAudioFormat = wavFormat
            // 用独立 tap 写文件（recognition tap 是 1024 buffer，这里用稍大 buffer 减负）
            engine.inputNode.installTap(onBus: 0, bufferSize: 8192, format: format) {
                [weak self] buffer, _ in
                guard let self, let wavFile = self.sessionAudioFile,
                      let wavFormat = self.sessionAudioFormat else { return }
                let converter = AVAudioConverter(from: format, to: wavFormat)
                let ratio = wavFormat.sampleRate / format.sampleRate
                let capacity = AVAudioFrameCount(Double(buffer.frameLength) * ratio) + 1024
                guard let outBuf = AVAudioPCMBuffer(pcmFormat: wavFormat,
                                                    frameCapacity: capacity) else { return }
                var error: NSError?
                let status = converter?.convert(to: outBuf, error: &error) { _, outStatus in
                    outStatus.pointee = .haveData
                    return buffer
                }
                if status == .haveData {
                    try? wavFile.write(from: outBuf)
                }
            }
        } catch {
            print("[语音] 会话录音文件创建失败：\(error.localizedDescription)")
            sessionAudioFile = nil
        }
        engine.prepare()

        // ⚠️ Catalyst 上 start() 可能卡住 → 后台线程启动；
        // 捕获 Sendable 盒子（sending 检查不允许捕获 MainActor 上下文创建的局部对象）
        let engBox = AudioEngineBox(engine)
        Task.detached(priority: .userInitiated) {
            do {
                try engBox.engine.start()
            } catch {
                print("[语音] 引擎启动失败：\(error.localizedDescription)")
            }
        }

        isListening = true
        isTranscribing = !wakeMode
        isWakeArmed = wakeMode
        lastTextTime = Date()
        startSilenceTimer()
        isStarting = false
    }

    /// nonisolated：闭包在非隔离上下文创建，音频实时线程直接调用
    nonisolated private static func installTap(on engine: AVAudioEngine, format: AVAudioFormat, box: RecognitionRequestBox) {
        engine.inputNode.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in
            box.request?.append(buffer)
        }
    }

    /// 唤醒命中后的完整流程：
    /// 销毁唤醒会话（识别流从头开始，不带唤醒词垃圾）→ 立刻开全新留言会话（
    /// 引擎在应答播放期间完成预热）→ 服务器应答"我在！"边放边听，
    /// 应答播完时识别器已稳定，紧跟说话一个字都不丢
    func handleWakeWord() async {
        rearmToken += 1   // 作废所有待执行的自动重挂（防止旧会话回调抢先重挂）
        isRearming = true     // 阻止 stop() 自动重挂（接下来手动开留言会话）
        stop()
        isRearming = false

        // 开全新留言会话（先于应答启动，预热引擎；开头 2.5s 剥离开头噪音）
        stripAckUntil = Date().addingTimeInterval(2.5)
        startVoiceInput()

        // 服务器朗读"我在！"（Xiaoxiao，与 AI 回复同声）；播放期间麦克风已在听
        await OpenMemoAPI.shared.speak("我在！")

        // 保险：万一留言会话没起来（识别器不可用等），应答后重新挂起唤醒
        if !isListening && wakeModeEnabled {
            startWakeListening()
        }
    }

    // MARK: - 转写处理

    private func handle(text: String) {
        // 唤醒词模式：等 "小麦小麦"（zh-CN 识别，容忍同音字 "小卖"）
        if isWakeArmed {
            if text.lowercased().contains("小麦") || text.lowercased().contains("小卖") {
                print("[语音] 唤醒词命中：\(text)")
                isTranscribing = true
                isWakeArmed = false
                liveText = ""          // 唤醒词本身不算留言内容
                lastTextTime = Date()
                // 异步执行完整唤醒流程（应答"我在！"，麦克风全程不断）
                Task { @MainActor in
                    await self.handleWakeWord()
                }
            }
            return
        }
        // 留言模式：持续更新，重置静音计时
        if isTranscribing {
            var t = text
            // 开麦初期（唤醒刚命中）：剥离开头噪音——
            // 唤醒词残余（小麦小麦）与服务器应答"我在！"被麦克风拾取的部分
            if let until = stripAckUntil, Date() < until {
                var stripped = true
                while stripped && !t.isEmpty {
                    stripped = false
                    for prefix in ["小麦小麦", "小麦", "小卖", "我在，", "我在。", "我在！", "我在"] {
                        if t.hasPrefix(prefix) {
                            t = String(t.dropFirst(prefix.count))
                            stripped = true
                            break
                        }
                    }
                }
                if t.isEmpty {
                    // 只有噪音：不更新文本，但刷新静音计时（应答播放期间会话保持存活）
                    lastTextTime = Date()
                    return
                }
            }
            liveText = t
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

    /// 留言模式：2.5 秒没有新语音 → 自动提交
    private func checkSilence() {
        guard isTranscribing else { return }
        let idle = Date().timeIntervalSince(lastTextTime)
        if idle >= 2.5 {
            let finalText = liveText.trimmingCharacters(in: .whitespacesAndNewlines)
            // 先彻底销毁会话，再回调提交（避免重复触发）
            stop()
            if !finalText.isEmpty {
                onMessageReady?(finalText)
            }
        }
    }
}

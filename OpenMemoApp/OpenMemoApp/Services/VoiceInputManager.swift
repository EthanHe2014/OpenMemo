import Foundation
import Speech
import AVFoundation

/// 语音输入管理器：STT 语音留言 + 静音 2 秒自动发送。
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
    private let reqBox = RecognitionRequestBox()   // @unchecked Sendable：音频线程往里 append
    private var recognitionTask: SFSpeechRecognitionTask?
    private var silenceTimer: Timer?
    private var lastTextTime = Date()
    private var isStarting = false
    private var sessionCount = 0   // 日志用
    private var wakeModeEnabled = false  // 唤醒词开关（App 输入栏按钮控制）
    private var isRearming = false       // 防重入：stop 后自动重新挂起唤醒监听
    private var rearmToken = 0           // 唤醒接管时作废所有待执行的自动重挂
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
    /// 麦克风保持常听（不销毁会话！）→ 服务器 Edge TTS 应答"我在！"（边放边听，
    /// 跟着应答说话也不丢字）→ 留言内容剥离开头噪音后照常转写
    func handleWakeWord() async {
        // 开留言会话；开头 3.5 秒内剥离开头噪音：唤醒词残余（小麦）与应答"我在"
        stripAckUntil = Date().addingTimeInterval(3.5)
        // 服务器朗读"我在！"（Xiaoxiao，与 AI 回复同声）；不销毁会话，
        // 应答播放期间麦克风仍在听，用户紧跟说话不会丢
        await OpenMemoAPI.shared.speak("我在！")
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

    /// 留言模式：2 秒没有新语音 → 自动提交
    private func checkSilence() {
        guard isTranscribing else { return }
        let idle = Date().timeIntervalSince(lastTextTime)
        if idle >= 2.0 {
            let finalText = liveText.trimmingCharacters(in: .whitespacesAndNewlines)
            // 先彻底销毁会话，再回调提交（避免重复触发）
            stop()
            if !finalText.isEmpty {
                onMessageReady?(finalText)
            }
        }
    }
}

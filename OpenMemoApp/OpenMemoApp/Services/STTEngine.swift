import Foundation
import SwiftUI
import Speech

// MARK: - STT 平台检测 + 统一 Provider 层
//
// 目标：一个语音输入层，自动检测当前 OS，动态选用合适的 STT：
//   - Apple（iOS/macOS/Catalyst）→ Apple 语音识别（SFSpeechRecognizer）
//   - Android（移植版）        → Android SpeechRecognizer
//   - 不支持的平台             → 本地离线 STT（sherpa-onnx 等）
//
// 说明：当前 App 是 SwiftUI（仅 Apple 平台）。本层把 STT 抽象成
// `STTProvider` 协议，Apple 实现已就位；Android/本地实现留好接口，
// 将来 Flutter/Kotlin 移植时按同一协议接入即可，上层代码零改动。

/// 检测到的 STT 平台
enum STTPlatform: String, CaseIterable {
    case apple     = "Apple 语音识别"
    case android   = "Android 语音识别"
    case local     = "本地离线 STT"
    case unknown   = "未知"
}

/// 平台检测：按当前运行环境返回对应的 STT 平台
func detectSTTPlatform() -> STTPlatform {
    #if os(iOS) || os(macOS) || targetEnvironment(macCatalyst)
    // Apple 全家桶：iOS / macOS / Catalyst（Mac App）→ Apple 语音识别
    return .apple
    #else
    // 其它平台（Android 移植版 / 桌面 Linux / Windows 等）：
    // Android 走系统 SpeechRecognizer；其余退回本地离线 STT。
    // 注：SwiftUI 包目前只编译 Apple 平台，Android 分支由移植版
    // （Flutter/Kotlin）按同一 STTProvider 协议实现。
    return .local
    #endif
}

/// 统一 STT 接口：所有平台实现同一协议，上层（聊天页）不感知差异
@MainActor
protocol STTProvider: AnyObject {
    var platform: STTPlatform { get }
    /// 是否可用（权限已给、引擎就绪）
    var isAvailable: Bool { get }

    /// 直接开始留言（用户按麦）
    func startVoiceInput()
    /// 开/关唤醒词监听
    func setWakeMode(_ enabled: Bool)
    /// 停止并销毁当前会话
    func stop()

    /// 留言完成回调（静音自动提交）
    var onMessageReady: ((String) -> Void)? { get set }
    /// 实时转写文本
    var liveText: String { get set }
    /// 是否正在留言
    var isTranscribing: Bool { get }
    /// 是否唤醒待命
    var isWakeArmed: Bool { get }
    /// 是否在监听（引擎运行中）
    var isListening: Bool { get }
}

/// STT 引擎入口：自动检测平台 → 返回对应 Provider（带智能降级）
enum STTEngine {
    @MainActor
    static let shared: any STTProvider = {
        switch detectSTTPlatform() {
        case .apple:
            // Apple 平台：优先系统识别；不可用（权限被拒/引擎不支持）时
            // 自动降级到本地离线 STT（服务器 sherpa-onnx），保证语音可用
            let apple = AppleSTTProvider()
            if apple.isAvailable {
                return apple
            }
            let local = LocalSTTProvider()
            return local.isAvailable ? local : apple  // 两头都不可用就退回 Apple（弹权限框）
        case .android:
            // Android 移植版接入点（见 AndroidSTTProvider 占位）
            return AndroidSTTProvider()
        case .local, .unknown:
            return LocalSTTProvider()
        }
    }()

    /// 当前平台（供 UI 显示）
    static var currentPlatform: STTPlatform {
        detectSTTPlatform()
    }
}

// MARK: - Apple 实现（SFSpeechRecognizer，现有引擎）

/// Apple 平台的 STT：直接包一层 VoiceInputManager（引擎已在其中，
/// 含 Catalyst 血泪修复：每会话全新引擎、后台启动、线程安全）。
@MainActor
final class AppleSTTProvider: STTProvider {
    let platform: STTPlatform = .apple
    var isAvailable: Bool { VoiceInputManager.requestAuthorizationSync() }

    private let manager = VoiceInputManager()

    var onMessageReady: ((String) -> Void)? {
        get { manager.onMessageReady }
        set { manager.onMessageReady = newValue }
    }
    var liveText: String {
        get { manager.liveText }
        set { manager.liveText = newValue }
    }
    var isTranscribing: Bool { manager.isTranscribing }
    var isWakeArmed: Bool { manager.isWakeArmed }
    var isListening: Bool { manager.isListening }

    func startVoiceInput() { manager.startVoiceInput() }
    func setWakeMode(_ enabled: Bool) { manager.setWakeMode(enabled) }
    func stop() { manager.stop() }
}

// MARK: - Android 实现（移植占位）

/// Android 平台 STT（Flutter/Kotlin 移植版接入点）：
/// 用 Android 系统 SpeechRecognizer，识别中文。
/// ⚠️ 当前 SwiftUI 包不含 Android 运行库，此实现为占位——
/// 移植时用 Kotlin 实现同一协议即可。
@MainActor
final class AndroidSTTProvider: STTProvider {
    let platform: STTPlatform = .android
    var isAvailable: Bool { false }   // 当前包内不可用

    var onMessageReady: ((String) -> Void)?
    var liveText: String = ""
    var isTranscribing: Bool = false
    var isWakeArmed: Bool = false
    var isListening: Bool = false

    func startVoiceInput() {}
    func setWakeMode(_ enabled: Bool) {}
    func stop() {}
}

// MARK: - 本地离线实现（见 LocalSTTProvider.swift）

// 真实实现已移到 LocalSTTProvider.swift：
// App 内录音 → WAV → 服务器 /api/stt（sherpa-onnx 离线转写）→ 文本。

// MARK: - 辅助

extension VoiceInputManager {
    /// 同步查询授权状态（Apple provider 的 isAvailable 用）
    nonisolated static func requestAuthorizationSync() -> Bool {
        let semaphore = DispatchSemaphore(value: 0)
        var granted = false
        SFSpeechRecognizer.requestAuthorization { @Sendable status in
            granted = (status == .authorized)
            semaphore.signal()
        }
        _ = semaphore.wait(timeout: .now() + 3)
        return granted
    }
}

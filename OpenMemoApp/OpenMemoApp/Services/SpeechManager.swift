import Foundation
import AVFoundation

/// AI 回复朗读：AVSpeechSynthesizer（本地 TTS，Mac Catalyst + iPhone 通用，离线即时）。
/// 朗读时剥离 emoji（与服务端一致：TTS 不读 emoji，显示保留原文）。
@MainActor
@Observable
final class SpeechManager {
    static let shared = SpeechManager()

    private let synthesizer = AVSpeechSynthesizer()
    var isSpeaking = false

    private let zhVoice: AVSpeechSynthesisVoice? = {
        // 优先普通话女声（macOS: Tingting；iOS 自动选择）
        if let v = AVSpeechSynthesisVoice(language: "zh-CN") { return v }
        return AVSpeechSynthesisVoice(language: "zh-TW")
    }()

    /// 朗读一段文字（自动剥离 emoji）
    func speak(_ text: String) {
        let clean = Self.stripEmojis(text)
        guard !clean.isEmpty else { return }
        synthesizer.stopSpeaking(at: .immediate)
        let utterance = AVSpeechUtterance(string: clean)
        utterance.voice = zhVoice
        utterance.rate = AVSpeechUtteranceDefaultSpeechRate * 0.95  // 略慢，清晰
        utterance.pitchMultiplier = 1.0
        synthesizer.speak(utterance)
        isSpeaking = true
    }

    /// 停止朗读（用户开始语音输入 / 切换会话时调用，避免回声）
    func stop() {
        synthesizer.stopSpeaking(at: .immediate)
        isSpeaking = false
    }

    /// 与服务端 voice.py 一致的 emoji 剥离规则
    static func stripEmojis(_ text: String) -> String {
        guard !text.isEmpty else { return "" }
        var emojiSet = CharacterSet()
        emojiSet.insert(charactersIn: Unicode.Scalar(0x1F300)!...Unicode.Scalar(0x1FAFF)!)   // 表情/符号
        emojiSet.insert(charactersIn: Unicode.Scalar(0x1F1E6)!...Unicode.Scalar(0x1F1FF)!)   // 国旗字母 🇨🇳
        emojiSet.insert(charactersIn: Unicode.Scalar(0x2600)!...Unicode.Scalar(0x27BF)!)     // 杂项符号/装饰
        emojiSet.insert(charactersIn: Unicode.Scalar(0x2300)!...Unicode.Scalar(0x23FF)!)     // 技术符号 ⏰
        emojiSet.insert(charactersIn: Unicode.Scalar(0x2B00)!...Unicode.Scalar(0x2BFF)!)     // 箭头/星
        emojiSet.insert(charactersIn: Unicode.Scalar(0xFE0F)!...Unicode.Scalar(0xFE0F)!)     // emoji 修饰符
        let filtered = String(text.unicodeScalars.filter { !emojiSet.contains($0) })
        // 去 emoji 后可能留下多余空白
        return filtered.split(whereSeparator: \.isWhitespace).joined(separator: " ")
    }
}

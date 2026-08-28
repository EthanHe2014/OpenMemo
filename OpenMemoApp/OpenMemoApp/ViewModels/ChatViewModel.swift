import Foundation
import SwiftUI

struct ChatMessage: Identifiable, Equatable {
    let id = UUID()
    let role: Role
    let text: String
    var speaker: String? = nil

    enum Role {
        case user, assistant
    }
}

@MainActor
@Observable
final class ChatViewModel {
    /// 服务端的所有会话（侧边栏列表），最新的排在最前。
    var sessions: [ChatSession] = []
    /// 当前打开的会话 id（空 => 新建、未保存的聊天）。
    var currentSessionId: String = ""
    /// 当前会话标题（用户发来第一条消息后更新）。
    var currentTitle: String = "新对话"

    var messages: [ChatMessage] = []
    var inputText = ""
    var isSending = false
    var isLoading = false
    var errorMessage: String?
    var sidebarOpen = false

    private let api = OpenMemoAPI.shared
    private var didStartFresh = false

    // MARK: - 会话管理

    /// 应用启动时调用一次：开启全新聊天（无旧上下文）+ 加载侧边栏。
    func startFresh() async {
        // 幂等：仅在启动时重置一次，不是每次切回该页都重置。
        guard !didStartFresh else { return }
        didStartFresh = true
        newSession()          // sets currentSessionId = "" and clears messages
        await refreshSessions()
        currentTitle = "新对话"
    }

    /// 新建一个本地聊天。旧的仍保留在侧边栏（服务端）。
    func newSession() {
        currentSessionId = ""    // empty => app uses a transient id for this new chat
        messages = []
        currentTitle = "新对话"
        errorMessage = nil
    }

    /// 打开已有会话并加载其历史。
    func selectSession(_ session: ChatSession) async {
        currentSessionId = session.sessionId
        currentTitle = session.displayTitle
        sidebarOpen = false
        messages = []
        await loadHistory(sessionId: session.sessionId)
    }

    /// 删除服务端会话并从侧边栏移除。
    func deleteSession(_ session: ChatSession) async {
        do {
            _ = try await api.deleteSession(session.sessionId)
        } catch {
            errorMessage = "删除失败：\(error.localizedDescription)"
        }
        sessions.removeAll { $0.sessionId == session.sessionId }
        // 如果删除的正好是当前会话，则重新开始一个全新会话。
        if currentSessionId == session.sessionId {
            newSession()
        }
    }

    /// Send voice message with speaker identification.
    /// 模型就绪 + 有录音数据 → 自动识别说话人（无需手动选）。
    func sendVoice(text: String, audioData: Data?) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !isSending else { return }

        if currentSessionId.isEmpty {
            currentSessionId = "ios_" + UUID().uuidString.lowercased().replacingOccurrences(of: "-", with: "")
        }
        if messages.isEmpty {
            currentTitle = String(trimmed.prefix(30))
        }

        // 有录音 → 后台识别说话人，识别完再发（识别失败就用手动选择的说话人）
        if let data = audioData, SpeakerRecognizer.shared.isModelReady {
            isSending = true
            errorMessage = nil
            let sessionId = currentSessionId
            Task {
                let speaker = await Self.identifySpeaker(from: data)
                Self.logSI("identify result: \(speaker ?? "nil") (audio \(data.count)B, model ready)")
                let finalSpeaker = speaker ?? selectedSpeaker
                let userText = Self.prefixSpeaker(finalSpeaker, trimmed)
                await self.finishSend(userText: userText, sessionId: sessionId, speaker: finalSpeaker)
            }
        } else {
            Self.logSI("no identify: audio=\(audioData?.count ?? -1)B modelReady=\(SpeakerRecognizer.shared.isModelReady)")
            let userText = Self.prefixSpeaker(selectedSpeaker, trimmed)
            messages.append(ChatMessage(role: .user, text: userText))
            isSending = true
            errorMessage = nil
            let sessionId = currentSessionId
            Task {
                await self.finishSend(userText: userText, sessionId: sessionId, speaker: selectedSpeaker)
            }
        }
    }

    /// 写说话人识别调试日志（Documents/speaker_si.log）
    static func logSI(_ msg: String) {
        let line = "\(Date()) \(msg)\n"
        if let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first {
            let url = docs.appendingPathComponent("speaker_si.log")
            if let data = line.data(using: .utf8) {
                if FileManager.default.fileExists(atPath: url.path) {
                    if let fh = try? FileHandle(forWritingTo: url) {
                        fh.seekToEndOfFile()
                        fh.write(data)
                        try? fh.close()
                    }
                } else {
                    try? data.write(to: url)
                }
            }
        }
    }

    /// 把说话人名字做成消息前缀；nil 则不加
    private static func prefixSpeaker(_ speaker: String?, _ text: String) -> String {
        guard let speaker, !speaker.isEmpty else { return text }
        return "[\(speaker)] \(text)"
    }

    /// 用录音数据识别说话人（写入临时文件 → SoundAnalysis）
    private static func identifySpeaker(from data: Data) async -> String? {
        let tmp = FileManager.default.temporaryDirectory
            .appendingPathComponent("voice_\(UUID().uuidString).caf")
        do {
            try data.write(to: tmp)
            logSI("identify: wrote \(data.count)B to \(tmp.lastPathComponent)")
            let results = await SpeakerRecognizer.shared.identifySpeaker(audioURL: tmp)
            try? FileManager.default.removeItem(at: tmp)
            logSI("identify: results = \(results)")
            guard let top = results.first else { return nil }
            // 置信度太低或识别成背景 → 不算
            guard top.0 != "__background__", top.1 >= 0.6 else { return nil }
            return top.0
        } catch {
            logSI("identify: ERROR \(error)")
            try? FileManager.default.removeItem(at: tmp)
            return nil
        }
    }

    /// 发消息 + 等回复（sendVoice 与 send 共用）
    private func finishSend(userText: String, sessionId: String, speaker: String? = nil) async {
        // 展示时去掉 "[名字] " 前缀，speaker 单独存（气泡底部显示）；发给 AI 的仍带前缀
        let displayText = Self.extractSpeaker(from: userText)?.clean ?? userText
        self.messages.append(ChatMessage(role: .user, text: displayText, speaker: speaker))
        defer { self.isSending = false }
        do {
            let reply = try await api.chat(message: userText, sessionId: sessionId, speaker: speaker)
            self.messages.append(ChatMessage(role: .assistant, text: reply))
            await self.refreshSessions()
        } catch {
            self.messages.append(ChatMessage(role: .assistant, text: "连接失败：\(error.localizedDescription)"))
        }
    }

    /// 从 "[名字] 正文" 解析出 (名字, 正文)；没有前缀则原样返回
    static func extractSpeaker(from text: String) -> (name: String, clean: String)? {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard t.hasPrefix("[") else { return nil }
        if let end = t.firstIndex(of: "]") {
            let name = String(t[t.index(after: t.startIndex)..<end]).trimmingCharacters(in: .whitespaces)
            let rest = String(t[t.index(after: end)...]).trimmingCharacters(in: .whitespaces)
            if !name.isEmpty {
                return (name, rest)
            }
        }
        return nil
    }

    private func loadHistory(sessionId: String) async {
        isLoading = true
        defer { isLoading = false }
        do {
            let history = try await api.getConversations(sessionId: sessionId)
            // 服务端消息可能带 "[名字] " 前缀 → 解析成 speaker 字段，正文保持干净
            messages = history.map { msg in
                if msg.role == .user, let parsed = Self.extractSpeaker(from: msg.text) {
                    return ChatMessage(role: .user, text: parsed.clean, speaker: parsed.name)
                }
                return msg
            }
        } catch {
            errorMessage = "无法加载对话：\(error.localizedDescription)"
        }
    }

    /// 从服务端重新加载侧边栏列表。
    func refreshSessions() async {
        do {
            sessions = try await api.listSessions()
        } catch {
            // 非致命错误：保留现有列表，侧边栏仍可用。
            errorMessage = error.localizedDescription
        }
    }

    // MARK: - Speaker Detection
    /// Currently selected speaker name (nil = no speaker identification)
    var selectedSpeaker: String? = nil
    /// Available speaker names loaded from SpeakerRecognizer
    var availableSpeakers: [String] { SpeakerRecognizer.shared.enrolledSpeakers }
    /// Whether speaker model is ready
    var speakerModelReady: Bool { SpeakerRecognizer.shared.isModelReady }

    // MARK: - 发送

    func send() {
        let text = inputText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !isSending else { return }

        // 新会话还没有服务端 session id -> 首次发送时自动生成一个新的。
        if currentSessionId.isEmpty {
            currentSessionId = "ios_" + UUID().uuidString.lowercased().replacingOccurrences(of: "-", with: "")
        }
        // 从第一条用户消息生成标题（类似 DeepSeek）。
        if messages.isEmpty {
            currentTitle = String(text.prefix(30))
        }

        if currentSessionId.isEmpty {
            currentSessionId = "ios_" + UUID().uuidString.lowercased().replacingOccurrences(of: "-", with: "")
        }
        // 从第一条用户消息生成标题（类似 DeepSeek）。
        if messages.isEmpty {
            currentTitle = String(text.prefix(30))
        }
        inputText = ""
        isSending = true
        errorMessage = nil

        let sessionId = currentSessionId
        let speaker = selectedSpeaker
        let userText = Self.prefixSpeaker(speaker, text)
        Task {
            await self.finishSend(userText: userText, sessionId: sessionId, speaker: speaker)
        }
    }
}

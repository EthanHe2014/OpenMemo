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
        // 每次启动都回到「全部锁定」：必须重新说话识别才能解锁
        unlockedSpeaker = nil
        UserDefaults.standard.removeObject(forKey: "siUnlockedSpeaker")
        newSession()          // sets currentSessionId = "" and clears messages
        await refreshSessions()
        currentTitle = "新对话"
    }

    /// 新建聊天（+ 按钮用）：任何时候都能开新对话
    func startNewChat() async {
        newSession()
        await refreshSessions()
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

    // MARK: - 说话人专属会话锁

    /// 房主名字：只有 TA 的专属会话能打开（其它人的会话一律上锁）
    var ownerName: String { UserDefaults.standard.string(forKey: "siOwnerName") ?? "Ethan" }

    /// 当前解锁的说话人（nil = 全部锁定；识别出谁就解锁谁的专属会话）
    var unlockedSpeaker: String? = nil

    /// 该会话是否上锁。规则：
    /// - 已识别出说话人 → 只有 TA 的专属会话解锁，其余全锁
    /// - 未识别（全部锁定）→ 说话人专属会话全锁；匿名会话只留当前正在用的
    func isLockedSession(_ sessionId: String) -> Bool {
        if sessionId.isEmpty { return false }
        if let unlocked = unlockedSpeaker {
            return sessionId != "speaker_\(unlocked)"
        }
        if sessionId.hasPrefix("speaker_") { return true }
        return sessionId != currentSessionId
    }

    /// 当前会话是否被锁
    var isLockedChat: Bool { isLockedSession(currentSessionId) }

    /// 当前锁定会话的说话人名字（非专属会话则为空）
    var lockedSpeakerName: String {
        guard currentSessionId.hasPrefix("speaker_") else { return "" }
        return String(currentSessionId.dropFirst("speaker_".count))
    }

    /// 识别出说话人 → 解锁 TA 的专属会话（任务页也按这个人过滤）
    func unlockSpeaker(_ name: String) {
        unlockedSpeaker = name
        UserDefaults.standard.set(name, forKey: "siUnlockedSpeaker")
        // 通知任务页立即刷新（语音解锁：说一句话即解锁并显示 TA 的任务）
        NotificationCenter.default.post(name: .speakerUnlocked, object: name)
    }

    /// 谁能删除这个会话：只有会话主人（已识别的对应说话人）可以。
    /// 未识别出任何人时，谁都不能删。
    func canDeleteSession(_ sessionId: String) -> Bool {
        guard let unlocked = unlockedSpeaker, !sessionId.isEmpty else { return false }
        if sessionId.hasPrefix("speaker_") {
            return sessionId == "speaker_\(unlocked)"
        }
        // 匿名会话：有已识别的用户在场时允许清理
        return true
    }

    /// 谁能重命名：与删除同规则，只有会话主人可以
    func canRenameSession(_ sessionId: String) -> Bool {
        canDeleteSession(sessionId)
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

    /// 重命名会话（自定义标题）
    func renameSession(_ session: ChatSession, to newTitle: String) async {
        let title = newTitle.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !title.isEmpty else { return }
        do {
            _ = try await api.renameSession(session.sessionId, newTitle: title)
            if let idx = sessions.firstIndex(where: { $0.sessionId == session.sessionId }) {
                sessions[idx].title = title
            }
            if currentSessionId == session.sessionId {
                currentTitle = title
            }
        } catch {
            errorMessage = "重命名失败：\(error.localizedDescription)"
        }
    }

    /// 删除当前会话（导航栏删除按钮用）
    func deleteCurrentChat() async {
        let sid = currentSessionId
        // 只有会话主人能删
        guard canDeleteSession(sid) else { return }
        guard !sid.isEmpty else {
            newSession()
            return
        }
        do {
            _ = try await api.deleteSession(sid)
        } catch {
            errorMessage = "删除失败：\(error.localizedDescription)"
        }
        sessions.removeAll { $0.sessionId == sid }
        newSession()
    }

    /// Send voice message with speaker identification.
    /// 模型就绪 + 有录音数据 → 自动识别说话人（无需手动选）。
    func sendVoice(text: String, audioData: Data?) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !isSending else { return }
        if isLockedChat { return }   // 别人的专属会话不能发消息

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
                // 识别出说话人 → 解锁 TA 的专属会话（其余保持锁定）
                if let sp = finalSpeaker {
                    unlockSpeaker(sp)
                }
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
    /// 说话人已识别 → 路由到该说话人专属会话（speaker_<名字>），
    /// AI 上下文只有这个人的聊天记录，天然隔离隐私。
    private func finishSend(userText: String, sessionId: String, speaker: String? = nil) async {
        var targetSession = sessionId
        if let sp = speaker, !sp.isEmpty {
            let spSession = "speaker_\(sp)"
            if self.currentSessionId != spSession {
                self.currentSessionId = spSession
                self.currentTitle = "\(sp) 的聊天"
                await self.loadSpeakerHistory(spSession)
            }
            targetSession = spSession
        }

        // 展示时去掉 "[名字] " 前缀，speaker 单独存（气泡底部显示）；发给 AI 的仍带前缀
        let displayText = Self.extractSpeaker(from: userText)?.clean ?? userText
        self.messages.append(ChatMessage(role: .user, text: displayText, speaker: speaker))
        defer { self.isSending = false }
        do {
            let reply = try await api.chat(message: userText, sessionId: targetSession, speaker: speaker)
            self.messages.append(ChatMessage(role: .assistant, text: reply))
            await self.refreshSessions()
        } catch {
            self.messages.append(ChatMessage(role: .assistant, text: "连接失败：\(error.localizedDescription)"))
        }
    }

    /// 加载某说话人专属会话的历史（新会话则为空）
    private func loadSpeakerHistory(_ spSession: String) async {
        do {
            let history = try await api.getConversations(sessionId: spSession)
            messages = history.map { msg in
                if msg.role == .user, let parsed = Self.extractSpeaker(from: msg.text) {
                    return ChatMessage(role: .user, text: parsed.clean, speaker: parsed.name)
                }
                return msg
            }
        } catch {
            messages = []
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
        if isLockedChat { return }   // 别人的专属会话不能发消息

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


extension Notification.Name {
    static let speakerUnlocked = Notification.Name("speakerUnlocked")
}

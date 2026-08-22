import Foundation
import SwiftUI

struct ChatMessage: Identifiable, Equatable {
    let id = UUID()
    let role: Role
    let text: String
    /// 说话人（Apple 说话人识别：名字或 "说话人N"）；nil = 未识别
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

    private func loadHistory(sessionId: String) async {
        isLoading = true
        defer { isLoading = false }
        do {
            let history = try await api.getConversations(sessionId: sessionId)
            messages = history
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

    // MARK: - 发送

    /// 发送语音消息：文本 + 说话人识别结果（Apple 本地模型，nil=未识别）
    func sendVoice(text: String, speaker: String?) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        inputText = trimmed
        // 先记下要打的说话人，send() 里 append 后立刻补上
        send()
        if let speaker, let idx = messages.lastIndex(where: { $0.role == .user }) {
            messages[idx].speaker = speaker
        }
    }

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

        messages.append(ChatMessage(role: .user, text: text))
        inputText = ""
        isSending = true
        errorMessage = nil

        let sessionId = currentSessionId
        Task {
            defer { isSending = false }
            do {
                let reply = try await api.chat(message: text, sessionId: sessionId)
                // 只把回复追加到发送时所在的会话；若用户已切走则丢弃，避免串会话
                guard self.currentSessionId == sessionId else { return }
                self.messages.append(ChatMessage(role: .assistant, text: reply))
                // 保持侧边栏最新，让新建/更新的会话出现在顶部。
                await self.refreshSessions()
            } catch {
                guard self.currentSessionId == sessionId else { return }
                self.messages.append(ChatMessage(role: .assistant, text: "连接失败：\(error.localizedDescription)"))
            }
        }
    }
}

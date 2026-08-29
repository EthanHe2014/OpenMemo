import Foundation
import SwiftUI

final class OpenMemoAPI: @unchecked Sendable {
    static let shared = OpenMemoAPI()

    // 服务地址：模拟器用本机直连；真机改为你的隧道/公网地址（设置页可改）
    var baseURL = "http://127.0.0.1:18890"

    /// 无缓存会话：轮询必须拿到最新数据。服务端已返回 Cache-Control: no-store，
    /// 这里再用 reloadIgnoringLocalCacheData 双保险（不能用 ephemeral——Catalyst 上任务会挂起）。

    private let decoder: JSONDecoder = {
        let d = JSONDecoder()
        return d
    }()

    private let encoder = JSONEncoder()

    // MARK: - 健康检查
    func health() async throws -> HealthResponse {
        let (data, _) = try await URLSession.shared.data(from: URL(string: "\(baseURL)/api/health")!)
        return try decoder.decode(HealthResponse.self, from: data)
    }

    // MARK: - 任务
    func listTasks(status: String? = nil, owner: String? = nil) async throws -> TaskListResponse {
        var components = URLComponents(string: "\(baseURL)/api/tasks")!
        var items: [URLQueryItem] = []
        if let status = status {
            items.append(URLQueryItem(name: "status", value: status))
        }
        if let owner = owner {
            items.append(URLQueryItem(name: "owner", value: owner))
        }
        if !items.isEmpty {
            components.queryItems = items
        }
        let (data, _) = try await URLSession.shared.data(from: components.url!)
        return try decoder.decode(TaskListResponse.self, from: data)
    }

    // MARK: - 看护告警
    func listAlerts(afterId: Int = 0) async throws -> AlertListResponse {
        var components = URLComponents(string: "\(baseURL)/api/alerts")!
        components.queryItems = [URLQueryItem(name: "after_id", value: String(afterId))]
        let (data, _) = try await URLSession.shared.data(from: components.url!)
        return try decoder.decode(AlertListResponse.self, from: data)
    }

    // MARK: - 提醒记录（AI 提醒原文）
    func listReminders(afterId: Int = 0) async throws -> ReminderListResponse {
        var components = URLComponents(string: "\(baseURL)/api/reminders")!
        components.queryItems = [URLQueryItem(name: "after_id", value: String(afterId))]
        let (data, _) = try await URLSession.shared.data(from: components.url!)
        return try decoder.decode(ReminderListResponse.self, from: data)
    }

    func getTask(_ id: Int) async throws -> OpenMemoTask {
        let (data, _) = try await URLSession.shared.data(from: URL(string: "\(baseURL)/api/tasks/\(id)")!)
        let resp = try decoder.decode(TaskResponse.self, from: data)
        return resp.task
    }

    func createTask(content: String, triggerTime: String? = nil, priority: String = "medium", isRecurring: String? = nil, notes: String? = nil, owner: String? = nil) async throws -> OpenMemoTask {
        var body: [String: Any?] = [
            "content": content,
            "priority": priority,
            "is_recurring": isRecurring,
            "notes": notes
        ]
        body["trigger_time"] = triggerTime
        body["owner"] = owner
        let jsonData = try JSONSerialization.data(withJSONObject: body.compactMapValues { $0 })
        var req = URLRequest(url: URL(string: "\(baseURL)/api/tasks")!)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = jsonData
        let (data, _) = try await URLSession.shared.data(for: req)
        let resp = try decoder.decode(TaskResponse.self, from: data)
        return resp.task
    }

    func updateTask(_ id: Int, content: String? = nil, triggerTime: String? = nil, priority: String? = nil, status: String? = nil, notes: String? = nil) async throws -> OpenMemoTask {
        var body: [String: Any?] = [:]
        body["content"] = content
        body["trigger_time"] = triggerTime
        body["priority"] = priority
        body["status"] = status
        body["notes"] = notes
        let jsonData = try JSONSerialization.data(withJSONObject: body.compactMapValues { $0 })
        var req = URLRequest(url: URL(string: "\(baseURL)/api/tasks/\(id)")!)
        req.httpMethod = "PATCH"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = jsonData
        let (data, _) = try await URLSession.shared.data(for: req)
        let resp = try decoder.decode(TaskResponse.self, from: data)
        return resp.task
    }

    func deleteTask(_ id: Int) async throws -> Bool {
        var req = URLRequest(url: URL(string: "\(baseURL)/api/tasks/\(id)")!)
        req.httpMethod = "DELETE"
        let (data, _) = try await URLSession.shared.data(for: req)
        let resp = try JSONDecoder().decode([String: Bool].self, from: data)
        return resp["success"] ?? false
    }

    // MARK: - 会话（DeepSeek 风格侧边栏）

    func listSessions() async throws -> [ChatSession] {
        let (data, _) = try await URLSession.shared.data(from: URL(string: "\(baseURL)/api/sessions")!)
        let resp = try decoder.decode(SessionListResponse.self, from: data)
        return resp.sessions
    }

    func deleteSession(_ id: String) async throws -> Bool {
        var req = URLRequest(url: URL(string: "\(baseURL)/api/sessions/\(id)")!)
        req.httpMethod = "DELETE"
        let (data, _) = try await URLSession.shared.data(for: req)
        let resp = try decoder.decode(DeleteSessionResponse.self, from: data)
        return resp.success
    }

    func renameSession(_ id: String, newTitle: String) async throws -> Bool {
        var req = URLRequest(url: URL(string: "\(baseURL)/api/sessions/\(id)")!)
        req.httpMethod = "PATCH"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONEncoder().encode(["title": newTitle])
        let (data, _) = try await URLSession.shared.data(for: req)
        let resp = try decoder.decode(RenameSessionResponse.self, from: data)
        return resp.success
    }

    func getConversations(sessionId: String) async throws -> [ChatMessage] {
        var comps = URLComponents(string: "\(baseURL)/api/conversations/\(sessionId)")!
        comps.queryItems = [URLQueryItem(name: "limit", value: "100")]
        let (data, _) = try await URLSession.shared.data(from: comps.url!)
        let resp = try decoder.decode(ConversationListResponse.self, from: data)
        // 把服务端原始消息转换为 App 消息，映射角色。
        return resp.messages.map { raw in
            let role: ChatMessage.Role = (raw.role == "user") ? .user : .assistant
            return ChatMessage(role: role, text: raw.content)
        }
    }

    // MARK: - 对话
    func chat(message: String, sessionId: String, speaker: String? = nil) async throws -> String {
        // speak: true → 服务端用 Edge TTS（XiaoxiaoNeural）朗读回复，与提醒同声
        let reqBody = ChatRequest(message: message, sessionId: sessionId, speak: true, speaker: speaker)
        let jsonData = try encoder.encode(reqBody)
        var req = URLRequest(url: URL(string: "\(baseURL)/api/chat")!)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = jsonData
        req.timeoutInterval = 30
        let (data, _) = try await URLSession.shared.data(for: req)
        let resp = try decoder.decode(ChatResponse.self, from: data)
        return resp.reply
    }

    /// 立即打断服务端当前语音播放（用户点麦克风录音时调用，防回声）
    func stopSpeak() async {
        var req = URLRequest(url: URL(string: "\(baseURL)/api/stop-speak")!)
        req.httpMethod = "POST"
        req.timeoutInterval = 5
        _ = try? await URLSession.shared.data(for: req)
    }

    /// 服务端 Edge TTS 朗读一段文字（等播放完成才返回，用于唤醒应答"我在！"）
    func speak(_ text: String) async {
        var req = URLRequest(url: URL(string: "\(baseURL)/api/speak")!)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONEncoder().encode(["text": text])
        req.timeoutInterval = 30
        _ = try? await URLSession.shared.data(for: req)
    }
}
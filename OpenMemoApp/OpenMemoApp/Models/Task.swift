import Foundation

struct OpenMemoTask: Identifiable, Codable, Hashable {
    let taskId: Int
    var content: String
    var triggerTime: String?
    var priority: String
    var status: String
    var isRecurring: String?
    var createdAt: String
    var updatedAt: String
    var reminderSent: Int?
    var notes: String?
    var taskType: String?
    var metaData: [String: String]?

    enum CodingKeys: String, CodingKey {
        case taskId = "task_id"
        case content
        case triggerTime = "trigger_time"
        case priority
        case status
        case isRecurring = "is_recurring"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case reminderSent = "reminder_sent"
        case notes
        case taskType = "task_type"
        case metaData = "meta_data"
    }

    /// 宽松解码：meta_data 里混合了字符串和布尔值（如 appointment: true），
    /// 若按 [String: String] 整体解码会抛错、导致整个任务列表加载失败。
    /// 这里把非字符串值丢掉，只保留字符串字段（reminder_text 等）。
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        taskId = try c.decode(Int.self, forKey: .taskId)
        content = try c.decode(String.self, forKey: .content)
        triggerTime = try c.decodeIfPresent(String.self, forKey: .triggerTime)
        priority = try c.decode(String.self, forKey: .priority)
        status = try c.decode(String.self, forKey: .status)
        isRecurring = try c.decodeIfPresent(String.self, forKey: .isRecurring)
        createdAt = try c.decode(String.self, forKey: .createdAt)
        updatedAt = try c.decode(String.self, forKey: .updatedAt)
        reminderSent = try c.decodeIfPresent(Int.self, forKey: .reminderSent)
        notes = try c.decodeIfPresent(String.self, forKey: .notes)
        taskType = try c.decodeIfPresent(String.self, forKey: .taskType)
        if let raw = try? c.decodeIfPresent([String: JSONValue].self, forKey: .metaData) {
            metaData = raw.compactMapValues { $0.stringValue }
        } else {
            metaData = nil
        }
    }

    init(taskId: Int, content: String, triggerTime: String?, priority: String, status: String,
         isRecurring: String?, createdAt: String, updatedAt: String, reminderSent: Int?,
         notes: String?, taskType: String?, metaData: [String: String]?) {
        self.taskId = taskId
        self.content = content
        self.triggerTime = triggerTime
        self.priority = priority
        self.status = status
        self.isRecurring = isRecurring
        self.createdAt = createdAt
        self.updatedAt = updatedAt
        self.reminderSent = reminderSent
        self.notes = notes
        self.taskType = taskType
        self.metaData = metaData
    }

    var id: Int { taskId }

    /// 智能任务类型标签（news/travel/schedule/normal）
    var typeLabel: String {
        switch taskType {
        case "news": return "每日推送"
        case "travel": return "出行"
        case "schedule": return "日程"
        default: return "普通"
        }
    }

    var priorityLevel: PriorityLevel {
        switch priority {
        case "high": return .high
        case "medium": return .medium
        case "low": return .low
        default: return .medium
        }
    }

    var triggerDate: Date? {
        guard let t = triggerTime else { return nil }
        let fmt = ISO8601DateFormatter()
        fmt.formatOptions = [.withFullDate, .withTime]
        return fmt.date(from: t) ?? ISO8601DateFormatter().date(from: t.replacingOccurrences(of: " ", with: "T"))
    }

    var isPending: Bool { status == "pending" }
    var isCompleted: Bool { status == "completed" }
    var isCancelled: Bool { status == "cancelled" }
}

/// 宽松 JSON 值：meta_data 里混合字符串/布尔/数字时用。
private enum JSONValue: Codable, Hashable {
    case string(String)
    case bool(Bool)
    case int(Int)
    case double(Double)
    case object([String: JSONValue])
    case array([JSONValue])
    case null

    var stringValue: String? {
        switch self {
        case .string(let s): return s
        default: return nil
        }
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if let s = try? c.decode(String.self) { self = .string(s) }
        else if let b = try? c.decode(Bool.self) { self = .bool(b) }
        else if let i = try? c.decode(Int.self) { self = .int(i) }
        else if let d = try? c.decode(Double.self) { self = .double(d) }
        else if let o = try? c.decode([String: JSONValue].self) { self = .object(o) }
        else if let a = try? c.decode([JSONValue].self) { self = .array(a) }
        else { self = .null }
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .string(let s): try c.encode(s)
        case .bool(let b): try c.encode(b)
        case .int(let i): try c.encode(i)
        case .double(let d): try c.encode(d)
        case .object(let o): try c.encode(o)
        case .array(let a): try c.encode(a)
        case .null: try c.encodeNil()
        }
    }
}

enum PriorityLevel: String, CaseIterable {
    case high = "high"
    case medium = "medium"
    case low = "low"

    var label: String {
        switch self {
        case .high: return "高"
        case .medium: return "中"
        case .low: return "低"
        }
    }
}

struct TaskListResponse: Codable {
    let tasks: [OpenMemoTask]
    let count: Int
}

struct OpenMemoReminder: Identifiable, Codable, Hashable {
    let reminderId: Int
    let taskId: Int?
    let content: String?
    let message: String
    let createdAt: String?

    var id: Int { reminderId }

    enum CodingKeys: String, CodingKey {
        case reminderId = "reminder_id"
        case taskId = "task_id"
        case content
        case message
        case createdAt = "created_at"
    }
}

struct ReminderListResponse: Codable {
    let reminders: [OpenMemoReminder]
    let count: Int
}

struct OpenMemoAlert: Identifiable, Codable, Hashable {
    let alertId: Int
    let type: String?
    let message: String
    let createdAt: String?

    var id: Int { alertId }

    enum CodingKeys: String, CodingKey {
        case alertId = "alert_id"
        case type
        case message
        case createdAt = "created_at"
    }
}

struct AlertListResponse: Codable {
    let alerts: [OpenMemoAlert]
    let count: Int
}

struct TaskResponse: Codable {
    let task: OpenMemoTask
    let success: Bool
}

struct ChatRequest: Encodable {
    let message: String
    let sessionId: String
    let speak: Bool
    let speaker: String?
    let emotion: String?

    init(message: String, sessionId: String, speak: Bool, speaker: String? = nil, emotion: String? = nil) {
        self.message = message
        self.sessionId = sessionId
        self.speak = speak
        self.speaker = speaker
        self.emotion = emotion
    }

    enum CodingKeys: String, CodingKey {
        case message
        case sessionId = "session_id"
        case speak
        case speaker
    }
}

struct ChatResponse: Codable {
    let reply: String
    let success: Bool
    let action: String?
    let speaker: String?
}

/// 语音情绪识别结果（SenseVoice）
struct EmotionResponse: Codable {
    let text: String
    let emotion: String
    let language: String?
}

/// 聊天结果：回复文本 + 可能的用户切换信号（仅白名单用户 test 会带）
struct ChatResult {
    let reply: String
    let action: String?
    let speaker: String?
}

// MARK: - 会话（DeepSeek 风格侧边栏）

struct ChatSession: Identifiable, Codable, Hashable {
    let sessionId: String
    var title: String
    let lastAt: String?
    let msgCount: Int?

    var id: String { sessionId }

    /// 简短的可显示标签（标题为空/null 时的兜底）。
    var displayTitle: String {
        let t = title.trimmingCharacters(in: .whitespacesAndNewlines)
        return t.isEmpty ? "新对话" : t
    }

    enum CodingKeys: String, CodingKey {
        case sessionId = "session_id"
        case title
        case lastAt = "last_at"
        case msgCount = "msg_count"
    }
}

struct SessionListResponse: Codable {
    let sessions: [ChatSession]
    let count: Int
}

struct RawConversationMessage: Codable {
    let role: String
    let content: String
    let createdAt: String?

    enum CodingKeys: String, CodingKey {
        case role, content
        case createdAt = "created_at"
    }
}

struct ConversationListResponse: Codable {
    let messages: [RawConversationMessage]
    let count: Int
}

struct DeleteSessionResponse: Codable {
    let success: Bool
    let deleted: String
}

struct RenameSessionResponse: Codable {
    let success: Bool
}

struct HealthResponse: Codable {
    let name: String
    let version: String
    let status: String
    let model: String?
}
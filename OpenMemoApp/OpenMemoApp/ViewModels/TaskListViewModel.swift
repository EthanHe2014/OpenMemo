import Foundation
import SwiftUI
@MainActor
@Observable
final class TaskListViewModel {
    var tasks: [OpenMemoTask] = []
    var isLoading = false
    var errorMessage: String?
    var latestReminder: OpenMemoReminder?
    private var lastSeenReminderId = 0
    private var hasLoadedReminders = false

    private let api = OpenMemoAPI.shared
    private var pollTimer: Timer?

    /// 启动 15 秒轮询（任务 + 提醒横幅）。ViewModel 自持 Timer，避免 SwiftUI .task 被取消的问题。
    func startPolling() {
        guard pollTimer == nil else { return }
        pollTimer = Timer.scheduledTimer(withTimeInterval: 15, repeats: true) { [weak self] _ in
            Task { @MainActor [weak self] in
                await self?.load()
            }
        }
    }

    func stopPolling() {
        pollTimer?.invalidate()
        pollTimer = nil
    }

    func load() async {
        isLoading = true
        errorMessage = nil
        do {
            let resp = try await api.listTasks()
            self.tasks = resp.tasks
            await pollReminders()   // 先轮询提醒（横幅）——不被本地通知同步阻塞
            // 本地通知同步放后台做，个别平台（Catalyst）add 请求可能挂起，不能卡轮询
            let taskList = resp.tasks
            Task { await LocalNotificationManager.shared.syncNotifications(for: taskList) }
            self.isLoading = false
        } catch {
            self.errorMessage = error.localizedDescription
            self.isLoading = false
        }
    }

    /// 轮询已触发的提醒（AI 提醒原文），有新提醒就亮横幅。
    /// 首次加载只记录游标，不弹历史提醒；之后每次发现新提醒才弹。
    func pollReminders() async {
        do {
            let resp = try await api.listReminders(afterId: lastSeenReminderId)
            let newestFirst = resp.reminders
            guard !newestFirst.isEmpty else { return }
            let newest = newestFirst.max(by: { $0.reminderId < $1.reminderId })!
            lastSeenReminderId = newest.reminderId
            if hasLoadedReminders {
                // 只弹最新一条，避免刷屏
                latestReminder = newest
            } else {
                hasLoadedReminders = true
            }
        } catch {
        }
    }

    func add(content: String, triggerTime: String?, priority: String, notes: String?) async {
        do {
            _ = try await api.createTask(content: content, triggerTime: triggerTime, priority: priority, notes: notes)
            await load()
        } catch {
            self.errorMessage = error.localizedDescription
        }
    }

    func toggleComplete(_ task: OpenMemoTask) async {
        let newStatus = task.isCompleted ? "pending" : "completed"
        do {
            _ = try await api.updateTask(task.taskId, status: newStatus)
            await load()
        } catch {
            self.errorMessage = error.localizedDescription
        }
    }

    func delete(_ task: OpenMemoTask) async {
        do {
            _ = try await api.deleteTask(task.taskId)
            await load()
        } catch {
            self.errorMessage = error.localizedDescription
        }
    }
}
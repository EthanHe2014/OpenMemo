import Foundation
import UserNotifications

/// iOS 本地通知管理器。
/// 服务端（Mac）负责语音提醒，App 端同时在本机调度一条本地通知，
/// 这样即使用户不在 Mac 附近，手机上也会在提醒时间弹出通知。
@MainActor
final class LocalNotificationManager {
    static let shared = LocalNotificationManager()
    private let center = UNUserNotificationCenter.current()

    private init() {}

    /// 申请通知权限。应在 App 启动时调用一次。
    func requestAuthorization() async {
        do {
            _ = try await center.requestAuthorization(options: [.alert, .sound, .badge])
        } catch {
            print("[本地通知] 申请权限失败：\(error.localizedDescription)")
        }
    }

    /// 让本地通知与任务列表保持一致：
    /// - 对每个「待办且提醒时间在未来」的任务调度一条本地通知；
    /// - 对已完成 / 已取消 / 时间已过的任务取消对应通知。
    /// 采用替换式同步：先按本 App 已知任务 ID 清理，再重新调度，避免重复。
    func syncNotifications(for tasks: [OpenMemoTask]) async {
        let now = Date()

        // 收集当前需要生效的任务 ID
        var activeIDs = Set<Int>()
        for task in tasks where task.isPending {
            guard let date = task.triggerDate else { continue }
            guard date > now else { continue }   // 已过时间不排本地通知
            activeIDs.insert(task.taskId)
            await schedule(task, at: date)
        }

        // 其余已知任务（已完成/已取消/已过期）取消其本地通知
        let toCancel = tasks.map(\.taskId).filter { !activeIDs.contains($0) }
        for id in toCancel {
            cancel(id)
        }
    }

    /// 为单个任务调度本地通知。
    private func schedule(_ task: OpenMemoTask, at date: Date) async {
        let content = UNMutableNotificationContent()
        content.title = "\(task.typeLabel) · \(task.content)"
        // 优先用 AI 写的 reminder_text 作为正文，缺失则回退到任务内容。
        let reminderText = task.metaData?["reminder_text"]?.trimmingCharacters(in: .whitespacesAndNewlines)
        content.body = (reminderText?.isEmpty == false) ? reminderText! : "该做「\(task.content)」啦"
        content.sound = .default

        let comps = Calendar.current.dateComponents([.year, .month, .day, .hour, .minute], from: date)
        let trigger = UNCalendarNotificationTrigger(dateMatching: comps, repeats: false)
        let request = UNNotificationRequest(identifier: identifier(for: task.taskId), content: content, trigger: trigger)

        do {
            try await center.add(request)
        } catch {
            print("[本地通知] 调度失败 task#\(task.taskId)：\(error.localizedDescription)")
        }
    }

    /// 取消某个任务对应的本地通知（完成后/删除后/时间过）。重复触发无副作用。
    func cancel(_ taskId: Int) {
        center.removePendingNotificationRequests(withIdentifiers: [identifier(for: taskId)])
    }

    /// 任务 ID -> 通知唯一标识。
    private func identifier(for taskId: Int) -> String {
        "openmemo_task_\(taskId)"
    }
}

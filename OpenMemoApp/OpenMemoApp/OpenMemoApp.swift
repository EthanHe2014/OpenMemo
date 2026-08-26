import SwiftUI

@main
struct OpenMemoApp: App {
    @State private var taskVM = TaskListViewModel()
    @State private var chatVM = ChatViewModel()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environment(taskVM)
                .environment(chatVM)
        }
    }
}

struct ContentView: View {
    @Environment(TaskListViewModel.self) private var taskVM
    @State private var reminderBannerVisible = false
    @State private var alertBannerVisible = false

    var body: some View {
        MainContainerView()
        .task { // 先加载 + 启动轮询（不等权限弹窗，弹窗可能一直挂着）；权限申请并行进行
            taskVM.startPolling()
            await taskVM.load()
            Task { await LocalNotificationManager.shared.requestAuthorization() }
        }
        .overlay(alignment: .top) {
            if alertBannerVisible, let a = taskVM.latestAlert {
                AlertBannerView(alert: a) {
                    withAnimation { alertBannerVisible = false }
                }
                .transition(.move(edge: .top).combined(with: .opacity))
            } else if reminderBannerVisible, let r = taskVM.latestReminder {
                ReminderBannerView(reminder: r) {
                    withAnimation { reminderBannerVisible = false }
                }
                .transition(.move(edge: .top).combined(with: .opacity))
            }
        }
        .onChange(of: taskVM.latestReminder) { _, newValue in
            guard newValue != nil else { return }
            withAnimation { reminderBannerVisible = true }
            // 6 秒后自动收起
            Task {
                try? await Task.sleep(for: .seconds(6))
                withAnimation { reminderBannerVisible = false }
            }
        }
        .onChange(of: taskVM.latestAlert) { _, newValue in
            guard newValue != nil else { return }
            withAnimation { alertBannerVisible = true }
            // 8 秒后自动收起
            Task {
                try? await Task.sleep(for: .seconds(8))
                withAnimation { alertBannerVisible = false }
            }
        }
    }
}

/// 顶部看护告警横幅：watchdog 发现问题/自动处理时显示
struct AlertBannerView: View {
    let alert: OpenMemoAlert
    let onDismiss: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: alert.type == "autofix" ? "wrench.and.screwdriver.fill" : "exclamationmark.triangle.fill")
                .font(.title2)
                .foregroundStyle(.orange)
            VStack(alignment: .leading, spacing: 2) {
                Text(alert.type == "autofix" ? "看护 · 已自动处理" : "看护 · 发现问题")
                    .font(.caption)
                    .foregroundStyle(.orange)
                Text(alert.message)
                    .font(.subheadline)
                    .lineLimit(3)
            }
            Spacer(minLength: 0)
            Button(action: onDismiss) {
                Image(systemName: "xmark")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(14)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(Color.orange.opacity(0.4)))
        .shadow(radius: 8)
        .padding(.horizontal, 12)
        .padding(.top, 6)
    }
}

/// 顶部提醒横幅：显示 AI 生成的提醒原文
struct ReminderBannerView: View {
    let reminder: OpenMemoReminder
    let onDismiss: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "bell.badge.fill")
                .font(.title2)
                .foregroundStyle(.orange)
            VStack(alignment: .leading, spacing: 2) {
                Text("⏰ 提醒")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Text(reminder.message)
                    .font(.subheadline)
                    .lineLimit(3)
            }
            Spacer(minLength: 0)
            Button(action: onDismiss) {
                Image(systemName: "xmark")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(14)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(Color.orange.opacity(0.3)))
        .shadow(radius: 8)
        .padding(.horizontal, 12)
        .padding(.top, 6)
    }
}

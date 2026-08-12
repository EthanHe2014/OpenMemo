import SwiftUI

struct TaskListView: View {
    @Environment(TaskListViewModel.self) private var taskVM
    @State private var filterStatus: String? = nil

    var body: some View {
        NavigationStack {
            Group {
                if taskVM.isLoading && taskVM.tasks.isEmpty {
                    ProgressView("加载中...")
                } else if let error = taskVM.errorMessage {
                    VStack(spacing: 16) {
                        Image(systemName: "wifi.slash")
                            .font(.system(size: 48))
                            .foregroundStyle(.secondary)
                        Text("连接失败")
                            .font(.headline)
                        Text(error)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .multilineTextAlignment(.center)
                        Button("重试") { Task { await taskVM.load() } }
                            .buttonStyle(.bordered)
                    }
                    .padding()
                } else if taskVM.tasks.isEmpty {
                    ContentUnavailableView(
                        "暂无任务",
                        systemImage: "checklist",
                        description: Text("直接跟 OpenMemo 说，它就会帮你记下来")
                    )
                } else {
                    taskList
                }
            }
            .navigationTitle("任务")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    filterMenu
                }
            }
        }
        .task {
            await taskVM.load()
        }
    }

    // MARK: - 分组列表

    private var taskList: some View {
        List {
            // 顶部统计卡片
            Section {
                summaryCard
                    .listRowInsets(EdgeInsets())
                    .listRowBackground(Color.clear)
            }

            if filterStatus == nil {
                statusSection(title: "待办", status: "pending", icon: "clock", color: .orange)
                statusSection(title: "已完成", status: "completed", icon: "checkmark.circle.fill", color: .green)
                statusSection(title: "已取消", status: "cancelled", icon: "xmark.circle", color: .gray)
            } else {
                let tasks = taskVM.tasks.filter { $0.status == filterStatus }
                if tasks.isEmpty {
                    ContentUnavailableView("没有这类任务", systemImage: "tray", description: Text("换个筛选看看"))
                } else {
                    Section {
                        ForEach(tasks) { task in
                            row(for: task)
                        }
                    }
                }
            }
        }
        .listStyle(.insetGrouped)
        .refreshable {
            await taskVM.load()
        }
    }

    private func statusSection(title: String, status: String, icon: String, color: Color) -> some View {
        let tasks = taskVM.tasks.filter { $0.status == status }
        if tasks.isEmpty { return AnyView(EmptyView()) }
        return AnyView(
            Section {
                ForEach(tasks) { task in
                    row(for: task)
                }
            } header: {
                HStack(spacing: 6) {
                    Image(systemName: icon)
                        .foregroundStyle(color)
                    Text("\(title) · \(tasks.count)")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
            }
        )
    }

    private func row(for task: OpenMemoTask) -> some View {
        NavigationLink(destination: TaskDetailView(task: task)) {
            TaskRowView(task: task) {
                Task { await taskVM.toggleComplete(task) }
            }
        }
        .swipeActions(edge: .trailing, allowsFullSwipe: true) {
            Button(role: .destructive) {
                Task { await taskVM.delete(task) }
            } label: {
                Label("删除", systemImage: "trash")
            }
        }
    }

    // MARK: - 统计卡片

    private var summaryCard: some View {
        let pending = taskVM.tasks.filter(\.isPending).count
        let completed = taskVM.tasks.filter(\.isCompleted).count
        let today = taskVM.tasks.filter { task in
            guard let t = task.triggerTime, let d = TaskListHelpers.parseTime(t) else { return false }
            return Calendar.current.isDateInToday(d) && task.isPending
        }.count

        return HStack(spacing: 0) {
            statBlock(value: pending, label: "待办", color: .orange, icon: "clock")
            statDivider
            statBlock(value: today, label: "今日提醒", color: .red, icon: "bell")
            statDivider
            statBlock(value: completed, label: "已完成", color: .green, icon: "checkmark.circle.fill")
        }
        .padding(.vertical, 14)
        .background(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .fill(Color(.secondarySystemGroupedBackground))
                .shadow(color: .black.opacity(0.06), radius: 6, y: 2)
        )
        .padding(.horizontal, 16)
        .padding(.vertical, 6)
    }

    private var statDivider: some View {
        Rectangle()
            .fill(Color(.separator).opacity(0.5))
            .frame(width: 0.5, height: 30)
    }

    private func statBlock(value: Int, label: String, color: Color, icon: String) -> some View {
        VStack(spacing: 4) {
            HStack(spacing: 4) {
                Image(systemName: icon)
                    .font(.caption)
                    .foregroundStyle(color)
                Text("\(value)")
                    .font(.title3.bold())
                    .foregroundStyle(.primary)
            }
            Text(label)
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
    }

    // MARK: - 筛选菜单

    private var filterMenu: some View {
        Menu {
            filterButton("全部", status: nil)
            filterButton("待办", status: "pending")
            filterButton("已完成", status: "completed")
            filterButton("已取消", status: "cancelled")
        } label: {
            Image(systemName: filterStatus == nil ? "line.3.horizontal.decrease.circle" : "line.3.horizontal.decrease.circle.fill")
        }
    }

    private func filterButton(_ title: String, status: String?) -> some View {
        Button {
            filterStatus = status
        } label: {
            if filterStatus == status {
                Label(title, systemImage: "checkmark")
            } else {
                Text(title)
            }
        }
    }
}

// MARK: - 时间解析辅助

enum TaskListHelpers {
    static func parseTime(_ s: String) -> Date? {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd HH:mm"
        f.locale = Locale(identifier: "zh_CN")
        return f.date(from: s)
    }

    /// 相对时间："今天 15:00" / "明天 08:00" / "周三 09:00" / "8月20日 10:00"
    static func relativeTime(_ s: String) -> String {
        guard let d = parseTime(s) else { return s }
        let cal = Calendar.current
        let hm = String(s.suffix(5))
        let weekdays = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"]
        if cal.isDateInToday(d) { return "今天 \(hm)" }
        if cal.isDateInTomorrow(d) { return "明天 \(hm)" }
        if cal.isDateInYesterday(d) { return "昨天 \(hm)" }
        let dayDiff = cal.dateComponents([.day], from: cal.startOfDay(for: Date()), to: cal.startOfDay(for: d)).day ?? 99
        if dayDiff > 0 && dayDiff <= 6 {
            let w = cal.component(.weekday, from: d)
            return "\(weekdays[w - 1]) \(hm)"
        }
        let m = cal.component(.month, from: d)
        let day = cal.component(.day, from: d)
        return "\(m)月\(day)日 \(hm)"
    }
}

// MARK: - 任务行

struct TaskRowView: View {
    let task: OpenMemoTask
    var onToggle: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            statusIcon

            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 6) {
                    Text(task.content)
                        .font(.body.weight(task.isPending ? .medium : .regular))
                        .strikethrough(task.isCompleted)
                        .foregroundStyle(task.isCompleted ? .secondary : .primary)
                        .lineLimit(1)
                    if task.isCompleted {
                        badge("已完成", color: .green)
                    }
                    if task.isCancelled {
                        badge("已取消", color: .gray)
                    }
                }

                HStack(spacing: 10) {
                    if let time = task.triggerTime {
                        Label(TaskListHelpers.relativeTime(time), systemImage: "clock")
                            .font(.caption)
                            .foregroundStyle(timeColor(time))
                    }
                    if let rec = task.isRecurring, !rec.isEmpty {
                        Label(recurringLabel(rec), systemImage: "repeat")
                            .font(.caption)
                            .foregroundStyle(.orange)
                    }
                }
            }

            Spacer(minLength: 4)

            Button(action: onToggle) {
                Image(systemName: checkboxImage)
                    .font(.title3)
                    .foregroundStyle(checkboxColor)
                    .frame(width: 32, height: 32)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .disabled(task.isCancelled)
        }
        .opacity(task.isCancelled ? 0.5 : 1)
        .padding(.vertical, 3)
    }

    private func timeColor(_ time: String) -> Color {
        guard task.isPending, let d = TaskListHelpers.parseTime(time) else { return .secondary }
        if d < Date() { return .red.opacity(0.8) }   // 已过期
        if Calendar.current.isDateInToday(d) { return .primary.opacity(0.7) }
        return .secondary
    }

    @ViewBuilder
    private var statusIcon: some View {
        Group {
            if task.isCompleted {
                Image(systemName: "checkmark.circle.fill")
                    .font(.body)
                    .foregroundStyle(.green)
            } else if task.isCancelled {
                Image(systemName: "circle.slash")
                    .foregroundStyle(.gray)
            } else {
                Circle()
                    .fill(priorityColor)
                    .frame(width: 10, height: 10)
            }
        }
        .frame(width: 24)
    }

    private var checkboxImage: String {
        if task.isCompleted { return "checkmark.circle.fill" }
        if task.isCancelled { return "circle.dashed" }
        return "circle"
    }

    private var checkboxColor: Color {
        if task.isCompleted { return .green }
        if task.isCancelled { return .gray }
        return .secondary
    }

    private func badge(_ text: String, color: Color) -> some View {
        Text(text)
            .font(.caption2)
            .padding(.horizontal, 6)
            .padding(.vertical, 1)
            .background(color.opacity(0.15), in: Capsule())
            .foregroundStyle(color)
    }

    private func recurringLabel(_ rec: String) -> String {
        switch rec.lowercased() {
        case "每天", "daily": return "每天"
        case "工作日", "weekday": return "工作日"
        default: return rec
        }
    }

    private var priorityColor: Color {
        switch task.priority {
        case "high": return .red
        case "medium": return .orange
        case "low": return .green
        default: return .gray
        }
    }
}

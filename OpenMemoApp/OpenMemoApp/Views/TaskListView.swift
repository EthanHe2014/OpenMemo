import SwiftUI

struct TaskListView: View {
    @Environment(TaskListViewModel.self) private var taskVM
    @State private var filterStatus: String? = nil

    var filteredTasks: [OpenMemoTask] {
        if let status = filterStatus {
            return taskVM.tasks.filter { $0.status == status }
        }
        return taskVM.tasks
    }

    private var pendingCount: Int {
        taskVM.tasks.filter { $0.isPending }.count
    }

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
                    List {
                        Section {
                            ForEach(filteredTasks) { task in
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
                        } header: {
                            if filterStatus == nil && pendingCount > 0 {
                                Text("待办 \(pendingCount)")
                            }
                        }
                    }
                    .listStyle(.insetGrouped)
                    .refreshable {
                        await taskVM.load()
                    }
                }
            }
            .navigationTitle("任务")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Menu {
                        Button {
                            filterStatus = nil
                        } label: {
                            if filterStatus == nil { Label("全部", systemImage: "checkmark") } else { Text("全部") }
                        }
                        Button {
                            filterStatus = "pending"
                        } label: {
                            if filterStatus == "pending" { Label("待办", systemImage: "checkmark") } else { Text("待办") }
                        }
                        Button {
                            filterStatus = "executed"
                        } label: {
                            if filterStatus == "executed" { Label("已执行", systemImage: "checkmark") } else { Text("已执行") }
                        }
                        Button {
                            filterStatus = "completed"
                        } label: {
                            if filterStatus == "completed" { Label("已完成", systemImage: "checkmark") } else { Text("已完成") }
                        }
                        Button {
                            filterStatus = "cancelled"
                        } label: {
                            if filterStatus == "cancelled" { Label("已取消", systemImage: "checkmark") } else { Text("已取消") }
                        }
                    } label: {
                        Image(systemName: "line.3.horizontal.decrease.circle")
                    }
                }
            }
        }
        .task {
            await taskVM.load()
        }
    }
}

struct TaskRowView: View {
    let task: OpenMemoTask
    var onToggle: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            // 状态图标
            statusIcon

            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 6) {
                    Text(task.content)
                        .font(.body)
                        .strikethrough(task.isCompleted)
                        .foregroundStyle(task.isCompleted || task.isExecuted ? .secondary : .primary)
                        .lineLimit(1)
                    if task.isExecuted {
                        badge("已执行", color: .green)
                    }
                    if task.isCompleted {
                        badge("已完成", color: .blue)
                    }
                    if task.isCancelled {
                        badge("已取消", color: .gray)
                    }
                }

                HStack(spacing: 10) {
                    if let time = task.triggerTime {
                        Label(time, systemImage: "clock")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    if let rec = task.isRecurring, !rec.isEmpty {
                        Label(recurringLabel(rec), systemImage: "repeat")
                            .font(.caption)
                            .foregroundStyle(.orange)
                    }
                }
            }

            Spacer(minLength: 4)

            // 末尾复选框：点击切换 完成/待办
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
        .padding(.vertical, 2)
    }

    // MARK: - 状态图标

    @ViewBuilder
    private var statusIcon: some View {
        Group {
            if task.isExecuted || task.isCompleted {
                Image(systemName: "checkmark.circle.fill")
                    .foregroundStyle(task.isExecuted ? .green : .blue)
            } else if task.isCancelled {
                Image(systemName: "circle.slash")
                    .foregroundStyle(.gray)
            } else {
                Circle()
                    .fill(priorityColor)
                    .frame(width: 10, height: 10)
            }
        }
        .frame(width: 22)
    }

    // MARK: - 复选框

    private var checkboxImage: String {
        if task.isCompleted || task.isExecuted {
            return "checkmark.circle.fill"
        }
        if task.isCancelled {
            return "circle.dashed"
        }
        return "circle"
    }

    private var checkboxColor: Color {
        if task.isCompleted || task.isExecuted { return .green }
        if task.isCancelled { return .gray }
        return .secondary
    }

    // MARK: - 辅助

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
